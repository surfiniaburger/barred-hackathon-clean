from scenarios.debate.debate_judge_common import DebateEval


def _payload(counter_evidence):
    return {
        "thinking_process": "test",
        "pro_debater": {"technical_accuracy": 1, "logic_soundness": 1, "evidence_strength": 1, "total_score": 3, "critique": "x"},
        "con_debater": {"technical_accuracy": 1, "logic_soundness": 1, "evidence_strength": 1, "total_score": 3, "critique": "x"},
        "winner": "con_debater",
        "con_candidate_id": "C1",
        "reason": "test",
        "mechanism": "Source anchor: x\nSink anchor: y\nMissing guard anchor: z",
        "counterfactual": "test",
        "predicate": "test",
        "anchors": ["x", "y"],
        "counter_evidence": counter_evidence,
    }


def _counter_evidence():
    return {
        "defense_kind": "null_check",
        "guard_anchor": "if (!ptr) return;",
        "guarded_value": "ptr",
        "protected_operation_anchor": "use(ptr);",
        "operation_value": "ptr",
        "enforcement": "reject_before_operation",
        "invariant": "ptr is non-null",
        "predicate_precondition": "ptr is null",
        "value_relation": "guarded_value_equals_operation_value",
        "counterfactual": "without the check, use(ptr) could run",
    }


def test_debate_eval_unwraps_only_a_single_legacy_counter_evidence_item():
    result = DebateEval.model_validate(_payload([_counter_evidence()]))
    assert result.counter_evidence is not None
    assert result.counter_evidence.guard_anchor == "if (!ptr) return;"


def test_debate_eval_does_not_accept_multiple_counter_evidence_items():
    try:
        DebateEval.model_validate(_payload([_counter_evidence(), _counter_evidence()]))
    except ValueError:
        pass
    else:
        raise AssertionError("multi-item counter evidence must remain invalid")
