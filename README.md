# BARRED: Evidence-Gated Security Fix Review

> **Track:** Push the Frontier  
> **Model:** Meta Muse-Glimmer-30B (`trymirai/Muse-Glimmer-30B-M`)  
> **Architecture:** Open-weight 30B multimodal dense transformer with Llama BPE tokenizer, optimized for autonomous agentic code workflows  
> **Core Innovation:** Transforming probabilistic AI security opinions into deterministic, machine-verifiable evidence decisions  

---

### 📋 Hackathon Project Disclosure (Oct 26 – Nov 4, 2026)
*This project was developed for the Meta AI Developer Hackathon. All core innovations presented in this submission were designed, implemented, and evaluated during the hackathon period (October 26 – November 4, 2026):*
1. **Deterministic AST Candidate Extractor (`scenarios/debate/con_receipt_extractor.py`):** Automatically discovers dominating bounds checks and guard invariants from source code slices.
2. **Mathematical Receipt Validator (`scenarios/debate/counter_evidence_validation.py`):** Verifies invariant contracts to eliminate AI safety hallucinations and false positives (achieving `0.0%` accepted logic error rate across all benchmarks).
3. **Meta Muse-Glimmer-30B Integration:** End-to-end multi-agent debate, adjudication, and candidate selection powered by Meta's open-weights model via Uzu.
4. **Fault-Tolerant 3-Way Adjudication Contracts:** `PASS` (Proven via C1) | `BLOCKED` (Falsified/Exploitable) | `UNRESOLVED` (Explicit abstention on unsupported domains).
5. **Architectural Bug Fixes & False-Positive Elimination:** Hardened through 43 regression tests closing null-receipt false passes, non-dominating guard hallucinations, schema coercion failures, and ungrounded wrapper claims.
6. **One-Command Reviewer CLI & Evidence Pack:** A developer-facing tool allowing instant 30-second inspection or full live verification.

---


## The Problem
Every AI coding assistant today suffers from a fatal flaw: **it produces persuasive, authoritative-sounding explanations whether it is right or wrong.**

When reviewing a security fix, an LLM might declare code "Safe" because the developer added a superficial check or an irrelevant comment. To protect themselves, platforms slap broad legal disclaimers on coding agents (*"Verify all actions taken by the agent"*).

**BARRED replaces disclaimers with deterministic proof.**

Instead of letting an LLM generate ungrounded prose, BARRED pairs **Meta's Muse-Glimmer-30B** with **deterministic AST evidence gates**. The model is constrained to select machine-extracted candidates ($C_1 \dots C_n$), while the deterministic engine mathematically verifies control-flow dominance and value relations.

The result is a clean tri-state security review:
1. **`PASS`**: Machine-verified invariant proof attached (guard dominates sink on all paths).
2. **`BLOCKED`**: Plausible model hallucination caught and rejected by AST gate.
3. **`UNRESOLVED`**: Explicit epistemic refusal when outside the verified proof domain (no fake safety claims).

### Who needs this

AI coding assistants are increasingly pointed at legacy C/C++ codebases for
security review and modernization — exactly where a convincing-but-wrong
"safe" verdict is most dangerous. BARRED is for software engineers and
security reviewers who need to independently verify the evidence behind an
AI-proposed security fix before trusting it.

The core design principle: the model's ability to *propose* a security
argument is separated from the system's authority to *validate* it. The LLM
selects among machine-extracted candidates; only the deterministic gate can
certify one. No candidate the gate cannot verify ever becomes a `PASS`.

---

## Setup (Bootstrap)

This repository contains only the hackathon event code. The pre-event foundation
(`inert-silver` at commit `7218e2d`) is fetched at setup time:

```bash
./bootstrap.sh
```

This clones the foundation, applies the event patches, and installs dependencies.
After bootstrap, the full pipeline is available under `foundation/`.

The offline demo (`cli demo --offline`) works without the foundation — it uses
the curated evidence pack in `evidence_pack/`.

Dependency note: `scenarios/debate/graph_dataflow.py` is vendored unmodified
from `inert-silver` so the offline reviewer runs standalone; it is a pre-event
dependency module, not claimed event work.

## Quickstart & Evaluation Modes

### Run the Demo (Offline Replay)
Inspect the three canonical outcomes without needing a 20GB+ GPU running:
```bash
uv run python cli.py demo --offline
```

