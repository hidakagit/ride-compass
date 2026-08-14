# OSM PBF取込バッチ設計（Overpass依存の解消）

ステータス: Phase 3（Supabase取込・Overpassフォールバック設定無効化）に続き、**Phase 4（関東圏への拡大・highwayフィルタリング）完了**（2026-08-15）。実装・検証の詳細記録は docs/architecture.md 9章「実PostGISでの動作検証（Phase 0）」「OSM PBF取込バッチ（Phase 1）」「RegionServiceのPostGIS化（Phase 2）」「Supabase取込とOverpass停止（Phase 3）」参照。

**現在の運用姿勢**: `.env`で`ROAD_GRAPH_USE_REPOSITORY=true`＋`OVERPASS_FALLBACK_ENABLED=false`。PostGIS（Supabase）が唯一のOSMデータソースで、**Overpassへの問い合わせは発生しない**（フォールバックのロジック自体はコードに併存しており、`.env`の2行で切り戻せる）。取込済み範囲はデフォルト位置（王子・35.7597,139.7387）を中心とした半径25km（bbox 35.5345,139.4611-35.9849,140.0163）。範囲外は路面タイル＝空・Road Graph＝None（いずれも常時WARNINGログ）。

**取込プロファイル（2026-08-15更新）**: `import_profile.yaml`のhighwayマッチを`"*"`から自転車で通行しうる種別（trunk/primary/secondary/tertiary/unclassified/residential/living_street/cycleway/track、および各`_link`）のみへ限定。都心の実データでは全highway種別の73%がfootway/service/steps/path/pedestrian等（自転車ルーティングに使われない）で占められており、除外により生データ量を概算1/3に圧縮できる（副次効果としてルート探索候補から「階段」等も消える）。既存データのクリーンアップ（除外種別の行を`osm_raw_ways`/`osm_raw_nodes`及び派生テーブルから削除）も実施済み。

**容量方針（本番想定）**: 本番はSupabaseを想定し、フリープランの容量500MBに対して**予算400MB以内**とする（2026-08-15にユーザー要件を300MB→400MBへ更新）。Supabase実測の推移: Phase 3直後196MB→運用で292MBまで増加→highwayフィルタ対象外データのクリーンアップで**74.4MB**まで圧縮→半径25km（王子中心）取込後**約342MB**（残り約58MB）。取込バッチは完了サマリに`db_size_mb`を常時出力するため、範囲を広げる際はこの値で予算内かを確認する。派生データ（road_edges等）はルート生成が実際に使った地域ぶんだけ組織的に増えるキャッシュのため、残り予算を圧迫してきたら該当行のDELETEが圧力弁になる（次回リクエストで再生成される）。

**既知の性能上の落とし穴（2026-08-15発見・修正）**: `road_edges.from_node_id`/`to_node_id`（外部キー参照列）に索引が無く、`road_nodes`から行を削除するたびに整合性チェックで`road_edges`の全件シーケンシャルスキャンが走っていた（ローカル検証で35,550行の削除に27分かかった）。`idx_road_edges_from_node_id`/`idx_road_edges_to_node_id`を追加して解消（`road_graph_repository.py`の`create_tables`、`idx_road_edges_osm_way_id`追加時と同じ経緯）。容量予算の「圧力弁」（road_edges等のDELETE）を実際に使う場面で効いてくるため、Supabase等の既存DBには`create_tables()`の再実行（冪等）が必要。

## 1. 目的と背景

現在、OSM道路データは公開Overpass APIからランタイムに都度取得している。実運用で以下の問題が確認済み（docs/architecture.md・overpass_client.pyのコメント参照）:

- Render経由の送信元IPに対し、公開Overpassエコシステム全体が広く遅延・失敗する（1ミラーあたり平均10〜20秒）
- 「200 OKだが0件」という見せかけの成功があり、空タイルがキャッシュに焼き付く事故が起きた
- 8方位並列問い合わせが全滅するなどレート制限の影響を受けやすく、公開インスタンスへの配慮（順次問い合わせ）が速度の上限になる
- Road Graphベースのルート生成が1リクエスト40〜70秒（大半がOverpass取得＋標高取得）

本設計は、**利用するOSMデータをPBF（Geofabrik等の地域抽出ファイル）からPostGISへ事前取込するバッチ**を導入し、ランタイムのOverpass問い合わせを不要にすることを目的とする。あわせて、将来の拡張（道路以外の要素の利用）に備えて**取込対象の要素をプロファイル設定で宣言的に指定できる**構造にする。

