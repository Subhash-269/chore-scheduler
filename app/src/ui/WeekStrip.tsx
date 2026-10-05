import { StyleSheet, Text, View } from 'react-native';

import { shortDay, weekDates } from '@/data/dates';
import type { Household, Slot } from '@/data/types';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';

/** M T W ... with one dot per assignment - the mini preview on Pick. */
export function WeekStrip({ household, slots, start }: { household: Household; slots: Slot[]; start: string }) {
  const { c, personColor } = useTheme();
  return (
    <View style={styles.row}>
      {weekDates(start).map((d) => (
        <View key={d} style={styles.day}>
          <Text style={[styles.label, { color: c.tx3 }]}>{shortDay(d)[0]}</Text>
          {slots.filter((s) => s.date === d).map((s) => (
            <View key={s.id} style={[styles.dot, { backgroundColor: personColor(s.person, household.roommates, household.colors) }]} />
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 6, alignItems: 'flex-start' },
  day: { width: 18, alignItems: 'center', gap: 3 },
  label: { fontFamily: font.mono, fontSize: 9, marginBottom: 1 },
  dot: { width: 6, height: 6, borderRadius: 3 },
});
