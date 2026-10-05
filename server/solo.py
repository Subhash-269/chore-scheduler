"""
solo.py - planning for one person: balance minutes across days.

With one person there's nobody to share with, so "fair" means no day gets
heavy. Same window rule as the household solver (each chore exactly once per
frequency window, consecutive occurrences at least frequency - tolerance days
apart, piggyback chores on every nth host occurrence), but instead of
assigning people it picks days, keeping each day under a minutes cap (lower on
busy days) and the heaviest day as light as possible. Solved exactly with
scipy's MILP (HiGHS), plus a simple "earliest day" plan to compare against.

Output is the same schedule JSON the household solver publishes, so Today,
the fridge board, previews and requests all work unchanged.
"""
import datetime

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .requests_logic import WEEKDAYS, recompute

DEFAULT_MINUTES = 15


def _occurrences(groups, total_days, phase):
    """Windows for each independent chore: [(group, k, first_day, last_day)]."""
    occ = []
    for g in groups:
        if g.get("piggyback_on"):
            continue
        f = g["frequency_days"]
        offset = phase.get(g["name"], 0)
        k, start = 0, 0
        while start < total_days:
            occ.append((g, k, start, min(start + f, total_days) - 1, offset if k == 0 else 0))
            k, start = k + 1, start + f
    return occ


def _piggy_minutes(groups, host_name, k):
    """Minutes added to host occurrence k by chores that ride on it."""
    extra, riders = 0, []
    for g in groups:
        if g.get("piggyback_on") == host_name and (k + 1) % max(1, g.get("every_nth") or 1) == 0:
            extra += g.get("minutes") or DEFAULT_MINUTES
            riders.append(g)
    return extra, riders


def _caps(config, calendar):
    cap = config.get("daily_cap_minutes") or 60
    busy_cap = config.get("busy_cap_minutes")
    busy_cap = 15 if busy_cap is None else busy_cap
    busy = set(config.get("busy_days") or [])
    person = config["roommates"][0]
    off = set(config.get("days_off", {}).get(person, []))
    caps, kinds = [], []
    for d in calendar:
        wd = WEEKDAYS[d.weekday()]
        if wd in off or d.isoformat() in off:
            caps.append(0)
            kinds.append("off")
        elif wd in busy:
            caps.append(busy_cap)
            kinds.append("busy")
        else:
            caps.append(cap)
            kinds.append("normal")
    return caps, kinds


def _phase_from_state(groups, state, start):
    """Earliest allowed day in the first window, so cadence continues from last plan."""
    phase = {}
    for g in groups:
        last = (state or {}).get("group_phase", {}).get(g["name"])
        if last and not g.get("piggyback_on"):
            gap = g["frequency_days"] - (g.get("tolerance_days") or 0)
            earliest = (datetime.date.fromisoformat(last) - start).days + gap
            phase[g["name"]] = max(0, earliest)
    return phase


def _solve_milp(occ, groups, caps, kinds):
    n_occ, n_days = len(occ), len(caps)
    # variables: x[o, d] for each occurrence and each day in its window, then over[d], then L
    var = {}
    for o, (g, k, a, b, earliest) in enumerate(occ):
        for d in range(max(a, earliest), b + 1):
            var[(o, d)] = len(var)
    if any(not any((o, d) in var for d in range(n_days)) for o in range(n_occ)):
        return None  # a window too short for the carried-over cadence
    n_x = len(var)
    over0, L = n_x, n_x + n_days
    n = n_x + n_days + 1

    minutes = []
    for g, k, *_ in occ:
        extra, _ = _piggy_minutes(groups, g["name"], k)
        minutes.append((g.get("minutes") or DEFAULT_MINUTES) + extra)

    rows, lo, hi = [], [], []
    def row(coefs, lb, ub):
        r = np.zeros(n)
        for i, c in coefs:
            r[i] += c
        rows.append(r)
        lo.append(lb)
        hi.append(ub)

    for o in range(n_occ):                                   # each occurrence exactly once
        row([(var[(o, d)], 1) for d in range(n_days) if (o, d) in var], 1, 1)
    by_group = {}
    for o, (g, k, *_ ) in enumerate(occ):
        by_group.setdefault(g["name"], []).append(o)
    for name, os_ in by_group.items():                      # spacing between consecutive occurrences
        g = occ[os_[0]][0]
        gap = g["frequency_days"] - (g.get("tolerance_days") or 0)
        for o1, o2 in zip(os_, os_[1:]):
            for d1 in range(n_days):
                if (o1, d1) not in var:
                    continue
                for d2 in range(d1, min(n_days, d1 + gap)):
                    if (o2, d2) in var:
                        row([(var[(o1, d1)], 1), (var[(o2, d2)], 1)], -np.inf, 1)
    for d in range(n_days):
        load = [(var[(o, d)], minutes[o]) for o in range(n_occ) if (o, d) in var]
        row(load + [(over0 + d, -1)], -np.inf, caps[d])     # load - over <= cap
        if kinds[d] == "normal":
            row(load + [(L, -1)], -np.inf, 0)                # load <= L (heaviest normal day)

    c = np.zeros(n)
    c[over0:over0 + n_days] = 1000                          # going over a cap: last resort
    c[L] = 10                                                # then keep the heaviest day light
    for (o, d), i in var.items():                            # tiny nudge: earlier in the window
        c[i] = 0.001 * (d - occ[o][2])
    integrality = np.zeros(n)
    integrality[:n_x] = 1
    res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integrality,
               bounds=Bounds(np.r_[np.zeros(n_x), np.zeros(n_days), 0], np.r_[np.ones(n_x), np.full(n_days, np.inf), np.inf]),
               options={"time_limit": 20})
    if res.x is None:
        return None
    return {o: d for (o, d), i in var.items() if res.x[i] > 0.5}


