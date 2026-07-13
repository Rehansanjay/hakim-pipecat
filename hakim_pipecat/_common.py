"""Shared wire-protocol helpers for the Hakim Pipecat services.

Both `stt.py` and `tts.py` talk directly to Hakim's public WebSocket API
(see https://tryhakim.ai/docs) using the `websockets` library Pipecat
already depends on. Nothing here depends on the `hakim` Python package.
"""

from __future__ import annotations

import os
from typing import Literal

Region = Literal["auto", "de", "uae", "ksa"]

_REGION_HOSTS: dict[str, str] = {
    "auto": "api.tryhakim.ai",
    "de": "de.api.tryhakim.ai",
    "uae": "uae.api.tryhakim.ai",
    "ksa": "ksa.api.tryhakim.ai",
}


def resolve_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("HAKIM_API_KEY")
    if not key:
        raise ValueError(
            "Hakim API key not set. Pass api_key=... or set the HAKIM_API_KEY "
            "environment variable. Get a key from the Hakim dashboard "
            "(Settings -> API keys)."
        )
    return key


def resolve_ws_url(path: str, *, region: Region = "auto", base_url: str | None = None) -> str:
    """Build the `wss://` upgrade URL for a realtime endpoint.

    `base_url` (if given) wins outright — it's how staging/self-hosted
    deployments override the default region hosts. Otherwise the region
    code maps to one of Hakim's published regional endpoints.
    """
    if base_url:
        host = (
            base_url.removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("wss://")
            .removeprefix("ws://")
            .rstrip("/")
        )
    else:
        host = _REGION_HOSTS.get(region, _REGION_HOSTS["auto"])
    return f"wss://{host}{path}"


class HakimStreamError(Exception):
    """Raised when a Hakim realtime session sends a fatal `error` frame.

    Mirrors the `code` / `message` / `retryable` fields on the server's
    `error` frame (see https://tryhakim.ai/docs) so callers can branch on
    `code` without parsing the raw frame themselves.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.retryable = retryable
