"""配布の住所の辞書（`jageocoder`用、街区まで）の置き場と開き方。

辞書は`scripts/fetch_address_dictionary.py`が配布元から取って`DICTIONARY_DIR`へ入れ、入れた辞書を開いて引けるかを確かめる。
置き場の名前は配布のファイル名（`domain/place_search.py: ADDRESS_DICTIONARY_URL`）から導く——版を上げたコードは
古い版の辞書を開かない。地点の検索の住所も施設の辺りも辞書を引かず、住所の区画の表から引く
（`infrastructure/address_search.py`・`infrastructure/address_area_lookup.py`）。
"""

from pathlib import Path

from jageocoder.exceptions import AddressTreeException
from jageocoder.tree import AddressTree

from app.domain.place_search import ADDRESS_DICTIONARY_URL

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "address_dictionary"
DICTIONARY_DIR = DATA_DIR / ADDRESS_DICTIONARY_URL.rsplit("/", 1)[1].removesuffix(".zip")


class AddressDictionaryUnavailableError(Exception):
    """辞書を開けない（まだ取っていない・取り損ねた）。"""


def open_dictionary(path: Path) -> AddressTree:
    """辞書を読むだけで開く。開いた辞書は、開いたスレッドの中でだけ引ける。"""
    try:
        return AddressTree(db_dir=path, mode="r")
    except AddressTreeException as exc:
        raise AddressDictionaryUnavailableError from exc
