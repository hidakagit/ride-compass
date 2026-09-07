"""proj_data.py（rasterioが参照するPROJデータの固定）のテスト。"""

import os

from app.infrastructure.proj_data import pin_bundled_proj_data


def test_pins_to_a_directory_that_actually_contains_proj_db():
    pinned = pin_bundled_proj_data()

    assert pinned is not None, "rasterio同梱のproj_dataが見つからない"
    assert (pinned / "proj.db").is_file()
    assert os.environ["PROJ_DATA"] == str(pinned)
    assert os.environ["PROJ_LIB"] == str(pinned)


def test_overrides_a_foreign_proj_installation(monkeypatch):
    """別インストール（PostGIS同梱等）を指す設定が既にあっても上書きする。"""
    monkeypatch.setenv("PROJ_LIB", r"C:\somewhere\else\proj")
    monkeypatch.delenv("PROJ_DATA", raising=False)

    pinned = pin_bundled_proj_data()

    assert os.environ["PROJ_LIB"] == str(pinned)
    assert os.environ["PROJ_DATA"] == str(pinned)


def test_resolved_crs_uses_the_pinned_database():
    """固定したデータベースでEPSGが解決できる（固定しないと実行機によっては失敗する）。"""
    pin_bundled_proj_data()
    from rasterio.crs import CRS

    assert CRS.from_epsg(4326).to_epsg() == 4326
