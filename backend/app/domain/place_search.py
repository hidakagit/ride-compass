"""地点の検索（入力した文字列から、出発地・経由地・目的地にできる地点の候補を引く）の語彙と答えの形。

候補は種類（何から引いたか）と、当たった段（住所ならどこまで細かく当たったか）を持つ。種類を足すときは
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
PlaceKind = Literal["address"]
PLACE_KIND_LABELS: dict[PlaceKind, str] = {"address": "住所"}

#: 当たった段（粗い→細かい）。住所の辞書の段（`jageocoder.address.AddressLevel`）をそのまま名前にしたもの。
PlaceMatchLevel = Literal["prefecture", "county", "city", "ward", "oaza", "aza", "block", "building"]
PLACE_MATCH_LEVEL_LABELS: dict[PlaceMatchLevel, str] = {
    "prefecture": "都道府県",
    "county": "郡",
    "city": "市区町村",
    "ward": "区",
    "oaza": "大字・町",
    "aza": "字・丁目",
    "block": "街区・地番",
    "building": "号",
}

#: 入力の長さの上限。住所の1行（都道府県から号まで・建物名つき）が収まる長さ。
PLACE_QUERY_MAX_LENGTH = 100
PlaceQuery = Annotated[str, StringConstraints(min_length=1, max_length=PLACE_QUERY_MAX_LENGTH)]

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


class PlaceCandidate(StrictModel):
    """検索の候補1件。`name`は都道府県から当たった段までをつないだ表示名、位置はその段の代表点。"""

    kind: PlaceKind
    level: PlaceMatchLevel
    name: str
    latitude: Latitude
    longitude: Longitude


class PlaceSearchResult(StrictModel):
    """当たった候補。並びは当たりの良い順（入力のより長い部分に当たったものが先）。何も当たらなければ空。"""

    candidates: list[PlaceCandidate]


def normalize_place_query(query: str) -> str:
    """検索に渡す形。住所の辞書は空白を語の区切りとして読まず、空白から先に当たらない
    （「東京都 新宿区西新宿」が「東京都」までになる）ため、空白を除く。"""
    return _WHITESPACE.sub("", query)
