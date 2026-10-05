import {
  Inter_200ExtraLight, Inter_400Regular, Inter_500Medium, Inter_600SemiBold, useFonts,
} from '@expo-google-fonts/inter';
import { JetBrainsMono_400Regular, JetBrainsMono_500Medium } from '@expo-google-fonts/jetbrains-mono';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppDataProvider } from '@/data/AppData';
import { PrefsProvider } from '@/data/prefs';
import { useReminderSync } from '@/data/reminders';
import { ThemeProvider, useTheme } from '@/theme/ThemeProvider';

SplashScreen.preventAutoHideAsync();

function Navigator() {
  const { c, isDark } = useTheme();
  useReminderSync();
  return (
    <>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }}>
        <Stack.Screen name="task/[id]" options={{ presentation: 'modal' }} />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Inter_200ExtraLight, Inter_400Regular, Inter_500Medium, Inter_600SemiBold,
    JetBrainsMono_400Regular, JetBrainsMono_500Medium,
  });

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AppDataProvider>
          <PrefsProvider>
            <Navigator />
          </PrefsProvider>
        </AppDataProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
