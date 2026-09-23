# 軸スタジオ管理画面（frontend）

## 責務

管理者向け（Basic認証保護下）の評価軸CRUD画面。一覧・作成・編集・複製・削除・
非公開化の状態管理を行い、[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)
のAPIをそのまま呼ぶ。同じ`/admin`の「材料」タブ（材料ごとの欠損割合の表示、
[評価・スコアリング（backend）](../backend/evaluation-scoring.md)「材料の欠損割合」節の
APIを呼ぶ）・「データ保守」タブ（派生データ鮮度台帳の表示、
[静的道路属性・タイル配信（backend）](../backend/static-road-attributes.md)
「派生データ鮮度台帳」節のAPIを呼ぶ）・「較正値」タブ（走ってみて決める値の編集、
[ルーティングエンジン（backend）](../backend/routing-engine.md)「較正値」節のAPIを呼ぶ）も
本モジュールが持つ。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `components/AxisStudio/AxisStudio.tsx` | トップレベル。一覧取得・作成/更新/削除/複製/非公開化の状態管理 |
| `components/AxisStudio/AxisComposer.tsx` | 1画面フォームの本体。draftの状態・保存前の検証・保存と、節の組み立てだけを持つ |
| `components/AxisStudio/AxisScoringSection.tsx` | 「点数の決め方」の節。材料の選択と、その材料の型に応じた点数入力（0点/100点・効き方、はい/いいえ、値ごと、他軸の係数）。折れ点の直接編集は畳んだ詳細設定の中 |
| `components/AxisStudio/AxisMapDisplaySection.tsx` | 「地図表示・公開」の節。アイコン・チップ略称・パネル補足・色分けしきい値のまとめ入力と段階プレビュー・公開チェック |
| `components/AxisStudio/AxisFormFields.tsx` | 上記2節とAxisComposerが共有する入力部品（`InfoPopoverButton`・`MaterialInfoButton`・`SectionLabel`・`NumberField`・`SliderNumberField`） |
| `components/AxisStudio/axisDraft.ts` | Draft（フォームの内部状態）とbackendのpayloadの相互変換。`buildShape`・`draftFromExisting`・`pickPassthroughFields`・`PASSTHROUGH_PAYLOAD_KEYS`。変更理由はbackendのpayloadスキーマで、フォームUIの増減とは独立している |
| `components/AxisStudio/BreakpointCurveEditor.tsx` | 折れ点をドラッグ・矢印キーで調整できるSVGの曲線エディタ。背景へ実データの分布を重ねる |
| `components/AxisStudio/curveDistributionOverlay.ts` | 曲線エディタの背景へ分布を重ねるための純粋関数（DOM非依存。階級のクリップ・按分、分位線、表示範囲外の割合） |
| `components/AxisStudio/scoreDistribution.ts` | 生値の分布へ折れ点を当てはめ、得点帯ごとの延長割合と警告を求める純粋関数（DOM非依存、`DistributionPreview.tsx`が使う） |
| `components/AxisStudio/DistributionPreview.tsx` | 折れ点の下に「この折れ点での得点分布」を出すパネル。満点への張り付き・0点への偏りを警告する |
| `components/AxisStudio/DistributionPreview.module.css` | 上記2コンポーネント（`MaterialRangeHint`と共有）のスタイル |
| `components/AxisStudio/MaterialRangeHint.tsx` | 材料選択行の下に、その材料が実データで取る値の分位（p50/p75/p90）を出す1行表示 |
| `services/axisPreviewApi.ts` | 分布プレビューと、しきい値が地図で効くかの問い合わせのAPIクライアント（`app/admin/api/axis-definitions/preview-distribution/`・`preview-display-thresholds/`・`app/admin/api/material-distribution/[materialId]/`経由） |
| `app/admin/api/axis-definitions/preview-display-thresholds/route.ts` | `proxyToBackendAdmin`でbackend `POST /api/admin/axis-definitions/preview-display-thresholds`へ転送する |
| `hooks/useThresholdsDroppedOnMap.ts` | 下書きのしきい値のうち地図では段にならないものを取得する（下書きが落ち着いてから問い合わせる。失敗時は空） |
| `app/admin/api/axis-definitions/preview-distribution/route.ts` | `proxyToBackendAdmin`でbackend `POST /api/admin/axis-definitions/preview-distribution`へ転送する。初回はWayの抽選を伴うため転送タイムアウトを長く取る |
| `app/admin/api/material-distribution/[materialId]/route.ts` | 同じくbackend `GET /api/admin/material-catalog/{material_id}/distribution`へ転送する |
| `hooks/useAxisValueDistribution.ts` | 編集中のshapeの生値分布を取得。取得キーに折れ点を含めないため、折れ点のドラッグ中は通信しない |
| `hooks/useMaterialDistribution.ts` | 材料1件の値の分布を取得。同じ材料を複数行が選んでも取得は1回で済むようモジュール内で結果を共有する |
| `components/AxisStudio/breakpointTools.ts` | 折れ点の自動生成・区分線形補間・追加位置決定・ドラッグスナップ刻み幅算出（DOM非依存の純粋関数、`AxisComposer.tsx`が使う） |
| `services/axisAdminApi.ts` | backend `axis_admin.py`への薄いHTTPラッパー（`listAxisDefinitions`・`createAxisDefinition`・`updateAxisDefinition`・`deleteAxisDefinition`・`unpublishAxisDefinition`） |
| `app/admin/api/axis-definitions/route.ts`・`[axisId]/route.ts`・`[axisId]/unpublish/route.ts` | `axisAdminApi.ts`が叩くNext.js route handler群。`proxyToBackendAdmin`でbackend `/api/admin/axis-definitions`（一覧取得・作成/PUT更新/DELETE削除/POST非公開化）へそのまま転送する |
| `components/AxisStudio/MaterialCoveragePanel.tsx` | 「材料」タブ本体。材料ごとの欠損割合を「欠損時の扱い」で2グループに分けた表（各グループ内は欠損割合降順）と集計対象外材料の理由一覧。集計は「集計する」ボタン押下時のみ |
| `services/materialCoverageApi.ts` | `MaterialCoveragePanel`が使うAPIクライアント（`app/admin/api/material-coverage/`経由、90秒タイムアウト） |
| `app/admin/api/material-coverage/route.ts` | `materialCoverageApi.ts`が叩くroute handler。`proxyToBackendAdmin`でbackend `GET /api/admin/material-catalog/coverage`へ転送する。全表走査を伴うため`timeoutMs`で既定（15秒）より長い転送タイムアウトを指定する |
| `app/admin/api/material-values/[materialId]/route.ts` | `materialCatalogApi.ts: getMaterialValues`が叩くroute handler。`proxyToBackendAdmin`でbackend `GET /api/admin/material-catalog/{material_id}/values`へ転送する（Next.js 16の`params`はPromise） |
| `components/AxisStudio/DerivedDataFreshnessPanel.tsx` | 「データ保守」タブ本体。派生テーブルごとに、鮮度（最新取込runと反映済み最古run）・被覆（親に対して行が無い件数）・完成度（値の列の未計算件数）を1行へまとめて表示。対象の表・列はbackendが宣言から導く（`source_run_id`を持つ表が派生データ）。集計は「集計する」ボタン押下時のみ |
| `components/AxisStudio/DbStatusPanel.tsx` | 「データ保守」タブ・本番DBの状態。取込runの最終実行・テーブルの実数と容量・統計とVACUUMの鮮度・接続を1件1行で出す |
| `services/dbStatusApi.ts`・`app/admin/api/db-status/route.ts` | 上記のAPIクライアントと、/adminのBasic認証セッションを再利用する同一オリジンのroute handler |
| `services/derivedDataFreshnessApi.ts` | `DerivedDataFreshnessPanel`が使うAPIクライアント（`app/admin/api/derived-data-freshness/`経由、90秒タイムアウト） |
| `app/admin/api/derived-data-freshness/route.ts` | `derivedDataFreshnessApi.ts`が叩くroute handler。`proxyToBackendAdmin`でbackend `GET /api/admin/derived-data/freshness`へ転送する |
| `components/AxisStudio/TileCachePanel.tsx` | 「データ保守」タブの2枚目。サーバー側のタイルファイルキャッシュ（基礎地図・路面/事故/POIタイルが共有）を全消去する操作パネル。全利用者へ影響するため入口はここだけに持つ |
| `components/AxisStudio/TuningPanel.tsx` | 「較正値」タブ本体。走ってみて決める値をデプロイなしで編集する。**並べる項目はbackendが宣言から導く**ため画面側に一覧を持たず、効き方（`effect`）ごとに見出しを分けて「変えたのに効かない」群がそれと分かるようにする。1件=1行で、説明と既定値・範囲は(i)の奥（他の管理パネルと同じ省スペースの作り）。入力は打っただけでは送らず「DBへ保存」でまとめて書き、既定と同じ値にして保存した行は上書きを消す（DBへ残るのは動かしたぶんだけ） |
| `services/tuningApi.ts` | 較正値の一覧・更新（`/admin/api/tuning`経由） |
| `app/admin/api/tuning/route.ts`・`[paramId]/route.ts` | `tuningApi.ts`が叩くNext.js route handler。`proxyToBackendAdmin`でbackend `/api/admin/tuning`（一覧取得・PUT更新）へそのまま転送する |
| `services/basemapAdminApi.ts` | `TileCachePanel`が使うAPIクライアント（`app/admin/api/basemap-refresh/`経由） |
| `app/admin/api/basemap-refresh/route.ts` | `basemapAdminApi.ts`が叩くroute handler。`proxyToBackendAdmin`でbackend `POST /api/admin/basemap/refresh`へ転送する |
| `hooks/useMaterialCatalog.ts` | `GET /api/material-catalog`取得。静的な写しは持たず、取得完了までと失敗時は空の一覧を返し、`loaded`で読み込み中と区別する（写しで埋めると、backendへ材料を足しても古い一覧が出続ける） |
| `hooks/useMaterialValues.ts` | `GET /api/admin/material-catalog/{material_id}/values`取得（`app/admin/api/material-values/[materialId]/`のroute handler経由）。categorical材料の候補選択セレクトに使う実データ値一覧 |
| `services/materialCatalogApi.ts` | 上記2フックが叩くbackend APIの薄いラッパー |
| `lib/axisMaterialsCatalog.ts` | 材料の型（`AxisMaterialOption`。一覧そのものは`hooks/useMaterialCatalog.ts`が取る）と、材料idを表示へ変える関数。`materialCatalogLabel`（論理名 - 物理名、軸スタジオ専用）/`materialCatalogName`（論理名だけ。カタログに無いidはundefinedで、呼び出し側はその材料を出さない）/`formatMaterialValue`。後の2つは軸スタジオ外（[ルート設定・結果パネル](route-settings-and-results.md)のComparisonPanel、page.tsxの区間クリック詳細）が`material_values`のラベル・単位表記に使う共用ヘルパー |
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
  重みの節を一切出さず表示専用フィールドのみ編集できる）で開く。
  材料・計算式・重みを変えたい場合は引き続き「複製して新規作成」に導線を残す。
