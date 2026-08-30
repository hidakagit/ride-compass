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
  `breakpoints`（折れ線、両端クランプ）。`evaluate_breakpoint_linear`は`np.interp`実装
  （x範囲外は両端値へクランプ、NaN混入時は明示的にNaNへ戻す後処理が必要——`np.interp`は
  NaNを正しく伝播しないため）。
- `CategoricalShape`: 単一`material`の値を`mapping`（カテゴリ値→スコア）で引く。
  `evaluate_categorical`は配列入力を`np.searchsorted`の二分探索で解決する（O(要素数×
  log(キー数))、多値categorical材料での高速化）。
- 数値変換の実装は`domain/axis_templates.py: evaluate_breakpoint_linear`/
  `evaluate_categorical`。「合成」（他軸のスコアを次の軸の入力として使う階層構造）は
  独立したプリミティブではなく、連続演算の結合ステップの性質から生じる（`terms`の各
  materialが材料id・他軸のaxis_idのどちらも区別なく指せるため）。

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

`topological_axis_order`は深さ優先探索でトポロジカルソートし、結果を内容ベースの
キー（各軸の`materials`）でメモ化する（FIFO上限64件、`refresh_axis_definitions`が
同一dictオブジェクトを`.clear()`+`.update()`で差し替えるため、オブジェクトidベースの
キーは使えない）。循環参照は`AxisDependencyCycleError`を送出しキャッシュしない。

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
        └──→ axis_catalog.py（GET /api/axis-catalog、実行時・即座に反映）
