"""End-to-end validator tests for Con receipt V1 (Step 5 of Con Receipt Plan).

Tests the full pipeline: code → extractor → validator, using synthetic candidates.
"""
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock
from agentbeats.models import EvalRequest
from scenarios.debate.debate_judge_common import DebateEval, DebaterScore
from scenarios.debate.adk_debate_judge import DebateJudgeADK, _EvalContext, _collect_soft_checks


from scenarios.debate.counter_evidence_validation import validate_counter_evidence
from scenarios.debate.con_receipt_extractor import extract_candidates, format_candidates_for_prompt

OBLIGATION = {"version": "v1", "kind": "upper_bound", "candidate_ids": None}

# Valid upper-bound reject
VALID_CODE = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}"
VALID_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (len > cap) return;",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "len <= cap before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets len reach memcpy.",
}

# Wrong value: guard checks 'cap', operation uses 'len'
WRONG_VALUE_CODE = "void f(char *dst, char *src, int len, int cap) {\n    if (cap > len) return;\n    memcpy(dst, src, len);\n}"
WRONG_VALUE_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (cap > len) return;",
    "guarded_value": "cap",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "cap <= len before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets cap reach memcpy.",
}

# Guard after operation (non-dominating)
GUARD_AFTER_CODE = "void f(char *dst, char *src, int len, int cap) {\n    memcpy(dst, src, len);\n    if (len > cap) return;\n}"
GUARD_AFTER_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (len > cap) return;",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "len <= cap before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets len reach memcpy.",
}

# Incompatible pairing: null_check with wrong value_relation
MISMATCH_CODE = "void f(int *p) {\n    if (p == NULL) return;\n    *p = 42;\n}"
MISMATCH_EVIDENCE = {
    "defense_kind": "null_check",
    "guard_anchor": "if (p == NULL) return;",
    "guarded_value": "p",
    "protected_operation_anchor": "*p = 42;",
    "operation_value": "p",
    "enforcement": "operation_inside_safe_branch",
    "invariant": "p is non-null before deref",
    "predicate_precondition": "p is null",
    "value_relation": "guarded_value_bounds_offset_plus_width",
    "counterfactual": "Removing guard lets null p be dereferenced.",
}


def test_e2e_valid_receipt_confirmed():
    r = validate_counter_evidence(VALID_CODE, "copy can overflow", VALID_EVIDENCE, OBLIGATION)
    assert r["status"] == "deterministically_confirmed", r


def test_e2e_wrong_value_not_confirmed():
    r = validate_counter_evidence(WRONG_VALUE_CODE, "copy can overflow", WRONG_VALUE_EVIDENCE, OBLIGATION)
    assert r["status"] != "deterministically_confirmed", r


def test_e2e_guard_after_not_confirmed():
    r = validate_counter_evidence(GUARD_AFTER_CODE, "copy can overflow", GUARD_AFTER_EVIDENCE, OBLIGATION)
    assert r["status"] != "deterministically_confirmed", r


def test_e2e_incompatible_pairing_rejected():
    obl = {"version": "v1", "kind": "null_dereference"}
    ev = dict(MISMATCH_EVIDENCE)
    ev["defense_kind"] = "null_check"
    r = validate_counter_evidence(MISMATCH_CODE, "null deref", ev, obl)
    assert r["status"] == "invalid_contract", r
    assert "counter_evidence_incompatible_pairing" in r["failure_reasons"], r


def test_e2e_extractor_produces_valid_candidate():
    cands = extract_candidates(VALID_CODE, OBLIGATION)
    assert len(cands) >= 1
    # Complete the extractor candidate with the missing receipt fields
    ev = cands[0].to_dict()
    ev.pop("source_span", None)
    ev.pop("unsupported_conditions", None)
    ev.setdefault("invariant", "len <= cap before copy")
    ev.setdefault("predicate_precondition", "len exceeds capacity")
    ev.setdefault("counterfactual", "Removing guard lets len reach memcpy.")
    r = validate_counter_evidence(VALID_CODE, "copy can overflow", ev, OBLIGATION)
    assert r["status"] == "deterministically_confirmed", r


def test_e2e_extractor_candidate_with_incompatible_pairing_rejected():
    # range_guarded_operation candidate should have compatible enforcement/value_relation
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len <= cap) {\n        memcpy(dst, src, len);\n    }\n}"
    cands = extract_candidates(code, OBLIGATION)
    assert len(cands) >= 1
    ev = cands[0].to_dict()
    ev.pop("source_span", None)
    ev.pop("unsupported_conditions", None)
    ev.setdefault("invariant", "len <= cap before copy")
    ev.setdefault("predicate_precondition", "len exceeds capacity")
    ev.setdefault("counterfactual", "Removing guard lets len reach memcpy.")
    r = validate_counter_evidence(code, "copy can overflow", ev, OBLIGATION)
    assert r["status"] == "deterministically_confirmed", r


