# baseten_key_env.sh — sourceable snippet (not executable).
#
# Fills LLM_API_KEY / BASETEN_API_KEY from the OS keychain at runtime.
# No-op unless the key is missing AND the target is a Baseten endpoint,
# so local Mirai/Uzu runs (LLM_API_KEY=dummy) never touch the keychain.
# Expects ROOT_DIR to point at the repo root (set by the sourcing script).
if [ -z "${LLM_API_KEY:-}" ] && [[ "${LLM_API_BASE:-}" == *"baseten"* ]]; then
    _BARRED_KEYRING_KEY="$(python3 "$ROOT_DIR/scripts/baseten_key.py" 2>/dev/null || true)"
    if [ -n "${_BARRED_KEYRING_KEY:-}" ]; then
        export LLM_API_KEY="$_BARRED_KEYRING_KEY"
        export BASETEN_API_KEY="$_BARRED_KEYRING_KEY"
    fi
    unset _BARRED_KEYRING_KEY
fi