## 2. 現状のOverpass依存点

| 利用箇所 | メソッド | 取得内容 | 用途 |
|---|---|---|---|
| `GraphService`（services/graph_service.py） | `OverpassClient.get_ways_and_nodes` | highway wayとその全node（ID・トポロジー付き） | Road Graph構築。`repository`指定時はzoom12タイル単位で取得し、生データを`osm_raw_ways`/`osm_raw_nodes`へ永続化 |
| `RegionService`（services/region_service.py） | `OverpassClient.get_roads` | highway wayのジオメトリのみ（ID無し） | 路面ベクタタイル（MVT）生成。ファイルキャッシュに永続化 |

重要な既存資産: **PostGISスキーマには既に「生のOSMデータ層」（`osm_raw_ways`/`osm_raw_nodes`、road_graph_models.py）が存在する**。タイル境界問題の根本修正で導入されたこの層は「取得元に依存しない安定した生データの蓄積場所」として設計されており、Road Graph構築（`get_way_specs_with_closure`→`build_road_graph`）はこの層だけを読む。また`domain/osm_adapter.py`は当初から「将来PBF一括抽出等に切り替えても影響範囲はこのファイルに限定される」ことを想定して分離されている。

**したがって本設計の核心は「PBF取込バッチを、既存の生OSM層へのもう1つの書き込み手段として追加する」ことであり、Road Graph構築側のロジックは原理的に無変更で済む。**

## 3. 全体方針

```
【バッチ（オフライン、ローカル/任意のマシンで実行）】
Geofabrik PBF（例: kanto-latest.osm.pbf）
    ↓ pyosmium でストリーム読み取り
取込プロファイル（YAML）でマッチする要素を抽出
    ↓ 既存の osm_adapter と同じ解釈（direction等）を適用
COPYベースのバルクロードで PostGIS へ UPSERT
    - osm_raw_ways / osm_raw_nodes（既存テーブル、geom列を追加）
    - osm_import_runs（新規、取込メタデータ）
    - road_graph_tiles（取込範囲のタイルを取得済みマーク）

【ランタイム（変更は段階的）】
GraphService: 無変更（取得済みマークにより取込範囲内ではOverpassへ行かなくなる）
RegionService: PostGIS読みを第一系統に変更（Overpassはフォールバックとして残す）
最終的に settings.overpass_fallback_enabled=false でOverpass完全停止
```

設計原則:

1. **真実の源（source of truth）は`osm_raw_*`層に一本化する**。PBFバッチもランタイムのOverpass取得（フォールバック期間中）も、同じテーブルへ同じ意味論で書く。OSMのグローバルID（way/node ID）はデータソースによらず同一なので、両ソースの共存はUPSERTで自然に整合する
2. **既存機能を壊さない段階的移行**。過去の検討（architecture.md「選択肢A却下」）でRegionServiceのPostGIS必須化を避けたのは「dev環境にPostGISが無い」ためだった。今回はPostGIS導入自体が目的なので前提が変わるが、それでも「DB障害時にOverpassへフォールバック」を設定で選べる形にして可用性を維持する
3. **取込対象はプロファイルYAMLで宣言**。現在必要なのはhighway wayのみだが、将来（例: 水飲み場・トイレ・コンビニ等のPOI、通行障害のbarrier）の要素追加が「プロファイルに1エントリ追加＋対応する書き込み先の定義」で済む構造にする

## 4. 取込ツールの選定

| 選択肢 | 概要 | 評価 |
|---|---|---|
| **pyosmium（採用）** | PythonでPBFをストリーム処理するライブラリ（pipで導入可、Windows/Linuxのwheelあり） | 既存スキーマ（`osm_raw_*`）へ直接、既存の`osm_adapter`と同じ解釈で書ける。追加のネイティブバイナリ不要。取込プロファイルの自由度が最も高い |
| osm2pgsql（flex出力） | 標準的なOSM→PostGIS取込ツール。Luaで出力スキーマを制御 | 強力だが独自バイナリの導入が必要で、`node_ids`配列＋既存テーブル構造を正確に再現するにはLuaでかなり作り込む必要がある。タグ解釈（direction等）がPython側の`osm_adapter`と二重実装になる |
| imposm3 | GoバイナリのOSM取込ツール。YAMLマッピング | マッピング設定は魅力的だが、スキーマが独自形式でRoad Graph側の読み替えが必要になる。バイナリ依存も増える |

