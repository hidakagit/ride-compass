# 動的材料・フィーチャー値配信（backend）

## 責務

ルート未確定時に、視界内の全道路へ公開軸の値（地図が塗る値）を、探索と同じ評価から配信する。材料は、
タイルのフィーチャーごとに探索と同じ値式で読んだもの（`services/feature_materials.py`）と、風・勾配・雨のような
タイルへ焼けない材料（時々刻々変わる・向きに依存する）を材料ごとのサービスが配ったものを合わせる。配信の単位は路面タイルのフィーチャーと同じで、
ズームによってway丸ごとにも区間（road_edges）にもなる——このモジュールはどちらかを
知る必要がなく、タイルと同じ`feature_key`を鍵として扱う（[static-road-attributes.md](static-road-attributes.md)の`EDGE_UNIT_MIN_ZOOM`参照）。ルート確定後の風はルーティングエンジンが
求める（後述「ルート確定後の風の評価」）。前後で違うのは走行方位（前は利用者が決めた1つの方位、後は
区間を実際に走る向き）と予報の範囲の外の時刻の扱いだけで、予報の地点と時刻の選び方・式は同じ。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `wind.py`・`wind_grid.py`・`gradient.py`・`rain.py`（雨の材料の宣言——窓の長さの一覧——と、1時間雨量の履歴から材料の値を求める計算・配ってよい履歴の古さ）・`dynamic_way_values.py`（要求の条件の組み立てと、フィーチャーの材料から地図が塗る値への写し） |
| services | `wind_way_service.py`・`gradient_way_service.py`・`rain_way_service.py`・`feature_midpoints.py`（配信サービスが、タイル内のフィーチャーの値をDBから引き、DB障害・取込範囲外・空のタイルを同じ形でログの欄へ記録する口と、地点の値を引く配信サービスが中ほどを鍵と緯度・経度の配列で引く口）・`feature_materials.py`（タイルのフィーチャーごとの材料と、道1本のフィーチャーごとの区間の材料を読み、ディスクへ持つ）・`dedicated_way_values.py`（材料→配信の実装の表、軸の葉の材料から実装を選ぶこと、条件を組んで値を引く共通の口、地図のレンズ、区間インスペクタが足す材料をまとめて引くこと） |
| infrastructure | `dynamic_way_value_cache.py`（配信サービスの値は勾配のみ。ディスク経由）・`feature_material_cache.py`（タイルのフィーチャーごとの材料と区間の材料。ディスク経由）・`tile_persistent_cache.py`（呼び出し元が設計したタプルの鍵でPythonオブジェクトを置く汎用のディスクキャッシュ。`diskcache`の包み） |
| api | `region.py`（`GET /api/region/dynamic-way-values/{axis_id}/...`）・`dependencies.py`（`get_dedicated_way_value_service`・`get_axis_inspector_service`） |

勾配材料の入力（`edge_elevation.average_grade`とフィーチャーの方位）・中ほど・フィーチャーごとの材料を
DBから取り出す`infrastructure/road_graph_repository.py: get_feature_gradient_inputs_in_tile`・`get_feature_midpoints_in_tile`・
`get_feature_materials_in_tile`・`get_feature_segments_in_tile`と、そのSQL（`infrastructure/road_tile_sql.py`）は
[routing-engine.md](routing-engine.md)が主管するファイルに属する。

## 2つのidの名前空間（読む前の前提）

この機構には名前の似た2つのidが出てくる。**混同すると無音の404・全道路の色なしになる**
ため、常に区別する。

| id | 何を指すか | 実体 | 出てくる場所 |
|---|---|---|---|
| **軸id** (`axis_id`) | 評価軸そのもの。軸スタジオでDBの行として増減する | `axis_definitions.axis_id` | APIのパスパラメータ、`AXIS_DEFINITIONS`のキー |
| **材料id** (`material_id`) | サービスが返す生値が軸定義のどの材料か。例: `wind_drag_ratio`・`gradient_percent`・`rain_24h_mm` | `material_catalog.py`のキー | 各サービスの`material_ids`クラス属性（担当する材料）と組み立てたインスタンスの`material_id`、`_SERVICES_BY_MATERIAL`のキー、キャッシュの名前空間、`paint_feature_values`の`served`の鍵 |

**実装は軸idを持たない。** 軸とサービスは、軸定義が内部軸まで辿って読む材料（葉の材料、
`domain/dynamic_way_values.py: leaf_materials`）とサービスの`material_id`の突き合わせで結ばれる。材料はコードが正本（GUIから増減しない）なので、
実装が材料の名前を知るのは、DBの行で増減する軸の名前を知るのとは違う。公開済みの軸は直さずに
複製して改良するため、軸の名前で結ぶと複製した軸が配信されない。

`tests/test_dedicated_way_values.py`が、担当する材料で組み立てたサービスの`material_id`が
その材料であること・材料カタログの既知材料であること・1つの材料を2つのサービスが担当すると
登録時に落ちることを検査する。

