"""全部の測りの結果から、テストの見直しの候補を出す（.claude/rules/testing-review.md「テストを変異テストで見直す」）。backend の下で、
測った版と同じ版のチェックアウトで、analyze.py のあとに打つ。

引数: 成果物を取ってきた場所（analyze.py に渡した所。pertest.json・summary.json がある） 前回の見直しの場所（無ければ空の
ディレクトリ） 書き出す場所
書くもの（書き出す場所）:
- review.json: 測った版・今回の重なりの候補（テスト関数ごとに、中身のハッシュ・行数・高さ・消したあとの確かめに使う変異と残す
  テスト）・消す一覧（前回と今回の両方で候補になり、中身が変わっていないもの）・書き方の候補・隔離の候補
- summary.md: 実行の要約に出す表

重なりの候補の選び方:
- テストの高さは、通る関数の層（.importlinter の layers）の一番上。200本以上のテストが通る足場の関数と、読み込みのときに
  呼ばれうる関数（importtime.py）は数えない。数える関数が無いテストは判断できないので残す。
- 判断できないものは残す: 読み込みのときに呼ばれうる関数の変異を見つけるテスト・基準で落ちたテスト（隔離の候補）。変異を1つも
  見つけないテストは比べようがないので候補にしない（書き方の候補に出す）。
- API の経路（app/api/routers の関数）ごとに、それを通るテストを1本は残す。
- 低い高さから順に、同じ高さ以下の残すテストで見つからない変異を多く見つける順に残し、何も足さないものを候補にする。
- 消すのはテスト関数ごと: パラメータの組の1つでも残すなら、その関数は候補にしない。

書き方の候補（review.json の writing。analyze.py が pertest.json に出した組を、テスト関数ごとにまとめる。問いの番号は
.claude/rules/testing.md「そのテストは要るか（3問を順に）」）。既製の書き方の検出器は pytest に使えるものが無い（PyNose は
unittest と PyCharm だけ、pytest-smell は作りかけの研究用）ので、測りの記録からここで出す:
- 通るのに何も見つけない（zero）: 関数を通るのに、変異を1つも見つけない。確かめが弱い（値を見ずに型や件数だけを見る）か、
  1問目・2問目で要らないものが多い。
- 広くしか落ちない（broad_only）: 見つけた変異が全部、100本以上のテストが一緒に落ちる書き換え（どのテストでも落ちる壊れ方）だけ。
  そのテストだけが確かめていることが、変異で見えていない。値を見る確かめが弱いか、3問目で広い方に含まれる。
"""
import collections
import configparser
import functools
import glob
import hashlib
import heapq
import json
import os
import subprocess
import sys

from _shared import def_lines, fn_of
from importtime import called_at_import, is_import_time

ART, PREV, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SCAFFOLD_TESTS = 200
LIST_IN_SUMMARY = 60
os.makedirs(OUT, exist_ok=True)

pertest = json.load(open(os.path.join(ART, "pertest.json"), encoding="utf-8"))
summary = json.load(open(os.path.join(ART, "summary.json"), encoding="utf-8"))
shard = sorted(glob.glob(os.path.join(ART, "mutation-*")))[0]
tbf = {k: set(v) for k, v in json.load(open(os.path.join(shard, "mutmut-stats.json"), encoding="utf-8"))
       ["tests_by_mangled_function_name"].items()}
found = {t: set(v) for t, v in pertest["found"].items()}
baseline_failed = {t for v in pertest["baseline_failed"].values() for t in v}


def key_of(nodeid):
    """テスト関数（パラメータの組を外した名前）。"""
    return nodeid.split("[")[0]


# 層の高さ。.importlinter の layers は上から並ぶので、下ほど低い。
cfg = configparser.ConfigParser()
cfg.read(".importlinter", encoding="ascii")
layers = [line.strip() for line in cfg["importlinter:contract:layers"]["layers"].splitlines() if line.strip()]
rank = {name.strip(): len(layers) - 1 - i for i, line in enumerate(layers) for name in line.split("|")}


