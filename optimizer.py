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
    - a person is never assigned a task they are excluded from
      (config: exclusions - "this person never does this chore")
  Soft rules (minimized, never silently ignored):
    - the rest-buffer between any two of a person's tasks
    - cadence (consecutive occurrences of the same chore stay close
      to its own frequency_days, not just "one per window")
  Fairness priority (they can genuinely conflict, so the order matters):
    1. equal TOTAL number of tasks per person (cumulative across runs)
    2. equal share of each INDIVIDUAL chore, among the schedules that
       keep (1) - counted only over people eligible for that chore
  Those two are the same schedule only while everyone can do every chore.
  Exclude someone from the dominant chore and they diverge sharply, so
  (1) wins and (2) settles for whatever is left.

  Algorithm 1 - MILP (HiGHS)              : exact, provable optimum
  Algorithm 2 - Greedy heuristic          : fast, single pass, no lookahead
  Algorithm 3 - Simulated Annealing       : metaheuristic, temperature-based
  Algorithm 4 - Tabu Search               : metaheuristic, memory-based
  Algorithm 5 - Genetic Algorithm         : metaheuristic, population-based
  Algorithm 6 - Daily Hungarian Assignment: exact per-day bipartite matching

Plus a fairness-safe rest-polish pass (polish_schedule) that can be applied
to any of the above afterward.
"""
import heapq
import itertools
import random
import numpy as np
from scipy.optimize import milp, linear_sum_assignment, LinearConstraint, Bounds
from scipy.sparse import lil_matrix, vstack


def is_person_off(person, date_obj, weekday_name, days_off):
    # hot path (millions of calls from the heuristics and polish) - skip the
    # date formatting entirely for the common "no days off" case
    off_entries = days_off.get(person)
    if not off_entries:
        return False
    return weekday_name in off_entries or date_obj.isoformat() in off_entries


def is_person_excluded(person, task, exclusions):
    """True if `person` is configured to NEVER do `task`.

    Unlike days-off (a calendar thing - "not THIS day"), an exclusion holds
    on every single day, so an excluded person simply never enters that
    task's candidate pool. `exclusions` maps person -> set of task names and
    is normalized by load_config (which also expands a chore-group name into
    that group's tasks), so everything downstream only ever sees task names.
    """
    if not exclusions:
        return False
    return task in exclusions.get(person, ())




def build_windows(frequency_days, total_days):
    windows, d = [], 0
    while d < total_days:
        end = min(d + frequency_days, total_days)
        windows.append(list(range(d, end)))
        d = end
    return windows


def compute_group_phase_blocks(chore_groups, state, start_day):
    """Shared by algo_milp AND the validators (count_structural_violations,
    validate_schedule) - this used to only live inside algo_milp, which
    caused a real bug: the validator had no idea a previous run's carried
    phase existed, so it judged every algorithm against 'fresh windows
    starting at day 0' - incorrectly FLAGGING MILP's correct, deliberately
    delayed first occurrence as a violation, while incorrectly PASSING
    every other algorithm's carry-over-blindness (which happened to match
    the naive fresh-start assumption by coincidence, not by correctness).

    Returns {group_name: phase_block_days} - days at the start of THIS run
    during which a chore is not yet due, because the previous run's last
    occurrence hasn't finished its own frequency cycle yet."""
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
    return group_phase_block


def compute_group_phase_deadlines(chore_groups, state, start_day):
    """The missing UPPER-bound counterpart to compute_group_phase_blocks.
    phase_block only enforces 'not due before day X' (a lower bound) - on
    its own, that let the FIRST window stay just as wide as a normal
    window (frequency_days wide), so the solver could legally drift all
    the way to the far end of it and produce a much bigger real-world gap
    than the chore's own tolerance promises (e.g. last done Aug 9,
    'due after Aug 19', but the old first window still let it land as
    late as Aug 26 - a 16-17 day real gap when the rule is '10 +-1').

    Returns {group_name: deadline_day_idx} - the LAST day index (relative
    to this run's day 0) by which the first occurrence must happen to
    keep the boundary gap within (frequency_days + tolerance_days). Only
    present for groups that actually have carried-over phase data."""
    deadlines = {}
    if state and "group_phase" in state:
        for g in chore_groups:
            if "piggyback_on" in g:
                continue
            last_date = state["group_phase"].get(g["name"])
            if last_date is None:
                continue
            days_since = (start_day - last_date).days
            tol = g.get("tolerance_days", 0)
            max_gap = g["frequency_days"] + tol
            deadline_day_idx = max_gap - days_since - 1  # last acceptable day index, inclusive
            deadlines[g["name"]] = deadline_day_idx
    return deadlines


def resolve_group_windows(g, chore_groups_by_name, total_days, phase_block=0, host_phase_block=0,
                           phase_deadline=None, host_phase_deadline=None):
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
        host_windows, _, _ = resolve_group_windows(host, chore_groups_by_name, total_days,
                                                     phase_block=host_phase_block, phase_deadline=host_phase_deadline)
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
        # width capped by BOTH: the normal frequency_days width, AND the
        # phase_deadline (if given) - the missing upper-bound fix. Without
        # phase_deadline, this window could legally stretch the full
        # frequency_days wide even though the carried-over debt already
        # used up most of the tolerance budget getting here.
        natural_end = g["frequency_days"]
        if phase_deadline is not None:
            capped_end = min(natural_end, phase_deadline + 1)
            end = max(capped_end, phase_block + 1)  # never produce an empty window
        else:
            end = natural_end
        first = list(range(phase_block, min(end, total_days)))
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




