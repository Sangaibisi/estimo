"""End-to-end gateway smoke check (S1 exit gate).

Run inside the compose stack: `docker compose --profile mock run --rm smoke`,
or against a real LiteLLM endpoint with ESTIMO_GATEWAY__* set.
"""

from __future__ import annotations

import asyncio
import json
import sys

from estimo_gateway.client import GatewayClient
from estimo_gateway.config import GatewaySettings


async def run() -> int:
    settings = GatewaySettings()
    client = GatewayClient(settings)
    try:
        result = await client.complete(
            "smoke",
            [{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=16,
        )
    finally:
        await client.aclose()
    print(
        json.dumps(
            {
                "model": result.model,
                "text": result.text,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.text else 1


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
