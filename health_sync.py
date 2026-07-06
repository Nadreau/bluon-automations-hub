#!/usr/bin/env python3
"""Automations Hub health sync — keeps the Bluon Notion "Automations Hub" page current.

For every tracked repo it discovers the GitHub Actions workflows, reads each one's
latest run + enabled/disabled state, computes a health status, and upserts a row in
the Automation Status DB (hub_config.json holds the Notion ids):
  🟢 Healthy = latest run succeeded · 🔴 Failing = latest run failed
  ⏸ Paused  = workflow disabled     · 💤 Dormant = no run in 30+ days
Env: NOTION_KEY, GH_TOKEN (repo-scope PAT so private repos' runs are readable).
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

NK = os.environ["NOTION_KEY"]
GH = os.environ["GH_TOKEN"]
CFG = json.load(open(os.path.join(os.path.dirname(__file__) or ".", "hub_config.json")))
DS = CFG["data_source_id"]

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
 "bluon-account-agent/status-refresh.yml": ("Account directory numbers", "Pulls live HubSpot stats (activated/pending/ARR) into the Accounts directory rows + status pages", "2×/day weekdays", "https://www.notion.so/356576a5c12d80bfaa75c13940485416"),
 "bluon-account-agent/route.yml": ("Call router + account briefs", "Reads new calls in the reps' meeting DBs + Dropbox, tags the right account, logs to its Call History, refreshes the page", "Every 2h, 8:30a–6:30p ET weekdays", "https://www.notion.so/356576a5c12d80bfaa75c13940485416"),
 "bluon-account-agent/refresh-accounts.yml": ("Account pages weekly refresh", "Incrementally refreshes every built account page (scorecard, org chart, call history) — only rewrites accounts whose data changed", "Sundays ~7am ET", "https://www.notion.so/356576a5c12d80bfaa75c13940485416"),
 "bluon-account-agent/build-all.yml": ("Account page builder", "Builds rich account pages for any not-yet-built directory accounts", "2×/day", "https://www.notion.so/356576a5c12d80bfaa75c13940485416"),
 "bluon-account-agent/archive.yml": ("Call archive sweep", "Moves Sales Pitches + Kickoff rows older than 2 months into the Archive (keeps the live DBs fast)", "Sundays", ""),
 "bluon-ads-dashboard/update-meta-reporting.yml": ("Meta ads report", "Rebuilds the Meta Ads Reporting page from the Meta API", "Daily ~8am ET", "https://www.notion.so/37a576a5c12d81798a42eb3f518308fa"),
 "bluon-ads-dashboard/update-google-ads-reporting.yml": ("Google ads report", "Rebuilds the Google Ads Reporting page (all 4 Demand Gen campaigns + status)", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d815080f8e7a194531cb6"),
 "bluon-ads-dashboard/update-openai-ads-reporting.yml": ("ChatGPT ads report", "Rebuilds the OpenAI/ChatGPT Ads Reporting page", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d816e9fe9e7d126861a0f"),
 "bluon-ads-dashboard/update-landing-reporting.yml": ("Landing pages report", "Rebuilds the Landing Page Reporting page from GA4 (by-source funnel)", "Daily ~8am ET", "https://www.notion.so/37b576a5c12d8133847ce3ef573f650b"),
 "bluon-ads-dashboard/update-dashboard.yml": ("Ads dashboard", "Daily top-level ads dashboard rebuild", "Daily ~7am ET", ""),
 "bluon-ads-dashboard/update-budget-breakdown.yml": ("Budget breakdown", "Rebuilds the audience budget breakdown page", "Daily ~11am ET", "https://www.notion.so/333576a5c12d81ab960bc7b23d554fcb"),
 "bluon-ads-dashboard/update-combined-overview.yml": ("Combined ads overview", "Rebuilds the all-platform combined overview", "Daily ~8am ET", "https://www.notion.so/2ac76c456c6e4a99bcb65bbf97340697"),
 "bluon-ads-dashboard/update-where-from.yml": ("Where They Came From", "Attribution report — how prospects heard about Bluon (call transcripts + demo sheet)", "Daily ~8:15am ET", "https://www.notion.so/38e576a5c12d8102b765e9f87fa79f78"),
 "bluon-ads-dashboard/sync-dco-database.yml": ("DCO sheet sync", "Mirrors Clay's DCO Google Sheet links into Notion", "Every 4h", ""),
 "bluon-sales-coach/grade.yml": ("Pitch + kickoff grader", "Grades new sales pitches and kickoff calls with Claude, writes scores back", "10am / 1pm / 4pm ET weekdays", ""),
 "bluon-sales-coach/digest.yml": ("Coaching digest", "Posts the daily coaching digest to Slack (Coaching Agent app)", "~6pm ET weekdays", ""),
 "bluon-sales-meeting-sync/sync.yml": ("Sales standup mirror", "Mirrors the 10am sales standup note (summary, action items, transcript) into the shared Internal Sales Meetings DB", "10:30a–12:30p ET sweep, Mon–Sat", ""),
 "bluon-email-machine/rolling-drafts.yml": ("Email drafts (rolling)", "Drafts segment emails on the rolling schedule — PAUSED while the email machine is shelved", "paused", ""),
 "bluon-email-machine/to-hubspot.yml": ("Email → HubSpot", "Pushes approved email drafts into HubSpot — PAUSED", "paused", ""),
 "bluon-email-machine/approval-notify.yml": ("Email approval ping", "Slack ping when a draft awaits approval — PAUSED", "paused", ""),
 "bluon-email-machine/reporting.yml": ("Email reporting", "Rebuilds the Email Reporting page — PAUSED", "paused", "https://www.notion.so/38e576a5c12d81879c21f82642db1fa1"),
 "bluon-email-machine/regen-mockup.yml": ("Email mockup regen", "Regenerates an email mockup on request — PAUSED", "paused", ""),
 "bluon-email-machine/weekly-drafts.yml": ("Email weekly drafts", "Superseded weekly draft batch — manual only", "manual", ""),
 "bluon-automations-hub/health.yml": ("Automations health sync", "This page — checks every automation's latest run and updates these rows", "Daily ~7:30am ET", ""),
}

now = datetime.now(timezone.utc)

def status_of(wf_state, run):
    if wf_state != "active": return "⏸ Paused"
    if not run: return "💤 Dormant"
    started = datetime.strptime(run["run_started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if (now - started).days > 30: return "💤 Dormant"
    if run.get("conclusion") == "success": return "🟢 Healthy"
    if run.get("status") in ("in_progress", "queued") : return "🟢 Healthy"  # currently running
    return "🔴 Failing"

# existing rows keyed by title
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

count = 0
for repo, system in REPOS.items():
    wfs = gh(f"/repos/Nadreau/{repo}/actions/workflows").get("workflows", [])
    for wf in wfs:
        fname = wf["path"].split("/")[-1]
        if fname in SKIP_FILES: continue
        key = f"{repo}/{fname}"
        friendly, desc, sched, report = CATALOG.get(key, (wf["name"], "", "", ""))
        runs = gh(f"/repos/Nadreau/{repo}/actions/workflows/{wf['id']}/runs?per_page=1&exclude_pull_requests=true").get("workflow_runs", [])
        run = runs[0] if runs else None
        st = status_of(wf["state"], run)
        props = {
            "Automation": {"title": T(friendly)},
            "System": {"select": {"name": system}},
            "What it does": {"rich_text": T(desc)},
            "Schedule": {"rich_text": T(sched)},
            "Status": {"select": {"name": st}},
            "Last result": {"select": {"name": (run.get("conclusion") or "—") if run else "—"}},
            "Run log": {"url": run["html_url"] if run else wf["html_url"]},
        }
        if report: props["Report page"] = {"url": report}
        if run: props["Last run"] = {"date": {"start": run["run_started_at"]}}
        if friendly in existing:
            nt("PATCH", f"pages/{existing[friendly]}", {"properties": props})
        else:
            nt("POST", "pages", {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": props})
        count += 1
        print(f"  {st}  {system:<20} {friendly}")
        time.sleep(0.3)
print(f"synced {count} automations")
