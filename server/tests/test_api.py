"""End-to-end API test: example household -> solve -> publish -> strike -> export.

    python -m pytest server/tests -q
"""
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from server import store
from server.main import app

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    return TestClient(app)


def example_household(weeks=1):
    with open(os.path.join(ROOT, "config_example.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["start_day"] = str(cfg["start_day"])
    cfg["weeks_to_plan"] = weeks
    return cfg


def wait_for(client, job_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/plans/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("solve did not finish in time")


def test_household_validation_rejects_unknown_exclusion(client):
    h = example_household()
    h["exclusions"]["Alice"] = ["Laundry"]  # not a chore
    r = client.put("/household", json=h)
    assert r.status_code == 422
    assert "Laundry" in r.json()["detail"]


def test_full_loop(client):
    assert client.get("/schedule").status_code == 404
    assert client.put("/household", json=example_household()).status_code == 200

    job = wait_for(client, client.post("/plans", json={}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert all(p["status"] in ("done", "failed") for p in job["progress"].values())
    candidates = job["result"]["candidates"]
    assert candidates, "every algorithm failed"
    # ranked best-first by the same tuple main.py sorts on
    assert [c["rank_key"] for c in candidates] == sorted(c["rank_key"] for c in candidates)
    best = candidates[0]
    assert best["slots"] and {"id", "date", "task", "person"} <= best["slots"][0].keys()

    published = client.post(f"/plans/{job['id']}/publish", json={"algorithm": best["key"]}).json()
    assert published["algorithm"] == best["key"]
    assert os.path.exists(store.path(store.STATE))  # carry-over written like main.py

    slot = published["slots"][0]
    r = client.put(f"/status/{slot['id']}", json={"state": "done"})
    assert r.status_code == 200
    live = client.get("/schedule").json()
    assert live["statuses"][slot["id"]]["state"] == "done"

    r = client.put(f"/status/{slot['id']}", json={"state": "partial", "sessions": ["done", None, None]})
    assert r.json()["sessions"] == ["done", None, None]
    assert client.delete(f"/status/{slot['id']}").status_code == 200
    assert client.get("/schedule").json()["statuses"] == {}

    csv = client.get("/export/csv")
    assert csv.status_code == 200 and slot["task"] in csv.content.decode("utf-8-sig")
