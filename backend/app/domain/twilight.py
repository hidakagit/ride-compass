"""市民薄明（civil twilight）に基づく夜間判定。

街灯・トンネル由来の走りにくさを表す軸を、出発・到達時刻に応じて動的化するための天文
計算。軸の側は時刻を知らないまま据え置き、呼び出し元が`is_night`の真偽で軸の重みを
0/1に切り替える。

市民薄明（太陽高度-6度、日没後も屋外の視認性が残る時間帯）の終わりを「夜」の境界に使う
（日の入り時刻そのものではなく、薄明が終わるまではまだ十分明るいため）。

天文計算は`astral`ライブラリ（暦計算、外部通信なし・決定論的）に委譲する。

`astral.sun(observer, date=D, tzinfo=UTC)`は「dateで指定したUTC暦日の中に収まる
薄明イベント」を返すため、経度が東側（日本など）だと同じdate引数から返るdawnとduskが
別々の現地日（duskはD当日の夕方、dawnは翌日の未明）を指し、時刻順が入れ替わって返る
——`dawn <= at <= dusk`で当日の昼間を判定すると誤る。この罠を避けるため、`at`前後数日分の
dawn/dusk全イベントをUTC時刻でソートし、直前のイベント種別（dawn直後=昼、dusk直後=夜）で
判定する。
"""

from datetime import date, datetime, timedelta, timezone

from astral import Observer
from astral.sun import sun

from app.domain.time_zone import JST
from app.domain.route import Coordinates


# at前後の探索範囲（日数）。日付跨ぎの経度ずれ（上記docstring参照）を確実に吸収するため
# 1日では足りない。
_SEARCH_WINDOW_DAYS = 2


def is_night(coordinates: Coordinates, at: datetime) -> bool:
    """`at`が`coordinates`地点の市民薄明の外（夜間）かどうか。`at`がtz-naiveならUTCとみなす
    （呼び出し元の到達時刻計算がUTCで統一されているため）。極夜・白夜等、市民薄明が
    定義できない緯度ではFalse（夜として扱わない）に倒す。"""
    at_utc = at.astimezone(timezone.utc) if at.tzinfo else at.replace(tzinfo=timezone.utc)
    observer = Observer(latitude=coordinates.latitude, longitude=coordinates.longitude)

    events: list[tuple[datetime, bool]] = []  # (時刻, is_dawn)
    for delta in range(-_SEARCH_WINDOW_DAYS, _SEARCH_WINDOW_DAYS + 1):
        day = at_utc.date() + timedelta(days=delta)
        pair = _civil_dawn_dusk(observer, day)
        if pair is None:
            continue
        dawn, dusk = pair
        events.append((dawn, True))
        events.append((dusk, False))
    if not events:
        return False

    events.sort()
    is_day = False
    for ts, is_dawn in events:
        if ts > at_utc:
            break
        is_day = is_dawn
    return not is_day


def sunrise_sunset_jst(coordinates: Coordinates, on_date: date) -> tuple[str | None, str | None]:
    """`coordinates`地点の`on_date`（JST基準の暦日）における日の出・日没時刻をJST ISO文字列
    （例: "2026-08-29T05:12:00+09:00"）で返す。

    `is_night`が使う市民薄明ではなく、太陽の中心が地平線と一致する瞬間（大気差を考慮）と
    いう一般的な定義の日の出・日没を返す。定義できない緯度では(None, None)。"""
    observer = Observer(latitude=coordinates.latitude, longitude=coordinates.longitude)
    try:
        s = sun(observer, date=on_date, tzinfo=JST)
    except ValueError:
        return None, None
    return s["sunrise"].isoformat(), s["sunset"].isoformat()


def _civil_dawn_dusk(observer: Observer, day: date) -> tuple[datetime, datetime] | None:
    try:
        s = sun(observer, date=day, tzinfo=timezone.utc)
    except ValueError:
        # astralは市民薄明が定義できない日（極夜・白夜）でValueErrorを投げる。
        return None
    return s["dawn"], s["dusk"]
