"""One bounded local request, run in a supervised process by the gateway."""

import json
import signal
import sys

import httpx

from agent_fault_lab.journal import strict_json
from agent_fault_lab.ollama_adapter import LOCAL_HOST

LIMIT = 4 * 1024 * 1024


def main() -> None:
    # Retain a local deadline even if the supervising gateway process dies.
    signal.setitimer(signal.ITIMER_REAL, 60)
    raw = sys.stdin.buffer.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("Semantic request exceeds evidence limit")
    payload = strict_json(raw.decode())
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=60) as client:
        with client.stream("POST", LOCAL_HOST + "/api/chat", json=payload) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > LIMIT:
                    raise ValueError("Semantic response exceeds evidence limit")
                data.extend(chunk)
    print(json.dumps(strict_json(data.decode()), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
