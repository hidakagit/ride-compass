# 地図: 動的気象レイヤー（frontend）

## 責務

気象庁由来の時刻変化する気象データ（数値予報モデルMSMの計算値の風・降水、降水ナウキャスト/
降水短時間予報・雷・竜巻・キキクル・線状降水帯予測マップ・線状降水帯の雨域）を地図上に表示する共通機構と、
各要素固有のデータ層。

**数値予報モデル（MSM）から作る表示は「予報」と呼ばない**。画面の文言（地図チップの説明・区間の風・
「今日」のパネル等）では「モデルの計算値（予報ではなく誤差を含みうる）」と出し、MSMの値から天気
（晴れ・雨等）を計算して出さない——気象庁の公式の説明が、どちらも予報業務の許可の対象と書いている
（[data-sources.md](../../architecture/data-sources.md)「気象業務法の予報業務許可」節）。気象庁が出したものを
そのまま重ねる表示（降水ナウキャスト・降水短時間予報・警報等）は、気象庁の呼び方のまま出してよい。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `features/map/layers/dynamicWeather.ts` | 共通契約（型・共有タイムライン・状態管理の型・純粋関数） |
| `lib/time.ts` | 画面に出す時刻の扱い（日本時間の暦と時刻・書式・日時の入力欄との変換）と、時刻の並びから最も近いコマを引く関数。気象レイヤーと出発時刻は同じ表記・同じ引き方を使う |
| `features/map/layers/weatherSources.ts` | 源泉の宣言（`mapDisplay.weatherElements`）を名前付きソースへ束ね、段を1本の時系列へつなぎ、源泉が要素ごとに宣言する規則で選んだ時刻に描くコマを選ぶ |
| `features/map/layers/jmaDelivery.ts` | 気象庁の配信の時刻一覧の取得と読み方・コマのタイルと地物（GeoJSON）のURL（源泉のパスのテンプレートをコマで埋める）（配信の遅れを持つ要素は、まだ配信されていないコマを前の`basetime`へずらして読む）・地物の取得・タイルのURLの読み戻し |
| `features/map/layers/precipitationNowcast.ts` | 降水の色の段・凡例と、自前の格子の降水の塗り（gridFill） |
| `features/map/layers/windLayer.ts`・`windArrowIcon.ts` | 風と降水が共有する格子の扱い（取り損ねた地点を補う・時刻ごとに描く格子を選び点ごとに時刻で値を引く・詳細格子の間隔と範囲）と、風の矢印（gridMark）・Canvas 2Dアイコン描画 |
| `features/map/layers/lidenIcon.ts` | 落雷の地点の記号（Canvas 2Dアイコン描画） |
| `features/map/layers/jmaTileIndex.ts` | 在否インデックスの解釈（「空だと確認済み」の判定、純ロジック） |
| `features/map/layers/jmaTileProtocol.ts` | `jmatile://`スキームのMapLibreプロトコル。空と分かっているタイルをネットワークへ出さずに透明タイルで返し、配信の失敗を要素ごとに記録して購読できるようにする |
| `features/map/useJmaTileIndex.ts` | 在否インデックスの定期取得 |
| `features/map/scene/groups/weather.ts` | 動的気象の描き方。何を描くか（チップid・名前付きソース・描き方の種類・配信元）は源泉の`mapDisplay.weatherElements`をループして受け取り、ここは要素ごとの見た目（`paint`・`layout`・`filter`・記号の絵）だけを持つ。ソース名（`weatherSourceId`）・ソースの宣言・レイヤー・記号の絵の登録（`WEATHER_ICONS`）はこの2つから導かれる |
| `features/map/scene/applyToMap.ts`（`weatherStateFrom`・`weatherPayloadFrom`） | `dynamicWeather`（チップid→名前付きソース→表示・中身）を宣言の入力へ移す。JMAタイルのURLへ`jmatile://`スキームを付ける |
| `features/map/useDynamicWeatherLayers.ts`・`useWeatherGrid.ts`・`features/conditions/useWeatherConditions.ts` | 状態管理・フェッチ。動的気象は要素を名指さず、表示中の名前付きソースをループして段の種類（配信元のタイル・配信元の地点・自前の格子）ごとに1つずつの実装で描画内容を作る。取得の骨格（重複排除・定期の取り直し・読み込み中と失敗の状態）はTanStack Queryが持ち（[ページ全体構成](page-composition.md)「データ取得の骨格」）、配信元の時刻一覧・風格子（粗い格子と詳細格子）・在否インデックスは`refetchInterval`で、現在地に追随する取得は`useWeatherConditions`内の`useLocationFetch`（キーに位置を持つ）で取り直す。取り直す間隔（アメダス・在否インデックス・風格子）はbackendの宣言が生成物`refresh-intervals.json`で配る（新しい値が出る間隔そのもの。配信元の時刻一覧の間隔は`jmaElements[].refreshIntervalMs`）。「降っていない」「無風」の境も生成物`weather-scales.json`から読み、画面は持たない |
| `features/conditions/WeatherPanel/WeatherPanel.tsx`・`amedasWeatherIcon.ts`・`weatherCode.ts`・`features/conditions/TodayOutlook/TodayOutlook.tsx`・`features/conditions/WarningBadge/WarningBadge.tsx` | UI（警報バッジの出所ごとの段階の呼び名と色は、backendの宣言`domain/warning_display.py`が生成物`vocabulary.ts`で配る） |
| `services/weatherApi.ts`・`types/weather.ts` | API呼び出し・型定義 |

