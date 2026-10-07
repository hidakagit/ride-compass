# API設計（現状）

backendが公開するHTTP APIの**全体の形**と、エンドポイントをまたいで共通に効く約束を記す。

**エンドポイントの全件・各応答のフィールドはここに書かない。** 正本は
`backend/scripts/export_openapi.py`が書き出す`frontend/src/types/generated/openapi.json`
（コミット対象、CIの`api-contract`ジョブがドリフトを検知する）で、frontendの型も
そこから生成される。個々の挙動・制約はモジュール設計書
（[docs/modules/README.md](../modules/README.md)）が持つ。

**この生成物が運ぶのは契約だけ**——名前・型・required・enum。docstring由来の散文は
書き出す前に落としてあるため、コメントを直しても生成物は動かない。散文を読むなら
稼働中のアプリの`/docs`（`/openapi.json`）を見る。

## 群と、群ごとの性格

| 群 | 例 | 認可 | 失敗時 |
|---|---|---|---|
| 運用 | `/health`・`/api/debug/stats` | 不要（集計値のみ） | — |
| ルート生成 | `/api/routes/generate` | 不要 | ジョブの`error` |
| 天候・防災バッジ | `/api/weather/*` | 不要 | 502（警報系の空応答は「出ていない」だけ） |
| 地点の検索 | `/api/place-search` | 不要 | 503（住所の辞書が無い。この口だけが使えない）／502（対象範囲を読めない）。空の応答は「当たらなかった」だけ |
| 地図タイル | `/api/region/*-tiles`・`/api/basemap/*`・`/api/jma-tile/*`・`/api/gsi-*-tile/*` | 不要 | 空タイル／502 |
| 軸カタログ | `/api/axis-catalog` | 不要（読み取り専用） | DBから読む値（事故の収録年・タイルの世代）だけ空へ倒す |
| 管理 | `/api/admin/*` | HTTP Basic必須 | 401／404／422／503（DBの障害。どの口も`api/admin_db_errors.py`の1か所で返す） |

## 全体に効く約束

- 応答の型の約束（名前の付け方・取得できなかった値・いつも一緒に決まる値・軸の辞書）は
  [data-model.md](data-model.md)「命名と欠損」「軸に関わる値だけは「キー自体を持たない」」が持つ。
- **上書きは全フィールド必須**。`route_preference`（公開軸のaxis_idを全件）・`hard_filters`は
  部分指定を422で拒む——部分指定を許すと、指定しなかった項目にクラス既定値が黙って入り、
  「送った覚えのない条件で生成された」状態になる。公開軸はDBが正本で軸スタジオから
  増減するため、**現在のキー集合は`GET /api/axis-catalog`で引く**。
- **レート制限は経路ごとに別枠**（`infrastructure/rate_limiter.py`、プロセス内メモリの
  移動窓）。上限値の正本は`backend/app/config.py: Settings`。地図を眺めてタイルを引いた
  だけで区間インスペクタが引けなくなる、といった巻き添えを避けるため枠を結合しない。
- **`Cache-Control`は`api/cache_policy.py`が一元管理する**。新規エンドポイントの
  追加漏れは`tests/test_cache_policy.py`が全ルート走査で検出する。
- **防災・警報系の空応答は「出ていない」だけを表す**。地点解決・上流取得に失敗して出ているかが
  分からないときは、他の`/api/weather`系と同じく502を返す——空で返すと、画面は警報が出ていないと
  見せてしまい、利用者は取れていないことに気づけない。

## ルート生成だけが非同期ジョブになっている

`POST /api/routes/generate`は202で`job_id`だけを返し、`GET /api/routes/generate/{job_id}`を
ポーリングして結果を受け取る。生成は数秒〜数十秒かかり（探索範囲が広いほど長い）、
ブラウザのfetchを長時間ブロックするのを避けるため。

- ジョブはプロセス内メモリのみで、**サーバー再起動で失われる**
  （`infrastructure/job_registry.py`、完了から一定時間でパージ）。
- バックグラウンドタスクの例外はHTTPレスポンスへ伝播できないため、`status="failed"`と
  `error`に記録して初めてクライアントが知る。
- per-IPのレート制限と同時実行数の上限は**投稿時点**で効く（待ち行列化していない）。
  ポーリング側は軽量なメモリ参照のみのため制限を課さない。

実行が`asyncio.create_task`であってFastAPIの`BackgroundTasks`でない理由・タスク参照の
保持は[ルート生成エンジン](../modules/backend/routing-engine.md)を参照。

## 生成条件はレスポンスへエコーする

`conditions`（`GenerationConditions`）が、その生成に**実際に適用された**条件を全フィールド
埋めて返す。上書きした値と既定値のどちらが効いたかを応答だけで判別できるため、
レスポンスJSONを保存すればそのまま再現条件になる。

## タイル系の共通規約

- ズーム範囲外・タイル座標が範囲外（`0 <= x,y < 2**z`）は、ほかの要求の欄の外れと同じ422。ズームと列・行の
  下限は経路の引数の型（`domain/region.py: RoadTileZoom`・`TileIndex`等）、列・行の上限は
  `domain/region.py: check_tile_index`が見る。通常はMapLibreが要求しないため、直接叩かれた場合の安全弁。
- 取込範囲外・DB障害は**エラーではなく空タイル**を返す（MapLibreは失敗したタイル要求を
  再試行しないため、広範囲が永久に空白になるのを避ける）。**恒久的な空と一時的な空を
  `Cache-Control`で区別する**——詳細は
  [静的道路属性・タイル配信](../modules/backend/static-road-attributes.md)。
- 同時実行数の超過は429ではなく**待たせて全件処理**する（同じ理由）。
