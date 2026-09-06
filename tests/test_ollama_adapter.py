"""Exercise the real SDK with in-memory HTTP responses. Never contact Ollama."""

import json

import httpx
import pytest
from pydantic import JsonValue

from agent_fault_lab.model import Message, ModelSettings, ProviderError, ToolCall
from agent_fault_lab.ollama_adapter import LOCAL_HOST, OllamaClient
from agent_fault_lab.tools import TOOL_SPECS


class FakeAPI:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, JsonValue | httpx.Response | Exception] = {
            "/api/version": {"version": "test-version"},
            "/api/status": {"cloud": {"disabled": True}},
            "/api/tags": {"models": [{"name": "qwen3:4b", "digest": "test-digest"}]},
            "/api/show": {"capabilities": ["completion", "tools", "thinking"]},
            "/api/chat": {
                "model": "qwen3:4b",
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": "Done"},
                "prompt_eval_count": 123,
                "eval_count": 12,
                "load_duration": 9000,
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(LOCAL_HOST + "/")
        self.requests.append(request)
        response = self.responses[request.url.path]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    def client(self) -> OllamaClient:
        return OllamaClient(transport=httpx.MockTransport(self))


def test_doctor_only_reads_metadata() -> None:
    api = FakeAPI()
    info = api.client().inspect()
    assert info.ready and info.cloud_disabled and info.tools_supported
    assert info.model_digest == "test-digest" and info.ollama_version == "test-version"
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("GET", "/api/version"),
        ("GET", "/api/status"),
        ("GET", "/api/tags"),
        ("POST", "/api/show"),
    ]


@pytest.mark.parametrize(
    ("endpoint", "response", "problem"),
    [
        ("/api/status", {"cloud": {"disabled": False}}, "cloud is enabled"),
        ("/api/status", {"cloud": {"disabled": "true"}}, "Cannot verify"),
        ("/api/status", {}, "Cannot verify"),
        ("/api/tags", {"models": []}, "not installed"),
        ("/api/tags", {"models": [{"name": "qwen3:4b", "digest": ""}]}, "no digest"),
        ("/api/show", {"capabilities": ["completion"]}, "tool support"),
        (
            "/api/show",
            {"capabilities": ["tools"], "remote_host": "https://ollama.com"},
            "Remote/cloud",
        ),
        (
            "/api/show",
            {"capabilities": ["tools"], "remote_model": "another-model"},
            "Remote/cloud",
        ),
    ],
)
def test_unready_never_infers(endpoint: str, response: JsonValue, problem: str) -> None:
    api = FakeAPI()
    api.responses[endpoint] = response
    with pytest.raises(ProviderError, match=problem):
        api.client().complete(
            [Message(role="user", content="hello")], TOOL_SPECS, ModelSettings()
        )
    assert "/api/chat" not in [request.url.path for request in api.requests]
    assert "/api/pull" not in [request.url.path for request in api.requests]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={"error": "unknown endpoint"}),
        httpx.Response(200, text="not JSON"),
        httpx.Response(302, headers={"Location": "https://example.com"}),
        httpx.ConnectError("not running"),
    ],
)
def test_unverifiable_daemon_fails_closed(response: httpx.Response | Exception) -> None:
    api = FakeAPI()
    api.responses["/api/status"] = response
    info = api.client().inspect()
    assert not info.ready and info.cloud_disabled is None
    assert all(str(request.url).startswith(LOCAL_HOST) for request in api.requests)
    assert len(api.requests) == 2  # No redirect or retry.


