#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Baseten config
export DEBATER_MODEL="openai/meta-models/muse-spark-open-1026"
export VERIFIER_MODEL="openai/meta-models/muse-spark-open-1026"
export GENERATOR_MODEL="openai/meta-models/muse-spark-open-1026"
export JUDGE_MODEL="openai/meta-models/muse-spark-open-1026"
export OPENAI_API_BASE="https://inference.baseten.co/v1"
export OPENAI_API_KEY="${BASETEN_API_KEY:-}"
export LLM_SAMPLING_PROFILE="env"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-4096}"
export SEND_MESSAGE_TIMEOUT="${SEND_MESSAGE_TIMEOUT:-1800}"
export LITELLM_REQUEST_TIMEOUT="${LITELLM_REQUEST_TIMEOUT:-360}"
export LITELLM_NUM_RETRIES="${LITELLM_NUM_RETRIES:-3}"

# Start the debate stack in background
echo "Starting debate stack..."
cd "$ROOT_DIR/foundation"
bash scenarios/debate/start_stack.sh > /tmp/stack.log 2>&1 &
STACK_PID=$!
cd "$ROOT_DIR"

# Wait for ports to be ready
echo "Waiting for debate stack ports..."
for port in 9009 9018 9019 9020; do
    for i in $(seq 1 60); do
        if (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null; then
            echo "Port $port ready"
            break
        fi
        sleep 2
    done
done

echo "Debate stack started (PID: $STACK_PID). Starting app..."
exec uv run python app.py
