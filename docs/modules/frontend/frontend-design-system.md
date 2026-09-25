# フロントエンド デザイン基盤（Tailwind CSS + Radix UI + components/ui/）

## 1. 目的・適用範囲

`frontend/src/components/ui/`は、Radix UI（振る舞い）とTailwind CSS（見た目）を束ねる共通UI部品の層。
**画面の見た目はこの層だけが決める**——画面は部品を置き、並べ方（flex・grid・gap・位置・幅）だけを
Tailwindのユーティリティで書く。CSS Modulesは使わない（CSSのファイルは`globals.css`だけ）。
採用済みのRadixのパッケージは`frontend/package.json`の`@radix-ui/*`を見る。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| components/ui（部品） | `Button/Button.tsx`（押すと1回動く。`variant`が役割、`size`が大きさ。`type`未指定時は`"button"`）・`Toggle/Toggle.tsx`（押して切り替える。押下状態は呼び出し側が持つ）・`ToggleGroup/ToggleGroup.tsx`（並んだ選択肢から1つを選ぶ。選んでいるものは外れない）・`Tabs/Tabs.tsx`（タブの列とタブの見た目。Root・ContentはRadixのものを出す）・`Popover/Popover.tsx`（押すと開く浮きパネル。中身はdocument.body直下へ描く）・`Input/Input.tsx`（1行・複数行・選択の入力欄。3つとも同じ枠）・`NumberInput/NumberInput.tsx`（入力途中の文字を部品が持つ数値欄。打つたびに渡すか、欄を離れたとき・Enterで渡すかを選ぶ）・`Text/Text.tsx`（文字の役割ごとの大きさ・太さ・色）・`Table/Table.tsx`（一覧表）・`Card/Card.tsx`（ひとまとまりの面）・`Callout/Callout.tsx`（本文の中の注意の1かたまり）・`Badge/Badge.tsx`（名前の横に添える札）・`Dot/Dot.tsx`（状態の小さな丸）・`LogLine/LogLine.tsx`（ログの1行）・`Dialog/Dialog.tsx`（`title`必須でアクセシブル名を型で強制）・`Checkbox/Checkbox.tsx`・`AxisLegend/axisLegend.ts`（軸の帯グラフと軸チップの形。重み配分の設定とルート結果の内訳が共有する） |
| lib | `cn.ts`（`clsx`で条件付きclassNameをまとめ、`tailwind-merge`で同じプロパティを指すクラスの後勝ちを解決する）・`paletteCssVariables.ts`（backendが配る色のうちCSSから参照するものを、CSS変数として流す） |
| app | `globals.css`（デザイントークン・`@theme`登録・リセット・レスポンシブレイアウト・MapLibreのDOM上書き。下記8節） |

部品はいずれも`class-variance-authority`（variant管理）＋`cn()`を使うshadcn/ui方式
（npmパッケージ導入ではなくコピー&オウン）。

## 2. 使い分け基準

- **新しいUI機構（スライダー・タブ・ボトムシート等）は、自前実装より先に定番ライブラリ
  （Radix UI・Embla等）で賄えないかを検討する。** 既存の`components/BottomSheet`だけは例外で、地図のピンチ
  ズームと衝突しないよう`touch-action`を実機で詰めた自前実装であり、暗幕なし・部分表示という
  独自要件を持つ——置き換えを検討するならこの挙動を壊さないかを先に確かめ、着手前に
  ユーザーへ相談する。
- **見た目は部品が持つ。** 色・枠・角丸・影・文字の大きさと太さは`components/ui/`の部品（cvaのvariant）
  だけが持つ。画面は部品の役割（variant）を選び、並べ方だけを書く。1画面にしか無い形（地図のチップ・風向の
  ダイヤル等）はその画面でTailwindのクラスとして書いてよいが、同じ形が2か所目に出たら部品へ出す。
- **実績のある既成部品を既定にする。** 自前で持つのは、仕様が理由を持って要求している見た目・振る舞いだけ
  （例: 地図の上の操作は親の`pointer-events: none`を押せる部品だけが戻し、`touch-action: none`で地図の
  ピンチを守る＝`Button`の`float`。右上の列はMapLibre純正の続きに見せる＝`mapCtrl`）。理由の書かれて
  いない色味・角丸・余白は、既成部品の既定へ寄せる（見た目が変わることを許容する）。
