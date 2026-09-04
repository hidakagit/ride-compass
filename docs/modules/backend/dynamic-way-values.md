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

## 材料登録（`domain/dynamic_way_values.py`）

```python
def dynamic_way_value_materials() -> dict[str, DynamicWayValueMaterial]:
    return {
        axis_id: DynamicWayValueMaterial(
            material_id=axis_id, label=definition.label,
            needs_time=definition.dynamic_way_value_needs_time,
            needs_bearing=definition.dynamic_way_value_needs_bearing,
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
- `dedicated_way_value_layer=True`の軸は現状wind/gradientの2軸のみ。

`api/dependencies.py: get_dynamic_way_value_service`内の`_DYNAMIC_WAY_VALUE_SERVICE_
FACTORIES`は、material_id→サービス実装本体（`WindWayService`/`GradientWayService`）の
組み立てを担う別のdict。こちらはPython実装本体（コンストラクタ）の登録のため軸スタジオの
宣言だけでは代替できず、新しい材料を追加する際は引き続きコード変更が必要
（`dynamic_way_value_materials()`側とは別軸・別タイミングで拡張できる）。

## API（`api/routers/region.py`）

`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}?bearing_deg=&at=`

```
material_id → dynamic_way_value_materials().get(material_id)（無ければ404）
            → needs_bearing かつ bearing_deg 省略 → 422
            → get_dynamic_way_value_service(material_id) が WindWayService/GradientWayService を組み立て
            → service.get_way_values(z, x, y, at, bearing_deg)
            → {way_id: 値} の辞書（JSON）
```

- ルート確定後は呼ばれない専用エンドポイント（フロントは`axis_difficulties`を使う）。
- 静的な路面タイル（`/api/region/road-surface-tiles`、MVT）とは別経路——フロントは
  同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で合成する
  （[map-axis-coloring.md](../frontend/map-axis-coloring.md)参照）。
- 路面・POIタイルと同じレート制限・座標検証・DB接続プールのsemaphore
  （`_region_tile_semaphore`、`config.py: road_tile_max_concurrent`）を共有する。

## キャッシュ（`infrastructure/dynamic_way_value_cache.py`）

タイル単位の値を地図表示専用のRedisキャッシュへ格納する。キーは
`_key(material_id, z, x, y, hour_bucket, bearing_deg)` — `bearing_bucket(bearing_deg)`が
向きを`BEARING_BUCKET_DEG`（5度）刻みで離散バケット化するため、パン・ズームで同じ
タイルが再び視界に入っても、同じ時刻バケット・向きバケットの範囲内では風グリッド・
DBへの再問い合わせは発生しない。

値は`{way_id: 値}`のJSONオブジェクトで、風のように「タイル内全wayが同値」の場合も
勾配のように「way単位で異なる値」の場合も同じ表現で吸収する。TTLは呼び出し元が渡す
（風=`WIND_GRID_CACHE_TTL_SECONDS`＝3時間、勾配=`GRADIENT_TILE_VALUES_TTL_SECONDS`＝
24時間）。正本を持たないキャッシュで、Redis障害時はfail-open（未キャッシュとして
扱い実計算へ進む）。

## サービス実装

### `WindWayService`（`wind_way_service.py`）

走行方位（`bearing_deg`）は**ユーザーがコンパススライダーで指定した単一の値**（全道路
共通）を使う。道路自身のOSM格納方向は使わない。同じタイル内の全wayは常に同じ
`wind_penalty`値を持つ（風グリッドもタイル中心1点で代表させる近似のため）。

```
get_way_values(z, x, y, at, bearing_deg)
  ├─ repository未接続 → {}
  ├─ get_way_ids_in_tile → way_id一覧（カバレッジ外はNone→{}、DB障害も{}）
  ├─ hour_bucket = at.strftime("%Y-%m-%dT%H")
  ├─ キャッシュhit → 値を1個取り出す（下記「暗黙の前提」参照）
  └─ キャッシュmiss →
       nearest_grid_point(タイル中心) → get_wind_grid([grid_point])
       → _nearest_time_index（範囲外はNone→{}）
       → WindCalculator.wind_penalty(speed, direction, bearing_deg)
       → 全way_idへbroadcastしてキャッシュ書き込み
  └─ 戻り値は常に dict.fromkeys(way_ids, penalty)
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

両サービスとも`get_way_values(z, x, y, at, bearing_deg) -> dict[int, float]`という
同じシグネチャで`region.py`から材料非依存に呼ばれる。

## 純粋計算ロジック（domain層）

| 関数 | 意味 | 符号 |
|---|---|---|
| `WindCalculator.wind_penalty`（`wind.py`） | 走行方位と風向風速から向かい風/追い風の影響 | 正=向かい風、負=追い風、0付近=横風 |
| `GradientCalculator.effective_gradient`（`gradient.py`） | 道路自身の勾配・向きと走行方位から実効勾配 | 正=登り、負=下り、0付近=道路をほぼ横切るだけ |

両者とも「`cos(道路/風の基準方向 − 走行方位)`を係数として物理量へ掛ける」という同型の
連続補正モデルを踏襲している。同じ道路の逆方向（forward/backward）の`road_edges`行を
使っても勾配の結果は変わらない（cosの偶関数性と符号の二重反転が相殺するため、
`test_gradient.py: test_forward_and_backward_edge_agree`で検証済み）。

## ルート確定後の風の評価

風の方向はEdge自身の`bearing_deg`（directed edgeのためルート実走行方向と一致）を使う。
風の時刻はEdgeごとの通過予定時刻（基準点からの直線距離×迂回率÷仮定巡航速度、
`domain/wind.py: estimate_passage_hours`）で起点の時別予報（`WindForecastSeries`）から
引き、レグ（往路/復路）ごとに別のコスト配列として探索前に合成する。区間表示・`wind_score`
は探索に使ったその配列から読む（詳細は[routing-engine.md](routing-engine.md)
「レグ別コスト配列」参照）。

`ASSUMED_SPEED_KMH`（`domain/wind.py`、仮定巡航速度の既定値20km/h、`MIN/MAX_ASSUMED_SPEED_KMH`
＝5〜60）はリクエスト（`assumed_speed_kmh`）で上書きでき、通過予定時刻・区間の到達予想時刻・
所要時間表示に使う。`ROUTE_DETOUR_RATIO`（1.3）は道なり距離／直線距離の想定比。
