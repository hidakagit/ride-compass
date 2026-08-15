# 静的道路属性の棚卸しと実装計画（調査報告・2026-08-15）

**ステータス（2026-08-16更新）: P0完了・P1主要部分完了**。P0（タグ保持基盤・
`domain/traffic.py`・MVT拡張v4・交通ストレス/自転車インフラレイヤー）・既存データへの
再取込・T9（surface列化）はいずれも完了済み（詳細は
[improvement-plan.md](improvement-plan.md)「静的道路属性 P0」節）。P1は
下記§3の1〜3のうち「node取込機構」「停止密度評価」を2026-08-16に実装完了（詳細は
本節末尾の実装結果を参照）。intersectionDensity・trafficStress/bicycle_infra評価組み込み・
自転車歩行者道スコープ拡張・`bicycle=no`Hard Constraint・name/refのMVT焼き込み（§3 P1の
4〜6、および2の後半）は未着手のまま残る。以下は元の調査報告（2026-08-15時点、着手前）。

新レイヤー（交通ストレス・自転車インフラ・信号密度等）追加に向けた、OSM静的道路属性の
棚卸しと実装方針の提案。動的データ（天気・風・降水）は対象外。

関連: [architecture.md](architecture.md) / [improvement-plan.md](improvement-plan.md)（T9/T11/T12が本計画と関係）

**着手前ゲート**: T16〜T19（ゲートADR・マイグレーション機構・ファサード削減・同期ペア検知テスト）は
2026-08-15完了済み。T9（surface列化）は当初「本計画のスキーマ変更・再取込に同梱」の
想定だったが、中核ルーティング評価ロジックに触れる別スコープのためP0実装時に切り離した
（improvement-plan.md参照）。

**カバレッジ実測（関東全域、2026-08-15）**: `backend/scripts/measure_tag_coverage.py`で
kanto-latest.osm.pbf（取込対象131万way）を実測。東京都心試算より全般に低い
（lanes 8.7%・maxspeed 6.2%・name 8.3%、都心試算の半分程度）。P0実装済みの
smoothness(0.1%)・cycleway系(各0.0〜0.6%)も低く、実データ投入後は表示が疎になる見込み。
width/shoulderは実測値（0.3%/0.0%）でP2据え置きを確定（§2.1参照）。

---

## 1. 現状調査の結果

### 1.1 調査項目への回答

