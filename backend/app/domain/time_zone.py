"""アプリ全体で使う日本標準時（JST）の正準定義と、時刻の読み方。

JMAの配信データ・薄明の計算・ルートの通過予定時刻など、時刻を扱う箇所が独立に
`ZoneInfo("Asia/Tokyo")`を持つと、型（`ZoneInfo`か固定オフセットか）や表記が分かれる。
戦略層（`services/route_generator.py`）からタイムゾーン定数だけを輸入する形も、
依存の向きとして不自然になる。ここを唯一の定義とする。

時刻の読み方も同じ理由でここに置く: タイムゾーンの無い時刻をJSTとして読むことと、予報の系列の時刻へ直す前に
JSTへ寄せることを呼び手ごとに書くと、tzinfoを剥がすだけの読み方が混ざり、JST以外の時刻が時差ぶんずれる。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def as_jst(value: datetime) -> datetime:
    """時刻をJSTの時刻にする。タイムゾーンの無い時刻はJSTの時刻として読む。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def as_series_time(value: datetime) -> datetime:
    """時刻を予報の系列の時刻（タイムゾーンの無いJSTの時刻）にする。読み方は`as_jst`と同じ。"""
    return as_jst(value).replace(tzinfo=None)
