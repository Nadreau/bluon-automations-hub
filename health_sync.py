#!/usr/bin/env python3
"""Automations Hub — keeps the Bluon Notion "Automations Hub" page current as a LIVE story:

  1. Headline callout: free-minutes meter for the month + whether private automations are blocked
  2. "The story right now" — auto-generated narrative (what's healthy / failing / paused and WHY)
  3. Minutes leaderboard — every automation ranked by Actions minutes burned this month,
     with repo visibility (public = free / private = metered), status, and the reason
  4. The detail database (rows also refreshed: status, last run, links)

Status logic: disabled → ⏸ Paused · no run in 30d → 💤 Dormant · latest run OK/running → 🟢 Healthy
· else 🔴 Failing. A failing run whose job never started (0 jobs) is flagged as GitHub's billing
block, not a code failure.

Env: NOTION_KEY, GH_TOKEN (repo-scope so private repos' run metadata is readable).
"""
import json, math, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

NK = os.environ["NOTION_KEY"]
GH = os.environ["GH_TOKEN"]
CFG = json.load(open(os.path.join(os.path.dirname(__file__) or ".", "hub_config.json")))
DS = CFG["data_source_id"]; PAGE = CFG["page_id"]

def nt(method, p, pl=None, retries=4):
    for i in range(retries):
        req = urllib.request.Request("https://api.notion.com/v1/" + p,
            data=json.dumps(pl).encode() if pl is not None else None, method=method,
            headers={"Authorization": "Bearer " + NK, "Notion-Version": "2025-09-03",
                     "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504): time.sleep(1.5 * (i + 1)); continue
            sys.stderr.write(f"notion {e.code} {p} {e.read().decode()[:120]}\n"); return {}
        except Exception: time.sleep(1.5 * (i + 1))
    return {}

def gh(p):
    req = urllib.request.Request("https://api.github.com" + p,
        headers={"Authorization": "Bearer " + GH, "Accept": "application/vnd.github+json",
                 "User-Agent": "bluon-automations-hub"})
    try:
        return json.load(urllib.request.urlopen(req))
    except Exception as e:
        sys.stderr.write(f"gh {p}: {e}\n"); return {}

def T(s): return [{"type": "text", "text": {"content": (s or "")[:1900]}}]
def TB(s): return [{"type": "text", "text": {"content": (s or "")[:1900]}, "annotations": {"bold": True}}]

REPOS = {  # repo -> System
    "bluon-account-agent":   "Account Intelligence",
    "bluon-ads-dashboard":   "Ads Reporting",
    "bluon-sales-coach":     "Sales Coaching",
    "bluon-sales-meeting-sync": "Meeting Sync",
    "bluon-email-machine":   "Email Machine",
    "hubspot-research-agent": "Research Agents",
    "bluon-market-intel":    "Research Agents",
    "bluon-automations-hub": "Health",
}
SKIP_FILES = {"diag.yml", "maint.yml", "enrich.yml"}  # manual utility jobs, not agents

# friendly name / what-it-does / human schedule / live report page — keyed "repo/file"
CATALOG = {
 # key: (name, what it does, human schedule, live report page, flow "source → destination")
 "bluon-account-agent/status-refresh.yml": ("Account numbers refresh", "Keeps every account's Activated / Pending / ARR current", "2×/day weekdays", "https://www.notion.so/356576a5c12d80bfaa75c13940485416", "HubSpot B4B deals → Accounts directory (Notion)"),
 "bluon-account-agent/route.yml": ("Call router", "Files every new rep call to the right account + refreshes that account's brief", "Every 2h, 8:30a–6:30p ET wkdys", "https://www.notion.so/356576a5c12d80bfaa75c13940485416", "Rep call DBs + Dropbox → account pages (Call History + brief)"),
 "bluon-account-agent/refresh-accounts.yml": ("Weekly page refresh", "Safety-net pass over all 1,032 account pages — only rewrites what changed", "Sundays ~1pm ET", "https://www.notion.so/356576a5c12d80bfaa75c13940485416", "HubSpot + call DBs → all account pages"),
 "bluon-account-agent/build-all.yml": ("New-account page builder", "Builds a rich page for any account that doesn't have one yet", "2×/day", "https://www.notion.so/356576a5c12d80bfaa75c13940485416", "HubSpot → new account pages (Notion)"),
 "bluon-account-agent/archive.yml": ("Old-call archiver", "Moves calls older than 2 months to the Archive so live DBs stay fast", "Sundays", "", "Sales Pitches + Kickoffs DBs → Archive DBs"),
 "bluon-ads-dashboard/update-meta-reporting.yml": ("Meta ads report", "Rebuilds the Meta report: spend, CTR, reach per ad set", "Daily ~8am ET", "https://www.notion.so/37a576a5c12d81798a42eb3f518308fa", "Meta Ads API → Meta Ads Reporting page"),
 "bluon-ads-dashboard/update-google-ads-reporting.yml": ("Google ads report", "Rebuilds the Google report: all 4 Demand Gen campaigns", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d815080f8e7a194531cb6", "Google Ads API → Google Ads Reporting page"),
 "bluon-ads-dashboard/update-openai-ads-reporting.yml": ("ChatGPT ads report", "Rebuilds the ChatGPT ads report", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d816e9fe9e7d126861a0f", "OpenAI Ads API → ChatGPT Ads Reporting page"),
 "bluon-ads-dashboard/update-landing-reporting.yml": ("Landing pages report", "Web traffic funnel by source", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d8133847ce3ef573f650b", "GA4 → Landing Page Reporting page"),
 "bluon-ads-dashboard/update-dashboard.yml": ("Ads dashboard", "Top-level daily ads dashboard", "Daily ~7am ET", "", "Meta Ads API → Ads dashboard page"),
 "bluon-ads-dashboard/update-budget-breakdown.yml": ("Budget breakdown", "Where the daily ad budget goes, by audience", "Daily ~11am ET", "https://www.notion.so/333576a5c12d81ab960bc7b23d554fcb", "Meta Ads API → Budget Breakdown page"),
 "bluon-ads-dashboard/update-combined-overview.yml": ("Combined ads overview", "All ad platforms on one page", "Daily ~8am ET", "https://www.notion.so/2ac76c456c6e4a99bcb65bbf97340697", "Meta + Google + OpenAI APIs → Combined Overview page"),
 "bluon-ads-dashboard/update-where-from.yml": ("Where They Came From", "How prospects say they heard about Bluon", "Daily ~8:15am ET", "https://www.notion.so/38e576a5c12d8102b765e9f87fa79f78", "Sales-call transcripts + demo sheet → Attribution page"),
 "bluon-ads-dashboard/sync-dco-database.yml": ("DCO sheet sync", "Pulls Clay's new ad links into Notion", "Every 4h", "", "Clay's Google Sheet → DCO database (Notion)"),
 "bluon-sales-coach/grade.yml": ("Pitch + kickoff grader", "AI-grades every new sales pitch and kickoff call", "10a / 1p / 4p ET wkdys", "", "B4B Kickoffs + Sales Pitches DBs → scores on each call (Notion)"),
 "bluon-sales-coach/digest.yml": ("Coaching digest", "Sends each rep their daily coaching summary", "~6pm ET weekdays", "", "Call scores (Notion) → Slack (Coaching Agent)"),
 "bluon-sales-meeting-sync/sync.yml": ("AM standup → shared Sales DB", "Copies Niko's 10am sales standup note (summary, action items, transcript) into the team's shared database", "10:30a–12:30p ET sweep, Mon–Sat", "", "Niko's personal Notion → Internal Sales Meetings DB (Bluon)"),
 "bluon-email-machine/rolling-drafts.yml": ("Email drafts (rolling)", "Drafts segment emails on a rolling schedule", "paused", "", "HubSpot segments → email drafts (Notion)"),
 "bluon-email-machine/to-hubspot.yml": ("Email → HubSpot", "Pushes approved drafts into HubSpot", "paused", "", "Approved drafts (Notion) → HubSpot emails"),
 "bluon-email-machine/approval-notify.yml": ("Email approval ping", "Slack ping when a draft awaits approval", "paused", "", "Notion draft status → Slack"),
 "bluon-email-machine/reporting.yml": ("Email reporting", "Email performance report", "paused", "https://www.notion.so/38e576a5c12d81879c21f82642db1fa1", "HubSpot email stats → Email Reporting page"),
 "bluon-email-machine/regen-mockup.yml": ("Email mockup regen", "Regenerates an email mockup on request", "paused", "", "Notion request → email mockup"),
 "bluon-email-machine/weekly-drafts.yml": ("Email weekly drafts", "Superseded weekly batch", "manual", "", "—"),
 "bluon-automations-hub/health.yml": ("This health page", "Checks every automation and rewrites this page", "3×/day", "", "GitHub + billing APIs → this page"),
}
PAUSE_REASONS = {
    "bluon-email-machine": "Paused on purpose (Jul 5) — the email machine project is shelved; its webhooks had kept firing for weeks",
    "bluon-market-intel": "Paused — superseded by newer research automations",
}

now = datetime.now(timezone.utc)
CYCLE_START = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
INCLUDED_MIN = 2000
RATE = 0.006  # $/Linux-minute (from the billing API)

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
def pdate(s): return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

# ── authoritative per-repo minutes from the billing API (what GitHub actually counts) ──
billing_repo_mins = {}
bill = gh(f"/users/Nadreau/settings/billing/usage?year={now.year}&month={now.month}")
for it in bill.get("usageItems", []):
    if it.get("product") == "actions" and "Linux" in it.get("sku", ""):
        rn = it.get("repositoryName") or "?"
        billing_repo_mins[rn] = billing_repo_mins.get(rn, 0) + it.get("quantity", 0)

# ── expected schedules (shared with nudge.py) for Overdue detection ──
SCHED = {}
try:
    for _e in json.load(open(os.path.join(os.path.dirname(__file__) or ".", "schedules.json")))["entries"]:
        SCHED.setdefault(f"{_e['repo']}/{_e['workflow']}", []).append(_e["cron"])
except Exception: pass
from datetime import timedelta
def _cron_match(cron, dt):
    def ok(field, val, lo, hi):
        if field == "*": return True
        for part in field.split(","):
            step = 1
            if "/" in part: part, s2 = part.split("/"); step = int(s2)
            if part == "*": rng = range(lo, hi + 1)
            elif "-" in part:
                a, b = part.split("-"); rng = range(int(a), int(b) + 1)
            else: rng = range(int(part), int(part) + 1)
            if val in rng and (val - rng.start) % step == 0: return True
        return False
    m, hh, dom, mon, dow = cron.split()
    return (ok(m, dt.minute, 0, 59) and ok(hh, dt.hour, 0, 23) and ok(dom, dt.day, 1, 31)
            and ok(mon, dt.month, 1, 12) and ok(dow, dt.weekday() + 1 if dt.weekday() < 6 else 0, 0, 7))
def last_expected_slot(key, now, grace_min=25, lookback_h=12):
    best = None
    for cron in SCHED.get(key, []):
        t = (now - timedelta(minutes=grace_min)).replace(second=0, microsecond=0)
        for _ in range(lookback_h * 60):
            if _cron_match(cron, t):
                if best is None or t > best: best = t
                break
            t -= timedelta(minutes=1)
    return best

# ── self-hosted runner state per repo (jobs on Niko's Mac = zero minutes) ──
runner_state = {}   # repo -> "online" | "offline"
for _repo in REPOS:
    _rs = gh(f"/repos/Nadreau/{_repo}/actions/runners").get("runners", [])
    if _rs: runner_state[_repo] = _rs[0]["status"]

# ── gather: per repo → visibility, workflows, latest runs, minutes this cycle ──
rows = []          # one dict per tracked workflow
repo_public = {}
for repo, system in REPOS.items():
    meta = gh(f"/repos/Nadreau/{repo}")
    public = not meta.get("private", True)
    repo_public[repo] = public
    wfs = {w["id"]: w for w in gh(f"/repos/Nadreau/{repo}/actions/workflows").get("workflows", [])
           if w["path"].split("/")[-1] not in SKIP_FILES}
    # billed minutes this cycle, per workflow (billed = ceil(wall-clock/60) per completed run)
    mins, latest = {}, {}
    page = 1
    while page <= 6:
        r = gh(f"/repos/Nadreau/{repo}/actions/runs?created=%3E%3D{CYCLE_START.date()}&per_page=100&page={page}&exclude_pull_requests=true")
        runs = r.get("workflow_runs", [])
        for run in runs:
            wid = run["workflow_id"]
            if wid not in wfs: continue
            if wid not in latest: latest[wid] = run   # list is newest-first
            if run.get("status") == "completed" and run.get("run_started_at") and run.get("updated_at"):
                secs = (pdate(run["updated_at"]) - pdate(run["run_started_at"])).total_seconds()
                if secs > 0: mins[wid] = mins.get(wid, 0) + max(1, math.ceil(secs / 60))
        if len(runs) < 100: break
        page += 1
    for wid, wf in wfs.items():
        fname = wf["path"].split("/")[-1]
        friendly, desc, sched, report, flow = CATALOG.get(f"{repo}/{fname}", (wf["name"], "", "", "", ""))
        run = latest.get(wid)
        if run is None:   # nothing this cycle — fetch the actual latest for status
            rr = gh(f"/repos/Nadreau/{repo}/actions/workflows/{wid}/runs?per_page=1&exclude_pull_requests=true").get("workflow_runs", [])
            run = rr[0] if rr else None
        # status + WHY
        if wf["state"] != "active":
            st, why = "⏸ Paused", PAUSE_REASONS.get(repo, "Paused on purpose")
        elif not run:
            st, why = "💤 Dormant", "Never run"
        elif run.get("status") == "in_progress":
            st, why = "▶️ Running", "Running right now" + (" on the Mac runner" if repo in runner_state else "")
        elif run.get("status") == "queued":
            if runner_state.get(repo) == "offline":
                st, why = "🕐 Queued", "Waiting for Niko's Mac to come online (runner offline) — runs on wake, expires after 24h"
            elif repo in runner_state:
                st, why = "🕐 Queued", "Waiting for a free slot on the Mac runner (another job is running)"
            else:
                st, why = "🕐 Queued", "Waiting for a GitHub-hosted runner"
        elif (now - pdate(run["run_started_at"])).days > 30:
            st, why = "💤 Dormant", f"No runs in {(now - pdate(run['run_started_at'])).days} days"
        elif run.get("conclusion") == "success":
            st, why = "🟢 Healthy", "Running normally"
        else:
            # billing-blocked runs DO get a job, but it dies in seconds with ZERO steps executed
            jl = gh(f"/repos/Nadreau/{repo}/actions/runs/{run['id']}/jobs").get("jobs", [])
            if jl and all(not j.get("steps") for j in jl):
                why = ("Last run hit the GitHub billing block — since moved to the Mac runner; clears itself at the next scheduled run"
                       if repo in runner_state else
                       "Never started — GitHub billing block (free minutes exhausted; resumes once a budget is set)")
                st = "🔴 Failing"
            else:
                st, why = "🔴 Failing", "Run failed — check the log"
        # Overdue: an expected slot passed but no run started for it (GitHub cron lag)
        if st in ("🟢 Healthy", "🔴 Failing", "💤 Dormant") and wf["state"] == "active":
            slot = last_expected_slot(f"{repo}/{fname}", now)
            if slot and (run is None or pdate(run["created_at"] if "created_at" in run else run["run_started_at"]) < slot):
                st, why = "⏳ Overdue", f"Its {slot:%H:%M} UTC slot hasn't started — GitHub cron is lagging; the Mac nudger fires it within ~10 min"
        rows.append(dict(repo=repo, system=system, file=fname, friendly=friendly, desc=desc,
                         sched=sched, report=report, flow=flow, public=public, status=st, why=why,
                         mins=mins.get(wid, 0), run=run, wf=wf))

rows.sort(key=lambda x: -x["mins"])
# meter uses BILLING-grade numbers (GitHub's own count); leaderboard uses per-workflow estimates
counted = round(sum(m for rn, m in billing_repo_mins.items() if not repo_public.get(rn, True)))
free_pub = round(sum(m for rn, m in billing_repo_mins.items() if repo_public.get(rn, True)))
total_bill = round(sum(billing_repo_mins.values()))
n_ok = sum(1 for r in rows if r["status"].startswith("🟢"))
n_fail = sum(1 for r in rows if r["status"].startswith("🔴"))
n_pause = sum(1 for r in rows if r["status"].startswith("⏸"))
n_dorm = sum(1 for r in rows if r["status"].startswith("💤"))
n_run = sum(1 for r in rows if r["status"].startswith("▶️"))
n_queue = sum(1 for r in rows if r["status"].startswith("🕐"))
mac_repos = len(runner_state)
mac_online = sum(1 for v in runner_state.values() if v == "online")
blocked = any("billing block" in r["why"] for r in rows)
over = max(0, total_bill - INCLUDED_MIN)
stamp = now.strftime("%b %d, %I:%M %p UTC")

# ── 1) rewrite the page (Meta-reporting layout: H1 sections w/ inline stats, per-item
#      heading_3 + gray stat callout, · separators, dividers). Detail DB stays at bottom. ──
kids = nt("GET", f"blocks/{PAGE}/children?page_size=100").get("results", [])
anchor = next((b for b in kids if b["type"] == "callout"), None)
dbblock = next((b for b in kids if b["type"] == "child_database"), None)
for b in kids:   # clear everything managed except the anchor callout + the DB itself
    if b["id"] not in {anchor and anchor["id"], dbblock and dbblock["id"]}:
        nt("DELETE", f"blocks/{b['id']}")

pct = min(100, round(total_bill / INCLUDED_MIN * 100))
live_bits = [f"{n_ok} healthy"]
if n_run: live_bits.append(f"{n_run} running now")
if n_queue: live_bits.append(f"{n_queue} queued")
live_bits += [f"{n_fail} failing", f"{n_pause} paused"]
mac_bit = (f"🖥 Mac runner ONLINE — {mac_repos} systems run free on Niko's Mac" if mac_online == mac_repos and mac_repos
           else f"🖥 ⚠️ Mac runner OFFLINE ({mac_online}/{mac_repos}) — its jobs queue until the Mac wakes")
head = (f"This month  ·  {total_bill:,} / {INCLUDED_MIN:,} free GitHub minutes ({pct}%)"
        + (f"  ·  {over:,} min over" if over else "")
        + f"  ·  {' · '.join(live_bits)}\n{mac_bit}"
        + (f"\n⛔ GitHub-hosted runs in private repos are blocked (no budget set) — Mac-runner + public-repo jobs are unaffected." if blocked else "\n✅ All systems running.")
        + f"  Resets the 1st · updated {stamp}")
if anchor:
    nt("PATCH", f"blocks/{anchor['id']}", {"callout": {"rich_text": T(head), "icon": {"emoji": "⛽"},
        "color": "red_background" if blocked else "green_background"}})

def _fmt_last(run):
    return pdate(run["run_started_at"]).strftime("%b %-d") if run else "never"

# group by system, rank systems + automations by minutes
by_sys = {}
for r in rows: by_sys.setdefault(r["system"], []).append(r)
sys_order = sorted(by_sys, key=lambda s: -sum(x["mins"] for x in by_sys[s]))

def _cells(*vals):
    return {"type": "table_row", "table_row": {"cells": [T(v) for v in vals]}}
def _hcells(*vals):
    return {"type": "table_row", "table_row": {"cells": [TB(v) for v in vals]}}

SYS_BLURB = {
    "Account Intelligence": "The self-maintaining account pages: HubSpot numbers, routed calls, briefs — 1,032 accounts.",
    "Ads Reporting": "The daily marketing report pages (Meta, Google, ChatGPT, landing, attribution).",
    "Sales Coaching": "AI grading of every pitch/kickoff + the daily Slack digest.",
    "Meeting Sync": "Niko's AM standup note, copied into the team's shared meetings database.",
    "Email Machine": "Cold-email drafting system — shelved for now.",
    "Research Agents": "On-demand company / market research.",
    "Health": "The watcher that keeps this page honest.",
}

blocks = []
# ── overview: one row per system, ranked by minutes ──
blocks.append({"type": "heading_1", "heading_1": {"rich_text": T("At a Glance")}})
by_sys = {}
for r in rows: by_sys.setdefault(r["system"], []).append(r)
sys_order = sorted(by_sys, key=lambda s: -sum(x["mins"] for x in by_sys[s]))
ov = [_hcells("System", "Agents", "Health", "Min (mo)", "Runs on")]
for sname in sys_order:
    items = by_sys[sname]
    icons = "".join(x["status"].split()[0] for x in sorted(items, key=lambda x: -x["mins"]))
    where = ("🖥 Niko's Mac — free" if all(x["repo"] in runner_state for x in items)
             else ("🌐 cloud — free" if all(x["public"] for x in items) else "☁️ cloud"))
    ov.append(_cells(sname, str(len(items)), icons, f"{sum(x['mins'] for x in items):,}", where))
blocks.append({"type": "table", "table": {"table_width": 5, "has_column_header": True,
    "has_row_header": False, "children": ov}})

# ── per-system sections: heading + purpose + clean table ──
for sname in sys_order:
    items = sorted(by_sys[sname], key=lambda x: -x["mins"])
    blocks.append({"type": "divider", "divider": {}})
    blocks.append({"type": "heading_2", "heading_2": {"rich_text": T(f"{sname}")}})
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": SYS_BLURB.get(sname, "")},
         "annotations": {"italic": True, "color": "gray"}}]}})
    tbl = [_hcells("", "Automation", "Connection (from → to)", "Schedule", "Last run")]
    for x in items:
        status_cell = x["status"] + ("" if x["status"].startswith(("🟢", "▶️")) else f"\n{x['why'][:80]}")
        name_cell = x["friendly"] + (f"\n{x['desc']}" if x["desc"] else "")
        tbl.append(_cells(status_cell, name_cell, x.get("flow", "") or "—",
                          x["sched"] or "manual", _fmt_last(x["run"])))
    blocks.append({"type": "table", "table": {"table_width": 5, "has_column_header": True,
        "has_row_header": False, "children": tbl}})

