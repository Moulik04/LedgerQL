import pytest

from ledgerql import generate


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


def test_generate_candidates_strips_markdown_fences():
    client = _FakeClient("```sql\nSELECT 1;\n```")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT 1;"]


def test_generate_candidates_passes_model_temperature_and_seed():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates("q", "schema", n=1, client=client)
    assert client.last_call["model"] == generate.OLLAMA_MODEL
    assert client.last_call["options"]["temperature"] == generate.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == generate.OLLAMA_SEED


def test_generate_candidates_includes_question_and_schema_in_prompt():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates(
        "What was Apple's revenue?", "SCHEMA_TEXT_HERE", n=1, client=client
    )
    assert "What was Apple's revenue?" in client.last_call["prompt"]
    assert "SCHEMA_TEXT_HERE" in client.last_call["prompt"]


def test_generate_candidates_rejects_n_other_than_one():
    client = _FakeClient("SELECT 1;")
    with pytest.raises(NotImplementedError):
        generate.generate_candidates("q", "schema", n=2, client=client)


def test_generate_candidates_returns_plain_sql_unchanged():
    client = _FakeClient("SELECT value FROM v_revenue WHERE ticker='AAPL'")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT value FROM v_revenue WHERE ticker='AAPL'"]
