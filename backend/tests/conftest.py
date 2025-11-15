import pytest
from app.core.app import create_app
from app.services.admin_service import reset_metrics
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    reset_metrics()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
