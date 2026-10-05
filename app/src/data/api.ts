import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type { Household, PlanJob, Schedule, TaskStatus } from './types';

const URL_KEY = 'chores.serverUrl';
const TOKEN_KEY = 'chores.token';
const HOUSEHOLD_KEY = 'chores.household';

/**
 * Where the Python server lives. In development the phone reaches your
 * computer over Wi-Fi, so the best guess is "the machine running Metro,
 * port 8000". EXPO_PUBLIC_API_URL (set for store builds) or the Connect
 * screen override it.
 */
export function guessServerUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const hostUri = Constants.expoConfig?.hostUri; // e.g. "192.168.1.20:8081"
  const host = hostUri?.split(':')[0];
  return `http://${host || 'localhost'}:8000`;
}

// ---------------------------------------------------------------- small persistent values
// The session token goes in the Keychain / Keystore; SecureStore isn't available on web.
const secure = {
  get: (k: string) => (Platform.OS === 'web' ? AsyncStorage.getItem(k) : SecureStore.getItemAsync(k)),
  set: (k: string, v: string) => (Platform.OS === 'web' ? AsyncStorage.setItem(k, v) : SecureStore.setItemAsync(k, v)),
  del: (k: string) => (Platform.OS === 'web' ? AsyncStorage.removeItem(k) : SecureStore.deleteItemAsync(k)),
};

let baseUrl: string | null = null;
let token: string | null | undefined;
let householdId: number | null | undefined;

export async function getServerUrl(): Promise<string> {
  if (baseUrl) return baseUrl;
  try {
    baseUrl = (await AsyncStorage.getItem(URL_KEY)) || guessServerUrl();
  } catch {
    baseUrl = guessServerUrl();
  }
  return baseUrl;
}

export async function setServerUrl(url: string) {
  baseUrl = url.trim().replace(/\/$/, '');
  try {
    await AsyncStorage.setItem(URL_KEY, baseUrl);
  } catch {}
}

export async function getToken(): Promise<string | null> {
  if (token === undefined) {
    try { token = await secure.get(TOKEN_KEY); } catch { token = null; }
  }
  return token ?? null;
}

async function setToken(t: string | null) {
  token = t;
  try { await (t ? secure.set(TOKEN_KEY, t) : secure.del(TOKEN_KEY)); } catch {}
}

export async function getHouseholdId(): Promise<number | null> {
  if (householdId === undefined) {
    try {
      const v = await AsyncStorage.getItem(HOUSEHOLD_KEY);
      householdId = v ? Number(v) : null;
    } catch { householdId = null; }
  }
  return householdId ?? null;
}

export async function setHouseholdId(id: number | null) {
  householdId = id;
  try { await (id ? AsyncStorage.setItem(HOUSEHOLD_KEY, String(id)) : AsyncStorage.removeItem(HOUSEHOLD_KEY)); } catch {}
}

// ---------------------------------------------------------------- requests
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, timeoutMs = 15000): Promise<T> {
  const url = `${await getServerUrl()}${path}`;
  const t = await getToken();
  const headers: Record<string, string> = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (t) headers.Authorization = `Bearer ${t}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal });
  } catch {
    throw new ApiError(0, `Can't reach the server at ${await getServerUrl()}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { msg?: string }) => d.msg).join('; ') : JSON.stringify(j.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Household-scoped path: /households/{id}/... for the selected household. */
async function hh(path: string): Promise<string> {
  const id = await getHouseholdId();
  if (!id) throw new ApiError(400, 'No household selected');
  return `/households/${id}${path}`;
}

// ---------------------------------------------------------------- shapes
export type User = { id: number; email: string; name: string };
export type Membership = { id: number; name: string; role: 'admin' | 'member'; roommate: string | null; configured: number; planned: number };
export type Member = { id: number; name: string; email: string; role: 'admin' | 'member'; roommate: string | null; joined_at: number };
export type Invite = { code: string; role: 'admin' | 'member'; expires_at: number };

export const api = {
  health: () => call<{ ok: boolean; version: string; algorithms: string[] }>('GET', '/health', undefined, 5000),

  // accounts
  signup: async (email: string, password: string, name: string) => {
    const r = await call<{ token: string; user: User }>('POST', '/auth/signup', { email, password, name });
    await setToken(r.token);
    return r.user;
  },
  login: async (email: string, password: string) => {
    const r = await call<{ token: string; user: User }>('POST', '/auth/login', { email, password });
    await setToken(r.token);
    return r.user;
  },
  providers: () => call<{ email: boolean; apple: boolean; google: boolean }>('GET', '/auth/providers', undefined, 5000),
  appleLogin: async (identity_token: string, name?: string) => {
    const r = await call<{ token: string; user: User }>('POST', '/auth/apple', { identity_token, name });
    await setToken(r.token);
    return r.user;
  },
  googleLogin: async (id_token: string) => {
    const r = await call<{ token: string; user: User }>('POST', '/auth/google', { id_token });
    await setToken(r.token);
    return r.user;
  },
  logout: async () => {
    try { await call('POST', '/auth/logout'); } catch {}
    await setToken(null);
    await setHouseholdId(null);
  },
  deleteAccount: async () => {
    await call('DELETE', '/me');
    await setToken(null);
    await setHouseholdId(null);
  },
  me: () => call<{ user: User; households: Membership[] }>('GET', '/me'),

  // households & members
  createHousehold: (name: string) => call<{ id: number; name: string; role: 'admin' }>('POST', '/households', { name }),
  acceptInvite: (code: string, roommate?: string) =>
    call<{ id: number; name: string; role: 'admin' | 'member' }>('POST', `/invites/${encodeURIComponent(code)}/accept`, { roommate }),
  members: async () => call<{ members: Member[]; invites: Invite[]; settings: Record<string, boolean> }>('GET', await hh('/members')),
  patchMember: async (uid: number, patch: { role?: 'admin' | 'member'; roommate?: string }) =>
    call('PATCH', await hh(`/members/${uid}`), patch),
  removeMember: async (uid: number) => call('DELETE', await hh(`/members/${uid}`)),
  createInvite: async (role: 'admin' | 'member') => call<Invite>('POST', await hh('/invites'), { role }),
  revokeInvite: async (code: string) => call('DELETE', await hh(`/invites/${code}`)),

  // config & planning
  getHousehold: async () => call<{ household: Household; warnings: string[] }>('GET', await hh('/config')),
  putHousehold: async (h: Household) => call<{ household: Household; warnings: string[] }>('PUT', await hh('/config'), h),
  startPlan: async (opts: { start_day?: string; weeks_to_plan?: number } = {}) =>
    call<{ job_id: string }>('POST', await hh('/plans'), opts),
  getPlan: async (id: string) => call<PlanJob>('GET', await hh(`/plans/${id}`)),
  publish: async (id: string, algorithm: string) => call<Schedule>('POST', await hh(`/plans/${id}/publish`), { algorithm }),

  // live schedule
  getSchedule: async () => call<{ schedule: Schedule; statuses: Record<string, TaskStatus> }>('GET', await hh('/schedule')),
  putStatus: async (slotId: string, s: TaskStatus) => call<TaskStatus>('PUT', await hh(`/status/${encodeURIComponent(slotId)}`), s),
  clearStatus: async (slotId: string) => call<{ ok: boolean }>('DELETE', await hh(`/status/${encodeURIComponent(slotId)}`)),
  exportUrl: async (fmt: 'csv' | 'docx' | 'pdf') =>
    `${await getServerUrl()}${await hh(`/export/${fmt}`)}?token=${encodeURIComponent((await getToken()) ?? '')}`,
};
