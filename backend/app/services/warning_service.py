"""緯度経度からJMA警報・注意報バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import httpx

from app.domain.jma_area import ResolvedArea, resolve_area
from app.domain.jma_warning import ActiveWarning, extract_active_warnings
from app.domain.route import Coordinates
from app.infrastructure.jma_area_boundaries import find_class20_code
from app.infrastructure.jma_warning_client import fetch_area_data, fetch_warning_documents
from app.domain.strict_model import StrictModel


class WeatherWarnings(StrictModel):
    area_name: str | None
    report_datetime: str | None
    warnings: list[ActiveWarning]


class WarningService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_warnings(self, point: Coordinates) -> WeatherWarnings:
        """出発地点の警報・注意報バッジ情報を取得する。

        地点→区域→警報エリアの解決、または警報自体の取得のどこで失敗しても
        例外にせず「警報なし」を返す。実際には警報が出ているのに見えなくなりうる
        安全側ではないトレードオフだが、WBGT警告と共有する既知の仕様として受け入れる。
        """
        class20_code = await find_class20_code(point.latitude, point.longitude)
        if class20_code is None:
            return _empty_warnings()

        area_data = await fetch_area_data(self._http_client)
        if area_data is None:
            return _empty_warnings()

        resolved = resolve_area(class20_code, area_data)
        if resolved is None:
            return _empty_warnings()

        documents = await fetch_warning_documents(self._http_client, resolved.office_code)
        if documents is None:
            return _empty_warnings()

        return _build_warnings(documents, resolved)


def _empty_warnings() -> WeatherWarnings:
    return WeatherWarnings(area_name=None, report_datetime=None, warnings=[])


def _build_warnings(documents: list, resolved: ResolvedArea) -> WeatherWarnings:
    """電文配列から、対象エリアぶんのアクティブな警報だけを集約する。

    警報の種類ごとに電文が分かれているため、同じコードが複数の電文に現れうる。codeで
    重複を排除し、採用した警報のうち最も新しいreportDatetimeを発表時刻として使う。
    """
    collected: dict[str, ActiveWarning] = {}
    latest_report_datetime: str | None = None

    for document in documents:
        if not isinstance(document, dict):
            continue
        warning = document.get("warning")
        if not isinstance(warning, dict):
            continue

        target = _find_area_item(warning.get("class20Items"), resolved.class20_code)
        if target is None:
            # 一部の電文（例: 高潮）は対象外の地域だとclass20Items自体に項目を
            # 持たないことがあるため、class10単位でも探す。
            target = _find_area_item(warning.get("class10Items"), resolved.class10_code)
        if target is None:
            continue

        active = extract_active_warnings(target.get("kinds", []))
        if not active:
            continue

        report_datetime = document.get("reportDatetime")
        if isinstance(report_datetime, str) and (
            latest_report_datetime is None or report_datetime > latest_report_datetime
        ):
            latest_report_datetime = report_datetime
        for item in active:
            collected[item.code] = item

    if not collected:
        return _empty_warnings()
    return WeatherWarnings(
        area_name=resolved.class10_name,
        report_datetime=latest_report_datetime,
        warnings=list(collected.values()),
    )


def _find_area_item(items: object, area_code: str) -> dict | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("areaCode") == area_code:
            return item
    return None
