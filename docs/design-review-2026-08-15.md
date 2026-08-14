# 全体設計レビュー（2026-08-15）

大規模変更（OSM PBF取込・PostGIS化・路面フィルタ再構成ほか、init以降の全35コミット）後に実施した、
コードベース全体の設計レビューの記録。改善の実行計画は [improvement-plan.md](improvement-plan.md) を参照。

レビュー方法: backend全モジュール・frontend全コンポーネント・docs・git履歴を通読し、
「複数の変更を横断した結果として発生した設計上の不整合」を重点的に調査した。

---

## A. 総合評価（5段階）

| 観点 | 評価 | 要点 |
|---|:-:|---|
| Architecture | 4 | 戦略/エンジンのポート分割、生/派生データ分離は模範的。Repositoryの肥大が減点 |
| Design consistency | 3 | 正準定義の努力はあるが、語彙・符号の不整合がAPI境界を越えて漏れている |
| Maintainability | 3 | コメント・docsは充実。手動同期ペアの多さと882行の時系列ドキュメントが負債 |
| Extensibility | 4 | 属性追加・軸追加が「定義を1つ足すだけ」になる構造が両端に揃っている |
| Performance | 3 | 実測駆動の最適化は優秀。Road Graphの全量ロード設計は関東スケールで不成立 |
| Testability | 4 | 50ファイル超・性能回帰テストまである。CIが無いことだけが致命的 |
| Data model | 3 | surface_attributesの重複保持、標高キャッシュ2系統など導出データの整理余地 |
| API design | 4 | `engine`フィールド、難易度の事前計算返却など境界判断が的確 |
| Frontend/Backend separation | 4 | 閾値ロジックをbackendに寄せる方針が徹底。型の手動二重管理が減点 |
| Production readiness | 3 | ログ・レート制限・デプロイ確認は整備済み。CI無し・認証無し・単一プロセス前提 |

---

## B. Critical Issues（今すぐ直すべき）

### B1. `gradient_percent` の符号の意味がエンジン間で食い違い、既定エンジンで勾配表示が壊れている

- **問題**: `openrouteservice_engine.py`（`_build_segment_details`）は `gradient_percent = abs(e2 - e1) / ...` と**絶対値**を返す。
  一方 `RoadGraphEngine` は `domain/attributes.py` の `average_grade`（**符号付き**、登り=正/下り=負）をそのまま返す。
- **なぜ問題か**: フロントの勾配色分けモード（`routeStyleModes.ts`）は「下り（<-2%）＝青」という符号付き前提の
  カテゴリを持つ。既定エンジンは openrouteservice のため、**「下り」カテゴリは絶対に表示されず、下り坂が
  上り系の警告色で描画される**。docs は wind_score の意味差は明記しているが gradient の符号差は未文書化（監査漏れ）。
- **影響**: 地図の勾配レイヤーの表示品質（ユーザー可視）、エンジン比較の妥当性。
- **修正方針**: ORSエンジン側を `(e2 - e1)`（符号付き）へ変更。`gradient_difficulty` は内部で `abs()` を取るため
  難易度計算への影響なし。`RouteSegmentDetail.gradient_percent` の正準定義（符号付き・進行方向基準）を
  `domain/route.py` に明記する。

### B2. CI/CD が存在しない

- **問題**: `.github/` が無く、backend 50テストファイル・frontend テスト・lint がローカル手動実行のみ。
- **なぜ問題か**: 「Claude Codeで大規模変更を繰り返す」開発スタイルにおいて、テスト実行が人間の習慣に依存する
  状態では回帰を検出できない。
- **修正方針**: GitHub Actions で pytest（PostGIS統合テストは接続不可時skip設計のためそのまま動く）＋
  vitest ＋ eslint ＋ `tsc --noEmit` を PR/push で回す。後続の全リファクタリングの安全網として最優先。

### B3. `page.tsx` の `roadHiddenKeysByMode` が毎レンダー新規オブジェクトになる

