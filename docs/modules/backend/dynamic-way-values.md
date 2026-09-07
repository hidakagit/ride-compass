# 動的材料・way_id値配信（backend）

## 責務

風・勾配のような「動的（時々刻々変わりうる）＋向きに依存する」材料について、ルート
未確定時に視界内の全道路（way）へ値を配信する。ルート確定後の風の評価は、実際には
ルーティングエンジンにより計算方法が異なる（後述「風の評価が2つの経路で非対称」）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `wind.py`・`wind_grid.py`・`gradient.py`・`dynamic_way_values.py` |
| services | `wind_way_service.py`・`gradient_way_service.py` |
| infrastructure | `dynamic_way_value_cache.py`・`wind_forecast_cache.py` |
| api | `region.py`（`GET /api/region/dynamic-way-values/{material_id}/...`）・`dependencies.py`（`get_dynamic_way_value_service`） |

勾配材料の入力（`elevation_attributes.average_grade`・`road_edges.bearing_deg`）を
DBから取り出す`infrastructure/road_graph_repository.py: get_way_gradient_inputs_in_tile`・
`get_way_ids_in_tile`は[routing-engine.md](routing-engine.md)が主管するファイルに属する。

## 材料登録と地図表示値（`domain/dynamic_way_values.py`）

```python
def dynamic_way_value_materials() -> dict[str, DynamicWayValueMaterial]:
    return {
        axis_id: DynamicWayValueMaterial(
            material_id=axis_id, label=definition.label,
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
そのまま使うため、新しい動的＋向きあり材料を追加するときは軸スタジオでの登録
（`dedicated_way_value_layer`・`dynamic_way_value_needs_time`/
`dynamic_way_value_needs_bearing`）だけで、この関数の戻り値には自動的に反映される。

- `needs_time`: 時刻（`at`クエリパラメータ）に依存するか。風=Yes（気象予報）、
  勾配=No（標高・道路の向きは時刻で変わらない）。
- `needs_bearing`: 向き（`bearing_deg`クエリパラメータ）に依存するか。風・勾配とも
  Yes（向きの*出所*が異なるだけで、パラメータとしては両方ともユーザー指定の走行方位を
  必要とする）。
- `needs_speed`: 想定速度（`speed_kmh`クエリパラメータ）に依存するか。走行速度依存の
  材料`wind_drag_ratio`を参照する風軸で立てる（勾配=No）。
- `dedicated_way_value_layer=True`の軸は現状wind/gradientの2軸のみ。

同じモジュールが、軸について地図が塗る値の種類を軸定義から決める:

| 関数 | 意味 |
|---|---|
| `map_value_kind(definition)` | `BreakpointLinearShape`かつ`preprocess="abs"`かつterms単数なら`signed_material`、それ以外は`difficulty` |
| `map_value_unit(definition)` | `signed_material`なら材料カタログの`unit`、`difficulty`は空文字 |
| `transform_dedicated_way_values(definition, material_id, values)` | 生値→地図表示値。`difficulty`は`evaluate_axis_scalar`で評価（同じ生値は1回だけ評価）、`signed_material`は素通し |

`api/dependencies.py: get_dynamic_way_value_service`内の`_DYNAMIC_WAY_VALUE_SERVICE_
FACTORIES`は、material_id→サービス実装本体（`WindWayService`/`GradientWayService`）の
組み立てを担う別のdict。こちらはPython実装本体（コンストラクタ）の登録のため軸スタジオの
宣言だけでは代替できず、新しい材料を追加する際は引き続きコード変更が必要
（`dynamic_way_value_materials()`側とは別軸・別タイミングで拡張できる）。

## API（`api/routers/region.py`）

`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}?bearing_deg=&at=&speed_kmh=`

```
material_id → dynamic_way_value_materials().get(material_id)（無ければ404）
            → needs_bearing かつ bearing_deg 省略 → 422
            → needs_speed かつ speed_kmh 省略 → 422（それ以外の材料はspeed_kmhを無視）
            → get_dynamic_way_value_service(material_id) が WindWayService/GradientWayService を組み立て
            → service.get_way_values(z, x, y, at, bearing_deg, speed_kmh)   … 材料の生値（キャッシュ対象）
            → transform_dedicated_way_values(AXIS_DEFINITIONS[material_id], service.material_id, 生値)
            → {way_id: 地図表示値} の辞書（JSON）
