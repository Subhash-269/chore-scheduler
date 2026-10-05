import { Redirect } from 'expo-router';

import { useAppData } from '@/data/AppData';
import { Loading } from '@/ui';

/** Entry: send people wherever their account and household currently are. */
export default function Index() {
  const { phase, isAdmin, draft } = useAppData();
  if (phase === 'loading') return <Loading label="looking for your household…" />;
  if (phase === 'offline') return <Redirect href="/connect" />;
  if (phase === 'signedOut') return <Redirect href="/auth" />;
  if (phase === 'noHousehold') return <Redirect href="/onboarding" />;
  if (phase === 'onboarding') {
    if (!isAdmin) return <Redirect href="/waiting" />;
    return <Redirect href={draft?.mode === 'solo' ? '/onboarding/chores' : '/onboarding/roommates'} />;
  }
  if (phase === 'unplanned') return <Redirect href={isAdmin ? '/plan/start' : '/waiting'} />;
  return <Redirect href="/today" />;
}
