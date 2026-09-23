# 地図: 動的気象レイヤー（frontend）

## 責務

気象庁由来の時刻変化する気象データ（MSM予報の風・降水延長予報、降水ナウキャスト/
降水短時間予報・雷・竜巻・キキクル・線状降水帯予測マップ）を地図上に表示する共通機構と、
各要素固有のデータ層。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/dynamicWeather.ts` | 共通契約（型・共有タイムライン・状態管理の型・純粋関数） |
| `Map/precipitationNowcast.ts`・`thunderNowcast.ts`・`jmaNowcastFrames.ts` | 降水/雷/竜巻ナウキャストのフレーム列取得・統合 |
| `Map/lidenLayer.ts`・`lidenIcon.ts` | 雷放電位置データ（liden、実際の落雷地点）のフレーム列・GeoJSON取得・Canvas 2Dアイコン描画 |
| `Map/windLayer.ts`・`windArrowIcon.ts` | 風の矢印（gridMark）の格子データ・Canvas 2Dアイコン描画 |
| `Map/riskMap.ts` | キキクル・線状降水帯予測マップ（未来フレームを持たない特殊系） |
| `Map/jmaTileIndex.ts` | 在否インデックスの解釈（URL解析・「空だと確認済み」の判定、純ロジック） |
| `Map/jmaTileProtocol.ts` | `jmatile://`スキームのMapLibreプロトコル。空と分かっているタイルをネットワークへ出さずに透明タイルで返し、配信の失敗を要素ごとに記録して購読できるようにする |
| `hooks/useJmaTileIndex.ts` | 在否インデックスの定期取得 |
| `features/map/scene/groups/weather.ts` | 動的気象の描き方。何を描くか（チップid・名前付きソース・描き方の種類・配信元）は源泉の`mapDisplay.weatherElements`をループして受け取り、ここは要素ごとの見た目（`paint`・`layout`・`filter`・記号の絵）だけを持つ。ソース名（`weatherSourceId`）・ソースの宣言・レイヤー・記号の絵の登録（`WEATHER_ICONS`）はこの2つから導かれる |
| `features/map/scene/applyToMap.ts`（`weatherStateFrom`・`weatherPayloadFrom`） | `dynamicWeather`（チップid→名前付きソース→表示・中身）を宣言の入力へ移す。JMAタイルのURLへ`jmatile://`スキームを付ける |
| `hooks/useDynamicWeatherLayers.ts`・`useWeatherGrid.ts`・`useWeatherConditions.ts` | 状態管理・フェッチ。定期取得は`usePolledFetch`（粗い風格子を含む全系統）、現在地に追随する取得は`useWeatherConditions`内の`useLocationFetch`が骨格を持ち、個々のフェッチはfetcherだけを渡す |
| `hooks/usePolledFetch.ts` | 「マウント時に即座に1回フェッチ＋以降intervalMsごとに再フェッチ、cancelledフラグで古いレスポンスの反映を防止」という、`useDynamicWeatherLayers.ts`内の定期取得（降水ナウキャスト・雷放電位置データ等）が共有するフェッチ骨格の共通実装 |
| `components/WeatherPanel/WeatherPanel.tsx`・`amedasWeatherIcon.ts`・`weatherCode.ts`・`components/TodayOutlook/TodayOutlook.tsx`・`components/WarningBadge/WarningBadge.tsx` | UI |
| `services/weatherApi.ts`・`types/weather.ts` | API呼び出し・型定義 |

## 共通契約（4本柱、`dynamicWeather.ts`冒頭コメント）

1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（`WIND_GRID_BBOX`、間隔は
   `windLayer.ts: WIND_GRID_SPACING_DEG`/`WIND_GRID_DETAIL_SPACING_DEG`）を共有する。
   フェッチも共有（`hooks/useWeatherGrid.ts`、風の矢印と降水延長予報のどちらか一方でも
   ONなら1回のフェッチで両方をカバーする）。
