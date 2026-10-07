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
| `features/admin/AxisStudio/AxisStudio.tsx` | トップレベル。一覧取得・作成/更新/削除/複製/非公開化の状態管理 |
| `features/admin/AxisStudio/AxisComposer.tsx` | 1画面フォームの本体。draftの状態・保存前の検証・保存と、節の組み立てだけを持つ |
| `features/admin/AxisStudio/AxisScoringSection.tsx` | 「点数の決め方」の節。材料の選択と、その材料の型に応じた点数入力（0点/100点・効き方、はい/いいえ、値ごと、他軸の係数）。折れ点の直接編集は畳んだ詳細設定の中 |
| `features/admin/AxisStudio/AxisMapDisplaySection.tsx` | 「地図表示・公開」の節。色分けしきい値のまとめ入力と段階プレビュー・アイコン・公開チェック |
| `features/admin/AxisStudio/AxisFormFields.tsx` | 上記2節とAxisComposerが共有する入力部品（`InfoPopoverButton`・`MaterialInfoButton`・`SectionLabel`・`SliderNumberField`） |
| `features/admin/AxisStudio/axisDraft.ts` | Draft（フォームの内部状態）とbackendのpayloadの相互変換。`buildShape`・`draftFromExisting`・`pickPassthroughFields`・`PASSTHROUGH_PAYLOAD_KEYS`。変更理由はbackendのpayloadスキーマで、フォームUIの増減とは独立している |
| `features/admin/AxisStudio/BreakpointCurveEditor.tsx` | 折れ点をドラッグ・矢印キーで調整できるSVGの曲線エディタ。背景へ実データの分布を重ねる |
| `features/admin/AxisStudio/curveDistributionOverlay.ts` | 曲線エディタの背景へ分布を重ねるための純粋関数（DOM非依存。階級のクリップ・按分、分位線、表示範囲外の割合） |
| `features/admin/AxisStudio/scoreDistribution.ts` | 生値の分布へ折れ点を当てはめ、得点帯ごとの延長割合と警告を求める純粋関数（DOM非依存、`DistributionPreview.tsx`が使う） |
| `features/admin/AxisStudio/DistributionPreview.tsx` | 折れ点の下に「この折れ点での得点分布」を出すパネル。満点への張り付き・0点への偏りを警告する |
| `features/admin/AxisStudio/MaterialRangeHint.tsx` | 材料選択行の下に、その材料が実データで取る値の分位（p50/p75/p90）を出す1行表示 |
| `features/admin/adminApi.ts` | 管理画面のAPIクライアントをまとめたもの。管理API（backend `/api/admin/**`）は`lib/apiClient.ts: adminApiClient`で同一オリジンの口`/admin/api/**`へ投げ、backendのパスの`/api/admin`より後をそのまま使う（例: backend `GET /api/admin/db-status`は`/admin/api/db-status`）。パス・本文・応答の型は管理APIの宣言から決まり、宣言に無いパスは型検査で落ちる（[ページ全体構成](page-composition.md)）。待ち時間は呼び出しごとに決める（全表走査の集計は`HEAVY_ADMIN_API_TIMEOUT_MS`、分布は`DISTRIBUTION_API_TIMEOUT_MS`）。稼働状況の口（`/health`・`/api/debug/stats`・`/api/version`）も同じファイルに置く |
| `app/admin/api/[...path]/route.ts` | 管理APIの転送の口。`/admin/api/<X>`への要求を、サーバーの環境変数から組み立てたBasic認証を付けてbackendの`/api/admin/<X>`へ、メソッド・クエリ・本文・応答の状態と本文ごとそのまま渡す。転送の待ち時間はどのクライアントよりも長く取り（`ADMIN_PROXY_TIMEOUT_MS`）、打ち切りはクライアントに任せる |
| `proxy.ts` | `/admin`配下（画面と管理APIへの転送の口）の手前のBasic認証。ファイル名と`config.matcher`はNext.jsの規約で、`matcher`が認証を求める道を決める。資格情報が未設定なら、どの要求も拒む |
| `lib/adminBasicAuth.ts` | Basic認証の資格情報を環境変数から読む口。片方でも空なら未設定（`null`）とし、`proxy.ts`と転送の口が同じ結果を見る |
| `features/admin/useSettledDraftQuery.ts` | 下書きから組んだ問い合わせの骨格（入力をJSONにして取得の鍵にし、落ち着いてから問い合わせ、今の入力と違う答えは出さない）。答えと一緒に、今の入力の問い合わせが失敗したかを返す（届く前と失敗はどちらも答えが無いため、呼ぶ側が分けて出せるように）。backendが判定・計算を持ち、画面は下書きを送るだけの取得（例: `useScoresPreview`・`useMapBandsOfThresholds`）が使う |
| `features/admin/useScoresPreview.ts` | 下書きの折れ点で、分布の階級の代表値と材料の参考点がそれぞれ何点になるか（参考点は折れ点の横軸の値も）を取得する（下書きが落ち着いてから問い合わせる。入力を変えた直後・失敗時は点数なしで、失敗したことも返す） |
| `features/admin/useMapBandsOfThresholds.ts` | 下書きのしきい値が地図でどの段になるか（段にならない値・地図の各段に当たる入力の段）を取得する（下書きが落ち着いてから問い合わせる。失敗時は判定なしで、失敗したことも返す） |
| `features/admin/useAxisValueDistribution.ts` | 編集中のshapeの生値分布を取得。取得キーに折れ点を含めないため、折れ点のドラッグ中は通信しない。取り直している間は前の分布を出したまま読み込み中にする |
| `features/admin/useMaterialDistribution.ts` | 材料1件の値の分布を取得。同じ材料を複数行が選んでも、画面を開いている間に取りに行くのは1回（取れなかったことも覚える） |
| `features/admin/AxisStudio/breakpointTools.ts` | 折れ点の自動生成・区分線形補間・追加位置決定・ドラッグスナップ刻み幅算出（DOM非依存の純粋関数、`AxisComposer.tsx`が使う） |
| `features/admin/AxisStudio/MaterialCoveragePanel.tsx` | 「材料」タブ本体。材料ごとの欠損割合を「欠損時の扱い」でグループに分けた表（各グループ内は欠損割合降順）と集計対象外材料の理由一覧。グループの見出し・説明と母集団の名前はbackendの宣言（`domain/material_catalog.py: MISSING_SEMANTICS_DISPLAY`・`domain/material_catalog.py: POPULATION_LABELS`）が生成物`vocabulary.ts`で配る |
| `features/admin/AxisStudio/DerivedDataFreshnessPanel.tsx` | 「データ保守」タブ本体。ソースごとの鮮度（成功した最新の取込と作り直しに使った取込）と、派生テーブルごとの列の比較（作ったときの列と今の宣言の列。値の列ごとの値なしの件数は参考）を、それぞれ1行へまとめて表示。対象の表・列はbackendが宣言から導く（表の印を持つ表が派生データ）。作り直しが要るかもbackendが決め（`needs_rebuild`）、画面は理由を問わずそれで数える |
| `features/admin/AxisStudio/DbStatusPanel.tsx` | 「データ保守」タブ・本番DBの状態。取込runの最終実行・テーブルの実数と容量・統計とVACUUMの鮮度・接続を1件1行で出す |
| `features/admin/AxisStudio/StatusRowList.tsx` | 上記2パネルが共有する点検の行の一覧（状態の丸・名前・規模、開くと項目と値）と、結果の一言（手当てが要れば目立たせる） |
| `features/admin/AxisStudio/ReportCard.tsx` | 集計のパネル（材料の欠損割合・派生データ鮮度台帳・本番DBの状態）が共有するカード。見出しとⓘ・「集計する」ボタン・集計中と失敗の表示・集計の時刻（日本時間）を持ち、中身の描画は各パネルが渡す。件数と時点の書式（`formatCount`・`formatMoment`）もここに置く |
| `features/admin/AxisStudio/TileCachePanel.tsx` | 「データ保守」タブの2枚目。サーバー側のタイルファイルキャッシュ（基礎地図・路面と点のタイルが共有）を全消去する操作パネル。全利用者へ影響するため入口はここだけに持つ |
| `features/admin/AxisStudio/TuningPanel.tsx` | 「較正値」タブ本体。走ってみて決める値をデプロイなしで編集する。**並べる項目はbackendが宣言から導く**ため画面側に一覧を持たず、効き方（`effect`）ごとに見出しを分けて「変えたのに効かない」群がそれと分かるようにする。1件=1行で、説明と既定値・範囲は(i)の奥（他の管理パネルと同じ省スペースの作り）。入力は打っただけでは送らず「DBへ保存」でまとめて書き、既定と同じ値にして保存した行は上書きを消す（DBへ残るのは動かしたぶんだけ）。保存を待つ間に打ち直した値は、未保存として残す |
| `features/admin/useMaterialValues.ts` | `GET /api/admin/material-catalog/{material_id}/values`取得（`adminApi.ts: getMaterialValues`）。categorical材料の候補選択セレクトに使う実データ値一覧 |
| `lib/axisMaterialsCatalog.ts` | 材料の一覧（`MATERIAL_CATALOG`。生成物`material-catalog.json`から作る）と型（`AxisMaterialOption`）、材料idを表示へ変える関数（`materialCatalogLabel`: 論理名 - 物理名）・選択肢の表記（`materialOptionText`） |
| `components/ui/icons/axisIconPalette.tsx` | 軸のアイコンの固定パレット（`icon_id`→アイコンコンポーネント） |
| `components/ui/FieldLabel/FieldLabel.tsx` | 情報アイコン付きラベルの共有UI部品（ルート設定とも共有） |

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
- 公開済みタブの先頭に、「表示だけ編集」「調整する」「非公開に戻す」の意味を文で並べる（`title`はスマホで出ない）。
### 折れ点の効き方を実データで見せる

