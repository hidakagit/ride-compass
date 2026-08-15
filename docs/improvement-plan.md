# 改善実行計画（2026-08-15 設計レビュー対応）

[design-review-2026-08-15.md](design-review-2026-08-15.md) の指摘に対する実行計画。
同日の第2回レビュー（[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md)、複雑度平衡の観点）
の対応タスク（T16〜T22）は後半の「第2回レビュー対応」節にある。
**進捗はこのファイルのチェックボックスを更新して管理する**（完了時に `[x]`＋完了日を追記）。

## 進め方の原則

- **順序の根拠**: 「検証の自動化（Phase 1）→ 境界の固定（Phase 2）→ 内部の再配置（Phase 2後半）→
  スケール準備（Phase 3）」の順にすると、各修正が前の成果を安全網として使え、後続の修正量が最小になる。
- 1タスク=1コミット（またはPR）。着手前後で全テストgreenを確認する。
- 挙動を変えるタスクはテストを先に追加/更新してから実装する。
- docs（architecture.md等の「現状」記述）はコード変更と同一コミットで更新する。
- 規模目安: S=1時間以内 / M=半日 / L=1日以上

---

## Phase 1: 安全網と即修正（今すぐ）

### - [x] T1. CI導入（GitHub Actions）〔B2〕規模M・最優先（2026-08-15完了）

- `.github/workflows/ci.yml` を新規作成。トリガー: push / pull_request。
- ジョブ構成:
  - backend: `pip install -r requirements.txt` → `pytest`（`backend/` で実行。
    PostGIS統合テストは conftest.py が接続不可時にskipする設計のため、DBサービス無しでそのまま動く）
  - frontend: `npm ci` → `npx vitest run` → `npx eslint .` → `npx tsc --noEmit`
- 完了条件: masterへのpushでbackend/frontend両ジョブが自動実行され、現状の全テストがgreen。
- 備考: 後続T2以降はすべてこのCIを安全網として進める。将来的にPostGISサービスコンテナを
  足して統合テストも回す拡張余地あり（今回は必須にしない）。

### - [x] T2. `gradient_percent` の符号統一〔B1〕規模S（2026-08-15完了）

1. `backend/tests/test_openrouteservice_engine.py` に「下り区間で負のgradient_percentが返る」検証を追加（先にredを確認）。
2. `backend/app/services/openrouteservice_engine.py` `_build_segment_details` の
   `gradient_percent = abs(e2 - e1) / ...` から `abs` を除去し符号付き（`(e2 - e1)`、進行方向基準）へ。
3. `backend/app/domain/route.py` `RouteSegmentDetail.gradient_percent` に正準定義
   「符号付き・進行方向基準（登り=正/下り=負）。両エンジン共通」をdocstringで明記。
4. `docs/architecture.md` の評価値定義の統一（レビュー指摘H2）の節へ、gradientも統一済みである旨を追記。
- 完了条件: 既定エンジン（openrouteservice）でフロントの勾配モードに「下り（青）」が出うる状態。
  `gradient_difficulty` は内部で `abs()` を取るため難易度・total_scoreに影響が無いことをテストで確認。

### - [x] T3. `page.tsx` の `roadHiddenKeysByMode` をuseMemo化〔B3〕規模S（2026-08-15完了）

- `frontend/src/app/page.tsx` の `Object.fromEntries(...)` を
  `useMemo(..., [hiddenLegendKeysByMode])` で包み、参照を安定化。
- 完了条件: 無関係な再レンダー（天候取得等）でMapViewの路面フィルタ用エフェクトが発火しないこと
  （`MapView` のprops参照同一性を検証するテスト、または手動でReact DevTools確認＋コメント記録）。

---

## Phase 2: 境界の固定と内部再配置（次の大規模変更前）

### - [x] T4. OpenAPIからのフロント型生成〔D2〕規模M（2026-08-15完了）

- backend: `python -c "..."` または起動中サーバーから `openapi.json` を出力するnpm/justスクリプトを用意。
- frontend: `openapi-typescript` を導入し、`src/types/generated/api.d.ts` を生成。
  `types/route.ts` / `types/weather.ts` は生成型の再エクスポート（または削除して直接参照）へ置換。
- CIに「生成物が最新か」のドリフト検知ステップを追加（生成→`git diff --exit-code`）。
- あわせて `RouteSegment.surface_summary/surface_values` のフロント露出を整理（G表参照。
  previewレスポンスから外すか、生成型に含まれても未使用であることを明記）。
- 完了条件: domain/route.py の変更がフロント型へ自動反映され、手動同期が不要になる。

### - [x] T5. `api/routes.py` のルータ分割＋レート制限値のSettings化〔D1〕規模M（2026-08-15完了）

- `app/api/` を `routers/health.py` / `routers/routes.py`（generate/preview）/ `routers/weather.py` /
  `routers/region.py` / `routers/basemap.py` と `dependencies.py`（DI工場）へ分割。