pyosmium採用の決め手は、**タグ解釈の単一実装を維持できる**こと。`oneway`→`direction`の解釈などを`domain/osm_adapter.py`に閉じ込めるという既存の設計判断をそのまま活かし、「Overpass経由でもPBF経由でも同じWaySpecになる」ことをコードレベルで保証できる（同じ関数を通すため）。

依存の追加は`backend/requirements-batch.txt`（`-r requirements.txt` + `osmium`）とし、Renderのwebサービスには入れない（バッチはデプロイ対象外）。

## 5. バッチ設計

### 5.1 実行形態

- 配置: `backend/app/batch/import_pbf.py`（`python -m app.batch.import_pbf`で実行）。`osm_adapter`・`road_graph_models`・`database.py`を再利用するためappパッケージ内に置く
- 実行場所: ローカル開発機など、対象PostgreSQLへ接続できる任意のマシン。Render Postgresは外部接続可能なので、本番DBへの取込もローカルから実行できる。webサービスのプロセスとは完全に独立
- CLI:

```
python -m app.batch.import_pbf \
    --pbf data/kanto-latest.osm.pbf \
    --profile app/batch/import_profile.yaml \
    --bbox 35.5,139.4,35.9,139.9   # 任意。省略時はPBF全体
    --database-url ...             # 省略時はsettings.database_url
    --dry-run                      # 件数集計のみ、書き込みなし
```

- `--bbox`は「bbox内に1つ以上のノードを持つway」を取込対象とする（ランタイムの`get_way_specs_with_closure`の主対象判定と同じ意味論）。DB容量の制御と、Geofabrik抽出ファイルより狭い範囲の運用を可能にする
- **実装時の変更（安全側への倒し込み）**: タイルの取得済みマークは`--bbox`を明示指定した場合のみ行う。設計当初は「省略時はPBFヘッダのbboxを使う」としていたが、ヘッダbboxは抽出ポリゴンの**外接矩形**にすぎず、実データが無い領域を「取得済み」と誤マークするとその範囲が永久に空表示になる（Overpassの見せかけの0件と同型の事故）ため、明示指定に限定した。**`--bbox`はPBFが実際にカバーする範囲の内側を指定すること**（CLIヘルプにも明記）

### 5.2 取込プロファイル（YAML）

```yaml
# app/batch/import_profile.yaml
version: 1
elements:
  - name: roads
    element_type: way
    match:
      highway: "*"          # タグの存在のみ要求（値は任意）。値のリスト指定も可
    target: osm_raw_ways     # 書き込み先（コード側に対応するwriterを実装）
  # --- 将来の拡張例（現時点では実装しない） ---
  # - name: drinking_water
  #   element_type: node
  #   match:
  #     amenity: ["drinking_water"]
  #   target: osm_raw_pois   # 新規テーブル＋writerを追加して有効化
```

- `match`は「タグ名→許容値（`"*"`は存在のみ）」のANDマッチ。現状の要件（`way["highway"]`）を表現でき、将来の要素追加も同じ語彙で書ける
- `target`ごとに専用のwriter（要素→行変換）をコードで持つ。roads用writerは`osm_adapter.osm_way_to_way_spec`を通してから行に変換する（Overpass経路との意味論一致を保証）
- プロファイル全体のハッシュを取込メタデータに記録し、「どの設定で取り込んだデータか」を後から追跡できるようにする

### 5.3 処理パイプライン

PBFはnode→way→relationの順に並んでいる。pyosmiumの`NodeLocationsForWays`（ノード位置インデックス、大きい抽出ファイルではディスクバックの`sparse_file_array`/`flex_mem`を使用）を併用し、**1パスで**wayとその構成ノードを解決する:

1. way要素がプロファイルにマッチしたら、`osm_adapter`でWaySpec化し、way行（`node_ids`配列・タグ列・WKBジオメトリ）を出力バッファへ
2. 同じwayの構成ノード（ID＋位置）をnode行として出力バッファへ（重複はDB側で解消）
3. バッファが一定件数（実装値: way 2万件）に達するごとに、asyncpgの`copy_records_to_table`で**ステージングテーブル**（実装では`TEMP`テーブル。セッション限定でWALも書かれず、切断時に自動削除される）へCOPY → `INSERT ... ON CONFLICT (osm_way_id) DO UPDATE`で本テーブルへマージ。node側は`DO NOTHING`（位置が変わることは稀で、変わっていればway側の再取込で整合する）

