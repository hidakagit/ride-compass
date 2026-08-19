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

### - [x] T52. JICE舗装点検DB 調査ゲート実行 規模S（調査のみ）— 2026-08-17完了・判定: 見送り（不採用）

- JICE窓口より返信受領（2026-08-17）。ゲート0〜2の結果:
  - ゲート0（利用資格・料金）: 個人の非商用R&D利用も申請可（利用者制約なし）。料金6万円+税、
    無償枠は上下100m単位集計データのみ（車線10m単位の詳細データは有償のみ）
  - ゲート1（緯度経度）: 記録単位区間別データ（車線10m単位）に道路中心線上の緯度経度は
    付与されているが、路線番号+距離標(KP)からの換算値であり車線別の実測位置ではない
    （原位置から数十mずれる場合がある、と窓口が明言）
  - ゲート2（関東の自治体道収録）: **ゼロ**。関東7都県で地方公共団体による舗装データの
    登録は無く、収録は直轄国道のみ
- 判定: **見送り（不採用）**。直轄国道のみの収録（trafficStress=4区分で、走りやすさ評価が
  主眼を置く生活道路・自転車専用道には届かない）・位置精度への懸念（換算値、数十mずれ）・
  料金6万円+税（個人開発・低頻度利用の現行規模に対し投資対効果が見合わない）の3点が重なり、
  ゲート3（対応付け精度実測、有償データ入手が前提）は未実施のまま見送りを確定した。
  商用化時の再配布条件（加工後の走りやすさ評価としての公開は再協議不要）は良好な回答を
  得ており、再訪条件とあわせて外部静的データソースレビュー§4.4に記録済み。
- 完了条件: ゲート0〜2の結果と判定を記録済み（本項目・外部静的データソースレビュー§4.4）。

### - [x] T53. JARTIC交通量によるtrafficStress較正 規模M（研究IF側の検証作業）（2026-08-18完了）

- 詳細設計は外部静的データソースレビュー§4.5参照。評価パイプラインには入れず、
  1回のスナップショット収集（`collect_jartic.py`新規、dev機PostgreSQLのみ保持）→
  観測点近傍エッジの`traffic_stress_level`と実交通量分布の突き合わせで完結させる。
  定期収集は較正に不足する場合のみ検討（停止条件を先に決めておく）。
- 完了条件: LTS段階間で交通量分布が単調に分離しているかの分析結果を記録し、
  分離が悪ければ`TRAFFIC_STRESS_BASE_BY_HIGHWAY`等の見直し材料とする。

**実装結果（2026-08-18完了）**:

- **収集（`backend/scripts/collect_jartic.py`新設）**: JARTIC WFS 2.0.0
  （`https://api.jartic-open-traffic.org/geoserver`、`t_travospublic_measure_1h`、
  登録不要・cql_filter必須）。実装中に2つの落とし穴を実測で確認・対処:
  (1) `観測年月日`＋`時間帯`から日時を再構成すると`時間帯`が1時間値では常に0で
  ValueErrorになる→自己完結な`時間コード`（YYYYMMDDHHmm）から直接parseへ変更。
  (2) このGeoServerデプロイは`count`/`startIndex`によるページングを完全に無視し
  （`startIndex`を変えても同一の全件セットが返り続ける）、範囲cql_filterで複数時間を
  一括要求すると非収束ループ化する→時間コード完全一致で1時間・1リクエストへ設計変更
  （`fetch_hour_features`、`collect()`が時間ごとにループ）。関東本土全域・1時間ぶんは
  単発リクエストで頭打ちなく全件（実測106件、道路種別=3=一般道）返ることを確認済み。
  収集先`traffic_stations`/`traffic_hourly`はスクリプト自身が`CREATE TABLE IF NOT EXISTS`
  で自己完結して用意し、`Base.metadata`・本番Oracle migration経路には一切含めない
  （外部静的データソースレビュー§4の「研究用データを本番に置かない」共通方針）。
  2026-08-14〜17の4日分・関東本土bboxを実DBへ収集（106観測点、日毎約5,000件の
  時間別レコード）。
- **分析（`backend/scripts/analyze_jartic_calibration.py`新設）**: 観測点を最寄りの
  osm_raw_ways（30m以内、domain/road.py: `SURFACE_MATCH_MAX_DISTANCE_M`と同じ許容量、
  `&&`前置＋`ST_DWithin(geography)`パターンはmeasure_axis_stats.pyと同じ）へ空間マッチし、
  `domain/traffic.py: traffic_stress_level`でLTS段階を算出、`traffic_hourly`の1日あたり
  平均交通量（上り+下り合算、収集日数で正規化）とLTS段階を突き合わせる。相関計算は
  `measure_axis_stats.py`の`pearson_correlation`/`spearman_correlation`をそのまま
  再利用（複製しない）。純関数（`group_volumes_by_level`/`summarize_group`/
  `is_monotonic_by_level`）は`test_analyze_jartic_calibration.py`で単体テスト。
  - 実装時の落とし穴: LATERAL内のKNN（`ORDER BY ... <->`）を`geography`型へ
    キャストすると`osm_raw_ways.geom`のGiST索引（geometry型）を使えず観測点ごとに
    全表スキャンになり実行が発散した→KNNは`geometry`のまま・距離判定のみ
    `ST_DWithin(geography)`にする（`EXPLAIN ANALYZE`で索引利用を確認、106観測点で
    217ms）。
  - **分析結果**: dev機PostgreSQLの`osm_raw_ways`は東京都心南部のみ（実測extent:
    lon 139.61-139.87, lat 35.58-35.79）にしか投入されておらず、関東本土全域で
    収集した観測点106件のうち30m以内にマッチするのはわずか8件（level4:2件・
    level5:6件、level1-3は無し）。8件の範囲では level昇順に平均交通量が単調非減少
    （level4平均20,787台/日 → level5平均24,897台/日、YES）、Pearson相関0.224・
    Spearman順位相関0.378と、方向性は`TRAFFIC_STRESS_BASE_BY_HIGHWAY`の想定
    （highway階級が上がるほど交通量も増える）と矛盾しない。ただしn=8・2段階のみで
    統計的な結論を出すには不十分（dev DBのosm_raw_waysカバレッジが東京都心南部に
    限られるための構造的制約であり、より広いLTS段階を横断した較正には本番相当
    （関東本土全域）のosm_raw_ways投入が必要。今回はスコープ外）。完了条件の
    「分析結果を記録」は満たしたが、`TRAFFIC_STRESS_BASE_BY_HIGHWAY`等の見直しを
    正当化するには材料不足のため、既定値は変更しない。
  - backend全green（847件、新規16件）。

**実装結果（続き・本番相当スケールでの再検証、2026-08-18）**: ユーザー指示によりdev DBの
カバレッジ制約を解消するため本番Oracle DBで再検証。事前に読み取り専用で本番`osm_raw_ways`
を確認（1,329,632way、関東本土bbox内1,327,099件=99.8%、緯度30度未満の外れ値は315件=0.02%と
軽微、migration 0001-0009はローカルと完全一致でラグ無し、`EXPLAIN ANALYZE`でLATERAL最近傍
マッチが133万way規模でも索引利用・9.3ms/クエリと確認）、追加のPBF再取込（最新化）は不要と
判断（全行`updated_at`が2026-08-16 18:13で統一されておりこの時点で既に最新）。
`collect_jartic.py --database-url`（新規、collect_jartic.pyには元々存在。
`analyze_jartic_calibration.py`側にも同じ引数を追加）で同じ4日分（2026-08-14〜17）を
本番へ再収集し、分析を再実行:

- マッチ観測点数がn=8→**n=68**（8.5倍）に拡大し、level3（1件）・level4（7件）・
  level5（60件）の3段階を横断（level1-2は依然0件、後述）。level昇順に平均交通量が
  単調非減少（level3: 16,652台/日 → level4: 23,573台/日 → level5: 29,762台/日、YES）を
  維持したが、相関は弱まった（Pearson 0.179・Spearman 0.164、n=8時点の0.224/0.378より
  低下）。level5内の分散が非常に大きい（最小6,773〜最大64,146台/日、約9.5倍）ことが
  主因と分析: JARTIC road_type=3（一般道）の観測点はそもそも幹線道路への設置に偏っており
  （観測点の88%=60/68がlevel5に集中）、同じhighway階級内でも都市部幹線と郊外幹線で
  実交通量が大きく異なるため、観測点の設置場所自体に高LTS側への選択バイアスがある
  （level1-2に相当する住宅街の道路はJARTICの継続観測対象になりにくい、データソース
  自体の構造的限界）。方向性（単調性）は維持されており`TRAFFIC_STRESS_BASE_BY_HIGHWAY`
  の想定と矛盾しないため、既定値は変更しない。分析後、`traffic_stations`/
  `traffic_hourly`は設計どおり本番から削除済み（`DROP TABLE`、削除確認済み）。
  backend全green（847件、変更なし。`--database-url`追加は純関数への影響なし）。

**実装結果（続き・高レベル帯の差別化材料とLV6要否の判断、2026-08-18）**: ユーザー相談
「幹線道路・高レベル帯での差別化に使えるか、カバレッジはどうか」「LV6細分化等の
メリットを考察して」を受け深掘り。本番DBへ同じ4日分を再収集（分析後`DROP TABLE`で
削除、以下すべて同サイクル）:

- **指定路線(is_designated)の実測差**: マッチ68件中、is_designated=True(62件)の
  平均交通量30,097台/日、False(6件)は16,902台/日と+78%の実差を確認。既存の
  `designation_adjustment=+1`の方向性を裏付ける（Falseがn=6と少なく量の再較正の
  根拠にはしない）。
- **クランプ前raw値の方が交通量とよく揃う**: クランプ後levelとの相関Pearson 0.179に
  対し、クランプ前raw値では0.309（Spearman 0.164→0.340）。level5(60件)のraw値は
  5-7に分布し42%(25件)が現行上限5を超える。
- **上記42%は選択バイアスの影響で母集団の割合ではない**: JARTIC road_type=3観測点は
  そもそも幹線道路（マッチ68件中64件がtrunk）への設置に偏っているため、この42%を
  「全道路の42%が天井超過」と読むのは誤り。判断材料として`measure_axis_stats.py`
  （`--database-url`引数を新規追加、collect_jartic.py/analyze_jartic_calibration.py
  と同じパターン）で母集団側のraw>5割合を測定: dev機（5.4万way）で1.0%件数/1.1%距離、
  **本番・関東本土全域（131万way）で0.9%件数/1.2%距離**とほぼ一致。T117が4→5拡張を
  決めた根拠（拡張前raw≥5が8.3%件数/9.3%距離）と比べ一桁小さく、T117の拡張で
  天井超過の大部分は既に吸収済みと判断。**LV6細分化は見送り**（母集団側の実測が
  明確に不要と示しており、JARTICの42%は「既知の少数派（母集団の約1%）の道路には
  確かに天井超えの実差がある」という補足証拠に位置づけを変更）。
  - 副次的に本番規模（131万way）での軸ペア相関も測定: Pearson 0.9468（距離加重
    0.9592）・Spearman 0.9522（距離加重0.9690）、dev機の0.9222/0.9145より高く、
    T121の軸独立性検討に対する追加参考値として記録。
- **`DEFAULT_BBOX`のカバレッジ確認**: ユーザー相談「関東本土が欠落していないか、
  広すぎるだけなら急ぎではない」を受け確認。`osm_raw_ways`のbbox外データ（3,957件・
  1,223.6km）はすべて南方向（伊豆諸島・小笠原、離島のため元々除外対象）で、北・東
  方向（茨城・千葉・栃木・群馬の本土側）へのはみ出しは0件。西方向（山梨県混入）を
  除けば関東本土の欠落は無いと確認したため、**`DEFAULT_BBOX`修正は見送り（優先度低、
  ユーザー了承）**。西の山梨県混入は無駄なAPI呼び出しが増えるのみで実害は無い。
  backend全green（847件、`measure_axis_stats.py`への`--database-url`追加は既存
  テスト23件に影響なし）。

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

### - [x] T56. 初回ルート生成時の地図タイル一過性表示崩れの再現性確認 規模S（調査・優先度低、2026-08-17クローズ）

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
- **クローズ（2026-08-17）**: headed Chromium（`headless: false`、Claude Browserペインではなく
  自前Playwrightスクリプト）で、デスクトップ幅（1280px）・モバイル幅（390px）それぞれ距離を
  変えて4回ずつ（計8回、18〜42km、ズーム幅を変動させる目的）「ルート生成」を実行し、候補到着
  直後から1.5秒間を150ms間隔で連続スクリーンショット（1回あたり11枚、計88枚）した。全ラウンド
  で英語ローマ字タイルの混在・縮小正方形描画のいずれも観測されず、コンソールエラーも0件。
  2026-08-16の観測がheadless固有（WebGLコンポジット周りの環境依存）だった可能性が高いと判断し、
  完了条件どおりクローズする。

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

### - [x] T91. MapView.tsx閾値監視の再設定〔統合レビューF-3〕規模S（2026-08-17完了）

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
- **完了（2026-08-17）**: 新閾値案（MapView.tsx 1,800行 or STATIC_OVERLAY_LAYERS 10種到達）を
  正式に採用し、`docs/complexity-review-2026-08-16.md`（R-6・Keep List・設計原則9）と
  `.claude/commands/review/context.md`のKEEP記載を「当初閾値は消化済み、T91で新閾値へ再設定」
  へ更新した。コード変更は不要（対応済みの2点はT47で完了済みのため）。現在値
  （2026-08-17時点: MapView.tsx 1,634行・STATIC_OVERLAY_LAYERS 6種）はいずれの閾値も未到達。

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

### - [x] T97. バックエンドpoi-tiles配信から交差点密度レイヤーを削除 規模S（2026-08-17完了）

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
- **対応（2026-08-17）**: `_POI_TILE_MVT_SQL`をstop_poiのみの単純なクエリへ簡素化し
  （intersectionレイヤーのCOALESCE枝・`bindparam("intersection_layer"/"degree_threshold")`を削除）、
  `vector_tile.py: INTERSECTION_LAYER_NAME`・`encode_empty_poi_tile`のintersection空レイヤー・
  `export_openapi.py`の`region-tile-config.json: poi.intersection_layer_name`出力を削除。
  `INTERSECTION_DEGREE_THRESHOLD`はルーティング材料（`get_intersection_counts`等）が
  引き続き使うため維持。`POI_TILE_VERSION`をv1→v2（backend/frontend対で更新）。
  DB統合テスト（intersectionレイヤーの次数検証）を削除、`regionApi.test.ts`のURL世代・
  コメントを更新。関連ドキュメント（region.py/region_service.pyの「POI・交差点密度」表記）も
  「POI」単独へ整理。backend 734件・frontend 265件・tsc・eslint全green。

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

### - [x] T101. 補給・休憩ポイントPOIレイヤー〔static-road-attributes-plan.md §2.3〕規模M（2026-08-18完了）

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

**実装結果（2026-08-18完了）**:

- **着手前の実店舗乖離リスク実測**: ユーザー懸念「実店舗とどれだけ合っているか」を受け、
  `backend/scripts/measure_poi_freshness.py`（新設、`measure_tag_coverage.py`と同じPBF1パス
  読み・単発実行の形式）でOSM側の最終編集日時（`check_date`/`survey:date`タグの付与率は
  2〜11%と低いため代理指標として使用）を関東全域で実測。コンビニは直近2年以内の編集が
  62.4%と明確に新しい一方、自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高いと
  判明。この結果を踏まえ、5種すべて取込対象にしつつ表示側で鮮度の差を利用者へ伝える方針にした
  （ユーザー承認）。単体テスト13件（`test_measure_poi_freshness.py`）つき。
- **バックエンド**: `domain/traffic.py`へ`classify_supply_poi`（`SupplyPoiKind`5値）を新設し、
  `classify_stop_poi`と同じ「node取込の対象判定を兼ねる」設計に揃えた。`osm_adapter.py:
  osm_node_to_poi_spec`は`classify_stop_poi(tags) or classify_supply_poi(tags)`で両分類を
  1回のnode走査で試す（タグ名が独立＝highway/railway vs shop/amenityのため優先順位は不要）。
  `import_profile.yaml`へ`convenience_stores`/`supply_amenity_nodes`の2ルールを追加（旧来の
  「将来の拡張例」コメントを実装で置き換え）。`ALLOWED_NODE_TAGS`へ`shop`/`amenity`を追加。
- **MVT配信はSQL無改修**: `_POI_TILE_MVT_SQL`は`osm_raw_pois.kind`を無条件で焼き込む設計
  だったため、新kind値の追加だけでバックエンド側は`POI_TILE_VERSION`世代上げ（2→3、
  ブラウザキャッシュのバスト用。フロント`regionApi.ts`と対で更新）のみで済んだ。
  `stop_poi`という1つのMVTレイヤーに停止要因・補給休憩の両kindが混在するため、フロント側で
  「独立した2レイヤーとして表示・トグルする」という完了条件を満たすには工夫が要った:
  `legendFilter.ts: buildCombinedLegendFilterExpression`へ`baseFilter`（凡例の非表示操作の
  有無に関わらず常にANDする恒常的な絞り込み）を追加し、`STATIC_FILTER_AXES`のstopPoi/
  supplyPoi軸それぞれに`["in", ["get","kind"], ["literal", STOP_POI_KINDS/SUPPLY_POI_KINDS]]`を
  設定。これが無いと、凡例で何も隠していない瞬間（`buildLegendFilterExpression`が
  `null`＝フィルタ無しを返す）に相手方のkindも一時的に見えてしまう不具合になるところだった
  （実装中に発見・設計で解消。MapView.overlayFilters.test.tsに再発防止テスト3件追加）。
- **フロント**: `staticAttributeLayers.ts`へ`SUPPLY_POI_CATEGORIES`（5色）・
  `SUPPLY_POI_LABELS/LEGEND/COLOR_EXPRESSION`・`STOP_POI_KINDS`/`SUPPLY_POI_KINDS`を新設。
  `mapLayers.ts`へ`supplyPoi`レイヤーを追加（安全・リスクの指標ではないため`trafficSafety`
  へは含めず、新設の`amenity`（補給・施設）カテゴリへ分離）。panelHintでコンビニと他4種の
  鮮度差を明記（「コンビニはOSMデータの更新が比較的新しく目安として使いやすい一方、
  自販機・トイレ・給水・駐輪場は閉店・撤去にデータが追いついていないことがあります」）。
  `MapView.tsx`は`ensureSupplyPoiLayer`（`ensureStopPoiLayer`と同じregion-poi-tilesソースを
  共有）・`STATIC_OVERLAY_LAYERS`/`LAYER_DATA_SOURCES`への行追加・ポップアップ
  （`buildSupplyPoiPopupHtml`）まで、既存のT47 R-6宣言的ループ・T63絞り込み軸カタログの
  おかげでほぼ機械的な追加で済んだ（`INTERACTIVE_LAYER_IDS`はSTATIC_OVERLAY_LAYERSから
  自動導出、page.tsxのチップ・凡例summaryも生成的で個別コード不要）。アイコンは買い物袋の
  シルエット（`icons.tsx: SupplyPoiIcon`）を新規。
- **データ**: dev機（Tokyo.osm.pbf、UPSERT冪等再取込）で`vending_machine`7,434件・
  `convenience`4,803件・`toilets`2,257件・`drinking_water`1,528件・`bicycle_parking`1,233件を
  確認（`measure_poi_freshness.py`の実測件数とほぼ一致）。
- **実機確認**: 開発サーバーを退避ポート（backend:8001・frontend:3011、T118と同じ考え方）で
  起動しPlaywright（headless chromium）で確認。「補給・休憩」チップのON切替、サイドバー
  「補給・施設」セクションの表示、`poi-tiles`タイルリクエストが`?v=3`で200を返すこと、
  地図上の点クリックで「補給・休憩: 給水」の正しいポップアップが出ることを確認
  （基礎地図タイル自体はこの検証環境のCDN到達性制約で読み込めなかったが、POI機能とは
  無関係と判断）。
- backend全873件（新規26件）・frontend全348件（新規22件）・tsc・eslint全green。

**実装結果（続き・本番バックフィル漏れとチップ幅の修正、2026-08-18）**: ユーザー報告
「補給・休憩を押してもデータがプロットされない」「アイコンが他横幅と揃っていない」を
受け対応。前者は本番Oracle DBへの`import_pbf.py`再実行（データバックフィル）を
dev機のみに対して行い、本番への反映を失念していたのが原因と判明（コードはmasterへ
push済みのため本番も動作はするが、`osm_raw_pois`に新kind行が1件も無く空振りしていた。
確認: 修正前の本番は`crossing`/`traffic_signals`/`stop`/`level_crossing`/`give_way`の
旧5種のみ）。ユーザー確認のうえ`import_pbf.py --database-url <本番>`で
`kanto-latest.osm.pbf`を再実行（全way・nodeも巻き込むUPSERT、実測1,421.5秒＝約23.7分）。
バックフィル後の本番`osm_raw_pois`で`vending_machine`17,349件・`convenience`14,182件・
`toilets`7,310件・`drinking_water`4,710件・`bicycle_parking`2,742件を確認（dev機実測と
ほぼ一致）。後者はチップの`chipLabel`が「補給・休憩」（読点込み5文字）で他レイヤー
（4文字以内）よりチップ幅が広がっていたため、読点を省いた「補給休憩」（4文字）へ短縮
（正式名称の`label`「補給・休憩ポイント」は変更なし）。

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

## 交通ストレスレシピ調整UIパネル（2026-08-17・T107の次ラウンド）

### - [x] T108. 交通ストレスレシピを実際に画面上で調整できるUIパネルを実装 規模M（2026-08-17完了）

- 背景: T107（基盤フェーズ）で交通ストレスの判定レシピを`TrafficStressRecipe`へ切り出し、
  `/api/routes/generate`・`/api/region/traffic-stress-breakdown`（POST）とも上書き可能に
  したが、実際にレシピを入力するUIが無く基盤が使われていなかった。
- ユーザー確認済みの方針: (1) レシピ上書きの有効/無効は既存`WeightPanel`の重み上書き
  トグルとは別トグルにする（レシピは有効化すると地図色が即座に変わるが、重みは次回の
  ルート生成まで反映されないという挙動差があるため）。(2) 地図上の交通ストレス凡例
  （1〜4カテゴリの表示/非表示チェックボックス）による絞り込みも、レシピ上書き中は動的に
  再計算する（凡例のラベル・色自体は不変、内部の`filter`式だけがレシピに追従する）。
- 調査で判明した重要な事実: `LegendEntry`の`filter`（MapLibre expression）を実際に使うのは
  `MapView.tsx`の`setStaticOverlayFilters`/`applyRoadLayerState`だけで、
  `MapLayersPanel.tsx`・`MapOverlayControls.tsx`は`color`/`label`/`key`/`isFallback`しか
  参照しない。そのため凡例を動的化してもこれら表示コンポーネントは無改修で済んだ
  （表示は変わらず、絞り込みの実体だけがレシピに追従する）。
- 対応:
  - `staticAttributeLayers.ts`: `TRAFFIC_STRESS_LEGEND`/`TRAFFIC_STRESS_COLOR_EXPRESSION`の
    生成ロジックを`buildTrafficStressLegend(recipe)`/`buildTrafficStressColorExpression(recipe)`
    として関数化。既存定数はこの関数を既定レシピで呼んだ結果として維持（無破壊）。
  - `MapView.tsx`: 新規props`trafficStressRecipe?`を追加。`setStaticOverlayFilters`が
    trafficStress軸だけ動的な凡例（`buildTrafficStressLegend`）へ差し替えつつ
    `applyTrafficStressRecipe`で`line-color`を`setPaintProperty`ライブ更新。地図初期化時
    （マウント時1回のuseEffect）に定義される`handleClick`は`redrawPropsRef.current`経由で
    最新のレシピを読み、区間クリックの内訳ポップアップ（`fetchTrafficStressBreakdown`・
    `evaluateTrafficStressLevel`）にも反映する（redrawAllLayersと同じstale closure対策）。
  - `TrafficStressRecipePanel`（新規、`WeightPanel`と同構造）: 独立トグル、highway別基準値
    13種のテーブル＋cycleway/maxspeed/lanes/指定路線の補正12項目を4つのfieldsetで編集、
    「既定値に戻す」ボタン（`DEFAULT_TRAFFIC_STRESS_RECIPE`、Python側と自動同期済みの単一
    ソース）。
  - `page.tsx`: 新規state（`trafficStressRecipeOverrideEnabled`/`trafficStressRecipe`）を
    `WeightPanel`と並べて配置し、`MapView`・`TrafficStressRecipePanel`・
    `/api/routes/generate`リクエスト・dirty判定キー（`currentWeightsKey`）すべてへ配線。
  - テスト: `staticAttributeLayers.test.ts`にカスタムレシピでの凡例・色分け式の検証3件、
    `TrafficStressRecipePanel.test.tsx`新規5件、`MapView.overlayFilters.test.ts`新規
    （フェイクmapで`setStaticOverlayFilters`がtrafficStress軸だけレシピに追従し他軸は
    不変であることを検証、`@maplibre/maplibre-gl-style-spec`のexpression評価器を実際に
    使ってfilter式の挙動差を確認）。
- 完了条件: backend変更なし（T107で完了済み）。frontend 275件・tsc・eslint全green（確認済み）。
  headed Playwrightでの実機確認も完了。研究モードON→レシピ上書きONの状態でhighway=primaryの
  基準値を4→2に変更したところ、対象道路の地図上の色が即座に変化（交通ストレス4/4→3/4）。
  同じ道路をクリックしたT90内訳ポップアップも変更後レシピで3/4を表示し、独立に呼び出した
  `/api/region/traffic-stress-breakdown`（同じ上書きレシピをbodyへ渡した場合）の結果とも
  一致（クライアント側`evaluateTrafficStressLevel`とサーバー側`traffic_stress_breakdown`の
  非同期実装が一致することを実地で確認）。凡例のレベル3チェックボックスを外すと、
  地図上のレベル3（オレンジ）道路が全域で消えることを確認（動的filter式が効いている証拠）。
  「既定値に戻す」ボタンで地図色・内訳とも即座に4/4へ復元。検証中コンソールエラーなし。

---

## 天候取得502の再発（2026-08-17・ユーザー報告）

### - [x] T109. Open-Meteo 429による天候取得502の再発を受け、再試行を強化（回数・バックオフ・全体予算） 規模S（2026-08-17完了）

- 発端: ユーザーがデバッグログとシステム状況サマリを提示。`weather:open-meteo`カテゴリの
  外部呼び出しが5件中5件とも失敗（最終失敗種別`http_429`、平均1946ms・最大2445ms）、
  フロントには`/api/weather`の502（`天候情報の取得に失敗しました`）が到達していた。
  T98で導入済みの単発呼び出し対策（`weather_client.py`: `MAX_RETRIES=2`・固定バックオフ
  0.3秒刻み・3時間以内のstale cache代用）をすり抜けての再発であり、当該座標の
  stale cacheも無かった（初回アクセス地点だったとみられる）ため完全な502になっていた。
- 対応: ユーザー承認のうえ「再試行を強化」の方針で実施。
  - `MAX_RETRIES`を2→4、バックオフを固定0.3秒刻みから指数（`RETRY_BACKOFF_SECONDS=0.5`を
    基数に`2**attempt`、`RETRY_BACKOFF_CAP_SECONDS=2.0`で単発上限をクランプ）へ変更。
    Retry-Afterヘッダを尊重する既存挙動もこの上限でクランプするよう統一。
  - 新規`RETRY_BUDGET_SECONDS=8.0`（待機合計の壁時計予算）を追加し、フロントの
    fetchタイムアウト（`weatherApi.ts`: 15秒）に対して十分な余裕を残したまま
    `MAX_RETRIES`に達する前でも打ち切れるようにした。429だけでなくTransportError
    （ConnectTimeout等）の再試行も同じ予算を共有するため、応答自体が返らない障害が
    連続した場合の総待機時間の上限も同時に押さえられる。
  - 既存の再試行テスト（`test_weather_client_cache.py`）は実時間で`asyncio.sleep`していたため
    `MAX_RETRIES`増加に伴う実行時間増加を避けるべく`asyncio.sleep`をno-opへ差し替える
    autouseフィクスチャを追加。新規に予算切れで早期打ち切りを検証するテストを1件追加。
- 完了条件: backend全735件green（新規テスト含む、実時間の追加待機なし）。
  `RETRY_BUDGET_SECONDS`により429連続時の総待機が実測上限内（バックオフ合計最大
  0.5+1.0+2.0+2.0=5.5秒、429応答は通常速いため実際の総所要はこれに近い）に収まることを
  ロジック上確認。根本原因（Render共有IPに対するOpen-Meteo側のレート制限）自体は
  クライアント側の再試行では解消できないため、有料/専用キー化の検討は
  今回のスコープ外としてユーザーとの選択肢提示のみ行った（再発時に再検討）。

---

## 研究パラメータの導線改善（2026-08-17・ユーザー報告）

### - [x] T110. 研究モードのトグルと調整パネル（評価重み・交通ストレスレシピ）を独立した「研究」ブロック/タブへ切り出し、「設定」→「開発者」へ改名 規模M（2026-08-17完了）

- 発端: ユーザー報告「重み付けを変える画面にスマホだと辿り着けない」。調査の結果、
  研究モードのON/OFFトグル（`ResearchPanel`）は「C. 設定」ブロックに、それが有効化する
  `WeightPanel`・`TrafficStressRecipePanel`は「A. ルートを作る」ブロックにあり、
  スマホでは両者が別々のBottomSheet（タブ）に分かれているため「設定タブでONにしても、
  効果がどのタブに出るか分からない」導線になっていたと判明。
  さらにユーザー自身の指摘（「ルート作成時も地図表示時にもそのパラメータを使う認識なので
  親子関係ではない」）通り、`page.tsx`の既存コメントは「A. ルートを作る」ブロックの契約を
  「編集は生成ボタンを押すまで地図へ影響しない」と明記していたが、
  `TrafficStressRecipePanel`は地図の色分けへ即時反映されるためこの契約に反した状態で
  Aブロックに同居していた（T108実装時に見直されていなかった）。
- 対応: 「設定」（ログ・システム状況・疎通確認・キャッシュ更新という運用/デバッグツール）
  とは混ぜず、かつA/Bどちらの子でもない、独立した4つ目のブロック/タブ「研究」を新設。
  研究モードのトグルと、その効果である`WeightPanel`・`TrafficStressRecipePanel`を
  同じ画面に同居させることで、トグルを入れる場所と実際に使う場所がタブを跨ぐという
  問題そのものを解消した。`ComparisonPanel`（実験スロット比較表）は入力パラメータではなく
  生成結果の一覧のため、`RouteList`の並びである「A. ルートを作る」に残した。
  デスクトップはサイドバーへ「研究」`<details>`ブロックを1つ追加（既定閉、「設定」と
  同じ扱い）、モバイルは`MobileSheet`型・タブボタン・`BottomSheet`をそれぞれ1つ追加
  （`tabButtonSmall`で「設定」と同じ控えめ幅、4タブとも375px幅で重ならず収まることを
  実機確認）。`BottomSheet`コンポーネント自体は汎用propsのみのため無改修で追加できた。
- 完了条件: frontend 275件・tsc・eslint全green。headed Playwright（自前スクリプト）で
  モバイル幅（375px）の4タブ表示・「設定」タブに研究モードトグルが無いこと・「研究」タブ
  内でOFF→ONに切り替えた瞬間に同じシート内へ`WeightPanel`・`TrafficStressRecipePanel`が
  現れること、デスクトップ幅でも同様の挙動を確認、いずれもコンソールエラー0件。