### Live Mode (Debate Stack + Web UI)

Live runs execute the full multi-agent debate against Meta models served via
**Baseten** (a separate private product). The key is fetched from the OS
keychain at runtime — store it once, then never export it again:

```bash
# one-time setup (macOS Keychain; no extra dependency; -U replaces a rotated key on rerun)
security add-generic-password -U -s barred-baseten -a api_key -w
# check what is configured (prints the source, never the key)
python3 scripts/baseten_key.py --status
```

Requires the bootstrapped foundation:

```bash
./bootstrap.sh
./start.sh
# open http://localhost:8080
```

Explicit `BASETEN_API_KEY` still wins when set (CI, one-off keys), and local
endpoints (`LLM_API_KEY=dummy`) never touch the keychain.

Or via Docker (bootstraps the foundation at build time). The container cannot
see the host keychain, so the wrapper resolves the key on the host and
injects it — the key never appears in your shell history or in any repo
file (standard `-e` caveat: it remains visible via `docker inspect` while
the container exists):

```bash
docker build -t barred .
./scripts/docker-run.sh
```

Live runs also work against any OpenAI-compatible endpoint with no API key
(use the `openai/` prefix so LiteLLM routes to your base URL). Verified path
on Apple Silicon via Mirai (swap in any served model ID):

```bash
# Terminal 1: serve local weights (no key; requires mirai>=0.6.15)
mirai server --model trymirai/Muse-Glimmer-30B-M --port 8123

# Terminal 2: run the stack + app against it
./bootstrap.sh
export LLM_API_BASE=http://127.0.0.1:8123/v1
export LLM_MODEL=openai/meta:muse-glimmer:30b:mirai:mirai-m:4
export LLM_API_KEY=dummy
echo "BASE=$LLM_API_BASE"
chmod +x start.sh
./start.sh
```

`BASE=` must print `http://127.0.0.1:8123/v1` before you start — an empty
value means an export typo'd (wrong base = 401s from the default endpoint).
`chmod` guards fresh clones where `start.sh` loses its exec bit
(`permission denied`).

(Any other OpenAI-compatible server works the same way, e.g.
`LLM_API_BASE=http://localhost:11434/v1` for Ollama, or Qwen3.5-4B via
`mirai server --model trymirai/Qwen3.5-4B-M`.) This exercises the real debate
+ deterministic gate end to end; only the model behind the endpoint differs.

### Local Glimmer end-to-end run (2-gate smoke, ~30–50 min)

With Terminals 1–2 above running, execute the two canonical seeds and score them:

```bash
# Terminal 3: run both seeds (leave T1/T2 running; log the run)
cd foundation
export PYTHONPATH="$PWD:$PYTHONPATH"
export LLM_API_BASE=http://127.0.0.1:8123/v1
export LLM_MODEL=openai/meta:muse-glimmer:30b:mirai:mirai-m:4
export LLM_API_KEY=dummy
echo "BASE=$LLM_API_BASE"
mkdir -p ../runs/local-glimmer-e2e
time uv run python scenarios/debate/run_batch.py \
  --seeds scenarios/debate/cve_seeds_smoke_2gate.jsonl \
  --run-id local-glimmer-e2e \
  --output ../runs/local-glimmer-e2e/corpus.jsonl \
  --gepa-dir ../runs/local-glimmer-e2e/gepa \
  --attempts-out ../runs/local-glimmer-e2e/attempts.jsonl \
  --manifest-out ../runs/local-glimmer-e2e/manifest.json \
  --seed 42 \
  --mode record \
  --slice-judge \
  --reflector \
  --reflector-in-process \
  --reflector-mode symmetric \
  --escalate-pareto \
  --max-concurrency 1 \
  --counter-evidence-validation-mode enforce_deterministic \
  --halt-on-con-win 2>&1 | tee ../runs/local-glimmer-e2e/run.log
```

Only start T3 after T2 prints `Port 9020 ready` (otherwise 503 agent-card
errors from 9009). Same `BASE=` guard as T2 — confirm it prints the 8123
URL before launching the batch. Outputs land in `runs/local-glimmer-e2e/`
(gitignored).

Verify (from the repo root):

```bash
uv run python cli.py eval --attempts runs/local-glimmer-e2e/attempts.jsonl
```