## 軸登録と要求の条件（`domain/dynamic_way_values.py`・`services/dedicated_way_values.py`）

配信するのは`AXIS_DEFINITIONS`（[軸スタジオ](axis-studio.md)のDB管理データ）の公開軸すべてで、レンズを組む都度
`AXIS_DEFINITIONS`の写しを取る（`services/dedicated_way_values.py: axis_way_value_lens`）。軸スタジオでの登録・公開は
次の要求から効く。公開していない軸（内部軸・下書き）と未知の`axis_id`は404を返す（500にするとフロントの
「データなし」フォールバックが効かない）。軸の`dedicated_way_value_layer`は、地図がその軸を配信の値で塗るかを
受け取る側へ伝える印で、配信できるかには関わらない。

値は、軸とそれが読む内部軸だけを探索と同じ評価（`domain/axis_definitions.py: evaluate_axes_array`）へ通して求める
（`domain/dynamic_way_values.py: paint_feature_values`）。評価へ渡す材料の列は2つの出どころを合わせる:

- 軸の葉の材料のうち、`services/dedicated_way_values.py: DEDICATED_WAY_VALUE_SERVICES`に配るサービスのある材料
  （風・向きで符号の決まる勾配・雨。材料ごとに1回のコード変更）は、そのサービスの値。タイルの材料に同じ材料の列が
  あっても置き換える——勾配は、タイルの材料では向きの符号が付かず、引いた地図の道1本では値が無い。
- それ以外の材料は、タイルのフィーチャーごとの材料（下の「タイルの材料」）。葉の材料がどれもサービスの材料なら
  タイルの材料は読まず、サービスが値を返したフィーチャーだけを塗る。

**要求の条件**（時刻`at`・走行方位`bearing_deg`・想定速度`speed_kmh`）のうち何が要るかは、材料の
サービスが受け取る条件の型（`conditions_type`。例: `WindConditions`）が決める。型はfrozen dataclassで、
既定値の無い欄が要るもの（例: 風は`bearing_deg`・`speed_kmh`が要り、`at`は省略すると今。勾配は
`bearing_deg`だけが要る）。要求は
`WayValueQuery`（どれも省略されうる）として受け、`assemble_conditions`がその型へ組み立てる。
**欠けを判定するのはここだけ**で、欠けていれば組み立てずに欠けた名前（`MissingConditions`）を
返す——地図の配信は422に、区間インスペクタは「データなし」にする。軸の葉の材料にサービスの材料が2つ以上あれば、
要る条件はそれぞれの型の欄を合わせたもので、欠けた名前も合わせて返す。サービスの
`get_way_values`は組み立て済みの値だけを受け取るので、要る欄は`None`を許さない型のまま届く。
値の範囲は欄の型（方位`domain/geo.py: BearingDeg`・速度`domain/route_request.py: AssumedSpeedKmh`・タイル座標
`domain/region.py: RoadTileZoom`・`TileIndex`）が持ち、地図の配信のクエリ・パスも区間インスペクタの本文も同じ型で書く
（外れ・NaN・無限大はどちらも422）。

**地図が載せる条件**も同じ条件の型から導き、軸は宣言を持たない。`GET /api/axis-catalog`の
`dynamic_way_value_conditions`は、軸の葉の材料を配るサービスの条件の型の欄の名前を重ねずに並べたもの
（`services/dedicated_way_values.py: dedicated_way_value_layers`。印に依らず全軸について求める）で、欄の名前
（`domain/dynamic_way_values.py: WayValueConditionName`）はそのままクエリパラメータの名前になる。
frontendはどのクエリパラメータをどの軸のリクエストへ載せるかをこれだけから決める（軸idの分岐を
持たない。[map-axis-coloring.md](../frontend/map-axis-coloring.md)参照）。

- **「要る」と「載せる」は別**: 載せるのは欄すべてで、要るのはそのうち既定値の無い欄。風の時刻は
  省略すると今の風になるので要らないが、地図は利用者が選んだ時刻の風を塗るので載せる。
- 載せない条件は、地図でその入力を変えても再取得しない（勾配は時刻スライダーで取り直さない）。
- 例: 風は時刻・走行方位・想定速度、勾配は走行方位だけ（標高・道路の向きは時刻で変わらない）、雨は
  何も載せない（今の観測を示し、出発時刻・方位では変わらない）。タイルの材料だけを読む軸も何も載せない。
- 同じ表から`dynamic_way_value_undetermined_by_bearing`も配る。
  配信のサービスが`undetermined_by_bearing`で宣言する、走行方位で値の決まらない道（値が`null`）を返しうるか
  で、frontendはtrueの軸の凡例にだけ「向きで決まらない」の行（`domain/map_display.py: LEGEND_SHARED_ROWS`）を
  足す。返しうるのは勾配だけ。

塗る値の種類（難易度か符号付き材料か）・段の境界・凡例の目盛りは
`domain/map_paint.py: map_paint`が決める（[axis-studio.md](axis-studio.md)「地図が塗るもの」）。

