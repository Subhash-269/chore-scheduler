import { router } from 'expo-router';
import { View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { exceptions } from '@/data/usePlan';
import { useTheme } from '@/theme/ThemeProvider';
import { Dot, Header, Loading, Row, Screen, Section, T, Tag, TopBar } from '@/ui';

export default function Team() {
  const { c, personColor } = useTheme();
  const { household, schedule, me } = useAppData();
  if (!household || !schedule) return <Loading />;
  const m = schedule.metrics;
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const offLabel = (p: string) => {
    const days = household.days_off[p] ?? [];
    const never = household.exclusions[p] ?? [];
    const parts = [days.length ? `Off ${days.map((d) => d.slice(0, 3)).join(', ')}` : 'No days off'];
    if (never.length) parts.push(`never ${never.join(', ')}`);
    return parts.join(' · ');
  };

  return (
    <Screen>
      <TopBar left={<T v="cap">{schedule.label} plan</T>} action="Members" onAction={() => router.push('/members')} />
      <Header title="Household" sub={`${m.total_tasks} tasks · spread of ${m.workload_spread} task${m.workload_spread === 1 ? '' : 's'}`} />
      <View style={{ flexDirection: 'row', height: 6, borderRadius: 3, overflow: 'hidden', gap: 2, marginTop: 12 }}>
        {household.roommates.map((p) => <View key={p} style={{ flex: m.workload[p] || 0.001, backgroundColor: color(p) }} />)}
      </View>

      <Section title="People" />
      {household.roommates.map((p, i) => (
        <Row key={p} end={i === household.roommates.length - 1} chevron
          onPress={() => router.push({ pathname: '/person/[name]', params: { name: p } })}
          left={<Dot color={color(p)} />} sub={offLabel(p)} right={`${m.workload[p] ?? 0}`}>
          <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
            <T>{p}</T>{me === p ? <Tag label="you" /> : null}
          </View>
        </Row>
      ))}

      <Section title="Fairness" />
      <Row right={`${m.workload_spread} task${m.workload_spread === 1 ? '' : 's'}`}>Workload spread</Row>
      <Row right={`${m.rest_balance_spread} d`}>Rest balance</Row>
      <Row right={`${m.per_chore_spread}`}>Per-chore spread</Row>
      <Row end chevron onPress={() => router.push('/health')}
        right={<Tag label={`${exceptions(m)} exc`} tone={exceptions(m) ? 'warn' : 'ok'} />}>Schedule health</Row>
      <T v="faint" style={{ marginTop: 14 }} color={c.tx3}>Ranked like main.py: rule breaks, rest exceptions, workload, rest balance, per-chore.</T>
    </Screen>
  );
}
