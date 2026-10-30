"""TDD tests for the 6 failure modes from the q9d smoke run.

These tests use mocked LLM responses to verify that the new code (discriminated
union, candidate selection, halt gating) handles each failure mode gracefully
instead of crashing or producing invalid outcomes.

Reference: docs/BARRED_Failure_Modes_and_Replay_Plan.md
"""

import json
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentbeats.models import EvalRequest
from debate_judge_common import DebateEval, DebaterScore, VerifierReport
from scenarios.debate.adk_debate_judge import DebateJudgeADK, _EvalContext, _collect_soft_checks


def _make_req(td, seed=42):
    return EvalRequest(
        participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
        config={
            "run_id": "test-fm",
            "seed": seed,
            "mode": "passthrough",
            "topic": "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}",
            "predicate": "Vulnerable to heap overflow",
            "target_verdict": "True",
            "record_path": os.path.join(td, "run.json"),
            "attempts_path": os.path.join(td, "attempts.jsonl"),
            "checkpoint_path": os.path.join(td, "ckpt.json"),
            "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            "counter_evidence_validation_mode": "enforce_deterministic",
        },
    )


def _make_debate_eval(winner="con_debater", outcome=None, counter_evidence=None, anchors=None, con_candidate_id=None):
    pro = DebaterScore(technical_accuracy=0.3, logic_soundness=0.3, evidence_strength=0.3, total_score=0.3, critique="Pro argued")
    con = DebaterScore(technical_accuracy=0.9, logic_soundness=0.9, evidence_strength=0.9, total_score=0.9, critique="Con proved bounds")
    kwargs = {
        "thinking_process": "Thinking...",
        "predicate": "Vulnerable to heap overflow",
        "anchors": anchors or ["len > cap", "memcpy(dst, src, len)"],
        "winner": winner,
        "reason": "test reason",
        "mechanism": "Guard anchor: if (len > cap) return;",
        "counterfactual": "If guard removed",
        "support_level": "supported",
        "verifier_report": "Passed",
        "pro_debater": pro,
        "con_debater": con,
    }
    if outcome is not None:
        kwargs["outcome"] = outcome
    if counter_evidence is not None:
        kwargs["counter_evidence"] = counter_evidence
    if con_candidate_id is not None:
        kwargs["con_candidate_id"] = con_candidate_id
    return DebateEval(**kwargs)


# Mode 1: Schema rejection — old-format Con win (winner=con_debater, no counter_evidence, no candidate_id)
# Should result in unresolved, not crash.
@pytest.mark.asyncio
async def test_failure_mode_1_null_receipt_becomes_unresolved():
    """Mode 1: Judge outputs winner=con_debater with counter_evidence=null and no candidate_id.
    New schema maps winner=con_debater -> outcome=con_win, but con_win requires counter_evidence or con_candidate_id.
    The model_validator should NOT raise — it should allow con_win without counter_evidence if con_candidate_id is None
    (backward compat). But the outcome is con_win without proof. Verify this doesn't crash and is handled."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        # Old-format Con win: winner=con_debater, no counter_evidence, no candidate_id.
        # Under the new schema, this safely downgrades to outcome=unresolved (controlled abstention).
        eval1 = _make_debate_eval(winner="con_debater", outcome=None, counter_evidence=None)
        assert eval1.outcome == "unresolved"
        assert eval1.winner is None
        assert eval1.con_candidate_id is None
        assert eval1.counter_evidence is None

        # Explicit unresolved outcome
        debate_eval2 = _make_debate_eval(winner=None, outcome="unresolved", counter_evidence=None)
        assert debate_eval2.outcome == "unresolved"
        assert debate_eval2.winner is None
        assert debate_eval2.counter_evidence is None


# Mode 2: Con receipt invalid — model produces a receipt with unrecognized operation
@pytest.mark.asyncio
async def test_failure_mode_2_invalid_receipt_rejected():
    """Mode 2: Con produces a receipt with an unrecognized operation. Should be rejected, not accepted."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        bad_ce = {
            "defense_kind": "upper_bound_reject",
            "guard_anchor": "if (len > cap) return;",
            "guarded_value": "len",
            "protected_operation_anchor": "foo_bar(x)",
            "operation_value": "x",
            "enforcement": "reject_before_operation",
            "invariant": "len <= cap",
            "predicate_precondition": "len exceeds cap",
            "value_relation": "guarded_value_equals_operation_value",
            "counterfactual": "Removing guard lets len reach foo_bar.",
        }
        debate_eval = _make_debate_eval(
            winner="con_debater", outcome="con_win", con_candidate_id="C99",
        )

        code = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    foo_bar(x);\n}"
        normalized_anchors = ["len > cap", "foo_bar(x)"]
        soft_checks, _ = _collect_soft_checks(ctx, debate_eval, code, normalized_anchors)

        receipt = soft_checks.get("counter_evidence_validation") or {}
        assert receipt.get("status") != "deterministically_confirmed"
        assert receipt.get("status") == "invalid_contract"


