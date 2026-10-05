"""ルート探索が候補を選ぶときの判断の値（折返し点・復路・代替経路の選び方と、地点を寄せてよい距離）。"""

# --- フロンティア方式の折返し点選定・復路探索 ---
# 復路探索の間、往路Edge（＋同一Node対の逆方向Edge）のコストへ掛ける倍率。infにはしない
# （復路が往路を戻る以外に道が無い区間[袋小路等]は通れる必要がある）。
RETRACE_PENALTY_MULTIPLIER = 8.0
# 折返し点候補同士の最小距離（km）。近接Nodeは同じ周回の変種にしかならないため間引く。
MIN_TURNAROUND_SEPARATION_KM = 1.5
# 折返し点候補の往路同士の重複率（距離加重）の上限。同一コリドー上の候補が上位を独占し
# 往路の大半を共有する似た周回がn件並ぶのを防ぐ。プールが埋まらない場合は緩和値で再試行。
TURNAROUND_MAX_OVERLAP_RATIO = 0.6
TURNAROUND_RELAXED_OVERLAP_RATIO = 0.85
# 採用済み候補との周回全体（往路＋復路、進行方向無視）の重複率上限。
# 往路だけを見るTURNAROUND_MAX_OVERLAP_RATIOより緩め——「同じ周回の逆回り」（往路と復路が
# 入れ替わっただけ）や「往路は違うが復路が同じ裏道へ収束する」周回を弾くための、
# より緩い最終チェック。
LOOP_MAX_OVERLAP_RATIO = 0.7
# 周回全長／往路実距離の比の想定範囲。往路は軸コスト最適経路、復路はその往路を避けて探索
# するため、復路は往路と同程度以上に長くなる。上下限は解析的には決まらず、実分布から置く。
# リング（折返し候補の往路実距離の範囲）は、この比で周回全長が目標±許容に
# 収まるよう`[(目標-許容)/MIN, (目標+許容)/MAX]`に置く（許容が狭く範囲が反転する場合は
# `目標/2 ± 許容/2`へ戻す）。
LOOP_TO_OUTBOUND_RATIO_MIN = 2.0
LOOP_TO_OUTBOUND_RATIO_MAX = 2.3
# リング中心（タイブレーク「リング中心に近い順」の基準）の比率。上下限の単純平均ではなく
# 目標距離をこの比率で割った値を使う——許容が目標距離以上のとき下限が0でクランプされ、
# 上下限の算術平均だと中心が0付近まで引き下げられ極端に短い往路が上位に来るため。
RING_CENTER_RATIO = (LOOP_TO_OUTBOUND_RATIO_MIN + LOOP_TO_OUTBOUND_RATIO_MAX) / 2.0
# 候補選定（`pareto_layer_index`）で「実質同じ」とみなす距離の粒度。往路実距離200m
# （周回全長では約400m差、体感で選び分ける単位より細かい）。難易度の粒度は難易度の桁
# （`DIFFICULTY_QUANTUM`）。細かすぎると互いに非劣解な候補が全件残ってフィルタとして働かず、
# 粗すぎると候補が減りすぎる。
PARETO_DISTANCE_QUANTUM_M = 200.0

# --- 目的地ルート（via-node方式、経由地無し）の代替経路選定 ---
# via-node候補（前向き木＋後ろ向き木の合成経路）の長さが、最も合成コストの低い経路の
# 長さの何倍までを候補にするか。
ALTERNATIVE_MAX_STRETCH = 1.3
# 採用済み候補との経路全体（前向き＋後ろ向き）の重複率上限。TURNAROUND_MAX_OVERLAP_RATIO/
# TURNAROUND_RELAXED_OVERLAP_RATIOと同じ役割・同じ値を使う（周回の往路間引きと同じ
# 「同一コリドー上の候補を間引く」意図のため、値を変える理由が無い）。
VIA_NODE_MAX_OVERLAP_RATIO = TURNAROUND_MAX_OVERLAP_RATIO
VIA_NODE_RELAXED_OVERLAP_RATIO = TURNAROUND_RELAXED_OVERLAP_RATIO

#: 目的地が起点から到達できないとき、「到達できる最寄りNode」へ寄せてよい上限（km）。
#: 補正の狙いは、タップした先が本線から孤立した小塊だった場合にすぐ近くの本線へ移すこと
#: なので、それより遠くへ動かすと利用者が指した覚えのない場所を通るルートになる
#: （補正後の座標は`corrected_destination`として返すが、動いたことが分かっても
#: 指した場所とは別物である事実は変わらない）。
MAX_DESTINATION_CORRECTION_KM = 1.0
