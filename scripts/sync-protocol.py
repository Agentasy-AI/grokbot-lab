#!/usr/bin/env python3
"""Keep skills/*/references/protocol.md identical to protocol/protocol.md, and lint SKILL.md frontmatter.

  python3 scripts/sync-protocol.py          # copy, then check
  python3 scripts/sync-protocol.py --check  # check only (exit 1 on drift or lint error), for CI
"""
import hashlib, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "protocol" / "protocol.md"
SKILLS = sorted(p for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").exists())
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def lint(skill):
    errs = []
    text = (skill / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return [f"{skill.name}: missing frontmatter"]
    fm = m.group(1)
    top = {l.split(":", 1)[0] for l in fm.splitlines() if l and not l.startswith(" ") and ":" in l}
    if extra := top - SPEC_FIELDS:
        errs.append(f"{skill.name}: non-spec frontmatter fields {sorted(extra)}")
    name = re.search(r"^name:\s*(.+)$", fm, re.M)
    if not name or name.group(1).strip() != skill.name:
        errs.append(f"{skill.name}: name must equal folder name")
    elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", skill.name) or len(skill.name) > 64:
        errs.append(f"{skill.name}: invalid name")
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    if not desc:
        errs.append(f"{skill.name}: missing description")
    elif len(desc.group(1).strip()) > 1024:
        errs.append(f"{skill.name}: description is {len(desc.group(1).strip())} chars (max 1024)")
    lines = text.count("\n")
    if lines > 500:
        errs.append(f"{skill.name}: SKILL.md has {lines} lines (max 500)")
    return errs


def main():
    check_only = "--check" in sys.argv
    errs = []
    for s in SKILLS:
        dst = s / "references" / "protocol.md"
        if not check_only:
            dst.parent.mkdir(exist_ok=True)
            shutil.copyfile(SRC, dst)
        if not dst.exists() or sha(dst) != sha(SRC):
            errs.append(f"{s.name}: references/protocol.md differs from protocol/protocol.md")
        errs += lint(s)
        d = re.search(r"^description:\s*(.+)$", (s / "SKILL.md").read_text(), re.M)
        print(f"{s.name:<16} protocol {sha(dst) if dst.exists() else '-':<12} "
              f"description {len(d.group(1).strip()) if d else 0} chars")
    print(f"{'source':<16} protocol {sha(SRC)}")
    for e in errs:
        print("ERROR", e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
