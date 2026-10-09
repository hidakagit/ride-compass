---
paths:
  - "backend/tests/**"
  - "backend/pytest.ini"
  - "frontend/src/**/*.test.ts"
  - "frontend/src/**/*.test.tsx"
  - "frontend/src/testing/**"
  - "frontend/vitest.setup.ts"
  - "frontend/e2e/**"
  - "frontend/e2e-live/**"
  - "frontend/capture/**"
  - "frontend/playwright*.config.ts"
  - "frontend/src/structure/**"
  - "frontend/vitest.config.mts"
  - "scripts/break_tests.py"
  - "backend/scripts/audit_test_rewrite.py"
  - "frontend/scripts/audit-test-rewrite.mjs"
  - "tools/flow-gate/test/**"
---

# テスト方針（パターン: 実行環境）

実行環境（レート制限・PostGIS・frontendのテスト環境・E2E）ごとの書き方。土台の決まりは[testing.md](testing.md)が持つ。節の名前とパターンの番号で指す先は、この文書か`testing*.md`のどれかにある（名前は重ならない）。

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

## パターン3: フロントエンドのテスト環境 → DOM不要ならnode環境

DOM（render/renderHook/window/document等）を使わない純ロジックのテストファイルは、
ファイル先頭へ`// @vitest-environment node`docblockを付けてnode環境に倒す
（設定ファイルの`environmentMatchGlobs`は使わない）。
既定のDOM環境はhappy-domで、個別ファイルで`// @vitest-environment jsdom`を付ければjsdomで動く。

新規テストファイルがDOMに触れない場合、このdocblockの追加を検討する。判断に迷ったら、そのテストファイルが
`render`/`renderHook`/`screen`/`document`/`window`のいずれかを使っているか確認する
——**テストファイル自身だけでなく、importしている実装側の関数が内部で
`document.createElement`等を呼んでいないかも確認すること。**

## パターン4: フロントエンドのE2E（Playwright）→ 実機でしか出ないものだけを見る

### 何を対象にするか

E2Eは、**実ブラウザ・本番ビルドでしか出ず、かつ機械で判定できるもの**を確かめる場である。次の3つの観点を見る。

| 観点 | 例 | 何で判定するか |
|---|---|---|
| 1. 収まる・押せる | ヘッダーが幅からはみ出す、凡例の行がセルからはみ出す、下部のバーの下に潜り込んで押せない | `scrollWidth`/`clientWidth`・`boundingBox()`の実寸 |
| 2. ブラウザ・ランタイムの実挙動 | ブラウザ既定の動作（暗黙のフォーム送信・タッチ操作の割り当て）、実イベントが地図を通って届くか、MapLibreのWorker・描画・スタイル検証・`idle` | 実イベントを起こした結果・画素・コンソール |
| 3. カスケードの勝ち負け | `@layer`の外に置いたリセットがTailwindのユーティリティを潰す、モジュールCSSの詳細度が部品の既定サイズを踏む | `getComputedStyle`の計算後の値 |

**対象にしないもの**:

- **読みやすさ・色**（配色が凡例と合っているか、縁取りが見えるか）。人が見る
  （[frontend-design-system.md](../../docs/modules/frontend/frontend-design-system.md)「実機確認の方法」）。
- **DOMの状態・ロジックだけの主張**（押すと何が出るか・候補が何件並ぶか・`aria-pressed`が
  反転するか）。vitestで確かめる。

**合否の基準が、決まった規則として既にあるものだけを置く**（ページが横にスクロールしない・
地図の外でピンチしてもページが拡大しない等）。どの状態・どの見え方が正しいかを実機の画面を見て判断する必要があるものは、
「人が見る」に入る。

各テストは、冒頭のコメントで**どの観点を見ているか**を言えること。言えないテストは置かない。
ブラウザはChromiumだけにする。

### 共通フィクスチャに置くもの

`e2e/fixtures.ts`に置いてよいのは、**目的の画面まで進める導線**だけ——アプリが起動する
ためのAPIモックの既定応答と、`openMobileApp`・`openMobileSheet`・`generateRoutes`・
`seedStoredState`のような段取りのヘルパー。

**判定対象になる値は、各テストが自分で用意する**（幅を測るための長いラベル・段階の細かい
軸・描けたかを見る塗り色等）。共通側の応答を上書きするには、テストの中で同じURLへ
`page.route`を後から登録する（Playwrightは後から登録したルートを先に当てる）。

### 走査する画面の状態は、画面から辿る

観点1〜3は、要素を性質で集めるだけでなく、**当てる画面の状態も手で選ばない**。
`e2e/all-states.spec.ts`が、`e2e/states.ts`の辿る画面の状態へ`e2e/scans.ts`の走査を当てる。

**土台**は幅 × 段階で、人が決める:

- 幅: CSSの`--breakpoint-mobile`の両側に1つずつ置く（両側にあることは実行時に検算する）。
- 段階: ルートの生成前・生成後・区間を乗り換えた後。生成後へは生成を1回押して届く。乗り換えた後へは、目的地へ向かう
  2候補を生成し、合成を始めて地図の乗り換え先を1つ押して届く（段取りと応答は`e2e/states.ts: splice`）。