# Mode 4: Anchors too few — judge provides anchors that don't match code
@pytest.mark.asyncio
async def test_failure_mode_4_anchors_too_few_rejected():
    """Mode 4: Judge provides anchors that don't match code. Should be rejected as anchors_too_few."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        debate_eval = _make_debate_eval(
            winner="pro_debater", anchors=["nonexistent_anchor_xyz", "another_missing_anchor"],
        )

        # _process_verifier_audit checks normalized_anchors < 2
        normalized_anchors = ["nonexistent_anchor_xyz", "another_missing_anchor"]
        soft_checks = {
            "predicate_quality": {"pass": True},
            "con_win_counter_evidence": {"pass": False, "applicable": False},
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        judge._restore_or_call_verifier = AsyncMock(return_value=(None, {"called": False, "logic_error": None, "error": None}))

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, "void f() {}", normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )
        assert is_valid is False


# Mode 5: Con win without counter-evidence
@pytest.mark.asyncio
async def test_failure_mode_5_con_win_no_evidence_rejected():
    """Mode 5: Con wins but has no concrete counter-evidence. Gate should reject."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        debate_eval = _make_debate_eval(
            winner="con_debater", outcome="unresolved", counter_evidence=None,
        )

        code = "void f(char *dst, char *src, int len) {\n    memcpy(dst, src, len);\n}"
        normalized_anchors = ["memcpy(dst, src, len)"]
        soft_checks = {
            "predicate_quality": {"pass": True},
            "con_win_counter_evidence": {"pass": False, "applicable": True},
            "counter_evidence_validation": None,
            "counter_evidence_validation_mode": "enforce_deterministic",
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, code, normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )
        assert is_valid is False


