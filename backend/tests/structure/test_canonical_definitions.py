"""正準定義と命名規約が、各所へ写されていないことの検査。

JSTも警戒度バッジの語彙も、独立に定義しても動いてしまう。コピーが増えたこと自体は動作に
現れず、**片方だけ直したとき**に初めて現れる（表記ゆれ・未知の値の静かな縮退）。ロガー名の
接頭辞も同じで、揃っていない1本は接頭辞単位のレベル制御を入れた日まで気づかれない。

ソースをテキストとして読む。母集団は`app`配下の全`.py`。
"""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"

# 外部ライブラリが自分で作るロガー。こちらが名指しするのはレベル制御のためで、
# アプリのログ出力そのものではないため命名規約の対象外。
EXTERNAL_LIBRARY_LOGGERS = {"httpx"}


def _sources() -> list[tuple[str, str]]:
    """(app/からの相対パス, ソース)。パス区切りは"/"へ正規化する（OS非依存の比較のため）。"""
    return [
        (p.relative_to(APP_DIR).as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted(APP_DIR.rglob("*.py"))
    ]


def _files_matching(pattern: re.Pattern[str]) -> list[str]:
    return [rel for rel, src in _sources() if pattern.search(src)]


def test_jst_is_defined_only_in_the_canonical_module():
    """2種類（`ZoneInfo`と固定オフセット）が混ざると、同じ「JST」でも`tzname()`と
    夏時間の扱いが違う値が流通する。
    """
    pattern = re.compile(r'ZoneInfo\("Asia/Tokyo"\)|timezone\(timedelta\(hours=9\)\)')

    assert _files_matching(pattern) == ["domain/time_zone.py"]


def test_the_badge_vocabulary_is_not_redefined_elsewhere():
    """`WarningBadgeLevel`を型として使うぶんには、値の食い違いはPydanticが弾く。
    弾けないのは語彙そのものを作り直したときだけ。
    """
    pattern = re.compile(r'"advisory"[^\n]*"emergency_warning"|"emergency_warning"[^\n]*"advisory"')

    assert _files_matching(pattern) == ["domain/warning_levels.py"]


def test_loggers_use_the_documented_prefix():
    """`ridecompass.`以外が混ざると、接頭辞単位のレベル制御を入れたときにそちらだけ漏れる
    （規約は`docs/conventions/logging.md`）。許可した名前が実態から消えたときも落とす。
    """
    pattern = re.compile(r'getLogger\("(?!ridecompass\.)([^"]+)"\)')
    named = {name for _, src in _sources() for name in pattern.findall(src)}

    assert named == EXTERNAL_LIBRARY_LOGGERS
