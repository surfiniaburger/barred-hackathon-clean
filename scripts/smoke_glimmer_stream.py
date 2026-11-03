#!/usr/bin/env python3
"""Smoke-test live token streaming from the local Meta Glimmer server.

Hits the OpenAI-compatible endpoint directly (no debate stack needed --
only T1 `mirai server --port 8123` must be up) and prints tokens as they
arrive, with first-token latency. Built for the demo-video proof-of-life
beat: request, streaming response, and model provenance, all on camera.

Usage:
    python3 scripts/smoke_glimmer_stream.py
    python3 scripts/smoke_glimmer_stream.py --max-tokens 64

Note: mirai 0.6.15 buffers the reasoning phase server-side and flushes
the thinking stream as a late burst (verified with unbuffered reads),
so expect request -> wait -> burst, not gradual tokens from second 1.
Thinking always exhausts max_tokens (finish=length, no answer phase);
a reasoning_effort passthrough was tried and the server ignores it.
For the shortest wait, use --max-tokens 128 (~35s real time).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8123/v1"
DEFAULT_MODEL = "meta:muse-glimmer:30b:mirai:mirai-m:4"
DEFAULT_PROMPT = (
    "In one sentence, is this C code safe? "
    "Code: if (len > cap) { return; } memcpy(dst, src, len);"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stream one live Glimmer completion.")
    ap.add_argument("--base", default=DEFAULT_BASE, help="OpenAI base URL")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Model id to request")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="User prompt")
    ap.add_argument("--max-tokens", type=int, default=256,
                        help="Cap on completion (thinking eats tokens too)")
    args = ap.parse_args()

    url = args.base.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": args.model,
            "messages": [{"role": "user", "content": args.prompt}],
            "max_tokens": args.max_tokens,
            "stream": True,
        }
    ).encode()

    print(f"POST {url}", flush=True)
    print(f"model: {args.model}", flush=True)
    print(f"prompt: {args.prompt}", flush=True)
    print("--- live tokens ---", flush=True)

    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    def _text_of(value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):  # content-block style parts
            return "".join(
                p.get("text", "") for p in value if isinstance(p, dict)
            )
        return ""

    t0 = time.monotonic()
    first_at = None
    delta_keys: set = set()
    arrivals = []  # (text-chunk index, elapsed) for the first few
    in_thinking = False

    def handle_line(line, state):
        nonlocal first_at, in_thinking
        if not line.startswith("data:"):
            return False
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return True
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            return False
        state["seen_model"] = state["seen_model"] or chunk.get("model")
        choice = (chunk.get("choices") or [{}])[0]
        state["finish"] = state["finish"] or choice.get("finish_reason")
        delta = choice.get("delta") or choice.get("message") or {}
        if isinstance(delta, dict):
            delta_keys.update(delta.keys())
        think = _text_of(delta.get("reasoning_content", "")
                         or delta.get("reasoning", ""))
        piece = _text_of(delta.get("content", "")) or choice.get("text", "")
        if think or piece:
            state["n"] += 1
            if len(arrivals) < 5:
                arrivals.append((state["n"], time.monotonic() - t0))
        if think:
            if first_at is None:
                first_at = time.monotonic()
            if not in_thinking:
                sys.stdout.write("[thinking] ")
                in_thinking = True
            state["thinking"] += 1
            sys.stdout.write(think)
            sys.stdout.flush()
        if piece:
            if first_at is None:
                first_at = time.monotonic()
            if in_thinking:
                sys.stdout.write("\n[answer] ")
                in_thinking = False
            state["answer"] += 1
            sys.stdout.write(piece)
            sys.stdout.flush()
        return False

    state = {"n": 0, "thinking": 0, "answer": 0,
             "seen_model": None, "finish": None}
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            # Single-byte reads: immune to userspace readahead buffering,
            # so arrival times below reflect the server, not this client.
            buf = bytearray()
            while True:
                byte = resp.read(1)
                if not byte:
                    break
                if byte == b"\n":
                    line = bytes(buf).decode("utf-8", errors="replace").strip()
                    buf.clear()
                    if handle_line(line, state):
                        break
                else:
                    buf += byte
    except OSError as e:
        print(f"\nERROR: cannot reach {url}: {e}", flush=True)
        print("Is T1 running?  mirai server --model trymirai/Muse-Glimmer-30B-M --port 8123",
              flush=True)
        return 1

    total = time.monotonic() - t0
    print("\n--- done ---", flush=True)
    if first_at is not None:
        print(f"first token: {first_at - t0:.1f}s   total: {total:.1f}s", flush=True)
    else:
        print(f"no text chunks received (total: {total:.1f}s)", flush=True)
        print(f"delta keys observed: {sorted(delta_keys)}", flush=True)
    if arrivals:
        seq = ", ".join(f"#{i}@{t:.1f}s" for i, t in arrivals)
        print(f"first arrivals: {seq}", flush=True)
    print(f"thinking chunks: {state['thinking']}   answer chunks: {state['answer']}",
          flush=True)
    print(f"finish: {state['finish']}   model seen in stream: {state['seen_model']}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