| # | 項目 | 現状 |
|---|---|---|
| 1 | 地図ライブラリ | MapLibre GL JS v5（固定、Next.js App Router）。`MapView.tsx`が描画専任 |
| 2 | ベクタータイル取得 | 自前MVT `GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`（z12-15）。PostGIS `ST_AsMVT`が第一系統（`road_graph_repository.py: RoadSurfaceTileQuery`）、Overpass＋Pythonエンコードはフォールバック。Next.js rewritesで同一オリジン化、`tile_cache`（ファイル、世代v3）に永続化 |
| 3 | OSMデータ取得 | 第一系統: PBF取込バッチ（`app/batch/import_pbf.py`、pyosmium）→ PostGIS `osm_raw_ways`/`osm_raw_nodes`。取込対象は `import_profile.yaml` で宣言。フォールバック: `OverpassClient`（本番は無効） |
| 4 | 現在取得しているOSMタグ | **wayの `highway` / `surface` / `oneway`（→direction）の3つのみ**。他のタグは `osm_adapter.py: osm_way_to_way_spec` の変換時にすべて破棄され、DBにも残らない。**ノードのタグは一切取得していない**（`osm_raw_nodes`は座標のみ＝信号・横断歩道等は現状ゼロ） |
| 5 | 路面の内部モデル | `surface`生タグ → `domain/road.py: classify_osm_surface`（GOOD/BAD_OSM_SURFACE_TAGS が正準の単一ソース）→ 3値 `surface_good`。Edge単位では `surface_attributes` テーブル（`SurfaceAttribute`） |
| 6 | 道路セグメントの内部モデル | `WaySpec`（osm_way_id, node_ids, highway, surface, direction）→ `build_road_graph` で交差点分割 → `Node`/`DirectedEdge`（Edgeは`highway`生値のみ保持）。属性は `elevation_attributes`/`surface_attributes` に分離（Edge本体と属性データの分離が既に設計原則） |
| 7 | レイヤー管理 | `MapView.tsx` が全レイヤーを初期化時に常設し、以降はvisibility切替のみ。`runWhenStyleReady`ヘルパー等の落とし穴対策済み |
| 8 | レイヤーON/OFF | `MapOverlayControls.tsx` の独立チェックボックス（標高・路面・風）。路面は `roadFilterAxes.ts` の**汎用の軸定義**（surface軸=色、highway軸=太さ/線種）で絞り込み・凡例を生成。「軸を増やすときはタイルへプロパティを1つ足し、ROAD_FILTER_AXESへ軸定義を1つ足すだけ」と設計済み |
| 9 | ズーム制御 | 路面MVTは `ROAD_TILE_MIN_ZOOM=12`/`MAX=15`（domain/region.py）。ソースのminzoom/maxzoom＋API側400ガードの二重防御。ズーム不足時はヒント表示 |
| 10 | キャッシュ | ①タイル: `tile_cache.py`（ファイル、SHA-256フラット化、**パスに世代番号v3**。`regionApi.ts: ROAD_SURFACE_TILE_VERSION`と対）②標高: SQLite ③天候: TTL30分 ④取得済み管理: `road_graph_tiles`マーカー |
| 11 | バックエンド地理処理 | PostGIS（SRID4326、ST_AsMVT/ST_TileEnvelope/ST_Intersects）、shapely（WKB一括デコード）、NetworkX（Dijkstra） |
| 12 | PostGIS利用状況 | 本番Supabase＋dev機ネイティブPG18。テーブル: `osm_raw_ways`/`osm_raw_nodes`（生OSM層）、`road_nodes`/`road_edges`（派生グラフ）、`elevation_attributes`/`surface_attributes`、`road_graph_tiles`、`osm_import_runs` |
| 13 | ルート探索との接続点 | `EvaluationService.evaluate_graph` → `domain/evaluation.py: compute_edge_cost`（Edge単位。difficulty 0-100 → 距離乗算ペナルティ）。重みは `route_preference.yaml`。Hard Constraintは `is_edge_allowed`（DISALLOWED_HIGHWAY_TYPES）。**「交通・自転車インフラ・信号は未実装」と拡張ポイントがコード上に明記済み**（`RoutePreference` docstring） |

### 1.2 重要な発見

**アーキテクチャは既に要求どおりの流れを持っている。** 仕様書・実装とも

```
Raw OSM（osm_raw_ways: 生タグ） → Normalized（WaySpec/adapter） → 属性（*_attributes）
  → Derived（EdgeCost/difficulty） → 表示（MVT） / 評価（EvaluationService）
```

の分離が成立しており、「生データとスコアの分離」「表示用と探索用の分離」は新設計不要。

**最大のギャップは「タグが3つしか生き残らない」こと。** lanes / maxspeed / width / cycleway /
bicycle / access / smoothness / tunnel / bridge / name … は PBF→WaySpec 変換の時点で捨てられ、
DBに存在しない。ノードタグ（信号・横断歩道・一時停止・踏切）は取込対象ですらない。
したがって本計画の中心は評価ロジックではなく、**取込段階でのタグ保持の拡張＋再取込**である。

なお `import_profile.yaml` には既に「将来の拡張例」としてnode要素（amenity等）の
コメントアウト例と `target: osm_raw_pois` の想定があり、取込機構の拡張は設計上想定内。

---

## 2. 静的道路属性一覧（棚卸し）

凡例 — 有用性: ★1〜5 / 取得難易度: 易=タグ保持だけ・中=正規化/パース必要・難=リレーション/ネットワーク解析必要 /
判断: **採用**（P0-P1で実装）・**保留**（P2）・**不要**

### 2.1 way属性（線）

