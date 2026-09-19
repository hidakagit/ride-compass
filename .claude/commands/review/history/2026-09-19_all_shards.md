# 統合レビュー（2026-09-19）シャード別の生出力

対象コミット `0d0c6251`（ベースライン `05c96456` = 2026-09-16統合レビュー）。
[2026-09-19_all.md](2026-09-19_all.md) の一次出力で、**統合前のため重複・severityの揺れ・矛盾を含む**。
読み物として整える目的は持たない——起票したタスクが「対象はこの節」と指せることだけを目的に、
Agentの出力をそのまま連結している。本文の判断・severityの最終確定は統合側（`2026-09-19_all.md`）が正。

シャードは `principles.md` 共通実行手順4d に従い、overall と consistency で共有した
（1シャード1Agentへ両レンズの確認観点を渡し、出力を2節に分けさせる）。
Phase 4（complexity）・Phase 6（UI）は規約どおり単独実施のため本ファイルには含まれない。


---

# シャードA: backend/app/domain

## overall

- file: backend/app/domain/evaluation.py / line: 651 / category: structure / import時に束ねた較正値 / severity: P1
  - summary: `DEFAULT_PENALTY_STRENGTH = tuning_value("evaluation.penalty_strength")` はモジュールimport時に1回だけ評価されるが、DBの上書きを`TUNING_VALUES`へ流し込む`refresh_tuning_values`は`main.py:157-160`のlifespan（＝全import完了後）で走るため、**プロセスを再起動しても上書きが届かない**。`tuning.py:461-466`はこの値の`effect`を`RESTART`（「プロセスを入れ替えないと効く」）と宣言しており、宣言と実態が食い違う。`docs/modules/backend/routing-engine.md:237-238`が「プロセス内に束ねる（import時に評価する）と、実行時に変えた値が効かない」と明記している規則の、その規則を書いた本人による違反。
  - failure_scenario: 管理者が `PUT /api/admin/tuning/evaluation.penalty_strength {"value": 1.5}` を実行すると、`tuning_admin.py:65`の`value=tuning_value(...)`は1.5を返すので画面は「いま効いている値=1.5」と表示する。しかし`RouteGenerateRequest.penalty_strength`の既定（`routes.py:160`）も`dependencies.py:168,206`の工場既定も0.7のまま、フロントが送る`routeGenerateConfig.default_penalty_strength`（`page.tsx:1502`／ビルド時生成物`route-generate-config.json`）も0.7のまま。backendを再起動しても同じ順序を繰り返すだけなので、**どの操作でも1.5は一度も効かない**。

- file: backend/app/domain/tuning.py / line: 472-534 / category: structure / 母集団を手で列挙（設計原則12違反） / severity: P2
  - summary: `FIXED_VALUES`のキー（モジュールパス）がそのまま検知器`undeclared_fixed_values`の走査対象（`scripts/review_checks.py:612-613`）であり、docstringも「キーの並びがそのまま検知器の対象範囲」と明言している。これは`docs/design-principles.md`構造仕様12「チェックの母集団は導出する。手で列挙しない」が名指しで禁じている形。実際に**ルーティング評価が読む数値定数が既に母集団の外にある**: `attributes.py:527 MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT`、`gradient.py:31 LENS_PERPENDICULAR_BAND_DEG`、`hard_filters.py`・`difficulty.py`・`material_catalog.py`・`axis_definitions.py`の定数群。
  - failure_scenario: 誰かが`attributes.py`へ勾配の上限をもう1つ足しても検知器は沈黙する。`TUNING_PARAMETERS`と`FIXED_VALUES`を見て「較正対象は洗い出せている」と判断した開発者が、上限40%という評価に効く定数を較正計画から落とす。

- file: backend/app/domain/traffic.py / line: 135-145 / category: dead / 撤去済み定数の説明ブロックが隣の定義の説明として残存 / severity: P2
  - summary: `STOP_SECONDS`辞書は削除され値は`tuning.py`の`_stop_parameter(...)`へ移ったのに、その辞書に付いていた説明ブロックが空行なしで`def stop_seconds`の直上に取り残されている。同じ根拠文が`tuning.py:384-396`の`description`にもあり二重管理。同型の残骸が`cycling_speed.py:31-37`にもある（較正対象ではない`SPEED_SOLVE_ITERATIONS`が較正値であるかのように読める）。
  - failure_scenario: 管理者が`stop.crossing_seconds`を5秒へ上書きした後、`traffic.py`を読んだ開発者が「信号の無い横断歩道が0なのは自転車は止まらず通過できるため」を現在の仕様と信じ、0秒前提で所要時間の検算をして食い違いの原因を探し回る。

- file: backend/app/domain/traffic.py / line: 279-283 / category: other / コメント方針違反＋検知器のすり抜け / severity: P2
  - summary: `MAJOR_CROSSING_MIN_RANK`の`#:`コメントに経緯が書かれている（「`[T800](../../../docs/tasks/T800.md)`でこの判定を入れてから…」）。`scripts/review_checks.py`の`NARRATIVE_PATTERN`（:84-94）が`T[0-9]{3,4}で`でブロックする建て付けだが、**Markdownリンク形式にすると`T800`と`で`の間に`](…md)`が挟まりパターンが当たらない**ため素通りしている。
  - failure_scenario: 「新規混入分はpre-commit/CIが機械的に検出しブロックする」を信頼している書き手が、同じリンク形式で経緯を書き続ける。T567完了後もこの形だけが検知されないまま増える。

- file: backend/app/domain/evaluation.py / line: 491-500 / category: dead / 到達しないガード / severity: P3
  - summary: 空タイル分岐へ追加した`if material_id in MATERIAL_CATALOG`は1件も除外しえない。`route_facing_material_ids()`（:349-363）が既に同じ条件で絞っており、非空側（:618-627）も`if material_id in material_arrays`（⊇`MATERIAL_CATALOG`）なので変更前から両者は同じ集合だった。
  - failure_scenario: 次に列のずれを疑う人が、このコメントを読んで「非対称は解消済み」と判断し、実際の列ずれ要因の点検を飛ばす。

- file: backend/app/domain/gradient.py / line: 42-59 / category: contract / 対で使う前提が強制されていない / severity: P3
  - summary: `effective_gradient`と`shows_gradient`は「先に`shows_gradient`で落とす」前提の対だが、`effective_gradient`側は何も検査しない。`math.cos(diff) >= 0`の境界では`+gradient_percent`を返す。契約は呼び手の記憶だけで保たれている。
  - failure_scenario: 区間インスペクタ等に「この向きでの勾配」を後から足す人が`effective_gradient`だけを呼ぶと、直角に近い道へ符号が不定のフル値が付く。地図では「データなし」なのに詳細では「+15%（登り）」と出る。

## consistency

- file: docs/modules/backend/dynamic-way-values.md / line: 225-227 / category: doc-drift / 同一文書内の自己矛盾 / severity: P2
  - summary: 「way単位のズームではそのwayの**いちばん急な区間**が代表になる」は、同じ文書の:124-129（「長さで重み付けて平均」）と実装（`road_graph_repository.py:695-698`）の両方と正反対。同じ古い主張が`docs/modules/backend/routing-engine.md:838`にも残る。
  - failure_scenario: 「way単位で激坂が見えない」という報告を調べる人が:225を読み、存在しない前提でSQLを疑う。:124を読んだ人は仕様どおりと判断し、2人の結論が食い違う。

- file: docs/architecture.md / line: 2074-2080 / category: doc-drift / 撤回済みの設計判断が「確定済み」として残存 / severity: P2
  - summary: 「**符号補正（確定済みの設計判断）**: 連続的なcos補正を採用した…二値反転案のような境界での不自然な急変が無い」。現在の`gradient.py:43-46`はまさにその二値反転＋直角帯の除外であり、cos投影は撤回されている。CLAUDE.md「規模M以上でドメイン概念を変える変更はarchitecture.md追従を完了条件に含める」の未実施。
  - failure_scenario: 勾配レンズを触る人がarchitecture.mdの「確定済みの設計判断」を根拠に`shows_gradient`の除外を取り除き、cos投影へ戻す。直角付近の急坂が再び「平坦」の色で塗られる。

- file: docs/modules/backend/dynamic-way-values.md / line: 253, 255-258 / category: doc-drift / 撤去済みの事実を語る周辺表現の残存 / severity: P2
  - summary: 表が`effective_gradient`の符号欄を「0付近=道路をほぼ横切るだけ」とし、地の文が「いずれも走行方位との角度差を**係数として**物理量へ反映」「（**cosの偶関数性**と符号の二重反転が相殺するため）」と述べる。いずれも撤回済みの前提。
  - failure_scenario: 表だけを見た人が「直角付近は0%が返る」と理解し、色が付かないのを「0%なのに描画されないバグ」として起票する。

- file: docs/modules/backend/routing-engine.md / line: 371-372 / category: doc-drift / 追加された条件が記載漏れ / severity: P2
  - summary: ターン費用の条件から`(target_node_rank >= MAJOR_CROSSING_MIN_RANK)`＝tertiary以上という第2条件が抜けている（実装は`routing.py:794-798`）。この第2条件が「自転車道(0)→サービス道路(1)で成立してしまう」誤発火を止めている中核。
  - failure_scenario: 「生活道路を渡るのに8秒付く」を調べる人が設計書どおりの条件で手計算し、実装に無いバグを追う。逆に`MAJOR_CROSSING_MIN_RANK`を撤去しても設計書と照らす限り矛盾が出ない。

- file: docs/modules/backend/routing-engine.md / line: 493 / category: doc-drift / 同一文書内の自己矛盾 / severity: P2
  - summary: 「`find_nearest_node_indexed`は**索引全体を走査する**」。実装は`routing.py:570-604`で`cell_bounds`を超えた時点で打ち切り、再スナップは`max_distance_km`でさらに絞る。同じ文書の:261-275が正反対を書いている。
  - failure_scenario: `no_candidates_side`の判定を見直す人が:493を根拠に「候補0件＝起点側の問題」と切り分け、距離上限で落ちた目的地側の事象を起点側として扱う。

- file: backend/app/domain/route.py / line: 142-146 / category: contract / コメントの主張と消費者の実態が逆 / severity: P2
  - summary: 「**フロントはこの印を見ない**」と断言しているが、`frontend/src/lib/routeSplice.ts:150`が`routes[0].is_fastest`を実際に読んでいる（基準線を並べ替えから除外するため）。「見ない」のは`routeTabLabel.ts`だけ。
  - failure_scenario: 「周回では常にFalseなのだから」と`is_fastest`を外す／付与規則を変える人が`routeSplice.ts`をgrep対象から外す。乗り換えで合成した候補が基準線より前へ差し込まれ、一覧の先頭が入れ替わる。

- file: backend/tests/test_tuning.py / line: 72-106 / category: test / 母集団が手書きで、実際に届かない1件が抜けている / severity: P1
  - summary: `TestReachesTheConsumers`はdocstringで「届かない値が混ざっていると、管理画面から変えても何も起きない」とこの欠陥を目的として宣言しているが、検証する消費者は手書きの6ケースで`TUNING_PARAMETERS`から導出していない。結果、**唯一実際に届かない`evaluation.penalty_strength`だけがテストの外**にある。
  - failure_scenario: 較正値を1つ足した人が`TestReachesTheConsumers`をgreenのまま通し、その値が`RESTART`扱いでimport時に束ねられていることに気づかない。

- file: backend/app/domain/axis_inspector.py / line: 54-55, 83 / category: doc-drift / 同一コミットで直した記述の兄弟が取り残された / severity: P2
  - summary: :141-142のdocstringは直されたが、:54-55「軸の材料に使うのは**このうち2クラスだけ**」と:83「`way_landcover`の**8列すべてではない**」はそのまま。`WIRED_LANDCOVER_KEYS`は現在8クラス全部を含むため、どちらも事実と逆。
  - failure_scenario: レスポンスを縮めようとした人が:54-55を読み「材料に使う2クラス以外は落とせる」と判断して6クラスを削り、実際には配線済みの材料を落とす。

- file: docs/modules/backend/routing-engine.md / line: 223-225 / category: doc-drift / 数え上げ（全件列挙）が既に嘘 / severity: P3
  - summary: 「ほとんどは次のリクエストから効くが、**信号とみなす半径だけは**…」。実際の`TuningEffect`は`IMMEDIATE`のほかに`TURN_STRUCTURE`・`RESTART`・`CLIENT_RELOAD`があり「だけ」は成立しない。
  - failure_scenario: ターンの秒数を変えた管理者が「次のリクエストから効く」と読み、反映確認をしないまま較正を進める。

- file: backend/tests/test_dynamic_way_values.py / line: 90, 97, 179 / category: test / 契約変更に追従していない入力 / severity: P3
  - summary: `transform_dedicated_way_values`の鍵は`dict[int,float]`（way_id）から`dict[str,float]`（feature_key）へ変わったが、テストはint鍵のまま。実行時の型検査が無いため鍵の型を保証するものが型注釈だけになっている。
  - failure_scenario: way_idを鍵にしたままの新しい配信サービスを足してもこのテストは通る。本番では`setFeatureState`のidが一致せず色だけが無言で消える。

- file: backend/tests/test_road_graph_repository.py / line: 853, 2151-2165 / category: test / 本番が生成しえない値を検証している / severity: P3
  - summary: 補給POIのテストが`kind="vending_machine"`を検証するが、`classify_supply_poi`（`traffic.py:243-262`）はこの値を返さなくなった（`vending_drinks`/`vending_unknown`／取り込まない）。
  - failure_scenario: 補給POIのbaseFilterをSQLへ移す変更をしても、存在しないkindで通り続けるため、実際に配信される値が落ちても検知できない。

- file: backend/app/domain/landcover.py / line: 1 / category: doc-drift / severity: P3
  - summary: モジュールdocstringが「土地被覆クラス別割合（`way_landcover`）の算出」と単位をway限定で名乗るが、`EdgeLandcover`も扱うようになった。
  - failure_scenario: 区間単位の土地被覆の型を探す人が「way専用モジュール」と判断し別ファイルを探す。

- file: docs/modules/backend/dynamic-way-values.md / line: 124-129 / category: contract / 実装が保証しない同値性を断言 / severity: P3
  - summary: 「符号付きで平均するため結果はwayの両端の標高差と一致し」と書くが、SQLは区間ごとに`sign(cos(...))`を掛けてから揃えるため、ヘアピン等では成立しない（真の直角では`sign=0`で分母だけ増える）。
  - failure_scenario: 峠の九十九折りで「way単位の勾配が両端の標高差と合わない」報告を受けた人が、平均処理ではなく標高データ側を疑い原因にたどり着けない。

---

# シャードB: backend/app/services

## overall

- file: backend/app/services/derived_data_revision_service.py / line: 74 / category: perf / イベントループを握るディスク削除 / severity: P2
  - summary: `tile_cache.clear_all()`（`shutil.rmtree`）が`asyncio.to_thread`を介さずasync関数から直接呼ばれ、リクエスト処理中にイベントループを止める。同じ系統の`tile_serving.py:71,91`は`tile_cache.get`/`set`を`asyncio.to_thread`で逃がしており、この1箇所だけ方針から外れている。
  - failure_scenario: バッチが`derived_data_meta.revision`を進めた後、最初にページを開いた利用者の`GET /api/axis-catalog`が`ensure_caches_match_db`を通り、`CACHE_DIR`全体を同期`rmtree`する。`docs/caching.md`の実測では土地被覆だけで21,264枚・45MBあり、削除完了まで`/health`を含む全リクエストが停止する。

- file: backend/app/services/derived_data_revision_service.py / line: 66-74 / category: perf / 無効化の過剰 / severity: P2
  - summary: `clear_all()`の発火条件がコメントの主張（「DBの世代が変わった」）より広く、材料キャッシュの**形の署名**が変わっただけのデプロイでも基礎地図・GSI DEM・土地被覆タイルを全消しする。
  - failure_scenario: `graph_material_cache.TILE_MATERIALS_CACHE_VERSION`は`shape_digest(EdgeMaterialTable, LeanNode, LeanEdge)`で、`LeanNode`へ列を足すと値が変わる。`cache_generation.sync_with_revision`は新しいversionの記録が無いので無条件にTrueを返すため、DBの世代が1も動いていないのに`clear_all()`が走る。コメント69-73は巻き添えを「基礎地図・DEM」とだけ数え上げ、最大の居住者である土地被覆（再取得ではなくCPU再描画）が抜けている。

- file: backend/app/services/tile_serving.py / line: 70-71 / category: structure / 世代確認の置き場所 / severity: P3
  - summary: ディスクのタイルを**読む**経路（`serve_cached_tile`）が`ensure_caches_match_db`を一度も呼ばず、鮮度は別のエンドポイント（`/api/axis-catalog`）が叩かれることに依存している。`docs/caching.md`（288-292行）が禁じている形。
  - failure_scenario: backend再起動直後にバッチが世代を進めていると、`/api/axis-catalog`が届く前に来たタイル要求は前プロセスが焼いた旧世代のタイルをディスクから返す。`persist`側だけを世代でガードし`get`側は無条件という非対称。

- file: backend/app/services/region_service.py / line: 138-141 / category: structure / レイヤー境界 / severity: P3
  - summary: `RegionService.repository`プロパティがinfrastructureの`RoadGraphRepository`をそのままルーターへ公開し、`api → services → infrastructure`の一方向依存を迂回している。
  - failure_scenario: `api/routers/axis_catalog.py:229`が`current_tile_versions(region_service.repository)`としてサービスの内部依存を取り出す。`dependencies.py:272`に`get_road_graph_repository`があるためDIの口が2系統になり、セッションのタイムアウト設定（180秒／20秒）の違いも呼び出し側から見えない。

- file: backend/app/services/road_graph_engine.py / line: 699, 726-727 / category: dead / 到達しない引数 / severity: P3
  - summary: `RoadGraphEngine.__init__`の`turn_cost`引数を渡す呼び出し元が本番・テスト・benchmarkのいずれにも無く、コメントが主張する「リクエストで上書き」という経路も存在しない。
  - failure_scenario: 読み手がコメント「較正中はリクエストで上書きして試せる」を見て、存在しないリクエストパラメータを探すか、較正の入口が2つあると誤解する。実際の入口は`current_turn_cost()`の1本だけ。

- file: backend/app/services/landcover_tile_service.py / line: 51-52 / category: other / 抑制の初期値 / severity: P3
  - summary: `_last_unavailable_log = 0.0`という初期値のため、`time.monotonic()`の基準が小さい環境では起動から60秒以内の最初の「配信できない」警告が落ちる。`-inf`にすれば構造的に起きない。（推測: 実環境での再現は未確認）
  - failure_scenario: 土地被覆が配信できない状態はデプロイ直後にこそ起きるため、最も知りたい1件目が消える。

## consistency

- file: backend/app/services/landcover_tile_service.py / line: 38-45 / category: contract / docstringの主張と実装の不一致 / severity: P2
  - summary: docstringは「**開いているラスタの構成**も鍵に入れる」と述べるが、実装は`settings.lulc_raster_paths_list`（＝**設定された**構成）を指紋にしており、「設定はあるが開けない」状態で焼いたタイルが正常時と同じ鍵でディスクへ残る。
  - failure_scenario: `LULC_RASTER_PATHS`に4枚が設定された状態でコンテナだけ先に入れ替わり3枚しか配置されていない間に地図をパンすると、欠けたゾーンの透明タイルが正常時と同じ鍵で書かれる。4枚目が配置され再オープンされても指紋は変わらないため、既にディスクに載った継ぎ目のタイルは永久に透明のまま配られる。

- file: backend/app/services/wind_way_service.py / line: 10-12 / category: doc-drift / モジュールdocstringが存在しないキャッシュを述べる / severity: P2
  - summary: モジュールdocstringが「計算結果のキャッシュも…dictとして`dynamic_way_value_cache.py`へ渡す」と述べるが、実装は値をキャッシュしない（同ファイル120-122行のコメントが正反対を述べ、`dynamic_way_value_cache`のimport自体が無い）。
  - failure_scenario: 3つ目の`dedicated_way_value`軸を追加する開発者がこのdocstringを雛形として読むと、実在しないキャッシュ経路を前提に設計する。

- file: docs/modules/backend/dynamic-way-values.md / line: 197-214 / category: doc-drift / 設計書が撤去済みの制御フローを記述 / severity: P2
  - summary: `WindWayService`の制御フロー図に`hour_bucket`・キャッシュhit/miss・書き込みが残り、「**暗黙の前提**: キャッシュhit時は`next(iter(cached.values()), 0.0)`で代表値を取り出す」という節が存在しないコードの不変条件を警告している。
  - failure_scenario: 次に風の配信を触る開発者が、実在しないキャッシュの整合性を壊さないよう設計を制約されるか、警告を信じて調査を空振りする。

- file: docs/modules/backend/dynamic-way-values.md / line: 225, 237-240 / category: doc-drift / 同一文書内の自己矛盾 / severity: P2
  - summary: `GradientWayService`節が「way単位のズームではそのwayの**いちばん急な区間**が代表になる」と述べ、コード片も`shows_gradient`フィルタを欠いており、どちらも同じ文書の124-138行および現在の実装と矛盾する。
  - failure_scenario: 1つの文書が同じ事実について正反対の2つの答えを持ち、読み手はどちらが現行かを実コードに当たるまで判別できない。