def evaluate(people, chore_groups, active_slots, exclusions=None):
    """Common scoring so every algorithm is judged the same way."""
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
    # per-chore fairness: spread within EACH task type, counted ONLY over the
    # people eligible for that chore. An excluded person's zero is the rule
    # working, not unfairness - counting it both inflates this number and
    # (worse) tells the optimizer to drag everyone else's share down toward
    # that zero, which is impossible and distorts the whole objective.
    per_task_spread = {}
    for task, counts in per_task_counts.items():
        eligible = [c for p, c in counts.items() if not is_person_excluded(p, task, exclusions)]
        per_task_spread[task] = (max(eligible) - min(eligible)) if eligible else 0
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




def algo_milp(people, chore_groups, days_off, calendar, weekday, state=None, exclusions=None):
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
    group_phase_block = compute_group_phase_blocks(chore_groups, state, start_day)
    group_phase_deadline = compute_group_phase_deadlines(chore_groups, state, start_day)

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
        pd = group_phase_deadline.get(g["name"])
        host_pb = group_phase_block.get(g.get("piggyback_on"), 0) if "piggyback_on" in g else 0
        host_pd = group_phase_deadline.get(g.get("piggyback_on")) if "piggyback_on" in g else None
        windows, host_name, host_windows_for_linking = resolve_group_windows(
            g, chore_groups_by_name, total_days, phase_block=pb, host_phase_block=host_pb,
            phase_deadline=pd, host_phase_deadline=host_pd)
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

    # one soft "still owes rest from the previous run" variable per person
    # whose last task's buffer spills into this run (see the carry-over rows below)
    carry_people = [p_idx for p_idx, p in enumerate(people) if person_blocked_days[p] > 0]
    n_carry = len(carry_people)
    CARRY_BASE = CADENCE_BASE + n_cadence

    n_vars = n_x + n_y + 2 + 2 * n_tasks + n_v + n_cadence + n_carry  # FINAL - nothing after this changes it

    constraints = []
    window_rows, window_lb, window_ub = [], [], []
    cadence_rows = []  # SOFT min-gap between this group's own candidate days
    piggyback_allowed_days = {}  # g_idx -> set of days it's allowed to fire on at all
    phase_allowed_days = {}      # g_idx -> set of days allowed, for phase-blocked groups
    for g_idx, g in enumerate(chore_groups):
        windows, host_name, _ = resolved_windows[g_idx]
        pb = group_phase_block.get(g["name"], 0)
        for w_idx, w in enumerate(windows):
            row = lil_matrix((1, n_vars))
            for d in w:
                row[0, yi(g_idx, d)] = 1
            window_rows.append(row)
            # --- trailing partial window: OPTIONAL, not mandatory. If the
            # schedule length doesn't divide evenly by this chore's frequency
            # (e.g. 21 days / 10-day frequency leaves a 1-day remainder),
            # the old behavior FORCED an occurrence into that tiny leftover
            # window regardless of how badly it clashed with the previous
            # one. That's backwards: the same carry-over logic that lets a
            # chore's cycle roll INTO the next run should also let it roll
            # OUT of this one - if the last window is too short for a
            # decent occurrence, skip it now and let the next run's phase
            # carry-over pick it up naturally, instead of forcing a bad
            # cadence choice today. Only the genuinely last window of a
            # non-piggyback group qualifies - a phase-shrunk FIRST window
            # (from carry-over catching up) stays mandatory; that debt is
            # real and due now, not deferrable further. ---
            is_trailing_partial = (host_name is None and w_idx == len(windows) - 1
                                    and len(windows) > 1 and len(w) < g["frequency_days"])
            window_lb.append(0 if is_trailing_partial else 1)
            window_ub.append(1)
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
    same_day_rows = []
    for p_idx in range(n_people):
        for d, day_slots in slots_by_day_map.items():
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

    # --- per-CHORE-TYPE fairness linking: each task name gets its own
    # L_max/L_min, linked ONLY to the people eligible for that task. Linking
    # an excluded person would pin that chore's L_min to their forced 0 (plus
    # whatever they carried from before the exclusion existed), so the
    # objective would be chasing a spread it can never close - and would try
    # to close it by starving everyone else of that chore. ---
    for t_idx, task in enumerate(unique_tasks):
        task_slot_ids = [s for s, slot in enumerate(slots) if slot["task"] == task]
        eligible_idx = [p_idx for p_idx, p in enumerate(people)
                        if not is_person_excluded(p, task, exclusions)]
        n_elig = len(eligible_idx)
        A_tmax = lil_matrix((n_elig, n_vars))
        A_tmin = lil_matrix((n_elig, n_vars))
        tmax_lb = np.zeros(n_elig)
        tmin_lb = np.zeros(n_elig)
        for row, p_idx in enumerate(eligible_idx):
            for s in task_slot_ids:
                A_tmax[row, xi(s, p_idx)] = -1
                A_tmin[row, xi(s, p_idx)] = 1
            A_tmax[row, task_lmax(t_idx)] = 1
            A_tmin[row, task_lmin(t_idx)] = -1
            carried_t = carried_per_task.get(task, {}).get(people[p_idx], 0)
            tmax_lb[row] = carried_t
            tmin_lb[row] = -carried_t
        constraints.append(LinearConstraint(A_tmax, lb=tmax_lb, ub=np.inf))
        constraints.append(LinearConstraint(A_tmin, lb=tmin_lb, ub=np.inf))

    # --- SOFT buffer constraint ---
    if uniform_buffer:
        # sum of ALL tasks for person p across any (B+1)-day window <= 1 + v
        # (this is exactly equivalent to "gap >= B+1 between any two tasks")
        rows = []
        for p_idx in range(n_people):
            for w_idx, d0 in enumerate(window_starts):
                row = lil_matrix((1, n_vars))
                for d in range(d0, min(d0 + B + 1, total_days)):
                    for s in slots_by_day_map.get(d, []):
                        row[0, xi(s, p_idx)] = 1
                row[0, vi_uniform(p_idx, w_idx)] = -1
                rows.append(row)
        constraints.append(LinearConstraint(vstack(rows), lb=-np.inf, ub=1))
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

    # --- SOFT rest carry-over from the previous run: a person who still owes
    # rest gets no task on days [0, blocked) unless that's truly unavoidable.
    # Exactly those days conflict with the carried-over task - an earlier
    # version zeroed whole (B+1)-day windows instead, which also blocked the
    # legal days after them and reported phantom "unavoidable" exceptions.
    # Soft, not hard, so it shows up as a reported violation rather than a
    # bare infeasibility. ---
    if carry_people:
        rows = []
        for k, p_idx in enumerate(carry_people):
            blocked = min(person_blocked_days[people[p_idx]], total_days)
            row = lil_matrix((1, n_vars))
            for d in range(blocked):
                for s in slots_by_day_map.get(d, []):
                    row[0, xi(s, p_idx)] = 1
            row[0, CARRY_BASE + k] = -blocked  # one violation covers any number of early tasks
            rows.append(row)
        constraints.append(LinearConstraint(vstack(rows), lb=-np.inf, ub=0))

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
            if (is_person_off(person, slot["date"], slot["day"], days_off)
                    or is_person_excluded(person, slot["task"], exclusions)):
                ub[xi(s, p)] = 0  # can't work that day, or never does that chore
    for g_idx, allowed_days in piggyback_allowed_days.items():
        for d in range(total_days):
            if d not in allowed_days:
                ub[yi(g_idx, d)] = 0
    for g_idx, allowed_days in phase_allowed_days.items():
        for d in range(total_days):
            if d not in allowed_days:
                ub[yi(g_idx, d)] = 0  # chore not due yet - phase carried over from previous run
    bounds = Bounds(lb=lb, ub=ub)

    # every buffer-violation variable: within-run (both encodings share
    # V_BASE) plus rest owed from the previous run
    buffer_var_ids = [V_BASE + k for k in range(n_v)] + [CARRY_BASE + k for k in range(n_carry)]
    cadence_var_ids = [ci(k) for k in range(n_cadence)]

    # --- PHASE 1: minimize buffer + cadence violations ONLY. Mixing a huge
    # penalty weight with small fairness weights in one objective badly
    # conditions the branch-and-bound search (that's what caused the earlier
    # timeout). Lexicographic (staged) solving is the correct, numerically
    # stable way to do "this matters infinitely more than that" in a MILP. ---
    c_phase1 = np.zeros(n_vars)
    c_phase1[buffer_var_ids + cadence_var_ids] = 1
    result1 = milp(c=c_phase1, constraints=constraints, integrality=integrality, bounds=bounds)
    if not result1.success:
        return None, result1.message, [], []
    min_violations = int(round(result1.x[buffer_var_ids].sum()))
    min_cadence_violations = int(round(result1.x[cadence_var_ids].sum()))

    # --- PHASE 2: lock in that minimum violation count as a hard cap, THEN
    # optimize TOTAL workload fairness - cumulative across runs, since L_max
    # and L_min include each person's carried totals.
    #
    # This used to be one blended objective,
    #     (L_max - L_min) + 4 * sum(per-chore spreads),
    # which quietly sold total fairness to buy per-chore fairness: 4x, once
    # per chore, so per-chore always won. Harmless while everyone could do
    # every chore - and badly wrong the moment someone is excluded from the
    # dominant one, because then "an equal share of each chore" and "an equal
    # number of chores" are different schedules. Measured on a 7-person
    # config with 2 people excluded from daily dishes: the blend gives
    # 12,12,12,12,11,4,4 while staging gives 10,10,10,10,10,9,9. Staging
    # states the priority outright instead of burying it in a weight. ---
    phase2_constraints = list(constraints)
    for var_ids, cap in ((buffer_var_ids, min_violations), (cadence_var_ids, min_cadence_violations)):
        if var_ids:
            cap_row = lil_matrix((1, n_vars))
            cap_row[0, var_ids] = 1
            phase2_constraints.append(LinearConstraint(cap_row, lb=0, ub=cap))

    c_total_fairness = np.zeros(n_vars)
    c_total_fairness[IDX_LMAX] = 1
    c_total_fairness[IDX_LMIN] = -1
    result2 = milp(c=c_total_fairness, constraints=phase2_constraints,
                   integrality=integrality, bounds=bounds)
    if not result2.success:
        return None, result2.message, [], []
    best_total_spread = result2.x[IDX_LMAX] - result2.x[IDX_LMIN]

    # --- PHASE 3: even out each INDIVIDUAL chore, choosing only among the
    # schedules that still achieve phase 2's optimal total spread. Same
    # lexicographic trick as phase 1 -> phase 2: cap the previous stage's
    # objective, then optimize the next one underneath it. ---
    spread_cap_row = lil_matrix((1, n_vars))
    spread_cap_row[0, IDX_LMAX] = 1
    spread_cap_row[0, IDX_LMIN] = -1
    phase3_constraints = phase2_constraints + [
        LinearConstraint(spread_cap_row, lb=-np.inf, ub=best_total_spread + 1e-6)]

    c_per_chore = np.zeros(n_vars)
    for t_idx in range(n_tasks):
        c_per_chore[task_lmax(t_idx)] = 1
        c_per_chore[task_lmin(t_idx)] = -1
    result = milp(c=c_per_chore, constraints=phase3_constraints,
                  integrality=integrality, bounds=bounds)
    if not result.success:
        return None, result.message, [], []

    x = result.x[:n_x].reshape(n_slots, n_people)
    y = result.x[n_x:n_x + n_y].reshape(len(chore_groups), total_days)
    active_slots = []
    for s, slot in enumerate(slots):
        if y[slot["group_idx"], slot["day_idx"]] > 0.5:
            p = int(np.argmax(x[s]))
            active_slots.append({**slot, "person": people[p]})

    # --- exceptions are read off the FINAL schedule, not the violation
    # variables: phases 2-3 only cap how many of those may be 1, so they are
    # free to sit on any window and used to name the wrong person/dates. ---
    cadence_violation_details = [
        {"group": chore_groups[g_idx]["name"], "date1": calendar[d1], "date2": calendar[d2], "gap": d2 - d1}
        for g_idx, d1, d2 in cadence_pairs
        if y[g_idx, d1] > 0.5 and y[g_idx, d2] > 0.5
    ]

    forced_violations = []
    prev_people = (state or {}).get("people", {})
    for p in people:
        mine = sorted((s for s in active_slots if s["person"] == p), key=lambda s: s["day_idx"])
        if mine and mine[0]["day_idx"] < person_blocked_days[p]:
            info = prev_people[p]
            forced_violations.append({
                "person": p,
                "task1": f"{info['last_group']} (previous run)", "date1": info["last_task_date"],
                "task2": mine[0]["task"], "date2": mine[0]["date"],
                "gap": (mine[0]["date"] - info["last_task_date"]).days,
            })
        for a, b in zip(mine, mine[1:]):
            gap = b["day_idx"] - a["day_idx"]
            if gap <= buffer_threshold(chore_groups, a["group_idx"], b["group_idx"], gap):
                forced_violations.append({
                    "person": p,
                    "task1": a["task"], "date1": a["date"],
                    "task2": b["task"], "date2": b["date"],
                    "gap": gap,
                })

    total_exceptions = len(forced_violations) + len(cadence_violation_details)
    note = "optimal, all rules fully honored" if total_exceptions == 0 else \
           f"optimal given constraints - {total_exceptions} unavoidable exception(s)"
    return active_slots, note, forced_violations, cadence_violation_details




