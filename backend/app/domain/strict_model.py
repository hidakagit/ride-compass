"""未知のフィールドを黙って捨てないPydanticモデルの基底。

Pydanticの`extra`の既定は`ignore`で、モデルが知らないフィールドは例外にならず捨てられる。
値は消えてアサーションだけが残るため、**フィールドを消した・改名したときの取り残しが
どこにも現れない**（`docs/tasks/T721.md`）。APIリクエストのモデルでは、typoした
フィールドが黙って無視され「指定したのに効かない」という形で利用者に出る。

このリポジトリのモデルは**すべて自前のコードが明示キーワードで組み立てる**——外部API
（JMA・OSM）のJSONは一度dictで受けて必要な値だけを取り出しており、提供側のペイロードが
そのままモデルへ流れ込む経路は無い。したがって`forbid`で一律に締めてよい。新しく外部
ペイロードを直接`model_validate`する経路を作る場合だけ、そのモデルで`extra="ignore"`を
明示的に上書きし、理由をその場に書くこと。

`model_config`はPydantic v2が親子でマージするため、派生側は`frozen=True`のような別の
設定だけを書けばよい（`extra`は引き継がれる）。

環境変数を読む`config.py: Settings`はこの基底を使わない。プロセスの環境変数には無関係な
ものが常に含まれるため`extra="ignore"`でなければ起動しない。
"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
