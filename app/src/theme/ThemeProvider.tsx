import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

import { dark, light, PERSON_COLORS, type Palette } from './tokens';

export type Appearance = 'system' | 'light' | 'dark';

type ThemeValue = {
  c: Palette;
  isDark: boolean;
  appearance: Appearance;
  setAppearance: (a: Appearance) => void;
  /** Colour for a roommate, honouring a saved pick, else by position. */
  personColor: (name: string, roommates: string[], saved?: Record<string, string>) => string;
};

const ThemeContext = createContext<ThemeValue | null>(null);
const KEY = 'chores.appearance';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [appearance, setAppearanceState] = useState<Appearance>('system');

  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((v) => {
        if (v === 'light' || v === 'dark' || v === 'system') setAppearanceState(v);
      })
      .catch(() => {});
  }, []);

  const value = useMemo<ThemeValue>(() => {
    const isDark = appearance === 'system' ? system === 'dark' : appearance === 'dark';
    return {
      c: isDark ? dark : light,
      isDark,
      appearance,
      setAppearance: (a) => {
        setAppearanceState(a);
        AsyncStorage.setItem(KEY, a).catch(() => {});
      },
      personColor: (name, roommates, saved) => {
        const pick = saved?.[name];
        if (pick) {
          const pair = PERSON_COLORS.find(([l]) => l === pick);
          return pair ? pair[isDark ? 1 : 0] : pick;
        }
        const i = Math.max(0, roommates.indexOf(name));
        return PERSON_COLORS[i % PERSON_COLORS.length][isDark ? 1 : 0];
      },
    };
  }, [appearance, system]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const v = useContext(ThemeContext);
  if (!v) throw new Error('useTheme outside ThemeProvider');
  return v;
}
