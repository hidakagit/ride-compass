"""市民薄明（civil twilight）に基づく夜間判定（改善計画T173）。

night軸（`domain/night.py`、街灯・トンネル由来の走りにくさ）を出発・到達時刻に応じて
動的化するための天文計算。night_difficulty自体（街灯・トンネルタグからの難易度算出）は
時刻を知らないまま据え置き、呼び出し元が本モジュールの`is_night`で「今、この地点は
市民薄明の外（夜間）か」を判定し、night_weightをその真偽で0/1に切り替えることで動的化する
（domain/night.py・difficulty.pyの変更は不要。呼び出し元がweightを掛け替えるだけで済む
設計、詳細はopenrouteservice_engine.py/road_graph_engine.pyの利用箇所参照）。

市民薄明（太陽高度-6度、日没後も屋外の視認性が残る時間帯）の終わりを「夜」の境界に使う
（日の入り時刻そのものではなく、薄明が終わるまではまだ十分明るいため。改善計画の
「市民薄明の開始/終了を境界に使う」という対応方針どおり）。

天文計算は`astral`ライブラリ（暦計算、外部通信なし・決定論的）に委譲する。妥当性は
sunrise-sunset.org（NOAA準拠の公開API）の実測値との突き合わせで確認済み
（test_twilight.py、東京の夏至・冬至・秋分。計算方式の違いにより数分のずれは許容）。

`astral.sun(observer, date=D, tzinfo=UTC)`は「dateで指定したUTC暦日の中に収まる
薄明イベント」を返すため、経度が東側（日本など）だと同じdate引数から返るdawnとduskが
別々の現地日（duskはD当日の夕方、dawnは翌日の未明）を指し、時刻順が入れ替わって返る
（実機検証で判明。安易に`dawn <= at <= dusk`で当日の昼間を判定すると誤る）。この関数は
その罠を避けるため、`at`前後数日分のdawn/dusk全イベントをUTC時刻で単純にソートし、
直前のイベント種別（dawn直後=昼、dusk直後=夜）で判定する（地域・時期に依存しない
頑健な方法）。
"""

from datetime import date, datetime, timedelta, timezone

from astral import Observer
from astral.sun import sun

from app.domain.route import Coordinates

# at前後の探索範囲（日数）。市民薄明が定義できる緯度なら1日あれば足りるが、日付跨ぎの
# 経度ずれ（上記docstring参照）を確実に吸収するため余裕を持たせる。
_SEARCH_WINDOW_DAYS = 2


def is_night(coordinates: Coordinates, at: datetime) -> bool:
    """`at`が`coordinates`地点の市民薄明の外（夜間）かどうか。`at`がtz-naiveならUTCとみなす
    （呼び出し元の到達時刻計算がUTCで統一されているため）。極夜・白夜等、市民薄明が
    定義できない緯度（本サービスの対象地域では実質発生しない）ではNoneを返す代わりに
    安全側（False、night軸を有効化しない）に倒す。"""
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


def _civil_dawn_dusk(observer: Observer, day: date) -> tuple[datetime, datetime] | None:
    try:
        s = sun(observer, date=day, tzinfo=timezone.utc)
    except ValueError:
        # astralは市民薄明が定義できない日（極夜・白夜）でValueErrorを投げる。
        return None
    return s["dawn"], s["dusk"]
