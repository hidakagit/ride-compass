# 地図: 動的気象レイヤー（frontend）

## 責務

Open-Meteo・気象庁由来の時刻変化する気象データ（風・降水ナウキャスト/降水短時間予報/
延長予報・雷・竜巻・キキクル・線状降水帯予測マップ）を地図上に表示する共通機構と、
各要素固有のデータ層。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/dynamicWeather.ts` | 共通契約（型・共有タイムライン・状態管理の型・純粋関数） |
| `Map/precipitationNowcast.ts`・`thunderNowcast.ts`・`jmaNowcastFrames.ts` | 降水/雷/竜巻ナウキャストのフレーム列取得・統合 |
| `Map/lidenLayer.ts`・`lidenIcon.ts` | 雷放電位置データ（liden、実際の落雷地点）のフレーム列・GeoJSON取得・Canvas 2Dアイコン描画 |
| `Map/windLayer.ts`・`windArrowIcon.ts` | 風の矢印（gridMark）の格子データ・Canvas 2Dアイコン描画 |
| `Map/windPenalty.ts` | 環境グループの風penalty gridFill（矢印の背後に敷く面塗り） |
| `Map/riskMap.ts` | キキクル・線状降水帯予測マップ（未来フレームを持たない特殊系） |
| `Map/MapView.tsx`（`DYNAMIC_WEATHER_RENDERERS`関連箇所のみ） | 表示層本体。`ensureDynamicWeatherLayer`・`applyDynamicWeatherState`・`dynamicWeatherIds` |
| `hooks/useDynamicWeatherLayers.ts`・`useWeatherGrid.ts`・`useWeatherConditions.ts` | 状態管理・フェッチ |
| `hooks/usePolledFetch.ts` | 「マウント時に即座に1回フェッチ＋以降intervalMsごとに再フェッチ、cancelledフラグで古いレスポンスの反映を防止」という、`useDynamicWeatherLayers.ts`内の5箇所（降水ナウキャスト・降水短時間予報・雷竜巻ナウキャスト・キキクル・線状降水帯予測マップ）が共有するフェッチ骨格の共通実装 |
| `components/WeatherPanel/WeatherPanel.tsx`・`amedasWeatherIcon.ts`・`weatherCode.ts`・`components/TodayOutlook/TodayOutlook.tsx`・`components/WarningBadge/WarningBadge.tsx`・`components/DynamicLayerTimeSlider/DynamicLayerTimeSlider.tsx` | UI |
| `services/weatherApi.ts`・`types/weather.ts` | API呼び出し・型定義 |

## 共通契約（4本柱、`dynamicWeather.ts`冒頭コメント）

1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（`WIND_GRID_BBOX`、間隔は
   `windLayer.ts: WIND_GRID_SPACING_DEG`/`WIND_GRID_DETAIL_SPACING_DEG`）を共有する。
   フェッチも共有（`hooks/useWeatherGrid.ts`、風の矢印と降水延長予報のどちらか一方でも
   ONなら1回のフェッチで両方をカバーする）。
2. **表現は3パターン**: 格子中央にマークを出す（`gridMark`、風の矢印）、格子/タイル境界を
   指定色で塗る（`gridFill`、降水延長予報・風penaltyの面塗り）、配信元が描画済みの画像を
   重ねる`rasterTile`（気象庁ナウキャスト・降水短時間予報・雷・竜巻・キキクルの土砂/大雨/
   浸水・線状降水帯予測マップ）。加えて洪水キキクルのみ、配信元のMapbox Vector Tile
   （.pbf）をMapLibre標準のvectorソース+lineレイヤーでそのまま描画する`vectorTile`
   （feature-state・GeoJSON変換は不要、`riskMap.ts`冒頭コメント参照）。
3. **時間経過はスライダー1本**: ONの全レイヤーのフレーム時刻を統合した1本のタイムライン
   （`mergeFrameTimes`）を`DynamicLayerTimeSlider`へ渡す。各レイヤーは
   `frameIndexForTime`で選択時刻に対応する自分のフレームを求め、選択時刻が自分の
   データ範囲外なら何も描画しない。キキクル3種・線状降水帯予測マップはこの
   タイムラインに乗らない（下記「特殊系」参照）。
4. **データ取得の差異はデータ層で吸収**: 各要素のデータ層モジュールがソース（1グループに
   つきN個ありうる）を統合し、フレームごとの描画内容（`DynamicWeatherRenderPayload`）を
   返す。表示層（`page.tsx`/`MapView.tsx`）はペイロードの`kind`しか見ない。

## 表示層の実装（`MapView.tsx`）

```
useDynamicWeatherLayers（フック、page.tsx経由）
  ├─ フェッチ・共有タイムライン計算・payload組み立て
  └─ dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>
                     を MapView へ渡す
                            │
                            ▼
