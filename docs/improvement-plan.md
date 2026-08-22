# 改善実行計画（2026-08-15 設計レビュー対応）

[design-review-2026-08-15.md](design-review-2026-08-15.md) の指摘に対する実行計画。
同日の第2回レビュー（[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md)、複雑度平衡の観点）
の対応タスク（T16〜T22）は完了済みのため[docs/improvement-plan-archive/2026-08-15.md](improvement-plan-archive/2026-08-15.md)「第2回レビュー対応」節へ移設済み。
**進捗はこのファイルのチェックボックスを更新して管理する**（完了時に `[x]`＋完了日を追記）。

**このファイルは変更履歴であり、「現在の正」ではない**（過去レビュー基準と同じ扱い）。
評価軸の数・地図レイヤーの一覧・現在有効な設定値のような「動く事実」は、書かれた時点の
スナップショットに過ぎず本文中で何度も更新されている（例: 評価軸は7軸→8軸→9軸→8軸→7軸→
6軸+windと変遷）。現在の値は常に一次情報（`docs/architecture.md`）を参照し、本ファイル内の
古い記述と食い違っていても「矛盾」ではなく「その時点のスナップショット」として扱う。

**完了済みタスクの実施記録は[docs/improvement-plan-archive/](improvement-plan-archive/)へ日付ごとに
退避している**（2026-08-19棚卸し整理）。索引は[improvement-plan-archive/README.md]
(improvement-plan-archive/README.md)（完了タスク一覧つき）。本体にはオープンなタスクを
含む節と「進め方の原則」のみを残す。

## 進め方の原則

- **順序の根拠**: 「検証の自動化（Phase 1）→ 境界の固定（Phase 2）→ 内部の再配置（Phase 2後半）→
  スケール準備（Phase 3）」の順にすると、各修正が前の成果を安全網として使え、後続の修正量が最小になる。
- 1タスク=1コミット（またはPR）。着手前後で全テストgreenを確認する。
- 挙動を変えるタスクはテストを先に追加/更新してから実装する。
- docs（architecture.md等の「現状」記述）はコード変更と同一コミットで更新する。
- **規模M以上でAPI・ドメイン概念・レイヤー種を新設するタスクは、完了条件へarchitecture.md
  追従を既定で含める**（統合レビューでarchitecture.md未追従の同型再発が繰り返し検出された
  ことを受け、統合レビュー2026-08-22 T197でルール化）。
- **backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数を変更したコミットは、
  `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を同一コミットで
  実行し、`git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを
  確認する**（生成物のペア更新漏れがT180・T185で2回発生したことを受け、統合レビュー
  2026-08-22 T196でルール化）。
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
- **2026-08-23追記: トリガーが実質成立した。** T218a（gradientの探索コスト組み込み、
  T12 Stage 0.5）の実装精査で、現行の1点ずつGSI点API呼び出し方式のまま
  gradient（average_grade）を全道路網へ事前計算しようとすると、本番規模で
  数十万〜百万オーダーのAPI呼び出しが必要になることが判明した。これはまさに
  上記で「唯一の正当なトリガー」としていた条件そのものである。T10は
  T218a（トリガー: T10完了）の直接の前提タスクとして扱う。
  詳細は`docs/decisions/t12-routing-scale.md` Stage 0.5参照。

### - [ ] T11. `segments` のAPI境界ビン化〔E4・レビュー指摘M3〕規模M — トリガー: road_graphエンジン常用化

- Edge単位のsegmentsを約500m単位で集約してから返す。フロントの描画コスト・転送量を削減。

### - [x] T12. Road Graph探索のスケール設計ADR〔C3〕規模M（設計のみ）（2026-08-23完了）

- pgRouting / プロセス内グラフキャッシュ / 事前縮約の比較ADRを書き、実装方針を決めてから着手する。
  現状の「リクエスト毎全量ロード」のまま機能を積まないこと。
- 完了記録: `docs/decisions/t12-routing-scale.md` として2部構成で確定（2026-08-23全項目承認）。
  - Part 1（評価ロジックの基本原則）: コスト正準形の凍結＋ペナルティ強度Pの可変化、
    事前計算の境界は「エッジ×型付き1次素材」（2次スコアは保存しない）、軸の可換性の
    設計保証（1次=事実/2次=翻訳ルール/3次=好み）、gradientを探索コストへ追加、
    0次ハードフィルタのしきい値調整可能化、の7原則
  - Part 2（実行基盤の選定）: 案B「プロセス内グラフキャッシュ」を段階移行で採用。
    pgRouting（評価定義がSQLへ二重化し軸可換性と正面衝突）・事前縮約（重み可変と
    非両立、かつボトルネックは探索でなくロード）は不採用。数値目標はキャッシュ温5秒
    以内・冷10秒以内（現状WARM 15.5秒）
  - 実装はT218（Stage 0）・T219（Stage 1）・T220（Stage 2）へ分割起票。着手は
    ユーザーの明示指示待ち
  - **2026-08-23追記（ユーザーの再検証要求を受けた訂正）**: 軸の可換性（原則7）は
    「レジストリ＋変換関数の2箇所だけで完結」という記述が不正確と判明し、
    「backend/frontend合わせ約15箇所への決まったコード変更（1次の再計算は不要）」へ
    訂正。またgradientの事前計算はT10（DEMタイル化）が前提条件と判明し、T218から
    T218a（新設、トリガー: T10完了）へ切り出した。詳細は`docs/decisions/
    t12-routing-scale.md`原則7・Stage 0.5、および下記「残タスクの優先順位」参照

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

---

**[T13〜T33ほか（第2回〜第3回レビュー対応・Oracle移行後対応・静的道路属性P0・
フロントUI一貫性再編・モバイル実機フィードバック対応、いずれも2026-08-15完了）は
docs/improvement-plan-archive/2026-08-15.md へ移設済み]**

---

**[T34〜T74ほか（第4回レビュー対応・品質保証の追加施策・外部静的データソース検討対応・
UI操作レビュー対応・属性の重複包含関係レビュー対応・静的属性レイヤー絞り込みUI拡張・
PostGISクエリコストレビュー対応・designation実装レビュー対応・将来の静的属性拡張検討・
統合レビュー対応2026-08-16第1回とそのフォローアップ、いずれも2026-08-16完了）は
docs/improvement-plan-archive/2026-08-16.md へ移設済み]**

---

**[T75〜T104ほか（交通ストレス判定ロジックの精緻化・統合レビュー対応2026-08-17第2回の指摘・
交差点密度レイヤーの地図可視化撤去・夜間のOpen-Meteo 502緩和・OSM追加属性の活用検討・
「地図の見え方」表示トグル誤操作バグ修正、いずれも2026-08-17完了）は
docs/improvement-plan-archive/2026-08-17.md へ移設済み]**

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


---

**[T106〜T117ほか（交通ストレスレシピ外出し基盤・交通ストレスレシピ調整UIパネル・
天候取得502の再発・研究パラメータの導線改善・交通ストレス5段階化、いずれも
2026-08-17完了）はdocs/improvement-plan-archive/2026-08-17.md（同一ファイル、
バックエンド一時的到達不能の調査より後の節）へ移設済み]**

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

### - [x] T128. 地図上アイコンチップの増加対策〔グルーピング・表示絞り込み〕規模M（2026-08-19完了、A案実装）

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
- 実装メモ（2026-08-19完了）: ユーザー指示「T128とT145の検討をしたい…アイコンをスマートに
  グループ化したい」「A、B、Cの順で実施して」を受け、T161（凡例追加）に続くB段階として
  A案（カテゴリ束ね）を実装した。T145b以降ramp軸（停止密度・事故密度）が追加され
  static10種+dynamic1種＝11チップに増えていたため、着手時点で当初の「9→5」より効果が
  大きくなった: `MAP_LAYER_CATEGORY_ORDER`順に束ねると道路状態（道路情報・指定路線、
  2→1）・交通・安全（車の圧迫感・停止要因・事故・停止密度・事故密度、5→1）が集約され、
  実際のチップ総数は11→6（自転車インフラ・地形・補給施設・ルートは1件のみのため従来どおり
  単独チップ）。
  変更ファイル: `mapLayers.ts`（`dataNature?: "raw"|"composite"`をMapLayerDescriptorへ追加、
  carStressと全ramp軸レイヤーに明示。カテゴリの表示順・見出し文言をMapLayersPanel.tsxから
  ここへ集約し`MAP_LAYER_CATEGORY_ORDER`/`MAP_LAYER_CATEGORY_LABELS`としてexport、
  地図上チップとサイドバーの両方が同じ単一ソースを参照するようにした[設計原則8]）、
  `MapLayersPanel.tsx`（上記への参照差し替えのみ、見た目・挙動は無変更）、
  `MapOverlayControls.tsx`（`buildChipGroups`でcategory単位に束ね、2件以上のカテゴリだけ
  グループチップ化。単独/グループの分岐を吸収する共通`ChipButton`コンポーネントを新設し、
  グループの▶内容は`groupByDataNature`で「推定指標（合成）」「観測データ」の小見出しへ
  分ける[両方混在するのは現状trafficSafetyのみ]。グループ内の各メンバーはサイドバーと同じ
  `LayerChip`部品でON/OFFトグルし、ONかつ凡例を持つメンバーはT161のrenderLegendDetailsを
  その場に続けて出す[もう1段のネスト展開は設けない]）、`page.tsx`（overlayLayersへ
  `category`/`dataNature`を渡す2行のみ）。
  **実装中の発見・修正**: `ChipButton`を当初`MapOverlayControls`関数の内側にネストした
  素朴な関数として書いたところ、eslint-plugin-react-hooksの新しい`refs`ルール
  （「refは直接コンポーネント/フック内でのみ触れる」）が誤検知した。回避のため関数名を
  PascalCase化して`<ChipButton ... />`とJSX呼び出しに変えたところlintは通ったが、
  今度は実際にレンダーのたびに新しい関数（＝別コンポーネント型）が生成されることになり、
  Reactが凡例展開のたびに丸ごとアンマウント/再マウントする実害が発生（vitestで
  「▶をクリックしてもaria-expandedがtrueにならない」という形で顕在化。原因は
  クリック時点のDOM要素への参照が再マウント後は別要素に差し替わり、テストが古い
  デタッチ済みノードを見ていたため）。**教訓: eslint-plugin-react-hooksのrefsルールを
  満たすためだけにコンポーネントを親関数の内側に定義しない**。`ChipButton`を
  モジュール直下の安定した関数へ移し、`rowRefs`/`panelRects`はprops（`registerRow`/
  `panelRect`）経由で渡す設計に修正して解消した。
  検証: `MapOverlayControls.test.tsx`へカテゴリ束ねの新規テスト4件（グループ化・
  メンバー展開・dataNature小見出しの出し分け・グループのaria-pressed）を追加。
  frontend vitest 345件・tsc・eslint全green。Playwright headless実機確認
  （退避ポート3011、DBなしのためタイル自体は「読み込みに失敗」表示だがUI操作は正常）:
  「道路状態」「交通・安全」チップの自動出現・展開時のメンバー一覧・「交通・安全」展開時の
  推定指標/観測データ小見出しの出し分け・メンバーをONにした際の色スウォッチ凡例
  （T161）のインライン表示・サイドバー側の連動を、いずれもスクリーンショットで確認。


---

**[T129・T130の一部ほか（研究モード実機検証の高速化・安定化・「道路適正」「自動車密度」を
独立レシピ軸として切り出すN1/N2構造・研究タブのレイアウト改善、いずれも2026-08-18完了）は
docs/improvement-plan-archive/2026-08-18-part1.md へ移設済み]**

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

### - [x] T136. 軽微な残骸・テスト非対称の解消（errorLabel・回帰テスト・living_street再検証）
  規模S（2026-08-20完了。errorLabel修正・回帰テストは2026-08-19完了、living_street再検証は
  dev DB接続可能な本セッションで実施）

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
  追記（2026-08-20完了、dev DB接続可能なセッションで実施）: `measure_axis_stats.py`を
  dev DB（東京都心南部、PostGIS実データ）に対して実行し、highway階級別事故密度で
  `living_street: 2.81`件/(km・年)を確認した（tertiary 3.13・cycleway 2.35の中間に近い
  値）。ただし`measure_axis_stats.py`自体は密度比のみを出力し件数を出さないため、
  「区間の分布・件数」の確認として`osm_raw_ways`を直接集計したところ、**living_street該当は
  dev DB全体でわずか8way・0.9km**（residential 42,725way・5,705.6km、tertiary
  9,239way・1,993.2km、cycleway 1,007way・178.0kmと比べて2〜3桁少ない）と判明した。
  この規模のサンプル（事故件数はおそらく1件未満〜数件）から算出された密度値は統計的に
  信頼できず、`road_suitability_recipe.yaml`のliving_street基準値（=1、cyclewayと統一）を
  実データの密度比に合わせて見直す根拠にはならないと判断した。**結論: 現行の基準値
  （構造統合による1、実データ根拠ではない）を維持する**。将来もっと広域（全国or関東本土
  全域の本番DB）でサンプル数が確保できたときに再評価する余地は残るが、本タスクの完了条件
  （`measure_axis_stats.py`出力への言及）は満たしたためcloseする。
  なお、dev DBは関東本土全域ではなく東京都心南部の地域サブセットである点に留意
  （全域データは本番Oracle CloudのDBのみ、docs参照）。

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

### - [x] T161. 停止密度・事故密度ramp軸に色スウォッチ付き凡例を追加する 規模S（2026-08-19完了）

- 発端: ユーザー相談「T128とT145の検討をしたい。1次要素、2次要素で地図上アイコンを
  スマートにグループ化したい…停止、事故密度の凡例を付けて」。T145bはramp軸の凡例情報
  （`axisRampLegendEntries`）を生成していたが、実際にはラベル文字列のみを
  `panelHintDetail`（文字列の`<ul>`）として出しており、他レイヤー（車ストレス・
  自転車インフラ等）が持つ色スウォッチ＋チェックボックスの凡例（`LegendEntry`/
  `STATIC_FILTER_AXES`）と体裁が異なっていた。ユーザーからも「展開後の表示は文字でなく、
  今のアイコン＋▼で凡例展開の見た目を踏襲したい」と明示指定。3段階（A凡例→Bチップ
  グルーピング→C研究タブ整理）のうちA。
- 対応方針: `axisLayers.ts`の`axisRampLegendEntries`（ラベルのみ返す簡易版）を廃止し、
  他レイヤーと同じ`LegendEntry[]`（key/label/color/filter）を返す`buildAxisRampLegend`へ
  置き換える。`staticAttributeLayers.ts`の`STATIC_FILTER_AXES`（絞り込み軸カタログ、
  サイドバー凡例チェックボックス・地図チップの▶展開凡例・実際の絞り込みを1箇所から
  駆動する既存の汎用機構）へ`RAMP_AXES`を機械的に追記するだけで、他レイヤーと全く同じ
  仕組み（新規UIコンポーネント不要）で凡例が両方の場所に現れる設計にした。
- 完了条件: 停止密度・事故密度レイヤーのサイドバーパネル・地図チップの両方に、色分けと
  対応した凡例（境界値ラベル・単位付き）が既存レイヤーと同じ見た目で表示されること。
- 実装メモ（2026-08-19完了）: 実装中に、`MapLayersPanel.tsx`の`renderSectionBody`の
  `switch (layer.id)`に`axis:${string}`（ramp軸レイヤーid）へのcase/defaultが元から
  無く、ramp軸のサイドバーパネル本文が常に空だったという既存バグ（T145b実装時の
  見落とし、T145bの完了条件チェックはPlaywrightで「チップの自動出現・ON切替」までしか
  確認しておらずパネル本文の中身までは見ていなかった）を発見し合わせて修正した
  （`default:`ケースで`renderStandardSectionBody`へフォールバックさせる、他の標準レイヤー
  と同型）。
  変更ファイル: `axisLayers.ts`（`axisRampLegendEntries`→`axisRampBand`/
  `axisRampBandLabel`/`buildAxisRampLegend`、後者は既存の`buildAxisRampValueExpression`
  への範囲比較filterを持つため地図の色分けと凡例の境界が一致することを構造的に保証）、
  `mapLayers.ts`（`panelHintDetail`の生成を削除、凡例は`STATIC_FILTER_AXES`側の責務に
  一本化）、`staticAttributeLayers.ts`（`StaticFilterAxisId`を`RampAxis["axisId"]`
  〔動的なaxis-catalog.json由来のためリテラル列挙不可〕で拡張し`STATIC_FILTER_AXES`へ
  `RAMP_AXES`を追記）、`MapLayersPanel.tsx`（前述のバグ修正）。`page.tsx`・
  `MapView.tsx`・`MapOverlayControls.tsx`は`STATIC_FILTER_AXES`を汎用的に走査する
  既存実装のため無改修で凡例・絞り込みの両方に反映された。
  検証: `axisLayers.test.ts`を`buildAxisRampLegend`向けに書き換え（キー重複無し・
  境界フィルタが`buildAxisRampValueExpression`と同じ値式を参照し境界が連続することを
  追加検証）。frontend vitest 341件・tsc・eslint全green。

### - [x] T162. 研究タブを「評価の重み」「レシピ」の2カテゴリから2次要素（軸）ごとの整理へ変更する 規模S（2026-08-19完了）

- 発端: T161・T128に続くC段階。ユーザー相談「T128とT145の検討をしたい…研究タブの中を、
  2次要素ごとに整理して」「A、B、Cの順で実施して」。以前の研究タブは「評価の重み」
  （`WeightPanel`、区間難易度の重み7軸がフラットな1リスト）と「レシピ[一次情報→
  二次情報の変換式]」（`RoadSuitabilityRecipePanel`/`MotorVehicleDensityRecipePanel`/
  `CarStressRecipePanel`）という「操作の種類」で分かれた2カテゴリで、同じ軸（車の圧迫感）の
  重みとレシピを見比べるのに2箇所を行き来する必要があった。
- 対応方針: `route_preference.yaml`の区間難易度の重み7軸（`PREFERENCE_FIELDS`）は
  registry軸（勾配/舗装/風/信号・踏切等/車の圧迫感/事故/夜間、`lib/evaluationAxes.ts`
  参照）と1:1対応するため、レシピを持つ軸（現状は車の圧迫感のみ）はその軸の重み行の
  直下へレシピパネルを差し込む構成にし、「レシピ」という独立カテゴリを廃止する。
- 完了条件: 車の圧迫感の重み入力のすぐ下に、道路適正・自動車密度（共有材料）＋
  車ストレスレシピパネルが表示されること。他の軸（重みのみでレシピを持たない）は
  従来どおり入力欄のみで変化しないこと。
- 実装メモ（2026-08-19完了）: `WeightPanel.tsx`へ`renderPreferenceFieldExtra?:
  (weightKey) => ReactNode`という汎用の差し込み枠を追加した（WeightPanel自身は
  車ストレス等の個別知識を持たないまま、page.tsx側がweightKeyごとに何を差し込むか
  決められる）。`page.tsx`側で`renderCarStressRecipeExtra()`（旧「レシピ」カテゴリの
  中身そのもの、共有材料グループ＋インデントしたCarStressRecipePanel）を組み立て、
  `car_stress_weight`のときだけ返す`renderPreferenceFieldExtra`を`WeightPanel`へ渡す形に
  した。旧「レシピ」カテゴリの`<div className={styles.researchCategory}>`ブロックは削除。
  **副次的な発見**: この移動で「共有材料[車の圧迫感・安全度が参照]」という見出し文言と
  周辺コメントが、T139で既に廃止済みの安全度軸を参照したままの**古いまま**だったことに
  気づき、あわせて修正した（`page.tsx`本文・`page.module.css`のコメント両方）。
  `page.module.css`の`.researchCategory + .researchCategory`（2カテゴリ間の余白ルール）も
  `.researchCategory`が1つだけになり不要になったため削除。
  検証: `WeightPanel.test.tsx`へ新規テスト1件（`renderPreferenceFieldExtra`が対象の
  weightKeyの行にだけ差し込まれる）追加。frontend vitest 346件・tsc・eslint・
  `next build`全green。Playwright headless実機確認（退避ポート3011）:
  研究モードON→評価重みカード展開→区間難易度の重みを展開→車の圧迫感の重み欄の直下に
  「レシピ[一次情報→二次情報の変換式]・共有材料[車の圧迫感が参照]」ボックス（道路適正・
  自動車密度）とその下にインデントされた車ストレスレシピパネルが現れることをスクリーン
  ショットで確認。

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

### - [x] T148. 旧・安全度レイヤーと計算コードを削除する 規模M（2026-08-19完了）

- 背景: 設計プロンプトのタスク9。T139〜T147の移行が完了し、night/accident/car_stress軸への
  切替が本番で安定稼働していることを確認したうえで、`domain/safety.py`・
  `safetyExpression.ts`・`safety`レイヤー・`safety_recipe.yaml`・関連API
  （`SafetyRecipeOverride`等）を削除する。
- 対応方針: 削除前に本番での稼働実績（最低1〜2週間、他タスクの完了条件と同様の慣例）を
  確認してから着手する。削除後はOpenAPI契約・フロント生成型を再生成し、ドリフトが無いことを
  CIで確認する。
- 完了条件: `safety`関連のシンボル・エンドポイント・レイヤーがコードベースから消え、
  backend pytest・frontend vitest・eslint・tsc・OpenAPIドリフト検知すべてgreen。
- 実装メモ（2026-08-19完了）: 本番はまだ稼働開始前（ユーザー確認済み）のため、「1〜2週間の
  安定稼働実績」というgate条件は適用対象外と判断し、T139完了直後に着手した（安全度軸は
  T139時点で既に難易度合成から外れた表示専用値であり、本番未稼働の状態で追加の移行リスクは
  発生しない）。
  backend: `domain/safety.py`・`app/safety_recipe.yaml`・`tests/test_safety.py`を削除。
  `domain/route.py`の`RouteSegmentDetail.safety`/`RouteCandidate.safety_score`フィールド、
  `domain/recipe_definition.py`の`AXIS_PARAM_SAFETY`定数・`RecipeComponents.safety_recipe`、
  `services/evaluation_service.py`の`load_safety_recipe()`、
  `services/region_service.py`の`get_safety_breakdown()`、
  `api/dependencies.py`の`RouteGenerationSetup.safety_recipe`、
  `api/routers/routes.py`の`SafetyRecipeOverride`クラス・`GenerationConditions.safety_recipe`、
  `api/routers/region.py`の`POST /api/region/safety-breakdown`エンドポイントを削除。
  `domain/evaluation.py`/`services/road_graph_engine.py`/`services/openrouteservice_engine.py`は
  `car_stress_level`と`safety_level`の両方が「車との近さ」(N2=road_suitability+
  motor_vehicle_density)を必要としていたために存在した`car_closeness_result`の
  重複計算防止パス（T134で追加）を、呼び出し元が`car_stress_level`単独になったため撤去し、
  `carStressExpression.ts`の`carCloseness`引数のデフォルト値評価（省略時に1回だけ計算される
  既存パターン）に委ねた。`scripts/export_openapi.py`の安全度関連書き出しを削除。
  `scripts/measure_axis_stats.py`は安全度関連のレポート生成コードを削除する過程で
  `pearson_correlation`/`spearman_correlation`/`_average_ranks`まで一度削除してしまい、
  同関数群を再利用している`scripts/analyze_jartic_calibration.py`（T53、車ストレス×交通量の
  相関分析、安全度とは無関係）のインポートを壊す事故を起こしたため、3関数を復元
  （docstringに「measure_axis_stats.py自体はもう使わないがanalyze_jartic_calibration.pyが
  再利用するため残す」旨を明記）。
  frontend: `components/SafetyRecipePanel/`ディレクトリ・`components/Map/safetyExpression.ts`
  （テスト含む）を削除。`types/route.ts`の`SafetyRecipeOverride`・`types/traffic.ts`の
  `SafetyBreakdown`型エイリアスを削除。`mapLayers.ts`の`safety`レイヤー定義・
  `staticAttributeLayers.ts`の安全度色分け/凡例・`MapView.tsx`の`ensureSafetyLayer`/
  `applySafetyRecipe`・`SAFETY_LAYER_ID`・`setStaticOverlayFilters`の`safety`関連引数
  （6引数→5引数）を削除。`recipeBreakdownPopup.ts`の`attachSafetyBreakdownHandler`/
  `SAFETY_BREAKDOWN_CONFIG`、`regionApi.ts`の`fetchSafetyBreakdown`、`icons.tsx`の
  `SafetyIcon`を削除。`page.tsx`から`SafetyRecipePanel`の配線・`safetyRecipe`の
  `useRecipeOverride`・`showSafety`レイヤートグルを削除。`mapLayers.ts`の
  `MapLayerCategory = "trafficSafety"`（UIカテゴリ名。車ストレス・事故・停止要因の
  カテゴリ見出しとして今も使用中）は安全度レイヤーとは別概念のため意図的に維持。
  `carStressExpression.ts`/`recipe.py`の「車との近さ」(N2)共有材料コメントから安全度への
  言及を除去。OpenAPI契約は`export_openapi.py`＋`npm run generate:api`＋`next typegen`で
  再生成し、生成物（`openapi.json`/`api.d.ts`/`axis-catalog.json`等、`safety-recipe.json`・
  `safety-test-cases.json`は書き出し対象から外れたため削除）にドリフトが無いことを確認。
  地図レイヤーは10→9レイヤーへ変更、docs/architecture.mdの該当箇所（§7「安全度」節・
  タイル世代表・APIリファレンス・TypeScriptインターフェース定義）を追従更新。
  backend pytest 818件・frontend vitest 340件・eslint・tsc・`next build`全green。

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

### - [x] T152. way_attribute_countsのWay単位平均化による精度劣化を実測し、交差点分割
  セグメント単位への移行要否を判断する 規模M（2026-08-20完了）

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
- 実装メモ（2026-08-20完了）: `measure_way_segment_split.py`をdev DB（東京都心南部、
  PostGIS実データ、対象way数86,642件）に対して実行した。
  - **モデルA（真値）**: 総セグメント数196,044、平均2.26セグメント/way、走査コスト倍率
    2.26倍。分布はp50=1.0・p90=5.0・p99=12.0・max=52（中央値のwayは分割なし＝1
    セグメントで、少数の長いwayが多数のセグメントを持つロングテール）。
  - **モデルB（raw_intersection_nodesの安価な近似）**: 総セグメント数196,042、平均2.26
    セグメント/way、倍率2.26倍。**A/Bの乖離は86,642way中わずか2way（0.002%）、平均
    セグメント数差は0.000**で、実質的にモデルAと区別がつかない精度だった。
  - **判断: (a) 現状維持（Way単位のまま）とする**。根拠: (1) 走査コスト倍率2.26倍は
    「精度が実害を伴うと確認できた場合に許容しうる」規模だが、本スクリプトが計測したのは
    あくまで「セグメント単位化した場合の機械的なコスト」であり、「Way単位平均が実際に
    ルート評価と地図表示を有意にズレさせている」という実害そのものは別途未計測（本タスクの
    対応方針が元々想定していた計測対象外）。実害の実測なしに2.26倍のコスト（ストレージ・
    `precompute_way_attribute_counts.py`のバッチ時間・関連テーブル設計変更）を先取りして
    払うのは、本プロジェクトが繰り返し採用してきた「実害が実測・実証されるまで複雑化を
    足さない」という設計方針（`docs/complexity-review-2026-08-16.md`）に反する。
    (2) 仮に将来「実害あり」と判明しセグメント単位化に踏み切る場合は、モデルBがモデルAと
    ほぼ同精度（乖離0.002%）なので、モデルB（既存`raw_intersection_nodes`の再利用、
    追加の空間計算なし）を採用すべきという判断材料も同時に得られた。
  - 「低ズームはWay単位平均、高ズームのみセグメント単位」という二段構えは、(a)現状維持の
    判断により本タスクでは検討不要と判断（Way単位から動かさないため）。
  - 後続の実装タスクは起票しない（(a)決定のため）。dev DBは関東本土全域ではなく東京都心
    南部の地域サブセットである点に留意（T136の実装メモと同じ注記）。

## 統合レビュー対応（2026-08-19・review:all第4回の指摘）

overall/complexity/consistency/uiの4レビューを並列実施し相互統合した結果
（`.claude/commands/review/history/2026-08-19_all.md`）のうち実施すべきものを起票する。
対象コミット`e90d920`時点（`32e84ed..e90d920`、T131・T132〜T136・T137〜T151の11コミット）の
指摘。P0は無し。

### - [x] T153. RoadGraphEngineのcar_closeness()/car_stress_level()二重計算を解消し、
  回帰テストのモジュール境界の死角を修正する 規模S（2026-08-19完了）

- 発端: 統合レビュー統合-1（overall F-1）。T134（車ストレス・安全度表示の二重計算解消）は
  `_build_segment_details`内の直接呼び出し2箇所（`car_stress_level`・`safety_level`）を
  対象に完了したが、同一差分内で先に適用されたT143が追加した別経路
  （`compute_edge_axis_scores`呼び出し、`road_graph_engine.py:337-345`）が
  `evaluation.py`内部で`car_closeness()`/`car_stress_level()`を独立に再計算しており、
  T134の対応範囲外だった。T134の回帰テスト（`test_road_graph_engine.py:534-558`）は
  `road_graph_engine`モジュールの束縛のみをmonkeypatchするため、`evaluation.py`側で
  解決される呼び出しをカウントできずgreenのまま通過している。T120・T121-a・前回overall F-3
  （T134自身が対応した指摘）に続く**4件目の同型パターン**（片方だけ直して別の箇所を忘れる）。
- 対応方針: `compute_edge_axis_scores`（`evaluation.py`）に`car_closeness_result: ... | None
  = None`引数を追加し、`_build_segment_details`が計算済みの結果を渡す形へ変更する
  （`car_stress_level`/`safety_level`と対称のパターン）。回帰テストは、
  `compute_edge_axis_scores`が受け取った結果をそのまま使い再計算しないことを直接検証する
  形（呼び出し引数のspy、または`car_closeness_result`が指定されたときは内部で
  `car_closeness()`を呼ばないことの検証）へ修正する。
- 完了条件: backend pytestが二重計算の不在を検証する形で追加・green。既存の
  `test_build_segment_details_calls_car_closeness_once_per_edge`が実際に
  `evaluation.py`経由の呼び出しも捕捉できることを確認する。
- 実装メモ（2026-08-19完了）: 着手時点でT148（並行セッションが完了）がsafety_level経由の
  旧dedup機構を撤去済みだったが、`road_graph_engine.py: _build_segment_details`の
  `car_stress_level()`直接呼び出し（表示用生値`car_stress`）と、続く
  `compute_edge_axis_scores`（T143）呼び出し内部での`car_stress_level()`再計算という
  **新しい経路**の二重計算は未解消のまま残っていることをコードで確認し、これを解消した
  （openrouteservice_engine.pyは`compute_edge_axis_scores`を経由せず
  `evaluate_axis_difficulties`を直接呼ぶ設計のため、この二重計算は元から発生しない）。
  `domain/evaluation.py: compute_edge_axis_scores`へ`car_stress_level_value`引数
  （未指定時のセンチネル`_CAR_STRESS_LEVEL_NOT_PROVIDED`で判定、Noneは「way_tags無しで
  計算不能」という既存の意味と衝突させないため）を追加し、`road_graph_engine.py`側で
  計算済みの`car_stress`をそのまま渡す形へ変更。誤りが含まれていたコメント
  （T148実装メモが「road_graph_engine.pyの区間表示ビルダーも単純化済み」と記載していたが
  実際には未解消だった）も実態に合わせて修正。
  回帰テスト`test_build_segment_details_calls_car_stress_level_once_per_edge`を新設
  （`test_road_graph_engine.py`）。旧回帰テストと同じmonkeypatchの死角
  （`road_graph_engine`と`evaluation`は`car_stress_level`をそれぞれ別々の名前へ束縛する
  ため片方だけ差し替えても検知できない）を踏まえ、両方の束縛へ同一spyを設定。
  `generate_loops`経由だと`RoadGraphEngine.prepare`がグラフ全Edge分の探索コスト計算でも
  `car_stress_level`を呼ぶため区間数との単純比較ができず、`_build_segment_details`を
  直接呼び出す形でテストした。フィックス適用前に一時的に戻して同テストが
  `4 == 2`で実際に失敗することを確認済み（テスト自体の有効性の検証）。
  backend pytest 821件（新規1件）green、既存820件に regression なし。

### - [x] T154. docs/architecture.md §7をT130〜T151全体（レジストリ制導入・区間インスペクタ・
  base_by_highway共有）へ包括的に追従させる 規模M（2026-08-19完了）

- 発端: 統合レビュー統合-2（overall F-2 ＋ consistency F-1・F-2・F-3の統合）。
  T132（前回起票、2026-08-19完了）は「T137〜T151の各タスクの完了条件でarchitecture.md
  追従が担保されている」という前提で実施したが、これが誤りだったことが今回判明した。
  具体的には: (a) `architecture.md:927-930`「`base_by_highway`の数値セット自体は独立」が
  実装（T130で意図的に共有）と正反対のまま——`git blame`で本レビュー対象コミット
  （`c61ede8`）が当該行を実際に編集しながら誤りを直していないことを確認した
  （「触れていないから見逃した」ではなく「触れたのに直せなかった」新しい失敗モード。
  architecture.md未追従パターンの**4回目の再発**）。(b) T146（区間インスペクタ、新設API
  `POST /api/region/axis-inspector`・`AxisInspectorResult`等）が一切未反映。(c)
  レジストリ機構（`domain/registry.py`/`domain/recipe_definition.py`）自体の説明が無く、
  既存の「評価軸追加の1本道」記述もレジストリ登録（表示のため）と計算経路（依然手動配線）が
  分岐している現状を反映していない。
- 対応方針: §7を包括更新する。(a)の段落を`RoadSuitabilityRecipe`共有の実装に合わせて
  書き換え、(b)区間インスペクタの小節（新設エンドポイント・`covered_weight_fraction`の
  意味・勾配/風が常時欠損である設計判断）を追加、(c)「一次属性レジストリ・二次軸レジストリ」
  の専用小節を新設しレジストリ登録ステップと計算経路の手動配線制約を明記する。あわせて、
  「規模M以上でAPI/ドメイン概念を新設するタスクは完了条件へarchitecture.md追従を既定で
  含める」運用と、「完了マーク済みのdocs追従タスクは実際に`git blame`で該当パラグラフを
  裏取りする」手順の明文化を検討する（CLAUDE.md改訂の要否も含めユーザー判断）。
- 完了条件: architecture.md中に`car_closeness`/`RoadSuitabilityRecipe`/`registry.py`/
  `axis-inspector`等の新設シンボルへの言及があり、`base_by_highway`の記述が実装と一致する
  こと。次回consistencyレビューで`git blame`による裏取りを実施し再発が無いことを確認する。
- 実装メモ（2026-08-19完了）: 着手時点で(a)は並行セッションのT148（旧安全度削除）が
  §7を大幅改稿した副産物として既に解消済みだったことをコードで確認（`highway`基本値が
  `RoadSuitabilityRecipe`共有である旨が正しく記載されている）。残っていた(b)(c)を対応。
  (b) §4のAPI一覧へ`POST /api/region/axis-inspector`のRequest/Response仕様を追加、
  §7へ「区間インスペクタ（改善計画T146）」小節を新設（`way_attribute_counts`からの5軸算出・
  gradient/wind常時欠損・`covered_weight_fraction`の意味を説明）。(c) §7へ「一次属性
  レジストリ・二次軸レジストリ（改善計画T137）」小節を新設し、`registry.py`の排他制約
  チェック機構・`register_defaults()`の正準登録内容（6軸＋windは対象外）を説明したうえで、
  「レジストリは表示メタデータのみを駆動し、コスト計算への配線はT142で意図的に見送られた
  ままの手動管理」という制約を明記。既存の「評価軸追加の1本道」段落へも、この1本道が
  コスト計算側の経路であり地図表示側は別経路である旨の注記を追加。`recipe_definition.py`
  への言及は、着手中にT155（本セッションで先行実施）によりファイル自体が削除されたため、
  「新設されたが配線されず孤立していたためT155で削除済み」という歴史的経緯の記述に留めた
  （現存しないモジュールを現在形で説明しない）。T160(3)で指摘されていた
  `architecture.md:104`のRouteSegmentDetail旧フィールド列挙（Step9時点の4指標のまま）も
  本タスクの一部として現行7指標へ更新（ついで実施）。
  運用ルール明文化（規模M以上のarchitecture.md追従の既定化・git blameでの裏取り手順）は
  CLAUDE.md改訂を伴うためユーザー判断のまま見送り。次回consistencyレビューでの裏取り確認は
  引き続き完了条件として有効。

### - [x] T155. recipe_definition.py（T141）の配線または削除を最終判断する 規模S（2026-08-19完了）

- 発端: 統合レビュー統合-3（overall F-3）。T141は「実配線はT142以降」と明記していたが、
  T142は別方式（`compute_edge_axis_scores`＋手書き辞書2種）を採用し`recipe_definition.py`
  （`Recipe`/`RecipeComponents`/`recipe_from_components`/`recipe_to_components`/
  `default_recipe`、136行）を一切参照していない。自身のテスト以外どこからも呼ばれない
  孤立状態のまま残存している。
