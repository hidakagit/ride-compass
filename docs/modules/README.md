# モジュール別設計書（索引）

機能単位の「現状の設計」を記す場所。フロント/バックで分け、各モジュール内は実コードの
みを根拠に記述する（レビュー結果・タスク記録は参照しない。経緯が必要な場合は
[docs/design-principles.md](../design-principles.md)や`docs/tasks/`側の該当タスクへ
リンクする）。

コードと乖離が生じたら、変更と同一コミットでここを更新する
（[design-principles.md](../design-principles.md)構造仕様「docsは現状と経緯を分ける」
参照）。

## backend

| モジュール | 内容 |
|---|---|
| [軸スタジオ・評価軸定義](backend/axis-studio.md) | `axis_definitions`テーブル・評価式・API |
| [ルート生成エンジン・経路探索](backend/routing-engine.md) | road_graph/openrouteserviceエンジン、周回生成戦略 |
| [評価・スコアリング](backend/evaluation-scoring.md) | 0次フィルタ・軸別difficulty合成・材料カタログ |
| [動的材料・way_id値配信](backend/dynamic-way-values.md) | 風・勾配のRedis配信層 |
| [静的道路属性・タイル配信](backend/static-road-attributes.md) | OSM取込・MVTタイル配信 |
| [気象・動的レイヤー](backend/weather-dynamic-layers.md) | Open-Meteo・気象庁データ |
| [標高](backend/elevation.md) | GSI DEMタイル |
| [横断基盤](backend/cross-cutting-infrastructure.md) | DB・Redis・ログ・レート制限・ジョブ管理 |

## frontend

| モジュール | 内容 |
|---|---|
| [軸スタジオ管理画面](frontend/axis-studio.md) | `/admin`の軸CRUD UI |
| [ルート設定・結果パネル](frontend/route-settings-and-results.md) | 重み設定・候補一覧・軸別内訳・比較表 |
| [地図: 軸・ルート色分け](frontend/map-axis-coloring.md) | dedicated_way_value_layer軸の描画 |
| [地図: 動的気象レイヤー](frontend/dynamic-weather-layers.md) | 風・降水・キキクル等の地図表示 |
| [地図: 静的レイヤー・道路表示](frontend/static-map-layers.md) | 路面・道路種別・POI・事故の地図表示 |
| [ページ全体構成・状態管理](frontend/page-composition.md) | `page.tsx`のコンポジション・永続化 |
| [開発者/研究者機能](frontend/developer-research-tools.md) | デバッグログ・システム状況・研究モード |