- **backendが源泉の値・名前・色は読む。** 生成物（`types/generated/`）とAPIが配る値（地図の配色・凡例の色・
  語彙の名前と段階の色〔`vocabulary.ts`〕等）を画面で書き直さない。CSSから参照する必要がある色は
  `lib/paletteCssVariables.ts`がCSS変数として流す。
- 同じ見た目のdivへ直接Tailwindクラスを都度書かない（「レイアウトのみで色を持たない」単純なケース——
  `flex flex-col gap-*`等——は画面が書く）。
- **余白の短縮形と、同じ辺を指す個別の形を1つの要素に並べない。** 部品の余白を呼び出し側で変えるときは、
  `cn()`が後勝ちで置き換えられる同じ種類（`px`同士等）にする。`p-2`と`px-3`を並べると先の方が効かない
  クラスとして残る（E2Eの余白ユーティリティの検査が落とす）。部品の土台（cvaの第1引数）は余白を持たない。

## 3. Design Token

| 種別 | 扱い |
|---|---|
| spacing | `--space-*`はTailwind既定のスペーシングスケール（0.25rem単位）と数値が一致する。`@theme`への追加登録は不要で、`gap-2`等がそのまま既存トークンと揃う |
| radius | `--radius-sm/md/lg`を`globals.css`の`@theme`へ登録済み。`rounded-sm/md/lg`で使える |
| shadow | `--shadow-float`を`@theme`へ登録済み。`shadow-float`で使える |
| font-size | `@theme`へは追加していない。文字の大きさは`--font-size-xs/sm/md`の3段（モバイル幅で詰まる）をTailwindの任意値記法（`text-[length:var(--font-size-sm)]`）で参照し、役割ごとの組み合わせは`ui/Text`の`textVariants`が持つ。Tailwind既定の`text-*`スケールは使わない |
| **color** | **`@theme`へ取り込んでいない。** `components/ui/`のコンポーネントも色は必ず`var(--color-*)`をTailwindの任意値記法（`bg-[var(--color-surface)]`等）で参照する。**Tailwind既定パレット（`bg-white`/`text-gray-900`等）は使用禁止。** 取り込むこと自体はダークモードの追従を壊さない——`@theme inline { --color-surface: var(--color-surface); }`の形ならユーティリティは`var(--color-surface)`参照のまま出力され、`@theme`の変数が出る`@layer theme`の`:root`より、`globals.css`のunlayeredな`:root`とダーク側の再定義が常に勝つ。壊れるのは、`@theme inline`へ色の値そのものを書いた場合（ユーティリティへ値が焼き込まれる）と、`globals.css`の`:root`に再定義の無い名前を`@theme`にだけ置いた場合。任意値記法のままでいる側の利点は綴り違いを止められること: `var(--color-*)`の綴り違いは`cssTokens.test.ts`が落とすが、短い名前（`bg-surfce`）の綴り違いはTailwindが警告なしにクラスを生成しないだけで何も止めない |

### 重なり順（z-index）

画面全体で重なり合う層は`globals.css`の`:root`にある`--z-*`トークンがすべてで、各
部品・画面は素の数値を持たない（`z-[var(--z-map-control)]`の形で参照する）。Radix Portalで`document.body`直下へ出る要素同士は、
記述順ではなくこの値だけで前後が決まるため、**新しい浮動UIを足すときは既存のどの層より
上/下なのかをこの表で決める**。

| トークン | 値 | 層 |
|---|---|---|
| `--z-map-control` | 20 | 地図に重ねる操作系（チップ列・現在地ボタン・走行条件列） |
| `--z-map-popup` | 25 | MapLibreのポップアップ |
| `--z-map-detail` | 30 | 地図内の詳細パネル |
| `--z-bottom-sheet` | 45 | モバイルのBottomSheet・下部タブバー |
| `--z-header-popover` | 46 | ヘッダー由来のポップオーバー（メニュー・警報バッジ・今日の見通し） |
| `--z-floating-panel` | 50 | 開発者向けFloatingPanel・`ui/Dialog` |
| `--z-top-popover` | 60 | 開いた時点で必ず見えるべき浮きパネル（`ui/Popover`の既定・レンズ一覧・走行条件） |

1つの部品の内側だけで重なる要素（読み込みオーバーレイ・sticky列見出し等）はこのスケールの
対象外で、素の小さい値のままでよい。

