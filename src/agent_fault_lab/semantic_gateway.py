"""Capability URL, serial requests, native Ollama settings and physical-call caps."""

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from agent_fault_lab.journal import atomic_json, strict_json
from agent_fault_lab.model import DEFAULT_MODEL
from agent_fault_lab.scanner import MAX_OUTPUT, stop


def native_request(raw: bytes) -> dict[str, Any]:
    value = strict_json(raw.decode())
    if not isinstance(value, dict) or value.get("model") != DEFAULT_MODEL:
        raise ValueError("Gateway requires the approved local model")
    allowed = {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "stream",
    }
    if set(value) - allowed:
        raise ValueError("Unsupported chat-completion request fields")
    if value.get("stream", False) is not False:
        raise ValueError("Streaming is not enabled for the semantic pilot")
    if value.get("tool_choice", "auto") != "auto":
        raise ValueError("Native gateway cannot promise forced tool selection")
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("A nonempty message list is required")
    converted = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in (
            "system",
            "user",
            "assistant",
            "tool",
        ):
            raise ValueError("Invalid chat message")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("Only text messages are supported")
        # Structured-output scanner requests are single-turn. Reject histories
        # whose tool-call IDs would require a lossy conversion to native Ollama.
        if set(message) - {"role", "content"} or message["role"] == "tool":
            raise ValueError("Tool histories are outside the semantic gateway contract")
        converted.append({"role": message["role"], "content": content or ""})
    requested = value.get("max_completion_tokens", value.get("max_tokens", 1024))
    if type(requested) is not int or requested <= 0:
        raise ValueError("Invalid output token limit")
    result: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "messages": converted,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": min(requested, 1024),
        },
    }
    if "tools" in value:
        if not isinstance(value["tools"], list):
            raise ValueError("Invalid tools")
        result["tools"] = value["tools"]
    if "response_format" in value:
        fmt = value["response_format"]
        if not isinstance(fmt, dict):
            raise ValueError("Invalid response format")
        schema = fmt.get("json_schema")
        if (
            fmt.get("type") == "json_schema"
            and isinstance(schema, dict)
            and isinstance(schema.get("schema"), dict)
        ):
            result["format"] = schema["schema"]
        elif fmt.get("type") == "json_object":
            result["format"] = "json"
        else:
            raise ValueError("Unsupported response format")
    return result


