"""配布の住所の辞書（`jageocoder`用、街区まで）を手元で引く。

辞書は`scripts/fetch_address_dictionary.py`が配布元から取って`DICTIONARY_DIR`へ入れ、backendは開いて引くだけにする。
置き場の名前は配布のファイル名（`domain/place_search.py: ADDRESS_DICTIONARY_URL`）から導く——版を上げたコードは
古い版の辞書を開かない。

辞書のsqliteの接続は開いたスレッドでしか使えないため、1回の検索ごとに同じスレッドの中で開いて引く
（開くのは1ms前後）。開いた辞書を持ち越さない。

入力の続き（打ちかけの語を頭に持つ住所）は、辞書の索引（大字の段までの標準化した表記のトライ）の前方一致で引く。
範囲で絞りながら引くので、対象範囲を受けて範囲の外の候補をここで落とす。
"""

import asyncio
from dataclasses import dataclass
from itertools import groupby, islice
from operator import itemgetter
from pathlib import Path

from jageocoder.address import AddressLevel
from jageocoder.exceptions import AddressTreeException
from jageocoder.node import AddressNode
from jageocoder.tree import AddressTree

from app.domain.place_search import (
    ADDRESS_DICTIONARY_URL,
    PLACE_PREDICTION_LIMIT,
    PLACE_PREDICTION_MIN_LENGTH,
    PlaceCandidate,
    PlaceMatchLevel,
)
from app.domain.region import BoundingBox
from app.infrastructure.debug_log import log_throttled_warning

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "address_dictionary"
DICTIONARY_DIR = DATA_DIR / ADDRESS_DICTIONARY_URL.rsplit("/", 1)[1].removesuffix(".zip")

#: 辞書の段 → 候補の段。
_LEVELS: dict[int, PlaceMatchLevel] = {
    AddressLevel.PREF: "prefecture",
    AddressLevel.COUNTY: "county",
    AddressLevel.CITY: "city",
    AddressLevel.WARD: "ward",
    AddressLevel.OAZA: "oaza",
    AddressLevel.AZA: "aza",
    AddressLevel.BLOCK: "block",
    AddressLevel.BLD: "building",
}

#: 今は無い区画も持つデータセット（節の`priority`。辞書の`dataset`の表の0: 住所変更履歴、1: 歴史的行政区域データセット）。
#: ほかのデータセット（位置参照情報・Geolonia 住所データ）は今の住所だけを持つ。
_HISTORICAL_DATASETS = frozenset({0, 1})

#: 続きを引くときに見る節の数の上限。範囲の外ばかりに当たる語でも、見る節を区切って時間を抑える。
_PREDICTION_SCAN_LIMIT = 500


@dataclass(frozen=True)
class AddressMatches:
    """当たった住所（どちらも当たりの良い順）。入力の全部に当たったもの（続きを含む）と、入力の一部にだけ当たったもの。
    施設の候補は2つの間に並ぶ（`domain/place_search.py: PlaceSearchResult`）。"""

    whole: list[PlaceCandidate]
    partial: list[PlaceCandidate]


class AddressDictionaryUnavailableError(Exception):
    """辞書を開けない（まだ取っていない・取り損ねた）。何も当たらなかったのとは別の事実。"""


def open_dictionary(path: Path) -> AddressTree:
    """辞書を読むだけで開く。開いた辞書は、開いたスレッドの中でだけ引ける。"""
    try:
        return AddressTree(db_dir=path, mode="r")
    except AddressTreeException as exc:
        raise AddressDictionaryUnavailableError from exc


def _has_postcode(node: AddressNode) -> bool:
    return any(key == "postcode" for key, _ in node.get_notes())


def _is_current_division(node: AddressNode) -> bool:
    """市区町村の段までの節が今の区画か。

    この段の節は歴史的行政区域データセットの名前の1件ずつから作られ、廃止の日を持ち越さないので、今は無い区画も`ref:`を
    持たずに今の区画と並ぶ（東京府渋谷区等。辞書を作る`jageocoder-converter`の`city_converter.py`）。今の区画にだけ付くものは
    2つある: 郵便番号（今の郵便番号データに、そのJISコードの今の名前で載る区画に付く）と、今の住所だけを持つデータセットの
    子の節。政令市・郡・都道府県は郵便番号を持たず子の区・市区町村が持ち、郵便番号の無い島の村は子の大字が今の住所の
    データから来る。"""
    return _has_postcode(node) or any(
        child.priority not in _HISTORICAL_DATASETS or _has_postcode(child) for child in node.iter_children()
    )


