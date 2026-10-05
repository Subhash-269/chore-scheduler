import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { addDays, dayNum, plainTask, shortDate, shortDay, todayIso } from '@/data/dates';
import { isOff } from '@/data/derive';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Header, Loading, Note, Screen, T, tap, TopBar } from '@/ui';

/** Ask for a day off. Dates with one of your tasks are marked; an admin picks who covers. */
export default function DayOff() {
  const { c } = useTheme();
  const { household, schedule, me, isAdmin, refresh } = useAppData();
  const [date, setDate] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household || !schedule) return <Loading />;
  if (!me) {
    return <Screen><TopBar back="Back" /><Header title="Ask for a day off" /><Note>Link your account to a roommate first: Settings → You are.</Note></Screen>;
  }

  const days = Array.from({ length: 28 }, (_, i) => addDays(todayIso(), i));
  const mine = new Map(schedule.slots.filter((s) => s.person === me).map((s) => [s.date, s]));

  const send = async () => {
    if (!date) return;
    setBusy(true);
    setErr(null);
    try {
      await api.askDayOff(date, note.trim() || undefined);
      await refresh();
      router.back();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title={date ? `Ask for ${shortDate(date)} off` : 'Pick a day'} disabled={!date} loading={busy} onPress={send} />}>
      <TopBar back="Back" />
      <Header title="Ask for a day off" sub={isAdmin ? 'You’ll approve it yourself in Requests, with a preview of who covers.' : 'An admin sees who could cover, previews it, then approves.'} />
      <View style={styles.grid}>
        {days.map((d) => {
          const off = isOff(household, me, d);
          const task = mine.get(d);
          const on = d === date;
          return (
            <Pressable key={d} disabled={off} onPress={() => { tap(); setDate(d); }}
              style={[styles.day, { borderColor: on ? c.tx : c.line2, backgroundColor: on ? c.tx : off ? c.soft : 'transparent', opacity: off ? 0.5 : 1 }]}>
              <Text style={{ fontFamily: font.mono, fontSize: 8, color: on ? c.bg : c.tx3 }}>{shortDay(d)}</Text>
              <Text style={{ fontFamily: font.monoMedium, fontSize: 14, color: on ? c.bg : c.tx }}>{dayNum(d)}</Text>
              <Text style={{ fontFamily: font.regular, fontSize: 8, color: on ? c.bg : c.tx2 }} numberOfLines={1}>
                {off ? 'off' : task ? plainTask(task.task) : ' '}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <Note>Days with a chore name are when you have a task. Greyed days you’re already off.</Note>
      <T v="cap" style={{ marginTop: 18 }}>Note (optional)</T>
      <TextInput value={note} onChangeText={setNote} placeholder="e.g. travelling" placeholderTextColor={c.tx3} maxLength={200}
        style={{ fontFamily: font.regular, fontSize: 15, color: c.tx, borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 9 }} />
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 16 },
  day: { width: '13%', minWidth: 42, alignItems: 'center', paddingVertical: 6, borderWidth: 1, borderRadius: 9, gap: 1 },
});
