/**
 * Solo versions of the fridge board: rows are chores instead of people, and a
 * load view shows minutes per day against the cap (busy days hatched).
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { sessionCount } from '@/data/AppData';
import { dayNum, shortDay, shortTask, weekdayName } from '@/data/dates';
import { strikeCounts } from '@/data/derive';
import type { Household, Slot, TaskStatus } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';

import { Strike, tap } from './index';

export const minutesOf = (h: Household, group: string) =>
  h.chore_groups.find((g) => g.name === group)?.minutes ?? 15;

export function capFor(h: Household, date: string) {
  const person = h.roommates[0];
  const wd = weekdayName(date);
  if ((h.days_off[person] ?? []).some((d) => d === wd || d === date)) return { cap: 0, kind: 'off' as const };
  if ((h.busy_days ?? []).includes(wd)) return { cap: h.busy_cap_minutes ?? 15, kind: 'busy' as const };
  return { cap: h.daily_cap_minutes ?? 60, kind: 'normal' as const };
}

/** Minutes per date, counting each chore group once per day. */
export function dailyMinutes(h: Household, slots: Slot[]) {
  const seen = new Set<string>();
  const out: Record<string, number> = {};
  for (const s of slots) {
    const k = `${s.date}|${s.group}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out[s.date] = (out[s.date] ?? 0) + minutesOf(h, s.group);
  }
  return out;
}

export function SoloGrid({ household, dates, slots, statuses = {}, today, changed, onPress, onLongPress }: {
  household: Household; dates: string[]; slots: Slot[]; statuses?: Record<string, TaskStatus>; today?: string;
  changed?: Set<string>; onPress?: (s: Slot) => void; onLongPress?: (s: Slot) => void;
}) {
  const { c } = useTheme();
  const tasks = household.chore_groups.flatMap((g) => g.tasks.map((t) => ({ task: t, group: g.name })));
  const at = new Map(slots.filter((s) => dates.includes(s.date)).map((s) => [`${s.task}|${s.date}`, s]));
  const border = { borderColor: c.line2 };
  return (
    <View style={[styles.grid, border]}>
      <View style={styles.row}>
        <View style={[styles.name, styles.headH, border, { backgroundColor: c.soft }]} />
        {dates.map((d) => {
          const { kind } = capFor(household, d);
          const isToday = d === today;
          return (
            <View key={d} style={[styles.head, border, { backgroundColor: isToday ? c.tx : c.soft }]}>
              <Text style={[styles.headDay, { color: isToday ? c.bg : c.tx3 }]}>{shortDay(d)}</Text>
              <Text style={[styles.headNum, { color: isToday ? c.bg : c.tx }]}>{dayNum(d)}</Text>
              {kind !== 'normal' ? <Text style={[styles.headDay, { color: isToday ? c.bg : c.tx3 }]}>{kind}</Text> : null}
            </View>
          );
        })}
      </View>
      {tasks.map(({ task, group }) => (
        <View key={task} style={styles.row}>
          <View style={[styles.name, border, { backgroundColor: c.soft }]}>
            <Text style={[styles.nameText, { color: c.tx }]} numberOfLines={1}>{shortTask(task)}</Text>
          </View>
          {dates.map((d) => {
            const s = at.get(`${task}|${d}`);
            const { kind } = capFor(household, d);
            const n = s ? sessionCount(household, s.group) : 1;
            const { done, missed } = s ? strikeCounts(statuses[s.id], n) : { done: 0, missed: 0 };
            return (
              <View key={d} style={[styles.cell, border, { backgroundColor: kind !== 'normal' ? c.soft : d === today ? c.todayCol : 'transparent' }]}>
                {s && changed?.has(s.id) ? <View pointerEvents="none" style={[styles.changed, { borderColor: c.tx }]} /> : null}
                {s ? (
                  <Pressable hitSlop={4} disabled={!onPress && !onLongPress}
                    onPress={onPress && (() => { tap(); onPress(s); })} onLongPress={onLongPress && (() => onLongPress(s))}>
                    <Strike n={n} done={done} missed={missed} size={10} thickness={1.5} fontFamily={font.mono}>{`${minutesOf(household, group)}m`}</Strike>
                  </Pressable>
                ) : null}
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}

/** Minutes per day as bars, with the cap line. */
export function LoadBars({ household, dates, slots, today }: { household: Household; dates: string[]; slots: Slot[]; today?: string }) {
  const { c } = useTheme();
  const minutes = dailyMinutes(household, slots);
  const top = Math.max(household.daily_cap_minutes ?? 60, ...dates.map((d) => minutes[d] ?? 0)) * 1.15;
  const capY = ((household.daily_cap_minutes ?? 60) / top) * 100;
  return (
    <View>
      <View style={styles.bars}>
        <View pointerEvents="none" style={[styles.capLine, { bottom: `${capY}%`, borderColor: c.tx2 }]}>
          <Text style={[styles.capText, { color: c.tx2, backgroundColor: c.bg }]}>{household.daily_cap_minutes ?? 60}m cap</Text>
        </View>
        {dates.map((d) => {
          const m = minutes[d] ?? 0;
          const { cap, kind } = capFor(household, d);
          return (
            <View key={d} style={[styles.barCol, kind !== 'normal' && { backgroundColor: c.soft }]}>
              <View style={{ height: `${(m / top) * 100}%`, backgroundColor: m > cap ? c.bad : d === today ? c.tx : c.tx2, borderRadius: 3 }} />
            </View>
          );
        })}
      </View>
      <View style={styles.barLabels}>
        {dates.map((d) => (
          <View key={d} style={{ flex: 1, alignItems: 'center' }}>
            <Text style={[styles.headDay, { color: c.tx3 }]}>{shortDay(d)[0]}</Text>
            <Text style={[styles.headNum, { color: d === today ? c.tx : c.tx2, fontSize: 11 }]}>{dayNum(d)}</Text>
            <Text style={[styles.headDay, { color: c.tx2 }]}>{minutes[d] ?? 0}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { borderTopWidth: 1, borderLeftWidth: 1 },
  row: { flexDirection: 'row' },
  name: { width: 48, height: 40, alignItems: 'center', justifyContent: 'center', borderRightWidth: 1, borderBottomWidth: 1 },
  headH: { height: 44 },
  nameText: { fontFamily: font.medium, fontSize: 9.5 },
  head: { flex: 1, height: 44, alignItems: 'center', justifyContent: 'center', borderRightWidth: 1, borderBottomWidth: 1 },
  headDay: { fontFamily: font.mono, fontSize: 7.5, letterSpacing: 0.5 },
  headNum: { fontFamily: font.monoMedium, fontSize: 12 },
  cell: { flex: 1, height: 40, alignItems: 'center', justifyContent: 'center', borderRightWidth: 1, borderBottomWidth: 1 },
  changed: { position: 'absolute', top: 3, left: 3, right: 3, bottom: 3, borderWidth: 1.5, borderStyle: 'dashed', borderRadius: 3 },
  bars: { flexDirection: 'row', gap: 6, height: 150, alignItems: 'flex-end', marginTop: 14 },
  barCol: { flex: 1, height: '100%', justifyContent: 'flex-end', borderRadius: 4 },
  capLine: { position: 'absolute', left: 0, right: 0, borderTopWidth: 1, borderStyle: 'dashed' },
  capText: { position: 'absolute', right: 0, top: -14, fontFamily: font.mono, fontSize: 9, paddingLeft: 4 },
  barLabels: { flexDirection: 'row', gap: 6, marginTop: 6 },
});
