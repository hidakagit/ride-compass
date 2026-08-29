# RideCompass ゼロベース網羅レビュー 指摘一覧

- 実施日: 2026-08-30
- 対象: master(コミット470bf32)相当の全ソース(review-zero-baseブランチ、review-temp worktree)
- 方式: 9領域に分割し、各領域を専用エージェントが8観点(正しさ×3・再利用性・簡素化・効率性・抽象度・CLAUDE.md規約)で網羅レビュー
- 本ファイルは各シャードの指摘を**絞り込まず全件**記載する

## サマリ

全9シャード・86件の指摘(重複統合前の生数)。内訳:

| severity | 件数 | 意味 |
|---|---|---|
| P0 | 1 | 重大・即修正級 |
| P1 | 13 | 重要 |
| P2 | 33 | 中程度 |
| P3 | 39 | 軽微 |

### 特に優先度が高いもの

- **[P0] AxisComposer.tsx (§9)**: 材料カタログが0件のとき`materialOptions[0].id`が未ガードで軸スタジオがクラッシュする。
- **[P1] MapView.tsx (§3)**: T414で追加した`windAxisPenalties`/`windPenaltyGeojson`が「変わらないデータを更新」ボタン(`redrawAllLayers`)で再適用されない——今回のT414実装から生じた回帰。
- **[P1] MapView.tsx (§3)**: `windPenaltyFill`レイヤーが`interactiveLayerIds`の除外対象漏れで、クリック時に無関係な路面ポップアップが誤表示される——同じくT414由来。
- **[P1] axis_admin.py (§5)**: `priority_overrides[*].material`のタイプミスが未検証のまま保存でき、0次条件が無警告で恒久的に不発動になる。
- **[P1] AxisComposer.tsx (§9)**: 折れ点(breakpoints)のx昇順チェックが無く、backendの前提を静かに破れる。同ファイルでは循環参照の保存時チェックも欠落。
- **[P1] weather.py等 (§5) / API_BASE_URL (§8)**: レート制限の429処理ブロック(12箇所)・`API_BASE_URL`フォールバック(7箇所)がいずれも「過去に単一ソース化で解決したはずの重複パターン」の再発。
- **[P1] jma_amedas_service.py / region_service.py (§7)**: docs/logging.mdの「候補0件は常時WARNING」「高頻度WARNINGは抑制」に反する箇所が複数ファイルに横展開。

---

## 1. backend/app/domain/ (32ファイル、6,067行)

- **file**: `backend/app/domain/routing.py`
  **line**: 224-247（特に226・245）
  **category**: correctness / **severity**: P2
  **summary**: `find_nearest_node_indexed`の探索打ち切り判定が、緯度方向(cos補正なし)のセルサイズを「安全マージン」として使っており、実際には経度方向の距離が常にそれ以下になる(cos(緯度)倍で短くなる)ため、打ち切りが早すぎる可能性がある。
  **failure_scenario**: docstringは「経度方向のセルが実際に狭い場合でも打ち切りが早すぎることはない」と主張するが実際は逆。日本の緯度範囲(24°〜46°N、cos=0.90〜0.69)では経度方向の実距離がこの分だけ短く見積もられておらず、東西方向の真に近いノードが未探索のまま探索が打ち切られうる。出発/経由地点のスナップ先がわずかにずれる可能性(road_graph_engine.pyから毎リクエスト複数回呼ばれる主要経路)。

- **file**: `backend/app/domain/evaluation.py`
  **line**: 507-527, 705-713
  **category**: correctness / **severity**: P2
  **summary**: `_neumaier_accumulate`は空リスト(`terms[0]`)を前提にしており、`axis_arrays`が空(公開軸が1つも無い状態)だと`compute_edge_costs_bulk`全体が`IndexError`で落ちる。
  **failure_scenario**: `AXIS_DEFINITIONS`は起動時にDBから読み込まれるまで空、またはDB読み込み前にリクエストが到達する競合状態が起きると`score_terms=[]`になり、`_neumaier_accumulate([])`が`IndexError`を送出、`/api/routes/generate`全体が意味不明な500になる。

- **file**: `backend/app/domain/route.py`
  **line**: 247-250
  **category**: correctness / **severity**: P2
  **summary**: `_merge_segment_bin`のcar_stress丸めがPython組み込み`round()`(銀行丸め)を使っており、同じ1-5尺度に対して「非対称な挙動なので使うべきではない」と明記・修正済みの`car_stress_display_level`(axis_definitions.py)の方針と矛盾している。
  **failure_scenario**: 距離加重平均がちょうど`.5`境界(例: 2.5, 3.5)になるビンでは、区間インスペクタ等で見える`car_stress_display_level`由来の値と、ビン集約された`RouteSegmentDetail.car_stress`の値が非対称に食い違いうる(2.5→2 vs 3.5→4)。

- **file**: `backend/app/domain/geo.py`
  **line**: 97-103
  **category**: correctness / **severity**: P3
  **summary**: `sample_indices`は`sample_count == 1`かつ`point_count > 1`のとき`step = (point_count - 1) / (sample_count - 1)`でゼロ除算(`ZeroDivisionError`)になるガードが無い。
  **failure_scenario**: 現在の唯一の呼び出し元は`MIN_SAMPLE_COUNT = 12`で下限を設けているため実害は無いが、domain層の汎用ヘルパーとして公開されており、将来別の呼び出し元が`sample_count=1`を渡すと即座にクラッシュする。

- **file**: `backend/app/domain/scoring.py`
  **line**: 1-25（特に18-19）
  **category**: correctness / **severity**: P3
  **summary**: `normalize_min_max`は候補が全て同値の場合「中立の100点」を返すとdocstringで説明しているが、実際に返す値は0-100スケールの最大値(＝最善)であり、字義通りの「中立」ではない。
  **failure_scenario**: 相対順位への影響は無いが、「全候補とも劣悪な値で差が無い」場合でも一律100点(最良)としてtotal_scoreへ加算されるため、ユーザー向けスコア内訳を見た人が「その指標は完璧だった」と誤解しうる。

- **file**: `backend/app/domain/axis_display.py`
  **line**: 66-465 全体（特に`derive_ramp_inputs`/`_resolve_referenced_axis_tile_input`）
  **category**: altitude / **severity**: P3
  **summary**: T278→T297→T308→T396→T404と段階的に安全側の特殊ケース分岐が積み重なった結果、「自動導出できる形状の組み合わせ」を判定するロジック自体が一種のミニインタプリタ化しており、新しいshape/材料の組み合わせが増えるたびに分岐が増える構造になっている。
  **failure_scenario**: 現状は各分岐が丁寧にコメントされ安全側でNoneを返す設計のためクラッシュリスクは低いが、3関数合計で400行近くの条件分岐となっており、新しい軸の形状パターンが追加されるたびにこのファイルへ特殊ケースを足す以外の拡張手段が用意されていない。

- **file**: `backend/app/domain/attributes.py`
  **line**: 88-137（`compute_elevation_attribute`）
  **category**: correctness / **severity**: P3
  **summary**: 標高欠損点を除外した`valid`リストに対し隣接ペア(`zip(valid, valid[1:])`)で勾配・距離を計算するため、欠損区間を挟んで本来隣接していない2点同士がそのまま「隣接区間」として扱われ、距離・勾配が不連続に平均化されうる。
  **failure_scenario**: 標高が疎らに欠損する区間(DEM取得の部分的失敗等)では、欠損を挟んだ2点間の直線距離・標高差から算出した`grade`が、実際の地形(欠損区間内の起伏)を反映しない平均化された値になる。

- **file**: `backend/app/domain/accident.py` / `backend/app/domain/traffic.py`
  **line**: accident.py 101-119、traffic.py 98-113
  **category**: reuse / **severity**: P3
  **summary**: `distance_weighted_accident_density`(accident.py)と`_density_per_km`(traffic.py、非公開)はロジックがほぼ同一で、accident.py側のdocstringは「traffic.pyへの依存は意味的に不要なため作らない」として意図的に複製している。
  **failure_scenario**: 意図的な設計判断としてコメント済みだが、共通化すれば重複コードを削減でき、将来どちらか片方だけ計算式が変更され食い違うリスクを構造的に防げる(現状は許容されたトレードオフ、低優先)。

- **file**: `backend/app/domain/jma_area.py`
  **line**: 32-66（`resolve_area`）
  **category**: correctness / **severity**: P3
  **summary**: `class20["parent"]`等、外部データ(area.json)のキー存在を`.get()`ではなく直接インデックスアクセスで前提にしている箇所があり、想定外の形式のエントリが来ると`KeyError`が握りつぶされずそのまま伝播する。
  **failure_scenario**: 気象庁area.jsonの構造が将来変わる、または一部エントリで`parent`キーが欠けている場合、`resolve_area`は`None`を返さず`KeyError`で例外送出する。他の外部データ処理関数は総じて`.get()`/`try-except`でunknown-safeに倒しているのに対し本関数だけ例外的。

