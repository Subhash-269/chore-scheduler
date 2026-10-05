import { Pressable, StyleSheet, Text, View } from 'react-native';

import { WEEKDAYS } from '@/data/dates';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';

import { tap } from './index';

export const toggleDay = (days: string[], day: string) =>
  (days.includes(day) ? days.filter((x) => x !== day) : [...days, day]);

/** M T W T F S S - struck-through days are days off. */
export function WeekdayPicker({ off, onToggle }: { off: string[]; onToggle: (day: string) => void }) {
  const { c } = useTheme();
  return (
    <View style={styles.row}>
      {WEEKDAYS.map((d) => {
        const isOff = off.includes(d);
        return (
          <Pressable key={d} hitSlop={2}
            onPress={() => { tap(); onToggle(d); }}
            style={[styles.day, { borderColor: isOff ? 'transparent' : c.line2, backgroundColor: isOff ? c.soft : 'transparent' }]}>
            <Text style={{ fontFamily: font.mono, fontSize: 11, color: isOff ? c.tx3 : c.tx, textDecorationLine: isOff ? 'line-through' : 'none' }}>
              {d[0]}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 5, marginTop: 7 },
  day: { flex: 1, alignItems: 'center', paddingVertical: 8, borderWidth: 1, borderRadius: 8 },
});