**存在しないトークン名を書かない**。`var(--color-text)`のように規約どおりの見た目でも
定義が無ければ継承値へ落ち、SVGの`fill`だとダークモードで文字が読めなくなる。
`globals.css`にも同一ファイル内にも定義の無い`var(--x)`参照は書かない。
`frontend/src/structure/cssTokens.test.ts`が`frontend/src`配下を走査して落とす。
対象は`.css`だけでなく、Tailwindの任意値記法（`bg-[var(--x)]`）でトークンを参照する
`.ts`/`.tsx`も含む。フォールバック付き（`var(--x, 既定値)`）の参照も同じく対象にする。

**テーマトークンにフォールバック（`var(--x, 既定値)`）を付けないこと。** フォールバックは
未定義であることを隠すだけで、トークン名の綴り違いはそのまま残る（同じトークン名なのに
参照ごとに実効値が違う、という状態になる）。フォールバックを使ってよいのは、呼び出し側が
インラインstyleで実行時に注入する変数
（`--bottom-control-row-height`・`--load-bar-height-ratio`等、定義がCSSに無いのが正しいもの）
だけ——これらは`.ts`/`.tsx`側がトークン名を文字列リテラルで持つため、チェックは
それを定義とみなして通す。

`@theme`ブロックの値は`globals.css`の`:root`内`--radius-*`/`--shadow-float`定義と意図的に
重複させている（`:root`側はunlayeredで、部品の任意値記法〔`var(--radius-sm)`等〕が参照しているため）。変更時は両方揃えて直すこと。`@theme`直前の
コメントには、Lightning CSSのコメント解釈に関する書き方の制約がある（`globals.css`の
該当コメント参照）。

## 4. 部品の作り方

- 部品は`cva`で役割（variant）と大きさ（size）を宣言し、呼び出し側の`className`を`cn()`で後に足す
  （tailwind-mergeが同じプロパティの後勝ちを解決する）。
- **状態の見た目は属性で書く**（`data-[state=on]:`・`data-[state=open]:`・`aria-expanded:`等）。Radixが付ける
  属性で切り替えると、状態を見た目のために二重に持たない。親の状態で子を変えるときは`group`/`group-data-*`、
  祖先の属性で変えるときは`in-data-*`を使う。
- 狭い画面だけの違いは`max-mobile:`（`--breakpoint-mobile`から導かれる）。
- 部品の構造の目印が要るとき（テストが兄弟関係を見る等）は`data-slot`（shadcn/uiの慣習）を付ける。

## 5. 意図的に作らない・統合しないもの

- **FloatingPanel/BottomSheetとDialogの統合**: 前者2つはドラッグ移動（react-rnd）・高さドラッグ
  （自前pointerイベント）という専用の振る舞いを持ち、Dialogでは表現できないため統合しない。
  Dialogは新規の単純なモーダル要求（ドラッグ不要な確認ダイアログ等）向けの土台。

## 5-1. パネルの操作ボタンの形

- **パネル（ルート設定・ルート結果・編集面）の操作は、アイコンの横に短い名前を置く形にそろえる**
  （`Button`の`size="iconLabel"`）。アイコンだけでは何をするか読めず、文字だけでは
  見出し行に並べたときに主操作と見分けにくいため。縦に積まないのは、下部シートの高さを取らないため
  （地図のチップは縦に積むが、パネルの操作はシートの中で候補一覧と高さを取り合う）。✕（閉じる・選択の解除・消す）と、文字だけで読める小さな
  操作（「現在地に戻す」「再試行」等）はこの形にしない。
- **`aria-label`を付けるなら、見えている名前をそのまま含める**（例: 見える名前「合成」→`aria-label`「ルートを合成」）。
  音声で操作する人は見えている名前で押すため。
- **置き場は効く範囲で決める**: 候補すべてに効く操作は見出しの行、候補1本に効く操作はその候補のタブの中。

## 5-2. レイアウトが動かないための決まり

- **状態によって要否が変わるボタン・行は、出し入れせず常にマウントして`disabled`で示す。**
  条件付きレンダリングや`display:none`で消すと行の高さが変わり、隣接するボタンが上下にずれて、
  消える直前・直後のタップが別の要素へ当たる。見た目だけ消すなら`visibility`を使う。
- **固定幅のflex行に置くSVGには`flex-shrink:0`を明示する。** 既定の`flex-shrink:1`のままだと
  ChromiumがSVGのintrinsicサイズを解決できず幅0へ潰れ、**アイコンが黙って消える**。

