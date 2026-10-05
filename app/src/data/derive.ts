import { weekdayName } from './dates';
import type { Household, Slot, TaskStatus } from './types';

export function isOff(h: Household | null, person: string, date: string): boolean {
  const entries = h?.days_off?.[person] ?? [];
  return entries.includes(weekdayName(date)) || entries.includes(date);
}

/** How many sessions are done / missed, for the strike segments. */
export function strikeCounts(status: TaskStatus | undefined, n: number): { done: number; missed: number } {
  if (!status) return { done: 0, missed: 0 };
  if (status.sessions && n > 1) {
    return {
      done: status.sessions.filter((s) => s === 'done').length,
      missed: status.sessions.filter((s) => s === 'missed').length,
    };
  }
  if (status.state === 'done' || status.state === 'covered') return { done: n, missed: 0 };
  if (status.state === 'missed') return { done: 0, missed: n };
  return { done: 0, missed: 0 };
}

export function isFinished(status: TaskStatus | undefined, n: number): boolean {
  const { done, missed } = strikeCounts(status, n);
  return status?.state === 'skipped' || done + missed >= n;
}

export function byDate(slots: Slot[]): Record<string, Slot[]> {
  const out: Record<string, Slot[]> = {};
  for (const s of slots) (out[s.date] ??= []).push(s);
  return out;
}

/** Average count per eligible person, for "share of each chore". */
export function eligibleAverage(h: Household, task: string, counts: Record<string, number>): number {
  const group = h.chore_groups.find((g) => g.tasks.includes(task));
  const eligible = h.roommates.filter((p) => {
    const ex = h.exclusions?.[p] ?? [];
    return !ex.includes(task) && !(group && ex.includes(group.name));
  });
  if (!eligible.length) return 0;
  return eligible.reduce((sum, p) => sum + (counts[p] ?? 0), 0) / eligible.length;
}

export function isExcluded(h: Household, person: string, task: string): boolean {
  const ex = h.exclusions?.[person] ?? [];
  const group = h.chore_groups.find((g) => g.tasks.includes(task));
  return ex.includes(task) || !!(group && ex.includes(group.name));
}

/** Short name for grid row headers. */
export function shortName(name: string) {
  return name.length <= 4 ? name : name.slice(0, 3);
}