**総評(担当エージェント)**: 各関数のdocstringに設計判断の経緯・トレードオフ・過去障害対応が丁寧に記録されており品質は高水準。P0該当なし。

---

## 2. backend/app/infrastructure/ (30ファイル+空__init__.py、6,055行)

- **file**: `backend/app/infrastructure/elevation_client.py`
  **line**: 141-144（`_get_tile_grid`）
  **category**: correctness / **severity**: P1
  **summary**: DEMタイル取得の一時的な通信エラーが「そのタイルは永続的にデータ無し」として無TTL・無期限にプロセス内メモリキャッシュされる。
  **failure_scenario**: `_fetch_tile`は404(正当な「未整備」)とhttpx.HTTPError(タイムアウト・5xx等の一時障害)のどちらも同じ`None`を返し、呼び出し元が区別せず無条件キャッシュする。GSI側が一瞬混雑しただけでも、`refresh=True`が渡らない限り(全呼び出し元が既定値`False`のまま呼んでいるのを確認済み)プロセス再起動まで標高Noneを返し続け、勾配評価が静かに劣化する。

- **file**: `backend/app/infrastructure/road_edge_geometry_cache.py`, `road_graph_tile_cache.py`, `wind_forecast_cache.py`, `wind_way_penalty_cache.py`
  **line**: 例: road_edge_geometry_cache.py 47-63、road_graph_tile_cache.py 45-64、wind_forecast_cache.py 41-56、wind_way_penalty_cache.py 63-76
  **category**: reuse / conventions / **severity**: P1
  **summary**: 4つのRedis cache-asideモジュールがすべて`debug_log.py: log_external_call`を使わず、手書きtry/exceptを個別に再実装している(CLAUDE.mdログ方針違反)。
  **failure_scenario**: CLAUDE.mdの「外部API/キャッシュアクセスは`log_external_call`で囲む」規約に反する。他の外部呼び出し(weather_client.py等10ファイル)は全て`log_external_call`経由だが、この4つのRedisモジュールだけ独自実装。結果`/api/debug/stats`にRedisキャッシュのヒット率・エラー率が一切反映されず、本番でRedisが不調でも主要な観測点から見えない。

- **file**: `backend/app/infrastructure/request_log.py`
  **line**: 68-80
  **category**: correctness / **severity**: P2
  **summary**: 未処理例外(500)発生時、レスポンスに`X-Request-ID`ヘッダが付かない。
  **failure_scenario**: 例外を再送出する分岐はアクセスログこそ出すが`response.headers["X-Request-ID"]`を設定せずに関数を抜ける。モジュールdocstringが謳う「ユーザー報告からサーバーログを特定できる」機能が、まさにユーザーが問い合わせてきやすい500エラー時にだけ働かない。

- **file**: `backend/app/infrastructure/tile_cache.py`
  **line**: 46-58（`set`関数、特に55-56行）
  **category**: correctness / **severity**: P2
  **summary**: `.bin`と`.meta`を別々の非アトミックな書き込みで保存するため、書き込み中の`get()`が誤ったContent-Typeを返しうる。
  **failure_scenario**: 初回キャッシュ書き込み中(`.bin`完了直後・`.meta`書き込み前)に別リクエストの`get()`が`content_file.is_file()`True・`meta_file.is_file()`Falseと判定し`"application/octet-stream"`にフォールバック。basemapスタイルJSON等(JSON期待)を配信するパスでこれが起きるとMapLibre側のJSONパース判定に影響しうる。

- **file**: `backend/app/infrastructure/road_edge_geometry_cache.py`(55,84,105) / `road_graph_tile_cache.py` / `wind_forecast_cache.py` / `wind_way_penalty_cache.py`
  **line**: 各ファイルの`client = get_redis_client()`呼び出し箇所（try節の外）
  **category**: correctness / **severity**: P2
  **summary**: `get_redis_client()`自体の呼び出しがtry/exceptの外にあり、fail-open契約が破れうる。
  **failure_scenario**: `redis.from_url()`はURLスキームが不正な場合等に同期的に例外を送出しうる(settings.redis_url設定ミス時)。その例外はtry/exceptで捕捉されず、モジュールdocstringが謳う「Redis自体の障害はfail-fastさせない」契約を破ってルート生成・タイル配信自体を落としうる。

- **file**: `backend/app/infrastructure/wind_way_penalty_cache.py`
  **line**: 41（`from app.infrastructure.weather_client import WIND_GRID_CACHE_TTL_SECONDS`）
  **category**: altitude / **severity**: P3
  **summary**: Redisキャッシュ層が外部APIクライアント(weather_client.py)の内部定数へ直接依存しており、レイヤーの境界が曖昧。
  **failure_scenario**: weather_client.py側でTTLの意味・値を変更した際に風タイルペナルティキャッシュのTTLも意図せず追従する。両者が独立した理由でTTLを変えたくなった場合に密結合が変更を妨げる。

- **file**: `backend/app/infrastructure/wind_way_penalty_cache.py`
  **line**: 50-56（`bearing_bucket`）
  **category**: correctness / **severity**: P3
  **summary**: `round()`のround-half-to-even挙動により、5度バケットの境界幅が均一でない。
  **failure_scenario**: 例えば`normalized=2.5`は0番バケット、`normalized=7.5`は8番バケットに丸まる等、境界の実際のバケット幅が理論上の5度から最大1度前後ずれる。体感できる誤差ではなく実害は小さい。

- **file**: `backend/app/infrastructure/http_client.py`
  **line**: 11-17
  **category**: efficiency / **severity**: P3
  **summary**: プロセス全体で使い回す`httpx.AsyncClient`が明示的にcloseされる経路を持たない。
  **failure_scenario**: database.pyのエンジンと同様の設計判断だが、テスト・スクリプト等でこのモジュールをimportして繰り返し使う場合にコネクションが溜まる可能性がある。本番プロセスの通常運用では実害は小さい。

**総評(担当エージェント)**: `debug_log.py`の座標2桁丸めはdocs/logging.md方針と一致(意図通り)。`redis_client.py`のサーキットブレーカー設計、`road_graph_repository.py`のCOPYベースUPSERT、`rate_limiter.py`のsweep/ウィンドウ管理は妥当と確認。P0該当なし。

---

## 3. frontend/src/components/Map/MapView.tsx (1ファイル、2,992行)

### P1

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1998-2027（`redrawPropsRef`初期値）, 2139-2224（`redrawAllLayers`本体）, 2933-2954（`refreshToken`エフェクト）
  **category**: correctness（呼び出し元整合性） / **severity**: P1
  **summary**: 「変わらないデータを更新」ボタン(`refreshToken`→`map.setStyle`→`redrawAllLayers`)が、T414で追加された`windAxisPenalties`・`windPenaltyGeojson`を再適用しない。
  **failure_scenario**: `redrawPropsRef`/`redrawAllLayers`の分割代入は`showWindAxis`/`showWindPenaltyFill`(ON/OFF)は含むが、実際の色分け値である`windAxisPenalties`(`applyWindAxisPenalties`、専用effectでしか呼ばれない)と`windPenaltyGeojson`(`applyWindPenaltyFillGeojson`、専用effectでしか呼ばれない)は含まない。風(評価軸)または風penalty面塗りをONにした状態で基礎地図タイル更新ボタンを押すと、`setStyle`で全ソース・feature-stateが消えた後、`redrawAllLayers`はレイヤーの可視化だけを復元し風の値は再投入されない。道路線は無色、面塗りは空のまま、次にパン/ズームしてpropが変化するまでこの状態が続く。他の動的気象要素(降水・風矢印等)は`DYNAMIC_WEATHER_LAYER_IDS`ループで正しく再適用されており、この2つだけが漏れている非対称な実装。

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1421-1440（`buildStaticOverlayLayers`の`windPenaltyFill`エントリ, 特に1433-1435）, 1546-1554（`buildInteractiveLayerIds`）, 2358-2422（`handleClick`）
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: 風penalty面塗りレイヤー(`WIND_PENALTY_FILL_LAYER_ID`)が`interactiveLayerIds`から除外されておらず、クリック時に路面用ポップアップが誤表示される。
  **failure_scenario**: `buildInteractiveLayerIds`は`elevation`と`"axis:"`始まりのkeyだけを除外するが、`windPenaltyFill`(プロパティは`{windPenalty: number}`のみ)はどちらにも該当せず対象に含まれる。`handleClick`はレイヤーIDで一部を分岐するが、それ以外はすべて`buildRoadSurfacePopupHtml`(`osm_way_id`/`surface_good`等を期待する型)に流す。ユーザーが「環境」グループの風penalty面塗りをONにしてクリックすると、実データが無いまま「路面: 不明」だけのポップアップが出る。ホバー時のカーソルもpointerになり誤ったアフォーダンスを与える。`windPenaltyFill`だけが独自機構ゆえにこの副作用を継承してしまっている。

