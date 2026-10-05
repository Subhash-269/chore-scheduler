import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { daysBetween, dayNum, plainTask, shortDay } from '@/data/dates';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, Dot, Header, Loading, Note, Row, Screen, Section, T, TopBar } from '@/ui';

/** Offer one of your tasks in exchange for someone else's, within a week either side. */
export default function Swap() {
  const { c, personColor } = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { household, schedule, refresh } = useAppData();
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household || !schedule) return <Loading />;

  const mine = schedule.slots.find((s) => s.id === id);
  if (!mine) return <Screen><TopBar back="Back" /><Note>That task isn’t in the live schedule any more.</Note></Screen>;
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const candidates = schedule.slots.filter((s) => s.person !== mine.person && Math.abs(daysBetween(mine.date, s.date)) <= 7);
  const dates = [...new Set(candidates.map((s) => s.date))];
  const chosen = candidates.find((s) => s.id === pick);

  const send = async () => {
    if (!chosen) return;
    setBusy(true);
    setErr(null);
    try {
      await api.askSwap(mine.id, chosen.id);
      await refresh();
      router.back();
    } catch (e) {
      setErr((e as Error).message);   // e.g. "Bob is off that day" - the server checks the rules
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title={chosen ? `Ask ${chosen.person} to swap` : 'Pick a task to trade for'} disabled={!chosen} loading={busy} onPress={send} />}>
      <TopBar back="Back" />
      <Header title="Swap a task" cap={`${shortDay(mine.date)} ${dayNum(mine.date)} · ${plainTask(mine.task)}`}
        sub={`You give ${plainTask(mine.task)} and take one of these instead. They accept or decline.`} />
      {err ? <Note tone="bad">{err}</Note> : null}
      {dates.map((d) => (
        <View key={d}>
          <Section title={`${shortDay(d)} ${dayNum(d)}`} />
          {candidates.filter((s) => s.date === d).map((s, i, arr) => (
            <Row key={s.id} end={i === arr.length - 1} onPress={() => setPick(s.id)}
              left={<View style={{ width: 16, height: 16, borderRadius: 8, borderWidth: pick === s.id ? 5 : 1.5, borderColor: pick === s.id ? c.tx : c.line2 }} />}
              right={<View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}><Dot color={color(s.person)} /><T v="meta">{s.person}</T></View>}>
              {plainTask(s.task)}
            </Row>
          ))}
        </View>
      ))}
      <Note>Days off, exclusions and one-task-a-day are checked before the request is sent.</Note>
    </Screen>
  );
}
