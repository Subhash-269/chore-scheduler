import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { api } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Note, Screen, Seg, T, TopBar } from '@/ui';

type Mode = 'signup' | 'login';

/** Create an account or sign in. Email + password; the session lives in the Keychain. */
export default function Auth() {
  const { c } = useTheme();
  const { refresh } = useAppData();
  const [mode, setMode] = useState<Mode>('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (mode === 'signup') await api.signup(email.trim(), password, name.trim());
      else await api.login(email.trim(), password);
      await refresh();
      router.replace('/');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const field = { fontFamily: font.regular, fontSize: 16, color: c.tx, borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 11 };
  const ready = email.includes('@') && password.length >= (mode === 'signup' ? 8 : 1) && (mode === 'login' || name.trim());

  return (
    <Screen footer={<Btn title={mode === 'signup' ? 'Create account' : 'Sign in'} onPress={submit} loading={busy} disabled={!ready} />}>
      <TopBar left={<T v="cap">chores</T>} action="Server" onAction={() => router.push('/connect')} />
      <View style={{ height: 30 }} />
      <T style={{ fontFamily: font.semibold, fontSize: 34, letterSpacing: -1.4 }}>chores</T>
      <T v="meta" style={{ marginTop: 6 }}>Fair by design. Six algorithms split the work so nobody carries the house.</T>
      <Seg style={{ marginTop: 28 }} value={mode} onChange={(m) => { setMode(m); setErr(null); }}
        options={[{ value: 'signup', label: 'Create account' }, { value: 'login', label: 'Sign in' }]} />
      <View style={{ marginTop: 10 }}>
        {mode === 'signup' ? (
          <TextInput value={name} onChangeText={setName} placeholder="Your name" placeholderTextColor={c.tx3}
            autoComplete="name" textContentType="name" style={field} />
        ) : null}
        <TextInput value={email} onChangeText={setEmail} placeholder="Email" placeholderTextColor={c.tx3}
          autoCapitalize="none" autoCorrect={false} keyboardType="email-address" autoComplete="email" textContentType="emailAddress" style={field} />
        <TextInput value={password} onChangeText={setPassword} placeholder={mode === 'signup' ? 'Password (8+ characters)' : 'Password'}
          placeholderTextColor={c.tx3} secureTextEntry autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
          textContentType={mode === 'signup' ? 'newPassword' : 'password'} onSubmitEditing={ready ? submit : undefined} style={field} />
      </View>
      {err ? <Note tone="bad">{err}</Note> : null}
      <Pressable onPress={() => setMode(mode === 'signup' ? 'login' : 'signup')} style={{ marginTop: 18 }}>
        <T v="meta">{mode === 'signup' ? 'Already have an account? ' : 'New here? '}<T v="link">{mode === 'signup' ? 'Sign in' : 'Create one'}</T></T>
      </Pressable>
    </Screen>
  );
}