2. **表現の型は決まっている**: 格子中央にマークを出す（`gridMark`、風の矢印）、格子/タイル境界を
   指定色で塗る（`gridFill`、降水延長予報の面塗り）、配信元が描画済みの画像を
   重ねる`rasterTile`（気象庁ナウキャスト・降水短時間予報・雷・竜巻・キキクルの土砂/大雨/
   浸水・線状降水帯予測マップ）。加えて洪水キキクルのみ、配信元のMapbox Vector Tile
   （.pbf）をMapLibre標準のvectorソース+lineレイヤーでそのまま描画する`vectorTile`
   （feature-state・GeoJSON変換は不要、`riskMap.ts`冒頭コメント参照）。
3. **時刻は共有state1つ**: 表示時刻は`dynamicLayerTargetTime`（条件バー`RideConditionBar`の
   出発時刻と同じstate、`setDynamicLayerTargetTime`で書き換える）。各レイヤーは
   `frameIndexForTime`で選択時刻に対応する自分のフレームを求め、選択時刻が自分の
   データ範囲外なら何も描画しない。キキクル4種・線状降水帯予測マップはこの
   タイムラインに乗らない（下記「特殊系」参照）。
   **予測を持たず観測だけが届くレイヤー（雷放電位置データ）は`observationIndexForTime`を
   使う**——配信の遅れ（実測5〜10分）のぶん共有時刻が最新フレームより後ろに来るのが常態で、
   範囲外で描かない規約をそのまま当てると常に何も描かれない。遅れのぶんは最新の観測を出し、
   それより先（利用者が出発時刻を選んだ等）を指していれば描かない
   （`OBSERVATION_DELAY_TOLERANCE_MS`）。
   **利用者が出発時刻を選ぶまでは「今」へ張り付き、時間の経過とともに進む**（`steppedNow`、
   5分刻み）。選んだ後はその時刻を保ち、「今」ボタンで張り付きへ戻る（`handleDynamicLayerNow`。
   **現在時刻を`setDynamicLayerTargetTime`へ渡すのでは代用にならない**——その値でピン留め
   され、以後は追従しない）。張り付かせないと、
   実況由来のフレーム列は先頭が更新のたび前進するのに共有時刻だけが取り残され、
   `frameIndexForTime`が範囲外を返して降水・雷・竜巻・雷放電が黙って描画を止める
   （利用者からは「雨が降っていない」と区別がつかない）。進める刻みを5分より細かくしても、
   出発時刻として選べる値自体が5分刻みのためどのレイヤーが選ぶフレームも変わらず、
   共有時刻をキーに持つ取得（`useDedicatedWayValues`）だけが無効化される。
4. **データ取得の差異はデータ層で吸収**: 各要素のデータ層モジュールがソース（1グループに
   つきN個ありうる）を統合し、フレームごとの描画内容（`DynamicWeatherRenderPayload`）を
   返す。表示層（`page.tsx`/`MapView.tsx`）はペイロードの`kind`しか見ない。

## 表示層の実装（`scene/groups/weather.ts`）

```
useDynamicWeatherLayers（フック、page.tsx経由）
  ├─ フェッチ・共有タイムライン計算・payload組み立て
  └─ dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>
                     を MapView へ渡す
                            │
                            ▼
scene/applyToMap.ts: weatherStateFrom  … `${チップid}/${名前付きソース}`で引ける形へ移す
                            │
                            ▼
scene/groups/weather.ts: mapDisplay.weatherElements（源泉の宣言）をループ
  for each 要素:
    見た目 = 描き方の鍵（チップ/ソース/描き方）で引く（配信元のラスタは共通の1つ）
    ソース = 要素の宣言＋届いた中身（届く前は仮の中身）
    レイヤー: 表示 = visible かつ payload.kind が要素の描き方と一致するとき
                            │
                            ▼
scene/applyMapScene.ts  … 前回の宣言との差だけを地図へ当てる
```

他の地図の要素と同じ宣言の一部なので、スタイルを差し替えた後の作り直しも同じ道を通る
（[静的レイヤー・道路表示](static-map-layers.md)「スタイル取り直し後の作り直し」）。

