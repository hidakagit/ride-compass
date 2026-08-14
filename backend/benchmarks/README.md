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
   dev環境にPostGIS接続が無く未検証（`docs/architecture.md`参照）。

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