| 関数 | 意味 |
|---|---|
| `paint_feature_values(axis_id, definitions, feature_keys, materials, served)` | 材料→地図表示値。塗る値が難易度なら軸とそれが読む内部軸をタイル内の全道路について1回の配列評価、符号付き材料ならその材料の列（サービスが配った値か、タイルの材料）をそのまま。評価できない道は落とし、サービスがNoneで返した道（走行方位で決まらない）はNoneのまま返す |

`services/dedicated_way_values.py: _SERVICES_BY_MATERIAL`は、材料id→担当するサービス実装本体
（`WindWayService`/`GradientWayService`/`RainWayService`）のdictで、配信の組み立てと地図が載せる条件の導出がここから引く。こちらはPython実装本体
（コンストラクタ）の登録のため軸スタジオの宣言だけでは代替できず、**新しい計算の材料**の配信には
コード変更が要る（同じ材料を参照する軸を増やすのには要らない）。実装は担当する材料のクラス属性
`material_ids`・受け取る条件の型`conditions_type`と、組み立てる材料を`material_id`で受け取る統一シグネチャの
`build`を持ち、クラスが`DedicatedWayValueServiceType`、インスタンスが`DedicatedWayValueService`（`material_id`・`conditions_type`・`get_way_values`）の
形を満たせば、`DEDICATED_WAY_VALUE_SERVICES`へ
1行足すだけで登録される（キーは`material_ids`から取るため、名前を2箇所に書かない）。
1つの実装が同じ計算の材料群を担当できる——雨は窓の長さの一覧（`domain/rain.py: RAIN_WINDOW_HOURS`）へ
1件足すと、材料カタログの行も配信の登録も一緒に増える。
1つの材料を2つのサービスが担当していると、モジュールの読み込み時（＝起動時）に落ちる。区間ごとに値が違いうる材料（下の
「引いた地図の道1本の値」）を担当するサービスが区間ごとの値の口（`SegmentValueService`の`segment_values`）を持たないときも同じ。

## 引いた地図の道1本の値（`domain/dynamic_way_values.py: paint_folded_feature_values`）

道1本を1つのフィーチャーにするズーム（`EDGE_UNIT_MIN_ZOOM`より下）では、道1本の値を、その道を**ルートとして走ったときの
ルートの値と同じ決まり**で出す——その道の区間をルートの区間に見立て、区間ごとに評価した得点を区間の長さで平均する
（`domain/route.py: merge_axis_difficulties`）。道1本の材料で評価すると、区間ごとに値の違う材料（割合・勾配）では、
得点が折れ線を通る前に平均されて、走ったルートの値と食い違う。

- **畳む軸**（`folds_segments`）: 密度の軸（`domain/axis_definitions.py: averages_density`）でなく、内部軸まで辿った葉の材料に
  区間ごとに値が違いうる材料（`domain/material_catalog.py: segment_material_ids`。値式が区間の値を読む材料）を持つ軸。
  密度の軸は畳まない——ルートの値は横軸の値（1kmあたりの量）の距離平均の得点で、道1本の材料（道の数÷道の長さ）がその
  平均と同じ値になる。ほかの軸は区間ごとの得点が道1本の得点と同じなので、区間を読まない。
- **区間の材料**: 区間ごとに値が違いうる材料は区間の値（`services/feature_materials.py: FeatureMaterialService.segments`）、
  ほかの材料は区間が属する道の値。配信のサービスが配る材料のうち区間ごとに違いうるもの（勾配）は、サービスが区間ごとの
  値を配る（下の「`GradientWayService`」）。風・雨は区間ごとに引き直さず、道の値を区間に配る。
- **符号付き材料を塗る軸**（勾配）: 畳んだ得点を、その得点に当たる材料の大きさへ戻し
  （`domain/axis_definitions.py: BreakpointLinearShape.smallest_magnitude_at`）、区間の材料の値の距離平均の符号（道全体で
  上るか下るか。0なら正）を付ける。段はルートの値と揃い、凡例は材料の目盛り（%）と上り・下りの塗り分けのまま。上って
  下る道も坂のきつさの色になり、上りと下りが釣り合う道はどちらかの色に寄る。
- 区間の無い道（長さ0の区間しか作れない道等）は、道1本の材料で評価する。走行方位で決まらない道は`null`のまま。
  区間の材料が読めないタイル（取込範囲外・DB障害）は値なし（`{}`）。
- 区間の材料を読むのは道1本のズームで畳む軸を要求されたときだけで、読み直しは重い（2026-10-10 の本番の実測で、
  都心 z12 の初回が約4秒）ので、タイルの材料と同じキャッシュに持つ（下の「キャッシュ」）。

## API（`api/routers/region.py`）

`GET /api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}?bearing_deg=&at=&speed_kmh=`

