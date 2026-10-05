import { todayIso } from './dates';
import type { ChoreGroup, Household } from './types';

export type Preset = ChoreGroup & { on: boolean; hint: string };

/** Starting chores for onboarding - the same shapes config_example.yml uses. */
export const CHORE_PRESETS: Preset[] = [
  { name: 'Dishwashing', tasks: ['Dishes'], frequency_days: 1, on: true, hint: 'every day' },
  { name: 'Trash', tasks: ['Trash'], frequency_days: 7, tolerance_days: 1, on: true, hint: 'weekly, ±1 day' },
  { name: 'Vacuum', tasks: ['Vacuum'], frequency_days: 3, tolerance_days: 1, on: true, hint: 'every 3 days, ±1' },
  { name: 'Mop', tasks: ['Mop'], piggyback_on: 'Vacuum', every_nth: 2, tolerance_days: 1, on: true, hint: 'with every 2nd vacuum' },
  { name: 'Bathroom', tasks: ['Bathroom'], frequency_days: 7, tolerance_days: 1, on: false, hint: 'weekly, ±1 day' },
  { name: 'Stove', tasks: ['Stove'], frequency_days: 10, tolerance_days: 1, on: false, hint: 'every 10 days' },
];

/** Solo starting chores, with rough minutes so no day gets heavy. */
export const SOLO_PRESETS: Preset[] = [
  { name: 'Dishes', tasks: ['Dishes'], frequency_days: 1, minutes: 15, on: true, hint: 'every day' },
  { name: 'Vacuum', tasks: ['Vacuum'], frequency_days: 3, tolerance_days: 1, minutes: 20, on: true, hint: 'every 3 days, ±1' },
  { name: 'Laundry', tasks: ['Laundry'], frequency_days: 7, minutes: 40, on: true, hint: 'weekly' },
  { name: 'Bathroom', tasks: ['Bathroom'], frequency_days: 7, tolerance_days: 1, minutes: 30, on: true, hint: 'weekly, ±1 day' },
  { name: 'Trash', tasks: ['Trash'], frequency_days: 7, tolerance_days: 1, minutes: 5, on: true, hint: 'weekly, ±1 day' },
  { name: 'Plants', tasks: ['Plants'], frequency_days: 3, tolerance_days: 1, minutes: 5, on: false, hint: 'every 3 days' },
];

export function emptySoloHousehold(name: string): Household {
  return {
    mode: 'solo',
    roommates: [name],
    colors: {},
    buffer_days: 0,
    chore_groups: SOLO_PRESETS.filter((p) => p.on).map(({ on, hint, ...g }) => g),
    days_off: {},
    exclusions: {},
    random_seed: 42,
    start_day: todayIso(),
    weeks_to_plan: 4,
    daily_cap_minutes: 60,
    busy_days: [],
    busy_cap_minutes: 15,
  };
}

export function emptyHousehold(): Household {
  return {
    mode: 'household',
    roommates: [],
    colors: {},
    buffer_days: 2,
    chore_groups: CHORE_PRESETS.filter((p) => p.on).map(({ on, hint, ...g }) => g),
    days_off: {},
    exclusions: {},
    random_seed: 42,
    start_day: todayIso(),
    weeks_to_plan: 4,
  };
}

/** "every 3d ±1", "2nd vacuum", "1d" - the compact rule label used across the app. */
export function ruleLabel(g: ChoreGroup): string {
  if (g.piggyback_on) return `${ordinal(g.every_nth ?? 1)} ${g.piggyback_on.toLowerCase()}`;
  const tol = g.tolerance_days ? ` ±${g.tolerance_days}` : '';
  return `${g.frequency_days ?? 1}d${tol}`;
}

export function ordinal(n: number): string {
  return n === 1 ? 'every' : n === 2 ? '2nd' : n === 3 ? '3rd' : `${n}th`;
}
