# スキーマ移行の記録（2026-08-15〜2026-09-20、migrations/*.sql）

**メンテナンスしない過去の記録。** T970でデータ層を作り直し、スキーマはORMの宣言から
`create_tables()`が作る形になったため、`backend/migrations/`は役目を終えて削除した。

残す理由は、47本のSQLが**1,081行のうち674行をコメントに使っており**、そこにしか無い判断が
あるため。ファイル自体はgit履歴に残るが、消した後は「そこを見る」と誰も気づけない。
以下は各移行が何を変え、なぜそうしたかを原文のまま写したもの。

対応するコードの多くは既に存在しない（`osm_raw_ways`・`edge_attribute_counts`・
`import_runs`系など）。**当時の判断の記録として読むこと。**

## 0001_legacy_backfill_and_indexes

追加された日: 2026-08-15

> 改善計画T17（最小マイグレーション機構の導入）で road_graph_repository.py: create_tables
> 内にあった冪等ALTER/インデックス操作/バックフィルを移設したもの。すべて既に本番・開発DBへ
> 適用済みの内容であり、この移設自体はスキーマを変更しない（内容は無変更、置き場所のみ変更）。
> 
> 新規DB（Base.metadata.create_allで作成された直後）に対しても、既存の古いDBに対しても、
> 同じ内容が冪等に適用できる（IF NOT EXISTS / IF EXISTS を使っているため）。
> PBF取込（Phase 1）で追加したosm_raw_ways.geom列（既存DB向けの冪等な追加）
> 生データ不変時の省略パス（is_split_up_to_date）で追加したosm_raw_ways.split_at列
> （既存DB向けの冪等な追加）
> save_graphの削除ステップ（DELETE FROM road_edges WHERE osm_way_id IN (...)）が
> インデックス無しで動いていたため追加（既存DB向けの冪等な追加）
> road_nodesへのDELETE（容量予算超過時の圧力弁・古いhighway種別のクリーンアップ等）が
> from_node_id/to_node_id経由のFK整合性チェックでroad_edgesの全件シーケンシャル
> スキャンを行っていたため追加（既存DB向けの冪等な追加。関東圏拡大に向けた
> クリーンアップ作業で発覚: 35,550行の削除に27分かかった）
> geom列導入前に保存された既存行のバックフィル（node_ids→osm_raw_nodesから
> LINESTRINGを再構成）。get_way_specs_with_closureはgeomを前提とした空間検索の
> ため、NULLのままだと旧データが閉包対象から漏れる。座標が判明しているノードが
> 2点未満の行はNULLのまま（save_raw_ways/PBF取込と同じ意味論）。
> 旧・閉包クエリ用のGINインデックス（node_ids &&）の廃止（既存DB向けの冪等な削除）。
> geom列の空間検索への置き換えで未使用になり、実測28MB（東京都心取込時）を占めて
> いたため、Supabaseフリープラン等の容量制約に合わせて削除する
> （road_graph_models.py: OsmRawWayRowのdocstring参照）。

```sql
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS geom geometry(LINESTRING,4326);
CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom ON osm_raw_ways USING gist (geom);
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS split_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_road_edges_osm_way_id ON road_edges USING btree (osm_way_id);
CREATE INDEX IF NOT EXISTS idx_road_edges_from_node_id ON road_edges USING btree (from_node_id);
CREATE INDEX IF NOT EXISTS idx_road_edges_to_node_id ON road_edges USING btree (to_node_id);
UPDATE osm_raw_ways w
SET geom = sub.line
FROM (
SELECT w2.osm_way_id, ST_MakeLine(n.geom ORDER BY u.ord) AS line
FROM osm_raw_ways w2
JOIN LATERAL unnest(w2.node_ids) WITH ORDINALITY AS u(node_id, ord) ON true
JOIN osm_raw_nodes n ON n.osm_node_id = u.node_id
WHERE w2.geom IS NULL
GROUP BY w2.osm_way_id
HAVING count(*) >= 2
) sub
WHERE w.osm_way_id = sub.osm_way_id;
DROP INDEX IF EXISTS ix_osm_raw_ways_node_ids;
```

## 0002_drop_unused_osm_raw_nodes_geom_index

追加された日: 2026-08-15

> 改善計画T28（PBF初回取込の後半チャンク減速調査）で判明: osm_raw_nodes.geomのGiSTは
> 全コードから空間検索されておらず（アクセスは常にosm_node_id指定）、取込時の逐次挿入コスト
> と容量を消費するだけの死荷重だった（road_graph_models.py: OsmRawNodeRowのdocstring参照）。
> spatial_index=False化と対になる、既存DB向けの冪等な削除（新規DBはそもそも作成されない）。

```sql
DROP INDEX IF EXISTS idx_osm_raw_nodes_geom;
```

## 0003_add_osm_raw_ways_tags

追加された日: 2026-08-15

> 静的道路属性 P0（docs/static-road-attributes-plan.md）: osm_raw_waysへ許可リストタグの
> jsonb列を追加する。既存DB向けの冪等な追加（新規DBはBase.metadata.create_allで
> 最初から持つ）。容量実測（2026-08-15）で本番規模+約9MBと軽微。

```sql
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '{}'::jsonb;
```

## 0004_drop_surface_attributes

追加された日: 2026-08-15

> T9（surface_attributesの導出化、docs/improvement-plan.md）: Edge単位のsurfaceは
> road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOINして導出する方式へ切り替えたため、
> 専用テーブルは不要になった。road_edges.osm_way_idのJOINにはmigration 0001で作成済みの
> idx_road_edges_osm_way_idを使うため、新規インデックスは不要。

```sql
DROP TABLE IF EXISTS surface_attributes;
```

## 0005_add_osm_raw_pois

追加された日: 2026-08-16

> 静的道路属性 P1（docs/static-road-attributes-plan.md）: 信号・横断歩道・一時停止・踏切の
> node取込先テーブルを新規作成する。既存DB向けの冪等な追加（新規DBはBase.metadata.create_all
> で最初から持つ）。osm_raw_nodesと違いgeomへGiST索引を張る（road_edgesとの空間結合に使うため）。

```sql
CREATE TABLE IF NOT EXISTS osm_raw_pois (
osm_node_id bigint PRIMARY KEY,
kind text NOT NULL,
tags jsonb NOT NULL DEFAULT '{}'::jsonb,
geom geometry(Point, 4326) NOT NULL,
updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_raw_pois_geom ON osm_raw_pois USING gist (geom);
```

## 0006_add_accident_points

追加された日: 2026-08-16

> 外部静的データソース T50（docs/external-data-sources-review-2026-08-16.md §4.1）:
> 警察庁 交通事故統計オープンデータの取込先テーブルを新規作成する。既存DB向けの冪等な
> 追加（新規DBはBase.metadata.create_allで最初から持つ）。取込元がOSMではないため
> osm_raw_pois等の既存テーブルとは分ける（rawと派生の分離を外部データにも適用する方針、
> 同ドキュメント§4「共通方針」）。

```sql
CREATE TABLE IF NOT EXISTS accident_points (
accident_id text PRIMARY KEY,
occurred_year integer NOT NULL,
fatal boolean NOT NULL,
involves_bicycle boolean NOT NULL,
attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
geom geometry(Point, 4326) NOT NULL,
updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accident_points_geom ON accident_points USING gist (geom);
CREATE TABLE IF NOT EXISTS accident_import_runs (
id serial PRIMARY KEY,
occurred_year integer NOT NULL,
file_name text NOT NULL,
status text NOT NULL,
started_at timestamptz NOT NULL,
finished_at timestamptz,
accident_count bigint
);
```

## 0007_add_route_designations

追加された日: 2026-08-16

> 外部静的データソース T51（docs/external-data-sources-review-2026-08-16.md §4.3）:
> 指定路線コンフレーション機構（パターンD初回実装）の取込先テーブルを新規作成する。
> 既存DB向けの冪等な追加（新規DBはBase.metadata.create_allで最初から持つ）。
> 取込元がOSMではないためosm_raw_ways等の既存テーブルとは分ける（accident_pointsと同じ判断）。
> Edge派生（elevation_attributes型）。1エッジが複数kind（N10かつN12）に該当しうるため
> 複合PKにする。

```sql
CREATE TABLE IF NOT EXISTS route_designations (
id serial PRIMARY KEY,
kind text NOT NULL,
name text,
pref_code text,
attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
source text NOT NULL,
geom geometry(LineString, 4326) NOT NULL,
updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_route_designations_geom ON route_designations USING gist (geom);
CREATE TABLE IF NOT EXISTS designation_attributes (
edge_id text NOT NULL REFERENCES road_edges(edge_id) ON DELETE CASCADE,
kind text NOT NULL,
matched_ratio double precision NOT NULL,
data_version text,
calculated_at timestamptz NOT NULL,
PRIMARY KEY (edge_id, kind)
);
CREATE TABLE IF NOT EXISTS designation_import_runs (
id serial PRIMARY KEY,
kind text NOT NULL,
source text NOT NULL,
status text NOT NULL,
started_at timestamptz NOT NULL,
finished_at timestamptz,
designation_count bigint
);
```

## 0008_stale_way_partial_index

追加された日: 2026-08-16

> 改善計画T68: is_split_up_to_dateはリクエストごとにbbox内の全way（GiST走査＋split_atフィルタ）
> をスキャンしてstale行を探すが、全way freshの定常状態が大多数なのに、bboxが大きいほど
> （ルート生成は最大60km径ループ＋マージン）走査量が線形に増える。
> 
> WHERE句の述語（is_split_up_to_dateのstale_stmt、road_graph_repository.py参照）と
> 完全一致する部分索引を追加する。プランナがそのまま使え、定常状態では索引がほぼ空になり
> LIMIT 1判定が即時になる（取込直後の全行staleな状態では通常GiSTと同等まで膨らむが、
> split進行に伴い縮む）。

```sql
CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom_stale
ON osm_raw_ways USING gist (geom)
WHERE split_at IS NULL OR split_at < updated_at;
```

## 0009_designation_attributes_osm_way_id

追加された日: 2026-08-16

> 改善計画T74: designation_attributesのキーをedge_id（road_edges FK、ルート生成地点周辺のみ
> 遅延構築）からosm_way_id（osm_raw_ways FK、関東全域自己完結）へ変更する。
> route_designationsは全域投入済みなのに、road_edges依存のせいでルート生成履歴の無いエリアでは
> 指定路線レイヤーが表示されない不具合（T74「遅延構築依存」）の根本対応。
> 
> designation_attributesはmatch_designations.pyが再計算する派生データ（正データはroute_designations
> 側）のため、DROP→新スキーマで作り直して安全。適用後は本番でもmatch_designations.pyの
> 再実行が必須（適用しただけではテーブルが空のまま）。