ソース名は**チップid＋名前付きソース＋描き方**（`weatherSourceId`）、レイヤーidはそこへ
**描き方**を足したもの（[静的レイヤー・道路表示](static-map-layers.md)「ソース名とレイヤーidの決め方」）。
**描き方をソース名から落とさない**——同じ名前付きソースを描き方違いで2要素が名乗ることがあり
（降水の`main`は配信元のラスタと自前の格子の面）、落とすとソースが1本へ畳まれて、後から
名乗った側のレイヤーが種類の合わないソースを指し、そのレイヤーだけが黙って描かれない。
**チップidは源泉の語をそのまま使う**——ここで別の呼び名を付け直すと、源泉が知っているものに
画面だけの語彙が重なる。

**要素ごとに配信先が違うため、1要素＝1ソース**（同じソースへ相乗りできない）。1要素に何枚
重ねるかは自由で、いまは1枚だけ持つ（縁取りは別レイヤーではなく記号の`icon-halo-*`で出す）。

## 色の段は帯で持ち、地図と凡例が同じ配列を読む

風速（`windLayer.ts: WIND_SPEED_COLOR_STOPS`）・降水強度（`precipitationNowcast.ts:
PRECIPITATION_COLOR_STOPS`）の色の段は**帯の下限＋色**で、地図はこの配列をそのまま
`step`式へ組み立てて塗る（`features/map/scene/groups/weather.ts`）。凡例
（`WIND_SPEED_LEGEND_LEVELS`・`PRECIPITATION_INTENSITY_LEVELS`）も同じ配列から帯の範囲を
書き出すため、地図に出る色と凡例の行は1対1で対応する。

**連続補間（`interpolate`）で塗ってはいけない。** 凡例が並べられるのは帯ごとの色見本1つ
だけで、それは帯の端の色でしかない。帯の中ほどの値はどの見本とも違う色になり、「この色は
凡例のどれか」が答えられなくなる。

**凡例の行を束ねないこと。** 束ねた行は、地図が塗り分けている複数の帯を1つの色見本で代表する
ことになり、束ねた中の値がまた見本と食い違う。粒度を粗くしたいなら段自体を減らす。

## 空タイル要求の間引き（在否インデックス）

JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。`hooks/useJmaTileIndex.ts`が
backendの`GET /api/jma-tile-index`（[気象・動的レイヤー](../backend/weather-dynamic-layers.md)
「在否インデックス」節。応答の型は`types/route.ts`が再exportする生成型
`JmaTileIndexResponse`で、`Map/jmaTileIndex.ts`は構造を手書きしない）を定期取得し、`Map/jmaTileProtocol.ts`が`maplibregl.addProtocol`で
タイル要求を横取りする。「空だと確認済み」のタイルはネットワークへ出さず、透明PNG
（ベクタは0バイトのMVT）を返す。

**この空PNGは1x1で、MapLibreが`tileSize`ぶんへ引き伸ばす。不透明な画素が1つでも入ると
タイル全面がその色で塗られ、空タイルは全ズーム・全座標で返るため地図全体が塗り潰される。**
`jmaTileProtocol.test.ts`が画素を復号して不透明度0を検査する。

**空タイルの中身は要求のたびに作り直す**。MapLibreはタイルのデータをWorkerへtransferして
渡すため、返したArrayBufferはdetachedになる。共有のインスタンスを返すと2回目以降の
postMessageが`An ArrayBuffer is detached and could not be cloned`で失敗し、そのタイルが
描画されない。空タイルは404（疎な格子状タイルの正常系）でも返るため、使い回せば実機では
常時起きる。

そのためJMAタイルのURLは`jmatile://`スキームを付けた形でソースへ渡す
（`scene/applyToMap.ts: weatherPayloadFrom`で付与）。届く前の仮のURL（`jmaPlaceholderTileUrl`）には
付けない——中身が届くまでレイヤーは非表示で、表示中のレイヤーを持たないソースのタイルは
要求されない。

