# 軸スタジオ・評価軸定義（backend）

## 責務

「評価軸」（道路のEdge/区間ごとに0-100のdifficultyスコアを出す単位、例: 勾配・事故密度）を、
`axis_definitions`DBテーブルを唯一の正本として定義・評価・配信する。

評価軸の値はルート探索が区間の材料から求める（`domain/evaluation.py`が全軸を配列で
まとめて評価する。[評価・スコアリング](evaluation-scoring.md)参照）。周回ルート生成専用ではない
（地図表示等、他の消費者からも参照される設計）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `axis_definitions.py`・`axis_display.py`・`map_paint.py`（地図が軸について塗るもの）・`axis_raw_value.py`・`axis_templates.py`・`registry.py`・`primary_attributes.py`（一次属性の語彙の宣言）・`value_distribution.py`（延長で重み付けた分位点とヒストグラム。分布の口の応答の型） |
| services | `axis_registry_service.py`・`axis_preview_service.py` |
| infrastructure | `axis_definition_models.py`・`axis_definition_repository.py` |
| api | `axis_admin.py`・`axis_catalog.py` |
| scripts | `measure_axis_saturation.py`・`axis_apply.py` |

## 分布プレビュー・材料の値の一覧（`services/axis_preview_service.py`・`domain/value_distribution.py`）

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
  という同一レスポンス内で矛盾した分布になる。
- 材料の分布は、階級を持たず分位と`zero_share`だけを返す（材料選択行の1行表示が読むのはこの2つだけ）。`zero_share`は
  値が**ちょうど0**の延長の割合で、負の値は含まない（含めると「下り勾配の道」まで「ゼロ」として数えられる）。

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `POST /api/admin/axis-definitions/preview-distribution` | Basic認証 | 編集中の`shape`の生値の分布 |
| `GET /api/admin/material-catalog/{material_id}/distribution` | Basic認証 | 材料1件の値の分位と`zero_share`（数値材料のみ、それ以外は`available=false`） |
| `GET /api/admin/material-catalog/{material_id}/values` | Basic認証 | 材料1件のDBに実際にある値の一覧（`AxisPreviewService.material_values`。[評価・スコアリング](evaluation-scoring.md)の材料カタログのAPI） |

どれも実データを全体から読むため、`AxisPreviewService`はルート生成用の長い`command_timeout`の
セッションで組む（`api/dependencies.py: get_axis_preview_service`）。値の一覧は索引の効かない
`SELECT DISTINCT`で、タイル配信用の短い上限では最後まで走らない。


## 飽和の計測（`scripts/measure_axis_saturation.py`）

折れ点が実データの分布と合っていないと、難易度が全区間でほぼ同じ値になる。そうなると
重みをいくら上げてもルートが変わらない——**症状はエラーではなく「重みが効かない」という
無言の形**で出るため、ヘルスチェックにも例外にも現れない。

公開軸ごとに、延長で重み付けた難易度の分位点と、上端（95以上）・下端（5以下）が占める
延長の割合を出す単発スクリプト。母集団と材料の組み立ては分布プレビューと同じ経路を使い、
違いは**折れ点を通した後の難易度**を見る点にある（飽和は折れ点の当て方の問題なので、
生値の分布だけでは判断できない）。

**張り付いた軸は原因で2つに分けて出す。** 張り付いた側（上端・下端）の延長を、得点へ写す前の値
（折れ点の軸は生値、対応表の軸は引く材料の値。`domain/axis_definitions.py: evaluate_axes_inputs`）ごとにまとめ、
最も長い1つの値だけで張り付きの基準を超えるなら「1つの値に集まっている」として、「折れ点が分布と合っていない
可能性」と別に出す。同じ値の道はどの折れ点でも同じ難易度になるので、折れ点を動かしても塊の位置が変わるだけで
散らない（例: 自転車インフラの無い道がすべて同じ生値0を持つ軸）。
全延長のうち最多の1つの値が占める割合も軸ごとに出す。上端・下端の基準は端に寄った塊しか拾わないので、
中ほどの1つの値に大半が集まった軸（どの道も同じ難易度で重みが効かない）はこの列で見る。

軸の難易度は`domain/axis_definitions.py: evaluate_axes_values`で標本の全wayぶんをまとめて得る。個々の軸へ
`evaluate_axis_values`を直接当てると、他の軸を材料にする合成軸が
「材料が欠損」として現れてしまう。

**分布は地域で大きく変わる**。全域の抽選標本では市街地の偏りが平均に埋もれるため、
`--bbox`（`min_lat,min_lon,max_lat,max_lon`）でその地域だけを母集団にできる。bbox指定時は
抽選（`TABLESAMPLE`）を併用しない——表全体のページから抽選するため、狭い範囲を重ねると
当たるページがほとんど残らず、標本が範囲の広さに関係なく数本まで落ちる。

本番へは`scripts/run_probe.py`で当てる（接続先は`--database-url`か、その道具が渡す環境変数から読み、無ければ設定値）。
軸の定義の正本は本番DBなので、コードの変更で難易度がどう動くかは、同じ`--bbox`で変更の前後を本番に当てて比べる
（抽選は回ごとに違う標本を引くため、前後の比較には使わない）。

## 軸の定義をファイルから本番へ入れる（`scripts/axis_apply.py`）

軸スタジオの画面を通さずに、軸1本の定義のJSON（管理APIの単体取得と同じ項目）を本番の管理APIへ入れる手元の道具。
書く口は管理APIだけで、DBへ直接は書かない（書き込みのガードと`AXIS_DEFINITIONS`の差し替えを画面と同じく通す）。

