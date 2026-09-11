from ledgerql import answer
from ledgerql.execute import ExecutionResult


class _FakeResponse:
    def __init__(self, text: str):
        self.response = text


class _FakeClient:
    def __init__(self, text: str):
        self._text = text
        self.last_call: dict | None = None

    def generate(self, **kwargs):
        self.last_call = kwargs
        return _FakeResponse(self._text)


def test_write_answer_includes_result_in_prompt_but_not_a_question():
    client = _FakeClient("The value was $391.0 billion.")
    result = ExecutionResult(columns=["value"], rows=[(391035000000,)])
    answer_text = answer.write_answer(result, client=client)
    assert answer_text == "The value was $391.0 billion."
    # Comma-grouped, not the raw digit string -- see
    # test_write_answer_comma_groups_large_numbers_in_the_prompt for why.
    assert "391,035,000,000" in client.last_call["prompt"]
    # No question is ever passed to write_answer -- the prompt has
    # nothing question-shaped to leak, verified by construction: the
    # function signature itself no longer accepts one.


def test_write_answer_comma_groups_large_numbers_in_the_prompt():
    # Real finding from the Phase 4 eval run: shown a long undelimited
    # digit string, qwen2.5-coder:7b deterministically drops a digit when
    # restating it (391035000000 -> 39103500000). Confirmed directly
    # against the live model that comma-grouping fixes it. verify.py's
    # extract_numbers() strips commas before comparing, so this only
    # changes what the model sees.
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["value"], rows=[(391035000000.0,)])
    answer.write_answer(result, client=client)
    assert "391,035,000,000.0" in client.last_call["prompt"]
    assert "391035000000.0" not in client.last_call["prompt"]


def test_write_answer_does_not_comma_group_a_plausible_bare_year():
    # verify.py's extract_years() matches bare 4-digit years with
    # (?<!\d)20\d{2}(?!\d) -- a comma-grouped "2,024" would silently
    # fail to match, turning the fiscal-year check into a no-op for that
    # value. A year-range int (2000-2099) must be shown undelimited.
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["fiscal_year", "value"], rows=[(2024, 391035000000.0)])
    answer.write_answer(result, client=client)
    assert "2024\t391,035,000,000.0" in client.last_call["prompt"]
    assert "2,024" not in client.last_call["prompt"]


def test_write_answer_leaves_non_numeric_values_unformatted():
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["ticker", "value"], rows=[("AAPL", None)])
    answer.write_answer(result, client=client)
    assert "AAPL\tNone" in client.last_call["prompt"]


def test_write_answer_handles_empty_result():
    client = _FakeClient("No matching data was found.")
    result = ExecutionResult(columns=["value"], rows=[])
    answer_text = answer.write_answer(result, client=client)
    assert answer_text == "No matching data was found."
    assert "(no rows)" in client.last_call["prompt"]


def test_write_answer_passes_temperature_and_seed():
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer(result, client=client)
    assert client.last_call["options"]["temperature"] == answer.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == answer.OLLAMA_SEED


def test_write_answer_system_prompt_instructs_grounding_only():
    # The system prompt is the only thing telling the model not to
    # infer/add numbers -- a silent regression here would reopen exactly
    # the hallucination surface this phase closes.
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer(result, client=client)
    assert "do not add" in client.last_call["system"].lower()
