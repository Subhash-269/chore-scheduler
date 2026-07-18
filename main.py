"""
main.py - orchestration only. Loads config, runs every algorithm from
optimizer.py, polishes and reports via scheduler.py, picks a winner, and
exports the result. Run this file: `python main.py`
"""
import time
import datetime

from optimizer import (
    algo_milp, algo_greedy, algo_simulated_annealing, algo_tabu_search,
    algo_genetic, algo_daily_hungarian, evaluate, count_structural_violations,
    rest_balance_spread,
)
from scheduler import (
    load_config, build_calendar, load_state, save_state, polish_and_report,
    print_metrics, print_schedule, print_task_breakdown, print_person_summary,
    validate_schedule, export_csv, export_docx, export_pdf,
    diagnose_milp_infeasibility,
)


if __name__ == "__main__":
    cfg = load_config("config.yml")
    roommates = cfg["roommates"]
    chore_groups = cfg["chore_groups"]
    days_off = cfg["days_off"]
    start_day = datetime.datetime.strptime(cfg["start_day"], "%Y-%m-%d").date()
    total_days = cfg["weeks_to_plan"] * 7
    calendar, weekday = build_calendar(start_day, total_days)

    prev_state = load_state("schedule_state.json")
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

    t0 = time.time()
    milp_slots, milp_note, forced_violations, cadence_violations = algo_milp(
        roommates, chore_groups, days_off, calendar, weekday, state=prev_state)
    print_metrics("Algorithm 1: MILP (HiGHS, exact)", milp_slots, roommates, chore_groups, time.time() - t0, milp_note)
    if milp_slots is None and prev_state:
        diagnose_milp_infeasibility(roommates, chore_groups, days_off, calendar, weekday, prev_state)
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

    t0 = time.time()
    greedy_slots, greedy_note = algo_greedy(roommates, chore_groups, days_off, calendar, weekday)
    print_metrics("Algorithm 2: Greedy heuristic", greedy_slots, roommates, chore_groups, time.time() - t0, greedy_note)
    greedy_slots = polish_and_report("Greedy", greedy_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    t0 = time.time()
    sa_seed = greedy_slots if greedy_slots else []
    sa_slots, sa_note = algo_simulated_annealing(roommates, chore_groups, days_off, calendar, weekday, sa_seed)
    print_metrics("Algorithm 3: Simulated Annealing", sa_slots, roommates, chore_groups, time.time() - t0, sa_note)
    sa_slots = polish_and_report("SA", sa_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    t0 = time.time()
    tabu_slots, tabu_note = algo_tabu_search(roommates, chore_groups, days_off, calendar, weekday, sa_seed)
    print_metrics("Algorithm 4: Tabu Search", tabu_slots, roommates, chore_groups, time.time() - t0, tabu_note)
    tabu_slots = polish_and_report("Tabu", tabu_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    t0 = time.time()
    ga_slots, ga_note = algo_genetic(roommates, chore_groups, days_off, calendar, weekday, sa_seed)
    print_metrics("Algorithm 5: Genetic Algorithm", ga_slots, roommates, chore_groups, time.time() - t0, ga_note)
    ga_slots = polish_and_report("GA", ga_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    t0 = time.time()
    hungarian_slots, hungarian_note = algo_daily_hungarian(roommates, chore_groups, days_off, calendar, weekday)
    print_metrics("Algorithm 6: Daily Hungarian Assignment", hungarian_slots, roommates, chore_groups, time.time() - t0, hungarian_note)
    hungarian_slots = polish_and_report("Hungarian", hungarian_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    if milp_slots is not None:
        milp_slots = polish_and_report("MILP", milp_slots, roommates, chore_groups, days_off, calendar, weekday, cfg["buffer_days"])

    print("\n" + "=" * 70)
    print(" Pick the one whose metrics you like best. MILP is the only one with a")
    print(" mathematical GUARANTEE - the other two are best-effort and may show")
    print(" buffer_violations > 0 if the config is tight.")
    print("=" * 70)

    # --- pick a winner: structural correctness is NON-NEGOTIABLE and ranks
    # first (frequency/cadence/piggyback/days-off - greedy/SA can silently
    # break these since they don't understand piggyback or carry-over state).
    # Only among structurally-correct candidates do buffer violations and
    # fairness spread act as tiebreakers. ---
    candidates = [
        ("Algorithm 1: MILP (HiGHS, exact)", milp_slots),
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
        m = evaluate(roommates, chore_groups, slots)
        structural = count_structural_violations(slots, chore_groups, days_off, calendar, weekday)
        rest_spread = rest_balance_spread(roommates, slots)
        scored.append((structural, m["buffer_violations"], rest_spread,
                       m["total_per_task_spread"], m["fairness_spread"], name, slots))
    # ranked: structural correctness first (non-negotiable), then fewest buffer
    # violations, then REST BALANCE ACROSS PEOPLE (this used to be missing
    # entirely from the ranking - a candidate could win with the worst rest
    # spread of the bunch just by tying on buffer violations and winning a
    # later tiebreaker that has nothing to do with rest), then the remaining
    # fairness dimensions.
    scored.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))

    def show_schedule(idx):
        (structural, violations, rest_spread, per_task_spread, fairness_spread, name, slots) = scored[idx]
        print(f"\n✅ Viewing: {name}  "
              f"(structural violations={structural}, buffer violations={violations}, "
              f"rest balance spread={rest_spread:.2f}, "
              f"per-chore spread={per_task_spread}, overall fairness spread={fairness_spread})")
        if structural > 0:
            print(f"   ⚠️  Every candidate had structural violations - this one had the fewest ({structural}).")
            print(f"      Structural rules (frequency/cadence/piggyback/days-off) should be zero -")
            print(f"      see the validation report below for exactly what's wrong.")
        print_schedule(name, slots, chore_groups)
        print_task_breakdown(slots, chore_groups)
        print_person_summary(slots, roommates)
        validate_schedule(slots, chore_groups, days_off, calendar, weekday)

    current_idx = 0
    show_schedule(current_idx)

    while True:
        print("\n" + "=" * 70)
        print(" SWITCH SCHEDULES, EXPORT, OR QUIT")
        print("=" * 70)
        for i, (structural, violations, rest_spread, per_task_spread, fairness_spread, name, _) in enumerate(scored, 1):
            tags = []
            if i - 1 == current_idx:
                tags.append("currently viewing")
            if i == 1:
                tags.append("recommended")
            flag = f"  <- {', '.join(tags)}" if tags else ""
            print(f"  [{i}] {name}")
            print(f"      structural={structural}, buffer violations={violations}, "
                  f"rest balance spread={rest_spread:.2f}, per-chore spread={per_task_spread}, "
                  f"fairness spread={fairness_spread}{flag}")
        choice = input(f"\nEnter a number to view [1-{len(scored)}], [E]xport this one (default), or [Q]uit: ").strip().lower()

        if choice in ("e", "export", ""):
            break
        if choice in ("q", "quit"):
            print("Exiting without saving or exporting anything.")
            raise SystemExit(0)
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(scored)):
                raise ValueError
        except ValueError:
            print("   Not a valid choice - try a number from the list, 'e', or 'q'.")
            continue
        current_idx = idx
        show_schedule(current_idx)

    (winner_structural, winner_violations, winner_rest_spread,
     winner_per_task_spread, winner_spread, winner_name, winner_slots) = scored[current_idx]
    print(f"\n✅ Exporting: {winner_name}")

    state_path = save_state(winner_slots, roommates, chore_groups)
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
        docx_path = export_docx(winner_slots)
        print(f"✅ DOCX saved to: {docx_path}")
    except ImportError:
        print("🚨 DOCX export skipped - run: pip install python-docx --break-system-packages")
    except Exception as e:
        print(f"🚨 DOCX export failed: {e}")

    save_pdf = input("\nSave this schedule as a PDF? [Y/n]: ").strip().lower()
    if save_pdf in ("", "y", "yes"):
        try:
            pdf_path = export_pdf(winner_slots, chore_groups, roommates)
            print(f"✅ PDF  saved to: {pdf_path}")
        except ImportError:
            print("🚨 PDF export skipped - run: pip install reportlab --break-system-packages")
        except Exception as e:
            print(f"🚨 PDF export failed: {e}")
    else:
        print("   Skipped PDF export.")
    print("=" * 70)