# 標高（backend）

## 責務

国土地理院DEMタイルから標高を取得し、(1) ルート単位のサンプリング評価と
(2) Road GraphのEdge単位属性（勾配計算の入力）の2用途へ供給する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| services | `elevation_service.py`・`elevation_aggregation.py`・`elevation_attribute_service.py` |
| infrastructure | `elevation_client.py` |
| batch | `precompute_elevation_attributes.py` |

## 2つの評価経路

| サービス | 用途 | 対象 |
|---|---|---|
| `ElevationService`（`elevation_service.py`） | ルート単位・12点サンプリングの標高評価 | `routing_engine=="openrouteservice"`のとき`OpenRouteServiceEngine`が使う |
| `ElevationAttributeService`（`elevation_attribute_service.py`） | Road GraphのDirected Edgeへ標高属性（`ElevationAttribute`）を紐付ける | Edgeの形状点（geometry）を国土地理院APIへ問い合わせる |

両者は同じ`ElevationClient`実装を再利用する（緯度経度キャッシュを共有するため、同じ
地点への問い合わせはキャッシュヒットする）。`ElevationAttributeService`の同時実行数は
`MAX_CONCURRENT_REQUESTS = 5`。

## DEMタイル方式（`infrastructure/elevation_client.py`）

以前はGSI点標高API（`getelevation.php`）を1地点ずつ呼んでいたが、Road Graph全体
（数万Edge）への標高付与には非現実的な回数の外部呼び出しが必要と判明した（実測:
480Edgeに対し2,880回）。現在はGSIのDEMタイル（テキスト形式）を範囲ごと取得し
ローカルで双線形補間（`_bilinear_interpolate`）する方式へ切り替え、外部呼び出し回数を
タイル単位（近接点は同一タイルを共有）へ削減している。呼び出し側インターフェース
（`get_elevation(client, point, refresh=False)`）は変更していない。

`type`は単一のDEM種別ではなく`DEM_TYPE_PRIORITY`（優先順位付き複数種別）を順に試す
（GSIサーバー側でのフォールバックではなく、クライアント側で順に試行する）。

一時的な通信エラーと恒久的なカバレッジ外（404）は`_CoverageGap`センチネルで区別し、
恒久的な欠損のみをキャッシュする（通信エラーを永続キャッシュしない）。

## 事前計算バッチ（`batch/precompute_elevation_attributes.py`）

Road Graphの全Edgeに対して`ElevationAttributeService`をあらかじめ実行し、
`elevation_attributes`テーブルへ永続化する。[ルート生成エンジン](routing-engine.md)の
road_graphエンジンは、探索コスト計算時にこの事前計算済みテーブルをキー参照するだけで
勾配軸を組み込める（探索中にGSI APIへ問い合わせない）。
