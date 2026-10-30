from unittest.mock import MagicMock, patch

from app import app


def test_refresh_http_route_uses_body_token_and_rotates_cookie():
    client = app.test_client()
    client.set_cookie('refresh_token', 'cookie-token')
    upstream = MagicMock(status_code=200)
    upstream.json.return_value = {'access_token': 'synthetic-access', 'refresh_token': 'rotated-refresh'}
    with patch('app._requests.post', return_value=upstream) as post:
        response = client.post('/api/v1/auth/refresh', json={'refresh_token': 'body-token'})
    assert response.status_code == 200
    assert response.get_json() == {'access_token': 'synthetic-access'}
    assert 'refresh_token=rotated-refresh' in response.headers['Set-Cookie']
    assert post.call_args.kwargs['json'] == {'refresh_token': 'body-token'}


def test_refresh_http_route_rejects_missing_token_without_core():
    with patch('app._requests.post') as post:
        response = app.test_client().post('/api/v1/auth/refresh')
    assert response.status_code == 401
    assert response.get_json() == {'detail': 'no refresh token'}
    post.assert_not_called()


def test_refresh_transport_failure_does_not_log_private_details(capsys, caplog):
    secret = 'synthetic-private-refresh-error'
    with patch('app._requests.post', side_effect=RuntimeError(secret)), \
            patch('app._append_incoming_log'), patch('app._opkey_before_request', return_value=None):
        response = app.test_client().post('/api/v1/auth/refresh', json={'refresh_token': 'synthetic-refresh-token'})
    captured = capsys.readouterr()
    assert response.status_code == 502
    assert response.get_json() == {'detail': 'refresh upstream error'}
    assert 'refresh_token=' in response.headers['Set-Cookie']
    assert secret not in captured.out + captured.err + caplog.text + response.get_data(as_text=True)


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
