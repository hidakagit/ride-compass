# 評価軸のフルレジストリ駆動化＋GUI編集基盤 ADR（T221）

T12（[t12-routing-scale.md](t12-routing-scale.md)）の「軸の可換性」検証（原則7、2026-08-23訂正）で
判明した事実——現行7軸の変換ロジックが実質3つの汎用テンプレートに還元できる——を踏まえ、
「見た目の磨き込みだけをIFとして切り出し、裏のロジックはすべてレジストリ駆動にする」という
ユーザーの将来像（2026-08-23）を実現するための独立した設計課題として起票する。

T12（探索のスケール＝速さ）とは別軸の課題（評価軸の編集容易性＝柔軟さ）だが、どちらも
「1次＝素材（データ）」「2次＝軸定義（ロジック）」「3次＝重み（好み）」という同じ3層分離
（T12原則2・3・6・7）を土台にしており、素材カタログはT218（探索の素材事前計算化）と共有する。

ステータス: **ドラフト（2026-08-23起票、方向性のみユーザー承認済み。詳細設計・段階構成は未承認）**

---

## 背景: 現行7軸は実質3つの汎用テンプレートでしかない

`backend/app/domain/difficulty.py`を精査した結果（2026-08-23）:

| テンプレート | 該当軸 | 実体 |
|---|---|---|
| **折れ線補間**（`_piecewise_linear`、difficulty.py:51-62） | gradient・wind・stop_density・car_stress・accident（5/7軸） | 値（または複数素材の重み付き和）をbreakpoints配列で0-100へ変換。2点のclamp-linear（wind/accident）も5点の勾配カーブ（gradient）も同一関数 |
| **カテゴリ変換** | surface_q（1/7軸、`road_difficulty`、difficulty.py:79-82） | 値→スコアの辞書引き（good=0/bad=80/None=None） |
| **フラグ加算** | night（1/7軸、`night_difficulty`、domain/night.py） | 複数の真偽フラグにそれぞれ点数を割り当てて合計、上限でclamp |

car_stressは一見複雑だが、実際は「レシピ（highway基準値＋補正、**T141で既にJSON上書き可能**）
→レベル1-5→折れ線補間」の2段構成で、後段は結局同じ折れ線補間テンプレートである。

**結論**: 現行7軸は"新しい計算ロジック"を1つも持っていない。すべて「どの素材を」
「どのテンプレートに」「どのパラメータで」通すか、という**データ**の違いだけで表現できる。
一方、実際にこれを支えるコードは以下のように分散しており（T12原則7の再検証で判明）、
軸の追加・削除には現状backend約10箇所＋frontend約5箇所への手書き変更が要る:

- `RoutePreference`（固定フィールドpydanticモデル、evaluation.py）とAPI層の重複モデル
- `AxisDifficulties`（固定フィールドNamedTuple、difficulty.py）
- `evaluate_axis_difficulties`（軸ごとに1行ハードコードされた本体、difficulty.py）
- `AXIS_WEIGHT_FIELD_TO_AXIS_ID`等の手書き対応表（evaluation.py）
- `route_preference.yaml`（既定重み、軸数ぶんのキー）
- フロントの手書きRecord群（`evaluationAxes.ts`・`secondaryAxes.ts`・
  `MapOverlayControls.tsx`の`SECONDARY_AXIS_ICONS`・`icons.tsx`の専用アイコン・
  `WeightPanel.tsx`のyamlミラー）

## 目標

1. **ロジック層（素材選択・変換テンプレート・パラメータ・重み・合成）を完全にレジストリ駆動にする**。
   軸の追加・削除・改変が、既存テンプレート＋既存素材の組み合わせで表現できる範囲では
   **コード変更なし・データ変更のみ**で完結する。
2. **見た目の磨き込み（アイコン・略名・案内文等）は独立したUIオーバーライド層として残す**。
   無指定時はテンプレート単位の汎用フォールバックで動作し、手作り感のある専用表現は
   「上書きしたい人だけが追加する任意設定」という位置づけへ変える。