def _solve_earliest(occ):
    """Baseline: every chore on the first day it's allowed."""
    chosen, last = {}, {}
    for o, (g, k, a, b, earliest) in enumerate(occ):
        gap = g["frequency_days"] - (g.get("tolerance_days") or 0)
        lo = max(a, earliest, last.get(g["name"], -10 ** 6) + gap)
        chosen[o] = min(lo, b)
        last[g["name"]] = chosen[o]
    return chosen


def _schedule(occ, groups, chosen, calendar, person, caps, kinds):
    slots = []
    for o, d in chosen.items():
        g, k, *_ = occ[o]
        _, riders = _piggy_minutes(groups, g["name"], k)
        for grp in [g, *riders]:
            for task in grp["tasks"]:
                date = calendar[d].isoformat()
                slots.append({"id": f"{date}|{task}", "date": date, "day": WEEKDAYS[calendar[d].weekday()],
                              "day_idx": d, "task": task, "group": grp["name"], "person": person, "rest_before": None})
    minutes_of = {g["name"]: g.get("minutes") or DEFAULT_MINUTES for g in groups}
    daily = [0] * len(calendar)
    seen_groups = set()
    for s in slots:
        key = (s["day_idx"], s["group"])
        if key not in seen_groups:      # minutes count once per chore group per day
            seen_groups.add(key)
            daily[s["day_idx"]] += minutes_of[s["group"]]
    over_days = [i for i, m in enumerate(daily) if m > caps[i]]
    normal = [m for m, k in zip(daily, kinds) if k == "normal"]
    per_task = {}
    for s in slots:
        per_task.setdefault(s["task"], {person: 0})[person] += 1
    # recompute() fills rest and per-person workload; the solo meanings of the
    # numbers below (minutes, not tasks per person) are set after it, not overwritten by it
    schedule = recompute({"slots": sorted(slots, key=lambda s: (s["day_idx"], s["group"], s["task"])), "metrics": {}},
                         [person])
    schedule["metrics"].update({
                    "structural_violations": 0,
                    "buffer_violations": len(over_days),     # shown as "exceptions": days over their cap
                    "workload_spread": (max(normal) - min(normal)) if normal else 0,  # minutes, heaviest vs lightest day
                    "rest_balance_spread": 0, "per_chore_spread": 0,
                    "per_task_counts": per_task, "avg_rest": 0, "min_rest": 0,
                    "daily_minutes": {calendar[i].isoformat(): m for i, m in enumerate(daily)},
                    "heaviest_day_minutes": max(normal) if normal else 0,
                    "days_over_cap": [calendar[i].isoformat() for i in over_days],
                })
    return schedule


def plan(config, state=None):
    """Two candidates for a solo household, best first, in solver_service's shape."""
    if len(config["roommates"]) != 1:
        raise ValueError("Solo mode plans for exactly one person")
    person = config["roommates"][0]
    start = datetime.date.fromisoformat(config["start_day"])
    total = config["weeks_to_plan"] * 7
    calendar = [start + datetime.timedelta(days=i) for i in range(total)]
    groups = config["chore_groups"]
    for g in groups:
        if g.get("piggyback_on") and not any(h["name"] == g["piggyback_on"] for h in groups):
            raise ValueError(f"'{g['name']}' rides on '{g['piggyback_on']}', which doesn't exist")
        if not g.get("piggyback_on") and not g.get("frequency_days"):
            raise ValueError(f"'{g['name']}' needs a frequency")
    caps, kinds = _caps(config, calendar)
    occ = _occurrences(groups, total, _phase_from_state(groups, state, start))

    candidates = []
    for key, label, chosen in (("balanced", "Balanced", _solve_milp(occ, groups, caps, kinds)),
                               ("earliest", "Earliest day", _solve_earliest(occ))):
        if chosen is None:
            continue
        s = _schedule(occ, groups, chosen, calendar, person, caps, kinds)
        m = s["metrics"]
        candidates.append({"key": key, "label": label, "proven": key == "balanced",
                           "rank_key": [m["buffer_violations"], m["heaviest_day_minutes"], m["workload_spread"]],
                           "metrics": m, "slots": s["slots"],
                           "forced_violations": [], "cadence_violations": []})
    candidates.sort(key=lambda c: c["rank_key"])
    return {"start_day": start.isoformat(), "days": total, "roommates": [person], "seed": 0,
            "warnings": [], "carried_over": bool(state), "candidates": candidates}


def state_after(schedule):
    """What the next solo plan needs: when each chore last happened."""
    last = {}
    for s in schedule["slots"]:
        last[s["group"]] = max(last.get(s["group"], s["date"]), s["date"])
    return {"group_phase": last}
