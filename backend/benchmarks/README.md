# パフォーマンスベンチマーク

`app/`のうちパフォーマンス上の懸念があった箇所（Road Graphルーティング、標高キャッシュ、
ベクタタイル生成）を、実際のOverpass/GSI/PostGIS接続無しで再現できる合成データに対して
計測する。追加のpip依存（pytest-benchmark等）は増やさず、`_harness.py`の
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
   CPU処理）とは異なり`asyncio.to_thread`でラップされていない（`get_graph_in_bbox`は
   このタスク以前は本番未接続の死んだコードだったため、この形でイベントループを塞ぐ
   リスクが実際に顕在化していなかった）。次の改善候補として記録するが、今回のタスクの
   スコープ（書き込み省略パス）には含めていない。

   また、COLD実測値（1km 154.4秒／4km 152.5秒）はStage 1-3（closure＋build＋save）の
   単純合計（1km: 11.0+6.0+81.2=98.2秒／4km: 13.9+6.0+103.5=123.4秒）より大きい
   （差は約29〜56秒）。`build_surface_attributes`（closureグラフ全体に対するCPU処理、
   単独では計測していない）やタイルキャッシュ判定ループが要因と推測されるが、
   詳細な内訳分解はまだ行っていない。

## 各ファイル

| ファイル | 対象 |
|---|---|
| `bench_nearest_node.py` | `domain/routing.py: find_nearest_node`の線形探索スケーリング |
| `bench_graph_build.py` | `domain/graph.py: build_road_graph`の構築コスト |
| `bench_route_trace.py` | `RoadGraphEngine`の8方位分の最近傍探索+Dijkstraをまとめて模擬 |
| `bench_vector_tile.py` | `infrastructure/vector_tile.py: encode_road_surface_tile`のway数スケーリング |
| `bench_event_loop_stall.py` | 上記MVTエンコードが同時実行中の他タスクをどれだけ足止めするか |
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