| 属性 | OSMタグ | 取得元 | 難易度 | データ量影響 | 有用性 | スコア化 | 表示価値 | 評価価値 | 判断 |
|---|---|---|---|---|---|---|---|---|---|
| 路面種別 | `surface=*` | way | 済 | 済 | ★★★★★ | surfaceScore | 済 | 済（3値） | **採用**（細分化） |
| 路面状態 | `smoothness=*` | way | 易 | 小 | ★★★★★ | smoothnessScore | 高 | 走行快適性 | **採用 P0** |
| 道路種別 | `highway=*` | way | 済 | 済 | ★★★★★ | trafficStress入力 | 済 | 済（Hard Constraint） | **採用**（済） |
| 車線数 | `lanes=*`（`lanes:forward/backward`は当面無視） | way | 中（intパース） | 小 | ★★★★☆ | trafficStress入力 | 中 | 交通ストレス | **採用 P0** |
| 制限速度 | `maxspeed=*` | way | 中（数値パース、日本はkm/h数値が主） | 小 | ★★★★☆ | trafficStress入力 | 中 | 交通ストレス | **採用 P0** |
| 一方通行 | `oneway=*` | way | 済（direction） | 済 | ★★★★☆ | — | 低 | 済（ルート制約） | **採用**（済。`oneway:bicycle`例外はP1） |
| 自転車道（車道上） | `cycleway=*`, `cycleway:left/right/both=*` | way | 中（left/right統合の正規化） | 小 | ★★★★★ | bicycleInfrastructureScore | 高 | 自転車走行環境・交通ストレス | **採用 P0** |
| 自転車通行可否 | `bicycle=*`（yes/no/designated/use_sidewalk/dismount） | way | 易 | 小 | ★★★★★ | インフラ分類・Hard Constraint | 高 | ルート制約 | **採用 P0** |
| 自動車通行制限 | `motor_vehicle=*`, `access=*` | way | 易 | 小 | ★★★★☆ | trafficStress補正（車が来ない道） | 中 | 交通ストレス・ルート制約 | **採用 P0** |
| 道路幅員 | `width=*`（`est_width`も） | way | 中（"3.5"/"3.5 m"表記ゆれ） | 小 | ★★★★☆（ただし日本のカバレッジ低） | trafficStress補正 | 中 | 交通ストレス | **保留 P2**（2026-08-15関東全域実測: 0.3%、評価に使えるレベルでないため見送り確定） |
| 路肩 | `shoulder=*` | way | 易 | 小 | ★★★★☆（カバレッジ極低の見込み） | trafficStress補正 | 低 | 安全性 | **保留 P2**（2026-08-15関東全域実測: 0.0%、見送り確定） |
| トンネル | `tunnel=yes` | way | 易 | 小 | ★★★☆☆ | 減点フラグ | 高（回避判断） | 安全性・快適性 | **採用 P0**（保持は軽い） |
| 橋・高架 | `bridge=yes`, `layer=*`, `embankment=yes` | way | 易 | 小 | ★★★☆☆ | 将来の風評価連携 | 中 | UI表示＋将来 | **採用 P0**（bridgeのみ。layer/embankmentはP2） |
| 歩行者共用 | `highway=path/footway` + `bicycle=yes/designated`（自転車歩行者道） | way | 中（**取込スコープ拡張が必要**、後述） | 中（行数増） | ★★★★☆ | インフラ分類（速度低下要因として区別） | 高 | 自転車走行環境 | **採用 P1** |
| 道路名称 | `name=*` | way | 易 | **中**（日本語文字列、平均数十バイト/way） | ★★☆☆☆ | — | UI・デバッグ | UI表示のみ | **採用 P1**（ポップアップ表示に有用） |
| 道路番号 | `ref=*` | way | 易 | 小 | ★★☆☆☆ | — | UI | UI表示のみ | **採用 P1** |
| 自転車推奨 | `bicycle=designated`, `bicycle_road=yes` | way | 易 | 小 | ★★★★☆ | インフラ分類に統合 | 高 | 自転車走行環境 | **採用 P0**（bicycleタグに含む） |
| サイクリングロード | relation `type=route, route=bicycle` | **relation** | **難**（relation取込は現行機構に無い） | 中 | ★★★★☆ | ボーナス評価 | 高 | 自転車走行環境 | **保留 P2**（大半は`highway=cycleway`のwayで拾える） |
| 最急勾配標識 | `incline=*` | way | 中 | 小 | ★★☆☆☆（DEMで代替可能） | — | 低 | 標高はDEM優先 | **不要**（既存標高系と重複） |
| 車線・道路の状態補助 | `tracktype=*`（track専用の締固め度） | way | 易 | 小 | ★★★☆☆ | surfaceScore補完（track且つsurface無しの推定材料にせず、表示のみ） | 中 | 補助 | **保留 P2** |

