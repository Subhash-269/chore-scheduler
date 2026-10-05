/**
 * Design tokens - a direct port of the "minimal mono" mockups
 * (mockup/chore-scheduler-mockups-v2.html). Greyscale for everything,
 * colour only for people.
 */
export type Palette = {
  bg: string;
  s1: string;
  soft: string;
  line: string;
  line2: string;
  tx: string;
  tx2: string;
  tx3: string;
  ok: string;
  warn: string;
  bad: string;
  dim: string;
  /** today's column on the fridge board */
  todayCol: string;
};

export const light: Palette = {
  bg: '#fafafa',
  s1: '#ffffff',
  soft: '#f0f0f0',
  line: '#e8e8e8',
  line2: '#d2d2d2',
  tx: '#111111',
  tx2: '#666666',
  tx3: '#9a9a9a',
  ok: '#0f8a5f',
  warn: '#b45309',
  bad: '#c62f4b',
  dim: 'rgba(0,0,0,0.42)',
  todayCol: '#f3f3f3',
};

export const dark: Palette = {
  bg: '#0e0e0e',
  s1: '#171717',
  soft: '#1f1f1f',
  line: '#262626',
  line2: '#383838',
  tx: '#f2f2f2',
  tx2: '#a0a0a0',
  tx3: '#6b6b6b',
  ok: '#2fbf8a',
  warn: '#f0a43a',
  bad: '#ff6b81',
  dim: 'rgba(0,0,0,0.6)',
  todayCol: '#151515',
};

/** Person colours: [light, dark] pairs, handed out in roommate order. */
export const PERSON_COLORS: [string, string][] = [
  ['#3b5bdb', '#6b88ff'],
  ['#c2570c', '#e88a3a'],
  ['#b0245c', '#e0609a'],
  ['#0a8f66', '#22c08c'],
  ['#7c3aed', '#a78bfa'],
  ['#0891b2', '#38bdf8'],
  ['#a16207', '#facc15'],
  ['#be123c', '#fb7185'],
];

export const font = {
  thin: 'Inter_200ExtraLight',
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  mono: 'JetBrainsMono_400Regular',
  monoMedium: 'JetBrainsMono_500Medium',
};

export const space = { gutter: 20 };
