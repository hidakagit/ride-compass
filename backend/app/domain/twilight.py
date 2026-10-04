"""市民薄明（civil twilight）に基づく夜間判定。

街灯・トンネル由来の走りにくさを表す軸を、区間を通る時刻に応じて動的化するための天文
計算。軸の側は時刻を知らないまま据え置き、呼び出し元が`night_mask`の真偽で区間ごとの軸の重みを
0/1に切り替える。

市民薄明（太陽高度-6度、日没後も屋外の視認性が残る時間帯）の終わりを「夜」の境界に使う
（日の入り時刻そのものではなく、薄明が終わるまではまだ十分明るいため）。

天文計算は`astral`ライブラリ（暦計算、外部通信なし・決定論的）に委譲する。

`astral.sun(observer, date=D, tzinfo=UTC)`は「dateで指定したUTC暦日の中に収まる
薄明イベント」を返すため、経度が東側（日本など）だと同じdate引数から返るdawnとduskが
別々の現地日（duskはD当日の夕方、dawnは翌日の未明）を指し、時刻順が入れ替わって返る
——`dawn <= at <= dusk`で当日の昼間を判定すると誤る。この罠を避けるため、判定する時刻の前後数日分の
dawn/dusk全イベントをUTC時刻でソートし、直前のイベント種別（dawn直後=昼、dusk直後=夜）で
判定する。
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
from astral import Observer
from astral.sun import sun

from app.domain.time_zone import JST
from app.domain.route import Coordinates
from app.domain.strict_model import StrictModel


# 判定する時刻の前後の探索範囲（日数）。日付跨ぎの経度ずれ（上記docstring参照）を確実に吸収するため
# 1日では足りない。
_SEARCH_WINDOW_DAYS = 2


def night_mask(coordinates: Coordinates, start: datetime, hours: np.ndarray) -> np.ndarray:
    """`start`から`hours`時間後の各時刻が、`coordinates`地点の市民薄明の外（夜間）かどうか（`hours`と同じ並び）。
    `start`がtz-naiveならUTCとみなす。極夜・白夜等、市民薄明が定義できない緯度と、前後の薄明の
    出来事で挟めない時刻・NaNはFalse（夜として扱わない）に倒す。

    薄明の出来事は`hours`の範囲を覆う日数ぶんだけ1回求め、各時刻は直前の出来事の種別で決める
    ——区間ごとに天文計算を回さない（探索範囲の区間は数万本ある）。"""
    start_utc = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)
    hours = np.asarray(hours, dtype=float)
    finite = hours[np.isfinite(hours)]
    if finite.size == 0:
        return np.zeros(hours.shape, dtype=bool)
    first_day = (start_utc + timedelta(hours=float(finite.min()))).date()
    last_day = (start_utc + timedelta(hours=float(finite.max()))).date()
    observer = Observer(latitude=coordinates.latitude, longitude=coordinates.longitude)

    events: list[tuple[datetime, bool]] = []  # (時刻, is_dawn)
    for delta in range(-_SEARCH_WINDOW_DAYS, (last_day - first_day).days + _SEARCH_WINDOW_DAYS + 1):
        pair = _civil_dawn_dusk(observer, first_day + timedelta(days=delta))
        if pair is None:
            continue
        dawn, dusk = pair
        events.append((dawn, True))
        events.append((dusk, False))
    if not events:
        return np.zeros(hours.shape, dtype=bool)
    events.sort()
    event_hours = np.array([(ts - start_utc).total_seconds() / 3600.0 for ts, _ in events])
    event_is_dawn = np.array([is_dawn for _, is_dawn in events])
    # 各時刻以前（同時刻を含む）の出来事の数。0（前に出来事が無い）か全部（後に無い）なら挟めない
    # ＝白夜・極夜の境目で、数日前の夕暮れを引きずって夜と判定せず、夜として扱わない側へ倒す。
    before = np.searchsorted(event_hours, hours, side="right")
    bracketed = (before > 0) & (before < len(event_hours)) & np.isfinite(hours)
    # 直前の出来事が夜明けなら昼、日暮れなら夜。
    return bracketed & ~event_is_dawn[np.clip(before - 1, 0, len(event_hours) - 1)]


class Twilight(StrictModel):
    """地点の当日（JST）の日の出・日没。JST ISO文字列（例: "2026-08-29T05:12:00+09:00"）。"""

    sunrise: str
    sunset: str


def sunrise_sunset_jst(coordinates: Coordinates, on_date: date) -> Twilight | None:
    """`coordinates`地点の`on_date`（JST基準の暦日）における日の出・日没。

    `night_mask`が使う市民薄明ではなく、太陽の中心が地平線と一致する瞬間（大気差を考慮）と
    いう一般的な定義の日の出・日没を返す。定義できない緯度ではNone。"""
    observer = Observer(latitude=coordinates.latitude, longitude=coordinates.longitude)
    try:
        s = sun(observer, date=on_date, tzinfo=JST)
    except ValueError:
        return None
    return Twilight(sunrise=s["sunrise"].isoformat(), sunset=s["sunset"].isoformat())


def _civil_dawn_dusk(observer: Observer, day: date) -> tuple[datetime, datetime] | None:
    try:
        s = sun(observer, date=day, tzinfo=timezone.utc)
    except ValueError:
        # astralは市民薄明が定義できない日（極夜・白夜）でValueErrorを投げる。
        return None
    return s["dawn"], s["dusk"]