### 2.2 node属性（点）— 現状は取込機構ごと未実装

| 属性 | OSMタグ | 取得元 | 難易度 | データ量影響 | 有用性 | スコア化 | 表示価値 | 評価価値 | 判断 |
|---|---|---|---|---|---|---|---|---|---|
| 信号 | `highway=traffic_signals`（node） | node | 中（**node取込の新設**） | 小（点、都市部で数千/区程度） | ★★★★☆ | signalDensity | 高 | 停止・減速コスト | **採用 P1** |
| 横断歩道 | `highway=crossing`（node） | node | 中（同上） | 中（数が多い） | ★★★☆☆ | 密度補助 | 中 | 停止・減速コスト | **採用 P1**（信号と同じ機構に相乗り） |
| 一時停止 | `highway=stop`, `highway=give_way`（node） | node | 中（同上） | 小 | ★★★☆☆ | 密度補助 | 中 | 停止・減速コスト | **採用 P1** |
| 踏切 | `railway=level_crossing`（node） | node | 中（同上） | 小 | ★★★☆☆ | 減点フラグ | 高 | 停止・危険要因 | **採用 P1** |
| 交差点 | OSMネットワーク構造（タグ不要） | **既存road_nodes** | 易（**新規取得不要**。`build_road_graph`の分割結果＝次数3以上のNode） | なし | ★★★★☆ | intersectionDensity | 中 | 停止・減速コスト | **採用 P1** |

### 2.3 POI（道路属性とは別カテゴリ）

いずれも `import_profile.yaml` のnode要素＋`osm_raw_pois`（新テーブル）で同一機構により取込可能。
**道路属性とはテーブル・レイヤー・優先度を分けて扱う**。全てP2。

| POI | OSMタグ | 備考 |
|---|---|---|
| コンビニ | `shop=convenience` | 補給計画に有用。カバレッジ良好 |
| トイレ | `amenity=toilets` | カバレッジ良好 |
| 自販機 | `amenity=vending_machine`（+`vending=drinks`） | 数が多い。ズーム制限必須 |
| 駐輪場 | `amenity=bicycle_parking` | |
| 飲料水 | `amenity=drinking_water` | プロファイルのコメント例そのまま |
| 道の駅 | 単一の確立タグ無し（`highway=rest_area`等の併用が実態） | **タグ運用の実データ検証が必要**。推測で実装しない |
| サイクルステーション | 確立タグ無し（`amenity=bicycle_repair_station`は空気入れ等） | 同上 |

### 2.4 主要属性の判断基準（D項目）

**根拠のない推測はしない。タグが無い場合は raw=NULL のまま保持し、スコア計算時の
フォールバック規則（highway種別による既定値）だけを文書化して使う**（生データ汚染と評価規則を分離）。

- **smoothness** → smoothnessScore: excellent=100 / good=85 / intermediate=60 / bad=30 /
  very_bad=10 / horrible以下=0 / 未設定・未知=None（評価しない）
- **surface** → surfaceScore（現行3値の細分化）: asphalt=100 / concrete系=90 / chipseal=85 /
  paving_stones・bricks=70 / sett=40 / compacted・fine_gravel=30 / gravel=20 /
  cobblestone系=10 / dirt・ground・earth=10 / sand・mud・grass=5 / 未知=None。
  **順序付き語彙テーブルを `domain/road.py` に一元化し、既存の3値（GOOD/BAD）はそこから導出**する
  形にすれば正準1箇所の原則（T7）を維持できる