- 追記（同ラウンド）: ユーザーから「画面下部のメニュー名を実態に合わせて修整して」との
  追加依頼。「設定」ブロックは元々研究モードのトグルも含む何でも入れ場所だった名残の名前で、
  トグルを「研究」へ分離した後は一般ユーザー向けの環境設定が一切無い、純粋な開発者/運用
  ツール集（デバッグログ・システム状況・疎通確認・キャッシュ更新）になっていたため実態と
  ズレていた。ユーザーへ選択肢（開発者/デバッグ/システム/変更しない）を提示し「開発者」を
  選択、`renderSettingsSectionBody`→`renderDeveloperSectionBody`・`SETTINGS_SHEET_TITLE_ID`→
  `DEVELOPER_SHEET_TITLE_ID`・`MobileSheet`の`"settings"`→`"developer"`を含め表示名・
  内部識別子とも一貫して改名（「地図の見え方」用の`MAP_SETTINGS_SHEET_TITLE_ID`は無関係の
  ため対象外）。「ルートを作る」「地図の見え方」「研究」は中身と合っているため変更なし。
  frontend 275件・tsc・eslint全green、Playwright実機確認（タブラベル`[ルートを作る,
  地図の見え方, 研究, 開発者]`・開発者タブに研究モード関連が0件・デスクトップサイドバーに
  「開発者」ブロックがあり「設定」ブロックが残っていないこと）でコンソールエラー0件。

---

### - [x] T111. モバイル下部タブのアイコン化、交通ストレスレシピ調整パネルの用語日本語化 規模M（2026-08-17完了）

- 発端: T110のフォローアップとしてユーザーから2件の依頼。(1) モバイル下部タブが文字のみで、
  特に「開発者」（`tabButtonSmall`=4rem幅）が折り返されて読みにくい。(2) 交通ストレスレシピ
  調整パネルの要素名（highway別基準値のラベル等）が技術的（OSMタグ語彙そのまま）で
  分かりにくいので、日本語の論理的なラベル＋具体的な属性説明（情報アイコン）にしてほしい。
- 対応(1): 地図上のiconChip（`MapOverlayControls.module.css`、アイコン+1行ラベルの縦積み）
  と同じ構成をモバイル下部タブへ適用。新規アイコン3種（`MapAppearanceIcon`/`ResearchIcon`/
  `DeveloperIcon`、`icons.tsx`の既存線画スタイルに統一）を追加、「ルートを作る」は既存の
  `RouteIcon`（地図上のルート絞り込みチップと共有）を流用。`page.module.css`の`.tabButton`を
  flex column化、`.tabLabel`（0.62rem・`white-space: nowrap`）で1行固定にし、以前の
  文字だけのボタンで発生していた折り返しを解消。
- 対応(2): `TrafficStressRecipePanel.tsx`のhighway別基準値13項目・スカラー12項目すべてに
  日本語の論理的なラベル＋`description`（情報アイコンのツールチップ、対応するOSMタグ・値を
  明記）を追加。highway別ラベルは`roadFilterAxes.ts`「道路の種類」軸の分類語（幹線道路/
  主要道/生活道路等）と整合させつつhighway値ごとに個別化。以前の「利用者はOSMタグ語彙を
  前提にしている」という設計判断（T108時点）をユーザーの実利用フィードバックを受け撤回し、
  タグ語彙は情報アイコンのツールチップ側へ退避する形へ転換。情報アイコンは新規`InfoIcon`
  （`StatusIcon`と同形だが用途が異なるため別名で追加）、ツールチップは既存のtitle属性規約
  （weatherHeader等と同じ、長押し/ホバーで見える補足）を踏襲。`WeightPanel`のラベル
  （`evaluationAxes.ts`カタログ、既に自然な日本語）は対象外と判断し変更していない。
  副次的に、`TrafficStressRecipePanel.module.css`に残っていた重複`.resetButton`定義
  （T110直前のcomposes化フィックス時の消し忘れ）を発見・削除した。
- 完了条件: frontend 275件・tsc・eslint全green。headed Playwrightでモバイル幅（375px）の
  4タブがアイコン+1行ラベルで折り返しなく収まること（ラベル高さ実測で1行相当を確認）、
  `highway=primary`/`highway=primary_link`の情報アイコンが前方一致の罠なく1件ずつ
  区別されること、コンソールエラー0件を確認。

---

### - [x] T112. 情報アイコンのtitle属性ツールチップをクリック開閉ボタンへ作り直し（スマホでタップしても開かない不具合） 規模S（2026-08-17完了）

- 発端: ユーザー報告「infoアイコンを押しても説明が出ない」。T111で実装した情報アイコンは
  `<span title={description}>`（weatherHeaderと同じ、ホバーで開くtitle属性）だったが、
  title属性のツールチップはブラウザのhover状態に依存し、スマホのタップ操作ではhover状態が
  発生しないため実機では一切開かないという設計ミスだった（デスクトップのマウスホバーでしか
  検証していなかった）。
- 対応: `TrafficStressRecipePanel.tsx`の`FieldLabel`をクリック/タップで確実に開閉する
  ボタン（`aria-expanded`+`aria-label`、`MapOverlayControls`の凡例展開トグルと同じ規約）へ
  作り直した。説明本文はopen状態のときだけ描画する別要素とし、スカラー項目は`.field`
  ラベル行の直後に`<p>`として、highway別基準値テーブルは行の直後に`colSpan={2}`の説明行
  （`<tr>`）として追加（`<td>`内にブロック要素を積む案はテーブル構造上避けた）。テーブル行は
  `.map()`コールバック内で`useState`を呼べないため、開閉状態を持つ専用の`HighwayRow`
  コンポーネントへ切り出した。
- 完了条件: frontend 276件（新規1件、クリック開閉の回帰テスト）・tsc・eslint全green。
  headed PlaywrightをiPhone 13デバイスエミュレーション（`hasTouch: true`）＋`tap()`で
  実行し、実機のタップ操作を再現したうえで、highway別基準値・スカラー項目双方の情報
  アイコンがタップで開閉すること（ユーザー報告の再現→解消を確認）、コンソールエラー0件を確認。

---

### - [x] T113. 交通ストレスレシピ入力フォームの見た目を改善（基準値=レベルピッカー、補正値=0中心バー、閾値=横並び） 規模M（2026-08-17完了）

- 発端: ユーザー依頼「基準値は低→高で1-4をプログレスバーで選択（4は将来的に5や6に変えられる
  ように）。補正値は0を中心に変動、変動条件はその横に個別設定できるようなイメージ」。
- 対応:
  - 基準値（highway別13項目）: 数値入力欄から、低→高の押しボタンが並ぶレベルピッカー
    （`StressLevelPicker`）へ変更。選択値以下の段階を地図と同じ色で塗り進捗バー風に見せる。
    段階数・色は`staticAttributeLayers.ts`の`TRAFFIC_STRESS_COLORS`を新規exportして
    単一ソース化し（このファイルはexportされたMapへキーを追加するだけで済むよう
    `Object.keys(...).sort()`から段階数を導出）、地図の色分けと将来にわたり自動的に一致する。
  - 補正値（自転車インフラ3項目・指定路線1項目・maxspeed/lanes計4項目）: 0中心の水平バー
    （`AdjustmentBar`）を数値入力の横に追加。負値（ストレス軽減）は最低段階の色、正値
    （ストレス増加）は最高段階の色で塗り、こちらも`TRAFFIC_STRESS_COLORS`から導出（ハード
    コードした色の二重管理を避ける）。表示スケールは±2に調整（既定値の実際の範囲-2〜+1に
    対し±4スケールだと塗りがほぼ見えず「常に0付近」に見えてしまうと実機確認で判明したため）。
  - 変動条件（maxspeed/lanesの閾値4項目）: 従来は補正値と別々の独立行だったのを、
    `ThresholdAdjustmentField`/`ThresholdAdjustmentRow`で1行にまとめ、補正値バーの
    すぐ下（横）に条件（例: 「条件 [30] km/h以下」）を個別編集できるようにした。
- 完了条件: frontend 277件（新規1件、閾値/補正値の対フィールドが独立して正しいキーを
  更新することの回帰テスト）・tsc・eslint全green。headed Playwrightでモバイル幅（375px）で
  横スクロールが発生しないこと、レベルピッカーのクリックで正しい`base_by_highway`更新が
  呼ばれること、対フィールドの閾値/補正値入力が独立して動作することを確認。スクリーンショット
  で0中心バーの視認性を目視確認し、当初のスケール（±4）が実質見えないと判明したため
  ±2へ調整した（本文参照）。

---

### - [x] T114. 補正値の0中心バーが実質見えない・数値入力が入力しにくい問題を-/+ステッパーへ作り直し、全体をコンパクト化 規模M（2026-08-17完了）

- 発端: ユーザー報告「補正値、水平バーが出ておらず数字入力。入力しにくいので改善して。
  全体的にもう少しコンパクトな形にしたい」。T113で±2スケールへ調整した0中心バーは、
  実機ではmin-widthの塗りが数px程度にしかならずバーとして知覚されず、数値入力単体は
  ネイティブの上下スピナー矢印が小さくタップしづらいという2つの問題が残っていた。
- 対応: `AdjustmentBar`を廃止し、`-`/`+`ボタンで挟んだ数値入力（`AdjustmentStepper`）へ
  作り直した。入力欄自体の背景色を負値（ストレス軽減）は最低段階の色、正値（ストレス増加）
  は最高段階の色で塗りつぶす（`TRAFFIC_STRESS_COLORS`から算出、T113と同じ単一ソース）ことで、
  細い塗り幅に頼らず常に確実に「0中心に変動している」ことが伝わるようにした。数値入力欄
  そのものは残しているため直接タイプでの入力も引き続き可能。ネイティブのスピナー矢印は
  CSSで非表示にし、増減は左右の大きな-/+ボタンで行う。あわせて「もう少しコンパクトに」
  への対応として、閾値+補正値の対フィールド（低速/高速道路・多車線/少車線道路）を縦2段
  から横並び1行（幅が足りなければ折り返し）へ、レベルピッカーのボタンサイズを1.5rem→
  1.25remへ、グループ間・フィールド間のgapを詰めた。実装中にラベルが右側の内容に押し
  縮められて「低速道路」が「低速」「道路」の2行に割れる回帰を実機確認で発見し、ラベル側に
  `flex-shrink: 0`/`white-space: nowrap`を付けて修正した。
- 完了条件: frontend 278件（新規1件、-/+ボタンでの増減の回帰テスト）・tsc・eslint全green。
  headed Playwrightで-ボタンのクリックにより値が実際に1減ること、375px幅で横スクロールが
  発生しないこと、スクリーンショットでラベルの折り返し崩れが解消していることを確認、
  コンソールエラー0件。

---

### - [x] T115. 「研究」の中身（評価重み・交通ストレスレシピの各グループ）をMapLayersPanelと同じ折りたたみ式へ統一 規模M（2026-08-17完了）

- 発端: ユーザー依頼「地図の見え方の中身と同じように、研究の中身も折りたたむようにして。
  表示しているときのみ折りたたみ解除まで合わせるべきか、どこまで合わせるかは考えて」。
- 検討: `MapLayersPanel.tsx`のレイヤー折りたたみ（T38、`<details>`+`<summary>`、デフォルト
  全閉）を精査したところ、開閉状態はレイヤーの表示ON/OFF（`layerVisibility`）とは
  完全に独立していると判明（OFF中のレイヤーも設定を開いて確認・編集でき、開閉状態は
  ON/OFFと無関係に保たれる）。この設計は「今どれを見たいか」という純粋なUI都合であり、
  有効/無効の状態と連動させる理由が無いための独立設計と判断。よって「研究」側も同じ
  考え方で、各グループの開閉を評価重み/交通ストレスレシピの上書きON/OFFトグルとは
  連動させず、独立したUI状態として実装した（合わせたのは「details+summary、デフォルト
  全閉」という折りたたみの仕組みそのものまでで、開閉のトリガー条件までは合わせていない）。
- 対応: `WeightPanel.tsx`の2つの`<fieldset><legend>`グループ、`TrafficStressRecipePanel.tsx`
  の5つの`<fieldset><legend>`グループを、いずれも`<details><summary>`（chevron付き）へ
  変更。CSS（`.groupHeader`/`.groupChevron`/`.groupBody`）は`WeightPanel.module.css`へ
  新規追加し、`TrafficStressRecipePanel.module.css`は既存のcomposes方式で再利用（新規の
  重複CSSを作らない）。
- 完了条件: frontend 278件・tsc・eslint全green（jsdomは`<details>`の閉状態に伴う
  UAスタイルシート由来の非表示化を再現しないため、既存テストの一部はsummaryクリックで
  明示的に開いてから検証するよう更新）。headed Playwrightで、両パネルの各グループが
  初期状態で非表示（折りたたみ済み）であること、summaryクリックで開くこと、再クリックで
  閉じることを実機で確認、コンソールエラー0件。

---

### - [x] T116. 「研究」タブを「評価の重み」「レシピ」のカテゴリへ分割、レシピの今後の追加に備えて括り出し 規模S（2026-08-17完了）

- 発端: ユーザー依頼「評価の重みと、交通ストレスのレシピは扱いを分けて欲しい。別タブに
  するかは微妙だと考えるが、同じタブの中でもグループ化はしたい。交通ストレスのレシピに
  ついても、今後ほかの2次データのレシピが増えると思うので、くくり出してほしい」。
- 対応: 別タブ化はせず（ユーザー自身も判断が難しいとした点）、「研究」タブ内を
  「評価の重み」（`WeightPanel`）と「レシピ[一次情報→二次情報の変換式]」
  （`TrafficStressRecipePanel`）の2カテゴリへ見出しで分割した。見出しの見た目は
  `MapLayersPanel.tsx`のカテゴリ見出し（道路状態/交通・安全等、`.groupTitle`）と
  composesで揃え、新規の重複CSSを作らないようにした。「レシピ」カテゴリは現状
  交通ストレスレシピの1つのみを内包するが、今後増える他の二次情報（自転車インフラ分類等）の
  レシピ化にも対応できるよう、同カテゴリの`<div>`内へパネルを追加するだけで済む構成に
  しておいた（現時点で複数レシピを扱う汎用的なレジストリ機構までは作らず、実際に2つ目の
  レシピが出た時点で必要なら抽象化する判断とした——1件しかない状態で将来の複数件を
  見越した汎用化をするのは過剰と判断）。
- 完了条件: frontend 278件・tsc・eslint全green。headed Playwrightで「評価の重み」
  「レシピ[一次情報→二次情報の変換式]」の2見出しが表示され、評価の重みがレシピより
  上に配置されていること、375px幅で横スクロールが発生しないことを確認、コンソール
  エラー0件。

---

## 交通ストレス5段階化（2026-08-17・ユーザー要望「変動要素が多く1-4はもう少し細かく
段階評価してもよい」）

### - [x] T117. 交通ストレスのクランプ上限を4→5へ拡張し、primary/trunk/指定路線の悪化要因を独立レベルとして可視化 規模M（2026-08-17完了）

- 発端: ユーザーから「交通ストレスは今1-4評価だが、変動要素が多くもう少し細かく段階評価
  してもよいと感じる。妥当な段階数を検討、提案して」という相談。「実測から始めて」との
  指示を受け、実装前にdev DB実データ（39,878way・道路網5,737.6km）でクランプ前の生値分布を
  実測した。
- 実測結果:
  - クランプ前の生値はraw=2が61.9%（件数）/55.9%（距離）を占め圧倒的多数。residential/
    unclassified等（合計69%）が制限速度・車線数タグをほぼ持たず補正が一切効かないまま
    基準値2に張り付くためで、タグの裏付けが無い以上これ以上の細分化はできない。
  - 一方raw≥5（従来level4に丸め込まれ区別不能）は8.3%（件数）/9.3%（距離）存在し、
    primary（73%該当）・trunk（78%該当）・primary_link/trunk_link（62%該当）に集中。
    指定路線（N10/N12）だけで見るとraw≥5が39.2%、raw=4と合わせ77.1%が現行level4に
    押し込まれており、T92記載の実測「78.3%」ともほぼ一致し手法の妥当性を確認。
  - 結論: 上端（level4→5への分割）は実データで裏付けられるが、下端（level1〜2）を
    増やす根拠は無し。5段階（下限1据え置き、上限4→5拡張）を採用。
- 対応:
  - `domain/traffic.py: traffic_stress_breakdown`のクランプを`min(4, ...)`→`min(5, ...)`へ。
  - `domain/difficulty.py: _TRAFFIC_STRESS_MAX_LEVEL`を4→5（区間難易度への正規化上限）。
  - `trafficStressExpression.ts`のMapLibre expression（`["min", 4, ...]`→`["min", 5, ...]`）を
    Python側と同期。
  - `staticAttributeLayers.ts: TRAFFIC_STRESS_COLORS`へ5番目の色を追加。旧level4の色（赤
    `#dc2626`）を新level5（最悪）へ引き継ぎ、新level4には中間色（オレンジ`#f97316`）を
    割り当てた。凡例ラベルは4「注意」・5「ストレス大」に再配分。`TrafficStressRecipePanel`の
    基準値ピッカーは`TRAFFIC_STRESS_COLORS`のキーから段階数を動的に導出する設計
    （T108で「段階数を4→5等へ増やす場合はここへキーを追加するだけ」と設計済み）のため
    無改修で追従。
  - `mapLayers.ts`のpanelHint/panelHintDetail、`MapView.tsx`のポップアップ内訳説明文
    （TRAFFIC_STRESS_SCALE_INTRO）を「5段階[1=快適〜5=ストレス大]」「1〜5の範囲」へ更新。
  - `export_openapi.py`の相互検証フィクスチャへ`("primary", {}, True, None)`（指定路線
    primaryでraw=5ちょうど）を追加し、新しい上限境界をPython⇔JS双方でテストする。
  - バックエンドテスト（`test_traffic.py`・`test_difficulty.py`・`test_region_service.py`）の
    旧上限4を前提にしたアサーションを新結果へ更新（`test_result_is_clamped_to_1_4_range`→
    `_1_5_range`、`test_is_designated_clamped_to_4`→`_on_primary_reaches_5`等）。
- 作業環境: このタスク着手時、`docs/improvement-plan.md`が同時に別セッション（同一
  ディレクトリ、未コミットの「安全度」9軸目実装が進行中と判明・pytest収集エラー17件で
  非green状態）と衝突するリスクを検知したため、ユーザー承認のうえ`git worktree`
  （`.claude/worktrees/traffic-stress-5levels`、ブランチ`traffic-stress-5levels`）で作業を
  完全に分離した。node_modules/venvは元ディレクトリのものをコピー・npm installで独立確保し、
  Playwright実機確認・pytest/vitest実行はすべてこのworktree内で完結させた。
- 完了条件: backend 736件（新規1件含む）・frontend 279件・tsc（環境起因の1件を除き無関係の
  新規エラー無し）・eslint（変更ファイル）全green。headed Playwright実機確認（1280px幅）で
  凡例の5段階（1〜5）が正しいラベル・色（`#16a34a`/`#84cc16`/`#f59e0b`/`#f97316`/`#dc2626`）で
  表示されること、panelHintの「5段階[1=快適〜5=ストレス大]」表示を確認。

### - [x] T118. T117で5段階に増えた基準値ピッカーがモバイル幅で画面外へ溢れる不具合を修正 規模S（2026-08-17完了）

- 発端: ユーザーが本番サイト（Render、モバイル実機スクリーンショット）を提示。「研究」タブの
  交通ストレスレシピ「道路種別ごとの基準値」テーブルで、ピッカー（1〜5の5ボタン）がパネル
  右端から画面外へ溢れていた。T117で4→5段階化した際、デスクトップ幅（1280px）のみ確認し
  モバイル幅での実機確認を怠っていたための回帰。
- 調査所見（2点、いずれも実データで確認）:
  1. **列幅共有によるテーブル全体の折り返し**: `<table>`は標準（`table-layout: auto`）では
     列幅を「同じ列に属する全行中もっとも幅を要求する行」で決めるため、`.tableLabel`側の
     `.fieldLabel`が`white-space: nowrap`だと、どこか1行でも長いラベル（例:
     「高規格の幹線道路(連絡路)」）があるだけでテーブル全体が右へ押し広げられ、ラベルが
     短い行（「自転車専用道」等）でもピッカー列が圧迫されて3+2の不格好な2段組みに
     折り返されていた（`.tableLabel .fieldLabel`のnowrap解除＋`.table`を
     `table-layout: fixed`化、ピッカー列（`.tableValue`）へ固定幅7.5remを与えて解決）。
  2. **原因不明のCSSカスケード上書き**: 上記1の対応後も、ローカル検証環境（`next build`＋
     `next start`、および正しいstandalone起動`node .next/standalone/server.js`のいずれでも
     再現）で`.levelSegment`の`width: 1.25rem`/`padding: 0`がグローバルな`button`既定
     （`globals.css`、`padding: 0.5rem 0.9rem`）に上書きされ続ける現象を確認。クラスセレクタ
     （詳細度0,1,0）はエレメントセレクタ（0,0,1）より高いはずで、CDP
     `getMatchedStylesForNode`相当の手動照合でも`.levelSegment`の該当ルールが対象要素へ
     マッチしていることを確認済みだが、原因を特定できなかった（`@layer`なし、`!important`
     なし、より詳細度の高い競合セレクタなし）。実害（見た目のボタンサイズ肥大化）が確定して
     いたため、`width`/`height`/`padding`へ`!important`を付与する対症療法で解決し、原因究明は
     打ち切った。次に同種の症状（クラスセレクタが効かない）が出た場合の手がかりとして記録
     しておく。
- 作業環境: T117と同じ理由（別セッションによる同一ディレクトリでの未コミット作業）に加え、
  検証用に起動したdev/prodサーバーのポート（8000/3010）がいずれかのタイミングで**自分が
  起動したのではないプロセス**（別セッションの安全度9軸目実装ぶん、`node_modules`配下の
  パスがメインディレクトリを指していた）に奪われていたことが判明し、誤ったビルドを検証
  してしまっていた期間があった（上記2の原因不明カスケードもこの誤検証中の産物だった
  可能性がある）。ユーザー承認済みのworktree方針を踏襲しつつ、**ポートも8001/3011へ
  変更して完全分離**し、以降は`netstat`でリッスン元プロセスのコマンドラインを都度確認
  してから検証する運用にした。
- 完了条件: backend 736件・frontend 279件・tsc・eslint（変更ファイル）全green。Playwright
  実機確認（モバイル390px幅、本番相当のstandaloneサーバー起動）で「自転車専用道」（短い
  ラベル）「高規格の幹線道路(連絡路)」（最長ラベル）を含む全13行が1行5ボタンのまま折り返さず
  収まり、`document.documentElement.scrollWidth`が`clientWidth`を超えないこと（横スクロール
  無し）を確認。

---

### - [x] T119. 安全度レシピの新設（9軸目）＋事故密度の精度改善 規模L（2026-08-17完了）

- 発端: ユーザー相談「交通ストレス、今は路面状態や走行のしやすさを評価しているが、
  別軸で安全度みたいなのも作れない？道路種類、灯りの有無、交通事故密度等、既存の他データも
  組み合わせて評価ファクターになりそうなものを考えてほしい」。ブレインストーミングで
  4候補（対自動車安全度/夜間走行安全度/路面・転倒リスク/初心者・ファミリー適性）を提示し、
  ユーザー選択で対自動車安全度＋夜間走行安全度を「安全度」という1つの意味づけへ統合する
  方針に合意。事故密度の扱い（新レシピへ組み込むか既存`accident_weight`軸のまま精度改善するか）
  と、その精度改善を研究モード限定にするか既定挙動にするかの2点はAskUserQuestionで確認し、
  いずれも「既存軸を精度改善」「既定挙動として反映」を選択。
- 対応: 交通ストレスレシピ（T107〜T116）と全く同じ構造を「安全度」用に新設。
  - **バックエンド**: `domain/safety.py`（新規）に`SafetyRecipe`/`safety_breakdown`/
    `safety_level`/`safety_tile_ingredients`を実装（`domain/traffic.py`の対応関数と1:1対応。
    highway別基準値は交通ストレスと別の数値セット、cycleway/maxspeed/lanes分類は
    `cycleway_class`を公開化して共有）。安全度のみが持つ補正: 路肩（`shoulder_adjustment`）・
    街灯（`lit_adjustment`）・トンネル（`tunnel_adjustment`）。lanes_low（少車線）は
    採用しない（安全側かは研究上見解が分かれるため）。`safety_recipe.yaml`＋
    `evaluation_service.py: load_safety_recipe`、`compute_edge_cost`/両エンジン/DIへの配線、
    `route_preference.yaml`へ`safety_weight: 0.10`追加、`api/routers/routes.py`へ
    `SafetyRecipeOverride`・`GenerationConditions.safety_recipe`、`api/routers/region.py`へ
    `POST /api/region/safety-breakdown`を追加。`domain/difficulty.py`へ`safety_difficulty`
    （交通ストレスと同じ1-4→0-100区分線形、T117の5段階化とは無関係に安全度は1-4のまま）を
    追加し`AxisDifficulties`を8軸→9軸へ拡張。
  - **MVTタイル**: `_ROAD_SURFACE_TILE_MVT_SQL`へ`shoulder`/`lit`材料タグを追加
    （`motor_vehicle_no`と同じCASE式パターン、tunnelは既存プロパティを再利用）、
    `ROAD_SURFACE_TILE_VERSION`を`"9"`→`"10"`（backend/frontend対、プロパティ追加のみで
    後方互換のためv9のような特別なデプロイ順序制約は無い）。
  - **事故密度の精度改善**（既定挙動として反映）: `get_accident_counts`/
    `get_nearest_accident_counts`の`bicycle_only`既定値を`False`→`True`へ変更（自転車ルート
    案内で自動車同士のみの事故まで数えていたのを是正）。単純COUNTから死亡事故を
    `ACCIDENT_FATAL_WEIGHT`（`domain/accident.py`、暫定値3.0）件分として積算するSUMへ変更し
    戻り値がint→float化。実装中、SQLのCASE式が`LEFT JOIN`不一致行（`a.fatal`がNULL）を
    誤って1件と数える回帰を自己発見し、`WHEN a.accident_id IS NULL THEN 0`を先頭に追加して
    修正（新規テストで検知できることを確認）。`GraphService.get_accident_counts`に欠けていた
    `bicycle_only`引数も追加。
  - **フロントエンド**: `frontend/src/components/Map/safetyExpression.ts`
    （`trafficStressExpression.ts`と同型のMapLibre expressionミラー）、
    `staticAttributeLayers.ts`へ`SAFETY_COLORS`（teal→olive→orange→dark-red、交通ストレスの
    緑〜赤と色相をずらし混同を防ぐ）・`buildSafetyLegend`/`buildSafetyColorExpression`・
    `StaticFilterAxisId`の`"safety"`追加、`mapLayers.ts`へ`"safety"`レイヤー（交通・安全
    カテゴリ、`panelHintDetail`で判定基準を明記）追加。`MapView.tsx`へ`SAFETY_LAYER_ID`・
    `ensureSafetyLayer`・`applySafetyRecipe`・安全度内訳ポップアップ（`fetchSafetyBreakdown`）
    を配線。T113で交通ストレス専用に実装した基準値レベルピッカー・補正値ステッパー・
    情報アイコン開閉ボタンを、2つ目のレシピ登場を機に`frontend/src/components/Map/
    recipeControls.tsx`（`LevelPicker`/`AdjustmentStepper`/`FieldLabel`、色パレット・
    段階配列を引数化）へ汎用化し、`TrafficStressRecipePanel.tsx`もそちらを使うよう移行
    （見た目・挙動は無変更）。新規`SafetyRecipePanel.tsx`（`recipeControls.tsx`を使用、
    路肩・街灯・トンネル補正グループを追加）を実装し、`page.tsx`の「レシピ」カテゴリ
    （T116で複数レシピを想定して設計済みの`<div>`）へ`TrafficStressRecipePanel`の直後に追加。
    `evaluationAxes.ts`へ`safety_weight`、`ComparisonPanel.tsx`へ`safety_score`行を追加。
    新規`SafetyIcon`（盾のシルエット）を地図チップへ追加。
- 作業環境・マージ: T117（同日、別セッションが`git worktree`で完全分離実装した交通ストレス
  5段階化）と並行して同じファイル群（`domain/difficulty.py`・`domain/traffic.py`・
  `domain/route.py`・`road_graph_repository.py`・`export_openapi.py`・`MapView.tsx`・
  `mapLayers.ts`・`staticAttributeLayers.ts`(+test)・`evaluationAxes.ts`・生成物等）を
  変更していたため、pushされたT117を`git pull`（rebase）で取り込んだところ
  `docs/architecture.md`・`docs/improvement-plan.md`・`frontend/src/types/generated/
  openapi.json`の3ファイルでコンフリクトが発生（他ファイルはgitが自動マージ）。手動解消の
  うえT番号の重複（両者ともT117を名乗っていた）をユーザー承認のうえT118へ改番したが、
  push直前に同じ別セッションがさらに`fix: T117の基準値ピッカーがモバイル幅で溢れる不具合を
  修正(T118)`をpush（`TrafficStressRecipePanel.module.css`/`.tsx`・`docs/improvement-plan.md`
  が対象）しており、そちらも独立にT118を名乗っていたため再度T119へ改番。このモバイル幅
  修正（table-layout: fixed・ピッカー列の固定幅7.5rem・ラベルの折り返し許可）は
  `SafetyRecipePanel`も交通ストレスと全く同じhighway別基準値テーブル構造を持つため
  同一の不具合を抱えていると判断し、`SafetyRecipePanel.module.css`/`.tsx`へも同じ修正を
  横展開した。
- 完了条件: backend 781件（新規50件超）・frontend 334件（新規約60件、`safetyExpression.test.ts`
  ・`SafetyRecipePanel.test.tsx`・`recipeControls.test.tsx`・既存4ファイルへの追加を含む）・
  tsc・eslint全green（マージ後に再実行して確認）。DB統合テスト（shoulder/lit材料タグ抽出・
  死亡事故重み付けSQL・bicycle_only既定値）はdev機ネイティブPostgreSQLへ実接続して実行・
  確認済み。headed Playwright実機確認（2レシピパネル並列表示・地図の安全度レイヤー配色・
  内訳ポップアップ・375px幅レイアウト）はマージ前に実施済み。

---

### - [x] T120. T119レビュー指摘の修正: 安全度内訳のDB例外が/api/debug/statsに計上されない不具合ほか 規模S（2026-08-18完了）

- 発端: T119完了後のコードレビューで、`region_service.py: get_traffic_stress_breakdown`の
  DB例外処理を`fields["lookup"]="error"`から`fields["result"]="error"`＋`fields["warned"]=True`
  （`log_external_call`側に新設した二重WARNING抑制フラグ）へ修正した際、同じファイル内の
  双子メソッド`get_safety_breakdown`には同じ修正が反映されておらず、docstringが「完全に
  同じ構造」と明言しているにもかかわらず旧パターンのまま残っていることが判明。
- 対応:
  - `get_safety_breakdown`のDB例外処理を`get_traffic_stress_breakdown`と同じ
    `result`/`warned`パターンへ修正（回帰テスト`test_safety_breakdown_db_error_is_counted_
    in_debug_stats`を追加）。
  - 両メソッドとも`fields["error_type"]`が未設定だったため、他の`log_external_call`呼び出し元
    （`weather_client.py`等）と同じ規約（`error_type_label(exc)`を設定）に揃え、
    `/api/debug/stats`の`error_types`集計が常に`"unknown"`一色になる問題も併せて修正。
  - `docs/logging.md`に`warned`フラグの使い方（`result`+`warned`+`error_type`の3点セット）を
    追記（CLAUDE.mdが「ログ方針はdocs/logging.mdに従う」と明記しているにもかかわらず未記載
    だったため）。
  - コードレビューでも指摘された「`fields`という汎用dictへ制御用フラグ`warned`を混在させる
    設計」自体の見直し（専用キーワード引数化等）は、既存の`cache`/`status`/`lookup`等も
    同様にドキュメント上の慣習に過ぎず型レベルでは予約されていないため許容範囲と判断し、
    今回は見送り。
