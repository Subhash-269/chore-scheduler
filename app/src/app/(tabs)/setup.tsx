import { router } from 'expo-router';

import { useAppData } from '@/data/AppData';
import { addDays, rangeLabel } from '@/data/dates';
import { ruleLabel } from '@/data/presets';
import { exceptions } from '@/data/usePlan';
import { Btn, Header, Loading, Note, Row, Screen, Section, T, Tag, TopBar } from '@/ui';

export default function Setup() {
  const { household, schedule, warnings, isAdmin } = useAppData();
  if (!household) return <Loading />;
  const end = schedule ? addDays(schedule.start_day, schedule.days - 1) : null;

  return (
    <Screen>
      <TopBar left={<T v="cap">{isAdmin ? 'config' : 'config · view only'}</T>} action={isAdmin ? '+ Add chore' : undefined}
        onAction={() => router.push({ pathname: '/chore/[name]', params: { name: '__new__' } })} />
      <Header title="Setup" sub={isAdmin ? 'Everything the solver uses. Changes apply on the next re-plan.'
        : 'Admins manage chores, rules and days off. Ask one of them for changes.'} />
      {warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}

      <Section title="Chores" />
      {household.chore_groups.map((g, i) => (
        <Row key={g.name} end={i === household.chore_groups.length - 1} right={ruleLabel(g)}
          sub={g.tasks.length > 1 ? g.tasks.join(' · ') : g.sessions?.length ? `${g.sessions.length}× a day` : undefined}
          disabled={!isAdmin} chevron={isAdmin}
          onPress={() => router.push({ pathname: '/chore/[name]', params: { name: g.name } })}>
          {g.name}
        </Row>
      ))}

      <Section title="House rules" />
      <Row chevron={isAdmin} disabled={!isAdmin} right={`${household.buffer_days} day${household.buffer_days === 1 ? '' : 's'}`} onPress={() => router.push('/rules')}>Rest buffer</Row>
      <Row chevron={isAdmin} disabled={!isAdmin} right={`${household.weeks_to_plan} weeks`} onPress={() => router.push('/rules')}>Planning window</Row>
      <Row chevron={isAdmin} disabled={!isAdmin} end right={household.random_seed === 'auto' ? 'fresh each run' : `seed ${household.random_seed}`} onPress={() => router.push('/rules')}>Roommate order</Row>

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
      {isAdmin ? <Btn style={{ marginTop: 18 }} title={schedule ? 'Re-plan' : 'Build schedule'} onPress={() => router.push('/plan/start')} /> : null}
    </Screen>
  );
}
