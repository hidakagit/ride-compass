# 地図: 静的レイヤー・道路表示（frontend）

## 責務

タイル焼き込み済みの静的道路属性（路面・道路種別・指定路線・トンネル・一方通行・停止
要因POI・補給休憩POI・事故）と二次(ramp)軸の汎用色分けレイヤーを地図上に表示し、チップ
（`MapOverlayControls`）から表示/絞り込みを操作する。

地図下部中央の一括操作行（`page.tsx: bottomControlRow`）は「まとめて元に戻す」操作を
並べる。**レイヤーのON/OFFと凡例の絞り込みは別の状態のため、戻す操作も別々に要る**
——同じバツ印で並べると区別できないので、対象を形で示すアイコン（重なり＋×／漏斗＋×、
`Map/icons.tsx`）を使い分ける。対象を表さない汎用のバツ印アイコンは置かない。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/staticAttributeLayers.ts` | 指定路線・トンネル・一方通行・停止要因POI・補給休憩POI・事故の色分け定義、絞り込み軸カタログ`buildStaticFilterAxes` |
| `Map/roadFilterAxes.ts` | 路面レイヤー（路面の種類=`surface`・道路の種類=`highway`）の絞り込み軸と配色。**線レイヤーで意味を運ぶのは色だけで、太さ・線種は情報を持たない**——1本の線へ複数の意味を載せると、色の意味が他方のON/OFFで入れ替わる。同時表示は並列トラックで分ける |
| `Map/legendFilter.ts` | カテゴリ絞り込みの汎用機構（凡例フィルタ式の組み立て・AND束ね・要約文生成） |
| `Map/landcoverClasses.ts` | 土地被覆のクラス（表示名・色・割合列・地図に塗るか）。backendのレジストリ由来の生成物（`landcover-classes.json`）を読むだけの薄い層で、凡例（`page.tsx`）と区間インスペクタ（`RoadInspectorPopup.tsx`）が共有する。色は地図タイルの塗りと同じ値のため、凡例と地図がずれない。**凡例は塗るクラスだけ**（`LANDCOVER_PAINTED_CLASSES`）——塗らないクラスを並べると色見本があるのに地図のどこにも無い表になる。区間インスペクタは数値なので全クラスを出す |
| `Map/primaryAttributes.ts` | 一次属性のカタログと、二次軸→一次属性の導出（軸増減時の観測データ連動表示に使用） |
| `Map/secondaryAxes.ts` | 「推定指標（合成）」チップグループの軸一覧生成（略名・対応`MapLayerId`・アイコン・パネル説明）。`show_map_icon`による除外を持つ |
| `Map/mapLayers.ts` | レイヤーカタログ本体（`MapLayerDescriptor[]`）・地図上チップの最上位グループ（`MAP_OVERLAY_GROUP_ORDER`が正本。現在は道路/環境/スポット）判定・軸スタジオ由来レイヤーの除外判定・`deriveFetchLayerStatus`（MapLibreのソースイベントを経由しないレイヤーのデータ状態判定） |
| `Map/MapView.tsx`（静的レイヤーのsource/layer初期化・並列トラック分離・下敷き表現箇所のみ） | 表示層本体 |
| `Map/mapStyleOps.ts` | 地図インスタンスへの低水準操作（レイヤーの表示切替・スタイル読み込み後の実行・面レイヤーの差し込み位置・ズーム依存のicon-size式）。このアプリのどのレイヤーかを知らないものだけを置く |
| `Map/routeArrowIcon.ts`・`icons.tsx` | ルート矢印・アイコン集（下記「本モジュールとの関係」参照） |
| `Map/popupEscape.ts` | ポップアップHTMLへOSMタグの生値を埋め込む前のエスケープ（`labelOrEscapedRaw`。対訳表に載る値は素通し、フォールバック側だけ潰す） |
| `Map/RoadInspectorPopup.tsx` | 道をクリックしたときの詳細（**Reactで描き、MapLibreのPopupへportalで差し込む**）。事実（この道の属性）を先に出し、評価は押したときだけ取りに行く（backend `POST /api/region/axis-inspector`、[静的道路属性・タイル配信](../backend/static-road-attributes.md)参照）。軸ごとの効き方は**ルート結果と同じ`AxisContributionBar`**で出す——同じものを別の見た目で見せると読み方を2つ覚えることになる。寄与度はbackendが返す値をそのまま使い、フロントで重みを掛け直さない |
| `Map/roadFacts.ts` | クリックした道の「事実」（道路名・路面・路面状態・指定路線・トンネル・橋・一方通行）をタイルのプロパティから組み立てる純関数。該当しない項目は行ごと出さない（「なし」が並ぶと該当する項目が埋もれる） |
| `types/traffic.ts` | 停止要因POI・補給休憩POIの`kind`列挙型定義 |
| `services/regionApi.ts`（`roadSurfaceTileUrl`/`poiTileUrl`/`accidentTileUrl`とタイル世代定数） | ベクタタイルのURLテンプレート（`fetchDynamicWayValues`は[地図: 軸・ルート色分け](map-axis-coloring.md)の管轄） |
| `lib/tileBaseUrl.ts` | タイル配信元オリジンの決定（既定はフロント自身のオリジン＝rewrites経由、`NEXT_PUBLIC_TILE_BASE_URL`設定時はbackend直接）。路面/POI/事故タイル・基礎地図スタイル（`MapView.tsx: mapStyleUrl`）・国土地理院色別標高図・JMA動的タイル（[動的気象レイヤー](dynamic-weather-layers.md)）が共通に使う |
| `components/MapOverlayControls/` | 地図上チップ（フローティングUI）。グループの開閉キー（`group:<グループ>`）は`MAP_OVERLAY_GROUP_ORDER`から生成・逆引きし、キー文字列を手で並べない——グループを増やしたとき見出しが「グループ本体」と認識されず2件目以降がチップ列から消えるのを防ぐ |
| `Map/LayerChip.tsx` | ON/OFFトグルの共通部品（`RouteSettingsPanel/HardFilterPanel.tsx`が使う） |
| `Map/InfoPopover.tsx` | 見出し脇の(i)アイコン→ポップオーバーという外枠の共通部品（開閉state・開閉に追随するアクセシブル名「◯◯を表示/隠す」・任意の見出し文言を含む）。中身はchildrenで呼び出し側が渡す。`RouteSettingsPanel`・`RouteAxisProfile`・`recipeControls.tsx: FieldLabel`・軸スタジオの材料説明が共用し、(i)→Popoverの組み立てを自前で持つ箇所は無い |
| `Map/LegendCheckboxList.tsx` | 凡例のチェックボックス一覧（チェックボックス+色スウォッチ+ラベル）の共通部品。リスト/行の見た目（class名）は呼び出し側が指定する（`LensControl`・`MapOverlayControls`の▶パネルで共用） |

## タイルの配信元（`lib/tileBaseUrl.ts`）

ベクタタイルはMapLibreがWeb Worker内でfetchするため、URLは常に絶対URLでなければならない
（相対パスはWorkerのベースURLで解決できない）。`tileBaseUrl()`が返すオリジンは、
`NEXT_PUBLIC_TILE_BASE_URL`が設定されていればその値（backendへ直接取りに行く。フロントの
ホスティング経由の往復を省く）、未設定ならフロント自身のオリジン（`next.config.ts`の
rewritesでbackendへプロキシ）。`window`をSSR時に参照しないよう、モジュール定数ではなく
呼び出し時に評価する関数になっている。適用範囲は路面/POI/事故のベクタタイルに限らず、
基礎地図のスタイルJSON（`MapView.tsx: mapStyleUrl`）・国土地理院色別標高図（同
`GSI_RELIEF_TILE_PATH`・`GSI_TERRAIN_TILE_PATH`）・土地被覆ラスタ（`regionApi.ts: landcoverTileUrl`）・JMA動的タイル
（`riskMap.ts`・`precipitationNowcast.ts`・`thunderNowcast.ts`のURLテンプレート）も同じ
関数でオリジンを決める。JMAの`targetTimes`
JSONやlidenのGeoJSONのようにアプリのfetch()で読む小さなデータは対象外（相対パスのまま）。

**暗黙の前提（基礎地図）**: スタイルJSON内のタイル・スプライト・グリフのURLはbackendが
`basemap_public_base_url`で書き込む（[横断基盤ではなく気象・動的レイヤー側の
`basemap_client.py`](../backend/weather-dynamic-layers.md)）。backend直接配信にする場合は
backend側の`BASEMAP_PUBLIC_BASE_URL`も同じbackendオリジンへ揃えないと、スタイルだけ
backendから取り、タイル本体はrewrites経由に戻る。

**暗黙の前提**: backend直接にすると、API呼び出し（`lib/apiBaseUrl.ts`）と同じオリジンに
タイル要求が載る。backend前段がHTTP/1.1のままだとブラウザのオリジン単位の同時接続数上限
（6本程度）をタイル要求が埋め、API呼び出しが詰まるため、HTTP/2以上（多重化）で応答できる
構成でのみ設定する（[docs/architecture.md](../../architecture.md)「同時接続数上限との競合」）。

## 表示状態の渡し方（レイヤー専用のpropを持たない）

`MapView`が受け取る静的レイヤーの表示状態は`staticLayerVisibility`
（`MapLayerId`→boolean）1つで、**レイヤーを足してもこのpropは変わらない**。
`axisVisibility`（ramp軸）・`dedicatedWayValueVisibility`（専用way値配信軸）と同じ形で、
[design-principles.md](../../design-principles.md)構造仕様3に揃えてある。

レイヤー専用のpropを増やす形だと、型宣言・分割代入・再描画対象の列挙・依存配列・可視状態の
対応表へ同じ名前を書き足すことになり、**1箇所でも忘れるとチップはONで凡例も出るのに地図には
何も出ない**（タイル要求すら飛ばないためネットワークを見ても気づけない）。

既定でONにするかも同じく記述子側の宣言（`MapLayerDescriptor.defaultOn`）で決め、
`buildDefaultLayerVisibility()`が初期値を導く。省略時はOFF——「明示的にONにして初めて出る」
が地図レイヤーの原則で、既定ONは防災級の情報という**性質**だけが根拠になる。

## 表示層の実装（`MapView.tsx`）

このモジュールが扱う静的レイヤーの実際のMapLibre実装（`addSource`/`addLayer`/
`setPaintProperty`/`setFilter`呼び出し）はすべて`MapView.tsx`にある。
`staticAttributeLayers.ts`等は色分け式・凡例の**定義**のみを持つ純粋なデータ層で、
DOM/MapLibreを一切知らない。

**面で塗るレイヤーは基礎地図の道路網より下に入る**（`mapStyleOps.ts`）。追加するときに
`type`が面（raster/fill等）なら`areaLayerAnchor`の返す位置を`beforeId`にする——判断は
`ensureLayerFromSpec`1箇所にあり、レイヤーごとに持たない。そのため下記の並び順が効くのは
**面どうし・線どうしの相対順**であって、面と線の間ではない（面をどれだけ濃くしても、
基礎地図の道路・地名とこのアプリの線レイヤーはその上に残る）。

差し込み位置は**基礎地図が道路網を描き始める最初のレイヤー**として導く。道路網は
`source-layer`が`transportation`のレイヤー群（OpenMapTilesスキーマの語彙で、基礎地図は
このスキーマのタイルを配る）で、**並び順やレイヤーidからは導かない**——スタイルの配色や
見せ方が変わってもスキーマの名前は変わらないのに対し、並び順は相関でしかない。

導出を並び順に頼ると2通りに外れる。「最後に面を描いたレイヤーの次」では、基礎地図が道路より
後ろにも面を置く（建物）ため位置が道路の後ろまで下がり、面が道路を覆ったまま残る。
「線が最も長く連なる区間の先頭」では、トンネル（`tunnel_*`）と地上の道路（`road_*`）の
境目に入り、道路網がトンネル区間だけ面の下に沈んで**道が途切れて見える**。

道路網より後ろに残る面（歩行者areaの塗り・建物）は`prepareBasemapForAreaLayers`が道路網の
手前へ動かす。動かさないと、道路の下へ潜らせた面が建物の不透明な塗りに穴を開けられる。

**暗黙の前提**: 位置を決めるのは`style.load`の時点、つまり基礎地図だけが載っている瞬間で
なければならない。後から導くと、このアプリが足した線レイヤーが最長の連なりを伸ばし、位置が
地名側へずれる。`map.setStyle()`で作り直すときは`resetBasemapAreaLayerPreparation`で
解決済みの記録を落としてから差し替える。

**暗黙の前提**: 建物を道路の手前へ動かすと、面レイヤーを1枚も出していないときの基礎地図も
「建物の上に道路」へ変わる。この地図はpitchを持たないため影響は小さい。

```
buildStaticOverlayLayers(axisOverlayLayers, dedicatedAxes,
                         dedicatedWayValueDisplays?, dedicatedWayValueLoading?)
