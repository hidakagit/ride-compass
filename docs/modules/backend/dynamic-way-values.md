# 動的材料・フィーチャー値配信（backend）

## 責務

風・勾配のような「動的（時々刻々変わりうる）＋向きに依存する」材料について、ルート
未確定時に視界内の全道路へ値を配信する。配信の単位は路面タイルのフィーチャーと同じで、
ズームによってway丸ごとにも区間（road_edges）にもなる——このモジュールはどちらかを
知る必要がなく、タイルと同じ`feature_key`を鍵として扱う（[static-road-attributes.md]
(static-road-attributes.md)の`EDGE_UNIT_MIN_ZOOM`参照）。ルート確定後の風の評価は、実際には
ルーティングエンジンにより計算方法が異なる（後述「風の評価が2つの経路で非対称」）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `wind.py`・`wind_grid.py`・`gradient.py`・`dynamic_way_values.py` |
| services | `wind_way_service.py`・`gradient_way_service.py` |
| infrastructure | `dynamic_way_value_cache.py`（勾配のみ。ディスク経由） |
| api | `region.py`（`GET /api/region/dynamic-way-values/{axis_id}/...`）・`dependencies.py`（`get_dedicated_way_value_service`） |

勾配材料の入力（`edge_materials.average_grade`・`road_edges.bearing_deg`）を
DBから取り出す`infrastructure/road_graph_repository.py:
get_feature_gradient_inputs_in_tile`・`get_feature_keys_in_tile`は
[routing-engine.md](routing-engine.md)が主管するファイルに属する。

## 2つのidの名前空間（読む前の前提）

この機構には名前の似た2つのidが出てくる。**混同すると無音の404・全道路の色なしになる**
ため、常に区別する。

| id | 何を指すか | 実体 | 出てくる場所 |
|---|---|---|---|
| **軸id** (`axis_id`) | 評価軸そのもの。軸スタジオでDBの行として増減する | `axis_definitions.axis_id` | APIのパスパラメータ、`dedicated_way_value_axes()`のキー |
| **材料id** (`material_id`) | サービスが返す生値が軸定義のどの材料か。例: `wind_drag_ratio`・`gradient_percent` | `material_catalog.py`のキー | 各サービスの`material_id`クラス属性、`_DEDICATED_WAY_VALUE_SERVICE_FACTORIES`のキー、キャッシュの名前空間、`transform_dedicated_way_values`の第2引数 |

**実装は軸idを持たない。** 軸とサービスは、軸定義が参照する材料（`AxisDefinition.materials`）と
サービスの`material_id`の突き合わせで結ばれる。材料はコードが正本（GUIから増減しない）なので、
実装が材料の名前を知るのは、DBの行で増減する軸の名前を知るのとは違う。公開済みの軸は直さずに
複製して改良するため、軸の名前で結ぶと複製した軸が配信されない。

`tests/test_dedicated_way_value_services.py`が、登録キー＝`material_id`属性であること・
`material_id`が材料カタログの既知材料であること・1つの材料を2つのサービスが担当すると
登録時に落ちることを検査する。

## 軸登録と地図表示値（`domain/dynamic_way_values.py`）

```python
def dedicated_way_value_axes() -> dict[str, DedicatedWayValueAxis]:
    return {
        axis_id: DedicatedWayValueAxis(
            axis_id=axis_id, label=definition.label,
            needs_time=definition.dynamic_way_value_needs_time,
            needs_bearing=definition.dynamic_way_value_needs_bearing,
            needs_speed=definition.dynamic_way_value_needs_speed,
        )
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if definition.dedicated_way_value_layer
    }
```

`AXIS_DEFINITIONS`（[軸スタジオ](axis-studio.md)のDB管理データ）から
`dedicated_way_value_layer=True`の軸を抽出し、呼び出しの都度（モジュール定数ではなく
関数として）導出する。`needs_time`/`needs_bearing`も軸自身のDBフィールド
（`AxisDefinition.dynamic_way_value_needs_time`/`dynamic_way_value_needs_bearing`）を
そのまま使うため、新しい専用way値配信軸を追加するときの軸スタジオでの登録
（`dedicated_way_value_layer`・`dynamic_way_value_needs_time`/
`dynamic_way_value_needs_bearing`）はこの関数の戻り値へ自動的に反映される。

