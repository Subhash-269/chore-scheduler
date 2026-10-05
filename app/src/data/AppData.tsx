import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type Dispatch, type ReactNode, type SetStateAction,
} from 'react';

import { api, ApiError, getHouseholdId, getToken, setHouseholdId, type Membership, type User } from './api';
import { emptyHousehold, emptySoloHousehold } from './presets';
import type { Household, Schedule, Slot, TaskStatus } from './types';

/**
 * Where the app is:
 *  offline     - server unreachable
 *  signedOut   - no session
 *  noHousehold - signed in, not in any household yet (create or join)
 *  onboarding  - household exists, no config yet (admin sets it up)
 *  unplanned   - config, but nothing published
 *  ready       - live schedule
 */
type Phase = 'loading' | 'offline' | 'signedOut' | 'noHousehold' | 'onboarding' | 'unplanned' | 'ready';

type AppDataValue = {
  phase: Phase;
  error: string | null;
  user: User | null;
  memberships: Membership[];
  membership: Membership | null;
  isAdmin: boolean;
  household: Household | null;
  warnings: string[];
  schedule: Schedule | null;
  statuses: Record<string, TaskStatus>;
  /** requests waiting on this account (day-off approvals, swaps offered to you) */
  waiting: number;
  /** which roommate this account is in the current household */
  me: string | null;
  setMe: (name: string | null) => Promise<void>;
  refresh: () => Promise<void>;
  selectHousehold: (id: number) => Promise<void>;
  signOut: () => Promise<void>;
  saveHousehold: (h: Household) => Promise<string[]>;
  setStatus: (slot: Slot, status: TaskStatus | null) => Promise<void>;
  /** tap on the fridge board: to do -> done -> missed -> to do */
  cycleStatus: (slot: Slot) => Promise<void>;
  /** chores done several times a day: strike the next open session (clears once all are done) */
  strikeNextSession: (slot: Slot) => Promise<void>;
  /** onboarding keeps a draft here until the household is saved */
  draft: Household | null;
  setDraft: Dispatch<SetStateAction<Household | null>>;
};

const Ctx = createContext<AppDataValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [household, setHousehold] = useState<Household | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [statuses, setStatuses] = useState<Record<string, TaskStatus>>({});
  const [waiting, setWaiting] = useState(0);
  const [draft, setDraft] = useState<Household | null>(null);
  // "you" picked during onboarding, before the household is saved
  const [pendingMe, setPendingMe] = useState<string | null>(null);

  const membership = memberships.find((m) => m.id === currentId) ?? null;

  const refresh = useCallback(async () => {
    const fail = (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        setUser(null);
        setPhase('signedOut');
        return;
      }
      setError((e as Error).message);
      setPhase('offline');
    };
    if (!(await getToken())) {
      setUser(null);
      setPhase('signedOut');
      return;
    }
    let mine: Membership[];
    let userName = 'Me';
    try {
      const r = await api.me();
      setError(null);
      setUser(r.user);
      setMemberships(r.households);
      mine = r.households;
      userName = r.user.name;
    } catch (e) {
      return fail(e);
    }
    if (!mine.length) {
      setHousehold(null);
      setSchedule(null);
      setPhase('noHousehold');
      return;
    }
    let id = await getHouseholdId();
    if (!id || !mine.some((m) => m.id === id)) {
      id = mine[0].id;
      await setHouseholdId(id);
    }
    setCurrentId(id);
    try {
      const h = await api.getHousehold();
      setHousehold(h.household);
      setWarnings(h.warnings);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setHousehold(null);
        setSchedule(null);
        // resume onboarding after a restart: start a fresh draft if there isn't one
        // households created from "Just me" are named that by onboarding
        const solo = mine.find((m) => m.id === id)?.name === 'Just me';
        setDraft((d) => d ?? (solo ? emptySoloHousehold(userName) : emptyHousehold()));
        setPhase('onboarding');
        return;
      }
      return fail(e);
    }
    try {
      const s = await api.getSchedule();
      setSchedule(s.schedule);
      setStatuses(s.statuses);
      setPhase('ready');
      api.requests('pending').then((r) => setWaiting(r.waiting_on_you)).catch(() => {});
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setSchedule(null);
        setPhase('unplanned');
      } else fail(e);
    }
  }, []);

  useEffect(() => {
    // every setState in refresh() runs after an await, so nothing here is synchronous
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  const selectHousehold = useCallback(async (id: number) => {
    await setHouseholdId(id);
    setPhase('loading');
    await refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
    setMemberships([]);
    setHousehold(null);
    setSchedule(null);
    setStatuses({});
    setPhase('signedOut');
  }, []);

  const setMe = useCallback(async (name: string | null) => {
    if (!user || !membership) {
      setPendingMe(name);
      return;
    }
    await api.patchMember(user.id, { roommate: name ?? '' });
    setMemberships((prev) => prev.map((m) => (m.id === membership.id ? { ...m, roommate: name } : m)));
  }, [user, membership]);

  const saveHousehold = useCallback(async (h: Household) => {
    const res = await api.putHousehold(h);
    setHousehold(res.household);
    setWarnings(res.warnings);
    // link the account to the roommate chosen during onboarding
    if (pendingMe && user && res.household.roommates.includes(pendingMe)) {
      await api.patchMember(user.id, { roommate: pendingMe }).catch(() => {});
      setMemberships((prev) => prev.map((m) => (m.id === currentId ? { ...m, roommate: pendingMe } : m)));
      setPendingMe(null);
    }
    return res.warnings;
  }, [pendingMe, user, currentId]);

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

  const strikeNextSession = useCallback(async (slot: Slot) => {
    const n = sessionCount(household, slot.group);
    const cur = statuses[slot.id];
    const sessions = Array.from({ length: n }, (_, i) => cur?.sessions?.[i] ?? (cur?.state === 'done' ? 'done' : null));
    const next = sessions.indexOf(null);
    if (next === -1) return setStatus(slot, null); // all struck: tap again to clear, like the board
    sessions[next] = 'done';
    const done = sessions.filter((x) => x === 'done').length;
    await setStatus(slot, { state: done === n ? 'done' : 'partial', sessions });
  }, [household, statuses, setStatus]);

  const me = membership?.roommate ?? pendingMe;

  const value = useMemo<AppDataValue>(() => ({
    phase, error, user, memberships, membership, isAdmin: membership?.role === 'admin',
    household, warnings, schedule, statuses, waiting, me, setMe, refresh, selectHousehold, signOut,
    saveHousehold, setStatus, cycleStatus, strikeNextSession, draft, setDraft,
  }), [phase, error, user, memberships, membership, household, warnings, schedule, statuses, waiting, me, setMe, refresh,
    selectHousehold, signOut, saveHousehold, setStatus, cycleStatus, strikeNextSession, draft]);

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
