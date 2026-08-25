"""既存の一次属性・二次軸をレジストリ（domain/registry.py）へ登録する既定セット（改善計画T137）。

`register_defaults()`を呼ぶと、一次属性（このファイルに固定の手書きカタログとして残る、
OSM/政府統計等の実際のデータ取込パイプラインが提供する有限集合で、軸スタジオの編集対象
ではない「材料の天井」）と、公開済みの二次軸（`AXIS_DEFINITIONS`から動的に導出、後述）が
プロセス内のレジストリへ登録される。モジュールimport時には自動実行しない（グローバルな
レジストリ状態への副作用をimportのタイミングに依存させると、テストの実行順序でレジストリが
空/一部登録済みのどちらの状態にもなりうり壊れやすいため）。

**実際の呼び出し元は`scripts/export_openapi.py`（ビルド時、`axis-catalog.json`等の生成物
書き出し用）とテストのみで、FastAPIアプリ本体は起動時に呼ばない**（改善計画T142の
コスト関数`compute_edge_axis_scores`はこのレジストリを一切参照しない。詳細は
docs/architecture.md「一次属性レジストリ・二次軸レジストリ」節・改善計画T154参照）。
本レジストリが実際に駆動するのは、地図レイヤーパネル・凡例・区間インスペクタが読む
表示カタログ（`axis-catalog.json`）の生成のみ。

**改善計画T320: 二次軸の登録を軸id直書きの手動列挙からAXIS_DEFINITIONS走査へ一本化**。
以前は`car_stress`・`night`等6軸ぶんを1軸ずつ`if axis_id in AXIS_DEFINITIONS: register_axis(
AxisSpec(axis_id="gradient", ...))`のように手書きしており、①組み込み軸がAXIS_DEFINITIONS
から削除されるとKeyErrorでビルド自体が落ちる、②新規に軸スタジオへ追加された軸はこの
一覧に含まれずビルド時静的生成物（`axis-catalog.json`）へ永遠に現れない、という2つの
不整合があった（後者は`scripts/export_openapi.py`側の`_auto_ramp_axes`という重複した
別ループで部分的に穴埋めしていたが、これ自体が「同じロジックの二重実装」という別の問題
だった）。`_register_axes()`は`AXIS_DEFINITIONS`をそのまま走査し、公開軸すべてを
（軸id・軸の数を一切コードへ書かずに）登録する形へ書き換えた。`display`・`inputs`
（参照する一次属性id）は`domain/axis_display.py: axis_display_for()`・
`primary_attribute_ids_for()`（`GET /api/axis-catalog`が実行時に使うのと同一の純粋関数、
片側import）から導出するため、ビルド時静的生成物と実行時APIの計算ロジックが完全に一致する。

**表示名（label）等の単一ソース化（改善計画T270フォローアップ・T320）**: `label`・
`description`（`AxisDisplaySpec`側の`category`はここでは持たない——地図レイヤーパネルの
グルーピング用の別概念だったが、`axis_display_for()`は自動導出時に既定値
`category="trafficSafety"`を使うため、軸ごとの個別分類は現状表現しない）は
`domain/axis_definitions.py: AXIS_DEFINITIONS[axis_id]`（T269でDB化・軸スタジオでGUI
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
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="highway",
            label="道路の種類",
            source="osm",
            geometry="edge",
            dtype="categorical",
            update_cadence="on_reimport",
            description="OSM highwayタグ（道路種別）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="lanes",
            label="車線数",
            source="osm",
            geometry="edge",
            dtype="numeric",
            update_cadence="on_reimport",
            description="OSM lanesタグ（車線数）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="maxspeed",
            label="制限速度",
            source="osm",
            geometry="edge",
            dtype="numeric",
            update_cadence="on_reimport",
            description="OSM maxspeedタグ（制限速度、km/h）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="cycleway",
            label="自転車インフラ",
            source="osm",
            geometry="edge",
            dtype="categorical",
            update_cadence="on_reimport",
            description="OSM cycleway/cycleway:left/right/bothタグ（自転車インフラ種別の材料）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="surface",
            label="路面の種類",
            source="osm",
            geometry="edge",
            dtype="categorical",
            update_cadence="on_reimport",
            description="OSM surfaceタグ（路面材質）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="bicycle_access",
            label="自転車通行可否",
            source="osm",
            geometry="edge",
            dtype="categorical",
            update_cadence="on_reimport",
            description="OSM bicycleタグ（自転車の通行可否・分類）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="motor_vehicle_access",
            label="自動車通行可否",
            source="osm",
            geometry="edge",
            dtype="categorical",
            update_cadence="on_reimport",
            description="OSM motor_vehicleタグ（自動車の通行可否）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="lit",
            label="街灯",
            source="osm",
            geometry="edge",
            dtype="boolean",
            update_cadence="on_reimport",
            description="OSM litタグ（街灯の有無）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="tunnel",
            label="トンネル",
            source="osm",
            geometry="edge",
            dtype="boolean",
            update_cadence="on_reimport",
            description="OSM tunnelタグ（トンネルの有無）",
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="oneway",
            label="一方通行",
            source="osm",
            geometry="edge",
            dtype="boolean",
            update_cadence="on_reimport",
            description=(
                "OSM onewayタグ（oneway:bicycleによるcontraflow例外込みでosm_adapter.py: "
                "_resolve_directionが解決済み）。逆方向は既にbuild_road_graphがEdge自体を"
                "生成しないため探索の正しさには無関係で、表示専用の一次属性（改善計画T289）。"
                "どの評価軸のinputsにも含めない。"
            ),
            ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="designation",
            label="指定路線",
            source="kokudo_suuchi",
            geometry="edge",
            dtype="categorical",
            update_cadence="yearly",
            description="国土数値情報 N10（緊急輸送道路）・N12（重要物流道路）該当フラグ",
            ingest_fn="app.batch.match_designations",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="elevation",
            label="標高",
            source="gsi",
            geometry="edge",
            dtype="numeric",
            update_cadence="static",
            description="国土地理院 標高API由来のEdge単位勾配（average_grade等）",
            ingest_fn="app.services.elevation_attribute_service",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="stop_poi",
            label="停止要因",
            source="osm",
            geometry="point",
            dtype="categorical",
            update_cadence="on_reimport",
            description="信号・横断歩道・一時停止・踏切のnode（静的道路属性P1）",
            ingest_fn="app.domain.osm_adapter.osm_node_to_poi_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="supply_poi",
            label="補給・休憩ポイント",
            source="osm",
            geometry="point",
            dtype="categorical",
            update_cadence="on_reimport",
            description="補給・休憩POI（コンビニ・自販機・トイレ・給水・駐輪場、T101）。"
            "スコア化はせず表示レイヤーとしてのみ使う（設計プロンプトの制約）ため、"
            "本レジストリでは軸から参照されない一次属性として登録するのみ。",
            ingest_fn="app.domain.osm_adapter.osm_node_to_poi_spec",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="accident_point",
            label="事故地点",
            source="npa_accident",
            geometry="point",
            dtype="categorical",
            update_cadence="yearly",
            description="警察庁交通事故統計の事故地点データ",
            ingest_fn="app.batch.import_accidents",
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="intersection",
            label="交差点",
            source="osm",
            geometry="point",
            dtype="numeric",
            update_cadence="on_reimport",
            description="次数3以上のroad_node（交差点、OSMの道路網トポロジーから導出。専用テーブルなし）",
            ingest_fn=None,
        )
    )
    register_primary_attribute(
        PrimaryAttributeSpec(
            attr_id="geometry",
            label="区間形状",
            source="osm",
            geometry="edge",
            dtype="geometry",
            update_cadence="on_reimport",
            description="区間の形状・距離（全軸が参照してよい共通コンテキスト、排他チェック対象外）",
            ingest_fn=None,
            shared=True,
        )
    )


def _register_axes() -> None:
    """公開済みの評価軸すべてを、AXIS_DEFINITIONSをそのまま走査してレジストリへ登録する
    （改善計画T320）。特定のaxis_idを名指しした条件分岐は持たない——`is_published`という
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
