# バッチパイプラインの依存関係（改善計画T281段階1）

`backend/app/batch/`配下8バッチの実行順序・再実行要否は、これまでmigrationコメントと
各スクリプトのdocstringに分散した不文律のままだった。ランタイムの遅延構築（`GraphService`の
`save_graph`経由）で生まれた新規Edgeは、対応するバッチの手動再実行まで`edge_attribute_counts`/
`elevation_attributes`が欠損し、stop/accident/intersection/gradient軸が**黙って評価から
抜け落ちる**（重み再正規化で薄まるだけで検知できない）。T74・T101・T242の本番障害は
いずれもこのクラスであり、対策が「人が気をつけるルール」に留まっていた。本ファイルは
依存DAGを1枚に可視化し、この再発パターンを見つけやすくする。

読み取り専用の調査結果であり、コードの挙動を変えるものではない。バッチ本体の実装は
各スクリプトのdocstring・`import_profile.yaml`が正準（本ファイルはそれらの要約・
横断的な依存関係の可視化）。

**2026-08-30追記（改善計画T351）**: ⑤`precompute_edge_attribute_counts.py`・
⑦`precompute_way_attribute_counts.py`・⑧`match_designations.py`が書き込む先
（`edge_attribute_counts`/`way_attribute_counts`/`designation_attributes`）へ、
実行時点の`accident_import_runs`/`osm_import_runs`の最新成功run id
（`source_accident_import_run_id`/`source_osm_import_run_id`、高水位マーク）と
`algorithm_version`を記録する列を追加した。これにより「このバッチはどのデータ世代を
見て計算したか」がDB上で機械的に確認できるようになったが、下記「段階2・3（本ファイルの
対象外）」の鮮度台帳のような自動検知・自動再計算のトリガー機構自体はまだ実装していない
——現状は記録された値を人が`SELECT`で参照し比較する運用のまま。詳細はdocs/tasks/T351.md参照。

## 1. 依存順序（実行順）

```
【第1グループ: 生データ取込（相互に独立、どの順でもよい）】
① import_pbf.py           PBFファイル → osm_raw_ways / osm_raw_nodes / osm_raw_pois
② import_accidents.py     警察庁公開CSV → accident_points
③ import_designations.py  国土数値情報N10/N12 → route_designations

【交差点分割（①の後、第2グループの前提）】
④ presplit_road_graph.py  osm_raw_ways/osm_raw_nodes（①の出力）→ road_edges / road_nodes
      └─ 取込済み全タイルを走査しGraphServiceの再構築経路（closure→build_road_graph→
         save_graph）を適用する。未実行の範囲は`GraphService.get_or_build_graph_with_attributes`
         がルート生成リクエスト内で同じ経路を遅延実行する安全網が働くため、本バッチは
         「ランタイムの初回リクエストで数十秒級の遅延が起きるのを避ける」ための事前実行であり、
         省略しても機能上は成立する（ただし後述⑤⑥[旧④⑤]は`road_edges`が存在しないと空実行になる）

【第2グループ: road_edges起点の派生計算（④のroad_edges作成後、かつ内部順序あり）】
⑤ precompute_road_node_degrees.py     road_edges → road_nodes.degree
      └─ 必ず⑥より先に実行すること（⑥のintersection_count計算が参照するため）
⑥ precompute_edge_attribute_counts.py  road_edges + accident_points + osm_raw_pois
                                        + road_nodes.degree → edge_attribute_counts
⑦ precompute_elevation_attributes.py   road_edges + GSI DEM API → elevation_attributes
      └─ ⑤⑥との明示的な前後関係なし。road_edgesにのみ依存

【第3グループ: osm_raw_ways起点の派生計算（road_edges非依存）】
⑧ precompute_way_attribute_counts.py   osm_raw_ways + accident_points + osm_raw_pois
                                        → raw_intersection_nodes / way_attribute_counts
⑨ match_designations.py                route_designations（③の出力）+ osm_raw_ways.geom
                                        → designation_attributes
      └─ ③の後、かつ①（osm_raw_ways更新）の後に再実行が必要
```

