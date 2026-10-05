import * as AppleAuthentication from 'expo-apple-authentication';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { api, type User } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { appleAvailable, googleConfigured, signInWithApple, signInWithGoogle } from '@/data/social';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, Note, Screen, Seg, T, TopBar } from '@/ui';

type Mode = 'signup' | 'login';

/** Sign in with Apple / Google, or an email account. The session lives in the Keychain. */
export default function Auth() {
  const { c, isDark } = useTheme();
  const { refresh } = useAppData();
  const [mode, setMode] = useState<Mode>('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<'email' | 'google' | 'apple' | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [apple, setApple] = useState(false);
  const [google, setGoogle] = useState(false);

  useEffect(() => {
    appleAvailable().then(setApple);
    // the Google button needs both a build with the native module and a server that accepts Google tokens
    if (googleConfigured()) api.providers().then((p) => setGoogle(p.google)).catch(() => {});
  }, []);

  const run = (kind: 'email' | 'google' | 'apple', fn: () => Promise<User | null>) => async () => {
    setBusy(kind);
    setErr(null);
    try {
      if (await fn()) {
        await refresh();
        router.replace('/');
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const submit = run('email', () => (mode === 'signup' ? api.signup(email.trim(), password, name.trim()) : api.login(email.trim(), password)));
  const field = { fontFamily: font.regular, fontSize: 16, color: c.tx, borderBottomWidth: 1, borderBottomColor: c.line2, paddingVertical: 11 };
  const ready = email.includes('@') && password.length >= (mode === 'signup' ? 8 : 1) && (mode === 'login' || !!name.trim());

  return (
    <Screen footer={<Btn title={mode === 'signup' ? 'Create account' : 'Sign in'} onPress={submit} loading={busy === 'email'} disabled={!ready} />}>
      <TopBar left={<T v="cap">chores</T>} action="Server" onAction={() => router.push('/connect')} />
      <View style={{ height: 24 }} />
      <T style={{ fontFamily: font.semibold, fontSize: 34, letterSpacing: -1.4 }}>chores</T>
      <T v="meta" style={{ marginTop: 6 }}>Fair by design. Plans who does what so nobody carries the house.</T>

      {apple || google ? (
        <View style={{ gap: 10, marginTop: 26 }}>
          {apple ? (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE}
              buttonStyle={isDark ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
              cornerRadius={13}
              style={{ height: 48, opacity: busy ? 0.5 : 1 }}
              onPress={busy ? () => {} : run('apple', signInWithApple)} />
          ) : null}
          {google ? <Btn kind="ghost" title="Continue with Google" onPress={run('google', signInWithGoogle)} loading={busy === 'google'} /> : null}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: c.line }} />
            <T v="cap">or with email</T>
            <View style={{ flex: 1, height: 1, backgroundColor: c.line }} />
          </View>
        </View>
      ) : null}

      <Seg style={{ marginTop: apple || google ? 14 : 28 }} value={mode} onChange={(m) => { setMode(m); setErr(null); }}
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
