# Road Graph移行の経緯（決定記録）

docs/architecture.md の旧9章を分離した経緯の記録（改善計画T8。現状の姿はarchitecture.md本体を参照）。
Phase 0〜3・永続化・タイルキャッシュ・各種レビュー対応の時系列を当時の記述のまま保存しており、
**追記専用**とする（現状と食い違って見える場合はarchitecture.md側が正）。

## Road Graph移行（時系列）

「OSMを基礎としたRoad Graphを中心に据え、そのRoad Graphへ各種属性を後から追加できる構造へ段階的に移行する」ための移行仕様書に基づく作業。Phase 0（現状調査）→Phase 1（Road Graph導入）まで完了。既存機能（Step1-10）は無変更。

### Phase 0で判明した現状（移行前）

- **Node/Edgeの概念が存在しなかった**: 道路は(1)ORSが返すGeoJSON LineString（`RouteCandidate.geometry`）、(2)等間隔12点サンプリングの`RouteSegmentDetail`、(3)Overpass由来でID破棄済みの路面MVTタイル、という3つの無関係な形でのみ扱われていた
- **経路探索は完全にopenrouteserviceへ委譲**: `RoutingService`/`RouteGenerator`はORSをブラックボックスとして使い、標高・風・路面の評価は「経路が返ってきた後」の後付けスコアリング（`RouteScorer`, `domain/difficulty.py`）に過ぎず、Edge Costが探索そのものに影響する仕組みは無かった
- **永続的なedge_id体系が無い**: `OverpassClient.get_roads`はOSM Way/Node IDを取得直後に破棄していた
- PostGIS（docker-compose）は用意されているが、backendコードから未接続

### Phase 1で実施した内容

既存のルート探索・地図表示には一切手を加えず、Road Graphを**独立した並行構造**として追加した。

- **`backend/app/domain/graph.py`**（新規）: `Node`（node_id, latitude, longitude, osm_node_id）、`DirectedEdge`（edge_id, from_node_id, to_node_id, geometry, distance_m, osm_way_id, highway）、`RoadGraph`（graph_version, nodes, edges）のPydanticモデルと、純粋関数`build_road_graph(osm_ways, osm_nodes) -> RoadGraph`を実装。
  - 分割地点（Node化する条件）は「各Wayの端点」または「複数Way間・同一Way内で複数回参照されるノード」とし、それ以外の中間点はNode化せずEdgeの`geometry`内の形状点として保持する（仕様書7・9章）
  - `oneway`タグ（`yes`/`-1`等）に応じて片方向のみ、それ以外は双方向（A→B, B→A）のDirected Edgeを生成する（仕様書8章）
  - 内部ID（`node-N`, `edge-N`の連番）とOSM ID（`osm_node_id`, `osm_way_id`）を明確に分離し、OSM IDをそのまま内部IDとして使わない（仕様書11章：「osm_way_idを永続的な道路の識別子として扱わないこと」）
  - `graph_version`は過剰なバージョン管理機構を導入せず、生成時刻ベースの文字列のみ（仕様書12章の方針どおり最小実装）
- **`backend/app/infrastructure/overpass_client.py`**: 新規メソッド`get_ways_and_nodes(client, bbox)`を追加。既存の`get_roads`（`out geom`でジオメトリのみ取得、ID破棄、地域路面レイヤー表示専用）とは別に、Way ID・Node IDとノード参照関係（トポロジー）を保持したまま取得する（`(._;>;); out body;`）。既存の`get_roads`・その呼び出し元（`RegionService`）は無変更
- **`backend/app/services/graph_service.py`**（新規）: `GraphService.build_graph_for_bbox(bbox)`がOverpass取得とグラフ構築を統合する。**Phase 1時点では永続化を行わない**（呼び出しのたびに構築、DB/ファイルキャッシュ未実装）。既存の`RouteGenerator`・`RegionService`のどちらからも参照されない、完全に独立したサービス
- **テスト**: `test_graph.py`（Way分割・交差点検出・oneway処理・ID分離・距離計算の単体テスト）、`test_graph_service.py`、`test_overpass_client.py`への追加分。既存を含む全147件がグリーン

### Phase 1で意図的に行わなかったこと（スコープ外の判断）

移行仕様書のPhase 1完了条件には「既存ルート探索がRoad Graphを利用できる」との記載があるが、これは仕様書34章「探索アルゴリズムを独断で変更しない」・39章「新しい経路探索アルゴリズムの独自実装は対象外」と直接競合する（現在の探索はORSへの完全委譲であり、内部Road Graphを実際の経路探索に使わせるには探索エンジンそのものの置き換えが必要になる）。そのため今回は「Road Graphを生成できる」ことのみを完了条件とし、`route_generator.py`/`routing_service.py`への組み込みは行っていない。Road GraphをEvaluation Engine・Route Engineへ接続する判断は、Phase 3（Road Attributes）・Phase 4（Evaluation Engine分離）以降で改めて提案する。

同様に、永続化（SQLite/PostGIS/ファイルキャッシュ）もPhase 1では未実装。DB選定（既存の未使用PostGISを採用するか、`cache_db.py`/`tile_cache.py`と同様の軽量方式を踏襲するか）はユーザー判断が必要な事項として残している（仕様書38章）。

### Phase 2で実施した内容

Phase 1時点では、`domain/graph.py: build_road_graph`が交差点分割などの純粋なグラフ構築ロジックと、OSMの`oneway`タグ文字列（`"yes"`/`"-1"`等）の解釈という**OSM固有の語彙知識**を同居させてしまっていた。これはPhase 2の目的（「OSMのデータ形式が変更されても、Road Graph内部モデルへの影響を最小化する」、仕様書22章）に反するため分離した。

- **`backend/app/domain/graph.py`**: `build_road_graph`の入力契約として`WaySpec`（データソース非依存、`osm_way_id`, `node_ids`, `highway`, `direction: "forward"|"backward"|"both"`）を新設。`ONEWAY_FORWARD_ONLY`/`ONEWAY_BACKWARD_ONLY`（OSMタグの生値）と、それを解釈する分岐は`domain/graph.py`から削除した。`build_road_graph`はもはや`tags`辞書という概念自体を知らない
- **`backend/app/domain/osm_adapter.py`**（新規、OSM Adapter/Importerに相当）: `osm_way_to_way_spec(raw_way: dict) -> WaySpec | None`が、OSMの`oneway`タグ（`yes`/`-1`/`reverse`等、大文字小文字・前後空白を無視）を`WaySpec.direction`へ変換し、`highway`タグをそのまま渡す。ノードが2未満のwayは経路探索上の区間になり得ないためNoneを返す（Adapter側でフィルタする）
- **`backend/app/services/graph_service.py`**: `GraphService.build_graph_for_bbox`が`OverpassClient.get_ways_and_nodes` → `osm_adapter.osm_ways_to_way_specs` → `build_road_graph`の順で配線するよう更新。責務の流れが仕様書47章の「OSM → OSM Adapter/Importer → Road Graph」と一致する形になった
- 既存の`OverpassClient.get_roads`（地域路面レイヤー用、Step10）は無変更。ルート探索・地図表示への影響なし
- テスト: `test_graph.py`を`WaySpec`ベースに更新（`oneway`文字列ではなく`direction`を直接指定する形に変更）、`test_osm_adapter.py`を新規作成（oneway解釈・highway受け渡し・ノード数フィルタの検証）。既存を含む全157件がグリーン

このリファクタリングにより、将来Overpassのクエリ形式が変わったり、OSM以外のデータソース（PBF一括抽出等）へ切り替える場合も、変更は`osm_adapter.py`（と対応する新Adapter）に閉じ、`build_road_graph`のグラフ構築アルゴリズムは無変更で使えることが期待される。

### Phase 3で実施した内容

標高・路面をRoad Attribute（仕様書13-16章）としてEdgeへ紐付ける仕組みを追加した。既存のルート単位の評価（`ElevationService`, `RouteGenerator`, `domain/road.py`のORS/Overpass由来のroad_score）は無変更で、Edge単位の属性生成は独立した並行機能として追加している。

- **`backend/app/domain/attributes.py`**（新規）: `ElevationAttribute`（edge_id, start/end_elevation_m, elevation_gain_m/loss_m, average/max/min_grade, data_source, data_version, calculated_at）と`SurfaceAttribute`（edge_id, surface_type, confidence, data_source, data_version, calculated_at）のPydanticモデル。仕様書13章の方針どおりEdge本体（`domain/graph.py`）とは別モデルとして定義し、`surface_type`はOSMタグの生値のみを保持し評価用スコア（`surface_score`等）は含まない（正規化・スコア化はPhase 4以降のEvaluation Engineの責務、仕様書24-26章）
  - `compute_elevation_attribute(edge_id, points, elevations, data_source)`: Edgeの形状点列とその標高値から獲得標高・喪失標高・符号付き勾配（average/max/min_grade）を算出する純粋関数。既存の`ElevationService.get_profile`（ルート単位、12点サンプリング用）とは別実装（意図的に非共有。既存の動いているルート生成フローに影響を与えないため、詳細は「Phase 3で意図的に行わなかったこと」参照）
  - `build_surface_attributes(graph, surface_by_way_id, data_source)`: RoadGraphの各EdgeへOSMの`surface`タグ（`osm_way_id`経由で対応付け）を割り当てる純粋関数。1つのOSM Wayが複数Edgeに分割されている場合は同じsurface_typeを共有する