折れ点の曲線エディタの下に、その折れ点で**実データの延長が得点帯へどう散らばるか**を出す。
数値の入力欄だけでは折れ点の妥当性を判断できず、公開して地図とルートを見るまで結果が
分からないため。満点への張り付きが半分を超える・0点が9割を超える場合は警告を添える。

分布の取得と点数の計算は役割を分ける。分布の口（`preview-distribution`）は**折れ点を通す前の生値**の
ヒストグラムを返す。DBから抽選して集計する重い問い合わせなので、取得のキー（`useAxisValueDistribution`の
`termsKey`）に折れ点を含めず、折れ点を動かしても取り直さない。各階級の代表値（中央、`binMidpoints`）の
点数は、DBを読まない軽い口（`preview-scores`）へ折れ点が落ち着くたびに問い合わせる（`useScoresPreview`）。
点数の計算は評価と同じ1か所（`domain/axis_definitions.py: BreakpointLinearShape.score_at`）で、画面は届いた点数を帯へまとめる
（`scoreDistribution.ts: scoreBands`）だけ——画面で計算し直すと、同じ折れ点に評価と画面で別の点数が付きうる。

抽選した道が1本も値を持たない（`sample_ways=0`）ときは、全帯0%のバーではなく理由を言葉で
出す。ルート文脈が要る材料（走行方向・時刻に依存する勾配・風）はWay単位では値が定まらず、
その軸ではこの状態が常態のため——0%のバーを並べると「分布はあるが全部0」と読めてしまう。
同じ理由で、分布はあるが**点数がまだ届いていない・取得に失敗した**間も帯を並べず、計算中か取得できなかったかを
言葉で出す（`scoreDistribution.ts: scoreBands`が点数の揃わない間はnullを返す）。

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
下書きへ戻すのを待つ間に別のフォームを開いていたら、そのフォームを替えず（打ちかけの入力が消える）、下書きのまま
残ったことを同じく知らせる。保存を待つ間に閉じて別のフォームを開いていたら、保存が済んでもそのフォームは閉じない。

