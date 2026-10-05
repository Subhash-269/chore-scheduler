import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { sessionCount, useAppData } from '@/data/AppData';
import { addDays, dayNum, plainTask, rangeLabel, shortDay, todayIso, weekDates, weekStart } from '@/data/dates';
import { strikeCounts } from '@/data/derive';
import type { Slot } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { Dot, Loading, Note, Row, Screen, Seg, Strike, T, TopBar } from '@/ui';
import { FridgeGrid } from '@/ui/FridgeGrid';
import { LoadBars, SoloGrid } from '@/ui/SoloBoard';

type Mode = 'board' | 'load' | 'list' | 'me';

export default function Calendar() {
  const { c, personColor } = useTheme();
  const { household, schedule, statuses, me, cycleStatus } = useAppData();
  const today = todayIso();
  const [start, setStart] = useState(() => weekStart(today));
  const [mode, setMode] = useState<Mode>('board');
  if (!household || !schedule) return <Loading />;

  const dates = weekDates(start);
  const solo = household.mode === 'solo';
  const open = (s: Slot) => router.push({ pathname: '/task/[id]', params: { id: s.id } });
  const strike = (s: Slot) => (sessionCount(household, s.group) > 1 ? open(s) : cycleStatus(s).catch(() => {}));
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const inWeek = schedule.slots.filter((s) => dates.includes(s.date) && (mode !== 'me' || s.person === me));

  return (
    <Screen padded={false}>
      <View style={{ paddingHorizontal: 20 }}>
        <TopBar
          left={
            <View style={{ flexDirection: 'row', gap: 18, alignItems: 'center' }}>
              <Pressable hitSlop={12} onPress={() => setStart(addDays(start, -7))}><T v="mono" style={{ fontSize: 15 }}>‹</T></Pressable>
              <T v="cap">week</T>
              <Pressable hitSlop={12} onPress={() => setStart(addDays(start, 7))}><T v="mono" style={{ fontSize: 15 }}>›</T></Pressable>
            </View>
          }
          action={start !== weekStart(today) ? 'This week' : undefined}
          onAction={() => setStart(weekStart(today))} />
        <T v="h1">{rangeLabel(dates[0], dates[6])}</T>
        <Seg style={{ marginTop: 12, marginBottom: 12 }} value={mode} onChange={setMode}
          options={solo
            ? [{ value: 'board', label: 'Board' }, { value: 'load', label: 'Load' }, { value: 'list', label: 'List' }]
            : [{ value: 'board', label: 'Fridge board' }, { value: 'list', label: 'List' }, ...(me ? [{ value: 'me' as const, label: 'Only me' }] : [])]} />
      </View>

      {mode === 'load' ? (
        <View style={{ paddingHorizontal: 20 }}>
          <LoadBars household={household} dates={dates} slots={schedule.slots} today={today} />
          <Note>Minutes per day. Shaded days are busy or off; red means over the cap.</Note>
        </View>
      ) : mode === 'board' ? (
        <View style={{ paddingHorizontal: 10 }}>
          {solo ? (
            <SoloGrid household={household} dates={dates} slots={schedule.slots} statuses={statuses} today={today}
              onPress={strike} onLongPress={open} />
          ) : (
            <FridgeGrid household={household} dates={dates} slots={schedule.slots} statuses={statuses} today={today}
              showRest onPress={strike} onLongPress={open} />
          )}
          <Note style={{ paddingHorizontal: 10 }}>Tap a name to strike it through, tap again for missed, again to clear. Long-press for more.</Note>
        </View>
      ) : (
        <View style={{ paddingHorizontal: 20 }}>
          {dates.map((d) => {
            const day = inWeek.filter((s) => s.date === d);
            return (
              <View key={d} style={{ marginTop: 14 }}>
                <View style={{ flexDirection: 'row', gap: 8, alignItems: 'baseline' }}>
                  <T style={{ fontSize: 13 }} color={d === today ? c.tx : c.tx2}>{shortDay(d)} {dayNum(d)}</T>
                  {d === today ? <T v="cap" color={c.tx}>today</T> : null}
                </View>
                {day.length ? day.map((s, i) => {
                  const n = sessionCount(household, s.group);
                  const { done, missed } = strikeCounts(statuses[s.id], n);
                  return (
                    <Row key={s.id} end={i === day.length - 1} onPress={() => strike(s)} onLongPress={() => open(s)}
                      right={<View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}><Dot color={color(s.person)} /><T v="meta">{s.person}</T></View>}>
                      <Strike n={n} done={done} missed={missed}>{plainTask(s.task)}</Strike>
                    </Row>
                  );
                }) : <T v="faint" style={{ paddingVertical: 8 }}>Nothing due</T>}
              </View>
            );
          })}
        </View>
      )}
    </Screen>
  );
}
