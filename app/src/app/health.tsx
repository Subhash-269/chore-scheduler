import { View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { addDays, rangeLabel } from '@/data/dates';
import { exceptions } from '@/data/usePlan';
import { useTheme } from '@/theme/ThemeProvider';
import { Dot, Header, Loading, Note, Row, Screen, Section, T, Tag, TopBar } from '@/ui';

/** Unavoidable exceptions, explained - the mobile version of main.py's ⚠️ printout. */
export default function Health() {
  const { c, personColor } = useTheme();
  const { household, schedule } = useAppData();
  if (!household || !schedule) return <Loading />;
  const m = schedule.metrics;
  const total = exceptions(m);
  const end = addDays(schedule.start_day, schedule.days - 1);

  return (
    <Screen>
      <TopBar back="Back" />
      <Header title="Schedule health" cap={`${schedule.label} · ${rangeLabel(schedule.start_day, end)}`}
        sub={total === 0 ? 'No exceptions. Every rule holds.'
          : schedule.proven ? `${total} exception${total === 1 ? '' : 's'}. Proven minimum: no schedule for these rules does better.`
            : `${total} exception${total === 1 ? '' : 's'}. ${schedule.label} is best-effort; MILP may do better.`} />

      {schedule.forced_violations.length ? (
        <>
          <Section title={`Rest buffer · ${schedule.forced_violations.length}`} />
          {schedule.forced_violations.map((v, i) => (
            <Row key={i} end={i === schedule.forced_violations.length - 1}
              left={<Dot color={personColor(String(v.person), household.roommates, household.colors)} />}
              sub={`${v.task1} ${v.date1} → ${v.task2} ${v.date2} · ${Number(v.gap) - 1} rest day(s)`}>
              {String(v.person)}
            </Row>
          ))}
          <Note>No valid alternative existed for these: everyone else was off, resting, or excluded.</Note>
        </>
      ) : m.buffer_violations ? (
        <>
          <Section title={`Rest buffer · ${m.buffer_violations}`} />
          <Note>Some people get less rest than the buffer asks for. Shortest rest is {m.min_rest} day(s).</Note>
        </>
      ) : null}

      {schedule.cadence_violations.length ? (
        <>
          <Section title={`Cadence · ${schedule.cadence_violations.length}`} />
          {schedule.cadence_violations.map((v, i) => (
            <Row key={i} end={i === schedule.cadence_violations.length - 1} left={<Dot color={c.tx3} />}
              sub={`${v.date1} → ${v.date2} · ${v.gap} days apart, usually from last plan's carry-over`}>
              {String(v.group)}
            </Row>
          ))}
        </>
      ) : null}

      <Section title="Checks" />
      <Row right={<Tag label={m.structural_violations ? `${m.structural_violations}` : 'pass'} tone={m.structural_violations ? 'bad' : 'ok'} />}>
        Frequency, piggyback, days off, exclusions
      </Row>
      <Row right={`${m.avg_rest}d avg · ${m.min_rest}d min`}>Rest between tasks</Row>
      <Row end right={`${m.workload_spread}`}>Workload spread</Row>
      <View style={{ height: 8 }} />
      <T v="faint">Validated independently after solving, like main.py’s validation report.</T>
    </Screen>
  );
}
