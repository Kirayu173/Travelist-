import pytest
from app.core.app import create_app
from app.utils.metrics import reset_metrics_registry
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    reset_metrics_registry()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
