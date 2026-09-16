# 統合レビュー（2026-09-16）シャード別の生出力

対象コミット `05c96456`、ベースライン `4a2cb02a`（2026-09-15 統合レビュー第9回）。

これは統合前の一次出力である（重複・矛盾・誤りを含みうる）。統合後のFindingsと、どの項目を
どう採用/棄却したかは [2026-09-16_all.md](2026-09-16_all.md) にある。起票したタスクが
「対象はこの節」と指せるように、severityに関わらず全件をそのまま残す。

シャードの切り方: `backend/app/domain`を材料・軸系（A）と探索・評価系（B）へ、
`backend/app/services`（C）、`backend/app/infrastructure`（D）、api/batch/config/scripts/
デプロイ（E）、frontend `Map/MapView`系（F）、frontend `Map`その他＋チップ（G）、
frontend `app`/`hooks`/`lib`/`services`（H）、`scripts/review_checks.py`（I）。
overallとconsistencyはシャードを共有し、1シャード1Agentが両レンズを出力した。

---

## シャードA: backend/app/domain（材料・軸・土地被覆系）

対象: material_catalog.py / attributes.py / axis_display.py / axis_inspector.py /
landcover.py / registry_defaults.py / derived_data_versions.py

### overall

- **file**: `backend/app/domain/material_catalog.py` **line**: 575-654
  **category**: 重複 / 構造仕様違反（構造仕様8・12） **severity**: P2
  **summary**: 土地被覆8クラスの材料だけが手書きの`MaterialSpec`ブロック8個で、同じファイル内のPOI材料が既に採っている「一覧から導く」形と食い違っている。
  **evidence**: `material_catalog.py:575-654`に`trees_percent`〜`snow_ice_percent`の8材料が1件ずつ手書き（`tile_property="trees_pct"`等のリテラルを含む）／同ファイル`:977-992`の停止要因POI材料は`POI_COUNT_KINDS`からdict内包表記で生成（「材料を1件ずつ手書きせず一覧から作る」と明記）／同じ8クラスの並びが4箇所に並列で手書き（`attributes.py:33-40`の`METRIC_KEY_*_PERCENT`、`attributes.py:47-56`の`WIRED_LANDCOVER_KEYS`、`landcover.py:35-47`の`LandcoverPercentages`、`landcover.py:120-131`の`LANDCOVER_CLASSES`）／タイル列名の規則`<クラス>_pct`は`road_graph_repository.py:299-308`で`key.removesuffix("_percent") + "_pct"`として導出される一方、`material_catalog.py`は同じ規則の結果を8回リテラルで書いている／更新漏れは検査で受け止める形（`test_material_coverage.py:44-48`の`covered | excluded == set(MATERIAL_CATALOG)`）だが、design-principles.md構造仕様12は「手書きの一覧の更新漏れを検出するための検査を足さない」としている。
  **failure_scenario**: クラスの改名・タイルプロパティ命名規則の変更時、導出側（タイル列・カバレッジ台帳）だけが追随し`MATERIAL_CATALOG`が取り残される。テストは「どちらにも未登録」は捕まえるが、`tile_property`のリテラルだけがずれた場合は捕まらず、材料は登録されたまま地図ramp自動導出だけが空になる。
  **recommendation**: `LANDCOVER_CLASSES`（label・percent_fieldを既に持つ）から8材料を生成する形へ寄せ、`tile_property`は`road_graph_repository.py`と同じ導出規則を共有する。

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 2603-2606
  **category**: 構造仕様違反（材料ごとの専用分岐）/ 局所最適の連鎖 **severity**: P2
  **summary**: 土地被覆の存在判定だけが`WIRED_LANDCOVER_KEYS`から導出されず、`trees_percent`という特定1クラスを名指ししている。
  **evidence**: `road_graph_repository.py:2603-2606`が`if row.trees_percent is not None`で分岐／同じ関数内のSELECT列（`:2561`）・タイル焼き込み列（`:299-308`）・カバレッジ台帳（`material_coverage.py:220-231`）はすべて`WIRED_LANDCOVER_KEYS`から導出済み／`attributes.py:321-324`の`from_bundles`は`bundle.landcover_percents[key]`と無条件アクセスするため、辞書にキーが欠けるとKeyError。
  **failure_scenario**: 将来`WIRED_LANDCOVER_KEYS`から`trees_percent`を外すと、SELECTに含まれなくなり`row.trees_percent`がAttributeError。`get_edge_materials_batch`は探索の主経路のため、ルート生成が全面的に落ちる。
  **recommendation**: 存在判定も並びから導く。

- **file**: `backend/app/domain/material_catalog.py` **line**: 581, 591, 601, 611, 621, 631, 641, 651
  **category**: 残骸 / スケール **severity**: P2
  **summary**: 8クラスぶんのタイル焼き込み列を路面MVTへ足して関東全域のタイル世代を上げた直後に、それを消費する唯一の軸が撤去され、現在`*_pct`を参照する軸が1つも無い。
  **evidence**: `axis-catalog.json`の`"property"`値一覧に`*_pct`は0件（公開軸は accident/bicycle_infra_quality/car_stress/gradient/night/surface_q/wind の7本）／`axis_definitions_snapshot.json`に`trees_percent`・`built_percent`・`crops_percent`・`landcover`の出現0件／`frontend/src`に`_pct`参照0件／`road_graph_repository.py:299-308`が8列を`_ROAD_SURFACE_TILE_MVT_SQL`へ焼き込む／コミット順: `ab498cdd`（T885起票=開放度廃止を決定）→`f49e2bc5`（T887完了、タイル世代 25-722e50311939 → 25-c079c3c2607b）→`c549a3da`（T885完了=開放度撤去）。
  **failure_scenario**: 全道路フィーチャに消費者ゼロの`double precision`8列が乗り、関東全域のタイルキャッシュ再生成を1回強制した。今後も焼き込みSQLを触るたびに使われていない8列のペイロードが乗り続ける。
  **recommendation**: (a) 軸を作る前提なら1タイルあたりの増分バイト数を実測してタスクへ残す。(b) 当面作らないなら、焼き込み列は`tile_property`を必要とする軸ができた時点で足す形へ戻す。

- **file**: `backend/app/domain/material_catalog.py` **line**: 578, 588, 598, 608, 618, 628, 638, 648
  **category**: 重複（値のコピー） **severity**: P3
  **summary**: 8つのdescriptionが「道路周囲100mリング内」というリング径を文字列で重複保持している。
  **evidence**: 正本は`derived_data_versions.py:20-21`（`WAY_LANDCOVER_DEFAULT_BUFFER_M = 100.0`／`_INNER_M = 10.0`）で、`way_landcover_algorithm_version`がこの値から版数を導く。
  **failure_scenario**: リング径を変えると版数は自動で変わるが、軸スタジオに出る8つの説明文は古い「100m」のまま残る。
  **recommendation**: descriptionをf-stringで定数から組み立てる。

### consistency

- **file**: `backend/app/domain/axis_inspector.py` **line**: 137-142
  **category**: 残骸 / docstringの破損 **severity**: P1
  **summary**: `axis_inspector_breakdown`のdocstringが文の途中で切れており、撤去済みの「開放度軸」と、もはや事実でない「配線済みの2列[trees/built]」を現行仕様として語っている。
  **evidence**: `axis_inspector.py:141-142`で括弧が閉じないまま`"""`が来る／`git diff 4a2cb02a...05c96456`で続きの2行がT887（`f49e2bc5`）の削除に巻き込まれたことが確認できる／開放度軸は`c549a3da`で撤去済み（スナップショットに`openness`0件）／配線クラスは2つではなく8つ（`attributes.py:47-56`）。
  **failure_scenario**: 区間インスペクタの唯一の純関数入口。次に触る開発者が「landcoverはtrees/builtの2列だけ」という誤った前提で配線を削る。
  **recommendation**: docstringを書き直し、「`percentages`がNoneなら土地被覆の材料はすべて欠損」という現在の挙動を1文で述べる。

- **file**: `scripts/review_checks.py` **line**: 1733
  **category**: 検査の母集団の欠落（構造仕様12 / CLAUDE.md「修正の原則」） **severity**: P1
  **summary**: 撤去済み軸の名指しを検出する`removed_axis_mentions`検知器が、アンダースコアを含まないaxis_idを母集団から落としており、今回撤去された2軸がちょうどその両方に当たる。
  **evidence**: `scripts/review_checks.py:1733` `return {a for a in mentioned - live if "_" in a}`／実測: `historical_axis_ids()`に`openness`・`curvature`は含まれる／`removed_axis_ids(files)`の返り値77件はすべてアンダースコア入りで両者を含まない／アンダースコア条件を外すと追加で拾えるのはちょうど`['curvature','openness']`の2件／この検知器は`DETECTOR_ENFORCEMENT`（`:2020`）でstaged/since/fullすべてブロック対象。
  **failure_scenario**: フィルタはノイズ（`synthetic_*`）を落とす意図と読めるが、実際にはノイズを全部残して実在の撤去済み軸だけを落としている。単語1語のaxis_id（`gradient`・`wind`・`night`・`accident`も該当）を今後撤去したとき、残った名指しはブロックされない。
  **recommendation**: 母集団の絞り込みをidの綴りではなく出自（`historical_axis_ids`のみ、テストフィクスチャ由来は除く）で行う。緩める前に検知できていた既知の1件が今も検知されることを別途示す。

- **file**: `docs/architecture.md` **line**: 1057
  **category**: docsと実装の乖離（撤去済み軸の残存） **severity**: P2
  **summary**: 「軸ごとの算出元と背景」の表に、撤去済みの開放度軸の行が現行として残っている。
  **evidence**: `docs/architecture.md:1057`に開放度の行／同表の直前（`:1040-1043`）に「現行の軸を列挙する」意図が明示／撤去は`c549a3da`／同型の残存: `docs/modules/backend/static-road-attributes.md:13`、`road_graph_models.py:265`、`road_graph_repository.py:810`・`:2389`。
  **failure_scenario**: 「現在どの軸があるか」をarchitecture.mdで確認した人が、存在しない軸を前提に仕様を組む。上の検知器の穴があるため機械的にはブロックされない。
  **recommendation**: 表から行を削るか撤去の断りを段落へ入れる。実装側4箇所の日本語ラベル残存も同時に掃く。

- **file**: `docs/modules/backend/evaluation-scoring.md` **line**: 326-330
  **category**: docsが述べる契約と実装の不一致 **severity**: P2
  **summary**: 「クラスを1つ配線するのはこの並びへ1行足すだけで済む」と書かれているが、実際には`MaterialSpec`と`METRIC_KEY_*`定数の追加が必須で、1行だけ足すとテストが落ちる。
  **evidence**: `evaluation-scoring.md:326-330`の記述／`MATERIAL_CATALOG`はこの並びから導かれていない／`test_material_coverage.py:44-48`が`covered | excluded == set(MATERIAL_CATALOG)`を要求するため等式が崩れる／T887のコミットメッセージも同じ主張。
  **failure_scenario**: docsを信じて1行だけ足した開発者が原因の分かりにくいテスト失敗に当たる。逆にこの記述があることで`MATERIAL_CATALOG`側の手書きが「解決済み」に見える。
  **recommendation**: 実装を記述に合わせる。合わせられないなら「材料エントリだけは別途追加が要る」を明記。

- **file**: `backend/app/domain/landcover.py` **line**: 5-8
  **category**: 設計原則と実装説明の矛盾 / 残骸 **severity**: P2
  **summary**: モジュールdocstringが、現在は設計原則で禁止されている「複数クラスの重み付き線形結合による軸」を正しい設計として説明している。
  **evidence**: `landcover.py:5-8`が`terms`（重み付き線形結合）で分類を表現すると述べる／`docs/design-principles.md:134-144`（構造仕様14、T887で新設）が「合計が決まっている材料は1つの軸で複数を足さない」と定める／`docs/modules/backend/evaluation-scoring.md:332-333`は追随済み。
  **failure_scenario**: このファイルを起点に土地被覆軸を作る人が、docstringの誘導どおり複数クラスの`terms`を組み、開放度が撤去された原因そのものを再生産する。
  **recommendation**: docstringを構造仕様14に沿って書き直し、経緯ポインタ（T624参照）を外す。

- **file**: `backend/app/domain/axis_inspector.py` **line**: 54-55, 83
  **category**: 追加された行が既に事実と食い違う **severity**: P2
  **summary**: 今回の範囲で追加・書き換えられたコメント2箇所が、配線クラスが2つだった時代の記述のまま。
  **evidence**: `:54-55`（本diffで新規追加）「軸の材料に使うのはこのうち2クラスだけ」——現在は8クラス全部が材料で、かつ現時点でどの軸も土地被覆材料を使っていない／`:83`（本diffで書き換え）「`way_landcover`の8列すべてではない」——`WIRED_LANDCOVER_KEYS`は8つの割合列と1対1のため成り立たない（`test_landcover_tile.py:87-88`が8件一致を検査）。
  **failure_scenario**: 「材料に使うのは2クラス」を根拠に残り6クラスの受け渡しを不要と判断して削る、という逆向きの変更が起こりうる。
  **recommendation**: 両方を現状へ書き直す。

- **file**: `backend/app/domain/axis_display.py` **line**: 234
  **category**: 削除された事実を語る周辺表現の残存 **severity**: P3
  **summary**: `raw_value_unit`のdocstringが撤去済みの開放度軸を現存する「実例」として名指ししている。
  **evidence**: `axis_display.py:234`「開放度の`樹木% + 建物%`が実例」／docs側の写し`docs/modules/backend/axis-studio.md:236`も同じ／`design-principles.md:136-138`は同じ説明を軸名を出さずに書けている／同ファイル`:432`は今回のdiffで`[openness等]`を削除済み（1箇所だけ直して1箇所を残した形）。
  **recommendation**: 軸名を出さない書き方へ揃える（実装とdocsの2箇所同時）。

- **file**: `backend/tests/test_material_catalog.py` **line**: 87-95
  **category**: 実装↔テストの乖離（母集団が導出されていない） **severity**: P3
  **summary**: 土地被覆材料のテストが8材料のうち`trees`/`built`の2つしか検証しておらず、`WIRED_LANDCOVER_KEYS`から導かれていない。
  **evidence**: `test_material_catalog.py:87-95`が2材料だけを取り出す／他のテストは並びから導いている（`test_attributes.py:176`・`:282`、`test_evaluation_bulk.py:307`、`test_road_graph_repository.py:1461`）／T887のコミットメッセージは「テストを1件も変更せずに1,984件が通った（すべて`WIRED_LANDCOVER_KEYS`から導かれるため）」と述べるが、このテストはその「すべて」に含まれていない。
  **failure_scenario**: `crops_percent`〜`snow_ice_percent`の6材料の配線が壊れてもテストは通り続ける。実データで稀なクラスほど気づかれない。
  **recommendation**: `for key in WIRED_LANDCOVER_KEYS`で回す形へ変える。

- **file**: `backend/app/domain/attributes.py` **line**: 141
  **category**: コメント方針（経緯の残存） **severity**: P3
  **summary**: 本diffで書き換えられたコメントにタスク番号の経緯ポインタが持ち越されている。
  **evidence**: `attributes.py:141`「`way_landcover`（T624）のうち…」（本diffで書き換えられた行）／`docs/comments.md:32-35`が禁止／検知器では拾われない（`find_source_narrative`を`backend/app/domain/`全件へ実行して0件）。
  **recommendation**: `（T624）`を落とす。`landcover.py:8`の同型も同じ扱い。

### 参考（範囲外の観測）

`backend/tests/realistic_axis_fixtures.py:317-327`が撤去済みの`openness`軸をフィクスチャとして保持し、`test_evaluation.py:679-706`等がその名前で通っている。フィクスチャが合成軸を持つこと自体は設計どおりだが、現在は「土地被覆材料を使う軸が本番に1つも無い」ため本番構成を模していない。

---

## シャードE: api層・batch・config・backend/scripts・デプロイ

対象: api/routers/region.py / api/routers/_tile_http.py / api/cache_policy.py / config.py /
batch/precompute_way_landcover.py / batch/precompute_road_node_intersections.py /
batch/precompute_way_divided_carriageway.py / batch/refresh_derived.py /
scripts/export_openapi.py / scripts/fetch_lulc_raster.py / Dockerfile / deploy-backend.yml

### overall

- **file**: `.github/workflows/deploy-backend.yml` **line**: 90-94
  **category**: デプロイ安全性 / 検知が効いていない **severity**: P2
  **summary**: `LULC_RASTER_PATHS`の自己修復はキーの有無しか見ないため、コメントが主張する効果が空値・誤値の場合に成立しない。
  **evidence**: 90行「上のCORS_ALLOWED_ORIGINSと同じ流儀の自己修復」と書きつつ92行は`grep -q "^LULC_RASTER_PATHS="`（キーの存在のみ）。CORS側（67-71行）は値まで見て`sed`で追記する／`fetch_lulc_raster.py:73-79`は未設定だと`logger.warning`して`return 0`／`config.py:197-198`の`lulc_raster_paths_list`は空要素を捨てる。
  **failure_scenario**: `LULC_RASTER_PATHS=`（空）が一度でも入るとfetchがWARNINGのみで成功扱い→デプロイ成功→土地被覆タイルが恒久的に503。旧Azure命名が入るとS3に無いキーを取りに行き`set -e`でbackendデプロイが恒久的にブロックされる。
  **recommendation**: CORSと同じく値まで検査するか、`fetch_lulc_raster.py`側で「未設定」を非0終了にする。