# --- Non-recognized operation (broad-detected) ---
BROAD_CODE = "void f(int x, int max) {\n    if (x > max) return;\n    foo_bar(x);\n}"
BROAD_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (x > max) return;",
    "guarded_value": "x",
    "protected_operation_anchor": "foo_bar(x)",
    "operation_value": "x",
    "enforcement": "reject_before_operation",
    "invariant": "x <= max before foo_bar",
    "predicate_precondition": "x exceeds max",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets x reach foo_bar.",
}


def test_e2e_broad_detected_rejected_without_trusted_summary():
    """An unrecognized sink with a structurally plausible guard is flagged by
    the extractor (operation_not_recognized_sink). The validator does NOT
    confirm it based on structural proof alone — it requires a trusted
    operation summary to establish the operation's semantics. Without one,
    the result is invalid_contract (counter_evidence_unrecognized_operation).
    This closes the semantic-validation gap: structural proof alone is
    insufficient for unrecognized operations."""
    cands = extract_candidates(BROAD_CODE, OBLIGATION)
    assert len(cands) >= 1
    assert "operation_not_recognized_sink" in cands[0].unsupported_conditions
    # Without trusted_operation_summary, the validator rejects.
    r = validate_counter_evidence(BROAD_CODE, "foo_bar overflow", BROAD_EVIDENCE, OBLIGATION)
    assert r["status"] == "invalid_contract", r
    assert "counter_evidence_unrecognized_operation" in r["failure_reasons"], r



# --- Candidate selection tests (Step 3 integration) ---

CANDIDATE_CODE = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}"


def _make_candidate_ctx(judge, req, code=CANDIDATE_CODE):
    """Helper: create an _EvalContext with extracted candidates stored."""
    from scenarios.debate.con_receipt_extractor import extract_candidates
    from scenarios.debate.adk_debate_judge import _EvalContext
    ctx = _EvalContext(req, judge)
    obl = {"version": "v1", "kind": "upper_bound"}
    ctx.defense_obligation = obl
    ctx.last_con_candidates = extract_candidates(code, obl)
    return ctx


