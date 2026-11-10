#!/usr/bin/env python3
"""Ping-pong test with a Grok Bot.

1. Start a local receiver on 127.0.0.1 (a free port unless --port is given).
2. Expose it with a Cloudflare quick tunnel (https://*.trycloudflare.com), with no account needed.
3. POST a ping to the Grok Bot routine webhook. The body carries a reply URL and a one-time token.
4. The Bot POSTs a pong back to the reply URL. Then we send the next ping, up to --rounds times.

Every exchange is appended to pingpong.log.jsonl. Secrets are never printed.
Stdlib only. Usage: python3 pingpong.py  (default suite: 5 sequential, escape, large, 3-burst = 10 pings)
"""
import argparse, json, os, re, secrets, subprocess, sys, threading, time, urllib.error, urllib.request, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repo root, where .env lives
RESULTS = HERE / "results"
LOG = HERE / "pingpong.log.jsonl"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(event, **kw):
    rec = {"t": now(), "event": event, **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{datetime.now():%H:%M:%S}] {event} " + json.dumps(kw, ensure_ascii=False))


class State:
    token = secrets.token_urlsafe(24)
    pongs = {}          # seq -> payload
    arrival = {}        # seq -> epoch seconds
    cond = threading.Condition()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/pong":
            return self._send(404, {"error": "not found"})
        if self.headers.get("Authorization", "") != f"Bearer {State.token}":
            log("pong_rejected", reason="bad token", ua=self.headers.get("User-Agent"))
            return self._send(401, {"error": "unauthorized"})
        n = min(int(self.headers.get("Content-Length") or 0), 64_000)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_raw": raw}
        seq = payload.get("seq") if isinstance(payload, dict) else None
        log("pong_received", seq=seq, payload=payload, ua=self.headers.get("User-Agent"))
        with State.cond:
            State.pongs[seq] = payload
            State.arrival[seq] = time.time()
            State.cond.notify_all()
        self._send(200, {"ok": True, "received_seq": seq})

    def log_message(self, *a):
        pass  # keep stdout clean


def start_tunnel(port):
    exe = os.environ.get("CLOUDFLARED", "cloudflared")
    p = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Copy all cloudflared output to cloudflared.log so tunnel problems can be diagnosed.
    url, registered = None, threading.Event()
    found = threading.Event()

    def pump():
        nonlocal url
        with (HERE / "cloudflared.log").open("w") as f:
            for line in p.stdout:
                f.write(line); f.flush()
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and not url:
                    url = m.group(0); found.set()
                if "Registered tunnel connection" in line:
                    registered.set()

    threading.Thread(target=pump, daemon=True).start()
    if not found.wait(45):
        p.kill()
        sys.exit("cloudflared did not report a public URL (see cloudflared.log)")
    if not registered.wait(45):
        log("tunnel_warning", reason="no 'Registered tunnel connection' within 45s (see cloudflared.log)")
    else:
        log("tunnel_registered")
    return p, url


def wait_public(url, timeout=30):
    """Best-effort check from this Mac. A failure is often local DNS negative caching
    of the brand-new hostname, which does not affect the Bot's cloud computer."""
    end, last = time.time() + timeout, None
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "/health", timeout=5) as r:
                if r.status == 200:
                    return None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2)
    return last or "timeout"


SPECIAL = ('zh:中文測試 emoji:🏓 quotes:"double" \'single\' backslash:\\ '
           'newline:\n tab:\t dollar:$(echo INJECTED) backtick:`echo INJECTED` meta:&;|<tag>')


