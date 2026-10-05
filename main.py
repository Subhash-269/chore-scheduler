"""
main.py - orchestration only. Loads config, runs every algorithm from
optimizer.py, polishes and reports via scheduler.py, picks a winner, and
exports the result. Run this file: `python main.py`
"""
import time
import datetime
import random

from optimizer import (
    algo_milp, algo_greedy, algo_simulated_annealing, algo_tabu_search,
    algo_genetic, algo_daily_hungarian, evaluate, count_structural_violations,
    rest_balance_spread,
)
from scheduler import (
    load_config, build_calendar, load_state, save_state, polish_and_report,
    check_state_freshness,
    print_metrics, print_schedule, print_task_breakdown, print_person_summary,
    validate_schedule, export_csv, export_docx, export_pdf,
    diagnose_milp_infeasibility,
)


def main():
    cfg = load_config("config.yml")
    roommates = cfg["roommates"]
    chore_groups = cfg["chore_groups"]
    days_off = cfg["days_off"]
    exclusions = cfg["exclusions"]
    start_day = datetime.datetime.strptime(cfg["start_day"], "%Y-%m-%d").date()
    total_days = cfg["weeks_to_plan"] * 7
    calendar, weekday = build_calendar(start_day, total_days)

    # --- randomized roommate order ------------------------------------
    # List order is a real tie-breaker, not cosmetics: among equally-optimal
    # schedules, MILP's variable order and greedy/Hungarian's max()/argmax()
    # all resolve ties toward whoever appears first, so a fixed order quietly
    # favours the same people every month (measured: it decides who lands on
    # 9 tasks instead of 10). Shuffling rotates that. Reports and exports
    # keep the config order, so runs stay comparable side by side.
    seed_setting = cfg["random_seed"]
    run_seed = random.randrange(1, 2 ** 31 - 1) if seed_setting == "auto" else seed_setting
    solver_order = list(roommates)
    random.Random(run_seed).shuffle(solver_order)

    prev_state = check_state_freshness(load_state("schedule_state.json"), start_day)
    if prev_state:
        print("=" * 70)
        print(" CONTINUING FROM PREVIOUS RUN")
        print("=" * 70)
        print(" Found schedule_state.json - carrying over rest owed, chore phase,")
        print(" and cumulative fairness from the last run.")
        print("=" * 70)

    print("=" * 70)
    print(f" COMPARING 6 SCHEDULING ALGORITHMS - same config, {cfg['weeks_to_plan']} weeks, {len(roommates)} people")
    print("=" * 70)
    configured_exclusions = {p: sorted(ts) for p, ts in exclusions.items() if ts}
    if configured_exclusions:
        print(" CHORE EXCLUSIONS IN FORCE (these people never get these chores):")
        for p, tasks in configured_exclusions.items():
            print(f"   - {p}: {', '.join(tasks)}")
        print("=" * 70)
    print(f" Roommate order shuffled with seed {run_seed}"
          + (' (random_seed: auto - recorded in schedule_state.json)' if seed_setting == "auto"
             else " (random_seed from config.yml)"))
    print(f"   {' -> '.join(solver_order)}")
    print("=" * 70)

    def polish(short_name, slots):
        return polish_and_report(short_name, slots, solver_order, chore_groups, days_off, calendar, weekday,
                                 cfg["buffer_days"], state=prev_state, exclusions=exclusions)

    def run_heuristic(label, short_name, algo, *seed_slots):
        """Time one heuristic, report its raw result, then polish it."""
        t0 = time.time()
        slots, note = algo(solver_order, chore_groups, days_off, calendar, weekday, *seed_slots,
                           exclusions=exclusions)
        print_metrics(label, slots, roommates, chore_groups, time.time() - t0, note, exclusions=exclusions)
        return polish(short_name, slots)

    milp_label = "Algorithm 1: MILP (HiGHS, exact)"
    t0 = time.time()
    milp_slots, milp_note, forced_violations, cadence_violations = algo_milp(
        solver_order, chore_groups, days_off, calendar, weekday, state=prev_state, exclusions=exclusions)
    print_metrics(milp_label, milp_slots, roommates, chore_groups, time.time() - t0, milp_note,
                  exclusions=exclusions)
    if milp_slots is None and prev_state:
        diagnose_milp_infeasibility(solver_order, chore_groups, days_off, calendar, weekday, prev_state,
                                    exclusions=exclusions)
    if forced_violations:
        print(f"   ⚠️  {len(forced_violations)} buffer exception(s) were UNAVOIDABLE given your exact")
        print(f"      days-off + frequencies - here is exactly where and why:")
        for v in forced_violations:
            print(f"      - {v['person']}: {v['task1']} on {v['date1']} -> {v['task2']} on {v['date2']}"
                  f"  (only {v['gap']-1} rest day(s), needed more - no valid alternative existed)")
    if cadence_violations:
        print(f"   ⚠️  {len(cadence_violations)} cadence exception(s) were UNAVOIDABLE (usually only")
        print(f"      when continuing from a previous run's carried-over phase):")
        for v in cadence_violations:
            print(f"      - {v['group']}: {v['date1']} -> {v['date2']} (only {v['gap']} days apart, "
                  f"expected roughly the chore's own frequency)")
    milp_slots = polish("MILP", milp_slots)

    greedy_slots = run_heuristic("Algorithm 2: Greedy heuristic", "Greedy", algo_greedy)
    # SA, Tabu and GA only re-decide WHO does each task, so they start from
    # greedy's (polished) occurrence days
    seed_slots = greedy_slots or []
    sa_slots = run_heuristic("Algorithm 3: Simulated Annealing", "SA", algo_simulated_annealing, seed_slots)
    tabu_slots = run_heuristic("Algorithm 4: Tabu Search", "Tabu", algo_tabu_search, seed_slots)
    ga_slots = run_heuristic("Algorithm 5: Genetic Algorithm", "GA", algo_genetic, seed_slots)
    hungarian_slots = run_heuristic("Algorithm 6: Daily Hungarian Assignment", "Hungarian", algo_daily_hungarian)

    print("\n" + "=" * 70)
    print(" Pick the one whose metrics you like best. MILP is the only one with a")
    print(" mathematical GUARANTEE - the other five are best-effort and may show")
    print(" buffer or structural violations if the config is tight.")
    print("=" * 70)

    # --- pick a winner: structural correctness is NON-NEGOTIABLE and ranks
    # first (frequency/cadence/piggyback/days-off/exclusions - greedy/SA can
    # silently break these since they don't understand piggyback or
    # carry-over state). Only among structurally-correct candidates do buffer
    # violations and the fairness dimensions act as tiebreakers. ---
    candidates = [
        (milp_label, milp_slots),
        ("Algorithm 2: Greedy heuristic", greedy_slots),
        ("Algorithm 3: Simulated Annealing", sa_slots),
        ("Algorithm 4: Tabu Search", tabu_slots),
        ("Algorithm 5: Genetic Algorithm", ga_slots),
        ("Algorithm 6: Daily Hungarian Assignment", hungarian_slots),
    ]
    scored = []
    for name, slots in candidates:
        if slots is None:
            continue
        m = evaluate(roommates, chore_groups, slots, exclusions)
        structural = count_structural_violations(slots, chore_groups, days_off, calendar, weekday,
                                                 state=prev_state, exclusions=exclusions)
        rest_spread = rest_balance_spread(roommates, slots)
        scored.append((structural, m["buffer_violations"], m["fairness_spread"],
                       rest_spread, m["total_per_task_spread"], name, slots))
    # ranked in the SAME priority order algo_milp optimizes internally, so the
    # ranking can't overrule the solver's own trade-off: structural
    # correctness first (non-negotiable), then fewest buffer violations, then
    # TOTAL workload fairness, then rest balance across people, and per-chore
    # fairness last as the final tiebreaker.
    #
    # Total workload fairness used to sit dead last, behind per-chore spread,
    # which let a candidate with totals of 12,12,12,12,11,4,4 beat one with
    # 10,10,10,10,10,9,9 purely on per-chore evenness - the exact trade the
    # solver is now staged to refuse. Rest balance still outranks per-chore
    # fairness: it was added to this ranking precisely because a candidate
    # could otherwise win with the worst rest pattern of the bunch.
    scored.sort(key=lambda t: t[:5])

    def show_schedule(idx):
        (structural, violations, fairness_spread, rest_spread, per_task_spread, name, slots) = scored[idx]
        print(f"\n✅ Viewing: {name}  "
              f"(structural violations={structural}, buffer violations={violations}, "
              f"workload spread={fairness_spread}, rest balance spread={rest_spread:.2f}, "
              f"per-chore spread={per_task_spread})")
        if structural > 0:
            print(f"   ⚠️  Every candidate had structural violations - this one had the fewest ({structural}).")
            print(f"      Structural rules (frequency/cadence/piggyback/days-off) should be zero -")
            print(f"      see the validation report below for exactly what's wrong.")
        print_schedule(name, slots, chore_groups)
        print_task_breakdown(slots, chore_groups, roommates, exclusions)
        print_person_summary(slots, roommates)
        validate_schedule(slots, chore_groups, days_off, calendar, weekday, state=prev_state,
                          exclusions=exclusions)

    current_idx = 0
    show_schedule(current_idx)

    while True:
        print("\n" + "=" * 70)
        print(" SWITCH SCHEDULES, EXPORT, OR QUIT")
        print("=" * 70)
        for i, (structural, violations, fairness_spread, rest_spread, per_task_spread, name, _) in enumerate(scored, 1):
            tags = []
            if i - 1 == current_idx:
                tags.append("currently viewing")
            if i == 1:
                tags.append("recommended")
            flag = f"  <- {', '.join(tags)}" if tags else ""
            print(f"  [{i}] {name}")
            print(f"      structural={structural}, buffer violations={violations}, "
                  f"workload spread={fairness_spread}, rest balance spread={rest_spread:.2f}, "
                  f"per-chore spread={per_task_spread}{flag}")
        choice = input(f"\nEnter a number to view [1-{len(scored)}], [E]xport this one (default), or [Q]uit: ").strip().lower()

        if choice in ("e", "export", ""):
            break
        if choice in ("q", "quit"):
            print("Exiting without saving or exporting anything.")
            return
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(scored)):
                raise ValueError
        except ValueError:
            print("   Not a valid choice - try a number from the list, 'e', or 'q'.")
            continue
        current_idx = idx
        show_schedule(current_idx)

    winner_name, winner_slots = scored[current_idx][5:]
    print(f"\n✅ Exporting: {winner_name}")

    state_path = save_state(winner_slots, roommates, chore_groups, random_seed=run_seed)
    print("=" * 70)
    print(f" Saved {state_path} - next run will continue rest/phase/fairness from here.")
    print("=" * 70)

    print("=" * 70)
    print(" EXPORTING WINNING SCHEDULE")
    print("=" * 70)
    try:
        csv_path = export_csv(winner_slots)
        print(f"✅ CSV  saved to: {csv_path}")
    except Exception as e:
        print(f"🚨 CSV export failed: {e}")

    try:
        docx_path = export_docx(winner_slots, chore_groups, roommates)
        print(f"✅ DOCX saved to: {docx_path}")
    except ImportError:
        print("🚨 DOCX export skipped - run: pip install python-docx")
    except Exception as e:
        print(f"🚨 DOCX export failed: {e}")

    save_pdf = input("\nSave this schedule as a PDF? [Y/n]: ").strip().lower()
    if save_pdf in ("", "y", "yes"):
        try:
            pdf_path = export_pdf(winner_slots, chore_groups, roommates)
            print(f"✅ PDF  saved to: {pdf_path}")
        except ImportError:
            print("🚨 PDF export skipped - run: pip install reportlab")
        except Exception as e:
            print(f"🚨 PDF export failed: {e}")
    else:
        print("   Skipped PDF export.")
    print("=" * 70)


if __name__ == "__main__":
    main()
