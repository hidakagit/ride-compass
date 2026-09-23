# フロントエンド デザイン基盤（Tailwind CSS + Radix UI + components/ui/）

## 1. 目的・適用範囲

`frontend/src/components/ui/`は、Tailwind CSS（CSS Modulesと併用）と Radix UI を束ねる
共通UIコンポーネント層で、新しいUIを作るときの標準。採用済みのRadixのパッケージは
`frontend/package.json`の`@radix-ui/*`を見る。

**適用範囲は新規UI・機能改修時の段階移行のみ**。既存CSS Modules資産の一括置換は行わない
（大規模な一括移行は保守リスクが高く、機能改修と無関係な差分が積み上がるため）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| components/ui（部品） | `Button/Button.tsx`（`variant`・`size`。`type`未指定時は`"button"`に固定し、グローバルの`button[type=submit]`リセットを誤って継承しない）・`Input/Input.tsx`（`type`をパススルー、`invalid`でaria-invalid＋赤枠）・`Card/Card.tsx`（背景だけを持つカード状の箱。枠線は持たない）・`Dialog/Dialog.tsx`（Radix Dialogのラップ。`title`必須でアクセシブル名を型で強制）・`Checkbox/Checkbox.tsx`（Radix Checkboxのラップ） |
| components/ui（`composes`で取り込む共有スタイル） | `adminPanel.module.css`（管理画面パネルの外枠と一覧表のシェル）・`floatingPopover.module.css`（情報アイコンから開く浮きパネル）・`infoButton.module.css`（見出し脇の(i)トリガー。開いている間はアクセント色）・`roundIconButton.module.css`（地図に重ねる小さい丸アイコンボタン）・`mapCtrlButton.module.css`（MapLibre純正コントロールの続きに見える四角ボタン）・`stepperButton.module.css`（値を1段ずつ増減する枠線ボタン）・`statusDot.module.css`（データ取得状態の表現：点滅／中空／danger）・`unusedBadge.module.css`（使われていないことを示す小さなバッジ）・`axisLegend.module.css`（軸の寄与を示す帯グラフと凡例ドット） |
| lib | `cn.ts`（`clsx`で条件付きclassNameをまとめ、`tailwind-merge`で同じプロパティを指すクラスの後勝ちを解決する） |
| app | `globals.css`（デザイントークン・`@theme`登録・リセット・レスポンシブレイアウト・MapLibreのDOM上書き。下記8節） |

部品はいずれも`class-variance-authority`（variant管理）＋`cn()`を使うshadcn/ui方式
（npmパッケージ導入ではなくコピー&オウン）。

## 2. 使い分け基準

- **新しいUI機構（スライダー・タブ・ボトムシート等）は、自前実装より先に定番ライブラリ
  （Radix UI・vaul等）で賄えないかを検討する。** 既存パターンの単純な拡張（コンポーネントへの
  prop追加等）はこの原則の対象外。既存の`components/BottomSheet`だけは例外で、地図のピンチ
  ズームと衝突しないよう`touch-action`を実機で詰めた自前実装であり、暗幕なし・部分表示という
  独自要件を持つ——置き換えを検討するならこの挙動を壊さないかを先に確かめ、着手前に
  ユーザーへ相談する。
- **新規UIコンポーネントは`components/ui/`のプリミティブ + Tailwindユーティリティクラスを優先する。**
- **既存CSS Modulesファイルは、その周辺で機能改修が発生したタイミングでのみ移行する。** 見た目を
  変えない目的だけでのリファクタリングは行わない。移すのは「本当に同一実装」と確かめられた
  重複だけ。
- Tailwindのクラスが各画面に無秩序に散らばらないよう、繰り返し使う見た目（ボタン・カード・
  ダイアログ等）は必ず`components/ui/`のコンポーネントへ集約する。個別ファイルで
  独自に`cva`バリアントを増やしたり、同じ見た目のdivへ直接Tailwindクラスを都度書いたり
  しない（後者は「レイアウトのみで色を持たない」単純なケース——`flex flex-col gap-*`等
  ——に限り許容する）。

## 3. Design Token

