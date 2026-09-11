# 静的道路属性の棚卸しと実装計画（調査報告・2026-08-15）※完了・記録のみ

**この計画は完了した。** P0（タグ保持基盤・`domain/traffic.py`・MVT拡張・交通ストレス／
自転車インフラレイヤー）・P1（点データとルート評価接続）とも実装済みで、当時の計画本文
（430行）は現状と重ならなくなったため撤去した。

| 知りたいこと | 現在の正本 |
|---|---|
| 静的道路属性の取込・集計・タイル配信がどうなっているか | [docs/modules/backend/static-road-attributes.md](modules/backend/static-road-attributes.md) |
| 評価軸がどう組まれるか | [docs/modules/backend/axis-studio.md](modules/backend/axis-studio.md)・[docs/design-principles.md](design-principles.md) |
| 実施の時系列 | [docs/improvement-plan-archive/](improvement-plan-archive/)（2026-08-15〜17） |

## 残っていた1件は[T725](tasks/T725.md)へ

本文§3.1が「`improvement-plan.md`側では二重管理を避けるためT番号を振らず本ファイルのみで
管理する」としていた**路面タイルへの道路名（name/ref）焼き込み**は未実装のまま残っていた。
計画文書が完了扱いになった時点で誰にも拾われなくなるため、[T725](tasks/T725.md)として
起票した（経緯は[T724](tasks/T724.md)）。

このファイル自体は、`improvement-plan-archive/`・`decisions/pre-static-attributes-gate.md`
ほかから参照されているため残す（アーカイブは書き換えない運用）。
