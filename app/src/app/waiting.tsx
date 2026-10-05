import { router } from 'expo-router';

import { useAppData } from '@/data/AppData';
import { Btn, Header, Note, Screen, T, TopBar } from '@/ui';

/** Members who joined before an admin finished setup or published a plan. */
export default function Waiting() {
  const { membership, phase, refresh } = useAppData();
  return (
    <Screen footer={<Btn kind="ghost" title="Check again" onPress={async () => { await refresh(); router.replace('/'); }} />}>
      <TopBar left={<T v="cap">{membership?.name ?? 'household'}</T>} action="Settings" onAction={() => router.push('/settings')} />
      <Header title="Almost there"
        sub={phase === 'onboarding' ? 'An admin is still setting up chores and roommates.' : 'An admin is picking the first schedule.'} />
      <Note>You’ll see Today and the fridge board as soon as a schedule is published.</Note>
    </Screen>
  );
}
