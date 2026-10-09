"""`scripts/fetch_address_dictionary.py`——配布元のzipから住所の辞書を入れ、置き場へ置く。

入口は`main`（デプロイが呼ぶ）。配布元は`respx_mock`で、テストの足場が書いた小さな辞書のzipを返し、置き場は
`tests/conftest.py: address_dictionary_dir`。入れた辞書は`address_dictionary.areas`で逆引きして確かめる。
見るのは、取得から置くまで（利用条件のREADMEも一緒に置く）・置き場に今の版があれば取りに行かず他の版を消すこと・
入れた回は旧い版を残しzipを消すこと・引けない辞書を置かないこと。

ここで見ないもの:
- 一時ファイル経由の取得と、落としたものを開いて確かめる手順（`app/batch/common.py: fetch_verified`）→ 同じ手順を使う
  取得の道具のテスト（例: `test_fetch_osm_pbf.py`）
- 逆引きした辺りの名前の作り方 → `test_place_search_route.py`（施設の辺り）
"""

import io
import zipfile

from app.domain.place_search import ADDRESS_DICTIONARY_URL
from app.infrastructure import address_dictionary
from scripts import fetch_address_dictionary
from tests.address_dictionary_fixture import README, SHINJUKU_8, dictionary_archive


def test_fetches_and_places_the_dictionary_with_its_readme(address_dictionary_dir, respx_mock, tmp_path):
    respx_mock.get(ADDRESS_DICTIONARY_URL).respond(content=dictionary_archive(tmp_path))

    assert fetch_address_dictionary.main() == 0

    assert address_dictionary.areas([(SHINJUKU_8.longitude, SHINJUKU_8.latitude)]) == ["新宿区西新宿二丁目"]
    assert (address_dictionary_dir / "README.md").read_text(encoding="utf-8") == README


def test_placing_a_new_version_keeps_the_older_one_but_not_the_archive(address_dictionary_dir, respx_mock, tmp_path):
    """デプロイは旧いコンテナを止める前に流すので、入れ替えまで旧いコンテナが引く旧い版は、入れた回には消さない。"""
    respx_mock.get(ADDRESS_DICTIONARY_URL).respond(content=dictionary_archive(tmp_path))
    older = address_dictionary_dir.parent / "gaiku_all_v22.older"
    older.mkdir(parents=True)

    fetch_address_dictionary.main()

    assert sorted(address_dictionary_dir.parent.iterdir()) == sorted([address_dictionary_dir, older])


def test_present_version_is_not_fetched_again_but_other_versions_are_removed(address_dictionary_dir, respx_mock):
    """置き場に今の版があれば配布元へ問い合わせない（代役に経路が無いので、問い合わせれば落ちる）。"""
    address_dictionary_dir.mkdir(parents=True)
    (address_dictionary_dir.parent / "gaiku_all_v22.older").mkdir()

    assert fetch_address_dictionary.main() == 0

    assert list(address_dictionary_dir.parent.iterdir()) == [address_dictionary_dir]


def test_an_archive_that_is_not_a_dictionary_places_nothing(address_dictionary_dir, respx_mock):
    """zipとしては開けても辞書として引けないもの（配布の誤り等）を置くと、backendは開いて引くたびに落ちる。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", README)
    respx_mock.get(ADDRESS_DICTIONARY_URL).respond(content=buffer.getvalue())

    assert fetch_address_dictionary.main() == 1

    assert not address_dictionary_dir.exists()
