import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { TextInput, View } from 'react-native';

import { api, getServerUrl, guessServerUrl, setServerUrl } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Header, Note, Screen, T, TopBar } from '@/ui';

/** Shown when the server can't be reached: lets you point the app at it. */
export default function Connect() {
  const { c } = useTheme();
  const { error, refresh } = useAppData();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(error);

  useEffect(() => {
    getServerUrl().then(setUrl);
  }, []);

  const connect = async () => {
    setBusy(true);
    setMsg(null);
    await setServerUrl(url);
    try {
      await api.health();
      await refresh();
      router.replace('/');
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen footer={<Btn title="Connect" onPress={connect} loading={busy} />}>
      <TopBar left={<T v="cap">server</T>} />
      <Header title="Connect to your scheduler" sub="The app talks to the Python scheduler running on your computer." />
      <T v="cap" style={{ marginTop: 22 }}>Server address</T>
      <TextInput
        value={url}
        onChangeText={setUrl}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder={guessServerUrl()}
        placeholderTextColor={c.tx3}
        style={{ fontFamily: font.mono, fontSize: 15, color: c.tx, borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 10 }}
      />
      {msg ? <Note tone="bad">{msg}</Note> : null}
      <View style={{ marginTop: 24, gap: 6 }}>
        <T v="cap">On your computer</T>
        <T v="mono" style={{ fontSize: 12.5, color: c.tx }}>python -m uvicorn server.main:app --host 0.0.0.0 --port 8000</T>
        <Note style={{ marginTop: 4 }}>Run it from the project folder. Your phone and computer need to be on the same Wi-Fi, and your firewall has to allow port 8000.</Note>
      </View>
    </Screen>
  );
}
