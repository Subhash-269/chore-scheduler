"""
optimizer.py - the scheduling algorithms themselves.

Six algorithms, same hard rules, same inputs/outputs, so they're directly
comparable:

  Hard rules (ALWAYS enforced, regardless of algorithm):
    - each chore group fires exactly once per frequency window
      (or ties to its host's window, for piggyback groups)
    - a person never works more than one task on the same day
      (different people CAN share a day freely)
    - a person is never assigned on their day(s) off
  Soft rules (minimized, never silently ignored):
    - the rest-buffer between any two of a person's tasks
    - cadence (consecutive occurrences of the same chore stay close
      to its own frequency_days, not just "one per window")

  Algorithm 1 - MILP (HiGHS)              : exact, provable optimum
  Algorithm 2 - Greedy heuristic          : fast, single pass, no lookahead
  Algorithm 3 - Simulated Annealing       : metaheuristic, temperature-based
  Algorithm 4 - Tabu Search               : metaheuristic, memory-based
  Algorithm 5 - Genetic Algorithm         : metaheuristic, population-based
  Algorithm 6 - Daily Hungarian Assignment: exact per-day bipartite matching

Plus a fairness-safe rest-polish pass (polish_schedule) that can be applied
to any of the above afterward.
"""
import sys
import datetime
import random
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix, vstack


def is_person_off(person, date_obj, weekday_name, days_off):
    off_entries = days_off.get(person, [])
    return weekday_name in off_entries or date_obj.strftime("%Y-%m-%d") in off_entries




def build_windows(frequency_days, total_days):
    windows, d = [], 0
    while d < total_days:
        end = min(d + frequency_days, total_days)
        windows.append(list(range(d, end)))
        d = end
    return windows




def resolve_group_windows(g, chore_groups_by_name, total_days, phase_block=0, host_phase_block=0):
    """Returns (windows, host_name, host_windows_for_linking). For a normal
    group, windows come from frequency_days as usual. For a piggyback group
    ('piggyback_on' + 'every_nth'), windows are the every-Nth window of the
    host group.

    tolerance_days (on the piggyback group) relaxes "must be the EXACT SAME
    day as the host" into "must be within tolerance_days of whatever day the
    host actually picks for that occurrence". With tolerance_days=0 (default)
    this is unchanged: Mop can only happen on the exact day chosen for host's
    every-Nth occurrence. host_windows_for_linking carries the ORIGINAL
    (un-widened) host windows aligned 1:1 with the returned windows list, so
    the caller can build the "stay near whichever day host picked" linking
    constraint - only needed when tolerance_days > 0.

    This tolerance is applied in the CORE solve (not just a post-hoc polish
    repair) - joint optimization with the real flexibility available beats
    solving strict then patching afterward. A dedicated day-shift move in
    polish_schedule can still nudge things further on top of this.

    phase_block: days at the START of this run during which THIS chore is NOT yet
    due (carried over from a previous run) - the first window is shortened to
    cover only the remaining days of its cycle, continuing the cadence instead
    of resetting it. Days inside phase_block get NO window at all (zero occurrences).

    host_phase_block: for a piggyback group, the HOST's own phase_block - must use
    the host's ACTUAL (phase-adjusted) windows, or the two misalign and the equality
    constraint becomes unsatisfiable (a real bug this fixes)."""
    if "piggyback_on" in g:
        host = chore_groups_by_name[g["piggyback_on"]]
        host_windows, _, _ = resolve_group_windows(host, chore_groups_by_name, total_days, phase_block=host_phase_block)
        every_nth = g["every_nth"]
        selected = [w for i, w in enumerate(host_windows) if (i + 1) % every_nth == 0]
        tol = g.get("tolerance_days", 0)
        if tol > 0:
            widened = []
            for w in selected:
                lo = max(0, min(w) - tol)
                hi = min(total_days - 1, max(w) + tol)
                widened.append(list(range(lo, hi + 1)))
            return widened, g["piggyback_on"], selected
        return selected, g["piggyback_on"], None
    if phase_block > 0 and phase_block < total_days:
        first = list(range(phase_block, min(phase_block + (g["frequency_days"] - phase_block), total_days)))
        rest = build_windows(g["frequency_days"], total_days - len(first) - phase_block)
        rest = [[d + phase_block + len(first) for d in w] for w in rest]
        return ([first] if first else []) + rest, None, None
    return build_windows(g["frequency_days"], total_days), None, None




def buffer_threshold(chore_groups, g1, g2, gap):
    """Directional per-group buffer: rest owed is charged to whichever
    task happened FIRST. Same-day ties use the stricter of the two."""
    if gap == 0:
        return max(chore_groups[g1]["buffer_days"], chore_groups[g2]["buffer_days"])
    return chore_groups[g1]["buffer_days"]




def evaluate(people, chore_groups, active_slots):
    """Common scoring so all 3 algorithms are judged the same way."""
    last_task = {p: None for p in people}
    last_group = {p: None for p in people}
    task_counts = {p: 0 for p in people}
    per_task_counts = {}  # task_name -> {person: count}
    rests = []
    violations = 0

    for slot in sorted(active_slots, key=lambda s: s["day_idx"]):
        p = slot["person"]
        d = slot["day_idx"]
        task = slot["task"]
        if last_task[p] is not None:
            gap = d - last_task[p]
            rest = gap - 1
            rests.append(rest)
            need = buffer_threshold(chore_groups, last_group[p], slot["group_idx"], gap)
            if gap <= need:
                violations += 1
        last_task[p] = d
        last_group[p] = slot["group_idx"]
        task_counts[p] += 1
        per_task_counts.setdefault(task, {pp: 0 for pp in people})
        per_task_counts[task][p] += 1

    loads = list(task_counts.values())
    # per-chore fairness: spread within EACH task type, only counting people
    # who are actually eligible to do it isn't tracked here - just raw spread
    per_task_spread = {
        task: max(counts.values()) - min(counts.values())
        for task, counts in per_task_counts.items()
    }
    total_per_task_spread = sum(per_task_spread.values())

    return {
        "workload": task_counts,
        "per_task_counts": per_task_counts,
        "per_task_spread": per_task_spread,
        "total_per_task_spread": total_per_task_spread,
        "fairness_spread": max(loads) - min(loads),
        "avg_rest": sum(rests) / len(rests) if rests else 0,
        "min_rest": min(rests) if rests else 0,
        "max_rest": max(rests) if rests else 0,
        "buffer_violations": violations,
        "total_tasks": sum(loads),
    }