- 対応方針: 以下のいずれかをユーザー判断で選択する: (a) REMOVE（現在何も提供していない
  ため）、(b) 将来用途（例: `ExperimentSlot`の差分レイヤー化）で本当に必要なら、明示的な
  トリガー（例: 「差分レイヤー化に着手する時点」）を付けてDEFERへ格上げする。
- 完了条件: (a)の場合はファイル・テストの削除とgrepでの参照ゼロ確認。(b)の場合は
  DEFER欄への移動とトリガー条件の明記。
- 実装メモ（2026-08-19完了）: (a) REMOVEを選択。着手時点で再確認しても
  `grep -rln "recipe_definition" backend --include="*.py"`は`tests/test_recipe_definition.py`
  自身のみで、T148（並行セッション）の改修後も状況は変わっていなかった。「いつか
  ExperimentSlotの差分レイヤー化で使うかもしれない」という(b)の将来用途は具体的な着手時期の
  見込みが無く、設計原則9（DEFERにはトリガーを付け、トリガー未到達の項目を「ついで」に
  実装しない）・原則10（将来のための過剰設計を避ける）に照らし採用しない。
  `backend/app/domain/recipe_definition.py`・`backend/tests/test_recipe_definition.py`を削除。
  grep再確認で参照ゼロ、backend pytest 814件（821件から7件減、削除したテスト分）green。

### - [x] T156. registry_defaults.pyとevaluation.pyの軸ID集合のドリフト検知テストを追加する
  規模S（2026-08-19完了）

- 発端: 統合レビュー統合-4（complexity F-2）。`registry_defaults.py`の軸ID集合（6軸）と
  `evaluation.py`の`AXIS_WEIGHT_FIELD_TO_AXIS_ID`（7キー=6軸+wind）・
  `_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`は独立した手書き辞書で、一致を検証するテストが無い
  （T154(c)と根本原因は同じ、T142がtransform_fnの動的解決を意図的に見送った帰結）。
  将来8軸目を追加する際、片方だけ更新してももう片方のテストは気づかない。
- 対応方針: `test_registry_defaults.py`または`test_evaluation.py`へ
  `set(AXIS_WEIGHT_FIELD_TO_AXIS_ID.values()) == {a.axis_id for a in all_axes()} |
  {"wind"}`相当の1行アサーションを追加する（`register_defaults()`呼び出し込み）。
- 完了条件: backend pytest green。意図的に片方の辞書だけをズラして当該テストが
  failすることを実装時に手元で確認する。
- 実装メモ（2026-08-19完了）: `test_registry_defaults.py`へ
  `test_registry_axis_ids_match_evaluation_axis_weight_mapping`を追加
  （`AXIS_WEIGHT_FIELD_TO_AXIS_ID`の値集合からwindを除いたものと、
  `registry.all_axes()`の軸ID集合の一致を検証。`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`は
  `AXIS_WEIGHT_FIELD_TO_AXIS_ID`とキーの集合が常に同じ形で保守されており
  （両方とも7軸固定の辞書リテラル、evaluation.py内で並んで定義）、片方を検証すれば
  実用上十分なため後者のみ対象とした）。`evaluation.py`の`night_weight`マッピング先を
  一時的に`"night_typo"`へ書き換えて当該テストが実際にfailすることを確認してから
  元に戻した（テスト自体の有効性の検証）。backend pytest 815件（新規1件）green。

### - [x] T157. MapView.tsxの閾値付きKEEPをレジストリ駆動レイヤーの実態に合わせて
  再定義する 規模S（基準整備のみ、コード変更なし）（2026-08-19完了）

- 発端: 統合レビュー統合-5（complexity F-1）。Keep List閾値「STATIC_OVERLAY_LAYERS
  10種」に到達したが、内訳は手書き8件＋レジストリ自動生成2件（ramp軸、
  `makeEnsureAxisRampLayer`により軸追加時のMapView側追記が実測ゼロ）であり、
  閾値設定当時の前提（「1軸=1手書きミラー」）と食い違っている。カウント方式を変えず
  次の閾値を置くと誤発火・誤不発火する。
- 対応方針: `/review:improve`経由でdocs/complexity-review-2026-08-16.mdのKeep Listを
  「手書きSTATIC_OVERLAY_LAYERS（ramp軸を除く）10件到達 or bespoke種の軸が3件目に
  増加 or MapView.tsx 2,000行到達」へ再定義する。あわせてpage.tsxの閾値付きKEEP
  （「40件 or 1,300行」、T135で反映済み）と同様に「何を測っているか」を明示的に
  書き添える。
- 完了条件: docs/complexity-review-2026-08-16.mdへの反映を次回complexityレビューで確認。
- 実装メモ（2026-08-19完了）: `docs/complexity-review-2026-08-16.md`のR-6節へ2026-08-19の
  再定義を追記（過去の判断は書き換えず、新しい追記として残す方針）。閾値を
  「手書きSTATIC_OVERLAY_LAYERS（ramp軸を除く）10件到達」「bespoke種の軸が3件目に増加」
  「MapView.tsx 2,000行到達」「5つ目のレシピ軸のMapView内ミラー追加」の4条件へ再定義し、
  ramp軸自体の増加は意図的にノーカウントとする理由を明記。Keep Listの該当項目・設計原則9も
  新しい閾値表現へ更新。実測値も記録: MapView.tsx 1,766行（T148の安全度レイヤー削除で
  1,891→1,766行に減少）・手書きSTATIC_OVERLAY_LAYERS 7件（T148でsafetyが抜け8→7、
  `frontend/src/components/Map/MapView.tsx:667-676`で確認）・ramp種2件
  （`axis-catalog.json`のkind="ramp"がstop_density/accidentの2件）・bespoke種2件
  （car_stress/night）。コード変更なし。

### - [x] T158. 「安全度」レシピパネルへルート生成の重みに使われなくなったことを示す注記を
  追加する 規模S（2026-08-19・対象消滅により対応不要と判断）

- 発端: 統合レビュー統合-6（uiレビュー）。T139で「安全度」軸はルート生成の重み付け
  （`RoutePreferenceWeights`）から除外され、事故密度・夜間という別軸へ分割されたが、
  研究タブでは、もはやルートの重みに影響しない「安全度」パネルが、実際に影響する
  「車の圧迫感」パネルと全く同じ見た目で並び続けている。研究者が値を調整しても実験結果に
  反映されないことに気づかないリスク、一般ユーザー視点でも「安全度」「事故密度」の違いが
  伝わらない。
- 対応方針: 「安全度」パネルの見出しまたはpanelHint（`mapLayers.ts`）へ
  「現在ルート生成の重みには使われていません（参考表示のみ、事故密度・夜間軸へ移行済み）」
  の一言を追記する。T148（旧安全度削除）着手前に有効な暫定対応であり、T148完了時に
  パネル自体が削除されればこの注記も一緒に消える。
- 完了条件: frontend vitest・eslint・tsc green。Playwright実機確認で注記が表示される
  ことを確認。
- 実装メモ（2026-08-19）: 本タスク起票の直後、並行セッションがT148（旧・安全度レイヤーと
  計算コードを削除）を「本番未稼働のため安定稼働gateは対象外」と判断し前倒しで実施
  （`6b7a2e7`）。`SafetyRecipePanel`自体が地図レイヤー・APIごと削除されたため、注記を
  追加する対象が消滅した。対応不要と判断しチェック完了とする。コード変更なし。

### - [x] T159. T148（旧安全度削除）の完了条件へ具体的な暦日を明記する 規模S
  （2026-08-19・対象消滅により対応不要と判断）

- 発端: 統合レビュー統合-7（complexity F-3）。T148の完了条件「本番稼働1〜2週間の確認後」に
  具体的な日付が無い。T145b/T151の本番Oracle Cloudへの反映は2026-08-19（本レビュー当日）に
  完了済みのため、起算日が定まる。
- 対応方針: T148の完了条件へ暦日（例: 2026-09-02＝本番反映から2週間）を追記する。
- 完了条件: T148の本文に暦日が明記されていること。
- 実装メモ（2026-08-19）: 本タスク起票の直後、並行セッションがT148そのものを完了させた
  （`6b7a2e7`、本番未稼働のため安定稼働gateは対象外と判断し前倒しで実施）。T148が完了した
  ため「完了条件への暦日追記」という前提（T148がまだ未着手でgate待ちであること）自体が
  成立しなくなった。対応不要と判断しチェック完了とする。コード変更なし。

### - [x] T160. 軽微な残骸・記述陳腐化・表記ゆれ4件を解消する 規模S（各項目S）（2026-08-19完了）

- 発端: 統合レビュー統合-8（overall F-4・complexity F-4・consistency F-4・ui P3の統合）。
  (1) 評価軸ラベルが3系統（`axis-catalog.json`/`evaluationAxes.ts`）で不一致
  （例: `stop_density`が「停止密度」/「信号・踏切等」）。意図的な言い換えか同期漏れかは
  コードから判別不能。(2) `registry_defaults.py`のdocstringが、T142が見送った
  transform_fnの動的解決をあたかも実装済みであるかのように記述している。
  (3) `architecture.md:104`の`RouteSegmentDetail`説明が`stop_difficulty`等の現行
  フィールドを欠いたまま（本レビュー対象範囲より前の既存乖離、T154着手のついでに
  修正可）。(4) 研究タブ「共有材料」グループの視覚的インデントが実測3px
  （意図した12pxとの乖離、枠線・見出しテキストで階層は十分伝わるため実害は軽微）。
- 対応方針: (1)は意図的な言い換えであることをコメントで明記するか統一するかを
  ユーザー判断とする。(2)はdocstringを現状（表示カタログ生成専用、コスト関数は
  引き続き手書き）に合わせて修正。(3)はT154の一部として現行フィールドへ更新。
  (4)は修正必須ではないため、気になる場合のみ`margin-left`を増やすかコメントを実態に
  合わせて修正。
- 完了条件: (2)(3)はdocs修正の反映確認。(4)は対応する場合のみPlaywright実機確認。
- 実装メモ（2026-08-19完了）: (1) `evaluationAxes.ts`のPREFERENCE_AXES（stop_weight）が
  実際に使われるのはWeightPanel/ComparisonPanel（研究モードの重み調整UI）のみで、
  axis-catalog.jsonのdisplay.label（地図凡例）は別コンポーネント（axisLayers.ts経由）が
  使うことをgrepで確認（重複用途はなし）。文脈が異なる意図的な言い換えと判断し、統一はせず
  `evaluationAxes.ts`のstop_weight定義へその旨のコメントを追加した（(2)着手方針どおり）。
  (2) `registry_defaults.py`のdocstringを、実際の呼び出し元（`export_openapi.py`と
  テストのみ、アプリ本体は起動時に呼ばない）に合わせて訂正。(3) T154で対応済み
  （改めての作業は無し）。(4) `page.module.css`の`.recipeDependentAxes`の`margin-left`を
  `var(--space-3)`→`var(--space-4)`へ増やし、`.recipeSharedMaterialGroup`のborder+padding
  （実測約9px）を差し引いても視覚的な差が確保されるようにした。dev環境（実データ・DB無し）
  のため実機Playwright確認は行わず、CSS変数値の計算で確認するに留めた。
  backend pytest 815件・frontend vitest 340件・eslint・tsc全green。
  (1)はユーザー判断の記録。

## 地図レイヤー階層の次数反転（2026-08-19・T128/T161/T162の継続検討）

T128（カテゴリ束ね）・T161（ramp軸凡例）・T162（研究タブ整理）の完了後、ユーザーと
グルーピングの基本方針を再検討した結果の起票（T163〜T168）。設計判断の要点:

- **地図の主目的は「要素分解して効いているものを探す」探索**。そのためチップの最上位を
  T128のトピック分類（category）から**情報の次数**（1次=生データ／2次=較正指標）へ反転する。
  トレードオフ（「安全まわりを一通り見たい」ときに観測・推定の2箇所を開く必要が生じる）は
  ユーザー了承済み。サイドバー（MapLayersPanel）はトピック分類（T86）を維持し、
  地図=探索・サイドバー=設定と役割を分ける（協議した案1）。
- **次数の対応はレジストリの排他制約（T137）から属性単位で導出する**。`axis-catalog.json`は
  既に各軸の`inputs`（1次属性ID）をエクスポート済み（T146）のため、フロントは
  「1次属性→表示レイヤー」の小さな対応表を1つ持つだけで、2次→1次（地図の連動ON・材料表示）
  と1次→2次（評価側の組み合わせ要素導出）の**双方向導出**が同じ単一ソースから得られる。
- **命名規則: 1次=事実の名詞（何があるか）、2次=較正指標（どれくらい効くか）**。
  1次と2次がペアで読める（停止要因→停止密度、事故地点→事故密度、標高→勾配）。
  全レイヤー・全属性に正式命名と略名（4文字以下）を1:1で確定済み（下表）。使い分けは
  **地図チップ=略名、サイドバー・研究タブ=正式命名**（`mapLayers.ts`の既存
  `label`/`chipLabel`の使い分けがそのまま実装機構）。
- **道路情報レイヤーは論理分割する**（T165）。1物理レイヤーに2属性（surface・highway）が
  同居したままだと、連動ONが無関係な視覚情報を連れてくる・カタログ機構にN:1の恒久例外が
  残る・命名1:1がUI表層だけになる、の3点で新方針にとって即負債とユーザー協議で判断。
  ただしMapLibreレイヤー2枚への物理分割は同一ジオメトリの上書きで「色×太さ」の多重表現が
  壊れるため不可。**論理レイヤー2つ＋描画は1本の線レイヤーへ合成**（両方ON=現行の
  色×太さ／路面のみ=色分け＋均一太さ／道路種別のみ=中立色＋太さ分け）とする。

確定命名表（2026-08-19ユーザー承認）:

| 種別 | 正式命名 | 略名 | 現行からの変更 |
|---|---|---|---|
| グループ | 観測データ | 観測 | 新設（最上位） |
| グループ | 推定指標（合成） | 推定 | 新設（最上位） |
| 2次 | 勾配 | 勾配 | なし |
| 2次 | 舗装質 | 舗装 | 軸ラベル「路面」→「舗装質」 |
| 2次 | 停止密度 | 停止密度 | なし |
| 2次 | 車の圧迫感 | 圧迫感 | なし |
| 2次 | 夜間 | 夜間 | なし（レイヤーはT145a待ち） |
| 2次 | 事故密度 | 事故密度 | なし |
| 1次 | 道路の種類 | 道路種別 | 「道路情報」太さ軸を昇格（T165で論理分割） |
| 1次 | 路面の種類 | 路面 | 「道路情報」色軸を昇格（同上） |
| 1次 | 車線数 | 車線数 | 新規（レイヤーなし） |
| 1次 | 制限速度 | 制限速度 | 新規（レイヤーなし） |
| 1次 | 自転車インフラ | インフラ | なし |
| 1次 | 指定路線 | 指定路線 | なし |
| 1次 | 街灯 | 街灯 | 新規（レイヤーなし） |
| 1次 | トンネル | トンネル | 新規（レイヤーなし） |
| 1次 | 標高 | 標高 | レイヤー名「標高図」→「標高」 |
| 1次 | 停止要因 | 停止要因 | なし |
| 1次 | 交差点 | 交差点 | 新規（レイヤーなし・T96で表示撤去済みの属性） |
| 1次 | 事故地点 | 事故地点 | チップ「事故」→「事故地点」 |
| 1次 | 補給・休憩ポイント | 補給休憩 | なし（軸外・評価に不使用） |
| 1次 | 自動車通行可否 | 車両可否 | 新規（レイヤーなし・T163のドリフト修正で材料に昇格） |

### - [x] T163. レジストリを1次/2次の命名・材料の単一ソースへ完全化する 規模S〜M（2026-08-19完了）

- 発端: 上記の次数反転検討。導出の正しさはレジストリの`inputs`の完全性に依存するが、
  検討中に**car_stressの実装（carStressExpression.ts・backend traffic.py共、
  「自動車通行不可なら1に固定」）がmotor_vehicle_accessを実際に消費しているのに
  `registry_defaults.py`のinputsに未記載**というドリフトを発見した（排他違反ではない
  〔どの軸も専有していない〕が、inputsが不完全）。また1次属性の正式名は現状レジストリに
  フィールドが無く、フロントが独自に持つと片側import（設計原則2）に反する。
- 対応方針: (1) `PrimaryAttributeSpec`へ表示ラベル（1次の正式名、上表）を追加。
  (2) car_stressの`inputs`へ`motor_vehicle_access`を追加（ドリフト修正）。
  (3) surface_q軸の`display.label`を「路面」→「舗装質」へ改名（1次「路面の種類」との
  紛らわしさ解消。重みラベル「舗装」・レジストリ記述「路面材質」と整合）。
  (4) `export_openapi.py`で`axis-catalog.json`へ`primary_attributes[]`（attr_id・正式名・
  source等）を書き出す。
- 完了条件: axis-catalog.jsonに全1次属性の正式名が含まれ、car_stressのinputsが実装の
  消費材料と一致すること。backend pytest・エクスポート整合テストgreen。
- 実装メモ（2026-08-19完了）: `registry.py`の`PrimaryAttributeSpec`へ`label: str`
  （必須フィールド）を追加し、`registry_defaults.py`の全16一次属性へ確定命名表どおりの
  正式名を設定。car_stress軸の`inputs`へ`motor_vehicle_access`を追加し、
  description・上記の起票メモへ経緯を追記。surface_q軸の`display.label`を
  「路面」→「舗装質」へ改名（axis_id自体・重みラベル「舗装」は変更なし）。
  `export_openapi.py`が`axis-catalog.json`へ`primary_attributes[]`
  （attr_id/label/shared）を書き出すよう拡張。
  検証: 新規回帰テスト2件（`test_car_stress_axis_includes_motor_vehicle_access`・
  `test_all_primary_attributes_have_non_empty_labels`）を`test_registry_defaults.py`へ
  追加。前者は「break→verify→restore」で実際に検知することを確認（`inputs`から
  motor_vehicle_accessを一時的に外して赤化→復元して緑化）。`test_registry.py`の
  テスト用ファクトリ`_attr()`にも`label`を追加（pydantic必須フィールド化に伴う修正）。
  backend pytest 818件（新規2件）・axis-catalog.json再生成後の再実行で差分ゼロ
  （生成の冪等性を確認）。frontend側はAXIS_LABELSがカタログの`display.label`を
  そのまま参照する既存実装のため無改修で「舗装質」へ追従、frontend vitest 346件・
  tsc・eslint全green（既存の「路面」文字列を使うテストはlayer id「road」の
  独立したテスト用ラベルで、軸カタログとは無関係のため影響なし）。

### - [x] T164. フロント一次属性カタログと双方向導出ヘルパーを新設する 規模S（2026-08-19完了）

- 発端: 同上。2次→1次（地図）と1次→2次（評価側）の両方が同じ単一ソースから導出できる
  ことが全体最適の要。
- 対応方針: `primaryAttributes.ts`（新設）に、attr_id→{略名（chipLabel）・
  layerId?（表示レイヤー、無ければundefined）}のUI固有対応表のみを持つ（正式名は
  T163のカタログ経由、片側import）。導出ヘルパー`axisMaterials(axisId)`（2次→1次）・
  `attrConsumers(attrId)`（1次→2次）を提供。
- 完了条件: 「カタログの全inputs属性が対応表に存在する（またはレイヤーなしと明示）」の
  ドリフト検知テストがgreen。frontend vitest・tsc・eslint green。
- 依存: T163。
- 実装メモ（2026-08-19完了）: `frontend/src/components/Map/primaryAttributes.ts`
  （新設）に、`PRIMARY_ATTRIBUTES`（axis-catalog.json: primary_attributes[]をそのまま
  反映）・`PRIMARY_ATTRIBUTE_LABELS`（正式名辞書）・`PRIMARY_ATTRIBUTE_CHIP_LABELS`
  （UI固有の略名、確定命名表どおり全16属性ぶん）・`PRIMARY_ATTRIBUTE_LAYER_IDS`
  （UI固有の表示レイヤー対応、Partial）・`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`
  （レイヤー無しの明示allowlist、8件）を実装。導出関数`axisMaterials(axisId)`・
  `attrConsumers(attrId)`（逆導出）・`axisMaterialLayerIds(axisId)`（材料のうち
  表示レイヤーを持つものだけを重複無しで返す、T167用）を提供。
  highway/surfaceは初期実装時点では「道路情報」レイヤー（road、1レイヤーに2属性同居）を
  暫定的に指す設計にしたが、T165での論理2レイヤー分割（roadType/roadSurface）に合わせて
  この2行を更新済み。
  検証: `primaryAttributes.test.ts`（新規9件）。ドリフト検知2件
  （略名網羅性・4文字以内／表示レイヤー対応表の網羅性〔レイヤー有り・明示的レイヤー無し
  のどちらか片方に必ず属し両方に属さない〕）はbreak→verify→restoreで実際に検知することを
  確認（略名を1件削除→赤化→復元→緑化）。frontend vitest 355件・tsc・eslint全green。

### - [x] T165. 道路情報レイヤーを「道路の種類」「路面の種類」へ論理分割する 規模M（2026-08-19完了）

- 発端: 上記の設計判断（1物理レイヤー2属性の同居は次数反転方針にとって即負債）。
- 対応方針: MapLayerIdを2つ（道路の種類・路面の種類）へ分割し、ON/OFF・凡例・絞り込み
  （roadFilterAxes.tsの色軸/太さ軸を各レイヤーへ分配）・チップ・データ状態を他レイヤーと
  同じ汎用機構に乗せる。**描画は1本のMapLibre線レイヤーに合成**（両方ON=現行の色×太さ／
  路面のみON=色分け＋均一太さ／道路種別のみON=中立色＋太さ分け）。ポップアップの表示
  グループもON状態から導出。localStorageの表示状態は旧`road`キー→両レイヤーへ移行。
  複合名「道路情報」は語彙から廃止（T30で命名に苦労した妥協名の解消）。
- 完了条件: 3状態（両方/片方ずつ）の描画がPlaywright実機確認で意図どおりであること。
  旧設定からの移行で表示状態が失われないこと。frontend全green。
- 依存: なし（T164と並行可）。
- 実装メモ（2026-08-19完了）: `MapLayerId`を`"road"`→`"roadType" | "roadSurface"`へ分割
  （mapLayers.ts）。物理描画は従来どおり1本のMapLibre線レイヤー（`ensureRoadSurfaceTileLayer`）
  のまま、`applyRoadLayerState(map, showRoadSurface, showRoadType, hiddenKeysByAxis)`が
  ON/OFFの組み合わせに応じて`setPaintProperty`で色・太さ・破線を動的に再計算
  （両方OFF=非表示、片方だけON=中立色`#9ca3af`+均一太さ or 色分け+均一太さ、両方ON=
  従来の色×太さ）。roadFilterAxes.tsの色軸/太さ軸は元々独立設計だったため、フィルタ・
  凡例側は「軸ごとに対応するMapLayerIdへ配線し直す」だけで済んだ（`roadFilterAxisLayerId`
  helperをMapLayersPanel.tsxに追加）。`LAYER_DATA_SOURCES`・`ROAD_SURFACE_SHARED_LAYER_IDS`・
  `isRoadSurfaceGroupVisible`は5レイヤー（roadType/roadSurface/carStress/bicycleInfra/
  designation）がすべて同じroad_surfaceタイルを共有する設計を維持しつつ2キー化。地図チップ
  用に`RoadSurfaceIcon`を新設（icons.tsx）、`LAYER_ICONS`をroadType/roadSurfaceの2エントリへ。
  localStorage移行: `useStoredState`のdeserializeで旧`road: boolean`キーを検出したら
  `roadType`/`roadSurface`双方へ複製（page.tsx）。ポップアップ（`buildRoadSurfacePopupHtml`）は
  物理レイヤー（feature.layer.id）ベースで判定しており論理MapLayerIdを直接参照していないため
  変更不要と確認（コード変更なしで完了条件を満たす）。
  発見したテストの問題（2件、いずれも論理分割の正しい副作用）: MapLayersPanel.test.tsxの
  ズーム警告2テストが`roadType`/`roadSurface`両方をtrueにしていたため、各セクションが
  独立に警告を出すようになった結果`getByText`が2件ヒットして失敗。テストの意図（路面軸の
  警告確認）に合わせ`roadSurface: true, roadType: false`の片方だけONへ修正。
  検証: `primaryAttributes.ts`のPRIMARY_ATTRIBUTE_LAYER_IDSをplaceholder値（`"road"`）から
  最終値（`"roadType"`/`"roadSurface"`）へ更新、対応テストも追随。frontend vitest 356件・
  tsc・eslint全green、`next build`成功。Playwright実機確認（バックエンド無しのためタイルは
  読み込めないがUI状態は完全検証可能）: チップ「道路状態」展開で道路種別/路面/指定路線が
  独立3項目として表示、roadType/roadSurfaceを個別にON/OFFしてサイドバーの対応セクション
  ・凡例（太さ軸/色軸それぞれ）が独立して切り替わることを確認。

### - [x] T166. 地図チップ最上位を次数（観測/推定）へ反転し確定命名を適用する 規模M（2026-08-19完了）

- 発端: 上記の次数反転検討の本体。
- 対応方針: チップの最上位グループをT128のcategory束ねから観測データ/推定指標の2トップへ
  変更（T128実装の`buildChipGroups`/`ChipButton`/`groupByDataNature`の骨格は流用し、
  グルーピング関数と見出しを差し替える）。観測グループの展開内はcategoryを小見出しに転用。
  推定グループは6軸を列挙し、専用レイヤーの無い軸（勾配・舗装質・夜間）は薄字＋代役への
  ポインタ（標高・路面の種類レイヤーで確認等）。確定命名表を適用（事故→事故地点、
  標高図→標高、略名/正式名の使い分け統一）。サイドバーはトピック分類のまま変更しない。
- 完了条件: チップが観測/推定の2トップ＋単独（ルート）になり、全名称が確定命名表と
  一致すること。Playwright実機確認。frontend全green。
- 依存: T164・T165。
- 実装メモ（2026-08-19完了）: `MapOverlayControls.tsx`の`buildChipGroups`を、category単位
  （T128）からdataNature単位（観測=`"group:raw"`・推定=`"group:composite"`、改善計画T166）へ
  差し替え。推定グループはcompositeなOverlayLayerChipが0件でも常に出す
  （後述のSECONDARY_AXES薄字項目があるため）。観測グループの▶内容
  （`renderObservedGroupPanel`）はcategoryをそのまま小見出しに転用し、MAP_LAYER_CATEGORY_ORDER
  順に並べる（T128の`groupByDataNature`は用途が無くなったため削除）。推定グループの▶内容
  （`renderEstimatedGroupPanel`）は新設`secondaryAxes.ts`の`SECONDARY_AXES`
  （axis-catalog.jsonの6軸を確定命名表の順で列挙、attr_id→略名・対応MapLayerId・
  レイヤー無し軸の代役案内文のUI固有対応、primaryAttributes.tsと同じ片側import設計）を
  常にすべて列挙し、対応レイヤーを持つ軸（車の圧迫感・停止密度・事故密度）は
  `layers`propから対応するOverlayLayerChipを引いてON/OFFトグル付き行に、専用レイヤーの
  無い軸（勾配・舗装質・夜間）はトグル無しの薄字行（既存の`.detailRowHidden`流用）+
  代役ポインタ文にする。次数グループの正式名/略名は`mapLayers.ts`に追加した
  `MAP_LAYER_DATA_NATURE_CHIP_LABELS`（観測/推定、確定命名表どおり）。代表アイコンは
  新設`ObservedDataIcon`（虫眼鏡）・`EstimatedIndexIcon`（メーター、icons.tsx）。
  `mapLayers.ts`の`category`/`dataNature`フィールドのdocコメントも役割変更
  （category=観測内の小見出しのみ、dataNature=最上位グルーピング）に合わせて更新。
  検証: `MapOverlayControls.test.tsx`の「カテゴリ束ね（T128）」describeブロックを
  「次数束ね（T166）」へ全面書き換え（観測/推定への束ね・観測グループのcategory小見出し・
  推定グループの6軸列挙＋薄字表示・compositeチップ0件でも推定グループが出ることの5テスト）。
  Playwright実機確認: 地図チップ最上位が観測/推定/ルートの3つのみであることを確認、
  観測グループ展開で「道路状態」「交通・安全」等のcategory小見出しが出ることを確認、
  推定グループ展開で6軸（勾配・舗装質・停止密度・車の圧迫感・夜間・事故密度）すべてが
  一覧に出て、レイヤー無し3軸には代役ポインタ文（標高レイヤーで確認できます等）が出ることを
  確認、車の圧迫感トグルのON/OFFが実際に動作することを確認。
  frontend vitest 357件・tsc・eslint全green、`next build`成功。

### - [x] T167. 2次レイヤーONで材料の1次レイヤーを連動ONする 規模S（2026-08-19完了）

- 発端: ユーザー要望「2次のレイヤを表示オンにすると、材料になっている1次のレイヤも
  同時にオンになるのはできない？」。
- 対応方針: `axisMaterials`（T164）から導出したlayerIdを自動ON（既存の「絞り込みを
  操作すると自動でON」と同じ**片方向**パターン。OFFへは連動させない）。推定グループの
  展開UIに材料一覧を表示し、レイヤーの無い材料（車線数・制限速度・交差点・街灯・
  トンネル・自動車通行可否）は薄字で「地図では未表示の材料」として名前だけ出す
  （効いているものを探す目的に対し、見えない材料の存在も正直に見せる）。
- 完了条件: 圧迫感ONで道路の種類・インフラ・指定路線が連動ONすることをPlaywright実機
  確認。frontend全green。
- 依存: T166。
- 実装メモ（2026-08-19完了）: 連動ON自体は`page.tsx`の`handleLayerToggle`に集約
  （`SECONDARY_AXES.find(a => a.layerId === id)`で対象レイヤーIDが推定指標軸かを判定し、
  `axisMaterialLayerIds(axisId)`が返す材料レイヤーを`setLayerVisibility`内で追加でtrueに
  するだけの片方向処理。OFF時は何もしない）。`MapOverlayControls.tsx`はレイヤー固有の
  知識を持たない汎用描画係のままにする方針（ファイル冒頭コメント）を維持し、連動ONの
  判断ロジックはpage.tsx側だけに置いた。材料一覧の表示は`renderMaterialsNote(axisId)`を
  新設し、`axisMaterials`の結果を`PRIMARY_ATTRIBUTE_LAYER_IDS`の有無で「材料:
  （略名を「・」区切り）」「地図では未表示の材料: （略名を「・」区切り）」の2行に分けて
  推定グループの各軸行の下へ出す（`renderMemberRow`にextra引数を追加してレイヤー有り軸へ、
  レイヤー無し軸のダミー行にも直接追加）。
  検証: `MapOverlayControls.test.tsx`へ新規1件（車の圧迫感の材料一覧が
  「材料: 道路種別・インフラ・指定路線」「地図では未表示の材料: 車線数・制限速度・車両可否」に
  分かれること、勾配・夜間でも同様に分かれることを確認）。frontend vitest 358件・tsc・
  eslint全green、`next build`成功。Playwright実機確認: 車の圧迫感ONで道路の種類・
  自転車インフラ・指定路線（いずれもaxisMaterialLayerIds("car_stress")の3レイヤー）が
  連動ONすることを確認、無関係な路面の種類はOFFのままであることを確認、車の圧迫感を
  その後OFFにしても連動先（道路の種類）はONのまま残ること（片方向）を確認。
- **追記（2026-08-22、T181フォローアップで連動ON自体を撤去）**: T181で観測グループの
  メンバーを個別に「表示項目の設定」で非表示にできるようになったことで、非表示にした
  メンバーがこの連動ONで裏からONにされ、かつ非表示設定でチップ自体が隠れているため
  OFFに戻す手段が無い、という不整合を生むようになった（実機フィードバック「自由に
  メンバを表示非表示できることで、裏で表示状態で残るのは避けたい」）。`handleLayerToggle`
  から連動ON処理自体を削除し、単純な`setLayerVisibility`のみへ戻した。代わりに、
  材料一覧の表示（`renderMaterialsNote`、下記実装メモ参照）はON/OFFに関わらずそのまま
  残し、「どの観測データが計算に使われているか」をユーザーが把握する手段として維持する。

### - [x] T168. 評価側へ逆導出を適用する（研究タブの材料一覧・インスペクタのラベル共通化） 規模S〜M（2026-08-19完了）

- 発端: ユーザー指摘「この命名、導出ルールは逆導出すると評価側の組み合わせ要素導出にも
  使えるはず。全体最適になるよう設計して」。
- 対応方針: 研究タブの区間難易度の各軸の重み行の直下へ、`axisMaterials`から導出した
  合成材料一覧（正式命名）を自動表示する（T162で新設した
  `WeightPanel.renderPreferenceFieldExtra`の枠にそのまま乗る）。区間インスペクタ（T146）の
  1次属性ラベルもT163のカタログ正式名へ共通化する。
- 実装メモ（2026-08-19完了）: `lib/evaluationAxes.ts`の`PreferenceAxisDef`へ`axisId?: string`
  （axis-catalog.jsonのaxis_id、windのみレジストリ未登録のため未指定）を追加し、
  区間難易度の重み7軸（elevation/road/wind/stop/car_stress/accident/night）とregistry軸id
  （gradient/surface_q/-/stop_density/car_stress/accident/night）を対応付けた。
  `page.tsx`に`renderAxisMaterialsExtra(axisId)`を新設し、`axisMaterials(axisId)`の結果を
  `PRIMARY_ATTRIBUTE_LABELS`（正式命名、T163カタログ）で「材料: ...」の1行として
  `renderPreferenceFieldExtra`経由でWeightPanelの各重み行へ差し込む（既存の
  car_stress_weight専用レシピ差し込み`renderCarStressRecipeExtra`と併存、他5軸は材料一覧
  のみ）。区間インスペクタ（`axisInspectorPopup.ts`）は、highway専用行と生タグ`tags`
  ループの両方のラベルを`PRIMARY_ATTRIBUTE_LABELS[key] ?? key`へ変更し、レジストリ登録
  済みキー（surface/cycleway/lanes等）は正式名、登録外の生タグ（name/ref等）はそれまで
  どおりraw keyのまま表示するフォールバック設計にした。
  検証: `lib/evaluationAxes.test.ts`（新規、node環境）に軸id対応のドリフト検知2件
  （axisIdを持つ軸は必ずaxis-catalog.jsonに材料を持つこと・wind以外の全軸がaxisIdを持つ
  こと）を追加。前者はbreak→verify→restoreで実際に検知することを確認（elevation_weightの
  axisIdを存在しない軸idへ一時的に書き換え→赤化→復元→緑化）。`axisInspectorPopup.test.ts`
  へ2件追加（highway/surfaceの正式名反映を確認する行、および登録外の生タグ`name`は
  raw keyのまま出ることを確認する新規テスト）。frontend vitest 362件・tsc・eslint全green、
  `next build`成功。Playwright実機確認（研究モードON+全`<details>`強制展開）:
  区間難易度の重み6軸すべて（勾配・舗装・信号踏切等・車の圧迫感・事故・夜間）の直下に
  対応する材料一覧（例: 車の圧迫感→「材料: 道路の種類・車線数・制限速度・自転車インフラ・
  指定路線・自動車通行可否」、風は対応するaxisIdが無いため材料行なし）が正しく表示される
  ことを確認。区間インスペクタ自体はバックエンド無しの環境のため実機確認できず、
  unitテスト（上記2件）でカバー。
- 完了条件: 軸のinputs変更がレジストリ登録のみで研究タブ・インスペクタへ自動反映される
  こと。frontend全green。
- 依存: T164（T165・T166と独立に着手可）。

### - [x] T169. 地図チップ観測/推定グループのタイル化・マトリックス化 規模M（2026-08-19完了）

- 発端: ユーザー指摘「観測・推定の2つにまとまったのは良いが、展開した時にみにくい。
  マトリックスイメージにできない？観測アイコンは▼で下展開すると道路種別・路面・指定路線等が
  縦に並ぶ、推定アイコンは▶で右展開すると勾配・舗装質・停止密度等が横に並ぶようにしたい」。
  1回目の対応（グループ単位の展開方向を▼/▶に分けるだけ）を実装したところ、ユーザーから
  再指摘「イメージと違う。1次要素、2次要素すべて『推定』アイコンと同様の四角タイルアイコンに
  して。その上で、推定▶ 勾配 舗装質 停止密度／観測▼ 道路種別 路面 指定路線 のように配置。
  勾配や舗装質等には▼が付随していてクリックすると凡例を下に展開、道路種別や路面には▶が
  付随していてクリックすると凡例を右に展開」という、より具体的な配置指定を受け、設計を
  作り直した（本エントリは最終形のみを記録する）。
- 対応方針: T166の観測/推定2トップ構成・グループ単位の展開方向（観測=▼縦積み、推定=▶横並び）
  はそのまま、内訳をさらに一段タイル化する。観測・推定のメンバー（一次属性の個別レイヤー、
  二次軸）を全て「アイコン+略名の四角タイル」（地図チップ本体・旧`推定`セルと同じ見た目）に
  統一し、タイルごとに独立した凡例展開ボタンを持たせる。展開方向はグループ本体の並び方向と
  直交させる（観測は▼縦積みなのでメンバーは▶で右展開、推定は▶横並びなので軸は▼で下展開）。
  地図チップ本体・グループ・メンバーの3階層すべてで同じ「タイル+隣接する展開トグル+
  展開パネル」という1つの部品（`ChipButton`）を再帰的に使い回す。
