"""
requests_logic.py - day-off cover options and swaps on a published schedule.

Pure functions over the schedule JSON (the shape solver_service publishes) and
the household config, so they're easy to test and never touch the database.

The same hard rules the solver uses apply to every manual change:
  - nobody works on their day off
  - nobody gets a chore they're excluded from
  - one task per person per day
Rest is soft: options are ranked by it and show it, but it doesn't block.
"""
import copy
import datetime

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weekday(date_str):
    return WEEKDAYS[datetime.date.fromisoformat(date_str).weekday()]


def is_off(config, person, date_str):
    entries = config.get("days_off", {}).get(person, [])
    return weekday(date_str) in entries or date_str in entries


def is_excluded(config, person, slot):
    ex = config.get("exclusions", {}).get(person, [])
    return slot["task"] in ex or slot["group"] in ex


def _busy(slots, person, date_str, ignore=()):
    return any(s["person"] == person and s["date"] == date_str and s["id"] not in ignore for s in slots)


def _gaps(slots, person, day_idx, ignore=()):
    """Rest days before and after day_idx for person (None = no task on that side)."""
    mine = sorted(s["day_idx"] for s in slots if s["person"] == person and s["id"] not in ignore)
    before = [d for d in mine if d < day_idx]
    after = [d for d in mine if d > day_idx]
    return (day_idx - before[-1] - 1 if before else None, after[0] - day_idx - 1 if after else None)


def workload(slots, roommates):
    counts = {p: 0 for p in roommates}
    for s in slots:
        counts[s["person"]] = counts.get(s["person"], 0) + 1
    return counts


def spread(counts):
    return (max(counts.values()) - min(counts.values())) if counts else 0


def recompute(schedule, roommates):
    """Refresh rest_before and the workload numbers after a manual change."""
    last = {}
    for s in sorted(schedule["slots"], key=lambda s: (s["day_idx"], s["group"], s["task"])):
        p = s["person"]
        s["rest_before"] = None if p not in last else s["day_idx"] - last[p] - 1
        last[p] = s["day_idx"]
    counts = workload(schedule["slots"], roommates)
    m = schedule.setdefault("metrics", {})
    m["workload"] = counts
    m["workload_spread"] = spread(counts)
    m["total_tasks"] = len(schedule["slots"])
    return schedule


def why_not(config, slots, person, slot, ignore=()):
    """None if person may take slot, else the reason they can't."""
    if is_off(config, person, slot["date"]):
        return f"{person} is off that day"
    if is_excluded(config, person, slot):
        return f"{person} never does {slot['task']}"
    if _busy(slots, person, slot["date"], ignore=ignore):
        return f"{person} already has a task that day"
    return None


# ------------------------------------------------------------------ day off
def day_off_options(schedule, config, roommate, date_str, limit=3):
    """Who could cover roommate's tasks on date_str, best first.

    Returns {"affected": [slot], "options": [...], "blocked": [...]}; each option
    assigns every affected slot to one person, with its rest and fairness impact."""
    slots = schedule["slots"]
    roommates = config["roommates"]
    affected = [s for s in slots if s["person"] == roommate and s["date"] == date_str]
    if not affected:
        return {"affected": [], "options": [], "blocked": []}
    ignore = {s["id"] for s in affected}
    before = workload(slots, roommates)
    buffer = config.get("buffer_days", 2)
    options, blocked = [], []
    for p in roommates:
        if p == roommate:
            continue
        reason = next((why_not(config, slots, p, s, ignore=ignore) for s in affected
                       if why_not(config, slots, p, s, ignore=ignore)), None)
        if reason:
            blocked.append({"person": p, "reason": reason})
            continue
        rest_before, rest_after = _gaps(slots, p, affected[0]["day_idx"], ignore=ignore)
        after = dict(before)
        after[roommate] -= len(affected)
        after[p] += len(affected)
        tight = [g for g in (rest_before, rest_after) if g is not None and g < buffer]
        options.append({
            "person": p,
            "rest_before": rest_before,
            "rest_after": rest_after,
            "short_rest": bool(tight),
            "totals_before": before,
            "totals_after": after,
            "spread_before": spread(before),
            "spread_after": spread(after),
            "changes": [{"slot_id": s["id"], "date": s["date"], "task": s["task"], "from": roommate, "to": p} for s in affected],
        })
    # rest first (no short rest, then most rest on the tighter side), then fairness, then fewest tasks
    def key(o):
        tighter = min(g for g in (o["rest_before"], o["rest_after"], 99) if g is not None)
        return (o["short_rest"], -tighter, o["spread_after"], o["totals_before"][o["person"]])
    options.sort(key=key)
    return {"affected": affected, "options": options[:limit], "blocked": blocked}