- **`backend/app/domain/graph.py`**: `WaySpec`に`surface: str | None`フィールドを追加（`highway`と同様、OSM Adapterが抽出する生タグ）。`DirectedEdge`へは持たせない（Edge本体とRoad Attributeの分離を維持するため、仕様書10・13章）
- **`backend/app/domain/osm_adapter.py`**: `osm_way_to_way_spec`が`tags.get("surface")`も`WaySpec.surface`へ抽出するよう拡張
- **`backend/app/services/elevation_attribute_service.py`**（新規）: `ElevationAttributeService.get_attributes_for_graph(graph)`が、RoadGraphの各Edgeの形状点（`geometry`）を国土地理院APIへ問い合わせ、Edgeごとの`ElevationAttribute`を算出する。既存の`ElevationClient`（緯度経度キャッシュ、SQLite永続化）をそのまま再利用するため、ルート生成側で既に問い合わせ済みの地点はキャッシュヒットする
- **`backend/app/services/graph_service.py`**: 新規メソッド`build_graph_with_surface_tags_for_bbox(bbox)`を追加。Road Graph構築に使ったのと同じOverpass取得結果（1回のみ）から`RoadGraph`と`dict[osm_way_id, surface]`を同時に返す（Surface Attribute生成のために再度Overpassへ問い合わせることを避けるため）。既存の`build_graph_for_bbox`は無変更（内部実装のみ共通化）
- テスト: `test_attributes.py`（登り/下り/混在勾配・欠損値・osm_way_id対応の検証）、`test_elevation_attribute_service.py`（DIモック）を新規作成。`test_osm_adapter.py`・`test_graph_service.py`に追加分。既存を含む全173件がグリーン

### Phase 3で意図的に行わなかったこと（スコープ外の判断）

- **標高計算ロジックを既存`ElevationService`と共有しなかった**: `ElevationService.get_profile`はルート単位・12点サンプリングという既存の使われ方に最適化されており、獲得標高（gain）のみを返し喪失標高（loss）や符号付き勾配（min/max_grade）を持たない。これをEdge単位の要件に合わせて拡張・共有化することも検討したが、Step5-9から動いている既存ルート生成フローに影響を与えるリスクがあるため見送り、`compute_elevation_attribute`として独立した実装にした（約15行の計算ロジックの重複だが、既存機能への影響ゼロを優先）。将来的に共通化する場合は、まず`ElevationService`側のテストが厚く保たれていることを確認してから検討する
- **正規化・スコア化（surface_score等）は実装しなかった**: 仕様書24-26章のRaw AttributeとScoreの分離方針に従い、Phase 3は「属性の導入」までに留め、スコア化はPhase 4（Evaluation Engine分離）以降で改めて設計する
- **交通・自転車インフラ・信号密度の属性は追加しなかった**: 現時点でこれらのデータソースが存在しない（仕様書39章は新規データソース連携を今回のスコープ外としていないが、既存データの整理を優先する仕様書Phase 3の方針「新機能を大量に追加することよりも、既存データをRoad Graph中心に整理することを優先する」に従い、既存の標高・路面のみを対象とした）
- **APIエンドポイントは追加しなかった**: `GraphService`同様、Phase 3の属性生成機能もAPIやUIには未接続（内部的に呼び出し・テスト可能な状態に留めている）
- **永続化は引き続き未実装**: 属性もRoad Graphと同様、呼び出しのたびに計算する設計。DB選定（PostGIS採用か、軽量方式継続か）は依然ユーザー判断待ち

### Phase 4で実施した内容

Phase 4着手前に「Evaluation Engineを何に対して作るか」という設計判断が生じたため、ユーザーに確認した。選択肢は(a) Phase1-3で作ったRoad Graph/Road Attribute側に新設する、(b) 既存の`RouteScorer`/`domain/difficulty.py`（route_generator.py内、ルート単位）を独立モジュールとして抽出する、(c)両方、の3案を提示し、(a)（Road Graph側への新設、既存のライブなルート生成コードには触れない）を採用した。

- **`backend/app/domain/evaluation.py`**（新規、Evaluation Engine本体）:
  - `RoutePreference`（`elevation_weight`, `road_weight`）: 仕様書27章のRoute Preference。現時点で実装済みのRoad Attribute（標高・路面）のみを対象とし、交通・自転車インフラ・信号等、未実装の属性用の重みは追加していない。重みのYAML外部化は仕様書のPhase分割どおりPhase 5の作業として明示的に見送った（デフォルト値を持つPydanticモデルとしてのみ用意し、呼び出し元が差し替え可能な構造にした）
  - `is_edge_allowed(edge)`: Hard Constraint（仕様書29章）。`highway`タグが`motorway`/`motorway_link`/`trunk`/`trunk_link`のEdgeを自転車通行不可として除外する。Phase 1から`DirectedEdge.highway`が既に保持されていたため、新たなデータソースなしで実装できた
  - `compute_edge_cost(edge, elevation_attribute, surface_attribute, preference)`: Road Attributeから Edge Costを算出する。**Score部分は新しい正規化方式を発明せず、既存の`domain/difficulty.py`（`gradient_difficulty`, `road_difficulty`, `composite_difficulty`。Step9で地図の難易度レイヤー用に導入済み、0-100・値が大きいほど走りにくい絶対基準）をそのまま再利用した**。Cost自体は「difficulty(0-100)を距離への乗算ペナルティ（1.0〜2.0倍）に変換する」という初期実装で、仕様書31章の方針どおり将来別方式に差し替え可能な独立した関数にしてある
- **`backend/app/services/evaluation_service.py`**（新規）: `EvaluationService.evaluate_graph(graph, elevation_attributes, surface_attributes)`がRoadGraphの全Edgeに対し`compute_edge_cost`を適用する。I/Oを行わない点は既存の`RouteScorer`（`services/route_scorer.py`、docstringに「I/Oを行わない純粋なクラス」と明記）と同じ位置づけで、この既存の設計精神を踏襲した
- Edge Costは仕様書32章の方針どおりRoad Graphへ恒久保存しない（`EvaluationService`の戻り値としてのみ存在する使い捨てのdict）
- テスト: `test_evaluation.py`（Hard Constraint・平坦舗装と激坂未舗装の比較・属性欠損時のフォールバック・重み変更）、`test_evaluation_service.py`（DIモック）を新規作成。既存を含む全185件がグリーン

### Phase 5で実施した内容

Phase 4で導入した`RoutePreference`（重み）はPydanticモデルとしてのみ存在し、デフォルト値（0.5/0.5）がコードに埋め込まれていた。Phase 5でこれを設定ファイルへ外部化した。

- **`backend/app/route_preference.yaml`**（新規）: `route_preference.elevation_weight`/`road_weight`。既存の`scoring.yaml`（ルート単位・candidate集合内の相対評価、`RouteScorer`が使う4指標）とは対象が異なる別設定のため、Phase 4完了時点の引き継ぎ事項で検討課題としていた「共用するか分離するか」は**分離**を選択した。同じ「重み」という概念でも、一方はルート候補同士の相対比較（min-max正規化）、もう一方は単体のEdgeに対する絶対評価という異なる意味を持つため、混同を避けるため
- **`backend/app/services/evaluation_service.py`**: `load_route_preference(path: Path = ROUTE_PREFERENCE_CONFIG_PATH) -> RoutePreference`を追加（`route_scorer.py`の`load_scoring_weights`と同じI/Oパターン、YAML読み込みという性質上services層に配置）。`EvaluationService.__init__`のデフォルト値を、ハードコードされた`RoutePreference()`から`load_route_preference()`に置き換えた。`preference`引数を明示的に渡すこれまでの呼び出し方（テスト等）には影響しない
- 複数プロファイル（快適性重視/トレーニング重視等、仕様書27・45章）は今回実装しない（仕様書Phase 5の方針「UIから変更する必要は今回必須ではない。まずは内部的に変更可能な構造を作る」に従う）。`load_route_preference`が`path`引数を取る構造にしてあるため、将来的に`route_preference_comfort.yaml`等を追加してパスを切り替えるだけで対応でき、コード変更は不要という設計にしてある
- テスト: `load_route_preference`の既定パス・カスタムパス読み込み、`EvaluationService()`のデフォルトが設定ファイル経由になったことの検証を追加。既存を含む全188件がグリーン

### Road Graph・Road Attributeの永続化（PostGIS）

Phase 1-5完了時点の引き継ぎ事項だった「永続化方式の決定」について、ユーザーの意思決定によりPostGISを採用した。**このdev環境にはDocker/PostgreSQLが無く、実際のPostGISに接続しての動作確認ができていない**ことをユーザーに明示した上で、コード実装のみを先に進めることで合意して着手した（後述「未検証の範囲」を参照）。

#### 前提として必要になった修正: ID安定化

永続化キャッシュが機能するには、同じ現実の交差点・道路区間には常に同じ`node_id`/`edge_id`が振られる必要がある。しかしPhase 1時点の実装は`node_id`/`edge_id`をビルド呼び出しごとにリセットされる連番（`node-1`, `edge-1`...）で採番しており、同じ地域を2回ビルドしても内部IDが一致しない状態だった。これは永続化を実装する前提として`domain/graph.py`を修正した。