- 完了条件: 観測・推定のメンバー/軸すべてが同じ四角タイルの見た目になり、観測メンバーは▶・
  推定軸は▼で個別に凡例を展開できることをPlaywright実機確認。frontend全green。
- 依存: T166・T167。
- 実装メモ（2026-08-19完了）: 1回目の実装で`ChipButton`へ追加した`expandDirection: "right" |
  "down"`（既定"right"、"down"は`.chipRowItem`内の通常フローへインライン展開、"right"は
  document.bodyへポータルしてposition: fixedで右に浮かせる）はそのまま活用し、これを
  グループ単位だけでなくメンバー/軸単位にも適用する形へ発展させた。
  観測グループの内訳（`renderObservedGroupPanel`）は、category小見出しの下へ
  `renderRawMemberTile`が返す`ChipButton`（`expandDirection="right"`、ONかつ凡例を持つ
  メンバーのみ展開ボタンが付く）を`.memberColumn`（縦積みのflexコンテナ）で並べる。
  推定グループの内訳（`renderEstimatedGroupPanel`）は、`renderAxisTile`が返す`ChipButton`
  （`expandDirection="down"`）を`.matrixRow`（横並び・折り返しのflexコンテナ）で並べる。
  専用レイヤーを持つ軸はON/OFFタイル、持たない軸（勾配・舗装質・夜間）は`disabled`＋
  proxyHint/材料一覧のみ展開可能な情報タイルにする（`ChipButton`の`disabled`はタップ用の
  本体ボタンだけを無効化し、展開トグル自体は`canExpand`で独立制御できるため、既存部品の
  組み合わせだけで実現できた）。材料一覧（T167）はON/OFFに関わらず確認したい情報のため
  `canExpand`へ含め、色の凡例は実際に地図へ描画されているときだけ（ON時）含めた。
  旧`.matrixCell`/`.matrixCellActive`/`.matrixCellInfo`（生の`<button>`/`<div>`で組んだ
  簡易タイル）と旧`renderMemberRow`（`LayerChip`ベースの丸ピル表示）は`ChipButton`の再利用に
  置き換えたため削除、`LayerChip`のimportも不要になったため削除。`.memberRow`/
  `.memberLegend`（旧ピル行専用）を削除し`.memberColumn`（新設、縦積みコンテナ）を追加、
  `.matrixRow`は並び方向の定義だけを残し中身のタイルの見た目は`ChipButton`側の
  `.iconChip`/`.iconChipActive`に委ねる形へ整理した。`renderMaterialsNote`の戻り値は
  タイルの展開パネル内に直接差し込む前提になったため、専用の`.memberLegend`ラッパーdivを
  やめてFragmentを返すよう変更。副次的に、メンバー/軸タイルの`isExpanded`をグループ単位の
  単独チップ（route等）と同じく`canExpand && expandedIds.has(key)`でガードする修正も
  行った（凡例を開いた状態のレイヤーをOFFにするとcanExpandがfalseになり展開トグル自体が
  消えるため、ガードが無いと空のパネルが開いたまま二度と閉じられなくなる不具合があった。
  実装中に自己点検で発見し、単独チップと同じ既存パターンへ揃えて解消）。
  検証: `MapOverlayControls.test.tsx`の「次数束ね（改善計画T166）」describeを新設計に
  合わせて更新（推定グループの6軸がすべてタイルとして並び専用レイヤーの無い軸はdisabledに
  なること、タイル個別の▼/▶展開ボタンを押して初めて凡例・代役案内・材料一覧が見えること、
  観測グループのメンバータイルにも同様に▶展開ボタンが付くことを新規1件で確認、既存の
  「観測グループを開くと…」「いずれかのメンバーがON…」等は無改修のまま全green）。
  frontend vitest 363件（1件純増）・tsc（既存の`layout.tsx`のLayoutProps型エラーは
  `next build`前のみに出る無関係な既知事象、変更前から発生することを`git stash`で確認済み）・
  eslint全green、`next build`成功。Playwright実機確認（一時プレビューページ経由、確認後
  削除）: 観測グループを開くと道路種別・路面・指定路線等が四角タイルとして縦に並び、
  路面タイル横の▶を押すと右へ凡例（アスファルト・砂利の色スウォッチ）が展開されること、
  推定グループを開くと勾配・舗装質・停止密度・圧迫感・夜間・事故密度が同じ四角タイルとして
  横に並び（車の圧迫感等ONのタイルは青くハイライト、専用レイヤーの無い軸は薄いグレーで
  タップ不能）、勾配タイル下の▼を押すと下へ「標高レイヤーで確認できます」「材料: 標高」が
  展開されることを確認。

---

## 動的要素（風・降雨等）の導入（2026-08-20・調査起票）

これまでの評価・地図表示は静的な要素（OSM属性・警察庁統計・国土数値情報等、地域に固定で
時間によって変わらないデータ）を中心に扱ってきた。ユーザー要望「風、降雨等の動的な要素を
扱いたい。ロードバイク走行に関わる動的要素と、その評価に利用可能なオープンデータ案を
洗い出して」「動的な要素を、時刻指定してマップに描画することはできないか検討して」を受け、
調査結果（2026-08-20実施、外部データソース選定はT50〜T54と同じ「調査→意思決定→実装」の
段階方式）をタスク分割して起票する。

**既存の資産（前提）**: Open-Meteo連携は導入済み（`weather_client.py`: 気温・風速・風向・
降水確率、TTLキャッシュ・429リトライ・マルチロケーション集約済み）。風は評価軸
（wind_weight）として稼働中で、`wind_service.py`が「区間の推定到達時刻×地点」で時間別予報を
引く仕組みを持つ。つまり「動的要素×到達時刻」の評価パイプラインの骨格は既にあり、以下の
多くはこの1本道へ載せられる。`mapLayers.ts`のkind="dynamic"（現状route1種のみ）も
動的レイヤーの受け皿として既にある。

**設計判断（全タスク共通）**:
- 評価軸（2次）へ組み込むか、警告・情報表示に留めるかを要素ごとに明示する。雷・冠水の
  ような「回避一択」の危険は評価の重み付けになじまない（重みを下げれば通ってよい、という
  意味になってしまう）ため警告表示とし、風・降水・暑さのような「程度の問題」だけを
  評価軸候補とする。
- 動的データは鮮度・提供時間帯・欠測がつきもののため、取得失敗・提供期間外を既存の
  レイヤーデータ状態機構（T87: loading/empty/error）へ正直に載せる。
- 出典・利用規約: 気象庁bosai系JSONは公式サポートの無い内部APIで仕様変更リスクがある
  （政府標準利用規約準拠・出典明記で利用可）。Open-Meteoは非商用無料・キー不要。
  各タスクの実装前に規約を再確認する。
- **気象庁とOpen-Meteoの使い分け**（ユーザー確認「気象庁とopenmeteoの使い分けを整理して」を
  受け明文化、2026-08-20実機検証）。両者は競合ではなく用途が分かれる:
  - **地点ベースの評価計算（区間の到達時刻×任意座標）は常にOpen-Meteo**。気象庁の予報JSONは
    行政区画コード単位の配信で任意座標を直接引けないため、地点値が要る評価計算には使えない。
    Open-Meteoは緯度経度を直接渡せるREST/JSONで、キャッシュ・429リトライ等の運用資産も
    既に構築済み。既存のwind評価・T172の拡張パラメータはこちら
  - **短時間・高解像度の面的可視化（降水・雷の直近ナウキャスト）は気象庁直接**。JMAナウ
    キャストタイル（250m〜1km・5〜10分毎）に相当する解像度・鮮度はOpen-Meteo経由では
    手に入らない（後述のjma_msm空間データは1時間刻み・約5km）。T171はこちら
  - **格子状の面的データをMapLibreへ描画する用途（風のベクトル場等）はOpen-Meteo経由で
    JMAモデルを取得**。気象庁自身はMSM等の数値予報生データをGRIB2形式でのみ配信しており
    Webタイル/ベクタとして直接消費できない。Open-MeteoがGRIB2を取り込みOMfiles形式へ
    変換・CDN配信しているため（`https://openmeteo-data-spatial.b-cdn.net/jma_msm/
    latest.json`で実在確認済み、日本域BBOX・wind_u/v_component_10m含む）、「JMAの
    モデル精度」と「Web消費しやすい形式」を両立できるのはこの経路のみ。T178はこちら
    （**データの出所は気象庁（JMA MSM）、配信経路はOpen-Meteo**という点に注意。地図に
    「Open-Meteo」とだけ出典表示すると出所が伝わらないため、出典表記はT178実装時に
    「気象庁の予測に基づく（Open-Meteo経由）」のように両方明記する）
  - **他省庁のデータは気象庁・Open-Meteoどちらでもない別系統**として扱う（T174の環境省
    WBGT、T176/T177の国交省河川水位・交通量）
  - **`models=jma_seamless`指定は不採用（2026-08-20実測で判明、T172着手時に検証）**:
    「地図に描いている風」と「ルート評価に使っている風」のモデルを揃える目的で
    `models=jma_seamless`を評価側にも指定することを一度検討したが、実機検証の結果
    **JMAモデルは`wind_gusts_10m`・`precipitation_probability`・`uv_index`を提供せず、
    指定するとこれらが全時刻nullになる**ことを確認した（`apparent_temperature`・
    `precipitation`は提供される）。`precipitation_probability`は既存のwind評価が
    既に使っているフィールドで、これがnull化するとT172で追加する突風・UV指数も
    含め軒並み欠測になり本末転倒のため、**地点ベース評価はデフォルトモデル
    （`best_match`、変数ごとに提供元がある最良のモデルを自動選択）のまま変更しない**。
    「地図（T178、JMA MSM由来）と評価（Open-Meteo REST、best_match由来）でモデルが
    異なる」こと自体は残るが、両者は目的が異なる（地図は面的な風の分布を見る、評価は
    ルート選定の材料にする）ため実害は小さいと判断し、モデル統一は見送る。

**実施順序（優先順位、2026-08-20整理。ユーザー要望「改善計画の中で優先順位付けをし、
整理して」を受け明文化）**: T170〜T178は互いに独立ではなく、依存関係・ユーザーの
関心の強さ・コストの3軸で優先度に差がある。番号順ではなく以下のPhase順で着手する。
**2026-08-20時点、Phase 1（T172→T170→T171→T178）・Phase 2（T173）は全て完了済み。次に着手するならPhase 3（T174）。**

- **Phase 1（風・雨・雷、ユーザーが繰り返し名指しした最優先領域）**: T172 → T170 →
  T171 → T178 の順。T172は依存が無くいつでも着手できる最小コスト（規模S）のため最初に
  済ませる（`models=jma_seamless`の指定は実機検証の結果不採用と確定済み、上記
  「設計判断」参照。地点評価は既定モデルのままでよい）。
  T170（時刻指定描画基盤）はT171・T178が共通して必要とする土台のため必ず先に完成させる。
  T171（雨雷ナウキャスト）はタイルURL構造を実機確認済みで設計の不確実性が低く、
  T178（風のベクトル場）はライブラリ選定は完了したがGPLv2の扱い・プレ1.0のAPI変更
  リスクが残るため、確実性の高いT171を先に済ませてからT178へ進む
- **Phase 2（低コスト・独立、Phase 1の合間にやる価値が高い）**: T173（日没×night軸の
  動的化）。外部API不要・既存の到達時刻計算に乗るだけで規模S〜Mと軽く、Phase 1と依存も
  競合もしないため並行して着手してよい
- **Phase 3（季節限定・着手時期に制約）**: T174（夏季WBGT警告）。提供期間が4〜10月の
  ため、他のPhaseと違い「今すぐ着手する理由」が季節に左右される。シーズン開始前
  （毎年4月）に間に合わせたいなら優先度を上げる、そうでなければPhase 1後でよい
- **Phase 4（調査のみ、実装可否は調査後に判断。トリガー未到達の実装を「ついでに」
  やらない、設計原則10と同じ考え方）**: T175（花粉）・T176（河川敷冠水）・T177
  （交通量時間帯補正）。3件とも規模はS〜Mだが「調査した結果、見送り」も正当な結論
  （T50〜T54のJICE見送りが前例）であり、Phase 1〜3の実装が固まってから着手する
  （調査だけ先行させても、Phase 1〜3の設計変更で調査結果の前提が崩れるリスクがある）

### - [x] T170. 時刻指定の動的レイヤー描画基盤（時刻セレクタ＋時刻パラメータ付きレイヤー） 規模M（2026-08-20完了）

- 発端: ユーザー要望「動的な要素を、時刻指定してマップに描画することはできないか検討して」。
  検討結果: **可能**。動的レイヤーの多くは「基準時刻＋対象時刻」でURL・クエリが決まる
  （降水ナウキャストのタイルは時刻パラメータ付きPNGタイル、Open-Meteoのhourlyは時刻で
  引くだけ）ため、地図側に「表示対象時刻」という横断的な状態を1つ持たせれば、個々の
  動的レイヤーはそれを購読してURLや式を差し替えるだけで時刻指定描画になる。
- 対応方針: `page.tsx`へ表示対象時刻の状態（`mapTargetTime`、既定=現在時刻。現在からの
  オフセット分で持ち、リロード時に古い絶対時刻が残らないようにする）を新設し、MapViewへ
  propsで渡す（`redrawPropsRef`パターンの追従箇所一式を含む）。UIは時刻スライダー
  （例: -3h〜+15h、データソースの提供範囲に応じて動的レイヤー側が可動域を宣言する）を
  時刻依存レイヤーが1つ以上ONのときだけ地図上へ出す（地図の視界を圧迫しない、設計原則12）。
  動的レイヤーのカタログ表現は`mapLayers.ts`のkind="dynamic"を使い、地図チップの
  グルーピング（観測/推定の2トップに対し第3グループ「動的」を追加するか、観測へ含めるか）は
  実装時にユーザーへ確認して決める。ルート評価側の`start_time`（出発時刻）とは独立した
  状態とする（地図の閲覧時刻とルート出発時刻は目的が異なる。将来「スライダーの時刻を
  出発時刻に使う」導線を足すのは自由）。
- 完了条件: 時刻セレクタの状態がMapViewへ届き、最初の時刻依存レイヤー（T171の
  ナウキャスト想定）がスライダー操作で表示時刻を切り替えられること。時刻依存レイヤーが
  全てOFFのときセレクタが出ないこと。Playwright実機確認・frontend全green。
- 依存: なし（ただし単体では見た目の変化が無いため、T171と同時着手が現実的）。
- 実装メモ（2026-08-20完了、T171と同時実装）: 動的レイヤーのグルーピングは、ユーザーへ
  確認のうえ**新しい第3グループ「動的」を新設**（観測/推定の2トップに並列。理由:
  観測/推定はどちらも「今この瞬間の事実・推定値」だが、動的レイヤーは「時刻を選ぶと
  内容が変わる」という質的に異なる性質を持つため）。`mapLayers.ts`の
  `MapLayerDataNature`へ`"dynamic"`を追加（`raw`/`composite`に続く3値目、
  `MAP_LAYER_DATA_NATURE_ORDER`は末尾に配置）。`MapOverlayControls.tsx`の
  `buildChipGroups`へ`group:dynamic`分岐を追加（`group:raw`と全く同じ「▼縦積み・
  地続き展開」の構成、`renderObservedMemberRows`等の既存汎用関数をそのまま再利用）。
  `MapLayersPanel.tsx`は`MAP_LAYER_DATA_NATURE_ORDER`をループする既存の汎用分岐が
  そのまま拾うため個別対応不要（新設カテゴリ`weather`を`MapLayerCategory`へ追加した
  だけで「動的データ」見出しの中に降水ナウキャストのセクションが現れる）。
  時刻対象時刻の状態自体は`page.tsx`が`nowcastFrameIndex`として保持し（framesの配列
  index方式。任意の連続時刻ではなく「実際に存在するフレームのどれか」を指す方が
  ズレなく正確なため、値を分単位オフセットではなくindexにした点が対応方針からの変更）、
  `MapView.tsx`へは計算済みの`precipitationNowcastTileUrl`（string | undefined）と
  `showPrecipitationNowcast`（boolean）だけをpropsで渡す（`redrawPropsRef`の6箇所
  すべてに追従済み）。時刻スライダーUI（`NowcastTimeSlider`コンポーネント、新設）は
  地図下部中央に浮かせ、`showPrecipitationNowcast`がtrueの間だけ`page.tsx`が
  マウントする。frontend vitest 392件（新規17件）・tsc全green。Playwright実機確認:
  「動的」チップ→「降水」チップの順にONにすると地図下部にスライダーが現れ
  （初期表示は最新の実況フレーム）、スライダー操作で`map.getSource(...).tiles`が
  実際に別のbasetime/validtimeへ切り替わり新しいタイルへの実ネットワークリクエストが
  発生することを確認。

### - [x] T171. 気象庁降水ナウキャストのラスタタイルレイヤーを追加する 規模M（2026-08-20完了）

- 背景: 現状の降水情報は「降水確率」（Open-Meteo、地点値）のみで、雨雲の空間分布が
  見えない。「出発直前に雨雲の位置と動きを見て回避する」はサイクリストの実用価値が
  最も高い動的表示。気象庁の高解像度降水ナウキャストは時刻パラメータ付きPNGタイルとして
  配信されており、GSI色別標高図（`ensureGsiReliefLayer`）と同じraster sourceパターンで
  重ねられる。
- 実機調査で確認したタイル構造（2026-08-20、雨・雷の時刻指定描画を明確化する検討時）:
  - 時刻一覧: `https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json`（実況、
    5分毎更新・basetime=validtime）／`targetTimes_N2.json`（60分先予測、同一basetimeに
    対し5分刻みでvalidtimeが並ぶ）。「現在時刻から先読みで時刻を計算せず、必ずこの
    一覧を参照する」ことが気象庁側の注記としてある（先読み計算だとズレる）
  - タイルURL: `https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/
    {validtime}/surf/hrpns/{z}/{x}/{y}.png`（ズーム4〜10、無降水域は透明PNG）。**訂正
    （2026-08-20実装時）**: 検討時点では`bosai/himawari/data/nowc/...`という誤ったパスを
    把握していた（実在するAPIの通信を直接見ずAI要約経由で調べたための誤り）。実装着手時に
    Playwrightで`https://www.jma.go.jp/bosai/nowc/`の実際のネットワーク要求を観測し、
    正しくは`bosai/jmatile/data/nowc/...`であることを確認・修正した（curlで200 image/png
    を確認済み）
  - `{basetime}`/`{validtime}`は`YYYYMMDDHHmmss`（UTC）
  - 雷ナウキャスト（活動度1〜4、10分毎更新）も同じ`bosai/nowc`のタイル配信系にあるが、
    プロダクトコード（`hrpns`に相当する部分）は本タスクでは未着手のまま。降水のみ実装した
    （T171完了条件は降水ナウキャストのみを対象とし、雷は別レイヤー・別調査として残す）
- 対応方針: 基準時刻一覧（targetTimes JSON）を取得→スライダーの対象時刻に最も近い
  validtimeのタイルURLを組み立て→raster sourceを差し替える（MapLibreのsetTiles）。
  kind="dynamic"レイヤーとして`mapLayers.ts`へ追加。不透明度は標高図と同様に半透明固定。
  出典明記（気象庁）を地図のattributionへ追加。bosai系は非公式APIのため、タイルURL構造の
  仕様変更検知（取得失敗をT87のerror状態へ落とす）を必ず入れる。雷ナウキャストは同じ
  仕組みに載る見込みだが、上記のとおりプロダクトコード未確認のため着手時に別途調査が
  要る（別レイヤー・警告表示扱い）。
- 完了条件: 降水ナウキャストがONのとき雨雲の分布が地図に重なり、T170のスライダーで
  実況〜予測を時刻切り替えできること。タイル取得失敗時にT87のエラー案内が出ること。
  Playwright実機確認・frontend全green。
- 依存: T170。
- 実装メモ（2026-08-20完了、T170と同時実装）: `precipitationNowcast.ts`（新設）を
  データ層として切り出し、DOM/MapLibreを一切知らない純粋関数だけを持たせた
  （`fetchNowcastFrames`: N1/N2を1つのvalidtime昇順の時系列へ束ねる。片方だけ失敗しても
  部分的な結果を返す〔`Promise.allSettled`〕、両方失敗のときだけ例外。
  `latestObservedFrameIndex`: スライダーの初期位置＝直近の実況フレーム。
  `nowcastTileUrlTemplate`: basetime/validtimeを埋め込みつつ`{z}/{x}/{y}`はMapLibreの
  プレースホルダとして残す）。`MapView.tsx`は`ensurePrecipitationNowcastLayer`
  （GSI標高ラスタと同型、初期化時に一度だけraster source/layer追加）と
  `applyPrecipitationNowcastState`（visible/tileUrlの両方が揃って初めて表示、
  片方でも欠けていれば非表示のまま＝フェッチ未完了中に古いタイルが一瞬見えるのを防ぐ）の
  2関数で完結させ、`STATIC_OVERLAY_LAYERS`の汎用ループには含めなかった（tileUrlという
  可変引数を持つ点が他の静的レイヤーと異なるため、`applyRoadLayerState`等と同じ
  「専用のapply関数」パターンにした）。T87（レイヤーデータ状態）は`LAYER_DATA_SOURCES`へ
  elevationと同型（sourceLayer無し、ラスタのため取得失敗のみ検知）で登録するだけで
  自動的に効いた。`page.tsx`はframes配列を`layerVisibility.precipitationNowcast`が
  trueの間だけ5分毎（実況の更新間隔）に再取得し、スライダー位置（`nowcastFrameIndex`、
  配列index方式）はユーザーが予測側を見ている間に定期再取得で実況へ引き戻されないよう
  「初回取得時、またはindexが新しいframes配列の範囲外になったときだけ」最新実況へ
  合わせる。CORSは事前にPlaywrightで検証済み（targetTimes JSONのfetch・PNGタイルの
  MapLibre raster source読み込みともにCORSヘッダ無しで問題なく動作、`Access-Control-
  Allow-Origin`は不要と判明）。出典表示は`addSource`の`attribution: "気象庁"`で対応。
  frontend vitest 392件（T170の実装メモの数値と同一、両タスクを同時実装したため）・
  tsc全green。Playwright実機確認: 降水ナウキャストON→地図下部にスライダー表示、
  `map.getSource("region-precipitation-nowcast").tiles`がスライダー操作で実際に別の
  basetime/validtimeへ切り替わり、新しいタイルへの実ネットワークリクエスト（7件、
  `hrpns`を含むURL）が発生することを確認。

### - [x] T172. Open-Meteo取得パラメータの拡張（突風・降水量・UV・体感温度） 規模S（2026-08-20完了）

- 背景: 既存の`weather_client.py`はcurrent/hourlyとも`temperature_2m,wind_speed_10m,
  wind_direction_10m(,precipitation_probability)`のみ。ロードバイク走行では平均風速より
  突風（橋上・河川敷の横風）、降水確率より降水量（mm/h、小雨か土砂降りか）が効く。
  UV指数・体感温度（apparent_temperature）も同じ呼び出しで取れる。
- 対応方針: 取得パラメータへ`wind_gusts_10m,precipitation,uv_index,apparent_temperature`を
  追加し、`WeatherConditions`（domain/weather.py）と天候表示UIへ露出する。評価への
  組み込みは本タスクではしない（風軸の突風考慮・降水の評価軸化はデータが取れてから
  別タスクで判断する、1タスク=1関心事）。既存のキャッシュキー・TTL・429対策は変更しない。
  `models=jma_seamless`は指定しない（上記「設計判断」参照。実機検証の結果、JMAモデルが
  `wind_gusts_10m`・`precipitation_probability`・`uv_index`を提供せず、指定すると本タスクで
  追加する値も既存の降水確率も軒並みnull化することが判明したため不採用と確定済み）。
  既定モデル（`best_match`）のまま追加パラメータのみ増やす。
- 完了条件: 天候表示に突風・降水量・UV・体感温度が出ること。backend/frontend全green。
- 依存: なし。
- 実装メモ（2026-08-20完了）: `weather_client.py`のcurrent/hourly両方（`get_forecast`・
  `get_forecast_many`の2箇所）へ`wind_gusts_10m,precipitation,apparent_temperature,
  uv_index`を追加。`WeatherConditions`（domain/weather.py）へ`apparent_temperature_c`・
  `wind_gusts_ms`・`precipitation_mm`・`uv_index`（いずれも`float | None`）を追加し、
  `weather_service.py`の`_conditions_from_data`で`current`直下（atがNoneの現在天候）と
  `hourly`のindex参照（atが未来時刻の予報）の両方から埋める新ヘルパー
  `_hourly_index_value`を追加（既存の`_hourly_value_near`は最近傍時刻探索用で今回は
  index確定済みのため別ヘルパーにした）。フィールド欠落時（新パラメータ追加前のstale
  cache等）はNoneへ倒す既存方針を踏襲し、専用テストで確認。OpenAPIスキーマ・
  frontend api.d.tsを再生成。`WeatherPanel.tsx`へ体感温度（気温に括弧書き併記）・
  突風（風速に括弧書き併記）・降水量mm/h（確率と併記、確率が無くても単独表示可）・
  UV指数（新規チップ、`SunIcon`追加）を表示。backend pytest 918件・frontend
  vitest 375件（新規11件）・tsc全green。実機（Playwright）で天候表示に
  「30.2℃(体感35.4)｜南東の風0.9 m/s(突風6.9)｜0%(0.0mm/h)｜UV 7.3」が
  表示されることを確認。

### - [x] T173. 日没×night軸の動的化（到達時刻が日没後の区間だけ夜間軸を効かせる） 規模S〜M（2026-08-20完了）

- 背景: night軸（街灯・トンネル、T139）は静的な「暗いときに危ない場所」の評価で、
  既定重み0（夜間ライド時に手動で上げる想定）。一方、区間ごとの推定到達時刻は
  `wind_service.py`が既に計算している。日没・薄暮の時刻は外部APIなしでクライアント/
  バックエンドの天文計算（緯度経度＋日付から決定論的に求まる。国立天文台の暦計算と同じ
  理屈で、ライブラリまたは数十行の実装）で得られるため、「到達時刻が日没後の区間だけ
  night軸の難易度を有効化する」という動的スイッチが外部データ不要で実装できる。
- 対応方針: 日没時刻計算をdomain純関数として追加（出典不要の天文計算。市民薄明の
  開始/終了を境界に使う）。`compute_edge_cost`相当の合成時にnight軸へ「到達時刻が
  薄暮以降なら1、日中なら0」の係数を掛ける（重み自体はユーザー設定のまま、係数は
  レジストリの軸内パラメータとして宣言する）。地図表示側は、T170のスライダー時刻が
  日没後のときnight軸レイヤー（T145a未実装のため当面はcar_stress等と同様の扱い）を
  強調する等の連動を検討するが、本タスクの完了条件には含めない（レイヤー自体がT145a
  トリガー待ちのため）。
- 完了条件: 同じルートでも出発時刻により夜間区間のdifficultyが変わることをテストで確認。
  日没計算の妥当性を既知の暦（国立天文台の公表値数点）と突き合わせるテストを持つ。
  backend全green。
- 依存: なし（T170とは独立。ルート評価側の話のため）。
- 実装メモ（2026-08-20完了）: 着手前の調査で、対応方針の前提が実装と2点食い違っていることが
  判明し、方針を修正した。(1) 「レジストリの軸内パラメータとして宣言する」は不採用。
  `registry_defaults.py`のAxisSpecはコスト計算（`compute_edge_axis_scores`/
  `evaluate_axis_difficulties`）から一切参照されない表示専用のレジストリ（設計判断は
  registry_defaults.pyのモジュールdocstring参照）と判明したため、night_weightそのものを
  呼び出し側で0/そのままに掛け替える方式にした（`night_difficulty`自体はlit/tunnelタグ
  のみに基づく時刻非依存の値のまま据え置き、domain/night.py・difficulty.pyの変更は
  不要だった）。(2) 「`wind_service.py`の到達時刻計算がnight軸でも再利用できる」は
  エンジンによって事情が異なると判明: 既定エンジン（`OpenRouteServiceEngine`、
  routing_engine="openrouteservice"）は経路確定後にopenrouteservice APIの結果を評価する
  設計のため、区間ごとの推定到達時刻（`wind_penalty`と同じ`arrival_time`）がそのまま
  使え、対応方針どおりの区間単位の動的化を実装できた。一方`RoadGraphEngine`（試験実装、
  既定ではない）はDijkstra探索用のEdge Costを`prepare()`内で経路確定前に一括構築するため
  （モジュールdocstring「風は出発時点の起点付近の風をルート全体に一様適用する」と同じ
  制約）、night軸も同じ簡略化（起点1点の時刻でルート全体に一様適用）にせざるを得なかった
  （プレ既存の`prepare(origin, radius_km)`にwindと同じ非依存の`get_conditions(origin)`
  パターンを踏襲）。またこのアプリには「出発時刻」というユーザー入力自体が現状無く
  （`route_generator.py`は常に`datetime.now(JST)`を使う）、動的化の効果は将来ユーザーが
  出発時刻を選べるようになったときに活きる（現状はテストでしか出発時刻を差し替えられない）。
  天文計算は`astral`（MIT、requirements.txtへ`astral==3.2`追加）に委譲する
  `domain/twilight.py`（新設）の`is_night(coordinates, at)`のみを追加。実装中に
  「`astral.sun(date=D)`は経度が東側だと同じdate引数のdawn/duskが別々の現地日を指し
  時刻順が入れ替わって返る」という罠を実機（Python REPL）で発見し、`at`前後数日分の
  dawn/duskイベントを単純にUTC時刻でソートし直前のイベント種別で判定する頑健な実装にした
  （日付境界を経度に応じて個別処理しない、地域非依存の解法）。妥当性はNAOJ（国立天文台）
  サイトが接続不可（TLSハンドシェイクでリセット）だったため、代わりにsunrise-sunset.org
  （NOAA準拠の公開API、無料・キー不要）の実測値と突き合わせた（東京の夏至・冬至・秋分、
  `test_twilight.py`）。`OpenRouteServiceEngine`は`evaluate_loops`内の区間ループで
  `is_night(points[i], arrival_time)`により`night_weight`を掛け替え、`RoadGraphEngine`は
  `prepare()`に`now`引数（省略時は実際の現在時刻、テストが注入できるよう追加）を足し
  `is_night(origin, now)`の結果を`RoutePreference.model_copy(update={"night_weight": 0.0})`
  で探索用・表示用（`_build_segment_details`）の両方へ反映した（`EvaluationService.
  evaluate_graph`に`preference`オーバーライド引数を追加、`self._preference`を直接
  書き換えるとリクエスト間で共有される状態を汚染するため）。backend pytest 928件
  （新規10件: test_twilight.py 7件・test_road_graph_engine.py 2件・
  test_openrouteservice_engine.py 1件）全green。

### - [x] T174. 夏季の暑さ指数（WBGT）警告表示 規模S〜M（2026-08-22完了）

- 背景: 環境省熱中症予防情報サイトが全国の暑さ指数（WBGT）の予測値・実況値をCSV/WebAPIで
  無料提供している（4〜10月のみ）。熱中症はロングライドの主要リスクで、補給・休憩POI
  レイヤー（T101）と併用価値が高い。
- 対応方針: 出発地点近傍のWBGT予測を取得し、警戒レベル（環境省の5段階）に応じて
  ルート生成画面・天候表示へ警告バッジを出す（評価軸にはしない: 暑さは「ルートを変えれば
  避けられる」ものではなく行動判断・補給計画の問題のため）。提供期間外（11〜3月）は
  取得自体を行わずUIにも出さない。地点マッピング（WBGT提供地点→出発地点の近傍検索）が
  必要な点が規模を左右するため、実装前に提供データの地点粒度を確認する。
- 完了条件: 夏季にWBGT警戒レベルが表示され、提供期間外は何も出ないこと。取得失敗時は
  警告なし（安全側でない点に注意書きを添える）。backend/frontend全green。
- 依存: なし。
- 実装内容:
  - **WebAPI仕様の確定**: 環境省サイトの`man15NH/wbgt_data_api_service_manual.pdf`
    （2026-08-22取得）で正式なJSON WebAPI（`GET https://www.wbgt.env.go.jp/api/v1/
    getForecastData`）を確認。地点別予測値は3時間刻みで翌々日まで取得できる。
    `forecast_val`は暑さ指数を10倍した整数文字列（実機確認: "280"→28.0）。
  - **地点マッピング**: 情報提供地点マスタ（`man15NH/wbgt_point_master-{日付}.csv`、
    全国約840地点、アメダス観測所ベース）を取得し、出発地点への最近傍点を単純な
    全走査（cos(緯度)補正付きユークリッド距離）で解決する（840点程度のため空間索引は
    不要）。市区町村ベースのJMA警報（T205）と異なり行政区画の親子関係が無いため、
    素直な最近傍点探索を新設（domain/wbgt_points.py）。
  - **発表時刻の検索方式（着手時に判明した罠）**: 予測API当初は「特定時刻検索
    （date_search_type=3）」でforecast_origin_dateに現在時刻を渡す設計だったが、
    実機確認でこの検索が「発表時刻テーブルとの厳密一致」であり、分・秒はおろか
    正時に丸めても直近の発表がまだ存在しない時間帯（例: 20時発表がまだ無い20:05）は
    空応答になると判明。「連続期間指定（date_search_type=1）」へ変更し、直近6時間の
    発表時刻を検索範囲として取得、レスポンスに複数の発表回（reference_time）が
    混在する場合は最新のものだけを採用するロジック（wbgt_service.py:
    `_pick_nearest_forecast`）を実装した。
  - `backend/app/domain/wbgt.py`（新設）: 暑さ指数の値→3段階＋非表示（`wbgt_level`、
    環境省サイト掲載の「熱中症予防運動指針」を典拠）、提供期間判定（`is_within_
    provision_period`、月単位の粗い判定。境界のズレは呼び出し元のfail-open方針で
    実害なく吸収される設計、コード内に明記）。
  - `backend/app/domain/wbgt_points.py`（新設）: `WbgtPoint`と`nearest_point`
    （最近傍点探索）。
  - `backend/app/infrastructure/wbgt_client.py`（新設）: 地点マスタ取得（24時間TTL）・
    予測値取得（1時間TTL）。サイト側の注意書き「自動化ツールからの高頻度アクセスは
    控えて」に配慮しtenacity再試行は設けない。
  - `backend/app/services/wbgt_service.py`（新設）: 上記を組み合わせ`WbgtStatus`
    （level/label/value/observed_at）を構築。提供期間外・地点解決失敗・予測取得失敗・
    「ほぼ安全」（21未満）のいずれもlevel=nullを返す（T205と共有するfail-open方針）。
  - `GET /api/weather/wbgt`（`weather.py`）: T205の`/api/weather/warnings`と同じ
    fail-open方針（502を返さない）。レート制限
    （`weather_wbgt_rate_limit_per_minute`）を追加。
  - `frontend/src/components/WarningBadge/WarningBadge.tsx`: T205で3段階だった
    `WarningBadgeLevel`へ`severe_warning`（厳重警戒）を追加し4段階化（JMAは3段階のまま
    利用、WBGTのみ4段階目を使う。3段階へ無理に丸め込まない）。
  - `frontend/src/components/WarningBadge/WarningBadge.module.css`: 実機確認
    （Playwright、モバイル幅390px）で判明した問題を修正——当初`.row`は
    WeatherPanelと同じ`overflow-x: auto`（横スクロール）だったが、JMA警報3件+WBGT
    1件の計4件だと1件が画面外に隠れて見切れた。警告バッジは安全性に関わる情報のため、
    隠れて見えなくなるのは望ましくないと判断し、`flex-wrap: wrap`（バッジ単位の折り返し、
    短い語句のためCJKの1文字折り返し問題は起きない）へ変更した。
  - `frontend/src/app/page.tsx`: 警報・注意報バッジ（T205）と同じ地点変更デバウンス
    （1.5秒）に相乗りしてWBGTを取得。JMA警報とWBGTの2つのバッジ配列を1つの
    `warningBadgeItems`へ合流させ、`WarningBadgeList`は1つのまま両方を描画する
    （表示コンポーネントを両タスクで共有するというT205時点の設計どおり）。
- 検証: `test_wbgt_domain.py`・`test_wbgt_points.py`（新設、純ロジック）・
  `test_wbgt_service.py`（新設、モックした地点マスタ・予測値取得を差し替え、
  複数発表回混在時に最新のみ採用することを含む）・`test_weather_route.py`への追加
  （成功/提供期間外・失敗時の空応答/レート制限）。backend 1010件・frontend 489件・
  tsc/eslint全green。Playwrightで実機確認（2026-08-22、提供期間内・東京の暑さ指数
  24.0=注意で実データによるバッジ表示を確認。JMA警報バッジ（T205）との共存、
  デスクトップ・モバイル両方でのレイアウトを確認し、上記のモバイル見切れ問題を
  発見・修正した）。

### - [x] T175. 花粉飛散情報の導入可否を調査する 規模S（調査のみ、2026-08-22完了・判定: 見送り）