def algo_greedy(people, chore_groups, days_off, calendar, weekday, exclusions=None):
    total_days = len(calendar)
    last_task = {p: None for p in people}
    task_counts = {p: 0 for p in people}
    per_task_counts = {t: {p: 0 for p in people} for g in chore_groups for t in g["tasks"]}
    active_slots = []

    # WHICH day fires each group's window is decided greedily, per window:
    # the first day with a well-rested candidate, or the window's last day
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
                                  and any(not is_person_excluded(p, t, exclusions) for t in g["tasks"])
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
                         and not is_person_excluded(p, task, exclusions)
                         and p not in assigned_today]
            if not available:
                # forced: relax days-off FIRST and keep exclusions intact -
                # "never does this chore" is a harder rule than "off this day"
                available = [p for p in people if p not in assigned_today
                             and not is_person_excluded(p, task, exclusions)]
            if not available:
                available = [p for p in people if p not in assigned_today]  # forced, may violate both
            if not available:
                available = list(people)  # more tasks today than people - double-book rather than crash
            # Priority order mirrors the MILP's staged objective: people who
            # have actually cleared their rest buffer first (it's a soft rule,
            # but breaking it is worse than any fairness gain), then whoever
            # has done the FEWEST tasks overall, then the fewest of this
            # specific chore, and the rest gap only as a final tiebreak.
            #
            # Rest used to come first, which quietly under-worked anyone
            # excluded from a frequent chore: permanently the most rested
            # person in the house, yet they only ever competed for the few
            # slots they were eligible for, so they finished the month
            # several tasks light while everyone else absorbed the daily one.
            buf = chore_groups[g_idx]["buffer_days"]

            def pick_key(p, _task=task, _buf=buf):
                rest = (d - last_task[p] - 1) if last_task[p] is not None else 9999
                return (rest >= _buf, -task_counts[p], -per_task_counts[_task][p], rest)

            best_person = max(available, key=pick_key)
            active_slots.append({"date": calendar[d], "day": weekday[d], "task": task,
                                 "day_idx": d, "group_idx": g_idx, "person": best_person})
            last_task[best_person] = d
            task_counts[best_person] += 1
            per_task_counts[task][best_person] += 1
            assigned_today.add(best_person)

    return active_slots, "greedy-complete (no optimality guarantee)"




