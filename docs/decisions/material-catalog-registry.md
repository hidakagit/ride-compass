# 材料カタログの正式レジストリ化（改善計画T277〜T340・T290）

> architecture.mdの経緯記述をdecisions/へ切り出す第2弾（改善計画T286）で移設。
> 現状の姿はarchitecture.md「材料カタログの正式レジストリ化」節を参照。
> 以下は移設時点の記述をほぼそのまま保持した経緯・教訓の記録。

軸が参照する「材料」（`MaterialTerm.material`/`CategoricalShape.material`/
`FlagSumShape.flags`が指す文字列id、`gradient_percent`等）は、これまで`AXIS_DEFINITIONS`の
コメントに散文で説明されるだけで正式な一覧を持たず、軸スタジオ（T270）のフロント側
`lib/axisMaterialsCatalog.ts`が独自にハードコードしていた（T277）。`domain/material_catalog.py:
MaterialSpec`/`MATERIAL_CATALOG`が単一の情報源になった——各材料は`material_id`・`label`・
`dtype`（numeric/boolean）に加え、内部専用（公開APIには含めない）の`tile_property`
（MVTタイルへの焼き込み済みプロパティ名、Noneはタイル非依存＝地図レイヤーのramp自動生成
不可を意味する）・`tile_property_inverted`（no_lit⟵litのような符号反転フラグ）を持つ。
**材料自体をGUIから追加・編集・削除する経路は用意しない**（ユーザー方針、材料の増減は
引き続き本ファイルへのコード変更＋デプロイのみで行う）。

新規公開エンドポイント`GET /api/material-catalog`（`api/routers/material_catalog.py`、
認可不要、読み取り専用）が`material_id`/`label`/`dtype`のみを返す（`tile_property`系は
地図表示ルール自動生成タスクT278・未起票がbackend内部でのみ使う想定で、公開レスポンスには
含めない）。フロントは`hooks/useMaterialCatalog.ts`がマウント時に1回取得し、取得完了まで・
失敗時は`lib/axisMaterialsCatalog.ts`の静的9件（同じ内容のスナップショット）を返す
（`useAxisCatalog.ts`と同型のパターン）。`components/AxisStudio/AxisComposer.tsx`が
このhook経由で材料選択ドロップダウンを構成する。

管理API（`api/routers/axis_admin.py: AxisDefinitionPayload`）に
`_check_materials_are_known`バリデータを追加し、shapeが参照する材料idが
`MATERIAL_CATALOG`に存在しない場合は422で拒否する（従来は任意の文字列を受け付けて
しまっていた抜け穴を塞いだ）。

T278（地図表示ルール自動生成・軸集合の同期・`kind=ramp`自動判定）は2026-08-24に完了した。

**表示専用材料の除外（改善計画T338）**: `MaterialSpec.display_only=True`の材料は
`GET /api/material-catalog`（`axis_studio_materials()`）から除外され、軸スタジオの
選択肢に現れない。現状該当するのは`designation`のみ——3値中"both"が実データで35.01%と
構造的なAND条件で頻発し（`decisions/material-normalization-for-axis-composition.md`
参照）、素朴な`CategoricalShape`の値ごとスコア付けでは実態を正しく表現できず誤解を招く
評価軸を作りやすいため。`MATERIAL_CATALOG`への登録自体は維持し
（`is_known_material`はTrueのまま）、`tile_property`経由の地図表示
（`staticAttributeLayers.ts`のdesignation凡例レイヤー・`car_stress`の
`display_override.tile_inputs`）には影響しない。「登録されているが評価軸から未参照」な
材料は他にも複数ある（`bridge`/`oneway`/`smoothness`等）が、これらは単に対応する軸が
まだ無いだけで評価軸化に技術的な障害は無いため`display_only`にはしていない
（`designation`固有の理由はコード側のフィールドdocstring参照）。

