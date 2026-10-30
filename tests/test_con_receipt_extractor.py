"""Tests for the deterministic Con receipt extractor (V1)."""

from scenarios.debate.con_receipt_extractor import (
    extract_candidates,
    extract_upper_bound_candidates,
    format_candidates_for_prompt,
)

OBLIGATION = {"version": "v1", "kind": "upper_bound"}


def test_reject_guard_produces_upper_bound_reject():
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}"
    cands = extract_candidates(code, OBLIGATION)
    assert len(cands) == 1
    assert cands[0].defense_kind == "upper_bound_reject"
    assert cands[0].enforcement == "reject_before_operation"
    assert cands[0].guarded_value == "len"
    assert cands[0].operation_value == "len"


def test_safe_branch_guard_produces_range_guarded():
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len <= cap) {\n        memcpy(dst, src, len);\n    }\n}"
    cands = extract_candidates(code, OBLIGATION)
    assert len(cands) == 1
    assert cands[0].defense_kind == "range_guarded_operation"
    assert cands[0].enforcement == "operation_inside_safe_branch"


def test_no_guard_returns_empty():
    code = "void f(char *dst, char *src, int len) {\n    memcpy(dst, src, len);\n}"
    cands = extract_candidates(code, OBLIGATION)
    assert cands == []


def test_no_matching_value_returns_empty():
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, other);\n}"
    cands = extract_candidates(code, OBLIGATION)
    assert cands == []


def test_null_obligation_returns_empty():
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}"
    cands = extract_candidates(code, None)
    assert cands == []


def test_wrong_obligation_kind_returns_empty():
    code = "void f(char *dst, char *src, int len, int cap) {\n    if (len > cap) return;\n    memcpy(dst, src, len);\n}"
    cands = extract_candidates(code, {"version": "v1", "kind": "null_dereference"})
    assert cands == []


def test_candidate_ids_are_immutable_and_sequential():
    code = (
        "void f(char *dst, char *src, int len, int cap, int n) {\n"
        "    if (len > cap) return;\n"
        "    memcpy(dst, src, len);\n"
        "    if (n > cap) return;\n"
        "    memset(dst, 0, n);\n"
        "}"
    )
    cands = extract_candidates(code, OBLIGATION)
    assert len(cands) >= 2
    assert cands[0].candidate_id == "C1"
    assert cands[1].candidate_id == "C2"


def test_format_candidates_empty():
    text = format_candidates_for_prompt([])
    assert "No valid receipt candidates" in text


def test_broad_detected_marked_unsupported():
    # A guard on a non-memory-sink operation should be marked unsupported
    code = "void f(int x, int max) {\n    if (x > max) return;\n    foo_bar(x);\n}"
    cands = extract_candidates(code, OBLIGATION)
    # foo_bar is not a recognized sink, but broad detection may find it
    if cands:
        for c in cands:
            if "foo_bar" in c.protected_operation_anchor:
                assert "operation_not_recognized_sink" in c.unsupported_conditions
