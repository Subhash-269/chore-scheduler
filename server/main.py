"""
main.py (server) - the HTTP API the mobile app talks to.

    python -m uvicorn server.main:app --host 0.0.0.0 --port 8000

Phase 1: one household, no accounts. Endpoints:
    GET  /health
    GET  /household              current household config (+ validation warnings)
    PUT  /household              validate with scheduler.load_config and save
    POST /plans                  start solving in the background -> {job_id}
    GET  /plans/{job_id}         per-algorithm progress, then ranked candidates
    POST /plans/{job_id}/publish make one candidate the live schedule
    GET  /schedule               live schedule + strike statuses
    PUT  /status/{slot_id}       strike / miss / cover / skip a task (or its sessions)
    DELETE /status/{slot_id}     clear it again
    GET  /export/{csv|docx|pdf}  the live schedule in the CLI's export formats
"""
import datetime
import os
import tempfile
import threading
import uuid
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import store
from .solver_service import ALGORITHMS, ConfigError, normalize_config, solve, write_state

app = FastAPI(title="Chore Scheduler API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# in-memory solve jobs: job_id -> dict. Raw solver output stays here (not JSON)
# until a candidate is published; a server restart simply forgets drafts.
_jobs = {}
_jobs_lock = threading.Lock()


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

    def solver_config(self):
        """The dict scheduler.load_config expects (app-only fields dropped)."""
        cfg = self.model_dump(exclude={"mode", "colors"}, exclude_none=True)
        for g in cfg["chore_groups"]:
            g.pop("sessions", None)
        cfg["days_off"] = {p: cfg["days_off"].get(p, []) for p in self.roommates}
        cfg["exclusions"] = {p: cfg["exclusions"].get(p, []) for p in self.roommates}
        return cfg


class PlanRequest(BaseModel):
    start_day: Optional[str] = None
    weeks_to_plan: Optional[int] = Field(None, ge=1, le=12)


class PublishRequest(BaseModel):
    algorithm: str


class Status(BaseModel):
    state: Literal["done", "missed", "covered", "skipped", "partial"]
    # one entry per session, left to right: "done" | "missed" | None (still to do)
    sessions: Optional[list[Optional[Literal["done", "missed"]]]] = None
    covered_by: Optional[str] = None
    note: Optional[str] = None


# ------------------------------------------------------------------ helpers
def _household():
    h = store.read(store.HOUSEHOLD)
    if h is None:
        raise HTTPException(404, "No household yet - finish onboarding first")
    return Household(**h)


def _validate(h: Household):
    try:
        return normalize_config(h.solver_config())
    except ConfigError as e:
        raise HTTPException(422, str(e))


def _public(job):
    """Job as JSON: drop the raw solver objects."""
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    if job.get("_result"):
        out["result"] = {k: v for k, v in job["_result"].items() if not k.startswith("_")}
    return out


# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    return {"ok": True, "algorithms": [label for _, label in ALGORITHMS]}


@app.get("/household")
def get_household():
    h = _household()
    _, warnings = _validate(h)
    return {"household": h.model_dump(), "warnings": warnings}


@app.put("/household")
def put_household(h: Household):
    _, warnings = _validate(h)
    store.write(store.HOUSEHOLD, h.model_dump())
    return {"household": h.model_dump(), "warnings": warnings}


@app.post("/plans")
def start_plan(req: PlanRequest = PlanRequest()):
    h = _household()
    if req.start_day:
        h.start_day = req.start_day
    if req.weeks_to_plan:
        h.weeks_to_plan = req.weeks_to_plan
    _validate(h)

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "progress": {key: {"label": label, "status": "queued", "seconds": None, "note": None}
                     for key, label in ALGORITHMS},
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def on_progress(key, status, seconds, note):
        job["progress"][key].update(status=status, note=note,
                                    seconds=None if seconds is None else round(seconds, 2))

    def run():
        try:
            job["_result"] = solve(h.solver_config(), state_path=store.path(store.STATE),
                                   on_progress=on_progress)
            job["status"] = "done"
        except Exception as e:  # surfaced to the app's Building screen
            job["status"] = "failed"
            job["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/plans/{job_id}")
def get_plan(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown or expired plan")
    return _public(job)


@app.post("/plans/{job_id}/publish")
def publish(job_id: str, req: PublishRequest):
    job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(409, "Plan is not finished")
    result = job["_result"]
    chosen = next((c for c in result["candidates"] if c["key"] == req.algorithm), None)
    if not chosen:
        raise HTTPException(404, f"No candidate '{req.algorithm}' in this plan")

    write_state(result, chosen["key"], store.path(store.STATE))
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
    store.write(store.SCHEDULE, schedule)
    store.write(store.STATUSES, {})  # a new schedule starts with nothing struck
    return schedule


@app.get("/schedule")
def get_schedule():
    schedule = store.read(store.SCHEDULE)
    if schedule is None:
        raise HTTPException(404, "No published schedule yet")
    return {"schedule": schedule, "statuses": store.read(store.STATUSES, {})}


@app.put("/status/{slot_id:path}")
def put_status(slot_id: str, status: Status):
    schedule = store.read(store.SCHEDULE)
    if schedule is None or not any(s["id"] == slot_id for s in schedule["slots"]):
        raise HTTPException(404, "No such task in the live schedule")
    statuses = store.read(store.STATUSES, {})
    statuses[slot_id] = {**status.model_dump(exclude_none=True),
                         "updated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    store.write(store.STATUSES, statuses)
    return statuses[slot_id]


@app.delete("/status/{slot_id:path}")
def clear_status(slot_id: str):
    statuses = store.read(store.STATUSES, {})
    statuses.pop(slot_id, None)
    store.write(store.STATUSES, statuses)
    return {"ok": True}


@app.get("/export/{fmt}")
def export(fmt: Literal["csv", "docx", "pdf"]):
    """Re-uses the CLI's exporters on the live schedule."""
    import scheduler  # repo-root module, already on sys.path via solver_service

    schedule = store.read(store.SCHEDULE)
    if schedule is None:
        raise HTTPException(404, "No published schedule yet")
    h = _household()
    cfg, _ = _validate(h)
    group_idx = {g["name"]: i for i, g in enumerate(cfg["chore_groups"])}
    slots = [{
        "date": datetime.date.fromisoformat(s["date"]), "day": s["day"], "day_idx": s["day_idx"],
        "task": s["task"], "group_idx": group_idx[s["group"]], "person": s["person"],
    } for s in schedule["slots"]]

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
