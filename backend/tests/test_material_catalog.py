"""材料カタログ（`MATERIAL_CATALOG`）の宣言そのものに対する不変条件。

材料の**値**が元データからどう決まるかは`tests/test_material_values.py`が持つ。ここは
「材料を1つ足したときに発火する」性質だけを見る——カタログに書いてある literal を
もう一度書いて突き合わせるテストは置かない。
"""

import math

from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    CoverageExcluded,
    MaterialSpec,
)


def _spec(**overrides) -> MaterialSpec:
    """ラベル整形の検査用に組み立てる、カタログに依存しない材料。"""
    fields = {
        "material_id": "cat_a",
        "label": "テスト材料",
        "description": "テスト用",
        "dtype": "categorical",
        "coverage": CoverageExcluded(reason="テスト用"),
    }
    return MaterialSpec(**{**fields, **overrides})


def test_all_materials_have_a_non_empty_description():
    # 軸スタジオの情報アイコンが説明文を表示するため、記入漏れのまま登録できてはいけない。
    for spec in MATERIAL_CATALOG.values():
        assert spec.description.strip() != "", f"{spec.material_id} has no description"


def test_all_reference_points_have_non_empty_label_and_finite_value():
    # 新規材料追加時に参考点のlabel空文字・非有限値(NaN/inf)混入を検知する。
    for spec in MATERIAL_CATALOG.values():
        for point in spec.reference_points:
            assert point.label.strip() != "", f"{spec.material_id} has a reference point with empty label"
            assert math.isfinite(point.value), f"{spec.material_id} has a non-finite reference point value"


def test_value_label_combines_the_translation_with_the_raw_value():
    spec = _spec(value_labels={"known": "既知の値"})

    assert spec.value_label("known") == "既知の値 - known"


def test_value_label_falls_back_to_the_raw_value_for_unknown_values():
    # 対訳表に無い値は物理名のみで、" - "は付かない。
    spec = _spec(value_labels={"known": "既知の値"})

    assert spec.value_label("unlisted") == "unlisted"


def test_value_label_returns_the_raw_value_when_the_material_has_no_translations():
    spec = _spec(dtype="numeric")

    assert spec.value_labels == {}
    assert spec.value_label("anything") == "anything"


def test_full_label_combines_label_and_material_id():
    # 軸スタジオは材料名も値と同じ「論理名 - 物理名」形式で受け取る。
    spec = _spec(material_id="cat_a", label="テスト材料")

    assert spec.full_label() == "テスト材料 - cat_a"


def test_wind_drag_ratio_reference_points_match_formula():
    # 参考点はハードコード数値ではなく`wind_drag_ratio`の計算値（基準速度20km/h、小数2桁丸め）
    # でなければならない。
    from app.domain.wind import WIND_DRAG_REFERENCE_SPEED_MS, wind_drag_ratio

    v = WIND_DRAG_REFERENCE_SPEED_MS
    spec = MATERIAL_CATALOG["wind_drag_ratio"]
    scenarios = {
        "時速20km・向かい風2m/s": (2.0, 0.0),
        "時速20km・向かい風4m/s": (4.0, 0.0),
        "時速20km・向かい風8m/s": (8.0, 0.0),
        "時速20km・追い風4m/s": (4.0, 180.0),
        "時速20km・真横4m/s": (4.0, 90.0),
        "走行速度と同じ追い風": (v, 180.0),
    }
    points_by_label = {p.label: p.value for p in spec.reference_points}
    assert points_by_label.keys() == scenarios.keys()
    for label, (wind_speed_ms, wind_direction_deg) in scenarios.items():
        assert points_by_label[label] == round(wind_drag_ratio(wind_speed_ms, wind_direction_deg, 0.0, v), 2)
    assert points_by_label["走行速度と同じ追い風"] == -1.0
