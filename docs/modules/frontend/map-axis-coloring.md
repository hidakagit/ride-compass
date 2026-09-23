# 地図: 軸・ルート色分け（frontend）

## 責務

評価軸（軸スタジオ管理）のdifficulty値を、(1) ルート確定前は視界内の全道路（評価軸
グループの線、風・勾配とも）、(2) ルート確定後は選択中ルートの線、それぞれ地図上で
色分け表示する。専用のフィーチャー→値配信レイヤー
（[動的材料・フィーチャー値配信（backend）](../backend/dynamic-way-values.md)）を持つ軸
（現状: 風・勾配）が対象。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/routeStyleModes.ts` | ルート確定後の色分けモード一覧・色式 |
| `Map/dedicatedWayValueLayer.ts` | ルート確定前の評価軸グループ線（専用way値レイヤー、風・勾配共通）の色式・凡例・feature-stateキー。軸カタログの表示宣言（`DedicatedWayValueDisplay`）だけから組み立て、軸ごとのファイル・定数を持たない |
| `Map/valueScale.ts` | 地図表示値の種類（`MapValueKind`: 難易度／符号付き材料）ごとの既定しきい値・配色、HSL補間、段階分け色式。ルート前後の色分けが共有する葉モジュール |
| `Map/dynamicWayValues.ts` | タイル座標計算・複数タイル応答の統合（材料非依存の共通部分） |
| `Map/axisLayers.ts` | `rampColorForBand`/`COLOR_UNKNOWN`（ramp軸の共有色ヘルパー）。ramp軸自体の全面的な生成ロジックは主に[地図: 静的レイヤー・道路表示](static-map-layers.md)の管轄 |
| `Map/__fixtures__/catalogAxes.ts` | 軸カタログの変換関数へ渡す合成入力（テスト専用）。**実際の公開軸を入力に使わない**——公開軸はDBが持ち軸スタジオで増減するため、実物を当てにすると変換の正しさではなく「いま何が公開されているか」を検証するテストになる |
| `Map/mapColorLegend.ts` | 地図上の色分け凡例（`MapColorLegendBand`型・`buildRangeLegendBands`・`rangeStepLabel`）の共通ロジック。`dedicatedWayValueLegend`が使う |
| `components/LensControl/LensControl.tsx` | レンズ（地図を何で塗るか）の唯一の入口。地図上部中央のピルが現在のレンズと凡例を示し、タップで単一選択の一覧（なし／総合難易度／評価に使用中の軸／未使用の軸）と「ルート後も周囲の道路を薄く塗る」トグルを開く（`page.tsx`が選択肢・凡例を組み立てる） |
| `Map/mapLayers.ts` | `isAxisStudioLayer`（レイヤーID判定） |
| `Map/MapView.tsx`（専用way値配信軸/DETAIL_LAYER_ID関連箇所のみ） | MapLibreへの実際の配線——ensure/apply関数群・setFeatureState反映・effect分割 |
| `features/map/scene/groups/routes.ts` | 色分け線そのものを引く側。レンズの配色式・凡例フィルタを受け取ってMapLibreの線レイヤーへ流す |
| `Map/axisLayers.ts`（`DedicatedWayValueAxis`関連のみ） | 軸カタログ→専用way値配信軸一覧の変換（`dedicatedWayValueAxesFromCatalogAxes`）とレイヤーIDの導出（`dedicatedWayValueMapLayerId`/`dedicatedWayValueLineLayerId`） |
| `hooks/useDedicatedWayValues.ts` | フェッチ・状態管理（viewportデバウンス＋タイル単位取得、全軸を1つのフックで賄う） |
| `services/axisAdminApi.ts`・`regionApi.ts`（`fetchDynamicWayValues`のみ） | backend APIラッパー |

**`MapView.tsx`は路面タイル・動的気象（降水/風の矢印/雷/竜巻）・POI等のロジックも持つ
ファイルで、それらは[地図: 静的レイヤー・道路表示](static-map-layers.md)・
[地図: 動的気象レイヤー](dynamic-weather-layers.md)の管轄。本ドキュメントは専用way値
配信軸/ルート確定後の色分け（DETAIL_LAYER_ID）に関わる箇所のみを扱う。**

## ルート確定前後で同じスケール（表示は複数、表示宣言は1つ）

```
ルート確定前  ── 評価軸グループ（線） ───────┐
              （useDedicatedWayValues、    │
               backendが軸定義で評価した   ▼
               地図表示値）        同じ表示宣言（種類・単位・しきい値・段階ラベル）
                                            ▲
