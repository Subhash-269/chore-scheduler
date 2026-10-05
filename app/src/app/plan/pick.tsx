import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { exceptions, usePlan } from '@/data/usePlan';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, BtnRow, Header, Loading, Note, Row, Screen, T, Tag, TopBar } from '@/ui';
import { WeekStrip } from '@/ui/WeekStrip';

/** The mobile version of main.py's "switch schedules, export, or quit" loop. */
export default function Pick() {
  const { c } = useTheme();
  const { job: jobId } = useLocalSearchParams<{ job: string }>();
  const { job, error } = usePlan(jobId);
  const { household, refresh, isAdmin } = useAppData();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (error) return <Screen><TopBar back="Back" /><Note tone="bad">{error}</Note></Screen>;
  if (!job?.result || !household) return <Loading label="loading candidates…" />;

  const candidates = job.result.candidates;
  const solo = household.mode === 'solo';
  const chosen = candidates.find((x) => x.key === selected) ?? candidates[0];

  const publish = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.publish(job.id, chosen.key);
      await refresh();
      router.replace('/today');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={
      <View style={{ gap: 8 }}>
        <Note style={{ marginTop: 0 }}>{solo ? 'over = days past your cap · heaviest = minutes on the busiest normal day' : 'exc = rule exceptions · spread = most minus fewest tasks'}</Note>
        <BtnRow>
          <Btn kind="ghost" title="Preview" onPress={() => router.push({ pathname: '/plan/preview', params: { job: job.id, key: chosen.key } })} />
          <Btn title={`Use ${chosen.label}`} onPress={publish} loading={busy} disabled={!isAdmin} />
        </BtnRow>
      </View>
    }>
      <TopBar back="Back" />
      <Header title={solo ? 'Pick your week' : 'Pick a schedule'}
        sub={solo ? 'Balanced keeps every day under your cap and the heaviest day as light as possible. Earliest is the naive plan, for comparison.'
          : 'Ranked by rule breaks, then rest, then fairness. Only MILP is proven optimal.'} />
      {job.result.warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 16, paddingBottom: 4 }}>
        <T v="cap">plan</T><T v="cap">{solo ? 'over · heaviest' : 'exc · spread'}</T>
      </View>
      {candidates.map((cand, i) => {
        const on = cand.key === chosen.key;
        return (
          <View key={cand.key}>
            <Row end={on || i === candidates.length - 1} onPress={() => setSelected(cand.key)}
              left={<View style={{ width: 16, height: 16, borderRadius: 8, borderWidth: on ? 5 : 1.5, borderColor: on ? c.tx : c.line2 }} />}
              right={solo ? `${cand.metrics.days_over_cap?.length ?? 0} · ${cand.metrics.heaviest_day_minutes}m` : `${exceptions(cand.metrics)} · ${cand.metrics.workload_spread}`}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <T>{cand.label}</T>
                {cand.proven ? <Tag label="proven" tone="inv" /> : null}
                {i === 0 ? <Tag label="best" /> : null}
              </View>
            </Row>
            {on ? (
              <Pressable onPress={() => router.push({ pathname: '/plan/preview', params: { job: job.id, key: cand.key } })}
                style={{ flexDirection: 'row', alignItems: 'flex-start', paddingLeft: 28, paddingBottom: 12,
                  borderBottomWidth: i === candidates.length - 1 ? 0 : 1, borderBottomColor: c.line }}>
                <WeekStrip household={household} slots={cand.slots} start={job.result!.start_day} />
                <View style={{ flex: 1 }} />
                <T v="link" style={{ alignSelf: 'center', fontSize: 11.5 }}>Preview ›</T>
              </Pressable>
            ) : null}
          </View>
        );
      })}
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
