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
  確認の手順をタスクとして提案する（置き場に issue を起こす。[file-issue/SKILL.md](../../.claude/skills/file-issue/SKILL.md)）。

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
| アドレス・ベース・レジストリ（デジタル庁）の都道府県・市区町村・町字マスターと位置参照拡張 | `backend/scripts/fetch_abr.py`（取得）、アダプタ`abr` | 配布の一覧（DCAT）がデータセットを CC BY 4.0 とする（2026-10-09 の調べで確認）。リンク先のデジタル庁のサイトの規約は、権利表記の無いコンテンツを公共データ利用規約（PDL1.0。CC BY 4.0 と互換）とし、出典の記載と、加工したら出典とは別に加工した旨を求める。地番マスター・地番マスター位置参照だけに登記所備付地図データ利用規約が掛かり、使う町字マスター・位置参照拡張には掛からない | 可 | 出典（「アドレス・ベース・レジストリ」（デジタル庁）＋リンク）と加工した旨。`backend/app/domain/place_search.py: ADDRESS_AREA_ATTRIBUTIONS`の行が`ALWAYS_SHOWN_ATTRIBUTIONS`に入って満たす | [利用規約](https://www.digital.go.jp/policies/base_registry_address_tos/)・[アドレス・ベース・レジストリ](https://www.digital.go.jp/policies/base_registry_address/) | 2026-10-09 |
| e-Stat 統計地理情報システムの境界データ（令和2年国勢調査 小地域（町丁・字等）、総務省統計局） | `backend/scripts/fetch_estat_small_areas.py`（取得）、アダプタ`estat_small_area` | e-Stat の利用規約（政府標準利用規約（第2.0版）に準拠。CC BY 4.0 と互換）。統計地理情報システムの規約は、コンテンツの利用条件を e-Stat の利用規約に委ね、境界データに固有の条件を持たない。境界は区画へ結ぶのと、施設の位置を含む境界から施設の辺りの区画を決めるのに使い、画面には出さない（加工に当たる） | 可 | 出典（記載例「出典：政府統計の総合窓口(e-Stat)（https://www.e-stat.go.jp/）」）と、出典とは別に加工した旨（記載例「「○○調査結果」（A省）を加工して作成」）。`ADDRESS_AREA_ATTRIBUTIONS`の行が満たす | [利用規約](https://www.e-stat.go.jp/terms-of-use)・[統計地理情報システムの利用規約](https://www.e-stat.go.jp/gis-terms) | 2026-10-09 |
| Overture Maps places（Overture Maps Foundation。地点の出どころは Meta・Microsoft・Foursquare・AllThePlaces・PinMeTo・DAC 等で、1つの地点の出どころは1つ） | `backend/scripts/fetch_overture_places.py`（取得）、アダプタ`overture_places` | テーマは出どころごとに CDLA Permissive 2.0（Meta・Microsoft・PinMeTo・DAC 等）・Apache 2.0（Foursquare）・CC0 1.0（AllThePlaces）。OpenStreetMap のデータを含まず、ODbL の共有の義務がかからない。Foursquare の NOTICE は、ライセンスの写しを渡すこと・変えた所を目立つように示すこと・NOTICE の全文を残すことを求め、API の形で配るなら NOTICE の内容を開発者向けの文書に目立つように載せることを勧める | 可（CDLA Permissive 2.0・Apache 2.0・CC0 1.0 のどれも商用の利用を制限しない） | 出どころごとの表示（Overture の出典の文書の文言）。Foursquare は著作権の1行・Apache 2.0・Overture の形へ変えた旨・NOTICE。`backend/app/domain/map_display.py: ALWAYS_SHOWN_ATTRIBUTIONS`の行と、そこからリンクする`frontend/public/licenses/`の Apache 2.0 の本文・NOTICE の写し（変えた旨を末尾に足したもの）が満たす | [出典](https://docs.overturemaps.org/attribution/)・[places](https://docs.overturemaps.org/guides/places/)・[Foursquare NOTICE](https://opensource.foursquare.com/places-notice-txt/) | 2026-10-08 |
| 文化遺産オンライン（文化庁・国立情報学研究所）の国の指定・登録の文化財の建造物を、ジャパンサーチ（国立国会図書館）の簡易Web APIで | `backend/scripts/fetch_bunka_heritages.py`（取得）、アダプタ`bunka_heritages` | ジャパンサーチのサイトポリシー「データの利用について」: メタデータはデータベースの紹介ページの条件に従い、書かれていなければ CC0 1.0。文化遺産オンラインの紹介ページの条件は「解説文：CC BY」だけで、使う項目（名称・位置・所有者・指定の別）に条件は無い（解説文は使わない）。文化遺産オンラインのサイト自体は「無断で転用・引用・改変することを禁じます」と書くが、簡易Web APIで取れるのは連携機関が API での提供を許したものだけ（簡易Web APIガイド 1.2）で、その条件がジャパンサーチの紹介ページに付いているので、それに従う。API は間を空けて打つよう求め、上限の目安は示さない（同 1.4） | 可（CC0・CC BY） | 条件は無いが、サイトポリシーの記載例の形（「ジャパンサーチ「文化遺産オンライン（文化庁・国立情報学研究所）」のメタデータを改変して利用」＋紹介ページのURL）で`ALWAYS_SHOWN_ATTRIBUTIONS`に出す | [サイトポリシー](https://jpsearch.go.jp/policy)・[紹介ページ](https://jpsearch.go.jp/database/bunka)・[簡易Web APIガイド](https://jpsearch.go.jp/static/developer/webapi/ja.html)・[文化遺産オンライン](https://online.bunka.go.jp/about) | 2026-10-08 |

公共データ利用規約（PDL1.0）は商用利用を認め、CC BY 4.0と互換である
（[デジタル庁](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)）。
どの提供元も、加工したものを国が作成したかのように見せることを禁じている。

## 版を持つ配布物の入れ替え

配布元が版ごとのファイルで配り、コードが版を1か所で名指して取りに行くものの、版と入れ替えの手順。

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
   新しい版で`convenience_store`の地点のうちコンビニのチェーンの語（同じファイルの`CHAIN_WORDS`）に当たらない名前を
   数え、新しいコンビニのチェーン・看板の掛け替え・まとまった表記の崩れがあれば語を足す（当たらない店は補給休憩のコンビニに出ない）。
2. [出典の文書](https://docs.overturemaps.org/attribution/)と Foursquare の NOTICE を読み、出どころと文言が変わっていれば
   `ALWAYS_SHOWN_ATTRIBUTIONS`の行と`frontend/public/licenses/foursquare-places-NOTICE.txt`を合わせる（生成物`mapDisplay.ts`を作り直す）。
   上の表の行の確認日も直す。
3. `rows.release`を新しい版へ書き換えてマージする。
4. 本番 VM で、別のコンテナ（[production-data/SKILL.md](../../.claude/skills/production-data/SKILL.md)「派生データの作り直し」と同じ`docker run`）から
   `python scripts/fetch_overture_places.py`（範囲の地点を写す。関東の枠で約190MB。Actions のランナーで17秒）→ `python -m app.batch.ingest_cli --source overture_place`
   → `python -m app.batch.derive_cli`の順に打つ。本番 DB へ書くので、開発機の対話のセッションで、ユーザーがチャットで言ったときだけ Claude が打つ（[dev-session/SKILL.md](../../.claude/skills/dev-session/SKILL.md)「本番へ書く」）。
5. 群ごとの件数（`SELECT place_group, count(*) FROM stop_places GROUP BY 1`）を前の版と比べ、大きく動いた群があれば 1 の変更を疑う。

### 文化財の建造物（文化遺産オンライン）

| 項目 | 内容 |
|---|---|
| 今の版 | `backend/app/batch/source_profile.yaml`の`bunka_heritage`の`rows.snapshot`（取った日。配信元は版を持たず、今の一覧だけを返す） |
| 更新の頻度 | 公表されていない。ジャパンサーチが最後に取り込んだ時刻は、連携データベースの参照API（`https://jpsearch.go.jp/api/database/bunka`）の`lastDataUpdated`（ミリ秒）で見られる |
| 取り方 | 全国の建造物（2026-10-08 に 17,560 件、1秒おきに18回・約30秒）を取る。取込の範囲は取込が絞るので、範囲を広げても取り直さない |

手元へ写したファイル（本番は VM の`/home/ubuntu/ridecompass-cache-data/bunka/`）は配信元が変わっても残るので、取り直すのは、
新しい指定を入れたいときと、写したファイルを失ったとき。

入れ替えの手順:

1. [紹介ページ](https://jpsearch.go.jp/database/bunka)のメタデータの条件と、[サイトポリシー](https://jpsearch.go.jp/policy)の
   出典の記載例を読み、変わっていれば`ALWAYS_SHOWN_ATTRIBUTIONS`の行を合わせる（生成物`mapDisplay.ts`を作り直す）。上の表の行の確認日も直す。
2. `rows.snapshot`を取る日へ書き換えてマージする。
3. 本番 VM で、別のコンテナ（[production-data/SKILL.md](../../.claude/skills/production-data/SKILL.md)「派生データの作り直し」と同じ`docker run`）から
   `python scripts/fetch_bunka_heritages.py` → `python -m app.batch.ingest_cli --source bunka_heritage` → `python -m app.batch.derive_cli`
   の順に打つ。本番 DB へ書くので、開発機の対話のセッションで、ユーザーがチャットで言ったときだけ Claude が打つ（[dev-session/SKILL.md](../../.claude/skills/dev-session/SKILL.md)「本番へ書く」）。
4. 寺社の数（`SELECT count(*) FROM stop_places WHERE place_group = 'temple_shrine'`。関東の範囲で 2026-10-08 に194）を前と比べ、
   大きく動いていれば、取込が読む項目（指定の別`bunka-11-s`・所有者`bunka-14-s`・`common.coordinates`）の名前か、
   所有者の書き方（`backend/app/domain/stop_place.py`の寺社の語）が変わっていないかを見る。

### 住所の区画の元データ（アドレス・ベース・レジストリ・e-Stat の小地域の境界）

| 項目 | 内容 |
|---|---|
| 今の版 | アドレス・ベース・レジストリは`backend/app/batch/source_profile.yaml`の`abr`の`rows.snapshot`（取った日。配布元は版を持たず、同じ URL に今の全件を置く）。e-Stat の境界は`estat_small_area`の`rows.survey`（統計調査の識別子。`A002005212020`が令和2年国勢調査の小地域） |
| 更新の頻度 | アドレス・ベース・レジストリは配布元のファイルの更新時刻（応答の`last-modified`。町字のテキストは 2026-10-02）で見る。e-Stat の境界は国勢調査ごと（5年おき） |
| 取り方 | アドレス・ベース・レジストリは全国の1ファイルずつ（都道府県・市区町村・町字のテキストと、都道府県・市区町村の代表点）と、取込の範囲に掛かる都道府県の町字の代表点。e-Stat の境界は範囲に掛かる都道府県の zip。範囲に掛かる都道府県は市区町村の代表点で決める（関東の範囲で12県。全国の1ファイルずつが約12MB、町字の代表点が約1MB、境界が約81MB。2026-10-09） |

手元へ写したファイル（本番は VM の`/home/ubuntu/ridecompass-cache-data/abr/`・`estat/`）は配布元が変わっても残るので、取り直すのは、
新しい住所を入れたいときと、写したファイルを失ったとき。

入れ替えの手順:

1. アドレス・ベース・レジストリは[利用規約](https://www.digital.go.jp/policies/base_registry_address_tos/)、e-Stat は
   [利用規約](https://www.e-stat.go.jp/terms-of-use)を読み、出典の求めが変わっていれば`ADDRESS_AREA_ATTRIBUTIONS`を合わせる
   （生成物`mapDisplay.ts`を作り直す）。上の表の行の確認日も直す。
2. `rows.snapshot`を取る日へ（e-Stat を新しい国勢調査にするなら`rows.survey`も）書き換えてマージする。
3. 本番 VM で、別のコンテナ（[production-data/SKILL.md](../../.claude/skills/production-data/SKILL.md)「派生データの作り直し」と同じ`docker run`）から
   `python scripts/fetch_abr.py` → `python scripts/fetch_estat_small_areas.py`（都道府県を ABR の市区町村の代表点から決めるので、この順）
   → `python -m app.batch.ingest_cli --source abr --source estat_small_area` → `python -m app.batch.derive_cli`の順に打つ。
   本番 DB へ書くので、開発機の対話のセッションで、ユーザーがチャットで言ったときだけ Claude が打つ（[dev-session/SKILL.md](../../.claude/skills/dev-session/SKILL.md)「本番へ書く」）。
4. 段ごとの区画の数（`SELECT level, count(*) FROM address_areas GROUP BY 1`）と、境界の結び付きの数（`SELECT count(*) FROM address_boundary_links`）を
   前と比べ、大きく動いていれば、取込が読む列（`backend/app/infrastructure/source_models.py`の`ABR_*_SOURCE_SQL`・`ESTAT_SMALL_AREAS_SOURCE_SQL`）の
   名前か、町字区分の意味（`backend/app/domain/address_area.py: MACHIAZA_TYPE_LEVELS`）が変わっていないかを見る。

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