ルート確定後  ── RouteSegmentDetailの ──────┘
              axis_difficulties /
              符号付き材料の直読み
```

軸ごとに地図が塗る値の種類はbackendが軸定義から決める（`GET /api/axis-catalog`の
`map_value_kind`/`map_value_unit`、[動的材料・フィーチャー値配信（backend）](../backend/dynamic-way-values.md)
参照）。`difficulty`の軸はルート前（専用way値レイヤー）もルート後（ルート線）も
軸スタジオのbreakpointsで評価済みの0〜100を塗り、`signed_material`の軸（勾配）は
どちらも符号付き材料生値を塗る。

**段階の境界は`map_value_thresholds`（`GET /api/axis-catalog`）だけを使う。**
`display_thresholds_override`は軸スタジオが編集した生値で、スケールは軸がramp表示を持つかで
変わる——ramp軸ではタイルの材料値を重み付き和にしたスケール（`buildAxisRampValueExpression`が
組み立てる値、ルート前の`display.thresholds`が使う側）であり、難易度と直接は比べられない。
backend（`domain/dynamic_way_values.py: map_value_thresholds`）が軸の折れ線で写してから返すため、
フロントはスケールの判断を持たない。折れ線が飽和する範囲へ置かれた境界は同じスコアへ写り、
その分だけ段階が減る。

## 軸id→振る舞いの判定（データ駆動、axis_idのハードコード比較を使わない）

| 判定 | 使う軸データ属性 | 関数・場所 |
|---|---|---|
| 専用のフィーチャー配信レイヤーを持つか | `AxisDefinition.dedicated_way_value_layer` | `axisLayers.ts: dedicatedWayValueAxesFromCatalogAxes`が抽出し、`useAxisCatalog`の`dedicatedAxes`として配る |
| 地図レイヤーID・MapLibre layer id | 軸id（文字列合成） | `axisLayers.ts: dedicatedWayValueMapLayerId`（`${axisId}Axis`）・`dedicatedWayValueLineLayerId`（`region-${axisId}-axis-line`） |
| フェッチに時刻／想定速度を載せるか | `AxisCatalogEntry.dynamic_way_value_needs_time` / `_needs_speed` | `useDedicatedWayValues`（載せない入力は依存キーからも外れるため、その入力が変わっても再フェッチしない） |
| 符号付き材料を直接読むか／難易度を読むか | `AxisCatalogEntry.map_value_kind`（backend `domain/dynamic_way_values.py: map_value_kind`が`shape`から導出） | `routeStyleModes.ts: routeColorableModeFromAxis`・`dedicatedWayValueLayer.ts`（`DedicatedWayValueDisplay.kind`） |
| 凡例の単位 | `AxisCatalogEntry.map_value_unit`（材料カタログの`unit`） | 同上 |

公開軸は無条件でレンズの選択肢になる（`routeStyleModes.ts: routeStyleModesFromCatalogAxes`が
公開軸すべて＋`difficulty`（総合難易度）＋`none`（塗らない）をマップする）。重み0の軸も
選べ、`LensControl`が「未使用」バッジで示す。ルート前に塗る手段（ramp・専用配信）を
持たない軸は「ルート後のみ」バッジ付きで選べるが、ルート前は何も塗らない。

**レンズ状態は1つ**（`page.tsx: lens`、`"none" | "difficulty" | axis_id`。localStorage
キーは`ridecompass:route-style-mode`）。ルート前は全道路（ramp軸は`axisVisibility`、
専用配信は`dedicatedWayValueVisibility`。どちらもレイヤーID→booleanの汎用Recordで、
軸ごとのpropを持たない）、ルート後はルート線（`MapView`の
`routeStyleModeId`）をこの1つの値から導出する。ルート後も全道路の塗りを残すかは
`lensKeepAfterRoute`（既定ON）。レンズが軸を指していれば生成リクエストへ`lens_axis_id`を
載せ、重み0でもbackendが区間表示のため風の時変化合成（風に依存する軸の場合）・
`material_values`への当該材料の封入（`signed_material`種の軸の場合）を行う
（backend側は`axis_raw_value.py: displayed_material_ids`、[routing-engine.md](../backend/routing-engine.md)
参照）。

`map_value_kind==="signed_material"`の場合、値は`axis_difficulties[axis_id]`ではなく
`material_values`から`shape.terms[0].material`（生材料、例: `gradient_percent`）を
`["get", material, ["get", "material_values"]]`で直接読む——向き（登り/下り）は
絶対値化されたdifficultyでは表現できないため。

**タイルへ焼くのは材料タグ（生の属性）までで、重み・折れ点・段の色は実行時にブラウザの式へ
組む。** 最終値をタイルへ焼くと、軸を1本調整するたびに全域のタイルを作り直すことになる。

**材料が実行時の動的値だけの軸は、`primary_attribute_ids`が空になるのが正しい。** 空を
不備の印として扱わない——軸idの健全性は「カタログに実在するか」で見る（idを間違えても
例外にならず、材料一覧が空のまま黙って壊れる）。

## valueScale.ts（ルート前後で共有する葉モジュール）

- `valueScaleFor(kind)`: 種類ごとの既定しきい値（軸カタログの`map_value_thresholds`が
  未設定のときだけ使う）。
- `interpolateColorStops(anchors, count)`: 中継点を並べた配色の上をHSL色空間でcount色に
  均等補間する。`interpolateColors(low, high, count)`は中継点を持たない場合の別名。
  固定の色配列を持たないため、しきい値の個数が変わっても色が自動追従する。
- `bandColorsFor(kind, boundaries)`: 段階ごとの色。**ルート前の全道路の塗り・ルート後の
  ルート線・凡例がすべてこの1つの関数を通る**ため、同じ軸の同じ段階はどこでも同じ色になる。
  - 難易度: `COLOR_EASY→COLOR_HARD`の1本の補間。
  - 符号付き材料: **0を含む段階（`boundaries`から求める）を境に、下り側と上り側で別の配色を
    補間する**。一本の補間だと0付近の段階が片方の端の色へ寄り、段階を細かくするほど隣と
    見分けられなくなる。境界がすべて正／すべて負／ちょうど0を含む場合も、この判定だけで
    決まる（片側が0段階になる）。この配色は「0が最も楽で、負側は正側と質が違う」ことを
    前提にする——`signed_material`は「絶対値で評価すると宣言した軸」（backend
    `domain/dynamic_way_values.py: map_value_kind`）なので、負側も同じだけ辛い軸が必要に
    なったら配色を足すのではなく種類を増やす側になる。
- `buildSteppedColorExpression({valueExpression, kind, boundaries?, numericExpression?, loading?, hiddenBandKeys?})`:
  null→`loading`がtrueなら`COLOR_LOADING`（フェッチ進行中でまだ値を受け取っていない）、
  falseなら`COLOR_NO_DATA`（取得済みだが値が無い）。それ以外は`["step", ...]`の色式。
  `hiddenBandKeys`（凡例で非表示にした段階）の色は`COLOR_HIDDEN`（透明）にする。
  **feature-state経由の値はMapLibreの`filter`から読めない**ため、線を間引くのではなく
  透明にして下の路面レイヤーを見せる。フェッチ進行中の色だけは非表示指定があっても残す
  （「まだ来ていない」と「隠した」が区別できなくなるため）。
- `buildDedicatedWayValueOpacityExpression(valueExpression, loading?)`:
  値を受け取れなかった道は薄く、値を持つ道は濃く塗る（濃さは源泉が配る
  `mapDisplay.road.unknownOpacity`/`knownOpacity`をそのまま使い、
  地図全体の「薄い＝対象外、濃い＝分類あり」という読み方に揃える）。
  **暗黙の前提**: 値が無い道には、標高が計算されていない道と、
  勾配のように向きを指定する軸で**その向きに対して直角に近く値を示せない道**
  （backend `domain/gradient.py: effective_gradient`がNoneを返す）が同じnullとして届く。配信側が
  種類を持たないため地図では区別できない。方位を1つ指定すると後者が街区の
  半分近くを占めうるため、薄くしないと値のある道がそこへ埋もれる。
  `loading`のあいだは薄くしない——`COLOR_LOADING`が見えなくなり「取得中」と
  「対象外」の区別が付かなくなる。

## routeStyleModes.ts（ルート確定後）

- `buildRangeSteppedMode`: 境界値配列（軸カタログの`map_value_thresholds`、未設定時は
  種類ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは境界値の実際の
  数字から機械的に生成し、体感ラベルを持つ軸ではその前に添える
  （`bandLabelsForBandCount`、ルート前の凡例と同じ規則）。

  **件数が段階数と合わないラベルは添えずに捨てる。** ずらして添えると最上位の段階のラベルが
  実際より狭い範囲を指す嘘になる。飽和そのものはラベルではなく軸の較正の問題である。

**ルート確定の前と後は同じ段で塗る。** 前は材料の重み付き和を、後は0〜100の難易度を塗るが、
段の切り方は同じもので、backendが両方の目盛りで言い直して配る（`domain/axis_display.py:
axis_display_for`が前の境界を決め、`domain/dynamic_way_values.py: map_value_thresholds`が
それを軸の折れ線で写す）。**フロントはどちらも受け取った境界をそのまま使い、自分で写さない。**

同じ理由で段の識別子も前後で共通（`mapColorLegend.ts: legendBandKey`＝`step-N`、値を持たない
道の受け皿は`LEGEND_NO_DATA_KEY`）。**軸idを綴りへ混ぜない**——非表示にした段の保存先は前後で
同じ`hiddenLegendKeysByMode[軸id]`のため、別の綴りにすると隠した段がルート生成で黙って戻る
。

段の範囲を文字にするのは`mapColorLegend.ts: rangeStepLabel`だけ。**語は述語に合わせる**——
境界の判定は`>= lower`・`< upper`のため、最上位帯は「以上」であって「超」ではない。
- `DIFFICULTY_MODE`（総合難易度）だけがフロントの固定モード——特定のaxis_idに紐づかず
  全軸の重み付き合成コストそのものを表示するため、軸スタジオと同期する対象にならない。
- `NONE_MODE`（レンズなし）: ルート線を単色（候補線の非選択色）で描き、凡例を持たない。
- `DEFAULT_ROUTE_STYLE_MODE_ID`は`"difficulty"`（総合難易度）。
- **候補線からの選択**: 未選択候補の線（役割`candidateLine`、細い参考線）には透明で太い
  当たり判定（役割`candidateHit`）を重ね、押された地物の`routeId`プロパティで候補を
  切り替える（`MapViewProps.onRouteSelect`）——一覧と地図のどちらからでも選べるようにする。
  選択中候補の区間詳細（`DETAIL_HIT_LAYER_ID`）とは別のハンドラで、一般道路網向けの
  ポップアップは両方の当たり判定をガードして開かない。
- **地図上の重ね順**（`scene/groups/routes.ts`が背面から前面の順に宣言し、
  `applyMapScene`がその順へ当てる）:
  選択中候補の区間色分け線（役割`detailLine`、不透明）とその縁取り
  （役割`detailCasing`。幅は源泉の`mapDisplay.route.lineWidthsPx`/`casingWidthsPx`）・当たり判定線
  （役割`detailHit`、指の接地面ぶんの幅で透明）は、同じ候補の進行方向矢印
  （役割`arrowHalo`→`arrow`、`routeArrowIcon.ts`）より常に下に置く。
  矢印層はページ表示直後に、色分け線は最初の生成後に作られるため、作成順に任せず
  「縁取り→色分け線→当たり判定線→矢印ハロー→矢印」の順を両方の作成時に明示する。
  縁取りの色（`palette.semantic.route_casing`）はレンズ配色にも背景にも依存しない一定の暗色
  ——線の色と同系色の面レイヤー（災害・降水・標高図等）が背景に来ても輪郭が残るようにする
  ためで、比較スロット線の縁取り（役割`slotCasing`）も同じ扱い。凡例で非表示にした
  カテゴリの縁だけが残らないよう、縁取りには色分け線と同じfilterを適用する。矢印2層は
  衝突判定を無効（`icon-allow-overlap`/`icon-ignore-placement: true`）にしてある——
  MapLibreは上のレイヤーから順にシンボルを配置するため、衝突判定を有効にすると主層の矢印と
  同位置・大きめのハロー層が全て落ち、色分け線が紺系のモードでは同色の矢印が線に沈む。

- **進行方向の矢印は、本体を白・縁を濃色にする。** 区間の色分けはレンズのモードで紺・緑・赤・
  紫と変わるため、線と同系色になりうる有彩色を本体に使わない。濃色の縁が線と基礎地図の
  双方から矢印を切り離す。
- **矢印の大きさはズームに追従させる。** 画面上の固定ピクセルのままだと、拡大するほど周囲の
  道路が太く描かれる一方で矢印だけが相対的に小さくなり、目立たなくなる。

- **選択中候補のハローは、候補線より下に敷く。** ハローは「いまどれを選んでいるか」を背後から
  示すもので、候補線より前へ出すと薄い暗色が線にかぶり、レンズの配色が濁る。
- **比較スロットの線は、候補の参考線より上・選択中候補の区間色分けより下に置く。** 参考線より
  下だと候補線に埋もれて比較にならず、区間色分けより上だといま見ている候補を隠す。
- **当たり判定どうしの前後は、重なった場所で押したときにどちらが勝つかで決める。** 区間の
  当たり判定は太く（幅24px）ルート全体を覆うため、乗り換え区間の帯の当たり判定はその前面へ
  置く——後ろだと帯を一度も押せない。

## dedicatedWayValueLayer.ts（ルート確定前の評価軸グループ線）

- `DedicatedWayValueDisplay`: `{kind, unit, boundaries?, bandLabels?}`。`page.tsx`が
  `axisCatalog.axes`から`dedicatedWayValueLayer===true`の軸を横断的に抽出し、
  `mapValueKind`/`mapValueUnit`/`displayThresholdsOverride`/`displayBandLabelsOverride`から
  組み立てて`MapViewProps.dedicatedWayValueDisplays`（axisId→宣言の汎用Map）として渡す。
  未設定の軸は`DEFAULT_DEDICATED_WAY_VALUE_DISPLAY`（難易度スケール・単位なし）。
- `dedicatedWayValueFeatureStateKey(axisId)`: setFeatureStateのキー（`${axisId}Value`）。
  同じ路面タイルソースの地物へ複数の軸が値を持つため軸idごとに異なる。
- `buildDedicatedWayValueColorExpression(valueExpression, display, loading?)`: 値の取得元
  （feature-state or geojsonプロパティ）だけが呼び出し側で異なる共通ロジック。評価軸
  グループ（`dedicatedWayValueColorExpression`、feature-state経由）が使う。値の取得元を
  引数に取る形のまま残してあり、feature-state以外から値を読む呼び出し側を足せる。`loading`は`buildSteppedColorExpression`へそのまま渡す（後述）。
- `dedicatedWayValueLegend(display)`: 同じ配色・しきい値から地図上の凡例
  （`mapColorLegend.ts: MapColorLegendBand[]`）を組み立てる。段階ラベル（軸スタジオの
  `display_band_labels_override`）は`mapColorLegend.ts: bandLabelsForBandCount`が
  「件数が段階数と一致する間だけ」に絞ってから数値レンジの前に添える——**ルート後の凡例も
  同じ関数を使う**（後述の`routeStyleModes.ts`）。単位は`display.unit`（難易度は空文字）。
  `page.tsx`が現在のレンズに応じて凡例を1つ組み立てる（`lensLegend`: ルート後はルート線
  モードの凡例、ルート前はramp軸なら`axisLayers.ts: buildAxisRampLegend`、専用配信軸なら
  この関数）。`LensControl`（`components/LensControl/`）が地図上部中央のピルとポップオーバーに
  表示する（モバイルのBottomSheetが画面下側を覆っても隠れないための配置）。
  `MapColorLegendBand`は`{key, label, color}`で、MapLibreのfilter述語を持たない
  （専用way値レイヤーの段階はfilterでは絞り込めないため。上記`valueScale.ts`参照）。

### 段階の表示ON/OFF（凡例のチェック）

保存先はレンズを問わず`page.tsx: hiddenLegendKeysByMode[軸id]`1箇所で、地図上チップの
▶パネルの絞り込み・「絞り込みをすべて解除する」もこの同じ場所を読み書きする。段階キーは
`mapColorLegend.ts: legendBandKey`/`LEGEND_NO_DATA_KEY`が唯一の出どころで、ルート前と
ルート後が同じキーを使う——**ルート生成をまたいでも同じ段階が隠れたまま**になる
（専用way値配信軸の場合。ramp軸はルート前とルート後で塗る値のスケール自体が違うため、
ramp凡例側のキー[`${axisId}-${index}`]と別になる）。効かせ方だけがレンズの種類で異なる。

| レンズ | ルート確定前 | ルート確定後 |
|---|---|---|
| 専用way値配信軸 | 色式で透明にする（`dedicatedWayValueHiddenBands`→`scene/groups/axisLines.ts`） | ルート線モードのfilter（`hiddenRouteLegendKeys`） |
| ramp軸 | タイルのプロパティへのfilter（`staticFilterAxes`経由、[静的レイヤー](static-map-layers.md)） | 同上 |

## useDedicatedWayValues.ts（フェッチ・状態管理）

viewportをデバウンス（500ms）してから、表示中のタイル範囲ぶんをまとめて1回の
リクエストで取得する（パン・ズームのたびに個別の道路を都度問い合わせない）。
**`bearingDeg`（走行方位）もviewportと同じ500msでデバウンスする**——コンパススライダー
（`WindBearingSlider`）はドラッグ中`onChange`を連続発火するため、素の値を依存配列に
入れるとドラッグ1回で「可視タイル数×連続イベント数」ぶんのfetchが発生してしまうため。
`speedKmh`（想定速度、入力欄）も同じ理由でデバウンスする。

**取得対象の軸は配列で受け取り、1つのフックが全軸ぶんを賄う**。Reactのフック規則により
実行時に増減しうる軸の件数だけフックを呼ぶことはできないため、軸ごとのインスタンス化は
しない。`axes`は呼び出し側がuseMemoで安定した参照を渡す契約（依存配列に直接入る）。
対象が0件の間はfetchせず結果も空へ戻す。

戻り値は`ReadonlyMap<axisId, DedicatedWayValuesResult>`で、`dedicatedWayValuesFor(results,
axisId)`が未取得・対象外の軸を空の結果へ倒して読み出す。1軸ぶんの結果は5種類:

- `values: ReadonlyMap<string, number>`（feature_key→値、複数タイル統合済み）——評価軸
  グループの`setFeatureState`にそのまま使える。**鍵は文字列のまま保つ**——路面タイルの
  `feature_key`はズームによってway_idにもedge_idにもなり（backendの`EDGE_UNIT_MIN_ZOOM`）、
  数値へ変換するとedge_idがNaNへ潰れて色が一切付かない。
- `loading: boolean`（現在のビューポートぶんのフェッチが進行中か）——
  `values`は古い値をそのまま残す設計（パン・ズームで一部の鍵が最新の応答に含まれなく
  なっても明示的に消さない）ため、`loading`だけを見て「まだ一度も値を受け取っていない
  wayが読込中なのか、取得済みだが値が無いのか」を呼び出し側（`valueScale.ts`の
  `COLOR_LOADING`/`COLOR_NO_DATA`）が判定する。
- `error: boolean`（直近に完了したフェッチで、いずれかのタイルの取得が通信失敗したか）——
  `fetchDynamicWayValues`の`DynamicWayValuesResult.error`をタイル横断でOR集約する。
  backendが正常応答で空オブジェクトを返した場合（対象範囲に本当に道路が無い）は
  `false`のまま。地図の色分け自体は「取得失敗」と「本当に空」のどちらも同じ無彩色
  （`COLOR_NO_DATA`）になり見分けが付かないため、`page.tsx`が`lens`が
  専用way値配信軸を指す間だけ`error`/`loading`/`values`の有無から
  `deriveFetchLayerStatus`（`mapLayers.ts`、動的気象レイヤーと共有する判定関数）で
  `LayerDataStatus`を1つ算出し、`LensControl`のピルへ小さな状態ドット（`LayerChip`と
  同じ視覚表現）として表示し、その意味をポップオーバーの見出しの下へ文として出す
  （`title`はスマホで出ないため）。取得失敗の原因（429・通信エラー）は`error: boolean`へ
  畳むため区別しない（[ページ全体構成](page-composition.md)「失敗・空・待ちの伝え方」）。判定には`hasFetched`（一度でも取得を試みて完了したか）も
  渡す——`"empty"`（「この範囲に表示できるデータがありません」）は「読込済みだが値なし」
  だけを指し、まだ取りに行っていない状態はどの`LayerDataStatus`にも当てはめない。
- `hasFetched: boolean`（上記の判定に使う）。フェッチを止めた（`enabled=false`になった）
  時点で`false`へ戻る——`true`のまま残すと、レイヤーを消しただけの状態が
  「取りに行った結果、値が無かった」として扱われる。

**軸ごとの再フェッチ判定**: 軸id・その軸へ載せるクエリパラメータ（`needsTime`なら時刻、
`needsSpeed`なら想定速度）・向き・対象タイル集合からリクエストキーを作り、キーが変わって
いない軸は再フェッチしない。時刻に依存しない軸（勾配）は時刻スライダーを動かしても
キーが変わらないため、風だけが再取得される。連続する呼び出しの間に古いリクエストが後から
解決しても新しい結果を上書きしないよう、リクエストの世代（`seq`、複数タイルの
`Promise.all`をまたぐカウンタ）で最新のものだけを反映する。

## MapView.tsx側の配線

`dedicatedWayValueLayer.ts`が組み立てる色式（純粋なMapLibre expression）は、
それ自体では地図に何も描かない。実際の地図反映は`MapView.tsx`側の以下の機構が担う。

```
page.tsx
  ├─ dedicatedFetchAxes = [レンズが指す専用配信軸]
  ├─ useDedicatedWayValues(dedicatedFetchAxes, viewport, travelBearingDeg, targetTime, assumedSpeedKmh)
  │     → ReadonlyMap<axisId, {values, loading, error, hasFetched}>
  ├─ dedicatedWayValues        = そのMapのvaluesだけを写したMap<axisId, Map<wayId, value>>
  ├─ dedicatedWayValueLoading  = 同じくloadingだけを写したMap<axisId, boolean>
  ▼
