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

## パターン3: フロントエンドのテスト環境 → DOM不要ならnode環境

`vitest.config.mts`の`environmentMatchGlobs`で、DOM（render/renderHook/window/document等）を
使わない純ロジックのテストファイルはnode環境に倒している。jsdom環境の構築コストはテスト
ファイルごとにかかるため、対象外にできるファイルが増えるほど実行時間が縮む。

新規テストファイルがservices/lib配下やMap内の式・フィルタ関数のようにDOMに触れない場合、
`environmentMatchGlobs`への追加を検討する。省略してもデフォルトのjsdomのままなので壊れる
ことはない（速度だけの問題）。判断に迷ったら、そのテストファイルが
`render`/`renderHook`/`screen`/`document`/`window`のいずれかを使っているか確認する。