- **trafficStress**（LTS: Level of Traffic Stress風の1-4段階。「交通量」ではなく「推定交通ストレス」）:
  - 基本値（highwayのみで決定、全wayで必ず決まる）: cycleway=1 / living_street・residential=2（信号少・車少想定）/
    unclassified・track=2 / tertiary系=3 / secondary・primary系=4 / trunk系=4（表示のみ、探索は除外済み）
  - 補正（タグがある場合のみ適用。unknownは補正しない）: 分離自転車道（`cycleway*=track`）→−2 /
    自転車レーン（`cycleway*=lane`）→−1 / maxspeed≤30→−1 / maxspeed≥60→+1 / lanes≥4→+1 /
    `motor_vehicle=no`（自転車可）→1に固定。結果を1-4へクランプ
- **bicycleInfrastructureClass**（列挙。スコアはこの分類から導出）:
  `separated`（highway=cycleway / cycleway*=track）＞ `lane`（cycleway*=lane）＞
  `shared_busway等`（cycleway*=share_busway/shared_lane）＞ `shared_pedestrian`（path/footway＋bicycle可＝自転車歩行者道、速い巡航には不向き）＞
  `roadway`（共用車道）/ `prohibited`（bicycle=no）/ `unknown`
- **signalDensity / intersectionDensity**: 個数ではなく「個/km」。エッジ単位で保持しルートで距離加重集計

---

## 3. 優先順位

### P0（すぐ実装）— タグ保持基盤＋交通ストレス・自転車インフラレイヤー

1. **タグ保持基盤**: `osm_raw_ways` に許可リストでフィルタした生タグを保持（方式は§5）＋PBF再取込
2. **カバレッジ実測**: 取込前にPBFから対象タグの付与率を集計する小スクリプト
   （pyosmiumで数分。width/shoulder等のP1/P2判断の根拠にする）
3. **交通ストレスレイヤー**: highway＋lanes＋maxspeed＋cycleway＋motor_vehicle → trafficStress(1-4)を
   バックエンドで算出しMVTに焼き込み、フロントに軸追加
4. **自転車インフラレイヤー**: cycleway系＋bicycle → bicycleInfrastructureClassをMVTに焼き込み、軸追加
5. **smoothness表示軸**: 生タグをMVTに焼き込み、路面軸を補強
6. tunnel/bridgeフラグの保持とMVT焼き込み（表示のみ。評価はP1以降）

P0は**表示（レイヤー）まで**。ルート評価への組み込みは、レイヤーで実データの見え方・カバレッジを
確認してから行う（マップの見える化を先行させる現行方針とも一致）。

### P1（次に実装）— 点データとルート評価接続

1. node取込機構（`osm_raw_pois`テーブル＋プロファイルnode要素）: 信号・横断歩道・一時停止・踏切
   ✅**完了（2026-08-16）**
2. signalDensity ✅**完了（「停止密度」として実装、下記参照）** / intersectionDensity
   （交差点は既存`road_edges`から次数導出、新規取得不要）**未着手**（road_graphエンジンは
   グラフ全体をメモリに持つため容易だが、ORSエンジン側は経路サンプル点ごとに新規のDB空間
   問い合わせが要り実装規模が増えるため、ユーザー承認のうえ本ラウンドのスコープから分離）
3. `EvaluationService`への組み込み: `compute_edge_cost`に**停止密度**の項を追加✅完了。
   trafficStress・インフラの項追加は**未着手**（P0時点でway属性としては取得済みだが評価組み込みは
   別スコープとして分離）。`route_preference.yaml`に`stop_weight`追加✅完了、`RouteCandidate`への
   ルート単位集約値は`stop_density`として追加✅完了（`trafficStressScore`等は未着手）。
   **未着手のtrafficStress・intersectionDensity（＝下記P2）を評価組み込みする際の判断項目**
   （複雑度平衡レビュー第4回R-5）: stop_weight追加時は`route_preference.yaml`（区間難易度・
   Edge Cost、絶対評価）のみへ追加し、`scoring.yaml`（total_score＝おすすめ度、候補集合内の
   相対評価）へは追加しなかった（ユーザー承認済みのスコープ判断）。この結果、停止密度は
   区間の色分け・探索コストには効くが、候補の並び順（おすすめ度）には一切効かない非対称が
   生じている。trafficStress等の追加でも同じ判断が必要になるため、着手時のタスク定義へ
   「`scoring.yaml`側にも軸を追加するか」を明示的な検討項目として含めること（放置すると
   「評価には入れたが推薦には入れ忘れた」が既成事実化しやすいため、一連の軸追加ごとに
   都度判断する）
