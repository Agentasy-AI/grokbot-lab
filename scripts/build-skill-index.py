#!/usr/bin/env python3
"""Build the well-known skill discovery bundle for agentasy.ai.

Output (deploy the contents of dist/ to the site root):
  dist/.well-known/agent-skills/index.json
  dist/.well-known/agent-skills/<name>.tar.gz   (reproducible: sorted, fixed mtime, no owner, gzip without a timestamp)

Format follows the draft "Agent Skills Discovery via Well-Known URIs" v0.2.0
(https://github.com/cloudflare/agent-skills-discovery-rfc). Re-check that schema before the first publish.

  python3 scripts/build-skill-index.py [--base-url https://agentasy.ai/.well-known/agent-skills/]
"""
import argparse, gzip, hashlib, io, json, re, subprocess, sys, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "https://schemas.agentskills.io/discovery/0.2.0/schema.json"
FIXED_MTIME = 1_700_000_000  # constant, for reproducible archives


def frontmatter(skill):
    text = (skill / "SKILL.md").read_text()
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
    get = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [None, None])[1]
    ver = re.search(r'^\s+version:\s*"?([^"\n]+)"?', fm, re.M)
    return get("name").strip(), get("description").strip(), ver.group(1) if ver else None


def archive(skill):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(p for p in skill.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            rel = f"{skill.name}/{f.relative_to(skill).as_posix()}"
            data = f.read_bytes()
            ti = tarfile.TarInfo(rel)
            ti.size, ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = len(data), FIXED_MTIME, 0, 0, "", ""
            ti.mode = 0o755 if f.stat().st_mode & 0o111 else 0o644
            tar.addfile(ti, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://agentasy.ai/.well-known/agent-skills/")
    a = ap.parse_args()
    if subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sync-protocol.py"), "--check"],
                      capture_output=True).returncode:
        sys.exit("protocol copies out of sync or lint failed; run scripts/sync-protocol.py first")
    out_dir = ROOT / "dist" / ".well-known" / "agent-skills"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for skill in sorted(p for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").exists()):
        name, desc, ver = frontmatter(skill)
        blob = archive(skill)
        (out_dir / f"{name}.tar.gz").write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        entries.append({"name": name, "type": "archive", "description": desc,
                        "url": f"{a.base_url}{name}.tar.gz", "digest": f"sha256:{digest}"})
        print(f"{name:<16} v{ver:<14} {len(blob):>6} B  sha256:{digest[:12]}")
    (out_dir / "index.json").write_text(json.dumps({"$schema": SCHEMA, "skills": entries}, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out_dir.relative_to(ROOT)}/index.json")


if __name__ == "__main__":
    main()
