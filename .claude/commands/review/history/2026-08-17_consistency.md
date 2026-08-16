# 設計・実装・テスト整合性レビュー（2026-08-17）

**実施日**: 2026-08-17
**対象**: T89〜T92（直近6コミット、`git log --oneline -10`基準）。対象コミット範囲
`25caee6`〜`49f9906`（HEAD）。作業ツリーには未コミット差分あり（後述、Finding F-4）。
**対象コミット（HEAD）**: `49f9906de748cfb6c2311afa2229f9494f7223a2`
**レビュー種別**: consistency（設計 ↔ 実装 ↔ テストの整合性）
**参照**: `.claude/commands/review/principles.md`・`context.md`。過去のconsistency専用history無し
（本ファイルが初回）。基盤構築以前の参照元は`docs/complexity-review-2026-08-16.md`
（F-1: architecture.md未追従の先例）。

## Executive Summary

T89〜T92のうちT90（交通ストレス区間別内訳API）・T92（交通ストレス判定精緻化）は
architecture.md・テスト・実装がいずれも高い水準で同期しており、過去に発生した
「差分は綺麗だが実は大きな欠落がある」パターン（complexity-review-2026-08-16のF-1）は
再発していない。一方、**T92がSQL側（MVT焼き込み用CASE式）の`traffic_stress`計算ロジックを
変更したにもかかわらず、路面タイルのキャッシュ世代（`ROAD_SURFACE_TILE_VERSION`）を
据え置いたままにしている**という実装内部の整合性バグを新たに検出した（F-1、P1）。
これは地図上の色表示（キャッシュ経由、古い値のまま）とT90で新設したクリック時の内訳API
（毎回DBから再計算、新しい値）の表示が食い違いうるという、T90の目的（「表示値と内訳の
一致」）そのものを損なう実害につながる。ログ方針の軽微な不徹底（F-2, P2）とdocsの
列挙漏れ（F-3, P3）も検出したが、いずれも実害は小さい。未チェックタスク（T91・T56）は
検証した範囲でチェック状態と実態が一致しており「隠れた完了」は見つからなかった。

## Findings

### [P1] T92のSQL変更が路面タイルキャッシュ世代に反映されておらず、地図表示とブレークダウンAPIの値が食い違いうる
- Problem: T92で`_ROAD_SURFACE_TILE_MVT_SQL`（MVTへ焼き込む`traffic_stress`のCASE式）の
  判定ロジックを変更した（secondary系のbase値4→3、shared_lane/share_busway補正、lanes<=1
  補正を追加）が、この値を含む路面タイルのキャッシュ世代`ROAD_SURFACE_TILE_VERSION`は
  `"7"`のまま据え置かれている。同じファイルの直前コメント（v2〜v7の変更履歴）が
  「焼き込み値が変わったら世代を上げる」運用を自ら示している（例: v3は
  「surface正準分類の拡充…でsurface_goodの値が変わった世代」として世代を上げている）
  にもかかわらず、T92はこの運用に従わなかった。
- Evidence:
  - `backend/app/domain/traffic.py:139-153`（`TRAFFIC_STRESS_BASE_BY_HIGHWAY`のsecondary
    4→3変更）、`backend/app/domain/traffic.py:304-335`（shared_lane/share_busway・
    lanes<=1補正の追加）。
  - `backend/app/infrastructure/road_graph_repository.py:198-199,235,250,269`
    （MVT側CASE式の同期変更、コメントに「改善計画T92」明記）。
  - `backend/app/services/region_service.py:93-111`（`ROAD_SURFACE_TILE_VERSION = "7"`、
    直前コメントがv2〜v7の変更履歴を列挙し「焼き込み値が変わったら世代を上げる」慣行を
    自ら示しているが、T92（v8になるべき変更）の記載が無い）。
  - `git show 49f9906 --stat`で確認: T92コミットは
    `backend/app/domain/traffic.py`・`road_graph_repository.py`・テスト2ファイル・
    `improvement-plan.md`・`mapLayers.ts`のみを変更しており、`region_service.py`は
    含まれない（tile version不変を確認）。
  - `backend/app/infrastructure/tile_cache.py`にTTL/自動失効の仕組みは無く
    （`get`/`set`/`clear_all`のみ）、`POST /api/basemap/refresh`（手動操作）でしか
    キャッシュはクリアされない（`docs/architecture.md:145`）。
  - `frontend/src/components/Map/MapView.tsx:864-865,1329`で`traffic_stress`
    プロパティ（キャッシュされたタイルの焼き込み値）がポップアップ主行の表示値・
    内訳ボタンの表示条件の両方に使われている一方、内訳ボタン押下後の値は
    `RegionService.get_traffic_stress_breakdown`（`region_service.py:264-284`）が
    `get_way_tags_by_osm_way_id`でDBから毎回再計算する新しい値を返す。