- **file**: `.github/workflows/deploy-backend.yml` **line**: 102-115
  **category**: デプロイ安全性 / 順序 **severity**: P2
  **summary**: 外部依存（S3からのラスタ取得）がmigration適用より後ろに置かれており、配布元の障害でDBだけ進んだ状態が残る。
  **evidence**: 102-106行で`apply_migrations.py`、110-115行で`fetch_lulc_raster.py`、129行で旧コンテナstop／`fetch_lulc_raster.py:90-92`はHTTPエラーで`return 1`（`set -e`で中断）／`command_timeout: 15m`。
  **failure_scenario**: S3の一時障害でfetchが落ちると、migrationは適用済み・コンテナは旧のまま。旧コードが新スキーマのDBを読む状態が復旧まで続く。初回デプロイで69MBのダウンロードが15分枠を食う場合も同様。
  **recommendation**: `fetch_lulc_raster.py`を`apply_migrations.py`より前へ移す（どちらもコンテナ入れ替え前で、順序入れ替えのコストはゼロ）。

- **file**: `backend/app/api/cache_policy.py` **line**: 102-104
  **category**: 抜け / 兄弟エンドポイントとの不揃い **severity**: P2
  **summary**: 土地被覆タイルだけ`PERMANENT`（24時間＋`immutable`）で、「同じURLの内容は変わらない」という前提がラスタ構成の変化に対して成り立たない。
  **evidence**: `cache_policy.py:52`の`PERMANENT`／`landcover_tile_service.py:24`の`LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)`——`settings.lulc_raster_paths`は世代の材料に入っていない／`render_tile`は範囲外で`None`を返し、`serve_cached_tile`は`cacheable = fields.get("postgis") != "error"`＝`True`で空タイルを返す（landcoverの`fetch_tile`は`fields["postgis"]`を設定しない）／兄弟の路面・POI・事故は`BATCH_TILE`（1時間・非immutable）。
  **failure_scenario**: ゾーン54S外を表示した利用者のブラウザへ全面透明PNGが24時間immutableで残る。後からゾーンを足しても`?v=`は変わらないため、リロードでも復旧できない。
  **recommendation**: `BATCH_TILE`相当へ落とすか、`LANDCOVER_TILE_VERSION`の材料へラスタ構成の指紋（バッチ側に`raster_set_fingerprint`が既にある）を含める。空タイル時に`cacheable=False`にできるよう`fields`へ状態を立てる。

- **file**: `backend/app/infrastructure/landcover_raster.py` **line**: 76-89
  **category**: 暗黙のタイミング制約 **severity**: P3
  **summary**: `_open_sources()`が「開けたラスタ0枚」もプロセス寿命いっぱい記憶するため、後からラスタを置いても再起動まで復旧しない。
  **evidence**: `_sources`は`None`のときだけ初期化され、空リストもキャッシュする／`reset_sources_for_testing()`はテスト専用。
  **recommendation**: 空だったときだけ再試行する（成功したソースのみ記憶）か、起動時に一度評価して`/health`へ状態を出す。

- **file**: `backend/app/services/landcover_tile_service.py` **line**: 36-43
  **category**: ログ量 **severity**: P3
  **summary**: ラスタ未設定時にタイル1枚ごとWARNINGを出すため、1画面ぶんの要求でログが埋まる。
  **evidence**: `has_sources()`が偽のたびに`logger.warning(... z x y)`／レート制限は毎分120。
  **failure_scenario**: 設定漏れのままチップをONにすると毎分最大120行×利用者数のWARNINGが他の障害ログを押し流す（`--log-opt max-size=10m --log-opt max-file=5`）。
  **recommendation**: 初回のみ、または一定間隔でのみ出す。

- **file**: `docs/tasks/T888.md` **line**: 1-25
  **category**: 重複 / 起票範囲 **severity**: P3
  **summary**: 「1箇所で済まない」問題としてT888が起票済みだが、対象がfrontendに限定されbackend側の同型が範囲外。
  **evidence**: T888本文は`show◯◯`prop・`layerVisibility`のみ／今回のbackend側は専用サービス・専用semaphore（`region.py:38`）・専用設定（`config.py:104`）・専用cache_policy行・専用生成物を新設している。
  **recommendation**: T888本文にbackend側も射程に含むと明記するか、別起票して範囲を分ける。

### consistency

- **file**: `docs/batch-pipeline-dependencies.md` **line**: 26
  **category**: 残骸（Markdown破損） **severity**: P2
  **summary**: 依存DAG図の閉じコードフェンスがT881の削除に巻き込まれて消えており、26行目以降の文書全体がコードブロックとして描画される。
  **evidence**: `grep -n '^```' docs/batch-pipeline-dependencies.md`の結果が26行目の1件のみ／`git diff 4a2cb02a...05c96456`で`-⑫ precompute_edge_curvature.py ...`と同じhunk内から閉じフェンスが削除されている。
  **failure_scenario**: 「2. バッチ別の入出力・依存・再実行トリガー」以降が読めない。再実行トリガーを引きに来た運用者が表を読めない。
  **recommendation**: 閉じフェンスをDAG図の末尾へ戻す。

- **file**: `backend/app/batch/precompute_way_landcover.py` **line**: 96-99
  **category**: コメントが主張する挙動と実装が逆 **severity**: P2
  **summary**: 遅延importの理由「rasterioは本番webイメージに無い」がT886で成り立たなくなっている。
  **evidence**: 該当コメント／`backend/requirements.txt`に`rasterio==1.5.1`が移動済み（batch側からは削除）／`landcover_raster.py:30`がモジュール冒頭で`import rasterio`し、`app.main`→`region.py:13`→`landcover_tile_service`経由で無条件に読み込まれる／同じ理由付けが`_RasterSource.__init__`（176行）にもある。
  **failure_scenario**: 次に触る者が「webイメージにrasterioは無い」を前提に判断し、不要な迂回を継続、または本当に無い依存（pyosmium）と取り違える。
  **recommendation**: コメントを現状へ直す。`docs/modules/backend/static-road-attributes.md:11`の同趣旨も見直す。

- **file**: `backend/app/batch/refresh_derived.py` **line**: 9-12
  **category**: 残骸 / 記載漏れ **severity**: P2
  **summary**: `_STAGES`へ⑭を足した一方、実行順序を述べるdocstringは⑬止まり。前回レビュー（S4 C-2）で指摘済みの「④〜⑫」系の陳腐化も3箇所残っている。
  **evidence**: `refresh_derived.py:9-12`の列挙は⑬で終わるが`_STAGES`（62-72行）は⑭を含む／同じ欠落が`docs/disaster-recovery.md:23-28`、`docs/batch-pipeline-dependencies.md:143`／前回指摘に対しては`全12バッチとも`→`いずれのバッチも`（同ファイル:91）だけが直っている。
  **failure_scenario**: disaster recovery手順を文書どおり追った運用者が実行範囲を⑬までと理解する。
  **recommendation**: docstringと2つのdocsへ⑭を反映し、「④〜⑫」を範囲の書き方ごと見直す。

- **file**: `docs/batch-pipeline-dependencies.md` **line**: 135
  **category**: 残骸 **severity**: P3
  **summary**: 再実行トリガー早見表が撤去済みの⑪⑫を指したままで、⑬⑭が抜けている。
  **evidence**: 「①→④→…→⑪→⑫」の記述／⑪⑫（curvature）は`0042_drop_curvature.sql`で撤去済み。
  **failure_scenario**: PBF再取込後にこの表どおり実行すると⑬（上下線分離）と⑭（交差点属性）が走らない。
  **recommendation**: ⑪⑫を落とし⑬⑭を入れる。`ROAD_SURFACE_REVISION`の材料列挙も同様。

- **file**: `docs/batch-pipeline-dependencies.md` **line**: 67
  **category**: 残骸 **severity**: P3
  **summary**: 中身が消えた見出し【第2グループの続き…】だけが残っている。
  **evidence**: 直下にあった⑫のエントリがT881で削除され、見出しの次はいきなり別の段落。参照している⑪も存在しない。
  **recommendation**: 見出しごと削除する。

- **file**: `backend/app/api/routers/_tile_http.py` **line**: 1-6, 38-46
  **category**: コメントが主張する挙動と実装のずれ / 数え上げ **severity**: P3
  **summary**: 共通HTTP層のdocstringが消費者を「路面・POI・事故」と数え上げたままで、`tile_response`の説明も`BATCH_TILE`（1時間）固定を前提にしている。
  **evidence**: 1行目・3-4行目の列挙／41-43行「その空白が利用者のブラウザへ1時間残らないように」／実際には`region.py:101`の土地被覆（`PERMANENT`、24時間＋immutable）も同じ関数を通る。
  **recommendation**: 消費者の列挙をやめ、既定値は対応表が決める旨に書き換える。

- **file**: `docs/modules/backend/static-road-attributes.md` **line**: 16, 234-238
  **category**: 記載と実装のずれ **severity**: P3
  **summary**: `_tile_http.py`の説明が「両者が共有する」のままで、`refresh_derived.py`の段の列挙順が`_STAGES`の実行順と一致しない。
  **evidence**: 16行「両者が共有する」／234-238行は`precompute_road_node_intersections.py`を2番目に置くが`_STAGES`では最後。
  **recommendation**: 「両者」を消費者数に依存しない表現へ、段の列挙は`_STAGES`の順へ揃える。

- **file**: `backend/tests/test_region_routes.py` **line**: 164, 231, 408
  **category**: 実装↔テストの抜け **severity**: P3
  **summary**: 兄弟タイルが全て持つ「レート制限が路面タイルと独立していること」のテストが、土地被覆にだけ無い。
  **evidence**: POI（164）・axis-inspector（231）・dynamic-way-values（408）に同種テストがあるが`test_landcover_tile.py`には無い／`region.py:95`は`_check_tile_rate_limit(request, "landcover-tile")`。
  **failure_scenario**: prefixの取り違えで土地被覆と路面がカウンタを共有しても落ちない。
  **recommendation**: 兄弟と同じ形のテストを1本足す。

- **file**: `backend/scripts/fetch_lulc_raster.py` **line**: 43-68
  **category**: ログ方針 **severity**: P3
  **summary**: 外部（S3）へのHTTP取得が`log_external_call`を通らない。
  **evidence**: `httpx.stream`を直接呼び、成否は`logger.info`／`logger.error`のみ／`docs/logging.md`は外部アクセスを`log_external_call`で囲むとしている。
  **recommendation**: 意図的な例外とするならその旨をdocstringへ1行書く。

- **file**: `docs/architecture.md` **line**: 1175
  **category**: 記載漏れ（現状） **severity**: P3
  **summary**: デプロイ手順の記述がmigration適用ステップ止まりで、T886で足した2ステップ（起動確認・ラスタ取得）が「現状」docsに無い。
  **evidence**: 1175-1178行はmigration適用のみ／起動確認（deploy-backend.yml:74-80）とラスタ取得（同110-115）の記述は`docs/tasks/T886.md`にしかない。
  **failure_scenario**: 次にデプロイ手順を変える者が、起動確認ステップの存在意義を知らずに位置を動かす／削る。
  **recommendation**: 同節へ2ステップとその順序の意味を1〜2文で追記する。

### 指摘に至らなかった確認事項（参考）

- 新設エンドポイントは兄弟と同じレート制限（prefix分離）・座標検証・専用semaphore・`log_external_call`・空タイル時の`no-store`経路を備えており、抜けはキャッシュポリシー1点のみ。
- `cache_policy.py`への登録漏れは`test_cache_policy.py`の全ルート走査が両方向で強制しており、今回も登録済み。
- OpenAPI生成物のドリフトは見当たらない（`openapi.json:676`に新パス、`region-tile-config.json`に`landcover`、`landcover-classes.json`／`regionApi.ts`の片側importも成立）。
- `ContentTypeGZipMiddleware`はPNGを素通しするため、ラスタタイルへの無駄な圧縮は発生しない。
- 新設バッチ`precompute_road_node_intersections.py`は`run_chunked_precompute`へ相乗りし、dry-run・0件警告・チャンク進捗・SQLをrepository側に置く規約を満たしている。
- curvature撤去の残骸は実コード（`backend/`・`frontend/`・`.github/`）には1件も残っていない。残るのは過去migration（書き換えない運用どおり）とdocsの番号参照のみ。

---

## シャードB: backend/app/domain（探索・評価・ジオメトリ系）

対象: routing.py / evaluation.py / graph.py / geo.py / osm_adapter.py / route.py

### overall

- **file**: `backend/app/domain/graph.py`（＋`services/graph_service.py`・`road_graph_engine.py`） **line**: 332
  **category**: 局所最適の連鎖 / 構造的欠陥（経路によって前提が崩れる） **severity**: P1
  **summary**: T800で足した`has_traffic_signals`/`max_highway_rank`を、探索グラフを作るもう一方の経路（`build_road_graph`）が埋めないため、その経路を通ったリクエストだけ「信号のある交差点にも横断待ちを足す」T800以前の挙動へ黙って戻る。
  **evidence**: `graph.py:332-334`が`LeanNode(node_id, latitude, longitude, osm_node_id)`のみで生成し2列は既定（False/0）／`graph_service.py:344`の`_build_search_materials_uncached`が`get_or_build_graph_with_attributes`（`:260`で`build_road_graph`）の結果を探索へ渡す（条件は`graph_service.py:343`の`if not await self._ensure_split_up_to_date(bbox)`）／`road_graph_engine.py:2304-2315`の`_node_intersection_attributes`は`graph.nodes`を読むだけでDBへ問い合わせない／対照: `road_graph_repository.py:1112`・`:1168`は両方とも2列を設定する／`_MERGE_ROAD_NODES_SQL`（`:1245-1251`）はこの2列を更新しない（DBの値は壊れず、欠けるのはその場のメモリ上のグラフだけ）。
  **failure_scenario**: PBF再取込直後や未split地点への最初のルート生成で、信号のある幹線交差点すべてに`major_crossing_seconds`/`major_turn_seconds`が上乗せされ、同じ地点・同じ条件でも2回目以降（タイル経路）と経路も`estimated_duration_seconds`も変わる。利用者からは再現しない揺らぎに見える。
  **recommendation**: `build_road_graph`の出力を探索へ渡す前に`road_nodes`の2列を補う。どちらの経路で作ったグラフでも同じ`turn_seconds`になることを1件のテストで固定する。

- **file**: `backend/app/domain/routing.py` **line**: 581
  **category**: 構造仕様違反（設計原則13の二重計上） **severity**: P2
  **summary**: 信号は二重計上として除外したのに、走行モデルが既に秒で数えている「一時停止」「車止め」のある無信号交差点は除外しておらず、同じ待ちを2回足している。
  **evidence**: `routing.py:715-716`の除外条件は`crosses_major & ~node_has_signal[...]`のみ／`routing.py:586`の`major_crossing_seconds: float = 8.0`（コメント「車列の切れ目を待つ時間」）／`domain/traffic.py:145-151`の`STOP_SECONDS`が`"stop": 8.0`・`"barrier": 8.0`、同`:131-137`のコメントは「待ちの期待値＋減速と再加速のロス」＝無信号交差点での待ちそのもの／`road_graph_engine.py:369-372`が`stop_count_material_ids()`の全kindを`stop_seconds(kind)`倍して区間の所要時間へ加算し、それが探索コストにも`estimated_duration_seconds`にも入る。
  **failure_scenario**: 生活道路が幹線を横切る（無信号＋一時停止標識）という日本で最も一般的な形で8秒＋8秒＝16秒。探索はこの種の交差点を過剰に避け、迂回候補が「速い」と表示される。較正（T801）はこの重なりを前提にしていない。
  **recommendation**: `stop`/`barrier`のPOIがあるノードも`crosses_major`から外す（`has_traffic_signals`を「待ちを走行モデルが既に数えているノードか」の意味へ一般化する）。外せないなら理由を`TurnCostSpec`のコメントへ書く。

- **file**: `backend/app/domain/routing.py` **line**: 544
  **category**: スケール（最悪計算量） **severity**: P2
  **summary**: `find_nearest_node_indexed`は`predicate`を満たすNodeが1つも無いとき、バケット数Bに対して約(4/3)·B³回のセル走査を行い、実質的に応答が返らなくなる。
  **evidence**: `routing.py:544`の`max_radius = max(len(index.buckets), 1) + 1`／`:545-562`が各半径で`(2r+1)²`回を回しリング外を`continue`で捨てる。打ち切りは`nearest_distance is not None`が前提（`:560`）のため全件棄却だと`max_radius`まで伸びる／唯一`predicate`を渡す呼び出しは`road_graph_engine.py:1396-1400`（述語=前向き木で到達可能なNode）で、直後の`:1403-1412`が`reached_nodes == 0`を明示的に想定してWARNINGを出している／セルは0.01度四方（約1.1km）。
  **failure_scenario**: 起点から1ノードも到達できないリクエストで、目的地補正の最近傍探索が数百億回のdict参照へ入る。ワーカースレッドが張り付き、利用者には「いつまでも返らない」として見える。WARNINGはその先にあるため出ない。
  **recommendation**: 索引が張られている最大半径を上限にする。リング走査を周（8rセル）の列挙にする。