## 共通契約

1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（緯度・経度0度から数える。敷く範囲はbackendの対象範囲。間隔は粗い格子の
   `windLayer.ts: WIND_GRID_SPACING_DEG`と、ズームの段ごとの詳細格子`windGridDetailSpacingDegForZoom`）を共有する。
   詳細格子の段の境界と間隔は見た目の判断なので画面が持ち、backendは下限（生成物の`detail_min_spacing_deg`）以上の
   間隔を受け付ける。連続にせず段に分けるのは、同じ段の中では間隔が変わらず、取り損ねた点を前回の値で補えるため
   （`useWeatherGrid.ts`は同じ間隔で最後に届いた詳細格子から、今の範囲の中の点だけを補う。間隔の違う格子からは補わない）。
   フェッチも共有（`features/map/useWeatherGrid.ts`、風の矢印と降水の格子の段のどちらか一方でも
   ONなら1回のフェッチで両方をカバーする）。格子の値はbackendが気象庁MSM（手元へ同期したファイル）から
   取り、矢印の描画は自前で持つ——GPLv2のライブラリにも気象庁の非公式の配信にも依存しない。
2. **表現の型は決まっている**: 格子中央にマークを出す（`gridMark`、風の矢印）、格子/タイル境界を
   指定色で塗る（`gridFill`、降水の格子の段の面塗り）、配信元が描画済みの画像を
   重ねる`rasterTile`（気象庁ナウキャスト・降水短時間予報・雷・竜巻・キキクルの土砂/大雨/
   浸水・線状降水帯予測マップ）。加えて洪水キキクルのみ、配信元のMapbox Vector Tile
   （.pbf）をMapLibre標準のvectorソース+lineレイヤーでそのまま描画する`vectorTile`
   （feature-state・GeoJSON変換は不要）と、配信元がコマごとにGeoJSONで配る領域を塗らずに線で描く`outline`
   （線状降水帯の雨域。属性は読まない）。
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
   5分刻み）。選んだ後はその時刻を保ち、「今」ボタンで張り付きへ戻る（`useDepartureTime.ts: followNow`。
   **現在時刻を`useDepartureTime.ts: setAt`へ渡すのでは代用にならない**——その値でピン留め
   され、以後は追従しない）。張り付かせないと、
   実況由来のフレーム列は先頭が更新のたび前進するのに共有時刻だけが取り残され、
   `frameIndexForTime`が範囲外を返して降水・雷・竜巻・雷放電が黙って描画を止める
   （利用者からは「雨が降っていない」と区別がつかない）。進める刻みを5分より細かくしても、
   出発時刻として選べる値自体が5分刻みのためどのレイヤーが選ぶフレームも変わらず、
   共有時刻をキーに持つ取得（`useDedicatedWayValues`）だけが無効化される。
4. **データ取得の差異はデータ層で吸収**: `weatherSources.ts`が源泉の宣言から名前付きソースの
   段（1つにつきN個ありうる）を1本の時系列へつなぎ、`useDynamicWeatherLayers.ts`が段の種類
   （配信元のタイル・配信元の地物・自前の格子）ごとに1つずつの実装でコマの描画内容
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
重ねるかは自由で、見た目が`casing`を持つ線（線状降水帯の雨域の輪郭線）だけが、同じソースの縁取りの線を
同じ段で主の線の下へ1枚敷く。記号の縁取りは別レイヤーではなく`icon-halo-*`で出す（下の「空タイル要求の間引き」の後の段落）。

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