ただし**配信できる値があるかは別**で、軸が参照する材料の値を組み立てるサービス本体が
`api/dependencies.py`の`_DEDICATED_WAY_VALUE_SERVICE_FACTORIES`に登録されている必要がある
（材料ごとに1回のコード変更）。軸が参照する材料のうち、登録済みのものが**ちょうど1つ**
（`served_dedicated_way_value_material`）でなければ配信できない——0件なら値が無く、2件以上は
1つのサービスが1つの材料の値しか返さないため軸を評価しきれない。そういう軸へ
`dedicated_way_value_layer`を立てることは書き込み時に拒否され（`axis_admin.py:
_check_dedicated_layer_is_implemented`）、既存データ等で万一そうなっている場合も配信側は
未知の`axis_id`と同じく404を返す（500にするとフロントの「データなし」
フォールバックが効かない）。

- `needs_time`: 時刻（`at`クエリパラメータ）に依存するか。風=Yes（気象予報）、
  勾配=No（標高・道路の向きは時刻で変わらない）。
- `needs_bearing`: 向き（`bearing_deg`クエリパラメータ）に依存するか。風・勾配とも
  Yes（向きの*出所*が異なるだけで、パラメータとしては両方ともユーザー指定の走行方位を
  必要とする）。
- `needs_speed`: 想定速度（`speed_kmh`クエリパラメータ）に依存するか。走行速度依存の
  材料`wind_drag_ratio`を参照する風軸で立てる（勾配=No）。
- `dedicated_way_value_layer=True`は軸スタジオで立てられるフラグで、配信を実装した材料を
  参照する軸なら、名前が何であってもコード変更なしにこの配信経路へ載る。

3つの`needs_*`は`GET /api/axis-catalog`が`dynamic_way_value_needs_time`/
`_needs_bearing`/`_needs_speed`としてそのまま公開し、frontendはどのクエリパラメータを
どの軸のリクエストへ載せるかをこれだけから決める（軸idの分岐を持たない。
[map-axis-coloring.md](../frontend/map-axis-coloring.md)参照）。

同じモジュールが、軸について地図が塗る値の種類を軸定義から決める:

| 関数 | 意味 |
|---|---|
| `map_value_kind(definition)` | `BreakpointLinearShape`かつ`preprocess="abs"`かつterms単数なら`signed_material`、それ以外は`difficulty` |
| `map_value_unit(definition)` | `signed_material`なら材料カタログの`unit`、`difficulty`は空文字 |
| `transform_dedicated_way_values(definition, material_id, values)` | 生値→地図表示値。`difficulty`は`evaluate_axis_scalar`で評価（同じ生値は1回だけ評価）、`signed_material`は素通し |

`api/dependencies.py`の`_DEDICATED_WAY_VALUE_SERVICE_FACTORIES`は、材料id→サービス実装本体
（`WindWayService`/`GradientWayService`）の組み立てを担うdict。こちらはPython実装本体
（コンストラクタ）の登録のため軸スタジオの宣言だけでは代替できず、**新しい材料**の配信には
コード変更が要る（同じ材料を参照する軸を増やすのには要らない）。実装はクラス属性
`material_id`と統一シグネチャの`build`を持ち、インスタンスが`DedicatedWayValueService`
（`material_id`・`get_way_values`）の形を満たせば、`_DEDICATED_WAY_VALUE_SERVICES`へ
1行足すだけで登録される（キーは`material_id`から取るため、名前を2箇所に書かない）。
1つの材料を2つのサービスが担当していると、モジュールの読み込み時（＝起動時）に落ちる。

## API（`api/routers/region.py`）

`GET /api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}?bearing_deg=&at=&speed_kmh=`

```
axis_id → dedicated_way_value_axes().get(axis_id)（無ければ404）
        → needs_bearing かつ bearing_deg 省略 → 422
        → needs_speed かつ speed_kmh 省略 → 422（それ以外の軸はspeed_kmhを無視）
        → get_dedicated_way_value_service(axis_id) が軸の参照する材料から WindWayService/GradientWayService を組み立て
          （配信を実装した材料がちょうど1つでなければNone→404）
        → service.get_way_values(z, x, y, at, bearing_deg, speed_kmh)   … 材料の生値（キャッシュ対象）
        → transform_dedicated_way_values(AXIS_DEFINITIONS[axis_id], service.material_id, 生値)
        → {フィーチャーの鍵: 地図表示値} の辞書（JSON。鍵はタイルが焼いた`feature_key`と
          同じもので、ズームによって区間・wayのどちらかになる）
```

