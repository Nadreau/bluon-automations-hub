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
 "bluon-email-machine/rolling-drafts.yml": ("Email drafts (rolling)", "Drafts segment emails on the rolling schedule", "paused", ""),
 "bluon-email-machine/to-hubspot.yml": ("Email → HubSpot", "Pushes approved email drafts into HubSpot", "paused", ""),
 "bluon-email-machine/approval-notify.yml": ("Email approval ping", "Slack ping when a draft awaits approval", "paused", ""),
 "bluon-email-machine/reporting.yml": ("Email reporting", "Rebuilds the Email Reporting page", "paused", "https://www.notion.so/38e576a5c12d81879c21f82642db1fa1"),
 "bluon-email-machine/regen-mockup.yml": ("Email mockup regen", "Regenerates an email mockup on request", "paused", ""),
 "bluon-email-machine/weekly-drafts.yml": ("Email weekly drafts", "Superseded weekly draft batch — manual only", "manual", ""),
 "bluon-automations-hub/health.yml": ("Automations health sync", "This page — checks every automation's minutes, latest run and health, and rewrites this story", "3×/day", ""),
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
        friendly, desc, sched, report = CATALOG.get(f"{repo}/{fname}", (wf["name"], "", "", ""))
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
        rows.append(dict(repo=repo, system=system, file=fname, friendly=friendly, desc=desc,
                         sched=sched, report=report, public=public, status=st, why=why,
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

blocks = [{"type": "heading_1", "heading_1": {"rich_text": T("Systems — Ranked by Minutes Burned")}}]
for s in sys_order:
    items = sorted(by_sys[s], key=lambda x: -x["mins"])
    smin = sum(x["mins"] for x in items)
    icons = "".join(x["status"][0] for x in items)   # e.g. 🔴🔴🟢⏸
    if all(x["repo"] in runner_state for x in items):
        vis = "🖥 Niko's Mac — free"
    elif all(x["public"] for x in items):
        vis = "🌐 public cloud — free"
    else:
        vis = "☁️ cloud — metered" if all(not x["public"] for x in items) else "mixed"
    blocks.append({"type": "divider", "divider": {}})
    blocks.append({"type": "heading_1", "heading_1": {"rich_text": T(f"{s}    {smin:,} min · {len(items)} agents · {vis}")}})
    all_paused = all(x["status"].startswith("⏸") for x in items)
    if all_paused:
        blocks.append({"type": "callout", "callout": {"rich_text": T(
            f"⏸ ENTIRE SYSTEM PAUSED   ·   {smin:,} min this month   ·   {items[0]['why']}"),
            "icon": {"emoji": "📊"}, "color": "gray_background"}})
        continue
    for x in items:
        where = ("🖥 Niko's Mac (free)" if x["repo"] in runner_state
                 else ("🌐 GitHub cloud (free — public)" if x["public"] else "☁️ GitHub cloud (metered — private)"))
        line1 = (f"{x['status'].upper()}   ·   {x['mins']:,} min this month   ·   runs on {where}   ·   "
                 f"{x['sched'] or 'manual'}   ·   last run {_fmt_last(x['run'])}")
        line2 = f"\n💬 {x['why']}" if not x["status"].startswith("🟢") else ""
        line3 = f"\n⚙️ {x['desc']}" if x["desc"] else ""
        blocks.append({"type": "heading_3", "heading_3": {"rich_text": T(x["friendly"])}})
        blocks.append({"type": "callout", "callout": {"rich_text": T(line1 + line2 + line3),
            "icon": {"emoji": "📊"}, "color": "gray_background"}})

blocks.append({"type": "divider", "divider": {}})
blocks.append({"type": "heading_1", "heading_1": {"rich_text": T("Full Detail — every automation, click through to logs & report pages")}})

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
