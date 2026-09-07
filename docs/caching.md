# キャッシュ方針

サーバー側で「一度得た値をどこに・どれだけ持つか」の決め方をここに集約する。
クライアント側（ブラウザへ返す`Cache-Control`）は`backend/app/api/cache_policy.py`の
対応表が唯一の正本で、本ファイルはその手前——**サーバーの中でどう保持するか**を扱う。

新しくキャッシュを足すとき、既存のキャッシュのTTLや保持方式を変えるときは、まずここを読む。

## 大原則

1. **正本を持たないものだけをキャッシュする。** ここで扱うキャッシュはすべて、失っても
   呼び出し元が再取得・再計算すれば正しい答えに戻れるものに限る。キャッシュが唯一の
   持ち主になっている状態を作らない。
2. **fail-open。** キャッシュ層の障害（Redis疎通不能・壊れたエントリ・ディスクエラー）は
   すべて「未キャッシュ」へ倒し、通常の取得経路へ進ませる。キャッシュの不調でアプリの
   機能を止めない。
3. **fail-openだからこそ、失敗は必ず記録する。** 握り潰したまま何も残さないと、障害が
   「少し遅くなっただけ」に見えて誰も気づけない。失敗は`log_external_call`のfields
   （`result="error"`・`error_type`）へ載せ、Redisならサーキットブレーカー
   （`record_redis_failure`）へも記録する。この記録が抜けると**壊れていることを検知する
   仕組みだけが静かに死ぬ**——これがキャッシュ実装で最も起きやすい欠陥である。
4. **キャッシュで隠すのは遅さだけで、正しさを隠さない。** 「古い値でも返す」（stale
   fallback）を選ぶ場合は、どれだけ古いものまで許すかを定数で明示する。

## 入力（取得）と保持（キャッシュ）の対応

取得層と保持層は対で決める。**両方とも既存の共通骨格を使うのが既定**で、自前で書くのは
下表の「例外」に当たるときだけ。

| 取得するもの | 入力（取得層） | 保持（キャッシュ層） |
|---|---|---|
| 更新頻度の低い外部JSON/CSV（警報・WBGT・洪水・アメダス観測・地域マスタ） | `simple_api_client.py: cached_fetch` | プロセス内`cachetools.TTLCache`（`cached_fetch`が内包） |
| 気象庁の動的タイル（ナウキャスト・キキクル等） | `jma_tile_client.py: fetch`（上流への秒間上限つき） | `jma_tile_redis_cache.py`（Redis） |
| 気象庁MSMの予報 | `msm_client.py: refresh`（ETag条件付きGETでファイル同期） | ローカルファイル（`backend/data/msm/`）。プロセスをまたいで残る |
| 地理院DEM・色別標高図・基礎地図 | 各クライアント（`elevation_client`・`gsi_relief_tile_client`・`basemap_client`） | `tile_cache.py`（ディスク、生バイト列） |
| PostGIS由来の重い中間結果 | リポジトリ層 | 用途で選ぶ（次節） |

新しい外部連携を足すときは、まず上表のどれと同じ性質かを考える。同じならその行の
組み合わせをそのまま使う。

## 保持層の選び方

| 層 | 使う場面 | 実装 | 生存期間 |
|---|---|---|---|
| プロセス内（TTL付き） | 小さく・全プロセスで同じ値・再取得が安い | `cachetools.TTLCache` | プロセスが死ぬまで |
| プロセス内（件数上限のLRU） | 大きなオブジェクトで、古さより**常駐メモリ量**が問題になるもの | `search_graph_cache`・`graph_material_cache`・`tile_score_matrix_cache` | 同上 |
| Redis | 複数プロセス・再起動をまたいで共有したい。値が小さくJSONで表せる | **`redis_json_cache.py`の`get_json`/`set_json`**（後述） | TTLで消える |
| ディスク（生バイト） | 外部から取ったバイナリをそのまま返すだけのもの | `tile_cache.py` | 手動で消すまで |
| ディスク（Pythonオブジェクト） | 再計算が高価で、デプロイをまたいで残したいもの | `tile_persistent_cache.py` | 世代番号を上げるまで |

**判断の順序**: (1) プロセス内で足りるならそれが最も安い → (2) 再起動・複数プロセスを
またぐ必要があるならRedis → (3) バイナリ実体が大きい、または再計算が数十秒規模ならディスク。

## Redisへ持つときは`redis_json_cache`を使う

「Redisが使えるか確認 → クライアント取得 → `log_external_call`で計測 → 失敗は握り潰して
未キャッシュ扱い → 成否をサーキットブレーカーへ記録」という14行ほどの定型文は、
`redis_json_cache.py`の`get_json`/`set_json`が内包している。**呼び出し元が持つのは
キー設計・TTL・値の意味づけだけ**にする。

```python
from app.infrastructure.redis_json_cache import get_json, set_json

value = await get_json(key, category="cache:xxx")            # ミス・障害はNone
await set_json(key, payload, ttl_seconds=TTL, category="cache:xxx")
```

