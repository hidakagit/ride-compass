"""既存の一次属性・二次軸をレジストリ（domain/registry.py）へ登録する既定セット（改善計画T137）。

`register_defaults()`を呼ぶと、以下の一次属性・二次軸がプロセス内のレジストリへ登録される。
モジュールimport時には自動実行しない（グローバルなレジストリ状態への副作用をimportのタイミングに
依存させると、テストの実行順序でレジストリが空/一部登録済みのどちらの状態にもなりうり壊れやすい
ため）。

**実際の呼び出し元は`scripts/export_openapi.py`（ビルド時、`axis-catalog.json`等の生成物
書き出し用）とテストのみで、FastAPIアプリ本体は起動時に呼ばない**（改善計画T142の
コスト関数`compute_edge_axis_scores`はこのレジストリを一切参照せず、`AXIS_WEIGHT_FIELD_
TO_AXIS_ID`等の独立した手書き辞書を使う——各軸の`transform_fn`のシグネチャが軸ごとに
大きく異なるため、レジストリ経由の動的解決はT142で意図的に見送られた。詳細は
docs/architecture.md「一次属性レジストリ・二次軸レジストリ」節・改善計画T154参照）。
本レジストリが実際に駆動するのは、地図レイヤーパネル・凡例・区間インスペクタが読む
表示カタログ（`axis-catalog.json`）の生成のみ。統合レビュー2026-08-19 complexity F-4・
改善計画T160(2)で、この段落が実態と異なる記述だったため訂正した。

T137時点では「車ストレス」「安全度」「自転車インフラ」の3軸が、highway・cycleway・
maxspeed・lanes・指定路線を車の圧迫感・安全度の両方で共有していた（T130で意図的に共有した
設計）ため未登録だったが、T138（自転車インフラを独立軸から車ストレスへ統合）・
T139（安全度を軸ごと廃止し事故実績・夜間へ分割）・T149（交差点密度を停止密度へ統合）を
経て軸自体が排他的な構造へ再編されたため、`car_stress`・`night`を登録済み（`accident`は
T137時点から既に排他、`stop_density`はT149でintersectionを吸収済み）。`safety`
（旧`domain/safety.py`）は難易度合成からはT139で外れており、そもそも軸として登録した
ことがない（表示専用の派生値だったため）。`domain/safety.py`自体はT148で削除済み。

axis_idは設計プロンプトが示す目標名（`car_stress`等）を使う。対応するPythonのモジュール・
関数のシンボル名（`domain/traffic.py: car_stress_level`）も改善計画T150（呼称のtraffic→
car_stressへの統一）で追従済み。

**表示名（label）の単一ソース化（改善計画T270フォローアップ、2026-08-24）**: 各軸の
`AxisDisplaySpec.label`は`domain/axis_definitions.py: AXIS_DEFINITIONS[axis_id].label`
（T269でAxisDefinitionへ追加、DB化・軸スタジオでGUI編集可能な方）から参照する形にした。
以前はこのファイルへ同じ文字列（例:「車の圧迫感」）を独立して手書きしており、
2箇所が実質同じ事実を別々に宣言する重複だった（設計原則2「片側import」違反）。
`AxisSpec.description`（本ファイル、開発者向けの長い技術説明）と`AxisDisplaySpec.category`
（本ファイル、地図レイヤーパネルのグルーピング用「terrain」「road」「trafficSafety」等）は
`AXIS_DEFINITIONS`の`description`（ユーザー向けの短い説明、RouteSettingsPanelのツールチップ用）
・`category`（評価軸の性質「観測」「推定」「動的」、目論見書3章）とは対象読者・意味が
異なる別概念のため統合しない（同じ「category」という語を使うが指す軸が異なる点に注意）。

**この単一ソース化が解決しない範囲**: `register_defaults()`はビルド時
（`export_openapi.py`）とテストのみで呼ばれ、FastAPIアプリ起動時には呼ばれない
（本docstring冒頭参照）。そのためこの参照は「Pythonコード上の既定値が一致する」ことを
保証するのみで、軸スタジオ（`/admin`）でDBの`label`をGUI編集しても、地図レイヤーパネル・
`axis-catalog.json`（ビルド時生成物）側のラベルは再デプロイまで追従しない
（`docs/decisions/t221-axis-registry.md`「Stage E実装」節の残作業3と同根の制約）。

**地図表示ルール（kind=ramp）の自動導出（改善計画T278、2026-08-24）**: `surface_q`・
`night`の`display`（`tile_inputs`/`thresholds`）は`domain/axis_display.py:
derive_ramp_inputs()`が`AXIS_DEFINITIONS`の材料（`domain/material_catalog.py`の
`tile_property`保持材料）から自動導出する。以前は`surface_q`が「既存の道路情報レイヤーと
重複するため」という理由で`kind="none"`に手書き固定されていたが、ユーザー判断
（2026-08-24）で「ramp化技術的に可能な軸は一律`kind="ramp"`にし、重複回避は地図
レイヤーパネル側の表示/非表示切替で運用する」方針へ統一した。`gradient`（材料が
タイル非依存）・`stop_density`（複数材料の重み付き結合、既存thresholds`[1,2,4]`は
統計的経験則で単純な折れ点流用では再現不可）・`car_stress`（材料がタイル非依存の
レシピ合成値）・`accident`（材料が年正規化済みでタイル生値とスケールが異なり、
静的な変換係数を持てない）は自動導出の対象外のまま手書きの`display`を維持する
（詳細はdomain/axis_display.pyのdocstring、改善計画T278参照）。
"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, UNSIGNALED_INTERSECTION_WEIGHT
from app.domain.axis_display import derive_ramp_inputs
from app.domain.registry import (
    AxisDisplaySpec,
    AxisSpec,
    PrimaryAttributeSpec,
    TileInputSpec,
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
    """現時点で入力が排他的な軸のみ登録する（詳細はモジュールdocstring参照）。"""
    register_axis(
        AxisSpec(
            axis_id="gradient",
            inputs=["elevation"],
            transform_fn="app.domain.difficulty.gradient_difficulty",
            output_range=(0.0, 100.0),
            description="区間の平均勾配から算出する難易度（絶対基準）",
            display=AxisDisplaySpec(
                kind="none",
                label=AXIS_DEFINITIONS["gradient"].label,
                category="terrain",
                note="標高属性（elevation_attributes）はGSI APIから都度取得でDBへ恒久保存"
                "しない設計のため、タイルへ焼き込める事実データが無い。標高図レイヤー"
                "（elevation）が地形の把握を代替する",
            ),
        )
    )
    surface_q_ramp = derive_ramp_inputs(AXIS_DEFINITIONS["surface_q"])
    assert surface_q_ramp is not None  # 材料surface_goodはtile_property保持済み（material_catalog.py）
    register_axis(
        AxisSpec(
            axis_id="surface_q",
            inputs=["surface"],
            transform_fn="app.domain.difficulty.road_difficulty",
            output_range=(0.0, 100.0),
            description="路面材質（`domain/road.py: classify_osm_surface`で良/不明の3値へ分類済み）"
            "から算出する走行しやすさ。ルート単位の集約統計（`RouteCandidate.road_score`、"
            "距離加重の舗装率%）は別関数`domain/road.py: distance_weighted_road_score`が担う"
            "（区間単位のこの軸と混同しないこと）",
            display=AxisDisplaySpec(
                kind="ramp",
                label=AXIS_DEFINITIONS["surface_q"].label,
                category="road",
                tile_inputs=surface_q_ramp.tile_inputs,
                thresholds=surface_q_ramp.thresholds,
                note="改善計画T278: 材料surface_good（タイル焼き込み済み）から自動導出。"
                "既存の道路情報レイヤー（road、surface_good/surface/highwayの3色分け"
                "モード）と表示内容が重複するため非表示にしたい場合は地図レイヤーパネルの"
                "表示切替で運用する（backend側にkind=noneの手動固定は設けない）。"
                "ラベルは「路面」から改名（改善計画T163）: 一次属性「路面の種類」（surface）"
                "との紛らわしさを解消するため。重みラベル「舗装」・レジストリ記述"
                "「路面材質」と整合させた",
            ),
        )
    )
    register_axis(
        AxisSpec(
            axis_id="stop_density",
            inputs=["stop_poi", "intersection"],
            transform_fn="app.domain.difficulty.stop_difficulty",
            output_range=(0.0, 100.0),
            description="信号・横断歩道・一時停止・踏切・無タグ交差点の密度（回/km）から算出する"
            "難易度。交差点密度(intersection)は単独軸を持たず、タグなし交差点として低い重み"
            "（0.3、signal等のstop_poiを1.0とした相対値）でこの軸へ吸収する"
            "（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」、改善計画T149で実装済み）",
            display=AxisDisplaySpec(
                kind="ramp",
                label=AXIS_DEFINITIONS["stop_density"].label,
                category="trafficSafety",
                tile_inputs=[
                    TileInputSpec(property="stop_per_km", weight=1.0),
                    TileInputSpec(property="intersection_per_km", weight=UNSIGNALED_INTERSECTION_WEIGHT),
                ],
                # domain/difficulty.py: stop_difficultyの正準スケール（0→4.0回/kmで0→100）に
                # 対応する4段階（〜1/〜2/〜4/4超）。
                thresholds=[1.0, 2.0, 4.0],
                unit="回/km",
                note="信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた"
                "停止要因の密度。way単位の事前集計（way_attribute_counts）由来",
            ),
        )
    )
    register_axis(
        AxisSpec(
            axis_id="car_stress",
            inputs=["highway", "lanes", "maxspeed", "cycleway", "designation", "motor_vehicle_access"],
            transform_fn="app.domain.traffic.car_stress_level",
            output_range=(0.0, 100.0),
            description="道路種別・車線数・制限速度・N10/N12該当・自転車インフラ（cycleway補正）・"
            "自動車通行可否（motor_vehicle=noなら他の補正に関わらず1固定）から算出する"
            "車ストレス（走行中の車との近接ストレス）。旧「交通ストレス」・"
            "「圧迫感」。改善計画T138で自転車インフラの独立軸を統合済み。呼称のtraffic→"
            "car_stressへの統一（Pythonシンボル名）は改善計画T150で実施済み。"
            "transform_fnは1-5の生レベルを返す`car_stress_level`を指す（0-100の"
            "difficultyへの変換は`domain/difficulty.py: car_stress_difficulty`が別途行う"
            "2段階構成。実際の呼び出しは`domain/evaluation.py: compute_edge_axis_scores`が"
            "この2段階を合成して行っており、まだtransform_fn文字列を動的解決してはいない）。"
            "motor_vehicle_accessは地図レイヤー階層の次数反転検討（改善計画T163）で"
            "inputsからの記載漏れが発覚し追加した（排他違反ではないが不完全だった）",
            display=AxisDisplaySpec(
                kind="bespoke",
                label=AXIS_DEFINITIONS["car_stress"].label,
                category="trafficSafety",
                note="highway×cycleway×maxspeed×lanes×指定路線のレシピ判定が必要なため"
                "汎用rampでは表せない。フロントの手書きexpression"
                "（carStressExpression.ts、既存carStressレイヤー）が担う",
            ),
        )
    )
    night_ramp = derive_ramp_inputs(AXIS_DEFINITIONS["night"])
    assert night_ramp is not None  # 材料no_lit/has_tunnelはtile_property保持済み（material_catalog.py）
    register_axis(
        AxisSpec(
            axis_id="night",
            inputs=["lit", "tunnel"],
            transform_fn="app.domain.night.night_difficulty",
            output_range=(0.0, 100.0),
            description="街灯なし・トンネルから算出する夜間の走りにくさ。改善計画T139で"
            "安全度軸から分離・新設。既定重み0で運用（route_preference.yaml参照）",
            display=AxisDisplaySpec(
                kind="ramp",
                label=AXIS_DEFINITIONS["night"].label,
                category="trafficSafety",
                tile_inputs=night_ramp.tile_inputs,
                thresholds=night_ramp.thresholds,
                note="改善計画T278: 材料no_lit（lit材料の否定）・has_tunnelから自動導出。"
                "現OSMデータではlitタグが疎なため色分けの差が小さく見える場合があるが、"
                "手書きexpressionを持たずとも自動導出のrampレイヤーとして表示できるように"
                "なったため専用レイヤー保留（改善計画T145a）は解消した",
            ),
        )
    )
    register_axis(
        AxisSpec(
            axis_id="accident",
            inputs=["accident_point"],
            transform_fn="app.domain.difficulty.accident_difficulty",
            output_range=(0.0, 100.0),
            description="事故地点密度（件/(km・年)）から算出する難易度。事故実績のみを入力とし、"
            "他のどの軸とも一次属性を共有しない",
            display=AxisDisplaySpec(
                kind="ramp",
                label=AXIS_DEFINITIONS["accident"].label,
                category="trafficSafety",
                tile_inputs=[TileInputSpec(property="accident_per_km", weight=1.0)],
                # domain/difficulty.py: accident_difficultyの正準スケール（0→0.5件/(km・年)で
                # 0→100）を、タイルへ焼き込む生値（収録3年分の重み付き件数/km、年正規化前）へ
                # 換算した4段階（〜0.4/〜0.8/〜1.5/1.5超）。
                thresholds=[0.4, 0.8, 1.5],
                unit="件/km",
                note="警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の"
                "距離正規化密度。way単位の事前集計（way_attribute_counts）由来。"
                "正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる",
            ),
        )
    )
