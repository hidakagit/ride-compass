# tenacityが再試行の待機にasyncio.sleep()を内部で使う（tenacity/asyncio/__init__.py）ため、
# ここでモジュールとしてimportしておく必要がある。標準ライブラリのasyncioはプロセス内で
# 単一のモジュールオブジェクトを共有するため、test_weather_client_cache.pyの
# no_real_sleepフィクスチャがweather_client_module.asyncio.sleepへ差し込むパッチが、
# このファイル自身が直接呼ばなくなった後もtenacity内部の待機を透過的に速攻化できる。
import asyncio
import random
import time

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, stop_after_delay

from app.config import settings
from app.domain.route import Coordinates
from app.infrastructure import cache_db
from app.infrastructure.debug_log import error_type_label, log_external_call

# 天候は数km単位でしか変わらないため、標高キャッシュ（4桁）より粗い精度で丸める。
CACHE_PRECISION = 2
# 標高と異なり天候は時間で変化するため、恒久キャッシュではなくTTLを設ける。
CACHE_TTL_SECONDS = 30 * 60

# 気象グリッド（風・降水延長予報、get_forecast_many）専用のTTL・フォールバック窓（改善計画
# 「Open-Meteo 429根本対策の6段階ロードマップ」④）。get_forecast（/api/weatherパネル、単発
# 呼び出し）側はCACHE_TTL_SECONDS/STALE_FALLBACK_MAX_AGE_SECONDSのまま変えない
# （こちらは値を変える理由が無い上、DB永続化の対象もget_forecast_many側だけのため）。
# 3時間はOpen-Meteoの予報モデル自体の更新頻度に対して十分な鮮度であり、かつ1日あたりの
# 総フェッチ回数（＝クォータ消費）を大きく削減できる（旧30分TTLの1/6）。DB永続化
# （cache_db.get_wind_forecast_many/set_wind_forecast_many）によりプロセス再起動をまたいで
# 生き残るようになったため、フォールバック窓も従来の3時間（再起動のたびに消えるメモリ
# キャッシュ前提の値）から24時間へ伸ばし、Open-Meteo側の長時間障害への耐性を上げる。
WIND_GRID_CACHE_TTL_SECONDS = 3 * 60 * 60
WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS = 24 * 60 * 60

# get_forecast（単一地点、/api/weatherの現在地パネル用）はcurrent/hourly全変数を表示に使うが、
# get_forecast_many（WindServiceの区間風評価・風/降水延長予報の格子点マップ）は消費側を
# 辿ると実際に使っているのはhourlyのwind_speed_10m/wind_direction_10m/precipitationのみ
# （T182で他5変数は取得しているだけで捨てられていると判明し除外済み。T183でprecipitationを
# 追加したが、無料プランのクォータ按分は1地点あたり10変数超で増える仕組み・現状3変数のため
# T182の対策効果は保たれる）。1回のリクエストが数百地点規模になり得るため、変数を絞ることで
# Open-Meteo側のクォータ消費（変数数・期間に応じた按分カウント）とレスポンスサイズの両方を
# 大きく削減できる。
WIND_GRID_VARIABLES = "wind_speed_10m,wind_direction_10m,precipitation"

