"""FastAPIアプリのOpenAPIスキーマをJSONへ書き出す（docs/improvement-plan.md T4）。

フロントエンドの型生成（openapi-typescript、frontend/package.jsonのgenerate:api）の
入力になる。出力先をfrontend/src/types/generated/へ置いてコミットするのは、
(1) フロントの型生成・ビルドがbackendの起動なしで完結する、
(2) CIのドリフト検知（backendから再生成→git diffで差分が無いことを確認）が成立する、
の2点のため。domain/route.py等のレスポンスモデルを変更したら、このスクリプトと
frontendのnpm run generate:apiを実行して生成物を同じコミットに含めること
（手動同期ペアを作らない方針。docs/design-review-2026-08-15.md 設計原則1・3）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\export_openapi.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated" / "openapi.json"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    # ensure_ascii=False: 日本語のdescription（レート制限メッセージ等）を可読なまま残す。
    # indent固定・末尾改行あり: 再生成のdiffが内容の変化だけを反映するようにする。
    OUTPUT_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
