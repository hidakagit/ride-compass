"""未知のフィールドを黙って捨てないPydanticモデルの基底。

Pydanticの`extra`の既定は`ignore`で、モデルが知らないフィールドは例外にならず捨てられる。
値は消えてアサーションだけが残るため、**フィールドを消した・改名したときの取り残しが
どこにも現れない**（`docs/tasks/T721.md`）。APIリクエストのモデルでは、typoした
フィールドが黙って無視され「指定したのに効かない」という形で利用者に出る。

外部API（JMA・OSM）のJSONは一度dictで受けて必要な値だけを取り出しており、提供側の
ペイロードがそのままモデルへ流れ込む経路は無い。新しく外部ペイロードを直接
`model_validate`する経路を作る場合は、そのモデルで`extra="ignore"`を明示的に上書きし、
理由をその場に書くこと。

**ただし、自前で書いた過去のデータは流れ込む。** `axis_definitions.shape_params`（DBのJSONB、
`infrastructure/axis_definition_repository.py`の`TypeAdapter(AxisShape).validate_python`）と
軸定義スナップショット（`infrastructure/axis_definitions_snapshot.py`の
`AxisDefinition.model_validate`）は、**過去のコードが書いた形**を今のモデルで読む。
`forbid`のもとでフィールドを消す・改名すると、既存の行が読めずアプリが起動に失敗する
（`refresh_axis_definitions`のfail-fast、[T396](../../../docs/tasks/T396.md)で本番障害の実績）。
これは意図した挙動——黙って値を捨てるより起動を止める方がよい——だが、
**そういう変更は本番DBの移行を先に済ませてからpushする**必要がある
（CLAUDE.md「コミット時の同期ルール」）。

`model_config`はPydantic v2が親子でマージするため、派生側は`frozen=True`のような別の
設定だけを書けばよい（`extra`は引き継がれる）。

環境変数を読む`config.py: Settings`はこの基底を使わない。プロセスの環境変数には無関係な
ものが常に含まれるため`extra="ignore"`でなければ起動しない。
"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
