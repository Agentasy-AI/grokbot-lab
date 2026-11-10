# grokbot-lab

Two [Agent Skills](https://agentskills.io) that let **Claude Code** and **xAI Grok Bot** collaborate through a small, tested protocol:

| Skill | Runs on | Role |
|---|---|---|
| [`grokbot-collab`](skills/grokbot-collab/SKILL.md) | Claude Code | Requester. It sends a ping (one whitelisted task), owns state and deadlines, and verifies the pong. |
| [`grokbot-agent`](skills/grokbot-agent/SKILL.md) | Grok Bot | Executor, acting as a remote sensor. It does one task per run and returns a pong with evidence. |

Both follow one contract: [`protocol/protocol.md`](protocol/protocol.md) (v0.1.1-draft). Each skill carries an identical copy, which `scripts/sync-protocol.py` keeps in step.

```
Claude Code / cronjob.agentasy.ai ──ping──▶ Grok Bot routine webhook
            ▲                                   │ one stateless task
            └──────────── pong (+evidence) ◀────┘
```

Status: **draft**. End-to-end tested against a real Grok Bot (7/7 scenarios, see [`lab/results/`](lab/results)).

## Key design points
- **Pings carry data, not instructions.** Behaviour is defined in the skills. In testing, instructions injected into a webhook body were ignored and the Bot reported them.
- **Evidence or it didn't happen.** An `ok` without evidence is treated as unverified.
- **Declines are valid outcomes.** The Bot never works around sites that disallow agents.
- **Human approval gates.** Schedules, chaining, more than 5 parallel pings, external effects, logins, new domains, retries after a decline, and deletions all need approval (protocol §8.2).
- **Bodies of 3 KB or less.** Grok Bot silently truncates webhook bodies at about 4 KB.

## Install

**Claude Code** (only `grokbot-collab` is installed):
```
/plugin marketplace add Agentasy-AI/grokbot-lab
/plugin install grokbot-collab@grokbot-lab
```

**Other agents** (Agent Skills CLI):
```
npx skills add Agentasy-AI/grokbot-lab --skill grokbot-collab
```

**Grok Bot.** Attach `skills/grokbot-agent/SKILL.md` and `skills/grokbot-agent/references/protocol.md` in the Bot's chat and ask it to save them verbatim as the `grokbot-agent` skill. Then fill in the configuration table. Ask it to report the sha256 of `protocol.md` and compare it with this repo. A well-known discovery index will be published at `https://agentasy.ai/.well-known/agent-skills/index.json`. Build it with `scripts/build-skill-index.py`.

Configure the Claude side with a `.env` file. See [`.env.example`](.env.example).

## Layout
```
protocol/protocol.md          single source of the contract
skills/grokbot-collab/        Claude Code skill (SKILL.md, references/, scripts/ping.py)
skills/grokbot-agent/         Grok Bot skill (SKILL.md, references/)
scripts/sync-protocol.py      copy the protocol into the skills and lint frontmatter (--check for CI)
scripts/build-skill-index.py  reproducible .well-known/agent-skills bundle into dist/
lab/                          experiments: webhook ping-pong, load tests, end-to-end tests and their results
BACKLOG.md                    decisions and open verification items (Traditional Chinese)
```

## License
MIT
