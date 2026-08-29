"""MSM（メソスケールモデル、5kmメッシュ）データのドメインモデル（改善計画T387、スケルトン）。

実際のGRIB2バイナリ解析（pygrib/cfgrib等、ネイティブ依存を伴う新規ライブラリ導入が
必要）は本タスクのスコープ外——CLAUDE.md指示は「将来受け取った際に...保存するデータ構造と
パーサースケルトンを作成」であり、実装は将来のタスクで着手する前提のインターフェース定義。
"""

from pydantic import BaseModel


class MsmMeshRecord(BaseModel):
    """5kmメッシュ1マスぶんのMSM予報値（GRIB2解析後の中間表現）。

    mesh_idは気象庁の1次細分区画に準じた5kmメッシュコード（GeoHash/H3等への置き換えは
    将来検討、CLAUDE.md指示の「または」節）。
    """

    mesh_id: str
    u_wind: float
    v_wind: float
    temp: float
    precip_1h: float
    valid_time: str