```

- `AXIS_DEFINITIONS`はPython literalの初期値を持たない（空dictで開始）。DBが唯一の正本。
- `refresh_axis_definitions`はDB読み込み失敗・0行・未知材料/軸参照のいずれかを検出すると
  `AxisDefinitionSyncError`を送出しfail-fastする（安全側フォールバックは持たない、
  main.pyのlifespanはこれを捕捉せずアプリ起動自体を失敗させる）。
- **行データ（軸の新規追加・既存軸の値変更）は`axis_admin.py`経由で行う。
  `backend/migrations/`はテーブル構造（DDL）のみを持つ**（`0027_axis_definitions_
  dedicated_way_value_layer.sql`で確認済み。0014〜0022は行データ入りの過去migrationだが
  書き換えない）。
- `axis_registry_meta.revision`（DB1行）は書き込みごとにインクリメントされるが、
  **現時点ではプロセス内キャッシュの無効化には使われていない**（`AxisDefinitionRow`
  docstring参照）。将来のマルチプロセス対応・監査用の記録として存在するのみ。

### fresh bootstrap（CI・新規環境）専用の別経路

`infrastructure/axis_definitions_snapshot.py`が`backend/fixtures/
axis_definitions_snapshot.json`（`dump_axis_definitions_snapshot.py`で現在のDBから
ダンプした手動更新のスナップショット）を読み書きする。`load_axis_definitions_snapshot`は
テーブルを**無条件に**丸ごと空にしてから投入する——`bootstrap_ci_db.py`・
`bootstrap_fresh_db.py`という専用スクリプトからのみ呼ぶ設計で、通常のアプリ起動経路
（`refresh_axis_definitions`）や稼働中DBに対して繰り返し実行される`import_pbf.py`等
からは呼ばない（誤って本番の生きた軸データをスナップショットで上書きする事故を防ぐ）。

**暗黙の前提**: スナップショットの更新は完全手動（本番/devでAPI経由の軸変更を行った後、
`dump_axis_definitions_snapshot.py`を都度手動実行する）。自動化されていないため、
axis_admin API経由の変更後にこのダンプを忘れると、以後のfresh bootstrap環境（CI・
新規開発環境・disaster recovery）が古い軸定義で構築される。

## 地図表示ルールの自動導出（`domain/axis_display.py`）

軸が参照する材料が全てMVTタイルへ焼き込み済みであれば、地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を`derive_ramp_inputs()`
が自動導出する。**安全に自動導出できるケースに限定**し、それ以外は`None`（`kind="none"`、
地図に出ない）を返す:

| shapeの形 | 自動導出できるか |
|---|---|
| `CategoricalShape`（真偽値材料1件、またはstr N値材料1件） | できる（隣接中間点をしきい値に） |
| `BreakpointLinearShape`で全termがboolean材料 | できる（重みの全部分和集合の隣接中間点。上限12term） |
| `BreakpointLinearShape`で`preprocess="identity"`かつboolean材料混在なし | できる（breakpointsのx値をそのまま流用） |
| `preprocess="abs"`を含む軸 | **できない**（実装しないと確定済み。方向依存材料[風・勾配]を含む軸は別の制約でも弾かれるため二重に対象外） |
| タイル非依存材料・方向依存材料（`tile_property_direction_dependent`）を含む軸 | できない |
| 他の軸を参照する`MaterialTerm`を含む軸 | 参照先を再帰的に解決できれば可（`_resolve_referenced_axis_tile_input`、car_stressの5内部軸が実例）。2段階以上のネストは非対応 |

`axis_display_for(definition)`の優先順位: ①自動導出成功＋`display_thresholds_override`
設定済みなら両方を組み合わせる、②自動導出成功のみなら自動導出のしきい値をそのまま使う、
③自動導出失敗なら`kind="none"`。

**暗黙の前提（重要な既知の非対称性）**: `derive_ramp_inputs`の評価側整合性は
`required=False`の材料でのみ厳密に一致する。`required=True`の材料が欠損している場合、
評価側（`evaluate_axis_scalar`）は軸全体を「評価不能（None）」にするが、フロント側の
自動導出expression（`buildAxisRampValueExpression`）はタイルプロパティ欠損を寄与0
（coalesce）として扱う——本来「評価不能」な区間が地図上では「評価済みで良好（緑）」に
誤表示されうる。テストで検証済みの許容された制約であり、実務上は稀（way単位の
事前集計は欠損時0埋めが基本）だが、新規軸でrequired=True材料が実際にタグ欠損
しやすい場合はこの不整合が顕在化しうる。

## 一次属性・二次軸レジストリ（`domain/registry.py`・`registry_defaults.py`、別系統）

**`AXIS_DEFINITIONS`とは別の、並行するレジストリ機構**。`register_axis()`/
`register_primary_attribute()`が`_AXES`/`_PRIMARY_ATTRIBUTES`（モジュールレベルdict、
`AXIS_DEFINITIONS`とは別オブジェクト）へ登録し、独自の排他制約チェック
（`AxisInputConflictError`、`AXIS_DEFINITIONS`側の`check_material_exclusivity`/
`AxisMaterialConflictError`とは別実装）を持つ。

**暗黙の前提（最重要）**: `register_defaults()`は**FastAPIアプリの起動時には一切呼ばれない**。
実際の呼び出し元は`scripts/export_openapi.py`（ビルド時、`axis-catalog.json`等の生成物を
書き出すスクリプト）とテストのみ。つまり:

```
【実行時】  axis_admin.py書き込み → AXIS_DEFINITIONS即座に更新 → GET /api/axis-catalog に即反映
【ビルド時】export_openapi.py実行時点のAXIS_DEFINITIONS → axis-catalog.json（静的生成物）に焼き込み
             （以後、次のビルド/デプロイまで変化しない）