def layer_rank(fn):
    """関数の層の高さ（app の直下のモジュール・パッケージの名前で引く。層に無ければ None）。"""
    return rank.get(fn.split(".")[1])


called = called_at_import()
import_time = {f for f in tbf if is_import_time(f, called)}
scaffold = {f for f, ts in tbf.items() if len(ts) >= SCAFFOLD_TESTS}
funcs_of = collections.defaultdict(set)
for f, ts in tbf.items():
    for t in ts:
        funcs_of[t].add(f)


def height(t):
    hs = [layer_rank(f) for f in funcs_of[t] if f not in scaffold and f not in import_time]
    hs = [h for h in hs if h is not None]
    return max(hs) if hs else None


judge = set(found)
heights = {t: height(t) for t in judge}
why_kept = {}
for t in judge:
    if any(fn_of(m) in import_time for m in found[t]):
        why_kept[t] = "読み込みのときに呼ばれうる関数の変異を見つける"
    elif t in baseline_failed:
        why_kept[t] = "基準で落ちた（隔離）"
    elif heights[t] is None:
        why_kept[t] = "高さを決める関数が無い"
by_key = collections.defaultdict(set)
for t in judge:
    by_key[key_of(t)].add(t)


def close_siblings(kept):
    """残すテストの、同じテスト関数のパラメータの組も残す。"""
    for k in {key_of(t) for t in kept}:
        kept |= by_key[k]
    return kept


forced = close_siblings(set(why_kept))
for r in sorted(f for f in tbf if f.startswith("app.api.routers.")):
    through = tbf[r]
    if any(t not in judge or t in forced for t in through):
        continue  # 何も見つけないテスト（候補にしない）か、もう残すテストが通っている
    pick = min((t for t in through if heights[t] is not None),
               key=lambda t: (heights[t], -len(found[t]), t), default=None)
    if pick:
        why_kept[pick] = "API の経路を通る1本"
        forced = close_siblings(forced | {pick})

kept = set(forced)
redundant = set()
cov = set()
for h in sorted({v for v in heights.values() if v is not None}):
    level = [t for t in judge if heights[t] == h]
    for t in level:
        if t in kept:
            cov |= found[t]
    # 足す変異の多い順に残す（足す数は残すたびに減るだけなので、取り出したときに数え直して、減っていなければ一番多い）。
    heap = [(-len(found[t] - cov), t) for t in level if t not in kept]
    heapq.heapify(heap)
    while heap:
        neg, t = heapq.heappop(heap)
        gain = len(found[t] - cov)
        if gain == 0:
            redundant.add(t)
        elif gain < -neg:
            heapq.heappush(heap, (-gain, t))
        else:
            kept.add(t)
            cov |= found[t]
kept = close_siblings(kept)
cand_keys = sorted(k for k, ts in by_key.items() if ts <= redundant and not ts & kept)

# 確かめ: 候補の見つける変異は、全部、同じ高さ以下の残すテストが見つける。
kept_found_by_height: dict[int, set[str]] = collections.defaultdict(set)
for t in kept:
    if heights.get(t) is not None:
        kept_found_by_height[heights[t]] |= found[t]
kept_found_at_or_below: dict[int, set[str]] = {}
below: set[str] = set()
for h in sorted(set(kept_found_by_height) | {v for v in heights.values() if v is not None}):
    below = below | kept_found_by_height.get(h, set())
    kept_found_at_or_below[h] = below
violations = []
for k in cand_keys:
    for t in by_key[k]:
        if not found[t] <= kept_found_at_or_below[heights[t]]:
            violations.append(t)
if violations:
    raise SystemExit(f"低い方に残すの確かめに反する候補 {len(violations)} 件: {violations[:5]}")

finders_kept = collections.defaultdict(list)
for t in sorted(kept):
    for m in found[t]:
        finders_kept[m].append(t)


@functools.cache
def source_of(key):
    """テスト関数の中身（デコレータから）のハッシュと行数。"""
    path, _, name = key.partition("::")
    try:
        lines = def_lines(path, name)
    except OSError:
        return None, 0
    if lines is None:
        return None, 0
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12], len(lines)


