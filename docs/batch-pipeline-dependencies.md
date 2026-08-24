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

## 1. 依存順序（実行順）

```
【第1グループ: 生データ取込（相互に独立、どの順でもよい）】
① import_pbf.py           PBFファイル → osm_raw_ways / osm_raw_nodes / osm_raw_pois
② import_accidents.py     警察庁公開CSV → accident_points
③ import_designations.py  国土数値情報N10/N12 → route_designations

【第2グループ: road_edges起点の派生計算（①のroad_edges作成後、かつ内部順序あり）】
④ precompute_road_node_degrees.py     road_edges → road_nodes.degree
      └─ 必ず⑤より先に実行すること（⑤のintersection_count計算が参照するため）
⑤ precompute_edge_attribute_counts.py  road_edges + accident_points + osm_raw_pois
                                        + road_nodes.degree → edge_attribute_counts
⑥ precompute_elevation_attributes.py   road_edges + GSI DEM API → elevation_attributes
      └─ ④⑤との明示的な前後関係なし。road_edgesにのみ依存

【第3グループ: osm_raw_ways起点の派生計算（road_edges非依存）】
⑦ precompute_way_attribute_counts.py   osm_raw_ways + accident_points + osm_raw_pois
                                        → raw_intersection_nodes / way_attribute_counts
⑧ match_designations.py                route_designations（③の出力）+ osm_raw_ways.geom
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
| ④ | `precompute_road_node_degrees.py` | `road_edges`（from/to node） | `road_nodes.degree`（全件洗い替え） | ①でroad_edgesが存在すること | road_edges変化時（PBF再取込・トポロジ変更） | 全件洗い替え、安全 |
| ⑤ | `precompute_edge_attribute_counts.py` | `road_edges`全件 + `accident_points` + `osm_raw_pois` + `road_nodes.degree` | `edge_attribute_counts`（edge_id主キーでUPSERT） | **④の後**（未実行だと全edgeでintersection_count=0） | `accident_points`/`osm_raw_pois`/`road_edges`のいずれか変化時 | 全件再計算、増分無し |
| ⑥ | `precompute_elevation_attributes.py` | `road_edges`（ジオメトリ） + GSI DEM API | `elevation_attributes` | ①でroad_edgesが存在すること | road_edges変化時（新規Edge追加・PBF再取込） | **増分実行可能**（未計算Edgeのみ計算） |
| ⑦ | `precompute_way_attribute_counts.py` | `osm_raw_ways`（geom/highway非NULL全件） + `accident_points` + `osm_raw_pois` | `raw_intersection_nodes`（全再構築）/ `way_attribute_counts`（UPSERT） | ①でosm_raw_waysが存在すること（road_edges非依存） | `accident_points`/`osm_raw_pois`/`osm_raw_ways`のいずれか変化時。**併せて`region_service.py`の`ROAD_SURFACE_TILE_VERSION`を上げてタイルキャッシュを陳腐化させること**（コード中に明記） | UPSERT、安全 |
| ⑧ | `match_designations.py` | `route_designations`（③の出力） + `osm_raw_ways.geom` | `designation_attributes`（kind単位でDELETE→INSERT） | **③の後、かつ①（osm_raw_ways更新）の後** | ③または①の再実行後 | DELETE→INSERT、安全 |

全8バッチともUPSERTまたはDELETE→INSERT（トランザクション内、0件時はDELETEもスキップ）で
単純な再実行は安全。冪等性の唯一の例外は①のノード座標（DO NOTHING）。

## 3. ランタイム側の読み取り元

| 出力テーブル | 読み取り元 | 用途 |
|---|---|---|
| `edge_attribute_counts` / `elevation_attributes` | `infrastructure/graph_material_cache.py`経由で`services/road_graph_engine.py`（`prepare`） | 評価軸算出（stop/accident/intersection/gradient） |
| `way_attribute_counts` | `services/region_service.py` | 道路サーフェスタイルMVT生成 |
| `designation_attributes` | `domain/evaluation.py`等の評価系 | 指定路線の評価軸（car_stress補正） |
| `road_nodes.degree` | ランタイムでは直接使われない | ⑤の`intersection_count`計算専用の中間データ |

`api/routers/health.py`の`/health`（`_KEY_TABLES`）が`osm_raw_ways`/`route_designations`/
`designation_attributes`等の0件検知で「バッチ未実行」を検出する仕組みを既に持つ
（ただし「0件」は検知できても「road_edges追加分だけ欠損している」部分的な鮮度劣化までは
検知しない）。

## 4. 再実行トリガー早見表

| 生データの変化 | 再実行が必要なバッチ |
|---|---|
| PBF更新・道路網トポロジ変化 | ①→④→⑤→⑥→⑦→⑧（⑧は③の完了も前提） |
| 事故CSV更新 | ②のみ再取込。ただし⑤・⑦が事故カウントを参照するため、⑤・⑦も追随再実行が必要 |
| KSJ指定路線データ更新 | ③→⑧ |
| ランタイムの遅延構築で新規Edgeが生まれた場合（`GraphService`のOverpass経由構築等） | ⑤・⑥の再実行が無いと、その新規Edgeの評価軸（stop/accident/intersection/gradient）が欠損する（**T74・T101・T242の再発パターン**）。④はroad_edges全体からの集計のため併せて再実行が必要 |

## 段階2・3（本ファイルの対象外）

統合エントリポイント（`python -m app.batch.refresh_derived`等、実行順序を自動解決する
単一コマンド）と、鮮度台帳（生データ更新時刻 vs 派生computed_atを機械比較できる仕組み）は
改善計画T281段階2・3として別途トリガー待ち（docs/improvement-plan.md参照）。