def completion(raw: bytes) -> dict[str, Any]:
    value = strict_json(raw.decode())
    if not isinstance(value, dict) or value.get("done") is not True:
        raise ValueError("Incomplete native model response")
    if value.get("done_reason") != "stop":
        raise ValueError("Native model response was truncated or did not stop normally")
    message = value.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("Malformed native response")
    if message.get("thinking"):
        raise ValueError("Unexpected thinking output from the Instruct checkpoint")
    answer: dict[str, Any] = {"role": "assistant", "content": message["content"]}
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list):
        raise ValueError("Invalid native tool calls")
    converted = []
    for index, call in enumerate(calls):
        function = call.get("function") if isinstance(call, dict) else None
        if (
            not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
            or not isinstance(function.get("arguments"), dict)
        ):
            raise ValueError("Invalid native function call")
        converted.append(
            {
                "id": f"scan-call-{index}",
                "type": "function",
                "function": {
                    "name": function["name"],
                    "arguments": json.dumps(function["arguments"]),
                },
            }
        )
    if converted:
        answer["tool_calls"] = converted
    result: dict[str, Any] = {
        "id": "aflab-local-completion",
        "object": "chat.completion",
        "created": 0,
        "model": DEFAULT_MODEL,
        "choices": [
            {
                "index": 0,
                "message": answer,
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
    }
    prompt, output = value.get("prompt_eval_count"), value.get("eval_count")
    if type(prompt) is int and prompt >= 0 and type(output) is int and output >= 0:
        result["usage"] = {
            "prompt_tokens": prompt,
            "completion_tokens": output,
            "total_tokens": prompt + output,
        }
    return result


class Gateway:
    def __init__(self, directory: Path, deadline: float) -> None:
        self.directory, self.deadline = directory, deadline
        self.path = f"/{uuid4().hex}/v1/chat/completions"
        self.requests = 0
        self.records: list[dict[str, Any]] = []
        self.bytes = 0
        self.error: str | None = None
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen[bytes] | None = None

    def exchange(self, path: str, raw: bytes) -> bytes:
        if path != self.path:
            self.error = "Gateway endpoint rejected"
            raise ValueError(self.error)
        if self.error:
            raise ValueError(self.error)
        try:
            native = native_request(raw)
            remaining = self.deadline - time.monotonic()
            if self.requests >= 12 or remaining <= 0:
                raise ValueError("Semantic physical-request or scan-time limit reached")
            if self.bytes + len(raw) > MAX_OUTPUT:
                raise ValueError("Semantic evidence exceeds 4 MiB")
            self.bytes += len(raw)
            self.requests += 1
            record: dict[str, Any] = {
                "number": self.requests,
                "requested": strict_json(raw.decode()),
                "effective": native,
                "status": "started",
            }
            self.records.append(record)
            self.persist()
            if self.error:
                raise ValueError(self.error)
            started = time.monotonic()
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-m", "agent_fault_lab.semantic_transport"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                out, err = self.process.communicate(
                    json.dumps(native).encode(), timeout=min(60, remaining)
                )
                record["elapsed_seconds"] = time.monotonic() - started
                self.bytes += len(out) + len(err)
                if self.bytes > MAX_OUTPUT:
                    raise ValueError("Semantic evidence exceeds 4 MiB")
                record["stderr"] = err.decode(errors="replace")
                if self.process.returncode:
                    raise ValueError(
                        "Local model request failed; see captured transport error"
                    )
                record["native_response"] = strict_json(out.decode())
                result = completion(out)
                record["status"] = "completed"
                return json.dumps(result, ensure_ascii=False).encode()
            finally:
                stop(self.process)
                self.process = None
                record["elapsed_seconds"] = time.monotonic() - started
                if record["status"] == "started":
                    record["status"] = "failed"
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            raise ValueError(self.error) from exc
        finally:
            self.persist()

    def persist(self) -> None:
        serialized = json.dumps(self.records, ensure_ascii=False)
        if len(serialized.encode()) > MAX_OUTPUT // 2:
            self.error = "Gateway evidence exceeds its 2 MiB share; truncated"
            self.records = [{"status": "truncated", "prefix": serialized[:65536]}]
        atomic_json(
            self.directory / "gateway.json",
            {
                "schema_version": 2,
                "artifact": "semantic-gateway",
                "requests": self.requests,
                "error": self.error,
                "records": strict_json(json.dumps(self.records)),
            },
        )

    def __enter__(self) -> Self:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, fmt: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_OUTPUT or self.headers.get(
                        "Transfer-Encoding"
                    ):
                        raise ValueError("Invalid semantic request body size")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("Incomplete request body")
                    answer = gateway.exchange(self.path, raw)
                    code = 200
                except (ValueError, OSError) as exc:
                    gateway.error = gateway.error or f"{type(exc).__name__}: {exc}"
                    gateway.persist()
                    answer = json.dumps(
                        {"error": {"message": str(exc), "type": "aflab_limit"}}
                    ).encode()
                    code = 400
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(answer)))
                self.end_headers()
                try:
                    self.wfile.write(answer)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.thread.start()
        return self

    @property
    def port(self) -> int:
        assert self.server
        return self.server.server_port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}" + self.path.removesuffix(
            "/chat/completions"
        )

    def __exit__(self, *args: object) -> None:
        if self.process is not None:
            # Termination also releases communicate() in the server thread.
            stop(self.process)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise ValueError("Semantic gateway thread did not terminate")
        self.persist()
