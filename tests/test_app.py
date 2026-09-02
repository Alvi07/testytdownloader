import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data

def test_frontend_serve():
    response = client.get("/")
    assert response.status_code == 200
    assert "ProStream" in response.text

def test_invalid_url_info():
    response = client.post("/api/info", json={"url": "not-a-valid-url"})
    assert response.status_code == 400