### 折れ点の効き方を実データで見せる

折れ点の曲線エディタの下に、その折れ点で**実データの延長が得点帯へどう散らばるか**を出す。
数値の入力欄だけでは折れ点の妥当性を判断できず、公開して地図とルートを見るまで結果が
分からないため。満点への張り付きが半分を超える・0点が9割を超える場合は警告を添える。

分布の取得と当てはめは役割を分ける。backendは**折れ点を通す前の生値**のヒストグラムだけを
返し、折れ点の当てはめは`scoreDistribution.ts`がクライアントで行う——折れ点を1つ動かす
たびに通信すると編集の手応えが失われるうえ、折れ点は区分線形の写像でしかなく、生値の
ヒストグラムがあればクライアントで正確に求まる。取得のキー（`useAxisValueDistribution`の
`termsKey`）に折れ点を含めないのはこのため。

抽選した道が1本も値を持たない（`sample_ways=0`）ときは、全帯0%のバーではなく理由を言葉で
出す。ルート文脈が要る材料（走行方向・時刻に依存する勾配・風）はWay単位では値が定まらず、
その軸ではこの状態が常態のため——0%のバーを並べると「分布はあるが全部0」と読めてしまう。

同じ分布を**曲線エディタの背景へも重ねる**（`curveDistributionOverlay.ts`）。得点帯ごとの
割合（上記のパネル）は「結果がどう散らばるか」を答えるが、「**曲線のどの部分が効いて
いるか**」は答えない——値が集中する帯の外側で折れ点を動かしても結果は変わらず、集中する
帯の中で急にすると大きく変わる。曲線エディタの横軸は折れ点を通す前の生値で、backendが
返す階級・分位と同じ量のため、そのまま重ねられる。