### P2

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1059-1062
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: `clearWindAxisFeatureState`が`map.removeFeatureState({source, sourceLayer})`をid・key指定なしで呼んでおり、将来同じroad_surfaceソースに別のfeature-stateキーが追加された場合に無関係な値まで巻き添えで消す。
  **failure_scenario**: 現状は`WIND_AXIS_FEATURE_STATE_KEY`しかこのソースのfeature-stateを使っていないため実害はないが、`removeFeatureState`はkey省略時に対象の全フィーチャーの全キーをクリアする。今後別の用途でfeature-stateを同じソースへ足した場合、`showWindAxis`をOFFにするたびにその値も無警告で消える。

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1189-1265（`ensureDesignationLayer`/`ensureTunnelLayer`/`ensureOnewayLayer`）
  **category**: reuse / altitude / **severity**: P2
  **summary**: 3つのensure関数がレイヤーID・色/不透明度式以外まったく同一構造で、コピペにより増殖している。
  **failure_scenario**: 直接の障害は無いが、同ファイル内でramp軸は`makeEnsureAxisRampLayer`というファクトリ関数へ既に一般化済みであり、複雑度平衡レビューの「個別レイヤーごとに似たensure/apply関数が場当たり的に増えていないか」という原則と矛盾する。将来4つ目の一次属性レイヤーが追加されるとまたコピペが生まれやすく、修正漏れ(3箇所のうち1つ更新し忘れる)のリスクを高めている。

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 2490-2505（`handleMapError`）, 2933-2954（`refreshToken`エフェクト）
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: 基礎地図タイル更新(`setStyle`)が失敗した場合、ユーザー向けのエラーバナー(`styleLoadFailed`)が出ない。
  **failure_scenario**: `handleMapError`は`tagged.__rcStyleReady`が一度でもtrueになった後は`setStyleLoadFailed(true)`を呼ばない。初回ロード成功後に「変わらないデータを更新」を押し、新スタイル取得がネットワーク不調等で失敗した場合、`error`イベントは飛ぶがバナーは出ずdebugLogにしか記録されない。ユーザーは成否のフィードバックを得られない。

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 2933-2954
  **category**: correctness（非同期処理の競合） / **severity**: P2
  **summary**: `refreshToken`が短時間に連続して変化した場合(連打等)、複数の`refreshBasemapCache`→`setStyle`呼び出しが重なることに対するガードが無い。
  **failure_scenario**: 1回目のawait中に`refreshToken`が再度変わると、2回目のeffectも独立して同じ処理を実行する。MapLibreは新しい`setStyle`呼び出しで前のスタイル読み込みを打ち切りうるため、1回目の`style.load`リスナーが発火せず`redrawAllLayers`が一度も呼ばれない可能性がある。実害は限定的だが排除できていない。

### P3

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1041-1049（`applyWindAxisPenalties`）
  **category**: efficiency / **severity**: P3
  **summary**: `way_id`ごとに`map.setFeatureState`を個別呼び出ししており、ビューポートが広くタイル内way数が多い場合にメインスレッドの負荷が線形に増える。
  **failure_scenario**: 500msデバウンス後とはいえ、密な道路網(都心部)で風(評価軸)ONのままパン/ズームを繰り返すと、数百〜千件規模のway_idそれぞれに個別の`setFeatureState`呼び出しが発生し、体感的なカクつきにつながりうる。

- **file**: `frontend/src/components/Map/MapView.tsx`
  **line**: 1739-1756（`buildStopPoiPopupHtml`/`buildSupplyPoiPopupHtml`と関連型）
  **category**: simplification / reuse / **severity**: P3
  **summary**: 型定義・関数本体ともほぼ同一の2組が、ラベル辞書とprefix文言だけを変えて別々に定義されている。
  **failure_scenario**: 実害は無いが`buildPoiPopupHtml(prefix, labels, kind)`のような1関数へ統合可能。将来3種類目のPOIレイヤーが増えた際にまた同じコピペが増える可能性が高い。

**総評(担当エージェント)**: P1の2件はルートCLAUDE.mdが繰り返し指摘してきた「新しいフィールド・パターンを追加した際、既存の集約ポイントへの配線漏れが繰り返し発生する」という同一クラスの不具合であり、docs/tasks/T414.mdの完了条件確認、または`redrawAllLayers`のprops網羅性を検証する軽量テスト追加を検討する価値がある。

---

## 4. frontend/src/components/Map/ (MapView.tsx・テスト除く、25ファイル、5,024行)

### P1

- **file**: `frontend/src/components/Map/jmaNowcastFrames.ts`
  **line**: 51-57, 63-66
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: `latestObservedFrameIndex`のフォールバックが「実況フレームが1件も無い」場合に末尾index(最も未来のフレーム)を返すため、`trimToCurrentAndFuture`がほぼ全フレームを切り捨ててしまう。
  **failure_scenario**: `fetchNowcastFrames`はN1(実況)とN2(予測)を`Promise.allSettled`で個別取得し、片方だけ失敗しても部分的な時系列を返す設計。N1だけが失敗(またはN1が0件)してN2が成功すると全件`isForecast:true`になり、`latestObservedFrameIndex`は実況フレームを見つけられず`Math.max(0, frames.length-1)`(配列末尾、最も未来の1フレーム)を返す。`frames.slice(末尾index)`はその1フレームしか残さず、降水ナウキャスト・雷/竜巻ナウキャストのスライダーがほぼ空になり直近の予測がすべて消える。同じ「観測データ0件」ケースを`precipitationFrames`は`lastNowcastMs = -Infinity`で正しく処理しており、本関数だけが逆(データを捨てる)フォールバックになっている非対称性から実装ミスの可能性が高い。

### P2

- **file**: `frontend/src/components/Map/roadFilterAxes.ts`(75), `staticAttributeLayers.ts`(38), `axisLayers.ts`(292)
  **category**: conventions（設計原則2: 定数の片側import）／simplification / **severity**: P2
  **summary**: `COLOR_UNKNOWN = "#9ca3af"`が3ファイルに独立定義されている。`axisLayers.ts`は「循環import回避のため複製」と明記しているが、他2ファイルにはその説明が無く、`staticAttributeLayers.ts`は既に`axisLayers.ts`からimport済みでimportを増やすだけで解消できる。
  **failure_scenario**: 「不明」色を将来変更する際、3箇所のうち1〜2箇所だけ変更漏れが起きると、路面レイヤー・車ストレス系レイヤー・二次軸rampレイヤーで「不明」の色調が食い違う。docs/complexity-review-2026-08-16.md末尾の設計原則2が守られていない。

- **file**: `frontend/src/components/Map/roadFilterAxes.ts`(231-307: matchInput/buildMatchExpression/buildOpacityMatchExpression/buildGroupLegend), `staticAttributeLayers.ts`(90-127: buildCategoricalLayerDefs)
  **category**: reuse / simplification / **severity**: P2
  **summary**: 「文字列プロパティ→(色分けmatch式・不透明度match式・凡例配列)」を組み立てるロジックがほぼ同じ骨格で2ファイルに別々実装されている。
  **failure_scenario**: `staticAttributeLayers.ts`側は「同じ骨格を逐語コピーしていたのを1箇所へ集約する」(改善計画T82)と明言しているが、集約先はファイル内に閉じており`roadFilterAxes.ts`側の等価ロジックとは統合されていない。「不明」判定の意味論や不透明度の扱いを将来変更する際、2箇所を同時に直す必要があり、T82で問題視されたのと同種のドリフトが再発しうる。

### P3

- **file**: `frontend/src/components/Map/axisLayers.ts`
  **line**: 147-157
  **category**: correctness（コメント陳腐化） / **severity**: P3
  **summary**: `axisLabelsFromCatalogAxes`のコメントは「windはレジストリ未登録のためカタログに無く、ここでのみ補う」としているが、実際は`axis-catalog.json`に`axis_id:"wind"`が既に登録済み(T352でルート色分けに組み込まれた際に追加されたと見られる)。
  **failure_scenario**: `wind:"風"`という直書きは`...axes.map(...)`で常に上書きされる(実害は今のところ無い)が、コメントと実態が矛盾したまま残ることで、将来wind軸のラベルをbackend側だけ変更した開発者が直書きの方を編集してしまい、変更が反映されないという手戻りを招きうる。

