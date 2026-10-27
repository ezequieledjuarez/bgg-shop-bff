from unittest.mock import patch

from app import app


def test_promotions_list_requires_auth():
    client = app.test_client()
    resp = client.get("/admin/promotions")
    assert resp.status_code == 401


def test_promotions_create_validation_and_success():
    client = app.test_client()
    payload = {"name": "Spring Sale", "discount_percent": 20, "active": True}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_promotions_controller.admin_create_promotion_service", return_value={"id": "1", "name": "Spring Sale"}):
            resp = client.post("/admin/promotions", json=payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "Spring Sale"