- 応答は材料の生値ではなく**地図が塗る値**。`map_value_kind(definition)`が`difficulty`の軸
  （風等）は軸定義（breakpoints・priority_overrides）で評価した難易度0〜100、
  `signed_material`の軸（勾配: 単一材料・`preprocess="abs"`）は符号付き材料生値のまま。
  ルート確定後のルート線色分け（`axis_difficulties`／符号付き材料の直読み）と同じ
  スケールになる。
- 段階の境界は`map_value_thresholds(definition)`が同じスケールへ揃えて返す。**段そのものを
  決めるのはここではなく`axis_display.py: axis_display_for`**（ルート確定前の全道路を
  塗る境界）で、ここはその値を軸の折れ線で写すだけ。写さずに配ると、材料の単位で書かれた
  境界が0〜100と比べられ、ルート線が全区間ひとつのバンドへ落ちる。
  **上書きの有無で経路を分けない**——上書きを設定していない軸だけがNoneを返して読む側の
  既定値へ転落すると、その軸だけルート確定の前後で段の数も意味も食い違う。
- **フィーチャーの値は、属する区間を長さで重み付けて平均したもの**
  （`_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL`）。区間単位のズームでは属する区間が1本なので
  その区間の値そのもの、way単位のズームではwayの全区間をならした値になる。1区間の外れ値が
  way全体を染めることは無い（19mの区間の値で2kmの幹線が塗られていた）。符号付きで平均する
  ため結果はwayの両端の標高差と一致し、**崖を下って上り返す道は打ち消し合って0%になる**
  （絶対値で平均すれば打ち消さないが符号が失われ、登り／下りの塗り分けができない）。
  向きは各区間をフィーチャーの基準方位（ジオメトリの始点→終点）へ揃えてから平均する——
  `road_edges`は同じ区間を両方向2行で持ち、そのまま足すと必ず0になるため。
- **勾配では、走行方位は符号だけを決める**（`domain/gradient.py`）。道路は道路に沿ってしか
  走れず、その道を走るときの進行方向は道路の向きそのもののため、方位が決められるのは
  「どちら向きに辿るか」だけで、坂の急さは変わらない。角度差を係数に掛ける（cos投影）と
  同じ坂が方位次第で緩く見え、ルート評価（`average_grade`をそのまま読む）とも食い違う。
  風（`wind_drag_ratio`）は風向が進行方向と独立に決まるためcos投影が正しく、ここは同型に
  できない。
- **指定方位に対して直角に近い道路は、勾配の値を持たせずに結果から落とす**
  （`domain/gradient.py: effective_gradient`がNoneを返す。地図では「データなし」）。直角付近はその道を
  どちら向きに辿るかが決まらず符号を選べない。0%として配ると、実際には急な坂の道が凡例の
  「平坦」の段へ入り、平坦な道と同じ色で塗られる——言えるのは「勾配を示せない」であって
  「平坦だ」ではない。落とす幅（`LENS_PERPENDICULAR_BAND_DEG`）は実地を見て決め直す値。
- 各サービスは`material_id`属性で自分が返す生値の材料idを宣言し、routerはそれを軸定義の
  どの材料として評価するかに使う。勾配は`gradient_percent`固定、風は`wind_drag_ratio`固定
  （走行速度依存、`speed_kmh`必須）。
  キャッシュは生値のまま持つため、軸スタジオでbreakpointsを変えてもキャッシュを捨てずに
  次の応答から反映される。評価できない値（軸が他の材料も必須にしている等）はその道路を
  結果から除く（地図上は「データなし」）。
- `GET /api/axis-catalog`は同じ判定を`map_value_kind`・`map_value_unit`（材料カタログの
  `MaterialSpec.unit`、難易度は空文字）として公開し、frontendは色式・凡例の単位を
  これだけから組み立てる（[地図: 軸・ルート色分け](../frontend/map-axis-coloring.md)参照）。

- ルート確定後は呼ばれない専用エンドポイント（フロントは`axis_difficulties`を使う）。
- 静的な路面タイル（`/api/region/road-surface-tiles`、MVT）とは別経路——フロントは
  同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で合成する
  （[map-axis-coloring.md](../frontend/map-axis-coloring.md)参照）。
- 路面・POIタイルと同じレート制限・座標検証・DB接続プールのsemaphore
  （`_region_tile_semaphore`、`config.py: road_tile_max_concurrent`）を共有する。

## キャッシュ（`infrastructure/dynamic_way_value_cache.py`）

**キャッシュするのは勾配だけ**。風は「タイル中心1点の風を全wayへ配る」だけで計算が軽く、
キャッシュが節約するのは1タイルあたり2.8ms（応答53msの5%）にとどまる一方、1エントリ
190KBを保持することになるため、キャッシュせず都度計算する。勾配はフィーチャー単位の計算で
809msを節約できるためキャッシュする（[docs/conventions/caching.md](../../conventions/caching.md)
「キャッシュしないという選択」参照）。

