"""Shared helpers for calling the Gnani Speech APIs.

Source: official Gnani docs, https://docs.gnani.ai (read on 2026-11-12)
  - Auth header `X-API-Key-ID` ................ /api/STT/speech-to-text.md, /api/TTS/tts-inference.md
  - Error shapes and codes ..................... /api/introduction/errors.md (same tables on the pages above)
  - "Only 1 active request is allowed at a time" (429 RATE_LIMITED, no Retry-After header)

The API key is read from .env on the server and only ever placed in the
request header to api.vachana.ai. It is never logged or sent to the browser.
"""
from __future__ import annotations

import asyncio

import httpx

from .. import config


def gnani_key_present() -> bool:
    return config.gnani_key_present()

AUTH_HEADER = "X-API-Key-ID"
BASE_URL = "https://api.vachana.ai"

# The docs say an account may be limited to one active request at a time,
# so all Gnani calls from this server go through one lock.
_gnani_lock = asyncio.Lock()

# Last result of a real call, shown by the status lights in the UI.
health = {"stt": {"ok": None, "error": None}, "tts": {"ok": None, "error": None}}


class GnaniNotConnected(RuntimeError):
    """No API key configured."""


class GnaniError(RuntimeError):
    """A Gnani call failed. `message` is safe to show to the worker."""

    def __init__(self, message: str, status: int = 502, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def require_key() -> str:
    if not gnani_key_present():
        raise GnaniNotConnected("Gnani API key is not set. Add GNANI_API_KEY to the .env file and restart the server.")
    return config.GNANI_API_KEY


def _error_text(resp: httpx.Response) -> str:
    """Pull the message out of any of the documented error shapes."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):                  # STT envelope
            return f"{body['error'].get('type', '')}: {body['error'].get('message', '')}".strip(": ")
        if isinstance(body.get("detail"), dict):                 # auth / rate limit
            return f"{body['detail'].get('error_code', '')}: {body['detail'].get('message', '')}".strip(": ")
        if isinstance(body.get("detail"), list):                 # 422 validation
            return "; ".join(str(d.get("msg", d)) for d in body["detail"])
        if body.get("message"):                                  # TTS flat / 504
            return str(body["message"])
    return ""


def raise_for_gnani(resp: httpx.Response, service: str) -> None:
    if resp.status_code < 400:
        return
    detail = _error_text(resp)
    code = resp.status_code
    if code == 401:
        msg = "Gnani rejected the API key (missing or invalid). Check GNANI_API_KEY in .env."
    elif code == 402:
        msg = "Gnani account has insufficient credit."
    elif code == 403:
        msg = f"This Gnani API key is not allowed to use {service}. Check the key's scopes on the Gnani dashboard."
    elif code == 429:
        raise GnaniError("Gnani is busy with another request. Please try again in a moment.", 429, retryable=True)
    elif code in (400, 422):
        msg = f"Gnani {service} could not process the request: {detail or 'bad request'}"
    elif code == 504:
        raise GnaniError(f"Gnani {service} timed out. Please try again.", 504, retryable=True)
    else:
        raise GnaniError(f"Gnani {service} service error ({code}). Please try again.", 502, retryable=True)
    raise GnaniError(msg, 502 if code >= 500 else code)


async def post(service: str, path: str, *, transport: httpx.AsyncBaseTransport | None = None, **kwargs) -> httpx.Response:
    """POST to Gnani with the key header, one request at a time, one retry on 429/5xx/timeout."""
    key = require_key()
    headers = {AUTH_HEADER: key, **kwargs.pop("headers", {})}
    attempts = 2
    async with _gnani_lock:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=config.REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
            for attempt in range(attempts):
                try:
                    resp = await client.post(path, headers=headers, **kwargs)
                    raise_for_gnani(resp, service)
                    health[service] = {"ok": True, "error": None}
                    return resp
                except httpx.TimeoutException:
                    err = GnaniError(f"Gnani {service} did not respond in time. Check the internet connection.", 504, True)
                except httpx.TransportError:
                    err = GnaniError(f"Cannot reach Gnani {service}. Check the internet connection.", 503, True)
                except GnaniError as e:
                    err = e
                if not err.retryable or attempt == attempts - 1:
                    health[service] = {"ok": False, "error": str(err)}
                    raise err
                await asyncio.sleep(1.0)
    raise AssertionError("unreachable")