- **file**: `backend/app/domain/routing.py` **line**: 712
  **category**: 局所最適の連鎖 **severity**: P3
  **summary**: `highway_rank`が自転車道・歩道・pathを一律0にしているため「上位の道と交わる」判定が`cycleway → service`でも成立し、T800でDB全域の`max_highway_rank`を併用したぶん発火頻度が上がった。
  **evidence**: `domain/traffic.py:250-252`が未知・自転車道・歩道を0で返す／同`:240-248`は`service`/`residential`/`living_street`/`unclassified`をすべて1／`routing.py:712`の`crosses_major`に差の下限が無く0→1でも成立／`:710-711`でDB側`max_highway_rank`との`np.maximum`。
  **failure_scenario**: 街路に並行する自転車道が側道・駐車場出入口を横切るたび、無信号なら直進でも+8秒。優先したい自転車インフラが交差の多さだけで不利になる。
  **recommendation**: 「上位」の定義に下限を入れるか自転車道を`residential`と同格へ。較正（T801）の検討項目へ含める。

- **file**: `backend/app/domain/evaluation.py` **line**: 481
  **category**: 重複（同じ述語の分岐が2つに分かれている） **severity**: P3
  **summary**: 空タイル分岐と通常分岐で材料列の作り方が非対称（片方だけ`if material_id in material_arrays`のガードを持つ）。
  **evidence**: `:481-487`（n==0）は`route_facing_material_ids()`等を無条件展開、`:603-612`（n>0）は同じ2関数にガード付き／同`:324-330`・`:369-370`が「空タイルと通常タイルが別々に条件を書くと`np.concatenate`が失敗する」と明記／現状は`material_arrays`が`MATERIAL_CATALOG`全件ぶん確保されるため差は観測されない。
  **failure_scenario**: 将来`route_facing_material_ids()`がカタログ外のidを返す変更が入った瞬間、空タイルだけ列が1本多くなり、道路データが疎らな区画を含むbboxでのみ合成が落ちる。
  **recommendation**: どちらかの書き方へ揃える。

- **file**: `backend/app/batch/refresh_derived.py` **line**: 9
  **category**: 数え上げ／記載漏れ **severity**: P3
  **summary**: docstringが実行順を全件列挙しており、T800で追加した⑭が抜けている。`_STAGES`との突き合わせテストはこの文章を見ない。
  **evidence**: `:4`の「④〜⑬」、`:9-12`の列挙は⑬で終わる／`:71`に⑭が登録済み／`:15`「`tests/test_refresh_derived.py`がファイル一覧と`_STAGES`を突き合わせて登録漏れを止める」＝検査対象は`_STAGES`のみ。
  **recommendation**: 段の列挙をやめ「`_STAGES`の順に実行する」とだけ書く。

### consistency

- **file**: `backend/app/domain/axis_inspector.py` **line**: 137
  **category**: 契約不一致（docstringが途中で切れている）／撤去済み軸の残存 **severity**: P2
  **summary**: シャードAと同一（docstringが括弧を閉じないまま終端し、撤去済みの開放度軸と「配線済みの2列」を現状として述べる）。
  **evidence**: `:141-142`の終端／`attributes.py:47-56`は8クラス／`openness`はスナップショット・axis-catalogともに0件。
  **recommendation**: docstringを閉じ、集合は`WIRED_LANDCOVER_KEYS`を指すだけにして件数・クラス名を書かない。

- **file**: `backend/app/domain/evaluation.py` **line**: 10
  **category**: 契約不一致（本番に消費者のいない経路を「使う場面」付きで説明） **severity**: P2
  **summary**: 冒頭の「同じ評価を3つの表現で持つ」表が、本番の呼び出し元がゼロの2つ（スカラー・ベクトル）に現役の用途を割り当てている。前回O-2の未解消分＋スカラー行。
  **evidence**: `compute_edge_costs_bulk(`／`compute_edge_cost(`の非定義呼び出しは`backend/tests/`のみ／`compute_edge_axis_scores`の非テスト呼び出しは`evaluation.py:248`（それ自体テスト専用）のみ／実際の区間表示は`:639-659`＋`:707`／`:829`が自分自身を専用用途として説明する自己参照／波及先は`axis_definitions.py:9`、`axis_templates.py:17`・`:77`。
  **failure_scenario**: 材料・軸を足す人がまず「区間表示の経路」としてスカラー版へ手を入れ、テストは通るが本番の表示は変わらない。
  **recommendation**: 「使う場面」列を実態（スカラー・ベクトル＝オラクル専用／タイル行列＝唯一の本番経路）へ書き換える。

- **file**: `backend/app/domain/route.py` **line**: 141
  **category**: 契約不一致（コメントが主張するフロント挙動と実装が違う） **severity**: P2
  **summary**: `is_fastest`のコメントが「フロントはこの候補を基準に他候補の超過分を出す」と述べるが、フロントは明示的にこのフラグを見ない。前回指摘の未解消。
  **evidence**: `route.py:141-146`／`frontend/src/lib/routeTabLabel.ts:26`が「backendの`is_fastest`は見ない」と明記／`page.tsx:1942`・`:2012`は`fastestRouteId(routes)`で自前に決める／フロントで読むのは`routeSplice.ts:150`のみ。
  **recommendation**: コメントを実態へ書き換える。

- **file**: `docs/modules/backend/routing-engine.md` **line**: 632
  **category**: docs乖離（存在しない引数を説明） **severity**: P2
  **summary**: 「`build_csr_structure`/`build_search_graph_statics`は両関数とも`reverse=True`で転置CSRを返す」と書くが、どちらも`reverse`引数を持たない。前回指摘の未解消。
  **evidence**: `routing-engine.md:632-635`／`routing.py:129`・`:207-209`のシグネチャ／転置は`TurnExpandedStructure.reverse_transitions()`（`:620`）。
  **recommendation**: 記述を削り、転置の在り処を一本化する。

- **file**: `docs/architecture.md` **line**: 1057
  **category**: 削除された事実を語る周辺表現の残存（T885） **severity**: P2
  **summary**: 撤去済みの開放度軸を前提にした記述がdocs・backend・frontendに残る。うち`primaryAttributes.ts`は、T886で実在するようになった`landcover`レイヤーを「意図的に持たない」側に置いたまま。
  **evidence**: `docs/architecture.md:1057`の表行／`docs/modules/backend/axis-studio.md:39`が`openness`を現役の一覧として名指し／`road_graph_models.py:265`・`road_graph_repository.py:810`・`:2389`／`frontend/src/components/Map/primaryAttributes.ts:63-64`「landcover…も同様に専用レイヤーは持たず、地図表示は開放度軸自身のramp表示に委ねる」＋`:78`の`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`に`"landcover"`／一方`mapLayers.ts:37`・`:212`に`landcover`レイヤーが実在する。
  **failure_scenario**: 土地被覆を使う軸を次に作ったとき、`primaryAttributeIdsToLayerIds`が`landcover`を返さず、推定指標レイヤーONに連動して観測データの面が出ない。
  **recommendation**: `openness`／「開放度」の語を外し、`landcover`を`PRIMARY_ATTRIBUTE_LAYER_IDS`側へ移す。

- **file**: `backend/app/domain/routing.py` **line**: 70
  **category**: 残骸（コメントが述べる仕組みが実装に無い） **severity**: P3
  **summary**: 並行Edge解消のコメントが「cost比較が同点の場合のタイブレークにも使う」と述べるが、この関数にコスト比較は無い。
  **evidence**: `:70-71`のコメント／`:72-81`の実装は`if pair not in best_by_pair`のみ／`edge_cost_by_id`引数とコスト比較の枝はT819で撤去済み／本diffでクラスdocstring（`:46-47`）は修正済み。
  **recommendation**: コメント後半を削る。

- **file**: `docs/modules/backend/routing-engine.md` **line**: 317
  **category**: docs乖離（overallのP1と対） **severity**: P3
  **summary**: 「信号の有無と最大階級は`road_nodes`の事前集計列で、グラフのノードに載って探索まで届く」と無条件に書くが、`build_road_graph`で組み直す経路では載らない。
  **evidence**: `routing-engine.md:317-319`・`:871-886`／`graph.py:332-334`・`graph_service.py:344`。
  **recommendation**: P1の実装修正と同時に、届く条件を明記するか実装側を揃える。

- **file**: `backend/app/domain/osm_adapter.py` **line**: 85
  **category**: コメントが述べる根拠と実装の経路が違う **severity**: P3
  **summary**: `ALLOWED_WAY_TAGS`へ`junction`を入れた理由として`_resolve_direction`を挙げているが、`_resolve_direction`はフィルタ前の生タグを読むため許可リストとは無関係に動く。
  **evidence**: `osm_adapter.py:85-86`のコメント／`:124-125`が生タグを渡し、`_filter_allowed_tags`（`:111`）を通すのは`WaySpec.tags`だけ（`:132`）／対照に`lit`（`:100-102`）は実際に成り立つ／保存された`junction`の実際の消費者は再split（`road_graph_repository.py:1928-1935`は`direction`列を読む）。
  **recommendation**: 保存理由（表示・後からの再導出）と、方向の解決が取込時にしか走らない事実を分けて書く。

- **file**: `backend/app/domain/routing.py` **line**: 231
  **category**: 自己申告の手動同期ペア（検知器化されていない） **severity**: P3
  **summary**: `overlap_ratio`と`select_diverse_by_overlap`内のbulk計算が同じ閾値判定式の二重実装で、文章のルールだけで守られている。
  **evidence**: `:231-245`と`:406-423`／`:234-236`が「閾値判定式を変更する場合は両方を揃えること」と書く／`test_routing.py:236-241`・`:244-`はそれぞれ単体で、突き合わせるテストは無い。
  **recommendation**: ランダム入力で両者が一致することを1件固定する（スカラー版をbulk版のオラクルとして呼ぶ）。

### 参考（解消の確認）

- T881（蛇行）の撤去は徹底。`curvature`／「蛇行」は`backend/app`・`frontend/src`・`docs/modules`・`docs/architecture.md`に0件。残るのは`backend/migrations/0035,0036,0040,0042`と`docs/tasks/`・レビュー履歴のみ。
- 前回P2の`routing.py:46-47`クラスdocstringと`evaluation-scoring.md:211-213`は修正済み。
- T800のテストは「わざと壊した入力」を持つ（`test_routing_turn_expanded.py:477-541`）。ただしグラフ構築経路を跨いだ検証は無く、上記P1はこの穴に落ちている。
- `TILE_MATERIALS_CACHE_VERSION`は`shape_digest(EdgeMaterialTable, LeanNode, LeanEdge)`のため`LeanNode`への2列追加で鍵が自動で変わる。
- `max_highway_rank`集計SQLは`HIGHWAY_RANK`辞書からCASE式を組み立てており写経は発生していない。

---

## シャードC: backend/app/services

対象: road_graph_engine.py / route_generator.py / graph_service.py / region_service.py /
axis_preview_service.py / landcover_tile_service.py / tile_serving.py / derived_data_revision_service.py

### overall

- **file**: `backend/app/services/axis_preview_service.py` **line**: 89
  **category**: 撤去の取り残し（シグネチャ変更への追従漏れ） **severity**: P0
  **summary**: T887が`way_scalar_materials`の引数を7個へ畳んだとき、2つある呼び出し元のうち`axis_preview_service`だけ更新されず、軸スタジオの分布プレビューが呼ぶたびTypeErrorで落ちる。
  **evidence**: 定義は`domain/axis_inspector.py:65-73`で位置引数7個／呼び出しは`axis_preview_service.py:89-93`で8個（…, `row.trees_percent`, `row.built_percent`, `row.surface`）／ASTで機械的に照合して確認（8 > 7）／`git show f49e2bc5 --stat`にこのファイルは含まれない／CIにbackendの型検査は無い（`.github/workflows/ci.yml:111`はruffのみ）。
  **failure_scenario**: 軸スタジオで折れ点を編集すると`POST /api/admin/axis-definitions/preview-distribution`（`axis_admin.py:505`）と`GET /api/admin/material-catalog/{id}/distribution`（`material_catalog.py:182`）が毎回500。`_sample_cache`はTTL15分のプロセス内キャッシュで、プロセス再起動後は必ず失敗する。`scripts/measure_axis_saturation.py:75`も同じ経路。引数の数だけ直しても`row.trees_percent`（float）が`landcover_percents`（dict）へ渡る型の誤りが残る。
  **recommendation**: 呼び出しを`{key: getattr(row, key) for key in WIRED_LANDCOVER_KEYS}`の形へそろえる。**この型の欠陥は検知器にできる**——モジュール直下の関数定義と素の名前呼び出しをASTで突き合わせる40行程度のチェックで、リポジトリ全体を走査して真の違反はこの1件だけだった（他26件は`**fields`を取る`log_external_call`等の誤検知で、kwargの有無を見れば消える）。

- **file**: `backend/app/services/landcover_tile_service.py` **line**: 24
  **category**: 無効化の鍵に入らない入力 / キャッシュ方針違反 **severity**: P2
  **summary**: 土地被覆タイルの世代が「どのラスタを開いているか」を鍵に含めず、しかもHTTPは`immutable`で24時間配るため、ラスタを1枚足しても新しい範囲が塗られない。
  **evidence**: `LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)`（配色とクラス構成だけ）／対象ラスタは環境変数`LULC_RASTER_PATHS`（`config.py:190`）でコード変更なしに増減する／`landcover_raster.py:149-151`のdocstringは「後からラスタを足せば値を持ちうる」と明記／バッチ側は同じ理由で`raster_set_fingerprint`（`precompute_way_landcover.py:119-128`）を持ち`WayLandcover.source_raster_set`へ記録する／`cache_policy.py:102-104`が`PERMANENT`（max-age=86400, immutable）を割り当て、同`:31-33`は「`immutable`はURLが同じなら内容も同じと保証できる場合のみ」と規定。
  **failure_scenario**: `LULC_RASTER_PATHS`へゾーンを1つ足すとURLの世代は変わらず、サーバーのディスクキャッシュは古いPNGを返し続け、ブラウザは`immutable`のため条件付きリクエストすらしない。ゾーン境界にまたがるタイルは世代を手で上げるまで恒久的に欠ける。
  **recommendation**: `raster_set_fingerprint`を署名材料へ入れる。入れられないなら`PERMANENT`を`BATCH_TILE`へ落とす。

- **file**: `backend/app/services/road_graph_engine.py` **line**: 2294
  **category**: 経路によって入力が変わる（暗黙のタイミング制約） **severity**: P2
  **summary**: シャードBのP1と同一事象（`_node_intersection_attributes`が読む信号有無・最大階級はタイルキャッシュ経路のグラフにしか載らない）。
  **evidence**: DBから読む経路（`road_graph_repository.py:1112`・`:1168`）は載せる／`_build_search_materials_uncached`（`graph_service.py:352-391`）が通る`build_road_graph`（`domain/graph.py:332-334`）は載せない／`domain/routing.py:715-716`は`node_has_signal`が偽のとき待ちを足す／`save_graph`のNode UPSERT（`:1245-1251`）はこの2列を書かないためDB側の値は壊れない。
  **recommendation**: 冷パスでも2列を載せる。難しければ差が出ることを`_build_search_graph`の1行INFOへ出す。

- **file**: `backend/app/services/route_generator.py` **line**: 490
  **category**: 失敗理由の握り潰し（前回P2の未解消・経路が追加されて悪化） **severity**: P2
  **summary**: 合成ルートの検証エラーは利用者向けの日本語で書かれているのに、`generate_spliced_route`が捕捉せずrouterの汎用catchで捨てられる。T621の終点チェック追加で、握り潰しに落ちる入力が1種類増えた。
  **evidence**: `road_graph_engine.py:1748-1771`が「経路が空です」等に加え今回「経路が目的地に着いていません」を送出／`route_generator.py:490`は`try`で囲まず`last_no_candidates_reason`も設定しない（他の生成経路はすべて設定する）／`api/routers/routes.py:421-427`の汎用catchが「時間をおいて再度お試しください」を返す。
  **failure_scenario**: 区間を乗り換えて目的地に届かない列を組むと、利用者は「時間をおいて再試行」を案内され、何度やっても同じ結果になる。原因はサーバーログにしかない。
  **recommendation**: `RoutingError`を捕捉して`last_no_candidates_reason`へ入れ空リストを返す。

- **file**: `backend/app/services/axis_preview_service.py` **line**: 89
  **category**: レジストリの1本道が下流へ伝播していない（構造仕様8） **severity**: P2
  **summary**: T887が`WIRED_LANDCOVER_KEYS`を正本にしたが、分布プレビューの母集団だけは2クラスを名指ししたままで、クラスを増やしても届かない。
  **evidence**: `road_graph_repository.py:744-763`の`WayMaterialSampleRow`が2フィールドのみ、`_SAMPLE_WAY_MATERIALS_SQL`（`:777-778`）も2列のみ、`sample_way_rows`（`:2370-2384`）も同様／評価経路側はT887で統一済み。
  **failure_scenario**: P0を直しても、`crops_percent`等を材料に使う軸を作ると分布プレビューだけ「値なし」になり、折れ点を当てる根拠が出ない。
  **recommendation**: `WayMaterialSampleRow`とSQLの列を`WIRED_LANDCOVER_KEYS`から組み立てる。

- **file**: `backend/app/services/graph_service.py` **line**: 99
  **category**: 無効化の抜け（再splitと材料キャッシュ） **severity**: P3
  **summary**: `_maybe_warm_tile_cache`はキャッシュ済みのタイルを飛ばすため、再split直後でもそのタイルの材料キャッシュは更新されない。
  **evidence**: `:103`が`get_tile_materials(...) is not None`のタイルを`continue`／`graph_material_cache`にタイル単位の無効化APIは無い／`_ensure_lazy_graph_consistent`は両方が同じ古いタイルキャッシュ由来なら整合して見える。
  **recommendation**: 再split後に該当z12タイルのエントリを捨てる。

