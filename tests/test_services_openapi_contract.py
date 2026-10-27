import pathlib


def test_openapi_includes_refresh_path():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    text = spec.read_text(encoding='utf-8')
    assert '/api/v1/auth/refresh:' in text
    # ensure response schema name present
    assert 'AuthRefreshResponse' in text
