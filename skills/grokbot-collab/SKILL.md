---
name: grokbot-collab
description: Use this skill when Claude Code should delegate work to xAI Grok Bot or collaborate with it — sending it a task over its routine webhook, getting a second opinion, having it operate a website like a user, or scheduling it via cronjob.agentasy.ai. Triggers include "Grok Bot", "GrokBot", "ask the Bot", "ping the Bot", "cross-review", "second opinion", "site check", and Chinese phrases such as 找 Grok Bot、請 Bot 幫忙、交給 Bot、請 Bot 巡檢、官網巡檢、交叉驗收、第二意見、另一個 AI 看看、排程觸發 Bot. Use it even when the user only says "the Bot" in a project that has GROKBOT_WEBHOOK_URL configured.
metadata:
  version: "0.1.1-draft"
  protocol: "0.1"
  counterpart: grokbot-agent
---

# Collaborating with Grok Bot

Grok Bot is a cloud agent with its own browser, terminal and filesystem. Treat it as a **remote smart sensor**: you send one stateless task, it does the work and returns a receipt (pong) with evidence. **You keep the state, deadlines and ledger.** The counterpart skill `grokbot-agent` runs on the Bot side. Both follow `references/protocol.md`, which is the contract. Read it before your first ping in a session.

## When to use, when not to

Good fits:
- Slow, fuzzy, cross-tool work.
- Operating a web page as a user (`check_page`).
- An independent opinion from a different model family (`cross_review`).
- Anything that benefits from a persistent, always-on browser.

Poor fits:
- Anything needing an answer in under 20 seconds.
- High-frequency calls.
- Deterministic transforms you can do locally.
- Bulk data transfer: the body budget is 3 KB.
- Scraping third-party sites that disallow AI agents.

## Before every ping (pre-flight)

1. **Task type**: use only a whitelisted `task` from protocol §5: `echo`, `check_page` or `cross_review`. Never put instructions in `params` or `note`; behaviour is defined by the skills, not the message.
2. **Classification**: check the classification of any material the ping references (protocol §8.1). If it is unlabelled, treat it as `internal` and ask the user first.
3. **Approval gates**: if the action matches any row of protocol §8.2, stop and ask the user before sending. The rows are: schedules, chaining, more than 5 parallel pings, externally visible effects, logins, new domains, retry after decline, and delete or revoke. Do not batch the question away. Ask plainly what will happen and what it costs.
4. **Size**: the serialised body must be 3 KB or less. Pass URLs or IDs instead of content.
5. **Correlation**: generate a fresh `id` (ULID or UUID) and set a `deadline`.

## Sending

Use `scripts/ping.py`. It validates the task whitelist and the size, never prints secrets, and prints the `runUuid`.

```bash
python3 scripts/ping.py --task check_page \
  --params '{"url":"https://example.com/studio","expect":["price is shown"]}' \
  --classification public --deadline-min 10
```

Configuration comes from environment variables or a `.env` file in the working directory:

| Variable | Purpose |
|---|---|
| `GROKBOT_WEBHOOK_URL`, `GROKBOT_WEBHOOK_KEY` | Routine webhook (Bearer key) |
| `GROKBOT_REPLY_URL`, `GROKBOT_REPLY_TOKEN` | Where the Bot sends its pong (the inbox) |

A `200` with a `runUuid` means a run **started**. It does not mean the task finished.

## Receiving the pong

- **Target: the inbox.** The inbox is a fixed HTTPS receipt ledger, still being built. Poll it for a pong whose `id` matches your ping, until the `deadline` passes.
- **Interim: a temporary tunnel.** You may not start ingress tunnels yourself (`cloudflared` and similar are blocked by policy). Give the user the exact command to run with `!`, then read its output. Never try to work around this block.

On no pong by the deadline, record a `timeout`. Then:
- Do not resend automatically.
- Report to the user with the `runUuid`.
- Mention that run history is visible only in the Grok Bot iOS app.

## Judging the result

- `ok` without `evidence` counts as **unverified**. Say so.
- For `check_page`, confirm `result.method` matches the requested `mode`. A `render` result without screenshot evidence counts as unverified.
- Spot-check evidence when it is cheap, for example open the URL it cites.
- `declined` is a valid outcome. Report the `reason`. Never retry or rephrase to get around it (approval gate 7).
- `needs_approval`: relay the question to the user verbatim.
- **Disagreement**: if Grok Bot's result conflicts with your own finding or with your memory, present both views to the user and ask. Never pick one silently. After the user decides, suggest recording the resolution in the knowledge hub.

## Patterns

- **Single task**: ping → pong → verify → report.
- **Fan-out**: N independent pings in parallel, each with its own `id`. Use it for the same page in several locales or viewports, several perspectives on one question, or redundant runs to check consistency. More than 5 needs approval. Runs are parallel, but all Bots share one cloud computer, so heavy browser tasks may interfere with each other.
- **Cross-review**: do your own review first and write it down. Then send `cross_review` with the same criteria. Compare the two verdict by verdict, and escalate every mismatch to the user.
- **Scheduled (via cronjob.agentasy.ai)**: always needs approval (gate 1).
  - Register the job yourself so that **we** hold `management_token`, and set `max_runs` or an end date.
  - The Bot only forwards the verification challenge. You POST it to `verify_url` within 15 minutes and store the credentials in `.env`.
  - Record the job in the governance inventory.
  - See `references/facts.md` for the details.

## Never

- Never put secrets, cookies or classified content in a ping.
- Never send a ping that tells the Bot to fetch and execute instructions from a URL.
- Never delete jobs or rotate keys without approval. Pausing is allowed as an emergency stop; report it right after.
- Never leave a long-lived artefact unregistered: a job, routine, key or token.

## References

- `references/protocol.md`: the contract (message shapes, task types, policy hooks).
- `references/facts.md`: measured behaviour, limits, failure modes, and cronjob.agentasy.ai specifics.