# 本番（Render、共有の送信元IP）では、単発の/api/weather呼び出し（現在地表示）だけでも
# Open-Meteo側の429 Too Many RequestsやConnectTimeout（TLSハンドシェイクの混雑による
# ものとみられる接続タイムアウト）が発生し502になることが実測で確認された（原因調査ログ参照）。
# WindServiceのルート評価は元々区間ごとに個別リクエストしておりこれを悪化させていたため
# get_forecast_manyで1リクエストへ集約したが、単発呼び出し側の対策としてこちらも
# 短いバックオフで数回だけ再試行する。
# 2026-08-17: 上記の初版対策（MAX_RETRIES=2・固定0.3秒刻み）をすり抜けて5件すべてが
# 429で失敗する再発をユーザーが実機で確認（ログ参照）。1回あたりの待機が短すぎて
# Open-Meteo側の抑制がまだ解けていない間に再試行を使い切っていたとみられるため、
# 再試行回数と1回あたりの待機を指数的に増やして強化する。
RETRY_STATUS_CODE = 429
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 0.5
# 1回あたりの待機上限。Open-MeteoがRetry-Afterへ長い秒数を指定してきても、この値で
# クランプし後続の再試行機会・全体予算（RETRY_BUDGET_SECONDS）を使い切らないようにする。
RETRY_BACKOFF_CAP_SECONDS = 2.0
# 再試行ループ全体（待機合計）の予算。フロントのfetchタイムアウト（weatherApi.ts: 15秒）
# より十分短く抑え、待機を使い切ったら以降は即座に諦めて呼び出し元へ制御を返す
# （在圏中のリクエスト自体の時間は含まないため実際の余裕はこれより小さいが、
# 429応答は通常速く返るため実用上は問題にならない）。
RETRY_BUDGET_SECONDS = 8.0
# 2026-08-17: 決定論的なバックオフだと、共有の送信元IPから同時に429を受けた複数リクエストが
# 全く同じ秒数で揃って再試行し、Open-Meteo側の抑制が解ける前に再び束になって突入する
# （再試行の同期）おそれがある。待機秒数へ小さなランダム幅を掛けて分散させる。
RETRY_JITTER_RANGE = (0.75, 1.25)
# 再試行を尽くしても失敗した場合、TTL切れ後もこの秒数以内のキャッシュがあれば代用する
# （502で天候欄を丸ごと空にするより、多少古い予報を出す方が実用的なため）。予報自体は
# forecast_days=2分をまとめて保持しているため、number（現在気象）はやや古くなりうるが
# hourly（ルート評価が使う区間ごとの時刻別値）は取得時刻に関わらず妥当な範囲を保つ。
# get_forecast（単一地点、/api/weatherパネル）専用。get_forecast_many（風・降水延長予報の
# 格子点マップ）はWIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS（モジュール冒頭）を使う。
STALE_FALLBACK_MAX_AGE_SECONDS = 3 * 60 * 60
# 共有クライアントの既定タイムアウト（10秒）のままだと、ConnectTimeout1回の失敗だけで
# 再試行の予算をほぼ使い切ってしまう。この呼び出しだけ短いタイムアウトへ上書きし、
# 早期に失敗を検知して再試行に回す。
REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

_forecast_cache: dict[tuple[float, float], tuple[float, dict]] = {}
# get_forecast_many専用のキャッシュ（上のWIND_GRID_VARIABLES参照）。_forecast_cacheと分けて
# いるのは、キーを共有すると「get_forecast_manyが先に書いた風・降水のみの応答」を後から
# get_forecastがキャッシュヒットとして読んでしまい、/api/weatherパネルの気温等が
# 欠落したまま返る（黙って空欄になる）事故になり得るため。両者は変数セットが異なる
# 別物として扱う。1プロセス内の高速な繰り返し参照を担うL1キャッシュで、プロセス再起動を
# またいだ永続化はcache_db.py（wind_forecast_cacheテーブル）がL2として別途担う
# （改善計画「Open-Meteo 429根本対策」④、get_forecast_many参照）。_forecast_cache
# （こちら）はDB永続化の対象外のまま（/api/weatherは単発呼び出しで再起動時の再取得コストが
# 小さく、DB化の効果が薄いため）。
_wind_forecast_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Retry-Afterヘッダ（秒数形式のみ想定、Open-Meteoは日付形式を返さない）を解釈する。
    "0"（即時再試行の指示）も有効な値としてそのまま返す——呼び出し側でNoneと区別すること。"""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _is_retryable(exc: BaseException) -> bool:
    """再試行すべき失敗か（改善計画、実機フィードバック「より一般的なpythonライブラリ等の
    手法を踏襲できないか」を受けtenacityへ置き換え）。429（レート制限）とTransportError
    （接続タイムアウト等、応答自体を受け取れなかった失敗）だけを対象とする。それ以外の
    HTTPエラー（4xx/5xx）やJSON解析エラーは再試行しても直らないため対象外のまま。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == RETRY_STATUS_CODE
    return isinstance(exc, httpx.TransportError)


