/**
 * Sign in with Apple / Google. Each returns the provider's identity token,
 * which the server verifies (server/social.py) before creating a session.
 */
import * as AppleAuthentication from 'expo-apple-authentication';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { Platform } from 'react-native';

import { api, type User } from './api';

const GOOGLE_WEB_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID;
const GOOGLE_IOS_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;

// Expo Go doesn't contain the Google Sign-In native module - only dev/store builds do
const inExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

export async function appleAvailable(): Promise<boolean> {
  if (Platform.OS !== 'ios') return false;
  try {
    return await AppleAuthentication.isAvailableAsync();
  } catch {
    return false;
  }
}

export function googleConfigured(): boolean {
  return !inExpoGo && Platform.OS !== 'web' && !!GOOGLE_WEB_CLIENT_ID;
}

/** null when the person cancels the sheet. */
export async function signInWithApple(): Promise<User | null> {
  let credential: AppleAuthentication.AppleAuthenticationCredential;
  try {
    credential = await AppleAuthentication.signInAsync({
      requestedScopes: [
        AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
        AppleAuthentication.AppleAuthenticationScope.EMAIL,
      ],
    });
  } catch (e) {
    if ((e as { code?: string }).code === 'ERR_REQUEST_CANCELED') return null;
    throw e;
  }
  if (!credential.identityToken) throw new Error('Apple did not return an identity token');
  // Apple only shares the name on the very first sign-in - pass it along while we have it
  const name = [credential.fullName?.givenName, credential.fullName?.familyName].filter(Boolean).join(' ') || undefined;
  return api.appleLogin(credential.identityToken, name);
}

/** null when the person cancels. */
export async function signInWithGoogle(): Promise<User | null> {
  // required lazily so Expo Go (no native module) never loads it
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const g = require('@react-native-google-signin/google-signin') as typeof import('@react-native-google-signin/google-signin');
  g.GoogleSignin.configure({ webClientId: GOOGLE_WEB_CLIENT_ID, iosClientId: GOOGLE_IOS_CLIENT_ID });
  try {
    await g.GoogleSignin.hasPlayServices();
    const res = await g.GoogleSignin.signIn();
    if (!g.isSuccessResponse(res)) return null; // cancelled
    if (!res.data.idToken) throw new Error('Google did not return an ID token - check EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID');
    return api.googleLogin(res.data.idToken);
  } catch (e) {
    if (g.isErrorWithCode(e) && e.code === g.statusCodes.SIGN_IN_CANCELLED) return null;
    if (g.isErrorWithCode(e) && e.code === g.statusCodes.PLAY_SERVICES_NOT_AVAILABLE) {
      throw new Error('Google Play services are needed for Google sign-in on this device');
    }
    throw e;
  }
}