blocks.append({"type": "divider", "divider": {}})
blocks.append({"type": "heading_2", "heading_2": {"rich_text": T("🗂 Click-through detail (run logs + report pages)")}})

# insert after the anchor banner (before the DB). Chunks are appended in REVERSE order,
# each anchored to the banner itself — so chunk order can't interleave with the DB block.
CH = 20
chunks = [blocks[i:i + CH] for i in range(0, len(blocks), CH)]
for chunk in reversed(chunks):
    nt("PATCH", f"blocks/{PAGE}/children", {"children": chunk, **({"after": anchor["id"]} if anchor else {})})

# ── 2) refresh the detail DB rows ──
existing = {}
cur = None
while True:
    body = {"page_size": 100}
    if cur: body["start_cursor"] = cur
    r = nt("POST", f"data_sources/{DS}/query", body)
    for row in r.get("results", []):
        t = "".join(x.get("plain_text", "") for x in row["properties"]["Automation"]["title"])
        existing[t] = row["id"]
    if not r.get("has_more"): break
    cur = r["next_cursor"]

for r in rows:
    run = r["run"]
    props = {
        "Automation": {"title": T(r["friendly"])},
        "System": {"select": {"name": r["system"]}},
        "What it does": {"rich_text": T(r["desc"])},
        "Schedule": {"rich_text": T(r["sched"])},
        "Status": {"select": {"name": r["status"]}},
        "Last result": {"select": {"name": (run.get("conclusion") or "—") if run else "—"}},
        "Run log": {"url": run["html_url"] if run else r["wf"]["html_url"]},
    }
    if r["report"]: props["Report page"] = {"url": r["report"]}
    if run: props["Last run"] = {"date": {"start": run["run_started_at"]}}
    if r["friendly"] in existing:
        nt("PATCH", f"pages/{existing[r['friendly']]}", {"properties": props})
    else:
        nt("POST", "pages", {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": props})
    time.sleep(0.25)

print(f"story rebuilt · {len(rows)} automations · counted {counted} min (private) + {free_pub} free (public) · "
      f"{n_ok}🟢 {n_fail}🔴 {n_pause}⏸ {n_dorm}💤")
