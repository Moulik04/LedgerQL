"""Stage 6.5: identity-anchored empty-result detection.

Distinguishes two shapes that look identical at the row-count level but
require opposite treatment: a query anchored on one specific company
(cik/ticker/name bound to a literal) that returns nothing means that
company's data for the requested slice is absent -- NO_DATA. A query with
no such anchor (e.g. "which companies had negative total assets") is a
set/filter question where an empty result is itself a valid, complete
answer and must be left alone.

The distinction is read off the already-parsed sqlglot AST (the same
library ledgerql/guardrails.py uses for its allowlist checks) rather than
matched against any of the specific business concepts a question happens
to ask about -- see docs/superpowers/specs/2026-09-16-phase5.5-task6b-design.md
section 1c for the full rationale and the gold case (G06) this exists to
avoid breaking.

Where the rule stops being principled (DECISIONS.md, 2026-09-18, item 3):
entity-bound + empty approximates presupposition failure, it is not identical.
An entity-bound list or existence query where "none" is the true answer
("did Tesla file any 8-K in 2025?") would false-abstain; the gold set has no
such case. It also cannot tell a real absence from a wrong literal
(`name = 'The Coca-Cola Company'`), and nothing downstream can: a repair for
that was tried and cut (an empty result carries no error to feed back, see
DECISIONS.md), so the wrong-literal case is an accepted false abstain.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# The three columns docs/schema.md documents as identifying a single
# company row -- present on `companies` and propagated onto every concept
# view (v_revenue, v_net_income, v_total_assets, v_cash). Fixed and small
# by schema design, not an enumerated list of business concepts -- do not
# grow this set without updating the spec.
IDENTITY_COLUMNS = {"cik", "ticker", "name"}

_LITERAL_ANCHOR_TYPES = (exp.Literal, exp.Subquery, exp.Select)


def is_empty_or_null(rows: list[tuple]) -> bool:
    if not rows:
        return True
    return all(v is None for row in rows for v in row)


def _binds_identity_column_to_a_literal(sql: str) -> bool:
    try:
        trees = sqlglot.parse(sql, read="duckdb")
    except ParseError:
        # Fail closed: an unparseable string is guardrails.py's problem,
        # not this stage's -- treat it as "not anchored" so an empty
        # result from it is answered normally rather than mis-flagged.
        return False

    for tree in trees:
        if tree is None:
            continue
        for predicate in tree.find_all(exp.EQ, exp.Like, exp.ILike):
            left, right = predicate.this, predicate.expression
            for identity_side, other_side in ((left, right), (right, left)):
                if (
                    isinstance(identity_side, exp.Column)
                    and identity_side.name.lower() in IDENTITY_COLUMNS
                    and isinstance(other_side, _LITERAL_ANCHOR_TYPES)
                ):
                    return True
    return False


def is_identity_anchored_empty(sql: str | None, rows: list[tuple]) -> bool:
    """True if `rows` is empty or a single all-NULL row, AND `sql` binds
    `cik`, `ticker`, or `name` to a literal (directly or inside a
    subquery) somewhere in its WHERE/ON/HAVING clauses. This is the
    signal that a specific company's data is absent, as opposed to a
    set/filter query for which an empty result is itself a valid answer.
    """
    if not sql or not is_empty_or_null(rows):
        return False
    return _binds_identity_column_to_a_literal(sql)


def is_entity_bound(sql: str | None) -> bool:
    """True if `sql` binds `cik`, `ticker`, or `name` to a literal."""
    return bool(sql) and _binds_identity_column_to_a_literal(sql)


def survivors_unanimously_empty(survivor_rows: list[list[tuple]]) -> bool:
    """True if at least one candidate executed and every candidate that did
    returned empty/all-NULL. Evaluated over survivors, not over all N
    candidates: consensus agreement divides by N, so a single survivor among
    four errored candidates reads as 0.2 agreement and hides that the only
    candidates that ran were unanimous. An empty list (nothing executed) is
    consensus.py's EXEC_ERROR path, not an empty-result signal."""
    return bool(survivor_rows) and all(is_empty_or_null(rows) for rows in survivor_rows)