def algo_milp(people, chore_groups, days_off, calendar, weekday, state=None):
    total_days = len(calendar)
    n_people = len(people)
    chore_groups_by_name = {g["name"]: g for g in chore_groups}
    start_day = calendar[0]

    # --- carry-over from previous run ---
    # (a) rest owed: block a person's early days if their last task (from the
    #     previous run) hasn't finished its buffer yet
    person_blocked_days = {p: 0 for p in people}
    if state and "people" in state:
        for p, info in state["people"].items():
            if p not in people:
                continue
            last_group = chore_groups_by_name.get(info["last_group"])
            buf = last_group["buffer_days"] if last_group else 0
            days_elapsed_before_run = (start_day - info["last_task_date"]).days - 1
            owed = buf - days_elapsed_before_run
            if owed > 0:
                person_blocked_days[p] = owed

    # (b) chore phase: shrink each group's FIRST window so its cadence
    #     continues from where the previous run left off, instead of resetting
    group_phase_block = {g["name"]: 0 for g in chore_groups}
    if state and "group_phase" in state:
        for g in chore_groups:
            if "piggyback_on" in g:
                continue  # piggyback groups don't have their own independent phase
            last_date = state["group_phase"].get(g["name"])
            if last_date is None:
                continue
            days_since = (start_day - last_date).days
            remaining = g["frequency_days"] - days_since
            if remaining > 0:
                group_phase_block[g["name"]] = remaining

    # (c) cumulative fairness carry-over from previous runs
    carried_total = {p: 0 for p in people}
    carried_per_task = {}
    if state:
        carried_total = {p: state.get("cumulative_totals", {}).get(p, 0) for p in people}
        carried_per_task = state.get("cumulative_per_task", {})

    slots = []
    for g_idx, g in enumerate(chore_groups):
        for d in range(total_days):
            for task in g["tasks"]:
                slots.append({"date": calendar[d], "day": weekday[d], "task": task,
                              "day_idx": d, "group_idx": g_idx})
    n_slots = len(slots)

    def xi(s, p): return s * n_people + p
    n_x = n_slots * n_people
    n_y = len(chore_groups) * total_days
    def yi(g, d): return n_x + g * total_days + d

    unique_tasks = [t for g in chore_groups for t in g["tasks"]]
    n_tasks = len(unique_tasks)
    TASK_BASE = n_x + n_y + 2
    def task_lmax(t_idx): return TASK_BASE + 2 * t_idx
    def task_lmin(t_idx): return TASK_BASE + 2 * t_idx + 1
    IDX_LMAX, IDX_LMIN = n_x + n_y, n_x + n_y + 1

    # --- buffer encoding: sliding-window (efficient) for uniform buffer,
    # pairwise (general but slower) fallback if per-group buffers differ ---
    uniform_buffer = len(set(g["buffer_days"] for g in chore_groups)) == 1
    slots_by_day_map = {}
    for s, slot in enumerate(slots):
        slots_by_day_map.setdefault(slot["day_idx"], []).append(s)

    if uniform_buffer:
        B = chore_groups[0]["buffer_days"]
        window_starts = list(range(0, max(1, total_days - B)))
        n_v = n_people * len(window_starts)
        V_BASE = n_x + n_y + 2 + 2 * n_tasks
        def vi_uniform(p_idx, w_idx): return V_BASE + p_idx * len(window_starts) + w_idx
    else:
        # general directional pairwise fallback (correct but O(pairs) variables)
        slots_by_day = sorted(range(n_slots), key=lambda s: slots[s]["day_idx"])
        global_max_buffer = max(g["buffer_days"] for g in chore_groups)
        buffer_pairs = []
        for p in range(n_people):
            for i, s1 in enumerate(slots_by_day):
                d1 = slots[s1]["day_idx"]
                buf1 = chore_groups[slots[s1]["group_idx"]]["buffer_days"]
                break_bound = max(buf1, global_max_buffer)
                for s2 in slots_by_day[i + 1:]:
                    d2 = slots[s2]["day_idx"]
                    gap = d2 - d1
                    if gap > break_bound:
                        break
                    threshold = buffer_threshold(chore_groups, slots[s1]["group_idx"], slots[s2]["group_idx"], gap)
                    if gap <= threshold:
                        buffer_pairs.append((p, s1, s2))
        n_v = len(buffer_pairs)
        V_BASE = n_x + n_y + 2 + 2 * n_tasks
        def vi(k): return V_BASE + k

    # --- pre-pass: resolve every group's windows BEFORE finalizing n_vars,
    # so we know how many cadence-violation variables we need ---
    resolved_windows = {}
    cadence_pairs = []  # (g_idx, d1, d2)
    for g_idx, g in enumerate(chore_groups):
        pb = group_phase_block.get(g["name"], 0)
        host_pb = group_phase_block.get(g.get("piggyback_on"), 0) if "piggyback_on" in g else 0
        windows, host_name, host_windows_for_linking = resolve_group_windows(
            g, chore_groups_by_name, total_days, phase_block=pb, host_phase_block=host_pb)
        resolved_windows[g_idx] = (windows, host_name, host_windows_for_linking)
        if host_name is None and "frequency_days" in g:
            freq = g["frequency_days"]
            tol = g.get("tolerance_days", 0)
            effective_min_gap = max(1, freq - tol)
            candidate_days = sorted({d for w in windows for d in w})
            for i, d1 in enumerate(candidate_days):
                for d2 in candidate_days[i + 1:]:
                    if d2 - d1 >= effective_min_gap:
                        break
                    cadence_pairs.append((g_idx, d1, d2))
    n_cadence = len(cadence_pairs)
    CADENCE_BASE = n_x + n_y + 2 + 2 * n_tasks + n_v
    def ci(k): return CADENCE_BASE + k

    n_vars = n_x + n_y + 2 + 2 * n_tasks + n_v + n_cadence  # FINAL - nothing after this changes it

    constraints = []
    window_rows, window_lb, window_ub = [], [], []
    cadence_rows = []  # SOFT min-gap between this group's own candidate days
    piggyback_allowed_days = {}  # g_idx -> set of days it's allowed to fire on at all
    phase_allowed_days = {}      # g_idx -> set of days allowed, for phase-blocked groups
    for g_idx, g in enumerate(chore_groups):
        windows, host_name, _ = resolved_windows[g_idx]
        pb = group_phase_block.get(g["name"], 0)
        for w in windows:
            row = lil_matrix((1, n_vars))
            for d in w:
                row[0, yi(g_idx, d)] = 1
            window_rows.append(row); window_lb.append(1); window_ub.append(1)
        if host_name is not None:
            piggyback_allowed_days[g_idx] = {d for w in windows for d in w}
        elif pb > 0:
            phase_allowed_days[g_idx] = {d for w in windows for d in w}

    # --- cadence: SOFT min-gap between a group's own candidate days.
    # "one per window" alone allows a day near the end of window i and a day
    # near the start of window i+1 to land too close together. This should
    # normally never happen and never needs a violation - but under phase
    # carry-over (shrunk first window), a hard version can become genuinely
    # infeasible depending on the remainder days. Soft = always solvable,
    # violation reported (and rare in practice) rather than a crash.
    # tolerance_days relaxes the minimum acceptable gap (freq - tolerance),
    # applied HERE in the core solve so MILP can jointly optimize with the
    # real flexibility available, instead of solving strict and patching
    # afterward (post-hoc repair is strictly weaker than joint optimization). ---
    for k, (g_idx, d1, d2) in enumerate(cadence_pairs):
        row = lil_matrix((1, n_vars))
        row[0, yi(g_idx, d1)] = 1
        row[0, yi(g_idx, d2)] = 1
        row[0, ci(k)] = -1
        cadence_rows.append(row)
    constraints.append(LinearConstraint(vstack(window_rows), lb=window_lb, ub=window_ub))
    if cadence_rows:
        constraints.append(LinearConstraint(vstack(cadence_rows), lb=-np.inf, ub=1))

    # --- piggyback linkage: tolerance_days=0 (default) forces the piggyback
    # chore onto EXACTLY the same day the host already picked. tolerance_days>0
    # relaxes this to "within tolerance_days of whichever day the host picked
    # for THIS SPECIFIC occurrence" - a per-instance linking constraint, not
    # just "somewhere in a wider window regardless of the host's actual day". ---
    piggy_rows, piggy_rhs = [], []
    piggy_link_rows = []
    for g_idx, g in enumerate(chore_groups):
        if "piggyback_on" not in g:
            continue
        host_idx = next(i for i, hg in enumerate(chore_groups) if hg["name"] == g["piggyback_on"])
        tol = g.get("tolerance_days", 0)
        windows, host_name, host_windows_for_linking = resolved_windows[g_idx]
        if tol == 0 or host_windows_for_linking is None:
            for d in piggyback_allowed_days[g_idx]:
                row = lil_matrix((1, n_vars))
                row[0, yi(g_idx, d)] = 1
                row[0, yi(host_idx, d)] = -1
                piggy_rows.append(row); piggy_rhs.append(0)
        else:
            # for each host day within the ORIGINAL (un-widened) window, Mop
            # firing on a day far from it must be justified by the host
            # having fired somewhere within tolerance - ties Mop to whichever
            # specific day the host actually picks, not just "nearby anything"
            for w, host_w in zip(windows, host_windows_for_linking):
                for d_m in w:
                    nearby_host_days = [d_h for d_h in host_w if abs(d_h - d_m) <= tol]
                    if not nearby_host_days:
                        continue  # this Mop day isn't near any valid host day - leave unconstrained here, window membership already limits it
                    row = lil_matrix((1, n_vars))
                    row[0, yi(g_idx, d_m)] = 1
                    for d_h in nearby_host_days:
                        row[0, yi(host_idx, d_h)] = -1
                    piggy_link_rows.append(row)
    if piggy_rows:
        constraints.append(LinearConstraint(vstack(piggy_rows), lb=piggy_rhs, ub=piggy_rhs))
    if piggy_link_rows:
        constraints.append(LinearConstraint(vstack(piggy_link_rows), lb=-np.inf, ub=0))

    link_rows, link_rhs = [], []
    for s, slot in enumerate(slots):
        row = lil_matrix((1, n_vars))
        for p in range(n_people):
            row[0, xi(s, p)] = 1
        row[0, yi(slot["group_idx"], slot["day_idx"])] = -1
        link_rows.append(row); link_rhs.append(0)
    constraints.append(LinearConstraint(vstack(link_rows), lb=link_rhs, ub=link_rhs))

    # --- HARD one-task-per-person-per-day. This is NOT part of the rest
    # buffer and must NEVER be soft - a person literally cannot be in two
    # places at once, regardless of how tight the buffer/carry-over gets.
    # (Making the buffer constraint soft earlier accidentally let this slip
    # through too, since gap=0 is inside the buffer's sliding window - this
    # is the fix: an explicit, always-hard constraint, independent of buffer.) ---
    slots_by_day_for_hard = {}
    for s, slot in enumerate(slots):
        slots_by_day_for_hard.setdefault(slot["day_idx"], []).append(s)
    same_day_rows = []
    for p_idx in range(n_people):
        for d, day_slots in slots_by_day_for_hard.items():
            if len(day_slots) < 2:
                continue
            row = lil_matrix((1, n_vars))
            for s in day_slots:
                row[0, xi(s, p_idx)] = 1
            same_day_rows.append(row)
    if same_day_rows:
        constraints.append(LinearConstraint(vstack(same_day_rows), lb=-np.inf, ub=1))

    A_max = lil_matrix((n_people, n_vars))
    A_min = lil_matrix((n_people, n_vars))
    max_lb = np.zeros(n_people)
    min_lb = np.zeros(n_people)
    for p_idx, p in enumerate(people):
        for s in range(n_slots):
            A_max[p_idx, xi(s, p_idx)] = -1
            A_min[p_idx, xi(s, p_idx)] = 1
        A_max[p_idx, IDX_LMAX] = 1
        A_min[p_idx, IDX_LMIN] = -1
        carried = carried_total.get(p, 0)
        max_lb[p_idx] = carried       # L_max >= carried_total + this-run count
        min_lb[p_idx] = -carried      # L_min <= carried_total + this-run count
    constraints.append(LinearConstraint(A_max, lb=max_lb, ub=np.inf))
    constraints.append(LinearConstraint(A_min, lb=min_lb, ub=np.inf))

    # --- per-CHORE-TYPE fairness linking: each task name gets its own L_max/L_min ---
    for t_idx, task in enumerate(unique_tasks):
        task_slot_ids = [s for s, slot in enumerate(slots) if slot["task"] == task]
        A_tmax = lil_matrix((n_people, n_vars))
        A_tmin = lil_matrix((n_people, n_vars))
        tmax_lb = np.zeros(n_people)
        tmin_lb = np.zeros(n_people)
        for p_idx, p in enumerate(people):
            for s in task_slot_ids:
                A_tmax[p_idx, xi(s, p_idx)] = -1
                A_tmin[p_idx, xi(s, p_idx)] = 1
            A_tmax[p_idx, task_lmax(t_idx)] = 1
            A_tmin[p_idx, task_lmin(t_idx)] = -1
            carried_t = carried_per_task.get(task, {}).get(p, 0)
            tmax_lb[p_idx] = carried_t
            tmin_lb[p_idx] = -carried_t
        constraints.append(LinearConstraint(A_tmax, lb=tmax_lb, ub=np.inf))
        constraints.append(LinearConstraint(A_tmin, lb=tmin_lb, ub=np.inf))

    # --- SOFT buffer constraint ---
    if uniform_buffer:
        # sum of ALL tasks for person p across any (B+1)-day window <= 1 + v
        # (this is exactly equivalent to "gap >= B+1 between any two tasks")
        # Carry-over from a previous run is folded in the SAME soft way: if a
        # person's last task (before day 0) still overlaps this window's span,
        # that's a virtual "1" already used - reduce the window's ub by 1
        # instead of hard-blocking days, so it becomes a violation (reported,
        # visible) only if truly unavoidable, never a silent infeasibility.
        virtual_k = {}  # p_idx -> days before day0 that the last task sits at
        for p_idx, p in enumerate(people):
            if person_blocked_days.get(p, 0) > 0:
                # person_blocked_days[p] = B - days_elapsed_before_run, so
                # days_elapsed_before_run = B - blocked; k = days_elapsed+1
                virtual_k[p_idx] = B - person_blocked_days[p] + 1

        rows, row_ub = [], []
        for p_idx in range(n_people):
            k = virtual_k.get(p_idx)
            for w_idx, d0 in enumerate(window_starts):
                row = lil_matrix((1, n_vars))
                for d in range(d0, min(d0 + B + 1, total_days)):
                    for s in slots_by_day_map.get(d, []):
                        row[0, xi(s, p_idx)] = 1
                row[0, vi_uniform(p_idx, w_idx)] = -1
                conflict = (k is not None) and (d0 <= B - k)
                rows.append(row)
                row_ub.append(0 if conflict else 1)
        constraints.append(LinearConstraint(vstack(rows), lb=-np.inf, ub=row_ub))
    else:
        if buffer_pairs:
            rows = []
            for k, (p, s1, s2) in enumerate(buffer_pairs):
                row = lil_matrix((1, n_vars))
                row[0, xi(s1, p)] = 1
                row[0, xi(s2, p)] = 1
                row[0, vi(k)] = -1
                rows.append(row)
            constraints.append(LinearConstraint(vstack(rows), lb=-np.inf, ub=1))

    integrality = np.ones(n_vars)
    lb = np.zeros(n_vars)
    ub = np.ones(n_vars)  # v's are binary too - ub=1 already correct, no override needed
    max_carried = max(carried_total.values()) if carried_total else 0
    lb[IDX_LMAX], ub[IDX_LMAX] = 0, n_slots + max_carried
    lb[IDX_LMIN], ub[IDX_LMIN] = 0, n_slots + max_carried
    max_carried_task = max((max(v.values()) for v in carried_per_task.values()), default=0)
    for t_idx in range(n_tasks):
        lb[task_lmax(t_idx)], ub[task_lmax(t_idx)] = 0, n_slots + max_carried_task
        lb[task_lmin(t_idx)], ub[task_lmin(t_idx)] = 0, n_slots + max_carried_task
    for s, slot in enumerate(slots):
        for p, person in enumerate(people):
            if is_person_off(person, slot["date"], slot["day"], days_off):
                ub[xi(s, p)] = 0
    for g_idx, allowed_days in piggyback_allowed_days.items():
        for d in range(total_days):
            if d not in allowed_days:
                ub[yi(g_idx, d)] = 0
    for g_idx, allowed_days in phase_allowed_days.items():
        for d in range(total_days):
            if d not in allowed_days:
                ub[yi(g_idx, d)] = 0  # chore not due yet - phase carried over from previous run
    bounds = Bounds(lb=lb, ub=ub)

    def v_index(k): return V_BASE + k  # valid in both branches - vi_uniform/vi both linearize to this

    # --- PHASE 1: minimize buffer + cadence violations ONLY. Mixing a huge
    # penalty weight with small fairness weights in one objective badly
    # conditions the branch-and-bound search (that's what caused the earlier
    # timeout). Lexicographic (staged) solving is the correct, numerically
    # stable way to do "this matters infinitely more than that" in a MILP. ---
    c_phase1 = np.zeros(n_vars)
    for k in range(n_v):
        c_phase1[v_index(k)] = 1
    for k in range(n_cadence):
        c_phase1[ci(k)] = 1
    result1 = milp(c=c_phase1, constraints=constraints, integrality=integrality, bounds=bounds)
    if not result1.success:
        return None, result1.message, [], []
    min_violations = int(round(sum(result1.x[v_index(k)] for k in range(n_v)))) if n_v else 0
    min_cadence_violations = int(round(sum(result1.x[ci(k)] for k in range(n_cadence)))) if n_cadence else 0

    # --- PHASE 2: lock in that minimum violation count as a hard cap, THEN
    # optimize fairness among all schedules that achieve it. ---
    c_phase2 = np.zeros(n_vars)
    c_phase2[IDX_LMAX] = 1
    c_phase2[IDX_LMIN] = -1
    PER_TASK_WEIGHT = 4
    for t_idx in range(n_tasks):
        c_phase2[task_lmax(t_idx)] = PER_TASK_WEIGHT
        c_phase2[task_lmin(t_idx)] = -PER_TASK_WEIGHT

    phase2_constraints = list(constraints)
    if n_v:
        cap_row = lil_matrix((1, n_vars))
        for k in range(n_v):
            cap_row[0, v_index(k)] = 1
        phase2_constraints.append(LinearConstraint(cap_row, lb=0, ub=min_violations))
    if n_cadence:
        cadence_cap_row = lil_matrix((1, n_vars))
        for k in range(n_cadence):
            cadence_cap_row[0, ci(k)] = 1
        phase2_constraints.append(LinearConstraint(cadence_cap_row, lb=0, ub=min_cadence_violations))

    result = milp(c=c_phase2, constraints=phase2_constraints, integrality=integrality, bounds=bounds)
    if not result.success:
        return None, result.message, [], []

    cadence_violation_details = []
    if n_cadence:
        cadence_values = result.x[CADENCE_BASE:CADENCE_BASE + n_cadence]
        for k, (g_idx, d1, d2) in enumerate(cadence_pairs):
            if cadence_values[k] > 0.5:
                cadence_violation_details.append({
                    "group": chore_groups[g_idx]["name"],
                    "date1": calendar[d1], "date2": calendar[d2], "gap": d2 - d1,
                })

    v_values = result.x[V_BASE:V_BASE + n_v] if n_v else []
    forced_violations = []
    if uniform_buffer:
        n_windows = len(window_starts)
        for k in range(n_v):
            if v_values[k] > 0.5:
                p_idx, w_idx = divmod(k, n_windows)
                d0 = window_starts[w_idx]
                d_end = min(d0 + B, total_days - 1)
                forced_violations.append({
                    "person": people[p_idx],
                    "task1": f"window {calendar[d0]}", "date1": calendar[d0],
                    "task2": f"to {calendar[d_end]}", "date2": calendar[d_end],
                    "gap": d_end - d0,
                })
    else:
        for k, (p, s1, s2) in enumerate(buffer_pairs):
            if v_values[k] > 0.5:
                forced_violations.append({
                    "person": people[p],
                    "task1": slots[s1]["task"], "date1": slots[s1]["date"],
                    "task2": slots[s2]["task"], "date2": slots[s2]["date"],
                    "gap": slots[s2]["day_idx"] - slots[s1]["day_idx"],
                })

    x = result.x[:n_x].reshape(n_slots, n_people)
    y = result.x[n_x:n_x + n_y].reshape(len(chore_groups), total_days)
    active_slots = []
    for s, slot in enumerate(slots):
        if y[slot["group_idx"], slot["day_idx"]] > 0.5:
            p = int(np.argmax(x[s]))
            active_slots.append({**slot, "person": people[p]})
    total_exceptions = len(forced_violations) + len(cadence_violation_details)
    note = "optimal, all rules fully honored" if total_exceptions == 0 else \
           f"optimal given constraints - {total_exceptions} unavoidable exception(s)"
    return active_slots, note, forced_violations, cadence_violation_details




