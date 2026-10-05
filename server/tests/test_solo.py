"""Solo mode: one person, minutes balanced across days."""
import datetime
import json
import time

import pytest
from fastapi.testclient import TestClient

from server import solo
from server.db import DB
from server.main import app

START = "2026-01-05"  # a Monday


def config(**over):
    cfg = {
        "mode": "solo", "roommates": ["Sam"], "start_day": START, "weeks_to_plan": 2,
        "daily_cap_minutes": 60, "busy_days": ["Tuesday", "Thursday"], "busy_cap_minutes": 15,
        "days_off": {}, "exclusions": {},
        "chore_groups": [
            {"name": "Dishes", "tasks": ["Dishes"], "frequency_days": 1, "minutes": 15},
            {"name": "Vacuum", "tasks": ["Vacuum"], "frequency_days": 3, "tolerance_days": 1, "minutes": 20},
            {"name": "Mop", "tasks": ["Mop"], "piggyback_on": "Vacuum", "every_nth": 2, "minutes": 15},
            {"name": "Laundry", "tasks": ["Laundry"], "frequency_days": 7, "minutes": 40},
            {"name": "Bathroom", "tasks": ["Bathroom"], "frequency_days": 7, "tolerance_days": 1, "minutes": 30},
        ],
    }
    cfg.update(over)
    return cfg


def dates_of(slots, task):
    return sorted(datetime.date.fromisoformat(s["date"]) for s in slots if s["task"] == task)


def test_balanced_plan_keeps_every_rule():
    result = solo.plan(config())
    best = result["candidates"][0]
    assert best["key"] == "balanced"
    slots, m = best["slots"], best["metrics"]
    start = datetime.date.fromisoformat(START)
    # every window has its chore exactly once
    for task, f in (("Dishes", 1), ("Vacuum", 3), ("Laundry", 7), ("Bathroom", 7)):
        days = [(d - start).days for d in dates_of(slots, task)]
        windows = [d // f for d in days]
        assert windows == sorted(set(windows)) and len(windows) == -(-14 // f), task
    # spacing: frequency - tolerance
    vac = dates_of(slots, "Vacuum")
    assert all((b - a).days >= 2 for a, b in zip(vac, vac[1:]))
    # mop rides on every 2nd vacuum, same day
    assert dates_of(slots, "Mop") == vac[1::2]
    # caps hold: normal days <= 60, busy days (Tue/Thu) <= 15
    for date, minutes in m["daily_minutes"].items():
        wd = datetime.date.fromisoformat(date).weekday()
        assert minutes <= (15 if wd in (1, 3) else 60), (date, minutes)
    assert m["buffer_violations"] == 0 and m["days_over_cap"] == []
    normal = [v for d, v in m["daily_minutes"].items() if datetime.date.fromisoformat(d).weekday() not in (1, 3)]
    assert m["workload_spread"] == max(normal) - min(normal)   # minutes between heaviest and lightest normal day
    assert m["workload"] == {"Sam": len(slots)}


def test_balanced_beats_earliest_on_the_heaviest_day():
    by_key = {c["key"]: c["metrics"] for c in solo.plan(config())["candidates"]}
    assert by_key["balanced"]["heaviest_day_minutes"] <= by_key["earliest"]["heaviest_day_minutes"]
    assert by_key["balanced"]["buffer_violations"] <= by_key["earliest"]["buffer_violations"]


def test_days_off_get_nothing_movable():
    cfg = config(days_off={"Sam": ["Wednesday"]})
    slots = solo.plan(cfg)["candidates"][0]["slots"]
    wednesdays = {s["task"] for s in slots if datetime.date.fromisoformat(s["date"]).weekday() == 2}
    assert wednesdays <= {"Dishes"}  # daily dishes can't move; everything else avoids Wednesday


def test_carry_over_keeps_the_cadence():
    # laundry happened the day before the plan starts: next one at least 7 days later
    state = {"group_phase": {"Laundry": "2026-01-04"}}
    laundry = dates_of(solo.plan(config(), state=state)["candidates"][0]["slots"], "Laundry")
    assert laundry[0] >= datetime.date(2026, 1, 11)


def test_rejects_more_than_one_person():
    with pytest.raises(ValueError):
        solo.plan(config(roommates=["Sam", "Alex"]))


# ------------------------------------------------------------------ API
@pytest.fixture()
def client(tmp_path):
    old = app.state.db
    app.state.db = DB(str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        app.state.db.close()
        app.state.db = old


def test_solo_flow_over_the_api(client):
    h = {"Authorization": "Bearer " + client.post("/auth/signup", json={"email": "sam@example.com", "password": "correct horse", "name": "Sam"}).json()["token"]}
    hid = client.post("/households", json={"name": "My flat"}, headers=h).json()["id"]
    bad = client.put(f"/households/{hid}/config", json=config(roommates=["Sam", "Alex"]), headers=h)
    assert bad.status_code == 422
    assert client.put(f"/households/{hid}/config", json=config(), headers=h).status_code == 200

    job = client.post(f"/households/{hid}/plans", json={}, headers=h).json()["job_id"]
    for _ in range(120):
        j = client.get(f"/households/{hid}/plans/{job}", headers=h).json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    assert j["status"] == "done", j["error"]
    assert set(j["progress"]) == {"balanced", "earliest"}
    published = client.post(f"/households/{hid}/plans/{job}/publish", json={"algorithm": "balanced"}, headers=h).json()
    assert published["metrics"]["daily_minutes"]
    with open(app.state.db.state_path(hid), encoding="utf-8") as f:
        assert "Laundry" in json.load(f)["group_phase"]
    slot = published["slots"][0]
    assert client.put(f"/households/{hid}/status/{slot['id']}", json={"state": "done"}, headers=h).status_code == 200
