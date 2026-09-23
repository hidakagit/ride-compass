# 軸スタジオ・評価軸定義（backend）

## 責務

「評価軸」（道路のEdge/区間ごとに0-100のdifficultyスコアを出す単位、例: 勾配・車の
圧迫感・事故密度）を、`axis_definitions`DBテーブルを唯一の正本として定義・評価・配信する。

評価軸の値は`road_graph_engine.py`から呼ばれる（`domain/evaluation.py:
compute_edge_axis_scores`経由、下記「呼び出し元」参照）。周回ルート生成専用ではない
（地図表示等、他の消費者からも参照される設計）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `axis_definitions.py`・`axis_display.py`・`axis_raw_value.py`・`axis_templates.py`・`registry.py`・`registry_defaults.py` |
| services | `axis_registry_service.py`・`axis_preview_service.py` |
| infrastructure | `axis_definition_models.py`・`axis_definition_repository.py` |
| api | `axis_admin.py`・`axis_catalog.py` |
| scripts | `measure_axis_saturation.py` |

## 分布プレビュー（`services/axis_preview_service.py`）

軸スタジオが折れ点を編集している最中に、**その設定で実データがどう分布するか**を返す。

- 母集団はWay単位（生データのページ単位抽選、`TABLESAMPLE SYSTEM`）で、**延長で
  重み付ける**。本数で数えると短い道が多数を占めて実際に走る距離の感覚と合わない。
  ページ単位の抽選のため地理的な偏りが残りうる点は、分布を「目安」として扱う前提で許容する。
- 材料値はDB側が`MaterialSpec.value_sql`で求める（`RoadGraphRepository.
  sample_way_material_values`）。評価が読むのと同じ式をway粒度のエイリアスへ当てるため、
  材料を増やしてもプレビューだけ取り残されることがない。
- Way単位で値を持たない材料はここに現れない。Edge単位（`road_edges`）にしか無い材料は
  Way単位の事前集計を用意して初めて分布を見られる
  （[静的道路属性・タイル配信](static-road-attributes.md)参照）。
  そのため、母集団の値はルート評価が実際に読むEdge単位の値と粒度が一致しない場合がある。
- 抽選したサンプルは`cachetools.TTLCache`で保持する（初回1秒前後、2回目以降は即座）。
- 返すのは**折れ点を通す前の生値**の分位とヒストグラムで、折れ点の当てはめはfrontendが行う
  （[軸スタジオ管理画面](../frontend/axis-studio.md)「折れ点の効き方を実データで見せる」参照）。
- **ヒストグラムの階級はデータの値域から決める**（0は常に範囲へ含める）。下限を0に固定すると
  生値が負になる軸——`terms`の重みがすべて負の軸（`bicycle_infra_quality`・`night`等）
  ——で全サンプルが階級0へ潰れ、分位が負を示しているのにヒストグラムは正の範囲しか持たない、
  という同一レスポンス内で矛盾した分布になる。`zero_share`は値が**ちょうど0**の延長の割合で、
  負の値は含まない（含めると「下り勾配の道」「開けていない道」まで「ゼロ」として数えられる）。

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `POST /api/admin/axis-definitions/preview-distribution` | Basic認証 | 編集中の`shape`の生値の分布 |
| `GET /api/admin/material-catalog/{material_id}/distribution` | Basic認証 | 材料1件の値の分布（数値材料のみ、それ以外は`available=false`） |


## 飽和の計測（`scripts/measure_axis_saturation.py`）

折れ点が実データの分布と合っていないと、難易度が全区間でほぼ同じ値になる。そうなると
重みをいくら上げてもルートが変わらない——**症状はエラーではなく「重みが効かない」という
無言の形**で出るため、ヘルスチェックにも例外にも現れない。

公開軸ごとに、延長で重み付けた難易度の分位点と、上端（95以上）・下端（5以下）が占める
延長の割合を出す単発スクリプト。母集団と材料の組み立ては分布プレビューと同じ経路を使い、
違いは**折れ点を通した後の難易度**を見る点にある（飽和は折れ点の当て方の問題なので、
生値の分布だけでは判断できない）。

