"""配布の住所の辞書（`jageocoder`用、街区まで）を手元で逆引きして、施設の辺りを決める。

辞書は`scripts/fetch_address_dictionary.py`が配布元から取って`DICTIONARY_DIR`へ入れ、ここは開いて引くだけにする。
置き場の名前は配布のファイル名（`domain/place_search.py: ADDRESS_DICTIONARY_URL`）から導く——版を上げたコードは
古い版の辞書を開かない。

施設の辺り（`areas`）は、立ち寄り先の派生の段が位置を逆引きして表に入れる。逆引きの索引は辞書の置き場に書くので、
置き場を読むだけでマウントするbackendは逆引きしない。地点の検索の住所は辞書を引かず、住所の区画の表から引く
（`infrastructure/address_search.py`）。
"""

from operator import itemgetter
from pathlib import Path

from jageocoder.address import AddressLevel
from jageocoder.exceptions import AddressTreeException
from jageocoder.tree import AddressTree

from app.domain.place_search import ADDRESS_DICTIONARY_URL

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "address_dictionary"
DICTIONARY_DIR = DATA_DIR / ADDRESS_DICTIONARY_URL.rsplit("/", 1)[1].removesuffix(".zip")

#: 今は無い区画も持つデータセット（節の`priority`。辞書の`dataset`の表の0: 住所変更履歴、1: 歴史的行政区域データセット）。
#: ほかのデータセット（位置参照情報・Geolonia 住所データ）は今の住所だけを持つ。
_HISTORICAL_DATASETS = frozenset({0, 1})


class AddressDictionaryUnavailableError(Exception):
    """辞書を開けない（まだ取っていない・取り損ねた）。"""


def open_dictionary(path: Path) -> AddressTree:
    """辞書を読むだけで開く。開いた辞書は、開いたスレッドの中でだけ引ける。"""
    try:
        return AddressTree(db_dir=path, mode="r")
    except AddressTreeException as exc:
        raise AddressDictionaryUnavailableError from exc


def _area(tree: AddressTree, longitude: float, latitude: float) -> str | None:
    """位置の辺り: 位置を字・丁目の段まで逆引きし、旧い住所の節（合併で無くなった市の住所等。今の住所の節が並んで当たる）を
    除いて最も近い節の、市区町村から先の名前。名前の無い大字の節（大字の無い区域）は市区町村までになる。"""
    found = [
        result for result in tree.reverse(longitude, latitude, level=AddressLevel.AZA, as_dict=False)
        if result["candidate"].priority not in _HISTORICAL_DATASETS
    ]
    if not found:
        return None
    node = min(found, key=itemgetter("dist"))["candidate"]
    return "".join(n.get_name("") for n in node.get_parent_list() if n.level >= AddressLevel.CITY)


def areas(points: list[tuple[float, float]]) -> list[str | None]:
    """位置（経度・緯度）ごとの辺りの名前（市区町村から字・丁目まで。「川口市元郷四丁目」）。辺りの節が無ければNone。
    派生の段がスレッドで呼ぶ。辞書を開けなければ`AddressDictionaryUnavailableError`を送出する。

    逆引きの索引（`jageocoder.rtree.Index`）が置き場に無ければ、最初の1回が作って置き場へ書く（全国の辞書で数分）。
    引くたびにも索引のファイルを書き戻すので、置き場を書けるときだけ呼べる。位置が無ければ辞書を開かない——地点を
    取り込んでいないDBの作り直しに、辞書は要らない。"""
    if not points:
        return []
    tree = open_dictionary(DICTIONARY_DIR)
    return [_area(tree, longitude, latitude) for longitude, latitude in points]