保持層は**ディスク**（`tile_persistent_cache`＝diskcache）。失っても外部へは取りに行かず
自前で再計算できるためRedisは使わず、1エントリが190KBでキーが
(タイル×向き×速度×時刻)の組み合わせで増えるためプロセス内メモリにも置かない。

キーは`_key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh)`のタプルへ**路面タイルの
形の署名**（`ROAD_SURFACE_TILE_SHAPE`）と派生データの世代を加えたもの（`material_id`は各サービスの
`material_id`属性がそのまま入る）。値は材料の生値で軸に依存しないため、同じ材料を参照する軸が
複数あってもキャッシュを共有する。

**世代を鍵へ入れる理由**: ここに入る鍵は路面タイルの`feature_key`と一字一句一致して初めて
意味を持つ（フロントが`setFeatureState`のidとして使う）。タイルの焼き方を変えたデプロイの
直後、世代が鍵に無いと、前の版の鍵を持つエントリが**どの地物にも一致しないままTTLが切れる
まで返り続け、色だけが静かに消える**（エラーにならない）。
`bearing_bucket(bearing_deg)`が向きを`BEARING_BUCKET_DEG`（5度）刻み、
`speed_bucket(speed_kmh)`が想定速度を1km/h刻みで離散バケット化するため、パン・ズームで
同じタイルが再び視界に入っても、同じバケットの範囲内ではDBへの再問い合わせも再計算も
発生しない。速度に依存しない材料（勾配）は速度バケットをNoneにし、速度が変わっても
キャッシュが分割されない。

値は`{feature_key: 値}`のdict。TTLは呼び出し元が渡す（勾配=`GRADIENT_TILE_VALUES_TTL_SECONDS`
＝24時間）。正本を持たないキャッシュで、読み書きに失敗しても未キャッシュ扱いで実計算へ進む。

## サービス実装

### `WindWayService`（`wind_way_service.py`）

走行方位（`bearing_deg`）は**ユーザーがコンパススライダーで指定した単一の値**（全道路
共通）を使う。道路自身のOSM格納方向は使わない。同じタイル内の全フィーチャーは常に同じ
`wind_drag_ratio`値を持つ（風グリッドもタイル中心1点で代表させる近似のため）。

```
get_way_values(z, x, y, at, bearing_deg, speed_kmh)
  ├─ bearing_deg・speed_kmh のいずれかがNoneなら即ValueError
  ├─ repository未接続 → {}
  ├─ get_feature_keys_in_tile → 鍵の一覧（カバレッジ外はNone→{}、DB障害も{}。それ以外の例外は500）
  ├─ nearest_grid_point(タイル中心) → get_wind_grid([grid_point])
  ├─ _nearest_time_index（範囲外はNone→{}）
  ├─ wind_drag_ratio(speed, direction, bearing_deg, kmh_to_ms(speed_kmh))
  └─ 戻り値は常に dict.fromkeys(feature_keys, penalty)   … 生値。難易度への変換はrouter側
```

**この値はキャッシュしない**。タイル中心1点の風を全フィーチャーへ配るだけで計算が軽く、
節約（1タイルあたり2.8ms＝応答の5%）が保持コスト（1エントリ190KB）に見合わない
（docs/conventions/caching.md「キャッシュしないという選択」）。

### `GradientWayService`（`gradient_way_service.py`）

風と異なり、`gradient_percent`自体が道路の始点→終点方向を基準にした符号付き値のため
**道路自身の向きが本質的に必要**。風はタイル単位のスカラー値1個へ縮小できるが、勾配は
フィーチャーごとに異なる値を返す。

入力は`RoadGraphRepository.get_feature_gradient_inputs_in_tile`が返す`(gradient_percent,
road_bearing_deg)`のフィーチャー単位dict（`edge_materials.average_grade`と
`road_edges.bearing_deg`をJOINしたSQL）。区間単位のズームではその区間の実際の勾配が
そのまま返り、way単位のズームでは**区間を長さで重み付けて平均した値**が代表になる
（上の「フィーチャーの値」節と同じ規則。1区間の外れ値がway全体を染めない）。

