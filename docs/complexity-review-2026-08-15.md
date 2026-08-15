# 複雑度平衡レビュー（2026-08-15・第2回）

同日の全体設計レビュー（[design-review-2026-08-15.md](design-review-2026-08-15.md)、T1〜T8完了後）に続けて実施した、
「複雑度の過不足」観点のコードベース全体レビューの記録。実行計画は [improvement-plan.md](improvement-plan.md) の
「第2回レビュー対応」節（T16〜T22）を参照。

レビュー方法: backend全45モジュール・frontend全30ファイル・docs・git履歴40コミットを通読し、
「局所的には正しいが全体として不自然」な箇所と、次の大規模変更（[static-road-attributes-plan.md](static-road-attributes-plan.md)、
約10属性の追加）に対する構造的な耐久性を重点的に調査した。

---

## 総合評価

**大規模変更直後のコードベースとしては異例に健全。** 実測に基づかない最適化はゼロ、
理由なき抽象化・理由なきデータ変換は見当たらなかった。最大のテーマは修正ではなく**順序**:
静的属性計画をこのまま始めると、後述の2つの構造的な税（二重評価パイプライン・属性追加経路の
増幅要因）が約10回払われる。実装前にT16〜T19（ゲートタスク）を完了させること。

5段階評価: Architecture 4 / Complexity Balance 3 / Responsibility Separation 4 / Data Model 3 /
Data Flow 4 / Extensibility 4 / Maintainability 4 / Performance 4 / Testability 4 / FE-BE Boundary 4

---

## Top Issues（全体最適への影響順）

### I-1. 二重評価パイプライン（エンジン税）〔最重要・方針決定が先〕

評価（標高・風・路面）がエンジン内部の責務になっており、路面語彙2系統（ORS数値ID / OSMタグ）・
標高2経路（`ElevationService` / `ElevationAttributeService`）・風2意味論が併走する。
評価の変更が常に2回＋意味整合テストになり、既にgradient符号（B1）・chipsealドリフト（F1）の
2事故の実績がある。さらに**静的属性計画の新指標（交通ストレス・信号密度等）は自前DBのタグで
しか計算できず、既定エンジン（openrouteservice）では原理的に算出不能**。このままでは
「主要な新機能が既定エンジンで動かない」構造矛盾へ発展する。

- **根本原因**: 評価が「経路計算エンジン」の内部にある。本来、評価は**geometry × 自前道路DB**の
  関数であり、経路をどのエンジンが引いたかに依存する必然はない
- **推奨**: ADRで方針だけ先に決める（T16）。ORS産geometryのサンプル点を自前DBのEdgeへ
  空間マッチ（PostGIS KNN）して属性を読む「評価の一本化」を目標状態とし、実装は静的属性の
  取込後（T21）。それまで新指標はORS側で**最初からNone**を返す設計に統一する

### I-2. 属性追加経路の広さ × これから10属性

属性1つ（表示のみ）で backend 7〜9箇所＋再取込: `import_profile.yaml` → `WaySpec` →
`osm_adapter` → `OsmRawWayRow` → `create_tables` ALTER → `save_raw_ways`（行dict＋
change_detection）→ MVT SQL → `vector_tile.py`（フォールバック側）→ タイル世代ペア×2。
経路自体は健全（設計原則6どおり）で、**増幅要因（二重エンコーダ・手書きALTER・ファサード）が
未除去なだけ**。タグのJSONB汎用化は正準語彙の仕組み（索引・MVT焼き込み・整合テスト）を壊す
ため**採用しない**。増幅要因の除去（T17〜T18・フォールバック撤去）後は5〜6箇所に減る。

### I-3. スキーママイグレーション不在

`create_tables` に冪等ALTER×6・インデックス追加/削除・バックフィルUPDATEが蓄積。
列追加10回・新テーブル（ノード属性・POI）追加に耐えない。Alembicフル導入までは不要で、
**番号付きSQLファイル＋適用記録テーブル**の最小機構で十分（T17）。

### I-4. Overpassフォールバックの2×2構成マトリクス

