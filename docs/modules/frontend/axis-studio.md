# 軸スタジオ管理画面（frontend）

## 責務

管理者向け（Basic認証保護下）の評価軸CRUD画面。一覧・作成・編集・複製・削除・
非公開化の状態管理を行い、[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)
のAPIをそのまま呼ぶ。同じ`/admin`の「材料」タブ（材料ごとの欠損割合の表示、
[評価・スコアリング（backend）](../backend/evaluation-scoring.md)「材料の欠損割合」節の
APIを呼ぶ）・「鮮度」タブ（派生データ鮮度台帳の表示、
[静的道路属性・タイル配信（backend）](../backend/static-road-attributes.md)
「派生データ鮮度台帳」節のAPIを呼ぶ）も本モジュールが持つ。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `components/AxisStudio/AxisStudio.tsx` | トップレベル。一覧取得・作成/更新/削除/複製/非公開化の状態管理 |
| `components/AxisStudio/AxisComposer.tsx` | 4ステップウィザードのフォーム本体 |
| `services/axisAdminApi.ts` | backend `axis_admin.py`への薄いHTTPラッパー（`listAxisDefinitions`・`createAxisDefinition`・`updateAxisDefinition`・`deleteAxisDefinition`・`unpublishAxisDefinition`） |
| `app/admin/api/axis-definitions/route.ts`・`[axisId]/route.ts`・`[axisId]/unpublish/route.ts` | `axisAdminApi.ts`が叩くNext.js route handler群。`proxyToBackendAdmin`でbackend `/api/admin/axis-definitions`（一覧取得・作成/PUT更新/DELETE削除/POST非公開化）へそのまま転送する |
| `components/AxisStudio/MaterialCoveragePanel.tsx` | 「材料」タブ本体。材料ごとの欠損割合を「欠損時の扱い」で2グループに分けた表（各グループ内は欠損割合降順）と集計対象外材料の理由一覧。集計は「集計する」ボタン押下時のみ |
| `services/materialCoverageApi.ts` | `MaterialCoveragePanel`が使うAPIクライアント（`app/admin/api/material-coverage/`経由、90秒タイムアウト） |
| `app/admin/api/material-coverage/route.ts` | `materialCoverageApi.ts`が叩くroute handler。`proxyToBackendAdmin`でbackend `GET /api/admin/material-catalog/coverage`へ転送する。全表走査を伴うため`timeoutMs`で既定（15秒）より長い転送タイムアウトを指定する |
| `components/AxisStudio/DerivedDataFreshnessPanel.tsx` | 「鮮度」タブ本体。edge_attribute_counts・way_attribute_counts・designation_attributesの鮮度不整合（テーブルごとに比較対象・最新取込run・反映済み最古run・NULL件数）とelevation_attributesの完成度（別枠）を表示。集計は「集計する」ボタン押下時のみ |
| `services/derivedDataFreshnessApi.ts` | `DerivedDataFreshnessPanel`が使うAPIクライアント（`app/admin/api/derived-data-freshness/`経由、90秒タイムアウト） |
| `app/admin/api/derived-data-freshness/route.ts` | `derivedDataFreshnessApi.ts`が叩くroute handler。`proxyToBackendAdmin`でbackend `GET /api/admin/derived-data/freshness`へ転送する |
| `hooks/useMaterialCatalog.ts` | `GET /api/material-catalog`取得。取得完了まで・失敗時は`lib/axisMaterialsCatalog.ts`の静的フォールバックを返す |
| `hooks/useMaterialValues.ts` | `GET /api/material-catalog/{material_id}/values`取得。categorical材料の候補選択セレクトに使う実データ値一覧 |
| `services/materialCatalogApi.ts` | 上記2フックが叩くbackend APIの薄いラッパー |
| `lib/axisMaterialsCatalog.ts` | 材料選択候補の静的フォールバック（`AXIS_MATERIAL_OPTIONS`）。`materialCatalogLabel`/`formatMaterialValue`は軸スタジオ外（[ルート設定・結果パネル](route-settings-and-results.md)のComparisonPanel、page.tsxの区間クリック詳細）が`material_values`のラベル・単位表記に使う共用ヘルパー |
| `components/Map/axisIconPalette.tsx` | 地図チップアイコンの固定パレット（`icon_id`→アイコンコンポーネント） |
| `components/Map/recipeControls.tsx`（`FieldLabel`のみ使用） | 情報アイコン付きラベルの共有UI部品（RouteSettingsPanel等とも共有） |

