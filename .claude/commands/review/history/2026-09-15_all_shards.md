# 統合レビュー（2026-09-15）シャード別の生出力

[2026-09-15_all.md](2026-09-15_all.md) のPhase 3（overall）・Phase 5（consistency）で、
ドメインシャードごとに1つのAgentへ両レンズを渡して得た**統合前の一次出力**。重複・
矛盾・誤検知を含む。統合後のFindingsは結果ファイル側を正とし、ここは「起票したタスクが
対象を指せるようにする」ための記録として残す（principles.md「集約」項）。

対象コミット: `4a2cb02a`（ベースライン `e5be72d2` = 2026-09-13統合レビュー）

シャード:

- [S1. backend/app/domain](#s1-backendappdomain)（13ファイル）
- [S2. backend/app/infrastructure](#s2-backendappinfrastructure)（13ファイル）
- [S3. backend/app/services](#s3-backendappservices)（9ファイル）
- [S4. backend/app/api + batch + config](#s4-backendappapi--batch--config)（22ファイル）
- [S5. frontend/src/components/Map](#s5-frontendsrccomponentsmap)（30ファイル）
- [S6. frontend/src/components（Map以外）](#s6-frontendsrccomponentsmap以外)（34ファイル）
- [S7. frontend/src/app・hooks・lib・services・types](#s7-frontendsrcapphookslibservicestypes)（27ファイル）

---

## S1. backend/app/domain

### overall

**O-1** `backend/app/domain/routing.py:46-47` / doc-drift / **P2**
- summary: `LazyRoadGraph`のクラスdocstringが「並行Edgeはコスト最小の1本へ解消済み」と述べるが、6行下の`build_lazy_road_graph`は「edge_idの昇順で先頭を採用する——コストはリクエストごとに変わるため、トポロジを組む時点では決められない」と正反対を述べる。
- evidence: `routing.py:46-47`（クラスdocstring）vs `routing.py:64-65`（関数docstring）。T819（`c60f2352`）が`edge_cost_by_id`引数とcost最小の枝を撤去した際、関数側だけ書き換えクラス側が残った。実装（`routing.py:72-81`）は`if pair not in best_by_pair`のみで、コストを一切見ない。
- failure_scenario: 並行Edgeの選ばれ方を疑って`LazyRoadGraph`を読んだ人が「コスト最小が採られる」と信じ、T537が意図的に受け入れた既知の制約（並行Edgeの片方だけが0次フィルタで除外されると`(u,v)`ペアごと到達不能になりうる）を「起こりえない」と誤って除外する。
- recommendation: クラスdocstringを「edge_idの昇順で1本へ解消済み（コストは持たない）」へ揃える。

**O-2** `backend/app/domain/evaluation.py:13, :829`, `axis_templates.py:17` / dead-reference / **P2**
- summary: `compute_edge_costs_bulk`は本番の呼び出し元が1つも無い回帰テストオラクルなのに、3箇所が「bbox全体の一括評価を担う本番経路」として名指しする。うち1箇所は自分自身を「専用」の呼び出し元として指す自己参照になっている。
- evidence: `grep -rn "compute_edge_costs_bulk(" backend/ | grep -v tests` の結果は定義行のみ。`road_graph_engine.py:703-706`が「bbox全体の一括評価（compute_edge_costs_bulk）は本エンジンから不要…回帰テストオラクルとして残る」と明記。にもかかわらず `evaluation.py:829`＝「算出する（bbox全体を一括評価する`compute_edge_costs_bulk`専用）」、`evaluation.py:13`の表＝「| ベクトル（Edge群） | `compute_edge_costs_bulk` | bbox全体の一括評価 |」、`axis_templates.py:17`＝「ベクトル化された一括経路（`evaluate_axis_array`、一括評価の`compute_edge_costs_bulk`が使う）」。`evaluate_axis_array`の実際の本番消費者は`evaluation.py:592`（`_evaluate_axes_bulk`）と`dynamic_materials.py:137`。
- failure_scenario: T822が死んだ参照`evaluation_service.evaluate_graph`を、実在するが本番から呼ばれない名前へ置き換えたことで生じた。ベクトル化経路の性能を調べる人が`compute_edge_costs_bulk`を計測・最適化しても本番の探索コスト合成には一切効かない。
- recommendation: 3箇所とも「スカラー版との一致を検証する回帰テストオラクル」と書く。`axis_templates.py:17`は実消費者`_evaluate_axes_bulk`／`build_static_edge_score_matrix`を指す。

**O-3** `backend/app/domain/dynamic_way_values.py:94-125` / 暗黙の結合 / **P2**
- summary: `display_thresholds_override`が「材料スケール」か「難易度スケール」かを、宣言ではなく`derive_ramp_inputs(definition) is not None`という**派生結果**が決める。材料に`tile_property`を1つ足すだけで、その材料を使う全軸の既存overrideの意味が黙って反転する。
- evidence: `dynamic_way_values.py:117-118`（`if derive_ramp_inputs(definition) is None: return list(override)`）。`wind`は`wind_drag_ratio`が`tile_property=None`（`material_catalog.py:137-139`）のためramp導出が失敗し、override `[20,40,60,80]`が難易度としてそのまま通る（生成物`axis-catalog.json`の`map_value_thresholds`で確認）。一方`openness`はramp導出が成功するため`[-85,-70,-50,-30]`→`[22.5,41.7,65.0,88.3]`へ写される。
- failure_scenario: `tile_property`を材料へ足すだけで軸が地図レンズを得る運用（設計原則8の1本道、T692）に従って`wind_drag_ratio`等へタイルプロパティを付けると、`derive_ramp_inputs`が成功に転じ、windの`[20,40,60,80]`が折れ線で写されて全て100へ飽和→重複畳み込みで`[100.0]`の1本になる。凡例5段が2段へ潰れ、例外もログも出ない。
- recommendation: overrideのスケールを`AxisDefinition`側の宣言（例: `display_thresholds_scale: "material" | "score"`）で持つか、軸スタジオの書き込み時に現在のスケールを固定して保存する。

**O-4** `backend/app/domain/dynamic_way_values.py:119-125` / correctness / **P2**
- summary: `map_value_thresholds`が飽和域の境界を畳むため、返す本数が`display_thresholds_override`より少なくなりうる。対になる`display_band_labels_override`の本数は畳まれないため、軸スタジオで書いた体感ラベルが黙って捨てられる。
- evidence: `dynamic_way_values.py:123`（`if not mapped or score > mapped[-1]`）。テスト`test_dynamic_way_values.py:123-126`が4本→2本になる例を固定している。フロント側は`axisLayers.ts:496`が`axis.bandLabelsOverride.length === bandCount`のときだけラベルを使い、不一致なら数値レンジへフォールバックする。
- failure_scenario: 軸スタジオで境界を折れ線の飽和域へ寄せると、閾値が畳まれてラベル5件と段階3件が食い違い、凡例が体感ラベルから無味の数値レンジへ入れ替わる。エラーは出ず、設定した本人にも理由が分からない。
- recommendation: 畳んだときにラベルも同じ規則で畳んで返すか、畳んだ事実を軸カタログへ出して読む側が判断できるようにする。

**O-5** `backend/app/domain/dynamic_way_values.py:122` / duplication / **P3**
- summary: しきい値の写像が`evaluate_breakpoint_linear`を直接呼び、`evaluate_axis_scalar`が上に重ねる`priority_overrides`を通らない。地図が実際に塗る値と写し方が食い違う。
- evidence: `dynamic_way_values.py:122` vs `axis_definitions.py:772-778`。現在のスナップショットは全軸`priority_overrides: []`のため実害は無い（実測）。
- recommendation: 写像を`evaluate_axis_scalar`経由にする。

**O-6** `backend/app/domain/axis_display.py:34, 157, 176, 446`（および同`:16`）/ count-narrative / **P3**
- summary: 「car_stressが5つの内部軸を参照する」という件数がコメント4箇所に残っている。軸構成はDBが正本で軸スタジオから増減できるため、内部軸が1本増えた瞬間に4箇所が同時に嘘になる。
- evidence: T822は同ファイルの`primary_attribute_ids_for`（`:500`）だけを「car_stressの内部軸6つ」→「car_stressが参照する内部軸」へ直しており、**直された1件は「6つ」・残る4件は「5つ」で既に互いに矛盾していた**（スナップショット実測では現在5）。
- recommendation: T824（数え上げ廃止）の対象をコードコメントへも広げる。同一ファイル内は一括で。

**O-7** `backend/app/domain/axis_templates.py:76-78` / doc-drift / **P3**
- summary: `round1_array`のdocstringが「`domain/difficulty.py`の配列版4関数・`domain/evaluation.py: compute_edge_costs_bulk`の最終丸めの両方で使う共通実装」と述べるが、両方とも事実でない。
- evidence: `grep -rn "round1_array" backend/app` の結果は`axis_templates.py`（定義）と`evaluation.py:52,733,779,808`のみ。`difficulty.py`は`round1_array`をimportしておらず、配列版の関数も`distance_weighted_difficulty_array`の1本だけ。丸めを呼ぶのは`compose_costs_from_axis_matrix`。
- recommendation: 実際の使用箇所を指す形へ書き直す。

**O-8** `backend/app/domain/registry_defaults.py:67-75`（＋`scripts/review_checks.py:1487, 1500-1516`）/ dead-reference・検知器の盲点 / **P2**
- summary: 一次属性`cycleway`を排他チェックから外す`shared=True`の根拠コメントが、T353で廃止済みの内部軸`car_stress_bicycle_infra_adjustment`を「現に参照している」と述べている。撤去済み軸を名指しするコメントを止めるはずの`removed_axis_mentions`検知器は、構造上これを検出できない。
- evidence: `registry_defaults.py:68-73`。当該軸はスナップショットにもコードにも存在しない。`python scripts/review_checks.py docs` 全件実行は「現在の軸定義に無いaxis_idを現行として名指し: 0件」を返す。理由は`removed_axis_ids`（`review_checks.py:1500-1516`）が母集団を`AXIS_ID_USE_RE = axis_id\s*[:=]\s*"…"`（`:1487`）で集めており、**コードから完全に消えた軸idは母集団に入らない**ため。加えて当該コメントは識別子が2行に折り返されており、行単位の正規表現でも当たらない。
- failure_scenario: 実際に参照しているのは`bicycle_infra_quality`1軸だけになったのに、コメントは「2軸が共有するから排他チェックの例外」と読める。さらに検知器は「撤去済み軸の名指しは機械が止める」という前提を与えながら、**通常の撤去（コードから完全に消す）でだけ機能しない**。
- recommendation: コメントを現状へ書き直す。検知器は母集団を現行ソースの`axis_id="…"`から導くのをやめ、軸スナップショットの履歴か、複数行を連結したテキストに対する照合へ変える。

### consistency

**C-1** `docs/modules/backend/evaluation-scoring.md:212-213` / doc-drift（前回P1の未解消＋悪化）/ **P1**
- summary: 「並行Edgeはコストが判明済みのため`domain/routing.py: build_lazy_road_graph`が『cost最小を採用』する」という記述が残る。前回統合レビュー（2026-09-13）でP1として指摘済みで、その後T819がcost最小の枝そのものを撤去したため、いまや**存在しないコードを説明している**。
- evidence: `docs/modules/backend/evaluation-scoring.md:211-213`。同じ事実を`docs/modules/backend/routing-engine.md:603-606`は「edge_idの昇順で先頭を採用する決定的な選択で解消する」と正しく書いており、モジュール文書2本が食い違う。指摘の初出は`history/2026-09-13_all_shards.md:40`。T819は検知器が拾った死んだ参照4件を直したが、この記述は生きた識別子（`build_lazy_road_graph`）を名指しするため検知器に掛からず残った。T822でも対象外。
- recommendation: routing-engine.mdの記述へ揃える。「生きた識別子を名指ししながら挙動だけが古い記述」は現行の検知器2種の射程外。

**C-2** `backend/app/domain/difficulty.py:70-86`（＋`axis_inspector.py:39-43`、`tests/test_evaluation.py:646-666`）/ 契約と実装の不一致・test-gap / **P2**
- summary: `composite_contributions`のdocstringが「**合計が合成スコアと一致する**」と太字で宣言するが、各寄与度を個別に`round(...,1)`するため一致しない。それを検証するはずのテストは`abs=0.15`の許容で書かれており、この関数が防ぐために作られた「内訳の合計が結論と合わない表示」をそのまま許している。
- evidence: `difficulty.py:84`（`round(score * weight / weight_sum, 1)`）vs `difficulty.py:67`（合成側は`round(total, 1)`）。実測: 重み等しい6軸がすべてスコア10.0のとき合成10.0に対し内訳の和10.2、7軸で9.8、3軸すべて50.0で合成50.0に対し和50.1。テストは`test_evaluation.py:666`が`abs=0.15`。
- failure_scenario: 区間インスペクタで有効な軸が5〜6本あるとき、寄与度の列を足しても合成値にならない（最大±0.25〜0.3）。テストの許容0.15は理論最大0.25に届くため、軸を1本足すだけで**壊れたのか許容内なのか区別できないまま落ちる**不安定テストにもなる。
- recommendation: 丸め前で分解し最後に最大剰余法等で合計を一致させるか、丸めを表示側へ寄せる。テストは厳密一致で書き直す。

**C-3** `backend/app/batch/precompute_way_divided_carriageway.py:1, 8-9`, `road_graph_repository.py:340` / doc-drift / **P2**
- summary: T865が「`way_geometry`へ列を足す形を一度書いたが取り消した」と明記しているのに、バッチのdocstringとタイルSQLのコメントが判定の置き場を`way_geometry.divided_carriageway`と述べ続けている。実体は専用テーブル`way_divided_carriageway.divided`。
- evidence: 実装は`road_graph_models.py:341`（`__tablename__ = "way_divided_carriageway"`）、`road_graph_repository.py:410`（`LEFT JOIN way_divided_carriageway wdc`）、`derived_data_freshness.py:86`。`docs/tasks/T865.md`が撤回の理由（系譜列が行単位で1組しかなく蛇行側の系譜を上書きする）を記録している。
- failure_scenario: `:8-9`を信じて「両バッチが同じ行を触る」前提で`way_geometry`へ次の列を足す判断をする——それはT865が測って取り消した設計そのもの。
- recommendation: 3箇所を訂正し、`:8-9`の段落を現在の理由へ書き換える。

**C-4** `backend/app/domain/osm_adapter.py:67-70` / 完了扱いタスクの未実施段階 / **P2**
- summary: T865が`carriageway`を`ALLOWED_WAY_TAGS`へ追加し、判定条件1を稼働中のものとして記述しているが、取込時フィルタである以上、**この変更より前に取り込まれたDBには当該タグが1件も存在しない**。T865は`[x]`で、この残りが`- [ ]`行として起票されていない。
- evidence: `osm_adapter.py:91-94`（`_filter_allowed_tags`）。同じ依存を持つT654は`improvement-plan.md:1019`に`- [ ]`＋トリガーとして残っている。`docs/tasks/T865.md`の「残る限界」節にはこの制約が無い。
- recommendation: T865へ追記するか別の`- [ ]`として起票。T654のトリガー行へ`carriageway`の反映を含める。

**C-5** `backend/tests/realistic_axis_fixtures.py:1`, `conftest.py:82`, `test_evaluation.py:641-642` / count-narrative / **P3**
- summary: 同じフィクスチャの軸数を「13軸」「14軸」と別々に述べ、実際は14（うち公開9）。公開軸数を述べる箇所は「全8軸」のまま。
- recommendation: 3箇所とも件数を落とす（T824の方針をテストコードへも適用）。

**C-6** `backend/app/domain/osm_adapter.py:68` / 実測値のコード直書き / **P3**
- summary: 許可リストのコメントが「関東全域で117件しか無く」という実測件数を持つ。次回のPBF更新で外れる数字。
- recommendation: 性質だけを残し、件数はT865.mdへ委ねる。

**補足（起票不要と判断）**: `raw_value_total_unit`は現在すべての公開軸で`null`だが、T760が「本番の公開軸で総量が出るものは無い」と明記済み。`review_checks.py docs`は「違反なし」だが、O-8のとおり`removed_axis_mentions`の0件は「無い」の証拠にならない。

---

## S2. backend/app/infrastructure

### overall

**O-1** `backend/app/infrastructure/search_graph_cache.py:18-20`（＋`services/derived_data_revision_service.py:54-57`）/ 無効化の取り残し / **P2**
- summary: T847で材料キャッシュの無効化が「プロセス寿命のみ」から「DB世代との突き合わせ」へ強化されたが、材料から派生する `search_graph_cache` だけが取り残され、材料を捨てたときに一緒に捨てられない。
- evidence: `cache_generation.sync_with_revision`のdocstringは「捨てたときTrueを返す（**呼び出し側が、そこから作られる他のキャッシュも一緒に捨てるため**）」と契約を述べる。受ける`ensure_caches_match_db`は`tile_score_matrix_cache.clear()`だけを呼ぶ。`_routable_index_cache`のキーは`(TileSet, hard_filters, max_average_grade_percent)`で、その値は`StaticEdgeScoreMatrix`の`gradient_percent`列に依存する。`search_graph_cache.py:18-20`のdocstringは「無効化方針は`graph_material_cache`と同じ」と書くが、`graph_material_cache`はもうその方針ではない。復旧経路`_ensure_lazy_graph_consistent`はedge_id集合のずれしか検出しない。
- failure_scenario: `refresh_derived.py`再実行で`derived_data_meta.revision`が進み材料は作り直されるが、`max_average_grade_percent`指定で温めた`_routable_index_cache`のエントリは残り、**旧勾配で計算したroutable node集合**が折返し点候補の選定に使われ続ける。警告も出ない。
- recommendation: `ensure_caches_match_db`から`search_graph_cache.clear()`も呼ぶ。docstringの引用をやめて自分の方針を直接述べる。**わざとrevisionを進めて空になることを確認してから完了扱いにすること。**

**O-2** `backend/app/infrastructure/material_coverage.py:231, 241` / 正準定義の複製 / **P2**
- summary: 「担当バッチが処理できる行」の条件を、`derived_data_freshness`はバッチと共有する宣言にしたのに、同じ変更で入った`material_coverage`は同じ条件を手書きで複製している。
- evidence: `CompletenessSpec.in_scope`は「**この宣言が唯一の情報源**」と明記し、実際に2つのバッチが`completeness_spec()`から取っている。一方`material_coverage.py:231,241`は`in_scope="w.geom IS NOT NULL AND w.highway IS NOT NULL"`を生SQL文字列で持ち、`precompute_way_landcover._target_way_ids_stmt`が同じ条件を独立に持つ。テストは`in_scope`がSQLへ入るかまでで、バッチ側との一致は検査していない。
- failure_scenario: `precompute_way_landcover`の対象条件を後から絞ると、材料カバレッジ画面の欠損率が構造的に0へ到達しなくなる——このdocstringが避けようとしたまさにその症状が、検知器なしで再発する。
- recommendation: 宣言側を唯一の情報源にする。少なくとも「バッチの対象述語と`in_scope`が同じ行集合を返す」ことをPostGIS統合テストで固定する（設計原則12）。

**O-3** `backend/app/infrastructure/road_graph_repository.py:1099-1108` / スケールしないクエリ類型 / **P3**（Inference中心）
- summary: 上下線分離判定の条件2が、条件3で明示的に避けたはずの「wayの全体bboxで前置フィルタを広げる」形になっている。
- evidence: 条件3には「前置フィルタは標本点まわりの小さな箱にする（**wayの全体bboxで広げると長い道で候補が爆発する**）」というコメントがあり点まわりの箱を使う（`:1124-1128`）。条件2は`b.geom && ST_Expand(t.geom, …)`——`t.geom`はway全体（`:1105`）。その後に長いLINESTRING同士のgeography `ST_DWithin`。`ref`/`name`一致条件は式インデックスが無い。T865の実測は開発DBのみ。
- recommendation: 条件2も標本点まわりの箱へそろえるか、本番で1回実測して根拠をコメントへ残す。

**O-4** `backend/app/infrastructure/derived_data_freshness.py:272-281` / 姉妹モジュール間の不統一 / **P3**
- summary: 完成度の集計が母集団ごとにまとめられておらず、`road_edges`を2回別々に全走査する。隣の`material_coverage`は同じ問題を「母集団ごとに1回」で解いている。
- recommendation: 母集団でグルーピングして1文にまとめる。低優先。

**O-5** `backend/app/infrastructure/cache_generation.py:18` / 残骸・破棄を記録しない / **P3**
- summary: `logger`を定義しているが一度も使っておらず、キャッシュを捨てた事実をこのモジュールは記録しない。軸定義側は破棄しても何も出ない経路が残る。
- recommendation: 破棄時に1行INFOを出すか、`logger`を削除する。

**O-6** `backend/app/infrastructure/tile_score_matrix_cache.py:88-91` / 不要なwrapper / **P3**
- summary: `_remember`は`_cache[key] = matrix`の1行で、docstringが述べる「上限超過分を退避する」は`LRUCache`の仕事。
- recommendation: 呼び出し2箇所を直接代入へ置き換えて削除する。

### consistency

**C-1** `backend/app/infrastructure/road_graph_repository.py:340`（同型が`precompute_way_divided_carriageway.py:1`）/ コメントが存在しない列を名指し / **P3**
（S1のC-3・S4のconsistency-1と同一事象）

**C-2** `backend/app/infrastructure/graph_material_cache.py:113-119` / docstringが述べる契約と実装が逆 / **P3**
- summary: `clear()`のdocstringが「テスト用（**本番コードパスからは呼ばない**）」と書いているが、T847以降はルート生成のたびに通る本番経路から呼ばれる。双子の`tile_score_matrix_cache.clear()`は更新済みで、片側だけ残っている。
- recommendation: 双子側と同じ文面へそろえる。

**C-3** `backend/app/infrastructure/road_graph_repository.py:9-11` / モジュールdocstringの責務記述が乖離 / **P3**
- summary: `AttributeRepository`を「Edge単位のRoad Attribute（elevation_attributes）」と説明しているが、実際にはway単位の派生データ群とキャッシュ世代カウンタまで抱えている。
- evidence: 実装（`:2155-2747`）は`save_way_landcover`・`get_way_curvature`・`recompute_way_divided_carriageway`（今回追加）等のway単位を持つ。`get_derived_data_revision`は道路属性ですらない。
- recommendation: 説明を現状化する。分割自体（Keep Listのフラット委譲契約）は変えない。

**C-4** `backend/tests/test_road_graph_repository.py:1613-1634` / 実装を変えたのにテストが契約を検証していない / **P2**
- summary: MVTの`oneway`焼き込み条件が変わった（`direction <> 'both'` → それ**かつ**上下線分離でない）のに、タイル側のテストは`way_divided_carriageway`に行を1件も入れず、新しい分岐を一切通らない。
- evidence: 実装は`CASE WHEN w.direction != 'both' AND NOT COALESCE(wdc.divided, false) THEN true END`（`:343-345`）。テストのdocstringは「T289: 一方通行は`osm_raw_ways.direction`から算出する」と変更前の契約のまま。T865が追加したバッチ側テストはタイルへの反映を検証範囲外にしている。
- failure_scenario: JOIN条件の書き間違い・否定の落としのいずれでも`pytest -m postgis`は全green。T865が直したはずの症状が本番で無警告のまま復活する。
- recommendation: `divided=true`の行を入れたケースを足す。**わざと`NOT COALESCE(...)`を外して落ちることを確認してから完了扱いにすること。**

**C-5** `docs/improvement-plan.md:1350` / `docs/tasks/T865.md` / `[x]`化時に未実施の段階が残っている / **P2**
- summary: T865は`[x]`だが、本番DBへのバックフィル（`precompute_way_divided_carriageway`の本番実行）と、条件1が効くために必要なPBF再取込のどちらも、実施記録も残タスクの起票も無い。
- evidence: `docs/tasks/T865.md:37`が自ら「本番の既存データはバックフィルが要る」と書くが、検証節の実測はすべて開発DB。比較対象のT654・T764は`- [ ]`＋残りの明記を保っている。MVT側は`COALESCE(wdc.divided, false)`で安全側に倒れるため、テーブルが空の本番では**従来どおり全部塗られる**。
- failure_scenario: 本番backendはデプロイ済みだが利用者が指摘した症状はそのまま残る。タイル世代だけが動いてキャッシュが作り直され、見た目は変わらない。`- [ ]`行が無いため`/task:next`にも周期レビューにも上がらない。
- recommendation: T865を`- [ ]`へ戻すか独立起票する。条件1についてはT654と同じ形でトリガー行を立てる。

**C-6** `backend/app/infrastructure/road_graph_repository.py:1117-1123` / コメントと述語の不一致 / **P3**（Inference含む）
- summary: 条件3の名前突き合わせについて、コメントは「名前が食い違う道どうしは対にしない（両方無名は許す）」と述べるが、述語は「片方だけ無名」も許しており、コメントが挙げた側道のケースをむしろ通す。
- evidence: 述語は`(b.ident IS NOT DISTINCT FROM t.ident OR t.ident IS NULL OR b.ident IS NULL)`。「両方無名は許す」は`IS NOT DISTINCT FROM`が既に賄っており、後ろ2つのORはそれより広い。
- recommendation: `OR b.ident IS NULL`を落とすか、コメントを実際の述語へ書き換える。テストへ「名前付き × 無名の並走」を1件足す。

**C-7** `backend/app/infrastructure/material_coverage.py:214-218` / 整形崩れ / **P3**
- summary: `curvature_deg_per_km`エントリのインデントが周囲の8スペースに対し4スペース。`ruff check`は式内インデントを検査しないため素通りしている。

**該当なしとした観点**: `region-tile-config.json`は同一コミットで再生成済み。`cache_identity.shape_digest`のバインド値署名（T813）は実物で固定済み。`MATERIAL_REVISION`撤去の残骸なし。新設3ファイルと`way_divided_carriageway`はdocs/modulesへ反映済み。経緯コメントの新規混入なし。

---

## S3. backend/app/services

### overall

**O-1** `backend/app/services/graph_service.py:226-228`（＋`derived_data_revision_service.py:33-57`）/ ガードが本来の経路に置かれていない / **P0**
- summary: T847で新設した「バッチが派生データを書き直したらディスクキャッシュを捨てる」TTLガードが、材料ディスクキャッシュを実際に読む経路（`get_search_materials_for_bbox` → `_build_search_materials_from_tile_cache`）から一度も呼ばれず、split鮮度が最新の定常状態では**本番で一度も発火しない**。
- evidence: `ensure_caches_match_db`の本番呼び出し元はリポジトリ全体で`graph_service.py:228`の1箇所のみ。それが置かれているのは`get_or_build_graph_with_attributes`。一方`get_search_materials_for_bbox`（`:299-348`）は`_ensure_split_up_to_date`が真なら`_build_search_materials_from_tile_cache`（341-348行）へ直行し、`get_or_build_graph_with_attributes`を通らない。冷パスだけが通る。`region_service.py:60-68`のバックグラウンド構築も`is_split_up_to_date`が真なら即return。
- failure_scenario: 本番で`refresh_derived.py`を再実行 → `derived_data_meta.revision`は進むが`split_at`は変わらない → backendはタイル材料ディスクキャッシュを世代照合せずに復元し続け、**プロセスを再起動するまで古い材料でルートを生成する**。T847.mdが動機として名指しした「`refresh_derived.py`の再実行がまさにこの形」そのもの。症状は「未訪問タイルだけ新しい」局所的な形で現れ、気づけない。
- recommendation: 呼び出しを`get_search_materials_for_bbox`の先頭（T847.md:82が宣言している位置）へ移す。移した後、わざと`revision`を進めて「温まったタイルへの2回目のリクエストでディスクキャッシュが捨てられる」ことを実際に観測してから完了扱いにする。

**O-2** `backend/benchmarks/bench_evaluate_graph.py:19`（呼び出し元`run_all.py:20,38`）/ 撤去の取り残し / **P2**
- summary: T819で`evaluation_service.evaluate_graph`を撤去したが、それをimportするベンチマークが残っており、`python -m benchmarks.run_all`は4/4でImportErrorになる。
- evidence: `run_all.py`自身のdocstringが「計測対象が構造的に無くなったベンチマークはこの一覧から外す（モジュール自体も残さない）」と規定。`docs/tasks/T819.md`は「消費者0件を確認済み（…**`backend/benchmarks`**）」と書いているが事実に反する。
- failure_scenario: 性能回帰を測ろうとして`run_all`を回すと、先行3本（数分）を走らせた後に4本目で落ちる。判断原則14の実測手段そのものが壊れている。
- recommendation: モジュールごと削除するか薄い入口を用意する。T819の「消費者0件」記述を訂正する。

**O-3** `backend/app/services/road_graph_engine.py:2074-2075`（関連コメント`:1046-1048`）/ 表示値の二重計算 / **P2**
- summary: 候補の所要時間はT790の走行モデルから求めるのに、区間ごとの到達予想時刻だけは仮定巡航速度の割り算のまま残っており、同じ候補の中で2つの時間軸が食い違う。
- evidence: `_estimate_duration_seconds`（1941-1963行）は`leg.travel_seconds_full`＋ターンの待ちを積む。`_build_segment_details`（2074-2075行）は`elapsed_hours = cumulative_km / self._assumed_speed_kmh`。両方ともフロントが表示する。さらに`:1046-1048`のコメント「**ここだけは**走行モデルを通さず…」は事実に反する。
- failure_scenario: モデルの総所要時間が2時間10分と出ているのに、最終区間の「到達予想」は出発+1時間30分（30km÷20km/h）と表示される。
- recommendation: 到達予想時刻をレグ配列の`travel_seconds_full`の累積から作る。前後の一致は機械的に検査できる。

**O-4** `backend/app/services/route_generator.py:490`（受け側`routes.py:421-427`）/ 失敗理由の握り潰し / **P2**
- summary: 区間の乗り換え（合成ルート）の検証エラーは利用者向けの日本語文として書かれているのに、routerの汎用catchで捨てられ「時間をおいて再度お試しください」という**この失敗には当てはまらない**案内だけが返る。
- evidence: `road_graph_engine.py:1741-1758`が`RoutingError("経路がつながっていません index=…")`等を送出。`generate_spliced_route`はこれを捕捉せず`last_no_candidates_reason`も設定しない。他の候補0件経路はすべて理由が画面へ届く。
- failure_scenario: 成立しないedge_id列を送ると、利用者は「時間をおいて再試行」を指示され、何度やっても同じ結果になる。原因はサーバーログにしか無い。
- recommendation: `RoutingError`を捕捉し`last_no_candidates_reason`へ入れて空リストを返す（他の生成経路と同じ形）。

**O-5** `backend/app/services/road_graph_engine.py:430-436` / ログの識別子が経路によって意味の違う値になる / **P3**
- summary: 再利用ログ`compose_leg_costs leg=%s mode=reused key=%s`の`key[0]`は、経路によって文字列にもfloatにもなる。あわせてスナップショット経路では復路レグが往路と同一オブジェクトを共有するため`label`が`"outbound"`のまま`context.legs[1]`に入る。
- recommendation: `mode`に`snapshot|passage|time_bin`を明示し、キーは補助情報として出す。

**O-6** `backend/app/services/evaluation_service.py:1-12` / 残骸 / **P3**
- summary: T819で`evaluate_graph`が撤去され、`RoutePreference()`をそのまま返す1関数だけのモジュールになった。名前が示す「評価のオーケストレーション」は何も行っていない。
- recommendation: `domain/route_preference.py`側へ寄せるか`dependencies.py`が直接組む形にして撤去する（挙動変化なし）。

### consistency

**C-1** `docs/tasks/T847.md:82` ↔ `graph_service.py:228` ↔ `derived_data_revision_service.py:38` ↔ `tests/test_derived_data_revision_service.py` / 4者乖離 / **P1**
- summary: 上記overall P0の記述側。T847.mdは呼び出し点を`get_search_materials_for_bbox`の先頭と宣言し、サービスのdocstringは存在しない`main.py` lifespanの`force`呼び出しを名指しし、テストはサービス関数を単体でしか叩かないため、どこにも「経路へ組み込まれている」ことを検証するものが無い。
- evidence: `main.py`に呼び出しは無く（grepで0件）、`force=True`の呼び出し元はテストのみ。`test_graph_service.py`の追加はFakeにメソッドを生やしただけで、呼ばれることは検査していない。
- recommendation: 実装を宣言どおりの位置へ移す（正はタスク記述側）。`force`のdocstringは実在する呼び出し元だけを書く。`test_graph_service.py`に経路の検査を1件足す。

**C-2** `backend/app/services/elevation_attribute_service.py:95-102`（実装77-82行）/ `tests/test_elevation_attribute_service.py:256-271` / docstringと実装の不一致・テストが矛盾する挙動を固定 / **P2**
- summary: docstringは「1点でも一時障害で読めなかったEdgeはFalseで、呼び出し側が永続化を見送る」と書くが、実装は`resolved_edges`を`start_elevation_m is None`の枝でしか参照しないため、一部の点だけ一時障害で読めなかったEdgeは**部分的な標高から算出した値のまま恒久永続化**される。
- evidence: `:78-82`が`resolved_edges`を見ない。`domain/attributes.py:542-572`はNone点を除外して算出する。キャッシュ判定は行の存在だけを見るため再取得されない。`test_partial_points_missing_elevation_is_still_persisted`がこの挙動を固定している。
- failure_scenario: GSIタイル取得が一過性に失敗し末尾1点だけが読めない → 残り2点から average_grade が算出され永続化 → 復旧後も二度と再取得されず、そのEdgeの勾配が恒久的にずれる。T850が防ごうとした「一時障害と欠測を取り違える」の残り半分。
- recommendation: 永続化条件を`resolved_edges.get(edge_id)`で一本化する。テストを2件へ分ける。

**C-3** `docs/modules/backend/routing-engine.md:623-626` / 撤去済みAPIを記述したまま / **P2**
- summary: T819が`build_csr_structure(reverse=True)`/`build_search_graph_statics(reverse=True)`（転置CSR経路）を撤去したのに、モジュール文書が引き続きこの引数を仕様として記述している。
- evidence: 実装は`routing.py:129`・`:207-209`でいずれも`reverse`引数を持たない。639行の`build_turn_expanded_tree(reverse=True)`は現存するため訂正対象ではない。
- recommendation: 623-626行を現状（転置は`TurnExpandedStructure.reverse_transitions`が担う）へ書き直す。

**C-4** `docs/modules/backend/evaluation-scoring.md:34` / 撤去済みの責務を語る記述 / **P3**
- summary: 0次ハードフィルタの節が「`RoutePreference`が個別ON/OFF上書きを持つ（`evaluation_service.py`が既定Noneを受け取り解決）」と書くが、現在は`RoadGraphEngine.__init__`の`hard_filters`→`compute_hard_filter_excluded`。同ファイル453行以降はT819で更新済みで、34行だけが取り残されている。

**その他、確認したが指摘に至らなかった点**: `SPLICED_ROUTE_ID`の片側importとドリフト検知テストは成立。`select_via_nodes`の打ち切り位置修正は`select_loop_turnarounds`と規則が揃う。撤去された防御分岐は先行する`_build_segment_details`が先に落ちるため到達不能で撤去は妥当。`_turn_seconds_along`の部分欠損には回帰テストあり。`road_graph_engine.py`の規模はKeep List対象のため指摘対象外。

---

## S4. backend/app/api + batch + config

### overall

**O-1** `backend/app/batch/_common.py:62-88` / derived-data-revision-partial-write / **P2**
- summary: 派生データ世代のbumpが「異常終了ではDBを書いていない」という成立しない前提に立っている。
- evidence: docstringが「dry-runと異常終了では進めない（**DBを書いていない**）」と述べる。しかし (a) `run_chunked_precompute`（`:210-219`）は`handle_chunk`ごとに`session.commit()`しており途中で例外が出ればそこまでのチャンクは確定済み。(b) `refresh_derived.py:81-96`は各段の`run()`を直接呼び、いずれかが非0を返すと`main()`側のbumpが`code != 0`で早期returnする。④〜⑫が書き込み済みでも世代は進まない。
- failure_scenario: 本番でPBF再取込後`refresh_derived`を実行→⑬（最も重い、OOM実績あり）がOOM killされる。④〜⑫の派生データはDBに入っているが`revision`は据え置き。`graph_material_cache`は古いまま復元し続ける——このヘルパー自身がdocstringで警戒している状態そのもの。
- recommendation: 「成功した段が1つでもあればbumpする」形にする（あるいは段ごとにbump）。docstringから誤った断定を外す。`test_failed_run_does_not_bump`が現在の誤った不変条件を固定しているためテストも見直す。

**O-2** `backend/app/batch/precompute_edge_curvature.py:47-79` / batch-driver-bypass / **P2**
- summary: `precompute_edge_curvature.py`だけが共通ドライバを使わず骨格を写経している。
- evidence: `run()`が「`count_targets`→対象件数ログ→dry-run早期return→0件WARNING→`stream_id_chunks`ループ→chunk進捗ログ→完了ログ」を手書き。`_common.py:186-188`のdocstringが明示的に禁じているもの。既にずれも発生（進捗ログが他バッチの`elapsed=%.1fs`に対しここだけ`chunk_ms=%d`）。
- recommendation: `run_chunked_precompute`へ寄せる。

**O-3** `precompute_way_curvature.py:42`ほか計9箇所 / lineage-query-duplication / **P2**
- summary: 系譜run id取得SQL（`SELECT MAX(id) FROM {osm,accident}_import_runs WHERE status = 'succeeded'`）が9箇所へコピーされている（依頼された「14行クローン」の実体）。
- evidence: バッチ固有なのはrepositoryメソッド名・`ALGORITHM_VERSION`・対象stmtだけで、それらは既に`run_chunked_precompute`が引数で吸収している。残る共通部分＝系譜取得は「同じ理由で変わる」。既にコピー同士が分岐している（片方だけ系譜ログを出す）。
- failure_scenario: `status`の語彙追加や高水位マークの定義変更時に一部だけが更新され、鮮度台帳が「常にstale」または「永久に最新」という読まれない警告になる。
- recommendation: `_common.py`へ`latest_succeeded_run_id(session, table)`を1本置く。**残りの14行クローン（`handle_chunk`の器）は共通化しない**——repositoryメソッドと版数定数の違いは各バッチの本質。

**O-4** `import_pbf.py:470-477`ほか6箇所 / batch-main-boilerplate / **P3**
- summary: バッチ`main()`の起動形が6箇所で手書き複製。`run_simple_batch_cli`は`--database-url`/`--dry-run`だけのバッチ専用で、追加引数を持つ6本は使えない。
- recommendation: ログ設定＋`asyncio.run(bump(...))`だけを畳む`run_batch_main`を置き、argparse部分は各バッチに残す。

**O-5** `backend/app/infrastructure/db_status.py:47-59`（＋`dependencies.py:408-412`, `routers/db_status.py:92-99`）/ admin-endpoint-cost / **P3**（推測）
- summary: `/api/admin/db-status`が全テーブル実COUNTをルート生成用プール上で無制限に実行できる。
- evidence: `_TABLE_STATS_SQL`は`query_to_xml`で実数カウントを回す。本番の`osm_raw_nodes`・`road_edges`（約500万件）を含む全テーブルの逐次走査。依存は`get_route_generation_session_factory()`（command_timeout=180）。`enforce_rate_limit`も同時実行上限も無い。
- recommendation: 本番で1回実測。余裕が無ければ専用semaphoreか、巨大テーブルだけ`n_live_tup`併記へ落とす。

**O-6** `backend/app/batch/_common.py:1-9` / docstring-enumeration-stale / **P3**
- summary: モジュールdocstringが利用者を列挙しており、最も横断的な`with_derived_data_revision_bump`と`run_chunked_precompute`を落としている。
- recommendation: 利用者ファイル名の列挙をやめ「何を提供するか」だけを書く。

### consistency

**C-1** `precompute_way_divided_carriageway.py:1, :9-10`（同型が`road_graph_repository.py:340`）/ docstring-contradicts-schema / **P2**
- summary: docstringが存在しないテーブル・列を指し、migration 0040の設計意図と正反対を述べる。
- evidence: 「way_geometry.divided_carriageway」「`precompute_way_curvature.py`と**同じ`way_geometry`の行を触るが**」と書くが、実際は独立テーブル`way_divided_carriageway.divided`。migration 0040のコメントと`static-road-attributes.md:244-247`は**「系譜の列が行単位で1組しか無く、2つのバッチが同じ行を書くと互いの系譜を上書きしてしまうため独立テーブルにした」**と明確に否定している。
- failure_scenario: docstringを根拠に「1本にまとめられる／`way_geometry`へ列を足せばよい」と判断すると、migration 0040がまさに避けた欠陥を再導入する。
- recommendation: 3箇所すべてを1コミットで訂正。

**C-2** `docs/batch-pipeline-dependencies.md:89, :94, :139, :147` / runbook-stale-after-new-batch / **P2**
- summary: ⑬の追加に追随しておらず、タイル世代の手動上げ指示が⑬に欠けている。
- evidence: `way_divided_carriageway.divided`は路面MVTへ焼き込まれている（`road_graph_repository.py:344`）が、タイル世代の手動上げを明記しているのは⑧の行だけ。`:139`の手順とbump対象リストからも⑬が欠落。`:147`「④〜⑫」（実際は⑬まで）、`:94`「**全12バッチとも**」（現在13本）。
- failure_scenario: ⑬だけを単独再実行した運用者がbumpせず、既存のディスクキャッシュタイルが配信され続け、一方通行レイヤーが古い判定のまま。`revision`のbumpは材料キャッシュにしか効かずタイルには効かない。
- recommendation: ⑬の行へ注記を追加。手順・対象リスト・「④〜⑬」を修正。「全12バッチ」は個数を書かない形へ。⑪にも同じ注記が無い点を併せて確認。

**C-3** `docs/batch-pipeline-dependencies.md:119-126` / doc-implementation-drift / **P3**
- summary: 世代bumpの説明が「一部のバッチだけ」と読める列挙のまま。実装は`_common.py:68-70`が「どのバッチが材料に効くかを個別に判断しない」として全バッチ無条件にbumpする。
- recommendation: 列挙をやめ挙動の記述へ置き換える。

**C-4** `precompute_way_attribute_counts.py:18`ほか4箇所 / stale-symbol-location / **P3**
- summary: 4バッチのdocstringがタイル世代定数の所在を誤って案内する（「region_service.py: ROAD_SURFACE_TILE_VERSION」）。実際の定義は`road_graph_repository.py:624`で、しかもこの値は導出値で手で上げてはいけない。手で上げるのは`cache_identity.py:29`の`ROAD_SURFACE_REVISION`。
- recommendation: 4箇所を統一。

**C-5** `backend/app/batch/match_designations.py:149-150` / dead-identifier-reference / **P3**
- summary: 「`precompute_edge_attribute_counts.py: _get_latest_run_ids`と同じ」とあるが、当該関数名は`_fetch_source_run_ids`。`_get_latest_run_ids`はリポジトリ全体に存在しない。
- recommendation: 名前を訂正。ソースコード内の識別子参照を検知器が拾えていない点も検討の価値あり。

**C-6** `backend/tests/test_precompute_way_divided_carriageway.py` / test-asymmetry / **P3**
- summary: 双子バッチのテスト対称性の欠け。dry-runがDBを書かないこと・0件時のWARNINGを検証していない。
- recommendation: 同型のdry-runテストを1件追加。

**C-7** `docs/architecture.md:824`付近 / architecture-doc-partial-coverage / **P3**
- summary: 新設の`GET /api/admin/db-status`・`/api/admin/road-graph-tiles`と既存の`/api/admin/derived-data/freshness`が一切現れない一方、同性格の`/api/admin/material-catalog/coverage`は記載がある。
- recommendation: `architecture.md`側のエンドポイント個別列挙をやめる方向で揃える（`routers/__init__.py:3-6`が既に「写し取った索引は持たない」方針を宣言）。

**C-8 生成物のドリフト: 該当なし** — `api.d.ts`に新設APIと新フィールドがいずれも反映済み。`route-generate-config.json`の`default_distance_tolerance_km: 5.0`も一致。

**総括（トレンド、S4担当の所見）**: batch側は「宣言を1箇所に置き、検査で網羅性を機械的に守る」方向へ明確に前進している（`COMPLETENESS_SPECS.in_scope`とバッチの突き合わせ、`_STAGES`とファイル一覧の突き合わせ、バッチ入口のbump強制、版数の一本化）。設計原則12がバッチ領域で実際に効いている。残る弱点は3種: (a) 共有の関心事のうちまだ`_common.py`へ上がっていないもの、(b) 新しいバッチ⑬を足したときの運用文書の追随漏れ——**機械検査を足した領域ほど、検査の外に残った散文の陳腐化が相対的に目立つ**、(c) 新設テーブルの名前がdocstringで旧案のまま。

---

## S5. frontend/src/components/Map

### overall

**O-1** `MapView.tsx:1653-1667`／`:1766-1772`／`:2711-2800`／`:3950-3976` / 再描画の網羅漏れ（T524/T825の再発）/ **P1**
- summary: `redrawAllLayers`が`applyInspectedWay`を呼ばないため、道の詳細ポップアップを開いたまま「地図の表示を再描画」を押すと、オレンジの強調だけが消えてポップアップは残る。
- evidence: `ROAD_INSPECT_LAYER_ID`は`ensureRoadSurfaceTileLayer`内で`visibility:"none"`／`filter:["==",["get","osm_way_id"],-1]`として追加され、`setStyle()`でソースごと消えるため再作成時は必ず初期値に戻る。`redrawAllLayers`が呼ぶ10関数に**`applyInspectedWay`は含まれない**。強調を適用する唯一の経路はポップアップeffect（`:3954-3976`）で依存配列は`[roadPopup]`のみ。`setStyle`ではこのstateは変わらないため再実行されない。`MapView.layerOps.test.ts:83-115`は`applyInspectedWay`単体しか見ていない。
- failure_scenario: 道をクリック→ポップアップ（対象wayが橙で強調）→「地図の表示を再描画」→ポップアップは開いたまま強調だけ消える。閉じて開き直すまで復旧しない。T868が明記した目的（「どの線の話かが分からないと場所を取り違える」）が成立しない。
- recommendation: `RedrawAllLayersProps`へ`inspectedWayId`を加え末尾で`applyInspectedWay`を呼ぶ。テストを追加し、外すと落ちることを確認する。

**O-2** `scripts/review_checks.py:442-487`（`find_map_redraw_gaps`）/ 検査の母集団が性質から導かれていない / **P1**
- summary: 検知器は`owners = {n for n,b in body.items() if ".addSource(" in b}`だけを母集団にするため、既存ソースを再利用するレイヤーや「どのwayを強調中か」といった再描画で失われる状態を一切見ない。
- evidence: `:480`が該当行。`applyInspectedWay`は`addSource`を持たないため母集団外。実行結果は「map.setStyle()後の再描画から辿れないレイヤー（全件）: 0件」——**O-1が存在する状態で0件**。`docs/tasks/T825.md`は「T524の再発を止めるのはこの1点で、個別の追加ではない」と書いており、この検知器が唯一の再発防止策として位置づけられている。T825完了（09-14）の翌日にT868が新しい抜けを作った。
- recommendation: 母集団を「`map.addLayer(`／`map.setFilter(`／`map.setFeatureState(`／`setLayerVisibility(`を含むトップレベル宣言」へ広げる（＝「再描画で失われる副作用を持つ宣言」という性質から導く）。広げた結果の既存検出件数を実測してタスクエントリへ書き、緩和を足すならその件数と割合も記録する。

**O-3** `mapLayers.ts:211-229` / 撤去済み仕様の残存（利用者向け文言）/ **P2**
- summary: 「道路の種類」チップの`description`と`panelHint`が「線の太さで表示」「路面の種類がONのときは色はそちらを優先」と述べるが、T858でどちらも撤去され、全レイヤーが同じ`DEFAULT_ROAD_LINE_WIDTH`（3px）・各レイヤーが自分の色式だけを使う設計になっている。
- evidence: `:221`・`:225-228`が該当。実装は`MapView.tsx:1788-1800`。`roadFilterAxes.ts`から`widthExpression`/`dashArrayExpression`は削除済み（`roadFilterAxes.test.ts:114-132`が復活を検査）。`:211-215`のコメント「物理描画は1本のMapLibre線レイヤー…に合成する」も`MapView.tsx:287`で独立レイヤー化済みのため成立しない。
- failure_scenario: 利用者がチップのtitle／▶パネルのⓘを読むと、実際には存在しない挙動を期待する。T858はまさにこの挙動への苦情を受けた修正で、説明文だけが直前の仕様を語り続けている。

**O-4** `roadFilterAxes.ts:15-19`（および`:45-51`、`:135`）/ 自己矛盾 / **P2**
- summary: 冒頭が「路面の種類がONの間は常にその配色で固定する（道路の種類の色を上書き）」と書く一方、6行下と`colorExpression`のdocstringは「他の軸のON/OFFで色の意味が変わることはない」と書いている。`:48-51`は存在しない出し分けロジックを指す。

**O-5** `dedicatedWayValueLayer.ts:39-40`／`MapView.tsx:2515`／`:3499`／`secondaryAxes.ts:50`／`dynamicWayValues.ts:28-30`／`dynamicWayValues.test.ts:77`（参考: `app/page.tsx:200`）/ 削除した事実を語る周辺表現の残存 / **P2**
- summary: T857で撤去された`gradientGridFill.ts`／`gradientFill`レイヤーを、複数のコメントが現存する対比対象として名指ししている。
- evidence: 6箇所（上記）。`dynamicWayValues.ts:28-30`は削除で中間行だけが消え宙に浮いた文が残った。`buildDedicatedWayValueColorExpression`の`:51`「値の取得元を引数に取る形のまま残してあり、feature-state以外から値を読む呼び出し側を足せる」は、消費者ゼロの汎用化が残っている旨の自己申告になっている。
- failure_scenario: 2026-09-10の統合レビューが同型（風penalty gridFill）をP2で指摘済みで、今回は勾配側で再発。
- recommendation: 6箇所を同一コミットで是正。`buildDedicatedWayValueColorExpression`は消費者1つのため畳むか「消費者は現在1つ」と正直に書く。

**O-6** `MapView.tsx:1866` / 正準定数の複製 / **P3**
- summary: `makeEnsureAttributeLineLayer`（指定路線・トンネル・一方通行）だけが線幅を直値`3`で持ち、`DEFAULT_ROAD_LINE_WIDTH`から外れている。

**O-7** `MapView.tsx:309-311` / `roadFilterAxes.ts:243-245` / 不要なfallback / **P3**
- summary: どちらもコード自身が「通らない」と述べているフォールバック（`DEFAULT_ROAD_LINE_OPACITY`、`getRoadFilterAxis`の`?? ROAD_FILTER_AXES[0]`）。

**O-8** `dynamicWeather.ts:209-229`／`useDynamicWeatherLayers.ts:355` / 母集団の手作業列挙 / **P3**
- summary: T861が直した欠陥は「予測を持たないレイヤーは常に描かれない」だが、修正の適用は`liden`の呼び出し1箇所を差し替える形で、同じ性質を持つ次の要素は同じ欠陥を再現する。
- evidence: `:313,318,338,343`は`frameIndexForTime`、`:355`だけが`observationIndexForTime`。判定条件（予測フレームの有無）は`JmaNowcastFrame.isForecast`としてデータ側に存在するが、`DynamicWeatherFrame`は`time`と`ref`しか持たないためフレーム列からは判定できない。
- recommendation: `DynamicWeatherFrame`へ`isForecast`を持たせ、予測が1件も無ければ自動的に`observationIndexForTime`を選ぶ共通関数にする。`dynamicWeather.ts:19-21`の4本柱3番へ例外を明記する（モジュール文書には既に書かれており、コード側だけが古い）。

**O-9** `icons.tsx:443-444`／`:552` / 残骸（コメントの帰属ずれ）/ **P3**
- summary: `ClearRoutesIcon`のdocstringが`RouteSpliceIcon`のdocの直前に取り残され、本体はdocを失っている。

### consistency

**C-1** `RoadInspectorPopup.tsx:49-52, 74-94`／`AxisContributionBar.tsx:56-70` / 共有部品が明示する契約の不遵守 / **P2**
- summary: 呼び出し側は`Object.keys(contributions).length > 0`で空状態を判定するが、`AxisContributionBar`は`hasContribution`（値0を「無し」とする）で判定して`null`を返すため、全寄与が0のとき「バーも凡例も案内文も出ない」空セクションになる。
- evidence: `RoadInspectorPopup.tsx:49-52`は**値0.0もキーとして入る**。`AxisContributionBar.tsx:53-55`のdocstringが「**空状態の案内文を出す側とバーを描く側で同じ判定を使う**（別々に書くとずれ、「案内文も出ないしバーも無い」状態が生まれる）」と明示し、そのために`hasContribution`をexportしている。backend側は重み合計>0なら difficulty 0・重み0の軸も`0.0`を返す。
- failure_scenario: 1軸だけ（例: 事故密度）を有効にし事故0件の道をクリックすると、全寄与が0になり「評価への効き方」の見出しの下に**何も無い**空白が出る。案内文も出ない。
- recommendation: 条件を`axes.some((a) => hasContribution(...))`へ差し替える。テストを追加し、条件を戻すと落ちることを確認する。

**C-2** `docs/modules/frontend/static-map-layers.md:241-242`（対`:88-92`）/ docs↔docs・docs↔実装 / **P2**
- summary: T858が`:88-92`を新しいルールへ書き換えた一方、`:241-242`の旧記述が残り、同一文書が正反対を主張している。

**C-3** `docs/modules/frontend/static-map-layers.md:152-158` / 死んだ記述 / **P2**
- summary: T819で撤去された`LayerChip`の状態ドットを現行仕様として記述している。現在の`LayerChip.tsx`のpropsは`label`/`on`/`ariaLabel`/`onClick`のみで、CSSクラスも0件。
- failure_scenario: 状態ドットを別の場所へ足そうとした人が「`LayerChip`に前例がある」と読んで存在しない実装を追う。死んだ識別子検知はファイル名（実在する）しか照合できずこの型を捕まえない。

**C-4** `docs/modules/frontend/page-composition.md:114`（および`:95`）/ 「検知0件になった」を修正の証拠にした / **P2**
- summary: `3329d303`が検知器の指す1件を消して「0件」を確認したが、**同じ識別子`showGradientFill`が同じファイルのASCII図（コードフェンス内）にもう1件残っている**。
- evidence: `:114`が該当（```で囲まれたブロック内）。frontend/srcには0件。コミットメッセージは「1件 → 0件 違反なし」。本レビューでの再実行も「違反なし」。**識別子は今も残っている**。`:95`「風・勾配それぞれについて…2表現を同時に配線する」も面塗りを持たなくなった今は成立しない。
- failure_scenario: 検知器がコードフェンス内を走査しないため、ASCII図・コード例に残る死んだ識別子は恒久的に見逃される。図はまさに「機構の全体像」を伝える場所。

**C-5** `docs/modules/frontend/map-axis-coloring.md:5-7, 36-46` / docs↔実装 / **P2**
- summary: T857は同ファイルを40行削っているが、責務節とASCII図に残った「環境グループの面（勾配のみ）」は更新されていない。

**C-6** `docs/modules/frontend/static-map-layers.md:264-265`（対`:296-297`）/ docs↔docs / **P3**
- summary: T868でReact描画へ移った道路名について`escapeHtml`を通すと書いたまま。同じ文書の別の節は正しい説明を持つ。

**C-7** `RoadInspectorPopup.test.tsx:51-65` / 実質的に意味のないテスト / **P3**
- summary: `gradient`軸が`available:false`で並ばないことを検査しているが、`gradient`はそもそも`axes`に含まれておらず、フィルタが壊れていてもこの検査は通る。

**C-8** `RoadInspectorPopup.tsx:113-134` / 正準定義の意味のずれ / **P3**
- summary: `PRIMARY_ATTRIBUTE_LABELS`は`axis-catalog.json`の**attr_id**をキーに持つ辞書だが、`result.tags`（OSMのタグキー）で引いており、たまたま綴りが一致するものだけが「登録済み属性」として扱われる。OSMの`bicycle`は`bicycle_access`と一致せずラベルの付かない「その他」へ落ちる。

**C-9** `docs/modules/frontend/static-map-layers.md:185`・`:231` / 数え上げの残存 / **P3**
- summary: 「静的5レイヤー」「7要素の`visible`」が件数を書き写している（前回レビューでも指摘済み、未解消）。

**C-10（参考、本シャード外）** `backend/app/infrastructure/road_graph_repository.py:340` / 死んだ参照 / **P3**
- （S1 C-3・S2 C-1・S4 C-1と同一事象）

### 問題が無いことを確認した観点（再指摘しないための記録）

- **T865の一貫性**: タイルの`oneway`プロパティ自体が`AND NOT COALESCE(wdc.divided, false)`で絞られているため、レイヤーの色分け・凡例・区間詳細の「一方通行: あり」行の3者が同じ母集団を見ている。
- **T852の突き合わせキー**: `payload.tileUrlTemplate`は`jmatile://`を含まない素のURLで、ハンドラも`toRealUrl`後に記録する。`tileDeliveryFailureLayerIds`のprefix比較は両側で同形になり突き合わせは成立する。
- **T860**: `AREA_LAYER_OPACITY`は面で塗る全経路が共有し、レイヤーごとの直値は残っていない。洪水キキクルは線レイヤーのため対象外で正しい。
- **T866**: `makeEnsureAxisRampLayer`が`ensureRoadSurfaceTileLayer`を先に呼ぶ形になり`makeEnsureDedicatedWayValueLayer`と対称。テストが「ソースがまだ無くても自分で用意する」を検査しており、修正を戻すと落ちる構造。
- **T858の回帰検査**: `roadFilterAxes.test.ts:114-132`は`Object.keys()`に該当キーが現れないことを見ており、別名で足しても落ちる形。
- **削除ファイルへの実コード参照**: `WidthSwatch`／`axisInspectorPopup`／`buildAxisInspectorHtml`／`buildRoadSurfacePopupHtml`／`gradientGridFill`はいずれも実コードから0件。`RoadInspectorPopup.module.css`のクラスも過不足なし（15/15一致）。
- **軸ごとの専用実装（構造仕様2・3・8）**: 本シャードの変更範囲に軸id直書きの分岐・軸ごとのprop/定数の新設は無い。

---

## S6. frontend/src/components（Map以外）

### overall

**O-1** `frontend/src/components/AxisStudio/DerivedDataFreshnessPanel.tsx:98-114` / duplicate-copy-implementation・横展開漏れ / **P2**
- summary: 前日に共有フック`useCopyToClipboard`が「押しても何も起きないボタンを作らない」ために新設されたのに、1日前に入ったこの`CopyButton`だけが取り残され、同じ欠陥（無反応のまま黙る）を持ったまま残っている。
- evidence: `:101`は`navigator.clipboard?.writeText(text).then(...).catch(...)`。optional chainingは**チェーン全体**を短絡するため、`navigator.clipboard`がundefinedのときは`.then`/`.catch`ごと評価されず、**エラーも表示も出ずに何も起きない**。`hooks/useCopyToClipboard.ts:15-18`のdocstringが同じ状況を明示。導入順: `9edf8c4f`（T836、09-14）が`CopyButton`追加 → `d74ce513`（T867、09-15）が共有フックを新設し`DebugConsole`・`BackendLogsPanel`へ適用。このパネルは未適用。`developer-research-tools.md:22`の利用者列にも載っていない。表示時間も不一致（1500ms・クリーンアップ無し／フックは2000ms・unmount時clearTimeout）。
- failure_scenario: `/admin`を平文HTTPの内部IPで開き「コピー」を押す → 何も起きず失敗文言も出ない。本番復旧用の`docker run`コマンドを手写しすることになる。同じ状況でDebugConsoleは失敗文言を出すため、画面ごとに挙動が食い違う。
- recommendation: `CopyButton`を削除し`useCopyToClipboard`へ寄せる。developer-research-tools.mdの利用者列にも追加。

**O-2** `DbStatusPanel.tsx:236-291` ↔ `DerivedDataFreshnessPanel.tsx:161-220` / 写経 / **P2**
- summary: 機械検出された14行クローン2組は表層の類似ではなく、「データ保守タブの行の見た目を揃える」という**同一の変更理由**を持つ写経で、CSSだけが共有され構造は二重に持たれている。
- evidence: 重複は検出範囲より広い。行の描画（`li>details>summary`＋markStale/markFresh＋rowName＋rowScale＋srOnly＋`dl`＋note）が完全同型で、差は`needsAttention`/`needsRebuild`とsrOnly文言のみ。型`StatusRow`と`FreshnessRow`も真偽フィールド名だけ違う。`formatCount`は完全一致、`formatComputedAt`は`formatMoment`のnull無し版。パネル外殻（Card＋headingRow＋InfoPopover＋controls＋ボタン文言＋summary＋error）も同型。設計文書側が変更理由の同一性を明言している（`axis-studio.md:306-310`「行の見た目は揃える」「CSSも同じモジュールを共有する」）。共有CSSが片方の名前のままで所有者が曖昧。
- failure_scenario: 3枚目のパネルを足すとき、あるいは行の見た目を1つ変えるときに片方だけ直した状態が型検査もテストもすり抜ける。既に`formatMoment`/`formatComputedAt`のnull扱いが片方にしか無い。
- recommendation: 行＋パネル外殻を`components/ui/`へ抽出し、CSSも中立な名前へ移す。真偽フィールドは共通名へ揃え、フォーマッタも1箇所へ。

**O-3** `DbStatusPanel.tsx:276-291`, `SplitCoverageMap.tsx:79-124` / 設計意図が成立していない / **P2**
- summary: 「`<details>`を開いたときだけMapLibreを初期化する」という設計は成立しておらず、集計結果が出た瞬間に閉じたまま初期化とAPI呼び出しが走る。
- evidence: コメントと`axis-studio.md:319-321`が「開いたときだけ初期化する——閉じたまま使う人に初期化の重さを払わせない」と述べる。実装（`:278-291`）は`<details>`の子として`<SplitCoverageMap />`を**無条件に**描画し`open` stateを持たない。Reactは開閉に関係なく子をマウントする。したがって`:79-91`の`useEffect`が即座に`getRoadGraphTiles()`を発火し、`:93-124`で`new maplibregl.Map(...)`まで走る。`SplitCoverageMap.test.ts`は純関数のみで契約を検査していない。
- recommendation: `open` stateでマウント制御する。「閉じた状態で`getRoadGraphTiles`が呼ばれない」テストを1件置く。

**O-4** `ComparisonPanel.tsx:166` / react-key-collision / **P2**
- summary: 表の行キーに表示ラベル文字列を使っており、材料の論理名と軸ラベルが一致する現行データ（「事故密度」）でReactキーが重複する。
- evidence: `:138-143`が物理指標行＋材料値行（`materialCatalogName`）＋軸難易度行（`axis.label`）を連結し、`:166`で`<tr key={row.label}>`。`material_catalog.py:639-641`に`material_id="accident_count_per_km_year", label="事故密度"`、軸ラベルにも「事故密度」がある。重み>0の軸が参照する材料が`material_values`に載るため、既定配分では両方が同時に出る。
- failure_scenario: 研究モードで2回以上生成して「比較」タブを開くと同一キーの2行になり、Reactが警告を出す。行の追加・並び替えで同キーの2行目が差し替わる／消える誤った再利用が起きうる（実機未確認）。
- recommendation: `MetricRow`に`key`（`"physical:distance"`/`material:${id}`/`axis:${id}`）を持たせる。

**O-5** `AxisComposer.tsx:131-159`（`NumberField`）/ state-sync-bug / **P2**
- summary: 外部起因の値変化を追従させる条件が「最後に同期した値」を更新しないため、値が元へ戻る変化を取りこぼし、入力欄に古い文字列が残ったままdraftと食い違う。
- evidence: `if (syncedValue !== value && Number(text) !== value)`（`:141`）の中でのみ`setSyncedValue`する。ユーザー入力で`value`が変わった経路では条件がfalseになり`syncedValue`が更新されない。折れ点の行はindexキーのため同じインスタンスが再利用される。
- failure_scenario: 折れ点[0]のx欄（初期0）に`5`を打つ → 「折れ点を自動生成」で0点=0を生成 → value=0とsyncedValue=0が一致するので同期が走らず、**入力欄は「5」を表示したままdraftは0**。管理者は「5」を見ながら0の軸を公開する。
- recommendation: `syncedValue !== value`の時点で必ず`setSyncedValue(value)`し、`setText`だけを条件付ける。回帰テストを1件追加（本件はT547由来で本期間より前の混入）。

**O-6** `RideConditionBar.module.css:30` / design-token-copy / **P3**
- summary: 「隣の出発時刻側へ見た目を揃える」ためにトークン`var(--shadow-float)`を捨てて生の値をコピーし、同じ影のリテラルがソース3箇所に並んだ。
- evidence: T862の差分で`var(--shadow-float)`→`0 1px 4px rgba(0,0,0,0.15)`。同リテラルは`DynamicLayerTimeSlider.module.css:21`・`RideConditionBar.module.css:30`・`WindBearingSlider.module.css:16`。トークン側は`globals.css:24,88`の`--shadow-float`（不透明度0.3、17箇所が参照）。コメント自身が同一の変更理由を述べている。
- recommendation: 「地図上に浮かぶ軽い小箱」用のトークンを定義して3箇所を差し替えるか、`ui/`にクラスを1つ置いて`composes`させる。

**O-7** `MapOverlayControls.tsx:145-151`, `:1054-1055` / 撤去済み要素への参照残り / **P3**
- summary: `gradientFill`エントリを消したのに、それを説明する3行コメントだけが`LAYER_ICONS`の中に取り残されている。`chipLabel`と`label`が同一式の二重定義になっている。

**O-8** `MapOverlayControls.module.css:182,519,528`, `Disclosure.module.css:26` / 撤去済みコンポーネントへの死んだ参照 / **P3**
- summary: `MapLayersPanel`は本期間で撤去され`.tsx`側のコメントは更新されたが、同じコミット群の`.module.css`側に4件の死んだ参照が残った。`:182`は「サイドバー側は引き続き…使う」ともう成立しない事実を現在形で主張している。
- evidence: `frontend/src`全体のgrepでlive sourceのヒットはこの4件のみ。`components/MapLayersPanel/`は存在しない。

**O-9** `TodayOutlook.tsx:45-46` / 途中で切れたコメント / **P3**
- summary: `getWeatherCodeDisplay`の第2引数撤去に伴い後続2行が消え、コメントが「〜ため、」で終わっている。

**O-10** `DebugConsole.module.css:100` / hardcoded-color / **P3**
- summary: 本期間で追加した`.copyError`の色が生の`#fca5a5`で、同ファイル内の`--color-log-error`トークンを使っていない。

### consistency

**C-1** `docs/modules/frontend/route-settings-and-results.md:230` / `RouteAxisProfile.test.tsx:141` / docs↔実装の乖離（文書内で自己矛盾）/ **P3**
- summary: 「AxisContributionBarは`RouteSettingsPanel.module.css`のstackBar/stackSegmentを流用」という記述が実装と食い違い、同じ文書の65行目とも矛盾している。
- evidence: 実装は`composes: ... from "../ui/axisLegend.module.css"`。文書`:65`は「スタイルを共有しない」と正しく書き、`:230`が誤り。`RouteSettingsPanel.module.css:53-63`は独自の`.stackBar`を持ちコメントで「共有すると片方の都合で他方が崩れる」と明言。テスト名も誤った出自を述べるが、アサーションは部分一致のためどちらでも通る。
- failure_scenario: 結果パネルの帯を直そうとした人が`RouteSettingsPanel.module.css`を編集し、設定側の帯グラフを壊す。T855で`--load-bar-height-ratio`が共有`.stackBar`に入ったばかりで、共有範囲の誤認は今後当たりやすい。

**C-2** `ComparisonPanel.test.tsx:72-89` / テストが実データの衝突条件を避けている / **P3**
- summary: 上記O-4の行キー衝突をテストが構造的に検出できない。フィクスチャの材料が、実カタログに存在する軸ラベルとの同名ケースを含んでいない。
- recommendation: 「材料の論理名と軸ラベルが一致するケース」を1件足し、行数を検査する。

**C-3** `RouteAxisProfile/axisRawValue.ts:74` / 契約の暗黙前提 / **P3**
- summary: 「最も延長の長い値」を`Object.entries(shares)[0]`で取っており、backendの降順ソートがJSのオブジェクトキー順として保存されることに依存している。整数様の値を持つcategorical材料が現れた瞬間に静かに壊れる。
- evidence: backend側は確かに降順（`route.py:293-296`）。ただしJSのオブジェクトは**整数インデックス様のキーだけ数値昇順へ並べ替えられる**。現行のcategorical材料はいずれも非数値文字列のため**今は成立している**（事実）。テストも非数値キーでしか検証していない。
- recommendation: フロント側で最大値を選ぶ形にする（並べ替えではなく最大値選択なので「フロントが判断表を持たない」原則には触れない）。

**C-4** `BackendLogsPanel.tsx:18` / 手動同期ペアにドリフト検知が無い / **P3**
- summary: backendのログ整形文字列（`debug_control.py:23 _LOG_FORMAT`）をフロントの正規表現が写しているが、両者を突き合わせるテストが無く、テスト側もフィクスチャで同じ書式を手書きしている。
- failure_scenario: `_LOG_FORMAT`からブラケットを外すと、フロントは全行で`parseLogLevel`がnullになり色分けが静かに消える。CIもテストも赤にならない。

**C-5** `DbStatusPanel.tsx:278-291` / `axis-studio.md:319-321` / docs↔実装（O-3と同一事象、重複計上しない）/ **P2**
- summary: 「開いたときだけMapLibreを初期化する」は文書・コードコメント・実装の3者で唯一実装だけが違う。解消方向は**実装側**。

**補足（Findingとしては挙げない）**: `ui/statusDot.module.css`の冒頭コメントが「3状態を…」→「状態を…」へ変わっており、数え上げ廃止方針に沿った良い変更。`AxisContributionBar.tsx:94-98`の「renderDetailは軸あたり1回だけ」は契約とテストが一致。`breakpointTools.ts`/`scoreDistribution.ts`/`curveDistributionOverlay.ts`は境界条件をコメントと実装で一貫して扱い、backend側との一致理由も明記されている。`AxisComposer.tsx`はKeep List対象のため規模自体は指摘していない。

---

## S7. frontend/src/app・hooks・lib・services・types

### overall

**O-1** `frontend/src/app/page.tsx:564-572`（`handleRoutesClear`）/ state-latch・dead-end / **P1**
- summary: 区間編集中（`editingRouteId != null`）に「ルートをクリア」を押すと、`editingRouteId`・`appliedAlternatives`・`splicePreviews`・`spliceError`が残ったまま候補だけが消え、地図の地点編集・候補選択・区間選択が無言で無効化されたまま復帰できなくなる。
- evidence: `handleRoutesClear`が落とすのは7つだけで編集モードの4stateを初期化しない（`handleGenerate`:1614-1617では明示的に落としている）。「ルートをクリア」ボタンは`routes.length > 0`の間つねに表示され、**編集中かどうかで出し分けていない**。`editingRouteId`が残ると`pointEditingEnabled`（887）・`routeInspectionEnabled`（888）・`pinPlacementArmedRole`（889）がすべて無効化される。`pointEditingEnabled`は`MapView.tsx:3608,3636,3656,3671`でマーカーの`draggable`とクリックハンドラ登録に直結。`routes.length === 0`になると`RouteSplicePanel`の「編集をやめて候補へ戻る」＝`editingRouteId`を戻す唯一の導線が画面から消える。
- failure_scenario: 目的地モードで生成 → 「このルートを編集」→ 「ルートをクリア」。地図をタップしても目的地・経由地は置けず、既存ピンもドラッグできず、候補線もタップできない（理由の表示は一切ない）。目的地ピンが残っていれば「ルート生成」で復帰できるが、続けて目的地行の✕（`pointEditingEnabled`でゲートされていない）を押すと検証で止まり、**リロード以外に復帰手段が無い**。
- recommendation: `handleRoutesClear`へ4stateのリセットを追加する。さらに構造として「`routes`に該当idが無ければ編集モードは成立しない」を派生値側で強制する（`pointEditingEnabled`を`editingRouteId`ではなく`editingRoute`で判定する）ほうが横展開に強い。

**O-2** `useDynamicWeatherLayers.ts:143-157` × `page.tsx:1453,1499-1502` × `lib/generationRequest.ts:68-72` / cross-feature-leak / **P1**
- summary: T859で共有時刻が5分刻みで自動前進するようになった結果、利用者が何も操作しなくても生成の約5分後に`conditionsDirty`がtrueになり、「条件が変更されています」の印が誤って点く。
- evidence: T859前はマウント時に固定され利用者操作でしか動かなかった。現在は`dynamicLayerTargetTime = pinnedTargetTime ?? now`で、`now`は30秒ごとに`steppedNow()`（5分刻み）へ更新される。`buildCurrentGenerationInput`は`startTime: dynamicLayerTargetTime`を入れ、`generationConditionsKey`は`IGNORED_WHEN_COMPARING`（`lens_axis_id`のみ）を除く**すべて**を比較対象にする。`start_time`は除外されていない。表示先は3箇所（設定見出し横のドット・結果欄先頭の文言・モバイルタブのドット）。既存テストはタイマーを進めないため検出できない。
- failure_scenario: 出発時刻を触らずに生成 → 放置 → 遅くとも5分以内に3箇所へ「条件が変更されています」が点灯する。利用者は何も変えていないため、この印は「自分の変更が未反映」の合図として機能しなくなる。
- recommendation: 「今」に張り付いている間の`start_time`は利用者が決めた条件ではないので、dirty判定から外す（`GenerationInput`へ「出発時刻を明示指定したか」を持たせる／`IGNORED_WHEN_COMPARING`へ理由付きで加える）。「送るものは全部比較する」規約に穴を開けない書き方を守ること。

**O-3** `useDynamicWeatherLayers.ts:120,302-305,536` × `RideConditionBar.tsx:117` / dead-export・未配線の契約 / **P1**
- summary: 「今」へ張り付きを戻す唯一のAPI `handleDynamicLayerNow`がどこからも呼ばれておらず、UIの「今」ボタンは代わりに`setDynamicLayerTargetTime(new Date())`を呼ぶため、押すと逆に**現在時刻でピン留めされる**。T859が直した「共有時刻が取り残されて降水・雷・竜巻が黙って消える」欠陥が、出発時刻を一度でも触った後（「今」を押した後を含む）に復活する。
- evidence: `handleDynamicLayerNow`は`setNow(steppedNow()); setPinnedTargetTime(null);`で、フックのコメントが「「今」ボタンで張り付きへ戻る」と明記。`grep -rn "handleDynamicLayerNow" src`の結果は宣言・型・returnとテスト1件のみで**production の消費者ゼロ**。実際の「今」は`RideConditionBar.tsx:117`の`onNow={() => onDepartureTimeChange(new Date())}`で`setPinnedTargetTime`へ入る。以後`pinnedTargetTime`は二度とnullに戻らない。加えて`new Date()`は`NOW_STEP_MS`へ丸められておらず、コメントが警告する「`useDedicatedWayValues`の取得だけが無効化される」状態を作る。
- failure_scenario: 時刻をドラッグ → 戻そうとして「今」を押す → 見た目は戻るが内部は固定ピン。10分以上開いたままにすると`frameIndexForTime`が範囲外を返して降水・雷・竜巻・雷放電が無言で描画を止める（＝T859の起票理由そのもの）。
- recommendation: `RideConditionBar`に`onNow`用の口を分けて`handleDynamicLayerNow`を配線する。`setDynamicLayerTargetTime`側も`steppedNow`と同じ刻みへ丸めるか理由を書く。配線しない判断なら関数とテストを撤去しコメントを実態へ直す（「テストだけが参照するコード」を残さない）。

**O-4** `page.tsx:784` / `page.tsx:1495` / duplication / **P3**
- summary: 同一の派生値（`routes.find((r) => r.id === editingRouteId) ?? null`）が`editingRouteForSplice`と`editingRoute`の別名で2回定義されている。
- failure_scenario: 片方の定義だけへ条件を足すと、地図側と操作側で編集対象の認識がずれる。

**O-5** `page.tsx:133-135` / `page.tsx:200` / 残骸コメント / **P3**
- summary: 「フロントは既存の距離計算ユーティリティを持たないためここに最小実装する」は`lib/geoDistance.ts`のimportがある現在成立しない。`// 環境グループの勾配gridFill。同じ理由で既定OFF。`の直下に対応するキーが無い。

**O-6** `page.tsx:1543-1552`（`handleApplySplice`）/ guard-latch / **P3**
- summary: 連打防止の`applyingRef`を立てた後の早期returnが1本あり、そこを通るとrefが二度とfalseに戻らずボタンが恒久的に無反応になる。
- evidence: `:1548`で`applyingRef.current = true`した後、`:1551-1552`の早期returnは`try`の外側にあり`finally`に到達しない。`setSplicing(true)`は`:1553`なので画面上は「処理中」にもならない。
- failure_scenario: 現状は到達不能と判断（`handleRoutesClear`は`routes`も空にするため先に return する）。ただしO-1の修正や`generatedConditions`の寿命変更で容易に到達可能になる。判断原則16に該当。

**O-7** `page.tsx:313,854-862` / 符号化の暗黙上限 / **P3**
- summary: 地図の帯idを`groupIndex * 100 + optionIndex`で符号化しており、1グループの選択肢が100を超えると別グループの帯を選んだことになる。ガードも表明も無い。

### consistency

**C-1** `docs/modules/frontend/page-composition.md:112-118` / docs↔実装＋検知器の母集団の穴 / **P2**
- summary: データフロー図が実装に存在しない`showGradientFill`を現行の分岐として書いている。しかも図がコードフェンス内にあるため、`review_checks.py`の死んだ識別子検知が構造的に見られない。
- evidence: 図中`dedicatedFetchAxes = [...] ∪ [showGradientFillなら勾配軸]`。実装（`page.tsx:1318-1321`）に`∪`の項は無い。`grep -rn "showGradientFill" frontend/src`はヒット0。検知器が0件を返す原因は`DOC_IDENT_RE`（`review_checks.py:662`）が**バッククォート付き**しか拾わないこと。フェンス内の図は識別子を裸で書く場所なので、**モジュール文書が構造を最も具体的に述べている箇所がまるごと検査の母集団から外れている**（設計原則12の趣旨に反する穴）。
- recommendation: (1) 図の該当行を実装へ直す。(2) `find_dead_identifier_refs`の母集団へコードフェンス内の行を含める。緩和を入れる場合は誤検知件数を実測してタスクエントリへ書く。

**C-2** `docs/modules/frontend/page-composition.md:269-276`（対`207-212`、実装`page.tsx:1956-1973`）/ docs↔実装・同一文書内の自己矛盾 / **P2**
- summary: 候補タブの「最速」の決め方について、同じ文書が2通りの説明を持ち、片方（273行）は実装と食い違う。
- evidence: `:273-275`「`is_fastest`が立つ候補は**順位番号の代わりに**「最速」と示し」／`:207-211`「一覧の中で所要時間が最小の候補に「最速」…**基準線は一覧の中だけで決める**」。実装は順位番号を常に出し、`fastestRouteIdInList`のときだけバッジを追加する。`routeTabLabel.ts:30-41`のdocstringが「**backendの`is_fastest`は見ない**」と明記。207-211が正。関連して`backend/app/domain/route.py:136-137`の`is_fastest`コメントも既に成立しないフロント挙動を述べている。
- recommendation: 273-275を207-211へ揃える。`domain/route.py:136-137`も訂正する。

**C-3** `useDynamicWeatherLayers.test.ts:395-412` / テストが実UIの契約を検証していない / **P2**
- summary: 「「今」ボタンで追従へ戻る」というテスト名でありながら、実UIの「今」ボタンが呼ばない関数を直接叩いており、O-3の未配線を隠している。
- evidence: `:404`が`result.current.handleDynamicLayerNow()`を直接呼ぶ。実UIの「今」は`setPinnedTargetTime`側へ入る。この2つは正反対の効果を持つ。
- failure_scenario: 現に起きている（「今」を押しても追従へ戻らない）。テストはgreenのままなので、この乖離はテストからは永久に見えない。

**C-4** `page-composition.md:224`および`302-310`（実装`page.tsx:1818-1843`、テスト`page.test.tsx:1401`）/ docs↔実装（UI配置）/ **P3**
- summary: 「このルートを編集」の置き場について、文書・テスト名・実装の3つが揃っていない。文書は「候補の中身」「ヘッダ操作枠はGPX出力とクリアの2つのみ」と書くが、実装はヘッダ操作枠の先頭に置いている。テストは配置を一切検証していない。

**C-5** `hooks/useCopyToClipboard.ts`（テストファイル無し）/ 実装↔テスト / **P3**
- summary: 新設フックの存在理由そのもの（`navigator.clipboard`がundefinedのときの**同期**TypeErrorをtryで受ける）が、テストで固定されていない。
- failure_scenario: 将来「`try`は冗長」として`.catch()`だけへ整理されると、httpのIPアクセスでコピーボタンが無反応に戻る。この環境は開発機の実機確認で踏みにくい。

**この担当シャードの傾向（前回比、S7担当の所見）**:
- **規模はほぼ横ばい**: `page.tsx`は2,490→2,513行（+23）、state宣言は43→45（+2）。T843で6本増えたが相殺されており、前回指摘の「state増殖」自体は悪化していない。
- **前回指摘「レンダー本体で毎回新規生成してエフェクトを毎回発火させる」は解消側**: `candidateShapes`・`splicedShape`・`spliceGroups`・`spliceStretchFeatures`はすべて`useMemo`済み。**再発なし**。
- **構造仕様1も遵守**: `routeSplice.ts`は集合演算と座標一致判定のみ、`difficultyLoadBar.ts`は表示倍率のみ。
- **代わりに増えたのは「状態の寿命」と「時間の扱い」の欠陥**: 今回のP1 3件はいずれも「ある機能が持ち込んだ状態・時刻が、別機能の前提を無言で書き換える」型。個々のモジュールは綺麗だが、`page.tsx`をハブとした状態の**寿命と所有者**の設計が追いついていない。
- **検知器の穴が1つ**: モジュール文書のコードフェンス内が死んだ識別子検知の母集団外。文書がデータフローを最も具体的に書く場所なので、費用対効果が高い修繕対象。

---
