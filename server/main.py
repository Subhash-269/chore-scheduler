"""
main.py (server) - the HTTP API the mobile app talks to.

    python -m uvicorn server.main:app --host 0.0.0.0 --port 8000

Phase 2: accounts and separate households. Every household route needs a
bearer token (Authorization: Bearer <token>) from /auth/signup or /auth/login.

    GET    /health
    POST   /auth/signup | /auth/login | /auth/logout
    POST   /auth/apple | /auth/google      sign in with a provider identity token
    GET    /auth/providers                  which sign-in methods this server accepts
    GET    /me                                 user + households
    DELETE /me                                 delete the account (App Store requirement)

    POST   /households                          create one (you become admin)
    GET    /households/{hid}/members            roles + which roommate each account is
    PATCH  /households/{hid}/members/{uid}      admin: role / roommate link
    DELETE /households/{hid}/members/{uid}      admin, or yourself (leave)
    POST   /households/{hid}/invites            admin: one-time code
    POST   /invites/{code}/accept               join with a code

    GET|PUT /households/{hid}/config            household config (PUT: admin)
    POST   /households/{hid}/plans              admin: solve in the background -> {job_id}
    GET    /households/{hid}/plans/{job}        per-algorithm progress, then ranked candidates
    POST   /households/{hid}/plans/{job}/publish   admin: make one candidate live
    GET    /households/{hid}/schedule           live schedule + strike statuses
    PUT|DELETE /households/{hid}/status/{slot}  strike / miss / cover / skip (or clear)
    GET    /households/{hid}/export/{fmt}       csv | docx | pdf (?token= for plain links)

    POST   /households/{hid}/requests           ask for a day off, or to swap a task
    GET    /households/{hid}/requests           with cover options / swap impact for pending ones
    POST   /households/{hid}/requests/{rid}/approve | decline | cancel
"""
import datetime
import os
import tempfile
import threading
import uuid
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import auth, requests_logic, social, solo
from .db import DB, dumps, loads, now
from .solver_service import ALGORITHMS, ConfigError, normalize_config, solve, write_state