- **問題**: `Object.fromEntries(...)` を毎レンダー実行し参照が毎回変わるため、`MapView` のエフェクト依存が
  無関係な再レンダー（天候取得等）のたびに発火し `map.setFilter` が走る。
- **なぜ問題か**: すぐ上の `NO_HIDDEN_LEGEND_KEYS`（参照固定でエフェクト発火を防ぐ工夫）が自身のコードで
  無効化されている。局所的にはどちらも正しいが組み合わせで壊れている典型例。
- **修正方針**: `useMemo(() => Object.fromEntries(...), [hiddenLegendKeysByMode])` で包む（1行）。

---

## C. Architectural Issues

### C1. `RoadGraphRepository` が5責務を持つ738行の単一クラス

生OSM層／派生グラフ（road_edges/nodes）／標高・路面属性／タイル取得マーカー／**表示用MVT生成**を1クラスで担う。
変更理由が異なる責務の同居であり、表示系（RegionService）がルーティング系Repositoryへ依存する層のねじれの原因。
→ `RawOsmRepository`（生データ+タイルマーカー）/ `RoadGraphRepository`（派生グラフ）/ `AttributeRepository` /
`RoadSurfaceTileQuery`（表示用）へ分割。同一セッション共有で挙動は不変。

### C2. トランザクション境界が Repository 内部にある

`save_graph` / `save_raw_ways` / `mark_tile_cached` 等が各メソッド内で `session.commit()` する。
呼び出し側が複数操作を1トランザクションに束ねられず、「生データ保存→タイルマーク」の安全性が
暗黙の呼び出し順規約に依存している。→ commit をサービス層（またはUnit of Work）へ移す。
移行完了までは「commitするメソッド」を repository docstring 冒頭に列挙する。

### C3. Road Graphエンジンの「リクエスト毎に全bboxグラフをメモリ構築」は関東スケールで不成立

`prepare` は都心4km相当bboxで Edge 15万件・decode 3.8秒（benchmarks実測）をリクエストのたびに
DB→Python→NetworkX へ全量ロードする。30km指定なら bbox は半径14km超で10倍規模。
既定エンジンが openrouteservice のため実害は未顕在。自前ルーティング本格化の**前に**
(a) pgRouting等のDB側探索 (b) プロセス内グラフキャッシュ (c) 事前縮約、の設計判断（ADR）が必要。
今すぐの実装は不要。

### C4. `surface_attributes` テーブルは `osm_raw_ways.surface` の Edge 単位コピー

`build_surface_attributes` は Wayタグを全Edgeへ複製するだけで独自情報を持たない（confidence常にNone）。
毎リクエスト15万行（Supabase WAN実測 8〜11秒）を転送し、容量予算300MBも圧迫。
`road_edges.highway` はEdgeに直接持つのに surface だけ別テーブルという非対称。
→ surface は `road_edges` 列に持たせるか JOIN で導出。`surface_attributes` は複数ソース突合で
confidence が必要になった時に再導入すればよい。

### C5. DIが両エンジンの依存を毎リクエスト構築する（`get_route_generator`）

コメントで自覚済み・オブジェクト構築は軽量なので現状許容。エンジン選択は起動時に確定する値のため、
lifespan でエンジンごとの依存ツリーを1回だけ組む形が素直（P3〜P4）。

---

## D. Maintainability Issues

- **D1. `api/routes.py` がレート制限ポリシー・DI工場・全エンドポイントの三役（400行）**。
  上限値7定数がコード埋め込みで `.env` 調整不可。→ ルータ分割＋`Settings` 化。
- **D2. 手動同期ペアが5組以上**:
  `ROAD_TILE_MIN/MAX_ZOOM`（region.py ↔ regionApi.ts）、タイル世代v2（region_service.py ↔ regionApi.ts）、
  MVTレイヤー名（vector_tile.py ↔ MapView.tsx）、**APIレスポンス型全体**（domain/route.py ↔ types/route.ts）。
  B1の符号不整合はこの手動同期の隙間で発生した。→ OpenAPI から `openapi-typescript` で型生成。
