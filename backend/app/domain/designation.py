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

# 取込対象kind（N10=emergency_transport/N12=critical_logistics）。import_designations.py・
# match_designations.pyの両バッチがこのタプルをimportして参照する（改善計画T75。以前は
# 各バッチが独自にリテラルタプルを持ち、kind追加時の編集漏れが静かに壊れる構造だった）。
# 順序はKANTO_PREFECTURE_CODES_KSJと同じくN10→N12の登場順（ログ・dry-run出力の安定順）。
DESIGNATION_IMPORT_KINDS: tuple[str, ...] = ("emergency_transport", "critical_logistics")

# trafficStress補正（+1）の対象となるkind。現状はDESIGNATION_IMPORT_KINDSと同一集合だが、
# 「取込対象か」と「trafficStress加点対象か」は概念的に別の軸（将来ナショナルサイクルルート等
# 加点なしのkindを追加する可能性がある）のため、別定数として保持する。
# SQL側（road_graph_repository.py: get_designated_edge_ids等のバインド配列）と
# Python側（traffic_stress_level呼び出し元）の両方がこの集合を参照する。
# 注意: `_ROAD_SURFACE_TILE_MVT_SQL`（MVTタイル生成、road_graph_repository.py）内の
# designation CASE式はis_ert/is_clの2列固定でこの集合を直接バインドしていない
# （2kind固定の設計。3kind目を追加する場合はSQLの構造自体の見直しが必要）。
# tests/test_road_graph_repository.pyのドリフト検知テストがこの集合とSQLの2値を突き合わせる。
TRAFFIC_STRESS_DESIGNATION_KINDS = frozenset(DESIGNATION_IMPORT_KINDS)

# 改善計画T74（2026-08-16実装）: designation_attributesのマッチング対象は当初road_edges
# （ルート生成地点周辺のみ遅延構築）だったが、route_designationsが関東全域投入済みなのに
# 表示がルート生成履歴のあるエリアに限られる不具合（road_edges遅延構築依存）の根本対応として
# osm_raw_ways（全域自己完結）基準へ変更した。副作用として評価粒度もedge単位any-matchから
# way単位ratio-matchへ統一される。トレードオフ: 長いwayの一部だけが実際に指定路線と重なる
# ケースでは、way全長に対する交差比率がDESIGNATION_MATCH_MIN_RATIO未満だとway全体が
# 非該当になる（従来のedge単位判定では、重なる部分のedgeだけ正しく検出できていた）。
# どちらが多く発生するかはOSM way分割粒度（交差点でどれだけ細かく切れているか）次第で、
# 無条件の改善ではなくトレードオフとして残る。
