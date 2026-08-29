"""registry_defaults.register_defaults()（既存の一次属性・二次軸の既定登録）が、
コード変更なしに実行できること・排他検証を通ることを確認する（改善計画T137）。
"""

import pytest

from app.domain import registry
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.axis_display import derive_ramp_inputs
from app.domain.registry_defaults import register_defaults

# 改善計画T350: register_defaults()は呼び出し時点のAXIS_DEFINITIONSをそのまま走査するため、
# 本番相当の14軸が必要（tests/realistic_axis_fixtures.py参照）。tests/conftest.pyの
# セッションスコープautouseフィクスチャが全テスト共通で用意する。


@pytest.fixture(autouse=True)
def _defaults_registered():
    registry.reset_registry_for_testing()
    register_defaults()
    yield
    registry.reset_registry_for_testing()


def _axis(axis_id: str):
    """`registry.get_axis`相当（単体取得関数は死コード監査で削除済み、テストローカルに
    `all_axes()`から引く形へ置き換える）。"""
    return next(axis for axis in registry.all_axes() if axis.axis_id == axis_id)


def _primary_attribute(attr_id: str):
    """`registry.get_primary_attribute`相当（同上）。"""
    return next(attr for attr in registry.all_primary_attributes() if attr.attr_id == attr_id)


def test_default_primary_attributes_are_registered():
    attr_ids = {attr.attr_id for attr in registry.all_primary_attributes()}
    assert {
        "highway",
        "lanes",
        "maxspeed",
        "cycleway",
        "surface",
        "bicycle_access",
        "motor_vehicle_access",
        "lit",
        "tunnel",
        "designation",
        "elevation",
        "stop_poi",
        "supply_poi",
        "accident_point",
        "intersection",
        "geometry",
    }.issubset(attr_ids)


def test_default_axes_are_registered_without_conflict():
    # 改善計画T320: _register_axes()はAXIS_DEFINITIONSの公開軸すべてを走査して登録する
    # ため、windも含む（以前は本ファイルへの手書き登録から意図的に除外していたが、
    # GET /api/axis-catalogという実行時APIは元々windも含めて返しており、静的生成物
    # だけが取り残されていた不整合を解消した）。改善計画T347: bicycle_infra_qualityが
    # 公開軸として加わった。
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids == {
        "gradient", "wind", "surface_q", "stop_density", "accident", "car_stress", "night",
        "bicycle_infra_quality",
    }


def test_intersection_density_is_not_a_standalone_axis():
    """交差点密度は単独軸を持たず、stop_density軸のinputsへ吸収する
    （設計プロンプト改訂2026-08-18「現行9軸からの帰属先」、改善計画T149で実装済み）。"""
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert "intersection_density" not in axis_ids
    assert _axis("stop_density").inputs == ["stop_poi", "intersection"]


def test_safety_and_bicycle_infra_axes_are_deliberately_not_registered():
    """安全度（旧`domain/safety.py`）は難易度合成からT139で外れ、そもそも軸として登録した
    ことがなく、T148で`domain/safety.py`自体も削除済み。自転車インフラはT138でcar_stressへ
    統合済みのため独立軸を持たない（モジュールdocstring参照）。"""
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids.isdisjoint({"traffic_stress", "safety", "bicycle_infra"})


def test_cycleway_axis_input_belongs_exclusively_to_bicycle_infra_quality():
    # 改善計画T353: car_stress内部軸car_stress_bicycle_infra_adjustment（1材料1軸原則
    # T268違反のため廃止）を経由してcar_stressが間接的に持っていたcycleway系材料は、
    # bicycle_infra_quality公開軸だけが直接持つ形に一本化された。car_stress自体は
    # 自転車インフラの有無に一切影響されなくなったため、cyclewayという一次属性の入力元は
    # bicycle_infra_qualityのみに戻った（改善計画T347時点の「両軸が共有」という前提は
    # 本タスクで解消）。
    car_stress_axis = _axis("car_stress")
    bicycle_infra_quality_axis = _axis("bicycle_infra_quality")
    assert "cycleway" not in car_stress_axis.inputs
    assert "cycleway" in bicycle_infra_quality_axis.inputs
    for axis in registry.all_axes():
        if axis.axis_id != "bicycle_infra_quality":
            assert "cycleway" not in axis.inputs


def test_night_axis_inputs_are_lit_and_tunnel():
    night_axis = _axis("night")
    assert set(night_axis.inputs) == {"lit", "tunnel"}


def test_accident_axis_input_is_exclusively_accident_point():
    accident_axis = _axis("accident")
    assert accident_axis.inputs == ["accident_point"]