```

- 応答は材料の生値ではなく**地図が塗る値**。`map_value_kind(definition)`が`difficulty`の軸
  （風等）は軸定義（breakpoints・priority_overrides）で評価した難易度0〜100、
  `signed_material`の軸（勾配: 単一材料・`preprocess="abs"`）は符号付き材料生値のまま。
  ルート確定後のルート線色分け（`axis_difficulties`／符号付き材料の直読み）と同じ
  スケールになるため、`display_thresholds_override`は軸ごとに1つの意味を持つ。
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

タイル単位の値を地図表示専用のRedisキャッシュへ格納する。キーは
`_key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh)` — `bearing_bucket(bearing_deg)`が
向きを`BEARING_BUCKET_DEG`（5度）刻み、`speed_bucket(speed_kmh)`が想定速度を1km/h刻みで
離散バケット化するため、パン・ズームで同じタイルが再び視界に入っても、同じ時刻バケット・
向きバケット・速度バケットの範囲内では風グリッド・DBへの再問い合わせは発生しない。
速度に依存しない材料（勾配）は速度バケットをNone（`-`）にし、速度が変わってもキャッシュが
分割されない。

値は`{way_id: 値}`のJSONオブジェクトで、風のように「タイル内全wayが同値」の場合も
勾配のように「way単位で異なる値」の場合も同じ表現で吸収する。TTLは呼び出し元が渡す
（風=`msm_client.update_interval_seconds()`＝配信元のrun更新間隔[3時間]、
勾配=`GRADIENT_TILE_VALUES_TTL_SECONDS`＝24時間）。正本を持たないキャッシュで、Redis障害時はfail-open（未キャッシュとして
扱い実計算へ進む）。

## サービス実装

### `WindWayService`（`wind_way_service.py`）

走行方位（`bearing_deg`）は**ユーザーがコンパススライダーで指定した単一の値**（全道路
共通）を使う。道路自身のOSM格納方向は使わない。同じタイル内の全wayは常に同じ
`wind_drag_ratio`値を持つ（風グリッドもタイル中心1点で代表させる近似のため）。

```
get_way_values(z, x, y, at, bearing_deg, speed_kmh)
  ├─ bearing_deg・speed_kmh のいずれかがNoneなら即ValueError
  ├─ repository未接続 → {}
  ├─ get_way_ids_in_tile → way_id一覧（カバレッジ外はNone→{}、DB障害も{}）
  ├─ hour_bucket = at.strftime("%Y-%m-%dT%H")
  ├─ キャッシュhit → 値を1個取り出す（下記「暗黙の前提」参照）
  └─ キャッシュmiss →
       nearest_grid_point(タイル中心) → get_wind_grid([grid_point])
       → _nearest_time_index（範囲外はNone→{}）
       → wind_drag_ratio(speed, direction, bearing_deg, kmh_to_ms(speed_kmh))
       → 全way_idへbroadcastしてキャッシュ書き込み
  └─ 戻り値は常に dict.fromkeys(way_ids, penalty)   … 生値。難易度への変換はrouter側
```

**暗黙の前提**: キャッシュhit時は`next(iter(cached.values()), 0.0)`で代表値を取り出す。
「タイル内の全way_idが同値」という前提の上に成り立つ最適化で、この前提が崩れる実装変更
（way単位に風向きを変える等）が入ると、無警告で不正確な代表値を返す。

### `GradientWayService`（`gradient_way_service.py`）

風と異なり、`gradient_percent`自体が道路の始点→終点方向を基準にした符号付き値のため
**道路自身の向きが本質的に必要**。風はタイル単位のスカラー値1個へ縮小できるが、勾配は
way_idごとに異なる値を返す。

入力は`RoadGraphRepository.get_way_gradient_inputs_in_tile`が返す`(gradient_percent,
road_bearing_deg)`のway単位dict（`elevation_attributes.average_grade`と
`road_edges.bearing_deg`をJOINしたSQL）。

**暗黙の前提（モジュール間の隠れた依存）**: このJOINは`ea.average_grade IS NOT NULL
AND re.bearing_deg IS NOT NULL`を要求するため、[elevation.md](elevation.md)の
`precompute_elevation_attributes.py`バッチが該当Edgeに対してまだ実行されていない
（または失敗した）場合、そのway_idは勾配タイルの結果から静かに除外される——エラーには
ならず、単に地図上でその道路に勾配の色が付かないだけに留まる。

```python
values = {
    way_id: round(GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, bearing_deg), 1)
    for way_id, (gradient_percent, road_bearing_deg) in inputs.items()
}
```

`at`引数はrouterとのインターフェース統一のためだけに受け取り、計算には使わない。

両サービスとも`get_way_values(z, x, y, at, bearing_deg, speed_kmh) -> dict[int, float]`という
同じシグネチャで`region.py`から材料非依存に呼ばれる（勾配は`at`・`speed_kmh`を無視する）。

## 純粋計算ロジック（domain層）

| 関数 | 意味 | 符号 |
|---|---|---|
| `wind_drag_ratio_array`／`wind_drag_ratio`（`wind.py`） | 走行方位・風向風速・走行速度から、相対風速ベクトルの二乗則で無風時に対する空気抵抗の増分（時速20km無風の抵抗を1とする倍率、`WIND_DRAG_REFERENCE_SPEED_MS`） | 正=向かい風、負=追い風、純横風は小さな正。速いほど同じ風で大きい |
| `GradientCalculator.effective_gradient`（`gradient.py`） | 道路自身の勾配・向きと走行方位から実効勾配 | 正=登り、負=下り、0付近=道路をほぼ横切るだけ |

`wind_drag_ratio_array`と`effective_gradient`はいずれも走行方位との角度差を係数として
物理量へ反映するモデル。同じ道路の逆方向
（forward/backward）の`road_edges`行を使っても勾配の結果は変わらない（cosの偶関数性と
符号の二重反転が相殺するため、`test_gradient.py: test_forward_and_backward_edge_agree`で
検証済み）。`wind_drag_ratio_array`は横風0のとき1次元式`sign(x)·x² − v²`（x=走行速度+
向かい風成分）と一致し、追い風が走行速度を超える領域も連続。引数はスカラー・配列どちらも
受け付け（numpyのブロードキャスト）、`domain/evaluation.py: DYNAMIC_MATERIAL_EVALUATORS`が
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
