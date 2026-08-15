# パフォーマンスベンチマーク

`app/`のうちパフォーマンス上の懸念があった箇所（Road Graphルーティング、標高キャッシュ）を、
実際のOverpass/GSI/PostGIS接続無しで再現できる合成データに対して計測する。追加のpip依存（pytest-benchmark等）は増やさず、`_harness.py`の
`time.perf_counter`ベースの計測のみで完結する。`pytest`の通常のテストスイートには
含まれない（ファイル名が`test_*.py`ではないため自動収集されない）。

## 実行方法

`backend/`ディレクトリから:

```
.venv/Scripts/python -m benchmarks.run_all              # 全部（数分かかる）
.venv/Scripts/python -m benchmarks.bench_nearest_node    # 個別に1本だけ
.venv/Scripts/python -m benchmarks.bench_elevation_cache # 標高キャッシュ（数十秒〜）
```

## わかったこと（実測値、開発機での参考値。絶対値はマシン依存だが相対的な傾向は再現する）

1. **`cache_db`（標高SQLiteキャッシュ）が呼び出しごとに新規sqlite3接続を張り直していた
   → 修正済み**（`infrastructure/cache_db.py`）。`_connect()`が毎回`PRAGMA`+
   `CREATE TABLE IF NOT EXISTS`込みで接続を張り直していた実装を、スレッドローカルに接続を
   1本キャッシュして使い回す方式に変更した（`asyncio.to_thread`のデフォルトExecutorは
   ワーカースレッドを使い捨てないため、スレッドごとの使い回しが成立する。テストでの
   `DATA_DIR`/`DB_PATH`のmonkeypatchにも追従できるよう、キャッシュ時点のパスと現在の
   `DB_PATH`が食い違ったら張り直す形にしてある）。
   `bench_elevation_cache.py`実測: 800回の`get_elevation`呼び出しが
   **修正前 中央値5.6秒 → 修正後 中央値0.47秒**（約12倍）。比較用の単一接続実装
   （benchのみ、asyncio.to_threadのディスパッチも無し）は約17-40ms なので、残りの差は
   `asyncio.to_thread`が1呼び出しごとにスレッドプールへディスパッチするオーバーヘッド
   （こちらは今回対象外）。`ElevationAttributeService.get_attributes_for_graph`
   （480 Edge x 6点=2880回、ネットワークはスタブ化）はend-to-endで
   **修正前 中央値4.7秒 → 修正後 中央値1.2〜3.1秒**（開発機の負荷変動で幅があるが、
   一貫して改善）。

2. **`find_nearest_node`（`domain/routing.py`）は明示的に線形探索**（PostGIS空間インデックス
   未使用構成向けの実装。docstringに明記済みの既知のトレードオフ、**未修正**）。
   1リクエストあたり17回呼ばれる（`prepare`1回 + `trace_loop`2回x8方位）。実測: ノード
   20,164個の合成グラフで1呼び出し**中央値98ms** → 17回で**約1.7秒**。ノード8,100個の
   格子でも`trace_loop`フェーズ全体（線形探索17回 + Dijkstra24回）で**中央値866ms**、
   うち線形探索が約半分（448ms）を占める。修正するにはPostGISの空間インデックス
   （`ST_DWithin`等）またはKD-Tree等のインメモリ空間索引の導入が必要で、影響範囲が
   大きいため今回は対象外（README作成時点でユーザーへ改善候補として提示済み、未着手）。