- file: docs/caching.md / line: 316-317 / category: doc-drift / 方針の正本と実装の不一致 / severity: P2
  - summary: キャッシュ方針の正本が「**全消し（`tile_cache.clear_all()`）は例外**…**運用操作としてのみ残す**。新しいキャッシュへ全消し手段を足さない」と定めるのに、`derived_data_revision_service.py:74`が自動経路から呼んでいる。
  - failure_scenario: 次にキャッシュを足す開発者が正本だけを読むと既存実装と食い違う設計を採るか、実装を見て「正本のほうが古い」と判断しルール全体の信頼を落とす。

- file: docs/architecture.md / line: 180 / category: doc-drift / 撤去済みシンボル名の残存 / severity: P3
  - summary: 路面タイルのキャッシュパスを`v{ROAD_SURFACE_TILE_VERSION}`と記すが、この定数は`ROAD_SURFACE_TILE_SHAPE`へ改名済みで存在しない。加えて`precompute_way_attribute_counts.py:18,46`・`precompute_edge_attribute_counts.py:43`・`precompute_way_divided_carriageway.py:12-13`が「タイル世代（region_service.py: ROAD_SURFACE_TILE_VERSION）を対上げして」と案内し続けている。**この4ファイルのdocstringは2026-09-15の統合レビューで既に指摘済みで未修正**。
  - failure_scenario: バッチ再実行後に世代を上げようとした運用者が存在しない定数を探し、実際に必要な操作（手上げ不要）へ辿り着けない。

- file: backend/app/infrastructure/graph_material_cache.py / line: 117-118 / category: contract / docstringが禁じた経路から呼ばれている / severity: P3
  - summary: `clear()`のdocstringが「テスト用（**本番コードパスからは呼ばない**）」と宣言しているが、`sync_disk_cache_with_derived_data_revision`経由で`ensure_caches_match_db`という本番経路から呼ばれる。
  - failure_scenario: 「本番では走らない」を信じてテスト都合の重い処理を`clear()`へ足すと、ルート生成リクエストの最中にその処理が走る。

- file: backend/app/services/region_service.py / line: 116-117 / category: doc-drift / 存在しないUIを案内する / severity: P3
  - summary: クラスdocstringが「『地図データを再読み込み』ボタンで…消去できる」と述べるが、その操作は`/admin`「データ保守」タブの`POST /api/admin/basemap/refresh`（Basic認証必須）。`grep -rn "地図データを再読み込み" frontend/src`は0件。
  - failure_scenario: 一般利用者向けUIにそのボタンがあると読んだ開発者が、路面タイルの古い内容を利用者側で解消できると判断する。

- file: backend/app/services/elevation_attribute_service.py / line: 98-102 / category: doc-drift / docstringが新しい入出力を含まない / severity: P3
  - summary: `_compute_attributes`のdocstringは「1回の`ElevationClient`呼び出しで標高を取得する」だけを述べるが、実装はrepositoryへ`get_edge_ids_on_structure`も問い合わせる。
  - failure_scenario: 「GSIへの問い合わせだけを行う純粋な取得層」と読んだ開発者が`self._repository_lock`の外で並列に呼べると判断し、セッションの同時使用でクラッシュする。

- file: docs/modules/backend/weather-dynamic-layers.md / line: 23-30 / category: doc-drift / 対象ファイル表の構造破綻と所管のずれ / severity: P3
  - summary: 対象ファイル表に`services`行と`domain`行がそれぞれ2つずつ現れ、かつ地理院の標高タイル変換（`terrain_tile_service.py`・`terrain_rgb.py`）が「気象庁MSM・気象庁・環境省由来のデータ」を責務とする文書に置かれている。
  - failure_scenario: 標高タイルに触る開発者はまず`elevation.md`を読み、`terrain_tile_service.py`の存在に気づかない。表が2行に割れているため目視でも読み飛ばす。

- file: docs/modules/backend/dynamic-way-values.md / line: 111 / category: doc-drift / 改名の取り残し / severity: P3
  - summary: APIの戻り値を`{way_id: 地図表示値}`と記すが、鍵は`feature_key`へ変わっている。
  - failure_scenario: フロント側で`setFeatureState`のidにway_idを使えばよいと読むと、区間単位ズームで色が一切付かない（エラーも警告も出ない）。

## 該当なしの確認（積極的に探した結果、問題を見つけなかったもの）
- 関数シグネチャと全呼び出し元の整合: `way_scalar_materials`は呼び出し元2箇所とも追従済み。`get_way_ids_in_tile`→`get_feature_keys_in_tile`等の旧名の残存参照ゼロ。
- 実装↔テスト: 今回の変更で経路を通るテストが1件も無いものは見つからなかった。
- 経緯記述の混入: 追加行のコメントに該当なし。
- 評価軸追加の1本道（構造仕様3・8）: `shows_gradient`はdomain側の純関数で軸固有の定数・分岐をエンジンやフロントへ足していない。

---

# シャードC: backend/app/infrastructure

## overall

- file: backend/app/infrastructure/landcover_raster.py / line: 82-104（`_open_sources`）／併せて services/landcover_tile_service.py:38-45 / category: structure / 部分的に開けた状態が恒久固定される / severity: P1
  - summary: ラスタが1枚でも開ければ`_sources`をそのまま保持し二度と開き直さないのに、ディスクキャッシュの鍵は「設定された全パス」の指紋から作るため、部分的な構成で描いたタイルが「完全な構成」の鍵で永久に居座る。
  - failure_scenario: `LULC_RASTER_PATHS`に4枚を設定した本番で、デプロイのラスタ取得ステップが未完のままコンテナが起動し3枚だけ開けた（モジュール自身のコメント64-67行が明示している想定ケース）。`has_sources()`はTrueを返すので配信は始まり、4枚目のゾーンが透明のPNGが4枚ぶんの指紋のパスへ書かれる。4枚目が現れても`_sources`は真値なので開き直されず、プロセスを再起動しても`serve_cached_tile`が先にディスクヒットするため、そのゾーンの継ぎ目タイルは土地被覆が欠けたまま恒久的に配られる。失敗ログも初回の1回しか出ない。

- file: backend/app/infrastructure/dynamic_way_value_cache.py / line: 10-14（docstring）、65-74（`_key`） / category: contract / 鍵が守ると宣言した不変条件を守れていない / severity: P1
  - summary: 鍵へ入れているのは`ROAD_SURFACE_TILE_SHAPE`（焼き込みSQLの形の署名）だけで、`feature_key`の実体（edge_id）を変えるのは形ではなくDB側の世代（`derived_data_meta.revision`／遅延re-split）であるため、docstringが「世代をまたいだエントリが生き残って色が静かに消えるのを防ぐ」と宣言している事態をこの鍵は防げない。`ensure_caches_match_db`が世代変化時に捨てるのは`tile_cache`・`graph_material_cache`・`tile_score_matrix_cache`の3つだけで、`dynway`名前空間は対象外。
  - failure_scenario: PBF再取込→`refresh_derived`完了で`derived_data_meta.revision`が進むと、焼き直された路面タイルの`feature_key`（edge_id）は変わる。しかし`tile_persistent_cache`のエントリは形の署名が同じままヒットし、旧edge_idをキーにしたdictが返る。フロントは存在しないidへ`setFeatureState`するため、そのタイルの勾配レンズが全道無色になる。TTLは24時間なので最大24時間続き、バケット（向き5度・速度1km/h）ごとに新旧が混ざるため「コンパスを少し回すと色が出たり消えたりする」という切り分けの難しい形で出る。

- file: backend/app/infrastructure/tile_cache.py / line: 81-82（`clear_all`）／呼び出し元 services/derived_data_revision_service.py:74 / category: structure / 全消しの自動呼び出しと同期rmtree / severity: P2
  - summary: T848で`tile_cache.clear_all()`（`shutil.rmtree`）がリクエスト処理中の`async def ensure_caches_match_db`から**同期のまま**呼ばれるようになった。同じファイルの他のI/Oは全て`asyncio.to_thread`へ逃がしてある。
  - failure_scenario: 夜間のprecomputeバッチ完了直後、最初に届いた`GET /api/axis-catalog`が`tile_cache`全体を`rmtree`する。その間イベントループが止まる。管理APIの`POST /api/basemap/refresh`は同期`def`ルーターなのでFastAPIがスレッドプールへ逃がしており、**運用操作の側だけが安全で、自動化された側が危ない**という逆転になっている。

- file: backend/app/infrastructure/tuning_overrides.py / line: 38-42（`TuningOverrideRow`）／backend/migrations/0043_add_tuning_overrides.sql:6-10 / category: contract / モデルとmigrationのスキーマ不一致 / severity: P2
  - summary: migration 0043は`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`を持つがORMモデルは`param_id`・`value`の2列しか宣言していない。fresh bootstrapは`create_tables()`→`apply_pending_migrations()`の順で走るため、ORM側が先に`CREATE TABLE`を済ませ、migrationの`CREATE TABLE IF NOT EXISTS`はno-opになる。
  - failure_scenario: CI・新規dev機・disaster recoveryで作ったDBの`tuning_overrides`には`updated_at`列が存在せず、本番（migrationで作られたDB）には存在する、という環境差が静かに生まれる。次に`SELECT updated_at`を足した時点で、本番では通りCI/新規環境では`UndefinedColumn`で落ちる。加えて`set_override`の`on_conflict_do_update(set_={"value": value})`は`updated_at`を更新しないため、本番側の列も「一度も更新されないupdated_at」という嘘の値を持ち続ける。

- file: backend/app/infrastructure/tile_cache.py / line: 85-95（`prune_to_size_limit`のdocstring） / category: doc-drift / LRUと書いてあるが実際はFIFO / severity: P2
  - summary: docstringは「現に読まれているタイルは書き直されて新しくなるため、消えるのは『もう誰も要求していないもの』から順になる」と述べるが、`get()`（31-46行）はファイルを読むだけでmtimeを更新せず、ヒット時は`set()`を呼ばない。実際の順序は「最初に書かれた順」。
  - failure_scenario: 上限到達時、毎日読まれている自宅周辺のタイル（数か月前に初回生成）と、一度だけパンして見た遠方のタイル（昨日生成）が並ぶと、消えるのは毎日読まれている方になる。運用者はdocstringを読んで「ホットなものは残る」と信じるため、ヒット率低下の原因をここだと疑えない。

- file: backend/app/infrastructure/road_graph_repository.py / line: 2946-2950 / category: duplication / 同じ欠損判定が導出版と決め打ち版の2通りある / severity: P2
  - summary: 「土地被覆の行があるか」の判定が`row.trees_percent is not None`という単一クラスの決め打ちで書かれている。同じファイルの`_landcover_percents_or_none`（1029-1033行）は同じ判定を`WIRED_LANDCOVER_KEYS`から導出しており、SELECT列（2903行）も導出されている。設計原則 構造仕様12に対する局所的な逸脱。
  - failure_scenario: 評価から樹木を外すため`WIRED_LANDCOVER_KEYS`から1行削ると、SELECTに`trees_percent`列が出なくなるため`row.trees_percent`が`AttributeError`になり、**すべてのルート生成が500になる**（`get_edge_materials_batch`は探索フェーズの必須経路）。

- file: backend/app/infrastructure/material_coverage.py / line: 79-82、264-273 / category: contract / JOINの1対1前提が宣言にも検査にも無い / severity: P3
  - summary: `join`句は母集団クエリのFROM側へ直接入るため、相手表が`osm_way_id`について一意でなければ全材料の欠損件数と`total`が同時に水増しされる。現状`way_landcover`は主キーが`osm_way_id`なので無害だが、その前提はコメントにもテストにも無い。
  - failure_scenario: 将来`edge_landcover`（主キー`(osm_way_id, node_lo, node_hi)`）に対する欠損率を同じ仕組みで足すと、1つのwayが持つ区間の数だけ行が増え、割合としては正しく見える材料と区間数に依存してずれる材料が混在する。

- file: backend/app/infrastructure/tuning_overrides.py / line: 79-82 / category: structure / infrastructureがトランザクション境界を操作する / severity: P3
  - summary: 設計原則 構造仕様7「トランザクション境界はサービス層。Repositoryはcommitしない」に対し、ここは`await session.rollback()`をinfrastructure側で行う。
  - failure_scenario: 同一セッションで先行していた未確定の書き込みも巻き添えで消える。この復帰処理が「書き込み側は倒れない」という前提に依存している。

## consistency

- file: backend/app/services/region_service.py / line: 287（`get_axis_inspector` → `get_way_landcover`）／規則の正本は road_graph_repository.py:326-334 / category: contract / 単位の選び方が消費者3つのうち1つだけ揃っていない / severity: P1
  - summary: 「区間の行があればそちら、無ければway単位へ落とす」という規則は路面タイルと評価経路には適用されたが、区間インスペクタだけが`get_way_landcover(osm_way_id)`（way単位固定）のまま残っている。`_landcover_value_column`のdocstringが「揃えないと、地図に出ている値と採点が使う値が食い違う」と明記した、まさにその食い違い。
  - failure_scenario: z14以上で`edge_landcover`の行がある道をクリックすると、地図は区間の値（例: trees 80%）で塗られているのに、インスペクタは`way_landcover`の値（例: trees 10%）で内訳を計算して出す。どちらが本当かを画面からは判断できない。インスペクタが受け取るのは`osm_way_id`のみ（MVTは`feature_key`=edge_idも焼いている）なので、クリックされた区間を特定する手段自体が現状の契約に無い。

- file: docs/modules/backend/evaluation-scoring.md / line: 324-331、352 / category: doc-drift / 土地被覆の読み出し元がway単位のまま / severity: P2
  - summary: 「土地被覆の割合材料はWay単位の派生テーブル`way_landcover`…Way単位の値を`road_edges.osm_way_id`経由でEdgeへ展開し」と書かれているが、`get_edge_materials_batch`は`edge_landcover`を優先して読む。本レビュー期間中に`static-road-attributes.md`は113行更新されたのに、このファイルは1行も更新されていない。
  - failure_scenario: 次に開放度軸を触る担当者がこのファイルを正として読み、「way単位の値がEdgeへ複製される」前提で軸を較正する。分布プレビュー（way単位標本）で決めた折れ点が実際のルート評価と合わず、原因をdocsから辿れない。

- file: backend/app/infrastructure/road_graph_repository.py / line: 876-882 / category: doc-drift / 編集で壊れたコメントブロック / severity: P2
  - summary: `ROAD_SURFACE_TILE_SHAPE`の直前に、(a)下の`_POI_COUNTS_BY_KIND_SQL`に属する2行、(b)削除された旧実装の説明が途中で切れた「タイルURL・キャッシュパスへ入る世代。…（手で上げるのはSQLが読むテーブルの中身を作り」、(c)新しい説明の3つが混ざっている。
  - failure_scenario: 「手で上げるのは…」を読んだ担当者が`cache_identity.py`に路面タイル用の手書きリビジョンを探すが、同じコミットで撤去済みで存在しない。`services/tile_version_service.py`へ辿り着くまで誤誘導し続ける。

- file: docs/caching.md / line: 316-317 / category: doc-drift / 「全消しは運用操作としてのみ」が実装と矛盾 / severity: P2
  - summary: （シャードBと重複。統合時に1件へ寄せる）

- file: backend/tests/test_road_graph_repository.py / line: 2984-3070（T919のテスト群） / category: test / 明文化された規則の1本だけ検証が無い / severity: P2
  - summary: 「区間の行があって値がNULL（その構成では値なし）のときもway側へは戻さない」は`_landcover_value_column`のdocstringとdocsが明示する規則だが、この分岐を通すテストが無い。既存3本は「区間の行あり（値あり）」「区間の行なし」「引いた表示」のみ。
  - failure_scenario: `case`を「NULLなら落とす」つもりで書き換えても既存テストは全て緑のまま通る。実際には隣り合う区間が別の単位の値で塗られ、地図の見え方だけが静かに変わる。

- file: backend/app/infrastructure/road_graph_repository.py / line: 2472-2474 / category: contract / 無条件の添字アクセス / severity: P3
  - summary: `float(value[0])`がjsonb配列の第0要素を無条件に読むが、SQL側の`round(sum(...)/nullif(sum(re.distance_m), 0), 2)`は分母が0のときNULLを返しうる。WHEREで除外されているのは`average_grade`・`bearing_deg`・`azimuth`のNULLだけ。
  - failure_scenario: `distance_m = 0`の縮退区間だけが1つのフィーチャーを構成した場合、`float(None)`が`TypeError`で落ちる。勾配レンズのタイル1枚が500を返し、その座標でだけ再現する。

- file: backend/app/infrastructure/cache_generation.py / line: 28-45／graph_material_cache.py:120-123 / category: doc-drift / 「本番コードパスからは呼ばない」が成り立っていない / severity: P3
  - summary: （シャードBと重複。統合時に1件へ寄せる）

- file: backend/app/infrastructure/landcover_raster.py / line: 83-88 / category: doc-drift / 「記憶しない」と実装のずれ / severity: P3
  - summary: docstringは「**1枚も開けなかった場合は記憶しない**」と書くが、実装は`_sources = opened`で空リストを代入して記憶し、`_RETRY_OPEN_AFTER_SECONDS`の間は再試行を抑制する。
  - failure_scenario: 「記憶しないなら毎回開き直すはず」と読んだ担当者が、ラスタ配置直後の透明タイルを「配置ミス」と誤診する（実際は最大60秒待てば解消）。

- file: backend/app/infrastructure/gsi_tile_client.py / line: 49／api/routers/gsi_tile.py:17,22／api/cache_policy.py:98 / category: doc-drift / 改名がクラス名だけに留まり外部に見える名前が古い / severity: P3
  - summary: モジュールとクラスは`GsiTileClient`へ改名され両製品を扱うと明記しているが、ルートパス`/api/gsi-relief-tile/`・レート制限キー・`/api/debug/stats`の外部呼び出しキーは`gsi-relief-tile`のまま。
  - failure_scenario: `/api/debug/stats`で`gsi-relief-tile`のヒット率・エラー率を見た運用者が、それを色別標高図だけの数字だと読む。実際にはDEMタイルの呼び出しも同じバケットへ合算されており、どちらの製品が遅い/失敗しているかを切り分けられない。

- file: backend/app/infrastructure/road_graph_repository.py / line: 3009-3012 / category: dead / 中身が空のdocstring / severity: P3
  - summary: 経緯記述の削除で本文が1文だけになり、末尾に空行だけが残った`"""..."""`になっている。事前実行の前提を持つのか読み取れない。
  - failure_scenario: 他所から呼ぼうとした担当者が`source_osm_import_run_id`/`algorithm_version`を省略してよいか判断できず、NULL入りの行を作る。

- file: backend/app/infrastructure/dynamic_way_value_cache.py / line: 10 / category: other / docstringのタイプミス / severity: P3
  - summary: 閉じ括弧・バッククォートが重複している。同じ編集で入ったP1（鍵に世代が入っていない）の見落としと同じ箇所にある。

---

# シャードD: backend/app/api + batch + 起動系

## overall

- file: backend/app/api/routers/tuning_admin.py / line: 95, 97（あわせて19、および api/dependencies.py:400-404） / category: structure / 層構造の逸脱（トランザクション境界がAPI層にある） / severity: P2
  - summary: 較正値の管理APIだけがサービス層を経由せず`app.infrastructure.tuning_overrides`を直接呼び、DIも`get_tuning_session`で生の`AsyncSession`を渡してルーター自身が`commit()`/`rollback()`している。`docs/design-principles.md`構造仕様7に反する。
  - failure_scenario: リポジトリ全体で`session.commit()`を持つルーターはこの1本のみ。兄弟の軸定義CRUDは`AxisRegistryAdminService`を経由する。今後「上書きを書いたら監査ログも残す」等の要求が来たとき、置き場所がルーターの中しか無い。またテストから業務ロジックを呼ぶにはHTTP経由しか無い。

- file: backend/app/api/routers/axis_catalog.py / line: 229（経路: tile_version_service.py:43 → derived_data_revision_service.py:66-74 → tile_cache.py:82） / category: perf / 公開GETからイベントループを塞ぐ全消去が走る / severity: P2
  - summary: 認可不要・ページ読み込みのたびに呼ばれる`GET /api/axis-catalog`が`ensure_caches_match_db`を呼ぶようになり、世代が変わっていると`tile_cache.clear_all()`（同期`shutil.rmtree`）と`graph_material_cache.clear()`をイベントループ上で実行する。
  - failure_scenario: 本変更前の呼び出し元は`graph_service.py:355`（ルート生成、`generate_max_concurrent=2`で絞られた重い経路）だけだった。バッチが世代を進めた直後、最初に`/api/axis-catalog`を取った一般利用者のリクエストが`backend/data/tile_cache`配下の全ファイル削除を同期で実行し、uvicornは単一ワーカーなので路面タイル・`/health`を含む全リクエストが待たされる。

- file: backend/app/batch/import_pbf.py / line: 417-421（定義は225・475-479、影響先は infrastructure/derived_data_freshness.py:207） / category: contract / 新フラグが鮮度台帳の高水位マークを進めてしまう / severity: P2
  - summary: `--pois-only`はway/nodeを1行も書かないのに、`osm_import_runs`へ`status='succeeded'`（`way_count=0, node_count=0`）の新しい行を残す。鮮度台帳は`MAX(id) WHERE status='succeeded'`を全派生テーブルの基準にしているため、POIだけ取り直すと**way由来の派生データが一斉に「古い」と判定される**。
  - failure_scenario: `GENERATION_FRESHNESS_SPECS`の6件（`edge_attribute_counts`・`way_attribute_counts`・`designation_attributes`・`way_landcover`・`edge_landcover`・`way_divided_carriageway`）はすべて`source_osm_import_run_id`を持つ。`docs/tasks/T935.md:111`によれば`--pois-only`は2026-09-18に本番へ適用済み（418,941件）。したがって`GET /api/admin/derived-data/freshness`は現在、実際には最新のwayデータで計算済みの6テーブルすべてを「取込世代が古い」と表示しているはずで、消すには数時間の`refresh_derived`全段再実行かPBF再取込しか手段が無い。誤警報が常態化すると本物の陳腐化を見落とす。