## AxisStudio.tsx（一覧・状態管理）

```
listAxisDefinitions() ──→ definitions（全軸）
                              │
              ┌───────────────┼────────────────┐
              ▼                                ▼
      下書きタブ（is_published=false）   公開済みタブ（is_published=true）
      編集・複製・削除ボタン             表示だけ編集・複製・非公開化ボタン
```

- 下書きタブが既定表示（新規作成した軸はまず下書きから始まるため）。
- 公開済みタブに削除ボタンは出さない（backendの`AxisPublishedImmutableError`と対応。
  削除は先に「非公開に戻す」という導線）。「表示だけ編集」ボタンは
  `AxisComposer`を制限モード（`editing.is_published`を見て自動判定、材料・計算式・
  重みのステップを一切出さず表示専用フィールドのみ編集できる1画面フォーム）で開く。
  材料・計算式・重みを変えたい場合は引き続き「複製して新規作成」に導線を残す。
- 削除前チェック: `axesReferencing(axisId, definitions)`が、削除しようとしている軸を
  他の軸が材料として参照していないか調べ、参照があれば確認ダイアログ（`window.confirm`）で
  警告する（一律拒否はしない、最終判断はユーザーに委ねる）。
- 一覧サマリ行（`renderRowMain`）は各軸が使う材料id/軸idの両方を`labelForMaterialOrAxis`で
  人間向けラベルへ解決する。まずこの軸一覧内に該当する軸id（内部軸階層、他axis_idを
  材料として参照するケース）が無いか探し、あればその`label`を優先する。無ければ
  `axisMaterialsCatalog.ts: materialLabel`（材料カタログの静的フォールバック一覧のみを
  引く）へフォールバックし、それにも無ければ生のidをそのまま出す。
- 最後の1軸は削除ボタンを無効化する。
- 編集・複製・新規作成はいずれもモーダル（`components/ui/Dialog`）で`AxisComposer`を開く
  （`<AxisComposer key={...}>`でkeyを切り替え、対象を変えるたびに再マウントする方式）。
- `/admin`ページ自体が既にBasic認証（`frontend/src/proxy.ts`）で保護されているため、
  この画面はユーザー名/パスワード入力欄を持たない。CRUD APIは同一オリジンのNext.js
  route handler（`app/admin/api/axis-definitions/`配下、`lib/adminApiProxy.ts:
  proxyToBackendAdmin`）経由で、ブラウザの認証キャッシュがそのまま転送される。backend宛の
  資格情報はサーバー側route handlerがサーバー環境変数から組み立てるため、ブラウザには
  一切露出しない。`proxyToBackendAdmin`は軸CRUD専用ではなく、「開発者」タブの
  バックエンドログ表示パネル（`app/admin/api/debug/logs/`）・「材料」タブの欠損割合
  （`app/admin/api/material-coverage/`）とも共有する汎用プロキシ（転送タイムアウトは
  既定15秒、`timeoutMs`オプションで呼び出し元route handlerが延長できる）。

## AxisComposer.tsx（4ステップウィザード）

| Step | 見出し |
|---|---|
| `basic` | 基本情報 |
| `shape_kind` | 点数のつけ方を選ぶ |
| `shape_params` | 点数の詳細を設定 |
| `display_publish` | 地図表示・公開 |

ステップ自体の追加・削除はコード変更を要する（動的ステップ化は目指さない設計判断）。
各ステップへ進む前に`validateStep`が該当ステップ内で完結する検証を行い（例: `basic`は
表示名必須、`shape_params`は折れ点のx昇順・categorical材料のスコア行1件以上、
`display_publish`はchip_labelの4文字制限・display_thresholds_overrideの昇順）、
最終保存直前にも全ステップを再検証する（戻って値を空にしたまま進んだ場合の安全網）。

