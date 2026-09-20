import asyncio
import json

import httpx
import pytest

import kit


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_disabled_without_key(monkeypatch):
    monkeypatch.setenv("KIT_API_KEY", "")
    assert kit.enabled() is False
    kit.tag_subscriber("a@example.com", kit.TAG_TRIAL)  # must not raise


def test_tag_flow_calls_kit_in_order(monkeypatch):
    monkeypatch.setenv("KIT_API_KEY", "kit_test_key")
    kit._tag_ids.clear()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        assert request.headers["X-Kit-Api-Key"] == "kit_test_key"
        if request.url.path == "/v4/tags":
            return httpx.Response(201, json={"tag": {"id": 42, "name": "PT Trial"}})
        if request.url.path == "/v4/subscribers":
            return httpx.Response(200, json={"subscriber": {"id": 1}})
        if request.url.path == "/v4/tags/42/subscribers":
            return httpx.Response(200, json={"subscriber": {"id": 1}})
        return httpx.Response(404)

    real_client = httpx.AsyncClient

    def patched(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    _run(kit.tag_subscriber_now("a@example.com", kit.TAG_TRIAL))
    _run(kit.tag_subscriber_now("b@example.com", kit.TAG_TRIAL))

    paths = [(m, p) for m, p, _ in calls]
    assert paths[:3] == [
        ("POST", "/v4/tags"),
        ("POST", "/v4/subscribers"),
        ("POST", "/v4/tags/42/subscribers"),
    ]
    assert calls[0][2] == {"name": "PT Trial"}
    assert calls[1][2]["email_address"] == "a@example.com"
    # second call reuses the cached tag id: no extra POST /tags
    assert paths[3:] == [("POST", "/v4/subscribers"), ("POST", "/v4/tags/42/subscribers")]


def test_error_surfaces(monkeypatch):
    monkeypatch.setenv("KIT_API_KEY", "bad")
    kit._tag_ids.clear()
    real_client = httpx.AsyncClient

    def patched(*a, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(401, json={"errors": ["nope"]}))
        return real_client(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    with pytest.raises(RuntimeError, match="Kit 401"):
        _run(kit.tag_subscriber_now("a@example.com", kit.TAG_MEMBER))
