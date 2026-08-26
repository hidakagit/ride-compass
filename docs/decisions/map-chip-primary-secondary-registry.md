# 地図チップの観測/推定/動的グルーピングと一次/二次命名の完全化（改善計画T163〜T169）

> architecture.mdの経緯記述をdecisions/へ切り出す第2弾（改善計画T286）で移設。
> 現状の姿はarchitecture.md「地図チップの観測/推定/動的グルーピングと一次/二次命名」節を参照。
> 以下は移設時点の記述をほぼそのまま保持した経緯・教訓の記録。

T137〜T145bで導入したレジストリ制は、当初「一次属性」「二次軸」という用語・単一ソースが
バックエンド（`registry_defaults.py`）にしか無く、フロントは独自の命名・カタログ（P1/P2、
観測データ/推定指標が別々の対応表）を個別に持っていた。T163〜T169はこの二重管理を解消し、
地図チップUIの最上位グルーピングをレジストリの区分そのものへ揃える改修。

- **レジストリの完全化（T163）**: `domain/registry.py`/`registry_defaults.py`を一次属性・
  二次軸の命名・材料の単一ソースとして完全化し、`export_openapi.py`が`axis-catalog.json`へ
  `primary_attributes`（attr_id・正式名・shared）を追加で書き出す。
- **フロント一次属性カタログ（T164、T308で情報源を実行時APIへ更新）**: [frontend/src/components/Map/primaryAttributes.ts](../../frontend/src/components/Map/primaryAttributes.ts)が
  1次→2次（研究タブの重み行に材料一覧を表示、T146区間インスペクタのラベル共通化、
  T168）の導出を片側importで行う（設計原則2）。2次→1次（地図チップの推定軸タイルに
  材料一覧を表示、T167→T181フォローアップで自動ON連動は撤去し表示のみに変更）は
  T308で純関数`primaryAttributeIdsToLayerIds(attrIds)`へ置き換わり、呼び出し側が
  `useAxisCatalog`（ライブ`GET /api/axis-catalog`の`primary_attribute_ids`、失敗時は
  `axis-catalog.json`の同フィールドへフォールバック）から取得した属性id配列を直接渡す
  形になった（旧`axisMaterials()`は静的`axis-catalog.json`の`inputs`専用で廃止、詳細は
  上記T308節）。地図チップの4文字以内略名はこのファイルのみが持つUI固有の対応（正式名は
  axis-catalog.json側が正）。
- **道路情報レイヤーの論理分割（T165）**: 従来の単一「道路情報」レイヤーを「道路の種類」
  （`roadType`）と「路面の種類」（`roadSurface`）へ分割（`ROAD_TILE_LAYER_ID`のline-color
  expressionを軸ごとに分離）。
- **チップ最上位の次数反転（T166）**: 地図チップの最上位グルーピングを、従来の
  カテゴリ単位（道路状態/交通・安全/自転車インフラ等、`MapLayerCategory`）から、
  「観測データ（`raw`、OSM/警察庁等の生タグをそのまま分類表示）」「推定指標（合成）
  （`composite`、複数材料から計算した二次軸）」「動的データ（`dynamic`、T170以降の
  時刻依存レイヤー）」の3区分（`MapLayerDataNature`）へ反転した。従来のカテゴリは
  観測グループ内の小見出しへ役割を移した。
- **材料の表示（T167・T168、T181フォローアップで自動ON連動を撤去）**: 二次軸（推定指標）を
  ONにすると`primaryAttributes.ts`の`inputs`が指す一次属性（観測データ）レイヤーを自動的に
  ONするカスケードを当初T167で導入したが、T181で観測グループのメンバーを個別に「表示項目の
  設定」で非表示にできるようになったことで、非表示にしたメンバーが推定側の操作で裏から
  ONにされ、かつ非表示設定でチップ自体が隠れているためOFFに戻す手段が無い、という不整合を
  生むようになった（実機フィードバック「自由にメンバを表示非表示できることで、裏で表示
  状態で残るのは避けたい」）ため、このカスケードは撤去した（`handleLayerToggle`は単純な
  `setLayerVisibility`のみ）。代わりに、推定軸タイルの▼展開時（`renderMaterialsNote`、
  MapOverlayControls.tsx）に「材料: ○○」として関連する一次属性を常に表示することで、
  どの観測データが計算に使われているかをユーザーが把握できるようにする（自動ONはしない）。
  逆方向として、研究タブの各軸の重み行の直下にその軸が参照する材料一覧を表示し、
  区間インスペクタのラベルも同じカタログへ統一する（T168、こちらは変更なし）。
