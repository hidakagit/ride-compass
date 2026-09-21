# データモデル（API境界の型）

**型そのものはここに書かない。** 正本は`backend/app/domain/route.py`等のPydanticモデルで、
frontendの型（`frontend/src/types/generated/api.d.ts`）はそこから生成される。ここには
**両側が守る約束**だけを置く。

DBの表の持ち方（生データを1つの形で持つ・派生は粒度ごとに1表）は
[静的道路属性・タイル配信](../modules/backend/static-road-attributes.md)が持つ。

## 命名と欠損

- **スネークケース**で統一する（フロント⇔バックエンドで変換しない）。
- 取得できなかった値は`null`で返し、**キーは消さない**。標高系・難易度系は取得失敗が
  常態としてありうるため、frontendはnull許容で扱う。

## 軸に関わる値だけは「キー自体を持たない」

`axis_difficulties`・`axis_contributions`・`axis_raw_values`・`material_values`は
`axis_id`／`material_id`をキーにした辞書で、**評価できなかった軸・非公開の軸・値を持たない
材料はキー自体を省く**。

これは上のnull規約とわざと逆になっている。軸はGUIから増減するため、固定フィールドを
持つとコード側が軸の一覧を持つことになり、[設計原則](design-principles.md)構造仕様2に
反する。`null`で埋めると「軸は存在するが値が無い」と「そもそもその軸が無い」を
区別できない。

同じ辞書が区間単位（`RouteSegmentDetail`）とルート単位（`RouteCandidate`）の両方にあり、
後者は前者を距離で加重して畳んだもの。**畳み方は1箇所が持ち**、軸が増えても集約側に
書き足す場所は無い。

## タイルで配るものはJSONの型を持たない

地域全体のレイヤー（路面・POI・事故・土地被覆・標高）はタイル（MVT／PNG）で配るため、
JSONのレスポンスモデルを持たない。タイルのプロパティ構成は焼き込みSQLが決め、その
署名がキャッシュ鍵に入る（[静的道路属性・タイル配信](../modules/backend/static-road-attributes.md)）。