- 完了条件: backend 786件全green（新規2件含む）。frontend側は今回の対象外
  （`debug_log.py`/`region_service.py`はバックエンドのみ、`docs/logging.md`はドキュメント）。

---

### - [x] T121-a. SafetyRecipeOverrideの閾値順序検証漏れを修正 規模S（2026-08-18完了）

- 発端: 安全度と交通ストレスの独立性検証（ユーザー相談「相関していて判断要素も似ているなら
  まとめて切り出すのはありか」）の過程で、`TrafficStressRecipeOverride`にだけ閾値順序検証
  （`maxspeed_low_threshold < maxspeed_high_threshold`、前回コードレビュー指摘の修正）を
  追加し、双子モデル`SafetyRecipeOverride`には同じ検証が反映されていないことが判明
  （2軸のレシピをコピペで実装している構造そのものが原因、T120と同種の「片方だけ直す」
  パターンの再発）。
- 対応: `SafetyRecipeOverride`へ`_check_threshold_order`（`TrafficStressRecipeOverride`と同型、
  安全度は`lanes_low`が無いため`maxspeed`のみ検証）を追加。回帰テスト
  （`test_generate_routes_rejects_invalid_request_body`へパラメータ追加）。
- 完了条件: backend 787件全green。

### - [x] T121. 安全度base値の事故密度較正 規模M（2026-08-18完了）

- 発端: 安全度と交通ストレスの独立性検証（dev DB 39,878way実測、2026-08-18）で、
  Pearson相関0.91（距離加重も同）・Spearman 0.86と判明。TS=5は100%が安全度4、TS=4も
  70%が安全度4で、両端では安全度が交通ストレスからほぼ完全に予測できてしまう。
  原因は`SAFETY_BASE_BY_HIGHWAY`が`TRAFFIC_STRESS_BASE_BY_HIGHWAY`とほぼ同じ考え方
  （交通ストレス側の判断のコピペに近い暫定値）で決められており、安全度が謳う
  「事故りやすさ・客観的リスク」を実データで裏付けていないため。既に投入済みの
  `accident_points`（外部静的データソースT50、fatal/involves_bicycle列・座標あり）を
  使えば新規データ取得なしで較正できる。
- 対応: `_ACCIDENT_COUNTS_SQL`（road_graph_repository.py）と同じ空間マッチパターン
  （30m・`&&`前置・`involves_bicycle`絞込み・死亡事故`ACCIDENT_FATAL_WEIGHT`重み付け）を
  `osm_raw_ways`全体（highway階級ごと）へ適用し、密度（重み付き件数/km/年、
  収録3年で正規化）を実測。
  - **primary/primary_link/trunk/trunk_link**（7.8〜9.0）・**secondary**（6.65、
    secondary_linkは標本222way・14.7kmで参考値10.4）は現行base（4・3）を裏付ける
    明確なクラスタを形成しており変更不要。
  - **tertiary/tertiary_link**（3.6〜3.7）が現行baseの同居先（residential 1.88・
    unclassified 2.77）より明確に高く、secondaryとresidential系の中間に位置。
    T92と同じ手法（lanes/maxspeed分布）で追加検証したところ、tertiaryはlanes付与率
    50%（うち81%が2車線）・maxspeed付与率34%（40km/h以上が49%）とsecondaryに近い
    構造を持つ一方、residential/unclassifiedはほぼ単路・30km/h以下
    （lanes付与4〜9%のうち76〜82%が1車線、maxspeed付与5〜13%のうち97%が30km/h以下）
    で一貫しており、tertiaryを2のまま据え置く根拠が薄いと判断。**tertiary/
    tertiary_linkのbaseを2→3へ較正**（`domain/safety.py`・`safety_recipe.yaml`・
    生成物`safety-recipe.json`/`safety-test-cases.json`を同期、テスト13箇所更新）。
  - **cycleway/living_street**（2.19/2.02）はresidential（1.88）よりわずかに高いが、
    自転車専用/準専用インフラは通行する自転車自体が多いため、自転車台数で正規化しない
    生の密度は曝露バイアスで見かけ上高く出うる。「安全度1が不適切」の根拠にはせず
    据え置き。**residential/unclassified/track**も、密度差（1.88 vs 2.77）が
    tertiaryほど明確でなくlanes/maxspeed分布も同傾向のため据え置き
    （trackはway数11・延長0.9kmで標本不足のため判断対象外）。
  - `accident_weight`軸との二重計上を避けるため、較正結果は`SAFETY_BASE_BY_HIGHWAY`の
    オフライン設計材料としてのみ使い、`safety_breakdown`の実行時入力（材料タグ）には
    追加していない（T119合意の継続）。
- **較正後の相関再測定（想定外の結果）**: Pearson相関は0.91→**0.9559**（距離加重
  0.9613）、Spearman 0.86→**0.9651**へ**上昇**した。TS=3群（tertiary/tertiary_link/
  secondary/secondary_link、交通ストレス側は元々T92で3に統一済み）が、較正前は
  安全度2/3に58.5%/38.5%で分裂していたが、較正後は安全度3に96.0%集中したため。
  つまり実データに基づく較正がむしろ2軸を接近させた。これは「tertiaryの危険度が
  客観的に高い」という同じ実態を、交通ストレス（T92、走行のしやすさの観点）と安全度
  （T121、事故密度の観点）が独立に検出し収束したもので、較正自体の妥当性は補強される
  一方、**現状の材料タグ構成では2軸の差別化の主因はlit/shoulder/tunnelという
  「安全度だけが持つ補正」に依存しており、そのうちshoulderは実測0.0%（T102）・
  litはdev DBが採用前取込のため0件**（T121-a起票時点のメモ参照）という点が、
  相関上昇によってより明確になった。T122（次タスク）のdev DB再取込（lit有効化）の
  優先度がこの結果により上がったと判断する。
- 完了条件: highway階級別事故密度の実測結果を記録（本文参照）、`SAFETY_BASE_BY_HIGHWAY`を
  較正（tertiary/tertiary_link 2→3）。較正後の相関を再測定し変化を記録（達成、
  ただし想定と逆に上昇）。backend 787件・frontend 335件・tsc・eslint全green
  （frontend側は`safetyExpression.test.ts`の閾値越えテスト1件を較正後の値へ更新）。
  T122の重み再考は、この相関上昇を踏まえて「まず軸を差別化してから重みを判断する」
  順序が崩れていないため、T122側で改めて判断する。
- **追記（2026-08-18、dev DB再取込後の再測定）**: ユーザー指示「lit有効化後に相関再測定
  してから確かに判断したい」を受け、dev DB（東京都心南部、`data/pbf/Tokyo.osm.pbf`）を
  現在のロード範囲（`ST_Extent(geom)`実測bbox）で`python -m app.batch.import_pbf`
  再取込（UPSERTのため冪等、既存データは上書き）。way数39,878→57,112（差分17,234件は
  T99のshared_pedestrian_waysルール追加分17,584件とほぼ一致、想定内）。`lit`タグが
  0件→6,681件（11.7%）へ有効化された。
  - 相関を再測定した結果、Pearson 0.9559→**0.9222**（距離加重0.9613→0.9288、
    Spearman 0.9651→0.9145）へ**低下**。lit補正が実際に差別化に寄与することを確認。
  - 副次的な発見: 安全度4段階の上限丸め損失も8.5%件数/9.5%距離→**4.3%件数/5.0%距離**
    へ半減した（lit補正が上限へ張り付く前に値を引き下げるため）。T122で提案していた
    安全度5段階化は、この数値で見るとT117が交通ストレスを5段階化した根拠
    （8.3%/9.3%）の半分程度まで下がっており、着手の優先度は当初想定より低いと
    判断材料が変わった。T122着手時に再判断する。

### レシピ付き軸の共通基盤整備（T122〜T124、2026-08-18再構成）

複雑度平衡性レビュー（`history/2026-08-18_complexity.md` F-1/F-2）の指摘
「レシピ付き軸が共有基盤なしの全層コピーで2軸分存在し、追加コスト64ファイル・
双子鏡像約1,500行/軸・同期バグ2件実発生（T120・T121-a）」への対応。
ユーザー相談「2軸作るのはいいが、将来的な拡張も踏まえて軸パラメータの汎用化や、
相関検討・新たな要素の注入・重みづけ変更を容易にする対応は検討できるか」を受け、
**1つの汎用フレームワークではなく性質の違う3層に分けて必要な深さだけ共通化する**
構成で再起票した（recipeControls.tsxの「2回目で共通化」原則の踏襲。
AxisRegistry的なフレームワーク化は2軸の現時点ではpremature、レビューKEEP
「Recipeの4表現は統一しない」も維持。重みづけ変更は変更コスト表B行のとおり
既にYAML1箇所で易のため対象外）。3つ目のレシピ軸の追加はT122・T123完了まで
凍結する（レビューTop 10 Actions #10）。着手順はT124（独立・先行可）→T122→T123で、
T124・T122・T123とも2026-08-18完了。3つ目のレシピ軸の追加凍結はここで解除。

### - [x] T122. レシピ判定プリミティブの共有: domain/recipe.py新設＋shoulder撤去（層1）規模M（2026-08-18完了）

- 発端: `TrafficStressRecipe`/`SafetyRecipe`が「highway別基準値＋タグ由来の加減点＋
  クランプ」という同一の採点構造をパラメータだけ変えて2回実装しており、T120・T121-aの
  「片方だけ直し忘れる」バグを構造的に誘発している（複雑度レビューF-2）。フロントの
  `recipeControls.tsx`（T119、2つ目のレシピ登場を機にユーザー要望で共通化済み）と
  同じ発想をbackend domain層にも適用する。
- 対応方針:
  - `app/domain/recipe.py`（新設）へ共有プリミティブを切り出す:
    `clamp_level`（クランプ）・`threshold_adjustment`（maxspeed/lanesのlow/high
    if/elif分岐）・`cycleway_adjustment`（track/lane/shared分岐）・
    `flag_adjustment`（shoulder/lit/tunnel/designationのような「タグ有無→±N」。
    レシピ項目追加＝変更コスト表H行12〜15箇所の削減に効く）。
    閾値順序検証（`_check_threshold_order`系）もここへ集約し、`routes.py`の
    `*Override`APIモデル2箇所のコピペ検証（T121-aで片方だけ直した箇所）を1本化する。
  - `domain/traffic.py`/`domain/safety.py`をプリミティブ経由の薄い実装へ統一する。
    `*Recipe`モデル・`*_breakdown`関数・`*Override`APIモデル自体はフィールド集合が
    異なる（交通=lanes_low、安全度=shoulder/lit/tunnel）ため軸ごとに残す
    （無理に共通のPydanticモデルへ寄せない）。
  - `shoulder_adjustment`をレシピ・YAML・APIモデル・フロントから撤去
    （T102実測0.0%・dev DB再取込後も0件の「死に補正」。「根拠のない補正を追加しない」
    という`domain/safety.py`自身の方針との矛盾解消。YAMLコメントへ実測値を残し、
    地域拡大時の復活判断材料とする。MVTタイルの`shoulder`材料タグ焼き込みも外すため
    `ROAD_SURFACE_TILE_VERSION`の対上げが必要）。
  - **安全度の1-5段階化は本タスクから分離済み・要再判断**: 当初根拠（上限丸め損失
    8.5%/9.5%、T117の8.3%/9.3%と同水準）はlit有効化後の再測定で4.3%/5.0%へ半減し
    前提が崩れた（T121追記参照）。着手する場合はT117と同じ手順
    （`domain/safety.py`クランプ・`_SAFETY_MAX_LEVEL`・`safetyExpression.ts`・
    `SAFETY_COLORS`・内訳ポップアップ・タイル世代の同期）。
- 完了条件: 両軸のbreakdown/level計算が`recipe.py`経由になり、クランプ・閾値分岐・
  cycleway/flag補正・検証の双子分岐が1箇所化。生成フィクスチャ照合
  （traffic-stress/safety-test-cases.json）が引き続き全green（プリミティブ化で
  計算結果が変わっていないことの回帰保証）。backend/frontend全green。
- 実装メモ（2026-08-18完了）: `app/domain/recipe.py`を新設し、`clamp_level`・
  `threshold_adjustment`・`cycleway_adjustment`・`flag_adjustment`・`tag_value_is`・
  `validate_threshold_order`の6プリミティブに加え、`parse_lanes`/`parse_maxspeed`/
  `cycleway_values`/`cycleway_class`（旧`_cycleway_values`はpublic化）をtraffic.pyから
  移設（safety.pyがtraffic.py経由で間接importしていた旧構成を解消、循環import回避）。
  `threshold_adjustment`はlow/high閾値のどちらを先に判定しても`low<high`が保証されて
  いれば結果が同じになる（2条件が排他的なため）ことを確認し、旧traffic.py（lanesはhigh
  優先）・旧safety.py（maxspeedはlow優先）の実装差異を1つの関数へ統合した。
  `routes.py`の`_check_threshold_order`は`validate_threshold_order`呼び出しへ1本化
  （T121-aの再発防止）。shoulder撤去は`SafetyRecipe`/`SafetyBreakdown`/
  `SafetyRecipeOverride`/`safety_recipe.yaml`/MVT SQL（`_ROAD_SURFACE_TILE_MVT_SQL`）/
  `safetyExpression.ts`/`SafetyRecipePanel.tsx`から実施し、YAMLへT102実測値（0.0%）を
  コメントで残した。MVTタイル世代をv10→v11（backend `ROAD_SURFACE_TILE_VERSION`・
  frontend `regionApi.ts`の対）へ更新。`test_traffic.py`のparse_lanes/parse_maxspeed
  テストは`test_recipe.py`（新設）へ移設し、新規プリミティブの単体テストを追加。
  backend 839件（新規21件）・frontend 334件・eslint全green（フルスイート実行時に
  SafetyRecipePanel/TrafficStressRecipePanelの情報アイコン開閉テスト5件がタイムアウトで
  落ちたが、該当ファイルのみの分離実行では16/16全green。T121で確認済みの環境リソース
  競合によるflakeと判断。tscは別セッション未コミットの`vitest.config.mts`変更由来の
  エラーが既に存在しておりT122とは無関係、本タスクでは不変更のまま）。

### - [x] T123. レシピ軸の糊のパラメータ化＋MapView閾値発火対応（層2）規模L（2026-08-18完了）

- 発端: 複雑度レビューF-1（MapView.tsx 1,908行でT91閾値1,800行が発火）＋F-2
  （3つ目のレシピ軸を現方式で足すと約2,150行へ・追加コスト64ファイルの主因が
  service/router/fetch/popup各層の双子鏡像）。両者の対応作業が重なるため1タスクに束ねる
  （レビューPhase 3相当）。
- 対応方針:
  - `region_service.py`の内訳取得双子（`get_traffic_stress_breakdown`/
    `get_safety_breakdown`）を、同ファイルの`_get_tile`（road_surface/poiを1実装で
    捌く既存の成功前例）と同じ形の`_get_breakdown(repository_method, domain_fn,
    category)`へ畳む。`region.py`の2エンドポイントも薄い宣言だけ残しパラメータ化。
  - `regionApi.ts`のfetch双子を軸設定オブジェクト渡しの1関数へ。
  - MapView.tsxの内訳ポップアップ双子（`buildTrafficStressBreakdownHtml`/
    `buildSafetyBreakdownHtml`＋ハンドラ配線、約158行）を軸別カタログ＋共通ビルダー化し
    専用モジュール（例: `recipeBreakdownPopup.ts`）へ抽出。
  - `trafficStressExpression.ts`/`safetyExpression.ts`の補正ブロック生成を共有ヘルパー化
    （T122のプリミティブのTS鏡像。照合フィクスチャがドリフトを検知する体制は維持）。
  - `useLayerDataStatus`抽出（`computeLayerDataStatus`・`clearStaleTrackedSourceErrors`・
    イベント配線、約120行。2026-08-17レビューDEFER(a)の事前合意の履行）。
- 効果の見込み（レビュー試算）: MapView.tsx 1,908→約1,600行（T91閾値発火の解消）、
  3つ目のレシピ軸の追加コスト概算64→40ファイル前後・鏡像行数約半減、
  レシピ項目1個の追加コスト12〜15箇所→7〜9箇所（SQL材料タグ・YAML・パネル・テストの
  軸固有部分のみ残る）。
- 完了条件: 上記5点の抽出・パラメータ化が完了しMapView.tsxが1,700行未満。
  次の閾値（レビューF-1提案: 「2,000行 or STATIC_OVERLAY_LAYERS 10種 or 3つ目の
  レシピ軸をMapView内へミラー追加しようとした時点」のいずれか早い方）を
  `/review:improve`経由でKeep Listへ反映。backend/frontend全green・Playwright実機確認
  （内訳ポップアップ2軸とも表示・配線が抽出後も動くこと）。
- 実装メモ（2026-08-18完了）: 5点すべて実装。
  - `region_service.py`: `get_traffic_stress_breakdown`/`get_safety_breakdown`を
    `_get_breakdown(domain_fn, external_call_name, label, osm_way_id, recipe)`経由の
    薄いラッパーへ統一（`_get_tile`と同じ方針）。`region.py`は`_breakdown_response`
    （歯止め＋サービス呼び出し）で2エンドポイントの共通部分を1本化。
  - `regionApi.ts`: `fetchTrafficStressBreakdown`/`fetchSafetyBreakdown`を
    `BreakdownAxisConfig`（path/recipeBodyKey/debugKey/errorLabel）渡しの
    `fetchBreakdown<TRecipe, TBreakdown>`へ統一。
  - `recipeBreakdownPopup.ts`（新設）: `buildTrafficStressBreakdownHtml`/
    `buildSafetyBreakdownHtml`＋`attach*Handler`（計148行）を、補正フィールド名→ラベルの
    `adjustmentLabels`（Record、記述順=表示順）を持つ`RecipeBreakdownAxisConfig`渡しの
    1実装へ集約。内訳行は`Object.entries(adjustmentLabels)`でBreakdownのフィールドを
    動的に読む（`measure_axis_stats.py: adjustment_field_names`と同じ「新しい補正が
    増えてもこのモジュール自体は変更不要」という設計）。
  - `recipeExpression.ts`（新設）: `trafficStressExpression.ts`/`safetyExpression.ts`の
    MapLibre expression断片組み立て（`cyclewayAdjustmentExpr`/`thresholdAdjustmentExpr`/
    `flagAdjustmentExpr`/`designationAdjustmentExpr`/`baseByHighwayExpr`/`clampLevelExpr`/
    `buildRecipeLevelExpression`/`evaluateRecipeLevel`）を集約（`domain/recipe.py`の
    TS側ミラー）。`threshold_adjustment`と同じくlow/highどちらを先に判定しても
    `low<high`前提下では結果が同じことを利用し1実装化。
  - `useLayerDataStatus.ts`（新設）: `computeLayerDataStatus`/`clearStaleTrackedSourceErrors`
    （純関数）と状態管理（`erroredSourceIdsRef`・`lastStatusRef`・`recompute`・
    `markSourceErrored`/`clearSourceLoading`/`notifySourceData`/`settleViewport`）を
    抽出。MapView.tsxとの循環import回避のため`LAYER_DATA_SOURCES`（ROAD_TILE_SOURCE_ID等
    への依存）はMapView.tsx側に残し、フックへ引数として渡す設計にした
    （`computeLayerDataStatus`の第4引数化）。map.on(...)自体の登録は他の関心事のハンドラと
    同じ巨大useEffect内に残し、各ハンドラの中身だけをフックの関数へ委譲する形にとどめた
    （登録自体の分離は`map`インスタンスの生成タイミングとの結合が強く、かえって複雑化する
    と判断）。
  - MapView.tsx: 1,905→1,654行（目標1,700行未満を達成）。
  - react-hooks/exhaustive-depsが`layerDataStatus.recompute`のようなプロパティアクセスの
    ままだとオブジェクト全体への依存を要求してくるため、フックの戻り値は呼び出し側で
    個々の関数へ分割代入して使う（`useCallback`の安定参照をそのまま活かす）。
  - 新閾値（レビューF-1提案どおり）をdocs/complexity-review-2026-08-16.md（R-6・Keep
    List・設計原則9）へ反映（`/review:improve`ではなくT91と同じ直接編集）。
    `.claude/commands/review/context.md`は既に「T91→T123」という前方参照になっており
    追加編集不要だった。
  - 検証: backend 839件・frontend 334件（フルスイート、5件のtimeoutはSafetyRecipePanel/
    TrafficStressRecipePanelの分離実行で16/16green・環境リソース競合によるflakeと判断）・
    eslint・tsc（別セッション未コミットの`vitest.config.mts`変更が既存のtsc型エラーを
    含んでいたため、一時的にコメントアウトして確認→`git checkout`で復元する手順で検証）
    全green。Playwright実機確認（headless chromium、東京都心南部の実データ）で交通ストレス・
    安全度の両ポップアップが最終値まで正しく表示されコンソールエラー0件を確認。

### - [x] T124. 軸統計計測スクリプトの常設化: measure_axis_stats.py（層3）規模S〜M（2026-08-18完了）

- 発端: T121〜T121続きの独立性検証で使った相関測定・クランプ前生値分布・材料タグ
  カバレッジ・highway階級別事故密度の各分析は、すべて使い捨てスクリプトで実施して
  破棄した。次の較正・3軸目追加・5段階化再判断のたびに書き直すのは無駄で、
  「実測してから判断する」文化（T92・T117・T121の判断はすべて実測起点）を
  1コマンドで支える計測基盤が要る。ユーザー相談「今回みたいな相関検討を容易にする
  対応」への直接回答。
- 対応方針: `backend/scripts/measure_axis_stats.py`（新設）。`measure_tag_coverage.py`
  （T102の判断を支えた前例）と同じ「単発実行・結果を標準出力・単体テストつき」の形で:
  - 軸ペアの同時分布と相関（Pearson/Spearman、距離加重込み）
  - クランプ前生値分布（段階数判断用。上限/下限丸め損失の件数%・距離%）
  - 材料タグカバレッジ（死に補正の検出。shoulder=0%のような矛盾を早期に出す）
  - highway階級別の自転車関与事故密度（base較正用。`_ACCIDENT_COUNTS_SQL`と同じ
    30m・involves_bicycle・死亡事故重み付けパターン）
  - 実装メモ: `osm_raw_ways`の`highway`は専用列（tagsに無い）。designationは
    `designation_attributes`をosm_way_idでDISTINCT JOIN。レシピはdomain関数を
    直接呼び出して計算する（SQL再実装しない。T121の使い捨て版と同じ方式）。
- 完了条件: dev DBに対して1コマンドで上記4分析が出力され、T121の実測値
  （相関0.9222・丸め損失4.3%/5.0%等）が再現できること。単体テスト（分布・相関計算の
  純関数部分）つきでbackend全green。docs/architecture.mdのscripts一覧に追記。
- 実装メモ（2026-08-18完了）: 相関・丸め損失・補正発火率の3つは`Breakdown`モデル
  （`TrafficStressBreakdown`/`SafetyBreakdown`）のフィールドを動的に拾う実装にした
  （`raw_pre_clamp_level`はbase+全`*_adjustment`フィールドの単純合計、
  `AdjustmentFiringCounter`は`*_adjustment`/`*_override`フィールド名一覧を
  `model_fields`から取得）ため、将来レシピへ補正フィールドが増減してもこのスクリプト側の
  変更は不要（カタログ化）。事故密度は`_ACCIDENT_COUNTS_SQL`と同じ`&&`前置＋
  `ST_DWithin(geography)`パターンをhighway単位集計に変えたSQLで計算し、密度の正規化
  自体は既存の`distance_weighted_accident_density`をそのまま再利用（SQL側で再実装しない）。
  `infrastructure/database.py: get_engine()`はWebリクエスト用に`command_timeout=20秒`が
  掛かっており、本スクリプトの全way集計クエリ（dev DBで54,342way）はこれを超えて
  `TimeoutError`になったため、`app/batch/*.py`と同じくタイムアウト無しの専用エンジンを
  スクリプト側で生成する方式にした。
  - dev DBで実行し完了条件を確認: Pearson 0.9222（距離加重0.9288）・Spearman 0.9145
    （距離加重0.9255）、安全度の丸め損失（raw>4）4.3%件数/5.0%距離と、T121の実測値と
    完全一致した。shoulder_adjustmentの発火率0.0%（死に補正）も再現し、T122での撤去判断
    の裏付けが自動計測でも再現できることを確認した。
  - 完了条件どおりbackend全green（810件、新規23件）。docs/architecture.mdの
    `backend/scripts/`へ本スクリプトを含む一覧を追記（従来このディレクトリは
    未記載だったため、既存スクリプトも合わせて追記した）。

---

## テストスイート実行効率化の検討事項（2026-08-18・フロントvitestタイムアウト調査より）

### - [x] T125. frontend vitestのtestTimeoutをコールドスタート耐性のある値へ引き上げ 規模S（2026-08-18完了）

- 発端: ユーザー報告「SafetyRecipePanel.test.tsx/TrafficStressRecipePanel.test.tsxが
  `npm test`で5000msタイムアウトする」を受けて調査。node_modules未インストールの
  フレッシュなworktreeで`npm install`後に初回実行したところ、`情報アイコンの説明開閉`
  実装自体は存在する（T119でTrafficStressRecipePanel専用実装から`recipeControls.tsx:
  FieldLabel`へ汎用化済み、ボタンのaria-labelも一致）にもかかわらず、3件のテストが
  5000msちょうどをわずかに超えて（5.0〜6.4秒）タイムアウトした。同じ2ファイルを
  キャッシュが温まった状態で再実行すると16件全てpassし、原因は実装欠落ではなく
  Vite変換・jsdom環境セットアップのコールドスタートコスト（初回はenvironment
  39.56秒・transform 7.16秒、2回目はenvironment 24.61秒・transform 3.87秒）が
  vitestデフォルトの`testTimeout`5000msと競合したことと判明。T54完了条件確認
  （2026-08-16、記録参照）で見た「vitest workerタイムアウト1件、並行セッション
  資源競合による偽陽性」と同じ症状クラスだが、今回は並行セッションが無くても
  単独のコールドスタートだけで再現した点が新規知見。CI（`.github/workflows/ci.yml`、
  T1）はnode_modulesをキャッシュ復元する前提のためこれまで顕在化していなかった可能性が
  あるが、新規worktree作成直後にテストを実行するユーザー・エージェントのワークフローでは
  再発しうる。
- 対応方針: `frontend/vitest.config.mts`の`test`設定へ`testTimeout`を明示追加
  （現状値未設定＝vitest既定5000ms）。コールドスタート実測（初回6.4秒）に対して
  十分な余裕を持たせた値（例: 15000ms）へ引き上げる。個別テストへ`it(..., { timeout })`を
  都度指定する方式は取らず、グローバル既定を上げることでこの種の環境起因の偽陽性を
  一律に防ぐ（該当テスト固有の問題ではなく全テストに共通する環境オーバーヘッドのため）。
  時間があれば`environment`セットアップ自体が数十秒かかっている点（`vitest.setup.ts`の
  内容確認）も合わせて調査する価値があるが、必須ではない。
- 完了条件: `node_modules`を一度削除した状態から`npm install`→`npm test`のコールド
  実行を再現し、タイムアウトによる失敗が発生しないことを確認。frontend全件green。
- 実装メモ（2026-08-18完了）: `vitest.config.mts`の`test`設定へ`testTimeout: 15000`を追加。
  完了条件の「`node_modules`削除→`npm install`」は、この作業ディレクトリが複数の並行
  セッションと共有されており他セッションの依存関係を巻き込むリスクがあるため、実測の
  コールドスタート要因（Vite変換キャッシュ、`node_modules/.vite`）だけを削除して同等の
  コールド状態を再現する方式に代えた。この状態で`npx vitest run`を実行し334件全green
  （タイムアウト失敗0件）を確認。
  - 副次的な発見: `vitest.config.mts`の`environmentMatchGlobs`（別コミットbe9fc95由来）が
    インストール済みvitest 4.1.10の型に存在せず`npx tsc --noEmit`がエラーになる
    （CIのtscゲートを壊している可能性）ことを発見。Vitest 4では同オプションが廃止されて
    おり、ランタイムでも意図通り機能していない懸念があるが、T125のスコープ外のため
    別タスクとして切り出した（spawn_task、2026-08-18）。

### - [x] T126. vitest.config.mtsのenvironmentMatchGlobsをVitest 4対応の方式へ修正 規模S（2026-08-18完了）

- 発端: T125の副次的発見（上記参照）を切り出したタスク。`environmentMatchGlobs`は
  Vitest 1〜3系にあった設定オプションで、インストール済みvitest 4.1.10
  （`frontend/package.json: "vitest": "^4.1.10"`）では廃止されており存在しない。
  `npx tsc --noEmit`が`InlineConfig`型エラーで落ちる（`.github/workflows/ci.yml`の
  frontendジョブはeslint→tsc→vitestの順で、tscゲートが壊れていた）だけでなく、
  一時的なプローブテスト（`typeof window`をログ出力）で確認したところランタイムでも
  黙って無視されており、`src/services/**`等をnode環境へ振り分ける意図が実際には
  機能していなかった（全ファイルが既定のjsdomのまま実行されていた）。
- 対応方針:
  - Vitest 4の後継機能`test.projects`（ワークスペース機能のインライン版）も検討したが、
    ファイル探索の単位自体がprojectsの`include`に変わり、パターンに含まれないテスト
    ファイルが静かに実行対象外になるリスクがあるため不採用。
  - 代わりに、バージョン間で仕様が安定している`// @vitest-environment <env>`
    docblock（ファイル先頭）を、旧`environmentMatchGlobs`が対象にしていた15ファイルへ
    個別付与する方式にした（`src/services/**`5件・`src/lib/apiError.test.ts`・
    `src/components/Map/*.test.ts`9件・`src/app/api/version/route.test.ts`）。
  - 付与作業中に`MapView.overlayFilters.test.ts`がMapView.tsxのensure*Layer関数経由で
    `regionApi.ts: accidentTileUrl()`（`window.location`参照）を実際に実行する経路を
    持つと判明。旧`environmentMatchGlobs`はこのファイルもnode環境に振り分ける設定だったが
    機能していなかったため表面化していなかった、実際には誤った設定だった。node docblockを
    付けず既定のjsdomのままにして解消した。
  - `vitest.config.mts`から`environmentMatchGlobs`ブロックを削除。
- 完了条件: `npx tsc --noEmit`がvitest.config.mts由来のエラー無しで通る。`npx vitest run`が
  frontend全件green。
- 実装メモ（2026-08-18完了）: `npx tsc --noEmit`がエラー0件（プレースホルダのコメントアウト
  無しで直接確認）。`npx vitest run`334件全green（`MapView.overlayFilters.test.ts`の
  環境訂正込み）。eslint全green。

### - [ ] T127. 日本全国データ取込の実現可能性検証〔容量・所要時間〕規模不明（調査完了・未実施、2026-08-18） — トリガー: 全国展開の意思決定

- 発端: ユーザー相談「日本全国のデータ取込をするならどれだけの容量、時間がかかるか。
  現実的かを検証してほしい」。実施はせず調査のみ。
- **ファイルサイズ**（Geofabrik実測、2026-08-18時点）: 関東`kanto-latest.osm.pbf`
  466MB・全国`japan-latest.osm.pbf`2,358MB（8地域区分合計。北海道179MB/東北292MB/
  関東466MB/中部484MB/関西333MB/中国223MB/四国84MB/九州297MB）。**倍率は約5.06倍**。
- **ストレージ試算（問題なし）**: 本番DB（関東本土7都県、T101バックフィル後）は
  投入後2,050MB。単純比例で全国約10GB、契約中のOracle Cloudブロックストレージ150GBに
  対し約7%で十分収まる。
