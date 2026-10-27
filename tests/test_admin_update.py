from unittest.mock import patch

from app import app


def test_admin_update_product_requires_admin_and_updates():
    client = app.test_client()
    payload = {"name": "Updated name"}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_products_controller.admin_update_product_service", return_value={"id": "1", "name": "Updated name"}):
            resp = client.put("/admin/products/1", json=payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "Updated name"


def test_admin_update_product_validation_fails_when_no_fields():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.put("/admin/products/1", json={}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400


def test_admin_update_promotion_requires_admin_and_updates():
    client = app.test_client()
    payload = {"name": "New Promo"}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_promotions_controller.admin_update_promotion_service", return_value={"id": "1", "name": "New Promo"}):
            resp = client.put("/admin/promotions/1", json=payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "New Promo"


def test_admin_update_promotion_validation_fails_when_no_fields():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.put("/admin/promotions/1", json={}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
