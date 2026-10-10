---
paths:
  - "frontend/src/**/*.test.ts"
  - "frontend/src/**/*.test.tsx"
  - "frontend/src/testing/**"
  - "frontend/vitest.{setup.ts,config.mts}"
  - "backend/scripts/cross_language_expectations.py"
---

# frontendのテストの書き方

番号は CLAUDE.md「原則」の番号。

## 確かめる高さ（frontend）

- 入口と確かめる出力は、対象の種類ごとに次の表で決める。内部のstate・フックの呼ばれ方・子へ渡した関数の同一性は確かめない。（原則5）

| 対象 | 入力 | 確かめる出力 |
|---|---|---|
| 部品（`*.tsx`） | props・利用者の操作（`userEvent`） | 描いたもの（role・名前・表示文言・`aria-*`の状態）と、呼ばれたコールバックの引数 |
| フック（`use*.ts`） | 引数（`renderHook`の`rerender`で変える）・戻り値の関数を呼ぶこと | 戻り値と、backendへ送ったもの |
| ページ（`app/**/page.tsx`） | 部品と同じ | 部品と同じ。ある機能の変化が別の機能の振る舞いを変える受け渡しを見る（[page-composition.md](../../docs/modules/frontend/page-composition.md)） |
| 純関数（`lib/`等） | 引数 | 戻り値 |

- 画面の操作は、利用者の1つの流れ（開く→選ぶ→送る）を1本のテストにしてよく、途中で何度確かめてもよい。（原則5）
- **差し替えてよいのは次の境界だけ**にする。自前のフック・`lib/`の関数・定数は、表の境界（環境変数の読み取り口・ファイルを
  落とす関数等）を除いて、差し替えずに本物を通す。（原則5）

| 境界 | 差し替え方 |
|---|---|
| backendとの通信 | 網の層で差し替える（msw。足場は`frontend/src/testing/backendServer.ts`）。backendを呼ぶ口のモジュール（`services/*Api.ts`・`features/**/*Api.ts`）も、通信を包む自前のフック（`hooks/useAxisCatalog.ts: useAxisCatalog`等）も差し替えない。口それぞれは、網の層で確かめる自分のテストを持つ |
| 時計 | `vi.useFakeTimers()`で進める。待ち時間の定数や、待つフック（`hooks/useDebouncedValue.ts: useDebouncedValue`）を差し替えない |
| 環境変数 | 下の「パターン7」 |
| テスト環境に無いブラウザの機能 | WebGL（`maplibre-gl`は`frontend/src/testing/maplibre.ts`の代役へ差し替え、地図の部品は本物を描く）・レイアウトの実寸（`embla-carousel-*`）等 |
| ファイルを落とす | GPXの書き出し等、ブラウザにファイルを保存させる関数 |
| 子の部品 | 下の条件を満たすときだけ |

- テスト環境が持つもの（`localStorage`・`navigator`の値等）は、それを読むフックを差し替えず、環境に値を置く。`localStorage`が
  投げる場面は、`window`のゲッター（`vi.spyOn(window, "localStorage", "get")`）を差し替えて作り、`getItem`/`setItem`へスパイを
  張らない。（原則5）
- 子の部品は本物を描く。差し替えてよいのは、子の中身がテスト環境に無い境界（上の表の「テスト環境に無いブラウザの機能」）を要し、
  それを境界の側で差し替えられないときだけにする。そのとき親のテストで見るのは受け渡し（親の状態がどの値として子へ渡るか・
  子から上がった操作で親の何が変わるか）だけにし、差し替えた子の表示は確かめない。（原則3・5）
- 子の代役は、受け取ったpropsを記録して`children`を描くだけにし、子の振る舞いを真似ない。差し替えたものと、それで見えなく
  なるものは、ファイル冒頭の「ここで見ないもの」に書く。（原則3・8）

## パターン7: 環境変数に依存する挙動のテスト → 判断を純関数へ出し、テストは環境変数に触らない

- vitestでは`process.env`がテストファイルをまたいで共有されるので、テストが書き換える環境変数を、そのテストの対象以外の実装も
  読む形を作らない。`afterEach`で戻して済ませない。（原則3）
- 環境変数で分かれる判断は、環境変数を引数で受ける純関数（`lib/tileBaseUrl.ts: resolveTileBaseUrl`）へ出してそれを確かめ、
  環境変数を読むのは分岐を持たない薄い関数（`lib/tileBaseUrl.ts: tileBaseUrl`）だけにする。（原則3・8）
- その値を使う側のテスト（URLの組み立て等）は、`process.env`を立てず、読み取り口のモジュール（`lib/tileBaseUrl.ts: tileBaseUrl`・
  `lib/adminBasicAuth.ts: adminBasicAuthCredentials`等）を`vi.mock`して値を固定する。（原則3）
- 自分のテスト対象だけが読む環境変数（`app/api/version/route.ts: GIT_COMMIT`・`lib/adminBasicAuth.ts`の資格情報等）は、その対象の
  テストが`vi.stubEnv`で立てて公開の入口を呼ぶ。（原則5）

## 取り違えうる値は、入れ替えると落ちる実例で見る

- 座標のように「どの軸をどこへ渡すか」を取り違えうる値は、変換式を検算せず、既知の1点（例: 東京都心のz/x/y）を通して、
  入れ替えたら落ちる形で確かめる。（原則11）

## パターン11: backendと画面が同じ計算を持つ → backendが「入力→答え」の表を出す

- 同じ計算をbackend（Python）と画面（TypeScript）の両方が持つところは、期待値を手で書き写さず、backendが出す「入力→答え」の表
  （`backend/scripts/cross_language_expectations.py`）を、画面のテストが全行、画面の関数へ当てる。表を読むテストは対象の関数の隣に
  置く（例: `lib/cardinalLabel.test.ts`）。（原則3）
- 表の入力は、答えが分かれるところ（区分の境界ちょうどとその少し手前・負の値・一周を超える値・0・日付変更線のような折り返し）を
  選び、区分の数などbackendの宣言から決まるものは、入力もそこから導く。（原則11）
- 表は機械によらずバイト単位で同じにし、浮動小数の答えは、CPUで最下位の桁が変わりうるなら意味のある桁へ丸めて出す。浮動小数の
  許す差は表に持たせず、画面のテストの側で決める。（原則3）
- 式の定数（丸めの桁・ズームの列・入力の下限等）は表で確かめず、backendの定数を生成物（`export_openapi.py`）へ出して画面の式が
  それを読む（例: タイルから組む点数の丸めは`mapDisplay.valueScale.difficultyDecimals`）。一致を確かめるテストは書かない。（原則3・8）
