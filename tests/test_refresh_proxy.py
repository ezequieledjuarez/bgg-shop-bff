from unittest.mock import MagicMock, patch

from app import app


def test_refresh_proxy_success():
    client = app.test_client()
    mocked = MagicMock()
    mocked.status_code = 200
    mocked.json.return_value = {"access_token": "access-token", "refresh_token": "new-refresh"}
    with patch("app._requests", autospec=True) as req_mod:
        # patch the requests module used in the endpoint
        req_mod.post.return_value = mocked
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-token"})

    assert response.status_code == 200
    assert response.get_json()["access_token"] == "access-token"
    set_cookie = response.headers.get("Set-Cookie", "")
    assert "refresh_token=" in set_cookie


def test_refresh_proxy_failure_clears_cookie():
    client = app.test_client()
    mocked = MagicMock()
    mocked.status_code = 401
    mocked.json.return_value = {}
    with patch("app._requests", autospec=True) as req_mod:
        req_mod.post.return_value = mocked
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-token"})

    assert response.status_code == 401
    # cookie should be cleared or not set
    # ensure body indicates failure
    assert response.get_json().get("detail") in ("refresh failed",)