**暗黙の前提（モジュール間の隠れた依存）**: このJOINは`em.average_grade IS NOT NULL
AND re.bearing_deg IS NOT NULL`を要求するため、[elevation.md](elevation.md)の
派生（`derive_raster_materials.py`）が該当区間の勾配を出していない（または勾配を出さないと
決めた区間）の場合、その鍵は勾配タイルの結果から静かに除外される——エラーには
ならず、単に地図上でその道路に勾配の色が付かないだけに留まる。区間は向きを持たない1行で、
勾配はジオメトリの始点→終点を正とするため、フィーチャーの基準方位とのcosの符号で向きを
揃えてから平均する。

```python
values = {
    feature_key: round(GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, bearing_deg), 1)
    for feature_key, (gradient_percent, road_bearing_deg) in inputs.items()
}
```

`at`引数はrouterとのインターフェース統一のためだけに受け取り、計算には使わない。

両サービスとも`get_way_values(z, x, y, at, bearing_deg, speed_kmh) -> dict[str, float]`という
同じシグネチャで`region.py`から材料非依存に呼ばれる（勾配は`at`・`speed_kmh`を無視する）。

両サービスが空dictへ倒すのは**DB障害だけ**（`database.py`の`DB_UNAVAILABLE_ERRORS`。
[横断インフラ](cross-cutting-infrastructure.md)「DB障害として扱う例外」節）。リポジトリとの
引数の食い違いのような実装の誤りまで空へ倒すと、応答は200・空のままになり、地図では
「データなし」と見分けがつかない。

## 純粋計算ロジック（domain層）

| 関数 | 意味 | 符号 |
|---|---|---|
| `wind_drag_ratio_array`／`wind_drag_ratio`（`wind.py`） | 走行方位・風向風速・走行速度から、相対風速ベクトルの二乗則で無風時に対する空気抵抗の増分（時速20km無風の抵抗を1とする倍率、`WIND_DRAG_REFERENCE_SPEED_MS`） | 正=向かい風、負=追い風、純横風は小さな正。速いほど同じ風で大きい |
| `GradientCalculator.effective_gradient`（`gradient.py`） | 道路自身の勾配・向きと走行方位から実効勾配 | 正=登り、負=下り（大きさは道路自身の勾配のまま。直角付近はNoneで、呼び出し側が落とす） |

`wind_drag_ratio_array`は走行方位との角度差を係数として物理量へ反映するが、
**`effective_gradient`は角度で大きさを変えない**——道路自身の勾配をそのまま使い、走行方位で
決めるのは符号（登り／下り）だけ。示せない向き（直角に近く、どちら向きに辿るかが決まらない）
では同じ関数がNoneを返し、値そのものが配られない。同じ道路の逆方向（forward/backward）の
`road_edges`行を使っても勾配の結果は変わらない（向きと勾配の符号が二重に反転して相殺する）。
`wind_drag_ratio_array`は横風0のとき1次元式`sign(x)·x² − v²`（x=走行速度+
向かい風成分）と一致し、追い風が走行速度を超える領域も連続。引数はスカラー・配列どちらも
受け付け（numpyのブロードキャスト）、`domain/dynamic_materials.py: DYNAMIC_MATERIAL_EVALUATORS`が
探索・区間表示の唯一の呼び出し元（[evaluation-scoring.md](evaluation-scoring.md)参照）。

## ルート確定後の風の評価

風の方向はEdge自身の`bearing_deg`（directed edgeのためルート実走行方向と一致）を使う。
風の時刻はEdgeごとの通過予定時刻（基準点からの直線距離×迂回率÷仮定巡航速度、
`domain/wind.py: estimate_passage_hours`）で起点の時別予報（`WindForecastSeries`）から
引き、レグ（往路/復路）ごとに別のコスト配列として探索前に合成する。区間表示
（`RouteSegmentDetail.material_values`）は探索に使ったその配列から読む（詳細は
[routing-engine.md](routing-engine.md)「レグ別コスト配列」参照）。

`ASSUMED_SPEED_KMH`（`domain/wind.py`、仮定巡航速度の既定値20km/h、`MIN/MAX_ASSUMED_SPEED_KMH`
＝5〜60）はリクエスト（`assumed_speed_kmh`）で上書きでき、通過予定時刻・区間の到達予想時刻・
所要時間表示と、風の材料`wind_drag_ratio`の走行速度（`kmh_to_ms`でm/sへ変換して
`DynamicAxisRequestContext.travel_speed_ms`へ渡す）に使う。`ROUTE_DETOUR_RATIO`（1.3）は道なり距離／直線距離の初期値で、探索範囲ごとに往路木から
測った実測中央値を学習して置き換える（[routing-engine.md](routing-engine.md)参照）。
