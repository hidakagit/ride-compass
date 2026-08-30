# 地図: 動的気象レイヤー（frontend）

## 責務

Open-Meteo・気象庁由来の時刻変化する気象データ（風・降水ナウキャスト・雷・竜巻・
キキクル・線状降水帯予測マップ）を地図上に表示する共通機構と、各要素固有のデータ層。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/dynamicWeather.ts` | 共通契約（型・共有タイムライン・状態管理の型） |
| `Map/precipitationNowcast.ts`・`thunderNowcast.ts`・`jmaNowcastFrames.ts` | 降水/雷/竜巻ナウキャストのフレーム列 |
| `Map/windLayer.ts`・`windArrowIcon.ts` | 風の矢印表示（gridMark） |
| `Map/riskMap.ts` | キキクル・線状降水帯予測マップ（未来フレームを持たない特殊系） |
| `hooks/useDynamicWeatherLayers.ts`・`useWeatherGrid.ts`・`useWeatherConditions.ts` | 状態管理・フェッチ |
| `components/WeatherPanel/`・`TodayOutlook/`・`WarningBadge/`・`DynamicLayerTimeSlider/` | UI |

## 共通契約（4本柱、`dynamicWeather.ts`冒頭より）

1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（`WIND_GRID_BBOX`）を共有する。
   フェッチも共有（`useWeatherGrid.ts`、1回のOpen-Meteo呼び出しで全要素ぶんの値を取る）。
2. **表現は2パターンのみ**: 格子中央にマークを出す（`gridMark`、風パターン）または
   格子を指定色で塗る（`gridFill`、雨パターン）。例外は「配信元が描画済みの画像」を
   重ねる`rasterTile`。
3. **時間経過はスライダー1本**: ONの全レイヤーのフレーム時刻を統合した1本のタイムライン
   （`mergeFrameTimes`）を共有スライダーへ渡す。各レイヤーは選択時刻に対応する自分の
   フレームを描画し、選択時刻が自分のデータ範囲外なら何も描画しない。
4. **データ取得の差異はデータ層で吸収**: 各要素のデータ層モジュール
   （`precipitationNowcast.ts`等）がソース（1要素につきN個ありうる）を1本のフレーム列へ
   統合し、フレームごとの描画内容（`DynamicWeatherRenderPayload`）を返す。表示層
   （`page.tsx`/`MapView.tsx`）はペイロードのkindしか見ない。

## 新しい動的要素を追加する1本道（コード内コメントに明記された手順）

1. backend: `wind_grid.py`の`WindGridPoint`へ値フィールドを追加、`weather_client.py`の
   `WIND_GRID_VARIABLES`へOpen-Meteo変数を足す（フェッチは相乗り）
2. データ層: 要素モジュールを新設し、フレーム列とペイロード関数を実装する
3. `MapView.tsx`: `DYNAMIC_WEATHER_RENDERERS`へ描画スペック（raster/gridFill/gridMarkの
   宣言と配色・アイコン）を1エントリ追加する
4. `mapLayers.ts`: 地図チップを追加し、`MapLayerId`・`page.tsx`の`dynamicWeather`一覧へ
   1行足す

## riskMap.ts（キキクル・線状降水帯予測マップ、特殊系）

他の動的気象レイヤーと異なり**未来方向の複数フレームを持たない**——気象庁側で実況と
短時間予測を統合済みの「現在の危険度」単一値のみを配信する（`validtime===basetime`を
実機確認済み）。共有タイムライン・`frameIndexForTime`には乗せない（フレームの
validtimeは実際の「今」から最大10分ほど遅れるのが常態のため）。

- キキクル3種（土砂・大雨・浸水）: 「防災」カテゴリとして`WarningBadge`と同様の常時
  マウント（チップ無し・時刻スライダーとも無関係）。
- 線状降水帯予測マップ: 別のデータ系統（rasrf系統、降水チップの一部）。

## 共有タイムラインのラベル

`mergeFrameTimes`が降水ナウキャスト（5分刻み）と格子予報（1時間刻み）を統合すると、
「近い将来は細かく、遠い将来は粗い」目盛りが自然にできる。表示ラベルは常に日付を含める
（タイムラインが約48時間先まで日付をまたぐため）。