- `node_id`は`osm_node_id`から決定論的に導出（`osm-node-<id>`）
- `edge_id`は`osm_way_id`＋Way内でのセグメント順序＋方向から決定論的に導出（`way-<osm_way_id>-seg<n>-fwd/bwd`）
- 仕様書11章の「osm_way_idを永続的な道路の識別子として扱わないこと」は維持（内部IDはOSM IDの生値そのものではなく別表現にしている）
- 既存テスト（`node_id != str(osm_node_id)`等の「内部IDはOSM IDと別物」という検証）に変更なく通ることを確認。新たに「同一入力から複数回ビルドしても同じID集合になること」を検証するテストを追加

#### 実装内容

- **技術選定**: SQLAlchemy 2.0（非同期、asyncpgドライバ）+ GeoAlchemy2（PostGISのGeometry型）+ Shapely（Python側のジオメトリ操作）。このプロジェクトで初めてのORM/リレーショナルDB利用（既存のcache_db.pyはSQLiteの素の`sqlite3`モジュール、tile_cache.pyはファイルキャッシュで、いずれもリレーショナルではない）
- **マイグレーションツールは導入しない**: Alembic等は使わず、`create_tables()`が`Base.metadata.create_all`相当を実行するのみ（cache_db.pyの`CREATE TABLE IF NOT EXISTS`と同じ「必要最小限」の思想、仕様書12章）
- **`backend/app/infrastructure/road_graph_models.py`**（新規）: SQLAlchemy ORMモデル4種（`road_nodes`, `road_edges`, `elevation_attributes`, `surface_attributes`）。`elevation_attributes`/`surface_attributes`は`road_edges.edge_id`への外部キー（`ON DELETE CASCADE`）で、ドメインモデルと同じく「Edge本体とAttributeの分離」を維持
- **`backend/app/infrastructure/road_graph_repository.py`**（新規）: `RoadGraphRepository`クラス。`get_graph_in_bbox`（`ST_Intersects`/`ST_MakeEnvelope`によるbbox空間検索）、`save_graph`（`Session.merge`によるUPSERT、Node→Edgeの順でflushしFK制約を満たす）、標高/路面属性の取得・保存。ドメインのPydanticモデルとORM行の相互変換関数を持つ
- **`backend/app/infrastructure/database.py`**（新規）: 非同期エンジン・セッションファクトリ（アプリ全体で1エンジンを共有する標準的なSQLAlchemyの使い方）
- **`GraphService`**: 新規メソッド`get_or_build_graph_with_attributes(bbox)`を追加。`repository`（コンストラクタの新規オプション引数、既定`None`）を渡した場合のみキャッシュを使う。渡さなければPhase 1-5と全く同じ「毎回Overpassから構築する」挙動のまま（既存メソッド`build_graph_for_bbox`/`build_graph_with_surface_tags_for_bbox`も無変更）
- **`ElevationAttributeService`**: `get_attributes_for_graph`が`repository`（同じく既定`None`のオプション引数）指定時のみEdge単位でキャッシュを確認し、未取得のEdgeだけGSI APIへ問い合わせる。部分キャッシュ（一部Edgeだけキャッシュ済み）にも対応
- **`config.py`**: `database_url`を追加（既定値はdocker-compose.ymlのpostgresサービスに対応）。`docker-compose.yml`の`DATABASE_URL`をSQLAlchemy非同期エンジン用に`postgresql+asyncpg://`スキームへ修正（これまで一度も実際に使われていなかった値のため、書き換えても既存動作への影響なし）
- テスト: `test_graph.py`にID安定性の検証を追加。`test_graph_service.py`/`test_elevation_attribute_service.py`に、インメモリの`FakeRoadGraphRepository`/`FakeElevationAttributeRepository`を使ったキャッシュヒット/ミス/部分キャッシュのオーケストレーションロジックのテストを追加。既存を含む全199件がグリーン

#### 未検証の範囲（重要）→ 解消済み

**【後日解消】本節の未検証項目は、後述「実PostGISでの動作検証（Phase 0）」ですべて実機確認済み。** 以下は実装当時の記録として残す。

このdev環境にはDocker/PostgreSQLが無く、`road_graph_repository.py`のSQL/ORMマッピングは**実際のPostGISに対して一度も実行されていない**。以下で部分的に静的検証は行った。

- `Base.metadata.create_all`相当のDDLをpostgresqlダイアレクトでコンパイルし、`geometry(POINT,4326)`等の型・外部キー制約が意図通り生成されることを確認
- `get_graph_in_bbox`の`ST_Intersects`/`ST_MakeEnvelope`を使ったSELECT文をpostgresqlダイアレクトでコンパイルし、SQLとして正しい形になることを確認

ただし、実際のPostGISへの接続・PostGIS拡張の有効化・`Session.merge`によるUPSERT・GeoAlchemy2の`from_shape`/`to_shape`によるジオメトリ変換の往復（特に緯度経度の軸順の取り違えがないか）は未検証。**ユーザーがDocker等でPostGISを起動できるようになった時点で、実接続での動作確認が必須。**

#### 意図的な設計上の簡略化（既知の制約）

- Node/Edgeの更新（OSM側の変更に追従した再取得・古いデータの失効判定）は実装していない。`updated_at`列は保持しているが、TTLベースの失効等の利用はまだ無い
- 「bboxと交差するEdgeが1件でもDBにあればキャッシュヒット」という不正確な簡易判定は、後述のタイル単位キャッシュ導入により解消済み

### RegionServiceの路面データとSurfaceAttributeの統合検討 → タイル単位キャッシュの導入

ユーザーから「RegionServiceの路面データとSurfaceAttributeを統合できないか」という検討依頼を受け、以下の選択肢を分析した。

- **A. RegionServiceのデータソースをRoad Graph/PostGIS経由に完全移行**: 却下。RegionServiceは現在ゼロDB依存で動いている実運用機能であり、PostGIS必須にすると「PostGISが落ちている間、地図の路面表示という既存機能が丸ごと壊れる」。実際、このdev環境は今もPostGIS未接続であり、この方針は「既存機能を維持できることを最優先する」という大原則に反する
- **B. Overpassクエリ方式だけを統一**（RegionServiceも`get_ways_and_nodes`を使うよう変更）: 見送り。今この2つのサービスが同時に同じ地域へ問い合わせる実運用シナリオが存在しない（Road Graph側はまだどのAPI/UIからも呼ばれていない）ため、実運用コード（RegionService）を変更するリスクに見合う効果が今は無い
- **C. Road Graph側のキャッシュ単位をRegionServiceのタイル方式に合わせる**: **採用**。RegionServiceには一切手を入れず、Road Graph側だけをXYZタイル境界単位のキャッシュに変更する。これは「bboxの一部だけが過去に取得済みの場合に断片的なデータを返してしまう」という永続化Phase時点の既知の制約の解消と表裏一体であり、RegionServiceへの依存もリスクも生じさせない
- **D. 統合しない（現状維持）**: Cの実施により部分的に採用（データソース自体は統合しない）

#### Cの実装内容: Road Graphのタイル単位キャッシュ

- **`backend/app/domain/region.py`**: `ROAD_GRAPH_TILE_ZOOM = 12`（Road Graph専用の固定ズームレベル。RegionServiceの`ROAD_TILE_MIN_ZOOM`/`MAX_ZOOM`はMapLibreの表示ズームに追従するための範囲だが、Road Graphには「現在の表示ズーム」という概念が無いため単一の固定値とした）。`tiles_covering_bbox(bbox, z)`（新規）を追加。任意のbboxを覆う最小限のXYZタイル群の(x,y)一覧を返す純粋関数で、既存の`tile_bounds_lonlat`（その逆関数に相当）と対で使う
- **`backend/app/infrastructure/road_graph_models.py`**: `RoadGraphTileRow`（新規、`road_graph_tiles`テーブル）を追加。「このタイルはOverpassへの問い合わせを完了した」ことだけを記録する取得済みマーカー（`road_nodes`/`road_edges`にデータが実在するかどうかとは独立して判定する）
- **`backend/app/infrastructure/road_graph_repository.py`**: `is_tile_cached(zoom, x, y)`/`mark_tile_cached(zoom, x, y)`を追加
- **`backend/app/services/graph_service.py`**: `get_or_build_graph_with_attributes`を書き換え。要求bboxを`tiles_covering_bbox`でタイル群に分解し、タイルごとに`is_tile_cached`で正確に判定、未取得タイルだけをOverpassへ**順に**問い合わせて（公開Overpassインスタンスへの配慮として並列化しない、RegionServiceと同じ方針）永続化する。Overpass取得に失敗したタイルはマークしない（次回リクエストで再取得を試みる、RegionServiceの路面タイルキャッシュと同じ方針）。全タイルの取得を保証してから`get_graph_in_bbox`でDBを読むため、返るデータは常に要求bboxを正確にカバーする
- テスト: `test_region.py`に`tiles_covering_bbox`の検証（単一タイルに収まるケース・複数タイルにまたがるケース・世界の端でのクランプ）を追加。`test_graph_service.py`のタイルキャッシュ系テストを、実際のタイル境界（`tile_bounds_lonlat`から逆算した既知のbbox）を使う形に書き換え、複数タイルにまたがるリクエスト・部分キャッシュ・一部タイルのみ取得失敗するケースを検証。既存を含む全205件がグリーン

### 設計・実装レビュー（Phase 1-5・永続化・タイルキャッシュ一式）

