"""Deterministic Con counter-evidence candidate extractor (V1).

Parses a C code snippet and emits a small set of candidate receipt objects
that the judge can select from (or abstain).  The judge does not invent
anchors, values, or labels; it chooses a candidate ID or returns "no valid
receipt".  The independent validator then determines whether the selected
candidate actually proves the defense.

V1 supports only the ``upper_bound`` defense family.  Other families
(``null_dereference``, ``identity_mismatch``) are deferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CandidateReceipt:
    """A candidate counter-evidence receipt emitted by the extractor."""

    candidate_id: str
    defense_kind: str  # upper_bound_reject | range_guarded_operation
    guard_anchor: str
    guarded_value: str
    protected_operation_anchor: str
    operation_value: str
    enforcement: str  # reject_before_operation | operation_inside_safe_branch
    value_relation: str  # guarded_value_equals_operation_value
    source_span: dict = field(default_factory=dict)
    unsupported_conditions: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "defense_kind": self.defense_kind,
            "guard_anchor": self.guard_anchor,
            "guarded_value": self.guarded_value,
            "protected_operation_anchor": self.protected_operation_anchor,
            "operation_value": self.operation_value,
            "enforcement": self.enforcement,
            "value_relation": self.value_relation,
            "source_span": self.source_span,
            "unsupported_conditions": self.unsupported_conditions,
        }


# Memory-operation sinks that a guard might protect.
_MEMORY_SINKS = {
    "memcpy", "memmove", "strcpy", "strncpy", "strcat", "strncat",
    "sprintf", "snprintf", "memset", "free", "kfree", "bcopy",
}

_MEMORY_OPS = re.compile(
    r"(memcpy|memmove|strcpy|strncpy|strcat|strncat|sprintf|snprintf|memset|free|kfree)\s*\([^)]*?\)"
)

# if-guard with a relational comparison: if (VAR OP EXPR) { ... } or if (VAR OP EXPR) return/goto;
_GUARD_RE = re.compile(
    r"if\s*\(\s*(\w+)\s*(>=|<=|!=|==|>|<)\s*([^)]++)\)",
    re.MULTILINE,
)

# Variable names commonly used as bounds in guards
_BOUND_NAMES = {"capacity", "max", "maxlen", "size", "limit", "n", "len", "max_size", "buf_size"}


def _find_guards(code: str) -> List[Dict[str, Any]]:
    """Find if-guards with relational comparisons. Returns list of dicts."""
    guards = []
    for m in _GUARD_RE.finditer(code):
        var = m.group(1)
        op = m.group(2)
        guard_text = m.group(0).rstrip()
        # Check the tail (text immediately after the closing paren) for reject keywords
        tail_start = m.end()
        tail = code[tail_start:tail_start + 40]
        is_reject = any(kw in tail for kw in ("return", "goto", "break"))
        enforcement = "reject_before_operation" if is_reject else "operation_inside_safe_branch"
        if is_reject:
            # Extend guard_text to include the reject statement
            import re as _re
            reject_match = _re.match(r"\s*(return[^;]*;|goto\s+\w+;|break;)", tail)
            if reject_match:
                guard_text = code[m.start():tail_start + reject_match.end()].rstrip()
        guards.append({
            "var": var,
            "op": op,
            "guard_text": guard_text,
            "enforcement": enforcement,
            "start": m.start(),
            "end": m.end() + (len(guard_text) - (m.end() - m.start())),
            "is_reject": is_reject,
        })
    return guards


def _find_operations(code: str) -> List[Dict[str, Any]]:
    """Find memory-operation sinks in the code."""
    ops = []
    for m in _MEMORY_OPS.finditer(code):
        op_text = m.group(0)
        # Extract the first argument (destination or size) as the operation value
        # Heuristic: if the op has a size arg, use it; otherwise use first arg
        args = m.group(0)[m.group(0).index("(") + 1:m.group(0).rindex(")")].split(",")
        op_val = args[-1].strip() if len(args) > 1 else args[0].strip()
        # For memcpy(dst, src, len), operation value is len (last arg)
        # For memset(ptr, val, size), operation value is size (last arg)
        ops.append({
            "op_text": op_text,
            "op_value": op_val,
            "start": m.start(),
            "end": m.end(),
        })
    return ops


def _is_inside_guard(guard: Dict[str, Any], op: Dict[str, Any], code: str) -> bool:
    """Check if the operation is textually inside the guard's consequence block."""
    # Simple heuristic: operation start is after guard end, and if guard has '{',
    # operation is before the matching close brace (approximated by next '}' at
    # same or lower indentation). For reject guards, operation is always "after".
    if guard["is_reject"]:
        return op["start"] > guard["end"]
    # For safe-branch guards, check if op is within the consequence block
    guard_end = guard["end"]
    # find the next '}' after guard_end
    brace_idx = code.find("}", guard_end)
    if brace_idx == -1:
        brace_idx = len(code)
    return guard_end <= op["start"] < brace_idx