## 5-3. 状態の伝え方

- **色だけで伝えている状態は、`aria-label`/`title`にも載せる。** 現在地マーカーの色で
  「GPSで取れた／既定値に倒れた」を示すような表現は、色を見分けられない利用者に届かない。
  見た目は色のままでよいので、同じ事実を必ず文字でも持たせる。
- **同じ行に並ぶ操作は、`aria-label`の文言を互いに変える。** 同名だとアクセシビリティ
  ツリー上でも`getByRole(name)`でも区別できず、テストは「どちらかに当たった」状態で通る。
- **UIの文言に開発用語を出さない。** 「デフォルト」「フォールバック」「キャッシュ」などは、
  初見の利用者が意味を取れる表現へ置き換える。

## 5-5. ブラウザ・ライブラリの既定に踏まれる所

- **Reactの`onWheel`で`preventDefault`は効かない。** React 17以降、ホイールイベントは
  ルートへ`passive: true`で委譲されるため、合成イベントの中で呼んでもコンソール警告に
  なるだけで止まらない。止めたいときは`useEffect`でDOMへ直に
  `addEventListener(..., { passive: false })`で張る。

## 6. テストパターン

`components/ui/FieldLabel/FieldLabel.test.tsx`（`FieldLabel`、Radix Popoverラッパー）を参照実装と
する。vitest + `@testing-library/react`で`render`/`screen`、`getByRole`/`aria-*`属性ベースの
アサーションに統一し、Radix内部のDOM構造には依存しない。`components/ui/*/*.test.tsx`も同じ方針。

**要素をクラス名で探さない**——見た目のクラスは部品の都合で変わる。役割・名前・`title`・`style`で探し、
構造の目印が要るときだけ`data-slot`を使う。部品が宣言したクラス文字列を書き写して突き合わせるテストは
書かない。テスト環境はTailwindの規則を作らないため、地図の上の部品を押せるかの
判定に要る`pointer-events-auto`の1規則だけを`vitest.setup.ts`が置く。

`Disclosure`（Radix Accordion）の本文は、閉じている間`hidden`で実際に隠れる。中身の挙動を
見るテストは、レンダー直後にその節を開いてからクエリする。開くときはトリガーへ`fireEvent.click`/`userEvent.click`を
当てる（開閉はReactの状態の更新なので、act()の外の生のDOMクリックでは次の描画が間に合わないことがある）。`aria-expanded`でトリガーを集める
ときは`:not([aria-haspopup])`で情報Popoverのトリガーを除く（同じ属性を持つ）。入れ子の
`Disclosure`は、開く操作を変化が無くなるまで繰り返す。

## 7. 実機確認の方法

地図UI変更と同様、Claude Codeの Browser ペインは MapLibre 同様に `isStyleLoaded` 等が進まない
既知の制約があり CSS の実描画確認に使えない。Playwright headless chromium を直接使う
（`frontend/node_modules/.bin/playwright`。`npx`は付けない）。ライト/ダーク確認は
`chromium.newPage({ colorScheme: "light" | "dark" })`で行う。

## 8. globals.cssのグローバルルールに関する方針

`globals.css`はデザイントークン・標準的なCSSリセット・レスポンシブレイアウト（インライン
styleでは`@media`が書けないための必然）・サードパーティ（MapLibre）のDOM上書きなど、
**「グローバルであること自体に意味がある」ルールに限定する**。「たまたま複数箇所で似た
見た目が必要だから」という理由でのブランケットルールは避け、部品か、その画面のクラスに持たせる。
ボタンの見た目の規則も置かない——全ボタン共通の見た目を置くと、部品の側で打ち消し忘れたプロパティが
そのまま素通しされる。キーボードのフォーカスの輪だけは、どの押せる要素にも同じものを出す。

### タップ領域（44px）は、主要な導線だけが自前で持つ

コンテナ配下の全`<button>`へ一律に`min-height`を掛けるようなブランケットルールは置かない。
一律適用は、既に自前の意図したサイズを持つ部品（`Toggle`のチップ・`components/ui/Checkbox`
等）を詳細度で潰す。

**「本当にメインの導線」だけが個別に44pxを持つ**（例: モバイル下部タブ〔`page.tsx`〕のように、
画面の切り替えそのものを担う操作）。補助的な
ボタン（一括操作リンク・情報アイコン・開発者向けボタン等）は44pxへ揃えず自然なサイズのまま
にする。**新しく「主要な導線」を追加する際は、globals.cssへブランケットルールを足すのでは
なく、そのコンポーネント自身のクラス（Tailwindの`min-h-11`等。狭い幅だけなら`max-mobile:`）で
明示すること**。

