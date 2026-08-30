# 軸スタジオ管理画面（frontend）

## 責務

管理者向け（Basic認証保護下）の評価軸CRUD画面。一覧・作成・編集・複製・削除・
非公開化の状態管理を行い、[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)
のAPIをそのまま呼ぶ。

**対象ファイル**

| ファイル | 行数 | 責務 |
|---|---|---|
| `components/AxisStudio/AxisStudio.tsx` | 278 | トップレベル。一覧取得・作成/更新/削除/複製/非公開化の状態管理 |
| `components/AxisStudio/AxisComposer.tsx` | 1392 | 4ステップウィザードのフォーム本体 |
| `services/axisAdminApi.ts` | | backend `axis_admin.py`への薄いHTTPラッパー（`listAxisDefinitions`・`createAxisDefinition`・`updateAxisDefinition`・`deleteAxisDefinition`・`unpublishAxisDefinition`） |

## AxisStudio.tsx（一覧・状態管理）

```
listAxisDefinitions() ──→ definitions（全軸）
                              │
              ┌───────────────┼────────────────┐
              ▼                                ▼
      下書きタブ（is_published=false）   公開済みタブ（is_published=true）
      編集・複製・削除ボタン             複製・非公開化ボタンのみ
```

- 下書きタブが既定表示（新規作成した軸はまず下書きから始まるため）。
- 公開済みタブは編集・削除ボタン自体を出さない（backendの`AxisPublishedImmutableError`と
  対応。改良は「複製して新規作成」、削除は先に「非公開に戻す」という導線）。
- 削除前チェック: `axesReferencing(axisId, definitions)`が、削除しようとしている軸を
  他の軸が材料として参照していないか調べ、参照があれば確認ダイアログで警告する
  （一律拒否はしない、最終判断はユーザーに委ねる）。
- 最後の1軸は削除ボタンを無効化する。
- 編集・複製・新規作成はいずれもモーダル（`components/ui/Dialog`）で`AxisComposer`を開く。

## AxisComposer.tsx（4ステップウィザード）

| Step | 見出し |
|---|---|
| `basic` | 基本情報 |
| `shape_kind` | 点数のつけ方を選ぶ |
| `shape_params` | 点数の詳細を設定 |
| `display_publish` | 地図表示・公開 |

ステップ自体の追加・削除はコード変更を要する（動的ステップ化は目指さない設計判断）。

### `shape_kind`ステップの3カード（フロントUI専用の分類）

| カード | 説明 | backend `AxisShape.kind`への対応 |
|---|---|---|
| なめらか評価 | 数値の大きさ・複数要素の有無で点数を変える | `breakpoint_linear` |
| ぴったり評価 | はい/いいえ、種類ごとに点数を決める | `categorical` |
| かけあわせ評価 | 既にある軸のスコアに重みを掛けて合計する | `breakpoint_linear`（他axis_idをmaterialとして参照、折れ点編集UIは出さない） |

**フロント側の`ShapeKind`型（`"breakpoint_linear" | "recipe_then_breakpoint_linear" |
"categorical"`）は3種のUIカードの選択肢であり、backendの`AxisShape`型（2プリミティブ:
`BreakpointLinearShape` | `CategoricalShape`）とは別の型**——「かけあわせ評価」カードも
最終的には`BreakpointLinearShape`を組み立てる（`buildShape(draft, materialOptions)`）。

## 材料説明ポップオーバー

`InfoPopoverButton`/`MaterialInfoButton`が、材料選択欄の隣に(ⓘ)アイコンを置き、
backend `material_catalog.py: MaterialSpec.description`をポップオーバー表示する
（`useMaterialCatalog`フック経由で取得、[静的道路属性（backend）](../backend/static-road-attributes.md)
とは別の[評価・スコアリング（backend）](../backend/evaluation-scoring.md)の材料カタログAPI）。
