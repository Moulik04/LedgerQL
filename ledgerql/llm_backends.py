"""LLM backend selection: local Ollama (default) or a remote vLLM server.

Every module that calls an LLM (generate.py, answer.py, classify.py) accepts
an optional `client` parameter duck-typed to `ollama.Client`'s own
`.generate(model=..., system=..., prompt=..., options={...}) -> obj.response`
shape. `default_client()` is the one place that decides which backend to
construct when no client is injected -- every module calls this instead of
constructing `ollama.Client` directly, so there is exactly one place that
knows about backend selection (avoiding yet another two-sources-of-truth
split, the bug class this project has hit five times).

`VLLMClient` is a pure-httpx adapter (httpx is already a base dependency)
talking to vLLM's OpenAI-compatible `/v1/chat/completions` endpoint -- it
requires no `vllm`/`torch` install locally. Only the Bridges-2 *server*
needs those (installed separately, see scripts/bridges2/).

Per LEDGERQL_MASTER_PROMPT.md's explicit preference for vLLM (or
transformers+peft) over Ollama when running on PSC Bridges-2's GPUs -- this
module exists so that preference costs one small, isolated addition rather
than rewriting generate.py/answer.py/classify.py's own logic. The default
(`LLM_BACKEND` unset or "ollama") is unchanged from every prior phase.
"""

import os
from dataclasses import dataclass

import httpx
import ollama

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
VLLM_HOST = os.environ.get("VLLM_HOST", "http://localhost:8000")


@dataclass
class _Response:
    response: str


class VLLMClient:
    """Duck-typed to match ollama.Client's own .generate() shape."""

    def __init__(self, host: str = VLLM_HOST, http_client: httpx.Client | None = None):
        self._http = http_client or httpx.Client(base_url=host, timeout=120.0)

    def generate(
        self,
        model: str,
        system: str,
        prompt: str,
        options: dict | None = None,
    ) -> _Response:
        options = options or {}
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if "temperature" in options:
            payload["temperature"] = options["temperature"]
        if "seed" in options:
            payload["seed"] = options["seed"]

        response = self._http.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return _Response(response=data["choices"][0]["message"]["content"])


def default_client() -> ollama.Client | VLLMClient:
    # Read fresh on every call, not bound once at import time -- callers
    # (and tests) must be able to switch backends by setting the env var
    # before calling this, without needing to reload the module.
    if os.environ.get("LLM_BACKEND", "ollama") == "vllm":
        return VLLMClient()
    return ollama.Client(host=OLLAMA_HOST)
