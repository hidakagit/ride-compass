"""`batch/source_profile.py`——取込プロファイルの読み込み。

入口は`load_source_profile`。見るのは、どの段に書いた知らない欄も読み込みを止め、その場所を名指すこと。

ここで見ないもの:
- アダプタが`rows`/`grid`をどう解釈して取り込むか・欄の値の検査 → 各アダプタのテスト（道の種別を含まない
  条件を断るのは`test_osm_pbf.py`）
"""

from pathlib import Path

import pytest
import yaml

from app.batch.source_profile import SourceProfileError, load_source_profile


def _profile() -> dict:
    return {
        "version": 1,
        "target": {"bbox": [35.0, 139.0, 36.0, 140.0]},
        "sources": [{"name": "accident", "adapter": "npa_honhyo", "rows": {"years": [2024]}}],
    }


@pytest.mark.parametrize(
    ("add_typo", "where", "key"),
    [
        (lambda p: p.update(sorces=[]), "プロファイルの最上位", "sorces"),
        (lambda p: p["target"].update(bbx=[0, 0, 1, 1]), "target", "bbx"),
        (lambda p: p["sources"][0].update(row={"years": [2023]}), "sources[accident]", "row"),
        (lambda p: p["sources"][0]["rows"].update(year=[2023]), "sources[accident].rows", "year"),
        (lambda p: p["sources"][0].update(grid={"zoom": 14}), "sources[accident].grid", "zoom"),
    ],
)
def test_unread_key_stops_loading_and_names_where_it_is(tmp_path: Path, add_typo, where, key):
    profile = _profile()
    add_typo(profile)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")

    with pytest.raises(SourceProfileError) as excinfo:
        load_source_profile(path)

    assert str(excinfo.value).startswith(f"{where} に知らない欄があります: ['{key}']")

