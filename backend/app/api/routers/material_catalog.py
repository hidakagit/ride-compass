"""材料カタログの管理画面向けAPI（いずれもHTTP Basic認可要）。

材料の一覧そのものはAPIで配らない。材料はコードの宣言（`domain/material_catalog.py`）で決まり
再デプロイでしか変わらないため、frontendはビルド時の生成物（`export_openapi.py`が書き出す
`material-catalog.json`）だけから材料を知る。ここに置くのは、実データを読まないと答えられないものだけ。

`GET /api/admin/material-catalog/{material_id}/values`（読み取り専用だがHTTP Basic認可要）は、
highway/surface/smoothnessのようなOSMタグの生値でオープンエンドな材料について、DBに
実際に取り込まれている値を動的取得し返す（軸スタジオの値入力欄がタグ生値を
暗記して手入力せずに選べるようにする）。値を出せないとき（DB障害・タイムアウト）は
`available=false`を返し、呼び出し側（フロント）が自由テキスト入力へフォールバックする。

`values.label`（`MaterialSpec.value_label`）は材料の値ごとの日本語ラベル対訳表
（`MaterialSpec.value_labels`、`domain/material_catalog.py`、材料定義自体の一部）を
そのまま返す。材料名（生成物の`label`、`MaterialSpec.full_label`）と同じく
「論理名 - 物理名」形式（例: 値"自転車専用道 - cycleway"）で
返す——論理名だけではどのOSMタグ値に対応するか分からず、軸定義
（`AxisDefinitionResponse`）や外部ドキュメント上で物理名を探す必要があるため。

`GET /api/admin/material-catalog/coverage`（Basic認証必須）は、材料ごとの欠損割合
（元データ[タグ・派生テーブル行]が無いWay/Edgeの割合）を全材料ぶん返す管理画面向けの
集計API（`services/material_coverage_service.py`・`infrastructure/material_coverage.py`）。
認可を要求する理由は`get_material_coverage`のdocstring参照。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_axis_preview_service, get_material_coverage_service
from app.domain.material_catalog import MATERIAL_CATALOG, is_known_material
from app.domain.value_distribution import EMPTY_SPREAD, ValueSpread
from app.services.axis_preview_service import AxisPreviewService
from app.services.material_coverage_service import MaterialCoverageReport, MaterialCoverageService
from app.domain.strict_model import StrictModel

router = APIRouter()


class MaterialValueEntry(StrictModel):
    value: str
    # 「論理名 - 物理名」形式（例: "自転車専用道 - cycleway"）。ラベル対訳表に無い値は
    # valueと同じ文字列（MaterialSpec.value_labelのフォールバック、新しいOSMタグ値が
    # DBに現れてもAPIが失敗しないようにするため。この場合論理名が無いため" - "は付かない）。
    label: str


class MaterialValuesResponse(StrictModel):
    """`available=False`は「候補を出せなかった」（DB障害・タイムアウト）。
    `available=True`で`values`が空なら「取得できたが値が無い」。画面はこの2つを
    区別して出す（区別しないと、DBのタイムアウトが「値が無い」として静かに表示される）。
    """

    available: bool = True
    values: list[MaterialValueEntry]


class MaterialDistributionResponse(ValueSpread):
    """材料の値の分位点とゼロの割合（延長で重み付け）。`available=false`は数値材料でなく、どちらも空。"""

    available: bool


def _require_known_material(material_id: str) -> None:
    if not is_known_material(material_id):
        raise HTTPException(status_code=404, detail=f"unknown material '{material_id}'")


@router.get(
    "/api/admin/material-catalog/{material_id}/distribution",
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_material_distribution(
    material_id: str,
    preview: AxisPreviewService = Depends(get_axis_preview_service),
) -> MaterialDistributionResponse:
    """材料の値が実データでどの範囲に散らばっているかを返す（軸スタジオ）。

    折れ点をどこへ置くかは、その材料が実際に取る値を知らないと決められない。カタログの
    `reference_points`はコードに書いた代表値で、実データの分布ではない。
    数値材料のみ対象で、真偽・カテゴリ材料は`available=false`を返す（分位に意味が無い）。
    """
    _require_known_material(material_id)
    distribution = await preview.material_value_distribution(material_id)
    if distribution is None:
        return MaterialDistributionResponse(available=False, **EMPTY_SPREAD.model_dump())
    return MaterialDistributionResponse(available=True, **distribution.model_dump())


@router.get(
    "/api/admin/material-catalog/{material_id}/values",
    response_model=MaterialValuesResponse,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_material_values(
    material_id: str,
    preview: AxisPreviewService = Depends(get_axis_preview_service),
) -> MaterialValuesResponse:
    """材料idに対応する実データの値一覧（ソート済み、重複無し）を返す。
    未知の材料idは404（フロントのタイプミス検知用）。値一覧を持たない材料（カテゴリ以外の
    真偽・数値の材料と、値の求め方を持たない材料）は`available=true`の空リスト、
    DB障害・タイムアウトは`available=false`を返す
    （`services/axis_preview_service.py: AxisPreviewService.material_values`参照。「候補が無い」と「候補を出せなかった」を
    画面が区別できるようにするため、両方を空リストへ倒さない）。

    利用者は軸スタジオ（`/admin`）だけで、1リクエストにつき索引の効かない
    `SELECT DISTINCT`（実質全表走査）を1回実行する。
    認可なしで公開すると繰り返し呼ばれるだけでプールを枯渇させられるため、同じ理由で
    Basic認証を課している`/api/admin/material-catalog/coverage`と同じadminパスへ置く。
    """
    _require_known_material(material_id)
    values = await preview.material_values(material_id)
    if values is None:
        return MaterialValuesResponse(available=False, values=[])
    spec = MATERIAL_CATALOG[material_id]
    return MaterialValuesResponse(values=[MaterialValueEntry(value=v, label=spec.value_label(v)) for v in values])


@router.get(
    "/api/admin/material-catalog/coverage",
    response_model=MaterialCoverageReport,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_material_coverage(
    service: MaterialCoverageService = Depends(get_material_coverage_service),
) -> MaterialCoverageReport:
    """全材料の欠損割合（`MATERIAL_CATALOG`の登録順、集計対象外の材料は理由付き）を返す。

    読み取り専用のAPIだがBasic認証を要求する:
    道の生データと区間の材料の全表走査を伴う重いクエリで、認可なしに公開すると
    繰り返し呼ばれるだけでDBを圧迫できてしまう（管理画面`/admin`からのみ使う想定）。
    """
    return await service.get_material_coverage()
