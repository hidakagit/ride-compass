# 改善実行計画（2026-08-15 設計レビュー対応）

[design-review-2026-08-15.md](design-review-2026-08-15.md) の指摘に対する実行計画。
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

### - [ ] T7. 路面・道路種別語彙の整合〔F1/F2〕規模M

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

### - [ ] T8. architecture.md の「現状」と「経緯」分離〔D3〕規模M

- `docs/architecture.md` → 現状仕様のみの `docs/architecture.md`（大幅スリム化）と、
  経緯・決定記録の `docs/decisions/`（ADR形式、既存の時系列記述をほぼそのまま移設）へ分割。
- CLAUDE.md の参照先・docs/osm-pbf-import.md 等からのリンクを更新。
- 完了条件: 「現在の構成・API・データフロー」が経緯を読まずに把握できる。履歴情報は失われない。

---

## Phase 3: 機能追加と合わせて（トリガー条件付き）

### - [ ] T9. `surface_attributes` の導出化〔C4/E2〕規模M — トリガー: 関東圏へのデータ拡大 or 容量逼迫

- surfaceを `road_edges` 列に持たせる（highwayと同じ扱い）か、`osm_raw_ways` とのJOINで導出し、
  `surface_attributes` テーブルを廃止。WARM時間（現状8〜11秒の主成分）と容量の削減を実測で確認。

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

## 記録

| 日付 | 完了タスク | 備考 |
|---|---|---|
| 2026-08-15 | （計画作成） | レビュー実施・本計画策定 |
| 2026-08-15 | T1 | .github/workflows/ci.yml 追加。ローカルで全チェックgreen確認（backend 391件・frontend 122件・eslint・tsc） |
| 2026-08-15 | T2 | 符号付きへ統一（backend 392件green）。正準定義をdomain/route.pyへ明記、architecture.md追記 |
| 2026-08-15 | T3 | useMemo化（lint・tsc・vitest 122件green）。Phase 1完了 |
| 2026-08-15 | T6 | RoadGraphRepositoryを責務別4クラス(RawOsm/DerivedGraph/Attribute/TileQuery)＋公開API互換ファサードへ分割。書き込みメソッドのcommitを全廃しサービス層が操作のまとまりごとにcommit()する規約へ（「生データ保存＋タイルマーク」「分割結果＋SurfaceAttribute」が各1コミットになり原子性が向上）。mark_tile_cachedはmerge→Core UPSERT化(text()実行がautoflush対象外のため)。全392件green |
| 2026-08-15 | T5 | api/routes.py(400行)をdependencies.py＋routers/5ファイルへ分割、レート制限・同時実行上限8値をSettingsへ外部化(.env上書き可)。テストはimportパスのみ更新で全392件green、OpenAPI再生成で契約不変を確認 |
| 2026-08-15 | T4 | export_openapi.py＋openapi-typescript導入。types/route.ts・weather.tsを生成型の再エクスポート化（geometryのみGeoJSON補正、Required<>で必須化）。CIにapi-contractドリフト検知ジョブ追加。surface_summary/valuesは契約が自動導出になったため個別整理は不要と判断 |
