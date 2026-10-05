import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, View } from 'react-native';

import { api, getServerUrl } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { useTheme, type Appearance } from '@/theme/ThemeProvider';
import { Btn, BtnRow, Dot, Header, Note, Row, Screen, Section, Seg, T, Tag, TopBar } from '@/ui';

/** Customize: appearance, which roommate is on this phone, server, export. */
export default function Settings() {
  const { appearance, setAppearance, personColor } = useTheme();
  const { household, schedule, me, setMe } = useAppData();
  const [server, setServer] = useState('');
  useEffect(() => { getServerUrl().then(setServer); }, []);

  const exportAs = async (fmt: 'csv' | 'docx' | 'pdf') => Linking.openURL(await api.exportUrl(fmt));

  return (
    <Screen>
      <TopBar back="Back" />
      <Header title="Customize" sub="Make the app yours. Schedule rules live in Setup." />

      <Section title="Appearance" />
      <Seg<Appearance> style={{ marginTop: 10 }} value={appearance} onChange={setAppearance}
        options={[{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} />

      {household ? (
        <>
          <Section title="This phone belongs to" />
          {household.roommates.map((p, i) => (
            <Row key={p} end={i === household.roommates.length - 1} onPress={() => setMe(p)}
              left={<Dot color={personColor(p, household.roommates, household.colors)} />}
              right={me === p ? <Tag label="you" tone="inv" /> : undefined}>{p}</Row>
          ))}
          <Note>Your tasks show first on Today.</Note>
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

      <Section title="Server" />
      <Row chevron end onPress={() => router.push('/connect')} right={<T v="mono" style={{ fontSize: 10.5 }} numberOfLines={1}>{server}</T>}>Address</Row>
    </Screen>
  );
}
