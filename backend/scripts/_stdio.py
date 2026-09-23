"""`scripts/`の実行口が共通で使う、端末への出力の設定。

`scripts/`を直接実行したとき（`python scripts/<名前>.py`）は`scripts/`自身が`sys.path`の先頭に
入るため、実行口は`from _stdio import use_utf8_stdio`で読める。テストはスクリプトを
`scripts.<名前>`としてimportするので、読むのは`if __name__ == "__main__":`の中に限る。
"""

import io
import sys


def use_utf8_stdio() -> None:
    """標準出力・標準エラーをUTF-8にする。Windowsの端末の既定（cp932）は日本語以外の記号（—等）を書けずに落ちる。"""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
