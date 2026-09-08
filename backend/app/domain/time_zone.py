"""アプリ全体で使う日本標準時（JST）の正準定義。

JMAの配信データ・薄明の計算・ルートの通過予定時刻など、時刻を扱う箇所が独立に
`ZoneInfo("Asia/Tokyo")`を持つと、型（`ZoneInfo`か固定オフセットか）や表記が分かれる。
戦略層（`services/route_generator.py`）からタイムゾーン定数だけを輸入する形も、
依存の向きとして不自然になる。ここを唯一の定義とする。
"""

from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