def apply_day_off(schedule, config, roommate, date_str, cover):
    """Mark roommate off on date_str and give their tasks that day to cover.
    Returns (new_schedule, new_config, changes). Raises ValueError if not allowed."""
    schedule = copy.deepcopy(schedule)
    config = copy.deepcopy(config)
    plan = day_off_options(schedule, config, roommate, date_str, limit=99)
    changes = []
    if plan["affected"]:
        option = next((o for o in plan["options"] if o["person"] == cover), None)
        if not option:
            reason = next((b["reason"] for b in plan["blocked"] if b["person"] == cover), f"{cover} can't take it")
            raise ValueError(reason)
        by_id = {s["id"]: s for s in schedule["slots"]}
        for ch in option["changes"]:
            by_id[ch["slot_id"]]["person"] = cover
        changes = option["changes"]
    off = config.setdefault("days_off", {}).setdefault(roommate, [])
    if date_str not in off:
        off.append(date_str)
    schedule.setdefault("manual_changes", []).extend(
        {**c, "reason": f"day off for {roommate}"} for c in changes)
    return recompute(schedule, config["roommates"]), config, changes


# ------------------------------------------------------------------ swaps
def swap_check(schedule, config, slot_a_id, slot_b_id):
    """Can the people on two slots trade them? -> dict with ok / reason / impact."""
    slots = schedule["slots"]
    by_id = {s["id"]: s for s in slots}
    a, b = by_id.get(slot_a_id), by_id.get(slot_b_id)
    if not a or not b:
        return {"ok": False, "reason": "One of those tasks isn't in the live schedule"}
    if a["person"] == b["person"]:
        return {"ok": False, "reason": "Both tasks belong to the same person"}
    pa, pb = a["person"], b["person"]
    ignore = {a["id"], b["id"]}
    for person, slot in ((pb, a), (pa, b)):
        reason = why_not(config, slots, person, slot, ignore=ignore)
        if reason:
            return {"ok": False, "reason": reason}
    swapped = copy.deepcopy(slots)
    for s in swapped:
        if s["id"] == a["id"]:
            s["person"] = pb
        elif s["id"] == b["id"]:
            s["person"] = pa
    buffer = config.get("buffer_days", 2)
    impact = {}
    for person, slot in ((pb, a), (pa, b)):
        rb, ra = _gaps(swapped, person, slot["day_idx"], ignore={slot["id"]})
        impact[person] = {"rest_before": rb, "rest_after": ra,
                          "short_rest": any(g is not None and g < buffer for g in (rb, ra))}
    return {"ok": True, "reason": None, "impact": impact}


def apply_swap(schedule, config, slot_a_id, slot_b_id):
    check = swap_check(schedule, config, slot_a_id, slot_b_id)
    if not check["ok"]:
        raise ValueError(check["reason"])
    schedule = copy.deepcopy(schedule)
    by_id = {s["id"]: s for s in schedule["slots"]}
    a, b = by_id[slot_a_id], by_id[slot_b_id]
    pa, pb = a["person"], b["person"]
    a["person"], b["person"] = pb, pa
    changes = [{"slot_id": a["id"], "date": a["date"], "task": a["task"], "from": pa, "to": pb},
               {"slot_id": b["id"], "date": b["date"], "task": b["task"], "from": pb, "to": pa}]
    schedule.setdefault("manual_changes", []).extend({**c, "reason": f"swap {pa} ↔ {pb}"} for c in changes)
    return recompute(schedule, config["roommates"]), changes
