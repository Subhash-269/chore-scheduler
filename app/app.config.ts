import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * app.json holds the static config; this adds what depends on the environment.
 *
 * Google sign-in needs its config plugin with the iOS URL scheme (the iOS OAuth
 * client ID, reversed). Without a Google Cloud client yet, the plugin is left out
 * so builds keep working and the app simply hides the Google button.
 *
 *   EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID   1234-abcd.apps.googleusercontent.com
 *   EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID   5678-efgh.apps.googleusercontent.com  (the server checks tokens against it)
 */
export default ({ config }: ConfigContext): ExpoConfig => {
  const iosClientId = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;
  const plugins = [...(config.plugins ?? [])];
  if (iosClientId) {
    const scheme = `com.googleusercontent.apps.${iosClientId.replace('.apps.googleusercontent.com', '')}`;
    plugins.push(['@react-native-google-signin/google-signin', { iosUrlScheme: scheme }]);
  }
  return { ...config, name: config.name ?? 'Chores', slug: config.slug ?? 'chores', plugins };
};
