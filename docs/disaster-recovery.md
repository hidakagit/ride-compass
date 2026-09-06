# 本番DB再構築（disaster recovery）・OSM更新時の派生データ再構築手順

CLAUDE.md「コミット時の同期ルール」・[deployment-sync.md](deployment-sync.md)から参照される
作業標準。「本番DBを失った場合にゼロから再構築する手順」と「OSMデータ更新時に派生データを
最新化する定常運用手順」の両方を扱う（後者は前者の一部でもある）。

## 2系統のフロー

```
新規/被災環境（disaster recovery、本ページの主題）
  1. PostgreSQL+PostGISクラスタ準備
  2. bootstrap_fresh_db.py（create_tables→migration適用→axis_definitions投入）
  3. 生データ取込（import_pbf.py・import_accidents.py・import_designations.py）
  4. refresh_derived.py（派生データ再構築、改善計画T281段階2）  ─┐
                                                                  │
定常運用（OSM等の生データ更新時）                                  │
  1. 生データ取込（更新分。import_pbf.pyは--bbox省略時PBF全体を   │
     UPSERT、差分更新も同じ経路）                                 │
  2. refresh_derived.py ──────────────────────────────────────────┘
```

`refresh_derived.py`（`app/batch/refresh_derived.py`）は依存DAG
（[batch-pipeline-dependencies.md](batch-pipeline-dependencies.md)）の④〜⑩
（`presplit_road_graph`→`precompute_road_node_degrees`→
`precompute_edge_attribute_counts`→`precompute_elevation_attributes`→
`precompute_way_attribute_counts`→`match_designations`→`precompute_way_landcover`）を
依存順に1コマンドで実行する。①〜③（生データ取込そのもの）は対象外——個別のファイル・
年次・kind指定を要するため。⑩`precompute_way_landcover`だけラスタファイルの手動取得
（下記「4. refresh_derived.py」節参照）を要するため、未整備の環境では`--skip-landcover`で
この段だけスキップできる。

## disaster recovery手順（新規/被災環境）

### 1. PostgreSQL+PostGISクラスタ準備

本番と同じバージョン（2026-09-04時点でPostgreSQL 18・PostGIS 3.6）を用意する。

- **新規VM**: OSのパッケージマネージャ（Ubuntu/Debianなら`apt`のPGDGリポジトリ）で
  `postgresql-18`・`postgresql-18-postgis-3`を導入し、`CREATE EXTENSION postgis`する。
- **既存VM上の検証用インスタンス**（本番影響ゼロで手順を試したい場合）:
  `sudo pg_createcluster 18 <cluster名> --port=<空きポート>`で本番クラスタ（`main`、
  ポート5432）とは別クラスタを作成できる。apt管理下の同じPostgreSQLバージョンが
  既にインストール済みなら追加パッケージ不要。検証後は`pg_ctlcluster ... stop`→
  `pg_dropcluster`で完全に削除できる（本番クラスタには一切影響しない）。
  Dockerの`postgis/postgis`公式イメージはARM64（Oracle Cloud A1インスタンス等）を
  サポートしないタグが多い（`exec format error`で起動失敗）ため、ARM64環境では
  上記のネイティブクラスタ方式を使うこと。

### 2. bootstrap_fresh_db.py

```
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db> \
  python scripts/bootstrap_fresh_db.py
```

`create_tables()`→`apply_pending_migrations()`→`axis_definitions_snapshot.json`の投入、を
1コマンドで行う（[T361](tasks/T361.md)）。まっさらなDB専用（稼働中DBに対して実行すると
axis_admin API経由の変更が消える、`bootstrap_fresh_db.py`のdocstring参照）。

### 3. 生データ取込

`import_pbf.py`（`--bbox`で範囲限定可、省略時PBF全体）・`import_accidents.py`・
`import_designations.py`をそれぞれ実行する（相互に独立、順不同）。PBF取込には
`pyosmium`（`requirements-batch.txt`）が必要——`requirements.txt`のみの本番webイメージ
には含まれないため、バッチ実行用に別途これを含めたイメージ/環境を用意すること。
ARM64のDebian系ベースイメージでは`libexpat1`（`apt-get install`）が無いと
`import osmium`が`ImportError: libexpat.so.1: cannot open shared object file`で
失敗する（python公式slimイメージには含まれない）。

### 4. refresh_derived.py

```
DATABASE_URL=... python -m app.batch.refresh_derived
```

**⑩precompute_way_landcoverが読むEsri×Impact Observatory Sentinel-2 10m Annual LULCの
GeoTIFFはリポジトリにコミットしない**（PBFをGeofabrikから手動取得するのと同じ運用）。
Azure Blob（`https://lulctimeseriesv003.blob.core.windows.net/lulctimeseriesv003/
lc<年>/<ゾーン>_<年>0101-<翌年>0101.tif`）またはMicrosoft Planetary Computer STAC
（コレクション`io-lulc-annual-v02`）から該当ゾーンのタイルを手動取得し、
`settings.lulc_raster_paths`（環境変数`LULC_RASTER_PATHS`、カンマ区切りで複数可）へ
ローカルパスを設定する。未設定のまま`refresh_derived.py`を実行するとこの段が
失敗するため、ラスタを用意できない環境（検証用の使い捨てDB等）では`--skip-landcover`を
明示的に指定してこの段だけスキップする。