- **所要時間試算（不確実性が大きい、要追加検証）**: 本番投入ログ（2026-08-18、T101の
  バックフィル実行）のchunk単位タイムスタンプを精査したところ、**way数94万件を超えた
  あたりから処理速度が非線形に悪化し、投入完了（133万way）まで悪化し続け頭打ちの
  兆候が無かった**（序盤約0.28ms/way→終盤約1.97ms/way、最悪chunk単体で約7.44ms/way）。
  これは2026-08-15の関東拡大時（12章）にも「94万way超からの緩やかな減速」として
  記録済み・未解決の既知事象（GiST索引は対策済みで無関係と判明済み、原因未特定。
  Oracle Always Free枠が2026-06-15に無告知で4 OCPU/24GB→2 OCPU/12GBへ半減された
  小規模構成であることが一因の可能性）。全国規模（約665万way、133万wayの5.06倍）へ
  外挿すると、**楽観（悪化がKanto終了時点の水準で頭打ちすると仮定）で約3.2時間、
  現実的（悪化トレンドがそのまま継続すると仮定）には半日〜それ以上**という、
  133万way超の規模を一度も実行したことが無いゆえの幅の大きい見積もりにしかならない。
- **ローカル開発機の制約**: 作業機のCドライブが237GB中221GB使用済み・空き16GBのみ。
  日本全国PBF（2.3GB）のダウンロードは可能だが、pyosmiumの位置インデックス
  （大規模ファイルではディスクバック方式）の一時領域を考えると余裕は乏しい。
- **推奨する進め方**: いきなり全国投入をテストせず、中間規模（例: 関東+中部+関西＝
  1,283MB、全国の54%・関東の2.75倍）で先に投入し、94万way超の減速が実際にどこまで
  悪化する／頭打ちするかを実測してから全国投入の可否を最終判断する。より精度の高い
  試算をするなら、日本全国PBF（2.3GB、要ダウンロード許可）でway/node/POI件数を
  ローカルで正確にカウントする（DB書き込み無し）ことも検討候補。
- 完了条件（実施する場合の目安）: 上記の段階的検証（中間規模での実投入）で94万way超の
  減速カーブが頭打ちすることを確認し、全国規模の所要時間・リスクを再試算してから着手判断。

### - [ ] T128. 地図上アイコンチップの増加対策〔グルーピング・表示絞り込み〕規模M（設計のみ、2026-08-18） — トリガー: 実装の意思決定

- 発端: ユーザー相談「地図上でアイコンが多くなってきている。グルーピングするか、
  表示非表示を切り替えられる改修を検討したい」。現状static9種＋dynamic1種＝10チップが
  常に並ぶ（T101で補給・休憩を追加してから顕在化）。実装はせず設計のみ。
- 現状整理: `MapLayerDescriptor.category`はサイドバー（`MapLayersPanel`）のグループ見出し
  として既に使われている（改善計画T86）が、地図上チップ列（`MapOverlayControls`）は
  この分類を使わずレイヤー1件=チップ1個のフラットな列のまま。既存category内訳:
  道路状態（道路情報・指定路線、2件）／交通・安全（車の圧迫感・安全度・停止要因・事故、
  4件）／自転車インフラ（1件）／地形（1件）／補給・施設（1件）。
- **生データ／合成データの軸**（ユーザー指摘）: 9レイヤーを実際に分類すると、
  「複数タグから計算した推定スコア」は**車の圧迫感・安全度の2件のみ**（他はOSM/警察庁の
  生タグ・生座標をそのまま分類・表示しているだけで合成ではない）。この2件はちょうど
  交通・安全カテゴリの中に、生データである停止要因・事故と混在している（同カテゴリの
  panelHintは既にこの違いを文章で説明済み: 指定路線の項「行政指定という事実」vs
  「車の圧迫感は複数要因を合成した推定指標」）。**生/合成の混在は交通・安全1カテゴリに
  閉じている**。
- 検討した3案:
  - **A. カテゴリ束ね（推奨）**: 既存categoryで5グループへ折りたたむ。1件しかない
    自転車インフラ/地形/補給・施設は見た目上ほぼ変化なし、実際に効くのは道路状態
    （2→1）と交通・安全（4→1）で、チップ総数9→5（ルート込み6）。交通・安全グループを
    開いたときだけ「推定指標（合成）」「観測データ」の2小見出しへさらに分ける
    （`dataNature: "raw"|"composite"`をカタログへ追加、他カテゴリは事実上"raw"のみ
    なので影響なし）。既存の「▶」展開アフォーダンス（`OverlayLayerChip`の
    legendDetails開閉と同じ発想）をグループチップにも再利用できる。
  - B. 常時表示チップ＋「その他」オーバーフローメニュー: よく使う数件のみ常時チップ化し
    残りを1つの「レイヤー」ボタンへ集約。削減効果は大きいが「よく使う」の線引きが
    恣意的、新規ユーザーが存在に気づきにくい機能が生まれるリスク。
  - C. サイドバーへ一本化・地図上チップを縮小: チップ列を「n/10表示中」の要約1個へ縮め、
    個別トグルはサイドバーだけで行う。地図を見ながらワンタップで切り替えられるという
    既存チップの価値（特にモバイル）を失うため、「多い」の緩和という今回のスコープに
    対して過剰な変更と判断。
  - → **A採用を推奨**。既存カタログ（category）をそのまま再利用でき新規タクソノミーを
    発明しない。生/合成の区別も交通・安全内の小分類として最小限の追加
    （`dataNature`フィールド1つ）で表現でき、他カテゴリへの影響が無い。
- 実装時の想定変更点（着手時のメモ、未実施）:
  - `mapLayers.ts`: `MapLayerDescriptor`へ`dataNature?: "raw" | "composite"`を追加
    （既定は"raw"扱い、明示するのはtrafficStress/safetyのみで足りる）。
  - `MapOverlayControls.tsx`: `category`単位でグルーピングしたチップ配列を組み立てる
    ロジックを追加。1件しかないカテゴリを単独チップのまま出すか、統一的に「1件だけの
    グループ」として同じコンポーネントで扱うかは実装時に決める（後者はコード一貫性、
    前者は見た目の変化を最小化）。
  - グループチップのタップ動作: 「▶展開してメンバー一覧を見せる」を基本とし、グループ
    まるごとON/OFFの一括トグルは誤操作リスクがあるため既定では設けない（必要なら
    展開後の一覧内に「すべて表示/非表示」行を別途検討）。
  - モバイル（BottomSheet）・デスクトップ（サイドバー）両レイアウトでの展開UI
    （ポップオーバー vs インライン展開）の挙動差はT33（チップ折り返し）・T34
    （BottomSheet化）の知見を踏まえて実装時に確認。
  - サイドバー（MapLayersPanel）側の見出しは変更不要（category単位のグループ化は
    T86で既に実装済み）。地図上チップとサイドバーで同じcategoryのまとまりを共有する
    ことで、「地図上のグループ＝サイドバーの見出し」という一貫した対応が保てる。
- 完了条件（実施する場合の目安）: 地図上チップ総数が5〜6個（現行9〜10個から半減程度）に
  収まり、交通・安全グループ展開時に生データ/合成データが視覚的に分かれて見えること。
  Playwright実機確認（チップ展開・個別トグル・モバイル幅での折り返し無し）。

## 研究モード実機検証の高速化・安定化（2026-08-18・N1/N2レシピ分離作業の最終検証より）

### - [x] T129. 研究モードのレシピ上書きをPlaywrightで実機確認する検証手順が非常に時間を要し、失敗時にハングする問題を解消する 規模S〜M（2026-08-18完了）

- 発端: 「道路適正」「自動車密度」を独立レシピ軸として切り出す作業
  （plan: valiant-sleeping-panda、docs/improvement-plan.md該当）の最終検証で、研究モードの
  UI操作を伴うheadless Playwright検証スクリプトをその場で書いて実行したところ、実行開始から
  7分以上経過しても完了せず、ユーザーから「テストに非常に時間がかかっている」と指摘を受けた。
  調査の結果、2つの要因が重なっていたと判明:
  1. **スクリプト側のバグ（ブラウザプロセスのリーク）**: `main()`内で例外が発生した場合に
     `browser.close()`を呼ばない実装だった（`try/finally`で囲んでいなかった）ため、
     `locator.click()`が30秒でタイムアウトしてPromiseがrejectされた後もheadless chromiumの
     プロセスが残り続け、Node.jsプロセスも終了しないまま「実行中」に見え続けた
     （実際にはこの時点で既に失敗していた）。
  2. **UI構造起因の誤ったロケータ**: `RoadSuitabilityRecipePanel`のhighway別基準値テーブルは
     `<details>`（`open`属性なしの既定閉状態）の中にある。Playwrightはブラウザの実描画に
     基づいてactionability（要素が視覧可能か）を判定するため、`<summary>`をクリックして
     `<details>`を展開しないまま中の要素（レベルピッカーの各ボタン）を`click()`しようとすると、
     要素は存在してもクリック不可と判定され続け、これも30秒タイムアウトの一因になった
     （testing-library/jsdom基準のフロントエンドユニットテストでは`<details>`が閉じていても
     子要素をクエリできてしまうため、この種の問題はvitest側では再現しない）。
  3. さらに、devサーバーの起動に使う`.claude/launch.json`のfrontend設定（port 3010）と、
     バックエンドの`CORS_ALLOWED_ORIGINS`（`http://localhost:3000`のみ許可）が食い違って
     おり、そのままではブラウザから直接叩くとCORSエラーで機能しない（Next.jsの`rewrites`
     プロキシ経由ではなく`NEXT_PUBLIC_API_URL`でバックエンドへ直接fetchする構成のため）。
     Browser pane（`preview_start`）経由ならプロキシ層が吸収していた可能性があるが、devサーバー
     自体が原因不明のタイミングで落ちる事象も重なり、原因切り分けに時間を要した。
- 対応方針: 上記3要因それぞれに対処した。
  1. `main()`の中身を`run(page)`へ分離し、`browser.close()`を`try/finally`で保証する構成へ
     書き換えた（エラー時も確実にブラウザ・Node.jsプロセスが終了する）。
  2. `<details>`は`open`属性で開閉状態が決まるため、対象要素の祖先`<details>`を
     `el.open = true`で強制的に開いてから操作する`expandAncestorDetails()`ヘルパーを追加した。
     ただし当初は対象を`getByRole()`（アクセシビリティツリー経由）で探そうとしたため、
     閉じた`<details>`の中の要素はそもそもa11yツリーから除外されて0件になり、
     「展開すべき対象が見つからない→展開されない→開かないので見つからない」という循環で
     デッドロックしていた。対象の発見には`button[aria-label="..."]`
     `input[type="checkbox"]`等のCSS属性セレクタ（DOMへ直接一致し、開閉状態に左右されない）を
     使い、開いた後の実際のクリック/検証だけ`getByRole()`を使う方式に直した。
     また`<details>`をテキスト内容で検索すると、そのテキストを内側に含む外側の`<details>`
     （例: 「研究」ブロック自体）まで誤ってヒットする問題もあったため、`<summary>`のテキストで
     `<details>`本体を特定してから親要素を取る方式（`detailsBySummaryText()`）に変更した。
  3. `.claude/launch.json`のfrontend設定ポート（3010）は変更せず、代わりに`backend/.env`の
     `CORS_ALLOWED_ORIGINS`へ`http://localhost:3010`を追加（カンマ区切りで複数オリジン対応済み、
     `backend/app/config.py: cors_allowed_origins_list`）。`.env`はgit管理外のローカル設定
     （`.gitignore`）のため、次回セッションが同じ問題を踏まないよう本メモに記録する。
  - 加えて、`.count()`はPlaywrightの自動待機（auto-retry）が効かない即時クエリのため、
     `page.reload()`直後のReactハイドレーション未完了と競合して0件を返す（実際に踏んだ罠）
     ことも判明。`expandAncestorDetails()`内で先に対象locatorへ
     `.first().waitFor({ state: "attached" })`を挟んでからcount()する形に修正した。
  - 副次的に、生成ボタンの実際のラベルが「ルートを生成」ではなく「ルート生成」だった
     （`RouteForm.tsx`）ことも発見・修正した。
- 完了条件: 研究モードのレシピ上書きを実機確認する際に、(a) 数分以内に確実に完了する
  （devサーバー起動待ちを除く）、(b) 失敗時にブラウザ/Node.jsプロセスが残留しない、
  の両方を満たすこと。
- 実装メモ（2026-08-18完了）: 修正後のPlaywright検証スクリプトで(a)道路適正のみ上書き・
  (b)自動車密度のみ上書き・(c)道路適正+自動車密度+交通ストレス(F)同時上書きの3パターンを
  実行し、約40秒で完了（devサーバー起動を除く）。「車の圧迫感」パネルの参照セクションが
  各上書きへ即座に反映されること、`/api/routes/generate`のconditionsエコーが
  `road_suitability_recipe`/`motor_vehicle_density_recipe`/`traffic_stress_recipe`すべてで
  リクエストと完全一致することを確認した。この検証スクリプト自体は使い捨てのため
  リポジトリには残していない（`frontend/test-results/`はgitignore対象）。次回同種の検証を
  書く際は、本メモの4つの罠（ブラウザプロセスのリーク・`<details>`未展開・
  `getByRole()`のa11yツリー依存・`.count()`の即時性）を踏まえて書き直すこと。
  `frontend/e2e/`配下への再利用可能ヘルパー化は今回は行わなかった（頻度が低く、
  本メモがあれば次回はゼロから躓かずに書けると判断）。

## 「道路適正」「自動車密度」を独立レシピ軸として切り出すN1/N2構造（2026-08-18・
   T122〜T124「レシピ付き軸の共通基盤整備」の続き）

### - [x] T130. 車の圧迫感（旧: 交通ストレス）・安全度が共有するhighway基準値＋cycleway補正
  （道路適正=N1）・制限速度＋車線数＋指定路線補正（自動車密度）を、それぞれ独立した
  上書き可能なレシピへ切り出す 規模L（2026-08-18完了）

- 発端: T122（レシピ判定プリミティブの共有）・T123（レシピ軸の糊のパラメータ化）で
  `domain/recipe.py`へ共有プリミティブを切り出した後も、`TrafficStressRecipe`/
  `SafetyRecipe`は依然としてhighway別基準値・cycleway補正・制限速度補正・車線数[多い方]
  補正・指定路線補正という値そのものが完全に一致する材料を、それぞれ独立したPydantic
  モデル・YAML・研究モードパネルとして重複保持していた（living_street基準値だけが
  交通ストレス側2／安全度側1と食い違っていた）。ユーザーとの設計検討（本セッション）で、
  この食い違いを解消したうえで「道路適正」(N1={A: highway基準値, B: cycleway})・
  「自動車密度」(delta={C: maxspeed, D: lanes_high, E: designation})を軸横断の独立レシピへ
  切り出し、「車との近さ」(N2 = 道路適正＋自動車密度)は専用の保存領域を持たず
  `car_closeness()`という合成関数としてのみ存在させる設計（選択肢A、3つ目の重複パネルを
  作らない）で合意した。
- 対応方針: `backend/app/domain/recipe.py`に`RoadSuitabilityRecipe`/
  `MotorVehicleDensityRecipe`（各独立YAML・DEFAULT_*・APIオーバーライドモデル付き）と
  `car_closeness()`を新設。`TrafficStressRecipe`/`SafetyRecipe`は軸固有フィールド
  （交通ストレス: lanes_low、安全度: lit/tunnel）のみへ縮小。`compute_edge_cost`・
  `EvaluationService`・両ルーティングエンジン・`routes.py`/`region.py`のAPI層・
  `export_openapi.py`のPython⇔JS相互検証フィクスチャまで一貫して配線。フロントは
  `recipeExpression.ts`に`carClosenessExpr()`を新設して`trafficStressExpression.ts`/
  `safetyExpression.ts`が共有し、新設の`RoadSuitabilityRecipePanel`/
  `MotorVehicleDensityRecipePanel`パネルと、縮小後の2パネル先頭に置く読み取り専用の
  参照セクション（`CarClosenessReferenceSection`）で研究モードUIを再構成。ユーザー向け
  呼称も「交通ストレス」から「車の圧迫感」へ統一。
- 完了条件: backend pytest・frontend vitest・`tsc --noEmit`・`next build`すべてgreen。
  研究モードで(a)道路適正のみ上書き・(b)自動車密度のみ上書き・(c)道路適正+自動車密度+
  交通ストレス(F)同時上書きをPlaywright実機確認し、参照セクションへの反映と
  `/api/routes/generate`のconditionsエコーの一致を確認する（T129参照）。
- 実装メモ（2026-08-18完了）: 実装自体は完了時点でbackend pytest 889件・frontend
  vitest 367件・tsc・`next build`すべてgreen、Playwright実機確認3パターンも成功して
  いたが、CLAUDE.mdが定める「着手前に該当タスクの有無を確認し、完了したらチェックを
  更新する」運用に反し、この規模Lの変更自体を追跡するimprovement-plan.mdのタスクが
  存在しないまま実装が進んでいた（コード中には「改善計画: 車との近さ材料の共有元化」と
  いう20箇所超の参照コメントがありながら、参照先のタスクが実在しないという状態。
  ultrareviewでの指摘を受けて本エントリを事後的に追加し、チェック済みで記録する）。
  加えて同レビューで発見された以下の実装不備も合わせて修正済み:
  - `lanes_low_threshold`（`TrafficStressRecipeOverride`）と`lanes_high_threshold`
    （`MotorVehicleDensityRecipeOverride`）が別モデルに分割されたことで失われていた
    `low<high`の順序検証を、`routes.py: validate_lanes_threshold_order`
    （`RouteGenerateRequest`/`TrafficStressBreakdownRequest`の`model_validator`から
    呼ぶ）として復元し、削除されていた回帰テストも復活。
  - `RoadSuitabilityRecipeOverride.base_by_highway`の部分上書きが両軸を同時に無効化
    する問題を、全12highwayキーの完備を要求する`model_validator`で解消。
  - 較正スクリプト（`measure_axis_stats.py`/`analyze_jartic_calibration.py`）が
    `road_suitability_recipe.yaml`/`motor_vehicle_density_recipe.yaml`を読まず
    ハードコード既定値へ静かにフォールバックしていた問題を修正。
  - `living_street`基準値の交通ストレス側2→1の変更にテストが無かった問題を
    `test_recipe.py`/`test_traffic.py`/`test_safety.py`へ追加してピン留め。
  - `car_closeness()`/`carClosenessExpr()`が`compute_edge_cost`（バックエンド、
    ルート生成の全Edge）・`setStaticOverlayFilters`（フロント、地図スタイル再構築）の
    双方で交通ストレス・安全度から2回ずつ計算されていた無駄を、事前計算結果を両方へ渡す
    形へ改めて解消（`test_evaluation.py`に呼び出し回数を数える回帰テストを追加）。
  - `ScalarInput`/`ThresholdAdjustmentRow`/補正値ステッパーの色定数が4つのレシピ
    パネルへコピペされていた重複を`recipeControls.tsx`/`recipeControls.module.css`へ
    集約。

## 研究タブのレイアウト改善（2026-08-18・T130の続き、ユーザー要望「地図の見え方の
   ようなデザインに合わせて、折りたたみを工夫したり表示非表示をスマートに。土台部分が
   冗長」）

### - [x] T131. 研究タブ5パネル（評価重み・道路適正・自動車密度・車の圧迫感・安全度）の
  開閉とON/OFFを分離してMapLayersPanelと同じ構成へ揃え、`CarClosenessReferenceSection`
  （「土台」参照ブロック）の冗長な文章を圧縮 規模M（2026-08-18完了）

- 発端: T115で研究タブ内の各グループ（highway別基準値・cycleway補正等）は
  `MapLayersPanel.tsx`と同じ折りたたみ（details、デフォルト全閉）へ揃えたが、5パネル
  自体の最上位は「上書きする」チェックボックス1つが開閉と有効/無効を兼ねたままだった
  （値を確認するだけでも上書きを有効化する＝地図やルート生成へ即座に影響するしかない）。
  また車の圧迫感・安全度パネル先頭の`CarClosenessReferenceSection`（T130で新設）は
  前置き文2つ＋「／」区切りの長文箇条書き4行という構成で、同じ説明が2パネルに重複する
  には冗長だった。
- 対応: `recipeControls.tsx`に`RecipePanelSection`（`MapLayersPanel.module.css`の
  `.layerSection`/`.layerHeader`/`.layerTitle`/`.chevron`/`.layerBody`をcomposesで
  再利用した`<details>`ラッパー、ON/OFFは`LayerChip`共通部品による独立チップ）と
  `withAutoEnable`（MapLayersPanelの「絞り込みを操作すると自動でON」と同じパターン）を
  新設し、5パネルすべてを移行。上書き無効中も中身は既定値で表示・編集でき、値を変更す
  ると上書きが自動でONになる。`CarClosenessReferenceSection`は前置き文2つを見出しの
  `[編集は各パネルで]`へ集約し、「／」区切りの長文箇条書きを7つの短いタグ（`.referenceTags`）
  へ置き換え。
- 完了条件: frontend vitest・`tsc --noEmit`・eslintすべてgreen（39件更新+新規、既存の
  「上書き無効時は入力欄を表示しない」系テストは新設計に合わせ「上書き無効でも展開すれば
  既定値で表示・編集でき、変更すると自動でONになる」へ書き換え）。ローカルNext.js dev
  サーバー（別セッションが起動済みのlocalhost:3000を共用）でアクセシビリティツリーを
  確認し、5パネルとも新チップ・折りたたみ・参照タグが意図通り描画されることを確認。
  作業中、別セッションが同一ワーキングツリー上で`WeightPanel.tsx`/`WeightPanel.module.css`
  /`RoadSuitabilityRecipePanel.tsx`/`MotorVehicleDensityRecipePanel.tsx`/
  `recipeControls.tsx`/`recipeControls.module.css`の6ファイルを編集前の状態へ巻き戻す
  competing writeを検知（git statusで一時的に「未変更」に戻っているのを発見）、内容を
  再構築して復旧した。

## 統合レビュー対応（2026-08-18・review:all第3回の指摘）

overall/complexity/consistency/uiの4レビューを並列実施し相互統合した結果
（`.claude/commands/review/history/2026-08-18_all.md`）のうち実施すべきものを起票する。
対象コミット`32e84ed`時点の指摘であり、直後のT131（研究タブレイアウト改善）で
一部（参照セクションの上書き非依存の可視化）は既に解消済み。各タスクの発端欄に注記する。

### - [x] T132. docs/architecture.md §7 を「道路適正」「自動車密度」独立レシピ軸(T130)・
  研究タブレイアウト改善(T131)・補給POIレイヤー(T101)へ追従させる 規模M（2026-08-19完了）

- 発端: 統合レビューF-1（overall・consistency共通指摘、統合-1）。architecture.md §7が
  `base_by_highway`の独立性を誤って記述（実際は`recipe.py`で意図的に共有）、撤去済み
  `shoulder_adjustment`の記述が残存、`TrafficStressRecipePanel`の守備範囲説明が現状
  （`lanes_low`のみ）と不一致、APIリクエスト例が現行のOverrideモデルではバリデーション
  エラーになる、「フロント9レイヤー」見出しがT101のsupplyPoi追加後も10レイヤーへ未更新。
  過去に2回発生した「architecture.md未追従」パターンの3回目の再発（P1）。
- 対応方針: §7の交通ストレス・安全度節へ`RoadSuitabilityRecipe`/`MotorVehicleDensityRecipe`/
  `car_closeness()`の共有構造を追記し、APIリクエスト/レスポンス例を現行モデルに合わせ
  差し替え、ディレクトリツリーへ新設ファイルを反映。呼称変更（交通ストレス→車の圧迫感）も
  反映。フロントレイヤー数見出しを10へ更新。T131のRecipePanelSection/withAutoEnable構成
  への言及も追加。
- 完了条件: architecture.md中に`car_closeness`/`RoadSuitabilityRecipe`/
  `MotorVehicleDensityRecipe`等の新設シンボルへの言及があること。記載中のAPI例が
  現行スキーマでバリデーションを通ること。
- 実装メモ（2026-08-19完了）: 着手時点で`base_by_highway`共有・`shoulder_adjustment`撤去・
  `CarStressRecipePanel`（旧`TrafficStressRecipePanel`）の守備範囲は、T130〜T150の一連の
  タスク（本タスクの発端より後に実施）が自身の完了作業の一部として既にarchitecture.md側も
  更新済みと判明。本タスクは残っていた実際のギャップに絞って対応: (1)
  `POST /api/routes/generate`のRequest例が`route_preference`3/7フィールドしか埋めておらず
  現行`RoutePreferenceWeights`（全7フィールド必須）で422になる不整合を修正し、欠落していた
  `road_suitability_recipe`/`motor_vehicle_density_recipe`（T130で新設のOverrideフィールド）
  も例に追加。実際に`RouteGenerateRequest.model_validate()`へ通して検証が通ることを確認
  （backendスクリプトで実行確認済み）。`conditions`エコー・`segments`/`RouteCandidate`
  レスポンス例も同様に更新（`car_stress`/`bicycle_infra`/`safety`生値、
  `stop_difficulty`/`car_stress_difficulty`/`accident_difficulty`/`night_difficulty`、
  `safety_score`の欠落を解消）。(2) 「フロント9レイヤー」見出し・列挙からsupplyPoi
  （T101）が抜けていた実際の残存ギャップを10レイヤーへ修正。(3) T132着手後に完了した
  T145b（レジストリ駆動の二次軸ランプレイヤー、`accident_per_km`/`stop_per_km`/
  `intersection_per_km`のタイル追加・`axisLayers.ts`）がarchitecture.md未反映のまま
  残っていたため新設の「レジストリ駆動の二次軸ランプレイヤー」節で追記、road-surface-tiles
  世代表記もv10（stale）→v12（現行）へ修正（v11=T122の`shoulder`撤去も追記漏れだった）。
  (4) T131のRecipePanelSection/withAutoEnable構成への言及を追加。docs変更のみ、コード変更
  なし。
- 注記: T132起票時点（2026-08-18）から本着手（2026-08-19）までの間に「評価システムの層構造
  再設計」（T137〜T151）が大量に完了し軸構成自体が7〜9軸から再編されているが、それらは
  各タスクの完了条件でarchitecture.md追従が既に担保されていたため、本タスクは前段の
  統合レビュー指摘4点＋着手時点で残っていた実ギャップの解消に限定した。

### - [x] T133. page.tsxのレシピ上書き状態管理を共通化し、5パネルの視覚的な階層関係を示す
  規模M（2026-08-19完了）

- 発端: 統合レビュー統合-2（overall F-2＋uiレビューの統合）。page.tsxのレシピ上書き状態
  （有効フラグ・値・debounce）が交通ストレス・安全度の2軸から道路適正・自動車密度を
  加えた4軸へ倍増したが共通フックがなくコピペのまま複製されている。UI側は「道路適正・
  自動車密度が車の圧迫感・安全度の材料である」という関係が5パネルのフラットな並びからは
  伝わりにくい。**なお参照セクション（`CarClosenessReferenceSection`）が上書きOFF時でも
  展開すれば見えるようになった点はT131で解消済み（本タスクの対象外）**。
- 対応方針: page.tsxの`useState`/`useDebouncedValue`を`useRecipeOverride<T>()`的な
  共通フックへ集約。研究タブの「レシピ」カテゴリ内で道路適正・自動車密度を「共通材料」
  として視覚的に1段インデントまたはグルーピング枠で囲い、車の圧迫感・安全度との階層関係
  を示す。
- 完了条件: page.tsxの`useState`/`useStoredState`件数が純減すること。frontend vitest・
  tsc・eslintすべてgreen。Playwright実機確認で階層関係が視覚的に区別できることを確認。
- 実装メモ（2026-08-19完了）: `frontend/src/hooks/useRecipeOverride.ts`を新設
  （`overrideEnabled`/`setOverrideEnabled`/`recipe`/`setRecipe`/`debouncedRecipe`を返す
  ジェネリックフック、単体テスト3件付き）。page.tsxの車の圧迫感・安全度・道路適正・
  自動車密度4レシピをこのフックへ集約し分割代入で既存の変数名（`carStressRecipe`等）を
  維持したまま呼び出し側の広範な参照を無改修で済ませた。page.tsx直下の`useState`呼び出し
  8件（4レシピ×2）＋`useDebouncedValue`呼び出し4件が、フック呼び出し4件へ純減（フック内部の
  `useState`/`useDebouncedValue`は集約先のためpage.tsx側のカウントには入らない）。UI側は
  「レシピ」カテゴリを`.recipeSharedMaterialGroup`（枠線＋「共有材料[車の圧迫感・安全度が
  参照]」見出し、道路適正・自動車密度の2パネルを内包）と`.recipeDependentAxes`
  （`margin-left`でインデント、車の圧迫感・安全度の2パネルを内包）へ再構成
  （page.module.css新設クラス3個）。Playwright実機確認（`next dev`起動、研究モードON）で
  共有材料グループの1px枠線・インデント差12pxをDOM実測で確認、スクリーンショットでも
  視覚的な階層を確認。backend側は無関係のため未実施。frontend vitest 388件（新規3件含む）・
  eslint・tsc（`next typegen`後）・`next build`すべてgreen。

### - [x] T134. 両エンジンの区間表示ビルダーでcar_closeness()の二重計算を解消する 規模S
  （2026-08-19完了）

- 発端: 統合レビュー統合-3（overall F-3）。`compute_edge_cost`（探索の全Edge）では
  T130のultrareview是正で`car_closeness_result`を1回計算し共有渡しする形へ解消済みだが、
  最終候補ルートの区間表示を組み立てる`openrouteservice_engine.py`/`road_graph_engine.py`
  の該当箇所では`car_closeness_result`未指定のまま交通ストレス・安全度それぞれで
  `car_closeness()`が計算され続けている。T120・T121-aに続く同型パターン（片方だけ直して
  別の箇所を忘れる）の3件目。
- 対応方針: `openrouteservice_engine.py:339-373`・`road_graph_engine.py:276-310`の
  該当2箇所で、`compute_edge_cost`と同じパターンで`car_closeness()`を1回だけ計算し
  両関数へ渡す。
- 完了条件: backend pytest green。`test_evaluation.py`の呼び出し回数カウントテストと
  対称な回帰テストを両エンジンにも追加。
- 実装メモ（2026-08-19完了）: 両エンジンとも`car_stress_level`/`safety_level`呼び出し直前で
  `car_closeness()`を1回だけ計算（`road_suitability_recipe`/`motor_vehicle_density_recipe`は
  `None`のときdomain/evaluation.pyと同じ`or DEFAULT_*`フォールバックが必要と実装中に判明
  — 両エンジンとも`self._road_suitability_recipe`等はOptionalでNoneが既定のため、これを
  怠ると道路適正未上書き時に`car_closeness()`内で`NoneType.base_by_highway`のAttributeError
  が発生する。実装時に既存テストで検出・修正済み）、結果`car_closeness_result`を両関数へ渡す
  形へ修正。回帰テストを両エンジンへ追加: `test_road_graph_engine.py:
  test_build_segment_details_calls_car_closeness_once_per_edge`（`road_graph_engine`モジュール
  の`car_closeness`をカウンタでラップし、全edge分のway_tagsを与えた全候補合計の呼び出し回数が
  生成された全segment数と一致することを検証）、`test_openrouteservice_engine.py:
  test_builds_segment_details_calls_car_closeness_once_per_point`（同様に全候補の
  総segment数と一致することを検証）。backend pytest 863件（新規2件含む、+99 skipped＝
  PostGISマーカー、DB未接続のためこのセッションでは未実行）all green。

### - [x] T135. レビュー基準の反映漏れ2件を解消する（page.tsx閾値・変更コスト表G''行）
  規模S（2026-08-19完了）

- 発端: 統合レビュー統合-4・複雑度レビューF-3'/F-2'。page.tsxの閾値付きKEEP提案
  （「状態40件 or 1,300行」）がdocs/complexity-review-2026-08-16.mdへ2回連続で未反映。
  変更コスト表にもG''行（軸の共通材料の外出し・再構成、T130実測70ファイル・
  +3,938/-2,084行）が未追記。あわせて、規模M以上の変更は着手前の最初のコミットで
  タスクエントリを先に作る運用（T130で一度破られ事後是正された実績あり）の明文化も
  検討する。