- 階級が表示範囲をまたぐときは**幅に比例して按分**する。丸ごと入れる／落とすと範囲の端で
  割合が跳ねる。
- 分位線は`p10`/`p50`/`p90`の3本に絞る（全6分位を出すと線だらけになる）。
- **表示範囲の外にある延長は割合として画面に残す**。黙って切ると「分布は全部見えている」と
  読めてしまい、折れ点が実データの範囲と合っていないこと自体——この重ね描きが一番伝えたい
  こと——が画面から消える。ごく僅か（`OFF_RANGE_NOTICE_THRESHOLD`未満）のときは出さない。

### 公開済み軸の「調整する」

公開済み軸の材料・計算式・折れ点を変えるには、backendの`check_publish_immutability`により
一度下書きへ戻す必要がある。「調整する」ボタンはその手順（非公開化→編集→保存時に再公開）を
1操作に畳む。編集を中断した場合は下書きのまま残るため、**その事実を必ず知らせる**
（黙って非公開になると一般ユーザー向けの軸カタログから消えたことに気づけない）。
材料・計算式を変えない表示専用の編集は従来どおり「表示だけ編集」を使う。

**暗黙の前提**: 中断の通知を出すかは`closeComposer(republished)`の**引数**で決める。
`setRepublishAxisId(null)`の直後に呼んでも、その関数が読む状態はそのレンダーの
クロージャのままで、再公開に**成功した**直後に「下書きのまま残った」と通知してしまう。

調整中は`公開する`チェックボックスを出さず、「保存すると公開へ戻ります」という事実だけを
示す（`AxisMapDisplaySection`の`republishing`）。保存が無条件に公開へ戻すため、操作できる
チェックボックスを置くと、外して保存しても公開へ戻り**画面の操作結果が無言で反転する**
（design-principles.md「1つの状態は1つの場所でだけ操作する」）。

- 削除前チェック: `axesReferencing(axisId, definitions)`が、削除しようとしている軸を
  他の軸が材料として参照していないか調べ、参照があれば確認ダイアログ（`window.confirm`）で
  警告する（一律拒否はしない、最終判断はユーザーに委ねる）。
- 一覧サマリ行（`renderRowMain`）は各軸が使う材料id/軸idの両方を`labelForMaterialOrAxis`で
  人間向けラベルへ解決する。まずこの軸一覧内に該当する軸id（内部軸階層、他axis_idを
  材料として参照するケース）が無いか探し、あればその`label`を優先する。無ければ
  `axisMaterialsCatalog.ts: materialCatalogLabel`（`useMaterialCatalog`が取得した材料一覧を
  引く）へフォールバックし、それにも無ければ生のidをそのまま出す。
- 最後の1軸は削除ボタンを無効化する。
- 編集・複製・新規作成はいずれもモーダル（`components/ui/Dialog`）で`AxisComposer`を開く
  （`<AxisComposer key={...}>`でkeyを切り替え、対象を変えるたびに再マウントする方式）。