軸の難易度は`domain/axis_definitions.py: evaluate_axes_scalar`で得る。個々の軸へ
`evaluate_axis_scalar`を直接当てると、他の軸を材料にする合成軸（車の圧迫感）が
「材料が欠損」として現れてしまう。

**分布は地域で大きく変わる**。全域の抽選標本では市街地の偏りが平均に埋もれるため、
`--bbox`（`min_lat,min_lon,max_lat,max_lon`）でその地域だけを母集団にできる。bbox指定時は
抽選（`TABLESAMPLE`）を併用しない——表全体のページから抽選するため、狭い範囲を重ねると
当たるページがほとんど残らず、標本が範囲の広さに関係なく数本まで落ちる。
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
| `display_thresholds_override` | list[float]\|None | 色分けしきい値の上書き |
| `display_band_labels_override` | list[str]\|None | 段階ごとの体感ラベルの上書き（例:「強い向かい風」）。設定する場合は`display_thresholds_override`も設定済みで要素数が段階数（しきい値数+1）と一致すること |
| `dedicated_way_value_layer` | bool | 専用のフィーチャー→値配信レイヤーを持つか |
| `dynamic_way_value_needs_time`/`dynamic_way_value_needs_bearing`/`dynamic_way_value_needs_speed` | bool | `dedicated_way_value_layer=True`の軸のみ意味を持つ。`GET /api/region/dynamic-way-values/...`の`at`/`bearing_deg`/`speed_kmh`クエリパラメータ必須判定（[dynamic-way-values.md](dynamic-way-values.md)参照） |

**表示に関するフィールドは、軸idの分岐をコードへ持たないための宣言**である。

- `time_scope`: `time_scoped_weights()`が`active_scopes`に含まれない軸の重みを0にする。
  別の時間帯依存軸（例: 通勤ラッシュ限定）を足すときも、増やすのはこの値だけで
  エンジン側のコードは変わらない。
- `show_map_icon`: 地図上チップから軸を丸ごと除外する。専用レイヤーの有無
  （`display.kind`）とは独立に効くため、kind別の分岐を新設しなくてよい。
  **`show_map_icon=true`のまま専用レイヤーを持たない軸へ、代替の説明文は用意しない**
  ——存在理由が自明でなくなったら`false`にして表示自体を止める。

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
- `MaterialTerm.required`と欠損: `required=True`の材料が欠損すれば軸全体が欠損
  （スカラーNone/配列NaN）。`required=False`の材料の欠損は寄与0として残りの項だけで
  評価する。ただし全termが欠損した場合は、残る項が無く「寄与0の合計＝0」と「観測値が0」を
  区別できないため、`required`の有無によらず軸全体が欠損になる。
- `CategoricalShape`: 単一`material`の値を`mapping`（カテゴリ値→スコア）で引く。
  `evaluate_categorical`は配列入力を`np.searchsorted`の二分探索で解決する（O(要素数×
  log(キー数))、多値categorical材料での高速化）。
- 数値変換の実装は`domain/axis_templates.py: evaluate_breakpoint_linear`/
  `evaluate_categorical`。「合成」（他軸のスコアを次の軸の入力として使う階層構造）は
  独立したプリミティブではなく、連続演算の結合ステップの性質から生じる（`terms`の各
  materialが材料id・他軸のaxis_idのどちらも区別なく指せるため）。

### `PriorityCondition`（0次条件）

`material`の値が`equals`と一致する場合、shape評価をスキップし`value`をそのまま返す
（探索除外のハードフィルタ`domain/hard_filters.py: DEFAULT_HARD_FILTERS`とは別の仕組み）。

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
キー（各軸の`materials`）でメモ化する（件数上限つきの`cachetools.LRUCache`。軸スタジオの
管理APIは呼び出しのたびに新しい`dict`を作るため、上限が無いと軸を編集するたびに鍵が増える。
`refresh_axis_definitions`が
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
        ├──→ road_graph_engine.py
        └──→ axis_catalog.py（GET /api/axis-catalog、実行時・即座に反映）
