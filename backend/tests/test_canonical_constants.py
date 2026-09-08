"""正準定義が1箇所であることの機械的な確認。

JST・警戒度バッジの語彙・ロガー接頭辞は、独立に定義しても動いてしまうため、コピーが
増えたこと自体は動作では現れない（片方だけ直す・未知の値が静かに縮退する形でしか
現れない）。ここで定義箇所を数えて固定する。
"""

import re
from pathlib import Path

from app.domain.time_zone import JST
from app.domain.warning_levels import WARNING_BADGE_LEVELS

# 外部ライブラリが自分で作るロガー。こちらが名指しするのはレベル制御のためで、
# アプリのログ出力そのものではないため命名規約の対象外。
EXTERNAL_LIBRARY_LOGGERS = {"httpx"}

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PY_FILES = sorted(APP_DIR.rglob("*.py"))


def _sources() -> list[tuple[str, str]]:
    """(app/からの相対パス, ソース)。パス区切りは"/"へ正規化する（OS非依存の比較のため）。"""
    return [(p.relative_to(APP_DIR).as_posix(), p.read_text(encoding="utf-8")) for p in PY_FILES]


def test_jst_is_defined_only_in_the_canonical_module():
    # `ZoneInfo("Asia/Tokyo")`も固定オフセット（timezone(timedelta(hours=9))）も、
    # 定義してよいのはdomain/time_zone.pyだけ。
    pattern = re.compile(r'ZoneInfo\("Asia/Tokyo"\)|timezone\(timedelta\(hours=9\)\)')
    offenders = [rel for rel, src in _sources() if pattern.search(src)]

    assert offenders == ["domain/time_zone.py"]


def test_jst_is_a_zoneinfo_for_asia_tokyo():
    assert str(JST) == "Asia/Tokyo"


def test_warning_badge_levels_are_ordered_from_light_to_severe():
    # frontend（WarningBadge.tsx: LEVEL_ORDER）と同じ並び。順序が食い違うと「最も重い
    # 警戒度を1つ選ぶ」判定が両者でずれる。
    assert WARNING_BADGE_LEVELS == ("advisory", "warning", "severe_warning", "emergency_warning")


def test_badge_level_vocabulary_is_not_redefined_as_a_literal_union():
    # 4語彙を並べたLiteral/tupleを別の場所で作らない（domain/warning_levels.pyが唯一）。
    pattern = re.compile(r'"advisory"[^\n]*"emergency_warning"|"emergency_warning"[^\n]*"advisory"')
    offenders = [rel for rel, src in _sources() if pattern.search(src)]

    assert offenders == ["domain/warning_levels.py"]


def test_loggers_use_the_documented_prefix():
    # docs/logging.md: ロガー名は`ridecompass.<用途>`。`app.*`が混ざると接頭辞単位の
    # レベル制御を入れたときにそちらだけ漏れる。
    pattern = re.compile(r'getLogger\("(?!ridecompass\.)([^"]+)"\)')
    offenders = sorted(
        f"{rel}: {name}"
        for rel, src in _sources()
        for name in pattern.findall(src)
        if name not in EXTERNAL_LIBRARY_LOGGERS
    )

    assert offenders == []