def _compute_wait(retry_state) -> float:
    """再試行までの待機秒数を求める。429のRetry-Afterヘッダの値があればそれを優先し
    （0はPythonのor演算子だと「未指定」と誤判定されるため、is not Noneで明示的に判定する）、
    無ければ指数バックオフを使う。上限でクランプした上でジッターを掛ける（RETRY_JITTER_RANGE参照）。
    tenacity.wait基底クラスを継承せず素のcallableのまま渡しているのは、Retry-Afterの尊重が
    tenacity標準のwait戦略に無く、どのみち自前のロジックが要るため（tenacity.asyncio.
    AsyncRetryingはwaitへ単純なcallable(retry_state) -> floatも受け付ける）。"""
    exc = retry_state.outcome.exception()
    retry_after = _retry_after_seconds(exc.response) if isinstance(exc, httpx.HTTPStatusError) else None
    base = retry_after if retry_after is not None else RETRY_BACKOFF_SECONDS * (2 ** (retry_state.attempt_number - 1))
    capped = min(max(base, 0.0), RETRY_BACKOFF_CAP_SECONDS)
    return capped * random.uniform(*RETRY_JITTER_RANGE)


class WeatherClient:
    """Open-Meteo Forecast APIのクライアント。

    `current`（現在の気象）と`hourly`（当日以降の時間別予報）を1回のリクエストで
    まとめて取得する。これにより「現在の天気」だけでなく「N時間後の天気」も
    追加リクエストなしで参照できる（`WeatherService.get_conditions`が利用する）。

    天候は付随情報のため、取得できなかった場合は例外を投げず`None`を返す。
    """

    @staticmethod
    def cache_key(point: Coordinates) -> tuple[float, float]:
        return (round(point.latitude, CACHE_PRECISION), round(point.longitude, CACHE_PRECISION))

    async def _fetch_json(
        self, client: httpx.AsyncClient, params: dict, fields: dict, method: str = "GET"
    ) -> object | None:
        """再試行込みでOpen-Meteoを叩き、成功したらJSON本体を返す。失敗時はfieldsへ記録しNoneを返す
        （呼び出し元は単一地点・複数地点どちらの形状（object/array）で解釈するかを判断する）。

        method="POST"（改善計画T178フォローアップ、風の格子点マップ用にget_forecast_manyが使う）は
        地点数が多い（数百件）とrequest-URIがnginxの既定上限を超え414 Request-URI Too Largeに
        なることが実機で判明したため（GETはクエリ文字列にlatitude/longitudeのカンマ区切りを
        載せる）。POSTはフォームボディへ同じパラメータを載せるためURI長の制約を受けない
        （実機確認: 624地点でPOST成功、同数のGETは414）。単一地点（get_forecast）はパラメータが
        少なくURI長の心配が無いためGETのまま変更しない。

        再試行はtenacity（改善計画、実機フィードバック「より一般的なpythonライブラリ等の手法を
        踏襲できないか」）に委譲している。stop_after_attempt（MAX_RETRIES回まで）と
        stop_after_delay（RETRY_BUDGET_SECONDS秒を過ぎたら打ち切り）をORで組み合わせ、
        どちらか早く達した方で止める。以前の自前ループは「次の待機を足すと予算を超える場合は
        待機せず即座に諦める」という先読みをしていたが、tenacity.stop_after_delayは待機前の
        経過時間だけを見るため、最悪1回ぶん（RETRY_BACKOFF_CAP_SECONDS秒）だけ予算を超えうる
        ——フロントのfetchタイムアウト（15秒）に対しては十分な余裕があるため許容する。
        """

        async def do_request() -> httpx.Response:
            if method == "POST":
                response = await client.post(settings.open_meteo_base_url, data=params, timeout=REQUEST_TIMEOUT)
            else:
                response = await client.get(settings.open_meteo_base_url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response

        def record_retry(retry_state) -> None:
            fields["retries"] = retry_state.attempt_number

        retryer = AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            wait=_compute_wait,
            stop=stop_after_attempt(MAX_RETRIES + 1) | stop_after_delay(RETRY_BUDGET_SECONDS),
            before_sleep=record_retry,
            reraise=True,
        )
        try:
            response = await retryer(do_request)
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None

        fields["result"] = "ok"
        fields["status"] = getattr(response, "status_code", None)
        try:
            return response.json()
        except ValueError as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None

    async def get_forecast(self, client: httpx.AsyncClient, point: Coordinates) -> dict | None:
        key = self.cache_key(point)

        with log_external_call("weather:open-meteo", lat=key[0], lon=key[1]) as fields:
            cached = _forecast_cache.get(key)
            if cached is not None:
                fetched_at, data = cached
                if time.time() - fetched_at < CACHE_TTL_SECONDS:
                    fields["cache"] = "hit"
                    return data

            fields["cache"] = "miss"
            params = {
                "latitude": point.latitude,
                "longitude": point.longitude,
                # weather_code（WMO天気コード）・is_dayは改善計画T385（天気アイコン化）用。
                # UV指数は夜間常に0.0になり項目としての情報価値が無いままヘッダーを
                # 圧迫していたため、weather_code+is_dayから快晴/くもり/霧/雨/雪/雷雨と
                # 昼夜を判定するアイコン1個へ置き換える（frontend/src/components/
                # WeatherPanel/weatherCode.ts参照）。
                "current": "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
                "precipitation,apparent_temperature,uv_index,weather_code,is_day",
                "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation_probability,"
                "wind_gusts_10m,precipitation,uv_index,apparent_temperature",
                # 改善計画T385: 「今日の見通し」パネル（日没・今日の降水確率最大・
                # 最大風速・気温レンジ）用。current/hourlyの瞬間値と違い1日1個の値
                # のため別枠のdailyパラメータで取る。forecast_days=2・timezone=Asia/Tokyo
                # は既存のcurrent/hourlyと共用のため、daily[0]がタイムゾーン基準の
                # 「今日」に一致する（get_forecast_many/WIND_GRID_VARIABLESには含めない。
                # WindServiceは地点数十件を並列取得するため、1地点あたりの取得項目を
                # 増やすとクォータ消費への影響が大きく、日次見通しはget_forecast
                # （単一地点、この関数）でしか使わないため不要）。
                "daily": "sunset,precipitation_probability_max,wind_speed_10m_max,"
                "temperature_2m_max,temperature_2m_min",
                "forecast_days": 2,
                "timezone": "Asia/Tokyo",
                "wind_speed_unit": "ms",
            }

            data = await self._fetch_json(client, params, fields)
            if data is None:
                if cached is not None and time.time() - cached[0] < STALE_FALLBACK_MAX_AGE_SECONDS:
                    fields["fallback"] = "stale_cache"
                    return cached[1]
                return None

            _forecast_cache[key] = (time.time(), data)
            return data

    async def get_forecast_many(
        self, client: httpx.AsyncClient, points: list[Coordinates]
    ) -> dict[tuple[float, float], dict | None]:
        """複数地点の予報を、可能な限り1回のOpen-Meteo呼び出しにまとめて取得する。

        WindServiceはルート1本につき区間数ぶん（最大数十件）weatherを個別リクエストしており、
        本番（Render、共有の送信元IP）ではこれだけで429が常態化し天候取得が全滅する事態が
        起きていた（原因調査ログ参照）。Open-Meteoは緯度経度をカンマ区切りで渡すと地点ごとの
        予報配列を1リクエストで返せるため、これを使ってリクエスト数自体を減らす。
        地点はcache_key（丸め精度CACHE_PRECISION）単位で重複排除し、キャッシュ済みの地点は
        リクエストに含めない。

        改善計画T178フォローアップ（風の格子点マップ）で数百地点をまとめて渡すようになった
        結果、GET（クエリ文字列）だと地点数によってはrequest-URIがnginxの既定上限を超え
        414 Request-URI Too Largeになることが実機で判明した（624地点で再現、288地点では
        未発生）。そのためPOST（フォームボディ）で送る（_fetch_json参照）。

        呼び出し元（WeatherService.get_conditions_many→WindService、get_wind_grid）が
        実際に使うのはhourlyのwind_speed_10m/wind_direction_10m/precipitationのみのため、
        get_forecast（単一地点、全変数）とは別にWIND_GRID_VARIABLESへ絞る。数百地点規模に
        なるこの経路の変数を絞ることが、Open-Meteo側クォータ消費削減の効果が最も大きい
        （get_forecastは単発呼び出しのため変数を絞っても効果が小さく、/api/weatherパネルの
        表示項目を削ることになるためそのまま全変数を維持する）。キャッシュも_forecast_cacheとは
        分離した_wind_forecast_cacheを使う（理由はモジュール冒頭のコメント参照）。

        改善計画「Open-Meteo 429根本対策」④: _wind_forecast_cacheはプロセス内メモリのため
        Renderのようなプラットフォームでのプロセス再起動・コンテナ再作成のたびに消え、
        再起動直後のアクセスがOpen-Meteoへの無駄な再取得（＝1日あたりのクォータ消費）を
        招いていた。cache_db.py（wind_forecast_cacheテーブル、SQLite）へL2として永続化し、
        L1（メモリ）に無いキーだけL2を引いてから不足分だけ実際にフェッチする。
        """
        keys: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for point in points:
            key = self.cache_key(point)
            if key not in seen:
                seen.add(key)
                keys.append(key)

        results: dict[tuple[float, float], dict | None] = {}
        now = time.time()
        needs_lookup: list[tuple[float, float]] = []
        for key in keys:
            cached = _wind_forecast_cache.get(key)
            if cached is not None and now - cached[0] < WIND_GRID_CACHE_TTL_SECONDS:
                results[key] = cached[1]
            else:
                needs_lookup.append(key)

        # メモリキャッシュ（L1）に無い/古い分だけ、プロセス再起動をまたいで永続化された
        # DB（L2、cache_db.py）を引く（改善計画「Open-Meteo 429根本対策」④）。見つかった分は
        # 新鮮・陳腐問わずL1へ書き戻し、以降のTTL判定・フォールバック判定を既存のL1中心の
        # ロジックのまま使い回す（L2は「再起動直後にL1が空でも前回の値が拾える」ための層で、
        # 1リクエスト内で繰り返し引く用途はL1が引き続き担う）。
        if needs_lookup:
            db_hits = await cache_db.get_wind_forecast_many(needs_lookup)
            for key, cached in db_hits.items():
                _wind_forecast_cache[key] = cached

        to_fetch: list[tuple[float, float]] = []
        for key in needs_lookup:
            cached = _wind_forecast_cache.get(key)
            if cached is not None and now - cached[0] < WIND_GRID_CACHE_TTL_SECONDS:
                results[key] = cached[1]
            else:
                to_fetch.append(key)

        if to_fetch:
            with log_external_call(
                "weather:open-meteo", lat=to_fetch[0][0], lon=to_fetch[0][1], locations=len(to_fetch)
            ) as fields:
                fields["cache"] = "miss"
                params = {
                    "latitude": ",".join(str(lat) for lat, _lon in to_fetch),
                    "longitude": ",".join(str(lon) for _lat, lon in to_fetch),
                    "current": WIND_GRID_VARIABLES,
                    "hourly": WIND_GRID_VARIABLES,
                    "forecast_days": 2,
                    "timezone": "Asia/Tokyo",
                    "wind_speed_unit": "ms",
                }

                data = await self._fetch_json(client, params, fields, method="POST")
                # 1地点のみのリクエストはOpen-Meteoが配列ではなく単一objectを返すため、
                # 常に地点数ぶんの配列として扱えるようここで揃える。
                entries = data if isinstance(data, list) else ([data] if data is not None else [])
                newly_fetched: dict[tuple[float, float], tuple[float, dict]] = {}
                for key, entry in zip(to_fetch, entries):
                    # 失敗時（entry is None）は既存キャッシュを消さない。下のフォールバック
                    # ループがそれを使えるようにするため（成功時のみ上書き）。
                    if entry is not None:
                        _wind_forecast_cache[key] = (now, entry)
                        newly_fetched[key] = (now, entry)
                    results[key] = entry
                # 上流の応答件数がリクエストと食い違う異常時は、対応しきれない残りをNone扱いにする。
                for key in to_fetch[len(entries) :]:
                    results[key] = None

                # 新規取得分をDB（L2）へ書き戻す。プロセスが再起動しても次回はここから
                # 拾えるようにする（改善計画「Open-Meteo 429根本対策」④）。書き込み失敗は
                # レスポンス自体には影響しない（cache_db.set_wind_forecast_many参照）。
                if newly_fetched:
                    await cache_db.set_wind_forecast_many(newly_fetched)

                # 再試行を尽くしても失敗した地点は、TTL切れ後もWIND_GRID_STALE_FALLBACK_MAX_
                # AGE_SECONDS以内のキャッシュがあれば代用する（get_forecastと同じ方針）。
                stale_fallback_count = 0
                for key in to_fetch:
                    if results.get(key) is not None:
                        continue
                    cached = _wind_forecast_cache.get(key)
                    if cached is not None and now - cached[0] < WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS:
                        results[key] = cached[1]
                        stale_fallback_count += 1
                if stale_fallback_count:
                    fields["fallback"] = f"stale_cache:{stale_fallback_count}"

        return {key: results.get(key) for key in keys}
