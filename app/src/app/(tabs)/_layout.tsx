import { Tabs } from 'expo-router';
import type { BottomTabBarProps } from 'expo-router/tabs';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useAppData } from '@/data/AppData';
import { useTheme } from '@/theme/ThemeProvider';
import { font } from '@/theme/tokens';
import { tap } from '@/ui';

/** Text-only tabs, the active one underlined - straight from the mono mockups. */
function TextTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const { c } = useTheme();
  const { household } = useAppData();
  const insets = useSafeAreaInsets();
  // solo has nobody to share with, so no Team tab
  const hidden = household?.mode === 'solo' ? new Set(['team']) : new Set<string>();
  return (
    <View style={[styles.bar, { borderTopColor: c.line, backgroundColor: c.bg, paddingBottom: Math.max(insets.bottom, 12) }]}>
      {state.routes.map((route, i) => {
        if (hidden.has(route.name)) return null;
        const on = state.index === i;
        const label = descriptors[route.key].options.title ?? route.name;
        return (
          <Pressable key={route.key} hitSlop={10} accessibilityRole="tab" accessibilityState={{ selected: on }}
            onPress={() => {
              const e = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!on && !e.defaultPrevented) { tap(); navigation.navigate(route.name); }
            }}>
            <Text style={{ fontFamily: on ? font.semibold : font.regular, fontSize: 12.5, color: on ? c.tx : c.tx3,
              textDecorationLine: on ? 'underline' : 'none' }}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function TabsLayout() {
  const { c } = useTheme();
  return (
    <Tabs tabBar={(props) => <TextTabBar {...props} />}
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: c.bg } }}>
      <Tabs.Screen name="today" options={{ title: 'Today' }} />
      <Tabs.Screen name="calendar" options={{ title: 'Calendar' }} />
      <Tabs.Screen name="team" options={{ title: 'Team' }} />
      <Tabs.Screen name="setup" options={{ title: 'Setup' }} />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', justifyContent: 'space-around', paddingTop: 13, borderTopWidth: StyleSheet.hairlineWidth },
});
