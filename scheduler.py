"""
scheduler.py - everything around the algorithms: config/state I/O, the
calendar, human-readable reporting, independent validation, and file export
(CSV/DOCX/PDF). Nothing in here decides WHO does WHAT - that's optimizer.py.
This module just loads inputs, reports outputs, and exports them.
"""
import copy
import csv
import datetime
import json
import os
import re
import sys
from collections import defaultdict
from xml.sax.saxutils import escape

import yaml

from optimizer import (
    is_person_excluded, evaluate, polish_schedule, count_structural_violations,
    check_structure, algo_milp, rest_balance_spread, per_person_rests,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _config_error(message):
    print(f"🚨 {message}")
    sys.exit(1)


def load_config(path="config.yml"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        _config_error(f"Config file not found: {path} (copy config_example.yml to get started)")

    # YAML turns an unquoted 2026-09-06 into a date object - accept both forms
    cfg["start_day"] = str(cfg["start_day"])

    # --- days off: same strictness as exclusions below - a typo'd name or
    # weekday ("Saturdy") would otherwise silently never match anything ---
    days_off = cfg.get("days_off") or {}
    for person in days_off:
        if person not in cfg["roommates"]:
            _config_error(f"days_off lists '{person}', who is not in roommates")
    for person in cfg["roommates"]:
        entries = []
        for entry in (days_off.get(person) or []):
            if isinstance(entry, datetime.date):
                entry = entry.isoformat()  # unquoted YAML date
            if entry not in WEEKDAYS:
                try:
                    datetime.datetime.strptime(entry, "%Y-%m-%d")
                except (TypeError, ValueError):
                    _config_error(f"days_off for '{person}' has '{entry}' - expected a weekday name "
                                  f"({', '.join(WEEKDAYS)}) or a date like 2026-01-31")
            entries.append(entry)
        days_off[person] = entries
    cfg["days_off"] = days_off

    by_name = {g["name"]: g for g in cfg["chore_groups"]}
    for g in cfg["chore_groups"]:
        if g.get("buffer_days") is None:
            g["buffer_days"] = cfg["buffer_days"]
        if g.get("tolerance_days") is None:
            g["tolerance_days"] = 0
        if "piggyback_on" in g:
            if g["piggyback_on"] not in by_name:
                _config_error(f"chore group '{g['name']}' piggybacks on unknown group '{g['piggyback_on']}'")
            if not g.get("every_nth") or g["every_nth"] < 1:
                _config_error(f"chore group '{g['name']}' needs every_nth >= 1 alongside piggyback_on")
            # approximate frequency for greedy/SA/feasibility-check, which don't
            # understand piggyback alignment - only the MILP enforces it exactly
            host = by_name[g["piggyback_on"]]
            g["frequency_days"] = host["frequency_days"] * g["every_nth"]
        elif not g.get("frequency_days"):
            _config_error(f"chore group '{g['name']}' needs either frequency_days or piggyback_on+every_nth")

    # --- per-person chore exclusions: "this person NEVER does this chore" ---
    # The config accepts either a chore GROUP name ("Stove") or a single TASK
    # name ("🍳 Stove"); both are normalized here into a set of task names per
    # person, so every algorithm and validator downstream only ever deals
    # with task names. Unknown names are a hard error, not a silent no-op -
    # a typo'd exclusion that quietly does nothing is the worst outcome.
    tasks_by_group = {g["name"]: list(g["tasks"]) for g in cfg["chore_groups"]}
    all_tasks = [t for tasks in tasks_by_group.values() for t in tasks]
    # every per-chore count and fairness variable is keyed by task name
    duplicates = sorted({t for t in all_tasks if all_tasks.count(t) > 1})
    if duplicates:
        _config_error(f"task name(s) used in more than one chore group: {', '.join(duplicates)}")
    exclusions = {p: set() for p in cfg["roommates"]}
    for person, entries in (cfg.get("exclusions") or {}).items():
        if person not in exclusions:
            _config_error(f"exclusions lists '{person}', who is not in roommates")
        for entry in (entries or []):
            if entry in tasks_by_group:
                exclusions[person].update(tasks_by_group[entry])
            elif entry in all_tasks:
                exclusions[person].add(entry)
            else:
                _config_error(f"exclusions for '{person}' names unknown chore '{entry}' - expected a chore "
                              f"group ({', '.join(tasks_by_group)}) or a task ({', '.join(all_tasks)})")
    cfg["exclusions"] = exclusions

    # Impossible or very tight exclusion configs get caught HERE, where the
    # message can say what to change. Otherwise MILP just reports a bare
    # "infeasible" and the heuristics quietly hand someone a chore they were
    # supposed to never do.
    for g in cfg["chore_groups"]:
        for task in g["tasks"]:
            eligible = [p for p in cfg["roommates"] if task not in exclusions[p]]
            if not eligible:
                _config_error(f"every roommate is excluded from '{task}' - nobody is left to do it")
            # whoever does this task then rests buffer_days, so with k eligible
            # people their turns come round every k*frequency_days - that has to
            # clear the buffer, i.e. k >= ceil((buffer_days + 1) / frequency_days)
            needed = -(-(g["buffer_days"] + 1) // g["frequency_days"])
            if len(eligible) < needed:
                print(f"⚠️  only {len(eligible)} roommate(s) can do '{task}' ({', '.join(eligible)}) - "
                      f"every {g['frequency_days']}d with a {g['buffer_days']}d rest buffer needs at least "
                      f"{needed}, so expect buffer violations on this chore")

    # --- seed for the roommate-order shuffle: an integer (reproducible) or
    # "auto" (fresh every run). Defaults to a fixed integer, so two runs of
    # the same config give the same schedule unless you ask for otherwise. ---
    seed = cfg.get("random_seed", 42)
    if seed is None:
        seed = 42
    if isinstance(seed, str) and seed.strip().lower() == "auto":
        cfg["random_seed"] = "auto"
    else:
        try:
            cfg["random_seed"] = int(seed)
        except (TypeError, ValueError):
            _config_error(f'random_seed must be an integer or "auto", got {seed!r}')
    return cfg




def build_calendar(start_date, total_days):
    calendar = [start_date + datetime.timedelta(days=d) for d in range(total_days)]
    weekday = [dt.strftime("%A") for dt in calendar]
    return calendar, weekday




def load_state(path="schedule_state.json"):
    """State from the previous run: last task date+chore per person (for rest
    carry-over), last occurrence date per chore group (for phase continuity),
    and cumulative task counts (for fairness across multiple runs)."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw["people"] = {
        p: {"last_task_date": datetime.datetime.strptime(v["last_task_date"], "%Y-%m-%d").date(),
            "last_group": v["last_group"]}
        for p, v in raw.get("people", {}).items()
    }
    raw["group_phase"] = {
        g: datetime.datetime.strptime(v, "%Y-%m-%d").date()
        for g, v in raw.get("group_phase", {}).items()
    }
    return raw




def check_state_freshness(state, start_day, path="schedule_state.json"):
    """Carry-over only means anything if the previous run ENDED before this
    one begins. A state file dated at or after start_day means the two
    windows overlap - normally a start_day that was never moved forward, or
    a state file belonging to an entirely different window.

    That used to sail straight through and quietly wreck the run: every
    person looked like they owed rest from the future, which the solver
    reported as a pile of "unavoidable" buffer exceptions (187 of them, on
    the run that prompted this), and every fairness number was computed
    against that nonsense. Now it says so plainly and runs without the bad
    carry-over rather than silently producing a distorted schedule."""
    if not state:
        return None
    dates = [info["last_task_date"] for info in state.get("people", {}).values()]
    dates += list(state.get("group_phase", {}).values())
    ahead = [d for d in dates if d >= start_day]
    if not ahead:
        return state
    newest = max(ahead)
    print("=" * 70)
    print(f" ⚠️  {path} IS AHEAD OF start_day - CARRY-OVER IGNORED")
    print("=" * 70)
    print(f" newest date in state : {newest.isoformat()}")
    print(f" start_day in config  : {start_day.isoformat()}"
          f"  ({(newest - start_day).days} days earlier)")
    print(" Rest owed, chore phase and cumulative fairness only carry over from")
    print(" a run that finished BEFORE this one starts. Running without them -")
    print(" otherwise everyone appears to owe rest from the future, which shows")
    print(" up as a pile of phantom buffer exceptions and skews every metric.")
    print(" Fix by moving start_day past the last schedule, or by deleting")
    print(f" {path} to start a fresh cycle.")
    print("=" * 70)
    return None


def save_state(winner_slots, people, chore_groups, path="schedule_state.json", random_seed=None):
    """Persist exactly what the NEXT run needs to continue seamlessly, no more."""
    state = {"people": {}, "group_phase": {}, "cumulative_totals": {}, "cumulative_per_task": {}}
    if random_seed is not None:
        # recorded, not read back: the only way to reproduce a run that used
        # random_seed: auto is to know which seed it landed on
        state["random_seed"] = random_seed

    by_person = {p: [] for p in people}
    for s in winner_slots:
        by_person[s["person"]].append(s)
    for p in people:
        slots = sorted(by_person[p], key=lambda s: s["day_idx"])
        if slots:
            last = slots[-1]
            state["people"][p] = {
                "last_task_date": last["date"].strftime("%Y-%m-%d"),
                "last_group": chore_groups[last["group_idx"]]["name"],
            }
        state["cumulative_totals"][p] = len(slots)

    for g in chore_groups:
        g_slots = [s for s in winner_slots if chore_groups[s["group_idx"]]["name"] == g["name"]]
        if g_slots:
            last_date = max(s["date"] for s in g_slots)
            state["group_phase"][g["name"]] = last_date.strftime("%Y-%m-%d")

    per_task = defaultdict(lambda: defaultdict(int))
    for s in winner_slots:
        per_task[s["task"]][s["person"]] += 1
    state["cumulative_per_task"] = {t: dict(counts) for t, counts in per_task.items()}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return path


def diagnose_milp_infeasibility(roommates, chore_groups, days_off, calendar, weekday, state,
                                 exclusions=None):
    """Runs automatically when MILP goes infeasible on a continuation run.
    Isolates whether rest carry-over, phase carry-over, or fairness
    carry-over (or some combination) is actually responsible, by re-solving
    with each turned off one at a time. This is the exact manual process
    used to debug this class of issue before - now it happens automatically,
    in your own terminal, without needing to hand over schedule_state.json."""
    print("=" * 70)
    print(" DIAGNOSING MILP INFEASIBILITY (continuation run)")
    print(" Testing which carry-over component is responsible...")
    print("=" * 70)

    all_three = "ALL THREE carry-overs (what actually ran)"
    tests = [("no carry-over at all (state=None)", None)]
    if state.get("people"):
        s = copy.deepcopy(state)
        s["group_phase"], s["cumulative_totals"], s["cumulative_per_task"] = {}, {}, {}
        tests.append(("rest carry-over ONLY", s))
    if state.get("group_phase"):
        s = copy.deepcopy(state)
        s["people"], s["cumulative_totals"], s["cumulative_per_task"] = {}, {}, {}
        tests.append(("phase (chore cadence) carry-over ONLY", s))
    if state.get("cumulative_totals") or state.get("cumulative_per_task"):
        s = copy.deepcopy(state)
        s["people"], s["group_phase"] = {}, {}
        tests.append(("fairness carry-over ONLY", s))
    tests.append((all_three, state))

    results = []
    for name, test_state in tests:
        slots, _, _, _ = algo_milp(roommates, chore_groups, days_off, calendar, weekday,
                                   state=test_state, exclusions=exclusions)
        status = "✅ FEASIBLE" if slots else "❌ INFEASIBLE"
        results.append((name, status))
        print(f"  {status}  <-  {name}")

    print("=" * 70)
    culprits = [name for name, status in results if "INFEASIBLE" in status and name != all_three]
    if culprits:
        print(f" LIKELY CAUSE: {', '.join(culprits)}")
        print(" This carry-over, combined with your current days-off/frequencies,")
        print(" creates a genuinely unsatisfiable hard constraint. Consider:")
        print("   - loosening that specific carry-over (e.g. skip it just this once)")
        print("   - adjusting the config that's in conflict (buffer_days, frequency,")
        print("     days_off, exclusions)")
    else:
        print(" No single component alone is infeasible - it's the COMBINATION.")
        print(" This is rarer and harder to loosen selectively; the safest fix is")
        print(" accepting the best-effort heuristic winner for this one run.")
    print("=" * 70)
    return results


def polish_and_report(name, slots, roommates, chore_groups, days_off, calendar, weekday, buffer_days_target,
                       state=None, exclusions=None):
    """Apply the rest-polish layer to one algorithm's output and print a
    compact before -> after summary. Also re-checks structural correctness
    before/after as a safety net - polish_schedule already guards against
    increasing structural violations internally, but it's cheap to verify
    rather than assume.

    state: the previous run's carried-over data (rest/phase/fairness), if
    any - passed through so the structural checks here match what
    algo_milp itself is judged against, instead of a carry-over-blind
    baseline that would let a real violation slip past unnoticed."""
    if slots is None:
        return None
    before = evaluate(roommates, chore_groups, slots, exclusions)
    before_structural = count_structural_violations(slots, chore_groups, days_off, calendar, weekday, state=state,
                                                     exclusions=exclusions)

    polished, moves = polish_schedule(roommates, chore_groups, days_off, slots, buffer_days_target, calendar, weekday,
                                       carry_over_state=state, exclusions=exclusions)

    after = evaluate(roommates, chore_groups, polished, exclusions)
    after_structural = count_structural_violations(polished, chore_groups, days_off, calendar, weekday, state=state,
                                                    exclusions=exclusions)

    print(f"   Polish: {moves} move(s) -> "
          f"avg rest {before['avg_rest']:.2f}->{after['avg_rest']:.2f}, "
          f"min rest {before['min_rest']}->{after['min_rest']}, "
          f"violations {before['buffer_violations']}->{after['buffer_violations']}")
    if after_structural > before_structural:
        print(f"   🚨 unexpected: structural violations INCREASED during polish "
              f"({before_structural}->{after_structural}) - this should never happen, keeping original")
        return slots
    return polished




def print_metrics(name, active_slots, people, chore_groups, elapsed, note, exclusions=None):
    if active_slots is None:
        print(f"\n### {name}: 🚨 INFEASIBLE ({note})")
        return
    m = evaluate(people, chore_groups, active_slots, exclusions)
    print(f"\n### {name}  [{note}]  ({elapsed*1000:.1f} ms)")
    print(f"   Workload spread (max-min tasks) : {m['fairness_spread']}")
    print(f"   Workload : " + ", ".join(f"{p}={c}" for p, c in m['workload'].items()))
    print(f"   Avg / Min / Max rest gap        : {m['avg_rest']:.2f} / {m['min_rest']} / {m['max_rest']}")
    print(f"   Buffer rule violations          : {m['buffer_violations']}")
    print(f"   Per-chore spread (eligible only): {m['total_per_task_spread']}  "
          + ", ".join(f"{t}:{s}" for t, s in m["per_task_spread"].items()))

    per_person_avgs = {p: (sum(rs) / len(rs) if rs else None)
                       for p, rs in per_person_rests(people, active_slots).items()}
    spread = rest_balance_spread(people, active_slots)
    print(f"   Rest balance across people      : spread {spread:.2f}  ("
          + ", ".join(f"{p}={v:.2f}" if v is not None else f"{p}=n/a" for p, v in per_person_avgs.items()) + ")")




def print_task_breakdown(active_slots, chore_groups, people, exclusions=None):
    """Per-chore-type breakdown: who does THIS specific chore, and how often.

    Lists every ELIGIBLE person, including any who ended up with zero - a
    zero among people who could have done the chore is exactly the kind of
    unevenness worth seeing, and it used to be invisible here because the
    counts only covered people who actually got the task. Excluded people
    are named separately: their zero is the rule working, so it neither
    shows up as a count nor counts toward the unevenness flag."""
    by_task = defaultdict(lambda: defaultdict(int))
    for s in active_slots:
        by_task[s["task"]][s["person"]] += 1

    # keep chore_groups' declared order/task order for readability
    ordered_tasks = [t for g in chore_groups for t in g["tasks"]]

    print("-" * 70)
    print(" TASK BREAKDOWN BY PERSON")
    print("-" * 70)
    for task in ordered_tasks:
        done = by_task.get(task, {})
        if not done:
            continue
        excluded = [p for p in people if is_person_excluded(p, task, exclusions)]
        counts = {p: done.get(p, 0) for p in people
                  if not is_person_excluded(p, task, exclusions)}
        for p, c in done.items():
            if p not in counts:
                counts[p] = c  # excluded but assigned anyway - show it, don't hide it
        parts = ", ".join(f"{p}({c})" for p, c in sorted(counts.items(), key=lambda kv: -kv[1]))
        spread = max(counts.values()) - min(counts.values()) if len(counts) > 1 else 0
        flag = "  ⚠️ uneven" if spread >= 2 else ""
        excl_note = f"   [excluded: {', '.join(excluded)}]" if excluded else ""
        print(f"  {task:18s} : {parts}{flag}{excl_note}")
    print()




def print_person_summary(active_slots, people):
    """Per-person: total task count, and the full sequence of rest gaps."""
    totals = {p: 0 for p in people}
    for s in active_slots:
        totals[s["person"]] += 1

    print("-" * 70)
    print(" TOTAL TASKS BY PERSON")
    print("-" * 70)
    for p in people:
        print(f"  {p:10s} : {totals[p]} tasks")
    print()

    print("-" * 70)
    print(" REST PERIODS BY PERSON (days between consecutive tasks)")
    print("-" * 70)
    for p, rests in per_person_rests(people, active_slots).items():
        if rests:
            avg_r = sum(rests) / len(rests)
            print(f"  {p:10s} : {rests}   (avg {avg_r:.1f}, min {min(rests)}, max {max(rests)})")
        else:
            print(f"  {p:10s} : no rest data (0-1 tasks total)")
    print()




def validate_schedule(active_slots, chore_groups, days_off, calendar, weekday, state=None, exclusions=None):
    """Independent audit: re-derive every rule from config and check the
    ACTUAL schedule against it. This does not trust the solver/heuristic -
    it re-checks from scratch, the same way a human would verify by hand.

    The checks themselves live in optimizer.check_structure (shared with
    the ranking that picks a winner, so the two can't disagree); this
    prints them. state (optional) makes them carry-over aware - see there."""
    total_days = len(calendar)
    report = check_structure(active_slots, chore_groups, days_off, calendar, weekday,
                             state=state, exclusions=exclusions)

    print("=" * 70)
    print(" SCHEDULE VALIDATION")
    print("=" * 70)
    all_ok = True

    # --- 1) frequency: every non-piggyback group fires EXACTLY once per its
    # own window, and 1b) its cadence (incl. the boundary with the previous
    # run) stays close to frequency_days ---
    for f in report["frequency"]:
        g, pb, windows = f["group"], f["phase_block"], f["windows"]
        bad_windows, deferred_window, bad_gaps = f["bad_windows"], f["deferred_window"], f["bad_gaps"]
        if bad_windows or bad_gaps:
            all_ok = False
        status = "OK" if not bad_windows else "FAIL"
        phase_note = f" [carried-over phase: due after {calendar[min(pb, total_days-1)].isoformat()}]" if pb > 0 else ""
        defer_note = (f" (trailing window {calendar[deferred_window[0]].isoformat()}"
                       f"-{calendar[deferred_window[-1]].isoformat()} deferred to next run)"
                       if deferred_window else "")
        print(f"  [{status}] {g['name']} (every {g['frequency_days']}d){phase_note}: "
              f"{len(windows)} windows, {len(f['occurrences'])} occurrences{defer_note}"
              + (f" - bad windows: {[[calendar[d].isoformat() for d in w] for w in bad_windows]}" if bad_windows else ""))

        tol = g.get("tolerance_days", 0)
        cadence_status = "OK" if not bad_gaps else "FAIL"
        tol_note = f" (tolerance +-{tol}d)" if tol else ""
        print(f"  [{cadence_status}] {g['name']} cadence (expect ~{g['frequency_days']}d apart{tol_note}): "
              + (f"irregular gaps: {bad_gaps}" if bad_gaps else "consistent"))

    # --- 2) piggyback: every piggyback occurrence lands on an occurrence
    # day of its host (exactly, or within tolerance_days) ---
    for pg in report["piggyback"]:
        g = pg["group"]
        status = "OK" if pg["violations"] == 0 else "FAIL"
        if status == "FAIL":
            all_ok = False
        tol = g.get("tolerance_days", 0)
        exp_dates = [calendar[d].isoformat() for d in pg["expected"]]
        act_dates = [calendar[d].isoformat() for d in pg["actual"]]
        tol_note = f" (tolerance +-{tol}d)" if tol else ""
        print(f"  [{status}] {g['name']} piggybacks on {g['piggyback_on']} every {g['every_nth']}{tol_note}: "
              f"expected {exp_dates}, got {act_dates}")

    # --- 3) days-off conflicts ---
    conflicts = report["days_off"]
    status = "OK" if not conflicts else "FAIL"
    if conflicts:
        all_ok = False
    print(f"  [{status}] Days-off conflicts: {len(conflicts)}"
          + (f" - {[(c['person'], c['date'].isoformat(), c['task']) for c in conflicts]}" if conflicts else ""))

    # --- 4) exclusion conflicts: nobody was handed a chore they're
    # configured to never do. Unlike days-off this can't be "worked around by
    # picking another day" - if it shows up here, the schedule is wrong. ---
    excluded_hits = report["excluded"]
    status = "OK" if not excluded_hits else "FAIL"
    if excluded_hits:
        all_ok = False
    configured = {p: sorted(ts) for p, ts in (exclusions or {}).items() if ts}
    rule_note = (" (" + "; ".join(f"{p} never: {', '.join(ts)}" for p, ts in configured.items()) + ")"
                 if configured else " (none configured)")
    print(f"  [{status}] Exclusion conflicts: {len(excluded_hits)}{rule_note}"
          + (f" - {[(c['person'], c['date'].isoformat(), c['task']) for c in excluded_hits]}" if excluded_hits else ""))

    print("=" * 70)
    print(f" VALIDATION {'PASSED' if all_ok else 'FAILED'}")
    print("=" * 70)
    return all_ok




def print_schedule(name, active_slots, chore_groups):
    """Full week-by-week timeline for one algorithm's result."""
    weekly = {}
    for r in schedule_rows_for_export(active_slots):
        date = datetime.date.fromisoformat(r["date"])
        monday = date - datetime.timedelta(days=date.weekday())
        week_str = f"Week of {monday.strftime('%b %d, %Y')}"
        weekly.setdefault(week_str, {d: [] for d in WEEKDAYS})
        rest_str = "[First]" if r["rest"] == "First" else f"[Rest: {r['rest']}]"
        weekly[week_str][r["day"]].append(f"{r['task']}: {r['person']} {rest_str}")

    print("\n" + "#" * 70)
    print(f"# FULL SCHEDULE - {name}")
    print("#" * 70)
    for week, days in weekly.items():
        print("=" * 100)
        print(f" 🗓️  {week.upper()} ")
        print("=" * 100)
        for day in WEEKDAYS:
            if days[day]:
                print(f"{day:<12} | {'  |  '.join(days[day])}")
    print()




def schedule_rows_for_export(active_slots):
    """Flat, sorted list of rows shared by the console timeline and all three export formats."""
    last_task = {}
    rows = []
    for slot in sorted(active_slots, key=lambda s: s["day_idx"]):
        p = slot["person"]
        rest = (slot["day_idx"] - last_task[p] - 1) if p in last_task else None
        rows.append({
            "date": slot["date"].strftime("%Y-%m-%d"),
            "day": slot["day"],
            "task": slot["task"],
            "person": p,
            "rest": "First" if rest is None else str(rest),
        })
        last_task[p] = slot["day_idx"]
    return rows




def export_csv(active_slots, path="chore_schedule.csv"):
    rows = schedule_rows_for_export(active_slots)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig so Excel shows emoji/accents correctly
        writer = csv.DictWriter(f, fieldnames=["date", "day", "task", "person", "rest"])
        writer.writerow({"date": "Date", "day": "Day", "task": "Task", "person": "Assigned To", "rest": "Rest Taken"})
        writer.writerows(rows)
    return path




def _strip_emoji(text):
    # ReportLab's built-in fonts can't render emoji glyphs (blank boxes) -
    # the descriptive word after it (e.g. "Dishes") already carries the meaning.
    return re.sub(r"[^\x00-\x7F]+", "", text).strip()


def _document_content(active_slots, chore_groups, people):
    """Everything the DOCX and PDF exports show, computed once. The two
    renderers only differ in HOW they draw it, so they can't drift apart in
    WHAT they show (this used to be ~100 lines copy-pasted into each)."""
    # a fixed color per chore type, used consistently across every page -
    # scan the calendar by color instead of reading every word
    palette = ["4472C4", "C0504D", "9BBB59", "8064A2", "4BACC6", "F79646"]
    ordered_tasks = [t for g in chore_groups for t in g["tasks"]]
    task_color = {_strip_emoji(t): palette[i % len(palette)] for i, t in enumerate(ordered_tasks)}

    rows = schedule_rows_for_export(active_slots)

    # group rows by week, then by day-of-week
    weekly, week_mondays = {}, {}
    for r in rows:
        d = datetime.date.fromisoformat(r["date"])
        monday = d - datetime.timedelta(days=d.weekday())
        week_key = monday.strftime("%b %d, %Y")
        weekly.setdefault(week_key, {day: [] for day in WEEKDAYS})
        week_mondays[week_key] = monday
        weekly[week_key][r["day"]].append(r)

    # --- intro block: schedule period, roommates, chores + frequency, totals ---
    all_dates = sorted(datetime.date.fromisoformat(r["date"]) for r in rows)
    start_date_str = all_dates[0].strftime("%b %d, %Y") if all_dates else "-"
    end_date_str = all_dates[-1].strftime("%b %d, %Y") if all_dates else "-"
    n_weeks = ((all_dates[-1] - all_dates[0]).days // 7 + 1) if all_dates else 0

    def chore_freq_label(g):
        tol = g.get("tolerance_days", 0)
        tol_note = f" (+-{tol}d)" if tol else ""
        if "piggyback_on" in g:
            return f"{_strip_emoji(g['tasks'][0])} - piggybacks on {g['piggyback_on']} every {g['every_nth']}{tol_note}"
        return f"{_strip_emoji(g['tasks'][0])} - every {g['frequency_days']} day(s){tol_note}"

    buffer_values = {g.get("buffer_days", 0) for g in chore_groups}
    buffer_label = f"{buffer_values.pop()} days" if len(buffer_values) == 1 else "varies by chore (see config)"

    intro = [
        ("Schedule period", f"{start_date_str}  -  {end_date_str}  ({n_weeks} week{'s' if n_weeks != 1 else ''})"),
        (f"Roommates ({len(people)})", ", ".join(people)),
        ("Chores and frequency", "\n".join(chore_freq_label(g) for g in chore_groups)),
        ("Total tasks scheduled", str(len(rows))),
        ("Rest buffer target", buffer_label),
    ]

    task_counts = {p: 0 for p in people}
    for r in rows:
        task_counts[r["person"]] += 1

    # task breakdown by person - same data as the console report, but clean:
    # no "uneven" warning annotations in the documents
    by_task = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_task[_strip_emoji(r["task"])][r["person"]] += 1
    breakdown = []
    for task in ordered_tasks:
        task_clean = _strip_emoji(task)
        counts = by_task.get(task_clean, {})
        if counts:
            breakdown.append([task_clean, ", ".join(f"{p}({c})" for p, c in
                                                    sorted(counts.items(), key=lambda kv: -kv[1]))])

    # rest periods by person - same data as the console report, clean (no flags)
    rest_rows = []
    for p, rests in per_person_rests(people, active_slots).items():
        if rests:
            rest_rows.append([p, ", ".join(str(r) for r in rests),
                              f"{sum(rests) / len(rests):.1f}", str(min(rests)), str(max(rests))])
        else:
            rest_rows.append([p, "no rest data (0-1 tasks total)", "-", "-", "-"])

    return {"task_color": task_color, "weekly": weekly, "week_mondays": week_mondays, "intro": intro,
            "task_counts": task_counts, "breakdown": breakdown, "rest_rows": rest_rows}


def _set_cell_background(cell, hex_color):
    """python-docx has no high-level API for cell shading - this is the
    standard low-level workaround via the cell's XML properties."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color.lstrip("#"))
    tcPr.append(shd)


def export_docx(active_slots, chore_groups, people, path="chore_schedule.docx"):
    """Same content as export_pdf (both draw _document_content) - intro
    block, summary tables, color-coded weekly person-timeline - rendered
    with python-docx instead of reportlab."""
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    content = _document_content(active_slots, chore_groups, people)
    task_color = content["task_color"]

    doc = Document()
    doc.add_heading("Chore Schedule", level=1)

    # --- intro block ---
    intro_table = doc.add_table(rows=len(content["intro"]), cols=2)
    intro_table.style = "Table Grid"
    intro_table.columns[0].width = Inches(1.8)
    intro_table.columns[1].width = Inches(5.2)
    for i, (label, value) in enumerate(content["intro"]):
        cells = intro_table.rows[i].cells
        cells[0].text = label
        cells[0].paragraphs[0].runs[0].bold = True
        _set_cell_background(cells[0], "F2F2F2")
        cells[1].paragraphs[0].text = ""
        for line_idx, line in enumerate(value.split("\n")):
            p = cells[1].paragraphs[0] if line_idx == 0 else cells[1].add_paragraph()
            p.add_run(line)
    doc.add_paragraph()

    def add_section_table(heading, header_row, data_rows, col_widths=None):
        doc.add_heading(heading, level=3)
        table = doc.add_table(rows=1, cols=len(header_row))
        table.style = "Table Grid"
        for i, label in enumerate(header_row):
            cell = table.rows[0].cells[i]
            cell.text = label
            cell.paragraphs[0].runs[0].bold = True
            cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            _set_cell_background(cell, "333333")
        for r_idx, row_data in enumerate(data_rows):
            cells = table.add_row().cells
            for i, val in enumerate(row_data):
                cells[i].text = str(val)
            if r_idx % 2 == 1:
                for cell in cells:
                    _set_cell_background(cell, "F2F2F2")
        if col_widths:
            for i, w in enumerate(col_widths):
                for row in table.rows:
                    row.cells[i].width = Inches(w)
        doc.add_paragraph()
        return table

    add_section_table("Total tasks by person", ["Person", "Total Tasks"],
                       [[p, c] for p, c in content["task_counts"].items()], [2.0, 1.2])
    add_section_table("Task breakdown by person", ["Chore", "Breakdown"], content["breakdown"], [1.3, 5.5])
    add_section_table("Rest periods by person", ["Person", "Rest gaps (days between tasks)", "Avg", "Min", "Max"],
                       content["rest_rows"], [0.9, 4.0, 0.5, 0.5, 0.5])

    # --- chore color key ---
    doc.add_heading("Chore color key", level=3)
    legend_table = doc.add_table(rows=1, cols=len(task_color))
    for i, (task, hexcolor) in enumerate(task_color.items()):
        cell = legend_table.rows[0].cells[i]
        cell.text = task
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        cell.paragraphs[0].runs[0].bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _set_cell_background(cell, hexcolor)
    doc.add_page_break()

    # --- weekly person-timeline tables (color-coded, day name + date headers) ---
    for week_key, days in content["weekly"].items():
        doc.add_heading(f"Week of {week_key}", level=2)
        monday_date = content["week_mondays"][week_key]
        timeline = doc.add_table(rows=1 + len(people), cols=1 + len(WEEKDAYS))
        timeline.style = "Table Grid"
        timeline.autofit = False
        timeline.columns[0].width = Inches(0.7)
        for c in range(1, 8):
            timeline.columns[c].width = Inches(0.93)

        hdr_cells = timeline.rows[0].cells
        hdr_cells[0].text = ""
        _set_cell_background(hdr_cells[0], "333333")
        for idx, day in enumerate(WEEKDAYS):
            cell = hdr_cells[idx + 1]
            date_str = (monday_date + datetime.timedelta(days=idx)).strftime("%b %d")
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            r1 = cell.paragraphs[0].add_run(day[:3])
            r1.bold = True
            r1.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            cell.add_paragraph().alignment = WD_ALIGN_PARAGRAPH.CENTER
            r2 = cell.paragraphs[1].add_run(date_str)
            r2.font.size = Pt(7)
            r2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            _set_cell_background(cell, "333333")

        for p_idx, person in enumerate(people):
            row_cells = timeline.rows[p_idx + 1].cells
            row_cells[0].text = person
            row_cells[0].paragraphs[0].runs[0].bold = True
            _set_cell_background(row_cells[0], "F2F2F2")
            for d_idx, day in enumerate(WEEKDAYS):
                cell = row_cells[d_idx + 1]
                match = next((r for r in days[day] if r["person"] == person), None)
                cell.text = ""
                if match:
                    task_clean = _strip_emoji(match["task"])
                    hexcolor = task_color.get(task_clean, "000000")
                    para = cell.paragraphs[0]
                    r1 = para.add_run(task_clean)
                    r1.bold = True
                    r1.font.size = Pt(8)
                    r1.font.color.rgb = RGBColor.from_string(hexcolor)
                    if match["rest"] != "First":
                        r2 = para.add_run(f" r{match['rest']}")
                        r2.font.size = Pt(7)
                        r2.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        doc.add_paragraph()

    doc.save(path)
    return path




def export_pdf(active_slots, chore_groups, people, path="chore_schedule.pdf"):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                     Spacer, PageBreak, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    # Paragraph text is ReportLab markup, so names are escaped - a chore
    # called "Sweep & Trash" would otherwise break the whole export.
    # (Plain-string Table cells are drawn literally and need no escaping.)
    content = _document_content(active_slots, chore_groups, people)
    task_color = content["task_color"]

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    day_header_style = ParagraphStyle("dayhdr", parent=styles["Normal"], fontSize=9,
                                       textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(path, pagesize=letter,
                             leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                             topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    elements = [Paragraph("Chore Schedule", styles["Title"]), Spacer(1, 10)]

    # --- intro block ---
    intro_rows_formatted = [
        [Paragraph(f"<b>{escape(label)}</b>", cell_style),
         Paragraph(escape(value).replace("\n", "<br/>"), cell_style)]
        for label, value in content["intro"]
    ]
    intro_table = Table(intro_rows_formatted, colWidths=[1.6 * inch, 5.2 * inch])
    intro_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F2F2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements += [intro_table, Spacer(1, 16)]

    def summary_table(header_row, data_rows, col_widths, font_size):
        table = Table([header_row] + data_rows, colWidths=[w * inch for w in col_widths])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return table

    elements += [Paragraph("Total tasks by person", styles["Heading3"]),
                 summary_table(["Person", "Total Tasks"],
                               [[p, str(c)] for p, c in content["task_counts"].items()], [2, 1.2], 9),
                 Spacer(1, 16)]
    elements += [Paragraph("Task breakdown by person", styles["Heading3"]),
                 summary_table(["Chore", "Breakdown"], content["breakdown"], [1.3, 5.5], 9),
                 Spacer(1, 16)]
    elements += [Paragraph("Rest periods by person", styles["Heading3"]),
                 summary_table(["Person", "Rest gaps (days between tasks)", "Avg", "Min", "Max"],
                               content["rest_rows"], [0.9, 4.4, 0.5, 0.5, 0.5], 8),
                 Spacer(1, 16)]

    legend_cells = []
    legend_style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for col, (task, hexcolor) in enumerate(task_color.items()):
        legend_cells.append(Paragraph(f'<font color="white"><b>{escape(task)}</b></font>', cell_style))
        legend_style.append(("BACKGROUND", (col, 0), (col, 0), colors.HexColor("#" + hexcolor)))
    legend_table = Table([legend_cells])
    legend_table.setStyle(TableStyle(legend_style))
    elements += [Paragraph("Chore color key", styles["Heading3"]), legend_table, PageBreak()]

    # --- PERSON TIMELINES: keep each week intact, but let ReportLab pack
    # multiple weeks on a page rather than wasting a page per week. ---
    # answers "when am I on duty" at a glance, and shows task-pairing patterns
    # (e.g. Mop riding on a Sweep day) as a visible row pattern, not buried text
    name_col_width = 0.9 * inch
    day_col_width = (7.3 * inch - name_col_width) / 7

    for week_key, days in content["weekly"].items():
        week_elements = [Paragraph(f"Week of {week_key}", styles["Heading2"]), Spacer(1, 6)]

        monday_date = content["week_mondays"][week_key]
        header_row = [Paragraph("", day_header_style)] + [
            Paragraph(f"{day[:3]}<br/><font size=\"7\">{(monday_date + datetime.timedelta(days=idx)).strftime('%b %d')}</font>",
                      day_header_style)
            for idx, day in enumerate(WEEKDAYS)
        ]
        table_data = [header_row]

        for person in people:
            row = [Paragraph(f"<b>{escape(person)}</b>", cell_style)]
            for day in WEEKDAYS:
                match = next((r for r in days[day] if r["person"] == person), None)
                if match:
                    task_clean = _strip_emoji(match["task"])
                    hexcolor = "#" + task_color.get(task_clean, "000000")
                    rest_str = "" if match["rest"] == "First" else f'<font size="7" color="#888888"> r{match["rest"]}</font>'
                    row.append(Paragraph(f'<font color="{hexcolor}"><b>{escape(task_clean)}</b></font>{rest_str}', cell_style))
                else:
                    row.append(Paragraph("", cell_style))
            table_data.append(row)

        timeline_table = Table(table_data, colWidths=[name_col_width] + [day_col_width] * 7,
                                rowHeights=[26] + [26] * len(people))
        timeline_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F2F2F2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (1, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ]))
        week_elements += [timeline_table, Spacer(1, 16)]
        elements.append(KeepTogether(week_elements))

    doc.build(elements)
    return path