**インデックスに載っていないタイルは「空」と見なす**（載っているのは中身のあるタイルだけ）。
そのためbackend側は、配信元が実データを持たず補間で埋めるズームについても在否を載せる必要が
ある——載せずにおくとクライアントがそこを一律「空」と見なし、補間が一度も動かないまま
そのズームだけ危険度が消える。

**取りこぼしより空振りを選ぶ**: 判断がつかない場合（インデックス未取得・要素の`basetime`が
要求と違う・インデックスの網羅範囲外・URLを解釈できない）は必ず「取りに行く」へ倒す。
誤って省くと危険情報が地図から消えるため、省けるのは空だと確認済みの場合だけに限る。
取得に失敗した応答（404を含む）も空タイルとして返す——MapLibreは失敗タイルを再試行しない
ため、ここで例外にするとその位置が永久に空白になる。

JMAタイル系ソースの`minzoom`/`maxzoom`・パスの系統・ベクタのレイヤー名は、源泉の宣言の`tile`
（`mapDisplay.weatherElements`）から受け取る（正本は
[気象・動的レイヤー](../backend/weather-dynamic-layers.md)の`domain/jma_tile_specs.py`）。
配信元は要素ごとに実データを持つズームが異なり、上限を超えると空タイルが返って地図から色が
消えるため、この値を画面側へ書かない。

`gridMark`（`weather.ts: markElement`）の縁取りは、主層と別のsymbolレイヤーではなく
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
| `windVector` | `arrow` | gridMark | `windLayer.ts`（走行方位に依存しない矢印のみ。走行方位への依存を含む向かい風/追い風の強さは[地図: 軸・ルート色分け](map-axis-coloring.md)の専用way値配信軸が担う） |
| `disaster` | `heavyRain`/`landslide`/`inundation` | raster | `riskMap.ts: fetchCurrentRiskFrames` |
| `disaster` | `thunder`/`tornado` | raster | `thunderNowcast.ts`（1本のフレーム列を共有、プロダクトコードのみ相違） |
| `disaster` | `flood` | vector | `riskMap.ts: fetchCurrentRiskFrames`（`floodRenderPayload`） |
| `disaster` | `liden` | gridMark | `lidenLayer.ts`（配信元GeoJSONをそのまま使う唯一の要素、下記参照） |

`disaster`（災害）は源泉がチップ`disaster`として宣言したソース（`dynamicWeather.ts: DisasterSourceKey`）を1チップへまとめたグループで、全ソースが1つの`showDisaster`に
連動する。同じ段（描き方ごとに決まる。`weather.ts: TIER_OF`）の中では源泉の宣言
（backendの`domain/map_display.py: WEATHER_ELEMENTS`）の並び順が重なり順になるため、面（キキクル3種・雷・竜巻のラスタ）を下に、局所的で見落としやすい線（洪水）・点
（落雷）を上に置く。面同士が重なった領域は混色し危険度5段階を読み取れなくなるが、危険度
ゼロの領域は配信元のタイルが透明のため平常時の地図の見た目は変わらない。**この並び順が
効くのは面どうし・線どうしの間だけである**——面は基礎地図の線・記号より下へ差し込まれ
（[静的レイヤー・道路表示](static-map-layers.md)参照）、線・点は最前面へ積まれるため、
面をどれだけ濃くしても線・点はその上に残る。気象庁は危険度を
ラスタ画像でしか配信せず現在の警戒レベルを返すAPIを持たないため、「重なっているなら最も
危険な1枚だけ出す」といった自動制御は実装できない。代わりに、チップの▶パネルの
「表示する情報」でソースを個別に間引ける——非表示キーは他の凡例絞り込みと同じ
`hiddenLegendKeysByMode`へ保存され、`hiddenDisasterSources`としてこのフックへ渡る。
ソースごとの`visible`だけでなく、1本の`targetTimes`JSONを共有する要素がすべて非表示なら
そのフェッチ自体も行わない（「表示中のものだけ叩く」方針）。どのソースがどのフェッチに
属するか（`DISASTER_FETCH_GROUP`）はデータ層のフェッチ関数ごとに決まる画面の持ち物で、
パスの系統からは導けない（雷・竜巻と落雷は同じ`nowc`系統・同じ時刻一覧だが、表示の
オンオフを別々に持つため別々に取りに行く）。鍵は源泉のソースから導くため、源泉に災害の
ソースが増えて振り分けが無ければ型検査が落ちる。