3. 上記2点を土台に、将来GUIで軸の追加・削除・並べ替え・重み調整（スライダー）ができる
   「評価ルーティング」編集画面を実現できる状態にする（本ADRのスコープは土台までで、
   GUI画面自体の実装は含まない）。

## アーキテクチャ設計（ドラフト）

### 軸定義スキーマ

```
AxisDefinition {
  axis_id: str
  materials: list[str]              # 参照する1次属性id（T218の素材カタログと共有）
  shape: "breakpoint_linear" | "categorical" | "flag_sum" | "recipe_then_breakpoint_linear"
  shape_params: JSON                 # テンプレートごとのパラメータ（下記）
  default_weight: float
  hard_filter: bool                 # 0次（グラフからの除外）として使うか、3次（重み付け）として使うか
}
```

- `breakpoint_linear`: `{ preprocess: "identity"|"abs"|"weighted_sum", weights?: {material: coef}, breakpoints: [[x,y], ...] }`
- `categorical`: `{ categories: {value: score}, default: score|null }`
- `flag_sum`: `{ flags: [{material, points}], cap: number }`
- `recipe_then_breakpoint_linear`: 既存の「レシピ→レベル→breakpoint_linear」2段構成
  （car_stress等、レシピ自体はT141の既存JSON上書きパターンをそのまま流用）

### 汎用評価関数（新規実装が必要なのはこの3〜4個だけ）

`evaluate_breakpoint_linear` / `evaluate_categorical` / `evaluate_flag_sum` /
`evaluate_recipe_then_breakpoint_linear` の4関数が`AxisDefinition`を読んでスコアを返す。
`evaluate_axis_difficulties`はこれらをレジストリの全軸についてループするだけの薄い関数へ
置き換わる（軸ごとの1行ハードコードが消える）。

**将来、この4テンプレートに収まらない計算が必要になった場合のみ、新テンプレートを1つ
コードで追加する。追加後はそのテンプレートも他の軸と同じくデータとして使い回せる。**

### 固定フィールド構造のdict化

- `RoutePreference` → `dict[axis_id, float]`（レジストリの既知axis_id集合に対する
  全件必須バリデーションは維持。API層の「省略時に既定値が黙って入るのを防ぐ」設計方針
  はそのまま活かせる）
- `AxisDifficulties` → `dict[axis_id, float | None]`
- `route_preference.yaml` → 既に実質dict形式のため変更不要
- `RouteSegmentDetail`の軸別フィールドも同様にdict化を検討

### レジストリの役割変更

現状`registry_defaults.py`はFastAPI本体から起動時に参照されず、フロント表示カタログ
（axis-catalog.json）の生成専用という状態（T12原則7の再検証で判明）。本設計では
**レジストリを実際の評価ロジックが参照する唯一の情報源へ昇格**させる。GUI編集を見据えると
最終的にはPythonファイルではなくDBテーブル化が必要（デプロイなしに軸を追加・編集できる
ようにするため）。

### UIオーバーライド層（見た目の磨き込み）

軸定義とは別の、任意の上書き設定として分離する:

```
AxisPresentationOverride {
  axis_id: str
  icon?: string           # 未指定ならshape単位の汎用アイコン（3〜4種）で代替
  chip_label?: str        # 未指定ならlabelの自動短縮
  hint_text?: str         # 未指定ならテンプレート単位の汎用文言テンプレート
}
```

`WeightPanel`のスライダー生成・`SECONDARY_AXES`の一覧生成は既にレジストリ駆動
（T25/T166の成果）のため、この層さえ用意すればフロントは新軸に無改修で追従できる。

## 段階移行案（ドラフト、未承認）

