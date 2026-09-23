# ディレクトリ構成

トップは`backend/`（FastAPI）・`frontend/`（Next.js）・`docs/`・`scripts/`（リポジトリ横断の
CI・pushフック用スクリプト）。

**個々のファイルがどのモジュールの責務かはここに書かない。**
各モジュール設計書（索引は[docs/modules/README.md](../modules/README.md)）の対象ファイル表が
持つ。表の完全性は**機械では検査していない**——ファイルを足した人が同じコミットで表へ
載せ、漏れは周期レビューで人が見る。ここでは**層の役割と、層をまたぐときの約束**
だけを示す。

## backend（`backend/app/`）

依存の向きは `api → services → domain` と `api → services → infrastructure` の一方向で、
`domain`はどの層にも依存しない。

- **`api/`**: HTTPの境界。`routers/`がエンドポイント、`dependencies.py`がDI工場と
  レート制限、`admin_auth.py`が管理APIの認可境界、`cache_policy.py`が`Cache-Control`を
  一元管理する。タイル系エンドポイントが共有する座標検証と応答組み立ては`_tile_http.py`。
- **`domain/`**: 外部I/Oを持たない純粋なロジックと語彙の正本。評価軸・材料・一次属性の
  レジストリ、スコアリング、地理計算、気象の判定ロジックが属する。**「同じ概念の定義が
  2箇所にある」状態をここで解消する**のが層の役割で、SQL・タイル・frontendはここが持つ
  定義から導出する。
- **`services/`**: ユースケースの組み立て。ルート生成・タイル配信・気象取得のように
  「複数のinfrastructureとdomainを束ねて1つの応答を作る」処理が属する。
- **`infrastructure/`**: DB・外部API・キャッシュ・ログといった外側との接続。キャッシュの
  鍵の組み立ては`cache_identity.py`が唯一の正本。
- **`batch/`**: 外部ソースの取込（`ingest*`・`source_adapters/`）と派生の生成
  （`derive_*`）。**実行順は`derive_cli.py`だけが持つ**。書き込みに成功したバッチは
  `derived_data_meta.revision`（DB）を進め、backendのディスクキャッシュがこれに追随する
  ——バッチはデプロイを伴わないため、コード内の定数では表せない。

スキーマは`infrastructure/`のORM宣言から`create_tables()`が作る。`backend/scripts/`は
運用・生成スクリプトで、`export_openapi.py`がfrontend向けの生成物を書き出し、
`bootstrap_database.py`がまっさらなDBをスキーマ→取込→派生の順で立ち上げる。

**評価軸の行データはコードにもmigrationにも無い。** `axis_definitions`テーブルが唯一の
正本で、変更は軸スタジオ（`/api/admin/axis-definitions`）経由のみ
（CLAUDE.md「コミット時の同期ルール」）。

## frontend（`frontend/src/`）

- **`app/`**: Next.js App Routerのページとroute handler（`/admin`配下の管理APIプロキシを含む）。
- **`components/`**: 機能単位のディレクトリ（`Map/`・`AxisStudio/`・`MapOverlayControls/`等）。
- **`hooks/`・`lib/`**: 画面をまたぐ状態・ユーティリティ。
- **`services/`**: backend APIを叩く薄い層。
- **`types/generated/`**: `export_openapi.py`の出力（OpenAPIスキーマと、材料カタログ・
  タイル世代等の付随生成物）。コミット対象で、CI（`ci.yml`）の`api-contract`ジョブがドリフトを検知する。
  OpenAPIスキーマは**契約だけ**を持ち、docstring由来の散文は載せない。

**backendが持つ値の一覧・既定値をfrontendが手書きで複製しないこと**——複製すると片側だけ
変えても全テストが緑のまま通り、キー集合の完全一致を要求するAPIでは全リクエストが422に
なる等の形で本番に出る。必要な値は`types/generated/`経由の片側importで受け取る。

**ただし軸カタログだけはビルド時の写しを持たない**（[design-principles.md](design-principles.md)
構造仕様9）。軸はGUIから増減するため、実行時の`GET /api/axis-catalog`だけを読む。
