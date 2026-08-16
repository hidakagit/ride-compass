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

### - [x] T9. `surface_attributes` の導出化〔C4/E2〕規模M（2026-08-15完了）

- `surface_attributes`テーブルを廃止し、`road_edges.osm_way_id`経由で`osm_raw_ways.surface`を
  LEFT JOINして導出する方式へ変更（`AttributeRepository.get_surface_attributes`）。
  `osm_raw_ways.surface`は既存データにも既に入っているため再取込は不要だった
  （当初想定の「静的属性の再取込と同一バッチ」から独立して単独実施、P0実装時の判断どおり）。
- `SurfaceAttribute`型（Pydantic、`confidence`/`data_source`/`calculated_at`）はEdge Cost計算では
  実質`surface_type`しか使われていなかったため廃止し、`dict[str, str | None]`（edge_id→surfaceタグ
  生値）へ単純化。`domain/evaluation.py: compute_edge_cost`の`surface_attribute`引数も
  `surface_type: str | None`に簡約（`classify_osm_surface`は元々None安全なため分岐が消えた）。
  `GraphService`の3経路（DBなし構成・省略/fast path・通常/rebuild path）すべてをこの型に統一し、
  rebuild経路の`save_surface_attributes`呼び出し自体を削除（Edge保存とは別テーブルへの
  書き込みが構造的に無くなった）
- `migrations/0004_drop_surface_attributes.sql`で`DROP TABLE`。JOINには既存の
  `idx_road_edges_osm_way_id`（migration 0001）を使うため新規インデックス不要
- 完了条件: backend 473件全green。dev機PG18へmigration 0004適用、
  `verify_postgis_phase0.py`23/23 PASS実機確認済み。`bench_postgis_prepare.py`で実データ計測
  （ローカルPostGIS、1km: save_graph単体8.25秒/WARM経路1.92秒、4km: 13.69秒/3.06秒）。
  旧実装のSupabase WAN実測値とは接続環境が異なり直接比較不可だが、
  「専用テーブルへの追加SELECT/UPSERTが構造的に消えた」ことは実装として確認済み
  （詳細はbackend/benchmarks/README.md 11番）

### - [ ] T10. DEMタイル化＋標高キャッシュ1系統化〔E3/F3〕規模L — トリガー: 全道路網への標高属性の一括事前計算が必要になったとき（2026-08-16調査によりトリガー具体化）