def algo_greedy(people, chore_groups, days_off, calendar, weekday):
    total_days = len(calendar)
    last_task = {p: None for p in people}
    last_group = {p: None for p in people}
    task_counts = {p: 0 for p in people}
    per_task_counts = {t: {p: 0 for p in people} for g in chore_groups for t in g["tasks"]}
    active_slots = []

    # decide WHICH day fires each group's window, greedily, in isolation per window
    fire_day = {}
    for g_idx, g in enumerate(chore_groups):
        for w in build_windows(g["frequency_days"], total_days):
            fire_day[(g_idx, w[-1])] = w  # keyed by window end for lookup below
    # map day -> list of (group_idx, window) whose window ends today (forces a decision by then)
    windows_by_group = {g_idx: build_windows(g["frequency_days"], total_days)
                        for g_idx, g in enumerate(chore_groups)}
    fired = {g_idx: set() for g_idx in range(len(chore_groups))}  # window-start markers already fired

    for d in range(total_days):
        assigned_today = set()
        due_tasks = []  # (group_idx, task_name)

        for g_idx, g in enumerate(chore_groups):
            windows = windows_by_group[g_idx]
            # find the window containing today that hasn't fired yet
            for w in windows:
                if d in w and w[0] not in fired[g_idx]:
                    is_last_day = (d == w[-1])
                    # opportunistic firing: check if TODAY has a well-rested candidate
                    candidates = [p for p in people
                                  if not is_person_off(p, calendar[d], weekday[d], days_off)
                                  and p not in assigned_today]
                    if candidates:
                        best_rest = max(
                            (d - last_task[p] - 1) if last_task[p] is not None else 999
                            for p in candidates
                        )
                        good_day = best_rest >= g["buffer_days"]
                    else:
                        good_day = False
                    if good_day or is_last_day:
                        fired[g_idx].add(w[0])
                        for task in g["tasks"]:
                            due_tasks.append((g_idx, task))
                    break  # only one window can contain today per group

        for g_idx, task in due_tasks:
            available = [p for p in people
                         if not is_person_off(p, calendar[d], weekday[d], days_off)
                         and p not in assigned_today]
            if not available:
                available = [p for p in people if p not in assigned_today]  # forced, may violate days-off
            best_person = max(
                available,
                key=lambda p: (
                    (d - last_task[p]) if last_task[p] is not None else 9999,
                    -per_task_counts[task][p],
                    -task_counts[p],
                )
            )
            active_slots.append({"date": calendar[d], "day": weekday[d], "task": task,
                                 "day_idx": d, "group_idx": g_idx, "person": best_person})
            last_task[best_person] = d
            last_group[best_person] = g_idx
            task_counts[best_person] += 1
            per_task_counts[task][best_person] += 1
            assigned_today.add(best_person)

    return active_slots, "greedy-complete (no optimality guarantee)"




