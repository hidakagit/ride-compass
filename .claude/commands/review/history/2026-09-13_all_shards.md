# 統合レビュー（2026-09-13）シャード別の生出力

[2026-09-13_all.md](2026-09-13_all.md) のPhase 3（overall）・Phase 5（consistency）を、
ドメインシャードごとに1つのAgentへ両レンズの観点を渡して実施した際の出力をそのまま連結する。
統合後の判断・重複統合・矛盾解消は本体の結果ファイル側にある。ここは**個票が後から
対象を指せるようにするための保存**であり、重複・矛盾を含んだままの一次出力である。

---

## S1a: backend/app/domain 中核4ファイル

対象: `routing.py`・`evaluation.py`・`cycling_speed.py`・`traffic.py`
（`road_graph_engine.py`・`evaluation_service.py`・該当テスト・`docs/modules/backend/*`・
`docs/architecture.md`まで辿って裏取り）

### overall

- file: backend/app/domain/cycling_speed.py / line: 37, 124-189 / category: 契約の取りこぼし（入力域と解の域の不一致） / severity: P1 / summary: 速度の二分法が`[WALKING_SPEED_KMH=4.5, MAX_DESCENT_SPEED_KMH=45]`km/hで挟むのに、APIは`assumed_speed_kmh`を最大60km/hまで受ける（`domain/wind.py:17 MAX_ASSUMED_SPEED_KMH=60`、`api/routers/routes.py:175`）ため、45km/hを超える巡航速度は平地・無風でも45km/hへ黙って切り詰められる / failure_scenario: 利用者が巡航50km/hで生成すると、`speed_ms`は上限12.5m/sで収束し（実測見積: 50km/hに要るホイール出力579Wに対し12.5m/sの必要出力431W、`too_fast`が全反復でFalse）全区間45km/hになる。所要時間が約11%（60km/h指定なら33%）過大に出て、コストの下地＝所要時間なので**候補の順位付けそのもの**もその前提で決まる。モジュール冒頭とSPEED_SOLVE_ITERATIONSのコメントが掲げる「平地・無風で巡航速度に一致する」という不変条件が、正規のAPI入力域の一部で成立していない。

- file: backend/app/services/road_graph_engine.py / line: 1227, 1482 / category: 局所最適の連鎖（コスト式の逆算が新しい加算項を勘定していない） / severity: P2 / summary: 難易度の逆算`(node_cost/node_seconds - 1)/P*100`は、ターンの待ちが`cost`・`seconds`の**両方へ割増なしで同額加算される**（routing.py:839-843, 1034-1037）ため、`Σ(travel·d)/(Σtravel+Σturn)`となり、ターンの多い候補ほど難易度が低く出る / failure_scenario: 30km周回で右左折100回×平均8秒＝800秒、走行5,400秒なら逆算難易度は真値の約87%。折返し点の並び（`pareto_layer_index`の第2指標）と目的地ルートの候補順で、**曲がりが多い候補が「易しい」側へ系統的に寄る**。engine:1149のdocstringは「往路の時間加重平均difficulty（コスト式の逆算、overall_difficultyと同じ物差し）」と書いているが、ターンぶんの希釈は物差しの違いとして書かれていない。

- file: backend/app/domain/cycling_speed.py / line: 102-121 / category: デッドコード＋同一式の二重実装 / severity: P2 / summary: `_resistance_force`はリポジトリ全体（app/scripts/tests/benchmarks）で1件も呼ばれておらず、同じ抵抗力の式が`speed_ms`の反復（171-185行）へ手で展開された形で二重に存在する / failure_scenario: 転がり抵抗や空気抵抗の式を変えるとき、`_resistance_force`（読むと「これが正本」に見える）だけを直しても探索の所要時間は1秒も変わらない。逆に`speed_ms`側だけ直すと、2つの式が黙って食い違ったまま残る。

- file: backend/app/domain/routing.py / line: 59-106 / category: 本番で到達しない分岐（契約の反転） / severity: P2 / summary: `build_lazy_road_graph`の`edge_cost_by_id`（並行Edgeをcost最小で解消する経路）に本番の呼び出し元が存在しない。`road_graph_engine.py:2122`が「本関数は`build_lazy_road_graph`へ`edge_cost_by_id`を渡さず、決定的フォールバック…」と明記しており、渡すのは`tests/test_routing.py:547,570`だけ / failure_scenario: docstringは「省略時（コストがまだ判明していない場面、**主にテスト**）」と書いており実態と逆（本番が常に省略側、テストだけが指定側）。並行Edgeの選び方を直そうとした人がcost最小の分岐を改良しても、本番の挙動は1ミリも変わらない。

- file: backend/app/domain/routing.py / line: 140-179, 226-251 / category: 新旧設計の残骸 / severity: P2 / summary: `build_csr_structure(reverse=True)`／`build_search_graph_statics(reverse=True)`の転置CSR経路に本番の呼び出し元が無い。後ろ向き木は`TurnExpandedStructure.reverse_transitions()`（640-655行、engine:1446の`reverse=True`）で遷移を反転しており、転置CSRを使わない / failure_scenario: 145-148行のdocstringは「転置CSR上で…Dijkstraをかけると…（後ろ向き木、`RoadGraphEngine.select_via_nodes`参照）」と、いま存在しない消費関係を指している。`select_via_nodes`の後ろ向き木を直そうとした人がこの関数を読み、触っても何も起きない。

- file: backend/app/domain/routing.py / line: 1065-1075 / category: テストのみが参照するコード / severity: P3 / summary: `node_costs_from_state_costs`の呼び出し元は`tests/test_routing_turn_expanded.py:114`だけで、本番のNode畳み込みは`build_turn_expanded_tree`内のlexsort（943-958行）が別実装で行っている / failure_scenario: 畳み込みの規則（同点のときどの状態を採るか）を変えるとき、テストが通っているのに本番は旧規則のまま、という食い違いが起きる。`docs/modules/backend/routing-engine.md:626`が「Nodeごとの値（…、`node_costs_from_state_costs`）も持つ」と書いているため、読み手はこちらが本体だと誤解する。

- file: backend/app/domain/evaluation.py / line: 672-689, 745-750 / category: ロジック重複 / severity: P3 / summary: `axis_weighted_sums`の項の作り方（`np.where(valid, arr*weight, 0)`／`np.where(valid, weight, 0)`＋Neumaier加算）が`compose_costs_from_axis_matrix`の本体と同じ式で二重に書かれている / failure_scenario: 「データ無しは除外し残りの重みで再正規化」の扱い（例: inf・負の重み）を変えるとき、片方だけ直すと`static_sums`へ畳んだ軸と毎回足す軸で違う規則が適用され、時刻ビンごとのコストが静かにずれる。docstring自身が「同じ式で保つ」と注記しており、重複の存在は認識されている。

- file: backend/requirements.txt / line: 27 / category: 不要になった依存 / severity: P2 / summary: T790でscipy/rustworkxをnumbaへ置き換えた結果、`import scipy`は`backend/app`・`backend/scripts`・`backend/tests`に1件も残っておらず（benchmarks/bench_t790_turn_expanded.pyのみ）、それでも`scipy==1.18.1`が本番イメージの依存に残っている / failure_scenario: 直下の28-31行のコメントが「コストを辺の静的な属性とみなすライブラリ（rustworkx・scipy）では表せないため自前で書く」と説明しているのに、そのscipyが依存に残ったままで、読み手はどちらが現役か判断できない。本番イメージのビルド時間・サイズも払い続ける。

- file: backend/app/services/evaluation_service.py / line: 29-84 / category: 本番呼び出し元の無いservice関数 / severity: P3 / summary: `evaluate_graph`は`compute_edge_costs_bulk`への素通しラッパーで、本番の呼び出し元が無い（`api/`からの参照は同ファイルの`load_route_preference`のみ。engine:700-702が「本エンジンから呼ばない」と明記）。ラッパー自身の存在理由はテスト（`test_evaluation_service.py`）とベンチマークだけ / failure_scenario: パリティ用オラクル（`compute_edge_costs_bulk`）は残す価値があるが、そのうえにservice層の素通し1枚が乗っているため、引数を1つ増やすたびに`compute_edge_cost`／`compute_edge_costs_bulk`／`evaluate_graph`の3箇所を揃える必要が生じる（`travel_speed_ms`が実際に3箇所へ追加されている）。

### consistency

- file: backend/app/domain/routing.py / line: 4-7 vs 14-19 / category: モジュールdocstring内の自己矛盾（削除された方針の残存） / severity: P1 / summary: 冒頭が「探索アルゴリズム自体は独自実装せず、標準的なグラフアルゴリズムライブラリの実装をそのまま利用する」と宣言し、10行下で「ライブラリの実装を使わないのは、到達時刻をラベルとして持ち回るため…自前で書く」と正反対のことを書いている / failure_scenario: このファイルを初めて読む人（または将来の自分）が冒頭だけを根拠に「numbaの自前Dijkstraは方針違反だからライブラリへ戻そう」と判断しうる。T790が捨てた前提（コストが辺の静的属性）へ戻す提案が、正本らしい記述に支えられて出てくる。

- file: docs/modules/backend/evaluation-scoring.md / line: 209-211 / category: 実装と正反対のdocs記述（docs間の相互矛盾） / severity: P1 / summary: 「並行Edge（同一Node間の複数Edge）はコストが判明済みのため`domain/routing.py: build_lazy_road_graph`が「cost最小を採用」する」と書いているが、本番は`edge_cost_by_id`を渡さずedge_id昇順フォールバックで解消する（engine:2122・2139）。同じ事実を`docs/modules/backend/routing-engine.md:603-606`は「edge_idの昇順で先頭を採用する決定的な選択で解消する（タイル集合キーでキャッシュするための制約）」と正しく書いており、2つのモジュール文書が食い違っている / failure_scenario: 「並行Edgeのうち0次フィルタで除外される側が選ばれる」不具合（T537が意図的に受け入れた既知の制約）を調査する人が、evaluation-scoring.md を信じて「cost最小なら許可される側が選ばれるはずだ」と前提を置き、実在しない経路をデバッグする。

- file: backend/app/domain/routing.py / line: 591-596 / category: 廃止された換算を語るdocstring / severity: P1 / summary: `TurnCostSpec`のdocstringが「費用を秒で持ち、探索へ渡すときに巡航速度でm換算する（探索のコストが距離の単位のため、「右折1回＝何m遠回りするのと同じか」として距離と直接比較できる）」と書いているが、T790以降コストは秒で、`turn_seconds`は`next_g = g + cost + wait`（840, 1196行）としてそのまま秒で加算される。m換算はコード上どこにも存在しない / failure_scenario: ターンの費用を較正する人（T801が予定されている）が「m換算の係数を探す」ところから始め、見つからないまま換算を新設しかねない。あるいは「秒→m換算が入っている」前提で`left_seconds`等の値を巡航速度で割った量として調整し、桁を外す。

- file: backend/app/domain/evaluation.py / line: 84-85 / category: 廃止された契約を語るdocstring / severity: P2 / summary: `EdgeCostResult`のdocstringが「costは距離ベース（メートル相当、小さいほど良い＝**Route Engineが最短経路探索にそのまま使える単位**）」と書いているが、探索が読むのは`compose_costs_from_axis_matrix(base=travel_seconds)`が返す秒のコスト配列で、`EdgeCostResult`は探索へ一切渡らない（本番の消費者は無く、パリティテストのオラクルのみ） / failure_scenario: 探索コストの単位を確認しようとした人がこのモデルを起点に読み、「探索は距離ベース」という前提でターン費用や停止の待ちの妥当性を評価する。

- file: backend/app/domain/evaluation.py / line: 241-244 / category: 成立しなくなった性能上の前提 / severity: P2 / summary: `compute_edge_cost`のコメント「この関数はlazy評価で探索のホットパス（訪れたEdgeごとに最大24回）になりうるため、Pydanticバリデーションのコストを避ける」は、現在の呼び出し元がテストのみ（`tests/test_evaluation*.py`）で成立しない。「最大24回」はDijkstra24本時代の数字 / failure_scenario: この関数を読む人が「探索のホットパスだから触ると遅くなる」と判断し、可読性を上げる整理や検証の追加を避け続ける。実際にはオラクル専用で、性能上の制約は無い。

- file: backend/app/domain/routing.py / line: 195, 876, 895 / category: 実在しない識別子への参照 / severity: P2 / summary: `ShortestPathTree`はコードから撤去済み（リポジトリ全体で`docs/tasks/T531.md`・`T557.md`の経緯記述にしか残っていない）のに、3箇所が現存する型のように参照している（「`ShortestPathTree.length_m`…に使う」「`ShortestPathTree`と違い」「`ShortestPathTree`と同じ理由」） / failure_scenario: `TurnExpandedTree`が「起点Nodeのコスト0を持たない」理由を確かめようとした人が、比較対象として挙げられている型をgrepしても見つからず、「なぜ起点を自分で上書きする必要があるのか」の根拠に辿り着けない。

- file: backend/app/domain/cycling_speed.py / line: 18 / category: 実装と食い違うモジュールdocstring / severity: P2 / summary: 冒頭が「速度の逆算は`v`の3次方程式になるため**ニュートン法**で解く（`speed_ms`）」と書いているが、`speed_ms`は二分法で、そのdocstring（137-138行）は「ニュートン法は抵抗力が0を跨ぐ下り坂で発散しうるため、区間を確実に狭める方を採る」と明示的にニュートン法を退けている / failure_scenario: 収束が遅いと感じた人が冒頭を信じて「ニュートン法の初期値を改善する」方向で手を入れ、実際には存在しない実装を探す。あるいは二分法を「暫定実装」と誤解してニュートン法へ戻し、下り坂で発散させる（退けた理由が冒頭には無い）。

- file: backend/app/domain/traffic.py / line: 1-11 / category: ファイルの責務を語るdocstringが現在の中身を覆っていない＋消費者の誤記 / severity: P2 / summary: (a) 冒頭は「静的道路属性の派生分類。すべて純関数・unknown安全」と宣言するが、このファイルは現在`STOP_SECONDS`/`stop_seconds`（走行モデルへ足す時間損失）と`HIGHWAY_RANK`/`highway_rank`（ターン費用の階級比較）という**所要時間モデルのパラメータ**を持つ。(b) 「自転車インフラは正規化フラグ材料4種…domain/evaluation.pyの軸材料合成が**直接参照する**」は誤りで、実際の消費者は`domain/material_catalog.py:416-445`（evaluation.pyがrecipeから取るのは`tag_value_is`だけ）。同じ古い主張が`material_catalog.py:416-417`にも残っている / failure_scenario: 自転車インフラ材料の抽出を変える人がevaluation.pyを開いて該当箇所を探し、見つからないまま「材料合成が消えた」と誤認する。また、走行モデルの定数を探す人はtraffic.pyを「静的属性の分類器」と読んで素通りする。

- file: docs/modules/backend/static-road-attributes.md / line: 369 / category: 対応する記述自体が無い（新設物の記載漏れ） / severity: P2 / summary: traffic.pyを所管するモジュール文書のファイル表が「停止要因POI・補給休憩POIの分類、交差点判定の空間マッチ半径・次数しきい値」までしか書いておらず、T790で同ファイルへ入った`STOP_SECONDS`（停止1回あたりの秒）と`HIGHWAY_RANK`が載っていない。routing-engine.md側も`highway_rank`を1回名指しするだけで`STOP_SECONDS`には触れず、両モジュール文書のどちらにも所要時間への効き方の記述が無い / failure_scenario: 「信号1回で何秒足しているのか」を確認したい人が、モジュール文書を両方読んでも辿り着けずコードをgrepすることになる。T806（暫定値を管理画面から変える）に着手する人が、較正対象の一覧を作るのにタスクファイルを漁る必要がある。

- file: docs/modules/backend/routing-engine.md / line: 322, 626 / category: 名指しされた識別子と実装の関係が違う / severity: P3 / summary: 「Nodeごとのコストは、そのNodeへ入る区間の最小を採る（`node_costs_from_state_costs`）」と書かれているが、`build_turn_expanded_tree`はこの関数を呼ばずlexsortで自前に畳んでおり（routing.py:943-958）、当該関数の呼び出し元はテストだけ / failure_scenario: Node畳み込みの規則（到達不能の扱い・同点タイブレーク）を追う人が、実際には使われていない関数を読んで結論を出す。

- file: docs/architecture.md / line: 21 / category: 存在しない協調関係 / severity: P2 / summary: 「`RoadGraphEngine`（…`GraphService`・**`EvaluationService`**・`domain/routing.py`の探索…を使う）へ委譲する」と書いているが、`road_graph_engine.py:700-702`が「evaluation_service.evaluate_graphは本エンジンから呼ばない」と明記しており、実際にエンジンが使うのは`domain/evaluation.py`の静的スコア行列＋`compose_costs_from_axis_matrix` / failure_scenario: アーキテクチャ図を頼りに評価経路を変更する人が`EvaluationService`へ手を入れ、本番のルート生成には何の影響も出ない（そしてパリティテストだけが壊れる）。

- file: backend/app/services/road_graph_engine.py / line: 26-27, 13, 1149 / category: T790で成立しなくなった記述の残存 / severity: P2 / summary: モジュールdocstringが「風は出発時点の起点付近の風をルート全体に一様適用する（**探索中は到達時刻が未確定のため**、区間ごとの推定到達時刻の風は使わない）」と書いているが、現在は`_LegCostComposer.time_varying`（349行）が風の時別系列があれば常に時刻ビンで合成し、探索は経過時間ラベルでビンを引く。同docstringの13行目と1149行目には`build_turn_expanded_tree`の実装として「scipy」が残っている（実装はnumba） / failure_scenario: 「風は出発時点で固定」という前提で、到着予定時刻の風を扱う機能を検討した人が、すでに実装済みの機構を二重に作る。

- file: backend/tests/test_routing_turn_expanded.py / line: 148-161, 226-232 / category: 変更後の契約を検証していないテスト / severity: P2 / summary: `build_turn_expanded_tree`のテストは全て1次元コスト（`edge_seconds=cost`、`bin_seconds`既定=inf）で呼んでおり、**時刻ビン（2次元コスト）を渡す経路のテストが1件も無い**。時刻ビンのテストがあるのはA*側だけ（274-307行）。一方、本番の周回生成（`select_loop_turnarounds`、engine:1192-1197）と目的地ルートの前向き木（engine:1387-1391）はどちらも`cost_bins_lazy`＋`bin_seconds`で木を張る＝T790の中核経路 / failure_scenario: `_turn_expanded_dijkstra`の`time_bin`クランプ（828-832行）や`arrival[nxt] = travelled + edge_seconds[time_bin, nxt] + wait`（843行）を壊しても、routing.pyのテストは全件緑のまま通る。実害は「風を無視した経路が返る」という値の劣化で、例外も候補0件も起こさないため気づく契機が無い。

- file: backend/app/domain/routing.py / line: 918-919 / category: ガードの無い暗黙の呼び出し制約 / severity: P2 / summary: `build_turn_expanded_tree`のdocstringが「**逆向きの木は時刻ビンを使えない**——目的地から遡るため各状態の到達時刻が決まらない。呼び出し元は1本のビンで呼ぶこと」と文章でだけ要求しており、`reverse=True`かつ2次元コストを弾く表明が実装に無い（現行の呼び出し元 engine:1443-1447 は正しく1本で呼んでいる） / failure_scenario: 後ろ向き木にも風の時間変化を入れたくなった人が素直に`cost_bins_lazy`を渡すと、`arrival`が「目的地からの残り時間」であるためビンが逆向きに引かれ、例外もNaNも出ないまま**時刻が反転した風で評価した経路**が返る。上の「2次元経路のテストが無い」と重なって、CIでも検出されない。

- file: backend/app/domain/traffic.py / line: 7-10 / category: 要素の数え上げ（増えた瞬間に嘘になる文） / severity: P3 / summary: 「車ストレスはAXIS_DEFINITIONSの内部軸**5つ**+公開軸**1つ**の階層構造で再現している」「自転車インフラは正規化フラグ材料**4種**」と個数を書いている。軸はDBが正本で軸スタジオからデプロイ無しに増減できる / failure_scenario: 軸スタジオで`car_stress_*`の内部軸を1本足した運用者がいても、このコメントは更新されない（コード変更を伴わないため）。以後、読み手は実際の構成と違う数を前提にする。

