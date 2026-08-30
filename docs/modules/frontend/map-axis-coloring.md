# 地図: 軸・ルート色分け（frontend）

## 責務

評価軸（軸スタジオ管理）のdifficulty値を、(1) ルート確定前は視界内の全道路（評価軸
グループの線）・環境グループの面、(2) ルート確定後は選択中ルートの線、それぞれ地図上で
色分け表示する。専用のway_id→値配信レイヤー（[動的材料・way_id値配信（backend）](../backend/dynamic-way-values.md)）
を持つ軸（現状: 風・勾配）が対象。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/routeStyleModes.ts` | ルート確定後の色分けモード一覧・色式 |
| `Map/windAxisLayer.ts`・`gradientAxisLayer.ts` | ルート確定前の評価軸グループ線の色式 |
| `Map/windPenalty.ts`・`gradientGridFill.ts` | ルート確定前の環境グループ面（gridFill）の値計算・色式 |
| `Map/dynamicWayValues.ts` | タイル座標計算・複数タイル応答の統合（材料非依存の共通部分） |
| `Map/axisLayers.ts` | ramp軸（`RAMP_AXES`）の生成、色補間ヘルパー |
| `Map/mapLayers.ts` | `isDedicatedWayValueLayerId`・`isAxisStudioLayer`（レイヤーID判定） |
| `hooks/useDynamicWayValues.ts` | フェッチ・状態管理（viewportデバウンス＋タイル単位取得） |
| `services/axisAdminApi.ts`・`regionApi.ts` | backend APIラッパー |

## ルート確定前後で異なる値source（3つの表示、共通しきい値）

```
                          [評価軸グループ（線）]                [環境グループ（面）]
ルート未確定  ── setFeatureState経由の値 ──┐   ┌── gridFill（風=風グリッド式計算 / 勾配=タイル平均） 
              （useDynamicWayValues）      │   │
                                            ▼   ▼
                                  同じ配色・しきい値を共有
                                            ▲
ルート確定後  ── RouteSegmentDetailの ──────┘   （環境グループは非表示、評価軸グループが
              axis_difficulties /              「生成したルートの色分け」モードへ役割を譲る）
              gradient_percent直読み
```

## 軸id→振る舞いの判定（データ駆動、axis_idのハードコード比較を使わない）

| 判定 | 使う軸データ属性 | 関数 |
|---|---|---|
| 専用way_id配信レイヤーを持つか | `AxisDefinition.dedicated_way_value_layer` | `mapLayers.ts: isDedicatedWayValueLayerId` |
| ルート結果色分けの選択肢に使えるか | `supports_route_coloring` | `routeStyleModes.ts: routeStyleModesFromCatalogAxes` |
| 符号付き値を直接読むべきか（勾配のような向きを持つ軸） | `shape.kind==="breakpoint_linear" && shape.preprocess==="abs" && shape.terms.length===1` | `routeStyleModes.ts: isSignedAbsShape` |

`isSignedAbsShape`が真の場合、値は`axis_difficulties[axis_id]`（0-100正規化済み）
ではなく`shape.terms[0].material`（生材料、例: `gradient_percent`）を直接読む——
向き（登り/下り）は絶対値化されたdifficultyでは表現できないため。

## routeStyleModes.ts（ルート確定後）

- `buildRangeSteppedMode`: 境界値配列（軸スタジオの`display_thresholds_override`、
  未設定時は経路ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは
  境界値の実際の数字から機械的に生成する。
- `interpolateColors(colorLow, colorHigh, count)`: 2色の間をHSL色空間でcount色に均等
  補間する（固定の色配列を持たないため、しきい値の個数が変わっても色が自動追従する）。
- `DIFFICULTY_MODE`（総合難易度）だけがフロントの固定モード——特定のaxis_idに紐づかず
  全軸の重み付き合成コストそのものを表示するため、軸スタジオと同期する対象にならない。

## windPenalty.ts / gradientGridFill.ts（環境グループの面表示、計算方法が異なる）

| | 風（`windPenalty.ts`） | 勾配（`gradientGridFill.ts`） |
|---|---|---|
| 値の出所 | 独立した空間フィールド（気象グリッド、道路とは無関係に存在） | way単位のeffective_gradient（評価軸グループ向けに既にフェッチ済み） |
| 計算方法 | `windPenalty()`——backend `WindCalculator.wind_penalty`のJS移植（物理式） | フェッチ元のタイル境界を1セルとして平均集計（追加のAPI呼び出し無し） |
| セルの単位 | 格子点を中心とする正方形（`gridCellRing`） | タイル境界そのもの（`tileRing`） |

## useDynamicWayValues.ts（フェッチ・状態管理）

viewportをデバウンス（500ms）してから、表示中のタイル範囲ぶんをまとめて1回の
リクエストで取得する（パン・ズームのたびに個別way_idを都度問い合わせない）。
`enabled=false`の間はfetchせず結果も空へ戻す。

戻り値は2種類:

- `values: ReadonlyMap<number, number>`（way_id→値、複数タイル統合済み）——評価軸
  グループの`setFeatureState`にそのまま使える。
- `byTile: TileDynamicWayValues[]`（タイルごとの生応答）——勾配の環境グループgridFill
  （タイル境界セル）が使う。風のgridFillは別経路（風グリッド由来の格子点）のため
  `byTile`は使わない。