- `GENERATE_RATE_LIMIT_PER_MINUTE` 等7定数を `config.py` の `Settings`（`.env` 上書き可）へ移動。
  既定値は現行値を維持。
- 完了条件: 既存APIテストが無変更でgreen（URL・挙動不変）。`.env` でレート上限を変更できる。

### - [x] T6. Repositoryの責務分割＋トランザクション境界の規約化〔C1/C2〕規模L（2026-08-15完了）

- 第1段（規約化・小）: `road_graph_repository.py` docstring冒頭に「commitするメソッド一覧」と
  呼び出し順の安全性根拠（生データ保存→タイルマークの順序が持つ意味）を明文化。
- 第2段（分割）: `RawOsmRepository`（osm_raw_*+road_graph_tiles）/ `RoadGraphRepository`（road_nodes/edges）/
  `AttributeRepository`（elevation/surface_attributes）/ `RoadSurfaceTileQuery`（MVT生成）へ分割。
  同一 `AsyncSession` を共有し、commit は呼び出し側（GraphService等）へ移す。
- 完了条件: 既存の統合テスト・Fakeリポジトリのテストが（Fakeの分割追従を除き）green。
  「Repositoryはcommitしない」が全リポジトリで成立。
- 備考: T5の後に行う（DI工場が整理されていた方が配線変更が小さい）。

### - [x] T7. 路面・道路種別語彙の整合〔F1/F2〕規模M（2026-08-15完了）

- 路面（F1）:
  - `chipseal` の扱いを決める（推奨: backend `GOOD_OSM_SURFACE_TAGS` へ追加。舗装として妥当なタグのため）。
  - フロント `SURFACE_GROUPS` の全タグ集合と backend `GOOD/BAD_OSM_SURFACE_TAGS` の対応を検証する
    テストをどちらかの側に追加（例: frontendテストでbackendのタグ集合をフィクスチャとして保持し、
    片方を変えたらテストが割れる形にする）。
  - `paving_stones` の色分け（石畳グループ）は表示上の判断として維持してよいが、
    評価（good）との関係をroadFilterAxes.tsのコメントに明記。
- 道路種別（F2）:
  - `import_profile.yaml` のコメント「自転車で通行しうる種別のみ取込」を実態
    （trunkは表示用に取り込むがルーティングでは通行不可）に合わせて修正。
  - `docs/architecture.md`（またはT8後の現状文書）に「取込スコープ／ルーティング可否／表示グルーピング」
    3者の関係を1つの表で明文化。
  - フロント凡例のうち本番取込に存在しない種別（footway/pedestrian/steps等）の扱いを決める
    （凡例注記を足す or 取込プロファイルに合わせて整理）。
- 完了条件: 同一タグの扱いがbackend評価とフロント表示で矛盾しない（テストで担保）。

### - [x] T8. architecture.md の「現状」と「経緯」分離〔D3〕規模M（2026-08-15完了）

- `docs/architecture.md` → 現状仕様のみの `docs/architecture.md`（大幅スリム化）と、
  経緯・決定記録の `docs/decisions/`（ADR形式、既存の時系列記述をほぼそのまま移設）へ分割。
- CLAUDE.md の参照先・docs/osm-pbf-import.md 等からのリンクを更新。
- 完了条件: 「現在の構成・API・データフロー」が経緯を読まずに把握できる。履歴情報は失われない。

---

## Phase 3: 機能追加と合わせて（トリガー条件付き）

### - [ ] T9. `surface_attributes` の導出化〔C4/E2〕規模M — トリガー: **静的道路属性のスキーマ変更・再取込と同一バッチで実施**（第2回レビューI-6でトリガー更新。旧: 関東圏拡大 or 容量逼迫）

- surfaceを `road_edges` 列に持たせる（highwayと同じ扱い）か、`osm_raw_ways` とのJOINで導出し、
  `surface_attributes` テーブルを廃止。WARM時間（現状8〜11秒の主成分）と容量の削減を実測で確認。
- 単独で実施すると再取込が二度手間になるため、静的属性実装（T16ゲート通過後）の
  マイグレーション・再取込に同梱する。スキーマ変更はT17のマイグレーション機構経由で行う。

### - [ ] T10. DEMタイル化＋標高キャッシュ1系統化〔E3/F3〕規模L — トリガー: 標高評価の本格精査

- GSIのDEMタイルを範囲ごと取得しローカルグリッド補間へ移行（docsの既存将来課題）。
- 点単位SQLiteキャッシュとEdge単位PostGISキャッシュをDEMベースの1系統へ統合。

### - [ ] T11. `segments` のAPI境界ビン化〔E4・レビュー指摘M3〕規模M — トリガー: road_graphエンジン常用化