JMAタイル系ソースの`minzoom`/`maxzoom`・ベクタのレイヤー名は、源泉の宣言の`tile`
（`mapDisplay.weatherElements`）から受け取る（正本は
[気象・動的レイヤー](../backend/weather-dynamic-layers.md)の`domain/jma_tile_specs.py`）。
配信元は要素ごとに実データを持つズームが異なり、上限を超えると空タイルが返って地図から色が
消えるため、この値を画面側へ書かない。

`gridMark`（`scene/groups/weather.ts: markDrawing`）の縁取りは、主層と別のsymbolレイヤーではなく
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

`disaster`（災害）は源泉がチップ`disaster`として宣言したソースを1チップへまとめたグループで、全ソースがそのチップ1つの入/切に
連動する（凡例で個別に隠したソースだけは描かない。`useDynamicWeatherLayers.ts: isShown`）。同じ段（描き方ごとに決まる。`scene/groups/weather.ts: TIER_OF`）の中では源泉の宣言
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
そのもので、画面は単位の対応表を持たない。時刻一覧を取る単位はファイルで、同じファイルを読む
配信要素どうしは1つの取得を共有する（下記）。

チップの説明文と表示専用の凡例も要素の宣言から組み立てる（`mapLayers.ts`）。説明は要素の`label`を、描くコマの規則
（`frameRule.kind`）ごとにまとめて並べ、規則ごとの言い回し（時刻に連動・直近の観測・現在の危険度のみ）だけを画面が持つ。
凡例は要素が宣言する塗る段（`levelScale`。生成物`weather-scales.json`の鍵）ごとに1ブロックで、見出しはその段で塗る要素の
`label`の並び。段の数と名前は凡例に並ぶので説明文に書かない——要素を足す・名前や規則を変えると説明と凡例が追従し、
文だけが古くなることは無い。「表示する情報」の色見本も同じ`levelScale`の注意を促す段から引き、段を持たない要素
（落雷の地点）だけをソースの鍵で持つ（`scene/legends.ts`）。

**配信元の要素id・パスの系統・時刻一覧の在り処と読み方はデータ層も源泉から引く**（`jmaDelivery.ts`）。
データ層は要素を名指さず、配信元のパスの形も持たない。コマのURLは`mapDisplay.weatherElements`の
`jmaElements[].urlTemplate`（系統・要素id・拡張子まで埋まり、コマの項目`{basetime}`等とタイル座標`{z}/{x}/{y}`が
残ったテンプレート。項目名は`jmaDelivery.ts: JmaFrame`の項目名と同じ）をコマで埋めて作り、タイル座標は地図ライブラリが
埋める。時刻一覧は`jmaElements[].targetTimesPaths`から取る。要素idやパスの形が変われば画面は新しい形で
取りに行く（手で持っていると、古い形のタイルが404→空タイルとなり地図から黙って消える）。タイルのURLを読み戻す側
（在否インデックスの判定・配信の失敗の記録）も同じテンプレートに当てて読む（`jmaDelivery.ts: readJmaTileUrl`）——
どのテンプレートにも当たらないURLは読めないものとして扱い、取りに行く側へ倒す。
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

時刻一覧はファイル（`jmaElements[].targetTimesPaths`の1つ）ごとにキャッシュのキーを持ち、同じファイルを読む要素
（キキクルの各要素、降水短時間予報と線状降水帯予測マップ）は1つの取得と1つの取り直しの周期を共有する——要素ごとに
取ると、後から表示した要素の周期がずれて同じファイルを周期ごとに2回取る。時刻一覧が複数のファイルに分かれる要素
（降水ナウキャストの実況と予測）は、`useDynamicWeatherLayers.ts`が読めたファイルの行を宣言の順につないで
`jmaFramesOf`で読み、一部のファイルだけ取れなければ残りで部分的な時系列を作る（全部取れなかったときだけ失敗）。

配信元から取るタイルでない段（`gridMark`の落雷の地点・`outline`の線状降水帯の雨域）は、他の段が既に手元にある
格子データ・タイルURLテンプレートから同期的にペイロードを組み立てるのに対し、配信元が地物をコマごとのGeoJSONで
配るため、選んだコマが変わるたびに`jmaDelivery.ts: fetchJmaGeojson`を非同期に取りに行く。
`useDynamicWeatherLayers.ts`は取れた中身を配信要素と時刻の鍵で持ち、選んでいるコマの鍵と一致する
ときだけpayloadへ反映する——scrub中に古いフェッチが後から解決しても、直前の時刻のデータを新しい
時刻の表示へ混ぜない。取れなかったコマの地物は描かず、チップの状態を失敗にする（下の「データ取得状態」）——描かない
だけでは、落雷が無いことと地点を取れていないことが同じに見える。配信元の404も失敗に数える（次の段落）。

