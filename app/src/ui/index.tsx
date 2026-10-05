/**
 * The mono design system as components. Each one mirrors a class in the
 * mockups: .cap, .li, .btn, .seg, .tg, .stp, .pill, .sk (strikethrough) ...
 */
import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
  type StyleProp, type TextProps, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useTheme } from '@/theme/ThemeProvider';
import { font, space } from '@/theme/tokens';

export const tap = () => Haptics.selectionAsync().catch(() => {});

// ---------------------------------------------------------------- text
type Variant = 'h1' | 'h2' | 'body' | 'meta' | 'faint' | 'cap' | 'mono' | 'big' | 'link';

export function T({ v = 'body', style, color, ...rest }: TextProps & { v?: Variant; color?: string }) {
  const { c } = useTheme();
  const base: Record<Variant, TextStyle> = {
    h1: { fontFamily: font.semibold, fontSize: 24, letterSpacing: -0.6, color: c.tx, lineHeight: 29 },
    h2: { fontFamily: font.semibold, fontSize: 17, letterSpacing: -0.2, color: c.tx },
    body: { fontFamily: font.regular, fontSize: 14.5, color: c.tx },
    meta: { fontFamily: font.regular, fontSize: 12, color: c.tx2, lineHeight: 17 },
    faint: { fontFamily: font.regular, fontSize: 11, color: c.tx3 },
    cap: { fontFamily: font.mono, fontSize: 9.5, letterSpacing: 1.4, textTransform: 'uppercase', color: c.tx3 },
    mono: { fontFamily: font.mono, fontSize: 12, color: c.tx2 },
    big: { fontFamily: font.thin, fontSize: 56, letterSpacing: -3, color: c.tx, lineHeight: 56 },
    link: { fontFamily: font.semibold, fontSize: 12.5, color: c.tx, textDecorationLine: 'underline' },
  };
  return <Text {...rest} style={[base[v], color ? { color } : null, style]} />;
}

// ---------------------------------------------------------------- layout
export function Screen({ children, footer, scroll = true, padded = true }: {
  children: ReactNode; footer?: ReactNode; scroll?: boolean; padded?: boolean;
}) {
  const { c } = useTheme();
  const inner = padded ? { paddingHorizontal: space.gutter } : null;
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {scroll ? (
        <ScrollView contentContainerStyle={[inner, { paddingBottom: 28 }]} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      ) : (
        <View style={[{ flex: 1 }, inner]}>{children}</View>
      )}
      {footer ? <View style={{ paddingHorizontal: space.gutter, paddingTop: 10, paddingBottom: 14 }}>{footer}</View> : null}
    </SafeAreaView>
  );
}

/** Top bar: "‹ Back" on the left, an underlined action on the right. */
export function TopBar({ back, onBack, left, action, onAction }: {
  back?: string; onBack?: () => void; left?: ReactNode; action?: string; onAction?: () => void;
}) {
  return (
    <View style={styles.top}>
      {back ? (
        <Pressable hitSlop={12} onPress={onBack ?? (() => router.back())}>
          <T v="meta" style={{ fontSize: 13 }}>‹  {back}</T>
        </Pressable>
      ) : left ?? <View />}
      {action ? (
        <Pressable hitSlop={12} onPress={onAction}>
          <T v="link">{action}</T>
        </Pressable>
      ) : <View />}
    </View>
  );
}

export function Header({ title, sub, cap }: { title: string; sub?: string; cap?: string }) {
  return (
    <View style={{ marginTop: 4, marginBottom: 6 }}>
      {cap ? <T v="cap" style={{ marginBottom: 6 }}>{cap}</T> : null}
      <T v="h1">{title}</T>
      {sub ? <T v="meta" style={{ marginTop: 5 }}>{sub}</T> : null}
    </View>
  );
}

export function Section({ title, link, onLink, style }: {
  title: string; link?: string; onLink?: () => void; style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.section, style]}>
      <T v="cap">{title}</T>
      {link ? <Pressable hitSlop={10} onPress={onLink}><T v="link" style={{ fontSize: 11.5 }}>{link}</T></Pressable> : null}
    </View>
  );
}