- **D3. `docs/architecture.md`（882行）が時系列日記**。現在の姿を知るには全履歴を読む必要があり、
  Claude Code のコンテキストコストに直結。→「現状仕様（常に最新）」と「決定記録（ADR、追記専用）」に分離。
- **D4. 小粒**: `repository=None` 引数が無型（3サービス）／`ASSUMED_SPEED_KMH` が wind_service.py と
  road_graph_engine.py に重複（同じ変更理由=ユーザー設定化を持つため統一対象）。
  ※ `MAX_CONCURRENT_REQUESTS` 群は各サービスの独立チューニング値のため共通化**しない**のが正しい。

---

## E. Performance Issues

- **E1**. Road Graph全量ロード（C3参照。将来スケールで最大の問題）
- **E2**. `get_surface_attributes` の毎リクエスト15万行転送（C4参照。WARM 8〜11秒の主成分）
- **E3**. GSI標高の1地点1リクエスト → DEMタイルのグリッド補間化（docsに将来課題として明記済み）
- **E4**. `segments` ペイロード肥大（road_graph時 数千区間×8候補。レビュー指摘M3・未対応）→ API境界で約500m単位のビン化
- **E5**. `ElevationAttributeService` のrepositoryロック直列化（軽微。候補ごとにセッションを分ける方が素直）
- 良い点: タイルDB往復1回化・`=ANY(配列)`・バルクUPSERT・`asyncio.to_thread` の使い分け等、
  実測に基づく最適化が benchmarks/ に記録付きで蓄積されている。

---

## F. Consistency Issues（最重点）

### F1. 路面の語彙が3系統あり、地図の色とルート評価が同じ道で食い違う

正準は `domain/road.py` の3値分類で、SQL側も同じ定数をバインドしており模範的。
しかしフロント `roadFilterAxes.ts` の `SURFACE_GROUPS` は独立した第3の分類:
- `chipseal`: フロントは「アスファルト（緑）」、backend正準では**不明** → タイルは緑なのに評価・ポップアップは「不明」
- `paving_stones`: backend正準で**good**、フロントは「石畳・敷石（紫）」

表示グルーピングと評価分類が別軸なのは許容できるが、タグ集合レベルの食い違い（chipseal）は単なるドリフト。
→ フロントのグループ定義をbackendのタグ集合から生成するか、和集合一致を検証するテストを置く。

### F2. 「システムが扱う道路種別の集合」が3箇所で独立定義

1. `import_profile.yaml`（取込対象。footway/service/steps/path等を除外、**trunkは含む**）
2. `evaluation.py` `DISALLOWED_HIGHWAY_TYPES`（**trunkは通行不可**）
3. `roadFilterAxes.ts` `HIGHWAY_GROUPS`（footway/pedestrian/steps等の凡例カテゴリを**持つ**）

結果: (a) 取込コメント「自転車で通行しうる種別のみ」とtrunk通行不可の矛盾（表示用取込なら正しいがコメントが実態とずれ）、
(b) 本番タイルにfootway等が存在しないのに凡例には列挙され、Overpassフォールバック有無で凡例の意味が変わる、
(c) 取込種別の増減時に3箇所の整合を人間が覚えている必要がある。
→ 目的が違うので統一定数にはせず、backendにhighway種別マスタを1ファイル置き、
取込・ルーティング可否・表示の3者の関係を docs の1つの表で明文化する。

### F3. 標高データのキャッシュが2系統

点単位SQLite（cache_db.py）とEdge単位PostGIS（elevation_attributes）。`ElevationClient` 共有により
二重取得は防げているが、「標高キャッシュはどこか」の答えが2つある。DEMタイル化の際に1系統へ。

### F4. 意図的な差異（問題なし・維持すべき手本）

`wind_score` のエンジン間の意味差は、docs明記＋レスポンス`engine`フィールド＋型コメントまで揃った
「意図的不整合の管理」の模範。B1（gradient）もこの水準に揃えるべき。

---

## G. Dead Code / Legacy