**赤（誤りの色）は、操作・保存・取得が失敗したときだけに使う。** 失敗ではない知らせ（例: 中断して下書きのまま
残った・地図では効かない値がある）は、注意の色（`ui/Callout`の`warning`。
得点分布の警告と同じ）で出す——赤で出すと、操作が通ったのに失敗したと読める。
材料・計算式を変えない表示専用の編集は従来どおり「表示だけ編集」を使う。

**暗黙の前提**: 中断の通知を出すかは`closeComposer(republished)`の**引数**で決める。
`setRepublishAxisId(null)`の直後に呼んでも、その関数が読む状態はそのレンダーの
クロージャのままで、再公開に**成功した**直後に「下書きのまま残った」と通知してしまう。

調整中は`公開する`チェックボックスを出さず、「保存すると公開へ戻ります」という事実だけを
示す（`AxisMapDisplaySection`の`republishing`）。保存が無条件に公開へ戻すため、操作できる
チェックボックスを置くと、外して保存しても公開へ戻り**画面の操作結果が無言で反転する**
（design-principles.md「1つの状態は1つの場所でだけ操作する」）。

- 削除できるか（ほかの軸が参照している軸・最後の1軸は消せない）は画面で判定しない。backendが
  起動時の読み込みと同じ判定で断り（[軸スタジオ（backend）](../backend/axis-studio.md)「書き込み時のガード」）、
  画面はその理由を一覧の上の誤りとしてそのまま出す。