<MapView dedicatedWayValues={...} dedicatedWayValueLoading={...} .../>
  ├─ buildStaticOverlayLayers(..., dedicatedAxes, ...)がdedicatedAxesをmapし、軸ごとに
  │     makeEnsureDedicatedWayValueLayer(layerId, colorExpression)（色式はdedicatedWayValueDisplays・
  │     dedicatedWayValueLoadingから）
  │     → 各軸の線レイヤーをroad_surfaceタイルの独立レイヤーとして初回のみ追加
  │       （ensureRoadSurfaceTileLayerが先にpromoteId付きsourceを用意している前提）
  ├─ dedicatedWayValuesのエントリを1つのeffectでループし、各軸へ
  │   applyAxisFeatureStateValues(map, dedicatedWayValueFeatureStateKey(axisId), values)
  │     → map.setFeatureState({source, sourceLayer, id: wayId}, {[key]: value}) を全way分実行
  └─ clearRoadTileFeatureState(map)
        → dedicatedWayValueVisibilityの値がすべてfalseへ揃った瞬間、setFeatureStateした
          全道路ぶんの値を明示的にクリアする1つのeffectに統合されている
          （`map.removeFeatureState`はsource/sourceLayer単位で全キーを一括で消す
          MapLibre仕様のため、いずれか1軸だけがOFFになった時点でクリアすると
          まだONの軸の色分けまで巻き添えで消える。全てfalseになるまで待つガードで防ぐ。
          いまは`applyMapScene.ts: applyFeatureStates`が、宣言の差だけを当てる
          汎用の形で持つ——軸を名指しせず、前回の宣言に在って今回無いものを消す）