```
axis_id → get_dedicated_way_value_service(axis_id) が今の軸の集合の写しで軸のレンズ（AxisWayValueLens）を組む
          （公開していない軸・未知の軸はNone→404）
        → lens.values(z, x, y, WayValueQuery(at, bearing_deg, speed_kmh))
            軸と内部軸の葉の材料のうち、配るサービスのある材料ごとに
              assemble_conditions(service.conditions_type, 要求)
                （要る条件が1つでも欠けていれば何も読まずに欠けた名前を返す→422。要らない条件は無視）
              → service.get_way_values(z, x, y, 条件)   … 材料の値（勾配はキャッシュ対象）
            葉の材料にサービスの無い材料があれば FeatureMaterialService.materials(z, x, y)
              … タイルのフィーチャーごとの材料（キャッシュ対象。取込範囲外・DB障害は{}を返す）
            → paint_feature_values(axis_id, 軸の集合, 鍵, タイルの材料, サービスの値)
        → {フィーチャーの鍵: 地図表示値} の辞書（JSON。鍵はタイルが焼いた`feature_key`と
          同じもので、ズームによって区間・wayのどちらかになる）
```

- 応答は材料の生値ではなく**地図が塗る値**。`map_paint`の塗る値が難易度の軸
  （風等）は軸定義（breakpoints・priority_overrides・参照する内部軸）で評価した難易度0〜100、
  符号付き材料の軸（勾配: 単一材料・`preprocess="abs"`）は符号付き材料生値のまま。
  ルート確定後のルート線色分け（`axis_difficulties`／符号付き材料の直読み）と同じ
  スケールになる。
- 段階の境界も`map_paint`が同じスケールへ揃えて返す（[axis-studio.md](axis-studio.md)「地図が塗るもの」）。
- **勾配のサービスが配るフィーチャーの値は、属する区間の勾配の値式を長さで重み付けて平均したもの**
  （`road_tile_sql.py: FEATURE_GRADIENT_INPUTS_IN_TILE_SQL`。集約の式は`domain/material_sql.py: length_weighted_mean_sql`）。区間単位のズームでは属する区間が1本なので
  その区間の値そのもの、way単位のズームではwayの全区間をならした値になる。符号付きで平均する
  ため、結果はwayの両端の標高差を全長で割った値と一致し、崖を下って上り返す道は打ち消し合って0%になる。
  **地図の勾配の軸は、way単位のズームではこの値を塗らず、区間から畳んだ値を塗る**（上の「引いた地図の道1本の値」）。
  この値は、走行方位で決まらない道（`null`）と、区間の無い道の値に使う。
  区間は道の点を並びの順に切ったもので、どの区間の勾配も道と同じ向き（ジオメトリの始点→終点）を正とするため、
  向きを揃え直さずに平均する。区間の方位で揃え直すと、つづら折りの区間の符号が反転して登り続ける道が0%近くになる
  （`tests/test_feature_gradient_inputs.py`）。
- **勾配では、走行方位は符号だけを決める**（`domain/gradient.py`）。道路は道路に沿ってしか
  走れず、その道を走るときの進行方向は道路の向きそのもののため、方位が決められるのは
  「どちら向きに辿るか」だけで、坂の急さは変わらない。角度差を係数に掛ける（cos投影）と
  同じ坂が方位次第で緩く見え、ルート評価（`average_grade`をそのまま読む）とも食い違う。
  風（`wind_drag_ratio`）は風向が進行方向と独立に決まるためcos投影が正しく、ここは同型に
  できない。
- **指定方位に対して直角に近い道路は、勾配の値を`null`で配る**
  （`domain/gradient.py: effective_gradient`がNoneを返す。地図では「向きで決まらない」）。直角付近はその道を
  どちら向きに辿るかが決まらず符号を選べない。0%として配ると、実際には急な坂の道が凡例の
  「平坦」の段へ入り、平坦な道と同じ色で塗られる——言えるのは「勾配を示せない」であって
  「平坦だ」ではない。結果から落とすと、値の無い道（「データなし」）と見分けられない。
  `null`にする幅（`LENS_PERPENDICULAR_BAND_DEG`）は実地を見て決め直す値。区間インスペクタは`null`の材料を
  値の無い材料と同じく足さない。
- 各サービスは`material_id`属性で自分が返す生値の材料idを宣言し、レンズはそれを軸定義の
  どの材料として評価するかに使う。勾配は`gradient_percent`固定、風は`wind_drag_ratio`固定
  （走行速度依存、`speed_kmh`必須）。
  キャッシュはタイルの材料もサービスの値も軸に依らない材料の値のまま持つため、軸スタジオでbreakpointsを変えても
  キャッシュを捨てずに次の応答から反映される。評価できない値（軸が他の材料も必須にしている等）はその道路を
  結果から除く（地図上は「データなし」）。`null`（走行方位で決まらない）は`null`のまま返す。
- `GET /api/axis-catalog`は同じ値を`map_paint`として公開し、frontendは色式と凡例の段の範囲の文字をそこから
  組み立てる（ルート確定の前後とも。[地図: 軸・ルート色分け](../frontend/map-axis-coloring.md)参照）。