| 対象 | 状態 | 提案 |
|---|---|---|
| `database.py` `get_session` | 未使用（docstringに自認あり） | 削除 |
| `graph_service.py` `build_graph_for_bbox` | アプリ内の呼び出しなし（scripts/tests用） | scripts専用と明記 or 削除 |
| `RoutingService` | 実質1メソッドのpass-through＋ORS固有パース混在（docs M2自認） | ORSClientへ統合 |
| `/api/routes/preview` | Step3残置（意図的） | docsの「暫定」表記を実態に合わせる or 削除 |
| `vector_tile.py` PythonMVTエンコーダ | 本番ではほぼ空タイル生成専用 | 意図的併存（ユーザー指示）のため維持。フォールバック撤去時に丸ごと消せることを記録 |
| `RouteSegment.surface_summary/values` | ORS生形式がフロント型まで露出、フロント未使用 | 少なくとも types/route.ts から削除 |
| `ElevationService` vs `compute_elevation_attribute` | 約15行の計算重複（意図的・文書化済み） | 現状維持で可。B1修正時に片寄せ再検討 |

openrouteservice/road_graph の二本立ては設定切替型の意図的併存であり、ポート分割により重複が
戦略層から排除済み。レガシー併存の管理としては良い状態。

---

## H. Good Design（維持すべきもの）

1. **`RouteGenerator` / `LoopRoutingEngine` のポート分割**: 周回戦略が単一実装、評価を距離フィルタ後に
   分離する契約をエンジン非依存で保証。性能回帰テスト（評価がフィルタ通過候補だけ）まで整備。
2. **`WaySpec` によるOSM Adapter境界**: OverpassランタイムとPBFバッチが同じAdapterを通り、タグ解釈が構造的に一致。
3. **生データ（osm_raw_*）と派生データ（road_edges）の分離＋`split_at`鮮度判定**: タイル境界依存の
   分割不一致問題への原理的に正しい解法。
4. **決定論的ID採番**（`osm-node-<id>` / `way-<id>-seg<n>-fwd`）: 冪等UPSERTの基盤。
5. **ログ基盤**: docs/logging.md＋`log_external_call`＋リクエストID自動付与＋`/api/debug/stats`。
6. **正準定義をSQLへバインドする手法**: 路面3値分類の二重定義を回避。F1のフロント側にも延長すべき。
7. **フロントの宣言的な軸/モード定義**: 「軸を増やす＝タイルにプロパティ1つ＋軸定義1つ」。
   道路属性が増えても既存コードを大量修正しない構造が両端で揃っている。
8. **benchmarks/**: 最適化判断がすべて実測値付きで残る文化。

---

## 今後の設計原則（Claude Codeでの開発ルール）

1. **概念の正準定義はbackend domain層に1箇所。** 他所（SQL・フロント）はバインド・生成・検証テストで追従させ、手書きコピーを作らない。
2. **同名フィールドの意味をエンジン間・境界間で変えない。** やむを得ない場合はwind_score方式（docs明記＋識別フィールド＋両側の型コメント）を必須とする。
3. **手動同期ペアを新設するときは、両側に相互参照コメント＋ズレ検知テストをセットで置く。**
4. **トランザクション境界はサービス層。** Repositoryはcommitしない（移行完了までは「commitするメソッド」をdocstring冒頭に列挙）。
5. **生データと派生データを分ける。派生は常に再生成可能に保ち、導出できるものをテーブルに実体化しない**（実測で必要と示された場合のみ例外）。
6. **新しい道路属性は5点セット（生値→Edge紐付け→評価関数→タイルプロパティ→軸/モード定義）の経路でのみ追加する。** DirectedEdge本体には持たせない。
7. **性能の主張はbenchmarks/の実測とセットで行う。**
8. **「関東全域で成立するか」を、全量ロード・全件転送を伴う設計判断の必須チェック項目にする。**
9. **既存機能に触る変更は「並行追加→設定で切替→旧削除」の3段階で行い、旧実装には削除条件（いつ消せるか）を必ず書き残す。**
10. **docsは「現状」と「経緯」を分け、現状文書はコード変更と同一コミットで更新する。**
