"""外部ソースのアダプタ。**ソースを足す唯一の追加点**。

各モジュールが`@register_adapter("...")`で自分を登録する。ここでimportすることが登録に
当たるため、新しいアダプタを足したらこのファイルへ1行加える。取込の共通経路
（`app/batch/ingest.py`）はアダプタ名だけを見て呼び、外部の形を一切知らない。
"""

from app.batch.source_adapters import gsi_dem_tile  # noqa: F401
from app.batch.source_adapters import npa_honhyo  # noqa: F401

__all__ = ["gsi_dem_tile", "npa_honhyo"]
