"""backendが1プロセスで動いていることを、起動時に確かめる。

プロセス内に持つ状態（ジョブ台帳・上流への秒間上限・軸定義と較正値の反映・レート制限・
定期ジョブ等）は、ワーカーを増やしても何も落ちずに意味だけが変わる——上限は黙って
ワーカー数倍になり、ジョブはポーリングの半分で見つからなくなる。そこで、ワーカーを
複数にした起動そのものを止める。
"""

from collections.abc import Mapping, Sequence
from pathlib import Path


def uvicorn_worker_count(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    """`argv`がuvicornのCLIでの起動なら、それが作るワーカー数。uvicorn以外の起動は1。

    ワーカーは`multiprocessing`のspawnで起動され、親の`sys.argv`をそのまま受け継ぐため、
    ワーカーの中からでも親に渡された引数が読める。引数の解釈はuvicorn自身のCLI定義に任せ、
    既定値の決め方（`--reload`ではワーカー指定を無視・未指定なら`WEB_CONCURRENCY`）だけを
    uvicornの`Config`に合わせる。
    """
    if not argv or not _is_uvicorn_entrypoint(argv[0]):
        return 1
    from uvicorn.main import main as uvicorn_cli

    params = uvicorn_cli.make_context("uvicorn", list(argv[1:]), resilient_parsing=True).params
    if params.get("reload"):
        return 1
    workers = params.get("workers")
    if workers is None and "WEB_CONCURRENCY" in environ:
        workers = int(environ["WEB_CONCURRENCY"])
    return workers or 1


def require_single_worker(argv: Sequence[str], environ: Mapping[str, str]) -> None:
    """ワーカーが複数なら起動を止める。"""
    workers = uvicorn_worker_count(argv, environ)
    if workers > 1:
        raise RuntimeError(
            f"backendは1プロセスでしか正しく動かない（workers={workers}）。"
            "プロセス内に持つ状態（ジョブ台帳・上流への秒間上限・レート制限等）が"
            "ワーカーごとに分かれるため、--workers・WEB_CONCURRENCYを外して起動すること"
        )


def _is_uvicorn_entrypoint(program: str) -> bool:
    path = Path(program)
    if path.stem == "uvicorn":
        return True
    # `python -m uvicorn`では`uvicorn/__main__.py`になる。
    return path.name == "__main__.py" and path.parent.name == "uvicorn"
