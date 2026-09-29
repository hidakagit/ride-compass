"""環境省 熱中症予防情報サイトの暑さ指数（WBGT）警戒レベル判定。

閾値は環境省サイト掲載の「熱中症予防運動指針」（(公財)日本スポーツ協会「スポーツ活動中の
熱中症予防ガイドブック」2019、https://www.wbgt.env.go.jp/wbgt.php 掲載の内容）を
典拠とする。サイクリングは運動のため、日常生活に関する指針（日本生気象学会）ではなく
運動指針を採用する。指針の最も軽い区分「ほぼ安全」（21未満）は警告として意味を持たない
ため、バッジ表示の対象にしない。

暑さ指数（WBGT）は気温と同じ摂氏度で表されるが気温そのものではない値のため、環境省サイトの
表記に倣い単位（℃）を付けずに「暑さ指数」とだけ呼ぶ。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.warning_levels import WarningBadgeLevel

_WEDNESDAY = 2
_PROVISION_WEEKS = 26

# 熱中症予防運動指針の閾値（暑さ指数の値、以上/未満の境界）。
# 21未満（ほぼ安全）はNoneを返す。
_LEVEL_THRESHOLDS: list[tuple[float, WarningBadgeLevel, str]] = [
    (31.0, "emergency_warning", "危険"),
    (28.0, "severe_warning", "厳重警戒"),
    (25.0, "warning", "警戒"),
    (21.0, "advisory", "注意"),
]


#: 段階ごとの表示名（警戒度バッジが出す語。domain/warning_display.py）。
WBGT_LEVEL_LABELS: dict[WarningBadgeLevel, str] = {level: label for _, level, label in _LEVEL_THRESHOLDS}


def wbgt_level(value: float) -> tuple[WarningBadgeLevel, str] | None:
    """暑さ指数の値から(levelキー, 表示名)を返す。21未満（ほぼ安全）はNone。"""
    for threshold, level, label in _LEVEL_THRESHOLDS:
        if value >= threshold:
            return level, label
    return None


def provision_period(year: int) -> tuple[date, date]:
    """その年の暑さ指数の提供期間（初日と最終日。どちらの日も期間に含む）。

    環境省は運用期間を年ごとに発表し、4月第4水曜から26週後の水曜までに置いている。
    終わりは10月第3水曜の年も第4水曜の年もあるため、月の何週目では決まらない。
    期間外の配信元は、エラーではなく値の無い成功を返す。
    """
    april_first = date(year, 4, 1)
    first_wednesday = april_first + timedelta(days=(_WEDNESDAY - april_first.weekday()) % 7)
    start = first_wednesday + timedelta(weeks=3)
    return start, start + timedelta(weeks=_PROVISION_WEEKS)


def is_within_provision_period(at: datetime) -> bool:
    """`at`（JST）の日が提供期間に入るか。"""
    start, end = provision_period(at.year)
    return start <= at.date() <= end
