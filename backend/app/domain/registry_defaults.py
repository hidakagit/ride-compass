"""既存の一次属性・二次軸をレジストリ（domain/registry.py）へ登録する既定セット。

`register_defaults()`を呼ぶと、一次属性（このファイルに固定の手書きカタログとして残る、
OSM/政府統計等の実際のデータ取込パイプラインが提供する有限集合で、軸スタジオの編集対象
ではない「材料の天井」）と、公開済みの二次軸（`AXIS_DEFINITIONS`から動的に導出、後述）が
プロセス内のレジストリへ登録される。モジュールimport時には自動実行しない（グローバルな
レジストリ状態への副作用をimportのタイミングに依存させると、テストの実行順序でレジストリが
空/一部登録済みのどちらの状態にもなりうり壊れやすいため）。

**実際の呼び出し元は`scripts/export_openapi.py`（ビルド時、`axis-catalog.json`等の生成物
書き出し用）とテストのみで、FastAPIアプリ本体は起動時に呼ばない**（コスト関数
`compute_edge_axis_scores`はこのレジストリを一切参照しない。詳細は
docs/architecture.md「一次属性レジストリ・二次軸レジストリ」節参照）。
本レジストリが実際に駆動するのは、地図レイヤーパネル・凡例・区間インスペクタが読む
表示カタログ（`axis-catalog.json`）の生成のみ。

二次軸の登録は`AXIS_DEFINITIONS`走査への一本化により、軸id・軸の数を一切コードへ
書かない。`_register_axes()`は`AXIS_DEFINITIONS`をそのまま走査し、公開軸すべてを
登録する。`display`・`inputs`（参照する一次属性id）は`domain/axis_display.py:
axis_display_for()`・`primary_attribute_ids_for()`（`GET /api/axis-catalog`が実行時に
使うのと同一の純粋関数、片側import）から導出するため、ビルド時静的生成物と実行時APIの
計算ロジックが完全に一致する。

**表示名（label）等の単一ソース化**: `label`・
`description`（`AxisDisplaySpec`側の`category`はここでは持たない——地図レイヤーパネルの
グルーピング用の別概念だが、`axis_display_for()`は自動導出時に既定値
`category="trafficSafety"`を使うため、軸ごとの個別分類は現状表現しない）は
`domain/axis_definitions.py: AXIS_DEFINITIONS[axis_id]`（DB化・軸スタジオでGUI
編集可能）を単一ソースとする。

**この単一ソース化が解決しない範囲**: `register_defaults()`はビルド時
（`export_openapi.py`）とテストのみで呼ばれ、FastAPIアプリ起動時には呼ばれない
（本docstring冒頭参照）。そのため軸スタジオ（`/admin`）での編集は、`axis-catalog.json`
（ビルド時生成物、frontendの読込中/エラー時フォールバック専用）へは再デプロイまで
反映されない（`GET /api/axis-catalog`という実行時APIには即座に反映される、
`api/routers/axis_catalog.py`参照）。
"""

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.axis_display import axis_display_for, primary_attribute_ids_for
from app.domain.registry import (
    AxisSpec,
    PrimaryAttributeSpec,
    register_axis,
    register_primary_attribute,
)


def register_defaults() -> None:
    """既存の一次属性・二次軸をレジストリへ登録する。二重呼び出しは`register_primary_attribute`/
    `register_axis`が`ValueError`（既に登録済み）を送出するため、呼び出し側が
    プロセス内で1回だけ呼ぶこと（テストでは`reset_registry_for_testing()`と対で使う）。"""
    _register_primary_attributes()
    _register_axes()


def _register_primary_attributes() -> None:
    # 各PrimaryAttributeSpecはattr_id/label/sharedのみを持つ（詳細はdomain/registry.py:
    # PrimaryAttributeSpec docstring参照）。
    register_primary_attribute(PrimaryAttributeSpec(attr_id="highway", label="道路の種類"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="lanes", label="車線数"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="maxspeed", label="制限速度"))
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="cycleway",
            label="自転車インフラ",
            # highway_is_cycleway/cycleway_has_track/cycleway_has_lane/
            # cycleway_has_sharedの4材料は、car_stress軸（内部のcar_stress_bicycle_infra_
            # adjustment経由）と、新設の公開軸bicycle_infra_qualityの両方が正当に参照する
            # （後者はcar_stressの内部補正とほぼ同一の重みを再利用した「ニアリーイコールの
            # 推定軸」として意図的に設計したため、2軸が同じ一次属性を共有すること自体が
            # 想定どおり）。geometryと同じ「複数軸が参照してよい共通の一次属性」として
            # 排他チェック対象外にする（highway自体はcar_stress_highway_baseが単独で使う
            # ため、shared化せず排他チェックを維持する）。
            shared=True,
        )
    )
    register_primary_attribute(PrimaryAttributeSpec(attr_id="surface", label="路面の種類"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="bicycle_access", label="自転車通行可否"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="motor_vehicle_access", label="自動車通行可否"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="lit", label="街灯"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="tunnel", label="トンネル"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="oneway", label="一方通行"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="designation", label="指定路線"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="elevation", label="標高"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="stop_poi", label="停止要因"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="supply_poi", label="補給・休憩ポイント"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="accident_point", label="事故地点"))
    register_primary_attribute(PrimaryAttributeSpec(attr_id="intersection", label="交差点"))
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="geometry",
            label="区間形状",
            shared=True,  # 区間の形状・距離（全軸が参照してよい共通コンテキスト、排他チェック対象外）
        )
    )


def _register_axes() -> None:
    """公開済みの評価軸すべてを、AXIS_DEFINITIONSをそのまま走査してレジストリへ登録する。
    特定のaxis_idを名指しした条件分岐は持たない——`is_published`という
    軸横断の性質だけで判定するため、組み込み軸が増減しても・軸スタジオ経由でGUI作成軸が
    増えても、このループ自体は変更不要（詳細はモジュールdocstring参照）。

    `inputs`（参照する一次属性id）・`display`（地図表示宣言）は、`GET /api/axis-catalog`
    （実行時API）が同じ軸に対して呼ぶのと同一の純粋関数（`domain/axis_display.py:
    primary_attribute_ids_for()`・`axis_display_for()`）から導出するため、ビルド時静的
    生成物（`axis-catalog.json`）と実行時APIとで計算ロジックが分岐しない。
    """
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if not definition.is_published:
            continue
        register_axis(
            AxisSpec(
                axis_id=axis_id,
                inputs=primary_attribute_ids_for(definition),
                display=axis_display_for(definition),
            )
        )
