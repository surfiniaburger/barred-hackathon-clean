"""Runtime Baseten key resolution: env var wins, else OS keychain, else ""."""

import os
import subprocess
import sys
from pathlib import Path

import barred_keys
from barred_keys import (
    fill_baseten_key,
    resolve_baseten_key,
    resolve_baseten_key_source,
)

ROOT = Path(__file__).resolve().parent.parent
SNIPPET = ROOT / "scripts" / "baseten_key_env.sh"

MIRAI_BASE = "http://127.0.0.1:8123/v1"
BASETEN_BASE = "https://inference.baseten.co/v1"

# A service name guaranteed absent from any real keychain, so tests never
# touch (or prompt for) a genuine credential.
MISSING_SERVICE = "barred-baseten-test-definitely-missing"


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "env-key-123")
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    assert resolve_baseten_key() == "env-key-123"
    assert resolve_baseten_key_source() == "env:BASETEN_API_KEY"


def test_env_var_whitespace_treated_as_missing(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "   ")
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    assert resolve_baseten_key() == ""
    assert resolve_baseten_key_source() == "none"


def test_missing_everywhere_resolves_empty_without_raising(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    assert resolve_baseten_key() == ""
    assert resolve_baseten_key_source() == "none"


def test_custom_keyring_id_from_env(monkeypatch):
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", "my-service")
    monkeypatch.setenv("BASETEN_KEYRING_ACCOUNT", "my-account")
    assert barred_keys.keyring_id() == ("my-service", "my-account")


def test_security_cli_absent_resolves_empty(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    monkeypatch.setattr(barred_keys.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        barred_keys, "_from_python_keyring", lambda service, account: ""
    )
    assert resolve_baseten_key() == ""


def test_python_keyring_fallback_used_when_security_misses(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setattr(barred_keys, "_from_security_cli", lambda s, a: "")
    monkeypatch.setattr(
        barred_keys, "_from_python_keyring", lambda s, a: "fallback-key"
    )
    assert resolve_baseten_key() == "fallback-key"


def test_cli_prints_key_for_substitution(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "cli-key-abc")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "baseten_key.py")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout == "cli-key-abc"


def test_cli_status_reports_source_without_revealing(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "super-secret-value")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "baseten_key.py"), "--status"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "env:BASETEN_API_KEY"
    assert "super-secret" not in proc.stdout


def test_cli_status_exit_1_when_no_key(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "baseten_key.py"), "--status"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == "none"


# --- Local-endpoint (Mirai/Uzu) isolation: the keychain must never be
# consulted for non-Baseten runs, so local flows can't regress or prompt.


def _block_keychain(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("keychain consulted for a local run")

    monkeypatch.setattr(barred_keys, "resolve_baseten_key", _boom)


def test_fill_skips_local_dummy_run_without_consulting_keychain(monkeypatch):
    _block_keychain(monkeypatch)
    env = {"OPENAI_API_BASE": MIRAI_BASE, "OPENAI_API_KEY": "dummy"}
    assert fill_baseten_key(env) is False
    assert env == {"OPENAI_API_BASE": MIRAI_BASE, "OPENAI_API_KEY": "dummy"}


def test_fill_skips_local_run_with_empty_key(monkeypatch):
    _block_keychain(monkeypatch)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    env = {"OPENAI_API_BASE": MIRAI_BASE, "OPENAI_API_KEY": ""}
    assert fill_baseten_key(env) is False
    assert env["OPENAI_API_KEY"] == ""


def test_fill_skips_baseten_run_with_key_already_set(monkeypatch):
    _block_keychain(monkeypatch)
    env = {"OPENAI_API_BASE": BASETEN_BASE, "OPENAI_API_KEY": "dummy"}
    assert fill_baseten_key(env) is False
    assert env["OPENAI_API_KEY"] == "dummy"


def test_fill_fills_empty_baseten_run_from_env(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "env-key-123")
    env = {"OPENAI_API_BASE": BASETEN_BASE, "OPENAI_API_KEY": ""}
    assert fill_baseten_key(env) is True
    assert env["OPENAI_API_KEY"] == "env-key-123"


def test_fill_empty_baseten_run_with_no_key_stays_empty(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("BASETEN_KEYRING_SERVICE", MISSING_SERVICE)
    env = {"OPENAI_API_BASE": BASETEN_BASE}
    assert fill_baseten_key(env) is False
    assert "OPENAI_API_KEY" not in env


def _run_startup_snippet(base: str, key: str | None, stub_dir: Path) -> tuple[str, bool]:
    """Source the real start.sh snippet under a stubbed python3.

    Returns (shell output, whether the keychain path ran). The stub records
    invocation in a marker file because the snippet redirects stderr away.
    """
    marker = stub_dir / "keychain_consulted"
    stub = stub_dir / "python3"
    stub.write_text(
        f'#!/usr/bin/env bash\ntouch "{marker}"\nexit 3\n'
    )
    stub.chmod(0o755)
    if key is None:
        key_setup = "unset LLM_API_KEY"
    else:
        key_setup = f'export LLM_API_KEY="{key}"'
    script = (
        f'ROOT_DIR="{ROOT}"; export LLM_API_BASE="{base}"; {key_setup}; '
        f'. "{SNIPPET}"; '
        'echo "LLM=[${LLM_API_KEY:-__EMPTY__}] BASETEN=[${BASETEN_API_KEY:-__EMPTY__}]"'
    )
    env = {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "BASETEN_KEYRING_SERVICE": MISSING_SERVICE,
    }
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30, env=env
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip(), marker.exists()


def test_startup_snippet_ignores_local_mirai_run(tmp_path):
    out, consulted = _run_startup_snippet(MIRAI_BASE, "dummy", tmp_path)
    assert consulted is False
    assert out == "LLM=[dummy] BASETEN=[__EMPTY__]"


def test_startup_snippet_ignores_local_run_with_empty_key(tmp_path):
    out, consulted = _run_startup_snippet(MIRAI_BASE, "", tmp_path)
    assert consulted is False
    assert out == "LLM=[__EMPTY__] BASETEN=[__EMPTY__]"


def test_startup_snippet_consults_keychain_for_baseten_run(tmp_path):
    # Positive control: proves the stub detects consultation when it happens.
    out, consulted = _run_startup_snippet(BASETEN_BASE, "", tmp_path)
    assert consulted is True
    assert out == "LLM=[__EMPTY__] BASETEN=[__EMPTY__]"


def test_startup_snippet_is_sourced_by_start_sh():
    assert '. "$ROOT_DIR/scripts/baseten_key_env.sh"' in (
        ROOT / "start.sh"
    ).read_text()