実装補足: osmiumのストリーム読み取り（ブロッキング）は別スレッドで回し、`queue.Queue`（上限4チャンク）経由でasyncioの書き込み側へ渡す（キュー上限が自然なバックプレッシャーになる）。DB側の失敗時はabortフラグでosmium側を明示的に打ち切り、スレッドの取り残しを防ぐ。

行単位`Session.merge`（既知の性能課題、architecture.mdレビュー指摘7）はバッチでは採らない。COPY＋SQLマージなら関東規模（数百万way・数千万node）でも現実的な時間で完了する見込み。

### 5.4 取込メタデータと取得済みマーク

新規テーブル `osm_import_runs`:

| 列 | 内容 |
|---|---|
| id | 連番 |
| pbf_name / pbf_timestamp | 取込元ファイル名と、PBFヘッダのosmosis_replication_timestamp（OSMデータの鮮度） |
| profile_hash | 取込プロファイルのハッシュ |
| bbox | 取込範囲（`--bbox`または PBFヘッダのbbox） |
| started_at / finished_at / status | 実行記録 |
| way_count / node_count | 取込件数 |

取込成功時、**取込bboxを覆う`ROAD_GRAPH_TILE_ZOOM`（zoom12）のタイル全てを`road_graph_tiles`へ取得済みマークする**（既存の`tiles_covering_bbox`を再利用）。これにより`GraphService.get_or_build_graph_with_attributes`は**一切の変更なしに**、取込範囲内ではOverpassへ行かなくなる。ランタイム側の挙動変更をコード変更ゼロで達成できるのがこの設計の要点。

`pbf_timestamp`は標高・路面Attributeの`data_version`にも使える（「どの時点のOSMに基づく属性か」の追跡）。

## 6. スキーマ変更

1. **`osm_raw_ways`に`geom`列（LINESTRING, 4326, 空間インデックス）を追加**
   - 現状、wayのジオメトリは`node_ids`→`osm_raw_nodes`のJOINでしか得られず、RegionService（タイル1枚分のwayを空間検索して線を描く）の読み先として使えない。取込時にノード位置からLINESTRINGを実体化して保存する
   - ランタイムのOverpassフォールバック経路（`save_raw_ways`）も同様にgeomを埋める（`get_ways_and_nodes`はノード位置を持っているので算出可能）
   - マイグレーションツールは引き続き導入しない方針（architecture.md）のため、`create_tables()`での新規作成＋既存環境向けの`ALTER TABLE ADD COLUMN IF NOT EXISTS`をバッチ起動時に実行する簡易対応とする
2. **`osm_import_runs`テーブル新設**（前節）
3. 将来のPOI等は`osm_raw_pois`のような**要素種別ごとの新テーブル**を追加する（`osm_raw_ways`に押し込まない）。プロファイルの`target`がそれを指す

`osm_raw_ways`の固定列（highway/surface/direction）は現状のまま維持する。「将来使うかもしれないタグを全部JSONBで持つ」案は、取込サイズと目的の不明確さからいったん見送り、**必要になったタグはプロファイルと列を追加して再取込する**運用とする（PBFが手元にあるので再取込のコストは低い）。

## 7. ランタイム側の変更

### Phase A（バッチ導入と同時）: GraphService本体は変更なし＋DI配線＋性能修正

取得済みマークにより取込範囲内ではDBのみで完結する。範囲外は従来どおりOverpassフォールバック（挙動維持）。実装時に以下を追加した:

- **DI配線**: `config.py`に`road_graph_use_repository`（既定false）を追加し、trueのとき`api/routes.py`の`get_graph_service`/`get_elevation_attribute_service`が`RoadGraphRepository`を注入する。falseなら従来どおりDBなしで動作する（Render等、DB未整備環境の安全側既定）
- **性能修正（Phase 1で必須と判明）**: 都心部のbbox（4km周回で約6.7km四方＝主対象way約4万・Edge十数万）に対し、(1)行単位`Session.merge`のUPSERT（設計レビュー指摘7）と(2)`get_way_specs_with_closure`のnode_ids配列GIN検索（数十万要素の配列パラメータ）が実用不能な遅さになることをE2Eで確認した（10分以上無応答）。以下へ置き換えた:
  - 全保存系（`save_graph`/`save_raw_ways`/attributes）を複数行VALUESの`INSERT ... ON CONFLICT`バルクUPSERTへ（1000行/文にチャンク分割、asyncpgのパラメータ上限32767を考慮）
  - `get_way_specs_with_closure`を空間検索ベースへ: 主対象＝「bboxとST_Intersectsで交差するWay」（旧「bbox内にノードを持つWay」の上位互換）、近傍＝「主対象全長のST_Extentと交差するWay」（旧「ノードを共有するWay」の厳密な上位集合。余分な近傍は交差点判定の文脈が増えるだけで、永続化されないため正しさを損なわない）。これは`osm_raw_ways.geom`列が前提のため、`create_tables()`に旧データのgeomバックフィル（node_ids→`ST_MakeLine`再構成）も追加した

### Phase B: RegionService — PostGIS第一系統化 ✅ 実装済み（2026-08-14）

`get_road_surface_tile`のOverpass問い合わせ部分を差し替えた:

1. タイルbboxで`osm_raw_ways`を`ST_Intersects`検索し、**MVTエンコードまで含めてPostGIS側で丸ごと生成**（`RoadGraphRepository.get_road_surface_tile_mvt`、`ST_AsMVT`/`ST_AsMVTGeom`。surface3値分類も同じクエリ内のCASE式で行い、タグ集合は`domain/road.py`の定数をバインドして単一ソース化）。ファイルキャッシュ方針は維持（2026-08-15改修。当初はway行をPythonへ転送して`encode_road_surface_tile`でMVT化していたが、遠隔DB（Supabaseムンバイ）では行転送＋Python側CPU処理で1タイル数秒かかり、パンのバースト時に3並列の待ち行列が30秒を超えてフロントエンドNext.jsのrewritesプロキシ（デフォルト30秒）がタイムアウト500を返す主因になっていた）
2. **カバレッジ判定**: 表示タイル（z12-15）のz12祖先タイル（`domain/region.py: tile_ancestor`、新規）が`road_graph_tiles`にマーク済みかで判定する。マーク済みならDBが正（0件でも正しい空）、未マークなら取込範囲外。2026-08-15からこの判定はMVT生成と同じ1クエリへ畳み込まれている（遠隔DBの往復1回分を節約。カバレッジ外ではCASE式の遅延評価によりMVT生成サブクエリ自体が実行されない）
3. DB接続不可・取込範囲外の場合は、`settings.overpass_fallback_enabled`（新設、既定true）に従いOverpassへフォールバック。falseなら空タイルを返す（**キャッシュには保存しない**。後からPBF取込された際に正しいタイルを再生成できるようにするため）。フォールバック発動・範囲外アクセスはログ方針に従い常時WARNINGで記録する
4. ~~将来最適化: PostGISの`ST_AsMVT`でMVT生成をSQL側へ寄せる案があるが、既存エンコーダとの出力互換検証が必要なため初期実装では見送った~~ → 2026-08-15に実施済み（上記1参照。出力互換は`tests/test_road_graph_repository.py`のMVTデコード検証で担保。Overpassフォールバック経路のみ従来の`encode_road_surface_tile`を使い続ける）

DIは`RegionService(overpass_client, http_client, repository=None, overpass_fallback_enabled=True)`の形で既存パターン（`GraphService`と同じ「repository任意注入」）を踏襲し、`road_graph_use_repository`有効時のみ注入する。実DB検証は`backend/scripts/verify_phase2_e2e.py`（9項目）で、取込範囲内タイルがPostGISのみで生成される（東京駅付近z14で3,304地物・Overpass呼び出し0回）ことを確認済み。

### Phase C: Overpass停止 ✅ 実施済み（2026-08-14、設定による無効化）

`overpass_fallback_enabled=false`で範囲外リクエストは「データ未整備」として空応答（路面タイル）/None（Road Graph）を返す。**フォールバックのロジックはコードに併存させ、設定のみで無効化する**（ユーザー指示。障害時・範囲拡大時の切り戻し手段として残す）。`GraphService`にも同フラグを追加し（Phase 2まではRegionServiceのみだった）、未取込タイルを含むルート生成リクエストはOverpassへ行かずNoneを返す。範囲外アクセス・フォールバック発動はログ方針に従い常時WARNINGで記録する。