- file: backend/app/domain/routing.py / line: 566 / category: 成り立たない前提を述べるコメント / severity: P3 / summary: `max_radius = max(len(index.buckets), 1) + 1` に「理論上到達しない安全弁（無限ループ防止）」とあるが、上限はバケット**数**で決まり、探索地点から最寄りバケットまでの**距離**（リング数）とは無関係。バケットが疎で遠い場合は到達しうる / failure_scenario: ノードが少数のセルに固まった小さなグラフで、数km離れた地点から`find_nearest_node_indexed`を呼ぶと、最寄りノードが存在するのにNoneを返す。呼び出し元は「道路網へスナップできない」として候補0件になり、原因が索引の打ち切りであることは記録に残らない。

補足（推測と事実の区別）: 「呼び出し元が無い」「テストが無い」はいずれも`backend/app`・`backend/scripts`・`backend/tests`・`backend/benchmarks`へのgrep結果に基づく事実。速度上限45km/hの数値見積もり（579W対431W）と難易度希釈の87%は、コード中の定数からの手計算による推定値で実測ではない。

---

## S2: backend/app/services（8ファイル）

`domain/routing.py`・`evaluation.py`・`cycling_speed.py`・`traffic.py`・`wind.py`、
`api/routers/routes.py`、`backend/tests/`、`docs/modules/backend/routing-engine.md`・
`docs/architecture.md`・`docs/tasks/T790.md`まで追跡して裏取り。

### overall

- file: backend/app/services/road_graph_engine.py / line: 254-258, 457-459, 557-559 / category: デッドコード（未読フィールド） / severity: P2 / summary: `LegCostArrays.passage_hours`・`headwind_ms`・`crosswind_ms`は書き込まれるだけで、app配下・backend/tests・frontendのどこにも読み手が無い / failure_scenario: 機能影響は無いが、フィールドdocstring「所要時間の算出（走行モデル）が使う」は嘘（走行モデルは`_travel_time_seconds`の引数で受け取る）。実体は`full_edge_row`長のfloat配列3本で、`_LegCostComposer._cache`に合成済みレグの数だけ保持される（本番規模56万Edgeなら1レグあたり約13MB）。読む人は「風の成分が下流で使える」と誤解し、下流に足そうとして二重の経路を作る。

- file: backend/app/services/road_graph_engine.py / line: 393-402, 510-516 / category: 読まれていない引数 / severity: P2 / summary: `compose(anchor=...)`は`anchor is None`しか見ておらず、座標の値は`_compose_at`で一切使われない（`DynamicAxisRequestContext`は`bearing_deg`/`start`/`passage_hours`のみ）。docstringは「`anchor`から`direction=+1`なら離れていくレグとして…合成する」と位置が効くかのように述べる / failure_scenario: `select_via_nodes`は行1438で`destination`をanchorに渡しており、読む人は「後ろ向きレグは目的地の風で評価される」と解釈する。実際は起点1地点の時別予報しか使わないため、風の空間変化を入れる改修でanchorを差し替えても結果が1ミリも変わらず、原因の切り分けに時間を失う。

- file: backend/app/services/road_graph_engine.py / line: 374-377 / category: 規則の二重持ち（静かな欠落） / severity: P2 / summary: 停止の待ちが読む材料idを`f"poi_{kind}_per_km"`とインラインで組み立てている。同じ規則は`domain/traffic.py:154-161 stop_count_material_ids()`が「単一ソース」として持ち、`route_facing_material_ids`はそちらを参照している / failure_scenario: 材料idの綴りを`traffic.py`側で変えると（`route_facing_material_ids`は自動追従するため列は揃ったまま）ここだけが`material_arrays.get()`でNoneを引き、全区間の停止の待ちが無言で0秒になる。全ルートの所要時間と探索コストが短くなるが例外は出ず、`test_candidate_aggregates_stop_density_from_path_edges`は軸のスコアしか見ていないため落ちない。

- file: backend/app/services/road_graph_engine.py / line: 1479-1480 / category: 局所最適の不整合（ランキング前の打ち切り） / severity: P2 / summary: via-node候補は`np.flatnonzero(within_stretch)[:MAX_VIA_NODE_CANDIDATES_EXAMINED]`でNode index順に2,000件へ切ってからパレート層・difficultyで並べる。定数の宣言（行221-223）は「`MAX_RING_CANDIDATES_EXAMINED`と同じ役割」と述べるが、周回側（行1249）は`np.lexsort(...)[:MAX_RING_CANDIDATES_EXAMINED]`で**並べてから**切っている / failure_scenario: 都心の目的地ルートのように伸び率1.3倍以内のNodeが2,000件を超える範囲では、Node index（タイル結合順＝経路品質と無関係）だけで候補集合が決まり、真のパレートフロント上の代替経路が選定前に落ちる。しかもINFOログは打ち切り後の件数を`within_stretch=%d`として出す（行1559-1562）ため、運用側から打ち切りの発生自体が見えない。

- file: backend/app/services/road_graph_engine.py / line: 1937-1959 / category: 無言のフォールバック / severity: P2 / summary: `_turn_seconds_along`は経路上の1本でも`(from,to)`のNode対が`edge_index_by_node_pair`に無いと、そこで`return 0.0`して**経路全体**のターンの待ちを捨てる。ログは一切出さない / failure_scenario: `build_traced_from_edge_ids`（区間の乗り換え）はクライアント由来のedge_id列を受け、並行Edgeのうち探索用グラフに載らなかった側が混ざりうる。そのとき「組み合わせたルート」だけ`estimated_duration_seconds`からターン分（都市部30kmで数分〜十数分規模）が丸ごと消え、元候補や`is_fastest`基準線より不当に速く見える。docs/logging.mdの「異常は常時WARNING以上」にも反する。

- file: backend/app/services/road_graph_engine.py / line: 1909, 2036-2037 / category: 二重の計算モデル / severity: P2 / summary: 候補の`estimated_duration_seconds`は走行モデル＋停止＋ターン（`travel_seconds_full`）から出るのに、区間の`estimated_arrival_time`は`cumulative_km / self._assumed_speed_kmh`という平坦な仮定速度のまま。T790で時間が単位になった後も片方だけが取り残されている / failure_scenario: 勾配・向かい風のある30km周回で、モデルの所要時間が105分でも最終区間の「到達予想」は90分（30km÷20km/h）を指す。frontend/src/app/page.tsx:1960の区間「到達予想」とRouteAxisProfileの所要時間が同一候補について別の終了時刻を示し、どちらが本当か利用者が判断できない。

- file: backend/app/services/road_graph_engine.py / line: 1931 vs 1979 / category: 効かない防御 / severity: P3 / summary: `_estimate_duration_seconds`は`leg_index < len(context.legs)`でガードするが、同じ`leg_of_edge`を使う`_build_segment_details`は行1979で無防備に`context.legs[leg_index]`を引く。`_build_candidate`は1892（segments）→1909（duration）の順に呼ぶため、このガードは決して発火しない / failure_scenario: レグ番号を振る側がlegsを用意し忘れた実装ミスは、ガードの無い`_build_segment_details`でIndexErrorとして500になる。ガードの存在は「legs不足は吸収される」という誤った安心を与え、`build_traced_from_edge_ids`のようにレグを自前で用意する新経路を足すときの検討を飛ばさせる。

- file: backend/app/services/road_graph_engine.py / line: 1941 / category: デッドコード / severity: P3 / summary: `if structure is None or lazy_graph is None`は、いずれも`_RoadGraphContext`の非Optionalフィールドに対する判定で到達しない / failure_scenario: 読む人が「turn_structureはNoneになりうる」と解釈し、他の箇所にも同種のNoneチェックを増やす。

- file: backend/app/services/road_graph_engine.py / line: 1433, 1976 / category: カプセル化 / severity: P3 / summary: `_LegCostComposer`の私有属性（`_score_matrix`・`_weights`・`_lens_axis_id`）を、クラス外の`select_via_nodes`・`_build_segment_details`から直接読んでいる / failure_scenario: composerの内部表現を変えた瞬間に、関係の無さそうな2箇所が同時に壊れる。公開アクセサが無いため「内部を変えてよい範囲」が誰にも分からない。

- file: backend/app/services/road_graph_engine.py / line: 419-421, 466-471 / category: ログの誤記 / severity: P3 / summary: 風の時別系列が無いとき、キャッシュキーは`("snapshot",)`のみのため`compose("inbound", ...)`が`compose("outbound", ...)`のオブジェクトをそのまま返す。`compose_leg_costs`のINFO行は既存オブジェクトを返す経路では出ず、出るときのlabelも最初の呼び出しのもの / failure_scenario: 風データが無い環境のログにレグが1本しか現れず、「復路レグの合成が走っていない＝バグ」と誤診する。

### consistency

- file: backend/app/services/road_graph_engine.py / line: 26-27 / category: 削除された事実の残存（モジュールdocstring） / severity: P1 / summary: 「風は出発時点の起点付近の風をルート全体に一様適用する（探索中は到達時刻が未確定のため、区間ごとの推定到達時刻の風は使わない）」は、同じファイルの時刻ビン機構（283-472・1174-1179・1219-1222）と正面から矛盾する / failure_scenario: エンジンの風の扱いについて最初に読まれる記述が実装の逆を述べている。時刻依存の軸（降雨・渋滞）を足そうとする人が「この探索は到達時刻を持てない」と結論し、撤去済みの静的推定を作り直す。

- file: docs/modules/backend/routing-engine.md / line: 90（および54） / category: 同一文書内の相互矛盾＋撤去済み機構の名指し / severity: P1 / summary: 行90「起点の時別風予報が無い、**または風に依存する公開軸の重みが0の場合**はスナップショット1本を共有する…ただし`lens_axis_id`が風に依存する公開軸なら重み0でもレグごとに合成する」が、同じ文書の行54「風に依存する軸の重みが0でも時刻で引き直す」および実装（road_graph_engine.py:346-349 `self.time_varying = wind_series is not None`）と矛盾。`_lens_axis_id`は現在`_active_material_ids`でしか使われず、時変化判定には一切関与しない。T790.md:43はこの重み依存を「直した欠陥」として明記している / failure_scenario: 「風の設定が効かない」を調べる運用者が、風の重みを0にすれば時変化合成が止まると信じて切り分けを誤る。さらに悪い形として、保守者がこの記述に合わせて重み判定を「復元」し、T790が直した「重み0で速度計算まで時刻固定に落ちる」不具合を再投入する。

- file: docs/modules/backend/routing-engine.md / line: 66 / category: 実在しない識別子 / severity: P2 / summary: `LegCostArrays`のフィールドとして`contribution_arrays`を名指ししているが、そのような属性は存在しない（T790で`weight_sums`＋`axis_contributions_at`の遅延計算へ置き換わった） / failure_scenario: 軸別寄与度の表示を足す人が`contribution_arrays`を探して見つからず、bbox全体ぶんの寄与度配列を作り直す——遅延化の最適化（経路上の数百行しか読まないという前提）を打ち消す。

- file: docs/modules/backend/routing-engine.md / line: 31-37 / category: 置き換えられた機構の残存 / severity: P2 / summary: 概要段落が「風は、各Edgeの通過予定時刻を『基準点からの直線距離×迂回率÷仮定巡航速度』で探索前に静的に推定し」と述べるが、直後の「レグ内の時刻ビン」節（40-55）は実際の経過時間で引くと述べる。静的推定は今や目的地モードの後ろ向き木が未到達区間へ使うフォールバックだけ / failure_scenario: 同じ文書が同じ話題について2つの異なる機構を述べており、どちらが現在の設計か読者が決められない。片方だけを根拠に「推定精度を上げれば風が正確になる」というタスクを起票すると、実際には主経路に効かない改修になる。

- file: docs/architecture.md / line: 312-313 / category: 置き換えられた機構の残存 / severity: P2 / summary: 「風の探索コストは、Edgeごとの通過予定時刻（基準点からの直線距離×迂回率÷仮定巡航速度）で起点の時別予報から引き」——上と同じ撤去済みの機構を、CLAUDE.mdが横断制約の正本と定めている文書が述べている / failure_scenario: architecture.mdは「コードからは導けない制約」を読みに来る文書のため、ここの記述は疑われずに前提として使われる。時刻依存の新機構を設計する人が、探索が経過時間を持てないという誤った制約の下で設計する。

- file: backend/app/services/road_graph_engine.py / line: 693-695 / category: 経緯化した誤ったコメント / severity: P2 / summary: `RoadGraphEngine._lens_axis_id`に「重み0の軸でも区間表示のために風の時変化合成を行う判定にだけ使う」とあるが、現在の用途は`_active_material_ids`のみ / failure_scenario: レンズ表示が欠けたときに、風の時変化合成側を疑って調べ始める。逆に`lens_axis_id`を消してよいか判断するとき、風への影響を心配して撤去できない。

- file: backend/app/services/road_graph_engine.py / line: 283-288 / category: クラスdocstringと実装の食い違い / severity: P2 / summary: `_LegCostComposer`のdocstringが snapshot 共有の条件に「風に依存する公開軸の重みが0」を挙げるが、60行下の`__init__`コメント（346-349）が明示的に否定し、実装もそうなっている / failure_scenario: クラスの入口の説明と実装が同じファイル内で矛盾しており、どちらが意図か分からないまま`time_varying`の条件を「整合させる」修正が入ると、走行モデルの風入力が重み0で固定に戻る。

- file: docs/modules/backend/routing-engine.md / line: 111 / category: 数え上げ＋事実誤り / severity: P2 / summary: 「`LoopRoutingEngine`という**7メソッド**の契約」と7件を列挙するが、Protocol（route_generator.py:146-182）は8件（`select_fastest_route`を含む）、route_generator.pyのモジュールdocstringは`build_traced_from_edge_ids`を含む9件を契約として記述する。docs/documentation.mdの「個数・全件の一覧を書かない」にも反する / failure_scenario: 別エンジンを実装する人がこの7件だけ満たして「契約を満たした」と判断し、基準線と区間の乗り換えが動かない実装を作る。

- file: backend/app/services/route_generator.py / line: 146-182 / category: Protocolの欠落 / severity: P2 / summary: `generate_spliced_route`が`self._engine.build_traced_from_edge_ids(...)`（行485）を呼び、モジュールdocstring（行42-45）も契約として明記しているのに、`LoopRoutingEngine` Protocolにこのメソッドの宣言が無い / failure_scenario: Protocolを満たす第2のエンジンを差し込むと、構造チェックも既存テスト（すべて具象の`RoadGraphEngine`を呼ぶ）も通過したうえで、利用者が初めて`spliced_edge_ids`を送った瞬間に`AttributeError`で500になる。

- file: backend/app/services/road_graph_engine.py / line: 1043-1045 / category: 成立しなくなった事実の残存 / severity: P2 / summary: `preview_segment`のコメント「road_graphエンジンは実測所要時間モデルを持たないため、他所と同じASSUMED_SPEED_KMHで概算する」は、走行モデル（`travel_seconds`、行372・1933で使用）が入った今は成立しない / failure_scenario: `/api/routes/preview`だけが勾配・風・路面を無視した所要時間を返し続ける（登坂区間で生成側が50分と言う経路を30分と表示する）。コメントが「モデルは無い」と断言しているため、直そうとする人がまず存在しないモデルを作りに行く。

- file: docs/modules/backend/routing-engine.md / line: 102 / category: 存在しないログ項目の名指し / severity: P2 / summary: 「`compose_leg_costs`ログ（レグ・迂回率・通過予定時刻の範囲・合成時間）で確認できる」とあるが、実際の出力は`leg=%s mode=%s bins=%d compose_ms=%d`（road_graph_engine.py:467-471） / failure_scenario: 迂回率の学習が効いているかを本番ログで確かめようとした運用者が、文書どおりのフィールドを探して見つからず、「ログが出ていない＝機構が動いていない」と誤判断する。

- file: backend/app/domain/cycling_speed.py / line: 18 / category: 同一ファイル内の矛盾 / severity: P2 / summary: モジュールdocstringが「ニュートン法で解く」と述べるが、`speed_ms`のdocstring（136-137）と実装（171-187）は二分法。routing-engine.md:14は正しく「二分法」と書いている（S1aと重複） / failure_scenario: 走行モデルの速度化を試みる人がファイル頭の記述を信じ、12回の二分ループをニュートン法へ「戻す」——そのファイル自身が警告している下り坂での発散を再現し、急勾配の区間で所要時間が壊れる。

- file: backend/app/services/road_graph_engine.py / line: 344-345 / category: 存在しない引数の名指し / severity: P3 / summary: `detour_ratio`のコメントに「`compose`の引数で個別に上書きできる」とあるが、`compose`（393-401）にその引数は無い / failure_scenario: レグごとに迂回率を変える改修で、既に存在すると書かれている引数を探して時間を失う。

- file: docs/modules/backend/routing-engine.md / line: 98 / category: 実装と食い違う記述 / severity: P3 / summary: 「復路レグ・目的地ルートの後ろ向きレグは、直前に求めた往路木から測った中央値」を使うとあるが、周回の復路レグ（road_graph_engine.py:1219-1222）は`distance_km / speed_kmh`で合成し`detour_ratio`を読まない / failure_scenario: 迂回率の学習値が周回の風評価に効くと信じて較正すると、周回側では何も変わらない。

- file: backend/app/services/jma_amedas_service.py / line: 16 / category: 死んだ参照 / severity: P3 / summary: 「CLAUDE.md「JMA気象データ連携・キャッシュ基盤」節参照」とあるが、CLAUDE.mdにその節は存在しない（内容はdocs/tasks/T387.mdにある） / failure_scenario: Redis保持の設計理由を確かめたい人がCLAUDE.mdを全文読んで見つけられず、根拠が無いものとして別の保持層へ移す判断をする。

- file: docs/tasks/T790.md / line: 32 / category: 上書きされた実測値の残存 / severity: P3 / summary: 完了サマリが「本番レスポンスは段階2a比で+2,400ms（3,105→5,483ms）」と書くが、同ファイルの計測表（809-810）とdocs/improvement-plan.md:1239は最終値4,675msを示す / failure_scenario: 最初に読まれるサマリだけが最適化2回目の前の数字で、T802の優先度を17%過大な劣化量から見積もる。

- file: docs/modules/backend/routing-engine.md / line: 430-437付近 / category: 対応する記述が無い / severity: P3 / summary: via-node選定の手順1〜3を説明しているが、`MAX_VIA_NODE_CANDIDATES_EXAMINED`による候補打ち切り（road_graph_engine.py:1480）に触れていない。周回側の`MAX_RING_CANDIDATES_EXAMINED`も同様 / failure_scenario: 「伸び率以内なら全Nodeが候補」と読める記述しか無いため、上のoverall指摘（ランキング前の打ち切り）が文書上どこからも見えず、代替経路の品質が想定より低い原因に誰も辿り着けない。

補足（事実として確認したこと）:
- T790の性能最適化には本番実測の裏付けがある（docs/tasks/T790.md:297-370）。「実測根拠が無い最適化」は見つからなかった。
- レイヤー構造の逸脱（servicesがinfrastructureを直接組み立てる／DI工場の迂回）は見つからなかった。`region_service.py:59-68`の`get_session_factory()`直呼びはHTTP応答後も走るバックグラウンド構築のため意図的で、docstringに理由が書かれている。
- テストは`FakeGraphService`が本物の`build_static_edge_score_matrix`を使うため、合成・探索・区間表示の実経路を通る。ただし**停止の待ちが所要時間へ入っていることを検証するテストは無い**（軸のスコアしか見ていない）ため、上記の材料id二重持ちは検知器を持たない。

---

## S1b+S4: backend/app/domain 残り12ファイル ＋ api 5 ＋ batch 4（計22ファイル）

呼び出し元・呼び出し先（`road_graph_repository.py`・`route_generator.py`・`evaluation.py`・
tests・生成物・docs）まで辿って裏取り。

### overall