def test_supply_poi_is_registered_but_used_by_no_axis():
    assert _primary_attribute("supply_poi") is not None
    for axis in registry.all_axes():
        assert "supply_poi" not in axis.inputs


def test_register_defaults_is_idempotent_guarded():
    """2回連続で呼ぶと(register_primary_attributeが)ValueErrorを送出する
    （二重登録によるレジストリ不整合を防ぐ、モジュールdocstring参照）。"""
    with pytest.raises(ValueError, match="already registered"):
        register_defaults()


def test_car_stress_axis_includes_motor_vehicle_access():
    """car_stress_level（domain/traffic.py）はmotor_vehicle=noを他の補正に関わらず1固定に
    する分岐でmotor_vehicle_accessを実際に消費しているが、登録軸のinputsには記載が
    無かった（排他違反ではないが不完全）。地図レイヤー階層の次数反転検討（改善計画T163）で
    発覚し追加した。"""
    car_stress_axis = _axis("car_stress")
    assert "motor_vehicle_access" in car_stress_axis.inputs
    for axis in registry.all_axes():
        if axis.axis_id != "car_stress":
            assert "motor_vehicle_access" not in axis.inputs


def test_all_primary_attributes_have_non_empty_labels():
    """一次属性の正式名（label、改善計画T163）は地図チップ・サイドバー・研究タブが表示する
    「観測データ」側の名称の単一ソース。pydanticのrequired制約は空文字を通すため、
    ここで機械的に空でないことを確認する。"""
    for attr in registry.all_primary_attributes():
        assert attr.label.strip() != "", f"{attr.attr_id} has empty label"


def test_registry_axis_display_labels_match_axis_definitions():
    """registry_defaults.pyのAxisDisplaySpec.labelは、domain/axis_definitions.py:
    AXIS_DEFINITIONS[axis_id].label（T269でDB化・軸スタジオでGUI編集可能になった方）を
    参照する形に統合済み（改善計画T270フォローアップ、2026-08-24）。以前は同じ文字列を
    2箇所で独立して手書きしており、片方だけ変更しても気づかない重複だった。この参照が
    将来また手書きの別文字列へ差し戻されないことを機械的に確認する。
    """
    for axis in registry.all_axes():
        assert axis.display is not None
        assert axis.display.label == AXIS_DEFINITIONS[axis.axis_id].label


def test_surface_q_and_night_kind_is_auto_derived_ramp():
    """改善計画T278: surface_q（従来kind="none"、既存の道路情報レイヤーとの重複を理由に
    手書き固定していた）・night（従来kind="bespoke"、専用expression未登録のためレイヤー
    非生成だった）は、ユーザー判断（2026-08-24、「ramp化技術的に可能な軸は一律ramp、
    重複回避はUI層で運用」）によりkind="ramp"の自動導出表示へ変わった。
    tile_inputs/thresholdsがdomain/axis_display.py: derive_ramp_inputsの出力と
    完全一致することも確認し、手書きの値が自動導出結果から差し戻されないようにする。
    """
    for axis_id in ("surface_q", "night"):
        axis = _axis(axis_id)
        assert axis.display is not None
        assert axis.display.kind == "ramp"
        ramp = derive_ramp_inputs(AXIS_DEFINITIONS[axis_id])
        assert ramp is not None
        assert axis.display.tile_inputs == ramp.tile_inputs
        assert axis.display.thresholds == ramp.thresholds


def test_gradient_stop_density_car_stress_accident_kind_unchanged_by_t278():
    """改善計画T278・T404の自動導出対象外/対象の境界回帰防止テスト。gradientは
    方向依存材料（gradient_percent）のためkind="none"のまま変わらない。stop_density/
    accidentは改善計画T404でderive_ramp_inputsの自動導出対象になった（実行時スケール
    変換が必要な材料も含むよう緩和、tests/realistic_axis_fixtures.py参照）が、色分けの
    段階自体はdisplay_thresholds_override（軽量な数値配列の上書き）で従来と同じ細かさを
    保つ。car_stressは改善計画T292で"bespoke"から"ramp"へ変更されたため、本テストの
    対象からは外し専用テスト（test_car_stress_ramp_display）で検証する。"""
    assert _axis("gradient").display.kind == "none"
    assert _axis("stop_density").display.kind == "ramp"
    assert _axis("stop_density").display.thresholds == [1.0, 2.0, 4.0]
    assert _axis("accident").display.kind == "ramp"
    # 改善計画T404: 旧display_override時代の閾値[0.4, 0.8, 1.5]はタイル生値（年正規化前、
    # 収録3年分）のスケールだった。derive_ramp_inputsの自動導出＋display_thresholds_
    # overrideは材料スケール（年正規化後）で表現するため、収録年数3で割った値になる
    # （tests/realistic_axis_fixtures.py参照、本番DBの実際の移行値と同じ）。
    assert _axis("accident").display.thresholds == [0.133, 0.267, 0.5]


