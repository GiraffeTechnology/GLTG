"""A non-ASCII X-Service-Auth header must be rejected, not crash the server.

ASGI decodes request headers as latin-1, so a client that sends a single raw
header byte in 0x80-0xFF hands require_tenant_identity a ``str`` containing a
code point above U+007F. ``hmac.compare_digest`` raises ``TypeError`` on
exactly that input, which would turn a fail-closed 401 into an unhandled 500
for a caller that has not authenticated -- the opposite of what this module
exists to guarantee.

The end-to-end test builds the ASGI scope by hand. That is deliberate:
``TestClient`` (and the httpx stack under it) encodes header values before the
request is ever sent, so a ``TestClient``-based test raises
``UnicodeEncodeError`` in the client and passes whether or not the server is
fixed. ``test_testclient_cannot_reach_this`` pins that trap.
"""

from __future__ import annotations

import asyncio
import hmac
import json

import pytest

from gltg.api.secure_compare import secure_compare_str
from gltg.api.tenant_security import InboundIdentityError, require_tenant_identity

RAW_NON_ASCII = b"\xff"
DECODED_NON_ASCII = RAW_NON_ASCII.decode("latin-1")
SECRET = "expected-inbound-secret"


@pytest.fixture(autouse=True)
def _inbound_secret(monkeypatch):
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)


def test_raw_byte_really_decodes_to_non_ascii():
    """Guard the premise: the wire byte must survive as a non-ASCII str."""
    assert any(ord(ch) > 0x7F for ch in DECODED_NON_ASCII)


def test_compare_digest_would_raise_on_this_input():
    """Pin why the guard exists: the stdlib call this replaced raises here."""
    with pytest.raises(TypeError):
        hmac.compare_digest(DECODED_NON_ASCII, SECRET)


def test_secure_compare_str_rejects_non_ascii_without_raising():
    assert secure_compare_str(DECODED_NON_ASCII, SECRET) is False


def test_secure_compare_str_still_matches_equal_secrets():
    assert secure_compare_str(SECRET, SECRET) is True
    assert secure_compare_str(SECRET, SECRET[:-1] + "x") is False


def test_secure_compare_str_handles_lone_surrogates():
    """Strict encoding would raise UnicodeEncodeError; surrogateescape must not."""
    assert secure_compare_str("\udcff", SECRET) is False


def test_non_ascii_auth_header_fails_closed():
    with pytest.raises(InboundIdentityError) as excinfo:
        require_tenant_identity("tenant-1", DECODED_NON_ASCII, ["tenant-1"])
    assert excinfo.value.code == "CALLER_AUTH_INVALID"
    assert excinfo.value.status_code == 401


def test_correct_secret_still_authenticates():
    assert require_tenant_identity("tenant-1", SECRET, ["tenant-1"]) == "tenant-1"


def test_tenant_mismatch_still_rejected():
    with pytest.raises(InboundIdentityError) as excinfo:
        require_tenant_identity("tenant-1", SECRET, ["tenant-2"])
    assert excinfo.value.code == "TENANT_CONTEXT_MISMATCH"


def _call_asgi(app, method, path, headers, body=b""):
    """Drive the ASGI app directly so raw header bytes reach the server."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return start["status"], payload


def test_non_ascii_auth_header_is_401_not_500_end_to_end():
    """The whole app, driven over raw ASGI, must answer 401 and not raise."""
    from gltg.api.main import app

    body = json.dumps(
        {
            "request_id": "NON-ASCII-1",
            "tenant_id": "tenant-1",
            "order": {"product_type": "t-shirt", "quantity": 1000},
        }
    ).encode()
    status, _ = _call_asgi(
        app,
        "POST",
        "/v2/lead-time/simulate",
        [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-service-tenant-id", b"tenant-1"),
            (b"x-service-auth", RAW_NON_ASCII),
        ],
        body=body,
    )
    assert status == 401


def test_testclient_cannot_reach_this():
    """Documents why the end-to-end test does not use TestClient.

    httpx encodes header values before sending, so a TestClient-based version
    fails in the client and never exercises the server. A test written that
    way passes against unfixed code.
    """
    import httpx

    with pytest.raises(UnicodeEncodeError):
        httpx.Headers({"X-Service-Auth": DECODED_NON_ASCII}).raw