```

- `AXIS_DEFINITIONS`はPython literalの初期値を持たない（空dictで開始）。DBが唯一の正本。
- `refresh_axis_definitions`はDB読み込み失敗・0行・未知材料/軸参照のいずれかを検出すると
  `AxisDefinitionSyncError`を送出しfail-fastする（安全側フォールバックは持たない、
  main.pyのlifespanはこれを捕捉せずアプリ起動自体を失敗させる）。
- **行データ（軸の新規追加・既存軸の値変更）は`axis_admin.py`経由でしか入らない。**
  スキーマは`axis_definition_models.py`のORM宣言から`create_tables()`が作る。
- **公開済み軸を不変にしているのは、一般ユーザーの保存設定が`axis_id`キーで再現される
  ため**（ルート設定パネルのプリセット・重みは`localStorage`に`axis_id`で残る）。公開後に
  破壊的な変更・削除を許すと、他の利用者の設定を黙って壊す。改良したいときは複製して
  新しい`axis_id`の下書きを作り、そちらを検証して公開する。
- `axis_registry_meta.revision`（DB1行、id=1固定）は書き込み（`upsert`/`delete`）ごとに
  インクリメントされる。`AXIS_DEFINITIONS`自体の無効化には使われていない（`AXIS_
  DEFINITIONS`は`refresh_axis_definitions`が毎回`.clear()`+`.update()`で全面更新するため
  無効化の概念自体が無い）が、`infrastructure/tile_score_matrix_cache.py:
  sync_disk_cache_with_axis_revision`が、アプリ起動時にも必ず1回呼ばれる`refresh_axis_
  definitions`から見て軸定義が実際に変わったかどうかの判定に使う（`AxisRegistryMetaRow`
  docstring参照）。将来のマルチプロセス対応・監査用の記録としても存在する。

### まっさらなDBに軸の行は入らない

`scripts/bootstrap_database.py`が作るのはスキーマ・取込・派生までで、`axis_definitions`の
行は作らない。`refresh_axis_definitions`は0行を`AxisDefinitionSyncError`として扱うため、
**新規環境は軸を1つ以上APIで登録するまでアプリが起動しない**。

テストは`tests/axis_system_fixture.py`を`AXIS_DEFINITIONS`へ流し込む。これが配るのは
軸の**性質**（shapeの種類・必須でない項・時間帯限定・表示の上書き・専用way値配信）で
あって本番の軸ではない。DBの実データとは独立で、DB側の値が変わっても追従しない。

## 地図表示ルールの自動導出（`domain/axis_display.py`）

軸が参照する材料が全てMVTタイルへ焼き込み済みであれば、地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を`axis_display_for()`
が自動導出する。**安全に自動導出できるケースに限定**し、それ以外は`None`（`kind="none"`、
地図に出ない）を返す:

| shapeの形 | 自動導出できるか |
|---|---|
| `CategoricalShape`（真偽値材料1件、またはstr N値材料1件） | できる（隣接中間点をしきい値に） |
| `BreakpointLinearShape`で全termがboolean材料 | できる（重みの全部分和集合の隣接中間点。上限12term） |
| `BreakpointLinearShape`で`preprocess="identity"`かつboolean材料混在なし | できる（breakpointsのx値をそのまま流用） |
| `preprocess="abs"`を含む軸 | **できない**（実装しないと確定済み。方向依存材料[風・勾配]を含む軸は別の制約でも弾かれるため二重に対象外） |
| タイル非依存材料・方向依存材料（`tile_property_direction_dependent`）を含む軸 | できない |
| 他の軸を参照する`MaterialTerm`を含む軸 | 参照先を再帰的に解決できれば可（`_resolve_referenced_axis_tile_input`、car_stressが参照する内部軸が実例）。2段階以上のネストは非対応 |

`axis_display_for(definition)`の優先順位: ①自動導出成功＋`display_thresholds_override`
設定済みなら両方を組み合わせる、②自動導出成功のみなら自動導出のしきい値をそのまま使う、
③自動導出失敗なら`kind="none"`。しきい値を決めるのは`axis_display_for`1本で、
ルート線側の境界（`dynamic_way_values.py: map_value_thresholds`）もそこから導く。

**折れ線が同じスコアへ写す境界は落とす。** 上書きで指定された値も同じ扱いで、軸スタジオで
4つ刻んでも折れ線が3つ目で100へ達していれば段は3つになる。評価が区別できない差に境界を
引くと、色だけが変わって評価は同じという見分けを地図が見せることになり、しかもルート線側は
難易度を塗るためその段を作れない（前後で段の数が食い違う）。

軸スタジオは刻んでいる最中にこの落ちる値を印として出すため、保存前の下書きで同じ判定を問う
（`thresholds_the_map_drops`、`POST /api/admin/axis-definitions/preview-display-thresholds`）。
判定は`axis_display_for`と同じ`_map_band_thresholds`を通し、frontendへ規則を写さない。
入力は段を決めるのに要るもの（`axis_id`・`shape`・`priority_overrides`・しきい値）だけで、
表示名・重みのような下書きの途中で欠けうる項目を揃えさせない——揃えさせると、書きかけの
軸では印が出なくなる。

**暗黙の前提（重要な既知の非対称性）**: 自動導出した表示と評価側の整合性は
`required=False`の材料でのみ厳密に一致する。`required=True`の材料が欠損している場合、
評価側（`evaluate_axis_scalar`）は軸全体を「評価不能（None）」にするが、フロント側の
自動導出expression（`buildAxisRampValueExpression`）はタイルプロパティ欠損を寄与0
（coalesce）として扱う——本来「評価不能」な区間が地図上では「評価済みで良好（緑）」に
誤表示されうる。テストで検証済みの許容された制約であり、実務上は稀（way単位の
事前集計は欠損時0埋めが基本）だが、新規軸でrequired=True材料が実際にタグ欠損
しやすい場合はこの不整合が顕在化しうる。

### 生値の単位（`raw_value_unit`）

`axis_raw_value.py`が、軸の**生値**（折れ点を通す前の`terms`重み付き和）の単位を導出する。
`BreakpointLinearShape`で、重み0以外の全termが下の条件をすべて満たすときだけ単位を返す。
それ以外は`None`:

| 返さない場合 | 理由 |
|---|---|
| `CategoricalShape` | 折れ点を通す前の和という概念が無い |
| 単位を持たない材料（真偽値・カテゴリ・無次元） | 添える単位が無い |
| 異なる単位の混在（内部軸の合成） | 和が物理量にならない |
| 重みが1以外の項を含む（負の重みを含む） | 生値は`Σ(材料値 × weight)`なので、1以外の重みは材料の値をスケールし直した量になり、材料の単位では読めない（重み付きの「1kmあたり1.5回として数えた踏切」を含む和は、実際の回/kmではない）。本番の停止密度がこの形で`None`になる |
| 2項以上で`additive`でない材料を含む | **単位が揃っていても和の意味は保証されない**。%・km/h・倍率のような割合・率は、母数の違うものを足しても何も表さない（`樹木% + 建物%`のような被覆率どうしの和が実例）。足せるのは回・件・個のような個数と、それを同じ距離で割った密度だけ（`MaterialSpec.additive`）。項が1つなら和ではないためこの条件は課さない |

`GET /api/axis-catalog`が`raw_value_unit`として配信し、
[ルート設定・ルート結果（frontend）](../frontend/route-settings-and-results.md)が
得点の隣へ生値を添えるのに使う。単位の無い数字は読み手が意味を取れないため出さない。
地図のramp軸の凡例も同じ単位を段階ラベルへ添える——rampの段の境界は折れ点のx値
（＝生値の目盛り）で、単位が定まる軸では生値と同じ量を塗っている（`axis_display.py`）。

### 材料単位への分解（`material_breakdown`）

上の表で`None`になる軸は、代わりに`axis_material_shares`が軸を**材料まで分解**し、
材料ごとの絶対量を並べられるようにする（同じ`axis_raw_value.py`）。軸参照は葉の材料まで
再帰的に辿り、途中の軸の得点は内訳に含めない。並びは各階層で正規化した重みの積の降順で、
重み0の材料は含めない。参照材料が1件へ分解される軸は分解しない（軸単位の生値で足りる
うえ、`shape.preprocess`が材料単位では効かない）。導出の根拠と、値の運搬・表示の詳細は
[評価・スコアリング](evaluation-scoring.md)「ルート単位の集約」節を参照。

`GET /api/axis-catalog`が`material_breakdown`として、材料id・表示名・型・単位・
正規化重みの並びで配信する（フロントは材料の対応表も並べ替えも持たない）。

## 一次属性レジストリ（`domain/registry.py`・`registry_defaults.py`、別系統）

**`AXIS_DEFINITIONS`とは別の、一次属性の語彙だけを持つレジストリ**。
`register_primary_attribute()`が`_PRIMARY_ATTRIBUTES`（モジュールレベルdict）へ登録し、
同じ`attr_id`の二重登録を拒む。軸は登録しない——材料が2つの軸へ跨がらないことの検査は
`AXIS_DEFINITIONS`側の`check_material_exclusivity`/`AxisMaterialConflictError`（軸の書き込み時）
だけが持つ。

**暗黙の前提（最重要）**: `register_defaults()`は**FastAPIアプリの起動時には一切呼ばれない**。
実際の呼び出し元は`scripts/export_openapi.py`（ビルド時、一次属性の名前を
`primaryAttributes.ts`へ書き出す）とテストのみ。**軸カタログそのものにビルド時の写しは
無い**——frontendは`GET /api/axis-catalog`が返したものだけを使う
（[設計原則](../../architecture/design-principles.md)構造仕様9）。ビルド時には
`AXIS_DEFINITIONS`が空（DBから埋めるのは実行時の`refresh_axis_definitions`だけ）なので、
ビルド時に軸を見る検査は置けない。

## API

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/admin/axis-definitions`・`/{axis_id}` | Basic認証必須 | 一覧・単体取得。レスポンスは`display`（`axis_display_for()`の計算結果）も含む——下書き軸の自己診断（地図表示データがまだ用意されていないか）のため |
| `POST /api/admin/axis-definitions` | Basic認証必須 | 作成 |
| `PUT /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 更新（公開済みは原則拒否。ただし表示専用フィールド[`icon_id`/`chip_label`/`panel_hint`/`show_map_icon`/`display_thresholds_override`/`display_band_labels_override`]のみの差分は例外的に許可） |
| `DELETE /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 削除 |
| `POST /api/admin/axis-definitions/{axis_id}/unpublish` | Basic認証必須 | 公開済み軸を下書きへ戻す（`is_published`以外は変更しない） |
| `POST /api/admin/axis-definitions/preview-display-thresholds` | Basic認証必須 | 編集中の軸で、上書きしたしきい値のうち地図が段にしないもの（DBを読まない） |
| `GET /api/axis-catalog` | 不要（公開） | `is_published=True`の軸のみ返す。`AxisDefinition`のほぼ全フィールドをそのまま返す |

