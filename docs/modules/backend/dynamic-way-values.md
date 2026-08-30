# 動的材料・way_id値配信（backend）

## 責務

風・勾配のような「動的（時々刻々変わりうる）＋向きに依存する」材料について、ルート
未確定時に視界内の全道路（way）へ値を配信する。ルート確定後は使わない（確定後は
ルート自身の実進行方向・実到達時刻から計算済みの`axis_difficulties`を使う）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `wind.py`・`wind_grid.py`・`gradient.py`・`dynamic_way_values.py` |
| services | `wind_service.py`・`wind_way_service.py`・`gradient_way_service.py` |
| infrastructure | `dynamic_way_value_cache.py`・`wind_forecast_cache.py` |
| api | `region.py`（`GET /api/region/dynamic-way-values/{material_id}/...`） |

## 材料登録（`domain/dynamic_way_values.py`）

```python
DYNAMIC_WAY_VALUE_MATERIALS: dict[str, DynamicWayValueMaterial] = {
    "wind":     DynamicWayValueMaterial(needs_time=True,  needs_bearing=True),
    "gradient": DynamicWayValueMaterial(needs_time=False, needs_bearing=True),
}
```

- `needs_time`: 時刻（`at`クエリパラメータ）に依存するか。風=Yes（気象予報）、
  勾配=No（標高・道路の向きは時刻で変わらない）。
- `needs_bearing`: 向き（`bearing_deg`クエリパラメータ）に依存するか。風・勾配とも
  Yes（向きの*出所*が異なるだけで、パラメータとしては両方ともユーザー指定の走行方位を
  必要とする）。
- **この辞書は`AxisDefinition.dedicated_way_value_layer`（[軸スタジオ](axis-studio.md)の
  DB管理フィールド）とは独立したハードコードで、軸スタジオの設定だけでは新規材料を
  追加できない**（[T458](../../tasks/T458.md)として起票済み）。

## API（`api/routers/region.py`）

`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}?bearing_deg=&at=`

```
material_id（パスパラメータ）
        │
        ▼
  DYNAMIC_WAY_VALUE_MATERIALS.get(material_id)
        │  無ければ404
        ▼
  needs_bearing かつ bearing_deg 省略 → 422
        │
        ▼
  get_dynamic_way_value_service(material_id) が material_id を見て
  WindWayService または GradientWayService を組み立てる
  （DBセッションを1つだけ開く単一の注入点、router側で両方Dependsしない）
        │
        ▼
  service.get_way_values(z, x, y, at, bearing_deg)
        │
        ▼
  {way_id: 値} の辞書（JSON）
```

- ルート確定後は呼ばれない専用エンドポイント（フロントは`axis_difficulties`を使う）。
- 静的な路面タイル（`/api/region/road-surface-tiles`、MVT）とは別経路——フロントは
  同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で合成する。
- 路面・POIタイルと同じレート制限・座標検証・DB接続プールのsemaphoreを共有する。

## キャッシュ（`infrastructure/dynamic_way_value_cache.py`）

タイル単位の値を地図表示専用のRedisキャッシュへ格納する。キーは
`_key(material_id, z, x, y, hour_bucket, bearing_deg)` — `bearing_bucket(bearing_deg)`が
向きを離散バケット化するため、パン・ズームで同じタイルが再び視界に入っても、同じ
時刻バケット・向きバケットの範囲内では風グリッド・DBへの再問い合わせは発生しない。

## サービス実装

- `WindWayService`（`wind_way_service.py`）: `_hour_bucket`・`_tile_center`・
  `_nearest_time_index`等のヘルパーを持つ。風グリッド由来の値を計算する。
- `GradientWayService`（`gradient_way_service.py`）: 道路自身の向きが本質的に必要な
  材料（`domain/gradient.py`参照）。
- 両サービスとも`get_way_values(z, x, y, at, bearing_deg)`という同じシグネチャで
  `region.py`から呼ばれる。