```sql
DROP TABLE IF EXISTS designation_attributes;
CREATE TABLE designation_attributes (
osm_way_id bigint NOT NULL REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
kind text NOT NULL,
matched_ratio double precision NOT NULL,
data_version text,
calculated_at timestamptz NOT NULL,
PRIMARY KEY (osm_way_id, kind)
);
```

## 0010_add_edge_attribute_counts

追加された日: 2026-08-19

> 改善計画T144: 事故密度・停止密度（タグなし交差点込み、T149）はPostGIS ST_DWithinでの
> Edge単位空間結合が重く、現状GraphServiceが都度クエリしている。事前集計を持つ
> edge_attribute_countsテーブルを新設する（designation_attributesと同じ「精密テーブル、
> バッチで再計算」パターン。マテリアライズドビューではなく通常テーブル＋バッチにする理由も
> designation_attributesと同じ: 元データ（accident_points/osm_raw_pois/road_edges）の
> 変更のたびに明示的な再計算が必要な派生データであることを明確にするため）。
> 
> 適用後は本番でもbackend/scripts/precompute_edge_attribute_counts.pyの実行が必須
> （適用しただけではテーブルが空のまま、designation_attributesと同じ運用）。
> 
> accident_countはdouble precision（死亡事故の重み付けSUMのため、domain/accident.py:
> ACCIDENT_FATAL_WEIGHT参照）。stop_count/intersection_countは単純な件数のためinteger。
> bicycle_only=trueの結果のみ保持する（road_graph_engine.pyの実際の呼び出しが常に既定値
> bicycle_only=Trueであるため、他の値は現状使われていない）。

```sql
CREATE TABLE IF NOT EXISTS edge_attribute_counts (
edge_id text PRIMARY KEY REFERENCES road_edges(edge_id) ON DELETE CASCADE,
accident_count double precision NOT NULL,
stop_count integer NOT NULL,
intersection_count integer NOT NULL,
computed_at timestamptz NOT NULL
);
```

## 0011_add_road_node_degree

追加された日: 2026-08-19

> 改善計画T151: get_intersection_countsは「渡されたedge_ids集合内で完結する部分グラフの
> 次数」を返す設計だったため、(a) 呼び出し元の集合が変わると同じedgeでも結果が変わる、
> (b) さらに深刻な問題として、内部の50,000件チャンク分割（road_graph_repository.py:
> get_intersection_counts）がリスト順序に依存してチャンク境界を決めるため、同一集合でも
> 順序が異なると境界をまたぐノードの次数が変わる非決定性があった（T144実装メモ参照）。
> 
> get_accident_counts/get_stop_poi_countsと同じ「edge単位で独立な空間近傍カウント」の
> 意味論へ揃えるため、次数を「対象road_nodeの真のグローバル次数（DB全体で見た次数）」として
> road_nodesへ事前計算・キャッシュする。呼び出し元の集合やチャンク分割から完全に独立するため、
> 順序依存・境界過小評価のどちらも構造的に解消する。
> 
> 適用後はbackend/app/batch/precompute_road_node_degrees.pyの実行が必須（適用しただけでは
> 全行degree=0のまま、edge_attribute_counts等と同じ運用）。road_edgesが変わるたび
> （PBF再取込時等）に再実行が必要な派生データ。

```sql
ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS degree integer NOT NULL DEFAULT 0;
```

## 0012_add_way_attribute_counts

追加された日: 2026-08-19

> 改善計画T145b「事実はタイルに、解釈はクライアントに」: 地図タイルへ焼き込む事実
> （事故・停止POI・交差点のカウント）のway単位事前集計。
> 
> T144のedge_attribute_counts（edge単位）はroad_edges（ルート生成時に遅延構築される
> Road Graph）に紐づくため、地図表示に使うとルート生成済みエリアしか色が付かない
> （dev実測: z14タイル内748way中27way=約3.6%しかカバーされない）。地図タイルの母集団で
> あるosm_raw_ways全域（レシピ非依存の生データ層）を対象に、way単位で再集計する。
> edge_attribute_countsは評価（ルート生成）用として並存する。
> 
> カウントの意味論はedge単位版（_ACCIDENT_COUNTS_SQL/_STOP_POI_COUNTS_SQL/
> road_nodes.degree）と同一: 事故=半径30m内のinvolves_bicycle事故（死亡はfatal_weight倍）、
> 停止POI=半径15m内のSTOP_POI_KINDS該当POI、交差点=半径30m内の次数3以上ノード。
> 交差点の次数はRoad Graph非依存にするため、osm_raw_ways.node_idsの隣接関係から導出した
> raw_intersection_nodes（次数3以上の生ノードのみ保持、バッチが全再構築）を参照する。
> 
> 適用後はbackend/app/batch/precompute_way_attribute_counts.pyの実行が必須（適用しただけ
> ではテーブルが空のまま、edge_attribute_counts等と同じ運用）。accident_points/
> osm_raw_pois/osm_raw_waysのいずれかが変わった場合（PBF再取込等）は再実行が必要。

```sql
CREATE TABLE IF NOT EXISTS raw_intersection_nodes (
osm_node_id bigint PRIMARY KEY,
degree integer NOT NULL,
geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_intersection_nodes_geom ON raw_intersection_nodes USING gist (geom);
CREATE TABLE IF NOT EXISTS way_attribute_counts (
osm_way_id bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
length_m double precision NOT NULL,
accident_count double precision NOT NULL,
stop_count integer NOT NULL,
intersection_count integer NOT NULL,
computed_at timestamptz NOT NULL
);
```

## 0013_add_edge_bearing

追加された日: 2026-08-23

> 改善計画T218（T12 ADR Stage 0: 探索の素材事前計算化＋リーンロード）。
> 探索時のwind評価（compute_wind_penalty）は現状、Edgeのgeometry（形状点列）の始点・終点
> から都度bearing_between()で方位角を計算している。この計算自体は軽いが、方位角の計算
> 「だけ」のためにgeometry（LINESTRING）をPostGISから取得・decodeする必要が生じており、
> これが探索リクエストのボトルネック（WARM時で全体の約6割、docs/decisions/
> t12-routing-scale.md参照）の一部になっている。bearing_degをEdge単位の永続列として
> 持たせることで、探索フェーズ（経路選択）ではgeometryを一切取得せずに風評価が完結する
> ようにする（domain/graph.py: DirectedEdge.bearing_deg、build_road_graph参照）。
> 
> 新規Edgeはbuild_road_graph側で算出しsave_graphが書き込むため、本カラム追加後の
> 取込・再splitでは自動的に埋まる。既存行は本カラム追加と同時にSQLのみでバックフィルする
> （PostGISのST_Azimuth/ST_StartPoint/ST_EndPointはgeomから直接計算できるため、
> アプリケーション側でgeometryをdecodeするバッチは不要）。
> 
> ST_Azimuth(a, b)は「aからbを見た方位角（ラジアン、北=0、時計回り）」を返す。degrees()で
> 度へ変換する。**geometry型のまま呼ぶ下のバックフィルは経度緯度を平面として扱った角度を
> 返し、domain/geo.py: bearing_between()（球面）とは一致しない**（緯度35度で最大約6度ずれる。
> 一致させるにはgeographyへキャストする必要がある）。この式はここに残すが、値としては
> 以後の再構築でPython側の算出に置き換わる。road_edgesの各行は既にfrom_node→to_nodeの向きにgeomが格納されている
> （domain/graph.py: build_road_graphがforward/backwardを別Edge行として持つ設計）ため、
> 各行のST_StartPoint/ST_EndPointをそのまま使えば向きの補正は不要。

```sql
ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS bearing_deg double precision;
UPDATE road_edges
SET bearing_deg = degrees(ST_Azimuth(ST_StartPoint(geom), ST_EndPoint(geom)))
WHERE bearing_deg IS NULL;
```

## 0014_axis_definitions

追加された日: 2026-08-24

> 改善計画T221 Stage D（評価軸のフルレジストリ駆動化＋GUI編集基盤、DBテーブル化）。
> ADR: docs/decisions/t221-axis-registry.md。
> 
> domain/axis_definitions.pyのAXIS_DEFINITIONS（Stage B/Cで確立した「軸定義データ」の
> 唯一のソース）をDBテーブルへ昇格させる。migration未適用・接続不可の環境では
> services/axis_registry_service.pyがWARNINGログを出しつつdomain/axis_definitions.py内蔵の
> 既定値へ安全側フォールバックするため、本migrationを本番へ適用するまでの間は評価の
> 振る舞いは一切変わらない（本番migration適用の緊急度が低い設計、docs/improvement-plan.md
> T74「本番DBが置き去りになる」の教訓を踏まえた意図的な安全側ロールアウト）。
> 
> shape_paramsはdomain/axis_definitions.pyのAxisShape（Pydantic Union）を
> `model_dump(mode="json")`した内容そのもの（"kind"フィールドで種別を判別、
> infrastructure/axis_definition_repository.py参照）。sort_orderは合成（composite）の
> 加算順として意味を持つ（AXIS_DEFINITIONSの辞書挿入順と同じ、Neumaier加算のビット一致
> 条件のため。tests/test_evaluation_bulk.py参照）。
> 軸レジストリ全体の版数（1行のみ）。管理API（axis_admin.py）の書き込みごとに
> インクリメントする。現時点ではプロセス内キャッシュの無効化には使わない
> （起動時＋管理API書き込み直後のpush型更新のみのため、同一プロセスではポーリング不要。
> ADR「Stage D設計メモ」参照）が、将来のマルチプロセス対応・監査用に記録しておく。
> 既存7軸をdomain/axis_definitions.pyのAXIS_DEFINITIONSからそのまま複製した初期データ
> （挙動が変わらないことがStage移行の前提、T239/Part2と同じ原則）。