- **既定は差の表示だけ**。今の定義は管理APIの単体取得から読む——公開の軸カタログは下書きの軸・0次条件・時間帯を持たず、
  体感ラベルも地図の段へ引き直した値なので、差の「前」には使えない。差は入れ子（`shape`等）の葉の項目ごとに「前 → 後」で出す。
- 書く操作は今の状態から決まる（無ければ追加、下書きなら更新1回、公開済みなら公開の取り消し→更新。削除は公開済みなら
  取り消してから）。公開済みの軸は更新も削除も拒まれる（上の「書き込み時のガード」）ため、取り消しを挟む。
- **書くのは差を出したときの指紋を渡したときだけ**。指紋は今の定義と書く定義から作るので、差を見てから書くまでに本番が
  変わっていれば一致せず、何も書かない。
- 取り消しの後の段で失敗したら、元の定義へ戻す（戻せなければ元の定義を出して止まる）。書いた後は、管理APIの単体取得が
  書いた定義と一致することと、軸カタログに公開なら同じ内容で載り・下書きか削除なら載らないことを確かめる。
  軸カタログで確かめられるのは、backendが1プロセスで動き、書いたプロセスが配るから（`single_process.py`）。
- 宛先と認証情報は`backend/.env.oracle.local`の`BACKEND_ORIGIN`・`ADMIN_BASIC_AUTH_USERNAME`・`ADMIN_BASIC_AUTH_PASSWORD`
  から読む（`_prod_env.py`）。引数に取らず、出力にも出さない。

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
| `icon_id` | str\|None | ルート設定・ルート結果の評価の内訳で名前に添えるアイコン（未設定は汎用のアイコン） |
| `time_scope` | "always"\|"night_only" | 特定時間帯のみ重みを持つか |
| `display_thresholds_override` | list[float]\|None | 色分けしきい値の上書き |
| `display_band_labels_override` | list[str]\|None | 段階ごとの体感ラベルの上書き（例:「強い向かい風」）。設定する場合は`display_thresholds_override`も設定済みで要素数が段階数（しきい値数+1）と一致すること |
| `dedicated_way_value_layer` | bool | ルート未確定時の地図がこの軸を配信の値で塗るか（配信はどの公開軸の値も返す。[dynamic-way-values.md](dynamic-way-values.md)） |

**表示に関するフィールドは、軸idの分岐をコードへ持たないための宣言**である。

- `time_scope`: `time_scoped_weights()`が`active_scopes`に含まれない軸の重みを0にする。
  別の時間帯依存軸（例: 通勤ラッシュ限定）を足すときも、増やすのはこの値だけで
  エンジン側のコードは変わらない。

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
  （Pythonの値の入口はNone、配列はNaN）。`required=False`の材料の欠損は寄与0として残りの項だけで
  評価する。ただし全termが欠損した場合は、残る項が無く「寄与0の合計＝0」と「観測値が0」を
  区別できないため、`required`の有無によらず軸全体が欠損になる。
- `CategoricalShape`: 単一`material`の値を`mapping`（カテゴリ値→スコア）で引く。
  材料の列は材料と入口によって別の形で届く——ルート選びと地図の配信の分類材料は語彙への番号の列
  （`domain/attributes.py: CategoricalColumn`。欠損は番号0）、Pythonの値の入口（区間の内訳）の
  分類材料は文字列のobject配列（欠損は`None`）、真偽材料は数値配列（1.0/0.0、欠損は`NaN`。
  `material_catalog.material_array_columns`が数値の行列へ載せる）。
  `evaluate_categorical`は、番号の列なら語彙の値ごとに1回引いた表を番号で配り、それ以外は
  `np.searchsorted`の二分探索で解決する（O(要素数×log(キー数))）。
  JSONのキーは文字列なので、真偽の材料の対応表は`"true"`/`"false"`で届く。真偽として読むのは
  この2つの綴りだけで、それ以外（`"yes"`・`"on"`・`"1"`等、pydanticなら真偽と読む綴りを含む）は
  書いたとおりの値の名前として扱う。
- 数値変換の実装は`domain/axis_templates.py: evaluate_breakpoint_linear`/
  `evaluate_categorical`。「合成」（他軸のスコアを次の軸の入力として使う階層構造）は
  独立したプリミティブではなく、連続演算の結合ステップの性質から生じる（`terms`の各
  materialが材料id・他軸のaxis_idのどちらも区別なく指せるため）。

### `PriorityCondition`（0次条件）

`material`の値が`equals`と一致する場合、shape評価をスキップし`value`をそのまま返す
（探索除外のハードフィルタ`domain/hard_filters.py: DEFAULT_HARD_FILTERS`とは別の仕組み）。

**一致の判定は1本**（`_priority_override_mask`）で、Pythonの値で持つ入口（区間の内訳）も
材料の値を配列にして同じ関数を通す。材料の値は入口ごとに別の形で届く——区間の内訳は
Pythonの値、ルート選びと地図の配信は材料の型ごとの配列で、分類の材料は語彙への番号の列、「不明」を持つ真偽の材料
は1.0/0.0/NaNの数値の配列になる。判定を2本持つと、この形の違いで区間の内訳とルート選びが同じ道に違う答えを出す。
`equals`は`CategoricalShape.mapping`のキーと同じ読み方（`flag_or_value_name`）で、`"true"`/`"false"`だけを
真偽と読み、それ以外は書いたとおりの値の名前として比べる。欠損（None・NaN）はどの条件にも当たらない。

