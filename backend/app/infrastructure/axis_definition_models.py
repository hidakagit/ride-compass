"""評価軸定義のPostGISスキーマ（SQLAlchemy ORM）。

軸定義（domain/axis_definitions.py: AxisDefinition）の正本はこのテーブルで、コードは
写しを持たない。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
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
    __table_args__ = {"info": IRREPLACEABLE}

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
    # 地図チップの表示要素。未設定はフロント側の汎用フォールバックに委ねるため、
    # `[]`ではなくNoneがそのまま「未設定」の意味を持つ。
    icon_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chip_label: Mapped[str | None] = mapped_column(String, nullable=True)
    panel_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    # falseなら地図上チップ・地図の見え方パネルの両方からこの軸を丸ごと除外する。
    show_map_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    time_scope: Mapped[str] = mapped_column(String, nullable=False, server_default="always")
    display_thresholds_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    display_band_labels_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dedicated_way_value_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # dedicated_way_value_layer=trueの軸だけが意味を持つ。
    dynamic_way_value_needs_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dynamic_way_value_needs_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dynamic_way_value_needs_speed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
