# OSMのsurfaceタグ（自由記述に近い文字列）を「走行しやすい舗装路面か」で分類する。
# どちらにも属さないタグは不明（良い・悪いのどちらにも倒さない）。
#
# この2集合が路面語彙の単一ソースで、PostGIS側のMVT生成SQLもフロントの表示グループも
# ここへ追従する。タグを増減したらexport_openapi.py（surface-tags.jsonを書き出す）の
# 再実行と、フロントのグループ定義の追従が要る。
GOOD_OSM_SURFACE_TAGS = {
    "asphalt",
    "paved",
    "concrete",
    "paving_stones",
    "concrete:plates",
    "concrete:lanes",
    # チップシール（表面処理舗装）。ロードバイクで普通に走れる舗装。
    "chipseal",
    # レンガ舗装。paving_stonesと同様の平滑な舗装ブロック。
    "bricks",
}
BAD_OSM_SURFACE_TAGS = {
    "unpaved",
    "gravel",
    "dirt",
    "ground",
    "sand",
    "grass",
    "cobblestone",
    "sett",
    "compacted",
    "fine_gravel",
    "pebblestone",
    "mud",
    "woodchips",
    "earth",
    # 岩盤・粗い岩。ロードバイクでは走行困難。
    "rock",
    # 切り出していない粗い石畳。sett/cobblestoneと同等以下の走行性。
    "unhewn_cobblestone",
}


