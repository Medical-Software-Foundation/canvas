"""Mock LKCareEvolve (ELLKAY) endpoint for local development.

Pretty-prints every inbound payload so you can verify what the
vanta-lab-orders plugin is shipping. Returns a fake FillerOrderNumber on
success.

Run:
    uv run python dev/mock_lkcareevolve/server.py
    uv run python dev/mock_lkcareevolve/server.py --port 8765 --api-key my-key

To expose to a cloud Canvas instance, tunnel localhost:
    ngrok http 8765
    # or: cloudflared tunnel --url http://localhost:8765

Then drop the public URL + api key into the plugin secrets:
    LKCAREEVOLVE_BASE_URL = https://<tunnel-host>
    LKCAREEVOLVE_API_KEY  = <api-key>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockLKCareEvolveHandler(BaseHTTPRequestHandler):
    api_key: str = ""  # set on startup

    def log_message(self, format: str, *args: Any) -> None:
        # Silence the default access-log noise; we print our own structured output.
        return

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _banner(self, title: str) -> None:
        bar = "=" * 78
        print(f"\n{bar}\n{title}\n{bar}", flush=True)

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self._send_json(200, {"status": "ok", "service": "mock-lkcareevolve"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""

        auth = self.headers.get("Authorization", "")
        content_type = self.headers.get("Content-Type", "")

        self._banner(f"[{ts}] {self.command} {self.path}")
        print(f"Authorization: {auth}", flush=True)
        print(f"Content-Type:  {content_type}", flush=True)
        print(f"Body bytes:    {length}", flush=True)

        # Auth check — the integrated plugin sends `Basic <key>`; older builds
        # used `Bearer <key>`. Accept either scheme as long as the token matches.
        token = auth.partition(" ")[2] if " " in auth else ""
        if token != self.api_key:
            print(f"\n[REJECTED] Authorization token mismatch.", flush=True)
            print(f"  expected token: {self.api_key}", flush=True)
            print(f"  got header:     {auth!r}", flush=True)
            self._send_json(401, {"error": "invalid api key"})
            return

        # Try to parse + pretty-print JSON body
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"\n[ERROR] Body is not valid UTF-8 JSON: {exc}", flush=True)
            print(f"Raw bytes: {raw!r}", flush=True)
            self._send_json(400, {"error": "invalid json"})
            return

        if parsed is not None:
            print("\nPayload:", flush=True)
            print(json.dumps(parsed, indent=2, sort_keys=False), flush=True)

            header = parsed.get("MessageHeader", {}) if isinstance(parsed, dict) else {}
            placer = header.get("PlacerOrderNumber")
            # Integrated contract puts ObservationRequest at the top level;
            # older builds nested it under MessageHeader. Check both.
            obs = (
                (parsed.get("ObservationRequest") or header.get("ObservationRequest") or [])
                if isinstance(parsed, dict)
                else []
            )
            aoe_total = sum(
                len(o.get("AOE", [])) for o in obs if isinstance(o, dict)
            )
            print(
                f"\nSummary: PlacerOrderNumber={placer}, "
                f"ObservationRequest count={len(obs)}, AOE answers={aoe_total}",
                flush=True,
            )

        # Routing — the integrated plugin POSTs to the base URL root; older
        # builds used /orders. Treat both as a real order submission.
        if self.path.rstrip("/") in ("", "/orders"):
            response_body = {
                "Status": "Accepted",
                "FillerOrderNumber": f"MOCK-{uuid.uuid4().hex[:12].upper()}",
                "ReceivedAt": ts,
            }
            self._send_json(200, response_body)
            print(f"\n[200] Responded with: {response_body}", flush=True)
            return

        self._send_json(
            200,
            {"Status": "Accepted", "Note": f"path {self.path} not a known orders path but accepted"},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock LKCareEvolve server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 to allow tunnel)")
    parser.add_argument("--api-key", default=None, help="Override the bearer token (default: random)")
    args = parser.parse_args()

    api_key = args.api_key or f"mock-{secrets.token_urlsafe(24)}"
    MockLKCareEvolveHandler.api_key = api_key

    server = ThreadingHTTPServer((args.host, args.port), MockLKCareEvolveHandler)

    bar = "=" * 78
    print(bar, flush=True)
    print("MOCK LKCAREEVOLVE SERVER", flush=True)
    print(bar, flush=True)
    print(f"Listening on  : http://{args.host}:{args.port}", flush=True)
    print(f"Local URL     : http://localhost:{args.port}", flush=True)
    print(f"Orders path   : POST / (root) or /orders", flush=True)
    print(f"Auth accepted : Basic <key> or Bearer <key>", flush=True)
    print(f"Health check  : GET  /health", flush=True)
    print("", flush=True)
    print(f"Local URL for curl    : http://localhost:{args.port}", flush=True)
    print("  (the deployed plugin enforces https:// — use the tunnel URL below)", flush=True)
    print(f"LKCAREEVOLVE_API_KEY  = {api_key}", flush=True)
    print("", flush=True)
    print("To reach a cloud Canvas instance, tunnel out with one of:", flush=True)
    print(f"    ngrok http {args.port}", flush=True)
    print(f"    cloudflared tunnel --url http://localhost:{args.port}", flush=True)
    print("Then use the tunnel HTTPS URL as LKCAREEVOLVE_BASE_URL.", flush=True)
    print(bar, flush=True)
    print("", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