def is_entity_bound_no_data(sql: str | None, survivor_rows: list[list[tuple]]) -> bool:
    """The NO_DATA signal: every executed candidate came back empty/all-NULL
    AND the winning query is bound to a specific company. See
    docs/superpowers/specs/2026-09-16-phase5.5-task6b-design.md section 1c
    for the rule and its boundary."""
    return survivors_unanimously_empty(survivor_rows) and is_entity_bound(sql)


_COMPARISONS = {
    exp.EQ: lambda a, b: a == b,
    exp.NEQ: lambda a, b: a != b,
    exp.LT: lambda a, b: a < b,
    exp.LTE: lambda a, b: a <= b,
    exp.GT: lambda a, b: a > b,
    exp.GTE: lambda a, b: a >= b,
}


def _literal_value(node: exp.Expression):
    if not isinstance(node, exp.Literal):
        return None
    if node.is_string:
        return node.this
    try:
        return float(node.this)
    except ValueError:
        return None


def _constant_truth(node: exp.Expression) -> bool | None:
    """The truth value of a WHERE condition that does not depend on any row:
    True, False, or None when it cannot be decided statically. NULL is falsy in
    a WHERE clause, so it reads as False."""
    if isinstance(node, exp.Paren):
        return _constant_truth(node.this)
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Null):
        return False
    if isinstance(node, exp.Not):
        inner = _constant_truth(node.this)
        return None if inner is None else not inner
    if isinstance(node, exp.And):
        values = [_constant_truth(node.this), _constant_truth(node.expression)]
        if False in values:
            return False
        return True if all(v is True for v in values) else None
    if isinstance(node, exp.Or):
        values = [_constant_truth(node.this), _constant_truth(node.expression)]
        if True in values:
            return True
        return False if all(v is False for v in values) else None
    compare = _COMPARISONS.get(type(node))
    if compare is not None:
        left, right = _literal_value(node.this), _literal_value(node.expression)
        if left is None or right is None or type(left) is not type(right):
            return None
        return compare(left, right)
    return None


def is_tautologically_empty(sql: str | None) -> bool:
    """True if `sql` provably returns nothing informative whatever the data:
    a constant-false WHERE (``WHERE 1 = 0``, ``WHERE FALSE``), or a query with
    no FROM whose every projection is NULL.

    This is the generator refusing in SQL. Asked for a concept the schema cannot
    express, a model will sometimes emit ``SELECT NULL AS credit_rating WHERE
    1 = 0`` rather than invent a column -- the honest answer written in the only
    language the prompt allowed. It is read off the AST, so it needs no list of
    concepts and holds for any concept a held-out question might ask about.

    **This check is inherently model-dependent, unlike `intent.py`'s regex on
    the question text.** It detects a specific *generator behaviour* -- writing
    a degenerate, provably-empty query instead of inventing a column -- not a
    property of the question or the schema. A model that never writes SQL
    shaped this way will never trip it, refusal-worthy question or not; the
    fallback for that model is whatever else classifies the case (NO_DATA,
    SCHEMA_MISMATCH via a stray column, or an abstain further downstream), not
    this check under another name. Measured 2026-09-20 (Bridges-2, DECISIONS.md):
    fired on exactly two cases (H03, O07) on Qwen3-Coder-30B and on zero cases
    on Qwen2.5-Coder-32B, whose generations for the same questions took a
    different, non-tautological shape. Do not read "it fired" on one model as
    evidence it would fire, or that the underlying refusal is caught some other
    way, on a different one.
    """
    if not sql:
        return False
    try:
        stmts = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError:
        return False
    if len(stmts) != 1 or not isinstance(stmts[0], exp.Select):
        return False
    stmt = stmts[0]
    where = stmt.args.get("where")
    if where is not None and _constant_truth(where.this) is False:
        return True
    has_from = stmt.args.get("from_") is not None or stmt.args.get("from") is not None
    return not has_from and all(isinstance(e.unalias(), exp.Null) for e in stmt.expressions)
