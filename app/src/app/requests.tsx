import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { api, type ChoreRequest, type CoverOption } from '@/data/api';
import { useAppData } from '@/data/AppData';
import { dayNum, plainTask, shortDate, shortDay, todayIso, weekDates, weekStart } from '@/data/dates';
import type { Slot } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { Btn, BtnRow, Dot, Header, Loading, Note, Screen, Section, T, Tag, tap, TopBar } from '@/ui';
import { FridgeGrid } from '@/ui/FridgeGrid';

const restLabel = (b: number | null, a: number | null) =>
  [b === null ? null : `${b}d rest before`, a === null ? null : `${a}d after`].filter(Boolean).join(' · ') || 'no other tasks nearby';

/** Day-off approvals with a preview, swaps offered to you, and your own requests. */
export default function Requests() {
  const { c } = useTheme();
  const { refresh } = useAppData();
  const [items, setItems] = useState<ChoreRequest[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await api.requests()).requests);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    // load() only sets state after its await
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (!items) return <Loading />;
  const forYou = items.filter((r) => r.status === 'pending' && r.can_decide);
  const yours = items.filter((r) => r.status === 'pending' && r.mine && !r.can_decide);
  const done = items.filter((r) => r.status !== 'pending').slice(0, 10);

  const act = (fn: () => Promise<unknown>) => async () => {
    setErr(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <Screen>
      <TopBar back="Back" />
      <Header title="Requests" sub={forYou.length ? `${forYou.length} waiting on you` : 'Nothing waiting on you.'} />
      {err ? <Note tone="bad">{err}</Note> : null}

      {forYou.map((r) => (r.kind === 'day_off'
        ? <DayOffCard key={r.id} r={r} onApprove={(cover) => act(() => api.approve(r.id, cover))()} onDecline={act(() => api.decline(r.id))} />
        : <SwapCard key={r.id} r={r} onAccept={act(() => api.approve(r.id))} onDecline={act(() => api.decline(r.id))} />))}

      {yours.length ? <Section title="You asked" /> : null}
      {yours.map((r) => (
        <View key={r.id} style={[styles.card, { borderColor: c.line2 }]}>
          <T>{r.kind === 'day_off' ? `Day off · ${shortDay(r.date!)} ${dayNum(r.date!)}` : `Swap with ${r.to}`}</T>
          <T v="faint" style={{ marginTop: 3 }}>{r.kind === 'day_off' ? 'waiting for an admin' : `waiting for ${r.to}`}{r.note ? ` · “${r.note}”` : ''}</T>
          <View style={{ marginTop: 10 }}><Btn kind="ghost" small title="Cancel request" onPress={act(() => api.cancelRequest(r.id))} /></View>
        </View>
      ))}

      {done.length ? <Section title="Recent" /> : null}
      {done.map((r) => (
        <View key={r.id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 9, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line }}>
          <T style={{ flex: 1, fontSize: 13 }} numberOfLines={1}>
            {r.kind === 'day_off' ? `${r.roommate} off ${shortDate(r.date!)}` : `${r.from} ↔ ${r.to}`}
            {r.result?.changes?.length ? ` · ${r.result.changes.map((x) => `${plainTask(x.task)} → ${x.to}`).join(', ')}` : ''}
          </T>
          <Tag label={r.status} tone={r.status === 'approved' ? 'ok' : undefined} />
        </View>
      ))}
    </Screen>
  );
}

