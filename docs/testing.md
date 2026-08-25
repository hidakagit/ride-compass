# テスト方針（実行効率を保つためのパターン）

RideCompassのテストスイートは規模が大きい（backend 800件超、frontend 330件超）。
**新しいテストを追加するときは、以下のパターンに従って実行時間の増加を最小限に抑えること。**
2026-08-18の実効性改善（backend 243秒→47秒、frontend 246秒→193秒）で得た知見をまとめたもの。

## 基本原則

1. **ループで実I/O（HTTPリクエスト・新規DB接続）を繰り返さない。** 「上限回数まで実行してから
   1回超過させる」ようなN回ループの検証は、境界に到達する直前までを実I/O無しで埋め、境界の
   1〜2回だけ実際に実行する。
2. **新規リソース（DB接続・テスト環境）の構築コストはテストスイート全体で使い回せないか検討する。**
   テスト関数ごとに新規構築するコストが積み重なると、テストの絶対数に比例して線形に遅くなる。
3. **速度最適化はテストが検証する内容を変えない範囲で行う。** 上記のいずれも「境界条件の実地検証」
   自体は残し、その手前の準備コストだけを削る。カバレッジを犠牲にしない。

## パターン1: レート制限テスト → rate_limiterを直接埋める

```python
from app.infrastructure import rate_limiter

def test_xxx_is_rate_limited_per_client():
    ...
    for _ in range(settings.xxx_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("xxx:testclient", settings.xxx_rate_limit_per_minute)
    assert client.get(...).status_code == 200  # 境界の1回だけ実HTTP
    response = client.get(...)
    assert response.status_code == 429
```

`TestClient`の接続元`client_id`は常に`"testclient"`（`app/api/dependencies.py: client_id`参照、
`test_client_ip_behind_proxy.py`で検証済み）。キーのprefixは各routerの
`check_rate_limit(f"{prefix}:{client_id(request)}", ...)`呼び出しに合わせる。

実例: test_region_routes.py, test_weather_route.py, test_basemap_routes.py,
test_accident_routes.py, test_routes_preview.py, test_routes_generate.py

## パターン2: PostGIS統合テスト（road_graph_session）→ ファイル単位でエンジン・イベントループを共有

`conftest.py`の`road_graph_session`/`road_graph_repository`はテストファイル（モジュール）単位で
1本のDB接続・イベントループを使い回す設計（新規DB接続の確立自体に1〜2秒かかるため、テスト関数
ごとに新規作成すると規模の大きいファイルでテスト全体の時間を大きく押し上げる。ローカル環境での
実測、localhost/127.0.0.1どちらでも同程度でDNS起因ではない）。

新しいテストファイルでこれらのフィクスチャを使う場合:

1. ファイル冒頭に `pytestmark = pytest.mark.asyncio(loop_scope="module")` を付ける
   （同期テストが同じファイルに混在していても影響しない）。
2. ファイル内で自前の追加async fixtureを定義してroad_graph_session/road_graph_repositoryに
   依存させる場合は、その自前fixtureにも明示的に`loop_scope="module"`を付ける
   （`@pytest_asyncio.fixture(loop_scope="module")`）。省略すると
   `MultipleEventLoopsRequestedError`になる。
3. 素の`@pytest.fixture`でasync generatorを書かない。`@pytest_asyncio.fixture`を明示的に使う
   （前者は互換用の内部変換パスを通り、モジュールスコープのイベントループと衝突する）。

実例: test_road_graph_repository.py, test_health.py（db_status_test_engine）,
test_match_designations.py（designation_conn）, test_accident_repository.py

**xdist_group="postgis"（改善計画T233フォローアップ、pytest-xdist導入後は必須）**:
CIは`-n auto --dist loadgroup`でDB以外のテストを並列化している。road_graph_session系
フィクスチャを使うテスト（ファイルまたは個別テスト関数）には必ず
`pytest.mark.xdist_group(name="postgis")`を付け、`pytestmark`が既にリストでなければ
`pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis")]`
の形にする。これを付けないと、同じridecompass_test DBへ複数workerが同時接続し、
他ファイルのTRUNCATEでテストデータが消える形のflakyな失敗を起こしうる。

## パターン3: フロントエンドのテスト環境 → DOM不要ならnode環境

DOM（render/renderHook/window/document等）を使わない純ロジックのテストファイルは、
ファイル先頭へ`// @vitest-environment node`docblockを付けてnode環境に倒している。
DOM環境の構築コストはテストファイルごとにかかるため、対象外にできるファイルが増えるほど
実行時間が縮む（旧`vitest.config.mts`の`environmentMatchGlobs`による一括指定は、Vitest 4で
同オプションが廃止されコンパイルエラー・ランタイムでの黙殺の両方を引き起こしたため
改善計画T126で撤去済み。バージョン間で仕様が安定しているdocblock方式へ移行した）。
既定のDOM環境自体も改善計画T329でjsdomからhappy-domへ変更済み（テストスイート全体の
実行時間が約35%短縮。canvas.getContext("2d")が未実装でnullを返す等、既存テストが依存する
挙動はjsdomと同一であることを確認済み。個別ファイルで`// @vitest-environment jsdom`を
付ければ従来のjsdomへ戻せる）。

新規テストファイルがservices/lib配下やMap内の式・フィルタ関数のようにDOMに触れない場合、
このdocblockの追加を検討する。省略してもデフォルトのhappy-domのままなので壊れることはない
（速度だけの問題）。判断に迷ったら、そのテストファイルが
`render`/`renderHook`/`screen`/`document`/`window`のいずれかを使っているか確認する
——ただし**テストファイル自身だけでなく、importしている実装側の関数が内部で
`document.createElement`等を呼んでいないかも確認すること**（`windArrowIcon.ts`が
`document.createElement("canvas")`を使う実例。テストファイル単体では判断できない
「実装側の隠れたDOM依存」を見落とし、node環境化すると実行時エラーになる）。

## パターン4: フロントエンドのPlaywright（E2E）→ 本番同等サーバー・ローカルworkers=1

1. **webServerは本番と同じエントリポイントを使う。** `frontend/next.config.ts`は
   `output: "standalone"`（本番Dockerfileが`node server.js`で起動する構成）のため、
   `playwright.config.ts`のwebServerも`npm run build && npm run start:standalone`
   （`frontend/scripts/prepare-standalone.mjs`でDockerfileのCOPY相当を再現してから
   `node .next/standalone/server.js`を起動）を使う。以前は`next start`
   （`npm run start`）を使っていたが、standalone構成とは組み合わせ不可という警告が
   出ており、standalone構成固有の問題（静的アセット配置ずれ等）をE2Eが検知できない
   状態だった（T252併用導入の実機検証で発覚、2026-08-23）。
2. **ローカル実行はworkers=1に固定する。** `playwright.config.ts`の既定
   （CPU論理コア数ベースの並列worker）のまま実行すると、同一のwebServer（Next.js
   サーバー1プロセス）へ複数のヘッドレスChromiumが同時に地図（MapLibre GL・WASM）を
   読み込みに行き、ページ遷移・`beforeEach`フックが軒並み30秒タイムアウトする事象を
   複数回実測した（2026-08-23）。workers=1へ絞ると同条件で安定して全green。
   CIはGitHub Actions側のジョブ専有リソースを前提に対象外（`process.env.CI`判定）。