def algo_simulated_annealing(people, chore_groups, days_off, calendar, weekday,
                              seed_slots, iterations=100000, seed=42):
    """Start from the greedy solution's occurrence days + assignments, then
    hill-climb/anneal on WHO does each task-instance to improve fairness and
    reduce buffer violations, while never breaking days-off or one-task/day."""
    rng = random.Random(seed)
    slots = [dict(s) for s in seed_slots]  # occurrence days fixed from seed
    n = len(slots)

    def score(slots):
        m = evaluate(people, chore_groups, slots)
        return m["fairness_spread"] * 10 + m["total_per_task_spread"] * 20 + m["buffer_violations"] * 100

    def valid_swap(i, j):
        # swapping people at slots i and j must not create a same-day double-booking
        # or assign someone on their day off
        si, sj = slots[i], slots[j]
        if si["day_idx"] == sj["day_idx"] and si["person"] != sj["person"]:
            return False  # would need same person twice same day at either slot's other tasks - skip for safety
        for (target, new_person) in [(si, sj["person"]), (sj, si["person"])]:
            if is_person_off(new_person, target["date"], target["day"], days_off):
                return False
            # same-day conflict check against ALL other slots that day
            for k, other in enumerate(slots):
                if k in (i, j):
                    continue
                if other["day_idx"] == target["day_idx"] and other["person"] == new_person:
                    return False
        return True

    current_score = score(slots)
    best_slots = [dict(s) for s in slots]
    best_score = current_score
    T0, T_end = 5.0, 0.01

    for it in range(iterations):
        T = T0 * ((T_end / T0) ** (it / iterations))
        i, j = rng.sample(range(n), 2)
        if slots[i]["person"] == slots[j]["person"]:
            continue
        if not valid_swap(i, j):
            continue
        slots[i]["person"], slots[j]["person"] = slots[j]["person"], slots[i]["person"]
        new_score = score(slots)
        delta = new_score - current_score
        if delta <= 0 or rng.random() < np.exp(-delta / max(T, 1e-6)):
            current_score = new_score
            if current_score < best_score:
                best_score = current_score
                best_slots = [dict(s) for s in slots]
        else:
            slots[i]["person"], slots[j]["person"] = slots[j]["person"], slots[i]["person"]  # revert

    return best_slots, f"annealed ({iterations} iters)"