**配信元の要素id・パスの系統・時刻一覧の在り処はデータ層も源泉から引く**（`jmaNowcastFrames.ts:
jmaDelivery`・`jmaTilePayload`・`fetchJmaTargetTimes`）。データ層は（チップ/名前付きソース）の鍵だけを
名指し、URLの要素id・系統・拡張子（ベクタなら`.pbf`）と時刻一覧のURLは`mapDisplay.weatherElements`の
`jmaElements`・`kind`から組み立てる。鍵の型は生成物から導くため、源泉から
要素が消えれば名指した側の型検査が落ち、要素idが変われば画面は新しいidで取りに行く
（手で持っていると、古いidのタイルが404→空タイルとなり地図から黙って消える）。
時刻一覧（`targetTimes*.json`）の中から自分の行を選ぶ`elements`の照合も同じ要素idを使う。

**1つの名前付きソースが、選んだ時刻によって別の配信要素から届くことがある**——降水の`main`ラスタは
60分先までが降水ナウキャスト、その先15時間先までが降水短時間予報で、配信要素も系統も時刻一覧も違う。
源泉は`jmaElements`を時刻の段の順（近い時刻から）に並べ、データ層は段の番号
（`precipitationNowcast.ts`の`NOWCAST_STAGE`・`SHORT_RANGE_STAGE`）で引く。MapLibreのソースは1本の
ままURLだけが差し替わるので、ソースのズーム範囲は段の間で一致している必要があり、backendが
生成時に確かめる（食い違えば生成が落ちる）。段ごとに時刻一覧の読み方（実況の外挿か数値予報の
ランか）が違うため、段の番号だけは降水のデータ層が名指す。

時刻一覧が複数のファイルに分かれる要素（降水ナウキャストの実況と予測）は、`fetchJmaTargetTimes`が
全ファイルの行をつなげて返し、一部のファイルだけ取れなければ残りで部分的な時系列を返す
（全部取れなかったときだけ失敗）。同じファイルを同時に取りに行く要素（キキクルの各要素、
降水短時間予報と線状降水帯予測マップ）は、未解決のフェッチを共有して往復を1回に畳む。

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

## 新しい動的要素を追加する1本道

1. backend: `domain/map_display.py: WEATHER_ELEMENTS`へ宣言を1件足す（チップid・名前付き
   ソース・描き方の種類・気象庁の配信要素id）。タイルで描くなら`domain/jma_tile_specs.py:
   JMA_TILE_SPECS`へ配信元の仕様（パスの系統・ズーム・ベクタのレイヤー名）を1件足す。
   配信元から取るがタイルでは描かない要素（落雷のGeoJSON等）は、同じファイルの
   `JMA_NON_TILE_PATH_GROUPS`へパスの系統だけを足す。
   新しいチップidを名乗ればチップも増える（`WEATHER_LAYER_GROUPS`はこの宣言から導かれ、
   生成物経由で`DynamicWeatherLayerId`・`MapLayerId`になる）。`scripts/export_openapi.py`で
   生成物（`mapDisplay.ts`の`weatherElements`）を作り直す。自前のMSM格子から描くなら、
   `wind_grid.py`の`WindGridPoint`へ値フィールドを、`msm_client.py`の`FORECAST_VARIABLES`へ
   MSM変数を足す（この経路は風・降水延長予報限定）
2. `features/map/scene/groups/weather.ts`: 配信元のラスタ（`rasterTile`）なら何も足さない
   （見た目は共通の1つ）。それ以外は`DRAWINGS`へ見た目（`paint`・`layout`・`filter`・記号）を
   1件足す——鍵は生成物から導かれるため、足し忘れると型検査が落ちる。ソース名・ソースの宣言・
   レイヤー・記号の絵の登録はここから導かれる