- file: backend/app/api/dependencies.py / line: 165, 203 / category: 正準定義の複製（値のコピー） / severity: P2 / summary: `_assemble_route_generation_setup`・`open_route_generation_setup`の`penalty_strength`既定値が`1.0`のリテラルのままで、正本の`domain/evaluation.py:635 DEFAULT_PENALTY_STRENGTH = 0.7`（`routes.py:157`がimportして使う）と**違う値**になっている / failure_scenario: APIハンドラ以外からこの工場を呼ぶ経路（現に`tests/test_routes_generate.py:453 _lightweight_route_generation_setup`がそう呼んでいる）は、P=0.7の運用と異なるP=1.0で`RoadGraphEngine`を組み立てる。T799で物理の軸の重みが0になりdifficultyが大きく出る前提で0.7へ下げたのに、この経路だけ割増が約1.4倍強く効き、悪路回避が過剰な経路が返る。片側importにしていないため、Pの較正値を次に変えたときもここだけ取り残される。

- file: backend/app/batch/precompute_way_attribute_counts.py / line: 11（および`road_graph_repository.py:908-910`の「意味論は同一」宣言） / category: 修正範囲が性質ではなく症状で決まっている（T765の取り残し） / severity: P2 / summary: T765はEdge単位の交差点カウントを「終点ノードのみ」（`ON rn.node_id = e.to_node_id`、始点を除いて二重計上を防ぐ規則）へ直したが、Way単位は`COUNT(*) FROM raw_intersection_nodes i WHERE i.osm_node_id = ANY(w.node_ids)`のまま**始点を含む全構成ノード**を数えており、同じ材料`intersection_count_per_km`が経路によって別の量になる。バッチのdocstringは今も「半径・kindフィルタ・死亡事故重みの意味論はedge単位版と同一」と述べる（同じPOI側は`_poi_counts_body("w.node_ids", "w.node_ids[1]")`で始点を除いており、除外規則が適用されたのはPOIだけ） / failure_scenario: 交差点密度を材料にした軸を軸スタジオで作ると、ルート評価（Edge単位）が「1回/100m」と出す道を、区間インスペクタ（`axis_inspector.py:87`）と地図レンズ（`tile_property="intersection_per_km"`＝way単位の焼き込み値）は「2回/100m」と出す。短いwayほど差が2倍に近づき、利用者は同じ軸の同じ道について地図と結果で矛盾する値を見る。現行の公開軸はこの材料を使っていないため今日は潜在。

- file: backend/app/api/routers/routes.py / line: 226-262（`GenerationConditions`） / category: 契約不一致（宣言した再現性が成り立たない） / severity: P2 / summary: docstringが「レスポンスJSONを保存すれば同じ条件をそのまま再送して再現できる」と宣言しているが、出力を決める2つのリクエスト項目`lens_axis_id`（:187）と`spliced_edge_ids`（:196）がエコーされていない / failure_scenario: 区間の乗り換え（T621）で得た候補のレスポンスを保存して再送すると、`conditions`には`spliced_edge_ids`が無いため`_run_generate_job`は`generate_via_waypoints`分岐（:378）へ入り、まったく別の通常の目的地探索結果が「再現」として返る。失敗ではなく黙って違う経路になるため、研究用途の実験記録が突き合わせ不能になる。`lens_axis_id`も区間表示の軸評価（レグごとの風）を変えるため、同じ条件JSONから同じ`axis_difficulties`が出ない。

- file: backend/app/domain/axis_definitions.py / line: 403, 428 / category: 不要な構造 / severity: P3 / summary: `check_material_exclusivity`・`axis_dependencies`が`from app.domain.material_catalog import is_known_material`を関数内importしているが、循環は存在しない（`material_catalog`の推移的import先はいずれも`axis_definitions`を参照しない）。理由のコメントも無い / failure_scenario: 読み手が「ここには循環がある」と誤って学習し、同種の遅延importを新しい関数へ広げる。モジュール先頭のimport一覧を見ても依存が見えないため、依存関係の把握が壊れる。

- file: backend/app/api/dependencies.py / line: 306-308, 319-321 / category: 宣言と実態の不一致（拡張コスト） / severity: P3 / summary: コメントは「3つ目の専用way値配信軸を追加する際は、このdictへ1エントリ足すだけでよい」と述べるが、直下の型注釈が`Callable[..., WindWayService | GradientWayService]`と軸ごとの具体型のunionで書かれており、3つ目を足すならこのunionも広げる必要がある / failure_scenario: 新しい軸のサービスを1エントリだけ足した人が型注釈を放置し、注釈が実態と食い違ったまま残る（ruffは型検査をしないため機械的には現れない）。

- file: backend/app/batch/precompute_way_attribute_counts.py / line: 47-48 / category: 自己申告のチェック（CLAUDE.md「修正の原則」違反） / severity: P3 / summary: edge版とway版の`ALGORITHM_VERSION`（両方`"v3"`）について「実際に揃っているかはコードレビュー時の目視確認」と明記している。両定数の一致は1行のテストで機械化できる / failure_scenario: 片方だけ版数を上げた変更が周期レビューまで気づかれず、`derived_data_freshness`の鮮度台帳が「再集計済み」と「未再集計」を取り違えたまま運用される。

### consistency

- file: docs/architecture.md / line: 579-580 / category: 事実誤り（文が壊れている） / severity: P2 / summary: 「penalty_strength（改善計画T218・T12 ADR原則1）は / 0次ハードフィルタの勾配しきい値で、いずれもroad_graphエンジンのみに効く。」となっており、`max_average_grade_percent`の説明が欠落した結果、**penalty_strengthが勾配しきい値だと述べている**。「いずれも」の対象も1つしか残っていない / failure_scenario: APIクライアントを書く人がこの節だけを読み、`penalty_strength`へ勾配%（例: 8）を入れる。値域`ge=0`のため422にならず、P=8＝「難易度100の道は体感9倍の時間」という極端な割増で探索され、返る経路が説明のつかないものになる。

- file: docs/architecture.md / line: 947（および例の567・645） / category: 既定値の乖離 / severity: P2 / summary: `penalty_strength?: number; // …省略時1.0`と書かれているが、`routes.py:157`の既定は`DEFAULT_PENALTY_STRENGTH`=0.7で、生成物`route-generate-config.json`も`default_penalty_strength: 0.7`を持つ（生成物側は実装と一致） / failure_scenario: この記述を信じて`penalty_strength`を省略したクライアントが「1.0で走る」前提で結果を解釈し、実際は0.7の結果を見る。実験の再現・A/B比較の基準がドキュメントとズレたまま残る。

- file: docs/architecture.md / line: 565-566 / category: 軸idの数え上げ（DB行データをドキュメントへ写している） / severity: P2 / summary: `route_preference`のリクエスト例が7キー。`stop_density`という軸idは本番スナップショット（revision 72）に存在せず（停止密度は`axis_abdaded0be20`）、`bicycle_infra_quality`/`openness`/`curvature`/`axis_abdaded0be20`が抜けている。`RoutePreferenceWeights._check_axis_keys`（routes.py:89-101）は公開軸の**完全一致**を要求する / failure_scenario: このドキュメント例をそのまま投げると`missing=[...] unknown=['stop_density']`で必ず422になる。利用者は自分の書き方を疑って時間を溶かす。軸はDBの行データで増減するため、ドキュメントに全件を写す限り再発し続ける（正本は`GET /api/axis-catalog`）。

- file: backend/app/batch/precompute_edge_attribute_counts.py / line: 72-74 / category: 参照先の取り違え（T765で書き換わった際の誤り） / severity: P2 / summary: 「次数は`raw_intersection_nodes`（全域、precompute_road_node_degrees.pyが再構築）を参照する」とあるが、実際に`_INTERSECTION_COUNTS_SQL`が参照するのは`road_nodes.degree`であり、`raw_intersection_nodes`を再構築するのは`precompute_way_attribute_counts.py:72`である。T765の差分でこのコメントに元々あった「**本バッチの実行前にprecompute_road_node_degrees.pyの実行が必須**」という警告も同時に消えている（モジュールdocstring:13-15には残存） / failure_scenario: PBF再取込後に派生データを作り直す運用者が、このコメントから「way側バッチを回せば前提が満たされる」と読み、`precompute_road_node_degrees`を飛ばす。`road_nodes.degree`が0のままなので全Edgeの`intersection_count`が0になり、交差点密度を使う軸が全道路を「交差点ゼロ」として評価する。エラーも警告も出ない。

- file: backend/tests/test_routes_generate.py / line: 94, 102 / category: 実装を変えても落ちないテスト / severity: P2 / summary: `penalty_strength`について、フェイクの既定が`1.0`、`captured["penalty_strength"]`へ記録はするが**リポジトリ全体でこの値をassertしている箇所が1つも無い**（`0.7`/`DEFAULT_PENALTY_STRENGTH`をassertするテストもゼロ） / failure_scenario: `routes.py:157`の既定を1.0へ戻す・`conditions`のエコーを落とす・`open_route_generation_setup`への受け渡しを取り違える、のいずれをやってもバックエンドのテストは全緑のまま通る。T790で既定値を変えたこと自体が回帰テストで守られていない。

- file: backend/app/api/dependencies.py / line: 211-212 / category: 削除済みの事実を語る記述 / severity: P3 / summary: `open_route_generation_setup`のdocstringが「FastAPIのリクエストスコープ外（`BackgroundTasks`経由、レスポンス送出後に実行される）で使うため」と述べるが、T661で`BackgroundTasks`は廃止され`routes.py:318-323`が「ジョブ本体は`create_task`で起動する」と明記している。`tests/test_routes_generate.py:121`にも同じ古い記述が残る / failure_scenario: この工場を触る人が「レスポンス送出後に動く」前提でセッション寿命やセマフォ解放のタイミングを考え、実際は送出前から並行して動く現行の実装と食い違った判断をする。

- file: backend/app/domain/axis_display.py / line: 475 / category: 数え上げ（同一ファイル内で矛盾） / severity: P3 / summary: `primary_attribute_ids_for`のdocstringが「car_stressの内部軸6つ」と書くが、同じファイルの:34・:157・:421はいずれも「5つの内部軸」で、スナップショットの`car_stress`も内部軸5件 / failure_scenario: 軸階層を追う人がどちらの数が正しいか判断できず、内部軸の取りこぼしを疑って無駄に実データを掘る。軸はDBで増減するため、個数を書いた側は必ず古くなる。

- file: backend/app/domain/material_catalog.py / line: 768, 776 / category: 数え上げ（正規化フラグ材料の件数） / severity: P3 / summary: 「意味的には他3材料と同じ」「4材料は常にbicycle_infra_flagsから一括で算出される…4件まとめて"nan"にしても副作用は無い」と書かれているが、`bool_default="nan"`の自転車インフラ正規化フラグは5件（:758のコメント自身は「5材料」と正しく書いており、同一ファイル内で矛盾） / failure_scenario: `bool_default`の扱いを変更する人が4件だけを対象に数え、後から追加された`shared_pedestrian_path`を取り残す。欠損が確定Falseへ丸められ、`bicycle_infra_quality`が未解決区間を「共用歩道なし確定」と誤評価する。

- file: backend/app/domain/material_catalog.py / line: 903 / category: 利用者向け説明文の事実誤り / severity: P3 / summary: `smoothness`材料の`description`（`GET /api/material-catalog`経由で軸スタジオのⓘに出る）が「excellent〜impassableの7段階」と書くが、直下の:905-907のコメントも`_SMOOTHNESS_VALUE_LABELS`（:511-520）も8値を列挙している / failure_scenario: 軸スタジオで`smoothness`のCategoricalShapeを作る人が「7段階」を信じて値を7つだけ登録し、8つ目の値を持つ道路が`evaluate_categorical`のdefault=NaNで評価不能になる。地図にも灰色（不明）として出るが、原因が説明文の誤りだと気づけない。

- file: backend/app/api/routers/material_catalog.py / line: 7-10 / category: 数え上げ（レスポンス項目の全件列挙が古い） / severity: P3 / summary: モジュールdocstringが「フロントの軸コンポーザーが必要とするのは`material_id`/`label`/`description`/`dtype`/`reference_points`のみ」と全件を列挙しているが、`MaterialCatalogEntry`（:64-77）は`unit`も返す。また`/api/admin/material-catalog/{material_id}/distribution`（:158）がdocstringのエンドポイント紹介から漏れている / failure_scenario: 公開レスポンスへ何を載せるかを判断する人が、この列挙を「載せてよいものの正本」と読み、`unit`の存在を知らずに重複したフィールドを足す、あるいは`unit`を内部専用と誤認して削る。

- file: backend/app/batch/import_pbf.py / line: 416-417 / category: 成立しなくなった前提を語る記述 / severity: P3 / summary: 「容量予算の監視（Supabaseフリープラン500MB・プロトタイプ目標300MB、docs/osm-pbf-import.md 10章）」とあるが、参照先の`docs/osm-pbf-import.md:9`は「本番DBはOracle Cloud（150GB）へ移行したため、以下のSupabase時代の容量予算（400MB）は**撤廃された**」と明記している（数値も300MBではなく400MB） / failure_scenario: 取込範囲を広げる担当者が`db_size_mb`のサマリを「300MBを超えたら止めるべき値」と読み、150GBの実容量に対して不要な範囲縮小を判断する。逆に、現に有効な監視指標が何の予算に対するものか誰も説明できなくなる。

- file: backend/app/domain/axis_definitions.py / line: 674-675 / category: コメント方針違反（経緯） / severity: P3 / summary: `evaluate_axes_scalar`のdocstringが「（コードレビュー指摘の修正: …）」と、いつ・誰の指摘で入ったかという経緯を書いている。`docs/comments.md`は「経緯は書かない」と定める / failure_scenario: 経緯コメントの前例として参照され、同種の記述が新規コードへ増える。T567（経緯コメント一掃）の母集団が減らない。

- file: backend/app/services/route_generator.py / line: 556（宣言は`domain/route.py:135-140`） / category: 改名・方式変更後に残った周辺表現 / severity: P3 / summary: T790でコストの単位が秒になり選定関数も`select_fastest_route`へ変わったのに、直前のコメントは「**距離だけで選んだ最短経路**を基準線として必ず1本含める」と旧方式のままで、`route.py:135`の「所要時間が最短の経路＝軸の重みをすべて0にしたときの基準線」と食い違う。同種の残存は`docs/tasks/T745.md:19,34`・`T696.md:39`（`is_shortest_distance`という存在しない識別子でコードを引用）にもある / failure_scenario: 基準線の選び方を調整する人が「距離最短」を前提に読み、時間ベースの`select_fastest_route`に距離の条件を足し戻す。タブの「+N分」表記の基準が実際の最速候補でなくなり、負の差が丸められて`null`になる（＝表記が黙って消える）形で現れる。

補足（問題なしを確認した点）: `is_shortest_distance`→`is_fastest`の改名は、backend・frontend（`page.tsx`・`routeSplice.ts`・`routeTabLabel.ts`・fixtures）・OpenAPI生成物まで消費者の取り残しゼロ。`route-generate-config.json`/`openapi.json`は`penalty_strength: 0.7`・`max_routes`・`assumed_speed_kmh`とも実装と一致。domain層へのI/O漏れ・DI工場の迂回・`create_tables`へのALTER追記・未使用エクスポートは検出されず。

---

## S3: backend/app/infrastructure（11ファイル）

呼び出し元（`app/services/`・`app/batch/`・`tests/`・`migrations/`・`docs/`）まで辿って確認。
実測（venv python）で裏を取った項目にはその旨を記載。

### overall

- file: backend/app/infrastructure/cache_identity.py / line: 3-5, 63-77（消費側は road_graph_repository.py:424-427） / category: キャッシュ鍵の妥当性 / severity: P1 / summary: `shape_digest`は`str(source)`でSQLを署名するため、`bindparams`で渡した**値**（`GOOD_OSM_SURFACE_TAGS`/`BAD_OSM_SURFACE_TAGS`）が署名に一切入らず、「形を変えれば鍵が自動で変わる」という本モジュールの約束が路面タイルでは成立していない / failure_scenario: `domain/road.py`の`GOOD_OSM_SURFACE_TAGS`に1タグ（例 `paving_stones`）を足すと、全タイルの`surface_good`の焼き込み値が変わるのに`ROAD_SURFACE_TILE_VERSION`は`25-bb4ca819b676`のまま（実測: `str(_ROAD_SURFACE_TILE_MVT_SQL)`に`good_tags`というプレースホルダ名は現れるが実タグ値は現れない＝署名不変）。結果、`tile_persistent_cache`のディスクタイル・ブラウザキャッシュ・CDNは旧分類を返し続け、Python側`classify_osm_surface`を使うルート評価とだけ新分類が効く——地図の「舗装/未舗装」とルート採点の食い違いが、手で世代を上げるまで無警告で続く。`ROAD_SURFACE_REVISION`のコメント（line 25-28）は手上げ条件を「SQLが読むテーブルの中身を作り直したとき」としか書いておらず、この場合を挙げていない。

- file: backend/app/infrastructure/derived_data_freshness.py / line: 23-26 / category: レイヤー構造 / severity: P1 / summary: infrastructureが`app/batch/precompute_*.py`を4本モジュールトップでimportしており、batch側は`road_graph_repository`（infrastructure）をimportし返す循環になっている。かつwebイメージは`requirements.txt`しか入れない（`backend/Dockerfile:5-6`、rasterio等は`requirements-batch.txt`のみ） / failure_scenario: `precompute_way_curvature.py`・`precompute_way_landcover.py`等のどれかにbatch専用依存（rasterio・GDAL系等）のトップレベルimportを1行足すと、テストとCIはbatch依存が入っているため緑のまま通り、本番webイメージだけが`api/routers/derived_data_freshness.py`→`infrastructure/derived_data_freshness.py`のimport連鎖で`ModuleNotFoundError`を起こしてbackendが起動失敗する。現在この規約を守らせているのは`precompute_way_landcover.py:88-90`のコメント1つだけで、検知器もテストも無い。

- file: backend/app/infrastructure/tile_score_matrix_cache.py / line: 93-106 / category: キャッシュ鍵の妥当性 / severity: P1 / summary: 「`dataclasses.fields()`に現れない中身で決まる列」を守るガードが`raw_axis_ids`/`material_ids`/`categorical_material_ids`の3つだけを検証し、同じ性質を持つ`highway_filter_flags`（`dict[str, np.ndarray]`、キー集合は`domain/hard_filters.py: HARD_FILTER_HIGHWAY_TYPES`由来）を検証していない / failure_scenario: `hard_filters.py:28-42`は「highway種別のフィルタを増やすなら`HARD_FILTER_HIGHWAY_TYPES`へ1行足すだけで済む」と明記しており、その1行では`StaticEdgeScoreMatrix`の宣言フィールドが変わらないため鍵の署名も変わらない。デプロイをまたいで残るディスクキャッシュから旧キー集合の行列が復元され、(a)`evaluation.py:1064-1066`が「先頭タイルのキーで揃える」ため、旧行列が先頭に来ればその新フィルタは全タイルで**静かに無効化**され利用者が除外したはずの道を通るルートが出る、(b)新行列が先頭に来れば`matrix.highway_filter_flags[name]`が`KeyError`になり、そのbboxのルート生成が丸ごと落ちる。`hard_filters.py:147`は`.items()`で回すため例外にもならず(a)は完全に無警告。

- file: backend/app/infrastructure/road_graph_repository.py / line: 3-15（モジュールdocstring）と 2013-2021 vs 2217-2306・2492-2569 / category: 責務分割 / severity: P2 / summary: 「Edge単位のRoad Attribute（elevation_attributes）」と宣言された`AttributeRepository`に、way単位の照会・再計算（`sample_way_rows`・`get_way_landcover`・`get_way_curvature`・`get_way_attribute_counts`・`recompute_way_curvature`・`recompute_way_attribute_counts`・`rebuild_raw_intersection_nodes`）が積み上がり、4分割の「変更理由が異なる操作を同居させない」という軸が成立しなくなっている / failure_scenario: way単位の新しい材料を足す開発者が、docstringどおりに読むと置き場所が見つからず、結局同じクラスへ足すしかない。2,763行のうちファサード（2572-2763）は全メソッドの単純委譲で、1メソッド追加ごとに2箇所の編集が固定費として乗り、委譲漏れは型でもテストでも落ちない。