`repository`有無 × `overpass_fallback_enabled` の4構成を `GraphService`/`RegionService` が分岐。
本番は既にPostGIS第一系統＋フォールバック無効で移行は実質完了しているのに、全コード経路が
生存し分岐・テスト・属性追加時の変更箇所を倍にしている。撤去条件を明文化して決め（T16）、
成立後に分岐・`vector_tile.py`・`OverpassClient.get_roads` を一括削除（T22）。
**それまで新属性はフォールバック側に実装しない。**

### I-5. Repositoryファサードの13委譲メソッド〔T18実施で判明・訂正〕

初回レビュー時は「T6分割後の過渡的重複で削除可能」と評価したが、T18着手時に**誤りと判明**。
`GraphService`/`ElevationAttributeService`/`RegionService`はこのフラットな委譲メソッド群を
ダックタイピングで期待する設計になっており、対応するテストも同じフラットな形の
`FakeRoadGraphRepository`等を独立して注入している。委譲メソッドは重複ではなく、
サービス層とテストが依存する正式なインターフェース契約だった。

**訂正した推奨**: 削除しない。新しい属性メソッド（静的道路属性計画向け）を追加するときは、
個別リポジトリに実装したうえで、同じ流儀でファサードにもフラットな委譲メソッドを追加する
（対称性を維持）。ファサードのdocstringへこの契約を明記済み（T18対応）。

### I-6. `surface_attributes` の重複保持（T9既存指摘の補強）

単独で実施すると再取込が二度手間になるため、**静的属性のスキーマ変更・再取込と同一バッチで**
実施する（T9のトリガーを更新）。

### I-7. ORS固有形式の domain・API 露出

`RouteSegment.surface_summary/surface_values` がdomain型→OpenAPI→フロント生成型まで貫通
（フロント未使用）。`domain/road.py` のID語彙（`GOOD_SURFACE_IDS`等）はdomainに居座る唯一の
外部API固有概念。**T21（評価一本化）が実現すれば丸ごと消えるため、単独対応はT16の決定後に
要否を判断する**（先にやると二度手間になりうる）。

### I-8. 残存する手動同期ペア2組（ドリフト検知テスト無し）

1. MVTレイヤー名: `vector_tile.ROAD_SURFACE_LAYER_NAME` ↔ `MapView.ROAD_TILE_SOURCE_LAYER`
2. タイル世代: `region_service._tile_cache_path` のv3 ↔ `regionApi.ROAD_SURFACE_TILE_VERSION`

属性追加のたびに世代を上げる運用になるためズレる機会が増える。`surface-tags.json` と同じ
生成物経由の照合をこの2組にも追加する（T19）。

### I-9. 本番構成が1箇所で書かれていない

`config.py` の既定は `road_graph_use_repository=False` だが本番は True＋フォールバック無効。
「正の構成」を知るには複数文書の突き合わせが必要。`.env.example` か architecture.md に
本番/開発プロファイルの値一覧を1表で明示する（T20、docs/設定例のみ）。

### I-10. Road Graph全量ロードのスケール壁

既知（C3/T12）。**DEFER維持が正しい**。自前ルーティング本格化の意思決定前に実装で
先回りしないこと。

---

## Keep List（変更しない方がよい設計）

- **エンジン切替そのもの**（設定切替型併存＋`engine`フィールド）。統一すべきは評価であって
  エンジンではない
- **RouteGenerator / LoopRoutingEngine のポート分割**と trace→距離フィルタ→evaluate の
  2段階契約＋性能回帰テスト
- **生OSM層/派生グラフの分離・split_at鮮度判定・決定論的ID採番**
- **`get_or_build_graph_with_attributes` の3経路**（複雑だが全分岐に実測根拠。単純化すると
  実測で潰した問題が再発する）
