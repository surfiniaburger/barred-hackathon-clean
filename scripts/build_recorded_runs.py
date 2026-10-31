#!/usr/bin/env python3
"""Build sanitized recorded-run data for the BARRED Recorded Run Explorer.

Reads curated attempt/manifest artifacts and emits:
  web/public/data/recorded-runs.v1.json
  web/public/data/artifacts/*.json

Usage:
    python3 scripts/build_recorded_runs.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "web" / "public" / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

# Curated sources
GLIMMER_ATTEMPTS = ROOT / "evidence_pack" / "m9bol_gate_smoke_v10_attempts.jsonl"
GLIMMER_MANIFEST = ROOT / "evidence_pack" / "batch_manifest.json"
GLIMMER_CORPUS = ROOT / "evidence_pack" / "corpus_gateol_smoke_v10.jsonl"

SPARK_ATTEMPTS = ROOT / "artifacts" / "attempts" / "gateol-smoke-v13.jsonl"
SPARK_MANIFEST = ROOT / "artifacts" / "runs" / "gateol-smoke-v13" / "batch_manifest.json"
SPARK_CORPUS = ROOT / "artifacts" / "factorial" / "corpus_gateol_smoke_v13.jsonl"

# Secret-like keys to reject
SECRET_KEYS = {"api_key", "authorization", "token", "secret", "password", "bearer"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_no_secrets(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in SECRET_KEYS:
                raise ValueError(f"Secret-like key '{k}' found at {path}")
            check_no_secrets(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            check_no_secrets(item, f"{path}[{i}]")


def load_attempts(path: Path) -> list[dict]:
    records = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        check_no_secrets(rec)
        records.append(rec)
    return records


def derive_status(rec: dict) -> str:
    """Deterministic status derivation per spec."""
    decision = rec.get("decision")
    je = rec.get("judge_eval", {})
    model_outcome = je.get("outcome")
    cev = rec.get("counter_evidence_validation") or {}
    gate_status = cev.get("status")

    if decision == "accepted" and gate_status == "deterministically_confirmed":
        return "PASS"
    if model_outcome == "con_win" and gate_status in ("invalid_contract", "rejected", None) and decision != "accepted":
        # Only BLOCKED if there's a claimed con_win that was rejected
        if gate_status in ("invalid_contract",) or rec.get("reject_reason", "").startswith("counter_evidence"):
            return "BLOCKED"
    # Final no-receipt round
    return "UNRESOLVED"


def extract_stage_timings(rec: dict) -> list[dict]:
    stages = []
    by_stage = rec.get("llm_usage", {}).get("by_stage", {})
    for stage_name, info in by_stage.items():
        stages.append({
            "stage": stage_name,
            "recorded_duration_ms": info.get("total_duration_ms", 0),
            "total_tokens": info.get("total_tokens", 0),
            "calls": info.get("calls", 0),
        })
    return stages


def sanitize_record(rec: dict) -> dict:
    """Extract only UI-relevant fields from an attempt record."""
    je = rec.get("judge_eval", {})
    cev = rec.get("counter_evidence_validation")
    cev_summary = None
    if cev:
        cev_summary = {
            "status": cev.get("status"),
            "method": cev.get("method"),
            "failure_reasons": cev.get("failure_reasons", []),
            "checks": cev.get("checks", {}),
            "defense_kind": cev.get("defense_kind"),
            "evidence": cev.get("evidence"),
        }

    # Soft checks (mechanism evidence etc.)
    soft = rec.get("soft_checks", {})
    mech_checks = {}
    for key in ("mechanism_evidence", "mechanism_grounding", "mechanism_template",
                "predicate_aboutness", "predicate_quality"):
        if key in soft and isinstance(soft[key], dict):
            mech_checks[key] = soft[key]

    return {
        "decision": rec.get("decision"),
        "reject_reason": rec.get("reject_reason"),
        "support_level": rec.get("support_level"),
        "judge_eval": {
            "outcome": je.get("outcome"),
            "con_candidate_id": je.get("con_candidate_id"),
            "winner": je.get("winner"),
            "support_level": je.get("support_level"),
            "anchors": je.get("anchors", []),
        },
        "counter_evidence_validation": cev_summary,
        "soft_checks": mech_checks,
        "anchors_normalized": rec.get("anchors_normalized", []),
        "predicate": rec.get("predicate"),
        "refinement_round": rec.get("refinement_round", 0),
        "llm_usage": {
            "totals": rec.get("llm_usage", {}).get("totals", {}),
            "by_stage": rec.get("llm_usage", {}).get("by_stage", {}),
        },
        "metadata": {
            "seed": rec.get("metadata", {}).get("seed"),
            "clock_now": rec.get("metadata", {}).get("clock_now"),
            "models": rec.get("metadata", {}).get("models", {}),
            "generation_config": rec.get("metadata", {}).get("generation_config", {}),
            "sample_sha256": rec.get("metadata", {}).get("sample_sha256"),
        },
    }


def build_case(rec: dict, scenario_id: str, run_id: str, case_index: int) -> dict:
    status = derive_status(rec)
    stage_timings = extract_stage_timings(rec)
    sanitized = sanitize_record(rec)

    # Artifact link
    artifact_name = f"{run_id}-{scenario_id}-r{rec.get('refinement_round', 0)}.json"
    artifact_path = ARTIFACTS_DIR / artifact_name
    artifact_path.write_text(json.dumps(sanitized, indent=2))
    check_no_secrets(sanitized)

    # Source code from the smoke seed file (will be filled by caller)
    source_code = rec.get("_source_code", "")

    return {
        "id": f"{run_id}-{scenario_id}-r{rec.get('refinement_round', 0)}",
        "scenario_id": scenario_id,
        "round": rec.get("refinement_round", 0),
        "status": status,
        "model_outcome": rec.get("judge_eval", {}).get("outcome"),
        "candidate_id": rec.get("judge_eval", {}).get("con_candidate_id"),
        "reason_code": rec.get("reject_reason"),
        "gate_status": (rec.get("counter_evidence_validation") or {}).get("status"),
        "predicate": rec.get("predicate"),
        "source_code": source_code,
        "anchors": rec.get("judge_eval", {}).get("anchors", []),
        "events": stage_timings,
        "checks": (rec.get("counter_evidence_validation") or {}).get("checks", {}),
        "failure_reasons": (rec.get("counter_evidence_validation") or {}).get("failure_reasons", []),
        "counterfactual": (rec.get("counter_evidence_validation") or {}).get("evidence", {}).get("relation"),
        "artifact_links": {
            "sanitized_record": f"data/artifacts/{artifact_name}",
        },
        "timing_ms": rec.get("llm_usage", {}).get("totals", {}).get("total_duration_ms", 0),
        "tokens": rec.get("llm_usage", {}).get("totals", {}).get("total_tokens", 0),
        "terminal_for_scenario": False,  # set later
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # Clean artifacts dir
    for f in ARTIFACTS_DIR.glob("*.json"):
        f.unlink()

    runs = []

    # --- Run A: Muse-Glimmer 30B (Uzu) ---
    glimmer_attempts = load_attempts(GLIMMER_ATTEMPTS)
    glimmer_run = {
        "id": "muse-glimmer-30b-uzu-v10",
        "label": "Muse-Glimmer-30B · Uzu",
        "provider": "Uzu local OpenAI-compatible proxy",
        "recorded_at": "2026-10-28T10:34:00Z",
        "source_manifest": "evidence_pack/batch_manifest.json",
        "model": "openai/trymirai/Muse-Glimmer-30B-M",
        "sampling": {"temperature": 1.0, "max_tokens": 4096},
        "cases": [],
    }

    # Match attempts to scenarios
    # safe_copy = seed 42 round 0
    # gdImageJpegPtr = seed 90 (rounds 0 and 1)
    glimmer_cases = []
    for rec in glimmer_attempts:
        seed = rec.get("seed", rec.get("metadata", {}).get("seed"))
        round_num = rec.get("refinement_round", 0)
        if seed == 42:
            scenario = "safe_copy"
        elif seed == 90 or seed == 43:
            scenario = "gdImageJpegPtr"
        else:
            scenario = f"seed_{seed}"

        # Get source code from smoke seed file
        source_code = ""
        smoke_file = ROOT / "foundation" / "scenarios" / "debate" / "cve_seeds_smoke_2gate.jsonl"
        if not smoke_file.exists():
            smoke_file = ROOT / "scenarios" / "debate" / "cve_seeds_smoke_2gate.jsonl"
        if smoke_file.exists():
            lines = smoke_file.read_text().strip().splitlines()
            idx = 0 if scenario == "safe_copy" else 1
            if idx < len(lines):
                sd = json.loads(lines[idx])
                source_code = sd.get("topic", "")

        rec["_source_code"] = source_code
        case = build_case(rec, scenario, "muse-glimmer-30b-uzu-v10", len(glimmer_cases))
        glimmer_cases.append(case)

    # Mark terminal rounds per scenario
    for scenario in ("safe_copy", "gdImageJpegPtr"):
        scenario_cases = [c for c in glimmer_cases if c["scenario_id"] == scenario]
        if scenario_cases:
            max_round = max(c["round"] for c in scenario_cases)
            for c in scenario_cases:
                if c["round"] == max_round:
                    c["terminal_for_scenario"] = True

    glimmer_run["cases"] = glimmer_cases
    runs.append(glimmer_run)

    # --- Run B: Muse Spark Open (Baseten) ---
    spark_attempts = load_attempts(SPARK_ATTEMPTS)
    spark_run = {
        "id": "muse-spark-open-baseten-v13",
        "label": "Muse Spark Open · Baseten",
        "provider": "Baseten hosted inference",
        "recorded_at": "2026-10-30T10:17:35Z",
        "source_manifest": "artifacts/runs/gateol-smoke-v13/batch_manifest.json",
        "model": "openai/meta-models/muse-spark-open-1026",
        "sampling": {"temperature": 1.0, "max_tokens": 4096},
        "cases": [],
    }

    spark_cases = []
    for rec in spark_attempts:
        seed = rec.get("seed", rec.get("metadata", {}).get("seed"))
        round_num = rec.get("refinement_round", 0)
        if seed == 42:
            scenario = "safe_copy"
        else:
            scenario = "gdImageJpegPtr"

        source_code = ""
        smoke_file = ROOT / "foundation" / "scenarios" / "debate" / "cve_seeds_smoke_2gate.jsonl"
        if not smoke_file.exists():
            smoke_file = ROOT / "scenarios" / "debate" / "cve_seeds_smoke_2gate.jsonl"
        if smoke_file.exists():
            lines = smoke_file.read_text().strip().splitlines()
            idx = 0 if scenario == "safe_copy" else 1
            if idx < len(lines):
                sd = json.loads(lines[idx])
                source_code = sd.get("topic", "")

        rec["_source_code"] = source_code
        case = build_case(rec, scenario, "muse-spark-open-baseten-v13", len(spark_cases))
        spark_cases.append(case)

    for scenario in ("safe_copy", "gdImageJpegPtr"):
        scenario_cases = [c for c in spark_cases if c["scenario_id"] == scenario]
        if scenario_cases:
            max_round = max(c["round"] for c in scenario_cases)
            for c in scenario_cases:
                if c["round"] == max_round:
                    c["terminal_for_scenario"] = True

    spark_run["cases"] = spark_cases
    runs.append(spark_run)

    # Build final catalog
    catalog = {
        "schema_version": 1,
        "generated_at": "2026-10-31T00:00:00Z",
        "disclosure": {
            "mode": "recorded_live_artifacts",
            "live_inference_available": False,
        },
        "runs": runs,
    }

    check_no_secrets(catalog)

    # Assert expected cases exist
    all_statuses = [c["status"] for r in runs for c in r["cases"]]
    assert "PASS" in all_statuses, "No PASS case found"
    assert "BLOCKED" in all_statuses, "No BLOCKED case found"
    assert "UNRESOLVED" in all_statuses, "No UNRESOLVED case found"

    # Fail if a PASS lacks deterministically_confirmed
    for r in runs:
        for c in r["cases"]:
            if c["status"] == "PASS":
                assert c["gate_status"] == "deterministically_confirmed", \
                    f"PASS case {c['id']} lacks deterministically_confirmed"

    # Write catalog
    output_path = DATA_DIR / "recorded-runs.v1.json"
    output_path.write_text(json.dumps(catalog, indent=2))
    print(f"Wrote {output_path}")
    print(f"  Runs: {len(runs)}")
    print(f"  Cases: {sum(len(r['cases']) for r in runs)}")
    print(f"  Statuses: {all_statuses}")

    # Write source manifest with SHA-256
    manifest = {
        "sources": {
            "glimmer_attempts": sha256_file(GLIMMER_ATTEMPTS),
            "glimmer_manifest": sha256_file(GLIMMER_MANIFEST),
            "spark_attempts": sha256_file(SPARK_ATTEMPTS),
            "spark_manifest": sha256_file(SPARK_MANIFEST),
        },
        "generated_at": "2026-10-31T00:00:00Z",
    }
    (DATA_DIR / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {DATA_DIR / 'source-manifest.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