4. 自転車歩行者道の取込スコープ拡張（path/footway＋bicycle可のみ。プロファイルにエントリ追加）
   **未着手**
5. `bicycle=no`のHard Constraint追加、`oneway:bicycle`例外の解釈 **未着手**
6. name/refのMVT焼き込み（ポップアップ表示）、width（カバレッジ実測が良ければ） **未着手**

**実装結果（1〜3、2026-08-16）**: `osm_raw_pois`（`osm_node_id`/`kind`/`tags`/`geom`、GiST索引付き。
migration 0005）を新設し、`domain/traffic.py: classify_stop_poi`（highway=traffic_signals/
crossing/stop/give_way・railway=level_crossingの5種、踏切優先）で分類したnodeのみを保持する。
取込はPBFバッチのみ（`pbf_source.py`にpyosmium `node()`ハンドラを追加、`import_profile.yaml`に
node要素2ルール）。**ADR決定2（フォールバック撤去条件成立まで新属性はOverpass経路に実装しない）
に従い、Overpassフォールバック側（`get_ways_and_nodes`のnode tags取得）は無改修のまま**。
評価は`AttributeRepository.get_stop_poi_counts`（road_graphエンジン、`road_edges`との
`ST_DWithin`空間結合）／`get_nearest_stop_poi_counts`（ORSエンジン、`get_nearest_surface_tags`と
同じサンプル点空間マッチ）で導出し、`domain/difficulty.py: stop_difficulty`（区分線形、暫定値）・
`domain/traffic.py: distance_weighted_stop_density`（合計count÷合計distance_kmの単純比）を経て
両エンジンのEdge Cost・区間難易度・`RouteCandidate.stop_density`に反映する。「データ未取得
（repository未注入）」と「実測0件」をNone/0で区別する設計（road_score等の既存方針を踏襲）。
backend 531件・frontend 146件・eslint・tsc全green、dev機PGへmigration適用・
Tokyo.osm.pbfでのdry-run実行（信号等81,921件マッチ）で実データ動作確認済み。

### P2（将来検討）

- POIレイヤー（コンビニ・トイレ・自販機・駐輪場・飲料水。道の駅はタグ運用の検証後）
- サイクリングロードのrelation取込（`type=route, route=bicycle`）
- shoulder / tracktype / layer・embankment、トンネル・橋と風評価の連携
- スコアの本格チューニング（0-100スケール統一、実走フィードバック反映）

---

## 4. 推奨データモデル（既存を壊さない差分）

設計原則: **生タグ（raw）と派生値（derived）を別の場所に持つ。DirectedEdge・既存APIは変えない。**

```
[取込層]  osm_raw_ways
  + tags jsonb NOT NULL DEFAULT '{}'   ← 許可リスト（下記）でフィルタ済みの生タグのみ
    許可リスト例: smoothness, lanes, maxspeed, width, cycleway, cycleway:left,
    cycleway:right, cycleway:both, bicycle, motor_vehicle, access, oneway:bicycle,
    tunnel, bridge, name, ref, tracktype, shoulder
  ※ highway/surface/direction の既存列はそのまま（正準アクセス経路を変えない）

[取込層]  osm_raw_pois（新テーブル、P1）
  osm_node_id BIGINT PK / kind TEXT（traffic_signals|crossing|stop|give_way|level_crossing|…）
  / tags jsonb / geom POINT / updated_at

[正規化層]  WaySpec（domain/graph.py）
  + tags: dict[str, str] = {}   ← adapterが許可リストを適用して受け渡し。
    build_road_graph は今までどおりタグを解釈しない（DirectedEdgeへは持たせない）

[派生層]  domain/traffic.py（新規・純関数群。すべてunknown安全）
  parse_lanes(tags) -> int | None
  parse_maxspeed(tags) -> int | None
  classify_bicycle_infrastructure(tags, highway) -> BicycleInfraClass
  traffic_stress_level(highway, tags) -> int(1-4) | None
  smoothness_score(tags) -> float | None
  ※ 判定基準は§2.4。正準定義はここ1箇所（road.pyのタグ集合と同じ運用、T7原則）

[評価層]  domain/evaluation.py（P1）
  RoutePreference に traffic_weight / infra_weight / stop_weight を追加
  compute_edge_cost の composite_difficulty に項を追加（欠損時は再正規化、既存方式のまま）
  属性の供給は surface と同じ「osm_way_id 経由で raw から導出」
  （T9の「surface_attributesの導出化」と同じ方向。新attributeテーブルは増やさない）
```

