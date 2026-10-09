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

# テスト方針（パターン: 足場と期待値）

テストが用意する足場・状態と、期待値の出どころの書き方。土台の決まりは[testing.md](testing.md)が持つ。節の名前とパターンの番号で指す先は、この文書か`testing*.md`のどれかにある（名前は重ならない）。

## パターン5: 外部クライアントのフェイクは共有モジュールから取る

`backend/tests/`直下の、`test_`で始まらないモジュール（`conftest.py`を除く）が、複数のテストで
同じ形になるフェイク・足場を持つ。何を持ち、どの場面で使うかは各モジュールの先頭のdocstringが書く。
新しいフェイクを書く前に、この直下を一覧してdocstringを読む。
**新しいテストで同じものを書き写さず、ここからimportする。**
複数のテストで要る足場を新しく置くときも、この直下に置き、用途を先頭のdocstringに書く。

**共有の足場とフェイク（この直下と、frontendの`frontend/src/testing/`）は、それ自身のテストを持つかを3問で決める。**
本物の口を真似て、ずれうる振る舞いを自分で持つフェイクは持つ。組み立ての足場は、
崩れても頼るテストが緑のまま通る約束だけを確かめる。値を並べるだけ・1行の委譲の足場は持たない（1問目）。約束が崩れると
頼るテストが赤になる足場も持たない（3問目）。フェイクは、同じ公開の口に対するテストを本物とフェイクの両方へ流して
ずれを止める（本物の側はHTTPならrespx、DBなら実DBで流し、テスト環境で作れない`maplibre-gl`は実ブラウザ（パターン4のE2E）で流す。
例: `frontend/src/testing/mapTrace/recordingMap.contract.ts`）。これは「消すべきテストの型」の「本番に生えたテスト専用の口の検査」
とは別物である。

**網・時計・Redisの代役は自前で書かず、定番の道具を使う**（どれも`requirements-dev.txt`）。

| 境界 | 道具 | 使い方 |
|---|---|---|
| HTTP（クライアントを受け取る実装） | respx | 経路（`respx.Router`）で応答を決め、`tests/fake_http.py: client_for`で本物の`httpx.AsyncClient`にして渡す。どのURLへも同じ応答で足りるなら`answering`。要求は`router.calls`で見る（見てよいのは状態を変える要求だけ。「確かめる高さ」の差し替えの箇条） |
| HTTP（実装が自分で`httpx.stream`等を呼ぶ） | respx | pytestのフィクスチャ`respx_mock`。実装の中で作られる`httpx.Client`を、1テストで何度も作らせない |
| 時計 | freezegun | フィクスチャ`clock`（`tests/conftest.py`）。`tick`・`move_to`で進める |
| Redis | fakeredis | フィクスチャ`fake_redis`（`tests/conftest.py`）。接続の失敗は`redis_server.connected = False` |

例外は窓・TTLを数える単調時計（`tests/conftest.py: MonotonicClock`。回数制限・外部I/Oの警告の抑制・
データの世代の読み直しが読む）で、これらのモジュールが読む時計だけを差し替える。

`admin_credentials`は、認証情報が設定されている前提に立つテストが引数で取る。ファイル内の
全テストが管理画面APIを叩く場合もautouseで配らない。

フィクスチャ同士に順序が要るなら、**先に動くべきものを引数に取って依存で書く**。宣言順に頼らない。
確かめるには`pytest <対象> --setup-plan`でセットアップ順を出す。

frontendは`frontend/src/testing/`配下が同じ役割を持ち、用途は各ファイルの先頭のコメントが書く
（例: `routeFixtures.ts: makeRouteCandidate()`は、`e2e/fixtures.ts`も含めてルート候補を組み立てる
すべての場所が使う）。

## パターン6: 絞り込んだ母集団をループするテストは、空でないことを確かめる

実データ・生成物・定数表から条件で絞った一覧をループして要素ごとに検査するときは、絞り込んだ一覧を名前へ束ね、
空でないことを主張してから検査する。

```python
picked = [m for m, s in SPECS.items() if isinstance(s, WayMaterialCoverageSpec)]
assert picked, "way材料のカバレッジ仕様が1件も無い"
row = await fetch_values(conn, edge_id)                # 組み立てたSQLを実行した結果
for material_id in picked:
    assert row[material_id] is not None
```

```ts
const expressionColors = COLOR_EXPRESSION.filter((i) => typeof i === "string" && i.startsWith("#"));
expect(expressionColors.length).toBeGreaterThan(0);
for (const color of expressionColors) { expect(legendColors.has(color)).toBe(true); }
```

空でないことの主張は**同じテストの中**に置く。

**要素ごとの検査は、ループより`parametrize`で書く。** ループで書くのは、上の例のように1回の実I/Oの結果を要素ごとに見るときである（基本原則1）。
宣言から導いた母集団を`parametrize`へ渡す（空になったら、`backend/pytest.ini`の`empty_parameter_set_mark`で集める時点で落ちる）。

絞り込みの書き方は問わない。ループの中の条件で要素を選ぶ形（`if`の片側にだけアサーションを置く・`continue`で飛ばす）と、
空なら真になる量化（`assert all(...)`・`assert not any(...)`・`expect(xs.every(...)).toBe(true)`）も同じに扱う。

落とす規則は`backend/tests/structure/test_vacuous_loops.py`と`frontend/src/structure/vacuousLoops.test.ts`が持つ。
**読めるのは上の例の形の主張だけ**で、別の形（`assert set(picked) == {...}`等）で確かめていても
違反として出る——そのときは上の形の主張を1行足す。

