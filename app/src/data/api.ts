import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';

import type { Household, PlanJob, Schedule, TaskStatus } from './types';

const KEY = 'chores.serverUrl';

/**
 * Where the Python server lives. In development the phone reaches your
 * computer over Wi-Fi, so the best guess is "the machine running Metro,
 * port 8000". EXPO_PUBLIC_API_URL or the Connect screen override it.
 */
export function guessServerUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const hostUri = Constants.expoConfig?.hostUri; // e.g. "192.168.1.20:8081"
  const host = hostUri?.split(':')[0];
  return `http://${host || 'localhost'}:8000`;
}

let baseUrl: string | null = null;

export async function getServerUrl(): Promise<string> {
  if (baseUrl) return baseUrl;
  try {
    baseUrl = (await AsyncStorage.getItem(KEY)) || guessServerUrl();
  } catch {
    baseUrl = guessServerUrl();
  }
  return baseUrl;
}

export async function setServerUrl(url: string) {
  baseUrl = url.trim().replace(/\/$/, '');
  try {
    await AsyncStorage.setItem(KEY, baseUrl);
  } catch {}
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, timeoutMs = 15000): Promise<T> {
  const url = `${await getServerUrl()}${path}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError(0, `Can't reach the server at ${await getServerUrl()}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<{ ok: boolean; algorithms: string[] }>('GET', '/health', undefined, 5000),
  getHousehold: () => call<{ household: Household; warnings: string[] }>('GET', '/household'),
  putHousehold: (h: Household) => call<{ household: Household; warnings: string[] }>('PUT', '/household', h),
  startPlan: (opts: { start_day?: string; weeks_to_plan?: number } = {}) =>
    call<{ job_id: string }>('POST', '/plans', opts),
  getPlan: (id: string) => call<PlanJob>('GET', `/plans/${id}`),
  publish: (id: string, algorithm: string) => call<Schedule>('POST', `/plans/${id}/publish`, { algorithm }),
  getSchedule: () => call<{ schedule: Schedule; statuses: Record<string, TaskStatus> }>('GET', '/schedule'),
  putStatus: (slotId: string, s: TaskStatus) =>
    call<TaskStatus>('PUT', `/status/${encodeURIComponent(slotId)}`, s),
  clearStatus: (slotId: string) => call<{ ok: boolean }>('DELETE', `/status/${encodeURIComponent(slotId)}`),
  exportUrl: async (fmt: 'csv' | 'docx' | 'pdf') => `${await getServerUrl()}/export/${fmt}`,
};
