"""指定路線コンフレーション機構の正準定数（外部静的データソース T51、パターンD初回実装。
docs/external-data-sources-review-2026-08-16.md §4.3）。

線データ（KSJ N10/N12等）をroad_edgesへ対応付ける際のバッファ幅・閾値をここへ集約する。
`app/batch/match_designations.py`（マッチング計算）と評価組み込み側（traffic_stress_level
呼び出し元）の両方がこの定数を参照する（domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと
同じ「片側import」原則、改善計画T44）。
"""

# Edgeジオメトリをこの幅（メートル）でバッファした範囲との交差長比でマッチ判定する。
DESIGNATION_BUFFER_WIDTH_M = 20.0

# バッファ内交差長 / Edge全長 がこの割合以上ならマッチとみなす。
DESIGNATION_MATCH_MIN_RATIO = 0.5

# trafficStress補正（+1）の対象となるkind（N10/N12のみ。ナショナルサイクルルートは
# 今回未実装のためkind自体が投入されない）。SQL側（MVT生成のバインド配列）と
# Python側（traffic_stress_level呼び出し元）の両方がこの集合を参照する。
TRAFFIC_STRESS_DESIGNATION_KINDS = frozenset({"emergency_transport", "critical_logistics"})