**注意**: `repository`未注入（`road_graph_use_repository=false`）の構成では、このフラグに関わらず従来どおりOverpassが使われる（DBなし構成ではOverpassが唯一のデータソースのため。RegionService/GraphService両方とも同じ扱い）。

## 8. 更新運用（OSMデータの鮮度）

- **定期再取込方式**を基本とする: Geofabrikの抽出ファイルは日次更新されるため、月1回程度（または必要時）に最新PBFで再実行する。UPSERTなので差分だけが実際に更新される
- **削除されたwayの掃除**: UPSERTだけではOSM側で消えたwayが残る。再取込時に「取込bbox内で`updated_at` < 今回run開始時刻」のway行を削除するオプション（`--prune`）を設ける。Edge側は既存のdelete-then-reinsert（`save_graph`）と`ON DELETE CASCADE`が面倒を見る
- pyosmiumはOSM公式のminutely/daily diff（replication）適用もサポートしているが、**差分追従は現段階では導入しない**（運用の複雑さに対して、サイクリング用途で必要な鮮度は月次で十分）。将来の拡張ポイントとして記録のみ

## 9. 段階的導入計画

| Phase | 内容 | 前提 |
|---|---|---|
| **0（前提）** | ✅ **完了（2026-08-14）**。dev機で稼働中のネイティブPostgreSQL 18.6＋PostGIS 3.6.2に対し、`backend/scripts/verify_postgis_phase0.py`で22項目を検証し全PASS（`create_tables`冪等性・`save_raw_ways`/closure・GIN `&&`検索・`save_graph`のUPSERT/FK/delete-then-reinsert・bbox空間検索・ジオメトリ軸順往復・attributes・タイルマーカー・`GraphService`オーケストレーション）。Docker不要だった。詳細はarchitecture.md「実PostGISでの動作検証（Phase 0）」 | ~~Docker導入~~ 不要（ネイティブPG18を使用） |
| **1** | ✅ **完了（2026-08-14）**。取込バッチ本体（pyosmium＋プロファイル＋COPYバルクロード＋`osm_import_runs`＋タイルマーク＋geom列）を実装。BBBike Tokyo抽出（79MB）から150,265 way/511,948ノードを194秒で取込（bbox指定・z12タイル16枚マーク）し、E2E（東京駅・4km周回・Overpassスタブ注入）で**Overpass呼び出し0回**の8方位候補生成完走を確認（222.7秒）。実データ規模で顕在化した性能・並行性の3問題（行単位merge・GIN配列検索・AsyncSession同時使用）も修正（詳細はarchitecture.md「OSM PBF取込バッチ（Phase 1）」） | Phase 0 |
| **2** | ✅ **完了（2026-08-14）**。RegionServiceのPostGIS第一系統化（z12祖先タイルでのカバレッジ判定・`overpass_fallback_enabled`設定・DB障害/範囲外時のフォールバック）。あわせて容量予算対応として未使用GINインデックス（28MB）を削除し、取込バッチのサマリへ`db_size_mb`を追加。実DB検証`scripts/verify_phase2_e2e.py`で9項目PASS（詳細は7章Phase B） | Phase 1 |
| **3** | ✅ **完了（2026-08-14）**。本番想定DB＝**Supabase**（`.env`のDATABASE_URL）へ縮小bbox（35.61,139.67-35.74,139.83、東京駅・新宿・渋谷・上野・池袋を含む）を取込（116,336 way / 389,493ノード / z12タイル4枚 / 195秒 / 取込後120MB）。`GraphService`へもフォールバック無効化フラグを追加し、`.env`で`OVERPASS_FALLBACK_ENABLED=false`＋`ROAD_GRAPH_USE_REPOSITORY=true`に設定（**ロジックは併存、設定のみで無効化**）。Supabaseに対しPhase 2検証9項目・ルート生成E2E（8方位成功・Overpassゼロ・336.6秒）を確認。取込バッチはasyncpg直結用に`?ssl=require`→`sslmode=require`のDSN正規化を追加 | Phase 2 |
| **4** | ✅ **完了（2026-08-15）**。予算400MB内での関東圏への拡大: (1) `import_profile.yaml`のhighwayマッチを自転車で通行しうる13種別へ限定（生データ量が概算1/3に）、(2) Supabase上の既存データから除外種別（footway/service/steps等）をクリーンアップ（292MB→74.4MB）、(3) `road_edges.from_node_id`/`to_node_id`索引欠如を発見・修正（road_nodes削除27分→数秒）、(4) デフォルト位置（王子）中心の同心円半径別way/node件数をKanto PBF（Geofabrik、487MB）から1パスで分析、(5) ユーザー選定の半径25kmで実取込（273,947 way / 1,182,433ノード / z12タイル56枚 / 596.5秒 / 取込後342MB）。新規カバー範囲（大宮駅付近）でPostGISのみでのMVT生成をスモークテストで確認 | Phase 3 |