- **チップのタイル化・マトリックス化（T169）**: 観測/推定グループの地図チップを、
  展開方向（▶=個々のメンバーの凡例展開／▼=グループ自体の縦積み展開）を統一した
  タイル状のマトリックスへ作り直した。モバイル幅では推定軸タイルを縮小、専用アイコンの
  追加、折りたたみ時限定のアイコン凡例表示など、実機フィードバックを受けた反復調整を
  複数回行った（詳細はコミット履歴のT169続き群参照）。
- **1次/2次の地図上表現統一（「梅・竹・松」）**: 1次「素材」レイヤー（道路種別/路面の合成・
  自転車インフラ・指定路線）は`line-offset`で道路に並行する複数トラックへ分離し
  （`ROAD_MATERIAL_TRACK_LAYER_IDS`、同時ONでも互いを覆い隠さない）、2次（car_stress・
  ramp軸）はそれより太く半透明な「下敷き」として1次の下に重ねる。下敷き幅
  （`SECONDARY_AXIS_CASING_WIDTH`）は1次トラック数×オフセット間隔＋自身の太さから
  計算式で導出し（設計原則2の「導出できる関係」拡張）、素材の本数が変わっても手計算し
  直す必要がない。
- **表示項目の設定パネル（T181）**: T169以降レイヤー追加が続き、観測グループ展開時に
  8メンバーが縦一列に並んでモバイル幅で見切れる報告を受け、グループ見出しのⓘボタン
  （従来は読み取り専用の凡例）を「表示する項目を選ぶ」設定パネルへ拡張した
  （`MapOverlayControls.tsx`の`renderVisibilitySettings`、旧`renderGroupLegendToggle`）。
  各項目にチェックボックス風ボタンを持たせ、非表示に選んだメンバー/軸のIDを
  `hiddenIds`（`${scope}:${id}`、scope="raw"|"composite"|"dynamic"）へ記録し、
  グループ本体の展開時はこのセットに含まれない項目だけを描画する
  （`renderObservedMemberRows`のフィルタ、`group:composite`分岐の`SECONDARY_AXES.filter`）。
  非表示IDのSetという設計（表示IDのSetではなく）により、既定では全件表示のまま新規
  レイヤーが自動的に見える。設定は`expandedIds`と同様のページ内一時的なUI状態で、
  永続化はしない。MapOverlayControlsが「レイヤー固有の知識を持たない汎用描画係」で
  あるという既存方針は維持（scope・keyはbuildChipGroups/SECONDARY_AXES側の値をそのまま
  受け取るのみ）。カテゴリ（`MapLayerCategory`）を観測グループのもう1段の自動折りたたみ
  として使う案を先に検討したが、ユーザーの実際の要望は能動的なON/OFF選択だったため
  不採用にした経緯がある。
  非表示に選んだ項目に対応するレイヤーが表示中（ON）だった場合、`toggleHidden`が
  `onToggle`（page.tsxの`handleLayerToggle`）を呼んでその場でOFFにする（実機フィードバック
  「設定で非表示にした場合、裏でレイヤ表示ONになっていればOFFにして」）。これを行わないと、
  チップ一覧から消えたレイヤーが地図には描画され続け、かつOFFにする手段（チップ自体）も
  無くなってしまう。逆方向（非表示解除）はチップを選べる状態に戻すだけで、レイヤーを
  自動でONにはしない（「隠す/出す」はチップの見た目の設定、ON/OFFの意思決定はユーザーが
  個別に行うという既存方針を維持）。`layerVisibility`（page.tsx）が唯一の情報源で
  `handleLayerToggle`が唯一の更新経路という既存の状態管理に対し、`hiddenIds`はあくまで
  表示専用のローカルUI状態のままであり、`onToggle`経由でしか外側の状態に影響しない
  （新しい状態の持ち方を増やしていない）。
- **材料連動ONの撤去（T214）**: T167で導入した「推定指標ONで材料の観測データレイヤーも
  連動ON」するカスケードは、T181の非表示設定と組み合わさると「非表示にしたメンバーが
  推定側の操作で裏からONにされ、かつチップが隠れているためOFFに戻せない」という不整合を
  生むようになったため撤去した（`page.tsx`の`handleLayerToggle`は単純な
  `setLayerVisibility`のみに戻した）。代わりに、材料一覧の表示（`renderMaterialsNote`、
  T167で同時導入）はON/OFFに関わらずそのまま残し、どの観測データが計算に使われているかを
  ユーザーが把握する手段として維持する（自動ONはしない）。
