"""API tests: accounts, household isolation, roles, invites, and the full
solve -> publish -> strike -> export loop.

    python -m pytest -c server/pytest.ini --rootdir=server server/tests
"""
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from server.db import DB
from server.main import app

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path):
    old = app.state.db
    app.state.db = DB(str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        app.state.db.close()
        app.state.db = old


def example_household(weeks=1):
    with open(os.path.join(ROOT, "config_example.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["start_day"] = str(cfg["start_day"])
    cfg["weeks_to_plan"] = weeks
    return cfg


def signup(client, email, name="Someone"):
    r = client.post("/auth/signup", json={"email": email, "password": "correct horse", "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def household(client, headers, name="Flat 4"):
    hid = client.post("/households", json={"name": name}, headers=headers).json()["id"]
    assert client.put(f"/households/{hid}/config", json=example_household(), headers=headers).status_code == 200
    return hid


def wait_for(client, hid, job_id, headers, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/households/{hid}/plans/{job_id}", headers=headers).json()
        if job["status"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("solve did not finish in time")


def test_signup_login_and_bad_password(client):
    signup(client, "dave@example.com", "Dave")
    assert client.post("/auth/signup", json={"email": "DAVE@example.com", "password": "another one", "name": "D"}).status_code == 409
    assert client.post("/auth/login", json={"email": "dave@example.com", "password": "nope nope"}).status_code == 401
    r = client.post("/auth/login", json={"email": "Dave@Example.com", "password": "correct horse"})
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me["user"]["name"] == "Dave" and me["households"] == []


def test_routes_need_a_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/households/1/config").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_households_are_isolated(client):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    hid = household(client, a)
    # B is not a member: the household simply doesn't exist for them
    assert client.get(f"/households/{hid}/config", headers=b).status_code == 404
    assert client.put(f"/households/{hid}/config", json=example_household(), headers=b).status_code == 404


def test_config_validation_uses_the_cli_rules(client):
    a = signup(client, "a@example.com")
    hid = client.post("/households", json={"name": "x"}, headers=a).json()["id"]
    h = example_household()
    h["exclusions"]["Alice"] = ["Laundry"]  # not a chore
    r = client.put(f"/households/{hid}/config", json=h, headers=a)
    assert r.status_code == 422 and "Laundry" in r.json()["detail"]


def test_invites_roles_and_leaving(client):
    admin = signup(client, "admin@example.com", "Dave")
    bob = signup(client, "bob@example.com", "Bob")
    hid = household(client, admin)

    code = client.post(f"/households/{hid}/invites", json={"role": "member"}, headers=admin).json()["code"]
    # members can't invite
    assert client.post(f"/households/{hid}/invites", json={}, headers=bob).status_code == 404
    pretty = f"{code[:3]}-{code[3:]}".lower()  # codes are forgiving about case and the dash
    joined = client.post(f"/invites/{pretty}/accept", json={"roommate": "Bob"}, headers=bob).json()
    assert joined == {"id": hid, "name": "Flat 4", "role": "member"}
    assert client.post(f"/invites/{code}/accept", json={}, headers=bob).status_code == 404  # one-time

    # members can read but not change the rules
    assert client.get(f"/households/{hid}/config", headers=bob).status_code == 200
    assert client.put(f"/households/{hid}/config", json=example_household(), headers=bob).status_code == 403
    assert client.post(f"/households/{hid}/plans", json={}, headers=bob).status_code == 403

    members = client.get(f"/households/{hid}/members", headers=admin).json()["members"]
    bob_id = next(m["id"] for m in members if m["name"] == "Bob")
    admin_id = next(m["id"] for m in members if m["name"] == "Dave")
    # the only admin can't step down or leave while others remain
    assert client.patch(f"/households/{hid}/members/{admin_id}", json={"role": "member"}, headers=admin).status_code == 409
    assert client.delete(f"/households/{hid}/members/{admin_id}", headers=admin).status_code == 409
    # a member can't promote themselves, but can leave
    assert client.patch(f"/households/{hid}/members/{bob_id}", json={"role": "admin"}, headers=bob).status_code == 403
    assert client.delete(f"/households/{hid}/members/{bob_id}", headers=bob).status_code == 200
    assert client.get(f"/households/{hid}/config", headers=bob).status_code == 404


def test_deleting_the_last_admin_hands_over_the_household(client):
    admin = signup(client, "admin@example.com", "Dave")
    bob = signup(client, "bob@example.com", "Bob")
    hid = household(client, admin)
    code = client.post(f"/households/{hid}/invites", json={}, headers=admin).json()["code"]
    client.post(f"/invites/{code}/accept", json={}, headers=bob)

    assert client.delete("/me", headers=admin).status_code == 200
    assert client.get("/me", headers=admin).status_code == 401  # tokens die with the account
    mine = client.get("/me", headers=bob).json()["households"]
    assert mine[0]["id"] == hid and mine[0]["role"] == "admin"


def test_full_loop(client):
    admin = signup(client, "admin@example.com", "Dave")
    hid = household(client, admin)
    assert client.get(f"/households/{hid}/schedule", headers=admin).status_code == 404

    job_id = client.post(f"/households/{hid}/plans", json={}, headers=admin).json()["job_id"]
    job = wait_for(client, hid, job_id, admin)
    assert job["status"] == "done", job["error"]
    candidates = job["result"]["candidates"]
    assert candidates, "every algorithm failed"
    # ranked best-first by the same tuple main.py sorts on
    assert [c["rank_key"] for c in candidates] == sorted(c["rank_key"] for c in candidates)
    best = candidates[0]

    published = client.post(f"/households/{hid}/plans/{job_id}/publish", json={"algorithm": best["key"]},
                            headers=admin).json()
    assert published["algorithm"] == best["key"]
    assert os.path.exists(app.state.db.state_path(hid))  # carry-over written like main.py

    slot = published["slots"][0]
    assert client.put(f"/households/{hid}/status/{slot['id']}", json={"state": "done"}, headers=admin).status_code == 200
    live = client.get(f"/households/{hid}/schedule", headers=admin).json()
    assert live["statuses"][slot["id"]]["state"] == "done"
    assert live["statuses"][slot["id"]]["updated_by"] == "Dave"

    r = client.put(f"/households/{hid}/status/{slot['id']}", json={"state": "partial", "sessions": ["done", None, None]},
                   headers=admin)
    assert r.json()["sessions"] == ["done", None, None]
    assert client.delete(f"/households/{hid}/status/{slot['id']}", headers=admin).status_code == 200
    assert client.get(f"/households/{hid}/schedule", headers=admin).json()["statuses"] == {}

    # plain links (e.g. Linking.openURL) authenticate with ?token=
    token = admin["Authorization"].split()[1]
    csv = client.get(f"/households/{hid}/export/csv?token={token}")
    assert csv.status_code == 200 and slot["task"] in csv.content.decode("utf-8-sig")