3. データ層: 要素モジュールを新設し、フレーム列（`DynamicWeatherFrame[]`）とペイロード
   関数を実装する。配信元のタイルなら`jmaTilePayload("<チップ>/<ソース>", 時刻)`で
   ペイロードになる（要素id・系統を書かない）
4. 新しいチップを足したときだけ: `mapLayers.ts`へ記述子（アイコン・凡例・
   `dataSource: "ownFetch"`）を1エントリ足す
5. `hooks/useDynamicWeatherLayers.ts`: フェッチeffect・フレーム列・payload計算・
   `dynamicWeather`オブジェクトへの追加（1〜2と違い自動反映の仕組みは無い、手書き作業）。
   `dynamicWeatherDataStatus`（下記「データ取得状態」節）へも同じ要素の
   `deriveFetchLayerStatus(loading, error, payload !== undefined, hasFetched)`呼び出しを
   1行足す。

契約テスト（`MapView.state.contract.test.ts`の全部を載せた状態）の母集団も生成物の
`mapDisplay.weatherElements`で、1で足した要素はそのまま検査の対象になる。

## データ取得状態

動的気象のチップ（`DynamicWeatherLayerId`）全てが、`useDynamicWeatherLayers.ts`から
`mapLayers.ts: deriveFetchLayerStatus(loading, error, hasPayload, hasFetched)`という同じ
純粋関数を通り、`LayerDataStatus`（"loading"/"empty"/"error"、`mapLayers.ts`）を1つ返す
（判定順序はエラー中 > 読込中 > 未取得[undefined] > 読込済みだが値なし、
`useLayerDataStatus.ts: computeLayerDataStatus`と同じ）。`loading`/`error`は各要素が既に
持つフェッチフック（`usePolledFetch`の戻り値、風は`useWeatherGrid`）自身の値をそのまま
渡し、`hasPayload`は選択中の共有時刻に対応するpayloadが`undefined`でないかで決まる。
`hasFetched`は一度でも取得が完了したかで、初回取得前を「値なし（empty）」と誤って
見せないために要る。

**MapLibreのソースイベント経由の系統（`MapView.tsx: buildLayerDataSources`）は
動的気象レイヤーの対象外**——実際の外部フェッチは自前のJSコード（`usePolledFetch`等）で
行われ、結果を`map.getSource(id).setData(...)`/`setTiles(...)`で流し込むだけのため、
MapLibre側のソースイベントはフェッチの待ち時間・失敗を観測できない（`kind`が
raster/vectorTile[実タイル取得がMapLibre自身の責務]であっても、フレーム一覧
[targetTimes.json等]の取得自体は自前のJSフェッチのため、そちらが失敗すると
payloadが`undefined`のままレイヤーが非表示になり続け、MapLibre側には何のイベントも
発生しない）。`elevation`（国土地理院のラスタタイル、静的データで自前のJSフェッチ層を
持たない）だけがT87の対象のまま残る。

`precipitationNowcast`は「main」（ナウキャスト/短時間予報/延長予報の3段）と
「linearRainband」（4つ目のソース）を1つのチップとして統合する——UI上のチップも
1つのため、いずれか一方でも描画できていればloading/errorとしない
（`nowcastLoading || linearRainbandLoading`・`nowcastError ?? linearRainbandError`・
`precipitationPayload !== undefined || linearRainbandPayload !== undefined`）。
`disaster`も同じくチップ1つのため、3本のフェッチ（キキクル・雷竜巻・落雷）の
loading/errorをまとめ、`hasPayload`は7ソースのいずれか1つでも描画できていれば
trueとする。