- Impact: T92以前にキャッシュ済みのタイル（同じz/x/yが再取得されない限り残り続ける）は、
  secondary系道路で古いtraffic_stress値（4のまま、shared_lane/lanes<=1補正も未反映）を
  表示し続ける。T90が解決したはずの「地図上の表示値とクリック時の内訳計算値の食い違い」
  （`improvement-plan.md`のT90節に記載された過去の不具合と同種の症状）が、キャッシュ経由で
  再発しうる。本番環境で既にウォームなキャッシュが存在する場合、ユーザーは同じ道路について
  「地図の色は4/4（赤）だが内訳を見ると3/4」という矛盾を目にする可能性がある（本番DBの
  実キャッシュ状態は本調査からは確認不能、Confidence: Highはコード上の事実、実害の有無は
  Low〜Medium）。
- Root Cause: T92の完了条件チェックリスト（`improvement-plan.md`のT92節）にタイル世代の
  対上げが項目として含まれておらず、レビュー・テストいずれでも機械的に検知されなかった
  （SQL⇔Python突き合わせテストはタイルをテスト内で都度新規生成するため、キャッシュ経由の
  陳腐化は原理的に検知対象外）。
- Recommendation: `ROAD_SURFACE_TILE_VERSION`をv8へ上げ、`regionApi.ts`側の対応定数・
  `region-tile-config.json`（生成物）を同時更新する。既存の対応するドリフト検知テスト
  （`regionApi.test.ts`）がv8への更新を強制するはずなので、実質的な追加コストは低い
  （T19と同型の変更）。本番デプロイ後は`POST /api/basemap/refresh`相当のキャッシュ
  クリアが必要になる（T89の背景にあった「migration適用漏れ」と同種の"コードは正しいが
  運用手順が抜ける"パターンのため、デプロイ手順書的なメモがあれば併記するとよい）。
- Scope: S（定数変更1箇所＋生成物再生成＋テスト確認、T19と同規模）
- Confidence: High（コード事実）。実運用への実害はMedium（本番キャッシュの実温まり具合は
  未確認）。
- 乖離の分類: **実装 ↔ 実装（自己整合性）**。`region_service.py`が自ら定めたバージョニング
  規約と、T92のSQL変更が守るべきだった運用の乖離。副次的に**設計意図（T90の目的）↔ 実装**
  の乖離でもある。

### [P2] `RegionService.get_traffic_stress_breakdown`がログ方針の確立済みパターン（log_external_call）から外れている
- Problem: 同じクラスの`get_road_surface_tile`/`get_poi_tile`はPostGIS読み取りを
  `log_external_call`で囲み、DB例外を捕捉して`fields["postgis"]="error"`＋
  `logger.warning`で常時WARNINGを出し、安全側（空タイル）へフォールバックする一貫した
  パターンを持つ。T90で新設した`get_traffic_stress_breakdown`はこのパターンを踏襲せず、
  `log_external_call`で囲まず、DB例外に対するtry/exceptも無い。
- Evidence: `backend/app/services/region_service.py:157-262`（`_tile_from_repository`・
  `_get_tile`が`log_external_call`＋WARNING＋グレースフルデグレードの型を確立）に対し、
  `backend/app/services/region_service.py:264-284`（`get_traffic_stress_breakdown`）は
  素の`await self._repository.get_way_tags_by_osm_way_id(osm_way_id)`のみ。
- Impact: DB例外発生時、`infrastructure/request_log.py:71-80`の
  `request_log_middleware`がスタックトレース付きERRORとして捕捉するため
  「エラーは常時出す」というlogging.mdの大原則自体には違反しない（実害は限定的）。
  ただし`/api/debug/stats`のカテゴリ別統計（呼び出し数・エラー数）にこのエンドポイントの
  DB呼び出しが計上されず、障害時に他のタイル系と同じ切り分け精度で運用調査できない。
- Root Cause: T90実装時、新設APIが「DB1行取得のみで重い処理ではない」ため、
  同クラスの既存の重いタイル生成メソッド向けパターンをそのまま踏襲する必要性が
  意識されなかったと推測される。