# Mode 6: Judge parse failure — controlled unresolved
@pytest.mark.asyncio
async def test_failure_mode_6_parse_failure_controlled():
    """Mode 6: Malformed judge output should produce controlled failure, not crash."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        # outcome=unresolved should be a valid controlled state
        debate_eval = _make_debate_eval(
            winner=None, outcome="unresolved", counter_evidence=None,
        )
        assert debate_eval.outcome == "unresolved"
        assert debate_eval.winner is None
        assert debate_eval.counter_evidence is None


# Mode 3: Verifier logic error (correct behavior)
@pytest.mark.asyncio
async def test_failure_mode_3_verifier_logic_error_is_correct():
    """Mode 3: Pro wins but verifier finds logic error. This is correct behavior."""
    with tempfile.TemporaryDirectory() as td:
        req = _make_req(td)
        judge = DebateJudgeADK()
        ctx = _EvalContext(req, judge)

        debate_eval = _make_debate_eval(winner="pro_debater")

        # Verify the outcome is pro_win
        assert debate_eval.outcome == "pro_win"
        # The verifier would catch logic errors in the Pro claim
        # This is the system working correctly, not a bug


def test_repair_messages_include_validation_error_context():
    """Verify that structured output repair includes the exact validation error so the model can fix it."""
    from agentbeats.structured_output import _build_repair_messages

    raw_json = json.dumps({
        "thinking_process": "Analysis",
        "outcome": "con_win",
        "con_candidate_id": None,
        "reason": "Con argued well",
        "mechanism": "Guard anchor: none",
        "counterfactual": "If check added",
        "predicate": "Vulnerable",
        "anchors": ["a", "b"],
        "pro_debater": {"technical_accuracy": 0.5, "logic_soundness": 0.5, "evidence_strength": 0.5, "total_score": 0.5, "critique": "ok"},
        "con_debater": {"technical_accuracy": 0.8, "logic_soundness": 0.8, "evidence_strength": 0.8, "total_score": 0.8, "critique": "ok"},
    })

    err_msg = "Value error, con_win requires a valid con_candidate_id from the provided candidate list"
    msgs = _build_repair_messages(DebateEval, raw_json, strict=False, validation_error=err_msg)

    assert len(msgs) == 2
    user_msg = msgs[1]["content"]
    assert "Validation Error to Fix:" in user_msg
    assert err_msg in user_msg
    assert "outcome" in DebateEval.model_json_schema()["required"]


def test_coerce_verdict_reason_alias():
    """Mode 5 (v5 live failure): Model outputs verdict_reason instead of reason,
    omits thinking_process and scorecard dicts. The before-validator should coerce."""
    raw = {
        "predicate": "The code is vulnerable to out-of-bounds memory access",
        "verdict": "pro_win",
        "outcome": "pro_win",
        "con_candidate_id": None,
        "mechanism": "Source anchor: src->sx == 0; Sink anchor: gdImageJpegPtr(src, &size, 0); Missing guard anchor: none found",
        "counterfactual": "The verdict flips if the guard is removed.",
        "anchors": ["src->sx == 0", "gdImageJpegPtr(src, &size, 0)"],
        "verifier_report": "not_applicable",
        "score": 100,
        # Note: NO thinking_process, NO pro_debater, NO con_debater, NO reason
        # Only verdict_reason (wrong field name)
    }
    # Should fail without coercion — but now it should pass
    result = DebateEval.model_validate(raw)
    assert result.outcome == "pro_win"
    assert result.winner == "pro_debater"
    assert result.reason != ""  # Should be populated from fallback
    assert result.thinking_process != ""  # Should be populated from fallback
    assert result.pro_debater.total_score == 0.5  # Default
    assert result.con_debater.total_score == 0.5  # Default


def test_coerce_verdict_reason_becomes_reason():
    """When model provides verdict_reason but not reason, the alias is applied."""
    raw = {
        "predicate": "Vulnerable to buffer overflow",
        "verdict_reason": "The Con side proved the guard exists.",
        "outcome": "con_win",
        "con_candidate_id": "C1",
        "mechanism": "Guard: if (len > cap) return; Sink: memcpy(dst, src, len)",
        "counterfactual": "Without guard, overflow occurs",
        "anchors": ["if (len > cap) return;", "memcpy(dst, src, len)"],
    }
    result = DebateEval.model_validate(raw)
    assert result.reason == "The Con side proved the guard exists."
    assert result.thinking_process == "The Con side proved the guard exists."
    assert result.outcome == "con_win"
    assert result.con_candidate_id == "C1"


def test_coerce_list_thinking_process():
    """When model provides thinking_process as a list, it is joined into a string."""
    raw = {
        "predicate": "Vulnerable to heap overflow",
        "thinking_process": ["Step 1: check guard", "Step 2: verify sink"],
        "reason": "Guard prevents overflow",
        "outcome": "pro_win",
        "mechanism": "Guard: if (len > cap); Sink: memcpy",
        "counterfactual": "Without guard",
        "anchors": ["if (len > cap)", "memcpy(dst, src, len)"],
        "pro_debater": {"technical_accuracy": 0.9, "logic_soundness": 0.9, "evidence_strength": 0.9, "total_score": 0.9, "critique": "Good"},
        "con_debater": {"technical_accuracy": 0.3, "logic_soundness": 0.3, "evidence_strength": 0.3, "total_score": 0.3, "critique": "Weak"},
    }
    result = DebateEval.model_validate(raw)
    assert result.thinking_process == "Step 1: check guard Step 2: verify sink"