DATA_DIR = os.environ.get("CHORES_DATA_DIR",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
INVITE_TTL = 7 * 24 * 3600

app = FastAPI(title="Chore Scheduler API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.state.db = DB(DATA_DIR)

# in-memory solve jobs: job_id -> dict. Raw solver output stays here (not JSON)
# until a candidate is published; a server restart simply forgets drafts.
_jobs = {}
_jobs_lock = threading.Lock()

DEFAULT_SETTINGS = {
    # like the paper on the fridge: anyone can tick anyone's box
    "members_can_tick_any": True,
}


def db() -> DB:
    return app.state.db


# ------------------------------------------------------------------ models
class ChoreGroup(BaseModel):
    name: str
    tasks: list[str]
    frequency_days: Optional[int] = None
    tolerance_days: Optional[int] = None
    buffer_days: Optional[int] = None
    piggyback_on: Optional[str] = None
    every_nth: Optional[int] = None
    # app-only: named sessions within a day (e.g. breakfast/lunch/dinner);
    # the solver still sees one task, the app strikes each session
    sessions: Optional[list[str]] = None
    # solo mode: rough minutes, used to keep any one day from getting heavy
    minutes: Optional[int] = Field(None, ge=1, le=600)


class Household(BaseModel):
    mode: Literal["household", "solo"] = "household"
    roommates: list[str] = Field(min_length=1)
    colors: dict[str, str] = {}
    buffer_days: int = 2
    chore_groups: list[ChoreGroup] = Field(min_length=1)
    days_off: dict[str, list[str]] = {}
    exclusions: dict[str, list[str]] = {}
    random_seed: int | Literal["auto"] = 42
    start_day: str
    weeks_to_plan: int = Field(4, ge=1, le=12)
    # solo mode
    daily_cap_minutes: int = Field(60, ge=5, le=600)
    busy_days: list[str] = []
    busy_cap_minutes: int = Field(15, ge=0, le=600)

    def solver_config(self):
        """The dict scheduler.load_config expects (app-only fields dropped)."""
        cfg = self.model_dump(exclude={"mode", "colors", "daily_cap_minutes", "busy_days", "busy_cap_minutes"},
                              exclude_none=True)
        for g in cfg["chore_groups"]:
            g.pop("sessions", None)
            g.pop("minutes", None)
        cfg["days_off"] = {p: cfg["days_off"].get(p, []) for p in self.roommates}
        cfg["exclusions"] = {p: cfg["exclusions"].get(p, []) for p in self.roommates}
        return cfg


class Signup(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=60)


class Login(BaseModel):
    email: str
    password: str


class AppleLogin(BaseModel):
    identity_token: str
    # Apple only shares the name on the very first sign-in, so the app passes it along
    name: Optional[str] = Field(None, max_length=60)


class GoogleLogin(BaseModel):
    id_token: str


class NewHousehold(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class MemberPatch(BaseModel):
    role: Optional[Literal["admin", "member"]] = None
    roommate: Optional[str] = None


class NewInvite(BaseModel):
    role: Literal["admin", "member"] = "member"


class AcceptInvite(BaseModel):
    roommate: Optional[str] = None


class PlanRequest(BaseModel):
    start_day: Optional[str] = None
    weeks_to_plan: Optional[int] = Field(None, ge=1, le=12)


class PublishRequest(BaseModel):
    algorithm: str


class NewRequest(BaseModel):
    kind: Literal["day_off", "swap"]
    # day_off
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    roommate: Optional[str] = None      # defaults to your own roommate; admins can ask for anyone
    # swap: your task, and the other person's task you'd take instead
    slot_id: Optional[str] = None
    with_slot_id: Optional[str] = None
    note: Optional[str] = Field(None, max_length=200)


class Decision(BaseModel):
    cover: Optional[str] = None         # day_off: who takes the affected tasks


class Status(BaseModel):
    state: Literal["done", "missed", "covered", "skipped", "partial"]
    # one entry per session, left to right: "done" | "missed" | None (still to do)
    sessions: Optional[list[Optional[Literal["done", "missed"]]]] = None
    covered_by: Optional[str] = None
    note: Optional[str] = None


# ------------------------------------------------------------------ auth helpers
def _token_from(request: Request):
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.query_params.get("token")  # plain links, e.g. export opened in a browser


def current_user(request: Request):
    token = _token_from(request)
    if not token:
        raise HTTPException(401, "Sign in first")
    row = db().one("SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?",
                   auth.token_hash(token))
    if not row:
        raise HTTPException(401, "Your session has expired - sign in again")
    return row


def _member(hid: int, user):
    m = db().one("SELECT * FROM members WHERE household_id = ? AND user_id = ?", hid, user["id"])
    if not m:
        raise HTTPException(404, "No such household")
    return m


def member_of(hid: int, user=Depends(current_user)):
    return {"user": user, "member": _member(hid, user)}


def admin_of(hid: int, user=Depends(current_user)):
    m = _member(hid, user)
    if m["role"] != "admin":
        raise HTTPException(403, "Only admins can do that")
    return {"user": user, "member": m}


def _issue_token(user_id):
    token, h = auth.new_token()
    with db().tx() as c:
        c.execute("INSERT INTO tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)", (h, user_id, now()))
    return token


def _user_json(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"]}


# ------------------------------------------------------------------ household helpers
def _hh_row(hid):
    row = db().one("SELECT * FROM households WHERE id = ?", hid)
    if not row:
        raise HTTPException(404, "No such household")
    return row


def _config(hid):
    cfg = loads(_hh_row(hid)["config"])
    if cfg is None:
        raise HTTPException(404, "No household config yet - finish onboarding first")
    return Household(**cfg)


def _validate(h: Household):
    cfg = h.solver_config()
    if h.mode == "solo":
        if len(h.roommates) != 1:
            raise HTTPException(422, "Solo mode is for exactly one person")
        cfg["buffer_days"] = 0  # rest between people doesn't apply; the daily cap does that job
    try:
        return normalize_config(cfg)
    except ConfigError as e:
        raise HTTPException(422, str(e))


def _settings(hid):
    return {**DEFAULT_SETTINGS, **loads(_hh_row(hid)["settings"], {})}


def _public(job):
    """Job as JSON: drop the raw solver objects."""
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    if job.get("_result"):
        out["result"] = {k: v for k, v in job["_result"].items() if not k.startswith("_")}
    return out


# ------------------------------------------------------------------ routes: accounts
@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "algorithms": [label for _, label in ALGORITHMS]}


@app.post("/auth/signup")
def signup(body: Signup):
    if db().one("SELECT 1 FROM users WHERE email = ?", body.email.strip()):
        raise HTTPException(409, "An account with that email already exists - sign in instead")
    with db().tx() as c:
        cur = c.execute("INSERT INTO users (email, name, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                        (body.email.strip(), body.name.strip(), auth.hash_password(body.password), now()))
        uid = cur.lastrowid
    return {"token": _issue_token(uid), "user": _user_json(db().one("SELECT * FROM users WHERE id = ?", uid))}


@app.post("/auth/login")
def login(body: Login):
    u = db().one("SELECT * FROM users WHERE email = ?", body.email.strip())
    if not u or not auth.verify_password(body.password, u["pw_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return {"token": _issue_token(u["id"]), "user": _user_json(u)}


def _social_login(provider, subject, email, email_verified, name):
    """Sign in with a verified provider identity: the linked account if there is
    one, else a provider-only account with the same verified email, else a new one.

    Password accounts are never auto-linked: sign-up doesn't verify emails, so
    someone could pre-register a victim's address and have the victim's later
    Google/Apple sign-in land in an account whose password they know."""
    ident = db().one("SELECT user_id FROM identities WHERE provider = ? AND subject = ?", provider, subject)
    if ident:
        uid = ident["user_id"]
    else:
        existing = db().one("SELECT id, pw_hash FROM users WHERE email = ?", email) if email else None
        if existing and (existing["pw_hash"] != "!" or not email_verified):
            raise HTTPException(409, "An account with this email already exists - sign in with your password")
        with db().tx() as c:
            if existing:
                uid = existing["id"]
            else:
                # Apple may hide the email behind a relay address, or omit it after the first sign-in
                placeholder = email or f"{provider}-{subject}@users.chores.invalid"
                uid = c.execute("INSERT INTO users (email, name, pw_hash, created_at) VALUES (?, ?, '!', ?)",
                                (placeholder, (name or "").strip() or "New roommate", now())).lastrowid
            c.execute("INSERT INTO identities (provider, subject, user_id, email, created_at) VALUES (?, ?, ?, ?, ?)",
                      (provider, subject, uid, email, now()))
    return {"token": _issue_token(uid), "user": _user_json(db().one("SELECT * FROM users WHERE id = ?", uid))}


@app.get("/auth/providers")
def providers():
    return {"email": True, "apple": True, "google": social.google_enabled()}


@app.post("/auth/apple")
def login_apple(body: AppleLogin):
    try:
        subject, email, verified = social.verify_apple(body.identity_token)
    except social.SocialAuthError as e:
        raise HTTPException(401, str(e))
    return _social_login("apple", subject, email, verified, body.name)


@app.post("/auth/google")
def login_google(body: GoogleLogin):
    if not social.google_enabled():
        raise HTTPException(503, "Google sign-in isn't set up on this server yet")
    try:
        subject, email, verified, name = social.verify_google(body.id_token)
    except social.SocialAuthError as e:
        raise HTTPException(401, str(e))
    return _social_login("google", subject, email, verified, name)


@app.post("/auth/logout")
def logout(request: Request, user=Depends(current_user)):
    with db().tx() as c:
        c.execute("DELETE FROM tokens WHERE token_hash = ?", (auth.token_hash(_token_from(request)),))
    return {"ok": True}


@app.get("/me")
def me(user=Depends(current_user)):
    rows = db().all("""SELECT h.id, h.name, m.role, m.roommate, h.config IS NOT NULL AS configured,
                              h.schedule IS NOT NULL AS planned
                       FROM members m JOIN households h ON h.id = m.household_id
                       WHERE m.user_id = ? ORDER BY m.joined_at""", user["id"])
    return {"user": _user_json(user), "households": [dict(r) for r in rows]}


@app.delete("/me")
def delete_me(user=Depends(current_user)):
    """Delete the account. Households where you were the only admin are
    handed to the longest-standing member, or deleted if nobody is left."""
    with db().tx() as c:
        for m in c.execute("SELECT household_id FROM members WHERE user_id = ? AND role = 'admin'", (user["id"],)).fetchall():
            hid = m["household_id"]
            other_admin = c.execute("SELECT 1 FROM members WHERE household_id = ? AND role = 'admin' AND user_id != ?",
                                    (hid, user["id"])).fetchone()
            if other_admin:
                continue
            heir = c.execute("SELECT user_id FROM members WHERE household_id = ? AND user_id != ? ORDER BY joined_at LIMIT 1",
                             (hid, user["id"])).fetchone()
            if heir:
                c.execute("UPDATE members SET role = 'admin' WHERE household_id = ? AND user_id = ?", (hid, heir["user_id"]))
            else:
                c.execute("DELETE FROM households WHERE id = ?", (hid,))
        c.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    return {"ok": True}


# ------------------------------------------------------------------ routes: households & members
@app.post("/households")
def create_household(body: NewHousehold, user=Depends(current_user)):
    with db().tx() as c:
        hid = c.execute("INSERT INTO households (name, created_at) VALUES (?, ?)", (body.name.strip(), now())).lastrowid
        c.execute("INSERT INTO members (household_id, user_id, role, joined_at) VALUES (?, ?, 'admin', ?)",
                  (hid, user["id"], now()))
    return {"id": hid, "name": body.name.strip(), "role": "admin"}


@app.get("/households/{hid}/members")
def list_members(hid: int, ctx=Depends(member_of)):
    rows = db().all("""SELECT u.id, u.name, u.email, m.role, m.roommate, m.joined_at
                       FROM members m JOIN users u ON u.id = m.user_id
                       WHERE m.household_id = ? ORDER BY m.joined_at""", hid)
    invites = []
    if ctx["member"]["role"] == "admin":
        invites = [dict(r) for r in db().all(
            "SELECT code, role, expires_at FROM invites WHERE household_id = ? AND used_by IS NULL AND expires_at > ?",
            hid, now())]
    return {"members": [dict(r) for r in rows], "invites": invites, "settings": _settings(hid)}


@app.patch("/households/{hid}/members/{uid}")
def patch_member(hid: int, uid: int, body: MemberPatch, ctx=Depends(member_of)):
    me_ = ctx["user"]
    is_admin = ctx["member"]["role"] == "admin"
    # anyone may link their OWN account to a roommate name; everything else is admin-only
    if not is_admin and (uid != me_["id"] or body.role is not None):
        raise HTTPException(403, "Only admins can do that")
    target = db().one("SELECT * FROM members WHERE household_id = ? AND user_id = ?", hid, uid)
    if not target:
        raise HTTPException(404, "Not a member")
    if body.role == "member" and target["role"] == "admin":
        admins = db().one("SELECT COUNT(*) AS n FROM members WHERE household_id = ? AND role = 'admin'", hid)["n"]
        if admins <= 1:
            raise HTTPException(409, "A household needs at least one admin")
    if body.roommate is not None:
        cfg = loads(_hh_row(hid)["config"])
        if body.roommate and cfg and body.roommate not in cfg["roommates"]:
            raise HTTPException(422, f"'{body.roommate}' isn't one of this household's roommates")
    with db().tx() as c:
        if body.role is not None:
            c.execute("UPDATE members SET role = ? WHERE household_id = ? AND user_id = ?", (body.role, hid, uid))
        if body.roommate is not None:
            c.execute("UPDATE members SET roommate = ? WHERE household_id = ? AND user_id = ?",
                      (body.roommate or None, hid, uid))
    return {"ok": True}


@app.delete("/households/{hid}/members/{uid}")
def remove_member(hid: int, uid: int, ctx=Depends(member_of)):
    if ctx["member"]["role"] != "admin" and uid != ctx["user"]["id"]:
        raise HTTPException(403, "Only admins can remove other people")
    target = db().one("SELECT * FROM members WHERE household_id = ? AND user_id = ?", hid, uid)
    if not target:
        raise HTTPException(404, "Not a member")
    if target["role"] == "admin":
        admins = db().one("SELECT COUNT(*) AS n FROM members WHERE household_id = ? AND role = 'admin'", hid)["n"]
        others = db().one("SELECT COUNT(*) AS n FROM members WHERE household_id = ?", hid)["n"] - 1
        if admins <= 1 and others > 0:
            raise HTTPException(409, "Make someone else an admin first")
    with db().tx() as c:
        c.execute("DELETE FROM members WHERE household_id = ? AND user_id = ?", (hid, uid))
        if not c.execute("SELECT 1 FROM members WHERE household_id = ?", (hid,)).fetchone():
            c.execute("DELETE FROM households WHERE id = ?", (hid,))
    return {"ok": True}


@app.post("/households/{hid}/invites")
def create_invite(hid: int, body: NewInvite = NewInvite(), ctx=Depends(admin_of)):
    code = auth.invite_code()
    with db().tx() as c:
        c.execute("INSERT INTO invites (code, household_id, role, created_by, expires_at) VALUES (?, ?, ?, ?, ?)",
                  (code, hid, body.role, ctx["user"]["id"], now() + INVITE_TTL))
    return {"code": code, "role": body.role, "expires_at": now() + INVITE_TTL}


@app.delete("/households/{hid}/invites/{code}")
def revoke_invite(hid: int, code: str, ctx=Depends(admin_of)):
    with db().tx() as c:
        c.execute("DELETE FROM invites WHERE household_id = ? AND code = ?", (hid, code.upper()))
    return {"ok": True}


@app.post("/invites/{code}/accept")
def accept_invite(code: str, body: AcceptInvite = AcceptInvite(), user=Depends(current_user)):
    code = code.replace("-", "").strip().upper()
    inv = db().one("SELECT * FROM invites WHERE code = ?", code)
    if not inv or inv["used_by"] is not None or inv["expires_at"] < now():
        raise HTTPException(404, "That code is invalid or has expired - ask for a new one")
    hid = inv["household_id"]
    if db().one("SELECT 1 FROM members WHERE household_id = ? AND user_id = ?", hid, user["id"]):
        raise HTTPException(409, "You're already in this household")
    with db().tx() as c:
        c.execute("UPDATE invites SET used_by = ? WHERE code = ?", (user["id"], code))
        c.execute("INSERT INTO members (household_id, user_id, role, roommate, joined_at) VALUES (?, ?, ?, ?, ?)",
                  (hid, user["id"], inv["role"], body.roommate or None, now()))
    h = _hh_row(hid)
    return {"id": hid, "name": h["name"], "role": inv["role"]}


# ------------------------------------------------------------------ routes: config & planning
@app.get("/households/{hid}/config")
def get_config(hid: int, ctx=Depends(member_of)):
    h = _config(hid)
    _, warnings = _validate(h)
    return {"household": h.model_dump(), "warnings": warnings}


@app.put("/households/{hid}/config")
def put_config(hid: int, h: Household, ctx=Depends(admin_of)):
    _, warnings = _validate(h)
    with db().tx() as c:
        c.execute("UPDATE households SET config = ? WHERE id = ?", (dumps(h.model_dump()), hid))
    return {"household": h.model_dump(), "warnings": warnings}


@app.post("/households/{hid}/plans")
def start_plan(hid: int, req: PlanRequest = PlanRequest(), ctx=Depends(admin_of)):
    h = _config(hid)
    if req.start_day:
        h.start_day = req.start_day
    if req.weeks_to_plan:
        h.weeks_to_plan = req.weeks_to_plan
    _validate(h)

    job_id = uuid.uuid4().hex[:12]
    algorithms = SOLO_ALGORITHMS if h.mode == "solo" else ALGORITHMS
    job = {
        "id": job_id,
        "household_id": hid,
        "mode": h.mode,
        "status": "running",
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "progress": {key: {"label": label, "status": "queued", "seconds": None, "note": None}
                     for key, label in algorithms},
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def on_progress(key, status, seconds, note):
        job["progress"][key].update(status=status, note=note,
                                    seconds=None if seconds is None else round(seconds, 2))

    def run():
        try:
            if h.mode == "solo":
                job["_result"] = _solve_solo(h, hid, on_progress)
            else:
                job["_result"] = solve(h.solver_config(), state_path=db().state_path(hid), on_progress=on_progress)
            job["status"] = "done"
        except Exception as e:  # surfaced to the app's Building screen
            job["status"] = "failed"
            job["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


SOLO_ALGORITHMS = [("balanced", "Balanced"), ("earliest", "Earliest day")]


def _solve_solo(h: Household, hid, on_progress):
    cfg = h.model_dump()
    state = None
    path = db().state_path(hid)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            state = loads(f.read())
        if "group_phase" not in (state or {}):
            state = None  # a household-mode state file; cadence starts fresh
    for key, _ in SOLO_ALGORITHMS:
        on_progress(key, "running", None, None)
    t0 = datetime.datetime.now()
    result = solo.plan(cfg, state=state)
    seconds = (datetime.datetime.now() - t0).total_seconds()
    found = {c["key"] for c in result["candidates"]}
    for key, _ in SOLO_ALGORITHMS:
        on_progress(key, "done" if key in found else "failed", seconds, None)
    return result


def _job(hid, job_id):
    job = _jobs.get(job_id)
    if not job or job["household_id"] != hid:
        raise HTTPException(404, "Unknown or expired plan")
    return job


@app.get("/households/{hid}/plans/{job_id}")
def get_plan(hid: int, job_id: str, ctx=Depends(member_of)):
    return _public(_job(hid, job_id))


@app.post("/households/{hid}/plans/{job_id}/publish")
def publish(hid: int, job_id: str, req: PublishRequest, ctx=Depends(admin_of)):
    job = _job(hid, job_id)
    if job["status"] != "done":
        raise HTTPException(409, "Plan is not finished")
    result = job["_result"]
    chosen = next((c for c in result["candidates"] if c["key"] == req.algorithm), None)
    if not chosen:
        raise HTTPException(404, f"No candidate '{req.algorithm}' in this plan")

    if job.get("mode") == "solo":
        with open(db().state_path(hid), "w", encoding="utf-8") as f:
            f.write(dumps(solo.state_after(chosen)))
    else:
        write_state(result, chosen["key"], db().state_path(hid))
    schedule = {
        "published_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "start_day": result["start_day"],
        "days": result["days"],
        "algorithm": chosen["key"],
        "label": chosen["label"],
        "proven": chosen["proven"],
        "metrics": chosen["metrics"],
        "forced_violations": chosen.get("forced_violations", []),
        "cadence_violations": chosen.get("cadence_violations", []),
        "slots": chosen["slots"],
    }
    with db().tx() as c:
        c.execute("UPDATE households SET schedule = ? WHERE id = ?", (dumps(schedule), hid))
        c.execute("DELETE FROM statuses WHERE household_id = ?", (hid,))  # a new schedule starts unstruck
    return schedule


# ------------------------------------------------------------------ routes: live schedule
def _schedule(hid):
    schedule = loads(_hh_row(hid)["schedule"])
    if schedule is None:
        raise HTTPException(404, "No published schedule yet")
    return schedule


@app.get("/households/{hid}/schedule")
def get_schedule(hid: int, ctx=Depends(member_of)):
    schedule = _schedule(hid)
    statuses = {r["slot_id"]: loads(r["status"]) for r in
                db().all("SELECT slot_id, status FROM statuses WHERE household_id = ?", hid)}
    return {"schedule": schedule, "statuses": statuses}


def _check_can_mark(hid, ctx, slot):
    m = ctx["member"]
    if m["role"] == "admin" or _settings(hid)["members_can_tick_any"]:
        return
    if not m["roommate"] or slot["person"] != m["roommate"]:
        raise HTTPException(403, "In this household members can only mark their own tasks")


def _slot(hid, slot_id):
    slot = next((s for s in _schedule(hid)["slots"] if s["id"] == slot_id), None)
    if not slot:
        raise HTTPException(404, "No such task in the live schedule")
    return slot


@app.put("/households/{hid}/status/{slot_id:path}")
def put_status(hid: int, slot_id: str, status: Status, ctx=Depends(member_of)):
    _check_can_mark(hid, ctx, _slot(hid, slot_id))
    value = {**status.model_dump(exclude_none=True),
             "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "updated_by": ctx["user"]["name"]}
    with db().tx() as c:
        c.execute("""INSERT INTO statuses (household_id, slot_id, status, updated_by, updated_at)
                     VALUES (?, ?, ?, ?, ?)
                     ON CONFLICT (household_id, slot_id) DO UPDATE
                     SET status = excluded.status, updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
                  (hid, slot_id, dumps(value), ctx["user"]["id"], now()))
    return value


@app.delete("/households/{hid}/status/{slot_id:path}")
def clear_status(hid: int, slot_id: str, ctx=Depends(member_of)):
    _check_can_mark(hid, ctx, _slot(hid, slot_id))
    with db().tx() as c:
        c.execute("DELETE FROM statuses WHERE household_id = ? AND slot_id = ?", (hid, slot_id))
    return {"ok": True}


@app.get("/households/{hid}/export/{fmt}")
def export(hid: int, fmt: Literal["csv", "docx", "pdf"], ctx=Depends(member_of)):
    """Re-uses the CLI's exporters on the live schedule."""
    import scheduler  # repo-root module, already on sys.path via solver_service

    schedule = _schedule(hid)
    cfg, _ = _validate(_config(hid))
    group_idx = {g["name"]: i for i, g in enumerate(cfg["chore_groups"])}
    slots = [{
        "date": datetime.date.fromisoformat(s["date"]), "day": s["day"], "day_idx": s["day_idx"],
        "task": s["task"], "group_idx": group_idx[s["group"]], "person": s["person"],
    } for s in schedule["slots"] if s["group"] in group_idx]

    out = os.path.join(tempfile.mkdtemp(), f"chore_schedule.{fmt}")
    try:
        if fmt == "csv":
            scheduler.export_csv(slots, path=out)
        elif fmt == "docx":
            scheduler.export_docx(slots, cfg["chore_groups"], cfg["roommates"], path=out)
        else:
            scheduler.export_pdf(slots, cfg["chore_groups"], cfg["roommates"], path=out)
    except ImportError as e:
        raise HTTPException(501, f"{fmt.upper()} export needs an extra package: {e.name}")
    return FileResponse(out, filename=os.path.basename(out))


# ------------------------------------------------------------------ routes: requests
def _linked_user(hid, roommate):
    row = db().one("SELECT user_id FROM members WHERE household_id = ? AND roommate = ?", hid, roommate)
    return row["user_id"] if row else None


def _request_row(hid, rid):
    r = db().one("SELECT * FROM requests WHERE id = ? AND household_id = ?", rid, hid)
    if not r:
        raise HTTPException(404, "No such request")
    return r


def _can_decide(hid, ctx, req, payload):
    """Admins decide days off. Swaps are decided by the other person, or by
    admins when that roommate has no account yet."""
    if req["kind"] == "swap":
        uid = _linked_user(hid, payload["to"])
        if uid:
            return ctx["user"]["id"] == uid
    return ctx["member"]["role"] == "admin"


def _request_json(hid, r, ctx):
    payload = loads(r["payload"])
    creator = db().one("SELECT name FROM users WHERE id = ?", r["created_by"]) if r["created_by"] else None
    out = {
        "id": r["id"], "kind": r["kind"], "status": r["status"], "note": r["note"], **payload,
        "created_by": creator["name"] if creator else None, "mine": r["created_by"] == ctx["user"]["id"],
        "created_at": r["created_at"], "decided_at": r["decided_at"], "result": loads(r["result"]),
        "can_decide": False,
    }
    if r["status"] == "pending":
        schedule, config = _schedule(hid), _config(hid).model_dump()
        out["can_decide"] = _can_decide(hid, ctx, r, payload)
        if r["kind"] == "day_off":
            out["preview"] = requests_logic.day_off_options(schedule, config, payload["roommate"], payload["date"])
        else:
            out["preview"] = requests_logic.swap_check(schedule, config, payload["slot_id"], payload["with_slot_id"])
    return out


@app.post("/households/{hid}/requests")
def create_request(hid: int, body: NewRequest, ctx=Depends(member_of)):
    m = ctx["member"]
    config = _config(hid).model_dump()
    if body.kind == "day_off":
        if not body.date:
            raise HTTPException(422, "Pick a date")
        roommate = body.roommate or m["roommate"]
        if not roommate:
            raise HTTPException(422, "Link your account to a roommate first (Settings, You are)")
        if roommate not in config["roommates"]:
            raise HTTPException(422, f"'{roommate}' isn't one of this household's roommates")
        if roommate != m["roommate"] and m["role"] != "admin":
            raise HTTPException(403, "You can only ask for your own days off")
        if requests_logic.is_off(config, roommate, body.date):
            raise HTTPException(409, f"{roommate} is already off that day")
        payload = {"roommate": roommate, "date": body.date}
    else:
        if not body.slot_id or not body.with_slot_id:
            raise HTTPException(422, "Pick both tasks to swap")
        schedule = _schedule(hid)
        by_id = {s["id"]: s for s in schedule["slots"]}
        mine, theirs = by_id.get(body.slot_id), by_id.get(body.with_slot_id)
        if not mine or not theirs:
            raise HTTPException(404, "No such task in the live schedule")
        if mine["person"] != m["roommate"] and m["role"] != "admin":
            raise HTTPException(403, "You can only offer your own tasks")
        check = requests_logic.swap_check(schedule, config, body.slot_id, body.with_slot_id)
        if not check["ok"]:
            raise HTTPException(422, check["reason"])
        payload = {"slot_id": body.slot_id, "with_slot_id": body.with_slot_id,
                   "from": mine["person"], "to": theirs["person"]}
    with db().tx() as c:
        rid = c.execute("""INSERT INTO requests (household_id, kind, created_by, payload, note, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (hid, body.kind, ctx["user"]["id"], dumps(payload), body.note, now())).lastrowid
    return _request_json(hid, _request_row(hid, rid), ctx)


@app.get("/households/{hid}/requests")
def list_requests(hid: int, status: Optional[str] = None, ctx=Depends(member_of)):
    sql = "SELECT * FROM requests WHERE household_id = ?"
    args = [hid]
    if status:
        sql += " AND status = ?"
        args.append(status)
    rows = db().all(sql + " ORDER BY created_at DESC LIMIT 50", *args)
    items = [_request_json(hid, r, ctx) for r in rows]
    return {"requests": items, "waiting_on_you": sum(1 for i in items if i["can_decide"])}


def _pending(hid, rid):
    r = _request_row(hid, rid)
    if r["status"] != "pending":
        raise HTTPException(409, f"This request was already {r['status']}")
    return r


def _decide(hid, rid, ctx, status, result=None):
    with db().tx() as c:
        c.execute("UPDATE requests SET status = ?, decided_by = ?, decided_at = ?, result = ? WHERE id = ?",
                  (status, ctx["user"]["id"], now(), dumps(result) if result is not None else None, rid))
    return _request_json(hid, _request_row(hid, rid), ctx)


@app.post("/households/{hid}/requests/{rid}/approve")
def approve_request(hid: int, rid: int, body: Decision = Decision(), ctx=Depends(member_of)):
    r = _pending(hid, rid)
    payload = loads(r["payload"])
    if not _can_decide(hid, ctx, r, payload):
        raise HTTPException(403, "You can't decide this one")
    schedule, cfg = _schedule(hid), _config(hid)
    new_config = None
    try:
        if r["kind"] == "day_off":
            new_schedule, new_config, changes = requests_logic.apply_day_off(
                schedule, cfg.model_dump(), payload["roommate"], payload["date"], body.cover)
            _validate(Household(**new_config))
        else:
            new_schedule, changes = requests_logic.apply_swap(
                schedule, cfg.model_dump(), payload["slot_id"], payload["with_slot_id"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    with db().tx() as c:
        c.execute("UPDATE households SET schedule = ? WHERE id = ?", (dumps(new_schedule), hid))
        if new_config is not None:
            c.execute("UPDATE households SET config = ? WHERE id = ?", (dumps(new_config), hid))
    return _decide(hid, rid, ctx, "approved", {"changes": changes})


@app.post("/households/{hid}/requests/{rid}/decline")
def decline_request(hid: int, rid: int, ctx=Depends(member_of)):
    r = _pending(hid, rid)
    if not _can_decide(hid, ctx, r, loads(r["payload"])):
        raise HTTPException(403, "You can't decide this one")
    return _decide(hid, rid, ctx, "declined")


@app.post("/households/{hid}/requests/{rid}/cancel")
def cancel_request(hid: int, rid: int, ctx=Depends(member_of)):
    r = _pending(hid, rid)
    if r["created_by"] != ctx["user"]["id"]:
        raise HTTPException(403, "Only the person who asked can cancel")
    return _decide(hid, rid, ctx, "cancelled")