1. **Stage A**: 既存7軸を4テンプレートへ実装移行（ロジックは変えず表現だけを変える。
   既存の全評価テストが差し替え前後で一致することを回帰テストで保証してから内部を
   差し替える、T12と同じ「検証→境界→内部」の順）
2. **Stage B**: `RoutePreference`/`AxisDifficulties`/API層モデルをdict形式へ一般化
3. **Stage C**: レジストリ（Pythonファイルのまま）を実際の評価ロジックの参照元にする
4. **Stage D**: レジストリのDBテーブル化＋管理API（軸のCRUD）
5. **Stage E**: GUI編集画面（軸の追加・削除・並べ替え、重みスライダー、テンプレート選択）
   ※本ADRのスコープ外、別タスクとして起票する

## スコープ外・要検討事項（未決）

- **新しい計算テンプレートの追加は引き続きコード変更が必要**。これは妥当な線引きとして
  明示する（4テンプレートで今の全軸をカバーできている以上、際限のない汎用化は目指さない）。
- **新素材の追加は引き続きバックフィルが必要**（T12原則3どおり、変わらない）。
- **製品判断（未決、ユーザー判断待ち）**:
  - GUI編集を誰に開放するか（研究モード限定か、一般利用者にも見せるか）
  - 軸の追加・重み変更に伴う安全性・妥当性の検証（極端な重み設定でおかしなルートが
    出ないかの歯止めをどう設けるか）
  - Stage D（DB化）はT12 Part 2のインフラ選定（プロセス内グラフキャッシュ）との
    整合が要る——軸定義がリクエスト中に変わりうるなら、キャッシュの無効化条件に
    「軸定義の版数」も加える必要がある
- **T12との関係**: 独立した設計課題だが、Stage C以降でレジストリが実際に評価を駆動する
  ようになると、T218（探索の素材事前計算化）が扱う素材カタログと、本ADRの
  `AxisDefinition.materials`は同じカタログを指す必要がある（二重管理を避ける）。

## 決定状況

- **方向性（ロジック層は完全レジストリ駆動、見た目の磨き込みは独立したUIオーバーライド層
  として残す）** → **承認済み（2026-08-23）**
- Stage A〜Eの段階構成・具体的スキーマ・DB化の要否 → **未承認（ドラフトのまま）**
- 実装着手 → **ユーザーの明示指示待ち**

## Stage D実装（2026-08-24完了）

「スコープ外・要検討事項（未決）」の3点はユーザー判断で以下に確定した:

- GUI編集の開放範囲 → **研究モード限定**（Stage EのGUI自体は本Stageのスコープ外のまま）
- 極端な重み設定への歯止め → **型・範囲チェックのみ**（意味的な妥当性検証は追加しない）
- Stage D（DB化）とT12 Part 2キャッシュとの整合 → **軸定義の版数をキャッシュキーに含める**
  （実装は`axis_registry_meta.revision`として記録。ただしT12 Part 2の
  `graph_material_cache.py`は軸評価済みスコアを持たない設計のため実際には無効化が不要
  と判明し、revisionはプロセス内キャッシュ更新のポーリングには使わずpush型更新の記録用
  として持つのみに留めた——詳細下記）。

加えて、GUI編集を誰に開放するかとは別に「将来、研究モードを一般ユーザーから隠し何らかの
権限制御を導入する計画がある」という方針が示された（2026-08-24）。管理APIの認可を
「研究モードだから無認可でよい」という前提にしないよう、認可判定を1箇所（FastAPI
Dependency）へ集約し、共有トークンによる簡易実装から実権限チェックへ後から差し替え
られる設計にした。

### 実装内容

- **DB化**: `backend/migrations/0014_axis_definitions.sql`が`axis_definitions`
  （軸定義本体、`AxisShape`を`model_dump(mode="json")`したJSONBとして保存）・
  `axis_registry_meta`（版数、1行のみ）の2テーブルを追加し、既存7軸を
  `domain/axis_definitions.py`の内容そのままシードする。ORM
  （`infrastructure/axis_definition_models.py`）・リポジトリ
  （`infrastructure/axis_definition_repository.py`）は既存の`road_graph_repository.py`と
  同じ「書き込みはcommitしない、呼び出し側がまとめて確定する」規約に従う。
