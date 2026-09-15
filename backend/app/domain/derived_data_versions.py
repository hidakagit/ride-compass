"""事前計算バッチ（`app/batch/precompute_*.py`）が書き込む派生データの系譜版数。

バッチ本体ではなくdomainに置く。鮮度台帳（`infrastructure/derived_data_freshness.py`、web
アプリが起動時に必ず読み込む）が「現在の版はどれか」を知る必要があるためで、版数を
バッチモジュール側に置くとinfrastructure→batchのimportが生まれる。batchは
`requirements-batch.txt`限定の依存（rasterio等）を使うのに対し本番webイメージは
`requirements.txt`しか入れないため、その向きのimportがあると**バッチへ依存を1行足した
だけで本番webが起動できなくなる**（CIとテストはbatch依存が入っているため緑のまま通る）。

版数を上げるのはアルゴリズムの出力が変わったときで、上げると鮮度台帳が既存行を古い版として
検知し、管理画面（`GET /api/admin/derived-data/freshness`）に再実行が必要として現れる。
"""

EDGE_ATTRIBUTE_COUNTS_ALGORITHM_VERSION = "v3"
WAY_ATTRIBUTE_COUNTS_ALGORITHM_VERSION = "v3"
WAY_DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION = "v1"

# 土地被覆はリング径ごとに別のアルゴリズムとして扱う（`--buffer-m`/`--inner-m`へ既定と違う値を
# 渡して実行した行は、鮮度台帳が古い版として検知する）。
WAY_LANDCOVER_DEFAULT_BUFFER_M = 100.0
WAY_LANDCOVER_DEFAULT_INNER_M = 10.0


def way_landcover_algorithm_version(inner_m: float, buffer_m: float) -> str:
    return f"v1-ring{int(inner_m)}-{int(buffer_m)}"


WAY_LANDCOVER_ALGORITHM_VERSION = way_landcover_algorithm_version(
    WAY_LANDCOVER_DEFAULT_INNER_M, WAY_LANDCOVER_DEFAULT_BUFFER_M
)