- Edge単位のsegmentsを約500m単位で集約してから返す。フロントの描画コスト・転送量を削減。

### - [ ] T12. Road Graph探索のスケール設計ADR〔C3〕規模M（設計のみ） — トリガー: 自前ルーティング本格化の意思決定

- pgRouting / プロセス内グラフキャッシュ / 事前縮約の比較ADRを書き、実装方針を決めてから着手する。
  現状の「リクエスト毎全量ロード」のまま機能を積まないこと。

### - [ ] T13. `WeatherService.get_conditions(at=...)` のhourly範囲外ガード〔既知L3〕規模S — トリガー: `at`を使う機能追加時

---

## Phase 4: 現時点では対応不要（任意・ついで）

### - [ ] T14. デッドコード削除 規模S

- `database.py: get_session` 削除／`graph_service.py: build_graph_for_bbox` のscripts専用明記or削除／
  `/api/routes/preview` の位置づけをdocsで実態に合わせる。

### - [ ] T15. 小粒の整理 規模S

- `ASSUMED_SPEED_KMH` をdomain定数へ統一（wind_service.py / road_graph_engine.py）。
- `repository=None` 引数への型注釈（`RoadGraphRepository | None`）追加（3サービス）。
- `get_route_generator` のlifespanベース構築への変更（C5）。
- `MapView.tsx`（751行）の分割は、レイヤー追加が続く場合のみ検討。

---

## 第2回レビュー対応（2026-08-15・複雑度平衡レビュー）

[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md) の指摘（I-1〜I-10）に対する実行計画。

### 着手前ゲート: 静的道路属性（[static-road-attributes-plan.md](static-road-attributes-plan.md)）の実装前に完了させる

順序の根拠: 属性1つあたりの変更箇所（現状backend 7〜9箇所）を増幅している要因
（手書きALTER・ファサード・検知テスト無しの同期ペア）を先に除去しないと、
このコストが約10属性分繰り返される。T16の決定がT17以降の作業の形を決めるため最初に行う。

### - [x] T16. 静的属性 実装前ゲートADR〔I-1/I-3/I-4〕規模S〜M・最優先（コード変更なし）（2026-08-15完了）

- `docs/decisions/pre-static-attributes-gate.md` を新規作成し、以下3点を決定する
  （ADRはドラフト→ユーザー承認で確定）:
  1. **評価のエンジン非依存化**〔I-1〕: ORS産geometryのサンプル点を自前DBのEdgeへ空間マッチ
     （PostGIS KNN）して属性を読む「評価の一本化」を目標状態とするか。目標とする場合、
     実装（T21）までの間、**新しい評価指標はORSエンジンでは最初からNoneを返す**設計を正とする
  2. **Overpassフォールバック撤去条件**〔I-4〕: 例「関東圏PBF取込完了＋本番でフォールバック
     発動ログ0件が2週間継続」。成立後にT22で一括削除。**それまで新属性はフォールバック側に
     実装しない**
  3. **マイグレーション方式**〔I-3〕: 番号付きSQLファイル＋適用記録テーブルの最小機構
     （Alembicフル導入はしない）。T17で実装
- 完了条件: 3決定が承認済みでdecisions/に記録され、静的属性計画の実装方針がこのADRを前提に
  確定できる状態。

### - [x] T17. 最小マイグレーション機構の導入〔I-3〕規模M — T16の後（2026-08-15完了）

- `backend/migrations/`（番号付きSQL）＋適用記録テーブル＋適用スクリプトの最小構成（50行程度）。
- 既存の `create_tables` 内の冪等ALTER×6・インデックス操作・バックフィルUPDATEを
  migration 0001 として移設し、`create_tables` は新規DB向けの `metadata.create_all`＋
  PostGIS拡張のみに凍結する（以後のALTER追記を禁止。設計原則2）。
- 完了条件: dev機PG18で「空DBから」「既存DBから」の両方で適用が冪等に成功し、全テストgreen。

### - [x] T18. Repositoryファサードの委譲メソッド調査〔I-5〕規模S（2026-08-15完了・当初案から縮小）

- **着手時に前提が誤りと判明**: `GraphService`/`ElevationAttributeService`/`RegionService`は
  `RoadGraphRepository`の具象型ではなくフラットな委譲メソッド群をダックタイピングで期待する
  設計になっており、対応するテストも同じフラットな形の`FakeRoadGraphRepository`等を独立して
  注入している。委譲メソッドは過渡的重複ではなく、サービス層とテストが依存する正式な
  インターフェース契約だった。呼び出し側をネスト参照（`.raw_osm.*`等）へ書き換えると、
  3サービス分のFakeも複製する必要が生じ、結合度が増す方向になる（依存性逆転に反する）。
  ユーザーに確認のうえ、当初案（委譲メソッド削除）を取りやめ、以下の縮小版で実施した。