- file: backend/app/batch/precompute_edge_landcover.py / line: 65-82（スキーマは migrations/0044_add_edge_landcover.sql:15-16） / category: structure / 派生テーブルに孤児行の回収経路が無い / severity: P2
  - summary: `edge_landcover`の主キーは`(osm_way_id, node_lo, node_hi)`で、`road_edges`への外部キーを持たない（FKは`osm_raw_ways`へのみ）。`presplit_road_graph.py`が区間の切り方を変えても古い行が消えず、リポジトリ内に`edge_landcover`をDELETE/TRUNCATEする経路は1つも無い。
  - failure_scenario: 兄弟の`edge_attribute_counts`は`edge_id text PRIMARY KEY REFERENCES road_edges(edge_id) ON DELETE CASCADE`で再splitのたびに自動回収される。`edge_landcover`だけがこの保護を持たない。(1)新しいPBF取込で交差点が増えA—CがA—B・B—Cへ割れると古い(A,C)行が永久に残る（本番は2,610,177行・691MB）。(2)その後Bが交差点でなくなり再びA—Cへ戻ると、**古いラスタ・古いアルゴリズム版で計算された(A,C)の値が生きた値として復活し**、増分実行は「値を持つ行がある」ので再計算対象から外すため、`--recompute`を明示しない限り永久に直らない。

- file: backend/app/api/cache_policy.py / line: 58（対応する追加は109） / category: doc-drift / 数え上げた注釈が追加で嘘になった / severity: P3
  - summary: `BATCH_TILE`の注釈は「取込バッチが走るまで変化しないタイル（路面・事故・POI）」と全件を列挙しているが、本変更で土地被覆タイルがこのポリシーへ移った。
  - failure_scenario: 読み手が「土地被覆は`BATCH_TILE`の3種に入っていない＝別ポリシーのはず」と判断し、109行の実体と食い違う。土地被覆はバッチではなく環境変数でラスタ構成が決まるため、この語の定義自体も現状と合っていない。

- file: backend/app/config.py / line: 118 / category: doc-drift / 設定の説明が対象エンドポイントの片方しか指していない / severity: P3
  - summary: `gsi_tile_rate_limit_per_minute`の注釈は「色別標高図タイルのプロキシ」だけを挙げるが、この値は`/api/gsi-terrain-tile/{z}/{x}/{y}.png`のバケットにも使われるようになった。
  - failure_scenario: 陰影が429で欠けたとき、運用者が「色別標高図を出していないのに何故」と誤診する。実際はprefixが別バケットのため1画面あたりの実効上限は300×2になっており、注釈からはそれも読めない。

- file: backend/app/batch/refresh_derived.py / line: 10-11（重複先は docs/modules/backend/static-road-attributes.md:265-271） / category: duplication / 撤去した理由がそのまま当てはまる写しが別ファイルに残る / severity: P3
  - summary: docstringから段の一覧・順序を削り「正本は下の`_STAGES`。ここへ順序を書き写すと…（実際に⑭が抜けたまま残っていた）」と明記したが、`static-road-attributes.md`には同じ10段を依存順に並べた一覧が残っている。
  - failure_scenario: `tests/test_refresh_derived.py`は`_STAGES`との突き合わせだけでMarkdownは検査しない。11本目の段を足したとき、このMarkdownだけが古くなり同じ事故が場所を変えて再発する。

## consistency

- file: backend/app/api/routers/gsi_tile.py / line: 51（比較対象は routers/jma_tile.py:153, 178） / category: contract / 恒久404の扱いが兄弟エンドポイントの一方にしか無い / severity: P2
  - summary: 「配信元に恒久的に存在しない404」という同じ性質に対し、JMAタイルは`JMA_TILE_NOT_FOUND`（`max-age=600`）を明示するのに、新設の標高タイルと既存の色別標高図プロキシは`Cache-Control`を一切付けない（`CachePolicyMiddleware`は2xxにしか付けない）。
  - failure_scenario: `gsi_tile.py:42-46`のdocstring自身が「整備区域外の404は正常系」と述べ、`gsi_tile_client.py:11-17`も「恒久的に正しい事実」としてプロセス内キャッシュを持つ。つまり認識はサーバ側にあるのにブラウザへは伝えていない。MapLibreの`raster-dem`は海上・整備区域外のタイルもパン/ズームのたびに再要求するため、同じURLの404が繰り返しbackendまで到達し`gsi-terrain-tile`のper-IPレート制限枠（300/min）を消費し続ける。沿岸部を連続してパンする利用者は404だけで429に達しうる。

- file: backend/app/infrastructure/gsi_tile_client.py / line: 49（テストの固定は tests/test_gsi_tile_client.py:103） / category: doc-drift / 外部呼び出しの集計カテゴリ名が実態と合わない / severity: P3
  - summary: （シャードCと重複。統合時に1件へ寄せる）

- file: backend/app/main.py / line: 129-131（対応テストの欠落箇所は tests/test_main_lifespan.py:52-84） / category: test / 変更した経路を通るテストが無く、かつテスト実行が実ディスクを消す / severity: P3
  - summary: `_prune_stale_disk_generations_job`へ`tile_cache.prune_to_size_limit`を足したが、この結線を通るテストは無い。加えて`_isolated_scheduler`は`_refresh_amedas_job`・`_prewarm_jma_tile_job`だけを無害化しており、`_prune_stale_disk_generations_job`・`_sync_msm_job`は差し替えていない。
  - failure_scenario: `_prune_stale_disk_generations_job`は`trigger="date", run_date=datetime.now()`で登録され、同フィクスチャのdocstringが「TestClientのcontext manager内で実際にジョブが発火しうる（実測で確認済み）」と述べている条件を満たす。`pytest backend/tests/test_main_lifespan.py`を実行すると、開発機の実体である`backend/data/tile_cache`に対して`prune_to_size_limit(512MB)`が走り、上限超過時は実ファイルを削除する。

- file: backend/app/api/cache_policy.py / line: 109 / category: test / 挙動変更に対する検査が存在しない / severity: P3
  - summary: 土地被覆タイルのポリシーを`PERMANENT`から`BATCH_TILE`へ変えたが、`tests/test_cache_policy.py`は「全ルートに表のエントリがあるか」「死んだエントリが無いか」しか見ておらず、個々のパスに割り当てられた**ポリシーの値**は2件しか検証していない。
  - failure_scenario: 将来このエントリを誤って`PERMANENT`へ戻してもどのテストも落ちない。109行の注釈が挙げる理由（ラスタ構成が環境変数で決まりURLに現れない）は実装からは導けない制約で、`immutable`が付くとブラウザは条件付きリクエストすら省くため、`LULC_RASTER_PATHS`を差し替えた後も最大24時間古い土地被覆が出続ける（本人のリロードでは直らない）。

## 補足（指摘外の確認事項）
- `main.py`のlifespan起動時ジョブは4本のままで増えていない。過去2回の「起動直後2〜3分だけ外部データ系が失敗」の再発条件は増えていない。
- `config.py`の全38設定を走査し、実装から参照されていないものは無かった。
- OpenAPI生成物は追従済み（`/api/admin/tuning`・`/api/gsi-terrain-tile/...`が`openapi.json`に存在、`AxisCatalogResponse`に`client_tuning`/`tile_versions`あり）。
- `docs/modules/backend/*.md`の対象ファイル表には新規5ファイルがすべて記載済みで、削除した`gsi_relief_tile.py`・`GsiReliefTileClient`への死んだ参照も残っていない。
- `precompute_edge_landcover.py`のスケール成立性は本番実測済み（2,610,177区間・6,106秒・値なし0件）。逐次INSERT・全量ロード・delete-then-reinsertはいずれも無い。

---

# シャードE: 検知器基盤・migration・ベンチ・CI

## overall

- file: scripts/review_checks.py / line: 1116（`DOC_IDENT_RE`）／参照点 1592 / category: contract / severity: P1
  - summary: 識別子が「より長いバッククォート語の内側」にあると抽出されず、前回P0と同型の**記法による母集団の絞り込み**が、いまenforced対象の文書に残る真の違反を隠している。
  - failure_scenario: 本体で実測。`docs/architecture.md:180`は `` `region/road-surface/v{ROAD_SURFACE_TILE_VERSION}/{z}/{x}/{y}.pbf` `` と書いている。この行は免除段落**ではない**。`identifier_exists("ROAD_SURFACE_TILE_VERSION", corpus)`は**False**（T848で撤去済み、現在は`ROAD_SURFACE_TILE_SHAPE`）。にもかかわらず`find_undeclared_dead_refs`をこの行に掛けると`[]`を返す——`DOC_IDENT_RE`がバッククォート内**全体**が識別子であることを要求するため。結果、architecture.mdは「タイル世代は手で書く定数」と読める記述を保ち続ける一方、`cache_identity.py:26-31`は正反対を宣言している。この記法は`guard_probe_edges`の外縁ケースにも無く、mutateでは一切試されていない。

- file: docs/batch-pipeline-dependencies.md / line: 83・120・134 / category: doc-drift / severity: P1
  - summary: precomputeバッチの運用手順が、存在しない定数`cache_identity.py: ROAD_SURFACE_REVISION`を上げるよう指示しており、現在の設計とは逆のことを言っている。
  - failure_scenario: 本体で確認。`git grep ROAD_SURFACE_REVISION -- backend frontend`は**0件**。`cache_identity.py`が持つのは`LANDCOVER_REVISION`・`SCORE_MATRIX_REVISION`・`UNKNOWN_REVISION`だけで、同ファイルは「路面・停止要因POI・事故の世代は手で書く定数を持たない」と明記している。運用者がこの表に従って`ROAD_SURFACE_REVISION`を探し、見つからないまま「世代上げは不要」と判断して終える→中身が変わったのに鍵が動かず、古い値のタイルを配り続ける。この文書は`docs/modules/`・`architecture.md`・`.claude/commands/`のどれにも属さないため、死んだ参照の検知器の母集団に一切入っていない。

- file: scripts/review_checks.py / line: 1120（`SOURCE_CORPUS_PREFIXES`）／2075（`AXIS_MENTION_TARGET_DOCS`）／2705（`md_files`） / category: structure / severity: P2
  - summary: 死んだ参照・撤去済み軸の検査対象となる文書が「docs/modules・architecture.md・.claude/commands」の手書き3系統で、CLAUDE.mdが「必読・唯一の正本」と指定する`docs/*.md`群が全て母集団の外にある。
  - failure_scenario: 本体で実測。architecture.md以外の`docs/`直下の.md（33ファイル）へ同じ`find_dead_identifier_refs`を掛けると**145件**。記録文書を除いても運用に効くものが残る: `docs/caching.md:270`が無効化の既定例として `` `ROAD_SURFACE_TILE_VERSION` ``（撤去済み）を挙げ、`docs/documentation.md:68`が「よい書き方」の見本として同じ死んだ名前を挙げている。`review_checks.py docs`は全件実行でも0件を返し続ける。

- file: scripts/pre-commit-docs-consistency.sh / line: 29 / category: contract / severity: P2
  - summary: pre-commitフックはステージ済みパスが6パターンに一致しないとdocs検査を**丸ごとスキップ**するが、`mutate`はこのラッパを通さず`review_checks.py docs --staged`を直接叩くため、表の「pre-commit / PASS」がフックの実際の挙動を保証していない。
  - failure_scenario: ゲートの正規表現は`^docs/modules/|^docs/improvement-plan\.md$|^docs/tasks/|^backend/app/|^frontend/src/|^\.claude/commands/review/`。`backend/tests/`だけを触るコミットは一致せず`exit 0`で素通りするが、`cmd_mutate`は`--staged`を直接呼ぶので`vacuous_test_loops`を「pre-commit PASS」と報告する。同様に`docs/architecture.md`単独（`undeclared_dead_refs`）、`scripts/`・`backend/scripts/`単独（`call_arity`・`module_redefinition`）、`CLAUDE.md`・`docs/*.md`単独（`dead_doc_links`・`doc_constant_drift`）、`.claude/commands/task/`単独（`review_doc_dead_refs`）が同じ形。走査範囲ではなく**検査の起動有無**の差で、mutateの表は誤った安心を与える。

- file: scripts/review_checks.py / line: 1162（`ARCHITECTURE_REMOVED_MARKER_RE`）・1189 / category: structure / severity: P2
  - summary: architecture.mdの段落単位免除が、非空行の**42.8%**をenforced検査の外へ出しており、その割合が一度も実測・記録されていない（T798「緩和は影響を測ってから入れる」）。
  - failure_scenario: 本体で実測。段落398のうち87（21.9%）が免除、行では非空行2,010のうち**860行（42.8%）**。語ごとの内訳は`撤去`47・`旧`52・`廃止`18・`削除済`9段落で、**`旧`1文字だけで免除されている段落が24**（「復旧」「新旧」「旧コンテナ」等の無関係な用法を含む）。`T743.md:53`が記録しているのは免除単位を狭めた効果（参考出力0→2件）だけで、免除が外している母集団の割合は書かれていない。

- file: scripts/review_checks.py / line: 2900（`cmd_metrics`） / category: doc-drift / severity: P2
  - summary: 「計測している側のファイルだけが計測されない」欠陥は`cmd_size`（2775-2781）でのみ直され、`cmd_metrics`は`is_impl_file`のまま`scripts/`を除外している。
  - failure_scenario: 本体で両方実行。`size`は`scripts/review_checks.py 3,952行`を表の**1位**として出すが、同じコミットで`metrics`が出す「実装本体62,219行／テスト64,921行」には`scripts/*.py` 5,832行も`scripts/tests/test_review_checks.py` 1,642行も入っていない。メトリクス履歴の傾向を見る読み手は、リポジトリ最大の単一ファイル（+1,126行／本サイクル）が数字に一切現れていないことに気づけない。

- file: scripts/review_checks.py / line: 548（`FIXED_VALUE_DECLARATION`）・603 / category: structure / severity: P2
  - summary: 「マジックナンバーが静かに戻るのを止める」と宣言する検知器の母集団が、`tuning.py: FIXED_VALUES`のキーとして手で挙げた11モジュールに限られ、その外の規模が測られていない。
  - failure_scenario: 本体で実測。`backend/app/`配下でモジュール直下に数値定数を持つがこの11に入らないファイルは**60ファイル／141定数**（`road_graph_repository.py`の`DIVIDED_CARRIAGEWAY_BEARING_TOLERANCE_DEG`等12、`landcover.py` 12、`weather.py` 7、`db_status_service.py` 5など）。評価に効く新しい閾値を`domain/hard_filters.py`等へ直書きしても検知器は0件のままで、管理画面から動かせない較正値が静かに増える。

- file: .github/workflows/deploy-backend.yml / line: 21-25 / category: contract / severity: P2
  - summary: benchmarksを自動デプロイの対象から外す根拠として「忘れて古いコードを測ることは`benchmarks/_revision.py`が実行時に止める」と書いているが、そのガードを呼ぶのは`run_all.py`だけで、今回追加した2本を含む個別実行のベンチには効かない。
  - failure_scenario: `require_current_revision()`の呼び出し元は`run_all.py:30`のみで、同29行が「個別の`bench_*`モジュールは呼ばない」と明記。`run_all.py`が回すのは4本でbenchファイルは28本ある。今回追加した`bench_t917_edge_tile.py`・`bench_t919_edge_landcover.py`はREADMEが「個別に実行すること」と明示。`backend/benchmarks/**`をpushしてもデプロイが起きない状態でVM上の古いコードを測っても何も止まらず、もっともらしい数字がタスクエントリへ「実測」として記録される。

- file: scripts/review_checks.py / line: 153（`python_comment_lines`）と 1286（`_python_comment_lines`） / category: duplication / severity: P3
  - summary: Pythonのコメント・docstring行番号を求める関数が同一ファイル内に2つあり、docstringの拾い方だけが違う。現時点で差分行に`NARRATIVE_PATTERN`該当は0件（現行の実害なし）。ただし定義が2つあるため、片方だけを直した改修で検知範囲が黙ってずれる。

- file: backend/migrations/0013_add_edge_bearing.sql / line: 15-20・25-27 / category: contract / severity: P3
  - summary: 適用済みmigrationのコメントだけを改訂して「このバックフィルの値は`bearing_between`と一致しない（緯度35度で最大約6度）」と明記したが、SQL自体は平面近似のまま残り、どの行が旧値のままかを追う手段が無い。
  - failure_scenario: 影響を受けるのは0013適用時点で既に存在した本番の行で、再splitされるまで最大約6度ずれた`bearing_deg`を持つ。この値は風の向かい風判定へ直接入るため、該当区間だけ風コストが僅かに誤る。どの範囲が未再構築かを判定する導線も、再構築完了を確認する検査も無い。

- file: backend/benchmarks/bench_t917_edge_tile.py / line: 24（同型: bench_t919_edge_landcover.py:41、写経元 bench_postgis_prepare.py:23） / category: doc-drift / severity: P3
  - summary: 本サイクル新設の2ファイルが「.envのDATABASE_URLはSupabase向けのため」という文をそのままコピーしているが、Supabaseは2026-08-15にOracle Cloudへ移行して廃止済み。
  - failure_scenario: 実行手順を読んだ人が「.envは遠隔のSupabaseを指している」と信じて`DATABASE_URL`を上書きしないまま実行し、意図せず別のDBを測る／接続エラーの原因を誤診する。`backend/benchmarks/`は`source_narrative`にも`source_comment_dead_identifier_refs`にも母集団として入らないため、同じ一文が3ファイルへ増えたことは機械的には一切検知されない。

- file: scripts/review_checks.py / line: 1-3952（規模ウォッチ発火の分類材料） / category: structure / severity: P3
  - summary: 3,952行に「検知器群」と「計測群」という別の変更理由が同居している。現時点では**理由つきKEEP**が妥当だが、分割トリガーを行数ではなく構造で持つべき材料。
  - 内訳（本体で実測）: 共通+docs検知器 1〜2767行（約2,770行・70%）、mutate/外縁 3185〜3914行（約730行・18%）、計測群（size/metrics/trigger/duplication）合計 約340行・9%。検知器群は同じ理由で一緒に動くため分けると`DETECTOR_ENFORCEMENT`と`guard_probe_*`が離れてしまい、前回P0の「表と配線のずれ」を作りやすくなる。一方で計測群（340行）は検知器を1本も参照せず、ここだけが独立して切れる。前回の「4,000行到達」トリガーまであと48行で、行数で切ると検知器群が割れる方向へ倒れる。

## consistency

- file: scripts/tests/test_review_checks.py / line: 1463 / category: test / severity: P2
  - summary: enforced 24検知器のうち3つ（`check_plan_vs_tasks`・`check_task_numbering`・`find_undeclared_fixed_values`）が入口関数を直接呼ぶテストを持たず、担保がmutateの正例1件だけ（前回P3-9の10件からは改善）。
  - failure_scenario: mutateの正例は「1検知器につき違反1件が鳴るか」しか見ないため境界が固定されていない。`check_task_numbering`（1912行）と`check_plan_vs_tasks`（1950行）は後半の「見出し番号照合」ループが**完全に同一のコード**（1971-1984と1932-1947）なので、片方を直してもう片方を直し忘れても全テストが緑のまま通る。

- file: scripts/review_checks.py / line: 3452（`guard_probe_edges`）・3901-3903 / category: test / severity: P2
  - summary: 外縁（ネガティブケース）は正しく導入されたが、22件中**15件がGAP（既知の穴）**のままで、mutateはその件数を印字するだけで落ちないため、穴を閉じる圧力がどこにも掛かっていない。
  - failure_scenario: `detected=True`（穴が塞がった）は7件、`detected=False`が15件、外側なしの宣言が2件。`cmd_mutate`は`gaps`を印字するだけでreturn 1しない。結果、`source_comment_dead_identifier_refs`の「バッククォートを付けずに綴った死んだ識別子」というGAPは宣言されたまま放置され、本体で実測すると**現に5箇所の実例**がある: `precompute_edge_attribute_counts.py:43`・`precompute_way_attribute_counts.py:18,46`・`precompute_way_divided_carriageway.py:13`が撤去済みの`ROAD_SURFACE_TILE_VERSION`を裸で名指しし、`tile_persistent_cache.py:24-25`は同じ名前をバッククォート付きで書いているが**行またぎで折り返している**ため同一行要求に掛からない。いずれも母集団の内側にあり、検知器は0件を返している。

- file: scripts/review_checks.py / line: 3719 / category: test / severity: P3
  - summary: 参考表示のみの7検知器（`count_narrative`・`cross_layer_claim`・`task_links`・`unfiled_deferrals`・`duplicate_test_scaffold`・`plan_entry_overlap`・`undeclared_dead_refs_exempted`）はmutateの正例・外縁のどちらの対象にもならず、出力が止まっても誰も気づかない。`undeclared_dead_refs_exempted`は`guard_probe_mutations`に違反の作り方が定義済みなのに`--case`を明示しない限り実行されない事実上の死んだプローブ。
  - failure_scenario: CLAUDE.mdが「`[x]`化の瞬間に候補を参考出力するので、その行の要否だけを判断すればよい」と運用を`unfiled_deferrals`に委ねている以上、これが黙って止まると残タスクの取りこぼしが再発する。

