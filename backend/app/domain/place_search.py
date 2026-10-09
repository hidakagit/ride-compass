"""地点の検索（入力した文字列から、出発地・経由地・目的地にできる地点の候補を引く）の語彙と答えの形。

候補は種類（何から引いたか。住所の辞書か、立ち寄り先の表の施設か）と、当たった段（住所ならどこまで細かく当たったか。
施設は施設そのものの点）を持つ。種類を足すときは
`PlaceKind`と`PLACE_KIND_LABELS`へ1つずつ足し、口と答えの形は変えない。表示名は語彙と同じ並びで
生成物（`vocabulary.ts`）が画面へ届ける。

住所は配布の住所の辞書（`jageocoder`用、街区まで）を本番のbackendの手元で引く。辞書の版は
`ADDRESS_DICTIONARY_URL`のファイル名で決まり、出典の文言はその版に同梱のREADMEが求めるもの。
版を上げるときは同梱のREADMEの文言を読み直して`ADDRESS_DICTIONARY_ATTRIBUTION`を合わせる（手順は
docs/architecture/data-sources.md「版を持つ配布物の入れ替え」）。
"""

import re
from typing import Annotated, Literal

from pydantic import StringConstraints

from app.domain.geo import Latitude, Longitude
from app.domain.strict_model import StrictModel

#: 候補の種類。
PlaceKind = Literal["address", "facility"]
PLACE_KIND_LABELS: dict[PlaceKind, str] = {"address": "住所", "facility": "施設"}

#: 当たった段（粗い→細かい）。住所の段は住所の辞書の段（`jageocoder.address.AddressLevel`）をそのまま名前にしたもの。
#: 最後の`point`は施設そのものの点（範囲の代表点ではない）。
PlaceMatchLevel = Literal["prefecture", "county", "city", "ward", "oaza", "aza", "block", "building", "point"]
PLACE_MATCH_LEVEL_LABELS: dict[PlaceMatchLevel, str] = {
    "prefecture": "都道府県",
    "county": "郡",
    "city": "市区町村",
    "ward": "区",
    "oaza": "大字・町",
    "aza": "字・丁目",
    "block": "街区・地番",
    "building": "号",
    "point": "地点",
}

#: 入力の長さの上限。住所の1行（都道府県から号まで・建物名つき）が収まる長さ。
PLACE_QUERY_MAX_LENGTH = 100
PlaceQuery = Annotated[str, StringConstraints(min_length=1, max_length=PLACE_QUERY_MAX_LENGTH)]

#: 入力の続き（打ちかけの語を頭に持つ住所）を候補に足す最短の長さ（空白を除いた文字数）。画面が打ちかけで引き始める
#: 長さも同じ。根拠は docs/modules/backend/place-search.md「引き方」。
PLACE_PREDICTION_MIN_LENGTH = 1
#: 足す続きの候補の数の上限。施設の候補の数の上限も同じ。
PLACE_PREDICTION_LIMIT = 10
#: 画面が、打つのが止まってから引くまでの間。打ち続けたときの1分あたりの回数の最大がこれで決まり、口の回数制限
#: （`config.py: place_search_rate_limit_per_minute`）はそれに当たらないようにこの値から導く。
PLACE_PREDICTION_DELAY_SECONDS = 0.4

_WHITESPACE = re.compile(r"\s")

#: 住所の辞書の配布（街区まで・全国）。配布の一覧は https://www.info-proto.com/static/jageocoder/ にある。
ADDRESS_DICTIONARY_URL = "https://www.info-proto.com/static/jageocoder/20260417/v2/gaiku_all_v22.20260417.zip"
#: 同梱のREADMEが「利用者から見えるところ」に書くよう求める文言。
ADDRESS_DICTIONARY_ATTRIBUTION = (
    "「位置参照情報（大字町丁目・街区レベル）令和6年」（国土交通省）、"
    '「Geolonia 住所データ」（株式会社Geolonia） <a href="https://geolonia.github.io/japanese-addresses/"'
    ' target="_blank" rel="noreferrer">https://geolonia.github.io/japanese-addresses/</a>、'
    "「アドレス・ベース・レジストリ」（デジタル庁） "
    '<a href="https://www.digital.go.jp/policies/base_registry_address_tos/" target="_blank" rel="noreferrer">'
    "https://www.digital.go.jp/policies/base_registry_address_tos/</a> "
    "をもとに、株式会社情報試作室が加工した jageocoder 用住所データベース（街区レベル）を利用"
)

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
    """当たった候補。並びは当たりの良い順で、入力の全部に当たった住所（続きを含む）→ 施設 → 入力の一部にだけ当たった
    住所。住所は入力のより長い部分に当たったものが先で、入力の続きは入力の全部に当たったものとして数え、入力の全部に
    当たった住所の後に短い表記から（同じ長さなら粗い段から）並ぶ。施設の中の並びは`infrastructure/stop_place_search.py`。
    何も当たらなければ空。"""

    candidates: list[PlaceCandidate]


def normalize_place_query(query: str) -> str:
    """検索に渡す形。住所の辞書は空白を語の区切りとして読まず、空白から先に当たらない
    （「東京都 新宿区西新宿」が「東京都」までになる）ため、空白を除く。"""
    return _WHITESPACE.sub("", query)