- `/admin`ページ自体が既にBasic認証（`frontend/src/proxy.ts`）で保護されているため、
  この画面はユーザー名/パスワード入力欄を持たない。CRUD APIは同一オリジンのNext.js
  route handler（`app/admin/api/axis-definitions/`配下、`lib/adminApiProxy.ts:
  proxyToBackendAdmin`）経由で、ブラウザの認証キャッシュがそのまま転送される。backend宛の
  資格情報はサーバー側route handlerがサーバー環境変数から組み立てるため、ブラウザには
  一切露出しない。読み取りと「片方だけ設定された状態は未設定として扱う」判断は
  `lib/adminBasicAuth.ts`が1箇所で持ち、`proxy.ts`（画面の保護）と`adminApiProxy.ts`
  （backendへの転送）の双方が同じ結果を見る。`proxyToBackendAdmin`は軸CRUD専用ではなく、「開発者」タブの
  バックエンドログ表示パネル（`app/admin/api/debug/logs/`）・「材料」タブの欠損割合
  （`app/admin/api/material-coverage/`）とも共有する汎用プロキシ（転送タイムアウトは
  既定15秒、`timeoutMs`オプションで呼び出し元route handlerが延長できる）。

## AxisComposer.tsx（1画面のフォーム）

**画面は1枚で、節の順番を持たない。** 軸を作るのに本当に前後関係があるのは
「材料を選ぶ→その材料の型で点数の入力欄が決まる」ところだけで、それは節を分けなくても
**選んだ材料に応じて入力欄を出し分ける**だけで表せる。スマホで開いたときに、開いてすぐ
色分けまで一続きに見えることを優先する。

| 節 | 見出し | 出る条件 |
|---|---|---|
| `basic` | （見出しなし。表示名・説明・既定重み） | 下書き軸のみ |
| `shape_params` | 点数の決め方（`AxisScoringSection`） | 下書き軸のみ |
| `display_publish` | 地図表示・公開（`AxisMapDisplaySection`） | 常に |

**暗黙の前提**: 下書きは材料カタログから導くが、そのカタログは実行時フェッチで後から
入れ替わる。**入れ替わったら導出し直す**——`useState`の初期化はマウント時に1度しか
走らないため、ビルド時フォールバックの材料で固定されたままになる。backendをデプロイ
してからfrontendをデプロイするまでの窓では、新しい材料を使う軸の編集画面が
「組み合わせる軸」として開く（`axisDraft.ts: draftFromExisting`が、材料として引けない
項目を軸参照とみなすため）。導出し直すのは**利用者がまだ触っていないとき**だけで、
判定はいまの下書きが最後に導出したものと同じ実体かで行う（触った後に入れ替えると入力が消える）。

`SECTIONS`は「どの節の検証か」を指す識別子で、順番の意味を持たない。保存時に
`validateSection`が各節の検証（`basic`は表示名必須、`shape_params`は折れ点のx昇順・
categorical材料のスコア行1件以上、`display_publish`はchip_labelの4文字制限・
display_thresholds_overrideの昇順）をまとめて行い、最初に見つかった原因を文章で出す。

**`noValidate`を付ける。** 検証は`validateSection`が行い原因を文章で示す。ブラウザの制約
検証（`step`・`min`/`max`）へ任せると、小数の刻みが浮動小数の誤差で不一致と判定された
とき、何の表示も無いまま送信だけが止まる——1画面で全ての欄が同時に検証対象へ入るぶん、
この止まり方が起きやすい。数値入力欄の`step`も`any`にする。

**制限モード**: `editing`が公開済み軸（`editing.is_published`）の場合、
`restrictedDisplayOnly`が`true`になり、`basic`・`shape_params`の節を**描画そのものごと
省く**（backendが表示専用フィールドの差分しか受け付けない——
`domain/axis_definitions.py: _COSMETIC_ONLY_FIELDS`——ため、いま何が変えられるかを画面の
形で示す）。検証も`display_publish`だけに絞る——描画していない節を検証すると「入力欄が
無いのにそこへ誘導される」行き止まりになる。`公開する`チェックボックスもこのモードでは
非表示にする（is_published自体は変更させない。切替は`AxisStudio.tsx`の「非公開に戻す」
ボタンへ導線を一本化）。入力欄の無い節の`draft`フィールド（label・shape・
default_weight等）は`draftFromExisting`が読み込んだ既存値のまま素通しで保存される。

### Draft⇔payloadの変換は別ファイル（`axisDraft.ts`）

`Draft`（フォームの内部状態）とbackendの`AxisDefinitionPayload`の相互変換
（`emptyDraft`・`draftFromExisting`・`draftFromDuplicate`・`buildShape`・
`pickPassthroughFields`と、素通しキーのカバレッジ型）は`AxisComposer.tsx`から分けてある。
**変更理由が違う**——こちらはbackendのpayloadスキーマが変わったときに動き、
`AxisComposer.tsx`はフォーム項目が増減したときに動く。

`breakpointTools.ts`・`scoreDistribution.ts`・`curveDistributionOverlay.ts`と同じDOM非依存の
純ロジックで、コンポーネントを起動せず直接テストできる（`axisDraft.test.ts`）。同じ性質は
フォームを操作する`AxisComposer.test.tsx`でも押さえているが、そちらは導線の検証と混ざる。