3. **`RegionService.get_road_surface_tile`のMVTエンコードがイベントループを同期的に塞いでいた
   → 修正済み**。`tile_cache.get/set`（ディスクI/O）は`asyncio.to_thread`でラップされて
   いたのに、CPU専用の`encode_road_surface_tile`だけラップされていなかった箇所を
   `await asyncio.to_thread(encode_road_surface_tile, ...)`に変更した。
   `bench_event_loop_stall.py`実測（way=3000の密集タイル、心拍コルーチンの最大停止時間で
   計測）: 修正前は直接呼び出しで**1.3〜4.5秒**（実行時のシステム負荷でばらつくが、修正前は
   常に1秒超）他タスクを止めていたのに対し、修正後の`RegionService`をend-to-endで計測すると
   **65〜523ms**まで縮む（`encode_road_surface_tile`単体を`asyncio.to_thread`でラップした
   場合は35〜246ms）。絶対値はこのマシンの負荷変動でぶれるが、修正前後で常に一桁近く
   改善する関係は再現する。
   **2026-08-16追記**: 改善計画T22でOverpassフォールバックを撤去し、`encode_road_surface_tile`
   （Python側MVTエンコーダ）自体を`encode_empty_road_surface_tile`（空タイルのみを返す、
   way数に依存しない定数コスト）へ置き換えたため、この計測が対象としていたway数スケーリング・
   イベントループ停止の問題は構造的に発生しなくなった。`bench_vector_tile.py`・
   `bench_event_loop_stall.py`は役目を終えたため削除済み。この項目は当時の修正の記録として残す。

4. **`build_road_graph`（交差点分割）もリクエストのたびに（PostGIS未接続の既定構成では）
   再計算される**（**未修正**）。Way 40,044本・Node 20,164個の合成データで
   **中央値1.58秒**。PostGISキャッシュ（`repository`指定構成）を使えば再計算を避けられるが、
   dev環境にPostGIS接続が無く未検証だった（`docs/architecture.md`参照）→ **2026-08-15に
   ローカルPostGIS（東京都心データ取込済み）で実測、5番参照**。

5. **PostGIS経由の`GraphService.get_or_build_graph_with_attributes`（`docs/architecture.md`が
   報告する「都心4km周回でprepare 187秒」の箇所）を、ローカルPostGIS＋実際の東京都心取込
   データ（way 150,265本）に対して実測**（`bench_postgis_prepare.py`）。都心駅起点・4km周回
   相当のbbox（`road_graph_engine.py`の`prepare()`と同じ算出式）で**end-to-end 271秒**
   （`docs/architecture.md`の187秒より悪化。マシン差はあるが同オーダー）。内訳を分解すると
   `get_way_specs_with_closure`（DB空間検索、closure込みway 79,468件）が**約16秒**、
   `build_road_graph`（交差点分割、CPU）が**約10秒**なのに対し、`save_graph`+
   `save_surface_attributes`（bulk UPSERT、delete-then-reinsert）が**128〜172秒**と
   **全体の85〜90%を占める**。ボトルネックは空間検索でもCPUでもなく**DB書き込み段**
   であることが実データで裏付けられた。
   また、このbboxのprimary way（35,202件）はdelete-then-reinsertでEdge 155,086本を
   書き換えるが、これはインポート済みデータのroad_edges全件数（155,086）と一致する
   ——つまり**この都心データセットでは「4km周回」1件のリクエストが実質DB上の
   全Edgeを書き換える**ことが分かった（`BBOX_MARGIN_MIN_KM=2km`下限＋closureの
   「主対象Wayの外接矩形」探索が、要求bboxよりはるかに広い範囲を引き込むため。
   1km周回でもprimary way 19,637件・closure way 72,580件と、全体15万wayの半分近くに
   達する）。`docs/osm-pbf-import.md`が次の最適化候補として挙げる「生データ不変時に
   road_edgesを直読みする省略パス」の必要性を実データで定量的に裏付ける結果。

