# Screenshots

Taken from the real app (the Expo web build at iPhone size, 390 × 844) running
against a local server with a sample household: Dave, Alice, Bob and Carol.
Bob is off on weekends and Carol on Fridays. No real names or data.

| File | Screen |
|---|---|
| `01-sign-in.png` | Create account / sign in |
| `02-chores.png` | Onboarding: pick chores |
| `03-building.png` | Building a plan, live progress |
| `04-pick.png` | Pick a plan |
| `05-preview.png` | Preview a plan on the fridge board before publishing |
| `06-today.png`, `06-today-dark.png` | Today, light and dark |
| `07-fridge-board.png`, `07-fridge-board-dark.png` | Fridge board with strikethrough, light and dark |
| `08-team.png` | Household and fairness |
| `09-members-invite.png` | Members and an invite code |
| `10-task-sheet.png` | Task sheet: done, missed, covered, not needed |
| `11-setup.png` | Setup |

## Refreshing them

Keep the file names, so the main README picks up new images automatically.

1. Start the server against a throwaway data folder (so your real household
   isn't touched), and start the web build:

   ```sh
   CHORES_DATA_DIR=/tmp/chores-shots python -m uvicorn server.main:app --port 8000
   cd app && npx expo start --web
   ```

2. Open it in a browser at 390 × 844 (device mode in DevTools), go through
   onboarding with the sample household, publish, strike a task or two, and
   capture each screen.

When the app runs on a phone, real device screenshots can replace these. Use
the same names, and resize them to 390 px wide so the gallery stays even.
