"""材料カタログ（`MATERIAL_CATALOG`）の宣言そのものに対する不変条件。

材料の**値**が元データからどう決まるかは`tests/test_material_values.py`が持つ。ここは
「材料を1つ足したときに発火する」性質だけを見る——カタログに書いてある literal を
もう一度書いて突き合わせるテストは置かない。
"""

from app.domain.material_catalog import MATERIAL_CATALOG






































# --- 改善計画T339: 汎用extractorファクトリの単体テスト。既存の簡易extractorをこれらの
# ファクトリへ置き換えた際の振る舞い不変性は、上記の各材料テスト・
# test_all_cataloged_extractors_run_without_error_on_minimal_and_missing_contextが
# 既に間接的に担保している。ここではファクトリ自体を材料から独立して検証する。


















def test_all_materials_have_a_non_empty_description():
    # 改善計画T345: 軸スタジオの情報アイコンが表示する説明文。display_only材料
    # 登録済みの全材料が空でない説明文を持つことを確認する（新規材料追加時に
    # description記入漏れを検知する）。
    for spec in MATERIAL_CATALOG.values():
        assert spec.description.strip() != "", f"{spec.material_id} has no description"




def test_value_label_falls_back_to_the_raw_value_for_unknown_values():
    # 改善計画T345さらなるフォローアップ2: 「論理名 - 物理名」形式で返す
    # （例: "住宅街の道路 - residential"）。
    highway = MATERIAL_CATALOG["highway"]
    assert highway.value_label("residential") == "住宅街の道路 - residential"
    # 対訳表に無い値（論理名が無い）は物理名のみ、" - "は付かない。
    assert highway.value_label("some_new_osm_value") == "some_new_osm_value"

    # value_labelsを持たない材料（例: gradient_percent）は常にvalueそのまま。
    gradient = MATERIAL_CATALOG["gradient_percent"]
    assert gradient.value_labels == {}
    assert gradient.value_label("anything") == "anything"


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


def test_all_reference_points_have_non_empty_label_and_finite_value():
    # 新規材料追加時に参考点のlabel空文字・非有限値(NaN/inf)混入を検知する。
    import math

    for spec in MATERIAL_CATALOG.values():
        for point in spec.reference_points:
            assert point.label.strip() != "", f"{spec.material_id} has a reference point with empty label"
            assert math.isfinite(point.value), f"{spec.material_id} has a non-finite reference point value"


def test_full_label_combines_label_and_material_id():
    # 改善計画T345さらなるフォローアップ2: 材料名も値と同じ「論理名 - 物理名」形式
    # （例: "道路種別 - highway"）で軸スタジオへ返す（full_labelはGET /api/material-catalogの
    # labelフィールドが使う）。
    highway = MATERIAL_CATALOG["highway"]
    assert highway.full_label() == "道路種別 - highway"
