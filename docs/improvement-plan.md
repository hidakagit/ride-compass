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

### - [ ] T154. docs/architecture.md §7をT130〜T151全体（レジストリ制導入・区間インスペクタ・
  base_by_highway共有）へ包括的に追従させる 規模M

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

### - [ ] T156. registry_defaults.pyとevaluation.pyの軸ID集合のドリフト検知テストを追加する
  規模S

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

### - [ ] T157. MapView.tsxの閾値付きKEEPをレジストリ駆動レイヤーの実態に合わせて
  再定義する 規模S（基準整備のみ、コード変更なし）

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

### - [ ] T160. 軽微な残骸・記述陳腐化・表記ゆれ4件を解消する 規模S（各項目S）

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
  (1)はユーザー判断の記録。


---

完了タスクの日付別一覧は[docs/improvement-plan-archive/README.md](improvement-plan-archive/README.md)を参照
（2026-08-19棚卸し整理でこの位置にあった「記録」表を移設）。