- ルート確定後は呼ばれない専用エンドポイント（フロントは`axis_difficulties`を使う）。
- 静的な路面タイル（`/api/region/road-surface-tiles`、MVT）とは別経路——フロントは
  同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で合成する
  （[map-axis-coloring.md](../frontend/map-axis-coloring.md)参照）。
- 路面・点のタイルと同じレート制限・座標検証・DB接続プールのsemaphore
  （`_region_tile_semaphore`、`config.py: road_tile_max_concurrent`）を共有する。

## タイルの材料（`services/feature_materials.py`）

タイル1枚ぶんのフィーチャーごとに、全部の材料（`domain/material_catalog.py: material_value_sql`を持つ材料）を読む
（`infrastructure/road_tile_sql.py: FEATURE_MATERIALS_IN_TILE_SQL`）。

- フィーチャーの並びと材料の表の結び方は路面タイルと同じ（区間単位のズームは区間の値、way単位のズームと区間を
  持たない道は道1本の行の値。密度の分母の長さもフィーチャーと同じ側から取る）。
- 値は探索と同じ値式で求め、タイルへ焼くときの丸め・係数（`tile_column_sql`・`tile_unscaled_sql_params`）を通さない。
  事故の密度は今の収録年数（`RoadGraphRepository.get_accident_years_covered`）で割る。区間単位のズームで、
  探索が同じ区間に読む材料と同じ値になる（`tests/test_feature_materials_in_tile.py`）。
- 取込範囲外・DB障害・フィーチャーの無いタイルは値なし（地図の配信は`{}`）。
- 道1本のズームの**区間の材料**（`FeatureMaterialService.segments`、`infrastructure/road_tile_sql.py: FEATURE_SEGMENTS_IN_TILE_SQL`）は、
  タイルに入る道ごとにその道の全区間（タイルの外の区間も）を、区間ごとに値が違いうる材料だけ、探索と同じ値式で区間の行から
  読む（`tests/test_feature_materials_in_tile.py`）。区間には、属する道の両端を結ぶ方位（勾配のサービスがフィーチャーの値に
  使うのと同じ方位）を添える。

## キャッシュ

### タイルの材料（`infrastructure/feature_material_cache.py`）

読んだタイルの材料と区間の材料をディスク（`tile_persistent_cache`）へ持つ。鍵は`(路面タイルの世代, 読み方の署名, z, x, y)`で、
軸の定義・走行方位・時刻を入れない——材料はどれにも依らず、どの軸の要求も同じタイルの材料を共有する。

- **路面タイルの世代**: 材料の鍵は路面タイルの`feature_key`と一致して初めて意味を持ち、派生の作り直しで同じSQLでも
  別の値になる。世代は派生の表と生データの両方を覆い、事故の収録年数も派生の作り直しと一緒に変わる。世代を読めない
  ときに読んだ材料は持たない（`infrastructure/cache_identity.py: is_known_tile_version`）。
- **読み方の署名**（`services/feature_materials.py: FEATURE_MATERIALS_VALUE_SHAPE`・`FEATURE_SEGMENTS_VALUE_SHAPE`）: 材料と区間の材料は
  この署名で別のエントリになる。読み出しのSQLの形と、持つ値の
  列の組から機械で署名する。SQLを変えたデプロイの直後から前の読み方のエントリは読まれなくなり、TTL（24時間）で失効する。
- 取込範囲外・空のタイル・DB障害は持たない（次の要求で読み直す）。
- Redisに置かないのは、失っても自前のPostGISから読み直せるため（[.claude/rules/caching-retention.md](../../../.claude/rules/caching-retention.md)
  「Redisへ置くもの・置かないもの」）。読み直しの重さは、本番でタイルを焼く文と同じ結び方で全材料を読んで都心 z12 で
  0.65秒・z14 で0.08秒（2026-10-10 の実測）。1エントリの大きさ（材料の列×フィーチャー数）は未計測。
- hit/missは`FeatureMaterialService`の`log_external_call`（`region:feature-materials`・`region:feature-segments`）の`fields["cache"]`に書く。

### 配信サービスの値（`infrastructure/dynamic_way_value_cache.py`）

**配信サービスの値でキャッシュするのは勾配だけ**（雨はタイルごとの値を持たず、観測所ごとの材料の値だけをプロセス内に
短く持つ。下の「`RainWayService`」）。風は予報の格子点の風を配列でまとめて引くだけで計算が軽く、
キャッシュが節約するのは1タイルあたり2.8ms（応答53msの5%。タイル中心1点の風を全wayへ配っていた版の
本番実測）にとどまる一方、1エントリ190KBを保持することになるため、キャッシュせず都度計算する。勾配はフィーチャー単位の計算で
809msを節約できるためキャッシュする（[.claude/rules/caching-retention.md](../../../.claude/rules/caching-retention.md)
「キャッシュしないという選択」参照）。