Expected: seed 42 → SAFE (`TN`), seed 90 → `UNRESOLVED` abstention (see
[`RESULTS.md`](RESULTS.md) for why the Seed 90 abstention is justified, not a
failure). The smoke file carries canonical ledger ids, so no seed remapping is
needed. What must never happen: a `PASS` on seed 90, or any
`deterministically_confirmed` receipt on invalid evidence — that is the gate
guarantee being witnessed live.

**Model provenance.** `start.sh` pins the serving model via `LLM_*` exports,
and shell exports take precedence over any parent-directory `.env`
(`run_scenario.py` uses `load_dotenv(override=False)`), so the model recorded
in `attempts.jsonl` telemetry matches the server T1 is actually running.

**Version pins.** Local Glimmer-30B chat verified end to end on `mirai` 0.6.15
(Qwen chat also verified, on 0.6.11). Note `mirai server` on 0.6.11 panics on
the Glimmer weights (`Weaver MLP does not support input Hadamard factors`) —
use `mirai>=0.6.15` for Glimmer-30B. The recorded Glimmer runs in
`evidence_pack/` were produced 2026-10-28 through the Uzu Python engine
(`uzu==0.6.8`) with model `trymirai/Muse-Glimmer-30B-M` (weights
`meta:muse-glimmer:30b:mirai:mirai-m:4`).

**No API key?** Every tri-state outcome is reproducible without one: the offline
demo above, `cli.py review --offline`, and `cli.py eval` all run on the curated
`evidence_pack/` (recorded model telemetry + deterministic re-validation), and
`web/public/data` ships prebuilt recorded runs (regenerate offline with
`python3 scripts/build_recorded_runs.py`).

---

## The Three Canonical Cases

| Case | Scenario | Model Action | Deterministic Gate Action | Final Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Case 1 (safe_copy)** | `safe_copy`: upper-bound guard (`len >= cap`) protecting `memcpy(dst, src, len)` | Selects Candidate `C1` | **Confirmed**: 7/7 AST checks verify guard dominates sink | **`PASS`** |
| **Case 2 (Seed 90 R1)** | `gdImageJpegPtr`: zero-width test on 3rd-party wrapper | Model refrains (`candidate_id: null`) | **Epistemic Bound**: AST domain refuses to certify unknown sinks | **`UNRESOLVED`** |
| **Case 3 (Seed 90 R0)** | Superficial/ungrounded check before memory operation | Model attempts hallucination (`C1`) | **Blocked**: Gate rejects ungrounded candidate | **`BLOCKED`** |

## Scope and limits

BARRED certifies claims inside its supported proof domain: memory-safety
invariants over recognized sinks (e.g. `memcpy`-family operations) with
statically verifiable guard dominance and value relations. The terminal
mapping is exact: a *selected* candidate that fails validation for any
reason — failed checks, ungrounded anchors, an unrecognized sink, a
malformed receipt — is rejected as `BLOCKED`. `UNRESOLVED` is abstention,
not rejection: no candidate was put forward for certification (the model
refrained) or the seed omits the decisive evidence (context-deficient), so
there is nothing to certify and nothing to reject. BARRED does not establish
universal software safety. An `UNRESOLVED` result is the system working as
designed: it tells you when its proof does not apply rather than
manufacturing certainty.

---

## Verification, Test Suite & Bug Fixes

### 🧪 43 TDD & Regression Tests (Passing in ~8s)
All core validator mechanisms, candidate extractors, and failure-mode mitigations are verified by a comprehensive 43-test offline suite:
```bash
# Standalone (no foundation needed, 16 tests):
uv run pytest tests/test_con_receipt_extractor.py tests/test_counter_evidence_fixtures.py -v

# Full suite (after bootstrap.sh, 27 tests):
cd foundation && uv run pytest \
  tests/test_con_receipt_e2e.py \
  tests/test_counter_evidence_validation.py \
  tests/test_debate_eval_schema.py \
  tests/test_failure_modes_replay.py -v
```

### 🛡️ Bug Fixes & False-Positive Elimination
In baseline unconstrained multi-agent debate runs, models routinely suffered from critical false positives and hallucinated defenses. The 43 tests explicitly encode and guard against these historical failure modes:

