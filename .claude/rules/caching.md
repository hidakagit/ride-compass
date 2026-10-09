---
paths:
  - "backend/app/infrastructure/**"
  - "backend/app/services/**"
  - "backend/app/api/**"
  - "backend/app/domain/**"
---

# キャッシュ方針

**サーバーの中で一度得た値をどこに・どれだけ持つか**の決まり。クライアント側（ブラウザへ返す`Cache-Control`）は
`backend/app/api/cache_policy.py`の対応表が唯一の正本。

新しくキャッシュを足すとき、既存のキャッシュのTTLや保持方式を変えるときは、まずここを読む。

何を持ち、いつ捨てるか（Redisへ置くもの・TTL・無効化）は[caching-retention.md](caching-retention.md)が持つ。

## 大原則

1. **正本を持たないものだけをキャッシュする。** 失っても呼び出し元が再取得・再計算すれば正しい答えに戻れるものに限る。
   キャッシュが唯一の持ち主になっている状態を作らない。
2. **fail-open。** キャッシュ層の障害（Redis疎通不能・壊れたエントリ・ディスクエラー）はすべて「未キャッシュ」へ倒し、
   通常の取得経路へ進ませる。
3. **失敗は必ず記録する。** 失敗は`log_external_call`のfields（`result="error"`・`error_type`）へ載せ、Redisなら
   サーキットブレーカー（`record_redis_failure`）へも記録する。
4. **キャッシュで隠すのは遅さだけで、正しさを隠さない。** 「古い値でも返す」（stale fallback）を選ぶ場合は、
   どれだけ古いものまで許すかを定数で明示する。

## 入力（取得）と保持（キャッシュ）の対応

取得層と保持層は対で決める。**両方とも既存の共通骨格を使うのが既定**で、自前で書くのは下表の「例外」に当たるときだけ。

| 取得するもの | 入力（取得層） | 保持（キャッシュ層） |
|---|---|---|
| 更新頻度の低い外部JSON/CSV（警報・WBGT・洪水・地域マスタ） | `simple_api_client.py: cached_fetch` | プロセス内`cachetools.TTLCache`（クライアントのモジュールが作り、呼び出し側（`api/dependencies.py`）が持って`cached_fetch`へ渡す） |
| アメダスの観測 | `simple_api_client.py: cached_fetch` | `jma_amedas_store.py`（Redis。定期の取得が書き、読む側はRedisから読む） |
| 気象庁の動的タイル（ナウキャスト・キキクル等） | `jma_tile_client.py: JmaTileClient.fetch`（上流への秒間上限つき） | `jma_tile_redis_cache.py`（Redis） |
| 気象庁MSMの予報 | `msm_client.py: refresh`（ETag条件付きGETでファイル同期） | ローカルファイル（`backend/data/msm/`） |
| 色別標高図・基礎地図 | 各クライアント（`gsi_tile_client`・`basemap_client`） | `tile_cache.py`（ディスク、生バイト列） |
| PostGIS由来の重い中間結果 | リポジトリ層 | 用途で選ぶ（次節） |

新しい外部連携を足すときは、まず上表のどれと同じ性質かを考え、同じならその行の組み合わせをそのまま使う。

## 保持層の選び方

保持層は**2つの軸だけ**で決める。値の形式（バイト列かオブジェクトか）を層を増やす理由にしない。

| | 実体がRAMに載る | 実体がディスクに載る |
|---|---|---|
| **プロセス内**（そのプロセスだけ） | `cachetools`（`TTLCache`／`LRUCache`） | — |
| **プロセスをまたぐ** | **Redis**（既定） | ディスク（`tile_cache`・`tile_persistent_cache`） |

**「再起動しても残るか」は軸にならない。** 判断を分けるのは**実体がどこに載るか**と、**上限・退避を誰が持つか**である。

| | Redis | ディスク |
|---|---|---|
| 実体の置き場所 | **常にRAM**（VMのRAMをPostgreSQLと共有） | ディスク |
| 上限 | `maxmemory` 2GB | 無し（自分で管理する） |
| 退避 | `maxmemory-policy volatile-lru`＝**TTLのあるキーだけ**自動退避。TTLなしのキーで上限に達すると書き込みがエラーになる | 無し（自分で消す） |
| 使用量の可視化 | `INFO memory` | `du` |

### 速度は判断材料にならない（本番実測、2026-09-07）

速さを理由にRedisを選ばない。速度を改善したいなら、保持層の選択ではなく**シリアライズ形式**（pickle以外の表現）を変える。

**判断の順序**:

