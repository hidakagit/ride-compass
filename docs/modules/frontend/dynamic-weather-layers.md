# 地図: 動的気象レイヤー（frontend）

## 責務

気象庁由来の時刻変化する気象データ（MSM予報の風・降水延長予報、降水ナウキャスト/
降水短時間予報・雷・竜巻・キキクル・線状降水帯予測マップ）を地図上に表示する共通機構と、
各要素固有のデータ層。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `features/map/layers/dynamicWeather.ts` | 共通契約（型・共有タイムライン・状態管理の型・純粋関数） |
| `lib/time.ts` | 画面に出す時刻の扱い（日本時間の暦と時刻・書式・日時の入力欄との変換）と、時刻の並びから最も近いコマを引く関数。気象レイヤーと出発時刻は同じ表記・同じ引き方を使う |
| `features/map/layers/weatherSources.ts` | 源泉の宣言（`mapDisplay.weatherElements`）を名前付きソースへ束ね、段を1本の時系列へつなぎ、源泉が要素ごとに宣言する規則で選んだ時刻に描くコマを選ぶ |
| `features/map/layers/jmaDelivery.ts` | 気象庁の配信のパス構造・時刻一覧の取得と読み方・コマのタイルと地点（GeoJSON）のURL |
| `features/map/layers/precipitationNowcast.ts` | 降水の色の段・凡例と、自前の格子の降水の塗り（gridFill） |
| `features/map/layers/windLayer.ts`・`windArrowIcon.ts` | 風と降水が共有する格子の扱い（今より前を落とす・取り損ねた地点を補う・詳細格子の間隔と範囲）と、風の矢印（gridMark）・Canvas 2Dアイコン描画 |
| `features/map/layers/lidenIcon.ts` | 落雷の地点の記号（Canvas 2Dアイコン描画） |
| `features/map/layers/jmaTileIndex.ts` | 在否インデックスの解釈（URL解析・「空だと確認済み」の判定、純ロジック） |
| `features/map/layers/jmaTileProtocol.ts` | `jmatile://`スキームのMapLibreプロトコル。空と分かっているタイルをネットワークへ出さずに透明タイルで返し、配信の失敗を要素ごとに記録して購読できるようにする |
| `features/map/useJmaTileIndex.ts` | 在否インデックスの定期取得 |
| `features/map/scene/groups/weather.ts` | 動的気象の描き方。何を描くか（チップid・名前付きソース・描き方の種類・配信元）は源泉の`mapDisplay.weatherElements`をループして受け取り、ここは要素ごとの見た目（`paint`・`layout`・`filter`・記号の絵）だけを持つ。ソース名（`weatherSourceId`）・ソースの宣言・レイヤー・記号の絵の登録（`WEATHER_ICONS`）はこの2つから導かれる |
| `features/map/scene/applyToMap.ts`（`weatherStateFrom`・`weatherPayloadFrom`） | `dynamicWeather`（チップid→名前付きソース→表示・中身）を宣言の入力へ移す。JMAタイルのURLへ`jmatile://`スキームを付ける |
| `features/map/useDynamicWeatherLayers.ts`・`useWeatherGrid.ts`・`features/conditions/useWeatherConditions.ts` | 状態管理・フェッチ。動的気象は要素を名指さず、表示中の名前付きソースをループして段の種類（配信元のタイル・配信元の地点・自前の格子）ごとに1つずつの実装で描画内容を作る。定期取得は`usePolledFetch`（配信元の時刻一覧・粗い風格子）、現在地に追随する取得は`useWeatherConditions`内の`useLocationFetch`が骨格を持ち、個々のフェッチはfetcherだけを渡す。取り直す間隔（アメダス・在否インデックス・風格子）はbackendの宣言が生成物`refresh-intervals.json`で配る（新しい値が出る間隔そのもの。配信元の時刻一覧の間隔は`jmaElements[].refreshIntervalMs`）。「降っていない」「無風」の境も生成物`weather-scales.json`から読み、画面は持たない |
| `features/map/usePolledFetch.ts` | 「マウント時に即座に1回フェッチ＋以降intervalMsごとに再フェッチ、cancelledフラグで古いレスポンスの反映を防止」という、定期取得（配信元の時刻一覧・粗い風格子）が共有するフェッチ骨格の共通実装 |
| `features/conditions/WeatherPanel/WeatherPanel.tsx`・`amedasWeatherIcon.ts`・`weatherCode.ts`・`features/conditions/TodayOutlook/TodayOutlook.tsx`・`features/conditions/WarningBadge/WarningBadge.tsx` | UI（警報バッジの出所ごとの段階の呼び名と色は、backendの宣言`domain/warning_display.py`が生成物`vocabulary.ts`で配る） |
| `services/weatherApi.ts`・`types/weather.ts` | API呼び出し・型定義 |

