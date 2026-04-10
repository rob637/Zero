"""
Telic Cloud Proxy — Zero-friction LLM access.

Users without their own API key hit this proxy. It:
1. Validates device tokens (rate limit per device)
2. Forwards requests to Anthropic
3. Enforces free-tier limits (25 messages/day)

Deployed on Vercel as a serverless function.

Monetization path:
  Free:  25 messages/day via proxy (no signup)
  Pro:   Unlimited via proxy (license key, subscription)
  BYOK:  Unlimited, user's own key (free forever)
"""

import hashlib
import json
import os
import time
from http import HTTPStatus

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Telic Proxy", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Desktop app sends Origin: null
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Device-Id", "X-License-Key"],
)

# Config from environment
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PROXY_SECRET = os.environ.get("PROXY_SECRET", "telic-proxy-default")

# Free tier limits
FREE_DAILY_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", "25"))
FREE_MODEL = os.environ.get("FREE_MODEL", "claude-sonnet-4-20250514")

# In-memory rate tracking (resets on cold start — fine for Vercel)
# Production: use Vercel KV or Upstash Redis
_usage: dict[str, dict] = {}  # device_id -> {"date": "2026-04-10", "count": 0}


def _get_device_usage(device_id: str) -> dict:
    """Get or create daily usage record for a device."""
    today = time.strftime("%Y-%m-%d")
    if device_id not in _usage or _usage[device_id]["date"] != today:
        _usage[device_id] = {"date": today, "count": 0}
    return _usage[device_id]


def _hash_device(device_id: str) -> str:
    """Hash device ID for privacy — we never store raw device identifiers."""
    return hashlib.sha256(f"{PROXY_SECRET}:{device_id}".encode()).hexdigest()[:16]


@app.post("/v1/messages")
async def proxy_messages(request: Request):
    """Proxy Anthropic /v1/messages — the only endpoint the app needs."""

    if not ANTHROPIC_API_KEY:
        return JSONResponse(
            {"error": "Proxy not configured. Set ANTHROPIC_API_KEY."},
            status_code=503,
        )

    # Device identification (anonymous — just for rate limiting)
    device_id = request.headers.get("X-Device-Id", "")
    license_key = request.headers.get("X-License-Key", "")

    if not device_id:
        return JSONResponse(
            {"error": "X-Device-Id header required."},
            status_code=400,
        )

    hashed = _hash_device(device_id)

    # Check license for Pro tier
    is_pro = bool(license_key and _validate_license(license_key))

    # Rate limit free tier
    if not is_pro:
        usage = _get_device_usage(hashed)
        if usage["count"] >= FREE_DAILY_LIMIT:
            return JSONResponse(
                {
                    "error": f"Free tier limit reached ({FREE_DAILY_LIMIT} messages/day). "
                    "Add your own API key in Settings for unlimited use, "
                    "or upgrade to Telic Pro.",
                    "limit_reached": True,
                    "daily_limit": FREE_DAILY_LIMIT,
                    "used": usage["count"],
                },
                status_code=429,
            )

    # Parse and sanitize the request body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    # Force model for free tier (prevent abuse via expensive models)
    if not is_pro:
        body["model"] = FREE_MODEL

    # Cap max_tokens for free tier
    if not is_pro:
        body["max_tokens"] = min(body.get("max_tokens", 4096), 4096)

    # Check if streaming
    is_stream = body.get("stream", False)

    # Forward to Anthropic
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Copy beta headers if present
    beta = request.headers.get("anthropic-beta")
    if beta:
        headers["anthropic-beta"] = beta

    if is_stream:
        # Streaming: proxy the SSE stream
        async def _stream():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=body,
                ) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        yield error_body
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        # Track usage on stream start (we don't wait for completion)
        if not is_pro:
            _get_device_usage(hashed)["count"] += 1

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "X-Telic-Remaining": str(
                    max(0, FREE_DAILY_LIMIT - _get_device_usage(hashed)["count"])
                ),
            },
        )
    else:
        # Non-streaming: forward and return
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
            )

        # Track usage on success
        if resp.status_code == 200 and not is_pro:
            _get_device_usage(hashed)["count"] += 1

        return JSONResponse(
            resp.json(),
            status_code=resp.status_code,
            headers={
                "X-Telic-Remaining": str(
                    max(0, FREE_DAILY_LIMIT - _get_device_usage(hashed)["count"])
                ),
            },
        )


@app.get("/status")
async def status():
    """Health check + usage stats (no sensitive data)."""
    return {
        "status": "ok",
        "active_devices": len(_usage),
        "free_daily_limit": FREE_DAILY_LIMIT,
    }


def _validate_license(key: str) -> bool:
    """Validate a Pro license key.

    Placeholder — in production, check against a database or
    Stripe subscription status. For now, accept a shared secret.
    """
    pro_key = os.environ.get("TELIC_PRO_KEY", "")
    return bool(pro_key and key == pro_key)