- **評価ロジックの読み出し方法は変えていない**: `AXIS_DEFINITIONS`は引き続き
  同期的なモジュールレベル辞書として`evaluation.py`/`difficulty.py`等から読まれる。
  `services/axis_registry_service.py: refresh_axis_definitions`が(1)アプリ起動時
  （`main.py`のlifespan）・(2)管理API書き込み直後、の2箇所だけで同じdictオブジェクトを
  in-place更新する「push型」設計にすることで、既存の同期アクセス箇所（Pydanticバリデータ
  含む）を一切変更せずに済ませた。単一プロセスデプロイという前提のもと
  `graph_material_cache.py`と同じ「プロセス単位、バージョン照合はしない」考え方を踏襲した
  ——結果として、当初想定していた「軸定義の版数をキャッシュキーに含める」対応は、
  実際にはT12 Part 2側のキャッシュ（軸評価済みスコアを持たない設計と判明）には不要で、
  `axis_registry_meta.revision`は将来のマルチプロセス化（ポーリング方式への切替）・監査用の
  記録としてのみ持つ形に落ち着いた。
  DB未接続・未migration・0行（migration未適用の可能性）の場合はWARNINGログを出し
  コード内蔵の既定値のまま動作を続けるため、**本migrationを本番へ適用するまでの間は
  評価の振る舞いが一切変わらない**（docs/improvement-plan.md T74「本番DBが置き去りになる」
  の教訓を踏まえた意図的な安全側ロールアウト）。
- **管理API**: `/api/admin/axis-definitions`（GET一覧・GET単体・POST作成・PUT更新・
  DELETE削除）。共有トークンheader（`X-Admin-Token`、`settings.axis_admin_token`、
  環境変数`AXIS_ADMIN_TOKEN`）で保護し、未設定（既定""）の環境では常に拒否する。
  「最後の1軸は削除できない」制約のみ構造的な歯止めとして持つ（重みの妥当性とは別次元、
  空レジストリは`refresh_axis_definitions`の0件フォールバックと衝突するため）。
- **axis-catalog.json（フロント）は変更していない**: CIの`api-contract`ジョブはDB接続を
  持たないため、`export_openapi.py`は引き続きPython内蔵の`AXIS_DEFINITIONS`から生成する。
  DB編集がこの生成物へ反映されるのはStage E以降の課題（CI側にDB接続を追加する判断とセット）。
- **検証**: backend全1126件green（新規37件含む）。dev DBへ実際に
  `0014_axis_definitions.sql`を適用し、シードされた7軸の内容が
  `domain/axis_definitions.py`のPython定義とバイト単位で一致すること、
  `refresh_axis_definitions`後の`AXIS_DEFINITIONS`が元の内容と一致すること（＝評価の
  振る舞いが変わらないこと）を実DBで確認した。OpenAPI再生成＋フロント型追従
  （`git diff`は`axis-catalog.json`を含む生成物のうちopenapi.json/api.d.tsのみ変化、
  axis-catalog.jsonは無変化）、`tsc --noEmit` green。
- **残作業（保留、影響範囲付き）**:
  1. **本番DBへのmigration適用**: 未実施。安全側フォールバック設計により適用が遅れても
     評価の振る舞いは変わらず、管理API（`/api/admin/axis-definitions`）が404相当
     （テーブル未作成でDBエラー）になるだけのため緊急度は低い。適用時は
     `AXIS_ADMIN_TOKEN`環境変数の設定も忘れないこと（未設定だと管理APIが常に403のまま）。
  2. **Stage E（GUI編集画面）**: 引き続き別タスクとして起票する（本ADRのスコープ外）。