- 「削除」は押しただけでは消さず、確認（`Dialog/Dialog.tsx: ConfirmDialog`）で「削除する」を押したときだけ
  削除のAPIを呼ぶ。消した軸を戻す手段が無く、下書きには折れ点を実データで調整した手間が入って
  いるため、同じ行に並ぶ「編集」「複製して新規作成」との押し間違いで失わせない。確認は消せるかを
  判定しない（判定は上のとおりbackendが持ち、断られたら確認を閉じたあと一覧の上に理由が出る）。
- 一覧サマリ行（`renderRowMain`）は各軸が使う材料id/軸idの両方を`labelForMaterialOrAxis`で
  人間向けラベルへ解決する。まずこの軸一覧内に該当する軸id（内部軸階層、他axis_idを
  材料として参照するケース）が無いか探し、あればその`label`を優先する。無ければ
  `axisMaterialsCatalog.ts: materialCatalogLabel`（材料の一覧`MATERIAL_CATALOG`を
  引く）へフォールバックし、それにも無ければ生のidをそのまま出す。
- 編集・複製・新規作成はいずれもモーダル（`components/ui/Dialog`）で`AxisComposer`を開く
  （`<AxisComposer key={...}>`でkeyを切り替え、対象を変えるたびに再マウントする方式）。
- `/admin`ページ自体が既にBasic認証（`frontend/src/proxy.ts`）で保護されているため、
  この画面はユーザー名/パスワード入力欄を持たない。管理APIは同一オリジンの口（`app/admin/api/[...path]`）
  経由で、ブラウザの認証キャッシュがそのまま使われる。backend宛の資格情報はサーバー側の口がサーバー環境変数から
  組み立てるため、ブラウザには一切露出しない。読み取りと「片方だけ設定された状態は未設定として扱う」判断は
  `lib/adminBasicAuth.ts`が1箇所で持ち、`proxy.ts`（画面の保護）と転送の口の双方が同じ結果を見る。
  **口はbackendの管理APIごとに作らない**——backendのパスの`/api/admin`を`/admin/api`へ読み替えるだけなので、
  管理APIを1つ足してもfrontendの口は増えない。

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

既定重みの下には、公開したときに公開軸の重みの合計に占める割合を参考に出す。割合はbackendが総合難易度と同じ分母で
返す値（`weight_share_when_published`）で、画面は計算し直さない——保存した重みで計算するため、編集中の値は保存して
から変わる。

下書きは材料の一覧（値ごとの材料か、はい/いいえの材料か）と軸の一覧からマウント時に1度だけ導く。材料の一覧は
ビルド時の生成物で、開いている間に入れ替わらない（読み込み中・取得失敗の状態も無い）。

