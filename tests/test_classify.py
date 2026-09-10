from ledgerql import classify


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


def test_classify_in_scope_question():
    client = _FakeClient("IN_SCOPE")
    result = classify.classify("What was Apple's revenue in fiscal 2024?", client=client)
    assert result.verdict == "IN_SCOPE"


def test_classify_out_of_scope_question():
    client = _FakeClient("OUT_OF_SCOPE")
    result = classify.classify("Should I buy Tesla stock?", client=client)
    assert result.verdict == "OUT_OF_SCOPE"


def test_classify_schema_mismatch_question():
    client = _FakeClient("SCHEMA_MISMATCH")
    result = classify.classify("What was Apple's dividend yield?", client=client)
    assert result.verdict == "SCHEMA_MISMATCH"


def test_classify_passes_model_temperature_and_seed():
    client = _FakeClient("IN_SCOPE")
    classify.classify("q", client=client)
    assert client.last_call["model"] == classify.OLLAMA_MODEL
    assert client.last_call["options"]["temperature"] == classify.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == classify.OLLAMA_SEED


def test_classify_includes_question_in_prompt():
    client = _FakeClient("IN_SCOPE")
    classify.classify("What was Tesla's net income?", client=client)
    assert "What was Tesla's net income?" in client.last_call["prompt"]


def test_classify_defaults_to_in_scope_on_unparseable_response():
    # A soft prefilter that fails closed would risk falsely blocking
    # legitimate questions on a malformed model response; guardrails.py
    # is the real safety boundary, so classify.py fails open.
    client = _FakeClient("I'm not sure what you mean.")
    result = classify.classify("q", client=client)
    assert result.verdict == "IN_SCOPE"


def test_classify_result_records_raw_explanation():
    client = _FakeClient("OUT_OF_SCOPE")
    result = classify.classify("q", client=client)
    assert result.explanation == "OUT_OF_SCOPE"