```sql
CREATE TABLE IF NOT EXISTS axis_definitions (
axis_id TEXT PRIMARY KEY,
sort_order INTEGER NOT NULL,
shape_params JSONB NOT NULL,
default_weight DOUBLE PRECISION NOT NULL,
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS axis_registry_meta (
id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO axis_registry_meta (id, revision) VALUES (1, 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO axis_definitions (axis_id, sort_order, shape_params, default_weight) VALUES
('gradient', 0, '{"kind": "breakpoint_linear", "terms": [{"material": "gradient_percent", "weight": 1.0, "required": true}], "preprocess": "abs", "breakpoints": [[0.0, 0.0], [3.0, 25.0], [6.0, 50.0], [9.0, 75.0], [15.0, 100.0]]}', 0.15),
('wind', 1, '{"kind": "breakpoint_linear", "terms": [{"material": "wind_penalty", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [8.0, 100.0]]}', 0.26),
('surface_q', 2, '{"kind": "categorical", "material": "surface_good", "mapping": {"true": 0.0, "false": 80.0}}', 0.19),
('stop_density', 3, '{"kind": "breakpoint_linear", "terms": [{"material": "stop_count_per_km", "weight": 1.0, "required": true}, {"material": "intersection_count_per_km", "weight": 0.3, "required": false}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [4.0, 100.0]]}', 0.20),
('car_stress', 4, '{"kind": "recipe_then_breakpoint_linear", "terms": [{"material": "car_stress_level", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[1.0, 0.0], [5.0, 100.0]]}', 0.20),
('accident', 5, '{"kind": "breakpoint_linear", "terms": [{"material": "accident_count_per_km_year", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [0.5, 100.0]]}', 0.08),
('night', 6, '{"kind": "flag_sum", "flags": [["no_lit", 50.0], ["has_tunnel", 50.0]], "cap": 100.0}', 0.0);
```

## 0015_axis_definitions_label

追加された日: 2026-08-24

> 改善計画T269（軸カタログのDB追従、目論見書「二画面構想」Phase 2前提）。
> ADR: docs/decisions/t221-axis-registry.md。
> 
> 0014で作ったaxis_definitionsテーブルへ表示名（label/description/category）を追加する。
> domain/axis_definitions.pyのAxisDefinitionへ同じ3フィールドを追加済み。NOT NULL DEFAULTで
> 追加するため、0014が既に本番へ適用済みでも安全（既存7行はこのmigration内のUPDATEで
> 実際の値へbackfillし、以降の新規行はAxisRegistryAdminService経由で必ず明示的に
> 値が入る。DEFAULTは「予期せず素通りしたNOT NULL違反」を防ぐ保険）。
> 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
> domain/axis_definitions.py内蔵の既定値へ安全側フォールバックするため、本migrationを
> 本番へ適用するまでの間は評価の振る舞い・表示のいずれも変わらない（T74の教訓を踏まえた
> 意図的な安全側ロールアウト、0014と同じ方針）。
> 既存7軸のlabel/description/categoryをdomain/axis_definitions.pyのAXIS_DEFINITIONSから
> そのまま複製する（0014と同じ「挙動・表示が変わらないことがStage移行の前提」原則）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '',
ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '推定';
UPDATE axis_definitions SET label = '勾配', description = '登り坂の急さが小さいほど易しい', category = '観測' WHERE axis_id = 'gradient';
UPDATE axis_definitions SET label = '風', description = '向かい風が弱いほど易しい', category = '動的' WHERE axis_id = 'wind';
UPDATE axis_definitions SET label = '舗装質', description = '舗装路であるほど易しい', category = '観測' WHERE axis_id = 'surface_q';
UPDATE axis_definitions SET label = '停止密度', description = '信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい', category = '観測' WHERE axis_id = 'stop_density';
UPDATE axis_definitions SET label = '車の圧迫感', description = '推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)', category = '推定' WHERE axis_id = 'car_stress';
UPDATE axis_definitions SET label = '事故密度', description = '事故密度(件/(km・年)、警察庁統計)が低いほど易しい', category = '推定' WHERE axis_id = 'accident';
UPDATE axis_definitions SET label = '夜間', description = '街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)', category = '観測' WHERE axis_id = 'night';
```

## 0016_axis_definitions_is_published

追加された日: 2026-08-24

> 改善計画T271（軸の公開フローと統治ルール、Phase 3）。
> ADR: docs/decisions/t221-axis-registry.md。
> 
> axis_definitionsテーブルへ公開状態（is_published）を追加する。domain/axis_definitions.py:
> AxisDefinitionへ同じフィールドを追加済み（既定False=下書き）。一般ユーザーの保存設定
> （RouteSettingsPanelのプリセット・重み）はaxis_idキーで再現されるため、公開済み軸への
> 破壊的変更・削除はAxisRegistryAdminServiceが拒否する（check_publish_immutability）。
> 
> 既存7行（本番稼働中、いずれも一般ユーザーへ既に公開済み）は
> DEFAULT trueでbackfillされる（0014/0015と同じ「既存の挙動・表示が変わらないことが
> Stage移行の前提」原則）。以降の新規行（軸スタジオ経由の作成）はAxisRegistryAdminService/
> domain/axis_definitions.pyの既定False（下書き）が明示的に入るため、DEFAULT trueは
> 移行時のbackfillのみに働く一時的な安全弁（予期せず素通りしたNOT NULL違反を防ぐ保険）。
> 
> 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
> domain/axis_definitions.py内蔵の既定値（is_published=True、既存7軸分）へ安全側
> フォールバックするため、本migrationを本番へ適用するまでの間は評価の振る舞い・表示の
> いずれも変わらない。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT true;
```

## 0017_car_stress_axis_hierarchy

追加された日: 2026-08-24

> 改善計画T292（car_stress軸を内部軸5つ＋公開軸1つの階層構造で再定義）。
> ADR: docs/decisions/t221-axis-registry.md。
> 
> 専用Pythonレシピ（旧CarStressRecipe/RoadSuitabilityRecipe/MotorVehicleDensityRecipe/
> car_closeness/road_suitability/cycleway_adjustment/car_stress_level等、domain/recipe.py・
> domain/traffic.pyから削除済み）を廃止し、highway基準値＋4つの補正＋motor_vehicle=no
> 優先確定の計6内部軸（is_published=false、他の公開軸から参照される専用の推定軸）を
> 新規追加し、既存car_stress行のshape_paramsをこれら6内部軸を参照する階層構造へ
> 更新する。値はすべてdomain/axis_definitions.py: AXIS_DEFINITIONSのPythonコード内蔵値
> （`AxisShape.model_dump(mode="json")`の出力）と1:1で一致させてある（0014/0015/0016と
> 同じ「DBの内容とコード内蔵の既定値を一致させる」原則）。
> 
> 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
> domain/axis_definitions.py内蔵の新既定値（内部軸6つ込み）へ安全側フォールバックする
> ため、本migrationを本番へ適用するまでの間はコード側の新しい評価ロジックがそのまま
> 使われる（0014〜0016と異なり、今回はコード側が既に新ロジックへ切り替わっている点に
> 注意——本migration未適用でも挙動はコード内蔵値どおりで変わらない。ただし軸スタジオ
> 経由でcar_stressやその内部軸を編集したい場合はDB適用が前提となる）。
> 
> sort_orderは既存7軸（0-6）の後ろへ内部軸6つを追加する（7-12）。内部軸はis_published=false
> のため一般向けAPI（GET /api/axis-catalog）・3次合成の重み付け対象には含まれず、
> sort_order自体が評価結果へ影響することはない（domain/axis_definitions.py:
> topological_axis_orderが依存順で並べ替えるため）。
> 内部軸6つを新規追加。
> 既存car_stress行を内部軸6つを参照する階層構造のshape_paramsへ更新する
> （label/description/category/default_weight/is_published/sort_orderは変更なし）。

```sql
INSERT INTO axis_definitions (axis_id, sort_order, shape_params, default_weight, label, description, category, is_published) VALUES
('car_stress_highway_base', 7,
'{"kind": "categorical", "material": "highway", "mapping": {"cycleway": 1.0, "living_street": 1.0, "residential": 2.0, "unclassified": 2.0, "track": 2.0, "tertiary": 3.0, "tertiary_link": 3.0, "secondary": 3.0, "secondary_link": 3.0, "primary": 4.0, "primary_link": 4.0, "trunk": 4.0, "trunk_link": 4.0}}',
0.0, '車ストレス内部軸: highway基準値', 'highway種別による車の圧迫感の基準値(1-4、非公開)', '推定', false),
('car_stress_bicycle_infra_adjustment', 8,
'{"kind": "categorical", "material": "bicycle_infra", "mapping": {"separated": -2.0, "lane": -1.0, "shared_busway": 0.0, "shared_pedestrian": 0.0, "roadway": 1.0}}',
0.0, '車ストレス内部軸: 自転車インフラ補正', '自転車インフラ種別による補正(非公開)', '推定', false),
('car_stress_maxspeed_adjustment', 9,
'{"kind": "breakpoint_linear", "terms": [{"material": "maxspeed_kmh", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}',
0.0, '車ストレス内部軸: 制限速度補正', '制限速度による補正(非公開)', '推定', false),
('car_stress_lanes_adjustment', 10,
'{"kind": "breakpoint_linear", "terms": [{"material": "lanes_count", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}',
0.0, '車ストレス内部軸: 車線数補正', '車線数による補正(非公開)', '推定', false),
('car_stress_designation_adjustment', 11,
'{"kind": "categorical", "material": "is_designated", "mapping": {"true": 1.0, "false": 0.0}}',
0.0, '車ストレス内部軸: 指定路線補正', '指定路線(緊急輸送道路・重要物流道路)該当による補正(非公開)', '推定', false),
('car_stress_motor_vehicle_no_adjustment', 12,
'{"kind": "categorical", "material": "motor_vehicle_no", "mapping": {"true": -1000.0, "false": 0.0}}',
0.0, '車ストレス内部軸: 自動車通行不可の優先確定', 'motor_vehicle=noの区間を最良値へ強制する内部軸(非公開)', '推定', false);
UPDATE axis_definitions SET shape_params =
'{"kind": "breakpoint_linear", "terms": [{"material": "car_stress_highway_base", "weight": 1.0, "required": true}, {"material": "car_stress_bicycle_infra_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_maxspeed_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_lanes_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_designation_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_motor_vehicle_no_adjustment", "weight": 1.0, "required": false}], "preprocess": "identity", "breakpoints": [[1.0, 0.0], [5.0, 100.0]]}'
WHERE axis_id = 'car_stress';
```

## 0018_axis_definitions_priority_overrides

追加された日: 2026-08-24