def test_real_sdk_serialization_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeAPI()
    # Synthetic credentials prove ambient configuration is not forwarded.
    monkeypatch.setenv("OLLAMA_HOST", "https://not-our-provider.invalid")
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-key-do-not-forward")
    monkeypatch.setenv("HTTP_PROXY", "http://not-our-proxy.invalid")
    turn = api.client().complete(
        [Message(role="user", content="Create task")], TOOL_SPECS, ModelSettings()
    )
    assert turn.content == "Done" and not turn.tool_calls
    assert turn.usage == {
        "prompt_eval_count": 123,
        "eval_count": 12,
        "load_duration": 9000,
    }
    assert turn.metadata["model_digest"] == "test-digest"
    request = api.requests[-1]
    body = json.loads(request.content)
    assert body["model"] == "qwen3:4b"
    assert body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0.0, "num_ctx": 4096, "num_predict": 512}
    assert "format" not in body  # No grammar imposed on tool-calling turns.
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        "create_task",
        "get_task",
    ]
    assert body["tools"][0]["function"]["parameters"]["required"] == ["title"]
    assert request.extensions["timeout"] == {
        "connect": 60.0,
        "read": 60.0,
        "write": 60.0,
        "pool": 60.0,
    }
    assert "synthetic-key" not in str(request.headers)


def test_tool_requests_and_followup_order_survive_sdk() -> None:
    api = FakeAPI()
    api.responses["/api/chat"] = {
        "model": "qwen3:4b",
        "done": True,
        "done_reason": "stop",
        "message": {
            "role": "assistant",
            "content": "",
            "thinking": "test metadata",
            "tool_calls": [
                {"function": {"name": "create_task", "arguments": {"title": "First"}}},
                {"function": {"name": "create_task", "arguments": {"title": "Second"}}},
            ],
        },
    }
    client = api.client()
    turn = client.complete(
        [Message(role="user", content="Create tasks")], TOOL_SPECS, ModelSettings()
    )
    assert turn.tool_calls == (
        ToolCall(name="create_task", arguments={"title": "First"}),
        ToolCall(name="create_task", arguments={"title": "Second"}),
    )
    assert turn.usage == {}  # Unknown usage is absent, not fabricated zero.
    client.complete(
        [
            Message(role="user", content="Create tasks"),
            Message(
                role="assistant", tool_calls=turn.tool_calls, metadata=turn.metadata
            ),
            Message(
                role="tool",
                tool_name="create_task",
                call_id="m1-t1",
                content='{"id":"one"}',
            ),
            Message(
                role="tool",
                tool_name="create_task",
                call_id="m1-t2",
                content='{"id":"two"}',
            ),
        ],
        TOOL_SPECS,
        ModelSettings(),
    )
    body = json.loads(api.requests[-1].content)
    assert body["messages"][1]["thinking"] == "test metadata"
    assert [json.loads(m["content"])["id"] for m in body["messages"][-2:]] == [
        "one",
        "two",
    ]
    assert all("call_id" not in m for m in body["messages"])
    assert all(m["tool_name"] == "create_task" for m in body["messages"][-2:])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"error": "server failed"}),
        httpx.ReadTimeout("Timed out"),
        httpx.Response(200, text="bad JSON"),
        {"done": False, "message": {"role": "assistant", "content": "partial"}},
        {"done": True, "message": {"role": "user", "content": "bad role"}},
        {
            "done": True,
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "create_task", "arguments": "not an object"}}
                ],
            },
        },
    ],
)
def test_failed_response_is_not_retried(
    response: JsonValue | httpx.Response | Exception,
) -> None:
    api = FakeAPI()
    api.responses["/api/chat"] = response
    with pytest.raises(ProviderError):
        api.client().complete(
            [Message(role="user", content="Create task")], TOOL_SPECS, ModelSettings()
        )
    assert sum(r.url.path == "/api/chat" for r in api.requests) == 1


def test_output_limit_is_preserved_for_loop_classification() -> None:
    api = FakeAPI()
    api.responses["/api/chat"] = {
        "done": True,
        "done_reason": "length",
        "message": {"role": "assistant", "content": "partial"},
    }
    assert (
        api.client().complete([], TOOL_SPECS, ModelSettings()).finish_reason == "length"
    )