6. **5番を受けて、生データ不変時の省略パスを実装 → 実データで10〜14倍高速化を確認**。
   `RoadGraphRepository.is_split_up_to_date`（`osm_raw_ways.split_at`と`updated_at`の比較、
   `LIMIT 1`で早期終了）が主対象Wayの分割が最新か判定し、最新なら`get_graph_in_bbox`+
   `get_surface_attributes`で`road_edges`/`road_nodes`/`surface_attributes`を直接読む
   （closure再計算・`build_road_graph`・`save_graph`を丸ごと省略）。実装にあたり2つの
   落とし穴を修正済み: (a) `save_raw_ways`のUPSERTが内容不変でも`updated_at`を進めていた
   （1つのWayが複数タイルにまたがるため、隣接タイル取得だけで無関係なWayがstale誤判定に
   なる）→ `_bulk_upsert`に`change_detection_columns`（`ON CONFLICT ... DO UPDATE ... WHERE`
   での no-op化）を追加して解消。(b) 座標既知ノードが2点未満のセグメントしか生成しない
   Way（`road_edges`に1行も無い）は「Edgeの存在」を鮮度シグナルにすると永久にstale
   判定され続ける → `osm_raw_ways.split_at`列（Edge非生成でもスタンプ）で解消。

   `bench_postgis_prepare.py`でCOLD（`split_at`リセット後、通常の低速経路）とWARM
   （省略パス）を分けて実測（都心駅起点、実データ・way 150,265本）:

   | シナリオ | COLD（低速経路） | WARM（省略パス） | 倍率 |
   |---|---|---|---|
   | 1km周回相当（primary way 19,637件） | 154.4秒 | 中央値11.1秒（min 10.6秒） | 約14倍 |
   | 4km周回相当（primary way 35,202件） | 152.5秒 | 中央値15.5秒（min 15.4秒） | 約10倍 |

   `is_split_up_to_date`単体は20〜30msと十分軽い（79,468way規模のclosureでも問題にならない）。
   **ただしWARM自体も「一瞬」ではなく10〜16秒かかる点は新たな発見**——`get_graph_in_bbox`は
   bbox内の全Edge（この規模では8.5万〜15.5万行）をORM経由でPythonオブジェクト化
   （shapelyでのgeometry decode込み）する必要があり、この読み出し自体が数秒〜十数秒
   かかる。しかも`get_road_surface_ways_in_bbox`（同じファイル内、密集タイルでの同種の
   CPU処理）とは異なり`asyncio.to_thread`でラップされていなかった（`get_graph_in_bbox`は
   このタスク以前は本番未接続の死んだコードだったため、この形でイベントループを塞ぐ
   リスクが実際に顕在化していなかった）→ **7番で修正済み**。

   また、COLD実測値（1km 154.4秒／4km 152.5秒）はStage 1-3（closure＋build＋save）の
   単純合計（1km: 11.0+6.0+81.2=98.2秒／4km: 13.9+6.0+103.5=123.4秒）より大きい
   （差は約29〜56秒）。`build_surface_attributes`が要因ではないかと推測していたが、
   **7番の追加調査で否定された**（実測1.32秒、closureグラフ全体361,839 Edge分でも
   無視できる規模）。

7. **6番で見つかった2件のフォローアップに対応**（`bench_postgis_prepare.py`は改修せず、
   対象範囲を直接計測するアドホックスクリプトで検証）。

   - **`get_graph_in_bbox`を`asyncio.to_thread`でラップ → 修正済み**
     （`road_graph_repository.py`）。単体実測（都心4km相当bbox、Edge 151,820件・
     Node 59,270件）で**13.30秒**——`get_road_surface_ways_in_bbox`と同じ理由
     （shapelyでのgeometry decodeを伴う大量行のORM→Pythonオブジェクト化）でイベント
     ループを塞いでいたため、`get_road_surface_ways_in_bbox`と同じパターン
     （行取得はasync、CPU変換部分だけを`asyncio.to_thread`）を適用した。
     `get_surface_attributes`（geometry decode無し、単純なフィールドコピー）も同時に
     計測し**4.74秒**（151,820件）——こちらはCPU処理というより多数チャンク
     （`_ID_CHUNK_SIZE`単位）のDBラウンドトリップ蓄積が主要因と見られ、今回は対象外
     とした。

   - **COLDの未解明分（29〜56秒）の原因調査 → `build_surface_attributes`ではないと判明**。
     直接計測（都心4km相当bbox）: `get_way_specs_with_closure` 17.38秒、
     `build_road_graph` 10.55秒（Edge 361,839件・Node 137,514件）、
     `build_surface_attributes` **1.32秒**（361,839件、Pydanticモデル構築のみで
     十分軽い）、`primary_edges`フィルタ 0.13秒。この4つの合計（29.4秒）は
     `bench_postgis_prepare.py`が最初に記録したclosure+build単体の値（1km:
     17秒、4km:20秒）とほぼ一致しており、**「未解明分」の主因は隠れたコストではなく、
     GCを無効化していない・別々のタイミングで計測したことによる実行時変動**
     （closureだけでも実行間で13.9秒⇔17.4秒とばらつく）である可能性が高い。
     save_graph側の詳細な内訳分解は行っていないため断定はできないが、追加の
     コード変更は不要と判断した。

