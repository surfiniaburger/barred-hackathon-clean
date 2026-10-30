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
5. **Architectural Bug Fixes & False-Positive Elimination:** Hardened through 38 regression and replay tests closing null-receipt false passes, non-dominating guard hallucinations, schema coercion failures, and ungrounded wrapper claims.
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

---

## Quickstart & Evaluation Modes

BARRED offers two ways to evaluate the system:

### Option A: 30-Second Instant Visual Demo (Offline Replay)
Inspect the three canonical outcomes without needing a 20GB+ GPU running:
```bash
uv run python cli.py demo --offline
```

---

### Option B: Full Live Multi-Agent Pipeline (Real Meta Muse-Glimmer-30B)

This runs the complete end-to-end multi-agent debate and deterministic evidence gating pipeline.

#### Terminal 1 — Download & Launch Mirai Model:
```bash
brew install mirai
mirai --model trymirai/Muse-Glimmer-30B-M
```

#### Terminal 2 — Start Uzu OpenAI-Compatible Proxy (Python 3.12):
```bash
# If .venv-uzu is not already initialized:
# uv venv .venv-uzu --python 3.12 && uv pip install --python .venv-uzu/bin/python uzu uvicorn fastapi
MODEL=trymirai/Muse-Glimmer-30B-M ./scripts/start_uzu_proxy.sh
```

#### Terminal 3 — Launch the Multi-Agent Debate Stack:
Spins up the Pro debater, Con debater, Verifier, and Judge microservices:
```bash
./scenarios/debate/start_all_muse_stack.sh
```

#### Terminal 4 — Execute the Evidence-Gated Batch Review:
```bash
uv run python scenarios/debate/run_batch.py \
  --seeds scenarios/debate/cve_seeds_smoke_2gate.jsonl \
  --run-id m9bol-gate-smoke-v10 \
  --output artifacts/factorial/corpus_gateol_smoke_v10.jsonl \
  --gepa-dir artifacts/gepa_m9dl_pareto_smoke \
  --attempts-out artifacts/attempts/gateol-smoke-v10.jsonl \
  --manifest-out artifacts/runs/gateol-smoke-v10/batch_manifest.json \
  --seed 42 --mode record --slice-judge --reflector --reflector-in-process \
  --reflector-mode symmetric --escalate-pareto --max-concurrency 1 \
  --counter-evidence-validation-mode enforce_deterministic --halt-on-con-win
```

#### Inspect Live Run Results via CLI:
Render the human-readable tri-state decision cards directly from the live attempt logs:
```bash
uv run python cli.py inspect artifacts/attempts/gateol-smoke-v10.jsonl
```

#### Evaluate Benchmark Ground Truth & Confusion Matrix:
Evaluate any batch attempt log against the canonical ground-truth ledger ([`reports/BARRED_Track_1_Canonical_Ledger.csv`](reports/BARRED_Track_1_Canonical_Ledger.csv)) to render the 2x2 confusion matrix and epistemic boundary metrics:
```bash
uv run python cli.py eval --attempts evidence_pack/m9bol_gate_smoke_v10_attempts.jsonl
```

---

## Detailed Explanation of Pipeline Flags

| Flag | Purpose & Impact |
| :--- | :--- |
| `--seeds cve_seeds_smoke_2gate.jsonl` | Loads the two test cases: Seed 42 (Supported memcpy guard) and Seed 43 (Unsupported wrapper). |
| `--counter-evidence-validation-mode enforce_deterministic` | **The Core Innovation**: Engages the AST evidence gate. Blocks any model claim lacking an invariant proof. |
| `--halt-on-con-win` | **Efficiency & Proof**: Halts execution the instant deterministic proof is confirmed (Seed 42 halts on Round 0). |
| `--slice-judge` | Slices code context specifically for judge adjudication, stripping misleading context. |
| `--reflector --reflector-mode symmetric --escalate-pareto` | **Multi-Turn Epistemic Escalation**: When the gate catches a hallucination in Round 0 (Seed 43), reflection forces the model to re-evaluate and admit `unresolved` in Round 1. |
| `--mode record` | Records bit-for-bit LLM prompt/response cassettes and attempt telemetry for auditability. |

---

## The Three Canonical Cases

| Case | Scenario | Model Action | Deterministic Gate Action | Final Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Case 1 (Seed 42)** | `safe_copy`: upper-bound guard (`len >= cap`) protecting `memcpy(dst, src, len)` | Selects Candidate `C1` | **Confirmed**: 7/7 AST checks verify guard dominates sink | **`PASS`** |
| **Case 2 (Seed 43 R1)** | `gdImageJpegPtr`: zero-width test on 3rd-party wrapper | Model refrains (`candidate_id: null`) | **Epistemic Bound**: AST domain refuses to certify unknown sinks | **`UNRESOLVED`** |
| **Case 3 (Seed 43 R0)** | Superficial/ungrounded check before memory operation | Model attempts hallucination (`C1`) | **Blocked**: Gate rejects ungrounded candidate | **`BLOCKED`** |

---