- **file**: `backend/app/services/derived_data_revision_service.py` **line**: 33
  **category**: 重複した仕組み **severity**: P3
  **summary**: `force`引数の本番呼び出し元が0件で、テストからしか使われない。同じことは`reset_for_tests()`でできる。
  **evidence**: `force=True`はgrepで`tests/test_derived_data_revision_service.py`の3箇所のみ／`tests/test_graph_service.py:547,556,561`は`reset_for_tests()`で同じ効果を得ている／docstring（`:38`）が呼び出し元を数え上げている。
  **recommendation**: `force`を撤去して`reset_for_tests()`へ寄せる。

- **file**: `backend/app/services/road_graph_engine.py` **line**: 2091
  **category**: 表示値の二重計算（前回P2の未解消） **severity**: P3
  **summary**: 候補の所要時間は走行モデルから求めるのに、区間の到達予想時刻だけが仮定巡航速度の割り算のまま。
  **evidence**: `_estimate_duration_seconds`（`:1958-1980`）は`leg.travel_seconds_full`とターンの秒を積む／`_build_segment_details`（`:2091`）は`elapsed_hours = cumulative_km / self._assumed_speed_kmh`／`preview_segment`のコメント（`:1045-1047`）も事実に反したまま。
  **recommendation**: 到達予想時刻もレグ配列の累積から作る。

### consistency

- **file**: `backend/tests/test_axis_preview_service.py` **line**: 1
  **category**: 実装↔テスト（変更の効きを一度も通らない） **severity**: P1
  **summary**: 分布プレビューのテストが純関数だけを見ており、ルーター側のテストは分布関数そのものをmonkeypatchするため、`load_way_sample`は全スイートで一度も実行されない。上のP0が1,984件greenのまま通過した直接の理由。
  **evidence**: `test_axis_preview_service.py`がimportするのは`HISTOGRAM_BINS`・`_distribution`・`_raw_value`だけ／`test_axis_distribution_routes.py:78,119,133`が分布関数を丸ごと差し替える／`load_way_sample`の実行経路は`axis_preview_service`自身と`scripts/measure_axis_saturation.py:75`のみ／T887のコミットメッセージは「テストを1件も変更せずに1,984件が通った」を効いている根拠に挙げているが、この経路は母集団に入っていない。
  **recommendation**: Fakeリポジトリの`sample_way_rows`から`load_way_sample`を1回通すテストを足す。ルーター側のmonkeypatchはHTTP層の検査として残してよいが、それだけを根拠にしない。

- **file**: `backend/app/domain/axis_inspector.py` **line**: 141
  **category**: 撤去済み軸の名指しが残る／検知器の母集団が狭い（シャード横断） **severity**: P2
  **summary**: T885が廃止した軸を、日本語ラベル「開放度」で名指しする記述が実装・docs・frontend・testsに残っている。検知器は軸**id**の綴りしか見ないため1件も検出しない。
  **evidence**: T885.mdは「`openness`を名指ししていた3箇所から名前を外した」と記録（ASCII idのみをgrep）／現行コードに残る「開放度」: `domain/axis_inspector.py:141`・`domain/axis_display.py:234`・`infrastructure/road_graph_models.py:265`・`road_graph_repository.py:810,2389`・`frontend/src/components/Map/MapView.tsx:196`・`primaryAttributes.ts:64`・`tests/`5ファイル／`docs/architecture.md:1057`は表の1行として現役の軸のように載せる／検知器`find_removed_axis_mentions`（`review_checks.py:1741`）の母集団は`axis_id="…"`とスナップショット履歴で、ラベルは対象外。
  **recommendation**: 撤去済み軸の**ラベル**もスナップショット履歴から導いて母集団へ入れる（`label="開放度"`はスナップショットに入っている）。

- **file**: `backend/app/services/road_graph_engine.py` **line**: 280
  **category**: docstringが述べる契約と実装の不一致 **severity**: P2
  **summary**: `_LegCostComposer`のクラスdocstringが「風に依存する公開軸の重みが0ならスナップショット1本」と述べるが、実装は重みを一切見ない。28行下のコメントが逆のことを書いている。
  **evidence**: クラスdocstring（`:276-281`）／実装は`self.time_varying = wind_series is not None`（`:342`）のみ／直前のコメント（`:339-341`）は「風の時別系列があれば**常に**時変化合成する」／`__init__`の`lens_axis_id`の説明（`:695-697`）も事実に反する——読み手は`_build_segment_details`の`_active_material_ids`（`:2031`）1箇所だけ。
  **recommendation**: クラスdocstringを`:339-341`へそろえ、`lens_axis_id`の説明を「区間表示の材料選択に使う」へ直す。

- **file**: `docs/modules/backend/routing-engine.md` **line**: 317
  **category**: docsが縮退の条件を言い切れていない **severity**: P2
  **summary**: 信号有無・最大階級の既定値を「バッチ未実行のDB」の話としてだけ説明しており、split鮮度が古い再構築経路ではバッチ実行済みでも常に既定値になることが書かれていない。
  **evidence**: `routing-engine.md:317-320`／`road_graph_engine.py:2301-2302`の同文docstring／実際は`build_road_graph`が設定しない。
  **recommendation**: 実装を直すか、「どちらの構築経路を通ったかで変わる」ことを両方へ書く。

- **file**: `backend/app/services/tile_serving.py` **line**: 1
  **category**: 消費者の数え上げが陳腐化 **severity**: P3
  **summary**: 骨格モジュールのdocstringが利用者を「路面/POI/事故」と列挙しており、今回追加された土地被覆が入っていない。同型が2箇所。
  **evidence**: `tile_serving.py:1`・`:4-5`／`api/routers/_tile_http.py:1-3`／`docs/modules/backend/static-road-attributes.md:308-311`。
  **recommendation**: 「タイル種別に依らず共有する」という性質の記述へ置き換える。

- **file**: `backend/app/services/tile_serving.py` **line**: 55
  **category**: 既定値が特定の実装を名乗る **severity**: P3
  **summary**: `source_label`の既定が`"postgis"`で、コメントは「呼び出し元が名乗る」と言うのに、名乗らなかった呼び出し元は黙ってpostgisを名乗る。
  **evidence**: `:55`の既定値と`:80-82`のコメント。
  **failure_scenario**: PostGIS以外を読む3つ目のタイル種別を足したとき、`/api/debug/stats`の内訳が黙ってpostgisへ計上される。
  **recommendation**: キーワード必須（既定なし）にする。

- **file**: `backend/app/services/axis_preview_service.py` **line**: 167
  **category**: DB由来の要素をコードコメントで数え上げ **severity**: P3
  **summary**: 「生値が負になる軸」としてDBの行データである軸idを列挙しており、軸が増減するたび嘘になる。実際T885で手作業の修正が要った。
  **evidence**: `:167-168`／T885の差分でこの行から`openness`が手で外されている。
  **recommendation**: 性質だけ残して例示を消す。

- **file**: `backend/app/services/road_graph_engine.py` **line**: 1765
  **category**: バリデーションの抜け・テスト未整備 **severity**: P3
  **summary**: 終点チェックは`find_nearest_node_indexed`がNoneを返したとき黙って素通りする。
  **evidence**: `:1765-1771`の条件／`tests/test_road_graph_engine.py:2999-3030`は3件を持つがスナップできない場合は無い。
  **recommendation**: スナップできない`destination`は`RoutingError`にするか、素通りさせる理由をdocstringへ書く。

### Regression（前回シャードS3の指摘）

- **O-1（P0、世代ガードが本来の経路に無い）: 解消を確認。** `ensure_caches_match_db`は`get_search_materials_for_bbox`の先頭（`graph_service.py:332`）へ移り、材料ディスクキャッシュを読む全経路が手前で通る。`region_service._build_graph_for_tile_background`は材料ディスクキャッシュを読まないため外れていて正しい。テスト2件（`test_graph_service.py:545-566`）が呼び出しと破棄の発火を固定。
- **C-1（P1、4者乖離）: 解消。** `force`のdocstringから実在しない`main.py` lifespanの記述が消え、テストが経路を検査している。
- **未解消**: O-3（到達予想時刻の二重計算）、O-4（合成ルートの失敗理由の握り潰し／今回さらに悪化）、O-5（`compose_leg_costs`のログキーの型が経路で変わる）、O-6（`evaluation_service.py`の残骸）、infrastructure側O-1（`search_graph_cache`が世代破棄に連動しない）。

---

## シャードD: backend/app/infrastructure

対象: road_graph_repository.py / road_graph_models.py / material_coverage.py /
derived_data_freshness.py / landcover_raster.py / graph_material_cache.py / cache_identity.py

### overall

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 743-763, 2370-2385
  **category**: 契約不一致（呼び出し元との引数個数ずれ）/ 残骸 **severity**: P0
  **summary**: `WayMaterialSampleRow`が`trees_percent`/`built_percent`の2フィールドを別々に持ったままのため、呼び出し元が`way_scalar_materials`へ8引数を渡し、軸スタジオの分布プレビューが必ず`TypeError`で落ちる（シャードCのP0と同一事象を別方向から検出）。
  **evidence**: `:760-761`が2フィールドを独立に持ち`:2380-2381`で詰める／`axis_preview_service.py:89-92`が8つの位置引数を渡す／`domain/axis_inspector.py:65-73`のシグネチャはT887で7つ／対象コミットで実行して確認: `TypeError: way_scalar_materials() takes from 5 to 7 positional arguments but 8 were given`／T881が`row.curvature_deg_per_km`を1つ落とし、T887がパラメータを1つ減らしたため差し引き1つ余っている。
  **failure_scenario**: `POST /api/admin/axis-definitions/preview-distribution`と`GET /api/admin/material-catalog/{material_id}/distribution`が500。`_guard_db_errors`は`DBAPIError`しか捕まえないので503にも化けず素の500。`scripts/measure_axis_saturation.py:75`も同じ。軸の形を決める作業（現フェーズの主業務）が止まる。
  **recommendation**: `WayMaterialSampleRow`側を`landcover_percents: dict[str, float|None]`1フィールドへ寄せて`WIRED_LANDCOVER_KEYS`から導く。

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 760-761, 777-778
  **category**: 導出漏れ（構造仕様12） **severity**: P2
  **summary**: 隣接する土地被覆の焼き込み列は`WIRED_LANDCOVER_KEYS`から導いているのに、軸スタジオ標本のSQLと行dataclassだけが2クラスを手書きで残している。
  **evidence**: `:298-307`の`_LANDCOVER_TILE_COLUMNS_SQL`は並びから組み立て、コメントに「手で並べると…静かに空になる」と明記／`:2561`・`:2604`、`material_coverage.py:219-231`も同じ並びから導く／一方`_SAMPLE_WAY_MATERIALS_TEMPLATE`（`:777-778`）は2行だけ、`WayMaterialSampleRow`（`:760-761`）も2フィールドのまま。
  **failure_scenario**: P0を直しても、6クラスを使う軸を軸スタジオで作ると分布プレビューだけがその材料を欠損として扱う。
  **recommendation**: テンプレートの列を並びから生成し、行dataclassを1フィールドにする。

- **file**: `backend/app/infrastructure/material_coverage.py` **line**: 219-231
  **category**: スケール **severity**: P2
  **summary**: 土地被覆のカバレッジが、クラスごとに独立した相関サブクエリ（`NOT EXISTS`）を`osm_raw_ways`全行に対して並べる形で、クラスを増やすと母集団走査あたりの索引探索が線形に増える。
  **evidence**: `:219-231`が8クラスぶんの`NOT EXISTS`を生成し、`build_way_coverage_sql`（`:254-271`）が`count(*) FILTER`列として並べ`FROM osm_raw_ways AS w`を全走査／T887前は2件だった／`way_landcover`は`osm_way_id`が主キー。
  **failure_scenario**: 100万行規模に対し1行あたり8回の主キー探索。管理APIなので障害にはならないが、クラスを増やすほど遅くなり、増やす側からは見えない。
  **recommendation**: 8つの相関`NOT EXISTS`を`LEFT JOIN`1本に置き換える。

- **file**: `backend/app/infrastructure/landcover_raster.py` **line**: 146-152
  **category**: キャッシュ方針（無効化） **severity**: P2
  **summary**: タイルの中身はラスタ構成に依存するのに、その構成がタイル世代へ入っていない（シャードCのP2と同一事象）。
  **evidence**: `services/landcover_tile_service.py:24`の署名材料／`cache_identity.py:37-40`は「差し替えたとき」としか書かず追加に触れていない／`render_tile`のdocstring（`:148-151`）は追加が起こる前提で書かれている／`api/cache_policy.py:104-108`が`PERMANENT`を割り当てる／同種の問題は`way_landcover`側では`source_raster_set`列で解決済み。
  **failure_scenario**: ゾーンを足したとき、空だったタイルはブラウザに`immutable`で24時間残り、継ぎ目で一部だけ塗れていたタイルは`tile_cache`に残るため**世代を上げるまで永久に**古い絵を配る。
  **recommendation**: 構成を署名へ入れるか、`LANDCOVER_REVISION`のコメントへ「追加/削除したときも上げる」を明記する。

- **file**: `backend/app/services/landcover_tile_service.py` **line**: 29-30
  **category**: キャッシュ方針（世代の掃除） **severity**: P2
  **summary**: パスへ世代番号を埋めるディスクキャッシュを新設したが、旧世代を消す導線が無い。`tile_cache`はパスをSHA-256へ潰すため世代で絞った削除が原理的にできない。
  **evidence**: `_tile_cache_path`が`region/landcover/v{VERSION}/{z}/{x}/{y}.png`を返す／`infrastructure/tile_cache.py:15-28`の`cache_key`がパス全体をハッシュ化しフラット化するため`clear_all`以外に消す手段が無い／`docs/caching.md:306-313`は「世代番号を使うなら古い世代を削除する手段を必ず用意し、どこで呼ぶかまで決める」と定め、同`:125`で`tile_cache`を「量が小さく実害無し（11MB）」として例外扱いしている。
  **failure_scenario**: 土地被覆はz6〜z14でPNGを吐くため、現在量（11MB）とは桁の違う蓄積になりうる。世代を上げた時点で旧世代が居座り、容量上限も退避も無いためディスクが埋まるまで気づけない。
  **recommendation**: 免除条件が当てはまるかを実測し、当てはまらないなら`tile_persistent_cache`側へ寄せるか世代プレフィックスで消せる仕組みを足す。実測値を`docs/caching.md`の表へ追記する。

- **file**: `backend/app/infrastructure/landcover_raster.py` **line**: 49-59, 107-131, 158-166
  **category**: 資源管理（スレッド安全） **severity**: P3
  **summary**: `_RasterSource`のdocstringは「読み取りをロックで直列化する」と述べるが、ロックが掛かっているのは`dataset.read`の1行だけ。
  **evidence**: `:52-54`のdocstring／`with source.lock:`は`:126-127`のみ／`dataset.window`（`:113`）・`window_transform(...)`（`:128`）・`dataset.crs`（`:162`・`:171`）はロックの外／並列度は`_landcover_tile_semaphore`（既定4）まで許される。
  **failure_scenario**: 同一ラスタを覆うタイルが4本同時に来ると、`dataset.read`の最中に別スレッドが同じハンドルの属性アクセスへ入る。実害が出るなら「稀に1枚だけ壊れたタイル/例外」という再現困難な形。
  **recommendation**: dataset参照をまとめてロックの内側へ入れる。あるいはdocstringを実態に合わせ根拠を1行書く。

- **file**: `backend/app/infrastructure/landcover_raster.py` **line**: 75-87
  **category**: 資源管理（失敗の恒久化） **severity**: P3
  **summary**: ラスタを開けなかった事実がプロセス寿命のあいだ記憶され続け、再試行の導線が無い。呼び出し側の警告文は原因を「未設定」と決め打ちしている。
  **evidence**: `_open_sources`は例外時にWARNINGを出したうえで空リストでも代入し、以後開き直さない／`landcover_tile_service.py:35-42`は「未設定のため」と出す。
  **failure_scenario**: マウント遅延やパーミッションで最初の1回だけ失敗すると、原因が解消しても再起動するまで全タイルが空。ログは「未設定」と言うので運用者は`.env`を見て止まる。
  **recommendation**: 失敗したパスは記憶せず次回開き直す。警告文を「未設定、または開けなかった」に改める。

