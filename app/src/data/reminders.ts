/**
 * Local reminders (no server, no push - these work in Expo Go too).
 *
 * The next 7 days are scheduled as one-off notifications and rebuilt whenever
 * the schedule, your strikes or your preferences change, so a nudge never
 * fires for something you've already struck through.
 */
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { useAppData, sessionCount } from './AppData';
import { addDays, parse, plainTask, todayIso } from './dates';
import { isFinished } from './derive';
import { usePrefs, type Reminder } from './prefs';
import type { Household, Schedule, Slot, TaskStatus } from './types';

const CHANNEL = 'reminders';
const supported = Platform.OS === 'ios' || Platform.OS === 'android';

if (supported) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: false, shouldSetBadge: false, shouldShowBanner: true, shouldShowList: true,
    }),
  });
}

/** Ask once, when a reminder is first switched on. */
export async function ensurePermission(): Promise<boolean> {
  if (!supported) return false;
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(CHANNEL, {
      name: 'Chore reminders', importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  const asked = await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowSound: true } });
  return asked.granted;
}

function at(date: string, r: Reminder): Date {
  const d = parse(date);
  d.setHours(r.hour, r.minute, 0, 0);
  return d;
}

const names = (slots: Slot[]) => {
  const list = [...new Set(slots.map((s) => plainTask(s.task)))];
  return list.length <= 2 ? list.join(' and ') : `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`;
};

type Planned = { date: Date; title: string; body: string };

/** What should fire over the next week (exported for clarity and testing). */
export function planReminders(opts: {
  morning: Reminder; evening: Reminder; schedule: Schedule; statuses: Record<string, TaskStatus>;
  household: Household; me: string; now?: Date;
}): Planned[] {
  const { morning, evening, schedule, statuses, household, me } = opts;
  const now = opts.now ?? new Date();
  const out: Planned[] = [];
  const solo = household.mode === 'solo';
  for (let i = 0; i < 7; i++) {
    const date = addDays(todayIso(), i);
    const mine = schedule.slots.filter((s) => s.date === date && s.person === me);
    if (!mine.length) continue;
    if (morning.on && at(date, morning) > now) {
      const others = schedule.slots.filter((s) => s.date === date && s.person !== me).length;
      const minutes = mine.reduce((sum, s) => sum + (household.chore_groups.find((g) => g.name === s.group)?.minutes ?? 15), 0);
      out.push({
        date: at(date, morning),
        title: `Today: ${names(mine)}`,
        body: solo ? `About ${minutes} min.` : others ? `Plus ${others} house task${others === 1 ? '' : 's'}.` : 'That’s everything today.',
      });
    }
    const open = mine.filter((s) => !isFinished(statuses[s.id], sessionCount(household, s.group)));
    if (evening.on && open.length && at(date, evening) > now) {
      out.push({ date: at(date, evening), title: `Still open: ${names(open)}`, body: 'Tap to strike it off.' });
    }
  }
  return out;
}

async function sync(planned: Planned[]) {
  await Notifications.cancelAllScheduledNotificationsAsync();
  for (const p of planned) {
    await Notifications.scheduleNotificationAsync({
      content: { title: p.title, body: p.body },
      trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: p.date, channelId: CHANNEL },
    });
  }
}

/** Mounted once at the root: keeps the scheduled reminders in step with the data. */
export function useReminderSync() {
  const { schedule, statuses, household, me } = useAppData();
  const { prefs } = usePrefs();
  useEffect(() => {
    if (!supported) return;
    const off = !prefs.morning.on && !prefs.evening.on;
    const timer = setTimeout(() => {
      if (off || !schedule || !household || !me) {
        Notifications.cancelAllScheduledNotificationsAsync().catch(() => {});
        return;
      }
      sync(planReminders({ morning: prefs.morning, evening: prefs.evening, schedule, statuses, household, me })).catch(() => {});
    }, 600); // strikes often come in bursts
    return () => clearTimeout(timer);
  }, [schedule, statuses, household, me, prefs.morning, prefs.evening]);
}
