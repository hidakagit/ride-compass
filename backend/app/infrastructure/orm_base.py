"""ORMモデルが共有する宣言の基点。

**表の形の宣言はORMモデル1か所に置く**（正本は実DBで、この宣言は「あるべき姿」）。
実DBとの一致は`backend/scripts/schema_gap.py`が測る。
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: 表の`info`に付ける印（`__table_args__ = {"info": IRREPLACEABLE}`）。外部から取り直せず、派生からも
#: 作り直せない表（人が管理画面で積み上げた行）であることを宣言する。バックアップ
#: （`scripts/admin_data_dump_args.py`）が書き出す母集団はこの印から導く。
IRREPLACEABLE_KEY = "irreplaceable"
IRREPLACEABLE = {IRREPLACEABLE_KEY: True}

#: 表の`info`に付ける印（`__table_args__`の最後に`{"info": DERIVED}`）。生データから作り直す派生の表であることを
#: 宣言する。派生の作り直し（`batch/derive_cli.py`）が作業用のスキーマへ写す表と、鮮度台帳
#: （`derived_data_freshness.py`）が数える表は、この印から導く。
DERIVED_KEY = "derived"
DERIVED = {DERIVED_KEY: True}


class Base(DeclarativeBase):
    pass


def declared_metadata() -> MetaData:
    """ORMが宣言する全表を載せた`Base.metadata`。

    `Base.metadata`には**importしたモジュールの表しか載らない**。全表を見る側（スキーマの作成・
    実DBとの突き合わせ・バックアップ）は、呼び出し側のimport次第で表が静かに欠けないよう、ここを通す。
    """
    from app.infrastructure import (  # noqa: F401
        axis_definition_models,
        derived_data_meta,
        derived_models,
        source_models,
        tuning_overrides,
    )

    return Base.metadata
