"""本番DBの数を「注意が要るか」へ読む判断。

しきい値そのものより「なぜその値か」が重要なため、定数ごとに根拠を書く。
"""

#: `idle in transaction`がこれより長く続いていれば注意。放置されたトランザクションは
#: VACUUMが古い行を回収するのを止め、テーブルを肥大化させる。冷えた状態のルート生成でも
#: 数分で終わるため、正常な処理がこの長さを超えることは無い。
IDLE_TRANSACTION_WARN_SECONDS = 600.0

#: 接続数がmax_connectionsのこの割合を超えたら注意（残り枠が尽きると新規接続が失敗する）。
CONNECTION_USAGE_WARN_RATIO = 0.8

#: 不要行（dead tuple）が行全体のこの割合を超えたら注意。VACUUMが追いついていない。
DEAD_TUPLE_WARN_RATIO = 0.2

#: 統計が無いことを注意として出す行数の下限。これを下回るテーブルは、プランナが行数を
#: どう推定しても全走査で足りるため実行計画が変わらない——注意を出しても打つ手が無い。
STATISTICS_WARN_MIN_ROWS = 10_000

#: 不要行を注意として出す絶対数の下限。割合だけで見ると、行数の少ないテーブルが常に注意に
#: なるが、回収できる容量が無く行動につながらない。
DEAD_TUPLE_WARN_MIN_ROWS = 1_000


def table_attention(row_count: int, dead_tuples: int, *, analyzed: bool) -> list[str]:
    """テーブル1つの注意の理由。空なら注意は要らない。"""
    reasons: list[str] = []
    if not analyzed and row_count >= STATISTICS_WARN_MIN_ROWS:
        reasons.append(
            "統計を一度も取っていない（プランナの行数推定が実数から外れ、クエリが遅いプランを選びうる）"
        )
    live = max(row_count, 1)
    dead_ratio = dead_tuples / (live + dead_tuples)
    if dead_tuples >= DEAD_TUPLE_WARN_MIN_ROWS and dead_ratio > DEAD_TUPLE_WARN_RATIO:
        reasons.append(f"不要行が{dead_tuples:,}件（VACUUMが追いついていない）")
    return reasons


def connection_attention(total: int, max_connections: int, longest_idle_transaction_seconds: float) -> list[str]:
    """接続の注意の理由。空なら注意は要らない。"""
    reasons: list[str] = []
    if longest_idle_transaction_seconds > IDLE_TRANSACTION_WARN_SECONDS:
        minutes = longest_idle_transaction_seconds / 60
        reasons.append(
            f"開いたまま放置されたトランザクションが{minutes:.0f}分（VACUUMが古い行を回収できず肥大化する）"
        )
    if max_connections and total / max_connections > CONNECTION_USAGE_WARN_RATIO:
        reasons.append(f"接続が{total}/{max_connections}（残り枠が尽きると新規接続が失敗する）")
    return reasons
