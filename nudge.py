#!/usr/bin/env python3
"""Schedule nudger — GitHub's cron delivery runs hours late for over-quota accounts,
so this runs locally (launchd, every 10 min) and dispatches any workflow whose
scheduled slot passed >10 min ago with no run started. GitHub stays the system of
record (runs/logs/secrets); this only replaces the *trigger* reliability.

Idempotent: skips if any run was created at/after the slot, and remembers slots it
already dispatched (~/.automation_nudger_state.json) so it never double-fires.
"""
import json, os, subprocess, sys
from datetime import datetime, timedelta, timezone

GH = "/opt/homebrew/bin/gh"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.expanduser("~/.automation_nudger_state.json")
GRACE_MIN = 10      # give GitHub this long to fire on its own
LOOKBACK_H = 3      # don't resurrect slots older than this

def cron_match(cron, dt):
    """Minimal 5-field cron matcher: *, lists, ranges, steps. dow: 0/7=Sun."""
    def ok(field, val, lo, hi):
        if field == "*": return True
        for part in field.split(","):
            step = 1
            if "/" in part: part, s = part.split("/"); step = int(s)
            if part == "*": rng = range(lo, hi + 1)
            elif "-" in part:
                a, b = part.split("-"); rng = range(int(a), int(b) + 1)
            else: rng = range(int(part), int(part) + 1)
            if val in rng and (val - rng.start) % step == 0: return True
        return False
    m, h, dom, mon, dow = cron.split()
    return (ok(m, dt.minute, 0, 59) and ok(h, dt.hour, 0, 23) and ok(dom, dt.day, 1, 31)
            and ok(mon, dt.month, 1, 12) and ok(dow, dt.weekday() + 1 if dt.weekday() < 6 else 0, 0, 7))
    # note: python weekday Mon=0..Sun=6 -> cron Sun=0, Mon=1..Sat=6

def latest_slot(cron, now):
    t = now.replace(second=0, microsecond=0)
    for _ in range(LOOKBACK_H * 60):
        if cron_match(cron, t): return t
        t -= timedelta(minutes=1)
    return None

def gh_json(args):
    r = subprocess.run([GH] + args, capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError(r.stderr[:200])
    return json.loads(r.stdout) if r.stdout.strip() else {}

def main():
    now = datetime.now(timezone.utc)
    cfg = json.load(open(os.path.join(HERE, "schedules.json")))
    try: state = json.load(open(STATE_PATH))
    except Exception: state = {}
    fired = 0
    for e in cfg["entries"]:
        repo, wf, cron = e["repo"], e["workflow"], e["cron"]
        slot = latest_slot(cron, now - timedelta(minutes=GRACE_MIN))
        if not slot: continue
        key = f"{repo}/{wf}@{cron}"
        if state.get(key) == slot.isoformat(): continue          # already nudged this slot
        try:
            runs = gh_json(["api", f"repos/Nadreau/{repo}/actions/workflows/{wf}/runs"
                            f"?created=%3E%3D{(slot - timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')}&per_page=1",
                            "--jq", "{n: .total_count}"])
            if runs.get("n", 0) > 0:
                state[key] = slot.isoformat(); continue          # GitHub fired it (or someone did)
            subprocess.run([GH, "workflow", "run", wf, "-R", f"Nadreau/{repo}"],
                           capture_output=True, text=True, timeout=60)
            state[key] = slot.isoformat(); fired += 1
            print(f"{now:%H:%M}Z nudged {key} (slot {slot:%H:%M}Z was never started)")
        except Exception as ex:
            print(f"{now:%H:%M}Z ERROR {key}: {str(ex)[:120]}")
    json.dump(state, open(STATE_PATH, "w"), indent=1)
    if fired == 0: print(f"{now:%H:%M}Z all schedules on time")

if __name__ == "__main__":
    main()