1. プロセス内で足りるならそれ
2. プロセスをまたぐ必要があり、**値が小さくTTLを付けられる**ならRedis
3. **数百MB規模、またはTTLを付けられない（＝いつまでも残ってよい）**ならディスク。ただし**掃除は自分の責任**（[caching-retention.md](caching-retention.md)「無効化」）

### プロセス内キャッシュは`cachetools`に統一する

追い出し処理（`OrderedDict`＋`move_to_end`＋`popitem`）を自前で書かない。TTLが要るなら`TTLCache`、件数上限だけなら
`LRUCache`。件数上限そのものの根拠（メモリ量の実測等）はコメントへ書く。

ライブラリで表現できない要件がある場合も、**自前で追い出しを書くのではなく`cachetools`を内側に包む**（包みは要件の分だけ
薄く持ち、立ち退き自体は`LRUCache`・`TTLCache`へ委ねる）。

テストで確かめるのは使う側の入口から見える振る舞いだけ（[testing.md](testing.md)「確かめる高さ」）。

**L1（プロセス内）＋L2（Redis）の2段構成は既定にしない。** 1段で足りることを確認してから、実測で必要性を示せたときだけ足す。

### ディスクを選ぶときの責任

ディスクを選ぶのは、**大きくて・TTLで自然消滅させたくない**ものである。ディスクを選んだ側は次を**必ず用意する**。

1. **容量の上限と退避**（`tile_persistent_cache.py`・`tile_cache.py`は`diskcache`の`size_limit`と退避の順（`eviction_policy`）で
   持つ。**自前で書かない**。退避の順は読み方で選ぶ——`least-recently-used`は読むたびに書き込みが走るため、
   地図の読み込みで大量に読まれる`tile_cache`は書いた順（`least-recently-stored`）にする）
2. **世代交代で不要になった実体を消す手段**と、それを**どこで呼ぶか**（上限とは別に要る。[caching-retention.md](caching-retention.md)「無効化」）
3. 使用量が想定内に収まっているかを確認する方法

鍵・読み書きの骨格・掃除は`infrastructure/`のモジュールが持ち（例: 地域タイルは`region_tile_cache.py`）、`services/`とは値で
やり取りする。上の層が`tile_cache.py`・`tile_persistent_cache.py`を直にimportすると`lint-imports`が落ちる
（[directory-layout.md](../../docs/architecture/directory-layout.md)「backend」）。

現在のディスク保持と掃除:

| 用途 | 掃除 |
|---|---|
| `tile_cache`（基礎地図・DEM・色別標高図の生バイト） | 容量上限（`tile_cache_size_limit_mb`）を超えると`diskcache`が書いた時刻の古い順に退避する |
| `tile_cache`のうち土地被覆タイル（PNG） | 起動直後と24時間ごとに、今開けているラスタ構成でない世代を消す（[caching-retention.md](caching-retention.md)「無効化」）。容量上限の対象でもある |
| `tile_cache`のうち地域のMVTタイル（路面・点。鍵`region/<系統>/v<世代>/…`） | 起動直後と24時間ごとに、配っていない世代を消す（[caching-retention.md](caching-retention.md)「無効化」）。容量上限の対象でもある |
| `msm`（予報の`.om`ファイル） | 同期のたびに予報窓の外を削除 |
| `tile_persistent_cache`（way_id別の動的値のpickle） | 容量上限＋`expire`による失効 |
| `road_network`（取込範囲全体の道路網の配列、世代ごとの置き場。メモリマップで開く） | 作ったときに同じ形の古い世代を削除、起動後に形の違う置き場を削除 |

これらをRedisへ移さない。

## 直接使ってよい場所

`get_redis_client_or_none`・`record_redis_failure`・`record_redis_success`・`redis_available`を直接呼んでよいファイルは
`backend/tests/structure/test_redis_skeleton.py: ALLOWED`が持つ（骨格そのもの・その接続本体と、単一キーのJSON読み書きでは
表現できないもの）。ここに無いファイルで使うとテストが落ちる。寄せられない事情があるなら、理由とともに`ALLOWED`へ足すこと。

**寄せ終わったのに`ALLOWED`へ残っている場合も落ちる**。

## 関連

- クライアント側の`Cache-Control`: `backend/app/api/cache_policy.py`の対応表
- 外部API取得層の共通骨格: `simple_api_client.py: cached_fetch`
- 各キャッシュの実装詳細: [docs/modules/backend/cross-cutting-infrastructure.md](../../docs/modules/backend/cross-cutting-infrastructure.md)
- ログの出し方（`log_external_call`のfields）: [.claude/rules/logging.md](logging.md)
