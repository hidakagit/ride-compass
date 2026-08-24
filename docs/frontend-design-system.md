# フロントエンド デザイン基盤（Tailwind CSS + Radix UI + components/ui/）

改善計画T299で新設。**現状の姿**を記す（decisions的な経緯はT299本文・改善計画参照）。

## 1. 目的・適用範囲

`frontend/src`はCSS Modules（27ファイル・約2,900行）で個別実装されており、カード状コンテナ・
チップ/トグル・入力欄で重複が目立っていた。Tailwind CSS（T252で併用導入済み）+ Radix UI
（Accordion/Popover/RadioGroup/Toggleは既存採用）を束ねる共通UIコンポーネント層
`frontend/src/components/ui/`を新設し、今後のUI開発の標準とする。

**適用範囲は新規UI・機能改修時の段階移行のみ**。既存CSS Modules資産の一括置換は行わない
（大規模な一括移行は保守リスクが高く、機能改修と無関係な差分が積み上がるため）。

## 2. 使い分け基準

- **新規UIコンポーネントは`components/ui/`のプリミティブ + Tailwindユーティリティクラスを優先する。**
- **既存CSS Modulesファイルは、その周辺で機能改修が発生したタイミングでのみ移行する。** 見た目を
  変えない目的だけでのリファクタリングは行わない（T299でも「本当に同一実装」と確認できた
  重複のみ移行し、一括置換はしていない）。
- Tailwindのクラスが各画面に無秩序に散らばらないよう、繰り返し使う見た目（ボタン・カード・
  ダイアログ等）は必ず`components/ui/`のコンポーネントへ集約する。個別ファイルで
  独自に`cva`バリアントを増やしたり、同じ見た目のdivへ直接Tailwindクラスを都度書いたり
  しない（後者は「レイアウトのみで色を持たない」単純なケース——`flex flex-col gap-*`等
  ——に限り許容する。T299のComparisonPanel/RouteSettingsPanel/MapLayersPanel移行を参照）。

## 3. Design Token

| 種別 | 扱い |
|---|---|
| spacing | `--space-1〜4`（0.25/0.5/0.75/1rem）はTailwind既定のスペーシングスケールと数値一致（T251調査）。`@theme`への追加登録は不要、`gap-2`等がそのまま既存トークンと揃う |
| radius | `--radius-sm/md/lg`（6px/10px/16px）を`globals.css`の`@theme`へ追加登録済み。`rounded-sm/md/lg`で使える |
| shadow | `--shadow-float`を`@theme`へ`--shadow-float`として追加登録済み。`shadow-float`で使える |
| font-size | `@theme`へは追加していない。`components/ui/`はTailwind既定の`text-*`スケールをそのまま使う（既存`--font-size-sm`(0.8rem)とはわずかにズレるが、両者は別ファイルに閉じており実害なし） |
| **color** | **`@theme`へ統合しない。** ダークモードが`globals.css`の`@media (prefers-color-scheme: dark)`内`:root`再定義に依存しており、`@theme`に入れると値が静的に固定されダークモード追従が壊れるため（T252の判断を踏襲）。`components/ui/`のコンポーネントも色は必ず`var(--color-*)`をTailwindの任意値記法（`bg-[var(--color-surface)]`等）で参照する。**Tailwind既定パレット（`bg-white`/`text-gray-900`等）は使用禁止。** |

`@theme`ブロックの値は`globals.css`の`:root`内`--radius-*`/`--shadow-float`定義と意図的に
重複させている（`:root`側はunlayeredで既存CSS Modulesが依存しており、動かすことによる
予期せぬCascade Layers影響を避けるため）。変更時は両方揃えて直すこと。

**既知の落とし穴**: `@theme`ブロック直前のコメント内に、コロン直後にroot要素セレクタ名を
続けて書くと、Lightning CSS（Tailwind v4のCSSエンジン）がコメント境界を誤認識しビルドエラーに
なる実機不具合をT299実装時に踏んだ（`globals.css`の該当コメント参照）。この付近のコメントを
編集する際は該当パターンを避けること。

## 4. `components/ui/`一覧

| コンポーネント | 概要 |
|---|---|
| `Button` | `variant`(primary/secondary/danger/ghost)・`size`(sm/md)。`type`未指定時は`"button"`固定（グローバル`button[type=submit]`リセットの誤爆防止） |
| `Input` | `type`をパススルー（text/number両対応）。`invalid`でaria-invalid＋赤枠 |
| `Card` | 単一のシンプルなラッパー。`bg-[var(--color-surface-2)] rounded-md p-2`（既存の`legendCard`/`admin.card`と同一実装に合わせた） |
| `Dialog` | Radix Dialogのラップ（Root/Trigger/Content）。`title`必須propsでアクセシブル名を型で強制 |
| `Checkbox` | Radix Checkboxのラップ |

いずれも`class-variance-authority`（variant管理）+ `clsx`/`tailwind-merge`（`frontend/src/lib/cn.ts`の
`cn()`ヘルパー）を使うshadcn/ui方式（npmパッケージ導入ではなくコピー&オウン）。

## 5. 意図的に作らない・統合しないもの

- **Select・Tabs**: 現状利用箇所ゼロのため見送り（YAGNI）。実需が生じたら追加する。
- **汎用Chip**: `components/Map/LayerChip.tsx`が既に良い設計のRadix Toggleラッパーのため、
  重複する汎用Chipは作らない。ただし`MapOverlayControls.tsx`のiconChip・`RouteList.tsx`の
  item選択ボタンとの間で選択状態トグルのロジックが3系統に分かれて重複している実態があり、
  将来的な統合候補として記録する（`MapOverlayControls.tsx`は563行の中心的な地図UIファイルで
  直近もT292で大きく触られたため、T299では意図的に対象外とした）。
- **FloatingPanel/BottomSheetとDialogの統合**: 前者2つはドラッグ移動（react-rnd）・高さドラッグ
  （自前pointerイベント）という専用の振る舞いを持ち、Dialogでは表現できないため統合しない。
  Dialogは今後の新規の単純なモーダル要求（ドラッグ不要な確認ダイアログ等）向けの土台。
- **colorトークンの`@theme`統合**: Tailwind v4の`@theme inline`機能でCSS変数参照のまま
  `@theme`へ取り込める可能性があるが、この開発環境ではダークモードの実機検証（ブラウザの
  compositing）が難しく、T299では検証せず見送った。将来の別タスク候補。

## 6. テストパターン

`recipeControls.test.tsx`（`FieldLabel`、Radix Popoverラッパー）を参照実装とする。vitest +
`@testing-library/react`で`render`/`screen`、`getByRole`/`aria-*`属性ベースのアサーションに
統一し、Radix内部のDOM構造には依存しない。`components/ui/*/*.test.tsx`も同じ方針。

## 7. 実機確認の方法

地図UI変更と同様、Claude Codeの Browser ペインは MapLibre 同様に `isStyleLoaded` 等が進まない
既知の制約があり CSS の実描画確認に使えない。Playwright headless chromium を直接使う
（`npx playwright`、`frontend/node_modules/playwright`が利用可能）。ライト/ダーク確認は
`chromium.newPage({ colorScheme: "light" | "dark" })`で行う。

## 8. T275（Tailwind採否）との関係

T275でTailwindの採否（(a)撤去/(b)新規のみ併用/(c)全面移行）を検討していたが、T299で
**(b)を採用して決着**した。(c)全面移行の是非は引き続き別途判断とする。