- file: backend/app/infrastructure/material_coverage.py / line: 213-228 / category: スケール成立性 / severity: P2 / summary: `trees_percent`/`built_percent`だけがway母集団の`count(*) FILTER (WHERE NOT EXISTS (...))`の形で別テーブルを引いており、集約のFILTER句内のサブリンクは反結合へ書き換えられず行ごとのSubPlanとして評価される / failure_scenario: `build_way_coverage_sql`は`osm_raw_ways`全行（本番は関東7都県、数百万行）を1回走査するが、この2材料ぶんだけ1行あたり2回の`way_landcover`索引探索が乗る。同じ「派生テーブルの行の有無」を数える他の材料は`EdgeMaterialCoverageSpec.present_count_sql`（母集団と独立した単発の集約）で済ませており、way母集団側に同等の仕組みが無いためこの形になっている。way_landcoverの列が増えるたびに同じサブプランが1本ずつ増える構造。

- file: backend/app/infrastructure/search_graph_cache.py / line: 88-94 / category: 不要な抽象化 / severity: P3 / summary: `_TileKeyedLru.set`が毎回上限を引数で受け取り変化時にLRUを作り直す機構は、本番では上限が再代入されないためテストのmonkeypatch専用の分岐であり、しかも引き継ぎ`list(self._entries.items())[-max_entries:]`はLRU順ではなく挿入順を仮定している / failure_scenario: 実測で`cachetools 7.1.7`の`LRUCache.__iter__`は挿入順を返す（`c['a']`で読み直しても順序は`['a','b','c']`のまま）。上限を縮めた際に「最近読まれたが古くに挿入されたエントリ」が捨てられ、「最近挿入されたが二度と使われないエントリ」が残る。今は本番経路で上限が変わらないため実害は無いが、将来上限を動的設定にした瞬間に立ち退き方針が静かに逆転する。

- file: backend/app/infrastructure/tile_score_matrix_cache.py / line: 87-90 / category: デッドコード・古い記述 / severity: P3 / summary: `_remember`は`_cache[key] = matrix`の1行ラッパーで、docstringの「上限超過分を退避する」という動作を一切行っていない（`LRUCache`が黙って捨てるだけで、退避先は無い） / failure_scenario: LRU上限超過時に何かへ退避されると読んだ開発者が、ディスク側にも自動で落ちると誤解し、`set()`を呼ばない経路（ディスクヒット時の`_remember`再取り込み）でもディスクが更新されると思い込む。

- file: backend/app/infrastructure/material_coverage.py / line: 205-228（および derived_data_freshness.py:173-184） / category: 指標の母集団 / severity: P3 / summary: 一部の材料で「欠損率の分母」がバッチの対象母集団より広く、欠損率が構造的に0へ到達しない / failure_scenario: `trees_percent`/`built_percent`の分母は`osm_raw_ways`全行だが、`precompute_way_landcover.py:124-135`の対象は`geom IS NOT NULL AND highway IS NOT NULL`に限られる。`curvature_deg_per_km`も分母は`road_edges`全件だが`precompute_edge_curvature.py:38-40`は`distance_m > 0`に限る。管理画面の運用者は「バッチをもう一度流せば0になるはず」と読むが決して0にならず、本当に未実行なのか対象外なのかを画面から区別できない。

### consistency

- file: docs/modules/backend/routing-engine.md / line: 353-355 / category: docs↔実装の乖離 / severity: P1 / summary: 「**ターン展開構造**（`TurnExpandedStructure`）は`prepare`が毎回構築する（キャッシュ対象ではない）……キャッシュへ載せる余地はあるが現状は載せていない」と書かれているが、T790で実際にはキャッシュされている（`search_graph_cache.py:64,116-119,153-158`、`road_graph_engine.py:2213-2238`の`_get_or_build_turn_structure`） / failure_scenario: この節を正本として読んだ開発者が「ターン費用（`TurnCostSpec`）を画面から指定できるようにする」等の変更に着手した際、キャッシュ鍵`TurnStructureKey = (TileSet, TurnCostSpec)`の存在に気づかない。`TurnCostSpec`をfrozen dataclassから可変な形へ変えると鍵が値等価でなくなり、キャッシュが恒久的に全ミスになって本番規模で数百msの再構築が毎リクエスト乗るが、機能は正しく動くため誰も気づかない。

- file: backend/app/infrastructure/search_graph_cache.py / line: 73-76、169-182 / category: 削除・統合された事実を語る周辺表現の残存＋数え上げ / severity: P2 / summary: 「4キャッシュ（lazy_graph・search_statics・routable_index）が共有する薄い包み」と、`invalidate_tile_set`の「全キャッシュ（…3つ）すべてから破棄する」が、実体5つ（`_turn_structure_cache`・`_detour_ratio_cache`を追加済み、183-187で実際に破棄している）と食い違う。個数を書いている点自体が`docs/documentation.md`の方針に反する / failure_scenario: 6本目のタイル集合派生キャッシュを足す開発者が「全キャッシュ」に挙がった3つだけを`invalidate_tile_set`へ足して満足し、実際には自分の新キャッシュを足し忘れる。再split後の自己修復で取り残されたキャッシュだけが旧edge_id集合を保持し、`LazyGraphEdgeMismatchError`の再発をプロセス再起動まで繰り返す。

- file: backend/tests/test_search_graph_cache.py / line: 146-152（`test_clear_empties_both_caches_together`）、ファイル全体 / category: 実装を変えても落ちないテスト / severity: P2 / summary: T790で追加された`_turn_structure_cache`と`_detour_ratio_cache`を検証するテストが1件も無く（`grep "turn_structure\|detour"`が0ヒット）、`clear`のテストは名前・中身とも旧2キャッシュのままで「全消し」を主張している / failure_scenario: `invalidate_tile_set`から`_turn_structure_cache.pop_matching(...)`（186行）を削除しても、全テストが緑のまま通る。実際に消すと、再split検知後に旧`lazy_graph`のedge index空間で組んだ`TurnExpandedStructure`が、新しく組み直した`SearchGraphStatics`のCSRと組み合わされ、探索が別の区間へ遷移する（範囲内なら無警告で誤ったルート、範囲外ならIndexError）。

- file: backend/app/infrastructure/derived_data_freshness.py / line: 50-93（および tests/test_derived_data_freshness.py:140-170） / category: ガードの穴／テストが変更後の契約を検証していない / severity: P2 / summary: 世代台帳の網羅性テストの母集団が「`precompute_*.py`のうち`^ALGORITHM_VERSION\s*=`を宣言しているもの」であるため、版数を宣言しなければ台帳に載らなくてもテストを素通りする。`precompute_edge_curvature.py`がまさにこれに該当し、`ALGORITHM_VERSION_NOT_IN_LEDGER`も空のままで理由の記録が無い / failure_scenario: `way_geometry`（地図・軸スタジオ用）は台帳に載ったが、**ルート評価が実際に読む**`road_edges.curvature_deg_per_km`は台帳に載らず、`road_edges`に系譜列自体が無い。PBF再取込後に`precompute_edge_curvature`の実行だけを忘れると、新規splitされたEdgeはNULL（＝蛇行軸が重み再正規化で薄まって無警告で評価から抜ける）のまま残るが、`GET /api/admin/derived-data/freshness`にはその陳腐化がどこにも現れない。同じ穴は`precompute_road_node_degrees`（`road_nodes.degree`）にも当てはまる。

- file: docs/caching.md / line: 272-275、docs/architecture.md:2074-2076 / category: docs↔実装の乖離 / severity: P2 / summary: 「形を変えたのに版を上げ忘れる、という最も多い事故が原理的に起きなくなる」「プロパティを足す・消す・**式を変えれば**自動で変わる」と断言しているが、overall 1件目のとおりバインドパラメータの値（＝`surface_good`の分類そのもの）は署名に入らない。`docs/caching.md:296-298`に手動ルールは残るものの、上の断言と併読すると「機械が捕まえるので手上げは不要」と読める / failure_scenario: この2箇所を根拠に「署名があるから世代は自動」と判断した開発者が、surfaceタグ集合の変更を世代据え置きでpushし、本番タイルの分類が変わらないことに数日気づかない。`cache_identity.py:25-28`の手上げ条件リストにもこのケースが無いため、コード側を読んでも救われない。

- file: backend/app/infrastructure/search_graph_cache.py / line: 31-34（および docs/modules/backend/routing-engine.md:329-336） / category: 実在しない挙動を語る記述 / severity: P2 / summary: 「`SearchGraphStatics`（順方向・転置版）は……小さい上限を別に持つ」とあるが、本番経路には転置版の`SearchGraphStatics`は存在しない。`build_search_graph_statics(..., reverse=True)`を呼ぶのは`tests/test_routing.py:236-241`だけで、後ろ向き木はT790以降`TurnExpandedStructure.reverse_transitions`が担っている。加えて、この上限を実際に共有している`_turn_structure_cache`が同節にまったく登場しない / failure_scenario: 「転置版も同じキャッシュに入っている」と読んだ開発者が転置版の再利用を実装すると、`_search_statics_cache`のキーは`TileSet`のみのため順方向と転置版が同一キーで衝突し、後ろ向き探索が順方向CSRを引いて（あるいはその逆で）経路が静かに反転する。

補足: `infrastructure → services`の逆依存は無し。`frontend/src/types/generated/region-tile-config.json`の3つのタイル世代は実測で現行コードの値と完全一致しており、生成物のドリフトは無い。

---

## S5: frontend/src/app（4ファイル）

`page.tsx`・`page.test.tsx`・`page.module.css`・`globals.css`。呼び出し元・呼び出し先
（`components/Map/`・`components/RouteForm/`・`lib/routeTabLabel.ts`・`lib/routeSplice.ts`・
`lib/generationRequest.ts`・`docs/modules/frontend/`・`docs/architecture.md`）まで追跡。

### overall

- file: frontend/src/app/page.tsx / line: 1592-1605, 1440-1462, 1510-1513 / category: 契約不一致（目的地補正とdirty判定の不整合） / severity: **P1** / summary: `corrected_destination`を受けたとき比較キーの`destination`だけを補正後へ差し替えているが、同じキーに入る`distance_km`は補正**前**の目的地から算出した値のまま残るため、生成直後に`conditionsDirty`が真になる / failure_scenario: 目的地モードで生成し、backendが目的地を補正した場合。`handleGenerate`が`setDestination(corrected)`するので次レンダーの`buildCurrentGenerationInput`は補正後の座標で`Math.ceil(haversine)+1`を再計算する。`page.test.tsx:846`のフィクスチャがまさにこの条件（起点35.7597/139.7387、指定35.681/139.767≈9.1km→`distance_km=11`、補正後35.70/139.70≈7.5km→`distance_km=9`）で、生成直後にユーザーが何も触っていないのに「条件が変更されています」とヘッダーの`dirtyDot`（モバイルはタブのドット）が点灯する。1594行のコメントは「conditionsDirtyが直後に誤ってtrueにならないように揃える」と書いているが、揃っているのは`destination`だけ。dirty印が常時点灯する結果、本当に条件を変えたときの合図が意味を失う。

- file: frontend/src/app/page.tsx / line: 1202（判定は1192-1202） / category: 撤去済み機能への案内が残存 / severity: **P1** / summary: 静的レイヤーチップのtooltipが`[設定はサイドバー]`と案内するが、T769（`dc19b737`、本レビュー期間内）で`MapLayersPanel`を削除しサイドバーは「ルート設定／ルート結果／ルート編集」の3区分だけになったため、案内先に該当設定が存在しない / failure_scenario: 道路・スポット系チップ（roadType/roadSurface/designation/tunnel/oneway/stopPoi/supplyPoi/accidents）を長押し/ホバーした利用者が、指示どおりサイドバーを開いても絞り込み設定が1つも無い。実際の入口は`MapOverlayControls`の▶パネル（`renderVisibilitySettings`）へ移っている。`page.test.tsx:332-339`がこのtooltipの末尾一致を回帰テストとして固定しているため、誤った案内文が検査で守られている状態。同種の「サイドバー」参照は`MapOverlayControls.tsx:95,636`にも残る。

- file: frontend/src/app/page.tsx / line: 804-822（消費側は MapView.tsx:3565-3574） / category: 参照の非安定化による無駄な再描画 / severity: P2 / summary: `splicePairs`/`spliceStretches`/`spliceStretchFeatures`をレンダー本体で毎回新規生成しており、`MapView`の`useEffect([spliceStretches, routeLayerOn])`が毎レンダー発火する / failure_scenario: 区間の乗り換えパネルで比較相手を選んでいる間、天候フェッチ・`onViewportChange`（moveend/zoomendごとに`setMapViewport`）・デバウンス確定などHomeの**あらゆる**再レンダーで`drawSpliceStretches`が走り、`spliceStretchesToFeatureCollection`のsort/mapとGeoJSONSourceの`setData`が地図パン中ずっと繰り返される。比較相手未選択時も毎回`hideSpliceStretches`が呼ばれる。加えて`pairedStretches`が両候補の`edge_ids`（30km級で数千件）からSetを毎レンダー構築する。同ファイル877-880行が`roadHiddenKeysByMode`について「毎レンダー新規生成するとMapView側のエフェクト依存でフィルタ再適用が走る（設計レビューB3）」としてuseMemo化した、まさに同じ欠陥の再発。

- file: frontend/src/app/page.tsx / line: 1831-1832, 1937, 2006 / category: 状態の取り残し（到達可能な空状態） / severity: P2 / summary: `comparisonTabActive`は研究モードOFFで解除されないため、「比較」タブを見たままヘッダーメニューで研究モードを切ると、`outerTabValue="comparison"`に対応するTrigger/Contentがどちらも描画されない状態になる / failure_scenario: 研究モードONで候補生成→「比較」タブを開く→ヘッダーの⋮メニューで研究モードをOFF。`showComparisonTab`がfalseになり比較タブが消える一方`comparisonTabActive`はtrueのままなので、Radixがどの`Tabs.Content`もアクティブにせず、ルート結果パネルの右カラムが空白になる（候補一覧は出ているのに中身が何も出ない＝壊れて見える）。候補タブを押すか「ルートをクリア」で復帰するが、その手掛かりは画面に無い。

- file: frontend/src/app/page.tsx / line: 129 / category: 正準定義のフロント手書き / severity: P2 / summary: `DISTANCE_TOLERANCE_KM = 5`がbackend（`routes.py:149` `distance_tolerance_km: float = Field(gt=0, le=50, default=5.0)`）の既定値を手書きで複製しており、`route-generate-config.json`に対応する項目が無い / failure_scenario: フロントは常に`distance_tolerance_km: 5`を明示送信するため、backend側で既定許容幅を調整（例: 3km）しても画面からの生成には一切効かず、backendの単体テストだけが新しい値で通る。同ファイル146行の`MAX_DISTANCE_KM`・1469行の`penaltyStrength`（T799）は生成物から導出済みで、この1つだけが取り残されている。

- file: frontend/src/app/page.tsx / line: 337, 1868 / category: デッドコード / severity: P3 / summary: `SAVED_ROUTES_TAB_VALUE`（"saved"）のタブは「保存機能の実装まで描画しない」ため、`onValueChange`内の`if (value === SAVED_ROUTES_TAB_VALUE) return;`は到達不能な分岐 / failure_scenario: 読み手が「先頭固定の保存済みタブがある」と誤解し、`routes.map`のindexベース順位番号との整合（保存タブが先頭に入ると順位がずれる）を検討する必要があると考えてしまう。

- file: frontend/src/app/page.module.css / line: 456-472 / category: デッドコード / severity: P3 / summary: `.refreshButton`はpage.tsxから参照されていない（地図の再描画ボタンは`.clearAllButton`を使う、page.tsx:2326-2334） / failure_scenario: 同名クラスが`SystemStatusPanel.module.css:1`にも存在するため、再描画ボタンの見た目を直そうとした担当者がこちらを編集し、何も変わらない。

- file: frontend/src/app/globals.css / line: 36, 70, 81, 93（ダーク側は181, 185, 194） / category: デッドトークン / severity: P3 / summary: `--color-success`・`--color-group-axis`/`-bg`/`-on`がリポジトリ全体で一度も参照されていない（`--color-group-*`の実消費者は`MapOverlayControls.module.css`のroad/environment/spotの3系統のみ） / failure_scenario: 「評価軸」チップグループはT414で評価軸をルート設定パネルへ移設した時点で地図チップから消えており、59-68行のコメントは今も4グループを数え上げている。新しいグループを足す担当者が「評価軸の色はどこで使われているか」を探して時間を溶かす。既存の検査器（未定義のCSSトークン）は逆方向しか見ないため機械では拾えない。

- file: frontend/src/app/page.tsx / line: 2418-2422 vs page.module.css:227-233 / category: 同一概念の二重表現 / severity: P3 / summary: 「条件が変わった／新着あり」を示すドットが、ヘッダー側は`styles.dirtyDot`（CSS Modules）、モバイルタブ側はTailwindの任意値と2通りで書かれている / failure_scenario: ドットの大きさ・色を変更する指示が来たとき、片方だけを直すと、同じ意味のはずのモバイルタブのドットだけが旧仕様のまま残る。`page.module.css:225-226`のコメント自身が二重管理を認めている。

- file: frontend/src/app/page.tsx / line: 244-327, 881-1240 / category: 責務の同居（切り出し候補） / severity: P3 / summary: 地図チップの凡例・絞り込みサマリ組み立てが約400行を占めるが、依存するのは`layerVisibility`・`hiddenLegendKeysByMode`・`axisCatalog`・`regionZoomTooWide`・`lens`/`hasDetail`・`layerDataStatus`・`selectedCandidate`だけで、ルート生成系stateとは独立している / failure_scenario: 2,490行のうちこの塊が「状態のハブ」として同居すべき理由は無く、レイヤーを1つ足すたびに生成ロジックと同じファイルを編集するため、ルート生成の変更とレイヤー表示の変更が同じファイルで恒常的に衝突する（本プロジェクトは並行セッション前提）。`useMapOverlayChips(...)`相当のフックへ寄せられる。

### consistency

- file: docs/modules/frontend/page-composition.md / line: 265-266（同ファイル212-213と矛盾） / category: 設計↔実装の乖離／自己矛盾 / severity: P2 / summary: 「タブは…『順位番号（1始まり） 距離km』**だけ**を表示する。方位・総合難易度はタブの中身（`RouteAxisProfile`）に出るためタブでは繰り返さない」とあるが、実装（page.tsx:1919-1931）はタブ内に総合難易度のバーと数値を描いており、同じ文書の212-213行は正しく書いている / failure_scenario: タブ表記を変更する担当者が265行だけを読み、「総合難易度はタブに無い」前提で`outcomeTabScore`を消す・またはRouteAxisProfile側に重複表示を足す。加えて「方位はRouteAxisProfileに出る」は事実でなく、`direction_label`は`route-waypoints`のタブ以外どこにも描画されない。同じ誤りがpage.tsx:1881-1884のコメントと`page.module.css:290-293`にもある。

- file: docs/modules/frontend/route-settings-and-results.md / line: 218-219 / category: 撤去済み機能の記述残存（検査器も検知済み） / severity: P2 / summary: RouteAxisProfileの節に「**凡例の表示設定**: `stackBarLegendTrigger`パターン…」とあるが、`RouteAxisProfile.tsx`は凡例の表示/非表示操作を一切持たない（propsに`hiddenLegendKeys`も`onToggle`も無い）。その操作は`LensControl`（page.tsx:2282-2283）にある / failure_scenario: 凡例の絞り込みを直す担当者がRouteAxisProfileを探して見つけられない。`scripts/review_checks.py docs`が`stackBarLegendTrigger`を死んだ識別子として既に検知しており、pre-commit/CIをブロックする状態にある。同節305行の`destinationState`も同様（実体は`useRouteFormSubmit.ts:27`の`destinationSet`）。

- file: docs/modules/frontend/page-composition.md / line: 19（`routeSplice.ts`の説明） / category: 改名・仕様変更の取り残し（T790） / severity: P2 / summary: 並び順の規約を「`overall_difficulty`昇順、**最短経路は先頭固定**」と書いているが、T790で先頭固定の基準は距離最短から**所要時間最短**（`is_fastest`）へ変わっている（`lib/routeSplice.ts:154`） / failure_scenario: 「最短経路」を距離最短と読んだ担当者が、`shortestDistanceRouteId`（距離最短の印）と混同して`insertByDifficulty`の先頭固定判定を距離基準へ書き換える。backend側（`route_generator.py:587`）と対で維持すべき規約のため、片方だけ変えると合成ルートの差し込み位置が食い違う（同19行自身が「片方を変えたらもう片方も変える」と警告している対象）。