- 背景: 春季ライドへの影響が大きい。環境省「はなこさん」は2021年度で廃止済みのため、
  現実的な候補はウェザーニューズのポールンロボ観測データ（無料公開、WxTech API/CSV）か
  Open-Meteoのpollen（CAMS由来）。ただし後者は欧州種（birch/alder/grass）中心で
  スギ・ヒノキ非対応の可能性が高い。
- 対応方針（調査項目）: (1) WxTech花粉APIの利用規約（商用可否・クレジット要件・
  レート制限）と提供期間・地点粒度、(2) Open-Meteo pollenの日本域での実効性
  （スギ・ヒノキが取れるか実データで確認）、(3) 表示形態（春季限定の警告バッジか、
  地点値表示か）。調査結果を本エントリへ追記し、実装するかを意思決定する
  （T50〜T54のJICE見送りと同じ「調査の結果、見送り」も正当な結論）。
- 完了条件: 上記3点の調査結果と実装可否の判断が本エントリに記録されること。
- 依存: なし。
- 調査結果（2026-08-22）:
  1. **Open-Meteo pollen**: 実機確認（東京地点、`air-quality-api.open-meteo.com`の
     `hourly=alder_pollen,birch_pollen,grass_pollen,...`）で全時刻`null`と判明。
     公式ドキュメントで「CAMS European Air Quality予測のみで提供、対象はヨーロッパ
     限定」「対応6種（alder/birch/grass/mugwort/olive/ragweed）にスギ・ヒノキは
     含まれない」と明記されており、背景記載の懸念どおり日本では使用不可（データ自体が
     存在しない、実装しても常に空欄になるだけ）。
  2. **ウェザーニューズ ポールンロボ（opendata-pollen）**: 無料公開・市区町村単位
     （citycode）でデータ提供、提供期間は年により変動するが概ね1〜7月頃（2026年度は
     1月中旬〜7月頃予定）。ただし利用上の注意に「営利・商用目的でのご利用や、
     **インターネットを通じた成果物の公開をご検討の場合は、お問い合わせください**」と
     明記されている。RideCompassはWeb上に公開するアプリのためこの条件に該当し、
     他の政府系公開データ（JMA・環境省・国土地理院等）と異なり、事業者（ウェザー
     ニューズ）への事前問い合わせ・許諾が必要という追加ハードルがある。
  3. 表示形態は（実装する場合）春季限定の警告バッジ（T174のWBGT・T212の河川氾濫予報と
     同じ`WarningBadgeList`共有コンポーネント）が妥当と判断できるが、上記2の理由で
     実装自体を見送るため設計止まりとする。
- 判断: **見送り**。Open-Meteo pollenは技術的に不可能（データ非対応）、ウェザーニューズ
  ポールンロボは技術的には可能だが事前の問い合わせ・許諾プロセスが必要で、他の無条件で
  組み込める公開APIとは前提が異なるため、個人開発の範囲で無条件に実装を進めることは
  適切でないと判断した。
- 再検討条件: ユーザーがウェザーニューズへ問い合わせて許諾を得た場合、またはJMA等が
  花粉情報を無条件公開データとして新たに提供するようになった場合に再度調査する。

### - [x] T176. 河川敷サイクリングロードの増水・冠水情報の導入可否を調査する 規模S〜M（調査のみ、2026-08-22完了）

- 背景: 荒川・多摩川等の河川敷CRはロード乗りの主要走路で、増水による冠水・通行止めは
  日本特有の高価値情報。国交省「川の防災情報」に水位テレメータ観測値があるが、
  リアルタイム配信の正式ルート（水防災オープンデータ提供サービス）は有償のソケット配信で、
  無償側はWebページ由来となり取得経路・規約に課題がある。
- 対応方針（調査項目）: (1) 川の防災情報の無償データ取得経路（公開JSON/CSVの有無と規約）、
  (2) 対象を「主要河川敷CR沿いの代表水位観測所×警戒水位超過の有無」程度の粗い警告に
  絞った場合の実装コスト、(3) 代替として自治体オープンデータ（都県の水防情報）の
  カバレッジ。冠水は「回避一択」のため評価軸にはせず、警告表示のみを想定する。
- 完了条件: 取得経路の実現可否と規約適合の判断が本エントリに記録されること。
- 依存: なし。
- 調査結果（2026-08-22）:
  1. **「川の防災情報」（river.go.jp）**: 実機確認で機械アクセスが明示的に禁止されている
     （取り扱い上の注意ページ: 「ツール等による定期的なデータ収集は、サーバに過度の
     負担がかかりサービス提供に支障をきたすため、お控えいただきますようお願いいたします」。
     高頻度アクセスにはIPブロックの可能性も明記）。無償の公開JSON/CSV経路として使うのは
     規約違反リスクがあり不採用。正式な代替は「水防災オープンデータ提供サービス」（河川
     情報センター経由の有償・実費配信）で、個人開発規模では契約コストに見合わない。
  2. **自治体オープンデータ**: 横浜市「河川水位オープンデータ」を確認したが月次更新の
     過去CSVのみでリアルタイム性が無く、「今、冠水しているか」の判定に使えない
     （そもそも対象が横浜市内河川で荒川・多摩川と無関係）。荒川下流GISオープンデータ
     ポータル（ArcGIS Hub、`gis-opendata-arage.hub.arcgis.com`）は水位観測所・重要
     水防箇所等のFeatureServiceを無償公開しているが、中身は観測所の位置・基準水位等の
     **静的メタデータのみ**で実測水位（現在値）を含まない。単体では冠水判定に使えない。
  3. **【調査中に発見した代替案】JMA指定河川洪水予報API**
     （`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`、実機確認: 200 OK、
     機械アクセス制限の明記なし。T205で使ったJMA bosai系r8スキーマと同じ提供体系）。
     国管理299河川・都道府県管理142河川（荒川を含む、多摩川も国管理の指定河川洪水予報
     対象に含まれると推定される。2026-08-22の実機確認時点では善福寺川・神田川の
     レベル4氾濫危険警報が発表中で、荒川・多摩川自体は平常時のため0件だった——このAPIは
     「発表中の河川だけがリストに現れる」設計であり、対象河川の静的マスタは提供されて
     いない）を対象に、レベル2〜5の氾濫注意報/警報/危険警報/特別警報をリアルタイムで
     発表する。レスポンスの`class20Codes`/`class15Codes`/`class10Codes`/`officeCodes`
     フィールドがT205（`jma_area.py`）で構築済みの市区町村→JMA警報エリア解決の仕組みと
     完全に同じ構造のため、T205の地点解決基盤をほぼそのまま再利用でき、実装コストが
     大幅に下がる見込み。
- 判断: **実現可能・実装を推奨**（当初想定していた「川の防災情報」経由ではなく、調査中に
  発見したJMA指定河川洪水予報APIを使う設計に転換）。無償・機械アクセス制限なし・
  リアルタイム・T205基盤の再利用で低コストという条件を満たす。実装はT210（通行止め・
  道路規制、表示形式を共有する可能性）の調査結果と合わせて別タスクとして起票する
  （本タスクは調査のみのスコープのため）。

### - [x] T177. リアルタイム交通量によるcar_stress時間帯補正の実現性を調査する 規模M（調査のみ、2026-08-22完了・判定: 見送り）

- 背景: car_stress（2次）は静的な推定で時間帯変動（通勤ラッシュ・深夜）を持たない。
  国交省の交通量API（直轄国道、5分値・1時間値、無料・要規約同意）はT53のJARTIC較正で
  検証済みのデータ系列であり土地勘がある。ただし直轄国道限定でロードが好む県道・裏道は
  カバー外のため、「全区間のリアルタイム補正」ではなく「時間帯別の統計的な補正係数を
  事前計算し、highwayクラスごとに掛ける」（例: 幹線は7-9時に+1相当）が現実的な形。
- 対応方針（調査項目）: (1) 直轄国道の時間帯別交通量プロファイルを数地点で集計し、
  時間帯係数として一般化できる形か確認、(2) T53で判明した母集団の偏り（raw>5が0.9-1.2%）が
  時間帯分析でも制約になるか、(3) 出発時刻×到達時刻で区間ごとに係数を変える場合の
  コスト関数への配線方法（T173の日没係数と同じ「軸内パラメータ」機構に載るか）。
- 完了条件: 時間帯係数の妥当性判断と、実装する場合の設計方針が本エントリに記録されること。
- 依存: T173（軸内の時刻係数機構を先に作る場合）。
- 調査結果（2026-08-22）: JARTIC WFS（T53と同じ`t_travospublic_measure_1h`、道路種別=3）
  から関東の4観測点（都心寄り2点・郊外寄り2点）について平日1日（2026-08-19）24時間分の
  実測（上り・下り×小型・大型交通量の合計）を取得し、時間帯プロファイルを比較した。
  1. **地点ごとにプロファイルの形状が大きく異なる**ことが判明。ある地点（3310900、都心）は
     朝6-7時に急上昇しその後日中通して高止まりする「朝立ち上がり・台形型」、別の地点
     （3110660）は朝の立ち上がりが弱く19-20時にむしろピークが来る「夜型」、また別の地点
     （3310950）は朝ピーク後に一旦落ち着き13-17時に再上昇する「二山型」など、単純な
     「朝夕2山の通勤ラッシュパターン」に一致しない地点が複数あった。頑健に言えるのは
     「深夜0-4時は全地点で明確に空いている」という程度で、それ以上の時間帯係数（例:
     幹線は7-9時に+1）を全地点共通で一般化する根拠は乏しい。
  2. **母集団の偏り（T53）は時間帯分析にもそのまま制約になる**: 観測点自体が幹線道路
     への設置に偏っている（母集団の1%未満）ため、得られる時間帯プロファイルは
     「幹線道路特有」のものであり、サイクリストが好む生活道路・裏道（観測対象外）への
     一般化を裏付けるデータが無い。幹線の朝ラッシュがそのまま生活道路の混雑度に比例する
     保証もない。
  3. 配線方法自体（T173の`is_night`と同じ「時刻→値」の純粋関数をEvaluationServiceが
     参照する軸内パラメータ機構）は技術的に用意可能だが、上記1・2により埋め込むべき
     係数値の根拠が無いため、設計だけ作って値を後回しにする合理性が無いと判断した。
- 判断: **見送り**。時間帯係数として一般化できるだけの安定したパターンが実データで
  確認できず、T53の観測点選択バイアスがそのまま制約になるため。
- 再検討条件: JARTIC観測点密度が大幅に増える、または直轄国道以外（都道府県道等）の
  時間帯別交通量データが新たに公開される等、データソース自体が改善された場合に
  再度調査する。

### - [x] T178. 風をweather-map-layer（Open-Meteo公式）で時刻指定描画する 規模M〜L（2026-08-20完了）