`GET /api/axis-catalog`の`material_runtime_scales`（実行時にしか決まらないスケール係数）
のみ、リクエストごとにDBを直接見る例外（現状`accident_count_per_km_year`のみ対象）。

### 軸そのものの不変条件（`domain/axis_definitions.py`のモデル）

**軸が入ってくる口は2つある**——管理API（`AxisDefinitionPayload`）と、起動時にDBの行から
組み立てる経路（`infrastructure/axis_definition_repository.py`）である。後者に検証の機会は
他に無いため、軸そのものの不変条件はモデル側が持ち、どちらの口から来ても同じように弾く
（`AxisDefinitionPayload`は`AxisDefinition`を継承するので、APIはこれらを422で返す）。

- `shape.breakpoints`はx昇順（`evaluate_breakpoint_linear`の`np.interp`が前提とする
  不変条件。崩れると例外もログも出ないまま全区間の得点が誤る）。
- `CategoricalShape.mapping`は空でないこと（引ける値が無い対応表はその軸を恒久的に欠損にする）。
- `display_thresholds_override`は設定する場合、空でなく厳密な昇順。
- `display_band_labels_override`は設定する場合、`display_thresholds_override`も
  設定済みで、要素数が段階数（`len(display_thresholds_override)+1`）と一致すること。
