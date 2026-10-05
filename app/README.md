# Chores app (iOS + Android)

React Native + Expo (SDK 57) front end for the chore scheduler. The six
algorithms still run in Python: the app talks to `server/` over Wi-Fi.

```
app/ (Expo, TypeScript)  ──HTTP──>  server/ (FastAPI)  ──>  optimizer.py + scheduler.py
```

## Run it on your phone

1. **Server** - from the repo root:

   ```sh
   pip install -r server/requirements.txt
   python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
   ```

   Use `python -m uvicorn`, not bare `uvicorn`: with the Microsoft Store
   Python, Windows blocks the `uvicorn.exe` launcher ("Access is denied").
   `--host 0.0.0.0` lets your phone reach it. On Windows, allow Python
   through the firewall for private networks the first time it asks.

2. **App** - in `app/`:

   ```sh
   npm install
   npx expo start
   ```

   Scan the QR code with the **Expo Go** app (iOS: Camera app, Android:
   Expo Go). Phone and computer must be on the same Wi-Fi.

The app guesses the server address from the machine running Metro
(`http://<that-ip>:8000`). If it can't connect, it shows a Connect screen
where you can type the address, or set `EXPO_PUBLIC_API_URL` before
`npx expo start`.

Browser preview: `npx expo start --web`.

## What's in the app

- Accounts: email + password, Sign in with Apple, Google (in builds that are set up for it)
- Households: start one or join with a 6-character code; admins and members; switch between households
- Onboarding: roommates (and which one is you), chores, availability
- Building: all six algorithms with live per-algorithm progress
- Pick a schedule (ranked like `main.py`), then preview any candidate on the full fridge board before publishing
- Today, Calendar (fridge board / list / only me), Team, person detail, Members with invite codes
- Strikethrough status: tap to strike, again for missed; long-press for covered,
  not needed, or per-session strikes for chores done several times a day
- Setup (admins): edit / add / delete chores, house rules, re-plan, schedule health
- Settings: light / dark / system, households, sign out, delete account, CSV/DOCX/PDF export

## Sign in with Apple and Google

Apple works in Expo Go on an iPhone. Google needs a development build
(`npx eas-cli@latest build --profile development`), because Expo Go doesn't
include its native module, plus these environment variables:

| Where | Variable | Value |
|---|---|---|
| app | `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` | the **Web** OAuth client ID (Google signs the ID token for it) |
| app | `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` | the **iOS** OAuth client ID (also sets the URL scheme in `app.config.ts`) |
| server | `GOOGLE_CLIENT_IDS` | the same client IDs, comma-separated |
| server | `APPLE_AUDIENCES` | optional; defaults to `com.subhash269.chores,host.exp.Exponent` |

Data lives in `server/data/` (gitignored): `chores.db` (accounts, households,
schedules, statuses) and one `schedule_state.json` per household (the same
carry-over file `main.py` writes).

## Checks

```sh
npx tsc --noEmit      # types
npx expo lint         # lint
python -m pytest -c server/pytest.ini --rootdir=server server/tests   # API, from the repo root
```

## Layout

| Path | What |
|---|---|
| `src/app/` | routes (Expo Router): `(tabs)/`, `onboarding/`, `plan/`, `task/[id]`, `chore/[name]`, `person/[name]` … |
| `src/ui/` | the mono design system: `index.tsx` (text, rows, buttons, seg, toggle, stepper, pills, `Strike`), `FridgeGrid`, `WeekStrip`, `WeekdayPicker` |
| `src/theme/` | tokens (light / dark, person colours) and the appearance provider |
| `src/data/` | API client, app-wide data store, date helpers, presets |