- 対応方針: `/review:improve`経由でdocs/complexity-review-2026-08-16.mdのKeep Listと
  変更コスト表を更新する（コード変更なし）。運用ルールの明文化はCLAUDE.mdへの追記要否を
  含めユーザー判断とする。
- 完了条件: docs/complexity-review-2026-08-16.mdへの反映を次回complexityレビューで確認。
- 実装メモ（2026-08-19完了）: T150が同一作業ツリーでbackend/frontend広範囲を書き換え中
  だったため、コード変更ゼロのdocs反映のみを対象に実施（T150との衝突回避）。Keep List
  （page.tsx / MapView.tsxの節）へpage.tsx独自閾値〔useState+useStoredState合計40件
  or 1,300行、2026-08-18時点実測38件・1,148行で未到達〕をMapView.tsxの既存閾値と並記、
  設計原則9へも同内容を追記。変更コストシミュレーション表へG'行（レシピ付き評価軸追加、
  T119実測64ファイル・+3,677/-394行、次回単軸追加時に再検証する参考値と明記）・G''行
  （軸の共通材料の外出し・再構成、T130実測70ファイル・+3,938/-2,084行）を新設し
  区別。運用ルール明文化（規模M以上の着手前タスクエントリ作成）はCLAUDE.md改訂要否含め
  ユーザー判断のため今回は見送り、別途確認が必要。

### - [ ] T136. 軽微な残骸・テスト非対称の解消（errorLabel・回帰テスト・living_street再検証）
  規模S — errorLabel修正・回帰テストは2026-08-19完了、living_street再検証のみ実DB接続可能な
  セッションへ持ち越し

- 発端: 統合レビュー統合-6（ui・consistency・overallのP3統合）。`regionApi.ts`の
  `errorLabel`に旧呼称「交通ストレス」の死んだ文字列が残存（`catch`で握りつぶされ実害は
  ないが将来リスク）。`carClosenessExpr()`のフロント側に呼び出し回数の回帰テストがない
  （backendのみ対称）。living_street基準値の統合が実データ根拠でなく構造統合の都合による。
  なお「車との近さ」/「自動車との近さ」の表記ゆれはT131のCarClosenessReferenceSection
  文言圧縮で「車との近さ」表記自体が無くなり解消済み（本タスクの対象外）。
- 対応方針: `regionApi.ts`の`errorLabel`を「車の圧迫感」へ1行修正。
  `MapView.overlayFilters.test.ts`等へ`vi.spyOn`ベースの`carClosenessExpr`呼び出し
  回数テストを追加。次回`measure_axis_stats.py`実行時にliving_street区間の分布・件数を
  確認する。
- 完了条件: frontend vitest green（新規テスト追加分含む）。living_street確認は
  `measure_axis_stats.py`出力への言及で足りる。
- 実装メモ（2026-08-19一部完了）: 着手時点で`errorLabel`は既にT150の機械的リネームにより
  「交通ストレス」→「車ストレス」へ変わっていたが、UI表示上の正準ラベル（`evaluationAxes.ts`・
  `CarStressRecipePanel`が使う「車の圧迫感」、T150実装メモのPlaywright確認記録参照）とは
  依然不一致だったため、あらためて「車の圧迫感」へ修正。`MapView.overlayFilters.test.ts`へ
  `vi.spyOn(recipeExpression, "carClosenessExpr")`ベースの呼び出し回数テストを追加し、
  `setStaticOverlayFilters`1回の呼び出しにつき`carClosenessExpr`が1回だけ計算され
  車の圧迫感・安全度の両方の凡例式へ使い回されることを検証（本番実装は既に
  `MapView.tsx: setStaticOverlayFilters`が1回だけ計算・両関数へ渡す形で対応済みだったが、
  それを検証する回帰テストが無い状態だった）。frontend vitest 388件（新規1件含む）green。
  living_street再検証は、このセッションが実DB（PostGIS・関東圏実データ）に接続できない
  環境だったため未実施のまま残存。対応方針が元々「次回`measure_axis_stats.py`実行時に
  確認する」という将来のバッチ実行時点の確認として位置づけていた項目のため、実データを
  伴うセッションでの持ち越しとする。

## 評価システムの層構造再設計（2026-08-18・区間評価の一次/二次/三次分離）

ユーザーから「一次データ（OSM等の生属性）・二次データ（軸スコア）・三次データ（重み付き合成コスト）の
役割が混ざっている」という課題認識のもと、層構造の再設計プロンプトが提示された。現状把握
（本セッション、Explore調査＋主要ファイル直接確認）の結果、提案の一部（〇次ハード制約の分離、
軸内係数と三次重みの分離、レシピの上書き可能な外部化）は既にT16〜T130の過程で実現済みだが、
以下は未実装または方向性の異なる決定事項として残っていた:

- **軸構成**: 提案は6軸（car_stress/accident/surface_q/stop_density/gradient/night）。現状は
  9軸（勾配・風・路面・停止密度・車の圧迫感・自転車インフラ・交差点密度・事故密度・安全度）で
  提案より粒度が細かく、かつ「車の圧迫感」と「安全度」が道路適正(N1)・自動車密度(N2)を意図的に
  共有する設計（T130、本日完了）になっている
- **レジストリ制**: `docs/complexity-review-2026-08-16.md`が「レシピが2つ目しかない段階では
  汎用レジストリ化は過剰」として明示的に見送っていた

ユーザーに確認のうえ、以下の方針で進める（詳細は本セクション追加時のセッション記録参照）:

1. **安全度軸は提案どおり廃止し、事故実績(accident)・夜間(night)へ分割する**（T130の
   「共有基盤化」路線からの転換。安全度が持つ街灯・トンネル補正はnight軸へ、highway別基準値・
   cycleway・maxspeed・lanes・指定路線補正はcar_stress軸へ統合し、事故密度は既存のaccident軸
   （変更なし）へ一本化）
2. **一次属性・二次軸のレジストリ制を導入する**（2026-08-16時点の見送り判断を、軸数が
   6〜9・将来のオープンデータ追加を見込む今回のスコープでは更新する）
3. **DB移行・両ルーティングエンジン書き換え・フロント全面改修を含む大規模変更のため、
   本セクションでタスク分割してから段階的に着手する**（1タスク=1コミット、着手前後で
   全テストgreenの原則をそのまま適用）

**未決定のまま残っている論点**（各タスクの着手時に確認・記録する）:

- ~~交差点密度（intersection_density）・自転車インフラ（bicycle_infra）は提案の6軸表に
  明示的な帰属先が無い~~ → **2026-08-18、設計プロンプト改訂で解決**。自転車インフラは
  car_stressの入力へ統合（T138、従来方針のまま）。交差点密度は単独軸を持たず、
  信号・横断歩道・一時停止・踏切と同じstop_density軸へ「タグなし交差点」を独立した
  低い重みのカテゴリ（例: `unsignaled_intersection: 0.3`、signal=1.0比）として吸収する
  （新規T149）。intersection_densityがstop_densityへ寄せられる理由は「立ち止まる／
  減速する頻度」という同じ性質の指標だから、car_stress（走行中の車との近接ストレス）
  ではなく質的に異なるという設計判断（改訂後の設計プロンプト「現行9軸からの帰属先」節）。
  bicycle_infra統合後は`accident`と`car_stress`の相関を確認し、二重計上懸念を潰す
  （T138の完了条件へ追加）。この決定を受け、T137で先行登録していた`intersection_density`
  単独軸はレジストリから削除しstop_density側のinputsへ統合する後方修正を実施済み（下記
  T137実装メモ追記参照）
- 提案の〇次フィルタは「自転車通行不可・高速道路」のみだが、現状の`DISALLOWED_HIGHWAY_TYPES`は
  `trunk`/`trunk_link`も含む（高速道路より広い）。また現状の`motor_vehicle=no`（自転車可の
  車両通行禁止）は〇次のハード除外ではなく二次軸内の最善値1固定という別ロジックであり、
  提案の「通行不可はハード制約へ統合」との対応関係を明確にする必要がある（T140で扱う。
  改訂後の設計プロンプトでもこの点への言及は無いため、引き続き未解決のまま残す）

### - [x] T137. 一次属性レジストリ・二次軸レジストリの定義形式と排他バリデータを実装する 規模L（2026-08-18完了）

- 背景: 設計プロンプトのタスク2。新しい一次属性・二次軸を「コアロジック無改修でレジストリに
  1件追加するだけ」で取り込めるようにする。既存の一次属性（highway/lanes/maxspeed/cycleway系/
  surface/N10・N12/lit/tunnel/標高/停止POI/事故地点/補給POI）と、既存の9軸（うち安全度は
  T140で廃止予定のため、レジストリ登録は6〜8軸を前提に設計する）をこの形式へ移行する。
- 対応方針: `backend/app/domain/registry.py`（新規）に`PrimaryAttributeSpec`
  （attr_id/source/geometry/dtype/update_cadence/ingest_fn相当の参照）・`AxisSpec`
  （axis_id/inputs/transform_fn参照/output_range/shared属性リスト）をPydanticモデルで定義。
  登録関数`register_axis()`が、登録しようとする軸の`inputs`が`shared=True`でない既存の
  他軸の`inputs`と重複する場合に`ValueError`（またはロガーへの警告、要決定）を送出する
  バリデータを実装。`length`/`geometry`のような全軸共通の入力は`shared=True`で除外対象とする。
  既存9軸をこの形式で宣言し直し、バリデータが現行構成（車の圧迫感と安全度がN1/N2を共有）を
  どう扱うか（意図的な共有として許可するか、T140の廃止を前提に一旦無視するか）を決める。
- 完了条件: 全一次属性・既存軸がレジストリに登録された状態でbackend pytest green。
  意図的に入力が重複する軸を試験的に登録するテストで、バリデータがエラー/警告を出すことを
  確認する回帰テストを追加。
- 実装メモ（2026-08-18完了）: `backend/app/domain/registry.py`（`PrimaryAttributeSpec`/
  `AxisSpec`/`register_primary_attribute`/`register_axis`/`AxisInputConflictError`）と
  `backend/app/domain/registry_defaults.py`（`register_defaults()`、既存16一次属性・5二次軸の
  宣言）を新設。レジストリはまだどこからも呼び出されておらず（コスト関数・レイヤーパネルへの
  配線はT142・T145で実施)、宣言のみの非破壊的な追加。「車ストレス」「安全度」「自転車インフラ」
  の3軸は現行実装がhighway/cycleway/maxspeed/lanes/指定路線を意図的に共有しているため未登録の
  まま残し、T138/T139で軸自体を再編したのち登録する（`test_registry_defaults.py`が
  この3軸が未登録であることを回帰確認）。`test_registry.py`（レジストリ機構の単体テスト、
  衝突検出・shared属性の除外を検証）・`test_registry_defaults.py`（既存属性・軸の登録内容の
  スナップショット的検証）を追加。backend pytest 904件green（新規14件含む）。
- 追記（2026-08-18、設計プロンプト改訂を受けた後方修正）: 当初`intersection_density`を
  独立軸として登録していたが、改訂後の設計プロンプトで「交差点密度はstop_density軸へ吸収」と
  確定したため、`registry_defaults.py`を修正（`intersection_density`のAxisSpec登録を削除し、
  `stop_density`のinputsへ`intersection`を追加）。テストも追従（登録軸は5→4種、
  `intersection_density`という名前の軸は存在しないことを確認するテストへ更新）。
  実際の吸収ロジック（`domain/traffic.py`のstop_density計算へタグなし交差点を低重みカテゴリ
  として組み込む実装）自体は新規T149で行う（T137時点ではレジストリの宣言のみ修正）。

### - [x] T138. 自転車インフラの独立難易度軸を廃止し交通ストレス（car_stress予定）側へ
  統合する 規模L（2026-08-18・機能面のみ完了、呼称統一は分離してT150へ）

- 背景: 設計プロンプトの2次軸表。現状は「車の圧迫感」（highway基準値＋cycleway＋lanes_low＋
  N1/N2）と「自転車インフラ」（分離自転車道等の分類、独立軸）が別軸だが、提案は自転車インフラを
  car_stressの入力の一部として統合する。T130で切り出した`RoadSuitabilityRecipe`/
  `MotorVehicleDensityRecipe`/`car_closeness()`はほぼそのまま土台として再利用できる。
- スコープ分割（着手時の判断）: 当初は「`domain/car_stress.py`新設＋呼称のcar_stressへの
  全面リネーム」まで1タスクで想定していたが、影響範囲がbackend34ファイル・frontend42
  ファイル（API契約・MVT SQL・フロントexpression鏡・研究モードパネル・レイヤーカタログ含む）
  に及ぶと判明。**機能面の統合（自転車インフラの独立軸廃止・二重計上の解消）と、
  呼称のtraffic_stress→car_stressへの機械的な統一は独立した変更**（前者は挙動が変わり
  検証が要るが影響ファイルは限定的、後者は挙動不変だが影響ファイルが広い）と判断し、
  本タスクでは前者のみ実施。後者は新規T150として分離起票した。
- 対応方針（実施内容）: `domain/difficulty.py`の`bicycle_infra_difficulty()`・
  `_BICYCLE_INFRA_DIFFICULTY_SCORES`・`AxisDifficulties.infra`フィールド・
  `evaluate_axis_difficulties()`の`bicycle_infra`/`infra_weight`引数を削除（9軸→8軸）。
  `domain/evaluation.py: RoutePreference.infra_weight`を削除し、その分（0.10）を
  `traffic_weight`（0.10→0.20）へ合算（既存項目全体への相対的な影響度を維持する形の
  移行、`route_preference.yaml`に根拠を記載）。`compute_edge_cost`・両エンジンの
  `_build_segment_details`から`classify_bicycle_infrastructure`呼び出し→
  `evaluate_axis_difficulties`への受け渡しを削除。`RouteSegmentDetail.infra_difficulty`
  フィールドを削除（`bicycle_infra`生値・`RouteCandidate.bicycle_infra_score`集約統計は
  一次属性の表示用データとして維持、スコアリングからのみ切り離す）。API層
  `RoutePreferenceWeights.infra_weight`を削除。OpenAPI再生成→フロント型再生成
  （`api.d.ts`）→`WeightPanel.tsx`/`evaluationAxes.ts`のinfra_weight除去、影響テスト
  fixtureを追従。docs/architecture.md §7を9軸→8軸表記へ更新。
- 完了条件: backend pytest 900件green・frontend vitest 372件green・tsc/eslint/
  `next build`すべてgreen（すべて確認済み）。**実データでの分布急変確認
  （`measure_axis_stats.py`相当）・統合後`car_stress`と`accident`の相関確認は、
  対応する測定スクリプトがT147（相関行列スクリプト、現時点で未実装）でしか
  一般化されていないため今回は実施せず、T147着手時にまとめて確認する**（未実施のまま
  据え置き、次のタスクで確認すること）。

### - [x] T139. 安全度軸を廃止し、事故実績(accident)・夜間(night)軸へ分割する 規模L（2026-08-18完了）

- 背景: 設計プロンプトの2次軸表（accident/night）。`domain/safety.py`の街灯・トンネル補正を
  night軸として独立させ、highway/cycleway/maxspeed/lanes/指定路線由来の部分はT138のcar_stress
  へ吸収済みのため重複実装しない。事故密度（`domain/difficulty.py: accident_difficulty`）は
  既に独立軸のため変更不要（入力を事故地点データのみに保つ設計は維持）。
- 対応方針: `domain/night.py`（新規）に`night_score`（lit無し・トンネルで加点、デフォルト重み0
  運用は設計プロンプトの指示どおり）を実装。`route_preference.yaml`の`safety_weight`を
  `night_weight`（既定0.0）へ置き換え。`domain/safety.py`・`SafetyRecipe`・関連API
  （`*RecipeOverride`）・フロント`safetyExpression.ts`・`safety`レイヤーは本タスクでは
  併存させ、削除はT148（移行完了後）で行う。
- 完了条件: backend pytest green。night_weight=0の既定でrun_id比較時の`total_score`・経路が
  変化しないことを確認（既定運用への影響が無いことの回帰確認）。
- 実装メモ（2026-08-18完了）: `backend/app/domain/night.py`（`night_difficulty(tags)`、
  street lit無し+50・tunnel+50・最大100の単純加点式。litタグ不在を「街灯なし」扱いする
  unknown-safe原則からの意図的な逸脱をdocstringに明記）を新設。`domain/difficulty.py`の
  `safety_difficulty`関数・`AxisDifficulties.safety`・`evaluate_axis_difficulties`の
  `safety_level_value`/`safety_weight`引数を`night_tags`/`night_weight`へ置換（8軸のまま、
  safetyがnightへ入れ替わっただけ）。`domain/evaluation.py: RoutePreference.safety_weight`を
  `night_weight`（既定0.0）へ、`compute_edge_cost`から`safety_level`呼び出し・
  `safety_recipe`引数を削除（cost計算からsafety_recipeが完全に不要になったため
  `EvaluationService`・`dependencies.py`のEvaluationService構築呼び出しからも
  `safety_recipe`を削除。ただしRoadGraphEngine/OpenRouteServiceEngine自体は表示用の
  `safety`生値・`safety_score`集約統計の算出に`self._safety_recipe`を引き続き使うため
  変更なし）。両エンジンの`_build_segment_details`は`evaluate_axis_difficulties`へ
  `way_tags`をそのまま渡す形に変更、`RouteSegmentDetail.safety_difficulty`を
  `night_difficulty`へ置換（`safety`生値・`safety_score`集約は維持）。API
  `RoutePreferenceWeights.safety_weight`→`night_weight`。OpenAPI再生成→フロント型再生成→
  `WeightPanel.tsx`/`evaluationAxes.ts`・影響テスト6件のfixture更新。docs/architecture.md
  §7を追従（`night.py`をディレクトリツリーへ追加、8軸表のsafety行→night行、
  RouteSegmentDetail型定義のsafety_difficulty→night_difficulty）。backend pytest 902件・
  frontend vitest 372件・tsc・eslint・`next build`全green。night_weight=0既定での
  total_score・経路への影響確認は、safety_weightが元々scoring.yaml（total_score）には
  含まれておらず区間difficulty/探索costにのみ効く設計だったため、night_weight=0なら
  `composite_difficulty`の重み付き平均から night 項が最初から除外される（Noneではなく
  重み0で寄与ゼロ）ことをコードレビューで確認済み（既存の`test_evaluate_axis_difficulties_*`
  でも重み0時の非寄与は数式的に自明）。

### - [x] T140. 〇次ハードフィルタの範囲を設計プロンプトに合わせて明確化する 規模M（2026-08-18完了）

- 背景: 上記「未決定のまま残っている論点」の2点目。`DISALLOWED_HIGHWAY_TYPES`の`trunk`/
  `trunk_link`が提案の「高速道路（motorway/motorway_link）のみ」より広く、また`motor_vehicle=no`
  の扱い（ハード除外か、二次軸内の特例か）が不明確なまま。
- 対応方針: `trunk`/`trunk_link`を除外に含める現行判断の妥当性（自転車走行の法的・実質的
  可否）を再確認し、含める場合は設計プロンプトの`hard_filters`概念（レシピ側で選択可能な
  フィルタのリスト）へ`"trunk"`のような独立エントリとして表現できるようにする。
  `motor_vehicle=no`はハード除外（グラフから完全除外）ではなく現状の「二次軸内で最善値固定」を
  維持する方針が妥当（自転車は法的に通行可能なため）と考えられるが、設計プロンプトの
  「ハード制約はスコア外」原則との整合をdocs/architecture.mdへ明記する。
- 完了条件: `hard_filters`のレシピ表現とtrunk除外の扱いがdocs/architecture.md・
  改善計画の両方に記録され、既存のis_edge_allowedの単体テストが現行動作を回帰確認する。
- 実装メモ（2026-08-18完了）: `trunk`/`trunk_link`除外は挙動を変えず維持する判断とした
  （日本のtrunk＝国道等の幹線道路は法的には自転車通行可能な場合が多いが、
  ロードバイクの周回ルート生成という用途にとって実務上走りにくい・危険という既存判断を
  尊重。設計プロンプト自体にtrunkへの言及が無く、変更を求める明確な指示も無いため）。
  `backend/app/domain/evaluation.py`の`DISALLOWED_HIGHWAY_TYPES`（単一frozenset）を
  `HARD_FILTER_HIGHWAY_TYPES`（`{"motorway": {...}, "trunk": {...}}`の名前付き辞書）＋
  `DEFAULT_HARD_FILTERS`（`frozenset({"no_bicycle", "motorway", "trunk"})`）へ再構成し、
  `is_edge_allowed`に`hard_filters`引数（省略時`DEFAULT_HARD_FILTERS`、T141でレシピJSON化
  した際にレシピの`hard_filters`フィールドをそのまま渡せる形）を追加。既存呼び出し元は
  全て`hard_filters`省略のため動作は完全に不変（既存9件のis_edge_allowedテストが無変更で
  green）。`motor_vehicle=no`は方針どおりハード除外に含めず二次軸側の特例のまま維持し、
  その理由をdocstring・architecture.mdへ明記。docs/architecture.md 7章へ新設した
  「〇次: ハード制約」節にフィルタ一覧表・trunk除外の実務判断・motor_vehicle=noとの
  区別を記録、「道路種別の3スコープ」表・`import_profile.yaml`のコメントも新シンボル名へ
  追従。新規テスト6件（trunk除外の回帰確認2件＋hard_filters上書きの新規動作3件＋
  空集合で全許可1件）を追加。backend pytest 906件green（API契約・フロントへの影響なし、
  is_edge_allowedはHTTP境界に露出しないdomain内部関数のため）。

### - [x] T141. レシピをJSON/DBレコード形式へ統合し、hard_filters・axis_params・weightsを
  1つの定義から取り出せるようにする 規模L（2026-08-18・宣言層のみ完了、API配線はT142以降）

- 背景: 設計プロンプトの「レシピのデータ定義」節。現状は5つの独立YAML
  （`road_suitability_recipe.yaml`/`motor_vehicle_density_recipe.yaml`/
  `traffic_stress_recipe.yaml`→T138で`car_stress_recipe.yaml`相当へ統合/`safety_recipe.yaml`→
  T139で`night_recipe.yaml`相当へ/`route_preference.yaml`）に分散しており、recipe_id・version
  という概念も無い。研究モードのスロット比較（`ExperimentSlot`）を将来「差分レイヤー」へ
  発展させる前提（設計プロンプトの制約節）のため、レシピをID+versionで保持できる構造にする。
  実際にはT138/T139は`traffic_stress_recipe.yaml`/`safety_recipe.yaml`自体のリネームは
  行わなかった（呼称統一はT150へ分離）ため、この前提は一部先行して外れている。
- 対応方針: `Recipe`（recipe_id, version, hard_filters, axis_params, weights）をPydantic
  モデルとして`domain/recipe_definition.py`（仮）に新設。既存の個別YAML群は
  `axis_params`/`weights`のキーへマッピングして読み込む後方互換レイヤーを用意するか、
  1本のYAML/JSONへ統合するかを実装時に判断（既存の研究モードOverride APIとの互換性を優先）。
- 完了条件: 任意のレシピJSON（recipe_id+version付き）を与えると軸内係数・重みの両方が
  一意に取り出せることをテストで確認。既存の`*RecipeOverride`APIが新構造の上でも動作する
  （後方互換）か、置き換える場合はOpenAPI契約の更新をfrontend型生成と合わせて行う。
- 実装メモ（2026-08-18完了）: T137のレジストリと同じ「宣言のみ・まだどこにも配線しない」
  方針を踏襲。`backend/app/domain/recipe_definition.py`に`Recipe`
  （recipe_id/version/hard_filters/axis_params/weights）・`RecipeComponents`
  （既存の型付きモデル群のNamedTuple）・`recipe_from_components()`（型付きモデル群→
  `Recipe`）・`recipe_to_components()`（`Recipe`→型付きモデル群、`compute_edge_cost`等へ
  そのまま渡せる）・`default_recipe()`（クラス既定値から組み立てるショートカット）を実装。
  `axis_params`のキーは現行の軸内レシピ名（`road_suitability`/`motor_vehicle_density`/
  `traffic_stress`/`safety`）のままとし、設計プロンプトが示す目標axis_id
  （`car_stress`等）への統一はT150後に追従する方針を明記。`gradient`/`surface_q`/
  `stop_density`/`intersection_density`/`accident`/`night`はオーバーライド可能な
  「レシピ」を現状持たない（モジュール定数のみ）ため`axis_params`には含めない
  （将来これらにオーバーライドを追加する際の対象として記録）。**後方互換の確認方法**:
  API層・OpenAPI契約・フロントには一切手を入れず（`*RecipeOverride`API・既存5YAMLは
  無変更）、既存の挙動が字義通り100%不変であることでbackward compatibilityを満たす
  （置き換えではなく追加のみ）。実際の配線（APIがRecipeを受け渡しする・地図表示と
  コスト計算が同一Recipeから生成される）はT142（コスト関数の縮退）以降で行う。
  設計プロンプトのレシピJSON例と同じ生dict形（`recipe_id`/`version`/`hard_filters`/
  `axis_params`/`weights`のプレーンなJSON）から`Recipe`を構築し軸内係数・重みを
  一意に取り出せることをテストで確認（`test_recipe_definition.py`新規7件、
  round-trip・部分指定時のクラス既定値フォールバックを含む）。backend pytest
  913件green（API契約・フロントへの影響なし）。

### - [x] T142. コスト関数を「重みベクトル×レジストリ全軸」のみへ縮退し、一次属性への
  直接参照を排除する 規模L（2026-08-18・関数分離まで完了、transform_fn動的解決は未実施）

- 背景: 設計プロンプトの完了条件「三次のコードが一次属性名を一切含まない」。現状の
  `compute_edge_cost`（domain/evaluation.py）は`edge.highway`・`way_tags`等の一次属性を
  直接受け取り、`evaluate_axis_difficulties`へ生値を渡している。三次（コスト合成）と
  二次（軸計算）の境界をコード上で明確に分離する。
- 対応方針: `compute_edge_cost`を「軸レジストリ（T137）を走査し、各軸のtransform_fnへ
  一次属性を渡して軸スコアを得る→重みベクトルで合成→距離に乗算」という2段階に分離。
  一次属性の受け渡しは軸計算層（二次）までで完結させ、三次の関数シグネチャは
  `axis_scores: dict[str, float] + weights: dict[str, float] -> cost`のみを受け取る形にする。
- 完了条件: `compute_edge_cost`（またはその後継）のシグネチャに一次属性名（highway/lanes等）が
  一切現れないことをコードレビューで確認。backend pytest green、既存の`test_evaluation.py`の
  ケースが同じ結果を返すことを回帰確認。
- 実装メモ（2026-08-18完了）: T149を先行実施した流れでそのまま継続着手。
  `domain/evaluation.py`に`compute_edge_axis_scores()`（二次：一次属性→
  `dict[axis_id, float]`。`evaluate_axis_difficulties`を内部で呼ぶが重みは使わず捨てる）・
  `compute_cost_from_axis_scores(distance_m, axis_scores, weights)`（三次：**完了条件どおり
  シグネチャに一次属性名が一切現れない**純関数、`composite_difficulty`を再利用）・
  `preference_to_axis_weights()`（`RoutePreference`のフィールド名→レジストリのaxis_id
  への変換）を新設。`compute_edge_cost`自体は削除・改名せず、この2関数を合成する薄い
  ラッパーとして残し、既存の全呼び出し元（`EvaluationService`・`GraphService`・
  ベンチマーク等）への影響をゼロにした（後方互換）。`test_evaluation.py`へ9件追加
  （シグネチャに一次属性名が無いことの機械的検証、`compute_edge_cost`が2関数の合成と
  完全に同じ結果を返すことの回帰確認含む）。あわせて、T137で登録した`surface_q`軸の
  `transform_fn`がルート単位集約関数（`distance_weighted_road_score`）を誤って指して
  いたバグを発見・修正（正しくは区間単位の`road_difficulty`）。**未実施**: レジストリの
  `transform_fn`文字列を実際にimportlib等で動的解決して呼び出す、という完全な
  「レジストリ駆動」の実装（`compute_edge_axis_scores`は各軸の実関数を直接名指しで
  呼ぶ従来どおりの実装のまま）。各`transform_fn`のシグネチャが軸ごとに大きく異なる
  （tags dict・数値・boolなど）ため、汎用的な動的呼び出しには追加の標準化設計が要り、
  今回のスコープ（完了条件の充足）には含めなかった。将来必要になれば別タスクで
  検討する。backend pytest 923件green（API・フロントへの影響なし、domain内部のみ）。

### - [x] T143. 地図の合成スコア表示とルート生成のコストを同一レシピ定義から生成する 規模M（2026-08-18完了）

- 背景: 現状把握C.で判明した非DRY構造。`RoadGraphEngine._build_segment_details`/
  `OpenRouteServiceEngine._build_segment_details`は表示用に`evaluate_axis_difficulties`を
  独立に再計算しており、T142後のコスト計算パス（軸スコア→合成）と別実装になる可能性がある。
  設計プロンプトの完了条件「同一レシピ定義から地図表示とルーティングコストの両方が生成される」
  に対応する。
- 対応方針: T142で分離した「軸スコア計算」を両エンジンの区間表示ビルダーとコスト計算の
  共通経路にする（T134でのcar_closeness()二重計算解消と同じ考え方を、軸スコア全体に拡張）。
- 完了条件: 両エンジンの区間表示とコスト計算が同一の軸スコア計算結果を参照することを
  呼び出し回数の回帰テストで確認。backend pytest green。
- 実装メモ（2026-08-18完了）: 着手時に重要な非対称性を発見した。**「両エンジン」の
  うちOpenRouteServiceEngineは、そもそもルーティング自体（Dijkstra探索）を行わず
  経路探索を外部ORS APIへ委譲しており、`domain/evaluation.py`のコスト関数
  （`compute_edge_cost`等）を一切使わない**（既存のarchitecture.mdにも明記済みの設計。
  `_build_segment_details`の`evaluate_axis_difficulties`呼び出しは表示専用の唯一の
  計算箇所で、そもそも二重実装が存在しなかった）。実際に「表示」と「探索コスト」の
  2箇所が重複していたのは**RoadGraphEngineのみ**。よって本タスクの実質的な対応は
  `RoadGraphEngine._build_segment_details`を、`compute_edge_cost`（`EvaluationService`
  経由の探索コスト計算）と同じ`compute_edge_axis_scores`＋`compute_cost_from_axis_scores`
  （T142）へ差し替えることに限定した（`domain/difficulty.py: evaluate_axis_difficulties`の
  直接呼び出しを撤去）。`OpenRouteServiceEngine`は変更不要（元から重複が無いため対象外、
  この判断根拠をここに明記）。`test_road_graph_engine.py`へ
  `test_build_segment_details_uses_compute_edge_axis_scores`（spy経由で実際に共通関数を
  通ることを確認）を追加。`test_evaluation.py`の
  `test_compute_edge_cost_equals_composing_axis_scores_and_cost_functions`（T142で追加済み）
  と合わせて、「探索コスト（compute_edge_cost内部）」と「区間表示（_build_segment_details）」
  の両方が同一の`compute_edge_axis_scores`を経由することを実証。backend pytest 924件green。

### - [x] T144. エッジ軸スコアの永続化スキーマ（事故密度・停止密度の事前集計含む）を追加する 規模L（2026-08-19完了）

- 背景: 設計プロンプトのタスク3。事故密度・停止密度はPostGIS ST_DWithinでのEdge単位集計が
  重く、現状は`GraphService`が都度クエリしている。マテリアライズドビュー/バッチ更新での
  事前集計を検討する。軸を増やしても列追加で済むよう、固定カラムか`axis_id→score`の
  可変構造かを判断する。