candidates = {}
for k in cand_keys:
    digest, n = source_of(k)
    t = min(by_key[k])
    m = min(found[t], key=lambda x: (len(finders_kept[x]), x))
    witness = next(u for u in finders_kept[m] if heights.get(u) is not None and heights[u] <= heights[t])
    candidates[k] = {"hash": digest, "lines": n, "height": heights[t], "mutant": m, "kept_test": witness}

prev_path = os.path.join(PREV, "review.json")
prev = json.load(open(prev_path, encoding="utf-8")) if os.path.exists(prev_path) else None
measured = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
counts = summary["変異の数"]
complete = counts["done"] == counts["planned"]  # 途中で止まった測りは、候補が欠けるので比べない
delete = []
if prev and complete:
    delete = sorted(k for k, v in candidates.items()
                    if v["hash"] and k in prev["candidates"] and prev["candidates"][k]["hash"] == v["hash"])


instances = collections.defaultdict(set)
for t in set(funcs_of) | judge:
    instances[key_of(t)].add(t)


def whole(group):
    """全部のパラメータの組が group に入るテスト関数。"""
    return sorted(k for k in {key_of(t) for t in group} if instances[k] <= group)


zero = whole(set(pertest["zero"]))
broad = whole(set(pertest["broad_only"]))
isolation = sorted({key_of(t) for t in baseline_failed})
review = {"measured": measured, "previous": prev["measured"] if prev else None, "complete": complete,
          "mutants": counts, "candidates": candidates,
          "delete": delete, "writing": {"zero": zero, "broad_only": broad}, "isolation": isolation,
          "kept_reasons": dict(collections.Counter(why_kept.values()))}
json.dump(review, open(os.path.join(OUT, "review.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def lines_of(keys):
    return sum(source_of(k)[1] for k in keys)


whole_score = summary["全体"]
md = [f"## テストの見直し（測った版 `{measured[:9]}`、前回 `{(prev['measured'] if prev else '無し')[:9]}`）", "",
      "| 観点 | テスト関数 | 行数 |", "|---|---:|---:|",
      f"| 重なり: 今回の候補 | {len(candidates)} | {sum(v['lines'] for v in candidates.values())} |",
      f"| 重なり: 消す一覧（前回と今回の両方で候補・中身が同じ） | {len(delete)} | {sum(candidates[k]['lines'] for k in delete)} |",
      f"| 書き方: 通るのに何も見つけない | {len(zero)} | {lines_of(zero)} |",
      f"| 書き方: 広くしか落ちない（100本以上が一緒に落ちる書き換えだけで落ちた） | {len(broad)} | {lines_of(broad)} |",
      f"| 隔離: 基準で落ちた | {len(isolation)} | {lines_of(isolation)} |", "",
      f"効き: 変異スコア {whole_score['detected']}/{whole_score['n']}（生き残り {whole_score['survived']}）。"
      f"判断できずに残したテスト: {review['kept_reasons']}", ""]
if not complete:
    md += [f"変異を回し終えていない（{counts['done']}/{counts['planned']}）ので、消す一覧を出さず、次の見直しの前回にもしない。", ""]
if prev and prev["measured"] == measured:
    md +=["前回と同じ版を測ったので、消す一覧は2回続けての確かめになっていない。", ""]
for title, keys in (("消す一覧", delete), ("隔離の候補", isolation)):
    if keys:
        md += [f"### {title}", ""] + [f"- `{k}`" for k in keys[:LIST_IN_SUMMARY]]
        if len(keys) > LIST_IN_SUMMARY:
            md.append(f"- ほか {len(keys) - LIST_IN_SUMMARY} 件（成果物 mutation-review の review.json）")
        md.append("")
open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
print("\n".join(md))
if os.environ.get("GITHUB_OUTPUT"):  # ワークフローが、回し終えた測りの見直しだけを成果物に残す
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"complete={'true' if complete else 'false'}\n")
