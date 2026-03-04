import os
import sys
os.environ["BSM_DB_BACKEND"] = "sqlite"
os.environ["BSM_DB_SQLITE_URL"] = "sqlite:///:memory:"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from src.bsm import db

client = TestClient(app)

def test_refresh_market_item(monkeypatch):
    # Mock authentication
    app.dependency_overrides = {}
    from backend.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"username": "testuser"}
    
    # Mock load_next_bili_session and get_item_detail
    monkeypatch.setattr("backend.routers.market.load_next_bili_session", lambda: {"cookies": "test_cookie"})
    
    mock_item_data = {
        "code": 0,
        "message": "success",
        "data": {
            "c2cItemsId": 195670144708,
            "type": 1,
            "c2cItemsName": "ALTER 测试手办",
            "showPrice": "850",
            "price": 85000,
            "publishStatus": 2,
            "saleStatus": 1,
            "dropReason": "手动下架",
            "detailDtoList": []
        }
    }
    monkeypatch.setattr("backend.routers.market.get_item_detail", lambda cookies, item_id: mock_item_data)
    
    # We also need to mock update_item_status and get_market_item if we don't want to hit the real DB
    monkeypatch.setattr("backend.routers.market.update_item_status", lambda **kwargs: None)
    monkeypatch.setattr("backend.routers.market.get_market_item", lambda item_id: {
        "id": 195670144708,
        "name": "ALTER 测试手办",
        "publish_status": 2,
        "sale_status": 1,
        "drop_reason": "手动下架"
    })
    
    response = client.post("/api/market/items/195670144708/refresh")
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())
    assert response.status_code == 200
    assert response.json()["item"]["publish_status"] == 2

def test_batch_refresh_market_items(monkeypatch):
    # Mock authentication
    app.dependency_overrides = {}
    from backend.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"username": "testuser"}
    
    # Mock load_next_bili_session and get_item_detail
    monkeypatch.setattr("backend.routers.market.load_next_bili_session", lambda: {"cookies": "test_cookie"})
    
    def mock_get_item_detail(cookies, item_id):
        return {
            "code": 0,
            "message": "success",
            "data": {
                "c2cItemsId": item_id,
                "type": 1,
                "c2cItemsName": f"Item {item_id}",
                "showPrice": "850",
                "price": 85000,
                "publishStatus": 2,
                "saleStatus": 1,
                "dropReason": "手动下架",
                "detailDtoList": []
            }
        }
    monkeypatch.setattr("backend.routers.market.get_item_detail", mock_get_item_detail)
    monkeypatch.setattr("backend.routers.market.update_item_status", lambda **kwargs: None)
    
    # Test batch with multiple valid IDs
    response = client.post("/api/market/items/batch-refresh", json={"ids": [111, 222, 333]})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    for r in results:
        assert r["ok"] is True
        assert r["publish_status"] == 2
        assert set(r.keys()).issuperset({"c2c_items_id", "publish_status", "sale_status", "drop_reason", "ok"})

    # Test capping at 10 items
    many_ids = list(range(1001, 1015)) # 14 items
    response = client.post("/api/market/items/batch-refresh", json={"ids": many_ids})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 10  # Should be capped at 10

    # Test empty request
    response = client.post("/api/market/items/batch-refresh", json={"ids": []})
    assert response.status_code == 400

if __name__ == "__main__":
    import pytest
    pytest.main(["-v", "-s", "tests/test_refresh_api.py"])

def test_batch_refresh_market_items(monkeypatch):
    # Mock authentication
    app.dependency_overrides = {}
    from backend.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"username": "testuser"}
    
    # Mock load_next_bili_session and get_item_detail
    monkeypatch.setattr("backend.routers.market.load_next_bili_session", lambda: {"cookies": "test_cookie"})
    
    def mock_get_item_detail(cookies, item_id):
        return {
            "code": 0,
            "message": "success",
            "data": {
                "c2cItemsId": item_id,
                "type": 1,
                "c2cItemsName": f"Item {item_id}",
                "showPrice": "850",
                "price": 85000,
                "publishStatus": 2,
                "saleStatus": 1,
                "dropReason": "手动下架",
                "detailDtoList": []
            }
        }
    monkeypatch.setattr("backend.routers.market.get_item_detail", mock_get_item_detail)
    monkeypatch.setattr("backend.routers.market.update_item_status", lambda **kwargs: None)
    
    # Test batch with multiple valid IDs
    response = client.post("/api/market/items/batch-refresh", json={"ids": [111, 222, 333]})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    for r in results:
        assert r["ok"] is True
        assert r["publish_status"] == 2
        assert set(r.keys()).issuperset({"c2c_items_id", "publish_status", "sale_status", "drop_reason", "ok"})

    # Test capping at 10 items
    many_ids = list(range(1001, 1015)) # 14 items
    response = client.post("/api/market/items/batch-refresh", json={"ids": many_ids})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 10  # Should be capped at 10

    # Test empty request
    response = client.post("/api/market/items/batch-refresh", json={"ids": []})
    assert response.status_code == 400
