
from app.domain.route_preference import RoutePreference


def load_route_preference() -> RoutePreference:
    """既定のRoute Preference（重み）を返す（仕様書27-28章）。

    `RoutePreference.weights`の`default_factory`が`default_axis_weights()`
    （`AXIS_DEFINITIONS`が唯一の情報源）のため、単に既定値を使うだけでよい。
    """
    return RoutePreference()

