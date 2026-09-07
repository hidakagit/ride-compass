"""rasterioが参照するPROJデータの場所を、rasterio同梱のものへ固定する。

rasterioは環境変数`PROJ_DATA`（PROJ 9系。旧称`PROJ_LIB`）を見て座標系データベース
`proj.db`を探す。この変数はPostGIS等の別アプリが自分用に設定していることがあり、その
場合はrasterioが要求するより古いレイアウトの`proj.db`を掴んでEPSG解決が失敗する
（`CRSError: The EPSG code is unknown.`）。

rasterioのwheelは自分が要求するレイアウトの`proj.db`を同梱しており、別インストールの
ものと混ぜて使う正しい使い方は無い。そのため同梱データが見つかる限りはそれを指す。
同梱データが無いビルド（システムのGDAL/PROJへリンクした構成）では何もしない。

**rasterioをimportする前に呼ぶこと。** import時点の環境変数が読まれるため、後から
設定しても効かない。
"""

import importlib.util
import os
from pathlib import Path


def pin_bundled_proj_data() -> Path | None:
    """rasterio同梱の`proj_data`を`PROJ_DATA`/`PROJ_LIB`へ設定する。

    設定したパスを返す。同梱データが見つからなければ何もせずNoneを返す。
    """
    spec = importlib.util.find_spec("rasterio")
    if spec is None or not spec.origin:
        return None
    bundled = Path(spec.origin).parent / "proj_data"
    if not bundled.is_dir():
        return None
    os.environ["PROJ_LIB"] = str(bundled)
    os.environ["PROJ_DATA"] = str(bundled)
    return bundled