`SECTIONS`は「どの節の検証か」を指す識別子で、順番の意味を持たない。保存時に
`validateSection`が入力の読み取りの誤り（しきい値が数値として読めない）だけを確かめ、原因を文章で出す。
軸の不変条件（表示名必須・折れ点のx昇順・値の行の件数・しきい値の件数と昇順等）は写さない——
backendが保存時に検証し、日本語の文で返す誤りをそのままフォームへ出す。

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
純ロジックで、コンポーネントを起動せず直接テストできる（`axisDraft.test.ts`）。

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
（`"breakpoint_linear"`か`"categorical"`）へ正規化する。既存軸を編集/複製する際は、逆に`draftFromExisting`が、`shape.terms`がすべて軸の一覧（`otherAxes`）の軸を指すなら
「ほかの軸」、そうでなければ材料として開く（保存済みの`kind`だけでは判別できないため）。材料カタログに無いかでは
決めない——backendのデプロイがfrontendより先に進んだ窓では、新しい材料がfrontendの一覧に無く、軸に見える。

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
    生成物と総当たりで突き合わせて一致すれば効き方まで復元し、手で編集された
    折れ点なら端点だけを点数の低い側/高い側から復元する。
  - `insertBreakpointAtLargestGap(breakpoints)`: 「+ 折れ点を追加」の挿入位置。隣接点の
    x間隔が最も広い区間の中間へ挿入する（末尾への追加では、既存の
    折れ点より横軸が小さい点を足してしまい昇順制約に即座に違反していた）。
  - `niceStep`/`snapToStep`: ドラッグ中のx方向スナップ刻み幅の算出（表示レンジに対して
    「きりのいい」1/2/5×10^nを選ぶ）。
- **効き目プレビュー表・自動生成の値の目安（「参考点から値を選ぶ」ボタン）**は、
  `draft.terms.length === 1`かつ他軸参照ではない（`shapeKind === "breakpoint_linear"`）
  場合にのみ、そのterm1件の材料が持つ`referencePoints`（生成物`material-catalog.json`の
  `reference_points`）から出す。
  複数termの組み合わせ・他軸参照は参考点の対応が取れないため対象外
  （`AxisScoringSection.tsx: primaryMaterial`）。参考点の生値を折れ点の横軸の値（重みと前処理を当てた値）へ
  写すのも、その点数も、backendの軽い口（`preview-scores`の`material_points`）が返す。届くまではボタンと表を
  出さない。
- `BreakpointCurveEditor`（`BreakpointCurveEditor.tsx`）: SVGでbreakpointsをドラッグ・
  矢印キー調整できる曲線プレビュー。
  同じ`draft.breakpoints` stateを数値入力行と共有し、常に同期する。`referenceRange`
  （参考点の値域）があればその範囲＋10%余白へ横軸を固定する——参考点が無い材料
  （`referenceRange`がundefined）はbreakpoints自体の値から自動スケールする。目盛り線・ドラッグ中の値ラベル
  （フォーカス中の点の上に表示）・矢印キーでの微調整（Shift併用で10倍刻み）を持つ。
- `SliderNumberField`（`AxisFormFields.tsx`）: 係数・スコアをスライダー（大まかな目安）＋数値入力（正確な値）の
  組み合わせで編集する。スライダーの範囲は材料ごとに大きく異なる値の目安にすぎず、
  範囲外の値は数値入力欄から直接指定できる。
- 数値の入力欄は共通部品`ui/NumberInput`（`commitOn="input"`）: `SliderNumberField`の数値欄・既定重み・
  折れ点の入力値/スコア・地図の色分けしきい値が使う。入力途中の文字（「-」・末尾の小数点等）は部品が持ち、
  数として読めた時点でだけ親へ渡す——素の`onChange={e => onChange(Number(e.target.value))}`では
  `Number("-")===NaN`により入力途中の「-」が消え、負数を打てない。折れ点はグラフを見ながら動かすため、
  打つたびに渡す（走行条件の速度は欄を離れたとき・Enterで渡す`commit`）。欄を選ぶと中身を全選択する（1回で上書きできる）。

### categorical材料の値入力

選択した材料のdtypeで表示を切り替える:
- `dtype="boolean"`: 該当時(true)/非該当時(false)の2スコア入力。
- `dtype="categorical"`（例: highway/surface/smoothness）: 値ごとのスコア行。
  `useMaterialValues(materialId)`が`GET /api/admin/material-catalog/{id}/values`から実データ値
  一覧を取得できた場合、値は読み取り専用の候補選択（自由入力を許さない——タイプミスが
  「静かに一致しない行」として残る落とし穴を防ぐため）になる。候補一覧が空の材料
  だけ自由テキスト入力のまま。

## MaterialCoveragePanel.tsx（「材料」タブ）

backend `GET /api/admin/material-catalog/coverage`の
レスポンス（`MaterialCoverageResponse`、生成型）をそのまま表にする。

