"""Day-off cover options, swaps, and the request / approve flow."""
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from server import requests_logic as rl
from server.db import DB
from server.main import app

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------------ pure logic
def make_schedule(people_by_day, tasks=("Dishes",), start="2026-01-05"):  # a Monday
    import datetime
    d0 = datetime.date.fromisoformat(start)
    slots = []
    for i, people in enumerate(people_by_day):
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        for task, person in zip(tasks, people):
            slots.append({"id": f"{date}|{task}", "date": date, "day": "", "day_idx": i,
                          "task": task, "group": task, "person": person, "rest_before": None})
    return {"slots": slots, "metrics": {}}


CONFIG = {"roommates": ["Ann", "Ben", "Cat", "Dan"], "buffer_days": 1,
          "days_off": {"Dan": ["Wednesday"]}, "exclusions": {"Cat": ["Trash"]}}


def test_day_off_options_respect_hard_rules_and_rank_by_rest():
    # Mon..Thu, two chores a day
    s = make_schedule([("Ann", "Ben"), ("Cat", "Dan"), ("Ben", "Ann"), ("Dan", "Cat")], tasks=("Dishes", "Trash"))
    plan = rl.day_off_options(s, CONFIG, "Ben", "2026-01-07")  # Wednesday: Ben has Dishes
    assert [a["task"] for a in plan["affected"]] == ["Dishes"]
    blocked = {b["person"]: b["reason"] for b in plan["blocked"]}
    assert "off" in blocked["Dan"]            # Dan is off Wednesdays
    assert "already has a task" in blocked["Ann"]   # Ann does Trash that day
    assert [o["person"] for o in plan["options"]] == ["Cat"]
    assert plan["options"][0]["totals_after"]["Cat"] == plan["options"][0]["totals_before"]["Cat"] + 1


def test_exclusions_block_cover():
    s = make_schedule([("Ann", "Ben"), ("Cat", "Dan")], tasks=("Dishes", "Trash"))
    plan = rl.day_off_options(s, CONFIG, "Dan", "2026-01-06")  # Dan's Trash on Tuesday
    assert "never does Trash" in {b["person"]: b["reason"] for b in plan["blocked"]}["Cat"]


def test_apply_day_off_moves_the_task_and_records_the_date():
    s = make_schedule([("Ann",), ("Ben",), ("Cat",), ("Ann",), ("Ben",)])
    new_s, new_c, changes = rl.apply_day_off(s, CONFIG, "Ben", "2026-01-06", cover="Dan")
    assert changes == [{"slot_id": "2026-01-06|Dishes", "date": "2026-01-06", "task": "Dishes", "from": "Ben", "to": "Dan"}]
    assert next(x for x in new_s["slots"] if x["date"] == "2026-01-06")["person"] == "Dan"
    assert "2026-01-06" in new_c["days_off"]["Ben"]
    assert new_s["metrics"]["workload"] == {"Ann": 2, "Ben": 1, "Cat": 1, "Dan": 1}
    assert s["slots"][1]["person"] == "Ben"  # inputs untouched
    with pytest.raises(ValueError):
        rl.apply_day_off(s, CONFIG, "Ben", "2026-01-06", cover="Ben")


def test_day_off_without_tasks_just_records_it():
    s = make_schedule([("Ann",), ("Ben",)])
    new_s, new_c, changes = rl.apply_day_off(s, CONFIG, "Cat", "2026-01-05", cover=None)
    assert changes == [] and "2026-01-05" in new_c["days_off"]["Cat"]


def test_swap_checks_both_directions():
    s = make_schedule([("Ann", "Ben"), ("Cat", "Dan"), ("Ben", "Ann")], tasks=("Dishes", "Trash"))
    # Ann's Mon Dishes <-> Cat's Tue Dishes: fine
    assert rl.swap_check(s, CONFIG, "2026-01-05|Dishes", "2026-01-06|Dishes")["ok"]
    # Ben's Mon Trash <-> Cat's Tue Dishes: Cat never does Trash
    assert "never does Trash" in rl.swap_check(s, CONFIG, "2026-01-05|Trash", "2026-01-06|Dishes")["reason"]
    # Ben's Wed Dishes <-> Dan's Tue Trash: Dan is off Wednesdays
    assert "off" in rl.swap_check(s, CONFIG, "2026-01-07|Dishes", "2026-01-06|Trash")["reason"]
    new_s, changes = rl.apply_swap(s, CONFIG, "2026-01-05|Dishes", "2026-01-06|Dishes")
    by_id = {x["id"]: x["person"] for x in new_s["slots"]}
    assert by_id["2026-01-05|Dishes"] == "Cat" and by_id["2026-01-06|Dishes"] == "Ann"
    assert len(changes) == 2 and len(new_s["manual_changes"]) == 2