> 改善計画T292（コードレビュー指摘の修正）。
> ADR: docs/decisions/t221-axis-registry.md。
> 
> axis_definitionsテーブルへ0次条件（priority_overrides）を追加する。domain/axis_definitions.py:
> AxisDefinition.priority_overridesへ同じフィールドを追加済み（改善計画T292）だが、
> このDBカラム・軸スタジオ管理API（axis_admin.py）双方への配線が漏れており、
> DB往復（起動時refresh_axis_definitions・管理API書き込み直後の反映）のたびに
> 設定した0次条件が黙って失われる欠陥がコードレビューで発覚した。
> 
> 既存13行（公開7軸＋car_stress内部軸6つ）はいずれもpriority_overrides=[]のため、
> NOT NULL DEFAULT '[]'でbackfillしても現在の評価結果に影響しない（0014〜0017と
> 同じ「既存の挙動が変わらないことが移行の前提」原則）。
> 
> 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
> domain/axis_definitions.py内蔵の既定値へ安全側フォールバックするため、本migrationを
> 本番へ適用するまでの間は評価の振る舞いは変わらない。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS priority_overrides JSONB NOT NULL DEFAULT '[]';
```

## 0019_axis_definitions_display_fields

追加された日: 2026-08-25

> 改善計画T310（ユーザー指示: 「今ハードコードされているところは、軸スタジオレコードに
> 対応付けて本番DBに移行してほしい」、2026-08-25）。
> ADR: docs/decisions/t221-axis-registry.md、docs/improvement-plan.md T310。
> 
> axis_definitionsテーブルへ地図チップ表示要素（icon_id/chip_label/panel_hint/
> proxy_hint/display_override）を追加する。以前はフロント（SECONDARY_AXIS_ICONS等）・
> backend（axis_display.py: STOP_DENSITY_DISPLAY等）にそれぞれ軸id→値のハードコード
> 辞書として存在し、軸スタジオ（DB）経由で編集・参照する経路が無かった（既存軸だけの
> 特別扱い）。domain/axis_definitions.py: AxisDefinitionへ同じフィールドを追加済み
> （改善計画T310）だが、このDBカラムへの配線が無いと、DB往復（起動時
> refresh_axis_definitions・管理API書き込み直後の反映）のたびに黙って失われる
> （0018 migrationのpriority_overrides追加時と同じ欠陥パターン、先回りして対処）。
> 
> 全カラムNULL許容（既定値なし）: 未設定は「フロント側の汎用フォールバックを使う」
> という意味を持つため、priority_overridesの`[]`既定のような「空だが確定した値」とは
> 性質が異なる。既存13行（公開7軸＋car_stress内部軸6つ）へのALTER TABLE ADD COLUMN
> 自体は全カラムNULLのままでも現在の評価結果・地図表示に影響しない（0014〜0018と
> 同じ「既存の挙動が変わらないことが移行の前提」原則）。
> 
> 続くUPDATE文は、domain/axis_definitions.py: AXIS_DEFINITIONSに手書きしたPython側の
> 既定値を、対応する軸スタジオレコード（本番DB行）へ同じ内容でbackfillする
> （ユーザー指示により、Pythonフォールバックだけでなく実際のDB行データとしても
> 同期させる）。値はaxis_definitions.pyから`model_dump(mode="json")`で機械的に
> 生成したもの（本migration作成時点、手で書き写していないため転記ミスが無い）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS icon_id VARCHAR,
ADD COLUMN IF NOT EXISTS chip_label VARCHAR,
ADD COLUMN IF NOT EXISTS panel_hint VARCHAR,
ADD COLUMN IF NOT EXISTS proxy_hint VARCHAR,
ADD COLUMN IF NOT EXISTS display_override JSONB;
UPDATE axis_definitions
SET icon_id = 'incline',
chip_label = '勾配',
proxy_hint = '（地図表示なし）標高レイヤーで確認できます'
WHERE axis_id = 'gradient';
UPDATE axis_definitions
SET icon_id = 'wave',
chip_label = '舗装'
WHERE axis_id = 'surface_q';
UPDATE axis_definitions
SET icon_id = 'crescent-moon',
chip_label = '夜間'
WHERE axis_id = 'night';
UPDATE axis_definitions
SET icon_id = 'density-stack',
chip_label = '停止密度',
panel_hint = '信号・横断歩道・一時停止・踏切等の停止要因が、沿線でどれだけ密集しているかの目安です。実際の位置は「停止要因」レイヤーで確認できます。',
display_override = '{"kind": "ramp", "label": "停止密度", "category": "trafficSafety", "tile_inputs": [{"property": "stop_per_km", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}, {"property": "intersection_per_km", "weight": 0.3, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [1.0, 2.0, 4.0], "unit": "回/km", "note": "信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた停止要因の密度。way単位の事前集計（way_attribute_counts）由来"}'::jsonb
WHERE axis_id = 'stop_density';
UPDATE axis_definitions
SET icon_id = 'warning-triangle',
chip_label = '圧迫感',
panel_hint = '道路種別・自転車インフラ・制限速度・車線数・指定路線・自動車通行可否から推定した車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして確認できます。',
display_override = '{"kind": "ramp", "label": "車の圧迫感", "category": "trafficSafety", "tile_inputs": [{"property": "highway", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": true, "categories": {"cycleway": 1.0, "living_street": 1.0, "residential": 2.0, "unclassified": 2.0, "track": 2.0, "tertiary": 3.0, "tertiary_link": 3.0, "secondary": 3.0, "secondary_link": 3.0, "primary": 4.0, "primary_link": 4.0, "trunk": 4.0, "trunk_link": 4.0}, "breakpoints": null}, {"property": "bicycle_infra", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"separated": -2.0, "lane": -1.0, "shared_busway": 0.0, "shared_pedestrian": 0.0, "roadway": 1.0}, "breakpoints": null}, {"property": "maxspeed_kmh", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}, {"property": "lanes_count", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}, {"property": "designation", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"emergency_transport": 1.0, "critical_logistics": 1.0, "both": 1.0}, "breakpoints": null}, {"property": "motor_vehicle_no", "weight": 1.0, "boolean": true, "invert": false, "true_value": -1000.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [2.0, 3.0, 4.0], "unit": "", "note": "改善計画T292: highway/bicycle_infra/maxspeed_kmh/lanes_count/designation/motor_vehicle_noの6材料から自動計算する。以前は専用の手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への階層再構成でtile_inputsの重み付き結合として表現できるようになった"}'::jsonb
WHERE axis_id = 'car_stress';
UPDATE axis_definitions
SET icon_id = 'density-scatter',
chip_label = '事故密度',
panel_hint = '警察庁の交通事故統計をもとに、自転車関連事故が沿線でどれだけ近くに集中しているかの目安です[死亡事故は重めに算入]。実際の発生地点は「事故」レイヤーで確認できます。',
display_override = '{"kind": "ramp", "label": "事故密度", "category": "trafficSafety", "tile_inputs": [{"property": "accident_per_km", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [0.4, 0.8, 1.5], "unit": "件/km", "note": "警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の距離正規化密度。way単位の事前集計（way_attribute_counts）由来。正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる"}'::jsonb
WHERE axis_id = 'accident';
```

## 0020_axis_definitions_show_map_icon

追加された日: 2026-08-25

