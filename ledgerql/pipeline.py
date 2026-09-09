"""Orchestrates the Phase 2 naive pipeline: schema -> generate -> execute -> answer.

No classification/guardrails (Phase 3), no self-consistency (Phase 4),
no confidence/abstain -- Phase 2 attempts to answer every question,
including ones a later phase should refuse. That's the deliberate
"before" baseline the eval harness in evals/run_eval.py measures.
"""

from ledgerql import answer as answer_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import schema_index


def ask(question: str, db_path: str | None = None) -> dict:
    schema_context = schema_index.get_schema_context()
    sql = generate_module.generate_candidates(question, schema_context, n=1)[0]
    if db_path is not None:
        result = execute_module.execute(sql, db_path=db_path)
    else:
        result = execute_module.execute(sql)

    base = {
        "question": question,
        "sql": sql,
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "error": result.error,
    }

    if result.error is not None:
        return {**base, "answer": None}

    answer_text = answer_module.write_answer(question, result)
    return {**base, "answer": answer_text}
