/**
 * Per-device preferences: what Today shows and which reminders fire.
 * Kept on the phone (AsyncStorage), not on the server - they're about this
 * person's screen, not the household's rules.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type Reminder = { on: boolean; hour: number; minute: number };

export type Prefs = {
  /** your tasks in their own section at the top of Today */
  yoursFirst: boolean;
  /** everyone else's tasks on Today */
  showHouse: boolean;
  /** how many upcoming days Today lists */
  nextDays: number;
  /** "Dishes and Vacuum today" at this time on days you have tasks */
  morning: Reminder;
  /** only if your tasks for the day are still open */
  evening: Reminder;
};

export const DEFAULT_PREFS: Prefs = {
  yoursFirst: true,
  showHouse: true,
  nextDays: 4,
  morning: { on: false, hour: 8, minute: 0 },
  evening: { on: false, hour: 20, minute: 0 },
};

const KEY = 'chores.prefs';

type PrefsValue = { prefs: Prefs; setPrefs: (patch: Partial<Prefs>) => void };
const Ctx = createContext<PrefsValue | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setState] = useState<Prefs>(DEFAULT_PREFS);

  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((raw) => { if (raw) setState({ ...DEFAULT_PREFS, ...JSON.parse(raw) }); })
      .catch(() => {});
  }, []);

  const setPrefs = useCallback((patch: Partial<Prefs>) => {
    setState((cur) => {
      const next = { ...cur, ...patch };
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, []);

  const value = useMemo(() => ({ prefs, setPrefs }), [prefs, setPrefs]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePrefs() {
  const v = useContext(Ctx);
  if (!v) throw new Error('usePrefs outside PrefsProvider');
  return v;
}

export const timeLabel = (r: Reminder) => `${String(r.hour).padStart(2, '0')}:${String(r.minute).padStart(2, '0')}`;
