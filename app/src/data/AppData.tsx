import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type Dispatch, type ReactNode, type SetStateAction,
} from 'react';

import { api, ApiError } from './api';
import type { Household, Schedule, Slot, TaskStatus } from './types';

type Phase = 'loading' | 'offline' | 'onboarding' | 'unplanned' | 'ready';

type AppDataValue = {
  phase: Phase;
  error: string | null;
  household: Household | null;
  warnings: string[];
  schedule: Schedule | null;
  statuses: Record<string, TaskStatus>;
  /** which roommate is using this phone (stored on the device) */
  me: string | null;
  setMe: (name: string | null) => void;
  refresh: () => Promise<void>;
  saveHousehold: (h: Household) => Promise<string[]>;
  setStatus: (slot: Slot, status: TaskStatus | null) => Promise<void>;
  /** tap on the fridge board: to do -> done -> missed -> to do */
  cycleStatus: (slot: Slot) => Promise<void>;
  /** onboarding keeps a draft here until the household is saved */
  draft: Household | null;
  setDraft: Dispatch<SetStateAction<Household | null>>;
};

const Ctx = createContext<AppDataValue | null>(null);
const ME_KEY = 'chores.me';

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [household, setHousehold] = useState<Household | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [statuses, setStatuses] = useState<Record<string, TaskStatus>>({});
  const [me, setMeState] = useState<string | null>(null);
  const [draft, setDraft] = useState<Household | null>(null);

  useEffect(() => {
    AsyncStorage.getItem(ME_KEY).then((v) => v && setMeState(v)).catch(() => {});
  }, []);

  const setMe = useCallback((name: string | null) => {
    setMeState(name);
    (name ? AsyncStorage.setItem(ME_KEY, name) : AsyncStorage.removeItem(ME_KEY)).catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    try {
      const h = await api.getHousehold();
      setError(null);
      setHousehold(h.household);
      setWarnings(h.warnings);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setHousehold(null);
        setSchedule(null);
        setPhase('onboarding');
        return;
      }
      setError((e as Error).message);
      setPhase('offline');
      return;
    }
    try {
      const s = await api.getSchedule();
      setSchedule(s.schedule);
      setStatuses(s.statuses);
      setPhase('ready');
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setSchedule(null);
        setPhase('unplanned');
      } else {
        setError((e as Error).message);
        setPhase('offline');
      }
    }
  }, []);

  useEffect(() => {
    // every setState in refresh() runs after an await, so nothing here is synchronous
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  const saveHousehold = useCallback(async (h: Household) => {
    const res = await api.putHousehold(h);
    setHousehold(res.household);
    setWarnings(res.warnings);
    return res.warnings;
  }, []);

  const setStatus = useCallback(async (slot: Slot, status: TaskStatus | null) => {
    const before = statuses[slot.id];
    // optimistic: the strike appears immediately, rolled back if the server says no
    setStatuses((prev) => {
      const next = { ...prev };
      if (status) next[slot.id] = status;
      else delete next[slot.id];
      return next;
    });
    try {
      if (status) await api.putStatus(slot.id, status);
      else await api.clearStatus(slot.id);
    } catch (e) {
      setStatuses((prev) => {
        const next = { ...prev };
        if (before) next[slot.id] = before;
        else delete next[slot.id];
        return next;
      });
      throw e;
    }
  }, [statuses]);

  const cycleStatus = useCallback(async (slot: Slot) => {
    const cur = statuses[slot.id]?.state;
    const next: TaskStatus | null = !cur ? { state: 'done' } : cur === 'done' || cur === 'covered' ? { state: 'missed' } : null;
    await setStatus(slot, next);
  }, [statuses, setStatus]);

  const value = useMemo<AppDataValue>(() => ({
    phase, error, household, warnings, schedule, statuses, me, setMe,
    refresh, saveHousehold, setStatus, cycleStatus, draft, setDraft,
  }), [phase, error, household, warnings, schedule, statuses, me, setMe, refresh, saveHousehold, setStatus,
    cycleStatus, draft]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppData() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAppData outside AppDataProvider');
  return v;
}

/** Number of sessions a slot's chore has (1 for ordinary chores). */
export function sessionCount(household: Household | null, group: string): number {
  const g = household?.chore_groups.find((x) => x.name === group);
  return Math.max(1, g?.sessions?.length ?? 1);
}