`precompute_elevation_attributes.py`のみ、`ElevationAttributeService.get_attributes_for_graph`
が「未計算のEdgeのみ計算する」設計のため**増分実行が可能**（新規Edge追加後にバッチ全体を
再実行しても安全、他の3つのprecomputeは全件洗い替え）。

## 2. バッチ別の入出力・依存・再実行トリガー

| # | バッチ | 入力 | 出力 | 前提 | 再実行トリガー | 冪等性 |
|---|---|---|---|---|---|---|
| ① | `import_pbf.py` | PBFファイル（`--pbf`）+ `import_profile.yaml` | `osm_raw_ways`（UPSERT）/ `osm_raw_nodes`（DO NOTHING、座標更新は追わない）/ `osm_raw_pois`（UPSERT）/ `osm_import_runs` | なし | PBFデータ更新時 | UPSERTだが**ノード座標の移動は追わない**（位置補正には完全再取込が必要） |
| ② | `import_accidents.py` | 警察庁公開CSV（`--years`） | `accident_points`（`accident_id`でUPSERT）/ `accident_import_runs` | なし | 年次データ更新時 | UPSERT、安全 |
| ③ | `import_designations.py` | 国土数値情報N10/N12 ZIP（自動DL） | `route_designations`（kind, pref_code単位でDELETE→INSERT）/ `designation_import_runs` | なし | KSJデータ更新時 | DELETE→INSERT、安全 |
| ④ | `presplit_road_graph.py` | `osm_raw_ways`/`osm_raw_nodes`（取込済み全z12タイル） | `road_edges`/`road_nodes`（`GraphService.get_or_build_graph_with_attributes`と同じ再構築経路） | ①でosm_raw_waysが存在すること | PBF再取込時（`is_split_up_to_date`がFalseになったタイルのみ再構築、`is_split_up_to_date`判定を使い済タイルはスキップし冪等） | 未split分のみ再構築、安全 |
| ⑤ | `precompute_road_node_degrees.py` | `road_edges`（from/to node） | `road_nodes.degree`（全件洗い替え） | ④でroad_edgesが存在すること | road_edges変化時（PBF再取込・トポロジ変更） | 全件洗い替え、安全 |
| ⑥ | `precompute_edge_attribute_counts.py` | `road_edges`全件 + `accident_points` + `osm_raw_pois` + `road_nodes.degree` | `edge_attribute_counts`（edge_id主キーでUPSERT） | **⑤の後**（未実行だと全edgeでintersection_count=0） | `accident_points`/`osm_raw_pois`/`road_edges`のいずれか変化時 | 全件再計算、増分無し |
| ⑦ | `precompute_elevation_attributes.py` | `road_edges`（ジオメトリ） + GSI DEM API | `elevation_attributes` | ④でroad_edgesが存在すること | road_edges変化時（新規Edge追加・PBF再取込） | **増分実行可能**（未計算Edgeのみ計算） |
| ⑧ | `precompute_way_attribute_counts.py` | `osm_raw_ways`（geom/highway非NULL全件） + `accident_points` + `osm_raw_pois` | `raw_intersection_nodes`（全再構築）/ `way_attribute_counts`（UPSERT） | ①でosm_raw_waysが存在すること（road_edges非依存） | `accident_points`/`osm_raw_pois`/`osm_raw_ways`のいずれか変化時。**併せて`region_service.py`の`ROAD_SURFACE_TILE_VERSION`を上げてタイルキャッシュを陳腐化させること**（コード中に明記） | UPSERT、安全 |
| ⑨ | `match_designations.py` | `route_designations`（③の出力） + `osm_raw_ways.geom` | `designation_attributes`（kind単位でDELETE→INSERT） | **③の後、かつ①（osm_raw_ways更新）の後** | ③または①の再実行後 | DELETE→INSERT、安全 |

全9バッチともUPSERTまたはDELETE→INSERT（トランザクション内、0件時はDELETEもスキップ）で
単純な再実行は安全。冪等性の唯一の例外は①のノード座標（DO NOTHING）。④はタイル単位で
`is_split_up_to_date`により未split分だけへスコープを絞るため、全件洗い替えではない。

## 3. ランタイム側の読み取り元