ユーザーの依頼により、`backend/`のRoad Graph移行作業一式（frontend/は別プロセスが並行作業中のため対象外）をコードレビューした。7件の指摘のうち4件を修正し、3件は既知の制約として記録するに留めた（理由は各項目に記載）。

#### 修正した指摘

1. **`.env.example`のDATABASE_URLが同期スキーム（`postgresql://`）のままだった**: `database.py`が非同期エンジン（asyncpgドライバ）を要求するため、コメント「not yet used by the backend」も含めて`postgresql+asyncpg://`へ修正し、実態に合わせた説明に更新した。`config.py`のデフォルト値・`docker-compose.yml`は既に正しかったが、開発者が`.env.example`をコピーして使う際に接続エラーになる状態だった
2. **`get_or_build_graph_with_attributes`が「取得失敗」と「道路が無い地域を正常に確認できた」を区別できていなかった**: 海・公園など道路が1本も無い地域は、Overpass取得自体は成功して空のグラフを返すが、旧実装は`get_graph_in_bbox`が0件ヒット（=None）を返すケースを一律「失敗」として扱っていた。タイルは正しくキャッシュ済みとしてマークされ続けるため、**そのような地域へのリクエストは永久にNoneを返し続ける**バグだった。取得ループ中に実際の取得失敗（`any_tile_fetch_failed`）を追跡し、失敗が無ければ0件ヒットを「空だが正常」として扱うよう修正した
3. **`GraphService`のFK前提条件が`ElevationAttributeService`にドキュメント化されていなかった**: `repository`指定時、`ElevationAttributeService.get_attributes_for_graph`はEdgeがPostGISに保存済みであることを暗黙に要求する（`elevation_attributes.edge_id`が`road_edges.edge_id`への外部キーのため）。`GraphService.build_graph_for_bbox`（DB未保存）から得たRoadGraphと組み合わせると外部キー制約違反になる、現状は到達しないが将来の誤用を招きうる罠だったため、docstringに前提条件を明記した
4. **`_lonlat_to_tile_index`が範囲外の緯度でmath domain errorを起こしうる**: `BoundingBox`は`Coordinates`と異なり緯度の範囲を検証しないため、90度を超える値が渡された場合`math.log(負の値)`で`ValueError`を送出しうる状態だった。Web Mercatorの有効範囲（±85.0511度）へクランプするよう修正し、回帰テストを追加した

#### 既知の制約として記録するに留めた指摘（意図的に未修正）

5. ~~**タイル境界の位置によって、同じOSM Wayの交差点分割が取得タイミング次第で変わりうる**~~ → **根本修正済み**。詳細は次項「タイル境界依存の交差点分割不一致問題：根本修正」を参照
6. **同一タイルへの同時リクエストに対するロック機構が無い**: `is_tile_cached`確認→Overpass取得→`save_raw_ways`→`mark_tile_cached`の一連の流れはトランザクション分離されておらず、2つのリクエストが同時に同じ未取得タイルへアクセスすると両方がOverpassへ問い合わせてしまう（「並列化せず順に問い合わせる」という設計意図が単一リクエスト内でのみ有効）。ただし、これは既存の`RegionService`の路面タイルキャッシュ（`tile_cache.py`）も同じ弱点を持っており、このプロジェクトが既に許容している既知のリスクパターンと同等であるため、Road Graph側だけを先に対策することはしなかった
7. ~~**`save_graph`等がNode/Edge/Attributeごとに`Session.merge`を個別実行しており、1タイルあたり数百〜数千回のクエリになりうる**~~ → **解消済み（Phase 1で必須と判明し対応）**。都心部bbox（Edge十数万）で1リクエストが数十分オーダーになることをE2Eで確認し、全保存系をバルクUPSERT（`INSERT ... ON CONFLICT`、1000行/文）へ置き換えた（詳細は「OSM PBF取込バッチ（Phase 1）」参照）。当時の判断（実接続確認まで見送り）の記録として残す: バルクUPSERT（`INSERT ... ON CONFLICT DO UPDATE`）に置き換えれば改善するが、実PostGISに接続できないこの環境ではGeoAlchemy2のジオメトリ値を含むバルク文が正しく動くか検証できない。誤った書き換えを未検証のまま入れるより、パフォーマンス課題として記録し、実接続確認のタイミングで対応する方が安全と判断した

修正後、レビューで追加した回帰テスト（DATABASE_URLの整合性は自動テスト対象外、緯度クランプ・空地域の扱いの2件）を含め、既存を含む全207件がグリーン（この時点。後述の根本修正でさらに増える）。

### タイル境界依存の交差点分割不一致問題：根本修正

レビュー指摘5について、対応レベルをユーザーに確認したところ「根本修正」を選択。**生のOSMデータ（Way/Node）とRoad Graph構築（交差点分割）を分離する**設計に作り直した。

#### 設計

```
Overpass（タイル単位で問い合わせ）
    ↓
生のOSM Way/Nodeデータをそのまま永続化（osm_raw_ways / osm_raw_nodes）
    ↓ ※取得元タイルに依存しない安定した層。素直にUPSERTしてよい
    ↓
Road Graph構築リクエスト時、DB上の既知の生データ全体から
「要求bbox内にノードを持つWay（主対象）」と
「それらのWayが参照する全ノード（Way全長分）を1つでも共有するWay（近傍）」を取得
    ↓
build_road_graph（無変更）をこの結合されたWay集合に対して実行
    ↓
主対象Way分のEdgeのみをdelete-then-reinsertで永続化（近傍Wayの永続化には触れない）
```

- **`backend/app/infrastructure/road_graph_models.py`**: `OsmRawNodeRow`/`OsmRawWayRow`（新規）。`OsmRawWayRow.node_ids`はPostgreSQL配列型（`ARRAY(BigInteger)`）で保存し、GINインデックス（`&&`演算子による重なり検索）を張る。**実装中に発見した問題**: `osm_node_id`/`osm_way_id`を単一列の整数主キーにすると、SQLAlchemyが自動的に`BIGSERIAL`（自動採番）だと解釈してしまう（DDLコンパイルで確認）。これらは常にOSM側のIDを明示的に指定する値のため、`autoincrement=False`を明示して回避した
- **`backend/app/infrastructure/road_graph_repository.py`**:
  - `save_raw_ways(way_specs, node_coords)`: 生データのUPSERT。Wayのタグ・ノード列は取得元タイルに関わらず常に同じ内容になるため曖昧さが無い
  - `get_way_specs_with_closure(bbox)`: 主対象Way（bbox内にノードを持つ）→ それらの全ノード（Way全長分）→ それらのノードを共有する近傍Wayを2段階のクエリで取得する。戻り値は`(WaySpec一覧, ノード座標, 主対象WayのosmWay ID集合)`
  - `save_graph(graph, way_ids_to_replace)`: `way_ids_to_replace`を指定すると、そのosm_way_idを持つ既存Edge行を全削除してから挿入し直す（delete-then-reinsert）。これにより、Wayの分割結果が変わった場合でも孤立した古いEdge行が残らない
- **`backend/app/services/graph_service.py`**: `get_or_build_graph_with_attributes`を書き換え。タイル取得ループはEdge構築を一切行わず`save_raw_ways`のみ呼ぶ。全タイルの生データ取得を保証した後、`get_way_specs_with_closure`→`build_road_graph`（無変更）→ 主対象Way分のみを`save_graph(..., way_ids_to_replace=primary_way_ids)`で保存、という流れに変更した
- テスト: `test_graph_service.py`の`FakeRoadGraphRepository`を実際のclosureロジック（1ホップ近傍探索）で実装し直した。**新規回帰テスト`test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`**で、Way Wがタイル境界をまたぎ側道Bと交差点を共有するケースを構築し、「Bを含むタイルを直接見た場合」と「Bを含まないタイルだけを見るがBは既に別途取得済みの場合」の両方で、Wが同じ分割結果（4 Edge、同じ距離集合）になることを確認した

#### この設計で解決されること・残る限界

- **解決**: 近傍Wayが既にDBに存在する限り（＝そのWayを含むタイルが過去に一度でも取得されていれば）、どのタイル経由で「主対象」の計算をトリガーしたかに関わらず、交差点の分割結果が一貫する
- **残る限界（結果整合的、1ホップに限定）**: 近傍探索は主対象Wayの全長分のノードから1ホップに限定している。近傍として取得したWay自身が、さらに別の（まだ近傍探索の対象外の）Wayと交差点を共有している場合、その交差点は近傍Way自身が別のリクエストで「主対象」として処理されるまで最新の状態に反映されない。道路網全体の連結成分を毎回たどる完全な整合性チェックはコストに見合わないと判断し、トレードオフとして許容した。実務上は、routeが実際に通る範囲を何度かリクエストするうちに自然と収束していく設計になっている
- **意図的に永続化しない対象**: 近傍Wayとして取得したWay自身のEdgeは、この呼び出しでは保存・更新しない（不完全な文脈で計算した分割結果によって、他のリクエストが正しく永続化したEdgeを誤って上書きしないため）

既存を含む全208件がグリーン（実PostGISへの接続・GIN索引の実動作・配列型のOverlap検索は引き続き未検証、DDL・クエリのコンパイルチェックのみ実施済み）。

### Road Graphを実際のルーティングへ接続する移行（完全移行）