## パターン7: 環境変数に依存する挙動のテスト → 判断を純関数へ出し、テストは環境変数に触らない

frontendのvitestでは**`process.env`はテストファイルをまたいで共有される**。テストが書き換える環境変数を、そのテスト自身の
対象以外の実装も読んでいる形を避ける（`afterEach`で戻すことで済ませない）。`process.env`ごと差し替えない（`process.env = { ...ORIGINAL }`）。

**判断を、環境変数を引数で受ける純関数へ出す**。環境変数を読むのは分岐を持たない薄い関数だけに
し、テストはその純関数を呼ぶ（`lib/tileBaseUrl.ts: resolveTileBaseUrl`。「確かめる高さ」の (a)）。

```ts
export function tileBaseUrl(): string {
  return resolveTileBaseUrl(process.env.NEXT_PUBLIC_TILE_BASE_URL, origin());
}
export function resolveTileBaseUrl(configured: string | undefined, origin: string | null): string { ... }
```

その値を**使う側**のテスト（URLの組み立て等）は、読み取り口のモジュールをモックして固定する。

```ts
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "" }));
```

漏れは`vitest.setup.ts`が実行時に見る（テストファイルの終わりに`process.env`が開始時と違えば落ちる。`vi.stubEnv`のように
復元されるものは通る）。自分のテスト対象だけが読む環境変数
（`app/api/version/route.ts: RENDER_GIT_COMMIT`・`lib/adminBasicAuth.ts`の資格情報等）は対象外で、`vi.stubEnv`で立てて公開の入口を呼ぶ
（使う側のテストは読み取り口のモジュールをモックして、その値を読まない）。

## パターン8: テストが用意する状態は、本番で起こりうるものに限る

DBの制約・取込の順序から**作れない状態**をテストで作らない。

- **派生行を作るテストは、親を先に入れる**。区間（`road_edges`）は生の道
  （`source_features`の`osm_way`）とノード（`node_materials`、端点はFK）の派生。本番と同じ順
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

## パターン9: 期待値の出どころを選ぶ（書き写さない・素のテキストを引く・軸を取り違えない）

**同じ計算を2つの言語で持つなら、期待値を手で書き写さない。** 片方（正本側）の実行結果を
フィクスチャとして書き出し、もう片方をそれに突き合わせる。backendと画面の間の置き場と作り方は「パターン11」。

**素のテキストノードは、要素として引けない。** `<span>`と`<span>`の間へ直に書かれたテキストは、
`getByText`の完全一致ではなく正規表現で当てる。

**座標のように「どの軸をどこへ渡すか」を間違えうる値は、入れ替えると別物になる実例で見る。**
変換式を検算するテストではなく、既知の1点（例: 東京都心のz/x/y）を通して**入れ替えたら落ちる**形にする。

## パターン10: 期待値が実行環境（OS）で変わる入力を使わない

**OSによって解釈が変わる入力を使わない**（開発機はWindows、CI・本番はLinux）。パスは実行中の環境の区切りで組む:

```python
str(Path("venv") / "Scripts" / "uvicorn.exe")
```

確かめたいのが「拡張子つきでも読める」なら、その性質だけを入力に持たせ、OS固有の書き方を
持ち込まない。実装に両方の区切りを読む分岐を足してテストへ合わせることもしない。

## パターン11: backendと画面が同じ計算を持つ → backendが「入力→答え」の表を出す

同じ計算をbackend（Python）と画面（TypeScript）の両方が持つところは、backendが出す表を画面のテストが通して一致を確かめる。

- **入力はbackendに置き、答えはbackendの関数が出す**。入力の並びと、それを関数へ通して表にする関数を
  `backend/scripts/cross_language_expectations.py`に置き、同じファイルの`EXPECTATIONS`へ「組の名前 → 表を作る関数」を
  1行足す。`backend/scripts/export_openapi.py`が組ごとに`frontend/src/types/generated/<組>-expectations.json`へ
  書き出す（組の名前は何の計算か。例: `geo`）。表は組の中で計算ごとにキーを分けた行の並びにする。
- **入力は答えが分かれるところを選ぶ**: 区分の境界ちょうどとその少し手前・負の値・一周を超える値・0・
  日付変更線のような折り返し。区分の数などbackendの宣言から決まるものは、入力もそこから導く。
- **生成物は機械によらずバイト単位で同じにする**。浮動小数の答えは、
  CPUで最下位の桁が変わりうるなら、意味のある桁へ丸めて出す。
- **画面のテストは表の全行を画面の関数へ当てる**。表の置き場は対象の関数の隣のテスト（例: `lib/cardinalLabel.test.ts`）で、
  全行を回す前に表が空でないことを確かめる（パターン6）。浮動小数の許す差は表に持たせず、テストの側で決める。
- **backendの関数は、表とは別に手で書いたあるべき値のpytestで確かめる**。pytestで表を通さない。
- 表と画面の両方で同じ事実を確かめる手書きのテストは、表へ寄せて消す。
- **式の定数（丸めの桁・ズームの列・入力の下限等）は、表で確かめずに生成物から読む**。backendの定数を生成物（`export_openapi.py`）へ出し、画面の式は
  それを読む（例: タイルから組む点数の丸めは`mapDisplay.valueScale.difficultyDecimals`）。一致を確かめるテストは書かない。
  backendに源泉の無い画面だけの値は、画面の中の1つの定数に置いて使う所がそれを読む。
