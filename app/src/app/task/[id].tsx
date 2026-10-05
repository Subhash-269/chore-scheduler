import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { sessionCount, useAppData } from '@/data/AppData';
import { dayNum, plainTask, shortDay, weekdayName } from '@/data/dates';
import { isExcluded, strikeCounts } from '@/data/derive';
import { ruleLabel } from '@/data/presets';
import type { SessionMark, TaskStatus } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Dot, KV, Note, Pill, Pills, Screen, Strike, T, tap, TopBar } from '@/ui';

/** Task sheet: how did it go? Strike, missed, covered, not needed - or per session. */
export default function TaskSheet() {
  const { c, personColor } = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { household, schedule, statuses, setStatus } = useAppData();
  const [err, setErr] = useState<string | null>(null);
  const slot = schedule?.slots.find((s) => s.id === id);
  if (!household || !schedule || !slot) return <Screen><TopBar back="Close" /><Note>This task isn’t in the live schedule any more.</Note></Screen>;

  const group = household.chore_groups.find((g) => g.name === slot.group);
  const n = sessionCount(household, slot.group);
  const status = statuses[slot.id];
  const { done, missed } = strikeCounts(status, n);
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const others = household.roommates.filter((p) => p !== slot.person && !isExcluded(household, p, slot.task));

  const save = (s: TaskStatus | null) => {
    setErr(null);
    tap();
    setStatus(slot, s).catch((e) => setErr((e as Error).message));
  };

  const setSession = (i: number, mark: SessionMark) => {
    const sessions: SessionMark[] = Array.from({ length: n }, (_, k) => status?.sessions?.[k] ?? null);
    sessions[i] = sessions[i] === mark ? null : mark;
    const d = sessions.filter((x) => x === 'done').length;
    const m = sessions.filter((x) => x === 'missed').length;
    if (d + m === 0) return save(null);
    const state: TaskStatus['state'] = d === n ? 'done' : m === n ? 'missed' : 'partial';
    save({ state, sessions, covered_by: status?.covered_by });
  };


  return (
    <Screen footer={<Btn title="Done" onPress={() => router.back()} />}>
      <TopBar back="Close" action={status ? 'Clear' : undefined} onAction={() => save(null)} />
      <T v="cap">{shortDay(slot.date)} {dayNum(slot.date)} · {weekdayName(slot.date)}</T>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10, marginTop: 6 }}>
        <Strike n={n} done={done} missed={missed} size={26} fontFamily={font.semibold} thickness={2.5}>{plainTask(slot.task)}</Strike>
        {n > 1 ? <T v="mono">{done}/{n}</T> : null}
      </View>
      {group ? <T v="meta" style={{ marginTop: 6 }}>{group.piggyback_on ? `Rides on every ${ruleLabel(group).split(' ')[0]} ${group.piggyback_on}` : (group.frequency_days === 1 ? 'Every day' : `Every ${group.frequency_days} days`)}{group.tolerance_days ? `, ±${group.tolerance_days} day` : ''}.</T> : null}

      <View style={{ marginTop: 14 }}>
        <KV k="Assigned"><View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}><Dot color={color(slot.person)} /><T>{slot.person}</T></View></KV>
        <KV k="Rest before" end>{slot.rest_before === null ? 'first task' : `${slot.rest_before} day${slot.rest_before === 1 ? '' : 's'}`}</KV>
      </View>

      {n > 1 && group?.sessions ? (
        <>
          <T v="cap" style={{ marginTop: 18 }}>Sessions</T>
          {group.sessions.map((name, i) => {
            const mark = status?.sessions?.[i] ?? null;
            return (
              <View key={name} style={[styles.sess, { borderBottomColor: c.line }]}>
                <View style={{ flex: 1 }}>
                  <Strike n={1} done={mark === 'done' ? 1 : 0} missed={mark === 'missed' ? 1 : 0}>{name}</Strike>
                </View>
                <Pills>
                  <Pill label="Strike" on={mark === 'done'} onPress={() => setSession(i, 'done')} />
                  <Pill label="Missed" on={mark === 'missed'} onPress={() => setSession(i, 'missed')} />
                </Pills>
              </View>
            );
          })}
        </>
      ) : (
        <>
          <Option mark="—" title="Done" sub={`by ${slot.person}, as planned`} on={status?.state === 'done'} onPress={() => save({ state: 'done' })} />
          <Option mark="✗" tone={c.bad} title="Missed" sub="nobody did it" on={status?.state === 'missed'} onPress={() => save({ state: 'missed' })} />
          <Option mark="↺" title="Someone else did it" sub="they get the credit in fairness" on={status?.state === 'covered'}
            onPress={() => others[0] && save({ state: 'covered', covered_by: status?.covered_by ?? others[0] })} />
          {status?.state === 'covered' ? (
            <Pills>
              {others.map((p) => (
                <Pill key={p} label={p} on={status.covered_by === p} left={<Dot color={color(p)} size={7} />}
                  onPress={() => save({ state: 'covered', covered_by: p })} />
              ))}
            </Pills>
          ) : null}
          <Option mark="⋯" title="Not needed" sub="skipped on purpose, not counted against anyone" on={status?.state === 'skipped'}
            onPress={() => save({ state: 'skipped' })} />
        </>
      )}
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}

function Option({ mark, title, sub, on, onPress, tone }: {
  mark: string; title: string; sub: string; on: boolean; onPress: () => void; tone?: string;
}) {
  const { c } = useTheme();
  return (
    <Pressable onPress={onPress} style={[styles.opt, { borderColor: on ? c.tx : c.line2, borderWidth: on ? 1.5 : 1 }]}>
      <T style={{ fontFamily: font.mono, fontSize: 17, width: 24, textAlign: 'center', color: tone ?? c.tx }}>{mark}</T>
      <View style={{ flex: 1 }}>
        <T style={{ fontSize: 14.5 }}>{title}</T>
        <T v="faint" style={{ marginTop: 2 }}>{sub}</T>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  opt: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, borderRadius: 14, marginTop: 10 },
  sess: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth },
});