ユーザーから「Road Graphを実際のルーティングに接続する、完全に移行する」との指示を受けた。これはPhase 1-5・「永続化」・「根本修正」で構築してきたRoad Graph/Road Attribute/Evaluation Engineを、これまでのように既存のopenrouteservice委譲（`route_generator.py`）と並行する独立構造のままにせず、**実際に`/api/routes/generate`のルート生成そのものを置き換える**作業。仕様書34章「探索アルゴリズムを独断で変更しない」との緊張関係があったため、着手前にユーザーへ3点確認した。

#### 着手前に確認した設計判断

1. **パスファインディングアルゴリズム**: 自前でDijkstraを実装 vs 標準ライブラリ（NetworkX）を導入 → **NetworkXを導入**を選択。「独自の経路探索アルゴリズムの実装はしない」という仕様書の原則と、標準ライブラリの利用は矛盾しないという判断
2. **移行範囲**: 経路探索の中核のみ置き換え（風は旧WindServiceを流用） vs 全面作り直し（標高・路面・風を含むルート生成ロジック全体をRoad Graph中心に再設計、風はEvaluation Engine未実装のため先にPhase 6実装が必要） → **全面作り直し**を選択。Phase 6（Dynamic Data対応・風）が前提として必要になることを理解した上での選択
3. **PostGIS前提**: 依存なしで先に動くように組む vs 先にPostGISを用意する → **依存なしで先に動くように組む**を選択。`repository`を注入しない構成（毎回Overpass/GSIへ問い合わせる）で、まず実際に動くことを検証する方針

#### 実施内容

- **Phase 6（Dynamic Data対応・風）を`domain/evaluation.py`へ実装**: `RoutePreference`に`wind_weight`を追加（デフォルト値をelevation:road:wind = 0.25:0.30:0.45に変更、`route_preference.yaml`も更新）。`compute_wind_penalty(edge, wind)`（新規）がEdgeの進行方向と風向風速から`domain/wind.py: WindCalculator`を使って（既存のまま再利用）wind_penaltyを算出し、`compute_edge_cost`のCost計算に組み込んだ。**既知の簡略化**: 出発時刻からの推定累積走行時間に応じた風の時間変化は見ない（探索中はまだ累積走行時間が確定しないため）。出発時点・起点付近の風をルート全体に一様適用する
- **`backend/app/domain/routing.py`（新規、Route Engine）**: `build_networkx_graph`（RoadGraph+Edge CostからNetworkXの`DiGraph`を構築、Hard Constraintで除外されたEdgeは含めない）、`find_nearest_node`（総当たりで指定地点に最も近いNodeを探す、PostGIS未使用のため空間インデックス無し）、`shortest_path_node_ids`（`nx.dijkstra_path`をそのまま利用）、`path_to_edge_ids`、`concat_node_paths`
- **`backend/app/services/route_generator.py`を全面書き換え**: `RoutingService`/`ElevationService`/`WindService`への依存を無くし、`GraphService`/`ElevationAttributeService`/`EvaluationService`/`WeatherService`/`RouteScorer`/`RoutePreference`を使う構成にした。8方位の候補地点をジオメトリで計算する部分（`destination_point`）は従来のまま流用。`RouteScorer`・`scoring.yaml`（ルート単位の総合スコアリング）も既存のまま再利用した（Evaluation Engineとは対象が異なる別の重み設定のため、混同しないという方針を維持）
- **`backend/app/api/routes.py`のDIを配線し直し**: `get_route_generator`が新しい依存関係を注入するよう変更。`/api/routes/preview`（Step3の疎通確認用エンドポイント）は引き続き`RoutingService`/`ORSClient`を使うため無変更
- **不要になったコードを削除**: `services/elevation_service.py`・`services/wind_service.py`（ルート単位・12点サンプリングの評価、Road Graph移行によりEdge単位の評価に置き換わったため）とそれぞれのテスト。`domain/geo.py`の`sample_indices`/`sample_line_coordinates`/`sample_line_points`（ルート単位サンプリング専用で他に呼び出し元が無くなったため）。`domain/road.py`の`paved_percent`/`surface_id_at_index`/`is_good_surface`/`GOOD_SURFACE_IDS`（openrouteserviceの`extra_info=surface`数値ID形式専用で、Road Graphへの移行によりOSMタグ形式の`classify_osm_surface`のみを使うようになったため）。削除前にGrep等で他に参照が無いことを確認した上で削除している
- **`requirements.txt`に`networkx==3.4.2`を追加**

#### 実機検証で発見・修正した2つの重大な性能問題

コードを書き終えた時点でテストは全てグリーンだったが、**実際にこのdev環境で動いているバックエンドへ生のリクエストを送ってみたところ、8方位すべてが失敗し空の結果が返る**という問題を発見した。単体テストは全てモックを使っており、この種の実運用上の問題は検出できなかった。以下の手順で原因を切り分けて修正した。

1. **8方位が並列にOverpassへ問い合わせて拒否される**: 当初の実装は方位ごとに個別のbboxを計算し、`GraphService.get_or_build_graph_with_attributes`を8並列（`asyncio.gather`）で呼んでいた。公開Overpassインスタンスへ8並列で問い合わせたところ、全て拒否・失敗する事象を実機で確認した。**修正**: 起点を中心とした単一の円（8方位分の経由地点をすべて覆う半径）でRoad Graphを1回だけ取得し、8方位全てで共有する設計に変更した。これにより`generate_loops`全体でOverpassへの問い合わせは1回のみになった（`OverpassClient`が既に持つ「未キャッシュのセルを並列化せず順に問い合わせる」という公開インスタンスへの配慮の精神を、方位間でも徹底する形）
2. **標高取得がRoad Graph全体に対して行われ非現実的に遅い**: 当初の実装は、経路探索前にRoad Graph全体（bboxによっては数万Edge）に対して`ElevationAttributeService.get_attributes_for_graph`を呼んでいた。実機検証で、200Edge分の標高取得に約12秒かかることを確認し、実際の対象（東京都心部で約6.5万Edge）に外挿すると1方位あたり1時間近くかかる計算になることが判明した。**修正**: 経路探索用のEdge Costからは標高を除外し（distance・路面・風のみで計算）、Dijkstra探索で最短路を確定した「後」に、その経路上のEdge（数十〜数百程度）だけに絞って標高を取得する設計に変更した。**この結果、標高（勾配）は実際の経路選択には影響せず、経路確定後の表示・スコアリング用途にのみ使われる**という重要な仕様変更を伴う（`RoutePreference.elevation_weight`は区間ごとの難易度表示や`RouteScorer`の総合スコアには反映されるが、Dijkstra探索自体には反映されない）

修正後、実機（このdev環境の実際のバックエンドプロセス、および直接`RouteGenerator`を呼び出すスクリプトの両方）で東京・王子駅付近、距離4km指定のリクエストが成功することを確認した。8方位全てで妥当な候補（距離4.46〜6.28km、獲得標高14〜44m、road_score=100.0、区間数154〜234）が生成され、`total_score`によるランキングも機能した。所要時間は約40〜70秒（PostGISキャッシュ無しのため、Overpass取得＋経路確定後の標高取得を毎回行う。パフォーマンス上の既知の制約として次項に記載）。

#### 新規/更新テスト

- `test_evaluation.py`: `compute_wind_penalty`の向かい風/追い風、`compute_edge_cost`への風統合の検証を追加
- `test_routing.py`（新規）: `build_networkx_graph`（Hard Constraint除外）、`find_nearest_node`、`shortest_path_node_ids`（コスト最小経路の選択・到達不能・始点=終点）、`path_to_edge_ids`、`concat_node_paths`の検証
- `test_route_generator.py`（全面書き換え）: 起点を中心とした「車輪」状のRoad Graphフィクスチャ（`build_loop_graph`）を新規構築。**フィクスチャ構築時に発見したバグ**: 隣接方位の経由地点が同一の実座標を指すにもかかわらず別々のNodeとして作ってしまい、最近接ノード探索が別方位のNodeへ誤ってスナップする問題があった（実データでは実在の交差点1つに収束するため起きない、テストフィクスチャ特有の問題）。共有Nodeを使う「スポーク＋アーク」構造に直して解決した。Overpass呼び出しが1回だけであること・標高取得がパス上のEdgeだけに絞られていること（フルグラフではないこと）を回帰テストとして明示的に追加
- `test_road.py`/`test_geo.py`: 削除した関数のテストを撤去
- 既存を含む全205件がグリーン

#### 既知の制約・次に検討すべきこと

- **標高が経路選択に影響しない**: 上記の性能問題への対応の結果、勾配がきついかどうかは経路の「選び方」には反映されず、確定した経路の「見せ方」（区間ごとの難易度表示、`RouteScorer`の総合スコア）にのみ反映される。PostGISキャッシュが有効になれば、標高もあらかじめEdge Attributeとして永続化されているため、探索時にも安価に参照できるようになり、この制約は解消できる可能性がある
- **1リクエストあたり40〜70秒**: PostGISキャッシュ無しの初期実装としては動作するが、実用的なレスポンス速度ではない。次の最優先事項は引き続き実際のPostGIS接続確認（次項参照）
- **風は出発時点の一様値**: Dynamic Data対応の簡略化として、Edgeごとの推定到達時刻による風の時間変化は見ていない
- **`_bbox_around_point`のマージン（`BBOX_MARGIN_RATIO`/`BBOX_MARGIN_MIN_KM`）は暫定値**: 実データでの検証は小さい距離（4km）でしか行っていない。大きい距離（15km・30km等、既存Step4での実機検証相当）でも同様に機能するかは未検証
- **NetworkXの`DiGraph`は同一ノード間の並行Edgeを1本しか保持できない**: 稀なケースで最安のEdgeが選ばれない可能性がある（`MultiDiGraph`への変更は今回未実施）

