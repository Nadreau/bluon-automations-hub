# bluon-automations-hub

Keeps the **Automations Hub** page in the Bluon Notion current: for every GitHub-Actions
automation (ads reporting, account intelligence, sales coaching, meeting sync, email machine),
it reads the latest run + enabled state and updates a status row —
🟢 healthy · 🔴 failing · ⏸ paused · 💤 dormant.

Runs daily via `health.yml`. No data leaves the accounts involved: it reads run *metadata*
(status, timestamps) from the GitHub API and writes to Notion. Secrets: `NOTION_KEY`,
`HEALTH_GH_TOKEN` (repo-scope, read-only use).