def algo_simulated_annealing(people, chore_groups, days_off, calendar, weekday,
                              seed_slots, iterations=100000, seed=42, exclusions=None):
    """Start from the greedy solution's occurrence days + assignments, then
    hill-climb/anneal on WHO does each task-instance to improve fairness and
    reduce buffer violations, while never breaking days-off, exclusions, or
    one-task/day."""
    rng = random.Random(seed)
    slots = [dict(s) for s in seed_slots]  # occurrence days fixed from seed
    n = len(slots)

    # the same objective and move-legality gate Tabu/GA/polish use - one
    # implementation each, so "better schedule" and "legal swap" mean the
    # same thing in every algorithm
    score = _make_score_fn(people, chore_groups, exclusions)
    valid_swap = _make_valid_swap_fn(slots, days_off, exclusions)

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




def _make_score_fn(people, chore_groups, exclusions=None):
    """The heuristics' mirror of the MILP's staged objective: buffer
    violations dominate, then TOTAL workload fairness, and per-chore fairness
    only breaks ties between schedules that already tie on both.

    The weights used to be the other way round (per-chore 20 against totals
    10), so SA/Tabu/GA chased the same bad trade the blended MILP objective
    did - piling work onto whoever can do the most chores. Kept at the
    original magnitude, because SA's temperature schedule is calibrated to
    the size of a typical score delta."""
    def score(slots):
        m = evaluate(people, chore_groups, slots, exclusions)
        return (m["buffer_violations"] * 100
                + m["fairness_spread"] * 10
                + m["total_per_task_spread"] * 0.5)
    return score