- 対応方針: 既存の`docs/architecture.md`のPostGISクエリコスト関連レビュー（2026-08-16）を
  踏まえ、事故密度・停止密度の事前集計をマテリアライズドビューとして追加。エッジ軸スコアの
  保存要否（設計プロンプトは「Road Graphへ恒久保存しない」という既存方針＝
  `EdgeCostResult`のdocstringと矛盾しないことを要確認）はT145実装時に決定する。
- 完了条件: 新規マイグレーションがdev機・本番の両方へ適用され、事前集計値と都度クエリの
  結果が一致することを検証スクリプトで確認。
- 実装メモ（2026-08-19完了）: ユーザーから「本番マイグレーションは着手してもよい」の
  明示許可を得て実施。設計プロンプトの「エッジ軸スコアの保存要否はT145実装時に決定する」
  というヒントに沿い、**0-100の最終difficultyスコアではなく、その入力となる生カウント
  （accident_count/stop_count/intersection_count）を事前集計する**方針にした
  （最終スコアはユーザーのレシピ上書きに依存し「恒久保存しない」既存方針と衝突するが、
  生カウントは静的データのみに依存する安定値のため矛盾しない）。migration
  0010（`edge_attribute_counts`テーブル、`designation_attributes`と同じ「精密テーブル＋
  バッチ再計算」パターンを踏襲）・`app/batch/precompute_edge_attribute_counts.py`
  （新規。既存の`RoadGraphRepository.get_accident_counts`/`get_stop_poi_counts`/
  `get_intersection_counts`を再利用し新しいSQLは書かない）・
  `scripts/verify_edge_attribute_counts.py`（新規、検証）を実装。

  **実装中に2つの重要な発見があった**:
  (1) `get_intersection_counts`は「渡されたedge_ids集合内だけで完結するローカルな次数」を
  返す設計（`_INTERSECTION_COUNTS_SQL`のdocstringに明記済み、実際のルート生成では
  空間的に連続した1つのローカルグラフ全体を渡すため正しく機能する）。本バッチのように
  `road_edges`を空間的な連続性を考慮せず任意順にチャンク分割すると、同じNodeに接続する
  道路が別チャンクへ分かれ次数を過小評価する不整合が生じた（dev機実測: 500件サンプル中
  132件で不一致）。intersection_countだけ全edge_idsを1回のクエリに渡し真のグローバルな
  次数を計算する設計へ変更し解消（accident_count/stop_countはedge単位で独立のため
  チャンク分割のままで問題ない）。
  (2) さらに、**同一のedge_id集合でも配列の順序が異なるとget_intersection_countsの結果が
  変わる非決定性**を実際に確認した（`road_edges`由来の順序と`edge_attribute_counts`由来の
  順序で、同じ122,189件の集合に対し一部edgeの次数が異なった）。原因未特定。ユーザー
  指摘のとおり、get_accident_counts/get_stop_poi_counts（edge単位で独立な空間近傍カウント）
  とget_intersection_counts（集合全体に依存する相対的な次数）のインターフェースの
  非対称性が根本原因。**今回はroad_edges起点の順序へ統一することで実害を回避したのみ**で、
  根本修正はT151として新規起票（ユーザー指示により今回は対応せず計画のみ）。

  dev機（road_edges 122,189件）: migration適用→バッチ実行（45秒）→検証（3,000件サンプルで
  全件一致）。本番（Oracle Cloud、207,767件）: migration適用→バッチ実行（実行時間計測は
  ツールのタイムアウトで打ち切られたが、対象207,767件が過不足なく書き込まれたことを
  直接カウント確認）→検証（500件サンプルで全件一致）。backend pytest 935件green。
  **本番の`get_accident_counts`/`get_stop_poi_counts`/`get_intersection_counts`の実クエリ
  経路（road_graph_engine.py等）は今回変更していない**（`edge_attribute_counts`テーブルは
  作成・データ投入のみで、まだ読み取り経路には配線していない。配線はT145実装時、または
  実際のクエリコストが問題になった時点で判断する）。

### - [ ] T145. 地図レイヤーパネルをレジストリ駆動にし、三次（合成コスト）を既定表示レイヤーとして
  新設する 規模L →（2026-08-19、T145a/T145bへ分割・方針再定義）

- 背景: 設計プロンプトのレイヤー表。現状の`mapLayers.ts`は10レイヤーが個別列挙で、
  「常時表示は合成コストのみ」に対応する三次レイヤー自体が存在しない。一次・二次は
  レジストリ（T137、ただしフロント側は別途TypeScript版が必要）から動的に列挙し、軸を
  増やしてもレイヤーパネル・凡例の改修が不要な構造にする。
- 分割の経緯（2026-08-19）: ユーザーと方針を協議し、当初案の「二次レイヤーの動的生成」を
  具体化する過程で2つの重要な制約を確認した。(1) 現行タイルは全ユーザー共有キャッシュ
  （Cache-Control: max-age=3600）のため、レシピ依存の軸最終値をサーバー側で焼き込むと
  研究モードの重み上書き（将来的にはユーザー別レシピ、T141のJSON/DB化が布石）と矛盾する。
  (2) 逆にaccident/stop_density軸は入力データ（事故点・POI集計）自体がタイルに無いため、
  クライアント側expressionでは原理的に計算できない。この2つから、アプリ自身の層構造を
  配信アーキテクチャへ写す「**事実はタイルに、解釈はクライアントに**」方針を採択した:
  一次属性・事前集計カウント（レシピ非依存の事実）はサーバー焼き込み、二次軸スコア
  （レシピ依存の解釈）はクライアントexpressionで計算する。三次（合成コスト）レイヤーは
  本タスクのスコープから外す（係数検証が別途必要なため、実施時期はユーザー判断）。

### - [ ] T145a. night軸の専用レイヤーを追加する 規模S〜M — トリガー: night軸の入力データ
  （lit/tunnelタグ）の充実

- 背景: 6軸のうちnightだけ対応する地図レイヤーが無い。ただし現OSMデータではlitタグが
  疎で、レイヤーを作っても他軸との差がほぼ見えないことをユーザーと確認済み（2026-08-19）。
- 対応方針: T145bの汎用機構へ普通に乗せる（専用実装はしない）。データが充実した時点で
  レジストリ登録のみで地図に現れるのが理想形。
- 完了条件: night軸レイヤーが地図上で意味のある差を表示できること。

### - [x] T145b. 「事実はタイルに、解釈はクライアントに」方針でレイヤーシステムを
  レジストリ駆動化する 規模L（2026-08-19完了、本番反映済み）

- 対応方針（2026-08-19確定、ユーザー承認済み）:
  1. **タイルへの事実の焼き込み**: `_ROAD_SURFACE_TILE_MVT_SQL`へ`edge_attribute_counts`
     （T144新設・T151で決定性担保済み、現在未配線）をJOINし、accident_count/stop_count/
     intersection_countをMVTプロパティとして追加する。これらはレシピ非依存の静的な事実
     のためキャッシュ設計と矛盾しない。`ROAD_SURFACE_TILE_VERSION`を対上げする
     （過去2回の対上げ漏れパターンに注意、完了条件に含める）。
  2. **軸カタログの書き出し**: `export_openapi.py`の既存パターンでレジストリ
     （`registry_defaults.py`）から軸カタログJSON（axis_id・ラベル・入力タイル
     プロパティ・値域・凡例情報・表示方式）を書き出す。
  3. **フロントの汎用レイヤーファクトリ**: 単一数値プロパティの単調ランプ_で表せる軸
     （accident/stop_density等）はカタログからexpressionを自動生成。タグの複雑な組み
     合わせを要するcar_stressは手書きexpression（`carStressExpression.ts`）を例外として
     登録する形で残す。パネル・凡例・トグルはカタログ駆動へ。
  4. 既存タイルにある事実から作れる新軸はレジストリ登録のみで地図に現れる状態を目標と
     する（新データ源が要る軸は取込＋事前集計＋タイルプロパティ追加＋登録）。
- 運用注意: `edge_attribute_counts`の鮮度がタイルに乗るため、PBF再取込時のバッチ再実行
  順序が「precompute_road_node_degrees→precompute_edge_attribute_counts→タイル
  キャッシュ破棄（世代対上げ）」の3段連鎖になる。ドキュメント化必須。
- 完了条件: (a) accident/stop_density軸のレイヤーが地図上で実データ表示されること
  （Playwright実機確認）。(b) タイル世代がバックエンド・フロント生成物・手書き定数の
  3箇所で一致することをドリフト検知テストで確認。(c) タイル生成コスト増をEXPLAIN
  ANALYZE等で実測し記録。(d) backend pytest・frontend vitest・eslint・tsc全green。
- 実装メモ（2026-08-19完了）: 実装中に方針へ影響する発見が2つあった。
  **(発見1) edge_attribute_counts（T144）は地図表示の母集団にできない**: road_edgesは
  ルート生成時に遅延構築されるため、タイル内wayのカバレッジがdev実測で約3.6%
  （748way中27way）しかなく地図がほぼ空になる。ユーザー協議のうえ**way単位の事実テーブル
  `way_attribute_counts`（母集団=osm_raw_ways全域）を新設**（migration 0012、
  `raw_intersection_nodes`〔osm_raw_ways.node_idsの隣接関係から導出した次数3以上の
  生ノード、Road Graph非依存〕含む）。カウントの意味論（半径・kindフィルタ・死亡事故
  重み・次数しきい値）はedge単位版と同一で、タイルへはkm正規化した密度
  （accident_per_km/stop_per_km/intersection_per_km、0はNULLIFでキー省略）を焼き込む。
  way単位集約による点データのぼやけは実測で限定的と確認（way長中央値98.4m＝edge粒度と
  同等、1km超は0.7%。ルート評価はedge単位のまま無影響、正確な点位置は既存の事故・
  停止要因レイヤーで確認可能）とユーザー合意済み。
  **(発見2) 停止密度がT101以降コンビニ・自販機を誤算入するバグ**: `_STOP_POI_COUNTS_SQL`/
  `_NEAREST_STOP_POI_COUNTS_SQL`にkindフィルタが無く、T101で同じosm_raw_poisへ入った
  補給POI（dev実測で全POIの約17%）を停止要因として数えていた。`STOP_POI_KINDS`
  （domain/traffic.py新設、StopPoiKind Literalとの一致を回帰テストで担保）でフィルタする
  修正を実施（**dev/本番のedge_attribute_counts・way_attribute_countsは修正後SQLでの
  再計算が必要**。devは実施済み、本番は未実施）。
  実装: バッチ`precompute_way_attribute_counts.py`（2段階: raw_intersection_nodes全再構築
  →way単位カウントのチャンクUPSERT。dev実測86,642way・51.2秒）、タイルSQLへ
  way_attribute_countsのLEFT JOIN＋per-kmプロパティ3種（`ROAD_SURFACE_TILE_VERSION`
  11→12対上げ、z14タイル生成実測0.109秒）。レジストリへ`AxisDisplaySpec`/`TileInputSpec`
  を拡張（kind=ramp/bespoke/none、tile_inputsの線形結合重み〔stop_densityの無タグ交差点
  0.3はdomain/difficulty.py: UNSIGNALED_INTERSECTION_WEIGHTを片側import〕・しきい値・
  凡例情報を宣言）、`export_openapi.py`が`axis-catalog.json`を書き出し。フロントは
  `axisLayers.ts`（新規、カタログのramp軸からvalue/color expression・凡例を自動生成）＋
  `mapLayers.ts`/`MapView.tsx`/`page.tsx`のカタログ駆動化（MapLayerIdへ`axis:${string}`
  テンプレート型を追加、STATIC_OVERLAY_LAYERS・LAYER_DATA_SOURCES・DEFAULT_LAYER_
  VISIBILITYへ自動合流）で、**新しいramp軸はレジストリ登録＋タイル焼き込みだけで
  チップ・パネル・凡例・地図レイヤーが現れる**構造になった。実装中の実バグ1件
  （チップアイコンがRecord<MapLayerId,Icon>から引けずundefinedコンポーネントで500）は
  AxisRampIcon（全ramp軸共用）へのフォールバックで解消。night/car_stressはbespoke宣言
  （car_stressは既存の手書きexpression、nightはT145a保留のままレイヤー未生成）、
  gradient/surface_qはnone宣言（標高図・道路情報レイヤーが代替）。
  検証: backend pytest 948件（新規: kindフィルタ回帰2件・raw_intersection_nodes/
  way_attribute_counts統合3件・STOP_POI_KINDSドリフト1件）・frontend vitest 381件
  （新規axisLayers.test.ts 8件・regionApi世代更新）・tsc・eslint全green。Playwright
  headless実機確認（退避ポート8001/3011）: 停止密度・事故密度チップの自動出現・ON切替・
  `?v=12`タイル取得9/9・パネルの交通・安全グループへの自動出現・地図の密度色分け描画を
  スクリーンショットで確認（コンソールエラーは退避ポート環境のCORS等のみ、軸レイヤー
  無関係）。**本番Oracle Cloudへも同日反映済み**: migration 0011/0012適用→3バッチ実行
  （degrees: 207,767件・2.9秒／edge_counts再計算〔バグ修正込み〕: 207,767件・64.9秒／
  way_counts: 1,329,632件・289.9秒）。反映後の実データ確認: way_attribute_counts
  133万件中96.1%（1,278,270件）が交差点近傍データを持ち、accident_count>0が12.1%・
  stop_count>0が18.9%（関東本土全域、dev機の東京都心南部限定データより広く分布）。
  raw_intersection_nodes 1,407,164件・road_nodes.degree>0が80,612件。

### - [x] T146. 区間インスペクタをレジストリ駆動にし、一次属性まで遡って表示できるようにする 規模M（2026-08-19完了）

- 背景: 設計プロンプトの区間インスペクタ要件。現状の`recipeBreakdownPopup.ts`は
  車の圧迫感・安全度の内訳（N1/N2込み）を個別に表示する専用実装で、軸を追加するたびに
  改修が必要。
- 対応方針: T145のレイヤーレジストリ生成物を再利用し、クリックした区間の一次属性→軸別
  スコア→合成コストをレジストリ走査で組み立てる汎用ポップアップへ置き換える。
- 完了条件: 任意の区間で一次属性から合成コストまでの内訳がポップアップに表示されることを
  Playwright実機確認。
- 実装メモ（2026-08-19完了）: 着手前にユーザーと「合成コスト」の扱いを協議した。勾配軸
  （標高データ）はルート沿いの区間文脈が無いと算出できないため、単独クリックしたwayでは
  原理的に正確な値を出せない。ユーザー承認のうえ「取得可能な軸だけで部分合計を出し、
  勾配軸は欠損と明記する」方針を採用した。また、当初検討したクライアント側での難易度式
  再実装（TSミラー）はPython側とのドリフトリスクがあるため見送り、**既存の車ストレス/
  安全度内訳ボタンと同じ「クリック時にサーバーへ1回問い合わせて正確な値を返す」パターン**
  へ統一した（タイル共有キャッシュとは無関係のper-request計算のため、T145bの
  「サーバー側で最終値を焼かない」制約はそもそも適用されない）。
  実装: `domain/evaluation.py`へ`axis_inspector_breakdown`（純関数、car_stress/surface_q/
  stop_density/accident/nightの5軸を`way_attribute_counts`＋タグから算出し
  `composite_difficulty`と同じ「データ無しは除外・残りの重みで再正規化」方針で部分合成、
  gradient/windは常にavailable=false）・`AxisInspectorResult`/`AxisInspectorAxis`を新設。
  `RoadGraphRepository.get_way_attribute_counts`（osm_way_id完全一致1行取得）を新設し
  `RegionService.get_axis_inspector`から`get_way_tags_by_osm_way_id`・
  `get_accident_years_covered`と束ねて呼ぶ。新エンドポイント`POST /api/region/
  axis-inspector`（既存の`_breakdown_response`ヘルパーをそのまま再利用、レート制限・
  リクエスト形は車ストレス/安全度内訳と同型）。フロントは`axisInspectorPopup.ts`
  （新規）が`axisLayers.ts: AXIS_LABELS`（axis-catalog.json由来、windのみレジストリ
  未登録のため補完）でラベルをカタログ駆動表示し、`MapView.tsx`の道路クリックポップアップへ
  「一次属性・全軸の内訳を見る」ボタンとして配線（osm_way_idが分かる区間なら常時表示、
  車ストレス/安全度個別ボタンとは独立に併存）。
  検証: backend pytest 960件（新規: 純関数4件・RegionService統合6件・repository統合2件）・
  frontend vitest 384件（新規axisInspectorPopup.test.ts 3件）・tsc・eslint全green。
  OpenAPI再生成・フロント型再生成（`AxisInspectorResult`/`AxisInspectorAxis`）済み。
  Playwright実機確認（退避ポート8001/3011、CORS許可オリジンへ3011を追加）で実際の区間
  クリック→ボタン押下→一次属性（highway・タグ）/二次軸スコア5軸/合成コスト58.3（重みの
  約44%相当の軸のみで算出、勾配・風は欠損と明記）の表示をスクリーンショットで確認。

### - [x] T147. 軸間相関行列（ピアソン）を計算するスクリプトを実装する 規模M（2026-08-18完了）

- 背景: 設計プロンプトのタスク8。T137のレジストリ登録時バリデータ（事前チェック）を
  すり抜ける間接的な相関（例: 異なる一次属性由来でも結果的に相関する）を事後監視する。
- 対応方針: `backend/scripts/measure_axis_correlation.py`（新規、既存の
  `measure_axis_stats.py`のデータ取得パターンを再利用）で全区間の軸スコアを取得し、
  ピアソン相関行列を算出。|r| > 0.7のペアを警告として標準出力・レポートファイルへ出力。
- 完了条件: dev DBまたは本番DBに対して実行し、6軸（car_stress/accident/surface_q/
  stop_density/gradient/night）すべてのペアで|r|が算出され、結果がレポートとして記録される
  （0.7を超えるペアがあれば、対応する軸内係数の見直し課題として別タスク化する）。
  T138で据え置いた「自転車インフラ統合後の`car_stress`↔`accident`相関確認」・
  「旧`traffic_weight`+`infra_weight`合成値との分布比較」も、本スクリプトの初回実行と
  併せてここで実施し、T138の完了条件を事後的に満たす。
- 実装メモ（2026-08-18完了）: 着手時に標本設計上の制約を発見した。gradient軸の入力
  （標高average_grade）は`elevation_attributes`テーブルが常時空（dev DB実測でCOUNT(*)=0
  確認、Road Graphへ恒久保存しない設計のため）で、国土地理院APIから都度取得する以外に
  取得手段が無い。他5軸はDBのみで大規模に計算できる一方gradientだけ外部API依存という
  非対称があるため、5軸を全件・gradientだけ小標本、という統計的に歪んだ比較を避け、
  **6軸すべてを同一のランダムサンプル（road_edgesからN件、既定300）に対して計算する**
  設計にした。`backend/scripts/measure_axis_correlation.py`（`pearson_correlation`・
  `correlation_matrix`は純関数、`RoadGraphRepository`の既存メソッド群
  （get_way_tags/get_surface_attributes/get_stop_poi_counts/get_intersection_counts/
  get_accident_counts/get_designated_edge_ids）とGSI `ElevationClient`を再利用してDB/外部
  APIから取得）・`--output`でのレポートファイル書き出しに対応。`test_measure_axis_correlation.py`
  （純関数8件）を追加。dev DBに対しn=300で実行し、**6軸すべてでr値を取得**（surface_qは
  有効値154/300、道路が概ね舗装済みで分散がほぼ0のため全ペアでr=N/A＝相関未定義という
  正しい統計的判定。他5軸の全15ペア中、|r|>0.7の警告は0件）。特に`car_stress`↔`accident`
  はr=0.308（弱い正の相関、二重計上の懸念なし。T138の据え置き事項を解消）。実行結果は
  本エントリに記録（レポートファイル自体はスクラッチパッドに保存、リポジトリには
  コミットしない運用、`measure_axis_stats.py`等の既存計測スクリプトと同じ扱い）。
  backend pytest 932件green。

### - [ ] T148. 旧・安全度レイヤーと計算コードを削除する 規模M

- 背景: 設計プロンプトのタスク9。T139〜T147の移行が完了し、night/accident/car_stress軸への
  切替が本番で安定稼働していることを確認したうえで、`domain/safety.py`・
  `safetyExpression.ts`・`safety`レイヤー・`safety_recipe.yaml`・関連API
  （`SafetyRecipeOverride`等）を削除する。
- 対応方針: 削除前に本番での稼働実績（最低1〜2週間、他タスクの完了条件と同様の慣例）を
  確認してから着手する。削除後はOpenAPI契約・フロント生成型を再生成し、ドリフトが無いことを
  CIで確認する。
- 完了条件: `safety`関連のシンボル・エンドポイント・レイヤーがコードベースから消え、
  backend pytest・frontend vitest・eslint・tsc・OpenAPIドリフト検知すべてgreen。

### - [x] T149. 交差点密度(intersection_density)をstop_density軸へ吸収する 規模M（2026-08-18完了）

- 背景: 設計プロンプト改訂（2026-08-18）「現行9軸からの帰属先（T140対応）」節。
  intersection_densityは単独軸を持たず、信号・横断歩道・一時停止・踏切と同じstop_density軸へ
  「タグなし交差点」を独立した低い重みのカテゴリとして吸収する（例:
  `unsignaled_intersection: 0.3`、signal=1.0比）。理由は「立ち止まる／減速する頻度」という
  同じ性質の指標であり、car_stress（走行中の車との近接ストレス）とは質的に異なるため。
  T137で先行登録していた`intersection_density`単独軸のレジストリ宣言は既に修正済み
  （`stop_density`のinputsへ`intersection`を追加、上記T137実装メモ追記参照）。
- 対応方針: `domain/traffic.py`の`distance_weighted_stop_density`（またはT141で再編される
  stop_density軸のtransform_fn相当）が、信号・横断歩道・一時停止・踏切のカウントに加えて
  次数3以上の無タグ交差点（`GraphService.get_intersection_counts`由来）を
  `unsignaled_intersection`カテゴリとして低い重みで合算するよう改修。既存の
  `intersection_weight`（`route_preference.yaml`）は廃止しstop_weight側へ吸収する。
  `domain/difficulty.py`の`intersection_difficulty`は本タスクで`stop_difficulty`へ統合し
  廃止（削除はT148と同様、移行完了確認後でよいが、こちらは軸自体が消えるため即時削除で
  問題ない規模と判断）。
- 完了条件: backend pytest green。stop_density単軸値が旧`stop_weight`+`intersection_weight`
  合成値の分布からの急変が無いことを実データで確認。レジストリ上`intersection_density`という
  axis_idが存在しないことを回帰テストで確認。
- 実装メモ（2026-08-18完了）: T142（コスト関数のレジストリ駆動化）に着手する前提として、
  レジストリ（T137）が既に「stop_densityがintersectionを吸収する」という目標構造を宣言
  していたのに対し、ドメインコード側はまだ`intersection_difficulty`を独立軸として計算
  していたという不整合を発見し、T142より先に本タスクを実施した。`domain/difficulty.py:
  stop_difficulty(stop_count_per_km, intersection_count_per_km=None)`へ改修し、
  `_UNSIGNALED_INTERSECTION_WEIGHT=0.3`（design promptのunsignaled_intersection:0.3、
  signal:1.0比）でタグなし交差点密度を加算するよう変更（`intersection_count_per_km`が
  Noneでも寄与0として扱う非対称設計、stop_count_per_km自体がNoneなら評価しない）。
  `intersection_difficulty`関数・`AxisDifficulties.intersection`フィールド・
  `evaluate_axis_difficulties`の`intersection_weight`引数を削除（8軸→7軸、
  `intersection_count_per_km`自体はstop_difficultyへの補助入力として残す）。
  `domain/evaluation.py: RoutePreference.intersection_weight`廃止・`stop_weight`
  0.15→0.20（合算）。`domain/route.py: RouteSegmentDetail.intersection_difficulty`削除
  （route集約統計`RouteCandidate.intersection_density`・地図の`poi-tiles`表示は表示用
  一次属性として維持）。両エンジン・API`RoutePreferenceWeights`・OpenAPI・フロント型・
  `WeightPanel.tsx`/`evaluationAxes.ts`を追従。`registry_defaults.py`へ`car_stress`
  （T138）・`night`（T139）軸も併せて登録（T137時点で保留していた3軸のうち2軸が
  排他構造へ再編済みのため）、これによりレジストリの登録軸が設計プロンプトの目標6軸
  （car_stress/accident/surface_q/stop_density/gradient/night）と完全一致した
  （`test_registry_defaults.py`で確認）。docs/architecture.md §7を8軸→7軸表記へ更新。
  backend pytest 915件・frontend vitest 372件・tsc・eslint・`next build`全green。

### - [x] T151. get_intersection_countsのインターフェースを他の空間集計メソッドと揃える 規模M（2026-08-19完了）

- 背景: T144実装中に発見（ユーザー指摘）。`get_accident_counts`/`get_stop_poi_counts`は
  edge単位で完全に独立な「半径内の件数」を返すのに対し、`get_intersection_counts`だけは
  「渡されたedge_ids集合全体から構成される部分グラフ内での相対的なNode次数」を返す
  （`_INTERSECTION_COUNTS_SQL`のdocstringに明記された意図的な設計）。この非対称性により
  (a) 呼び出し元が渡すedge_ids集合が変わると同じedgeでも結果が変わりうる、
  (b) より重大な発見として、**同一のedge_id集合でも配列の順序が異なると結果が変わりうる**
  ことをT144の検証中に実際に確認した（road_edges由来の順序とedge_attribute_counts由来の
  順序で、同じ122,189件の集合に対し一部edge（例: way-1010971919-seg0-fwd）の次数が
  0または1と異なった。原因未特定、PostgreSQLのクエリプラン非決定性の可能性）。
- 影響: `road_graph_engine.py`の実際の呼び出し（`get_intersection_counts(list(graph.edges.keys()))`）は
  Python dict/NetworkXのキー順序に依存するため、理論上は同じedgeが実行のたびに異なる
  交差点密度を返しうる。実害の大きさは未検証（T144の500〜3,000件サンプルでは0.6%程度の
  edgeで±1件の差、intersection_countはstop_density軸内で0.3倍の低い重みのため最終
  difficultyへの影響はさらに小さいと推測されるが、確認はしていない）。
- 対応方針（未実施、方針のみ。ユーザー指示により今回は計画のみで着手しない）:
  `get_accident_counts`/`get_stop_poi_counts`と同じ「edge単位で独立な空間近傍カウント」の
  意味論へ変更する。具体的には、次数を「渡されたedge_ids集合内で完結する部分グラフの
  次数」ではなく「対象road_nodeの真のグローバル次数（DB全体で見た次数）」に統一する。
  現在のコメントが警告する「DB全体を毎回集計すると遅い」問題は、T144で新設した
  `edge_attribute_counts`（本番207,767件で全体集計しても数分規模、既に実測済み）を
  正準の参照先にする、または`road_nodes`側に次数を事前計算・キャッシュする列を持たせる
  ことで解消できる可能性がある。
- 完了条件（未実施）: `get_intersection_counts`が入力集合の順序に依存せず、かつ
  `get_accident_counts`/`get_stop_poi_counts`と揃った意味論（真のグローバル次数）の
  決定的な実装になっていることをテストで確認（同一edge_id集合を異なる順序で2回渡し、
  結果が一致することを確認する回帰テストを含む）。
- 実装メモ（2026-08-19完了）: 非決定性の原因をコードから確定できた。「PostgreSQLの
  クエリプラン非決定性の可能性」という当初の推測は誤りで、実際は`get_intersection_counts`
  内部の`_chunked(edge_ids, 50_000)`（road_graph_repository.py）が原因。チャンク境界は
  リストの位置で決まるため、入力順序が変わるとチャンク境界がずれ、境界をまたぐノードの
  近傍が別チャンクに分かれて次数を過小評価する（T144の「全edge一括」対策も、渡した先の
  `get_intersection_counts`が内部でさらに50,000件ずつ再分割していたため効いていなかった）。
  対応方針どおり`road_nodes.degree`（DB全体から見た真のグローバル次数）へ一本化。
  migration 0011（`road_nodes.degree integer NOT NULL DEFAULT 0`）・
  `DerivedGraphRepository.recompute_node_degrees()`（新設、単一UPDATE...FROMで
  road_edges全件から再計算、PostGIS空間結合を伴わないためチャンク分割不要）・
  `app/batch/precompute_road_node_degrees.py`（新設、上記メソッドを呼ぶだけ）を実装。
  `_INTERSECTION_COUNTS_SQL`/`_NEAREST_INTERSECTION_COUNTS_SQL`は次数計算CTEを削除し
  `rn.degree >= :degree_threshold`を参照するだけに簡略化（両クエリとも大幅に短くなった）。
  `precompute_edge_attribute_counts.py`の「intersection_countだけ全edge一括」という
  特殊分岐が不要になったため削除し、accident_count/stop_countと同じチャンクループへ統合
  （結果としてバッチが単純化・高速化。dev機実測41.7秒、T144時点の記録より高速）。
  **運用上の実行順序**: `precompute_road_node_degrees.py`→`precompute_edge_attribute_counts.py`
  の順で実行すること（後者のintersection_countは前者が書く`degree`列を参照するため）。
  回帰テスト`test_get_intersection_counts_is_independent_of_edge_id_order_and_subset`
  （同一集合を逆順で渡す一致確認、部分集合を渡しても結果が変わらないことの確認）を追加。
  既存3件のintersection関連テストへ`recompute_node_degrees()`呼び出しを追加（degreeが
  ノード作成時点では既定値0のため）。dev機（road_edges 122,189件）でmigration適用・
  degreeバックフィル（5.7秒）・edge_attribute_counts再計算（41.7秒、3,000件検証で
  全件一致）・5,000件規模での順序反転一致（0件不一致）を実機確認。backend pytest 942件
  green。**本番Oracle Cloudへも同日（T145b対応の一環で）反映済み**: migration適用・
  degreeバッチ（207,767件・2.9秒）・edge_attribute_counts再計算（207,767件・64.9秒）まで
  実行完了。
  副次的な発見: dev機で`road_nodes`の22%（66,892件中14,784件）がroad_edgesから一切
  参照されないorphanノードと判明（degree=0の大半を占める。次数フィルタで確実に除外され
  intersection_countの正しさには影響しないため実害なし）。過去のWay再split時にEdgeだけ
  削除されNodeが残置され続けた蓄積と推測されるが、原因調査・削除はT151のスコープ外の
  別問題として今回は対応せず記録のみ。

### - [x] T150. 呼称をtraffic_stress→car_stressへ統一する（バックエンド・フロントエンド全体） 規模L（2026-08-19完了）

- 背景: T138で自転車インフラの独立軸廃止（機能面の統合）は完了したが、設計プロンプトが
  求める呼称そのものの統一（`domain/car_stress.py`新設、`TrafficStressRecipe`→
  `CarStressRecipe`、`traffic_stress_level`→`car_stress_level`、API
  `TrafficStressRecipeOverride`→`CarStressRecipeOverride`、フロント
  `trafficStressExpression.ts`→`carStressExpression.ts`、`TrafficStressRecipePanel`→
  `CarStressRecipePanel`、MVTプロパティ`traffic_stress`→`car_stress`、`mapLayers.ts`の
  レイヤーid・ラベル等）はT138から意図的に分離した（影響がbackend34ファイル・
  frontend42ファイルに及ぶ純粋な機械的リネームのため、機能変更と混在させると
  レビュー・切り戻しの単位が大きくなりすぎる）。