### 実PostGISでの動作検証（Phase 0）

OSMデータのPBF事前取込によるOverpass依存解消の設計検討（docs/osm-pbf-import.md）に着手するにあたり、その前提（同設計書「9. 段階的導入計画」のPhase 0）として、これまで未検証だった永続化層の実DB動作確認を実施した。

- **環境**: dev機にDockerは無いが、**ネイティブのPostgreSQL 18.6（Windowsサービス`postgresql-x64-18`、ポート5432）が稼働しており、PostGIS 3.6.2が利用可能**だったためこれを使用した（docker-compose.ymlの`postgis/postgis:16-3.4`は使っていない。イメージのPG16との差異は現時点で問題になっていない）。`ridecompass`ロール／`ridecompass` DB／PostGIS拡張／全7テーブルはローカルに作成済み
- **検証方法**: `backend/scripts/verify_postgis_phase0.py`（新規）。交差点共有・タイル境界外の近傍Way・一方通行を含む小さなフィクスチャ（実OSMと衝突しない910兆台の架空ID）を実DBへ書き込み、22項目を検証して終了時に全行削除する。再実行可能
- **結果**: 22/22 PASS（2026-08-14）。具体的に実機確認できたこと:
  - `create_tables()`の冪等性（既存スキーマ・PostGIS拡張ありでも成功）
  - `save_raw_ways`のUPSERT、GINインデックス（`node_ids`の`&&`検索）による`get_way_specs_with_closure`の主対象／1ホップ近傍の判定
  - `save_graph`の`Session.merge` UPSERT・FK制約（Node→Edge順）・delete-then-reinsertの冪等性
  - `ST_MakeEnvelope`/`ST_Intersects`によるbbox空間検索、GeoAlchemy2 `from_shape`/`to_shape`のジオメトリ往復で**緯度経度の軸順の取り違えが無い**こと（懸念事項だった）
  - elevation/surface attributesの保存・読込（timestamptzの往復含む）
  - `is_tile_cached`/`mark_tile_cached`、および`GraphService.get_or_build_graph_with_attributes`のオーケストレーション一式（初回はタイル数分だけデータソースへ問い合わせ、2回目はDBのみで完結し問い合わせゼロ）
- **注意（未決定事項）**: `backend/.env`の`DATABASE_URL`は現在**Supabase（クラウドPostgres）を指している**。今回の検証は環境変数`DATABASE_URL`で一時的にローカルDBへ上書きして実施した（.envは変更していない）。ローカルPG18とSupabaseのどちらを恒常的な開発用DBとするかは、PBF取込のPhase 1着手時に決める
- **残課題**: バルクUPSERT性能（レビュー指摘7、行単位`Session.merge`）は未対応のまま（PBF取込バッチはCOPY方式で最初から回避する設計）。ランタイムDI（`api/routes.py`への`repository`注入）も未配線

### OSM PBF取込バッチ（Phase 1）

Phase 0に続き、docs/osm-pbf-import.mdの設計に沿ってPBF取込バッチを実装し、E2E（Overpassゼロでのルート生成）まで検証した。

- **実装物**: `backend/app/batch/`（`import_pbf.py`＝CLI本体、`profile.py`＝取込プロファイルの読み込み/マッチング、`pbf_source.py`＝pyosmium依存を閉じ込めた読取層、`import_profile.yaml`＝既定プロファイル）。依存は`requirements-batch.txt`（`osmium==4.1.1`、webサービスには入れない）。スキーマは`osm_raw_ways.geom`列（実体化済みLINESTRING＋GiST索引＋旧データのバックフィル）と`osm_import_runs`テーブル（実行記録）を追加
- **DI配線**: `config.py`の`road_graph_use_repository`（既定false）。trueで`get_graph_service`/`get_elevation_attribute_service`へ`RoadGraphRepository`を注入する
- **実測（BBBike Tokyo抽出79MB、bbox=35.60,139.65,35.75,139.85）**: 取込150,265 way / 511,948ノード / 16タイル（z12）マーク、194秒。DBサイズは導出データ（road_edges 155,086行等）込みで約298MB
- **E2E（東京駅起点、4km周回、`scripts/verify_phase1_e2e.py`）**: 「呼ばれたら失敗するOverpassスタブ」を注入した状態で8方位すべての候補生成に成功し、**Overpass呼び出し0回**を確認。所要222.7秒（prepare 187s / trace 5.6s / evaluate 29s）
- **Phase 1で発見・修正した問題（実データ規模で初めて顕在化）**:
  1. **行単位`Session.merge`が実用不能（レビュー指摘7の顕在化）**: 都心bbox（主対象way約4.8万・Edge十数万）でE2Eが10分以上無応答。全保存系（`save_graph`/`save_raw_ways`/attributes）を複数行VALUESのバルクUPSERTへ置き換え（1000行/文、asyncpgのパラメータ上限32767を考慮したチャンク分割）
  2. **`get_way_specs_with_closure`のGIN配列検索がスケールしない**: 数十万要素の配列パラメータによる`&&`検索を、空間検索（主対象＝bboxと`ST_Intersects`するway、近傍＝主対象全長の`ST_Extent`と交差するway。旧semanticsの上位互換/上位集合で正しさは維持）へ置き換え。`osm_raw_ways.geom`が前提のため`create_tables()`に旧データのgeomバックフィルを追加
  3. **`AsyncSession`の同時使用クラッシュ**: `RoadGraphEngine.evaluate_loops`が候補ごとに`asyncio.gather`で並列実行するため、注入した`ElevationAttributeService`のrepository（単一セッション）が同時使用され`IllegalStateChangeError`で落ちることをE2Eで確認。repositoryアクセスのみ`asyncio.Lock`で直列化（GSIへのHTTP問い合わせは並列のまま）。再入検出フェイクによる回帰テストを追加
- **既知の制約・次の課題**:
  - ~~**prepareの187秒**: 大半は「タイル取得済みでも毎リクエスト、生データから交差点分割を再計算し全Edgeを再保存する」現設計のコスト（closureクエリ＋`build_road_graph`＋十数万行の再UPSERT）。生データが変わっていなければ`road_edges`を直接読む省略パスの導入が次の最適化候補~~ → **解消済み**。`RoadGraphRepository.is_split_up_to_date`＋`get_graph_in_bbox`による省略パスを実装（`osm_raw_ways.split_at`と`updated_at`の比較で鮮度判定。`save_raw_ways`のUPSERTを内容不変時のno-op化した上で導入。1つのWayが複数タイルにまたがると隣接タイル取得だけでstale誤判定する問題への対処）。実測値は`backend/benchmarks/README.md`参照
  - E2Eは東京都心（日本有数の道路密度）での数値。郊外ではway数が1桁少なくなり大幅に短くなる見込みだが未計測
  - 天候（Open-Meteo）・標高（GSI）は引き続き外部API（Phase 1の解消対象はOverpassのみ）

### RegionServiceのPostGIS化（Phase 2）

docs/osm-pbf-import.md「Phase B」の実施記録（2026-08-14）。地域路面レイヤー（路面ベクタタイル）のデータソースをPostGIS第一系統へ変更し、本番想定（Supabase）の容量予算にも対応した。

- **カバレッジ判定**: 表示タイル（z12-15）を`domain/region.py: tile_ancestor`（新規、右シフトによる祖先タイル計算）でz12へ丸め、`road_graph_tiles`の取得済みマークで「このタイルのデータはDBにあるか」を正確に判定する。PBF取込バッチとRoad Graphのタイル取得が同じマークを共有しているため、どちらで取得された範囲でも路面タイルはDBだけで生成できる
- **タイル生成**: `RoadGraphRepository.get_road_surface_tile_mvt`が、カバレッジ判定（z12祖先タイルのマーク確認）・`osm_raw_ways.geom`（Phase 1で実体化済み）の`ST_Intersects`検索・MVTエンコード（`ST_AsMVT`/`ST_AsMVTGeom`、surface3値分類のCASE式込み）を**1クエリ＝DB往復1回**でPostGIS側にて実行し、完成済みタイル1個だけを転送する（カバレッジ外はNULL側の列で判別しMVT生成サブクエリ自体を実行しない）。ファイルキャッシュの既存方針は無変更（2026-08-15改修。当初のway行転送＋Pythonエンコード構成は、遠隔DBで1タイル数秒→パンのバースト時にNext.jsプロキシの30秒タイムアウト500を招いていた。Overpassフォールバック経路のみ従来の`encode_road_surface_tile`を使用）。タイル応答には`Cache-Control: public, max-age=3600`を付与し、再訪・リロード時のブラウザ再取得を抑える（データはPBF取込時にしか変わらないため。取込反映の遅れは最大1時間で許容）
- **フォールバック**: 取込範囲外・DB障害時は`settings.overpass_fallback_enabled`（新設、既定true）に従い従来のOverpass問い合わせへフォールバックする（「PostGIS停止が既存機能を丸ごと壊さない」という過去の選択肢A却下時の懸念への回答）。falseなら空タイルを返し**キャッシュには保存しない**（後から取込された際に再生成させるため）。フォールバック発動・範囲外アクセスはログ方針どおり常時WARNING
- **容量予算対応（ユーザー要件: Supabaseフリー500MB→安全枠300MB）**: 実測内訳を取り、閉包クエリの空間検索化（Phase 1）以降未使用になっていたGINインデックス`ix_osm_raw_ways_node_ids`（28MB）を`create_tables()`で冪等に削除。DB全体は313MB→**284MB**となり、現行取込bbox（東京都心35.60,139.65-35.75,139.85）が300MB予算内のプロトタイプ基準規模であることを確認した。取込バッチの完了サマリに`db_size_mb`を追加し、超過を取込時点で検知できるようにした
- **検証**: ユニットテスト追加（PostGIS系統/フォールバック有無/DB障害/`tile_ancestor`）で全367件グリーン、実DB検証`backend/scripts/verify_phase2_e2e.py`で9項目PASS（取込範囲内z14タイル: 3,304地物をOverpass呼び出し0回で生成、z12タイル・範囲外の両フォールバック分岐も確認）。Phase 0検証22項目も回帰PASS