- file: docs/modules/frontend/page-composition.md / line: 226-228 / category: 設計↔実装の乖離（T803のheaderLead分離の未追従） / severity: P2 / summary: モバイルの節が「`headerAction`propとして`renderRouteSectionHeaderActions()`（**タブ列＋「ルート生成」ボタン**）を…渡す」と書いているが、実装（page.tsx:2444-2445）はタブ列を`headerLead`、ボタンのみを`headerAction`へ分けて渡す。同じ文書の234行は2口を正しく説明しており、226行だけが分離前の記述 / failure_scenario: BottomSheetヘッダーの構成を変える担当者が、`renderRouteSectionHeaderActions`がタブ列も返すと思って`headerLead`を削る／またはタブ列を`headerAction`へ移し、タブと生成ボタンが右端で密着して役割の区別が壊れる。

- file: docs/architecture.md / line: 135 / category: 「現状」記述の陳腐化 / severity: P2 / summary: サイドバー構成を「タイトル・`WeatherPanel`・旧`LocationControl`・`MapLayersPanel`・`RouteForm`・候補ごとのタブ・`BackendStatus`等」と説明しているが、現在の`<aside>`（page.tsx:2113-2201）は3つの`Disclosure`のみ。`WeatherPanel`は常設ヘッダー、`MapLayersPanel`は削除済み（T769）、`BackendStatus`は`/admin` / failure_scenario: 画面構成を把握するために最初にarchitecture.mdを読む担当者が、存在しないパネルを前提に実装方針を立てる。`MapLayersPanel`は`docs/architecture.md:2018,2349`にも残り、検査器はこの2件を「免除した段落」として参考出力するだけでブロックしない。page.tsx:890のコメントも削除済みコンポーネントを名指ししている。

- file: frontend/src/app/page.tsx / line: 2384-2385 / category: 削除された事実を語る表現の残存 / severity: P3 / summary: モバイル節のコメントが「下部タブバー＋部分シート3枚（「ルート設定」「ルート結果」**「地図の見え方」**）」と書いているが、3枚目は「ルート編集」。「地図の見え方」シートはT769で撤去済み / failure_scenario: モバイルのシート構成を触る担当者が「地図の見え方」シートを探し、`mobileSheet`の型と突き合わせるまで矛盾に気づかない。同種の陳腐化が332-334行にもある。

- file: frontend/src/app/page.module.css / line: 356-357 / category: 改名の取り残し（T790） / severity: P3 / summary: `.outcomeTabExtra`のコメントが「タブの距離の後ろに添える**「最短からの超過km」**」と書いているが、T790で表記は「基準線からの超過**時間**（`+12分`）」へ変わり、さらに同じクラスは「合成」バッジと「最短」バッジにも使い回されている / failure_scenario: このクラスの見た目を「超過km専用」と思って調整した担当者が、意図せず「合成」「最短」の見え方も変える。

- file: frontend/src/components/RouteForm/useRouteFormSubmit.ts / line: 33-34 / category: コメントが指す出力先が実装と逆 / severity: P3 / summary: `error`の説明が「『ルート生成』ボタンの近く（page.tsx: renderRouteSectionBody）へ表示する」だが、page.tsx:1716-1719は「出し先は`renderRouteOutcomeEmptyState`（「ルート結果」欄）に一本化する」と明示し、実際に1750行がそうしている / failure_scenario: 検証エラーの出方を直す担当者が`renderRouteSectionBody`を探し、そこに何も無いことで「実装漏れ」と誤診して本文へ二重表示を足す。T758が1箇所へ一本化した設計（`page.test.tsx:691-702`が`toHaveLength(1)`で固定）を壊す。

- file: frontend/src/app/page.test.tsx / line: 846-881（欠落している検証） / category: 変更後の契約を検証しないテスト / severity: P2 / summary: 目的地補正のテストが「案内文が出る」「次回生成で補正後座標を送る」だけを見ており、**補正直後に`conditionsDirty`が立っていないこと**を一切検査しないため、上記overall P1の不具合をこのフィクスチャで現に踏んでいながら緑のまま通る / failure_scenario: `conditionsDirty`はリポジトリ全体でpage.test.tsxに1件のテストも無い。生成条件の入力を1つ足したとき、`generationRequest.ts`側の純関数テストは通っても、page.tsx側の「生成直後はdirtyでない」「条件を変えるとdirtyになる」という実際の契約はどこでも検証されない。

- file: frontend/src/app/page.test.tsx / line: 332-339 / category: 誤った挙動を固定するテスト / severity: P2 / summary: 「dataNature=static（既定）のroadTypeは「[設定はサイドバー]」付きのtitleになる」という回帰テストが、サイドバーから当該設定が消えた後（T769）も更新されず、案内先の存在しない文言を検査で守っている / failure_scenario: `[設定はサイドバー]`を正しい案内へ直そうとすると、このテストが赤くなるため「既存の仕様」と解釈して差し戻される。T468の回帰を守る意図は`gradientFill`側のテスト（320-330行）で足りており、文言そのものを固定する必要は無い。

- file: frontend/src/app/page.tsx / line: 712-713 / category: 前提が成立しなくなったコメント / severity: P3 / summary: `hiddenLegendKeysByMode`について「路面モードとルートモードのIDは互いに重複しないため1つのレコードで両系統を管理できる」とあるが、ramp軸では両系統のレコードキーが一致する。実害が出ていないのはコメントが述べる理由ではなく、**凡例エントリのキー空間**が偶然分離しているため / failure_scenario: 旧`MapLayersPanel`時代に`{"surface_q": ["surface_q-2"]}`を保存した利用者が、レンズに同じ軸を選んでルートを生成すると、`routeSummary`が`hiddenRouteLegendKeys.length > 0`だけを見るため「レンズ: ○○・**一部非表示**」と出す一方、`LensControl`の凡例は全段階チェック済みに見える。ID体系を将来変えるとき、このコメントを根拠に「重複しないから安全」と判断すると今度は実害が出る。

- file: frontend/src/app/page.tsx / line: 510（方針は docs/design-principles.md:145・page-composition.md:77） / category: 設計原則と実装の乖離 / severity: P3 / summary: 想定速度`assumedSpeedKmh`だけが素の`useState`で、利用者が`RideConditionBar`で決めた値が次回起動時に既定値（20km/h）へ戻る。距離・候補数・モード・シート高さ・レンズ・重み・0次除外はすべて`useStoredState`で永続化している / failure_scenario: 設計原則「利用者が意図して決めた値は覚える」に対し、巡航速度は「行くたびに変わり古い値が残ると危険な値（場所のピン）」には当たらない乗り手固有の値。設定し直し忘れると風軸の時刻選択・到達予想時刻・`+N分`の対価表示すべてが既定20km/h基準で計算されるため、誤った前提のまま候補を見比べることになる。

---

## S6a: frontend/src/components/Map の MapView.tsx ＋ a〜m 始まりのファイル

（原文は絶対パスで出力されていたためリポジトリ相対へ正規化した。内容は変えていない）

### overall

- file: frontend/src/components/Map/MapView.tsx / line: 2865 / category: 再描画経路の取り残し / severity: P2 / summary: `redrawAllLayers`が`spliceStretches`を再描画対象に持たず、`map.setStyle()`でT621の乗り換え帯が消えたまま復活しない / failure_scenario: 合成ルート（区間の乗り換え）を表示中に「地図の表示を再描画」を押す → `setStyle()`で`SPLICE_SOURCE_ID`/`SPLICE_LAYER_ID`が破棄される → `redrawPropsRef`(2713行)に`spliceStretches`が無いため`redrawAllLayers`は再作成せず、帯専用effect(3565行)の依存`[spliceStretches, routeLayerOn]`も変化しない → 乗り換え候補の橙色の帯が消え、乗り換え操作が地図から見えなくなる。復旧は別候補の選択などでspliceが変わるまで起きない。これはT524（`MapView.routes.test.ts:217`のコメントが記録）で「redrawAllLayersだけ分岐を書き忘れる」として一度直した欠陥と**同じ性質が新設レイヤーで再発**したもの。

- file: frontend/src/components/Map/MapView.tsx / line: 368 / category: 手書きリストとスキーマの乖離 / severity: P2 / summary: `ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS`が`RouteSegmentDetail`のobject型フィールドを網羅しておらず、`material_categories`と`axis_raw_values`がJSON文字列のまま復元されずに流れる / failure_scenario: `openapi.json`の`RouteSegmentDetail`はobject型として6件を持つ（実測）が、配列に載っているのは3件のみ。ルート線クリック→`queryRenderedFeatures`で読み戻す際にMapLibreが全objectを文字列化する→`restoreRouteSegmentProperties`は未列挙の2件を文字列のまま返す→今は消費者がいないため無症状だが、ボトムシートに区間の生値や材料カテゴリを出した瞬間、`Object.entries("{\"a\":1}")`が1文字ずつのエントリになり無意味な行が並ぶ（`material_values`の列挙漏れで実際に壊れた、と同ファイルのコメント自身が記録している事象の再現）。網羅の保証が「追加するときは配列へも足すこと」という自己申告コメントだけで、型から導出されていない。

- file: frontend/src/components/Map/MapView.tsx / line: 1 / category: 規模ウォッチ閾値超過 / severity: P2 / summary: 交渉済みKeep List閾値3,700行を126行超過している（3,826行） / failure_scenario: 前回レビュー(2026-09-11)から+265行。閾値付きKEEPは「肥大が続くなら分割を再判断する」という安全弁のため、発火したまま放置すると安全弁が一度きりで機能しなくなる。同ファイルは既に「ルート候補描画・splice帯・静的オーバーレイ・動的気象スペック・POIポップアップHTML・マーカー管理・データ状態イベント」を同居させており、`DYNAMIC_WEATHER_RENDERERS`一式（1041〜1494行）とポップアップHTML組み立て（2267〜2404行）はMapLibreインスタンスへの依存が薄く切り出し候補。

- file: frontend/src/components/Map/MapView.tsx / line: 2954 / category: 契約不一致（同じ判断が経路ごとに違う） / severity: P3 / summary: `redrawAllLayers`が無条件で`fitBoundsToRoutes`を呼び、3576行のeffectが明文化している「フィットは候補一覧が変わったときだけ」という規則を破っている / failure_scenario: ルート生成後にユーザーが任意区間へズーム・パンして詳細を見ている→「地図の表示を再描画」を押す→routesは変わっていないのに全候補を包含する範囲へカメラが戻る。3576〜3579行のコメントは「ユーザーが選択後に手動でズーム/パンした操作を打ち消してしまう」ことを避けるためだと明記しており、再描画経路だけがその判断を共有していない。

- file: frontend/src/components/Map/MapView.tsx / line: 752 / category: 描画順の保証漏れ / severity: P3 / summary: 実験スロット線は作成時にしか`DETAIL_LAYER_ID`の下へ置かれず、後から区間色分け線が作られた場合に上下が逆転する / failure_scenario: 矢印レイヤーには`keepRouteArrowsAboveDetailSegments`（740行）という「どちらが先に作られても順序が決まる」対策があるのに、スロット線には対応物が無い。研究モード限定のため一般利用者への影響は無い。

- file: frontend/src/components/Map/jmaTileProtocol.ts / line: 68 / category: 失敗の握り潰し / severity: P3 / summary: `response.ok`でない応答を404と5xxの区別なく空タイルへ倒すため、配信・プロキシ障害が「データなし」と見分けられない / failure_scenario: backendの`/api/jma-tile`プロキシが502を返し続ける状態でも、targetTimes JSON（別経路）が成功していればvisible=trueになる→全タイルが透明PNGへ差し替わる→MapLibreのerrorイベントも発火しないため`markSourceErrored`(3287行)も走らず、災害・降水チップは「ONだが何も表示されない＝平常時」と区別がつかない。キキクルは「平常時は透明」が正常系なので、利用者は障害を危険度ゼロと誤読しうる。

- file: frontend/src/components/Map/MapView.tsx / line: 2647 / category: 無駄な再計算・再適用 / severity: P3 / summary: `staticOverlayLayers`のuseMemoが`dedicatedWayValueLoading`（フェッチ状態のMap）に依存するため、パン/ズームのたびに全オーバーレイ層のspecを作り直しpaint/filterを全再適用する / failure_scenario: レンズON でパンする→`useDedicatedWayValues`のloadingがtrue→falseと2回変化→`page.tsx:1367`が毎回新しいMapを返す→`staticOverlayLayers`の参照が変わる→3616行と3714行の2effectが再実行→全レイヤーで`ensure()`＋`setFilter`＋`recomputeLayerDataStatus`が走る。パン1回あたり2周、公開ramp軸が増えるほど線形に増える。

- file: frontend/src/components/Map/mapLayers.ts / line: 496 / category: デッドコード / severity: P3 / summary: `layerSectionDomId`は消費者ゼロ（撤去済みサイドバーの`<details>`セクションID生成） / failure_scenario: リポジトリ全体grepで参照は自身の定義行のみ（テストにも無い）。docstringが指す「サイドバーの各レイヤー設定セクション」はT769/T803〜T807のUI再編で消えており、読んだ人が存在しない画面を探す。

- file: frontend/src/components/Map/LayerChip.tsx / line: 16 / category: デッドコード（撤去済み機構の残骸） / severity: P3 / summary: `dataStatus` propと状態ドット描画（35・36・48〜50行、`LayerChip.module.css`の`statusDot_*`一式）はどの呼び出し元からも渡されない / failure_scenario: 唯一の消費者は`RouteSettingsPanel/HardFilterPanel.tsx:60`で、label/on/ariaLabel/onClickしか渡さない（grep実測）。`LAYER_DATA_STATUS_LABELS`のimport・`showStatusDot`分岐・CSSが丸ごと死んでおり、同じ機能は`MapOverlayControls`の`ChipButton`・`LensControl`が別実装で持っている。

- file: frontend/src/components/Map/mapLayers.ts / line: 123 / category: 意味を失った二重定数 / severity: P3 / summary: `MAP_OVERLAY_GROUP_LABELS`と`MAP_OVERLAY_GROUP_CHIP_LABELS`が全キーで同値になっており、「正式名／略名」の使い分けが成立していない / failure_scenario: 両者とも`{road:"道路", environment:"環境", spot:"スポット"}`で完全一致。使い分けの根拠（128行「サイドバーは正式名を使う」）はサイドバー撤去で消え、今は`MapOverlayControls.tsx:1055-1056`が同じ場所で両方を引いている。片方だけ変更したときに気づけない二重管理が残る。

### consistency

- file: frontend/src/components/Map/mapLayers.ts / line: 7 / category: 撤去済みコンポーネントを名指しする手順書 / severity: P2 / summary: 存在しない`MapLayersPanel`が「レイヤー追加手順」の必須ステップとして書かれており、in-scopeの6ファイル・計十数箇所で生きた消費者として参照されている / failure_scenario: `find frontend/src -iname "*MapLayersPanel*"`は0件、importも0件（実測）。それでも`mapLayers.ts:3,7,15,85,89,103,108,141,541`／`legendFilter.ts:21,72,81`／`LayerChip.tsx:19,23`／`LegendCheckboxList.tsx:20`／`axisLayers.ts:468,492`／`mapColorLegend.ts:6`／`staticAttributeLayers.ts:341`／`recipeControls.tsx:9`が現在形で参照する。とくに`mapLayers.ts:7`「3. MapLayersPanelにそのレイヤーの設定セクションの中身を足す」は、次にレイヤーを足す人が実行不能な手順を探して時間を浪費する。実際の追加先は`MapOverlayControls`（▶パネル）と`LensControl`。

- file: frontend/src/components/Map/jmaTileProtocol.test.ts / line: 70 / category: 契約を検証していないテスト / severity: P2 / summary: 「差し替えるたびに最新のものが使われる」というテストが`hasJmaTileIndex()===true`を2回確認するだけで、差し替えが効いたことを一切検証していない / failure_scenario: `setJmaTileIndex`の2回目呼び出しをno-opにしても（＝古いbasetimeのインデックスを握り続ける実装にしても）このテストは緑のまま。実際に起きる害は「basetimeが進んだのに旧世代のpresent集合で判定し、中身のある新しいタイルを空と誤判定して危険情報が地図から消える」で、`jmaTileIndex.ts:7-9`が「取りこぼしより空振りを選ぶ」と明記している最優先事項。

- file: frontend/src/components/Map/MapView.routes.test.ts / line: 253 / category: テスト名が実際の検証範囲を超えている / severity: P2 / summary: 「redrawAllLayers経由でも…の直接的な検証」と題しているが、呼んでいるのは`applyRouteLayerVisibility`単体で、`redrawAllLayers`が実際にそれを呼ぶことは検証していない / failure_scenario: `redrawAllLayers`から`applyRouteLayerVisibility`の呼び出しを削っても、あるいは新しいレイヤー（splice帯）を再描画対象に入れ忘れても、このテストは通る。実際 overall 1件目のとおりsplice帯の取り残しは誰にも検知されていない。

- file: frontend/src/components/Map/MapView.tsx / line: 2547 / category: 宙に浮いたdocstring・撤去済み機能の名指し / severity: P3 / summary: どのプロパティにも掛からない`/** 空白地点クリック時の「経由地に追加」ボタン押下で呼ばれる。 */`が残り、2698行にも「周回モード中は空白地点クリックでの経由地追加を行わない。」という成立しない前提のコメントがある / failure_scenario: T797で`pinPlacementEnabled`・`onWaypointAdd`・`onDestinationSet`は撤去済み。現在の配置は`armedPinRole`による武装式（3095行）。`MapViewProps`を読んだ人が、直後の`armedPinRole`の説明をこの見出しの続きと誤読する。

- file: frontend/src/components/Map/MapView.tsx / line: 312 / category: 削除済み識別子の名指し / severity: P3 / summary: 削除済みの定数`STATIC_OVERLAY_LAYERS`が7箇所（312・1655・2072・2106・2489・3613・3659・3699行）で現存物のように参照されている / failure_scenario: `docs/architecture.md:1506-1512`がT321でこの定数を削除したことを明記しており、現在は`buildStaticOverlayLayers(...)`の戻り値をコンポーネント内useMemoで持つだけ。grepしても実体が見つからず、読み手は「どこかに定義があるはず」と探す。2705行の「onWaypointAddRefと同じパターン」も存在しないrefを指す。

- file: frontend/src/components/Map/MapView.tsx / line: 1884 / category: 要素の数え上げ・実在しないレイヤーの列挙 / severity: P3 / summary: 「路面を除く5レイヤー（標高・車ストレス・指定路線・事故・停止要因POI）」等、現状と合わない個数・顔ぶれの列挙が複数ある / failure_scenario: `buildStaticOverlayLayers`が実際に返すのはelevation・全ramp軸・designation・tunnel・oneway・全専用way値配信軸・gradientFill・accidents・stopPoi・supplyPoiで、5件ではないうえ「車ストレス」は独立レイヤーではなくカタログ駆動のramp軸。同種の列挙が2104行・2495行・3611行にあるが、`staticAttributeLayers.ts:4`と`mapLayers.ts:23-25`は「自転車インフラの専用地図レイヤーは持たない」と明記している。軸が1つ増減するだけで嘘になる記述が4箇所に散っている。

- file: docs/modules/frontend/static-map-layers.md / line: 32 / category: モジュール文書と実装の乖離（消費者の記載誤り） / severity: P3 / summary: 共通部品の消費者一覧が現状と合っていない / failure_scenario: `LayerChip.tsx`の行は消費者を「RouteSettingsPanel・page.tsxのルート色分けセクション」とするが、実際のimportは`RouteSettingsPanel/HardFilterPanel.tsx`のみ。同35行の`LegendCheckboxList.tsx`は「RouteAxisProfile・MapOverlayControlsの▶パネルで共用」とするが、実際のimportは`LensControl.tsx`と`MapOverlayControls.tsx`で、RouteAxisProfileは消費者ではない。文書を根拠に影響範囲を見積もると、LensControlへの波及を見落とす。

- file: docs/modules/frontend/dynamic-weather-layers.md / line: 33 / category: 要素の数え上げ / severity: P3 / summary: 「表現は3パターン」と見出しで数えたうえで本文が4種類（gridMark/gridFill/rasterTile/vectorTile）を説明しており、既に自己矛盾している / failure_scenario: `dynamicWeather.ts:18`のコード側は「この4種のどれかを選ぶだけで」と4で書かれており、文書だけが3のまま。同23行の`usePolledFetch`行「6箇所（…）」も同じ数え上げ。`mapLayers.ts:16`「staticが8種に達し」、災害の「7要素」（3箇所に重複）も同類。