**タイルの式は0次条件を表せない。** タイルの式（`TileInputSpec`）に条件を載せる形が無いため、0次条件を持つ軸は
タイルでは塗らない（下の「地図表示ルールの自動導出」）。地図の配信（[dynamic-way-values.md](dynamic-way-values.md)）は
ルート選びと同じ評価を通すので条件も当てるが、0次条件を持つ軸の符号付き材料の生値は塗らない（下の「地図が塗るもの」）。
条件を落として塗ると、条件の当たる道で地図の色とルート選び・区間の内訳が食い違う。

### 軸の階層

`MaterialTerm.material`/`CategoricalShape.material`は材料idだけでなく他の軸の`axis_id`も
指せる。評価済みの軸のdifficultyが材料と同じ扱いで混ぜ込まれるため、非公開の内部軸
（`is_published=False`）を合成した公開軸を作れる。

## 評価パイプライン

| 関数 | 用途 |
|---|---|
| `evaluate_axis_values(definition, materials, length)` | 材料id→Pythonの値の並びから要素ごとの得点。欠損はNone。配列へ並べ替えて`evaluate_axis_array`を通す |
| `evaluate_axis_array(definition, materials)` | 軸の評価の本体（numpy配列、欠損はNaN）。どの入口もここを通る |
| `evaluate_axes_array(materials, definitions)` | `definitions`の全軸を依存順（`topological_axis_order`、内部軸→公開軸）で評価し、軸id→得点の辞書を返す（評価した軸の得点は後の軸の材料として読まれる） |
| `evaluate_axes_values(materials, length)` | `evaluate_axes_array`をPythonの値の並びから通し、公開軸だけの得点を返す（評価できない公開軸もキーを残してNone） |
| `evaluate_axes_inputs(materials, length)` | 同じ入力から、公開軸ごとに得点へ写す前の値（折れ点の軸は生値、対応表の軸は引く材料の値）を返す。他の軸を読む軸の生値は、読んだ軸の得点から求める。飽和の計測が使う |
| `raw_values(shape, materials, length)` | 折れ点を通す前の生値をPythonの値の並びから求める。保存前の`shape`を受け取れるため分布プレビューが使う |

折れ線の得点は難易度の桁へ丸め、Pythonの`round()`と同じ値へ丸める
（`domain/difficulty.py: round_difficulty_array`。2進の実際の値で丸める）——`np.round`は×10の丸め誤差で、端数がちょうど`.x5`の値を別の側へ丸める。

`topological_axis_order`は深さ優先探索でトポロジカルソートし、結果を内容ベースの
キー（各軸の`materials`）でメモ化する（件数上限つきの`cachetools.LRUCache`。軸スタジオの
管理APIは呼び出しのたびに新しい`dict`を作るため、上限が無いと軸を編集するたびに鍵が増える。
`replace_axis_definitions`が
同一dictオブジェクトのまま中身だけを差し替えるため、オブジェクトidベースの
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
        │ replace_axis_definitions()（同じdictのまま .clear() + .update()）
        ▼
  AXIS_DEFINITIONS（モジュールレベルdict）
        │
        ├──→ leg_costs.py（ルート探索のコストの合成）
        └──→ axis_catalog.py（GET /api/axis-catalog、実行時・即座に反映）
