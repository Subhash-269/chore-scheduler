import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { todayIso } from '@/data/dates';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, Dot, Header, KV, Loading, Note, Screen, Stepper, T, TopBar } from '@/ui';
import { StepBar } from '@/ui/Onboarding';
import { toggleDay, WeekdayPicker } from '@/ui/WeekdayPicker';

export default function Availability() {
  const { personColor } = useTheme();
  const { draft, setDraft, saveHousehold, refresh } = useAppData();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!draft) return <Loading />;

  const build = async () => {
    setBusy(true);
    setErr(null);
    try {
      await saveHousehold({ ...draft, start_day: todayIso() });
      const { job_id } = await api.startPlan();
      setDraft(null);
      refresh();
      router.replace({ pathname: '/plan/building', params: { job: job_id } });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title="Build schedule" onPress={build} loading={busy} />}>
      <TopBar back="Back" />
      <T v="cap">Step 3 / 3</T>
      <StepBar step={3} />
      <View style={{ height: 18 }} />
      <Header title="Who's around when?" sub="Tap a day to mark someone off every week. Specific dates and exclusions live in Setup." />
      {draft.roommates.map((p) => (
        <View key={p} style={{ marginTop: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 7 }}>
            <Dot color={personColor(p, draft.roommates, draft.colors)} />
            <T style={{ fontSize: 13 }}>{p}</T>
          </View>
          <WeekdayPicker off={draft.days_off[p] ?? []}
            onToggle={(day) => setDraft((d) => d && { ...d, days_off: { ...d.days_off, [p]: toggleDay(d.days_off[p] ?? [], day) } })} />
        </View>
      ))}
      <View style={{ marginTop: 18 }}>
        <KV k="Rest after any task">
          <Stepper value={draft.buffer_days} min={0} max={6} format={(v) => `${v}d`}
            onChange={(v) => setDraft((d) => d && { ...d, buffer_days: v })} />
        </KV>
        <KV k="Plan ahead" end>
          <Stepper value={draft.weeks_to_plan} min={1} max={8} format={(v) => `${v}w`}
            onChange={(v) => setDraft((d) => d && { ...d, weeks_to_plan: v })} />
        </KV>
      </View>
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