`Draft`は「今は選ばれていないkindの入力値」も保持する（kindを切り替えて戻したときに
打ち直しにならないようにするため）。保存時に`buildShape`が選択中のkindぶんだけを取り出す。

### 点数の決め方は材料から導く（`AxisScoringSection.tsx`）

**「なめらか評価／ぴったり評価」のような呼び名を利用者に選ばせない。** 選ぶのは
「点数のもとになるもの」（材料、または他の軸）1つだけで、その型が点数の入力欄を決める。
呼び名の3択は、選んだ材料と矛盾する組み合わせを選べてしまう（数値材料に「ぴったり評価」
を当てる等）うえ、名前の意味を覚える必要がある——材料は一覧から選べば型が確定するので、
その情報を利用者へ聞き直していたことになる。

**点数の形（`shapeKind`）は列挙されたものだけを持ち、GUIから任意に増やせるようにはしない。**
新しい形が要るならコード変更を伴う——際限のない汎用化を目指さず、増やす判断をそのつど
通す側に倒している。軸の**中身**（材料・係数・折れ点）は運用で自由に変えられることと、
**形の種類**が固定であることは別の決まりとして扱う。

セレクトは`<optgroup>`で「数値」「はい・いいえ / 種類」「ほかの軸」に分け、
`selectPrimaryMaterial(id)`が選ばれた型に応じて`draft.shapeKind`・`terms`・
`categoricalRows`・`breakpoints`をまとめて組み替える。数値材料の間の入れ替えでは係数と
折れ点を保つ（材料だけ差し替えたい場合に打ち直しにならないようにする）。

| 選んだもの | 出る入力欄 | `draft.shapeKind` |
|---|---|---|
| 数値の材料 | 「何点にするか」（0点にする値・100点にする値・効き方） | `breakpoint_linear` |
| はい/いいえ・種類の材料 | 該当時/非該当時のスコア、または値ごとのスコア行 | `categorical` |
| ほかの軸 | 係数を掛けた合計 | `recipe_then_breakpoint_linear` |

**フロント側の`ShapeKind`型（`"breakpoint_linear" | "recipe_then_breakpoint_linear" |
"categorical"`）は入力欄の出し分けを決める内部の分類であり、backendの`AxisShape`型
（`BreakpointLinearShape` | `CategoricalShape`）とは別の型**——
`buildShape(draft, materialOptions)`が送信直前に`draft.shapeKind`を`shape.kind`
（`"breakpoint_linear"`か`"categorical"`）へ正規化する。既存軸を編集/複製する際は、逆に`draftFromExisting`が`shape.terms`の構造（材料idか他axis_id参照か）から推定し
直す（保存済みの`kind`だけでは判別できないため）。

「ほかの軸」を選んでいる間は`materialOptions`ではなく`otherAxes`（編集中の軸自身を除く
全軸、`AxisStudio.tsx`が渡す）を候補にする——`MaterialTerm.material`が他axis_idを指せる
設計（backend「軸の階層」）に対応するGUI導線。

**材料を1行ずつ並べる編集欄（係数つき）は、要るときだけ出す**（`showTermRows`）。単一の
数値材料では係数は「0点/100点にする値」へ吸収されるため出さない。はい/いいえの材料を
足し合わせる軸（街灯なし−50＋トンネル+50等）は係数そのものが点数の配分なので、1件でも出す。

**折れ点の並びは保存形式であって入力欄ではない。** 実在する軸の大半は2点の直線で、曲線は
実データを見て決めるもの（較正）。そのため既定の入力は「0点にする値・100点にする値・
効き方」だけにし（`applyScoringRange`が`generateBreakpoints`で折れ点を作り直す）、折れ点の
表と曲線エディタは`<details>折れ点を直接いじる</details>`の中に畳む。

### 折れ点エディタ・スライダー・数値入力

- `breakpointTools.ts`（DOM非依存の純粋関数、`AxisScoringSection.tsx`が使う単一の実装）:
  - `generateBreakpoints(zeroValue, hundredValue, shape)`: 「0点にする値」「100点にする値」
    「形」（一定/後半で急/前半で急/S字）の3入力から6点の折れ点を生成する。
    `zeroValue > hundredValue`（値が大きいほど走りやすい軸）でも常にx昇順で返す。
  - `generatorSettingsFrom(breakpoints)`: 上の逆。いまの折れ点から3入力を復元する。
    **生成フォームは使い捨ての入力欄ではない**——3入力は`onChange`のたびに
    `draft.breakpoints`を作り直すため、固定の初期値を持たせると既存の軸を開いたときに
    その軸と無関係な範囲が表示され、どれか1つに触れた瞬間に較正済みの端点が黙って消える。
    生成物と総当たりで突き合わせて一致すれば効き方まで復元し（`matched`）、手で編集された
    折れ点なら端点だけを点数の低い側/高い側から復元する。
  - `interpolateBreakpointScore(breakpoints, x)`: 区分線形補間。backend:
    `domain/axis_templates.py: evaluate_breakpoint_linear`（`np.interp`、両端クランプ・
    小数1桁丸め）と同じ結果になるよう実装を揃える——効き目プレビュー表が実際の評価結果と
    食い違わないようにするため。
  - `insertBreakpointAtLargestGap(breakpoints)`: 「+ 折れ点を追加」の挿入位置。隣接点の
    x間隔が最も広い区間の中間へ挿入する（末尾への追加では、既存の
    折れ点より横軸が小さい点を足してしまい昇順制約に即座に違反していた）。
  - `niceStep`/`snapToStep`: ドラッグ中のx方向スナップ刻み幅の算出（表示レンジに対して
    「きりのいい」1/2/5×10^nを選ぶ）。