def make_data(n):
    s = "".join(f"{i:07d}|" for i in range(n // 8 + 1))
    return s[:n]


def send_ping(env, public_url, run_id, seq, phase, message, reply_extra=None, extra=None):
    """POST one ping. Returns (http_status, response_dict, webhook_ms, t_sent)."""
    body = {
        "type": "ping", "run_id": run_id, "seq": seq, "phase": phase, "sent_at": now(),
        "message": message,
        "reply": {
            "method": "POST",
            "url": f"{public_url}/pong",
            "headers": {"Authorization": f"Bearer {State.token}", "Content-Type": "application/json"},
            "body": {"type": "pong", "run_id": run_id, "seq": seq, "phase": phase,
                     "message": "<one short sentence from the Bot>", **(reply_extra or {})},
        },
        **(extra or {}),
    }
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        env["GROKBOT_WEBHOOK_URL"], data=data, method="POST",
        headers={"Authorization": f"Bearer {env['GROKBOT_WEBHOOK_KEY']}",
                 "Content-Type": "application/json; charset=utf-8"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    ms = round((time.time() - t0) * 1000)
    try:
        resp = json.loads(raw or b"{}")
    except ValueError:
        resp = {"_raw": raw[:500].decode("utf-8", "replace")}
    log("ping_sent", seq=seq, phase=phase, http=status, webhook_ms=ms,
        body_bytes=len(data), response=resp)
    return status, resp, ms, t0


def wait_pongs(seqs, timeout):
    with State.cond:
        State.cond.wait_for(lambda: all(s in State.pongs for s in seqs), timeout=timeout)
        return {s: State.pongs.get(s) for s in seqs}


def run_suite(env, public_url, run_id, a):
    results, seq = [], 0

    def one(phase, message, reply_extra=None, extra=None, check=None):
        nonlocal seq
        seq += 1
        status, resp, ms, t0 = send_ping(env, public_url, run_id, seq, phase, message, reply_extra, extra)
        rec = {"seq": seq, "phase": phase, "http": status, "webhook_ms": ms, "runUuid": resp.get("runUuid")}
        if status == 200:
            pong = wait_pongs([seq], a.timeout)[seq]
            rec["rtt_s"] = round(State.arrival[seq] - t0, 1) if pong else None
            rec["pong"] = pong
            if pong and check:
                rec["checks"] = check(pong)
        else:
            rec["error"] = resp
        log("result", **{k: v for k, v in rec.items() if k != "pong"})
        results.append(rec)
        return rec

    phases = a.phases.split(",")

    # 1. Sequential rounds: latency and stability
    if "seq" in phases:
        for i in range(1, a.seq_rounds + 1):
            r = one("seq", f"ping {i}/{a.seq_rounds} (sequential latency test). Reply as described in `reply`.")
            if r.get("rtt_s") is None:
                log("abort", reason="sequential round got no pong; stopping suite")
                return results

    # 2a. Escaping: special chars must come back byte-identical inside reply.body
    if "escape" in phases:
        def chk(p):
            got = p.get("echo_check")
            return {"echo_exact": got == SPECIAL,
                    "shell_expanded": isinstance(got, str) and "INJECTED" in got and "echo INJECTED" not in got,
                    "got": got}
        one("escape", "Escaping test: send `reply.body` exactly as given. Do not modify `echo_check`; "
                      "only fill in `message`.", reply_extra={"echo_check": SPECIAL}, check=chk)

    # 2b. Large body: can the Bot read a big field?
    if "large" in phases:
        n = a.large_kb * 1000
        blob = make_data(n)
        def chk(p, n=n, blob=blob):
            return {"expected_length": n, "got_length": p.get("data_length"),
                    "expected_tail": blob[-16:], "got_tail": p.get("data_tail")}
        one("large", f"Large-body test: the `data` field is {a.large_kb} KB. In reply.body, replace "
                     "`data_length` with the number of characters in `data` (an integer) and `data_tail` "
                     "with its last 16 characters. Use your computer to count; do not guess.",
            reply_extra={"data_length": "<integer>", "data_tail": "<last 16 chars of data>"},
            extra={"data": blob},
            check=chk)

    # 2c. Burst: N pings at once
    if "burst" in phases and a.burst > 0:
        seqs = list(range(seq + 1, seq + a.burst + 1))
        seq += a.burst
        sent = {}
        def fire(s):
            sent[s] = send_ping(env, public_url, run_id, s, "burst",
                                f"burst ping {s - seqs[0] + 1}/{a.burst} (concurrency test). Reply as described in `reply`.")
        ts = [threading.Thread(target=fire, args=(s,)) for s in seqs]
        [t.start() for t in ts]; [t.join() for t in ts]
        ok = [s for s in seqs if sent[s][0] == 200]
        pongs = wait_pongs(ok, a.timeout)
        for s in seqs:
            status, resp, ms, t0 = sent[s]
            pong = pongs.get(s)
            arrived = State.arrival.get(s)
            rec = {"seq": s, "phase": "burst", "http": status, "webhook_ms": ms, "runUuid": resp.get("runUuid"),
                   "rtt_s": round(arrived - t0, 1) if pong and arrived else None, "pong": pong}
            if status != 200:
                rec["error"] = resp
            log("result", **{k: v for k, v in rec.items() if k != "pong"})
            results.append(rec)
    return results


def summarize(results, run_id):
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"results-{run_id}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("\n=== summary ===")
    print(f"{'seq':>3}  {'phase':<7} {'http':>4} {'webhook':>8} {'rtt':>7}  checks")
    for r in results:
        rtt = f"{r['rtt_s']}s" if r.get("rtt_s") is not None else "NO PONG"
        c = r.get("checks") or r.get("error") or ""
        if isinstance(c, dict):
            c = json.dumps({k: v for k, v in c.items() if k != "got"}, ensure_ascii=False)
        print(f"{r['seq']:>3}  {r['phase']:<7} {r['http']:>4} {r['webhook_ms']:>6}ms {rtt:>7}  {c}")
    rtts = [r["rtt_s"] for r in results if r.get("rtt_s") is not None]
    if rtts:
        print(f"\npongs {len(rtts)}/{len(results)}  rtt min {min(rtts)}s  max {max(rtts)}s  "
              f"avg {round(sum(rtts) / len(rtts), 1)}s")
    print(f"details: {out.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phases", default="seq,escape,large,burst")
    ap.add_argument("--seq-rounds", type=int, default=5)
    ap.add_argument("--burst", type=int, default=3)
    ap.add_argument("--large-kb", type=int, default=100)
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--timeout", type=int, default=240, help="seconds to wait for each pong")
    a = ap.parse_args()
    planned = (a.seq_rounds if "seq" in a.phases else 0) + ("escape" in a.phases) \
        + ("large" in a.phases) + (a.burst if "burst" in a.phases else 0)
    if planned > 15:
        sys.exit(f"{planned} pings planned; cap is 15 (each ping costs Grok Bot usage)")

    env = load_env()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tunnel, public_url = start_tunnel(port)
    run_id = uuid.uuid4().hex[:8]
    results = []
    try:
        log("tunnel_up", url=public_url, run_id=run_id, planned_pings=planned)
        time.sleep(3)  # let the tunnel settle; local DNS check skipped (new hostnames don't resolve via MagicDNS)
        results = run_suite(env, public_url, run_id, a)
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        tunnel.terminate()
        srv.shutdown()
        log("done", run_id=run_id)
        if results:
            summarize(results, run_id)


if __name__ == "__main__":
    main()