- file: frontend/src/components/Map/dynamicWeather.ts / line: 35 / category: 参照先ファイルの誤り / severity: P3 / summary: 「新しい動的要素を追加する1本道」の手順(4)が「mapLayers.ts: … DYNAMIC_WEATHER_LAYER_IDSへ1行足す」と書いているが、`DYNAMIC_WEATHER_LAYER_IDS`は同ファイル（`dynamicWeather.ts:46`）にある / failure_scenario: 手順どおりmapLayers.tsだけを編集した人は`MapLayerId`は足せるが`DYNAMIC_WEATHER_LAYER_IDS`を足し忘れ、チップは出るのに`applyDynamicWeatherState`のループ対象に入らず「ONにしても何も描画されない」状態になる。

- file: frontend/src/components/Map/icons.tsx / line: 620 / category: 成立しなくなった前提 / severity: P3 / summary: 「ルート結果ヘッダの操作枠（保存・GPX出力）。機能実装まではdisabledの占位として使う。」が、GPX出力の実装後も更新されていない / failure_scenario: `page.tsx:1787-1796`の`DownloadIcon`ボタンは`downloadGpx`を実際に呼ぶ実装済み機能で、disabledなのは`SaveIcon`側だけ。コメントを信じると「どちらも未実装」と読め、GPX出力の不具合調査時に実装が無いものとして飛ばされる。同524行「ルート編集（モバイル下部タブ・サイドバー）」もサイドバー撤去後の残骸。

裏取りした事実: `MapLayersPanel`の不在（`find`・import検索とも0件）、`layerSectionDomId`の消費者0件、LayerChipの唯一の消費者がHardFilterPanelで`dataStatus`を渡さないこと、`RouteSegmentDetail`のobject型フィールド6件（`openapi.json`をparseして列挙）、MapView.tsx 3,826行 vs 閾値3,700、`icons.tsx`の全45 exportに外部消費者が存在すること。**推測を含むのは** overallの再計算コスト（P3）とjmaTileProtocolの障害握り潰し（P3）で、実測はしておらず経路からの推論。

問題が無いことを確認した観点: `ensureLayerFromSpec`の`specOwnsFilter`契約は`MapView.layerOps.test.ts:438-540`が正しく検証。`jmaTileIndex.ts`の「取りこぼしより空振り」方針は5つの早期returnすべてがfalse（＝取りに行く）へ倒れており、docstringと実装が一致。`axisLayers.ts`のramp配色・凡例・不明判定、`dedicatedWayValueLayer.ts`／`valueScale.ts`／`mapColorLegend.ts`／`gradientGridFill.ts`／`dynamicWayValues.ts`は軸idのハードコードが無く、`docs/modules/frontend/map-axis-coloring.md`とも乖離なし。

---

## S6b: frontend/src/components/Map の n〜z 始まりのファイル（MapView.tsx を除く）

（原文は絶対パスで出力されていたためリポジトリ相対へ正規化した）

### overall

- file: frontend/src/components/Map/routeStyleModes.ts / line: 129（および146-154） / category: 契約不一致（値スケールの取り違え） / severity: **P1** / summary: `display_thresholds_override`はramp軸では「材料スケール」の値なのに、`map_value_kind==="difficulty"`の経路で0〜100の`axis_difficulties`に対する段階境界としてそのまま使っている / failure_scenario: ルート生成後にレンズ「開放度」を選ぶ（`openness`は公開軸・`display_thresholds_override=[-85,-70,-50,-30]`、shapeのbreakpointsが示すとおり材料スケール）→`["step", ["to-number", ["get","openness",["get","axis_difficulties"]]], ...]`の入力は0〜100なので全区間が最上位バンドに落ち、ルート線（`MapView.tsx:833/851`の`DETAIL_LAYER_ID`）が全区間同一色になり、凡例には「-85未満／-85〜-70／…」という意味のない数値が並ぶ。停止密度軸（`axis_abdaded0be20`、`[2,4,7,12]`＝回/km）も同型で、difficulty 12未満の区間以外がすべて最上位色になる。ルート前は同じ軸が`buildAxisRampLegend`でタイルの材料値に対するstepとして正しく段階分けされるため、**「ルート生成した瞬間に色分けが壊れる」**という形で出る。

- file: frontend/src/components/Map/routeStyleModes.ts / line: 99-120 / category: 契約不一致（表示宣言の片落ち） / severity: P2 / summary: ルート後の凡例だけが`display_band_labels_override`（段階の体感ラベル）を一切使わず、数値レンジのみを出す / failure_scenario: レンズ「風」でルート前は`dedicatedWayValueLegend`が体感ラベル付きバンドを出すのに、ルート生成後は`buildRangeSteppedMode`の`rangeLabel`だけになり「20〜40」等の裸の数字に変わる。`docs/modules/frontend/map-axis-coloring.md:43`の図は「同じ表示宣言（種類・単位・しきい値・**段階ラベル**）」をルート前後で共有すると宣言しており、実装がその宣言の一部を落としている。

- file: frontend/src/components/Map/roadFilterAxes.ts / line: 30-33 / category: 契約不一致（拡張手順の記述が実態と逆） / severity: P2 / summary: 「軸を増やすときはROAD_FILTER_AXESへ1つ足すだけでよい（UI側の変更は不要）」と書くが、UI側はもう軸配列をループしておらず、`ROAD_LINE_COLOR_AXIS_ID`/`ROAD_LINE_WIDTH_AXIS_ID`の2軸を名指しで配線している / failure_scenario: 記述に従って3本目の絞り込み軸を`ROAD_FILTER_AXES`へ追加すると、`page.tsx:884`の`roadHiddenKeysByMode`には入るものの、サマリ・凡例（`page.tsx:1001-1050`の2ブロック）にも`MapView.tsx:1689-1700`のpaint決定にも現れず、UIにも地図にも一切反映されない軸が静かに増える。加えてこの2ブロックはsummary/legendDetailsが丸ごと写経になっており、軸が増えるたび複製が増える構造。

- file: frontend/src/components/Map/staticAttributeLayers.ts / line: 161-228 / category: 写経（同じ組み立て規則の複製） / severity: P3 / summary: tunnelとonewayの「真偽値プロパティ→凡例・色式・不透明度式」3点セットが逐語コピーで、文字列列挙用の`buildCategoricalLayerDefs`に相当する真偽値版ビルダーが無い / failure_scenario: 3つ目の真偽値一次属性（例: bridge、`lit`）を地図レイヤー化すると同じ6定義をもう一度手で写すことになり、`KNOWN_LINE_OPACITY`/`isFallback`の付け忘れのような片側だけの欠落が混入しても型もテストも止めない。

- file: frontend/src/components/Map/secondaryAxes.ts / line: 27-76 / category: 使われないビューモデルの肥大化 / severity: P3 / summary: `SecondaryAxisSummary`は12フィールドを持つが、本番の消費者は`page.tsx:675`（`layerId`・`primaryAttributeIds`）と`evaluationAxes.ts:95`（`axisId`の並び順）だけで、`chipLabel`/`iconId`/`panelHint`/`mapValueKind`/`displayThresholdsOverride`等は同じ値を別ルートから読んでいる / failure_scenario: 軸カタログにフィールドを1つ足すとき「secondaryAxesにも足す」のが慣例化しており、実際には誰も読まない写しが増え続ける。逆に片方だけ更新した場合、どちらが生きている経路かがコードから読み取れない。

### consistency

- file: docs/modules/frontend/map-axis-coloring.md / line: 53-55 / category: 設計書と実装の乖離（不変条件の宣言が偽） / severity: P2 / summary: 「`display_thresholds_override`は軸ごとに1つのスケールで解釈される（ルート前後でスケールが食い違う軸は無い）」と明記するが、ramp軸では前=材料スケール・後=difficultyスケールで実際に食い違う（overall 1件目と同一の欠陥のドキュメント側） / failure_scenario: この記述を根拠に「スケールは揃っている」と判断して軸スタジオでしきい値を較正すると、地図（ルート前）だけが意図どおりになり、ルート後の色分けが破綻していることに気づけない。

- file: frontend/src/components/Map/riskMap.ts / line: 11-20 / category: コメントが撤去済みUI設計を指している / severity: P2 / summary: ヘッダーが「キキクル3種（土砂・大雨・浸水）: 『防災』カテゴリとしてWarningBadgeと同様の常時マウント（チップ無し）」と書くが、現在はキキクル4種（洪水を含む）が`disaster`（表示名「災害」）チップ配下で`showDisasterSource(...)`によりON/OFF制御されている / failure_scenario: このファイルを起点にキキクルの表示制御を直そうとすると「チップが無い前提」で読み進め、実際の分岐を見落とす。ヘッダー内で自分自身（22行目以降の洪水＝4種目の説明）とも食い違っている。

- file: frontend/src/components/Map/routeStyleModes.test.ts / line: 22-205 / category: 契約を検証していないテスト（カバレッジ穴） / severity: P2 / summary: 動的モードの検証対象がgradient / wind / surface_qに限られ、「ramp軸かつ`display_thresholds_override`あり」（openness・停止密度）というカタログ実在の組み合わせを1件も通していない / failure_scenario: overall 1件目の欠陥がフルスイートgreenのまま素通りする。`ROUTE_STYLE_MODES`を全軸ループする検証（例: 難易度軸の境界がすべて0〜100の範囲に収まること）が無いため、軸スタジオで新しい軸へ材料スケールのしきい値を設定した瞬間に同じ壊れ方が再発してもCIは気づかない。

- file: frontend/src/components/Map/staticAttributeLayers.ts / line: 303 / category: コメントの事実誤り（数え上げの陳腐化） / severity: P3 / summary: 「`osm_raw_pois.kind`は取込時に`classify_stop_poi`で**5値**のいずれかへ分類済み」と書くが、`StopPoiKind`は実際には8値 / failure_scenario: この5という数を信じて凡例側の網羅性を判断すると、barrier/traffic_calming/railway_crossingの扱いを取りこぼす。同種の数え上げが同ファイル317行・340行にもある。**機能としてのドリフトは無く、嘘なのはコメントの数字だけ**（`staticAttributeLayers.test.ts:77,93`が生成物との突き合わせを強制している）。

- file: frontend/src/components/Map/staticAttributeLayers.ts / line: 341, 370 / category: 撤去済みコンポーネント・テストへの参照 / severity: P3 / summary: 「チェック操作時にそのレイヤーを自動でONにする判定（`MapLayersPanel.tsx`）」「テスト（…`MapLayersPanel.test.tsx`）からは…直接呼べる」と書くが、`MapLayersPanel`はリポジトリに存在しない / failure_scenario: 自動ON判定の実体を探して存在しないファイルを追うことになり、実際の所在（`MapOverlayControls`／`page.tsx`）に辿り着けない。同型の死んだ参照が`recipeControls.tsx:9`・`roadFilterAxes.ts:31`（`RoadFilterDialog`）・`page.tsx:1004`にもある。

- file: frontend/src/components/Map/routeStyleModes.ts / line: 163-166 / category: コメントが撤去済みファイル・古い軸構成を指す / severity: P3 / summary: 総合難易度の説明が「標高・風・路面を`route_preference.yaml`（またはリクエストの重み上書き）の重みで合成」と書くが、`route_preference.yaml`はT316で撤去済みで、合成対象も現在は公開9軸 / failure_scenario: 重みの正本を探して存在しないYAMLを探し、実際の正本（軸スタジオ＝`axis_definitions`テーブル）に辿り着けない。「標高・風・路面」の3軸列挙も、軸が増減した瞬間に嘘になる書き方。

- file: frontend/src/components/Map/secondaryAxes.ts / line: 5-8（矛盾は114-119） / category: ファイル内で自己矛盾するコメント＋経緯コメントの残存 / severity: P3 / summary: ヘッダーが「専用レイヤーの無い軸は薄字＋**代役へのポインタ**だけの行として表示する」と書く一方、同ファイル114-119行が「その案内文（旧proxy_hint）は不要になり撤去した」と書いており、実装にも代役案内は無い。あわせて経緯コメントが15件残っている / failure_scenario: T567が「一掃済み」を宣言している所有ファイルに経緯コメントが丸ごと残っており、`review_checks.py`の`NARRATIVE_PATTERN`は既存分をフル実行の参考件数としてしか出さないため、この取り残しは誰にも通知されない。

- file: frontend/src/components/Map/windLayer.ts / line: 111 / category: 数え上げ（増えた瞬間に嘘になる） / severity: P3 / summary: 「地図の色分け自体は`WIND_SPEED_COLOR_STOPS`の**9段階**そのまま」と配列長を本文へ焼き込んでいる / failure_scenario: Bf帯を1段足した時点でコメントだけが古くなる。同型が`precipitationNowcast.ts:148`（「格子点**624点**ぶんのセル」、格子間隔はズーム依存で可変）・`roadFilterAxes.ts:5`にもある。

- file: frontend/src/components/Map/WidthSwatch.tsx / line: 8-11 / category: 経緯コメント / severity: P3 / summary: 「改善計画:『道路種別が支配的な場合、色がすべて灰色で違和感がある』への対応で…持たせたため」と、対応の経緯がそのままpropのdocstringに残っている / failure_scenario: `docs/comments.md`の方針に反した記述が新規コミットの参考例になり、同じ書き方が増える。`windArrowIcon.ts:68-70,92`・`riskMap.ts:145`・`precipitationNowcast.ts:47`も同型。

裏取りした事実:
- `openness`の`display_thresholds_override=[-85,-70,-50,-30]`・停止密度の`[2,4,7,12]`は`axis-catalog.json`を直接パースして確認。`openness.shape.breakpoints`が`[[-100,0],[-80,30],[-20,100]]`であることから、しきい値が材料スケールでありdifficulty（0〜100）ではないことを確認した。
- ルート線が`mode.colorExpression`を使うことは`MapView.tsx:833`・`:851`、凡例が`getRouteStyleMode(...).legend`を使うことは`page.tsx:1421`で確認。
- `MapLayersPanel`・`RoadFilterEditor`・`RoadFilterDialog`が`frontend/src`に1件も存在しないことを全文grepで確認。
- `StopPoiKind`が8値であることは`backend/app/domain/traffic.py:18-27`と生成物`poi-kinds.json`の両方で確認。
- `route_preference.yaml`の不在は`find`と`docs/architecture.md:1033,1057,1078`で確認。

問題が無いことを確認した観点:
- 設計原則「1本道」: 対象16ファイルに軸id名指し分岐は実装コードに1件も無く、ramp軸のレイヤーid・凡例・絞り込み軸はすべて`axisMapLayerId`／`rampAxes.map(...)`で機械導出されている。
- 生成物との同期: `windLayer.ts`の詳細格子間隔は`wind-grid-config.json`を片側importし、`windLayer.test.ts`が配列全体一致と点数上限の安全率を検証している。`surface-tags.json`・`poi-kinds.json`も同様のドリフト検知テストを持つ。
- デッドコード: 対象ファイルの全exportについて本番消費者をgrepで数え、消費者0のものは無かった。
- 無駄な再計算: `ROUTE_STYLE_MODES`・`SECONDARY_AXES`・`STATIC_FILTER_AXES`相当はモジュールレベル定数かuseMemo済み。

---

## S7a: frontend/src/components の AxisStudio・MapOverlayControls・RouteAxisProfile

### overall

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 270 / category: 使われない高コスト通信 / severity: P2 / summary: 「かけあわせ評価」(`recipe_then_breakpoint_linear`)でも生値分布のPOSTが走るが、その結果を描画する`BreakpointCurveEditor`/`DistributionPreview`はどちらも`draft.shapeKind === "breakpoint_linear"`のブロック（806行）の中にしかなく、取得結果・loading・errorのいずれも消費されない / failure_scenario: /adminで「かけあわせ評価」を選び軸や係数を変えるたびに`POST /admin/api/axis-definitions/preview-distribution`（初回Way抽選で1秒前後）がデバウンス後に毎回発火する。`terms`は材料idではなくaxis_idのため応答は使えず、失敗しても`error`を描く場所が無いので画面には何も出ない（無言のサーバー負荷）。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 684 / category: 状態の持ち越し（契約不一致） / severity: P2 / summary: テンプレート切替時に`terms`を作り直すのは「→かけあわせ」「かけあわせ→なめらか」の2経路だけで、間に「ぴったり評価」を挟むと`d.shapeKind`が`categorical`になり666行の条件が成立せず、axis_idを持ったままの`terms`が`breakpoint_linear`へ持ち越される / failure_scenario: 「かけあわせ評価」→「ぴったり評価」→「なめらか評価」と選び直すと、材料セレクトの`value`が候補一覧に無いidのままになり、ブラウザは先頭の材料（例:「勾配」）を表示する。ユーザーは勾配を選んだつもりで保存するが`buildShape`はaxis_idを`material`として送信し、画面表示と保存内容が食い違った軸ができる。

- file: frontend/src/components/AxisStudio/scoreDistribution.ts / line: 22 / category: 死んだデータ＋規則の二重定義 / severity: P2 / summary: `BAND_EDGES`の`min`/`max`はリポジトリ全体でどこからも読まれず（消費者は`edge.label`と`BAND_EDGES.length`だけ）、帯の境界値25/50/75は59〜64行のif連鎖へ別途べた書きされている / failure_scenario: 得点帯を変えようと`BAND_EDGES`のラベルと`min`/`max`を書き換えても、`scoreBands`のif連鎖は25/50/75のままなので分類だけ旧境界で動き続ける。ラベルと中身がずれた棒グラフが出るが、型エラーもテスト失敗も起きない。

- file: frontend/src/components/AxisStudio/breakpointTools.ts / line: 58 / category: 同じ規則の写経 / severity: P3 / summary: 区分線形補間（backend `evaluate_breakpoint_linear`と同じ規則）が`interpolateBreakpointScore`と`scoreDistribution.ts:32 scoreForValue`の2箇所に別実装で存在し、丸め（前者は小数1桁、後者は丸めなし）とx1===x0時の返り値（前者y0、後者y1）も食い違う / failure_scenario: backend側の補間仕様を直すとき片方だけ追従し、「効き目プレビュー表の点数」と「得点分布バーの帯」が同じ折れ点・同じ値に対して別の帯を示す。

- file: frontend/src/components/RouteAxisProfile/AxisContributionBar.module.css / line: 31 / category: 撤去済み機構の残骸 / severity: P3 / summary: `.legendDot`(31-35)・`.legendLabel`(37-39)と`.legendTrigger[aria-expanded="true"] .legendLabel`(59-61)は、凡例をアイコン+数値だけにした後の残骸で参照がこのディレクトリに1件も無い / failure_scenario: 凡例の見た目を直す担当者が`.legendLabel`の色指定を触って「効かない」と時間を溶かす。`aria-expanded`セレクタは仕様が生きているように読めるが、対応する要素が存在しない。

- file: frontend/src/components/RouteAxisProfile/AxisContributionBar.tsx / line: 77 / category: 不要な二重評価＋意図しない一律減光 / severity: P3 / summary: `renderDetail`が1軸あたりfilterと本体で2回呼ばれ（1回目のJSXは捨てられる）、さらに`renderDetail`未指定の呼び出し（区間クリック詳細）では全チップが`data-checked="false"`になり`axisLegend.module.css:54`の`opacity: 0.55`が凡例全体へ掛かる / failure_scenario: 地図でルート区間をタップして開くボトムシートでは、押せる軸が1つも無いため内訳の凡例が丸ごと55%の不透明度で描かれる。CSS側のコメントが説明する「押せない軸だけを薄くして区別する」という意図は、この経路では区別として機能しない。

- file: frontend/src/components/RouteAxisProfile/RouteAxisProfile.tsx / line: 74 / category: 同じ規則の写経 / severity: P3 / summary: 「`axisContributions`が`null`または0の軸を除く」判定が`RouteAxisProfile`(74-77)と`AxisContributionBar`(53-56)の両方にあり、コメント自身が「判定がずれないよう同じ条件にする」と手動同期を前提にしている / failure_scenario: 絞り込み条件（例: 負値の扱い）をどちらか一方だけ変えると、「表示できる評価軸データがありません」の案内文が出ているのに帯と凡例も描かれる、あるいは逆に空の帯だけが残る。