- file: docs/modules/README.md / line: 59-63（「このディレクトリが扱わない領域」の表） / category: doc-drift / severity: P2
  - summary: `scripts/`配下が`undocumented_files`の母集団外（`IMPL_INCLUDE_PREFIXES`がbackend/app・frontend/srcのみ）である一方、「扱わない領域」の表にも挙がっておらず、リポジトリ最大の単一ファイルが設計書の担当を持たない宙吊り状態にある。
  - failure_scenario: CLAUDE.mdは「例外は**機械が完全性を検査している表**だけ（現在はdocs/modules/*.mdの対象ファイル表）」とこの表を完全性の根拠として名指ししている。`scripts/review_checks.py`は3,952行・31検知器を持ちCLAUDE.mdが判定を委ねている中核だが、どの`docs/modules/*.md`にも記載が無く、記載を要求する検知器も動かない。新しい検知器を足す人は3,952行のソースを読むしかない。

- file: backend/scripts/measure_gradient_outliers.py / line: 2・365／同型: measure_vending_types.py:1・scripts/review_checks.py:1434 / category: doc-drift / severity: P3
  - summary: 本サイクルの追加行に`docs/comments.md`が禁じる経緯記述が4件混入しているが、`source_narrative`の母集団（backend/app・frontend/src）の外のためpre-commitもCIもブロックしない。
  - failure_scenario: 本体で測ると、母集団外（`scripts/`・`backend/scripts/`・`backend/tests/`・`backend/benchmarks/`・`frontend/e2e/`、225ファイル）の経緯コメントは**765件**で、母集団内の全件参考値60件の**12.75倍**。`source_narrative`の外縁はGAPとして宣言済みだが、この765という規模はどこにも記録されておらず、「新規混入は機械が止める」という宣言と実態の開きが読み手には見えない。

- file: .github/workflows/deploy-backend.yml / line: 15-25 / category: doc-drift / severity: P3
  - summary: CLAUDE.mdが「対象と、**コンテナを入れ替えるかの振り分け**はそのワークフローが正本」と書くが、ワークフローに振り分けは存在せず、常にビルドして入れ替える1本道である。唯一の「振り分け」は`paths`の`!backend/benchmarks/**`による起動有無だけ。
  - failure_scenario: 「振り分けがある」と読んだ人が、`backend/migrations/`だけの変更ならコンテナは入れ替わらない（＝90秒のグレース停止は起きない）と誤解して、本番リクエストが走っている時間帯にpushする。

## 前回の中心テーマに対する判定（総括）

- **是正された**: `removed_axis_ids`（2179行）の`if "_" in a`はスナップショット履歴由来のidには掛からなくなり、`openness`/`curvature`は母集団に入った（実測: `gone` 81件に両方＋日本語ラベル`開放度`・`蛇行`を含む）。実在判定corpusは`split_source_comments`でコメントを除くようになり、リンクは`unresolvable_links`でパス解決するようになった。`guard_probe_edges`は外縁＋対照＋観測記録という三重の縛りで、前回指摘の「プローブを母集団の内側から作る」構造そのものを壊している。**設計としては正しく直っている。**
- **同じ型が再生産されている**: 前回は「記法での絞り込み（バッククォートの有無）」だった。今回は「**より長いバッククォート語の内側**」と「**行またぎで折り返したバッククォート**」という2つの新しい記法条件が、同じ1つの撤去（`ROAD_SURFACE_TILE_VERSION`）の残骸を8箇所以上にわたって隠している。外縁のケース表は「バッククォート無し」だけを穴として固定したため、この2つは外縁としても試されていない。
- **測られていない緩和**: architecture.mdの段落免除（非空行の42.8%）、`FIXED_VALUES`の母集団（外に141定数）、`source_narrative`の母集団外（765件）のいずれも、T798が要求する「検査対象から外す件数と母集団に対する割合」がタスクエントリに記録されていない。

---

# シャードF: frontend/src/components/AxisStudio

## overall

- file: frontend/src/components/AxisStudio/AxisScoringSection.tsx / line: 42-46, 378-381, 390-392, 399-403 / category: structure / 一度だけの初期化された使い捨てstateが既存値を上書きする / severity: P1
  - summary: 折れ点生成フォームの3入力（`generatorZeroValue`=0／`generatorHundredValue`=10／`generatorShape`="flat"）が`useState`の固定既定値のまま`draft.breakpoints`と同期されず、しかもT922で「生成」ボタンが撤去されて**入力のたびに即`applyScoringRange`→`generateBreakpoints`が走る**ため、既存軸を開いて3入力のどれか1つに触れた瞬間に既存の折れ点が丸ごと作り直される。
  - failure_scenario: 管理者が既存の勾配系軸（例: `breakpoints=[[-2,100],[0,0],[6,60],[12,100]]`）の「編集」を押す→「0点」欄に0、「100点」欄に10が出る（この軸の実際の値ではない）→「効き方」を『S字』へ変えるだけで`generateBreakpoints(0, 10, "s_curve")`の0〜10の6点へ折れ点が置き換わり、-2と12の端点は画面からもpayloadからも消える。警告は無く、そのまま「更新する」を押すと較正済みの軸が別物になる。公開済み軸の「調整する」経路でも同じ（保存と同時に再公開されるため本番の評価がそのまま変わる）。

- file: frontend/src/components/AxisStudio/AxisStudio.tsx / line: 86-97, 106-112 / category: contract / stale closureによる誤った通知 / severity: P1
  - summary: `handleSave`が`setRepublishAxisId(null)`を呼んだ後に同一レンダーの`closeComposer()`を呼ぶが、`closeComposer`はそのレンダーの`republishAxisId`（＝軸id）をクロージャで捕まえているため、**再公開に成功した直後に「下書きのまま残った」という通知が必ず出る**。
  - failure_scenario: 公開済み軸で「調整する」→折れ点を直して「更新する」→`updateAxisDefinition`は`is_published: true`で送られ実際には再公開されているのに、一覧画面に「『調整する』で下書きへ戻したまま編集を終えました。この軸は一般ユーザーには表示されません。」が赤字で表示される。管理者は公開に失敗したと読み違え、下書きタブを探して再度編集・保存しに行く。docsが「中断した場合は必ず知らせる」と書いている通知そのものが成功時にも出るため信用できなくなる。

- file: frontend/src/components/AxisStudio/AxisStudio.module.css / line: 285-317, 354-357 / category: dead / ウィザード撤去の残骸 / severity: P2
  - summary: T924で撤去したステッパーとカード選択のCSSクラスが6件残っている（`.stepIndicator`・`.shapeKindOptions`・`.shapeKindOption`・`.shapeKindOptionSelected`・`.shapeKindOptionBody`・`.radioRow`）。参照0件を確認済み。
  - failure_scenario: 次に「点数の決め方」の見た目を触る開発者が`.shapeKindOption`の枠線・選択色を現行UIのものと思って調整し、画面に何も反映されないまま原因を探す。削除条件の記載も無いため意図的な併存か残骸かが判定できない。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 55-59 / category: structure / フォールバック値で固定される初期化 / severity: P2
  - summary: `draft`は`useState(() => draftFromExisting(editing, materialOptions))`で**初回レンダーの`materialOptions`＝静的フォールバック（ビルド時生成物`material-catalog.json`由来）から1回だけ**組み立てられ、`useMaterialCatalog()`の実行時フェッチが解決しても再導出されない。`draftFromExisting`は`isAxisReference = (m) => !materialOptions.some(...)`で判定するため、判定の入力が古いカタログに固定される（判断原則16「フォールバックがDB値の伝播失敗を隠す」型）。
  - failure_scenario: backendに新しい材料を足して本番へ入り、frontendの再デプロイがまだの状態で、その材料を使う軸を「編集」で開く。`materialOptions`にその材料idが無いため他軸参照と誤判定され、`shapeKind`が`recipe_then_breakpoint_linear`になり、折れ点エディタ・分布プレビュー・「何点にするか」が一切出ず「組み合わせる軸」の画面が開く。実行時カタログが届いても画面は直らない。（推測: ズレの窓はbackendデプロイ〜frontendデプロイ間に限られるが、`useMaterialCatalog`の実行時フェッチはまさにその窓を埋めるために存在する）

- file: frontend/src/components/AxisStudio/TuningPanel.tsx / line: 14-20 / category: duplication / backendの列挙を画面が手書きで持つ / severity: P2
  - summary: `EFFECT_GROUPS`がbackendの`domain/tuning.py: TuningEffect`の全メンバーを文字列で手書きしている。生成型`TuningParameterView.effect`は`string`（`api.d.ts:2337`）のため綴りの型検査も効かず、ドリフト検知テストも無い。構造仕様8に対し、効き方の追加点だけがbackend+frontendの2箇所になっている。
  - failure_scenario: backendに`TuningEffect.TILE_REBAKE = "tile_rebake"`を足して較正値を1件そこへ移すと、`TuningPanel`はその行を「その他」という見出しの下へ無言で落とす。画面の存在理由である「変えたのに効かない群がそれと分かる」がその行だけ失われる（`TuningPanel.test.tsx:64`の「その他」テストは、この劣化を検知ではなく許容として固定している）。

- file: frontend/src/components/AxisStudio/AxisScoringSection.tsx / line: 1-682（特に238-529と531-676） / category: structure / 規模ウォッチ発火ファイルの変更理由 / severity: P3
  - summary: 682行の中に変更理由の異なる3クラスタが同居: ①材料選択→入力欄の出し分け（37-233）、②折れ点の較正まわり（342-527、約185行、T598/T922で連続して動いている）、③categorical材料の値入力（531-676、約145行）。②と③は互いのコードを参照せず`draft`/`setDraft`と`materialOptions`だけを共有する。
  - Recommendation: ②を`BreakpointScoringFields`、③を`CategoricalScoringFields`へ切り出せば①だけが残る。**KEEPするなら`history/size_watch.json`へ理由つきの個別閾値を登録して規模ウォッチの再発火を止める**（`AxisComposer.tsx`がT355で辿った運用と同じ）。

- file: frontend/src/components/AxisStudio/AxisScoringSection.tsx / line: 170, 681 / category: dead / ステップ構造の名残 / severity: P3
  - summary: コンポーネント本体が`function renderShapeParamsStep() { ... }`を定義して最後に`return renderShapeParamsStep();`するだけの一段の無意味な間接がある。
  - failure_scenario: （推測）名前が`...Step`のため読み手は「他にもStep関数があって切り替わる」と読み、どこで分岐しているかを探す。実際には分岐は無い。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx:69 と AxisMapDisplaySection.tsx:41,43-46 / category: structure / 分割で生じた状態の二重管理 / severity: P3
  - summary: しきい値まとめ入力のエラー文字列を、子（`thresholdErrorState`、表示用）と親（`thresholdError`、検証用）が同じ値でそれぞれ持ち、`setThresholdError`が両方へ書く。真の所有者が1つに決まっていない。
  - failure_scenario: （推測）将来しきい値入力が別の節へ移る・複数になると、親側だけが古いエラーを保持したまま保存を止める／通す状態が作れる。現時点では3経路が必ず両方を更新するため実害は観測できていない。

- file: frontend/src/components/AxisStudio/axisScoring.ts / line: 1-7 / category: structure / 共有理由が消えた7行モジュール / severity: P3
  - summary: `toBreakpointX`を独立ファイルへ出した理由は「節と効き目プレビューが同じ変換を共有する」だったが、T924の再編で3つの呼び出し元がすべて同一ファイル（`AxisScoringSection.tsx`）へ集まった。専用テストも無い。

- file: frontend/src/components/AxisStudio/DistributionPreview.tsx / line: 47 / category: other / 画面がデータ範囲を決め打ちしている / severity: P3
  - summary: 「関東の道路を抽選した…本」と地域名がフロントにベタ書き。母集団を決めるのはbackendの`axis_preview_service.py`（`osm_raw_ways`全体の`TABLESAMPLE`）で、地域はDBの取込範囲次第。
  - failure_scenario: 取込範囲を関東以外へ広げた環境で軸スタジオを開くと、実際は全取込範囲からの抽選なのに「関東の道路を抽選した」と表示され、分布の代表性を読み違える。

## consistency

- file: frontend/src/components/AxisStudio/AxisScoringSection.tsx / line: 42-43 / category: doc-drift / コメントの主張と実装が逆 / severity: P1
  - summary: 「draft.breakpointsとは別の使い捨て入力欄で、**「生成」を押すまでdraft.breakpointsへは反映しない**」と書いてあるが、T924時点（`05c96456`の`AxisComposer.tsx:904`）に存在した「生成」ボタンは撤去済みで、現在は3入力の`onChange`すべてが直ちに`applyScoringRange`を呼び`draft.breakpoints`を作り直す。実在しない操作を安全装置として名指ししている。
  - failure_scenario: この節を触る開発者が「押すまで反映されない」を前提に読み、生成フォームの既定値を`draft`と同期させる必要が無いと判断する（実際にoverall P1がその判断の結果として残っている）。

- file: frontend/src/components/AxisStudio/AxisMapDisplaySection.tsx / line: 51 / category: doc-drift / 実在しない識別子を名指し / severity: P2
  - summary: 「読めないまま**次へ進もうとした**場合は`validateStep`が止める」とあるが、`validateStep`はリポジトリ全体に存在しない（現行は`AxisComposer.tsx: validateSection`）。「次へ進む」操作もウィザード撤去で消えている。
  - failure_scenario: しきい値入力の検証を追う開発者が`validateStep`を探して見つからず、検証が抜けていると誤認して二重に検証を足す。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 19-22 / category: contract / 表示専用フィールドの列挙が1件欠けている / severity: P2
  - summary: `editing` propのJSDocが制限モードで編集できるフィールドを5件**手で数え上げ**ているが、backendの`_COSMETIC_ONLY_FIELDS`（`domain/axis_definitions.py:356-365`）は6件で`display_band_labels_override`が漏れている。実装（`AxisMapDisplaySection.tsx:187-215`）は制限モードでも体感ラベルを編集させるため、コメントより実装の方が広い。
  - failure_scenario: 「表示だけ編集で体感ラベルは変えられないはず」と読んだ開発者が公開済み軸の体感ラベル編集をバグとみなして塞ぐ。塞いだ結果、風の軸の凡例文言を変えるのに`unpublish→PUT→republish`が必要になり、その間一般ユーザーの軸カタログからその軸が消える。

- file: frontend/src/components/AxisStudio/AxisComposer.cosmeticRoundTrip.test.tsx / line: 28-37 / category: test / 検査の母集団を手で列挙している / severity: P2
  - summary: T926の回帰テストは`Object.keys(definition)`を母集団にしている点は良いが、**除外リスト`COSMETIC_FIELDS`がbackendの`_COSMETIC_ONLY_FIELDS`の手写し**で、両者を突き合わせる検査が無い（構造仕様12）。
  - failure_scenario: backendが`panel_hint`を`_COSMETIC_ONLY_FIELDS`から外した場合、このテストは`panel_hint`を除外したまま通り続ける。一方`AxisComposer`は`panel_hint`を常に組み立てて送るため、公開済み軸の「表示だけ編集」が本番で`AxisPublishedImmutableError`を返す——T926が直したのとまったく同型の欠陥が、その回帰テストの下をすり抜ける。

- file: frontend/src/components/AxisStudio/AxisStudio.tsx:99-112 と AxisStudio.adjustPublished.test.tsx:30-63 / category: test / 変更の中心経路を通るテストが0件 / severity: P2
  - summary: T924/T926で新設された「調整する→編集→保存で再公開」の**保存側分岐（`republish ? { ...payload, is_published: true } : payload`）を通るテストが1件も無い**。`AxisStudio.adjustPublished.test.tsx`は「unpublishしてモーダルが開く」「中断したら通知が出る」の2件だけ。
  - failure_scenario: この未検査の分岐にoverall P1（保存成功後の誤通知）が現に潜んでいる。`is_published: true`の付け忘れ・付けすぎも同様に検知されないまま本番へ出る。

- file: frontend/src/components/AxisStudio/AxisStudio.tsx:106-107 と AxisMapDisplaySection.tsx:283-292 / category: contract / 画面の操作結果が保存時に無言で反転する / severity: P2
  - summary: 「調整する」中は軸が下書きへ戻っているため`restrictedDisplayOnly`がfalseになり「公開する」チェックボックスが**オフの状態で表示・操作可能**になるが、保存時は`republish`判定で無条件に`is_published: true`が上書きされる。設計原則のUI仕様「1つの状態は1つの場所でだけ操作する」に反する。
  - failure_scenario: 管理者が「調整する」で折れ点を直しつつ「やはり一旦下書きに留めたい」と考え、チェックが外れていることを確認して「更新する」を押す。意図に反して軸は再公開され、一般ユーザー向けの軸カタログへ調整途中の定義がそのまま出る。

- file: frontend/src/components/AxisStudio/AxisComposer.test.tsx / line: 1-6, 43, 110, 396, 580, 672, 677, 858-861, 873 / category: doc-drift / 撤去済みウィザードを語る記述とアサーション / severity: P2
  - summary: ウィザード撤去後も「T332で4ステップウィザードへ再構成」「ウィザードをuserEventで実際に操作して」「『基本情報』ステップで」「ステップが進まない」「ウィザードの最終ステップ(4/4)へ『次へ』で遷移すると…原因は**AxisComposer.tsx 1017行目付近**参照」が残る。`AxisComposer.tsx`は現在327行で1017行目は存在しない。同型は`AxisComposer.emptyMaterialCatalog.test.tsx:37,40`・`axisDraft.test.ts:5`にもある。
  - failure_scenario: 開発者が`AxisComposer.tsx:1017`を開けず、4ステップの分岐がどこかに残っていると考えて存在しないステップ状態を探す。`queryByRole("button", {name:"次へ"})`の不在アサーション（3箇所）は、撤去済みUIの不在を確かめるだけの空回りのまま残っている。

- file: frontend/src/components/AxisStudio/AxisComposer.tsx / line: 60-66, 83-84 / category: dead / 切り出しで宙に浮いたコメント / severity: P3
  - summary: `useMaterialValues`を説明するコメントが残っているが、当該フックは`AxisScoringSection.tsx:39`へ移り`AxisComposer.tsx`はimportすらしていない。84行目の「上記のフック呼び出し（useMaterialCatalog/useState/**useMaterialValues**）」も同様。
  - failure_scenario: Rules of Hooksの根拠として「3つのフックを早期returnより前で呼び終えている」と書かれているため、読み手はこのファイルに3つフックがあると信じる。実際は2つ。

- file: frontend/src/components/AxisStudio/axisDraft.ts / line: 241-243, 283-286 / category: doc-drift / 成立しなくなった「カード」という語 / severity: P3
  - summary: 「元々どのカードで作られた軸か」「表示するカードを推定し直す」「draft.shapeKindはユーザー向け**カード選択**」と、T924で撤去した3択カードUIを現行の仕組みとして語っている。現在の入口は「点数のもとになるもの」セレクト1つ。同型は`AxisComposer.test.tsx:342, 733`にもある。
  - failure_scenario: `shapeKind`の3値を「利用者に見えるカードの種類」と読んだ開発者が、撤去した呼び名選択をカタチを変えて戻す。

- file: docs/modules/frontend/axis-studio.md / line: 37 / category: doc-drift / 対象ファイル表の所有者が古い / severity: P3
  - summary: 対象ファイル表が`breakpointTools.ts`を「**`AxisComposer.tsx`が使う**」としているが、実際の利用者は`AxisScoringSection.tsx`と`BreakpointCurveEditor.tsx`で、`AxisComposer.tsx`はimportしていない。同じ文書の229行目は正しく書いており、文書内で矛盾している。

- file: frontend/src/components/AxisStudio/AxisStudio.module.css / line: 229, 319-320, 327-328, 359-360 / category: doc-drift / CSSコメントが指すファイルが古い / severity: P3
  - summary: 4箇所のCSSコメントが所有者を`AxisComposer.tsx`と名指しするが、実体は移動済み（`AxisFormFields.tsx`・`BreakpointCurveEditor.tsx`・`AxisScoringSection.tsx:608-614`）。
  - failure_scenario: `.sliderNumberField`の見た目を直す開発者が`AxisComposer.tsx`を開き、該当JSXが無いためCSSが死んでいると判断して削除する。

- file: frontend/src/components/AxisStudio/BreakpointCurveEditor.tsx / line: 3-5, 36-38 / category: doc-drift / 移動済みの所在を語る＋同じ説明の二重化 / severity: P3
  - summary: 冒頭と関数JSDocが「数値入力行は**AxisComposer側に残り**…」とほぼ同文で2回書かれている。数値入力行は`AxisScoringSection.tsx:456-481`へ移動済み。

- file: frontend/src/components/AxisStudio/AxisStudio.tsx / line: 225 / category: ui / 通知をエラーの見た目で出している / severity: P3
  - summary: 「調整する」の中断通知（`notice`）が`listError`と同じ`styles.errorText`（`--color-danger`）で描かれる。内容は操作の失敗ではなく状態の案内。
  - failure_scenario: 管理者は赤字を保存失敗と読み、成功している編集をやり直す。overall P1（成功時にも出る）と重なると「赤字が出たが何も壊れていない」が常態化し、本物の`listError`も読み飛ばされる。

---

# シャードG: 操作パネル（MapOverlayControls・LensControl・RouteSettingsPanel）・生成物

## overall

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 137-159 / category: structure / レイヤーidのハードコード表 / severity: P2
  - summary: `LAYER_ICONS`（`Record<MapLayerId, ...>`、15個のレイヤーidを直書き）が残っており、「レイヤー追加時に`MapOverlayControls`側は変更しない」という`mapLayers.ts:1-8`の宣言が今期も破られた。
  - failure_scenario: 本期間の`fc9ba69a`（T914、起伏レイヤー追加）で、実際に記述子追加だけでは済まず`LAYER_ICONS`へ`hillshade: HillshadeIcon`を足す必要があった。`mapLayers.ts:1-8`の手順どおりに進めた人はアイコン追加を`tsc`のエラーで初めて気づく。軸側は`axisIconPalette.tsx: axisIconFor(iconId)`で軸自身のデータから解決できており、レイヤー側だけが記述子に`iconId`を持たない。**2026-09-16レビューのP2-15および同shards:716で既出・未解消**。

- file: frontend/src/components/Map/legendFilter.ts / line: 99-102 / category: dead / 表示されない要約生成パイプライン / severity: P2
  - summary: `summarizeLegendFilters`の出力（`OverlayLayerChip.summary`）が画面へ到達する経路が1つも無い。
  - failure_scenario: `MapOverlayControls.tsx:880-890`（メンバータイル）・`:1145-1150`（単独チップ）は`legendDetails`が非空なら`summary`を描かない。`summary`が実際に描かれるのは`legendDetails`が空のときだけで、それが起きるのは`page.tsx:1227-1229`の`tileZoomTooWide`のときのみ——そしてその場合`summary`も`TILE_ZOOM_TOO_WIDE_SUMMARY`で上書きされる。結果、`page.tsx:1079`・`:1128`が毎レンダー計算する「アスファルトのみ」「コンクリート以外」等の絞り込み要約文は**一度も表示されない**。`MapOverlayControls.test.tsx:241-242`は逆に「1行要約テキストそのものは表示しない」ことをアサートしている。`legendFilter.test.ts`には10件の単体テストがあり、要約規則の保守コストだけが残っている。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 880-890, 1145-1150 / category: structure / 契約の担保が別ファイルにある / severity: P2
  - summary: 前回P0だった「ズーム不足の案内が出ない」欠陥の原因構造（`hasLegend ? 凡例 : summary`）がそのまま残っており、案内が出ることを担保しているのは`page.tsx`側が凡例を空にする配線だけ。
  - failure_scenario: T896/T888段階2の修正自体は保たれている（`page.tsx:1227-1229`、`page.test.tsx:2102`・`:2126`が記述子由来の全対象idについて検証済み）。ただし描画側の規則は「凡例があれば凡例、無ければsummary」のままで、`summary`と`legendDetails`が同時に非空になる新しいレイヤーを足すと案内が再び黙って落ちる。規則は3箇所が同じ文で述べているが、どこにも強制は無い。
  - Recommendation: 案内を凡例の上へ併記する形にすれば、`page.tsx`側の不自然な`legendDetails = []`ごと畳める。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 1-1188 / category: structure / 複数の変更理由の同居（分割判断材料） / severity: P3
  - summary: 1,188行に7つの独立した変更理由が同居: (a)チップのグルーピング・描画（`buildChipGroups`:121-133、本体:1045-1188）、(b)はみ出しのページ送り（`usePagedOverflow`:335-404）、(c)長押しリピート入力（`useHoldRepeat`:424-493）、(d)フローティングパネルの位置計算（:765-820）、(e)凡例内訳の描画（:261-324）、(f)「表示する項目を選ぶ」設定と`hiddenIds`の永続化（:927-1025、:726-740）、(g)アイコン・色クラスの対訳表（:137-169, :507-511）。**(b)(c)はMapLayerId・凡例・グループのいずれも知らない汎用フック**（合計約140行）で、`hooks/`へ出せば本ファイルの変更理由が2つ減る。(a)(e)(f)は「チップ列の見せ方」という1つの理由で同時に変わるため割る理由は無い（理由つきKEEP）。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 173-185 / category: duplication / CSS値のJS側複製に検査が無い / severity: P3
  - summary: `PANEL_GAP_PX = 8`（`--space-2`）・`DETAIL_PANEL_MAX_HEIGHT_PX = 256`（`.detailPanelBase`の`min(45vh, 16rem)`）がCSSの値を手で写しており、ずれても誰も気づかない。
  - failure_scenario: `MapOverlayControls.module.css:397`の`16rem`を`20rem`へ広げると、JS側は256pxのまま計算するため、画面下端に余裕がある場所で開いたパネルだけがCSSの上限まで伸び、下端付近では256pxで頭打ちになる——「同じパネルなのに開く場所で高さの上限が変わる」という再現条件の分かりにくい挙動。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.module.css / line: 109-111 / category: dead / 到達しないCSSルール / severity: P3
  - summary: `.chipRow::-webkit-scrollbar { display: none }`は、T374で`.chipRow`が`overflow`を持たなくなった現在、何も効かない（スクロールするのは`.chipRowViewport`で`overflow: hidden`）。

- file: frontend/src/types/generated/region-tile-config.json / line: 12-16 / category: contract / 規則を述べたコメントの直下でその規則を破っている / severity: P3
  - summary: T848で road_surface/accident/poi の`tile_version`をビルド時生成物から外したがlandcoverだけ残り、その理由がどこにも書かれていない。`export_openapi.py:131-134`が「タイルの世代はここへ書かない」と書き、13行下の`:147`で`"tile_version": LANDCOVER_TILE_VERSION`を書いている。`regionApi.ts:52-55`も同じ矛盾。実装上は正当（`LANDCOVER_TILE_VERSION`はコード由来でバッチでは動かない）だが、コメントは例外を述べていない。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.test.tsx / line: 397-398 / category: duplication / 同じ実測値の3重持ち / severity: P3
  - summary: 「375×812で23%/54%/72%」という同じ実測値が`mapLayers.ts:522-525`・`docs/modules/frontend/static-map-layers.md:289-291`・本テストコメントの3箇所にある。加えてこのテストコメントは本diffの追加行で、`docs/comments.md`が禁じる「実測で〜だったため」型の経緯記述に該当する。

## consistency

- file: frontend/src/components/LensControl/LensControl.tsx / line: 36-39 / category: contract / 段階キーの語彙がramp軸で一致しない / severity: P2
  - summary: 「ルート前とルート後で同じ段階キーを共有する」という新設の契約が、ramp軸では成立しない（ルート前は`${axisId}-${i}`〔`axisLayers.ts:525`〕、ルート後は`step-${i}`〔`routeStyleModes.ts:110`→`mapColorLegend.ts:24`〕）。同じ保存先`hiddenLegendKeysByMode[axisId]`を2つの語彙が共有している（`page.tsx:969`・`:973`）。
  - failure_scenario: ルート未生成でレンズにramp軸（例: 車の圧迫感）を選び凡例の1段階のチェックを外す→`hiddenLegendKeysByMode["car_stress"] = ["car_stress-2"]`が保存され全道路の塗りからその段階が消える。ここでルートを生成すると`page.tsx:1438`が`step-2`側の語彙へ切り替わるため、(1)ルート線では何も隠れていないのにレンズのピルと見出しチェックが「一部非表示」の見た目になり、(2)「ルート後も周囲の道路を薄く塗る」がONなら背景の道路では依然その段階が消えたままなのに一覧のどの行にもそれが表示されない。逆向きも同様。`mapColorLegend.ts:21-23`のdocstringは専用way値配信軸（風・勾配）でのみ真。テストも両語彙の突き合わせを1件も持たない（`LensControl.test.tsx`の`LEGEND`は架空キー）。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 801-820 / category: contract / 自動折りたたみ時に浮いたパネルのキーが残る / severity: P2
  - summary: T888段階3で追加した`withinExpandedGroupLimit`によるグループの自動折りたたみが、そのグループのメンバーが開いていたフローティングパネルのキー（`member:*`）を`expandedIds`から消さない。
  - failure_scenario: (1)「道路」グループを展開、(2)「道路種別」タイルの▶で凡例を開く、(3)「環境」グループをタップ——`toggleExpanded`の排他クローズは`!GROUP_VISIBILITY_KEYS.has(id)`のときだけ走る（:810）ためスキップされ、`withinExpandedGroupLimit`（:816）はグループキーしか畳まないので`member:roadType`が残る、(4)もう一度「道路」をタップすると、▶を押していないのに道路種別の凡例パネルが**(2)の時点で測った座標のまま**再び浮かぶ。同ファイル:1027-1032が`closeGroupLegend`を設けた理由とまったく同じ型の欠陥で、新しい自動折りたたみ経路にだけ対応する片割れが無い。

- file: frontend/src/components/LensControl/LensControl.module.css / line: 183-198 / category: ui / 390px幅での横あふれ（推測を含む） / severity: P2
  - summary: 本diffで`.legendList`を2列グリッド（`minmax(9rem, 1fr)`）に、`.legendRow`に`white-space: nowrap`を新設したが、実在する公開軸の段階ラベルは1列ぶんの幅に収まらない。
  - failure_scenario（**実機未確認、コード上の推測**）: 390px幅で`.content`は`min(24rem, calc(100vw - 1.5rem))` = 366px、paddingを引いて内側≒344px。`repeat(auto-fill, minmax(9rem, 1fr))`＋`column-gap: 0.5rem`で2列になり1セル≒169px。一方`axis-catalog.json`の公開軸「停止密度」の`display_band_labels_override`は「250〜500mで1回停止」で、`routeStyleModes.ts:110`が`${labels[i]}（${rangeLabel}）`へ組み立てるため実際の行は「250〜500mで1回停止（46.7〜65.5）」になる。`--font-size-sm: 0.75rem`で全角13字＋半角9字≒210px、チェックボックス・色見本・gap（≒37px）を加えると**1セルの約1.5倍**。`nowrap`のため折り返さず、`.content`は`overflow-y: auto`を持つ（CSS仕様上`overflow-x`も`auto`に計算される）ので、ポップオーバー内に横スクロールバーが出るかラベル末尾が見切れる。風軸の「非常に強い向かい風（80〜100）」も同様。

- file: docs/modules/frontend/static-map-layers.md / line: 300-308 / category: doc-drift / 状態の書き手が1つ増えたのに記載が追従していない / severity: P2
  - summary: 「凡例カテゴリの絞り込み」節が`hiddenLegendKeysByMode`の書き手として`MapOverlayControls`だけを挙げ、本期間（T920）で2つ目の書き手になった`LensControl`を書いていない。節の見出し自体も撤去済みのサイドバーを名指ししている。
  - failure_scenario: 段階の表示ON/OFFの仕様を変える人がこの節だけを読み、`MapOverlayControls.tsx`の▶パネルだけを直す。`LensControl.tsx:171-192`と`page.tsx:996-998`が同じ状態を書いているため片側だけが新しい規則で動く——これは上の「段階キーの語彙が一致しない」欠陥が生まれた経路そのもの。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 259, 272-274, 651-652 / category: doc-drift / 撤去済みサイドバーを基準にした説明の残存 / severity: P3
  - summary: 撤去済みの`MapLayersPanel`（サイドバー）の実装を引き合いに出すコメントが3箇所残り、うち1つは本期間で成立しなくなった対比を述べている（:272-274「狭い▶パネルに2ボタンを置く余地が無いため1つのチェックボックスで兼ねる」——参照先は存在せず、さらに本diffで`LensControl`も同じ1チェックボックス方式に揃った）。同型は`MapOverlayControls.test.tsx:24-27`・`:150`にもある。本diffは`.module.css`側の同種参照3件（前回P3-22）を消しているので、**同じ一掃が.tsx/.test.tsxに届いていない**。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.module.css / line: 378-382 / category: doc-drift / 実在しない識別子を名指しするコメント / severity: P3
  - summary: `.expandArrowDownOpen`のコメントが「▶方向（単独チップの"flatRight"）」と書くが、`flatRight`はT418で撤去済みで現在の`expandDirection`は3値のみ。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.tsx / line: 150-156 / category: doc-drift / 存在しない辞書エントリを説明する孤立コメント / severity: P3
  - summary: `LAYER_ICONS`内に「勾配の環境グループ面表示。…elevationと同じElevationIconを流用する」というコメントがあるが、`gradient`という`MapLayerId`も該当エントリも存在しない。**2026-09-16レビューのshards:721で既出・未解消**。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.module.css / line: 180-182 / category: doc-drift / 追加行が同じ主張を二重に書き、経緯を含む / severity: P3
  - summary: 本diffが`MapLayersPanel`参照を消す際に、直前の行とほぼ同じ主張の文を1行足してしまっている（「以前の文字だけの横スクロールチップより…」／「以前のサイドバー側（撤去済み）の『表示』チップより…」）。後者は`docs/comments.md`が禁じる経緯記述そのもの。

- file: frontend/src/components/LensControl/LensControl.test.tsx / line: 88-97 / category: test / 消えた分岐を名乗るテストと、その重複 / severity: P3
  - summary: テスト名が本diffで削除された「propsが無いときは読み取り専用の凡例」分岐を今も検証しているかのように述べており、実体は`:105-114`の新テストと同じ経路の重複。2つのテストの唯一の差は`hasDetail`だが、凡例ブロックは`hasDetail`を一切読まないため、片方を消しても検知される欠陥は1件も増えない。

- file: frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx / line: 262 / category: ui / 画面に出る日本語に半角スペースが混入 / severity: P3
  - summary: prettierによる行結合で読点の後に半角スペースが残ったまま表示文言になっている（「…反映されず、 サーバー既定の配分で…」）。エラー時にしか出ない文言のため目に触れにくい。

- file: frontend/src/components/MapOverlayControls/MapOverlayControls.test.tsx / line: 313-320 / category: doc-drift / 分類規則の数え上げが1件足りない / severity: P3
  - summary: `mapOverlayGroupFor`の判定規則を列挙するコメントが「環境: category==="terrain"||"weather"」と書くが、実装（`mapLayers.ts:157-158`）は`"disaster"`も環境へ入れる。テスト名（:333）も同じ。同型は`mapLayers.ts:19-28`のカテゴリ列挙（前回P3-22で既出・未解消）にもある。

## 補足（確認できた事実）
本シャード範囲の生成物にbackendとのドリフトは検出されなかった。`openapi.json`の全パスをルーターの`@router`デコレータから逆引きして比較（差分0）、`components.schemas` 70件のうちbackendにクラス実体がある64件についてプロパティ名集合を機械比較（差分0）。`landcover-classes.json`の`painted`は`domain/landcover.py:138,148`と、`poi-kinds.json`の`vending_drinks`/`vending_unknown`は`staticAttributeLayers.ts:304-305`と、`route-generate-config.json`の`client_tuning`は`domain/tuning.py:307-316`と整合。前回P0だった「ズーム不足の案内が一度も表示されない」はT888段階2の記述子駆動で解消が保たれている（ただし描画側の`hasLegend ? 凡例 : summary`分岐自体は残存）。

---

# シャードH: frontend/src/app（page.tsx・admin）・hooks・services・lib

## overall

- file: frontend/src/app/page.tsx / line: 2342 / category: structure / 新機構の前提が満たされない経路の未配線 / severity: P1
  - summary: `tileVersionsReady`へ「タイル世代が届いたか」ではなく「軸カタログの取得が成功したか」（`axisCatalog.loaded`）を渡しており、カタログ取得が失敗すると路面・POI・事故タイルが1枚も出ず、しかも画面のどこにも理由が出ない。
  - failure_scenario: `GET /api/axis-catalog`が一時的に失敗すると`setTileVersions`が一度も呼ばれず`hasTileVersions()`がfalseのままになる。`MapView.tsx:1118`・`1388`・`1421`のensure関数がすべて無言で戻るため路面タイルのソース自体が作られない → MapLibreのsourceイベントが1つも飛ばず`mapViewLayerDataStatus`が空 → `overlayLayers`の`dataStatus`がundefined → **「道路の種類」「路面」「停止要因POI」「事故」チップはONの表示のまま、状態ドットも出ず、地図に何も描かれない**。T848以前はビルド時生成物の世代で描けていたため、カタログ取得失敗がこれらのレイヤーを巻き込むのは新規の結合。復帰導線は「ルート設定 > 重み」タブの再試行リンクだけで、地図側からは辿れない。

- file: frontend/src/services/regionApi.ts:70-75（`hasTileVersions`）／page.tsx:2342 / category: contract / コメントが約束する回復が実装されていない / severity: P2
  - summary: 「欠けているあいだはタイルを出さず、**揃った時点で描き直す**」と書いてあるが、揃った時点で描き直す経路が存在しない。
  - failure_scenario: backendのデプロイ順が前後して`tile_versions`を返さない版が応答すると`setTileVersions({})`→`loaded=true`となり`hasTileVersions()`はfalse。`MapView.tsx:3301-3306`の再描画effectは`[tileVersionsReady, redrawFromCurrentProps]`依存で`tileVersionsReady`は既にtrueなので再実行されない。**ページを再読み込みするまで路面・POI・事故タイルが戻らない**。（`tileVersionsReady`を`hasTileVersions()`由来にすれば上のP1と両方解消する）
  - 補足（兄弟ガードの非対称）: `ensureRoadSurfaceTileLayer`は`hasTileVersions()`を`applyData`の**中**で見るのに対し、`ensureAccidentTileLayer:1388`・`ensurePoiTileSource:1421`は`runWhenStyleReady`登録の**前**で見て抜ける。

- file: frontend/src/app/page.tsx / line: 1139-1141 / category: structure / T888の1本道化が兄弟境界で止まっている / severity: P2
  - summary: T888は`MapView`の`showElevation`/`showLandcover`/`showRoadType`…を`staticLayerVisibility`1本へ畳んだが、`useDynamicWeatherLayers`への境界は`showPrecipitationNowcast`/`showWindVector`/`showDisaster`という軸ごとのpropのまま残っている。
  - failure_scenario: 動的気象要素を1つ追加すると、記述子へ足すだけでは足りず、page.tsx:1139-1141へ`const showXxx = layerVisibility.xxx;`を、`UseDynamicWeatherLayersOptions`（`useDynamicWeatherLayers.ts:93-97`）へ`showXxx: boolean`を、分割代入・`visible:`マップ・依存配列へ同じ名前を書き足す。1箇所でも忘れると「チップはONで凡例も出るのに地図には何も出ない」が動的気象側で起きる。構造仕様8の射程。

- file: frontend/src/app/page.tsx / line: 1190-1197 / category: duplication / レイヤーidを名指しした対応表がハブに残る / severity: P2
  - summary: `legendDetailsByLayerId`が`route`・`precipitationNowcast`・`landcover`・`windVector`・`disaster`をリテラルで名指しし、対応する凡例定数もpage.tsxのモジュール直下にある。記述子は`defaultOn`・`tileMinZoom`・`dataNature`・`panelHint`を持つのに凡例だけ持たない。
  - failure_scenario: 表示専用の面レイヤーを1枚足すとき記述子に加えてpage.tsxへ凡例定数1つと1行を書き足す必要がある。書き忘れると▶パネルは`staticFilterSummaries`のフォールバックへ落ちて空になり、色の意味が画面のどこにも出ないまま面だけが地図に載る。

- file: frontend/src/lib/routeSplice.ts / line: 306 / category: contract / 較正値の既定がフロント側に別途存在する / severity: P2
  - summary: `options.minSplitLengthKm ?? 0`。backendの較正値（`domain/tuning.py:206` `splice.min_stretch_km`、既定0.2）が届かなかったときの既定として**0（＝下限なし）をフロントが独自に持っている**。`useAxisCatalog.ts:231-233`は「使う側は自分が要るidが無ければ既定を持たない」と明記しているが実際には持っている。backend側の`tuning_value`はfail-fastで、ガードが左右で逆向き。
  - failure_scenario: 較正値のidを改名する／`CLIENT_RELOAD`以外の`effect`へ変える／DB移行の途中で`client_tuning`にこのidが含まれない応答が返る、のいずれかで`undefined`になる。`tsconfig`は`noUncheckedIndexedAccess`無効のため型は`number`のまま通り、`?? 0`が吸収して`splitPairedStretch`が**共有ノードすべてで区間を割る**。目的地モード30km級では乗り換えグループが桁違いに増え、地図が破線の帯で埋まり「ルート編集」が実質使えなくなるが、例外もログも出ない。

- file: frontend/src/services/regionApi.ts / line: 114-116 / category: other / 同じ方針が兄弟レイヤーの一部にしか及んでいない / severity: P3
  - summary: `TILE_KINDS`（:67）は`road_surface`/`poi`/`accident`の3系統で、土地被覆だけ`regionTileConfig.landcover.tile_version`（ビルド時生成物）のまま。:52-55が掲げる理由が土地被覆に当てはまらないのかはコードからもコメントからも判断できない。

- file: frontend/src/app/page.tsx / line: 344-358（splice関連state群） / category: structure / ハブ状態の単位 / severity: P3
  - summary: 区間の乗り換え1機能のために7つのstateがハブへ並び、派生値6つと3つのhandlerも同じ場所にある。これらは「編集セッション」という**1つの理由**で一緒に変わる。
  - failure_scenario: リセット箇所が3つに散っているため、4つ目の「編集セッションを抜ける」経路を足したときに1つ落とすと、前回の`splicePreviews`が次の編集で使い回される（キーは`index:candidateId:start-end`だけで元ルートidを含まない）。実際`renderRouteEditSectionBody`の`onCancel`（:2164-2168）は`setSplicePreviews({})`を呼んでおらず、入口側（:1881-1886）の初期化に依存している。

- file: frontend/src/app/page.tsx / line: 1543-1546 / category: perf / 毎レンダーの全payload再構築 / severity: P3
  - summary: `conditionsDirty`が毎レンダー`buildCurrentGenerationInput(...)`→`generationConditionsKey(...)`（payload全体のJSON化）を実行する。同じファイルは`candidateShapes`（:798）等を同じ理由でuseMemoしており方針が揃っていない。

## consistency

- file: backend/app/domain/route.py / line: 142-145 / category: contract / コード自身が述べる契約と実装が逆 / severity: P2
  - summary: 「**フロントはこの印を見ない**」と断言しているが、`frontend/src/lib/routeSplice.ts:150`が`routes[0].is_fastest`を読んで先頭固定の判定に使っている。**どちらが正かはフロント側**——`route_generator.py:612`の`candidates.sort(key=lambda c: not c.is_fastest)`と対になった並び順の規約で、`page-composition.md:19`もこの使い方を正としている。2026-09-16のP2-10でこの行が指摘され、T904が「backend側のコメントだけが古かった」として書き換えたにもかかわらず、**書き換え後の文も同じく偽のまま**（3回連続の未解消）。
  - failure_scenario: この断言を信じた担当者が`is_fastest`の付与条件を変える／撤去すると、`insertByDifficulty`の`pinned`が常に0になり、目的地モードで合成したルートが基準線より前へ差し込まれる。並び順が変わるだけで例外もテスト失敗も出ない。正しい記述は「表示（タブの最速バッジ）には使わないが、合成候補を差し込む位置の判定には使う」。

- file: docs/modules/frontend/page-composition.md / line: 270-272 / category: doc-drift / 同一ファイル内で矛盾（前回未解消） / severity: P2
  - summary: 「`RouteCandidate.is_fastest`が立つ候補は**順位番号の代わりに**「最速」と示し」と書いているが、実装は順位番号を常に出し、`fastestRouteIdInList`のときだけバッジを**追加**する。同ファイルの:207-211が正しい説明をしており、正本の中で2つの定義が同居。2026-09-15シャードで既出、未解消。
  - failure_scenario: 周回モードの候補一覧を触る担当者が:270を読み、`page.test.tsx:1094`「周回モードでも『最速』と超過分を出す」を仕様違いとみなして消す。T818がユーザー指摘を受けて入れた表示がdocsを根拠に巻き戻る。

- file: docs/modules/frontend/page-composition.md / line: 222-223 と 301-306 / category: doc-drift / 操作の入口の位置が実装と違う / severity: P2
  - summary: :222「入口は**候補の中身**の「このルートを編集」」と書いているが、実装では`renderRouteResultHeaderActions()`（`page.tsx:1871-1893`）の**先頭のアイコンボタン**。さらに:301-306は同じヘルパーが「「GPX出力」・「ルートをクリア」…操作アイコン**のみ**を持つ」と述べ3つ目の存在を否定している。
  - failure_scenario: ヘッダの操作枠を整理する担当者が:301-306を「2つ」と読み、編集アイコンを紛れ込んだものとして撤去する。乗り換え機能（T621〜T874）への唯一の入口が消えるが、`renderRouteEditSectionBody`は`editingRoute`がnullのままなので何も描画されずテストも十分には落ちない。

- file: frontend/src/app/page.tsx / line: 2240-2242 と 2485-2486 / category: doc-drift / 撤去済みの区分を語るコメント / severity: P2
  - summary: :2240-2242「サイドバーは…「ルート設定／ルート結果／**ルート編集**」の**3区分**」と書いているが実際の`Disclosure`は2つ。:2485-2486も「モバイル: 部分シート**3枚**（…「**地図の見え方**」）」だが`MobileSheet`型（:303）は2値で`BottomSheet`も2枚。
  - failure_scenario: モバイルレイアウトを触る担当者が3枚目のBottomSheetと3つ目のタブを再実装する。`MapOverlayControls`と重複した入口ができ、design-principles.md「1つの状態は1つの場所でだけ操作する」に正面から反する。

- file: frontend/src/app/page.tsx / line: 584-586 / category: doc-drift / T888で成立しなくなった手順が同一ファイル内に残る / severity: P2
  - summary: 「地図レイヤーのON/OFF（**MAP_LAYERS**のid単位。**レイヤーを追加したらDEFAULT_LAYER_VISIBILITYへ初期値を1つ足す**）」。T888で`DEFAULT_LAYER_VISIBILITY = buildDefaultLayerVisibility()`（:188）となり足す必要は無くなった。同じファイルの:182-183が正反対を書いている。あわせて`MAP_LAYERS`は本番コードに存在しない（コメント3箇所のみ、定義ゼロ）。
  - failure_scenario: レイヤーを足す担当者が:584に従って手で1行足そうとし、導出関数であることに気づいて`buildDefaultLayerVisibility`を手書きオブジェクトへ戻す方向へ直す。構造仕様12がこの1コメントで巻き戻る。

- file: frontend/src/app/page.tsx / line: 961（ほか本番コード7箇所） / category: doc-drift / 存在しない識別子の名指し / severity: P2
  - summary: 「（ビルド時静的**STATIC_FILTER_AXES**は使わない）」。`STATIC_FILTER_AXES`は本番コードに存在せず、`MapView.overlayFilters.test.ts:22`と`staticAttributeLayers.test.ts:40`がテスト内ローカル定数名として持つのみ。本番コードで同名を名指しするコメントは他に`mapLayers.ts:390`・`MapView.tsx:1186`・`:1457`・`:1772`・`:2047`・`staticAttributeLayers.ts:18`・`:328`の計8箇所。
  - failure_scenario: 探した担当者が`grep`でテストファイルの定義に行き着き、テスト用の構築物を本番の正本と取り違える。`staticAttributeLayers.ts:18`は「（ファイル末尾）にカタログ化し」と場所まで指しているため実在すると信じる根拠が強い。
  - failure_scenario（検知器側）: `source_comment_dead_identifier_refs`が0件を返し続けているのは実在判定のcorpusが`*.test.ts`の**コード**を含むため（`corpus_files(files, include_tests=True)`）。**この8件はまさに「テストのローカル変数がコメントを支えている」形**で、母集団からテストのローカル定数を外せば機械的に拾える。

- file: frontend/src/services/regionApi.ts / line: 42-51 / category: doc-drift / 撤去済みの運用手順が直後の新方針と矛盾 / severity: P2
  - summary: 「タイル内容の世代。…**上げると**…**バックエンドのファイルキャッシュ側の世代と対で更新すること**」という手動での世代上げ手順が丸ごと残り、直後の:52-59「タイルの世代は**実行時にbackendから受け取る**…ビルド時生成物には持たない」と正面から矛盾する。
  - failure_scenario: タイルへ焼き込むプロパティを増やした担当者が:42-51に従って世代定数を探す→見つからないので`landcover.tile_version`にならって手書きの定数を復活させる。`cache_identity.shape_digest`と二重になり片方だけ上がる状態が生まれる。

- file: frontend/src/services/regionApi.test.ts / line: 57-62・69-74・78-80 / category: test / 名前が主張する検査を実際にはしていない / severity: P2
  - summary: テスト名「…レイヤー名・**世代**がbackend生成物（region-tile-config.json）と一致する」が残っているが、世代の比較先は`beforeEach`で自分が`setTileVersions(TILE_VERSIONS)`に渡した定数（:33）で、生成物とは無関係のトートロジー。実際`region-tile-config.json`から3系統の`tile_version`は撤去済み。
  - failure_scenario: `current_tile_versions`の辞書キーをbackend側で改名すると`TILE_KINDS`は追従しないため本番で全タイルが出なくなるが、フロントのテストは自分で入れた3キーを使い続けるため全件緑のまま通る。**この非対称こそ検査すべき対象**（`TILE_KINDS`とbackendの`TILE_SHAPES`のキー一致を見るテストが1件も無い）。

- file: frontend/src/app/page.tsx / line: 136-138 / category: doc-drift / 移設済みの実装を説明する宙に浮いたコメント / severity: P2
  - summary: 「…**フロントは既存の距離計算ユーティリティを持たないためここに最小実装する**」が、直後の定数は無関係な`LEGEND_FILTER_DEBOUNCE_MS`（:143）。説明対象の実装は`lib/geoDistance.ts: haversineKm`へ移設済み（:56でimport）で、「ユーティリティを持たない」という前提自体が偽。「ここに最小実装する」は`docs/comments.md`が禁じる経緯記述の型でもある。

- file: docs/modules/frontend/static-map-layers.md / line: 32 / category: doc-drift / 撤去済みの構造を指す / severity: P3
  - summary: 「`services/regionApi.ts`（…と**タイル世代定数**）」と書いているが世代定数はもう無い。さらにこのモジュールの挙動として最も非自明な「路面・POI・事故タイルは`GET /api/axis-catalog`が成功するまで1枚も出ない」がどこにも記載されていない。

- file: frontend/src/app/admin/api/tuning/route.ts、frontend/src/app/admin/api/tuning/[paramId]/route.ts / line: 全体 / category: test / 兄弟が持つテストが新規分だけ無い / severity: P3
  - summary: 兄弟の`axis-definitions`は3本のテストを持つが、今回追加された`tuning`側は0本。**この経路を通るテストが1件も無い**。
  - failure_scenario: `paramId`は`splice.min_stretch_km`のようにドットを含む。Next.jsのdynamic route paramsの扱いを変える改修で壊れても、TuningPanelのテストは`tuningApi`をモックしているため落ちず、`/admin`の「較正値」タブで保存だけが404になる。認可境界自体は`proxy.ts`の`matcher`が覆っており素通しは無い。

- file: frontend/src/lib/routeSplice.ts:306／page.tsx:309-318, 835 / category: test / 新設したガード・既定に空回りの確認が無い / severity: P3
  - summary: (a)`minSplitLengthKm`未指定時の`?? 0`を通るテストが無い。(b)`spliceFeatureIndex`の上限超過`throw`を通すテストが無い。(c)page.tsx:835が`clientTuning`の値を実際に`stretchAlternativeGroups`へ渡していることを見るテストが無い。
  - failure_scenario: (c)が無いため`clientTuning`のキー名を打ち間違えても、hook単体テストとroutesplice単体テストの両方が緑のまま実画面だけが下限なしで動く。

- file: frontend/src/hooks/useDedicatedWayValues.ts:6-7、32-33／regionApi.ts:149-157、168、203 / category: doc-drift / 鍵の改名（T918）に伴う周辺表現の残り / severity: P3
  - summary: 型と主要docstringは`feature_key`へ更新済みだが、周辺の地の文は`way_id`のまま（「個別way_idを都度問い合わせず」「まだ一度も値を受け取っていないway」「way_id→動的値配信層」、ログのfields名`wayCount`）。実際の鍵はズームによってway単位にも区間単位にもなる。
  - failure_scenario: デバッグログの`wayCount`を見た開発者が「way数」として読み、ズーム15で区間単位に割れたぶんを「way数が急増した＝取込がおかしい」と誤診する。

- file: frontend/src/lib/adminApiProxy.ts / line: 1-2 / category: doc-drift / ファイルの数え上げが不完全 / severity: P3
  - summary: 「backendのadmin API群（`axis_admin.py`・`debug_admin.py`、**いずれも**HTTP Basic認証必須）への…プロキシ」と2本だけ列挙しているが、実際の転送先は`/admin/api/`配下10ディレクトリぶん。
  - failure_scenario: 「いずれもBasic認証必須」を2本ぶんの保証と読んだ担当者が、3本目以降のbackendルーターへ`require_admin_basic_auth`を付け忘れる。ブラウザ経由では`proxy.ts`が守るが、backendへ直接届く経路は無防備になる。

- file: frontend/src/app/page.tsx / line: 778-786、139-142、145-151 / category: doc-drift / 対象を失った／不完全になったコメント / severity: P3
  - summary: (a):778-786のキー整合自己修復の説明は直後に対応するコードが無く、本体は`buildCurrentGenerationInput`(:1512-1515)へ移った（`page-composition.md:173-176`も同じくずれている）。(b):139-142の絞り込み軸の列挙は`supplyPoi`・`tunnel`・`oneway`・ramp軸全部が漏れた不完全な数え上げ。(c):145-151は旧コメントと新コメントが2段に積まれ「保存キーは…共通」が何と何の共通なのか読めない。
  - failure_scenario: (a)送信直前の整合補正を調べる担当者が`handleGenerate`の本体を上から読んでも見つからず、`handleGenerate`内へ2本目の`syncRoutePreferenceKeys`を足す。比較キーと送信payloadが別々の値から作られるようになり、`generationRequest.ts`が防いでいた欠陥が復活する。

- file: frontend/src/app/admin/page.test.tsx / line: 41 / category: test / 手書きの一覧が新規タブを含まない / severity: P3
  - summary: `openTab`の引数型リテラルが5値のままで「較正値」を含まず、`TuningPanel`も（他の子と違い）モックされていない。タブ一覧のアサーション(:63-70)だけが6件へ更新された。

## 補足（問題が無いことを確認した点）
T918（`way_id`→`feature_key`）の消費者の取り残しはゼロ。T888は`defaultOn`・`tileMinZoom`・`staticLayerVisibility`の3点とも記述子駆動で`static-map-layers.md:66-77`・`254-262`とも一致。`/admin`配下のAPIプロキシは`proxy.ts`の`matcher`＋backend側`require_admin_basic_auth`の二重で素通しは無い。`insertByDifficulty`・`stretchCoordinateRange`・`buildSplicedShape`の配列アクセスはいずれも境界チェック付き。

---

# シャードI: frontend/src/components/Map/MapView・mapStyleOps

## overall

- file: frontend/src/components/Map/MapView.tsx / line: 1388 / 1421（`ensureAccidentTileLayer` / `ensurePoiTileSource`）と 1118（`ensureRoadSurfaceTileLayer`） / category: contract / 同種ガードの置き場所が兄弟レイヤーで違う / severity: P1
  - summary: T918で入った`hasTileVersions()`ガードが、`ensureRoadSurfaceTileLayer`では`runWhenStyleReady`の**中**、`ensureAccidentTileLayer`/`ensurePoiTileSource`では**外**に置かれており、さらに`ensureStopPoiLayer`/`ensureSupplyPoiLayer`（1431-1480）と`makeEnsureAttributeLineLayer`（1347-1380）・`makeEnsureAxisRampLayer`（1501-1530）は、ソース生成が空振りしても`addLayer`をそのまま続ける。
  - failure_scenario: `GET /api/axis-catalog`が`map`の`load`より後に解決する回、`load`時点では`hasTileVersions()`がfalseのため路面・POIのソースが作られず、直後にdesignation・tunnel・oneway・ramp軸・専用way値軸・stopPoi・supplyPoiの`addLayer`が存在しないソースを指して実行される（MapLibre 5.24の`Style.addLayer`は`_validate`でエラーイベントを出しレイヤーを追加しない）。復旧は「`rampAxes`の参照が同じレンダーで変わるので`staticOverlayLayers`が作り直され、可視状態effectが`ensure`を呼び直す」という**偶然の依存**にしか支えられていない。さらに**軸カタログの取得に失敗した場合**（`useAxisCatalog.ts:239`）は`hasTileVersions()`が永久にfalseのままで、路面・POI・事故のソースが一度も作られない。このとき`computeLayerDataStatus`は`if (!map.getSource(sourceId)) continue;`（`useLayerDataStatus.ts:45`）で何も返さないため、**チップはON・凡例も出る・状態ドットも出ないのに地図には1本も線が出ない**。唯一の告知である`RouteSettingsPanel.tsx:259`は「重み配分が反映されない」としか言っておらず、地図レイヤーが全滅することに触れていない。`static-map-layers.md:71-73`が名指ししている失敗そのものの形。

- file: frontend/src/components/Map/MapView.tsx / line: 3304 / category: structure / 自分の文書が「使えない」と書いたガードを使っている / severity: P2
  - summary: タイル世代到着時の作り直しeffectが`!map.isStyleLoaded()`で早期returnする。`mapStyleOps.ts:101-104`は「`map.isStyleLoaded()`はタイル読み込み中も一時的にfalseを返すため、それをガードに使うと二度目以降の描画が永久にスキップされることがある」と明記しており、同じ罠を新しいeffectが踏んでいる。
  - failure_scenario: `tileVersionsReady`がfalse→trueになる瞬間に基礎地図タイルの取得が1枚でも進行中だと（起動直後はほぼ常にそう）`isStyleLoaded()`はfalseを返し、このeffectは一度も本体を実行しないまま終わる（`tileVersionsReady`は二度と変化しないため再実行されない）。現状で地図が復旧しているのは`rampAxes`参照変化による別経路のおかげで、このeffect自体は目的を果たしていない。（Inference: 復旧が別経路であることはコード読解による）

- file: frontend/src/components/Map/MapView.tsx / line: 1114-1167・1387-1415・1431-1480 / category: structure / T587の「既にあれば何もしない」が4関数に残っている / severity: P3
  - summary: `ensureLayerFromSpec`（403-437）へ寄せていないensureが4本あり、いずれも早期returnで既存レイヤーへspecを再適用しない。
  - failure_scenario: いまは4本とも paint が実行時入力に依存しないため実害は出ていない。ただし`ensureRoadSurfaceTileLayer`はソース定義に`tiles: [roadSurfaceTileUrl()]`（タイル世代入りURL）を持つため、セッション中に世代が変わる形を将来入れるとURLが更新されず古い世代のタイルを配り続ける。判断原則16の対象。

- file: frontend/src/components/Map/MapView.tsx / line: 1716-1724・1541-1544・2679-2681 / category: doc-drift / 同じ保証に2つの仕組みがあり、片方の説明が現実を述べていない / severity: P3
  - summary: `underRoadSurface`の宣言が「ここで宣言しないレイヤーは**初回描画だけ**路面の上に乗り、再描画で配列順どおりの重なりへ戻る」と述べているが、T912/T913で`ensureLayerFromSpec`（412行）が**面種別なら必ず`areaLayerAnchor(map)`の直前へ差し込む**ようになったため、面レイヤーはensureの順序に関係なく基礎地図の道路網より下へ入る。`underRoadSurface`の先積みが効くのは`areaLayerAnchor`がundefinedを返すとき（劣化経路）だけになった。
  - failure_scenario: 面レイヤーを足す人がこのコメントを読み、重なり順は`underRoadSurface`が決めていると理解する。実際に決めているのは`areaLayerAnchorId`（`mapStyleOps.ts:38`）なので、面が道路を覆う不具合が出たときに効かない側を触る。あわせて`docs/tasks/T888.md:26-30`の射程「描画順の決め方を記述子へ持たせて配列から導く」はT888が`[x]`化された今も未着手のまま本文に残っている。

- file: frontend/src/components/Map/MapView.tsx / line: 2810-2814（`handleZoom`）／1809-1819 / category: perf / コメントの主張と実装が食い違う / severity: P3
  - summary: コメントは「データ取得は発生しない、単なる数値比較」と書くが、`tileZoomTooWideLayerIds`（`mapLayers.ts:541-545`）は毎回`buildMapLayers([], [])`を呼び、十数件の記述子オブジェクト（長いpanelHint文字列を含む）を丸ごと作り直してからfilter/mapする。ピンチ・ホイールの1操作で`zoom`イベントは毎フレーム飛ぶ。（Inference: 実測はしていない）

- file: frontend/src/components/Map/MapView.tsx / line: 2812 / category: structure / 初期状態でヒントが一度も計算されない / severity: P3
  - summary: 旧`updateRoadZoomHint`は`redrawAllLayers`と道路レイヤーeffectからも呼ばれていたが、`updateTileZoomHint`は`zoom`イベントからしか呼ばれない。初期ズーム（`zoom: 13`、2612行）に対する判定は一度も走らず、`lastTileZoomHintRef`の初期値`""`に依存して「案内なし」が正しいことになっている。
  - failure_scenario: 現在は宣言済み`tileMinZoom`の最大が12で成立している。`tileMinZoom: 14`のレイヤーを1つ足す、または初期ズームを下げると、利用者が一度もズーム操作をしない限りチップに案内が出ず、ONにしても何も出ない理由が画面から消える（T888段階2がまさに直した症状の再発）。

- file: scripts/review_checks.py / line: 774-780（`MAP_REDRAW_SIDE_EFFECTS`） / category: structure / 検知器の母集団に入らない副作用の形 / severity: P3
  - summary: `map_redraw_coverage`の副作用マーカーは5つで`.moveLayer(`を含まない。この期に`mapStyleOps.ts:84`（`prepareBasemapForAreaLayers`）が初めて`moveLayer`による並び替えを導入した。現状は`style.load`と`resetBasemapAreaLayerPreparation`で作り直されるため穴ではないが、今後「再描画で失われる並び替え」を`redrawAllLayers`から辿れない位置へ足しても検知器は黙る。

- file: frontend/src/components/Map/MapView.tsx / line: 1602/1609/1616/1624/1634/1640/1663/1664/1665・1692-1702・1319-1328・349-355・2251-2252・3273 / category: duplication / レイヤーidのハードコード（全件洗い出し） / severity: P3
  - summary: 軸カタログ由来でない静的レイヤーのidは、`"elevation" "hillshade" "landcover" "roadType" "roadSurface" "designation" "tunnel" "oneway" "accidents" "stopPoi" "supplyPoi"`が`buildStaticOverlayLayers`・`buildLayerDataSources`・`applyRoadMaterialTrackOffsets`／`ROAD_MATERIAL_TRACK_LAYER_IDS`の3〜4箇所へ手書きで並ぶ（`mapLayers.ts:40-70`の`MapLayerId` unionを含めると4箇所）。`hillshade`はこの期に両方へ手で足された。
  - failure_scenario: 静的レイヤーを1枚足すとき`buildLayerDataSources`への追加を忘れると、そのレイヤーだけloading/empty/errorの状態ドットが永久に出ず、タイル取得失敗が「データなし」と区別できないまま無表示になる（`buildStaticOverlayLayers`にだけ足せば地図には出てしまうので動作確認では気づけない）。T886の3件取りこぼしと同型で、T888は`show◯◯` propの側だけを閉じ、この2表は手書きのまま残っている。

## consistency

- file: frontend/src/components/Map/mapLayers.ts / line: 466-468 / category: doc-drift / 撤去済み識別子を存在理由として名指し / severity: P2
  - summary: 専用way値配信軸の記述子について「実際の用途は(1) MapLayerIdとしての存在、(2) `buildRoadSurfaceSharedLayerIds`（下記）へ含め`regionZoomTooWide`判定の対象にすることの2点」と書かれているが、どちらもT888段階2で撤去済み（本番コードに実体なし）。「（下記）」が指す関数もこのファイルに無い。
  - failure_scenario: このエントリを消してよいか判断する人が存在しない関数を探す。実際には`dedicatedAxes`は`buildStaticOverlayLayers`（MapView.tsx:1649）のレイヤー登録源でもあるのにそのことは書かれていないため、「(1)だけなら型に畳める」と誤読して記述子を消すと地図レイヤーの登録ごと消える。

- file: frontend/src/components/Map/MapView.tsx / line: 360 / 1186 / 1457 / 1571 / 1705 / 1736 / 1772 / 2012 / 2040 / 2047 / 3211 / 3245 / 3268 / category: doc-drift / コメントが名指しする識別子が実在しない / severity: P2
  - summary: 本番コードに存在しない名前を参照先として名指しするコメントが11箇所以上ある。内訳: `STATIC_OVERLAY_LAYERS`（360, 1736, 1772, 2040, 3211, 3245 — 実体は関数`buildStaticOverlayLayers`）、`STATIC_FILTER_AXES`（1186, 1457, 1772, 2047 — 実体は`buildStaticFilterAxes`）、`ROAD_SURFACE_SHARED_LAYER_IDS`（1705 — 撤去済み）、`axisInspectorPopup`（1571 — 他にヒット無し）、`axisMaterialLayerIds`（2040 — 実体は`secondaryAxisCasingLayerIds`、`page.tsx:660`）、`show{Wind,Gradient}Axis`（2012 — 両方存在しない）、`showX系フラグ群`（3245）・`showRoadSurface/showRoadTypeの組み合わせ`（3268 — T888で`staticLayerVisibility`1つに畳まれた）。
  - failure_scenario: `setStaticOverlayFilters`の絞り込み対象を変えたい人が「`STATIC_FILTER_AXES`（staticAttributeLayers.ts）のlayerIdで…」（1772）を読み、その名前でgrepしてヒットせず、実際の生成関数`buildStaticFilterAxes(rampAxes)`が**実行時カタログの公開軸ぶんを含む**という肝心の性質に気づかないまま、ビルド時静的リストを想定した変更を入れる。`docs/modules/*.md`には死んだ識別子の検知器があるが、ソースコードのコメントは（バッククォートの有無・テストcorpus汚染により）この11箇所を一度も検査していない。

- file: frontend/src/components/Map/MapView.overlayFilters.test.ts / line: 202-213 / category: test / テストの題が主張する完全性を検査していない / severity: P2
  - summary: `it("面のラスタはすべて自分で宣言しており、名指しで選ばれていない")`が、実際には`hoisted`に`"elevation"`と`"landcover"`が含まれることと`"designation"`が含まれないことしか見ていない。この期に追加された3枚目の面レイヤー`hillshade`は、テストの追加と同じコミット群で入ったにもかかわらず検査対象に入っていない。
  - failure_scenario: 面レイヤーを4枚目に足す人が`underRoadSurface: true`を書き忘れてもこのテストは通る（母集団が手書きの2件のため）。構造仕様12に真っ向から反する形で、「差が観測できるのは新しいメンバーが増えた瞬間＝検査が既に見逃した後」がそのまま当てはまる。導出可能な形（エントリに`type`を持たせ`isAreaLayerType(entry.type)`なら`underRoadSurface`がtrueであることを全件について要求する）が同じファイル群に既にある。

- file: frontend/src/components/Map/MapView.layerOps.test.ts / line: 97-99（`beforeEach`の`setTileVersions`） / category: test / 変更した経路を1件も通らない / severity: P2
  - summary: この期に3箇所へ追加された`hasTileVersions()`ガード（MapView.tsx:1118, 1388, 1421）と`tileVersionsReady` effect（3302-3306）を通るテストがfrontend全体で1件も無い。`setTileVersions`/`hasTileVersions`を参照するテストは2ファイルだけで、前者は`beforeEach`で**常に世代を入れてしまう**ため、世代が無い状態の挙動は一度も実行されない。
  - failure_scenario: 上のoverall 1件目は、テストを1件足せば`addLayer`呼び出しの有無として観測できるのに、いまはどのテストからも見えない。

- file: docs/modules/frontend/static-map-layers.md / line: 114-115 / category: doc-drift / 関数シグネチャが実装より1引数少ない / severity: P3
  - summary: `buildStaticOverlayLayers(axisOverlayLayers, dedicatedAxes, dedicatedWayValueDisplays?, dedicatedWayValueLoading?)`と書かれているが、T920で第5引数`dedicatedWayValueHiddenBands`（MapView.tsx:1597）が追加されている。
  - failure_scenario: レンズ凡例の段階絞り込みがどこから入るかを追う人が`dedicatedWayValueHiddenBands`の流路を見落とし、「filterで絞れないので色を透明にする」というT920の設計判断（MapView.tsx:1186-1188）に気づかないままfilter側へ実装を足す。

- file: docs/modules/frontend/static-map-layers.md / line: 353 / category: doc-drift / ソースidが実装と違う / severity: P3
  - summary: 表は事故レイヤーのソースを`region-accident-tiles`と書くが、実装は`ACCIDENT_TILE_SOURCE_ID = "region-accidents"`（MapView.tsx:330）。
  - failure_scenario: タイル取得失敗を調べる人が`region-accident-tiles`でネットワークログ・`erroredSourceIds`をgrepして1件も当たらず、「事故レイヤーはソースイベントの追跡対象外なのだ」と誤って結論する。

- file: docs/modules/frontend/static-map-layers.md / line: 79-108・32 / category: doc-drift / この期に入った前提が1行も書かれていない / severity: P2
  - summary: 「タイル世代が届くまで路面・POI・事故のソースを作らない」（`hasTileVersions()`）という、レイヤーがいつ現れるかを決める前提がfrontend側のモジュール文書に無い。対象ファイル表は`regionApi.ts`を「タイル世代**定数**」と書いており現在の形と食い違う（backend側の`static-road-attributes.md:397-400`にだけ記述がある）。
  - failure_scenario: 「ONにしたのに地図に何も出ない」を調べる人が「暗黙の前提」節を読んでもタイル世代ゲートに辿り着かず、`tileMinZoom`・`road_edges`未構築・`baseFilter`の3つを順に潰してから最後にネットワークタブで気づく。

- file: frontend/src/components/Map/MapView.tsx / line: 522 / category: contract / 出典表示が実際に表示しているデータと違う / severity: P3
  - summary: 起伏（陰影）のDEMソースが、色別標高図用の帰属文字列`'地理院タイル(色別標高図)'`（202-203行）をそのまま使っている。
  - failure_scenario: 「起伏」だけをONにして「標高図」をOFFにしている利用者の地図で、ⓘの帰属表示に「地理院タイル(色別標高図)」とだけ出る。表示しているのは標高タイル（DEM）を`terrain_rgb.py`が変換したもの。

- file: frontend/src/components/Map/MapView.dataStatus.test.ts / line: 11-12 / category: doc-drift / 撤去済み定数を名指しする経緯コメント / severity: P3
  - summary: 「以前のLAYER_DATA_SOURCES/ROAD_SURFACE_SHARED_LAYER_IDS定数と同じ内容。」というコメントが残っているが、`ROAD_SURFACE_SHARED_LAYER_IDS`を組み立てていた行はこの期のdiffで削除された。`docs/comments.md`が禁じる経緯記述でもある（`source_narrative`は追加行のみを見るため残存分は検出されない）。

- file: frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx / line: 259-267 / category: contract / 文言が述べる影響範囲と実装が起こす影響の食い違い / severity: P2
  - summary: 軸カタログ取得失敗時の唯一の告知が「重み配分は反映されず、サーバー既定の配分で探索します」だけだが、T918のタイル世代ゲート以降、同じ失敗は**地図の路面・道路種別・指定路線・トンネル・一方通行・ramp軸・専用way値軸・POI・事故のすべてを地図から消す**副作用も持つようになった。
  - failure_scenario: カタログ取得が失敗した状態で地図を開いた利用者は、ルート設定パネルの注意書きを読んでも地図が真っ新な理由に結び付けられず、チップをON/OFFしても何も変わらないまま「この地域はデータが無い」と受け取る。状態ドットも出ないため失敗していること自体が地図側からは一切見えない。

## 補足（観測）
`mapStyleOps.ts`とその新規テスト（`mapStyleOps.test.ts`、実物の111レイヤーをフィクスチャに置き「差し込み位置を並び順ではなくスキーマの語彙から導く」ことを5件で固定）は、この期の変更の中でもっとも導出が徹底している部分で、`areaLayerAnchorId`の反例2通りが両方テストとして残っている点も含めてKEEP相当。

---

# シャードJ: 地図カタログ・レイヤー定義（mapLayers・staticAttributeLayers・valueScale ほか）

## overall

- file: frontend/src/components/Map/mapLayers.ts / line: 462-478 / category: dead / 撤去済み機構の残骸 / severity: P2
  - summary: 専用way値配信軸の`MapLayerDescriptor`は、T888で`buildRoadSurfaceSharedLayerIds`が消えた結果、本番コードに消費者が1つも無くなっている（生成直後に全消費点で捨てられる）。
  - failure_scenario: `buildMapLayers`の本番呼び出しは`page.tsx:1031`の1箇所だけで、その結果は`page.tsx:1203`で`.filter((layer) => !isAxisStudioLayer(layer))`により無条件に除外する。残る2つの内部呼び出しはどちらも`buildMapLayers([], [])`と軸を空で呼ぶ。コメント（:466-468）が挙げる2つの用途のうち(2)は関数ごと撤去済み、(1)「MapLayerIdとしての存在」は型`DedicatedWayValueMapLayerId`が満たしている。現状これらを読むのは`mapLayers.test.ts:16-22, 126-130`だけで、**テストが「存在して除外されること」を固定しているため本番で効いていない事実が検知されない**。3件目の専用配信軸を公開した開発者は、この記述子に`label`/`panelHint`を埋める作業（:469-478）を本番の表示に効くものと誤解する。

- file: frontend/src/components/Map/routeStyleModes.ts / line: 86-91 / category: duplication / 同じ表記規則の3実装 / severity: P2
  - summary: 「段階の数値レンジ文字列」を作る関数が`routeStyleModes.ts: rangeLabel`・`mapColorLegend.ts: rangeStepLabel`(:51)・`axisLayers.ts: axisRampBandLabel`(:488)の3箇所に別実装で存在し、1つだけ最上位帯の語が違う。
  - failure_scenario: `mapColorLegend.ts:48-50`は「`axisRampBandLabel`と同じ表記規則（未満/以上/〜）を共有する」と明記しているが、共有しているのは規則の文章だけでコードは別々。実際に`routeStyleModes.ts:89`だけが`超`を使っており（他2つは`以上`）、同じ軸の同じ境界値が画面の場所によって別の表記で出る。

- file: frontend/src/components/Map/precipitationNowcast.ts / line: 162-208 / category: structure / 手で列挙した一覧（構造仕様12） / severity: P3
  - summary: `PRECIPITATION_INTENSITY_LEVELS`が`PRECIPITATION_COLOR_STOPS[0]`〜`[8]`を手書きで添字参照する9件のliteral配列のまま残っており、同じ期間に`windLayer.ts`側だけが`.map()`による導出へ移された（非対称）。
  - failure_scenario: 段を1つ足すと地図はその帯を塗るのに凡例は8帯のままになる。逆に1つ減らすと`PRECIPITATION_COLOR_STOPS[8].mmPerHour`がモジュール読み込み時に`TypeError`となり、`page.tsx`がimportしているためページ全体が起動しない。件数一致テストがこの取り残しを検知するが、**「手書き一覧の更新漏れを検出する検査が必要になっていること自体が、その一覧を導出にできる証拠」**（構造仕様12）。

- file: frontend/src/components/Map/windLayer.ts / line: 127-146 / category: structure / 平行する手書き一覧 / severity: P2
  - summary: `WIND_BAND_NAMES`（9件）が`WIND_SPEED_COLOR_STOPS`（9件）と件数一致を要求する平行配列なのに、その一致を担保するものが無い。
  - failure_scenario: 色の段を1つ足して`WIND_BAND_NAMES`を足し忘れると`WIND_BAND_NAMES[index]`が`undefined`になり、風チップの凡例に**「undefined（24.4〜30m/s）」**という行がそのまま表示される。既存テストは素通しする——`windLayer.test.ts:168`は件数と色しか比べず、:173-177のラベル検証は`toContain`で数値レンジ部分だけを見るため先頭の体感表現が`undefined`でも通る。

- file: frontend/src/components/Map/icons.tsx / line: 670-672, 778-779 / category: dead / 未使用エクスポート（前回レビュー指摘の未解消） / severity: P3
  - summary: `RouteEditIcon`・`SaveIcon`はリポジトリ全体から1箇所も参照されていない。2026-09-13のレビュー（`history/2026-09-13_all_shards.md:339`）が同じ箇所の説明コメントをP3として指摘済みだが、コメントも参照も残ったまま。

- file: frontend/src/components/Map/dedicatedWayValueLayer.ts / line: 27-28 / category: dead / 使われていない再エクスポート / severity: P3
  - summary: `TileXY`・`tilesCoveringViewport`・`mergeDynamicWayValues`をこのファイル経由で読む消費者が本番にもテストにも無い。実消費者は`./dynamicWayValues`から直接importしている。この再エクスポートがあるためファイル冒頭（:10-11）が宣言する責務分離の輪郭がぼける。

- file: frontend/src/components/Map/routeStyleModes.ts / line: 49 / category: dead / severity: P3
  - summary: `export { COLOR_NO_DATA };`の再エクスポートを読む消費者が無い。

- file: frontend/src/components/Map/valueScale.ts / line: 16 / category: duplication / 同じ灰色の手書き複製 / severity: P3
  - summary: 「値が無い」を示す`#9ca3af`が`Map/`配下の本番コードに5箇所、手書きで独立して存在する（`valueScale.ts:16 COLOR_NO_DATA`・`axisLayers.ts:396 COLOR_UNKNOWN`・`windLayer.ts:140`〔定数名すら無いインラインの直書き〕・`staticAttributeLayers.ts:254 ACCIDENT_SEVERITY_COLOR_OTHER`・`MapView.tsx:378 ROAD_LINE_NEUTRAL_COLOR`）。関係が文書化されているのは1組だけ。
  - failure_scenario: 「データなし」の灰色を見分けやすい色へ変えようとすると、レンズの凡例だけが変わり、同じ画面のramp軸の「不明」と風の「無風」は旧色のまま残る——同じ意味の灰色が2色並ぶ。`context.md`の「フロントの語彙・色・凡例は宣言的カタログに集約する」に反する。

## consistency

- file: frontend/src/components/Map/routeStyleModes.ts / line: 89 / category: contract / ラベルが実装の判定と逆・ルート前後で不一致 / severity: P2
  - summary: 最上位段階のラベルを`〜超`（境界値を含まない）と書いているが、同じ関数が作る凡例フィルタは`>=`（境界値を含む、:73）で、さらにルート確定前の同じ軸の凡例は`〜以上`と表記する。
  - failure_scenario: レンズ「勾配」を選ぶ。ルート生成**前**はLensControlの凡例が`mapColorLegend.ts:53 rangeStepLabel`由来で最上段が「10%以上」。生成**後**は同じレンズの凡例が`routeStyleModes`由来に切り替わり同じ段が「10%超」になる（`page.tsx:1436-1449`が`hasDetail`で切り替える）。しかも述語は`[">=", value, boundaries[i-1]]`なので、**ちょうど10.0%の区間はこの段に入りながら「10%超」と書かれた行で数えられる**。テストが食い違いを両側から固定している（`dedicatedWayValueLayer.test.ts:102`が`"5%以上"`、`routeStyleModes.test.ts:132`が同じ境界で`"5%超"`）。`routeStyleModes.test.ts:265`「体感ラベルを持つ軸の凡例は…**ルート前と同じ表記になる**」は先頭帯（両者が必ず一致する唯一の帯）しか比べていないため空回りしている。

- file: frontend/src/components/Map/mapColorLegend.ts / line: 21-26 / category: contract / 段階キーの名前空間が2系統あるのに保存先が1つ / severity: P1
  - summary: 段階の非表示キーが、ramp軸では`${axisId}-${index}`（`axisLayers.ts:526`）、レンズのルート線・専用way値配信軸では`step-${index}`（`legendBandKey`）と別系統なのに、保存先は`page.tsx: hiddenLegendKeysByMode[軸id]`の同じ1配列である。
  - failure_scenario: レンズを「車の圧迫感」（ramp軸）にし、**ルート生成前**に凡例で最上段のチェックを外す（キーは`car_stress-3`）。ルートを生成すると`lensLegend`が`routeStyleModes`側（キー`step-N`）へ切り替わるため、(a)**隠したはずの段が黙って復活し**、(b)`hiddenRouteLegendKeys`には`car_stress-3`が残るので`page.tsx:1087`の`hiddenRouteLegendKeys.length > 0`が真になり、ルートチップに**「レンズ: 車の圧迫感の影響・一部非表示」**と出続ける。凡例のチェックはすべて入っているので、利用者は「どこが非表示なのか」を探して見つけられない。`legendFilter.ts:22-23`が定める「未知のキーは無視する」規約を、この1箇所だけが破っている。`docs/modules/frontend/map-axis-coloring.md`も自己矛盾（:183-184は「ramp軸はキーが別になる」と書きながら、:189の表ではramp軸のルート確定後を「同上（`hiddenRouteLegendKeys`）」＝引き継がれる、と読める形で並べている）。

- file: frontend/src/components/Map/mapLayers.ts / line: 26-28 / category: doc-drift / 生成物の現在値と食い違う根拠づけ / severity: P2
  - summary: 「自転車インフラ`bicycle_infra_quality`は地図レイヤーを持たない[`show_map_icon=false`]」と3ファイルが書いているが、生成物`axis-catalog.json`では`show_map_icon=true`かつ`display.kind="ramp"`で、地図レイヤー`axis:bicycle_infra_quality`は生成されている。同じ誤記が`staticAttributeLayers.ts:3-6`・`primaryAttributes.ts:62-63`にもある。
  - failure_scenario: 「自転車インフラが地図チップに出ない」を調べる開発者がこのコメントに従って`show_map_icon`を疑い、trueであることを確認して「カタログが壊れている」と結論する——実際の理由は`mapLayers.ts:135 isAxisStudioLayer`が**ramp軸を一律でチップから外している**（T414以降の別の決定）ことで、`show_map_icon`とは無関係。

- file: frontend/src/components/Map/mapLayers.ts / line: 345-349 / category: doc-drift / 画面に出る説明文が実際の凡例より少ない種別しか名乗らない / severity: P2
  - summary: 停止要因レイヤーの`description`（チップのtitle）と`panelHint`が「信号・横断歩道・一時停止・踏切」の4種しか挙げていないが、凡例（`staticAttributeLayers.ts:271-279 STOP_POI_CATEGORIES`）は7種を出す（＋徐行・車止め/ゲート・ハンプ/狭さく）。
  - failure_scenario: 利用者が▶パネルを開くと、チップの説明に出てこない3種の行が並ぶ。逆に「車止めのある道を避けたい」利用者はチップの説明文だけを読んで「このレイヤーには車止めは含まれない」と判断しONにしない。`docs/documentation.md`の数え上げ禁止に該当し、実際に既に嘘になっている。

- file: frontend/src/components/Map/mapLayers.ts / line: 466-468 / category: doc-drift / 撤去済みシンボルを名指し / severity: P2
  - summary: 「`buildRoadSurfaceSharedLayerIds`（下記）へ含め、`regionZoomTooWide`判定の対象にする」——どちらもT888で撤去済み。「下記」と書かれた先に関数が無い。現在の仕組みは`tileMinZoom`宣言＋`tileZoomTooWideLayerIds`（:541）で、しかも**専用way値配信軸の記述子は`tileMinZoom`を宣言していない**うえ`tileZoomTooWideLayerIds`は`buildMapLayers([], [])`と軸を空で呼ぶため、このコメントが述べる内容は二重に成立していない。

- file: frontend/src/components/Map/mapLayers.ts / line: 558 / category: doc-drift / 存在しない識別子・成立しない限定 / severity: P2
  - summary: 「『ズーム範囲外』（road専用の`zoomWarning`）」——`zoomWarning`はリポジトリ全体でこのコメント1件しか存在せず、「road専用」も成立しない（`tileMinZoom`は`landcover`・`stopPoi`・`supplyPoi`にも付いている）。

- file: frontend/src/components/Map/mapLayers.ts / line: 390（および page.tsx:961） / category: doc-drift / 存在しない定数を現行の仕組みとして名指し / severity: P2
  - summary: `STATIC_FILTER_AXES`の名指しは本番コードに8箇所（`staticAttributeLayers.ts:18,328`・`mapLayers.ts:390`・`MapView.tsx:1186,1457,1772,2047`・`page.tsx:961`）。実在するのは関数`buildStaticFilterAxes`と、`MapView.overlayFilters.test.ts:22`・`staticAttributeLayers.test.ts:40`のテストローカル定数だけ。**テスト側が意図的に旧名で束ねているため、grepすると「本番にも定数がある」と誤認しやすい**。一掃するときはテストローカル定数を母集団に入れないこと。

- file: frontend/src/components/Map/staticAttributeLayers.ts / line: 1-13, 85-86 / category: doc-drift / このファイルに無いものを責務として宣言 / severity: P3
  - summary: ファイル冒頭が「静的道路属性（**車ストレス**）…の色分け定義」と名乗り、:12-13が「車ストレスは既存の「路面」レイヤーと同じソースの独立レイヤー」と現在形で述べ、:85-86が`buildCategoricalLayerDefs`の対象外の例として`CAR_STRESS`を挙げるが、車ストレスの色分けはこのファイルから撤去済みで汎用ramp機構へ一本化されている（テスト側`staticAttributeLayers.test.ts:33-35`は正しく記録している）。

- file: frontend/src/components/Map/windLayer.ts / line: 68-70 / category: doc-drift / backend側の存在しないファイル・定数を根拠にする / severity: P3
  - summary: 「バックエンド側のstale fallback＝`weather_client.py`の`STALE_FALLBACK_MAX_AGE_SECONDS`と同じ考え方」——どちらも存在しない（T645でOpen-Meteo依存を撤去した際の残骸と推測）。実際にはbackendに対応する上限が無いため、フロントは**無期限に古い格子点を残し続ける**。

- file: frontend/src/components/Map/mapLayers.ts / line: 18-25, 176-181 / category: doc-drift / 型より短いカテゴリの数え上げ / severity: P3
  - summary: ファイル冒頭のカテゴリ説明が4つしか列挙せず、`MapLayerDescriptor.category`のJSDoc(:178)も`weather`までで`disaster`を落としている。実際の`MapLayerCategory`(:82)と`MAP_LAYER_CATEGORY_ORDER`(:86-93)は6つ。

- file: frontend/src/components/Map/routeStyleModes.ts / line: 218-232 / category: contract / 戻り型と自身のログが矛盾 / severity: P3
  - summary: `getRouteStyleMode`は`: RouteStyleMode`（非nullable）を返すと宣言しながら、フォールバックで`modes[0]`を無検査で返す。直前のログは`modes[0]?.id ?? "(no modes)"`と**空配列でありうることを自認している**。現状`routeStyleModesFromCatalogAxes`が必ず2モードを足すため到達しないが、「今は空にならないから」だけを根拠に型の嘘を残している（判断原則16）。

- file: frontend/src/components/Map/mapColorLegend.ts / line: 51-55, 72-78 / category: contract / `[0]`相当の無条件アクセスで`null`が文字列化する / severity: P3
  - summary: `buildRangeLegendBands`に空の`boundaries`を渡すと`lower`も`upper`も`null`になり、`rangeStepLabel`の第1分岐がそのまま`${upper}`を展開して**`"null%未満"`**というラベルを返す。同じ入力で`routeStyleModes.ts:87`は`""`を返すため、ルート前後で壊れ方まで違う。（推測: 空配列がaxis_admin APIで受理されるかは未確認）

- file: frontend/src/components/Map/primaryAttributes.ts / line: 57-65 / category: doc-drift / 定数の中身と列挙が一致しない / severity: P3
  - summary: 「表示レイヤーを意図的に持たない一次属性」の列挙に`motor_vehicle_access`が抜けている（`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`には入っている）。この`Set`は「未対応（漏れ）」と「意図的にレイヤー無し」を区別するためにあり、コメントが分類の根拠そのもの。

- file: frontend/src/components/Map/primaryAttributes.test.ts / line: 18-26 / category: test / ドリフト検知が片方向しか見ていない / severity: P3
  - summary: 「両方に無い／両方にある」は検知するが、**どちらの対応表にも古い`attr_id`が残っている**ケースを検知しない（ループが`PRIMARY_ATTRIBUTES`側しか回らない）。加えて`MapLayerId`のunionが`` `axis:${string}` ``を含むため、存在しないレイヤーidを書いても綴り次第でtscが通る——「対応表のレイヤーidが`buildMapLayers`の結果に実在するか」の検査も無い。

- file: docs/modules/frontend/static-map-layers.md / line: 114-115 / category: doc-drift / 関数シグネチャが1引数古い / severity: P3
  - summary: （シャードIと重複。統合時に1件へ寄せる）

- file: docs/modules/frontend/static-map-layers.md / line: 311-313（および dynamic-weather-layers.md:169） / category: doc-drift / 要素数の数え上げ / severity: P3
  - summary: 「`useDynamicWeatherLayers`が非表示キーを見て**7要素**の`visible`を決める」と件数を書いている。災害チップへ8つ目を足した瞬間に両方の文が嘘になる。

- file: frontend/src/components/Map/valueScale.ts / line: 46-49 / category: doc-drift / 既定値が実際には使われない（T921未完了に由来） / severity: P3
  - summary: `SIGNED_MATERIAL_BOUNDARIES`（13境界・14段階、「上り側は1%刻み」）は、唯一の`signed_material`軸である`gradient`が`display_thresholds_override: [-2, 2, 6, 10]`を持つため実環境では到達しない。`docs/tasks/T921.md`が「状態: 未完了（コード側は実装済み、残りは軸スタジオ経由のDB反映）」と明記している既知の未完了だが、コード側のコメントは既定値が現に効いているかのように書かれている。（本番DBの現在値はレビューからは確認できないため推測を含む）

---

# シャードP: 計画↔実装（トリガー棚卸し・未起票フォローアップ・architecture.md追従）

## A: トリガー棚卸し（全22件）

指定21件に加え、`docs/improvement-plan.md:1304` の **T826** がリストから漏れていたため22件で実施。

| タスク | 分類 | 根拠（実測値・grep結果） |
|---|---|---|
| **T127** 全国データ取込 | 未発火／**記述を是正** | 全国展開の意思決定なし。ただし本文の容量試算（2026-09-04、DB全体5,030MB→全国25.4GB）は、その後**14本のmigration**（0031〜0044）が適用されて陳腐化。特に`way_landcover`(0032)・`way_geometry`(0036)・`edge_landcover`(0044)。**本文自身が「2026-08-18時点の試算は陳腐化していた」と1度書き直しており、同じ陳腐化が2巡目** |
| **T206** 積雪・凍結 | 未発火 | 今日2026-09-19。トリガー「毎年11月」まで約6週間。**次回レビューが11月にかかる回で発火する** |
| **T207** 雷CAPE | 未発火 | T204だけでは不足という利用実績・要望の記録なし。前提変更（T645）は本文へ反映済み |
| **T208** 視程・霧 | 未発火 | 山間部・河川霧での利用報告なし。前提変更（T645）は本文へ反映済み |
| **T273** 軸カタログ縮退 | 未発火 | 「一般公開」の意思決定行はT273自身のトリガー記述のみ（grep 1件） |
| **T287** text型PK再評価 | 未発火 | T127に従属 |
| **T288** AXIS_DEFINITIONS マルチワーカー | 未発火 | `.github/workflows/deploy-backend.yml:126`が「uvicorn(`--workers`未指定の単一…」と明記。複数メンバー参加の記録もなし |
| **T307** プリセットのマスタ化 | 未発火（本文は最新） | `grep -rn "PRESETS" frontend/src` = **0件**（撤去済みが本文へ反映済み） |
| **T388** job_registry マルチワーカー | 未発火 | T288と同根拠 |
| **T389** MSM GRIB2パーサー | **別タスクで実質解決→射程の是正/クローズ提案** | 本文が起点とする`parse_grib2_stub`・`jma_msm_service.py`・grib関連コードは**grep 0件で全て消滅**。`infrastructure/msm_client.py`がAWS Open Data経由の前処理済みMSMをローカル同期し**MSMを本番で既に使用中**（T645）。本文の「本タスク完了までは検証不能」「MSMが理論上唯一のJMA候補」は**もはや成立しない** |
| **T422** 環境グループのプレースホルダー | 未発火（記述是正済み） | T897が排他ドメイン消滅を反映し残る欠陥をT899へ分離済み |
| **T479** クールダウン付きトリガー共通化 | 未発火 | 同型は**2箇所のまま**（`region_service.py:83 _maybe_trigger_graph_build`・`graph_service.py:99 _maybe_warm_tile_cache`）。`elevation_client.py`のin-flight重複排除はクールダウンTTLを持たず同型ではない |
| **T480** 動的材料クリックガード汎用化 | 未発火 | `axis_definitions_snapshot.json`の`dedicated_way_value_layer=true`は**2件**（`gradient`・`wind`）／全13軸・公開8軸。3件目は未到達 |
| **T526** 内訳バーの視覚表現 | 未発火（前提は維持） | 公開軸は8本のままで「各0.125配分で約12.5%」という前提は成立。実機報告なし |
| **T542** slmcs系の地図表示 | 未発火（**検証不能**） | 線状降水帯発生時の実データ取得記録なし。トリガーが外部事象依存で自力検証できない唯一の項目 |
| **T582** 本番VMのネットワーク許可 | 未発火 | 「本格公開」の意思決定行はT582自身のみ。OCI/iptablesの現状はworktreeからは確認不能 |
| **T629** ボタン系CSS共有化 | **前提が消滅→発火不能** | トリガーが名指しする`MapLayersPanel`は**`git ls-files` 0件**（`dc19b737` T769、2026-09-12に削除）。さらに`docs/modules/frontend/page-composition.md:195`は下部区分を「**2区分**」と記しており、T629本文の「3つ目の下部区分」も成立しない。**このトリガーは永久に発火しない** |
| **T636** JMAタイルのbase64包装除去 | 未発火 | T632/T633完了後にbackend CPUを測った記録なし |
| **T640** 点タイル配信の汎用化 | 未発火／**記述を是正** | 点レイヤーのエンドポイントは`poi-tiles`・`accident-tiles`の2本のまま。T934・T935は既存レイヤーの中身を変えただけで新レイヤーの追加ではない。**ただし本文43行目の「タイル世代（`ACCIDENT_TILE_VERSION`・`POI_TILE_VERSION`）はレイヤーごとに独立して持てる形を維持する」は、T848がこの2定数を撤去したため成立しない** |
| **T714** 長時間トランザクションの観測 | 未発火／**記述を是正** | 本番で`idle in transaction`起因の障害が観測された記録なし。ただし(a)対応方針の前半「まず観測を足す」は**T840（2026-09-14完了）が`/admin`「鮮度」タブへ`longest_idle_transaction_seconds`を追加して実質達成済み**。(b)本文が挙げる対象は2バッチだが、T919が新設した`precompute_edge_landcover.py:174`も`stream_id_chunks`を使う**3本目**で、本番で488,901way規模のバックフィルを実走している——**観測の機会があったのに誰も見ていない**。(c)行番号`_common.py:116-133`は現在別の関数を指す |
| **T715** 数値入力プリミティブ共有化 | 未発火／**記述を是正** | 解き方は2箇所のまま（`AxisFormFields.tsx:60 NumberField`／`RideConditionBar.tsx:66,162 speedDraft`＋`onBlur`）。**ただし本文の`AxisComposer.tsx:112-189`は現在まったく別のコード**で、`NumberField`/`SliderNumberField`は`AxisStudio/AxisFormFields.tsx`へ移設済み |
| **T826**（リスト漏れ）経緯コメント一掃 | 未発火 | `git log 05c96456..0d0c6251 -- axisLayers.ts secondaryAxes.ts` = **0コミット・0行変更**。対応方針1（T567への注記）はT898で実施済み |

### A節の総括

- **発火したもの: 0件**。
- **是正が必要なもの: 6件** — T629（前提消滅・発火不能）／T389（別タスクで実質解決）／T640・T714・T715・T127（本文が名指しする識別子・行番号・数値が実装とずれた）。
- **トリガー待ち中にタスク本文が腐る速度が上がっている**。前回レビュー以降の49タスクのうちT848・T769・T645・T840・T919の5つが、トリガー付きタスク6件の前提を静かに無効化した。T897（T422の前提消滅を是正）と同じ型が今回は5件同時に出ている。

## B: 未起票フォローアップ

`[x]`化された49タスク全件を「未起票／別タスク／スコープ外／後続／残作業／積み残／持ち越／未決／先送り／あとで／手付かず」で機械検索。ヒットは3件（T897:13・T904:18・T933:58）で、いずれも起票済みリンクありかその場で解消済み。

段階構成のタスクを本文まで読んで1件の取りこぼしを発見:

- file: docs/tasks/T888.md / line: 33-38 / category: structure / severity: P2
  - summary: T888が射程として明示した2項目のうち「描画順（重なり順）の決め方を`MapLayerDescriptor`へ持たせる」が未実施のままT888が`[x]`化され、後続タスクも起票されていない（もう1つの「最小ズームの宣言」は段階2で実施済み）。実装は今も`MapView.tsx:1544,1606,1613,1620`の`OverlayLayerEntry.underRoadSurface`を**レイヤーごとに手で書く**形で、`mapLayers.ts`の`MapLayerDescriptor`には移っていない。`grep -rn "underRoadSurface|描画順|重なり順" docs/improvement-plan.md`の結果はT912の完了記述のみで、独立した`- [ ]`行は存在しない。
  - failure_scenario: T888本文は「どちらも記述子へ持たせて配列から導けば、propの削減と同じ1つの是正で閉じる」と書いた上で`[x]`になっている → 次に面レイヤーを足す人はT888を読んで「静的レイヤー追加は1箇所で済む」と理解するが、実際には`underRoadSurface`の書き忘れが残っている。書き忘れると**チップはONになり凡例も出るのに、面が道路の上に積まれて道路が読めなくなる**（T913が実機で観測した症状そのもの）。`/task:next`は`- [ ]`行しか見ないため、この項目は次に誰かがT888を通読するまで拾われない。

## C: architecture.md の追従

前回レビュー以降の49タスクのうち新設を伴うもの（`git diff --diff-filter=A`実測）: 新設backendファイル9本（`gsi_tile.py`・`tuning_admin.py`・`_landcover.py`・`precompute_edge_landcover.py`・`domain/terrain_rgb.py`・`domain/tuning.py`・`infrastructure/tuning_overrides.py`・`terrain_tile_service.py`・`tile_version_service.py`）、新設テーブル2つ（`tuning_overrides`／`edge_landcover`）、新設フロント11ファイル。

**追従できているもの**: T914/T916（起伏・Terrain-RGB・hillshade `igor`）は`docs/architecture.md:172`に反映済み。T572/T605（GSIタイル）もline 26・166-172・203に反映済み。

### C-1（最大の穴・セクション自体が存在しない）

- file: docs/architecture.md / line: —（該当セクションなし。§4 APIは492-806、§6データモデルは844-947） / category: doc-drift / severity: **P1**
  - summary: T805（規模M〜L）が新設した較正値の仕組みが、architecture.mdに**1文字も存在しない**。`grep -c`実測: `tuning_overrides` 0件・`domain/tuning` 0件・`較正値` **0件**・`tuning_admin` 0件・`TuningPanel` 0件。実装側は`migrations/0043_add_tuning_overrides.sql`（新テーブル）・`GET`/`PUT /api/admin/tuning[/{param_id}]`・`/admin`の6タブ目`value="tuning"`が本番に入っている。`docs/modules/backend/cross-cutting-infrastructure.md`等5ファイルには記載があり、**architecture.mdだけが取り残されている**。
  - failure_scenario: §4「現状」のAPI一覧には`POST /api/admin/basemap/refresh`しか管理APIが載っておらず（793行）、§6データモデルにも`tuning_overrides`が無い → 新規参加者・将来の自分が「ルーティングの停止コスト・ターン費用はコードの定数」と読み、**再デプロイなしでDBから変えられる仕組みがあることに気づかないまま定数を直接書き換える**。書き換えてもDB上書きが優先されて反映されず、原因が分からない。CLAUDE.mdの「規模M以上でAPI・ドメイン概念・レイヤー種を新設するタスクは完了条件へarchitecture.md追従を既定で含める」に対する明確な違反で、T805本文にもarchitecture.mdへの言及が0件。

### C-2

- file: docs/architecture.md / line: 1836-1858（「派生データの系譜追跡」節） / category: doc-drift / severity: P2
  - summary: T919が新設した`edge_landcover`（本番バックフィル済み）が、派生データの系譜追跡の記述から漏れている。この節は`source_osm_import_run_id`と`algorithm_version`を持つテーブルを列挙しており、`edge_landcover`は両方の列を持つのに`way_landcover`だけが列挙されている。`grep -c edge_landcover docs/architecture.md` = **0件**。
  - failure_scenario: 生データ再取込後に「どの派生テーブルを作り直すか」をarchitecture.mdの列挙から判断すると`edge_landcover`が抜け落ち、**区間単位の土地被覆だけが古いOSM世代のまま残る**。way単位は更新されるため、同じ材料なのに2つの粒度で値が食い違い、区間インスペクタと地図で違う数字が出る。

### C-3

- file: docs/architecture.md / line: 180 / category: dead / severity: P2
  - summary: T848が撤去した定数`ROAD_SURFACE_TILE_VERSION`を、路面タイルのディスクキャッシュパスとして現在形で名指ししている。実装は`region_service.py:102`で`v{ROAD_SURFACE_TILE_SHAPE}`。あわせてT848が新設した`services/tile_version_service.py`はarchitecture.mdに**0件**。
  - failure_scenario: **この死んだ参照は検知器をすり抜けている**。`undeclared_dead_refs`は0件と報告するが、`DOC_IDENT_RE`がバッククォート単位でしかマッチせず、パス文字列に埋め込まれた識別子を抽出しない（実測: 当該行から`DOC_IDENT_RE.findall`の結果は**空リスト**）。同じ形の埋め込みは今後も検知されない。

### C-4

- file: docs/architecture.md / line: 1929-1938（`GET /api/region/poi-tiles`の説明） / category: doc-drift / severity: P2
  - summary: T934・T935が変えた点の単位が反映されていない。architecture.mdは「`osm_raw_pois`の点データを`kind`プロパティ付きで焼き込む」「SQL自体は無改修、`kind`を無条件で焼き込む設計」と述べるが、実装`road_graph_repository.py:752-795`は**停止要因を`ST_ClusterDBSCAN`でまとめ`ST_Centroid`を1点として出す**（T934、z14で1,654点→837点）。補給POIのkindも`vending_drinks`／`vending_unknown`の2種へ分割されたのに、1932行は今も「コンビニ・自販機・トイレ・給水・駐輪場」と旧kind構成を列挙している。
  - failure_scenario: 「SQLは無条件に焼くだけ」を信じて`kind`を1つ足す人が、クラスタリング側の分岐を触らずに済むと判断する → **新しい種別が意図せず近傍の別種別と重心へ統合される**、または逆に停止要因なのにまとめられない。どちらもタイルを見るまで気づけない。

### C-5（同根、軽微）

- file: backend/app/batch/precompute_way_attribute_counts.py（:18, :46）、precompute_edge_attribute_counts.py（:43）、precompute_way_divided_carriageway.py（:13）、infrastructure/tile_persistent_cache.py（:25） / category: dead / severity: P3
  - summary: T848が撤去した`ROAD_SURFACE_TILE_VERSION`を、バッチのdocstringが**運用手順として現在形で指示**している。同じ死んだ名前は`docs/caching.md:270`（無効化方針の代表例）と`docs/documentation.md:68`（「よい書き方」の見本）にも現在形で残る。
  - failure_scenario: バッチを実行した運用者がdocstringどおり`region_service.py`を開いて対上げする定数を探し、見つからない → 作業を止めるか、新しい自動組み立ての存在に気づかないまま手動でキャッシュを消しに行く。方針文書が実在しない定数を模範例として提示している状態。

### C-6（軽微）

- file: docs/architecture.md / line: 800-803 / category: doc-drift / severity: P3
  - summary: §4のAPI一覧末尾は標高オーバーレイとして`GET /api/gsi-relief-tile/{path:path}`のみを挙げるが、T914が新設した`GET /api/gsi-terrain-tile/{z}/{x}/{y}.png`が§4に無い（§3の172行には記載あり）。

### C節の総括

追従漏れは「気づきにくさ」で二極化している。T914/T916のように*既存セクションの中身を書き換える*変更は確実に追従されている一方、**T805のように*新しいセクションを起こす必要がある*変更は丸ごと落ちている**（P1）。これは「更新されているが古い」ではなく「対応するセクション自体が存在しない」型で、2026-08-16に静的道路属性P0/P1で起きた見落としと同じ形。