8. **6番の省略パスをSupabase（WAN経由）実データで再計測**。`is_split_up_to_date`の
   `split_at`列マイグレーションをSupabaseへ適用した上で、開発機からSession pooler
   経由で`bench_postgis_prepare.py`を実行（都心駅起点、実データ）:

   | シナリオ | COLD（低速経路） | WARM（省略パス） | 倍率 |
   |---|---|---|---|
   | 1km周回相当（primary way 19,637件） | 126.0秒 | 中央値18.0秒（min 14.4秒） | 約7.0倍 |
   | 4km周回相当（primary way 35,202件） | 211.0秒 | 中央値27.9秒（min 26.6秒） | 約7.6倍 |

   ローカルPostGIS実測（1km 154.4秒→11.1秒、4km 152.5秒→15.5秒）と比べると、
   短縮の**絶対値**（108秒／183秒）はローカル（143秒／137秒）と同等以上だが、
   短縮**倍率**（7.0〜7.6倍）はローカル（10〜14倍）より低い。「省略パスはWAN
   環境ほど効く」という当初の予想（`docs/architecture.md`参照）とは逆の結果——
   理由はWARM側自体もラウンドトリップ回数分だけWAN遅延の影響を受けるため。
   `is_split_up_to_date`単体はローカルで20〜30msだったのがSupabaseでは
   780〜810ms（1回のクエリでもレイテンシがミリ秒→サブ秒に増える）、WARM全体でも
   1km 10.6〜11.1秒→14.4〜18.0秒、4km 15.4〜15.5秒→26.6〜27.9秒と、いずれも
   ネットワークラウンドトリップ回数の影響がそのまま乗る形になっている。一方COLD側は
   一括UPSERT（数万〜十数万行を1回のバルクINSERT文にまとめて送る）が主体のため、
   WANでもラウンドトリップ回数自体は増えず、Supabase側のDBサーバー性能が良ければ
   ローカルと同程度かそれ以上の速度が出ることもある（1km COLD: 126.0秒 vs
   ローカル154.4秒）。

9. **8番のWARM内訳をSupabase（WAN）で分解計測 → 主犯は`get_graph_in_bbox`のCPU処理と判明**。
   `is_split_up_to_date`/`get_graph_in_bbox`/`get_surface_attributes`をそれぞれ単体で
   計測するアドホックスクリプトを実行（都心駅起点、実データ、min値）:

   | シナリオ | `is_split_up_to_date` | `get_graph_in_bbox` | `get_surface_attributes` |
   |---|---|---|---|
   | 1km（Edge 82,611件） | 0.79秒 | 9.17秒 | 4.97秒 |
   | 4km（Edge 151,820件） | 0.79秒 | 14.25秒 | 7.97秒 |

   `get_graph_in_bbox`がWARM全体の約6割を占め最大コスト。ローカルでの単体計測
   （4km・CPU処理のみで13.3秒、7番参照）とほぼ同じ規模のため、正体はネットワーク
   ラウンドトリップではなく**shapelyでのgeometry decodeそのもの（CPU処理）**と判明。

   `get_surface_attributes`（`_chunked(edge_ids, _ID_CHUNK_SIZE=10_000)`+`.in_()`、
   1km 9回・4km 16回のラウンドトリップ）は、`get_way_specs_with_closure`のノード座標
   取得で既に使われている`=ANY(配列)`パターン（1要素=1パラメータのIN句展開と異なり
   配列全体で1パラメータになり、パラメータ数上限を気にせず1回のクエリに収まる）へ
   `get_graph_in_bbox`のNode取得・`get_elevation_attributes`と合わせて置き換えた
   （`road_graph_repository.py`、チャンク幅は同じ理由で50,000に統一。ラウンドトリップは
   1km 9→2回・4km 16→4回に減少）。改修後に同条件で再計測:

   | シナリオ | `get_graph_in_bbox`（前→後） | `get_surface_attributes`（前→後） |
   |---|---|---|
   | 1km | 9.17秒 → 9.00秒（誤差範囲） | 4.97秒 → 4.19秒（約16%減） |
   | 4km | 14.25秒 → 14.81秒（悪化、誤差範囲） | 7.97秒 → 7.33秒（約8%減） |

   `get_surface_attributes`はラウンドトリップ削減の効果が小さいながら見られた
   （副作用の無い改修のため採用）が、`get_graph_in_bbox`は実質無変化——このスケール
   （Edge数万〜十数万件）ではラウンドトリップ回数よりもshapely decodeのCPU時間の方が
   支配的で、ラウンドトリップ削減だけでは効かないことが分かった。なお対照として
   コード変更していない`is_split_up_to_date`も0.79秒→1.45秒とブレており、WAN計測は
   実行間variance自体が大きい点に注意（改修効果はこのノイズ幅に近い）。

   **残課題として上位**: `get_graph_in_bbox`のCPU律速（geometry decode）を削減する
   には、ラウンドトリップ数の削減とは異なるアプローチが必要 → **10番で対応**。

