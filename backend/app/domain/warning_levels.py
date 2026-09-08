"""警戒度バッジ（`WarningBadge`）の4段階語彙の正準定義。

JMA警報・WBGT・河川氾濫予報は、判定の根拠（警報名・暑さ指数・氾濫危険レベル）は
まったく別だが、画面に出すバッジの**段階**は共通の4語彙で表す。値をそれぞれのモジュールへ
コピーすると、5段階目の追加や表記ゆれが「片方だけ直る」形で入り込む——frontend側は
未知の語彙をどの段階とも判定できず、実際より軽い警戒度として静かに扱う。
"""

from typing import Literal, get_args

# 昇順（軽い→重い）。frontend側の順序（`WarningBadge.tsx: LEVEL_ORDER`）と一致させる。
WarningBadgeLevel = Literal["advisory", "warning", "severe_warning", "emergency_warning"]

WARNING_BADGE_LEVELS: tuple[WarningBadgeLevel, ...] = get_args(WarningBadgeLevel)
