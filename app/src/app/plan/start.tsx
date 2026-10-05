import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { addDays, rangeLabel, todayIso } from '@/data/dates';
import { Btn, Header, KV, Note, Screen, Stepper, TopBar } from '@/ui';

/** Start a (re-)plan: pick the window, then run all six algorithms. */
export default function StartPlan() {
  const { household, schedule } = useAppData();
  const [weeks, setWeeks] = useState(household?.weeks_to_plan ?? 4);
  const [start, setStart] = useState(() => {
    // continue right after the live schedule, or from today
    if (schedule) {
      const next = addDays(schedule.start_day, schedule.days);
      return next > todayIso() ? next : todayIso();
    }
    return todayIso();
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { job_id } = await api.startPlan({ start_day: start, weeks_to_plan: weeks });
      router.replace({ pathname: '/plan/building', params: { job: job_id } });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title="Build schedule" onPress={go} loading={busy} />}>
      <TopBar back={schedule ? 'Back' : undefined} />
      <Header title={schedule ? 'Plan the next stretch' : 'Build your first schedule'}
        sub="Six algorithms solve the same rules. You compare and pick before anything is saved." />
      <View style={{ marginTop: 18 }}>
        <KV k="Starts">
          <Stepper value={0} min={-7} max={60}
            format={() => rangeLabel(start, start).split(' – ')[0]}
            onChange={(d) => setStart(addDays(start, d))} />
        </KV>
        <KV k="Length" end>
          <Stepper value={weeks} min={1} max={8} format={(v) => `${v}w`} onChange={setWeeks} />
        </KV>
      </View>
      <Note>{rangeLabel(start, addDays(start, weeks * 7 - 1))}. Rest owed, chore phase and fairness carry over from the last published plan.</Note>
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
