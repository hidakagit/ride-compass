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
  確認の手順をタスクとして提案する（置き場に issue を起こす。[flow.md](../conventions/flow.md)）。

## 母集団の取り方

「外部データソース」は、取込バッチ・backendの実行時・frontendのいずれかが**ネットワーク越しに
取得するデータの提供元**すべてを指す。取込アダプタ（`backend/app/batch/source_adapters/`の
`@register_adapter`）だけでは足りない——実行時に取りに行くもの（気象・防災・基礎地図等）と、
取得スクリプトだけが取りに行くもの（警報の区域の境界等）はアダプタを持たない。棚卸しはコードに現れる外部ホストから取る:

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
| 気象庁 予報区等GISデータ（「市町村等（気象警報等）」の区域の境界） | `backend/scripts/fetch_jma_area_boundaries.py`（取得・変換）、`backend/app/infrastructure/jma_area_boundaries.py`（警報・洪水予報の区域を引く） | 配布ページが「気象庁ホームページの利用規約を遵守」と明記し、その規約（PDL1.0準拠）に従う。GISデータについての別段の定めは規約に無い。境界は簡略化して使う（加工に当たる） | 可 | 出典＋**加工した旨**（規約の記載例: 「気象庁『図・写真等の名称』（当該ページのURL）を加工して作成」） | [予報区等GISデータ](https://www.data.jma.go.jp/developer/gis.html)・[利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html) | 2026-09-27 |
| 交通事故統計オープンデータ（警察庁） | `backend/scripts/fetch_accident_csv.py`、アダプタ`npa_honhyo` | 警察庁ウェブサイト利用規約（PDL1.0準拠）。取り込む年数・量の定めは無い（公開している全年を取り込む） | 可 | 出典＋**加工した旨** | [利用規約](https://www.npa.go.jp/rules/index.html)・[オープンデータ](https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html) | 2026-09-27 |
| 10m Annual Land Use Land Cover（Impact Observatory・Microsoft・Esri） | アダプタ`io_lulc_tile`、`backend/scripts/fetch_lulc_raster.py` | CC BY 4.0 | 可 | 作成者の表示 | [AWS Open Data Registry](https://registry.opendata.aws/io-lulc/) | 2026-09-23 |
| 基礎地図（OpenFreeMap） | `backend/app/infrastructure/basemap_client.py` | 無料・登録不要・利用回数の制限なし（データはOSM、スキーマはOpenMapTiles） | 可 | 「OpenFreeMap © OpenMapTiles Data from OpenStreetMap」（MapLibreは配信元のTileJSONから自動で出す） | [openfreemap.org](https://openfreemap.org/) | 2026-09-23 |
| 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済みデータ） | `backend/app/infrastructure/msm_client.py`（`msm_base_url`） | 配布物はCC BY 4.0（Open-Meteo）。元データは気象庁の利用条件（PDL1.0）に従い、**気象業務法の制約**（第17条 予報業務の許可）が別にかかる——格子の値をどう扱えば許可が要るかは下の「気象業務法の予報業務許可」節 | Open-Meteo分は可。気象業務法との関係は**要確認**（公式の文書で決まらない部分があり、気象庁への照会が要る。許可の要否は有償・無償で変わらないため、無償で公開している今も同じ問い） | Open-Meteoへのクレジット（表示箇所の近くにリンク）＋気象庁の出典 | [Open-Meteo licence](https://open-meteo.com/en/licence)・[open-data](https://github.com/open-meteo/open-data)・[気象庁 copyright](https://www.jma.go.jp/jma/en/copyright.html)・[予報業務許可Q&A](https://www.jma.go.jp/jma/kishou/minkan/q_a_m.html) | 2026-09-26 |
| 気象庁ホームページの防災情報（アメダス・警報・ナウキャスト・キキクル・洪水予報・推計気象分布等のJSON・タイル） | `backend/app/infrastructure/`の`jma_*`・`flood_client.py` | 気象庁ホームページ利用規約（PDL1.0準拠）。**気象業務法の制約**（第17条 予報業務の許可・第23条 警報の制限）が別にかかる。アメダスの観測を累計して評価の材料（雨の材料）にするのと、推計気象分布（天気。実況で予報ではない）の地点の区分を晴れ・くもりに読み替えて観測所の降水と合わせ、天気のアイコンにするのと、降水ナウキャスト・降水短時間予報のタイルの色を、段をそのままにアプリの段の色へ1対1で塗り替えて重ねるのは加工に当たり、規約は出典と加工した旨の記載で加工を認める（観測値の加工についての別段の定めは無い）。塗り替えが気象業務法の上で「そのまま掲載」に入るかは、下の「気象業務法の予報業務許可」節の書いていないこと。出発時刻の予報で延ばす使い方は、下の「気象業務法の予報業務許可」節の確認が先 | 可（気象業務法の範囲で） | 出典。加工した場合は**加工した旨** | [利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)・[推計気象分布の解説](https://www.jma.go.jp/jma/kishou/know/suikei_kishou/kaisetsu.html) | 2026-10-05 |
| 暑さ指数（WBGT、環境省 熱中症予防情報サイト） | `backend/app/infrastructure/wbgt_client.py`（予測値API・情報提供地点マスタCSV） | サイトの利用規約（PDL1.0準拠）。規約が適用外として挙げるのはメール配信サービスと「電子情報提供サービス」（事業者向けのCSVファイル提供）で、使っている予測値API（`api/v1/getForecastData`）と地点マスタCSVは別の「暑さ指数の実況値・予測値ダウンロード」の側にあり、適用外に挙がっていない。同サイトのよくある質問は、アプリで使うならこのWebAPIを案内している。自動化ツールからの高頻度アクセスは控えるよう求めている | 可 | 出典（例: 「出典：環境省熱中症予防情報サイト（当該ページのURL）」）。加工した場合は出典とは別に加工した旨 | [ご利用にあたって](https://www.wbgt.env.go.jp/tos.php)・[実況値・予測値ダウンロード](https://www.wbgt.env.go.jp/wbgt_data_download.php)・[API仕様書](https://www.wbgt.env.go.jp/man15NH/wbgt_data_api_service_manual.pdf)・[よくある質問](https://www.wbgt.env.go.jp/faq2.php)・[電子情報提供サービス](https://www.wbgt.env.go.jp/data_service.php) | 2026-09-26 |
| 住所の辞書（jageocoder 用住所データベース 街区レベル、株式会社情報試作室。元データは国土交通省の位置参照情報・Geolonia 住所データ・デジタル庁のアドレス・ベース・レジストリ（町字マスター）・日本郵便の郵便番号データ・歴史的行政区域データセットβ版） | `backend/scripts/fetch_address_dictionary.py`（取得）、`backend/app/infrastructure/address_dictionary.py`（地点の検索） | 配布物に同梱のREADME（jageocoder 用住所データベース利用規約（街区レベル））。商用・非商用とも可（反社会的勢力・法令または公序良俗に違反する目的・データの提供者が不適切と判断した者の利用を除く）。サーバへ置くときはREADMEをデータと同じ場所に置く。READMEの文言を書けば国土交通省の利用規約も満たす（README）。アドレス・ベース・レジストリはPDL1.0で、地番マスターに掛かる登記所備付地図データ利用規約は、辞書が使う町字マスターには掛からない | 可 | 利用者から見える所に、READMEが指定する文言（「位置参照情報（大字町丁目・街区レベル）令和6年」（国土交通省）…をもとに、株式会社情報試作室が加工した jageocoder 用住所データベース（街区レベル）を利用）。文言は版ごとに変わる（下の「版を持つ配布物の入れ替え」） | [配布](https://www.info-proto.com/static/jageocoder/)・[jageocoder](https://github.com/t-sagara/jageocoder)・[アドレス・ベース・レジストリの利用規約](https://www.digital.go.jp/policies/base_registry_address_tos/) | 2026-10-07 |
| Overture Maps places（Overture Maps Foundation。地点の出どころは Meta・Microsoft・Foursquare・AllThePlaces・PinMeTo・DAC 等で、1つの地点の出どころは1つ） | `backend/scripts/fetch_overture_places.py`（取得）、アダプタ`overture_places` | テーマは出どころごとに CDLA Permissive 2.0（Meta・Microsoft・PinMeTo・DAC 等）・Apache 2.0（Foursquare）・CC0 1.0（AllThePlaces）。OpenStreetMap のデータを含まず、ODbL の共有の義務がかからない。Foursquare の NOTICE は、ライセンスの写しを渡すこと・変えた所を目立つように示すこと・NOTICE の全文を残すことを求め、API の形で配るなら NOTICE の内容を開発者向けの文書に目立つように載せることを勧める | 可（CDLA Permissive 2.0・Apache 2.0・CC0 1.0 のどれも商用の利用を制限しない） | 出どころごとの表示（Overture の出典の文書の文言）。Foursquare は著作権の1行・Apache 2.0・Overture の形へ変えた旨・NOTICE。`backend/app/domain/map_display.py: ALWAYS_SHOWN_ATTRIBUTIONS`の行と、そこからリンクする`frontend/public/licenses/`の Apache 2.0 の本文・NOTICE の写し（変えた旨を末尾に足したもの）が満たす | [出典](https://docs.overturemaps.org/attribution/)・[places](https://docs.overturemaps.org/guides/places/)・[Foursquare NOTICE](https://opensource.foursquare.com/places-notice-txt/) | 2026-10-08 |

公共データ利用規約（PDL1.0）は商用利用を認め、CC BY 4.0と互換である
（[デジタル庁](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)）。
どの提供元も、加工したものを国が作成したかのように見せることを禁じている。

## 版を持つ配布物の入れ替え

配布元が版ごとのファイルで配り、コードが版を1か所で名指して取りに行くものの、版と入れ替えの手順。

### 住所の辞書（jageocoder 用住所データベース 街区レベル）

| 項目 | 内容 |
|---|---|
| 今の版 | `20260417`（`backend/app/domain/place_search.py: ADDRESS_DICTIONARY_URL`の`gaiku_all_v22.20260417.zip`） |
| 配布の頻度 | 年1回の見込み（配布の版の日付: 2021年に7回・2022年に3回・2023年に5回・2024年に5回のあと、2025-04-23・2026-04-17。元データの位置参照情報も年1回の更新） |
| 新しい版の見つけ方 | [配布の一覧](https://www.info-proto.com/static/jageocoder/)に日付のディレクトリが増える。その下の`v2/`に`gaiku_all_v<NN>.<日付>.zip` |

入れ替えの手順:

1. 新しい版の`v2/`の一覧で、街区までの全国の辞書のファイル名を読む。末尾の`_v<NN>`（`v22`等）が、その辞書を読める
   `jageocoder`の版（2.2.xなら`v22`）を表す（同梱のREADMEの「データ形式について」）。
2. zipを取って同梱のREADMEを読み、利用条件と「利用者から見えるところ」に書く文言が変わっていないかを見る。
3. `ADDRESS_DICTIONARY_URL`を新しい版のzipへ書き換え、文言が変わっていれば`ADDRESS_DICTIONARY_ATTRIBUTION`を
   READMEの文言へ合わせる（生成物`mapDisplay.ts`を作り直す）。`_v<NN>`が変わっていれば、`backend/requirements.txt`の
   `jageocoder`をその版へ上げる。この表の「今の版」と、上の表の行の確認日も直す。
4. マージすると、デプロイが新しい版を取り（置き場の名前が版で変わる。取って入れるので数十秒）、コンテナの入れ替えのあとの
   検索は新しい版を引く。入れ替えまでは古いコンテナが古い版を引き続け、古い版は次のデプロイで同じスクリプトが消す
   （それまで本番の置き場に2つの版が並ぶ。1つ入れて約1.4GB）。
5. 本番の`/api/place-search?q=東京都新宿区西新宿2-8-1`が候補を返すことを見る。

次の入れ替えは、着手可能日を入れた issue で待つ（置き場のリポジトリ）。

### Overture Maps の地点（places）

| 項目 | 内容 |
|---|---|
| 今の版 | `backend/app/batch/source_profile.yaml`の`overture_place`の`rows.release` |
| 配布の頻度 | 毎月（公式の[リリースの予定](https://docs.overturemaps.org/release-calendar/)）。配布元の S3 に残るのは最大60日（2つの版）で、それより古い版は取り直せない |
| 新しい版の見つけ方 | [リリースの予定](https://docs.overturemaps.org/release-calendar/)の表。版ごとのリリースノート（`https://docs.overturemaps.org/blog/<年>/<月>/<日>/release-notes/`）へのリンクがある。版の名前（`2026-09-23.1`等）は S3 の置き場の`release/<版>/`になる |

手元へ写したファイル（本番は VM の`/home/ubuntu/ridecompass-cache-data/overture/`）は配布元から消えても残るので、
版を上げるのは、新しい地点を入れたいときと、写したファイルを失って取り直すとき（古い版が配布元から消えていれば取り直せない）。

入れ替えの手順:

1. リリースノートで places のスキーマの変更（列の名前・`taxonomy`の語）と、出どころ（`sources[].dataset`）の増減を読む。
   取込と派生が読む列（`backend/app/infrastructure/source_models.py: OVERTURE_PLACES_SOURCE_SQL`・アダプタの絞り）と群の語
   （`backend/app/domain/stop_place.py: OVERTURE_GROUP_WORDS`）が変わっていれば合わせる。
2. [出典の文書](https://docs.overturemaps.org/attribution/)と Foursquare の NOTICE を読み、出どころと文言が変わっていれば
   `ALWAYS_SHOWN_ATTRIBUTIONS`の行と`frontend/public/licenses/foursquare-places-NOTICE.txt`を合わせる（生成物`mapDisplay.ts`を作り直す）。
   上の表の行の確認日も直す。
3. `rows.release`を新しい版へ書き換えてマージする。
4. 本番 VM で、別のコンテナ（[deployment-sync.md](../conventions/deployment-sync.md)「派生データの作り直し」と同じ`docker run`）から
   `python scripts/fetch_overture_places.py`（範囲の地点を写す。関東の枠で約190MB。Actions のランナーで17秒）→ `python -m app.batch.ingest_cli --source overture_place`
   → `python -m app.batch.derive_cli`の順に打つ。本番 DB へ書くので、Claude は自分で打たず問いで頼む（[flow.md](../conventions/flow.md)「自動で進めないもの」）。
5. 群ごとの件数（`SELECT place_group, count(*) FROM stop_places GROUP BY 1`）を前の版と比べ、大きく動いた群があれば 1 の変更を疑う。

## 気象業務法の予報業務許可

データの利用条件とは別に、気象庁以外の者が気象・地象の予報の業務を行うには気象庁長官の許可が要る
（気象業務法第17条。許可を受けずに行うと第46条で50万円以下の罰金）。「予報」は「観測の成果に基づく
現象の予想の発表」（第2条第6項）で、気象庁の説明では「時」と「場所」を特定して今後生じる自然現象の
状況を予想し利用者へ提供すること、「業務」は定時・非定時に反復・継続して行うことを指す。「地象」には
気象に密接に関連する地面の諸現象が入る（第2条第2項）。気象・地象の予報業務には気象予報士の設置も要る
（第19条の2）。予報を行う者の所在が国外でも、日本向けの予報なら許可が要る。許可は個人でも取れる。

気象庁の公式の説明（[予報業務許可Q&A](https://www.jma.go.jp/jma/kishou/minkan/q_a_m.html)・
[予報業務を行うためのガイドブック](https://www.jma.go.jp/jma/kishou/minkan/pamphlet.pdf)・
[根拠規定](https://www.jma.go.jp/jma/kishou/minkan/hourei.pdf)、2026-09-26・2026-09-27確認）に**書いてあること**:

- 有償か無償かで区別しない。「業務」の定義（Q&A）は反復・継続して行う行為で、対価に触れない。
  ガイドブックは、自ら作成した予報を「ブログやSNSで広く公表する」ことを対象、所属する会社や家庭内で
  使うことを対象外として例示する。予報業務の目的の「不特定多数の者」は「あらゆる利用者」を指す（Q&A）。
  したがって、無償で公開しているウェブアプリでも、予報に当たるかどうかの判定は変わらない。
- 気象庁や許可事業者の予報をそのまま伝える・解説するだけなら許可は要らない。
- 数値予報モデルの格子点値（GPV。MSMを含む）は予報を行うための資料で、それ自体は予報ではない。
  そのまま描画・提供するのは許可が要らない。その際、予報ではなく数値予報モデルの結果で大きな誤差を
  含みうることを明示するよう推奨している。
- GPVから特定の地点の値を抜き出すときに空間内挿・高度補正等の加工をすると、独自の予報とみなされる
  可能性がある（Q&A）。ガイドブックは「独自の加工を行ったり、予報と称して提供する場合は許可が必要」と
  書く。加工しなくても、予報と称して出せば独自の予報とみなされる。
- 数値予報資料から明日の天気や気温などを自動で計算するソフトウェアで予報を行う場合も、「どのような
  予測の方法であっても」許可が要り、現象の予想は気象予報士に行わせる必要がある（Q&A）。
- 降水・降雪・気温の影響による地面の状態の変化（乾燥・ぬかるみ・アイスバーン等）や地面温度の予報は、
  地象の予報業務許可が要る。
- 大気の諸現象と一対一に対応づけられない指数（値から一定の式で気温等を逆算できないもの）の予想は
  許可の対象外。
- 発表する時点で過去になっている予想を公表するのは対象外。

**書いていないこと**（気象庁の情報利用推進課へ照会しないと決まらない）:

- 格子の値を周囲の格子点から補間して、経路上の地点・通過予定時刻ごとの値として画面に出すこと、
  および値を画面に出さずに経路の探索（所要時間・難易度）にだけ使うことが、上の「加工」に当たるか。
- 格子の雲量・降水量・気温から、自前のしきい値で天気の分類（晴れ・くもり・雨・雪等）を決めて出すことが、
  上のソフトウェアの問いの「予報を行う」に当たるか（「予報」と呼ばず、モデルの計算値と明示した場合を含む）。
- 観測（アメダス等）から今の路面の状態を推定して示すことが予報に当たるか（定義は今後生じる現象の予想）。
- 気象庁の降水ナウキャスト・降水短時間予報の画像を、段の区切りをそのままに色だけを別の色へ1対1で塗り替えて重ねることが、
  上の「そのまま伝える」に入るか（ガイドブック p.3 は「気象庁…が出した予報をそのまま掲載する・伝える。またはそれを解説する」を
  対象外と書き、色の塗り替えには触れていない。予報業務許可Q&Aにも記述が無い。2026-10-05確認）。

**照会の答えが来るまでの扱い**（ユーザーの判断）: 上の「書いてあること」が言い切っている2点——モデルの値を
「予報」と称して出すことと、数値予報から天気を計算して出すこと——はしない。画面はMSMの値を「モデルの計算値
（予報ではなく誤差を含みうる）」と出し、天気の分類（晴れ・雨等）は観測（アメダスと推計気象分布）からだけ導く。「可能性がある」
とだけ書かれた補間（地点・通過予定時刻ごとの値を画面に出す・経路の探索に使う）は答えまで続ける。
気象庁が出したものをそのまま重ねる表示（警報・キキクル等）は対象外。降水ナウキャスト・降水短時間予報は、段の区切りを
そのままに色だけをアプリの降水の段の色へ1対1で塗り替えて重ね（新しい予想を作らず、どこが何mm/hの段かは気象庁の画像と同じ）、
答えまで続ける。

## 使わないと決めたソース

商用利用が不可なため採用しない。

| ソース | 理由 | 公式ページ | 確認日 |
|---|---|---|---|
| 国土数値情報 緊急輸送道路（N10）・重要物流道路（N12） | 使用許諾条件が「非商用」 | [N10](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N10-v2_0.html)・[N12](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N12-2021.html)・[非商用の定義](https://nlftp.mlit.go.jp/ksj/other/agreement_02.html) | 2026-09-23 |

国土数値情報は**データごとに**使用許諾条件が違う（商用可のものもある）。国土数値情報から
別のデータを使うときも、そのデータのページの「使用許諾条件」を読む。
