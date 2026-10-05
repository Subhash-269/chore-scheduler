/**
 * The fridge board: people x days, like the printed PDF on the fridge.
 * Tap a name to strike it through; long-press for the task sheet.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { sessionCount } from '@/data/AppData';
import { dayNum, shortDay, shortTask } from '@/data/dates';
import { isOff, shortName, strikeCounts } from '@/data/derive';
import type { Household, Slot, TaskStatus } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';

import { Dot, Strike, tap } from './index';

type Props = {
  household: Household;
  dates: string[];
  slots: Slot[];
  statuses?: Record<string, TaskStatus>;
  today?: string;
  /** slot ids to outline (changed vs the live schedule) */
  changed?: Set<string>;
  showRest?: boolean;
  onPress?: (slot: Slot) => void;
  onLongPress?: (slot: Slot) => void;
  compact?: boolean;
};

export function FridgeGrid({ household, dates, slots, statuses = {}, today, changed, showRest, onPress, onLongPress, compact }: Props) {
  const { c, personColor } = useTheme();
  const people = household.roommates;
  const inRange = new Set(dates);
  const cell: Record<string, Slot[]> = {};
  for (const s of slots) {
    if (!inRange.has(s.date)) continue;
    (cell[`${s.person}|${s.date}`] ??= []).push(s);
  }
  const rowH = compact ? 46 : 56;
  const border = { borderColor: c.line2 };

  return (
    <View style={[styles.grid, border]}>
      <View style={styles.row}>
        <View style={[styles.nameCol, styles.nameHead, border, { backgroundColor: c.soft }]} />
        {dates.map((d) => {
          const isToday = d === today;
          return (
            <View key={d} style={[styles.head, border, { backgroundColor: isToday ? c.tx : c.soft }]}>
              <Text style={[styles.headDay, { color: isToday ? c.bg : c.tx3 }]}>{shortDay(d)}</Text>
              <Text style={[styles.headNum, { color: isToday ? c.bg : c.tx }]}>{dayNum(d)}</Text>
            </View>
          );
        })}
      </View>

      {people.map((p) => (
        <View key={p} style={styles.row}>
          <View style={[styles.nameCol, border, { height: rowH, backgroundColor: c.soft }]}>
            <Dot color={personColor(p, people, household.colors)} size={7} />
            <Text style={[styles.name, { color: c.tx }]} numberOfLines={1}>{shortName(p)}</Text>
          </View>
          {dates.map((d) => {
            const items = cell[`${p}|${d}`] ?? [];
            const off = isOff(household, p, d);
            const isToday = d === today;
            const isChanged = items.some((s) => changed?.has(s.id));
            return (
              <View key={d} style={[styles.cell, border, {
                height: rowH,
                backgroundColor: off ? c.soft : isToday ? c.todayCol : 'transparent',
              }]}>
                {isChanged ? <View pointerEvents="none" style={[styles.changed, { borderColor: c.tx }]} /> : null}
                {off && !items.length ? <Text style={[styles.off, { color: c.tx3 }]}>off</Text> : null}
                {items.map((s) => {
                  const n = sessionCount(household, s.group);
                  const { done, missed } = strikeCounts(statuses[s.id], n);
                  return (
                    <Pressable
                      key={s.id}
                      hitSlop={4}
                      disabled={!onPress && !onLongPress}
                      onPress={onPress && (() => { tap(); onPress(s); })}
                      onLongPress={onLongPress && (() => onLongPress(s))}
                      style={{ alignItems: 'center' }}>
                      <Strike n={n} done={done} missed={missed} size={compact ? 9.5 : 10.5} thickness={1.5}>{shortTask(s.task)}</Strike>
                      {n > 1 ? <Text style={[styles.sub, { color: c.tx3 }]}>{done}/{n}</Text>
                        : showRest && s.rest_before !== null ? <Text style={[styles.sub, { color: c.tx3 }]}>r{s.rest_before}</Text> : null}
                    </Pressable>
                  );
                })}
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { borderTopWidth: 1, borderLeftWidth: 1 },
  row: { flexDirection: 'row' },
  // its own style, never combined with `flex: 1` - react-native-web would let the
  // shorthand's 0% basis win and collapse the column
  nameCol: { width: 40, alignItems: 'center', justifyContent: 'center', gap: 3, borderRightWidth: 1, borderBottomWidth: 1 },
  nameHead: { height: 38 },
  head: { flex: 1, height: 38, alignItems: 'center', justifyContent: 'center', borderRightWidth: 1, borderBottomWidth: 1 },
  headDay: { fontFamily: font.mono, fontSize: 7.5, letterSpacing: 0.5 },
  headNum: { fontFamily: font.monoMedium, fontSize: 12 },
  cell: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3, borderRightWidth: 1, borderBottomWidth: 1, paddingHorizontal: 1 },
  name: { fontFamily: font.semibold, fontSize: 9.5, marginTop: 3 },
  off: { fontFamily: font.mono, fontSize: 8 },
  sub: { fontFamily: font.mono, fontSize: 7.5 },
  changed: { position: 'absolute', top: 3, left: 3, right: 3, bottom: 3, borderWidth: 1.5, borderStyle: 'dashed', borderRadius: 3 },
});