@pytest.mark.asyncio
async def test_candidate_selection_valid_id_accepted():
    """Con selects a valid candidate ID (C1) → resolved receipt validates → accepted."""
    with tempfile.TemporaryDirectory() as td:
        req = EvalRequest(
            participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
            config={
                "run_id": "test-cand-valid",
                "seed": 42,
                "mode": "passthrough",
                "topic": "test",
                "predicate": "Vulnerable to heap overflow",
                "target_verdict": "True",
                "record_path": os.path.join(td, "run.json"),
                "attempts_path": os.path.join(td, "attempts.jsonl"),
                "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            },
        )
        judge = DebateJudgeADK()
        ctx = _make_candidate_ctx(judge, req)

        pro = DebaterScore(technical_accuracy=0.3, logic_soundness=0.3, evidence_strength=0.3, total_score=0.3, critique="Pro argued")
        con = DebaterScore(technical_accuracy=0.9, logic_soundness=0.9, evidence_strength=0.9, total_score=0.9, critique="Con proved bounds check")
        debate_eval = DebateEval(
            thinking_process="Thinking...",
            predicate="Vulnerable to heap overflow",
            anchors=["len > cap", "memcpy(dst, src, len)"],
            winner="con_debater",
            outcome="con_win",
            reason="Code contains a strict bounds check.",
            mechanism="Guard anchor: if (len > cap) return;",
            counterfactual="If guard removed",
            support_level="supported",
            verifier_report="Passed",
            pro_debater=pro,
            con_debater=con,
            con_candidate_id="C1",
        )
        normalized_anchors = ["len > cap", "memcpy(dst, src, len)"]
        soft_checks = {
            "con_win_counter_evidence": {"pass": True, "applicable": True},
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        judge._restore_or_call_verifier = AsyncMock()

        # _collect_soft_checks resolves the candidate; simulate by setting ctx.last_con_receipt
        # The actual _process_verifier_audit calls _collect_soft_checks internally in run_eval,
        # but here we call it directly. Let's call _collect_soft_checks first.
        sc, as_ = _collect_soft_checks(ctx, debate_eval, CANDIDATE_CODE, normalized_anchors)
        soft_checks = sc

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, CANDIDATE_CODE, normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )

        assert is_valid is True, meta
        assert meta["error"] == "validated_con_counter_evidence"
        judge._restore_or_call_verifier.assert_not_called()


@pytest.mark.asyncio
async def test_candidate_selection_unknown_id_rejected():
    """Con selects a non-existent candidate ID (C99) → rejected (unknown candidate)."""
    with tempfile.TemporaryDirectory() as td:
        req = EvalRequest(
            participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
            config={
                "run_id": "test-cand-unknown",
                "seed": 42,
                "mode": "passthrough",
                "topic": "test",
                "predicate": "Vulnerable to heap overflow",
                "target_verdict": "True",
                "record_path": os.path.join(td, "run.json"),
                "attempts_path": os.path.join(td, "attempts.jsonl"),
                "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            },
        )
        judge = DebateJudgeADK()
        ctx = _make_candidate_ctx(judge, req)

        pro = DebaterScore(technical_accuracy=0.3, logic_soundness=0.3, evidence_strength=0.3, total_score=0.3, critique="Pro argued")
        con = DebaterScore(technical_accuracy=0.9, logic_soundness=0.9, evidence_strength=0.9, total_score=0.9, critique="Con proved bounds check")
        debate_eval = DebateEval(
            thinking_process="Thinking...",
            predicate="Vulnerable to heap overflow",
            anchors=["len > cap", "memcpy(dst, src, len)"],
            winner="con_debater",
            outcome="con_win",
            reason="Code contains a strict bounds check.",
            mechanism="Guard anchor: if (len > cap) return;",
            counterfactual="If guard removed",
            support_level="supported",
            verifier_report="Passed",
            pro_debater=pro,
            con_debater=con,
            con_candidate_id="C99",
        )
        normalized_anchors = ["len > cap", "memcpy(dst, src, len)"]
        soft_checks = {
            "con_win_counter_evidence": {"pass": True, "applicable": True},
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        judge._restore_or_call_verifier = AsyncMock()

        sc, as_ = _collect_soft_checks(ctx, debate_eval, CANDIDATE_CODE, normalized_anchors)
        soft_checks = sc

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, CANDIDATE_CODE, normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )

        assert is_valid is False
        judge._restore_or_call_verifier.assert_not_called()


@pytest.mark.asyncio
async def test_candidate_selection_no_candidate_unresolved():
    """Con with no candidate ID → unresolved outcome survives (not accepted)."""
    with tempfile.TemporaryDirectory() as td:
        req = EvalRequest(
            participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
            config={
                "run_id": "test-cand-none",
                "seed": 42,
                "mode": "passthrough",
                "topic": "test",
                "predicate": "Vulnerable to heap overflow",
                "target_verdict": "True",
                "record_path": os.path.join(td, "run.json"),
                "attempts_path": os.path.join(td, "attempts.jsonl"),
                "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            },
        )
        judge = DebateJudgeADK()
        ctx = _make_candidate_ctx(judge, req)

        pro = DebaterScore(technical_accuracy=0.3, logic_soundness=0.3, evidence_strength=0.3, total_score=0.3, critique="Pro argued")
        con = DebaterScore(technical_accuracy=0.9, logic_soundness=0.9, evidence_strength=0.9, total_score=0.9, critique="Con proved bounds check")
        debate_eval = DebateEval(
            thinking_process="Thinking...",
            predicate="Vulnerable to heap overflow",
            anchors=["len > cap", "memcpy(dst, src, len)"],
            winner=None,
            outcome="unresolved",
            reason="No candidate proves the defense.",
            mechanism="Guard anchor: if (len > cap) return;",
            counterfactual="If guard removed",
            support_level="inconclusive",
            verifier_report="Passed",
            pro_debater=pro,
            con_debater=con,
        )
        normalized_anchors = ["len > cap", "memcpy(dst, src, len)"]
        soft_checks = {
            "con_win_counter_evidence": {"pass": False, "applicable": True},
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        judge._restore_or_call_verifier = AsyncMock()

        sc, as_ = _collect_soft_checks(ctx, debate_eval, CANDIDATE_CODE, normalized_anchors)
        soft_checks = sc

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, CANDIDATE_CODE, normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )

        assert is_valid is False
        assert debate_eval.outcome == "unresolved"
        assert debate_eval.con_candidate_id is None
        judge._restore_or_call_verifier.assert_not_called()


@pytest.mark.asyncio
async def test_no_free_text_receipt_enforcement():
    """Model-supplied counter_evidence is ignored when con_candidate_id is present."""
    with tempfile.TemporaryDirectory() as td:
        req = EvalRequest(
            participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
            config={
                "run_id": "test-no-freetext",
                "seed": 42,
                "mode": "passthrough",
                "topic": "test",
                "predicate": "Vulnerable to heap overflow",
                "target_verdict": "True",
                "record_path": os.path.join(td, "run.json"),
                "attempts_path": os.path.join(td, "attempts.jsonl"),
                "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            },
        )
        judge = DebateJudgeADK()
        ctx = _make_candidate_ctx(judge, req)

        pro = DebaterScore(technical_accuracy=0.3, logic_soundness=0.3, evidence_strength=0.3, total_score=0.3, critique="Pro argued")
        con = DebaterScore(technical_accuracy=0.9, logic_soundness=0.9, evidence_strength=0.9, total_score=0.9, critique="Con proved bounds check")
        # Model tries to supply both con_candidate_id AND a free-text counter_evidence
        free_text_ce = {
            "defense_kind": "upper_bound_reject",
            "guard_anchor": "if (FAKE > 0) return;",
            "guarded_value": "FAKE",
            "protected_operation_anchor": "memcpy(dst, src, FAKE)",
            "operation_value": "FAKE",
            "enforcement": "reject_before_operation",
            "invariant": "fake",
            "predicate_precondition": "fake",
            "value_relation": "guarded_value_equals_operation_value",
            "counterfactual": "fake",
        }
        debate_eval = DebateEval(
            thinking_process="Thinking...",
            predicate="Vulnerable to heap overflow",
            anchors=["len > cap", "memcpy(dst, src, len)"],
            winner="con_debater",
            outcome="con_win",
            reason="Code contains a strict bounds check.",
            mechanism="Guard anchor: if (len > cap) return;",
            counterfactual="If guard removed",
            support_level="supported",
            verifier_report="Passed",
            pro_debater=pro,
            con_debater=con,
            con_candidate_id="C1",
        )
        normalized_anchors = ["len > cap", "memcpy(dst, src, len)"]
        soft_checks = {
            "con_win_counter_evidence": {"pass": True, "applicable": True},
        }

        updater = MagicMock()
        updater.update_status = AsyncMock()

        judge._restore_or_call_verifier = AsyncMock()

        sc, as_ = _collect_soft_checks(ctx, debate_eval, CANDIDATE_CODE, normalized_anchors)
        soft_checks = sc

        is_valid, report, meta, reason = await judge._process_verifier_audit(
            ctx, 0, debate_eval, CANDIDATE_CODE, normalized_anchors, soft_checks, {}, {}, None, "start", updater
        )

        # The resolved receipt comes from the candidate (C1), not the free-text.
        # The free-text anchors (FAKE) should not appear in the validated receipt.
        assert is_valid is True, meta
        # Verify the receipt used the candidate's anchors, not the free-text ones
        receipt = soft_checks.get("counter_evidence_validation") or {}
        assert "FAKE" not in str(receipt), "Free-text receipt was used instead of candidate"
        judge._restore_or_call_verifier.assert_not_called()


@pytest.mark.asyncio
async def test_server_side_resolution():
    """The runtime resolves con_candidate_id to the candidate's receipt, not the model's."""
    with tempfile.TemporaryDirectory() as td:
        req = EvalRequest(
            participants={"pro_debater": "http://localhost:9001", "con_debater": "http://localhost:9002"},
            config={
                "run_id": "test-server-resolve",
                "seed": 42,
                "mode": "passthrough",
                "topic": "test",
                "predicate": "Vulnerable to heap overflow",
                "target_verdict": "True",
                "record_path": os.path.join(td, "run.json"),
                "attempts_path": os.path.join(td, "attempts.jsonl"),
                "defense_obligation": {"version": "v1", "kind": "upper_bound"},
            },
        )
        judge = DebateJudgeADK()
        ctx = _make_candidate_ctx(judge, req)

        # Verify candidates were extracted
        assert len(ctx.last_con_candidates) >= 1
        assert ctx.last_con_candidates[0].candidate_id == "C1"

        # Verify the candidate's receipt validates
        c = ctx.last_con_candidates[0]
        ev = c.to_dict()
        ev.pop("source_span", None)
        ev.pop("unsupported_conditions", None)
        ev.setdefault("invariant", "len <= cap before copy")
        ev.setdefault("predicate_precondition", "len exceeds capacity")
        ev.setdefault("counterfactual", "Removing guard lets len reach memcpy.")
        from scenarios.debate.counter_evidence_validation import validate_counter_evidence
        r = validate_counter_evidence(CANDIDATE_CODE, "copy can overflow", ev, {"version": "v1", "kind": "upper_bound"})
        assert r["status"] == "deterministically_confirmed", r
