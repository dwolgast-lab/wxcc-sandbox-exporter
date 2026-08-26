"""A recording fake transport. No test in this suite touches the network."""

import json

import pytest


class FakeResponse:
    def __init__(self, status=200, body="", content_type="application/json"):
        self.status = status
        self.body = body if isinstance(body, bytes) else body.encode()
        self.content_type = content_type


class FakeTransport:
    """Maps 'METHOD /path' -> FakeResponse or a list of them (consumed in order)."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def add(self, key, status=200, body=None, content_type="application/json"):
        payload = json.dumps(body) if not isinstance(body, (str, bytes, type(None))) else body
        self.routes.setdefault(key, []).append(
            FakeResponse(status, payload or "", content_type))
        return self

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append({"method": method, "url": url,
                           "headers": headers or {}, "data": data})
        path = url.split("://", 1)[-1]
        path = path[path.index("/"):] if "/" in path else "/"
        for key in (f"{method} {url}", f"{method} {path}"):
            queue = self.routes.get(key)
            if queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeResponse(404, json.dumps({"error": f"no route for {method} {path}"}))


@pytest.fixture
def transport():
    return FakeTransport()
