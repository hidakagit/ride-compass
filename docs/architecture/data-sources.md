# 外部データソースの利用条件

**RideCompassは将来商用になりうる前提で扱う。** 外部から取得して保存・加工・表示する
データは、提供元が定める利用条件の範囲でしか使えない。利用条件はコードからは導けず、
提供元の公式ページにしか無い——この文書はその写しと、確認した日付を持つ。

## 使い方

- **外部データソースを新しく使う前**に、提供元の公式ページで利用条件を読み、下の表へ
  1行足す。商用利用が不可・不明なら採用しない（不明なまま使い始めない）。
- **既存のソースの使い方を変える前**（表示だけだったものを評価・ルート計算へ使う、
  取得したものを再配布する等）に、その行の条件がその使い方を許すかを読み直す。
- 表記の要件は画面の出典表記（[static-map-layers.md](../modules/frontend/static-map-layers.md)
  「出典表記」）が満たす。行を足したら、表記が要件を満たしているかも見る。
- 観測や第三者の記事から推測して埋めない。公式の文言を読めなかった項目は「要確認」と書き、
  確認の手順を起票する。

## 母集団の取り方

「外部データソース」は、取込バッチ・backendの実行時・frontendのいずれかが**ネットワーク越しに
取得するデータの提供元**すべてを指す。取込アダプタ（`backend/app/batch/source_adapters/`の
`@register_adapter`）だけでは足りない——実行時に取りに行くもの（気象・防災・基礎地図・
逆ジオコーダ等）はアダプタを持たない。棚卸しはコードに現れる外部ホストから取る:

```bash
git grep -h -o -E "https?://[a-zA-Z0-9.-]+" -- backend/app backend/scripts frontend/src | sort -u
```

設定値（`backend/app/config.py`の既定URL等）もこの走査に入る。環境変数だけで与えるURLは
入らないため、本番の設定を足したときは別に見る。

## 表

| ソース | 取りに行く場所 | 利用条件 | 商用 | 表記の要件 | 公式ページ | 確認日 |
|---|---|---|---|---|---|---|
| OpenStreetMap（Geofabrikの抽出PBF） | `backend/scripts/fetch_osm_pbf.py`、アダプタ`osm_pbf_way`・`osm_pbf_node` | ODbL 1.0 | 可 | 「© OpenStreetMap contributors」と、ODbLで提供されている旨（`/copyright`へのリンクで可）。DBそのものを配布するなら同じライセンスで出す義務がある | [copyright](https://www.openstreetmap.org/copyright) | 2026-09-23 |
| 地理院タイル（標高タイル・色別標高図） | アダプタ`gsi_dem_tile`、`backend/app/batch/dem_tile_store.py`、`backend/app/infrastructure/gsi_tile_client.py` | 国土地理院コンテンツ利用規約（公共データ利用規約PDL1.0準拠） | 可 | 出典（「地理院タイル」＋一覧ページへのリンク）。加工した場合は出典とは別に**加工した旨**。アプリからの実時間読み込みは申請不要 | [利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)・[タイル一覧](https://maps.gsi.go.jp/development/ichiran.html) | 2026-09-23 |
| 国土地理院 逆ジオコーダ（`mreversegeocoder`） | `backend/app/infrastructure/jma_warning_client.py` | **要確認**——公開APIとしての利用条件が無い。国土地理院は「主に地理院地図からの利用を想定」し、継続提供も仕様の維持も保証しないと明記している | 要確認 | 要確認 | [gsimaps README](https://github.com/gsi-cyberjapan/gsimaps) | 2026-09-23 |
| 交通事故統計オープンデータ（警察庁） | `backend/scripts/fetch_accident_csv.py`、アダプタ`npa_honhyo` | 警察庁ウェブサイト利用規約（PDL1.0準拠） | 可 | 出典＋**加工した旨** | [利用規約](https://www.npa.go.jp/rules/index.html) | 2026-09-23 |
| 10m Annual Land Use Land Cover（Impact Observatory・Microsoft・Esri） | アダプタ`io_lulc_tile`、`backend/scripts/fetch_lulc_raster.py` | CC BY 4.0 | 可 | 作成者の表示 | [AWS Open Data Registry](https://registry.opendata.aws/io-lulc/) | 2026-09-23 |
| 基礎地図（OpenFreeMap） | `backend/app/infrastructure/basemap_client.py` | 無料・登録不要・利用回数の制限なし（データはOSM、スキーマはOpenMapTiles） | 可 | 「OpenFreeMap © OpenMapTiles Data from OpenStreetMap」（MapLibreは配信元のTileJSONから自動で出す） | [openfreemap.org](https://openfreemap.org/) | 2026-09-23 |
| 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済みデータ） | `backend/app/infrastructure/msm_client.py`（`msm_base_url`） | 配布物はCC BY 4.0（Open-Meteo）。元データは気象庁の利用条件（PDL1.0）に従い、**気象業務法の制約**（第17条 予報業務の許可）が別にかかる | Open-Meteo分は可。気象業務法との関係は**要確認** | Open-Meteoへのクレジット（表示箇所の近くにリンク）＋気象庁の出典 | [Open-Meteo licence](https://open-meteo.com/en/licence)・[open-data](https://github.com/open-meteo/open-data)・[気象庁 copyright](https://www.jma.go.jp/jma/en/copyright.html) | 2026-09-23 |
| 気象庁ホームページの防災情報（アメダス・警報・ナウキャスト・キキクル・洪水予報等のJSON・タイル） | `backend/app/infrastructure/`の`jma_*`・`flood_client.py` | 気象庁ホームページ利用規約（PDL1.0準拠）。**気象業務法の制約**（第17条 予報業務の許可・第23条 警報の制限）が別にかかる | 可（気象業務法の範囲で） | 出典。加工した場合は**加工した旨** | [利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html) | 2026-09-23 |
| 暑さ指数（WBGT、環境省 熱中症予防情報サイト） | `backend/app/infrastructure/wbgt_client.py` | サイトはPDL1.0準拠。ただし**電子情報提供サービスは同規約の適用外**で、使っている予測値APIがどちらに当たるかは**要確認** | 要確認 | 出典（環境省である旨）。加工した場合は加工した旨 | [ご利用にあたって](https://www.wbgt.env.go.jp/tos.php)・[電子情報提供サービス](https://www.wbgt.env.go.jp/data_service.php) | 2026-09-23 |

公共データ利用規約（PDL1.0）は商用利用を認め、CC BY 4.0と互換である
（[デジタル庁](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)）。
どの提供元も、加工したものを国が作成したかのように見せることを禁じている。

## 使わないと決めたソース

商用利用が不可なため採用しない（取り込んでいたものは撤去した）。

| ソース | 理由 | 公式ページ | 確認日 |
|---|---|---|---|
| 国土数値情報 緊急輸送道路（N10）・重要物流道路（N12） | 使用許諾条件が「非商用」 | [N10](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N10-v2_0.html)・[N12](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N12-2021.html)・[非商用の定義](https://nlftp.mlit.go.jp/ksj/other/agreement_02.html) | 2026-09-23 |

国土数値情報は**データごとに**使用許諾条件が違う（商用可のものもある）。国土数値情報から
別のデータを使うときも、そのデータのページの「使用許諾条件」を読む。
