"""Runtime resolution of the Baseten API key (stdlib only).

Precedence:
1. ``BASETEN_API_KEY`` environment variable — explicit always wins.
2. OS keyring, looked up only when the env var is empty:
   - macOS Keychain via the ``security`` CLI (no extra dependency).
   - The Python ``keyring`` package when installed (Linux/Windows).
3. ``""`` when nothing is configured. Callers keep working for local
   ``LLM_API_KEY=dummy`` endpoints; only Baseten runs need the key.

The keychain item defaults to service ``barred-baseten`` / account
``api_key``. Override with ``BASETEN_KEYRING_SERVICE`` /
``BASETEN_KEYRING_ACCOUNT``. Store it once with::

    security add-generic-password -U -s barred-baseten -a api_key -w

Nothing here ever raises: a missing CLI, a missing item, or a denied
lookup all resolve to ``""``.
"""
from __future__ import annotations

import os
import shutil
import subprocess

SERVICE_ENV = "BASETEN_KEYRING_SERVICE"
ACCOUNT_ENV = "BASETEN_KEYRING_ACCOUNT"
DEFAULT_SERVICE = "barred-baseten"
DEFAULT_ACCOUNT = "api_key"


def keyring_id() -> tuple[str, str]:
    """(service, account) identifying the keychain item."""
    return (
        os.getenv(SERVICE_ENV, DEFAULT_SERVICE),
        os.getenv(ACCOUNT_ENV, DEFAULT_ACCOUNT),
    )


def _from_security_cli(service: str, account: str) -> str:
    exe = shutil.which("security")
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _from_python_keyring(service: str, account: str) -> str:
    try:
        import keyring  # type: ignore
    except ImportError:
        return ""
    try:
        return keyring.get_password(service, account) or ""
    except Exception:
        return ""


def resolve_baseten_key() -> str:
    """Return the Baseten API key, or ``""`` when none is configured."""
    env_key = (os.getenv("BASETEN_API_KEY") or "").strip()
    if env_key:
        return env_key
    service, account = keyring_id()
    return _from_security_cli(service, account) or _from_python_keyring(
        service, account
    )


def resolve_baseten_key_source() -> str:
    """Name where the key would come from, without revealing it."""
    if (os.getenv("BASETEN_API_KEY") or "").strip():
        return "env:BASETEN_API_KEY"
    service, account = keyring_id()
    if _from_security_cli(service, account):
        return f"os-keychain:{service}/{account}"
    if _from_python_keyring(service, account):
        return f"python-keyring:{service}/{account}"
    return "none"


def fill_baseten_key(env: dict) -> bool:
    """Fill an empty ``OPENAI_API_KEY`` for Baseten runs.

    Returns True when a key was filled. Local endpoints (Mirai/Uzu with
    ``LLM_API_KEY=dummy``) always return False without consulting the
    keychain, so they can never trigger an OS access prompt.
    """
    if env.get("OPENAI_API_KEY"):
        return False
    if "baseten" not in (env.get("OPENAI_API_BASE") or ""):
        return False
    key = resolve_baseten_key()
    if not key:
        return False
    env["OPENAI_API_KEY"] = key
    return True
