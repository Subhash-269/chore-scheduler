import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, TextInput, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import type { ChoreGroup } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Dot, KV, Loading, Note, Pill, Pills, Screen, Section, Seg, Stepper, TopBar } from '@/ui';

const NEW = '__new__';
const DEFAULT_SESSIONS = ['Breakfast', 'Lunch', 'Dinner', 'Late', 'Extra', 'Extra 2'];

/** Edit (or add) a chore group - the mobile version of a chore_groups entry. */
export default function EditChore() {
  const { c, personColor } = useTheme();
  const { name } = useLocalSearchParams<{ name: string }>();
  const { household, saveHousehold } = useAppData();
  const isNew = name === NEW;
  const original = household?.chore_groups.find((g) => g.name === name);
  const [g, setG] = useState<ChoreGroup>(original ?? { name: '', tasks: [], frequency_days: 7, tolerance_days: 1 });
  const [taskDraft, setTaskDraft] = useState('');
  // exclusions are per person; edit them here as "who can do it" for this chore's tasks
  const [excluded, setExcluded] = useState<string[]>(
    () => household?.roommates.filter((p) => (household.exclusions[p] ?? []).includes(name)) ?? []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household) return <Loading />;

  const piggy = !!g.piggyback_on;
  const solo = household.mode === 'solo';
  const hosts = household.chore_groups.filter((x) => x.name !== name && !x.piggyback_on);
  const sessions = g.sessions?.length ?? 1;

  const save = async () => {
    const groupName = g.name.trim();
    if (!groupName) return setErr('Give the chore a name.');
    const tasks = g.tasks.length ? g.tasks : [groupName];
    const clean: ChoreGroup = piggy
      ? { name: groupName, tasks, piggyback_on: g.piggyback_on, every_nth: g.every_nth ?? 2, tolerance_days: g.tolerance_days ?? 0, sessions: g.sessions, minutes: g.minutes }
      : { name: groupName, tasks, frequency_days: g.frequency_days ?? 7, tolerance_days: g.tolerance_days ?? 0, buffer_days: g.buffer_days, sessions: g.sessions, minutes: g.minutes };
    const groups = isNew ? [...household.chore_groups, clean]
      : household.chore_groups.map((x) => (x.name === name ? clean : x.piggyback_on === name ? { ...x, piggyback_on: groupName } : x));
    const exclusions = Object.fromEntries(household.roommates.map((p) => {
      const rest = (household.exclusions[p] ?? []).filter((e) => e !== name && e !== groupName);
      return [p, excluded.includes(p) ? [...rest, groupName] : rest];
    }));
    setBusy(true);
    setErr(null);
    try {
      await saveHousehold({ ...household, chore_groups: groups, exclusions });
      router.back();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = () => {
    const riders = household.chore_groups.filter((x) => x.piggyback_on === name).map((x) => x.name);
    Alert.alert(`Delete ${name}?`, riders.length ? `${riders.join(', ')} ride on it and will be deleted too.` : 'It disappears from the next re-plan.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        try {
          await saveHousehold({
            ...household,
            chore_groups: household.chore_groups.filter((x) => x.name !== name && x.piggyback_on !== name),
            exclusions: Object.fromEntries(household.roommates.map((p) => [p, (household.exclusions[p] ?? []).filter((e) => e !== name)])),
          });
          router.back();
        } catch (e) { setErr((e as Error).message); }
      } },
    ]);
  };

  const addTask = () => {
    const t = taskDraft.trim();
    if (t && !g.tasks.includes(t)) setG({ ...g, tasks: [...g.tasks, t] });
    setTaskDraft('');
  };

  const input = { fontFamily: font.regular, fontSize: 15, color: c.tx, paddingVertical: 8 };

  return (
    <Screen footer={!isNew ? <Btn kind="danger" title="Delete chore" onPress={remove} /> : undefined}>
      <TopBar back="Cancel" action={isNew ? 'Add' : 'Save'} onAction={save} />
      <TextInput value={g.name} onChangeText={(v) => setG({ ...g, name: v })} placeholder="Chore name, e.g. Mop" placeholderTextColor={c.tx3}
        style={{ fontFamily: font.semibold, fontSize: 24, letterSpacing: -0.6, color: c.tx, paddingVertical: 4 }} />

      <Section title="Tasks in this group" />
      <Pills>
        {g.tasks.map((t) => <Pill key={t} label={`${t} ×`} onPress={() => setG({ ...g, tasks: g.tasks.filter((x) => x !== t) })} />)}
        <View style={{ flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: c.line2, borderRadius: 20, paddingHorizontal: 10 }}>
          <TextInput value={taskDraft} onChangeText={setTaskDraft} onSubmitEditing={addTask} placeholder="+ task"
            placeholderTextColor={c.tx3} style={[input, { fontSize: 12, paddingVertical: 5, minWidth: 60 }]} />
        </View>
      </Pills>
      <Note>Each task gets its own person on the day. Leave empty to use the chore name.</Note>

      <Section title="Repeats" />
      <Seg style={{ marginTop: 8 }} value={piggy ? 'piggy' : 'every'}
        onChange={(v) => setG(v === 'piggy'
          ? { ...g, piggyback_on: hosts[0]?.name, every_nth: g.every_nth ?? 2, frequency_days: undefined }
          : { ...g, piggyback_on: undefined, every_nth: undefined, frequency_days: g.frequency_days ?? 7 })}
        options={[{ value: 'every', label: 'Every N days' }, { value: 'piggy', label: 'Piggyback' }]} />
      <View style={{ marginTop: 6 }}>
        {piggy ? (
          <>
            <KV k="Rides on">
              <Pills>{hosts.map((h) => <Pill key={h.name} label={h.name} on={g.piggyback_on === h.name} onPress={() => setG({ ...g, piggyback_on: h.name })} />)}</Pills>
            </KV>
            <KV k="Every nth time"><Stepper value={g.every_nth ?? 2} min={1} max={10} onChange={(v) => setG({ ...g, every_nth: v })} /></KV>
          </>
        ) : (
          <>
            <KV k="Every"><Stepper value={g.frequency_days ?? 7} min={1} max={60} format={(v) => `${v}d`} onChange={(v) => setG({ ...g, frequency_days: v })} /></KV>
            {solo ? null : (
              <KV k="Own rest buffer">
                <Stepper value={g.buffer_days ?? household.buffer_days} min={0} max={10} format={(v) => (g.buffer_days == null ? `house ${v}d` : `${v}d`)}
                  onChange={(v) => setG({ ...g, buffer_days: v })} />
              </KV>
            )}
          </>
        )}
        {solo ? (
          <KV k="Takes about">
            <Stepper value={g.minutes ?? 15} min={5} max={180} format={(v) => `${v}m`} onChange={(v) => setG({ ...g, minutes: Math.round(v / 5) * 5 || 5 })} />
          </KV>
        ) : null}
        <KV k="Tolerance"><Stepper value={g.tolerance_days ?? 0} min={0} max={5} format={(v) => `±${v}`} onChange={(v) => setG({ ...g, tolerance_days: v })} /></KV>
        <KV k="Times per day" end>
          <Stepper value={sessions} min={1} max={6}
            onChange={(v) => setG({ ...g, sessions: v === 1 ? null : DEFAULT_SESSIONS.slice(0, v).map((d, i) => g.sessions?.[i] ?? d) })} />
        </KV>
      </View>
      {sessions > 1 ? <Note>One person does all {sessions} sessions that day. Each one gets its own strike on the fridge board.</Note> : null}

      {solo ? null : <><Section title="Who can do it" />
      <Pills>
        {household.roommates.map((p) => {
          const can = !excluded.includes(p);
          return (
            <Pill key={p} label={p} on={can} off={!can} left={<Dot color={personColor(p, household.roommates, household.colors)} size={7} />}
              onPress={() => setExcluded(can ? [...excluded, p] : excluded.filter((x) => x !== p))} />
          );
        })}
      </Pills>
      <Note>Struck-through people are never assigned this chore. The solver checks there are still enough people for the rest buffer.</Note></>}
      {err ? <Note tone="bad">{err}</Note> : null}
      <Btn style={{ marginTop: 18 }} title={isNew ? 'Add chore' : 'Save'} onPress={save} loading={busy} />
    </Screen>
  );
}