def _make_valid_swap_fn(slots, days_off, exclusions=None):
    """Swapping the people at slots i and j must not double-book anyone on a
    day, land anyone on a day off, or hand anyone a task they are excluded
    from. Closes over `slots`, so callers that mutate slots in place (SA,
    Tabu, GA) always see the current state."""
    def valid_swap(i, j):
        si, sj = slots[i], slots[j]
        if si["day_idx"] == sj["day_idx"] and si["person"] != sj["person"]:
            return False
        for (target, new_person) in [(si, sj["person"]), (sj, si["person"])]:
            if is_person_off(new_person, target["date"], target["day"], days_off):
                return False
            if is_person_excluded(new_person, target["task"], exclusions):
                return False
            for k, other in enumerate(slots):
                if k in (i, j):
                    continue
                if other["day_idx"] == target["day_idx"] and other["person"] == new_person:
                    return False
        return True
    return valid_swap




def per_person_rests(people, slots):
    """{person: [rest days between each pair of their consecutive tasks]}"""
    last_task = {}
    rests = {p: [] for p in people}
    for slot in sorted(slots, key=lambda s: s["day_idx"]):
        p = slot["person"]
        if p in last_task:
            rests[p].append(slot["day_idx"] - last_task[p] - 1)
        last_task[p] = slot["day_idx"]
    return rests


def rest_balance_spread(people, slots):
    """Spread (max-min) of each person's AVERAGE rest gap. Shared by
    rest_polish_score, print_metrics, and winner-selection - one
    implementation, so 'rest balance' means the same number everywhere
    it's used, including in the ranking that actually picks a winner."""
    avgs = [sum(rs) / len(rs) for rs in per_person_rests(people, slots).values() if rs]
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
                                 calendar, weekday, baseline_fairness, baseline_per_task, baseline_structural,
                                 carry_over_state=None, exclusions=None):
    """Yields every valid, safety-checked neighbor state reachable from
    `state` in one move (person-swap or day-shift), each scored. Used by beam
    search - the caller decides how many of these to keep, not this function.
    A generator, so only the kept ones stay in memory (a round can produce
    thousands of full-schedule copies).

    carry_over_state: the PREVIOUS RUN's schedule_state.json data (rest/phase/
    fairness), passed straight through to the structural check so it uses
    the SAME phase-adjusted windows as the baseline it's being compared
    against - not to be confused with `state` above, which is this
    function's own beam-search candidate (a schedule), not carry-over data."""
    n = len(state)
    total_days = len(calendar)
    chore_groups_by_idx = {i: g for i, g in enumerate(chore_groups)}
    valid_swap = _make_valid_swap_fn(state, days_off, exclusions)

    def safety_ok(candidate, days_changed):
        m = evaluate(people, chore_groups, candidate, exclusions)
        if m["fairness_spread"] > baseline_fairness or m["total_per_task_spread"] > baseline_per_task:
            return False
        # A person-swap keeps every occurrence day, so frequency/cadence/
        # piggyback can't change, and valid_swap already rules out days-off
        # and exclusion hits - it can never add a structural violation.
        # Skipping the re-check there halves polish time.
        if days_changed and count_structural_violations(
                candidate, chore_groups, days_off, calendar, weekday,
                state=carry_over_state, exclusions=exclusions) > baseline_structural:
            return False
        return True

    # --- move type 1: person-swap ---
    for i in range(n):
        for j in range(i + 1, n):
            if state[i]["person"] == state[j]["person"] or not valid_swap(i, j):
                continue
            candidate = [dict(s) for s in state]
            candidate[i]["person"], candidate[j]["person"] = candidate[j]["person"], candidate[i]["person"]
            if safety_ok(candidate, days_changed=False):
                score = rest_polish_score(people, chore_groups, candidate, buffer_days_target)
                yield score, candidate

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
            if safety_ok(candidate, days_changed=True):
                score = rest_polish_score(people, chore_groups, candidate, buffer_days_target)
                yield score, candidate


