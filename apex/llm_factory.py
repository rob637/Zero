"""
LLM client factory — creates the right Anthropic client.

Three modes:
  1. BYOK:  User has ANTHROPIC_API_KEY → direct Anthropic client
  2. Proxy: No user key, TELIC_PROXY_URL set → proxy-backed client
  3. None:  No key, no proxy → returns None (setup required)

The proxy path uses the standard Anthropic SDK — it just points
base_url at our cloud proxy instead of api.anthropic.com.
"""

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Proxy URL — default to the Vercel deployment
# Override with TELIC_PROXY_URL env var for self-hosted
DEFAULT_PROXY_URL = "https://telic-proxy.vercel.app"

# Device ID — stable per-install identifier for rate limiting
_device_id: str | None = None


def _get_device_id() -> str:
    """Get or create a stable device identifier.

    Stored in ~/.telic/device_id. Never sent as raw —
    the proxy hashes it server-side.
    """
    global _device_id
    if _device_id:
        return _device_id

    device_path = Path.home() / ".telic" / "device_id"
    if device_path.exists():
        _device_id = device_path.read_text().strip()
    else:
        _device_id = str(uuid.uuid4())
        device_path.parent.mkdir(parents=True, exist_ok=True)
        device_path.write_text(_device_id)
        logger.info("Generated new device ID")

    return _device_id


def get_llm_mode() -> str:
    """Return the current LLM mode: 'byok', 'proxy', or 'none'."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "byok"
    if os.environ.get("OPENAI_API_KEY"):
        return "byok"
    # Proxy is available by default — users can disable with TELIC_PROXY=off
    if os.environ.get("TELIC_PROXY", "on").lower() != "off":
        return "proxy"
    return "none"


def create_anthropic_client():
    """Create an Anthropic client using the best available method.

    Returns (client, mode) where mode is 'byok' or 'proxy'.
    Returns (None, 'none') if no API key and no proxy.
    """
    import anthropic

    mode = get_llm_mode()

    if os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic(), "byok"

    if mode == "proxy":
        proxy_url = os.environ.get("TELIC_PROXY_URL", DEFAULT_PROXY_URL)
        device_id = _get_device_id()

        # The Anthropic SDK supports base_url — we point it at our proxy.
        # The proxy expects X-Device-Id for rate limiting.
        client = anthropic.Anthropic(
            api_key="telic-proxy",  # dummy — proxy uses its own key
            base_url=f"{proxy_url}",
            default_headers={
                "X-Device-Id": device_id,
            },
        )
        logger.info(f"Using Telic proxy ({proxy_url})")
        return client, "proxy"

    return None, "none"


def create_openai_client():
    """Create an OpenAI client if key is available."""
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        return openai.OpenAI(), "byok"
    return None, "none"