- **効き目プレビュー表・自動生成の値の目安（「参考点から値を選ぶ」ボタン）**は、
  `draft.terms.length === 1`かつ他軸参照ではない（`shapeKind === "breakpoint_linear"`）
  場合にのみ、そのterm1件の材料が持つ`referencePoints`（`GET /api/material-catalog`の
  `reference_points`、下記「useMaterialCatalog.ts / useMaterialValues.ts」節参照）から出す。
  複数termの組み合わせ・他軸参照は参考点の対応が取れないため対象外
  （`AxisScoringSection.tsx: primaryMaterial`）。参考点の生値は折れ点の横軸（`weight`を
  掛け、`preprocess="abs"`なら絶対値を取った後の値）へ変換してから使う
  （`AxisScoringSection.tsx: toBreakpointX`、backend: `evaluate_axis_scalar`の`total`計算と同じ
  変換）。
- `BreakpointCurveEditor`（`BreakpointCurveEditor.tsx`）: SVGでbreakpointsをドラッグ・
  矢印キー調整できる曲線プレビュー。
  同じ`draft.breakpoints` stateを数値入力行と共有し、常に同期する。`referenceRange`
  （参考点の値域）を渡すとその範囲＋10%余白へ横軸を固定する——参考点が無い材料は
  従来どおりbreakpoints自体の値から自動スケールする。目盛り線・ドラッグ中の値ラベル
  （フォーカス中の点の上に表示）・矢印キーでの微調整（Shift併用で10倍刻み）を持つ。
- `SliderNumberField`（`AxisFormFields.tsx`）: 係数・スコアをスライダー（大まかな目安）＋数値入力（正確な値）の
  組み合わせで編集する。スライダーの範囲は材料ごとに大きく異なる値の目安にすぎず、
  範囲外の値は数値入力欄から直接指定できる。
- `NumberField`（`AxisFormFields.tsx`）: フォーム内の数値入力（`SliderNumberField`の数値欄・既定重み・
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
  `useMaterialValues(materialId)`が`GET /api/admin/material-catalog/{id}/values`から実データ値
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
  （`Map/InfoPopover`＋`@/components/ui/`のポップオーバーCSS、`AxisComposer`の材料説明と
  同じ見た目）へ畳み、常時表示の説明文は各グループ1行だけにする。
- `excluded_reason`を持つ材料（集計対象外）は表に含めず、`<details>`の折りたたみ一覧へ
  理由つきで出す。
- 集計はDB全体の走査を伴うため、タブを開いたとき自動では実行せず「集計する」ボタン押下時
  のみ実行する（`DerivedDataFreshnessPanel`と同じ流儀）。
- 認証情報の入力欄は持たない（`AxisStudio.tsx`と同じく`/admin`のBasic認証セッションを
  route handler経由で再利用する）。

## DerivedDataFreshnessPanel.tsx（「データ保守」タブ）

`GET /admin/api/derived-data-freshness`（backend `GET /api/admin/derived-data/freshness`）の
レスポンス（`DerivedDataFreshnessResponse`、生成型）をそのまま一覧にする。
`MaterialCoveragePanel`（完成度、値がNULL/未取得か）とは別の切り口——行は存在するが、
参照している生データの世代が最新の取込より古いままではないか、という鮮度を見る。

**画面の説明はⓘ（`InfoPopover`）の奥に置き、ベタ書きしない**（design-principles.md
「冗長なものは削る」。読むのは1度きりなのに場所は常に取り続ける）。集計前はボタンだけを出す
——押すまで一覧は無いため、そこに無いものの説明を先に読ませない。

- 集計後の先頭に**作り直しが要る件数と、次に打つ1コマンド**（`app/batch/derive_cli.py`、
  派生データを段の順に作り直す単一の入口）をコピーできる形で置く。**行ごとにバッチ名を
  散らさない**——古い理由がどれであっても利用者が打つのは同じ1コマンドのため。
- そのコマンドは**本番でそのまま打てる形**（稼働中のbackendコンテナではなく、別コンテナを
  メモリ上限付きで立てる`docker run`）で出す。バッチのモジュール名だけを出すと、手元へ
  コピーした人は開発DBを作り直して本番が古いまま残り、本番で稼働中のコンテナへ入って
  打った人はサービスごと止めうる。打つ場所・実行後に要る後処理はⓘの奥に置く。
- 一覧は鮮度（世代比較）・被覆・完成度を**同じ見た目の1行**へ揃える
  （`rowsFromReport`が表ごとの`tables`を`FreshnessRow`へ写す）。読み手が知りたいのは「作り直しが要るか」で
  あり、判定方式の違いは開いた先に書けばよい。run番号・版数・担当バッチ・判定の但し書きは
  `<details>`の中で、タップしたときだけ出す。
