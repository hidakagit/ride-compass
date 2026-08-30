# 設計原則（正本、仕様のみ）

このファイルはRideCompassの**仕様としての設計原則**（システムがどう構造化されているべきかの
契約）の唯一の正本である。「開発時にどう判断し、どう進めるか」というプロジェクトの進め方は
ここに置かず`docs/improvement-plan.md`「進め方の原則」節へ分離する（2026-08-31、
ユーザー指摘「共通化の判断基準は仕様ではなくプロジェクトの進め方」を受け、両者を明確に
分離した）。

レビュー結果（`docs/*-review-*.md`・`.claude/commands/review/history/`）は**その時点の指摘**
であり、指摘を踏まえて確定した原則はレビュー結果側へ追記するのではなく、必ずこのファイルを
書き換える（2026-08-31、原則が`design-review-2026-08-15.md`・`complexity-review-2026-08-16.md`
という2つの日付付きレビューファイルの末尾に分散し、新しい仕組みを作る際に参照されないまま
同種の違反が繰り返された実績を受けて新設・統合した）。

各原則は簡潔に保ち、発見の経緯・事故の詳細は元のレビューファイル（各原則末尾のリンク）へ
譲る。「どう判断し、どう進めるか」（共通化の判断基準・新規実装前の原則点検・DEFERの運用等）
というプロジェクトの進め方は、このファイルではなく
[.claude/commands/review/principles.md](../.claude/commands/review/principles.md)
「判断原則」節に集約する（2026-08-31、仕様と進め方の分離をユーザーが指示）。

---

## 構造仕様（最重要、RideCompass固有のアーキテクチャ契約）

以下はRideCompass自身の構造（軸スタジオ・評価軸パイプライン・エンジン間契約等）を定める
ものであり、他プロジェクトへ持ち出せる一般則ではない。

1. **フロントエンドとバックエンドの境界**: 材料の計算式・軸の定義・しきい値・重みは
   backendが唯一の正として持つ。frontendは軸スタジオ/backendが配信した値を汎用機構で
   描画するだけで、軸固有の判断ロジック・計算式・しきい値をfrontend側に持たない。
   （2026-08-31、`windPenalty.ts`がbackendの`WindCalculator.wind_penalty`をJS移植して
   いた事例を機に明文化。詳細は本ファイル下部「関連する過去の逸脱」参照）
2. **材料と軸の区別**: 個々の材料の取得・正規化・物理量の計算式は、材料ごとにbackendの
   Pythonで個別に持つ（材料の実体が違う以上、共通化できない。これは許容する）。
   しかし「軸」（材料を束ねて評価に使う単位、軸スタジオが管理する対象）は、軸スタジオで
   設定した内容を唯一の正として動作する。軸ごとにfrontend側のファイル・関数・定数・propを
   持たない。新しい軸を追加するときfrontendのコード変更が一切不要（軸スタジオでの登録の
   みで完結する）状態を仕様とする。
3. **評価軸の追加は1本道のみ**: 取込（profile/ALLOWED_TAGS）→ domain純関数 →
   共通合成関数（1箇所）→ RoutePreference/YAML → AttributeRepositoryメソッド＋
   ファサード対称委譲 → フロントはevaluationAxes/staticAttributeLayersの
   カタログ編集だけ、という一本のデータフローのみを持つ。エンジンファイルに軸固有の知識を
   持たない。この構造は`dedicated_way_value_layer`軸（wind/gradient等、専用の
   way_id→値配信レイヤーを持つ軸）にも同様に適用する——feature-stateキー・
   color expression・redraw再適用・interactiveLayerIds所属・環境グループのgridFill計算は、
   いずれも軸スタジオのデータから導出する汎用機構1つが持つ。
   （`docs/complexity-review-2026-08-16.md`原則1・13参照）
4. **概念の正準定義はbackend domain層に1箇所**。他所（SQL・フロント）はバインド・生成・
   検証テストで追従する構造とし、手書きコピーを持たない。
   （`docs/design-review-2026-08-15.md`原則1参照）
5. **同名フィールドの意味をエンジン間・境界間で変えない**。やむを得ない場合は
   wind_score方式（docs明記＋識別フィールド＋両側の型コメント）を必須とする。
   （`docs/design-review-2026-08-15.md`原則2参照）
6. **生データと派生データを分ける。派生は常に再生成可能な構造とし、導出できるものを
   テーブルに実体化しない**（実測で必要と示された場合のみ例外）。
   （`docs/design-review-2026-08-15.md`原則5参照）
7. **トランザクション境界はサービス層。Repositoryはcommitしない構造とする。**
   （`docs/design-review-2026-08-15.md`原則4参照）
8. **拡張可能なレジストリは常に1本道の追加点を持つ**（原則3「評価軸の追加は1本道のみ」の
   一般化）。評価軸に限らず、材料カタログ（`material_catalog.py`へ1件追加するだけで
   軸スタジオの選択肢へ反映）・動的気象要素（`wind_grid.py`の値フィールド追加→データ層
   モジュール新設→`DYNAMIC_WEATHER_RENDERERS`へ1エントリ→地図チップ登録、という定められた
   4段階）等、「種類が増えうるもの」はすべて、追加時に消費側の既存コードへ手を入れず
   1箇所（レジストリ・カタログ・宣言テーブル）への追加だけで下流の全消費者へ伝播する構造に
   する（`docs/modules/backend/axis-studio.md`・`evaluation-scoring.md`・
   `docs/modules/frontend/dynamic-weather-layers.md`参照）。
9. **軸カタログはbackendからfrontendへの片側importのみで流れる**。`axis-catalog.json`
   （`export_openapi.py`がビルド時にDBから書き出す静的生成物）は、frontend側で
   (a) 実行時API（`GET /api/axis-catalog`）フェッチ完了までの一時的なフォールバック、
   (b) ビルド時にしか導出できない定数（`DEDICATED_WAY_VALUE_LAYER_IDS`等）の生成源、
   の2用途にのみ使う。frontendからbackend側の生成物へ書き戻す経路は持たない
   （`docs/modules/frontend/axis-studio.md`・`map-axis-coloring.md`・
   `static-map-layers.md`参照）。

一般的なソフトウェア工学の慣習（数値定数の片側import・スキーマ変更はmigrations/のみ・
フォールバック経路へ新機能を実装しない・空間JOINのGiST索引利用・UIの語彙表カタログ集約等）は
RideCompass固有の仕様ではないため、このファイルには置かない。レビュー観点として
`.claude/commands/review/overall.md`・`complexity.md`の各確認観点に集約している
（2026-08-31、ユーザー指摘を受け分離）。

## UI仕様（RideCompass固有——地図アプリであることに由来する制約）

- 地図アプリとして地図表示エリアを最大限確保する構造を優先する。UI文言は表示幅を
  圧迫しない（全角括弧でなく半角角括弧`[]`、共通語の重複表現を割愛）。パネル・
  ポップアップ・凡例のいずれも地図そのものの視界を削ってまで情報量を増やさない。
  （`docs/complexity-review-2026-08-16.md`原則12）

---

## 関連する過去の逸脱（教訓、詳細は各リンク先）

- `windPenalty.ts`がbackendの物理式をJS移植・`WIND_AXIS_THRESHOLDS`が軸スタジオから
  独立したハードコード定数・`windAxisPenalties`/`gradientAxisValues`という軸ごとの
  別名propという3つの症状が、いずれも構造仕様1〜3の違反として同一原因だった
  （2026-08-31、ユーザー指摘。詳細調査は別途タスク化予定）。
