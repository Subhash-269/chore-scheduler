import * as Clipboard from 'expo-clipboard';
import { useCallback, useEffect, useState } from 'react';
import { Alert, Share, View } from 'react-native';

import { api, type Invite, type Member } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, BtnRow, Dot, Header, Loading, Note, Pill, Pills, Row, Screen, Section, Seg, T, Tag, TopBar } from '@/ui';

const pretty = (code: string) => `${code.slice(0, 3)}-${code.slice(3)}`;
const daysLeft = (expires: number) => Math.max(0, Math.ceil((expires * 1000 - Date.now()) / 86400000));

/** Who's in the household, their role, and invite codes. */
export default function Members() {
  const { c, personColor } = useTheme();
  const { user, isAdmin, household, membership, refresh } = useAppData();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [role, setRole] = useState<'member' | 'admin'>('member');
  const [fresh, setFresh] = useState<Invite | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.members();
      setMembers(r.members);
      setInvites(r.invites);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // load() only sets state after its await
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (!members) return <Loading />;
  const roommates = household?.roommates ?? [];
  const linked = new Set(members.map((m) => m.roommate).filter(Boolean));

  const act = (fn: () => Promise<unknown>) => async () => {
    setErr(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setErr((e as Error).message); }
  };

  const invite = act(async () => setFresh(await api.createInvite(role)));

  const manage = (m: Member) => {
    if (!isAdmin || m.id === user?.id) return;
    Alert.alert(m.name, m.email, [
      { text: m.role === 'admin' ? 'Make member' : 'Make admin', onPress: act(() => api.patchMember(m.id, { role: m.role === 'admin' ? 'member' : 'admin' })) },
      { text: 'Remove from household', style: 'destructive', onPress: act(() => api.removeMember(m.id)) },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  return (
    <Screen>
      <TopBar back="Team" />
      <Header title="Members" cap={membership?.name} sub="Accounts in this household. Admins change chores and rules and publish schedules; members tick and swap." />

      <Section title="People" />
      {members.map((m, i) => (
        <Row key={m.id} end={i === members.length - 1} onPress={isAdmin && m.id !== user?.id ? () => manage(m) : undefined}
          left={m.roommate ? <Dot color={personColor(m.roommate, roommates, household?.colors)} /> : <Dot color={c.line2} />}
          sub={m.roommate ? `is ${m.roommate}` : 'not linked to a roommate yet'}
          right={<View style={{ flexDirection: 'row', gap: 6 }}>
            {m.id === user?.id ? <Tag label="you" /> : null}
            <Tag label={m.role} tone={m.role === 'admin' ? 'inv' : undefined} />
          </View>}>
          {m.name}
        </Row>
      ))}
      {roommates.some((r) => !linked.has(r)) ? (
        <Note>Not on the app yet: {roommates.filter((r) => !linked.has(r)).join(', ')}. They still get tasks; anyone can strike them.</Note>
      ) : null}

      {isAdmin ? (
        <>
          <Section title="Invite someone" />
          {fresh ? (
            <View style={{ alignItems: 'center', marginTop: 16 }}>
              <T style={{ fontFamily: font.monoMedium, fontSize: 34, letterSpacing: 6 }}>{pretty(fresh.code)}</T>
              <T v="faint" style={{ marginTop: 6 }}>joins as {fresh.role} · one use · {daysLeft(fresh.expires_at)} days</T>
              <View style={{ width: '100%', marginTop: 14 }}>
                <BtnRow>
                  <Btn kind="ghost" small title="Copy" onPress={() => Clipboard.setStringAsync(pretty(fresh.code))} />
                  <Btn small title="Share" onPress={() => Share.share({ message: `Join our chores household: open the Chores app → Join a household → ${pretty(fresh.code)}` })} />
                </BtnRow>
              </View>
            </View>
          ) : (
            <>
              <Seg style={{ marginTop: 10 }} value={role} onChange={setRole}
                options={[{ value: 'member', label: 'As member' }, { value: 'admin', label: 'As admin' }]} />
              <Btn style={{ marginTop: 10 }} title="Create invite code" onPress={invite} />
            </>
          )}
          {invites.filter((x) => x.code !== fresh?.code).length ? (
            <>
              <Section title="Open invites" />
              <Pills>
                {invites.filter((x) => x.code !== fresh?.code).map((x) => (
                  <Pill key={x.code} label={`${pretty(x.code)} · ${daysLeft(x.expires_at)}d ×`} onPress={act(() => api.revokeInvite(x.code))} />
                ))}
              </Pills>
              <Note>Tap an open code to revoke it.</Note>
            </>
          ) : null}
        </>
      ) : <Note>Ask an admin for an invite code to add someone.</Note>}
      {err ? <Note tone="bad">{err}</Note> : null}
    </Screen>
  );
}
