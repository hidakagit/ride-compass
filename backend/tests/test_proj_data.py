"""`infrastructure/proj_data.py`——rasterioが読むPROJのデータを、rasterio同梱のものへ向ける。

入口は`pin_bundled_proj_data`。入力はインストールされたパッケージの置き場（ディスク）なので、
一時ディレクトリに`rasterio`パッケージの形を作り、importの探し先をそこへ向けて与える。
環境変数は`monkeypatch.setenv`で先に置き、テストの後に元へ戻す。

ここで見ないもの:
- rasterioのimportより先に呼ばれること → import順の約束で、`tests/conftest.py`と
  `infrastructure/landcover_raster.py`の先頭が守る。効いていることは、座標系を使う
  `test_landcover_raster.py`が本物のrasterioで通ることが示す

同梱の置き場の形を作る代わりに、インストールされた本物のrasterioへ当てる1件だけは、wheelの置き場
（`proj_data/proj.db`）が今の版でもあることを見る。rasterioは`PROJ_LIB`が無ければ自分の隣の`proj_data`を
自分で探すので、`PROJ_LIB`を置かないCIでは土地被覆のテストがこの代わりにならない。
"""

import os
import sys

import pytest

from app.infrastructure.proj_data import pin_bundled_proj_data

BEFORE = "/opt/other-app/share/proj"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """`rasterio`がまだimportされていない状態で、探し先を一時ディレクトリだけにする。"""
    monkeypatch.setenv("PROJ_LIB", BEFORE)
    monkeypatch.setenv("PROJ_DATA", BEFORE)
    for name in [m for m in sys.modules if m == "rasterio" or m.startswith("rasterio.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    return tmp_path


def test_the_data_bundled_with_rasterio_is_pinned_for_both_variable_names(installed):
    package = installed / "rasterio"
    (package / "proj_data").mkdir(parents=True)
    (package / "__init__.py").write_text("")

    pinned = pin_bundled_proj_data()

    assert pinned == package / "proj_data"
    assert os.environ["PROJ_DATA"] == os.environ["PROJ_LIB"] == str(package / "proj_data")


@pytest.mark.parametrize("layout", ["without-bundled-data", "not-installed"])
def test_without_bundled_data_the_variables_are_left_as_they_were(installed, layout):
    if layout == "without-bundled-data":
        (installed / "rasterio").mkdir()
        (installed / "rasterio" / "__init__.py").write_text("")

    assert pin_bundled_proj_data() is None
    assert os.environ["PROJ_DATA"] == os.environ["PROJ_LIB"] == BEFORE


def test_the_installed_rasterio_ships_a_coordinate_system_database(monkeypatch):
    """wheelの更新で同梱の置き場が変わると、固定は黙ってNoneを返し、別アプリが`PROJ_LIB`を置いた機械
    （本番）でrasterioが他所の`proj.db`を掴んでEPSG解決に失敗する。"""
    monkeypatch.setenv("PROJ_LIB", BEFORE)
    monkeypatch.setenv("PROJ_DATA", BEFORE)

    pinned = pin_bundled_proj_data()

    assert pinned is not None
    assert (pinned / "proj.db").is_file()
