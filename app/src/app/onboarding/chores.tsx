import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { useAppData } from '@/data/AppData';
import { CHORE_PRESETS, ruleLabel, SOLO_PRESETS } from '@/data/presets';
import type { ChoreGroup } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Header, Loading, Note, Row, Screen, Stepper, T, Toggle, TopBar } from '@/ui';
import { StepBar } from '@/ui/Onboarding';

export default function Chores() {
  const { c } = useTheme();
  const { draft, setDraft } = useAppData();
  const [custom, setCustom] = useState('');
  if (!draft) return <Loading />;

  const solo = draft.mode === 'solo';
  const presets = solo ? SOLO_PRESETS : CHORE_PRESETS;
  const groups = draft.chore_groups;
  const has = (name: string) => groups.some((g) => g.name === name);
  const current = (name: string) => groups.find((g) => g.name === name);
  const extras = groups.filter((g) => !presets.some((p) => p.name === g.name));

  const toggle = (g: ChoreGroup, on: boolean) => setDraft((d) => {
    if (!d) return d;
    let next = on ? [...d.chore_groups, g] : d.chore_groups.filter((x) => x.name !== g.name);
    // a piggyback chore can't outlive its host
    if (!on) next = next.filter((x) => x.piggyback_on !== g.name);
    return { ...d, chore_groups: next };
  });

  const setMinutes = (name: string, minutes: number) => setDraft((d) => d && {
    ...d, chore_groups: d.chore_groups.map((x) => (x.name === name ? { ...x, minutes } : x)),
  });

  const addCustom = () => {
    const name = custom.trim();
    if (!name || has(name)) return;
    setDraft((d) => d && { ...d, chore_groups: [...d.chore_groups,
      { name, tasks: [name], frequency_days: 7, tolerance_days: 1, ...(d.mode === 'solo' ? { minutes: 15 } : {}) }] });
    setCustom('');
  };

  // solo: minutes stepper on the right; household: the frequency label
  const right = (g: ChoreGroup) => (solo && has(g.name)
    ? <Stepper value={current(g.name)?.minutes ?? 15} min={5} max={180} format={(v) => `${v}m`}
        onChange={(v) => setMinutes(g.name, Math.round(v / 5) * 5 || 5)} />
    : ruleLabel(g));

  return (
    <Screen footer={<Btn title={solo ? 'Next: your week' : 'Next: availability'} disabled={!groups.length}
      onPress={() => router.push(solo ? '/onboarding/solo-week' : '/onboarding/availability')} />}>
      <TopBar back="Back" />
      <T v="cap">{solo ? 'Step 1 / 2' : 'Step 2 / 3'}</T>
      <StepBar step={solo ? 1 : 2} of={solo ? 2 : 3} />
      <View style={{ height: 18 }} />
      <Header title={solo ? 'Your chores' : 'What needs doing?'}
        sub={solo ? 'Rough minutes are enough. They balance the week so no day gets heavy.'
          : 'Start from common chores. Fine-tune frequency and who can do what in Setup later.'} />
      <View style={{ marginTop: 6 }}>
        {presets.map(({ on: _on, hint, ...g }) => {
          const hostMissing = !!g.piggyback_on && !has(g.piggyback_on);
          return (
            <Row key={g.name} disabled={hostMissing}
              left={<Toggle on={has(g.name)} disabled={hostMissing} onChange={(v) => toggle(g, v)} />}
              sub={hostMissing ? `needs ${g.piggyback_on}` : hint}
              right={right(g)}>
              {g.tasks[0]}
            </Row>
          );
        })}
        {extras.map((g) => (
          <Row key={g.name} left={<Toggle on onChange={() => toggle(g, false)} />} sub="custom · weekly, ±1 day" right={right(g)}>
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
      <Note>{solo ? 'Frequency and tolerance can be changed per chore in Setup.' : 'Mop rides along on every 2nd Vacuum day, like your config.yml does.'}</Note>
    </Screen>
  );
}