- **file**: `backend/app/infrastructure/derived_data_freshness.py` **line**: 147-161
  **category**: スケール **severity**: P3
  **summary**: `road_nodes.max_highway_rank`の未計算判定が、`road_nodes`全行に対する相関`EXISTS`（`road_edges`の2列OR）になっている。
  **evidence**: `:153-158`の`uncalculated`／`build_completeness_sql`（`:165-176`）が`FROM road_nodes`を全走査／索引は`migrations/0001:24-25`にあるためBitmapOrは効く／同ファイルの他2件は相関サブクエリを持たないか主キー1本。
  **recommendation**: `road_edges`側からUNIONして絞ったノード集合とJOINする形を検討（着手するなら本番DBで実測してから）。

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 1381-1397
  **category**: 対称性の欠落 **severity**: P3
  **summary**: `degree`には孤立ノードを0へ戻す防御SQLがあるが、同じ形で追加された`max_highway_rank`には無い。
  **evidence**: `_RESET_UNREFERENCED_NODE_DEGREES_SQL`（`:1430-1441`）が`recompute_node_degrees`（`:1455-1456`）から呼ばれる／T800で追加された`_RECOMPUTE_NODE_MAX_HIGHWAY_RANK_SQL`は`ranks`に現れないノードを更新対象外にし、対応するresetは無い。
  **failure_scenario**: 再splitでEdgeが消えて孤立したノードに以前の高い`max_highway_rank`が残る。`domain/routing.py:704-711`が`np.maximum`を取るため、残った過大な値がそのまま採用され、実在しない「上位の道を渡る待ち」が加算される。
  **recommendation**: 同種のresetを足すか、`degree`側のresetを不要と判断できるなら両方から外して理由を残す。

### consistency

- **file**: `backend/app/infrastructure/road_graph_models.py` **line**: 265
  **category**: 撤去された事実を語る周辺表現の残存 **severity**: P2
  **summary**: T885で廃止した公開軸「開放度（openness）」を、材料テーブル・SQL・docsが今も現行の軸として名指ししている。機械的な検知器はこの軸だけ構造的に見えない。
  **evidence**: シャード内 — `road_graph_models.py:265`「（開放度評価軸の材料）」、`road_graph_repository.py:810`「区間インスペクタ（開放度軸）」、`:2389`「開放度軸内訳」／シャード外 — `domain/axis_inspector.py:141`、`domain/axis_display.py:234`、`docs/modules/backend/static-road-attributes.md:13`、`docs/modules/backend/axis-studio.md:39`・`:236`、`docs/architecture.md:1057`／`backend/fixtures/axis_definitions_snapshot.json`に`openness`は0件／検知器`removed_axis_ids`（`:1733`）は`{a for a in mentioned - live if "_" in a}`でアンダースコア必須のため`openness`を母集団から落とし、`review_checks.py docs`は「0件」を返す。日本語ラベルは母集団に一切入らない。
  **failure_scenario**: 「土地被覆の材料は何のためにあるのか」を後から読む人が、存在しない軸の材料として説明された列を見て、その軸を探しに行って見つからない。検知器が0件を返し続けるため周期レビューでも拾われない。
  **recommendation**: 記述を軸に依存しない表現へ改める。あわせて`removed_axis_ids`の絞りを見直す。

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 2700-2703, 2754-2755
  **category**: コード自身が述べる契約と実装の不一致 **severity**: P2
  **summary**: ファサードが「新しいメソッドは必ず対称に委譲する」と明記しているのに、T800で追加した2メソッドだけ委譲が無く、唯一そのバッチだけが個別リポジトリを直接構築している。
  **evidence**: `RoadGraphRepository`のdocstring（`:2700-2703`）「ここへの追加は重複ではなく契約の一部」／「派生グラフ」節（`:2737-2755`）に`recompute_node_max_highway_rank`・`recompute_node_traffic_signals`（`:1458-1479`で新設）が無い／`batch/precompute_road_node_intersections.py:51,57`は`DerivedGraphRepository(session)`を直接構築、他の全バッチはファサード経由／この契約はcontext.mdの「意図的な設計判断」にもKEEPとして載っている。
  **failure_scenario**: `FakeRoadGraphRepository`でこの2メソッドを差し替えられないため、「直接構築でいい」が前例として積み上がる。
  **recommendation**: 委譲メソッドをファサードへ足しバッチを戻す。委譲しない判断ならdocstringの例外条項へ書く。

- **file**: `backend/tests/test_axis_distribution_routes.py` **line**: 76-80
  **category**: 実装↔テスト（実質的に意味のないテスト） **severity**: P2
  **summary**: 分布プレビューの2エンドポイントは「ルーター層」「計算本体」の両方にテストがあるが、その境目にある`load_way_sample`だけがどちらからも呼ばれておらず、上記P0がそこを素通りした。
  **evidence**: `test_axis_distribution_routes.py`のdocstringが分担を宣言し`:76-80`で分布関数をmonkeypatch／`test_axis_preview_service.py`の13件はいずれも`load_way_sample`を呼ばない／`grep -rn "load_way_sample" backend/tests`は0件／`sample_way_rows`のpostgisテスト（`test_road_graph_repository.py:2325-2375`）は件数とbboxの効き方しか見ていない。
  **failure_scenario**: 「ルーターは薄いので本体で見る／本体は純関数なので直接見る」という分担が、その2つをつなぐ組み立て関数を母集団から落とす。2コミットにまたがる引数個数のずれが全件greenのまま本番へ出た。
  **recommendation**: `load_way_sample`をフェイクリポジトリで1本通すテストを足す。MVTの土地被覆テスト（`test_road_graph_repository.py:2115-2147`は2列しか見ていない）も並びから回す形にする。

- **file**: `backend/app/domain/axis_inspector.py` **line**: 54-56, 83, 141
  **category**: コメントが主張する挙動と実装が逆 **severity**: P3
  **summary**: T887が全8クラスを配線した後も「材料に使うのは2クラスだけ」「8列すべてではない」という前提のコメントが残っている。
  **evidence**: `:54`・`:83`・`:141`／現在の`WIRED_LANDCOVER_KEYS`は8クラスで`road_graph_models.py:284-292`の割合列と1対1。
  **recommendation**: 3箇所を並びを指す形へ直し、個数を書かない。

- **file**: `backend/app/infrastructure/road_graph_repository.py` **line**: 2401, 2605
  **category**: 1要素が行全体の判定を代表している **severity**: P3
  **summary**: 「土地被覆の行に値があるか」を`trees_percent`1列のNULL判定で代表しているが、この代表関係を保証しているのは書き込み側の慣習だけ。
  **evidence**: `get_way_landcover`（`:2399-2413`）と`get_edge_materials_batch`（`:2603-2607`）／`LandcoverPercentages`の各フィールドは非Optional（`domain/landcover.py:36-48`）のため片方だけ非NULLだとValidationError／書き込み側（`:2216-2236`）は一括NULL/一括値にしているため現状は成り立つ。
  **recommendation**: `valid_pixels IS NULL`を判定に使うか、代表にしている理由を1行書く。

### 参考（対象コミットで確認した良い点）

- `graph_material_cache.py:44-47` — `TILE_MATERIALS_CACHE_VERSION`へ`LeanNode`/`LeanEdge`を署名材料として追加した変更は、T800の列追加にディスクキャッシュを機械的に追随させる正しい形。
- 蛇行（curvature）の撤去は残骸ゼロ。実装側のヒットは`backend/migrations/0035/0036/0042`（履歴として残すSQL）と`docs/tasks/`のみ。
- タイル世代の対上げは正しく行われている（`region-tile-config.json`の`road_surface`が更新され、`landcover`が新規追加。土地被覆の焼き込み列がSQLの署名に入るため自動で動いた）。

---

## シャードF: frontend Map（MapView本体・ルート描画抽出）

対象: MapView.tsx / MapView.routes.ts / MapView.bench.ts / mapStyleOps.ts

### overall

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 2668
  **category**: 構造仕様違反 / 描画順の暗黙依存（T886で新規に顕在化） **severity**: P2
  **summary**: 面ラスタのうち`elevation`だけがハードコードのkey文字列で路面ソースより前へホイストされており、同じ性質の`landcover`が漏れた結果、初回表示では土地被覆ラスタが路面の線レイヤーの「上」に、再描画後は「下」に来る。
  **evidence**: `MapView.tsx:2668-2670`が`staticOverlayLayers.find((layer) => layer.key === "elevation")?.ensure(map)` → `ensureRoadSurfaceTileLayer(map)` → `ensureAllStaticOverlayLayers(...)`の順。直前の`:2660-2663`が「標高を先に単独ensureしてから路面ソースを作ることで『標高が最背面、その上に路面』の意図を保つ」と明記／`:1476-1479`の`buildStaticOverlayLayers`の配列は`elevation`→`landcover`→`axisOverlayLayers`…の順で、`landcover`のensure（`:420-440`）は3行目で初めて呼ばれる／`ensureRoadSurfaceTileLayer`（`:1011-1057`）はその前に3線レイヤーを追加済みで、`addLayer`はbeforeId省略で最上位へ積む（`:1456-1458`が「配列の並び順がそのままensure()呼び出し順＝描画の重なり順になる」と述べる）／再描画経路（`redrawAllLayers:2141`→`setStaticOverlayVisibility:1597-1608`）はループ内で`landcover`→ramp軸の順にensureし、ramp軸のensure（`:1389-1393`）が`ensureRoadSurfaceTileLayer`を呼ぶため順序が入れ替わる／`LANDCOVER_TILE_MIN_ZOOM=6`・初期ズーム13（`:2610`）・`AREA_LAYER_OPACITY=0.32`（`:232`）のため既定ズームで重なる／docs側の正（`docs/modules/frontend/static-map-layers.md:72-91`）はelevation→landcover→axisOverlayLayersの順。
  **failure_scenario**: 「土地被覆」と「路面の種類」を同時にONにすると、初回表示では路面の色分け線・クリック強調が32%のラスタ越しに濁って見える。「地図の表示を再描画」を押した瞬間だけ線が鮮明になり、同じ操作でも見え方が変わる。
  **recommendation**: ensure呼び出し順に重なり順を委ねるのをやめ、配列から`beforeId`を導いて`addLayer`へ渡す。重いなら少なくとも「背景の面レイヤー」の集合を`key`のハードコードではなく記述子の性質から導いてホイストする（構造仕様12）。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 1239
  **category**: 同種のガードが一部のレイヤーにしか無い / 暗黙の順序依存 **severity**: P2
  **summary**: 路面ソースを共有する3つのensureファクトリのうち、`makeEnsureAttributeLineLayer`（designation/tunnel/oneway）だけが`ensureRoadSurfaceTileLayer`を呼ばず、ソースの存在を呼び出し順に依存している。
  **evidence**: `:1239-1267`が`source: ROAD_TILE_SOURCE_ID`を参照するが`ensureRoadSurfaceTileLayer`を呼ばない／兄弟は両方呼ぶ（`:1077`・`:1389-1393`）。後者のコメントは「順序に頼るとそのときだけレイヤーが落ち、その軸の色分けが戻らない」と理由まで明記／初回だけは`:2669`の明示呼び出しで救われるが、再描画経路にその1行は無い／designationのensureより前に路面ソースを作るのは`buildStaticOverlayLayers:1480`の`...axisOverlayLayers`だけで、`rampAxes`が空なら誰も作らない。
  **failure_scenario**: 公開ramp軸が0件の状態（全ramp軸unpublish直後、axis-catalogフェッチ失敗時のフォールバックが空等）で「地図の表示を再描画」を押すと、designation/tunnel/onewayのaddLayerが`source "region-road-surface-tiles" not found`になる。
  **recommendation**: `makeEnsureAttributeLineLayer`の`applyData`先頭で`ensureRoadSurfaceTileLayer(map)`を呼び3ファクトリを対称にする。ramp側にある同型テストを1件足して、外すと落ちることを確認する。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 194
  **category**: 残骸（撤去済み軸の名指し）＋コメント方針違反 **severity**: P2
  **summary**: `ROAD_TILE_ATTRIBUTION`のコメントが、T885で廃止された「開放度軸」をタスク番号つきで現存物として名指ししている。
  **evidence**: `:194-197`「Esri×Impact Observatory×Microsoft（土地被覆、開放度軸[T624]）の4系統が混在するため」／撤去は`c549a3da`／同種が`primaryAttributes.ts:62-64`にも／CLAUDE.md「コメント方針」は経緯（Txxx）を禁じるが、この行は`--since`の対象外で素通り。
  **recommendation**: 「開放度軸[T624]」を落として「土地被覆（way_landcover／土地被覆ラスタの出典）」に改める。同一コミットで`primaryAttributes.ts:62-64`も直す。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 2033
  **category**: 責務混在（抽出の線が通っていない） **severity**: P3
  **summary**: `applySpliceLayerVisibility`だけが`MapView.tsx`に残り、同じ責務の`applyRouteLayerVisibility`は`MapView.routes.ts`にある。
  **evidence**: `:2033-2055`が使うのは`MapView.routes.ts`からimportした4関数だけで`MapView.tsx`側の値を参照しない／対になる`MapView.routes.ts:366-388`は同じ形／`docs/tasks/T877.md:54`は乗り換え帯を`MapView.routes.ts`の管轄と定義。
  **recommendation**: `applySpliceLayerVisibility`を`MapView.routes.ts`へ移す。

- **file**: `frontend/src/components/Map/MapView.routes.ts` **line**: 41
  **category**: 公開面を絞らずに抽出した（消費者ゼロのexport） **severity**: P3
  **summary**: 抽出先モジュールのexportのうち4つは、テストを含めて外部の消費者が1件も無い。
  **evidence**: 参照0件は`DETAIL_SOURCE_ID`（:41）・`SPLICE_COLOR`（:196）・`ensureRouteArrowLayer`（:402）・`keepRouteArrowsAboveDetailSegments`（:445）／`docs/tasks/T877.md`自身が「抽出した側の内部で完結する」と書く／`MapView.tsx`側は「exportはテスト専用」を都度明示する規約だが、`MapView.routes.ts`でその注記は2つだけ。
  **recommendation**: 4件のexportを外す。残すexportには同じ注記を揃える。

- **file**: `frontend/src/components/Map/MapView.routes.ts` **line**: 144
  **category**: 重複（抽出で1ファイルに集まって可視化された写経） **severity**: P3
  **summary**: 6つの`draw*`関数が同一骨格を各25〜35行で繰り返している。
  **evidence**: `drawBaseRoutes`(:144)・`drawSpliceStretches`(:231)・`drawSplicedRoute`(:269)・`drawSelectedOutline`(:324)・`drawExperimentSlots`(:457)・`drawDetailSegments`(:513)と対の`hide*`／`:184-186`と`:348-349`が同じ規則を各所で再掲／`drawExperimentSlots`だけsetData後に早期returnしvisibilityを明示しない非対称（:470-472）。
  **recommendation**: `{sourceId, data, layerSpecs[]}`を受ける汎用関数へ寄せられるか検討。寄せないなら`drawExperimentSlots`の非対称だけでも揃える。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 198
  **category**: 重複（同一文字列の二重定義） **severity**: P3
  **summary**: 土地被覆の帰属表示の文字列が`ROAD_TILE_ATTRIBUTION`の一部と`LANDCOVER_ATTRIBUTION`に逐語で2度書かれている。
  **evidence**: `:201`と`:240`が完全一致／`:237-238`のコメントはソースが別である理由だけを書き、文字列を共有しない理由には触れていない。
  **recommendation**: `LANDCOVER_ATTRIBUTION`を`ROAD_TILE_ATTRIBUTION`が連結する形にする。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 1256
  **category**: 前回レビュー指摘の未解消（Regression） **severity**: P3
  **summary**: 2026-09-15のS5 O-6・O-7が指摘したP3が2件とも残り、improvement-plan.mdにも起票されていない。
  **evidence**: O-6: `:1256` `"line-width": 3,`（このファクトリだけ`DEFAULT_ROAD_LINE_WIDTH`を使わない直値）／O-7: `:293-294`の`DEFAULT_ROAD_LINE_OPACITY`（コメント自身が「実運用では通らない」と書くフォールバック）と`:1189`／T870〜T888に対応する行は無い。
  **recommendation**: 1行ずつ直すか、「直さない」と決めて判断を残す。

### consistency

