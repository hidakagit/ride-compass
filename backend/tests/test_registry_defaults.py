"""registry_defaults.register_defaults()（既存の一次属性・二次軸の既定登録）が、
コード変更なしに実行できること・排他検証を通ることを確認する（改善計画T137）。
"""

import pytest

from app.domain import registry
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.axis_display import derive_ramp_inputs
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL,
    PRIMARY_ATTRIBUTE_LABELS,
)
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


def test_primary_attributes_come_from_the_material_catalog():
    """語彙をここへ書き写さず、材料カタログから導かれることだけを見る。"""
    registered = {attr.attr_id for attr in registry.all_primary_attributes()}

    assert registered == set(PRIMARY_ATTRIBUTE_LABELS) | set(PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL)


def test_every_primary_attribute_a_material_points_to_is_registered():
    pointed = {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}
    registered = {attr.attr_id for attr in registry.all_primary_attributes()}

    assert pointed <= registered


def test_attributes_without_material_are_declared_as_such():
    """材料を持たない一次属性は、その旨の表にだけ載っている。"""
    pointed = {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}

    for attr_id in PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL:
        assert attr_id not in pointed, f"{attr_id}は材料が指しているので、材料由来の表へ移す"


def test_default_axes_are_registered_without_conflict():
    # 改善計画T320: _register_axes()はAXIS_DEFINITIONSの公開軸すべてを走査して登録する
    # ため、windも含む（以前は本ファイルへの手書き登録から意図的に除外していたが、
    # GET /api/axis-catalogという実行時APIは元々windも含めて返しており、静的生成物
    # だけが取り残されていた不整合を解消した）。改善計画T347: bicycle_infra_qualityが
    # 公開軸として加わった。
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids == {
        "gradient", "wind", "surface_q", "stop_density", "accident", "night",
        "bicycle_infra_quality", "openness",
    }


def test_intersection_density_is_not_a_standalone_axis_nor_a_stop_density_input():
    """交差点密度は単独軸を持たず、停止密度の材料でもない。

    次数3以上の分岐点を数えたもので、信号の有無とは無関係にグラフの形だけから出ている。
    T字路でも曲がれば止まり十字路でも直進なら止まらないため、「停止」の代理としては弱い。
    停止密度は種別別のPOI密度（信号・踏切・一時停止）で組み直され、交差点密度は
    その材料から外れている（docs/records/tasks/T655.md「交差点密度の扱い」）。
    """
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert "intersection_density" not in axis_ids
    assert _axis("stop_density").inputs == ["stop_poi"]


def test_safety_and_bicycle_infra_axes_are_deliberately_not_registered():
    """安全度（旧`domain/safety.py`）は難易度合成からT139で外れ、そもそも軸として登録した
    ことがなく、T148で`domain/safety.py`自体も削除済み。自転車インフラはT138で別軸へ
    統合済みのため独立軸を持たない（モジュールdocstring参照）。"""
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids.isdisjoint({"traffic_stress", "safety", "bicycle_infra"})


def test_cycleway_axis_input_belongs_exclusively_to_bicycle_infra_quality():
    bicycle_infra_quality_axis = _axis("bicycle_infra_quality")
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


def test_gradient_stop_density_accident_kind_unchanged_by_t278():
    """改善計画T278・T404の自動導出対象外/対象の境界回帰防止テスト。gradientは
    方向依存材料（gradient_percent）のためkind="none"のまま変わらない。stop_density/
    accidentは改善計画T404でderive_ramp_inputsの自動導出対象になった（実行時スケール
    変換が必要な材料も含むよう緩和、tests/realistic_axis_fixtures.py参照）が、色分けの
    段階自体はdisplay_thresholds_override（軽量な数値配列の上書き）で従来と同じ細かさを
    保つ。"""
    assert _axis("gradient").display.kind == "none"
    assert _axis("stop_density").display.kind == "ramp"
    # 上書きは[2.0, 4.0, 7.0, 12.0]だが、この軸の折れ線は5.0で100へ達するため7.0と12.0は
    # 同じ難易度になる。**評価が区別できない差に段の境界は引かない**——引くと色だけが
    # 変わってルート線側にはその段が作れず、前後で段の数が食い違う（T939、
    # `domain/axis_display.py: ramp_band_thresholds`）。
    assert _axis("stop_density").display.thresholds == [2.0, 4.0, 7.0]
    assert _axis("accident").display.kind == "ramp"
    # 改善計画T404: 旧display_override時代の閾値[0.4, 0.8, 1.5]はタイル生値（年正規化前、
    # 収録3年分）のスケールだった。derive_ramp_inputsの自動導出＋display_thresholds_
    # overrideは材料スケール（年正規化後）で表現するため、収録年数3で割った値になる
    # （tests/realistic_axis_fixtures.py参照、本番DBの実際の移行値と同じ）。
    assert _axis("accident").display.thresholds == [0.133, 0.267, 0.5]
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
        "wind", "surface_q", "stop_density", "accident", "night", "bicycle_infra_quality",
        "openness",
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

    各軸のaxis_idフィールドが辞書キーと一致することも合わせて確認する。
    """
    registry_axis_ids = {axis.axis_id for axis in registry.all_axes()}
    definition_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}
    assert definition_axis_ids == registry_axis_ids
    for axis_id, definition in AXIS_DEFINITIONS.items():
        assert definition.axis_id == axis_id


def test_no_primary_attribute_is_exempt_from_the_exclusive_check():
    # shared=Trueは排他チェックの免除で、実質的な属性を免除すると、その属性を2軸が
    # 使い始めても検査が黙る。現在この免除を受けている属性は無い。
    shared = {attr.attr_id for attr in registry.all_primary_attributes() if attr.shared}

    assert shared == set()


def test_a_second_axis_using_cycleway_is_rejected():
    # 自転車インフラの材料を2軸目が参照したら、軸スタジオでの登録が弾かれる。
    # 重ねるなら意図した判断として弾かれた側を解く必要がある、という形にしておく。
    existing = _axis("bicycle_infra_quality")
    assert "cycleway" in existing.inputs

    with pytest.raises(registry.AxisInputConflictError) as exc_info:
        registry.register_axis(registry.AxisSpec(axis_id="another", inputs=["cycleway"]))

    assert exc_info.value.overlapping_attrs == {"cycleway"}
