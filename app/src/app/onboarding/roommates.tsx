import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Dot, Header, Loading, Note, Row, Screen, T, Tag, TopBar } from '@/ui';
import { StepBar } from '@/ui/Onboarding';

export default function Roommates() {
  const { c, personColor } = useTheme();
  const { draft, setDraft, me, setMe } = useAppData();
  const [name, setName] = useState('');
  if (!draft) return <Loading />;
  const people = draft.roommates;

  const add = () => {
    const n = name.trim();
    if (!n || people.includes(n)) return;
    setDraft((d) => d && { ...d, roommates: [...d.roommates, n] });
    if (!me && people.length === 0) setMe(n);
    setName('');
  };
  const remove = (p: string) => {
    setDraft((d) => d && { ...d, roommates: d.roommates.filter((x) => x !== p) });
    if (me === p) setMe(null);
  };

  return (
    <Screen footer={<Btn title="Next: chores" disabled={people.length < 2} onPress={() => router.push('/onboarding/chores')} />}>
      <TopBar back="Back" />
      <T v="cap">Step 1 / 3</T>
      <StepBar step={1} />
      <View style={{ height: 18 }} />
      <Header title="Who lives here?" sub="Everyone who shares chores. Tap a name to mark which one is you." />
      <View style={{ marginTop: 8 }}>
        {people.map((p) => (
          <Row key={p} onPress={() => setMe(p)}
            left={<Dot color={personColor(p, people, draft.colors)} />}
            right={<Pressable hitSlop={12} onPress={() => remove(p)}><T v="meta" color={c.tx3} style={{ fontSize: 16 }}>×</T></Pressable>}>
            <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
              <T>{p}</T>
              {me === p ? <Tag label="you" /> : null}
            </View>
          </Row>
        ))}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 }}>
          <View style={{ width: 8, height: 8, borderRadius: 4, borderWidth: 1, borderStyle: 'dashed', borderColor: c.tx3 }} />
          <TextInput
            value={name}
            onChangeText={setName}
            onSubmitEditing={add}
            returnKeyType="done"
            blurOnSubmit={false}
            placeholder="Add roommate…"
            placeholderTextColor={c.tx3}
            style={{ flex: 1, fontFamily: font.regular, fontSize: 14.5, color: c.tx, paddingVertical: 6 }}
          />
          {name.trim() ? <Pressable onPress={add} hitSlop={10}><T v="link">Add</T></Pressable> : null}
        </View>
      </View>
      <Note>Order doesn’t matter: it’s shuffled every run so nobody is always picked first.</Note>
      {people.length < 2 ? <Note>Add at least two people. A solo mode is coming in phase 3.</Note> : null}
    </Screen>
  );
}