**本番（関東本土全域）で実行する場合は必ずDockerメモリ上限を指定すること**
（`docker run --memory=<上限> ...`）。全域規模（road_edges約500万件）では
`precompute_elevation_attributes`（DEMタイルをプロセス内メモリキャッシュへ保持し続ける
設計、`infrastructure/tile_cache.py`とは別にプロセス内`_tile_grid_cache`も肥大化する）が
長時間・大量にメモリを消費し、上限を指定しないとホストOS全体のメモリを枯渇させうる
（2026-09-04の本番実行で実際にVM全体が6時間以上無応答になるインシデントが発生、
下記「既知のリスク」参照）。上限の目安は本番VMの物理メモリの50〜70%程度
（他のプロセス——本番backend・PostgreSQL・OS自体——の分を必ず残すこと）。

**稼働中DBへの定常運用（新規/被災環境のbootstrap直後を除く）で実行した場合は、
完了後に`TILE_MATERIALS_CACHE_VERSION`（`infrastructure/graph_material_cache.py`）・
`TILE_SCORE_MATRIX_CACHE_VERSION`（`infrastructure/tile_score_matrix_cache.py`）を
同一コミットで上げてpushすること**（deploy-backend.ymlが`backend/**`変更を検知し
本番backendを自動デプロイ、再起動でディスク永続キャッシュの新世代が有効になる）。
上げないと、バッチ実行前に既にキャッシュ済みだったタイルはディスク経由で古いまま
復元され続け、未訪問タイルだけ新しい値になる——「一部だけ更新されたように見える」
形で気づきにくい（改善計画T574、2026-09-04。新規/被災環境のbootstrap直後は
ディスクキャッシュが元々空のためこの手順は不要）。

## backend前段nginx（TLS・HTTP/3）の再構築

本番VMのnginxはUbuntu配布版ではなくnginx.org公式パッケージ（1.30系、QUIC/HTTP/3同梱）で、
設定は`/etc/nginx/conf.d/`（`ridecompass-backend.conf`・`openmeteo-proxy.conf`）にある。
リポジトリ追加・パッケージ差し替え・server blockの全文・UDP 443開放（iptables＋OCI
セキュリティリスト）の手順は[T580](tasks/T580.md)「VM側の作業手順」参照。TLS証明書は
certbot（`sslip.io`ドメイン、HTTP-01）で、port 80のserver blockを残しておく必要がある。

## 既知のリスク・対策（2026-09-04、本番実行時のOOMインシデントを受けて追記）

`refresh_derived.py`を関東本土全域（road_edges約500万件）に対してメモリ上限指定なしで
実行したところ、⑦`precompute_elevation_attributes`の途中でVM全体のメモリが枯渇し、
SSH・HTTPともに6時間14分（02:06〜08:20 UTC）応答不能になった（本番backendも同時間帯
完全にダウン）。OCI CLIの`SOFTRESET`（ACPI経由の正常再起動）も約13分応答せず、最終的に
`RESET`（強制電源サイクル）で復旧した。ジャーナルログに`snapd.service: Watchdog timeout`・
大量の`sshd: Broken pipe`が残っており、システム全体が深刻なメモリスラッシング状態に
あったと見られる（OOM Killerの直接ログは再起動でクリアされ確認できず）。

**判明した脆弱性と対策**:
- **スワップが0Bだった**（対策済み: 4GBのswapfileを`/`に追加、`vm.swappiness=30`に設定。
  緩衝材を持たせることで、急激なメモリ枯渇時にOOM Killerがより正確に選別してkillする
  余地を作る）。
- **重いバッチにDockerメモリ上限が無かった**（対策: 上記「④refresh_derived.py」節の
  運用ルール。今後本番で重いバッチを実行する際は必ず`--memory`を指定すること）。
- **本番backendコンテナ自体のメモリ保護は未実施**（今回のインシデントで確認できた残課題。
  `docker run --oom-score-adj=<負の値>`等でOOM Killerの標的になりにくくする対策は
  今回は実施していない、次回検討）。
- 全国規模（[T127](tasks/T127.md)が扱う所要時間の不確実性）への外挿では、この種の
  リソース枯渇リスクがさらに増す。全国投入を検討する際は、この節の対策を前提に
  含めること。

## 検証実績（2026-09-04、[T573](tasks/T573.md)）

既存本番VM上に別ポートの使い捨てPostgreSQL 18+PostGIS 3.6クラスタを作成し、
最新masterのコードで以下を実施・成功を確認した。

- `bootstrap_fresh_db.py`: 30 migration適用、axis_definitions 13件投入。
- `import_pbf.py --bbox 35.60,139.65,35.75,139.85`（東京都心、Geofabrik
  `kanto-latest.osm.pbf`使用）: ways=41,555 nodes=211,625 pois=58,269、547.9秒。
- `refresh_derived.py`: ④〜⑨全段階成功、196.4秒。
- backend起動→`POST /api/routes/generate`→ポーリングで実際にルートが生成されることを
  確認（東京駅相当、5km±2km、`status: "done"`）。

**今回未検証の範囲**（次回の検証・本番実運用時に補うこと）:
- `import_accidents.py`・`import_designations.py`は実行していない（⑨`match_designations`
  はcandidates=0で正常終了したが、これは③未実行のため指定路線データが無いことによる
  ——route_designationsテーブルが空の状態での「候補0件」であり、バグではない）。
- 全国規模（東京都心の小規模bboxのみ検証、[T127](tasks/T127.md)が扱う94万way超からの
  非線形減速問題は未検証のまま）。
- 完全な新規VM（既存VM上の別クラスタで検証したため、VM自体のセットアップ手順は含まれない）。
- Redis（`graph_material_cache`等）・タイル永続キャッシュ（`tile_persistent_cache`）の
  初期化・版数確認手順（新規環境なので原理的に空の状態から始まり、既存キャッシュとの
  版数不一致は発生しない——この検証項目は「稼働中DBの更新後」のシナリオ向け、
  [batch-pipeline-dependencies.md](batch-pipeline-dependencies.md)「改善計画T538追記」
  参照）。
