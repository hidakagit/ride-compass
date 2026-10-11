"""取込（`ingest.ingest_source`）が、入力（読むファイルの中身・プロファイルの宣言・アダプタのコード）がそのソースの
成功した最新の取込と同じなら取り込まず、そのrunを残すこと。

入力を宣言する本物のアダプタ（`bunka_heritages`。手元の1行1件の JSON を読む）を、このテストだけのソースの名前で通す。
置き場（`bunka_heritages.DATA_DIR`）とコードの置き場（`code_fingerprint.ROOT`）は一時ディレクトリへ移す。

ここで見ないもの:
- 指紋がどのモジュールをたどるか → `test_code_fingerprint.py`
- アダプタごとに、読むファイルを漏れなく挙げているか → 挙げ漏れたファイルは指紋に入らないが、どのアダプタも行を読む
  関数と同じ導き方（同じ関数）でファイルを挙げる
"""

import json
import os
import shutil
from dataclasses import replace

import pytest
import pytest_asyncio

from app.batch import code_fingerprint
from app.batch.ingest import ingest_source, partition_table_name
from app.batch.source_adapters import bunka_heritages
from app.batch.source_profile import NoFields, SourceProfile, SourceSpec, load_source_profile
from tests.conftest import raw_connection

pytestmark = pytest.mark.asyncio(loop_scope="module")

SOURCE = "ingest_unchanged_probe"
ROWS = bunka_heritages.BunkaHeritageRows(snapshot="2026-10-08", designations=["重要文化財"])


def _profile(rows: bunka_heritages.BunkaHeritageRows = ROWS) -> SourceProfile:
    return replace(load_source_profile(None), sources=(
        SourceSpec(name=SOURCE, adapter="bunka_heritages", rows=rows, grid=NoFields()),))


def _line(item_id: str) -> str:
    item = {"id": item_id, "common": {"title": item_id, "coordinates": {"lat": 35.65, "lon": 139.70}},
            "bunka-11-s": "重要文化財"}
    return json.dumps(item, ensure_ascii=False) + "\n"


@pytest_asyncio.fixture(loop_scope="module")
async def conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため。"""
    async with raw_connection() as connection:
        try:
            yield connection
        finally:
            await connection.execute(f'DROP TABLE IF EXISTS "{partition_table_name(SOURCE)}"')
            await connection.execute("DELETE FROM source_runs WHERE source = $1", SOURCE)


@pytest.fixture
def heritages(monkeypatch, tmp_path):
    """取込が読む一覧のファイル。中身は`bunka-1`の1件。"""
    monkeypatch.setattr(bunka_heritages, "DATA_DIR", tmp_path / "bunka")
    path = bunka_heritages.heritages_path(ROWS.snapshot)
    path.parent.mkdir()
    path.write_text(_line("bunka-1"), encoding="utf-8")
    return path


@pytest.fixture
def code_root(monkeypatch, tmp_path):
    """指紋が読むコードの写し。写しを書き換えると、コードを直したことになる。"""
    root = tmp_path / "code"
    shutil.copytree(code_fingerprint.ROOT / "app", root / "app", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(code_fingerprint, "ROOT", root)
    return root


async def _runs(conn) -> list[tuple[int, str]]:
    rows = await conn.fetch("SELECT run_id, status FROM source_runs WHERE source = $1 ORDER BY run_id", SOURCE)
    return [(row["run_id"], row["status"]) for row in rows]


async def _rows(conn) -> list[tuple[str, int]]:
    rows = await conn.fetch(f'SELECT natural_key, run_id FROM "{partition_table_name(SOURCE)}" ORDER BY natural_key')
    return [(row["natural_key"], row["run_id"]) for row in rows]


async def test_ingesting_the_same_inputs_again_keeps_the_previous_run(conn, heritages, code_root):
    first = await ingest_source(conn, _profile(), SOURCE)

    assert await ingest_source(conn, _profile(), SOURCE) == first
    assert await _runs(conn) == [(first, "succeeded")]
    assert await _rows(conn) == [("bunka-1", first)]


async def test_a_changed_byte_with_the_same_size_and_time_is_ingested(conn, heritages, code_root):
    first = await ingest_source(conn, _profile(), SOURCE)
    stat = heritages.stat()
    heritages.write_text(_line("bunka-2"), encoding="utf-8")
    os.utime(heritages, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert (heritages.stat().st_size, heritages.stat().st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)

    second = await ingest_source(conn, _profile(), SOURCE)

    assert second != first
    assert await _rows(conn) == [("bunka-2", second)]


async def test_a_changed_declaration_of_the_source_is_ingested(conn, heritages, code_root):
    first = await ingest_source(conn, _profile(), SOURCE)

    second = await ingest_source(conn, _profile(replace(ROWS, designations=["重要文化財", "国宝"])), SOURCE)

    assert second != first
    assert await _runs(conn) == [(first, "succeeded"), (second, "succeeded")]


async def test_a_changed_adapter_code_is_ingested(conn, heritages, code_root):
    first = await ingest_source(conn, _profile(), SOURCE)
    adapter = code_root / "app" / "batch" / "source_adapters" / "bunka_heritages.py"
    adapter.write_text(adapter.read_text(encoding="utf-8") + "\n# 直した\n", encoding="utf-8")

    second = await ingest_source(conn, _profile(), SOURCE)

    assert second != first
    assert await _runs(conn) == [(first, "succeeded"), (second, "succeeded")]


async def test_inputs_equal_to_the_last_succeeded_run_are_not_ingested_after_a_failed_run(
        conn, heritages, code_root):
    """失敗した取込は行を残さないので、比べる相手は成功した最新の取込。"""
    first = await ingest_source(conn, _profile(), SOURCE)
    original = heritages.read_bytes()
    heritages.write_text(_line("bunka-2") + "{壊れた行\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        await ingest_source(conn, _profile(), SOURCE)
    heritages.write_bytes(original)

    assert await ingest_source(conn, _profile(), SOURCE) == first
    assert [status for _, status in await _runs(conn)] == ["succeeded", "failed"]
    assert await _rows(conn) == [("bunka-1", first)]
