"""`infrastructure/tile_cache.py`——配信パスを鍵にタイルの生バイトをディスクへ置く。

入口は`get`・`set`。置き場は`tests/conftest.py`がテストごとの一時ディレクトリへ向けてあり、
ディスクは本物を通す。ディスクが拒む場面は、置き場をファイルの下へ向けて作る。

ここで見ないもの:
- 置いたものが戻る・置いていない鍵は無い → `test_fake_tile_cache.py`（代役と同じテストを本物へ流す）
- 全消去 → `diskcache`への1行の委譲で、使う側（`test_basemap_routes.py`）が通す
- 容量の上限と退避の順 → `diskcache`が持つ（設定は宣言で、振る舞いはライブラリのもの）
- 読み書きをイベントループの外で行うこと → 呼び出し元の順序の約束で、結果に現れない
  （理由は`docs/modules/backend/static-road-attributes.md`「vector_tile.py・tile_cache.py」）
- 抑制付きWARNINGの抑制の窓 → `test_debug_log.py`
"""

import logging

from app.infrastructure import tile_cache


def test_a_disk_that_refuses_turns_reads_into_misses_and_writes_into_warnings(tmp_path, monkeypatch, caplog):
    """キャッシュに読めない・書けないことは、配信を止める理由にならない。"""
    not_a_directory = tmp_path / "file"
    not_a_directory.write_bytes(b"")
    monkeypatch.setattr(tile_cache, "CACHE_DIR", not_a_directory / "tile_cache")

    with caplog.at_level(logging.WARNING):
        tile_cache.set("a.png", b"a", "image/png")
        assert tile_cache.get("a.png") is None

    messages = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert any("write failed" in m and "a.png" in m for m in messages)
    assert any("read failed" in m and "a.png" in m for m in messages)