## Verification, Test Suite & Bug Fixes

### 🧪 38 TDD & Regression Tests (Passing in 1.4s)
All core validator mechanisms, candidate extractors, and failure-mode mitigations are verified by a comprehensive 38-test offline suite:
```bash
uv run pytest tests/test_con_receipt_e2e.py tests/test_con_receipt_extractor.py tests/test_counter_evidence_fixtures.py tests/test_failure_modes_replay.py -v
```

### 🛡️ Bug Fixes & False-Positive Elimination
In baseline unconstrained multi-agent debate runs, models routinely suffered from critical false positives and hallucinated defenses. The 38 tests explicitly encode and guard against these historical failure modes:

1. **Elimination of Null-Receipt False Passes (`test_failure_modes_replay.py`)**:
   - *Previous Defect:* LLM judges previously awarded defense wins (`winner="con_debater"`) based solely on plausible-sounding rhetoric without machine-verifiable receipts, causing catastrophic false positives on vulnerable code.
   - *Fix:* Con wins without deterministically confirmed receipts safely downgrade to controlled epistemic refusal (`outcome="unresolved"`).
2. **Rejection of Incompatible and Non-Dominating Guards (`test_counter_evidence_fixtures.py`)**:
   - *Previous Defect:* Models claimed safety when a bounds check occurred *after* the vulnerable memory operation (`memcpy`), or checked unrelated variables (e.g., checking `cap > len` or checking `size` while copying `len`).
   - *Fix:* The AST validator strictly enforces control-flow dominance (guard must precede and dominate sink) and variable-binding equality (`guarded_value_equals_operation_value`).
3. **Semantic Validation Gap for Unknown Sinks (`test_con_receipt_e2e.py`)**:
   - *Previous Defect:* Superficial guards on 3rd-party library calls (e.g. `gdImageJpegPtr` in Seed 43) were erroneously claimed as bounded safety proofs.
   - *Fix:* Non-standard memory sinks without formal trusted operation summaries are flagged (`operation_not_recognized_sink`) and rejected (`counter_evidence_unrecognized_operation`), forcing honest abstention (`UNRESOLVED`).
4. **Resilient Schema Coercion & Parse Recovery (`test_debate_eval_schema.py`)**:
   - *Previous Defect:* Live LLM variations outputting `verdict_reason` instead of `reason`, formatting `thinking_process` as a JSON array, or omitting scorecard sub-dictionaries caused unhandled crashes.
   - *Fix:* Robust Pydantic before-validators and repair context coercion automatically harmonize variations without compromising validation rigor.
5. **Early Deterministic Halting & Multi-Turn Reflection**:
   - *Live Result:* Confirmed defenses (Seed 42) halt immediately on Round 0 (`--halt-on-con-win`), preventing compute waste and regression. In Seed 43, when Round 0 hallucination was rejected, symmetric reflection forced the model to concede `unresolved` on Round 1.

---

## Benchmark Ground Truth & Canonical Ledger

[`reports/BARRED_Track_1_Canonical_Ledger.csv`](reports/BARRED_Track_1_Canonical_Ledger.csv) is the human-adjudicated ground-truth for all 50 seeds (IDs 42–91) evaluated during the hackathon period:

| Verdict | Count | Description |
| :--- | :---: | :--- |
| `proved_safe` | **20** | Deterministic AST proof confirmed the fix is correct |
| `confirmed_vulnerable` | **22** | Fix is insufficient or exploitable; model should output `BLOCKED` or `UNRESOLVED` |
| `context_deficient` | **8** | Seeds 45, 49, 54, 56, 60, 70, 74, 91 — insufficient source context for proof either way; correct system behavior is epistemic abstention (`UNRESOLVED`) |

The 8 context-deficient seeds represent BARRED's honest epistemic boundary: the system abstains rather than hallucinating a verdict.

Run the confusion matrix evaluator against any batch attempt log:
```bash
uv run python cli.py eval --attempts evidence_pack/m9bol_gate_smoke_v10_attempts.jsonl
```

See [`RESULTS.md`](RESULTS.md) for the before/after comparison showing how the deterministic gate eliminates baseline hallucinations.

---

## Benchmark Ground Truth & Canonical Ledger

[`reports/BARRED_Track_1_Canonical_Ledger.csv`](reports/BARRED_Track_1_Canonical_Ledger.csv) is the human-adjudicated ground-truth for all 50 seeds (IDs 42–91) evaluated during the hackathon period:

| Verdict | Count | Description |
| :--- | :---: | :--- |
| `proved_safe` | **20** | Deterministic AST proof confirmed the fix is correct |
| `confirmed_vulnerable` | **22** | Fix is insufficient or exploitable; model should output `BLOCKED` or `UNRESOLVED` |
| `context_deficient` | **8** | Seeds 45, 49, 54, 56, 60, 70, 74, 91 — insufficient source context for proof either way; correct system behavior is epistemic abstention (`UNRESOLVED`) |

The 8 context-deficient seeds represent BARRED's honest epistemic boundary: the system abstains rather than hallucinating a verdict.

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