- **表（`<table>`）を使わない。** 列を横に並べるとモバイルでは横スクロールの中へ数字が隠れ、
  「比較対象」の列だけが見える状態になる。ラベルと値を縦に積み、値だけが折り返す形にする。
- 対象の表と列はbackendがORMの宣言から導き（`infrastructure/derived_data_freshness.py:
  derived_tables`）、frontendは返ってきた行を並べるだけで対象を手書きしない。
- 集計はDB全体の走査を伴うため、`MaterialCoveragePanel`と同じく「集計する」ボタン押下時
  のみ実行する。認証情報の入力欄は持たない（`/admin`のBasic認証セッションをroute handler
  経由で再利用する）。
- 描画は`FreshnessReportView`（レポートを受け取る）として取得と分けてある。認証の要る画面を
  通さずに見え方を確かめられるようにするため。

## DbStatusPanel.tsx（「データ保守」タブ・本番DBの状態）

`GET /api/admin/db-status`を呼び、取込runの最終実行・テーブルの実数と容量・統計とVACUUMの
鮮度・接続の状態を出す。`DerivedDataFreshnessPanel`と同じ形（説明はⓘ、1件1行、数字は開いた
先、集計はボタン押下時のみ）で、CSSも同じモジュールを共有する。

- 判定の種類（取込・接続・テーブル）が違っても行の見た目は揃える。読み手が知りたいのは
  「注意が要るか」で同じだから。**揃えたぶん、何と何が並んでいるのかは群の見出しが引き受ける**
  （`groupsFromStatus`が群を組み立てる）。並び順に根拠がある群は、その根拠も見出しへ書く。
- **ヘッダーへ母数**（テーブルの数・行数の合計・DB全体の容量）を出す。畳んだ行の「Nテーブル」
  が何分のNなのかは、全体の数が同じ画面に無いと読めない。
- **テーブルは注意のあるものだけを行にし、残りは1行へ畳む**（本番では20件超あり、全部並べると
  注意すべき行が埋もれる）。畳んだ側も開けば一覧が見える。**畳んだ行は分けた基準（注意の
  有無）を自分で名乗る**——「その他」では、隠れた側が重要でないのか見るべきものが埋もれて
  いるのかが読めない。
- 描画は`StatusRows`として取得と分けてある（認証の要る画面を通さず見え方を確かめるため）。

## TileCachePanel.tsx（「データ保守」タブの2枚目）

`POST /admin/api/basemap-refresh`（backend `POST /api/admin/basemap/refresh`）を呼び、
サーバーが持つタイルのファイルキャッシュ（`tile_cache`。基礎地図のプロキシ結果と
路面・事故・POIのベクタタイルが同じ場所を共有する）を全消去する。
`DerivedDataFreshnessPanel`が「古いかどうかを見る」のに対し、こちらは「古いものを捨てる」
操作側のため同じタブに並べる。

影響は押した人だけでなく**全利用者**に及ぶ（次のタイル要求で作り直されるまで、外部
サービスへの実問い合わせやタイル生成が走る）。この操作が管理API認可境界の内側にしか
入口を持たないことが、`/`側の「地図の表示を再描画」ボタン（押した人の地図インスタンス
だけを組み直す純粋なクライアント操作）と分かれている理由。押しても管理者自身の画面は
変わらない（この画面は地図を持たない）ため、消したこと自体と、各利用者へ反映されるのが
既存タイルの`Cache-Control`（基礎地図は10分）が切れた後であることを結果表示で伝える。

## 材料が0件のときの防御

`useMaterialCatalog()`は取得完了まで・失敗時・0件の応答のいずれも空配列を返し、
取得が終わったかを`loaded`で別に持つ（後述）。`AxisComposer`は`loaded`が偽の間は読み込み中の
表示だけを出し（通信が遅いだけのときにbackendの異常を疑わせない）、取得後も0件ならフォーム
自体を表示せず、「材料カタログを取得できませんでした（0件の応答）」というエラー画面＋
「閉じる」ボタンのみを出す（`emptyDraft`が`materialOptions[0]`への無条件アクセスでクラッシュするのを防ぐガード。
フック呼び出し自体はこのガードより前で完了させ、Rules of Hooksには反しない）。

## 材料説明ポップオーバー

`InfoPopoverButton`/`MaterialInfoButton`（`AxisFormFields.tsx`）が、材料選択欄の隣に
(ⓘ)アイコンを置き、backend `material_catalog.py: MaterialSpec.description`をポップオーバー
表示する。外枠（開閉state・Radix Popover・開閉に追随するアクセシブル名）は共通部品
`Map/InfoPopover.tsx`が持ち、ここはラベル文言を持たない小型トリガーとしての薄いラッパー。
ポップオーバーのCSS自体は共有部品の`@/components/ui/infoButton.module.css`・
`floatingPopover.module.css`をそのままimportし、二重定義しない。

## useMaterialCatalog.ts / useMaterialValues.ts（材料カタログhook）