10. **`get_graph_in_bbox`のgeometry decode・Pydantic構築を高速化**。まずDBレスの
    合成データでshapely.wkb.loads（1行ずつ）とshapely.from_wkb（shapely 2.0の
    ベクトル化バッチAPI、GEOS呼び出しのループをC側で回す）を比較したところ10〜24倍
    差が出たが、ローカル実データ（road_edges平均2.5点/Edge、中央値2点）で座標抽出・
    Pydantic構築まで含めて計測し直すと、決して無視できないが桁が違うほどではない
    差に縮んだ（詳細は下記）。合成ベンチマークだけで結論を出さず実データで検証し
    直す必要があったという教訓も含めて記録する。

    ローカル実データ（都心4km相当bbox、Edge151,820件・Node59,270件、decode+construct
    部分のみ計測、DBラウンドトリップ含まず）:

    | 実装 | Edge | Node | 合計 |
    |---|---|---|---|
    | 現状（`to_shape()`逐次＋通常コンストラクタ） | 4.684秒 | 1.427秒 | 6.111秒 |
    | 改修後（`shapely.from_wkb()`一括＋`model_construct`） | 3.073秒 | 0.768秒 | 3.841秒 |

    約37%削減（6.11秒→3.84秒）。`_rows_to_road_graph`（`road_graph_repository.py`）を
    書き換え、`Node`/`DirectedEdge`は`model_construct`でフィールド検証をスキップする
    （DBは自ら書き込んだ内部ストアで型が保証済みのため安全という判断。生成結果が
    従来実装と一致することは既存テストで確認）。

    本番コード経路（`get_graph_in_bbox`丸ごと、DB取得含む）で改修前後を実測:

    | 環境 | 改修前 | 改修後 |
    |---|---|---|
    | ローカルPostGIS（4km） | 13.3秒（7番参照） | min 6.6秒（約50%減） |
    | Supabase・WAN経由（4km） | min 14.25秒（9番参照） | min 14.43秒（実質無変化） |

    ローカルでは明確に効くが、**Supabase（WAN）では改善が観測できなかった**——
    このスケール（Edge数万〜十数万件＋geometry）ではCPU処理の37%削減（数秒規模）が、
    行データ本体の転送時間（10秒規模、環境固定コスト）に埋もれてしまうため。
    つまり`get_graph_in_bbox`のWANでの真のボトルネックは「CPU処理」でも
    「ラウンドトリップ回数」（9番で否定済み）でもなく、**転送データ量そのもの**
    である可能性が高い。改修自体はサーバー側CPU時間を確実に削減する（ローカル/
    自己ホスト環境や将来のCPUバウンドな負荷では有効）ため採用するが、Supabase
    環境でのprepare全体時間改善には直結しなかった。次の候補は転送列の絞り込みや
    より軽量なペイロード形式（例: 座標精度を落とす、不要列を選択しない）。

