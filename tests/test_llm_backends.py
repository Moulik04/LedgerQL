import json

import httpx
import ollama

from ledgerql import llm_backends


def test_default_client_returns_ollama_client_by_default(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    client = llm_backends.default_client()
    assert isinstance(client, ollama.Client)


def test_default_client_returns_ollama_client_when_backend_is_explicitly_ollama(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    client = llm_backends.default_client()
    assert isinstance(client, ollama.Client)


def test_default_client_returns_vllm_client_when_backend_is_vllm(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    client = llm_backends.default_client()
    assert isinstance(client, llm_backends.VLLMClient)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://vllm-test:8000")


def test_vllm_client_generate_posts_chat_completions_and_returns_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "SELECT 1;"}}],
            },
        )

    client = llm_backends.VLLMClient(http_client=_mock_client(handler))
    response = client.generate(
        model="Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
        system="You are a SQL generator.",
        prompt="Question: what is 1?\n\nSQL:",
        options={"temperature": 0.2, "seed": 42},
    )

    assert response.response == "SELECT 1;"
    assert captured["url"] == "http://vllm-test:8000/v1/chat/completions"
    assert captured["json"]["model"] == "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "You are a SQL generator."},
        {"role": "user", "content": "Question: what is 1?\n\nSQL:"},
    ]
    assert captured["json"]["temperature"] == 0.2
    assert captured["json"]["seed"] == 42


def test_vllm_client_generate_works_without_options():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = llm_backends.VLLMClient(http_client=_mock_client(handler))
    response = client.generate(model="m", system="s", prompt="p", options=None)

    assert response.response == "ok"


def test_vllm_client_generate_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = llm_backends.VLLMClient(http_client=_mock_client(handler))
    try:
        client.generate(model="m", system="s", prompt="p", options={})
        raise AssertionError("expected an httpx.HTTPStatusError")
    except httpx.HTTPStatusError:
        pass