| 種別 | 扱い |
|---|---|
| spacing | `--space-*`はTailwind既定のスペーシングスケール（0.25rem単位）と数値が一致する。`@theme`への追加登録は不要で、`gap-2`等がそのまま既存トークンと揃う |
| radius | `--radius-sm/md/lg`を`globals.css`の`@theme`へ登録済み。`rounded-sm/md/lg`で使える |
| shadow | `--shadow-float`を`@theme`へ登録済み。`shadow-float`で使える |
| font-size | `@theme`へは追加していない。`components/ui/`はTailwind既定の`text-*`スケールをそのまま使う（`--font-size-*`とはわずかにズレるが、両者は別ファイルに閉じており実害なし）。`*.module.css`側は素の`rem`ではなく`--font-size-*`トークンを使う |
| **color** | **`@theme`へ取り込んでいない。** `components/ui/`のコンポーネントも色は必ず`var(--color-*)`をTailwindの任意値記法（`bg-[var(--color-surface)]`等）で参照する。**Tailwind既定パレット（`bg-white`/`text-gray-900`等）は使用禁止。** 取り込むこと自体はダークモードの追従を壊さない——`@theme inline { --color-surface: var(--color-surface); }`の形ならユーティリティは`var(--color-surface)`参照のまま出力され、`@theme`の変数が出る`@layer theme`の`:root`より、`globals.css`のunlayeredな`:root`とダーク側の再定義が常に勝つ。壊れるのは、`@theme inline`へ色の値そのものを書いた場合（ユーティリティへ値が焼き込まれる）と、`globals.css`の`:root`に再定義の無い名前を`@theme`にだけ置いた場合。任意値記法のままでいる側の利点は綴り違いを止められること: `var(--color-*)`の綴り違いは`cssTokens.test.ts`が落とすが、短い名前（`bg-surfce`）の綴り違いはTailwindが警告なしにクラスを生成しないだけで何も止めない |

### 重なり順（z-index）

画面全体で重なり合う層は`globals.css`の`:root`にある`--z-*`トークンがすべてで、各
`*.module.css`は素の数値を持たない。Radix Portalで`document.body`直下へ出る要素同士は、
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
| `--z-top-popover` | 60 | 開いた時点で必ず見えるべき浮きパネル（`ui/floatingPopover`・レンズ一覧・走行条件） |

1つの部品の内側だけで重なる要素（読み込みオーバーレイ・sticky列見出し等）はこのスケールの
対象外で、素の小さい値のままでよい。

### 固定ダークな面の上の色

開発者向けFloatingPanel（`SystemStatusPanel`・`DebugConsole`）とログ本文
（`BackendLogsPanel`）はテーマに追従しない暗い面のため、重大度色は`--color-danger`等の
テーマトークンではなく`--color-log-error`/`--color-log-warning`/`--color-log-info`
（ライト/ダークで切り替えない固定値）を使う。テーマトークンは明るい面向けの濃さで、
暗い面では沈んで読めなくなる。

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
重複させている（`:root`側はunlayeredで既存CSS Modulesが依存しており、動かすことによる
予期せぬCascade Layers影響を避けるため）。変更時は両方揃えて直すこと。`@theme`直前の
コメントには、Lightning CSSのコメント解釈に関する書き方の制約がある（`globals.css`の
該当コメント参照）。

## 4. 共有スタイルの取り込み方

**別コンポーネントの`*.module.css`を直接importして借りない**。CSS Modulesは存在しない
クラス名に対して`undefined`を返すため、貸し手側の改名が無スタイルのまま本番へ出る
（tscもlintも止めない）。共有したい見た目は`components/ui/`へ出し、双方が`composes`で
取り込む（5-4節）。

## 5. 意図的に作らない・統合しないもの

- **Select**: 利用箇所が無いため`components/ui/`に作らない。実需が生じたら追加する。
- **Tabs**: `components/ui/`でラップせず、`@radix-ui/react-tabs`を各画面が直接使う。
- **汎用Chip**: `components/Map/LayerChip.tsx`（Radix Toggleラッパー）があるため、
  `components/ui/`に汎用Chipは作らない。