11. **`surface_attributes`専用テーブルを廃止しosm_raw_ways.surfaceのJOIN導出へ
    （改善計画T9、2026-08-15）**。road_edges.osm_way_id経由でosm_raw_ways.surfaceを
    LEFT JOINして読む方式に変更し、`save_graph`とは別に行っていた
    `save_surface_attributes`（Edge単位UPSERT）を廃止した。ローカルPostGIS（開発機、
    実データ）で計測（`bench_postgis_prepare.py`。9番以降の計測はSupabase WAN経由
    だったのに対しこちらはローカル接続のため直接比較はできない点に注意）:

    | シナリオ | `save_graph`単体 | WARM経路end-to-end |
    |---|---|---|
    | 1km | 8.25秒（primary_edges=11,210） | 1.92秒（primary_edges=11,210） |
    | 4km | 13.69秒（primary_edges=22,164） | 3.06秒（primary_edges=22,164） |

    旧実装は`save_graph`に加えて`save_surface_attributes`（Edge数分のUPSERT）を
    同じCOLD経路で追加実行し、WARM経路でも`get_surface_attributes`が専用テーブルへの
    追加SELECT（9番の実測で1km 4.19秒・4km 7.33秒、WAN）を要していた。JOIN化により
    どちらの経路も「追加のテーブルへのDB往復」自体が構造的に無くなった
    （SELECT/UPSERT対象テーブルが1つ減った）。Supabase等WAN環境での定量比較は、
    旧実装が既にコードから削除済みのため再測定できない。

## 各ファイル

| ファイル | 対象 |
|---|---|
| `bench_nearest_node.py` | `domain/routing.py: find_nearest_node`の線形探索スケーリング |
| `bench_graph_build.py` | `domain/graph.py: build_road_graph`の構築コスト |
| `bench_route_trace.py` | `RoadGraphEngine`の8方位分の最近傍探索+Dijkstraをまとめて模擬 |
| `bench_elevation_cache.py` | `infrastructure/cache_db.py`の接続張り直しコスト、`ElevationAttributeService`のend-to-end |
| `_harness.py` | 計測用の共通ユーティリティ（外部依存無し） |
| `_synthetic.py` | 合成の格子状道路網ジェネレータ（規模を揃えて比較するため） |

## 対象外にしたもの

フロントエンド（GeoJSON構築・MapLibreレイヤー更新）は`frontend/src/components/Map/MapView.bench.ts`
（vitestの`bench()`API）に分離してある。実行方法はそちらのファイル冒頭のコメント参照。

## 実サービス接続が必要なベンチマーク（`run_all.py`には含まれない）

上記はすべて合成データ・外部接続無しで再現できるものだが、`bench_postgis_prepare.py`だけは
例外的に実際のローカルPostGIS接続・実データ・DB書き込み（既存データと同内容への
delete-then-reinsertで冪等）を伴う。「合成データのみに閉じる」という上記の既存方針からは
外れるため、`run_all.py`には含めず個別実行とする。

| ファイル | 対象 | 前提 |
|---|---|---|
| `bench_postgis_prepare.py` | `GraphService.get_or_build_graph_with_attributes`（PostGISキャッシュ経路）のprepare段階を実データで内訳分解。省略パス（`is_split_up_to_date`）のCOLD/WARM比較も計測する | ローカルPostGISに`app/batch/import_pbf.py`で東京都心データを取込済みであること（`docs/osm-pbf-import.md`参照）。実行方法はファイル冒頭のdocstring参照（`DATABASE_URL`をローカルDBへ上書き） |

実行前に対象bboxのデータ量（DB書き込み対象のprimary way数）を確認し、ディスク空き容量に
対して十分小さいことを確認してから実行すること（この既存実装は`save_graph`が
delete-then-reinsertのため、対象データ量が大きいとWAL生成量もそれなりに増える）。

closure/build/save（1回あたり数十秒〜3分規模）は`slow_repeat`（既定1）、
`is_split_up_to_date`/WARM呼び出し（1回あたりms〜秒規模）は`fast_repeat`（既定3）で
繰り返し回数を分けている。最初の実装では両方に同じ`repeat`を使っていたため
1回の実行が20分を超え、実装の試行錯誤（バグ修正→再実行）に耐えなかった教訓から
分離した。分散（stdev）が欲しい場合は`_run_scenario`呼び出しで`slow_repeat`を
明示的に増やすこと（実行時間が線形に伸びる点に注意）。