- **file**: `frontend/src/components/Map/routeStyleModes.ts`
  **line**: 184, 193-195
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: `DEFAULT_ROUTE_STYLE_MODE_ID = "wind"`が固定文字列でハードコードされており、`getRouteStyleMode`は該当IDが見つからない場合`modes[0]`へ無警告でフォールバックする。
  **failure_scenario**: axis-catalog.jsonのwind軸が`supports_route_coloring:true`を持つ暗黙の契約に依存している。バックエンド側でそのフラグをfalseにする、あるいは軸自体をunpublishする変更が起きても検知手段が無く、初期選択のルート色分けモードが静かに`STATIC_MODES[0]`(勾配)等へ変わり、ユーザーが気づかないまま挙動が変わる。

- **file**: `frontend/src/components/Map/mapLayers.ts`
  **line**: 227（`MapLayerDescriptor.panelHintDetail`宣言）
  **category**: simplification（デッドコード） / **severity**: P3
  **summary**: `panelHintDetail`フィールドはインターフェースに宣言され詳細なコメントも付いているが、`buildMapLayers()`が返す配列のどのレイヤーもこのフィールドを設定しておらず、消費者(レンダリング側)も存在しない。
  **failure_scenario**: 旧「車ストレス専用3レシピパネル」時代の名残がインターフェースに残り続けることで、新規開発者が「このフィールドを設定すればパネルに内訳が出る」と誤解して実装しても何も表示されず、原因調査に時間を浪費しうる。

- **file**: `frontend/src/components/Map/windAxisLayer.ts`
  **line**: 80-87（`WIND_AXIS_THRESHOLDS`）
  **category**: altitude / **severity**: P3
  **summary**: 他のramp軸(`axisLayers.ts`の`RampAxis.thresholds`)はすべて`axis-catalog.json`(バックエンドのAXIS_DEFINITIONS)から動的に取得するのに対し、windAxisレイヤーのしきい値`[-6, -2, 2, 6]`だけがフロント側にハードコードされている。
  **failure_scenario**: コメント自体が「暫定値」「T406以降の課題」と認めており許容範囲内だが、将来wind軸のしきい値をbackend側だけ調整した場合にこのファイルの追従漏れが発生しやすい(T180・T185・T218のOpenAPIドリフトと同種のパターン)。

- **file**: `frontend/src/components/Map/precipitationNowcast.ts`(233-249: precipitationGridToCellFeatureCollection), `windPenalty.ts`(37-55: windPenaltyGridToCellFeatureCollection), `windLayer.ts`(147-163: windGridToFeatureCollection)
  **category**: reuse / **severity**: P3
  **summary**: 「格子点配列をループし、値欠損はスキップし、gridCellRing(またはPoint)でFeatureを1件push」というほぼ同一のループが3ファイルに個別実装されている。
  **failure_scenario**: 直接のバグではないが、「1点の欠損で全体を落とさない」という共通方針を変更する場合、3箇所すべてを揃って直す必要があり、共通化されている部分(gridCellRing)とされていない部分が中途半端に混在している。

- **file**: `frontend/src/components/Map/routeSegmentChartPopup.ts`
  **line**: 87-90
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: `export`されている`buildAxisDifficultyRadarSvg(entries)`は`n=entries.length`で即座に`angleStep=(2*Math.PI)/n`を計算しており、`n===0`だと`Infinity`、`n<3`だと破綻した座標を無警告で生成する。呼び出し元は`entries.length>=3`のときのみ呼ぶ契約だが、関数内部では強制されていない。
  **failure_scenario**: 現状唯一の呼び出し元は正しくガードしているため実害は無いが、公開関数として他から`n<3`で直接呼ばれると`NaN`座標を含むSVG文字列が生成されうる。

**総評(担当エージェント)**: MapLibre expression構築ロジック自体は`case`/`all`式の遅延評価を正しく利用しており演算ロジックの誤りは見当たらなかった。指摘の大半は「片側import原則の徹底不足」「暗黙の契約への依存」「一部失敗系統の整理漏れ」に集中。

---

## 5. backend/app/api/ + backend/app/batch/ (28ファイル、4,315行)

### P1

- **file**: `backend/app/api/routers/weather.py`(L53-57, 76-83, 97-101, 115-123, 138-142, 177-181, 209-215)ほか `routes.py`(L46-50, 247-251)・`basemap.py`(L20-24, 38-42)・`jma_tile.py`(L17-21)
  **category**: reuse / simplification / **severity**: P1
  **summary**: 「`check_rate_limit`→失敗なら`record_rate_limit_rejection`→`HTTPException(429,...)`」の5行ブロックが`weather.py`だけで7箇所、api/routers/全体で計12箇所ほぼ同一のままコピペされている。
  **failure_scenario**: `_tile_validation.py`(路面/POI/事故タイルの`check_tile_rate_limit`)という「同じ処理の重複はここへ切り出す」前例が既にリポジトリ内に存在するのに、非タイル系エンドポイントには適用されていない。429メッセージ文言やログ記録の仕方を将来変える際、12箇所すべてを手で揃える必要がある。

- **file**: `backend/app/api/routers/axis_admin.py`(L177-245、特にL209-217の`_check_materials_are_known`) ／ 参照先 `backend/app/domain/axis_definitions.py`(L118-138 PriorityCondition, L583, L671)
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: `AxisDefinitionPayload._check_materials_are_known`は`shape`が参照する材料は検証するが、`priority_overrides[*].material`(0次条件)は一切検証しない。
  **failure_scenario**: 軸スタジオで`priority_overrides`に材料idをタイプミスして保存しても201/200で成功する。評価時`materials.get(override.material)`は`None`を返し、`_priority_override_matches_scalar(None, equals)`は常に`False`になるため、その0次条件は全Edgeで恒久的に不発動のまま何のエラーも出ない。このバリデータ自身のdocstringが「未知の文字列を送っても通ってしまっていた抜け穴」として`shape`向けに防ごうとしたのと同型のバグが`priority_overrides`側にだけ残っている。

### P2

- **file**: `backend/app/api/routers/axis_admin.py`(L247-270 `to_definition`, L288-307 `_to_response`)
  **category**: conventions（同期ペア） / simplification / **severity**: P2
  **summary**: `to_definition()`のdocstringは「create/update両エンドポイントが同じフィールドを手書きコピーしており2箇所同時に直す必要があった」ことを1箇所へ集約したと書いているが、読み取り側`_to_response()`は依然として全15フィールドを手動コピーしている。
  **failure_scenario**: `AxisDefinitionFields`へフィールドを追加すると`to_definition()`と`_to_response()`の2箇所を同時に直す必要がある状態は変わっていない。CLAUDE.mdが名指しで警告する「同期ペアの片側更新漏れ」と同じ形のリスクが、このコミット自身が「解決した」と主張する箇所に残っている。

- **file**: `backend/app/batch/import_accidents.py`(L107-111)・`import_pbf.py`(L177-182) ／ `precompute_edge_attribute_counts.py`(L75-76)・`precompute_elevation_attributes.py`(L55-56)・`precompute_way_attribute_counts.py`(L60-61)
  **category**: reuse / **severity**: P2
  **summary**: asyncpgコマンドステータス文字列をパースする`_status_count`が2ファイルに、`_chunked`(リストのチャンク分割)が3ファイルにそれぞれ同一実装のまま重複している。
  **failure_scenario**: `_common.py`は正にこの種の重複を解消するために新設されたモジュール(「4バッチに独立実装として増殖していた」)であるにもかかわらず、その後に追加された`_status_count`/`_chunked`は同じ轍を踏んでいる。将来どちらかの実装だけ修正されると挙動が食い違う。

- **file**: `backend/app/batch/match_designations.py`(L143 `_MATCH_SQL`実行 と L163 `_LATEST_SUCCEEDED_OSM_RUN_ID_SQL`実行の間)
  **category**: correctness（並行実行時の境界条件） / **severity**: P2
  **summary**: 実際のマッチングを実行した「後」に、系譜追跡用の`source_osm_import_run_id`を別クエリで取得している。
  **failure_scenario**: この2クエリの間に新しいPBF取込が完了すると、`designation_attributes.source_osm_import_run_id`は実際にマッチングへ使われたスナップショットより新しいrun idを記録してしまう。改善計画T351の派生データ系譜追跡が前提とする保証が壊れる。運用上バッチを同時実行しない前提であれば実害は小さいが、ガードもコメントも無い。

- **file**: `backend/app/api/routers/basemap.py`(L32-44 `basemap_refresh`)
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: 基礎地図・路面タイルのファイルキャッシュを丸ごと消す`POST /api/basemap/refresh`が認可不要(レート制限のみ)。
  **failure_scenario**: `axis_admin.py`・`debug_admin.py`が導入したBasic認証パターンと異なり、この破壊的操作は依然として無認証。複数の発信元から緩やかに叩き続けられると、外部サービスへの再問い合わせとディスク再書き込みが常態化し「キャッシュが常に温まらない」状態を意図的に作り出せる。

