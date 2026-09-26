"""並行実行（司令塔）の道具。各ファイルの持ち物は docs/conventions/orchestration.md「道具のファイル」の表。

依存の向き: 下の層（`gitio`・`ledger`・`github`・`ci_duration`・`procs`）は核（`core`）を読まない。核は下の層を
読み、依頼で足した機能（`queue`・`pending`・`slots`）は核と下の層を読む。核がそれらを読むのは、結果を並べる
`check`・`status`の中だけ（関数の中で遅れて読む。先頭で読むと循環する）。
"""