MapView.tsx: DYNAMIC_WEATHER_RENDERERS（唯一の描画スペック情報源）
  ├─ ensureDynamicWeatherLayer(map, id, groupSpec)  … source/layerを初期化時に1度だけ追加
  └─ applyDynamicWeatherState(map, id, groupSpec, groupState)  … 都度呼ばれる反映処理
        for each named source:
          visible = groupState[source]?.visible ?? false
          payload = groupState[source]?.payload
          payload.kind が spec の該当サブレイヤーと一致するときだけ表示にする
```

`dynamicWeatherIds(id, source, sub)`が`region-dynamic-weather-${id}-${source}-${sub}`
という命名規約でsource/layer idを機械的に決める（`-main`のみ、縁取り専用の別レイヤーは持たない）。

`gridMark`（`DynamicWeatherMarkSpec`）の縁取りは、主層と別のsymbolレイヤーではなく
`icon-halo-color`/`icon-halo-width`（SDFアイコンのpaintプロパティ、`icon-image`に
`sdf: true`が必須）で1層にまとめる。MapLibreはレイヤーの上から順にシンボルを配置する
ため、同位置・大きめのシンボルを別レイヤー（下）で重ねると`icon-allow-overlap: false`
下では常に「衝突」として全て落ちる——1層にまとめれば衝突判定は主層自身の1回だけになり、
縁取りは常に主層と同じ地点に出る。

## 1グループ=複数の名前付きソース

1つの`DynamicWeatherLayerId`（チップ単位）は、`DynamicWeatherSourceId`で識別される
複数の名前付きソースを同時に持てる。単一ソースのグループは`"main"`という1キーだけを持つ。

| グループ | ソースキー | kind | データ層 |
|---|---|---|---|
| `precipitationNowcast` | `main` | raster（60分以内）→raster（〜15時間）→gridFill（延長予報） | `precipitationNowcast.ts` |
| `precipitationNowcast` | `linearRainband` | raster（sjfcstmap） | `riskMap.ts: fetchLinearRainbandFrames` |
| `windVector` | `arrow` | gridMark | `windLayer.ts` |
| `windVector` | `penaltyFillCoarse` | gridFill | `windPenalty.ts: windPenaltyCoarseGridToClippedFeatureCollection`（粗い格子=`useWeatherGrid.ts`の`grid`） |
| `windVector` | `penaltyFill` | gridFill | `windPenalty.ts: windPenaltyGridToCellFeatureCollection`（詳細格子=`effectiveGrid`） |
| `thunderNowcast` | `main` | raster | `thunderNowcast.ts` |
| `tornadoNowcast` | `main` | raster | `thunderNowcast.ts`（同じフレーム列を共有、プロダクトコードのみ相違） |
| `liden` | `main` | gridMark | `lidenLayer.ts`（配信元GeoJSONをそのまま使う唯一の要素、下記参照） |
| `landslideRisk`/`heavyRainRisk`/`inundationRisk` | `main` | raster | `riskMap.ts: fetchCurrentRiskFrames` |
| `floodRisk` | `main` | vector | `riskMap.ts: fetchCurrentRiskFrames`（`floodRenderPayload`） |

`liden`（雷放電位置データ）は、他要素が既に手元にある格子データ・タイルURLテンプレートから
同期的にペイロードを組み立てるのに対し、配信元が実際の落雷地点をGeoJSONで提供するため
選択フレームが変わるたびに`lidenLayer.ts: fetchLidenGeojson`を非同期fetchする唯一の要素
（「データ取得の差異はデータ層で吸収」という4本柱の枠内だが、取得のタイミング自体が
「フレーム選択に追従した都度fetch」という他要素に無い形）。`hooks/useDynamicWeatherLayers.ts`
が`frameIndexForTime`で求めた選択中refの変化を`useEffect`で監視し、取得結果を`{ref, geojson}`
の形でstateへ保持する——保持しているrefと選択中refが一致するときだけpayloadへ反映すること
で、scrub中に古いフェッチが後から解決しても直前の時刻のデータを新しい時刻の表示へ混ぜない。
落雷ごとの強弱を示す値を配信元が持たないため、gridMarkが必須とする`valueProperty`
（`LIDEN_MARK_VALUE_PROPERTY`）は固定値1を全featureへ合成し、`minScale===maxScale`により
icon-sizeはズームのみに依存する。

`windVector`の`penaltyFill`は`arrow`と同じフレーム時刻を使うが表示ON/OFFは独立している
（`showWindPenaltyFill = showWindVector && !hasDetail`。矢印自体はルート確定後も表示され
続ける）。

`penaltyFillCoarse`は`penaltyFill`（詳細格子、`useWeatherGrid.ts`の`detailGrid`が画面中心
付近の狭いbbox[`windLayer.ts: clampWindDetailBbox`]しかカバーしないことがある）の下敷きとして、
関東本土全域を常時カバーする粗い格子（`grid`、`WIND_GRID_SPACING_DEG`）から同じ配色ロジック
（`windPenaltyFillColorExpression`、`dedicatedWayValueBoundaries`由来のしきい値も共有）で
セルを作る。可視条件（`showWindPenaltyFill`）は`penaltyFill`と同じ。`DYNAMIC_WEATHER_RENDERERS.
windVector`内で`penaltyFillCoarse`を`penaltyFill`より前に定義しており、`ensureDynamicWeather
Layer`がgroupSpecのキー順=`addLayer`呼び出し順で描画するため、粗い格子が背面・詳細格子が
前面になる。`windPenalty.ts: windPenaltyCoarseGridToClippedFeatureCollection`が、粗い格子
セル（1辺`WIND_GRID_SPACING_DEG`の正方形）のうち詳細格子の実際のカバー範囲（返ってきた
点群の外接矩形を詳細格子の間隔ぶん外側へ拡張した範囲）と重なる部分を、`subtractRectangle`
（軸に平行な矩形どうしの引き算、外部ライブラリ不要）で幾何学的に切り取ってから描画する。
両方を同じ場所へ重ねて描画すると、半透明のfill-opacityが二重に重なって色が凡例と対応
しなくなるため、点や矩形の包含判定で丸ごと除外・非除外を決めるのではなく、重なった部分
だけを正確に切り取る。1つの粗いセルが詳細格子のカバー範囲と部分的にしか重ならない場合、
残った部分（最大4枚の矩形）を別々のFeatureとして描画するため、1粗格子点が0〜4個の
Featureに対応することがある。詳細格子の取得範囲自体（ズームに応じた間隔、
`clampWindDetailBbox`）は変更しないため、ズームインしたときの細かい表現は維持される。

## 新しい動的要素を追加する1本道

1. backend: `wind_grid.py`の`WindGridPoint`へ値フィールドを追加、`weather_client.py`の
   `WIND_GRID_VARIABLES`へOpen-Meteo変数を足す（この経路は風・降水延長予報限定）
2. データ層: 要素モジュールを新設し、フレーム列（`DynamicWeatherFrame[]`）とペイロード
   関数を実装する
3. `MapView.tsx`: `DYNAMIC_WEATHER_RENDERERS`へ描画スペックを1エントリ追加する
   （既存グループへ名前付きソースを1つ追加する場合も同じ辞書内へ足すだけでよい）
4. `mapLayers.ts`: 地図チップを追加し、`MapLayerId`・`dynamicWeather.ts`の
   `CHIP_DYNAMIC_WEATHER_LAYER_IDS`（または常時マウントなら
   `ALWAYS_ON_DYNAMIC_WEATHER_LAYER_IDS`）へ1行足す
5. `hooks/useDynamicWeatherLayers.ts`: フェッチeffect・フレーム列・payload計算・
   `dynamicWeather`オブジェクトへの追加（3〜4と違い自動反映の仕組みは無い、手書き作業）

## キキクル・線状降水帯予測マップ（特殊系）

他の動的気象レイヤーと異なり**未来方向の複数フレームを持たない**——気象庁側で実況と
短時間予測を統合済みの「現在の危険度」単一値のみを配信する（`validtime===basetime`）。

- キキクル3種（土砂・大雨・浸水）: 「防災」カテゴリとして`WarningBadge`と同様の常時
  マウント（チップ無し・時刻スライダーとも無関係、マウント時に常にフェッチする）。
  `MapLayerId`自体を持たない。
- 線状降水帯予測マップ: `precipitationNowcast`チップの4つ目のソース（`linearRainband`）。
  共有タイムラインの選択時刻が現在〜3時間先の範囲内（`isWithinFutureWindow`）のときだけ、
  他のソースと重ねて表示する（キキクルと異なりタイムラインと連動し続ける）。

## 共有タイムラインのラベル

`mergeFrameTimes`が降水ナウキャスト（5分刻み）と格子予報（1時間刻み）を統合すると、
「近い将来は細かく、遠い将来は粗い」目盛りが自然にできる。表示ラベルは常に日付を含める
（タイムラインが約48時間先まで日付をまたぐため）。正時判定は`getUTCMinutes()`で行う
（JSTは UTC+9:00ちょうどで分のずれが無いため）。

## 常設ヘッダーの天候表示（`WeatherPanel`）との違い

`WeatherPanel`（常設ヘッダー、`amedasWeatherIcon.ts`が天気分類を担う）は**アメダス実測値**
のみで構成し、Open-Meteo予報とは独立にフェッチする。`TodayOutlook`（`weatherCode.ts`が
Open-MeteoのWMOコードを分類）は**Open-Meteo予報**（今日の降水確率最大・最大風速・
気温レンジ・天気の流れ）を扱う。両者は別APIに依存する独立コンポーネントで、本モジュールの
動的地図レイヤーとは別のフェッチ経路を持つ。

## 暗黙の前提

- 各named sourceのvisibility判定（`showWindPenaltyFill`のような追加条件）は汎用機構
  （`dynamicWeather.ts`/`MapView.tsx`）の外、呼び出し側（`page.tsx`/
  `useDynamicWeatherLayers.ts`）が都度手書きする。汎用機構自身は渡された`visible`
  フラグをそのまま使うだけで、「なぜそのフラグなのか」を一切知らない。
- `frameIndexForTime`の許容誤差（`FRAME_RANGE_EPSILON_MS`=1秒）は「複数フレームから
  該当する1枚を選ぶ」用途専用であり、「常に1枚だけの現在値スナップショットを表示し続ける」
  キキクル系の性質とは噛み合わない。新しい「現在値スナップショットのみ」を持つ要素は
  共有タイムラインに乗せてはならない。
- `applyDynamicWeatherState`は「visibleとpayloadのどちらか一方でも欠ければ非表示」を
  常に守る。フェッチ未完了・取得失敗・選択時刻がデータ範囲外のいずれでも、古いフレームが
  一瞬でも見えないようにするための設計であり、この判定を呼び出し側で緩めてはならない。
- `windVector`の`arrow`（gridMark）は`windGrid`（粗い格子）でフレーム時刻を計算するが、
  実際の描画は`effectiveWindGrid`（詳細格子があればそちらを優先）を使う。フレーム時刻の
  計算元と実際に塗る値の元が別グリッドである点は初見では見落としやすい。
- `gradientFill`（勾配の面塗り）は`page.tsx`のコメント上`windVector`と同じ「環境グループ」
  という語彙で呼ばれるが、`DYNAMIC_WEATHER_RENDERERS`汎用機構には統合されておらず、
  `MapView.tsx`内に`ensureGradientFillLayer`/`applyGradientFillGeojson`という独立実装を
  持つ。このモジュールの対象範囲は風・降水・雷・竜巻・キキクル・線状降水帯予測マップの
  みであり、勾配は含まない（勾配は[地図: 軸・ルート色分け](map-axis-coloring.md)の管轄）。
- タイルURLテンプレート（`riskMap.ts: tileUrlTemplate`・`precipitationNowcast.ts`・
  `thunderNowcast.ts`）は`lib/tileBaseUrl.ts: tileBaseUrl()`で常に絶対URLにする。
  `vectorTile`（洪水キキクル）はMapLibreがWeb Worker内で取得するため相対パスだと
  `new Request(url)`がWorkerのbase URLに対して解決できず例外になり、`rasterTile`も
  backend直接配信（`NEXT_PUBLIC_TILE_BASE_URL`）ではページと別オリジンになるため絶対URLが
  要る（`services/regionApi.ts`の`roadSurfaceTileUrl`等と同じ仕組み、
  [静的レイヤー](static-map-layers.md)「タイルの配信元」参照）。`targetTimes`JSON等のアプリのfetch()で
  読むデータは相対パスのまま。