- **file**: `backend/app/api/routers/health.py`(L101-137 `db_status`)
  **category**: conventions（認可パターンの一貫性） / **severity**: P2
  **summary**: migration適用状況・主要テーブル行数・最新import run状態を返す`GET /api/debug/db-status`が無認証で公開されている。
  **failure_scenario**: 秘匿情報や座標は含まないが、`axis_admin.py`/`debug_admin.py`が「運用系の内部状態を扱うAPIは認可必須」という方針へ寄せている流れの中で本エンドポイントだけが取り残されている。migration未適用状況やテーブル行数は攻撃対象の偵察情報になりうる。

- **file**: `backend/app/api/routers/axis_admin.py`(L387-389 `unpublish_axis_definition`)
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: `service.unpublish(axis_id)`成功直後、`assert definition is not None`で存在保証をしている。
  **failure_scenario**: Pythonを`-O`/`PYTHONOPTIMIZE`付きで実行するとassert文は丸ごと削除される。将来「unpublish成功直後にgetがNoneを返す」ケースが生まれた場合、この行は無言でスキップされ`_to_response(None)`が未処理のAttributeErrorで素の500になる。

### P3

- **file**: `backend/app/batch/import_pbf.py`(L381-389, L432-456)・`import_accidents.py`(L213-244)・`import_designations.py`(L287-313)
  **category**: correctness（再実行安全性） / **severity**: P3
  **summary**: `*_import_runs`テーブルへ`status='running'`でINSERTし成功/失敗時にUPDATEする設計だが、プロセスがUPDATE前にクラッシュ(OOM・強制終了等)すると当該run行が`running`のまま永久に残る。
  **failure_scenario**: `GET /api/debug/db-status`はこの最新run行のstatusを「バッチが正常に走ったか」の判断材料として使うため、孤立した`running`行があると運用者が「今まさに実行中」と誤認し続ける。タイムアウトによる自動的な`failed`への遷移や次回実行時の検知が無い。

- **file**: `backend/app/api/dependencies.py`(L49-56 `client_id`)
  **category**: correctness（境界条件） / **severity**: P3
  **summary**: `request.client`がNoneのとき、レート制限キーが固定文字列`"unknown"`にフォールバックする。
  **failure_scenario**: リバースプロキシの設定不備やテスト環境等で`request.client`が取れないリクエストが複数発生すると、本来別クライアントであるべきリクエスト群が同一レート制限バケットを共有し、無関係な利用者同士が互いの429を誘発しうる。

- **file**: `backend/app/api/routers/region.py`(L146-166 `region_axis_inspector`) ／ `backend/app/api/routers/_tile_validation.py`(L17-28 `check_tile_rate_limit`)
  **category**: altitude / **severity**: P3
  **summary**: タイル配信(z/x/y座標)向けに設計された`check_tile_rate_limit`を、座標を持たないPOST JSON APIの`axis-inspector`がそのまま流用している。
  **failure_scenario**: 実害は無いが、命名と実装意図(タイル)が呼び出し実態(単一Way検索)とずれており、将来「タイル固有の処理」をこの関数へ足すと`axis-inspector`にも意図せず波及する。

- **file**: `backend/app/api/routers/debug_admin.py`(L42-50 `read_recent_logs`)
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: `limit`クエリパラメータに上限チェックが無い(`int | None`のまま`lines[-limit:]`)。
  **failure_scenario**: リングバッファ自体が最大1000件に制限されているため実害は小さいが、`limit`に負数を渡した場合の挙動(意図しないスライス結果)が未検証・未ガードのまま。認可必須のadmin APIのため深刻度は低い。

- **file**: `backend/app/batch/import_accidents.py`(L178-182 `run_import`)・`import_designations.py`(L253-259 `run_import`)
  **category**: efficiency / **severity**: P3
  **summary**: 年ごと(accidents)・kind×都道府県ごと(designations、最大14件)のファイルダウンロードが`for`ループ内で`await`により直列実行されている。
  **failure_scenario**: 各ダウンロードは独立した外部URLへのGETのため`asyncio.gather`等での並列化余地があるが、現状は1件ずつ待ってから次へ進むため対象年数・都道府県数が多いほどバッチ全体の所要時間が線形に伸びる。低頻度実行のバッチではあるが改善の明確な余地。

- **file**: `backend/app/batch/precompute_edge_attribute_counts.py`(L106 `_fetch_source_run_ids` と L131-159 チャンクループ)
  **category**: correctness（並行実行時の境界条件） / **severity**: P3
  **summary**: 系譜追跡用のrun idをチャンク処理開始「前」に1回だけ取得し、以降全チャンク(数十分規模になりうる)で使い回す。
  **failure_scenario**: チャンク処理中に新しいaccident/osm取込が完了すると、実クエリは常に最新DB状態を読むため、実際に計算に使われたデータと記録されたrun idが乖離しうる。match_designations.pyのケースより実行時間が長い分、乖離の発生確率も高い。

**総評(担当エージェント)**: 総行数4,315行(28ファイル、`__init__.py`2ファイルは0行)。

---

## 6. frontend/src/app/ (9ファイル、2,016行)

- **file**: `frontend/src/app/page.tsx`
  **line**: 1046-1053
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: `conditionsDirty`(「条件が変更されています」ヒント)が目的地モードの`waypoints`/`destination`の変更を検知しない。
  **failure_scenario**: 目的地モードでルート生成後、地図上で経由地を追加・削除・目的地を変更しても、比較対象は`latitude/longitude/routeMode/(loopのみ)distanceKm/weightsKey`のみで経由地集合を含まない。ユーザーは「まだ古い指定のまま生成されたルートを見ている」ことに気づけず、意図と異なる候補をそのまま利用してしまう可能性がある。

- **file**: `frontend/src/app/page.tsx`
  **line**: 1433-1445（比較対象: 1150-1152, 1168-1180）
  **category**: correctness（呼び出し元・呼び出し先の整合性） / **severity**: P2
  **summary**: モバイル操作バー用の`RouteForm`呼び出しにだけ`progressLabel`propが渡されていない。
  **failure_scenario**: デスクトップ側は`progressLabel={generationProgressLabel}`を渡しているが、モバイル側には同じpropがない。現状は`RouteForm.tsx`の`compact`分岐が`progressLabel`を無条件で無視するため実害は顕在化していないが、そちらが将来修正されればモバイルだけ「順番待ち...」「生成中...(N秒経過)」が出ない回帰が起き、呼び出し元だけを見ると気づきにくい。

- **file**: `frontend/src/app/page.tsx`
  **line**: 889-897
  **category**: altitude / reuse / **severity**: P2
  **summary**: `isDynamicGroupLayer`が、`mapLayers.ts`に既にある`dataNature === "dynamic"`と本質的に同じ情報をレイヤーIDの手書き列挙で再実装しており、しかも`windAxis`(`dataNature`は"dynamic")だけを暗黙に除外している。
  **failure_scenario**: 新しい動的レイヤーを`mapLayers.ts`側へ`dataNature:"dynamic"`として追加した開発者が889-897行のリストへの追記を忘れると、「[設定はサイドバー]」という誤った説明文が付く／凡例が本来出るべきところで出ない、という不整合が起きる。`windAxis`が意図的に除外されている理由(T414の暫定対応)もこの箇所にはコメントされていない。

- **file**: `frontend/src/app/page.tsx`
  **line**: 852-879
  **category**: simplification / **severity**: P3
  **summary**: `summary`/`legendDetails`の組み立てがレイヤーIDごとに5〜8段ネストした三項演算子チェーンになっている。
  **failure_scenario**: 「レイヤーを追加したらsummaryの対応をここへ1行足すだけでよい」というコメントがあるが、実際には同種のチェーンが`legendDetails`にも別途あり、加えて`isDynamicGroupLayer`列挙・`DEFAULT_LAYER_VISIBILITY`にも追記が要る。3〜4箇所のうち1箇所だけ更新して他を忘れるヒューマンエラーが起きやすい。

- **file**: `frontend/src/app/page.tsx`
  **line**: 845-851, 902, 1029
  **category**: correctness（複数の関連stateの不整合） / **severity**: P3
  **summary**: 「風(評価軸)」チップは`hasDetail`(ルート確定)後に機能停止するが、チップ自体は直前の`on`状態のまま表示され続ける。
  **failure_scenario**: `showWindAxis = layerVisibility.windAxis && !hasDetail`により地図描画・データ取得は止まるが、`overlayLayers`の`on`値は`layerVisibility.windAxis`そのままのため、チップは「選択中(ON)だが無効化されている」という見た目になる。ユーザーは「ONのはずなのに地図に何も出ない」状態にdisabledのツールチップを読むまで気づけない。(参考: 今回の/simplifyで`disabledReason`統合を実施したが、この「on状態とdisabled状態の見た目の不一致」自体は別課題として未対応)

