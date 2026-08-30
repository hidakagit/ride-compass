# ルート設定・結果パネル（frontend）

## 責務

一般ユーザー向けのルート生成条件入力（距離・重み・除外道路）と、生成結果の表示・比較
（軸別内訳・候補一覧・研究モードの実験スロット比較）を担う。

**対象ファイル**

| ファイル | 行数 | 責務 |
|---|---|---|
| `components/RouteForm/RouteForm.tsx` | 166 | 距離入力・生成ボタン。周回/目的地モード切替 |
| `components/RouteSettingsPanel/RouteSettingsPanel.tsx` | 295 | 一般向け軸重み設定・除外道路・地図色分けトグル |
| `components/WeightPanel/WeightPanel.tsx` | 118 | 研究モード向けのscoring_weights（distance/difficulty）編集 |
| `components/WindBearingSlider/WindBearingSlider.tsx` | 82 | 走行方位の指定スライダー |
| `components/RouteList/RouteList.tsx` | 67 | 生成候補の一覧表示 |
| `components/RouteAxisProfile/RouteAxisProfile.tsx` | 65 | 選択中ルートの軸別difficulty横棒グラフ |
| `components/ComparisonPanel/ComparisonPanel.tsx` | 158 | 研究モードの実験スロット比較表 |

## RouteSettingsPanel.tsx（一般向けメイン設定面）

```
useAxisCatalog() ──→ catalog.axes（公開軸一覧、is_published=Trueのみ）
                          │
        ┌─────────────────┼──────────────────┐
        ▼                                     ▼
  除外する道路（0次フィルタ、               軸ごとの行:
  no_bicycle/motorway/trunk）               チェックボックス + スライダー(重み) + 「色分け」トグル
```

- 軸の一覧・既定重みは`useAxisCatalog`経由（取得完了まで・失敗時は既存軸の静的
  フォールバック）。軸スタジオでの追加が再デプロイなしに反映される。
- カテゴリ（観測/推定/動的）によるグルーピング表示は行わない（軸スタジオが常に
  `category="推定"`固定で軸を作るようになったため、フラットな1本のリストにした）。
- `mapColorLayerIdFor(axisId)`: 軸id→地図色分けレイヤーIDの解決。
  (1) `catalog.secondaryAxes`（ramp表示を持つ軸）にあればそのレイヤーID、
  (2) 無ければ`axis.dedicatedWayValueLayer`を見て`${axisId}Axis`という命名規則から
  機械的に導出（[地図: 軸・ルート色分け](map-axis-coloring.md)参照）。どちらも無ければ
  地図表示非対応。
- ルート確定後（`hasDetail=true`）は、専用way_id配信レイヤーを持つ軸（風・勾配）の
  トグルを「地図表示なし」（案内文つき）へ切り替える——ルート確定後はこれらの軸が
  「生成したルートの色分け」側の役割になるため。
- `routePreference`（送信対象）とカタログのキー集合を`syncRoutePreferenceKeys`で
  双方向同期する（軸の追加/unpublishに追従。backendは「上書きするなら既知の全axis_id
  キー一致」を要求するため、ズレるとルート生成が422になる）。

## WeightPanel.tsx（研究モード）

RouteSettingsPanelとは別の入口（研究モード向け）。`ScoringWeights`
（`distance_weight`/`difficulty_weight`の2指標）を編集する。`route_preference`
（軸ごとの重み）自体を編集するUIはもう持たない（過去に撤去済み）が、初期値の定数
export（`DEFAULT_ROUTE_PREFERENCE`、`axis-catalog.json`の`preference_defaults`由来）は
`page.tsx`・admin側が引き続き参照する。

## RouteAxisProfile.tsx（選択中ルートの軸別内訳）

`RouteCandidate.axis_difficulties`（axis_id→difficulty 0-100の距離加重平均）を、
`useAxisCatalog().axes`の並び順で横棒グラフ表示する。評価できなかった軸（キー自体が
無い）は表示しない。色は`axisLayers.ts: rampColorForBand`（地図の段階配色と同じ配色系統）
を`bandCount=101`で流用し、0-100の連続値をそのまま色へ変換する。

## RouteList.tsx / ComparisonPanel.tsx

- `RouteList.tsx`: 候補一覧のラベルを評価軸カタログから動的生成する（軸を増やしても
  このファイルを直接編集する必要が無い）。
- `ComparisonPanel.tsx`: 研究モードの実験スロット比較表。物理量（距離・獲得標高等）の
  静的行に加え、`axisLabels`（axis_id→表示名）・`axes`（カタログ由来の並び順）を
  `page.tsx`から受け取り、軸別のdifficulty行を動的生成する。`total_score`（同一
  generate呼び出し内でのみ比較可能な相対値）は実験間比較表には出さない。

## RouteForm.tsx / WindBearingSlider.tsx

- `RouteForm.tsx`: 距離入力・生成ボタン。`RouteMode`（"loop"|"destination"）で周回/
  目的地モードを切り替える。モバイル上部バー向けの`compact`表示を持つ。
- `WindBearingSlider.tsx`: 走行方位（bearing_deg）の指定スライダー。
