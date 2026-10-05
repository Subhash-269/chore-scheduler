import { router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { addDays, rangeLabel, todayIso, weekDates } from '@/data/dates';
import { exceptions, usePlan } from '@/data/usePlan';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, BtnRow, Dot, Loading, Note, Screen, T, tap, TopBar } from '@/ui';
import { FridgeGrid } from '@/ui/FridgeGrid';

/** Any of the six candidates on the full board, week by week, before anything is saved. */
export default function Preview() {
  const { c, personColor } = useTheme();
  const params = useLocalSearchParams<{ job: string; key: string }>();
  const { job } = usePlan(params.job);
  const { household, schedule, refresh } = useAppData();
  const [key, setKey] = useState(params.key);
  const [week, setWeek] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const cand = job?.result?.candidates.find((x) => x.key === key) ?? job?.result?.candidates[0];

  // outline anything that differs from the live schedule
  const changed = useMemo(() => {
    const out = new Set<string>();
    if (!schedule || !cand) return out;
    const live = new Map(schedule.slots.map((s) => [s.id, s.person]));
    for (const s of cand.slots) if (live.has(s.id) && live.get(s.id) !== s.person) out.add(s.id);
    return out;
  }, [schedule, cand]);

  if (!job?.result || !cand || !household) return <Loading label="loading preview…" />;
  const result = job.result;
  const weeks = Math.ceil(result.days / 7);
  const start = addDays(result.start_day, week * 7);
  const dates = weekDates(start).filter((d) => d < addDays(result.start_day, result.days));

  const publish = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.publish(job.id, cand.key);
      await refresh();
      router.replace('/today');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen padded={false} footer={
      <BtnRow>
        <Btn kind="ghost" title="Back" onPress={() => router.back()} />
        <Btn title={`Use ${cand.label}`} onPress={publish} loading={busy} />
      </BtnRow>
    }>
      <View style={{ paddingHorizontal: 20 }}>
        <TopBar back="Pick"
          action={weeks > 1 ? `Week ${week + 1}/${weeks} ›` : undefined}
          onAction={() => setWeek((w) => (w + 1) % weeks)} />
        <T v="h1">Preview</T>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 10, borderWidth: 1, borderStyle: 'dashed',
          borderColor: c.tx, borderRadius: 10, paddingVertical: 7, paddingHorizontal: 10 }}>
          <T v="cap" color={c.tx}>preview</T>
          <T v="meta" style={{ flex: 1, fontSize: 11.5 }}>nothing is saved yet</T>
          <T v="mono" style={{ fontSize: 11 }}>{rangeLabel(dates[0], dates[dates.length - 1])}</T>
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingHorizontal: 20, paddingVertical: 12 }}>
        {result.candidates.map((x) => {
          const on = x.key === cand.key;
          return (
            <Pressable key={x.key} onPress={() => { tap(); setKey(x.key); }}
              style={{ borderWidth: 1, borderColor: on ? c.tx : c.line2, backgroundColor: on ? c.tx : 'transparent', borderRadius: 9, paddingVertical: 6, paddingHorizontal: 11 }}>
              <T style={{ fontSize: 12, color: on ? c.bg : c.tx2 }}>{x.label}</T>
            </Pressable>
          );
        })}
      </ScrollView>
      <View style={{ paddingHorizontal: 12 }}>
        <View style={{ flexDirection: 'row', gap: 16, paddingHorizontal: 8, marginBottom: 10 }}>
          <T v="mono">exc <T v="mono" color={c.tx}>{exceptions(cand.metrics)}</T></T>
          <T v="mono">spread <T v="mono" color={c.tx}>{cand.metrics.workload_spread}</T></T>
          <T v="mono">rest bal <T v="mono" color={c.tx}>{cand.metrics.rest_balance_spread}d</T></T>
          {changed.size ? <T v="mono">changed <T v="mono" color={c.tx}>{changed.size}</T></T> : null}
        </View>
        <FridgeGrid household={household} dates={dates} slots={cand.slots} today={todayIso()} changed={changed} showRest />
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 12, paddingHorizontal: 8 }}>
          {household.roommates.map((p) => (
            <View key={p} style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
              <Dot color={personColor(p, household.roommates, household.colors)} size={7} />
              <T v="mono">{cand.metrics.workload[p] ?? 0}</T>
            </View>
          ))}
          <T v="faint">totals</T>
        </View>
        {changed.size ? <Note style={{ paddingHorizontal: 8 }}>Dashed boxes differ from the live schedule.</Note> : null}
        {err ? <Note tone="bad" style={{ paddingHorizontal: 8 }}>{err}</Note> : null}
      </View>
    </Screen>
  );
}
