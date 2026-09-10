from ledgerql import generate


class _FakeResponse:
    def __init__(self, text: str):
        self.response = text


class _FakeClient:
    def __init__(self, texts):
        # Accept either a single string (every call returns the same
        # text) or a list (one text per call, in order).
        self._texts = [texts] if isinstance(texts, str) else list(texts)
        self._call_index = 0
        self.last_call: dict | None = None
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.last_call = kwargs
        self.calls.append(kwargs)
        text = self._texts[min(self._call_index, len(self._texts) - 1)]
        self._call_index += 1
        return _FakeResponse(text)


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


def test_generate_candidates_returns_plain_sql_unchanged():
    client = _FakeClient("SELECT value FROM v_revenue WHERE ticker='AAPL'")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT value FROM v_revenue WHERE ticker='AAPL'"]


def test_generate_candidates_passes_system_prompt_to_client():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates("q", "schema", n=1, client=client)
    assert client.last_call["system"] == generate.SYSTEM_PROMPT


def test_generate_candidates_makes_n_calls():
    client = _FakeClient(["SELECT 1;", "SELECT 2;", "SELECT 3;"])
    result = generate.generate_candidates("q", "schema", n=3, client=client)
    assert result == ["SELECT 1;", "SELECT 2;", "SELECT 3;"]
    assert len(client.calls) == 3


def test_generate_candidates_uses_distinct_seeds_per_call():
    client = _FakeClient(["SELECT 1;", "SELECT 2;", "SELECT 3;"])
    generate.generate_candidates("q", "schema", n=3, client=client)
    seeds = [call["options"]["seed"] for call in client.calls]
    assert seeds == [generate.OLLAMA_SEED, generate.OLLAMA_SEED + 1, generate.OLLAMA_SEED + 2]


def test_generate_candidates_default_temperature_unaffected_by_n():
    client = _FakeClient(["SELECT 1;", "SELECT 2;"])
    generate.generate_candidates("q", "schema", n=2, client=client)
    for call in client.calls:
        assert call["options"]["temperature"] == generate.OLLAMA_TEMPERATURE


def test_generate_candidates_accepts_explicit_temperature_override():
    client = _FakeClient(["SELECT 1;", "SELECT 2;"])
    generate.generate_candidates(
        "q", "schema", n=2, temperature=generate.OLLAMA_CONSENSUS_TEMPERATURE, client=client
    )
    for call in client.calls:
        assert call["options"]["temperature"] == generate.OLLAMA_CONSENSUS_TEMPERATURE
