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

from dataclasses import dataclass
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
    """
    april_first = date(year, 4, 1)
    first_wednesday = april_first + timedelta(days=(_WEDNESDAY - april_first.weekday()) % 7)
    start = first_wednesday + timedelta(weeks=3)
    return start, start + timedelta(weeks=_PROVISION_WEEKS)


def is_within_provision_period(at: datetime) -> bool:
    """`at`（JST）の日が提供期間に入るか。"""
    start, end = provision_period(at.year)
    return start <= at.date() <= end


@dataclass(frozen=True)
class WbgtPoint:
    """暑さ指数の情報提供地点。地点は行政区画ではなくアメダス観測所に置かれているため、
    区域の親子関係ではなく最寄りの地点で引く。"""

    no: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class WbgtForecast:
    """暑さ指数の予測値1件。発表時刻の無い行は載せない。"""

    #: 発表時刻（配信元の表記。同じ表記どうしの大小がそのまま時刻の前後になる）。
    reference_time: str
    #: 予測の対象時刻（JSTの素の時刻）。読めない行はNone。
    forecast_time: datetime | None
    #: 対象時刻の配信元の表記（応答へそのまま出す）。
    forecast_time_text: str | None
    #: 暑さ指数。値が無い・読めない行はNone。
    wbgt: float | None


# 発表（reference_time）は概ね毎時だが遅延もありうるため、直近この時間幅で発表時刻を
# 検索する（1〜2時間の遅延は起こりうる前提で余裕を持たせる）。
FORECAST_SEARCH_WINDOW_HOURS = 6


def current_forecast(forecasts: list[WbgtForecast], now: datetime) -> WbgtForecast | None:
    """最新の発表回に絞ったうえで、現在時刻に最も近い対象時刻の予測を選ぶ。

    検索窓を広げて取得したレスポンスには発表回（reference_time）が複数混ざる。絞らずに
    「現在時刻に最も近い」を選ぶと、新しい発表回で既に置き換わっている値を拾いうる。
    """
    if not forecasts:
        return None
    latest_reference_time = max(forecast.reference_time for forecast in forecasts)

    now_naive = now.replace(tzinfo=None)
    best: WbgtForecast | None = None
    best_diff: float | None = None
    for forecast in forecasts:
        if forecast.reference_time != latest_reference_time or forecast.forecast_time is None:
            continue
        diff = abs((forecast.forecast_time - now_naive).total_seconds())
        if best_diff is None or diff < best_diff:
            best, best_diff = forecast, diff
    return best
