"""backendがディスクへ置くもの（キャッシュ・同期したファイル・道路網の置き場等）の根。

本番ではホストのディレクトリをこの場所へ載せる（`deploy-backend.yml`の`-v`）ので、コンテナを入れ替えても中身が残る。
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