保持層は**ディスク**（`tile_persistent_cache`＝diskcache）。失っても外部へは取りに行かず
自前で再計算できるためRedisは使わず、1エントリが190KBでキーが
(タイル×向き)の組み合わせで増えるためプロセス内メモリにも置かない。

キーは`_key(material_id, z, x, y, bearing_deg)`のタプルへ**路面タイルの
世代**（配信している路面タイルと同じ文字列。形の署名とDBの世代を含む）と**材料の値の作り方の署名**（`value_shape`）を
加えたもの（`material_id`は各サービスの`material_id`属性がそのまま入る）。値は材料の生値で軸に依存しないため、
同じ材料を参照する軸が複数あってもキャッシュを共有する。

**材料単位の失効は鍵で表す**。`value_shape`は材料のサービスが必須キーワードで渡し、勾配は
`services/gradient_way_service.py: GRADIENT_VALUE_SHAPE`（入力のSQLの署名
`infrastructure/road_tile_sql.py: FEATURE_GRADIENT_INPUTS_SHAPE`・直角付近で値を決めない幅・丸めの桁を
機械で署名し、式を変えたときだけ手で上げるリビジョンを添えたもの）。材料の計算を変えたデプロイの直後から、その材料のエントリだけが読まれなくなり、
他の材料のエントリは残る。タグで消す方式（起動時に材料ごと`evict`）にしないのは、デプロイで入れ替わるまで
旧コンテナが同じ置き場へ古い計算の値を書き続け、消した直後に同じ鍵へ戻るため。読まれなくなったエントリは
TTLで失効し、書き込みのたびに`diskcache`が失効したものを消す（容量上限の退避とは別に働く）。

**世代を鍵へ入れる理由**: ここに入る鍵は路面タイルの`feature_key`と一字一句一致して初めて
意味を持つ（フロントが`setFeatureState`のidとして使う）。タイルの焼き方を変えたデプロイの
直後、世代が鍵に無いと、前の版の鍵を持つエントリが**どの地物にも一致しないままTTLが切れる
まで返り続け、色だけが静かに消える**（エラーにならない）。
`domain/dynamic_way_values.py: bearing_bucket`が向きを`BEARING_BUCKET_DEG`（5度）刻みで離散バケット化するため、
パン・ズームで同じタイルが再び視界に入っても、同じバケットの範囲内ではDBへの再問い合わせも
再計算も発生しない。時刻・想定速度は鍵に入れない——キャッシュする勾配はどちらにも依らず、
依る材料（風）はキャッシュしない。時刻・速度に依る材料をキャッシュするときは、その要素を鍵へ足す。

値は`{feature_key: 値}`のdict。TTLはこのモジュールが持つ（24時間。勾配の入力は道の向きと標高で決まりほぼ変わらない）。正本を持たないキャッシュで、読み書きに失敗しても未キャッシュ扱いで実計算へ進む。
このモジュール自身は`log_external_call`で囲まない。hit/missは呼び出し元のサービスが自分の
`log_external_call`の`fields["cache"]`へ書き、`/api/debug/stats`のそのカテゴリのヒット率に載る
（[.claude/rules/logging.md](../../../.claude/rules/logging.md)「外部API・キャッシュアクセス」節）。

## サービス実装

### `WindWayService`（`wind_way_service.py`）

走行方位（`bearing_deg`）は**ユーザーがコンパススライダーで指定した単一の値**（全道路
共通）を使う。道路自身のOSM格納方向は使わない——ルートを出す前は、その道をどちら向きに走るかが
決まっていない。

**予報の地点と時刻の選び方はルート確定後の区間と同じ**（同じ事実を1か所で持つ。
[設計原則](../../architecture/design-principles.md)構造仕様17）。各フィーチャーは中ほど（両端の平均。
区間単位のズームでは、ルートの区間の中点と同じ点）に最も近い予報の格子点（`domain/wind.py: WindLattice`）の、
指定時刻に最も近い時刻の風を引き（`WindForecastSeries`）、値は同じ評価器
（`domain/dynamic_materials.py: evaluate_dynamic_material_arrays`）で求める。格子は緯度・経度0度から数えた
固定の線に揃えてあるため、タイルに敷いても探索範囲に敷いても同じ地点は同じ格子点へ寄る。同じタイルでも、
中ほどが別の格子点に近い道は別の値になる。

違うのは**予報の範囲の外の時刻**だけで、ルートの区間は予報の端の値で延ばして印を付けるが、地図は塗らない
（「データなし」）。延ばした値は探索では「値が無いより妥当」として使うが、地図で色として見せるには当てにならない。