def _make_score_fn(people, chore_groups):
    def score(slots):
        m = evaluate(people, chore_groups, slots)
        return m["fairness_spread"] * 10 + m["total_per_task_spread"] * 20 + m["buffer_violations"] * 100
    return score




def _make_valid_swap_fn(slots, days_off):
    def valid_swap(i, j):
        si, sj = slots[i], slots[j]
        if si["day_idx"] == sj["day_idx"] and si["person"] != sj["person"]:
            return False
        for (target, new_person) in [(si, sj["person"]), (sj, si["person"])]:
            if is_person_off(new_person, target["date"], target["day"], days_off):
                return False
            for k, other in enumerate(slots):
                if k in (i, j):
                    continue
                if other["day_idx"] == target["day_idx"] and other["person"] == new_person:
                    return False
        return True
    return valid_swap




def rest_balance_spread(people, slots):
    """Spread (max-min) of each person's AVERAGE rest gap. Shared by
    rest_polish_score, print_metrics, and winner-selection - one
    implementation, so 'rest balance' means the same number everywhere
    it's used, including in the ranking that actually picks a winner."""
    last_task = {}
    per_person_rests = {p: [] for p in people}
    for slot in sorted(slots, key=lambda s: s["day_idx"]):
        p = slot["person"]
        if p in last_task:
            per_person_rests[p].append(slot["day_idx"] - last_task[p] - 1)
        last_task[p] = slot["day_idx"]
    avgs = [sum(rs) / len(rs) for rs in per_person_rests.values() if rs]
    return (max(avgs) - min(avgs)) if avgs else 0