export function Row({ left, children, right, sub, onPress, onLongPress, end, chevron, disabled, style }: {
  left?: ReactNode; children?: ReactNode; right?: ReactNode; sub?: string; onPress?: () => void;
  onLongPress?: () => void; end?: boolean; chevron?: boolean; disabled?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  const body = typeof children === 'string' ? <T>{children}</T> : children;
  return (
    <Pressable
      disabled={disabled || (!onPress && !onLongPress)}
      onPress={onPress}
      onLongPress={onLongPress}
      style={({ pressed }) => [
        styles.row,
        { borderBottomColor: c.line, borderBottomWidth: end ? 0 : StyleSheet.hairlineWidth, opacity: disabled ? 0.42 : pressed ? 0.6 : 1 },
        style,
      ]}>
      {left}
      <View style={{ flex: 1 }}>
        {body}
        {sub ? <T v="faint" style={{ marginTop: 2 }}>{sub}</T> : null}
      </View>
      {typeof right === 'string' ? <T v="mono" style={{ fontSize: 11.5 }}>{right}</T> : right}
      {chevron ? <T v="meta" color={c.tx3} style={{ fontSize: 17, marginLeft: 2 }}>›</T> : null}
    </Pressable>
  );
}

export function KV({ k, children, end }: { k: string; children: ReactNode; end?: boolean }) {
  const { c } = useTheme();
  return (
    <View style={[styles.kv, { borderBottomColor: c.line, borderBottomWidth: end ? 0 : StyleSheet.hairlineWidth }]}>
      <T v="meta" style={{ fontSize: 13 }}>{k}</T>
      {typeof children === 'string' ? <T style={{ fontSize: 13 }}>{children}</T> : children}
    </View>
  );
}

export function Note({ children, tone, style }: { children: ReactNode; tone?: 'ok' | 'warn' | 'bad'; style?: StyleProp<TextStyle> }) {
  const { c } = useTheme();
  return <T v="meta" color={tone ? c[tone] : undefined} style={[{ fontSize: 11.5, marginTop: 10 }, style]}>{children}</T>;
}

// ---------------------------------------------------------------- atoms
export function Dot({ color, size = 8 }: { color: string; size?: number }) {
  return <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: color }} />;
}

export function Check({ on, onPress }: { on: boolean; onPress?: () => void }) {
  const { c } = useTheme();
  return (
    <Pressable hitSlop={10} onPress={onPress} style={[styles.check, { borderColor: on ? c.tx : c.line2, backgroundColor: on ? c.tx : 'transparent' }]}>
      {on ? <View style={[styles.tick, { borderColor: c.bg }]} /> : null}
    </Pressable>
  );
}