- 軸カタログ: 本番と同じく重みのある軸を複数持つ（`e2e/states.ts: installScanMocks`）。
- モード（デバッグモード等）は切り替えない。

**土台の上は画面から辿る**。`aria-expanded`を持つ部品と`role="tab"`のうち、
**最前面で押せるもの**（中心点のヒットテストが部品自身か子孫を返す）だけを押し、押せる限り奥まで辿る。
押せないものは押さない（違反にもしない）。どの状態へも1回だけ入る:
幅 × 段階ごとに1枚のページで辿り、開いたものは閉じて元へ戻す（同じタブ列のタブは戻らずに次へ渡り、最後に
元のタブへ戻す）。各段階のページは開き直したもので、前の段階と同じ段取り（生成・乗り換え）を踏んでから辿る。
祖先の状態にあった部品は押さない。

**同じ部品**は、要素から祖先までの**タグと（並べ替えた）クラスの並び**で見分ける。

**閉じたら元に戻る**ことは、それ自体を違反として見る。押す前と閉じたあとの**指紋**（開閉の値を部品の
見分けごとに集めたものと、ページの倍率）が一致しなければ落とす。同じタブ列のタブは、指紋にタブ列の中の位置を添える。
localStorageは指紋に入れない。

押したあとは、画面が**落ち着く**まで待ってから次を見る（`e2e/states.ts: settle`）。**Playwrightの
`networkidle`では済ませない**。

**検査は、判定が読むものから2種類に分けて当てる回数を変える**:

| 種類 | 判定が読むもの | 当て方 | 例 |
|---|---|---|---|
| 配置の検査 | 要素の座標・寸法、ページの幅 | 状態ごと | ページが横にスクロールしない、操作できる部品（ブラウザが計算したロールがWAI-ARIAのwidgetに当たるもの）が画面の横幅からはみ出さない（横スクロールする容器——縦にスクロールする容器も含む——の中の部品は、最も近いその容器が画面の横幅に収まるかを見る）、操作できる部品の押す点（中心点）がスクロールしない祖先（`overflow`が`hidden`・`clip`）に切り取られていない（その軸でスクロールする祖先より外側は見ない）、操作できる部品の箱が24px四方以上（WCAG 2.2 達成基準 2.5.8。例外はブラウザが入力欄の内側に描く部品だけ）、省略記号で切られた文字が無い（計算後の`text-overflow`が`ellipsis`で、中身が箱より広い要素）、中身が箱から横にはみ出して親の縁の外へ漏れていない（自分と親の計算後の`overflow-x`がどちらも`visible`で、中身が箱より広い要素のうちいちばん内側。親が切る・スクロールするなら見ない） |
| 部品の検査 | 要素と祖先の計算後のスタイル | 段階ごとに各部品1回 | 余白ユーティリティがリセットに潰されない、地図の外で始めたピンチがページを拡大しない（タッチを持つ文脈＝モバイル幅だけ） |

**新しいシート・パネルは、開閉する部品に`aria-expanded`（または`role="tab"`）を付けて
走査の母集団に入れる。** 窓（`Dialog/Dialog.tsx`）を開くボタンも、`aria-haspopup="dialog"`と開いている間`true`の
`aria-expanded`を付けて入れる。

### 書き方

1. **「見たい画面まで進める段取り」は`e2e/fixtures.ts`のヘルパーを使い、テストごとに
   書き直さない。** `openMobileApp`（モック登録・390x812・goto）→`openMobileSheet`（タブを押して開く。
   開くまで再試行する）→`generateRoutes`（距離指定→生成→完了待ち）の順に呼ぶ。保存される画面状態（レイヤーのON/OFF等）は
   クリックで作らず`seedStoredState`でlocalStorageへ与える。
2. **レイアウトの溢れは座標・幅を実測して押さえる。** role・名前で見つかることを「押せる」ことの確かめにしない。
   `scrollWidth`/`clientWidth`の比較と`boundingBox()`で確かめる（`e2e/mobile.spec.ts`の
   ヘッダー検査）。
3. **ロケータを当て推量で書かない。** 実際の名前は、落ちたテストの`test-results/<テスト名>/
   error-context.md`（その時点の画面構造）で確かめる。
4. **地図が描けたかは画素で見る。** 描けたことを見るのは`e2e/map-runtime.spec.ts`の1本だけに置き
   （GeoJSONの面を専用色で塗り、canvasの写しにその色の画素が出るかを数える）、他の
   テストへ同じ確認を足さない。
5. **タッチ操作は`Input.dispatchTouchEvent`（CDP）で指ごとに送る**（`isMobile`・`hasTouch`を付けた文脈で、
   ページの拡大は`visualViewport.scale`で読む）。既定動作の確認に`Input.synthesizePinchGesture`を使わない。
6. **足したテストは、わざと壊した入力で落ちることを見てから完了にする**（[fixing.md](fixing.md)
   「直し方」）。