**配信の遅れを持つ要素は、時刻一覧のコマをそのまま取らない**——配信元はコマの地物を配信するまで404を返し、
配信した後は地物が無くても空の集まりを返す。線状降水帯の雨域は、時刻一覧が最新の`basetime`の実況と20分先までを載せる
間ずっとその`basetime`を配信しておらず（配信は`basetime`の約13.5分後、その約1分後に時刻一覧の最新が次の`basetime`へ
進む。2026-09-28の実測）、1つ前の`basetime`が実況と30分先までの予測を配っている。公式の画面はこれを要素ごとの
`dataDelay`（10分）で扱い、その要素の最新の`basetime`から遅れの幅に入るコマを、幅の端まで前の`basetime`へずらして読む
（実況のコマはずらした先の実況になる）。画面も同じずらし方をする（源泉の`jmaElements[].dataDelayMinutes`、
`jmaDelivery.ts: jmaFramesOf`）ので、時刻一覧の最新の予測の先端でも前の`basetime`の30分先の地物を描き、
取りに行くのは配信済みのコマだけになる。したがって地物の404は「取れていない」で、チップを失敗にする。

backendの中継は地物の404を覚えず、ブラウザにも覚えさせない（[気象・動的レイヤー（backend）](../backend/weather-dynamic-layers.md)
「配信前の地物の404は覚えない」）——時刻の食い違いで配信前のコマを取りに行く利用者がいても、配信された後の取得に当たらない。

地点ごとの強弱を示す値を配信元が持たないため、gridMarkが必須とする
`valueProperty`（`JMA_POINT_VALUE_PROPERTY`）は固定値1を全featureへ合成し、`minScale===maxScale`に
よりicon-sizeはズームのみに依存する（線の地物にも合成されるが、線の見た目は読まない）。

## 新しい動的要素を追加する1本道

1. backend: `domain/weather_elements.py: WEATHER_ELEMENTS`へ宣言を1件足す（チップid・名前付き
   ソース・描き方の種類・気象庁の配信要素id・選んだ時刻に描くコマの規則、自前の格子から描くなら
   読む値、配信元が段の色を焼き込むなら塗る段`level_scale`）。配信元から取るなら`domain/jma_tile_specs.py: JMA_ELEMENTS`へ配信要素の宣言を1件足す
   （パスの系統・時刻一覧のファイルと読み方、タイルで描くならズームとベクタのレイヤー名、公式の画面の設定が
   `dataDelay`を持つなら配信の遅れ。宣言が無いと生成が落ちる）。
   新しいチップidを名乗ればチップも増える（`WEATHER_LAYER_GROUPS`はこの宣言から導かれ、
   生成物経由で`DynamicWeatherLayerId`・`MapLayerId`になる）。`scripts/export_openapi.py`で
   生成物（`mapDisplay.ts: weatherElements`）を作り直す。自前のMSM格子から描くなら、
   `wind_grid.py: WindGridPoint`へ値フィールドを、`msm_client.py: MsmSeries`へ項目を、
   `FORECAST_VARIABLES`へMSM変数とその項目の対応を足す（この経路は風・降水の格子の段限定）。MSMから描く要素の
   説明文は「予報」と呼ばない（上の「責務」）
2. `features/map/scene/groups/weather.ts`: 配信元のラスタ（`rasterTile`）なら何も足さない
   （見た目は共通の1つ）。それ以外は`DRAWINGS`へ見た目（`paint`・`layout`・`filter`・記号）を
   1件足す——鍵は生成物から導かれるため、足し忘れると型検査が落ちる。ソース名・ソースの宣言・
   レイヤー・記号の絵の登録はここから導かれる
3. 新しいチップを足したときだけ: backendの`domain/map_display.py`へ種別・情報源（`ownFetch`）・
   性質（`dynamic`）を1行、`mapLayers.ts`へ記述子（アイコン・凡例）を1エントリ足す
