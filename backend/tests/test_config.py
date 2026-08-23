import pytest
from pydantic import ValidationError

from app.config import Settings, settings

# 実行環境のbackend/.env(Supabase等の実接続先を指しうる)の影響を受けないよう、値の検証には
# Settings()の暗黙インスタンス化(.env読み込みが発生する)を避け、明示kwargs指定
# (init値が.env/環境変数より優先される)かmodel_fieldsの宣言済みdefaultを直接見る。


def test_default_field_declarations():
    assert Settings.model_fields["cors_allowed_origins"].default == "http://localhost:3000"
    assert Settings.model_fields["routing_engine"].default == "road_graph"
    assert Settings.model_fields["debug_mode"].default is False
    assert Settings.model_fields["render_git_commit"].default is None


def test_cors_allowed_origins_list_splits_comma_separated_value():
    result = Settings(cors_allowed_origins="http://a.example.com,http://b.example.com").cors_allowed_origins_list

    assert result == ["http://a.example.com", "http://b.example.com"]


def test_cors_allowed_origins_list_with_single_origin_returns_single_item_list():
    result = Settings(cors_allowed_origins="http://localhost:3000").cors_allowed_origins_list

    assert result == ["http://localhost:3000"]


def test_routing_engine_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings(routing_engine="not-a-real-engine")


def test_routing_engine_accepts_declared_literals():
    assert Settings(routing_engine="road_graph").routing_engine == "road_graph"
    assert Settings(routing_engine="openrouteservice").routing_engine == "openrouteservice"


def test_module_level_settings_singleton_is_a_settings_instance():
    # app.config.settingsはアプリ全体で共有される単一インスタンス(app/main.py, app/api/routes.py
    # 等が直接importして使う)。型と存在だけを確認し、実際の値(.env依存)には踏み込まない。
    assert isinstance(settings, Settings)
