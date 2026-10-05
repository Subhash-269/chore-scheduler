import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { Btn, Header, KV, Loading, Note, Screen, Section, Seg, Stepper, TopBar } from '@/ui';

/** House rules: rest buffer, planning window, roommate-order seed. */
export default function Rules() {
  const { household, saveHousehold } = useAppData();
  const [buffer, setBuffer] = useState(household?.buffer_days ?? 2);
  const [weeks, setWeeks] = useState(household?.weeks_to_plan ?? 4);
  const [seed, setSeed] = useState<number | 'auto'>(household?.random_seed ?? 42);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!household) return <Loading />;

  const save = async (replan: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      await saveHousehold({ ...household, buffer_days: buffer, weeks_to_plan: weeks, random_seed: seed });
      if (replan) router.replace('/plan/start');
      else router.back();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<View style={{ gap: 8 }}><Btn title="Save & re-plan" onPress={() => save(true)} loading={busy} /><Btn kind="text" title="Save only" onPress={() => save(false)} /></View>}>
      <TopBar back="Setup" />
      <Header title="House rules" sub="These apply to every chore unless a chore overrides them." />

      <Section title="Rest buffer" />
      <KV k="Days off after any task"><Stepper value={buffer} min={0} max={6} format={(v) => `${v}d`} onChange={setBuffer} /></KV>
      <Note>More rest is nicer, but with few people and daily chores some days won’t have anyone fully rested. The solver reports those as unavoidable exceptions.</Note>

      <Section title="Planning window" />
      <KV k="Plan ahead"><Stepper value={weeks} min={1} max={8} format={(v) => `${v}w`} onChange={setWeeks} /></KV>

      <Section title="Roommate order" />
      <Seg style={{ marginTop: 10 }} value={seed === 'auto' ? 'auto' : 'fixed'}
        onChange={(v) => setSeed(v === 'auto' ? 'auto' : 42)}
        options={[{ value: 'fixed', label: 'Keep order (seed)' }, { value: 'auto', label: 'Fresh shuffle' }]} />
      {seed !== 'auto' ? <KV k="Seed" end><Stepper value={seed} min={1} max={9999} onChange={setSeed} /></KV> : null}
      <Note>Order is a real tie-breaker between equally good schedules. A fixed seed is reproducible; bump it for a different but repeatable rotation.</Note>
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
