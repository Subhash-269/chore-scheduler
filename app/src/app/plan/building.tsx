import { router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { View } from 'react-native';

import { usePlan } from '@/data/usePlan';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, Header, Note, ProgressLine, Row, Screen, T, TopBar } from '@/ui';

const MARK = { queued: '○', running: '◐', done: '✓', failed: '✗' } as const;

/** All six algorithms solving the same rules, each row finishing live. */
export default function Building() {
  const { c } = useTheme();
  const { job: jobId } = useLocalSearchParams<{ job: string }>();
  const { job, error } = usePlan(jobId);

  useEffect(() => {
    if (job?.status === 'done') router.replace({ pathname: '/plan/pick', params: { job: job.id } });
  }, [job]);

  const rows = job ? Object.entries(job.progress) : [];
  const finished = rows.filter(([, p]) => p.status === 'done' || p.status === 'failed').length;

  return (
    <Screen footer={job?.status === 'failed' || error ? <Btn title="Back" kind="ghost" onPress={() => router.back()} /> : undefined}>
      <TopBar left={<T v="cap">{finished}/{rows.length || 6} algorithms</T>} action="Cancel" onAction={() => router.back()} />
      <Header title="Building your schedule" sub="Six algorithms solve the same rules, then a rest polish. You'll pick the result." />
      <View style={{ marginTop: 10 }}>
        {rows.map(([key, p], i) => (
          <Row key={key} end={i === rows.length - 1}
            left={<T v="mono" color={p.status === 'failed' ? c.bad : c.tx} style={{ width: 18, fontSize: 14 }}>{MARK[p.status]}</T>}
            right={p.status === 'done' ? `${p.seconds?.toFixed(p.seconds < 0.1 ? 2 : 1)}s` : p.status === 'running' ? 'solving…' : p.status === 'failed' ? 'no result' : 'queued'}
            disabled={p.status === 'queued'}>
            <View>
              <T>{p.label}</T>
              {p.status === 'running' ? <View style={{ marginTop: 7, width: '70%' }}><ProgressLine value={0.5} /></View> : null}
            </View>
          </Row>
        ))}
      </View>
      {job?.status === 'failed' || error ? <Note tone="bad">{job?.error ?? error}</Note> : (
        <Note style={{ textAlign: 'center', marginTop: 24 }}>Usually under a minute</Note>
      )}
    </Screen>
  );
}
