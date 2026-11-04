#!/usr/bin/env python3
"""Print the Baseten API key resolved at runtime (env var > OS keychain).

Used for command substitution so the key never lives in shell history::

    docker run -e BASETEN_API_KEY="$(python3 scripts/baseten_key.py)" ...

``--status`` prints where the key would come from without revealing it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from barred_keys import resolve_baseten_key, resolve_baseten_key_source


def main(argv: list[str]) -> int:
    if "--status" in argv or "--check" in argv:
        source = resolve_baseten_key_source()
        print(source)
        return 0 if source != "none" else 1
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    sys.stdout.write(resolve_baseten_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