1. **Elimination of Null-Receipt False Passes** (covered by `test_counter_evidence_fixtures.py`):
   - *Previous Defect:* LLM judges previously awarded defense wins (`winner="con_debater"`) based solely on plausible-sounding rhetoric without machine-verifiable receipts, causing catastrophic false positives on vulnerable code.
   - *Fix:* Con wins without deterministically confirmed receipts safely downgrade to controlled epistemic refusal (`outcome="unresolved"`).
2. **Rejection of Incompatible and Non-Dominating Guards (`test_counter_evidence_fixtures.py`)**:
   - *Previous Defect:* Models claimed safety when a bounds check occurred *after* the vulnerable memory operation (`memcpy`), or checked unrelated variables (e.g., checking `cap > len` or checking `size` while copying `len`).
   - *Fix:* The AST validator strictly enforces control-flow dominance (guard must precede and dominate sink) and variable-binding equality (`guarded_value_equals_operation_value`).
3. **Semantic Validation Gap for Unknown Sinks** (covered by `test_con_receipt_extractor.py`):
   - *Previous Defect:* Superficial guards on 3rd-party library calls (e.g. `gdImageJpegPtr` in Seed 90) were erroneously claimed as bounded safety proofs.
   - *Fix:* Non-standard memory sinks without formal trusted operation summaries are flagged (`operation_not_recognized_sink`) and rejected (`counter_evidence_unrecognized_operation`), forcing honest abstention (`UNRESOLVED`).
4. **Resilient Schema Coercion & Parse Recovery** (covered by `test_con_receipt_extractor.py`):
   - *Previous Defect:* Live LLM variations outputting `verdict_reason` instead of `reason`, formatting `thinking_process` as a JSON array, or omitting scorecard sub-dictionaries caused unhandled crashes.
   - *Fix:* Robust Pydantic before-validators and repair context coercion automatically harmonize variations without compromising validation rigor.
5. **Early Deterministic Halting & Multi-Turn Reflection**:
   - *Live Result:* Confirmed defenses (safe_copy) halt immediately on Round 0 (`--halt-on-con-win`), preventing compute waste and regression. In Seed 90, when Round 0 hallucination was rejected, symmetric reflection forced the model to concede `unresolved` on Round 1.

---

## Benchmark Ground Truth & Canonical Ledger

[`reports/BARRED_Track_1_Canonical_Ledger.csv`](reports/BARRED_Track_1_Canonical_Ledger.csv) is the human-adjudicated ground-truth for all 50 seeds (IDs 42–91) evaluated during the hackathon period:

| Verdict | Count | Seeds |
| :--- | :---: | :--- |
| `proved_safe` | **20** | 42, 46–48, 50–52, 57, 58, 62, 63, 66, 68, 72, 82–84, 86, 88, 90 |
| `confirmed_vulnerable` | **22** | 43, 44, 53, 55, 59, 61, 64, 65, 67, 69, 71, 73, 75–81, 85, 87, 89 |
| `context_deficient` | **8** | 45, 49, 54, 56, 60, 70, 74, 91 |

Verdicts come from the per-seed evidence audits (`BARRED_Track_1_Seed_XX_Evidence_Audit.md`): `proved_safe` means the audit refuted the exact claim on mechanism; `confirmed_vulnerable` means the audit reproduced the claimed mechanism; `context_deficient` means the seed omits the decisive implementation or reachability evidence, so the correct system behavior is epistemic abstention (`UNRESOLVED`) rather than a hallucinated verdict.

Run the confusion matrix evaluator against any batch attempt log:
```bash
uv run python cli.py eval --attempts evidence_pack/m9bol_gate_smoke_v10_attempts.jsonl
```

See [`RESULTS.md`](RESULTS.md) for the before/after comparison showing how the deterministic gate eliminates baseline hallucinations.

---

## Live Evidence Pack

- **Audit Trace**: [`evidence_pack/audit_m9bol_gate_smoke_v10.json`](evidence_pack/audit_m9bol_gate_smoke_v10.json)
- **Batch Manifest**: [`evidence_pack/batch_manifest.json`](evidence_pack/batch_manifest.json)
- **Attempt Telemetry**: [`evidence_pack/m9bol_gate_smoke_v10_attempts.jsonl`](evidence_pack/m9bol_gate_smoke_v10_attempts.jsonl)
- **Factorial Corpus**: [`evidence_pack/corpus_gateol_smoke_v10.jsonl`](evidence_pack/corpus_gateol_smoke_v10.jsonl)

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
