# codereview レビュー（2026-09-03）

## 対象

- 対象コミット: `7fbf04d`（T531完了コミット）までのT531一連（起点`5b408c4`〔T531着手〕、
  `git diff 5b408c4...HEAD`。並行セッションの`c6252f1`〔MapView.tsxのピン位置補正〕・
  OpenAPI生成物・docsは正しさ角度の対象外、docs/modulesは規約角度のみ対象）
- 差分範囲: T531「周回ルート生成を8方位固定からフロンティア方式へ転換」実装
  （backend 31ファイル約2,100行追加/1,100行削除: `domain/routing.py`・
  `services/road_graph_engine.py`・`services/route_generator.py`・`api/routers/routes.py`・
  `infrastructure/search_graph_cache.py`・benchmarks・tests、frontend `RouteForm.tsx`・
  `page.tsx`・テスト）
- レビュー種別: `codereview`（`/code-review`、high effort、3+5角度×6候補→1票検証→上位10件）
- 実施方法: 8つの独立した観点別Agent（correctness×3・reuse・simplification・efficiency・
  altitude・conventions、いずれも読み取り専用のExplore）を並行実行し、収集した候補
  約40件を重複排除のうえ、上位候補は実コードの直接確認（テスト実行・grep・算術）で裏取りした。
- **対応状況（2026-09-03追記）**: 上位10件と「やる価値がある」群10件を
  [T557](../../../docs/tasks/T557.md)として起票（未着手）。

## Executive Summary

正しさ角度3つとaltitude角度が独立に同じ2箇所へ収束した: (1) 目的地モードでフロントが
未検証の`max_routes`を常時送信する（RouteFormの早期returnがバリデーションを飛ばす）、
(2) リング定義`[(目標−許容)/2.0, (目標+許容)/2.3]`が「許容≥目標」で下限が負になり、
フロント既定の許容5km・短距離指定で目標の6割程度の周回が上位に来る。どちらも実装内容
そのものではなく「新しい入力の組合せ」（モード切替後のstate残り、短距離＋固定許容）に
対する境界の見落としで、テストは正常系の周回モード・20〜30kmしか固定していない。

構造面では、折返し点ランキングの物差し（コスト式の逆算）と最終ソートの物差し
（`overall_difficulty`、NaN除外）が「全軸データ欠損Edge」の扱いで食い違い、T552
（欠損Edgeのコスト補完）の対象と同根の問題がランキング側にも存在する。docs/modules
（パッケージE委任）は、その後のリング再定義コミット（`ce5b186`）に追従しておらず、
同一コミット同期ルールの取りこぼしが起きた（委任→本体で仕様変更→docs未追従という
分担の継ぎ目の問題）。

## Findings（上位10件、`ReportFindings`で報告済み）

### [P1] 目的地モードで未検証の`max_routes`を常時送信し422になる（`frontend/src/app/page.tsx:1402`、CONFIRMED）

- Problem: `RouteForm.handleSubmit`は目的地モードで距離・候補件数の検証を飛ばし
  `onGenerate(0)`するが、`handleGenerate`はモードに関わらず`max_routes: Number(maxRoutesInput)`
  を送る。空文字（→0）や16以上がbackendの`Field(ge=1, le=15)`に当たる。
- Impact: 周回モードで候補数を空にしてから目的地モードで生成すると422。画面に無い入力欄が
  原因の汎用エラーだけが出る。
- Fix: 目的地モードでは`max_routes`を送らない（backend既定8）か、送信前に検証する。

### [P1] 許容≥目標距離でリング下限が負になり極端に短い周回が上位になる（`backend/app/services/road_graph_engine.py:736`、CONFIRMED）

- Problem: `ring_lower_m=(目標−許容)/2.0`が負でも反転ガード（`lower > upper`）が働かず、
  `ring_center_m`が目標の半分より大幅に手前へ寄る。フロントは許容5km固定。
- Impact: 距離1km・許容5km→リング[−2.0km, 2.6km]・中心0.3km。難易度同点なら往路300mの
  Nodeが上位を独占し周回0.6kmが返る（許容5kmで距離フィルタも通過）。狭い許容
  （`tol < 0.07×目標`）での反転フォールバック（/2.0の対称化）も比の上側を無視して候補0件に
  倒れやすい。
- Fix: 下限を0でクランプし、中心は`目標/中央比`（例: 2.1）で決める。反転時のフォールバックも
  同じ中心を使う。

### [P2] 全軸データ欠損Edgeが往路ランキングで難易度0（最良）扱い（`road_graph_engine.py:765`、CONFIRMED）

- Problem: `(cost/len−1)/P×100`の逆算はNaN compositeに倍率1.0を当てる`compose`の規約を
  そのまま受け、`np.where(np.isfinite, …, 0.0)`も同方向。`overall_difficulty`はNaN区間を
  除外するため物差しが食い違う。
- Fix: T552（コスト補完）と併せ、ランキング側で「NaN区間の距離割合」を別途扱う。

### [P2] 再split後にキャッシュ済み`lazy_graph`と現在の`graph`がずれるとKeyError（`road_graph_engine.py:578`、PLAUSIBLE）