- `axis_id`・`label`・材料idは空文字でないこと、`default_weight`は非負、`chip_label`は
  1〜4文字。重み・係数にNaN・無限大を許さない（軸の得点も合成difficultyも黙ってNaNになり、
  欠損と区別できなくなるため）。

### 書き込み時のバリデーション（`AxisDefinitionPayload`）

軸の外側の状態（材料カタログ・既存の軸・配信実装）に照らすものだけがこちら側にある。

- `chip_label`未設定時は`label`自体が4文字以下であること——未設定だと`label`がそのまま
  地図チップへ出るため。`label`の長さは軸そのものの不変条件ではない（地図チップへ出ない
  内部軸・`show_map_icon=false`の軸にも課すことになる）ので、新規作成する側へ要求する。
- shapeが参照する材料・軸参照が既知であること、材料のdtype（numeric/boolean/
  categorical）がshape種別の前提と一致すること（`CategoricalShape`は
  boolean/categorical材料、`BreakpointLinearShape`はnumeric/boolean材料）。
  `CategoricalShape`はさらに`mapping`のキー型（bool/str）が材料のdtypeと一致することも
  検証する。
- `priority_overrides[*].material`も既知材料/軸参照であること（未知の場合、0次条件が
  無警告のまま一切発動しなくなるため）。