- file: frontend/src/components/AxisStudio/axisDraft.ts / line: 171 / category: 暗黙の順序依存 / severity: P3 / summary: `emptyDraft`の`terms`初期値は`materialOptions[0]?.id`をdtype無視で採るが、`AxisComposer`の材料セレクト(739行)は`numeric`/`boolean`のみを候補にする / failure_scenario: `material_catalog.py`の`MATERIAL_CATALOG`先頭へcategorical材料を足すと、新規作成フォームの既定termが候補に無いidになり、セレクトは2番目以降の材料を表示したまま保存時にcategorical材料を`breakpoint_linear`のtermとして送る（backendの評価でエラー）。現状は先頭が`gradient_percent`(numeric)のため顕在化していない。

- file: frontend/src/components/AxisStudio/scoreDistribution.ts / line: 73 / category: 表示文字列への依存 / severity: P3 / summary: `distributionWarnings`が帯を`b.label === "100点"` / `"0点"`という**表示ラベル文字列**で引いている / failure_scenario: `BAND_EDGES`のラベルを言い換えた瞬間、満点張り付き・0点偏りの警告が`?? 0`で常に0扱いになり、警告が一切出なくなる（型もテストも通る）。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 776 / category: 無駄な失敗リクエスト / severity: P3 / summary: `MaterialRangeHint`はterms行全体の中にあり、「かけあわせ評価」でaxis_idを持つ行に対しても`GET /admin/api/material-distribution/{axis_id}`を投げる。モジュール内キャッシュは成功時しか埋めないため失敗は毎マウント繰り返される / failure_scenario: 「かけあわせ評価」で軸を3本組み合わせると、行が描かれるたびに3本の404が出て`debugLog`と`/api/debug/stats`を汚す（画面には何も出ない）。

- file: frontend/src/components/AxisStudio/BreakpointCurveEditor.tsx / line: 3 / category: 説明の重複 / severity: P3 / summary: ファイル先頭コメント(3-10)と`BreakpointCurveEditor`のJSDoc(36-41)がほぼ同文で、同じ内容がさらに`docs/modules/frontend/axis-studio.md`にもある / failure_scenario: 仕様が変わったとき片方だけ直り、どちらが現行かを読み手が判断できなくなる。

### consistency

- file: docs/design-principles.md / line: 135 / category: 正本ドキュメントと実装の逆転 / severity: **P1** / summary: 「消さずに薄くする……重み0の軸は薄いチップとして同じ並びに残し、詳細を開く操作だけを持たせない」と書いてあるが、実装は`AxisContributionBar.tsx:77`のfilterで重み0の軸をチップごと落とす。`docs/tasks/T783.md`が「薄く残す扱い（T776）はユーザー判断で撤回した」と明記しており、撤回がdesign-principles.mdへ反映されていない / failure_scenario: CLAUDE.mdが「設計原則の唯一の正本（常に最新）」と指定している文書のため、次に軸まわりのUIを作る担当者が重み0の軸を薄く残す実装を書き、T783でユーザーが撤回した挙動が復活する。

- file: docs/modules/frontend/route-settings-and-results.md / line: 235 / category: モジュール文書と実装の乖離 / severity: P2 / summary: 「公開軸すべてを渡せば、寄与が出ない軸も薄いチップとして残る」(235-236)と「軸ごとにnullを返せばその軸だけ押せない」(238-240)がどちらも現行と逆。nullを返した軸は「押せないチップ」ではなくfilterで除去される。226行の「名前は……押せないチップの`aria-label`が持つ」も成り立たない / failure_scenario: このモジュール文書を根拠に`AxisContributionBar`を再利用した別画面が「渡せば薄く残る」前提で`legendAxes`へ全軸を渡し、意図した軸が黙って消える。

- file: frontend/src/components/RouteAxisProfile/AxisContributionBar.tsx / line: 25 / category: コメントと実装の食い違い / severity: P2 / summary: `legendAxes`のprop説明・`renderDetail`の説明と、`RouteAxisProfile.tsx:79-81`の「チップ自体は消さず薄く残るため『消さずに薄くする』はそのまま成り立つ」が、いずれも77行のfilter（null→除去）と矛盾する / failure_scenario: propのドキュメントを信じた呼び出し側が「押せないチップが出るはず」と実装し、実機では何も出ないことに気づくのがレビュー後になる。

- file: frontend/src/components/RouteAxisProfile/AxisContributionBar.test.tsx / line: 99 / category: 契約が検証されていない / severity: P2 / summary: `legendAxes`を渡すテストがリポジトリ全体で1件も無い。「寄与が出ないが重みはある軸を凡例に残す」という`legendAxes`の唯一の存在理由が、このコンポーネント自身のテストでは固定されていない / failure_scenario: `(legendAxes ?? rows)`を`rows`へ単純化するリファクタをしても`AxisContributionBar.test.tsx`は全緑のまま通り、「重みはあるが寄与0/欠損の軸」が静かに消える。

- file: frontend/src/components/AxisStudio/axisDraft.ts / line: 210 / category: 実在しない識別子・誤った個数 / severity: P2 / summary: 「`AxisShape`は3種のPydantic discriminated unionの構造をそのまま写した型のため、"terms"/"material"/"flags"というフィールド有無による判別も可能」とあるが、`types/route.ts:89`の`AxisShape`は2種で、`flags`はbackend・frontendのどちらにも存在しない / failure_scenario: shapeを増減するときにこのコメントを手掛かりに「3種目・flagsフィールド」を探して見つからず時間を溶かす。`docs/modules/frontend/axis-studio.md`は正しく「2プリミティブ」と書いており、コード側だけが古い。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 638 / category: 宣言している挙動と実装の不一致 / severity: P2 / summary: 「このコンポーネントはレイヤー固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要」と書いてあるが、`LAYER_ICONS`(136行)は`Record<MapLayerId, …>`で静的なレイヤーidを全件要求し、`gradientFill`・`disaster`・`windVector`といった個別レイヤーの事情がコメント込みでこのファイルに入っている / failure_scenario: `mapLayers.ts`の`MapLayerId`へ新しい静的レイヤーを足すと`LAYER_ICONS`がtscエラーになり、「変更不要」という記述を信じた担当者が原因箇所を探すことになる。実際に変更不要なのは軸カタログ由来の動的idだけで、条件がコメントに書かれていない。

- file: frontend/src/components/AxisStudio/breakpointTools.ts / line: 50 / category: 成立しなくなった前提 / severity: P2 / summary: `sortBreakpoints`のdocstringが「ドラッグ・数値入力・自動生成のいずれの後も呼ぶ」と宣言しているが、実際の呼び出し元は3箇所だけで、ドラッグも数値入力も並べ替えを通らない / failure_scenario: この宣言を信じて「折れ点は常に昇順」を前提にした処理を足すと、隣の点を追い越すドラッグで前提が破れる。現状は`validateStep`の昇順チェックが「次へ」でユーザーを止めるだけで、曲線エディタ側のグラフ交差表示は防げていない。

- file: frontend/src/components/AxisStudio/AxisStudio.tsx / line: 299 / category: 削除済み機能の名指し / severity: P3 / summary: `DialogContent`のコメントが「AxisComposerは材料/折れ点/**フラグ**の可変長リストを持つ」と書くが、フラグはUIにもshapeにも存在しない / failure_scenario: モーダル幅を見直す担当者が「フラグの欄」を探して見つからず、コメントが指す現行の可変長リストがどれかを判断できない。

- file: frontend/src/components/AxisStudio/breakpointTools.ts / line: 77 / category: 経緯コメント／docsとの二重メンテ / severity: P3 / summary: 「末尾へ既定値[0,0]を足すだけの旧実装は……」は`docs/comments.md`が禁じる経緯で、かつ同じ経緯が`docs/modules/frontend/axis-studio.md:195-197`にも書かれている / failure_scenario: docs側だけ更新されコード側が残る。方針どおりならコード側は削除して`docs/modules`へ一本化する対象。

- file: frontend/src/components/AxisStudio/curveDistributionOverlay.ts / line: 30 / category: 要素の数え上げ / severity: P3 / summary: 「全6分位を出すと線だらけになるため、外れ・中央・外れの3本に絞る」は個数の言明で、分位の実体は backend生成の`quantiles`（現状p10/p25/p50/p75/p90/p99の6件） / failure_scenario: backendへp95を足すと「全6分位」が誤りになるが、機械検査は無く誰も気づかない。

裏取りした事実:
- `types/route.ts:89`の`AxisShape`は2メンバー、backendの`kind`リテラルも2つ。`flags`は双方にgrepで0件。
- `docs/tasks/T783.md`に「重み0＝詳細を持たない軸のチップは**出さない**。薄く残す扱い（T776）はユーザー判断で撤回した」と明記。`RouteAxisProfile.test.tsx:63`が現行挙動を固定しており、**実装とテストが正・design-principles.md/route-settings-and-results.md/コメントが古い**という向きで確定。
- `BAND_EDGES`の`min`/`max`、`.legendDot`/`.legendLabel`はリポジトリ全体grepで消費者0件。`iconStatusDot_*`は動的参照があり生きている（誤検知を排除済み）。

問題が無いことを確認した観点:
- 設計原則「軸ごとのファイル・関数・定数・propを新設しない（1本道）」への違反は3ディレクトリとも無し。`LAYER_ICONS`が名指しするのは軸ではなく手書きレイヤーidで別の分類。
- `axisDraft.ts`の`_PayloadKeyCoverage`と`MaterialCoveragePanel`の`GROUP_BY_SEMANTICS`はいずれも「増えたら型で落ちる」設計で、数え上げの罠を正しく避けている。
- `docs/modules/frontend/axis-studio.md`の対象ファイル表は漏れなく、記述内容も実装と一致。
- `MapOverlayControls.test.tsx`に「実装を変えても落ちない」テストは見当たらなかった。

---

## S7b: frontend/src/components の残り（RouteForm・RouteSettingsPanel・BottomSheet・RouteSplicePanel・TodayOutlook・WeatherPanel・ComparisonPanel・LensControl・ui・直下ファイル）

（原文は絶対パスで出力されていたためリポジトリ相対へ正規化した）

### overall

- file: frontend/src/components/RouteSplicePanel/RouteSplicePanel.tsx / line: 76 / category: 契約不一致（3値の状態を2値へ潰している） / severity: P2 / summary: `stretches.length === 0`を無条件に「同じ道を通る」と表示するが、`pairedStretches`（page.tsx:804-807）は**区間の対応づけを諦めたとき**にも空配列を返すため、まったく別の道を通る2本に「この2本は同じ道を通ります。」と出る / failure_scenario: 目的地モードで生成し、比較相手に`edge_ids`が空の候補（本パネル自身のコメントが「エンジン・古い候補では空で返る」として想定している状態）を選ぶ→`differingStretches(displayed, [])`が1区間、`differingStretches([], displayed)`が0区間で本数が食い違い`pairedStretches`が`[]`を返す→実際は全区間が別の道なのに「同じ道を通ります」と断言される。`unavailable`ガードは`displayed.edge_ids`しか見ておらず`targets`側を見ていない。

- file: frontend/src/components/TodayOutlook/TodayOutlook.module.css / line: 15 / category: デザイントークン非準拠 / severity: P2 / summary: `TodayOutlook.module.css`・`WeatherPanel.module.css`・`RouteSplicePanel.module.css`は`--font-size-*`/`--space-*`/`--radius-*`を1箇所も使わず生の`rem`/`px`を直書きしており、`globals.css:208-217`がモバイル(≤640px)でトークンを圧縮する仕組み（T505）から外れている / failure_scenario: スマホ実機で表示すると、トークンを使う`RouteForm`/`LensControl`/`ComparisonPanel`の文字だけが0.8rem→0.75remに縮み、常設ヘッダー（WeatherPanelの0.95rem）・「今日」パネル（0.62〜0.9rem）・「区間の乗り換え」（13px固定）は縮まないため、同一画面内で文字サイズの基準が2系統に割れる。とくに`RouteSplicePanel`の`px`はルートfont-sizeにも追従しない。

- file: frontend/src/components/WeatherPanel/amedasWeatherIcon.ts / line: 32 / category: 同じ規則が複数箇所へ書き写されている / severity: P2 / summary: 天気カテゴリの日本語ラベルと「晴れだけ昼夜でアイコンを替え、他は`ICON_BY_CATEGORY`を引く」という組み立て規則が`amedasWeatherIcon.ts:32-59`と`weatherCode.ts:60-97`に丸ごと二重化しており（さらに`weatherCode.test.ts:11-22`に3つ目の複製）、一致を強制する検査が無い / failure_scenario: `weatherCode.ts`側だけ「くもり」を「曇り」に直す→常設ヘッダー（アメダス実測）とその真下の「今日の見通し」（MSM予報）が同じ`CloudIcon`に対して別の語を出す。`weatherCode.ts:57-59`のコメントが「別の呼び方をすると『別のことを言っている』と読める」と明示的に禁じている状態が、型でもテストでも現れずに成立する。

- file: frontend/src/app/page.tsx / line: 811 / category: 一覧と地図の母集団のずれ / severity: P3 / summary: パネルの区間行は`splicePairs`全件から作るのに、地図の帯`spliceStretchFeatures`は`stretchCoordinateRange`がnullまたは座標2点未満の区間を落とすため、行数と帯の本数が一致しないことがある / failure_scenario: `edge_point_offsets`と`edge_ids`の対応が取れない候補で「2本目の区間」を押しても地図に何も現れない。パネルの(i)は「比較相手を選ぶと、その区間が地図にオレンジの帯で出ます」と断言しているため、利用者は操作が効いていないと読む。

- file: frontend/src/components/RouteSplicePanel/RouteSplicePanel.module.css / line: 169 / category: 共有コンポーネントの迂回 / severity: P3 / summary: `.actions button`・`.head select`という要素セレクタで生のボタン／セレクトへ直接スタイルを当てており、`components/ui/Button`を使っていない（`ui/Button.tsx:5-8`が「見た目の決定箇所をこのコンポーネントへ集約する」と宣言している唯一の例外） / failure_scenario: `Button`の`secondary`バリアントの枠線色・disabled表現を変えても「この組み合わせを候補へ追加」だけ取り残され、同じ役割のボタンが画面によって別の見た目になる。

- file: frontend/src/components/WeatherPanel/weatherCode.ts / line: 90 / category: 到達しない引数・不要な抽象化 / severity: P3 / summary: `getWeatherCodeDisplay(weatherCode, isDay)`の`isDay`は唯一の呼び出し元（`TodayOutlook.tsx:49`）が常に`1`を渡すため`MoonIcon`分岐に到達せず、`weatherCode.test.ts:43-48`がその到達しない分岐を固定している / failure_scenario: コマ単位`is_day`が将来入ったとき、引数を通す配線が既にあると誤認して呼び出し側だけ直し、`amedasWeatherIcon`側（`isDay: boolean`、型が違う）との整合を取り損ねる。

- file: frontend/src/components/ComparisonPanel/ComparisonPanel.tsx / line: 147 / category: 一意でないReact key / severity: P3 / summary: 行のkeyに表示ラベル（`row.label`）を使っているが、行は「ルート属性の固定ラベル」「材料カタログのラベル」「軸カタログのラベル」という独立した3つの名前空間から集めており、衝突を防ぐものが無い / failure_scenario: 軸スタジオで軸ラベル「勾配」を作り、材料カタログにも「勾配」がある状態で比較表を開くとkey重複警告が出て、行の差分更新が入れ替わりうる。

- file: frontend/src/components/RouteSplicePanel/RouteSplicePanel.tsx / line: 95 / category: 内部単位の露出 / severity: P3 / summary: 区間の行が持つ唯一の識別情報が`{stretch.end - stretch.start}区画ぶん`（`edge_ids`の本数）で、利用者が区間を選び分ける材料になっていない / failure_scenario: 区間が2本以上出たとき、「1本目=3区画／2本目=3区画」のように同じ表示になり、地図の帯を見比べる以外に区別できない。

### consistency

- file: frontend/src/components/BottomSheet/BottomSheet.tsx / line: 192 / category: コメントが存在しないセレクタを名指し / severity: P2 / summary: 「`.app-sidebar button, .app-bottom-sheet button`等のモバイル向けタップ領域ルールが参照するマーカークラス」と書いているが、そのブランケットルールは撤去済みで、`globals.css:454-458`は`.app-sidebar`を「マッチ対象が存在しない死んだセレクタだった」として削除したと明記している。現存するのは`.app-bottom-sheet input[type=checkbox]/[role=checkbox]/input[type=text|number]/label`だけで、`button`は1つも無い / failure_scenario: `app-bottom-sheet`の要否を判断する人がコメントどおり`button`ルールを探して見つからず、クラスごと不要と判断して外す→iOSの自動ズーム防止（inputのfont-size:16px）とチェックボックス拡大が丸ごと失われる。

- file: frontend/src/components/ui/Card/Card.tsx / line: 5 / category: コメントが撤去済みコンポーネントを名指し / severity: P3 / summary: Cardを使わない理由の説明が「ComparisonPanel/RouteSettingsPanel/`MapLayersPanel`の`.panel`は…」と、T769以降のUI再編で撤去された`MapLayersPanel`を現存物として挙げている / failure_scenario: Cardの適用範囲を見直す人が`MapLayersPanel.module.css`を確認しに行って存在せず、この判断の根拠を再構成できない。

- file: docs/frontend-design-system.md / line: 93 / category: 文書が実装に無いAPIを宣言 / severity: P3 / summary: `components/ui/`一覧が`Button`のvariantを「primary/secondary/**danger**/ghost」と書くが、`ui/Button/Button.tsx:17-23`の`cva`にはprimary/secondary/ghostしか無い / failure_scenario: 「削除」系の確認ボタンを足す人が表を信じて`variant="danger"`と書き、tscで落ちてから実装を読み直す（実害はビルド時に止まるが、表の他の行の信頼性も落ちる）。

- file: docs/frontend-design-system.md / line: 103 / category: 全件列挙の表が実態と合っていない / severity: P3 / summary: 「CSSのみの共有スタイル」表が`ui/`配下の`*.module.css`を全件列挙する形をとりながら`unusedBadge.module.css`（`LensControl.module.css:156`が`composes`で使用中）を落としている。この表は機械検査の対象外 / failure_scenario: 共有したい見た目が出たとき、この表に無いから存在しないと判断して2つ目の「未使用バッジ」CSSを新設する。

- file: docs/frontend-design-system.md / line: 171 / category: 文書中の唯一の実例が撤去済み / severity: P3 / summary: 44pxタップ領域を「本当にメインの導線だけが個別に持つ」という現行方針の唯一の具体例が`MapLayersPanel.module.css`の`.layerTitle`で、そのファイルは存在しない / failure_scenario: 新しい主要導線に44pxを付ける人が、参照すべき現存の手本を辿れない。

- file: docs/modules/frontend/route-settings-and-results.md / line: 305 / category: 実在しない識別子 / severity: P3 / summary: `useRouteFormSubmit`の受け取りprop列挙が`destinationState`と書くが実装は`destinationSet`。`scripts/review_checks.py docs`の「死んだ識別子参照」が既に検知している / failure_scenario: prop名でgrepして辿れず、フックの入出力契約を読み違える。

- file: docs/modules/frontend/page-composition.md / line: 225 / category: 文書が実装と違う差し込み口を書く / severity: P3 / summary: 「`headerAction`propとして`renderRouteSectionHeaderActions()`（タブ列＋「ルート生成」ボタン）を渡す」とあるが、実装は`headerLead`/`headerAction`に分かれている（S5と重複） / failure_scenario: BottomSheetのヘッダ構成を変える人が「タブはheaderActionの中」という前提で`headerLead`を未使用と判断し、タブ列を右上のアクション群へ寄せてしまう。

- file: frontend/src/components/TodayOutlook/TodayOutlook.tsx / line: 168 / category: 経緯コメント＋数え上げ / severity: P3 / summary: 「8コマがスマホ横幅に収まりきらない場合は…（ユーザーからの明示許可: …）」という1つのコメントに、経緯（誰の指摘で）と個数（8コマ）が同居している。`review_checks.py docs`の経緯コメント検知が既に参考出力に挙げている唯一の本シャード該当箇所 / failure_scenario: backendの`today_periods`のコマ数が変わると「8コマ」が嘘になり、横スクロールの条件を読む人が実際と違う前提を持つ。

