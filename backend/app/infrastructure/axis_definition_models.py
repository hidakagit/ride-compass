"""評価軸定義のPostGISスキーマ（SQLAlchemy ORM）。

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
    # 一般向けルート設定画面（RouteSettingsPanel）がGET /api/axis-catalog
    # 経由で表示する表示名・説明・分類（観測/推定/動的）。
    label: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(String, nullable=False, server_default="推定")
    # 公開済み軸は不変（管理APIが更新・削除を拒否する）。
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # 0次条件（PriorityCondition）のリスト。domain/axis_definitions.py:
    # AxisDefinition.priority_overridesを`model_dump(mode="json")`したJSON配列。
    priority_overrides: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # 地図チップ表示要素（軸自身のデータとして持つ）。未設定はフロント側の汎用
    # フォールバックに委ねるため、priority_overridesのような`[]`既定は不要——
    # Noneがそのまま「未設定」の意味を持つ。
    icon_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chip_label: Mapped[str | None] = mapped_column(String, nullable=True)
    panel_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    # falseなら地図上チップ・地図の見え方パネルの両方からこの軸を丸ごと除外する。
    show_map_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # axis_idハードコード分岐を性質ベースの宣言的フィールドへ汎用化したもの。
    time_scope: Mapped[str] = mapped_column(String, nullable=False, server_default="always")
    # 地図の色分けしきい値だけを差し替える軽量な上書き（domain/
    # axis_definitions.py: AxisDefinition.display_thresholds_overrideのdocstring参照）。
    # 未設定はderive_ramp_inputsが計算したしきい値をそのまま使う。
    display_thresholds_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # display_thresholds_overrideと対になる、段階ごとの体感ラベルの軽量な
    # 上書き（domain/axis_definitions.py: AxisDefinition.display_band_labels_overrideの
    # docstring参照）。未設定は数値レンジ表記のみの凡例になる。
    display_band_labels_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 専用のway_id→値配信レイヤー（Redis経由、app/infrastructure/dynamic_way_value_cache.py）
    # を持つかの宣言（domain/axis_definitions.py: AxisDefinition.dedicated_way_value_layerの
    # docstring参照）。
    dedicated_way_value_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # dedicated_way_value_layer=trueの軸のみ意味を持つ、GET /api/region/
    # dynamic-way-values/{material_id}/...のat/bearing_degクエリパラメータ必須判定
    # （domain/axis_definitions.py: AxisDefinition.dynamic_way_value_needs_time/
    # dynamic_way_value_needs_bearingのdocstring参照）。
    dynamic_way_value_needs_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dynamic_way_value_needs_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dynamic_way_value_needs_speed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # create_tables()（Base.metadata.create_all）が先に走る「まっさらなDBから
    # のブートストラップ」経路では、DB側のserver_defaultが無いとmigrationのINSERT
    # （updated_atを指定しない）がNOT NULL制約違反になるため、server_defaultを持つ。
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class AxisRegistryMetaRow(Base):
    """軸レジストリ全体の版数（1行のみ、id=1固定）。

    管理API（api/routers/axis_admin.py）の書き込みごとにインクリメントする。将来の
    マルチプロセス対応・監査用の記録に加え、`infrastructure/tile_score_matrix_cache.py:
    sync_disk_cache_with_axis_revision`が、アプリ起動のたびに呼ばれる`refresh_axis_
    definitions`から見て軸定義が実際に変わったかどうかの判定にも使う
    （services/axis_registry_service.pyのdocstring参照）。migration 0014が初期行
    （id=1, revision=1）を投入する——この行を経由しない環境（`Base.metadata.create_all`の
    みのテストDB等）では`get_revision()`がNoneを返し、安全側（常に無効化）へ倒れる。
    """

    __tablename__ = "axis_registry_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