def polish_schedule(people, chore_groups, days_off, slots, buffer_days_target, calendar, weekday,
                     beam_width=6, max_rounds=60, patience=10, carry_over_state=None, exclusions=None):
    """BEAM SEARCH, not pure greedy hill-climbing: keeps the top `beam_width`
    candidate states each round (not just the single best move), expands ALL
    of them, then prunes back down. This is the tractable, principled version
    of "search more broadly than one path" - true brute-force over every
    permutation is computationally impossible at this scale (~47 slots, 5
    people is already ~5^47 states), but beam search genuinely escapes the
    classic greedy trap: a move that looks slightly worse now but opens a
    much better state next round survives, instead of being discarded
    immediately the way single-path hill-climbing would discard it.

    Two move types: person-swap (WHO, never WHEN) and day-shift (WHEN, only
    within a chore group's own tolerance_days - MILP already uses that
    tolerance in its core solve, but the heuristics don't, so this is where
    they get to use it). Both moves are gated identically: never accepted if they
    increase structural violations (frequency/cadence/piggyback/days-off) or
    make fairness worse than the schedule this pass started from.

    Stops early if the best-ever score hasn't improved in `patience` rounds -
    beam search costs beam_width times more per round than plain
    hill-climbing, so this keeps runtime sane without sacrificing the search
    breadth that matters."""
    base = [dict(s) for s in slots]
    baseline = evaluate(people, chore_groups, base, exclusions)
    baseline_fairness = baseline["fairness_spread"]
    baseline_per_task = baseline["total_per_task_spread"]
    baseline_structural = count_structural_violations(base, chore_groups, days_off, calendar, weekday,
                                                        state=carry_over_state, exclusions=exclusions)

    start_score = rest_polish_score(people, chore_groups, base, buffer_days_target)
    beam = [(start_score, base)]
    best_score, best_slots = start_score, base
    # every state in the beam after round r is exactly r moves from `base`,
    # so the returned schedule's move count is the round it was found in
    # (counting rounds searched instead over-reported, e.g. 10 "moves" for
    # a schedule returned unchanged)
    moves_made = 0
    rounds_since_improvement = 0

    for round_no in range(1, max_rounds + 1):
        all_candidates = itertools.chain.from_iterable(
            _generate_polish_neighbors(
                people, chore_groups, days_off, state, buffer_days_target,
                calendar, weekday, baseline_fairness, baseline_per_task, baseline_structural,
                carry_over_state=carry_over_state, exclusions=exclusions)
            for _, state in beam)
        # same result as sorted(...)[:beam_width], ties included, without
        # holding every candidate in memory
        beam = heapq.nsmallest(beam_width, all_candidates, key=lambda t: t[0])
        if not beam:
            break

        if beam[0][0] < best_score:
            best_score, best_slots = beam[0]
            moves_made = round_no
            rounds_since_improvement = 0
        else:
            rounds_since_improvement += 1
            if rounds_since_improvement >= patience:
                break

    return best_slots, moves_made




def algo_tabu_search(people, chore_groups, days_off, calendar, weekday,
                      seed_slots, iterations=20000, tabu_tenure=15, seed=42, sample_size=40,
                      exclusions=None):
    """Unlike SA (which sometimes accepts worse moves via temperature), Tabu
    Search always takes the BEST available neighbor - but bans reversing any
    of the last `tabu_tenure` moves, forcing it to explore instead of
    oscillating between the same two states. Aspiration: a tabu move is still
    taken if it beats the best solution found so far."""
    rng = random.Random(seed)
    slots = [dict(s) for s in seed_slots]
    n = len(slots)
    score = _make_score_fn(people, chore_groups, exclusions)
    valid_swap = _make_valid_swap_fn(slots, days_off, exclusions)

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
                  seed_slots, generations=1500, population_size=30, seed=42, exclusions=None):
    """Evolves a POPULATION of candidate person-assignments (occurrence days
    stay fixed from the seed) via crossover + mutation, unlike SA/Tabu which
    walk a single solution. Invalid children (same-day conflicts, days-off,
    exclusions) are repaired by falling back to a valid random swap."""
    rng = random.Random(seed)
    n = len(seed_slots)
    score = _make_score_fn(people, chore_groups, exclusions)

    def random_individual():
        ind = [dict(s) for s in seed_slots]
        valid_swap = _make_valid_swap_fn(ind, days_off, exclusions)
        for _ in range(n):
            i, j = rng.sample(range(n), 2)
            if ind[i]["person"] != ind[j]["person"] and valid_swap(i, j):
                ind[i]["person"], ind[j]["person"] = ind[j]["person"], ind[i]["person"]
        return ind

    def crossover(a, b):
        child = [dict(a[k]) for k in range(n)]
        valid_swap = _make_valid_swap_fn(child, days_off, exclusions)
        for k in range(n):
            if rng.random() < 0.5 and b[k]["person"] != child[k]["person"]:
                j = next((idx for idx in range(n) if child[idx]["person"] == b[k]["person"]
                          and child[idx]["day_idx"] != child[k]["day_idx"]), None)
                if j is not None and valid_swap(k, j):
                    child[k]["person"], child[j]["person"] = child[j]["person"], child[k]["person"]
        return child

    def mutate(ind):
        valid_swap = _make_valid_swap_fn(ind, days_off, exclusions)
        i, j = rng.sample(range(n), 2)
        if ind[i]["person"] != ind[j]["person"] and valid_swap(i, j):
            ind[i]["person"], ind[j]["person"] = ind[j]["person"], ind[i]["person"]
        return ind

    # population entries are (score, individual): individuals are never
    # mutated once scored (crossover/mutate work on fresh copies), so each
    # score is computed once instead of on every sort and tournament
    def fitness(entry): return entry[0]

    population = [(score(ind), ind) for ind in (random_individual() for _ in range(population_size))]
    best_score, best_slots = min(population, key=fitness)

    for gen in range(generations):
        ranked = sorted(population, key=fitness)
        if ranked[0][0] < best_score:
            best_score = ranked[0][0]
            best_slots = [dict(s) for s in ranked[0][1]]

        # tournament selection + crossover + mutation -> next generation
        next_gen = ranked[:2]  # elitism: keep the 2 best unchanged
        while len(next_gen) < population_size:
            t1 = min(rng.sample(ranked, 4), key=fitness)[1]
            t2 = min(rng.sample(ranked, 4), key=fitness)[1]
            child = crossover(t1, t2)
            if rng.random() < 0.2:
                child = mutate(child)
            next_gen.append((score(child), child))
        population = next_gen

    return best_slots, f"genetic ({generations} generations, pop={population_size})"