- 対応方針: 挙動を一切変えない前提でシンボル名・ファイル名・MVTプロパティ名・
  APIフィールド名を機械的に置換する。OpenAPI契約が変わる（`traffic_stress_recipe`→
  `car_stress_recipe`等）ため、backend変更→OpenAPI再生成→フロント型再生成→フロント
  参照更新、の順で1コミットにまとめる（契約変更を跨いだ中間状態を残さない）。MVT
  プロパティ名の変更はタイル世代を上げる必要がある（`ROAD_SURFACE_TILE_VERSION`、
  `road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）。
- 完了条件: `grep -ri "traffic_stress\|trafficStress\|TrafficStress"`
  （純粋な履歴記録・コメント中の「旧」を除く）がbackend/frontendのソースコードから
  消えること。backend pytest・frontend vitest・eslint・tsc・`next build`・OpenAPI
  ドリフト検知すべてgreen。Playwright実機確認で研究モードのレシピパネル・地図レイヤー・
  区間インスペクタの表示が変更前と同一であることを確認。
- 実装メモ（2026-08-19完了）: backend（39ファイル＋`traffic_stress_recipe.yaml`→
  `car_stress_recipe.yaml`のファイル名変更、`git mv`で履歴保持）→frontend（48ファイル、
  `trafficStressExpression.ts`→`carStressExpression.ts`・`TrafficStressRecipePanel/`→
  `CarStressRecipePanel/`のディレクトリ名変更込み）の順に、それぞれ専用エージェントへ
  委譲して機械的リネームを実施（合計約90ファイル）。API契約変更（`traffic_weight`→
  `car_stress_weight`、`traffic_stress_recipe`→`car_stress_recipe`、`traffic_stress_score`→
  `car_stress_score`、エンドポイント`/api/region/traffic-stress-breakdown`→
  `/api/region/car-stress-breakdown`）を含むため、backend完了後に`export_openapi.py`→
  `openapi-typescript`の順で再生成してからfrontend側に着手する依存順を守った。
  対応方針が見込んでいたMVTタイルプロパティの改称・タイル世代アップは**不要と判明**（実装調査の結果、
  `_ROAD_SURFACE_TILE_MVT_SQL`は最終値ではなく材料タグ`cycleway_class`/`maxspeed_kmh`等のみを
  焼き込む設計であり、`traffic_stress`という文字列そのものをプロパティキーとして持っていなかった
  ため。対応方針の記述はこの点で不正確だった）。JSON学習用フィクスチャ
  `traffic-stress-recipe.json`/`traffic-stress-test-cases.json`は意図的に旧名のまま維持
  （`export_openapi.py`側のパス定数を今回は変更せず、frontendの`carStressExpression.ts`側に
  この命名不一致を明記するコメントを追加。両者を揃えるのは別タスクとして残置）。
  委譲実行中に2件の実装ミスを発見・自己修正済み: (1) backend側で改行コードがCRLFへ
  混入する副作用が発生し全ファイルLFへ正規化、(2) frontend側でPowerShellの大文字小文字
  非区別置換により`CAR_STRESS_recipe`等の破損した識別子が混入し復旧。最終検証は
  backend pytest 941件（postgisマーカー6件含む）・frontend vitest 372件・tsc・eslint・
  `next build`すべてgreen、実データ（dev DB）に対する`/api/region/car-stress-breakdown`の
  疎通確認、Playwright実機確認（研究モードON→評価の重みパネルに「車の圧迫感」ラベル・
  値0.2が正しく表示、`CarStressRecipePanel`が「車の圧迫感[地図の色分けに即時反映]」として
  正常描画、コンソールエラー・`undefined`/`NaN`表示なし）まで完了。

### - [ ] T152. way_attribute_countsのWay単位平均化による精度劣化を実測し、交差点分割
  セグメント単位への移行要否を判断する 規模M

- 背景: `way_attribute_counts`（T145b、`road_graph_models.py: WayAttributeCountsRow`）は
  事故・停止POI・交差点密度をWay全体の長さで平均した1行/Wayとして持つ。一方
  `edge_attribute_counts`（T144、ルート評価用）はWayを交差点で分割したEdge単位で持つため、
  事故・停止がWay内で局所的に偏っている場合、地図のWay単位表示（平均値）と実際に
  そのEdgeを通ったときの評価値がズレる。この「集計単位のぼかし誤差」がどの程度の
  規模か未計測（ユーザーとの議論で「①通れない道の混入は表示ノイズに留まりルート評価には
  波及しない」「②Way全体平均によるぼかしの方が本質的」と整理済み、②が本タスクの対象）。
- 対応方針:
  1. `backend/scripts/measure_way_segment_split.py`（本タスク登録と同時に追加済み）を
     PBF取込済みのdev/ステージングDBに対して実行し、Way単位→交差点分割セグメント単位へ
     上げた場合の走査コスト倍率（モデルA=`build_road_graph`と同一の真の分割基準、
     モデルB=既存`raw_intersection_nodes`（次数3以上）を再利用する安価な近似）を実測する。
  2. 実測値（cost_multiplier_a/b、p90/p99/maxのセグメント数分布、A/Bの乖離）を基に、
     「②の精度劣化がどれだけ実害か」「モデルBの近似精度で十分か」を評価する。
  3. 上記を踏まえ、次のいずれかを判断する: (a) 現状維持（Way単位のまま、精度劣化は許容）、
     (b) `raw_intersection_nodes`ベース（モデルB）でセグメント単位化、(c) 真の分割基準
     （モデルA、`edge_attribute_counts`と同じ精度）でセグメント単位化。コスト抑制策として
     「低ズームはWay単位平均、高ズーム（`ROAD_TILE_MIN_ZOOM`〜`MAX_ZOOM`）のみセグメント
     単位」という二段構えの要否もあわせて判断する。
- 完了条件: dev/ステージングDBでの実測値が改善計画（本タスク）に記録され、上記(a)〜(c)の
  いずれかが決定され、決定した場合は後続の実装タスク（テーブル設計・バッチ変更）として
  新規起票されていること。現状維持(a)と判断した場合も、その根拠（実測倍率・乖離の規模）を
  記録した上でチェック完了とする。

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
| 2026-08-17 | T107（コードレビュー対応） | T107実装のコードレビューで5件（1: レシピ既定値がYAML/Python定数の2箇所に分裂しドリフト検知テストが無い、2: SQL⇔Python整合性テスト削除に伴いPython⇔JS間の実ドリフト検知が失われていた、3: lanes/maxspeed="0"でPythonとフロント式の判定が食い違う、4: v9はプロパティ削除を伴う初のタイル世代非互換変更でデプロイ順序次第で一時的に地図が全線グレー化しうる、5: `@maplibre/maplibre-gl-style-spec`を新規依存追加したがmaplibre-gl内蔵版とのバージョン乖離リスク）を検出・全件修正。`_cycleway_class`/`traffic_stress_tile_ingredients`をdomain/traffic.pyへ切り出し、`export_openapi.py`が`traffic_stress_level()`の実行結果を`traffic-stress-test-cases.json`へ書き出しフロントの`trafficStressExpression.test.ts`がこれを検証する形でPython⇔JS実ドリフト検知を復元。SQL側でmaxspeed/lanes="0"を無効値として除外。YAML既定値のドリフト検知テストを`route_preference.yaml`と同じ方式で追加。デプロイ順序の注意をregionApi.ts/region_service.py/architecture.mdへ明記。style-specをexact pin。backend 735件・frontend 265件・tsc・eslint全green |
| 2026-08-17 | T91 | 統合レビューF-3（MapView.tsx閾値監視の空白化）に対応。当初閾値（静的レイヤー+2種 or MapView 1,200行）は決めておいた2点（宣言的レイヤー登録・useStoredState抽出）ともT47で消化済みと確認したうえで、統合レビュー第2回（2026-08-17）が提示した新閾値案「MapView.tsx 1,800行 or STATIC_OVERLAY_LAYERS 10種到達」を正式採用。`docs/complexity-review-2026-08-16.md`（R-6・Keep List・設計原則9）と`.claude/commands/review/context.md`のKEEP記載を更新。コード変更は無し。現在値（MapView.tsx 1,634行・STATIC_OVERLAY_LAYERS 6種）はいずれも未到達 |
| 2026-08-17 | T97 | T96でフロントから交差点密度レイヤーの可視化を撤去した後も残っていたバックエンド配信（poi-tilesのintersectionレイヤー）を削除。`_POI_TILE_MVT_SQL`をstop_poi単独のクエリへ簡素化し、`vector_tile.py`・`export_openapi.py`・`region_service.py`・`region.py`のintersection関連記述を整理。ルーティング材料（`get_intersection_counts`・`INTERSECTION_DEGREE_THRESHOLD`）は無変更。`POI_TILE_VERSION`をv1→v2（backend/frontend対で更新）。intersectionレイヤーのDB統合テストを削除、`regionApi.test.ts`を追従。backend 734件・frontend 265件・tsc・eslint全green |
| 2026-08-17 | T56 | headed Chromium（自前Playwrightスクリプト、Claude Browserペインではない）でデスクトップ・モバイル幅×距離違いで計8回ルート生成し、候補到着直後1.5秒間を150ms間隔で連続撮影（計88枚）して再現性を確認。全ラウンドでタイルの一過性崩れ・コンソールエラーとも観測されず、2026-08-16のheadless環境限定の症状だった可能性が高いと判断しクローズ |
| 2026-08-17 | T108 | T107（基盤フェーズ）で用意したレシピ上書き機構を実際に触れるUIパネルとして実装。`staticAttributeLayers.ts`の凡例・色分け式をレシピ引数の関数へ変更（既存定数は無破壊）、`MapView.tsx`へ`trafficStressRecipe` propsとライブ更新（`setPaintProperty`・凡例フィルタの動的差し替え）を配線、`TrafficStressRecipePanel`新規（highway別基準値13種＋補正12項目、`WeightPanel`とは独立トグル）、`page.tsx`にstateを追加し地図・内訳ポップアップ・次回生成リクエスト・dirty判定へ配線。`MapLayersPanel`/`MapOverlayControls`は`LegendEntry.filter`を参照しないため無改修で済んだ。frontend 275件・tsc・eslint全green |
| 2026-08-17 | T109 | ユーザー報告（デバッグログ・システム状況サマリで`weather:open-meteo`が5件中5件`http_429`失敗、`/api/weather`が502）。T98の初版対策（`MAX_RETRIES=2`・固定0.3秒刻み）をすり抜けての再発と判明し、ユーザー選択（再試行強化）を受け対応。`MAX_RETRIES`を2→4、バックオフを固定刻みから指数（基数0.5秒・上限2.0秒でクランプ、Retry-Afterヘッダにも同じ上限適用）へ変更、新規`RETRY_BUDGET_SECONDS=8.0`（待機合計の壁時計予算、フロントfetchタイムアウト15秒に対して余裕を残す）を429・TransportErrorの両再試行経路で共有。既存テストの実待機を無くすため`asyncio.sleep`のno-op置換フィクスチャを追加、予算切れ早期打ち切りの新規テストを追加。backend 735件全green。根本原因（Render共有IPに対するOpen-Meteo側レート制限）自体はクライアント再試行では解消不可のため、有料/専用キー化はユーザーへ選択肢提示のみでスコープ外 |
| 2026-08-17 | T110 | ユーザー報告（重み付け画面にスマホで辿り着けない）を受け調査。研究モードのON/OFFトグルが「設定」タブ、効果である`WeightPanel`/`TrafficStressRecipePanel`が「ルートを作る」タブと別タブに分かれていたのが原因と判明。ユーザー指摘（生成時・地図表示時どちらでも使うパラメータなので親子関係ではない）を踏まえ、「設定」（運用/デバッグツール）とは混ぜず、A/Bどちらの子でもない独立した4つ目のブロック/タブ「研究」を新設しトグルとパネルを同居。`ComparisonPanel`（結果一覧）は性質が異なるため「ルートを作る」に残した。追加依頼（メニュー名を実態に合わせる）を受け、研究モードトグル分離後は純粋な開発者/運用ツール集になった「設定」を「開発者」へ改名（表示名・内部識別子とも一貫、ユーザー選択のうえ決定）。frontend 275件・tsc・eslint全green、Playwright実機確認（モバイル4タブ収まり・開発者タブから研究トグル消失・研究タブ内でのOFF→ON即時パネル表示、デスクトップ含め）でコンソールエラー0件を確認 |
| 2026-08-17 | T111 | T110のフォローアップ。(1) モバイル下部タブ「開発者」が文字だけの4rem幅ボタンで折り返され読みにくいとの報告を受け、地図上のiconChipと同じ「アイコン+1行ラベル」構成へ4タブとも統一（新規アイコン3種`MapAppearanceIcon`/`ResearchIcon`/`DeveloperIcon`追加、`RouteIcon`は既存を流用）。(2) 交通ストレスレシピ調整パネルの要素名を「日本語の論理をラベルに、具体的な属性説明は情報アイコンで」という方針へ転換。highway別基準値13項目・スカラー12項目すべてに日本語ラベル＋`description`（情報アイコンのツールチップ、OSMタグ・値を明記）を追加し、T108時点の「タグ語彙をそのまま出す」判断を撤回。新規`InfoIcon`追加、`WeightPanel`（既に自然な日本語ラベル）は対象外。副次的にcomposes化フィックス時の消し忘れ（重複`.resetButton`定義）を発見・削除。frontend 275件・tsc・eslint全green、Playwright実機確認（4タブとも1行ラベルで375px幅に収まる・`highway=primary`/`primary_link`の情報アイコンが前方一致の罠なく区別される）でコンソールエラー0件を確認 |
| 2026-08-17 | T112 | ユーザー報告「infoアイコンを押しても説明が出ない」。T111の情報アイコンがtitle属性（ホバー依存）実装だったためスマホのタップでは一切開かない設計ミスと判明（デスクトップのマウスホバーでしか検証していなかった）。クリック/タップで確実に開閉するボタン（`aria-expanded`、`MapOverlayControls`の凡例展開トグルと同じ規約）へ作り直し、highway別基準値テーブルは行ごとの専用`HighwayRow`コンポーネントへ切り出して開閉状態を持たせた。frontend 276件（新規1件）・tsc・eslint全green、iPhone 13デバイスエミュレーション＋`tap()`で実機タップを再現しユーザー報告の再現→解消を確認、コンソールエラー0件 |
| 2026-08-17 | T113 | ユーザー依頼「基準値は低→高で1-4をプログレスバーで選択（将来5・6にも拡張可能に）、補正値は0中心に変動、変動条件はその横に個別設定」。基準値をレベルピッカー（`StressLevelPicker`、地図と色・段階数を共有するため`staticAttributeLayers.ts`の`TRAFFIC_STRESS_COLORS`を新規export）、補正値を0中心バー（`AdjustmentBar`）へ変更。maxspeed/lanesの閾値+補正値は`ThresholdAdjustmentField`/`ThresholdAdjustmentRow`で1行にまとめ、条件を補正値の横で個別編集できるようにした。バーの表示スケールは実機確認で±4だとほぼ見えないと判明し±2へ調整。frontend 277件（新規1件）・tsc・eslint全green、Playwright実機確認（375px幅で横スクロール無し・レベルピッカー/対フィールドの動作・スクリーンショットでの視認性）でコンソールエラー0件 |
| 2026-08-17 | T114 | ユーザー報告「補正値、水平バーが出ておらず数字入力。入力しにくいので改善して。全体的にもう少しコンパクトな形にしたい」。T113の0中心バーは実機ではmin-widthの塗りが数px程度で知覚されず、数値入力単体もネイティブのスピナー矢印が小さくタップしづらい問題が残っていたと判明。`AdjustmentBar`を廃止し、-/+ボタンで挟んだ色付き数値入力（`AdjustmentStepper`、背景色は`TRAFFIC_STRESS_COLORS`から算出）へ作り直した。あわせて閾値+補正値の対フィールドを縦2段から横並び1行へ、レベルピッカーのボタンサイズ・グループ間gapを詰めてコンパクト化。実装中にラベルが右側の内容に押し縮められて「低速道路」が2行に割れる回帰を発見・修正（`flex-shrink: 0`/`white-space: nowrap`）。frontend 278件（新規1件）・tsc・eslint全green、Playwright実機確認（-ボタンでの実際の値変化・375px幅で横スクロール無し・ラベル折り返し崩れの解消）でコンソールエラー0件 |
| 2026-08-17 | T115 | ユーザー依頼「地図の見え方の中身と同じように、研究の中身も折りたたむように。表示しているときのみ折りたたみ解除まで合わせるべきか、どこまで合わせるかは考えて」。`MapLayersPanel.tsx`の折りたたみ（T38）を精査し、開閉状態はレイヤーの表示ON/OFFと完全に独立した純粋なUI状態と判明。「研究」側も同じ考え方で、`WeightPanel.tsx`（2グループ）・`TrafficStressRecipePanel.tsx`（5グループ）の`<fieldset><legend>`をすべて`<details><summary>`（chevron付き、デフォルト全閉）へ変更し、開閉は上書きトグルのON/OFFとは連動させなかった（合わせたのは折りたたみの仕組みまでで、開閉のトリガー条件までは合わせていない、という判断を明記）。CSSは`WeightPanel.module.css`へ新規追加しTrafficStressRecipePanel側はcomposesで再利用。frontend 278件・tsc・eslint全green、Playwright実機確認（両パネルとも初期非表示・クリックで開閉）でコンソールエラー0件 |
| 2026-08-17 | T116 | ユーザー依頼「評価の重みと交通ストレスのレシピは扱いを分けてほしい。別タブは微妙だが同じタブ内でグループ化はしたい。レシピは今後他の二次データ分も増えると思うのでくくり出してほしい」。別タブ化はせず、「研究」タブ内を「評価の重み」「レシピ[一次情報→二次情報の変換式]」の2カテゴリへ見出しで分割（見た目は`MapLayersPanel.tsx`のカテゴリ見出しとcomposesで統一）。「レシピ」カテゴリは現状交通ストレスレシピ1つのみだが、将来の追加パネルはこのカテゴリの`<div>`内に足すだけで済む構成にした（1件しかない現時点で汎用レジストリ機構まで作るのは過剰と判断し見送り）。frontend 278件・tsc・eslint全green、Playwright実機確認（2見出しの表示・順序・375px幅での横スクロール無し）でコンソールエラー0件 |
| 2026-08-17 | T117 | ユーザー相談「交通ストレスは変動要素が多く1-4は粗い、妥当な段階数を検討・提案して」を受け、実装前にdev DB実データ（39,878way・5,737.6km）でクランプ前の生値分布を実測。raw≥5が8.3%（件数）/9.3%（距離）存在しprimary/trunk/指定路線に集中（従来level4に丸め込まれ区別不能）、下端level2（62%/56%）はタグ欠損由来の一極集中で細分化の材料無しと判明。上限4→5拡張（下限1据え置き）を実測で裏付けたうえで実装。`domain/traffic.py`のクランプ・`domain/difficulty.py`の正規化上限・`trafficStressExpression.ts`のMapLibre expressionを同期、`staticAttributeLayers.ts`へ5色目（新規オレンジ#f97316をlevel4、旧赤#dc2626をlevel5へ引き継ぎ）を追加。`TrafficStressRecipePanel`はT108で段階数可変設計済みのため無改修で追従。作業中、同一ディレクトリで別セッションの「安全度」9軸目実装（未コミット・pytest収集エラー17件で非green）と衝突するリスクを検知し、ユーザー承認のうえgit worktree（`traffic-stress-5levels`ブランチ）で完全分離して実装。backend 736件・frontend 279件・tsc・eslint全green、Playwright実機確認（5段階の色・ラベル・panelHint文言）でコンソールエラー0件 |
| 2026-08-17 | T118 | ユーザーが本番モバイル実機スクショを提示（T117で5段階化した基準値ピッカーが画面右端から溢れる）。原因は標準table auto-layoutの列幅共有（1行でも長いラベルがあると全行のピッカー列が圧迫される）と判明し、ラベルの折り返し許可＋`table-layout: fixed`＋ピッカー列への固定幅（7.5rem）で解消。副次的に、原因不明のCSSカスケード上書き（クラスセレクタがグローバルbutton既定に上書きされ続ける現象、根本原因は未特定）を`!important`の対症療法で解決。作業中、検証用ポート（8000/3010）が別セッションのプロセスに奪われ誤ったビルドを検証してしまっていたことが判明し、ポートも8001/3011へ分離。backend 736件・frontend 279件・tsc・eslint全green、Playwright実機確認（モバイル390px幅、standaloneサーバー、最短/最長ラベル行とも1行5ボタンで横スクロール無し）で確認 |
| 2026-08-17 | T119 | ユーザー相談「交通ストレスとは別軸で安全度も作れないか（道路種類・灯り・事故密度等を組み合わせて）」を受け設計・実装。交通ストレスレシピ（T107〜T116）と同じ構造で`domain/safety.py: SafetyRecipe`（highway別基準値＋cycleway/maxspeed/lanes/路肩/街灯/トンネル/指定路線の補正、lanes_lowは不採用）を新設し9軸目として`route_preference.yaml`・両エンジン・API（`/api/routes/generate`・`POST /api/region/safety-breakdown`）へ配線。MVTタイルへ`shoulder`/`lit`材料タグ追加でv9→v10（後方互換のプロパティ追加のみ）。ユーザー選択に基づき事故密度は新レシピへ組み込まず既存`accident_weight`軸のまま`bicycle_only`既定値をFalse→True・死亡事故を`ACCIDENT_FATAL_WEIGHT`(3.0)件分と積算するSUMへ変更（既定挙動として反映、実装時にLEFT JOIN不一致行の誤カウントを自己発見・修正）。フロントは`safetyExpression.ts`（trafficStressExpression.tsのミラー）・`SafetyRecipePanel.tsx`を新規実装し、T113で交通ストレス専用だった基準値ピッカー・補正ステッパー等を`recipeControls.tsx`へ汎用化して両パネルで共有。T117/T118（同日、交通ストレス5段階化＋モバイル幅溢れ修正）と2度のT番号衝突・マージ（`docs/improvement-plan.md`・`architecture.md`・`frontend/src/types/generated/openapi.json`・`TrafficStressRecipePanel.module.css`/`.tsx`）が発生し手動解消、T118のモバイル幅修正は同一構造を持つ`SafetyRecipePanel`へも横展開した。backend 781件・frontend 335件・tsc・eslint全green、DB統合テストはdev機ネイティブPostgreSQLで確認済み |
| 2026-08-18 | T120 | T119完了後のコードレビューで、`get_traffic_stress_breakdown`のDB例外集計修正（`result`/`warned`パターン）が双子メソッド`get_safety_breakdown`へは反映されていなかったバグを検出・修正。両メソッドとも`error_type`未設定だった問題（error_types集計が常に"unknown"）も併せて修正し、`docs/logging.md`へ`warned`フラグの使い方を追記。backend 786件全green |
| 2026-08-18 | T121-a | ユーザー相談「安全度と交通ストレスの独立性、軸の数の妥当性を検証、似ている部分はまとめて切り出すのはありか検討・提案して」を受けdev DB実測（39,878way）を実施。相関0.91（ほぼ冗長）・shoulder_adjustment実測0.0%（死に補正）・安全度4段階の上限丸め損失9.5%距離（T117の交通ストレス5段階化根拠と同水準）と判明。調査の過程で`TrafficStressRecipeOverride`にだけ閾値順序検証（前回コードレビュー指摘）があり双子モデル`SafetyRecipeOverride`には無い非対称（T120と同種の「片方だけ直し忘れる」再発）を発見し即修正。軸統合は見送り（相関は現行base値がコピペに近いことの結果であり概念の同一性の証拠ではないため、事故密度較正（T121）を先に試す）、代わりに`domain/recipe.py`共通化・安全度5段階化・shoulder撤去をT122として起票、事故密度較正をT121として起票。backend 787件全green |
| 2026-08-18 | T121 | ユーザー指示「T121着手して」を受け実施。`_ACCIDENT_COUNTS_SQL`と同じ空間マッチ（30m・involves_bicycle・死亡事故重み付け）でhighway階級別事故密度を実測し、`SAFETY_BASE_BY_HIGHWAY`のtertiary/tertiary_linkが同居先（residential/unclassified）より明確に高密度（3.6〜3.7 vs 1.9〜2.8）と判明。T92と同じ手法でlanes/maxspeed分布も追加検証しsecondaryに近い構造（lanes付与50%・うち81%が2車線）と確認、2→3へ較正（domain/safety.py・safety_recipe.yaml・生成物・テスト13箇所を同期）。cycleway/living_streetの密度がresidentialよりやや高い点は自転車専用インフラの曝露バイアス（正規化していない生密度は自転車量が多い場所ほど見かけ上高くなる）と判断し据え置き。**較正後の相関を再測定したところ0.91→0.96へ上昇**（tertiary系がsecondary系と同じbase=3に揃ったことでTS=3群の安全度分布が58.5%/38.5%の分裂から96.0%集中へ収束したため）。実データに基づく較正が却って2軸を接近させたという想定外の結果を得て、現状の材料タグ構成（shoulder実測0%・dev DBのlit未取込）では2軸の差別化がlit/shoulder/tunnelというごく薄い補正に依存している実態がより明確になったと結論。T122（dev DB再取込等）の優先度がこの結果で上がったと判断し記録。backend 787件・frontend 335件・tsc・eslint全green |
| 2026-08-18 | T121（続き） | ユーザー指示「lit有効化後に相関再測定してから確かに判断したい」を受け、dev DB（東京都心南部）を`Tokyo.osm.pbf`から現ロード範囲（ST_Extent実測bbox）で再取込（UPSERT冪等）。way数39,878→57,112（差分17,234件はT99のshared_pedestrian_waysルール分17,584件とほぼ一致、想定内）、`lit`タグが0件→6,681件（11.7%）へ有効化。相関を再測定すると0.9559→**0.9222**（距離加重0.9613→0.9288）へ低下し、lit補正の差別化効果を確認。副次的に安全度4段階の上限丸め損失も8.5%/9.5%→**4.3%/5.0%**へ半減しており、T122で予定していた5段階化の根拠（T117の8.3%/9.3%と同水準、という当初の判断）が崩れたため、T122から5段階化を切り離し「要再判断」として記録し直した |
| 2026-08-18 | T122〜T124再構成（起票） | 複雑度平衡性レビュー（history/2026-08-18_complexity.md F-1/F-2「レシピ付き軸が共有基盤なしの全層コピー、追加コスト64ファイル・双子鏡像1,500行/軸・同期バグ2件実発生」）とユーザー相談「将来拡張を踏まえた軸パラメータの汎用化・相関検討・新要素注入・重み変更の容易化」を受け、旧T122を3層構成へ再起票。T122=判定プリミティブ共有（domain/recipe.py新設＋flag_adjustment＋検証集約＋shoulder撤去）、T123=糊のパラメータ化（region_service/_get_breakdown・router・regionApi・内訳ポップアップ共通ビルダー抽出・useLayerDataStatus抽出＝MapView閾値発火F-1対応を兼ねる）、T124=軸統計計測スクリプト常設化（measure_axis_stats.py、使い捨てで3回書いた相関・クランプ損失・事故密度分析の1コマンド化）。AxisRegistry的フレームワーク化は2軸ではprematureとして不採用、重み変更は既にYAML1箇所（変更コスト表B行）のため対象外、3つ目のレシピ軸はT122・T123完了まで凍結。5段階化はT122内で「要再判断」のまま保持 |
| 2026-08-18 | T124 | `backend/scripts/measure_axis_stats.py`を新設。相関（Pearson/Spearman、距離加重込み）・クランプ前生値分布（丸め損失%）・材料タグの補正発火率・highway階級別事故密度をdev DBから1コマンドで出力する。相関・丸め損失・発火率の集計は`TrafficStressBreakdown`/`SafetyBreakdown`の`*_adjustment`/`*_override`フィールドを`model_fields`から動的に拾う実装にし、将来の補正フィールド増減に追従できるようにした（カタログ化）。事故密度は`_ACCIDENT_COUNTS_SQL`と同じ`&&`前置＋`ST_DWithin(geography)`パターンをhighway単位集計に変えたSQLで計算し、正規化自体は既存の`distance_weighted_accident_density`を再利用。`infrastructure/database.py: get_engine()`のWebリクエスト用`command_timeout=20秒`が全way集計クエリでは不足し`TimeoutError`になったため、`app/batch/*.py`と同じくタイムアウト無しの専用エンジンをスクリプト側で生成する方式に変更。dev DB実行でPearson 0.9222（距離加重0.9288）・Spearman 0.9145（距離加重0.9255）・安全度丸め損失4.3%件数/5.0%距離・shoulder_adjustment発火率0.0%と、T121の実測値と完全一致することを確認した。`docs/architecture.md`へ`backend/scripts/`の一覧（従来未記載だった既存スクリプトも含む）を追記。backend 810件（新規23件）全green |
| 2026-08-18 | T124再検証 | 「`test_measure_axis_stats.py`の4件が`KeyError: 'shoulder_adjustment'`で失敗する」という報告を受け別worktree（`claude/mystifying-pascal-dc1cc1`、HEAD=T124と同一コミット10d71c3）で再検証。`SafetyBreakdown`（domain/safety.py）には`shoulder_adjustment`フィールドが実在し、当該4件を含む`test_measure_axis_stats.py`23件・backend全810件とも再現なくgreen。重複ファイル・stale `.pyc`も無し。ブランチはmasterと差分ゼロで修正対象コード自体が存在しなかったため、コード変更は行わずT124完了記録（backend 810件全green）が引き続き正しいことのみ確認・記録した |
| 2026-08-18 | T122 | `backend/app/domain/recipe.py`を新設し、`clamp_level`・`threshold_adjustment`・`cycleway_adjustment`・`flag_adjustment`・`tag_value_is`・`validate_threshold_order`の共有プリミティブへtraffic.py/safety.pyを統一。`parse_lanes`/`parse_maxspeed`/`cycleway_class`等の材料タグ正規化もtraffic.pyから移設（safety.pyの間接import経由の旧構成を解消）。`threshold_adjustment`はlow/high閾値のどちらを先に判定しても`low<high`前提下では結果が同じであることを利用し、旧traffic.py（lanesはhigh優先）・旧safety.py（maxspeedはlow優先）の実装差異を1関数へ統合した。`routes.py`の`_check_threshold_order`を`validate_threshold_order`呼び出しへ1本化（T121-aの再発防止）。shoulder_adjustment（T102実測0.0%の死に補正）を`SafetyRecipe`/`SafetyBreakdown`/`SafetyRecipeOverride`/YAML/MVT SQL/`safetyExpression.ts`/`SafetyRecipePanel.tsx`から撤去し、MVTタイル世代をv10→v11へ更新。backend 839件（新規21件）・frontend 334件・eslint全green（フルスイート実行時のSafetyRecipePanel/TrafficStressRecipePanel情報アイコンテスト5件タイムアウトは分離実行で16/16green、環境リソース競合によるflakeと判断） |
| 2026-08-18 | T123 | レシピ軸の糊のパラメータ化＋MapView閾値発火対応。`region_service.py`の内訳取得双子を`_get_breakdown`（`_get_tile`と同じ方針）へ、`region.py`の2エンドポイントを`_breakdown_response`へ統一。`regionApi.ts`のfetch双子を`BreakdownAxisConfig`渡しの1関数へ統一。新設`recipeBreakdownPopup.ts`でMapView.tsxの内訳ポップアップ双子（148行）を`adjustmentLabels`（Breakdownのフィールド名→ラベル、記述順=表示順）渡しの1実装へ集約（新しい補正フィールドが増えても本体変更不要）。新設`recipeExpression.ts`で`trafficStressExpression.ts`/`safetyExpression.ts`のMapLibre expression断片組み立て（`domain/recipe.py`のTS側ミラー）を共有化。新設`useLayerDataStatus.ts`で`computeLayerDataStatus`/`clearStaleTrackedSourceErrors`と状態管理・イベントハンドラを抽出（MapView.tsxとの循環import回避のため`LAYER_DATA_SOURCES`はMapView.tsx側に残し引数で渡す設計）。MapView.tsx 1,905→1,654行（目標1,700行未満達成）。新閾値（2,000行 or STATIC_OVERLAY_LAYERS 10種 or 3つ目のレシピ軸のMapView内ミラー追加）をdocs/complexity-review-2026-08-16.mdへ反映、3つ目のレシピ軸の追加凍結を解除。backend 839件・frontend 334件・eslint・tsc全green、Playwright実機確認（headless chromium、東京都心南部の実データ）で交通ストレス・安全度の両内訳ポップアップが最終値まで正しく表示されコンソールエラー0件を確認 |
| 2026-08-18 | T125 | `frontend/vitest.config.mts`へ`testTimeout: 15000`を追加。vitest既定の5000msがnode_modules未インストール直後等のコールドスタート（Vite変換・jsdom環境セットアップ、実測初回6.4秒）と競合しSafetyRecipePanel/TrafficStressRecipePanel等のテストがタイムアウトで落ちる偽陽性（T121〜T123で繰り返し観測）を解消。作業ディレクトリが並行セッションと共有されておりnode_modules削除は他セッションを巻き込むリスクがあるため、完了条件の検証は`node_modules/.vite`（Vite変換キャッシュ）削除によるコールド状態再現に代えて実施し、334件全green（タイムアウト失敗0件）を確認。副次的に、同ファイルの`environmentMatchGlobs`（別コミットbe9fc95由来）がインストール済みvitest 4.1.10に存在しない設定でCIのtsc gateを壊している疑いを発見、T125のスコープ外のため別タスクとして切り出した |
| 2026-08-18 | T126 | `vitest.config.mts`の`environmentMatchGlobs`（Vitest 1〜3系のオプション、インストール済み4.1.10では廃止済み）を修正。`npx tsc --noEmit`のInlineConfig型エラーの原因であり、`typeof window`プローブで確認したところランタイムでも無視されておりnode環境への振り分けが機能していなかった。Vitest 4の`test.projects`はファイル探索単位が変わり対象外テストが静かに漏れるリスクがあるため不採用とし、対象15ファイルへ`// @vitest-environment node`docblockを個別付与する方式へ置き換えた。付与作業中に`MapView.overlayFilters.test.ts`が実際は`window.location`参照コード経路（`accidentTileUrl`）を持ちjsdomが必要（旧設定は誤ってnode指定していたが機能しておらず表面化していなかった）と判明し、このファイルのみdocblockを付けず解消。`npx tsc --noEmit`エラー0件・`npx vitest run`334件全green・eslint全green |
| 2026-08-18 | T53 | `backend/scripts/collect_jartic.py`（JARTIC WFS収集）・`analyze_jartic_calibration.py`（LTS段階×実交通量の突き合わせ）を新設。収集側は実装中に2つの実測起点の落とし穴を解消（`時間帯`ではなく自己完結な`時間コード`からの日時parseへ変更／このGeoServerデプロイが`count`/`startIndex`ページングを完全無視すると確認し時間コード完全一致・1時間1リクエストのループ方式へ設計変更）。分析側もLATERAL内KNNを`geography`キャストすると`osm_raw_ways.geom`のGiST索引を使えず全表スキャン化することを実測で発見し、KNNは`geometry`のまま・距離判定のみ`ST_DWithin(geography)`にして解消。2026-08-14〜17の4日分・関東本土全域を実DBへ収集（106観測点）したが、dev DBの`osm_raw_ways`が東京都心南部のみのカバレッジ（実測extent: lon 139.61-139.87, lat 35.58-35.79）のため30m以内にマッチする観測点はn=8（level4/5のみ）にとどまった。この範囲内ではlevel昇順に平均交通量が単調非減少（20,787→24,897台/日、Pearson 0.224・Spearman 0.378）で`TRAFFIC_STRESS_BASE_BY_HIGHWAY`の想定と矛盾しないが、n=8・2段階のみのため統計的な結論には不十分と判断し、基準値は変更せず分析結果の記録のみで完了とした（より広い較正には本番相当のosm_raw_ways投入が必要、現状スコープ外）。backend 847件（新規16件）全green |
| 2026-08-18 | T53（本番相当スケールで再検証） | ユーザー指示「本番DBには関東全域なOSMデータがある認識で、確認・最新化した上で較正検証できるか」を受け実施。読み取り専用で本番Oracle DBを事前確認: `osm_raw_ways` 1,329,632件（関東本土bbox内99.8%、外れ値0.02%）、migration 0001-0009ラグ無し、133万way規模でもLATERAL最近傍マッチは索引利用9.3ms（`EXPLAIN ANALYZE`実測）、全行`updated_at`が2026-08-16で統一済みのため追加のPBF再取込（最新化）は不要と判断。`analyze_jartic_calibration.py`へ`collect_jartic.py`と同じ`--database-url`引数を追加し、同じ4日分を本番へ再収集・再分析（ユーザー確認済みの方針どおり分析後に`DROP TABLE`で本番から削除）。マッチ観測点n=8→**68**に拡大しlevel3-5を横断、単調性は維持（16,652→23,573→29,762台/日、YES）したが相関はn=8時点より弱まった（Pearson 0.179・Spearman 0.164）。原因はJARTIC road_type=3観測点が幹線道路設置に偏る選択バイアス（68件中60件=88%がlevel5に集中、level5内の分散が最小6,773〜最大64,146台/日と大きい）と分析。方向性は矛盾しないため既定値は変更せず、より大きな標本でも同じ結論（記録のみで完了）を確認した。backend 847件（変更なし）全green |
| 2026-08-18 | T53（LV6要否の判断・DEFAULT_BBOXカバレッジ確認） | ユーザー相談「高レベル帯の差別化に使えるか」「LV6細分化のメリットを考察して」「DEFAULT_BBOXは狭くなっているなら優先度を上げたい」を受け深掘り。指定路線(is_designated)の実測交通量差+78%（30,097 vs 16,902台/日、n=62/6）で既存`designation_adjustment=+1`の方向性を裏付け。クランプ前raw値の方が交通量とよく揃う（Pearson 0.179→0.309）ことを確認したが、level5内の42%が天井超過というJARTIC側の数字は幹線道路設置バイアスの影響と判明。`measure_axis_stats.py`へ`--database-url`引数を追加し母集団側のraw>5割合を測定した結果、dev機1.0%/1.1%・本番131万way規模でも0.9%/1.2%とほぼ一致し、T117の拡張根拠（8.3%/9.3%）の1/8程度に収束済みと確認。**LV6細分化は見送り**（母集団側の実測が根拠、JARTICの42%は「既知の少数派道路には天井超えの実差がある」という補足証拠へ位置づけ変更）。`DEFAULT_BBOX`は本番`osm_raw_ways`のbbox外データ（3,957件）を方角別に確認したところ全て南方向（離島、元々除外対象）で北・東（関東本土側）への欠落は0件と確認、西の山梨県混入（無害）のみのため修正は優先度低として見送り。backend 847件（`measure_axis_stats.py`への`--database-url`追加は既存テスト23件に影響なし）全green |
| 2026-08-18 | T101 | ユーザー懸念「実店舗とどれだけ合っているか」を受け、着手前に`backend/scripts/measure_poi_freshness.py`（新設）でOSM側の最終編集日時を関東全域で実測。コンビニは直近2年以内の編集が62.4%と新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高いと判明したため、5種すべて取込みつつ表示側で鮮度差を伝える方針で実装（ユーザー承認）。`domain/traffic.py: classify_supply_poi`新設、`osm_node_to_poi_spec`は`classify_stop_poi or classify_supply_poi`で1回のnode走査に統合。`_POI_TILE_MVT_SQL`はkindを無条件で焼き込む設計のためSQL無改修で済んだ一方、1つのMVTレイヤー（`stop_poi`）に2種類のkindが混在するため独立2レイヤー化には`legendFilter.ts: buildCombinedLegendFilterExpression`へ`baseFilter`（非表示操作の有無に関わらず常にANDする恒常的な絞り込み）を新設して対応（無いと凡例が「何も隠していない」瞬間に相手方のkindが一時的に見えてしまう不具合になるところだった、実装中に発見・設計で解消）。`mapLayers.ts`は`trafficSafety`へ含めず新設`amenity`（補給・施設）カテゴリへ分離。dev DB再取込でvending_machine 7,434件等を確認。退避ポート（8001/3011）でPlaywright実機確認（チップON切替・`poi-tiles?v=3`の200・地図クリックで「補給・休憩: 給水」の正しいポップアップ）。backend 873件（新規26件）・frontend 348件（新規22件）・tsc・eslint全green |
| 2026-08-18 | T101（本番バックフィル漏れ・チップ幅修正） | ユーザー報告「補給・休憩を押してもデータがプロットされない」「アイコンが他横幅と揃っていない」を受け対応。前者はdev機のみに`import_pbf.py`を再実行しデータバックフィルしており本番Oracle DBへの反映を失念していたのが原因（コードはmasterへpush済みで動作はするが`osm_raw_pois`に新kindが1件も無く空振り）。ユーザー確認のうえ`import_pbf.py --database-url <本番>`で`kanto-latest.osm.pbf`を再実行（全way・nodeも巻き込むUPSERT、実測1,421.5秒=約23.7分）、本番`osm_raw_pois`で`vending_machine`17,349件・`convenience`14,182件・`toilets`7,310件・`drinking_water`4,710件・`bicycle_parking`2,742件を確認（dev機実測とほぼ一致）。後者は`chipLabel`「補給・休憩」（読点込み5文字）が他レイヤー（4文字以内）よりチップ幅を広げていたため「補給休憩」（4文字）へ短縮（`label`「補給・休憩ポイント」は変更なし） |
| 2026-08-18 | T127（起票・調査のみ） | ユーザー相談「日本全国のデータ取込をするならどれだけの容量、時間がかかるか、現実的か検証してほしい」を受け調査（実施はせず）。Geofabrikで実測: 関東466MB・全国2,358MB（8地域合計）で倍率約5.06倍。ストレージは本番現況2,050MBから単純比例で全国約10GB、契約150GBに対し約7%で問題なし。所要時間はT101本番バックフィル（同日実施）のchunk単位ログを精査し、**way数94万件超から処理速度が非線形に悪化し続け頭打ちの兆候が無い**（序盤0.28ms/way→終盤1.97ms/way、最悪chunk単体で7.44ms/way）という2026-08-15記録済み・未解決の既知事象を確認。全国規模（約665万way）へ外挿すると楽観3.2時間〜現実的には半日以上という幅の大きい見積もりにしかならず、133万way超を一度も実行したことが無いための不確実性と結論。ローカル開発機のCドライブ空きが16GBのみという制約も確認。段階的検証（中間規模での実投入による減速カーブ実測）を推奨し、全国投入は意思決定待ちとして記録のみで完了 |
| 2026-08-18 | T128（起票・設計のみ） | ユーザー相談「地図上でアイコンが多くなってきている。グルーピングか表示非表示切替を検討したい。地図の見え方のグルーピング、生データ/合成データかは意識して」を受け設計（実装はせず）。現状static9種+dynamic1種=10チップがフラットに並ぶ状態を、サイドバー（MapLayersPanel）で既に使っているcategory（改善計画T86、道路状態/交通・安全/自転車インフラ/地形/補給・施設の5分類）で束ねる案を検討。9レイヤーを生データ/合成データで分類し直すと「複数タグから計算した推定スコア」は車の圧迫感・安全度の2件のみで、混在は交通・安全カテゴリ1つに閉じていると判明。3案（A: 既存category束ね＋交通・安全内をdataNature[raw/composite]で小分類、B: 常時チップ+オーバーフローメニュー、C: サイドバー一本化）を比較しAを推奨、チップ総数9→5（ルート込み6）への削減と生/合成の視覚区別を両立できる設計とした。実装時の想定変更点（`dataNature`フィールド追加・`MapOverlayControls.tsx`のグルーピングロジック・展開UIのモバイル/デスクトップ差）まで記録し、着手はユーザー判断待ちとしてT128（設計のみ）で起票 |
| 2026-08-18 | （評価システム再設計・現状把握＋タスク起票） | ユーザーから区間評価の一次/二次/三次層構造への再設計プロンプトを受け、Explore調査＋主要ファイル直接確認（domain/evaluation.py・recipe.py・traffic.py・safety.py・difficulty.py・route_preference.yaml等）で現状把握を実施。現行9軸（うち車の圧迫感・安全度がT130のN1/N2を意図的に共有）と提案6軸のギャップを一覧化し、2つの衝突点（安全度廃止 vs 本日完了のT130共有化路線／レジストリ制 vs 2026-08-16レビューでの見送り判断）をユーザーに確認。回答: (1)提案どおり安全度廃止・accident/night分割を採用 (2)レジストリ制を導入 (3)improvement-plan.mdへタスク分割してから段階着手。T137〜T148としてタスクを起票（車ストレスへのN1/N2/自転車インフラ統合、安全度廃止、〇次フィルタの範囲明確化、レシピのJSON/DB統合、コスト関数の縮退、表示とコストの同一化、DB永続化、レイヤーパネル・区間インスペクタのレジストリ駆動化、相関行列スクリプト、旧安全度削除）。交差点密度・自転車インフラの6軸表への非帰属、`trunk`除外範囲の差異、`motor_vehicle=no`の位置づけは各タスク内の未決定論点として明記 |
| 2026-08-18 | T137 | `backend/app/domain/registry.py`（`PrimaryAttributeSpec`/`AxisSpec`/`register_primary_attribute`/`register_axis`/`AxisInputConflictError`、shared属性による排他チェック除外込み）・`registry_defaults.py`（`register_defaults()`、既存16一次属性・5二次軸の宣言）を新設。レジストリはまだどこからも呼び出されておらず（配線はT142・T145）、宣言のみの非破壊的な追加。「車ストレス」「安全度」「自転車インフラ」の3軸は現行実装がhighway/cycleway/maxspeed/lanes/指定路線を意図的に共有しているため未登録のまま残し、T138/T139で軸自体を再編したのち登録する方針（`test_registry_defaults.py`が3軸の未登録を回帰確認）。`test_registry.py`（機構の単体テスト、衝突検出・shared属性の除外を検証）を追加。backend pytest 904件green（新規14件含む） |
| 2026-08-18 | （評価システム再設計・設計プロンプト改訂への追従） | ユーザーが設計プロンプトを改訂し提示。差分は「現行9軸からの帰属先（T140対応）」節の新設: bicycle_infraはcar_stress入力へ統合（従来方針どおり）、intersection_densityは単独軸を持たずstop_density軸へ「タグなし交差点」を低い重み（例`unsignaled_intersection: 0.3`）のカテゴリとして吸収、と確定。T137で先行登録していたintersection_density単独軸のレジストリ宣言（`registry_defaults.py`）が新方針と矛盾していたため後方修正（AxisSpec削除・stop_densityのinputsへintersection追加、テスト追従、backend pytest 903件green）。intersection_density吸収の実装自体は新規T149として起票。T138の完了条件へcar_stress↔accident相関確認を追加、T147の完了条件を「6〜8軸」→「6軸」（intersection_density分の軸数減を反映）へ修正。T140（〇次フィルタ）に影響する記述は改訂版に無く、引き続き未解決のまま |
| 2026-08-18 | T138 | ユーザーから「本番未リリースのためT138〜T149は破壊的変更も一時的なら許容する」との明示許可を得て着手。影響範囲調査（backend34ファイル・frontend42ファイルがtraffic_stress/infra関連シンボルに言及）の結果、「自転車インフラの独立軸廃止（機能変更）」と「traffic_stress→car_stressの呼称統一（機械的リネーム、影響大）」を分離し本タスクでは前者のみ実施（後者はT150として新規起票）。`domain/difficulty.py`から`bicycle_infra_difficulty`/`AxisDifficulties.infra`/`evaluate_axis_difficulties`のbicycle_infra・infra_weight引数を削除（9軸→8軸）。`domain/evaluation.py: RoutePreference.infra_weight`廃止・`traffic_weight`0.10→0.20（合算）。両エンジンの`_build_segment_details`・`domain/route.py: RouteSegmentDetail.infra_difficulty`・API`RoutePreferenceWeights.infra_weight`を追従（`bicycle_infra`生値・`bicycle_infra_score`集約統計は表示用一次属性として維持）。OpenAPI再生成→`openapi-typescript`でフロント型再生成→`WeightPanel.tsx`/`evaluationAxes.ts`・影響テスト8件のfixture更新。docs/architecture.md §7を9軸→8軸表記へ更新。backend pytest 900件・frontend vitest 372件・tsc・eslint・`next build`全green（`next build`初回はOneDriveのファイルロックで`EPERM`が発生、`.next`削除で解消。ソースコードとは無関係な環境要因と判断）。実データでの分布急変確認・car_stress↔accident相関確認はT147（相関行列スクリプト）の初回実行時にまとめて行う前提で据え置き |
| 2026-08-18 | T139 | ユーザー指示「t139に進めて」を受け続けて着手。`domain/night.py`（新規、`night_difficulty(tags)`: lit無し+50・tunnel+50・最大100の単純加点式）を新設。`domain/difficulty.py`の`safety_difficulty`関数・`AxisDifficulties.safety`を`night`へ置換、`evaluate_axis_difficulties`のsafety_level_value/safety_weight引数をnight_tags/night_weightへ変更（8軸のままsafety→nightへ入替）。`domain/evaluation.py: RoutePreference.safety_weight`を`night_weight`（既定0.0）へ、`compute_edge_cost`から`safety_level`呼び出し・`safety_recipe`引数を削除（cost計算に不要化）。`EvaluationService`・`dependencies.py`のEvaluationService構築からも`safety_recipe`を削除（両エンジン自体は表示用のsafety生値・safety_score集約に`self._safety_recipe`を引き続き使うため変更なし）。両エンジンの`_build_segment_details`は`way_tags`をそのまま`evaluate_axis_difficulties`へ渡す形に変更、`RouteSegmentDetail.safety_difficulty`→`night_difficulty`（safety生値・safety_scoreは維持）。API`RoutePreferenceWeights.safety_weight`→`night_weight`。OpenAPI再生成→フロント型再生成→`WeightPanel.tsx`/`evaluationAxes.ts`・影響テスト6件のfixture更新。docs/architecture.md §7追従。backend pytest 902件・frontend vitest 372件・tsc・eslint・`next build`全green |
| 2026-08-18 | T140 | ユーザー指示「140を進めて」を受け着手。`trunk`/`trunk_link`除外は挙動を変えず維持する判断（設計プロンプトに言及が無く変更指示も無いため）。`domain/evaluation.py`の`DISALLOWED_HIGHWAY_TYPES`（単一frozenset）を`HARD_FILTER_HIGHWAY_TYPES`（`{"motorway":{...},"trunk":{...}}`の名前付き辞書）＋`DEFAULT_HARD_FILTERS`（`frozenset({"no_bicycle","motorway","trunk"})`）へ再構成し、`is_edge_allowed`に`hard_filters`引数（省略時`DEFAULT_HARD_FILTERS`、T141のレシピJSON化を見据えた設計）を追加。既存呼び出し元は全て省略のため動作は完全に不変。`motor_vehicle=no`は方針どおりハード除外に含めず二次軸側の特例のまま維持。docs/architecture.md 7章に新設「〇次: ハード制約」節（フィルタ一覧表・trunk除外の実務判断・motor_vehicle=noとの区別）を追加、「道路種別の3スコープ」表・`import_profile.yaml`コメントも新シンボル名へ追従。新規テスト6件（trunk除外の回帰確認・hard_filters上書きの新規動作・空集合で全許可）を追加。backend pytest 906件green（is_edge_allowedはHTTP境界に非露出のdomain内部関数のためAPI契約・フロントへの影響なし） |
| 2026-08-18 | T141 | ユーザー指示「141も着手して」を受け着手。T137のレジストリと同じ「宣言のみ・未配線」方針で`backend/app/domain/recipe_definition.py`を新設。`Recipe`（recipe_id/version/hard_filters/axis_params/weights）・`RecipeComponents`（既存の型付きモデル群のNamedTuple）・`recipe_from_components()`/`recipe_to_components()`（双方向変換）・`default_recipe()`を実装。axis_paramsのキーは現行の軸内レシピ名（road_suitability/motor_vehicle_density/traffic_stress/safety）のまま、目標axis_idへの統一はT150後に追従する方針を明記。オーバーライド不可の軸（gradient/surface_q/stop_density/intersection_density/accident/night）はaxis_paramsに含めない。API層・OpenAPI契約・フロントは無変更のため後方互換は自明に満たす（実配線はT142以降）。設計プロンプトのレシピJSON例と同じ生dict形からRecipeを構築し軸内係数・重みを一意に取り出せることをtest_recipe_definition.py（新規7件）で確認。backend pytest 913件green |
| 2026-08-18 | T149 | ユーザー指示「進めて」（T142着手の流れ）を受け、T142より先に本タスクを実施。理由: T142（コスト関数のレジストリ駆動化）に着手する前提としてレジストリ（T137）とドメインコードの整合性を確認したところ、レジストリは既に「stop_densityがintersectionを吸収する」という目標構造を宣言済みなのにドメインコード側は独立軸のままという不整合を発見したため。`domain/difficulty.py: stop_difficulty(stop_count_per_km, intersection_count_per_km=None)`へ改修しタグなし交差点密度を0.3倍の重みで加算（8軸→7軸）。`intersection_difficulty`関数・`AxisDifficulties.intersection`・`RoutePreference.intersection_weight`（stop_weight 0.15→0.20へ合算）・`RouteSegmentDetail.intersection_difficulty`を削除（route集約統計・地図表示は維持）。両エンジン・API・OpenAPI・フロント型・WeightPanel/evaluationAxes.tsを追従。`registry_defaults.py`へ`car_stress`（T138）・`night`（T139）軸も併せて登録し、レジストリが設計プロンプトの目標6軸（car_stress/accident/surface_q/stop_density/gradient/night）と完全一致することを確認。docs/architecture.md §7を7軸表記へ更新。backend pytest 915件・frontend vitest 372件・tsc・eslint・next build全green |
| 2026-08-18 | T142 | T149に続けて着手。`domain/evaluation.py`へ`compute_edge_axis_scores()`（二次: 一次属性→axis_id別スコア辞書）・`compute_cost_from_axis_scores(distance_m, axis_scores, weights)`（三次: 完了条件どおりシグネチャに一次属性名が一切現れない純関数）・`preference_to_axis_weights()`を新設。`compute_edge_cost`はこの2関数を合成する薄いラッパーとして残し既存呼び出し元への影響ゼロ（後方互換）。test_evaluation.pyへ9件追加（シグネチャの機械的検証・分離前後の結果一致を回帰確認）。副産物としてT137で登録していた`surface_q`軸のtransform_fnがルート単位集約関数を誤って指していたバグを発見・修正。レジストリのtransform_fn文字列を実際に動的解決して呼ぶ完全な「レジストリ駆動」は未実施（各軸のtransform_fnシグネチャが大きく異なり汎用ディスパッチには追加設計が要るため、今回のスコープ外として明記）。backend pytest 923件green（API・フロントへの影響なし） |
| 2026-08-18 | T143 | ユーザー指示「143から150一連の続行をお願い」を受け着手。調査の結果、OpenRouteServiceEngineはDijkstra探索を行わず経路探索自体を外部ORS APIへ委譲するためdomain/evaluation.pyのコスト関数を一切使わず、区間表示のevaluate_axis_difficulties呼び出しが元から唯一の計算箇所（重複が無い）と判明。実質的な対応はRoadGraphEngineのみに限定し、`_build_segment_details`をcompute_edge_cost（EvaluationService経由の探索コスト）と同じcompute_edge_axis_scores＋compute_cost_from_axis_scores（T142）へ差し替え。test_road_graph_engine.pyへspy経由の回帰テストを追加し、探索コストと区間表示が同一関数を経由することを実証。OpenRouteServiceEngineは対象外と明記（変更なし）。backend pytest 924件green |
| 2026-08-18 | T147 | T144（本番DBマイグレーションを伴うため後回し）を飛ばし、自己完結するT147へ着手。`elevation_attributes`テーブルが常時空（dev DB実測でCOUNT(*)=0）と判明し、gradient軸だけ他5軸と異なりGSI API都度取得が必要という非対称を発見。統計的に公平な比較のため6軸すべてを同一のランダムサンプル（road_edgesからn=300）で計算する設計とした。`backend/scripts/measure_axis_correlation.py`（新規、RoadGraphRepositoryの既存メソッド群＋ElevationClientを再利用、`--output`でレポートファイル書き出し対応）・`test_measure_axis_correlation.py`（純関数8件）を追加。dev DBに対しn=300で実行し6軸すべてでr値取得（surface_qは分散ほぼ0のため全ペアr=N/A＝正しい判定、他5軸の全15ペアで|r|>0.7の警告0件、car_stress↔accident=0.308でT138の据え置き事項も解消）。backend pytest 932件green |
| 2026-08-19 | T144 | ユーザー指示「効率的な順番に進めて。本番マイグレーションは着手してもよい」を受け着手。設計プロンプトの「保存要否はT145実装時に決定する」というヒントに沿い、0-100の最終difficultyではなく入力となる生カウント（accident_count/stop_count/intersection_count）を事前集計する方針に。migration 0010（edge_attribute_counts）・precompute_edge_attribute_counts.py・verify_edge_attribute_counts.pyを新規実装。実装中に2つの発見: (1) get_intersection_countsは渡されたedge_ids集合内で完結するローカルな次数を返す設計のため、バッチの任意順チャンク分割が次数を過小評価（132/500不一致→全edge一括のグローバル計算に変更し解消）、(2) さらに同一集合でも配列順序が異なると結果が変わる非決定性を発見（ユーザー指摘によりget_accident_counts/get_stop_poi_countsとのインターフェース非対称が根本原因と特定、T151として起票、今回は対応せず）。dev機（122,189件、バッチ45秒、3,000件検証で全件一致）・本番Oracle Cloud（207,767件、検証500件で全件一致）の両方へmigration適用・バッチ実行・検証まで完了。既存の読み取り経路（road_graph_engine.py等）は今回変更なし（テーブル作成・データ投入のみ、配線はT145以降で判断）。backend pytest 935件green |
| 2026-08-19 | T150 | ユーザー指示「150進めて」を受け着手。backend（domain/traffic.py・designation.py・difficulty.pyの主要シンボルは自分で直接改称）→残りbackend約35ファイル・frontend約48ファイルは専用エージェントへ委譲し機械的リネームを実施（合計約90ファイル、ファイル/ディレクトリ名変更2件含む）。API契約変更を挟むため「backend完了→OpenAPI再生成→frontend型再生成→frontend着手」の順序を厳守。対応方針が見込んでいたMVTタイル世代アップは実装調査の結果不要と判明（材料タグのみ焼き込む設計で`traffic_stress`という文字列自体を持たなかったため）。委譲中の実装ミス2件（CRLF混入、PowerShell大文字小文字非区別置換による識別子破損）を自己検出・修正済みで最終成果物には残っていないことを確認。JSON学習用フィクスチャの命名不一致（`traffic-stress-*.json`のまま）は意図的に残置し別タスク送り。最終検証: backend pytest 941件（postgis 6件含む）・frontend vitest 372件・tsc・eslint・`next build`全green、dev DB実データに対する新エンドポイント`/api/region/car-stress-breakdown`疎通確認、Playwright実機確認（研究モード内の評価重みパネル・CarStressRecipePanelが新語彙で正常描画、コンソールエラー・undefined/NaN表示なし）まで完了 |
| 2026-08-19 | T135 | 別セッションがT150（traffic_stress→car_stress呼称統一）を同一作業ツリーで進行中と確認したため、コード変更を伴わないdocs反映のみで完結するT135を選んで実施（T150との衝突回避）。docs/complexity-review-2026-08-16.mdのKeep List「page.tsx / MapView.tsxの現状維持」節へpage.tsx独自閾値〔useState+useStoredState合計40件 or 1,300行、2026-08-18時点実測38件・1,148行で未到達〕をMapView.tsxの既存閾値と並記し追加、設計原則9へも同内容を追記。変更コストシミュレーション表へG'行（レシピ付き評価軸追加、T119実測64ファイル・+3,677/-394行、次回単軸追加時に再検証する参考値と明記）・G''行（軸の共通材料の外出し・再構成、T130実測70ファイル・+3,938/-2,084行）を新設し区別。運用ルール明文化（規模M以上の着手前タスクエントリ作成）はCLAUDE.md改訂要否含めユーザー判断のため見送り、別途確認が必要。コード変更なし |
| 2026-08-19 | T145b | T151に続けて着手。当初「edge_attribute_countsをタイルへ焼き込む」案で実装したが、road_edgesの遅延構築によりタイル内カバレッジ3.6%と判明しユーザー協議で方針変更、way単位事実テーブル（way_attribute_counts＋raw_intersection_nodes、migration 0012）を新設して全域カバレッジ（86,642way・51秒）を確保。実装中に停止密度がT101以降コンビニ・自販機を誤算入するバグを発見・修正（STOP_POI_KINDSフィルタ新設）。レジストリへAxisDisplaySpec拡張→axis-catalog.json書き出し→フロントの汎用レイヤーファクトリ（axisLayers.ts）で、新しいramp軸はレジストリ登録＋タイル焼き込みだけで地図に現れる構造を実現。タイル世代v12。backend 948件・frontend 381件・tsc・eslint全green、Playwright実機確認済み。ユーザー承認を得て本番Oracle Cloudへも同日反映（migration 0011/0012適用＋3バッチ実行、way_attribute_counts 1,329,632件・96.1%が交差点近傍データを保有）。詳細はT145b実装メモ参照 |
| 2026-08-19 | T151 | T150完了・commit後に着手（T150進行中は同一ファイル群に触れるため待機）。当初「PostgreSQLのクエリプラン非決定性の可能性」とされていた原因をコード読解のみで確定: `get_intersection_counts`内部の`_chunked(edge_ids, 50_000)`がリスト位置でチャンク境界を決めるため、入力順序が変わるとチャンク境界がずれ境界をまたぐノードの次数が変わる（T144の「全edge一括」対策も、呼び出し先が内部で再度50,000件分割していたため効いていなかったと判明）。対応方針どおりroad_nodes.degree（DB全体から見た真のグローバル次数）へ一本化。migration 0011・`DerivedGraphRepository.recompute_node_degrees()`（新設、単一UPDATE...FROM、チャンク分割不要）・`app/batch/precompute_road_node_degrees.py`（新設）を実装、`_INTERSECTION_COUNTS_SQL`/`_NEAREST_INTERSECTION_COUNTS_SQL`を`rn.degree`参照へ簡略化、`precompute_edge_attribute_counts.py`の特殊分岐を削除しaccident/stopと同じチャンクループへ統合（結果として高速化、dev機41.7秒）。運用上`precompute_road_node_degrees.py`→`precompute_edge_attribute_counts.py`の順で実行が必要になった（docstring・改善計画双方に明記）。順序非依存の回帰テスト追加、dev機で5,000件規模の順序反転一致（0件不一致）を実機確認。副次的にroad_nodesの22%がorphan（road_edges未参照）と判明したが実害なしのため記録のみで対応せず。backend pytest 942件green。ユーザー承認を得て本番Oracle Cloudへも同日反映（migration適用・degrees/edge_countsバッチ実行完了） |
| 2026-08-19 | T146 | T145bのレジストリ生成物を再利用し区間インスペクタを実装。着手前にユーザーと合成コストの扱いを協議し、勾配軸（標高データ）は単独クリックしたwayでは算出不能なため「取得可能な軸だけで部分合計・勾配軸は欠損と明記」の方針で合意。クライアント側での難易度式再実装（ドリフトリスクあり）は見送り、既存の車ストレス/安全度内訳ボタンと同じ「クリック時にサーバーへ1回問い合わせ」パターンへ統一。`domain/evaluation.py: axis_inspector_breakdown`（car_stress/surface_q/stop_density/accident/nightの5軸をway_attribute_counts＋タグから算出、composite_difficultyと同じ「データ無しは除外・再正規化」で部分合成）・新エンドポイント`POST /api/region/axis-inspector`・フロント`axisInspectorPopup.ts`（axis-catalog.json由来のラベルで表示、道路クリックポップアップへ「一次属性・全軸の内訳を見る」ボタンとして配線）を実装。backend 960件・frontend 384件・tsc・eslint全green、Playwright実機確認（一次属性/5軸スコア/合成コスト58.3〔重み約44%相当・勾配風は欠損明記〕の表示）済み。詳細はT146実装メモ参照 |