**制限モード**: `editing`が公開済み軸（`editing.is_published`）の場合、
`restrictedDisplayOnly`が`true`になり通常の4ステップ構成を迂回する——`stepIndex`の
初期値を`display_publish`へ固定し、ステッパー・戻る/次へボタンを描画せず
`renderDisplayPublishStep()`（表示専用フィールドのみ）を単独の1画面フォームとして表示する。
このステップ内の`公開する`チェックボックスもこのモードでは非表示にする（is_published自体は
変更させない。切替は`AxisStudio.tsx`の「非公開に戻す」ボタンへ導線を一本化）。他ステップの
入力欄が無いぶん、`draft`の該当フィールド（label・shape・default_weight等）は
`draftFromExisting`が読み込んだ既存値のまま素通しで保存される。backend側は
`is_cosmetic_only_update`でこの差分が表示専用フィールドのみであることを再検証する
（[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)参照）。

### `shape_kind`ステップの3カード（フロントUI専用の分類）

| カード | 説明 | backend `AxisShape.kind`への対応 |
|---|---|---|
| なめらか評価 | 数値の大きさ・複数要素の有無で点数を変える | `breakpoint_linear` |
| ぴったり評価 | はい/いいえ、種類ごとに点数を決める | `categorical` |
| かけあわせ評価 | 既にある軸のスコアに重みを掛けて合計する | `breakpoint_linear`（他axis_idをmaterialとして参照、折れ点編集UIは出さない） |

**フロント側の`ShapeKind`型（`"breakpoint_linear" | "recipe_then_breakpoint_linear" |
"categorical"`）は3種のUIカードの選択肢であり、backendの`AxisShape`型（2プリミティブ:
`BreakpointLinearShape` | `CategoricalShape`）とは別の型**——`buildShape(draft, materialOptions)`が
送信直前に`draft.shapeKind`を`shape.kind`（常に`"breakpoint_linear"`または`"categorical"`の
2値）へ正規化する。既存軸を編集/複製する際は、逆に`draftFromExisting`が`shape.terms`の
構造（材料idか他axis_id参照か）からどのカードで作られたかを推定し直す（保存済みの
`kind`だけでは判別できないため）。

「かけあわせ評価」カード選択中は`materialOptions`ではなく`otherAxes`（編集中の軸自身を
除く全軸、`AxisStudio.tsx`が渡す）を材料候補にする——`MaterialTerm.material`が他axis_idを
指せる設計（backend「軸の階層」）に対応するGUI導線。

### 折れ点エディタ・スライダー・数値入力

- `BreakpointCurveEditor`: SVGでbreakpointsをドラッグ調整できる曲線プレビュー。同じ
  `draft.breakpoints` stateを数値入力行と共有し、常に同期する。
- `SliderNumberField`: 係数・スコアをスライダー（大まかな目安）＋数値入力（正確な値）の
  組み合わせで編集する。スライダーの範囲は材料ごとに大きく異なる値の目安にすぎず、
  範囲外の値は数値入力欄から直接指定できる。
- `NumberField`: このファイル内の数値入力（`SliderNumberField`の数値欄・既定重み・
  折れ点の入力値/スコア・地図の色分けしきい値）が共通で使う`<input type="number">`
  ラッパー。DOM値をコンポーネント自身のローカル文字列stateで保持し、有限数として
  パースできた時点でだけ`onChange`で親へ伝える（「-」や末尾の小数点のような未確定の
  中間状態を親の`value`へ反映しないことで、Reactが管理する制御値に上書きされず
  最後まで打ち切れる。素の`onChange={e => onChange(Number(e.target.value))}`パターンは
  `Number("-")===NaN`により入力途中の「-」が消え負数を打てない）。ローカル文字列は
  外部起因の`value`変化にだけ追従させる（useEffectではなくレンダー中に前回値との差分を
  見て補正するReact公式推奨パターンを使い、無駄な多重レンダーを避ける）。`onFocus`で
  既存の値を全選択する（タップ/クリック1回で上書きできるようにする）。

### categorical材料の値入力

選択した材料のdtypeで表示を切り替える:
- `dtype="boolean"`: 該当時(true)/非該当時(false)の2スコア入力。
- `dtype="categorical"`（例: highway/surface/smoothness）: 値ごとのスコア行。
  `useMaterialValues(materialId)`が`GET /api/material-catalog/{id}/values`から実データ値
  一覧を取得できた場合、値は読み取り専用の候補選択（自由入力を許さない——タイプミスが
  「静かに一致しない行」として残る落とし穴を防ぐため）になる。候補一覧が空の材料
  （bicycle_infra等、動的値一覧に未対応）だけ自由テキスト入力のまま。

