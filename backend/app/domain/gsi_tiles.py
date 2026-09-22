"""国土地理院タイルの製品ごとの事実（実データを持つ範囲・上流のパス・出典表記）。

画面が写しを持つと、上限を片側だけ広げたときに黙ってタイルが出なくなる（例外にならない）。
出典表記は利用条件の一部で、データを取りに行く側が持つ。
"""

_API_PREFIX = "/api"

#: 色別標高図。上流のパスと、配信元が実データを持つ上限。
RELIEF_UPSTREAM_PATH = "xyz/relief/{z}/{x}/{y}.png"
RELIEF_MAX_ZOOM = 15
RELIEF_ROUTE = f"{_API_PREFIX}/gsi-relief-tile/{{path:path}}"
#: 画面が要求するURL。ルートの接頭辞と上流のパスから決まる（別々に書かない）。
RELIEF_TILE_URL = f"{_API_PREFIX}/gsi-relief-tile/{RELIEF_UPSTREAM_PATH}"
RELIEF_ATTRIBUTION = (
    '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank"'
    ' rel="noreferrer">地理院タイル(色別標高図)</a>'
)

#: 標高タイル（DEM10B、10mメッシュ）。配信元が実データを持つのはz14まで。
TERRAIN_UPSTREAM_PATH = "xyz/dem_png/{z}/{x}/{y}.png"
TERRAIN_MIN_ZOOM = 2
TERRAIN_MAX_ZOOM = 14
#: 変換して配るため、上流のパスではなく自前のルートを持つ。
TERRAIN_TILE_URL = f"{_API_PREFIX}/gsi-terrain-tile/{{z}}/{{x}}/{{y}}.png"
TERRAIN_ROUTE = TERRAIN_TILE_URL