def test_car_stress_ramp_display():
    """改善計画T292: car_stressは内部軸5つ+公開軸1つの階層構造への再実装に伴い
    kind="bespoke"からkind="ramp"へ変更した。改善計画T404: derive_ramp_inputsが
    軸参照を再帰的に解決してtile_inputsを自動導出できるようになった
    （_resolve_referenced_axis_tile_input参照、旧・本ファイルへ直接手書きしていた
    display_overrideは廃止しdisplay_thresholds_overrideへ移行済み）。内部軸5つぶんの
    tile_inputsが揃っていることを確認する。"""
    display = _axis("car_stress").display
    assert display.kind == "ramp"
    assert display.thresholds == [2.0, 3.0, 4.0]
    properties = {ti.property for ti in display.tile_inputs}
    # 改善計画T347: bicycle_infraタイルプロパティ自体を削除したため6→5材料へ。
    assert properties == {"highway", "maxspeed_kmh", "lanes_count", "designation", "motor_vehicle_no"}
    highway_input = next(ti for ti in display.tile_inputs if ti.property == "highway")
    assert highway_input.categories is not None
    assert highway_input.has_unknown_fallback is True
    maxspeed_input = next(ti for ti in display.tile_inputs if ti.property == "maxspeed_kmh")
    assert maxspeed_input.breakpoints is not None
    motor_vehicle_input = next(ti for ti in display.tile_inputs if ti.property == "motor_vehicle_no")
    assert motor_vehicle_input.boolean is True
    assert motor_vehicle_input.true_value == -1000.0


def test_register_defaults_does_not_crash_when_a_builtin_axis_is_removed(monkeypatch):
    """改善計画T320: `_register_axes()`はAXIS_DEFINITIONSをそのまま走査するだけで、
    特定のaxis_id（"gradient"等）を直接indexingしない。そのため、組み込み軸が軸スタジオで
    unpublish→削除された状態でビルド（export_openapi.py）を実行しても、以前のように
    AXIS_DEFINITIONS["gradient"]がKeyErrorでビルドごと落ちることはなく、単にその軸が
    登録対象から自然に外れるだけであることを確認する（if文で個別に存在確認する対症療法とは
    異なり、そもそも欠けている軸を名指しする必要が無い設計）。"""
    registry.reset_registry_for_testing()
    monkeypatch.delitem(AXIS_DEFINITIONS, "gradient")

    register_defaults()

    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert "gradient" not in axis_ids
    assert axis_ids == {
        "wind", "surface_q", "stop_density", "accident", "car_stress", "night", "bicycle_infra_quality",
    }


def test_registry_axis_ids_match_axis_definitions():
    """registry_defaults.py（表示カタログ用レジストリ）の登録軸集合と、
    domain/axis_definitions.pyのAXIS_DEFINITIONS（評価ロジックが実際に参照する軸定義、
    改善計画T221 Stage B/C）の軸ID集合が一致することを検証する（旧
    `_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`手書き辞書との突き合わせを置き換えた。
    統合レビュー2026-08-19 consistency F-2の「片方だけ更新しても気づかない死角」対策は
    この形で引き続き機械化する）。

    改善計画T320: `_register_axes()`がAXIS_DEFINITIONSの公開軸をそのまま走査するように
    なったため、windも含め比較対象は「公開軸すべて」で一致する（以前はwindだけ意図的に
    表示カタログから除外されていたが、GET /api/axis-catalogという実行時APIは元々windも
    含めて返しており、静的生成物側だけの片手落ちだった）。

    改善計画T292: car_stress軸を支える内部軸6つ（is_published=False、他の公開軸から
    参照される専用の推定軸）もAXIS_DEFINITIONSに含まれるが、`is_published=False`のため
    `_register_axes()`のループ自体が最初からスキップする（表示カタログ・一般ユーザー向けの
    軸選択・地図レイヤー用には登録しない、内部軸は恒久的に非公開のまま運用する設計）。

    各軸のaxis_idフィールドが辞書キーと一致することも合わせて確認する。
    """
    registry_axis_ids = {axis.axis_id for axis in registry.all_axes()}
    definition_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}
    assert definition_axis_ids == registry_axis_ids
    for axis_id, definition in AXIS_DEFINITIONS.items():
        assert definition.axis_id == axis_id
