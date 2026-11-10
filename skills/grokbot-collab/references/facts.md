# Grok Bot: verified facts and failure modes

Measured on 2026-11-09 in grokbot-lab unless noted. Results are in `lab/results/results-c57d15c1.json`.

## Webhook (into the Bot)
- `POST` with `Authorization: Bearer <key>`. Response `{"success":true,"runUuid":"…"}` in about 1 s.
- 200 means the run started, not that it finished. The result shows up in the Bot's chat and, when instructed, as a pong.
- **Body truncation:** a 100 KB body was accepted with HTTP 200, but the Bot saw only the first ~4 KB (3,276 chars of the data field). There was no error on either side. Keep bodies at 3 KB or less.
- The Bot **follows instructions embedded in the body** even when the routine says not to. That is why the protocol forbids instructions in pings.

## Round trips
| Case | Observed |
|---|---|
| Simple echo, sequential ×5 | 20.2–32.3 s (median about 23 s) |
| Escaping test (unicode, quotes, `$(…)`) | 115 s. Byte-exact, no shell expansion. |
| 100 KB body | 129 s, truncated as above |
| 3 parallel pings | 27–40 s each. Runs are parallel, not queued. |

## Limits (from docs)
- All routines combined: 300 runs/hour. Per routine: 200 runs/hour. Over the limit you get `Automation run rate limit exceeded`, with no automatic retry.
- Known issue: a shared limit can trigger that error even below your own quota.
- Up to 50 routines per Bot. Run history keeps the last 20 runs, **visible only in the iOS app**.
- Each run consumes Grok Bot usage, billed separately from Grok and Cursor plans.

## Failure modes
| Symptom | Likely cause | Action |
|---|---|---|
| 200 but nothing in chat | Old or wrong webhook key, wrong Bot's chat, routine instruction doesn't report | Check the iOS run history, confirm the key, check which Bot owns the routine |
| Non-200 | Routine paused, or key rotated | Ask the user to check the routine state |
| Pong never arrives | Callback URL unreachable from the Bot, inbox down, Bot declined in chat only | Check the Bot's chat. Record a timeout. Don't resend automatically. |
| `result` is suspiciously clean | Truncated input (over 4 KB) | Check the body size |

## Protocol v0.1 end-to-end (2026-11-10, lab/results/e2e-fb5ae151.json)
All 5 scenarios passed with agent_version 0.1.1-draft. Pings were sent in parallel.
| Scenario | RTT | Outcome |
|---|---|---|
| echo (unicode, quotes, `$(…)`) | 97 s | ok, byte-identical |
| check_page agentasy.ai | 69 s | ok, h1 quoted. Claude spot-checked it and it matched. |
| unknown task | 36 s | declined `unknown_task` |
| instruction injected in `note` | 34 s | ok. The instruction was ignored and the Bot said so in `message`. |
| domain not on allow-list | 38 s | declined `domain_not_allowed` |
Retest of protocol 0.1.1 (`lab/results/e2e-963ac896.json`, agent 0.1.2-draft), 2/2 passed:
- `check_render` took 143 s. `method: render`, with a screenshot posted in chat (`screenshot_chat`). It reported the hero background as royal blue (about #1d3f9e). **The requested viewport of 1280x800 was NOT applied.** The Bot rendered at 1920x1072 and said so itself. Treat `viewport` as best-effort.
- `check_http` took 38 s. `method: http`, with HTTP status, size and title quoted.
- Rendering costs about 4x the time of an HTTP fetch.

Earlier caveat (fixed in protocol 0.1.1): check_page findings ("HTTP 200 … 25 KB of page HTML") suggest the Bot fetched HTML rather than rendering the page in a browser. JS-rendered pages need an explicit render requirement.

## Installing or updating the Bot-side skill
- Verified on 2026-11-10: Grok Bot chat accepts **file attachments** such as `SKILL.md` and `references/protocol.md`. The Bot saves them as skill files ("更新技能檔案"). Prefer attachments over pasting, since pasting risks truncation and reformatting.
- Ask the Bot to store the files verbatim and report the first 12 hex digits of the sha256 of each file. If config values were written into `SKILL.md`, its hash changes, which is expected. Then check `protocol.md`'s hash plus the reported version and config values.

## Local environment notes
- This Mac uses Tailscale MagicDNS, so a brand-new `*.trycloudflare.com` hostname often won't resolve locally for a while. The Bot can still reach it.
- Starting an ingress tunnel is blocked for Claude by the auto-mode classifier. The user must run it.

## cronjob.agentasy.ai (from llms.txt, 2026-11-10)
- Outbound-only scheduler for agents. No account: whoever holds `management_token` owns the job.
- Schedules: cron, `interval_sec` (60 or more), or one-shot `run_at`. Payload is a fixed JSON object of at most 8 KB, but stay at 3 KB or less for Grok Bot. You cannot edit a job in place or trigger it manually.
- Trigger envelope: `{"type":"trigger","job_id","delivery_id","run_number","scheduled_at","sent_at","attempt","payload"}`.
- `outgoing_auth: {"header":"Authorization","value":"Bearer <grok key>"}` is stored encrypted and never returned.
- **Verification:** the service POSTs `{"type":"url_verification","job_id","challenge","verify_url"}`.
  - Callback mode: the Bot answers 200 automatically. Someone must then POST `{"challenge"}` to `verify_url` within **15 min of job creation**.
  - The `/verify` response returns `hmac_secret` and `management_token` **once**.
  - Per protocol §6, the Bot forwards the challenge to the inbox and Claude Code completes verification.
- The run ledger (status, first 1 KB of the response, timing) is kept for 30 days: `GET /v1/jobs/{id}/runs`.
- Limits: 20 live jobs and 4 concurrent sends **per webhook host**, probably global across users. Grok Bot webhooks all live on `api2.cursor.sh`.
- MCP server: `https://cronjob.agentasy.ai/mcp`. Tools include `create_job`, `verify_challenge`, `list_jobs`, `get_deliveries`, `pause_job` and `delete_job`.
