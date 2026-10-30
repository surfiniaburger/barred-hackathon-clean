#!/usr/bin/env bash
# bootstrap.sh — fetch pre-event foundation and apply hackathon patches
set -euo pipefail

BASE_COMMIT="7218e2d17fbab6de69a1ef6ff3c9cebf10089e83"
FOUNDATION_DIR="foundation"

if [ -d "$FOUNDATION_DIR" ]; then
    echo "Foundation already present. Skipping clone."
else
    echo "Cloning pre-event foundation from inert-silver..."
    git clone https://github.com/surfiniaburger/inert-silver.git "$FOUNDATION_DIR"
    cd "$FOUNDATION_DIR"
    git checkout "$BASE_COMMIT"
    cd ..
fi

echo "Applying hackathon patches..."
cd "$FOUNDATION_DIR"
git apply ../patches/hackathon.patch
cd ..

echo "Installing dependencies..."
cd "$FOUNDATION_DIR"
uv sync
cd ..

echo "Bootstrap complete. Run 'cd foundation && uv run python ../cli.py demo --offline' to verify."