- Problem: `origin_index=node_id_to_index[origin_node]`・`graph.edges[lazy_graph.edge_ids[i]]`
  が無ガード。タイル集合キーのキャッシュに無効化フックが無い。
- Impact: prepareでは500、復路探索では`except Exception`が候補単位で握りつぶし
  「除外設定をご確認ください」という誤った文言でHTTP 200。
- Fix: `.get()`で欠損を検知したらタイル集合のキャッシュを破棄して再構築、または
  `save_graph`後に`search_graph_cache`を無効化。

### [P2] docs/modulesのリング定義・タイブレーク記述が実装と乖離、経緯記述の混入（`docs/modules/backend/routing-engine.md:177,183,215`、CONFIRMED）

- Problem: 「目標距離/2 ± 許容/2」「目標の半分に近い順」は`ce5b186`以前の設計。215行の
  「改善計画T531で候補ごとの取得から統合」は記載粒度ルールが禁止する経緯記述。
- Fix: 現状（比2.0/2.3・リング中心）へ書き換え、経緯文を削る。

### [P2] `SearchGraphStatics`×64エントリで最大約1.2GB、`masks`が毎回22MB×2（`backend/app/infrastructure/search_graph_cache.py:51`、CONFIRMED）

- Fix: `entry_keys`を都度生成へ、int32化（19MB→約7MB/エントリ）、staticsの上限を分離。
  `masks`はuint64ビットマスク1本で2パス共有。

### [P2] `route-180`のassertがid再採番後は常に真（`backend/tests/test_road_graph_engine.py:369`、CONFIRMED）

- Fix: `compass_label(180)`が`direction_label`に無いことを検証する形へ。

### [P2] 間引きが往路のみ比較のため復路が収束するとほぼ同一の周回が並ぶ（`road_graph_engine.py:803`、PLAUSIBLE）

- Fix: T553の周回単位重複率チェックを「復路同士・往路と他候補の復路」も含む形へ広げる。

### [P2] `_origin_estimate_fn`が`_build_estimate_cost_fn`を複製、`return_edge_indices`が`path_to_edge_ids_lazy`と二重走査（`road_graph_engine.py:1196,891`、CONFIRMED）

- Fix: `_build_estimate_cost_fn`の結果を`context.origin_estimate`へ保持。
  `path_to_edge_indices_lazy`を切り出し`path_to_edge_ids_lazy`をそのラッパにする。

### [P2] 毎リクエストの全Edge/全Node規模の不要なPythonオブジェクト生成（`road_graph_engine.py:436`、CONFIRMED）

- Problem: `cost_array.tolist()`で56万float新規生成、`far_enough`用に全Node座標をtolist、
  `difficulty_by_node`をリング全Node分のdictで構築、`outbound_cache`が最大4,000件の往路listを保持。
- Fix: `cost_list`は従来の内包、座標・difficultyは`ranked`に絞る、`tree_path_edge_indices`は
  int32配列を返す。

## 上位10件以外の候補（「やる価値がある」群、T557へ含める）

P3相当10件: `_accumulate_tree_lengths`の到達判定を`np.isfinite(cost)`へ／`cost_array`と
`cost_list`の二重保持解消／未使用フィールド（`_TurnaroundData.node_index`・
`LoopTurnaround.outbound_distance_km`/`outbound_difficulty`）と`_predecessor_list`遅延キャッシュの
撤去／`select_diverse_by_overlap`の出力引数（`initial_selected`/`rejected_by_overlap`）を閾値列へ／
`overlap_ratio`（DEBUGログ専用）と間引き本体の重複率定義の一本化／`preview_segment`での
`SearchGraphStatics`構築の回避／`search_graph_cache.py`のLRU 3組の共通化／
`bench_t531`と`bench_t536`の配線重複とsplitガードの非対称／`bench_nearest_node.py`の
旧8方位前提コメント／`test_routing.py`の`_length_array`が本番の`build_search_graph_statics`を再実装。

設計判断として見送り（別タスク向き、起票せず記録のみ）: 探索パラメータ（retrace倍率・
間引き閾値）のリクエストパラメータ化、周回/往路比の自己較正、difficulty同点判定
（小数1桁）の共通キー関数化、候補id・順位の権威の一元化（T551で`kind`/`rank`フィールドとして
扱う）、目的地モードでの`max_routes`エコー、プール上限40と3倍則の不整合、
`routing-engine.md`の`select_loop_turnarounds`節の冗長さ。

不採用: 共有`cost_list`の一時書き換えをEdgeごとの`dict.get`オーバーレイへ置き換える案
（Pythonコールバックが探索中に戻りT536の高速化が失われる）。`benchmarks/`の索引未登録
（既存慣行で対象外）。

## Regression

- 前回（2026-09-01、T518差分）との関係: 対象が異なるため直接比較不可。前回のP1×2は
  いずれもT524で修正済み・再発なし。今回のP1×2は新規（T531で新設した入力経路）。

## スコアサマリ

| 項目 | 値 |
|---|---|
| P0 | 0 |
| P1 | 2 |
| P2 | 8 |
| P3 | 10 |
| 総合スコア | 46（`100 − (2×10 + 8×3 + 10×1)`） |
| 前回差分 | −5（対象差分が異なる参考値。P1件数は同数、P2は+2、P3は−1） |