- file: frontend/src/components/WeatherPanel/weatherCode.ts / line: 21 / category: 数え上げ / severity: P3 / summary: 「10値だけ」「6カテゴリ」、`amedasWeatherIcon.ts:9`「4カテゴリ」、`ui/statusDot.module.css:21`「3状態」と、増減で嘘になる個数が各所にある。とくに`statusDot.module.css`は同じコメント内で「状態が増えたときに呼び出し側へ手を入れずに済む」と増加を前提にしながら数を固定している / failure_scenario: `domain/weather.py: derive_weather_code`が霧・雷雨を返すようになった時点で「10値だけ」が誤りになり、フォールバック方針の説明が読者を誤導する。

- file: frontend/src/components/BackendStatus.tsx / line: 11 / category: 経緯コメント / severity: P3 / summary: 「…競合が実機で発生した（例: 新しい方がok→古い方がタイムアウトでngになりngのまま固定）ため、…」と、いつ何が起きたかの経緯を書いている。検知器のトリガー語に当たらず機械検出をすり抜けている / failure_scenario: 同型のコメントが「検知されないから方針に適合している」と見なされて増える（`MapView.tsx:3019`が既に参照している）。

- file: frontend/src/components/Map/dynamicWeather.ts / line: 117 / category: コメントが成立しなくなった前提を名指し / severity: P3 / summary: `formatDynamicFrameTime`/`formatDynamicFrameHourMinute`の説明が「WeatherPanelの左端インジケータ」「WeatherPanelのルーラー目盛りラベル」と書くが、現在の`WeatherPanel.tsx`は瞬間値の統計チップ1行のみでルーラーもインジケータも持たない。実際の消費者は`RideConditionBar/departureTimeline.ts`と`TodayOutlook.tsx` / failure_scenario: 時刻ラベル書式を直す人がWeatherPanelを見に行き、該当UIが無いため影響範囲を見誤る。

裏取りした事実:
- `MapLayersPanel`は実装から完全に消えている。grepのヒットはレビュー履歴と`docs/architecture.md:2018,2349`、`docs/frontend-design-system.md:171`、`ui/Card/Card.tsx:5`のみ。
- `review_checks.py docs`をフル実行し、本シャード該当の既存検知は3件（`route-settings-and-results.md:218,305`の死んだ識別子、`TodayOutlook.tsx:169`の経緯コメント）であることを確認。上記のうち検査器が拾っていない指摘はいずれも現在の検知器の対象外。
- `globals.css:208-217`がモバイルで`--font-size-xs/sm/md`と`--space-1〜4`を実際に再定義していること、`.app-bottom-sheet button`ルールが`globals.css`に存在しないことを目視確認。
- `ui/`配下の9つの`*.module.css`すべてに消費者が存在し、`Map/icons.tsx`の45個のエクスポートにも未使用は無い。

問題が無いことを確認した観点:
- 設計原則「1本道」: 本シャードの実装ファイル全体を軸idでgrepした結果、名指し分岐はゼロ件。`RouteSettingsPanel`・`ComparisonPanel`・`LensControl`はいずれも軸カタログ／材料カタログ駆動で、`HardFilterPanel`のキーと既定値も生成物由来。
- デッドコード: `ui/`の全コンポーネント・全共有CSS、`BackendStatus`、`amedasWeatherIcon`/`weatherCode`に消費者ゼロのものは無い。`icons.tsx`にも未使用エクスポートは無く、アイコン定義の重複もない。
- `lens`の永続値の健全性: `LensControl`の`?? { label: lens }`フォールバックは生の軸idを見せうるが、`page.tsx:700-708`が`routeStyleModes`に無い保存値を`LENS_DIFFICULTY_ID`へ戻すため、恒常的に露出する経路は無い。
- テストの契約検証: `BottomSheet.test.tsx`・`RouteSplicePanel.test.tsx`・`RouteSettingsPanel.test.tsx`はいずれも実装を変えれば落ちる形。ただし`ComparisonPanel.test.tsx`・`RouteSettingsPanel.test.tsx`のit名／先頭コメントは経緯記述を含み（検知器はテストを対象外）、`weatherCode.test.ts:43-48`は本番で到達しない`MoonIcon`分岐を固定している。

---

## S8: frontend/src の lib・hooks・services（33ファイル）

### overall

- file: frontend/src/hooks/useDynamicWeatherLayers.ts / line: 132-134, 383-389 / category: 規則の書き写し / severity: P2 / summary: 災害グループのソースキー文字列が、`page.tsx`の`DISASTER_SOURCE_LEGEND`（297-305）・フェッチ有効判定の配列リテラル・`dynamicWeather.disaster`オブジェクトの3箇所へ独立に手書きされており、一致を保証するのはコメントだけ。`hiddenDisasterSources: readonly string[]`なので型でも守られない / failure_scenario: `page.tsx`の凡例で`landslide`→`landslideRisk`へ改名すると、利用者が▶パネルで「土砂災害キキクル」のチェックを外しても`hiddenDisasterSources`に入るのは`landslideRisk`で、`showDisasterSource("landslide")`は依然true。面が消えず、混色して他の危険度が読めないまま二度と消せない。tsc・eslintは通り、`useDynamicWeatherLayers.test.ts`も同じ7キーをハードコードしているため落ちない。

- file: frontend/src/hooks/usePolledFetch.ts / line: 40 / category: 汎用フックに残った個別既定値 / severity: P3 / summary: 汎用ポーリングフックの`debugLogCategory`の既定値が特定用途の`"api:jma-nowcast-times"`。`useDynamicWeatherLayers.ts`の6呼び出しはいずれも指定を省略しているため、全系統の取得失敗がこの1カテゴリへ混ざる / failure_scenario: キキクルが落ちていて画面に出ないとき、DebugConsole/BackendLogsPanelでカテゴリ「危険度分布」相当を探しても1行も無く、`api:jma-nowcast-times`（降水ナウキャスト）に紛れている。原因切り分けが遅れる。

- file: frontend/src/services/healthApi.ts / line: 4-15 / category: 骨格の非共有 / severity: P3 / summary: `services/`配下で唯一`lib/fetchJson.ts`の共通骨格を通らず素の`fetch`を使い、失敗を`catch {}`で握り潰すため、backend疎通の失敗・タイムアウトがdebugLogへ一切残らない。`fetchJson.ts`のモジュールコメント（4-12行）が「骨格を各クライアントへ写経すると非対称が静かに生まれる」と警告している当のパターン / failure_scenario: 「サーバーに接続できません」表示が出たとき、デバッグモードをONにしても`/health`の試行記録・x-request-idがどこにも無く、タイムアウトなのかHTTPエラーなのか通信断なのかを画面から判別できない。

- file: frontend/src/services/regionApi.ts / line: 9-22 / category: 消費者ゼロの抽象 / severity: P3 / summary: `postAndCheckOk`の`body`省略分岐は唯一の呼び出し元`fetchAxisInspector`が常にbodyを渡すため到達しない。その存在理由としてコメントが名指しする`refreshBasemapCache`はリポジトリ全体grepで0件 / failure_scenario: 実害は無いが、分岐と`requestMeta`のスプレッドが「2種類の呼び出しを支えている」ように読め、実際には1種類しか無い。

- file: frontend/src/services/axisAdminApi.ts / line: 16 / category: 命名衝突 / severity: P3 / summary: `debugAdminApi.ts:12`と併せて、モジュール内ローカル定数`API_BASE_URL`が「オリジン」ではなく「パス」（`/admin/api/axis-definitions`）を指しており、`lib/apiBaseUrl.ts`のexport `API_BASE_URL`（オリジン）と同名・別意味 / failure_scenario: 別ファイルからのコピペで`${API_BASE_URL}/api/...`の形を持ち込むと、`/admin/api/axis-definitions/api/...`という無意味なURLになる。型はstringのまま通る。

- file: frontend/src/lib/apiBaseUrl.ts / line: 1-3 / category: 数え上げ / severity: P3 / summary: 消費者7ファイルを全件列挙している。現時点では一致するが、8本目のクライアントを足した瞬間に嘘になる / failure_scenario: 一覧を信じて「この7つだけ直せばよい」と判断し、後から増えたクライアントを取り残す。

### consistency

- file: frontend/src/hooks/useWeatherGrid.ts / line: 25-27 / category: 死んだ識別子・成立しない前提 / severity: P2 / summary: `WEATHER_GRID_REFRESH_INTERVAL_MS = 3時間`の根拠として「バックエンド側のTTLキャッシュ（weather_client.py: WIND_GRID_CACHE_TTL_SECONDS）に合わせた」と書いているが、`backend/app/services/weather_client.py`もその定数も存在しない（T645でMSMの`.om`ローカル読み出しへ全面移行し、TTLキャッシュ自体が無い）。「これより短い間隔で再取得してもキャッシュヒットするだけ」も現在は偽 / failure_scenario: 風の更新が遅いという指摘を受けた担当者が、コメントに従って`weather_client.py`のTTLを探すが見つからず、間隔を短縮してよいかの判断根拠を失う。あるいは「キャッシュヒットするだけ」を信じて短縮し、MSM読み出し負荷を無自覚に増やす。

- file: docs/modules/frontend/page-composition.md / line: 27 / category: 実在しない環境変数名 / severity: P2 / summary: 「ブラウザからのfetch先（`NEXT_PUBLIC_API_BASE_URL`）」と書いているが、`lib/apiBaseUrl.ts:8`が読むのは`NEXT_PUBLIC_API_URL`。`.env.example:21`・`docker-compose.yml:7`・`README.md:123`もすべて`NEXT_PUBLIC_API_URL` / failure_scenario: 新しい環境を立てる人がこのモジュール文書どおり`NEXT_PUBLIC_API_BASE_URL`を設定し、`API_BASE_URL`が既定の`http://localhost:8000`のままになる。ブラウザからのAPI呼び出しが全滅するが、エラーは「接続できません」だけで設定名の誤りには気づけない。

- file: docs/modules/frontend/page-composition.md / line: 19 / category: 設計↔実装の乖離（S5と重複） / severity: P2 / summary: 並び順の規約を「最短経路は先頭固定」と距離基準で書いているが、実装も正本のbackendも先頭固定するのは`is_fastest`＝所要時間最短。加えて`lib/routeTabLabel.ts:50`の`shortestDistanceRouteId`（距離最短の印）という別概念が同居しているため、「最短経路」がどちらを指すか文書からは決められない / failure_scenario: 差し込み位置を直す担当者が距離順を前提に`insertByDifficulty`を読み、`is_fastest`が距離最短だと誤解する。目的地モードで「距離は長いが速い基準線」が先頭にいる実データと突き合わせると辻褄が合わず、正しい実装をバグとして「修正」しかねない。

- file: frontend/src/services/materialCatalogApi.ts / line: 22-25 / category: 置き換え済みの契約を記述 / severity: P3 / summary: 「DB未接続・DB障害はいずれも`{values: []}`（200）を返す」と書いているが、現在の`MaterialValuesResponse`は`available`を持ち、唯一の消費者`useMaterialValues.ts:51`は`response.available === false`で「候補が無い」と「出せなかった」を区別している / failure_scenario: このコメントを契約と信じて`available`を「使われていないフィールド」と判断し削除すると、DBタイムアウトが「値が無い材料」として軸スタジオに静かに表示される状態へ戻る。

- file: frontend/src/services/regionApi.ts / line: 74-75, 87 / category: 同一ファイル内の自己矛盾 / severity: P3 / summary: 74-75行が「stop_poiのみの1レイヤー構成（交差点密度は地図上の独立可視化レイヤーとしては提供しない）」と書く一方、87行は「POI/交差点密度レイヤーも同じズーム範囲に準拠する」と、提供しないはずのレイヤーを現存物として扱っている / failure_scenario: 交差点密度レイヤーを探して`staticAttributeLayers.ts`・backendを往復し、存在しないものを追う。

- file: frontend/src/hooks/useAxisCatalog.ts / line: 34 / category: 宣言と実装の不一致 / severity: P3 / summary: `defaultWeights`のJSDocが「未知のaxis_idには0を返す」と書いているが、実体は素のオブジェクトで未知キーは`undefined`。型上は`number`なので検査も通らない。`RouteSettingsPanel.tsx:119`が`catalog.defaultWeights[axisId] || 0.1`と自前で穴埋めしている / failure_scenario: このJSDocを信じて`const w = catalog.defaultWeights[axisId]; if (w > 0) {...}`と書くと、未公開軸・タイポ混入時に`undefined > 0`で常にfalseへ倒れる。あるいは`undefined`のまま`route_preference`へ入れて`JSON.stringify`がキーごと落とし、backendのキー完全一致検証で422になる。

- file: frontend/src/hooks/useWeatherConditions.ts / line: 4-5, 53 / category: 数え上げ（かつ内部矛盾） / severity: P3 / summary: 冒頭が「4つとも…同じ形のeffectを持つ」と書く一方、53行は「本ファイルの5つのフェッチが同じ骨格を持つ」と書く。実際の`useLocationFetch`呼び出しは5本 / failure_scenario: 数を頼りに読むと1本を見落とす。バッジを1種増やすと両方の記述が同時に嘘になる。

- file: frontend/src/hooks/usePolledFetch.ts / line: 31-35 / category: 数え上げ（三者三様） / severity: P3 / summary: 「…5箇所（降水ナウキャスト・降水短時間予報・雷竜巻ナウキャスト・キキクル・線状降水帯予測マップ）独立実装されていた」——雷放電位置データが漏れており当該ファイルの実数は6。`docs/modules/frontend/dynamic-weather-layers.md:23`は「6箇所」と別の数を書き、同22行は「粗い風格子を含む全系統」と書く（実際の呼び出しは8箇所）。さらに経緯コメントでもある / failure_scenario: 共通化の適用範囲を数で把握しようとすると、どの記述を採っても実態と合わない。

- file: frontend/src/hooks/useDynamicWeatherLayers.ts / line: 159-161 / category: 宣言と実装の不一致 / severity: P3 / summary: 降水短時間予報について「取得失敗はnowcastと同じくエラーメッセージへ記録する」と書いているが、162行の分割代入は`data`だけを取り出し`error`/`loading`を捨てている。`dynamicWeatherDataStatus.precipitationNowcast`が集約するのは`nowcastError ?? linearRainbandError`のみで、rasrfの失敗はどの表示にも現れない / failure_scenario: rasrfだけが落ちている状態で「降水」チップは正常表示のまま6時間以降の予報だけが欠ける。ステータスドットは「取得済み」を示し続けるため、利用者にも開発者にも欠落の合図が出ない。

- file: frontend/src/services/regionApi.ts / line: 14, 20 / category: 死んだ識別子 / severity: P3 / summary: `PostRequestOptions.body`と`postAndCheckOk`のコメントが`refreshBasemapCache`を現存する呼び出し元として名指ししているが、grepでこの2行以外に0件。99行の`旧fetchCarStressBreakdown`も同様 / failure_scenario: 「ボディ無しPOSTの呼び出し元」を探して見つからず、分岐を消してよいかの判断に時間を取られる。

- file: docs/modules/frontend/page-composition.md / line: 37 / category: 「全」の主張が偽 / severity: P3 / summary: 「`fetchJson.ts`/`apiError.ts`は全`services/*Api.ts`クライアントが共有するfetch骨格」と書いているが、`services/healthApi.ts`は共有していない。同文書は続けて骨格を「7段」と数え上げてもいる / failure_scenario: 骨格側を改修した担当者が「全クライアントに効く」と判断して個別確認を省き、healthApiだけ旧挙動のまま残る。

- file: docs/modules/frontend/developer-research-tools.md / line: 27 / category: 実在しないパス / severity: P3 / summary: 「`GET /api/health`クライアント」と書いているが、`healthApi.ts:7`も`backend/app/api/routers/health.py:91`も`/health`（`/api`接頭辞なし） / failure_scenario: nginx/rewritesのパス設定やヘルスチェック監視を`/api/health`向けに書き、常に404で「落ちている」と判定される。

- file: frontend/src/lib/routeSplice.ts / line: 140-147 / category: 二重に持つ規約の写し漏れ / severity: P3 / summary: backendの並び順規約を要約しているが、backend（`route_generator.py:584-587`）には`if max_routes >= 2:`という条件が付いており「1本だけ返すときは固定しない」。フロント側（154行）は無条件に`routes[0].is_fastest`で先頭固定とみなす。コメント自身が「片方を変えたらもう片方も変える」と宣言している対の片側が既に欠けている / failure_scenario: `max_routes=1`で生成した目的地ルートに区間乗り換えを行うと、合成候補が生成候補より易しくても先頭に来ず2番目へ入る。影響範囲は狭いが、規約を「同じ」と信じた次の改修で差が拡大する。

- file: frontend/src/lib/routeTabLabel.test.ts / line: 63-66 / category: 宣言と検証対象のずれたテスト / severity: P3 / summary: テスト名が「backendが付ける接頭辞と、フロントが組み立てるidが同じ1つの値から出る」と契約を宣言しているが、実際のアサーションは`expect(SPLICED_ROUTE_ID_PREFIX).toBe("route-spliced")`というフロント定数のリテラル確認のみ。backend側には一切触れない / failure_scenario: backendが`"route-merged"`へ改名しても、このテストも他のどのテストも落ちない。合成ルートが`isSplicedRoute`で判定されなくなり、一覧で「合成」ではなく順位番号が付いて生成候補と区別できなくなる（`routeTabLabel.ts:12-13`が「型でも例外でも現れない」と警告している当の事象）。

- file: frontend/src/lib/apiBaseUrl.ts / line: 3 / category: 死んだ文書参照 / severity: P3 / summary: 「CLAUDE.md「複雑度平衡」原則の「定数の片側import」」と参照しているが、CLAUDE.mdに「複雑度平衡」も「片側import」も存在しない。正本は`docs/design-principles.md:72`と`.claude/commands/review/context.md:70` / failure_scenario: 根拠を確認しようとCLAUDE.mdを全文検索して見つからず、方針の有無自体を疑う。

裏取りした事実:
- `backend/app/services/weather_client.py`と`WIND_GRID_CACHE_TTL_SECONDS`はリポジトリ全体grepで0件。現行は`weather_service.py:58-83`が`msm_client.read_series`を直接呼ぶ（TTLキャッシュ無し）。
- `refreshBasemapCache`・`fetchCarStressBreakdown`はいずれも`regionApi.ts`のコメント内以外に0件。
- 環境変数名は実装・`.env.example`・`docker-compose.yml`・`README.md`すべて`NEXT_PUBLIC_API_URL`。
- backend `route_generator.py:571`が`is_fastest=True`を付け、584-587が`max_routes >= 2`のときだけ先頭固定。`generate_spliced_route`は`is_fastest`を触らないため、合成候補が二重に基準線になることは無い。
- `axis-catalog.json`の`dedicated_way_value_layer=true`は`gradient`・`wind`の2軸。
- `dead_identifier_refs`は`docs/modules`しか走査しないため、ソースコメント内の死んだ識別子3件（`WIND_GRID_CACHE_TTL_SECONDS`・`refreshBasemapCache`・`weather_client.py`）はどの経路でも検知されない。

問題が無いことを確認した観点:
- `lib/fetchJson.ts`の骨格集約は実効的で、`requestOk`/`requestJson`/`fetchJson`の3入口はhealthApi以外の全クライアントが実際に通っている。
- backend定数の手書き複製は、`services/regionApi.ts`・`lib/evaluationAxes.ts`・`lib/hardFilterSync.ts`のいずれも生成物由来で、lib/hooks/services側に`page.tsx:129`の`DISTANCE_TOLERANCE_KM = 5`に相当する手書き複製は無かった（ただし`distance_tolerance_km`の既定値はそもそも`route-generate-config.json`に書き出されていない）。
- 純関数テスト（`routeSplice.test.ts`・`gpxExport.test.ts`・`evaluationAxes.test.ts`・`hardFilterSync.test.ts`）は境界・失敗方向を独立計算で検証しており、「誤った挙動を固定している」テストは見つからなかった。
- `useStoredState`のレンダー中リセット・`usePolledFetch`のenabled遷移時`hasFetched`巻き戻し・`useDedicatedWayValues`の世代番号ガードはいずれも競合と再入を正しく扱っている。
