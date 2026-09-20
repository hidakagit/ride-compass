# 標高（backend）

## 責務

国土地理院のDEMタイルから標高を取り、道の勾配を出す。取込・派生・経路の集計の3段に
分かれており、**実行時に国土地理院へ問い合わせる経路は持たない**。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `attributes.py`（`ElevationValues`・`compute_elevation_values`） |
| services | `elevation_aggregation.py` |
| batch | `source_adapters/gsi_dem_tile.py`（取込。タイルのURL・形式・欠測の記法・製品の優先順を持つ）・`source_adapters/_raster_wkb.py`（画素の並びをPostGISの`raster`へ包む）・`derive_raster_materials.py`（派生） |

## 3段に分かれている

```
国土地理院 DEMタイル（テキスト、256×256）
   │ source_adapters/gsi_dem_tile.py: int32へ詰めてタイル1枚=1行
   ▼
source_features(source='dem')          ← 生データ。取り直さない限り変わらない
   │ derive_raster_materials.py: 区間の形状点で標高を読み、勾配を出す
   ▼
edge_materials（start/end・gain/loss・average/max/min）
   │ 探索フェーズが材料として読む（road_graph_repository.py）
   ▼
経路の集計（elevation_aggregation.py）
```

値の出し方そのものは`domain/attributes.py: compute_elevation_values`が持つ。派生バッチは
画素を読んで渡すだけで、上限も欠測の扱いもそこには無い。

## 勾配を出さない区間

`average_grade`がNULLなのは「まだ計算していない」だけではない。次の2つは、計算したうえで
**値を持たせない**と決めた区間である。

- **舗装公道としてありえない急勾配**（`MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT`）。道の起伏では
  なくDEMの読み違いで、丸めても上限で切っても直らない。
- **橋・高架・トンネル**。DEMが返すのは地表面の標高で、桁や坑道の高さではない——谷を渡る橋
  なら谷底の起伏を、山を抜けるトンネルなら山の起伏を、そのまま道の勾配として受け取る。
  **測り間違いではなく別のものを測っている**ため、値の側では直せない。

どちらも標高そのもの（start/end・gain/loss）は残す。0次ハードフィルタは値の無い区間を
除外しない（`domain/hard_filters.py`）ため、誤った値で黙って経路から外すより安全側になる。

この列のNULLは鮮度台帳で「未計算」として数えない（`derived_models.py: ABSENT_OK`）。

## 欠測点の扱い

標高が読めなかった点は除外して評価する。**除外後に隣り合う2点でも、元の点列では間に
欠損点を挟んでいることがある**——そのまま隣接扱いすると、欠損区間の実際の起伏が均された
平均勾配として混入する。距離（両点とも既知なので常に正確）と、獲得/喪失・勾配（欠損を
挟むと信頼できない）を分けて積む。

整備区域外のタイルは配信元が404を返す。取込はそのタイルを行として作らないため、そこに
落ちる区間は標高を持たない——「試したが値が無い」と「まだ試していない」は、タイルの行が
在るかどうかで区別できる。

## 向きと標高

区間は向きを持たない1行で、標高も順方向の値だけを持つ。逆向きは読み出し時に導く
（始点↔終点、上り↔下り、平均勾配は符号反転、最大↔最小は入れ替えて符号反転）。地形の
物理量は進行方向に依存しないため、この変換は厳密に正しい。変換はSQLが行う
（`road_graph_repository.py: _REVERSED_ELEVATION_COLUMNS`）ので、材料の式も評価も向きを
知らない。

## 経路の集計（`elevation_aggregation.py`）

確定した経路の区間ぶんの値から、累積標高・最大勾配などを組み立てる。区間の値は探索
フェーズで読んだ材料がそのまま持っているため、ここでDBへ問い合わせ直さない。

## タイルの読み方（`batch/source_adapters/gsi_dem_tile.py`）

配信元のURL・製品の優先順（細かい製品が全域を覆わないため粗い側へ落ちる）・欠測の記法を
持つ。取込だけが使い、web側は読まない。ズームは`source_profile.yaml`が持つ。