4. 新しい種類を足したときだけ: 時刻一覧の読み方なら`jmaDelivery.ts`の読み方の表と、同じ読み方でプリウォームの
   フレームを選ぶbackendの`jma_tile_specs.py: read_target_times`（[動的気象レイヤー（backend）](../backend/weather-dynamic-layers.md)
   「定期プリウォーム」）と、両方が同じコマを出すことを確かめる表の場面（`scripts/cross_language_expectations.py: jma_expectations`）、コマの規則なら
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
読み取り結果（まだ無ければ読み込み中・失敗があれば失敗）と、配信元の地物を描くソース（落雷の地点・線状降水帯の
雨域等）が選んだコマの地物の取得（取っている間は読み込み中・失敗は失敗）と、格子を読むソースがあれば
`useWeatherGrid`の状態から決め、`hasPayload`は選択中の共有時刻に対応するpayloadが`undefined`で
ないかで決まる。`hasFetched`は一度でも取得が完了したかで、初回取得前を「値なし（empty）」と
誤って見せないために要る。

配信元の時刻一覧はファイルごとに取り直す。間隔はそのファイルを読む表示中の配信要素のうち
最も更新の速い系統の更新間隔（源泉の`refreshIntervalMs`、`domain/jma_tile_specs.py:
JMA_REFRESH_INTERVAL_SECONDS`）に合わせる——遅い系統を早めに取り直すぶんには古い表示にならない。
取り直しに失敗している間は、そのファイルの前の行を使わずに失敗として数える（古い一覧のコマは表示時刻から外れていく）。
格子は失敗しても前の格子を残し、失敗の文言を添える。

**チップを消している間は「まだ取りに行っていない」**（`hasFetched`が偽）で、再び出したときは前に取った時刻一覧・格子
（キャッシュに残る間。読み手が消えてから既定の5分）をすぐに出し、裏で取り直す——読み込み中を経ない。前の値は
定期の取り直しの周期の間に出している値と同じ種類の古さで、取り直しが届けば置き換わる。

**MapLibreのソースイベント経由の系統（`MapView.tsx: buildLayerDataSources`）は
動的気象レイヤーの対象外**——実際の外部フェッチはアプリ自身の取得（TanStack Query）で
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
表示中のpayloadのタイルURLと突き合わせて、当たったチップを`"error"`にする。記録は配信要素ごとに、
失敗したタイルのURLを源泉のテンプレートで読み戻したコマのテンプレート（payloadの`tileUrlTemplate`と同じ文字列。
basetime・validtimeを含む）で持つため、フレームが進んで取得できるようになれば自然に外れる。グループ配下を機械的に走査するので、要素やチップが
増えても足すコードは無い。

算出した`dynamicWeatherDataStatus`は`useMapView`が地図から上がる取得状態（ソースイベント側）と
マージし、地図上チップ（`MapOverlayControls`の状態ドット）へ渡す
（[静的地図レイヤー](static-map-layers.md)「レイヤーのデータ取得状態」節参照）。

## 線状降水帯の雨域

`precipitationNowcast`チップの`linearRainbandArea`・`linearRainbandAreaForecast`（公式の画面の既定の表示
「代表楕円表示方式」が読む2つの配信要素）。下の線状降水帯予測マップと違い単一値ではなく、雷・竜巻と同じ時刻一覧に
実況と予測の行で載るため、共有タイムラインに乗る（`nearest`。取るコマは上の「配信の遅れを持つ要素」のとおりずらす）。どちらの配信要素も実況と予測の
両方の時刻に地物を持ち、公式の画面は2つを同じ見た目（赤い実線・白い縁取り・塗りなし）で重ねてどちらが実況かを
描き分けないため、画面もそうする（破線は公式の詳細表示の予測だけで、既定の表示は使わない）。色・太さは公式の
描画定義の値を源泉（`domain/weather_display.py`・`domain/map_display.py`）が持つ。

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
  であり、**今まさに発生している線状降水帯の雨域とは別物**。

## 共有タイムラインのラベル

目盛りは`RideConditionBar/departureTimeline.ts: buildDepartureTimeline`が、気象レイヤーの
取得結果に依存せず作る（出発時刻はレイヤーが1つもONでなくても選べる必要があるため）。
粒度は降水ナウキャスト・格子の段と同じ「直近60分は5分刻み、以降は1時間刻み」で、
選んだ時刻が各レイヤーのフレームへ素直に対応する。表示ラベルは常に日付を含める
（タイムラインが約48時間先まで日付をまたぐため）。正時の目盛りには、日本時間の偶数時だけ
時刻を書く（毎コマ書くと文字が重なる）。