- 実施内容: `RoadGraphRepository`のdocstringを訂正し、
  「フラットな形がサービス層の正式契約である」ことと「新しい属性メソッドは個別リポジトリへ
  実装したうえで、同じ流儀でファサードにもフラットな委譲メソッドを対称に追加する」規約を明記。
  複雑度平衡レビュー（I-5・Keep List・設計原則7）と本タスクを訂正済み。
- 完了条件: docstring更新のみ（コード動作は無変更）。設計原則7を「追加しない」から
  「対称に追加する」へ訂正済み。

### - [x] T19. 残存手動同期ペア2組へのドリフト検知テスト〔I-8〕規模S（2026-08-15完了）

- ①MVTレイヤー名（`vector_tile.ROAD_SURFACE_LAYER_NAME` ↔ `MapView.ROAD_TILE_SOURCE_LAYER`）
  ②タイル世代（`region_service._tile_cache_path` のv番号 ↔ `regionApi.ts`の`?v=`クエリ値）。
- `surface-tags.json` と同じ方式で自動化: `region_service.py`にハードコードされていた`v3`を
  `ROAD_SURFACE_TILE_VERSION`定数へ抽出し、`export_openapi.py`が`region-tile-config.json`
  （`layer_name`/`tile_version`）として書き出す。`MapView.ROAD_TILE_SOURCE_LAYER`をexportし、
  `regionApi.test.ts`が生成物と突き合わせる（タイル世代は`roadSurfaceTileUrl()`の実際の
  `?v=`値を検証対象にし、2重の手書き定数を作らない）。CIのapi-contractジョブでドリフト検知。
- 完了条件: どちらか片側だけ変えるとCIが割れる。backend397件・frontend129件・eslint・tsc
  すべてgreenを確認。

### - [x] T20. 本番/開発プロファイルの1表明示〔I-9〕規模S（docs/設定例のみ・任意）（2026-08-15完了）

- `.env.example`（または architecture.md）に「本番=PostGIS＋フォールバック無効＋ORSエンジン /
  開発 / CI」の設定値一覧を1表で明示する。コード変更なし。
- 実施: `.env.example`末尾へ本番（Render+Supabase）/開発（ネイティブPG）/開発（DBなし・既定）
  の3プロファイル比較表を追記。

### 条件付き・後続（静的属性の実装後、またはT16の条件成立後）

### - [ ] T21. 評価のエンジン非依存化（一本化）〔I-1/I-7〕規模L — トリガー: T16で目標化を決定し、静的属性の取込が完了していること

- ORSエンジンの評価（路面・将来の新属性）を、ORS extras依存から「サンプル点→自前DB Edge
  空間マッチ→属性読み出し」へ置き換える。カバレッジ外の挙動（None評価で候補は返す）を先に定義。
- 完了に伴い削除できるもの: `domain/road.py` のORS数値ID語彙（`GOOD_SURFACE_IDS`/
  `paved_percent`/`surface_id_at_index`/`is_good_surface`）、`RoutingService` のextrasパース、
  `RouteSegment.surface_summary/surface_values`（OpenAPI再生成でフロント型からも消える）。
- 静的属性が取り込まれる前に着手しない（照合対象の属性が無いと価値が出ない）。

### - [ ] T22. Overpassフォールバックの一括撤去〔I-4〕規模M — トリガー: T16で決めた撤去条件の成立

- `overpass_fallback_enabled` 分岐（GraphService/RegionService）・`vector_tile.py`
  （PythonMVTエンコーダ）・`OverpassClient.get_roads` と対応テストを一括削除。
- 完了条件: タイル生成経路がPostGIS（ST_AsMVT）1系統になり、カバレッジ外は空タイル＋
  常時WARNINGのみ。architecture.mdの該当記述を同一コミットで現状化。

---

## 第3回レビュー対応（2026-08-15・研究インターフェース）

[research-interface-review-2026-08-15.md](research-interface-review-2026-08-15.md)
（評価モデル研究環境としての全体レビュー）の実行計画。

### - [x] T23. 研究ループの開通（Phase 1）〔§10-1/2/5/6/9〕規模M（2026-08-15完了）

- **重みのリクエスト上書き**（§10-1）: `RouteGenerateRequest`へ`scoring_weights`/`route_preference`
  （省略可・全フィールド必須・非負）を追加。`dependencies.py`の`get_route_generator`を
  `get_route_generation_builder`（上書き値を受けて組み立てを完了するビルダー）へ再構成
- **total_score内訳の返却**（§10-2）: `RouteCandidate.score_breakdown`
  （軸別の正規化スコア・重み・寄与点。寄与点の合計=total_score）。あわせて全重み0時の
  ZeroDivisionを合成不能（total_score=None）へガード
- **条件エコー**（§10-6）: `RouteGenerateResponse.conditions`（座標・距離・適用重み・生成時刻）。
  レスポンスJSON保存＝再現条件になる
