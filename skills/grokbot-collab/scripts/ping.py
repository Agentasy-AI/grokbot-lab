#!/usr/bin/env python3
"""Send one protocol-compliant ping to a Grok Bot routine webhook.

  python3 ping.py --task echo --params '{"text":"hello"}' --classification public
  python3 ping.py --task check_page --params '{"url":"https://…","expect":["…"]}' \
                  --classification public --deadline-min 10 [--note "…"] [--dry-run]

Reads GROKBOT_WEBHOOK_URL, GROKBOT_WEBHOOK_KEY, GROKBOT_REPLY_URL, GROKBOT_REPLY_TOKEN
from the environment or ./.env. Never prints secrets. Prints one JSON line:
{"id", "task", "http", "runUuid", "body_bytes", "deadline"}.
Stdlib only.
"""
import argparse, json, os, sys, urllib.error, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROTOCOL_V = "0.1"
TASKS = {"echo", "check_page", "cross_review"}
MAX_BODY = 3000  # bytes; Grok Bot silently truncates around 4 KB
REQUIRED_PARAMS = {"echo": {"text"}, "check_page": {"url", "expect"}, "cross_review": {"doc_url", "criteria"}}


def env():
    vals = {}
    p = Path.cwd() / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    vals.update({k: v for k, v in os.environ.items() if k.startswith("GROKBOT_")})
    missing = [k for k in ("GROKBOT_WEBHOOK_URL", "GROKBOT_WEBHOOK_KEY", "GROKBOT_REPLY_URL", "GROKBOT_REPLY_TOKEN")
               if not vals.get(k)]
    if missing:
        sys.exit(f"missing config: {', '.join(missing)}")
    return vals


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=sorted(TASKS))
    ap.add_argument("--params", required=True, help="JSON object")
    ap.add_argument("--classification", required=True)
    ap.add_argument("--deadline-min", type=int, default=10)
    ap.add_argument("--note")
    ap.add_argument("--source", default="claude-code")
    ap.add_argument("--dry-run", action="store_true", help="validate and print the body (token masked), don't send")
    a = ap.parse_args()

    params = json.loads(a.params)
    if not isinstance(params, dict):
        sys.exit("--params must be a JSON object")
    if miss := REQUIRED_PARAMS[a.task] - params.keys():
        sys.exit(f"{a.task} needs params: {sorted(miss)}")

    cfg = env()
    now = datetime.now(timezone.utc)
    body = {
        "type": "ping", "v": PROTOCOL_V, "id": str(uuid.uuid4()), "source": a.source,
        "task": a.task, "params": params, "classification": a.classification,
        "reply": {"url": cfg["GROKBOT_REPLY_URL"], "token": cfg["GROKBOT_REPLY_TOKEN"]},
        "deadline": iso(now + timedelta(minutes=a.deadline_min)), "sent_at": iso(now),
    }
    if a.note:
        body["note"] = a.note
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    if len(data) > MAX_BODY:
        sys.exit(f"body is {len(data)} bytes (> {MAX_BODY}); pass URLs/IDs instead of content")

    if a.dry_run:
        shown = json.loads(data); shown["reply"]["token"] = "***"
        print(json.dumps(shown, ensure_ascii=False, indent=2)); print(f"body_bytes={len(data)}")
        return

    req = urllib.request.Request(cfg["GROKBOT_WEBHOOK_URL"], data=data, method="POST", headers={
        "Authorization": f"Bearer {cfg['GROKBOT_WEBHOOK_KEY']}", "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        resp = json.loads(raw or b"{}")
    except ValueError:
        resp = {}
    print(json.dumps({"id": body["id"], "task": a.task, "http": status, "runUuid": resp.get("runUuid"),
                      "body_bytes": len(data), "deadline": body["deadline"]}))
    sys.exit(0 if status == 200 else 1)


if __name__ == "__main__":
    main()
