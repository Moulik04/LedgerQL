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


def test_write_answer_includes_question_and_result_in_prompt():
    client = _FakeClient("Apple's fiscal 2024 revenue was $391.0 billion.")
    result = ExecutionResult(columns=["value"], rows=[(391035000000,)])
    answer_text = answer.write_answer("What was Apple's revenue?", result, client=client)
    assert answer_text == "Apple's fiscal 2024 revenue was $391.0 billion."
    assert "What was Apple's revenue?" in client.last_call["prompt"]
    assert "391035000000" in client.last_call["prompt"]


def test_write_answer_handles_empty_result():
    client = _FakeClient("No matching data was found.")
    result = ExecutionResult(columns=["value"], rows=[])
    answer_text = answer.write_answer("q", result, client=client)
    assert answer_text == "No matching data was found."
    assert "(no rows)" in client.last_call["prompt"]


def test_write_answer_passes_temperature_and_seed():
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer("q", result, client=client)
    assert client.last_call["options"]["temperature"] == answer.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == answer.OLLAMA_SEED