`RouteSegmentDetail` / `RouteCandidate` への追加（P1）: `traffic_stress`(1-4|null),
`bicycle_infra`(列挙|null), ルート集約の `traffic_stress_score` / `signal_density` 等。
いずれもnull許容の追加のみで後方互換（OpenAPI生成→フロント型は自動追従、T4の仕組みに乗る）。

---

## 5. データ取得方式

### 5.1 表示: 既存MVTパイプラインの拡張のみ（クライアント計算なし）

```
PBF取込（tags jsonb保持）
  → PostGIS osm_raw_ways
  → ST_AsMVT（SQLにプロパティ追加: smoothness, lanes, maxspeed,
     bicycle_infra, traffic_stress, tunnel, bridge…）
  → tile_cache（世代 v3→v4 に更新。regionApi.ts の ROAD_SURFACE_TILE_VERSION も対で更新）
  → MapLibre（roadFilterAxes.ts に軸を追加。UIは汎用ループのため RoadFilterDialog 側は無変更）
```

- 生タグ系（smoothness等）はSQLで `lower(btrim(tags->>'smoothness'))` を焼くだけ
- **trafficStress / bicycleInfraのような複合分類はMapLibreのmatch式では表現しきれないため、
  バックエンドで分類済みの値をプロパティとして焼き込む**（`surface_good`と同じ流儀）。
  多タグの複合判定をSQLに二重実装しないため、分類はPython正準関数で行い
  「分類結果の対応表（タグ組合せ→分類値）」をバインドするか、フォールバック系と同様に
  SQL側へ最小限のCASEで写像し**正準テストで突き合わせる**（GOOD_TAGSバインドと同じ考え方。
  実装時にどちらが単純か比較して決める）
- ST_AsMVTはNULLプロパティをキーごと省略するため、**カバレッジの低いタグはタイルサイズを
  ほとんど増やさない**。増分は主にhighway由来のtraffic_stress（全way）とname

### 5.2 評価: バックエンドで評価時導出（事前計算テーブルは増やさない）

- Edge Costは現在も呼び出し時計算（`EdgeCostResult`は恒久保存しない仕様）。traffic系も同じく
  `osm_way_id → osm_raw_ways.tags` から評価時に導出する。T9（surface_attributes廃止・導出化）と
  同じ方向であり、再取込のタイミングでT9を同時に進めると重複作業がない
- signalDensity（P1）: エッジへの信号対応付けは `osm_raw_pois.osm_node_id` と
  `osm_raw_ways.node_ids` の突合せ（GINを廃止した経緯があるため、実装時は
  ST_DWithinの空間結合と性能比較して選ぶ）。ルート単位は距離加重で集約
- intersectionDensity（P1）: `road_edges` のfrom/to次数から導出。新規データ取得なし

### 5.3 新規導入物

**新ライブラリ・新DB・新外部サービスは不要。** 使うのはすべて既存物
（pyosmium・PostGIS jsonb・ST_AsMVT・roadFilterAxesの軸機構・OpenAPI型生成）。

必要な運用作業は **PBF再取込（バッチ再実行）** のみ。データ容量への影響:

- `tags jsonb`（許可リスト限定）: 行数不変・1行あたり数十〜200バイト増の見込み。
  日本のOSMは対象タグのカバレッジが低い（residentialの大半はlanes/maxspeed無し）ため
  上振れしにくいが、**Supabase無料枠の制約があるため取込前にdry-runで実測すること**
  （node_idsのGIN廃止で28MB稼いだ経緯あり。nameタグが最大の増分要因なので、
  容量が厳しければnameだけ許可リストから外してP1へ回す）
