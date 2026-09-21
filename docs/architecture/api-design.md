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
| ルート生成 | `/api/routes/generate`・`/api/routes/preview` | 不要 | ジョブの`error`／502 |
| 天候・防災バッジ | `/api/weather/*` | 不要 | 予報・実測は502、警報系は空応答（fail-open） |
| 地図タイル | `/api/region/*-tiles`・`/api/basemap/*`・`/api/jma-tile/*`・`/api/gsi-*-tile/*` | 不要 | 空タイル／502 |
| 軸・材料カタログ | `/api/axis-catalog`・`/api/material-catalog` | 不要（読み取り専用） | 502 |
| 管理 | `/api/admin/*` | HTTP Basic必須 | 401／404／422 |

## 全体に効く約束

- **スネークケース**。フロント⇔バックエンドで名前を変換しない。
- **取得できなかった値はnullで返し、キーを消さない**（標高系・`overall_difficulty`・
  区間ごとの各値）。フロントはnull許容で扱う。ただし**軸の辞書だけは逆**で、
  評価できなかった軸・非公開の軸は**キー自体を持たない**（`axis_difficulties`・
  `axis_contributions`・`material_values`）。軸はGUIから増減するため、固定フィールドを
  持たない汎用dictで運ぶ。
- **上書きは全フィールド必須**。`route_preference`（公開軸のaxis_idを全件）・`hard_filters`は
  部分指定を422で拒む——部分指定を許すと、指定しなかった項目にクラス既定値が黙って入り、
  「送った覚えのない条件で生成された」状態になる。公開軸はDBが正本で軸スタジオから
  増減するため、**現在のキー集合は`GET /api/axis-catalog`で引く**。
- **レート制限は経路ごとに別枠**（`infrastructure/rate_limiter.py`、プロセス内メモリの
  固定窓）。上限値の正本は`backend/app/config.py: Settings`。地図を眺めてタイルを引いた
  だけで区間インスペクタが引けなくなる、といった巻き添えを避けるため枠を結合しない。
- **`Cache-Control`は`api/cache_policy.py`が一元管理する**。新規エンドポイントの
  追加漏れは`tests/test_cache_policy.py`が全ルート走査で検出する。
- **防災・警報系だけはfail-open**（地点解決・上流取得のどこで失敗しても例外にせず空応答）。
  他の`/api/weather`系が502を返すのと意図的に非対称で、安全側ではないトレードオフを
  承知で選んでいる。

## ルート生成だけが非同期ジョブになっている

`POST /api/routes/generate`は202で`job_id`だけを返し、`GET /api/routes/generate/{job_id}`を
ポーリングして結果を受け取る。冷パス（材料キャッシュの無い範囲への初回アクセス）が
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

- ズーム範囲外・タイル座標が範囲外（`0 <= x,y < 2**z`）は400。通常はMapLibreが要求
  しないため、直接叩かれた場合の安全弁。
- 取込範囲外・DB障害は**エラーではなく空タイル**を返す（MapLibreは失敗したタイル要求を
  再試行しないため、広範囲が永久に空白になるのを避ける）。**恒久的な空と一時的な空を
  `Cache-Control`で区別する**——詳細は
  [静的道路属性・タイル配信](../modules/backend/static-road-attributes.md)。
- 同時実行数の超過は429ではなく**待たせて全件処理**する（同じ理由）。