**タイルの配信そのものが落ちている状態は、この経路には現れない**——`jmaTileProtocol.ts`は
どの失敗も空タイルへ倒すため（上記「空タイル要求の間引き」参照）、MapLibreはタイルを
取得できたものとして扱い、フレーム一覧のフェッチも正常なまま。「平常時は透明」が正常系の
レイヤー（キキクル等）では、これが危険度ゼロと見分けられない。そのためプロトコルハンドラが
404以外の失敗を要素ごとに記録し（404は配信元が「空」と答えている＝配信は生きている）、
`useSyncExternalStore`で購読した記録を`dynamicWeather.ts: tileDeliveryFailureLayerIds`が
表示中のpayloadのタイルURLと突き合わせて、当たったチップを`"error"`にする。記録は
失敗したフレームの要素配下URL（basetime・validtimeを含む）で持つため、フレームが進んで
取得できるようになれば自然に外れる。グループ配下を機械的に走査するので、要素やチップが
増えても足すコードは無い。

算出した`dynamicWeatherDataStatus`は`page.tsx`が`mapViewLayerDataStatus`
（ソースイベント側）とマージして1つの`layerDataStatus`にし、`overlayLayers`
（`MapOverlayControls`の状態ドット）へ渡す
（[静的地図レイヤー](static-map-layers.md)「レイヤーのデータ取得状態」節参照）。

## キキクル・線状降水帯予測マップ（特殊系）

他の動的気象レイヤーと異なり**未来方向の複数フレームを持たない**——気象庁側で実況と
短時間予測を統合済みの「現在の危険度」単一値のみを配信する（`validtime===basetime`）。

- キキクル4種（土砂災害・大雨・浸水・洪水）: `disaster`チップ配下の4ソースで、時刻
  スライダーとは連動しない——チップがONの間、選択中の共有時刻に関わらず`frames[0]`
  （現在値）があれば表示する。同じ`disaster`チップの雷・竜巻・落雷はスライダーに連動
  するため、1つのチップの中で連動する要素としない要素が同居する。
  `disaster`は他のweatherレイヤー（既定OFF）と異なり記述子が`defaultOn`を宣言する
  （防災級の情報はユーザー操作を待たず表示すべきという理由。[静的レイヤー・道路表示]
  (static-map-layers.md)参照）。地図上チップは複数同時にONにできるため、他の環境レイヤー
  （降水・風・標高図）を選んでも災害情報は地図に残る。
- 線状降水帯予測マップ: `precipitationNowcast`チップの4つ目のソース（`linearRainband`）。
  共有タイムラインの選択時刻が現在〜3時間先の範囲内（`isWithinFutureWindow`）のときだけ、
  他のソースと重ねて表示する（キキクルと異なりタイムラインと連動し続ける）。
  配信元は予測領域を**格子単位の単色（`rgb(255,40,0)`）で塗る**ため、地図上では矩形に
  見える。降水ナウキャストの細かい雨域と重なると描画不具合と受け取られやすいため、凡例の
  色をこの実際の塗り色へ合わせ、形状が予測領域であることを文言に含めている
  （凡例はレイヤーカタログの`readOnlyLegend`が持つ）。示すのは「今後3時間以内に発生するおそれ」
  であり、**今まさに発生している線状降水帯の雨域（配信元の`slmcs`系、当アプリは未使用）
  とは別物**。

## 共有タイムラインのラベル

目盛りは`RideConditionBar/departureTimeline.ts: buildDepartureTimeline`が、気象レイヤーの
取得結果に依存せず作る（出発時刻はレイヤーが1つもONでなくても選べる必要があるため）。
粒度は降水ナウキャスト・延長予報と同じ「直近60分は5分刻み、以降は1時間刻み」で、
選んだ時刻が各レイヤーのフレームへ素直に対応する。表示ラベルは常に日付を含める
（タイムラインが約48時間先まで日付をまたぐため）。正時判定は`getUTCMinutes()`で行う
（JSTは UTC+9:00ちょうどで分のずれが無いため）。

## 常設ヘッダーの天候表示（`WeatherPanel`）との違い

