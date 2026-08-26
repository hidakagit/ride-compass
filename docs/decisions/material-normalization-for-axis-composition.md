# 材料の正規化と評価軸の合成に関する設計判断

ステータス: **検討完了・実装は未着手**（2026-08-26のユーザーとの議論で結論）。

## 背景

軸スタジオ（`/admin`）の「値ごとのスコアを設定」画面で、`highway`・`bicycle_infra`のような
`dtype="categorical"`材料の値をユーザーが自由入力する必要があり、「OSMのタグ生値を暗記
していないと使えない」という実機フィードバックを発端に調査した。

調査の過程で、より本質的な懸念が浮上した——**新しい生データソースを取り込むたびに、
`bicycle_infra`（`domain/traffic.py: classify_bicycle_infrastructure`）のような「複数の
タグを組み合わせて1つの分類値を作るPython関数」を都度書く必要があり、材料の数に比例して
Pythonコードが肥大化し続けるのではないか**、という懸念である（目論見書2章の層構造・
7章「材料の天井」が本来解消しようとしている問題そのもの）。

## 検証したこと

`material_catalog.py`の`dtype="categorical"`材料のうち、単一タグの生値をそのまま使う
もの（`highway`/`surface`/`smoothness`）とは別に、**複数のタグや複数の材料を組み合わせて
1つの分類値を作っているもの**が3つあった: `bicycle_infra`・`cycleway_class`・
`designation`。

これらの分類ロジック（優先順位付きif-elifチェーン）を、「正規化された複数の真偽値材料
＋線形結合（重み付き和）」で近似したときにどれだけ結果がズレるかを、dev機の実データ
（`osm_raw_ways` 86,642件、`designation_attributes`）で検証した。

| 材料 | 元ロジックの性質 | 優先順位方式と線形結合方式がズレるケース |
|---|---|---|
| `bicycle_infra` | 複数タグのOR条件＋1箇所AND条件（highway×bicycle） | 86,642件中11件（0.0127%） |
| `cycleway_class` | 複数タグのOR条件のみ | 86,642件中1件（0.0012%） |
| `designation`（"both"判定） | `is_ert`と`is_cl`のAND条件 | 8,223件中2,879件（**35.01%**） |

`bicycle_infra`/`cycleway_class`はズレがほぼ無視できる水準だった。一方`designation`の
"both"（緊急輸送道路と重要物流道路の両方に該当する道路）は、実データで3分の1以上を占める
**構造的に頻発するケース**で、線形結合では正確に近似できないことが分かった。

## 結論

1. **材料は生データに近い正規化された形（数値・真偽値・単純なOR判定）に統一する方針**
   とする。実際`material_catalog.py`の14材料中11は既にこの形になっており、複雑な
   組み合わせ分類を行っているのは`bicycle_infra`・`cycleway_class`・`designation`の
   3つだけだった。
2. **評価軸の合成は、既存の3プリミティブ（`CategoricalShape`/`BreakpointLinearShape`/
   `FlagSumShape`）だけで十分**という判断に至った。「優先順位付き条件分岐」を表現する
   新しいプリミティブ（`PriorityCondition`のAND対応拡張）を追加する案も検討したが、
   実データ検証の結果、正規化材料の線形結合による近似で評価目的には足りることが
   確認できたため見送る。目論見書7章「歯止め3: テンプレート4種の線引きを維持する」
   （新しい計算形はコード変更で追加する、GUIに際限のない汎用性を持たせない）とも
   整合する結論になった。
3. **地図表示用の人間向けカテゴリラベル（例: 自転車インフラの色分け凡例）は、評価軸の
   材料とは別レイヤーの関心事として、既存のPython分類ロジック・SQL CASE式
   （`_ROAD_SURFACE_TILE_MVT_SQL`）をそのまま維持してよい**。`staticAttributeLayers.ts`の
   凡例定義はMVTタイルの生プロパティを直接参照しており、評価軸側の材料選定とは独立した
   経路のため、評価軸側を変更しても地図表示には影響しない。
4. `designation`のようにAND条件が高頻度で発生する材料は、**評価軸としては単純化
   （種別を問わず一律加点）で十分**（実際、既存の`car_stress_designation_adjustment`
   内部軸は`is_designated`という既に単純化済みの真偽値材料を使っており、`designation`
   材料そのものは評価軸で未使用だった）。3値の分類自体は地図表示専用として残す。

## 現状の実装との乖離（2026-08-26時点）