> 改善計画T318（ユーザー判断: 「軸スタジオで、地図マップ上にアイコン表示するかどうか
> ON/OFFできるようにして。代役案内文(proxy_hint)は不要になるので消して」、2026-08-25）。
> 
> axis_definitionsテーブルへshow_map_icon（真偽値、地図上チップ・地図の見え方パネルの
> 両方からこの軸を丸ごと表示/除外する）を追加し、旧proxy_hint（0019 migration追加、
> 専用地図レイヤーを持たない軸向けの代役案内文）を撤去する。以前は専用レイヤーを
> 持たない軸を「常に無効化されたチップとして表示し、proxy_hintで理由を説明する」
> 仕組みだったが、そもそも表示しないという選択肢自体が持てるようになったことで
> proxy_hintは不要になった（domain/axis_definitions.py: AxisDefinition.show_map_icon
> のdocstring参照）。
> 
> show_map_iconはNOT NULL DEFAULT trueで追加する（priority_overridesの`[]`既定と同じ
> 「空だが確定した値」の考え方）。既存全軸が現在「地図上に表示される」状態のため、
> 既定trueにすることでbackfillのUPDATE文なしに現在の挙動を保てる（0016
> is_published追加時と同じ「既定値=移行時の安全側の値」パターン）。
> 
> proxy_hintのDROPは不可逆だが、実データを持つのはgradient軸1件のみ
> （0019 migration参照）で、その内容（案内文の文言）はこのmigration適用と同時に
> コード側（domain/axis_definitions.py）からも削除済みのため、DB側にだけ残しておく
> 意味が無い。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS show_map_icon BOOLEAN NOT NULL DEFAULT true,
DROP COLUMN IF EXISTS proxy_hint;
```

## 0021_bicycle_infra_axis

追加された日: 2026-08-26

> 改善計画T347（ユーザー指示: 「同等の軸を登録し、bicycle_infraを削除したい」
> 「フォールバックも不要」「classify_bicycle_infrastructureの存在自体がPython側に
> 生データ加工ロジックを持たせない設計原則に反する」、2026-08-26）。
> 
> material_catalog.pyのbicycle_infra材料（優先順位付き分類）・domain/traffic.py:
> classify_bicycle_infrastructure・MVTタイルのbicycle_infraプロパティを削除し、
> 既に評価に使われている正規化フラグ材料4種（highway_is_cycleway/cycleway_has_track/
> cycleway_has_lane/cycleway_has_shared、domain/recipe.py: bicycle_infra_flags）だけを
> 正準とする。本migrationは対応するDB側の変更3点をまとめる。
> 
> (1) car_stress_bicycle_infra_adjustment内部軸のshape_paramsドリフト修正。
> 改善計画T336でコード側（axis_definitions.py）は categorical(material="bicycle_infra")
> から breakpoint_linear（正規化フラグ4種の重み付き線形和、実データ検証済み
> 0.0127%ズレ）へ既に切り替わっていたが、対応するmigrationが一度も書かれておらず
> 0017 migrationのshape_paramsが旧categorical形のまま残っていた（T347着手時に発覚。
> 本タスク以前から存在した潜在バグ）。bicycle_infra材料をこのmigrationで削除する
> ため、ここで放置すると本migration適用環境で「存在しない材料を参照する」壊れた
> shape_paramsになる。値はdomain/axis_definitions.py:
> AXIS_DEFINITIONS["car_stress_bicycle_infra_adjustment"].shape.model_dump(mode="json")
> の出力と1:1で一致させてある（0014〜0020と同じ「DBの内容とコード内蔵の既定値を
> 一致させる」原則）。
> (2) 新設の公開軸「自転車インフラ」（bicycle_infra_quality）を追加する。
> 正規化フラグ4種を直接持たず、car_stress_bicycle_infra_adjustment（同じ4フラグの
> 重み付き線形和、実データ検証済み）を単一の材料（軸参照）として受け取り、
> breakpointsだけをdifficultyの規約（0=最も走りやすい・100=最も走りにくい）へ
> 線形再スケールする（ユーザー指摘: 生の4材料を2軸が別々に持つと
> check_material_exclusivity[材料の排他帰属チェック]が二重計上として拒否するため、
> car_stress自身が内部軸を合成するのと同じ階層構造[改善計画T292]へ作り替えた）。
> sort_orderは既存0-12（公開7軸+car_stress内部軸6つ）の次の13
> （axis_registry_service.create()のsort_order算出と同じ「既存最大+1」原則）。
> 地図表示は持たない（show_map_icon=false。旧bicycle_infraタイルプロパティ自体を
> 削除したため、この4フラグから地図ramp用のタイル値を新設しない限り地図表示
> できず、今回はスコープ外）。値はdomain/axis_definitions.py:
> AXIS_DEFINITIONS["bicycle_infra_quality"]と1:1で一致させてある。
> (3) car_stress軸のdisplay_override（地図ランプ表示宣言）から、削除するbicycle_infra
> タイルプロパティを参照するtile_inputを取り除き、note文言を6材料→5材料へ更新する
> （Python側のdomain/axis_definitions.py: AXIS_DEFINITIONS["car_stress"]は既に
> この内容へ更新済み。評価側のcar_stress自身のterms
> [car_stress_bicycle_infra_adjustment内部軸]には影響しない、地図ランプ表示専用の
> tile_inputsのみの変更）。

```sql
UPDATE axis_definitions SET shape_params =
'{"kind": "breakpoint_linear", "terms": [{"material": "highway_is_cycleway", "weight": -4.0, "required": true}, {"material": "cycleway_has_track", "weight": -4.0, "required": true}, {"material": "cycleway_has_lane", "weight": -2.0, "required": true}, {"material": "cycleway_has_shared", "weight": -1.0, "required": true}], "preprocess": "identity", "breakpoints": [[-11.0, -2.0], [-4.0, -2.0], [-3.0, -1.0], [-2.0, -1.0], [-1.0, 0.0], [0.0, 1.0]]}'
WHERE axis_id = 'car_stress_bicycle_infra_adjustment';
INSERT INTO axis_definitions
(axis_id, sort_order, shape_params, default_weight, label, description, category, is_published, chip_label, show_map_icon) VALUES
('bicycle_infra_quality', 13,
'{"kind": "breakpoint_linear", "terms": [{"material": "car_stress_bicycle_infra_adjustment", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[-2.0, 0.0], [-1.0, 33.3], [0.0, 66.7], [1.0, 100.0]]}',
0.15, '自転車インフラ', '専用の自転車インフラ（分離自転車道・自転車レーン等）が整備されているほど易しい。', '推定', true,
'自転車道', false);
UPDATE axis_definitions
SET display_override = '{"kind": "ramp", "label": "車の圧迫感", "category": "trafficSafety", "tile_inputs": [{"property": "highway", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": true, "categories": {"cycleway": 1.0, "living_street": 1.0, "primary": 4.0, "primary_link": 4.0, "residential": 2.0, "secondary": 3.0, "secondary_link": 3.0, "tertiary": 3.0, "tertiary_link": 3.0, "track": 2.0, "trunk": 4.0, "trunk_link": 4.0, "unclassified": 2.0}, "breakpoints": null}, {"property": "maxspeed_kmh", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}, {"property": "lanes_count", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}, {"property": "designation", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"both": 1.0, "critical_logistics": 1.0, "emergency_transport": 1.0}, "breakpoints": null}, {"property": "motor_vehicle_no", "weight": 1.0, "boolean": true, "invert": false, "true_value": -1000.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [2.0, 3.0, 4.0], "unit": "", "note": "改善計画T292: highway/maxspeed_kmh/lanes_count/designation/motor_vehicle_noの5材料から自動計算する。以前は専用の手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への階層再構成でtile_inputsの重み付き結合として表現できるようになった（改善計画T347でbicycle_infraタイルプロパティ自体を削除したため6→5材料へ）"}'::jsonb
WHERE axis_id = 'car_stress';
```

## 0022_remove_car_stress_bicycle_infra_adjustment

追加された日: 2026-08-27

> 改善計画T353/T359/T360。
> 
> T353: car_stress_bicycle_infra_adjustment内部軸（`highway_is_cycleway`等4正規化
> フラグ材料を`car_stress`と`bicycle_infra_quality`の両方が軸参照経由[T292]で共有する
> 構造）が、材料の排他帰属原則（改善計画T268: check_material_exclusivity、1つの材料は
> 原則1つの軸だけが使う）と矛盾していたため廃止する。`car_stress`から自転車インフラ
> 由来の調整を完全に排除し、`bicycle_infra_quality`だけが正規化フラグ材料を直接持つ
> 設計へ是正する。
> 
> T359: 王子-荒川ルート検索がヒットしない問題（本タスクの発端）への対応を合わせて含む。
> `car_stress_highway_base`のmappingに`footway`/`path`を追加（車ストレス軸が評価不能
> だった問題の解消）。`bicycle_infra_quality`に5つ目の材料`shared_pedestrian_path`
> （highway=footway/pathかつbicycle=yes/designated、河川敷サイクリングロード等の
> 共用歩行者自転車道を検知）を追加。
> 
> T360: T353実施時、この変更をmigrationではなくaxis_adminのAPI直接操作（unpublish->
> PUT->republish、DELETE）でdev DBにのみ適用したため、fresh bootstrap（CI・新規開発
> 環境・disaster recovery等、まっさらなDBへ全migrationを順に適用する経路）では
> car_stress_bicycle_infra_adjustmentが14件目として復活してしまう不整合が発覚した
> （T360で起票）。本migrationはこの不整合を解消し、dev DBで実際にAPI経由で適用済みの
> 最終状態（13軸）を、migration適用だけでも再現できるようにする。
> 
> 値はいずれもdev DBでAPI経由（PUT /api/admin/axis-definitions/{axis_id}）適用済みの
> 実際の値と1:1で一致させてある（0014〜0021と同じ「DBの内容とコード内蔵/適用済みの
> 値を一致させる」原則）。
> (1) car_stress_highway_base: footway/pathを追加（値1.0、cycleway・living_streetと
> 同格）。あわせてchip_label/show_map_iconを、現行のaxis_adminバリデーション
> （show_map_icon=trueかつchip_label未設定ならlabel4文字以内を要求、この軸の
> labelは20文字）を満たす値へ修正する（内部軸は元々地図チップに表示されない
> ため、show_map_icon=falseが意味的にも正しい）。
> (2) bicycle_infra_quality: car_stress_bicycle_infra_adjustment（軸参照）をやめ、
> highway_is_cycleway/cycleway_has_track/cycleway_has_lane/cycleway_has_sharedの
> 4正規化フラグ材料を直接参照する（旧2段階のbreakpoint_linear変換を1段階へ
> 数学的に正確に合成、実データで発生する全パターンで旧来と同じ出力）。
> さらに5つ目の材料shared_pedestrian_pathを追加（重み-4.0、track/highway=
> cycleway同格）。breakpointsは[[-4,0],[-2,33.3],[-1,66.7],[0,100]]。
> (3) car_stress: car_stress_bicycle_infra_adjustmentへの参照をtermsから削除。
> breakpointsを[[1.0,0.0],[5.0,100.0]]から[[0.0,0.0],[4.0,100.0]]へ再較正する
> （自転車インフラのベースラインオフセット+1を除去したことに対応。インフラ
> 非該当の道路では旧来と評価が完全一致するよう調整済み。自転車インフラの恩恵は
> 今後bicycle_infra_quality軸の重み付けのみで反映される、評価の意味の変更を
> 伴う——実データでの影響は86,642件中3,942件[4.5%]、T353本文参照）。
> (4) car_stress_bicycle_infra_adjustment内部軸を削除する。上記(2)(3)で参照を
> 外した後のため、削除後も他の軸から参照されない孤立軸を残さない。

```sql
UPDATE axis_definitions SET
shape_params = '{"kind": "categorical", "mapping": {"path": 1.0, "track": 2.0, "trunk": 4.0, "footway": 1.0, "primary": 4.0, "cycleway": 1.0, "tertiary": 3.0, "secondary": 3.0, "trunk_link": 4.0, "residential": 2.0, "primary_link": 4.0, "unclassified": 2.0, "living_street": 1.0, "tertiary_link": 3.0, "secondary_link": 3.0}, "material": "highway"}'::jsonb,
chip_label = '道路基準',
show_map_icon = false
WHERE axis_id = 'car_stress_highway_base';
UPDATE axis_definitions SET
shape_params = '{"kind": "breakpoint_linear", "terms": [{"weight": -4.0, "material": "highway_is_cycleway", "required": true}, {"weight": -4.0, "material": "cycleway_has_track", "required": true}, {"weight": -2.0, "material": "cycleway_has_lane", "required": true}, {"weight": -1.0, "material": "cycleway_has_shared", "required": true}, {"weight": -4.0, "material": "shared_pedestrian_path", "required": true}], "preprocess": "identity", "breakpoints": [[-4.0, 0.0], [-2.0, 33.3], [-1.0, 66.7], [0.0, 100.0]]}'::jsonb,
description = '専用の自転車インフラ（分離自転車道・自転車レーン等、河川敷サイクリングロード等の自転車通行可の歩行者道を含む）が整備されているほど易しい。'
WHERE axis_id = 'bicycle_infra_quality';
UPDATE axis_definitions SET
shape_params = '{"kind": "breakpoint_linear", "terms": [{"weight": 1.0, "material": "car_stress_highway_base", "required": true}, {"weight": 1.0, "material": "car_stress_maxspeed_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_lanes_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_designation_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_motor_vehicle_no_adjustment", "required": false}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [4.0, 100.0]]}'::jsonb,
description = '推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数の指標で、信号や交差点の頻度は含まない(別軸)。自転車インフラの有無は別軸(自転車インフラ)で評価します。',
panel_hint = '道路種別・制限速度・車線数・指定路線・自動車通行可否から推定した車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして確認できます。'
WHERE axis_id = 'car_stress';
DELETE FROM axis_definitions WHERE axis_id = 'car_stress_bicycle_infra_adjustment';
```

## 0023_axis_definitions_time_scope_route_coloring

追加された日: 2026-08-28

> 改善計画T352（axis_idハードコード分岐を宣言的フィールドへ汎用化）。
> 
> axis_definitionsテーブルへ2つの宣言的フィールドを追加する。
> 
> 1. time_scope（TEXT、既定'always'）: この軸の重みが常に有効か、特定の時間帯
> （現状は'night_only'のみ）でのみ有効かの宣言。従来road_graph_engine.py/
> openrouteservice_engine.pyがaxis_id"night"を直接ハードコード分岐していた
> T173ロジックを、この性質ベースのフィールドへ置き換える
> （domain/axis_definitions.py: AxisDefinition.time_scope・time_scoped_weights参照）。
> 既存全軸は'always'が正しい既定値のため、night軸のみ明示的に'night_only'へ
> backfillする。
> 
> 2. supports_route_coloring（BOOLEAN、既定false）: この軸のdifficultyを、
> ルート地図の色分けモード（frontend routeStyleModes.ts）の選択肢として動的に
> 使えるかの宣言。従来RouteStyleModeIdが"wind"を直接ハードコードしていたのを
> 置き換える。wind軸のみtrueへbackfillする（gradientは対象外のまま——生材料
> gradient_percentを直接読む特殊実装のため、domain/axis_definitions.py:
> AxisDefinition.supports_route_coloringのdocstring参照）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS time_scope TEXT NOT NULL DEFAULT 'always',
ADD COLUMN IF NOT EXISTS supports_route_coloring BOOLEAN NOT NULL DEFAULT false;
UPDATE axis_definitions SET time_scope = 'night_only' WHERE axis_id = 'night';
UPDATE axis_definitions SET supports_route_coloring = true WHERE axis_id = 'wind';
```

