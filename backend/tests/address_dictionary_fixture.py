"""住所の辞書（`jageocoder`用）を、数件の節だけで書く足場。

配布の辞書（全国・入れて1.4GB）はテストに置けないため、配布の辞書を書くのと同じ`jageocoder`の公開の型
（節の表`AddressNodeTable`・索引`AddressTrie`・索引から節への表`TrieNode`）で小さな辞書を書き、検索は本物を通す。
節の並び（親より後に子、`siblingId`は部分木の次の節）と索引の鍵（都道府県から・市区町村から…の標準化した表記を、
大字の段まで）は配布の辞書と同じ形にしてある。

節の位置は配布の辞書（20260417版）の値。
"""

import io
import zipfile
from pathlib import Path
from typing import NamedTuple

from jageocoder.address import AddressLevel
from jageocoder.itaiji import Converter
from jageocoder.node import AddressNode, AddressNodeTable
from jageocoder.trie import AddressTrie, TrieNode


class Place(NamedTuple):
    name: str
    level: int
    longitude: float
    latitude: float
    children: tuple["Place", ...] = ()
    #: 配布の辞書の注記。旧い住所の節は`ref:<今の住所>`を持ち、今の市区町村は郵便番号（`postcode:`）を持つ。
    note: str = ""

    @property
    def priority(self) -> int:
        """配布の辞書と同じく、節の出どころのデータセットの番号（`dataset`の表）: 旧い住所の節（`ref:`）は住所変更履歴（0）、
        市区町村の段までは歴史的行政区域データセット（1）、大字から下は今の住所のデータ（Geolonia 住所データ、2）。"""
        if self.note.startswith("ref:"):
            return 0
        return 1 if self.level <= AddressLevel.WARD else 2


#: 東京都新宿区西新宿二丁目8番。
SHINJUKU_8 = Place("8番", AddressLevel.BLOCK, 139.691778, 35.689627)
NISHI_SHINJUKU = Place("西新宿", AddressLevel.OAZA, 139.697501, 35.690383, (
    Place("二丁目", AddressLevel.AZA, 139.691774, 35.68945, (SHINJUKU_8,)),
))
#: 同じ名前の大字が関東（渋谷区本町）と関東の外（大阪市中央区本町）にある。
SHIBUYA_HONMACHI = Place("本町", AddressLevel.OAZA, 139.683187, 35.680992)
OSAKA_HONMACHI = Place("本町", AddressLevel.OAZA, 135.50814, 34.683563)
#: 合併で無くなった市の大字（埼玉県岩槻市本町）と、今の住所の大字（埼玉県さいたま市岩槻区本町）。位置は同じ。
IWATSUKI_HONMACHI = Place("本町", AddressLevel.OAZA, 139.693159, 35.947813)
FORMER_IWATSUKI_HONMACHI = Place("本町", AddressLevel.OAZA, 139.693159, 35.947813, note="ref:埼玉県さいたま市岩槻区本町")
#: 名前が「大字」だけの大字（埼玉県川口市大字）。名前を標準化すると空になり、索引の鍵も空の文字列になるので、配布の辞書と
#: 同じく、何も当たらない入力にも当たった文字列が空の結果として返る。
KAWAGUCHI_OAZA = Place("大字", AddressLevel.OAZA, 139.741148, 35.862285)

PLACES = (
    Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (
        Place("新宿区", AddressLevel.CITY, 139.703463, 35.69389, (NISHI_SHINJUKU,), "postcode:1600000"),
        Place("渋谷区", AddressLevel.CITY, 139.697948, 35.663982, (SHIBUYA_HONMACHI,), "postcode:1500000"),
    )),
    Place("埼玉県", AddressLevel.PREF, 139.649, 35.85736, (
        Place("さいたま市", AddressLevel.CITY, 139.645502, 35.861515, (
            Place("岩槻区", AddressLevel.WARD, 139.694182, 35.949882, (IWATSUKI_HONMACHI,), "postcode:3390000"),
        )),
        Place("岩槻市", AddressLevel.CITY, 139.694182, 35.949882, (FORMER_IWATSUKI_HONMACHI,)),
        Place("川口市", AddressLevel.CITY, 139.724171, 35.807741, (KAWAGUCHI_OAZA,), "postcode:3320000"),
    )),
    Place("大阪府", AddressLevel.PREF, 135.51931, 34.68692, (
        Place("大阪市", AddressLevel.CITY, 135.502046, 34.693891, (
            Place("中央区", AddressLevel.WARD, 135.509687, 34.681225, (OSAKA_HONMACHI,), "postcode:5390000"),
        )),
    )),
)

#: 配布の辞書に同梱される利用条件の代わり。
README = "jageocoder 用住所データベース利用規約（テスト）\n"


def write_dictionary(path: Path, places: tuple[Place, ...] = PLACES) -> None:
    """`path`（無いディレクトリ）へ辞書を書く。"""
    path.mkdir(parents=True)
    converter = Converter()
    records = [AddressNode.root().to_record()]
    keys: dict[str, list[int]] = {}

    def add(place: Place, parent_id: int, ancestors: list[str]) -> None:
        record = AddressNode(
            id=len(records), name=place.name, name_index=converter.standardize(place.name),
            x=place.longitude, y=place.latitude, level=place.level, priority=place.priority,
            note=place.note, parent_id=parent_id,
        ).to_record()
        records.append(record)
        names = [*ancestors, place.name]
        if place.level <= AddressLevel.OAZA:
            for start in range(len(names)):
                keys.setdefault(converter.standardize("".join(names[start:])), []).append(record["id"])
        for child in place.children:
            add(child, record["id"], names)
        record["siblingId"] = len(records)

    for place in places:
        add(place, 0, [])
    records[0]["siblingId"] = len(records)

    nodes = AddressNodeTable(db_dir=path)
    nodes.create()
    nodes.append_records(records)
    nodes.create_indexes()
    trie = AddressTrie(path / "address.trie", {key: True for key in keys})
    trie.save()
    trie_nodes = TrieNode(db_dir=path)
    trie_nodes.create()
    trie_nodes.append_records(
        sorted(({"id": trie.get_id(key), "nodes": ids} for key, ids in keys.items()), key=lambda r: r["id"])
    )
    # 書くときに開いた SQLite の接続は、jageocoder の関数のキャッシュ（`lru_cache`）が表を握ったまま残す。後で別のスレッド
    # （辞書を引くスレッド）でキャッシュから押し出されて片付けられると、閉じるときに`sqlite3.ProgrammingError`になるので、
    # 書いたスレッドで閉じる。
    for table in (nodes, trie_nodes):
        if table.conn:
            table.conn.close()
            table.conn = None
    (path / "README.md").write_text(README, encoding="utf-8")


def dictionary_archive(work_dir: Path) -> bytes:
    """配布と同じ形のzip（辞書のファイルとREADMEを、ディレクトリを挟まずに並べたもの）。"""
    source = work_dir / "dictionary"
    write_dictionary(source)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for file in sorted(source.iterdir()):
            archive.write(file, file.name)
    return buffer.getvalue()
