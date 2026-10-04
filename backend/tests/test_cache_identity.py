"""`infrastructure/cache_identity.py`——キャッシュ鍵（形の署名・配信するタイルの世代）の組み立て。

入口は`shape_digest`・`cache_identity`・`tile_version`・`is_known_tile_version`。署名の材料は
架空のdataclassとSQLで与え、本番の表・SQLの中身には踏み込まない。

ここで見ないもの:
- 道路網の置き場が署名で選ばれること → `test_road_network_store.py`
- 世代をDBから読んでTTLで持つこと → `test_derived_data_revision_service.py`
- 世代を読めなかったタイルをディスクへ残さないこと → `is_known_tile_version`を読む側（`services/region_service.py`・
  `services/accident_service.py`）の責務
"""

import dataclasses
import re

import pytest
from sqlalchemy import bindparam, text

from app.infrastructure import cache_identity
from app.infrastructure.derived_data_meta import DataRevisions


@dataclasses.dataclass
class _Columns:
    a: int
    b: float


def test_the_signature_is_a_short_hex_that_fits_a_url_and_a_directory_name():
    digest = cache_identity.shape_digest("SELECT 1")

    assert re.fullmatch(r"[0-9a-f]{12}", digest)


def test_a_dataclass_is_signed_by_its_column_names():
    @dataclasses.dataclass
    class SameNamesOtherTypes:
        a: str
        b: str = "x"

    @dataclasses.dataclass
    class RenamedColumn:
        a: int
        renamed: float

    digest = cache_identity.shape_digest(_Columns)

    assert cache_identity.shape_digest(SameNamesOtherTypes) == digest
    assert cache_identity.shape_digest(RenamedColumn) != digest


def test_changing_the_text_of_a_query_changes_the_signature():
    assert cache_identity.shape_digest(text("SELECT a FROM t")) != cache_identity.shape_digest(text("SELECT b FROM t"))


def test_a_value_bound_when_the_query_is_defined_is_part_of_the_signature():
    def query(layer: str):
        return text("SELECT :layer, :z").bindparams(bindparam("layer", value=layer))

    assert cache_identity.shape_digest(query("poi")) == cache_identity.shape_digest(query("poi"))
    assert cache_identity.shape_digest(query("poi")) != cache_identity.shape_digest(query("stop"))


def test_each_source_counts_on_its_own_and_their_boundary_is_not_lost():
    assert cache_identity.shape_digest("ab", "c") != cache_identity.shape_digest("a", "bc")
    assert cache_identity.shape_digest(_Columns, "SELECT 1") != cache_identity.shape_digest(_Columns, "SELECT 2")


def test_the_identity_is_the_revision_followed_by_the_signature():
    identity = cache_identity.cache_identity("2", "SELECT 1")

    assert identity == f"2-{cache_identity.shape_digest('SELECT 1')}"
    assert cache_identity.cache_identity("3", "SELECT 1") != identity


@pytest.mark.parametrize(("revisions", "version", "known"), [
    # 取込だけを流した（派生の世代は動かない）ときも世代が変わるよう、両方の世代を持つ。最初の派生の世代は0。
    (DataRevisions(derived=0, imported=3), "0.3-abc", True),
    (None, "x-abc", False),  # まだ読めていない
    (DataRevisions(derived=None, imported=5), "x-abc", False),  # 派生の世代の行が無い
])
def test_a_tile_version_carries_both_revisions_or_is_marked_unknown(revisions, version, known):
    assert cache_identity.tile_version(revisions, "abc") == version
    assert cache_identity.is_known_tile_version(version) is known