- **file**: `frontend/src/app/page.tsx`
  **line**: 647-661
  **category**: reuse / **severity**: P3
  **summary**: `handleRoadAxisSetHidden`と`handleStaticFilterAxisSetHidden`が実装として完全に同一(軸idをキーに非表示配列を丸ごと差し替えるだけ)。
  **failure_scenario**: コメントは型安全のための意図的な重複と説明しているが、どちらか一方だけにバグ修正・機能追加をして他方へ反映し忘れる「片方だけ更新し忘れる」パターンのリスクは残る。

**総評(担当エージェント)**: `MapView`への大量のprops・`getRouteStyleMode`のフォールバック・`getRoadFilterAxis`の参照安定性はいずれも問題なしと確認。CLAUDE.md/frontend/AGENTS.mdの明確な違反は無し。ログ方針も遵守。

---

## 7. backend/app/services/ (21ファイル、4,230行)

### P1

- **file**: `backend/app/services/jma_amedas_service.py`
  **line**: 148-157（呼び出し元 `backend/app/main.py:74-78`）
  **category**: correctness（欠けているガード）／conventions（docs/logging.md） / **severity**: P1
  **summary**: `refresh_all_stations()`が観測所テーブル・最新時刻・観測値マップいずれかの取得失敗で`return 0`する3箇所に、WARNINGログが一切無い。
  **failure_scenario**: JMAアメダスAPIの仕様変更・障害等で各fetch関数が空応答を返し始めても、この関数は`0`を返すだけで例外にならず、呼び出し元も`count=0`を`.debug`でしか出さない(本番では実質出力されない)。10分間隔バッチが継続的に空振りし続けても`/api/debug/stats`に計上されず、docs/logging.md「WARNING|常時|候補0件などユーザー影響のある準異常」に反して、TTL(15分)切れ後は全国のWBGT/アメダスバッジがフロントで一斉に502化するまで誰も気づけない。

- **file**: `backend/app/services/region_service.py`
  **line**: 269-278（`_get_tile`内の`fetch_tile`）
  **category**: conventions（docs/logging.md） / **severity**: P1
  **summary**: 高頻度に発生しうる「取込範囲外」WARNINGが`debug_log`の抑制付き`_throttled_warning`/`log_throttled_warning`を経由せず、素の`logger.warning`直呼びになっている。
  **failure_scenario**: docs/logging.md「同種の警告はカテゴリごとに毎分5件で抑制」という明文ルールに反する。地図タイルは通常操作でも毎分数百イベントになりうる高頻度経路であり、ユーザーが未取込エリアを地図でパン・ズームし続けるだけで抑制なしのWARNINGが1分間に数百行Renderのログに出力され、他の重要な障害ログが埋もれる。同型の未抑制`logger.warning`は`graph_service.py:97-101`・`accident_service.py:40`・`wind_way_service.py:96,117,122`にも存在し、同じ規約違反パターンが横展開している。

### P2

- **file**: `backend/app/services/elevation_attribute_service.py`
  **line**: 58-90
  **category**: correctness（欠けているガード） / **severity**: P2
  **summary**: GSI標高APIの一時障害で全点`None`になったEdgeも、「全フィールドNone」の`ElevationAttribute`がそのままDBへ永続化され、以後リトライされない。
  **failure_scenario**: `get_attributes_for_graph`は「既にテーブルに行がある」ことだけを再取得スキップの判定に使う。GSI DEMサーバの一時的な障害でその時だけ全点`None`になっても例外を出さず「標高データなし」を意味する空の`ElevationAttribute`がそのままUPSERTされる。GSI復旧後もこのEdgeは「キャッシュ済み」として扱われ続け、勾配軸(gradient)の評価が永続的に欠落したままになる。本来は「守備範囲外(海上等)」と「一時障害」を区別してキャッシュすべきだが、両者を区別する仕組みが無い。

- **file**: `backend/app/services/axis_registry_service.py`
  **line**: 148-179（`create`）, 181-204（`update`）
  **category**: correctness（並行実行の安全性） / **severity**: P2
  **summary**: `list_all_with_sort_order`での読み取りと`upsert`+`commit`の間にロックが無いcheck-then-actで、複数の管理セッション(軸スタジオ)が同時に同一`axis_id`をcreate/updateするとTOCTOUレースになる。
  **failure_scenario**: 2つのリクエストがほぼ同時に`create()`へ入ると両方とも「existing に無い」と判定してしまい、意図した`ValueError`ではなく後勝ちのUPSERTがDB制約に依存した非決定的な結果になるか、片方が捕捉されないDB例外で500になる。`update()`も`check_publish_immutability`判定後にupsertするまでの間に別セッションがunpublish/deleteすると想定外の状態遷移を許してしまう。

### P3

- **file**: `backend/app/services/region_service.py`
  **line**: 356, 388, 411
  **category**: conventions（docs/logging.md） / **severity**: P3
  **summary**: `get_axis_inspector`/`get_accident_years_covered`/`get_material_values`のDB障害WARNINGも同様に未抑制(`_throttled_warning`未経由)。
  **failure_scenario**: 単発クリック操作契機のため頻度は低いが、PostGIS障害が継続する間はユーザー操作のたびにWARNINGが無制限に出続け、DB障害時にログが埋まりやすい状況を悪化させる。上記region_service.py:271-277と同根の問題。

- **file**: `backend/app/services/graph_service.py`
  **line**: 24-30, 61-77（`_warming_tiles`）
  **category**: efficiency / **severity**: P3
  **summary**: split直後のタイルキャッシュ「温め」がバックグラウンドタスクとして発火するが、失敗時に再試行の仕組みが無く`_warming_tiles`から即座に外れるだけ。
  **failure_scenario**: 一時的なDB接続エラーで温めに失敗した場合(WARNINGログのみ)、次にそのタイルへアクセスが来るまで再試行されない。実害は「次のリクエストがDB読み出しにフォールバックするだけ」で機能的には問題ないが、「2回目リクエストからキャッシュヒット」という設計目標をこの経路だけ達成できない。

- **file**: `backend/app/services/wind_way_service.py`
  **line**: 82-133
  **category**: altitude / reuse / **severity**: P3
  **summary**: `get_way_wind_penalties`は`region_service.py`の`_get_tile`/`serve_cached_tile`パターン(ファイルキャッシュ確認→ミス時fetch→WARNING)と非常に似た構造を持つが、`serve_cached_tile`の骨格(`tile_serving.py`)を再利用せず個別実装している。
  **failure_scenario**: 直接のバグではないが、`tile_serving.py`のdocstringが謳う「重複していたため骨格を共有する」という改善計画の対象から本ファイルだけ漏れており、今後road-surface/poi/accidentタイル側の骨格に手を入れた際、風タイル配信だけ追従漏れが起きるリスクがある。

- **file**: `backend/app/services/route_scorer.py`
  **line**: 61
  **category**: correctness（潜在的だが低リスク） / **severity**: P3
  **summary**: `weight_sum == 0`の厳密浮動小数点比較。
  **failure_scenario**: 現状`_weights`は非負の設定値の和のみで構成されるため実害は無いが、将来的に負の重みが許容されるよう仕様変更された場合、加減算による浮動小数点誤差で本来「合成不能」として`None`にすべきケースが極小値での正規化計算に流れる可能性がある。

- **file**: `backend/app/services/openrouteservice_engine.py`
  **line**: 314-320
  **category**: simplification / **severity**: P3
  **summary**: 境界外ガードを撤去した経緯のコメントが長大(改善計画T78参照)で、該当箇所自体にロジック上の懸念は無い。
  **failure_scenario**: 実害なし。コメントの妥当性は前提が将来のリファクタで崩れないことに依存しており、前提が壊れた場合は沈黙せず直ちに例外化する設計(安全側で問題ない)。

**総評(担当エージェント)**: `road_graph_engine.py`の浮動小数点比較・`wind_way_service.py`のNone/[]区別・`openrouteservice_engine.py`の逐次await(同一AsyncSession制約による意図的逐次化)・各serviceのlog_external_call経由の遵守は、いずれも調査の結果問題なしと確認。総行数4,230行(21ファイル)。

---

## 8. frontend/src/hooks/ + services/ + lib/ + types/ (generated除く、38ファイル、3,156行)

### P1

- **file**: `frontend/src/services/weatherApi.ts:15`、`regionApi.ts:5`、`routeApi.ts:14`、`materialCatalogApi.ts:4`、`axisCatalogApi.ts:4`、`debugStatsApi.ts:3`、`healthApi.ts:1`
  **category**: conventions（片側import原則） / reuse / **severity**: P1
  **summary**: `const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";`が一字一句同一のまま7サービスファイルへ複製されている。
  **failure_scenario**: `lib/backendInternalUrl.ts`はまさにこの姉妹定数(サーバー側`BACKEND_INTERNAL_URL`)について「独立に手書きしていたことが過去の本番502インシデントの原因だった」と明記し単一ソース化済みだが、クライアント側の`NEXT_PUBLIC_API_URL`フォールバックには同じ対処がされていない。将来フォールバック値やバリデーションを変更する際、7箇所のうち1つを直し忘れれば環境差分バグが再発する——まさに`backendInternalUrl.ts`のコメントが警告している事故パターンそのもの。