- 発端: ユーザー確認「時刻指定で描画できる対象を明確にして。今特に気にしているのは
  風、雨、雷」。調査の結果、**雨・雷（T171）と風は技術的な位置づけが異なる**ことが
  判明したため、風は別タスクとして分離した。降水・雷は気象庁ナウキャストが時刻パラメータ
  付きのPNGタイルとして配信されているため、GSI標高図と同じraster sourceパターンで
  そのまま乗るが、風はこの種のタイル配信が無く、点データ（風向・風速）から自前で
  ベクトル場を構成する必要がある。ユーザー指示「Open-Meteoのweather-map-layerを使う
  方向で調査して」を受け、案B（[open-meteo/weather-map-layer](
  https://github.com/open-meteo/weather-map-layer)）を深掘りし、**採用の方向で確定**した
  （自前の格子点サンプリング案は不採用。理由は下記実装メモ参照）。
- 実機調査で確認した内容（2026-08-20、CDNへ直接アクセスして検証）:
  - パッケージ: npm `@openmeteo/weather-map-layer`（現バージョン0.0.20、CDN配信も可）。
    依存に`maplibre-gl: ^5.20.1`を持ち、本リポジトリの`maplibre-gl@^5.24.0`と両立する
  - 組み込みはシンプル: `maplibregl.addProtocol('om', omProtocol)`でカスタムprotocolを
    登録し、`map.addSource({url: 'om://' + omUrl, type: 'raster' | 'vector', ...})`と
    `map.addLayer(...)`を呼ぶだけ。バックエンド不要（ブラウザから直接CDNへアクセス、
    S3を起点にBunny CDNで配信されている）
  - **日本域向けのJMA MSMデータが実在することを確認済み**:
    `https://openmeteo-data-spatial.b-cdn.net/jma_msm/latest.json`が200を返し、
    `variables`に`wind_u_component_10m`/`wind_v_component_10m`を含む（他:
    precipitation・temperature_2m・cloud_cover系・pressure_msl・relative_humidity_2m・
    shortwave_radiation）。`crs_wkt`のBBOXは`[22.4, 120.0, 47.6, 150.0]`で日本全域
    （沖縄含む）をカバー。`reference_time`は3時間毎に更新され、`valid_times`は
    そこから1時間刻みで約39時間先まで並ぶ（JMA MSMの実際の更新間隔・解像度〜5km
    そのままの空間分解能で、対抗のDWD ICON全球モデル〜11kmより日本域では大幅に高精度）
  - 矢印表示は`om://` URLへ`&arrows=true`を付けたvector sourceを別途addSourceする
    （ラスタ源＝色分けの背景、ベクタ源＝矢印、の2層構成がサンプルの標準形）
  - 時刻指定は`time_step`パラメータ（例: `current_time_1H`で直近時刻の1時間丸め、
    `valid_times_N`でN番目のvalid_timeを指定）。T170のスライダーが持つ「対象時刻」から
    `jma_msm/latest.json`の`valid_times`配列中の最寄りインデックスを引けば連動できる
  - データのライセンスはCC-BY-4.0（Open-Meteoオープンデータ、出典表記が必要・商用利用も
    許諾範囲内）。降水（`precipitation`）もこのモデルに含まれるが、解像度・更新間隔とも
    T171の気象庁ナウキャスト（250m〜1km・5〜10分毎）の方が近未来の雨には優れるため、
    降水はT171を主とし、こちらのprecipitationは風と同じ地図上で気圧配置・広域の雨域を
    俯瞰する補助として使うかは実装時に判断する
  - **ライブラリ本体（`@openmeteo/weather-map-layer`のコード）はGPLv2**（データ自体の
    CC-BY-4.0とは別）。バージョン0.0.20とプレ1.0で、README上も「本番対応ではない・
    APIが変更されうる」と明記されている。GPLv2はコピーレフトのため、npm依存として
    そのまま組み込んでビルドに含める場合の法的な扱い（配布形態がリンクとみなされるか等）
    は着手前に確認する。本リポジトリは現状LICENSEファイル自体を持たない私的リポジトリの
    ため実務上のリスクは小さいと見込むが、将来公開・配布する可能性があるなら要再検討
    という条件付きで記録する
- 対応方針: 上記を踏まえ、`@openmeteo/weather-map-layer`を導入し、`jma_msm`データセットの
  ラスタ（背景色分け、任意）＋ベクタ（矢印、`arrows=true`）の2層をkind="dynamic"レイヤーと
  して`mapLayers.ts`へ追加する。T170のスライダー時刻→`valid_times`インデックスの対応表を
  作り、スライダー操作でom:// URLの`time_step`を差し替える。ライブラリがプレ1.0のため、
  バージョン固定（キャレット無しの完全一致指定）と、取得失敗時のフォールバック
  （T87のerror状態、または黙って非表示）を必ず入れる。
- 完了条件: GPLv2の扱いに関する結論（上記の条件付き記録で足りるか、別途要確認か）を
  本エントリへ確定として記録したうえで、風向・風速が地図上へ矢印で描画され、T170の
  スライダーで時刻（3時間毎の予報初期値×1時間刻みのvalid_time、約39時間先まで）を
  切り替えられること。ライブラリ取得失敗時に地図全体がクラッシュしないこと。
  Playwright実機確認・frontend全green。
- 依存: T170（時刻指定描画基盤）。
- 実装メモ（2026-08-20完了）: 着手前にGitHub上のREADME・examples/vector/wind-arrows.html
  （公式サンプル、curlでraw.githubusercontent.comから直接取得し実コードを確認）・npm
  registryを実機調査し直した結果、対応方針から2点変更した。(1) ラスタ（背景色分け）は
  「対応方針上は任意」だった点を活かし、矢印（vector、`arrows=true`）のみを実装（地図の
  視界を圧迫しない、設計原則12。ラスタ色分けは見送り）。(2) T170の時刻スライダーは実装時点
  では降水ナウキャストのフレーム配列に密結合していたため、風にもそのまま使うことができ
  なかった。`NowcastTimeSlider`を`DynamicLayerTimeSlider`へ一般化（`{label, badge}`という
  レイヤー非依存のframe型を受け取るだけの汎用UIへ変更、時刻の整形・実況/予測ラベルの
  計算は呼び出し側＝各レイヤーのデータ層へ移した）し、降水・風の両方がONのときは
  page.tsx側の新設コンテナ（`dynamicLayerSliders`、page.module.css）が縦に積んで両方
  同時表示する（1本のスライダーへ無理に統合しなかった理由: 降水は5分刻み・±60分、
  風は1時間刻み・約39時間先までと粒度・レンジが大きく異なり、共有タイムラインにすると
  どちらかの操作性が犠牲になるため）。
  データ層は`windLayer.ts`（新設、precipitationNowcast.tsと同型の純粋関数のみ）:
  `fetchWindFrames`（`jma_msm/latest.json`のvalid_times配列をindex付きフレームへ変換）・
  `nearestFrameIndexToNow`（reference_timeが3時間毎更新のため配列先頭が「今」とは限らず、
  実際の時刻差で最寄りフレームを探す。降水の`latestObservedFrameIndex`とは選び方が異なる
  ため別関数にした）・`windVectorSourceUrl`（om://ソースURL組み立て、`time_step=
  valid_times_{index}&variable=wind_u_component_10m&arrows=true`）・`formatWindFrameTime`
  （風は約39時間先まで日付をまたぐため、降水の"HH:mm"と異なり"M/D HH:mm"で日付も含める）。
  `MapView.tsx`は`maplibregl.addProtocol("om", omProtocol)`をモジュールスコープで一度だけ
  登録し、`ensureWindVectorLayer`（vector source・line layer、source-layer名は公式サンプルと
  同じ`"wind-arrows"`、風速に応じた濃淡は`case`式で簡略化）と`applyWindVectorState`
  （vector sourceは`tiles`配列ではなく`url`1本で時刻を表すため、`setTiles`ではなく
  `setUrl`で時刻を差し替える点が降水ラスタと異なる）の2関数で完結させ、降水と同じ
  専用の時刻依存effect（1本にまとめ、依存配列へshowWindVector/windVectorTileUrlを追加）
  から呼ぶ。T87データ状態は降水と同じくsourceLayer無し登録（風は連続場のため「0件」判定に
  意味が無い、取得失敗のみ検知）。
  GPLv2の扱い: 対応方針の条件付き記録のとおり採用した（本リポジトリはLICENSEファイルを
  持たない私的リポジトリのため実務上のリスクは小さいと判断。npm依存は`--save-exact`で
  完全一致指定、`@openmeteo/weather-map-layer@0.0.20`固定）。
  実機調査で新たに判明した点: `@openmeteo/weather-map-layer`は内部で`@openmeteo/file-reader`
  （omファイル形式のWASMデコーダ、`@openmeteo/file-format-wasm`）とWeb Workerを使うが、
  package.jsonの`exports`が`import.browser`条件でブラウザ向けビルド（`node:fs`非依存）を
  分離しているため、Next.js（Turbopack、追加設定なし）が自動的にブラウザ向けチャンクを
  解決しWASM・Workerとも問題なくバンドルされることをPlaywright実機確認で確認した
  （懸念していたバンドラ対応リスクは実害無しと判明）。`maplibre-gl`はweather-map-layer側の
  `dependencies`（`^5.20.1`、peerDependenciesではない）だが、本リポジトリの`^5.24.0`が
  範囲を満たすためnpm installで単一コピーへdedupeされることも確認済み（node_modules内に
  重複コピーは作られない）。
  Playwright実機確認: 「動的」→「風」の順にONにすると地図全面に矢印が表示され
  （`queryRenderedFeatures`で494件のwind-arrows地物を確認、CDNから実際の`.om`データ
  ファイル取得も確認）、地図下部に時刻スライダーが出現（初期位置は現在時刻に最も近い
  フレーム）。スライダー操作で`map.getSource("region-wind-vector")`のURLが実際に別の
  `time_step`へ切り替わることを確認。降水ナウキャストと風を同時にONにすると2本の
  スライダーが縦に積んで表示され、片方だけOFFにしてももう片方は影響を受けないことを確認。
  コンソールエラー無し。frontend vitest 401件（新規9件、windLayer.test.ts）・tsc全green。
  DynamicLayerTimeSliderへの一般化に伴い、降水ナウキャスト側の呼び出し（page.tsx）・
  テスト（旧NowcastTimeSlider.test.tsx→DynamicLayerTimeSlider.test.tsx）も追従済み。
  追記（2026-08-20、ユーザー確認「風の強さを矢印の大きさで表現できる？」）: 実機調査の
  結果、矢印の長さ（ジオメトリ自体）はライブラリ側がズームレベルのグリッド間隔で決めており
  風速0.27〜7.0 m/sの範囲で測定してもほぼ一定、風速には連動しないと判明（自由に変更できない
  部分）。一方`line-width`はこちら側のpaint設定のため、風速`value`を`interpolate`式で
  線形補間し太さでも強さを表現するようにした（色の濃淡と合わせた二重の表現）。ユーザー
  追加要望「1m/s単位で把握したい」を受け、当初の4点指定（区間ごとに傾きが変わる）から
  0 m/s→1.5px・15 m/s→9pxの2点のみへ単純化し、傾きを0.5px/(m/s)固定にした（1m/s差が
  常に0.5px差になり、体感の一定性を保つ。15 m/s超は9pxで頭打ち）。Playwright実機確認:
  ズームアウトして日本近海の風速分布を見た画面で、洋上の強風域の矢印が内陸の弱風域より
  明らかに太く表示されることを確認。frontend vitest 402件全green・tsc全green。
  追記2（2026-08-20、ユーザーフィードバック「やっぱり見にくい。風がほぼない場合も常に
  矢印が出ているのが違和感」「ライブラリから変えることは検討できる？ライセンス制約も
  あるといえばあるし」を受け、`@openmeteo/weather-map-layer`依存を撤去し自前実装へ
  全面移行）: 検討の過程で次の3点が判明・決着した。
  (1) ヒートマップ（ラスタ色分け）案は技術的に不可能と判明: 気象データの生の格子
  ファイル（.om）には風向・風速の成分（u/v）のみが保存され、「風速そのもの」という
  合成値（`wind_speed_10m`）はどのモデル・どのドメインでも事前計算されていない
  （実機で`variable=wind_speed_10m`をjma_msm・dwd_icon両方に対し試し「見つからない」
  エラーを確認）。矢印（vector、arrows=true）側だけがu/v→速さ・向きの変換を内部で
  行う特別な経路で、ラスタ側にはその経路が無い。
  (2) GPLv2は`@openmeteo/weather-map-layer`本体だけでなく、内部で使う`.om`ファイル
  デコーダ（`@openmeteo/file-reader`・`@openmeteo/file-format-wasm`）も同じ
  GPL-2.0-onlyと判明（package.json確認）。どのライブラリ経由でも.omを使う限り
  GPLv2から逃れられない。
  (3) 自前実装（Open-Meteo REST API、既存の`weather_client.py`の仕組みを再利用）は
  ライセンス面では有利だが、Open-Meteo本APIのレート制限に弱いという新たなトレードオフが
  判明した（`weather_service.py`のdocstringに記録済みの「ルート1本の生成だけで429が
  常態化した」実績を踏まえた判断材料として提示、ユーザーが把握した上で「自前実装案で
  進めて」と決定）。

  **実装内容**: バックエンドに`GET /api/weather/wind-grid`を新設
  （`app/domain/wind_grid.py`: 関東本土bbox上の固定格子点を生成する純粋関数
  `generate_wind_grid_points`＋`WindGridPoint`モデル、`app/services/weather_service.py`:
  `get_wind_grid`が既存の`WeatherClient.get_forecast_many`（多地点一括・30分TTL
  キャッシュ・429リトライ）をそのまま再利用、`app/api/routers/weather.py`:
  レート制限20/分・取得失敗地点は結果から除外）。格子間隔は当初0.35°（約39km、56点）で
  実装したが、実機確認で「ルート計画時の通常のズーム（13、表示範囲約15km四方）では
  格子点が視界に1つも入らないことがある」と判明したため0.2°（約22km、156点）へ密度を
  上げた（1ユーザーあたりのOpen-Meteoリクエスト回数は変わらず常に1回にまとまる設計の
  ため、密度を上げても429リスクは増えない。実測で156点でも約2.8秒、56点時とほぼ変わらず）。
  **ただし0.2°でも、格子点の配置と閲覧地点の位置関係次第ではズーム13で矢印が0件になる
  ケースが実機で再現した**（東京都北区付近で最寄り格子点まで10.1km、ズーム13の表示半径
  約7.5kmを上回る）。これは「全ユーザーで同じ格子点を使い回すキャッシュ効率」と
  「任意の閲覧地点での密な表示」が本質的にトレードオフの関係にあるため（閲覧地点中心の
  可変格子にすればキャッシュ再利用率が下がり429リスクが戻る）、本ラウンドでは対応せず
  記録に留める。ズーム7〜10程度（関東〜東京都心スケール）では格子点が適度に分布し
  実用的に見える（Playwright実機確認済み）ため、現状は「広域の風況把握」用途として
  位置づけ、閲覧地点直近の密な表示が必要になった場合は別途検討する。

  フロント側は`windLayer.ts`を全面書き換え（`fetchWindFrames`/`windVectorSourceUrl`等の
  om://依存関数を削除、`windGridToFeatureCollection`が格子点＋選択中フレームindexから
  GeoJSON FeatureCollectionを組み立てる純粋関数として新設）。`MapView.tsx`は
  `maplibregl.addProtocol("om", ...)`registrationとvector source/lineレイヤーを削除し、
  GeoJSON source + symbolレイヤー（矢印アイコンは`createWindArrowIcon`でCanvas描画し
  `sdf:true`で登録、`icon-color`で連続グラデーション着色）に置き換えた。これにより
  ライブラリの制約が無くなり、ユーザー要望「矢印の長さと色の連続グラデーションの
  組み合わせ」を`icon-size`（長さ+太さを一様スケール）・`icon-color`（青→オレンジ→赤の
  連続グラデーション）で実現。ユーザーフィードバック「ほぼ無風でも矢印が出るのが違和感」
  に対応し、風速1 m/s以下の地点は`filter`で非表示にした。`@openmeteo/weather-map-layer`は
  `npm uninstall`済み（GPLv2依存を完全に解消）。OpenAPIスキーマ再生成
  （`export_openapi.py`→`generate:api`）で`WindGridPoint`型を`frontend/src/types/weather.ts`
  へ追加。backend pytest 940件（新規12件: test_wind_grid.py 5件・test_weather_service.py
  4件・test_weather_route.py 3件）・frontend vitest 404件全green、tsc/eslintクリーン。
  Playwright実機確認: バックエンドの実APIから156点の実データ取得・GeoJSON構築・
  symbolレイヤー描画・時刻スライダーでのフレーム切り替えを確認。
  追記3（2026-08-20、ユーザー要望「広域ではなく通常ズームでもある程度使えるように設計して」）:
  格子間隔0.2°（156点）でも「特定の閲覧地点では最寄り格子点までズーム13の表示半径を
  超える」ケースが実機で再現したため、格子間隔を0.1°（緯度約11km・経度約9km、624点）へ
  さらに密にした。0.1°は正方格子の理論上の最悪ケース（どの地点でも最寄り格子点までの
  距離が対角線の半分以内）がズーム13の表示半径（約7.5km）にほぼ収まる値として選び、
  関東本土bbox内2000点のランダムサンプルで実際に**100%がズーム13の表示半径7.5km以内に
  格子点を持つ**ことを検証済み（`generate_wind_grid_points`に対する検証スクリプト、
  最悪ケース7.04km・中央値4.03km）。
  地点数を増やした結果、GET（クエリ文字列でlatitude/longitudeのカンマ区切りを渡す方式）
  ではrequest-URIがnginxの既定上限を超え414 Request-URI Too Largeになることが実機で
  判明した（624地点で再現、288地点では未発生）。そのため`weather_client.py`の
  `get_forecast_many`をPOST（フォームボディ）へ変更した（`_fetch_json`に`method`引数を
  追加、単一地点の`get_forecast`はGETのまま維持）。POSTなら624地点でも実機で200 OK・
  約3.3秒で成功することを確認済み。既存テスト（`test_weather_client_cache.py`の
  `FakeHttpClient`等、`test_wind_service.py`の`CountingHttpClient`）へ`post`メソッドを
  追加して追従。backend pytest 940件・frontend vitest 404件全green、tsc/eslintクリーン。
  Playwright実機確認: 元々0件だった東京都北区の初期表示（ズーム13）で1件描画されることを
  確認（この日は関東全域が非常に穏やか〔1m/s前後〕だったため、多くの格子点が無風閾値
  フィルタ〔1 m/s以下は非表示〕の近傍に留まり、統計上のカバレッジ改善ほど視覚的な
  密集感は無いが、これはデータ側の実際の穏やかさを正しく反映した結果であり不具合ではない）。

### - [x] T179. Open-Meteo 429再発を受け、自前ホストVM経由のリレープロキシで送信元IPを分離 規模S（2026-08-20完了）

- 発端: ユーザー報告「openmeteoで429．renderだと頻発」。T109（2026-08-17）で根本原因は
  特定済みだった（Open-MeteoはRenderの共有送信元IP単位でレート制限しており、他テナントの
  分も巻き添えで429になる。クライアント側の再試行では解消できず、当時は「有料/専用キー化の
  検討はスコープ外、再発時に再検討」としていた）。今回がその再発。
- 検討: (1) Open-Meteo有料プラン（APIキー化、IP単位→キー単位のレート制限に変わる根本解決）、
  (2) RenderのStatic Outbound IPアドオン（専用送信元IPを購入）、(3) 一般的な有料プロキシ
  サービス経由（そのプロキシ自体のIPが既に他顧客と共有・データセンター系IPとしてOpen-Meteo側で
  制限対象になっている可能性があり、費用を払っても解決しないリスクがある）、(4) 既存の
  Oracle Cloud VM（`ridecompass-postgis`、[[oracle-cloud-postgis-migration]]、PostGIS本番DBが
  Always Free枠で稼働中・専用固定IP）を中継プロキシとして流用、を比較した。(4)は追加費用ほぼ0円
  （既存Always Free枠の延長）・新規外部ベンダー依存が発生しない・実装パターンも流用できる
  （port 5432で既に運用実績のある「OCIセキュリティリスト+iptablesの両方でRenderのアウトバウンド
  範囲のみ許可」という多層防御方式をそのままport 8080へ複製できる）という理由でユーザーが選択。
  (1)(2)は根本解決だが費用が絡む意思決定のため、再発が続く場合の次の選択肢として温存する。
- 対応: `ridecompass-postgis`VMへnginxをインストールし、`/v1/forecast`のみを
  `https://api.open-meteo.com/v1/forecast`へ中継するリバースプロキシを追加（他パスは404、
  オープンリレー化を防ぐ）。ポート8080はOCIセキュリティリスト・VM内iptablesの両方で
  管理者IP＋Renderのアウトバウンド範囲（`74.220.48.0/24`・`74.220.56.0/24`）のみへ制限
  （port 5432と同じ多層防御パターン）。`backend/app/config.py`に`open_meteo_base_url`
  （既定はOpen-Meteo直叩き、ローカル開発はこのままでよい）を追加し、
  `weather_client.py`のハードコードされた`OPEN_METEO_URL`定数を置き換えた
  （GET/POSTどちらの呼び出しも同じ設定値を参照）。本番（Render）は環境変数
  `OPEN_METEO_BASE_URL`をこのVMのプロキシURLへ向けることで切り替える
  （`.env.example`にプレースホルダを記載、実IPはVM再作成で変わりうるため
  リポジトリへは書かず環境変数側でのみ設定する）。
- 完了条件: プロキシ経由でOpen-MeteoのGET/POST（多地点一括、風グリッド用）両方が
  200を返すこと、許可パス以外が404で拒否されること、backend pytest全green、
  設定値がRenderの実運用でのみ有効化されローカル開発の挙動を変えないこと。
- 実装メモ（2026-08-20完了）: nginx 1.24.0（Ubuntu標準リポジトリ）を使用。
  `proxy_ssl_server_name on`でSNIを維持し上流のTLS証明書検証を通す。実機確認:
  GET `/v1/forecast?latitude=...&longitude=...`・POST（複数地点まとめて、`get_forecast_many`が
  使う形式）とも200 OKで実データを取得、`/`・`/etc/passwd`等の他パスは404を確認。
  iptablesルールは`netfilter-persistent save`で永続化。OCIセキュリティリストは既存の
  5432番ルールを変更せず8080番の3ルール（管理者IP・Render 2範囲）のみ追加。
  backend pytest 940件全green（`OPEN_METEO_URL`定数を参照していた箇所は無く、
  置き換えによる既存テストへの影響なし）。並行してVM上で`apt-get upgrade`によりカーネル
  更新の再起動待ち通知が出たが、本番DBサーバーの再起動は影響が大きいためこのタスクの
  スコープ外とし着手していない（別途ユーザー判断が必要、記録のみ）。
  **残作業（本エントリの完了条件には含めないが必須）**: Render側の環境変数
  `OPEN_METEO_BASE_URL`をこのVMのプロキシURLへ設定するのはユーザー操作
  （Renderダッシュボードへのアクセス権がこのセッションに無いため）。設定するまでは
  本番は従来どおりOpen-Meteo直叩きのまま（コード変更のみでは429対策は効かない点に注意）。

### - [x] T180. 風の強さを面（ヒートマップ）で表現し、詳細格子で密度を上げる 規模M（2026-08-20完了）

- 発端: T178完了後のユーザーフィードバック「その周辺エリア全体の風のつよさというのが
  分かりにくい。ヒートマップとかそういう面での表現はできない？」。矢印（1点ごとの正確な
  向き・強さ）だけでは、周辺一帯がどのくらい強いかの雰囲気を一目で掴みにくいという指摘。
- 検討: 以前（T178実装メモ）「ヒートマップは技術的に不可能」と記録していたのは、GPLv2
  ライブラリ（`@openmeteo/weather-map-layer`）が使う生の格子ファイル(.om)にu/v成分しか
  無く風速そのものが無いという、あのライブラリ固有の制約だった。T178完了時点で既に
  自前実装（`GET /api/weather/wind-grid`、通常のOpen-Meteo REST API経由）へ全面移行して
  おり、各格子点は最初から風速の数値を持っているため、MapLibre標準のheatmapレイヤー
  （点データ＋weight＋radius/intensity/colorの組み合わせで密度を面として塗る機能）を
  そのまま使える。
  ただし格子間隔が0.1°（約9〜11km、624点・関東全域固定）と粗く、通常のルート計画
  ズーム（13、表示半径約7.5km）では視界に1〜2点しか入らず「面」ではなく「点にじみ」に
  しかならない懸念があった。ユーザー提案「格子間隔をより密にしながら、キャッシュ階層を
  工夫できない？」を受け、表示中の範囲だけを対象にした詳細格子を追加することにした。
  最も重要な設計判断は、詳細格子の座標を「問い合わせbboxの角」ではなく
  `WIND_GRID_BBOX`の固定原点からのオフセットで計算すること（domain/wind_grid.py:
  `generate_wind_grid_detail_points`のコメント参照）。ユーザーの閲覧地点をそのまま
  格子の起点にすると、閲覧位置が少しずれるだけで格子点の絶対座標も全部ずれてしまい、
  近い場所を見ている別ユーザーとの`weather_client.py`キャッシュ共有が効かなくなる
  （＝429リスクが戻る、T178で見送った「閲覧地点中心の可変格子」問題そのもの）。原点を
  固定することで、bboxが多少ずれていても重なる範囲では同じ絶対座標の格子点になり、
  既存の30分TTLキャッシュがユーザー間で共有される。
- 対応方針: (1) バックエンドに`GET /api/weather/wind-grid-detail`を新設し、bboxに
  交差する0.02度間隔（約2km）の格子点を返す。1リクエストあたりの点数上限
  （`WIND_GRID_DETAIL_MAX_POINTS=900`）を設け、超える場合は400を返す。(2) フロントは
  ズーム10以上のときだけ、現在のビューポート（`clampWindDetailBbox`で最大0.5度四方へ
  クリップ、926点上限に収まる範囲）を対象に詳細格子を取得し、粗い格子（`windGrid`）へ
  上書きする形で使う（詳細格子が空/未取得なら粗い格子へ自動フォールバック）。
  (3) MapLibreの`heatmap`レイヤーを矢印と同じsourceに追加し、風速をweightへ正規化して
  面として描画する。矢印は向き・正確な値、ヒートマップは周辺一帯の強弱の雰囲気、という
  役割分担で両方を重ねる。
- 完了条件: 詳細格子APIがbboxに応じた点数を返し、広すぎるbboxは400で拒否されること。
  同じ場所を見る2つの異なるbboxが重なる範囲で同一座標の格子点を返す（キャッシュ共有の
  前提）ことをユニットテストで確認。ヒートマップがMapLibre上に描画され、矢印を隠さない
  こと。backend/frontend双方のテスト全green。
- 依存: T178（自前実装への移行が前提）。
- 実装メモ（2026-08-20完了）: バックエンド`domain/wind_grid.py`に
  `generate_wind_grid_detail_points`（固定原点ラティスへのスナップ、WIND_GRID_BBOXへの
  クリップ）・`WIND_GRID_DETAIL_SPACING_DEG=0.02`・`WIND_GRID_DETAIL_MAX_POINTS=900`を
  追加。`api/routers/weather.py`に`GET /api/weather/wind-grid-detail`（bbox不正/過大は
  400、専用レート制限`wind_grid_detail_rate_limit_per_minute=30`）を追加。
  テストは「小さいbboxの結果が、それを包含する大きいbboxの結果に同じ絶対座標で含まれる」
  という一番重要な性質（固定ラティスであること）を直接検証する形にした（bboxをわずかに
  ずらした2つの完全一致を期待する素朴なテストは、境界をまたぐ場合に正しく失敗することが
  分かり書き直した）。
  フロント側は`windLayer.ts`に`clampWindDetailBbox`（ビューポート中心を基準に最大0.5度
  四方へクリップ、点数上限を安全に下回らせる）・`WIND_DETAIL_MIN_ZOOM=10`を追加。
  `MapView.tsx`は`onViewportChange`コールバック（moveend/zoomend・初回idleで現在の
  bbox+zoomを親へ通知、道路タイル用の`onRegionZoomHintChange`とは別の汎用通知）を新設し、
  page.tsx側でuseDebouncedValue（500ms）を通してから詳細格子を取得する。取得失敗時は
  エラー表示をせず静かに粗い格子へフォールバックする（補助的な機能のため）。
  ヒートマップの実装で2点、実機確認を通じて当初想定から変更した。(1)
  `heatmap-weight`の基準値を当初矢印と同じ0〜15m/sにしていたが、実機確認（2026-08-20、
  関東全域が終日1〜2m/s程度の穏やかな日）で重みが0.1前後に潰れほぼ透明になったため、
  0〜8m/sへ引き下げた。(2) `heatmap-radius`を当初ズーム6→20px・14→90px程度の緩やかな
  補間にしていたが、詳細格子は間隔が固定（0.02度）のため画面上のピクセル間隔がズームの
  たびに倍々で広がり、半径が追従しないと点同士が繋がらず「面」ではなく「点の集まり」に
  見えることが実機で判明した（ズーム13で点間隔≈143pxに対し半径79pxではほぼ繋がらない）。
  半径をズーム16で380pxまで大きく伸ばす形に変更し、半径が伸びるほど1点の寄与が
  大きくなり飽和しやすくなる分は`heatmap-intensity`をズームが進むほど下げて相殺した。
  実機確認は当日の実際の風（1.14m/s、ほぼ無風）に加え、Playwrightのレスポンスモックで
  強めの風（基準8m/s±jitter）を再現したケースの両方で行い、無風時は淡く・強風時は
  矢印がオレンジ〜赤へ変わりつつ周辺一帯に滑らかな青系の面が広がることを確認した
  （設計原則12「地図の視界を圧迫しない」を踏まえ、不透明度は0.65に抑え道路・ラベルが
  読める程度に留めている）。backend pytest 950件（新規10件）・frontend vitest 418件
  （新規11件）全green、tsc/eslintクリーン。
  追記（2026-08-20、ユーザーフィードバック「矢印のデザインを工夫できる？風を示している
  ことを表現し、地図上のオブジェクトとは区別する意図」）: 旧デザイン（直方体の軸+三角の
  矢じり）は直線的で道路標識のような「硬い」印象があったため、矢印アイコン
  （`MapView.tsx`: `createWindArrowIcon`）を緩やかにうねる3本のストリームライン
  （気流線）が1点の矢じりへ収束する形へ再設計した。風チップボタン（`icons.tsx`:
  `WindIcon`、渦を巻く3本の曲線）と同じ「曲線=風」という視覚言語を地図上でも踏襲し、
  地図上の他オブジェクト（道路・POI等、直線・単純多角形が主体）との見分けをつきやすく
  している。3次ベジェ曲線を細かく刻んでオフセットした左右の縁からリボン状の塗りを作る
  汎用ヘルパー`fillTaperedRibbon`を新設（尾を太く矢じりに近づくほど細くする、風上から
  風下へ流れる感覚を表現）。Playwright実機確認（単体でのアイコン拡大表示・実際の地図上で
  回転/着色/ハロー適用後の見え方・ダークモード）で、道路標識的な硬さが無くなり気流線と
  して読み取れることを確認した。frontend vitest 418件全green（アイコンの見た目のみの
  変更のためテスト件数の変化なし）・tsc/eslintクリーン。
  追記2（2026-08-20、ユーザーフィードバック「地図のうえでどの範囲の風向き、風速を示して
  いるか分かりにくい。対応する格子内を薄く矢印と対応する色で着色できない？」）: heatmap
  レイヤー（ぼかしたKDEの密度分布）は「周辺一帯のなめらかな強弱」を見せる一方、「どの
  矢印がどの範囲の値を代表しているか」というセル境界を逆に曖昧にしてしまう性質があった
  ため、矢印を中心とする1辺spacingDeg（粗い格子0.1度・詳細格子0.02度）の正方形セルを
  矢印と全く同じ色スケールで薄く塗る方式へ置き換えた（heatmapレイヤーは撤去）。
  `windLayer.ts`に`windGridToCellFeatureCollection`（各点を中心とする正方形ポリゴンを
  生成、値欠損点はスキップ）・`WIND_GRID_SPACING_DEG`/`WIND_GRID_DETAIL_SPACING_DEG`
  （backend/app/domain/wind_grid.pyの同名定数と値を合わせる必要があるとコメントで明記。
  APIレスポンス自体には間隔情報が含まれないため）を追加。矢印のicon-colorとセルの
  fill-colorが同じ配色定義からずれないよう、`MapView.tsx`に`WIND_COLOR_SCALE_EXPRESSION`
  を新設し両方から参照する形にした（2箇所に同じ配色を書くと片方だけ直して食い違う事故を
  防ぐため）。fill-opacityは0.22（設計原則12を踏まえ道路・ラベルが読める程度）。
  page.tsx側は矢印用のwindVectorGeoJsonと同じeffectiveWindGrid・frameIndexから
  windCellGeoJsonを算出し、粗い格子/詳細格子どちらが使われているかに応じて間隔も
  切り替える。Playwright実機確認（レスポンスモックで色の変化を含めた見た目を確認）:
  地図上に矢印と同色のセルが敷き詰められ、どの矢印がどの範囲を代表しているか一目で
  分かることを確認した。frontend vitest 425件（新規7件）全green、tsc/eslintクリーン。
  追記3（2026-08-20、ユーザー報告「地図に描画されない」・調査依頼）: 実機調査の結果、
  無風閾値`WIND_CALM_THRESHOLD_MS`（1.0m/s、T178当初の実機フィードバック「ほぼ無風でも
  矢印が出るのが違和感」に基づく設定）が原因と判明した。調査時点の実データ（王子周辺、
  詳細格子16点）が全点0.70〜0.81m/sと、関東でごく普通に起きる弱風（無風ではない）だが
  閾値未満という条件に揃っており、矢印が1本も表示されなくなっていた（`queryRenderedFeatures`
  で矢印0件・セルは16件描画済みを確認、セル塗り自体は正常。ただし対応する矢印が無いため
  「セル↔矢印の対応を示す」という機能の核心が体感できず、薄いセルの色だけでは
  「何も描画されていない」ように見えていた）。閾値を0.3m/sへ引き下げ、同じ実データで
  矢印9件が描画されることを実機確認した（修正前0件）。frontend vitest 426件全green、
  tsc/eslintクリーン。
  追記4（2026-08-21、ユーザー報告「風の表現、背景色が変わりきっていない（地図上部の
  一部が未反映）。背景色を付けると他要素と重ね合わせた時に分かりにくいのはある。背景色
  以外で、その範囲での風の強さ、を表す分かりやすい表現を提案して」→「背景色は消して。
  矢印をもう少し大きくして、風の強さについても長さと色でより目立つように」）: 上記
  追記2で追加したセル塗り（`WIND_VECTOR_BASE_CELLS_*`/`WIND_VECTOR_DETAIL_CELLS_*`
  レイヤー、`windGridToCellFeatureCollection`）を全撤去し、「矢印↔範囲の対応」という
  役割ごと矢印自体（大きさ・色のグラデーション）へ一本化した。セル塗りは道路・ルート等の
  他レイヤーと重なると見分けにくいという指摘に加え、base/detail 2層の境界（低ズームで
  detailが可視範囲の一部しかカバーしない領域）でbaseの薄い塗りとdetailの塗りが混在し
  「途中で塗り分けが変わって見える」不具合の温床にもなっていたため、面表現自体をやめる
  判断とした。矢印側は`WIND_ICON_MIN_SCALE`（0.7→0.9）・`WIND_ICON_MAX_SCALE`
  （1.9→2.6）を引き上げ、全体を一回り大きくしつつ弱風〜強風のスケール差（=矢印の長さの
  差）を拡大した（icon-sizeはMapLibreのsymbolレイヤー仕様上アイコン全体を一様スケール
  するため、太さも連動して変わる。色のグラデーション自体（`WIND_COLOR_SCALE_
  EXPRESSION`）は変更していない）。あわせて`windLayer.ts`の`windGridToCellFeatureCollection`・
  `WindCellFeatureProperties`・`WIND_GRID_SPACING_DEG`/`WIND_GRID_DETAIL_SPACING_DEG`
  （セル生成専用だった定数、他に利用箇所なし）を削除し、`page.tsx`/`MapView.tsx`から
  `windBaseCellGeoJson`/`windDetailCellGeoJson`の算出・受け渡し・依存配列を除去した。
  frontend vitest 441件全green（セル関連4件削除）、tsc/eslintクリーン。

### - [x] T182. get_forecast_many（複数地点）のOpen-Meteo取得変数を風のみへ絞る 規模S（2026-08-21完了）

- 発端: ユーザー報告「openmeteo の上限を超えてしまっているのか」。本番`/api/debug/stats`で
  直近デプロイ直後から`weather:open-meteo`が6/6件`http_429`、Open-Meteoへの直接curlで
  `"Daily API request limit exceeded. Please try again tomorrow."`を確認、日次クォータ
  枯渇と特定（T179で対策したRenderの共有送信元IP起因の429とは別種）。公式pricingページに
  よると無料プランは1地点あたり10変数超・2週間超で按分カウントが増える仕組み。
- 調査: T172（2026-08-20完了）で`get_forecast`（単一地点、`/api/weather`現在地パネル用）と
  `get_forecast_many`（複数地点、WindServiceの区間風評価・`get_wind_grid`の風格子点マップ用）
  の両方へcurrent 7変数・hourly 8変数を追加していたが、`get_forecast_many`の消費側
  （`wind_service.py`・`weather_service.py:_wind_grid_point_from_data`）を辿ると実際に
  使っているのはhourlyの`wind_speed_10m`/`wind_direction_10m`のみで、残り6変数
  （temperature・apparent_temperature・wind_gusts・precipitation・uv_index・
  precipitation_probability）は取得しているだけで捨てられていた。`get_forecast_many`は
  風の格子点マップで最大600〜900地点をまとめて1リクエストに乗せる、事実上ここが
  クォータ消費の主要因。
- 対応: `weather_client.py`へ`WIND_ONLY_VARIABLES`定数（`wind_speed_10m,wind_direction_10m`）
  を追加し`get_forecast_many`のcurrent/hourly両方をこれへ絞った。`get_forecast`
  （単一地点、`/api/weather`パネルは全8変数を実際に表示している）はT172のまま変更なし。
  キャッシュは`_forecast_cache`（get_forecast用）と`_wind_forecast_cache`
  （get_forecast_many用）へ分離——単一のキャッシュキーを共有すると、
  `get_forecast_many`が先に書き込んだ風のみの応答を`get_forecast`が後からキャッシュヒット
  として読んでしまい、`/api/weather`パネルの気温等が黙って空欄になる事故になり得るため
  （既存テスト`test_get_forecast_many_skips_already_cached_points`・
  `test_get_forecast_many_uses_stale_cache_for_point_that_fails_refetch`が
  この2メソッド間のキャッシュ共有を前提にしていたため、両方をget_forecast_many起点の
  ウォームアップへ書き換え、キャッシュ非共有の回帰テストを追加）。
- 完了条件: backend pytest全green。`get_forecast_many`のリクエスト変数数が
  15→2（現用4）へ削減され、`get_forecast`側の表示機能に影響がないこと。
- 実装メモ（2026-08-21完了）: backend pytest 951件全green（新規1件含む）。
  スコープ外の関連事実（記録のみ、本タスクでは対応しない）: T179で構築したOracle Cloud VM
  経由リレープロキシは、Render環境変数`OPEN_METEO_BASE_URL`が未設定のままのため本番では
  実際には未使用（[[oracle-cloud-postgis-migration]]）。今回の日次クォータ枯渇は送信元IPに
  依存しない現象と直接curlで確認済みのため、仮にT179を有効化しても解決しない可能性が高い
  （Open-Meteoの日次カウント方式がIP単位かどうか自体が未確認・要調査）。

### - [x] T183. 降水ナウキャストを60分より先も延長し、風と汎用化した自前実装で表示する 規模M（2026-08-21完了）

- 発端: ユーザー要望「雨情報を拡張できない？1時間より先も、短時間雨予報を出してほしい」。
  調査の結果、気象庁の降水ナウキャストAPI（`targetTimes_N2`）自体が+60分を上限とする
  仕様（JMA側の制約、回避不可）と判明。一方でOpen-Meteo経由のモデル予報（風の格子点
  マップが既に取得している`precipitation`変数）は約48時間先まで持つため、これを
  60分以降の延長予報として使う方針を提示したところ、ユーザーから「1時間より先は自前実装に
  切り替えて、風と同じ考え方で、風と汎用化して実装してほしい。アイコンは1つ。ただし
  内部は時間によって使い分けて。スライドバーも、1時間までは細いメモリ、1時間から先は
  1時間毎の粗いメモリに統合できる？」という具体的な実装方針の指示を受けた。
- 対応方針: 「降水」の地図チップ・時刻スライダーは1つのまま（新規チップは追加しない）とし、
  内部でデータ源を60分境界で切り替える。60分以内は既存の気象庁ナウキャストラスタタイル、
  60分以降は風の格子点マップ（`GET /api/weather/wind-grid`）が返す`precipitation_mm`を
  MapLibre symbolレイヤー（しずくアイコン、大きさ・色で強さを表現）として描画する。
  風とインフラを共有することで、Open-Meteoへのリクエスト自体を増やさない（T182で
  日次クォータ枯渇の対策をしたばかりのため、新規の外部リクエスト経路を増やさないことを
  優先した）。
- 実装メモ（2026-08-21完了）:
  **バックエンド**: `WindGridPoint`（`domain/wind_grid.py`）へ`precipitation_mm: list[float]`
  を追加。`weather_client.py`の`WIND_ONLY_VARIABLES`（`wind_speed_10m,wind_direction_10m`）を
  `WIND_GRID_VARIABLES`へ改名し`precipitation`を追加（3変数、無料プランのクォータ按分閾値
  「10変数超」を十分下回るためT182の対策効果は保たれる）。`weather_service.py:
  _wind_grid_point_from_data`は他の2フィールドと同じ厳格な検証（欠損・長さ不一致なら
  格子点ごとNone）をprecipitationにも適用。OpenAPIスキーマ・フロント型（`api.d.ts`）を
  再生成。backend pytest 853件（新規1件）全green。
  **フロントエンド（汎用化）**: 風の格子点フェッチ（元はpage.tsx直書き、約100行）を
  `hooks/useWeatherGrid.ts`へ抽出し、`enabled`引数で汎用化。降水延長予報も同じフックの
  同じ結果（`effectiveGrid`）を共有するため、`showWindVector || showPrecipitationNowcast`の
  どちらか一方でもONならフェッチが走る（1回のOpen-Meteo呼び出しで両機能ぶんを賄う）。
  `precipitationNowcast.ts`に`PRECIPITATION_COLOR_STOPS`（windLayer.tsのWIND_SPEED_COLOR_STOPSと
  同じ片側import設計）・`precipitationGridToFeatureCollection`・`buildCombinedPrecipitationFrames`
  （ナウキャスト0〜60分・5分刻みと延長予報60分以降・1時間刻みを1つの時系列へ束ねる。
  DynamicLayerTimeSliderがframes配列のindexをそのままスライダー刻みに使う設計のため、
  この間隔差がそのまま「1時間まで細かく、それ以降は粗い」目盛りになる。特別なUIロジックは
  不要）・`nearestCombinedPrecipitationFrameIndex`を追加。`MapView.tsx`は風の矢印と同じ
  symbolレイヤー構成（`createPrecipitationDropIcon`＝しずく形、sdf:true・ハロー層・
  無降水フィルタ）で延長予報アイコンを描画。アイコンサイズ式（風専用だった
  `windIconSizeExpression`）を`zoomAndPropertyIconSizeExpression`へ一般化し両方で共有。
  `mapLayers.ts`の説明文を更新。frontend vitest 457件（新規16件）全green、tsc/eslintクリーン。
  Playwright実機確認（devサーバー＋APIモック、`wind-grid`にprecipitation_mmを含めた
  レスポンスを返す）: 「降水」チップON→スライダーが「実況」から始まり、60分以内は
  ラスタタイル表示（アイコン無し）、スライダーを60分より先へ動かすとバッジが「広域予報」に
  変わり同時にしずくアイコンが出現、降水量に応じて色（弱い=水色〜猛烈=紫）・大きさが
  変わることを確認。60分以内でアイコンが出ないこと・60分超でタイルが出ないこと（相互排他）も
  確認した。

### - [x] T184. 動的気象レイヤー（風・降水）を共通契約で再設計する 規模M（2026-08-21完了）

- 発端: T183完了直後のユーザー実機フィードバック「動きがおかしい。動的レイヤについては
  今後もデータ追加があり得るので、それも見据えて拡張性がある設計、実装にしてほしい。
  格子単位は統一。格子中央にマークを出す（風パターン）または格子を指定色で塗る
  （雨パターン）で表現する。時間経過はスライドバー1本で表現する。該当時間データがない
  場合、地図には描画しない。1要素（雨）でも、データの取り方が複数あり得る。（ナウキャスト
  ＋自前取得）これはデータ取得層Nだが、差異はデータ取得層で吸収。画面表示時にはそれは
  意識しないようにしたい」。T183実装（しずくアイコン＋独立スライダー2本、風・降水延長
  予報それぞれに専用の関数対）は機能としては動いていたが、レイヤーごとに個別の
  source/layer管理・アイコン形状・スライダーを持つ設計だったため、要素が増えるたびに
  同じ配線をコピーする必要があり、2本のスライダーが同じ時刻を指しているのか・どちらが
  どのデータ範囲を持つのかも分かりにくかった。
- 対応方針（ユーザー承認: 「案A前提でお願い。実装して」）: 3層構成へ再設計する。
  (1) **データ取得層**（要素ごとのモジュール、`windLayer.ts`/`precipitationNowcast.ts`）が
  各要素固有のデータソース（降水ならナウキャスト+風と共有の格子点マップの2つ）を吸収し、
  共通のフレーム列（`DynamicWeatherFrame`）とペイロード関数を返す。(2) **共通契約層**
  （新設`dynamicWeather.ts`、DOM/MapLibre非依存の純粋関数のみ）が、表現を`gridMark`
  （格子中央にマーク、風パターン）・`gridFill`（格子を色で塗る、雨パターン）の2種類に
  限定し、例外として気象庁ナウキャストのような「配信元が描画済みの画像」用に`rasterTile`を
  1つだけ許容する（JMAのナウキャストタイルはCORS制限で数値格子へ変換できず、画像として
  重ねるほかない）。全レイヤーのフレーム時刻を`mergeFrameTimes`で1本のタイムラインへ統合し
  共有スライダーへ渡す。選択時刻がレイヤー自身のデータ範囲外なら`frameIndexForTime`が
  `null`を返し「描画しない」（旧: 端のフレームへクランプして古いデータを見せ続ける挙動を
  廃止）。(3) **表示層**（`MapView.tsx`/`page.tsx`）はペイロードの`kind`だけを見て描画し、
  データソースの区別を一切意識しない。新しい動的要素を追加する手順を4段階の「1本道」として
  `dynamicWeather.ts`冒頭にコメントで明文化した。
- 実装メモ（2026-08-21完了、フロントエンドのみ・バックエンドは変更無し）:
  **共通契約層**: `dynamicWeather.ts`を新設。`DYNAMIC_WEATHER_LAYER_IDS`（要素一覧の
  単一の情報源）・`DynamicWeatherRenderPayload`（`rasterTile`/`gridFill`/`gridMark`の
  判別union）・`mergeFrameTimes`・`frameIndexForTime`・`nearestTimeIndex`・
  `formatDynamicFrameTime`・`gridCellRing`（gridFillのセルジオメトリ生成）を実装。
  **データ取得層**: `windLayer.ts`は`windGridToFeatureCollection`を非公開化し、
  `windFrames`/`windRenderPayload`（gridMark）を追加。`precipitationNowcast.ts`は
  `buildCombinedPrecipitationFrames`等の旧関数群を`precipitationFrames`
  （`PrecipitationFrameRef = {source:"nowcast"|"extended", index}`を持つフレーム列）・
  `precipitationRenderPayload`（sourceに応じてrasterTile/gridFillを切替）・
  `precipitationGridSpacingDeg`へ置き換えた。**表示層**: `MapView.tsx`はレイヤーごとに
  重複していた`ensureXxxLayer`/`applyXxxState`関数対（3組）を、宣言的スペック
  （`DynamicWeatherRendererSpec`、raster/gridFill/gridMarkそれぞれの色・サイズ・
  アイコン生成関数を持つ）を引数に取る汎用関数対
  `ensureDynamicWeatherLayer`/`applyDynamicWeatherState`へ統合し、要素ごとの差異は
  `DYNAMIC_WEATHER_RENDERERS`テーブル1箇所へ集約した（風のストリームラインアイコン
  描画自体は変更無し、降水延長予報の旧しずくアイコンはgridFill化に伴い撤去）。
  `MapViewProps`の個別5フィールド（`showPrecipitationNowcast`等）を単一の
  `dynamicWeather: Partial<Record<DynamicWeatherLayerId, {visible, payload}>>`へ統合し、
  props destructure・`redrawPropsRef`・依存配列・`redrawAllLayers`・3箇所のapply呼び出しの
  計6箇所以上あった配線をO(1)化した。`page.tsx`は風・降水それぞれの独立したフレーム
  index計算・2本のスライダー状態を廃止し、`mergeFrameTimes`で統合した1本の
  `timeline`・`sliderIndex`・`handleSliderIndexChange`と、`frameIndexForTime`で
  導出する各要素のpayloadを持つ単一の`dynamicWeather`メモ化オブジェクトへ置き換えた。
  `DynamicLayerTimeSlider`は複数レイヤー同時対応が前提のUIになったため、レイヤー固有の
  `badge`・`unavailable`/`unavailableLabel`プロパティを撤去（1つの目盛りに複数レイヤーが
  同時に対応しうる設計では「このレイヤーの実況/予測」「対応データなし」という単一レイヤー
  向けの概念が意味を持たなくなったため）。tsc/eslintクリーン、frontend vitest 458件
  （新規: dynamicWeather.test.ts追加、windLayer.test.ts/precipitationNowcast.test.ts/
  DynamicLayerTimeSlider.test.tsxを新APIへ更新）全green。

### - [x] T185. 降水延長予報gridFillの格子間隔をズーム依存で細かくする 規模S（2026-08-21完了）

- 発端: T184デプロイ後の実機フィードバック（本番スクリーンショット）「このゴワゴワ感を
  直すには、格子を小さくするしかない？拡大率が大きいと気になる。拡大率によって格子
  サイズも大きく（風の矢印と同じ）補正する汎用的な拡張はできない？」。降水延長予報の
  gridFill表現は「1格子点が担当する実面積」を色で塗る図形のため、風の矢印のicon-size
  ズーム補正（ピクセル単位の記号を拡大するだけ）とは事情が違う——セルの表示サイズだけを
  ズームに応じて縮めても、格子点自体の間隔（＝実データの密度）は変わらないため、単に
  隙間が空くだけで「ゴワゴワ」（色境界の段差）は解消しない。回答として、ズームインする
  ほど画面上の面積を大きく占める同じ間隔の格子が段差を目立たせているのが根本原因なので、
  格子間隔自体をズームに応じて細かくする方針を提示し、ユーザー承認（「まずはズーム依存で
  detail格子のspacingを段階的に細かくするので実装して」）を得て実装した。
- 対応方針: 詳細格子（改善計画T180、`generate_wind_grid_detail_points`）は元々`spacing_deg`
  引数を持っていたが、APIエンドポイントが常にデフォルト値（0.02度）で固定呼び出ししていた。
  これをフロント側がズームに応じて選んだ離散値（0.02/0.01/0.005/0.0025度、ズーム10/13/16/19の
  4段階）をクエリパラメータとして渡せるように拡張した。連続値にすると閲覧者ごとに格子の
  絶対座標（ラティス原点固定によるキャッシュ共有、T180実装メモ参照）がずれてキャッシュが
  効かなくなるため、離散段階のみ許可する（バックエンドでも許可値リスト外は400で拒否）。
- 実装メモ（2026-08-21完了）:
  **バックエンド**: `domain/wind_grid.py`へ`WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG =
  (0.02, 0.01, 0.005, 0.0025)`を追加（単一の情報源、フロント側windLayer.tsのズーム段階と
  値を揃えること）。`api/routers/weather.py: get_wind_grid_detail`へ`spacing_deg`クエリ
  パラメータ（省略時は既存の0.02、後方互換）を追加し、許可値リスト外は400、
  `generate_wind_grid_detail_points`へそのまま渡す。点数上限チェック（`WIND_GRID_DETAIL_
  MAX_POINTS`、900点）は間隔に関わらず既存のロジックのまま機能する（間隔を細かくした分
  だけ同じbboxで点数が増えるため、広いbbox×細かい間隔の組み合わせは自然に400になる）。
  **フロントエンド**: `windLayer.ts`へ`WIND_GRID_DETAIL_SPACING_STOPS`（ズーム→間隔の
  4段階テーブル）・`windGridDetailSpacingDegForZoom(zoom)`を追加。`clampWindDetailBbox`は
  固定0.5度だったクリップ幅を`spacingDeg引数 × 25`（間隔なりに比例、900点上限に対し
  26×26=676点の安全マージンは維持）へ一般化。`weatherApi.ts: getWindGridDetail`が
  `spacing_deg`をクエリへ追加。`useWeatherGrid.ts`はズームから`spacingDeg`を都度計算して
  bbox・APIへ渡し、実際にフェッチへ使った値を`effectiveGridSpacingDeg`として返す
  （`precipitationRenderPayload`のセルサイズ計算がズレないよう、呼び出し側が再計算せず
  フック側の実測値をそのまま使う設計）。ズームをまたいで間隔が変わった回は、穴あき対策の
  持ち越し（`mergeWindGridKeepingStale`）を諦めて新しい間隔で作り直す（間隔の異なる格子点は
  同じラティスに乗らないため混在させると不整合になる）。`precipitationNowcast.ts`の
  `precipitationGridSpacingDeg(isDetail: boolean)`（粗い/詳細の2値切替のみ対応していた）は
  不要になったため撤去し、`page.tsx`は`effectiveGridSpacingDeg`をそのまま
  `precipitationRenderPayload`へ渡すよう更新。
  backend pytest 857件（新規4件）・frontend tsc/eslintクリーン・vitest 462件（新規: 段階
  マッピング・bboxクリップ・フック配線のテストを追加）全green。

### - [x] T186. スマホで地図のピンチズームが反応しないことがある不具合を修正 規模XS（2026-08-21完了）

- 発端: 実機フィードバック「スマホで地図上ピンチアウト、ピンチインが効かないことがある」。
- 原因: 地図キャンバスに重なるDOM要素は`touch-action: none`を明示しないと、2本指ピンチの
  片方の指がその要素へ乗った瞬間にブラウザがタッチ開始点ごとのtouch-actionを見て地図
  ジェスチャーとして確定できなくなる（2026-08-16に現在地ボタン、別途MapOverlayControlsの
  アイコンチップ等で同様の不具合を修正済みの既知パターン、両ファイルの`touch-action: none`
  コメント参照）。1回目の修正で`DynamicLayerTimeSlider`（地図下部中央に浮く時刻スライダー、
  T184で風・降水の2本を1本へ統合）の漏れに対応したが、ユーザーから「スライダー以外でも
  再現した」との追加報告を受け、`position: fixed`/`position: absolute`で地図に重なる
  全要素を`touch-action`/`pointer-events`の指定有無で再監査したところ、モバイル下部固定の
  `.mobileTabBar`（「ルートを作る」/「地図の見え方」等のタブ、`page.module.css`）にも
  同じ漏れが見つかった。`.locateButton`/`.locateError`/`.dynamicLayerSliders`がこのバーに
  隠れないようbottom側をタブバー高さぶん底上げしているコメントから分かるとおり、地図
  キャンバス自体はこのバーの下にも常時描画されており（`.mapPane`側はバーぶんの余白を
  確保していない）、画面下端は常にこのバーと地図が重なっている。スライダーが特定条件
  （動的気象レイヤーON時）でしか出ないのに対し、タブバーは常時・全画面で出ているため、
  こちらの方が「スライダー以外でも」再現した実体だった可能性が高い。
- 対応: `DynamicLayerTimeSlider.module.css`の`.row`・`.loading`・`.error`（いずれも
  `pointer-events: auto`で実際にタッチを受け止める箱）へ`touch-action: none`を追加。
  `page.module.css`の`.mobileTabBar`（バー自身、隙間なく子の`.tabButton`で埋まっているため
  祖先へ一括指定）と、コードベースの既定方針（`.iconChip`等と同じく実際に押せる要素へも
  明示する）に合わせて`.tabButton`自身にも`touch-action: none`を追加。親の`.wrapper`
  （`.dynamicLayerSliders`）は元から`pointer-events: none`で当たり判定を持たないため対応
  不要（他の隙間と同じく地図キャンバスへタッチを素通しする）。`position: fixed`/
  `position: absolute`で地図に重なりうる全CSS moduleを再監査し、他に漏れが無いことを確認
  した（MapOverlayControls・BottomSheet・FloatingPanel・locateButton/locateError・MapView
  loadingOverlayはいずれも対応済み）。Playwright実機確認（モバイル幅・タッチ有効の
  コンテキスト）で、`.row`・`.mobileTabBar`・`.tabButton`いずれも`getComputedStyle().
  touchAction`が`"none"`（修正前は`"auto"`）になることを確認した。CSSのみの変更のため
  テストファイルの追加は無し。

### - [x] T187. 観測グループの凡例展開▶が条件によって消える不具合を修正 規模XS（2026-08-21完了）

- 発端: 実機フィードバック「たまに凡例を出すための▶が消える」（本番モバイル実機
  スクリーンショット、観測グループを開いた状態で「道路種別」「路面」の隣に▶が無い）。
- 原因: `MapOverlayControls.tsx`の`OverlayLayerChip.summary`は元々「legendDetailsが空
  （描く凡例が無い）ときの唯一の表示内容」（例:「ズームインすると表示されます」、
  interfaceのdocstring参照）として設計されており、単独チップの描画（末尾の
  `canExpand = layer.on && !layer.disabled && (hasLegendDetails || Boolean(layer.summary))`）
  は正しくこれを反映していた。一方、観測/動的グループのメンバータイル
  （`renderRawMemberTile`）は`canExpand`が`legendDetails`の有無だけで判定されており、
  `summary`が考慮されていなかった。`page.tsx`の`roadTypeLegendDetails`/
  `roadSurfaceLegendDetails`は`regionZoomTooWide`（地図が道路タイルの最低ズーム未満）の間
  空配列になり、代わりに`roadTypeSummary`/`roadSurfaceSummary`が「ズームインすると
  表示されます」を返す設計だったため、ズームアウトするたびに道路種別・路面の▶が
  （案内文を出す手段ごと）消えていた。「たまに」に見えたのは、ズーム操作のたびに
  この条件が切り替わっていたため。
- 対応: `renderRawMemberTile`の`canExpand`を単独チップ側と同じ
  `Boolean(!member.disabled && (hasLegend || member.summary))`へ揃え、`panelContent`も
  `hasLegend`が偽のときは`<p className={styles.detailNotice}>{member.summary}</p>`
  （単独チップ側と同じ`.detailNotice`表示）へフォールバックするよう修正。
  `MapOverlayControls.test.tsx`に回帰テストを2件追加（legendDetails空+summary有りで▶が
  出て案内文が開ける／legendDetails空+summary無しでは▶が出ない）。一度フィックスを
  意図的に戻して新規テストが実際に落ちることを確認してから復元し、テストが不具合を
  正しく検知することを確認済み。frontend tsc/eslintクリーン・vitest 464件（新規2件）
  全green。

### - [x] T188. 全クリアアイコンを時刻スライダー隣へ移動し、降水の色分け凡例・時刻スライダーの目盛りを細かくする 規模S（2026-08-21完了）

- 発端: 実機フィードバック「左上の全クリアアイコンを、スライドバーの左側に移動して。
  雨の凡例をもう少し段階細かくして。スライドバーの左半分ぐらいまでは細かく。右半分は
  1時間単位でできない？あとメモリを簡潔に出せれば出して」。「左半分は細かく・右半分は
  1時間単位」の対象を確認したところ（現状のスライダーはインデックスが均等間隔で、
  「細かい部分」＝降水ナウキャスト区間はバー全体の2割程度であり半分ではない）、
  ユーザーからは「時刻スライダーの目盛り表示だけ追加と、雨の色分け凡例追加の2つを実施」
  との回答を得た（間隔設計＝T183で決めたナウキャスト60分上限・延長予報48時間先までの
  配分自体は変更しない）。
- 対応1（全クリアアイコンの移動）: `MapOverlayControls.tsx`が自前で持っていた全レイヤー
  一括OFFボタン（`handleClearAll`/`hasAnyLayerOn`、地図左上の`.wrapper`内）を撤去し、
  同じロジックを`page.tsx`（`handleClearAllLayers`、既に`overlayLayers`/`handleLayerToggle`
  を持つため）へ移設。地図下部中央の時刻スライダーと同じ行（新設`.bottomControlRow`、
  `page.module.css`。旧`.dynamicLayerSliders`が持っていたposition/z-index等をここへ
  集約し、`.dynamicLayerSliders`自体は並び方向だけを持つ内側のflexへ縮小）に並べ、
  スライダー左側に常時表示する。時刻依存レイヤーがOFFでスライダー自体が無いときも
  ボタン単体で機能を保つ（レイヤーの種類を問わない一括OFFのため）。
- 対応2（時刻スライダーの目盛り）: `DynamicLayerTimeSliderFrame`へ`hourMark?: boolean`を
  追加し、`page.tsx`の`sliderFrames`が各フレームの`time.getUTCMinutes() === 0`（正時判定。
  JSTはUTC+9:00ちょうどで分のずれが無いためタイムゾーンに左右されない）から算出して渡す。
  `DynamicLayerTimeSlider.tsx`は`hourMark`なフレームだけを`<datalist>`の`<option>`にし、
  `input[type=range]`の`list`属性で参照する（ネイティブの目盛り表示、複数スライダー同時
  マウント時のid衝突は`useId()`で回避）。スライダー自体のつまみ位置は既存どおりインデックス
  線形のまま変更しない。降水ナウキャスト区間（5分刻み）は正時フレームがまばらにしか
  無いため目盛りもまばらに、延長予報区間（1時間刻み）は全フレームが正時のため毎コマに
  目盛りが付き、「近い将来は連続的に細かく動かせる・遠い将来は1時間刻みで止まる」という
  既存の間隔設計がそのまま目盛りの疎密として伝わる。
- 対応3（降水の色分け凡例）: `precipitationNowcast.ts`の`PRECIPITATION_COLOR_STOPS`
  （地図チップの凡例とMapView.tsxのfill-color補間式の単一の情報源）に1mm/hの閾値を追加し
  0mm/h（小雨）と1mm/h（弱い雨）を分離（気象庁公式「雨の強さと降り方」に10mm/h未満の
  区分が無いため、天気アプリで広く使われる1mm/hの目安＝傘の要不要の境目で分けた、
  10mm/h以上の境界値は引き続き気象庁公式のまま）。`PRECIPITATION_INTENSITY_LEVELS`
  （手書きの7段配列、`PRECIPITATION_COLOR_STOPS`から自動導出ではないため個別に追記）も
  合わせて更新。`MapView.tsx`のfill-color式は`PRECIPITATION_COLOR_STOPS`を`flatMap`で
  組み立てる設計のため変更不要（単一の情報源、片側import）。
- 検証: `MapOverlayControls.test.tsx`から移設済みの全クリアボタンのテストを撤去（コメントで
  移設先を明記）。frontend tsc/eslintクリーン・vitest全461件green。

### - [x] T189. 降水の色分け凡例をさらに細分化し、時刻スライダーをネイティブrange inputから横スクロールのルーラーへ置き換える 規模M（2026-08-21完了）

- 発端: T188に続く実機フィードバック（他の天気アプリの雨雲レーダー画面のスクリーンショットを
  参考画像として提示）「雨の判例ももっと細かくして。参考にしてほしいサイトをはる」と
  「スライドバーを折りたたみ式にして。目盛りを送るのではなく、折りたたみエリアをスライドすると
  動くイメージ」。後者は実装方針を確認したところ「まず画面（モックアップ）で見た目を確認して
  から決めたい」との回答を得たため、Artifactで現状比較・2ゾーン非線形案・蛇腹（アコーディオン）
  案の3種をドラッグ操作できるモックアップとして提示した。ユーザーの結論は「見た目は現状のまま
  で良くて、横スクロールでメモリの方が移動するようにしたい」——モックアップの非線形ゾーン・
  ひだ表現は不要で、外枠の見た目（ピル型の箱・時刻ラベル・「現在」ボタン）は変えず、操作方式
  だけをネイティブrange inputのつまみドラッグから、目盛り自体を横スクロールで動かす方式へ
  変更する、という結論だった。
- 対応1（降水の色分け凡例、参考: 他アプリの雨雲レーダー凡例）: `precipitationNowcast.ts`の
  `PRECIPITATION_COLOR_STOPS`を7段階→9段階へ拡張。10mm/h未満を0.4/2/4mm/hの3閾値でさらに
  細分化し、「ポツポツ」「パラパラ」「ザーッ」「ザーザー」という体感表現ラベルを追加した
  （気象庁の「雨の程度を表すことば」にも載る一般的な表現であり特定アプリ固有ではないため
  採用、ブランド固有のアイコン・配色は再現していない）。20mm/h以上は引き続き気象庁公式の
  「雨の強さと降り方」のまま。`PRECIPITATION_INTENSITY_LEVELS`も合わせて更新。
  `MapView.tsx`のfill-color式は`PRECIPITATION_COLOR_STOPS`を`flatMap`で組み立てる設計のため
  変更不要（単一の情報源）。
- 対応2（時刻スライダーの操作方式変更）: `DynamicLayerTimeSlider.tsx`のネイティブ
  `input[type=range]`を撤去し、横スクロール可能なルーラー（`.rulerViewport`、CSS
  `scroll-snap-type: x mandatory`）へ置き換えた。中央固定の目印（`.centerIndicator`、
  `.rulerViewport`の直接の子としてposition: absoluteで置くことでスクロールする
  `.rulerTrack`とは独立させる）へ、目盛りの方をスクロールで合わせにいく操作感になる。
  トラック左右に`calc(50% - TICK_SPACING_PX/2)`のパディングを入れることで、
  `scrollLeft = index * TICK_SPACING_PX`という単純な対応関係になるよう設計した
  （layoutEffect側の同期・スクロール確定時のindex算出の両方がこの前提）。「現在」ボタン等
  外部からのindex変化のときだけプログラムでスクロールし直す（`syncedIndexRef`で自分の
  スクロール由来か外部由来かを判別、無限スクロールループを回避）。ネイティブrange input
  が無償で持っていたキーボード操作・ARIAセマンティクスは自前で用意（`role="slider"`+
  `aria-valuemin/max/now/text`、矢印キー・Home/End）。目盛りの線（`hourMark`、正時判定）と
  文字ラベル（新設`tickLabel`）を分離: 延長予報区間は全コマが正時のため`hourMark`のまま
  毎コマ文字を出すとTICK_SPACING_PX（22px）に対して文字幅が重なる不具合を実機Playwright
  確認で発見し、`tickLabel`は3時間おきへ間引く別フィールドとして追加した。
  `touch-action`は`.row`全体への一括`none`指定だと積集合の仕様上`.rulerViewport`の
  `pan-x`（横スクロールに必要）まで打ち消してしまうため、`.row`からは外し実際にタップする
  要素（`.time`・`.nowButton`）へ個別に指定する方針へ変更（MapOverlayControls.module.cssの
  `.iconChip`等と同じ「実際に押せる要素へも明示する」既存方針に揃えた）。
- 検証: 一時的な検証用ページ（コミット対象外）とPlaywrightで実際にdevサーバー上のコンポーネントを
  操作し確認（デスクトップ: キーボード矢印/Home/End・マウスホイールでのindex変化とARIA値、
  モバイル想定コンテキスト: タッチタップとtouch-action計算値）。`.rulerViewport`は
  `pan-x`、`.nowButton`/`.time`は`none`になっていることを確認し、コンソールエラー無し。
  スクロール操作は`scrollLeft = index * TICK_SPACING_PX`の設計どおり一致することも確認した
  （ホイール操作後、`scrollLeft=352`で`index=16`＝`352/22=16`）。`DynamicLayerTimeSlider.test.tsx`
  はrole="slider"のARIA値とキーボード操作（矢印キー・境界・Home/End）を検証するテストへ
  更新（jsdomは実際のスクロール・レイアウトを実装しないため、横スクロールジェスチャー自体は
  ユニットテストでは検証できない旨をコメントに明記）。frontend tsc/eslintクリーン・
  vitest全464件green。

### - [x] T190. 時刻スライダーの左端インジケータ化・目盛りラベルの短文化・密度調整 規模S（2026-08-21完了）

- 発端: T189に続く実機フィードバック「ルーラーにもう少し目盛りを細かく表示して。日付部分は
  不要、時刻のみ。時刻も細いところは分だけにする等」「左端を表示時刻にして。今の位置の正しい
  日時は左端ではなく上に出して」。
- 対応1（目盛りラベルの短文化・密度）: `dynamicWeather.ts`に`formatDynamicFrameHourMinute`
  （日付無し、HH:mm）・`formatDynamicFrameMinuteOnly`（分のみ2桁、`getUTCMinutes()`で
  JST判定）を追加（`formatDynamicFrameTime`はこの2つを内部で合成する形へリファクタ）。
  `DynamicLayerTimeSliderFrame.tickLabel`をboolean→string（実際に出す短い文字列、
  `undefined`で非表示）へ変更。`page.tsx`側で正時のコマは`formatDynamicFrameHourMinute`
  （2時間おきに間引き、T189の3時間おきから密度を上げた）、正時でない密なコマ
  （降水ナウキャストの5分刻み等）は`formatDynamicFrameMinuteOnly`を毎コマぶん出す
  （文字が短いため間引き不要）。目盛りの間隔自体（`TICK_SPACING_PX`）も22px→18pxへ縮小し
  「もう少し目盛りを細かく」に対応。
- 対応2（左端インジケータ化・正確な日時の上段表示）: `DynamicLayerTimeSlider.tsx`の選択位置
  インジケータを画面中央固定（`.centerIndicator`）から左端寄り固定（`.leftIndicator`、
  `TICK_SPACING_PX`の半分だけ内側の固定px位置）へ変更。`.rulerTrack`のパディングも
  左右対称（`calc(50% - N/2)`）から左0・右`calc(100% - Npx)`（最後のコマの中心も
  インジケータへ届くだけの余白）へ変更。indexとscrollLeftの対応式
  （`scrollLeft = index * TICK_SPACING_PX`）はどちらの配置でも同じ式になるよう意図的に
  設計したため、layoutEffect/handleScroll側のロジック自体は変更不要だった。外枠
  （`.row`→`.panel`、実機フィードバック「見た目は現状のままで良くて」のT189から続く方針）は
  縦2段（`.timeHeader`＝正確な日時のフル表記1行＋`.controlsRow`＝ルーラーと現在ボタンの
  横並び）へ変更し、以前ルーラーの左に横並びだった現在時刻ラベルを上段へ移した
  （実機フィードバック「今の位置の正しい日時は左端ではなく上に出して」）。
- 検証: 一時的な検証用ページ（コミット対象外）とPlaywrightで実際にdevサーバー上の
  コンポーネントを操作し確認。マウスホイールでのスクロール後、`scrollLeft`から算出した
  indexとコンポーネントが報告したindexが一致すること、インジケータが左端付近（ルーラー
  左端から`TICK_SPACING_PX/2`とほぼ一致する数px）に位置すること、目盛りラベルが意図通り
  （正時は2時間おきに"HH:mm"、それ以外は毎コマ分のみ2桁）表示され重ならないことをスクリーン
  ショットで確認、コンソールエラー無し。`DynamicLayerTimeSlider.test.tsx`はテキスト内容の
  変更の影響を受けないため無修正でも通ることを確認。frontend tsc/eslintクリーン・
  vitest全464件green。

### - [x] T191. 時刻スライダー（ルーラー）が縦ホイール・マウスドラッグでスクロールできない不具合を修正 規模S（2026-08-21完了）

- 発端: T190直後の実機フィードバック「ルーラースクロールできない」。
- 原因調査: 一時的な検証用ページ（コミット対象外）とPlaywrightで、想定される操作手段を
  1つずつ再現した。トラックパッドの横スワイプ・実機のタッチスワイプ（`Input.
  dispatchTouchEvent`で再現）はいずれも問題無く`scrollLeft`が変化した一方、**普通のマウス
  ホイール（縦方向のdeltaYのみ、`mouse.wheel(0, 200)`で再現）では`scrollLeft`が一切変化
  しなかった**（横スクロール専用要素はブラウザの既定動作では縦方向のホイール入力に反応
  しない）。加えて`.rulerViewport`はスクロールバー自体をCSSで非表示にしていたため、
  スクロールバーをドラッグする手段も無く、**マウスだけの環境（トラックパッド・タッチ無し）
  では操作する方法が実質無い**ことが分かった。
- 対応: `DynamicLayerTimeSlider.tsx`に2つの操作手段を追加した。(1) ネイティブの`wheel`
  イベントを`useEffect`+`addEventListener(..., {passive: false})`で購読し、縦方向の
  deltaYが横方向より大きいときだけ`scrollLeft`へ変換する（ReactのonWheelはReact 17以降
  ルート委譲がpassive: trueで登録されるため、合成イベント内で`preventDefault`を呼んでも
  無効化されない仕様のため、ネイティブのリスナーを直接張る必要があった）。(2)
  `pointerdown/move/up/cancel`でマウス限定（`pointerType === "mouse"`）のドラッグスクロール
  を実装し、`cursor: grab`で掴めることを示す。トラックパッド・タッチはブラウザの
  ネイティブスクロール（`touch-action: pan-x`）に引き続き任せ、二重処理にならないよう
  `pointerType`で分岐した。
- 検証: 検証用ページ+Playwrightで、縦ホイール・マウスドラッグ・実機相当のタッチスワイプの
  3手段それぞれについて、操作後の`scrollLeft`とコンポーネントが報告したindexが
  `scrollLeft = index * TICK_SPACING_PX`の対応どおりになることを確認した（修正前は
  縦ホイールだけ`scrollLeft`が0のまま変化しなかったことも合わせて確認済み）。
  `DynamicLayerTimeSlider.test.tsx`（キーボード操作・ARIA値の既存テスト）は無修正のまま
  全green。frontend tsc/eslintクリーン・vitest全464件green。

### - [x] T192. 時刻スライダー（ルーラー）がスマホの横スクロールで動かせない不具合を修正 規模S（2026-08-21完了）

- 発端: T191直後の実機フィードバック「スマホで変わらず横スクロールでバーを動かせない」。
  T191では縦マウスホイール・マウスドラッグの不具合（`scrollLeft`が変化しないことを
  Playwrightで確認済み）を修正したが、それとは別にスマホのタッチスクロールは元々別経路
  （ブラウザのネイティブタッチスクロール、`touch-action: pan-x`）に任せる設計のままで、
  そちらが実機で機能していなかった。
- 調査: 一時的な検証用ページ（コミット対象外）で、実際のページと同じ祖先要素
  （`page.module.css`の`.bottomControlRow`/`.dynamicLayerSliders`、`translateX(-50%)`の
  transformを含む）を再現し、Playwright+CDPの`Input.dispatchTouchEvent`でタッチスワイプを
  合成して検証したが、この検証環境（Chromiumのタッチエミュレーション）では`scrollLeft`が
  正しく変化する挙動しか再現できず、実機（iOS Safari等）特有の挙動差を主要因として
  切り分けることはできなかった。
- 対応: ブラウザのネイティブタッチスクロール（`touch-action: pan-x`）への依存をやめ、
  タッチ・マウス・ペンのいずれもPointer Events（`pointerdown/move/up/cancel`）で統一的に
  自前ドラッグする設計へ変更した（T191で追加したマウス限定のドラッグ処理を拡張し、
  `pointerType`による分岐を撤去）。`.rulerViewport`の`touch-action`は`pan-x`から`none`へ
  変更し、ブラウザ自身のジェスチャー処理と自前のドラッグ処理が競合しないようにした
  （他の地図上コントロール＝`MapOverlayControls.module.css`の`.iconChip`等と同じ
  「touch-action: none+実際のジェスチャーはJSで処理」という既存方針にも揃う）。
  併せて、ネイティブスクロールに依存しなくなったことで意味を失った`scroll-snap-type`/
  `scroll-snap-align`をCSSから削除し、代わりに`handleScroll`の確定処理（スクロールが
  止まったタイミングで最寄りのコマへ寄せる）自体に、厳密なコマ位置への明示的な
  スクロール（`scrollTo`のsmooth）を追加した（自前ドラッグではCSSのscroll-snapに
  相当する「ぴったりの位置へ寄せる」処理を自前で担う必要があるため）。
- 検証: 検証用ページ+Playwrightで、実際のページと同じ祖先要素の中でタッチスワイプ
  （CDP合成）を再現し、`scrollLeft`とonIndexChangeで報告されたindexが一致することを
  確認。キーボード操作・ARIA値の既存テストは無修正のまま全green。frontend
  tsc/eslintクリーン・vitest全464件green。なお実機（特にiOS Safari）での最終確認は
  ユーザー側にお願いする必要がある旨、申し送り。

### - [x] T193. 時刻スライダー（ルーラー）がスマホ・フルブラウザともドラッグに無反応な不具合を修正 規模XS（2026-08-21完了）

- 発端: T192直後の実機フィードバック「スマホでも、フルブラウザでも動かない」。本番
  （Render）へのデプロイ反映（`/api/version`のcommitが最新と一致）は確認済みの上での報告。
  具体的な症状: 「スマホでは、目盛り部分を指で左右にスクロールしても何も動かない」
  「フルブラウザでは、目盛り部分にマウスを乗せるとハンドアイコンに変わるが、左右に
  動かしても何も反応しない」。
- 原因: T192で追加した自前のPointer Eventsドラッグ実装（`handlePointerDown`/
  `handlePointerMove`）が`e.preventDefault()`を呼んでいなかった。カーソルがハンド
  アイコンに変わる（CSSの`cursor: grab`は効いている＝要素自体は正しく特定できている）のに
  ドラッグそのものが反応しないという症状は、ブラウザの既定動作（mousedown+dragによる
  テキスト選択ドラッグ等）が`pointermove`と競合し、スクリプト側の`scrollLeft`更新が
  見た目に反映されない典型的なパターン。Playwright（CDPによるマウス/タッチイベント合成）
  では合成入力の性質上この既定動作が顕在化せず、検証環境では問題なく動いているように
  見えていたため、これまでの調査で見落としていた。
- 対応: `handlePointerDown`/`handlePointerMove`に`e.preventDefault()`を追加。
  `setPointerCapture`は一部のブラウザ/状況で例外を投げることがあるためtry/catchで囲み
  失敗しても致命的にならないようにした。CSS側にも`-webkit-user-drag: none`（WebKit系が
  要素を暗黙にドラッグ可能とみなすのを防ぐ）・`-webkit-tap-highlight-color: transparent`
  （タップ時の既定ハイライトを消す、`MapOverlayControls.module.css`の`.iconChip`等と
  同じ理由）を追加し、ブラウザの既定ジェスチャーとの競合要因を減らした。
- 検証: 検証用ページ+Playwrightで、ドラッグ中に`window.getSelection()`が空のまま
  （テキスト選択が発生していない）ことと、`scrollLeft`/indexが引き続き正しく変化する
  ことを確認。ただしPlaywrightの合成入力では元の不具合自体を再現できなかったため、
  この対応が実機での症状を実際に解消したかどうかはユーザー側の実機確認が必要。
  frontend tsc/eslintクリーン・vitest全464件green。

### - [x] T181. 観測グループ等の地図チップがメンバー増加で再び見切れる対策〔T128の2段目〕規模S〜M（2026-08-22完了）

- 発端: ユーザー報告（本番モバイル実機スクリーンショット、2026-08-20）「縦アイコンが多くて
  見切れるようになってきた。研究画面として今後も追加しそうなので、今のレイアウトの
  考え方を踏襲しながら収める方法を提案して」。T128（カテゴリ束ね、2026-08-19完了）で
  9〜11個のフラットなチップ列を推定/観測/動的の3グループへ折りたたんだが、観測グループ
  自体が展開されると道路種別・路面・指定路線・停止要因・事故・インフラ・標高図・補給休憩の
  8メンバーが再び縦一列に並び、モバイル画面では下部の時刻バー等と競合して見切れる
  （`.chipRow`は`overflow-y: auto`のスクロールでは受けているが、スクロール必須自体が
  「見切れる」という体感になっている）。
- 当初案（不採用）: `MapLayerDescriptor.category`を観測グループのもう1段の自動折りたたみ
  として使い、観測グループを開くとまずカテゴリ見出し（5個）だけを見せ、カテゴリを開くと
  その1〜3メンバーが出る2段構成にする案を最初に実装したが、ユーザーから「実施内容
  イメージが違う。推定、観測アイコンをクリックすると、表示するアイコンをonoffできる
  ようにするイメージだったはず」と指摘を受け撤回した。カテゴリという新しい自動分類軸を
  増やすのではなく、ユーザー自身がどのメンバーを見るか能動的に選ぶ方式が本来の要望
  だった。
- 採用した実装方針: 観測/推定/動的グループ見出しのⓘボタン（従来は読み取り専用の
  「アイコンの意味」凡例だった）を、「表示する項目を選ぶ」設定パネルへ拡張した
  （`renderVisibilitySettings`、旧`renderGroupLegendToggle`）。各項目にチェックボックス
  風のボタン（`.visibilityCheckbox`）を持たせ、非表示に選んだメンバー/軸のIDを
  `hiddenIds`（`${scope}:${id}`形式、scope="raw"|"composite"|"dynamic"）へ記録する。
  グループ本体を展開すると、このセットに含まれないメンバー/軸だけが並ぶ
  （`renderObservedMemberRows`のフィルタ、`group:composite`分岐の`SECONDARY_AXES.filter`）。
  既定（何も非表示に選んでいない状態）は従来どおり全件表示のため、新しいレイヤーが
  追加されても自動的に表示される（非表示IDのSetを持つ設計、表示IDのSetにしなかった
  理由）。設定はページ内の一時的なUI状態（expandedIdsと同じ位置づけ）で永続化はしない。
- 追加フィードバック対応: 実装直後にユーザーから「設定で非表示にした場合、裏でレイヤ
  表示ONになっていればOFFにして」との指摘。非表示に選んだ瞬間、対応するレイヤーが
  ON（`member.on`/軸の場合は`axis.layerId`が指すメンバーの`on`）であれば`toggleHidden`が
  `onToggle`（page.tsxの`handleLayerToggle`、`layerVisibility`state唯一の更新経路）を
  呼んでその場でOFFにする（`toggleHidden`のシグネチャへ`layerId`/`isOn`を追加）。
  そうしないと、チップ一覧から消えたレイヤーが地図には描画され続け、かつOFFにする
  手段（チップ自体）も無くなってしまうため。逆方向（非表示解除）はチップを選べる状態に
  戻すだけでレイヤーを自動ONにはしない（「隠す/出す」はチップの見た目の設定、ON/OFFの
  意思決定はユーザーが個別に行うという既存方針を維持）。あわせてフロント全体の状態管理の
  一貫性を確認し、`layerVisibility`（page.tsx）が唯一の情報源・`handleLayerToggle`が
  唯一の更新経路という既存構造に対し`hiddenIds`はあくまで表示専用のローカルUI状態で
  `onToggle`経由でしか外側へ影響しないこと（新しい状態の持ち方を増やしていないこと）を
  確認した。
- 完了条件: 表示項目の設定パネルで非表示に選んだメンバー/軸が、グループ展開時に
  実際に除外されること。非表示に選んだ瞬間、ONだったレイヤーがOFFになること。
  設定を変えていない他のメンバー/軸のON/OFF・凡例展開がT128までの挙動と変わらないこと。
  モバイル幅でのPlaywright実機確認。
- 検証: `MapOverlayControls.test.tsx`（既存1件更新・新規4件追加、計33件green）。
  frontend全体495件・tsc/eslint全green。Playwrightでモバイル幅（390px）の実機確認:
  観測グループのⓘから道路種別・路面・指定路線以外（停止要因・事故・インフラ・標高図・
  補給休憩）を非表示に設定し、観測グループを開くと設定どおり3件だけが並ぶことを
  確認した（8件→3件、見切れ問題も同時に解消）。

### - [x] T194. Open-Meteo 429による気象グリッド欠損の根本対策（6段階ロードマップ） 規模M〜L 完了（2026-08-21、状況調査・記録のみ。④の実装はT195）

- 発端: T190〜T193（時刻スライダーのUI改善）を実機確認する過程で「スマホでもフルブラウザでも
  ルーラーが動かせない」という報告を受け、切り分け用の診断ページ・実機コンソールでの
  直接調査（`document.elementFromPoint`・イベントリスナー計装等）を経て、UI実装自体は
  正常でルーラーの`scrollWidth === clientWidth`（スクロールする余地が無い）ことが判明。
  さらに遡ると、Open-Meteo API（風・降水延長予報が使う外部気象API）が429（レート制限）を
  返し、`/api/weather/wind-grid`が「1格子点の失敗で全体を落とさない」設計（T178）により
  空配列＋200 OKを返す→フロントエンドはエラーと判定できず`windGrid=[]`→風・延長予報の
  フレームが0件→降水ナウキャストの実況分のみでタイムラインが1コマまで縮退、という
  連鎖でスライダーが「動かせるコマが無い」状態になっていたことが根本原因と特定できた
  （UI操作系の不具合ではなかった。エラー表示が一切出ないままユーザーからは「動かない」
  としか見えない点は`docs/logging.md`の方針＝エラー/429は常時可視化、の趣旨に照らしても
  改善余地がある）。
- 対応方針: このタスク自体はコード対応を伴わず、**改善計画に載せるだけ**にとどめる
  （ユーザー指示「改善計画に乗せるまでにとどめる。根本対策を再度考えたい」）。ユーザーが
  提示した以下6段階のロードマップについて、現状の実装到達点を調査済み。着手判断・優先度は
  ユーザー側で改めて検討する。
- **① 複数座標を1リクエストにまとめる — 完了**。`get_forecast_many`
  （`backend/app/infrastructure/weather_client.py:218-303`）が複数地点をカンマ区切り
  latitude/longitudeで1回のOpen-Meteo POSTリクエストにまとめている（624地点でも1回で完結。
  GETだと414になるためPOST採用、同ファイル:130-137）。
- **② 気象用Gridを道路評価Gridから分離する — 完了**。`wind_grid.py`は独立モジュールで、
  `RoadGraphEngine`（PostGIS空間インデックス使用）とはコード・定数とも無関係
  （`wind_grid`を参照するのは`weather_service.py`・`api/routers/weather.py`のみ）。
- **③ 気象Gridを固定化する — 部分実装**。基本格子（`WIND_GRID_BBOX`・
  `WIND_GRID_SPACING_DEG=0.1`、624点、`wind_grid.py:32-49`）はビューポート非依存で完全固定。
  ただしT180で追加した「詳細格子」（`generate_wind_grid_detail_points`、`wind_grid.py:
  102-134`）はビューポートのbboxに応じて対象範囲・間隔（ズーム依存、0.02〜0.0025度の
  離散段階）が変わるため、グリッド自体が可変という点で③の趣旨に対しては部分実装にとどまる。
- **④ 3時間程度のTTLでDBキャッシュ — 完了（T195で実装）**。プロセス内メモリ辞書
  （L1、`_wind_forecast_cache`）に加え、既存の標高キャッシュと同じ`cache_db.py`のSQLite
  永続化（L2）を追加し、プロセス再起動・Renderのスケールアウトをまたいでキャッシュが
  残るようにした。正のTTLも`WIND_GRID_CACHE_TTL_SECONDS`＝3時間へ拡大（旧30分）。
  詳細はT195参照。
- **⑤ バックグラウンド更新 — 未着手**。APScheduler/cron/Celery/FastAPIのbackground task等は
  `backend/app/main.py`含めどこにも無く、すべてユーザーリクエスト契機の同期フェッチのみ。
- **⑥ 利用者が増えたらOpen-Meteo自前運用 — 未着手**。関連策としてT179（Oracle Cloud VM
  経由のリレープロキシ、送信元IP分離）はコード実装済みだが、Render側の環境変数
  `OPEN_METEO_BASE_URL`が未設定のため本番では未使用。T182で判明した日次クォータ枯渇は
  送信元IP非依存の現象と直接確認済みで、「仮にT179を有効化しても解決しない可能性が高い」
  と記録済み（T182の実装メモ参照）。
- 次の一手の候補（優先度はユーザー判断）: ④はT195で実装済み。残る⑤のバックグラウンド更新
  （ユーザーリクエストをOpen-Meteoへの同期フェッチから完全に切り離せる）と⑥（利用者増加時の
  自前運用）は、既存実装（①〜④）の上に積む次の自然なステップとして引き続き未着手のまま
  記録のみにとどめる。あわせて、今回発覚した「全格子点429時でも200 OKで握りつぶす」設計自体
  （`/api/weather`は既に502を返す設計になっているのと非対称）も、根本対策とは別に小さく
  直せる余地がある（フロント側の`windError`表示が自然に機能するようになる）。この2点は
  いずれも今回はコード対応せず、ユーザーが優先度を判断し着手を指示した時点で別タスクとして
  着手する。

### - [x] T195. 気象グリッド（風・降水延長予報）取得のDB永続化キャッシュ化（T194の④実装） 規模S 完了（2026-08-21）

- 発端: T194で調査した6段階ロードマップのうち、ユーザーが「④をやって、他は改善計画に
  記載するまでにして」と優先度を明示。Renderのようなインスタンス再起動でプロセス内メモリが
  消える環境では、メモリキャッシュ（L1）だけでは429で消耗した後の再フェッチが再起動のたびに
  発生してしまうため、既存の標高キャッシュ（Step5）と同じ`cache_db.py`のファイルベース
  SQLite永続化に相乗りさせ、気象グリッドもプロセス再起動をまたいで再利用できるようにした。
- 実装内容:
  - `backend/app/infrastructure/cache_db.py`: `wind_forecast_cache`テーブル
    （`lat, lon, data(JSON文字列), fetched_at(epoch秒)`、`PRIMARY KEY (lat, lon)`）を追加。
    `get_wind_forecast_many`/`set_wind_forecast_many`（いずれも`asyncio.to_thread`経由、
    スレッドローカル接続を既存の標高キャッシュと共有）を新設。DB読み書き失敗時は
    `docs/logging.md`の方針通り抑制付きWARNINGで常時記録し、キャッシュミス扱いにフォール
    バックしてルート生成自体は継続する（標高キャッシュの既存方針を踏襲）。
  - `backend/app/infrastructure/weather_client.py`: `get_forecast_many`をL1（メモリ辞書
    `_wind_forecast_cache`）→L2（`cache_db`のSQLite）→Open-Meteo実フェッチ、の順に問い合わせる
    よう変更。新規取得できた分はL1・L2の両方へ書き戻す。TTLを`WIND_GRID_CACHE_TTL_SECONDS`
    ＝3時間（旧`CACHE_TTL_SECONDS`＝30分）へ拡大し、劣化時のフォールバック許容幅も
    `WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS`＝24時間（旧3時間）へ拡大。単一地点用の
    `get_forecast`/`_forecast_cache`（`/api/weather`が使う経路）は対象外とし、変更していない。
  - `docs/architecture.md`: 「SQLite永続キャッシュ（`cache_db.py`、標高・気象グリッド）」
    として2テーブル構成を記述し、`get_forecast_many`のL1+L2設計を追記。
- 検証: `backend/tests/test_cache_db.py`・`backend/tests/test_weather_client_cache.py`に
  新規テストを追加（DB往復・部分ヒット・上書き・メモリキャッシュクリア後もDBキャッシュから
  復元・TTL超過で再フェッチ、等）。`pytest tests/test_cache_db.py
  tests/test_weather_client_cache.py -v` → 31件成功。バックエンド全体
  `pytest -q` → 866 passed, 99 skipped（既存のPostGIS統合テストskipのみ、回帰なし）。
- 残り（⑤⑥）: T194の記録の通り、バックグラウンド更新（⑤）とOpen-Meteo自前運用（⑥）は
  今回はコード対応せず未着手のまま。着手判断はユーザー側で行う。

## 統合レビュー対応（2026-08-22・review:all第5回の指摘）

出典: `.claude/commands/review/history/2026-08-22_all.md`（第2パス「統合Findings改訂版」。
第1パスはローカルmasterの26コミット追従遅れ状態を対象にしていたため、末尾の第2パスが正）。
ユーザー指示「程度優先度問わず全て改善計画に追記」（2026-08-22）により全件起票。

### - [x] T196. OpenAPI生成物へT185のspacing_degを反映し、master CIの実行状況を確認、再生成をコミット手順へ組み込む〔P1〕規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-1。T185（`d9f4edb`）が`/api/weather/wind-grid-detail`へ
  追加した`spacing_deg`クエリパラメータが`frontend/src/types/generated/openapi.json`・
  `api.d.ts`に未反映（worktreeでの再生成で+12/-1行の差分を実測）。T180（→T183の再生成で
  解消済み）に続く生成物ペア更新漏れの同型2例目。フロントは`weatherApi.ts`がURL手組みで
  呼ぶため型エラーとして表面化しない。`d9f4edb`（2026-08-21）以降、CIのapi-contractジョブは
  赤になるはずの状態が継続している（非公開リポジトリ・gh CLI未導入のためレビューでは
  実行履歴未確認。Actions無償枠枯渇でCI自体が実行されていない疑いあり）。
- 実装内容: `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を実行し
  `openapi.json`/`api.d.ts`を再生成（`spacing_deg`パラメータ反映、T198のwind-grid-config.json
  新設分も同時に反映）。GitHub ActionsのCI実行状況は非公開リポジトリ・`gh` CLI未導入のため
  このセッションでは確認できず（未解消のまま記録。ユーザー側でActionsタブを直接確認するか
  `gh` CLIのセットアップが必要）。
- 再発防止: 本ファイル冒頭に「backend側のAPIルーター・Pydanticモデル・レジストリ・
  domain定数を変更したコミットは、`export_openapi.py`→`npm run generate:api`を同一コミットで
  実行し`git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを確認する」
  を進め方の原則として追記（下記「進め方の原則」参照）。
- 検証: 再生成後の差分をコミットに含めた状態でbackend pytest 967件・frontend vitest 469件が
  全green（他タスク分含む合算値、下記T202参照）。
- 未解消: CI実行状況の確認自体はユーザー側で別途行う必要がある。

### - [x] T197. architecture.mdへ動的気象スタック（T170〜T195）・レイヤー階層次数反転（T163〜T169）を追従し、「規模M以上の新設はarchitecture.md追従を完了条件に含める」運用を明文化する〔P1〕規模S〜M（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-2（第4回の統合-2から継続、同型6回目）。T194/T195の
  キャッシュ2段構成はarchitecture.mdへ正しく追従された一方、動的気象スタック全体
  （`dynamicWeather.ts`共通契約・`wind_grid.py`/`twilight.py`・`/api/weather/wind-grid`
  ・`wind-grid-detail`エンドポイント・`DynamicLayerTimeSlider`・T179リレープロキシ）と
  地図チップの観測/推定/動的グルーピング（T163〜T169、`primaryAttributes.ts`双方向導出・
  梅竹松の1次/2次表現統一）はgrep 0件のまま。「担当タスクの節だけ更新する一段浅い追従」の反復。
- 実装内容:
  - `docs/architecture.md`「1. 技術選定」へ「動的気象レイヤー（風・降水延長予報）の共通契約
    （改善計画T170〜T195）」を新設（T184共通契約の4本柱・風の格子点マップ・詳細格子・
    降水延長予報・night軸動的化・Open-Meteo 429対策6段階ロードマップ・時刻スライダーの
    ルーラー化・useWeatherGridフックへの抽出を記述）。
  - 「7. 静的道路属性と7軸評価モデル」へ「地図チップの観測/推定/動的グルーピングと
    一次/二次命名の完全化（改善計画T163〜T169）」を新設（レジストリ完全化・一次属性
    カタログ・道路情報論理分割・チップ最上位の次数反転・材料連動ON/OFF・チップの
    タイル化/マトリックス化・梅竹松の表現統一を記述）。
  - §2ディレクトリ構成へ`domain/twilight.py`・`domain/wind_grid.py`・
    `Map/dynamicWeather.ts`・`Map/windLayer.ts`・`Map/precipitationNowcast.ts`・
    `Map/primaryAttributes.ts`・`DynamicLayerTimeSlider/`・`hooks/useWeatherGrid.ts`を
    追記。requirements.txt（astral/tenacity追加）・generated/（axis-catalog.json・
    wind-grid-config.json）の説明も更新。
  - §4 API設計へ`GET /api/weather/wind-grid`・`GET /api/weather/wind-grid-detail`
    （リクエスト/レスポンス例・400/429エラー仕様含む）を新規追記。
  - 「静的レイヤー・タイル配信」節冒頭を「フロント9レイヤー」から実態（固定レイヤー＋
    降水ナウキャスト・風の2 kind="static"/dataNature="dynamic"レイヤー）に合わせて修正。
  - 本ファイル冒頭「進め方の原則」へ運用ルールを追記（上記参照）。
- 検証: architecture.md追記後、grepで新設シンボル（`dynamicWeather`・`wind_grid`・
  `twilight`・`DynamicLayerTimeSlider`・観測/推定/動的グルーピング）が全てヒットすることを
  確認。ドキュメントのみの変更のためbackend/frontendテストへの影響なし。

### - [x] T198. 風格子定数群（間隔・許可段階・上限点数）を生成物経由の片側importへ集約する〔P2〕規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-3（第1パス統合-3の拡大版）。backend
  `domain/wind_grid.py`とfrontend `windLayer.ts`が`WIND_GRID_SPACING_DEG=0.1`／
  `WIND_GRID_DETAIL_SPACING_DEG=0.02`／許可間隔段階（`WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG`
  ⇔`WIND_GRID_DETAIL_SPACING_STOPS`、0.02/0.01/0.005/0.0025）を「値を合わせること」
  コメントのみで二重定義。`WIND_GRID_DETAIL_MAX_POINTS=900`⇔フロントの係数25も同様。
  APIレスポンスに間隔情報が含まれないため、backend側の変更はフロントのセル描画の
  静かなズレとして現れる。同期バグが実際に起きた「照合の無い糊」（T120・T121-a）と同構造。
- 実装内容:
  - `backend/scripts/export_openapi.py`: 新規`wind-grid-config.json`
    （`spacing_deg`/`detail_spacing_deg`/`detail_allowed_spacings_deg`/`detail_max_points`、
    `domain/wind_grid.py`の定数から直接書き出し）を追加（`region-tile-config.json`と
    同じパターン）。
  - `frontend/src/components/Map/windLayer.ts`: `WIND_GRID_SPACING_DEG`・
    `WIND_GRID_DETAIL_SPACING_DEG`・`WIND_GRID_DETAIL_SPACING_STOPS`の間隔値を
    `wind-grid-config.json`からのimportへ置き換え（片側import、設計原則2）。zoom境界
    （10/13/16/19）はUI固有の判断のためフロント側定数のまま維持。
    `WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS`（安全率係数25）はexportし、
    `detail_max_points`との整合をテストで検証する形にした（設計判断の安全率自体は
    独立した定数のまま、ドリフトはテストで検知）。
  - `backend/app/domain/wind_grid.py`: コメントを「wind-grid-config.jsonが単一の情報源」
    という記述へ更新（旧「フロント側と同じ値を維持すること」を廃止）。
- 検証: `frontend/src/components/Map/windLayer.test.ts`へ3件追加（生成物との値一致・
  スペーシング段階の順序一致・安全率係数が上限点数の範囲内であることのドリフト検知）。
  frontend vitest全体でgreen確認（下記T202参照）。

### - [x] T199. 動的レイヤー凡例ポップオーバーを排他表示にする〔P2〕規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-4（第1パス統合-4の継続、対象コミット`a6c82a2`で再現
  確認済み）。降水凡例と風凡例を続けて開くと同x位置で約139px重なり、半透明背景のため
  両方のテキストが交錯して判読不能（レビューの実測rect: 降水y=196 h=190・風y=247 h=188）。
  雨天時に風と降水を同時確認する場面でちょうど両方の凡例を見たくなるため遭遇率が高い。
- 実装内容: `MapOverlayControls.tsx`に`GROUP_VISIBILITY_KEYS`
  （`group:composite`/`group:raw`/`group:dynamic`、floatingパネルを持たないグループ本体の
  開閉キー）を新設し、`toggleExpanded`が新しくキーを開くとき、そのキーがグループ本体
  でなければ他のfloatingパネル系キー（member:/axis:/単独チップ/`${groupKey}:legend`）を
  すべて閉じてから開くよう変更。グループ本体同士（観測/推定/動的の同時展開）は従来どおり
  独立に開閉できる（floatingパネルを持たず重ならないため対象外）。
- 検証: `MapOverlayControls.test.tsx`に回帰テストを追加（降水→風の順に凡例を開くと降水側が
  自動的に閉じ`aria-expanded="false"`になることを検証）。Playwright実機確認
  （デスクトップ1280×900）で、降水凡例→風凡例の順に開くと風の凡例のみ表示され重ならない
  ことをスクリーンショットで確認。ルート生成本線（8候補生成）への非回帰も確認。

### - [x] T200. wind-grid全地点失敗時のエラーを可視化する（空配列200 OKの非対称解消）〔P2〕規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-5。T194の根本原因調査で特定済みの事項の起票
  （T194時点ではユーザー指示により記録のみとしていたが、全件起票指示を受け正式タスク化）。
  Open-Meteoが全地点429でも`/api/weather/wind-grid`は空配列+200 OKを返すため、フロントは
  エラーと判定できず`windError`表示が機能せず、時刻スライダーが「動かせるコマが無い」として
  現象化する（診断に実機コンソール計装まで要した実績）。`/api/weather`（単一地点）は
  502を返す設計で、非対称。docs/logging.mdの「エラー・429は常時可視」方針にも反する。
- 実装内容: `backend/app/api/routers/weather.py`へ`_reject_if_all_points_failed(label, points,
  grid)`ヘルパーを新設。`points`が非空かつ`grid`（`WeatherService.get_wind_grid`の返り値、
  失敗地点はNone）が非空で全件Noneの場合のみ502＋抑制無しWARNINGログを出す（「1地点の失敗で
  全体を落とさない」T178の方針は維持。`grid`が空リストの場合は対象外とし、既存テストの
  フェイク実装（points数と無関係に空リストを返すもの）との後方互換を保った）。
  `get_wind_grid`・`get_wind_grid_detail`の両エンドポイントへ適用。
- 検証: `backend/tests/test_weather_route.py`へ2件追加（wind-grid・wind-grid-detailそれぞれ
  全地点失敗時に502＋detail「気象データの取得に失敗しました」を返すこと）。
  backend pytest 967件全green（既存の空リストフェイクを使うテスト群への影響なしを確認）。

### - [x] T201. 規模ウォッチ閾値をT184共通契約の実態に合わせて再定義する（canvas幾何ヘルパー抽出は任意）〔P2〕規模S（＋任意S）（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-6。MapView.tsx 2,502行（閾値2,000超）・page.tsx
  1,615行（閾値1,300超。`useWeatherGrid`抽出で-115行の改善はあった）。T184で
  「レンダラー宣言・アイコン生成は`DYNAMIC_WEATHER_RENDERERS`（MapView内）へ集約」が
  契約上の正当な配置になったため、行数閾値の前提（手書き描画コードの無秩序な増加を捕捉）が
  変化した。第1パスの「アイコン生成をwindLayer.tsへ移動」案はT184契約と衝突するため撤回済み。
- 実装内容:
  - `docs/complexity-review-2026-08-16.md`のR-6・Keep Listへ2026-08-22時点の再定義を追記。
    新閾値: MapView.tsx「2,800行 or DYNAMIC_WEATHER_RENDERERSのスペック5件目 or 手書き
    STATIC_OVERLAY_LAYERS（ramp除く）10件 or bespoke種の軸3件目 or 5つ目のレシピ軸の
    MapView内ミラー追加」、page.tsx「1,900行 or useState+useStoredState合計40件」。
  - 任意の抽出も実施: mapに依存しない純粋なCanvas 2D描画コード（`Point2D`・
    `cubicBezierPoint`・`fillTaperedRibbon`・`createWindArrowIcon`・`WIND_ARROW_SIZE_PX`）を
    `frontend/src/components/Map/windArrowIcon.ts`（新設）へ抽出。レンダラー登録
    （`DYNAMIC_WEATHER_RENDERERS`）・アイコン参照はMapView.tsxに残し、T184契約
    （描画スペックはMapViewに集約）とは矛盾しない形にした。
  - 実測（抽出後）: MapView.tsx 2,401行（新閾値2,800行に対し399行の余裕）・
    DYNAMIC_WEATHER_RENDERERS 2件（閾値5件に対し余裕）・page.tsx 1,615行
    （新閾値1,900行に対し285行の余裕）・state 13件（閾値40件に対し余裕）。
- 検証: `windArrowIcon.test.ts`（新設）でスモークテスト1件追加（jsdomがcanvas 2D
  コンテキストを実装しないため描画内容自体は検証不可、例外なく32×32のImageDataを返す
  ことのみ確認）。tsc/eslintクリーン、frontend vitest全体green（下記T202参照）。

### - [x] T202. 統合レビュー第5回の軽微指摘6件を一括解消する〔P3〕規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-7。いずれも単独起票に満たない軽微だが実在する取りこぼし。
- 対応内容（6項目）:
  1. **動的気象ラスタのプレースホルダタイル404**: レイヤーON直後にプレースホルダURL
     （`.../00000000000000/none/00000000000000/...`）への実リクエストが404になる事象を
     再度実機Playwright確認で再現した（デスクトップ・モバイル双方、他タスクの変更前後で
     常に2件）。コード上は`setTiles`→`setLayerVisibility`の順序が既に正しく（visible化前に
     実URLへ差し替え済み）、`ensureDynamicWeatherLayer`もソース追加時にvisibility:noneで
     追加しているため、単純な順序raceは見当たらなかった。`next dev`実行時のReact Strict
     Modeによる開発時二重effect実行（mount→cleanup→再mount）で、初回payload未確定の瞬間に
     一瞬visible状態が生じている可能性が高いと判断（本番ビルドでは未検証）。実害は無く
     表示は自己回復するため、コード変更ではなく`MapView.tsx`の該当コメントを「visibility:
     noneの間は要求されない」という不正確な断定から、観測した例外・推定原因・本番での
     未検証である旨を明記する記述へ訂正した。
  2. **`useWeatherGrid.ts`の更新間隔をT195へ追従**: `WEATHER_GRID_REFRESH_INTERVAL_MS`を
     30分→3時間（`weather_client.py: WIND_GRID_CACHE_TTL_SECONDS`と一致）へ変更し、
     コメントも新しい値・根拠に更新。
  3. **`DynamicLayerTimeSlider.tsx`冒頭の旧設計コメント修正**: 「複数の時刻依存レイヤーが
     同時ONのときは縦に複数マウントする」という記述をT183の1本統合後の実態
     （共有タイムラインへ統合済みのため1つだけマウント）へ書き換えた。
  4. **初期ロード時のMapLibre null警告3件の由来調査**: RideCompass自身のカスタムレイヤーは
     いずれも初期状態でvisibility:none（`grep`で"visibility: \"visible\""のハードコードが
     0件であることを確認）かつ空のFeatureCollectionで初期化されるため、boot時点で
     式評価対象のフィーチャーが存在せず警告を出しようがない。警告の実際の発生源は
     RideCompassが直接制御しないOpenFreeMap「liberty」基礎地図スタイル自体の内部式である
     可能性が高いと判断した（サードパーティスタイルのため修正は範囲外。Confidence: Low、
     追加のライブデバッグなしにこれ以上は特定できないため今回はここまでとする）。
  5. **`config.py`のwind-gridコメント更新**: 「関東本土全域（約56地点）」を現行0.1°間隔の
     約624地点へ更新し、密度変遷の経緯（`domain/wind_grid.py`参照）も併記。
  6. **推定グループのレイヤー無し軸の添え書き**: `secondaryAxes.ts`の
     `SECONDARY_AXIS_PROXY_HINTS`（勾配・舗装質・夜間）へ「（地図表示なし）」を先頭に付与し、
     ▼展開時の案内文・タイトル属性（ツールチップ）の両方で自己説明的にした。タイルの見た目
     自体（4文字以下ラベル・小型グレー表示）は展開せずに常設ラベルを追加するとレイアウトへの
     影響を実機確認できていないため変更せず、恒常表示化は今回見送り（ユーザー判断のDEFER）。
- 検証: `MapLayersPanel.test.tsx`・`MapOverlayControls.test.tsx`の既存アサーションを
  新しい案内文（正規表現の部分一致）へ更新。frontend vitest 469件・backend pytest 967件
  全green。tsc/eslintクリーン。

### - [x] T203. wind-grid応答のtimes配列重複を削減する 規模S（2026-08-22完了）

- 発端: 統合レビュー2026-08-22 改訂-7（第1パスO-1）。`/api/weather/wind-grid`の応答は
  実測約0.93MB（非圧縮）で、全624地点が同一内容の`times`配列（48時刻×16文字）を
  個別に持つことが約1/3を占める。gzip圧縮下では重複はほぼ消えるため実害は限定的と
  レビューでは判断（本番の圧縮有無は未確認）。
- 着手前の計測（トリガー未到達分の実測、「計測なき最適化を避ける」ゲート）:
  `backend/app/main.py`にGZipMiddlewareが存在しない（CORSMiddlewareとrequest_log_
  middlewareのみ）ことを確認。実測で非圧縮1,068,257 bytes・gzip level6後119,874 bytes。
  Renderのようなホスティング基盤は一般にオリジンレスポンスをそのまま転送し圧縮の付与は
  アプリ層の責務であるため、本番でも非圧縮配信の可能性が高く、レビュー時の想定
  （「gzip圧縮下では実害は限定的」）を覆す実測結果が得られたため実装へ進んだ。
- 実装: `times`を`WindGridPoint`（domain/wind_grid.py）から外し、応答本体を
  `WindGridResponse{times: list[str], points: list[WindGridPoint]}`へ変更
  （`WeatherService.get_wind_grid`が`(times, points)`のタプルを返す形へ、
  `api/routers/weather.py`の2エンドポイントがこれを`WindGridResponse`として返す）。
  全地点が同じforecast_days・timezoneで一括取得される（weather_client.py）ため
  hourly.timeは全地点共通という既存の前提（フロント側trimWindGridToCurrentAndFuture等が
  既に採用済み）にそのまま乗る形。フロント内部（windLayer.ts/useWeatherGrid.ts/
  precipitationNowcast.ts）は「各点がtimesを持つ」表現のまま一切変更していない。
  `services/weatherApi.ts`の`toWindGridPoints`が、受け取った`{times, points}`を
  内部用に`points.map(p => ({...p, times}))`へ変換してから返すことで、ワイヤー
  フォーマット（削減対象）とフロント内部データモデル（既存ロジック）を分離した。
  `types/weather.ts`の`WindGridPoint`は生成型（times無し）に`times: string[]`を
  合成した型として維持し、内部表現の型を変えていない。
- 完了条件: 応答が`{times, points}`形になり、フロント側の見た目・挙動（風矢印・
  降水延長予報の表示、時刻スライダー）が変わらないこと。
- 検証: バックエンド1029件・フロント495件・tsc/eslint全green。実機確認（開発サーバー、
  curl）: `/api/weather/wind-grid`が非圧縮493,862 bytes（旧1,068,257 bytesから約54%削減、
  事前実測どおり）・gzip後103,053 bytesへ削減されたことを確認。`wind-grid-detail`も
  同じ`{times, points}`形で応答することを確認。

## 動的データの追加候補整理（2026-08-22・雷ほか未着手データの棚卸しと起票）

ユーザー要望「動的データの対応追加を進めたい。雷等の改善計画未記載の物含めて、取り込むべき
データを整理して」を受け、既存の動的要素導入（T170〜T178、上記節）以降に検討されていなかった
候補を実機調査つきで棚卸しした（2026-08-22）。T171実装メモが「雷ナウキャストは別レイヤー・
別調査として残す」としていた宿題も含む。設計判断はT170〜T178節と同じ方針を踏襲する
（「回避一択」の危険は評価軸にせず警告表示、動的データの欠測はT87のレイヤーデータ状態機構
へ正直に載せる）。

**実施順序（Phase）**: Phase A（T204）・Phase B（T205）は完了（2026-08-22）。

- **Phase A（最小コスト・即着手、完了）**: T204（雷ナウキャスト、竜巻はオプション同梱）。
  T171と同じタイル配信系で、プロダクトコード（`thns`/`targetTimes_N3.json`）の実在を
  今回のPlaywright実機確認で確定済みのため、残る作業は実装のみ。
- **Phase B（警告バッジ基盤、完了）**: T205（気象警報・注意報）。T174（WBGT）と警告バッジの
  表示枠を共有できるため、この基盤を先に作ってからT174へ進むと二重実装を避けられる
  （`WarningBadge.tsx`として実装済み、T174着手時はこれを再利用する）。
- **Phase C（既起票の優先順位再確認、内容変更なし）**: T176（河川敷冠水、台風期の今が
  調査の好機）→ T175（花粉、冬季着手で間に合う）→ T177（交通量時間帯補正、季節非依存）。
- **Phase D（トリガー付きDEFER・調査のみ）**: T206（積雪・凍結）・T207（雷ポテンシャル
  CAPE延長予報）・T208（視程・霧）・T209（黄砂・PM2.5）・T210（通行止め・道路規制調査）。
  いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

### - [x] T204. 雷ナウキャスト（活動度1〜4）を追加し、竜巻発生確度（trns）を低コストなら同梱する 規模S〜M（2026-08-22完了）

- 発端: ユーザー要望（2026-08-22「雷等の改善計画未記載の物含めて」）。T171実装メモが
  「雷ナウキャストはプロダクトコード未確認のため別レイヤー・別調査として残す」としていた
  宿題。今回Playwright実機確認で以下を確定した:
  - 時刻一覧: `https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N3.json`
    （200 OK、実況〜60分先・10分刻み。降水のN1/N2とは別ファイル。竜巻の`trns`も同じ
    N3内に同居し、追加のfetchが不要）。elements配列に`thns`（雷、活動度1〜4）・
    `thns_nd`・`trns`（竜巻発生確度）・`trns_nd`を確認。
  - タイル: `https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/
    {validtime}/surf/thns/{z}/{x}/{y}.png`（雷）・同`trns`（竜巻）ともに
    200 image/pngを実機確認済み（T171のhrpnsと完全に同型のURL構造）。
- 対応方針: `precipitationNowcast.ts`とほぼ同型のデータ層（`thunderNowcast.ts`新設、
  時刻一覧の取得・最寄りフレーム選択・タイルURL組み立て）を追加し、
  `dynamicWeather.ts`の共通契約（4ステップ）に乗せてMapView.tsxの
  `DYNAMIC_WEATHER_RENDERERS`へrasterTileスペックを1エントリ追加する。既存の共有
  タイムライン（`mergeFrameTimes`）へ自然に合流するため、時刻スライダー側の変更は
  不要（既に複数レイヤー共有前提の設計）。竜巻（trns）は雷と同じN3・同じ描画方式のため、
  実装時に追加コストが小さいと確認できれば1つの警告レイヤー内で階級表現を分けて同梱する
  （雷=オレンジ系、竜巻=紫系等の別階級で区別。コストが見込みより大きければ竜巻は
  T210と同様の調査のみへ切り出す）。評価軸には組み込まず警告表示のみ（回避一択のため）。
  地図チップの分類は「動的データ」グループへ追加。
- 完了条件: 雷ナウキャストがONのとき活動度に応じた着色が地図に重なり、共有タイムライン
  スライダーで実況〜60分先を切り替えられること。タイル取得失敗時にT87のエラー案内が
  出ること。竜巻を同梱する場合は視覚的に雷と区別できること。Playwright実機確認・
  backend/frontend全green。
- 依存: なし（T170〜T178の基盤の上に載る）。
- 実装内容:
  - `frontend/src/components/Map/jmaNowcastFrames.ts`（新設）: precipitationNowcast.tsから
    JMAナウキャスト系に共通する時刻一覧の取得・整形（`fetchJmaTargetTimes`・
    `trimToCurrentAndFuture`・`parseValidtime`）を抽出（変更理由が同じ処理の共通化、
    設計原則6）。`precipitationNowcast.ts`は内部実装をこのモジュールへ委譲しつつ、
    既存の公開名（`trimToCurrentAndFuture`・`parseValidtime`・`NowcastFrame`）を
    再エクスポートして既存の呼び出し元（page.tsx）への影響を無くした。
  - `frontend/src/components/Map/thunderNowcast.ts`（新設）: `targetTimes_N3.json`
    （1ファイルに実況・予測が同居、降水のN1/N2分割と異なる）から雷・竜巻共通のフレーム列を
    取得する`fetchThunderNowcastFrames`、dynamicWeather.tsの共通フレーム列へ変換する
    `thunderFrames`（windFrames/windRenderPayloadと同型の単純index-refパターン）、
    プロダクトコードだけが異なる`thunderRenderPayload`（thns）/`tornadoRenderPayload`
    （trns）、気象庁の公式解説
    （[雷ナウキャストとは](https://www.jma.go.jp/jma/kishou/know/toppuu/thunder2-1.html)・
    [竜巻発生確度ナウキャストの見方](https://www.jma.go.jp/jma/kishou/know/toppuu/tornado3-3.html)、
    2026-08-22確認）に基づく凡例（`THUNDER_ACTIVITY_LEVELS`・`TORNADO_POTENTIAL_LEVELS`、
    色は降水と同じく気象庁非公開のため近似値と明記）を持つ。
  - `dynamicWeather.ts`: `DYNAMIC_WEATHER_LAYER_IDS`へ`thunderNowcast`・`tornadoNowcast`を追加。
  - `mapLayers.ts`: 2つの`MapLayerId`（雷・竜巻は独立ON/OFF、同じ地図に両方重ねると見分け
    にくいという判断で1つの警告レイヤーへは統合せず別チップにした）と、それぞれの
    カタログエントリ（`kind="static"`・`dataNature="dynamic"`、評価軸には組み込まない）を追加。
  - `MapView.tsx`: `DYNAMIC_WEATHER_RENDERERS`へ`thunderNowcast`/`tornadoNowcast`の
    rasterTileスペックを追加（降水ナウキャストと同型、gridFill無し＝延長予報を持たない）。
    `LAYER_DATA_SOURCES`は`DYNAMIC_WEATHER_LAYER_IDS`から自動導出されるため変更不要
    （T184の1本道が実際に機能した箇所）。
  - `icons.tsx`: `ThunderIcon`（雷雲から伸びる稲妻）・`TornadoIcon`（渦を巻く漏斗雲）を追加。
  - `page.tsx`: 雷・竜巻共有の1本のfetch（どちらか一方でもONの間動作、`nowcastFrames`と
    同じパターン）、共有フレーム列からの`thunderPayload`/`tornadoPayload`（同じref、
    プロダクトコードのみ異なる）、`dynamicWeather`オブジェクトへの追加、共有タイムライン
    （`activeFrameLists`）・共有スライダー表示条件・loading/error集約への合流を実装。
    凡例（`THUNDER_LEGEND_DETAILS`/`TORNADO_LEGEND_DETAILS`）を降水/風と同じパターンで追加。
  - `MapLayersPanel.test.tsx`: 新規`MapLayerId`2件を全ての`layerVisibility`フィクスチャへ
    追加（`MapLayerVisibility`型の完全性をtscが強制）。
- 検証: `jmaNowcastFrames.test.ts`（新設、fetchJmaTargetTimesのラベル付きエラー）・
  `thunderNowcast.test.ts`（新設、時刻一覧のisForecast判定・フレーム変換・両プロダクトの
  ペイロード組み立て・範囲外refでのundefined返却・凡例段階数）を追加。
  frontend vitest 480件・tsc/eslint全green。Playwright実機確認（デスクトップ）で
  `targetTimes_N3.json`の1回のfetch共有・雷/竜巻タイルの実際の取得成功・両凡例の表示内容・
  雷だけOFFにしても竜巻は残る独立トグルを確認。プレースホルダタイルの404×2・boot時の
  null警告3件は既知（T202で文書化済み、React Strict Mode由来と推定・実害無し）で
  新規の問題ではない。

### - [x] T205. 気象警報・注意報を警告バッジとして表示する 規模M（2026-08-22完了）

- 発端: ユーザー要望（2026-08-22）。JMA警報・注意報API
  （`https://www.jma.go.jp/bosai/warning/data/warning/{市区町村等コード}.json`、
  200 OK実機確認済み。雷注意報・大雨・洪水・強風・波浪等を含む）は、雷ナウキャスト
  （T204、60分先まで）を補完する「それより先の見通し」を提供できる。T174（WBGT警告）と
  同じ「地図レイヤーではなく警告バッジ」という表現形式を共有できるため、この基盤を
  先に作ってからT174へ進む方が二重実装を避けられる。
- 対応方針: (1) 出発地点の緯度経度→市区町村コードの解決方法を調査する（国土地理院の
  逆ジオコーディングAPI、または警報区分コード一覧との近傍マッチ等、要検討）。
  (2) 取得した警報・注意報のうちサイクリングに関連する種別（雷・大雨・洪水・強風・
  波浪・大雪等）を絞り込み、警告レベルに応じたバッジをルート生成画面・天候表示へ出す
  （T174と共通の表示コンポーネントを新設し両タスクで共有する）。(3) 対象外の種別
  （津波等、サイクリングと無関係なもの）は表示しない。
- 完了条件: 警報・注意報が発表されている地点で警告バッジが表示され、無い場合は何も
  出ないこと。取得失敗時は警告なし（安全側でない点に注意書きを添える、T174と同じ方針）。
  backend/frontend全green。
- 依存: なし。T174とバッジ表示コンポーネントを共有する（T174着手前にT205を先に実施する
  ことを推奨、Phase順参照）。
- 実装内容:
  - **エンドポイントの訂正（着手時に判明）**: 発端に記載した
    `.../warning/data/warning/{code}.json`は令和8年5月29日の運用切替前の旧（legacy）
    スキーマで、2026-08-22時点（切替後）はレスポンスが`{areaTypes:[...]}`形の
    別スキーマへ変わっていた。現行の`.../warning/data/r8/{府県予報区コード}.json`
    （実機確認済み、`{controlDatetime, reportDatetime, warning:{class10Items,
    class20Items}}`の配列を返す。1レスポンスに大雨・土砂災害・高潮・暴風・波浪・大雪・
    その他の注意報が別電文（VPWW55〜61）として同居する）を採用した。
  - `backend/app/domain/jma_warning.py`（新設）: 気象庁「気象警報・注意報（Ｒ０６）」
    電文フォーマット解説資料の別表3（PDF、dmdata.jp経由で取得・全コード照合）を典拠に
    `WARNING_CODE_NAMES`（全コード→名称）を定義。`CYCLING_RELEVANT_WARNING_CODES`は
    ユーザー要望の列挙（雷・大雨・洪水・強風・波浪・大雪）に土砂災害を追加した
    （山間部ロングライドの通行可否に直結するため）。霜・着氷・着雪・なだれ・低温は
    T206（積雪・凍結）、濃霧はT208（視程・霧）で別途扱う予定のため対象外、高潮・乾燥・
    その他の注意報は道路走行との関連が薄く対象外（「対象外の種別は表示しない」の
    「津波」と同種の除外）。`warning_level()`は名称文字列（「特別警報」「警報」を
    含むか）から3段階を導出し、レベルを別テーブルとして二重管理しない（設計原則2）。
  - `backend/app/domain/jma_area.py`（新設）: 緯度経度から得た市区町村コード（5桁）
    →JMA警報エリア（class20/class10/office）の解決。JMA地域マスタ（area.json）の
    class20エリアコードが市区町村コード+"00"と一致することを実機照合で確認し、
    GSIの市区町村名とJMAの地域名の文字列突合を不要にした。
  - `backend/app/infrastructure/jma_warning_client.py`（新設）: 国土地理院逆ジオコーダ
    （緯度経度→市区町村コード）・JMA地域マスタ（area.json、24時間TTL）・JMA警報API
    （r8、10分TTL）の3クライアント。いずれもOpen-Meteoほど更新頻度が高くないため
    tenacity再試行は設けず、失敗時はNoneを返す（呼び出し元が「警報なし」として扱う）。
  - `backend/app/services/warning_service.py`（新設）: 上記3つを直列に呼び、
    どこで失敗しても空の`WeatherWarnings`（警報なし）を返す。r8レスポンスの電文配列
    全件を走査し、対象エリアのkindsをcode単位で辞書へ集約（重複排除）、採用した警報の
    中で最も新しいreportDatetimeをバッジの発表時刻として使う。class20Itemsに対象
    エリアが無い電文（高潮等で実機観測）はclass10Itemsへフォールバックする。
  - `GET /api/weather/warnings`（`weather.py`）: 他の`/api/weather`系と異なり、
    取得失敗を502にせず常に200+空warningsで返す（完了条件どおりの意図的なfail-open。
    T200のwind-grid全滅502ガードとは方針が異なる点をコードコメントで明記）。
    レート制限（`weather_warnings_rate_limit_per_minute`）を追加。
  - `frontend/src/components/WarningBadge/WarningBadge.tsx`（新設）:
    T174と共有する汎用バッジ表示コンポーネント（JMA固有の型に依存しないitem形）。
    3段階（advisory/warning/emergency_warning）の配色は雷ナウキャスト
    （T204、`THUNDER_ACTIVITY_LEVELS`）の最高段階と同じ紫をemergency_warningに使い、
    アプリ全体の警戒度配色語彙を揃えた。
  - `frontend/src/app/page.tsx`: 天候取得と同じ地点変更デバウンス（1.5秒）に相乗りして
    `getWeatherWarnings`を呼ぶ（独立したデバウンスを増やさない）。バッジの`title`へ
    付随事項（竜巻・ひょう等）と「取得できない場合は警報が出ていてもバッジが表示され
    ないことがあります」という注意書きを併記する（完了条件の「安全側でない点に注意書きを
    添える」、T174と同じ方針）。
  - `frontend/src/app/page.module.css`: `.weatherHeader`へ`flex-wrap: wrap`を追加し、
    狭い幅ではバッジが2行目へ折り返るようにした（WeatherPanel内部は独自にスクロール
    するため、ヘッダー全体を縮めるより両方の内容を読める）。
- 検証: `test_jma_warning_domain.py`・`test_jma_area.py`（新設、コード分類・エリア解決の
  純ロジック）・`test_warning_service.py`（新設、モックした3クライアント関数を差し替えて
  複数電文の集約・フォールバック・失敗時の空応答を確認）・`test_weather_route.py`への
  追加（エンドポイントの成功/失敗時空応答/レート制限）。`WarningBadge.test.tsx`・
  `weatherApi.test.ts`への追加。backend 989件・frontend 487件・tsc/eslint全green。
  Playwrightで実機確認（2026-08-22時点、東京地方は実際に大雨危険警報・雷注意報
  （竜巻・ひょう付随）・土砂災害注意報が発表中だったため、モックではなく実データで
  3件のバッジ表示・正しい配色・titleの付随事項・モバイル幅での折り返しを確認できた）。

### - [ ] T206. 積雪・凍結情報（JMA「今後の雪」タイル・Open-Meteo積雪変数） 規模S〜M — トリガー: 冬季前（毎年11月）またはユーザーからの着手指示

- 発端: ユーザー要望（2026-08-22）。JMA「今後の雪」タイル配信
  （`https://www.jma.go.jp/bosai/jmatile/data/snow/targetTimes.json`、200 OK実機確認済み。
  `snowd`積雪深・`snowf01h`〜`snowf72h`各時間降雪量を含む）とOpen-Meteoの積雪変数
  （`snowfall`・`snow_depth`・`freezing_level_height`、いずれも実機取得確認済み）が
  候補。関東平野部では対象日が限定的だが、山間部ロングライドでは凍結・積雪が
  「回避一択」の危険になりうる。
- 対応方針（トリガー到達時）: 表現形式（rasterTileの面表示 vs 警告バッジ）・評価軸に
  組み込まない方針（凍結は危険側、警告表示のみ）を含めて着手前に再検討する。
  Open-Meteo経由の`freezing_level_height`（凍結高度）は既存のget_forecast_many格子へ
  変数追加するだけの低コストな経路（T183と同じ相乗り）。
- 完了条件（着手時に確定）: 積雪・凍結の警告が該当時期・該当地点で表示され、対象外
  シーズンは取得自体を行わずUIにも出ないこと。

### - [ ] T207. 雷ポテンシャル（CAPE）による延長予報の検討 規模S — トリガー: T204（雷ナウキャスト60分先まで）だけでは見通しが不足するという利用実績・要望が出た時点

- 発端: ユーザー要望（2026-08-22）。Open-MeteoのCAPE（対流有効位置エネルギー、
  実機取得値2040 J/kgを確認済み）は雷雲発達の指標として60分より先の見通しを提供できるが、
  「CAPE値→雷リスク」への変換は気象学的な閾値設定を要し専門性が高い。T204の
  雷ナウキャスト（実況〜60分）が既に主要な需要をカバーする可能性があり、CAPE延長は
  過剰投資になりうるため、実際に「60分より先も知りたい」という需要が確認できてから
  着手する。
- 対応方針（トリガー到達時）: 降水延長予報（T183、gridFill表現）と同じ経路
  （wind-grid格子へのCAPE変数相乗り）が使えるか検討。閾値設定（気象庁・気象予報士向け
  資料等を参照）を先に固めてから実装する。
- 完了条件（着手時に確定）。

### - [ ] T208. 視程・霧情報の導入可否を調査する 規模S（調査のみ）— トリガー: 山間部・河川霧発生地域での利用報告、または優先度見直し

- 発端: ユーザー要望（2026-08-22）。Open-Meteoの`visibility`変数は取得可能
  （実機取得値29,340m）だが、サイクリングでの実用価値（山岳・河川霧向け、早朝走行時の
  視認性）は関東平野中心の現状ユーザー像に対して優先度が低いと判断。
- 対応方針（調査項目、トリガー到達時）: (1) 表示形式（警告バッジ vs 数値表示）、
  (2) 「霧が出やすい」を判定する閾値（湿度・気温差との複合判定が必要か）、
  (3) 単独の情報価値が低い場合は気温・湿度と合成した「朝もや注意」のような複合指標に
  するか。調査結果を本エントリへ追記し実装可否を判断する（T50〜T54のJICE見送りと同じ
  「調査の結果、見送り」も正当な結論）。
- 完了条件（調査時に確定）。

### - [ ] T209. 黄砂・PM2.5情報の導入可否を調査する 規模S（調査のみ）— トリガー: T175（花粉）の調査完了後

- 発端: ユーザー要望（2026-08-22）。環境省そらまめくん（大気汚染物質広域監視システム）
  等が候補だが未調査。T175（花粉）が調査する「季節性の大気質情報をどう表示するか」
  （春季限定バッジ等の設計）と表現形式を共有できる可能性が高いため、T175の調査結果
  （利用規約・提供期間・地点粒度の調査知見）を踏まえてから着手する方が手戻りが少ない。
- 対応方針（調査項目、トリガー到達時）: (1) そらまめくんの公開データ提供経路（API/CSV）と
  利用規約、(2) Open-Meteoの大気質API（`air-quality-api.open-meteo.com`、別ドメイン・
  別クォータ）でPM2.5・黄砂（dust）が日本域で取れるかの実データ確認、(3) 表示形式
  （T175と共通化できるか）。調査結果を本エントリへ追記し実装可否を判断する。
- 完了条件（調査時に確定）。

### - [x] T210. 通行止め・道路規制情報の導入可否を調査する 規模S〜M（調査のみ、2026-08-22完了・判定: 見送り）

- 発端: ユーザー要望（2026-08-22）。JARTIC規制情報・国交省xROAD系のデータが候補だが、
  T53（JARTIC交通量WFS較正）で使った系統とは別のAPI・別の利用規約の可能性が高く未調査。
- 対応方針（調査項目）: (1) JARTIC規制情報・xROAD等の公開データ提供経路（API/フィード
  形式）と利用規約（商用可否・クレジット要件・更新頻度）、(2) 対象を「サイクリングロード・
  幹線道路の全面通行止め」程度に絞った場合の実装コスト、(3) 表示形式（警告バッジ vs
  地図上の規制区間ハイライト）。冠水・通行止めは「回避一択」のため評価軸にはせず、
  警告表示のみを想定する。調査結果を本エントリへ追記し実装可否を判断する。
- 完了条件: 取得経路の実現可否と規約適合の判断が本エントリに記録されること。
- 依存: なし（T176河川敷冠水と表示形式を共有できる可能性があるため、T176調査後に
  着手すると効率的）。
- 調査結果（2026-08-22）:
  1. **JARTIC規制情報オープンデータ**（`https://www.jartic.or.jp/service/opendata/`）:
     実機確認で「毎月月初に更新し、更新前の情報は取得できなくなります」と明記された
     **月次更新のCSV**と判明。「今、通行止めになっているか」を判定するリアルタイム
     警告用途には使えない（T53で使った交通量WFSとは別に、規制情報自体は月次バッチ
     という性質を持つ）。
  2. **xROAD（道路データプラットフォーム）**: データベース一覧を確認したが、交通量・
     施設点検・重量高さ指定道路・重要物流道路・主要渋滞箇所・交通事故統計・ロードキル・
     道路基盤地図等はあるものの、「通行止め・規制情報」に該当するデータベースは
     存在しない。
  3. NEXCO各社の高速道路規制情報はリアルタイムで提供されているとみられるが、自転車が
     通行しない高速道路が対象のためスコープ外。都道府県警察単位の個別発表は統一APIが
     無く、47都道府県ぶん個別対応するコストが見合わない。
- 判断: **見送り（専用の実装は行わない）**。無償・リアルタイム・統一的なAPIという条件を
  満たす経路が現時点で見当たらないため。T176で発見したJMA指定河川洪水予報API
  （河川の氾濫危険情報）とは異なり、道路そのものの通行止め・規制には行政横断の
  リアルタイム公開データが存在しないというのが結論。
- 再検討条件: JARTIC規制情報がリアルタイム化される、またはxROADに通行止め系
  データベースが新設される等、データ提供状況が変わった場合に再度調査する。

### - [x] T211. 台風情報の専用対応可否を検討する 規模S（調査のみ）— 2026-08-22完了・判定: 見送り（不採用）

- 発端: ユーザー要望（2026-08-22「取り込むべきデータを整理して」）を受けた棚卸しの一環で
  台風進路図・接近情報の専用対応を検討した。
- 判定: **見送り（専用の実装は行わない）**。理由: (1) JMA台風情報の公開JSON API
  （`bosai/typhoon/`配下）は実機確認で404となり、当日時点で対象台風が無く配信自体が
  発生していない可能性が高く安定した検証ができなかった。(2) 台風接近時にサイクリストが
  実際に必要とする情報（強風・大雨・警報の有無）は、T204（雷ナウキャスト）・既存の
  風/降水延長予報・T205（警報・注意報バッジ）の組み合わせで実質的にカバーできており、
  「進路予想円」等の専用可視化を追加する投資対効果が低いと判断した。
- 再検討条件: ユーザーから台風進路図そのものの表示ニーズが明示された場合、または
  上記(1)の技術的制約が変わった場合に再度調査する。

### - [x] T212. JMA指定河川洪水予報を用いた河川敷冠水警告バッジを追加する 規模S〜M（2026-08-22完了）

- 発端: T176調査（2026-08-22）で発見したJMA指定河川洪水予報API
  （`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`、実機確認: 200 OK、
  機械アクセス制限の明記なし）。T176完了条件どおり、無償・規約適合・リアルタイムの
  取得経路が見つかったため実装タスクとして起票する。
- 対応方針: T205（`jma_area.py`の市区町村→JMA警報エリア解決、`WarningBadgeList`）の
  基盤を再利用する。出発地点の市区町村コード（class20/class10コード）が、現在発表中の
  いずれかの河川氾濫予報の対象エリア（レスポンスの`class20Codes`/`class10Codes`）に
  含まれるか照合し、含まれればレベル2〜5（氾濫注意報/警報/危険警報/特別警報）に応じた
  警告バッジを出す。表示形式はT210の判断（道路そのものの通行止めには統一的なリアルタイム
  データが無い）を踏まえバッジ表示のみとし、地図上の規制区間ハイライトは対象外とする
  （河川氾濫予報はエリア単位の情報でありピンポイントの区間表現に向かない）。評価軸には
  しない（冠水は回避一択のため、T176背景の方針どおり）。
- 完了条件: 対象河川の氾濫予報が発表されている地点で警告バッジが表示され、無い場合は
  何も出ないこと。取得失敗時は警告なし（T205/T174と同じfail-open方針）。backend/
  frontend全green。
- 依存: なし。T205の`jma_area.py`・`WarningBadgeList`を再利用する。
- 実装内容:
  - **コード対応表の確定**: 気象庁「指定河川洪水予報」電文フォーマット解説資料の表２
    （令和8年度出水期以降、dmdata.jp経由で取得）を典拠に、`item.code`が「発表/継続/
    警報解除（下位レベルへの引き下げ）/完全解除」を区別することを確認した。JMA警報
    （T205）と異なりstatus文字列ではなくcode自体（`10`=完全解除、それ以外は全て
    アクティブ）が状態を表す。ライブデータ（神田川のレベル4氾濫危険警報→善福寺川の
    レベル2氾濫注意報解除への遷移、2026-08-22実機確認）と突き合わせて検証済み。
  - `backend/app/domain/flood_forecast.py`（新設）: `FLOOD_CODE_LEVELS`（code→レベル
    2〜5）、`CLEARED_CODE`（"10"）、レベル→バッジ4段階（advisory/warning/
    severe_warning/emergency_warning、T174で追加済みの4段階をそのまま流用）の対応、
    `extract_active_flood_forecast`（電文1件から対象地点向けの`ActiveFloodForecast`を
    抽出。class20Code優先・class10Codeへのフォールバックで地点の該当判定）。
  - `backend/app/infrastructure/flood_client.py`（新設）: 洪水予報API取得（10分TTL、
    T205のjma_warning_client.pyと同じ理由でtenacity再試行は無し）。
  - `backend/app/services/flood_service.py`（新設）: T205の`fetch_municipality_code`・
    `fetch_area_data`・`jma_area.resolve_area`を再利用して地点解決し、洪水予報電文
    配列から対象地点にマッチしアクティブなものだけを集約する。地点解決・取得の
    どこで失敗しても空を返す（T205/T174と共有するfail-open方針）。訓練・試験電文
    （`status`≠"通常"）は除外する。
  - `GET /api/weather/flood-forecast`（`weather.py`）: T205/T174と同じfail-open方針
    （502は返さない）。レート制限
    （`weather_flood_forecast_rate_limit_per_minute`）を追加。
  - `frontend`: `WarningBadgeList`（T205/T174と共有）へ河川氾濫予報バッジを合流表示。
    天候・警報・WBGTと同じ地点変更デバウンスに相乗りしてフェッチする。
- 検証: `test_flood_forecast_domain.py`・`test_flood_service.py`（新設、モックした
  地点解決・洪水予報取得関数を差し替えて複数河川該当・解除済み除外・訓練電文除外・
  取得失敗時の空応答を確認）・`test_weather_route.py`への追加（成功/失敗時空応答/
  レート制限）。backend 1029件・frontend 491件・tsc/eslint全green。Playwrightで実機
  確認（検証開始時点で実際に神田川がレベル4氾濫危険警報を発表中だったが、検証の途中で
  実際に解除される事象が発生し、バッジも正しく消えることを確認できた——「code=10=
  完全解除」判定が実データの状態遷移に対して正しく効いている証拠。バッジ表示自体は
  直前に取得した実際のレスポンス形をモックして再現し、配色・タイトル・モバイル幅での
  表示を確認した）。

### - [x] T213. xROADデータベース一覧の全件棚卸しを行う 規模S（調査のみ、2026-08-22完了・判定: 新規採用なし）

- 発端: ユーザー要望（2026-08-22「xROADで使えそうなものがないか調査して」）。T210
  （通行止め・道路規制情報の調査）でxROADのデータベース一覧に触れたが、対象を
  規制情報に絞っていたため全件は横断確認していなかった。
- 対応方針: xROAD公式サイト（`https://www.xroad.mlit.go.jp/database/`）のデータベース
  一覧を全件（14件）確認し、既存の外部データソース検討
  （[external-data-sources-review-2026-08-16.md](external-data-sources-review-2026-08-16.md)
  §2.4等）で評価済みのものは同一実体かどうかを確認、未評価のものは目的適合度・
  組み込みコストを判定する。
- 調査結果（2026-08-22、Browserで全14件を実機確認。カテゴリ内訳:
  交通量データ3・施設点検データ1・ETC2.0データ1・道路の属性データ3・DRM1・
  道路基盤地図情報等2・その他3）:
  1. **既評価と同一データ（結論変わらず）**:
     - 常時観測交通量（国管理道路）= JARTIC交通量API。既に条件付き採用済み
       （T53でtrafficStress較正に使用）
     - 重要物流道路：xROAD上の提供形式はExcel別表・PDF位置図のみで、既に確認済みの
       KSJ N12（GeoJSON、採用候補P2）より機械可読性が劣る。xROAD経由へ切り替える
       理由なし
     - 全国道路施設点検データベース（基礎）：詳細ページの問い合わせ先が
       `pavementdb@jice.or.jp`／`jice.or.jp/pavement_db`であり、T50〜T54で調査し
       見送り確定済みのJICE舗装点検DBと同一実体と確認。橋梁・トンネル・道路附属物・
       土工DBも「構造物健全性≠走行面品質」という既存の不採用理由がそのまま当てはまる
     - デジタル道路地図データベース（DRM-DB）：既に不採用（有償会員限定、OSM＋自前
       MVTと役割重複）
     - 交通事故統計情報：警察庁データそのもの。既に採用済み（8軸目
       accident_density、T117）
  2. **未評価だった項目の新規判定**:
     - 重さ・高さ指定道路：大型車の通行環境を示す点でN10/N12系に近い「大型車ストレス
       の代理指標」候補だが、詳細ページ（`/database/483/`）にダウンロード・APIの
       記載が無く、機械可読データの入手経路が確認できない（問い合わせ窓口のみ）
       → 見送り。入手経路が確認できた場合のみ再訪
     - 主要渋滞箇所：交差点の慢性渋滞地点。詳細ページ（`/database/482/`）も同様に
       ダウンロード・APIの記載なし。加えて「渋滞＝車視点の指標」であり対象交差点は
       既存のtrafficStress評価で元々高ストレス判定される幹線が中心と見込まれ、
       目的適合度も高くない → 見送り
     - ロードキル発生・対策状況：直轄国道限定の動物との衝突事故データ。走りやすさ
       評価（路面・交通ストレス・安全性）の目的と趣旨が異なる → 不採用
     - MMSによる三次元点群データ等：生の点群データで加工コストが特大、直接評価には
       使えない → 不採用
     - 全国道路基盤地図等データベース：直轄国道の地図・道路台帳データ。OSM＋自前MVT
       で充足済み（地理院タイル道路縁と同じ不採用理由） → 不採用
     - ETC2.0プローブ情報：詳細ページに「利用規程上、様式データ（走行履歴・旅行速度
       等）は道路管理者（国交省・高速道路会社等）のみが扱うことができる」と明記され
       一般利用不可。一部地区（「ゾーン30プラス」全国10地区、関東は千葉県市原市の
       1地区のみ）の急挙動データのみCSV公開されているが対象が局所的すぎ評価には
       使えない → 不採用
     - 国際海上コンテナ車（40ft背高）特殊車両通行許可不要区間：大型トレーラーの許可
       要否を示す区間データで、ロードバイクの走りやすさと無関係 → 不採用
     - ODゾーン間交通量データ・断面交通量データ：外部データソース検討（§4.4補足）で
       既に言及済みの「道路交通センサス」系と同一。区間表形式でコンフレーション難度が
       最も高く、位置付けは変わらない（JICE舗装点検DBのゲート3不通過につき見送りの
       まま）
- 判定: **見送り（新規の採用候補なし）**。既に採用・条件付き採用と判定済みのデータ
  （JARTIC・重要物流道路・警察庁事故データ）はxROAD上でも同一実体か、それより
  機械可読性が劣る提供形式であることを確認しただけだった。未評価だった8件は
  いずれも「目的不適合」または「機械可読なデータ入手経路が確認できない」のどちらか
  で見送りとなり、新規の追加候補は無かった。
- 再検討条件: 重さ・高さ指定道路・主要渋滞箇所についてxROAD側にAPI/ダウンロード
  機能が追加された場合、またはETC2.0プローブ情報の利用規程が緩和された場合に
  再訪する。

### - [x] T214. 推定指標ONで材料の観測データを連動ONするカスケードを撤去する 規模S（2026-08-22完了）

- 発端: ユーザー指摘「自由にメンバを表示非表示できることで、裏で表示状態で残るのは
  避けたい。推定配下グループメンバを選択したら、対応する観測メンバを導出onにする
  ロジックを無しにして」。T167（2026-08-19）で導入した「推定指標（車の圧迫感・停止
  密度・事故密度）をONにすると材料の観測データレイヤーも連動ON」するカスケードが、
  T181（表示項目の設定パネル、2026-08-22）で観測グループのメンバーを個別に非表示に
  できるようになったことと衝突するようになった。非表示に設定したメンバーが推定側の
  操作で裏からONにされてしまい、かつ非表示設定でチップ自体が隠れているためOFFに
  戻す手段が無い、というT181で解消したはずの不整合が推定側の操作から再発する。
- 対応方針: `page.tsx`の`handleLayerToggle`から連動ONの分岐を削除し、単純な
  `setLayerVisibility`のみに戻す（片方向カスケード自体を撤去、OFF方向は元々連動
  させていなかったため変更なし）。代わりに、どの観測データが計算に使われているかは
  T167で同時に導入した`renderMaterialsNote`（MapOverlayControls.tsx、推定軸タイルの
  ▼展開時に「材料: ○○」「地図では未表示の材料: ○○」を表示）がON/OFFに関わらず
  常に示すため、自動ONで地図に出す機能を失っても材料の把握手段は失われない。
  2次の下敷き表現（`secondaryAxisCasingLayerIds`、材料が1つでも表示されているときだけ
  太く半透明にする）は連動ONの有無に関わらず現在の`layerVisibility`をそのまま見る
  実装のため変更不要（連動ONが無くなった今は、下敷き効果を見るには材料レイヤーを
  ユーザーが手動でONにする必要があるという素直な挙動になる）。
- 完了条件: 推定指標をONにしても対応する観測データレイヤーが自動ONにならないこと。
  材料一覧の表示（renderMaterialsNote）はそのまま残ること。
- 検証: frontend全体495件・tsc/eslint全green（cascadeを参照するテストは無く、
  page.tsxはこの粒度でunit testされていないため既存テストへの影響なし）。

### - [x] T215. 内訳パネルが画面下端に近い位置で開くとスクロールできないことがある不具合を修正する 規模S（2026-08-22完了）

- 発端: ユーザー報告「スクロールできないことがある」（T181の表示項目設定パネル導入後）。
  調査の結果、2つの独立した原因を発見した。
  1. `.detailPanelBase`（MapOverlayControls.module.css、▶/▼展開の内訳パネル共通の
     外枠）が`overflow-y: auto`（内部スクロールが必要な箱）と`touch-action: none`
     （地図のピンチズームへ誤認されないための指定）を同時に持っていた。
     `touch-action: none`はブラウザのネイティブなタッチパン/スクロール自体を無効化する
     ため、パネルの中身が`max-height`（16rem/45vh）を超えるとモバイルでタッチスクロール
     できなくなっていた。T181で表示項目設定パネルに6〜8項目のチェックボックス付き
     一覧が追加されたことで、この上限を超えるケースが増えた。
  2. パネルは`position: fixed`でJSが測った行の位置（`toggleExpanded`、
     `rect.bottom + gap`等）から浮かせるが、行が画面下端に近い場合にCSS既定の
     最大高さ（16rem=256px）ぶんがビューポート外へはみ出し、fixed要素はドキュメントの
     スクロール領域に算入されないため、パネル自身の内部スクロールが機能していても
     ビューポート外の部分には原理的に到達できなかった。
- 対応方針:
  1. `.detailPanelBase`の`touch-action`を`none`から`pan-y`へ変更。縦方向のネイティブ
     タッチスクロールは許可しつつ、横方向のパンとピンチズームは引き続き無効化される
     ため、元々の目的（地図へのジェスチャー誤認防止）は保たれる。
  2. `toggleExpanded`（MapOverlayControls.tsx）が、パネルの`top`位置と`window.innerHeight`
     から利用可能な高さ（`availableHeight`）を計算し、CSS既定の上限（`DETAIL_PANEL_
     MAX_HEIGHT_PX`=256px、CSSの16remと一致させたJS側定数）より狭ければ`maxHeight`を
     動的に縮めてインラインstyleで上書きする（下限120px）。横方向の`maxWidth`を画面幅
     から逆算する既存の仕組みと同じ考え方を縦方向にも揃えた。
- 完了条件: パネルが画面のどの位置で開いても、常にビューポート内に収まること
  （縮めた分はパネル自身の内部スクロールで見える）。モバイルでタッチスクロールが
  機能すること。
- 検証: `MapOverlayControls.test.tsx`に新規1件追加（`window.innerHeight`と
  `getBoundingClientRect`をモックし、画面下端に近い位置で開いたパネルのmaxHeightが
  下限120pxまで縮むことを確認）、計34件green。frontend全体・tsc/eslint全green。
  Playwright実機確認（モバイル幅390×260pxという極端に低いビューポート）:
  設定パネルの`maxHeight`が動的に143.4pxへ縮み、パネルの下端が常にビューポート内
  （y+height <= viewportHeight）に収まることを確認した。

### - [x] T216. 地図チップのグループ開閉・表示項目設定をlocalStorageへ永続化する 規模S（2026-08-22完了）

- 発端: ユーザー要望「グループの選択状態等は保持しておいて、次開いた時に同じ状態に
  して。時間経過で変動する要素以外は、過去の設定内容はlocalStorage等で保持してほしい」。
  各レイヤーのON/OFF自体（`layerVisibility`）はT47 R-6の時点で`useStoredState`に
  よりlocalStorage永続化済みだが、T166〜T181で追加した観測/推定/動的グループの
  開閉状態（`expandedIds`）とT181の表示項目設定（`hiddenIds`）はMapOverlayControls
  内部の一時的なUI状態のままで、ページ再訪問のたびにリセットされていた。
- 対応方針: `expandedIds`・`hiddenIds`を`useStoredState`（既存のP47 R-6集約フック、
  page.tsxの他の永続化設定と同じ仕組み）へ置き換える
  （`ridecompass:map-overlay-expanded-groups`・`ridecompass:map-overlay-hidden-ids`）。
  `expandedIds`は個々の凡例展開（member:/axis:/単独チップ/`${groupKey}:legend`）まで
  含めると「今ちょっと確認のために開いている」一時的な状態が次回訪問時に勝手にポップ
  アップとして再現されてしまうため、グループ本体の開閉（`GROUP_VISIBILITY_KEYS`:
  group:composite/group:raw/group:dynamic）だけを保存対象にする
  （serialize/deserializeの両方でフィルタし、過去に保存された値・旧仕様の値が
  紛れ込んでも安全側に倒す）。`hiddenIds`は無条件で全件を保存・復元する
  （レイヤー構成が変わり存在しないIDが残っても、現在渡された項目とのマッチングでしか
  使わないため実害はない）。「時間経過で変動する要素」（動的レイヤーの実際のデータ・
  時刻スライダーのフレームインデックス等）はそもそもMapOverlayControlsの管轄外
  （useWeatherGrid/DynamicLayerTimeSlider等）のため対応不要。
- 完了条件: グループを展開し表示項目を設定した状態でページを再読み込みしても、
  同じ開閉状態・表示項目設定が復元されること。個々の凡例展開（一時的なポップアップ）は
  復元されないこと。
- 検証: `MapOverlayControls.test.tsx`に新規1件追加（unmount→再renderで開閉状態・
  非表示設定が復元されることを確認）、既存テストはlocalStorageが前のテストから
  引き継がれないよう`beforeEach`で`window.localStorage.clear()`を追加、計35件green。
  frontend全体497件・tsc/eslint全green。Playwright実機確認: 観測データの表示項目
  設定で「道路種別」を非表示にし観測グループを展開した状態でページをリロードし、
  リロード後も展開状態（aria-expanded=true）と非表示設定（道路種別チップ0件）が
  localStorage経由で復元されることを確認した。

### - [x] T217. トンネル（一次属性）を観測グループの独立レイヤーとして追加する 規模S（2026-08-22完了）

- 発端: ユーザーからの「地図上に描画可能な状態で保持しているが、レイヤー追加していない
  要素を洗い出して」という調査依頼を受けて洗い出した結果、tunnel（OSMのtunnelタグ）が
  該当した。tunnelはnight軸（推定グループ、T145a）の材料として`app/infrastructure/
  road_graph_repository.py`のroad_surfaceタイルへ既に焼き込み済みで、区間ポップアップ
  （`MapView.tsx`）でも「トンネル」として表示されていたが、他の一次属性（道路種別・
  路面等）と違い観測グループ内に独立した色分けレイヤー・チップを持っていなかった。
  ユーザーから「トンネルを観測配下にアイコン追加して」と明示指示を受け実装した。
- 対応方針: designation（指定路線）と全く同じ構成（road_surfaceソースを再利用する
  独立line レイヤー、該当区間のみ`tunnel: true`・非該当はプロパティ欠落）で新規レイヤー
  `tunnel`を追加。バックエンド側の変更は無い（タイルへの焼き込み自体は既存のまま）。
  - `mapLayers.ts`: `MapLayerId`に`"tunnel"`追加、`MAP_LAYERS`へエントリ追加
    （category: roadCondition）、`ROAD_SURFACE_SHARED_LAYER_IDS`へ追加。
  - `staticAttributeLayers.ts`: `TUNNEL_LEGEND`/`TUNNEL_COLOR_EXPRESSION`/
    `TUNNEL_OPACITY_EXPRESSION`を追加（tunnelは文字列列挙ではなく単純な真偽値のため
    `buildCategoricalLayerDefs`ではなく事故と同じcase式で直接記述）、`STATIC_FILTER_AXES`
    へ絞り込み軸を追加。
  - `MapView.tsx`: `ensureTunnelLayer`を追加し`STATIC_OVERLAY_LAYERS`/
    `LAYER_DATA_SOURCES`へ登録、他の1次「素材」レイヤー（道路種別・自転車インフラ・
    指定路線）と同じ並列トラック分離（`ROAD_MATERIAL_TRACK_LAYER_IDS`）にも参加させる、
    `showTunnel` propを新規に配線。
  - `primaryAttributes.ts`: `PRIMARY_ATTRIBUTE_LAYER_IDS`に`tunnel: "tunnel"`を追加、
    `PRIMARY_ATTRIBUTES_WITHOUT_LAYER`から`tunnel`を除去（litのみ引き続きレイヤー無し）。
    これによりnight軸の材料一覧（T167のrenderMaterialsNote）が
    「材料: トンネル」「地図では未表示の材料: 街灯」に変わる（副次効果、実害無し）。
  - `icons.tsx`: `TunnelIcon`（アーチ型の坑口）を新規追加、`MapOverlayControls.tsx`の
    `LAYER_ICONS`へ登録。
- 完了条件: 観測グループを開くと「トンネル」チップがアイコン付きで並び、ONにすると
  地図上にトンネル該当区間が色分け表示され、区間ポップアップの表示内容とも整合すること。
- 検証: tsc/eslint全clean、フロントエンド全体501件green（新規4件:
  `staticAttributeLayers.test.ts`にトンネルの凡例・色分け式のテスト、既存3件を更新
  [`primaryAttributes.test.ts`のaxisMaterialLayerIds("night")期待値、`MapOverlayControls.
  test.tsx`の夜間軸材料一覧テキスト、`MapLayersPanel.test.tsx`のlayerVisibility/
  staticFilterHiddenKeysByAxisフィクスチャ]）。Playwright実機確認（headless chromium、
  dev環境backend:8000・frontend:3000）: 観測グループ展開→「トンネル」チップをON→
  地図上にオレンジ色の該当区間が描画されることを確認、推定グループの夜間軸凡例で
  「材料: トンネル」「地図では未表示の材料: 街灯」の表示も確認。

### - [x] T218. 探索の素材事前計算化＋リーンロード（T12 Stage 0）規模M（2026-08-23完了、一部スコープ調整あり）

- T12 ADR（docs/decisions/t12-routing-scale.md）Part 2で確定したStage 0（共通前提工事）。
  road_graphエンジンのWARM 15.5秒のうち約6割を占める「リクエスト毎のORM全行取得＋
  geometry decode＋空間結合」を、取込時の素材事前計算へ移す。
- 内容:
  - エッジ単位の型付き素材列を事前計算・永続化する（タグ解読結果: highway/lit/tunnel/
    surface分類/cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no/designation、
    件数集計: stop_count/intersection_count/accident_count[`edge_attribute_counts`の配線含む]、
    幾何導出値: bearing）。素材世代番号を持たせ、抽出ロジック変更時の再計算をバッチで
    追跡する。**average_grade（gradient用）は本タスクのスコープに含めない**（T218a参照）
  - 探索経路からgeometryを外す（探索はトポロジ＋距離＋素材＋bearingのみで成立。
    geometryは最終候補の経路エッジ分だけ後から取得する）
  - リクエスト時の空間結合（get_stop_poi_counts等）を保存済み素材の読取りへ置換
  - windのbearing方式（エッジ側は方位のみ、リクエスト時に風ベクトルと合成）をこの
    素材列上で実装
  - ペナルティ強度P（コスト式`距離×(1+P×D/100)`のP、既定1.0）と、0次ハードフィルタの
    しきい値調整（平均勾配X%超の除外等）のAPIパラメータ化
- 完了条件: WARM（データ取込済みエリア）でルート生成が10秒以内（現状15.5秒、
  gradientを含まない前提の数値）。評価結果（軸スコア・区間詳細）が既存実装と一致する
  回帰テストを先に用意してから内部を差し替える（検証の自動化→境界の固定→内部の再配置）。
- 本番DBの素材バックフィル完了を完了条件に含める（T101/T74の教訓: コード変更のみで
  完了扱いにしない）。
- **2026-08-23再検証で判明した重要な訂正**: 当初案はgradient（average_grade）も
  本タスクの素材列に同列で含めていたが、精査の結果これは誤りだった。現行の
  `ElevationAttributeService`は1エッジの形状点ごとにGSI点標高APIを呼ぶ設計で、
  実測（`backend/benchmarks/README.md`）では480エッジに対し2,880回（1エッジ平均6点）の
  呼び出しが発生している。本番規模（road_edges 207,767件〜関東全域想定134万件）へ
  全道路網一括で適用すると数十万〜百万オーダーのGSI呼び出しが必要になり、これは
  T10（DEMタイル化＋標高キャッシュ1系統化）が定義する「全道路網一括の標高属性事前計算」
  というトリガー条件にそのまま該当する。したがってgradient対応はT218本体から
  切り出し、T10を前提とするT218aへ分離した。

- **実装メモ（2026-08-23完了）**:
  - migration 0013（`road_edges.bearing_deg`列を追加、`ST_Azimuth`によるSQLのみの
    バックフィル）。`domain/graph.py: build_road_graph`がforward/backward双方の
    実方位角を計算して埋める。`domain/evaluation.py: compute_wind_penalty`は
    `edge.geometry`ではなく`edge.bearing_deg`を直接読む形へ変更（探索フェーズが
    geometryに依存しなくなった）。
  - `edge_attribute_counts`（T144、書き込み専用のまま放置されていた）に読み取りメソッド
    `get_edge_attribute_counts`を新設し、`get_stop_poi_counts`/`get_intersection_counts`/
    `get_accident_counts`の3本の空間結合クエリを1本のキー参照へ集約（road_graph_engine.py:
    prepare()を変更）。
  - `RoadGraphRepository.get_graph_topology_in_bbox`（geom列を一切SELECTしない軽量版）＋
    `get_edges_with_geometry`（最終候補のEdgeだけ実ジオメトリを取得し直す）を新設。
    `GraphService.get_or_build_graph_with_attributes`に`lean`引数を追加し、
    `RoadGraphEngine.prepare`はlean=Trueで探索用グラフを取得、`trace_loop`が
    Dijkstra確定後の経路エッジぶんだけ`get_edges_with_geometry`で実ジオメトリを
    後付けする設計（DirectedEdge自体は変更せず、探索専用の空リストプレースホルダを
    使う設計にとどめ、Overpassライブ経路への影響もゼロ）。
  - `penalty_strength`（P、コスト式`距離×(1+P×D/100)`）をAPI（`RouteGenerateRequest`）
    まで配線し、`GenerationConditions`へエコー。既定1.0で従来と完全に同一の挙動。
  - **スコープ調整（当初案からの変更）**: タグ解読結果（highway/lit/tunnel/surface分類/
    cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no/designation）の専用テーブル
    事前計算は見送った。`get_way_tags`/`get_designated_edge_ids`は空間結合ではなく
    `osm_way_id`の単純なキー結合（インデックス済み）であり、実測の主要因（ORM全行
    decode・3本の空間結合）ではないため、リスクに見合わないと判断した。将来ボトルネックと
    判明すれば再検討する。
  - 0次ハードフィルタのしきい値調整（平均勾配X%超の除外等）はT218aへ持ち越し
    （gradient素材がまだ無いため対象が無い）。
  - 検証: 既存回帰テスト（`test_evaluation.py`・`test_road_graph_engine.py`・
    `test_routes_generate.py`ほか）を新実装向けに更新し、backend全体1030件green。
    ローカルdev DB（実データ122,189エッジ）で`get_graph_topology_in_bbox`と
    `get_graph_in_bbox`を直接比較計測し、エッジ集合が完全一致すること・
    1km相当bboxで約0.9秒→約0.5〜0.65秒、4km相当bboxで約1.6秒→約0.8〜1.2秒への
    短縮を確認（`get_edge_attribute_counts`・`get_edges_with_geometry`も実データで
    動作確認済み）。ただしWARM 15.5秒→10秒以内というエンドツーエンドの目標値は、
    この計測方法（`get_or_build_graph_with_attributes`経由）では別要因
    （`is_split_up_to_date`がFalseになる既存の未整理な状態、T218とは無関係）に
    阻まれ再確認できておらず、今回検証したのはボトルネックの主要部分
    （geometry decode）のみである点に留意。
  - **本番Oracle DBへのmigration適用・バックフィルは未実施**（ローカルdev DBのみ適用・
    検証済み）。実行前にユーザーへ確認すること。

### - [ ] T218a. gradientの探索コスト組み込み（T12 Stage 0.5）規模M〜L — トリガー: T10完了

- T12 ADR Stage 0.5に対応。T10（DEMタイル化＋標高キャッシュ1系統化）の実装により
  DEMタイル一括取得＋ローカル補間でaverage_gradeをエッジ単位に一括算出できるように
  なった後、その素材をT218の素材列へ合流させ、gradientをPart 1決定5どおり探索コストへ
  組み込む。
- 本タスクの新設によりT10は「トリガー未到達で優先度最低」の位置づけから、
  「Part 1で確定済みの決定（gradientを探索コストに入れる）を実現するための直接の
  前提タスク」へ格上げされる。T10自体の着手判断（優先順位節参照）を参照すること。
- 完了条件: 山岳ルート（平均勾配の高いエリア）でgradient重み・ペナルティ強度Pを
  上げると実際に経路が変わることを確認。

### - [ ] T219. 探索グラフのプロセス内タイルキャッシュ（T12 Stage 1）規模M — トリガー: T218完了

- T218の素材・トポロジ配列をz12タイル単位でプロセス内LRUキャッシュする
  （キー=タイルID＋素材世代、世代不一致で破棄。上限はエッジ数ベースで設定し実測で調整。
  想定メモリは40〜60B/エッジ、関東全域でも55〜80MB程度）。
- `find_nearest_node`の全ノード線形走査（20万ノード規模で計1.7秒/リクエスト）を
  タイル毎の空間索引（グリッドバケット等）へ置換する。
- 完了条件: 同一エリア2回目以降のルート生成が5秒以内（キャッシュ温の数値目標）。

### - [ ] T220. 探索データ構造のscipy化（T12 Stage 2）規模M — トリガー: T219完了後の実測で「評価＋NetworkX構築＋trace」が目標を超過した場合のみ

- 計測ゲート付きの保留タスク。T219完了後の実測でキャッシュ温5秒以内を達成できて
  いれば着手しない（計測せず先回りで依存を増やさない、T12 ADR Stage 2参照）。
- 発動時の内容: コスト合成のnumpyベクトル化＋`scipy.sparse.csgraph`（CSR＋C実装
  Dijkstra）への置換。依存にnumpy/scipyを追加。
- 2026-08-23再検証: 本タスク起票時に引用した「NetworkX構築は実測1.4秒/15万エッジ」は、
  実際には`get_graph_in_bbox`内のORM行→RoadGraphドメインオブジェクト構築（別工程）の
  数値であり、`build_networkx_graph`自体の実測値ではなかった（記述ミス、訂正済み）。
  `build_networkx_graph`単体の実測値は現時点で存在しない。ゲートの判断根拠は
  事前の推定値ではなくT219完了後の実測に置くため、本タスクの発動要否はその実測を待つ。

### - [ ] T221. 評価軸のフルレジストリ駆動化＋GUI編集基盤 規模L（設計のみ、Part 2以降は未着手）— トリガー: ユーザーの実装着手指示

- 背景: T12原則7の再検証（2026-08-23）で、現行7軸の変換ロジックが実質3テンプレート
  （折れ線補間・カテゴリ変換・フラグ加算、+car_stressの「レシピ→レベル→折れ線補間」の
  複合形）に還元できることが判明した。ユーザーから「将来的には見た目の磨き込み部分だけ
  IFで切り出して残し、裏のロジック部分はすべてフルレジストリ駆動化したい」という将来像
  （2026-08-23）を受け、独立したADRとして起票した。
- ADR: `docs/decisions/t221-axis-registry.md`（ドラフト、2026-08-23起票）。
  ロジック層（素材選択・変換テンプレート・パラメータ・重み・合成）を完全レジストリ駆動へ、
  見た目（アイコン・略名・案内文）は無指定時に汎用フォールバックが効くUIオーバーライド層へ
  分離する方向性のみ承認済み。段階構成（Stage A: 4テンプレートへの実装移行〜Stage E:
  GUI編集画面）・具体的スキーマ・DB化の要否は未承認のドラフトのまま。
- T12（探索速度）とは独立した設計課題だが、素材カタログ（T218参照）を共有する。
  Stage D（DB化）はT12 Part 2のキャッシュ無効化条件（軸定義の版数）との整合が要る。
- 未決の製品判断: GUI編集を誰に開放するか（研究モード限定か否か）、軸追加・重み変更の
  安全性検証をどう設けるか。詳細はADR末尾参照。

### - [ ] T222. Overpassライブ経路（`repository`未指定構成）の削除 規模M — トリガー: ユーザーの実装着手指示

- 背景: T218（探索の素材事前計算化＋リーンロード）実装時に判明。`GraphService`は
  `repository`未指定時、`OverpassClient.get_ways_and_nodes`経由でOverpassから都度
  Road Graphを構築する経路を今も持つ（T22でoverpass_fallback_enabled設定・
  PythonMVTエンコーダ・`OverpassClient.get_roads`は撤去済みだが、`get_ways_and_nodes`は
  「DBなし構成専用」として意図的に存続、`docs/improvement-plan-archive/2026-08-15.md`
  T22参照）。本番・dev環境は常に`repository`を注入するため到達しないが、コードとしては
  並行して残り続けている。
- 対応方針（着手時に検討）: `GraphService.__init__`から`overpass_client`/`http_client`
  引数と`repository`未指定分岐を削除し、`repository`必須の構成へ一本化する。
  `build_graph_with_surface_tags_for_bbox`・`_fetch_graph_with_surface_attributes`・
  `_build`・`OverpassClient.get_ways_and_nodes`本体の要否も合わせて判断する（DBなし構成の
  テスト・ローカル検証で使われている場合は移行方法を検討する）。
- 完了条件: `repository is None`分岐が`GraphService`・`RoadGraphEngine`関連コードから
  消え、DBなし構成に依存していたテストが新方式（repositoryへの直接シード等、T22の
  `test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`と
  同じ移行パターン）で置き換わること。

## 残タスクの優先順位（2026-08-23再整理・第3版）

ユーザー要望「改めて改善計画の洗い出しを行って」を受け、未完了（`[ ]`）の全15タスクを
横断して仕分け直した最新版。判断基準は従来と同じ3軸（依存関係・季節等のタイミング制約・
コスト）。T12関連の再検証（T10とT218の依存関係／評価軸可換性の訂正）とT221の新規起票を
経た後の版であり、これらの経緯は各タスク本文・T12 ADR・T221 ADRに残してあるため、
本節では最新の結論のみを記す。

- **今すぐ着手できる（トリガー成立済み、優先度順）**:
  1. **T209**（黄砂・PM2.5情報の導入可否調査、規模S・調査のみ）: トリガー「T175完了後」が
     2026-08-22のT175完了時点で既に成立している。着手コストが全残タスク中最小の調査で、
     見送るべき理由が無い。
  2. **T218**（探索の素材事前計算化＋リーンロード、T12 Stage 0、規模M、gradientを除く
     6素材構成）: T12 ADR（Part 1・Part 2）が全項目確定し設計上の障害は無い。
     トリガーは「ユーザーの実装着手指示」のみ——外部要因待ちではなく、ユーザーが
     号令を出せば即着手できる状態。
  3. **T221**（評価軸のフルレジストリ駆動化＋GUI編集基盤、規模L・方向性のみ承認済み）:
     T218と同様「ユーザーの実装着手指示」のみがトリガー。ただし段階構成（Stage A〜E）・
     具体的スキーマはドラフトのままのため、着手する場合はStage A（既存7軸を4テンプレート
     へ実装移行）の詳細設計から始まる点はT218より1段階手前。

  上記2・3はいずれも**本整理は洗い出しのみで着手はしない**（明示指示を待つ）。両者は
  独立に着手可能（T221のStage Aは既存軸の実装移行が中心でT218のリーンロードとは
  ほぼ独立、素材カタログの部分だけ将来的にすり合わせが要る＝T221 ADR参照）。

- **トリガー未到達（現時点では着手しない、トリガー成立が近いと見込まれる順）**:
  1. **T206**（積雪・凍結情報、規模S〜M）: トリガー「冬季前=11月」。残タスク中もっとも
     季節トリガーの到達が近い（約2.5ヶ月後）。
  2. **T219**（プロセス内タイルキャッシュ、T12 Stage 1、規模M）: トリガー「T218完了」。
     設計は確定済みでT218完了後は即着手できる状態になる。
  3. **T220**（探索データ構造のscipy化、T12 Stage 2、規模M）: トリガー「T219完了後の
     実測が目標未達の場合のみ」。計測ゲート付きで、T219の結果次第では発生しない
     可能性もある。
  4. **T11**（`segments`のAPI境界ビン化、規模M）: トリガー「road_graphエンジン常用化」。
     常用化にはroad_graphの応答速度が実用域に達している必要があり、事実上
     T218〜T220の成果に依存する間接トリガー。
  5. **T10**（DEMタイル化＋標高キャッシュ1系統化、規模L）: トリガー「全道路網への標高
     属性の一括事前計算が必要になったとき」。**2026-08-23の再検証で実質成立が確定**——
     T218a（gradientの探索組み込み、Part 1で確定済みの決定）の直接の前提であることが
     判明したため、「トリガー未到達の低優先タスク」という従来の位置づけから見直し済み。
     山岳ルート回避（ユーザー要件）を実現するにはT10を経由する以外の現実的な道筋が無い。
  6. **T218a**（gradientの探索コスト組み込み、T12 Stage 0.5、規模M〜L）:
     トリガー「T10完了」。T10完了後に着手可能。
  7. **T145a**（night軸の専用レイヤー追加、規模S〜M）: トリガー「lit/tunnelタグデータの
     充実」。T217（2026-08-22）でtunnelは観測グループの独立レイヤーになったが、これは
     night軸自体のレイヤー化ではなく、トリガーである「litタグの疎さ」自体は変化していない。
  8. **T105**（地図操作直後にバックエンド到達不能になる事象の原因特定、規模S〜M）:
     トリガー「次回の再現報告」。現時点で再現報告なし。
  9. **T127**（日本全国データ取込の実現可能性検証、規模不明・調査は完了/実施内容は
     未定）: トリガー「全国展開の意思決定」。意思決定自体が発生していない。
  10. **T145**（地図レイヤーパネルのレジストリ駆動化・三次レイヤー新設、規模L）:
      2026-08-19にT145a/T145bへ分割済みで、本体（三次レイヤー新設）は明確なトリガーを
      持たず「実施時期はユーザー判断」という裁量待ちのまま。
  11. **T207**（雷ポテンシャルCAPE延長予報、規模S）: トリガー「T204だけでは見通しが
      不足するという利用実績・要望」。未到達。
  12. **T208**（視程・霧情報の導入可否調査、規模S・調査のみ）: トリガー「山間部・河川霧
      発生地域での利用報告」。未到達。

いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

**サマリ（15タスク）**: 今すぐ着手可能3件（T209・T218・T221、いずれも指示待ち）／
季節トリガー接近1件（T206）／T10（実質トリガー成立、T218a経由でPart1決定の前提）1件／
T10・T218後続の段階待ち3件（T218a・T219・T220）／road_graph常用化待ち1件（T11）／
外部要因待ち5件（T145a・T105・T127・T207・T208）／裁量待ち1件（T145）。

過去の再検証内容（T10↔T218の依存関係の確定、評価軸可換性「レジストリ2箇所だけでは
完結しない」という訂正の詳細）は`docs/decisions/t12-routing-scale.md`（原則7・Stage 0.5）
に、評価軸のフルレジストリ駆動化構想は`docs/decisions/t221-axis-registry.md`に記録済み。

---

完了タスクの日付別一覧は[docs/improvement-plan-archive/README.md](improvement-plan-archive/README.md)を参照
（2026-08-19棚卸し整理でこの位置にあった「記録」表を移設）。