## MaterialCoveragePanel.tsx（「材料」タブ）

`GET /admin/api/material-coverage`（backend `GET /api/admin/material-catalog/coverage`）の
レスポンス（`MaterialCoverageResponse`、生成型）をそのまま表にする。

- 「欠損時の扱い」（`missing_semantics`）で2つのグループに分けて表示する:
  「評価に影響する欠損」（`unknown`、欠損区間ではその材料を使う軸が評価対象外）と
  「タグ不在を確定値として評価する材料（参考）」（`definite`、欠損は「該当なし」を意味し
  評価に穴は開かない）。欠損割合の数字が同じでも意味が正反対のため同じ表へ並べない。
  各グループは`<section aria-label>`で、見出し＋1行の説明＋表。行は欠損割合の降順
  （`sortByMissingRatioDesc`）。`definite`の行は`data-missing-semantics`属性でバーの色を落とす。
- 表の列は材料（論理名 - 物理名）・母集団（Way/Edge）・欠損割合の3列。欠損割合セルは
  数値＋バーの下に「欠損 / 総数」を小さく重ねる（材料名が2行に折り返す高さを使い、
  スマホ幅でも横スクロールなしで収める）。欠損の判定根拠（`source`）は材料セルの`title`
  （ホバー表示）に置く。
- 母集団の定義・件数ベースであること・判定根拠の見方といった補足は、見出し脇の(i)
  （`Map/InfoPopover`＋`recipeControls.module.css`の`infoButton`/`infoTooltip`、
  `AxisComposer`の材料説明と同じ見た目）へ畳み、常時表示の説明文は各グループ1行だけにする。
- `excluded_reason`を持つ材料（集計対象外）は表に含めず、`<details>`の折りたたみ一覧へ
  理由つきで出す。
- 集計はDB全体の走査を伴うため、タブを開いたとき自動では実行せず「集計する」ボタン押下時
  のみ実行する（`DerivedDataFreshnessPanel`と同じ流儀）。
- 認証情報の入力欄は持たない（`AxisStudio.tsx`と同じく`/admin`のBasic認証セッションを
  route handler経由で再利用する）。

## DerivedDataFreshnessPanel.tsx（「鮮度」タブ）

`GET /admin/api/derived-data-freshness`（backend `GET /api/admin/derived-data/freshness`）の
レスポンス（`DerivedDataFreshnessResponse`、生成型）をそのまま表にする。
`MaterialCoveragePanel`（完成度、値がNULL/未取得か）とは別の切り口——行は存在するが、
参照している生データの世代が最新の取込より古いままではないか、という鮮度を見る。

- `generations`（edge_attribute_counts・way_attribute_counts・designation_attributes）は
  テーブルごとに小さな表を並べる（比較対象・最新取込run・反映済み最古run・NULL件数・
  鮮度バッジ）。`algorithm_version`はedge/wayのみ表内に行として追加（designationは
  対象外のため出さない）。テーブル名の隣に行数と鮮度不整合の有無（バッジ）を出す。
- `elevation`（`road_edges`との行数差分）は世代比較ではなく完成度のため、上記とは別枠で
  「完成度（鮮度ではない）」と明記して表示する。
- 集計はDB全体の走査を伴うため、`MaterialCoveragePanel`と同じく「集計する」ボタン押下時
  のみ実行する。認証情報の入力欄は持たない（`/admin`のBasic認証セッションをroute handler
  経由で再利用する）。

## 材料が0件のときの防御

`useMaterialCatalog()`は取得成功かつ0件のとき、静的フォールバックへは留まらず空配列を
そのまま返す仕様（後述）。この場合`AxisComposer`はウィザード自体を表示せず、「材料
カタログを取得できませんでした（0件の応答）」というエラー画面＋「閉じる」ボタンのみを
出す（`emptyDraft`が`materialOptions[0]`への無条件アクセスでクラッシュするのを防ぐガード。
フック呼び出し自体はこのガードより前で完了させ、Rules of Hooksには反しない）。

## 材料説明ポップオーバー