| フック | 取得先 | フォールバック | 取得成功かつ0件のとき |
|---|---|---|---|
| `useMaterialCatalog()` | `GET /api/material-catalog` | 持たない（静的な写しで埋めると、backendへ材料を足しても古い一覧が出続ける） | **空配列をそのまま返す**。「読み込み中」と「取得後に空」は`loaded`で区別する |
| `useMaterialValues(materialId)` | `GET /api/admin/material-catalog/{id}/values` | 持たない（実データ値一覧はコード側で妥当な代替を用意できないため） | 空配列（＝呼び出し側は自由テキスト入力へフォールバック） |

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
- このフォームに編集欄を持たないフィールド（正本は`axisDraft.ts`の
  `PASSTHROUGH_PAYLOAD_KEYS`。ここには再掲しない）も、既存軸の値をdraftの`passthrough`へ
  素通しして保存時に再送する（未送信だとサーバー側の既定値で上書きされ、既存軸の
  値が失われるため）。フォームが値を組み立てるフィールドは型`EditedPayloadKey`が持ち、
  2つのリストが`AxisDefinitionPayload`の全フィールドを覆うことを型`_PayloadKeyCoverage`が
  静的に検査するため、backend側へフィールドが増えたときはどちらかへ追加しないとtscが
  通らない。`display_thresholds_override`/`display_band_labels_override`は
  専用の編集UI（`display_publish`の節）を持つため、このリストには含まない。
  `display_band_labels_override`の編集欄は`display_thresholds_override`が有効（null以外）の
  間だけ現れ、段階数（`displayThresholdsOverride.length+1`）と要素数を常に一致させる
  （`resizeBandLabels`）——しきい値の上書きを解除する（自動計算に戻す）とラベルの上書きも
  一緒にnullへ解除する（backend側のバリデーション「ラベルはしきい値の上書きが設定済みで
  なければならない」との不整合を防ぐ）。

### 色分けしきい値の編集（まとめ入力とプレビュー）

境界値は1つの入力欄へまとめて書く（`parseThresholdList`が区切りを問わず解釈する）。
**入力欄の文字列はdraftとは別にコンポーネントが持ち、読めたときだけdraftへ反映する**
——読めない途中の状態でdraftを書き換えると直前の並びが消える。読めないまま保存しようと
した場合は`validateSection`が止めるため（節が`onThresholdErrorChange`で親へ伝える）、
下書きの値が黙って保存されることはない。

入力した内容は`renderBandPreview`がその場で段階の並びとして描く。段階ラベルの組み立ては
地図の凡例と同じ`mapColorLegend.ts: buildRangeLegendBands`を通し、色は親（`AxisStudio`）が
軸カタログの分類から決めて渡す（ramp軸は`rampColorForBand`、専用way値配信軸は
`bandColorsFor`。[地図: 軸・ルート色分け](map-axis-coloring.md)参照）。**軸スタジオ側は
「その軸がどちらの経路で地図に出るか」の判定を持たない**——カタログの実際の分類を引くため、
プレビューの色と地図の色がずれない。地図に出る経路がまだ無い軸（下書き等）は色を持たず、
その旨を注記する。

**地図では段にならない値は、入力欄のすぐ下で名指しする**（「地図では効かない: 12」、理由は
ⓘの奥）。点数の決め方で1つ手前の境界と同じ点数になる値は、地図が段を作らない
（[backend](../backend/axis-studio.md)「折れ線が同じスコアへ写す境界は落とす」）。
**判定はbackendに問い、画面は規則を持たない**——`AxisComposer`が下書きの`shape`・
`priority_overrides`・しきい値を`useThresholdsDroppedOnMap`へ渡し、結果を節へpropで渡す。
点数の決め方を変えても判定し直すよう、問い合わせのキーには`shape`も含める。取得に失敗した
ときは印を出さない（判定できないことを「効かない値がある」と取り違えさせない）。
段階プレビュー（見出しの「N段階になります」と並び）も同じ判定の結果から、地図が段として
作る境界だけで描く（`axisDraft.ts: thresholdsKeptOnMap`。入力からbackendが返した値を除く
だけ）——印だけ出して段数を入力どおりに数えると、見出しと地図の凡例の段数が食い違う。
判定の結果が届くまでの間は、入力どおりの段で出る。
- **`category`は編集欄を持たない素通しフィールド**（`PASSTHROUGH_PAYLOAD_KEYS`）。新規
  作成時だけ`"推定"`になり、既存軸は既存の値をそのまま送り返す（観測/動的は材料側の性質で、
  材料を組み合わせて判定式を作る軸スタジオの仕組みからは生み出せないため、新規は推定で
  よい）。**編集欄を持たないフィールドを定数で作り直さない**——公開済み軸のPUTは
  「表示専用フィールドだけの差分」しか通らない（backend:
  `domain/axis_definitions.py: is_cosmetic_only_update`）ため、画面に無い値を1つでも
  書き換えると、何も変えていないのに保存が拒否される。
  **この往復を検査するテストは、実在軸のスナップショットを母集団にする**——フォームの
  初期値と一致する軸だけを置くと、素通しフィールドが書き換わっていても差分が出ず、検査が
  素通りする。

## backend側との対応

frontendのこの画面は、backendの[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)が
定義する`AxisDefinitionPayload`のバリデーション規則（chip_label 4文字制限・
display_thresholds_override昇順・shape.breakpoints x昇順・材料/軸参照の既知性）の一部を
`AxisComposer.tsx: validateSection`でも先回りしてチェックする（保存時のエラーで初めて気づく
手戻りを避けるため）。ただし最終防衛はbackend側であり、frontendの検証はUX上の先回りに
すぎない。