が描画順（＝重なり順、背面→前面）を決める:

  elevation（色別標高図ラスタ）
    │
  hillshade（起伏、標高タイル→raster-dem→陰影）
    │
  landcover（土地被覆ラスタ）
    │
  axisOverlayLayers（二次ramp軸: car_stress・accident等）
    │  ← 「材料が同時に表示されているときだけ」太く半透明な下敷きにする
    │    （buildAxisOverlayLayersの第2引数casingLayerKeys）
    ▼
  designation → tunnel → oneway
    │  ← ROAD_MATERIAL_TRACK_LAYER_IDS（路面・道路の種類・指定路線・トンネル・一方通行）を
    │    line-offsetで並列トラックへ分離（applyRoadMaterialTrackOffsets）
    ▼
  専用way値配信軸（軸カタログ順、評価軸グループの線。本モジュール対象外）
    ▼
  accidents → stopPoi → supplyPoi（点データ、別ソース）
```

「道路情報」の各軸は**それぞれ独立した線レイヤー**（`ROAD_TILE_LAYER_ID`=路面の種類、
`ROAD_TYPE_LAYER_ID`=道路の種類）で、同じベクタソースを共有する。`applyRoadLayerState`は
レイヤーごとに、そのレイヤーの軸の色式・不透明度式・凡例の絞り込みだけを適用する——
**どちらの色の意味も、もう一方のON/OFFでは変わらない**。太さは全レイヤー共通の
`DEFAULT_ROAD_LINE_WIDTH`で、線種は使わない。両方ONのときは下記の並列トラックが横へ分ける。

## 起伏（陰影）の濃さ（`MapView.tsx: ensureTerrainHillshadeLayer`）

陰影は「傾きのある所だけ塗る」ため、面レイヤの規則をそのまま満たす。ただし**MapLibreの
既定のままでは、この国の平野部では出ていても気づけない**。

- 計算方法は`igor`。既定の`standard`は傾きのsinに比例して塗るため、関東平野の傾き（数度）
  では影の実効の不透明度が0.03を下回る。`igor`は傾きのarctanに比例し、同じ傾きで倍以上になる。
- **`basic`・`multidirectional`は使えない**。平坦な画素にも光を塗るため、「値のある所だけ
  塗る」を満たさない。
- 標高は`raster-dem`のcustom encodingの係数で垂直方向へ強調して読む。**タイルの値は実際の
  標高のまま**で、読み方だけを変える（mapbox encodingの係数を倍率倍したものを渡す）。倍率を
  上げるほど緩い斜面が読めるが、上げすぎると急斜面との差が潰れる。

**暗黙の前提**: 陰影の濃さはズームにも依る（MapLibreは1画素あたりの標高差から傾きを求める
ため、拡大するほど同じ斜面の濃淡が薄くなる）。倍率は広域で見るときを基準に決めている。

## スタイル取り直し後の作り直し（`redrawAllLayers`）

「地図の表示を再描画」は`map.setStyle()`でスタイル全体を差し替えるため、このアプリが
足したsource/layerは一度すべて消える。`MapView.tsx: redrawAllLayers`（モジュールレベルの
関数で、表示状態を引数で受け取る）が現在の状態から作り直す。

**暗黙の前提**: ここから辿れない描画は作り直されず、そのレイヤーは押した人の地図から
消えたまま戻らない（次にそのpropが変わるまで復旧しない）。**対象はsource/layerの追加に
限らず、filter・feature-state・visibilityで持つ表示状態も同じ**——たとえば詳細を見ている
道の強調（`applyInspectedWay`）はレイヤーのfilterとvisibilityだけで表され、ポップアップは
開いたままなので、復元しないと「どの線の話か」だけが失われる。そのため
`redrawAllLayers`は表示状態のpropに加えて`inspectedWayId`（コンポーネントのstate由来、
refで最新値を渡す）も受け取る。`scripts/review_checks.py`の`map_redraw_coverage`が、
**再描画で失われる副作用を持つ宣言**（source/layerの追加・filter・feature-state・
visibilityの設定）が`redrawAllLayers`から辿れるかを機械的に見ているため、新しい描画を
足して辿れない位置に置くとpre-commitとCIが落ちる。
カメラはここでは動かさない——表示範囲は利用者の操作に属し、フィットは候補一覧が
変わったときだけ行う。

## 並列トラック分離（`applyRoadMaterialTrackOffsets`）

同じ道路ジオメトリへ複数の独立レイヤー（路面の種類・道路の種類・指定路線・トンネル・一方通行）を
重ねて描画すると、後から描画されたレイヤーが前のレイヤーを覆い隠す。`line-offset`で
道路と平行な複数トラックへ横並びに分離することでこれを避ける——ON中のレイヤーだけを
対称に割り付ける（1件→0、2件→±1.5、3件→-3/0/+3）ため、どれかをOFFにすると残りが
自動で中央へ寄り直す。

トラック本数（`ROAD_MATERIAL_TRACK_LAYER_IDS.length`）・オフセット間隔
（`MATERIAL_TRACK_OFFSET_STEP`=2px）・1次レイヤーの太さ（`DEFAULT_ROAD_LINE_WIDTH`=3px）
から、二次軸の下敷き幅（`SECONDARY_AXIS_CASING_WIDTH`）が式として算出される。

## 二次軸の下敷き表現（`buildAxisOverlayLayers`の`casingLayerKeys`）

二次(ramp)軸は「その材料（対応する一次属性の表示レイヤー）が1つでも同時に表示されて
いるとき」だけ太く半透明な下敷きになる。材料が1つも表示されていなければ通常の太さ・
不透明度で表示する。「どの一次属性がどの二次軸の材料か」の解決は`page.tsx`が
`axisCatalog.secondaryAxes`（実行時カタログ）の`primaryAttributeIds`から行い、
`MapView.tsx`は渡された`secondaryAxisCasingLayerIds`（キー集合）をそのまま使うだけの
汎用描画係のまま保たれている。

**暗黙の前提**: 下敷きかどうかは`makeEnsureAxisRampLayer`が組み立てる**レイヤーspecの
`line-width`/`line-opacity`そのもの**として持ち、specの外から`setPaintProperty`で
上書きする形は取らない。`ensureLayerFromSpec`はレイヤーが既にあるときspecのpaintを
丸ごと再適用するため、spec外で太さを決めると、以後どこかで`ensure()`が呼ばれた時点
（`setStaticOverlayFilters`はレイヤーごとに`ensure()`を呼ぶ）にspec側の値へ無条件で
巻き戻り、材料が1つも表示されていない軸まで太く半透明のまま描かれる。この結びつきは
`MapView.layerOps.test.ts`の「レイヤー追加後にensureが再度呼ばれても下敷きの有無が
巻き戻らない」で固定してある。

**絞り込み（`filter`）はspecへ畳めない**——凡例のON/OFFという実行時の状態から
`setStaticOverlayFilters`が組み立てるもので、`ensure`側はレイヤー固有の材料関係を知らない
汎用描画係のままにしておきたい。そこで**どちらが持ち主かを呼び出し側が宣言する**
（`ensureLayerFromSpec`の`specOwnsFilter`、必須引数）。キーの有無から推測する形だと、
「自分の持ち物だが今は条件なし」と「外側が管理しているので触るな」が区別できず、後者を
前者として扱った瞬間に利用者の絞り込みが表示ON/OFFのたびに巻き戻る。

## 初期表示の覆い（`initialTilesLoading`）

最初の数秒はタイルが揃わず地図がほぼ白紙のため、`MapView`が「地図を読み込み中…」の
覆いを重ねる。外すのはMapLibreの最初の`idle`だが、**`idle`は表示中のすべての取得が
落ち着くまで来ない**——取得が終わらないソースが1つでもあると、基礎地図が描けていても
覆いが残り続け、白紙で固まったように見える。覆いの役目は最初の白紙を隠すことなので、
`idle`が来なくても`INITIAL_TILES_OVERLAY_MAX_MS`で外す。

## レイヤーのデータ取得状態（`ChipButton`/`LayerChip`共通のドット表現）

`MapOverlayControls`の`ChipButton`は、`LayerChip.tsx`と同じ`LayerDataStatus`（`mapLayers.ts`、"loading"/"empty"/"error"）を受け取り、
「表示ON かつ dataStatus が設定されている」間だけアイコン右上へ小さな状態ドットを描画する
（`on`/`active`がfalseの間は出さない）。クラス名は`LayerDataStatus`の値とそろえて
（`MapOverlayControls.module.css: .iconStatusDot_loading`等）動的に組み立てる点も
`LayerChip.module.css`側と同じ設計。

`page.tsx`の`layerDataStatus`（`overlayLayers`へ渡す値）は、
出所の異なる2つの`Partial<Record<MapLayerId, LayerDataStatus>>`をマージしたもので、
内訳は次の2系統:

- **`mapViewLayerDataStatus`**（`MapView.tsx: buildLayerDataSources`）:
  road/POI/事故/標高等、MapLibreが自身のタイル取得として実行するレイヤー。ソースイベント
  （`sourcedata`/`sourcedataloading`/`error`）から算出する。
- **`dynamicWeatherDataStatus`**（[動的気象レイヤー](dynamic-weather-layers.md)
  「データ取得状態」節参照）: 降水ナウキャスト・風・災害（雷・竜巻・落雷・キキクル4種を
  1チップへまとめたグループ）。
  実際の外部フェッチが自前のJSコード（`usePolledFetch`等）で行われ、結果を
  `map.getSource(id).setData(...)`等で流し込むだけのため、MapLibreのソースイベントは
  フェッチの待ち時間・失敗を観測できない。`buildLayerDataSources`の対象外とし、代わりに
  各要素のフェッチ自身のloading/errorから直接算出する。

両者はキーが重ならない（`buildLayerDataSources`は動的気象レイヤーを含まない）ため、
マージの優先順位を気にする必要はない。

## 「ズームインすると表示されます」の案内

ベクタタイルは配信元が決めた最小ズーム未満では要求されないため、そのズームでは
ONにしても何も塗られない。「データが無い地域」と区別できるよう案内を出す。

対象は**記述子が`tileMinZoom`を宣言したレイヤー**で、レイヤーごとの閾値も「どれが対象か」も
記述子が持つ。`MapView.tsx: handleZoom`がズームのたびに`mapLayers.ts:
tileZoomTooWideLayerIds(zoom)`を引き、結果が変わったときだけ`onTileZoomTooWideChange`で
伝える（zoomイベントは1回のピンチ操作でも何十回と飛ぶ）。`page.tsx`は受け取ったidの
チップへ`TILE_ZOOM_TOO_WIDE_SUMMARY`を出し、**凡例を空にする**——▶の中身は「凡例があれば
凡例、無ければsummary」で決まるため、凡例を出したままだと案内が一度も表示されない。

表示ON/OFFでは出し分けない。ONにする前に「いまの縮尺では出ない」と分かる方が、ONにして
から何も起きない理由を探すより早い。

**暗黙の前提**: 軸スタジオ由来のレイヤー（ramp軸・専用way値配信軸）も同じ路面タイルを
共有するため同じズームで消えるが、地図上チップを持たないため案内の出し先が無い。
レンズだけを選んだ状態でも、同じタイルを読む道路のチップ側に案内が出る。

## 最上位グルーピング（道路/環境/スポット）

`mapLayers.ts: mapOverlayGroupFor(layer)`がレイヤーIDを3グループへ分類する。
`isAxisStudioLayer`（`dedicated_way_value_layer`軸[記述子の`axisStudioLayer`が立つ]・
ramp軸[`dataNature==="composite"`]）に該当するものは`undefined`（地図上チップ・サイドバーの
どちらにも一切出さない——ルート設定パネルへ移設済み、[ページ構成](page-composition.md)参照）。

**暗黙の前提**: `mapOverlayGroupFor`は`isAxisStudioLayer`を最初にチェックしてから
`category`値を見る。`category`だけでは判別できない（例: `car_stress`の
`category="trafficSafety"`は`accidents`等と同じ値のため、`isAxisStudioLayer`のガードが
無いと誤って「スポット」グループへ紛れ込む）。

グループは表示上のまとまりだけを表し、**どのレイヤーも複数同時にONにできる**。重なって
読みにくくなった場合は、各チップの▶パネルで要素・カテゴリ単位に絞り込む（下記「凡例
カテゴリの絞り込み」節）。道路グループの線同士は`line-offset`による並行トラック
（`applyRoadMaterialTrackOffsets`）で重ならずに並ぶ。

**開いておけるグループは`MAP_OVERLAY_MAX_EXPANDED_GROUPS`件まで**（別のグループを開くと
古く開いたものから畳む。保存済みの状態にも同じ上限を効かせる——上限を下げる前に書かれた値は
保存側を直しても直らない）。開いたグループのメンバーはチップ列へ縦に積まれるため、開くほど
地図が縦に隠れる: 375×812では、すべて畳んだ状態で画面の縦の23%、1グループ開くと54%、
すべて開くと72%を占める。主用途が走行中のスマホであることを踏まえた制約で、レイヤーを足したとき
伸びるのはそのグループの中だけになり、グループが増えても上限は動かない。並べ方をレイヤー
カタログ側（`mapLayers.ts`）が決めるのは、チップ列の中身がそこから導かれるため——描画する側に
持たせると、カタログを増やした人がこの制約に気づけない。

軸スタジオ由来のレイヤー（`isAxisStudioLayer`、ramp軸・専用way値配信軸）は地図上チップにも
サイドバーにも現れず、`layerVisibility`の対象外——表示ON/OFFはレンズ（`LensControl`）が
単独で持ち、常に1つだけが選ばれる。これらは同じ道路の同じ位置をそれぞれの評価で塗り分ける
ため、重ねると後から描画した色が前の色を完全に覆い、並行トラックのように並べて見ることも
できない。

## 凡例カテゴリの絞り込み（サイドバーと地図上チップで同じ状態を共有）

`LegendFilterSummaryAxis.axisId`（`legendFilter.ts`）を持つ軸だけがユーザー操作で
絞り込める。`axisId`は非表示キーの保存先（`page.tsx: hiddenLegendKeysByMode`のキー）を
指し、地図上チップの▶パネル（`MapOverlayControls`）がこのIDの状態を書き換える。
描画には`LegendCheckboxList`を使う。

`axisId`を持たない軸は読み取り専用の凡例として描画される。配信元が色を焼き込み済みの
ラスタタイル（降水ナウキャスト・風・災害の危険度凡例）がこれにあたり、カテゴリ単位で
地物を選り分けること自体ができない。

例外として、災害チップの「表示する情報」だけは`axisId`を持ちながら地物の絞り込みではなく
**レイヤーソースの表示切替**に使う（`useDynamicWeatherLayers`が非表示キーを見て7要素の
`visible`を決める、[動的気象レイヤー](dynamic-weather-layers.md)参照）。UIとしては
他の絞り込みと同じチェックボックス行で、反映先だけが異なる。

## 路面レイヤーの絞り込み軸（`roadFilterAxes.ts`）

タイルには`surface_good`（3値正準分類、絞り込み軸としては未使用）・`surface`（OSM生タグ
正規化済み）・`highway`（道路種別）が焼き込まれている。**「路面の種類」（surface）と
「道路の種類」（highway）の2軸だけを絞り込み軸として持つ。**

色分け（line-color）は「路面の種類」がONの間は常にその配色で固定する（道路の種類の色を
上書きする形、両方ONでも色の奪い合いは起きない）。ユーザーが色分け軸を選ぶUIは持たない。

## staticAttributeLayers.ts（指定路線・トンネル・一方通行・停止要因POI・補給休憩POI・事故）

`roadFilterAxes.ts`の軸機構（複数の生タグ値を少数のグループへ束ねる）とは異なり、これらは
backendが既に1つの分類値（`kind`=列挙文字列・`tunnel`/`oneway`/`involves_bicycle`/
`fatal`=真偽値・`designation`=3値）へ変換済みのプロパティのため、生値→グループの
対応表は不要で単純な`match`/`case`式で足りる。

分類値の一覧はbackendが正で、フロントは色とラベルを与えるだけ。**backendが種別を1つ足した
のにフロントが古いままだと、その地物は`baseFilter`に弾かれて地図から完全に消える**（凡例にも
出ないため「データが無い」としか見えない）ため、停止要因POI・補給休憩POIは生成物
（`poi-kinds.json`）との照合をテストで固定する。凡例の行は種別と1対1ではない——利用者から
見て区別する意味の無い種別（車道用の踏切と歩道・自転車道用の踏切）は`CategoryDef.aliasKeys`で
1行へまとめる。色分け式・ラベル対訳表には各種別がそのまま載るため、地図の見た目と
ポップアップの語彙は種別ごとに正しく出る。

路面ポップアップ（`Map/roadFacts.ts`）の`smoothness`の値→表示名も
同じ考え方で、正本はbackendの`material_catalog.py: MaterialSpec.value_labels`。生成物
（`material-catalog.json`）から引く（手書きで持つと、同じ値を地図のポップアップと
軸スタジオで別の呼び方をすることになる）。

道路名（OSMの`name`/`ref`）は**対訳表を持たない固有名詞**のため、この経路には乗らない。
`escapeHtml`を通して先頭行へ出す（どの道かを決める情報で、路面・属性はその道の性質）。
片方だけ持つwayが多いため、両方あるときだけ1行へ畳む。

| レイヤー | ソース | 独立/共有 |
|---|---|---|
| 指定路線・トンネル・一方通行 | `ROAD_TILE_SOURCE_ID`（路面と同じ） | 独立レイヤー（並列トラック対象） |
| 停止要因POI・補給休憩POI | `region-poi-tiles`（点データ） | 同一source-layer`stop_poi`を`kind`値集合で分ける（`baseFilter`必須） |
| 事故 | `region-accident-tiles`（点データ、別ソース） | 独立 |

色の使い分け（一次/二次の意味の統一）:
- 「事実の種類」を区別するだけのカテゴリ（停止要因POI種別・補給POI種別）は中立色。
- 「二次軸の材料そのもの」として寄与するカテゴリ（指定路線・事故の当事者区分）は二次軸と
  同じ緑→赤の評価配色（`AXIS_RAMP_COLORS`）を使い、「1次のこの色は2次のこの色と同じ
  方向を指す」と直接読めるようにする。

各レイヤーの絞り込みは`buildStaticFilterAxes(rampAxes)`にカタログ化し、`legendFilter.ts`の
汎用機構（`buildLegendFilterExpression`/`buildCombinedLegendFilterExpression`）をそのまま
流用する。ramp軸ぶんの絞り込み軸は`rampAxes`（実行時フェッチ、軸スタジオの公開軸を含む）
から関数的に組み立てる——ビルド時静的リストの手書き列挙ではない。

## 交差点密度は地図上の独立可視化レイヤーとして提供しない

次数3以上の`road_node`はバックエンドのPOIタイルに焼き込まれているが、専用レイヤーを
持たない（材料`intersection_count_per_km`としては軸スタジオから引き続き選べるが、
現在この材料を使う公開軸は無い）。

## ポップアップへOSMタグの生値を出すときはエスケープする

ポップアップの値は`osm_raw_ways`/`osm_raw_pois`のタグ由来＝**第三者が編集できるデータ**で、
対訳表に載らない値は生のまま文字列へ入る（`SMOOTHNESS_LABELS`・`DESIGNATION_LABELS`・
停止要因/補給POIのラベル辞書はいずれも`?? 生値`のフォールバックを持つ）。
行き先は2通りある。**道路の詳細はReactで描くため、生値はテキストノードとして入る**
（`RoadInspectorPopup.tsx`）。点データ（事故・POI）はHTML文字列を`Popup.setHTML()`へ渡す
経路で、こちらはMapLibreの`DOM.sanitize()`が走る。

そのサニタイザにはバイパスが報告されており（修正版はv6系で、Next.jsのバンドラが
Workerのスクリプトを解決できず地図が描画されないため上げられない——
[architecture.md](../../architecture.md)「フロントエンド実装上の注意」）、
**ライブラリのサニタイザ1枚に安全性を預けない**。埋め込む前に`popupEscape.ts`の
`escapeHtml`／`labelOrEscapedRaw`を通す。

判断の基準は**行き先ではなく出所**にする。固定の対訳表に載る値は素通しでよく、
`?? 生値`のフォールバック・OSMタグのキーと値・軸スタジオ経由でDBに入る軸ラベルと軸idは、
`setHTML()`か`innerHTML`かに関わらずエスケープする——「サニタイザが後ろにいるから
ここは要らない」と経路ごとに判断すると、サニタイザを通らない経路が後から増えたときに
そこだけ素通しで残る。

## 本モジュールとの関係が薄いファイル

- `routeArrowIcon.ts`（周回ルートの順回り/逆回り矢印、選択中ルートにのみ描画）は
  「選択中ルート」に紐づく動的データを扱う。対象ファイル表に含まれているが、責務としては
  [ページ構成](page-composition.md)・[地図: 軸・ルート色分け](map-axis-coloring.md)に近い。
  区間クリック時の詳細表示（地点・到達予想時刻・軸別内訳）はボトムシート側
  （[ルート設定・結果パネル](route-settings-and-results.md)のRouteAxisProfile）が持ち、
  地図上（`MapView.tsx: handleRouteSegmentClick`）は軽量なマーカーを立てるのみで
  テキストポップアップを持たない。`handleRouteSegmentClick`が`queryRenderedFeatures`
  経由で読み戻す`feature.properties`は、MapLibreがGeoJSONソースをvector tile相当の
  内部表現へ変換する際にオブジェクト値をJSON文字列へ自動シリアライズするため、
  `restoreRouteSegmentProperties`（`ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS`に列挙した
  フィールドのみ）で復元してから使う。新しいオブジェクト型フィールドを`RouteSegmentDetail`
  へ追加するときはこの配列への追加が必須（追加漏れで文字列のまま渡り実行時エラーになる）。
- `icons.tsx`はこのモジュール（`MapOverlayControls`のアイコン辞書）専用ではなく、
  [動的気象レイヤー](dynamic-weather-layers.md)の`WeatherPanel`/`TodayOutlook`からも
  使われる、地図関連UI全体で共有するアイコン集である。