- 「欠損時の扱い」（`missing_semantics`）でグループに分けて表示する。見出し・説明・並びは
  backendの宣言（`domain/material_catalog.py: MISSING_SEMANTICS_DISPLAY`、生成物`vocabulary.ts`）。例:
  「評価に影響する欠損」（欠損区間ではその材料を使う軸が評価対象外）と「タグ不在を確定値として
  評価する材料（参考）」（欠損は「該当なし」を意味し評価に穴は開かない）。欠損割合の数字が同じでも
  意味が正反対のため同じ表へ並べない。各グループは`<section aria-label>`で、見出し＋1行の説明＋表。
  行は欠損割合の降順（`sortByMissingRatioDesc`）。宣言が「評価に効かない」とする扱いの行は
  `data-affects-evaluation`属性でバーの色を落とす（画面は扱いの値そのものを持たない）。
- 表の列は材料（論理名 - 物理名）・母集団（Way/Edge）・欠損割合の3列。欠損割合セルは
  数値＋バーの下に「欠損 / 総数」を小さく重ねる（材料名が2行に折り返す高さを使い、
  スマホ幅でも横スクロールなしで収める）。欠損の判定根拠（`source`）は材料セルの名前の下に小さく出す
  （`title`はスマホで出ない）。
- 母集団の定義・件数ベースであること・判定根拠の見方といった補足は、見出し脇の(i)
  （`components/ui/InfoPopover`、`AxisComposer`の材料説明と
  同じ見た目）へ畳み、常時表示の説明文は各グループ1行だけにする。
- 集計対象外の材料（`kind: "excluded"`。件数を持たず理由だけを持つ）は表に含めず、`<details>`の折りたたみ一覧へ
  理由つきで出す。
- 集計のカードは`ReportCard`（下記「集計のカード」）。母数としてWay・Edgeの総数を集計の時刻の前に出す。

## 集計のカード（`ReportCard.tsx`）

材料の欠損割合・派生データ鮮度台帳・本番DBの状態は、どれもDB全体の走査を伴う集計なので、タブを開いたとき
自動では実行せず「集計する」ボタン押下時のみ実行する。その骨格（見出し・ⓘ・ボタン・集計中と失敗の表示・集計の
時刻）を`ReportCard`が1つで持ち、各パネルは取得の関数と中身の描画だけを渡す。認証情報の入力欄は持たない
（`/admin`のBasic認証セッションを転送の口経由で再利用する）。時点は日本時間で出す（`lib/time.ts`）。

**画面の説明はⓘ（`InfoPopover`）の奥に置き、ベタ書きしない**（design-principles.md
「冗長なものは削る」。読むのは1度きりなのに場所は常に取り続ける）。集計前はボタンだけを出す
——押すまで一覧は無いため、そこに無いものの説明を先に読ませない。

## DerivedDataFreshnessPanel.tsx（「データ保守」タブ）

backend `GET /api/admin/derived-data/freshness`の
レスポンス（`DerivedDataFreshnessResponse`、生成型）をそのまま一覧にする。
`MaterialCoveragePanel`（完成度、値がNULL/未取得か）とは別の切り口——派生を作った生データの取込が、
ソースごとに成功した最新の取込より古いままではないか、派生の表を作ったときの列が今の宣言の列と違わないか、
という鮮度を見る。

- 集計後の先頭に**作り直しが要る件数と、作り直しの手順の在り処**（`docs/conventions/deployment-sync.md`
  「派生データの作り直し」）を置く。**行ごとにバッチ名を散らさない**——古い理由がどれであっても利用者が
  打つのは同じ1コマンドのため。本番で打つ形（本番VMのパス・コンテナ名）は運用の知識なので画面に持たない。
- 一覧はソースの鮮度（取込の世代比較）と、表の列の比較を**同じ見た目の1行**へ揃え、「取込」と「派生の表」の
  2つのまとまりに並べる（`sourceRows`がソースごとの`sources`を、`tableRows`が表ごとの`tables`を
  `StatusRowList.tsx: StatusRow`へ写す）。読み手が知りたいのは「作り直しが要るか」で
  あり、判定方式の違いは開いた先に書けばよい。run番号・足した／消した列・判定の但し書きは
  `<details>`の中で、タップしたときだけ出す。列ごとの値なしの件数も開いた先に参考として出し、判定には
  使わない（作り直した後の値なしは作り直しでは埋まらない。[静的道路属性](../backend/static-road-attributes.md)「派生データ鮮度台帳」）。