def algo_daily_hungarian(people, chore_groups, days_off, calendar, weekday, exclusions=None):
    """Same day-choice logic as greedy (WHEN each chore fires), but the person
    assignment for a day's tasks is solved as an exact bipartite MINIMUM COST
    MATCHING (Hungarian algorithm) across ALL of that day's tasks at once,
    instead of greedy's one-task-at-a-time priority pick. This can find a
    better joint assignment on days with multiple simultaneous tasks."""
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
                    candidates = [p for p in people
                                  if not is_person_off(p, calendar[d], weekday[d], days_off)
                                  and any(not is_person_excluded(p, t, exclusions) for t in g["tasks"])]
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
                if (is_person_off(p, calendar[d], weekday[d], days_off)
                        or is_person_excluded(p, task, exclusions)):
                    cost[ti, pi] = 1e6  # ineligible - matching avoids it unless nothing else exists
                    continue
                # same priority order as greedy above, expressed as costs:
                # clearing the rest buffer dominates, then TOTAL workload,
                # then this specific chore, then a small nudge toward whoever
                # is most rested. The weights used to run the other way
                # (rest 10, per-chore 5, total 1), which is what left people
                # excluded from the daily chore several tasks short.
                rest = (d - last_task[p] - 1) if last_task[p] is not None else 999
                cost[ti, pi] = ((0 if rest >= chore_groups[g_idx]["buffer_days"] else 1000)
                                + task_counts[p] * 20
                                + per_task_counts[task][p] * 3
                                - min(rest, 30) * 0.1)

        # rectangular matching: each person gets at most one task today. If a
        # day ever has MORE tasks than people, the extra tasks come back
        # unmatched and go through the fallback below instead of vanishing.
        row_ind, col_ind = linear_sum_assignment(cost)
        matched = dict(zip(row_ind, col_ind))
        assigned_today = set()
        for ti, (g_idx, task) in enumerate(due_tasks):
            pi = matched.get(ti)
            person = people[pi] if pi is not None else None
            if person is None or person in assigned_today or cost[ti, pi] >= 1e6:
                # fallback: pick best remaining eligible person not yet used today
                remaining = [p for p in people if p not in assigned_today
                             and not is_person_off(p, calendar[d], weekday[d], days_off)
                             and not is_person_excluded(p, task, exclusions)]
                if remaining:
                    person = max(remaining, key=lambda p: (d - last_task[p]) if last_task[p] is not None else 9999)
                else:
                    # last resort: relax days-off before exclusions, the same
                    # precedence greedy uses for its forced pick
                    person = next((p for p in people if not is_person_excluded(p, task, exclusions)), people[0])
            active_slots.append({"date": calendar[d], "day": weekday[d], "task": task,
                                 "day_idx": d, "group_idx": g_idx, "person": person})
            last_task[person] = d
            task_counts[person] += 1
            per_task_counts[task][person] += 1
            assigned_today.add(person)

    return active_slots, "daily Hungarian assignment (exact per-day matching)"