```
get_way_values(z, x, y, WindConditions(bearing_deg, speed_kmh, at))
  ├─ 時刻をJSTのローカル時刻へ（tz付きはJSTへ変換してからtzinfoを外す）
  ├─ get_feature_midpoints_in_tile → 鍵ごとの中ほど（カバレッジ外はNone→{}、DB障害も{}。それ以外の例外は500）
  ├─ get_wind_forecast_lattice(タイルと全フィーチャーの中ほどを覆う矩形)（読めなければ{}）
  │     … タイルをまたぐ道の中ほどはタイルの外にありうる。格子の外の点は端の格子点へ寄せられるため、覆う
  ├─ sampled_times で時刻が予報の範囲の外（端へ寄せた）なら{}
  ├─ evaluate_dynamic_material_arrays(DynamicAxisRequestContext(一律の方位, 通過時刻0, 各中ほどの格子点))
  └─ 戻り値は {feature_key: 値}   … 生値。難易度への変換はrouter側
```

**この値はキャッシュしない**。タイル1枚ぶんを1回のMSM読み出しと配列演算で求めるだけで計算が軽く、
保持コスト（1エントリ190KB）に見合う節約にならない（下の「キャッシュ」節と
.claude/rules/caching-retention.md「キャッシュしないという選択」）。

### `GradientWayService`（`gradient_way_service.py`）

風と異なり、`gradient_percent`自体が道路の始点→終点方向を基準にした符号付き値のため
**道路自身の向きが本質的に必要**（風は利用者の1つの方位を全道路へ当てるが、勾配は道路ごとの
向きで値が決まる）。

入力は`RoadGraphRepository.get_feature_gradient_inputs_in_tile`が返す`(gradient_percent,
road_bearing_deg)`のフィーチャー単位dict（勾配は属する区間の`edge_elevation.average_grade`から、
方位はフィーチャーのジオメトリの両端を結ぶ方位）。区間単位のズームではその区間の実際の勾配が
そのまま返り、way単位のズームでは**区間を長さで重み付けて平均した値**が代表になる（上の「API」の勾配の節）。

way単位のズームで区間から畳むときの区間ごとの値（`segment_values`）は、区間の勾配に、区間が属する道の両端を結ぶ方位で
符号を付ける（道1本の値と同じ向き。区間の方位で付けるとつづら折りの区間の符号が反転する）。道が走行方位に直角に
近ければ、その道の区間は値を決めない。

**暗黙の前提（モジュール間の隠れた依存）**: この入力のSQLは`em.average_grade IS NOT NULL`を
要求するため、[elevation.md](elevation.md)の
派生（`derive_elevation.py`）が該当区間の勾配を出していない（または勾配を出さないと
決めた区間）の場合、その鍵は勾配タイルの結果から静かに除外される——エラーには
ならず、単に地図上でその道路に勾配の色が付かないだけに留まる。

```python
effective = (
    (feature_key, GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, bearing_deg))
    for feature_key, (gradient_percent, road_bearing_deg) in inputs.items()
)
values = {feature_key: round(value, 1) for feature_key, value in effective if value is not None}
```

受け取る条件は走行方位だけ（`GradientConditions`）。時刻・想定速度は要求にあっても組み立てで落ちる。

### `RainWayService`（`rain_way_service.py`）

1つの実装が雨の材料すべて（`domain/rain.py: RAIN_MATERIAL_IDS`——窓ごとの雨量と雨が止んでからの時間）を担当し、
どの材料を返すかは組み立てるときに受け取る。値は**最寄りの雨量計の今の観測**で、走行方位・時刻・想定速度には
依らない（受け取る条件`RainConditions`は空）。出発時刻の予報で延ばすことはしない。

```
get_way_values(z, x, y, ...)
  ├─ WeatherService.get_station_rain_materials(今) → 観測所ごとの材料の値（無い・古ければ{}）
  ├─ get_feature_midpoints_in_tile → 鍵ごとの中ほど（カバレッジ外・空は{}、DB障害も{}）
  ├─ rain_material_columns（domain/rain.py）: 中ほどに最も近い雨量計の値
  └─ 欠測（NaN）の道は結果から除く
```

- **候補は雨量計を持つ観測所だけ**（正時の地図JSONに1時間雨量の項目がある観測所）。気温だけの観測所が
  近くにあっても、その値は無い。**最寄りの雨量計が欠測なら、次に近い雨量計で埋めない**——近さの順に
  埋めると、同じ道が欠測の有無で別の雨量計の値へ静かに切り替わる。
- 最寄りは球面の距離で決める（`domain/geo.py: nearest_point_indices`。アメダス・暑さ指数の1地点の最寄りも同じ関数）。ルートの探索範囲は数百万区間になるため、
  全区間×全観測所の距離は作らず、緯度・経度の格子ごとに最寄りになりうる観測所だけを候補に残して比べる
  （粗い格子で絞ってから細かい格子で絞る。どちらも三角不等式で、最寄りを落とさない）。
- **ルートの区間も同じ関数で、区間の中点の値を引く**（[ルーティングエンジン](routing-engine.md)
  「`prepare(origin, points, radius_km)`」）。区間単位のズームのフィーチャーの中ほどはルートの区間の中点と同じ点なので、地図の色と
  ルートの区間の値は同じ雨量計の同じ観測になる。