- **表（`<table>`）を使わない。** 列を横に並べるとモバイルでは横スクロールの中へ数字が隠れ、
  「比較対象」の列だけが見える状態になる。ラベルと値を縦に積み、値だけが折り返す形にする。
- 対象の表と列はbackendがORMの宣言から導き（`infrastructure/derived_data_freshness.py:
  derived_tables`）、frontendは返ってきた行を並べるだけで対象を手書きしない。
- 描画は`FreshnessReportView`（レポートを受け取る）として取得と分けてある。認証の要る画面を
  通さずに見え方を確かめられるようにするため。

## DbStatusPanel.tsx（「データ保守」タブ・本番DBの状態）

`GET /api/admin/db-status`を呼び、取込runの最終実行・テーブルの実数と容量・統計とVACUUMの
鮮度・接続の状態を出す。`DerivedDataFreshnessPanel`と同じ形（集計のカード`ReportCard`、1件1行の
`StatusRowList`、数字は開いた先）にする。

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

backend `POST /api/admin/basemap/refresh`を呼び、
サーバーが持つタイルのファイルキャッシュ（`tile_cache`。基礎地図のプロキシ結果と
路面・事故・POIのベクタタイルが同じ場所を共有する）を全消去する。
`DerivedDataFreshnessPanel`が「古いかどうかを見る」のに対し、こちらは「古いものを捨てる」
操作側のため同じタブに並べる。

影響は押した人だけでなく**全利用者**に及ぶ（次のタイル要求で作り直されるまで、外部
サービスへの実問い合わせやタイル生成が走る）。この操作が管理API認可境界の内側にしか
入口を持たないことが、`/`側の「地図の表示を再描画」ボタン（押した人の地図インスタンス
だけを組み直す純粋なクライアント操作）と分かれている理由。押しても管理者自身の画面は
変わらない（この画面は地図を持たない）ため、消したこと自体と、各利用者へ反映されるのが
既存タイルの`Cache-Control`が切れた後であることを結果表示で伝える（基礎地図の時間は生成物`refresh-intervals.json`の
`basemap_browser_cache_seconds`。backendの`api/cache_policy.py: BASEMAP`から出る）。

## 材料説明ポップオーバー

`InfoPopoverButton`/`MaterialInfoButton`（`AxisFormFields.tsx`）が、材料選択欄の隣に
(ⓘ)アイコンを置き、backend `domain/material_catalog.py: MaterialSpec.description`をポップオーバー
表示する。外枠（開閉state・Radix Popover・開閉に追随するアクセシブル名）は共通部品
`components/ui/InfoPopover/InfoPopover.tsx`が持ち、ここはラベル文言を持たない小型トリガーとしての薄いラッパー。
見た目は共通部品（`ui/Button`の`info`・`ui/Popover`の`note`）が持つ。

## useMaterialValues.ts（材料の実データ値hook）

材料の一覧そのものは取得しない（`lib/axisMaterialsCatalog.ts: MATERIAL_CATALOG`が生成物から作る）。
実行時に取るのは、実データを読まないと答えられない値の一覧だけ。

| フック | 取得先 | フォールバック | 取得成功かつ0件のとき |
|---|---|---|---|
| `useMaterialValues(materialId)` | `GET /api/admin/material-catalog/{id}/values` | 持たない（実データ値一覧はコード側で妥当な代替を用意できないため） | 空配列（＝呼び出し側は自由テキスト入力へフォールバック） |

**暗黙の前提**: `useMaterialValues`は材料idを取得のキーにするため、propが変わった直後のレンダーから
その材料の値（未取得なら空配列）を返し、前の材料の値一覧を一瞬でも引きずらない。前の値を残す指定
（`placeholderData`）を足すと、この約束が崩れる。

