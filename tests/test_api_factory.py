from fastapi.testclient import TestClient

from app.api import create_app


def test_api_routers_registered():
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/projects")
    assert response.status_code == 200
