from unittest.mock import patch

from app import app


def test_create_product_requires_name_and_valid_fields():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.post("/admin/products", json={}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    assert "name" in resp.get_data(as_text=True)


def test_adjust_stock_requires_integer_and_non_negative():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=True):
        # missing body
        resp = client.post("/admin/products/1/variants/1/adjust-stock", json={}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.post("/admin/products/1/variants/1/adjust-stock", json={"new_stock": "abc"}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.post("/admin/products/1/variants/1/adjust-stock", json={"new_stock": -5}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
