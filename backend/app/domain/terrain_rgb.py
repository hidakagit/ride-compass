"""MapLibreの`raster-dem`が読むTerrain-RGBの詰め方。

標高を-10000mを原点とする0.1m刻みの符号なし整数にして、1画素のRGBへ詰める。
"""

#: Terrain-RGBの刻みと原点。**画面が標高を読み戻す式の係数はここから決まる**
#: （生成物へ書き出す。画面が係数を直に持つと、詰め方を変えたとき黙ってずれる）。
TERRAIN_RGB_UNIT_M = 0.1
TERRAIN_RGB_BASE_M = -10000.0