| 出力テーブル | 読み取り元 | 用途 |
|---|---|---|
| `edge_attribute_counts` / `elevation_attributes` | `infrastructure/graph_material_cache.py`経由で`services/road_graph_engine.py`（`prepare`） | 評価軸算出（stop/accident/intersection/gradient） |
| `way_attribute_counts` | `services/region_service.py` | 道路サーフェスタイルMVT生成 |
| `designation_attributes` | `domain/evaluation.py`等の評価系 | 指定路線の評価軸（car_stress補正） |
| `road_nodes.degree` | ランタイムでは直接使われない | ⑥の`intersection_count`計算専用の中間データ |

`api/routers/health.py`の`/health`（`_KEY_TABLES`）が`osm_raw_ways`/`route_designations`/
`designation_attributes`等の0件検知で「バッチ未実行」を検出する仕組みを既に持つ
（ただし「0件」は検知できても「road_edges追加分だけ欠損している」部分的な鮮度劣化までは
検知しない）。`road_edges`/`road_nodes`自体は④が事前に埋めなくても
`GraphService.get_or_build_graph_with_attributes`がリクエスト内で同じ経路を遅延実行する
安全網を持つため、`/health`の対象には含まれない。

**改善計画T538追記**: `graph_material_cache.py`・`tile_score_matrix_cache.py`のプロセス内
メモリキャッシュは、`infrastructure/tile_persistent_cache.py`経由でディスク（`backend/data/
tile_persistent_cache/`）へも永続化されるようになった。ディスク側はデプロイでプロセスが
再起動しても消えないため、④road_edges/road_nodes・⑤road_nodes.degree・⑥edge_attribute_
counts・⑦elevation_attributes・⑨designation_attributes（`EdgeMaterialBundle.is_designated`
経由）のいずれかを更新するバッチを実行したら、`graph_material_cache.py: TILE_MATERIALS_
CACHE_VERSION`・`tile_score_matrix_cache.py: TILE_SCORE_MATRIX_CACHE_VERSION`（両方とも
`region_service.py: ROAD_SURFACE_TILE_VERSION`と同じ「手動で上げる版数文字列」の運用）を
手動で上げること。上げ忘れると、バッチ実行後もディスクキャッシュ経由で古いタイル材料・
スコア行列が次回デプロイ後も復元され続ける（⑧の`ROAD_SURFACE_TILE_VERSION`と同型の
上げ忘れリスク。docs/tasks/T538.md参照）。

## 4. 再実行トリガー早見表

| 生データの変化 | 再実行が必要なバッチ |
|---|---|
| PBF更新・道路網トポロジ変化 | ①→④→⑤→⑥→⑦→⑧→⑨（⑨は③の完了も前提）。あわせて`TILE_MATERIALS_CACHE_VERSION`/`TILE_SCORE_MATRIX_CACHE_VERSION`を手動で上げる（改善計画T538、上記「3. ランタイム側の読み取り元」追記参照） |
| 事故CSV更新 | ②のみ再取込。ただし⑥・⑧が事故カウントを参照するため、⑥・⑧も追随再実行が必要 |
| KSJ指定路線データ更新 | ③→⑨ |
| ランタイムの遅延構築で新規Edgeが生まれた場合（`GraphService`が未split範囲へのリクエストで`is_split_up_to_date`判定によりその場で交差点分割する経路） | ⑥・⑦の再実行が無いと、その新規Edgeの評価軸（stop/accident/intersection/gradient）が欠損する（**T74・T101・T242の再発パターン**）。⑤はroad_edges全体からの集計のため併せて再実行が必要 |

## 段階2・3（本ファイルの対象外）

統合エントリポイント（`python -m app.batch.refresh_derived`等、実行順序を自動解決する
単一コマンド）と、鮮度台帳（生データ更新時刻 vs 派生computed_atを機械比較できる仕組み）は
改善計画T281段階2・3として別途トリガー待ち（docs/improvement-plan.md参照）。**2026-08-30
追記**: 改善計画T351が鮮度台帳の材料となる列（source_*_import_run_id・algorithm_version、
上記冒頭の追記参照）を先行して用意した。段階3着手時はこの列を読むだけで鮮度台帳を構築でき、
新たな系譜追跡機構をゼロから設計する必要はない。