- 信号等のnode（P1）: 点データで軽量（都市部でも数万行オーダー）
- MVTサイズ: プロパティ追加で1タイルあたり+30〜60%程度を見込む（要実測）。z12-15の
  範囲限定・ファイルキャッシュ済みのため実害は小さい想定

---

## 6. 最小変更案（P0の具体ステップ）

既存アーキテクチャの拡張ポイントに沿った、各層1変更の積み上げ。

1. **カバレッジ実測スクリプト**（`backend/scripts/`、pyosmium読み）
   — 対象タグ付与率を出力。P0採用属性の最終確認とP1/P2判断の根拠
2. **`import_profile.yaml`**: `keep_tags`（許可リスト）セクションを追加
3. **取込バッチ**: `build_way_record`/`_MERGE_WAYS_SQL`/ステージング表に `tags` 列を追加、
   `osm_adapter.py` で許可リスト適用（`WaySpec.tags`）。Alembic等は未導入のため
   既存慣行に合わせたDDL適用（`ALTER TABLE osm_raw_ways ADD COLUMN tags jsonb NOT NULL DEFAULT '{}'`）
4. **再取込実行**（既存バッチ、ユーザー作業。`osm_import_runs.profile_hash`が世代を記録）
5. **`domain/traffic.py` 新規**: §4の純関数群＋単体テスト（unknown安全性を重点検証）
6. **MVT SQL拡張**（`RoadSurfaceTileQuery`）: プロパティ追加。タイル世代 v4 へ
   （`region_service.py: _tile_cache_path` と `regionApi.ts: ROAD_SURFACE_TILE_VERSION` を対で更新）
7. **フロント**: `roadFilterAxes.ts` に「交通ストレス」「自転車インフラ」「路面状態(smoothness)」軸を追加
   （凡例・絞り込みは既存の汎用機構が処理。surface-tags.json方式の整合テストを踏襲）
8. **ログ**: 取込・MVT生成の追加属性は既存の `log_external_call`/1行INFOサマリ方針に従う

Overpassフォールバック経路（`get_ways_and_nodes`は元々全タグを返している）も
adapterの許可リスト適用だけで同じ動きになる。

## 7. UI方針（レイヤー追加の受け皿。2026-08-15 実装済み）

P0のレイヤー追加に先行して、レイヤー操作UIを「地図上=ON/OFFチップ＋適用中条件の1行サマリ、
細かな設定=サイドバー集約」へ再構成した（詳細は[architecture.md](architecture.md)の
「UI再構成（第2段）」参照）。

- レイヤーカタログ `frontend/src/components/Map/mapLayers.ts`（id/label/kind/description）が
  チップ行・サイドバーのセクション枠の単一ソース。**kind=static（地域固定）/dynamic（時間・
  ルートで変わる）** でグループ分けし、静的データと動的データを混同しない方針をUIにも反映
- P0の新レイヤー（交通ストレス・自転車インフラ等）の追加手順:
  ①カタログに1エントリ ②`page.tsx`に表示状態の初期値とサマリ対応 ③`MapLayersPanel`に
  セクション中身（凡例・絞り込み軸） ④`MapView.tsx`にソース/レイヤー登録。
  チップ・条件サマリ・スクロール誘導は汎用機構が処理するため個別実装は不要
- 条件サマリは`legendFilter.ts: summarizeLegendFilters`（凡例定義のみに依存）が自動生成。
  将来の動的レイヤー（天候等）もkind=dynamicでカタログに足せば同じ枠組みに乗る
- 路面の絞り込み編集は「下書き→適用」方式を維持（即時反映だと複数条件の組み合わせ編集が
  しづらいという過去のフィードバックによる）

### 実装しない・やらないこと（本計画の範囲外）

- OSMに無い属性の推測補完（unknownはunknownのまま）
- クライアント側での属性計算・スコア計算
- relation取込機構（P2まで持たない）
- ルーティングエンジン自体の変更（EvaluationServiceの項追加のみで、探索は既存Dijkstraのまま）