`InfoPopoverButton`/`MaterialInfoButton`（`AxisComposer.tsx`内で定義、Radix Popover使用）が、
材料選択欄の隣に(ⓘ)アイコンを置き、backend `material_catalog.py: MaterialSpec.description`を
ポップオーバー表示する。ポップオーバーのCSS自体は`recipeControls.module.css`
（`FieldLabel`用に定義済みのもの）を流用し、二重定義しない。

## useMaterialCatalog.ts / useMaterialValues.ts（材料カタログhook）

| フック | 取得先 | フォールバック | 取得成功かつ0件のとき |
|---|---|---|---|
| `useMaterialCatalog()` | `GET /api/material-catalog` | `AXIS_MATERIAL_OPTIONS`（静的） | フォールバックへは留まらず**空配列をそのまま返す**（「未完了/失敗」と「成功したが0件」を区別する） |
| `useMaterialValues(materialId)` | `GET /api/material-catalog/{id}/values` | 持たない（実データ値一覧はコード側で妥当な代替を用意できないため） | 空配列（＝呼び出し側は自由テキスト入力へフォールバック） |

**暗黙の前提**: `useMaterialValues`はpropが変わった直後の1レンダー中、前の材料の値一覧を
一瞬でも引きずらないよう、`useEffect`ではなくレンダー中の同期比較（`state.materialId ===
materialId ? state.values : []`）でリセットする——Reactの「propが変わったらstateをリセット
する」推奨パターンであり、`react-hooks/set-state-in-effect`のリント違反を避けるための
実装上の選択。

## axisIconPalette.tsx（地図チップアイコン）

`icon_id`（`AxisDefinition.icon_id`、軸自身のデータ）→アイコンコンポーネントのフラットな
辞書（`AXIS_ICON_PALETTE`、12種）。未知/未設定の`icon_id`は`AxisRampIcon`（汎用フォールバック）
に倒れるため、パレットに無い値でも動作は壊れない。新しいアイコン形状の追加はこのファイルへの
1件追加＋コード変更を要する（GUIからの任意SVG登録は、スタイル一貫性・XSSサニタイズの
コストが高いため見送り済みの設計判断）。

## AxisComposer→backend送信ペイロードの注意点

- `axis_id`はユーザー入力欄を持たない。新規作成/複製時は`generateAxisId()`が
  `crypto.randomUUID()`（利用不可な非セキュアコンテキストでは`Math.random()`ベースの
  フォールバック）で自動採番する。編集時は既存の`axis_id`をそのまま使う。
- このフォームに編集欄を持たないフィールド（`priority_overrides`・`time_scope`・
  `dedicated_way_value_layer`・
  `dynamic_way_value_needs_time`・`dynamic_way_value_needs_bearing`）も、既存軸の値を
  draftへ素通しして保存時に再送する（未送信だとサーバー側の既定値で上書きされ、既存軸の
  値が失われるため）。`display_thresholds_override`/`display_band_labels_override`は
  専用の編集UI（`display_publish`ステップの数値配列/文字列配列エディタ）を持つため、
  このリストには含まない。`display_band_labels_override`の編集欄は
  `display_thresholds_override`が有効（null以外）の間だけ現れ、段階数
  （`displayThresholdsOverride.length+1`）と要素数を常に一致させる——しきい値を
  追加/削除するとラベルの入力欄も連動して増減し（`addThresholdOverrideValue`/
  `removeThresholdOverrideValue`参照）、しきい値の上書きを解除する（自動計算に戻す）と
  ラベルの上書きも一緒にnullへ解除する（backend側のバリデーション「ラベルはしきい値の
  上書きが設定済みでなければならない」との不整合を防ぐ）。
- 軸スタジオが作る軸の`category`は常に`"推定"`固定（観測/動的は材料側の性質であり、
  材料を組み合わせて判定式を作る軸スタジオの仕組みからは生み出せないため）。

## backend側との対応

frontendのこの画面は、backendの[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)が
定義する`AxisDefinitionPayload`のバリデーション規則（chip_label 4文字制限・
display_thresholds_override昇順・shape.breakpoints x昇順・材料/軸参照の既知性）の一部を
`AxisComposer.tsx: validateStep`でも先回りしてチェックする（保存時のエラーで初めて気づく
手戻りを避けるため）。ただし最終防衛はbackend側であり、frontendの検証はUX上の先回りに
すぎない。
