"""Offline tests must never reach paid model APIs."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def forbid_http_requests(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline tests must mock HTTP requests")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
