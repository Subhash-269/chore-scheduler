"""
solver_service.py - runs the same pipeline as main.py, but for the app:
no prints, no input(), JSON-safe results, and per-algorithm progress so the
app's "Building" screen can show each one finishing.

Nothing here decides who does what - that is still optimizer.py. This file
only wires config -> algorithms -> polish -> ranking, exactly like main.py.
"""
import contextlib
import datetime
import io
import os
import random
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml  # noqa: E402

from optimizer import (  # noqa: E402
    algo_milp, algo_greedy, algo_simulated_annealing, algo_tabu_search,
    algo_genetic, algo_daily_hungarian, evaluate, count_structural_violations,
    rest_balance_spread,
)
from scheduler import (  # noqa: E402
    load_config, build_calendar, load_state, save_state, polish_and_report,
    check_state_freshness, schedule_rows_for_export,
)

# (key, label) in the order main.py runs them
ALGORITHMS = [
    ("milp", "MILP"),
    ("greedy", "Greedy"),
    ("sa", "Simulated annealing"),
    ("tabu", "Tabu search"),
    ("ga", "Genetic"),
    ("hungarian", "Hungarian"),
]


class ConfigError(ValueError):
    """The household config failed the same validation the CLI applies."""


@contextlib.contextmanager
def _quiet():
    """optimizer/scheduler report by printing; the API returns data instead."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def normalize_config(household):
    """Validate a household by running it through scheduler.load_config, so
    the app gets exactly the CLI's checks (unknown names, impossible
    exclusions, piggyback hosts...). Returns (cfg, warnings)."""
    fd, path = tempfile.mkstemp(suffix=".yml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(household, f, allow_unicode=True, sort_keys=False)
        with _quiet() as out:
            try:
                cfg = load_config(path)
            except SystemExit:
                message = out.getvalue().strip().lstrip("🚨").strip()
                raise ConfigError(message or "invalid household config") from None
    finally:
        os.unlink(path)
    warnings = [line.strip().lstrip("⚠️").strip() for line in out.getvalue().splitlines() if line.strip()]
    return cfg, warnings


def load_carry_over(state_path, start_day):
    """Previous run's state, or None if missing or not before start_day."""
    with _quiet():
        return check_state_freshness(load_state(state_path), start_day, path=state_path)


def _json_safe(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    return value


def slot_id(slot):
    return f"{slot['date'].isoformat()}|{slot['task']}"


def serialize_slots(slots, chore_groups):
    rest_by_id = {}
    for row in schedule_rows_for_export(slots):
        rest_by_id[f"{row['date']}|{row['task']}"] = None if row["rest"] == "First" else int(row["rest"])
    out = []
    for s in sorted(slots, key=lambda s: (s["day_idx"], s["group_idx"], s["task"])):
        sid = slot_id(s)
        out.append({
            "id": sid,
            "date": s["date"].isoformat(),
            "day": s["day"],
            "day_idx": s["day_idx"],
            "task": s["task"],
            "group": chore_groups[s["group_idx"]]["name"],
            "person": s["person"],
            "rest_before": rest_by_id.get(sid),
        })
    return out


def solve(household, state_path=None, on_progress=None):
    """Run all six algorithms + polish + ranking. Returns a dict with the
    ranked candidates (best first) and the raw slots needed to publish."""
    cfg, warnings = normalize_config(household)
    roommates = cfg["roommates"]
    chore_groups = cfg["chore_groups"]
    days_off = cfg["days_off"]
    exclusions = cfg["exclusions"]
    start_day = datetime.date.fromisoformat(cfg["start_day"])
    calendar, weekday = build_calendar(start_day, cfg["weeks_to_plan"] * 7)

    seed_setting = cfg["random_seed"]
    run_seed = random.randrange(1, 2 ** 31 - 1) if seed_setting == "auto" else seed_setting
    solver_order = list(roommates)
    random.Random(run_seed).shuffle(solver_order)
    prev_state = load_carry_over(state_path, start_day) if state_path else None

    def report(key, status, seconds=None, note=None):
        if on_progress:
            on_progress(key, status, seconds, note)

    def polish(slots):
        with _quiet():
            return polish_and_report("", slots, solver_order, chore_groups, days_off, calendar, weekday,
                                     cfg["buffer_days"], state=prev_state, exclusions=exclusions)

    raw = {}
    extras = {}

    # MILP first, like main.py - it's the only one that reports unavoidable exceptions
    report("milp", "running")
    t0 = time.time()
    with _quiet():
        milp_slots, note, forced, cadence = algo_milp(solver_order, chore_groups, days_off, calendar, weekday,
                                                      state=prev_state, exclusions=exclusions)
    raw["milp"] = polish(milp_slots)
    extras["milp"] = {"forced_violations": _json_safe(forced or []),
                      "cadence_violations": _json_safe(cadence or [])}
    report("milp", "done" if raw["milp"] else "failed", time.time() - t0, note)

    def heuristic(key, algo, *seed):
        report(key, "running")
        t = time.time()
        with _quiet():
            slots, n = algo(solver_order, chore_groups, days_off, calendar, weekday, *seed, exclusions=exclusions)
        raw[key] = polish(slots)
        report(key, "done" if raw[key] else "failed", time.time() - t, n)

    heuristic("greedy", algo_greedy)
    # SA, Tabu and GA re-decide WHO, starting from greedy's polished days
    seed_slots = raw["greedy"] or []
    heuristic("sa", algo_simulated_annealing, seed_slots)
    heuristic("tabu", algo_tabu_search, seed_slots)
    heuristic("ga", algo_genetic, seed_slots)
    heuristic("hungarian", algo_daily_hungarian)

    candidates = []
    for key, label in ALGORITHMS:
        slots = raw.get(key)
        if not slots:
            continue
        m = evaluate(roommates, chore_groups, slots, exclusions)
        structural = count_structural_violations(slots, chore_groups, days_off, calendar, weekday,
                                                 state=prev_state, exclusions=exclusions)
        rest_spread = rest_balance_spread(roommates, slots)
        candidates.append({
            "key": key,
            "label": label,
            "proven": key == "milp",
            # same priority order as main.py's ranking (and the MILP's staged objective)
            "rank_key": [structural, m["buffer_violations"], m["fairness_spread"],
                         round(rest_spread, 4), m["total_per_task_spread"]],
            "metrics": _json_safe({
                "structural_violations": structural,
                "buffer_violations": m["buffer_violations"],
                "workload_spread": m["fairness_spread"],
                "rest_balance_spread": round(rest_spread, 2),
                "per_chore_spread": m["total_per_task_spread"],
                "workload": m["workload"],
                "per_task_counts": m["per_task_counts"],
                "avg_rest": round(m["avg_rest"], 2),
                "min_rest": m["min_rest"],
                "total_tasks": m["total_tasks"],
            }),
            "slots": serialize_slots(slots, chore_groups),
            **extras.get(key, {}),
        })
    candidates.sort(key=lambda c: c["rank_key"])

    return {
        "start_day": start_day.isoformat(),
        "days": len(calendar),
        "roommates": roommates,
        "seed": run_seed,
        "warnings": warnings,
        "carried_over": prev_state is not None,
        "candidates": candidates,
        # not JSON - kept server-side so publish can write schedule_state exactly like main.py
        "_raw": raw,
        "_chore_groups": chore_groups,
    }


def write_state(result, key, state_path):
    """Persist the chosen candidate's carry-over, exactly like main.py's export step."""
    save_state(result["_raw"][key], result["roommates"], result["_chore_groups"],
               path=state_path, random_seed=result["seed"])