```

- `AXIS_DEFINITIONS`はPython literalの初期値を持たない（空dictで開始）。DBが唯一の正本。
- 差し替えはイベントループで動くので、ループの上で読む側は差し替えの途中を見ない。`asyncio.to_thread`の先で
  軸を読む処理（静的スコア行列を組む`build_static_edge_score_matrix`）は、入口で`copy_axis_definitions`の写しを
  1回取り、終わりまでその写しだけを読む——直に読むと、読む間の保存で鍵が欠ける・回している辞書の大きさが変わる・
  読むたびに軸の集合が食い違う。写しと差し替えは同じロックで排他にし、写しが差し替えの途中（空の辞書）を見ない。
- `refresh_axis_definitions`はDB読み込み失敗・0行・値の不変条件（下の「軸の外に照らす値の不変条件」）に
  通らない軸のいずれかを検出すると`AxisDefinitionSyncError`を送出しfail-fastする（安全側フォールバックは
  持たない、main.pyのlifespanはこれを捕捉せずアプリ起動自体を失敗させる）。材料をカタログから外す・材料の
  型を変えるコード変更は、それを指す軸が本番DBに残っていればデプロイした起動で落ちる——先に軸を直す。
- **行データ（軸の新規追加・既存軸の値変更）は`axis_admin.py`経由でしか入らない。**
  スキーマは`axis_definition_models.py`のORM宣言から`create_tables()`が作る。
- **公開済み軸を不変にしているのは、一般ユーザーの保存設定が`axis_id`キーで再現される
  ため**（ルート設定パネルのプリセット・重みは`localStorage`に`axis_id`で残る）。公開後に
  破壊的な変更・削除を許すと、他の利用者の設定を黙って壊す。改良したいときは複製して
  新しい`axis_id`の下書きを作り、そちらを検証して公開する。

### まっさらなDBに軸の行は入らない

`scripts/bootstrap_database.py`が作るのはスキーマ・取込・派生までで、`axis_definitions`の
行は作らない。`refresh_axis_definitions`は0行を`AxisDefinitionSyncError`として扱うため、
**新規環境ではアプリが起動しない**。軸を足す管理APIも起動したbackendにしか無いので、新規環境へ
軸を入れる経路は、管理データのバックアップからの復元（`pg_restore`、
[横断基盤](cross-cutting-infrastructure.md)「取り直せない管理データのバックアップ」）だけである。
新規環境（composeのDB・クラウドのセッション）はテストを回す場と決めており、
アプリを確かめるのは本番か手元の開発機で行う（[setup.md](../../architecture/setup.md)）。

テストの中でも`AXIS_DEFINITIONS`は空から始まる。軸の集合を必要とするテストは、見たい
性質（shapeの種類・表示の上書き・専用way値配信等）だけを持つ軸をそのファイルで組み立て、
`tests/axis_system_fixture.py`の道具で流し込む。本番の軸は模さず、DBの実データとは独立で、
DB側の値が変わっても追従しない。軸の中身が主題でないテスト（永続化・レジストリの操作・
公開の出し分け等）は同じモジュールの`axis_definition()`で軸を作り、見たい性質（材料・重み・
公開・配信の印）だけを引数で書く。既定は型を満たすためだけの値なので、既定に寄りかかった
主張は書けない。

## 地図表示ルールの自動導出（`domain/axis_display.py`）

軸が参照する材料が全てMVTタイルへ焼き込み済みであれば、地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を`axis_display_for()`
が自動導出する。**安全に自動導出できるケースに限定**し、それ以外は`None`（`kind="none"`、
地図に出ない）を返す:

| shapeの形 | 自動導出できるか |
|---|---|
| `CategoricalShape`（真偽値材料1件、またはstr N値材料1件） | できる（隣接中間点をしきい値に） |
| `BreakpointLinearShape`で全termがboolean材料 | できる（重みの全部分和集合の隣接中間点。上限12term） |
| `BreakpointLinearShape`で`preprocess="identity"`（全termがboolean材料の形を除く） | できる（breakpointsのx値をそのまま流用。boolean材料の項は該当時に重み・非該当時に0の2値として足す） |
| `preprocess="abs"`を含む軸 | **できない**（実装しないと確定済み。方向依存材料[風・勾配]を含む軸は別の制約でも弾かれるため二重に対象外） |
| タイル非依存材料・方向依存材料（`tile_property_direction_dependent`）を含む軸 | できない |
| 他の軸を参照する`MaterialTerm`を含む軸 | 参照先の軸を1段だけ解決して畳めれば可（`_resolve_referenced_axis_tile_input`）。2段階以上のネストは非対応 |
| `priority_overrides`（0次条件）を持つ軸、または畳む参照先の軸が持つ | できない（タイルの式が条件を表せない。上の「`PriorityCondition`」） |

`axis_display_for(definition)`の優先順位: ①自動導出成功＋`display_thresholds_override`
設定済みなら両方を組み合わせる、②自動導出成功のみなら自動導出のしきい値をそのまま使う、
③自動導出失敗なら`kind="none"`。しきい値を決めるのは`axis_display_for`1本で、
ルート線側の境界（`map_paint.py: map_paint`の`thresholds`）もそこから導く。

**折れ線が写した得点（小数1桁に丸めた値）が、直前に残した境界の得点を上回らない境界は落とす。**
上書きで指定された値も同じ扱いで、軸スタジオで4つ刻んでも折れ線が3つ目で100へ達していれば段は
3つになる。評価が区別できない差に境界を引くと、色だけが変わって評価は同じという見分けを地図が
見せることになり、しかもルート線側は難易度を塗るためその段を作れない（前後で段の数が食い違う）。
得点が下がる境界も同じ理由で落ちる——ルート線の段は難易度の昇順でしか切れないため、材料の値が
増えるほど得点が下がる折れ線では、最初の境界だけが残る。
折れ線の最も低い得点は、最初の境界の手前の得点として数える——その得点へ写る境界（折れ線の下端より下に置いた
境界）は、下の段に得点で入る道が無い（凡例に「0点未満」のような届かない段が出る）ので落ちる。上端の得点へ写る
境界は落とさない（その段には上端に張り付いた道が入る）。

軸スタジオは刻んでいる最中にこの落ちる値を印として出すため、保存前の下書きで同じ判定を問う
（`bands_the_map_keeps`、`POST /api/admin/axis-definitions/preview-display-thresholds`）。
判定は`axis_display_for`と同じ`_map_band_thresholds`を通し、frontendへ規則を写さない。
入力は段を決めるのに要るもの（`axis_id`・`shape`・`priority_overrides`・しきい値）だけで、
表示名・重みのような下書きの途中で欠けうる項目を揃えさせない——揃えさせると、書きかけの
軸では印が出なくなる。保存前の下書きなので自分自身を参照する軸も届く（保存は循環として拒否される）。
その軸は、保存済みの自分を材料として畳まず、地図に出ない軸として扱う（全段が残る）。

**段が落ちても、体感ラベルは地図の段へ引き直して配る。** 体感ラベルの上書き
（`display_band_labels_override`）は人が刻んだ境界の段ごとに付くため、境界が落ちると件数が
地図の段数と合わない。境界が落ちてまとまった段は、その下端で始まる入力の段として扱い、その段の
ラベルを持つ（`bands_the_map_keeps`が地図の各段に当たる入力の段の番号を返す。下端が同じ値なので、
地図の凡例のレンジとラベルが食い違わない）。軸カタログは生の上書きではなくこの引き直した値
（`map_band_labels`）を、地図が塗るものの`band_labels`（下の「地図が塗るもの」）で配る。
軸スタジオの段階プレビューも同じ番号を問い合わせの応答（`bands_on_map`）で受け取る。

**地図の式が評価と同じ値を出すことは、表で確かめる。** 導出の形ごと（例: 真偽の材料・分類の未登録の値・
実行時の係数・他の軸を参照する項）に、表のために組んだ軸と道1本の材料から、
地図へ配る表示（`axis_display_for`）・タイルのプロパティ（`domain/material_catalog.py: tile_property_value`）・評価が付ける値（折れ点の軸は折れ点を通す前の和、分類の軸は点数）と
「不明」かを`scripts/cross_language_expectations.py: axis_ramp_expectations`が表にして生成物へ出し、画面のテストが
全行を画面の式へ通す（置き場と作り方は[testing-frontend.md](../../../.claude/rules/testing-frontend.md)「パターン11」）。

**暗黙の前提（重要な既知の非対称性）**: 自動導出した表示と評価側の整合性は
`required=False`の材料でのみ厳密に一致する。`required=True`の材料が欠損している場合と、全termの材料が
欠損している場合、評価側（`evaluate_axis_array`）は軸全体を「評価不能（None）」にするが、フロント側の
自動導出expression（`buildAxisRampValueExpression`）はタイルプロパティ欠損を寄与0
（coalesce）として扱う——本来「評価不能」な区間が地図上では「評価済みで良好（緑）」に
誤表示されうる。0を省く材料（`TileEncoding.omit_zero`。密度等）はタイルに0が載らず、地図は欠損を0として読むため、地図の側では欠損と0を見分けられない。
実務上は稀（way単位の事前集計は欠損時0埋めが基本）だが、新規軸でrequired=True材料が実際にタグ欠損
しやすい場合はこの不整合が顕在化しうる。同じ理由で、他の軸を参照する項（`TileInputSpec.breakpoints`）は
材料の値が0の道も地図では寄与0になり、評価（参照先の折れ線の0での点数）と食い違いうる。上の表はこれらの場面を入れない。

### 地図が塗るもの（`domain/map_paint.py`）

`map_paint(definition)`が、地図がその軸について塗るものを1つの値（`MapPaint`）で返す。ルート確定前の全道路の塗り
（ramp・[地図の配信](dynamic-way-values.md)）・ルート確定後のルート線の色分け・凡例は、どれもこの値に従うので、
同じ軸の色分けはルートの有無でスケールも段も変わらない。塗る値の種類だけが要る読み手（配信の写し
`dynamic_way_values.py: paint_feature_values`・区間表示へ載せる材料`evaluation.py: displayed_material_ids`）も、
この値の`value`を読む。`GET /api/axis-catalog`は軸ごとにこの値を`map_paint`として配る。

| 欄 | 意味 |
|---|---|
| `value` | 塗る値の種類（`DifficultyMapValue`・`SignedMaterialMapValue`の判別共用体）。0次条件（`priority_overrides`）を持たず、`BreakpointLinearShape`かつ`preprocess="abs"`かつterms単数で、その項が材料（`MATERIAL_CATALOG`にある）を指すなら符号付き材料（生値を塗る材料を名指す）、それ以外は難易度。項は軸を指すこともあり、その値は参照先の得点で符号にも単位にも材料の意味が無い。0次条件を持つ軸の生値は、条件の当たる道でも生値のままで評価と食い違う。ramp軸は`axis_display_for`が符号を畳む形を外すため、いつも難易度 |
| `unit` | 符号付き材料なら材料カタログの`unit`、難易度は空文字 |
| `thresholds` | `value`のスケールでの段の境界（下記） |
| `tiles` | ルート確定前に全道路をタイルの値で塗る式と、その値（材料の目盛り）での段の境界（`axis_display_for`の`AxisDisplaySpec`）。タイルで塗れない軸（専用way値配信・地図に出ない軸）は`kind="none"` |
| `band_labels` | 段ごとの体感ラベル（上の「段が落ちても、体感ラベルは地図の段へ引き直して配る」の`map_band_labels`）。上書きの無い軸はnull |
| `legend` | 凡例が段の境界を書く目盛り（`MapLegendScale`: `thresholds`と同じ件数の境界と単位）。符号付き材料は塗る値そのもの（材料の単位）。難易度の軸のうち、得点が単位の定まる生値（`raw_value_unit`）から0次条件なし・符号を畳まずに作られ、その量について狭く増える（折れ線の節の得点が狭く昇順）軸は、境界を量で書く（例: 雨は5・20・50mm）。それ以外は得点（単位null。画面は「影響 33点未満」と書く）。塗るのは得点でも量で書いてよいのは、狭く増える間だけ「得点 f(a)以上 f(b)未満」と「量 a以上 b未満」が同じ道を指すため。量の境界は折れ線の下端より上・上端以下に限る（外では得点が端に張り付く） |

**段の並びの件数は値が揃える。** 読む側は段の番号で境界・凡例・タイルの境界・体感ラベルを引き合わせるので、
`MapPaint`は作るときに、`thresholds`の件数+1（段の数）と、`legend`の境界の件数+1・`tiles`がrampならその境界の件数+1・
`band_labels`があればその件数が揃っているかを確かめ、揃わなければ送出する（揃わない値を軸カタログへ出さない）。

段の境界（`thresholds`）:

- **段そのものを決めるのは`axis_display_for`**（ルート確定前の全道路を塗る境界）で、ramp軸ではその値を軸の折れ線で
  難易度へ写すだけ。写さずに配ると、材料の単位で書かれた境界が0〜100と比べられ、ルート線が全区間ひとつのバンドへ落ちる。
  分類の軸の値は初めから得点なので写さない。
- ramp表示を持たない軸（専用way値配信）の上書きは、地図が塗る値そのものに対する境界なのでそのまま返す。符号付き材料の
  軸で上書きが無ければ、折れ線の節を0対称に開いた境界にする（軸は`|値|`を評価している）。
- **上書きの有無で経路を分けない**——上書きを設定していない軸だけが無しを返して読む側の既定値へ転落すると、その軸だけ
  ルート確定の前後で段の数も意味も食い違う。境界を宣言していない難易度の軸も、既定の境界（`DEFAULT_DIFFICULTY_BOUNDARIES`）を
  ここで解いて返す——読む側に既定を持たせない。ただし凡例を量で書ける軸（上の`legend`）は、折れ線の節（軸が「どの量から
  効きが変わるか」を宣言したもの）で切る——3等分の境界を量へ戻すと半端な量（雨なら6.1mm等）になる。

### 生値の単位（`raw_value_units`）

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

`raw_value_units`は、この単位と、生値へ走行距離を掛けた総量の単位（重み0以外の項の材料の`total_unit`が1つに揃うときだけ。
[evaluation-scoring.md](evaluation-scoring.md)の材料の`total_unit`）を1つの値（`RawValueUnits`）で返す。総量の単位は生値の
単位がある軸にだけ付き、生値の単位の無い総量の単位は値が断る。
`GET /api/axis-catalog`がこれを`raw_value_units`として配信し、
[ルート設定・ルート結果（frontend）](../frontend/route-settings-and-results.md)が
得点の隣へ生値を添えるのに使う。単位の無い数字は読み手が意味を取れないため出さない。
地図の凡例も、得点が単位の定まる生値について狭く増える軸では、段を生値の量と単位で書く
（`map_paint.py: map_paint`の`legend`。上の「地図が塗るもの」）——rampの段の境界は
折れ点のx値（＝生値の目盛り）で、単位が定まる軸では生値と同じ量を塗っている（`axis_display.py`）。

### 材料単位への分解（`material_breakdown`）

上の表で`None`になる軸は、代わりに`axis_material_shares`が軸を**材料まで分解**し、
材料ごとの絶対量を並べられるようにする（同じ`axis_raw_value.py`）。軸参照は葉の材料まで
再帰的に辿り、途中の軸の得点は内訳に含めない。並びは各階層で正規化した重みの積の降順で、
重み0の材料は含めない。参照材料が1件へ分解される軸は分解しない（軸単位の生値で足りる
うえ、`shape.preprocess`が材料単位では効かない）。導出の根拠と、値の運搬・表示の詳細は
[評価・スコアリング](evaluation-scoring.md)「ルート単位の集約」節を参照。

`GET /api/axis-catalog`が`material_breakdown`として、材料id・表示名・型・単位・
正規化重みの並びで配信する（フロントは材料の対応表も並べ替えも持たない）。

## 一次属性の語彙（`domain/primary_attributes.py: PRIMARY_ATTRIBUTES`、別系統）

**`AXIS_DEFINITIONS`とは別の、一次属性の語彙**。型（`PrimaryAttributeSpec`）は`domain/registry.py`が持つ。
語彙はタプル`PRIMARY_ATTRIBUTES`が宣言し、同じ`attr_id`を2度宣言すると
モジュールのimport時に落ちる（読む側はidで1件を引くため、後の宣言が黙って消える）。軸は含まない——
材料が2つの軸へ跨がらないことの検査は`AXIS_DEFINITIONS`側の`check_material_exclusivity`/
`AxisMaterialConflictError`（軸の集合の検査`check_axis_set`）だけが持つ。

材料（`MaterialSpec.primary_attribute`）は一次属性を
idの文字列ではなく宣言そのもので指す。材料が指す要素には`PRIMARY_ATTRIBUTES`の表の中で`:=`により
名前を付け、材料カタログはその名前をimportして書く。表の要素そのものでない一次属性（同じ`attr_id`の写しも）を指す材料は、
`MaterialSpec`の検証（`domain/material_catalog.py: MaterialSpec._check_primary_attribute_is_declared`）が断る。
既存の一次属性を指す材料を足すときは、材料の宣言だけで済む。逆向き（材料を1つも持たない一次属性）は
許す: 地図の分類としてだけ存在し（例: 補給・休憩ポイント）、軸の`primary_attribute_ids`には
現れないため評価に効かない。一次属性が複数の材料に共有される（例: `landcover`は土地被覆の区分ごとの材料が指す）ため、
名前・幾何・地図の束ね方は材料ではなく一次属性の側に1回だけ書く。

語彙をフロントへ届けるのはビルド時の`scripts/export_openapi.py`
（一次属性の名前を`primaryAttributes.ts`へ書き出す）。**軸カタログそのものにビルド時の写しは
無い**——frontendは`GET /api/axis-catalog`が返したものだけを使う
（[設計原則](../../architecture/design-principles.md)構造仕様9）。ビルド時には
`AXIS_DEFINITIONS`が空（DBから埋めるのは実行時の`refresh_axis_definitions`だけ）なので、
ビルド時に軸を見る検査は置けない。

## API

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/admin/axis-definitions`・`/{axis_id}` | Basic認証必須 | 一覧・単体取得。レスポンスは`display`（`axis_display_for()`の計算結果）も含む——下書き軸の自己診断（地図表示データがまだ用意されていないか）のため。`weight_share_when_published`（保存した既定の重みで公開したとき、公開軸の重みの合計に占める割合。総合難易度と同じ分母、`difficulty.weight_share`）も含み、作成・更新・非公開化の応答も同じ値を返す |
| `POST /api/admin/axis-definitions` | Basic認証必須 | 作成 |
| `PUT /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 更新（公開済みは原則拒否。ただし表示専用フィールド[`icon_id`/`display_thresholds_override`/`display_band_labels_override`]のみの差分は例外的に許可） |
| `DELETE /api/admin/axis-definitions/{axis_id}` | Basic認証必須 | 削除 |
| `POST /api/admin/axis-definitions/{axis_id}/unpublish` | Basic認証必須 | 公開済み軸を下書きへ戻す（`is_published`以外は変更しない） |
| `POST /api/admin/axis-definitions/preview-display-thresholds` | Basic認証必須 | 編集中の軸で、上書きしたしきい値のうち地図が段にしないものと、地図の各段に当たる入力の段（DBを読まない） |
| `POST /api/admin/axis-definitions/preview-scores` | Basic認証必須 | 編集中の折れ点で、横軸の値の並び（分布の階級の代表値）と1つ目の項の材料の値の並び（参考点）がそれぞれ何点になるか。参考点は横軸の値も返す。どちらも評価と同じ配列の計算（`domain/axis_definitions.py: BreakpointLinearShape.scores_at`・`first_term_points`）で出し、参考点は「ほかの項の材料が無い道」として評価する——ほかの項に必須の材料があれば評価と同じく欠損（null）になる（DBを読まない） |
| `GET /api/axis-catalog` | 不要（公開） | `is_published=True`の軸のみ返す。画面が読む項目（名前・説明・重みの既定・チップ・地図が塗るもの・生値の単位と内訳等）だけを返し、`shape`・しきい値の上書きの生の値は返さない（地図の段は`map_paint`が軸の折れ線で写して配る） |

管理API（`/api/admin/axis-definitions`）のBasic認証はルーターの`dependencies`で1か所に宣言し、
口ごとには付けない——口を足しても認証の付け忘れが起きない。

`GET /api/axis-catalog`の`tile_runtime_scales`（タイルのプロパティ名→実行時にしか決まらない換算係数）
だけが、リクエストごとにDBを見る（係数の源の事故の収録年）。どの材料に係数が要るかは材料の宣言
（`MaterialSpec.tile_property_runtime_scale`）だけが持ち、ルーターは材料名を持たない。印を付けた材料が
増えると、同じ源なら宣言だけでその材料のタイルの値にも係数が届く。新しい源（収録年数以外）を足すときは
`domain/material_catalog.py: tile_runtime_scales`にその値の求め方を足す——足すまではその材料の係数が
配られず、地図はその材料を使う軸をどの道も「データなし」で塗る（最良側の色にはならない）。

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
- `axis_id`・`label`・材料idは空文字でないこと、`default_weight`は非負。重み・係数にNaN・無限大を許さない（軸の得点も合成difficultyも黙ってNaNになり、
  欠損と区別できなくなるため）。

### 検証の文

**検証の文は管理画面の保存の誤りにそのまま出る**（画面は軸の不変条件を写さない）。文は利用者が読める
日本語で書き、`axis_definitions.py: axis_error`（`PydanticCustomError`）で返す——`ValueError`は
「Value error, 」の前置きが付いて返る。組み込みの制約（空・件数）が英語の文を返すもののうち画面で
起きるもの（表示名が空・しきい値の上書きが0件）は、制約より先に動く検証（`mode="before"`）で日本語にする
（制約そのものは契約に載せるため残す）。

**文は材料・軸を表示名で名指し（`axis_definitions.py: named_references`）、直し方を添える。** idは画面のどこにも
出ないので、idで名指すと管理者はどの材料・軸のことか辿れない。名前を持たない参照（材料にも軸にも無いid）だけは
idのまま出す。書き込み時のガード・削除の断り（下の「書き込み時のガード」）も同じ書き方で、管理APIが409の
`detail`としてそのまま返す。起動時の読み込みの失敗（`AxisDefinitionSyncError`）は運用者がログで読むため、軸をidで名指す。

### 軸の外に照らす値の不変条件（`domain/axis_definitions.py: check_axis_definition`）

材料カタログ・ほかの軸に照らす値の不変条件。**書き手を問わず成り立つべきもの**
なので、管理APIの本文（`AxisDefinitionPayload`）も、起動時の読み込み
（`services/axis_registry_service.py: refresh_axis_definitions`）も同じ関数を通す——管理APIを通らずに書かれた
行（バックアップからの復元）も、次の起動で書き込み時と同じ検査に止まる（通らなければ起動しない）。軸の参照として受け入れるのは、管理APIでは今の`AXIS_DEFINITIONS`、
読み込みでは同じ読み込み結果の軸。モデルの検証に置かないのは、保存済みの行を読み出す管理APIの一覧・単体取得が、
通らなくなった行（材料をカタログから外した後の軸等）もそのまま見せて直させる必要があるため。

- shapeが参照する材料・軸参照が既知であること、材料のdtype（numeric/boolean/
  categorical）がshape種別の前提と一致すること（`CategoricalShape`は
  boolean/categorical材料、`BreakpointLinearShape`はnumeric/boolean材料）。
  `CategoricalShape`はさらに`mapping`のキー型（bool/str）が材料のdtypeと一致することも
  検証する。
- `priority_overrides`は、どの道にも当たらない条件を拒む（評価はエラーもログも出さず、条件が
  無警告のまま一切発動しなくなるため）: `material`が既知の材料であること、その材料が真偽・分類の
  材料であること（数値の材料・軸の点数には値の名前で当たる値が無い）、`equals`を対応表のキーと同じ
  読み方で読んだ値の型が材料の値の型と合うこと（真偽の材料は`"true"`/`"false"`、分類の材料はそれ以外の
  値の名前）。
- リクエスト時に評価される動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）と静的材料を同じ軸で
  混在させないこと。動的軸の再評価経路（`domain/dynamic_materials.py:
  evaluate_dynamic_axis_arrays`）へ渡るのは「探索範囲の静的スコア行列の公開軸スコア」と
  「動的材料」だけで、静的材料の配列は渡らない——混在させた軸は`evaluate_axis_array`が
  KeyErrorになり`/api/routes/generate`ごと失敗する。静的材料が必要なら別の軸へ切り出して
  軸参照で合成する。
  参照材料の導出は`AxisDefinition.materials`と同じ`referenced_materials`
  （`domain/axis_definitions.py`）を使い、**shapeの種別を問わず`priority_overrides`が
  参照する材料も含める**。動的軸かどうかを判定する`_axes_depending_on_materials`が
  同じ導出を根拠にしているため、検証側だけ`shape.terms`に絞ると素通りした軸が実行時に落ちる。
- 密度の軸（`domain/axis_definitions.py: averages_density`。1kmあたりの回数・件数の材料`MaterialSpec.additive`だけを
  項に持ち、前処理の無い軸）の折れ点は、(0, 0)ともう1点の2つに限る（点数は回数に比例し、もう1点より先はその点数で
  止まる）。探索の費用はこの軸の分を回数×傾きの秒として足す（[評価・スコアリング](evaluation-scoring.md)「ルート単位の
  集約」の密度の軸）ので、傾きが1つに決まらない折れ線では、探索とルートの値が食い違い、道の切り方で点数の和が変わる。
  足せる材料かは材料カタログが決めるため、モデルの検証ではなくここに置く。

### 軸の集合の検査（`domain/axis_definitions.py: check_axis_set`）

軸1本ずつでは決まらず、軸の集合で決まる不変条件。起動時の読み込み（バックアップから戻した行も）と管理APIの書き込みが
同じ関数を通す。

- 軸idが材料idと重ならない——軸の評価結果は材料と同じ辞書へ書き戻されるため、重なると同名の材料の値を黙って上書きする。
- 1つの材料を2つの軸で数えない（`check_material_exclusivity`）。重なりは後に並ぶ軸の誤りとして名指す（作成・更新の書き込みは
  書いた軸を最後に並べて渡す（`services/axis_registry_service.py: _check_loadable_after_write`）ので、断りの文が書いた軸の側から読める）。
- 組み合わせが輪にならない（`topological_axis_order`）。

書き込みの断りは例外の文（表示名で名指す）のまま返し、起動時の読み込みの失敗は例外が持つid（重なった2軸・輪の並び）で
文を組み直す（`services/axis_registry_service.py: _loading_problem`。上の「検証の文」）。

組み合わせに使われる軸を公開しないこと（`check_internal_axis_not_published`）は含めず、書き込みだけが見る——時刻で
変わる軸が公開軸を組み合わせる形（上の動的材料と静的材料を混在させない条件が案内する形）を拒むことになるため。

### 書き込み時のガード（`AxisRegistryAdminService`）

| 操作 | ガード |
|---|---|
| create | axis_idの重複。内部軸の誤公開防止 |
| update | 公開済みは原則拒否（`check_publish_immutability`）。ただし`candidate`引数を渡すと、表示専用フィールドのみの差分（`is_cosmetic_only_update`）なら公開済みでも許可する。内部軸の誤公開防止は下書きから公開へ切り替える書き込みにだけ当て、既に公開中で組み合わせに使われる軸の表示だけの直しは通す |
| delete | 公開済みは拒否 |
| unpublish | `is_published`のみを変更する専用操作（`update()`は使えない、公開済みは拒否されるため） |

create/update/deleteは、確定する前に**書いた後の全軸**を起動時の読み込みと同じ判定
（0行と、`check_axis_definition`に通らない軸（`services/axis_registry_service.py: _rejected_axes`）と、下の軸の集合の検査）へ通し、通らなければ確定しない。
確定してから反映（`refresh_axis_definitions`）で通らないと分かっても、行は既にDBにあり、次の起動が止まる。
削除では、ほかの軸（材料・0次条件のどちらでも）が参照している軸と最後の1軸がこれで止まる——内部軸を
整理するときは、参照している軸を先に直すか消す。判定を別に持たないので、読み込みの規則が増えれば
書き込みも同じだけ止まる。

削除の断り（`services/axis_registry_service.py: _check_deletable`）は、消す軸と、それを組み合わせに使っている軸を
表示名で名指し、先に外すか消すという次の手を書く。消す前の全軸は読み込みを通っているので、消した後に判定を
通らなくなる軸は、消す軸を指している軸だけである（判定のうち軸を減らして破れうるのは参照先の実在だけで、軸の集合の検査は軸を減らしても破れない）。

いずれの書き込みも「DB commit → `refresh_axis_definitions`呼び出し」で完結する
（1操作=1トランザクション）。create/update/unpublishは書いた後の全軸を返し、管理APIの応答（公開したときの重みの割合）は
それから組む——書いたあとに一覧を読み直さない。

create/update/delete/unpublishはいずれも冒頭で`AxisDefinitionRepository.
acquire_write_lock()`（PostgreSQLのトランザクションスコープadvisory lock）を呼び、
「読み取り→Python側で検証→書き込み」の一連を直列化する。このロックが無いと、
2つのcreate()が同時に走った場合に互いのsort_orderや材料排他帰属チェックが相手の
変更を見ないまま古いスナップショットへ基づいて計算されるため、書き込み後にsort_order
衝突・材料の二重帰属というTOCTOUレースが起こりうる（`sort_order`の衝突は表の一意制約でも断られ、
書き込みが失敗する側へ倒れる）。asyncio.Lock（同一プロセス内のみ
有効）ではなくDBレベルのロックにしているのは、将来複数ワーカー化する場合にも機能させる
ため。

## 軸idを名指しするコードを残さない

軸は軸スタジオから増減するため、`axis_id`を条件分岐に使うコードがあると、その軸を消した
瞬間に壊れる。表示の振る舞い（地図に出すか・符号付きで塗るか・時間帯で効くか）は
すべて`AxisDefinition`のフィールドから導く。現時点で軸idを名指しする削除ガードは持たない。