def rest_polish_score(people, chore_groups, slots, buffer_days_target):
    """Lower is better. Priority order:
    1. true violations (rest < buffer) - the only thing that's really wrong
    2. borderline cases (rest == buffer exactly) - technically fine, but zero margin
    3. spread of AVERAGE REST ACROSS PEOPLE - this is the part that was
       missing before: minimizing total violations and maximizing the global
       average doesn't stop one person's rest pattern from being consistently
       tighter than everyone else's. This directly targets "does everyone
       get a similarly comfortable rest pattern", not just "is the overall
       number OK".
    4. reward higher average rest overall (tie-breaking preference)
    Does NOT touch workload fairness or per-chore spread - this pass has one job."""
    last_task = {}
    all_rests = []
    for slot in sorted(slots, key=lambda s: s["day_idx"]):
        p = slot["person"]
        if p in last_task:
            all_rests.append(slot["day_idx"] - last_task[p] - 1)
        last_task[p] = slot["day_idx"]
    true_violations = sum(1 for r in all_rests if r < buffer_days_target)
    borderline = sum(1 for r in all_rests if r == buffer_days_target)
    avg_rest = sum(all_rests) / len(all_rests) if all_rests else 0
    spread = rest_balance_spread(people, slots)

    return true_violations * 1000 + borderline * 5 + spread * 20 - avg_rest




def _generate_polish_neighbors(people, chore_groups, days_off, state, buffer_days_target,
                                 calendar, weekday, baseline_fairness, baseline_per_task, baseline_structural):
    """All valid, safety-checked neighbor states reachable from `state` in one
    move (person-swap or day-shift), each scored. Used by beam search - the
    caller decides how many of these to keep, not this function."""
    n = len(state)
    total_days = len(calendar)
    chore_groups_by_idx = {i: g for i, g in enumerate(chore_groups)}
    valid_swap = _make_valid_swap_fn(state, days_off)

    def safety_ok(candidate):
        m = evaluate(people, chore_groups, candidate)
        if m["fairness_spread"] > baseline_fairness or m["total_per_task_spread"] > baseline_per_task:
            return False
        if count_structural_violations(candidate, chore_groups, days_off, calendar, weekday) > baseline_structural:
            return False
        return True

    neighbors = []

    # --- move type 1: person-swap ---
    for i in range(n):
        for j in range(i + 1, n):
            if state[i]["person"] == state[j]["person"] or not valid_swap(i, j):
                continue
            candidate = [dict(s) for s in state]
            candidate[i]["person"], candidate[j]["person"] = candidate[j]["person"], candidate[i]["person"]
            if safety_ok(candidate):
                score = rest_polish_score(people, chore_groups, candidate, buffer_days_target)
                neighbors.append((score, candidate))

    # --- move type 2: day-shift (only for groups with tolerance_days > 0) ---
    occurrences = {}
    for idx, s in enumerate(state):
        occurrences.setdefault((s["group_idx"], s["day_idx"]), []).append(idx)
    for (g_idx, d_old), idxs in occurrences.items():
        tol = chore_groups_by_idx[g_idx].get("tolerance_days", 0)
        if tol == 0:
            continue
        for d_new in range(max(0, d_old - tol), min(total_days, d_old + tol + 1)):
            if d_new == d_old:
                continue
            movers = [state[k] for k in idxs]
            others_that_day = [s["person"] for k, s in enumerate(state) if k not in idxs and s["day_idx"] == d_new]
            if any(is_person_off(m["person"], calendar[d_new], weekday[d_new], days_off) for m in movers):
                continue
            if any(m["person"] in others_that_day for m in movers):
                continue
            if len(set(m["person"] for m in movers)) != len(movers):
                continue
            candidate = [dict(s) for s in state]
            for k in idxs:
                candidate[k]["day_idx"] = d_new
                candidate[k]["date"] = calendar[d_new]
                candidate[k]["day"] = weekday[d_new]
            if safety_ok(candidate):
                score = rest_polish_score(people, chore_groups, candidate, buffer_days_target)
                neighbors.append((score, candidate))

    return neighbors


