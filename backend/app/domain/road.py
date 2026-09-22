# OSMのsurfaceタグ（自由記述に近い文字列）を「走行しやすい舗装路面か」で分類する。
# どちらにも属さないタグは不明（良い・悪いのどちらにも倒さない）。
#
# **1つの表で宣言し、集合はそこから導く**——良い側と悪い側を別々に並べると、同じタグを
# 両方へ書いたときにそのタグが良くも悪くもある状態になり、どちらで塗られるかは読む側の
# 評価順で決まる。表なら1つのタグに1つの判定しか書けない。
#
# この表が路面語彙の単一ソースで、PostGIS側のMVT生成SQLもフロントの表示グループも
# ここへ追従する。タグを増減したらexport_openapi.py（surface-tags.jsonを書き出す）の
# 再実行と、フロントのグループ定義の追従が要る。
_SURFACE_IS_GOOD: dict[str, bool] = {
    "asphalt": True,
    "paved": True,
    "concrete": True,
    "paving_stones": True,
    "concrete:plates": True,
    "concrete:lanes": True,
    # チップシール（表面処理舗装）。ロードバイクで普通に走れる舗装。
    "chipseal": True,
    # レンガ舗装。paving_stonesと同様の平滑な舗装ブロック。
    "bricks": True,
    "unpaved": False,
    "gravel": False,
    "dirt": False,
    "ground": False,
    "sand": False,
    "grass": False,
    "cobblestone": False,
    "sett": False,
    "compacted": False,
    "fine_gravel": False,
    "pebblestone": False,
    "mud": False,
    "woodchips": False,
    "earth": False,
    # 岩盤・粗い岩。ロードバイクでは走行困難。
    "rock": False,
    # 切り出していない粗い石畳。sett/cobblestoneと同等以下の走行性。
    "unhewn_cobblestone": False,
}

GOOD_OSM_SURFACE_TAGS = {tag for tag, good in _SURFACE_IS_GOOD.items() if good}
BAD_OSM_SURFACE_TAGS = {tag for tag, good in _SURFACE_IS_GOOD.items() if not good}