- **file**: `frontend/src/hooks/useDynamicWeatherLayers.ts:237-258`（キキクル）, `:262-283`（線状降水帯予測マップ）
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: 危険度分布(キキクル)・線状降水帯予測マップのフェッチはエラー時`debugLog`のみでエラーstateを持たず、`dynamicLayerError`に一切反映されない。
  **failure_scenario**: 同じファイル内の降水ナウキャスト(`nowcastError`)・雷ナウキャスト(`thunderNowcastError`)は同型の失敗を明示的に`dynamicLayerError`へ集約しUIへ表示するのに対し、キキクル・線状降水帯だけは黙って何も表示されない。JMA側APIが一時的に落ちた場合、ユーザーは「危険なし」なのか「取得失敗」なのか区別できず、安全関連情報の欠落に気づけない。

### P2

- **file**: `frontend/src/hooks/useWeatherGrid.ts:35`、`useWindAxisPenalties.ts:16-19`、`useDynamicWeatherLayers.ts:65-68`
  **category**: conventions（片側import原則） / **severity**: P2
  **summary**: `500`msのデバウンス定数が3ファイルへ独立定義され、いずれも「◯◯と同じ値・揃える」というコメントだけで結びつけられている(今回の/simplifyで追加した`WIND_BEARING_DEBOUNCE_MS`もこの連鎖に含まれる)。
  **failure_scenario**: `docs/complexity-review-2026-08-16.md`末尾の設計原則2「数値定数は必ず片側がもう片側をimportする。『◯◯と揃える』というコメントで2箇所に同じ値を書くことを禁止する」に文字どおり抵触。どれか1つだけ値を変えても他の2箇所が追従せず、地図パン操作とコンパススライダー操作でデバウンス感覚がバラバラになりうる。

- **file**: `frontend/src/hooks/useAxisCatalog.ts:160-180`、`useMaterialCatalog.ts:16-44`、`useMaterialValues.ts:33-51`、`useDynamicWeatherLayers.ts`(5箇所)
  **category**: reuse / altitude / **severity**: P2
  **summary**: 「`cancelled`フラグ＋`Promise`＋`catch`握りつぶし＋クリーンアップ」という同型のフェッチ骨格が最低8箇所で個別に手書きされている。
  **failure_scenario**: 新しいデータソースを追加するたびにこの15〜25行をコピペしており、`cancelled`判定を1箇所書き漏らすとレースコンディションが再発しうる。加えて`useWeatherConditions.ts`は同じ目的を`requestId`連番方式で実装しており、同一アプリ内に「cancelledブール」「requestId連番」の2流儀が並存し、新規参入者がどちらに倣うべきか判断しづらい。

- **file**: `frontend/src/services/regionApi.ts:112-149`（`fetchAxisInspector`）と`:203-245`（`refreshBasemapCache`）
  **category**: reuse / simplification / **severity**: P2
  **summary**: 同一ファイル内の2関数が「fetch→通信エラーtry/catch→durationMs計算→requestId抽出→!response.ok処理」というほぼ同型の約30行ブロックを独立に持つ。
  **failure_scenario**: `routeApi.ts`は同等のパターンを`postJson`という共通ヘルパーへ切り出し済みなのに対し、`regionApi.ts`はファイル内共通化すらしていない。今後3つ目のPOST系エンドポイントを追加する際、また新たにこのブロックがコピペされる可能性が高い。

- **file**: `frontend/src/hooks/useMaterialCatalog.ts:16-44` と `useAxisCatalog.ts:123-139`
  **category**: correctness（呼び出し元・呼び出し先の整合性） / **severity**: P2
  **summary**: `useAxisCatalog`はコードレビュー指摘を受け「同時マウント時の二重フェッチ」対策としてモジュールレベルdedup機構(`inFlightCatalogFetch`)を追加したが、同じ設計思想のはずの`useMaterialCatalog`にはこの対策がない。
  **failure_scenario**: 現状`useMaterialCatalog`の呼び出し元は単一マウントのみのため顕在化しないが、将来材料カタログを2箇所以上で同時マウントする機能を追加すると、`useAxisCatalog`で一度発生し修正済みのバグと同型の二重フェッチが再発する。

### P3

- **file**: `frontend/src/hooks/useStoredState.ts:54-63`
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: 復元effectは`raw == null`(保存値なし)の場合何もしないため、`key`が動的に変化するケースでは前の`key`の値が`value`に残り続け`defaultValue`へリセットされない。
  **failure_scenario**: 現在の全呼び出し元(page.tsx)は静的文字列keyのみのため顕在化していないが、汎用フックとして将来「選択中エンティティごとに永続化キーを変える」呼び出し方をされた場合、新しいkeyに保存値がなければ黙って直前のkeyの値を引き継いでしまう。

- **file**: `frontend/src/hooks/useMaterialValues.ts:24-51`
  **category**: correctness / **severity**: P3
  **summary**: `materialId`が`null`へ戻ったときeffectは早期returnし`state.materialId`を更新しない。同じ`materialId`へ後で戻ると、レンダー時導出`values`が「一致」判定になり新規フェッチ完了前の古いキャッシュ値を一瞬返す。
  **failure_scenario**: 機能的には大きな実害はないが、同材料への再選択時に古い値がフェッチ完了前に一瞬表示される可能性がある。

- **file**: `frontend/src/lib/evaluationAxes.ts:61-71`（`PREFERENCE_AXIS_DESCRIPTIONS`）, `:84-93`（`?? ""`フォールバック）
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: `PREFERENCE_AXES`は`SECONDARY_AXES`から軸を導出するが、対応する説明文が`PREFERENCE_AXIS_DESCRIPTIONS`に無い場合`?? ""`で黙って空文字になる。テストもこの一致を検証していない。
  **failure_scenario**: 新しい公開軸が`SECONDARY_AXES`へ追加された際、このRecordへ説明文を足し忘れても、ビルドエラーにも実行時警告にもならず、ルート設定画面のその軸の説明欄だけが無言で空欄になる。

- **file**: `frontend/src/services/axisAdminApi.ts:23-68`（`adminFetch`）, `frontend/src/lib/fetchJson.ts:30-74`, `frontend/src/services/routeApi.ts:16-78`（`postJson`）
  **category**: reuse / **severity**: P3
  **summary**: 3つの独立実装が「fetch→通信エラー処理→!response.ok→errorBody解析→formatErrorDetail→throw」という同一パターンを持つ。
  **failure_scenario**: エラーメッセージ整形ロジックに将来変更が入った際、3箇所のうち1つを直し忘れると軸スタジオ・ルート生成・区間インスペクタでエラー表示の一貫性が崩れる。

- **file**: `frontend/src/services/debugStatsApi.ts:5-35`
  **category**: correctness（呼び出し先との整合性） / **severity**: P3
  **summary**: `ExternalCallStats`/`DebugStats`が手書き型として二重管理されている。backendの`/api/debug/stats`はOpenAPIスキーマ上無型応答のため「生成型を正とする」方針を適用できない正当な例外ではある。
  **failure_scenario**: backend側がこのエンドポイントへフィールドを追加・削除・改名しても、コンパイル時に一切検知できず、フィールド名の食い違いは実行時に初めて気づく(値が`undefined`になるだけで例外も出ない)。

**総評(担当エージェント)**: 既存のデバウンス・TTLキャッシュ・タイル単位バッチフェッチは丁寧に設計されており効率性の独立指摘は無し。`page.tsx`側のgenerated型との対応関係も目立った契約不一致は無し。総行数3,156行(38ファイル)。

---

## 9. frontend/src/components/ (Map除く、30ファイル、6,224行)

### P0

- **file**: `frontend/src/components/AxisStudio/AxisComposer.tsx`
  **line**: 321, 328, 351-352, 806-807, 924
  **category**: correctness（欠けているガード） / **severity**: P0
  **summary**: 材料カタログが0件のとき`materialOptions[0].id`が未ガードでAxisComposerのマウント自体がクラッシュする。
  **failure_scenario**: `emptyDraft()`・`draftFromExisting()`は`materialOptions[0].id`を無条件参照する(`useState<Draft>(() => ...)`の初期化子内、マウント直後に実行される)。呼び出し元の`useMaterialCatalog()`は2026-08-25の修正で「取得成功したがmaterialsが0件」の場合に静的フォールバックへ留まらず空配列をそのままsetMaterialsするよう仕様変更済み。backend側の`material_catalog.py`が運用上の一時的な状態等で0件を返すと、`materialOptions[0]`が`undefined`となり`.id`アクセスで`TypeError`が発生し、軸スタジオの新規作成・既存軸の編集モーダルどちらも開けなくなる(エラー表示すら出ない)。