- **正準語彙のSQLバインド＋`surface-tags.json`生成照合**（新語彙もこの型で）
- **`scoring.yaml`（候補内相対）/`route_preference.yaml`（絶対）の分離**
- **フロントの宣言的定義群**（mapLayers / roadFilterAxes / routeStyleModes / legendFilter）
- **実測駆動の最適化すべて**（ST_AsMVT・`=ANY`チャンク・`asyncio.to_thread`・
  change_detection付きUPSERT。過剰最適化は1件も無かった）
- **`MapView.tsx`（751行）・`page.tsx`（492行）の現状維持**（T15の判断を支持）
- **`/api/routes/preview` の残置**
- **wind_scoreの意味差の管理方式**（意図的不整合の管理手本。今後の非対称にも同じ型を使う）
- **`MAX_CONCURRENT`系を共通化しないこと**（独立チューニング値）
- **`RoadGraphRepository`ファサードのフラット委譲メソッド群**（I-5をT18実施時に訂正。
  `GraphService`/`ElevationAttributeService`/`RegionService`とそのテストFakeが依存する
  正式なインターフェース契約であり、重複ではない。ネスト参照への書き換えは行わない）

---

## 変更コストシミュレーション（要約）

| Case | 変更 | 容易度 | 主因 |
|---|---|---|---|
| A | 道路属性追加（表示のみ） | 中 | backend 7〜9箇所＋再取込。増幅要因除去後は5〜6箇所 |
| B | 評価ロジック変更 | 易 | `difficulty.py`/`compute_edge_cost`/`route_preference.yaml`に局所化 |
| C | ルーティングエンジン変更 | 易 | `LoopRoutingEngine`実装＋DI分岐＋config（ポート分割の成果） |
| D | PostGIS構造変更 | 中〜難 | マイグレーション不在（I-3）が主因。T17で「中」へ |
| E | 地図表示変更 | 易 | 宣言的定義の編集のみ。MapView本体のみ追記になる |
| F | 外部API変更 | 易〜中 | 天候・標高・basemapは易。ORSのみsurface数値ID漏出（I-7）で中 |
| G | 新しい評価指標追加 | 難 | Case Aフルセット＋両エンジンsegments 2箇所＋ORS側は原理的に不可（I-1直撃） |

---

## 追加の設計原則（既存10箇条に加える。今回の調査で確定）

1. **新しい道路属性は既定経路のみで追加する**: 取込プロファイル → raw層の型付き列 →
   （評価するなら）属性・difficulty関数 → タイルプロパティ → フロント軸定義。
   DirectedEdge本体・フォールバック経路・その場しのぎの別テーブルには足さない
2. **スキーマ変更は必ずマイグレーションファイルで行う**（T17導入後）。`create_tables`への
   ALTER追記・バックフィルSQL追記を禁止する
3. **エンジン間で同名フィールドの意味を割らない**。片方で算出できない値は**最初からNone**を
   返し、部分的に意味の違う値で埋めない
4. **フォールバック経路に新機能を実装しない**。フォールバックは既存機能の維持のみを担い、
   削除条件を常に文書に残す
5. **タイルプロパティを変えたら世代ペアを同一コミットで上げる**。手動同期ペアの新設は
   ドリフト検知テストを同時に置けない限り禁止
6. **共通化の判断基準は「変更理由が同じか」だけ**（`ASSUMED_SPEED_KMH`は統一・
   `MAX_CONCURRENT`系は重複のまま、の既存判断を踏襲）
7. **RoadGraphRepositoryファサードは意図的なフラットインターフェース**（サービス層とテストの
   Fakeが依存する契約）。新しい属性メソッドは個別リポジトリへ実装したうえで、**同じ流儀で
   ファサードにもフラットな委譲メソッドを対称に追加する**（T18で訂正。当初「追加しない」と
   していたが誤りだった）
8. **全量ロード・全件転送を伴う設計判断は関東スケール試算をbenchmarks/に残してから**
9. **「何もしない」を明示的な判断として記録する**。DEFERにはトリガー条件を付けて
   improvement-plan.mdへ書き、トリガー未到達の項目を「ついで」に実装しない
10. **docs現状文書はコードと同一コミットで更新、経緯はdecisions/へ**（既存原則の再確認）
