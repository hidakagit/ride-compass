"""`infrastructure/proj_data.py`——rasterioが読むPROJデータの固定。

ここで見ないもの:
- ラスタの読み出しそのもの → `test_landcover.py`・`test_fetch_lulc_raster.py`

**rasterioの在処は差し替えて与える。** 実インストールに寄りかかると、同梱データが無い構成
（システムのGDAL/PROJへリンクしたビルド）の分岐を通せない。実物へ当てるのは末尾の1件だけで、
そこは「この環境のwheelが本当に座標系DBを同梱しているか」という別の問いを見る。
"""

import os
from pathlib import Path

import pytest

from app.infrastructure.proj_data import pin_bundled_proj_data

SENTINEL = "/somewhere/else"


class _Spec:
    def __init__(self, origin: str | None) -> None:
        self.origin = origin


@pytest.fixture
def untouched_environment(monkeypatch):
    monkeypatch.setenv("PROJ_DATA", SENTINEL)
    monkeypatch.setenv("PROJ_LIB", SENTINEL)


def _rasterio_at(monkeypatch, spec: _Spec | None) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: spec)


def test_nothing_is_pinned_when_rasterio_cannot_be_located(monkeypatch, untouched_environment):
    for spec in (None, _Spec(origin=None)):
        _rasterio_at(monkeypatch, spec)

        assert pin_bundled_proj_data() is None
        assert os.environ["PROJ_DATA"] == SENTINEL


def test_nothing_is_pinned_when_the_wheel_ships_no_bundled_data(monkeypatch, untouched_environment, tmp_path):
    """同梱データが無いビルドで空のパスを指すと、rasterioはPROJデータを一切見つけられなくなる。"""
    _rasterio_at(monkeypatch, _Spec(origin=str(tmp_path / "__init__.py")))

    assert pin_bundled_proj_data() is None
    assert os.environ["PROJ_LIB"] == SENTINEL


def test_both_variable_names_point_at_the_bundled_directory(monkeypatch, untouched_environment, tmp_path):
    """PROJ 9は`PROJ_DATA`、8以前は`PROJ_LIB`を読む。片方だけ書くと、もう片方を読む構成で
    PostGIS等が設定した別レイアウトの`proj.db`を掴む。
    """
    bundled = tmp_path / "proj_data"
    bundled.mkdir()
    _rasterio_at(monkeypatch, _Spec(origin=str(tmp_path / "__init__.py")))

    assert pin_bundled_proj_data() == bundled
    assert os.environ["PROJ_DATA"] == str(bundled)
    assert os.environ["PROJ_LIB"] == str(bundled)


def test_the_installed_rasterio_ships_a_coordinate_system_database():
    """同梱の置き場がwheelの更新で変わると、ここは黙ってNoneを返し、rasterioは他所の
    `proj.db`を掴んでEPSG解決に失敗する。
    """
    pinned = pin_bundled_proj_data()

    assert pinned is not None
    assert (Path(pinned) / "proj.db").is_file()