- **ルート色分けモード追加**（§10-5）: `routeStyleModes.ts`へ「路面」（road_surface_good 3値）
  「総合難易度」（difficulty 3段階）。segments返却済みデータのみでAPI変更なし
- **研究時構成の明文化**（§10-9）: architecture.md「評価重みのリクエスト上書きと評価モデル
  研究時の構成」節を新設（重み実験はroad_graphエンジンで行うこと等）
- 完了条件: backend 408件・frontend 131件・eslint・tsc全green、OpenAPI再生成済み
  （openapi.json/api.d.tsを同一コミットに含める）

### - [x] T26. 区間表示の道なり化＋距離連動サンプリング〔ユーザーFB: 区間が荒すぎて実態が分からない〕規模M（2026-08-15完了）

- `RouteSegmentDetail.geometry`（区間の道なり形状）を追加。ORSエンジンはルートgeometryの
  サンプル点インデックスで切り出し、road_graphエンジンはEdge形状点列をそのまま付与
  （いずれも追加APIコール無し）。フロント`segmentsToFeatureCollection`は形状を優先し、
  null時のみ従来の始点・終点直線で代替。propertiesからは形状を除外
- ORSエンジンのサンプリングを12点固定から距離連動へ（`sample_count_for_distance`:
  約1km間隔・下限12点・上限32点。最悪でも8候補×32点=256 GSIリクエスト/生成）
- 完了条件: backend 411件・frontend 134件・eslint・tsc全green、OpenAPI/フロント型再生成済み

### - [x] T27. 未選択候補ルートの視覚的減光〔ユーザーFB: 見にくい〕規模S（2026-08-15完了）

- T26（区間の道なり化）を実機（Playwright）で確認したところ、選択中ルートの路面/難易度色分けが
  未選択7候補（アンバー・幅3・不透明度0.85）と輻輳し、色分けの主役が埋もれて見えることを確認。
- `MapView.tsx`の`route-candidates-line`（未選択側）を、ベースマップ（OpenFreeMap、暖色系）に
  溶け込みにくい寒色（スレート`#64748b`）へ変更し、幅2.5・不透明度0.65に調整。
  8候補比較（KEEP対象、地図上での見比べ）は維持しつつ、選択中候補の色分けを主役として
  引き立てる（不透明度0.45まで下げると背景に埋没して候補が見えなくなることを実機確認済みで
  避けた。詳細な検討過程はMapView.tsxのコメント参照）。
- 検証方法: `npx playwright`（プロジェクト依存の`playwright`パッケージ、ブラウザ済みインストール）で
  実際にdevサーバーへ接続し、距離30kmでルート生成→「路面」「総合難易度」の各色分けモードへ
  切替→スクリーンショットで目視確認（8候補すべて生成されたことをRouteListのテキストからも確認）。
- 完了条件: frontend 134件・eslint・tsc全green。tsc/eslint/vitestに影響する型変更は無し
  （paint式の定数調整のみ）。

### - [x] T24. 比較環境（Phase 2）〔§10-3/4/7〕規模L（2026-08-15完了）

- `RouteCandidate.overall_difficulty`（segments難易度の距離加重平均、`domain/difficulty.py:
  distance_weighted_difficulty`）を追加。`RouteGenerator.generate_loops`で両エンジン共通に付与
  （エンジン非依存、evaluate_loops直後・スコアリング前）
- デバッグモード配下の重み調整UI（`WeightPanel`、scoring 4値＋preference 3値の入力欄＋
  「既定値に戻す」。上書き無効時は`scoring_weights`/`route_preference`をリクエストから省略し
  既存挙動を完全維持）
- フロントの実験スロット（`ExperimentSlot`、デバッグモード中の生成のみ直近3件をメモリ内保持。
  代表候補はtotal_score最上位で生成時に固定。`ComparisonPanel`で生値・絶対難易度のみの比較表
  （total_scoreはスロット間比較に出さない）、`MapView`にスロット別色（緑/オレンジ/紫）の
  重ね描きレイヤーを追加）
- 完了条件: backend 418件・frontend 141件・eslint・tsc全green、OpenAPI/フロント型再生成済み。
  Playwright実機確認（重み上書き→2回生成→比較表2列表示→地図上に色分岐した2本の重ね描き線）
  で動作確認済み

### - [ ] T25. 評価軸カタログ化（Phase 3）〔§10-8〕規模M — トリガー: 静的属性P1（評価組み込み）と同時

- 軸のid/表示名/重みキー/説明の1カタログ化。内訳表示・RouteListのhint文言・重みUIを
  カタログから列挙生成（早すぎる汎用化を避けるため、軸が実際に増える時点まで着手しない）

---

## Oracle移行後対応（2026-08-15・DB移行完遂に伴う追加タスク）

本番DBのOracle Cloud移行（docs/osm-pbf-import.md 9章Phase 5・11章）完了に伴うタスク。

