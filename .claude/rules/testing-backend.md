---
paths:
  - "backend/tests/**"
  - "backend/pytest.ini"
---

# backendのテストの書き方

## 性質で確かめる（hypothesis）

**任意の入力で成り立つ性質が実装か公開の仕様から言える計算は、例を並べる代わりに性質で書く**（backendは
hypothesisの`@given`）。向くのは幾何・座標変換・補間のような、連続した入力の範囲を持つ純関数である。

**性質で書いたら、その性質が覆う例は書かない。** 性質の主張が成り立つが乱数がまず引かない入力——境界ちょうどの値
（`<=`と`<`の違い）・過去のバグを刺した入力——は、別の例のテストにせず、性質のテストに`@example`で必ず付ける。
例のテストで残すのは、性質の主張では答えが決まらないもの——離散の約束（呼び名の対応等）・外部の権威との突き合わせ——だけである。

- **入力の範囲は本番の範囲で作る**（パターン8と同じ）。全世界の乱数では起きにくい場面は、その場面を作る範囲を別に与える。
- **期待値を実装と同じ規則で作らない**（testing-review.md「消すべきテストの型」の実装の規則の再実装）。比べる相手は、より遅いが
  素直な計算か、公開の仕様である。
- **見つかった入力は、実装の欠陥か自分の前提の誤りかを分けてから直す**（testing-rewrite.md「テストが落ちたら、まず自分の前提を
  疑う」）。前提の誤りで、実装に書かれていない事実（計算の分解能等）だったなら、実装のdocstringへ足してから
  テストの許容を直す。
- 例の数は既定（100）のまま回す。例ごとの壁時計の締め切りは`tests/conftest.py`が外している。
- **CIは見つけた失敗の例を残さない。** hypothesisは環境変数`CI`があると`ci`の設定（乱数を固定し、例の保存先を
  持たず、失敗の再現の印を出す）を既定で効かせ、`tests/conftest.py`は親を渡さずに設定を登録してそれを引き継ぐ
  （GitHub Actionsは`CI`を立てる）。CIで落ちた例は、出力の`@reproduce_failure`をテストへ一時的に付けて
  手元で再現し、残すなら`@example`にする。

## テストは、テストだけで成立させる

本番の正本（材料カタログ・軸定義）や生成物を読む代わりに、**性質だけを表す架空の名前**（`num_a`・`bool_a`・`cat_a`・`axis_a`）を使い、モジュール大域の
辞書ごと差し替える。「この材料が実在すること」がテストの関心なのかを毎回問う。

**ファイルの冒頭で責務を宣言する。** モジュールdocstringに「対象は何か」と
**「ここでは見ないもの・どのファイルが持つか」**を書く。書けないなら責務が定まっていない。「ここでは見ない」と
書いた先を触らない。

**テストごとに同じ偽の世界を建て直しているなら、実装が大域から読んでいることを疑う**（直す順はtesting.md「確かめる高さ」の可変の状態の箇条）。

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

`TestClient`の接続元`client_id`は常に`"testclient"`（`app/api/rate_limit.py: client_id`参照）。
キーは`f"{prefix}:{client_id(request)}"`で、prefixは各routerが`enforce_rate_limit`へ渡すものに合わせる。

**テストは回数0から始まる**（autouseの`monotonic_clock`がテストごとに1窓より長く進める）。
回数の記録（`rate_limiter`の内部）は消し込まない・差し替えない。窓の境界を確かめるテストは`monotonic_clock`を引数に取って進める
（`test_rate_limiter.py`）。

実例: test_region_routes.py, test_weather_route.py, test_basemap_routes.py,
test_routes_generate.py

## パターン2: PostGIS統合テスト（road_graph_session）→ ファイル単位でエンジン・イベントループを共有

`conftest.py: road_graph_session`/`conftest.py: road_graph_repository`はテストファイル（モジュール）単位で
1本のDB接続・イベントループを使い回す。

新しいテストファイルでこれらのフィクスチャを使う場合:

1. ファイル冒頭に `pytestmark = pytest.mark.asyncio(loop_scope="module")` を付ける。
2. ファイル内で自前の追加async fixtureを定義してroad_graph_session/road_graph_repositoryに
   依存させる場合は、その自前fixtureにも明示的に`loop_scope="module"`を付ける
   （`@pytest_asyncio.fixture(loop_scope="module")`）。
3. 素の`@pytest.fixture`でasync fixtureを書かない。`@pytest_asyncio.fixture`を明示的に使う。
4. ファイル単位で共有するのは接続とスキーマまでにする。**テストが書き換える行（生データ・派生の表）は、
   関数スコープのfixtureで各テストの前に作り直す。** 共有した行を書き換えて後片付けで戻す形にしない。

実例: test_material_values.py（road_graph_sessionを直接使う）, test_derive_topology.py（自前の
module fixtureを重ねる）

**xdist_group="postgis"（必須）**:
road_graph_session系フィクスチャを使うテスト（ファイルまたは個別テスト関数）には必ず
`pytest.mark.xdist_group(name="postgis")`と`pytest.mark.postgis`（`pytest.ini`の`markers`に登録済み）の両方を付け、
`pytestmark`が既にリストでなければ
`pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis]`
の形にする。

## パターン8: テストが用意する状態は、本番で起こりうるものに限る

DBの制約・取込の順序から**作れない状態**をテストで作らない。

- **派生行を作るテストは、親を先に入れる**。区間（`road_edges`）は生の道
  （`source_features`の`osm_way`）とノード（`road_nodes`、端点はFK）の派生。本番と同じ順
  （生データを入れてから派生バッチを流す）で作り、派生の表へ行を直接書き込まない
  （`test_derive_topology.py: topology_conn`が、生の道を取り込んでから
  `derive_topology.derive`を呼ぶ形）。
- **生データも取込の入口から入れる**。`source_features`・`source_runs`へ直接書かない。`tests/source_ingest.py: ingest_records`が
  アダプタだけを差し替えて`ingest_source`を通す。行を変えたいときは、変えた後の全行で取り込み直す。
- **値式が必ず値を返すものを「欠損」にしない**。真偽の材料は`COALESCE(条件, false)`で
  閉じるため、「材料が1つも無い区間」は作れない。その前提のテストは前提ごと消す
  （軸が算出できない状況を確かめたいなら、軸の集合を差し替えて表現する。
  土台は`tests/axis_system_fixture.py`）。
- 制約を足した結果としてテストが大量に落ちたら、**テストの前提が本番と食い違っていた証拠**
  として読む。