### Supabase取込とOverpass停止（Phase 3）

docs/osm-pbf-import.md「Phase C」の実施記録（2026-08-14）。ユーザー要件: 本番はSupabase（フリープラン500MB、安全枠300MB以内でプロトタイプ実施）、**Overpassフォールバックは設定で無効化しロジックは併存させる**。

- **Supabase接続確認**: `.env`の`DATABASE_URL`（`?ssl=require`付きDirect connection）でSQLAlchemy+asyncpgから接続できることを確認（PostgreSQL 17.6、PostGIS 3.3.7導入済み、ベース19MB）。疎通チェック用に`backend/scripts/check_db_connection.py`を追加。取込バッチのasyncpg直結パスには`?ssl=require`→`?sslmode=require`のDSN正規化（`_asyncpg_dsn`）を追加した（`ssl=`はSQLAlchemyのasyncpgダイアレクト固有の書き方のため）
- **取込**: 容量試算（ローカル実測284MBが予算上限規模＋標高属性の将来増分）に基づき、**bboxを約7割へ縮小**（35.61,139.67-35.74,139.83。東京駅・新宿・渋谷・上野・池袋を含む）して取込んだ。実測: 116,336 way / 389,493ノード / z12タイル4枚 / 195秒 / 取込後120MB
- **`GraphService`のフォールバック無効化フラグ**: Phase 2で`RegionService`に入れた`overpass_fallback_enabled`を`GraphService`にも追加。無効時、未取込タイルを含むルート生成リクエストはOverpassへ行かず「データ未整備」としてNoneを返す（常時WARNING）。`repository`未注入の構成では両サービスともフラグに関わらず従来どおりOverpassを使う（DBなし構成の互換性維持）
- **設定**: `.env`を`ROAD_GRAPH_USE_REPOSITORY=true`＋`OVERPASS_FALLBACK_ENABLED=false`へ変更。**コードは無変更で`.env`の2行だけで切り戻せる**
- **検証（すべてSupabaseに対して実施）**: Phase 2検証9項目PASS（東京駅付近z14タイルはローカルと同一の3,304地物）、ルート生成E2E成功（8方位・Overpass呼び出し0回・336.6秒。prepare 295秒とローカル比+108秒はWANレイテンシ分）。ユニットテスト全370件グリーン
- **容量**: E2E後のSupabase実測196MB（予算300MBに対し余裕約100MB）。**導出データ（road_edges等）はルート生成が要求した地域ぶんだけ増える**が、生OSM層から再計算可能なキャッシュのため、逼迫時は該当行のDELETEが安全な圧力弁になる（docs/osm-pbf-import.md 10章）

### 次のPhaseへの引き継ぎ事項

- ~~**最優先**: 実際のPostGISに接続しての動作確認~~ → **完了**（Phase 0）
- ~~**PBF取込のPhase 2（RegionServiceのPostGIS第一系統化）・Phase 3（Supabase取込・Overpass停止）**~~ → **完了**（前2項）。Overpass依存解消の計画（docs/osm-pbf-import.md）は全Phase完了
- ~~**prepare 295秒（Supabase・都心）の短縮**: 生データ不変時の分割再計算・全量再保存の省略パス（`is_split_up_to_date`、上記参照）はローカルPostGISで実装・実測済みだが、Supabase（WAN経由）での実測はまだ行っていない。再保存の省略はWAN環境ほど効く見込みのため、Supabase環境での再計測が次のステップ~~ → **実測済み**。Supabase（WAN経由、東京都心実データ）でCOLD/WARM実測: 1km 126.0s→18.0s（約7.0倍）、4km 211.0s→27.9s（約7.6倍）。短縮の絶対値（108〜183秒）はローカルPostGIS実測（143〜137秒）と同等以上だが、短縮**倍率**はローカル（10〜14倍）よりむしろ低い — WARM側も`is_split_up_to_date`・`get_graph_in_bbox`・`get_surface_attributes`のラウンドトリップ回数分だけWAN遅延の影響を受ける（例: `is_split_up_to_date`単体がローカル20〜30msに対しSupabaseでは780〜810ms）ため、COLD側の一括UPSERTほどには短縮率が伸びない。詳細は`backend/benchmarks/README.md`参照
- **Renderデプロイへの反映**: Render側の環境変数に`DATABASE_URL`（Supabase）・`ROAD_GRAPH_USE_REPOSITORY`・`OVERPASS_FALLBACK_ENABLED`を設定すれば同じ姿勢で動く（未実施。Render→Supabase間のレイテンシは要実測）
- **OSMデータの更新運用**: 月次程度でPBF再取込（docs/osm-pbf-import.md 8章）。`--prune`（削除way掃除）は未実装のまま
- 大きい距離（15km・30km等）でのRoad Graphベースのルート生成の実機検証（現時点では4kmでのみ確認済み）
- `compute_edge_cost`のCost計算式（distanceへの乗算ペナルティ）は初期実装であり、仕様書31章が求める「複数のCost計算方式を比較検討できる」構造は、実際に2つ目の方式を試すタイミングでリファクタリングの必要性を再評価する
- 標高が経路選択に影響しない制約（前述）をPostGISキャッシュ有効化後に解消するかどうかの検討
- 複数のRoute Preferenceプロファイル（快適性重視/トレーニング重視等）を実際に追加する場合、`route_preference.yaml`をどう複数化するかは、実際にUI/APIから選択可能にするタイミングで改めて設計する
- `ROAD_GRAPH_TILE_ZOOM = 12`は暫定値（東京付近で1辺約8km）。実データが蓄積された段階で、Overpassへの問い合わせ回数とキャッシュ粒度のトレードオフを見直す余地がある
- RegionServiceとRoad Graphのデータソース統合（選択肢A）は、Road Graphが実際にRoute Engineへ接続され「本当に使われる」段階になった今、改めて検討の俎上に載る余地がある

### ルーティングエンジンの切り替え対応（openrouteservice ⇄ Road Graph、2026-08-23〜2026-08-31の間存在した仕組み。改善計画T428で本節をarchitecture.mdから移設。改善計画T462でopenrouteserviceエンジンを完全撤去し、以降はroad_graphが唯一のエンジン）

「Road Graphを実際のルーティングへ接続する移行（完全移行）」で`/api/routes/generate`をopenrouteservice委譲からRoad Graph + NetworkX（Dijkstra）ベースへ全面置き換えたが、Road Graphの経路探索自体（ルーティングエンジンとしての精度・速度）はまだ発展途上で、今後も継続して手を入れる将来拡張と位置付けている。一方で、標高・風・路面といった「評価に必要な情報」の取得方法や地図上の見える化は、経路探索エンジンがどちらであっても検証を進めたい。そのため、経路探索エンジンを設定で切り替えられるようにし、openrouteservice委譲（外部APIキーのみで動く、枯れた実装）を使いながら評価まわりの精査を進められるようにした。

- **戦略（共通）とエンジン（差し替え可能）の分離**: 当初は「2つの`generate_loops`実装を丸ごと並行して残す」形で切り替えを導入したが、8方位・半径ヒューリスティック・距離許容フィルタ・`RouteScorer`適用・ソートという周回生成戦略が二重化し、仕様書5章の将来拡張（適応的半径調整・候補地点選定の改善等）を2回ずつ実装することになるため、直後の設計レビュー（後述）でポート分割へリファクタリングした。現在の構造:
  - **`RouteGenerator`**（`backend/app/services/route_generator.py`、戦略層・単一実装）: 経由地点の計算（`destination_point`）、8方位分の`trace_loop`並列実行、距離許容範囲フィルタ、`RouteScorer`によるtotal_score付与・ソートを持つ。エンジンには`LoopRoutingEngine`（Protocol）として`prepare`（リクエスト単位の共有準備）／`trace_loop`（1方位分の経路と距離）／`evaluate_loops`（**距離フィルタ通過後の候補だけ**への標高・風・路面評価）の3段階で委譲する。評価を後段に分離しているのは、棄却済み候補への外部API問い合わせ（GSI標高等）を避けるため（旧openrouteservice版が持っていたクォータ節約の挙動を両エンジン共通の戦略として保証する形。Road Graph版は従来フィルタ前に標高を取得していたが、この分割でフィルタ後のみになった）
  - **`OpenRouteServiceEngine`**（`backend/app/services/openrouteservice_engine.py`）: 経路はopenrouteservice Directions API（`RoutingService`/`ORSClient`）へ1方位1リクエストで委譲し、評価は復元した`ElevationService`（距離連動サンプリング、約1km間隔・12〜32点）・`WindService`（区間ごとの推定到達時刻の風）で行う
  - **`RoadGraphEngine`**（`backend/app/services/road_graph_engine.py`）: `prepare`でRoad Graphを1回だけ取得しEdge Cost・探索用グラフ（`SparseRoadGraph`、改善計画T220）・起点スナップ・出発時点の風を構築、`trace_loop`でDijkstra探索、`evaluate_loops`で経路上のEdgeだけに標高を取得する（完全移行時の実機検証で判明した性能問題への対応をポート3段階へ対応付けた形。`prepare`は当初NetworkXグラフも並行構築していたが、探索本体は最初からscipy.sparse版のみを使っており並行構築分はランタイムで誰にも読まれていなかったため改善計画T226で削除、`prepare`のコストが約0.2〜0.4秒/リクエスト@69,216エッジ短縮した）
