from __future__ import annotations

from app.utils.metrics import MetricsRegistry


def test_metrics_registry_enforces_max_events():
    registry = MetricsRegistry(max_events=3)
    for idx in range(5):
        registry.record("GET", f"/path/{idx}", 10.0, 200)
    assert len(registry._events) == 3  # bounded by max_events
    snapshot = registry.snapshot()
    assert snapshot["total_requests"] == 5


def test_snapshot_window_prunes_old_events(monkeypatch):
    registry = MetricsRegistry(max_events=10)
    fake_time = {"now": 0.0}

    def _fake_time() -> float:
        return fake_time["now"]

    monkeypatch.setattr("app.utils.metrics.time", _fake_time)
    registry.record("GET", "/old", 5.0, 200)
    fake_time["now"] = 10.0
    registry.record("POST", "/new", 6.0, 201)

    windowed = registry.snapshot_window(window_seconds=5)
    assert windowed["total_requests"] == 1
    assert windowed["routes"][0]["path"] == "/new"
