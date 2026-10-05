import { router } from 'expo-router';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api, setHouseholdId } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Dot, Header, Note, Row, Screen, T, Tag, TopBar } from '@/ui';

/** Join with a 6-character code, then say which roommate you are. */
export default function Join() {
  const { c, personColor } = useTheme();
  const { refresh, household, me, setMe } = useAppData();
  const [code, setCode] = useState('');
  const [joined, setJoined] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const join = async () => {
    setBusy(true);
    setErr(null);
    try {
      const h = await api.acceptInvite(code);
      await setHouseholdId(h.id);
      await refresh();
      setJoined(true);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (joined) {
    return (
      <Screen footer={<Btn title="Continue" onPress={() => router.replace('/')} />}>
        <TopBar left={<T v="cap">joined</T>} />
        <Header title="Which one is you?" sub={household ? 'Your tasks show first on Today.' : 'An admin is still setting up roommates. You can pick later in Settings.'} />
        {household?.roommates.map((p, i) => (
          <Row key={p} end={i === household.roommates.length - 1} onPress={() => setMe(p).catch((e) => setErr((e as Error).message))}
            left={<Dot color={personColor(p, household.roommates, household.colors)} />}
            right={me === p ? <Tag label="you" tone="inv" /> : undefined}>{p}</Row>
        ))}
        {err ? <Note tone="bad">{err}</Note> : null}
      </Screen>
    );
  }

  const clean = code.replace(/[^a-z0-9]/gi, '').toUpperCase().slice(0, 6);
  return (
    <Screen footer={<Btn title="Join" onPress={join} loading={busy} disabled={clean.length !== 6} />}>
      <TopBar back="Back" />
      <Header title="Join a household" sub="Ask an admin for the 6-character code. It works once and expires after a week." />
      <View style={{ marginTop: 26, alignItems: 'center' }}>
        <TextInput value={clean.length > 3 ? `${clean.slice(0, 3)}-${clean.slice(3)}` : clean} onChangeText={setCode}
          autoCapitalize="characters" autoCorrect={false} placeholder="K7Q-2XM" placeholderTextColor={c.tx3} maxLength={7}
          style={{ fontFamily: font.monoMedium, fontSize: 30, letterSpacing: 6, color: c.tx, textAlign: 'center',
            borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 10, minWidth: 220 }} />
      </View>
      {err ? <Note tone="bad" style={{ textAlign: 'center' }}>{err}</Note> : null}
    </Screen>
  );
}