def _current_nodes(tree: AddressTree, node: AddressNode) -> list[AddressNode]:
    """旧い行政区画の節（合併で無くなった市の住所等）を、注記`ref:`が指す今の住所の節へ置き換え、`ref:`の無い今は無い
    区画は落とす。辞書は旧い名前でも引けるよう旧い節を持ち、当たりがその節で終わると旧い名前のまま返す（今の節へ
    付け替えるのは、その先の段を辿るときだけ）。

    `ref:`の行き先が大字の無い区域（名前の無い大字の節。`ref:`では`<市区町村>.`）なら、その市区町村にする——名前の無い節は
    市区町村の名前で大字の段として出て、位置も子から借りたものになる。"""
    targets = [target for key, value in node.get_notes() if key == "ref" for target in value.split("|")]
    if not targets:
        return [node] if node.level > AddressLevel.WARD or _is_current_division(node) else []
    return [
        result.node.parent if result.node.name == AddressNode.NONAME else result.node
        for target in targets
        for result in tree.searchNode(target)
        if result.matched
    ]


def _candidate(node: AddressNode) -> PlaceCandidate:
    return PlaceCandidate(
        kind="address",
        level=_LEVELS[node.level],
        name="".join(node.get_fullname()),
        area=None,
        latitude=node.y,
        longitude=node.x,
    )


def _located(node: AddressNode) -> AddressNode | None:
    """索引は位置を持たない節も指す（同じ市区町村の別の節等）。辞書の検索と同じく子の位置を借り、借りられない節は
    候補にしない（位置を持つ同じ住所の節が別にある）。"""
    if not node.has_valid_coordinate_values():
        node = node.add_dummy_coordinates()
    return node if node.has_valid_coordinate_values() else None


def _continuations(tree: AddressTree, query: str, area: BoundingBox) -> list[AddressNode]:
    """入力を頭に持つ索引の表記の節を、短い表記から（同じ長さなら粗い段から）、範囲の中の`PLACE_PREDICTION_LIMIT`件まで。

    同じ長さで粗い段を先にするのは、1文字の入力（「柏」）で同じ長さの大字（「柏下」「柏井」…）が市区町村（「柏市」）より
    先に上限を埋めないため。"""
    prefix = tree.converter.standardize(query)
    # 標準化で空になる入力（「大字」等）は、空の頭がすべての表記に当たる。
    if len(query) < PLACE_PREDICTION_MIN_LENGTH or not prefix:
        return []
    trie = tree.trie.get_trie()
    entries = (
        (len(key), node_id)
        for key in sorted(trie.iterkeys(prefix), key=lambda k: (len(k), k))
        for node_id in tree.trie_nodes.get_record(pos=trie.key_id(key)).get("nodes", [])
    )
    found: dict[int, AddressNode] = {}
    for _, same_length in groupby(islice(entries, _PREDICTION_SCAN_LIMIT), key=itemgetter(0)):
        # 段は節を読むだけで分かるので先に並べ、高くつく旧い節の置き換え（辞書の検索）は上限に達するまでだけ行う。
        for indexed in sorted((tree.get_node_by_id(node_id) for _, node_id in same_length), key=lambda n: n.level):
            for node in _current_nodes(tree, indexed):
                located = _located(node)
                if located is not None and area.contains(_candidate(located)):
                    found.setdefault(located.id, located)
            if len(found) >= PLACE_PREDICTION_LIMIT:
                return list(found.values())[:PLACE_PREDICTION_LIMIT]
    return list(found.values())


def _search(path: Path, query: str, area: BoundingBox) -> AddressMatches:
    tree = open_dictionary(path)
    whole: list[AddressNode] = []
    partial: list[AddressNode] = []
    for result in tree.searchNode(query):
        # 何も当たらない入力にも、当たった文字列が空の結果が1件返る（名前が「大字」だけの節は、標準化した名前が空で、
        # 空の索引の鍵がどの入力の頭にも当たる）。
        if not result.matched:
            continue
        (whole if len(result.matched) == len(query) else partial).extend(_current_nodes(tree, result.node))
    # 旧い節を置き換えた今の節は、同じ入力でそのまま当たっていることがあり、続きにも同じ節が出る。
    nodes: dict[int, AddressNode] = {}
    for node in [*whole, *_continuations(tree, query, area)]:
        nodes.setdefault(node.id, node)
    whole_count = len(nodes)
    for node in partial:
        nodes.setdefault(node.id, node)
    found = list(nodes.values())

    def within_area(found_nodes: list[AddressNode]) -> list[PlaceCandidate]:
        return [candidate for candidate in map(_candidate, found_nodes) if area.contains(candidate)]

    return AddressMatches(whole=within_area(found[:whole_count]), partial=within_area(found[whole_count:]))


async def search_addresses(query: str, area: BoundingBox) -> AddressMatches:
    """対象範囲の中の住所の候補。辞書を開けなければ`AddressDictionaryUnavailableError`を送出する。"""
    try:
        return await asyncio.to_thread(_search, DICTIONARY_DIR, query, area)
    except AddressDictionaryUnavailableError:
        log_throttled_warning(
            "place-search:address-dictionary",
            "住所の辞書を開けないため住所を引けません path=%s（scripts/fetch_address_dictionary.pyで取得する）",
            DICTIONARY_DIR,
        )
        raise