**自前で骨格を書いてよい例外**（該当する場合はその理由をモジュールのdocstringへ書く）:

- `mget`/`pipeline`による一括読み書きが必要（1リクエストで数百キーを引く等）
- 値がバイナリで、JSON化すると容量・CPUの無駄が無視できない
- キーの生存期間を個別に操作する必要がある（`ex`以外のRedis機能を使う）

例外に当たる場合も、原則3（失敗の記録）と原則2（fail-open）は必ず満たす。

**移行中の状態**: 既存の`jma_tile_redis_cache`・`dynamic_way_value_cache`・
`road_edge_geometry_cache`・`road_graph_tile_cache`は共通骨格ができる前に書かれたもので、
各自の実装のまま動いている（[T644](tasks/T644.md)で順次移行する）。**これらを新しい
キャッシュのお手本にしない。**

## TTLの決め方

**数字を書くときは、必ず「何に合わせた値か」をコメントへ書く。** 根拠の無いTTLは
レビューできず、上流の仕様が変わったときに誰も直せない。決め方は次のいずれかに揃える。

| 類型 | 決め方 | 現在の例 |
|---|---|---|
| 上流の更新間隔に合わせる | 上流の更新周期 ＋ 取り込みの余裕 | アメダス観測15分（バッチ10分＋余裕）、MSM由来の派生値＝配信元のrun更新間隔（`msm_client.update_interval_seconds()`） |
| 内容が変わらない期間に合わせる | 内容が確定して以後変化しないなら、その識別子が有効な間 | JMAタイル本体20分（`basetime`が変わればキーも変わる） |
| ほぼ不変なマスタ | 1日 | 地域マスタ・WBGT地点マスタ・観測所一覧（いずれも24時間） |
| 共有率で決める | 短くしすぎるとヒットせず、長くすると鮮度を失う中間 | `targetTimes`2分 |
| 再計算コストで決める | 失っても計算し直すだけなら長め | 道路形状・タイル取得済みマーカー（24時間） |

**避けること**: 「なんとなく10分」。上のどれにも当てはまらない場合は、その値にした理由を
1行で書けるかを先に確認する。書けないなら、まだ決め方が定まっていない。

## 「取っても得るものが無い」ことの覚え方

疎なデータ（気象庁の動的タイル・整備区域外のDEM等）では、**空振りを覚えること自体が
キャッシュの目的**になる。同じ「得るものが無い」でも、覚える対象と減らせる通信が違う。

| 種類 | 覚えるもの | 減る通信 |
|---|---|---|
| 恒久404 | 上流に存在しないパス | サーバー → 上流 |
| 空の実体 | 200で返るが中身が空（透明タイル等） | クライアント → サーバー |
| 在否インデックス | 「その範囲のどこが空か」の一覧 | クライアントの要求自体を発生させない |

新しく疎なデータを扱うときは、**どれが要るのかを先に決める**（3つとも要るとは限らない）。
現状の整理と統合の検討は[T644](tasks/T644.md)。

## 無効化（キャッシュを捨てる）

**既定は世代番号**。キー自体に世代を埋め、上げた瞬間から新旧が別物になる方式にする
（`ROAD_SURFACE_TILE_VERSION`・`TILE_MATERIALS_CACHE_VERSION`・
`TILE_SCORE_MATRIX_CACHE_VERSION`）。古い値は参照されなくなるだけで、消す操作が要らず、
消し忘れ・巻き添えが起きない。

**全消し（`tile_cache.clear_all()`）は例外**。他レイヤーのキャッシュまで巻き添えにするため、
運用操作としてのみ残す。新しいキャッシュへ全消し手段を足さない。

焼き込み値（MVTのCASE式・材料タグ・domain純関数）を変えたら、対応する世代定数と生成物を
**同一コミットで**上げる（CLAUDE.md「コミット時の同期ルール」）。

## 機械的な強制（未実装、[T647](tasks/T647.md)）

この方針は現時点では人が読んで守るだけで、機械的なチェックが無い。`get_redis_client_or_none`・
`record_redis_failure`を`redis_client.py`・`redis_json_cache.py`以外で新たに使ったら
`scripts/review_checks.py docs`（pre-commitとCIが実行）が違反として検出する形を予定して
いる。例外に当たるモジュールは許可リストで免除し、理由をdocstringへ書く。

## 関連

- クライアント側の`Cache-Control`: `backend/app/api/cache_policy.py`の対応表（[T632](tasks/T632.md)）
- 外部API取得層の共通骨格: `simple_api_client.py: cached_fetch`（[T488](tasks/T488.md)）
- 各キャッシュの実装詳細: [docs/modules/backend/cross-cutting-infrastructure.md](modules/backend/cross-cutting-infrastructure.md)
- ログの出し方（`log_external_call`のfields）: [docs/logging.md](logging.md)
