"""配布の住所の辞書（`jageocoder`用、街区まで）を手元で引く。

辞書は`scripts/fetch_address_dictionary.py`が配布元から取って`DICTIONARY_DIR`へ入れ、backendは開いて引くだけにする。
置き場の名前は配布のファイル名（`domain/place_search.py: ADDRESS_DICTIONARY_URL`）から導く——版を上げたコードは
古い版の辞書を開かない。

辞書のsqliteの接続は開いたスレッドでしか使えないため、1回の検索ごとに同じスレッドの中で開いて引く
（開くのは1ms前後）。開いた辞書を持ち越さない。
"""

import asyncio
from pathlib import Path

from jageocoder.address import AddressLevel
from jageocoder.exceptions import AddressTreeException
from jageocoder.node import AddressNode
from jageocoder.tree import AddressTree

from app.domain.place_search import ADDRESS_DICTIONARY_URL, PlaceCandidate, PlaceMatchLevel
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


class AddressDictionaryUnavailableError(Exception):
    """辞書を開けない（まだ取っていない・取り損ねた）。何も当たらなかったのとは別の事実。"""


def open_dictionary(path: Path) -> AddressTree:
    """辞書を読むだけで開く。開いた辞書は、開いたスレッドの中でだけ引ける。"""
    try:
        return AddressTree(db_dir=path, mode="r")
    except AddressTreeException as exc:
        raise AddressDictionaryUnavailableError from exc


def _current_nodes(tree: AddressTree, node: AddressNode) -> list[AddressNode]:
    """旧い行政区画の節（合併で無くなった市の住所等）を、注記`ref:`が指す今の住所の節へ置き換える。辞書は旧い名前でも
    引けるよう旧い節を持ち、当たりがその節で終わると旧い名前のまま返す（今の節へ付け替えるのは、その先の段を辿るときだけ）。"""
    targets = [target for key, value in node.get_notes() if key == "ref" for target in value.split("|")]
    if not targets:
        return [node]
    return [result.node for target in targets for result in tree.searchNode(target) if result.matched]


def _search(path: Path, query: str) -> list[PlaceCandidate]:
    tree = open_dictionary(path)
    nodes: dict[int, AddressNode] = {}
    for result in tree.searchNode(query):
        # 何も当たらない入力にも、当たった文字列が空の結果が1件返る（名前が「大字」だけの節は、標準化した名前が空で、
        # 空の索引の鍵がどの入力の頭にも当たる）。
        if not result.matched:
            continue
        # 旧い節を置き換えた今の節は、同じ入力でそのまま当たっていることがある。
        for node in _current_nodes(tree, result.node):
            nodes.setdefault(node.id, node)
    return [
        PlaceCandidate(
            kind="address",
            level=_LEVELS[node.level],
            name="".join(node.get_fullname()),
            latitude=node.y,
            longitude=node.x,
        )
        for node in nodes.values()
    ]


async def search_addresses(query: str) -> list[PlaceCandidate]:
    """住所の候補（当たりの良い順）。辞書を開けなければ`AddressDictionaryUnavailableError`を送出する。"""
    try:
        return await asyncio.to_thread(_search, DICTIONARY_DIR, query)
    except AddressDictionaryUnavailableError:
        log_throttled_warning(
            "place-search:address-dictionary",
            "住所の辞書を開けないため住所を引けません path=%s（scripts/fetch_address_dictionary.pyで取得する）",
            DICTIONARY_DIR,
        )
        raise
