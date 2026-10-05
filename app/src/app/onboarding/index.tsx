import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { api, setHouseholdId } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { emptyHousehold, emptySoloHousehold } from '@/data/presets';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Header, Note, Screen, T, Tag, tap, TopBar } from '@/ui';

type Choice = 'household' | 'join' | 'solo';

const CHOICES: { key: Choice; title: string; body: string; soon?: string }[] = [
  { key: 'household', title: 'Start a household', body: 'Set up chores and roommates, then invite everyone with a code.' },
  { key: 'join', title: 'Join a household', body: 'I have a code from a roommate.' },
  { key: 'solo', title: 'Just me', body: 'Spread my chores evenly across the week so no day gets heavy.' },
];

/** Who's this for? - the one fork in onboarding. */
export default function Fork() {
  const { c } = useTheme();
  const { setDraft, refresh, user, setMe } = useAppData();
  const [choice, setChoice] = useState<Choice>('household');
  const [name, setName] = useState('Home');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const next = async () => {
    if (choice === 'join') return router.push('/onboarding/join');
    setBusy(true);
    setErr(null);
    try {
      const solo = choice === 'solo';
      const h = await api.createHousehold(solo ? 'Just me' : name.trim() || 'Home');
      await setHouseholdId(h.id);
      await refresh();
      const me = user?.name ?? 'Me';
      setDraft(solo ? emptySoloHousehold(me) : { ...emptyHousehold(), roommates: user ? [user.name] : [] });
      await setMe(me);
      router.push(solo ? '/onboarding/chores' : '/onboarding/roommates');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title="Continue" onPress={next} loading={busy} />}>
      <TopBar left={<T v="cap">welcome{user ? `, ${user.name}` : ''}</T>} action="Settings" onAction={() => router.push('/settings')} />
      <View style={{ height: 24 }} />
      <Header title="Who's this for?" sub="You can be in more than one household, and switch later." />
      {CHOICES.map((o) => {
        const on = o.key === choice;
        return (
          <Pressable key={o.key} disabled={!!o.soon} onPress={() => { tap(); setChoice(o.key); }}
            style={[styles.card, { borderColor: on ? c.tx : c.line2, borderWidth: on ? 1.5 : 1, opacity: o.soon ? 0.45 : 1 }]}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <T v="h2">{o.title}</T>
              {o.soon ? <Tag label={o.soon} /> : null}
            </View>
            <T v="meta" style={{ marginTop: 4 }}>{o.body}</T>
            {on && o.key === 'household' ? (
              <TextInput value={name} onChangeText={setName} placeholder="Household name" placeholderTextColor={c.tx3}
                style={{ fontFamily: font.regular, fontSize: 15, color: c.tx, borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 8, marginTop: 10 }} />
            ) : null}
          </Pressable>
        );
      })}
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 16, padding: 16, marginTop: 12 },
});
