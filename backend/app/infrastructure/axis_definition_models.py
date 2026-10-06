"""評価軸定義のPostGISスキーマ（SQLAlchemy ORM）。

軸定義（domain/axis_definitions.py: AxisDefinition）の正本はこのテーブルで、コードは
写しを持たない。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import IRREPLACEABLE, Base


class AxisDefinitionRow(Base):
    """1つの評価軸の永続化行。

    sort_orderは合成（composite）の加算順として意味を持つ（Neumaier加算のビット一致条件）。
    shape_paramsは`domain/axis_definitions.py`のAxisShape（Pydantic Union）を
    `model_dump(mode="json")`した内容そのもの。
    """

    __tablename__ = "axis_definitions"
    __table_args__ = (
        UniqueConstraint("sort_order", name="axis_definitions_sort_order_key"),
        {"info": IRREPLACEABLE},
    )

    axis_id: Mapped[str] = mapped_column(String, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    shape_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    default_weight: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(String, nullable=False, server_default="推定")
    # 公開済み軸は不変（管理APIが更新・削除を拒否する）。
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    priority_overrides: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # 未設定はフロント側の汎用のアイコンに委ねるため、空文字ではなくNoneが「未設定」の意味を持つ。
    icon_id: Mapped[str | None] = mapped_column(String, nullable=True)
    time_scope: Mapped[str] = mapped_column(String, nullable=False, server_default="always")
    display_thresholds_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    display_band_labels_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dedicated_way_value_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
