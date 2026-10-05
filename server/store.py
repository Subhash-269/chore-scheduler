"""
store.py - tiny JSON-file persistence for phase 1 (one household, one device
group, no accounts). Everything lives under server/data/, which is
gitignored. Swapped for a real database when accounts arrive in phase 2.
"""
import json
import os
import threading

DATA_DIR = os.environ.get("CHORES_DATA_DIR",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
_lock = threading.Lock()


def path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


def read(name, default=None):
    p = path(name)
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write(name, value):
    p = path(name)
    tmp = p + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)


def delete(name):
    p = path(name)
    if os.path.exists(p):
        os.remove(p)


# file names, in one place
HOUSEHOLD = "household.json"
SCHEDULE = "schedule.json"      # the published schedule
STATUSES = "statuses.json"      # slot_id -> status
STATE = "schedule_state.json"   # carry-over, same format main.py writes
