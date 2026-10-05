import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { sessionCount, useAppData } from '@/data/AppData';
import { addDays, dayNum, monthLong, plainTask, shortDay, todayIso, weekdayName } from '@/data/dates';
import { isFinished, strikeCounts } from '@/data/derive';
import type { Slot } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { minutesOf } from '@/ui/SoloBoard';
import { Check, Dot, Loading, Note, ProgressLine, Row, Section, Strike, T, Tag, TopBar } from '@/ui';

export default function Today() {
  const { c, personColor } = useTheme();
  const { household, schedule, statuses, me, refresh, cycleStatus, setStatus } = useAppData();
  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => { setRefreshing(true); await refresh(); setRefreshing(false); }, [refresh]);

  if (!household || !schedule) return <Loading />;
  const today = todayIso();
  const todays = schedule.slots.filter((s) => s.date === today);
  // solo: one list - every task is yours
  const mine = household.mode === 'solo' ? [] : todays.filter((s) => s.person === me);
  const house = household.mode === 'solo' ? todays : todays.filter((s) => s.person !== me);
  const doneCount = todays.filter((s) => isFinished(statuses[s.id], sessionCount(household, s.group))).length;
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const solo = household.mode === 'solo';
  const minutes = (s: Slot) => minutesOf(household, s.group);
  const minutesToday = todays.reduce((sum, s) => sum + minutes(s), 0);
  const minutesDone = todays.filter((s) => isFinished(statuses[s.id], sessionCount(household, s.group))).reduce((sum, s) => sum + minutes(s), 0);
  const end = addDays(schedule.start_day, schedule.days - 1);

  const open = (s: Slot) => router.push({ pathname: '/task/[id]', params: { id: s.id } });
  const toggle = (s: Slot) => {
    const n = sessionCount(household, s.group);
    if (n > 1) return open(s); // several sessions: strike them one by one in the sheet
    if (statuses[s.id]?.state === 'done') setStatus(s, null).catch(() => {});
    else cycleStatus(s).catch(() => {});
  };

  const taskRow = (s: Slot, last: boolean) => {
    const n = sessionCount(household, s.group);
    const { done, missed } = strikeCounts(statuses[s.id], n);
    const st = statuses[s.id]?.state;
    return (
      <Row key={s.id} end={last} onPress={() => open(s)} onLongPress={() => toggle(s)}
        left={<Check on={done + missed >= n && st !== 'missed'} onPress={() => toggle(s)} />}
        right={solo ? `${minutes(s)}m` : s.person === me ? (s.rest_before !== null ? `r${s.rest_before}` : '') : (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Dot color={color(s.person)} /><T v="meta" style={{ fontSize: 12 }}>{s.person}</T>
          </View>
        )}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Strike n={n} done={done} missed={missed}>{plainTask(s.task)}</Strike>
          {n > 1 ? <T v="mono" style={{ fontSize: 10.5 }}>{done}/{n}</T> : null}
          {st === 'missed' ? <Tag label="missed" tone="bad" /> : null}
          {st === 'covered' && statuses[s.id]?.covered_by ? <Dot color={color(statuses[s.id]!.covered_by!)} size={6} /> : null}
        </View>
      </Row>
    );
  };

  const upcoming = [1, 2, 3, 4].map((i) => addDays(today, i)).filter((d) => d <= end);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 28 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.tx3} />}>
        <TopBar left={<T v="cap">Today</T>} action={me ?? 'Who are you?'} onAction={() => router.push('/settings')} />
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 12, marginTop: 6, marginBottom: 14 }}>
          <T v="big">{dayNum(today)}</T>
          <View style={{ paddingBottom: 3 }}>
            <T style={{ fontFamily: font.semibold, fontSize: 14 }}>{weekdayName(today)}</T>
            <T v="meta">{monthLong(today)}</T>
          </View>
          <View style={{ flex: 1 }} />
          <View style={{ alignItems: 'flex-end', paddingBottom: 3 }}>
            <T style={{ fontFamily: font.mono, fontSize: 13 }}>{solo ? `${minutesDone}/${minutesToday}` : `${doneCount}/${todays.length}`}</T>
            <T v="faint">{solo ? 'min done' : 'done'}</T>
          </View>
        </View>
        <ProgressLine value={solo ? (minutesToday ? minutesDone / minutesToday : 0) : todays.length ? doneCount / todays.length : 0} />

        {today < schedule.start_day || today > end ? (
          <Note>{today < schedule.start_day ? `The schedule starts on ${schedule.start_day}.` : 'This schedule has ended. Plan the next stretch from Setup.'}</Note>
        ) : null}

        {me && mine.length ? (
          <>
            <Section title="Yours" />
            {mine.map((s, i) => taskRow(s, i === mine.length - 1))}
          </>
        ) : null}

        <Section title={me && !solo ? 'House' : 'Today'} link="Week" onLink={() => router.push('/calendar')} />
        {house.length ? house.map((s, i) => taskRow(s, i === house.length - 1))
          : <Note>{todays.length ? 'Nothing else today.' : 'Nothing due today.'}</Note>}

        {upcoming.length ? <Section title="Next days" /> : null}
        {upcoming.map((d) => {
          const day = schedule.slots.filter((s) => s.date === d);
          return (
            <View key={d} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: c.line, borderStyle: 'dashed' }}>
              <T v="mono" style={{ width: 50, fontSize: 10.5 }} color={c.tx3}>{shortDay(d)} {dayNum(d)}</T>
              <T style={{ flex: 1, fontSize: 13 }} numberOfLines={1}>{day.length ? day.map((s) => plainTask(s.task)).join(', ') : '—'}</T>
              {solo ? <T v="mono" style={{ fontSize: 11 }}>{day.reduce((sum, s) => sum + minutes(s), 0)}m</T>
                : <View style={{ flexDirection: 'row', gap: 4 }}>{day.map((s) => <Dot key={s.id} color={color(s.person)} />)}</View>}
            </View>
          );
        })}
        <Note style={{ marginTop: 16 }}>Tap the box to strike a task through. Tap the name for options: {solo ? 'missed, skip' : 'covered, missed, skip'}.</Note>
      </ScrollView>
    </SafeAreaView>
  );
}