- **FloatingPanel/BottomSheetとDialogの統合**: 前者2つはドラッグ移動（react-rnd）・高さドラッグ
  （自前pointerイベント）という専用の振る舞いを持ち、Dialogでは表現できないため統合しない。
  Dialogは新規の単純なモーダル要求（ドラッグ不要な確認ダイアログ等）向けの土台。

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

## 5-4. CSS Modulesの`composes`が安全な理由

共有したいスタイルは`components/ui/`へ出して双方が`composes`する（4節と同じく、同じクラスを
直に共有しない）。**`composes`は取り込み側に新しいローカルクラスを発行したうえでベースの
規則を合成する**ため、取り込み側が足す状態セレクタ（`[aria-pressed="true"]`等）は自分の
生成後クラスにしか掛からず、元のクラスや他の取り込み側へ波及しない。同じクラスを直接
共有した場合と違い、意図しない汚染が起きないのはこの性質による。

## 5-5. ブラウザ・ライブラリの既定に踏まれる所

- **Reactの`onWheel`で`preventDefault`は効かない。** React 17以降、ホイールイベントは
  ルートへ`passive: true`で委譲されるため、合成イベントの中で呼んでもコンソール警告に
  なるだけで止まらない。止めたいときは`useEffect`でDOMへ直に
  `addEventListener(..., { passive: false })`で張る。

## 6. テストパターン

`components/Map/recipeControls.test.tsx`（`FieldLabel`、Radix Popoverラッパー）を参照実装と
する。vitest + `@testing-library/react`で`render`/`screen`、`getByRole`/`aria-*`属性ベースの
アサーションに統一し、Radix内部のDOM構造には依存しない。`components/ui/*/*.test.tsx`も同じ方針。

`Disclosure`（Radix Accordion）の本文は、閉じている間`hidden`で実際に隠れる。中身の挙動を
見るテストは、レンダー直後にその節を開いてからクエリする。`aria-expanded`でトリガーを集める
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
見た目が必要だから」という理由でのブランケットルールは避け、コンポーネント自身のCSS
Modulesファイルに持たせる。

### タップ領域（44px）は、主要な導線だけが自前で持つ

コンテナ配下の全`<button>`へ一律に`min-height`を掛けるようなブランケットルールは置かない。
一律適用は、既に自前の意図したサイズを持つ部品（`LayerChip`のピル・`components/ui/Checkbox`
等）を詳細度で潰す。

**「本当にメインの導線」だけが個別に44pxを持つ**（例: モバイル下部タブの
`page.module.css: .tabButton`のように、画面の切り替えそのものを担う操作）。補助的な
ボタン（一括操作リンク・情報アイコン・開発者向けボタン等）は44pxへ揃えず自然なサイズのまま
にする。**新しく「主要な導線」を追加する際は、globals.cssへブランケットルールを足すのでは
なく、そのコンポーネント自身のCSS Modules（または Tailwindの`min-h-11`等）へ
`@media (max-width: 640px)`スコープで明示すること**。

`globals.css`に置いてよいモバイル向けルールは、特定の要素カテゴリ全体に共通し、
コンポーネント個別の意図が入り込む余地の無いものだけ（例: `.app-bottom-sheet`スコープの
チェックボックス拡大・text/number inputの44px＋`font-size:16px`・labelの44px）。
とくにinputの`font-size:16px`はiOS Safariの自動ズーム防止というOSレベルの挙動抑止で、
例外を許すと同じ不具合が再発しうるため、グローバルであることに必然性がある。

### `components/ui/`コンポーネント自身の自己防衛

`components/ui/Checkbox`は`globals.css`側の個別パッチに頼らず、コンポーネント自身が
`p-0 min-h-0`をTailwindユーティリティで明示している（`globals.css`の`@layer base`にある
`button`の既定paddingはTailwindの`utilities`レイヤーより弱いため通常は
上書きできるが、「上書きできる」ことと「実際に上書きしている」ことは別で、対象の
コンポーネントが明示的に宣言していない限りベースレイヤーの値がそのまま素通しされる）。
`components/ui/`へ新しいプリミティブを追加する際も、ベースレイヤーの既定値
（`button`のpadding等）と衝突しうるプロパティは、コンポーネント自身が明示的に
Tailwindユーティリティで上書き宣言すること。