### P1

- **file**: `frontend/src/components/AxisStudio/AxisComposer.tsx`
  **line**: 519-557（`validateStep`に折れ点の順序チェックが存在しない）、978-991、198-208
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: 折れ点(breakpoints)のx昇順チェックが無く、backendの前提(x昇順必須)を静かに破れる。
  **failure_scenario**: `BreakpointCurveEditor`のドラッグ操作や数値入力行は、折れ点のx値が昇順かどうかを一切検証せず保存できる。一方backend側`evaluate_breakpoint_linear`は「breakpointsはx昇順の(x,y)組」であることを明記した上で`np.interp`にそのまま渡しており、xが昇順でないと補間結果が黙って不正になる(エラーにはならない)。同種の懸念を持つ`displayThresholdsOverride`にはT404でbackend・frontend双方に昇順チェックが追加されたのに、より根幹の`breakpoints`自体には同じガードが漏れている。ユーザーが曲線エディタでうっかり点を入れ替えると、軸の難易度スコアが意図と逆転する等の不具合が保存後まで気づかれない。

- **file**: `frontend/src/components/AxisStudio/AxisComposer.tsx`
  **line**: 510-512（`axisTermOptions`）
  **category**: correctness（欠けているガード） / **severity**: P1
  **summary**: 「かけあわせ評価」の軸参照は自己参照のみ除外し、多段の循環参照(A→B→A)を作成前に警告しない。
  **failure_scenario**: `axisTermOptions`は`draft.axisId`との一致のみを除外条件にしており、既存軸同士が循環参照する組み合わせをGUI上何の警告もなく保存できる。backend側`axis_admin.py`のバリデータ群にも保存時の循環検出は無く、循環検出は評価時のトポロジカルソート(`AxisDependencyCycleError`)でのみ発生する設計。管理者が軸スタジオで誤って循環参照を作成すると保存は成功し、後日一般ユーザーがルート生成を行った際に初めて評価時エラーとして表面化する。

### P2

- **file**: `frontend/src/components/SystemStatusPanel/SystemStatusPanel.tsx`
  **line**: 43-58
  **category**: correctness / **severity**: P2
  **summary**: `loading`状態が`getFrontendVersion()`の`.finally()`にしか紐付いておらず、backend統計取得中でも「更新中…」表示が消える。
  **failure_scenario**: `fetchAll`は`getDebugStats()`と`getFrontendVersion()`を並行実行するが、`setLoading(false)`は後者の`.finally()`にのみ付いている。フロントエンド情報の取得が先に完了しバックエンド統計取得がまだ継続中の場合、「更新中…」ラベルが消え「更新」ボタンが再度押せる状態に戻るが、バックエンドカラムはまだ何も表示されない空白のままになる。

- **file**: `frontend/src/components/RouteForm/RouteForm.tsx`
  **line**: 36
  **category**: conventions（設計原則1: 正準定義の手書きコピー禁止） / **severity**: P2
  **summary**: `MAX_DISTANCE_KM = 100`がbackendのPydantic制約の手書きコピーで、生成済みスキーマから導出されていない。
  **failure_scenario**: コメントで「backendのRouteGenerateRequest.distance_km(Field(gt=0, le=100))と一致させる」と明記しているとおり手動同期ペア。`types/generated/openapi.json`には既に`"distance_km": {"maximum": 100.0}`という同じ制約が生成物として存在するにもかかわらず、そこから読まず独立した定数として直書きしている。docs/design-review-2026-08-15.md原則1に反し、backendの上限値が変わった際にフロントのバリデーションだけ古いまま残るドリフトリスクがある。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.tsx`
  **line**: 235-252（`renderLegendSwatch`）
  **category**: reuse / conventions / **severity**: P2
  **summary**: `WidthSwatch.tsx`と同じ「太さ・線種スウォッチ」を独立に再実装しており、同じデータが2箇所で違う縮尺で表示される。
  **failure_scenario**: `WidthSwatch.tsx`は`entry.width`を`DISPLAY_SCALE=1.8`倍して表示するが、`renderLegendSwatch`は同じ`LegendEntry.width`を縮尺なしでバー高さに使う独自実装。同一の「道路の種類」凡例データが、サイドバーの地図の見え方パネル(太く見える)と地図上チップの▶内訳パネル(細く見える)とで視覚的に一致しないバーとして描画される。

- **file**: `frontend/src/components/ComparisonPanel/ComparisonPanel.tsx`
  **line**: 26-68（`METRIC_ROWS`）
  **category**: altitude / conventions（設計原則8: UI語彙カタログ集約） / **severity**: P2
  **summary**: ルート候補メトリクスのラベル・整形ロジックがカタログ化されず、`RouteList.tsx`と個別に食い違う書式で重複している。
  **failure_scenario**: docs/complexity-review-2026-08-16.md原則8はUI語彙表のカタログ集約を明記し、ComparisonPanelを過去の違反例として名指ししている。`pref`(重み)部分はT320でカタログ化されたが`METRIC_ROWS`は依然コンポーネント内のハードコード配列のまま。`RouteList.tsx`も同じフィールドを独立に整形しており、風の表示が食い違う(RouteListは符号付きで方向まで表現するが、ComparisonPanelは符号無しの生値のみ)。片方だけ文言修正されもう片方が古いままになるドリフトリスクがある。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.tsx`
  **line**: 302-361（`usePagedOverflow`内`registerViewport`/`registerTrack`）
  **category**: efficiency / **severity**: P2
  **summary**: refコールバックが毎レンダー新規生成され、再レンダーのたびに`ResizeObserver`を破棄・再構築している。
  **failure_scenario**: `registerViewport`/`registerTrack`が`useCallback`でメモ化されず毎回新しい関数として返されるため、参照が変わるたびにReactは旧ref→新refを呼び直し`rewireObserver()`が`ResizeObserver`のdisconnect＋新規observe＋同期`measure()`を都度実行する。状態変更が頻繁なコンポーネントで、そのたびに無関係なObserverの破棄・再構築コストが発生する。

- **file**: `frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx`
  **line**: 102-104
  **category**: correctness / efficiency / **severity**: P2
  **summary**: `lastWeights`が初回マウント時の`catalog.defaultWeights`(静的フォールバックの可能性あり)で固定され、非同期取得後の値と再同期されない。
  **failure_scenario**: `lastWeights`はマウント時の値(フェッチ未完了なら静的フォールバック値)を一度だけ取り込み、以後`catalog.defaultWeights`が実際のDB値へ更新されても再同期されない。ユーザーがまだ一度も触っていない軸のチェックを外して再度チェックすると、`handleToggle`が古い静的フォールバック値を使って復元してしまう可能性がある。

### P3

- **file**: `frontend/src/components/WindBearingSlider/WindBearingSlider.tsx`
  **line**: 59
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: `onChange`で`Number(next)`の結果が`NaN`になりうる経路に対するガードが無い。
  **failure_scenario**: ライブラリが数値以外(パース不能な文字列)を渡した場合に`NaN`をそのまま`windBearingDeg`へ伝播する。呼び出し元(page.tsx)側でのNaNガードも確認できておらず、風向のルート評価パラメータが不定値になる余地が残る。

- **file**: `frontend/src/components/MapOverlayControls/MapOverlayControls.tsx`
  **line**: ファイル全体（1-1491行）
  **category**: altitude / simplification / **severity**: P3
  **summary**: 汎用フック(`usePagedOverflow`・`useHoldRepeat`)・共通コンポーネント(`ChipButton`)・複数グループ種別の描画ロジックが単一ファイル約1,500行に集約されている。
  **failure_scenario**: docs/complexity-review-2026-08-16.md原則9がMapView.tsx/page.tsxに設けている行数閾値・分割判断のトリガーが、同程度の複雑さを持つこのファイルには適用されていない。`usePagedOverflow`・`useHoldRepeat`は本来他のスクロール可能UIでも再利用しうる汎用ロジックだが、ファイル内関数として閉じ込められている。

- **file**: `frontend/src/components/AxisStudio/AxisComposer.tsx`
  **line**: 918-926
  **category**: correctness（欠けているガード） / **severity**: P3
  **summary**: 材料追加ボタンのフォールバックが`termOptions[0]?.id ?? materialOptions[0].id`で、`materialOptions`自体が空の場合は依然クラッシュしうる。
  **failure_scenario**: P0指摘(emptyDraft)と同根の問題だが、こちらは「材料を追加」ボタン押下時にも同じ無guardな`materialOptions[0].id`参照が残っている。P0を仮に個別に直しても、この箇所が同種の未修正経路として残る。

**総評(担当エージェント)**: レビュー対象30ファイル、総行数6,224行。

---