# ------------------------------------------------------------------ API flow
@pytest.fixture()
def client(tmp_path):
    old = app.state.db
    app.state.db = DB(str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        app.state.db.close()
        app.state.db = old


def signup(client, email, name):
    r = client.post("/auth/signup", json={"email": email, "password": "correct horse", "name": name})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def house(client):
    """Admin Dave + member Bob (linked to roommate Bob), one published week."""
    with open(os.path.join(ROOT, "config_example.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["start_day"], cfg["weeks_to_plan"] = str(cfg["start_day"]), 1
    cfg["roommates"] = ["Alice", "Bob", "Carol", "Dave"]
    dave, bob = signup(client, "dave@example.com", "Dave"), signup(client, "bob@example.com", "Bob")
    hid = client.post("/households", json={"name": "Home"}, headers=dave).json()["id"]
    assert client.put(f"/households/{hid}/config", json=cfg, headers=dave).status_code == 200
    code = client.post(f"/households/{hid}/invites", json={}, headers=dave).json()["code"]
    client.post(f"/invites/{code}/accept", json={"roommate": "Bob"}, headers=bob)
    job = client.post(f"/households/{hid}/plans", json={}, headers=dave).json()["job_id"]
    for _ in range(480):
        j = client.get(f"/households/{hid}/plans/{job}", headers=dave).json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    best = j["result"]["candidates"][0]["key"]
    schedule = client.post(f"/households/{hid}/plans/{job}/publish", json={"algorithm": best}, headers=dave).json()
    return {"hid": hid, "dave": dave, "bob": bob, "schedule": schedule}


def test_day_off_request_preview_and_approve(client, house):
    hid, dave, bob = house["hid"], house["dave"], house["bob"]
    bobs = next(s for s in house["schedule"]["slots"] if s["person"] == "Bob")
    r = client.post(f"/households/{hid}/requests", json={"kind": "day_off", "date": bobs["date"], "note": "travelling"}, headers=bob)
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["roommate"] == "Bob" and req["can_decide"] is False  # members don't approve days off

    inbox = client.get(f"/households/{hid}/requests?status=pending", headers=dave).json()
    assert inbox["waiting_on_you"] == 1
    preview = inbox["requests"][0]["preview"]
    assert preview["affected"][0]["id"] == bobs["id"]
    cover = preview["options"][0]["person"]

    assert client.post(f"/households/{hid}/requests/{req['id']}/approve", json={"cover": cover}, headers=bob).status_code == 403
    done = client.post(f"/households/{hid}/requests/{req['id']}/approve", json={"cover": cover}, headers=dave).json()
    assert done["status"] == "approved" and done["result"]["changes"][0]["to"] == cover

    live = client.get(f"/households/{hid}/schedule", headers=dave).json()["schedule"]
    assert next(s for s in live["slots"] if s["id"] == bobs["id"])["person"] == cover
    cfg = client.get(f"/households/{hid}/config", headers=dave).json()["household"]
    assert bobs["date"] in cfg["days_off"]["Bob"]
    # can't ask twice for the same day off
    again = client.post(f"/households/{hid}/requests", json={"kind": "day_off", "date": bobs["date"]}, headers=bob)
    assert again.status_code == 409


def test_members_can_only_ask_for_themselves(client, house):
    r = client.post(f"/households/{house['hid']}/requests", json={"kind": "day_off", "date": "2026-01-02", "roommate": "Alice"},
                    headers=house["bob"])
    assert r.status_code == 403


def test_swap_with_unlinked_roommate_goes_to_admin(client, house):
    hid, dave, bob = house["hid"], house["dave"], house["bob"]
    slots = house["schedule"]["slots"]
    mine = [s for s in slots if s["person"] == "Bob"]
    pair = None
    for m in mine:
        for o in slots:
            if o["person"] == "Alice":
                r = client.post(f"/households/{hid}/requests",
                                json={"kind": "swap", "slot_id": m["id"], "with_slot_id": o["id"]}, headers=bob)
                if r.status_code == 200:
                    pair = r.json()
                    break
        if pair:
            break
    assert pair, "no valid swap found in the sample week"
    assert pair["from"] == "Bob" and pair["to"] == "Alice"
    # Alice has no account, so an admin decides
    assert client.post(f"/households/{hid}/requests/{pair['id']}/approve", headers=bob).status_code == 403
    assert client.post(f"/households/{hid}/requests/{pair['id']}/approve", headers=dave).json()["status"] == "approved"
    live = {s["id"]: s["person"] for s in client.get(f"/households/{hid}/schedule", headers=dave).json()["schedule"]["slots"]}
    assert live[pair["slot_id"]] == "Alice" and live[pair["with_slot_id"]] == "Bob"


def test_cancel_and_decline(client, house):
    hid, dave, bob = house["hid"], house["dave"], house["bob"]
    a = client.post(f"/households/{hid}/requests", json={"kind": "day_off", "date": "2026-02-02"}, headers=bob).json()  # a Monday: Bob is off weekends
    assert client.post(f"/households/{hid}/requests/{a['id']}/cancel", headers=dave).status_code == 403
    assert client.post(f"/households/{hid}/requests/{a['id']}/cancel", headers=bob).json()["status"] == "cancelled"
    b = client.post(f"/households/{hid}/requests", json={"kind": "day_off", "date": "2026-02-03"}, headers=bob).json()
    assert client.post(f"/households/{hid}/requests/{b['id']}/decline", headers=dave).json()["status"] == "declined"
    assert client.post(f"/households/{hid}/requests/{b['id']}/approve", headers=dave).status_code == 409
