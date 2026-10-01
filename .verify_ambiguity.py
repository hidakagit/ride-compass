"""差分で足した名指しの1組ずつについて、同じ末尾のファイルを1本足すと「曖昧」で出るかを見る。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend" / "tests" / "structure"))
import test_named_references as t  # noqa: E402

files = t.tracked_files(ROOT)
assert t.dangling_references(ROOT, files) == [], "起点で既に検知がある"

diff = subprocess.run(
    ["git", "diff", "-U0", "3a9457f5", "HEAD"], cwd=ROOT, check=True, capture_output=True
).stdout.decode("utf-8")
changed: dict[str, set[int]] = {}
cur = None
for line in diff.splitlines():
    if line.startswith("+++ b/"):
        cur = line[6:]
        changed[cur] = set()
    elif line.startswith("@@") and cur:
        plus = line.split("+")[1].split(" ")[0]
        start, _, count = plus.partition(",")
        n = int(count) if count else 1
        changed[cur].update(range(int(start), int(start) + n))

pairs = set()
refs = 0
for rel, rows in changed.items():
    if Path(rel).suffix not in t.SCANNED_SUFFIXES:
        continue
    text = (ROOT / rel).read_text(encoding="utf-8")
    prose = t._keep(text, t.prose_spans(rel, text), inside=True)
    for m in t.REFERENCE.finditer(prose):
        row = prose.count("\n", 0, m.start()) + 1
        if row in rows:
            refs += 1
            pairs.add((rel, row, m.group("path"), m.group("name")))

written_paths = sorted({p for _, _, p, _ in pairs})
missed = []
for wp in written_paths:
    fake = "zz_verify_fake/" + wp.lstrip("./")
    found = t.dangling_references(ROOT, files + [fake])
    expected = [(rel, row, name) for rel, row, p, name in pairs if p == wp]
    for rel, row, name in expected:
        key = f"{rel}:{row}: {wp}: {name}（パスが2本に当たる"
        if not any(f.startswith(key) for f in found):
            missed.append((rel, row, wp, name))

print(f"差分の行で読まれた名指し {refs} 件・異なる（場所, パス, 名前）{len(pairs)} 組・異なるパス {len(written_paths)} 本")
print(f"同じ末尾のファイルを足して『2本に当たる』で出なかった組: {len(missed)}")
for m in missed:
    print("  ", m)