- GSIのDEMタイルを範囲ごと取得しローカルグリッド補間へ移行（docsの既存将来課題）。
- 点単位SQLiteキャッシュとEdge単位PostGISキャッシュをDEMベースの1系統へ統合。
- **トリガー調査（2026-08-16）**: 「標高評価の本格精査」という当初の抽象的なトリガー文言を
  実施可否判断のため調査した結果、**精度向上を動機にした着手は不要**と判明した。
  現行の点API（`getelevation.php`、`elevation_client.py`）はGSI側で
  DEM1A→DEM5A→DEM5B/5C→DEM10Bの優先順位フォールバックを既に自動で行っており、
  DEM1Aが整備済みの地点では今のコードのまま既にDEM1A精度を受け取っている
  （[maps.gsi.go.jp/development/elevation.html](https://maps.gsi.go.jp/development/elevation.html)）。
  DEM1AはDEM5A（航空レーザ測量）の同一データを1/5格子に内挿した派生データのため
  測定精度自体はDEM5Aと同一で、違いは格子密度（5m→1m）のみ。区間勾配計算はOSM形状点
  （多くは5m超間隔）ごとに標高取得する設計のため、ルート側のサンプリング密度を上げない限り
  1m格子化の恩恵はほぼ出ない。またDEM1Aのカバレッジは2024年時点で3次メッシュ約46%
  （2026年7月にも拡大中）と全国均一ではなく、現状の自動フォールバックに頼る方が
  未整備地域での取りこぼしが少ない。
  一方、既存の点キャッシュ（SQLite接続再利用、`bench_elevation_cache.py`実測で12倍高速化済み）と
  Edge単位PostGISキャッシュにより「1地点1リクエスト」の実害も設計レビュー時点より
  縮小済みと判断。想定できる唯一の正当なトリガーは精度ではなく**量**の問題
  ——P0/P1で舗装・交通ストレス等をPBFバッチで全道路網へ事前計算したのと同じ発想で、
  標高属性も点API逐次呼び出しでは非現実的な規模（全道路網一括）で必要になったときのみ、
  DEMタイル一括取得＋ローカル補間が正当化される。それまでは現状維持とし、着手しない。

### - [ ] T11. `segments` のAPI境界ビン化〔E4・レビュー指摘M3〕規模M — トリガー: road_graphエンジン常用化

- Edge単位のsegmentsを約500m単位で集約してから返す。フロントの描画コスト・転送量を削減。

### - [ ] T12. Road Graph探索のスケール設計ADR〔C3〕規模M（設計のみ） — トリガー: 自前ルーティング本格化の意思決定

- pgRouting / プロセス内グラフキャッシュ / 事前縮約の比較ADRを書き、実装方針を決めてから着手する。
  現状の「リクエスト毎全量ロード」のまま機能を積まないこと。

### - [x] T13. `WeatherService.get_conditions(at=...)` のhourly範囲外ガード〔既知L3〕規模S（2026-08-15完了）

- `at`がhourly取得範囲（forecast_days=2分）外のとき、最も近い時刻の値を誤って代用せず
  Noneを返すガード（`_within_hourly_range`）を追加。トリガー（`at`を使う機能追加）を待たずに
  T14/T15-C5と合わせて着手（並行セッションがT9で触れていないファイルのため実施可能だった）。
- 完了条件: 範囲外指定時にNoneを返すテストを追加。backend 473件green

---

## Phase 4: 現時点では対応不要（任意・ついで）

### - [x] T14. デッドコード削除 規模S（2026-08-15完了）

- `database.py: get_session` 削除 ✅完了（2026-08-15。どこからも参照されていないことを確認して削除）
- `graph_service.py: build_graph_for_bbox` ✅完了（2026-08-15）: アプリ内・scripts内どちらからも
  呼ばれておらず（テストのみが参照）、scripts専用の需要も無いことを確認したため削除。
  `_build`共通ヘルパーを使う`build_graph_with_surface_tags_for_bbox`は実運用（`GraphService`内部の
  フォールバック経路）で使われているため維持。関連テスト2件・docstring参照
  （graph_service.py/elevation_attribute_service.py/architecture.md）を追従修正
- `/api/routes/preview` の位置づけをdocsで実態に合わせる ✅完了（2026-08-15）: バックエンドの
  エンドポイント自体は元々「Step3の疎通確認用・残置」と明記済みだったが、フロントエンド
  `routeApi.ts: previewRoute()`がどのUIコンポーネントからも呼ばれていない（テストのみ参照）
  実態が未記載だったため、architecture.md（モジュール一覧・API一覧の両方）へ追記

### - [x] T15. 小粒の整理 規模S（2026-08-15完了・lifespan化のみ見送り）

- `ASSUMED_SPEED_KMH` をdomain定数へ統一 ✅完了（2026-08-15）: `domain/wind.py`
  （`WindCalculator`と同じ「風評価」文脈のため配置）へ集約し、
  wind_service.py/road_graph_engine.pyの重複定義を削除してimportへ置換。
  road_graph_engine.py側固有の「表示専用・windのfetchには使わない」という利用文脈の注記は
  呼び出し箇所のコメントとして維持
- `repository=None` 引数への型注釈（`RoadGraphRepository | None`）追加 ✅完了（2026-08-15）:
  対象3サービス（GraphService/RegionService/ElevationAttributeService）すべてに追加。
  infrastructureはservicesに依存しないため循環importの懸念無し
- `get_route_generator` のlifespanベース構築への変更（C5）— **検討のうえ見送り**（2026-08-15）。
  `app/main.py`に`lifespan`自体が未導入で新規追加が必要な点、T23でこの関数がリクエスト毎の
  `scoring_weights`/`route_preference`上書きに対応する`build()`クロージャへ再構成済みのため
  lifespan化できるのは`settings.routing_engine`分岐のみで実利が薄い点、元のC5指摘
  （design-review-2026-08-15.md）自体が「オブジェクト構築は軽量で現状許容」「P3〜P4」と
  優先度を低く見積もっていた点から、見た目の粒度に見合わないリスクと判断し着手しなかった
- `MapView.tsx`（751行）の分割は、レイヤー追加が続く場合のみ検討。未着手

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

### - [x] T21. 評価のエンジン非依存化（一本化）〔I-1/I-7〕規模L — トリガー: T16で目標化を決定し、静的属性の取込が完了していること（2026-08-15完了）

- ORSエンジンの路面評価を、ORS extras依存（数値ID語彙）から「サンプル点→自前DB Edge空間
  マッチ→OSMタグ読み出し」へ置き換えた。`AttributeRepository.get_nearest_surface_tags`
  （PostGIS、UNNEST+LATERAL+KNN`<->`索引スキャン→`ST_DWithin`実距離30mで足切り、1回のSQLで
  全候補分の全サンプル点をまとめて処理）を新規実装し、`RoadGraphRepository`ファサードへ
  対称に委譲（T18規約）。`OpenRouteServiceEngine`は他サービス（GraphService等）と同じ
  「`repository: RoadGraphRepository | None = None`、未注入時は評価をスキップしNoneを返す」
  パターンで注入
- 削除済み: `domain/road.py` のORS数値ID語彙（`GOOD_SURFACE_IDS`/`UNKNOWN_SURFACE_ID`/
  `paved_percent`/`surface_id_at_index`/`is_good_surface`）、`ORSClient`の`extra_info=surface`
  リクエスト、`RoutingService`のextrasパース、`RouteSegment.surface_summary/surface_values`
  （OpenAPI再生成でフロント型からも削除）
- 新規: `domain/road.py: distance_weighted_road_score`（(距離, 判定)ペア列からの距離加重集計、
  両エンジン共通）。`road_graph_engine.py: _aggregate_road_score`はこれを呼ぶ薄いラッパーへ縮小
- 完了条件: backend 468件・frontend 146件・eslint・tsc全green、OpenAPI/フロント型再生成済み。
  `get_nearest_surface_tags`のDB統合テストはローカルネイティブPGに対して実行し
  （スナップ半径内/範囲外/複数点の順序保持を確認）、実際にPostGIS上で動作することを確認済み

### - [x] T22. Overpassフォールバックの一括撤去〔I-4〕規模M（2026-08-16完了）

- `overpass_fallback_enabled` 分岐（GraphService/RegionService）・`vector_tile.py`
  （PythonMVTエンコーダ）・`OverpassClient.get_roads` と対応テストを一括削除。
- 完了条件: タイル生成経路がPostGIS（ST_AsMVT）1系統になり、カバレッジ外は空タイル＋
  常時WARNINGのみ。architecture.mdの該当記述を同一コミットで現状化。
- **撤去条件を改定**（2026-08-16、ユーザー提起＋ADR決定2改定）: 当初条件2（本番ログ2週間連続0件）
  を撤廃した。理由: プロトタイプを個人で試行錯誤している低利用規模の段階では、2週間待っても
  該当ログの母数がほぼ増えず、時間経過が検証の信頼性を実質的に上げない。また本番は既に
  `OVERPASS_FALLBACK_ENABLED=false`で運用中のため、撤去しても本番の挙動自体は変わらない
  （既に無効化された経路の削除に過ぎない）。詳細は
  [decisions/pre-static-attributes-gate.md 決定2改定](decisions/pre-static-attributes-gate.md)参照。
  条件1（関東圏PBF取込完了）は2026-08-15に成立済みのため、待機なしで着手した。
- **実施内容**: `config.py`の`overpass_fallback_enabled`設定を削除。`GraphService`（repositoryモード）は
  未取込タイルを含むリクエストへ即Noneを返す読み出し専用へ変更（`OverpassClient.get_ways_and_nodes`
  はDBなし構成専用として残置）。`RegionService`は`overpass_client`/`http_client`引数ごと削除し
  `repository`のみを受け取る形へ縮小、カバレッジ外は`vector_tile.py: encode_empty_road_surface_tile`
  （空フィーチャのみの軽量エンコーダへ縮小、旧`encode_road_surface_tile`のジオメトリ変換・
  Mercator投影コードは削除）を返す。`OverpassClient.get_roads`を削除（`get_ways_and_nodes`は
  DBなし構成のRoad Graph構築専用として存続）。way数スケーリングを計測していた
  `bench_vector_tile.py`・`bench_event_loop_stall.py`は対象機能が構造的に消えたため削除、
  `benchmarks/README.md`・`run_all.py`・`_synthetic.py`を追従。`scripts/verify_phase1_e2e.py`・
  `verify_phase2_e2e.py`・`.env.example`（2箇所）・`docs/architecture.md`・
  `docs/osm-pbf-import.md`・`docs/static-road-attributes-plan.md`を現状化。
- 完了条件確認: backend 568件全green（`test_graph_service.py`のrepositoryモード関連テストは
  「GraphServiceが自らOverpassを取得・永続化する」設計から「PBF取込バッチ等が投入済みのデータを
  読むだけ」の設計へテスト前提を作り直した。タイル境界をまたぐ交差点分割の回帰テスト
  `test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`は
  repositoryへの直接シード方式に置き換えて同じ回帰を引き続き検証）。

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

### - [x] T25. 評価軸カタログ化（Phase 3）〔§10-8〕規模M（2026-08-16完了）

- 軸のid/表示名/重みキー/説明の1カタログ化。内訳表示・RouteListのhint文言・重みUIを
  カタログから列挙生成（早すぎる汎用化を避けるため、軸が実際に増える時点まで着手しない）
- 実施: `frontend/src/lib/evaluationAxes.ts`新規（`SCORING_AXES`/`PREFERENCE_AXES`、
  `mapLayers.ts`と同じ「カタログ＋汎用列挙」の型）。ラベルを`Record<keyof ScoringWeights, ...>`
  / `Record<keyof RoutePreferenceWeights, ...>`として書き、OpenAPI生成型（T4）に対する
  コンパイル時の完全性チェックをドリフト検知として使う（新規の生成物・テストは追加しない）。
  `WeightPanel.tsx`のSCORING_FIELDS/PREFERENCE_FIELDS、`RouteList.tsx`のhint文言をこの
  カタログからの生成へ置換（手作業で3箇所に分散していたラベルを1箇所化）。副次効果として、
  route_preference側で唯一UI入力欄が無かった`stop_weight`（静的属性P1で追加）も
  自動的に入力欄へ現れるようになった。バックエンド側は`test_route_scorer.py`の既存の
  axis id固定テストがそのままドリフト検知を兼ねる（コメントでフロント側との対応を明記）
- **スコープを絞った**（ユーザー承認済み）: `score_breakdown`は追加（T23）以降
  フロントのどこにも表示されていないと判明したが、新規の内訳表示UI自体は今回作らず
  カタログ基盤のみとした（新規UIサーフェスを増やすとモバイルUI改修と競合するリスクがあるため）
- 完了条件: frontend 146件・eslint・tsc全green、backend 531件green

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

- **カバレッジ実測の再実施**: ✅完了（2026-08-15、`backend/scripts/measure_tag_coverage.py`
  新規作成）。関東全域PBF（kanto-latest.osm.pbf、取込対象131万way）で実測。
  東京都心スコープの旧試算より全体的に低い（例: lanes 16.9%→8.7%、name 18.0%→8.3%、
  maxspeed 16.4%→6.2%）。**width(0.3%)・shoulder(0.0%)はP2据え置きが確定**（想定通り）。
  一方、P0で実装済みのsmoothness(0.1%)・cycleway系(各0.0〜0.6%)が想定より遥かに疎で、
  実データ投入後は表示がほぼ空になる見込み。lanes/maxspeedは幹線道路(55.8%/38.2%)でのみ
  機能し生活道路(1.8%/1.6%)ではほぼ効かないため、trafficStressは生活道路で
  highway基本値頼みになる。P1着手時（評価組み込み）はこの低カバレッジを前提にすること
- **既存データへの再取込**: ✅**完了（2026-08-15、25km圏内→関東本土全域の2段階で実施）**。
  まず本番Oracle DBへ同一bboxで再取込み（run_id=2、273,947way、db_size_mb 315→297）し
  `tags`列を実データで埋めた（詳細はosm-pbf-import.md 9章Phase 6）。続けて関東本土7都県
  （bbox 34.85,138.35-37.20,140.95、離島除外）へ拡大——`osm_raw_ways`/`osm_raw_nodes`を
  TRUNCATEしてT28(B)（GiST遅延作成）を実地発火させ、ways=1,308,092・elapsed=777.4秒
  （約13分、事前見積もり20〜70分を大幅に上回る好結果）で完走（詳細はosm-pbf-import.md
  9章Phase 7・12章）。これでsmoothness/tunnel/bridge等の静的属性が関東本土全域で
  観測可能になった
- **T9（surface_attributes導出化）**: ✅完了（2026-08-15、詳細は本ファイル「Phase 3」節の
  T9項目参照）
- **静的属性P1（node取込・評価組み込み）**: ✅**完了（2026-08-16。自転車歩行者道スコープ拡張等の
  残り4点はP2据え置き）**。信号・横断歩道・一時停止・踏切のnode取込機構（`osm_raw_pois`新テーブル、
  migration 0005）と「停止密度」評価軸（同日前半）に続き、交差点密度（intersectionDensity）・
  trafficStress・bicycle_infra（P0由来way属性）の評価組み込みも同日後半に実施（ユーザー承認の
  うえ当初のスコープ分離判断を見直し、同ラウンドで実施）。7軸すべて`route_preference.yaml`
  （区間難易度・探索コスト）のみに追加し`scoring.yaml`（おすすめ度）には追加しない方針を維持。
  詳細は`docs/static-road-attributes-plan.md` P1節参照

---

## フロントUI一貫性再編（2026-08-15・UI導線レビュー）

現状UIの導線整理で判明した課題（設定の反映タイミング・保存有無・配置の3軸がバラバラ、
「路面」等の用語衝突、デバッグモードの2役兼務）への対応。方針は「設定を『生成条件』と
『地図の見え方』の2系統へ再編し、系統ごとに反映タイミング・保存・エラー表示場所を統一する」。

### - [x] T29. デバッグ/研究モードの分割 規模S（2026-08-15完了）

- `lib/researchMode.ts`（localStorageキー `ridecompass:research-enabled`）＋`useResearchEnabled`
  フックを新設し、デバッグモード（ログ表示専任）から研究機能を分離する。
- WeightPanel表示・実験スロット記録・ComparisonPanel・MapViewスロット重ね描きの条件を
  `debugEnabled`→`researchEnabled`へ切替。DebugPanelのラベルはログ表示専任へ改名し、
  研究モードのトグル（ResearchPanel）を新設。
- 完了条件: デバッグOFF×研究ONで重み調整・比較ができ、デバッグON×研究OFFでログのみ出る。

### - [x] T30. サイドバー3ブロック再編＋用語統一 規模L（2026-08-15完了）

- サイドバーを「A. ルートを作る」（位置・天候・距離・重み・生成・候補一覧・比較表）／
  「B. 地図の見え方」（レイヤー設定）／「C. 開発者向け」（デフォルト閉。デバッグ・研究・
  疎通・再読み込み）の3ブロックへ再編。Aは最上部・デフォルト開の折りたたみ。
- レイヤーON/OFFは地図上と同一見た目のチップへ統一（サイドバー側のスイッチを置換）。
- 用語改名: レイヤー「路面」→「道路情報」／ルート色分けモード「路面」→「舗装/未舗装」／
  「総合スコア」→「おすすめ度」／重みラベルを候補一覧の表示語（距離の合わせ込み・獲得標高・
  向かい風・舗装率）へ一致／難易度重み「標高」→「勾配」／グループ見出しを役割ベース
  （「地図に重ねる情報」「生成したルートの色分け」）へ／「デフォルト（東京・王子）」→
  「初期地点（東京・王子）」／「変わらないデータを更新」→「地図データを再読み込み」（Cへ移動）／
  勾配凡例の範囲表記明確化・交通ストレス凡例の説明語追加。
- 生成前の空状態プレースホルダ（候補一覧の位置に操作ガイド文）と、ルート色分けセクション
  からAブロックへの誘導を追加。エラー表示は共通コンポーネント化（role=alert・操作箇所直下の原則）。
- 完了条件: 全テスト・lint・tsc green、Playwright実機確認。

### - [x] T31. 反映タイミングの系統別統一 規模M（2026-08-15完了）

- **系統B（地図の見え方）＝即時反映**: 路面絞り込みの「下書き→適用」を廃止し、ルート凡例と
  同じ即時チェックボックスへ統合（RoadFilterEditor削除）。連続タップの再描画負荷は
  地図への反映をデバウンス（約400ms）して吸収。軸ごとに「すべて表示/すべて隠す」を追加。
- **系統A（生成条件）＝生成ボタンで反映**: 生成済み候補と現在のフォーム値（位置・距離・重み）の
  差分を検知し、「条件が変更されています。再生成で反映されます」ヒントを生成ボタン付近へ表示
  （RouteFormのdistanceを制御コンポーネント化してpage.tsxで比較）。
- 完了条件: チェック操作が即時に地図へ反映され（デバウンス後）、生成条件の編集は生成まで
  地図に影響しないことをテストで担保。

### - [x] T32. 地図設定の保存ポリシー統一 規模S（2026-08-15完了）

- 実装補足: 保存はエフェクトではなく状態を変えるハンドラ内で更新後の値を明示的に書く方式
  （色分けモードの既存保存と同じ流儀）。エフェクト保存だと開発時StrictModeの再マウントで
  「復元前の既定値の保存」が復元読み出しへ割り込み、保存済み設定を既定値で上書きする実害を
  Playwright実機確認で観測したため。

- 系統B（レイヤーON/OFF・絞り込み/凡例の非表示キー）とAブロックの開閉状態をlocalStorageへ
  保存（色分けモードの既存保存と同じフォールバック方針: 読み書き失敗は既定値へ）。
- 完了条件: リロード後もレイヤー表示・絞り込みが復元される。系統A（位置・距離・重み）は
  保存しないことを方針として明記。

---

## モバイル実機フィードバック対応（2026-08-15）

ユーザーが外出時にスマホ実機で検証した際の8点の使いにくさフィードバックへの対応。
T29〜T32（フロントUI一貫性再編）で整理したサイドバー構成に対する、実機での追加ラウンド。
方式決定（#2の下部シート×2）はユーザーに確認済み。

### - [x] T33. レイヤーチップ列をモバイルで折り返し表示に 規模S（2026-08-15完了）

- `MapOverlayControls.module.css`の`@media (max-width:640px)`内で`.chipRow`を横スクロール
  （`overflow-x:auto`）から折り返し（`flex-wrap:wrap`）へ変更。レイヤー5種類は2行程度に収まり
  スクロール操作自体が不要になる。
- 完了条件: Playwright実機確認（390px幅）でチップ行のscrollWidth=clientWidthとなり
  横スクロールが発生しないことを確認。

### - [x] T34. モバイルを「ルート編集」「地図表示」の下部部分シート×2へ再構成 規模L（2026-08-15完了）

- 新規`BottomSheet`コンポーネント（`frontend/src/components/BottomSheet/`）: 画面下部から
  最大65vhせり上がる部分シート。フルスクリーンの暗幕は敷かず（シート表示中も地図の上側が
  見えたままパン/ズームできる）、閉じる操作は✕ボタン・下スワイプ・タブ再タップの3通り。
  `role="dialog"`のみで`aria-modal`は付けない（背後の地図を`inert`にしない）。
- `page.tsx`のサイドバー中身を`renderRouteSectionBody()`/`renderMapSettingsSectionBody()`へ
  関数化し、デスクトップの`<aside>`とモバイルの`BottomSheet`×2の両方から呼ぶ（中身の重複を
  避ける）。開発者向け`<details>`は地図の見え方側の関数末尾へ統合（以前は独立した3つ目の
  トップレベルブロックだったが、モバイルでも同じシートから触れるようにするため統合）。
  モバイルは`<aside>`ドロワー・暗幕・`inert`を全廃し、下部固定タブバー（「ルートを作る」/
  「地図の見え方」、`page.module.css: .mobileTabBar`）＋`mobileSheet`状態（排他表示）に置換。
- 実装中の実機確認で、固定表示のタブバーがMapLibreの帰属表示（`.maplibregl-ctrl-bottom-*`、
  ライセンス上必須）を覆い隠す問題を発見・修正（`page.module.css`でモバイル時のみ
  `margin-bottom: var(--mobile-tabbar-height)`を帰属表示へ適用）。
- 完了条件: backend/frontend全テスト・eslint・tsc green。Playwright実機確認（390px幅・
  1280px幅の両方）でシート開閉・帰属表示の非隠蔽・実ルート生成フローの疎通を確認。

### - [x] T35. 緯度経度の手動入力を削除 規模S（2026-08-15完了）

- `useLocation.ts`から`manualLat`/`manualLng`/`showManualInput`/`manualLocationError`/
  `toggleManualInput`/`handleManualSubmit`を削除（戻り値は`location`/`locationSource`/
  `locating`/`locateError`/`handleLocateMe`のみ）。`LocationControl.tsx`を出発地点表示のみの
  コンポーネントへ縮小。`types/route.ts`の`LocationSource`から未使用になった`"manual"`を削除。
- 完了条件: frontend全テストgreen（手動入力関連テストは削除、残る現在地取得・表示のテストは
  維持）。

### - [x] T36. 天候情報を常設ヘッダへ移動 規模M（2026-08-15完了）

- `page.module.css`に`.viewport`（画面全体の外枠、天候ヘッダ＋既存`.app-shell`行を縦に並べる）
  ＋`.weatherHeader`（1行の常設ヘッダ）を新設。`globals.css`の`.app-shell`は`height:100dvh`から
  `flex:1; min-height:0`へ変更し、外側の`.viewport`が高さ確保を担う形へ。
- `WeatherPanel`を「ルートを作る」ブロックからこの常設ヘッダへ移動（デスクトップ・モバイル共通の
  1箇所）。風向・風速が生成条件に効くことの説明は、狭いモバイル幅でも1行に収まるようヘッダの
  `title`属性（長押し/ホバー補足）へ持たせた。
- 完了条件: Playwright実機確認でヘッダに天候が表示されることを確認。

### - [x] T37. アプリ名見出しを削除 規模S（2026-08-15完了）

- `page.tsx`サイドバー内の`<h1>RideCompass</h1>`＋サブタイトルを削除。`page.module.css`の
  `.title`/`.subtitle`（参照が無くなったため）も削除。ブラウザタブ名（`layout.tsx`の
  `metadata.title`）はUI上には出ないため維持。
- 完了条件: Playwright実機確認でサイドバー内にアプリ名が表示されないことを確認。

### - [x] T38. 「地図の見え方」の各レイヤーをアコーディオン化 規模M（2026-08-15完了）

- `MapLayersPanel.tsx`のレイヤーごとの`<section>`を`<details>`（デフォルト全閉）へ変更し、
  `<summary>`に見出し＋ON/OFFチップを収めた。チップのクリックが`<details>`のネイティブ開閉と
  競合しないよう、`LayerChip`の`onClick`をイベントを受け取れる形へ変更し
  `preventDefault`/`stopPropagation`する。地図上の条件サマリからの誘導（`handleLayerSummaryClick`）
  は、対象の`<details>`が閉じていたら`.open = true`を先に設定してから開く。
- 完了条件: frontend全テストgreen（各テストは対象`<details>`を`.open = true`で開いてから
  本文中の凡例・チェックボックスを検証するよう更新）。

### - [x] T39. 交通ストレスの判定基準を凡例に明記 規模S（2026-08-15完了）

- `MapLayersPanel.tsx`の`trafficStress`セクションに、`backend/app/domain/traffic.py:
  traffic_stress_level`の要約（道路種別を基準に自転車専用帯・レーン・制限速度・車線数で
  補正した1〜4の目安、実際の交通量は加味しない旨）を1〜2文で追加。
- 完了条件: Playwright実機確認で説明文が表示されることを確認。

### - [x] T40. 自転車インフラと道路情報（路面）の違いを明記 規模S（2026-08-15完了）

- `MapLayersPanel.tsx`の`bicycleInfra`セクションに、道路情報レイヤーの路面種別（舗装の物理的
  状態）とは別軸（自転車が走る帯の構造）であることを1文で追加。
- 完了条件: Playwright実機確認で説明文が表示されることを確認。

---

## 第4回レビュー対応（2026-08-16・複雑度平衡レビュー第2弾）

[complexity-review-2026-08-16.md](complexity-review-2026-08-16.md) の指摘（R-1〜R-10）に対する実行計画。

順序の根拠: T43〜T46はいずれも「評価軸・属性を増やすときの編集箇所」を減らす作業のため、
静的道路属性P2（trafficStress・交差点密度の評価組み込み。軸が2つ増える）の**着手前**に
完了させるとコスト削減が2回以上回収される。全項目とも挙動不変で既存テストが安全網になる。
T22（フォールバック撤去）は撤去条件の成立日（最短2026-08-29）待ちのため別トラック
（確認手順はT22の節へ追記済み）。

### - [x] T43. 区間評価の4軸合成をdomainへ一本化〔R-1〕規模S〜M・最優先（2026-08-16完了）

- `domain/difficulty.py`へ「生値セット（gradient_percent・wind_penalty・road_surface_good・
  stop_count_per_km）＋`RoutePreference`→軸別難易度＋合成difficulty」を返す純関数を1つ追加し、
  `openrouteservice_engine._build_segment_details`・`road_graph_engine._build_segment_details`・
  `domain/evaluation.compute_edge_cost`の3箇所の同文ブロックをその呼び出しへ置換する。
  `RouteSegmentDetail`の構築（データ源がエンジン固有）はエンジン側に残す。
- 完了条件: 挙動不変（backend全テストgreenのまま）。評価軸を追加するときの
  「(難易度, 重み)リスト」の編集箇所が3→1になること。

### - [x] T44. 空間マッチ半径定数のdomain集約〔R-3〕規模S（2026-08-16完了）

- `SURFACE_MATCH_MAX_DISTANCE_M`（30m）を`domain/road.py`へ、
  `STOP_POI_MATCH_MAX_DISTANCE_M`（15m）を`domain/traffic.py`へ移し、
  `openrouteservice_engine.py`の定数定義と`AttributeRepository`各メソッド
  （get_nearest_surface_tags / get_stop_poi_counts / get_nearest_stop_poi_counts）の
  デフォルト引数をimport参照へ置換する（「コメントで揃える」手動同期の解消。設計原則2の具体化）。
- 完了条件: 15.0 / 30.0 のリテラルがdomainの定数1箇所ずつになり、backend全テストgreen。

### - [x] T45. ComparisonPanelの評価軸カタログ化〔R-4〕規模S（2026-08-16完了）

- `formatWeights`を`SCORING_AXES`/`PREFERENCE_AXES`（lib/evaluationAxes.ts）からの列挙生成へ
  置換する（現状はpref側が標高/路面/風の3軸ハードコードで、P1で追加された`stop_weight`が
  実験条件の表示に出ない）。`METRIC_ROWS`へ停止密度（`stop_density`）の行を追加する。
- 完了条件: 重み表示が全軸を含み、軸追加時にComparisonPanel.tsxの編集が不要になること。
  frontend全テスト・eslint・tsc green。

### - [x] T46. BICYCLE_INFRA_LABELSの重複解消〔R-7〕規模S（2026-08-16完了）

- `MapView.tsx`のポップアップ用ラベル辞書（staticAttributeLayers.tsの
  `BICYCLE_INFRA_CATEGORIES`と完全一致の写し）を、staticAttributeLayers.ts側から
  key→labelを導出したexportへ置換する（UI語彙の正準1箇所化。設計原則8の具体化）。
  `SMOOTHNESS_LABELS`は唯一の定義のため現状維持でよい。
- 完了条件: 自転車インフラのラベル文言がstaticAttributeLayers.tsの1箇所になり、
  frontend全テストgreen。

### - [x] T47. docs・運用の小粒4点〔R-5/R-6/R-9/R-10〕規模S（2026-08-16完了）

- **scoring軸判断の明記**〔R-5〕✅完了: static-road-attributes-plan.md P1節（項目3）へ、
  trafficStress・intersectionDensity等の評価組み込み着手時に「`scoring.yaml`側にも
  軸を追加するか」を明示判断項目とする旨を追記。
- **フロント分割閾値の記録**〔R-6〕✅完了（本ファイルのT47記述自体が対応）: page.tsx/
  MapView.tsxは現状維持とし、「静的レイヤー+2種類 または MapView 1,200行」到達時に
  (a)静的レイヤーensure/setペアの宣言的ループ化 (b)page.tsxの保存付き状態の
  useStoredState抽出、の2点のみ実施する方針を記録済み。T54で静的レイヤー+2種類の
  トリガーが成立し、(a)(b)とも実装済み（下の実施ログ「T47 R-6実装」参照）。
- **DBなしプロファイルの縮退明記**〔R-9〕✅完了: `.env.example`のプロファイル比較表へ、
  `ROAD_GRAPH_USE_REPOSITORY=false`では路面・停止密度評価が全区間Noneになる旨を追記。
- **dev用batスクリプトの整理**〔R-10〕✅完了: `.gitignore`が既に`restart-dev.bat`の
  ログ出力先（`/logs/`）を除外設定していることから正規の開発ツールと判断し、削除ではなく
  コミット対象化する方針とした。両ファイルへ用途・関連ドキュメントへの参照を示す
  ヘッダコメントを追加（内容は無変更）。

---

## 品質保証の追加施策（2026-08-16・計画外レビュー）

第4回複雑度平衡レビュー後、ユーザーから「テストカバレッジ・パフォーマンス計測など計画に無い観点」の
検討依頼を受け、既存の改善計画（設計レビュー系）とは別軸で品質保証体制のギャップを棚卸しした。
投資対効果の高い2点（依存関係の脆弱性検知・クリティカルパスのE2E自動化）をT48/T49として実施。
残り（カバレッジ可視化・バンドルサイズ計測・本番エラー監視）は現段階では優先度を下げて見送り。

### - [x] T48. Dependabot導入〔依存関係の脆弱性検知〕規模S（2026-08-16完了）

- `.github/dependabot.yml`を新規作成。npm（`/frontend`）・pip（`/backend`）・github-actions（`/`）の
  3エコシステムを週次でスキャン。自動マージはせず、PRが立ったら既存CI（backend/frontend/api-contract）の
  greenを確認して取り込む運用とする。
- 完了条件: 設定ファイルのみ（コード変更なし）。次回の週次スキャンでPRが起票されるかは
  実際のGitHub側スケジュールに依存するため未検証。

### - [x] T49. クリティカルパスのE2E自動化〔Playwright, CI組み込み〕規模M（2026-08-16完了）

- 背景: これまでの「Playwright実機確認」（T27・T34等）はすべてタスク実施時にAIエージェントが
  手動でPlaywrightを叩く一回性の検証で、継続的な回帰防止スイートではなかった。地図UI変更のたびに
  人手（AI操作）で確認し直す運用コストを、CIでの自動E2Eへ一部移す。
- 設計判断（バックエンド・外部APIには依存させない）: 実バックエンド＋実外部API
  （openrouteservice/Open-Meteo/OpenFreeMap）に接続するE2Eは、APIキー等のCIシークレット管理・
  無料枠消費・DBセットアップ・ネットワーク起因のflakinessを抱える。APIレスポンスの型的な正しさは
  既存の`api-contract`ジョブ（OpenAPIドリフト検知）が別途担保しているため、E2Eは
  「有効なAPIレスポンスが来たときにフロントが正しく描画・操作できるか」に対象を絞り、
  `frontend/e2e/fixtures.ts`でPlaywrightのネットワークインターセプト（`page.route`）により
  `/api/routes/generate`・`/api/weather`・`/api/basemap/**`（MapLibreスタイルを空スタイルに差し替え）・
  `/api/region/road-surface-tiles/**`をすべてモックする。この結果、E2Eジョブはバックエンドプロセス・
  DB・APIキーを一切必要とせず、frontendのみで完結する。
- 対象は2本のスモークテスト（`frontend/e2e/smoke.spec.ts`）: ①ルート生成→候補一覧の表示
  （距離入力→生成ボタン→モック2候補が一覧に表示されることを確認）②地図レイヤーのON/OFF切替
  （地図上のレイヤーチップの`aria-pressed`が反転することを確認。サイドバー側にも同名チップが
  あるため完全一致で地図上のチップに絞り込む必要があった）。
- `playwright.config.ts`: `next build && next start`（プロダクションビルド）をwebServerとして起動、
  Chromium1ブラウザのみ（クロスブラウザ検証が目的ではなくフロントのリグレッション検知が目的のため）。
- 既存のvitest（`npm test`）が`frontend/e2e/**`を`*.spec.ts`パターンで誤って拾ってしまう問題が発覚し、
  `vitest.config.mts`へ`exclude: [...configDefaults.exclude, "e2e/**"]`を追加して分離した。
- CIへ`e2e`ジョブを新規追加（`.github/workflows/ci.yml`、`frontend`ジョブと独立、DB/シークレット不要）。
  失敗時のみ`playwright-report`をartifactアップロードする。
- 完了条件: ローカルで`npm run test:e2e`2件green、既存`npm test`148件green・eslint・tsc green
  （いずれも確認済み）。CI上での実行結果は次回push/PRで確認。

---

## 外部静的データソース検討対応（2026-08-16）

[external-data-sources-review-2026-08-16.md](external-data-sources-review-2026-08-16.md)
（外部静的データソースの精査・実行計画、同ドキュメント§4）の実施順（§4.6）に沿ったタスク起票。
DEMタイル化（同ドキュメント優先2）は既存T10と同一のため新規タスクは起こさず、
T10の実行設計として同ドキュメント§4.2を参照する形にする。

### - [x] T50. 警察庁事故データ→事故密度軸（8軸目）規模L（2026-08-16完了）

- **2026-08-16訂正**: 起票時点では本票CSVの入手をユーザー作業（手動ダウンロード）と
  想定していたが、実際のURL構造を確認したところ
  `https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{year}/honhyo_{year}.csv`
  という年号だけで組み立てられる予測可能なパスで、2019〜2024年の全年で同一命名規則
  （`honhyo_`/`hojuhyo_`/`kosokuhyo_`）を確認済み。ログイン・利用登録不要、robots.txtにも
  制限記述なし、直接GETでHTTP 200・text/csvが返ることを確認済み（2024年分62.8MB）。
  したがって**CSV取得はバッチに組み込める**（ユーザー作業は不要）。コード表
  （`codebook_{year}.xlsx`、当事者種別コード等）も同じ命名規則で取得可能だが、こちらは
  `domain/accident.py: involves_bicycle`の分類ロジックを書く際の参照資料として一度確認すれば
  足りるため、実行時バッチでの取得対象には含めない。
- 詳細設計は外部静的データソースレビュー§4.1参照。取込（`import_accidents.py`新規。
  年次リストを引数に`honhyo_{year}.csv`をHTTP取得→Shift_JISデコード→ステージング→MERGE、
  `log_external_call`で取得を囲み404等はWARNING常時出力・スキップして継続）→
  保持（migration 0006、`accident_points`/`accident_import_runs`）→表示先行
  （`/api/region/accident-tiles/{z}/{x}/{y}.pbf`、kind=static新規レイヤー）→評価組み込み
  （`get_accident_counts`/`get_nearest_accident_counts`、`accident_difficulty`を8軸目として
  `evaluate_axis_difficulties`へ、`route_preference.yaml`のみ・`scoring.yaml`は非対称維持）の順。
- 完了条件: DMS変換・自転車関連判定の単体テスト、ST_DWithin境界の統合テスト、実CSVでの
  dry-run、Playwright表示確認、backend/frontend全green。

**実装結果（取得・保持・表示先行、2026-08-16）**:

- **取得**: `app/batch/import_accidents.py`（新規）。年次リストから`honhyo_{year}.csv`のURLを
  組み立ててHTTP取得（`backend/data/accidents/`へ保存、既取得分は再ダウンロードしない）、
  CP932デコード→`csv.reader`で1行ずつストリーム処理→関東7都県（`domain/accident.py:
  KANTO_PREFECTURE_CODES`）へ絞り込み。**2019〜2021年は本票CSVが58列構成（2022年以降は
  68列）と実データで判明し非対応**（列数不一致はその年の取込全体をValueErrorで明示的に
  失敗させる設計。詳細は同ファイルのモジュールdocstring参照）。2022〜2024年の3年分を
  実際に取り込み、関東で303,455件（自転車関連92,955件・死亡事故2,032件）を確認済み
- **保持**: migration 0006（`accident_points`/`accident_import_runs`、`accident_models.py`）。
  `domain/accident.py`（新規・純関数）: 都道府県コード表・当事者種別コード表は
  2026-08-16に実際にコード表CSV（`npa.go.jp/.../koudohyou/`）を取得して確認した値を使用
  （51/52=軽車両-自転車/駆動補助機付自転車を`involves_bicycle`、死者数>0を`is_fatal`）。
  緯度・経度は度分秒連結表記（右5桁=秒×1000、次2桁=分、残り=度）から10進変換
- **表示**: `/api/region/accident-tiles/{z}/{x}/{y}.pbf`（`accident_repository.py:
  AccidentTileQuery`＋`accident_service.py: AccidentService`、road_surfaceと違い
  カバレッジ判定は無い＝関東全域が一律で対象）。フロントは新規レイヤー「事故（警察庁統計）」
  （`mapLayers.ts`、kind=static）、円レイヤー（`MapView.tsx`、色=自転車関連/その他、
  死亡事故は円を拡大）、クリックポップアップ、サイドバー凡例（`MapLayersPanel.tsx`）。
  `next.config.ts`にproxy rewriteを追加（road-surface-tilesと同じ理由、追加し忘れると
  フロントから404になることを実機で発見）
- 完了条件のうち「実CSVでのdry-run」「Playwright表示確認」「backend/frontend全green」は
  達成（backend 595件・frontend 153件・eslint・tsc全green、Playwright実機確認で
  地図上のドット表示・凡例・クリックポップアップ・チップON/OFFを確認）。

**実装結果（評価組み込み、2026-08-16）**: `AttributeRepository.get_accident_counts`/
`get_nearest_accident_counts`（`get_stop_poi_counts`と同型、`bicycle_only`切替付き）＋
`get_accident_years_covered`（`accident_import_runs`の成功run数から動的取得、
ハードコード定数にしない）を新規実装し`RoadGraphRepository`ファサードへ対称に委譲。
密度は「件/(km・年)」（`domain/accident.py: distance_weighted_accident_density`、
収録年数で正規化する点がstop_density等と異なる）。`domain/difficulty.py:
evaluate_axis_difficulties`を7軸→8軸へ拡張（改善計画T43で1箇所化済みのため呼び出し元
3箇所は引数追加のみ）。`RoutePreference.accident_weight`（初期値0.08）を
`route_preference.yaml`のみへ追加（`scoring.yaml`は既存7軸と同じ非対称維持、追加せず）。
`RouteSegmentDetail.accident_difficulty`/`RouteCandidate.accident_density`追加、
`RoutePreferenceWeights`（API境界）へも対称に追加、OpenAPI/フロント型再生成。
フロントは`evaluationAxes.ts`のPREFERENCE_AXIS_METAへ1軸追加（型完全性チェックで
自動ドリフト検知）、`WeightPanel.tsx`の既定値、`ComparisonPanel.tsx`の`METRIC_ROWS`へ
事故密度行を追加（stop_density/intersection_densityと同じ前例に倣う、こちらは
カタログからの自動生成ではないため手動追加が必要）。ST_DWithin境界の統合テストを含む
完了条件を満たした。backend 645件（新規25件）・frontend自分の変更分は全green
（eslint・vitest対象ファイル）。tsc: 本タスクが変更したファイルにエラーなし。
なお実装時点で別セッションがpage.tsx/MapView.tsx/staticAttributeLayers.*を並行編集中で
未完了のtsc差分が存在したが、本タスクとは無関係のため関知していない。
2019〜2021年データの取込（別スキーマの列位置調査が必要）は任意の拡張として引き続き残る

### - [x] T51. 指定路線コンフレーション機構＋N10/N12表示 規模L（2026-08-16完了、スコープをN10/N12のみへ縮小）

- 詳細設計は外部静的データソースレビュー§4.3参照。「線データをroad_edgesへ対応付ける」
  パターンD初回実装（migration 0007、`route_designations`/`designation_attributes`、
  バッファマッチ`ST_Length(ST_Intersection(edge, ST_Buffer(designation, 20m)))/ST_Length(edge) ≥ 0.5`）。
  N10/N12（緊急輸送道路・重要物流道路、GeoJSON登録不要で取得済み確認）は
  trafficStress補正＋MVT表示、ナショナルサイクルルート（太平洋岸自転車道・りんりんロード、
  KML/GPX登録不要）はまず独自線ソースでの表示のみ先行。
- 特段の外部トリガー待ちは無く着手可能（データ入手に登録手続き不要と確認済み）。
- 完了条件: 既知路線（国道16号・6号等）の目視確認、matched_ratio分布・バッファ幅比較での
  誤対応（並行側道・歩道の巻き込み）実測、backend/frontend全green。

**2026-08-16訂正（ユーザー指示によるスコープ縮小）**: 「N10、N12対応まででいったんとどめて」
との指示を受け、ナショナルサイクルルート（太平洋岸自転車道・りんりんロード）は今回のラウンドから
除外。加えて実装着手時にデータソース調査をやり直したところ、レビュー当初の想定
「N10もGeoJSON形式での提供を確認済み」が誤りと判明（N10はGML/シェープファイルのみ、
GeoJSONが実在するのはN12のみ。両方とも実際にダウンロード・展開して中身を確認して発覚）。
りんりんロードについてもレビュー文書が想定していたGPX配布元（つくば市サイクリングガイド）が
404で、機械可読な一括ダウンロード元が見つからなかった（NCR除外の判断を後押しする追加根拠）。

**実装結果（バックエンド、2026-08-16）**:

- **取得**: `app/batch/import_designations.py`（新規）。N10はZIP内のJPGIS/GML
  （`gml:Curve`＋`ksj:UrgentTransportationRoad`、xlinkで参照）を標準ライブラリ
  `xml.etree.ElementTree`でパース、N12はZIP内の素のGeoJSONを標準ライブラリ`json`で
  パース（**新規依存ライブラリ追加なし**、pyshp/fiona/geopandasいずれも不要と判明）。
  都道府県コードだけで組み立てられる公開URL
  （`https://nlftp.mlit.go.jp/ksj/gml/data/N{10,12}/...`）から関東7都県分を直接取得
  （実機確認済み、登録不要・PDL1.0相当で非商用利用可）。事故データと違い自然キーが無いため
  ステージング→MERGEではなく`(kind, pref_code)`単位のDELETE→INSERTで冪等にする。
  実際にdev DBへ取り込み、5,084件（N10: 2,820件・N12: 2,264件）を関東7都県で確認済み
- **保持**: migration 0007（`route_designations`/`designation_attributes`/
  `designation_import_runs`、`designation_models.py`新規。accident_models.pyと同じ
  「取込元がOSMではないため専用ファイルに分離しつつ同じBaseを共有」方針）。
  `domain/designation.py`（新規）: `DESIGNATION_BUFFER_WIDTH_M`(20m)・
  `DESIGNATION_MATCH_MIN_RATIO`(0.5)・`TRAFFIC_STRESS_DESIGNATION_KINDS`（正準1箇所、
  改善計画T44の「片側import」原則）
- **マッチング**: `app/batch/match_designations.py`（新規、事前計算バッチ）。
  road_edges×route_designationsをST_DWithinで絞り込んだ上でST_Union→ST_Intersection→
  ST_Lengthでバッファ交差率を算出し`designation_attributes`へ書き込む（同一(edge_id,kind)へ
  複数route_designations行が寄与する場合の二重計上をST_Unionで防止）。**実データ規模
  （関東7都県5,084件×dev DBのroad_edges 22,164件）でのdry-run実行時間が長い問題を確認・解決
  （2026-08-16）**: 初回実装（GROUP BYにe.geomを含む・バッファをJOIN内で行ごとに再計算）は
  1時間近く無応答の末に接続エラーで失敗。GROUP BYをe.edge_id単独へ変更しバッファ計算を
  `WITH ... AS MATERIALIZED`で1行1回に限定する改善をまず行ったが、それでも30分超無応答
  だったため`EXPLAIN`でクエリプランを確認したところ根本原因が判明: JOIN条件が
  `ST_DWithin(e.geom::geography, b.geom::geography, $1)`と`::geography`キャストを
  挟んでいたため、`idx_road_edges_geom`（geometry型GiST索引）をプランナが認識できず
  Join Filter（22,164×5,084の全組み合わせを評価、コスト14億）に落ちていた。buffer_geom
  （既に20mバッファ済みのgeometry）に対する素の`ST_Intersects(e.geom, b.buffer_geom)`
  （どちらもgeometry型、キャスト無し）へ変更したところGiST索引が使われるようになり
  （コスト239万、約590倍改善）、実データでdry-run 12.8秒・本実行15.5秒で完走。
  dev DBへ実際に投入し7,052件（emergency_transport 6,090・critical_logistics 962）を確認済み。
  正しさ自体はDB統合テスト（test_road_graph_repository.py、小規模フィクスチャ）で確認済み
- **評価組み込み**: `domain/traffic.py: traffic_stress_level`へ`is_designated`引数を追加
  （既存のtrack/lane等補正と同じクランプ内+1、新しい評価軸は増やさない）。
  `AttributeRepository.get_designated_edge_ids`/`get_nearest_designated_flags`を
  `get_way_tags`系と同型で新規実装しファサードへ対称に委譲、3エンジン呼び出し箇所
  （road_graph_engine.py/openrouteservice_engine.py/domain/evaluation.py）を更新
- **MVT表示**: `_ROAD_SURFACE_TILE_MVT_SQL`（road_graph_repository.py）へ`designation`
  プロパティとtrafficStress+1補正を追加（`cw`/`ts`と同じCROSS JOIN LATERALパターン、
  road_edges経由でdesignation_attributesと相関）。`ROAD_SURFACE_TILE_VERSION`を
  `4→5`へ（T19の版上げ手順どおり）。SQL⇔Python二重実装の整合性テストを追加
- **フロント表示（2026-08-16完了）**: `mapLayers.ts`へ`designation`レイヤーを追加
  （trafficStress/bicycleInfraと同じ、road_surfaceソースを再利用する独立レイヤー）。
  `staticAttributeLayers.ts`へ`DESIGNATION_LEGEND`/`DESIGNATION_COLOR_EXPRESSION`/
  `DESIGNATION_LABELS`を追加（emergency_transport=赤・critical_logistics=青・対象外=灰、
  T63の絞り込み軸カタログにも追加）。`MapView.tsx`の`STATIC_OVERLAY_LAYERS`
  （T47 R-6の宣言的ループ）へ`ensureDesignationLayer`を追加、クリックポップアップは
  `RoadSurfacePopupProperties`へ`designation`を追加する形で（trafficStress/bicycle_infraと
  同じ）road情報ポップアップに統合。`icons.tsx`へ盾形の新規アイコン、
  `MapOverlayControls.tsx`のアイコン対応表・`MapLayersPanel.tsx`のセクション本文にも追加。
  `page.tsx`は`DEFAULT_LAYER_VISIBILITY`への1行追加のみ（絞り込み・保存・要約計算は
  カタログ駆動のため自動対応）
- **実機確認（2026-08-16、Playwright）**: dev backendプロセスが2026-08-15起動のまま
  （uvicorn --reloadなし）で今回のSQL修正・designation列追加を反映していなかったため、
  `restart-dev.bat`相当の手順でbackend/frontendを再起動してから検証。designation_attributesに
  実在するedge（emergency_transport該当）の座標を直接DB照会で特定し、その地点へ地図を
  ナビゲートして確認: (1) 指定路線レイヤーをONにすると該当道路が赤線（緊急輸送道路）で
  ハイライトされる、(2) サイドバーの凡例（緊急輸送道路(N10)・重要物流道路(N12)・対象外）が
  正しく表示される、(3) 該当道路をクリックすると「緊急輸送道路（N10）」のポップアップが
  表示され、交通ストレスが4/4（+1補正込み）と一致することを確認
- backend: 新規テスト一式（GML/GeoJSONパーサの実データ検証・DB統合テスト・
  domain単体テスト・MVT整合性テスト）を含め652件、frontend 215件・tsc・eslint全green
  （T50コミット後に本タスク分のみを再度乗せて確認、T50・T51それぞれの範囲が独立に
  テスト通過することを確認済み）

### - [ ] T52. JICE舗装点検DB 調査ゲート実行 規模S（調査のみ）〜L（採用時）— トリガー: JICE返信

- **現状: JICEへ照会メール送信済み（2026-08-16）、返信待ち**（利用資格・料金・緯度経度有無・
  関東収録範囲の4点を1通で照会済み、詳細は外部静的データソースレビュー§4.4）。
- 返信到達後、ゲート1〜3（緯度経度有無→収録範囲→T51機構でのマッチ精度実測、目安80%以上）を
  順に確認し、途中で✕なら見送り。通過した場合のみ`pavement_sections`/`pavement_attributes`を
  実装（新軸にはせず、既存smoothnessスコアへ「実測MCI優先」の入力ソースとして合成）。
- 完了条件: ゲート0〜3の結果を本ファイルまたはレビュードキュメントへ追記し、採否を確定する。

### - [ ] T53. JARTIC交通量によるtrafficStress較正 規模M（研究IF側の検証作業）— トリガー: 特になし（手が空いたとき）

- 詳細設計は外部静的データソースレビュー§4.5参照。評価パイプラインには入れず、
  1回のスナップショット収集（`collect_jartic.py`新規、dev機PostgreSQLのみ保持）→
  観測点近傍エッジの`traffic_stress_level`と実交通量分布の突き合わせで完結させる。
  定期収集は較正に不足する場合のみ検討（停止条件を先に決めておく）。
- 完了条件: LTS段階間で交通量分布が単調に分離しているかの分析結果を記録し、
  分離が悪ければ`TRAFFIC_STRESS_BASE_BY_HIGHWAY`等の見直し材料とする。

### - [x] T54. 既取込データの可視化漏れ解消（停止要因POI・交差点密度レイヤー）規模S〜M（2026-08-16完了）

- 背景: 2026-08-16の棚卸しで判明。`osm_raw_pois`（信号・横断歩道・一時停止・踏切、
  migration 0005・P1で導入済み）は評価（停止密度軸）にのみ使われており、地図上に
  一切表示されていない（対応するAPIエンドポイント・レイヤーが存在しない）。
  intersectionDensity（交差点密度、次数3以上のroad_node）も同様に評価専用で、
  可視化レイヤーが無い。どちらも**新規データ取得不要**（既存テーブル・既存派生値の表示化のみ）。
- 完了条件: 停止要因POI・交差点密度が地図上で確認できる。Playwright実機確認。
  backend/frontend全green。

**実装結果（2026-08-16）**: 別セッションが着手・大部分実装した状態で中断していたものを
本セッションが引き継ぎ、その間に本流へ合流していたT50（警察庁事故データ）・T58（ピンチズーム
修正）と統合して完成させた。

- **表示**: `/api/region/poi-tiles/{z}/{x}/{y}.pbf`（新規）。road_surfaceと同じカバレッジ判定
  （road_graph_tilesのz12祖先タイルマーク）を再利用しつつ、1タイルへ`stop_poi`・`intersection`
  の2レイヤーを焼き込む（`_POI_TILE_MVT_SQL`、`RoadSurfaceTileQuery.get_poi_tile_mvt`）。
  `RegionService`はroad_surface/poiの2種のタイル取得を共通の`_get_tile`ヘルパーへ統合。
  フロントは「停止要因」「交差点密度」の2つの独立レイヤー（`mapLayers.ts`）、円マーカー
  （`MapView.tsx`、停止要因は種別ごとの色分け、交差点密度は接続数で円の大きさを補間）、
  クリックポップアップ、サイドバー凡例（`MapLayersPanel.tsx`）
- **統合作業**: T54ブランチ（`.claude/worktrees/t54-poi-intersection-viz`）はT50と同じ
  ファイル群（`mapLayers.ts`・`MapView.tsx`・`MapLayersPanel.tsx`・`MapOverlayControls.tsx`・
  `regionApi.ts`・`staticAttributeLayers.ts`・`icons.tsx`・`export_openapi.py`・
  `region-tile-config.json`）を独立に変更していたため、T50を含む形へrebaseし14ファイルの
  コンフリクトを解消（すべて「両方の追加を残す」加算的マージ、削除・意味変更の衝突は無し）。
  `region-tile-config.json`はT50が`{layer_name, tile_version, accident:{...}}`、T54が
  `{road_surface:{...}, poi:{...}}`と異なるスキーマへ変更していたため、
  `{road_surface:{...}, accident:{...}, poi:{...}}`へ統一。T54側にも
  `next.config.ts`のproxy rewrite追加漏れ（T50で発見したのと同じ既知の落とし穴）があり、
  合わせて追加した
- **データ欠損の確認**: 実機確認でdev DBの`osm_raw_pois`が0件（signal/crossing等のnode取込が
  このDBには未実施）と判明。`intersection`レイヤーは実データ（次数3以上のnode 8,517件）で
  正常動作を確認（785 features/タイル、`degree`プロパティ確認済み）。`stop_poi`は0件のため
  空レイヤーとして正常動作（エラーにはならない）が、視覚的な確認は再取込み後の課題として残る
- 完了条件確認: backend 617件・frontend 187件（vitest workerタイムアウトが1件出たが
  該当ファイル単体では8/8 pass、既知の並行セッション資源競合による偽陽性と確認）・tsc・eslint
  全green。Playwright実機確認で「停止要因」「交差点密度」「事故（T50）」の3レイヤー同時ON、
  サイドバー凡例、地図上の交差点密度ドット表示（実データ）を確認
- **本番データ欠損の解消（2026-08-16追記）**: ユーザー報告（本番onrender.comで停止要因・交差点密度・
  事故が一切描画されない）を受けて本番Oracle Cloud DBを直接調査したところ、上記のdev DB欠損より
  深刻な状態と判明した。`osm_raw_pois`・`accident_points`の2テーブルが**本番に存在しない**
  （migration 0005・0006が未適用）、かつ`road_nodes`/`road_edges`（タイル描画が実際に読む
  導出済み道路グラフ）が**本番で0件**（`GraphService.get_or_build_graph_with_attributes`の遅延
  構築方式のため、生データ取込み直後はどの地点も未構築。ルート生成した地点のみその場で構築・
  永続化される設計、docs/architecture.md参照）だった。対応: ①ユーザー許可を得てmigration 0005・
  0006を本番へ適用、②本番へ`import_accidents.py --years 2022-2024`実行（303,455件、devと一致）、
  ③本番へ`import_pbf.py`を前回と同じ関東本土bbox（34.85,138.35-37.20,140.95）・
  `kanto-latest.osm.pbf`で再実行（アップサート、66チャンク・3056秒≒51分、
  ways=1,308,092は前回と同数のまま`osm_raw_pois`332,004件を新規投入）。dev DBも同じPBF
  （Tokyo.osm.pbf、既存と同じ小範囲bbox）で再取込みし`osm_raw_pois`46,688件を投入済み。
  `road_nodes`/`road_edges`の本番一括先埋めは今回のスコープ外（設計どおり実際にルート生成
  された地点から自然に埋まる想定のため）。大規模書き込み系コマンドは自動モードの安全分類器に
  一度ブロックされ、ユーザーへ状況説明の上で明示的な再試行指示を得てから実行した。

**未起票のまま据え置き（既存文書で追跡継続、二重管理を避ける）**: `name`/`ref`のMVT焼き込み・
`tracktype`表示は
[static-road-attributes-plan.md](static-road-attributes-plan.md) §3.1の未着手項目として
既に記録済みのため、本節では新規タスク化しない。**2026-08-17追記**: 自転車歩行者道の取込
スコープ拡張・`bicycle=no`のHard Constraint（`oneway:bicycle`例外を含む）は、ユーザー承認済みの
別ブランチ作業（`origin/claude/osm-roadbike-map-features-1yn5yi`、コミット`0f1f952`）をmasterへ
統合し、T番号の衝突（同ブランチはT96〜T99を使用していたが、masterは既にT96〜T98を別件で
使用済みだった）を避けてT99〜T102として本ファイルへ起票した（後方の「OSM追加属性の活用検討」節
参照）ため、この据え置きリストから外す。

---

## UI操作レビュー対応（2026-08-16）

[ui-review-2026-08-16.md](ui-review-2026-08-16.md)（Playwright実機操作による一般ユーザー目線レビュー）の
要改善点3件をT55〜T57として起票。同レビューで最重要所見として報告した「候補選択のたびに地図が
読み込み中に戻る」は検証スクリプトのセレクタ不具合による誤検知と判明し再検証済みのため、
起票対象からは除外している（詳細はレビュー文書の「訂正」節を参照）。

### - [x] T55. モバイル下部タブバー×北コンパスボタンの重なり解消 規模S（2026-08-16誤検知と判明・起票対象外）

- 390px幅で、地図左下の黒丸「N」ボタンが下部タブバー（「ルートを作る」ラベルの1文字目）と
  重なる所見だったが、Playwrightで再現・スクリーンショット確認したところ**アプリ自作の
  ボタンではなく、Next.js開発モード（`next dev`）が既定で表示するDev Toolsインジケータ**
  （`devIndicators.position`既定値`bottom-left`、本番ビルドには現れない）と判明した。
  実際の地図コントロール（`maplibregl-ctrl-compass`）は右上に配置されており無関係。
  アプリ側の修正は不要と判断し、起票対象から除外する（詳細は
  [ui-review-2026-08-16.md](ui-review-2026-08-16.md)「訂正2」参照）。
- 残る所見（同条件での地図初期表示6秒超）はヘッドレスブラウザのタッチエミュレーション特有の
  遅延の可能性が残ったまま実機未検証。継続して気になる場合のみ実機スマートフォンで確認する。

### - [ ] T56. 初回ルート生成時の地図タイル一過性表示崩れの再現性確認 規模S（調査・優先度低）

- 初回「ルート生成」直後、地図が新しいルート範囲へズーム/パンする過程で、右半分だけ
  英語ローマ字ラベルの別スタイルタイルが矩形状に一瞬混在する場面が1度観測された
  （再実行では発生せず、確度は高くない）。タイル読み込みタイミング次第の競合が疑われる。
- 複数回の生成操作を連続実行し、再現するか・再現条件（初回のみか、ズーム幅が大きい時か等）を
  切り分ける。再現しない場合はクローズしてよい。
- 完了条件: 再現性の有無を記録。再現する場合のみ原因調査・修正へ進む。
- 追加証跡（2026-08-16、統合レビューF-4）: headless Playwrightでの操作確認中に、候補到着直後に
  地図が縮小正方形で描画され直後に自然回復する類似症状を観測（Phase 5スクリーンショット06→07、
  詳細は[history/2026-08-16_all.md](../.claude/commands/review/history/2026-08-16_all.md)）。
  再現条件は「headless環境・候補到着直後」で、その後の操作で自然回復。headless固有の可能性を
  排除できておらず（Confidence: Medium）、実機スマートフォン・通常ブラウザでの再現性確認は
  本タスクの完了条件として引き続き残る。

### - [x] T57. 天候インジケータの視認性向上 規模S（2026-08-16完了）

- 常設ヘッダの天候表示（T36で追加）が小さいグレー文字1行のみで、初見では見落としやすい。
  向かい風・追い風がルート選定の判断材料になっている（`route_preference.yaml`の風関連重み）
  ことを踏まえ、文字サイズ・コントラスト・アイコン化等での視認性向上を検討する。
- 完了条件: Playwright実機確認で改善前後の見た目を比較・記録。frontend全テストgreen。

**実装内容**: `WeatherPanel.tsx`に風アイコン（`icons.tsx`の`WindIcon`、既存アイコン群と
同じstroke=currentColorの線画スタイル）を追加し、テキストを`font-size: 0.9rem`→`0.95rem`・
`font-weight: 600`・`color: var(--foreground)`明示（従来は無指定で実質デフォルト色）へ変更。
アイコンは`color: var(--color-accent)`の行コンテナに置きcurrentColorで色を継承させ、
天候ヘッダ全体の主張を強めた。あわせて「現在の天候: 」の接頭辞を削除（アイコンとheaderの
title属性で文脈は伝わるため冗長と判断）。理由は視認性だけでなく、太字化＋アイコン追加で
横幅が増えた結果、狭いスマホ幅（360px/320pxで実測）では接頭辞込みだと2行に折り返され
ヘッダが縦に伸びる回帰が発生したため（Playwrightで320/360/390pxを実測して確認、
削除後は最狭320pxでも1行維持）。`WeatherPanel.test.tsx`のerror状態アサーションは
`/現在の天候/`→`/の風/`へ更新（接頭辞除去に伴う自然な追従）。
frontend 180件（他セッションとの並行実行によるvitest workerタイムアウトが1件出たが、
該当ファイル単体では7/7 pass、既知の資源競合による偽陽性と確認）・tsc・eslint全green。

### - [x] T58. スマホでピンチイン・ピンチアウトが効かないことがある不具合の修正 規模S（2026-08-16完了）

- ユーザー報告（スマホ実機、位置依存で発生）を受けて調査。原因は、MapLibre GLが地図キャンバス自体には
  `touch-action: none`を正しく付与している一方、このアプリが地図上に独自に重ねている操作ボタン
  （左上のレイヤーアイコン列`.iconChip`・条件サマリ`.summaryButton`、右下の現在地ボタン
  `.locateButton`）には`touch-action`が一切指定されていなかったこと。2本指ピンチの片方がこれらの
  ボタンに乗ると、ブラウザがタッチ開始点ごとに異なる`touch-action`を見て地図ジェスチャーとして
  確定できず反応しない、という筋（`layout.tsx`のviewport設定にも`maximumScale`/`userScalable`の
  制限が無く、ページの既定ズームに化ける余地も残っていた）。
- 修正: `MapOverlayControls.module.css`の`.iconChip`/`.summaryButton`と`page.module.css`の
  `.locateButton`へ`touch-action: none`を追加（BottomSheetの`.handle`・FloatingPanelの
  `.dragHandle`が既に持っていたのと同じ対策をこれら3要素にも揃えた）。ページ全体のズーム無効化
  （アクセシビリティ上避けたい`user-scalable=no`）は行わない、より狭い修正で対応。
- 完了条件: frontend既存テストgreen（CSSのみの変更のため対象コンポーネントのテストに影響なし、
  vitest 5件確認済み）。ピンチ自体はヘッドレスブラウザでの自動テストが困難なため、
  実機での改善確認はユーザー側で追って行う。
- **2026-08-16追記（根本原因の追加修正）**: 実機再確認で「部分的にズームができない」
  「画面全体を拡大縮小してしまう」の両症状が残っていると報告あり、再調査。
  `MapOverlayControls.module.css`の`.wrapper`は`pointer-events: none`で地図へタッチを
  透過させる設計だったが、直下の`.chipRow`だけ`.wrapper > *`で`pointer-events: auto`に
  戻していたため、ボタンの隙間（行間のgap・単独チップ横の余白）まで丸ごとタッチ捕捉領域に
  なっていた。この隙間は`touch-action`未指定（既定auto）のため、ピンチの片方の指が乗ると
  ブラウザがページ全体のネイティブズームに化けていた（T58当初の修正はボタン本体への対症療法で、
  コンテナの隙間を塞いでいなかった）。`pointer-events: auto`を実際に押せる`.iconChip`/
  `.summaryButton`だけに局所化し、隙間は`.wrapper`の`pointer-events: none`を継承して
  地図へ素通しするよう修正。同じ穴があった`page.module.css`の`.locateError`と
  `MapView.tsx`のエラーバナーにも`pointer-events: none`を追加。frontend全187件green。

### - [x] T59. 地図タイル閲覧だけでも道路グラフ(road_nodes/road_edges)が構築されるよう対応 規模M（2026-08-16完了）

- 背景: ユーザー報告（本番で停止要因・交差点密度・事故が描画されない）の調査中、
  `road_nodes`/`road_edges`（道路情報・交通ストレス・自転車インフラ・交差点密度レイヤーの
  タイル配信が実際に読むテーブル）が、**ルート生成（`GraphService.get_or_build_graph_with_attributes`
  経由）でしか構築されない**設計と判明。地域タイル配信（`RegionService`）は`road_graph_tiles`
  （生データ取込済みマーク）だけを見て`road_edges`を直接読むだけで、GraphServiceの構築ロジックを
  一切呼んでいなかった。生データ（`osm_raw_ways`）を関東全域に取り込んでも、実際にルート生成
  されたことがない地点は道路グラフが空のままになりうる。ユーザー指摘「ルート生成時にその場だけ
  情報保持は微妙。ルート生成と地図の閲覧は別々の用途で使うこともある」を受けて対応。
- 対応: `RegionService._tile_from_repository`が、カバレッジ内（生データ取込済み）と分かった
  z12祖先タイルについて、`_maybe_trigger_graph_build`でバックグラウンド構築を起動するよう変更。
  同期的に待たせるとNext.jsのrewritesプロキシ30秒タイムアウト（docs/architecture.md参照）に
  触れかねないため、タイル応答自体はこれまでどおり即座に返し、構築は`asyncio.create_task`で
  非同期に進める（次回以降の同じ地域へのアクセスから反映される）。実装のポイント:
  - z12（`ROAD_GRAPH_TILE_ZOOM`）タイル単位でプロセス内メモリのみの重複起動防止セット
    （`_building_graph_tiles`）を持ち、ビューポート内の多数のz13-15タイルリクエストが
    同じz12祖先へ集約されても構築は1回だけ起動する（road-surface/poi両タイルの
    リクエストからも同じキーで重複排除される）
  - 直近`_GRAPH_CHECK_TTL_SECONDS`（300秒）以内に確認済みのタイルは再チェックしない
    （既に最新でも地図を眺めるたびに`is_split_up_to_date`確認用の短命DBセッションを
    開き続けない対策）
  - `RegionService`のユニットテストで使う`FakeRegionRepository`はダックタイピングで
    `RoadGraphRepository`を継承しないため、`isinstance`判定で自然に発火対象から外れ、
    ユニットテストが実DBへ触れることはない
- 本番Oracle Cloud DBの`road_nodes`/`road_edges`一括先埋めは今回のスコープ外（設計どおり
  自然に埋まる想定のため。詳細はT54節「本番データ欠損の解消」参照）
- 完了条件: backend 621件（新規テスト4件: 実リポジトリでの発火・フェイクでの非発火・
  重複起動防止・TTLスキップ）全green
- **2026-08-16追記（本番障害・同時実行数上限の追加）**: デプロイ直後、ユーザーが本番実機の
  デバッグログで`accident-tiles`の502エラーを複数観測（`region-accidents`ソース、z12/z13の
  異なるタイルで連続発生）。調査の結果、上の実装が原因と判明: 実構築（closure再計算・Edge
  全量再UPSERT、数十秒〜数分規模）が**DBセッションを長時間保持したまま同時実行数を一切
  絞っていなかった**。SQLAlchemyの接続プール上限は既定15（pool_size 5+max_overflow 10）で、
  `road_tile_max_concurrent`(6)+`accident_tile_max_concurrent`(6)が既に最大12を占有しうる
  設計だったため、密集した未構築エリアへの一斉アクセス（ユーザーが地図を広く動かした場面）で
  背景構築タスクがプールの残り枠を奪い合い、無関係な`accident-tiles`等の通常タイル配信まで
  接続待ちで502化した（以前「密集タイルのバーストでRenderが再起動する」障害を踏まえ
  road_tile/accident_tile側は同時実行数上限で対策済みだったが、今回の新規バックグラウンド
  経路には同様の歯止めが無かった）。
  - 対応: `config.py`へ`graph_build_max_concurrent: int = 1`を追加し、実構築部分のみ
    `asyncio.Semaphore`で絞る（鮮度確認`is_split_up_to_date`は軽いクエリのためsemaphore外）。
    1つのセッションを保持したままsemaphore待ちにすると「順番待ちタスクが次々に接続だけ
    先取りして塞ぐ」逆効果になるため、鮮度確認と実構築を別セッションに分離してから絞った。
    低優先度の完全バックグラウンド処理のためユーザー体験への影響は無く、複数エリアへの
    構築要求は単に順番に処理される。
  - 完了条件: backend 621件全green

### - [x] T60. 交差点密度チップの幅を他レイヤーと揃える 規模S（2026-08-16完了）

- `chipLabel`未指定のため5文字の正式名称「交差点密度」がそのままチップ幅
  （`width: max-content`）に反映され、4文字以下の`chipLabel`で揃えている他レイヤー
  （trafficStress/bicycleInfra/accidents）より横に長く不揃いに見えていた（実機フィードバック）。
  `mapLayers.ts`へ`chipLabel: "交差点"`（3文字）を追加。

### - [x] T61. 天候ヘッダをアイコン+区切り線のスタット表示へ再構成 規模S（2026-08-16完了）

- 気温・風向風速・降水確率を"/"区切りの1文で表示していたが、区切りの"/"と風速の単位
  "m/s"の"/"が混ざって見え読みにくいという実機フィードバックを受けて再構成した。
- 対応: 項目ごとにアイコン（気温=温度計・風=渦気流（既存WindIcon）・降水確率=雨粒、
  新規`ThermometerIcon`/`RaindropIcon`、`icons.tsx`）を添えて視覚的に区切り、項目間の
  "/"は区切り線（`.divider`）に置き換えた。値と単位（℃/m/s/%）は別要素にして単位側を
  一段淡く・小さくし（`.unit`）、値と単位が混ざらないようにした。アイコンだけでは
  伝わらない項目名はスクリーンリーダー向けに`.srOnly`（clipパターン）で補足している。
- テスト: DOM Testing Libraryの既知の制約（複数要素にまたがるテキストは通常のgetByTextの
  TextMatchでは見つからない）のため、値+単位をまたぐアサーションは`container.textContent`
  の結合テキストで確認する形へ書き換えた。
- 完了条件: frontend全テストgreen（WeatherPanel: 新規2件含む6件）、tsc/eslintクリーン、
  Playwright実機確認（ライト/ダーク両テーマ、480px幅ヘッダのスクリーンショット）で
  アイコン・区切り線・値/単位の視覚的分離を確認済み。

---

## 属性の重複・包含関係レビュー対応（2026-08-16）

ユーザーからの指摘（「自転車インフラ」は道路情報の中の「自転車・歩行者道」と意味が
一部かぶっていないか）を受けた属性カタログの棚卸し。

### - [x] T62. 自転車インフラ表示ラベルの衝突解消＋軸間の入力共有をコメントで明記 規模S（2026-08-16完了）

- 棚卸し結果:
  1. `bicycle_infra`の`shared_pedestrian`ラベル「自転車歩行者道」
     （`staticAttributeLayers.ts`）と、「道路の種類」レイヤーの`highway`分類グループ
     「自転車・歩行者道」（`roadFilterAxes.ts`、highway=cycleway/path/footway/
     pedestrian/bridleway/steps）が中黒の有無だけの差で並存し紛らわしい。指しているもの
     （前者=自転車の通行条件、後者=道路種別タグ）は異なり、包含関係もきれいではない
     （highway=cycleway⊂separated、path/footwayはbicycleタグ次第でshared_pedestrianに
     なる場合とroadwayに落ちる場合がある、pedestrian/bridleway/stepsはどちらにも
     個別対応が無くroadwayへ落ちる、cycleway=track併設の幹線道路はhighway側では
     「自転車・歩行者道」に入らないままseparatedになる、など）。
  2. `traffic_stress_level`と`classify_bicycle_infrastructure`
     （両方とも`domain/traffic.py`）が同じcycleway/cycleway:left/right/bothタグを
     別々の目的で解釈している。そのため「専用自転車道が併設されている」という1つの
     事実が、`交通ストレス`重みと`自転車インフラ`重み（`evaluationAxes.ts`）の両方を
     同時に押し下げ、2軸は完全には直交しない。
  3. `TRAFFIC_STRESS_BASE_BY_HIGHWAY`にpath/footway/pedestrian/bridleway/steps/
     motorway/motorway_link/service/roadが登録されておらず、これらの区間は交通ストレス軸
     では常にNone（評価対象外）になる一方、道路の種類・自転車インフラでは評価対象になり
     うる（3軸のカバレッジが揃っていない）。
- 対応方針: スコアリングの数値・挙動は変更しない（暫定値の本格チューニングはP2据え置き
  のまま）。表示ラベルの衝突解消と、上記の設計上の非直交性・カバレッジ差を将来の読み手が
  「バグ」と誤認しないよう根拠コメントとして明記する。
  1. `staticAttributeLayers.ts`の`shared_pedestrian`ラベルを「自転車・歩行者道」と区別
     できる表記へ変更（`roadway`の「車道（専用施設なし）」と対になる書き方に揃える）
  2. `classify_bicycle_infrastructure`と`traffic_stress_level`のdocstringへ、同じ
     cycleway系タグを別目的で解釈しており2軸が完全には直交しない旨の相互参照コメントを追加
  3. `TRAFFIC_STRESS_BASE_BY_HIGHWAY`へ、テーブル外のhighway値が意図的に評価対象外
     （None）である旨のコメントを追加
- 完了条件: frontend/backend全テストgreen、tsc/eslintクリーン。

---

## 静的属性レイヤーの絞り込みUI拡張（2026-08-16）

ユーザー指摘（「道路情報と同様の絞り込みを他の静的道路属性でも実施したい」）を受けた検討。
当初案（属性カテゴリのチェックボックスを機械的に横展開）を提示したところ、ユーザーから
「交差点密度のような連続量は属性カテゴリ単位でなく、アプリの目的（安全・快適なルート判断）に
沿った絞り込み方を再検討してほしい」という追加指摘を受け、レイヤーごとに絞り込み軸の設計を
見直した。

### - [x] T63. 静的属性5レイヤーへの絞り込みUI追加（交差点密度は閾値バケット化、事故は重大度軸を新設）規模M（2026-08-16完了）

- 対応方針: `staticAttributeLayers.ts`の`STATIC_FILTER_AXES`カタログへ絞り込み軸を集約し、
  `roadFilterAxes.ts`（道路情報）が使う汎用機構（`legendFilter.ts`の
  `buildLegendFilterExpression`/`buildCombinedLegendFilterExpression`、`MapLayersPanel.tsx`の
  凡例チェックボックス方式）をそのまま流用。属性値のカテゴリを機械的に絞り込み軸へ展開するのではなく、
  レイヤーごとにアプリの目的に沿った軸を選定した:
  - 交通ストレス・自転車インフラ・停止要因POIは名義尺度のため、既存のカテゴリをそのまま
    絞り込み可能にした（変更なし、絞り込みUIの配線のみ追加）。
  - 交差点密度はdegree（接続路の本数）という連続量を単一カテゴリのまま扱っていたため
    そもそも絞り込みようがなかった。円の大きさ（`INTERSECTION_RADIUS_EXPRESSION`、degree=3で
    最小・6以上で最大）と同じ閾値で「3本」「4〜5本」「6本以上（主要な交差点）」の3段階＋
    防御的な「不明・他」に束ね、「主要な交差路だけ表示」を実現。
  - 事故は既存の当事者軸（自転車関連/その他）に加え、既に円の拡大で強調していた重大度
    （死亡事故か否か、`fatal`）を独立した第2軸として新設し、道路情報の「路面の種類×道路の種類」
    と同じAND絞り込み（`buildCombinedLegendFilterExpression`）で「死亡事故だけ確認したい」に応えた。
- 実装: `staticAttributeLayers.ts`（`INTERSECTION_LEGEND`の3+1バケット化、`ACCIDENT_SEVERITY_LEGEND`
  新設、`STATIC_FILTER_AXES`カタログ）、`MapView.tsx`（`STATIC_FILTER_AXES`をlayerIdで
  `STATIC_OVERLAY_LAYERS`と突き合わせる`setStaticOverlayFilters`を新設、道路情報の
  `applyRoadLayerState`と同型）、`MapLayersPanel.tsx`（`renderLegendDisplay`（参照専用表示）を
  廃止し、道路情報の`renderRoadAxis`と同型の`renderStaticFilterAxis`へ統一、OFF中でも操作可能・
  自動ON案内も道路情報と揃える）、`page.tsx`（`hiddenLegendKeysByMode`の同一namespace内に
  6軸ぶんのキーを追加、`staticLegendHiddenKeysByAxis`をuseMemoで安定化、道路情報と同じ400ms
  デバウンス定数を`LEGEND_FILTER_DEBOUNCE_MS`へ改名して共有、地図上チップのサマリ行
  （`summarizeLegendFilters`）も5レイヤーへ拡張）。
- 完了条件: frontend全テストgreen（`staticAttributeLayers.test.ts`へ交差点密度バケットの
  境界値網羅・事故重大度軸・`STATIC_FILTER_AXES`整合性のテストを追加）、tsc/eslintクリーン。

---

## PostGISクエリコストレビュー対応（2026-08-16）

「OSMのみ→個別データソース追加で遅いSQLが散見される」というユーザー依頼を受け、全テーブル・
全SQL（road_graph_repository.py・accident_repository.py・batch群・migrations 0001〜0007）を
通読し、dev DB（東京都心南部: road_edges 22,164行・accident_points 303,455行・osm_raw_pois
46,688行）でEXPLAIN ANALYZE実測して裏付けを取ったレビューの対応タスク。

**根本原因はテーブル設計ではなくクエリ規約の不徹底**: `_INTERSECTION_COUNTS_SQL`のコメントで
明文化済みの「`geom::geography`のST_DWithinはGiST索引を使わずSeq Scanになるため、必ず`&&`
（bbox重なり）を前置する」という規約を、後発の停止POI・事故カウント4クエリが踏襲していなかった。
テーブル設計自体（raw/派生の分離・点テーブルの選別方針・import_runs系・`=ANY(配列)`チャンク・
KNNの`ORDER BY <-> LIMIT 1`・ST_AsMVTのDB側生成）は一貫しており健全と確認した。

レビューで問題なしと確認した事項（タスク化しない）: `idx_route_designations_geom`未使用は
将来の表示レイヤー用に許容（240kB）／`_NEAREST_WAY_TAGS_SQL`等のCASE内ST_DWithin二重評価は
誤差レベル／ANALYZE統計はautovacuumが正常追随。

### - [x] T64. geographyキャストST_DWithinの索引不使用4クエリへ`&&`前置フィルタ追加 規模S〜M（2026-08-16完了）

- 対象（road_graph_repository.py、いずれもJOIN条件がST_DWithin(geography)単体で
  GiST索引を使えず全件Join Filterになる）:
  - `_STOP_POI_COUNTS_SQL`（road_edges×osm_raw_pois）
  - `_NEAREST_STOP_POI_COUNTS_SQL`（サンプル点×osm_raw_pois）
  - `_ACCIDENT_COUNTS_SQL`（road_edges×accident_points）
  - `_NEAREST_ACCIDENT_COUNTS_SQL`（サンプル点×accident_points）
- dev DB実測: `_STOP_POI_COUNTS_SQL`は**200エッジで134.1秒**（Join Filter除外467万行/ワーカー）、
  `_NEAREST_ACCIDENT_COUNTS_SQL`は**8点で18.6秒**（240万行評価・Materializeがディスクスピル）。
  `get_stop_poi_counts`/`get_accident_counts`はルート評価でローカルグラフ全edge（数千〜数万件）を
  渡すため、現行実装は評価1回で分〜時間オーダーになりうる。本番（関東全域、road_edges 134万行）
  ではさらに悪化する。
- 対応方針: `_INTERSECTION_COUNTS_SQL`と同じく、JOIN条件へ
  `p.geom && ST_Expand(e.geom, :max_distance_deg)`（点版は`ST_Expand(pts.geom, ...)`）を前置。
  度換算は既存の`_meters_to_bbox_margin_deg`をそのまま使う（マイグレーション不要）。
  代替案の関数索引`gist((geom::geography))`はSQL無変更で済むが、リポジトリ内で確立済みの
  `&&`前置パターンへの統一を優先する。
- 修正版の実測（同条件）: `_STOP_POI_COUNTS_SQL` 134.1秒→**0.44秒（306倍）**、
  `_NEAREST_ACCIDENT_COUNTS_SQL` 18.6秒→**0.24秒（79倍）**。いずれもGiST索引スキャンに変わる
  ことをEXPLAIN ANALYZEで確認済み。
- 再発防止: docs/complexity-review-2026-08-16.md末尾の設計原則へ原則11「空間JOINを含むSQLは
  `&&`前置（または`ORDER BY <-> LIMIT`のKNN索引）必須。ST_DWithin(geography)単体をJOIN条件に
  しない」を新規追加（同一コミット）。
- **実装結果（2026-08-16）**: 4クエリすべてへ`&&`前置フィルタ（`_meters_to_bbox_margin_deg`で
  度換算）を追加。dev DBで`_STOP_POI_COUNTS_SQL`（200エッジ）を再検証し、
  `EXPLAIN`が`Index Scan using idx_osm_raw_pois_geom ... Index Cond: (geom && st_expand(...))`
  へ変化（修正前はJoin Filter）、実測1.2秒（同条件の元実装134.1秒から大幅短縮）を確認。
  結果セットは不変（backend 652件、既存repository統合テスト無変更でgreen）。
  `osm_raw_pois`/`accident_points`の`geom`列GiST索引（`idx_osm_raw_pois_geom`/
  `idx_accident_points_geom`）は既存のため追加migration不要
- 完了条件: 4クエリのEXPLAINでSeq Scan+Join Filterが消えGiST索引が使われること。
  既存のrepository統合テスト（件数・境界値）が無変更でgreen（結果セットは不変のはず。
  `&&`は保守的マージンのため取りこぼしが無い）。

### - [x] T65. 路面MVTタイルの指定路線判定をway行ごとLATERALから事前集約JOINへ 規模S（2026-08-16完了）

- `_ROAD_SURFACE_TILE_MVT_SQL`の`d` LATERAL（designation焼き込み、T51で追加）は、タイル内way
  1本ごとにroad_edges→designation_attributesの索引スキャンを実行する（way1本あたり約0.16ms）。
  dev DB実測で全way相当39,878本を6.27秒。密集タイル（数千way）では1タイルあたり数百msの上乗せ。
- 対応方針: designation_attributes全体（本番でも数千〜数万行の小テーブル）を一度だけ
  `osm_way_id`単位に集約するサブクエリへ書き換え、`LEFT JOIN ... ON d.osm_way_id = w.osm_way_id`
  のハッシュJOINにする。同条件の実測で6.27秒→**0.36秒（17倍）**。
  ```sql
  LEFT JOIN (
      SELECT e.osm_way_id,
             bool_or(da.kind = 'emergency_transport') AS is_ert,
             bool_or(da.kind = 'critical_logistics') AS is_cl
      FROM designation_attributes da JOIN road_edges e ON e.edge_id = da.edge_id
      GROUP BY e.osm_way_id
  ) d ON d.osm_way_id = w.osm_way_id
  ```
  （`d.is_ert`/`d.is_cl`の参照側は`COALESCE(..., false)`へ変更）
- T51の残作業「フロント表示とパフォーマンス実地検証」と同じ箇所のため、T51側の検証前に
  実施するのが望ましい。
- **実装結果（2026-08-16）**: `_ROAD_SURFACE_TILE_MVT_SQL`のdesignation判定を
  `CROSS JOIN LATERAL`（way1本ごとの索引スキャン）から提案どおりの事前集約`LEFT JOIN`へ
  書き換え。LEFT JOIN化に伴い`d.is_ert`/`d.is_cl`はtraffic_stress側の参照のみ
  `COALESCE(..., false)`でNULL対応（designationプロパティのCASE式は`WHEN d.is_ert THEN ...`が
  NULLで自然にfalse相当になるため無変更）。dev DBで実データ（z12/z14タイル、designation該当
  206件を含む）を突き合わせ、書き換え前後でdesignationプロパティが完全一致することを確認。
  test_road_graph_repository.pyの整合性テストも含めbackend 652件green
- 完了条件: test_road_graph_repository.pyの整合性テスト（Python実装との同値性）が無変更でgreen。
  MVT出力のdesignationプロパティが書き換え前後で一致。

### - [x] T66. save_graphのdelete-then-reinsertでdesignation_attributesが黙って消える問題の対策 規模M（2026-08-16完了）

- `save_graph(way_ids_to_replace=...)`は既存Edge行をDELETE→再INSERTするため、
  `ON DELETE CASCADE`の`designation_attributes`が巻き添えで消える。elevation_attributesは
  オンデマンド再計算で復元されるが、designationは`match_designations.py`のバッチ再実行まで
  該当Edgeの指定路線フラグが欠落し、**評価（trafficStress加点）とMVT表示の両方が静かに
  間違う**。edge_idは決定論的なので同じedge_idで再INSERTされても属性行は戻らない。
  OSM再取込後だけでなく、通常のルート生成による再split（is_split_up_to_dateがFalseの経路）でも
  発生する。
- 対応方針（いずれかを選択、実装時に判断）:
  - 案a: save_graphのDELETE対象から「今回も同じedge_idで再挿入される行」を除外する
    （delete-then-reinsert→UPSERT+差分DELETEへ変更。CASCADEが発火するのは本当に消える
    edge_idだけになる）。推奨: 分割結果が実際に変わらない大多数のケースで属性が保存される。
  - 案b: save_graph完了時に該当edge_idだけ`route_designations`と部分再マッチする軽量処理を挟む
    （バッファ交差の対象が少数edgeに限られるため評価時導出よりは軽いが、リクエスト経路に
    空間計算が入る）。
- 完了条件: 「取込済みdesignationを持つEdgeが再splitされても、分割結果が同一なら
  designation_attributes行が残る」ことを検証する統合テストを追加しgreen。
  docs（T51節またはdecisions/）へ「match_designations.pyの再実行が必要になる条件」を明文化。
- **実装結果（2026-08-16、案aを採用）**: `save_graph`のedge_rows計算をDELETEより前へ移動し、
  「今回のgraphに同じedge_idで含まれる行」をDELETE対象から`edge_id.not_in(new_edge_ids)`で
  除外するよう変更（`_bulk_upsert`のON CONFLICT DO UPDATEが効くため、除外した行は
  INSERT→CASCADE発火ではなくUPDATEで更新され、designation_attributes等のEdge派生属性が残る）。
  new_edge_idsが空（対象way群がEdgeを1件も生成しなかった）場合は従来どおり全削除。
  回帰テスト2件を追加: ①同一分割結果（同じedge_id）での再saveでdesignation_attributesが
  残ることを確認、②実際にsegment構成が変わりedge_idが消える再split（node6の交差点扱いが
  無くなり2segment→1segmentへ統合）では、CASCADEどおり古いedge_idの行が正しく消えることを確認
  （新edge_idは`match_designations.py`の再実行が必要という既存の運用のまま）。
  backend 654件（新規2件）green。docsへの運用条件明文化は本節自体が該当箇所とする

### - [x] T67. match_designations.pyのINSERTをexecutemany化 規模S（2026-08-16完了）

- `_INSERT_SQL`をマッチ件数分（dev実測7,052行、本番は数万行想定）ループで1行ずつ
  `conn.execute`しており、本番（Oracle遠隔）ではRTT×行数がそのまま実行時間に乗る。
- 対応方針: `conn.executemany`（asyncpg、1ラウンドトリップにバッチ化される）へ置換。
  行数がさらに増える場合はCOPY（`copy_records_to_table`）も選択肢だが、
  現規模ではexecutemanyで十分。
- 完了条件: dry-run→実行で従来と同一件数が書き込まれること。バッチのログ
  （docs/logging.md準拠の1行INFOサマリ）へ書き込み所要時間を追加。
- **実装結果（2026-08-16）**: `conn.executemany`へ置換し、ログへ`insert_elapsed`
  （INSERT部分のみの所要時間）を追加。dev DBで実行（road_edges増加により対象は
  28,940件へ拡大していた）、insert_elapsed=4.1秒で完走。backend 652件green

### - [x] T68. is_split_up_to_date用のstale限定部分GiST索引 規模S（2026-08-16完了）

- `is_split_up_to_date`はリクエストごとにbbox内の全way（GiST走査＋split_atフィルタ）を
  スキャンしてstale行を探す。全way freshの定常状態が大多数なのに、bboxが大きいほど
  （ルート生成は最大60km径ループ＋マージン）走査量が線形に増える。
- 対応方針: migration 0008として
  `CREATE INDEX ... ON osm_raw_ways USING gist (geom) WHERE split_at IS NULL OR split_at < updated_at`
  を追加。クエリのWHERE句が述語と完全一致しているためプランナがそのまま使え、
  定常状態では索引がほぼ空になりLIMIT 1判定が即時になる。
  取込直後（全行stale）は通常GiSTと同等まで膨らむが、split進行に伴い縮む
  （インデックスの肥大が気になる場合はsplit一巡後にREINDEX）。
- 完了条件: 定常状態のdev DBでEXPLAINが部分索引を選ぶこと。既存テストgreen。
  import_pbf.pyのGiST後作成分岐（T28(B)）との整合（初回取込時の索引作成順）を確認。
- **実装結果（2026-08-16）**: `migrations/0008_stale_way_partial_index.sql`として提案どおりの
  部分索引を追加。dev DB・テストDB双方へ適用しEXPLAIN ANALYZEで`idx_osm_raw_ways_geom_stale`が
  選ばれることを実測確認（実データでstale行1件を含むbboxに対しExecution Time 10ms）。
  T28(B)の索引ドロップ＆再作成は`idx_osm_raw_ways_geom`（フルGiST）のみを対象にしており
  今回の部分索引は対象外と確認した（新規PBF一括取込では今回追加した部分索引はドロップされず
  存続する。取込直後は全行staleのためフルGiSTと同等サイズになる点は元々のタスク記述どおりで
  想定内、split進行で自然に縮む）。backend 666件green

### - [x] T69. get_way_specs_with_closureの近傍extent爆発の防衛 規模M・要設計判断（2026-08-16完了）

- 近傍Wayの探索範囲を「主対象Way全体のST_Extent」で決めているため、bboxをかすめる
  1本の長大way（河川沿いサイクリングロード・幹線等で数十km）があるとextentがその全長へ
  広がり、そこに交差する全way＋全node座標をロードする。上限ガードが無く、
  最悪ケースでメモリ・転送量・build_road_graph計算量が数十倍に膨らむ。
- 対応方針（候補、実装時にログで実態を見て判断）:
  - 案a: extentを`ST_Expand(bbox, 上限マージン)`でクランプする（実装最小。クランプ幅を
    超えて伸びるwayの端の交差点は「そのwayが主対象になる別リクエストで更新される」
    既存の結果整合性の考え方に載せられる）。
  - 案b: 主対象wayごとの個別envelope集合（ST_Collect）で近傍検索する（過剰包含が最小に
    なるが、クエリが複雑化）。
  - まず現状把握として、extentがbboxの何倍まで広がっているかをdocs/logging.md準拠の
    1行INFOサマリ（route_generator.py方式）でログし、実データで閾値を決めてから実装してよい。
- 完了条件: タイル境界交差点分割の回帰テスト（test_graph_service.py）がgreenのまま、
  極端なextent拡大が発生しないことをログまたはテストで確認。
- **実装結果（2026-08-16）**: 案aを採用。`NEIGHBOR_EXTENT_MAX_MARGIN_M`（10km）を追加し、
  主対象Wayのextentを要求bboxからこのマージン分拡張した範囲へ`ST_Intersection`でクランプする
  （主対象Wayは定義上すべて要求bboxと交差するため、クランプ結果が空集合になることはない）。
  クランプが実際に発動した場合（raw extentとclamped extentが異なる場合）はWARNINGで
  raw/clamped両方の座標を1行ログする。dev DBのEXPLAIN実測では通常時（クランプ不要な
  ケース）はraw=clampedで一致することを確認。回帰テスト
  `test_get_way_specs_with_closure_clamps_extent_of_a_long_primary_way`（node1からのびる
  長大wayの遠端付近にある無関係wayが近傍として含まれないこと・WARNINGログを確認）を追加。
  backend 667件green

---

## designation実装レビュー対応（2026-08-16・8角度コードレビュー）

T51実装（指定路線N10/N12の取込・マッチング・評価・表示）の未コミット変更に対する
コードレビュー（候補発見8角度＋1票候補の検証2エージェント、確定26件・要実測1件・棄却0件）
の対応タスク。起票済みのT65〜T67と重複する指摘は除外済み。T70〜T73が正確性・データ欠損系で
最優先、T74は設計判断（T66と関連）、T75以降は構造整理。

### - [x] T70. タイル世代v5の対上げ漏れ修正 規模S・最優先（2026-08-16完了）

- backend `region_service.py: ROAD_SURFACE_TILE_VERSION`は"5"へ上がったが、
  `frontend/src/services/regionApi.ts`の同名定数と生成物
  `frontend/src/types/generated/region-tile-config.json`が"4"のまま（`export_openapi.py`
  未再実行）。T19の「対で上げる」規約違反。フロント定数と生成物が両方旧値"4"で一致している
  ためT19のドリフト検知テストはgreenのまま素通りする（CIのapi-contractジョブは再生成差分で
  検知するはず）。
- 影響: v4時代にタイル閲覧済みのブラウザが`?v=4`のHTTPキャッシュ済みタイル
  （designationプロパティ無し・trafficStress+1補正前）を使い続け、指定路線レイヤーが
  全区間灰色のままになる。
- 対応: `export_openapi.py`を再実行して生成物を更新し、`regionApi.ts`の定数を"5"へ。
- 完了条件: `roadSurfaceTileUrl()`が`?v=5`を返し、regionApi.test.ts含めfrontend全green。

### - [x] T71. import_designations.py取込の原子性・0件ガード・executemany化 規模S〜M・最優先（2026-08-16完了）

- 問題1（原子性）: (kind, pref)単位のDELETE→INSERTがトランザクション外
  （match_designations.pyの`conn.transaction()`と非対称）で、asyncpgのautocommitにより
  1文ずつ確定する。INSERT途中の接続断・型エラーで「旧データDELETE済み・新データ一部のみ」の
  中途半端な状態がDBへ確定し、後続のmatch_designations.pyはrun状態を確認せず欠けたデータで
  designation_attributesを再計算する。
- 問題2（0件ガード）: パーサが0件を返した場合もDELETEだけ実行され、status=succeeded・
  count=0で「成功」として既存データが静かに消える。0件時のログもINFO固定で、
  docs/logging.mdの「候補0件はWARNING以上・原因内訳を同行に」規約に違反。
- 問題3（効率）: features（関東7都県5,084行）を1行ずつ`conn.execute`しており、
  T67で解消したmatch側と同じRTT×行数問題をimport側が抱えている（T67のスコープはmatch側のみ）。
- 対応: `async with conn.transaction()`で括り、0件時はDELETEせずWARNINGでスキップ、
  INSERTは`conn.executemany`化（T67と同じ処方）。1行INFOサマリへ`insert_elapsed`追加。
- 完了条件: 「0件時に既存データが残る」「途中失敗時に旧データが残る」のテスト追加、
  backend全green。
- **実装結果（2026-08-16）**: `_write_designations`ヘルパへDELETE+executemanyを
  `async with conn.transaction()`で括って抽出し、features空時はDELETEごとスキップして
  WARNINGログを出す。1行INFOサマリへ`insert_elapsed`を追加し、0件時はWARNINGへ昇格。
  `tests/test_import_designations.py`に統合テスト3件（0件時保持・置換・executemany失敗時の
  ロールバック、asyncpg.Connectionをmonkeypatchして模擬）を追加。backend 666件green

### - [x] T72. designationパーサの防御強化（3要素座標・MultiLineString・複数セグメント）規模S〜M（2026-08-16完了）

- N12 GeoJSON: `for lon, lat in geometry["coordinates"]`が3要素座標`[lon, lat, alt]`
  （RFC 7946で合法）でValueErrorになりrun全体が異常終了する。また`type != "LineString"`
  （MultiLineString等）のfeatureを無警告でスキップし、路線が黙って欠落する。
- N10 GML: `curve.find(".//gml:posList")`が各gml:Curveの最初のposListしか読まず、
  複数の`gml:LineStringSegment`を持つCurve（JPGISで合法）の2番目以降が無警告で
  切り捨てられる。件数は合うためログから検出できず、バッファ交差率だけが縮んで
  後半区間のedgeが指定路線と判定されなくなる。
- 対応: 座標は先頭2要素のみ取得、MultiLineStringは対応または件数付きWARNING、
  posListは`findall`で複数検出時に連結またはWARNING。関東7都県の実データで
  複数セグメントCurve・非LineStringの実在数を先に計測して対応レベルを決めてよい。
- 完了条件: 3ケースのユニットテスト追加、backend全green。
- **実装結果（2026-08-16）**: N12は`_linestrings_from_geometry`でLineString/MultiLineString
  双方から座標配列を取り出し、3要素座標は先頭2要素のみ使用（RFC 7946のaltitude無視）。
  非対応typeは件数付きWARNING。N10は`find`→`findall`化し、複数posListをdocument順に
  連結（複数検出時はWARNING）。`tests/test_import_designations.py`にパーサ単体テスト6件を追加

### - [x] T73. match_designations.pyの0件時WARNING昇格＋全消しガード 規模S（2026-08-16完了）

- candidates=0/matched=0でも「マッチング完了」のINFO固定で、docs/logging.mdの
  「候補0件はWARNINGへ昇格し原因内訳を同行に含める」規約に違反。かつ0件でも
  designation_attributesを全kind分DELETE→0件INSERTするため、route_designationsが空
  （import未実行・取込失敗後）やバッファ閾値不整合の場合に、評価（trafficStress加点）と
  MVT表示のdesignationが静かに全消失する。
- 対応: 0件時はWARNING（candidates/matchedの内訳を同行に）とし、candidates=0の場合は
  DELETEを実行しない選択肢を検討。import側の0件WARNINGはT71に含む。
- 完了条件: 0件経路のログレベルと全消しガードのテスト追加、backend全green。
- **実装結果（2026-08-16）**: DELETE+executemanyを`_write_matches`ヘルパへ抽出し、
  candidates空時はDELETEごとスキップしてWARNING（`run_match`側の重複ログは削除）。
  candidatesはあるがmatched=0（全件ratio閾値未満）の場合もWARNINGへ昇格。
  `tests/test_match_designations.py`に統合テスト3件（0件時保持・置換・executemany失敗時の
  ロールバック）を追加。backend 666件green

### - [x] T74. MVT指定路線表現の見直し（粒度・重複kind・遅延構築依存）規模M・要設計判断（2026-08-16完了）

`_ROAD_SURFACE_TILE_MVT_SQL`のdesignation表現に関する3つの関連問題。T66
（save_graphのCASCADE消失）と対象が近接するため、同時に設計判断するのが望ましい。

1. **粒度不一致**: MVT側はway単位のbool_or集約（1エッジでも該当すればway全長に
   designation付与＋trafficStress+1）だが、評価側（get_designated_edge_ids→
   traffic_stress_level）はedge単位。部分該当wayでポップアップ表示値と区間評価値が
   同一地点で食い違う。整合性テストは1way≒1エッジの小規模フィクスチャのため検出しない。
2. **重複kindの欠落**: designation CASEが単一値のため、N10・N12両方に該当するway
   （幹線では十分起こる）はemergency_transportのみ出力され、凡例で「緊急輸送道路」を
   非表示にするとN12でもある区間が地図から完全に消える。
3. **遅延構築依存**: designationプロパティ（と+1補正）だけがroad_edges
   （ルート生成地点周辺のみ遅延構築）JOIN経由で導出され、他プロパティの
   osm_raw_ways自己完結という不変条件から外れている。本番では生成履歴の無いエリアの
   指定路線レイヤーが表示されず、まだら表示になる。
- 対応方針候補: ②はis_ert/is_clの2フラグをプロパティとして別々に出す。③は
  route_designations（全域投入済みのraw層）へ直接マッチする事前計算、または
  osm_way_id単位のマッチ結果テーブルを持つ（①の粒度定義の再検討と同時に）。
- 完了条件: 部分該当way・重複kind・未構築エリアの3ケースを検証するテスト／実機確認。
- **検討メモ（2026-08-16、未着手）**: T70〜T73と合わせて着手を検討したが、③の解消には
  osm_way_id単位の事前計算テーブル新設＋専用バッチ（route_designationsは全域投入済みだが
  road_edges/designation_attributesはルート生成地点周辺のみ遅延構築のため、既存の
  match_designations.pyへ相乗りできない）が要り、①（粒度再定義）・②（is_ert/is_cl分離）は
  MVTプロパティ形状の変更としてフロント側（staticAttributeLayers.tsの凡例・色分け・
  フィルタ、is_ert/is_cl同時該当時の1本の線への色の割り当て方針）の再設計を伴う。
  3点を同時に設計判断する規模M相当の変更（新テーブル・新バッチ・SQL・フロント4ファイル程度）
  と判断し、T70〜T73（データ欠損系の実害）を優先して本ラウンドでは着手を見送った。
  次に着手する際は、まず③（事前計算テーブル化）から始めると①の再定義もその上に自然に
  乗る（事前計算をedge単位ではなくway単位の交差長比で持てば、①の「any-edge」から
  「ratio-based」への改善も同時に得られる）。
- **実装結果（2026-08-16）**: ユーザー報告「指定路線が全路線・関東エリアで表示されない」の
  原因調査を契機に着手。上記検討メモどおり③から着手し①・②を同時解消した。
  - ③: `designation_attributes`のキーをedge_id（road_edges FK）からosm_way_id（osm_raw_ways
    FK）へ変更（migration `0009_designation_attributes_osm_way_id.sql`、DROP→再作成）。
    `match_designations.py`の`_MATCH_SQL`をroad_edges基準からosm_raw_ways基準へ書き換え。
    これによりルート生成履歴に関係なく全域で即時表示されるようになった。
  - ①: ③の副産物として、MVT表示（way単位bool_or集約）と評価側（旧: edge単位any-match）が
    way単位ratio-matchへ統一された。トレードオフとして、長いwayの一部だけが実際に指定路線と
    重なる場合、比率が閾値未満だとway全体が非該当になりうる点を`domain/designation.py`に
    明記した（無条件の改善ではない）。
  - ②: `_ROAD_SURFACE_TILE_MVT_SQL`のdesignation CASE式を3値化（`emergency_transport`/
    `critical_logistics`/両方該当時`both`）。フロントは`staticAttributeLayers.ts`の
    `DESIGNATION_CATEGORIES`に3件目を追加するだけで凡例・色分け・ポップアップが
    `buildCategoricalLayerDefs`経由で自動反映された（2フラグ独立レイヤー案は
    `MapLayersPanel`の1レイヤー1トグル前提を崩すため見送り）。
  - `_DESIGNATED_EDGE_IDS_SQL`（road_edges経由でedge_id→osm_way_idマッピングしてJOIN、
    呼び出し時点でroad_edgesは構築済みのためT74の対象外）・`_NEAREST_WAY_TAGS_SQL`
    （nearest.osm_way_idで直接判定）も追随。
  - road_edges再splitのCASCADE巻き添え（旧T66の懸念）はdesignation_attributesがosm_raw_ways
    FKになったことで対象外になったため、回帰テスト2件を「way単位化によりresplitの影響を
    受けない」ことを検証する新テストへ置換。
  - タイル世代v5→v6を対で上げ、`export_openapi.py`を再実行して`region-tile-config.json`を
    再生成。
  - 運用: 本番・dev DBともにmigration適用後、`match_designations.py`の再実行が必須
    （designation_attributesがDROPされ空になるため）。
- **本番適用（2026-08-16）**: dev DB適用時にmigration 0007〜0009・`match_designations.py`を
  実行したところ、本番Oracle Cloud DBには**migration 0007（route_designations/
  designation_attributes新設）自体が未適用**、`route_designations`データも**未投入**
  （`import_designations.py`が本番で一度も実行されていなかった）と判明した（T54の
  「本番データ欠損」と同種の、機能追加時にdev DBだけ整備してdev/prod環境差分に気づかない
  パターン）。対応: ①migration 0007・0008・0009を本番へ適用、②`import_designations.py`を
  本番へ実行（5,084件、3.9s、devと同数）、③`match_designations.py`を本番へ実行
  （osm_raw_ways 1,308,092件が対象、dry-run 326.7s→実行337.9s、candidates=307,888
  matched=125,971）。検証: 本番`designation_attributes`のうちroad_edges未構築
  （ルート生成未経験）のwayが**81,055件**（全体の64%）で、旧設計ではこれらが本番で
  一切表示されなかったことを裏付けた。うちN10・N12両方該当（`both`）は38,705件。
  **git push後、Renderの自動デプロイが完了するまでの間は旧コード（designation_attributes.
  edge_id参照）が新スキーマに対しUndefinedColumnErrorを出すが、region_service.pyの
  エラー握りつぶし＋空タイル返却フォールバックにより路面タイル全体が一時的に空表示になる
  だけで、ハードダウンはしない**（自己解消、Renderデプロイ完了後に正常化）。

### - [x] T75. designation kind追加の1本道整備（片側import化＋テーブル化）規模S（2026-08-16完了）

- kind集合が、正準`domain/designation.py: TRAFFIC_STRESS_DESIGNATION_KINDS`に加えて
  ①MVT生成SQL内の文字列リテラル（`road_graph_repository.py`）
  ②`match_designations.py: _KINDS`タプル ③`import_designations.py`のインラインタプル
  の計4表現に分散している（設計原則2「数値定数は片側import」違反。kind追加時にMVT側だけ
  旧2値で取り残され、整合性テストは既存2kindしか突き合わせないため検知されない）。
- また`import_designations.py`のkind→URL・ソース名・パーサの対応が3関数の平行分岐に
  分散し、いずれもelse側が暗黙にN12扱いへ倒れる（kind追加時の編集漏れが静かに壊れる。
  improvement-plan.mdで予定されているナショナルサイクルルート追加時に顕在化）。
- 対応: domainへ取込対象kind集合を定義し両バッチがimport。MVT SQLはバインド化
  （T65の事前集約JOINへのパラメータ渡し）または整合性テストの全kind網羅化。
  import側はkind→(url_template, source, member, parser)の単一テーブル`_KIND_SPECS`へ
  畳み、未知kindはKeyErrorで即死させる。
- 完了条件: kindを1箇所追加すれば全系統が追随する（追随しない箇所はテストが割れる）こと。
- **実装結果（2026-08-16）**: `domain/designation.py`へ`DESIGNATION_IMPORT_KINDS`
  （取込対象kindタプル、正準）を新設し、`TRAFFIC_STRESS_DESIGNATION_KINDS`はこれの
  frozenset化として定義（概念上は別軸だが現状は同一集合と明記）。`match_designations.py`の
  `_KINDS`ローカルタプルを廃止してこれをimport。`import_designations.py`は
  URL・source・ZIPメンバー名・パーサの3関数平行分岐を`_KIND_SPECS: dict[str, _DesignationKindSpec]`
  （kind→仕様の単一テーブル）へ統合し、`_KIND_SPECS[kind]`のKeyErrorで未知kindを即死させる形へ。
  MVT SQL（`_ROAD_SURFACE_TILE_MVT_SQL`のis_ert/is_cl 2列固定）は2kind固定の構造自体が
  T74（未着手）の設計判断待ちのためバインド化は見送り、整合性テストの全kind網羅化
  （critical_logistics側も検証対象に追加＋`TRAFFIC_STRESS_DESIGNATION_KINDS`の値そのものを
  突き合わせるドリフト検知アサーションを追加）で代替。backend 670件green

### - [x] T76. designated判定KNNの_NEAREST_WAY_TAGS_SQLへの統合 規模S〜M（2026-08-16完了）

- `get_nearest_designated_flags`は、直前の`get_nearest_surface_tags`/`get_nearest_way_tags`と
  同一のサンプル点集合に対するKNNを3本目の独立クエリ・独立ラウンドトリップとして再実行し、
  SQL骨格（WITH pts＋LATERAL＋ST_DWithin判定）も4本目のコピーになっている。
  KNN対象テーブルが属性間で異なる場合、並行道路付近でhighwayとis_designatedが別のway/edge
  由来になる不整合の可能性もある。
- 対応: `_NEAREST_WAY_TAGS_SQL`へdesignation判定列（EXISTS(designation_attributes ...)等）を
  追加し、専用SQL・専用メソッド・エンジン側の3回目の呼び出しを削除する。is_designatedは
  `traffic_stress_level`でtagsと必ず対で使われるため同居が自然。実装時にway_tags側KNNの
  対象テーブルとedge_id解決の整合を確認すること。
- 完了条件: DB統合テストで既存結果と同値、ラウンドトリップ数の削減を確認。backend全green。
- **実装結果（2026-08-16）**: `_NEAREST_WAY_TAGS_SQL`のLATERAL副問い合わせへ`e.edge_id`を
  追加し、`is_designated`列（designation_attributesへのEXISTS、既存のST_DWithinゲートに
  同居）を返すよう拡張。`get_nearest_way_tags`の戻り値を`(highway, tags)`から
  `(highway, tags, is_designated)`の3要素へ変更し、専用メソッド`get_nearest_designated_flags`・
  専用SQL`_NEAREST_DESIGNATED_FLAGS_SQL`・ファサード委譲を削除。
  `openrouteservice_engine.py`は1回のKNN結果から`flat_way_tags`/`flat_designated_flags`を
  導出する形へ変更（`_build_segment_details`のシグネチャは無変更、T78/T79側の課題として残す）。
  backend 669件green（Fake/DB統合テストとも新シグネチャへ追従）

### - [x] T77. get_designated_edge_idsの転送方式見直し 規模S・要実測（2026-08-16完了）

- `graph.edges.keys()`全件（数千〜数万ID、数百KB級のtext[]）を毎prepareでアップロードするが、
  designation_attributesの該当kind行を無フィルタで全取得しPython側で積集合を取る方が
  転送量・往復数とも安い可能性が高い（レビュー判定PLAUSIBLE。テーブルはroad_edgesの
  遅延構築範囲に比例して成長するため、行数を実測してから方式を決める）。
- ついで: `_DESIGNATED_EDGE_IDS_SQL`のDISTINCTは呼び出し側のset化と二重で冗長
  （除去は挙動不変。転送量削減目的で残すならコメント明記）。
- 完了条件: dev/本番相当の行数・転送量を実測して方式決定、採用時は前提行数をコメント化。
- **実装結果（2026-08-16、測定のうえ現状維持を決定）**: dev DBで実測（王子中心40kmbbox）
  したところ、designation_attributes該当kind行数=28,940に対し、同bbox内road_edgesは
  既に117,744件（生成済み範囲の蓄積）で、大きめのループ生成リクエストのgraph.edges.keys()は
  同オーダー（数万件）になりうると判明。どちら向きにアップロードしても転送量が大差ない規模の
  ため、代替案（無フィルタ全件取得＋Python側積集合）への切替による明確な優位は無いと判断し、
  現状の実装（edge_idsをWHERE ANYへ渡す、インデックス付きPK検索）を維持することにした。
  測定結果と判断根拠を`_DESIGNATED_EDGE_IDS_SQL`のコメントに記録（designation_attributesが
  将来大きく育つ場合は再検討する旨も明記）。ついでのDISTINCT重複除去は、1エッジが複数kindに
  該当する場合の重複行転送を防ぐ目的と判明したためコメントを追記し維持（除去しない判断）。

### - [x] T78. ORSエンジンの点属性dataclass化（平行フラット配列の解消）規模M（2026-08-16完了）

- designated_flags追加で同型の平行フラット配列が6本に達し、属性1つの追加に
  「宣言・elseデフォルト・offsetループ内append・スライス・引数・`i < len(...)`ガード」の
  同型セットを毎回コピーする構造の限界を超えた。append漏れ・順序ずれは防御的ガードが
  「データ無し」として握りつぶすため、別属性の値が別地点へ紐づく誤評価がテストを
  すり抜ける。
- 対応: 点ごとの属性を1つのdataclassへ束ね、countsによる分割ヘルパでoffset簿記を
  1箇所化する（属性追加が1フィールド追加で済む形に）。T52（JICE舗装DB）等の
  次属性追加前に実施するとコストが回収される。
- 完了条件: 挙動不変リファクタとして既存テスト無変更でbackend全green。
- **実装結果（2026-08-16）**: `_PointAttributes`dataclass（surface_tag/stop_count/highway/
  tags/is_designated/intersection_count/accident_count）と汎用`_split_by_counts(flat, counts)`
  ヘルパを新設。`evaluate_loops`は6本の平行フラット配列を1本の`flat_attributes`へ束ね、
  `_build_segment_details`の引数も6個から`attributes: list[_PointAttributes]`1個へ縮小し、
  境界外ガードも1箇所（`attributes[i] if i < len(attributes) else _PointAttributes()`）に
  集約。`tags`のデフォルトは`{}`ではなく`None`にして「repository未注入（評価スキップ）」と
  「repositoryはあるが空間マッチが範囲外（highway=None・tags={}）」の区別を保持
  （`classify_bicycle_infrastructure`が`tags={}`だと"unknown"を返しうり、None時の
  「呼び出し自体をスキップしNoneを返す」既存挙動と食い違うため、挙動不変の要件上重要な区別）。
  既存テスト無変更でbackend 669件green

### - [x] T79. _build_segment_detailsのcontext渡し化 規模S（2026-08-16完了）

- `road_graph_engine.py: _build_segment_details`が11個の位置引数を取り、うち8個は
  呼び出し側の`_RoadGraphContext`フィールドの単純展開。同型`dict[str, int]`が3つ並び、
  順序取り違えが型検査・実行時エラーで検知されない。
- 対応: contextを1引数で渡す（残りはedges・elevation_attributes・start_time程度に縮む）か、
  キーワード専用引数化。
- 完了条件: 既存テスト無変更でbackend全green。
- **実装結果（2026-08-16）**: 提案どおりcontextを1引数化。呼び出し元8個の位置引数
  （surface_attributes/stop_counts/way_tags/intersection_counts/accident_counts/
  accident_years_covered/designated_edge_ids/wind）を`context`へ集約し、関数シグネチャは
  edges・elevation_attributes・context・start_timeの4引数へ縮小。既存テスト無変更で
  backend 669件green

### - [x] T80. バッチ共通ヘルパ化（DSN変換・ダウンロード）規模S（2026-08-16完了）

- asyncpg用DSN変換（replace 3連鎖）の同一実装が4箇所（import_pbf.py・import_accidents.py・
  match_designations.py・import_designations.py）に増殖し、import_accidents.pyの
  docstring「2箇所だけのため共通化しない」の前提が崩れた。
- `_download_zip`は`_download_year`（import_accidents.py）の骨格
  （dest存在チェック→.part一時ファイル→replace→HTTPError WARNING→.part削除）の
  逐語レベル再実装。
- 対応: バッチ共通モジュール（例: `app/batch/_common.py`）へDSN変換と
  `download_to_path(client, url, dest, ...)`を抽出し全バッチから参照。
  import_runs記録パターン（現在2箇所）は3箇所目が出た時点で共通化する（今回は見送り）。
- 完了条件: 4バッチが共通ヘルパ経由になり、既存テストgreen。
- **実装結果（2026-08-16）**: `app/batch/_common.py`を新規作成し`asyncpg_dsn`・
  `download_to_path`を実装。4バッチ（import_pbf.py・import_accidents.py・
  match_designations.py・import_designations.py）すべてのDSN変換を置換、
  `_download_year`（import_accidents.py）・`_download_zip`（import_designations.py）は
  共通ヘルパへ委譲する薄いラッパーへ縮小（`_download_zip`は元々無かった取得完了ログ
  size_mb/elapsedが副次的に追加された）。テスト側も重複していたローカル`_asyncpg_dsn`を
  共通importへ置換し、`tests/test_batch_common.py`を新規作成（DSN変換1件＋
  download_to_pathの3ケースをhttpx.MockTransportでテスト）。import_runs記録パターンは
  提案どおり見送り（現状2箇所のまま）。backend 672件green（新規4件）

### - [x] T81. ORDINALITY順序復元ヘルパの集約 規模S（2026-08-16完了）

- `by_ord = {...}; return [by_ord.get(i + 1, default) for ...]`イディオムが
  `road_graph_repository.py`の6メソッド目のコピーになった。「ordは1始まり・欠落は既定値」の
  暗黙規約が分散し、SQL側変更時のオフバイワン（全属性が隣のサンプル点の値になる）の温床。
- 対応: `_chunked`と同格のモジュール内ヘルパへ集約し6メソッドを置換。
- 完了条件: 既存repository統合テスト無変更でbackend全green。
- **実装結果（2026-08-16）**: `_restore_ordinality_order(rows, count, default, value_fn=...)`
  を新設し、対象5メソッド（get_nearest_surface_tags/get_nearest_stop_poi_counts/
  get_nearest_way_tags/get_nearest_intersection_counts/get_nearest_accident_counts）を
  置換。get_nearest_way_tagsのみ4列→3要素タプルの変換が必要なため`value_fn`を渡す形。
  既存repository統合テスト無変更でbackend green

### - [x] T82. フロント カテゴリ凡例3点セットの共通ビルダー化 規模S〜M（2026-08-16完了）

- `staticAttributeLayers.ts`のDESIGNATION_*一式（interface＋LABELS＋LEGEND＋
  COLOR_EXPRESSION）がBICYCLE_INFRA_*の逐語コピーで、STOP_POI_*も同型のため
  「文字列列挙プロパティのカテゴリ→3点セット」導出ロジックの複製が3組に達した。
- 対応: `buildCategoricalLayerDefs({property, categories, unknownLabel})`的な共通ビルダーを
  新設し3組を生成へ置換（TRAFFIC_STRESS=数値キー・ACCIDENT=case式・INTERSECTION=interpolateは
  同型でないため対象外）。設計原則8（UI語彙のカタログ集約）に沿う。
- 完了条件: 生成結果が現行定義と同値であることをテストで確認、frontend全green。
- **実装結果（2026-08-16）**: `buildCategoricalLayerDefs(property, categories, unknownLabel)`
  を新設し、BICYCLE_INFRA/DESIGNATION/STOP_POIの3組（interface＋LABELS＋LEGEND＋
  COLOR_EXPRESSION）を生成へ置換（3つの個別interfaceは共通`CategoryDef`へ統合）。
  既存の`staticAttributeLayers.test.ts`（生成結果を直接検証、テスト側は無変更）24件green。
  tsc・eslintも対象ファイルでgreen

### - [x] T83. MapViewインタラクティブレイヤー配列のテーブル導出化 規模S（2026-08-16完了）

- handleClick/handleMouseMoveの2箇所に同一内容の8要素レイヤーID配列が手書き重複しており、
  `STATIC_OVERLAY_LAYERS`テーブル（T47 R-6）との三重管理。レイヤー追加時に片方を追記し
  忘れると「ポップアップは出るがカーソルが変わらない」等の非対称な劣化が検知されず残る。
- 対応: 配列を`STATIC_OVERLAY_LAYERS`から導出（elevation=ラスタを除外し
  DETAIL_LAYER_ID/ROAD_TILE_LAYER_IDを追加）。ポップアップビルダーの対応表も
  テーブルへのフィールド追加（interactive/popupBuilder）として一般化を検討。
- 完了条件: レイヤー追加時に配列の手動追記が不要になること、frontend全green。
- **実装結果（2026-08-16）**: `INTERACTIVE_LAYER_IDS`を新設し、`STATIC_OVERLAY_LAYERS`から
  elevation（ラスタタイルのため地物クリック判定が効かない）を除いたlayerId列に
  `DETAIL_LAYER_ID`/`ROAD_TILE_LAYER_ID`を加えて導出。handleClick/handleMouseMoveの
  2箇所の手書き8要素配列を`INTERACTIVE_LAYER_IDS.filter((id) => map.getLayer(id))`へ置換
  （生成順は元の手書き配列と一致することを確認済み）。ポップアップビルダーの対応表
  一般化（handleClick内の1箇所のみで複製が無いため優先度低いと判断）は見送った。
  tsc・eslintは対象ファイルでgreen、既存のMapView.segments.test.ts 3件green

### - [x] T84. MapLayersPanel説明文のカタログ集約 規模S〜M（2026-08-16完了）

- `case "designation"`は同型定型JSX（mutedHint＋renderOffHint＋staticFilterAxesFor）の
  6case目の複製で、説明文が`mapLayers.ts`のdescriptionとは別にswitch内へハードコード
  されている（文言修正時に片方だけ直り画面間で食い違う。elevationのcaseのみ
  layer.description参照で不統一）。
- 対応: カタログへpanelHint的フィールドを追加し、標準レイヤーはデータ駆動で描画、
  caseは真に特殊なレイヤー（道路情報等）のみへ縮小（設計原則8）。
- 完了条件: パネル説明文の定義箇所が1箇所になり、frontend全green。
- **実装結果（2026-08-16）**: `MapLayerDescriptor`へ`panelHint?: string`を追加し、
  trafficStress/bicycleInfra/designation/stopPoi/intersections/accidents（標準6レイヤー）と
  elevationの説明文をmapLayers.tsへ集約。`MapLayersPanel.tsx`は
  `renderStandardSectionBody(layer)`（panelHint＋renderOffHint＋staticFilterAxesFor）を新設し、
  6caseすべてをこれへ委譲するfall-throughへ縮小。road/routeのみ引き続き専用JSXを保持
  （真に特殊なレイヤー）。既存の`MapLayersPanel.test.tsx`（表示テキストを直接検証）27件green、
  tsc・eslintも対象ファイルでgreen

### - [x] T85. designation加点エンジンテストの縮小 規模S・任意（2026-08-16見送りでクローズ）

- `test_openrouteservice_engine.py`のdesignation加点テストがエンジン2個で全周生成を
  2回実行するが、非指定側（=2の確認）は`test_traffic.py: test_is_designated_defaults_to_false`
  と`default_designated=False`で走る既存エンジンテストで既にカバーされている。
  エンジンテストは8方位フル実行で高コスト。
- 対応: designated=True側1本へ縮小。ただし2値差分の対照実験としての意味もあるため任意
  （縮小しない判断も可。その場合は本タスクを「見送り」でクローズ）。
- 完了条件: 縮小する場合はスイート実行時間の短縮を確認しbackend全green。
- **判断（2026-08-16、見送り）**: 実測したところ`test_openrouteservice_engine.py`全23件が
  0.62秒、うち対象の`test_traffic_stress_reflects_designation_bonus_when_repository_injected`
  （8方位×2エンジン生成）単体は0.01秒だった。「8方位フル実行で高コスト」という前提が
  実データでは成立せず（Fakeベースのユニットテストで実I/Oが無いため）、削減しても
  スイート実行時間への効果が無いに等しい。2値差分の対照実験としての可読性（同じテスト内で
  designated=True/False双方が見える）を優先し、縮小せず現状維持を選択した。

---

## 将来の静的属性拡張に向けたUI整理検討（2026-08-16）

ユーザーから提示された外部UI/UXレビュー指摘表（🔴高5点・🟠中4点・🟡低3点）を、
将来の静的道路属性追加・分析研究に向けた投資価値の観点で検討した。指摘のうち
#1（表示/分析の役割分離）・#3（表示ON/OFFと分析利用の反映タイミング分離）・
#5（探索条件の独立UI領域）・#8（折りたたみ）・#9（表示条件/分析条件/データ詳細の分離）は
フロントUI一貫性再編（T29〜T32・T38）で既に対応済みと確認し再起票しない。
#6・#7（データの意味・凡例）はT39/T40で1〜2文の説明文と凡例を既に実装済みのため
ⓘアイコン化までは過剰と判断し見送り。#10・#11・#12（デザインシステム・説明簡潔化・
モバイル/オンボーディング）はユーザー提示の優先度どおり🟡低・ルート探索機能完成後に
先送りする。現状のコードで実際にギャップが残っている#2・#4のみをT86・T87として起票する。

### - [x] T86. 静的レイヤーのカテゴリ化〔レビュー指摘#2〕規模S〜M（2026-08-16完了）

- 背景: `mapLayers.ts`のMAP_LAYERSは`kind: static/dynamic`の2分類のみで、staticカテゴリが
  既に8種（標高図・道路情報・交通ストレス・自転車インフラ・指定路線・停止要因・交差点密度・
  事故）に達しflatな一覧のまま並ぶ（T38のアコーディオン化で縦の高さは抑えているが分類は
  されていない）。JICE舗装DB（T52、JICE返信待ち）等の追加候補も控えており、レイヤー数が
  増えるほど見つけやすさが悪化する。
- 対応: `MapLayerDescriptor`へ`category`フィールド（`roadCondition`/`trafficSafety`/
  `bicycleInfra`/`terrain`の4分類、対応方針どおりの分類・粒度）を追加し、staticの8レイヤーへ
  割り当てた（道路状態=道路情報・指定路線、交通・安全=交通ストレス・事故・停止要因・
  交差点密度、自転車インフラ、地形=標高図）。`MapLayersPanel`のグループ見出しを`kind`単位から
  この`category`単位へ変更（`STATIC_CATEGORY_ORDER`で列挙順を固定）。dynamic（route、1種のみ）は
  従来どおり単独見出しのまま。`MapOverlayControls`（地図上のチップ行）は対応方針どおりフラットな
  ままとし対象外。
- 完了条件確認: frontend全green（vitest 219件・tsc・eslint）、Playwright実機確認
  （サイドバーに「道路状態」「交通・安全」「自転車インフラ」「地形」「生成したルートの色分け」の
  5見出しが表示され、各レイヤーが想定した分類の下に属することを確認）。

### - [x] T87. レイヤーのデータ状態表示〔レビュー指摘#4〕規模S〜M（2026-08-16完了）

- 背景: 現状`MapLayersPanel`は「表示OFF」「ズーム範囲外」（road専用の`zoomWarning`）の案内は
  あるが、タイル取得失敗（T59の背景にあった502障害等）と、そのレイヤーの対象データが
  0件（T54で判明した`osm_raw_pois`未取込のような欠損）を区別する表示が無く、
  どちらも単に「何も描画されない」状態になる。事故CSV・指定路線マッチングのような
  外部データソースが増えるほど、この区別の欠如が実際の問い合わせ・混乱につながりやすい。
- 対応方針: 各静的レイヤーのタイル取得結果（MapView.tsxのsourcedata/errorイベント）を検知し、
  レイヤーごとに「OFF」「読込中」「データなし（0件）」「取得失敗」の状態を`LayerChip`・
  `MapLayersPanel`セクションへ反映する。road専用の`zoomWarning`表示パターンを他レイヤーへ
  一般化できるか、着手時に設計する。
- 完了条件: 意図的に空データ・取得エラーを発生させた状態でPlaywright実機確認し、
  各状態が視覚的に区別できることを確認。frontend全green。

**実装結果（2026-08-16）**:

- **判定ロジック**: `MapView.tsx`に純粋関数`computeLayerDataStatus`を新設（(source, source-layer)
  ごとに`getSource`/`isSourceLoaded`/`querySourceFeatures`から`loading`/`empty`/`error`を判定、
  正常時はキー自体を持たない）。road/trafficStress/bicycleInfra/designationは同じ
  `road_surface`タイルを再利用するため意図的に同じsource/source-layerを指し、
  road_edges未構築地点では4レイヤーが同時に`empty`になる（T59の遅延構築設計と整合）。
  stopPoi/intersectionsは同じ`region-poi-tiles`ソースだが別のsource-layerのため、
  T54のようにosm_raw_poisだけ未取込という片方だけの欠損を区別できる。
  取得失敗は`error`イベントで対象sourceIdを記録し、次の`sourcedataloading`
  （新しい取得サイクルの開始）まで保持する（`isSourceLoaded`がtrueに戻っただけでは
  失敗したタイル自体が再試行されたとは限らないため、それだけを解除根拠にしない）。
- **表示**: `LayerChip`に`dataStatus`props（表示ON時のみ状態ドット、loading=点滅・
  empty=中空・error=赤塗り）を追加。`MapLayersPanel`に`renderDataStatusHint`を新設し、
  road専用だった`zoomWarning`パターンを一般化（`renderStandardSectionBody`対象の6レイヤー・
  elevation・road全てで使えるようにした。roadはregionZoomTooWide中は二重表示を避けるため
  データ状態案内を抑制）。`mapLayers.ts`に`LayerDataStatus`/`LayerDataStatusByLayer`/
  `LAYER_DATA_STATUS_LABELS`を追加（カタログ集約の方針どおり文言を1箇所に）。
- **配線**: `MapView`の新規props`onLayerDataStatusChange`をpage.tsxが`useState`で受け、
  `MapLayersPanel`へ`layerDataStatus`として渡す。表示ON/OFFが変わるeffect・
  `sourcedata`/`sourcedataloading`/`error`イベントのたびに再計算し、値が変わらなければ
  コールバックを呼ばない（不要な再レンダー防止）。
- **実機確認（2026-08-16〜17）**: dev環境（localhost:3000/8000）を起動しBrowser経由で確認。
  初回はこのセッションのBrowserペインが表示されておらずWebGLフレームをコンポジットできない
  状態（`map.loaded()`が`false`のまま、`load`イベント未発火でカスタムソース未追加）で
  検証できなかったが、ユーザーにペイン表示を依頼したところ解消し、実データでの3状態確認が
  できた。
  - **データなし**: dev DBは`osm_raw_pois`が0件（T54で判明済みの既知の欠損）のため、
    「停止要因」チップに中空ドット、セクション本文に「この範囲に表示できるデータが
    ありません」が実際に表示されることを確認（road/交通ストレス等、実データがある
    レイヤーには何も出ないことも同時に確認）。
  - **取得失敗**: backendプロセスを停止した状態で未取得のタイル座標へ地図を移動させ、
    road/交通ストレス/停止要因/交差点密度/事故の5レイヤー（road_surfaceタイルを共有する
    4レイヤーが同時にerrorになる設計どおりの挙動を含む）に「データの取得に失敗しました。
    しばらくしてから再読み込みしてください」が表示されることを確認。
  - **回復の実機確認で2件のバグを発見・修正**（ユニットテストでは再現できない、実際の
    MapLibreイベント順序に起因する不具合）:
    1. バックエンド復旧後、障害中に別地点で記録した`error`が、既にタイル取得済み
       （キャッシュ済みで新規の`sourcedataloading`が発火しない）の地点へ戻っても
       解除されず「取得失敗」表示が残り続けた。`moveend`/`zoomend`
       （パン/ズーム収束時点）でも`isSourceLoaded=true`のsourceのエラーを解除する
       `clearStaleTrackedSourceErrors`を追加して解消。
    2. 1の修正確認中、実際には`road_surface`に6,273件のフィーチャーがあるのに
       「この範囲に表示できるデータがありません」のまま固定される別の不具合を発見。
       `isSourceLoaded`がtrueになる瞬間と`querySourceFeatures`が実際のフィーチャーを
       返せるようになる瞬間の間にズレがあり、そのタイミングで確定した`empty`判定を
       更新するきっかけ（sourcedataイベント）がその後発生しないケースがあった。
       `idle`（描画が落ち着いた状態）でも継続的に再計算するリスナーを追加して解消。
    修正後、同じ手順（backend停止→別地点でerror→backend復旧→キャッシュ済みの
    正常地点へ戻る）を再実行し、正しく正常状態（road等はno-message、停止要因のみ
    empty）へ回復することを確認済み。
- **テスト**: `MapView.dataStatus.test.ts`（`computeLayerDataStatus`9ケース＋
  `clearStaleTrackedSourceErrors`3ケースの計12件、フェイクmapオブジェクトで検証）、
  `MapLayersPanel.test.tsx`に4件追加（error/empty表示・OFF中の非表示・
  road regionZoomTooWide中の二重表示防止）。backend変更なし、
  frontend全235件・tsc・eslint全green。

---

## 統合レビュー対応（2026-08-16・review:all第1回）

### - [x] T88. architecture.mdの現状化〔統合レビューF-1〕規模S〜M（2026-08-16完了）

- 背景: `docs/architecture.md`は「コード変更と同一コミットで更新」ルールだが、
  8軸目（事故密度、T50）・指定路線コンフレーション機構（T51）・migration 0006/0007/0008・
  路面タイル世代v5・T59（地図タイル閲覧起点の道路グラフ構築）・静的レイヤー9系統（P0/P1含む）
  が反映されないまま約40コミット分（daef76e..HEAD）進んでいた。実際にはP0/P1（静的道路属性、
  交通ストレス・自転車インフラ・停止密度・交差点密度）自体もこの回以前から未反映だったと
  判明（統合レビューPhase 4で発覚）。
- 対応: 新設「## 7. 静的道路属性と8軸評価モデル」節で8軸の一覧・重み表・P1各軸・T50事故密度・
  T51指定路線コンフレーション・静的レイヤー3系統のタイル配信・T59バックグラウンド構築を集約。
  併せて§2ディレクトリ構成（domain/traffic.py・accident.py・designation.py・difficulty.py、
  batch/一式、infrastructure/accident_repository.py・designation_models.py、
  services/accident_service.py、migrations 0006-0008、frontend Map/staticAttributeLayers.ts・
  icons.tsx・hooks/useStoredState.ts）・§4 API（poi-tiles/accident-tilesエンドポイント追加、
  road-surface-tilesプロパティ更新）・§6データモデル（RouteSegmentDetail/RouteCandidateの
  8軸フィールド）を現状化。
- 完了条件: architecture.mdが8軸評価モデル・指定路線機構・T59・新規タイル世代を説明できる
  状態になっていること（コードとの照合はレビュー実施時点のコードを一次情報として使用）。
- 対応状況: 統合レビュー（[history/2026-08-16_all.md](../.claude/commands/review/history/2026-08-16_all.md)）
  F-1として起票、ユーザー承認のうえ本タスクとして実施・完了。

---

## T74migration未適用による交通ストレス不具合対応・凡例見える化（2026-08-16）

### - [x] T89. 交通ストレス凡例の見える化〔ユーザー報告〕規模S（2026-08-16完了）

- 発端: ユーザー報告「交通ストレスが地図に表示されなくなった」。調査したところ、T74
  （designation_attributesのosm_way_idキー化）のコードは実装済みだったが、対応migration
  `0009_designation_attributes_osm_way_id.sql`のdev DB適用と`match_designations.py`の
  再実行が未実施のままで、`_ROAD_SURFACE_TILE_MVT_SQL`が`column "osm_way_id" does not exist`
  で失敗していた（`region_service.py`のDB障害フォールバックにより空タイルへ静かに劣化、
  HTTPは200 OKのまま交通ストレス等road_surfaceタイル全系統が表示されない状態）。
  migration適用＋バッチ再実行（match=11,102件）で復旧、Playwright実機確認済み。
- 追加相談: 「そもそも交通ストレスの1〜5評価基準が分かりにくい」との指摘（実際は1〜4段階、
  凡例に「不明・他」を含め5項目並ぶため誤解されやすい）。ユーザー承認のうえ低コスト対応
  （凡例の視覚分離＋判定根拠の内訳表示）を実施し、高コストな区間クリック内訳表示
  （backendがtraffic_stress算出根拠をレスポンスへ含める必要あり）は次イテレーション見送り。
  あわせて「指定路線と交通ストレスを分ける基準」も検討: 指定路線（KSJ N10/N12）は行政指定
  という「事実」の表示、交通ストレスは道路種別・車線数・制限速度・自転車インフラ・指定路線
  該当を合成した「推定指標」であり、指定路線は交通ストレスの入力の一つ（bicycleInfraとの
  関係と同型、T62で先例あり）。指定路線かどうか自体を個別確認できるようにする価値がある
  ため統合はせず、両パネルの説明文を相互参照させる形にとどめた。
- 対応:
  - `legendFilter.ts`: `LegendEntry`へ`isFallback?: boolean`を追加。「不明・他」「対象外」
    受け皿カテゴリ（trafficStress/intersection/buildCategoricalLayerDefs経由の全カテゴリ
    軸）へ設定し、`MapLayersPanel.tsx`（区切り線＋弱調表示、CSS `.legendCheckboxRowFallback`）・
    `MapOverlayControls.tsx`（同、`.detailRowFallback`）の両凡例UIで数値/順序段階と
    視覚的に分離。
  - `mapLayers.ts`: `MapLayerDescriptor`へ`panelHintDetail?: readonly string[]`を追加し、
    trafficStressのpanelHintを「4段階（1=快適〜4=ストレス大）」明記へ書き換え、
    `domain/traffic.py: traffic_stress_level`の加点/減点ロジック（基準値・自転車道-2/
    レーン-1・速度±1・車線数+1・指定路線+1・motor_vehicle=no固定1・不明の理由）を
    箇条書きで追加。designationのpanelHintにも「別レイヤーとして表示している理由」を追記し
    相互参照させた。
  - `MapLayersPanel.tsx`: `renderStandardSectionBody`が`panelHintDetail`を`<ul>`で描画。
- 完了条件: frontend全テストgreen（vitest 214件・tsc・eslint）、Playwright実機確認
  （サイドバー・地図上▶ポップオーバー双方で区切り線・箇条書きの表示を確認）。

### - [x] T90. 交通ストレスの区間別判定内訳表示〔ユーザー提案C案〕規模M（2026-08-16完了）

- 背景: T89の凡例改善（凡例の視覚分離・全体的な判定基準の箇条書き）は「1〜4段階のどれが
  何を意味するか」という一般論までしか説明できない。「なぜこの道路が具体的にこのストレス
  値なのか」という個別区間の内訳（例:「県道・制限速度50km/h→ベース4、専用レーンなし、
  指定路線非該当で+1なし」）までは分からないため、地図上の道路をクリックすると内訳を
  ポップアップ表示する案（T89検討時のC案）が挙がった。
- 対応: 検討していた(b)方式（クリック時に別APIでタグ取得）を採用。ただし当初懸念していた
  「SQL/JS二重実装」は発生させていない——`domain/traffic.py`に`traffic_stress_breakdown`を
  新設し、判定ロジック（ベース値・cycleway/maxspeed/lanes/designation各補正・
  motor_vehicle=no固定1）を内訳付きで1箇所に実装、`traffic_stress_level`はその`level`だけを
  返す薄いラッパーへ縮小した（Python側の実装は引き続き1本、SQL側`_ROAD_SURFACE_TILE_MVT_SQL`の
  CASE式との整合は既存の整合性テストで担保）。新規API
  `GET /api/region/traffic-stress-breakdown?osm_way_id={id}`
  （`RegionService.get_traffic_stress_breakdown`）が該当行を返す。フロントは道路クリック時の
  ポップアップへ「内訳を見る」ボタンを追加し、押下時のみオンデマンド取得（クリック連打での
  レート制限消費を避ける）。
  - **実装中に発見した設計変更**: 当初はクリック地点の緯度経度から最近傍道路を空間マッチで
    引く設計を予定していたが、実機（Playwright）検証で、交差点付近など道路が近接する場所では
    ポップアップの表示値（実際にクリックされた道路のtraffic_stress）と内訳ボタンの計算値
    （空間マッチが拾った別の道路）が食い違う不具合を発見した。クリック地点の緯度経度ではなく
    `osm_way_id`（クリックされたMVTフィーチャーそのものが持つ識別子）の完全一致で引き直す
    設計へ変更し、この不整合を構造的に解消した。`_ROAD_SURFACE_TILE_MVT_SQL`へ`osm_way_id`
    プロパティを追加（路面タイル世代v6→v7）、`AttributeRepository.get_way_tags_by_osm_way_id`
    （完全一致1行取得）を新規実装。
- 完了条件確認: backend 688件（新規9件含む: `traffic_stress_breakdown`のdomain単体テスト、
  `RoadGraphRepository.get_way_tags_by_osm_way_id`のDB統合テスト、`RegionService`・
  APIルータのテスト）・frontend 219件・tsc・eslint全green。DB照会・HTTPエンドポイント直接
  呼び出しで`osm_way_id`→内訳の一貫性を確認したうえ、Playwright実機確認（交通ストレス
  レイヤーON→道路クリック→ポップアップの表示値と「内訳を見る」ボタン押下後の最終値が
  一致することを確認）。
- 関連: T89（凡例の視覚分離・全体的な判定基準の説明）の追加相談として起票。

---

## 統合レビュー対応フォローアップ（2026-08-16・review:all第1回の残り指摘）

### - [ ] T91. MapView.tsx閾値監視の再設定〔統合レビューF-3〕規模S

- 背景: 複雑度平衡レビュー第4回R-6で「静的レイヤー+2種 or MapView 1,200行到達」を閾値に、
  到達時は決めておいた2点（宣言的レイヤー登録・useStoredState抽出）のみ実施し分割はしない、
  という契約を置いていた（T47で実施）。統合レビュー時点（MapView.tsx 1,299行）で両条件が
  成立し約束の2点は消化済みと確認されたが、次の閾値が定義されないままだった。2026-08-16時点で
  MapView.tsxはさらに1,378行まで増加しており（T54のPOI/交差点密度レイヤー等）、監視が空白の
  まま静的レイヤー追加が続いている。
- 対応: `docs/complexity-review-2026-08-16.md`・`.claude/commands/review/context.md`のKEEP記載を
  「消化済み」へ更新し、新しい閾値を定義する（例:「次の静的レイヤー追加時に、MapViewに残る
  手書きのソース/レイヤー登録ブロックのテーブル駆動化を検討」「1,500行で再評価」等、T86の
  カテゴリ化と同じ発想で束ねるのが自然）。コード分割自体が必要かは着手時に判断し、不要なら
  基準ファイルの更新のみで完了させる。
- 完了条件: 新しい閾値・監視条件がKEEP記載として明文化されていること。
- 対応状況: 統合レビュー（[history/2026-08-16_all.md](../.claude/commands/review/history/2026-08-16_all.md)）
  F-3として起票。2026-08-16時点でMapView.tsx 1,378行（レビュー時点比+79行）まで増加を確認済み。
- **未着手のまま悪化継続**（統合レビュー第2回、2026-08-17）:
  [history/2026-08-17_all.md](../.claude/commands/review/history/2026-08-17_all.md) F-3で再確認。
  MapView.tsxは1,664行（T87分含む作業ツリー、前回確認比+286行）まで増加。今回増分自体は
  単一責務（データ取得状態表示）に閉じており品質悪化はないと判定。新閾値案（「1,800行 or
  STATIC_OVERLAY_LAYERS 10種到達」）を`/review:improve`経由での基準反映候補として提示。

---

## 交通ストレス判定ロジックの精緻化（2026-08-17）

### - [x] T92. 交通ストレス判定を実データに基づき精緻化＋評価軸の合成基準を明文化 規模M（2026-08-17完了）

- 発端: ユーザー実機フィードバック「指定路線ならほぼすべて赤色（4/4）。実態にあった形で
  もう少し評価して」。
- 調査: 実データ（関東本土、`osm_raw_ways` 39,878件・指定路線該当11,102件）で検証。
  - 指定路線該当の83.3%（9,251件）が最終値4/4。うち56%（6,225件）は`primary`/`secondary`/
    `trunk`がいずれもbase=4で揃っており、指定路線の+1補正があってもなくてもどのみち4に
    なる「補正が実質無意味」なケースだった。
  - 一方、既に収集済みのタグの中に判定へ一切反映されていない差別化要因があった:
    `cycleway=shared_lane`（自転車と共有の車線表示）が指定路線対象道路の15.6%（1,239件）に
    付いているが「表示なし」と同じ0扱い、`lanes=1`（対面通行1車線）が319件あるが車線数の
    軽減側補正が存在しなかった（4車線以上の+1のみ）。
  - `secondary`（県道級）は実データ上も2〜3車線・40〜50km/h帯が主流で、`primary`/`trunk`
    （国道級・幹線）と一律base=4は実態と乖離。`primary`/`trunk`は現実にも最もストレスが
    高い区間であるため据え置き。
- 追加相談: 「信号密度（停止要因）も交通ストレスへ合成できないか」という提案を受け、
  合成すべきか独立軸のままにすべきかの判断基準を整理した。基準:
  **交通ストレスへ合成するのは「この区間で自動車とどれだけ近く・速く・多く接するか」という
  同一の構造を推定する手がかりに限る（道路種別・車線数・制限速度・自転車インフラ・指定路線、
  T89で指定路線に適用した基準と同型）。信号・一時停止の密度や交差点密度は「立ち止まる
  頻度・判断ポイントの多さ」という質的に別の負担であり、ユーザーが独立に重み調整したい
  対象（`stop_weight`/`intersection_weight`）でもあるため合成しない。** 事故密度も
  タグからの推測ではなく実測の結果指標であり性質が異なるため対象外。この基準を
  `domain/traffic.py: traffic_stress_breakdown`のdocstringへ明文化した。
- 対応:
  - `backend/app/domain/traffic.py`: `TRAFFIC_STRESS_BASE_BY_HIGHWAY`の`secondary`/
    `secondary_link`を4→3へ。`traffic_stress_breakdown`のcycleway補正へ
    `shared_lane`/`share_busway`（-1、`lane`と同じ扱い）、車線数補正へ`lanes<=1`（-1、
    4車線以上の+1と対称）を追加。
  - `backend/app/infrastructure/road_graph_repository.py`: `_ROAD_SURFACE_TILE_MVT_SQL`の
    CASE式を同じ条件で更新（SQL⇔Python二重実装、test_road_graph_repository.pyの
    整合性テストで担保）。
  - 試算（DB実データへ提案ロジックを適用）: 指定路線の4/4割合が83.3%→78.3%、全道路網では
    24.4%→21.4%に低下を確認。
  - UI説明文をレイアウトごとの粒度で更新: `mapLayers.ts`の`panelHintDetail`（サイドバー
    「地図の見え方」設定画面・地図上▶詳細パネルの両方が参照する共通の箇条書き、基準値・
    各補正の説明を新ロジックへ更新し「合計が範囲を超えたら丸める」旨と停止要因/交差点との
    切り分けを追記）、`MapView.tsx`の区間別内訳ポップアップ（T90機能。冒頭に4段階の説明、
    「合計 4 +1 = 5 → 上限の4に丸め」のように数式と丸めを明示、個別のタグ内容は主行の
    自転車インフラ表示等に委ねポップアップ側は簡潔な数値のみに留める）。
- 完了条件: backend 694件（新規11件含む: secondary基準値・shared_lane・lanes<=1の単体
  テスト、SQL整合性テストへの新規fixture2件）・frontend（MapLayersPanel既存テスト35件が
  更新後の文言でも通過することを確認）全green。

---

## 統合レビュー対応フォローアップ（2026-08-17・review:all第2回の指摘）

[history/2026-08-17_all.md](../.claude/commands/review/history/2026-08-17_all.md)
（統合レビュー第2回。ユーザー指示によりリポジトリ全体を横断確認）の指摘に対する実行計画。

### - [x] T93. 路面タイルキャッシュ世代の対上げ〔統合レビューF-1〕規模S（2026-08-17完了）

- 背景: T92で`_ROAD_SURFACE_TILE_MVT_SQL`の`traffic_stress`判定ロジック（secondary系base値
  4→3、shared_lane/share_busway・lanes<=1補正）を変更したが、`ROAD_SURFACE_TILE_VERSION`の
  対上げを失念していた（T70に続き同型のミス2回目）。`tile_cache.py`にTTLは無く手動クリアでしか
  失効しないため、T92以前にキャッシュ済みのタイルは古いtraffic_stress値を返し続け、
  地図の色表示とT90の内訳ポップアップ（DBから毎回再計算）が食い違いうる状態だった。
- 対応: `region_service.py`の`ROAD_SURFACE_TILE_VERSION`を`"7"`→`"8"`へ（プロパティ構成は
  不変、世代のみ更新）。`regionApi.ts`側の対応定数も`"8"`へ。`export_openapi.py`を再実行し
  `region-tile-config.json`を再生成（`openapi.json`・`api.d.ts`は内容不変を確認）。
  `docs/architecture.md`（§4路面タイルプロパティの現行世代表記、§7世代履歴）を追従更新。
  `regionApi.test.ts`のハードコード期待値（`?v=7`）を`?v=8`へ修正（ドリフト検知テスト本体は
  生成物参照のため無修正で正しく機能）。
- 完了条件: backend 694件・frontend 243件（いずれも単独実行）・tsc・eslint全green。
  本番デプロイ後は`POST /api/basemap/refresh`相当のキャッシュクリアが別途必要
  （デプロイ手順側の申し送り、コード対応はここまで）。

### - [x] T94. `RegionService.get_traffic_stress_breakdown`のログ方針統一〔統合レビューF-2〕規模S（2026-08-17完了）

- 背景: 同クラスの`get_road_surface_tile`/`get_poi_tile`は`log_external_call`＋WARNING＋
  グレースフルデグレードで統一されているが、T90新設の`get_traffic_stress_breakdown`だけ
  素のDB呼び出しで、対応するtry/exceptも無い。DB例外時はミドルウェアがERRORとして捕捉するため
  「エラーは常時出す」大原則には違反しないが、`/api/debug/stats`のカテゴリ別統計に計上されず
  運用調査の精度が落ちる。
- 対応: `log_external_call("region:traffic-stress-breakdown", osm_way_id=...)`で囲み、
  DB例外はWARNING＋`None`フォールバック（レスポンス契約`TrafficStressBreakdown | None`と
  自然に整合、`get_road_surface_tile`等と同じグレースフルデグレード方針）へ統一。
  フィールド名は`"result"`ではなく`"lookup"`にした（`"result"`だと`log_external_call`自身が
  `fields["result"]=="error"`を見て二重にWARNINGを出してしまうため。`_tile_from_repository`が
  `"postgis"`という専用キーを使っているのと同じ理由）。
- 完了条件: `FakeRegionRepository.get_way_tags_by_osm_way_id`にエラー注入対応を追加し、
  DB障害時にNoneへ安全側に倒れる回帰テストを追加（`test_traffic_stress_breakdown_db_error_returns_none`）。
  backend 695件（新規1件）全green。

### - [x] T95. architecture.md §7対称メソッド列挙の追記〔統合レビューF-4〕規模S（2026-08-17完了）

- 背景: `docs/architecture.md`§7の`AttributeRepository`対称メソッド一覧に、T90で新設した
  `get_way_tags_by_osm_way_id`（osm_way_id完全一致1行取得、`get_nearest_*`とは別系統）が
  含まれていない。API仕様・タイル世代・目的は既に別箇所で文書化済みのため実害は軽微。
- 対応: 対称メソッド列挙の直後へ「`get_way_tags_by_osm_way_id`（T90、osm_way_id完全一致の
  1行取得）はこの対に属さない別系統で、区間別交通ストレス内訳API専用」を追記した。
- 完了条件: docs追記のみ。

---

## 交差点密度レイヤーの地図可視化撤去（2026-08-17・ユーザー判断）

### - [x] T96. 交差点密度を地図の独立可視化レイヤーから撤去（フロントのみ）規模S（2026-08-17完了）

- 背景: ユーザーが実利用のうえ「道が何本交わっているかは地図の道路網を見れば分かり、
  独立レイヤーとして可視化する意味が薄い」と判断（信号・踏切等の停止要因は種別が
  道路の見た目から読み取れないため引き続き可視化する価値ありと判断、停止要因レイヤーは維持）。
  ルーティング材料（`intersection_weight`評価軸、`get_intersection_counts`/
  `get_nearest_intersection_counts`）は完全に別コードのため触れない。
- 対応: フロントのみ変更（ユーザー選択、バックエンドは次項T97まで意図的に据え置き）。
  `mapLayers.ts`のカタログから`intersections`エントリを削除、`MapView.tsx`の
  `ensureIntersectionLayer`・`INTERSECTION_LAYER_ID`・`INTERSECTION_SOURCE_LAYER`・
  ポップアップ・`STATIC_OVERLAY_LAYERS`/`LAYER_DATA_SOURCES`エントリを削除、
  `staticAttributeLayers.ts`の`INTERSECTION_COLOR`/`INTERSECTION_LEGEND`/
  `INTERSECTION_RADIUS_EXPRESSION`・絞り込み軸エントリを削除、`icons.tsx`の
  `IntersectionIcon`・`MapOverlayControls.tsx`のアイコン対応・`MapLayersPanel.tsx`の
  switch分岐・`page.tsx`のprops配線を削除。バックエンドのpoi-tiles MVT配信
  （`_POI_TILE_MVT_SQL`のintersectionレイヤー部分）は停止要因と同一SQL関数内にあり
  変更コスト・リスクが非対称に大きいため今回は触れない（T97参照）。
- 完了条件: backend/frontendとも全テストgreen（バックエンド無変更）。実機確認で
  地図上・サイドバーとも交差点密度チップ/セクションが表示されず、他レイヤー
  （特に停止要因・道路情報）に影響が無いことを確認。

### - [ ] T97. バックエンドpoi-tiles配信から交差点密度レイヤーを削除 規模S — トリガー: 次にpoi-tiles配信のSQL/region_service.pyを変更するタイミング

- 背景: T96でフロントの交差点密度可視化を撤去した後も、バックエンドは
  `_POI_TILE_MVT_SQL`（`road_graph_repository.py`）で引き続きintersectionレイヤーを
  MVTへ焼き込んでいる（停止要因POIと同一SQL関数内で`||`結合しているため、
  T96単独では触れなかった。ユーザー承認済みの判断）。フロントが二度と参照しないため
  死荷重だが、単独では変更コストに見合わないと判断し、次にこのSQL・
  `region_service.py`のpoi-tiles配信部分を触る機会にまとめて片付ける。
- 対応（着手時に実施）: `_POI_TILE_MVT_SQL`からintersectionレイヤーの`COALESCE(...)`枝・
  `bindparam("intersection_layer", ...)`を削除し停止要因のみのクエリへ簡素化、
  `vector_tile.py`の`INTERSECTION_LAYER_NAME`・`region_service.py`経由で
  `region-tile-config.json`が書き出す`poi.intersection_layer_name`、
  `domain/traffic.py`の`INTERSECTION_DEGREE_THRESHOLD`（※`get_intersection_counts`等
  ルーティング材料が引き続き使うため削除しない、MVT専用の記述だけ整理）を確認して
  不要なら削除する。`regionApi.test.ts`等に残るintersection関連のドリフト検知テストが
  あれば併せて整理する。POI_TILE_VERSIONの世代を上げる（T93と同じ理由）。
- 完了条件: backend/frontend全テストgreen、`/api/region/poi-tiles`のレスポンスから
  intersectionレイヤーが消えていることを確認。

---

## 夜間のOpen-Meteo 502緩和（2026-08-17・別セッション作業の遡及記録）

### - [x] T98. 候補間リクエスト集約による夜間の天候取得502緩和＋失敗理由の診断情報追加 規模M（2026-08-17完了、遡及起票）

- 経緯: 本タスクは別セッションが着手・完了・コミット（`2cc7f44`）まで実施していたが、
  T番号の付与・本ファイルへの記録が漏れていた（「1タスク=1コミット・T番号管理」規約からの
  逸脱）。統合レビュー系の作業をしていた別セッションが`docs/improvement-plan.md`を読み直す
  過程で発覚し、遡及的に起票・記録する。
- 背景: 周回ルート生成は8候補（方位）ぶんの風評価をほぼ完全並列実行しており、素朴には
  候補数ぶんのOpen-Meteo呼び出しがほぼ同時発火する。本番の共有送信元IPでこれが429常態化・
  夜間帯の502の一因になっていた。
- 対応:
  - `backend/app/services/weather_service.py`: `WeatherService.prefetch(points)`を新設
    （複数地点の予報を`get_forecast_many`でまとめて1回取得しキャッシュへ先読み、結果は
    使い捨て）。
  - `backend/app/services/wind_service.py`: `WindService.prefetch(points_per_candidate)`を
    新設（候補ごとのサンプル点を合流させ`WeatherService.prefetch`へ1回だけ委譲）。
  - `backend/app/services/openrouteservice_engine.py`: 候補群を並列評価する前に
    `WindService.prefetch`を呼び、後続の候補ごとの`get_wind_profile`呼び出しがキャッシュ
    ヒットしHTTPを発生させないようにする。
  - `backend/app/infrastructure/debug_log.py`: `/api/debug/stats`へ失敗理由を推測できる
    情報（`error_types`内訳、`last_error_type`/`last_error_at`、`last_success_at`、
    `retried_calls`、`stale_fallback_used`）を追加。`basemap_client.py`・
    `elevation_client.py`・`overpass_client.py`・`weather_client.py`が新フィールドへ追従。
  - フロント: `SystemStatusPanel.tsx`の外部呼出サマリへ「最終失敗」列とホバー内訳を追加、
    `debugStatsApi.ts`が新フィールドを型に反映。
  - `docs/architecture.md`（天候の行、§4 `/api/debug/stats`のレスポンス例）へ追従済み
    （コミット本文に含まれていたため現状化自体は漏れていなかった）。統合レビュー側で
    「候補間リクエスト集約」という挙動変更自体の説明が外部サービスのデータフロー節に
    無かった点のみ追記した。
- 完了条件（コミットメッセージ・diffから確認）: `test_debug_log.py`・
  `test_weather_service.py`・`test_wind_service.py`・`test_openrouteservice_engine.py`・
  `SystemStatusPanel.test.tsx`・`debugStatsApi.test.ts`に新規テスト追加、17ファイル
  370行追加・20行削除。個別のテスト総件数はこのセッションでは未計測（次回の全体テスト実行時に
  確認すること）。

---

## OSM追加属性の活用検討（2026-08-17・別ブランチ作業をmasterへ統合、番号振り直し）

[static-road-attributes-plan.md](static-road-attributes-plan.md)のタグ棚卸し・実測カバレッジ
（関東全域131万way、`measure_tag_coverage.py`）をもとに、現在地図に出ていないOSM由来情報を
実データ充当率込みで再ランク付けし、ユーザー承認を得た4件を起票する。

**経緯（番号振り直しの理由）**: 本節は別ブランチ
（`origin/claude/osm-roadbike-map-features-1yn5yi`、コミット`0f1f952`、2026-08-16 16:40 UTC）で
先に「T96〜T99」として起票・ユーザー承認済みだった内容だが、そのブランチが分岐した後の
masterで別件（交差点密度撤去・Open-Meteo 502緩和等）にT96〜T98を使ってしまい、番号が衝突した。
ブランチはmasterへ未マージのまま残っていたため、内容を確認のうえT99〜T102へ振り直して
masterへ統合する（コード変更は無く、元コミットもdocsのみ）。

ランクで上位に挙がった「name/refのMVT焼き込み」（name 8.3%、UI表示用途）は元のブランチと同じく
今回のスコープから除外し、static-road-attributes-plan.md §3.1の未着手項目として引き続き据え置く。

### - [x] T99. 自転車歩行者道の取込スコープ拡張〔static-road-attributes-plan.md §2.1/§3.1-1〕規模M（2026-08-17完了）

- 背景: 現在の取込プロファイルは`highway=path/footway`を取込対象外としており、河川敷等でよく
  見る自転車歩行者共用道（日本のサイクリングロードに多い形態）が地図・評価の対象から漏れている。
  static-road-attributes-plan.md §2.1で有用性★★★★☆として採用判断済み（P1）だが未着手のまま。
- 対応: `import_profile.yaml`へ`shared_pedestrian_ways`ルール（`highway=path/footway`かつ
  `bicycle=yes/designated/permissive`のAND条件）を追加。`domain/traffic.py:
  classify_bicycle_infrastructure`の`shared_pedestrian`分類（分類ロジック自体は実装済み）に
  実データが流れるようにする。取込コストがゼロだったため`segregated`タグ（歩行者と物理分離
  されているか）も`ALLOWED_WAY_TAGS`へ追加した（T102の実測を待たず含めた。分類ロジックへの
  反映自体はT102の判断待ちで見送り）。
  **YAMLの罠**: `bicycle: [yes, ...]`と無引用で書くとYAML 1.1のデフォルト解決規則で
  `yes`がブール値`True`と解釈され`ProfileError`になる（`"yes"`と引用符必須）。テスト
  （`test_import_profile.py::test_shared_pedestrian_ways_match`）が実際にYAMLをロードして
  検証するため、この罠はテストで検知される形になっている。
- 完了条件（コード側、2026-08-17完了）: `matching_rule`の単体テスト・`osm_way_to_way_spec`の
  `segregated`保持テストを追加。backend 713件全green。
- **本番再取込み（2026-08-17完了）**: `backend/data/pbf/kanto-latest.osm.pbf`をユーザー承認のうえ
  本番Oracle Cloud DBへ再取込み（事前にdry-runで`matched_ways=1,329,632`等を確認したうえ実行、
  非破壊的なCOPY→INSERT ON CONFLICTのUPSERTのため既存データへの影響なし）。
  run_id=5、ways=1,329,632・nodes=147,291・pois=332,294（67チャンク、db_size_mb=2004、
  elapsed=904.0s、エラーなし）。本番DBへ直接クエリして反映を確認: `shared_pedestrian_ways`
  ルールに該当するway（highway=footway/path AND bicycle可）17,584件（T102のカバレッジ実測時の
  「その他」グループ件数と完全一致）、うち`segregated`タグ保持5,000件（約28.4%、T102実測どおり）。
  road_nodes/road_edges（ルーティング用派生グラフ）は既存設計どおり該当エリアへの初回アクセス時に
  遅延構築されるため本タスクの範囲外。

### - [x] T100. `bicycle=no`のHard Constraint化＋`oneway:bicycle`例外の解釈〔static-road-attributes-plan.md §3.1-2/3〕規模S〜M（2026-08-17完了）

- 背景: `bicycle`タグ自体はP0で取込・自転車インフラ分類に使用済みだが、`bicycle=no`
  （自転車通行不可）が経路探索のHard Constraintへ未反映で、実際は通れない区間を提案しうる。
  `oneway:bicycle`例外（自転車は一方通行規制の対象外、等）もP0でタグ自体は保持済みだが
  未解釈のまま（`osm_adapter.py`のコメントで意図的に先送りと明記）。関連する2つの未反映を
  まとめて1タスクとする（direction/access判定という同じ層の変更のため）。
- 対応:
  - `domain/evaluation.py: is_edge_allowed`に`way_tags`引数を追加し、`bicycle=no`のway全体を
    Hard Constraintで除外する条件を追加（`DISALLOWED_HIGHWAY_TYPES`と同じ「除外」扱い、
    `way_tags=None`＝データ未取得時は既存のhighway不明時と同じく許可する方針を踏襲）。
    `compute_edge_cost`の唯一の呼び出し箇所を更新するだけで済んだ（`way_tags`は
    trafficStress/bicycle_infra評価で既に受け取り済みのため新規配線不要）。road_graphエンジン
    （`EvaluationService.evaluate_graph`）は既にway_tagsを渡しているため自動的に有効になる。
    openrouteserviceエンジンは`compute_edge_cost`自体を呼ばない（外部APIが探索するため
    `DISALLOWED_HIGHWAY_TYPES`と同じくroad_graphエンジン限定の機能、既存の非対称のまま）。
  - `osm_adapter.py`に`_resolve_direction(tags)`を新設。`oneway:bicycle`に値があれば
    （forward/backward/no）`oneway`本体より優先し、無ければ`oneway`にフォールバックする
    （現実のcontraflow cycling表現、`oneway=yes`+`oneway:bicycle=no`＝車は一方通行だが
    自転車は両方向通行可、が代表例）。PBF取込バッチもOverpass経路と同じ`osm_adapter.py`を
    経由するため（import_pbf.py冒頭コメント参照）、新規の二重実装は発生していない。
- 完了条件: `bicycle=no`区間が経路探索候補から除外されることを単体テストで確認
  （`is_edge_allowed`5件＋`compute_edge_cost`1件）。`oneway:bicycle`の例外分岐も単体テスト
  6件で確認（優先関係・大文字小文字/空白耐性・フォールバック・不明値時の挙動）。
  backend 725件（新規12件）全green。
- 備考: 本タスクの完了条件はコード・テストの範囲で完結しており（T99/T102と異なり実データ
  再取込みは完了条件に含まれない）、DBアクセス/PBFファイルなしで完了できた。

### - [ ] T101. 補給・休憩ポイントPOIレイヤー〔static-road-attributes-plan.md §2.3〕規模M

- 背景: 停止要因POI（信号・横断歩道等）・交差点密度は`osm_raw_pois`テーブル＋MVT機構で実装済み
  （T54）。同じ機構に、ロードバイクの実用性に直結する補給・休憩系POI（`shop=convenience`,
  `amenity=vending_machine/toilets/drinking_water/bicycle_parking`）を相乗りさせる。
- 対応: `import_profile.yaml`にnode取込ルールを追加（`osm_raw_pois.kind`へ`convenience`/
  `vending_machine`/`toilets`/`drinking_water`/`bicycle_parking`等を追加）。新テーブルは不要
  （既存`kind`カラムで種別管理）。表示は`stopPoi`と同様に独立レイヤーとして`mapLayers.ts`へ
  1エントリ追加、種別ごとのアイコン・色分け。数が多い自販機はズーム制限を個別に検討。
  評価ロジック（Edge Cost等）への組み込みは範囲外、P0の停止要因POIと同じく表示のみ。
- 完了条件: `measure_tag_coverage.py`で各タグを事前実測し、極端に低い種別（未確立タグの道の駅・
  サイクルステーション等は元々対象外）を除外した上で、少なくとも1種別（コンビニを推奨）が
  地図上に表示されることをPlaywrightで確認。

### - [x] T102. 街灯・分離歩道・バリアタグのカバレッジ実測と採用可否判断〔新規候補〕規模S（2026-08-17完了）

- 背景: `lit=*`（街灯の有無。早朝/夜間走行の安全性判断に有用）・`segregated=yes/no`
  （自転車歩行者道の歩車分離、T99と関連）・`barrier=gate/bollard`（河川敷サイクリングロード等の
  車止め、通行可否判定に影響）は、既存のタグ棚卸し（static-road-attributes-plan.md）でまだ
  評価対象に入っていない。
- 対応（コード）: `backend/scripts/measure_tag_coverage.py`に`CANDIDATE_WAY_TAGS`（`lit`/
  `segregated`、既存`CoverageCounter`でway取込対象への付与率を計測）・`CANDIDATE_NODE_TAGS`
  （`barrier`）を追加。`barrier`はnode属性かつ取込プロファイルに対応ルールが無く「対象母集団」が
  取れないため、新設`NodeTagCounter`で値ごと（`barrier=gate`/`barrier=bollard`等）の生カウントの
  み報告する形にした。単体テスト追加、backend 713件全green。
- **実測（2026-08-17、`backend/data/pbf/kanto-latest.osm.pbf`、対象way 1,329,632件）**:
  - `lit`: 全体1.1%（幹線4.8%）
  - `segregated`: 全体0.6%だが、T99で新規取込した自転車歩行者道（highway=footway/path AND
    bicycle可）に限ると**28.4%**
  - `barrier`（node、生カウント）: bollard 21,975・kerb 9,488・gate 8,535・cycle_barrier
    3,980・toll_booth 1,271件（以下ロングテール）
  - 比較対象: 既採用`smoothness`は同条件で0.2%、P2据え置き確定済み`width`/`shoulder`は
    0.4%/0.0%
- **判断**（詳細は[static-road-attributes-plan.md](static-road-attributes-plan.md) §2.5）:
  `lit`・`segregated`とも既採用tagの実測水準を上回り**採用推奨**（`segregated`は特に
  自転車歩行者道内28.4%という対象を絞った濃度が高い）。`barrier`も件数規模から**採用推奨**だが、
  lit/segregatedと異なり対応する取込ルールが無いため実装は別タスクとして起票する
  （stop_inducing_highway_nodes等と同じnode取込機構への相乗りを想定）。
- 完了条件: 3タグの実測値が`static-road-attributes-plan.md`に記載され、それぞれ採用/見送りの
  判断が下されていること（実装自体は本タスクの範囲外）→ 達成。`lit`/`segregated`は取込コストが
  ゼロ（既存tags jsonbへ相乗り、再取込は必要）だったため、判断と同時に`ALLOWED_WAY_TAGS`へ
  追加した（`segregated`はT99側で先行済み、`lit`は本タスクで追加）。評価軸・表示への反映
  （`classify_bicycle_infrastructure`等）は別タスクで検討。`barrier`は新規node取込ルールが
  必要なため実装は別タスクとして今後起票する。backend 726件全green。

---

## 「地図の見え方」表示トグル誤操作バグ修正（2026-08-17・ユーザー報告）

### - [x] T103. MapLayersPanelの「絞り込みを一括クリア」出現/消失によるレイアウトシフト誤操作を修正 規模S（2026-08-17完了）

- 発端: ユーザー報告「表示、非表示を切り替えられない。非表示にしようとしたら一瞬ですぐ表示になる」。
  ローカルdevビルドの自動操作では終始再現せず、本番サイト（Render）へPlaywrightで直接接続して
  調査。ユーザーからの「一括クリアボタンを一度押すとそれで再現しない？」という手がかりを受け、
  「絞り込みを一括クリア」ボタン操作前後でレイヤー表示トグルのbounding boxを実測したところ、
  Y座標が最大25px変動することを確認した。
- 原因: `MapLayersPanel.tsx`の「絞り込みを一括クリア」ボタンが`{hasHiddenFilters && (...)}`の
  条件付きレンダリングで出現/消失しており、出現・消失のたびにパネル内の後続要素
  （レイヤーの表示トグル等）が上下にずれる。実機で「消える直前・直後にクリックすると、
  ずれた先にある別要素（凡例チェックボックス等）に当たる」誤操作を`document.elementFromPoint`で
  実測確認した（ボタンが消えた直後、以前レイヤートグルがあった座標には路面種別の凡例チェック
  リストが来ていた）。
- 対応: ボタンを常時マウントし、`hasHiddenFilters`に応じて`disabled`・`tabIndex=-1`・
  `aria-hidden`・CSSの`visibility:hidden`で見た目と操作性のみを切り替える形へ変更
  （`display:none`や条件付きレンダリングは高さが0になり後続要素がずれるため使わない）。
  `aria-hidden`により`getByRole`等のアクセシビリティベースのクエリからは従来どおり除外される
  （既存テストは無修正で通過することを確認）。
- 完了条件: 修正後、同じ手順（絞り込み1件非表示化→一括クリア→レイヤートグル位置を実測）で
  Y座標が完全に不変であることをPlaywrightで確認。DOM常駐化を固定する回帰テストを追加。
  frontend 236件・tsc・eslint全green。

### - [x] T104. 地図上の凡例内訳パネルで長いラベルが末尾ごと見切れる不具合を修正 規模S（2026-08-17完了）

- 発端: ユーザーがモバイル実機のスクリーンショットを提示。地図上の指定路線レイヤーの凡例内訳
  ポップアップ（`MapOverlayControls.tsx`の`.detailPanel`）で「緊急輸送道路 かつ 重要物流道路
  （N10・...」のように末尾（`N12）`部分）が`...`で見切れていた（サイドバー側のボトムシート
  表示では折り返されて全文表示されており、地図上のポップアップだけの問題と判明）。
- 原因: `.detailRowLabel`（`MapOverlayControls.module.css`）が`white-space: nowrap` +
  `text-overflow: ellipsis`で1行省略表示になっており、幅18remのパネルに収まらない長いラベルの
  末尾が失われていた。サイドバー側の凡例行（`MapLayersPanel.module.css: .legendCheckboxRow`）は
  同種のoverflow指定を持たず自然に折り返されるため問題が起きていなかった。
- 対応:
  - `.detailRowLabel`から`overflow: hidden`/`text-overflow: ellipsis`/`white-space: nowrap`を
    削除し、サイドバー側と同じ「折り返して全文表示する」方式へ統一。
  - ユーザー提案（全角括弧を半角へ）を採用し、最も長かったラベル
    `staticAttributeLayers.ts`の指定路線`both`カテゴリを「緊急輸送道路 かつ 重要物流道路
    （N10・N12）」→「緊急輸送道路 かつ 重要物流道路[N10・N12]」へ変更（半角の方が幅を取らず、
    折り返し発生自体も減る）。他のラベル（`（N10）`等、単体では見切れていなかったもの）は
    据え置き。
- 完了条件: モバイル幅（390px）のPlaywright実機確認で、指定路線の凡例内訳ポップアップが
  「緊急輸送道路 かつ 重要物流道路[N10・N12]」を2行に折り返して全文表示することを確認。
  テキスト変更に伴い`MapLayersPanel.test.tsx`の該当アサーションを更新。frontend 236件・
  tsc・eslint全green。

### - [x] T106. システムUI文言の全角括弧を半角`[]`へ統一、指定路線「両方該当」ラベルの重複表現を削減、設計原則12を追記 規模M（2026-08-17完了）

- 発端: T104はモバイルスクリーンショットで見切れていた1箇所（指定路線`both`ラベル）だけの
  対症療法だった。ユーザーから「システムUI全般で全角カッコを[]にする意図だった」という
  範囲の明確化と、「緊急輸送 かつ 重要物流道路[N10＋N12]のような重複表現の割愛」という
  追加要望、および「地図アプリとして地図表示エリアを広く保つことが重要」という
  設計思想を今後のためにドキュメント化してほしいという3点の依頼を受けた。
- 対応:
  - コードコメント・テストのit()タイトルを除く、ユーザーに実際に表示される文言
    （ラベル・説明文・凡例・ポップアップ・エラーメッセージ）を対象に全角括弧「（）」を
    半角`[]`へ一括置換。`mapLayers.ts`・`staticAttributeLayers.ts`・`layout.tsx`・
    `page.tsx`・`ComparisonPanel.tsx`・`MapView.tsx`（ポップアップHTML含む）・
    `MapLayersPanel.tsx`・`WeightPanel.tsx`・`RouteList.tsx`・`LocationControl.tsx`・
    `DebugConsole.tsx`・`ResearchPanel.tsx`と、`services/*.ts`のエラーメッセージ5ファイル
    （`weatherApi`/`routeApi`/`versionApi`/`regionApi`/`debugStatsApi`）が対象。
    `debugLog(...)`の開発者向けデバッグコンソール出力は地図表示エリアと無関係のため対象外
    と判断し据え置いた。
  - 指定路線の`both`カテゴリラベルをユーザー指定表記どおり
    `緊急輸送道路 かつ 重要物流道路[N10・N12]`→`緊急輸送 かつ 重要物流道路[N10＋N12]`へ変更
    （共有語「道路」の重複を末尾へ寄せて割愛、N10/N12の区切りは全角「＋」を使用）。
  - `docs/complexity-review-2026-08-16.md`の設計原則へ12条目「地図アプリとして地図表示
    エリアを最大限確保することを優先する」を追記し、半角`[]`使用・共有語重複割愛を
    今後のUI文言実装時の指針として明文化した。
  - 副次的に発見・修正した回帰: `LocationControl.test.tsx`が`new RegExp(label)`でラベルを
    正規表現化していたため、ラベル自体に`[]`を含めた結果`[取得済み]`が文字クラスとして
    誤解釈され照合が壊れる実害を検出。正規表現特殊文字をエスケープしてから`RegExp`化する
    よう修正。同様に`MapLayersPanel.test.tsx`の`/4段階（...）/`正規表現リテラルも
    `\[`/`\]`エスケープへ更新。
- 完了条件: 変更対象ファイルすべてでUI文言中の全角括弧が解消されたことをgrepで確認
  （コメント・test titleは対象外と確認）。`MapLayersPanel.test.tsx`・`LocationControl.test.tsx`・
  `DebugConsole.test.tsx`・`services/*.test.ts`の該当する古い文言アサーションを更新。
  frontend 238件・tsc・eslint全green。Playwright実機確認（デスクトップ1280px・
  モバイル390px）で指定路線セクションの新ラベル`緊急輸送 かつ 重要物流道路[N10＋N12]`と
  交通ストレス凡例の`4段階[1=快適〜4=ストレス大]`が正しく表示・折り返されることを確認。

---

## バックエンド一時的な到達不能の調査（2026-08-17・ユーザー報告）

### - [ ] T105. 地図をグリグリ操作した直後にバックエンドへ到達できなくなる事象の原因特定 規模S〜M — トリガー: 次回の再現報告

- 発端: ユーザーが本番サイト（Render）のモバイル実機スクリーンショットを提示。地図を素早く
  パン/ズームした直後、デバッグログに`region-road-surface-tiles`の`Failed to fetch`が2件、
  数分後には「システム状況」パネルの更新ボタンを3回連打してもバックエンド側
  （`/api/debug/stats`）だけが毎回`Failed to fetch`になり続けた（フロントエンド側
  `/api/version`は同一オリジンのNext.js自身の応答のため毎回即成功、対比でバックエンドの
  不調が際立った）。
- 調査所見: `/api/debug/stats`はDB・外部APIに依存しないプロセス内メモリ参照のみの
  軽量エンドポイント（`health.py`）のため、遅延ではなく到達不能（TCP接続不可）である
  可能性が高い。`region.py`には過去の実障害（グリグリ操作で並列タイル要求が急増→
  PostGIS問い合わせがCPUを奪い合う→Renderのヘルスチェックが無応答→インスタンス強制
  再起動、対策として`_region_tile_semaphore`で同時実行数6に制限済み）の記録があり、
  症状のパターンが一致する。ただし対策済みのはずの経路のため、(a)対策の再発、
  (b)Render無料枠のコールドスリープ（無操作でスリープ→次リクエストで再起動に数十秒）、
  のどちらか、あるいは両方が疑わしいが、Renderダッシュボード側のログ（インスタンス
  再起動イベント）を確認しないと確定できず、このセッションからは見えないため未確定。
- 副次対応（このラウンドで実施済み）: 調査中に`debugStatsApi.ts: getDebugStats`・
  `versionApi.ts: getFrontendVersion`が`fetch()`自体の失敗（通信エラー）をデバッグログへ
  記録していない不備を発見（HTTPステータス異常・JSON解析失敗はログするが、通信エラーだけ
  素通りしていた）。`regionApi.ts: refreshBasemapCache`で既に確立していた
  try/catchパターンへ統一し、次回同様の事象が起きた際にデバッグログだけで
  「フロントは動いているがバックエンドだけ通信エラー」を後から追跡できるようにした。
  frontend既存テストへ通信エラーケースを追加（各2件）、全green。
- 完了条件: ユーザーが同じ事象を再現・報告した際、更新後のデバッグログ（通信エラーの
  記録が残るようになった）とRenderダッシュボードのログを突き合わせて、
  「対策済み制御の再発」か「コールドスリープ」かを切り分ける。

---

## 交通ストレスレシピ外出し基盤（2026-08-17・ユーザー要望「研究フェーズでは地図表示の
パラメータも調整したい、運用でも個人最適化できるようにしたい」）

### - [x] T107. 交通ストレスの判定レシピ（一次情報→二次情報の変換式）をタイル・SQLから切り離し、上書き可能な形へ外出し 規模L（2026-08-17完了・基盤フェーズ）

- 発端: ユーザーから「OSMタグ由来の一次情報と、それを評価して組み合わせた二次情報
  （交通ストレス等）は仕組み上分けて考えられないか。二次情報側は今後アプリ側で重み調整
  できるようにしたい」という設計相談を受けた。調査の結果、一次情報（`osm_raw_ways.tags`
  の生タグ）と二次情報（`domain/traffic.py`の純関数が計算する分類値）は既にコードの層としては
  分離されていたが、交通ストレスに限っては**判定レシピ（highway別基準値・cycleway/maxspeed/
  lanes/指定路線の補正の閾値・補正量）自体がPython（ルート採点用）とSQL（地図タイルMVT生成用、
  `road_graph_repository.py`のCASE式）の2箇所に別実装されており、しかもSQL側はタイルへ
  **計算済みの最終値**を焼き込んでいた（タイルは全ユーザー共有でキャッシュされる、
  Cache-Control: max-age=3600＋ディスクキャッシュ）。このため、続く「研究フェーズで地図表示の
  パラメータも変えて実態を確かめたい」「運用でも各自が調整できる方が個人最適になるのでは」
  という要望に対しては、レシピを変えるたびに世界中のタイルキャッシュを作り直す必要がある
  （T92/T93で実際にこの手順を踏んだ）現行設計のままでは対応できないと判明した。
- 合意した方針: タイルには最終値ではなく「材料タグ」だけを焼き込み、最終値の計算はブラウザ側
  （MapLibre expression）で行う。これによりレシピ変更が地図表示に関してサーバー・タイル
  キャッシュに一切触れず完結し、個人ごとにレシピを変えても共有キャッシュを壊さない。
  ルート採点（サーバー側Python）は既存の`RoutePreference`上書きと同じ形でレシピ自体を
  リクエスト単位に上書き可能にする。
- **今回のスコープ（ユーザー承認、基盤フェーズ）**: レシピの外出し（`TrafficStressRecipe`
  pydanticモデル化・`traffic_stress_recipe.yaml`化・`/api/routes/generate`へのリクエスト
  上書き配線）／タイルの材料タグ化（`cycleway_class`/`maxspeed_kmh`/`lanes_count`/
  `motor_vehicle_no`をSQLへ、世代v8→v9）／地図側のクライアント計算式への切替
  （`trafficStressExpression.ts`、MapLibre expression）／T90の内訳ポップアップの
  POST化（研究モードでレシピを上書き中はその内容を反映できるよう配線）。
  **実際に触れる調整UIパネル（研究モードのスライダー等）は次ラウンド**。通常モードでの
  個人最適化は将来判断（今回は研究モード限定の配線のみ用意）。既定レシピは現行定数と完全に
  同じ値にし、このラウンドは見た目・挙動を一切変えない（オーバーライドを渡すUIがまだ無い
  ため）。bicycle_infraは同型の候補だが今回は対象外（traffic_stressのみ）。
- 対応:
  - `domain/traffic.py`: `TrafficStressRecipe`（`base_by_highway`＋cycleway/maxspeed/lanes/
    指定路線の閾値・補正量、既定値は従来のハードコード定数と完全一致）を新設し、
    `traffic_stress_breakdown`/`traffic_stress_level`へ`recipe`引数を追加（省略時は
    `DEFAULT_TRAFFIC_STRESS_RECIPE`、後方互換）。`traffic_stress_recipe.yaml`＋
    `evaluation_service.py: load_traffic_stress_recipe`を追加。
  - 採点経路（`compute_edge_cost`・`EvaluationService`・両エンジン・
    `api/dependencies.py: get_route_generation_builder`）へ`traffic_stress_recipe`を配線し、
    `/api/routes/generate`のリクエスト/レスポンス（`TrafficStressRecipeOverride`、
    `route_preference`と同じ「全フィールド必須」の別モデル）で上書き・エコーできるようにした。
  - `/api/region/traffic-stress-breakdown`をGET+クエリからPOST+JSONボディへ変更し、
    任意の`traffic_stress_recipe`を受け取れるようにした（`RegionService`・リポジトリへ
    `recipe`引数を追加）。フロント`fetchTrafficStressBreakdown`もPOST化。
  - `road_graph_repository.py: get_road_surface_tile_mvt`のSQLから`traffic_stress`
    （計算済み最終値）のCASE式を削除し、代わりに材料タグ`cycleway_class`/`maxspeed_kmh`/
    `lanes_count`/`motor_vehicle_no`を焼き込むよう変更。**実装中の発見**: `ST_AsMVT`は
    Postgresの`numeric`型を認識できずtextへフォールバックする実機挙動を、新規DB統合テストの
    実行中に発見（`maxspeed_kmh`が文字列`'60'`で返り数値比較テストが失敗）。`::integer`への
    明示キャストで解決（放置していればフロントのMapLibre expressionでも同じ理由で数値比較が
    壊れていた）。`ROAD_SURFACE_TILE_VERSION`を`"8"`→`"9"`（`regionApi.ts`も追従）。
  - `frontend/src/components/Map/trafficStressExpression.ts`（新規）:
    `buildTrafficStressExpression(recipe)`が`traffic_stress_breakdown`と1:1対応する
    MapLibre expressionを組み立てる。既定レシピは`export_openapi.py`が書き出す
    `traffic-stress-recipe.json`から読み、Python側とのドリフトをCIで検知する
    （`region-tile-config.json`と同じ生成パターン、手動同期ペアを作らない設計原則1）。
    `staticAttributeLayers.ts`の`TRAFFIC_STRESS_COLOR_EXPRESSION`・`TRAFFIC_STRESS_LEGEND`を
    このexpression経由へ置き換え（既定レシピは現行定数と同値のため見た目は無変更）。
    地図クリックのポップアップ（`MapView.tsx`）も材料タグから`evaluateTrafficStressLevel`
    （`@maplibre/maplibre-gl-style-spec`のexpression評価器を使い、paint/filterと同じ
    expressionを単発評価。判定ロジックを3箇所目に増やさないための共通経路）で計算するよう変更。
  - テスト: `domain/traffic.py`へカスタムレシピのテスト6件追加。`test_road_graph_repository.py`
    の旧SQL⇔Python`traffic_stress`整合性テスト2本を、bicycle_infraのみの整合性テストと
    材料タグ抽出の検証テストへ再構成。`trafficStressExpression.test.ts`新規27ケース
    （backend/tests/test_traffic.pyの代表ケースを踏襲、既定レシピ・カスタムレシピ両方）。
    `regionApi.test.ts`・`test_region_routes.py`のPOST化・世代9追従。
  - `docs/architecture.md`（API仕様・§7静的道路属性・タイル配信バージョン表）を更新。
- 完了条件: backend 733件・frontend 265件・tsc・eslint全green（すべて確認済み）。実機確認
  （地図の交通ストレス色分けが変更前と同一であることの確認、T90ポップアップのPOST化後の
  動作確認）は次のタスクリスト項目で実施する。

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
| 2026-08-15 | カバレッジ実測（関東全域） | `measure_tag_coverage.py`新規作成（backend 472件green）。kanto-latest.osm.pbf全域（131万way）で実測し、東京都心試算より全般に低いことを確認。width/shoulderのP2据え置きを確定、smoothness/cycleway系の疎さ・lanes/maxspeedが幹線限定であることをP1着手時の前提として記録 |
| 2026-08-15 | T13・T14(一部)・T15-C5検討 | 別セッションのT9（surface_attributes導出化）と並行して、T9未接触のファイルに限定して実施。T13（WeatherServiceのhourly範囲外ガード）完了、T14は`database.py: get_session`削除のみ完了（残り2項目はT9対象ファイルのため保留）、T15-C5（lifespanベース構築）は検討のうえ見送り（詳細は各タスクの節を参照）。backend 473件green |
| 2026-08-15 | T9 | `surface_attributes`テーブルを廃止し`road_edges.osm_way_id`経由で`osm_raw_ways.surface`をJOIN導出する方式へ変更。`SurfaceAttribute`型を`dict[str, str \| None]`へ単純化し`GraphService`3経路・`compute_edge_cost`・`EvaluationService`・`RoadGraphEngine`を追従、`migrations/0004_drop_surface_attributes.sql`を追加。backend 473件green、dev機PG18へmigration適用・`verify_postgis_phase0.py`23/23 PASS・`bench_postgis_prepare.py`実測（詳細はT9節・benchmarks/README.md 11番）済み |
| 2026-08-15 | 既存データへの再取込（本番・25km圏内） | T9完了後、本番Oracle DBへ同一bbox（王子中心25km、Phase 5と同一）で再取込み（run_id=2、273,947way・14チャンク・1450.2秒・db_size_mb 315→297）。dry-runで件数一致を事前確認。起動時の`apply_pending_migrations`によりmigration 0004も同時適用（本番`routing_engine`既定は`openrouteservice`のため実害無しを確認済み）。取込後smoke: tags非空67,705/273,947way（約24.7%）、`get_road_surface_tile_mvt`（王子z14）23,774バイト生成を確認。関東全域への拡大（T28(B)大規模検証）は別判断待ちで未実施。詳細はosm-pbf-import.md 9章Phase 6 |
| 2026-08-15 | 関東本土全域への拡大（T28(B)大規模検証） | ヘッダbboxが伊豆・小笠原等の離島を含み危険と判明したため、本土7都県のbbox（34.85,138.35-37.20,140.95）をdry-runで検証（本土捕捉率99.7%）。ユーザー承認のうえ本番`osm_raw_ways`/`osm_raw_nodes`をTRUNCATEしT28(B)の空テーブル分岐を発火させて実取込み。**ways=1,308,092・nodes=7,793,238・66チャンク・elapsed=777.4秒（約13分）・db_size_mb=1364**、GiST一括再構築2.4秒。事前見積もり20〜70分を大幅に上回る好結果でT28(A)(B)(C)の効果を実地確認。ways=940,000超からの緩やかな残存減速（GiST起因ではなさそう）を次回の調査対象として記録。`verify_postgis_phase0.py`23/23 PASS・4地点タイル生成スモーク確認済み。詳細はosm-pbf-import.md 9章Phase 7・12章 |
| 2026-08-15 | （UI導線レビュー） | フロントUIの導線整理を実施。反映タイミング・保存・配置の3軸不統一、「路面」の3義衝突、デバッグモード2役を特定し、T29〜T32を起票 |
| 2026-08-15 | T29 | `lib/researchMode.ts`＋`useResearchEnabled`＋`ResearchPanel`を新設し、重み上書き・実験スロット・比較表・地図重ね描きの条件を`researchEnabled`へ切替。DebugPanelは「デバッグログを表示」（ログ専任）へ改名。frontend 151件・eslint・tsc全green |
| 2026-08-15 | T30 | サイドバーを「ルートを作る」（生成条件集約・最上部デフォルト開）/「地図の見え方」/「開発者向け」（デフォルト閉）へ再編。レイヤーON/OFFを共通`LayerChip`へ統一、`ErrorText`共通化、空状態ガイド・ルート未生成時の誘導リンク追加。用語改名: 路面→道路情報（レイヤー）/舗装・未舗装（色分けモード）/舗装率（重み）、総合スコア→おすすめ度、デフォルト→初期地点、変わらないデータを更新→地図データを再読み込み、勾配凡例の範囲明示、交通ストレス凡例へ説明語追加、重みラベルを表示語と一致。frontend 152件全green |
| 2026-08-15 | T31 | 道路情報の絞り込みを即時反映へ統一（`RoadFilterEditor`削除、凡例チェック＋軸ごと一括ボタンへ。地図反映のみ`useDebouncedValue`400msで連続タップを合流）。生成条件のdirty検知（位置・距離・重みのスナップショット比較）と再生成ヒントを追加、RouteFormを制御化。frontend 151件全green |
| 2026-08-15 | T32 | レイヤーON/OFF・非表示キー・「ルートを作る」開閉をlocalStorageへ保存/復元。エフェクト保存起因のStrictMode上書き問題をPlaywrightで検出しハンドラ内保存へ修正。実機確認は用語・3ブロック構成・自動ON・リロード復元・おすすめ度表示・dirtyヒントの28項目全OK（実ルート生成含む） |
| 2026-08-15 | T14・T15（残り） | T9完了で解禁された残りの小粒整理をまとめて実施。T14: `build_graph_for_bbox`（アプリ内・scripts内どちらからも未参照と確認）を削除、`/api/routes/preview`のフロント`previewRoute()`が実UIから未使用である実態をarchitecture.mdへ追記。T15: `ASSUMED_SPEED_KMH`重複定義を`domain/wind.py`へ集約（wind_service.py/road_graph_engine.pyはimportに置換）、`repository=None`引数へ`RoadGraphRepository \| None`型注釈を3サービス（GraphService/RegionService/ElevationAttributeService）に追加。T14・T15とも完了、lifespanベース構築（C5）のみ既存の見送り判断を維持。backend 471件green |
| 2026-08-15 | T21 | 関東本土全域への静的属性再取込み完了によりトリガー成立、評価のエンジン非依存化を実装。ORSエンジンの路面評価をextras数値ID語彙から`AttributeRepository.get_nearest_surface_tags`（PostGIS KNN+ST_DWithin、全候補分を1回のSQLで一括処理）による自前DB空間マッチへ置換。`domain/road.py`のORS数値ID語彙4関数を削除し、両エンジン共通の`distance_weighted_road_score`を新設（road_graph_engine.pyの`_aggregate_road_score`は薄いラッパーへ縮小）。`ORSClient`の`extra_info=surface`・`RoutingService`のextrasパース・`RouteSegment.surface_summary/surface_values`も削除。backend 468件・frontend 146件・eslint・tsc全green、OpenAPI/フロント型再生成済み。`get_nearest_surface_tags`のDB統合テストはローカルネイティブPGへ実接続して実行・PASS確認済み |
| 2026-08-15 | （モバイル実機フィードバック対応） | スマホ実機検証での8点の使いにくさを起票・全件完了。T33: レイヤーチップ折り返し。T34: サイドバードロワーを下部タブバー＋部分シート（`BottomSheet`新規、暗幕なし・地図を隠さない）へ再構成、実装中にMapLibre帰属表示のタブバー下への隠れを発見し修正。T35: 緯度経度手動入力を撤去（`useLocation`/`LocationControl`縮小）。T36: 天候表示を常設ヘッダへ移動。T37: アプリ名見出しを削除。T38: 「地図の見え方」の各レイヤーをアコーディオン化（デフォルト全閉）。T39/T40: 交通ストレス・自転車インフラの凡例に判定基準/道路情報との違いの説明文を追加。frontend 146件・eslint・tsc全green、Playwright実機確認（390px幅・1280px幅）で全項目確認済み |
| 2026-08-16 | 静的属性P1（node取込・停止密度評価、主要部分） | 信号・横断歩道・一時停止・踏切のnode取込機構（`osm_raw_pois`新テーブル、migration 0005、`domain/traffic.py: classify_stop_poi`、`osm_adapter.py: osm_node_to_poi_spec`、`pbf_source.py`のpyosmium `node()`ハンドラ、`import_profile.yaml`のnode要素2ルール）と「停止密度」評価軸（`AttributeRepository.get_stop_poi_counts`/`get_nearest_stop_poi_counts`、`RoutePreference.stop_weight`、`compute_edge_cost`・両エンジンのEdge Cost/区間難易度への統合、`RouteCandidate.stop_density`/`RouteSegmentDetail.stop_difficulty`）を実装。ユーザー承認のうえスコープを絞り、交差点密度（intersectionDensity）とtrafficStress/bicycle_infra（P0由来way属性）の評価組み込みは別タスクへ分離。PBF取込バッチはRawOsmRepositoryを経由せず直接asyncpg COPYで書くため、Overpassフォールバック側は元々ADR方針どおり無改修。backend 531件・frontend 146件・eslint・tsc全green、OpenAPI/フロント型再生成済み。dev機ネイティブPGへmigration 0005適用（空DB・既存DBとも冪等確認）、Tokyo.osm.pbfでdry-run実行し信号等81,921件のマッチを実データで確認済み。詳細はdocs/static-road-attributes-plan.md P1節参照 |
| 2026-08-16 | （第4回レビュー） | 複雑度平衡レビュー第2弾を全ソース通読で実施（complexity-review-2026-08-16.md、詳細版はArtifact公開）。第2回指摘I-1〜I-10の完済を実コードで確認（I-4のみ条件待ち）。残課題R-1〜R-10のうち実装対応をT43〜T47として起票、T22へ撤去期限（最短2026-08-29）と発動ログ確認手順を追記。設計原則10箇条を改訂（原則1/2/8/9を更新） |
| 2026-08-16 | T43〜T47 | 第4回レビュー対応を全件実施。T43: `domain/difficulty.py`へ`evaluate_axis_difficulties`（軸別difficulty＋合成値をまとめて返すNamedTuple）を追加し、両エンジンの`_build_segment_details`・`compute_edge_cost`の3箇所の重複合成ブロックを置換（評価軸追加時の編集箇所3→1）。T44: `SURFACE_MATCH_MAX_DISTANCE_M`/`STOP_POI_MATCH_MAX_DISTANCE_M`を`domain/road.py`/`domain/traffic.py`へ集約し、openrouteservice_engine.py・AttributeRepository（個別リポジトリ＋ファサード委譲6箇所）をimport参照へ統一。T45: `ComparisonPanel.tsx`の`formatWeights`を`SCORING_AXES`/`PREFERENCE_AXES`カタログからの生成へ置換（stop_weightの欠落を解消）、`METRIC_ROWS`へ停止密度行を追加、テスト3件追加。T46: `staticAttributeLayers.ts`へ`BICYCLE_INFRA_LABELS`をexportし`MapView.tsx`の重複辞書を削除。T47: static-road-attributes-plan.mdへscoring軸判断項目を追記、.env.exampleへDBなし構成の評価縮退を追記、restart-dev.bat/stop-dev.batへ用途コメントを追加（削除せずコミット対象化）。backend 531件・frontend 148件（新規3件含む）・eslint（変更ファイルのみ、既存の無関係な未コミット変更除く）・tsc全green |
| 2026-08-16 | T48・T49 | ユーザー依頼（計画外の品質観点）でDependabot（`.github/dependabot.yml`、npm/pip/github-actions週次）とクリティカルパスE2E自動化を実施。E2Eはバックエンド・外部APIに依存させず、`frontend/e2e/fixtures.ts`のPlaywrightネットワークモックで`/api/routes/generate`・`/api/weather`・`/api/basemap/**`・`/api/region/road-surface-tiles/**`を置換（API契約の正しさはapi-contractジョブが別途担保する設計分担）。ルート生成→表示・レイヤーON/OFFの2本を`playwright.config.ts`（Chromium1種、`next build && next start`）＋CIの`e2e`ジョブとして追加。vitestが`e2e/**`を誤検出する問題を`vitest.config.mts`のexcludeで解消。frontend 148件・eslint・tsc・E2E2件すべてgreen |
| 2026-08-16 | T25 | 静的属性P1で評価軸が増えたことによりトリガー成立、評価軸カタログ化を実施。`frontend/src/lib/evaluationAxes.ts`新規（`SCORING_AXES`/`PREFERENCE_AXES`、`mapLayers.ts`と同じ型）。ラベルを`Record<keyof ScoringWeights\|RoutePreferenceWeights, ...>`で書きOpenAPI生成型への完全性チェックをドリフト検知に使う（新規生成物・テスト無し）。`WeightPanel.tsx`・`RouteList.tsx`のハードコードをカタログ生成へ置換、副次効果でUI入力欄が無かった`stop_weight`も自動追加。`score_breakdown`の新規表示UIはスコープ外とした（ユーザー承認、モバイルUI改修との競合回避）。backend 531件・frontend 146件・eslint・tsc全green |
| 2026-08-16 | 静的属性P1残り（intersectionDensity・trafficStress・bicycle_infra評価組み込み） | ユーザー依頼で当初分離していたP1残りスコープを実施。ユーザー承認のうえ、intersectionDensityを当初案（road_graphエンジンはグラフ内Node次数を直接計算）から「半径内の交差点（次数3以上のroad_node）件数」という停止POIと同一の空間マッチ方式へ設計変更し、両エンジンとも同じ形の実装に統一（結果として当初の分離理由だったORS側の実装規模増加が解消され、同ラウンドで完了）。`AttributeRepository`へ`get_way_tags`/`get_nearest_way_tags`/`get_intersection_counts`/`get_nearest_intersection_counts`を新規実装（get_surface_attributes/get_nearest_surface_tagsと同じJOIN・空間KNNパターンの踏襲、交差点は`road_edges`のfrom/to隣接ノード集合から次数を都度導出）。`domain/difficulty.py: evaluate_axis_difficulties`を4軸→7軸へ拡張（T43で1箇所化済みのため呼び出し元3箇所は引数追加のみ）。`RoutePreference`へ`traffic_weight`/`infra_weight`/`intersection_weight`追加、7軸すべて`route_preference.yaml`のみに追加し`scoring.yaml`には追加しない（stop_weightと同じ判断、R-5対応）。`RouteSegmentDetail`/`RouteCandidate`へ新フィールド追加、OpenAPI/フロント型再生成。`evaluationAxes.ts`のPREFERENCE_AXESへ3軸追加・`WeightPanel.tsx`の既定値更新。backend 581件（新規47件、repository統合テストで次数3/2判定・空間マッチ境界を検証）・frontend 153件・eslint・tsc全green。詳細はdocs/static-road-attributes-plan.md P1節参照 |
| 2026-08-16 | （外部静的データソース検討対応） | external-data-sources-review-2026-08-16.mdの実行計画をT50〜T54として起票。T50: 警察庁事故データ／T51: 指定路線コンフレーション機構＋N10/N12・NCR表示（着手可能）／T52: JICE舗装DB調査ゲート（JICE返信待ち、継続中）／T53: JARTIC較正（研究IF側）／T54: 既取込データ（停止要因POI・交差点密度）の可視化漏れ解消（2026-08-16の追加棚卸しで判明、新規データ取得不要） |
| 2026-08-16 | T50訂正（CSV取得のユーザー作業前提を撤回） | ユーザーからの指摘を受け警察庁事故統計CSVの配布URL構造を実機確認（WebFetch）。`honhyo_{year}.csv`等が年号だけで組み立てられる予測可能なパスで、2019〜2024年で同一命名規則・ログイン不要・robots.txt制限なしを確認し、直接GETでHTTP 200を実測（2024年分62.8MB）。T50・external-data-sources-review-2026-08-16.md §4.1/§4.6を「CSV取得もバッチに組み込める（ユーザー作業不要）」へ訂正、T50のトリガーを撤去 |
| 2026-08-16 | T22 | ユーザー提起により撤去条件（本番ログ2週間連続0件）を撤廃（低利用規模のプロトタイプ段階では時間経過が検証の信頼性を上げないため。decisions/pre-static-attributes-gate.md 決定2改定）、待機なしで着手・完了。`overpass_fallback_enabled`設定・`GraphService`/`RegionService`のフォールバック分岐・`OverpassClient.get_roads`・Python側MVTエンコーダ（`encode_road_surface_tile`）を削除し、地域路面レイヤーをPostGIS（ST_AsMVT）単独系統へ一本化（カバレッジ外は空タイル）。`RegionService`は`overpass_client`/`http_client`引数ごと不要になり縮小。way数スケーリングを計測していた`bench_vector_tile.py`・`bench_event_loop_stall.py`を削除。`test_graph_service.py`のrepositoryモードテスト群を「GraphServiceが自ら取得・永続化する」前提から「PBF取込済みデータを読むだけ」前提へ作り直し（タイル境界交差点分割の回帰テストは直接シード方式へ置換して同じ回帰を継続検証）。backend 568件全green、benchmarks/scripts/docs（architecture.md・osm-pbf-import.md等）を追従更新 |
| 2026-08-16 | （UI操作レビュー） | Playwright実機操作による一般ユーザー目線レビューを実施（docs/ui-review-2026-08-16.md）。北コンパスボタン重なり・タイル一過性崩れ・天候視認性の3件をT55〜T57として起票。当初最重要所見とした「候補選択で地図が読み込み中に戻る」は検証スクリプトのセレクタ不具合による誤検知と判明し、再検証（3候補連続切替、いずれも200〜300msで正常更新）のうえ起票対象から除外 |
| 2026-08-16 | T58 | ユーザー報告（スマホでピンチイン・ピンチアウトが効かないことがある）を調査し修正。MapLibreのキャンバス自体は`touch-action: none`だが、地図上の自作オーバーレイボタン（レイヤーアイコン列・条件サマリ・現在地ボタン）に`touch-action`が無く、ピンチの片方の指がそこに乗ると地図ジェスチャーとして確定しないことが原因と特定。3要素へ`touch-action: none`を追加（CSSのみ、frontend既存テストgreen） |
| 2026-08-16 | T50（取得・保持・表示先行） | 警察庁交通事故統計オープンデータの取込・表示を実装。`domain/accident.py`（DMS変換・当事者種別/都道府県コード判定、コード表CSVを実取得して値を確認）、`app/batch/import_accidents.py`（年号からURLを組み立てて直接HTTP取得、関東7都県へ絞り込み）、migration 0006（`accident_points`/`accident_import_runs`）を新規実装。**2019〜2021年は本票CSVが58列構成（2022年以降は68列）と実データで判明し非対応と判断**（列数不一致はその年の取込全体を明示的に失敗させる設計）。2022〜2024年を実際にdev DBへ取込み関東303,455件（自転車関連92,955件・死亡2,032件）を確認。表示は`/api/region/accident-tiles/{z}/{x}/{y}.pbf`（`accident_repository.py`/`accident_service.py`新規、road_surfaceと異なりカバレッジ判定なし）＋フロント新規レイヤー「事故（警察庁統計）」（円マーカー、色=自転車関連/その他、死亡事故は拡大表示）。実装中に`next.config.ts`へのproxy rewrite追加漏れ（新エンドポイントがフロント経由で404になる）をPlaywright実機確認で発見・修正。backend 595件・frontend 153件・eslint・tsc全green、Playwright実機確認（レイヤーON/OFF・地図上のドット表示・サイドバー凡例）で表示を確認。評価組み込み（8軸目化）は残作業として引き続きT50に残す（詳細はT50節参照） |
| 2026-08-16 | T54（引き継ぎ・完了） | 別セッションが`.claude/worktrees/t54-poi-intersection-viz`で着手・大部分実装した状態（プロセス終了・未コミットのまま中断）を発見し引き継いだ。`/api/region/poi-tiles/{z}/{x}/{y}.pbf`（停止要因POI・交差点密度の2レイヤーを1タイルに焼き込み）とフロント新規2レイヤー「停止要因」「交差点密度」の実装内容を検証（backend 578件・frontend単体40件・tsc・eslint全green、実装自体は完成していたと確認）のうえコミットし、並行して本流へ合流していたT50（警察庁事故データ）・T58（ピンチズーム修正）へrebaseして統合。T50と同じファイル群（mapLayers.ts・MapView.tsx・MapLayersPanel.tsx・MapOverlayControls.tsx・regionApi.ts・staticAttributeLayers.ts・icons.tsx・export_openapi.py・region-tile-config.json）を独立変更していたため14ファイルでコンフリクトが発生したが、すべて「両方の追加を残す」加算的マージで解消（意味的な衝突は無し）。region-tile-config.jsonは両者で異なるスキーマ変更をしていたため`{road_surface, accident, poi}`の3キー構成へ統一。T54側にも`next.config.ts`のproxy rewrite追加漏れ（T50で発見したのと同じ落とし穴）があり追加。統合後の実機確認でdev DBの`osm_raw_pois`が0件（該当データ未取込み）と判明したが、intersectionレイヤーは実データ（次数3以上のnode 8,517件、785 features/タイル）で正常動作を確認。backend 617件・frontend 187件・tsc・eslint全green、Playwright実機確認（停止要因・交差点密度・事故の3レイヤー同時ON、サイドバー凡例、実データでの交差点密度表示）。master a13d1f0→84a2511→52ed0a9でfast-forward |
| 2026-08-16 | T47 R-6実装（トリガー成立） | T54で静的レイヤーが+2種類（停止要因POI・交差点密度）に達し、T47 R-6に記録済みだったトリガー条件が成立。(a)MapView.tsxの標高・交通ストレス・自転車インフラ・事故・停止要因POI・交差点密度6レイヤーぶんのensure/set関数ペアを`STATIC_OVERLAY_LAYERS`テーブル+ループへ置換、(b)page.tsxに散在していたlocalStorage読み書き（load/save関数＋復元用useIsomorphicLayoutEffect）を`useStoredState`フック（新規、hooks/useStoredState.ts）へ集約、を実施。別セッションが着手・未コミットのまま中断していた状態を引き継ぎ、内容確認（全diff読解）・frontend全200件・tsc・eslint・Playwright e2eスモーク2件green、レイヤーチップ全種の手動トグルでconsoleエラー無しを確認したうえでコミット。あわせて同じワーキングツリーにあった別件2点も検証のうえコミット: ComparisonPanelへtraffic_stress_score/bicycle_infra_score/intersection_density（静的属性P1残りで追加されたがMETRIC_ROWS未対応だった3軸）の行を追加、vitest.config.mtsへ`.claude/worktrees/**`の除外を追加（並行worktree配下の同名test.tsxをvitestが誤って拾い偽陽性を出す実害の対策） |
| 2026-08-16 | （PostGISクエリコストレビュー） | ユーザー依頼（個別データソース追加で遅いSQLが散見される）を受け全テーブル・全SQLを通読、dev DBでEXPLAIN ANALYZE実測。最重要所見はST_DWithin(geography)単体JOINの索引不使用4クエリ（停止POI 200エッジ134秒→`&&`前置で0.44秒/306倍、事故8点18.6秒→0.24秒/79倍を実測済み）。T64〜T69を起票。テーブル設計自体は健全で、問題は後発クエリの`&&`前置規約不徹底に集約されると結論 |
| 2026-08-16 | T62 | ユーザー指摘（自転車インフラと道路情報の自転車・歩行者道分類が意味的にかぶっていないか）を受けた属性の重複・包含関係の棚卸しを実施し起票・完了。数値・スコアリング挙動は不変、表示ラベルと根拠コメントのみ変更。`staticAttributeLayers.ts`: `bicycle_infra=shared_pedestrian`のラベルを「自転車歩行者道」→「歩道（自転車通行可）」へ変更し、roadFilterAxes.tsの highway表示分類「自転車・歩行者道」との違い・非対称な包含関係をコメントで明記。`domain/traffic.py`: `classify_bicycle_infrastructure`と`traffic_stress_level`が同じcycleway系タグを別目的で解釈しており2軸（交通ストレス重み・自転車インフラ重み）が完全には直交しない旨を相互参照コメントで明記、`TRAFFIC_STRESS_BASE_BY_HIGHWAY`に登録の無いhighway値（path/footway等）が意図的に評価対象外である旨を追記。backend 621件・frontend 200件・tsc・eslint全green |
| 2026-08-16 | （designation実装レビュー） | T51実装の未コミット変更へ8角度コードレビューを実施（候補発見8＋1票候補の検証2エージェント、確定26件・要実測1件・棄却0件。T65〜T67起票済み分は重複除外）。T70〜T85を起票。最優先はタイル世代対上げ漏れ（T70）と取込バッチのデータ欠損系（T71〜T73）、T74（MVT指定路線表現）はT66と関連する設計判断。log_external_call未使用は既存バッチ同一先例のため対象外、improvement-plan.mdのdiff内矛盾は作業ツリーで解消済みと確認 |
| 2026-08-16 | （将来UI整理検討） | ユーザー提示の外部UI/UXレビュー指摘表12点を将来の静的属性拡張の観点で検討。🔴高5点中4点（#1/#3/#5/#8/#9）はT29〜T32・T38で対応済み、#6/#7はT39/T40で対応済みと確認し再起票せず、#10〜#12はユーザー提示どおり🟡低・先送り。現状ギャップが残る#2（レイヤーのカテゴリ化）・#4（データ状態の明示）のみT86・T87として起票 |
| 2026-08-16 | T70〜T77 | designation実装レビュー対応を優先順位どおり実施。T70: 路面タイル世代v5の対上げ漏れ（フロント定数・生成物が旧v4のまま）を修正。T71: import_designations.pyのDELETE→INSERTをtransaction()で括り0件時はDELETEごとスキップ（既存データ保持）＋executemany化。T72: N12 GeoJSONの3要素座標・MultiLineString、N10 GMLの複数posListへの防御を追加。T73: match_designations.pyも0件時のDELETE全消しガード＋WARNING昇格。T75: kind集合の分散（3表現）をdomain/designation.py: DESIGNATION_IMPORT_KINDSへ一本化、import側は_KIND_SPECSテーブルへ統合（未知kindはKeyError即死）。T76: get_nearest_designated_flags（3本目の独立KNN）を_NEAREST_WAY_TAGS_SQLへ統合し専用SQL/メソッドを削除。T77: get_designated_edge_idsの転送方式をdev DB実測（designation_attributes 28,940行 vs road_edges 117,744行）のうえ現状維持を決定。T74（MVT指定路線表現の見直し）は新テーブル・新バッチを要する規模M相当と判明したため検討メモのみ残し未着手。あわせてT68（is_split_up_to_date用stale限定部分GiST索引、EXPLAIN実測で採用確認）・T69（get_way_specs_with_closureの近傍extent爆発防衛、ST_Intersectionでbboxの10kmマージンへクランプ）も実施。backend最終669件（DB統合テスト含む新規テストを各タスクで追加）、各タスクごとに個別コミット |
| 2026-08-16 | 統合レビュー（review:all第1回）・T76チェック修正・T88 | daef76e..HEAD（8軸目・designation機構・PostGISコスト対策T64〜T69・designation実装レビュー対応T70〜T85）を対象に、overall/complexity/consistency/ui4種を統合実施（[history/2026-08-16_all.md](../.claude/commands/review/history/2026-08-16_all.md)）。backend 672件・frontend 212件（並走実行時のMapLayersPanel3件timeoutは単独再実行で全green、実行環境競合と判定）とPlaywright実機確認（変更画面＋主要導線1周）でP0/P1新設なしを確認。P1指摘（F-1: architecture.md未追従）をT88として起票・即実施：新設「§7 静的道路属性と8軸評価モデル」節に8軸一覧・重み表・P1各軸・T50事故密度・T51指定路線コンフレーション・タイル配信3系統・T59バックグラウンド構築を集約し、§2ディレクトリ構成・§4 API・§6データモデルも追従。P2指摘（F-2: T76チェックボックス未更新）も修正。F-3（MapView閾値監視の安全弁消化）・F-6（context.mdの鮮度）はレビュー基準側の課題のため/review:improveでの対応が別途必要 |
| 2026-08-16 | （未完了タスク棚卸し）・T91起票 | ユーザー依頼により全90タスク＋関連ドキュメント（static-road-attributes-plan.md P1残り・統合レビューhistory）を棚卸し。未チェック7件（T10〜T12はトリガー未到達で現状維持、T52はJICE返信待ちでブロック中、T53・T56・T87は着手可能）を確認。統合レビューF-3（MapView.tsx閾値監視の安全弁消化、レビュー時点1,299行→棚卸し時点1,378行まで増加確認）をT91として新規起票。F-4（T56の再現証跡）はT56本文へ追記。F-2（T76チェック漏れ）は既に前回セッションで修正済みと確認（追加対応不要）。P1残り3項目（bicycle=no Hard Constraint・自転車歩行者道スコープ拡張・name/refのMVT焼き込み）はstatic-road-attributes-plan.mdで二重管理回避の方針どおり本ファイルへは転記せず |
| 2026-08-16 | T87（1回目） | レイヤーのデータ状態表示（読込中/データなし/取得失敗）を実装。`MapView.tsx`に純粋関数`computeLayerDataStatus`を新設し(source, source-layer)ごとに判定、`LayerChip`の状態ドットと`MapLayersPanel`のセクション案内文（road専用だった`zoomWarning`パターンを一般化）へ反映。新規テスト13件、frontend全232件・tsc・eslint全green。dev環境をBrowser経由で実機確認しようとしたが、このセッションのBrowserペインがWebGLフレームをコンポジットできず（`map.loaded()`が操作後も`false`のまま）MapLibreの`load`イベントが発火せずカスタムソースが一度も追加されない制約に遭遇し、loading/empty/errorの3状態の視覚的な区別確認は持ち越しとした |
| 2026-08-17 | T87（実機確認・2回目） | ユーザーがBrowserペインを表示したことで前回の制約が解消し、実機確認を完遂。dev DBの既知欠損（`osm_raw_pois`0件、T54）で「データなし」、backendプロセス停止で「取得失敗」（road/交通ストレス等road_surfaceタイル共有4レイヤーが同時にerrorになる設計どおりの挙動含む）を実データで確認。**この過程で実装のバグ2件を発見・修正**（ユニットテストでは再現できない実際のMapLibreイベント順序起因）: ①エラー解除条件が「次の取得サイクル開始」限定だったため、障害復旧後に既にキャッシュ済みの地点へ戻ってもエラー表示が残り続ける不具合→`moveend`/`zoomend`でも`isSourceLoaded=true`なら解除する`clearStaleTrackedSourceErrors`を追加、②`isSourceLoaded`がtrueになる瞬間と`querySourceFeatures`が実データを返せる瞬間のズレにより、実際は6,273件あるのに「データなし」のまま固定される不具合→`idle`イベントでの継続的な再計算を追加。修正後に同じ手順を再実行し正しい回復を確認。新規テスト3件追加（`clearStaleTrackedSourceErrors`、計12件）、frontend全235件・tsc・eslint全green |
| 2026-08-17 | T92 | ユーザー実機フィードバック「指定路線ならほぼすべて赤色。実態にあった形でもう少し評価して」を受け、dev DB実データ（関東本土、指定路線11,102件）で検証。指定路線該当の83.3%が最終値4/4、うち56%は`primary`/`secondary`/`trunk`が一律base=4のため+1補正が実質無意味と判明。また既存タグの中に未活用の差別化要因（`cycleway=shared_lane`15.6%・`lanes=1`319件）があると判明。「信号密度も合成できないか」という追加相談には、交通ストレスへ合成するのは「自動車への近接度」を推定する同一構造の手がかりに限る、信号・交差点密度は質的に別の負担で独立軸のまま残すべき、という基準を整理して回答（`traffic_stress_breakdown`のdocstringへ明文化）。合意のうえ`TRAFFIC_STRESS_BASE_BY_HIGHWAY`の`secondary`/`secondary_link`を4→3、cycleway補正へ`shared_lane`/`share_busway`（-1）、車線数補正へ`lanes<=1`（-1）を追加（`road_graph_repository.py`のSQL CASE式も同期）。試算で指定路線の4/4割合が83.3%→78.3%に低下を確認。凡例（`mapLayers.ts: panelHintDetail`、サイドバー設定画面・地図上▶詳細パネル共通）とポップアップ内訳（T90機能）の説明文をレイアウトごとの粒度で更新。backend 694件（新規11件）・frontend（MapLayersPanel既存35件が更新後の文言でも通過）全green |
| 2026-08-17 | 統合レビュー（review:all第2回） | ユーザー指示によりリポジトリ全体（前回差分だけでなくlayer境界・DI・重複・スケール成立性・カタログ集約を既存コード全体で再確認）を対象に4種統合実施（[history/2026-08-17_all.md](../.claude/commands/review/history/2026-08-17_all.md)、Phase4は同日実施の[history/2026-08-17_consistency.md](../.claude/commands/review/history/2026-08-17_consistency.md)を統合）。backend 694件・frontend 243件（いずれも単独実行でall green、初回並走実行時のbackend 248件skipはサンドボックス環境のDB初回接続レイテンシによる一過性のものと再実行で確認）。P1指摘（F-1: T92のSQL変更がタイルキャッシュ世代に未反映、T70に続き同型のミス2回目）をT93として起票・即修正、P2指摘2件をT94・T95として起票、T91（MapView.tsx閾値監視）はF-3として再確認（1,378→1,664行まで悪化継続、新閾値案を提示）。レビュー基準自体への示唆（タイル世代対上げ・閾値運用ルールの2パターンともに2回目の再発）を`/review:improve`候補として記録 |
| 2026-08-17 | T93 | 統合レビューF-1修正。`region_service.py: ROAD_SURFACE_TILE_VERSION`を`"7"`→`"8"`、`regionApi.ts`の対応定数も追従、`export_openapi.py`再実行で`region-tile-config.json`再生成（openapi.json/api.d.tsは内容不変）。`docs/architecture.md`の世代表記・履歴を追従、`regionApi.test.ts`のハードコード期待値を修正。backend 694件・frontend 243件・tsc・eslint全green |
| 2026-08-17 | T94 | 統合レビューF-2修正。`RegionService.get_traffic_stress_breakdown`を`log_external_call`＋WARNING＋Noneフォールバックへ統一（`get_road_surface_tile`等と同じグレースフルデグレード方針）。フィールド名は`log_external_call`自身の二重WARNING発火を避けるため`"result"`ではなく`"lookup"`にした。`FakeRegionRepository`にエラー注入対応を追加しDB障害時の回帰テストを追加。backend 699件全green |
| 2026-08-17 | T95 | 統合レビューF-4修正。`docs/architecture.md`§7の`AttributeRepository`対称メソッド列挙へ`get_way_tags_by_osm_way_id`（T90、対に属さない別系統である旨）を1行追記。docsのみ |
| 2026-08-17 | T96 | ユーザー実利用フィードバック「交差点密度は道路網を見れば分かり可視化の意味が薄い」を受け、地図の独立可視化レイヤーから撤去（フロントのみ、ルーティング材料のintersection_weightは無変更）。`mapLayers.ts`のカタログ・`MapView.tsx`のensure関数/レイヤーID/ポップアップ/データ状態テーブル・`staticAttributeLayers.ts`の色/凡例/半径式・`icons.tsx`・`MapOverlayControls.tsx`・`MapLayersPanel.tsx`・`page.tsx`から関連コードを削除。バックエンドのpoi-tiles MVT配信は停止要因と同一SQL関数内にあり変更コストが非対称に大きいため据え置き、T97として起票。frontend 235件・tsc・eslint全green、Playwright実機確認済み |
| 2026-08-17 | T98（別セッション作業の遡及記録） | 別セッションが着手・完了・コミット（`2cc7f44`）していたがT番号・記録が漏れていたため遡及起票。周回ルート8候補ぶんのOpen-Meteo呼び出しがほぼ完全並列発火し本番共有IPで429常態化・夜間502の一因になっていた問題を、`WeatherService.prefetch`/`WindService.prefetch`による候補間リクエスト集約で緩和。`/api/debug/stats`へ`error_types`/`last_error_type`等の診断情報を追加し`SystemStatusPanel`に反映。17ファイル370行追加・20行削除、新規テスト複数追加（詳細はT98節参照） |
| 2026-08-17 | docs整合性の点検・修正 | `improvement-plan.md`を読み直し改善候補を洗い出し。(1) T96でarchitecture.md「静的レイヤー・タイル配信（フロント9レイヤー）」の更新が漏れていた（実際は8レイヤー、交差点密度を撤去済み）ことが判明し修正。(2) T98（上記）を遡及記録し、architecture.mdの天候の行へ候補間リクエスト集約の挙動説明を追記（`/api/debug/stats`拡張自体はコミット時に反映済みだった） |
| 2026-08-17 | static-road-attributes-plan.mdの残タスク整理・別ブランチ統合 | 残タスク4件を検証のうえ§3.1として整理していたところ、ユーザー指摘により2件（自転車歩行者道スコープ拡張・bicycle=noのHard Constraint）が別ブランチ（`origin/claude/osm-roadbike-map-features-1yn5yi`、コミット`0f1f952`）で既に起票済み（ただしmasterへ未マージ）と判明。同ブランチはT96〜T99を使用していたが、masterは既に別件（交差点密度撤去・Open-Meteo 502緩和等）でT96〜T98を使用済みだったため衝突。ユーザー承認のうえ内容を確認し、T99〜T102として番号を振り直してmasterへ統合した（T99自転車歩行者道スコープ拡張／T100 bicycle=no Hard Constraint＋oneway:bicycle例外／T101補給・休憩POIレイヤー／T102 lit/segregated/barrierカバレッジ実測） |
| 2026-08-17 | T99・T102（コード実装のみ） | ユーザー依頼によりコード実装が完結する部分を先行実施。T99: `import_profile.yaml`へ`shared_pedestrian_ways`ルール（highway=footway/path AND bicycle=yes/designated/permissive）追加、`segregated`タグを`ALLOWED_WAY_TAGS`へ追加。YAMLで`bicycle: [yes, ...]`を無引用で書くとYAML 1.1のブール値解決規則で`ProfileError`になる罠を発見・引用符で回避。T102: `measure_tag_coverage.py`へ`CANDIDATE_WAY_TAGS`（lit/segregated）・`CANDIDATE_NODE_TAGS`（barrier、取込プロファイルにルールが無いため新設`NodeTagCounter`で値ごとの生カウントのみ報告）を追加。いずれも実際の再取込み・PBF実測（完了条件）はDBアクセス/PBFファイルの無い環境では実施できないためチェックは`[ ]`のまま。backend 713件全green |
| 2026-08-17 | T100 | `domain/evaluation.py: is_edge_allowed`へ`way_tags`引数を追加し`bicycle=no`のHard Constraint除外を実装（road_graphエンジンは既存配線のみで自動的に有効化、openrouteserviceエンジンは対象外の非対称は既存のまま）。`osm_adapter.py`に`_resolve_direction`を新設し`oneway:bicycle`を`oneway`本体より優先させるcontraflow cycling対応を実装（PBF取込バッチも同じアダプタを経由するため二重実装なし）。本タスクは完了条件が単体テスト・backendテストgreenのみでDB/PBF不要だったため、T99・T102と異なりこのラウンドで完全に完了。backend 725件（新規12件）全green |
| 2026-08-17 | T102（実測完了） | `backend/data/pbf/kanto-latest.osm.pbf`（対象way 1,329,632件）で実測。lit（全体1.1%・幹線4.8%）・segregated（全体0.6%だがT99の自転車歩行者道内では28.4%）とも既採用tag（smoothness 0.2%）を上回り採用推奨と判断、取込コストゼロのため`lit`も`ALLOWED_WAY_TAGS`へ追加（segregatedはT99で先行済み）。barrier（node、bollard 21,975件等）も採用推奨だが新規node取込ルールが必要なため実装は別タスク。backend 726件全green |
| 2026-08-17 | T103 | ユーザー報告（表示/非表示を切り替えられない、非表示にしようとすると一瞬ですぐ表示に戻る）を本番サイトで実機調査。「絞り込みを一括クリア」ボタンが条件付きレンダリング（`hasHiddenFilters`）で出現/消失するたび、パネル内の他のレイヤー表示トグルが上下にずれ（Playwrightでbounding box実測、最大25px程度）、直後のクリックが別要素（凡例チェックボックス等）に当たる誤操作を確認・再現。`MapLayersPanel.tsx`のボタンを条件付きレンダリングから常時マウント＋`visibility:hidden`（CSS、高さは常に確保）へ変更し解消。修正後はレイアウト位置が完全に不変であることを実機確認。回帰テスト追加、frontend 236件・tsc・eslint全green |
| 2026-08-17 | T99本番再取込み | ユーザー承認のうえ`kanto-latest.osm.pbf`を本番Oracle Cloud DBへ再取込み（事前dry-runで`matched_ways=1,329,632`等を確認）。run_id=5、ways=1,329,632・nodes=147,291・pois=332,294（67チャンク、db_size_mb=2004、elapsed=904.0s、エラーなし、UPSERTのため非破壊的）。本番DBへ直接クエリし反映を確認: `shared_pedestrian_ways`該当17,584件（T102実測の「その他」グループ件数と一致）、うち`segregated`保持5,000件（約28.4%、実測どおり）、`lit`保持14,368件。T99を完全完了（`[x]`）へ更新 |
| 2026-08-17 | T104 | ユーザーがモバイル実機スクショを提示（地図上の指定路線凡例内訳ポップアップで「緊急輸送道路 かつ 重要物流道路（N10・...」が末尾`N12）`ごと見切れ）。`MapOverlayControls.module.css: .detailRowLabel`の`white-space: nowrap`+`text-overflow: ellipsis`が原因と特定し、サイドバー側と同じ折り返し方式へ統一。あわせてユーザー提案（全角括弧→半角）を採用し該当ラベルを`[N10・N12]`へ変更。モバイル390px幅のPlaywright実機確認で2行折り返し・全文表示を確認。frontend 236件・tsc・eslint全green |
| 2026-08-17 | T106 | ユーザー依頼によりT104を「システムUI全般」へ拡張。UI表示文言（コメント・test title除く）の全角括弧を半角`[]`へ一括置換（mapLayers/staticAttributeLayers/MapView等18ファイル＋services配下エラーメッセージ5ファイル）、指定路線`both`ラベルを`緊急輸送 かつ 重要物流道路[N10＋N12]`（共有語重複割愛）へ変更、設計原則12「地図表示エリア最大化優先」をcomplexity-review-2026-08-16.mdへ追記。副次的に`LocationControl.test.tsx`の`new RegExp(label)`が`[]`を文字クラスと誤解釈する回帰を発見・修正。frontend 238件・tsc・eslint全green、Playwright実機確認（デスクトップ・モバイル）済み |
| 2026-08-17 | T107（基盤フェーズ） | ユーザー相談（一次情報/二次情報の分離、二次情報側の重みを研究モード・将来は運用でも調整したい）を受け設計。交通ストレスの判定レシピをPython定数から`TrafficStressRecipe`（pydantic）へ外出しし、タイル（全ユーザー共有キャッシュ）には最終値でなく材料タグ（`cycleway_class`/`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`）だけを焼き込む方式へ変更（世代v8→v9）。最終値の計算はフロント（`trafficStressExpression.ts`、MapLibre expression、既定レシピは`export_openapi.py`書き出しJSON経由でPython側と同期）とルート採点（`domain/traffic.py`）がそれぞれ担う。`/api/routes/generate`にレシピのリクエスト上書きを追加、T90内訳ポップアップはGET→POST化。実装中にST_AsMVTがPostgres numeric型をtextへフォールバックする挙動をDB統合テストで発見・`::integer`キャストで修正（見逃せばフロントの数値比較も壊れていた）。今回は基盤のみで実際の調整UIパネルは次ラウンド。backend 733件・frontend 265件・tsc・eslint全green |
