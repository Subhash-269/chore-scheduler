import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { Btn, Header, KV, Loading, Note, Screen, Section, Seg, Stepper, T, TopBar } from '@/ui';
import { toggleDay, WeekdayPicker } from '@/ui/WeekdayPicker';

/** House rules: rest buffer, planning window, roommate-order seed. Solo: daily cap and busy days. */
export default function Rules() {
  const { household, saveHousehold } = useAppData();
  const [buffer, setBuffer] = useState(household?.buffer_days ?? 2);
  const [weeks, setWeeks] = useState(household?.weeks_to_plan ?? 4);
  const [seed, setSeed] = useState<number | 'auto'>(household?.random_seed ?? 42);
  const [cap, setCap] = useState(household?.daily_cap_minutes ?? 60);
  const [busyDays, setBusyDays] = useState<string[]>(household?.busy_days ?? []);
  const [busyCap, setBusyCap] = useState(household?.busy_cap_minutes ?? 15);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household) return <Loading />;
  const solo = household.mode === 'solo';

  const save = async (replan: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      await saveHousehold(solo
        ? { ...household, weeks_to_plan: weeks, daily_cap_minutes: cap, busy_days: busyDays, busy_cap_minutes: busyCap }
        : { ...household, buffer_days: buffer, weeks_to_plan: weeks, random_seed: seed });
      if (replan) router.replace('/plan/start');
      else router.back();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const round5 = (v: number) => Math.round(v / 5) * 5;

  return (
    <Screen footer={<View style={{ gap: 8 }}><Btn title="Save & re-plan" onPress={() => save(true)} loading={busy} /><Btn kind="text" title="Save only" onPress={() => save(false)} /></View>}>
      <TopBar back="Setup" />
      {solo ? (
        <>
          <Header title="Your week" sub="The plan keeps each day under these, and the heaviest day as light as it can." />
          <Section title="Most per day" />
          <KV k="Normal days"><Stepper value={cap} min={15} max={240} format={(v) => `${v}m`} onChange={(v) => setCap(round5(v))} /></KV>
          <Section title="Busy days" />
          <T v="meta" style={{ marginTop: 4 }}>Struck-through days stay light.</T>
          <WeekdayPicker off={busyDays} onToggle={(d) => setBusyDays((cur) => toggleDay(cur, d))} />
          <KV k="Most on a busy day"><Stepper value={busyCap} min={0} max={120} format={(v) => `${v}m`} onChange={(v) => setBusyCap(round5(v))} /></KV>
          <Note>Daily chores still happen on busy days; everything else moves around them.</Note>
        </>
      ) : (
        <>
          <Header title="House rules" sub="These apply to every chore unless a chore overrides them." />
          <Section title="Rest buffer" />
          <KV k="Days off after any task"><Stepper value={buffer} min={0} max={6} format={(v) => `${v}d`} onChange={setBuffer} /></KV>
          <Note>More rest is nicer, but with few people and daily chores some days won’t have anyone fully rested. The solver reports those as unavoidable exceptions.</Note>
        </>
      )}

      <Section title="Planning window" />
      <KV k="Plan ahead"><Stepper value={weeks} min={1} max={8} format={(v) => `${v}w`} onChange={setWeeks} /></KV>

      {solo ? null : (
        <>
          <Section title="Roommate order" />
          <Seg style={{ marginTop: 10 }} value={seed === 'auto' ? 'auto' : 'fixed'}
            onChange={(v) => setSeed(v === 'auto' ? 'auto' : 42)}
            options={[{ value: 'fixed', label: 'Keep order (seed)' }, { value: 'auto', label: 'Fresh shuffle' }]} />
          {seed !== 'auto' ? <KV k="Seed" end><Stepper value={seed} min={1} max={9999} onChange={setSeed} /></KV> : null}
          <Note>Order is a real tie-breaker between equally good schedules. A fixed seed is reproducible; bump it for a different but repeatable rotation.</Note>
        </>
      )}
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