- **file**: `docs/modules/frontend/map-axis-coloring.md` **line**: 125
  **category**: docs↔実装の乖離（T877の移動に追従していない） **severity**: P2
  **summary**: T877で`MapView.routes.ts`へ移った関数を、モジュール文書2本がいまも`MapView.tsx`の所有物として名指ししている。
  **evidence**: `map-axis-coloring.md:125`が`MapView.tsx: drawDetailSegments`・`keepRouteArrowsAboveDetailSegments`を挙げるが実体は`MapView.routes.ts:513`・`:445`／`route-settings-and-results.md:32`は見出しが`MapView.tsx`で本文が`drawSpliceStretches`等（実体は`MapView.routes.ts:231/:309/:211`）、同じ表の`:33`に既に`MapView.routes.ts`の行が別途ある／`find_undocumented_files`は「どこかに載っているか」しか見ないためこの型は機械検査を通る。
  **recommendation**: 2箇所のファイル名を直し、`route-settings-and-results.md:32`の記述を`:33`へ畳む。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 1575
  **category**: コードが述べる契約と実装の不一致 **severity**: P2
  **summary**: `buildInteractiveLayerIds`のdocstringは「handleClickとhandleMouseMoveが同じ一覧を参照しないと『ポップアップは出るがカーソルが変わらない』非対称な劣化になる」と宣言するが、クリックを受け付ける2レイヤーがその一覧に入っていないため、まさにその非対称が現に存在する。
  **evidence**: `:1584-1591`の一覧は`DETAIL_HIT_LAYER_ID`・`ROAD_TILE_LAYER_ID`・`ROAD_TYPE_LAYER_ID`＋`interactive:true`のオーバーレイ／クリックはlayer-scopedで3枚に登録（`:2946-2948`: `DETAIL_HIT_LAYER_ID`・`ROUTES_HIT_LAYER_ID`・`SPLICE_HIT_LAYER_ID`）で後2者は一覧に無い／カーソルを変える`handleMouseMove`（`:2787-2795`）も同じrefを読む／`mouseenter`/`mouseleave`は0件。
  **failure_scenario**: デスクトップで未選択の候補線・乗り換え帯の上へマウスを置いてもカーソルが矢印のままで、クリックできることが分からない。
  **recommendation**: 「layer-scopedクリックを持つレイヤー」を1配列から導き、登録・ガード・`buildInteractiveLayerIds`の3つが同じ配列を読む形にする。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 1872
  **category**: 撤去済み仕様を語る記述の残存（前回O-3と同型の別箇所） **severity**: P2
  **summary**: `MapViewProps.showRoadType`のdocstringが「太さ・線種で反映」「物理描画はshowRoadSurfaceと同じ線レイヤーへ合成される」と述べるが、実装は独立レイヤー＋共通の固定太さ。
  **evidence**: `:1872-1874`／実装は`ROAD_TYPE_LAYER_ID`という独立レイヤー（`:270`）で`applyRoadLayerState`（`:1167-1198`）が両レイヤーへ`DEFAULT_ROAD_LINE_WIDTH`を一律設定／`roadFilterAxes.ts:21`・`static-map-layers.md:93-97`も独立レイヤーと明記／前回S5 O-3が`mapLayers.ts:211-229`の同じ主張を指摘済みで、そちらも未修正。
  **recommendation**: `:1872-1874`を実態へ直し、同一コミットで`mapLayers.ts`側も掃く。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 1936
  **category**: 数え上げ＋存在しない要素の名指し **severity**: P3
  **summary**: `staticLegendHiddenKeysByAxis`のdocstringが絞り込み軸を列挙しているが、存在しない「自転車インフラ」を挙げ、実在するtunnel/oneway/supplyPoiを落としている。
  **evidence**: `:1936-1939`の列挙／実際の`buildStaticFilterAxes`（`staticAttributeLayers.ts:352-374`）はdesignation/tunnel/oneway/stopPoi/supplyPoi/accidentParty/accidentSeverity＋ramp軸ぶん／自転車インフラは同ファイル`:1877-1879`が自ら「専用レイヤーを持たない」と書く。
  **recommendation**: 列挙をやめ「`buildStaticFilterAxes`が返す軸ぶん」とだけ書く。

- **file**: `frontend/src/components/Map/MapView.tsx` **line**: 2695
  **category**: 手書きの母集団が2箇所に分かれている **severity**: P3
  **summary**: 「layer-scopedクリックハンドラを持つレイヤー」が、ガード側と登録側で別々に手書き列挙されている。
  **evidence**: `:2695`のガード配列と`:2946-2948`の登録、`:2970-2972`の解除の3箇所が同じ集合を独立に持つ。
  **recommendation**: `{layerId, handler}`の1配列から3つを導く。上のC-2も同時に閉じる。

- **file**: `frontend/src/components/Map/MapView.routes.test.ts` **line**: 119
  **category**: テストの足場の重複 **severity**: P3
  **summary**: `fakeMap`が同ディレクトリの4テストファイルで独立に定義され、redraw検証の追加のたびに各コピーがMapLibreの部分再実装へ肥大している。
  **evidence**: `duplicate_test_scaffold`が参考1件として出し続けている／`MapView.routes.test.ts:119-152`のコピーは`fitBounds`/`getZoom`/`getCanvas`/`setFilter`/`setFeatureState`/`removeFeatureState`まで持つ／`docs/tasks/T884.md`の残作業はbackend 2ファイルと`vi.mock`前置きだけでこの4件を射程に入れていない。
  **recommendation**: `frontend/src/testing/`へ1つに寄せる。T884の残作業へ足すか別Txxxへ起票する。

### 参考（確認事項）

- `scripts/review_checks.py docs`はフル実行で違反なし。`map_redraw_coverage`も0件で、T886が足した`landcover`は`redrawAllLayers`から辿れている（上記O-1は到達性ではなく重なり順の問題で、この検知器の射程外）。
- 土地被覆レイヤーの兄弟（標高図）との揃い具合は、**重なり順以外は抜けなし**（attribution・minzoom/maxzoom・データ状態レジストリ・`interactive:false`・読み取り専用凡例・ズーム範囲外の案内）。
- T888の射程は妥当（`showLandcover`という名前だけで`MapView.tsx`に12箇所＋key`landcover`2箇所＋`page.tsx`2箇所＋記述子。本文の「10箇所以上」は実測と一致）。ただしT888の本文は**描画順をensure呼び出し順に委ねている構造には触れていない**。
- T877の抽出そのものは責務の線で切れている（状態なし関数群・importの向き不変・テストも分離済み）。上記O-4/O-5は「線は正しいが端の始末が残っている」型。
- 構造仕様2・3（軸ごとの専用分岐）の新設は本シャードの変更範囲に無い。

---

## シャードG: 地図レイヤーカタログ・チップUI

対象: mapLayers.ts / landcoverClasses.ts / RoadInspectorPopup.tsx / primaryAttributes.ts /
icons.tsx / MapOverlayControls.tsx / MapOverlayControls.module.css / RideConditionBar.tsx

### overall

- **file**: `frontend/src/components/Map/primaryAttributes.ts` **line**: 61-64, 67-77
  **category**: 残骸 / 未配線 **severity**: P1
  **summary**: 撤去済みの「開放度軸」を前提にしたコメントが残り、そのうえ「landcoverは専用レイヤーを持たない」という記述がT886で偽になっているのに、`landcover`が`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`側に据え置かれている。
  **evidence**: `:62-64`の記述／同`:76`の`"landcover"`が`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`に在籍／`mapLayers.ts:37,211-222`に`landcover`の`MapLayerId`と記述子が存在／`PRIMARY_ATTRIBUTE_LAYER_IDS`（同:44-54）に`landcover`キーは無い／ドリフト検知テスト`primaryAttributes.test.ts:18-26`は「対応表に無い」「両方にある」だけを見るため、同名`MapLayerId`の存在は検査しない。
  **failure_scenario**: T885の「作り直すとき」に`trees_percent`単独の軸を公開すると、レンズ表示時に`page.tsx:675-686`の下敷き判定が`primaryAttributeIdsToLayerIds(["landcover"])`から空配列を受け取り、土地被覆レイヤーをONにしていても二次軸が下敷き表現に切り替わらない。原因がこのカタログの1行であることは画面からは辿れない。
  **recommendation**: `landcover`を`PRIMARY_ATTRIBUTE_LAYER_IDS`側へ移し、コメントから開放度軸の記述を落とす。「`MapLayerId`に同名のレイヤーがあるのに`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`にいる」をドリフト検知テストの3つ目の条件として足す。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.tsx` **line**: 135-156
  **category**: カタログ集約違反（軸側と静的レイヤー側で機構が別） **severity**: P3
  **summary**: レイヤーid→アイコンの対応表だけがコンポーネント内の手書きRecordで、軸側には`icon_id`→パレットのデータ駆動機構があるのに共有していない。
  **evidence**: `:135-156`の`LAYER_ICONS`（T886は`:34`のimportと`:137`の1行を追加）／軸側は`axisIconPalette.tsx:40`の`AXIS_ICON_PALETTE`と`:56`の`axisIconFor(iconId)`で軸自身のデータから解決／`mapLayers.ts`はReactを一切importしない`.ts`。
  **recommendation**: `MapLayerDescriptor`へ`iconId`を持たせ、静的レイヤー用の辞書で引く。先送りするならmapLayers.ts側のコメントへ「アイコンはMapOverlayControls側に持つ」を明記して追加点の一覧を実態へ揃える。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.tsx` **line**: 148-153
  **category**: 残骸 **severity**: P3
  **summary**: `LAYER_ICONS`の中に、既に存在しない「勾配の環境グループ面表示」のエントリを説明する孤立コメントが残っている。
  **evidence**: `:148-151`のコメントに該当キーが無く、`MapLayerId`（mapLayers.ts:35-64）にも勾配の面レイヤーは無い／同じ痕跡が`page.tsx:204`にも。
  **recommendation**: 2箇所とも削除する。

- **file**: `frontend/src/components/Map/icons.tsx` **line**: 455-459
  **category**: 残骸（docコメントの宛先ずれ） **severity**: P3
  **summary**: 「ゴミ箱、バツ印を使わない」というdocコメントが`RouteSpliceIcon`の直前に積まれ、本来の対象`ClearRoutesIcon`は無説明になっている。
  **evidence**: `:455-456`のdocブロックの直後に`:457-459`の別docブロックが続き`:460`が`RouteSpliceIcon`／ゴミ箱の実体は`:564`の`ClearRoutesIcon`。
  **recommendation**: docブロックを`ClearRoutesIcon`の直前へ移す。

- **file**: `frontend/src/app/page.tsx` **line**: 1204-1207
  **category**: 専用分岐の新設（汎用化の取りこぼし） **severity**: P3
  **summary**: 土地被覆のズーム不足案内が、道路レイヤー側と同じ文言・同じ役目のまま、別の手書き三項として増えた。
  **evidence**: `page.tsx:1204-1207`／`:1088-1090`（道路軸側は`ROAD_FILTER_AXES`を走査する形で「軸を名指しして同じ形のブロックを並べない」と`:1080-1082`が明記）／`MapLayerDescriptor`（mapLayers.ts:157-187）は最小ズームを持たない。
  **recommendation**: `MapLayerDescriptor`へ`minZoom`を持たせ、summary生成側で一律に判定する。

- **file**: `frontend/src/components/Map/mapLayers.ts` **line**: 16-21
  **category**: 数え上げ（メンテ必須のコメント） **severity**: P3
  **summary**: カテゴリ説明のコメントが各カテゴリの所属レイヤーを列挙しており、T886で実際に書き換えが必要になった。
  **evidence**: `:19`がT886差分で「terrain（地形）: 標高図」→「terrain（地形・土地）: 標高図・土地被覆」へ変更されている／`:17-21`の他カテゴリも同じ形。
  **recommendation**: 各カテゴリは「何を束ねるか」だけにし、所属の列挙は落とす。

### consistency

- **file**: `frontend/src/components/Map/primaryAttributes.ts` **line**: 64
  **category**: 撤去済み事実の残存（検知器の母集団漏れ） **severity**: P1
  **summary**: T885で削除した軸`openness`（開放度）が現行docs・実装コメントの複数箇所に「今ある軸」として残っており、専用の検知器`removed_axis_mentions`が構造的にこれを見られない。
  **evidence**: 残存箇所——`primaryAttributes.ts:64`／`MapView.tsx:196`／`docs/architecture.md:1057`の軸一覧表の行／`docs/modules/backend/axis-studio.md:39`／`backend/app/domain/axis_display.py:234`・`axis_inspector.py:141`・`infrastructure/road_graph_models.py:265`・`road_graph_repository.py:810,2389`。`axis-catalog.json`・`axis_definitions_snapshot.json`のどちらにも`openness`は0件／検知器`scripts/review_checks.py:1733`の`if "_" in a`がアンダースコアを含まないidを母集団から除外／同時期に撤去した`curvature`は`frontend/src`・`backend/app`・`docs`に0件（手で消されている）。
  **failure_scenario**: architecture.mdの軸表とaxis-studio.mdを読んだ人が、存在しない軸の`shape_params`を前提に「負の重みだけの軸」の扱いを設計する。`curvature`が0件で`openness`が9箇所という差は手作業の当たり外れで生まれており、次の軸削除でも同じ確率で取り残される。
  **recommendation**: `removed_axis_ids`の`"_" in a`フィルタを、単語idを誤検知しない別の絞り込みへ置き換える。緩和を外す前に既知の1件が検知されることと誤検知の実測件数をタスクへ書く。残存9箇所の掃除は同じ検知器が0件を返すことを完了条件にする。

- **file**: `frontend/src/components/Map/mapLayers.ts` **line**: 3-8
  **category**: コードが述べる契約と実装の不一致 **severity**: P2
  **summary**: 冒頭の「レイヤー追加手順」が、同じ仕組みを説明する`MapOverlayControls.tsx`のコメントとも、T886の実作業とも食い違う。
  **evidence**: `mapLayers.ts:3-8`の3手順／`MapOverlayControls.tsx:636-639`は「レイヤーが増えてもここは変更不要」と書く／T886が実際に触ったのは記述子（mapLayers.ts:211）・`page.tsx:188`（初期値）・`page.tsx:266`と`:1213`（凡例、MapOverlayControlsではない）・`page.tsx:1204`（サマリ）・`MapOverlayControls.tsx:34,137`（アイコン、手順に無い）・`MapView.tsx:422-435`。
  **failure_scenario**: 手順どおり進めた人が`MapOverlayControls`の▶パネルに凡例の置き場を探して見つけられず（実際は`page.tsx`の`legendDetailsByLayerId`）、手順に無い`LAYER_ICONS`の追加はコンパイルエラーで初めて気づく。
  **recommendation**: 手順を実態へ直すか、`minZoom`・`iconId`を記述子へ持たせて手順そのものを短くする。記述は片方に残し、もう片方は参照だけにする。

- **file**: `frontend/src/components/Map/RoadInspectorPopup.tsx` **line**: 112-113
  **category**: 数え上げ **severity**: P3
  **summary**: 「8クラスは合計100%になる」というコメントが、クラス数を生成物から受け取る設計と噛み合っていない。
  **evidence**: `:112-113`／`landcoverClasses.ts:18`は生成物の全件をそのまま読む（件数を持たない）。
  **recommendation**: 「クラスの割合は合計100%になるため」とし件数を落とす。

- **file**: `frontend/src/components/Map/RoadInspectorPopup.tsx` **line**: 117-119
  **category**: 型の契約をフロント側で外している **severity**: P3
  **summary**: 生成物の`percent_field`をOpenAPI型へ二重キャストで突き合わせており、対応が崩れてもフロント側では何も落ちない。
  **evidence**: `:119` `value: landcover[cls.percentField as keyof typeof landcover] as number`／対応の保証はbackend側の`test_landcover_tile.py:87-88`にある。
  **failure_scenario**: backend側のモデルとレジストリのどちらかだけを変えた状態で生成物を更新すると、該当クラスの`value`が`undefined`になり`>= 0.5`のフィルタに落ちて行が黙って消える。
  **recommendation**: `percentField`を`keyof components["schemas"]["LandcoverPercentages"]`として型付けし、tscでも検査する。

- **file**: `docs/modules/frontend/static-map-layers.md` **line**: 5-7
  **category**: docsと実装の乖離（数え上げの副作用） **severity**: P3
  **summary**: 責務の一文が対象レイヤーを列挙しており、土地被覆・標高図（ラスタ面レイヤー）が入っていない。
  **evidence**: `:5-7`の列挙／同ファイルの対象ファイル表（:21）と描画順（:81）には`landcover`が入っている。
  **recommendation**: 責務は性質で書き、列挙は対象ファイル表に任せる。

- **file**: `docs/tasks/T873.md` **line**: 52
  **category**: 完了時に本文へ残った未実施項目 **severity**: P3
  **summary**: 対応方針の1項目（共有時刻の丸め）が実施も判断の明文化もされないまま、タスクが完了扱いになっている。
  **evidence**: `T873.md:52`「`setDynamicLayerTargetTime`側も`steppedNow`と同じ刻みへ丸めるか、丸めない理由を書く」／「対応」「検証」節に該当記述なし／実装は`useDynamicWeatherLayers.ts:163`で丸め無し／同ファイル`:68-72`が「これより細かく進めてもどのレイヤーが選ぶフレームも変わらないまま、共有時刻をキーに持つ取得だけが無効化される」と警告／5分刻みでない値を渡せる経路は`RideConditionBar.tsx:102-112`の`datetime-local`直接指定。
  **failure_scenario**: 出発時刻を「9:31」のように直接入力するたび、表示フレームは変わらないのに専用way値の取得だけが無効化され、レンズの色が一拍消えてから戻る。完了扱いの本文に埋もれているため`- [ ]`行しか見ない機械抽出には二度と出てこない。
  **recommendation**: 丸めるか理由を書くかを決める。今決めないなら独立した`- [ ]`行として別Txxxへ起票する。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.module.css` **line**: 182, 519, 528
  **category**: 死んだ参照 **severity**: P3
  **summary**: 削除済みの`MapLayersPanel`を「サイドバー側」として現存扱いで参照し、見た目を揃える約束をコメントが宣言している。
  **evidence**: `:182`・`:519`・`:528`／`find frontend/src -iname "*MapLayersPanel*"`は0件／同種が`globals.css:444`・`page.module.css:120`・`Disclosure.module.css:26`にも／`dead_file_refs`の走査対象はdocs/modulesのバッククォート付きファイル名で、CSSコメントは母集団外。
  **recommendation**: 3箇所を現存の相手へ書き替えるか削除する。ソースコメント側のファイル名参照も`dead_file_refs`の母集団へ入れられるか検討する。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.module.css` **line**: 544-550
  **category**: 同種の扱いが兄弟の一部にしか無い **severity**: P3
  **summary**: 淡色スウォッチの輪郭は`.detailSwatchDot`にだけ足され、同じ`LegendCheckboxList`を使う`LensControl`側のスウォッチには無い。
  **evidence**: `:544-550`（T886差分で`border`を追加）／`LensControl.tsx:168-175`は同じ共通部品へ`styles.swatch`を渡し、`LensControl.module.css:55-62`に`border`は無い／現在レンズ凡例に地色に近い値は含まれていない。
  **failure_scenario**: 淡色パレットの凡例をレンズ側へ出した瞬間、そこだけスウォッチが見えなくなる。共通部品を使っているぶん発見が遅れる。
  **recommendation**: 輪郭を共通スウォッチ側へ寄せ、呼び出し側のclassは寸法だけを決める。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.module.css` **line**: 272
  **category**: デザイントークン非準拠 **severity**: P3
  **summary**: 塗りつぶしチップの文字色1箇所だけが生値`#ffffff`で、兄弟ルールはトークンを使っている。
  **evidence**: `:272`の`.iconChipActive`／同`:287-290`等は`var(--color-group-on-text)`／`--color-accent`はダークモードで再定義されていないため現在の見た目は正しい。
  **recommendation**: トークンへ置き換える。

