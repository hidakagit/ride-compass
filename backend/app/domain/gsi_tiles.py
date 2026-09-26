"""国土地理院タイルの製品ごとの事実（実データを持つ範囲・上流のパス・出典表記）。

画面が写しを持つと、上限を片側だけ広げたときに黙ってタイルが出なくなる（例外にならない）。
出典表記は利用条件の一部で、データを取りに行く側が持つ。中継するルートと画面が要求するURLは、
受ける層（`api/routers/gsi_tile.py`）がここの上流のパスから導く。
"""

#: 色別標高図。上流のパスと、配信元が実データを持つ上限。
RELIEF_UPSTREAM_PATH = "xyz/relief/{z}/{x}/{y}.png"
RELIEF_MAX_ZOOM = 15
RELIEF_ATTRIBUTION = (
    '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank"'
    ' rel="noreferrer">地理院タイル(色別標高図)</a>'
)

#: 標高タイル（DEM10B、10mメッシュ）。配信元が実データを持つのはz14まで。
TERRAIN_UPSTREAM_PATH = "xyz/dem_png/{z}/{x}/{y}.png"
TERRAIN_MIN_ZOOM = 2
TERRAIN_MAX_ZOOM = 14