function DayOffCard({ r, onApprove, onDecline }: { r: ChoreRequest; onApprove: (cover?: string) => void; onDecline: () => void }) {
  const { c, personColor } = useTheme();
  const { household, schedule } = useAppData();
  const options = r.preview?.options ?? [];
  const affected = r.preview?.affected ?? [];
  const [pick, setPick] = useState<string | undefined>(options[0]?.person);
  const chosen = options.find((o) => o.person === pick);

  // the week of the request, with the chosen cover already applied
  const preview = useMemo(() => {
    if (!schedule || !chosen) return null;
    const moved = new Map(chosen.changes.map((x) => [x.slot_id, x.to]));
    const slots: Slot[] = schedule.slots.map((s) => (moved.has(s.id) ? { ...s, person: moved.get(s.id)! } : s));
    return { slots, changed: new Set(moved.keys()) };
  }, [schedule, chosen]);

  if (!household || !r.date) return null;
  const color = (p: string) => personColor(p, household.roommates, household.colors);
  const blockedNote = (r.preview?.blocked ?? []).map((b) => b.reason).join(' · ');

  return (
    <View style={[styles.card, { borderColor: c.tx }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Dot color={color(r.roommate!)} />
        <T style={{ fontFamily: font.semibold }}>{r.roommate} · day off {shortDay(r.date)} {dayNum(r.date)}</T>
      </View>
      <T v="faint" style={{ marginTop: 3 }}>{r.created_by}{r.note ? ` · “${r.note}”` : ''}</T>

      {affected.length === 0 ? (
        <Note>No tasks that day, so nothing moves. Approving just records the day off.</Note>
      ) : options.length === 0 ? (
        <Note tone="warn">Nobody can cover {affected.map((a) => plainTask(a.task)).join(', ')}: {blockedNote}. Decline, or re-plan after approving in Setup.</Note>
      ) : (
        <>
          <T v="cap" style={{ marginTop: 14 }}>Who covers {affected.map((a) => plainTask(a.task)).join(', ')}?</T>
          {options.map((o: CoverOption) => {
            const on = o.person === pick;
            return (
              <Pressable key={o.person} onPress={() => { tap(); setPick(o.person); }}
                style={[styles.opt, { borderColor: on ? c.tx : c.line2, borderWidth: on ? 1.5 : 1 }]}>
                <View style={[styles.radio, { borderColor: on ? c.tx : c.line2, borderWidth: on ? 5 : 1.5 }]} />
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <Dot color={color(o.person)} size={7} /><T>{o.person}</T>
                    {o.short_rest ? <Tag label="short rest" tone="warn" /> : null}
                  </View>
                  <T v="faint" style={{ marginTop: 2 }}>{restLabel(o.rest_before, o.rest_after)} · spread {o.spread_before} → {o.spread_after}</T>
                </View>
              </Pressable>
            );
          })}
          {blockedNote ? <Note style={{ fontSize: 11 }}>Can’t: {blockedNote}</Note> : null}
          {preview ? (
            <View style={{ marginTop: 12, marginHorizontal: -6 }}>
              <FridgeGrid household={household} dates={weekDates(weekStart(r.date))} slots={preview.slots} changed={preview.changed}
                today={todayIso()} compact />
              <Note style={{ fontSize: 11, marginHorizontal: 6 }}>Dashed box: what changes if you approve.</Note>
            </View>
          ) : null}
        </>
      )}
      <View style={{ marginTop: 12 }}>
        <BtnRow>
          <Btn kind="ghost" small title="Decline" onPress={onDecline} />
          <Btn small title={chosen ? `Approve · ${chosen.person} covers` : 'Approve'} disabled={affected.length > 0 && !chosen}
            onPress={() => onApprove(chosen?.person)} />
        </BtnRow>
      </View>
    </View>
  );
}

function SwapCard({ r, onAccept, onDecline }: { r: ChoreRequest; onAccept: () => void; onDecline: () => void }) {
  const { c, personColor } = useTheme();
  const { household, schedule } = useAppData();
  if (!household || !schedule) return null;
  const by = new Map(schedule.slots.map((s) => [s.id, s]));
  const give = by.get(r.with_slot_id!);   // yours now, would become theirs
  const take = by.get(r.slot_id!);        // theirs now, would become yours
  const impact = r.preview?.impact?.[r.to!];
  const ok = r.preview?.ok;
  return (
    <View style={[styles.card, { borderColor: c.tx }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Dot color={personColor(r.from!, household.roommates, household.colors)} />
        <T style={{ fontFamily: font.semibold }}>{r.from} wants to swap</T>
      </View>
      {give && take ? (
        <T v="meta" style={{ marginTop: 6 }}>
          {r.to}’s {plainTask(give.task)} {shortDay(give.date)} {dayNum(give.date)} ↔ {r.from}’s {plainTask(take.task)} {shortDay(take.date)} {dayNum(take.date)}
        </T>
      ) : null}
      {r.note ? <T v="faint" style={{ marginTop: 3 }}>“{r.note}”</T> : null}
      {ok === false ? <Note tone="warn">Can’t swap any more: {r.preview?.reason}</Note>
        : impact ? <Note tone={impact.short_rest ? 'warn' : undefined}>{r.to}: {restLabel(impact.rest_before, impact.rest_after)}{impact.short_rest ? ' (shorter than the house rest buffer)' : ''}</Note> : null}
      <View style={{ marginTop: 12 }}>
        <BtnRow>
          <Btn kind="ghost" small title="Decline" onPress={onDecline} />
          <Btn small title="Accept swap" disabled={ok === false} onPress={onAccept} />
        </BtnRow>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 14, padding: 14, marginTop: 14 },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 11, borderRadius: 12, marginTop: 8 },
  radio: { width: 16, height: 16, borderRadius: 8 },
});