export function Btn({ title, onPress, kind = 'primary', small, disabled, loading, style }: {
  title: string; onPress?: () => void; kind?: 'primary' | 'ghost' | 'text' | 'danger'; small?: boolean;
  disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  const bg = kind === 'primary' ? c.tx : 'transparent';
  const fg = kind === 'primary' ? c.bg : kind === 'danger' ? c.bad : kind === 'text' ? c.tx2 : c.tx;
  return (
    <Pressable
      disabled={disabled || loading}
      onPress={() => { tap(); onPress?.(); }}
      style={({ pressed }) => [
        styles.btn,
        small && styles.btnSm,
        { backgroundColor: bg, borderColor: kind === 'ghost' ? c.line2 : 'transparent', opacity: disabled ? 0.4 : pressed ? 0.7 : 1 },
        style,
      ]}>
      {loading ? <ActivityIndicator color={fg} /> : (
        <T style={{ fontFamily: kind === 'text' || kind === 'danger' ? font.medium : font.semibold, fontSize: small ? 12.5 : 14.5, color: fg }}>{title}</T>
      )}
    </Pressable>
  );
}

export function BtnRow({ children }: { children: ReactNode }) {
  return <View style={{ flexDirection: 'row', gap: 8 }}>{children}</View>;
}

export function Seg<V extends string>({ options, value, onChange, style }: {
  options: { value: V; label: string }[]; value: V; onChange: (v: V) => void; style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  return (
    <View style={[styles.seg, { borderColor: c.line2 }, style]}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable key={o.value} onPress={() => { tap(); onChange(o.value); }} style={[styles.segItem, on && { backgroundColor: c.tx }]}>
            <T style={{ fontSize: 12, fontFamily: on ? font.semibold : font.regular, color: on ? c.bg : c.tx2 }} numberOfLines={1}>{o.label}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Toggle({ on, onChange, disabled }: { on: boolean; onChange?: (v: boolean) => void; disabled?: boolean }) {
  const { c } = useTheme();
  return (
    <Pressable disabled={disabled} hitSlop={8} onPress={() => { tap(); onChange?.(!on); }}
      style={[styles.toggle, { backgroundColor: on ? c.tx : c.line2, opacity: disabled ? 0.4 : 1 }]}>
      <View style={[styles.knob, { backgroundColor: c.bg, left: on ? 15 : 2 }]} />
    </Pressable>
  );
}

export function Stepper({ value, onChange, min = 0, max = 99, format }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; format?: (v: number) => string;
}) {
  const { c } = useTheme();
  const step = (d: number) => { const v = Math.min(max, Math.max(min, value + d)); if (v !== value) { tap(); onChange(v); } };
  return (
    <View style={[styles.stepper, { borderColor: c.line2 }]}>
      <Pressable hitSlop={6} onPress={() => step(-1)} style={styles.stepBtn}><T v="meta" style={{ fontSize: 15 }}>−</T></Pressable>
      <View style={[styles.stepVal, { borderColor: c.line }]}>
        <T style={{ fontFamily: font.monoMedium, fontSize: 13 }}>{format ? format(value) : `${value}`}</T>
      </View>
      <Pressable hitSlop={6} onPress={() => step(1)} style={styles.stepBtn}><T v="meta" style={{ fontSize: 15 }}>+</T></Pressable>
    </View>
  );
}

export function Pill({ label, on, off, dashed, onPress, left }: {
  label: string; on?: boolean; off?: boolean; dashed?: boolean; onPress?: () => void; left?: ReactNode;
}) {
  const { c } = useTheme();
  return (
    <Pressable onPress={onPress && (() => { tap(); onPress(); })}
      style={[styles.pill, { borderColor: on ? c.tx : c.line2, backgroundColor: on ? c.tx : 'transparent', borderStyle: dashed ? 'dashed' : 'solid' }]}>
      {left}
      <T style={{ fontSize: 12, color: on ? c.bg : off || dashed ? c.tx3 : c.tx, textDecorationLine: off ? 'line-through' : 'none' }}>{label}</T>
    </Pressable>
  );
}

export function Pills({ children }: { children: ReactNode }) {
  return <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>{children}</View>;
}

export function Tag({ label, tone }: { label: string; tone?: 'inv' | 'ok' | 'warn' | 'bad' }) {
  const { c } = useTheme();
  const color = tone === 'inv' ? c.bg : tone ? c[tone] : c.tx2;
  return (
    <View style={[styles.tag, { borderColor: tone === 'inv' ? c.tx : tone ? c[tone] : c.line2, backgroundColor: tone === 'inv' ? c.tx : 'transparent' }]}>
      <Text style={{ fontFamily: font.monoMedium, fontSize: 9, letterSpacing: 0.6, textTransform: 'uppercase', color }}>{label}</Text>
    </View>
  );
}

export function ProgressLine({ value }: { value: number }) {
  const { c } = useTheme();
  return (
    <View style={{ height: 2, backgroundColor: c.line }}>
      <View style={{ height: 2, width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`, backgroundColor: c.tx }} />
    </View>
  );
}

/**
 * The strikethrough status. One segment per session, left to right:
 * solid = done, red = missed, faint = still to do. 5+ sessions collapse to
 * one continuous line (segments would be too small).
 */
export function Strike({ children, n = 1, done = 0, missed = 0, size = 14.5, color, fontFamily, thickness = 2 }: {
  children: string; n?: number; done?: number; missed?: number; size?: number; color?: string;
  fontFamily?: string; thickness?: number;
}) {
  const { c } = useTheme();
  const struck = done + missed > 0 || n > 1;
  const complete = done + missed >= n && missed === 0;
  const textColor = color ?? (missed > 0 && done === 0 ? c.bad : complete ? c.tx3 : c.tx);
  const faint = c.line2;
  return (
    <View style={{ alignSelf: 'flex-start' }}>
      <Text style={{ fontFamily: fontFamily ?? font.medium, fontSize: size, color: textColor }}>{children}</Text>
      {struck ? (
        <View pointerEvents="none" style={{ position: 'absolute', left: -2, right: -1, top: '50%', marginTop: -thickness / 2, height: thickness, flexDirection: 'row', gap: n >= 5 ? 0 : 3 }}>
          {n >= 5 ? (
            <View style={{ flex: 1, backgroundColor: faint, borderRadius: 1 }}>
              <View style={{ width: `${(done / n) * 100}%`, height: '100%', backgroundColor: c.tx, borderRadius: 1 }} />
            </View>
          ) : Array.from({ length: n }, (_, i) => (
            <View key={i} style={{ flex: 1, borderRadius: 1, backgroundColor: i < done ? c.tx : i < done + missed ? c.bad : faint }} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function Loading({ label }: { label?: string }) {
  const { c } = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: c.bg }}>
      <ActivityIndicator color={c.tx} />
      {label ? <T v="cap">{label}</T> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 40, paddingTop: 4 },
  section: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 22, marginBottom: 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 11, minHeight: 46 },
  kv: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10, paddingVertical: 11 },
  check: { width: 20, height: 20, borderWidth: 1.5, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  tick: { width: 9, height: 5, borderLeftWidth: 2, borderBottomWidth: 2, transform: [{ rotate: '-45deg' }], marginTop: -2 },
  btn: { borderRadius: 13, paddingVertical: 14, alignItems: 'center', justifyContent: 'center', borderWidth: 1, flex: 1 },
  btnSm: { paddingVertical: 9, borderRadius: 10 },
  seg: { flexDirection: 'row', borderWidth: 1, borderRadius: 10, padding: 2 },
  segItem: { flex: 1, alignItems: 'center', paddingVertical: 7, paddingHorizontal: 4, borderRadius: 8 },
  toggle: { width: 34, height: 20, borderRadius: 12 },
  knob: { position: 'absolute', top: 2, width: 16, height: 16, borderRadius: 8 },
  stepper: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 10 },
  stepBtn: { width: 32, alignItems: 'center', paddingVertical: 6 },
  stepVal: { minWidth: 40, alignItems: 'center', paddingVertical: 6, paddingHorizontal: 4, borderLeftWidth: 1, borderRightWidth: 1 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: 20, paddingVertical: 6, paddingHorizontal: 12 },
  tag: { borderWidth: 1, borderRadius: 5, paddingHorizontal: 5, paddingVertical: 2 },
});