## 0024_derived_data_lineage

追加された日: 2026-08-30

> 改善計画T351: 派生データの世代管理・Raw→Derived系譜追跡の強化。
> 
> edge_attribute_counts/way_attribute_countsはcomputed_atしか持たず、(a) どのimport_runの
> 内容から計算したか、(b) 「入力データが古い」のか「計算ロジックが変わった」のかを
> DB上で区別する手段が無かった（T350のDB設計書レビューで指摘）。
> 
> source_accident_import_run_id/source_osm_import_run_idは、バッチ実行時点で
> accident_import_runs/osm_import_runsのstatus='succeeded'な行の中でのMAX(id)を記録する
> （＝厳密な行単位の系譜ではなく「この計算はどのデータ世代までを見ていたか」の高水位マーク。
> accident_import_runsは年ごとに複数行が積み上がる設計のため、全年度の一覧ではなく
> 単調増加するidの最大値を比較することで新規取込の有無を検出できれば十分という判断）。
> 新しいimport_runが成功するたびにこの値は増加するため、記録済みの値と現在のMAX(id)を
> 比較するだけで「再計算が必要か」を機械的に判定できるようになる。
> 
> algorithm_versionは計算ロジック自体（半径・重み付け等のパラメータ）のバージョンで、
> 入力データが変わらなくてもロジック変更時は値が変わる（region_service.py:
> ROAD_SURFACE_TILE_VERSIONと同じ「手動で上げる版数文字列」の考え方）。
> designation_attributesは1(osm_way_id, kind)に対し複数のroute_designations行が
> ST_Unionで寄与しうる（match_designations.pyのdocstring参照）ため、単一FKでは表現できない
> （T351が指摘した「同kindの複数route_designations行が同じWayへマッチした場合、どの行が
> 実際にマッチしたか特定できない」問題への対応）。実際にマッチへ寄与した全route_designations.id
> を配列で保持する。source_osm_import_run_idはosm_raw_ways側の系譜追跡（上記2テーブルと
> 同じ高水位マーク方式）。data_version列は既にバッファ幅（アルゴリズムパラメータ）を
> 記録済みのため、algorithm_versionは新設しない。

```sql
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS source_accident_import_run_id integer REFERENCES accident_import_runs(id) ON DELETE SET NULL;
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS algorithm_version text;
ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS source_accident_import_run_id integer REFERENCES accident_import_runs(id) ON DELETE SET NULL;
ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS algorithm_version text;
ALTER TABLE designation_attributes ADD COLUMN IF NOT EXISTS matched_route_designation_ids integer[];
ALTER TABLE designation_attributes ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
```

## 0025_axis_definitions_display_thresholds_override

追加された日: 2026-08-30

> 改善計画T404（display_override廃止方針、docs/tasks/T404.md）。
> 
> axis_definitionsテーブルへ地図の色分けしきい値だけを差し替える軽量な上書き
> （display_thresholds_override）を追加する。domain/axis_definitions.py:
> AxisDefinition.display_thresholds_overrideへ同じフィールドを追加済み。
> 
> NULL許容（既定値なし）: 未設定は「derive_ramp_inputsが計算したしきい値をそのまま使う」
> という意味を持つため、既存行へのALTER TABLE ADD COLUMN自体は全行NULLのままでも
> 現在の評価結果・地図表示に影響しない（0019 migrationのdisplay_override追加時と
> 同じ「既存の挙動が変わらないことが移行の前提」原則）。
> 
> CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（既存
> car_stress/stop_density/accident 3軸のdisplay_thresholds_override設定・
> display_overrideのNULL化）はこのmigrationではなくaxis_admin API（unpublish→
> PUT→republish）経由で行う。本migrationはテーブル構造（DDL）のみを追加する。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS display_thresholds_override JSONB;
```

## 0026_axis_definitions_drop_display_override

追加された日: 2026-08-30

> 改善計画T409（display_override廃止の最終処理、docs/tasks/T409.md）。
> 
> T404でcar_stress/stop_density/accidentの3軸（旧display_overrideの唯一の利用者）を
> display_thresholds_overrideへ移行し、3軸ともdisplay_overrideをNULLへ戻し済み
> （T404完了時点でdev DBを確認済み）。旧display_overrideフィールド自体（コード側の
> AxisDefinition.display_override・axis_display_for()の後方互換フォールバック分岐・
> axis_admin.pyのPayload/Responseフィールド・axis_definition_repository.pyの(逆)
> シリアライズは本migrationと同一コミットで削除済み）に続き、DBカラムも削除する。
> 
> CLAUDE.md「コミット時の同期ルール」により、axis_definitionsのテーブル構造（DDL）変更は
> backend/migrations/で行う（行データの変更ではなくスキーマ変更のためこの経路が正しい）。
> 
> 適用前提: 全行のdisplay_overrideがNULLであること（着手時にdev DBで確認済み）。
> 本番DBへの適用はCLAUDE.md「既存DBの行データを新しいコードが読めなくなる変更を含む
> backend変更は、本番DBのデータ移行を完了させてからpushする」の対象——本migrationは
> 既存行のdisplay_overrideが全てNULLである前提のためデータ損失は起きないが、
> 本番backendが新コード（display_overrideカラムを一切読み書きしない）へ切り替わる前に
> このDROP COLUMNを本番DBへ適用する必要は無い一方、pushのタイミングは本番運用への
> 影響を考慮してユーザー判断とする（docs/tasks/T409.md参照）。

```sql
ALTER TABLE axis_definitions
DROP COLUMN IF EXISTS display_override;
```

## 0027_axis_definitions_dedicated_way_value_layer

追加された日: 2026-08-30

> 軸スタジオの評価軸定義へ「専用のway_id→値配信レイヤー（Redis経由）を持つか」の
> 宣言的フィールド（dedicated_way_value_layer）を追加する。domain/axis_definitions.py:
> AxisDefinition.dedicated_way_value_layerへ同じフィールドを追加済み。
> 
> 従来frontend側（RouteSettingsPanel.tsx/mapLayers.ts/MapView.tsx）がaxis_idの
> 文字列比較（"wind"/"gradient"）で直接ハードコード分岐していた。この2軸だけが
> 専用のway_id→値配信レイヤー（backend/app/infrastructure/dynamic_way_value_cache.py）を
> 持つためルート未確定時から地図上で線色分け表示できるが、これは軸の評価ロジック
> （shape）自体からは自動導出できない工学的事実のため、supports_route_coloringと
> 同様に明示的なフィールドとして持たせる。
> 
> NOT NULL DEFAULT false（既定値なし＝この専用レイヤーを持たない大多数の軸の
> 実際の状態と一致するため、既存行へのALTER TABLE ADD COLUMN自体は全行falseの
> ままでも現在の挙動に影響しない）。
> 
> CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（wind/gradientの
> dedicated_way_value_layer=trueへのbackfill）はこのmigrationではなくaxis_admin API
> （unpublish→PUT→republish）経由で行う。本migrationはテーブル構造（DDL）のみを追加する
> （0025_axis_definitions_display_thresholds_override.sqlと同じ方針）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS dedicated_way_value_layer BOOLEAN NOT NULL DEFAULT false;
```

## 0028_axis_definitions_dynamic_way_value_needs

追加された日: 2026-08-31

> 軸スタジオの評価軸定義へ「dedicated_way_value_layer=trueの軸のGET /api/region/
> dynamic-way-values/{material_id}/...がat/bearing_degクエリパラメータを必須とするか」の
> 宣言的フィールド（dynamic_way_value_needs_time/dynamic_way_value_needs_bearing）を
> 追加する。domain/axis_definitions.py: AxisDefinitionへ同じフィールドを追加済み。
> 
> 従来domain/dynamic_way_values.py: DYNAMIC_WAY_VALUE_MATERIALSが軸スタジオ
> （dedicated_way_value_layer）とは独立したPython辞書へこの値をハードコードしており、
> 3件目の動的材料を追加するには軸スタジオでの登録に加えてコード変更・再デプロイが必要
> だった（改善計画T458）。dedicated_way_value_layerと同様、この値自体は軸の評価ロジック
> （shape）からは自動導出できない工学的事実のため、明示的なフィールドとして持たせる。
> 
> NOT NULL DEFAULT false（既定値なし＝dedicated_way_value_layer=falseの大多数の軸では
> 意味を持たないフィールドのため、既存行へのALTER TABLE ADD COLUMN自体は全行falseの
> ままでも現在の挙動に影響しない）。
> 
> CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（wind/gradientの
> 実際の値へのbackfill）はこのmigrationではなくaxis_admin API（unpublish→PUT→republish）
> 経由で行う。本migrationはテーブル構造（DDL）のみを追加する
> （0027_axis_definitions_dedicated_way_value_layer.sqlと同じ方針）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_time BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_bearing BOOLEAN NOT NULL DEFAULT false;
```

## 0029_axis_definitions_display_band_labels_override

追加された日: 2026-08-31

> 改善計画T513（docs/tasks/T513.md）。
> 
> axis_definitionsテーブルへ、display_thresholds_overrideと対になる段階ごとの体感
> ラベルの軽量な上書き（display_band_labels_override）を追加する。domain/
> axis_definitions.py: AxisDefinition.display_band_labels_overrideへ同じフィールドを
> 追加済み。
> 
> NULL許容（既定値なし）: 未設定は「数値レンジ表記のみの凡例を使う」という意味を持つ
> ため、既存行へのALTER TABLE ADD COLUMN自体は全行NULLのままでも現在の地図表示に
> 影響しない（0025 migrationのdisplay_thresholds_override追加時と同じ「既存の挙動が
> 変わらないことが移行の前提」原則）。
> 
> CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（風軸への
> display_band_labels_override設定）はこのmigrationではなくaxis_admin API（T501の
> 表示専用フィールド直接編集）経由で行う。本migrationはテーブル構造（DDL）のみを
> 追加する。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS display_band_labels_override JSONB;
```

## 0030_axis_definitions_drop_route_coloring

追加された日: 2026-09-03

