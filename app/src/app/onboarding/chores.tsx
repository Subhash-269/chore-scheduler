import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { CHORE_PRESETS, ruleLabel } from '@/data/presets';
import type { ChoreGroup } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Header, Loading, Note, Row, Screen, T, Toggle, TopBar } from '@/ui';
import { StepBar } from '@/ui/Onboarding';

export default function Chores() {
  const { c } = useTheme();
  const { draft, setDraft } = useAppData();
  const [custom, setCustom] = useState('');
  if (!draft) return <Loading />;

  const groups = draft.chore_groups;
  const has = (name: string) => groups.some((g) => g.name === name);
  const extras = groups.filter((g) => !CHORE_PRESETS.some((p) => p.name === g.name));

  const toggle = (g: ChoreGroup, on: boolean) => setDraft((d) => {
    if (!d) return d;
    let next = on ? [...d.chore_groups, g] : d.chore_groups.filter((x) => x.name !== g.name);
    // a piggyback chore can't outlive its host
    if (!on) next = next.filter((x) => x.piggyback_on !== g.name);
    return { ...d, chore_groups: next };
  });

  const addCustom = () => {
    const name = custom.trim();
    if (!name || has(name)) return;
    setDraft((d) => d && { ...d, chore_groups: [...d.chore_groups, { name, tasks: [name], frequency_days: 7, tolerance_days: 1 }] });
    setCustom('');
  };

  return (
    <Screen footer={<Btn title="Next: availability" disabled={!groups.length} onPress={() => router.push('/onboarding/availability')} />}>
      <TopBar back="Back" />
      <T v="cap">Step 2 / 3</T>
      <StepBar step={2} />
      <View style={{ height: 18 }} />
      <Header title="What needs doing?" sub="Start from common chores. Fine-tune frequency and who can do what in Setup later." />
      <View style={{ marginTop: 6 }}>
        {CHORE_PRESETS.map(({ on: _on, hint, ...g }) => {
          const hostMissing = !!g.piggyback_on && !has(g.piggyback_on);
          return (
            <Row key={g.name} disabled={hostMissing}
              left={<Toggle on={has(g.name)} disabled={hostMissing} onChange={(v) => toggle(g, v)} />}
              sub={hostMissing ? `needs ${g.piggyback_on}` : hint}
              right={ruleLabel(g)}>
              {g.tasks[0]}
            </Row>
          );
        })}
        {extras.map((g) => (
          <Row key={g.name} left={<Toggle on onChange={() => toggle(g, false)} />} sub="custom · weekly, ±1 day" right={ruleLabel(g)}>
            {g.name}
          </Row>
        ))}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 }}>
          <T v="meta" style={{ width: 34, textAlign: 'center', fontSize: 16 }} color={c.tx3}>+</T>
          <TextInput value={custom} onChangeText={setCustom} onSubmitEditing={addCustom} placeholder="Custom chore…"
            placeholderTextColor={c.tx3} returnKeyType="done"
            style={{ flex: 1, fontFamily: font.regular, fontSize: 14.5, color: c.tx, paddingVertical: 6 }} />
          {custom.trim() ? <Pressable onPress={addCustom} hitSlop={10}><T v="link">Add</T></Pressable> : null}
        </View>
      </View>
      <Note>Mop rides along on every 2nd Vacuum day, like your config.yml does.</Note>
    </Screen>
  );
}
