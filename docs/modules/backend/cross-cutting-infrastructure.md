# 横断基盤（backend）

## 責務

DB接続・マイグレーション・Redis・HTTPクライアント・レート制限・ログ・デバッグ機構・
非同期ジョブ管理という、特定のドメイン機能に属さない横断的な基盤を提供する。

**対象ファイル**（すべて`backend/app/infrastructure/`）

| ファイル | 責務 |
|---|---|
| `database.py` | PostGIS接続（SQLAlchemy） |
| `migrate.py` | 最小マイグレーション機構（番号付きSQL） |
| `redis_client.py` | Redis共有クライアント |
| `http_client.py` | 外部API向け共有HTTPクライアント |
| `rate_limiter.py` | プロセス内メモリのみの固定窓レート制限 |
| `request_log.py` | リクエストIDの付与、1リクエスト=1行のHTTPアクセスサマリログ |
| `debug_log.py` | 外部I/O（外部API・タイル/標高キャッシュ）イベントのログと集計 |
| `debug_control.py` | `debug_mode`のランタイム切替・直近ログの保持 |
| `job_registry.py` | 汎用の非同期ジョブレジストリ（プロセス内メモリのみ） |

## ログ方針（`debug_log.py`）

| イベント種別 | レベル | 条件 |
|---|---|---|
| 成功 | DEBUG | `debug_mode=True`時のみ実質出力（タイル系は毎分数百イベントになりうるため常時出力しない） |
| 失敗 | WARNING | **常時**出力（`debug_mode`に関わらず）。カテゴリごと固定窓（60秒）`WARN_BURST_PER_WINDOW=5`件で抑制、超過分は窓切り替わり時に件数のみ報告 |

全イベントはカテゴリ単位でプロセス内カウンタへ集計し、`GET /api/debug/stats`が呼び出し
回数・エラー数・キャッシュヒット率・平均/最大所要時間を返す。常時出力されるWARNINGの
座標値は小数2桁（≈1km）へ丸める（ユーザーの現在地由来の座標が含まれうるため）。

`error_type_label(exc)`: 例外を`/api/debug/stats`へ出しても安全な粗いラベル
（クラス名＋HTTPステータスコードのみ、メッセージ・URLは含めない）へ変換する。

## レート制限（`rate_limiter.py`）

プロセス内メモリのみの固定窓（`_WINDOW_SECONDS=60.0`）カウンタ。`check_rate_limit
(client_id, max_requests, window_seconds)`が直近ウィンドウ内のリクエスト数を判定する。
`_sweep`が`_SWEEP_INTERVAL_SECONDS=300.0`ごとに、直近ウィンドウ内にヒットが無い
client_idキーを間引く（IPローテーションによるメモリリーク防止）。

## マイグレーション（`migrate.py`）

番号付きSQLファイル（`backend/migrations/`）を順に適用する最小機構。行データの変更は
含まない（[軸スタジオ・評価軸定義](axis-studio.md)「行データはAPI経由」参照）。

## ジョブレジストリ（`job_registry.py`）

プロセス内メモリのみの非同期ジョブ管理。[ルート生成エンジン](routing-engine.md)の
`POST /api/routes/generate`（202即時応答＋ポーリング）が使う。サーバー再起動で
ジョブは失われる。