**designationの正規化フラグ分解（改善計画T338フォローアップ、2026-08-26）**: 上記の
`display_only`対応（3値のまま選択肢から隠すだけ）はT336（`bicycle_infra`→正規化フラグ
材料）と設計思想が食い違う場当たり的な対応だった、というユーザー指摘を受け、
`designation`が畳み込む前の生フラグを正規化材料としても分解した。
`is_emergency_transport`[N10該当]/`is_critical_logistics`[N12該当]を新設（`display_only`
ではなく軸スタジオの選択肢に現れる）。`_ROAD_SURFACE_TILE_MVT_SQL`が3値`designation`
CASE式の計算に既に使っていた`d.is_ert`/`d.is_cl`をそのまま2つのタイルプロパティとしても
焼き込む（`ROAD_SURFACE_TILE_VERSION`13→15）。ただし`extractor`はどちらも未設定のまま
——`is_designated`（車ストレスの`car_stress_designation_adjustment`内部軸が使う、種別を
問わない一律加点の簡略化材料）と異なりどの内蔵軸からも参照されないため、種別ごとの
per-edge kindを評価パイプラインへ運ぶ配線は「軸スタジオで実際に使いたいユーザーが現れる」
というトリガーが来るまで新設しない（`oneway`/`designation`自体と同じ「トリガー付き
DEFER」、設計原則9）。`designation`（3値、地図表示専用）自体は方針どおり維持する
（ユーザー確認済み、地図の凡例レイヤーへの変更は不要）。

**材料抽出の宣言駆動化（改善計画T339）**: T280で「材料→抽出関数」の対応表自体は
`MaterialSpec.extractor`で宣言的になったが、関数の中身は依然手書きのPythonコードだった。
実際には大半のextractorが「単一タグの生値取得」「タグ値の単純一致判定」「数値パース」
「件数/距離の密度計算」という少数の汎用パターンに分類できたため、パラメータ化された
extractorファクトリ関数（`raw_way_tag_extractor`/`tag_equals_extractor`/
`way_tag_parser_extractor`/`count_per_km_extractor`、いずれも`material_catalog.py`）を
新設し、`MaterialSpec`宣言の場で`extractor=tag_equals_extractor("bridge", "yes")`のように
直接呼び出す形にした（`MaterialSpec`へ`extractor_kind`文字列フィールドを追加する案は、
GUIから材料を追加・編集できない設計方針の下では実行時に動的解釈する相手が無く実益が
薄いため見送った）。既存9材料のextractorをこの形へ置き換え、専用関数を9つ削除した。
汎用パターンに収まる新しい材料は、ファクトリ呼び出し1行の宣言だけで（専用のPython関数を
書かずに）抽出可能になる——`tracktype`（OSMの未舗装路グレードタグ）がその実証例。
優先順位付き分類のような複雑な組み合わせロジック（`bicycle_infra`）は対象外で専用関数
のまま。

**軸スタジオの値入力UX改善（改善計画T340）**: `highway`/`surface`/`smoothness`はOSMタグの
生値でオープンエンドなため、`AxisComposer.tsx`の「値ごとのスコア」入力欄がタグ生値の
暗記・手入力を要求するUX課題を抱えていた（2026-08-26ユーザー報告）。新設エンドポイント
`GET /api/material-catalog/{material_id}/values`（`api/routers/material_catalog.py`、
認可不要）が、DBに実際に取り込まれている値の一覧（重複無し・ソート済み）を返す。DB読み取り
は`RawOsmRepository.get_distinct_material_values`（`infrastructure/
road_graph_repository.py`、単純な`SELECT DISTINCT`。surface/smoothnessは
`_ROAD_SURFACE_TILE_MVT_SQL`と同じ`lower(btrim(...))`正規化、highwayは生値のまま）が
担い、DB未接続・DB障害時のグレースフルデグレード（空リスト、`log_external_call`による
ログ・統計）は`RegionService.get_material_values`（`get_axis_inspector`と同じ方針）が
担う。既知だが動的値一覧に対応していない材料（`tracktype`等）は空リスト、未知の
材料idは404。