- Recommendation: `log_external_call("region:traffic-stress-breakdown", osm_way_id=osm_way_id)`
  で囲み、DB例外時は`fields["result"]="error"`を設定したうえで再送出するか、
  既存パターンに倣いWARNING＋Noneへフォールバックするかを設計判断する
  （Noneフォールバックの場合はレスポンス契約`TrafficStressBreakdown | None`と整合するため
  自然）。
- Scope: S
- Confidence: Medium（「ログ方針違反」とまでは言い切れず、既存コード内の局所的な
  一貫性の欠如という性質が強いため）
- 乖離の分類: **設計（docs/logging.mdの確立済みパターン・同クラス内の先例）↔ 実装**

### [P3] architecture.md §7の「対称メソッド」列挙にT90新設の`get_way_tags_by_osm_way_id`が含まれていない
- Problem: `docs/architecture.md`の§7「停止密度・交通ストレス・自転車インフラ・交差点密度」
  節末尾に`AttributeRepository`の対称メソッド一覧（`get_stop_poi_counts`/
  `get_nearest_stop_poi_counts`、`get_way_tags`/`get_nearest_way_tags`、
  `get_intersection_counts`/`get_nearest_intersection_counts`）が列挙されているが、
  T90で新設した`get_way_tags_by_osm_way_id`（osm_way_id完全一致1行取得）はこの列挙に
  含まれていない。
- Evidence: `docs/architecture.md:508-510,526`にAPI・用途としては説明済み
  （「欠落」ではない）が、`docs/architecture.md`の§7末尾（`poi-tiles`で提供、の直前段落）の
  対称メソッド列挙には現れない。実装は`backend/app/infrastructure/road_graph_repository.py:1451,1719-1720`
  （`AttributeRepository`本体＋ファサード対称委譲）。
  `get_way_tags_by_osm_way_id`は`get_nearest_*`と対になる設計ではない（完全一致1件取得の
  独立系統）ため、既存の「get_*/get_nearest_*」対称表には元々馴染まない性質がある点は
  酌量点。
  検索範囲: `grep -n "get_way_tags_by_osm_way_id" docs/architecture.md` はヒット無し。
- Impact: 軽微。API仕様・タイル世代・目的は既に文書化されているため、実装内容の
  理解に支障は無い。
- Recommendation: 次回architecture.md更新時に、対称メソッド列挙の後ろへ
  「`get_way_tags_by_osm_way_id`（T90、osm_way_id完全一致1行取得、区間別内訳API専用）」
  を1行追記する。
- Scope: S（文言追記のみ）
- Confidence: High
- 乖離の分類: **docs ↔ 実装**（軽微な列挙漏れ、記述自体の欠落ではない）

### [P3/情報] T87（2回目実装）が作業ツリーで完了・improvement-plan.mdも[x]化済みだが未コミット
- Problem: `git status`時点で`docs/improvement-plan.md`のT87チェック状態
  （`- [ ]` → `- [x]`＋実機確認2回目の記録）と、対応する実装
  （`MapView.tsx`の`clearStaleTrackedSourceErrors`等、新規`MapView.dataStatus.test.ts`）が
  いずれも作業ツリーに存在するが、コミットされていない（`git diff --stat`で
  8ファイル637行の差分、`MapView.dataStatus.test.ts`はuntracked）。
- Evidence: 本レビュー開始時の`git status --short`
  （`M docs/improvement-plan.md`, `M frontend/src/components/Map/MapView.tsx`ほか、
  `?? frontend/src/components/Map/MapView.dataStatus.test.ts`）。
  docsとコードの内容自体は整合している（docs↔実装の乖離ではない）。
- Impact: 実害なし（docsと実装は作業ツリー内で一致）。プロジェクト規約
  「1タスク=1コミット」（context.md）に対し、コミットが実装完了に追いついていない状態。
- Recommendation: レビューとは別に、T87（2回目）の変更をコミットする
  （本レビューはコード・docsを変更しない方針のため対応せず、ユーザー側の作業として
  申し送る）。
- Scope: S
- Confidence: High
- 乖離の分類: 該当なし（docs↔実装は一致。運用上の「コミット未実施」のみ）

## KEEP（変更しない方がよい設計・確認して問題なしだった箇所）