- リクエスト時に評価される動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）と静的材料を同じ軸で
  混在させないこと。動的軸の再評価経路（`domain/dynamic_materials.py:
  evaluate_dynamic_axis_arrays`）へ渡るのは「タイル単位でキャッシュ済みの公開軸スコア」と
  「動的材料」だけで、静的材料の配列は渡らない——混在させた軸は`evaluate_axis_array`が
  KeyErrorになり`/api/routes/generate`ごと失敗する。静的材料が必要なら別の軸へ切り出して
  軸参照で合成する。
  参照材料の導出は`AxisDefinition.materials`と同じ`referenced_materials`
  （`domain/axis_definitions.py`）を使い、**shapeの種別を問わず`priority_overrides`が
  参照する材料も含める**。動的軸かどうかを判定する`_axes_depending_on_materials`が
  同じ導出を根拠にしているため、検証側だけ`shape.terms`に絞ると素通りした軸が実行時に落ちる。
- `dedicated_way_value_layer`を立てられるのは、フィーチャー→値配信の実装
  （`api/dependencies.py`の`_DEDICATED_WAY_VALUE_SERVICE_FACTORIES`）が登録済みの
  `axis_id`だけ。宣言だけでは配信できる値が無い（配信側は実装の無い材料を未知の
  `material_id`と同じく404で返す）。

### 書き込み時のガード（`AxisRegistryAdminService`）

| 操作 | ガード |
|---|---|
| create | axis_idが既存材料idと衝突していないか（衝突すると評価時に材料値を黙って上書きする）。材料の排他帰属。内部軸の誤公開防止。循環参照検出 |
| update | 公開済みは原則拒否（`check_publish_immutability`）。ただし`candidate`引数を渡すと、表示専用フィールドのみの差分（`is_cosmetic_only_update`）なら公開済みでも許可する。材料の排他帰属。内部軸の誤公開防止。循環参照検出 |
| delete | 最後の1軸は削除不可（0行になると直後の`refresh_axis_definitions`が起動・反映に失敗する）。公開済みは拒否 |
| unpublish | `is_published`のみを変更する専用操作（`update()`は使えない、公開済みは拒否されるため） |

いずれの書き込みも「DB commit → `refresh_axis_definitions`呼び出し」で完結する
（1操作=1トランザクション）。

create/update/delete/unpublishはいずれも冒頭で`AxisDefinitionRepository.
acquire_write_lock()`（PostgreSQLのトランザクションスコープadvisory lock）を呼び、
「読み取り→Python側で検証→書き込み」の一連を直列化する。このロックが無いと、
2つのcreate()が同時に走った場合に互いのsort_orderや材料排他帰属チェックが相手の
変更を見ないまま古いスナップショットへ基づいて計算されるため、書き込み後にsort_order
衝突・材料の二重帰属というTOCTOUレースが起こりうる。asyncio.Lock（同一プロセス内のみ
有効）ではなくDBレベルのロックにしているのは、将来複数ワーカー化する場合にも機能させる
ため。

## 軸idを名指しするコードを残さない

軸は軸スタジオから増減するため、`axis_id`を条件分岐に使うコードがあると、その軸を消した
瞬間に壊れる。表示の振る舞い（地図に出すか・符号付きで塗るか・時間帯で効くか）は
すべて`AxisDefinition`のフィールドから導く。現時点で軸idを名指しする削除ガードは持たない。