## 共通契約

1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（`WIND_GRID_BBOX`、間隔は粗い格子の
   `windLayer.ts: WIND_GRID_SPACING_DEG`と、ズームの段ごとの詳細格子`windGridDetailSpacingDegForZoom`）を共有する。
   詳細格子の段の境界と間隔は見た目の判断なので画面が持ち、backendは下限（生成物の`detail_min_spacing_deg`）以上の
   間隔を受け付ける。連続にせず段に分けるのは、同じ段の中では間隔が変わらず、取り損ねた点を前回の値で補えるため
   （`useWeatherGrid.ts`は間隔が変わった回だけ補わない）。
   フェッチも共有（`features/map/useWeatherGrid.ts`、風の矢印と降水延長予報のどちらか一方でも
   ONなら1回のフェッチで両方をカバーする）。格子の値はbackendが気象庁MSM（手元へ同期したファイル）から
   取り、矢印の描画は自前で持つ——GPLv2のライブラリにも気象庁の非公式の配信にも依存しない。
2. **表現の型は決まっている**: 格子中央にマークを出す（`gridMark`、風の矢印）、格子/タイル境界を
   指定色で塗る（`gridFill`、降水延長予報の面塗り）、配信元が描画済みの画像を
   重ねる`rasterTile`（気象庁ナウキャスト・降水短時間予報・雷・竜巻・キキクルの土砂/大雨/
   浸水・線状降水帯予測マップ）。加えて洪水キキクルのみ、配信元のMapbox Vector Tile
   （.pbf）をMapLibre標準のvectorソース+lineレイヤーでそのまま描画する`vectorTile`
   （feature-state・GeoJSON変換は不要）。
3. **時刻は共有state1つ**: 表示時刻は走行条件の出発時刻そのもの（`features/conditions/useDepartureTime.ts`の
   `at`。条件バー`RideConditionBar`が書き換え、選ぶまでは5分刻みの「今」へ追従する）で、
   このフックは状態を持たず受け取るだけにする——出発時刻は生成リクエストと専用配信軸も読む
   走行条件で、気象レイヤーの持ち物ではない。各ソースは、**源泉が要素ごとに宣言する規則**
   （`frameRule`、backendの`domain/weather_elements.py`）で選択時刻に対応する自分のコマを選ぶ
   （`weatherSources.ts: selectFrame`）。既定の規則（`nearest`）は`frameIndexForTime`で、
   選択時刻が自分のデータ範囲外なら何も描画しない。「現在」の単一値だけを配る要素
   （キキクル・線状降水帯予測マップ）はこのタイムラインに乗らない（下記「特殊系」参照）。
   **予測を持たず観測だけが届く要素（雷放電位置データ）は`observationIndexForTime`を
   使う**——配信の遅れ（実測5〜10分）のぶん共有時刻が最新フレームより後ろに来るのが常態で、
   範囲外で描かない規約をそのまま当てると常に何も描かれない。遅れのぶんは最新の観測を出し、
   それより先（利用者が出発時刻を選んだ等）を指していれば描かない
   （遅れの幅は源泉が規則の`window_minutes`で宣言する）。
   **利用者が出発時刻を選ぶまでは「今」へ張り付き、時間の経過とともに進む**（`steppedNow`、
   5分刻み）。選んだ後はその時刻を保ち、「今」ボタンで張り付きへ戻る（`handleDynamicLayerNow`。
   **現在時刻を`setDynamicLayerTargetTime`へ渡すのでは代用にならない**——その値でピン留め
   され、以後は追従しない）。張り付かせないと、
   実況由来のフレーム列は先頭が更新のたび前進するのに共有時刻だけが取り残され、
   `frameIndexForTime`が範囲外を返して降水・雷・竜巻・雷放電が黙って描画を止める
   （利用者からは「雨が降っていない」と区別がつかない）。進める刻みを5分より細かくしても、
   出発時刻として選べる値自体が5分刻みのためどのレイヤーが選ぶフレームも変わらず、
   共有時刻をキーに持つ取得（`useDedicatedWayValues`）だけが無効化される。
