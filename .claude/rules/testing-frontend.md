---
paths:
  - "frontend/src/**/*.test.ts"
  - "frontend/src/**/*.test.tsx"
  - "frontend/src/testing/**"
  - "frontend/vitest.{setup.ts,config.mts}"
  - "backend/scripts/cross_language_expectations.py"
---

# frontendのテストの書き方

## 確かめる高さ（frontend）

**入口**は、対象の種類で決まる。内部のstate・フックの呼ばれ方・子へ渡した関数の同一性は見ない。

| 対象 | 入力 | 確かめる出力 |
|---|---|---|
| 部品（`*.tsx`） | props・利用者の操作（`userEvent`） | 描いたもの（role・名前・表示文言・`aria-*`の状態）と、呼ばれたコールバックの引数 |
| フック（`use*.ts`） | 引数（`renderHook`の`rerender`で変える）・戻り値の関数を呼ぶこと | 戻り値と、backendへ送ったもの（状態を変える要求だけ。読むだけの要求は応答を与えるだけで、送ったかを見ない） |
| ページ（`app/**/page.tsx`） | 部品と同じ | 部品と同じ。ある機能の変化が別の機能の振る舞いを変える受け渡しを見る（[page-composition.md](../../docs/modules/frontend/page-composition.md)） |
| 純関数（`lib/`等） | 引数 | 戻り値 |

**画面の操作は、利用者の1つの流れを1本のテストにしてよい**（開く→選ぶ→送る、のような流れ。途中で何度
確かめてもよい）。

**差し替えてよいのは次の境界だけ。** 自前のフック・`lib/`の関数・定数は、表の境界（環境変数の読み取り口・ファイルを落とす関数等）を除いて、差し替えずに本物を通す。

| 境界 | 差し替え方 |
|---|---|
| backendとの通信 | 網の層で差し替える（msw）。backendを呼ぶ口のモジュール（`services/*Api.ts`・`features/**/*Api.ts`）も、通信を包む自前のフック（`hooks/useAxisCatalog.ts: useAxisCatalog`等）も差し替えず、本物を通す（足場は`frontend/src/testing/backendServer.ts`）。口それぞれは、網の層で確かめる自分のテストを持つ |
| 時計 | `vi.useFakeTimers()`で進める。待ち時間の定数や、待つフック（`hooks/useDebouncedValue.ts: useDebouncedValue`）を差し替えない |
| 環境変数 | 「パターン7」 |
| テスト環境に無いブラウザの機能 | WebGL（`maplibre-gl`）・レイアウトの実寸（`embla-carousel-*`）等。`maplibre-gl`は`frontend/src/testing/maplibre.ts`の代役へ差し替え、地図の部品は本物を描く。テスト環境が持つもの（`localStorage`・`navigator`の値等。環境変数は上の行）は、それを読むフックを差し替えず、環境に値を置く。`localStorage`が投げる場面を作るときは`window`のゲッター（`vi.spyOn(window, "localStorage", "get")`）を差し替え、`getItem`/`setItem`へスパイを張らない |
| ファイルを落とす | GPXの書き出し等、ブラウザにファイルを保存させる関数 |
| 子の部品 | 下の条件を満たすときだけ |

**子の部品は、既定では本物を描く。** 差し替えてよいのは、子の中身がテスト環境に無い境界（上の表の
「テスト環境に無いブラウザの機能」）を要し、それを境界の側で差し替えられないときだけ。差し替えて親のテストで見るのは
受け渡し（親の状態がどの値として子へ渡るか、子から上がった操作で親の何が変わるか）だけで、差し替えた子の表示は確かめない（子のテストが持つ）。

代役は受け取ったpropsを記録し、`children`を描くだけにする。子の振る舞いを真似ない。差し替えたものと、それで見えなくなるものは、ファイル冒頭の
「ここで見ないもの」に書く。

## パターン7: 環境変数に依存する挙動のテスト → 判断を純関数へ出し、テストは環境変数に触らない

frontendのvitestでは**`process.env`はテストファイルをまたいで共有される**。テストが書き換える環境変数を、そのテスト自身の
対象以外の実装も読んでいる形を避ける（`afterEach`で戻すことで済ませない）。

**判断を、環境変数を引数で受ける純関数へ出す**。環境変数を読むのは分岐を持たない薄い関数だけに
し、テストはその純関数を呼ぶ（`lib/tileBaseUrl.ts: resolveTileBaseUrl`。testing.md「確かめる高さ」の (a)）。

```ts
export function tileBaseUrl(): string {
  return resolveTileBaseUrl(process.env.NEXT_PUBLIC_TILE_BASE_URL, origin());
}
export function resolveTileBaseUrl(configured: string | undefined, origin: string | null): string { ... }
```

その値を**使う側**のテスト（URLの組み立て等）は、`process.env`を立てず、読み取り口のモジュール（`lib/tileBaseUrl.ts: tileBaseUrl`・
`lib/adminBasicAuth.ts: adminBasicAuthCredentials`等）を`vi.mock`して値を固定する。

```ts
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "" }));
```

自分のテスト対象だけが読む環境変数
（`app/api/version/route.ts: GIT_COMMIT`・`lib/adminBasicAuth.ts`の資格情報等）は、その対象のテストが`vi.stubEnv`で立てて公開の入口を呼ぶ。

## パターン9: 期待値の出どころを選ぶ（書き写さない・素のテキストを引く・軸を取り違えない）

**同じ計算を2つの言語で持つなら、期待値を手で書き写さない。** 片方（正本側）の実行結果を
フィクスチャとして書き出し、もう片方をそれに突き合わせる。backendと画面の間の置き場と作り方は「パターン11」。

**素のテキストノードは、要素として引けない。** `<span>`と`<span>`の間へ直に書かれたテキストは、
`getByText`の完全一致ではなく正規表現で当てる。

**座標のように「どの軸をどこへ渡すか」を間違えうる値は、入れ替えると別物になる実例で見る。**
変換式を検算するテストではなく、既知の1点（例: 東京都心のz/x/y）を通して**入れ替えたら落ちる**形にする。

## パターン11: backendと画面が同じ計算を持つ → backendが「入力→答え」の表を出す

同じ計算をbackend（Python）と画面（TypeScript）の両方が持つところは、backendが出す表を画面のテストが通して一致を確かめる
（表の置き場と出し方は`backend/scripts/cross_language_expectations.py`の先頭）。

- **入力は答えが分かれるところを選ぶ**: 区分の境界ちょうどとその少し手前・負の値・一周を超える値・0・
  日付変更線のような折り返し。区分の数などbackendの宣言から決まるものは、入力もそこから導く。
- **生成物は機械によらずバイト単位で同じにする**。浮動小数の答えは、
  CPUで最下位の桁が変わりうるなら、意味のある桁へ丸めて出す。
- **画面のテストは表の全行を画面の関数へ当てる**。表の置き場は対象の関数の隣のテスト（例: `lib/cardinalLabel.test.ts`）で、
  全行を回す前に表が空でないことを確かめる（testing-structure.md パターン6）。浮動小数の許す差は表に持たせず、テストの側で決める。
- **式の定数（丸めの桁・ズームの列・入力の下限等）は、表で確かめずに生成物から読む**。backendの定数を生成物（`export_openapi.py`）へ出し、画面の式は
  それを読む（例: タイルから組む点数の丸めは`mapDisplay.valueScale.difficultyDecimals`）。一致を確かめるテストは書かない。
