"""評価軸定義のPostGISスキーマ（SQLAlchemy ORM、改善計画T221 Stage D）。

軸定義（domain/axis_definitions.py: AxisDefinition）をDBの唯一の情報源へ昇格させる
（ADR: docs/decisions/t221-axis-registry.md）。DBの起動時初期化（create_tablesの
Base.metadata.create_all）に乗せるため同じBaseを使う（accident_models.py等と同じ規約）。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.road_graph_models import Base


class AxisDefinitionRow(Base):
    """1つの評価軸の永続化行。

    sort_orderは合成（composite）の加算順として意味を持つ（domain/axis_definitions.pyの
    AXIS_DEFINITIONSコメント参照、Neumaier加算のビット一致条件のため）。shape_paramsは
    domain/axis_definitions.pyのAxisShape（Pydantic Union）を`model_dump(mode="json")`した
    内容そのもの（infrastructure/axis_definition_repository.py参照）。
    """

    __tablename__ = "axis_definitions"

    axis_id: Mapped[str] = mapped_column(String, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    shape_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    default_weight: Mapped[float] = mapped_column(Float, nullable=False)
    # 改善計画T269: 一般向けルート設定画面（RouteSettingsPanel）がGET /api/axis-catalog
    # 経由で表示する表示名・説明・分類（観測/推定/動的）。0015 migrationでNOT NULL
    # DEFAULT付きの追加カラムとして導入した（既存7行は同migrationでbackfill済み）。
    label: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(String, nullable=False, server_default="推定")
    # 改善計画T271: 公開済み軸は不変（管理APIが更新・削除を拒否する）。0016 migrationで
    # NOT NULL DEFAULT trueの追加カラムとして導入した（既存7行[本番稼働中]は
    # 全て公開済み扱いとしてbackfillした。既定trueは移行時の安全側の値であり、
    # アプリ層[domain/axis_definitions.py: AxisDefinition.is_published]の新規作成時の
    # 既定はFalse=下書きが正）。
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AxisRegistryMetaRow(Base):
    """軸レジストリ全体の版数（1行のみ、id=1固定）。

    管理API（api/routers/axis_admin.py）の書き込みごとにインクリメントする。将来の
    マルチプロセス対応・監査用の記録で、現時点ではプロセス内キャッシュの無効化には使わない
    （services/axis_registry_service.pyのdocstring参照）。
    """

    __tablename__ = "axis_registry_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