### - [x] T28. PBF初回取込の減速防止（GiST対策）規模M（2026-08-15 A/B/C完了）

- 背景: Oracle初回取込（空DB・関東25km・14チャンク）でチャンク所要時間が7秒→73秒へ単調増加。
  原因は蓄積量に比例するGiST逐次挿入コスト（＋shared_buffers超過後のランダムI/O）と調査済み
  （docs/osm-pbf-import.md §10の該当項目参照）。関東フル（way約131万＝4.8倍）を現状のまま
  取り込むとマージフェーズだけで数時間級になる試算。
- 実施内容（推奨順）:
  - **(A) `osm_raw_nodes.geom`のGiST廃止** ✅完了: 全コードから空間検索されていない死荷重
    （アクセスは常に`osm_node_id`指定）。`road_graph_models.py`の`spatial_index=False`化＋
    migration 0002で`DROP INDEX IF EXISTS`（migration 0001の未使用GIN削除と同じパターン）。
    本番・ローカルとも適用済み。**実測: 本番DB 315MB→253MB（約20%削減）**、Phase 0検証23/23
    PASS維持を確認
  - **(B) 初回ロード時の`osm_raw_ways.geom` GiST後作成** ✅実装完了（未検証）:
    `import_pbf.py`に実装済み（`osm_raw_ways`が空のときのみDROP→全チャンク投入後に
    `SET maintenance_work_mem`＋`CREATE INDEX IF NOT EXISTS`で再作成。月次UPSERT再取込は
    非空のため自動的に対象外＝稼働中DBのインデックスを落とさない。途中失敗時は`finally`で
    再作成して担保）。**実際の大規模空DB取込での効果測定は未実施**（次に関東フル等の
    大規模再取込を行うタイミングで検証すること）
  - **(C) Oracle側PG設定** ✅完了（2026-08-15）: `/etc/postgresql/18/main/postgresql.conf`を
    直接編集（変更前に`postgresql.conf.bak-t28c`としてバックアップ保存）し`systemctl restart
    postgresql`で反映。`shared_buffers 128MB→3GB`・`max_wal_size 1GB→8GB`・
    `checkpoint_timeout 5min→30min`・`maintenance_work_mem 64MB→1GB`（12GB機の設定）。
    再起動後`pg_settings`で反映を確認、`/api/region/road-surface-tiles`実タイル取得（王子付近、
    HTTP 200）で本番稼働に影響がないことをスモーク確認済み
- 完了条件: 空DBへの取込でチャンク時間が平坦（終盤も序盤の2倍以内）になること。
  A/B/Cの実装・適用は完了したが、大規模空DB取込（関東フル等）での実測検証は
  まだ行っていないため、体感効果の最終確認は次回の大規模再取込時に行う

---

## 静的道路属性 P0（2026-08-15・docs/static-road-attributes-plan.md）

### - [x] P0. タグ保持基盤＋交通ストレス・自転車インフラ・路面状態レイヤー 規模L（2026-08-15完了）

- **タグ保持基盤**: `osm_raw_ways.tags jsonb`列を追加（migration 0003）。許可リスト
  （`osm_adapter.py: ALLOWED_WAY_TAGS`、18種）でフィルタしたタグのみ保持し、PBF取込
  （`import_pbf.py`）・Overpassフォールバック双方が同じ`osm_way_to_way_spec`を通るため
  同じ意味論になる
- **`domain/traffic.py`新規**: `smoothness_score`・`parse_lanes`・`parse_maxspeed`・
  `classify_bicycle_infrastructure`・`traffic_stress_level`の純関数群（すべてunknown安全）
- **MVT拡張**（タイル世代v3→v4）: `smoothness`・`tunnel`・`bridge`・`traffic_stress`（1-4）・
  `bicycle_infra`（列挙）をプロパティ追加。SQL側CASE式は`domain/traffic.py`と1:1対応させ、
  DB統合テストで11通りのタグ組合せの突き合わせ整合性テストを追加（判定ロジックの二重実装
  ドリフト検知）
- **フロント**: 「交通ストレス」「自転車インフラ」を独立レイヤーとして新規追加
  （`mapLayers.ts`・`staticAttributeLayers.ts`固定色分け、既存の「路面」の色分け軸選択とは
  別系統）。smoothness/tunnel/bridge/traffic_stress/bicycle_infraは路面クリックポップアップへ
  追加
- **T28との関係**: P0のスキーマ変更（tags列追加）はT28のGiST対策と同じ再取込に含める
  想定だったが、コード実装を先行させ、実データへの再取込・関東範囲拡大は別途実施する
  （下記「未着手」参照）
- 完了条件: backend 464件・frontend 148件・eslint・tsc全green、ローカル・本番DBへmigration
  0002/0003適用済み、Playwright実機確認（交通ストレス・自転車インフラの色分け表示、
  凡例、クリックポップアップでの新プロパティ表示）で動作確認済み