```

frontendの静的フォールバック（[軸スタジオ管理画面（frontend）](../frontend/axis-studio.md)・
[地図: 軸・ルート色分け](../frontend/map-axis-coloring.md)の`RAMP_AXES`・
`DEDICATED_WAY_VALUE_LAYER_IDS`等）は、この`axis-catalog.json`（ビルド時スナップショット）
を経由するため、**軸スタジオでの変更は次の再デプロイまでこれらの静的値には反映されない**
（`GET /api/axis-catalog`という実行時APIには即座に反映されるため、実行時フェッチが完了
すればアプリ全体としては最終的に正しい状態になるが、フェッチ完了までの間・フェッチ失敗時は
古い静的値のまま表示される）。

`_register_axes()`（`registry_defaults.py`）は`AXIS_DEFINITIONS`を走査して公開軸のみを
登録する（特定のaxis_idを名指しした条件分岐は持たない）。`inputs`・
`display`は`primary_attribute_ids_for()`・`axis_display_for()`（実行時APIと同一の純粋
関数）から導出するため、ビルド時静的生成物と実行時APIの計算ロジック自体は分岐しない
（分岐するのは「いつのAXIS_DEFINITIONSを見るか」というタイミングのみ）。

## API

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/admin/axis-definitions`・`/{axis_id}` | Basic認証必須 | 一覧・単体取得。レスポンスは`display`（`axis_display_for()`の計算結果）も含む——下書き軸の自己診断（地図表示データがまだ用意されていないか）のため |
| `POST /api/admin/axis-definitions` | Basic認証必須 | 作成 |
| `PUT /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 更新（公開済みは拒否） |
| `DELETE /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 削除 |
| `POST /api/admin/axis-definitions/{axis_id}/unpublish` | Basic認証必須 | 公開済み軸を下書きへ戻す（`is_published`以外は変更しない） |
| `GET /api/axis-catalog` | 不要（公開） | `is_published=True`の軸のみ返す。`AxisDefinition`のほぼ全フィールドをそのまま返す |

`GET /api/axis-catalog`の`material_runtime_scales`（実行時にしか決まらないスケール係数）
のみ、リクエストごとにDBを直接見る例外（現状`accident_count_per_km_year`のみ対象）。

### 書き込み時のバリデーション（`AxisDefinitionPayload`）

- `chip_label`は4文字以下（未設定時は`label`自体が4文字以下であることを要求）——
  地図チップが固定サイズのタイルのため。
- `display_thresholds_override`は設定する場合、空でなく厳密な昇順。
- `shape.breakpoints`はx昇順（`evaluate_breakpoint_linear`の`np.interp`が前提とする
  不変条件）。
- shapeが参照する材料・軸参照が既知であること、材料のdtype（numeric/boolean/
  categorical）がshape種別の前提と一致すること（`CategoricalShape`は
  boolean/categorical材料、`BreakpointLinearShape`はnumeric/boolean材料）。
  `CategoricalShape`はさらに`mapping`のキー型（bool/str）が材料のdtypeと一致することも
  検証する。
- `priority_overrides[*].material`も既知材料/軸参照であること（未知の場合、0次条件が
  無警告のまま一切発動しないバグの再発防止）。

### 書き込み時のガード（`AxisRegistryAdminService`）

| 操作 | ガード |
|---|---|
| create | axis_idが既存材料idと衝突していないか（衝突すると評価時に材料値を黙って上書きする）。材料の排他帰属。内部軸の誤公開防止。循環参照検出 |
| update | 公開済みは拒否（`check_publish_immutability`）。材料の排他帰属。内部軸の誤公開防止。循環参照検出 |
| delete | 最後の1軸は削除不可。`_CODE_COUPLED_AXIS_ID`（下記）に該当する軸は削除不可。公開済みは拒否 |
| unpublish | `is_published`のみを変更する専用操作（`update()`は使えない、公開済みは拒否されるため） |

いずれの書き込みも「DB commit → `refresh_axis_definitions`呼び出し」で完結する
（1操作=1トランザクション）。

## 既知の軸idハードコード（`_CODE_COUPLED_AXIS_IDS`）

`services/axis_registry_service.py`の`frozenset[str] = frozenset({"car_stress", "gradient"})`。
削除すると壊れるコードが存在する軸のリストで、`is_published`の状態に関わらず削除を拒否する
安全弁。

- `car_stress`: `car_stress_display_level()`（`axis_definitions.py`）が
  `AXIS_DEFINITIONS["car_stress"]`を直接参照する。
- `gradient`: `domain/dynamic_way_values.py: DYNAMIC_WAY_VALUE_MATERIALS`が`"gradient"`を
  辞書キーとして直接宣言する。
