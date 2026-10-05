import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, Linking, View } from 'react-native';

import { api, getServerUrl } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { timeLabel, usePrefs, type Reminder } from '@/data/prefs';
import { ensurePermission } from '@/data/reminders';
import { useTheme, type Appearance } from '@/theme/ThemeProvider';
import { Btn, BtnRow, Dot, Header, Note, Row, Screen, Section, Seg, Stepper, T, Tag, Toggle, TopBar } from '@/ui';

/** Customize: appearance, which roommate you are, households, account, export. */
export default function Settings() {
  const { c, appearance, setAppearance, personColor } = useTheme();
  const { household, schedule, me, setMe, user, memberships, membership, selectHousehold, signOut, refresh } = useAppData();
  const { prefs, setPrefs } = usePrefs();
  const [denied, setDenied] = useState(false);
  const [server, setServer] = useState('');
  const solo = household?.mode === 'solo';

  // reminder times move in half-hour steps
  const toSteps = (r: Reminder) => r.hour * 2 + (r.minute >= 30 ? 1 : 0);
  const fromSteps = (r: Reminder, v: number): Reminder => ({ ...r, hour: Math.floor(v / 2), minute: v % 2 ? 30 : 0 });
  const switchReminder = async (key: 'morning' | 'evening', on: boolean) => {
    if (on && !(await ensurePermission())) { setDenied(true); return; }
    setDenied(false);
    setPrefs({ [key]: { ...prefs[key], on } });
  };
  useEffect(() => { getServerUrl().then(setServer); }, []);

  const exportAs = async (fmt: 'csv' | 'docx' | 'pdf') => Linking.openURL(await api.exportUrl(fmt));

  const leave = async () => { await signOut(); router.replace('/auth'); };
  const deleteAccount = () => Alert.alert(
    'Delete your account?',
    'This signs you out everywhere and removes your account. Households you admin pass to the next member, or are deleted if you are the only one.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete account', style: 'destructive', onPress: async () => {
        await api.deleteAccount();
        await refresh();
        router.replace('/auth');
      } },
    ]);

  return (
    <Screen>
      <TopBar back="Back" />
      <Header title="Customize" sub="Make the app yours. Schedule rules live in Setup." />

      <Section title="Appearance" />
      <Seg<Appearance> style={{ marginTop: 10 }} value={appearance} onChange={setAppearance}
        options={[{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} />

      <Section title="Today shows" />
      {solo ? null : (
        <>
          <Row right={<Toggle on={prefs.yoursFirst} onChange={(v) => setPrefs({ yoursFirst: v })} />} sub="your tasks in their own section at the top">My tasks first</Row>
          <Row right={<Toggle on={prefs.showHouse} onChange={(v) => setPrefs({ showHouse: v })} />} sub="everyone else’s tasks for today">Household tasks</Row>
        </>
      )}
      <Row end right={<Stepper value={prefs.nextDays} min={0} max={7} format={(v) => (v ? `${v}d` : 'off')} onChange={(v) => setPrefs({ nextDays: v })} />}>Upcoming days</Row>

      <Section title="Reminders" />
      <Row right={<Toggle on={prefs.morning.on} onChange={(v) => switchReminder('morning', v)} />}
        sub={prefs.morning.on ? `${timeLabel(prefs.morning)} on days you have tasks` : 'what’s yours today'}>Morning digest</Row>
      {prefs.morning.on ? (
        <Row right={<Stepper value={toSteps(prefs.morning)} min={10} max={24} format={(v) => timeLabel(fromSteps(prefs.morning, v))}
          onChange={(v) => setPrefs({ morning: fromSteps(prefs.morning, v) })} />}>at</Row>
      ) : null}
      <Row end={!prefs.evening.on} right={<Toggle on={prefs.evening.on} onChange={(v) => switchReminder('evening', v)} />}
        sub={prefs.evening.on ? `${timeLabel(prefs.evening)}, only if still open` : 'only if your tasks are still open'}>Evening nudge</Row>
      {prefs.evening.on ? (
        <Row end right={<Stepper value={toSteps(prefs.evening)} min={30} max={46} format={(v) => timeLabel(fromSteps(prefs.evening, v))}
          onChange={(v) => setPrefs({ evening: fromSteps(prefs.evening, v) })} />}>at</Row>
      ) : null}
      {denied ? <Note tone="warn">Notifications are off for Chores. Turn them on in your phone’s Settings, then try again.</Note> : null}
      <Note>Reminders live on this phone. Strike your tasks and that day’s nudge is cancelled.</Note>

      {household ? (
        <>
          <Section title="You are" />
          {household.roommates.map((p, i) => (
            <Row key={p} end={i === household.roommates.length - 1} onPress={() => { setMe(p).catch(() => {}); }}
              left={<Dot color={personColor(p, household.roommates, household.colors)} />}
              right={me === p ? <Tag label="you" tone="inv" /> : undefined}>{p}</Row>
          ))}
          <Note>Links your account to a roommate. Your tasks show first on Today.</Note>
        </>
      ) : null}

      {schedule ? (
        <>
          <Section title="Export the live schedule" />
          <View style={{ marginTop: 10 }}>
            <BtnRow>
              <Btn kind="ghost" small title="CSV" onPress={() => exportAs('csv')} />
              <Btn kind="ghost" small title="DOCX" onPress={() => exportAs('docx')} />
              <Btn kind="ghost" small title="PDF" onPress={() => exportAs('pdf')} />
            </BtnRow>
          </View>
          <Note>Same files main.py exports. The PDF is the one for the fridge.</Note>
        </>
      ) : null}

      <Section title="Households" />
      {memberships.map((m) => (
        <Row key={m.id} onPress={m.id === membership?.id ? undefined : async () => { await selectHousehold(m.id); router.replace('/'); }}
          right={<View style={{ flexDirection: 'row', gap: 6 }}>
            {m.id === membership?.id ? <Tag label="current" tone="inv" /> : null}<Tag label={m.role} />
          </View>}>{m.name}</Row>
      ))}
      <Row chevron onPress={() => router.push('/onboarding/join')}>Join another household</Row>
      <Row chevron end onPress={() => router.push('/onboarding')}>Start another household</Row>

      <Section title="Account" />
      <Row sub={user?.email}>{user?.name ?? '—'}</Row>
      <Row onPress={leave}>Sign out</Row>
      <Row end onPress={deleteAccount}><T color={c.bad}>Delete account</T></Row>

      <Section title="Server" />
      <Row chevron end onPress={() => router.push('/connect')} right={<T v="mono" style={{ fontSize: 10.5 }} numberOfLines={1}>{server}</T>}>Address</Row>
    </Screen>
  );
}