def polish_schedule(people, chore_groups, days_off, slots, buffer_days_target, calendar, weekday,
                     beam_width=6, max_rounds=60, patience=10):
    """BEAM SEARCH, not pure greedy hill-climbing: keeps the top `beam_width`
    candidate states each round (not just the single best move), expands ALL
    of them, then prunes back down. This is the tractable, principled version
    of "search more broadly than one path" - true brute-force over every
    permutation is computationally impossible at this scale (~47 slots, 5
    people is already ~5^47 states), but beam search genuinely escapes the
    classic greedy trap: a move that looks slightly worse now but opens a
    much better state next round survives, instead of being discarded
    immediately the way single-path hill-climbing would discard it.

    Two move types, same as before: person-swap (WHO, never WHEN) and
    day-shift (WHEN, only within a chore group's own tolerance_days - the
    ONLY place tolerance_days has any effect; the core solve always targets
    the exact day). Both moves are gated identically: never accepted if they
    increase structural violations (frequency/cadence/piggyback/days-off) or
    make fairness worse than the schedule this pass started from.

    Stops early if the best-ever score hasn't improved in `patience` rounds -
    beam search costs beam_width times more per round than plain
    hill-climbing, so this keeps runtime sane without sacrificing the search
    breadth that matters."""
    base = [dict(s) for s in slots]
    baseline = evaluate(people, chore_groups, base)
    baseline_fairness = baseline["fairness_spread"]
    baseline_per_task = baseline["total_per_task_spread"]
    baseline_structural = count_structural_violations(base, chore_groups, days_off, calendar, weekday)

    start_score = rest_polish_score(people, chore_groups, base, buffer_days_target)
    beam = [(start_score, base)]
    best_score, best_slots = start_score, base
    moves_made = 0
    rounds_since_improvement = 0

    for _ in range(max_rounds):
        all_candidates = []
        for _, state in beam:
            all_candidates.extend(_generate_polish_neighbors(
                people, chore_groups, days_off, state, buffer_days_target,
                calendar, weekday, baseline_fairness, baseline_per_task, baseline_structural))

        if not all_candidates:
            break

        all_candidates.sort(key=lambda t: t[0])
        beam = all_candidates[:beam_width]
        moves_made += 1

        if beam[0][0] < best_score:
            best_score, best_slots = beam[0]
            rounds_since_improvement = 0
        else:
            rounds_since_improvement += 1
            if rounds_since_improvement >= patience:
                break

    return best_slots, moves_made




def algo_tabu_search(people, chore_groups, days_off, calendar, weekday,
                      seed_slots, iterations=20000, tabu_tenure=15, seed=42, sample_size=40):
    """Unlike SA (which sometimes accepts worse moves via temperature), Tabu
    Search always takes the BEST available neighbor - but bans reversing any
    of the last `tabu_tenure` moves, forcing it to explore instead of
    oscillating between the same two states. Aspiration: a tabu move is still
    taken if it beats the best solution found so far."""
    rng = random.Random(seed)
    slots = [dict(s) for s in seed_slots]
    n = len(slots)
    score = _make_score_fn(people, chore_groups)
    valid_swap = _make_valid_swap_fn(slots, days_off)

    current_score = score(slots)
    best_slots = [dict(s) for s in slots]
    best_score = current_score
    tabu = {}  # (i,j) swap key -> iteration it becomes allowed again

    for it in range(iterations):
        candidates = [tuple(rng.sample(range(n), 2)) for _ in range(sample_size)]
        best_move, best_move_score = None, None
        for i, j in candidates:
            if slots[i]["person"] == slots[j]["person"] or not valid_swap(i, j):
                continue
            slots[i]["person"], slots[j]["person"] = slots[j]["person"], slots[i]["person"]
            cand_score = score(slots)
            slots[i]["person"], slots[j]["person"] = slots[j]["person"], slots[i]["person"]  # revert to check next

            key = (i, j)
            is_tabu = tabu.get(key, -1) > it
            if is_tabu and cand_score >= best_score:
                continue  # tabu and doesn't beat global best - skip (aspiration not met)
            if best_move is None or cand_score < best_move_score:
                best_move, best_move_score = key, cand_score

        if best_move is None:
            continue
        i, j = best_move
        slots[i]["person"], slots[j]["person"] = slots[j]["person"], slots[i]["person"]
        current_score = best_move_score
        tabu[(i, j)] = it + tabu_tenure
        tabu[(j, i)] = it + tabu_tenure
        if current_score < best_score:
            best_score = current_score
            best_slots = [dict(s) for s in slots]

    return best_slots, f"tabu search ({iterations} iters, tenure={tabu_tenure})"




def algo_genetic(people, chore_groups, days_off, calendar, weekday,
                  seed_slots, generations=1500, population_size=30, seed=42):
    """Evolves a POPULATION of candidate person-assignments (occurrence days
    stay fixed from the seed) via crossover + mutation, unlike SA/Tabu which
    walk a single solution. Invalid children (same-day conflicts, days-off)
    are repaired by falling back to a valid random swap."""
    rng = random.Random(seed)
    n = len(seed_slots)
    score = _make_score_fn(people, chore_groups)

    def random_individual():
        ind = [dict(s) for s in seed_slots]
        valid_swap = _make_valid_swap_fn(ind, days_off)
        for _ in range(n):
            i, j = rng.sample(range(n), 2)
            if ind[i]["person"] != ind[j]["person"] and valid_swap(i, j):
                ind[i]["person"], ind[j]["person"] = ind[j]["person"], ind[i]["person"]
        return ind

    def crossover(a, b):
        child = [dict(a[k]) for k in range(n)]
        valid_swap = _make_valid_swap_fn(child, days_off)
        for k in range(n):
            if rng.random() < 0.5 and b[k]["person"] != child[k]["person"]:
                j = next((idx for idx in range(n) if child[idx]["person"] == b[k]["person"]
                          and child[idx]["day_idx"] != child[k]["day_idx"]), None)
                if j is not None and valid_swap(k, j):
                    child[k]["person"], child[j]["person"] = child[j]["person"], child[k]["person"]
        return child

    def mutate(ind):
        valid_swap = _make_valid_swap_fn(ind, days_off)
        i, j = rng.sample(range(n), 2)
        if ind[i]["person"] != ind[j]["person"] and valid_swap(i, j):
            ind[i]["person"], ind[j]["person"] = ind[j]["person"], ind[i]["person"]
        return ind

    population = [random_individual() for _ in range(population_size)]
    best_slots = min(population, key=score)
    best_score = score(best_slots)

    for gen in range(generations):
        scored_pop = sorted(population, key=score)
        if score(scored_pop[0]) < best_score:
            best_score = score(scored_pop[0])
            best_slots = [dict(s) for s in scored_pop[0]]

        # tournament selection + crossover + mutation -> next generation
        next_gen = scored_pop[:2]  # elitism: keep the 2 best unchanged
        while len(next_gen) < population_size:
            t1 = min(rng.sample(scored_pop, 4), key=score)
            t2 = min(rng.sample(scored_pop, 4), key=score)
            child = crossover(t1, t2)
            if rng.random() < 0.2:
                child = mutate(child)
            next_gen.append(child)
        population = next_gen

    return best_slots, f"genetic ({generations} generations, pop={population_size})"