### 未着手（P0に続くタスク）

- **カバレッジ実測の再実施**: 2026-08-15の容量試算（[Static Attributes Capacity
  Estimate]メモリ）は東京都心スコープでの実測。関東圏の実データでのタグ付与率は未実測
- **既存データへの再取込**: 本番・ローカルとも`tags`列はスキーマ上追加されたのみで、
  既存行は`tags='{}'`のまま（既存インポート済みデータは新タグを持たない）。
  smoothness/tunnel/bridgeが実データで見えるようにするには、範囲拡大（T28検証）と
  合わせた再取込が必要
- **T9（surface_attributes導出化）**: 中核のルーティング評価ロジック
  （EvaluationService・RoadGraphEngine等7ファイル）に触れる別スコープの変更のため、
  P0とは切り離して別タスクとして実施する（再取込を伴わないため単独実施可）
- **静的属性P1（node取込・評価組み込み）**: signal/crossing等のnode取込機構、
  EvaluationServiceへの組み込みは計画書のP1（トリガー未成立）のまま

---

## 記録

| 日付 | 完了タスク | 備考 |
|---|---|---|
| 2026-08-15 | （計画作成） | レビュー実施・本計画策定 |
| 2026-08-15 | T1 | .github/workflows/ci.yml 追加。ローカルで全チェックgreen確認（backend 391件・frontend 122件・eslint・tsc） |
| 2026-08-15 | T2 | 符号付きへ統一（backend 392件green）。正準定義をdomain/route.pyへ明記、architecture.md追記 |
| 2026-08-15 | T3 | useMemo化（lint・tsc・vitest 122件green）。Phase 1完了 |
| 2026-08-15 | T8 | architecture.md(908行)を現状仕様(583行)へスリム化し、進捗ステータス時系列→decisions/step-log.md、旧9章(Road Graph移行の経緯)→decisions/road-graph-migration.mdへ分離(追記専用の決定記録)。9章参照・DB行の「未接続」等の古い記述も現状化 |
| 2026-08-15 | T7 | chipseal/bricksをGOOD、rock/unhewn_cobblestoneをBADへ追加し表示と評価の食い違いを解消。正準集合をsurface-tags.jsonとして書き出しroadFilterAxes.test.tsで整合検証(CIドリフト検知)。路面タイル世代v3へ。highway3スコープの関係表をarchitecture.mdへ追加、import_profile.yamlのtrunkコメント矛盾を修正 |
| 2026-08-15 | T6 | RoadGraphRepositoryを責務別4クラス(RawOsm/DerivedGraph/Attribute/TileQuery)＋公開API互換ファサードへ分割。書き込みメソッドのcommitを全廃しサービス層が操作のまとまりごとにcommit()する規約へ（「生データ保存＋タイルマーク」「分割結果＋SurfaceAttribute」が各1コミットになり原子性が向上）。mark_tile_cachedはmerge→Core UPSERT化(text()実行がautoflush対象外のため)。全392件green |
| 2026-08-15 | T5 | api/routes.py(400行)をdependencies.py＋routers/5ファイルへ分割、レート制限・同時実行上限8値をSettingsへ外部化(.env上書き可)。テストはimportパスのみ更新で全392件green、OpenAPI再生成で契約不変を確認 |
| 2026-08-15 | T4 | export_openapi.py＋openapi-typescript導入。types/route.ts・weather.tsを生成型の再エクスポート化（geometryのみGeoJSON補正、Required<>で必須化）。CIにapi-contractドリフト検知ジョブ追加。surface_summary/valuesは契約が自動導出になったため個別整理は不要と判断 |
| 2026-08-15 | （第2回レビュー） | 複雑度平衡レビュー実施（complexity-review-2026-08-15.md）。静的属性の着手前ゲートT16〜T20と条件付きT21〜T22を追加、T9のトリガーを「静的属性の再取込と同一バッチ」へ更新 |
| 2026-08-15 | T16 | 実装前ゲートADR（decisions/pre-static-attributes-gate.md）を承認・確定。決定1: 評価のエンジン非依存化を目標状態化（実装T21は静的属性取込後、それまで新指標はORS側None）／決定2: フォールバック撤去条件を承認（関東圏PBF完了＋発動ログ0件2週間）／決定3: 最小自前マイグレーション機構を採用（Alembic不採用） |
| 2026-08-15 | T17 | `infrastructure/migrate.py`（`apply_pending_migrations`、`schema_migrations`テーブルで適用管理）を新規実装。`create_tables`内の冪等ALTER×6・インデックス操作・バックフィルUPDATEを`migrations/0001_legacy_backfill_and_indexes.sql`へ移設し内容無変更で凍結。呼び出し元3箇所（import_pbf.py・verify_postgis_phase0.py・verify_phase2_e2e.py）を更新、`scripts/apply_migrations.py`を新規追加。dev機の実DB（既存スキーマ）・新規テストDBの両方で冪等性を実機確認、バックエンド397件全green |
| 2026-08-15 | T18 | 当初案（委譲メソッド削除・呼び出し側をネスト参照へ変更）が誤りと判明したため縮小実施。ファサードのフラット委譲メソッド群はGraphService/ElevationAttributeService/RegionServiceとテストFakeが依存する正式契約と確認し、docstringへ「新属性メソッドも対称にファサードへ追加する」規約を明記。複雑度平衡レビューのI-5・Keep List・設計原則7を訂正 |
| 2026-08-15 | T19 | region_service.pyにハードコードされていたタイル世代`v3`を`ROAD_SURFACE_TILE_VERSION`定数へ抽出。export_openapi.pyが`region-tile-config.json`（レイヤー名・タイル世代）を新規出力し、`MapView.ROAD_TILE_SOURCE_LAYER`をexport、regionApi.test.tsで生成物と照合するドリフト検知テストを追加。backend397件・frontend129件・eslint・tsc全green |
| 2026-08-15 | T20 | `.env.example`末尾へ本番/開発（ネイティブPG）/開発（DBなし・既定）の3プロファイル比較表を追記。コード変更なし。ゲートタスクT16〜T20が全完了、静的道路属性計画の実装に着手可能な状態に |
| 2026-08-15 | （第3回レビュー） | 研究インターフェースレビュー実施（research-interface-review-2026-08-15.md）。判定「一部改善が必要」（土台A・操作環境未着工）。T23〜T25を追加 |
| 2026-08-15 | T23 | 研究ループ開通（Phase 1）: 重みのリクエスト上書き（get_route_generation_builderへDI再構成）・score_breakdown返却（全重み0ガード含む）・conditionsエコー・ルート色分けモード「路面」「総合難易度」追加・研究時構成をarchitecture.mdへ明文化。backend 408件・frontend 131件・eslint・tsc全green、OpenAPI/フロント型再生成済み |
| 2026-08-15 | T26 | 区間表示の道なり化（RouteSegmentDetail.geometry、両エンジン・追加APIコール無し）＋ORSエンジンの距離連動サンプリング（約1km間隔・12〜32点）。フロントは形状優先描画（null時は直線代替）。backend 411件・frontend 134件全green |
| 2026-08-15 | T27 | Playwright実機確認で発覚した「未選択候補と色分け線の輻輳」を修正。未選択候補の線をアンバー→スレートへ変更し幅・不透明度を調整（8候補比較は維持しつつ選択中候補の色分けを視覚的に主役化）。frontend 134件・eslint・tsc全green |
| 2026-08-15 | （Oracle移行完遂） | 本番DBのOracle Cloud移行を完遂（スキーマ作成→Phase 0検証23/23→関東25km取込273,947way/559.5秒/315MB→Phase 2検証8/9→本番スモークOK）。初回取込の後半チャンク減速を調査しT28（GiST対策）を追加。詳細はdocs/osm-pbf-import.md 9章Phase 5・11章 |
| 2026-08-15 | T24 | 研究インターフェースPhase2（比較環境）実装。`overall_difficulty`（絶対基準集約値）・`WeightPanel`（重み上書きUI）・`ExperimentSlot`（実験スロット、直近3件）・`ComparisonPanel`（比較表）・`MapView`スロット重ね描きを追加。backend 418件・frontend 141件全green、Playwright実機確認済み |
| 2026-08-15 | T28(A/B) | PBF初回取込の後半チャンク減速対策。(A)未使用の`osm_raw_nodes.geom` GiST廃止（本番DB315MB→253MB、約20%削減）(B)初回空DB取込時のみ`osm_raw_ways.geom` GiST後作成（実装済み・大規模検証は次回取込時）。(C)Oracle側PG設定はSSH sudo制約でブロックされ保留 |
| 2026-08-15 | T28(C) | ユーザー許可を得てOracle側PostgreSQL設定を変更・反映。`shared_buffers 128MB→3GB`・`max_wal_size 1GB→8GB`・`checkpoint_timeout 5min→30min`・`maintenance_work_mem 64MB→1GB`。`systemctl restart postgresql`で反映、本番タイル取得で疎通確認済み。T28完了（大規模実測検証のみ次回持ち越し） |
| 2026-08-15 | P0(静的属性) | `osm_raw_ways.tags jsonb`（許可リスト18タグ）・`domain/traffic.py`（交通ストレス/自転車インフラ純関数）・MVT拡張（v3→v4）・フロント新規2レイヤーを実装。backend 464件・frontend 148件全green、ローカル・本番DBへmigration適用済み、Playwright実機確認済み。T9・範囲拡大・P1は別タスクとして残す |