- 観測所ごとの材料の値は`jma_amedas_service.py: load_station_rain_materials`がRedisの履歴から組み立て、`WeatherService`の実体の中に5分持つ
  （タイル1枚ごとに全観測所×全時間の履歴を読み直さない）。履歴の取り方は
  [気象・動的レイヤー](weather-dynamic-layers.md)「`JmaAmedasService`」。
- **材料の値は観測どおりの量**（mm・時間）で、どこからを濡れているとみなすかは軸の折れ点が決める。
  値の定義（窓の中に欠測があれば値なし、止んでからの時間の上限）は材料カタログの説明と`domain/rain.py`が持つ。

各サービスとも`get_way_values(z, x, y, 条件) -> dict[str, float]`という同じ形で、地図のレンズと区間インスペクタから
材料非依存に呼ばれる（`services/dedicated_way_values.py: AxisWayValueLens.values`・`way_values`）。条件は`assemble_conditions`が組み立てたそのサービスの`conditions_type`の値
（上の「軸登録と要求の条件」）。

各サービスが例外を空dictへ倒すのは**DB障害だけ**（`database.py: DB_UNAVAILABLE_ERRORS`。
[横断インフラ](cross-cutting-infrastructure.md)「DB障害として扱う例外」節）。リポジトリとの
引数の食い違いのような実装の誤りまで空へ倒すと、応答は200・空のままになり、地図では
「データなし」と見分けがつかない。

## 純粋計算ロジック（domain層）

| 関数 | 意味 | 符号 |
|---|---|---|
| `wind_drag_ratio_array`／`wind_drag_ratio`（`wind.py`） | 走行方位・風向風速・走行速度から、相対風速ベクトルの二乗則で無風時に対する空気抵抗の増分（時速20km無風の抵抗を1とする倍率、`WIND_DRAG_REFERENCE_SPEED_MS`） | 正=向かい風、負=追い風、純横風は小さな正。速いほど同じ風で大きい |
| `GradientCalculator.effective_gradient`（`gradient.py`） | 道路自身の勾配・向きと走行方位から実効勾配 | 正=登り、負=下り（大きさは道路自身の勾配のまま。直角付近はNoneで、配信は`null`として配る） |

`wind_drag_ratio_array`は走行方位との角度差を係数として物理量へ反映するが、
**`effective_gradient`は角度で大きさを変えない**——道路自身の勾配をそのまま使い、走行方位で
決めるのは符号（登り／下り）だけ。示せない向き（直角に近く、どちら向きに辿るかが決まらない）
では同じ関数がNoneを返し、値は`null`として配られる。同じ道路の逆方向（forward/backward）の
`road_edges`行を使っても勾配の結果は変わらない（向きと勾配の符号が二重に反転して相殺する）。
`wind_drag_ratio_array`は横風0のとき1次元式`sign(x)·x² − v²`（x=走行速度+
向かい風成分）と一致し、追い風が走行速度を超える領域も連続。引数はスカラー・配列どちらも
受け付け（numpyのブロードキャスト）、`domain/dynamic_materials.py: DYNAMIC_MATERIAL_EVALUATORS`が
探索・区間表示・ルートを出す前の地図の唯一の呼び出し元（[evaluation-scoring.md](evaluation-scoring.md)参照）。
スカラー版の`wind_drag_ratio`は、材料カタログの説明に載せる代表値の計算
（`material_catalog.py`）だけが使う。

## ルート確定後の風の評価

風の方向はEdge自身の`bearing_deg`（directed edgeのためルート実走行方向と一致）を使う。
風の時刻はEdgeごとの通過予定時刻（基準点からの直線距離×迂回率÷仮定巡航速度、
`domain/wind.py: estimate_passage_hours`）で、探索範囲を覆う格子点ごとの時別予報（`WindForecastSeries`、
各Edgeは中点に最も近い格子点）から引き、レグ（往路/復路）ごとに別のコスト配列として探索前に合成する。区間表示
（`RouteSegmentDetail.material_values`・`wind`）は、探索がその区間に使った時刻ビンの値を読む（詳細は
[routing-engine.md](routing-engine.md)「レグ内の時刻ビン」「レグ別コスト配列」参照）。

`ASSUMED_SPEED_KMH`（`domain/route_request.py`、仮定巡航速度の既定値20km/h、`MIN/MAX_ASSUMED_SPEED_KMH`
＝5〜60）はリクエスト（`assumed_speed_kmh`）で上書きでき、通過予定時刻・走行モデルの巡航速度
（区間の到達予想と所要時間はこの走行モデルの秒から出る）と、風の材料`wind_drag_ratio`の走行速度（`kmh_to_ms`でm/sへ変換して
`DynamicAxisRequestContext.travel_speed_ms`へ渡す）に使う。`ROUTE_DETOUR_RATIO`（1.3）は道なり距離／直線距離の初期値で、探索範囲ごとに往路木から
測った実測中央値を学習して置き換える（[routing-engine.md](routing-engine.md)参照）。
