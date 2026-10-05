import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { todayIso } from '@/data/dates';
import { Btn, Header, KV, Loading, Note, Screen, Section, Stepper, T, TopBar } from '@/ui';
import { StepBar } from '@/ui/Onboarding';
import { toggleDay, WeekdayPicker } from '@/ui/WeekdayPicker';

/** Solo step 2: how much a day can hold, and which days stay light. */
export default function SoloWeek() {
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
    <Screen footer={<Btn title="Build my week" onPress={build} loading={busy} />}>
      <TopBar back="Back" />
      <T v="cap">Step 2 / 2</T>
      <StepBar step={2} of={2} />
      <View style={{ height: 18 }} />
      <Header title="Your week" sub="The plan keeps each day under your cap, and the heaviest day as light as it can." />

      <View style={{ marginTop: 10 }}>
        <KV k="Most per day">
          <Stepper value={draft.daily_cap_minutes ?? 60} min={15} max={240} format={(v) => `${v}m`}
            onChange={(v) => setDraft((d) => d && { ...d, daily_cap_minutes: Math.round(v / 5) * 5 })} />
        </KV>
      </View>

      <Section title="Busy days" />
      <T v="meta" style={{ marginTop: 4 }}>Struck-through days stay light.</T>
      <WeekdayPicker off={draft.busy_days ?? []}
        onToggle={(day) => setDraft((d) => d && { ...d, busy_days: toggleDay(d.busy_days ?? [], day) })} />
      <View style={{ marginTop: 10 }}>
        <KV k="Most on a busy day">
          <Stepper value={draft.busy_cap_minutes ?? 15} min={0} max={120} format={(v) => `${v}m`}
            onChange={(v) => setDraft((d) => d && { ...d, busy_cap_minutes: Math.round(v / 5) * 5 })} />
        </KV>
        <KV k="Plan ahead" end>
          <Stepper value={draft.weeks_to_plan} min={1} max={8} format={(v) => `${v}w`}
            onChange={(v) => setDraft((d) => d && { ...d, weeks_to_plan: v })} />
        </KV>
      </View>
      <Note>Daily chores still happen on busy days. Everything else moves around them.</Note>
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