日本語ラベルの付与は「UI語彙のカタログ集約」原則に従いbackend側では行わず、
frontend側`lib/materialValueLabels.ts`が単一の情報源になる。highway/surfaceは既存の
地図絞り込みUIカタログ（`components/Map/roadFilterAxes.ts`のHIGHWAY_GROUPS/
SURFACE_GROUPS）から「タグ値→表示グループの日本語ラベル」を導出（export済みに変更、
同じ語彙を2箇所に手書きしない）、smoothnessはOSM標準8値のラベルを新規定義した。未知の
値・未登録の材料idはタグ値そのまま表示するフォールバック（`materialValueLabel`）。

`AxisComposer.tsx`の値入力欄は自由テキスト入力を完全に置き換えず、`useMaterialValues`
フック（`hooks/useMaterialValues.ts`）が取得した値一覧がある材料でのみ、隣に「値の候補」
セレクトを添える形にした（選ぶと自由テキスト入力欄へ反映される。値一覧が空の間は候補
セレクト自体を表示せず、従来どおりの自由テキスト入力のみ）。新しいタグ値がDBへまだ
反映されていないケース・想定外の値を先回りして設定したいケースを塞がないための判断。

**材料の網羅登録（改善計画T290）**: MVTタイル（`_ROAD_SURFACE_TILE_MVT_SQL`）には
既存7軸が実際に使う材料以外にも生データ（`highway`・`surface`・`smoothness`・
`bridge`・`bicycle_infra`・`cycleway_class`・`maxspeed_kmh`・`lanes_count`・
`motor_vehicle_no`・`designation`・`oneway`）が既に焼き込まれていたが、
`MATERIAL_CATALOG`には登録されていなかった。「評価や地図描画に使えそうな生データは
全部材料登録しておく」という設計一貫性の方針（ユーザー方針、2026-08-24）に基づき、
11材料すべてを登録し**9材料→20材料**へ拡張した。`dtype`を
`Literal["numeric", "boolean"]`から`Literal["numeric", "boolean", "categorical"]`へ
拡張し、多値カテゴリカルな6件（`highway`・`surface`・`bicycle_infra`・
`cycleway_class`・`designation`・`smoothness`）は`categorical`として登録した。
（`cycleway_class`は改善計画T337で削除済み。地図描画に使えそうという理由で網羅登録
されたが、実際にはMVTタイルへ焼き込むだけで評価軸・地図表示のどちらからも参照されない
まま残っていたため。「使えそうな生データを登録しておく」網羅登録方針自体は、実際に
参照されるようになるかを継続的に見直す前提であることの実例）。

**「登録」と「評価軸での利用」は独立**: 執筆当初（T290）は`CategoricalShape.mapping`が
`dict[bool, float]`（真偽値限定）だったため、`categorical`材料は軸スタジオの選択肢には
現れるがまだどの評価軸の材料としても使えない状態だった。その後改善計画T292で
`CategoricalShape.mapping`が`dict[bool | str, float]`へ拡張され（`_check_materials_are_known`
の許容dtypeも`categorical`を含むよう追従）、内部軸（`car_stress_highway_base`・
`car_stress_bicycle_infra_adjustment`等）が実際にcategorical材料を使うようになった。
ただし軸スタジオGUI（`AxisComposer.tsx`）側は「カテゴリ値」テンプレートの材料選択が
`dtype === "boolean"`のみに絞られたままで、GUIからcategorical材料を選べない状態が
改善計画T322まで残っていた（バックエンドの利用可否とGUIの選択可否がT292時点で
乖離していた）。T322で「カテゴリ値」テンプレートの材料選択肢へcategorical dtype材料も
含め、選択時は値(自由入力)ごとのスコアを複数行で設定できるUIへ拡張し、この乖離を解消した。

フロント側`lib/axisMaterialsCatalog.ts: AxisMaterialOption`は`boolean: boolean`
（2値フラグ）から`dtype: AxisMaterialDType`（"numeric"/"boolean"/"categorical"の3値）へ
変更した——旧実装のまま`categorical`材料を追加すると`!boolean`（numeric用フィルタ）に
誤って混入し、選べるのに送信時にエラーになるUXを生んでいたため、T290に付随する
必須の追従修正として対応した。