- **`domain/geo.py`のサンプリング関数も復元**: `sample_indices`/`sample_line_coordinates`/`sample_line_points`（`geo.py`）は、完全移行で「Road Graphエンジンからは参照されなくなった」という理由で削除されていたが、`OpenRouteServiceEngine`が引き続き必要とするため復元した。
- **路面判定は1系統へ統一済み（2026-08-15、改善計画T21）**: 導入当初は`GOOD_SURFACE_IDS`/`paved_percent`/`surface_id_at_index`/`is_good_surface`（openrouteserviceの数値ID基準）と`classify_osm_surface`（OSMタグ基準、RoadGraphEngine用）の2系統が併存していたが、`decisions/pre-static-attributes-gate.md`（決定1）に基づき、ORSエンジンのサンプル点を`RoadGraphRepository.get_nearest_surface_tags`（PostGIS KNN、スナップ半径`SURFACE_MATCH_MAX_DISTANCE_M=30m`）で自前DBのEdgeへ空間マッチしてOSMタグを読む方式へ統一した。前者4関数は削除済み。両エンジンとも`classify_osm_surface`＋距離加重集計`distance_weighted_road_score`（`domain/road.py`、Edge/サンプル区間どちらの距離単位でも使える共通関数）を使う。`settings.road_graph_use_repository=false`（DBなしプロファイル）では空間マッチ自体を行わず、ORSエンジンの路面評価は全区間`None`になる。
- **設定と既定値（当時）**: `config.py`に`routing_engine: Literal["openrouteservice", "road_graph"]`を追加した（`.env`の`ROUTING_ENGINE`で上書き可）。導入当初はマップの見える化・評価情報の精査を優先するという方針に合わせ既定値を`openrouteservice`にしていたが、改善計画T236・T241〜T246（品質比較・連結性調査・本番DB起動不能問題とDELETE性能問題の解消）を経て、**改善計画T247（2026-08-23）で既定値を`road_graph`へ切り替えた**。その後、改善計画T462（2026-08-31）で`routing_engine`設定自体・openrouteservice側の全実装を撤去し、road_graphが唯一のエンジンになった。
- **DI（`api/dependencies.py`の`get_route_generation_builder`）**: `settings.routing_engine`の値に応じてどちらのエンジンを構築し`RouteGenerator`へ渡すかを切り替える。両エンジン分の依存を`Depends`パラメータとして宣言しているため、FastAPIの制約上、実際には使わない側の依存（`httpx.AsyncClient`等、いずれもこの時点では実I/Oを伴わない軽量なオブジェクト）も毎リクエスト構築されるが、条件分岐に応じて一部の`Depends`だけを解決する簡便な方法が無いため単純さを優先した（コード上のコメント参照）。研究インターフェース改善Phase 1（T23）で、`RouteGenerator`本体ではなくビルダーを返す形へ再構成し、エンドポイントが検証済みの重み上書き（無ければYAML既定値）を渡して組み立てを完了する。
- **`/api/routes/preview`**: Step3の疎通確認用エンドポイントは当初`RoutingService`/`ORSClient`直接使用のままエンジン切り替えの対象外だったが、改善計画T237で`get_preview_builder`（`api/dependencies.py`）を新設し`routing_engine`に連動するようにした（`RoadGraphEngine.preview_segment`参照）。

#### 設計レビュー（エンジン切り替え後）と対応した推奨アクション

エンジン切り替え導入直後に仕様書・実装・将来拡張の観点で設計レビューを実施し、優先度上位4件を実装した。

1. **評価値の定義統一＋`engine`フィールド（レビュー指摘H2）**: エンジン間で同じフィールド名の数値の意味が食い違っていた3点のうち2点を統一した。
   - **road_scoreの不明路面の扱い**: openrouteservice数値ID版`paved_percent`は不明を分母に含めて実質減点していたが、OSMタグ版（`classify_osm_surface`ベースの距離加重集計）と同じ「**不明は分母から除外**（不明≠悪い路面）、全区間不明ならNone」へ統一した。あわせて`is_good_surface`もID 0（Unknown）を`False`ではなく`None`（判定不能）へ変更し、両語彙の3値判定（良い/悪い/不明）の意味を揃えた（`domain/road.py`冒頭の「正準定義」コメント参照）
   - **区間難易度（`segments[].difficulty`）の合成重み**: openrouteservice版は`scoring.yaml`（候補集合内の相対評価用）を流用しており、`route_preference.yaml`を使うRoad Graph版と地図の色分けが食い違っていた。**両エンジンとも`route_preference.yaml`（Edge単位の絶対評価用の重み）へ統一**した。`scoring.yaml`はルート単位のtotal_score専用となり、役割の境界が明確になった（副次効果として、旧openrouteservice版がリクエストごとに行っていた`load_scoring_weights()`のファイルI/Oも除去された）
   - **区間勾配（`segments[].gradient_percent`）の符号**（後日追加: 2026-08-15の全体設計レビューB1で発覚）: openrouteservice版は絶対値で返しており（下り坂が登り扱いになり、フロントの勾配色分けの「下り」カテゴリが既定エンジンで一度も表示されない）、Road Graph版の符号付き`average_grade`と食い違っていた。**両エンジンとも符号付き（進行方向基準、登り=正/下り=負）へ統一**した（`domain/route.py`: `RouteSegmentDetail`の正準定義参照。難易度への変換は`gradient_difficulty`が絶対値を取るため影響なし）
   - **wind_scoreの意味の違いは意図的に残す**: openrouteservice版は区間ごとの推定到達時刻の風（時間変化あり）、Road Graph版は出発時点の風の一様適用（探索中は到達時刻が未確定という制約）。将来の時間展開対応まで統一できないため、レスポンスに**`engine`フィールド**（`RouteGenerateResponse.engine`、フロントの`types/route.ts`にも追加しデバッグログに出力）を追加し、どちらの定義の数値かを識別可能にした
2. **`/api/routes/generate`のレート制限・同時実行ガード（レビュー指摘H3)**: 最も高コストなエンドポイント（openrouteservice: 外部APIクォータ消費 / road_graph: コールド時40〜70秒＋Overpass/GSI大量問い合わせ）が無防備だったため、既存の`check_rate_limit`によるper-IP上限（`GENERATE_RATE_LIMIT_PER_MINUTE = 10`/分）と、プロセス全体の同時実行数上限（`GENERATE_MAX_CONCURRENT = 2`、`asyncio.Semaphore`）を追加した。上限超過は待たせず429で即座に返す（ブラウザのリトライ・連打による外部サービスへの負荷の積み上げ防止）
3. **`ORSClient`のコネクション共有（レビュー指摘M1）**: 呼び出しごとに新規`httpx.AsyncClient`を生成していた（8方位の周回生成でTLSハンドシェイク8回。`ElevationClient`で実測57秒→7秒の差を生んだのと同じパターン）ため、他のクライアントと同様にDI（`get_routing_service`）が生成する共有コネクションのコンストラクタ注入へ統一した
4. **ポート分割（レビュー指摘H1）**: 前述の「戦略（共通）とエンジン（差し替え可能）の分離」

レビューで指摘されたが今回は見送った項目（既知の課題として記録）:
- **Road Graph版の`segments`肥大化（M3）**: Edge=区間のため4kmで150〜230区間、30km×8候補では数千区間になりペイロード・描画コストが嵩む。表示用の集約（約500m単位のビン化等）をAPI境界で行う案
- **周回品質（M4）**: 両エンジンとも「行きと帰りが同じ道」の往復型周回を防ぐ仕組みが無い。Road Graph版は「前の脚で使ったEdgeのコストを一時的に引き上げる」ことで自前修正でき、自前エンジンの差別化ポイントになりうる
- **`find_nearest_node`の距離上限が無い（M5）**: 起点が道路網から極端に遠い場合も最近傍Nodeへ黙ってスナップする
- ~~`RoutingService`へのORS固有パース漏れ（M2）~~: **解消済み（2026-08-15、改善計画T21）**。`properties.extras.surface`のパース自体を撤去した（路面評価が自前DB空間マッチへ統一されたため、ORS側のextra_infoが不要になった）
- **`WeatherService.get_conditions(at=...)`のhourly範囲外ガード未実装（L3）**: openrouteservice版（改善計画T247で既定はroad_graphへ切替済みだが、引き続き選択可能なエンジン）が使う経路で実使用時の既知制約として残る（20km/h想定の周回では実害はほぼ無い）