def check_structure(active_slots, chore_groups, days_off, calendar, weekday, state=None, exclusions=None):
    """The single implementation of the NON-NEGOTIABLE structural rules
    (frequency, cadence, piggyback, days-off, exclusions) - unlike buffer,
    there's no 'soft' version of these. A candidate that breaks one is
    WRONG, regardless of how good its other metrics look.

    count_structural_violations (ranking, polish safety gate) and
    validate_schedule (the printed audit) both read from this. They used to
    be two hand-kept copies of the same checks, and drifting apart is
    exactly how the carry-over bug below slipped through once.

    state (optional): if given, checks are carry-over AWARE - using the
    SAME phase-adjusted windows algo_milp uses internally, and checking the
    gap against the previous run's actual last occurrence, not just gaps
    within this run alone. Without this, a candidate that ignores carry-over
    entirely (most non-MILP algorithms do) would incorrectly show 0
    violations, and MILP's correct, deliberately-delayed first occurrence
    would incorrectly show a violation - exactly backwards from reality.

    Returns a dict:
      frequency: per non-piggyback group - windows, occurrences, bad_windows,
                 deferred_window, phase_block, bad_gaps (date1, date2, gap)
      piggyback: per piggyback group - expected/actual days, violations
      days_off / excluded: the offending slots"""
    total_days = len(calendar)
    start_day = calendar[0]
    chore_groups_by_name = {g["name"]: g for g in chore_groups}
    group_phase_block = compute_group_phase_blocks(chore_groups, state, start_day)
    group_phase_deadline = compute_group_phase_deadlines(chore_groups, state, start_day)
    occ_by_group = {g["name"]: sorted({s["day_idx"] for s in active_slots
                                        if chore_groups[s["group_idx"]]["name"] == g["name"]})
                    for g in chore_groups}

    frequency = []
    for g in chore_groups:
        if "piggyback_on" in g:
            continue
        pb = group_phase_block.get(g["name"], 0)
        pd = group_phase_deadline.get(g["name"])
        windows, _, _ = resolve_group_windows(g, chore_groups_by_name, total_days, phase_block=pb, phase_deadline=pd)
        occ = occ_by_group[g["name"]]
        occ_set = set(occ)

        # --- every window fires exactly once. A trailing partial window
        # (schedule length not a multiple of the frequency) may be skipped -
        # it rolls into the next run's phase carry-over - but never doubled ---
        bad_windows, deferred_window = [], None
        for w_idx, w in enumerate(windows):
            is_trailing_partial = (w_idx == len(windows) - 1 and len(windows) > 1
                                    and len(w) < g["frequency_days"])
            count = len(occ_set & set(w))
            if is_trailing_partial and count == 0:
                deferred_window = w
            elif (count > 1) if is_trailing_partial else (count != 1):
                bad_windows.append(w)

        # --- cadence: consecutive occurrences stay close to frequency_days
        # apart, not just "one per independent window" - catches e.g. two
        # Stove visits 12 days apart when freq=7. tolerance_days relaxes the
        # minimum acceptable gap. ---
        tol = g.get("tolerance_days", 0)
        min_gap = max(1, g["frequency_days"] - tol)
        max_gap = 2 * g["frequency_days"] - 1 + tol
        bad_gaps = [(calendar[a].isoformat(), calendar[b].isoformat(), b - a)
                    for a, b in zip(occ, occ[1:]) if not min_gap <= b - a <= max_gap]

        # --- boundary: gap from the PREVIOUS run's actual last occurrence
        # to this run's first one - checked BOTH directions. Too close: a
        # phase-blind algorithm firing again right away (e.g. SweepTrash on
        # Aug 16, then Aug 17). Too far: the phase-block only enforces "not
        # due before X" - nothing stops the solver drifting to the far end of
        # that window (e.g. last on Aug 9, next on Aug 25 - 16 days when the
        # rule is "every 10 +-1"). ---
        if state and "group_phase" in state and occ:
            last_date = state["group_phase"].get(g["name"])
            if last_date is not None:
                boundary_gap = (calendar[occ[0]] - last_date).days
                if not min_gap <= boundary_gap <= max_gap:
                    bad_gaps.append((last_date.isoformat() + " (previous run)",
                                     calendar[occ[0]].isoformat(), boundary_gap))

        frequency.append({"group": g, "windows": windows, "occurrences": occ, "phase_block": pb,
                          "bad_windows": bad_windows, "deferred_window": deferred_window,
                          "bad_gaps": bad_gaps})

    # --- piggyback: every piggyback occurrence lands on (or within
    # tolerance_days of) its host's every-Nth occurrence day ---
    piggyback = []
    for g in chore_groups:
        if "piggyback_on" not in g:
            continue
        host_occ = occ_by_group[g["piggyback_on"]]
        expected = [d for i, d in enumerate(host_occ) if (i + 1) % g["every_nth"] == 0]
        actual = occ_by_group[g["name"]]
        tol = g.get("tolerance_days", 0)
        if len(actual) != len(expected):
            violations = 1
        else:
            violations = sum(1 for a, e in zip(actual, expected) if abs(a - e) > tol)
        piggyback.append({"group": g, "expected": expected, "actual": actual, "violations": violations})

    return {
        "frequency": frequency,
        "piggyback": piggyback,
        "days_off": [s for s in active_slots if is_person_off(s["person"], s["date"], s["day"], days_off)],
        "excluded": [s for s in active_slots if is_person_excluded(s["person"], s["task"], exclusions)],
    }


def count_structural_violations(active_slots, chore_groups, days_off, calendar, weekday, state=None,
                                  exclusions=None):
    """Silent tally of check_structure, for ranking candidates and gating polish moves."""
    r = check_structure(active_slots, chore_groups, days_off, calendar, weekday, state=state, exclusions=exclusions)
    return (sum(len(f["bad_windows"]) + len(f["bad_gaps"]) for f in r["frequency"])
            + sum(p["violations"] for p in r["piggyback"])
            + len(r["days_off"]) + len(r["excluded"]))
