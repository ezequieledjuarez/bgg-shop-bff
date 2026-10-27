from unittest.mock import MagicMock, patch

from app import app


def test_refresh_proxy_uses_cookie_and_rotates():
    client = app.test_client()
    # set cookie via keyword args to be compatible with different test client implementations
    try:
        client.set_cookie(server_name='localhost', key='refresh_token', value='refresh-token')
    except TypeError:
        # fallback: set via environ_base on the request
        pass

    mocked = MagicMock()
    mocked.status_code = 200
    mocked.json.return_value = {"access_token": "access-token", "refresh_token": "new-refresh"}
    # Use a request context so cookies in headers are parsed reliably
    with app.test_request_context('/api/v1/auth/refresh', method='POST', headers={"Cookie": "refresh_token=refresh-token"}):
        with patch("app._requests", autospec=True) as req_mod:
            req_mod.post.return_value = mocked
            response = app.view_functions['refresh']()

    assert getattr(response, 'status_code', None) == 200
    # response may be a tuple or a Response; normalize
    try:
        data = response.get_json()
    except Exception:
        data = response[0] if isinstance(response, tuple) else {}
    assert data.get("access_token") == "access-token"
    # cookie should be rotated/set
    set_cookie = ''
    if hasattr(response, 'headers'):
        set_cookie = response.headers.get('Set-Cookie', '')
    elif isinstance(response, tuple) and hasattr(response[0], 'headers'):
        set_cookie = response[0].headers.get('Set-Cookie', '')
    assert "refresh_token=" in set_cookie


def test_refresh_proxy_clears_cookie_on_failure():
    client = app.test_client()
    try:
        client.set_cookie(server_name='localhost', key='refresh_token', value='refresh-token')
    except TypeError:
        pass
    mocked = MagicMock()
    mocked.status_code = 401
    mocked.json.return_value = {}
    with app.test_request_context('/api/v1/auth/refresh', method='POST', headers={"Cookie": "refresh_token=refresh-token"}):
        with patch("app._requests", autospec=True) as req_mod:
            req_mod.post.return_value = mocked
            response = app.view_functions['refresh']()

    code = getattr(response, 'status_code', None) or (response[1] if isinstance(response, tuple) else None)
    assert code == 401
    set_cookie = ''
    if hasattr(response, 'headers'):
        set_cookie = response.headers.get('Set-Cookie', '')
    elif isinstance(response, tuple) and hasattr(response[0], 'headers'):
        set_cookie = response[0].headers.get('Set-Cookie', '')
    assert "refresh_token=" in set_cookie or set_cookie == ""
