"""Validator fixtures for counter-evidence V1 (Step 1 of Con Receipt Plan).

Positive fixtures: code snippets where the validator should return
`deterministically_confirmed`.

Negative fixtures: code snippets where the validator should NOT confirm
(invalid_contract, refuted, or inconclusive).
"""

from scenarios.debate.counter_evidence_validation import validate_counter_evidence

OBLIGATION = {"version": "v1", "kind": "upper_bound"}

# --- Positive: upper_bound_reject (guard rejects before operation) ---
POS_UPPER_REJECT_CODE = (
    "void copy(char *dst, char *src, int len, int capacity) {\n"
    "    if (len > capacity) return;\n"
    "    memcpy(dst, src, len);\n"
    "}"
)
POS_UPPER_REJECT_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (len > capacity) return;",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "len <= capacity before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing if (len > capacity) return; lets len reach memcpy.",
}

# --- Positive: range_guarded_operation (operation inside safe branch) ---
POS_RANGE_GUARDED_CODE = (
    "void copy(char *dst, char *src, int len, int capacity) {\n"
    "    if (len <= capacity) {\n"
    "        memcpy(dst, src, len);\n"
    "    }\n"
    "}"
)
POS_RANGE_GUARDED_EVIDENCE = {
    "defense_kind": "range_guarded_operation",
    "guard_anchor": "if (len <= capacity) {",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "operation_inside_safe_branch",
    "invariant": "len <= capacity inside branch",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing the if guard lets unchecked len reach memcpy.",
}

# --- Negative: guard protects wrong value ---
NEG_WRONG_VALUE_CODE = (
    "void copy(char *dst, char *src, int len, int capacity) {\n"
    "    if (size > capacity) return;\n"
    "    memcpy(dst, src, len);\n"
    "}"
)
NEG_WRONG_VALUE_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (size > capacity) return;",
    "guarded_value": "size",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "size <= capacity before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets size reach memcpy.",
}

# --- Negative: guard after operation (no dominance) ---
NEG_GUARD_AFTER_CODE = (
    "void copy(char *dst, char *src, int len, int capacity) {\n"
    "    memcpy(dst, src, len);\n"
    "    if (len > capacity) return;\n"
    "}"
)
NEG_GUARD_AFTER_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (len > capacity) return;",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "len <= capacity before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets len reach memcpy.",
}

# --- Negative: enforcement/value_relation mismatch (null_check with safe-branch relation) ---
NEG_MISMATCH_CODE = (
    "void deref(int *p) {\n"
    "    if (p == NULL) return;\n"
    "    *p = 42;\n"
    "}"
)
NEG_MISMATCH_EVIDENCE = {
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

# --- Negative: missing defense_obligation ---
NEG_NO_OBLIGATION_CODE = POS_UPPER_REJECT_CODE
NEG_NO_OBLIGATION_EVIDENCE = POS_UPPER_REJECT_EVIDENCE

# --- Negative: anchor not in code ---
NEG_BAD_ANCHOR_CODE = POS_UPPER_REJECT_CODE
NEG_BAD_ANCHOR_EVIDENCE = {
    "defense_kind": "upper_bound_reject",
    "guard_anchor": "if (x > y) return;",
    "guarded_value": "len",
    "protected_operation_anchor": "memcpy(dst, src, len)",
    "operation_value": "len",
    "enforcement": "reject_before_operation",
    "invariant": "len <= capacity before copy",
    "predicate_precondition": "len exceeds capacity",
    "value_relation": "guarded_value_equals_operation_value",
    "counterfactual": "Removing guard lets len reach memcpy.",
}


def test_pos_upper_reject_confirmed():
    r = validate_counter_evidence(POS_UPPER_REJECT_CODE, "copy can overflow", POS_UPPER_REJECT_EVIDENCE, OBLIGATION)
    assert r["status"] == "deterministically_confirmed", r


def test_pos_range_guarded_confirmed():
    r = validate_counter_evidence(POS_RANGE_GUARDED_CODE, "copy can overflow", POS_RANGE_GUARDED_EVIDENCE, OBLIGATION)
    assert r["status"] == "deterministically_confirmed", r


def test_neg_wrong_value_not_confirmed():
    r = validate_counter_evidence(NEG_WRONG_VALUE_CODE, "copy can overflow", NEG_WRONG_VALUE_EVIDENCE, OBLIGATION)
    assert r["status"] != "deterministically_confirmed"


def test_neg_guard_after_not_confirmed():
    r = validate_counter_evidence(NEG_GUARD_AFTER_CODE, "copy can overflow", NEG_GUARD_AFTER_EVIDENCE, OBLIGATION)
    assert r["status"] != "deterministically_confirmed"


def test_neg_missing_obligation():
    r = validate_counter_evidence(NEG_NO_OBLIGATION_CODE, "copy can overflow", NEG_NO_OBLIGATION_EVIDENCE, None)
    assert r["status"] == "invalid_contract"
    assert "counter_evidence_missing_defense_obligation" in r["failure_reasons"]


def test_neg_bad_anchor():
    r = validate_counter_evidence(NEG_BAD_ANCHOR_CODE, "copy can overflow", NEG_BAD_ANCHOR_EVIDENCE, OBLIGATION)
    assert r["status"] == "invalid_contract"
    assert "counter_evidence_guard_not_found" in r["failure_reasons"]


def test_neg_mismatch_null_check():
    obl = {"version": "v1", "kind": "null_dereference"}
    ev = dict(NEG_MISMATCH_EVIDENCE)
    ev["defense_kind"] = "null_check"
    r = validate_counter_evidence(NEG_MISMATCH_CODE, "null deref", ev, obl)
    # Should NOT be confirmed because enforcement/value_relation are incompatible
    assert r["status"] != "deterministically_confirmed", r