- **file**: `frontend/src/components/RideConditionBar/departureTimeline.ts` **line**: 46
  **category**: コメントの根拠と実装のずれ **severity**: P3
  **summary**: 目盛りラベルの間引き判定だけUTCの「時」を見ており、JSTでは奇数時にラベルが付く。
  **evidence**: `:46`の`time.getUTCHours() % 2 === 0`／表示系は`dynamicWeather.ts:150,156`が`Asia/Tokyo`で整形／`dynamicWeather.ts:159-163`のコメントは「JSTはUTC+9:00ちょうどで分のずれが無いため…同じ理由」と説明するが、この理由は「分」にしか当てはまらない。
  **recommendation**: JSTの時で判定するか、コメントから「時も同じ理由」と読める記述を外す。

- **file**: `frontend/src/components/Map/RoadInspectorPopup.test.tsx` **line**: 43-65
  **category**: テストの読みやすさ **severity**: P3
  **summary**: 新しいテストが`beforeEach`（モックのリセット）より前に置かれている（実行順は正しい）。
  **evidence**: `:43`に新規の`it`、`:65`に`beforeEach`。
  **recommendation**: `beforeEach`の後ろへ移す。

### 参考

T886の新規テストは「わざと壊すと落ちる」形になっている（`landcoverClasses.test.ts`は生成物の形と`mapOverlayGroupFor`の帰属を、`RoadInspectorPopup.test.tsx:43-64`は畳んだ状態の要約・0%行の非生成を固定）。RideConditionBarの「今」は`onDepartureNow`という別propへ分離され、テストも`onDepartureTimeChange`を呼ばないことまで固定していてT873の意図どおり。

---

## シャードH: 状態ハブ・hooks・lib・API層

対象: page.tsx / useDynamicWeatherLayers.ts / routeSplice.ts / generationRequest.ts /
regionApi.ts / testing/routeFixtures.ts / next.config.ts

### overall

- **file**: `frontend/src/app/page.tsx` **line**: 1204-1213
  **category**: 効いていない実装 / 局所最適の連鎖 **severity**: P2
  **summary**: T886で足した土地被覆の「ズームインすると表示されます」案内は、描画側の条件により**一度も画面に出ない**。
  **evidence**: `page.tsx:1199-1208`が`summaryByLayerId.landcover`へズーム不足時の文字列を入れ、`:1209-1216`が`legendDetailsByLayerId.landcover = LANDCOVER_LEGEND_DETAILS`（`:266-277`で定義、`LANDCOVER_CLASSES`から常に1ブロック＝非空）を入れる／`MapOverlayControls.tsx:1126-1131`（単独チップ）と`:843-871`（グループのメンバータイル）はどちらも`hasLegend ? renderLegendDetails(...) : <p>{summary}</p>`で、legendDetailsが非空ならsummaryを描かない／道路側（`page.tsx:1083-1096`）は`regionZoomTooWide`のとき`legendDetails = []`と空にしてからsummaryを出す（landcoverにはこの片割れが無い）／`grep -rn "landcover\|ズームイン" frontend/src/app/page.test.tsx`は0件。
  **failure_scenario**: 土地被覆チップをONにしたままz5などへ引くと、タイルが一枚も要求されず地図は何も変わらない。利用者は▶を開いても凡例だけが並び、「データが無い地域なのか、ズームが足りないのか」を区別する手掛かりが無い。
  **recommendation**: 道路側と同じくズーム不足時は`legendDetails`を空にしてsummaryへ倒すか、`MapOverlayControls`側を「summaryがあれば凡例の上に併記する」形へ寄せる（後者なら道路側の不自然な空化も畳める）。わざとズームを引いた状態で案内が出ることをテストで固定する。

- **file**: `frontend/src/app/page.tsx` **line**: 1873-1881
  **category**: 重複 / 残骸 **severity**: P2
  **summary**: T874が「このルートを編集」のonClickへ足した3行のリセットは、同じonClickの6行下に既にあった同一の3行と完全に重複している。
  **evidence**: `:1873-1875`と`:1879-1881`が同一（後者は`git show 4a2cb02a:frontend/src/app/page.tsx`の1834-1836に既存）／追加側のコメント（`:1870-1872`）が述べる目的は既存の3行が既に満たしている。
  **recommendation**: 追加した3行を削り、コメントだけを既存ブロックの上へ移す。編集セッションのリセットが4箇所で微妙に違う組み合わせになっている点も一緒に畳む。

- **file**: `frontend/src/app/page.tsx` **line**: 1204-1207
  **category**: 重複（同じ規則の2実装目を手書き） **severity**: P2
  **summary**: 「レイヤーのminzoomより広いズームではタイルを要求しないので何も出ない」という同じ規則が、道路系とlandcoverで別々の配線・別々の判定源として2本実装されている。
  **evidence**: 道路系は`MapView.tsx:1696-1698`の`updateRoadZoomHint`（MapLibre側で判定）→`onRegionZoomHintChange`→`page.tsx:775`→`:1088`（呼び出しは`MapView.tsx:2176・2812・3316`の3箇所）／landcoverは`page.tsx:1204-1207`でpage側が`mapViewport.zoom`から直接判定し、表示中かは見ていない／この追加のため`mapViewport`が`overlayLayers`の依存へ入り（`:1280`）、パン/ズームのたびに全チップ記述子が作り直される。
  **recommendation**: レイヤー記述子が`minZoom`を持ち、案内を記述子から機械的に導く汎用形へ寄せる（構造仕様3・8）。

- **file**: `frontend/src/app/page.tsx` **line**: 584-592
  **category**: 状態増殖 / リセットの分散 **severity**: P3
  **summary**: `handleRoutesClear`は編集セッションの状態を残す。T874はUI側で症状を止めたが、状態そのものは残ったままで、畳む処理が4箇所に散っている。
  **evidence**: `:584-592`が倒すのはroutes/selectedRouteId/comparisonTabActive/generatedConditions/generatedRoutePreference/experimentSlots/selectedRouteSegmentのみ／編集セッションを畳む処理は`:1612-1616`・`:1654-1656`・`:1873-1881`・`:2159-2163`の4箇所で対象の組み合わせが異なる／ルートidは決定的（`route_generator.py:148,358,599`）。
  **failure_scenario**: routesを設定する経路が1本増えて（保存済みルートの復元等）そこでリセットを書き忘れると、同じidが再登場した瞬間に編集面が無言で復帰し、`appliedAlternatives`は古い位置を指したまま地図に帯が出る。
  **recommendation**: 編集セッションの4つを1つの状態へまとめる。まとめるまでは少なくとも`handleRoutesClear`にも同じリセットを置く。

### consistency

- **file**: `frontend/src/lib/routeSplice.ts` **line**: 259-299
  **category**: コメントと実装の不一致（docコメントの取り残し） **severity**: P2
  **summary**: T843が`createsRevisit`を`stretchAlternativeGroups`のJSDocと関数本体の**間**へ挿入したため、`stretchAlternativeGroups`の説明が別の関数に付いた状態になっている。
  **evidence**: `:259-268`が`stretchAlternativeGroups`の説明、`:269-279`が`createsRevisit`の説明、`:280`が`function createsRevisit`／`:299`の`export function stretchAlternativeGroups`にはJSDocが無い／差分で`+createsRevisit`が既存JSDocの直後へ追加されている。
  **failure_scenario**: ホバー・生成ドキュメントで`createsRevisit`に別関数の説明が出る。`stretchAlternativeGroups`はこのモジュールの入口なので、グループ化の規約が読み手から見えなくなる。
  **recommendation**: `:259-268`のJSDocを`:299`の直前へ移す。

- **file**: `frontend/src/app/page.tsx` **line**: 1585-1591
  **category**: ガードの非対称 / 構造的欠陥（早期returnでフラグが戻らない） **severity**: P2
  **summary**: `handleApplySplice`は`applyingRef.current = true`を立てた後に`try`の外で早期returnする経路があり、そこを通ると連打防止フラグが二度と戻らない。同じ条件を`handlePreviewSplice`は持たない。
  **evidence**: `:1585-1587`でフラグを立て、`:1590-1591`の`if (!generatedInput) return;`が`try`（`:1595`）より前・`finally`（`:1620-1624`）の外／`generatedInput`はこのガード以外で使われず、実際の条件は`evaluateSplicedRoute`（`:1554-1555`）が自前で再取得して`null`を返す形で二重に持っている／対の`handlePreviewSplice`（`:1567-1580`）はこのガードを持たず、`null`を受けて`setSpliceError(...)`を出す。
  **failure_scenario**: `generatedConditions === null`かつ編集中の状態に到達すると、「新しいルートを作る」がエラー表示も進行表示も無いまま何も起きず、以後そのセッションの間ずっと押しても無反応になる。現在は`handleRoutesClear`が同時に倒すため到達しないが、routesを設定する経路が増えれば成立する（判断原則16）。
  **recommendation**: `:1590-1591`のガードを削り（`evaluateSplicedRoute`の`null`で一本化）、preview側と同じエラー文言へ合流させる。フラグを立てるのは`try`の直前1箇所に限る。

- **file**: `frontend/src/lib/generationRequest.ts` **line**: 62-70, 103-104
  **category**: コメントが主張する契約と実装の不一致 **severity**: P3
  **summary**: `IGNORED_WHEN_COMPARING`のコメントは「ここに挙げた以外はすべて比較対象になる／除外は明示的な列挙だけに限る」と述べるが、条件付き除外2件はレジストリの外のif文として書かれている。
  **evidence**: `:62-70`のコメントとレジストリ／`:103`の`max_routes`・`:104`の`start_time`（T873で2件目が増えた）／docs側（`page-composition.md:288-291`）は3件を文章で並べており二重管理。
  **recommendation**: `IGNORED_WHEN_COMPARING`を`{ field: { reason, appliesWhen? } }`の形にして条件付き除外も同じ表に載せる。

- **file**: `docs/modules/frontend/static-map-layers.md` **line**: 189-206
  **category**: docsと実装の乖離 **severity**: P3
  **summary**: 「表示範囲が広すぎます」の案内の節がroad_surface系だけを扱い、T886で増えた2本目の経路（landcover、判定源も配線も別）が書かれていない。
  **evidence**: `:189-206`が`ROAD_TILE_MIN_ZOOM`系のみを記述し「対象はroad_surfaceタイルを共有する全レイヤーで、一覧は…が唯一の情報源」と断言／実装は`page.tsx:1204-1207`に別経路を持つ／同ファイル`:21`・`:48`・`:78`はlandcoverを追記済みでこの節だけが追従していない。
  **recommendation**: 節を「タイルのminzoomより広いときの案内」へ一般化し、判定源が2つある事実（または1本化したこと）を書く。

- **file**: `docs/modules/frontend/page-composition.md` **line**: 281-283
  **category**: docsの数え上げ／乖離 **severity**: P3
  **summary**: `handleRoutesClear`が空にするstateを全件列挙しており、既に実装とずれている。
  **evidence**: `:281-283`の列挙／実装（`page.tsx:584-592`）は`setSelectedRouteSegment(null)`も行う一方、編集セッション側は空にしない。どちらも記述に無い。
  **recommendation**: 列挙をやめ挙動の記述へ書き換える。全件が要るならコードを指す。

- **file**: `frontend/src/app/page.tsx` **line**: 331-333, 881
  **category**: コード自身が述べる契約の不足 **severity**: P3
  **summary**: 乗り換え帯のfeature idを`groupIndex * 100 + optionIndex`で符号化しているが、「1グループの選択肢は100未満」という前提がコメントにも実装にも無い（既存）。
  **evidence**: `:331-333`の符号化と`:881`の復号／選択肢の件数は`routeSplice.ts:344-353`が作り、候補数（max_routes最大15）×分割数に比例して増える。上限のガードは無い。
  **failure_scenario**: 1グループの選択肢が100を超えると、帯をタップしたときに隣のグループの選択肢へ乗り換わる（`?.`が効かないので無言で誤った区間が差し替わる）。
  **recommendation**: 符号化をやめるか、少なくとも100を定数化して前提を1行のコメントで明示する。

### 指摘に至らなかった確認項目（記録）

- **`next.config.ts`のタイル系rewrites**: 漏れなし。backendのタイルエンドポイントは`accidents.py:18`／`region.py:49,68,88`の4本で、すべて`next.config.ts:31-49`に登録済み。`region.py:104`の`dynamic-way-values`はアプリの`fetch()`経由でrewrites対象外という設計が`static-map-layers.md:40-50`と一致。
- **`landcoverTileUrl()`の兄弟との揃い**: `regionApi.ts:83-94`は`tileBaseUrl()`＋生成物由来の`tile_version`で兄弟と同型。`landcoverClasses.ts`も生成物を読むだけで片側importを守り、色・ラベルの手書きは無い。`landcoverClasses.test.ts:24,28,32`が固定。
- **T873の配線**: `onNow`の利用箇所は`RideConditionBar.tsx:122`の1つだけで取り残しなし。`departureTimePinned`→`startTimePinned`は`buildCurrentGenerationInput`の依存配列（`page.tsx:1526`）へも入っている。`generationRequest.test.ts:105-123`は実装を戻すと落ちる形。
- **T874のテスト**: `page.test.tsx:1456-1498`が編集中のクリア→編集面が消える・`point-editing-enabled`がtrueへ戻る・再生成で再び編集へ入れる、を検証しており`editingRouteId`直参照へ戻すと落ちる。
- **規模**: page.tsx 2,513→2,560行、page.test.tsx 1,963→2,013行（暴走なし）。
- **`review_checks.py docs --since 4a2cb02a`**: 違反なし。

---

## シャードI: 検知器の実効性監査（scripts/review_checks.py）

`DETECTOR_ENFORCEMENT`の22検知器それぞれについて母集団が「導出」か「手書き」かを判定し、
モジュールを直接importして落としている集合を実測した。

### overall

- **file**: `scripts/review_checks.py` **line**: 2758（guard_probe_mutations）/ 2737（removed_axis_probe_id）/ 2719（drifted_constant_probe）
  **category**: 検知の穴（監査自身の構造） **severity**: P0
  **summary**: mutateのプローブが検知器自身の母集団関数・母集団の内側から作られており、母集団の穴を構造的に絶対に検出できない（＝全PASSが「鳴る」証拠にならない）。
  **evidence**: `removed_axis_probe_id`（2737-2755）は違反に使うaxis_idを`removed_axis_ids()`から取るため、`if "_" in a`で母集団から落ちるidはプローブにも選ばれない（今回見逃した`openness`/`curvature`に対しmutateは構造上PASSを返す）／`drifted_constant_probe`（2719-2734）も`code_numeric_constants()`から綴りを取る（同型）／母集団の内側へ違反を置くプローブ: `map_redraw_coverage`（2830）は入口`MapView.tsx`自身へ追記（T871が足したimport追従の母集団拡張を一度も通らない）、`web_layer_batch_import`（2825）は`backend/app/services/`配下へ（対象外の`main.py`を試さない）、`source_narrative`（2808）は`frontend/src/lib/`へ（対象外のbackend/tests・scriptsを試さない）、`way_tag_allowlist`（2835）は手書き3ファイルの1つへ／この監査は`.github/workflows/docs-consistency.yml:61`が毎push実行し、README.md:43が「実際に鳴るか」の根拠として名指ししている。
  **failure_scenario**: 母集団を狭める変更（除外の追加・ディレクトリ限定）を入れてもmutateは緑のまま。「検知器がある」「鳴る」の次に必要な「取りこぼしていない」が、どの自動検査でも測られていない。
  **recommendation**: プローブの置き場所を母集団の**外縁**に取り、素材を検知器の母集団関数から取らない。各検知器に「拾うべきなのに現状の母集団に入らない位置」を1件ずつ持たせ、MISSを期待値とするネガティブケース表を作る。

- **file**: `scripts/review_checks.py` **line**: 1159（identifier_exists）/ 1079（source_corpus）
  **category**: 母集団の手書き（実在判定corpusの汚染） **severity**: P0
  **summary**: 識別子の実在判定corpusがソース全文（＝コメント込み）のため、撤去済みの名前がコメントに残っているだけで「実在する」と判定され、architecture.md・docs/modulesの死んだ参照が0件になる。
  **evidence**: 実測（HEAD=05c96456）: `find_undeclared_dead_refs`（architecture.md）現行**0件** → corpusからコメントを除くと**12件**（`MapLayersPanel`（149行）・`MAP_LAYERS`（1511）・`ROAD_SURFACE_SHARED_LAYER_IDS`（1511）・`STATIC_FILTER_AXES`（1512）・`LAYER_DATA_SOURCES`（1513）・`STATIC_OVERLAY_LAYERS`（1513）・`axisMaterialLayerIds`（1529）・`WIND_GRID_CACHE_TTL_SECONDS`（2155）・`night_difficulty`（310）等、いずれも撤去の断りが無い行）／`docs/modules/*.md`の`find_dead_identifier_refs`も現行0件 → コメント除外corpusで**19件**／`MapLayersPanel`は実体が無い（`find frontend/src -name "MapLayersPanel*"`→0件）。生き残らせているのは`backend/app/domain/axis_definitions.py:215,219`のdocstring／同じファイル内の`find_source_comment_dead_identifier_refs`（1055-1069）は既に「コメントを除いた本文」をcorpusにしており（1058行に理由も明記）、doc側だけがそれを使っていない。
  **failure_scenario**: 撤去したシンボルをコメントが1つでも引き継いでいる限り、正本であるarchitecture.md・docs/modulesは古い名前を「現行」として書き続け、検知器は0件を返す。
  **recommendation**: doc側の検知器も`split_source_comments`のコード側corpusを使う（実装は既にある）。外部語彙・テスト専用ヘルパの救済は`EXTERNAL_VOCABULARY`と`imported_names()`の既存2経路へ寄せる。