def _build_candidate(guard: dict, op: dict, cid: int) -> CandidateReceipt:
    """Build a candidate receipt from a matched guard/operation pair."""
    enforcement = guard["enforcement"]
    defense_kind = "upper_bound_reject" if guard["is_reject"] else "range_guarded_operation"
    unsupported = []
    if not guard["is_reject"] and enforcement == "operation_inside_safe_branch":
        if guard["op"] not in (">", ">=", "<", "<="):
            unsupported.append("guard_not_relational")
    return CandidateReceipt(
        candidate_id=f"C{cid}",
        defense_kind=defense_kind,
        guard_anchor=guard["guard_text"],
        guarded_value=guard["var"],
        protected_operation_anchor=op["op_text"],
        operation_value=op["op_value"],
        enforcement=enforcement,
        value_relation="guarded_value_equals_operation_value",
        source_span={"guard_start": guard["start"], "guard_end": guard["end"],
                     "op_start": op["start"], "op_end": op["end"]},
        unsupported_conditions=unsupported,
    )


def _guard_matches_op(guard: dict, op: dict, code: str) -> bool:
    """Check whether a guard/operation pair is a valid candidate."""
    if guard["var"] != op["op_value"]:
        return False
    if not _is_inside_guard(guard, op, code) and not guard["is_reject"]:
        return False
    if guard["is_reject"] and op["start"] < guard["start"]:
        return False
    return True


def extract_upper_bound_candidates(code: str) -> List[CandidateReceipt]:
    """Extract upper_bound defense candidates from C code."""
    guards = _find_guards(code)
    ops = _find_operations(code)
    candidates = []
    cid = 0

    for guard in guards:
        if guard["op"] not in (">", "<", ">=", "<=", "!="):
            continue
        for op in ops:
            if not _guard_matches_op(guard, op, code):
                continue
            cid += 1
            candidates.append(_build_candidate(guard, op, cid))

    return candidates


def extract_candidates(code: str, defense_obligation: Any, diagnostics: list = None) -> List[CandidateReceipt]:
    """Extract candidate receipts for the given defense obligation.

    V1 supports only the upper_bound family. Other families return an empty
    list (the judge must abstain or return "no valid receipt").

    Uses tree-sitter AST when available (higher coverage), falls back to regex.
    """
    if not isinstance(defense_obligation, dict) or defense_obligation.get("version") != "v1":
        return []
    kind = defense_obligation.get("kind")
    if kind != "upper_bound":
        return []  # deferred families
    if _ts_available():
        return extract_upper_bound_candidates_ts(code, diagnostics)
    return extract_upper_bound_candidates(code)


