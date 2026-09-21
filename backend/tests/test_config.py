from app.config import Settings

# 実行環境のbackend/.envに引きずられないよう、値の検証には明示kwargs指定を使う
# （init値が.env/環境変数より優先される）。


def test_cors_allowed_origins_list_splits_comma_separated_value():
    result = Settings(cors_allowed_origins="http://a.example.com,http://b.example.com").cors_allowed_origins_list

    assert result == ["http://a.example.com", "http://b.example.com"]


def test_cors_allowed_origins_list_with_single_origin_returns_single_item_list():
    result = Settings(cors_allowed_origins="http://localhost:3000").cors_allowed_origins_list

    assert result == ["http://localhost:3000"]


def test_lulc_raster_paths_list_drops_empty_entries():
    assert Settings(lulc_raster_paths="").lulc_raster_paths_list == []
    assert Settings(lulc_raster_paths="a.tif,,b.tif").lulc_raster_paths_list == ["a.tif", "b.tif"]