4. **データ取得の差異はデータ層で吸収**: `weatherSources.ts`が源泉の宣言から名前付きソースの
   段（1つにつきN個ありうる）を1本の時系列へつなぎ、`useDynamicWeatherLayers.ts`が段の種類
   （配信元のタイル・配信元の地点・自前の格子）ごとに1つずつの実装でコマの描画内容
   （`DynamicWeatherRenderPayload`）を作る。表示層（`MapView.tsx`とsceneの`groups/weather.ts`）は
   ペイロードの`kind`しか見ない。

## 表示層の実装（`scene/groups/weather.ts`）

```
useDynamicWeatherLayers（フック、features/map/view/useMapView.ts経由）
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

JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。`features/map/useJmaTileIndex.ts`が
backendの`GET /api/jma-tile-index`（[気象・動的レイヤー](../backend/weather-dynamic-layers.md)
「在否インデックス」節。応答の型は`types/route.ts`が再exportする生成型
`JmaTileIndexResponse`で、`features/map/layers/jmaTileIndex.ts`は構造を手書きしない）を定期取得し、`features/map/layers/jmaTileProtocol.ts`が`maplibregl.addProtocol`で
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

**取りこぼしより空振りを選ぶ**: 判断がつかない場合（インデックス未取得・要素のフレーム
（`basetime`・`validtime`・`member`。1つの`basetime`に実況と複数の予測が載るため3つで照合する）が
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

どのチップのどの名前付きソースが、どの段から・どの読み方で・どの規則で描かれるかは源泉の宣言
（生成物`mapDisplay.weatherElements`）が持ち、画面は一覧を持たない。代表例: 降水の`main`は配信元の
ラスタ2段（降水ナウキャスト→降水短時間予報）の先を自前の格子の塗りが継ぎ、同じチップの
`linearRainband`は「現在」の単一値を窓の間だけ重ねる。風の矢印は走行方位に依存しない矢印のみで、
走行方位への依存を含む向かい風/追い風の強さは[地図: 軸・ルート色分け](map-axis-coloring.md)の
専用way値配信軸が担う。

`disaster`（災害）は源泉がチップ`disaster`として宣言したソース（`dynamicWeather.ts: DisasterSourceKey`）を1チップへまとめたグループで、全ソースが1つの`showDisaster`に
連動する。同じ段（描き方ごとに決まる。`weather.ts: TIER_OF`）の中では源泉の宣言
（backendの`domain/weather_elements.py: WEATHER_ELEMENTS`）の並び順が重なり順になるため、面（キキクル3種・雷・竜巻のラスタ）を下に、局所的で見落としやすい線（洪水）・点
（落雷）を上に置く。面同士が重なった領域は混色し危険度5段階を読み取れなくなるが、危険度
ゼロの領域は配信元のタイルが透明のため平常時の地図の見た目は変わらない。**この並び順が
効くのは面どうし・線どうしの間だけである**——面は基礎地図の線・記号より下へ差し込まれ
（[静的レイヤー・道路表示](static-map-layers.md)参照）、線・点は最前面へ積まれるため、
面をどれだけ濃くしても線・点はその上に残る。気象庁は危険度を
ラスタ画像でしか配信せず現在の警戒レベルを返すAPIを持たないため、「重なっているなら最も
危険な1枚だけ出す」といった自動制御は実装できない。代わりに、チップの▶パネルの
「表示する情報」でソースを個別に間引ける——行（要素の呼び名）は源泉の要素の宣言
（backend `domain/weather_elements.py: WEATHER_ELEMENTS`の`label`）から`scene/legends.ts:
disasterSourceLegendAxis`が作り、隠したソースは他の凡例絞り込みと同じ保存先
（`useMapView`が持つ。チップidを鍵にする）へ入って、`hiddenSources`としてこのフックへ渡る。
ソースごとの`visible`だけでなく、非表示のソースが読む配信要素は、同じ配信要素を読む表示中の
ソースが無ければ取りに行かない（「表示中のものだけ叩く」方針）。取りに行く単位は配信要素
そのもので、画面は単位の対応表を持たない。同じ時刻一覧のファイルを読む配信要素どうしは、
未解決の取得を共有して往復を1回に畳む（下記）。

**配信元の要素id・パスの系統・時刻一覧の在り処と読み方はデータ層も源泉から引く**（`jmaDelivery.ts`）。
データ層は要素を名指さず、URLの要素id・系統・拡張子（ベクタなら`.pbf`）と時刻一覧のURLは
`mapDisplay.weatherElements`の`jmaElements`・`kind`から組み立てる。要素idが変われば画面は新しいidで
取りに行く（手で持っていると、古いidのタイルが404→空タイルとなり地図から黙って消える）。
時刻一覧（`targetTimes*.json`）の中から自分の行を選ぶ`elements`の照合も同じ要素idを使う。
行をコマにする読み方（`reader`）も源泉が配信要素ごとに宣言する——同じ系統・同じファイルでも、
実況＋予測（その要素の行を時刻順に並べ、最新の実況より前を捨てる）・数値予報のラン（系列ごとに
有効時刻を複数持つ最新のランだけ）・「現在」の単一値（最新の1行）で並び方が違う。

**1つの名前付きソースが、選んだ時刻によって別の配信要素から届くことがある**——降水の`main`ラスタは
60分先までが降水ナウキャスト、その先15時間先までが降水短時間予報で、配信要素も系統も時刻一覧も違う。
源泉は`jmaElements`を時刻の段の順（近い時刻から）に並べ、同じ名前付きソースを名乗る後続の要素
（自前の格子の塗り等）がさらに先の段になる。`weatherSources.ts: sourceTimeline`は、各段について
前の段の最後のコマより後の時刻だけを継いで1本にする（近い時刻は精度の高い前の段が持ち、二重に
出さない。途中の段が取れていなければ、その前の段の直後から次の段が継ぐ）。MapLibreのソースは
1本のままURLだけが差し替わるので、ソースのズーム範囲は段の間で一致している必要があり、backendが
生成時に確かめる（食い違えば生成が落ちる）。同じ名前付きソースの要素はコマの規則も同じで、
backendのテストが全要素で確かめる。

時刻一覧が複数のファイルに分かれる要素（降水ナウキャストの実況と予測）は、`fetchJmaTargetTimes`が
全ファイルの行をつなげて返し、一部のファイルだけ取れなければ残りで部分的な時系列を返す
（全部取れなかったときだけ失敗）。同じファイルを同時に取りに行く要素（キキクルの各要素、
降水短時間予報と線状降水帯予測マップ）は、未解決のフェッチを共有して往復を1回に畳む。

配信元から取る記号の段（`gridMark`、例: 落雷の地点）は、他の段が既に手元にある格子データ・
タイルURLテンプレートから同期的にペイロードを組み立てるのに対し、配信元が地点をGeoJSONで
配るため、選んだコマが変わるたびに`jmaDelivery.ts: fetchJmaPointGeojson`を非同期に取りに行く。
`useDynamicWeatherLayers.ts`は取れた中身を配信要素と時刻の鍵で持ち、選んでいるコマの鍵と一致する
ときだけpayloadへ反映する——scrub中に古いフェッチが後から解決しても、直前の時刻のデータを新しい
時刻の表示へ混ぜない。地点ごとの強弱を示す値を配信元が持たないため、gridMarkが必須とする
`valueProperty`（`JMA_POINT_VALUE_PROPERTY`）は固定値1を全featureへ合成し、`minScale===maxScale`に
よりicon-sizeはズームのみに依存する。

## 新しい動的要素を追加する1本道

1. backend: `domain/weather_elements.py: WEATHER_ELEMENTS`へ宣言を1件足す（チップid・名前付き
   ソース・描き方の種類・気象庁の配信要素id・選んだ時刻に描くコマの規則、自前の格子から描くなら
   読む値）。タイルで描くなら`domain/jma_tile_specs.py:
   JMA_TILE_SPECS`へ配信元の仕様（パスの系統・ズーム・ベクタのレイヤー名）を1件足す。
   配信元から取るがタイルでは描かない要素（落雷のGeoJSON等）は、同じファイルの
   `JMA_NON_TILE_PATH_GROUPS`へパスの系統だけを足す。配信元から取るなら、同じファイルの
   `JMA_TARGET_TIMES_READERS`へ時刻一覧の読み方を1件足す（無いと生成が落ちる）。
   新しいチップidを名乗ればチップも増える（`WEATHER_LAYER_GROUPS`はこの宣言から導かれ、
   生成物経由で`DynamicWeatherLayerId`・`MapLayerId`になる）。`scripts/export_openapi.py`で
   生成物（`mapDisplay.ts`の`weatherElements`）を作り直す。自前のMSM格子から描くなら、
   `wind_grid.py`の`WindGridPoint`へ値フィールドを、`msm_client.py`の`FORECAST_VARIABLES`へ
   MSM変数を足す（この経路は風・降水延長予報限定）
2. `features/map/scene/groups/weather.ts`: 配信元のラスタ（`rasterTile`）なら何も足さない
   （見た目は共通の1つ）。それ以外は`DRAWINGS`へ見た目（`paint`・`layout`・`filter`・記号）を
   1件足す——鍵は生成物から導かれるため、足し忘れると型検査が落ちる。ソース名・ソースの宣言・
   レイヤー・記号の絵の登録はここから導かれる
3. 新しいチップを足したときだけ: backendの`domain/map_display.py`へ種別・情報源（`ownFetch`）・
   性質（`dynamic`）を1行、`mapLayers.ts`へ記述子（アイコン・凡例）を1エントリ足す
4. 新しい種類を足したときだけ: 時刻一覧の読み方なら`jmaDelivery.ts`の読み方の表、コマの規則なら
   `weatherSources.ts: selectFrame`、格子の値なら`useDynamicWeatherLayers.ts: GRID_PAYLOAD`へ1つ足す
   （種類の集合は生成物から導くため、足し忘れは型検査が落ちる）。取得・時系列・描画内容・取得状態は
   宣言の一覧をループして作るため、要素を足すだけならフロントの手書き作業は無い。

契約テスト（`scene/scene.state.contract.test.ts`の全部を載せた状態）の母集団も生成物の
`mapDisplay.weatherElements`で、1で足した要素はそのまま検査の対象になる。

## データ取得状態

動的気象のチップ（`DynamicWeatherLayerId`）全てが、`useDynamicWeatherLayers.ts`から
`mapLayers.ts: deriveFetchLayerStatus(loading, error, hasPayload, hasFetched)`という同じ
純粋関数を通り、`LayerDataStatus`（"loading"/"empty"/"error"、`mapLayers.ts`）を1つ返す
（判定順序はエラー中 > 読込中 > 未取得[undefined] > 読込済みだが値なし、
`useLayerDataStatus.ts: computeLayerDataStatus`と同じ）。チップの表示中のソースが読む配信要素の
読み取り結果（まだ無ければ読み込み中・失敗があれば失敗）と、格子を読むソースがあれば
`useWeatherGrid`の状態から決め、`hasPayload`は選択中の共有時刻に対応するpayloadが`undefined`で
ないかで決まる。`hasFetched`は一度でも取得が完了したかで、初回取得前を「値なし（empty）」と
誤って見せないために要る。

配信元の時刻一覧は、表示中のソースが読む配信要素をまとめて1本で取り直す。間隔はそのうち
最も更新の速い系統の更新間隔（源泉の`refreshIntervalMs`、`domain/jma_tile_specs.py:
JMA_REFRESH_INTERVAL_SECONDS`）に合わせる——遅い系統を早めに取り直すぶんには古い表示にならない。

**MapLibreのソースイベント経由の系統（`MapView.tsx: buildLayerDataSources`）は
動的気象レイヤーの対象外**——実際の外部フェッチは自前のJSコード（`usePolledFetch`等）で
行われ、結果を`map.getSource(id).setData(...)`/`setTiles(...)`で流し込むだけのため、
MapLibre側のソースイベントはフェッチの待ち時間・失敗を観測できない（`kind`が
raster/vectorTile[実タイル取得がMapLibre自身の責務]であっても、フレーム一覧
[targetTimes.json等]の取得自体は自前のJSフェッチのため、そちらが失敗すると
payloadが`undefined`のままレイヤーが非表示になり続け、MapLibre側には何のイベントも
発生しない）。`elevation`（国土地理院のラスタタイル、静的データで自前のJSフェッチ層を
持たない）だけがT87の対象のまま残る。

チップは複数の名前付きソースを束ねるため、表示中のソースのどれかが描けていれば空とせず、
どれかの取得が失敗していれば失敗、どれかがまだ取れていなければ読み込み中とする。

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

算出した`dynamicWeatherDataStatus`は`useMapView`が地図から上がる取得状態（ソースイベント側）と
マージし、地図上チップ（`MapOverlayControls`の状態ドット）へ渡す
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
（タイムラインが約48時間先まで日付をまたぐため）。正時の目盛りには、日本時間の偶数時だけ
時刻を書く（毎コマ書くと文字が重なる）。

**「今」の目盛りを選んだら、その時刻に固定せず「今」への追従へ戻す**（「現在」ボタンと同じ）。
固定すると、放置するうちに選んだ時刻が過去になり、予報のレイヤー（「今」より前のコマを
落とす）の範囲から外れて表示が消える。時刻を選んでいない間の出発時刻は、5分刻みの「今」へ
追従する（`features/conditions/useDepartureTime.ts`）——画面を開いたまま放置しても置いていかれない。

## 常設ヘッダーの天候表示（`WeatherPanel`）との違い

`WeatherPanel`（常設ヘッダー）は**アメダス実測値**のみで構成し（天気はbackendが実測から導いたWMOコードで届き、
`amedasWeatherIcon.ts`は「晴れ」を昼夜で描き分けるだけ）、予報とは独立にフェッチする。`TodayOutlook`（`weatherCode.ts`がWMOコードを
分類。分類と名前はbackendの宣言〔`domain/weather_display.py: WEATHER_CATEGORIES`〕が生成物`vocabulary.ts`で配り、
画面が持つのは分類ごとのアイコンだけ）は**MSM予報**（今日の最大降水量・最大風速・気温レンジ・日の出日没・天気の流れ）を
扱う。両者は別APIに依存する独立コンポーネントで、本モジュールの動的地図レイヤーとは別の
フェッチ経路を持つ。

**どちらに何を出すかは取得元ではなく値の性質で決める**。常設ヘッダーは走行中に何度も見る
瞬間値だけに絞り（幅が足りず溢れる）、1日1個の値はタップで開く`TodayOutlook`へ置く。
取得元での住み分け（実測はバー・外部予報はパネル）は、予報が気象庁MSMのローカル同期へ
移った時点で意味を失っている。

## 暗黙の前提

- 名前付きソースを描くかどうかの追加条件（線状降水帯予測マップの窓等）は源泉のコマの規則で
  決まり、`useDynamicWeatherLayers.ts`がpayloadの有無へ畳む。描き方の宣言
  （`scene/groups/weather.ts`）は渡された`visible`・`payload`をそのまま使うだけで、
  「なぜそうなのか」を一切知らない。
- `frameIndexForTime`の許容誤差（`FRAME_RANGE_EPSILON_MS`=1秒）は「複数フレームから
  該当する1枚を選ぶ」用途専用であり、「常に1枚だけの現在値スナップショットを表示し続ける」
  キキクル系の性質とは噛み合わない。新しい「現在値スナップショットのみ」を持つ要素は
  共有タイムラインに乗せてはならない。**フレーム列は持つが予測が無い（観測だけ）要素**は
  その中間で、共有タイムラインに乗せたまま`observationIndexForTime`で選ぶ。
- `scene/groups/weather.ts`は「visibleとpayloadのどちらか一方でも欠ければ非表示」を
  常に守る。フェッチ未完了・取得失敗・選択時刻がデータ範囲外のいずれでも、古いフレームが
  一瞬でも見えないようにするための設計であり、この判定を呼び出し側で緩めてはならない。
- 自前の格子の段は粗い格子（`useWeatherGrid`の`grid`）でコマの時刻を作るが、実際の描画は
  `effectiveGrid`（詳細格子があればそちらを優先）を使う。コマの時刻の計算元と実際に塗る値の元が
  別グリッドである点は初見では見落としやすい。
- **JMAプロキシ配下のURLはすべて`jmaDelivery.ts: jmaProxyUrl(path)`で組み立てる**
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
  （`jmaDelivery.ts: jmaProxyUrl(path)`。時刻一覧の系統とファイル名は源泉の
  `jmaElements`が持つ）として持つ。
