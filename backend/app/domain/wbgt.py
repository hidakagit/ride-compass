"""環境省 熱中症予防情報サイトの暑さ指数（WBGT）警戒レベル判定（改善計画T174）。

閾値は環境省サイト掲載の「熱中症予防運動指針」（(公財)日本スポーツ協会「スポーツ活動中の
熱中症予防ガイドブック」2019、2026-08-22に https://www.wbgt.env.go.jp/wbgt.php で確認）を
典拠とする。サイクリングは運動のため、日常生活に関する指針（日本生気象学会）ではなく
運動指針を採用する。5段階のうち「ほぼ安全」（21未満）は警告として意味を持たないため、
バッジ表示の対象にしない（extreme以外は何も出さない、というWarningBadgeの一般原則に合わせる）。

暑さ指数（WBGT）は気温と同じ摂氏度で表されるが気温そのものではない値のため、環境省サイトの
表記に倣い単位（℃）を付けずに「暑さ指数」とだけ呼ぶ。
"""

from __future__ import annotations

from datetime import datetime

# 熱中症予防運動指針の閾値（暑さ指数の値、以上/未満の境界）。
# 21未満（ほぼ安全）はNoneを返す。
_LEVEL_THRESHOLDS: list[tuple[float, str, str]] = [
    (31.0, "emergency_warning", "危険"),
    (28.0, "severe_warning", "厳重警戒"),
    (25.0, "warning", "警戒"),
    (21.0, "advisory", "注意"),
]


def wbgt_level(value: float) -> tuple[str, str] | None:
    """暑さ指数の値から(levelキー, 表示名)を返す。21未満（ほぼ安全）はNone。"""
    for threshold, level, label in _LEVEL_THRESHOLDS:
        if value >= threshold:
            return level, label
    return None


# 提供期間（環境省サイトの運用期間、例年4月第4水曜〜10月第3水曜。年ごとに厳密な開始/
# 終了日が変わるため月単位の粗い判定に留める）。この判定は「無駄なAPI呼び出しを避ける」
# ための事前フィルタに過ぎず、正確性の最終防線ではない——月の境界（4月上旬・10月下旬）は
# 実際には提供期間外でも判定上は期間内に倒れるが、その場合はAPI呼び出し自体が失敗し、
# 呼び出し元（wbgt_service.py）のfail-open方針（取得失敗時は警告なし）により結果的に
# 「何も表示されない」という正しい見え方に収束する（T205と同じ考え方）。
PROVISION_START_MONTH = 4
PROVISION_END_MONTH = 10


def is_within_provision_period(at: datetime) -> bool:
    return PROVISION_START_MONTH <= at.month <= PROVISION_END_MONTH