> 改善計画T549（docs/tasks/T549.md）。
> 
> axis_definitionsテーブルから0023 migrationが追加したsupports_route_coloringカラムを
> 削除する。従来はこのフラグがtrueの軸だけがルート地図の色分けモード（frontend
> routeStyleModes.ts）の選択肢として現れる設計だったが、この機構の対象外になる軸は
> 技術的に存在しないと判明したため、フラグを撤去し全公開軸を無条件で対象にする設計へ
> 変更した（domain/axis_definitions.py: AxisDefinitionのdocstring参照）。
> 
> CLAUDE.md「コミット時の同期ルール」により、本migrationはテーブル構造（DDL）のみを
> 変更する。time_scopeカラム（0023で同時追加）はこのタスクの対象外のため変更しない。

```sql
ALTER TABLE axis_definitions
DROP COLUMN IF EXISTS supports_route_coloring;
```

## 0031_axis_definitions_dynamic_way_value_needs_speed

追加された日: 2026-09-05

> 軸スタジオの評価軸定義へ「dedicated_way_value_layer=trueの軸のGET /api/region/
> dynamic-way-values/{material_id}/...がspeed_kmhクエリパラメータを必須とするか」の
> 宣言的フィールド（dynamic_way_value_needs_speed）を追加する。0028の
> dynamic_way_value_needs_time/needs_bearingと同型（domain/axis_definitions.py:
> AxisDefinition.dynamic_way_value_needs_speed参照）。
> 
> NOT NULL DEFAULT false。既存行の実際の値（風軸が走行速度依存の材料wind_drag_ratioへ
> 切り替わった時点でtrue）はこのmigrationではなくaxis_admin API経由で設定する
> （テーブル構造のみを管理する方針、CLAUDE.md「コミット時の同期ルール」）。

```sql
ALTER TABLE axis_definitions
ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_speed BOOLEAN NOT NULL DEFAULT false;
```

## 0032_add_way_landcover

追加された日: 2026-09-06

> Way単位の土地被覆クラス別割合（Esri×Impact Observatory Sentinel-2 10m Annual LULC由来）。
> 道路centerlineの周囲100mリング内画素をクラスごとに集計し割合(%)へ変換したもの
> （算出ロジックはdomain/landcover.py、事前計算はbatch/precompute_way_landcover.py）。
> 適用後はprecompute_way_landcover.pyの実行が必須（適用しただけではテーブルが空のまま、
> 他のprecomputeバッチと同じ運用）。

```sql
CREATE TABLE IF NOT EXISTS way_landcover (
osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
valid_pixels              integer NOT NULL,
water_percent             real NOT NULL,
trees_percent             real NOT NULL,
flooded_veg_percent       real NOT NULL,
crops_percent             real NOT NULL,
built_percent             real NOT NULL,
bare_percent              real NOT NULL,
snow_ice_percent          real NOT NULL,
rangeland_percent         real NOT NULL,
data_source               text NOT NULL,
data_version              text NOT NULL,
computed_at               timestamptz NOT NULL,
source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
algorithm_version         text
);
```

## 0033_add_poi_counts_by_kind

追加された日: 2026-09-08

> 停止要因POIの種別別カウント。既存の`stop_count`（種別を捨てた合計）と並走させ、
> 評価軸が種別ごとの重みを持てるようにする（`domain/traffic.py: POI_COUNT_KINDS`が
> キーの単一ソース、集計は`RoadGraphRepository`のSQLが行う）。
> 
> 種別ごとの実カラムではなくjsonbにするのは、キーを増やすときにmigration・ORM・
> タイルSQL・材料の4箇所ではなくキー一覧の1箇所だけを触れば済むようにするため
> （docs/tasks/T655.md「集計キー」参照）。
> 
> 適用後は precompute_edge_attribute_counts.py / precompute_way_attribute_counts.py の
> 再実行が必須（適用しただけでは空のjsonbのまま、他のprecomputeバッチと同じ運用）。

```sql
ALTER TABLE edge_attribute_counts
ADD COLUMN IF NOT EXISTS poi_counts jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE way_attribute_counts
ADD COLUMN IF NOT EXISTS poi_counts jsonb NOT NULL DEFAULT '{}'::jsonb;
```

## 0034_poi_counts_null_means_not_aggregated

追加された日: 2026-09-08

> `poi_counts`の「未集計」と「集計済みで0件」を区別できるようにする。
> 
> 0033はNOT NULL DEFAULT '{}'で追加したため、集計バッチを流す前の既存行が
> 「集計済みで0件」と区別できず、材料が0として評価される（軸が全区間で0点になり、
> ルート選択が静かに歪む）。NULL可へ変え、NULLを「未集計＝材料は欠損」の意味にする
> （`elevation_attributes`等が「行の有無」で同じことを表しているのと同じ流儀）。
> 
> 集計バッチは0件でも空のjsonbを明示的に書くため、実行後は`{}`＝集計済みで0件になる。
> edge側は集計バッチが一度も完走していない（poi_countsが非空の行が0件）ため、
> 既存の'{}'はすべて「未集計」を意味する。way側はバッチ完了済みで'{}'が
> 「集計済みで0件」の正しい値のため、触らない。

```sql
ALTER TABLE edge_attribute_counts ALTER COLUMN poi_counts DROP NOT NULL;
ALTER TABLE edge_attribute_counts ALTER COLUMN poi_counts DROP DEFAULT;
ALTER TABLE way_attribute_counts ALTER COLUMN poi_counts DROP NOT NULL;
ALTER TABLE way_attribute_counts ALTER COLUMN poi_counts DROP DEFAULT;
UPDATE edge_attribute_counts SET poi_counts = NULL WHERE poi_counts = '{}'::jsonb;
```

## 0035_add_road_edges_curvature

追加された日: 2026-09-10

> road_edgesへ「蛇行の強さ」（度/km、domain/geo.py: curvature_deg_per_km）を持たせる。
> 折れ線の頂点ごとの方位変化を積み上げ距離kmで割った値で、直線は0・つづら折りほど大きい。
> 
> NULLは「未計算」であって「まっすぐ(0)」ではない。既存行は再splitされるまでNULLのままの
> ため、適用後は app/batch/precompute_edge_curvature.py の実行が必須
> （NOT NULL DEFAULT 0 にすると未計算を「まっすぐ」と読んでしまい、評価が静かに歪む。
> 同じ形の障害をdocs/tasks/T655.mdで起こしている）。
> 
> 本番500万行の再計算はこのmigrationでは行わない（デプロイ時に自動適用されるため、
> 長時間のUPDATEをここへ置くとデプロイが詰まる）。バッチで別途流す。

```sql
ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS curvature_deg_per_km double precision;
```

## 0036_add_way_geometry

追加された日: 2026-09-10

> Way単位の形状由来スカラー（osm_raw_ways.geomの折れ線から測る値）。
> 現在の中身は蛇行の強さ（度/km、domain/geo.py: curvature_deg_per_km）1列で、
> 事前計算はbatch/precompute_way_curvature.py。
> 
> road_edges.curvature_deg_per_km（Edge単位、ルート評価用）と並存する:
> road_edgesはルート生成時に遅延構築される派生データのため、地図タイル・区間インスペクタ・
> 軸スタジオの分布プレビューが母集団にできない（way_attribute_countsと同じ理由）。
> 同じ材料をwayの折れ線そのものに対して測るため、wayを切り出す交差点頂点の折れも含み、
> 値はEdge単位の延長加重平均以上になる。
> 
> 行が無い＝未計算（バッチ未実行・取込直後）、列がNULL＝算出不能（頂点1点・長さ0）。
> 適用後はprecompute_way_curvature.pyの実行が必須（他のprecomputeバッチと同じ運用）。

```sql
CREATE TABLE IF NOT EXISTS way_geometry (
osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
curvature_deg_per_km      double precision,
computed_at               timestamptz NOT NULL,
source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
algorithm_version         text
);
```

## 0037_way_landcover_null_means_no_value

追加された日: 2026-09-10

> `way_landcover`の「未計算」と「計算済み・値なし」を区別できるようにする。
> 
> precompute_way_landcover.pyの増分実行は`way_landcover`に行が無いwayを対象にするため、
> ラスタ範囲外・境界またぎ・有効画素不足のway（行を作らない）は実行のたびに毎回
> ラスタ読み込みからやり直される。結果は毎回同じ「値なし」で、全国展開でラスタが
> 複数枚になると境界またぎのwayが増え、再実行のたびに効いてくる。
> 
> 割合8列とvalid_pixelsをNULL可へ変え、NULLを「計算済み・値なし」の意味にする
> （0034で`poi_counts`へ同じ意味づけを与えたのと同じ流儀）。既存行はすべて値を持つため
> 意味は変わらない。読み出しはいずれもLEFT JOINで列を参照する形のため、NULL列は
> 「行が無い」場合と同じく欠損として扱われる。
> 「値なし」と確定させたときのラスタ構成の指紋（precompute_way_landcover.py:
> raster_set_fingerprint）。ラスタを足せば境界またぎ・範囲外のwayは値を持ちうるため、
> 指紋が変われば増分実行が値なし行を対象に戻す。値を持つ行では意味を持たない。

```sql
ALTER TABLE way_landcover ALTER COLUMN valid_pixels DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN water_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN trees_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN flooded_veg_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN crops_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN built_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN bare_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN snow_ice_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN rangeland_percent DROP NOT NULL;
ALTER TABLE way_landcover ADD COLUMN IF NOT EXISTS source_raster_set text;
```

## 0038_drop_stop_count_columns

追加された日: 2026-09-11

> 停止要因の旧集計列`stop_count`を`edge_attribute_counts`・`way_attribute_counts`から落とす。
> 
> 停止密度は停止要因POIの種別別密度（`poi_counts`、0033で追加）だけを材料にする形へ
> 移行済みで、`stop_count`（線から15m以内にあるSTOP_POI_KINDS該当POIの総数）を読む
> 経路はコード上に無くなった。数え方そのものが「自分が走る道の上に無い点」「1つの
> 信号交差点を複数ノード」まで数えるもので、`poi_counts`で置き換わっている。
> 
> 列を残しても読み手が無い一方、毎回の集計バッチはこの列のためにPostGIS空間結合
> （osm_raw_poisとの近接カウント）を1本多く実行し続ける。またUPSERTのバインド
> パラメータ数・材料の表のpickle列数という「列数への暗黙の依存」の対象が
> 増えたままになる。
> `IF EXISTS`はfresh bootstrap（`create_tables()`→`apply_pending_migrations()`）のため。
> そこではORMの現在の定義からテーブルが作られ、0010/0012の`CREATE TABLE IF NOT EXISTS`が
> 素通りするため、この列は最初から存在しない。

