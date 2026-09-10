"""ビルド時静的生成物（`frontend/src/types/generated/axis-catalog.json`）と、
リポジトリが持つ実DB像（`backend/fixtures/axis_definitions_snapshot.json`）の突き合わせ。

frontendの静的フォールバックの整合性テストは、両辺がどちらも同じ`axis-catalog.json`から
導出されており、**生成物そのものの陳腐化を検知できない**。軸スタジオで公開軸を増減して
スナップショットを更新したのに`export_openapi.py`を流し忘れると、実行時APIの取得が
終わるまで（あるいは失敗している間ずっと）frontendが古い軸集合で動く。

生成物はスナップショットのうち**公開軸だけ**を写すため、非公開の内部軸
（車ストレスの階層軸等）は対象外。
"""

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_PATH = _REPO_ROOT / "backend" / "fixtures" / "axis_definitions_snapshot.json"
_CATALOG_PATH = _REPO_ROOT / "frontend" / "src" / "types" / "generated" / "axis-catalog.json"


def _published_snapshot_axes() -> dict[str, dict]:
    rows = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))["axes"]
    definitions = [row["definition"] for row in rows]
    return {d["axis_id"]: d for d in definitions if d["is_published"]}


def _catalog() -> dict:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(not _CATALOG_PATH.exists(), reason="frontendの生成物が無い環境")
def test_catalog_axis_ids_match_the_published_snapshot_axes():
    catalog_ids = sorted(axis["axis_id"] for axis in _catalog()["axes"])
    snapshot_ids = sorted(_published_snapshot_axes())

    assert catalog_ids == snapshot_ids, (
        "axis-catalog.jsonが実DB像と食い違っている。"
        "backend/scripts/export_openapi.py → cd frontend && npm run generate:api を流すこと"
    )


@pytest.mark.skipif(not _CATALOG_PATH.exists(), reason="frontendの生成物が無い環境")
def test_catalog_preference_defaults_match_the_snapshot_default_weights():
    defaults = _catalog()["preference_defaults"]
    expected = {axis_id: d["default_weight"] for axis_id, d in _published_snapshot_axes().items()}

    assert defaults == pytest.approx(expected)


@pytest.mark.skipif(not _CATALOG_PATH.exists(), reason="frontendの生成物が無い環境")
def test_catalog_labels_match_the_snapshot():
    # ラベルは画面にそのまま出る。軸スタジオで改名したのに生成物を流し忘れると、
    # 実行時APIの取得が終わるまで古い名前が見えたままになる。
    catalog_labels = {axis["axis_id"]: axis["label"] for axis in _catalog()["axes"]}
    expected = {axis_id: d["label"] for axis_id, d in _published_snapshot_axes().items()}

    assert catalog_labels == expected
