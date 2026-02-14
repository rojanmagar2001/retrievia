from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="SSE client for /v1/chat/stream")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    payload: dict[str, object] = {"message": args.message}
    if args.conversation_id:
        payload["conversation_id"] = args.conversation_id

    headers = {
        "Authorization": f"Bearer {args.token}",
        "X-Tenant-Id": args.tenant_id,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }

    with httpx.stream(
        "POST",
        f"{args.base_url}/v1/chat/stream",
        headers=headers,
        json=payload,
        timeout=120.0,
    ) as response:
        response.raise_for_status()
        event_name: str | None = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
                continue
            if not line.startswith("data:"):
                continue

            data = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                print(data)
                continue

            if event_name == "token":
                print(parsed.get("delta", ""), end="", flush=True)
            elif event_name == "final":
                print("\n\n--- FINAL ---")
                print(json.dumps(parsed, indent=2))
                break
            elif event_name == "error":
                print("\n\n--- ERROR ---")
                print(json.dumps(parsed, indent=2))
                break


if __name__ == "__main__":
    main()