`globals.css`に置いてよいモバイル向けルールは、特定の要素カテゴリ全体に共通し、
コンポーネント個別の意図が入り込む余地の無いものだけ（例: `.app-bottom-sheet`スコープの
チェックボックス拡大・text/number inputの44px＋`font-size:16px`・labelの44px）。
とくにinputの`font-size:16px`はiOS Safariの自動ズーム防止というOSレベルの挙動抑止で、
例外を許すと同じ不具合が再発しうるため、グローバルであることに必然性がある。

### ページはピンチで拡大させない（2本指は地図の拡大に使う）

利用者が2本指を置くのはほぼ地図を拡大するためで、下部シート・ポップオーバー・ヘッダー等の上で
始まったピンチでもページ全体を拡大させない。これを`globals.css`の`@layer base`にある1つの規則
（全要素へ`touch-action: pan-x pan-y`）で持つ。1本指のパン（スクロール）は許し、`pinch-zoom`だけを
外す（ダブルタップの拡大も止まる）。

- **viewportの`user-scalable=no`・`maximum-scale`を使わない理由**: iOS Safari（iOS 10以降）は
  既定でこれらを無視する（MDN・WebKitブログ）。Android Chromeは従うが、効き方がブラウザで揃わない。
  `touch-action`はiOS Safari 13以降・Chromiumのどちらも`pinch-zoom`の有無を見る。
- **全要素へ掛ける理由**: `touch-action`は祖先との積で決まるが、WebKitはスクロール容器
  （`overflow: auto`/`scroll`）で祖先の値を打ち切り、容器の中を既定（auto）へ戻す
  （`Source/WebCore/style/StyleAdjuster.cpp`の`computeUsedTouchAction`）。Chromiumはスクロール
  容器でパンだけを戻し、ピンチの制限は受け継ぐ。`html`だけに掛けると、iOS Safariでは下部シート等の
  スクロール容器の中から始めたピンチがページを拡大する。
- **地図のピンチ**: 地図のcanvasとその容器の`touch-action`はMapLibre自身のスタイルシートが
  クラスで決め（`@layer base`より強い）、ピンチはMapLibreがタッチイベントで受け取って地図を拡大する。
- 部品が個別に持つ`touch-action`（チップの`none`・パネルの`pan-y`等）は、ドラッグを地図と
  スクロールのどちらへ渡すかを決めるためのもので、`pinch-zoom`を含まない限りこの規則を崩さない。
  `auto`・`manipulation`・`pinch-zoom`を部品へ書くと、その部品の上でページが拡大する。
- アクセシビリティの代償: ピンチでの拡大はできなくなる。WCAG 1.4.4（テキストのサイズ変更）は
  ブラウザ自身の拡大・文字サイズ設定のどれか1つで200%にできれば満たせるとしている。

E2E（ヘッドレスのChromium）が2つに分けて確かめる。地図のcanvas以外の部品から始めたピンチがページを
拡大しないことは、全状態の走査（`e2e/all-states.spec.ts`）がモバイル幅の画面の全状態で、部品ごとに2本指の
ピンチを送って見る（下部シート・ポップオーバー・ヘッダーの中も含む）。地図の上のピンチが地図を拡大することは
`e2e/map-runtime.spec.ts`の「タッチ端末」が見る。iOS Safariの挙動は公式の文書とWebKitのソースを根拠にしている。

### `components/ui/`コンポーネント自身の自己防衛

`components/ui/Checkbox`は`globals.css`側の個別パッチに頼らず、コンポーネント自身が
`p-0 min-h-0`をTailwindユーティリティで明示している（`globals.css`の`@layer base`にある
`button`の既定paddingはTailwindの`utilities`レイヤーより弱いため通常は
上書きできるが、「上書きできる」ことと「実際に上書きしている」ことは別で、対象の
コンポーネントが明示的に宣言していない限りベースレイヤーの値がそのまま素通しされる）。
`components/ui/`へ新しいプリミティブを追加する際も、ベースレイヤーの既定値
（`button`のpadding等）と衝突しうるプロパティは、コンポーネント自身が明示的に
Tailwindユーティリティで上書き宣言すること。
