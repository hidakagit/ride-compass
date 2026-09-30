"""自前で作って配るタイルのメディアタイプ。

作る側（キャッシュへ書く`content_type`）・配る側（応答ヘッダ）・gzipの対象の判定が同じ値を読む
——別々に持つと、片方だけ変えたときにキャッシュキー（content_type込み）と応答ヘッダがずれる。
外部から取ってそのまま返すタイルは、配信元が返した値を使う（ここの値で上書きしない）。
"""

# MVT（Mapbox Vector Tile）。
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"
# ラスタタイル（土地被覆・Terrain-RGB）。
PNG_CONTENT_TYPE = "image/png"
