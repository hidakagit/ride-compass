
from app.domain.route_preference import RoutePreference


def load_route_preference() -> RoutePreference:
    """呼び出しのたびに、その時点の公開軸から導いた既定の重みを返す。"""
    return RoutePreference()