- **内訳パネルの画面下端はみ出し対策（T215）**: `.detailPanelBase`が`overflow-y: auto`
  （内部スクロールが必要）と`touch-action: none`（地図へのジェスチャー誤認防止）を
  同時に持っていたため、`touch-action: none`がネイティブのタッチスクロール自体を無効化し、
  パネルの中身が`max-height`（16rem/45vh）を超えるとモバイルでスクロールできなくなる
  不具合があった（実機フィードバック「スクロールできないことがある」）。`touch-action`を
  `pan-y`へ変更し、縦方向のネイティブスクロールを許可しつつ横方向のパン・ピンチズームは
  引き続き無効化する。あわせて、パネルは`position: fixed`でJSが測った行の位置から浮かせる
  ため、行が画面下端に近いとCSS既定の最大高さぶんがビューポート外へはみ出し内部スクロール
  でも原理的に到達できない領域ができる問題があり、`toggleExpanded`が`window.innerHeight`
  から利用可能な高さを逆算して`maxHeight`を動的に縮めるようにした（横方向の`maxWidth`を
  画面幅から逆算する既存の仕組みと同じ考え方、下限120px）。
- **グループ開閉・表示項目設定の永続化（T216）**: ユーザー要望「グループの選択状態等は
  保持しておいて、次開いた時に同じ状態にして。時間経過で変動する要素以外は、過去の設定
  内容はlocalStorage等で保持してほしい」を受け、`expandedIds`のうちグループ本体の開閉
  （`GROUP_VISIBILITY_KEYS`）と`hiddenIds`（T181の表示項目設定）を`useStoredState`
  （`ridecompass:map-overlay-expanded-groups`・`ridecompass:map-overlay-hidden-ids`）で
  localStorageへ永続化した。個々の凡例展開（member:/axis:/単独チップ/`${groupKey}:legend`）は
  「今ちょっと確認のために開いている」一時的な状態であり、次回訪問時に勝手にポップアップが
  開いた状態で再現されるのは望ましくないため保存対象から除外する（serialize/deserialize
  両方でGROUP_VISIBILITY_KEYSにフィルタする）。各レイヤーのON/OFF自体（`layerVisibility`）は
  T47 R-6の時点で既に`useStoredState`で永続化済みのため今回の対応不要（動的レイヤーの
  実際のデータ・現在時刻に依存するフレームインデックス等の「時間経過で変動する要素」は
  そもそも永続化の対象にしていない）。
- **トンネルの独立レイヤー化（T217）**: tunnel（一次属性、OSMのtunnelタグ）は
  night軸（推定グループ、T145a）の材料として`road-surface-tiles`へ既に焼き込み済み
  だったが、他の一次属性と違い観測グループ内に色分けレイヤー・チップを持たず、区間
  ポップアップでのみ確認できる状態だった（「地図上に描画可能な状態で保持しているが
  レイヤー未追加の要素」の洗い出しで判明）。designation（指定路線）と同じ構成
  （road_surfaceソースを再利用する独立lineレイヤー、該当区間のみ`tunnel: true`）で
  観測グループのメンバーとして追加した（バックエンド側の変更は無し）。これに伴い
  `PRIMARY_ATTRIBUTE_LAYER_IDS`にtunnelが移り`PRIMARY_ATTRIBUTES_WITHOUT_LAYER`から
  外れたため、night軸の材料一覧（T167の`renderMaterialsNote`）は
  「材料: トンネル」「地図では未表示の材料: 街灯」（litのみ引き続きレイヤー無し）に変わる。
- **一方通行の独立レイヤー化（T289）**: 一方通行はグラフ構造レベルで既に完全に
  ハンドリング済み（`domain/osm_adapter.py: _resolve_direction`が`oneway`/
  `oneway:bicycle`タグ[contraflow例外込み]からforward/backward/bothを解決し、
  `domain/graph.py: build_road_graph`が逆方向のEdge自体を生成しないため、探索は
  構造的に一方通行を守っており逆走経路は原理的に生成されない）。一方通行かどうかを
  評価・表示に使う材料としては未配線だったため、T217（トンネル）と同型の一次属性・
  独立レイヤー追加を行った。tunnelと異なり`osm_raw_ways.direction`列（forward/
  backward/both）自体はDB永続化済みだがMVTタイルへは未焼き込みだったため、
  `_ROAD_SURFACE_TILE_MVT_SQL`へ`CASE WHEN w.direction != 'both' THEN true END AS
  oneway`を追加した（タイル世代v13）。どの評価軸のinputsにも含めない、表示専用の
  一次属性（`registry_defaults.py`へ登録、評価軸には組み込まない設計判断）。
  評価軸の危険色（`AXIS_RAMP_COLORS`）とは意図的に別の中立色（青系`#2563eb`）を使い、
  「色が付く＝評価に効く」という他の観測レイヤーの読み方と混同しない。
