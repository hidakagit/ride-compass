"""ORMモデルが共有する宣言の基点。

**表の形の宣言はORMモデル1か所に置く**（正本は実DBで、この宣言は「あるべき姿」）。
実DBとの一致は`backend/scripts/schema_gap.py`が測る。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
