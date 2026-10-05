import { Redirect } from 'expo-router';

import { useAppData } from '@/data/AppData';
import { Loading } from '@/ui';

/** Entry: send people wherever the household currently is. */
export default function Index() {
  const { phase } = useAppData();
  if (phase === 'loading') return <Loading label="looking for your household…" />;
  if (phase === 'offline') return <Redirect href="/connect" />;
  if (phase === 'onboarding') return <Redirect href="/onboarding" />;
  if (phase === 'unplanned') return <Redirect href="/plan/start" />;
  return <Redirect href="/today" />;
}