## 10. リスク・未解決事項

- **本番DBの容量（Supabaseフリー500MB・予算400MB）**: Phase 4（2026-08-15）で関東圏（Geofabrik kanto-latest.osm.pbf）全域をフィルタ後でも試算すると生データ層だけで約1.9GB（way 1,312,048件・node 8,900,206件）となり、フィルタリングだけでは関東7都県フルカバーには全く届かないことが実測で判明した。**現実的な運用は「王子（デフォルト位置）中心の同心円状に、実測サイズを見ながら段階的に広げる」**。Phase 4時点はSupabase実測342MB（残り約58MB）。**導出データ（road_edges/surface_attributes等）はルート生成が要求した地域ぶんだけ蓄積されていく**点に注意（生OSM層と違い取込時に確定しない。都心の実測では「フル活用時」に生データ層の約51%相当が追加で乗った）。ただし導出テーブルはすべて生OSM層から再計算可能なキャッシュなので、予算が逼迫したら該当行のDELETEが安全な圧力弁になる（次回リクエストで再生成される。ただしこの圧力弁自体がPhase 4で発覚した索引欠如の影響を受けていたため、`create_tables()`の再実行を先に済ませておくこと）。取込バッチが完了サマリに`db_size_mb`を出すため、超過は取込時点で気づける。さらに広げる場合は(1)半径をさらに広げて実測、(2)導出テーブルの圧縮（surface_attributesのway単位化等）、(3)有償プランを検討する
- ~~**毎リクエストの分割再計算・全量再保存のコスト**: タイル取得済みでも`get_or_build_graph_with_attributes`は生データからの交差点分割と全Edge再UPSERTを毎回行うため、都心bboxでprepareに約187秒かかる（E2E実測）。生データ不変時に`road_edges`を直接読む省略パスが次の最適化候補~~ → **解消済み**。`RoadGraphRepository.is_split_up_to_date`（`osm_raw_ways.split_at`と`updated_at`の比較）＋`get_graph_in_bbox`による省略パスを実装し、`GraphService.get_or_build_graph_with_attributes`に配線した（architecture.md「OSM PBF取込バッチ（Phase 1）」参照）
- ~~**実PostGIS未検証のコードの上に建てる**~~: **解消済み**。Phase 0で`road_graph_repository.py`の全操作を実PostGIS（ローカルPG18.6＋PostGIS 3.6.2）に対して検証した
- **開発用DBの選定が未決定**: `backend/.env`の`DATABASE_URL`は現在Supabase（クラウドPostgres）を指しており、Phase 0検証はローカルPG18へ環境変数で上書きして実施した。Phase 1着手時に「ローカルPG18／Supabase／Render Postgres」のどれを取込先の正とするか決める（取込バッチは`--database-url`でどこへでも向けられる設計のため、複数併用も可能）
- **バッチ実行中のランタイム競合**: 取込中もwebサービスは同じテーブルを読む。UPSERTは行単位で整合するが、取込途中の範囲は「wayはあるがタイルマークがまだ無い」状態になり得る。タイルマークを最後にまとめて行うことで「マーク済み＝データ完備」の不変条件を守る（マーク前にOverpassフォールバックが動いても、同一IDへのUPSERTなので害はない）
- **Windowsでのpyosmium**: wheelは提供されているが、大容量PBF処理のディスクバックインデックスの挙動はWindowsで実測して確認する
- **`osm_raw_nodes`の位置更新**: node側UPSERTを`DO NOTHING`にする簡略化は「ノードが移動した」ケースを取りこぼす。`--prune`付きの完全再取込で回収できるため許容とするが、気になる場合は`DO UPDATE`（位置比較付き）へ変更可能
