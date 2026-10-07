"""Configured private providers may use different credentials for each tenant."""
import json

import pytest

from gltg.integrations.giraffe_db_client import GiraffeDBNotConfigured, client_from_env


def test_tenant_credentials_are_selected_without_shared_key_fallback(monkeypatch):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "shared-must-not-fallback")
    monkeypatch.setenv("GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps({"tenant-a": "key-a", "tenant-b": "key-b"}))
    client = client_from_env()
    assert client._headers("tenant-a")["X-Service-Auth"] == "key-a"
    assert client._headers("tenant-b")["X-Service-Auth"] == "key-b"
    with pytest.raises(GiraffeDBNotConfigured):
        client._headers("unknown-tenant")
    assert "key-a" not in repr(client) and "key-b" not in repr(client)


@pytest.mark.parametrize("value", ["not-json", "[]", "{}", '{"tenant-a": ""}', '{"tenant-a": "line\\nbreak"}', '{"tenant-a": 12}'])
def test_invalid_tenant_credentials_fail_closed(monkeypatch, value):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", value)
    with pytest.raises(GiraffeDBNotConfigured):
        client_from_env()