`axis_definitions.py`の全軸を検査した結果、複雑な分類材料が実際に評価軸で使われている
箇所は**`car_stress_bicycle_infra_adjustment`内部軸が`bicycle_infra`材料を参照している
1箇所のみ**だった。`cycleway_class`・`designation`（3値）はどの軸からも参照されておらず、
軸スタジオの材料選択肢に現れるだけの未使用状態。つまり本方針と現状実装の乖離は
実質的にごく小さい。

## 未実施（今後の対応、着手は任意のトリガー待ち）

- ~~`car_stress_bicycle_infra_adjustment`を、`bicycle_infra`材料ではなく複数の正規化
  フラグ材料（例: `cycleway_has_track`/`cycleway_has_lane`/`cycleway_has_shared`/
  `highway_is_cycleway`等）の線形結合へ置き換える。~~ **改善計画T336で実施済み
  （2026-08-25）**。`domain/axis_definitions.py`の
  `_CAR_STRESS_BICYCLE_INFRA_FLAG_WEIGHTS`/`_CAR_STRESS_BICYCLE_INFRA_FLAG_BREAKPOINTS`
  参照。`bicycle_infra`材料自体は削除せず地図表示専用として維持している（本ドキュメント
  「結論」3参照）。cycleway/highway由来の判定（優先順位: track/highway=cycleway＞lane＞
  shared_busway等）は全数combinatorial検証でズレ0件、ズレが残るのは本ドキュメントが
  想定していたbicycle由来の分岐（shared_pedestrian・prohibitedのAND条件）のみ。
- `highway`/`surface`/`smoothness`のような本質的にオープンエンドな多値材料の
  「値の一覧とラベル」問題（当初の発端）は、この設計判断とは独立に対応する必要がある。
  対応案（DBから実データの値を動的取得＋既知の値にはラベルを付与、未知の値はタグ値
  そのまま表示）は本ドキュメント作成時点で未実装のまま。**改善計画T340で対応**
  （2026-08-25着手）。
- ~~`cycleway_class`材料の未使用状態（登録済みだが評価軸から未参照）を整理する。~~
  **改善計画T337で削除済み（2026-08-25）**。T336で追加した正規化フラグ材料
  （`cycleway_has_track`等）が同じcycleway系タグをより細かい粒度で既にカバーしており、
  正規化フラグ化して評価軸で使えるようにする案（本ドキュメントが検証した0.0012%の
  近似ズレ）は屋上屋になるため見送った。地図表示側でも未使用（`bicycle_infra`のみが
  表示に使われている）と判明したため、MVTタイルのプロパティごと削除した
  （`ROAD_SURFACE_TILE_VERSION`対上げ）。
- `designation`材料（3値カテゴリ）の未使用状態の整理は**改善計画T338で対応済み
  （2026-08-25・2026-08-26フォローアップ）**。当初"both"のAND条件の構造的頻発[35.01%]を
  理由に「3値のまま`display_only`で軸スタジオから隠すだけ」で済ませたが、これは本文書
  「結論」1-2（材料は正規化された形に統一する方針、bicycle_infra/cycleway_classの
  「複雑な分類の生値＋正規化フラグの併存」パターン）と食い違う対応だったため、
  ユーザー指摘を受け`designation`も分解した。3値へ畳み込む前の生フラグを
  `is_emergency_transport`[N10該当]・`is_critical_logistics`[N12該当]という正規化された
  真偽値材料として新設し（`cycleway_class`のように削除するのではなく、`bicycle_infra`の
  ように併存させる——`designation`は地図表示で実際に使われている生きたデータのため）、
  軸スタジオで選択可能にした。"both"のAND条件そのものへの対応（本文書が検証した知見）は
  変わらず有効: 評価軸としての単純化（`is_designated`、種別を問わず一律加点）は維持し、
  種別を区別する評価軸を実際に作りたいユーザーが現れるまでextractorの配線はDEFERする。

## 参照

- `RideCompass 目論見書`（Artifact、2026-08-24承認・2026-08-25追記）2章「中核思想」・
  7章「設計上の歯止め」
- [t221-axis-registry.md](t221-axis-registry.md)（4テンプレート化の経緯、「新しい計算
  テンプレートの追加は引き続きコード変更が必要」の方針）
- `backend/app/domain/material_catalog.py`・`backend/app/domain/axis_definitions.py`
  （T280、材料抽出フェーズの宣言駆動化）
