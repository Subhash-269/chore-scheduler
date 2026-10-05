import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { emptyHousehold } from '@/data/presets';
import { useTheme } from '@/theme/ThemeProvider';
import { Btn, Header, Screen, T, Tag, tap, TopBar } from '@/ui';

type Choice = 'household' | 'solo' | 'join';

const CHOICES: { key: Choice; title: string; body: string; soon?: string }[] = [
  { key: 'household', title: 'A household', body: 'Share chores fairly between roommates, with rest days between turns.' },
  { key: 'solo', title: 'Just me', body: 'Spread my chores evenly across the week so no day gets heavy.', soon: 'phase 3' },
  { key: 'join', title: 'Join a household', body: 'I have a code from a roommate.', soon: 'phase 2' },
];

/** Who's this for? - the one fork in onboarding. */
export default function Fork() {
  const { c } = useTheme();
  const { setDraft } = useAppData();
  const [choice, setChoice] = useState<Choice>('household');

  const next = () => {
    setDraft(emptyHousehold());
    router.push('/onboarding/roommates');
  };

  return (
    <Screen footer={<Btn title="Continue" onPress={next} />}>
      <TopBar left={<T v="cap">welcome</T>} />
      <View style={{ height: 24 }} />
      <Header title="Who's this for?" sub="You can switch later. Your history comes with you." />
      {CHOICES.map((o) => {
        const on = o.key === choice;
        return (
          <Pressable
            key={o.key}
            disabled={!!o.soon}
            onPress={() => { tap(); setChoice(o.key); }}
            style={[styles.card, { borderColor: on ? c.tx : c.line2, borderWidth: on ? 1.5 : 1, opacity: o.soon ? 0.45 : 1 }]}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <T v="h2">{o.title}</T>
              {o.soon ? <Tag label={o.soon} /> : null}
            </View>
            <T v="meta" style={{ marginTop: 4 }}>{o.body}</T>
          </Pressable>
        );
      })}
    </Screen>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 16, padding: 16, marginTop: 12 },
});
