import { Stack } from 'expo-router';

import { useTheme } from '@/theme/ThemeProvider';

export default function PlanLayout() {
  const { c } = useTheme();
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }} />;
}