- **T90/T92の完了条件（テスト件数）の裏取り**: `improvement-plan.md`のT90節
  （「backend 688件…新規9件」）・T92節（「backend 694件…新規11件」）は、実際の
  テストファイルと対応関係が確認できた。`test_traffic.py`に`test_secondary_base_is_3`
  （行115）・`test_cycleway_shared_lane_reduces_by_1`（行140）・
  `test_cycleway_share_busway_reduces_by_1`（行144）・`test_single_lane_reduces_by_1`
  （行156）、`test_road_graph_repository.py`に`test_get_way_tags_by_osm_way_id_*`
  （行578, 594）が存在。`.venv/Scripts/python.exe -m pytest --collect-only`で
  現在694件収集を実測（T92の主張と一致）。`test_traffic.py`＋
  `test_road_graph_repository.py`を実行し159件全passを確認（DB統合テストがskipされず
  実際に実行されていることも確認、PostGIS接続は生きている）。
- **SQL⇔Python二重実装ドリフト検知の新属性追従**: T92で追加されたshared_lane/
  share_busway・lanes<=1の2補正は、`test_road_graph_repository.py:1135-1138`の
  fixture（`("unclassified", {"lanes": "1"})`・`("tertiary_link", {"cycleway": "shared_lane"})`）
  として整合性テストに追加済みで機能している。
- **路面タイル世代の同期（フロント⇔バックエンド）**: `region_service.py:111`
  （`ROAD_SURFACE_TILE_VERSION = "7"`）、`regionApi.ts:25`（同`"7"`）、
  `region-tile-config.json:4`（`"tile_version": "7"`）が三者とも一致。
  `regionApi.test.ts:45-48`のドリフト検知テストが実際に生成物と実装値を突き合わせる
  設計で機能している（Finding F-1で指摘した問題は「世代を上げ忘れた」ことであり、
  同期機構自体は正しく動作している）。
- **T90のarchitecture.md反映**: 新規API・`osm_way_id`プロパティの意味・タイル世代v7への
  変更理由が`docs/architecture.md:508-510,526,815`に具体的に反映されており、
  過去に発生した「完了マーク済みタスクの主要変更がdocsへ全く反映されない」パターン
  （complexity-review-2026-08-16のF-1）は再発していない。
- **未チェックタスクの実態（T91・T56）**: T91は`MapView.tsx`が作業ツリーで1,677行
  （HEAD時点1,410行、T91起票時点1,378行からさらに増加）に達しており、チェックが
  漏れているのではなく、閾値超過が悪化しながら真に未着手のまま放置されている状態を
  確認した（隠れた完了ではない）。T56も本文に変更が無く、真に未検証のまま。
- **openapi生成型の追従**: `frontend/src/types/generated/api.d.ts:157,512-518,814`に
  `/api/region/traffic-stress-breakdown`パス・`TrafficStressBreakdown`スキーマが
  存在し、T90のAPI追加に追従済み。
- **レート制限のログ方針準拠**: 新設エンドポイント（`region.py:132`）も
  `_check_tile_rate_limit`→`record_rate_limit_rejection`を経由しており、429時の
  WARNING・統計計上は他のタイル系エンドポイントと同じ経路で確立済み。

## REMOVE
該当なし。

## SIMPLIFY
該当なし（今回の調査範囲では過剰な複雑さは見つからなかった）。

## REFACTOR
該当なし（F-2のログ方針統一は「バグ修正」寄りのためFindingsに計上、REFACTOR分類はしない）。

## EXTEND
該当なし。

## DEFER
該当なし。

## Regression / Previous Findings

- complexity-review-2026-08-16のF-1（architecture.md未追従、静的道路属性P0/P1が
  丸ごと未反映だった問題）の再発は、T89〜T92の範囲では確認されなかった
  （T90はむしろ模範的に反映されている）。
- 統合レビューF-3（T91、MapView.tsx閾値監視の再設定未着手）は今回も未解消のまま
  （improvement-plan.mdのT91が`- [ ]`のまま、状況は悪化）。新規の指摘ではなく
  既存T91への裏付け証跡の追加として扱う。

## Overall Judgment

T89〜T92単体の「設計→実装→テスト」の一本道は概ね健全（特にT90/T92は模範的）。
最も重要な指摘は、T92のSQL変更がタイルキャッシュのバージョニング規約という
プロジェクト自身の運用ルールに違反しており、T90が解決したはずの
「表示とクリック内訳の不一致」をキャッシュ経由で再発させうる実装内部の整合性バグ
（F-1, P1）。次点でログ方針の局所的な不徹底（F-2, P2）。いずれも修正規模は小さい
（S）。architecture.mdの追従状況は良好で、過去に発生した検出漏れパターンは
再発していない。