def format_candidates_for_prompt(candidates: List[CandidateReceipt]) -> str:
    """Format candidates as a string for injection into the judge prompt."""
    if not candidates:
        return "No valid receipt candidates found by the extractor."
    lines = ["Candidate receipts (select one by ID, or state 'no valid receipt'):"]
    for c in candidates:
        lines.extend([
            f"\nCandidate {c.candidate_id}:",
            f"  defense_kind: {c.defense_kind}",
            f"  guard_anchor: {c.guard_anchor}",
            f"  guarded_value: {c.guarded_value}",
            f"  protected_operation_anchor: {c.protected_operation_anchor}",
            f"  operation_value: {c.operation_value}",
            f"  enforcement: {c.enforcement}",
            f"  value_relation: {c.value_relation}",
        ])
        if c.unsupported_conditions:
            lines.append(f"  unsupported_conditions: {c.unsupported_conditions}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tree-sitter-based extractor (V1.1) — higher coverage than regex fallback
# ---------------------------------------------------------------------------

def _ts_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c  # noqa: F401
        return True
    except Exception:
        return False


def _ts_parse(code: str):
    import tree_sitter
    import tree_sitter_c
    lang = tree_sitter.Language(tree_sitter_c.language())
    parser = tree_sitter.Parser(lang)
    return parser.parse(code.encode("utf-8")), lang


def _ts_walk(node):
    yield node
    for c in node.children:
        yield from _ts_walk(c)


def _ts_text(code_bytes: bytes, node) -> str:
    return code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _ts_find_guards(root, code_bytes: bytes) -> list:
    """Find if_statements with binary conditions. Returns list of dicts."""
    guards = []
    for node in _ts_walk(root):
        if node.type != "if_statement":
            continue
        cond = node.child_by_field_name("condition")
        if cond is None:
            continue
        # unwrap parenthesized_expression
        binexpr = cond
        while binexpr and binexpr.type == "parenthesized_expression":
            binexpr = binexpr.named_children[0] if binexpr.named_children else None
        if binexpr is None or binexpr.type != "binary_expression":
            continue
        left = binexpr.child_by_field_name("left")
        op_node = binexpr.child_by_field_name("operator")
        right = binexpr.child_by_field_name("right")
        if left is None or op_node is None or right is None:
            continue
        left_txt = _ts_text(code_bytes, left)
        op_txt = _ts_text(code_bytes, op_node)
        right_txt = _ts_text(code_bytes, right)
        if op_txt not in (">", "<", ">=", "<=", "!=", "=="):
            continue

        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")

        # Check if consequence contains return/goto/break
        is_reject = False
        if consequence is not None:
            cons_text = _ts_text(code_bytes, consequence)
            is_reject = any(kw in cons_text for kw in ("return", "goto", "break"))

        enforcement = "reject_before_operation" if is_reject else "operation_inside_safe_branch"
        defense_kind = "upper_bound_reject" if is_reject else "range_guarded_operation"

        guards.append({
            "node": node,
            "cond_node": cond,
            "consequence": consequence,
            "alternative": alternative,
            "left_txt": left_txt,
            "op_txt": op_txt,
            "right_txt": right_txt,
            "guard_text": _ts_text(code_bytes, node)[:200],
            "enforcement": enforcement,
            "defense_kind": defense_kind,
            "is_reject": is_reject,
            "start": node.start_byte,
            "end": node.end_byte,
        })
    return guards


def _ts_find_operations(root, code_bytes: bytes, guard_vars: set = None) -> list:
    """Find call_expression nodes that are potential operations.

    Primary: recognized memory sinks (memcpy, free, kfree, etc.).
    Fallback: any call expression where a guard variable appears in the arguments
    (broad detection for upper_bound obligations). Broad-detected operations are
    marked ``recognized_sink=False`` so the validator can reject them if the
    structural proof cannot be established.
    """
    guard_vars = guard_vars or set()
    ops = []
    seen_starts = set()
    for node in _ts_walk(root):
        if node.type != "call_expression":
            continue
        func = node.child_by_field_name("function")
        if func is None:
            continue
        func_name = _ts_text(code_bytes, func)
        args = node.child_by_field_name("arguments")
        if args is None:
            continue
        arg_idents = [_ts_text(code_bytes, c) for c in args.named_children]
        arg_text = " ".join(arg_idents)
        recognized = func_name in _MEMORY_SINKS
        broad = (not recognized) and any(gv in arg_text for gv in guard_vars)
        if not recognized and not broad:
            continue
        if node.start_byte in seen_starts:
            continue
        seen_starts.add(node.start_byte)
        op_val = arg_idents[-1] if len(arg_idents) > 1 else (arg_idents[0] if arg_idents else "")
        ops.append({
            "node": node,
            "func_name": func_name,
            "op_text": _ts_text(code_bytes, node),
            "op_value": op_val,
            "start": node.start_byte,
            "end": node.end_byte,
            "arg_idents": arg_idents,
            "recognized_sink": recognized,
        })
    return ops


def _ts_inside(node_a, node_b) -> bool:
    """Check if node_a's byte range is inside node_b's byte range."""
    return node_b.start_byte <= node_a.start_byte and node_a.end_byte <= node_b.end_byte


def extract_upper_bound_candidates_ts(code: str, diagnostics: list = None) -> List[CandidateReceipt]:
    """Tree-sitter-based extraction of upper_bound defense candidates."""
    if not _ts_available():
        return extract_upper_bound_candidates(code)  # fallback to regex

    tree, _ = _ts_parse(code)
    code_bytes = code.encode("utf-8")
    root = tree.root_node

    guards = _ts_find_guards(root, code_bytes)
    guard_vars = {g["left_txt"] for g in guards}
    ops = _ts_find_operations(root, code_bytes, guard_vars)
    candidates = []
    cid = 0

    for guard in guards:
        if guard["op_txt"] not in (">", "<", ">=", "<=", "!=", "=="):
            continue
        guarded_var = guard["left_txt"]

        for op in ops:
            op_val = op["op_value"]
            # Exact identifier match first; then identifier-aware (word-boundary) match.
            if guarded_var != op_val:
                import re as _re
                if not _re.search(r'\b' + _re.escape(guarded_var) + r'\b', op["op_text"]):
                    if diagnostics is not None:
                        diagnostics.append({"guard_var": guarded_var, "op_func": op["func_name"], "reason": "value_mismatch"})
                    continue

            # Check containment
            consequence = guard["consequence"]
            if guard["is_reject"]:
                if not (op["start"] > guard["start"]):
                    if diagnostics is not None:
                        diagnostics.append({"guard_var": guarded_var, "op_func": op["func_name"], "reason": "no_containment_reject"})
                    continue
            else:
                if consequence is None or not _ts_inside(op["node"], consequence):
                    if diagnostics is not None:
                        diagnostics.append({"guard_var": guarded_var, "op_func": op["func_name"], "reason": "no_containment_safe_branch"})
                    continue

            # Unsupported conditions
            unsupported = []
            if not op.get("recognized_sink", True):
                unsupported.append("operation_not_recognized_sink")
            if not guard["is_reject"] and guard["enforcement"] == "operation_inside_safe_branch":
                if guard["op_txt"] not in (">", ">=", "<", "<="):
                    unsupported.append("guard_not_relational")

            cid += 1
            candidates.append(CandidateReceipt(
                candidate_id=f"C{cid}",
                defense_kind=guard["defense_kind"],
                guard_anchor=guard["guard_text"],
                guarded_value=guarded_var,
                protected_operation_anchor=op["op_text"],
                operation_value=op_val,
                enforcement=guard["enforcement"],
                value_relation="guarded_value_equals_operation_value",
                source_span={"guard_start": guard["start"], "guard_end": guard["end"],
                             "op_start": op["start"], "op_end": op["end"]},
                unsupported_conditions=unsupported,
            ))

    # Prefer recognized sinks: if any exist, drop broad-detected candidates.
    recognized = [c for c in candidates if "operation_not_recognized_sink" not in c.unsupported_conditions]
    if recognized:
        candidates = recognized
    # Limit to 5 candidates per seed to avoid overwhelming the judge.
    candidates = candidates[:5]
    return candidates


def extract_upper_bound_candidates_ts_with_diagnostics(code: str) -> tuple:
    """Tree-sitter-based extraction with per-pair rejection reasons.

    Returns (candidates, rejections) where rejections is a list of dicts
    with keys: guard_var, op_func, reason.
    """
    if not _ts_available():
        return [], [{"reason": "tree_sitter_unavailable"}]

    tree, _ = _ts_parse(code)
    code_bytes = code.encode("utf-8")
    root = tree.root_node
    guards = _ts_find_guards(root, code_bytes)
    guard_vars = {g["left_txt"] for g in guards}
    ops = _ts_find_operations(root, code_bytes, guard_vars)

    candidates = []
    rejections = []
    cid = 0

    for guard in guards:
        if guard["op_txt"] not in (">", "<", ">=", "<=", "!=", "=="):
            continue
        guarded_var = guard["left_txt"]
        for op in ops:
            # Value match
            if guarded_var != op["op_value"] and guarded_var not in op["op_text"].split():
                rejections.append({"guard_var": guarded_var, "op_func": op["func_name"],
                                  "reason": "value_mismatch"})
                continue
            # Containment
            consequence = guard["consequence"]
            if guard["is_reject"]:
                if not (op["start"] > guard["start"]):
                    rejections.append({"guard_var": guarded_var, "op_func": op["func_name"],
                                      "reason": "no_containment_reject"})
                    continue
            else:
                if consequence is None or not _ts_inside(op["node"], consequence):
                    rejections.append({"guard_var": guarded_var, "op_func": op["func_name"],
                                      "reason": "no_containment_safe_branch"})
                    continue

            # Build candidate
            unsupported = []
            if not op.get("recognized_sink", True):
                unsupported.append("operation_not_recognized_sink")
            if not guard["is_reject"] and guard["enforcement"] == "operation_inside_safe_branch":
                if guard["op_txt"] not in (">", ">=", "<", "<="):
                    unsupported.append("guard_not_relational")

            cid += 1
            candidates.append(CandidateReceipt(
                candidate_id=f"C{cid}",
                defense_kind=guard["defense_kind"],
                guard_anchor=guard["guard_text"],
                guarded_value=guarded_var,
                protected_operation_anchor=op["op_text"],
                operation_value=op["op_value"],
                enforcement=guard["enforcement"],
                value_relation="guarded_value_equals_operation_value",
                source_span={"guard_start": guard["start"], "guard_end": guard["end"],
                             "op_start": op["start"], "op_end": op["end"]},
                unsupported_conditions=unsupported,
            ))
    # Limit
    recognized = [c for c in candidates if "operation_not_recognized_sink" not in c.unsupported_conditions]
    if recognized:
        candidates = recognized
    candidates = candidates[:5]
    return candidates, rejections


def extract_candidates_ts(code: str, defense_obligation: Any, diagnostics: list = None) -> List[CandidateReceipt]:
    """Tree-sitter-based candidate extraction. Falls back to regex if unavailable."""
    if not isinstance(defense_obligation, dict) or defense_obligation.get("version") != "v1":
        return []
    kind = defense_obligation.get("kind")
    if kind != "upper_bound":
        return []
    if not _ts_available():
        return extract_upper_bound_candidates(code)
    return extract_upper_bound_candidates_ts(code, diagnostics)