## axisIconPalette.tsx（軸のアイコン）

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
地図の凡例と同じ`mapColorLegend.ts: buildRangeLegendBands`を通し（レンジの数字は入力した目盛りで書く。
地図の凡例は軸カタログの`map_paint.legend`の目盛りで書くため、得点で書く軸では数字が違う）、色は親（`AxisStudio`）が
軸カタログの分類から決めて渡す（どちらも地図と同じ`bandColorsFor`で、値の種類は軸カタログの
`map_paint.value.kind`。[地図: 軸・ルート色分け](map-axis-coloring.md)参照）。**軸スタジオ側は
「その軸がどちらの経路で地図に出るか」の判定を持たない**——カタログの実際の分類を引くため、
プレビューの色と地図の色がずれない。地図に出る経路がまだ無い軸（下書き等）は色を持たず、
その旨を注記する。

**地図では段にならない値は、入力欄のすぐ下で名指しする**（「地図では効かない: 12」、理由は
ⓘの奥）。点数の決め方で1つ手前の境界と同じ点数になる値は、地図が段を作らない
（[backend](../backend/axis-studio.md)「折れ線が同じスコアへ写す境界は落とす」）。
**判定はbackendに問い、画面は規則を持たない**——`AxisComposer`が下書きの`shape`・
`priority_overrides`・しきい値を`useMapBandsOfThresholds`へ渡し、結果を節へpropで渡す。
点数の決め方を変えても判定し直すよう、問い合わせのキーには`shape`も含める。取得に失敗した
ときは印を出さない（判定できないことを「効かない値がある」と取り違えさせない）。
段階プレビュー（見出しの「N段階になります」と並び）も同じ判定の結果から、地図が段として
作る境界だけで描く（`axisDraft.ts: thresholdsKeptOnMap`。入力からbackendが返した値を除く
だけ）——印だけ出して段数を入力どおりに数えると、見出しと地図の凡例の段数が食い違う。
判定の結果が届くまでの間は、入力どおりの段で出る。判定の取得に失敗したときも入力どおりの段で出し、そのことを
プレビューに添える（地図の段はそれより少ないことがある——黙って入力どおりに出すと、地図と同じ段だと読める）。
体感ラベルも同じ応答の`bands_on_map`（地図の各段に当たる入力の段の番号）で引き直してから
プレビューへ添え（`axisDraft.ts: bandLabelsOnMap`。番号で引くだけ）、地図に出ない段のラベル
欄には「地図には出ない」と印を付ける——地図は落ちた境界でまとまった段に下側の段のラベルを
当てるため（[backend](../backend/axis-studio.md)「段が落ちても、体感ラベルは地図の段へ
引き直して配る」）、上側の段に付けたラベルは地図のどこにも出ない。黙って消えると、付けた
ラベルが出ない理由を利用者が辿れない。
- **`category`は編集欄を持たない素通しフィールド**（`PASSTHROUGH_PAYLOAD_KEYS`）。新規
  作成時だけ`"推定"`になり、既存軸は既存の値をそのまま送り返す（観測/動的は材料側の性質で、
  材料を組み合わせて判定式を作る軸スタジオの仕組みからは生み出せないため、新規は推定で
  よい）。**編集欄を持たないフィールドを定数で作り直さない**——公開済み軸のPUTは
  「表示専用フィールドだけの差分」しか通らない（backend:
  `domain/axis_definitions.py: is_cosmetic_only_update`）ため、画面に無い値を1つでも
  書き換えると、何も変えていないのに保存が拒否される。
  **この往復を検査するテストは、素通しの項目がすべて新規の値と違う軸を置き、そのことを
  同じテストの中で確かめる**——フォームの初期値と一致する軸だけを置くと、素通しフィールドが
  書き換わっていても差分が出ず、検査が素通りする。比べる項目はbackendの契約
  （`AxisDefinitionPayload`の全項目）から取る。

## backend側との対応

frontendのこの画面は、backendの[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)が
定義する`AxisDefinitionPayload`のバリデーション規則（display_thresholds_overrideの
昇順・shape.breakpointsのx昇順・材料/軸参照の既知性等）を写さない。backendは検証の文を利用者が読める
日本語で返し（`axis_definitions.py: axis_error`。`ValueError`だと「Value error, 」の前置きが付く）、
画面は保存の誤りとしてそのまま出す。写すと、backendの条件を変えたとき画面だけが古い条件で止める。
