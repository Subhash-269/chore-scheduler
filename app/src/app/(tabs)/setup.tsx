import { router } from 'expo-router';

import { useAppData } from '@/data/AppData';
import { addDays, rangeLabel } from '@/data/dates';
import { ruleLabel } from '@/data/presets';
import { exceptions } from '@/data/usePlan';
import { Btn, Header, Loading, Note, Row, Screen, Section, T, Tag, TopBar } from '@/ui';

export default function Setup() {
  const { household, schedule, warnings } = useAppData();
  if (!household) return <Loading />;
  const end = schedule ? addDays(schedule.start_day, schedule.days - 1) : null;

  return (
    <Screen>
      <TopBar left={<T v="cap">config</T>} action="+ Add chore"
        onAction={() => router.push({ pathname: '/chore/[name]', params: { name: '__new__' } })} />
      <Header title="Setup" sub="Everything the solver uses. Changes apply on the next re-plan." />
      {warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}

      <Section title="Chores" />
      {household.chore_groups.map((g, i) => (
        <Row key={g.name} chevron end={i === household.chore_groups.length - 1} right={ruleLabel(g)}
          sub={g.tasks.length > 1 ? g.tasks.join(' · ') : g.sessions?.length ? `${g.sessions.length}× a day` : undefined}
          onPress={() => router.push({ pathname: '/chore/[name]', params: { name: g.name } })}>
          {g.name}
        </Row>
      ))}

      <Section title="House rules" />
      <Row chevron right={`${household.buffer_days} day${household.buffer_days === 1 ? '' : 's'}`} onPress={() => router.push('/rules')}>Rest buffer</Row>
      <Row chevron right={`${household.weeks_to_plan} weeks`} onPress={() => router.push('/rules')}>Planning window</Row>
      <Row chevron end right={household.random_seed === 'auto' ? 'fresh each run' : `seed ${household.random_seed}`} onPress={() => router.push('/rules')}>Roommate order</Row>

      <Section title="Schedule" />
      {schedule && end ? (
        <>
          <Row chevron right={<Tag label={`${exceptions(schedule.metrics)} exc`} tone={exceptions(schedule.metrics) ? 'warn' : 'ok'} />}
            sub={`${schedule.label} · ${rangeLabel(schedule.start_day, end)}`} onPress={() => router.push('/health')}>
            Schedule health
          </Row>
          <Row chevron end onPress={() => router.push('/settings')}>Appearance, you, server</Row>
        </>
      ) : <Row chevron end onPress={() => router.push('/settings')}>Appearance, you, server</Row>}
      <Btn style={{ marginTop: 18 }} title={schedule ? 'Re-plan' : 'Build schedule'} onPress={() => router.push('/plan/start')} />
    </Screen>
  );
}
