/** Date helpers. Dates travel as local "YYYY-MM-DD" strings, like the server. */

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

export function iso(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

export function parse(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function todayIso(): string {
  return iso(new Date());
}

export function addDays(s: string, n: number): string {
  const d = parse(s);
  d.setDate(d.getDate() + n);
  return iso(d);
}

/** Monday of the week containing s. */
export function weekStart(s: string): string {
  const d = parse(s);
  const offset = (d.getDay() + 6) % 7;
  return addDays(s, -offset);
}

export function weekDates(start: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

export function weekdayName(s: string): string {
  return WEEKDAYS[(parse(s).getDay() + 6) % 7];
}

export const shortDay = (s: string) => weekdayName(s).slice(0, 3).toUpperCase();
export const dayNum = (s: string) => `${parse(s).getDate()}`;
export const monthLong = (s: string) => MONTHS_LONG[parse(s).getMonth()];

/** "Aug 10 – 16" or "Aug 31 – Sep 6" */
export function rangeLabel(start: string, end: string): string {
  const a = parse(start);
  const b = parse(end);
  const left = `${MONTHS[a.getMonth()]} ${a.getDate()}`;
  const right = a.getMonth() === b.getMonth() ? `${b.getDate()}` : `${MONTHS[b.getMonth()]} ${b.getDate()}`;
  return `${left} – ${right}`;
}

export function shortDate(s: string): string {
  const d = parse(s);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

export function daysBetween(a: string, b: string): number {
  return Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000);
}

/** Strip a leading emoji + space, e.g. "🧼 Dishes" -> "Dishes". */
export function plainTask(task: string): string {
  return task.replace(/^[^\p{L}\p{N}]+/u, '').trim() || task;
}

/** Short label for tight grid cells. */
export function shortTask(task: string): string {
  const t = plainTask(task);
  const known: Record<string, string> = { Dishes: 'Dish', Vacuum: 'Vac', Bathroom: 'Bath' };
  if (known[t]) return known[t];
  const first = t.split(/[\s/]/)[0];
  return first.length > 6 ? `${first.slice(0, 5)}.` : first;
}
