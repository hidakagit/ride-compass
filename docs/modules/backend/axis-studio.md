# 軸スタジオ・評価軸定義（backend）

## 責務

「評価軸」（道路のEdge/区間ごとに0-100のdifficultyスコアを出す単位、例: 勾配・車の
圧迫感・事故密度）を、`axis_definitions`DBテーブルを唯一の正本として定義・評価・配信する。

評価軸の値は`road_graph_engine.py`・`openrouteservice_engine.py`の両方から呼ばれる
（`domain/evaluation.py: compute_edge_axis_scores`経由、下記「呼び出し元」参照）。周回
ルート生成専用ではない。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `axis_definitions.py`・`axis_display.py`・`axis_templates.py`・`registry.py`・`registry_defaults.py` |
| services | `axis_registry_service.py` |
| infrastructure | `axis_definition_models.py`・`axis_definition_repository.py`・`axis_definitions_snapshot.py` |
| api | `axis_admin.py`・`axis_catalog.py` |

## データモデル（`domain/axis_definitions.py`）

### `AxisDefinition`（1軸の宣言、`frozen=True`）

| フィールド | 型 | 意味 |
|---|---|---|
| `axis_id` | str | 軸の識別子 |
| `shape` | `AxisShape` | 評価式（下記） |
| `default_weight` | float | APIで上書きされない場合の既定合成重み |
| `label`/`description` | str | 表示名・説明 |
| `category` | "観測"\|"推定"\|"動的" | 分類 |
| `is_published` | bool | true=一般公開、false=下書き（軸スタジオのみで見える） |
| `priority_overrides` | list[PriorityCondition] | 0次条件（下記） |
| `icon_id`/`chip_label`/`panel_hint`/`show_map_icon` | | 地図チップ表示要素 |
| `time_scope` | "always"\|"night_only" | 特定時間帯のみ重みを持つか |
| `supports_route_coloring` | bool | ルート結果色分けの選択肢に使えるか |
| `display_thresholds_override` | list[float]\|None | 色分けしきい値の上書き |
| `dedicated_way_value_layer` | bool | 専用way_id→値配信レイヤーを持つか |

### `AxisShape`（評価式、2プリミティブ）

```
[BreakpointLinearShape]

  材料1 ─┐
  材料2 ─┼─ weight付き線形結合 ─→ preprocess(identity/abs) ─→ breakpoints折れ線補間 ─→ difficulty(0-100)
  材料N ─┘

[CategoricalShape]

  材料(1個) ─→ mapping（カテゴリ値→スコア） ─→ difficulty(0-100)
```

- `BreakpointLinearShape`: `terms`（`MaterialTerm`のリスト、各々`material`・`weight`・
  `required`を持つ）を線形結合 → `preprocess`（"identity"または"abs"）→
  `breakpoints`（折れ線、両端クランプ）。
- `CategoricalShape`: 単一`material`の値を`mapping`（カテゴリ値→スコア）で引く。
- 数値変換の実装は`domain/axis_templates.py: evaluate_breakpoint_linear`/
  `evaluate_categorical`。

### `PriorityCondition`（0次条件）

`material`の値が`equals`と一致する場合、shape評価をスキップし`value`をそのまま返す
（探索除外のハードフィルタ`domain/evaluation.py: DEFAULT_HARD_FILTERS`とは別の仕組み）。

### 軸の階層

`MaterialTerm.material`/`CategoricalShape.material`は材料idだけでなく他の軸の`axis_id`も
指せる。評価済みの軸のdifficultyが材料と同じ扱いで混ぜ込まれるため、非公開の内部軸
（`is_published=False`）を合成した公開軸を作れる。

## 評価パイプライン

| 関数 | 用途 |
|---|---|
| `evaluate_axis_scalar(definition, materials)` | 1Edge分。欠損はNone |
| `evaluate_axis_array(definition, materials)` | numpy配列版。欠損はNaN、ベクトル化経路用 |
| `evaluate_axes_scalar(materials)` | 全軸を依存順（`topological_axis_order`、内部軸→公開軸）で評価し、公開軸のみのdifficulty辞書と全軸を含むmaterials辞書を返す |

## ライフサイクル

```
  axis_admin.py（create / update / delete / unpublish）
        │ 書き込み
        ▼
  axis_definitions DBテーブル（唯一の正本）
        │ 読み込み
        ▼
  refresh_axis_definitions()（axis_registry_service.py）
    起動タイミング: (1) main.py起動時（lifespan）に1回
                    (2) axis_admin.py書き込み成功直後に1回
        │ .clear() + .update()
        ▼
  AXIS_DEFINITIONS（モジュールレベルdict）
        │
        ├──→ road_graph_engine.py / openrouteservice_engine.py
        └──→ axis_catalog.py（GET /api/axis-catalog）
```

- `AXIS_DEFINITIONS`はPython literalの初期値を持たない（空dictで開始）。DBが唯一の正本。
- `refresh_axis_definitions`はDB未接続・0行・未知材料/軸参照のいずれかを検出すると
  `AxisDefinitionSyncError`を送出しfail-fastする（安全側フォールバックは持たない）。
- **行データ（軸の新規追加・既存軸の値変更）は`axis_admin.py`経由で行う。
  `backend/migrations/`はテーブル構造（DDL）のみを持つ**（`0027_axis_definitions_
  dedicated_way_value_layer.sql`で確認済み）。

## API

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/admin/axis-definitions`・`/{axis_id}` | Basic認証必須 | 一覧・単体取得 |
| `POST /api/admin/axis-definitions` | Basic認証必須 | 作成 |
| `PUT /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 更新（公開済みは`AxisPublishedImmutableError`で拒否） |
| `DELETE /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 削除 |
| `POST /api/admin/axis-definitions/{axis_id}/unpublish` | Basic認証必須 | 公開済み軸を下書きへ戻す（`is_published`以外は変更しない） |
| `GET /api/axis-catalog` | 不要（公開） | `is_published=True`の軸のみ返す。`AxisDefinition`のほぼ全フィールド（`shape`・`display_thresholds_override`・`dedicated_way_value_layer`含む）をそのまま返す |

`GET /api/axis-catalog`の`material_runtime_scales`（実行時にしか決まらないスケール係数）
のみ、リクエストごとにDBを直接見る例外（現状`accident_count_per_km_year`のみ対象）。

## 不変条件・ガード

- **公開済み不変**（`check_publish_immutability`）: 公開済み軸の更新・削除を拒否。
  改良は複製（新規axis_idで下書き作成）してから公開する。
- **材料の排他帰属**（`check_material_exclusivity`）: 新規/更新軸の材料が既存の別軸と
  重複していないか検査（`MATERIAL_CATALOG`に実在する材料のみが対象、軸参照は対象外）。
- **内部軸の非公開維持**（`check_internal_axis_not_published`）: 他の軸から参照されている
  内部軸を公開しようとすると拒否。
- **循環参照検出**（`topological_axis_order`）: 軸間の参照循環を検出
  （`AxisDependencyCycleError`）。
