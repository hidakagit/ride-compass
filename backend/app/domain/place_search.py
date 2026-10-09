"""地点の検索（入力した文字列から、出発地・経由地・目的地にできる地点の候補を引く）の語彙と答えの形。

候補は種類（何から引いたか。住所の区画の表か、立ち寄り先の表の施設か）と、当たった段（住所ならどの段の区画に当たったか。
施設は施設そのものの点）を持つ。種類を足すときは
`PlaceKind`と`PLACE_KIND_LABELS`へ1つずつ足し、口と答えの形は変えない。表示名は語彙と同じ並びで
生成物（`vocabulary.ts`）が画面へ届ける。

住所は住所の区画の表（`domain/address_area.py`）から引く。
"""

from typing import Annotated, Literal

from pydantic import StringConstraints

from app.domain.geo import Latitude, Longitude
from app.domain.strict_model import StrictModel

#: 候補の種類。
PlaceKind = Literal["address", "facility"]
PLACE_KIND_LABELS: dict[PlaceKind, str] = {"address": "住所", "facility": "施設"}

#: 当たった段（粗い→細かい）。`point`の前までが住所の区画の段（`domain/address_area.py: ADDRESS_AREA_LEVELS`）。
#: 最後の`point`は施設そのものの点（範囲の代表点ではない）。
PlaceMatchLevel = Literal["prefecture", "city", "ward", "oaza", "aza", "point"]
PLACE_MATCH_LEVEL_LABELS: dict[PlaceMatchLevel, str] = {
    "prefecture": "都道府県",
    "city": "市区町村",
    "ward": "区",
    "oaza": "大字・町",
    "aza": "字・丁目",
    "point": "地点",
}

#: 入力の長さの上限。住所の1行（都道府県から号まで・建物名つき）が収まる長さ。
PLACE_QUERY_MAX_LENGTH = 100
PlaceQuery = Annotated[str, StringConstraints(min_length=1, max_length=PLACE_QUERY_MAX_LENGTH)]

#: 入力の続き（打ちかけの語を頭に持つ住所）を候補に足す最短の長さ（空白を除いた文字数）。画面が打ちかけで引き始める
#: 長さも同じ。根拠は docs/modules/backend/place-search.md「引き方」。
PLACE_PREDICTION_MIN_LENGTH = 1
#: 住所の候補の数の上限（続きの候補を含む）。施設の候補の数の上限も同じ。
PLACE_PREDICTION_LIMIT = 10
#: 画面が、打つのが止まってから引くまでの間。打ち続けたときの1分あたりの回数の最大がこれで決まり、口の回数制限
#: （`config.py: place_search_rate_limit_per_minute`）はそれに当たらないようにこの値から導く。
PLACE_PREDICTION_DELAY_SECONDS = 0.4

#: 住所の区画の表（`domain/address_area.py`）の元データの出典。アドレス・ベース・レジストリは CC BY 4.0、e-Stat の境界は
#: 政府標準利用規約（第2.0版）で、どちらも出典と加工した旨を書く（docs/architecture/data-sources.md）。
ADDRESS_AREA_ATTRIBUTIONS: tuple[str, ...] = (
    '住所: 「<a href="https://www.digital.go.jp/policies/base_registry_address/" target="_blank" rel="noreferrer">'
    "アドレス・ベース・レジストリ</a>」（デジタル庁）の町字マスター・位置参照拡張を加工して作成"
    ' (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>)',
    '住所の境界: 出典 <a href="https://www.e-stat.go.jp/" target="_blank" rel="noreferrer">政府統計の総合窓口(e-Stat)</a>。'
    "「令和2年国勢調査 小地域（町丁・字等別）境界データ」（総務省統計局）を加工して作成",
)


class PlaceCandidate(StrictModel):
    """検索の候補1件。住所なら`name`は都道府県から当たった段までをつないだ表示名で、位置はその段の代表点。
    施設なら施設の名前と、施設の位置。"""

    kind: PlaceKind
    level: PlaceMatchLevel
    name: str
    #: 施設の辺り（市区町村から字・丁目まで。「川口市元郷四丁目」）。同じ名前の店を見分ける。住所は表示名がその住所
    #: なので持たない。施設でも、立ち寄り先の表の行が辺りを持たなければ持たない（`derived_models.py: StopPlaceRow.area`）。
    area: str | None
    latitude: Latitude
    longitude: Longitude


class PlaceSearchResult(StrictModel):
    """当たった候補。並びは住所 → 施設。住所の中の並びは`infrastructure/address_search.py`、施設の中の並びは
    `infrastructure/stop_place_search.py`。入力の一部にだけ当たった住所（「小杉湯」の「小杉」）は候補にしない。
    何も当たらなければ空。"""

    candidates: list[PlaceCandidate]