`WeatherPanel`（常設ヘッダー、`amedasWeatherIcon.ts`が天気分類を担う）は**アメダス実測値**
のみで構成し、予報とは独立にフェッチする。`TodayOutlook`（`weatherCode.ts`がWMOコードを
分類）は**MSM予報**（今日の最大降水量・最大風速・気温レンジ・日の出日没・天気の流れ）を
扱う。両者は別APIに依存する独立コンポーネントで、本モジュールの動的地図レイヤーとは別の
フェッチ経路を持つ。

**どちらに何を出すかは取得元ではなく値の性質で決める**。常設ヘッダーは走行中に何度も見る
瞬間値だけに絞り（幅が足りず溢れる）、1日1個の値はタップで開く`TodayOutlook`へ置く。
取得元での住み分け（実測はバー・外部予報はパネル）は、予報が気象庁MSMのローカル同期へ
移った時点で意味を失っている。

## 暗黙の前提

- 各named sourceのvisibility判定（`linearRainbandVisible`のような追加条件）は汎用機構
  （`dynamicWeather.ts`/`scene/groups/weather.ts`）の外、呼び出し側（`page.tsx`/
  `useDynamicWeatherLayers.ts`）が都度手書きする。汎用機構自身は渡された`visible`
  フラグをそのまま使うだけで、「なぜそのフラグなのか」を一切知らない。
- `frameIndexForTime`の許容誤差（`FRAME_RANGE_EPSILON_MS`=1秒）は「複数フレームから
  該当する1枚を選ぶ」用途専用であり、「常に1枚だけの現在値スナップショットを表示し続ける」
  キキクル系の性質とは噛み合わない。新しい「現在値スナップショットのみ」を持つ要素は
  共有タイムラインに乗せてはならない。**フレーム列は持つが予測が無い（観測だけ）要素**は
  その中間で、共有タイムラインに乗せたまま`observationIndexForTime`で選ぶ。
- `scene/groups/weather.ts`は「visibleとpayloadのどちらか一方でも欠ければ非表示」を
  常に守る。フェッチ未完了・取得失敗・選択時刻がデータ範囲外のいずれでも、古いフレームが
  一瞬でも見えないようにするための設計であり、この判定を呼び出し側で緩めてはならない。
- `windVector`の`arrow`（gridMark）は`windGrid`（粗い格子）でフレーム時刻を計算するが、
  実際の描画は`effectiveWindGrid`（詳細格子があればそちらを優先）を使う。フレーム時刻の
  計算元と実際に塗る値の元が別グリッドである点は初見では見落としやすい。
- **JMAプロキシ配下のURLはすべて`jmaNowcastFrames.ts: jmaProxyUrl(path)`で組み立てる**
  （タイルテンプレート・時刻一覧・GeoJSON・`scene/groups/weather.ts`の届く前の仮のURLの
  区別なく）。配信オリジン（`lib/tileBaseUrl.ts: tileBaseUrl()`）を付けるかどうかを
  呼び出し側の判断に委ねると、付け忘れた箇所だけがフロントのホスティング経由になる。
  常に絶対URLにする理由:
  `vectorTile`（洪水キキクル）はMapLibreがWeb Worker内で取得するため相対パスだと
  `new Request(url)`がWorkerのbase URLに対して解決できず例外になり、`rasterTile`も
  backend直接配信（`NEXT_PUBLIC_TILE_BASE_URL`）ではページと別オリジンになるため絶対URLが
  要る（`services/regionApi.ts`の`roadSurfaceTileUrl`等と同じ仕組み、
  [静的レイヤー](static-map-layers.md)「タイルの配信元」参照）。
  時刻一覧・GeoJSONはMapLibreではなくアプリ自身の`fetch()`で読むが、同じく絶対URLにする——
  **タイルURLは時刻一覧が返るまで確定しない**ため、ここでフロントのホスティングを経由すると
  往復1つぶんが初回表示のクリティカルパスへ直列に乗る。`tileBaseUrl()`は`window`を参照する
  ので、モジュール直下の定数ではなく呼び出し時に評価する関数
  （`jmaNowcastFrames.ts: jmaProxyUrl(path)`。時刻一覧の系統とファイル名は源泉の
  `jmaElements`が持つ）として持つ。
