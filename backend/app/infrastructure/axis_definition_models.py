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
    # 改善計画T292: 0次条件（PriorityCondition）のリスト。domain/axis_definitions.py:
    # AxisDefinition.priority_overridesを`model_dump(mode="json")`したJSON配列
    # （0018 migrationでNOT NULL DEFAULT '[]'の追加カラムとして導入。既存行は
    # 全てpriority_overrides=[]のためbackfillは自明）。レビュー指摘で発見: 以前は
    # このカラム自体が存在せず、DB往復（起動時refresh_axis_definitions・管理API
    # 書き込み直後の反映）のたびに設定した0次条件が黙って失われていた。
    priority_overrides: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # 改善計画T310: 地図チップ表示要素（既存軸だけ特別扱いしていたSECONDARY_AXIS_ICONS等の
    # 軸id→値の手書き辞書を撤去し、軸自身のデータとして持たせたもの）。0019 migrationで
    # NULL許容の追加カラムとして導入（未設定はフロント側の汎用フォールバックに委ねるため、
    # priority_overridesのような`[]`既定は不要——Noneがそのまま「未設定」の意味を持つ）。
    icon_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chip_label: Mapped[str | None] = mapped_column(String, nullable=True)
    panel_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    # 改善計画T318: falseなら地図上チップ・地図の見え方パネルの両方からこの軸を丸ごと
    # 除外する。0020 migrationでNOT NULL DEFAULT trueの追加カラムとして導入（既存行は
    # 全て「表示する」が現状の挙動のためbackfill不要）。旧proxy_hint（専用地図レイヤーを
    # 持たない軸向けの代役案内文、NULL許容カラム）はこの真偽値へ置き換わり撤去した。
    show_map_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # 改善計画T352: axis_idハードコード分岐（road_graph_engine.py等のnight判定・
    # frontend routeStyleModes.tsのwind色分け選択肢）を性質ベースの宣言的フィールドへ
    # 汎用化したもの。0023 migrationでNOT NULL DEFAULTの追加カラムとして導入
    # （既存全軸は'always'/falseが移行時点の実際の挙動と一致するため、night/windのみ
    # 明示的にbackfillした）。
    time_scope: Mapped[str] = mapped_column(String, nullable=False, server_default="always")
    supports_route_coloring: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 改善計画T404: 地図の色分けしきい値だけを差し替える軽量な上書き（domain/
    # axis_definitions.py: AxisDefinition.display_thresholds_overrideのdocstring参照）。
    # 0025 migrationでNULL許容の追加カラムとして導入（未設定はderive_ramp_inputsが
    # 計算したしきい値をそのまま使うため、既存行への追加自体は現在の地図表示に影響しない）。
    display_thresholds_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 改善計画T513: display_thresholds_overrideと対になる、段階ごとの体感ラベルの軽量な
    # 上書き（domain/axis_definitions.py: AxisDefinition.display_band_labels_overrideの
    # docstring参照）。新規migrationで追加するNULL許容カラム（未設定は数値レンジ表記のみの
    # 凡例のため、既存行への追加自体は現在の地図表示に影響しない）。
    display_band_labels_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 専用のway_id→値配信レイヤー（Redis経由、app/infrastructure/dynamic_way_value_cache.py）
    # を持つかの宣言（domain/axis_definitions.py: AxisDefinition.dedicated_way_value_layerの
    # docstring参照）。新規migrationで追加するNOT NULL DEFAULTの追加カラム（既存全軸は
    # falseが移行時点の実際の挙動と一致する。wind/gradientのbackfillはCLAUDE.md
    # 「コミット時の同期ルール」によりmigrationではなくaxis_admin API経由で行う）。
    dedicated_way_value_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 改善計画T458: dedicated_way_value_layer=trueの軸のみ意味を持つ、GET /api/region/
    # dynamic-way-values/{material_id}/...のat/bearing_degクエリパラメータ必須判定
    # （domain/axis_definitions.py: AxisDefinition.dynamic_way_value_needs_time/
    # dynamic_way_value_needs_bearingのdocstring参照）。新規migrationで追加するNOT NULL
    # DEFAULTの追加カラム（既存全軸はfalseが移行時点の実際の挙動と一致する。wind/gradientの
    # backfillはCLAUDE.md「コミット時の同期ルール」によりmigrationではなくaxis_admin API
    # 経由で行う）。
    dynamic_way_value_needs_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dynamic_way_value_needs_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 改善計画T330: create_tables()（Base.metadata.create_all）が先に走る「まっさらなDBから
    # のブートストラップ」経路では、DB側のserver_defaultが無いと0014 migrationのINSERT
    # （updated_atを指定しない）がNOT NULL制約違反になる。他の全カラムはこのため
    # server_defaultを持つ（本カラムだけ0014導入時に見落とされていた）。
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