**「今」の目盛りを選んだら、その時刻に固定せず「今」への追従へ戻す**（「現在」ボタンと同じ）。
固定すると、放置するうちに選んだ時刻が過去になり、先の時刻を描くレイヤー（「今」より前のコマを
落とす）の範囲から外れて表示が消える。時刻を選んでいない間の出発時刻は、5分刻みの「今」へ
追従する（`features/conditions/useDepartureTime.ts`）——画面を開いたまま放置しても置いていかれない。

## 常設ヘッダーの天候表示（`WeatherPanel`）との違い

`WeatherPanel`（常設ヘッダー）は**観測**（アメダス実測値。天気の晴れ・くもりだけは地点の推計気象分布）のみで構成し（天気はbackendが観測から導いたWMOコードで届き、
`weatherCode.ts`がコードを分類し——分類と名前はbackendの宣言〔`domain/weather_display.py: WEATHER_CATEGORIES`〕が
生成物`vocabulary.ts`で配り、画面が持つのは分類ごとのアイコンだけ——`amedasWeatherIcon.ts`は「晴れ」を昼夜で
描き分けるだけ）、MSMとは独立にフェッチする。`TodayOutlook`（「今日」のパネル）は**MSMの計算値**（今日の最大降水量・
最大風速・気温レンジと一定間隔のコマの気温・降水量。間隔は応答の`today_period_interval_hours`）と日の出日没を扱い、見出しの下に計算値であって予報ではない旨を出す。
日の出日没は天文計算の値のため、その見出しの外（上）に置く。
天気のアイコンは出さない（上の「責務」の、MSMから天気を計算して出さない制約）。両者は別APIに依存する独立
コンポーネントで、本モジュールの動的地図レイヤーとは別のフェッチ経路を持つ。

**どちらに何を出すかは取得元ではなく値の性質で決める**。常設ヘッダーは走行中に何度も見る
瞬間値だけに絞り（幅が足りず溢れる）、1日1個の値はタップで開く`TodayOutlook`へ置く。

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
- 自前の格子の段は粗い格子（`useWeatherGrid`の`grid`）でコマの時刻を作る（`weatherSources.ts: gridStageFrames`が
  「今」が属する1時間より前を落とす）が、実際の描画は時刻ごとに`windLayer.ts: gridAtTime`が選ぶ格子（詳細格子が
  その時刻を持てばそちら、持たなければ粗い格子）を使う。コマの時刻の計算元と実際に塗る値の元が別グリッドなので、
  **コマは格子の時刻の値を持ち、値は点ごとに時刻で引く（位置で引かない）**——backendは取った時点の正時から先を
  返すため、取った時刻が違う格子（粗い格子と詳細格子、前回の値で補った点）では同じ位置が別の時刻を指す。
- **JMAプロキシ配下のURLはすべて`jmaDelivery.ts: jmaProxyUrl(path)`で組み立てる**
  （タイルテンプレート・時刻一覧・GeoJSON・`scene/groups/weather.ts`の届く前の仮のURLの
  区別なく）。配信オリジン（`lib/tileBaseUrl.ts: tileBaseUrl()`）を付けるかどうかを
  呼び出し側の判断に委ねると、付け忘れた箇所だけがフロントのホスティング経由になる。
  常に絶対URLにする理由:
  `vectorTile`（洪水キキクル）はMapLibreがWeb Worker内で取得するため相対パスだと
  `new Request(url)`がWorkerのbase URLに対して解決できず例外になり、`rasterTile`も
  backend直接配信（`NEXT_PUBLIC_TILE_BASE_URL`）ではページと別オリジンになるため絶対URLが
  要る（`features/map/regionApi.ts: roadSurfaceTileUrl`等と同じ仕組み、
  [静的レイヤー](static-map-layers.md)「タイルの配信元」参照）。
  時刻一覧・GeoJSONはMapLibreではなくアプリ自身の`fetch()`で読むが、同じく絶対URLにする——
  **タイルURLは時刻一覧が返るまで確定しない**ため、ここでフロントのホスティングを経由すると
  往復1つぶんが初回表示のクリティカルパスへ直列に乗る。`tileBaseUrl()`は`window`を参照する
  ので、モジュール直下の定数ではなく呼び出し時に評価する関数
  （`jmaDelivery.ts: jmaProxyUrl(path)`。時刻一覧のパスとコマのパスのテンプレートは源泉の
  `jmaElements`が持つ）として持つ。
