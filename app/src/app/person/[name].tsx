import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { dayNum, plainTask, shortDay, todayIso } from '@/data/dates';
import { eligibleAverage, isExcluded } from '@/data/derive';
import { useTheme } from '@/theme/ThemeProvider';
import { PERSON_COLORS } from '@/theme/tokens';
import { Btn, Dot, Loading, Note, Screen, Section, T, Tag, TopBar } from '@/ui';
import { toggleDay, WeekdayPicker } from '@/ui/WeekdayPicker';

export default function Person() {
  const { c, isDark, personColor } = useTheme();
  const { name } = useLocalSearchParams<{ name: string }>();
  const { household, schedule, me, setMe, saveHousehold, isAdmin } = useAppData();
  const [editing, setEditing] = useState(false);
  const [daysOff, setDaysOff] = useState<string[]>(household?.days_off[name] ?? []);
  const [colorPick, setColorPick] = useState<string | undefined>(household?.colors[name]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household || !schedule) return <Loading />;

  const m = schedule.metrics;
  const color = personColor(name, household.roommates, household.colors);
  const mySlots = schedule.slots.filter((s) => s.person === name);
  const rests = mySlots.map((s) => s.rest_before).filter((r): r is number => r !== null);
  const avgRest = rests.length ? rests.reduce((a, b) => a + b, 0) / rests.length : 0;
  const shortRests = rests.filter((r) => r < household.buffer_days).length;
  const tasks = Object.keys(m.per_task_counts);
  const maxCount = Math.max(1, ...tasks.flatMap((t) => Object.values(m.per_task_counts[t])));
  const upNext = mySlots.filter((s) => s.date >= todayIso()).slice(0, 3);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await saveHousehold({
        ...household,
        days_off: { ...household.days_off, [name]: daysOff },
        colors: colorPick ? { ...household.colors, [name]: colorPick } : household.colors,
      });
      setEditing(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={editing ? <Btn title="Save" onPress={save} loading={busy} /> : undefined}>
      <TopBar back="Household" action={isAdmin ? (editing ? 'Cancel' : 'Edit') : undefined} onAction={() => setEditing(!editing)} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <Dot color={color} size={11} />
        <T v="h1">{name}</T>
        {me === name ? <Tag label="you" /> : null}
      </View>

      {editing ? (
        <>
          <Section title="Colour" />
          <View style={{ flexDirection: 'row', gap: 12, marginTop: 10 }}>
            {PERSON_COLORS.map(([l, d]) => (
              <Pressable key={l} hitSlop={6} onPress={() => setColorPick(l)}
                style={{ padding: 3, borderRadius: 14, borderWidth: 1.5, borderColor: (colorPick ?? color) === l || (colorPick ?? color) === d ? c.tx : 'transparent' }}>
                <Dot color={isDark ? d : l} size={18} />
              </Pressable>
            ))}
          </View>
          <Section title="Off every week" />
          <WeekdayPicker off={daysOff} onToggle={(day) => setDaysOff((cur) => toggleDay(cur, day))} />
          <Note>Exclusions (“never assign”) are set per chore in Setup → chore → Who can do it.</Note>
          {me !== name ? <Btn kind="ghost" small style={{ marginTop: 16 }} title="This is me" onPress={() => { setMe(name).catch(() => {}); }} /> : null}
          {err ? <Note tone="bad">{err}</Note> : null}
        </>
      ) : (
        <>
          <T v="meta" style={{ marginTop: 6 }}>
            {(household.days_off[name] ?? []).length ? `Off ${household.days_off[name].join(', ')}` : 'No days off'}
            {(household.exclusions[name] ?? []).length ? ` · never ${household.exclusions[name].join(', ')}` : ''}
          </T>
          <View style={{ flexDirection: 'row', borderTopWidth: 1, borderBottomWidth: 1, borderColor: c.line, marginTop: 14 }}>
            {[[`${m.workload[name] ?? 0}`, 'tasks'], [`${avgRest.toFixed(1)}d`, 'avg rest'], [`${shortRests}`, 'short rests']].map(([v, l], i) => (
              <View key={l} style={{ flex: 1, paddingVertical: 10, paddingLeft: i ? 12 : 0, borderLeftWidth: i ? 1 : 0, borderLeftColor: c.line }}>
                <T style={{ fontSize: 21, fontFamily: 'Inter_200ExtraLight', letterSpacing: -0.8 }}>{v}</T>
                <T v="cap">{l}</T>
              </View>
            ))}
          </View>

          <Section title="Share of each chore" link="| = avg" />
          {tasks.map((t) => {
            const counts = m.per_task_counts[t];
            const excluded = isExcluded(household, name, t);
            const mine = counts[name] ?? 0;
            const avg = eligibleAverage(household, t, counts);
            return (
              <View key={t} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 7 }}>
                <T style={{ width: 70, fontSize: 12.5 }} color={excluded ? c.tx3 : c.tx} numberOfLines={1}>{plainTask(t)}</T>
                <View style={{ flex: 1, height: 6, borderRadius: 3, backgroundColor: c.soft }}>
                  {!excluded ? <View style={{ width: `${(mine / maxCount) * 100}%`, height: 6, borderRadius: 3, backgroundColor: color }} /> : null}
                  {!excluded ? <View style={{ position: 'absolute', left: `${(avg / maxCount) * 100}%`, top: -4, bottom: -4, width: 2, backgroundColor: c.tx }} /> : null}
                </View>
                <T v="mono" style={{ width: 18, textAlign: 'right' }}>{excluded ? '—' : mine}</T>
              </View>
            );
          })}
          {(household.exclusions[name] ?? []).length ? <Note>Excluded chores don’t count as unfair: averages use eligible people only.</Note> : null}

          <Section title="Up next" />
          {upNext.length ? upNext.map((s) => (
            <View key={s.id} style={{ flexDirection: 'row', gap: 12, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.line }}>
              <T v="mono" style={{ width: 50, fontSize: 10.5 }} color={c.tx3}>{shortDay(s.date)} {dayNum(s.date)}</T>
              <T style={{ fontSize: 13 }}>{plainTask(s.task)}</T>
            </View>
          )) : <Note>Nothing left in this plan.</Note>}
        </>
      )}
    </Screen>
  );
}