```

- `promoteId: { [ROAD_TILE_SOURCE_LAYER]: "feature_key" }`（`ensureRoadSurfaceTileLayer`）が
  MVTフィーチャーへ安定したidを持たせる前提条件——これが無いと`setFeatureState`が使えない。
  **`osm_way_id`では代用できない**（タイルのフィーチャーはズームによってway丸ごとにも
  区間にもなり、`feature_key`だけがその単位に追従する）。ここを取り違えても例外も警告も
  出ず、ただ色が付かなくなるだけのため、`MapView.state.contract.test.ts`が固定している。
- 専用way値配信軸の線は、路面本体と同じ`ROAD_LINE_SOURCE_ID`/`ROAD_TILE_SOURCE_LAYER`を
  共有する独立レイヤーとして宣言される（`tunnel`/`oneway`と同型の構成）。
- `dedicatedWayValues`はパン・ズームのたびに変わりうる値のため、「表示ON/OFF」を担う
  一括の適用（宣言から組んだシーンを当てる経路）とは別に、値だけをfeature-stateで反映する
  （無関係な再実行を避けるため）。
- **`map.setStyle()`（「地図の表示を再描画」ボタン経由のスタイル取り直し）は
  カスタムレイヤーを全て消すため、`redrawAllLayers`が全レイヤーを再構築する。この際
  `dedicatedWayValues`の値自体は変わっていないため通常の依存effectは再実行されないが、
  `redrawAllLayers`が`applyAxisFeatureStateValues`を明示的に再呼び出しすることで、
  setStyle直後に評価軸レイヤーが無色のまま残る事故を防いでいる**（暗黙の前提:
  この明示的な再適用を忘れると、setStyle後は視覚的にレイヤー自体は存在するが完全に無色の
  ままになる）。

`dedicatedWayValues`は`MapViewProps`上、`ReadonlyMap<axisId, ReadonlyMap<wayId, value>>`
という1つの汎用propにまとまっている（`dedicatedWayValueDisplays`・`dedicatedWayValueLoading`
（`ReadonlyMap<axisId, boolean>`）と同じく、design-principles.md構造仕様3
「軸ごとにpropを新設しない」に沿う）。`useDedicatedWayValues`も軸の配列を受け取る1つの
フックで、軸ごとのフック呼び出しを持たない（Reactのフック規則により、実行時に増減しうる
軸の件数だけフックを呼ぶことはできないため）。feature-stateキーは
`dedicatedWayValueFeatureStateKey(axisId)`で軸idから機械的に導出するため、軸ごとの対応表は
持たない。

## 動的気象レイヤーとの関係

`dedicatedWayValueLayer.ts`が扱う「評価軸グループ」（道路そのものを線で塗る）は、
`windVector`（矢印表示、環境グループの探索用表現）とは完全に独立した見せ方であり、
同じ`[時刻/向き]`入力を共有するだけで、レイヤー・ソース・フェッチ経路はすべて別individual。
[地図: 動的気象レイヤー](dynamic-weather-layers.md)が扱う`DYNAMIC_WEATHER_RENDERERS`汎用機構
（風の矢印・降水ナウキャスト等）とは異なり、専用way値配信軸は`mapLayers.ts:
isAxisStudioLayer`により地図上チップ（`MapOverlayControls.tsx`）に一切現れない。表示ON/OFFの起動導線は地図上部中央の
`LensControl`のみが持つ（本ファイル冒頭「対象ファイル」参照）。

## 3件目の軸を公開したときに自動で追従する範囲

`dedicated_way_value_layer=true`の軸を軸スタジオで公開すると、frontend側は
`useAxisCatalog`の`dedicatedAxes`経由で以下がすべて自動で増える（このモジュールの
ファイルを編集する必要は無い）。

| 追従するもの | 導出元 |
|---|---|
| `MapLayerId`・`MapLayerDescriptor`（地図UIからの除外を含む） | `buildMapLayers(rampAxes, dedicatedAxes)` |
| MapLibreの線レイヤー登録・色式と濃さの再適用 | `buildStaticOverlayLayers(..., dedicatedAxes, ...)` |
| 表示ON/OFF（レンズ選択） | `page.tsx: dedicatedWayValueVisibility` |
| way値のフェッチとクエリパラメータの取捨 | `useDedicatedWayValues` + 軸カタログの`needsTime`/`needsSpeed` |
| feature-stateキー・色式・濃さ・凡例 | `dedicatedWayValueFeatureStateKey`/`dedicatedWayValueColorExpression`/`dedicatedWayValueOpacityExpression`/`dedicatedWayValueLegend` |

**追従しないもの**: 値を組み立てるbackendのサービス本体（`_DEDICATED_WAY_VALUE_SERVICE_
FACTORIES`への登録、[dynamic-way-values.md](../backend/dynamic-way-values.md)参照）。
未登録の軸へこのフラグを立てる書き込み自体がbackendで拒否される。
