import { View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

/** "Step n / 3" progress segments at the top of onboarding. */
export function StepBar({ step, of = 3 }: { step: number; of?: number }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 4, marginTop: 4 }}>
      {Array.from({ length: of }, (_, i) => (
        <View key={i} style={{ flex: 1, height: 2, backgroundColor: i < step ? c.tx : c.line2 }} />
      ))}
    </View>
  );
}
