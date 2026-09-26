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
  確認の手順を起票案にする（[asking-user.md](../conventions/asking-user.md)「起票は承認制」）。

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
| 国土地理院 逆ジオコーダ（`mreversegeocoder`） | `backend/app/infrastructure/jma_warning_client.py`（警報・洪水予報の区域を引く） | **公式の文書では決まらない**——APIとしての利用規約が無い。「自分のシステムへ組み込んでよいか」という問いへの国土地理院の回答（よくあるご質問）は、禁止はせず、主に地理院地図からの利用を想定している・常に長期に提供するとは限らない・仕様は予告なく変わる、と書くだけで、商用利用には触れていない。代わりの手段として東京大学CSISのシンプルジオコーディングを挙げている | 要確認 | 要確認 | [gsimaps README](https://github.com/gsi-cyberjapan/gsimaps)・[よくあるご質問](https://github.com/gsi-cyberjapan/gsimaps/issues/29) | 2026-09-26 |
| 交通事故統計オープンデータ（警察庁） | `backend/scripts/fetch_accident_csv.py`、アダプタ`npa_honhyo` | 警察庁ウェブサイト利用規約（PDL1.0準拠） | 可 | 出典＋**加工した旨** | [利用規約](https://www.npa.go.jp/rules/index.html) | 2026-09-23 |
| 10m Annual Land Use Land Cover（Impact Observatory・Microsoft・Esri） | アダプタ`io_lulc_tile`、`backend/scripts/fetch_lulc_raster.py` | CC BY 4.0 | 可 | 作成者の表示 | [AWS Open Data Registry](https://registry.opendata.aws/io-lulc/) | 2026-09-23 |
| 基礎地図（OpenFreeMap） | `backend/app/infrastructure/basemap_client.py` | 無料・登録不要・利用回数の制限なし（データはOSM、スキーマはOpenMapTiles） | 可 | 「OpenFreeMap © OpenMapTiles Data from OpenStreetMap」（MapLibreは配信元のTileJSONから自動で出す） | [openfreemap.org](https://openfreemap.org/) | 2026-09-23 |
| 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済みデータ） | `backend/app/infrastructure/msm_client.py`（`msm_base_url`） | 配布物はCC BY 4.0（Open-Meteo）。元データは気象庁の利用条件（PDL1.0）に従い、**気象業務法の制約**（第17条 予報業務の許可）が別にかかる——格子の値をどう扱えば許可が要るかは下の「気象業務法の予報業務許可」節 | Open-Meteo分は可。気象業務法との関係は**要確認**（公式の文書で決まらない部分があり、気象庁への照会が要る） | Open-Meteoへのクレジット（表示箇所の近くにリンク）＋気象庁の出典 | [Open-Meteo licence](https://open-meteo.com/en/licence)・[open-data](https://github.com/open-meteo/open-data)・[気象庁 copyright](https://www.jma.go.jp/jma/en/copyright.html)・[予報業務許可Q&A](https://www.jma.go.jp/jma/kishou/minkan/q_a_m.html) | 2026-09-26 |
| 気象庁ホームページの防災情報（アメダス・警報・ナウキャスト・キキクル・洪水予報等のJSON・タイル） | `backend/app/infrastructure/`の`jma_*`・`flood_client.py` | 気象庁ホームページ利用規約（PDL1.0準拠）。**気象業務法の制約**（第17条 予報業務の許可・第23条 警報の制限）が別にかかる | 可（気象業務法の範囲で） | 出典。加工した場合は**加工した旨** | [利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html) | 2026-09-23 |
| 暑さ指数（WBGT、環境省 熱中症予防情報サイト） | `backend/app/infrastructure/wbgt_client.py`（予測値API・情報提供地点マスタCSV） | サイトの利用規約（PDL1.0準拠）。規約が適用外として挙げるのはメール配信サービスと「電子情報提供サービス」（事業者向けのCSVファイル提供）で、使っている予測値API（`api/v1/getForecastData`）と地点マスタCSVは別の「暑さ指数の実況値・予測値ダウンロード」の側にあり、適用外に挙がっていない。同サイトのよくある質問は、アプリで使うならこのWebAPIを案内している。自動化ツールからの高頻度アクセスは控えるよう求めている | 可 | 出典（例: 「出典：環境省熱中症予防情報サイト（当該ページのURL）」）。加工した場合は出典とは別に加工した旨 | [ご利用にあたって](https://www.wbgt.env.go.jp/tos.php)・[実況値・予測値ダウンロード](https://www.wbgt.env.go.jp/wbgt_data_download.php)・[API仕様書](https://www.wbgt.env.go.jp/man15NH/wbgt_data_api_service_manual.pdf)・[よくある質問](https://www.wbgt.env.go.jp/faq2.php)・[電子情報提供サービス](https://www.wbgt.env.go.jp/data_service.php) | 2026-09-26 |

公共データ利用規約（PDL1.0）は商用利用を認め、CC BY 4.0と互換である
（[デジタル庁](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)）。
どの提供元も、加工したものを国が作成したかのように見せることを禁じている。

## 気象業務法の予報業務許可

データの利用条件とは別に、気象庁以外の者が気象・地象の予報の業務を行うには気象庁長官の許可が要る
（気象業務法第17条。許可を受けずに行うと第46条で50万円以下の罰金）。「予報」は「観測の成果に基づく
現象の予想の発表」（第2条第6項）で、気象庁の説明では「時」と「場所」を特定して今後生じる自然現象の
状況を予想し利用者へ提供すること、「業務」は定時・非定時に反復・継続して行うことを指す。「地象」には
気象に密接に関連する地面の諸現象が入る（第2条第2項）。気象・地象の予報業務には気象予報士の設置も要る
（第19条の2）。予報を行う者の所在が国外でも、日本向けの予報なら許可が要る。

気象庁の公式の説明（[予報業務許可Q&A](https://www.jma.go.jp/jma/kishou/minkan/q_a_m.html)・
[予報業務を行うためのガイドブック](https://www.jma.go.jp/jma/kishou/minkan/pamphlet.pdf)・
[根拠規定](https://www.jma.go.jp/jma/kishou/minkan/hourei.pdf)、2026-09-26確認）に**書いてあること**:

- 気象庁や許可事業者の予報をそのまま伝える・解説するだけなら許可は要らない。
- 数値予報モデルの格子点値（GPV。MSMを含む）は予報を行うための資料で、それ自体は予報ではない。
  そのまま描画・提供するのは許可が要らない。その際、予報ではなく数値予報モデルの結果で大きな誤差を
  含みうることを明示するよう推奨している。
- GPVから特定の地点の値を抜き出すときに空間内挿・高度補正等の加工をすると、独自の予報とみなされる
  可能性がある（Q&A）。ガイドブックは「独自の加工を行ったり、予報と称して提供する場合は許可が必要」と
  書く。加工しなくても、予報と称して出せば独自の予報とみなされる。
- 降水・降雪・気温の影響による地面の状態の変化（乾燥・ぬかるみ・アイスバーン等）や地面温度の予報は、
  地象の予報業務許可が要る。
- 大気の諸現象と一対一に対応づけられない指数（値から一定の式で気温等を逆算できないもの）の予想は
  許可の対象外。
- 発表する時点で過去になっている予想を公表するのは対象外。

**書いていないこと**（気象庁の情報利用推進課へ照会しないと決まらない）:

- 格子の値を周囲の格子点から補間して、経路上の地点・通過予定時刻ごとの値として画面に出すこと、
  および値を画面に出さずに経路の探索（所要時間・難易度）にだけ使うことが、上の「加工」に当たるか。
- 観測（アメダス等）から今の路面の状態を推定して示すことが予報に当たるか（定義は今後生じる現象の予想）。

## 使わないと決めたソース

商用利用が不可なため採用しない（取り込んでいたものは撤去した）。

| ソース | 理由 | 公式ページ | 確認日 |
|---|---|---|---|
| 国土数値情報 緊急輸送道路（N10）・重要物流道路（N12） | 使用許諾条件が「非商用」 | [N10](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N10-v2_0.html)・[N12](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N12-2021.html)・[非商用の定義](https://nlftp.mlit.go.jp/ksj/other/agreement_02.html) | 2026-09-23 |

国土数値情報は**データごとに**使用許諾条件が違う（商用可のものもある）。国土数値情報から
別のデータを使うときも、そのデータのページの「使用許諾条件」を読む。