- **file**: `scripts/review_checks.py` **line**: 782（DOC_IDENT_RE）/ 1055
  **category**: 母集団の手書き（記法での絞り込み） **severity**: P1
  **summary**: 「ソースコードのコメントが名指しする死んだ識別子」は実際にはバッククォート付きの綴りしか見ず、コメントがふつうに使う裸の綴り・ファイル名は母集団に入らない。
  **evidence**: 実測: 実装コメント中のバッククォート付き識別子は延べ2,917。これに対し裸で書かれてコード本文に綴りが無いSCREAMING_SNAKEだけで**11種19箇所**（`STATIC_OVERLAY_LAYERS`（MapView.tsx:314ほか6箇所）・`MAP_LAYERS`（page.tsx:599,1037・MapOverlayControls.tsx:51）・`WIND_GRID_CACHE_TTL_SECONDS`（useWeatherGrid.ts:25）・`STALE_FALLBACK_MAX_AGE_SECONDS`（windLayer.ts:68）・`PRIMARY_ATTRIBUTE_CHIP_LABELS`（material_catalog.py:159））／ファイル名は一切見ていない。実測で実在しないもの: `weather_client.py`・`scripts/collect_jartic.py`（wind_grid.py:22）・`measure_axis_stats.py`（precompute_edge_attribute_counts.py:39）。
  **failure_scenario**: フロントのコメントが「backendの◯◯と同じ値」と書いた相手が消えても誰も気づかない。実際にweather_client.pyとその2定数は消えており、値の同期契約だけがコメントに残っている。
  **recommendation**: docs/modulesで使っている裸の綴り抽出をコメントにも当て、高精度な部分集合から段階導入する。ファイル名は`find_dead_file_refs`をコメント行へ流用するだけで足りる。

- **file**: `scripts/review_checks.py` **line**: 100（SOURCE_COMMENT_PATHSPECS）
  **category**: 母集団の手書き **severity**: P1
  **summary**: 経緯コメント検知の対象がbackend/app・frontend/srcの実装ファイルに手書きで限定され、規約が及ぶ残りの領域では新規混入が無検査で入り続ける。
  **evidence**: 実測—— 対象内の残存は**60件**。対象外: backend/tests **664件**（163ファイル）・frontend/srcのテスト**200件**（143ファイル）・backend/scripts **46件**・scripts/ **10件**（`review_checks.py`自身の4件を含む）・frontend/e2e **8件**。合計928件で対象内残存の15倍／CLAUDE.md「コメント方針」は領域を限定せず「新規混入分はpre-commitフック・CIが機械的に検出しブロックする」と書いている（docs/comments.md:125だけがbackend/app・frontend/srcと限定）／T567（一掃タスク）は完了扱い。
  **recommendation**: pathspecをgitが持つ実装拡張子全体から導出し、参考表示（full）と強制（staged/since）の切り分けで既存分を扱う。段階導入するならまず対象外の実測件数を毎回出す（0件で黙らせない）。

- **file**: `scripts/review_checks.py` **line**: 1941（check_dead_doc_links）/ 703（HISTORY_REF_RE）
  **category**: 検知の穴 **severity**: P1
  **summary**: 「死んだリンク」検知がリンクを解決せずファイル名の実在だけを見るため、パスが間違ったリンクを全て見逃す。
  **evidence**: 実測—— docs/・.claude/（history・archive除く）の相対リンク2,562本のうち**83本が解決不能**（48ファイル）。うち**39本がhistory/宛て**、2本がdocs/tasks宛てで、この検知器が担当と明記している範囲そのもの（例: `docs/tasks/T809.md:93`・`T810.md:101`・`T821.md:97`が`../.claude/commands/review/history/2026-09-13_all.md`＝1階層不足）／`docs/architecture.md:151`は実在しない`../frontend/src/components/MapLayersPanel/MapLayersPanel.tsx`へリンクしているが、`FILE_TOKEN_RE`（698）がバッククォート付きしか見ないためファイル実在検査にも載らない。
  **failure_scenario**: principles.md共通実行手順2が「引用されたhistory/ファイルが実在するか確認する」ことを人手の手順として残している一方、機械側は名前一致で常に緑。
  **recommendation**: Markdownリンク`[..](path)`を母集団として、リンク先をパス解決で検査する。

- **file**: `scripts/review_checks.py` **line**: 506 / 546（map_redraw_local_modules）
  **category**: 母集団の手書き（深さ・ディレクトリの限定） **severity**: P2
  **summary**: T871で広げた再描画検知の母集団が「入口が同じディレクトリから取り込むモジュール」1ホップに固定されており、2ホップ目とhooks/はいまも検査の外。
  **evidence**: 実測—— 母集団24ファイル。Map配下の実装39ファイル中15が母集団外で、そのうち**7ファイルは母集団のモジュールが実際にimportしている**（`dynamicWayValues.ts`・`jmaTileIndex.ts`・`landcoverClasses.ts`・`mapColorLegend.ts`・`primaryAttributes.ts`・`routeArrowIcon.ts`・`valueScale.ts`）／正規表現は`@/components/Map/`と`./`の直下名のみで、サブディレクトリ表記と`@/hooks/`は一致しない。
  **failure_scenario**: T871が防ごうとした形（描画の担当を別ファイルへ分けると検知の外へ出る）が、1ホップ深いところ・hooks/へ移すだけで再現する。`dynamicWayValues.ts`は`.setFeatureState(`を1行足した瞬間に無検査になる。
  **recommendation**: 到達グラフをimportの推移閉包で作る。

- **file**: `scripts/review_checks.py` **line**: 321（WEB_LAYER_DIRS）
  **category**: 母集団の手書き **severity**: P2
  **summary**: 「webアプリが読む層」を4ディレクトリの手書きで表しており、本番web起動の本体である`backend/app/main.py`が対象外。
  **evidence**: 実測—— backend/app配下で対象外の.pyは`__init__.py`・`config.py`・`main.py`・`version.py`の4本／検知器のコメント（316-320）は「webアプリが読み込む層から`app/batch`をトップレベルimportすると本番webが起動時に落ちる」と述べており、main.pyはその定義に最も強く当てはまる。
  **failure_scenario**: lifespanで起動ジョブを足す作業はmain.pyを触る。そこへ`from app.batch...`を1行書くと、テストとCIは緑のまま本番webだけがクラッシュループになる（T630・T814と同じ事故）。
  **recommendation**: 母集団を「backend/app配下で`app/batch/`以外の全て」へ導出する。

- **file**: `scripts/review_checks.py` **line**: 348（MATERIAL_TAG_READER_FILES）
  **category**: 母集団の手書き **severity**: P2
  **summary**: 材料解決のタグ読み取り検査の母集団が3ファイルの手書きで、同じ役割の2ファイルが対象外。
  **evidence**: 実測—— `backend/app/domain/hard_filters.py:84`・`backend/app/domain/night.py:27-28`がway tagを読むが一覧外。両ファイルとも`from app.domain.recipe import tag_value_is`を持ち、母集団を「`tag_value_is`をimportするモジュール」から導出できる。現状はいずれも許可済みキーのみを読んでいるため違反0件。
  **recommendation**: `tag_value_is`/`way_tags`を読むモジュールを走査して母集団にする。

- **file**: `scripts/review_checks.py` **line**: 65（IMPL_INCLUDE_PREFIXES）
  **category**: 母集団の手書き / 責務混在 **severity**: P2
  **summary**: レビュー基盤自身（scripts/）がすべての規模・記載漏れ・経緯コメント検査の母集団から外れており、その間にreview_checks.pyは5日で3倍になった。
  **evidence**: 実測—— `is_impl_file("scripts/review_checks.py")`はFalse。行数は997行（2026-09-11のmaster）→2,705行（前回レビュー対象4a2cb02a）→**2,996行**（HEAD）／`size`ウォッチ表の最大はMapView.tsx 3,440行で、review_checks.pyは表に載れば2位相当だが表に出ない／1ファイルがdocs検査・size・metrics・duplication・trigger・mutateの6サブコマンドを同居させている（mainの2966-2989行）。
  **recommendation**: `is_impl_file`の母集団へscripts/・backend/scripts/を入れる（記載漏れ検査だけは明示的に除く）。検知器群と計測群の分離を検討する。

- **file**: `scripts/review_checks.py` **line**: 2198・2226
  **category**: 重複 **severity**: P3
  **summary**: `--since`（CI経路）で`map_redraw_coverage`が二重に登録され、件数が2回加算・2回表示される。
  **evidence**: `docs --since HEAD~2 --keys`の出力に`[map_redraw_coverage]`の節が2つ／2198行はif/elseの外、2226行は`if args.since:`の中。
  **recommendation**: 2226行の登録を削る。

- **file**: `scripts/review_checks.py` **line**: 1623（code_numeric_constants）
  **category**: 検知の穴 **severity**: P3
  **summary**: 同名定数を最初に見つけた1ファイルで確定するため、複数箇所に同名がある定数は照合相手を取り違える。
  **evidence**: 実測—— 定数266種のうち3種が複数ファイルで異なる値（`DISTANCE_KM` 10.0/22.0/4.0、`TIME_BIN_HOURS` 1.0(app)/0.5(benchmarks)、`OSM_WAY_ID` 100/500）／`setdefault`のためgit ls-files順でapp側が勝つ。
  **recommendation**: 同名が複数あるときは全候補のいずれかと一致すれば通す（またはファイル修飾を要求する）。

### consistency

- **file**: `docs/documentation.md` **line**: 54
  **category**: 契約と実装の不一致 **severity**: P1
  **summary**: 「機械が完全性を検査している表」はdocs/modulesの対象ファイル表だけ、と宣言しているが、検知器は表を見ておらず文書全文の部分文字列照合。
  **evidence**: `find_undocumented_files`（1298-1319）は`name in modules_text`（全モジュール文書を連結した文字列への包含）で判定／実測—— 実装328ファイルのうち**8件**は、どのモジュール文書の表（`|`始まりの行）にも名前が無く本文にしか出てこない（`services/derived_data_revision_service.py`・`Map/pinMarks.ts`・`MapOverlayControls.tsx`・`TravelBearingControl.tsx`・`lib/adminApiProxy.ts`・`lib/adminBasicAuth.ts`・`lib/gpxExport.ts`・`src/proxy.ts`）／`docs/architecture.md:456`も「機械的に検出するため静かに古くならない」と同じ主張をしている。
  **recommendation**: 判定を「対象ファイル表の行に現れること」に限定する（表の書式は既に固定されている）。

- **file**: `scripts/review_checks.py` **line**: 76（GENERIC_BASENAMES）
  **category**: 母集団の手書き（構造仕様12の直接の例） **severity**: P1
  **summary**: 「名前だけでは特定できないファイル名」を手書き一覧で持っているが、同じ関数が既にbasenameの重複数を導出しており、一覧外の重複名は名前空間の衝突で「記載済み」と誤判定される。
  **evidence**: 実測—— 実装ファイルで重複するbasenameは7種、うち**5種が一覧外**（`db_status.py`・`derived_data_freshness.py`・`material_catalog.py`・`region.py`・`weather.py`）。修飾形での照合では`routers/db_status.py`・`infrastructure/db_status.py`・`routers/derived_data_freshness.py`・`infrastructure/derived_data_freshness.py`・`domain/region.py`・`domain/weather.py`はいずれも文書に出てこないが、素の名前が別ファイルの記述で一致するため全て「記載済み」と判定されている／`find_undocumented_files`は1304-1307行で`basename_count`を全実装ファイルから導出済みで、手書き一覧はその導出を狭める用途にしか使われていない。
  **recommendation**: `GENERIC_BASENAMES`を廃し、`basename_count > 1`だけを条件に修飾形照合へ切り替える。

- **file**: `scripts/review_checks.py` **line**: 920（find_dead_refs_inside_exempted_paragraphs）
  **category**: 契約と実装の不一致（安全網の穴） **severity**: P1
  **summary**: 「免除した中身を黙って捨てると0件が誤読される」ために置かれた参考出力が、免除の原因になった行そのものを母集団から外しているため、常に0件を返す。
  **evidence**: 936行で`not ARCHITECTURE_REMOVED_MARKER_RE.search(line)`により「断り語を含む行」を除外している。断り語は段落単位の免除の引き金でもあるため、断り語と死んだ名前が同じ行にある場合はenforced側でも参考側でも見られない／実測—— architecture.mdは現行0件／免除段落の参考も0件だが、免除を一切かけずコメント除外corpusで測ると**141件**、うち129件が「段落免除」または「行に断り語」でどちらの出力にも現れない（例: 151行は`旧MapLegendPanel`のせいで行ごと免除され、同じ行の`RoadFilterEditor`・実在しないMapLayersPanel.tsxへのリンクが検査されない）。
  **failure_scenario**: 「撤去済み」と1語書けば、その行の他の名前がいくつ死んでいても永久に報告されない。0件で黙らないための仕掛けが、いちばん怪しい行だけを選んで捨てている。
  **recommendation**: 参考出力側は行単位の除外をやめ、「免除段落に含まれる実在しない名前」を全部出す（enforced側の判定は変えない）。

- **file**: `scripts/tests/test_review_checks.py` **line**: 510
  **category**: テストと検知器の対応 **severity**: P2
  **summary**: 強制22検知器のうち10個は、入口関数を1度も呼ぶユニットテストが無く、担保がmutateだけ（そのmutateは上のP0の構造を持つ）。
  **evidence**: 実測（テストファイル内での関数名出現回数）—— 0回: `find_dead_file_refs`・`find_narrative_violations`・`check_task_numbering`・`check_dead_doc_links`・`find_redis_skeleton_violations`・`find_undocumented_files`・`find_web_layer_batch_imports`・`find_way_tag_allowlist_violations`・`find_cross_file_env_writes`・`find_source_comment_dead_identifier_refs`／母集団を対象にしたテストは2件のみ。
  **recommendation**: 「この入力は拾うべき／拾ってはいけない」の対を各検知器に最低1組置く。とくに母集団の境界を明示的に固定する。

- **file**: `scripts/review_checks.py` **line**: 616 / 2200
  **category**: docstringと実装の不一致 **severity**: P2
  **summary**: `find_duplicate_test_scaffolds`のdocstring・見出しは一般に述べるが、配線はfrontendの`.test.ts(x)`のみ。
  **evidence**: 2201行が`[f for f in files if f.endswith(".test.ts") or f.endswith(".test.tsx")]`を渡す／実測—— backend/testsに同名の足場が2種（`_make_graph`が3ファイル、`make_generator`が2ファイル）。現行出力はfrontendの`fakeMap` 1件のみ。
  **recommendation**: 母集団をテストファイル全般へ広げるか、見出し・docstringへ対象範囲を書く。

- **file**: `.claude/commands/review/README.md` **line**: 36
  **category**: 契約の読み違いを誘う記述 **severity**: P3
  **summary**: 「pre-commit経路とCI経路が同じ集合を強制する」は検知器キーの集合については正しいが、各検知器の**走査範囲**は経路で大きく違う。
  **evidence**: `docs --since HEAD~2 --keys`の出力で12検知器が`--since`でも「（全件）」で走る一方、`--staged`は同じ検知器をステージ済みファイルへ絞る（2071-2130）。
  **recommendation**: `DETECTOR_ENFORCEMENT`に範囲の次元を持たせるか、README側に「集合は同じ、範囲は経路ごと」と1行足す。

- **file**: `scripts/review_checks.py` **line**: 1055
  **category**: docstringと実装の不一致 **severity**: P3
  **summary**: 「ソースコードのコメントが名指しする識別子のうち、実装のどこにも綴りが無いもの」とあるが、実際はバッククォート付きのみ。
  **evidence**: 1228行で`DOC_IDENT_RE`（バッククォート必須）＋修飾形のみを抽出。
  **recommendation**: docstringへ明記するか、上のP1の対応で実装側を広げる。

### このシャードの問いへの答え

`docs`のフル実行は6.7秒で「違反なし」を返すが、**0件の多くは「違反が無い」ではなく「母集団に入っていない」**。効いているのは3つの共通構造:
(1) 実在判定corpusがコメント込み（→ architecture.md 12件・docs/modules 19件が不可視）、
(2) 記法での絞り込み（バッククォート必須・リンクを解決しない）、
(3) 監査プローブが検知器自身の母集団から作られる（→ mutate全PASSが母集団の穴を保証しない）。
既知2件（`if "_" in a`、日本語ラベル）は、いずれも(3)によって緑のまま通ったものと同型。