```sql
ALTER TABLE edge_attribute_counts DROP COLUMN IF EXISTS stop_count;
ALTER TABLE way_attribute_counts DROP COLUMN IF EXISTS stop_count;
```

## 0039_add_derived_data_meta

追加された日: 2026-09-14

> 派生データの世代（app/infrastructure/derived_data_meta.py）。
> precompute系バッチが中身を書き直すたびに増える単調カウンタで、材料キャッシュが
> 「ディスクへ書いた時点から中身が変わったか」を判定するのに使う。
> axis_registry_meta（migration 0014）と同じ1行テーブルの形。

```sql
CREATE TABLE IF NOT EXISTS derived_data_meta (
id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO derived_data_meta (id, revision) VALUES (1, 1) ON CONFLICT (id) DO NOTHING;
```

## 0040_add_way_divided_carriageway

追加された日: 2026-09-15

> 上下線が分かれた道の片側かどうか（事前計算は
> batch/precompute_way_divided_carriageway.py）。
> 
> OSMは中央分離帯のある道路の上下線を別々のwayとして持ち、その一本ずつに oneway=yes を
> 付ける。そのため osm_raw_ways.direction だけでは「一方通行規制の道」と「上下線が
> 分かれた道の片側」を区別できない。後者は道路としては双方向で、逆方向は数m隣にある。
> 一方通行レイヤーはこのテーブルで後者を外す。
> 
> way_geometry（蛇行）へ列を足さず独立したテーブルにするのは、系譜の列
> （computed_at・source_osm_import_run_id・algorithm_version）が行単位で1組しか無く、
> 2つのバッチが同じ行を書くと互いの系譜を上書きしてしまうため（鮮度台帳
> derived_data_freshness.pyはこの系譜で再実行の要否を判断する）。
> 
> 行が無い＝未判定（バッチ未実行）。読む側は安全側＝falseとして扱い、従来どおり
> direction だけで塗る（黙って何も出さないより、多く出る方を選ぶ）。
> 適用後はprecompute_way_divided_carriageway.pyの実行が必須（他のprecomputeバッチと
> 同じ運用）。

```sql
CREATE TABLE IF NOT EXISTS way_divided_carriageway (
osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
divided                   boolean NOT NULL,
computed_at               timestamptz NOT NULL,
source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
algorithm_version         text
);
```

## 0041_add_road_node_intersection_attributes

追加された日: 2026-09-15

> 交差点ノードの属性（信号の有無・そのノードに集まる道の最大階級）を road_nodes へ
> 事前計算する（degree と同じ形。backend/app/batch/precompute_road_node_intersections.py）。
> 
> ターンの費用（domain/routing.py: build_turn_expanded_structure）は「進入した道より上位の
> 道と交わる交差点」で追加の秒数を足すが、信号の有無を見ていないため、信号のある交差点でも
> 信号待ちとは別に横断の待ちを足していた。信号での待ちは停止密度の材料が走行モデルへ運ぶ
> （domain/traffic.py: stop_count_material_ids）ので、そこは二重になる。ターン側が足すべき
> なのは「信号が無いのに上位の道を渡る・そこへ入る」ときの待ちで、それには交差点ノード単位で
> 信号の有無が要る（Edge へ畳み込むと、どちらの端の信号かが失われる）。
> 
> max_highway_rank は domain/traffic.py: HIGHWAY_RANK の順位で、DB 全体から見た値。
> 探索は読み込んだ部分グラフから同じ値を導いており、こちらはその下限を上げるためだけに使う
> （bbox の外にはみ出した上位の道を取りこぼさない）。
> 
> 適用しただけでは has_traffic_signals=false・max_highway_rank=0 のまま
> （degree・edge_attribute_counts と同じ運用）。既定値は「信号が無い・上位の道が無い」で、
> どちらもバッチ実行前の挙動を今までと変えない側へ倒してある。road_edges・osm_raw_pois が
> 変わるたび（PBF再取込時等）に再実行が要る派生データ。

```sql
ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS has_traffic_signals boolean NOT NULL DEFAULT false;
ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS max_highway_rank integer NOT NULL DEFAULT 0;
```

## 0042_drop_curvature

追加された日: 2026-09-15

> 蛇行（累積方位変化）の置き場所を落とす。road_edgesの列と、way単位の置き場だった
> way_geometryテーブル。
> 
> この材料は「1箇所の鋭い角」と「持続する緩いカーブ」を区別できない。距離で割って
> 平均するため、意味が正反対の2つが同じ値になる——半径30mの円がそのまま約1,900度/kmに
> なり、自転車のために作られた周回コースが地域で最も蛇行が酷い道として採点されていた。
> 元々は「右左折の回数をEdge単体の材料で表せない」ことの代理だったが、探索が有向区間の
> 状態を持つようになり、ターンの費用を秒で直接数えるようになったため代理の必要も無い。
> 
> 軸・材料・算出・事前計算バッチ・タイルの焼き込みは撤去済みで、この2つを読む経路は
> コード上に無い。way_geometryは中身が蛇行1列だけだったためテーブルごと落とす。
> `IF EXISTS`はfresh bootstrap（`create_tables()`→`apply_pending_migrations()`）のため。
> そこではORMの現在の定義からテーブルが作られるため、どちらも最初から存在しない。

```sql
ALTER TABLE road_edges DROP COLUMN IF EXISTS curvature_deg_per_km;
DROP TABLE IF EXISTS way_geometry;
```

## 0043_add_tuning_overrides

追加された日: 2026-09-16

> 較正値の上書き（app/infrastructure/tuning_overrides.py）。
> 既定値は宣言（app/domain/tuning.py: TUNING_PARAMETERS）が持ち、このテーブルは
> そこから動かしたぶんだけを持つ。axis_definitionsのように「行そのものが定義」には
> しない——テーブルが空でも宣言どおりに動くため、fresh bootstrap（CI・新規環境・
> disaster recovery）でスナップショットの投入が要らない。

```sql
CREATE TABLE IF NOT EXISTS tuning_overrides (
param_id TEXT PRIMARY KEY,
value DOUBLE PRECISION NOT NULL,
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 0044_add_edge_landcover

追加された日: 2026-09-17

> 区間単位の土地被覆クラス別割合（`way_landcover`と同じEsri×Impact Observatory由来、
> 同じリング径・同じ算出ロジック[domain/landcover.py]、母集団だけが区間）。
> 事前計算はbatch/precompute_edge_landcover.py。適用しただけではテーブルが空のため、
> 実行が必須（他のprecomputeバッチと同じ運用）。
> 
> 主キーがedge_idではなく「way＋両端ノードの組」なのは、road_edgesがforward/backwardを
> 別行で持ち、路面タイルが代表として残す行をedge_id昇順で決めるため。edge_idを鍵にすると
> 代表の向きに行が無いときだけ値が落ちる（road_graph_repository.py:
> _TILE_FEATURE_SOURCE_SQLがnode_lo/node_hiを出しているのと同じ理由）。この鍵ならラスタ
> 読み出しも物理区間あたり1回で済む。
> 
> way_landcoverは撤去しない。road_edgesは取込済み範囲へpresplit_road_graph.pyが埋める
> 派生データで、区間を持たないwayでは区間単位の行が作れないため、way単位の行が
> 落とし先として要る。
> 「計算済み・値なし」と確定させたときのラスタ構成の指紋（way_landcoverの
> source_raster_setと同じ意味・同じ増分実行の判定に使う）。
> 読み出しはwayごとにまとめて引くため、主キー索引がそのまま効く（先頭列がosm_way_id）。

```sql
CREATE TABLE IF NOT EXISTS edge_landcover (
osm_way_id                bigint NOT NULL REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
node_lo                   text NOT NULL,
node_hi                   text NOT NULL,
valid_pixels              integer,
water_percent             real,
trees_percent             real,
flooded_veg_percent       real,
crops_percent             real,
built_percent             real,
bare_percent              real,
snow_ice_percent          real,
rangeland_percent         real,
data_source               text NOT NULL,
data_version              text NOT NULL,
computed_at               timestamptz NOT NULL,
source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
algorithm_version         text,
source_raster_set         text,
PRIMARY KEY (osm_way_id, node_lo, node_hi)
);
```

## 0045_add_osm_import_run_poi_count

追加された日: 2026-09-20

> 取込runが「何を書いたか」をPOIについても残す。
> 
> 鮮度台帳は`MAX(id) WHERE status='succeeded'`を高水位として使うが、`--pois-only`の取込は
> way・nodeを1行も書かないのに成功行を残すため、way由来の派生テーブルまで一斉に
> 「古い」判定になっていた。way_count/node_countだけでは「POIは書いた」ことを表せず、
> POI由来の派生テーブル（edge_attribute_countsのpoi_counts）を正しく古い判定にもできない。
> 
> 既存行はNULLのまま残す。鮮度の判定側はNULLを「不明＝書いたかもしれない」として扱う
> （安全側＝古い判定へ倒す）ため、過去の全量取込は今までどおりPOIの高水位にもなる。

```sql
ALTER TABLE osm_import_runs ADD COLUMN IF NOT EXISTS poi_count bigint;
```

## 0046_road_edges_osm_way_id_not_null_fk

追加された日: 2026-09-20

> 区間は`osm_raw_ways`を交差点で切って作る派生行のため、対応するwayの行が必ずある。
> この制約をDBが持たないと、「wayの行が無い区間」という状態を読み出し側（材料の値式）が
> 毎回吸収することになる。兄弟の派生表（way_attribute_counts・way_landcover・
> designation_attributes等）は同じFKを既に持っており、road_edgesだけが持っていなかった。
> 
> PBF取込はwayをupsertし削除しないため、CASCADEで区間が消えるのは
> 「wayそのものが無くなったとき」だけで、そのとき区間を残す意味は無い。

```sql
ALTER TABLE road_edges ALTER COLUMN osm_way_id SET NOT NULL;
ALTER TABLE road_edges DROP CONSTRAINT IF EXISTS road_edges_osm_way_id_fkey;
ALTER TABLE road_edges
ADD CONSTRAINT road_edges_osm_way_id_fkey
FOREIGN KEY (osm_way_id) REFERENCES osm_raw_ways (osm_way_id) ON DELETE CASCADE;
```

## 0047_tuning_overrides_updated_at

追加された日: 2026-09-20

> `tuning_overrides.updated_at`（いつその較正値へ動かしたか）。
> 
> 0043の`CREATE TABLE IF NOT EXISTS`にも同じ列があるが、fresh bootstrapでは
> `create_tables()`が先に表を作るためそちらは何もしない。ORMが作った表にもこの列を
> 持たせて、どの経路で作った環境でも同じ形にする。

```sql
ALTER TABLE tuning_overrides ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
```