def algo_daily_hungarian(people, chore_groups, days_off, calendar, weekday):
    """Same day-choice logic as greedy (WHEN each chore fires), but the person
    assignment for a day's tasks is solved as an exact bipartite MINIMUM COST
    MATCHING (Hungarian algorithm) across ALL of that day's tasks at once,
    instead of greedy's one-task-at-a-time priority pick. This can find a
    better joint assignment on days with multiple simultaneous tasks."""
    from scipy.optimize import linear_sum_assignment
    total_days = len(calendar)
    n_people = len(people)
    last_task = {p: None for p in people}
    task_counts = {p: 0 for p in people}
    per_task_counts = {t: {p: 0 for p in people} for g in chore_groups for t in g["tasks"]}
    active_slots = []
    windows_by_group = {g_idx: build_windows(g["frequency_days"], total_days)
                        for g_idx, g in enumerate(chore_groups) if "piggyback_on" not in g}
    fired = {g_idx: set() for g_idx in range(len(chore_groups))}
    occurrence_count = {g_idx: 0 for g_idx in range(len(chore_groups))}
    piggybacks_by_host = {}  # host_idx -> [(g_idx, every_nth), ...]
    for g_idx, g in enumerate(chore_groups):
        if "piggyback_on" in g:
            host_idx = next(i for i, hg in enumerate(chore_groups) if hg["name"] == g["piggyback_on"])
            piggybacks_by_host.setdefault(host_idx, []).append((g_idx, g["every_nth"]))

    for d in range(total_days):
        due_tasks = []
        for g_idx, g in enumerate(chore_groups):
            if "piggyback_on" in g:
                continue
            windows = windows_by_group[g_idx]
            for w in windows:
                if d in w and w[0] not in fired[g_idx]:
                    is_last_day = (d == w[-1])
                    candidates = [p for p in people if not is_person_off(p, calendar[d], weekday[d], days_off)]
                    best_rest = max(((d - last_task[p] - 1) if last_task[p] is not None else 999)
                                     for p in candidates) if candidates else -1
                    if best_rest >= g["buffer_days"] or is_last_day:
                        fired[g_idx].add(w[0])
                        occurrence_count[g_idx] += 1
                        for task in g["tasks"]:
                            due_tasks.append((g_idx, task))
                        # piggyback: this host's Nth occurrence also fires its rider chores today
                        for pig_idx, every_nth in piggybacks_by_host.get(g_idx, []):
                            if occurrence_count[g_idx] % every_nth == 0:
                                for task in chore_groups[pig_idx]["tasks"]:
                                    due_tasks.append((pig_idx, task))
                    break
        if not due_tasks:
            continue

        # cost matrix: rows=due_tasks, cols=people. Lower cost = more rested + fewer of this task type so far.
        cost = np.zeros((len(due_tasks), n_people))
        for ti, (g_idx, task) in enumerate(due_tasks):
            for pi, p in enumerate(people):
                if is_person_off(p, calendar[d], weekday[d], days_off):
                    cost[ti, pi] = 1e6
                    continue
                rest_gap = (d - last_task[p]) if last_task[p] is not None else 999
                cost[ti, pi] = -rest_gap * 10 + per_task_counts[task][p] * 5 + task_counts[p]

        # Hungarian needs a square-ish matrix with no person used twice THIS day -
        # pad with dummy rows if fewer tasks than people so each person appears once
        row_ind, col_ind = linear_sum_assignment(cost)
        assigned_today = set()
        for ti, pi in zip(row_ind, col_ind):
            if ti >= len(due_tasks):
                continue
            g_idx, task = due_tasks[ti]
            person = people[pi]
            if person in assigned_today or cost[ti, pi] >= 1e6:
                # fallback: pick best remaining eligible person not yet used today
                remaining = [p for p in people if p not in assigned_today
                             and not is_person_off(p, calendar[d], weekday[d], days_off)]
                person = max(remaining, key=lambda p: (d - last_task[p]) if last_task[p] is not None else 9999) \
                    if remaining else people[0]
            active_slots.append({"date": calendar[d], "day": weekday[d], "task": task,
                                 "day_idx": d, "group_idx": g_idx, "person": person})
            last_task[person] = d
            task_counts[person] += 1
            per_task_counts[task][person] += 1
            assigned_today.add(person)

    return active_slots, "daily Hungarian assignment (exact per-day matching)"




def count_structural_violations(active_slots, chore_groups, days_off, calendar, weekday):
    """Silent version of validate_schedule's checks, for ranking candidates.
    These are NON-NEGOTIABLE structural rules (frequency, cadence, piggyback,
    days-off) - unlike buffer, there's no 'soft' version of these. A candidate
    that breaks one of these is WRONG, regardless of how good its other
    metrics look, and must never be picked over a structurally-correct one."""
    total_days = len(calendar)
    occ_by_group = {g["name"]: sorted({s["day_idx"] for s in active_slots
                                        if chore_groups[s["group_idx"]]["name"] == g["name"]})
                    for g in chore_groups}
    violations = 0
    for g in chore_groups:
        if "piggyback_on" in g:
            continue
        windows = build_windows(g["frequency_days"], total_days)
        occ = set(occ_by_group[g["name"]])
        violations += sum(1 for w in windows if len(occ & set(w)) != 1)
        tol = g.get("tolerance_days", 0)
        effective_min_gap = max(1, g["frequency_days"] - tol)
        occ_sorted = sorted(occ)
        for i in range(1, len(occ_sorted)):
            gap = occ_sorted[i] - occ_sorted[i - 1]
            if gap < effective_min_gap or gap > 2 * g["frequency_days"] - 1 + tol:
                violations += 1
    for g in chore_groups:
        if "piggyback_on" not in g:
            continue
        host_occ = occ_by_group[g["piggyback_on"]]
        expected = [d for i, d in enumerate(host_occ) if (i + 1) % g["every_nth"] == 0]
        actual = occ_by_group[g["name"]]
        tol = g.get("tolerance_days", 0)
        if len(actual) != len(expected):
            violations += 1
        else:
            violations += sum(1 for a, e in zip(actual, expected) if abs(a - e) > tol)
    violations += sum(1 for s in active_slots if is_person_off(s["person"], s["date"], s["day"], days_off))
    return violations