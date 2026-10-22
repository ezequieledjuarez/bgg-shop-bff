from unittest.mock import patch

from app import app


def test_admin_requires_authentication():
    client = app.test_client()
    resp = client.get("/admin/products")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Authentication required"


def test_admin_forbidden_for_non_admin():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=False):
        resp = client.get("/admin/products", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_admin_allows_admin_and_returns_list():
    client = app.test_client()
    sample = {"items": [], "page": 1}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_products_controller.admin_list_products_service", return_value=sample):
            resp = client.get("/admin/products", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    assert resp.get_json() == sample
