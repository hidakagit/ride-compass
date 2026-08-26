# 改善実行計画（2026-08-15 設計レビュー対応）

[design-review-2026-08-15.md](design-review-2026-08-15.md) の指摘に対する実行計画。
同日の第2回レビュー（[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md)、複雑度平衡の観点）
の対応タスク（T16〜T22）は完了済みのため[docs/improvement-plan-archive/2026-08-15.md](improvement-plan-archive/2026-08-15.md)「第2回レビュー対応」節へ移設済み。
**進捗はこのファイルのチェックボックスを更新して管理する**（完了時に `[x]`＋完了日を追記）。

**このファイルは変更履歴であり、「現在の正」ではない**（過去レビュー基準と同じ扱い）。
評価軸の数・地図レイヤーの一覧・現在有効な設定値のような「動く事実」は、書かれた時点の
スナップショットに過ぎず本文中で何度も更新されている（例: 評価軸は7軸→8軸→9軸→8軸→7軸→
6軸+windと変遷）。現在の値は常に一次情報（`docs/architecture.md`）を参照し、本ファイル内の
古い記述と食い違っていても「矛盾」ではなく「その時点のスナップショット」として扱う。

**完了済みタスクの実施記録は[docs/improvement-plan-archive/](improvement-plan-archive/)へ日付ごとに
退避している**（2026-08-19棚卸し整理）。索引は[improvement-plan-archive/README.md]
(improvement-plan-archive/README.md)（完了タスク一覧つき）。本体にはオープンなタスクを
含む節と「進め方の原則」のみを残す。

## 進め方の原則

- **順序の根拠**: 「検証の自動化（Phase 1）→ 境界の固定（Phase 2）→ 内部の再配置（Phase 2後半）→
  スケール準備（Phase 3）」の順にすると、各修正が前の成果を安全網として使え、後続の修正量が最小になる。
- 1タスク=1コミット（またはPR）。着手前後で全テストgreenを確認する。
- 挙動を変えるタスクはテストを先に追加/更新してから実装する。
- **コミット時の同期ルール（OpenAPI生成物の再生成・architecture.md追従・タイル世代の
  対上げ）はCLAUDE.mdの「コミット時の同期ルール（必読）」節が正**（2026-08-23の棚卸で
  T196/T197のルールをここからCLAUDE.mdへ昇格・一本化した。本ファイルには重複記載しない）。
- 規模目安: S=1時間以内 / M=半日 / L=1日以上
- **フロントエンドで新しいUI機構（スライダー・タブ・ボトムシート等）を追加するときは、
  自前実装より先に定番ライブラリ（例: Radix UI、vaul等）で賄えないか検討する**
  （2026-08-23、ユーザー指示「一般的に使われているライブラリやスタイルを使うことで、
  車輪の再発明が防げるならば積極的に取り入れてほしい」、T250対応中に受領）。既存の
  BottomSheet（frontend/src/components/BottomSheet）は地図のピンチズームジェスチャーと
  衝突しないよう`touch-action`を実機フィードバックベースでチューニングした自前実装で、
  暗幕なし・部分表示という独自要件を持つため、置き換えを検討する場合はこの挙動を
  壊さないか要確認、かつ着手前にユーザーへ相談する。既存パターンの単純な拡張
  （例: コンポーネントへのprop追加）はこの原則の対象外。

---

**[Phase 1〜4（2026-08-15設計レビュー対応の原型4節、T1〜T15。T10/T11/T12は2026-08-23完了）は
docs/improvement-plan-archive/2026-08-15.md へ移設済み（2026-08-23棚卸）]**

## バックエンド一時的な到達不能の調査（2026-08-17・ユーザー報告）

### - [ ] T105. 地図をグリグリ操作した直後にバックエンドへ到達できなくなる事象の原因特定 規模S〜M — トリガー: 次回の再現報告

- 発端: ユーザーが本番サイト（Render）のモバイル実機スクリーンショットを提示。地図を素早く
  パン/ズームした直後、デバッグログに`region-road-surface-tiles`の`Failed to fetch`が2件、
  数分後には「システム状況」パネルの更新ボタンを3回連打してもバックエンド側
  （`/api/debug/stats`）だけが毎回`Failed to fetch`になり続けた（フロントエンド側
  `/api/version`は同一オリジンのNext.js自身の応答のため毎回即成功、対比でバックエンドの
  不調が際立った）。
- 調査所見: `/api/debug/stats`はDB・外部APIに依存しないプロセス内メモリ参照のみの
  軽量エンドポイント（`health.py`）のため、遅延ではなく到達不能（TCP接続不可）である
  可能性が高い。`region.py`には過去の実障害（グリグリ操作で並列タイル要求が急増→
  PostGIS問い合わせがCPUを奪い合う→Renderのヘルスチェックが無応答→インスタンス強制
  再起動、対策として`_region_tile_semaphore`で同時実行数6に制限済み）の記録があり、
  症状のパターンが一致する。ただし対策済みのはずの経路のため、(a)対策の再発、
  (b)Render無料枠のコールドスリープ（無操作でスリープ→次リクエストで再起動に数十秒）、
  のどちらか、あるいは両方が疑わしいが、Renderダッシュボード側のログ（インスタンス
  再起動イベント）を確認しないと確定できず、このセッションからは見えないため未確定。
- 副次対応（このラウンドで実施済み）: 調査中に`debugStatsApi.ts: getDebugStats`・
  `versionApi.ts: getFrontendVersion`が`fetch()`自体の失敗（通信エラー）をデバッグログへ
  記録していない不備を発見（HTTPステータス異常・JSON解析失敗はログするが、通信エラーだけ
  素通りしていた）。`regionApi.ts: refreshBasemapCache`で既に確立していた
  try/catchパターンへ統一し、次回同様の事象が起きた際にデバッグログだけで
  「フロントは動いているがバックエンドだけ通信エラー」を後から追跡できるようにした。
  frontend既存テストへ通信エラーケースを追加（各2件）、全green。
- 完了条件: ユーザーが同じ事象を再現・報告した際、更新後のデバッグログ（通信エラーの
  記録が残るようになった）とRenderダッシュボードのログを突き合わせて、
  「対策済み制御の再発」か「コールドスリープ」かを切り分ける。
- **関連（2026-08-24）**: 「20kmでルート生成に常に失敗する」報告の調査中、本タスクで
  確立したtry/catchパターンが`routeApi.ts`（POST系）・`regionApi.ts`の残り2関数・
  `jmaNowcastFrames.ts`には適用されておらず同種の穴が再発していたことが判明、
  T258で横断的に修正済み。20kmバグ自体の根本原因はT259で確定（Renderプラットフォームの
  約100秒タイムアウト）。本タスク（地図グリグリ操作直後の到達不能）とT259（ルート生成の
  20km失敗）は症状が別だが、いずれも「Render上の重い処理がプラットフォーム側の制約
  （ヘルスチェック無応答による強制再起動、または約100秒のリクエストタイムアウト）に
  引っかかって接続が切れる」という同根の可能性が高い。

### - [x] T259. 20kmルート生成が本番で常に失敗する事象の根本原因を特定 規模S（調査のみ、2026-08-24完了）

- 発端: ユーザー報告「現在地点から20kmでルート生成に常に失敗する」。ユーザー実機
  （緯度経度35.7506948, 139.7418897、本番フロント）で「fail to fetch」を確認。
  過去2回の直接API再現（ローカルスクリプトから本番DBへ直結、王子・ユーザー座標いずれも）は
  成功しており矛盾していたため、実際のブラウザ経由の本番環境で再調査した。
- **再現手順**: Browserツールで本番フロント（ride-compass-frontend.onrender.com）を開き、
  `navigator.geolocation.getCurrentPosition`をユーザー座標へモックした上で「現在地に移動」
  →距離20km→「ルート生成」を実行（`localStorage.setItem("ridecompass:debug-enabled","1")`
  でデバッグログも有効化）。
- **判明した事実**:
  1. ボタンが「生成中...」のままになり、**リクエスト開始から85.4秒後**に「Failed to fetch」
     でUIへエラー表示。ブラウザコンソールには
     `Access to fetch at 'https://ride-compass-backend.onrender.com/api/routes/generate' ...
     has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present`
     という**CORSポリシー違反に見えるメッセージ**が出ていたが、これは正しい診断ではない
     （後述）。T258で追加した`api:route`カテゴリのログにも
     `失敗 (通信エラー) {durationMs: 85435, error: TypeError: Failed to fetch}`として
     正しく記録された（T258の効果を実地で確認）。
  2. 同一リクエストをブラウザを介さずcurlで本番バックエンドへ直接送ったところ
     （`Origin`ヘッダーは付与、ブラウザのCORS強制は受けない）、**`HTTP/2 502`
     （`content-length: 0`、`server: cloudflare`、`x-render-origin-server: Render`）が
     `time_total=100.82秒`で返ってきた**。CORSヘッダーは一切無し。
  3. **結論**: これはアプリのCORS設定不備ではなく、**Render（Cloudflare経由）のプラット
     フォーム側が約100秒でリクエストを強制打ち切りし、空の502をエッジ層自身が生成して
     返している**。FastAPIアプリの`CORSMiddleware`はこの502に一切関与していない
     （アプリまで到達していない、またはアプリの応答より先にエッジが切っている）ため
     CORSヘッダーが無く、ブラウザは「CORSヘッダーの無いクロスオリジン応答」を実態と
     異なる「CORSポリシー違反」として報告している。フロント側のアプリレベルタイムアウト
     （`routeApi.ts`の360秒、T248参照）は一度も発火していない。
  4. **状況証拠（未確定）**: 502応答から26秒後に本番`/api/debug/stats`を確認したところ
     `started_at`（プロセス起動時刻）がその直後を指しており、複数回の確認でも安定していた
     （＝頻繁な再起動ではなく単発の再起動）。この重いリクエストの処理中にバックエンド
     プロセス自体がクラッシュ・自動再起動した可能性を示唆するが、Renderダッシュボードの
     再起動理由（OOM等）は本セッションから確認できず未確定。
  5. **過去の「直接検証は成功」との矛盾が解けた**: 過去の再現テストはローカルスクリプトから
     本番DBへ直結し、アルゴリズム・DB部分のみを計測していた。RenderのHTTP層（今回発見した
     約100秒のプラットフォームタイムアウト）を一切経由しないテストだったため、実際の
     ユーザー体験（ブラウザ→Render経由）とは異なる条件で「成功」していたに過ぎない。
- **T248との関係**: T248（road_graph既定エンジンの性能改善、規模M〜L）は「冷パスの体感
  遅延」として記録されていたが、本調査によりこの地点・距離の組み合わせは体感遅延ではなく
  **プラットフォームタイムアウトによる完全な失敗**に達することが確定した。T248のトリガー
  （「一般公開の意思決定時に必須化、それまでは研究利用での体感遅延報告で着手」）の前提
  （＝現状は"遅延"に留まる）を見直す必要がある可能性がある。
- 完了条件: 満たした（失敗のタイミング・エラー内容の特定というユーザー依頼の範囲）。
  ただし根本原因（冷パスがプラットフォーム制約を超えて完全失敗する）自体の修正は
  未着手。修正方針（冷パスの高速化＝T248、非同期ジョブ化、対象地点のキャッシュ事前温め等）
  はユーザー判断待ちのため、対応要否・優先度はT248側で改めて検討する。

### - [x] T261. 大規模な冷パスリクエストで本番バックエンドプロセスがクラッシュ→自動復旧する事象 規模不明（2026-08-24完了、T263のOracle VM移行で解消）

- 発端: T248候補1（save_graphのCOPY化）を本番デプロイした直後、ユーザーが「現在地10km」
  で生成を試みたところ25.8秒で`Failed to fetch`が発生（デバッグログ`durationMs:25842`）。
  直後の`GET /api/debug/stats`（DB・外部API非依存の軽量エンドポイント）まで同じく
  `Failed to fetch`になっており、個別リクエストの遅延ではなく**バックエンドプロセス
  自体がダウンしていた**ことを示す。ユーザーから「バックエンドは落ちてから自動復旧
  しているよう」という的確な指摘を受けた。
- **調査で判明した事実**:
  1. デプロイ直後から`/api/debug/stats`の`started_at`（プロセス起動時刻）が数分おきに
     更新され続けており、明確な**クラッシュ→自動再起動の繰り返し**を確認した
     （例: `22:42:46`→`22:46:22`と、こちらの追加リクエストのたび新しい起動時刻に
     切り替わる）。
  2. デプロイ直後という時系列とcommit一致から、当初はT248候補1（COPY化、一括で
     全レコードをメモリに載せてCOPYする実装）が原因と強く疑い、本番安定性を最優先して
     `git revert`で切り戻した（コミット`b2e846f`、詳細はT248候補1本文参照）。
  3. **しかし切り戻し後（`_bulk_upsert`のchunk=1000 ON CONFLICT、以前から本番で
     長期間安定稼働していたはずの実装）でも、同じ地点・10kmのリクエストが
     `http_code=502`・`time_total=71.4秒`で失敗し、直後にプロセスの`started_at`が
     再度更新されている（クラッシュが再現）ことを確認した**。これは
     **COPY化が原因ではない**ことを強く示唆する重大な発見であり、当初の仮説
     （T248候補1のメモリ使用量問題）は誤りだった可能性が高い。
  4. **新しい仮説**: T248・T259でこれまで「本番実測で成功」としてきた検証は、
     すべてローカルbackendから`DATABASE_URL`を本番Oracle Cloud PostGISへ直結する
     方式（RenderのHTTPレイヤー・実際のRenderアプリプロセスを一切経由しない）で
     行われていた。**Render上の実際のアプリプロセスが、大規模な新規split
     （`get_way_specs_with_closure`→`build_road_graph`→`save_graph`、都心規模で
     数万Node・十数万Edgeのグラフ全体をPythonオブジェクトとしてメモリに保持する
     経路）をこなせるだけのメモリを持っているかどうかは、今回のユーザー報告が
     初めての実地検証だった可能性が高い**。RenderのHTTPプロキシ層でのタイムアウト
     （T259で確定した約100秒）とは別に、**アプリプロセス自体のメモリ不足（OOM）
     によるクラッシュ**が真因である疑いが濃厚だが、Renderダッシュボードの再起動理由
     （OOM/ヘルスチェック失敗等）は本セッションから確認できず未確定。
  5. 切り戻し後のプロセスは、負荷が無い状態（アイドル時）では安定して200を返し続けて
     おり、常時落ちているわけではない。**特定の重い（未split・広域の）リクエストが
     トリガーになっている**点はT259と一致する。
- **現状**: T248候補1（COPY化）は切り戻し済みで、切り戻し自体は「メモリ使用量が
  未検証な新しい実装を本番から除去する」という安全側の判断として妥当だが、
  **クラッシュの根本原因は未解決のまま残っている**（切り戻し後の旧実装でも再現した
  ため）。「現在地」を含む一部地点・10km以上のリクエストで、ユーザーが実際に
  クラッシュ→復旧待ちを経験する状態が現在も続いている可能性がある。
- **ユーザー提供のRenderログによる追加調査（2026-08-24）**: ユーザーから該当時間帯の
  生ログを提供してもらい、2つの再起動を比較した。
  - `22:53:34`の再起動: 直前に`Shutting down`→`Waiting for application shutdown`→
    `Application shutdown complete`→`Finished server process`という**正常終了ログ**
    と`==> Your service is live`が出ていた（これは切り戻しデプロイそのもの）。
  - `22:56:41`の再起動: 直前の`22:56:27`の`GET /health -> 200`（90ms）から、正常終了
    ログが一切無いまま次の起動ログへ直接飛んでいた。しかもその手前で`/health`の
    応答時間が1ms→200〜300ms→90ms前後へ悪化する傾向が見えていた。
  - この非対称性（正常終了ログの有無）から、**プロセスが応答不能になり強制終了された**
    可能性が高いと判断した。T105が別トリガー（タイル要求急増）で記録していた
    「CPU専有→ヘルスチェック無応答→Render強制再起動」と同型の障害を疑い、
    `graph_service.py`の`build_road_graph(way_specs, node_coords)`が同ファイル内の
    他の重いCPU処理（`_rows_to_road_graph`等）と異なり`asyncio.to_thread`で
    オフロードされていない同期呼び出しのままイベントループ上に居ることを発見、
    修正した（コミット`5230bb5`）。
  - **しかし本番デプロイ後に再検証したところ、修正後も同じ症状が再現した**:
    同一リクエスト（10km、`http_code=502`・`time_total=71.5秒`）を実行しながら
    `/health`を1秒間隔でポーリングしたところ、応答時間が数百ms〜2.5秒へ悪化する
    だけでなく、**10秒のタイムアウトで2回応答が返らなかった**（`curl: Operation
    timed out`）。リクエスト失敗と同時に`started_at`も更新されており、クラッシュは
    解消していない。
  - **結論（暫定）**: `build_road_graph`のイベントループ専有は実在する問題だが、
    それだけでは説明がつかない。`asyncio.to_thread`はイベントループの
    スケジューリング公平性を改善するだけで、コンテナ自体のCPU割当（Renderの
    インスタンスプランがCPUを絞っている場合）が不足していれば、スレッドへ逃がした
    計算も同じ限られたCPU時間を奪い合い続け、ヘルスチェックも含め全体が遅くなる
    ことは避けられない。**Renderのインスタンスプラン（CPU/メモリの上限）が、この
    規模の冷パスリクエストに対して不足している可能性が、当初のOOM仮説と並ぶ
    有力候補として浮上した**。
- **Renderダッシュボードのイベントログで確定（2026-08-24、ユーザー提供のスクリーン
  ショット）**: Freeプランのため`Metrics`タブのCPU/メモリグラフは表示不可
  （`Upgrade to any paid instance type to view application metrics`）だったが、
  `Event timeline`に**`Instance failed`イベントが明示的に記録**されていた（推測では
  なく確定した事実）。時系列（新しい順）:
  - `8:09 AM` Instance failed: `xqvlt`（`5230bb5`＝asyncio.to_thread修正のインスタンス）
  - `8:08 AM` Deploy live for `5230bb5`
  - `7:56 AM` Instance failed: `w9zmn`（`b2e846f`＝切り戻し後のインスタンス）
  - `7:53 AM` Deploy live for `b2e846f`
  - `7:50/7:45/7:42/7:41 AM` Instance failed: `f4nmj`（**同一インスタンスIDで4回連続**、
    `91b25a7`＝COPY化のインスタンス）
  - `7:26 AM` Deploy live for `91b25a7`
  - **コードを何に変えても、デプロイ直後の重いリクエストで`Instance failed`が発生
    している**。これはT248候補1（COPY化）・T261の`asyncio.to_thread`修正のいずれも
    根本原因ではなかったことの確定的な裏付けであり、**Renderの無料プラン（公称
    0.1 CPU・512MB、Freeプランはこの数値も含めダッシュボードから直接は確認不可）の
    リソース制約そのものが律速要因である可能性が最も高い**という結論に至った。
    都心規模で数万〜十数万件のNode/Edgeをまるごとメモリ上のPythonオブジェクト
    （Pydantic/dataclass）として保持しながら交差点分割・PostGIS往復・バルクUPSERTを
    行う現在の冷パス設計は、512MB級のメモリ上限に対して明らかに重い可能性がある。
- 対応方針の選択肢（規模・コストの見積もりが異なるためユーザー判断が必要）:
  1. **Renderのインスタンスプランを有料枠へ増強する**（規模: 小、コスト: 月額課金）。
     最も直接的で低リスクな解決策。増強後に同じ10kmリクエストで再検証し、
     `Instance failed`が解消するか確認する。
  2. **冷パスの計算コスト・メモリ使用量そのものを削減する設計変更**
     （T248候補2「冷パスの体験設計」との統合、規模L以上）。Freeプランのまま
     解決したい場合はこちらが必須になるが、根本的な設計変更（ストリーミング処理・
     チャンク単位の逐次処理・バックグラウンドジョブ化等）が要る。
  3. 1と2の併用（増強しつつ将来的な負荷増にも備えて設計改善も行う）。
- **最終対応（2026-08-24）**: ユーザー判断により選択肢1・3のいずれでもなく、
  「Renderからの離脱」（別クラウドサービスへの移行）を選択。詳細検討・実装はT262
  （冷パス削減、性能改善として実施）・T263（Oracle Cloud VMへの移行、根本対応）を参照。
- 完了条件: 満たした。T263（Oracle VM移行）で実機ブラウザ検証まで完了し、T261が
  報告していた「大規模な冷パスリクエストでのクラッシュ」は新backend（Oracle Cloud VM）
  では再現しないことを確認した（詳細はT263参照）。Render側backendは1日間の並行稼働後に
  停止予定。

### - [x] T262. 冷パスのメモリ・CPU削減（Pydantic依存の解消、T261対応方針2） 規模M（2026-08-24完了、クラウド移行と併用でユーザー承認）

- 発端: T261の対応方針として「別クラウドサービスの調査」（ユーザーが別途比較検討）と
  「冷パスの計算・メモリ使用量削減」の併用を承認。後者の技術的フィージビリティを
  調査した結果（`domain/graph.py`の`Node`/`DirectedEdge`/`RoadGraph`/`WaySpec`が
  全てPydantic BaseModelで、都心規模（数万〜十数万Way/Edge）の`build_road_graph`が
  そのバリデーションコストを毎回払っていた）を踏まえ、既存の`LeanNode`/`LeanEdge`/
  `LeanRoadGraph`/`RoadGraphLike`基盤（T248候補1d、探索の読み取り専用パスに限定して
  導入済み）を「構築（build）」「保存（save）」パスへ拡張する形で実装した。
- **調査（Explore agent、実装前）**: `WaySpec`のコンストラクタ呼び出し・フィールド
  アクセス・`build_road_graph`戻り値の使われ方・`save_graph`引数の使われ方・関連
  テストのアサーションを全数洗い出し、Pydantic固有機能（`.model_dump()`等）への
  依存が0件であることを確認してから着手（障害になる箇所なし）。
- **実装1: `WaySpec`をdataclass化**（`domain/graph.py`）: 外部境界（API）を一切
  跨がない内部契約と確認済みのため、Lean/Full分離ではなく直接`@dataclass(frozen=True,
  slots=True)`へ変更。フィールド順を`node_ids`（必須）→デフォルト付きの順へ並び替え
  （全呼び出し元がキーワード引数のため無影響）。`tags`のミュータブルデフォルトは
  `field(default_factory=dict)`へ。
- **実装2: `build_road_graph`が`LeanRoadGraph`を返すよう変更**（`domain/graph.py`）:
  内部で構築する`Node`/`DirectedEdge`を`LeanNode`/`LeanEdge`へ変更。`LeanEdge.geometry`
  は「常に空」という規約（`get_graph_topology_in_bbox`側の規約）ではなく実座標を
  保持させることで、探索専用（`lean=True`）・地図表示（`lean=False`、実ジオメトリ
  必須）の両方の呼び出し元を同じ型で満たせるようにした（呼び出し元
  `GraphService.get_or_build_graph_with_attributes`は元々戻り値を`RoadGraphLike`
  Protocolで受けており、変更不要と確認済み）。
- **実装3: `save_graph`が`RoadGraphLike`を受けるよう変更**（`road_graph_repository.py`、
  本体・ファサード委譲の両方）。内部は元々`.node_id`/`.latitude`等の属性読み取りのみで
  完結しており、型注釈の変更のみで対応できた。
- **実装4: `Coordinates`（Pydantic、API境界のバリデーションが必要なため型自体は
  維持）への不要な変換を解消**（`domain/geo.py`・`domain/graph.py`・
  `domain/routing.py`）: `bearing_between`/`haversine_distance_km`の型ヒントを
  `Coordinates`固定から、`.latitude`/`.longitude`を持つ任意の型を受け付ける
  `LatLon`Protocol（新設）へ変更。`build_road_graph`の`_way_length_m`・bearing計算は
  座標ペアごとに`Coordinates`を構築し直していたのを、Pydanticバリデーション無しの
  `LatLonPoint`（`NamedTuple`、新設）へ変更。`domain/routing.py`の`find_nearest_node`/
  `find_nearest_node_indexed`（1リクエストにつき最大17回呼ばれる、T219）は、既に
  `latitude`/`longitude`を持つ`node`オブジェクトを`Coordinates`へ包み直さず直接渡す
  よう変更（無駄な構築そのものを無くした）。`Coordinates`自体はAPI境界（リクエスト
  スキーマの`ge=-90,le=90`検証等）で今後も使うため型は維持。
- **横展開の調査（ユーザー依頼「他にも同様修正を横展開できる個所はある？」）**:
  リポジトリ全体のPydantic BaseModelサブクラスを洗い出し、構築ホットパスの有無で
  仕分けた。
  - **対応済み**: `Node`/`DirectedEdge`/`RoadGraph`（T248候補1d）・`WaySpec`・
    `Coordinates`の内部ホットパス使用（本タスク）。
  - **追加候補として発見・未対応**: `EdgeAttributeCounts`/`ElevationAttribute`
    （`domain/attributes.py`）。`get_edge_materials_batch`・`get_graph_in_bbox`系の
    JOINクエリで、該当行があるEdgeの数ぶん（都心規模で数万件）ループ内でPydantic
    構築している。API層（ルーター）へは一切露出せず、`EvaluationService`が構造的
    アクセスのみで消費していることを確認済みで、`WaySpec`と同種の対応が可能と見込む。
    次に着手する場合の最有力候補として記録する。
  - **調査したが対象外と判断**: `WindGridPoint`/`WindGridResponse`（`domain/wind_grid.py`）
    はAPIレスポンスへ直接シリアライズされる境界型のため対象外。`POISpec`
    （`domain/osm_adapter.py`）はPBF取込バッチ（オフライン処理、リクエスト時間に
    影響しない）専用のため優先度低。
- **検証**: 隔離マイクロベンチマークで`Coordinates`→`LatLonPoint`の構築コストを
  直接計測（300,000回構築、`Coordinates`0.552秒→`LatLonPoint`0.185秒、**3.0倍**）。
  `Node`/`DirectedEdge`側の効果はT248候補1dの既存実測（171,461件で構築コスト推定
  11秒相当）を踏襲（実装が変わっていないため今回は再計測せず）。end-to-endの
  `bench_postgis_prepare.py`は、直前に実行したbackend全体テスト（155秒、通常47秒の
  3倍以上）等による同時実行負荷でノイズが大きく、今回は参考値に留める
  （システムが空いている時間帯に改めて計測することが望ましい）。
  backend全体1126件green（直列実行、xdist並列時の既存フレークはT248候補1と同じ理由
  で対象外）。
- 完了条件: 満たした（横展開調査を含む）。本番デプロイ後の`Instance failed`再発有無の
  確認、および追加候補（EdgeAttributeCounts/ElevationAttribute）への着手要否は
  T261側でユーザー判断を仰ぐ。
- **本番再検証（2026-08-24、デプロイ後）**: 同一座標・10kmで再検証したところ、
  `http_code=502`・`time_total=73.1秒`で失敗し、`/health`が10秒タイムアウト2回・
  9.75秒応答1回を記録、直後にプロセス`started_at`が更新（クラッシュ再現）。
  **T262（Pydantic依存削減）単独ではT261のクラッシュを解消できなかった**。
  この時点で本番コードはCOPY化を含まない（`b2e846f`切り戻し後のまま）状態であり、
  COPY化・T262いずれも原因ではないことが二重に確定したため、ユーザー指示により
  COPY化（T248候補1）を`git revert`でb2e846fを打ち消す形で再導入した（詳細は
  T248候補1の該当節参照）。T262（Pydantic依存削減）自体は性能改善として引き続き
  有効（クラッシュの根本解決ではないが、退行ではない）。

### - [x] T263. backendをOracle Cloud VM（DBと同居）へ移行 規模L（2026-08-24完了）

- 発端: T261で「Renderの無料プランのリソース制約（0.1 CPU/512MB）が冷パスクラッシュの
  真因」と確定（Renderのイベントログで「コードを何に変えてもInstance failedが発生」を
  確認済み）。ユーザー指示「クラウド移行する。Google Cloud Runで考えたいが、毎月の
  無料枠の範囲内で運用できる仕組みを構築できればという条件付」を受けて着手。
- **調査でCloud Runを断念**: Cloud Runの無料枠はegress（送信データ量）が月1GiBのみ
  （CPU/メモリの無料枠は180,000 vCPU秒・360,000 GiB秒と潤沢）。現在のbackendは
  basemapタイル・路面/事故/POIのMVTタイル・風の格子点データをそのままプロキシしており
  （`api/routers/basemap.py`等）、egressがボトルネックになり軽い利用でも無料枠を
  超過しうると判明。
- **既存Oracle Cloud VMへの同居を採用**: DBが既に稼働しているOracle Cloud Always Free
  VM（Ampere A1）を調査したところ、egressが月10TB（Cloud Runの1万倍）とほぼ無制限、
  SSH確認でメモリ8〜9GBの余裕があることが判明。PaaSの自動デプロイ・自動復旧は失うが、
  自前で（systemd/Dockerの再起動ポリシー・GitHub Actions経由のSSHデプロイ・
  nginx+certbotでのTLS）構築する方針とし、ユーザー承認を得て実施した。
- **実施内容**:
  - VM上にDocker・certbotを導入。既存nginx（`openmeteo-proxy.conf`と共存）へ
    新規`server`ブロックを追加。
  - TLS: 独自ドメイン不要な`sslip.io`（`193-123-166-150.sslip.io`）＋certbotで
    Let's Encrypt証明書を取得（自動更新設定済み）。
  - **ファイアウォールの二重構造が判明**: Oracle Cloud ConsoleのSecurity List
    （クラウド側）をユーザーが開放しても、**VM自身のiptables**（`netfilter-persistent`で
    永続化、22/5432/8080番のみ許可の既定REJECT構成）が別途80/443/22番を塞いでいた。
    両方の許可が必要と判明し、iptablesにも許可ルールを追加。
  - `.env`（DATABASE_URL・CORS_ALLOWED_ORIGINS・BASEMAP_PUBLIC_BASE_URL・
    OPEN_METEO_BASE_URL等、chmod 600・gitにコミットしない）をVM上に作成。
    `OPEN_METEO_BASE_URL`はDB同様に`http://localhost:8080/v1/forecast`
    （既存のOpen-Meteoリレープロキシへ同一VM内で直結）へ変更。
  - **CI/CD構築で発見した問題と対応**:
    1. 当初`docker/build-push-action`のcache-to type=ghaが既定の`docker`ドライバで
       非対応と判明（"Cache export is not supported for the docker driver"）、
       `docker/setup-buildx-action`を追加して解消。
    2. GitHub Actionsランナー（amd64）とOracle VM（Ampere A1、arm64）のアーキ不一致で
       `no matching manifest for linux/arm64/v8`が発生。`docker/setup-qemu-action`＋
       `platforms: linux/arm64`でクロスビルドを試みたが、**QEMUエミュレーションが
       10分超えても完了しないほど非現実的に遅い**と判明（numpy/scipy等のインストール
       自体がエミュレーション対象になるため）。ghcr.io経由のpush/pull方式を撤回し、
       **SSH経由でVM自身にgit pull→ネイティブdockerビルド→再起動させる方式**へ変更
       （実測約3分で完了）。
    3. デプロイ用SSH鍵（新規生成、ユーザーの個人鍵とは別）をVMの`authorized_keys`へ
       追加し、GitHub Secrets（`ORACLE_VM_SSH_KEY`・`ORACLE_VM_HOST`）へ登録。
    4. `--network=host`が必須と判明: PostgreSQLがVMにネイティブ（コンテナ外）で
       稼働しているため、Dockerの既定ブリッジネットワークだとコンテナ内の`localhost`が
       コンテナ自身を指し`ConnectionRefusedError`になった。ホストのネットワーク
       名前空間を共有することで解消。
  - フロントエンド（Render）側の環境変数を更新: `NEXT_PUBLIC_API_URL`（ブラウザ向け）と
    **`BACKEND_INTERNAL_URL`（Next.jsサーバー側のrewrites専用、basemap/MVTタイルの
    プロキシ先。`NEXT_PUBLIC_API_URL`とは別物と気づかず最初の疎通確認でbasemapが
    502になった）**をいずれも新backend URLへ更新。
- **検証**:
  - VM内直接実行でT261再現条件（現在地10km相当）: `total_ms=17,252`（17.25秒）→
    再実行`total_ms=4,639`（4.6秒）、いずれもHTTP 200・クラッシュなし。
    `docker stats`でメモリ658MB（ピーク）→599MB（安定）、6GB上限に対し十分な余裕。
  - CI/CDパイプライン自体をエンドツーエンドで検証（push→VM上でgit pull＋ビルド＋
    再起動が実際に成功することを確認）。
  - **実機ブラウザでの検証**（本番フロントエンド→新backend、Browserツール）:
    basemap表示成功、ルート生成（現在地10km相当）`durationMs=16,513`（16.5秒）・
    候補7件・クラッシュなしを確認。
- 完了条件: 満たした。1日間の並行稼働（Render backendは残したまま）で最終確認した後、
  Render側のbackendサービスを停止する（ユーザー合意、即削除はせずロールバック手段として
  当面残す）。
- **残作業: デプロイ確認機構（`/health`のcommit）の回帰を発見・修正（2026-08-24完了）**:
  T248の完了確認中、本番backendの`/api/debug/stats`が`"commit":null`を返し続けている
  ことに気付いた。原因はRender固有の自動注入環境変数`RENDER_GIT_COMMIT`
  （`docs/architecture.md`「Renderデプロイの反映確認」参照）がOracle VM上のDocker運用
  には存在せず、移行時に代替の注入手段を用意し忘れていたため。これにより
  「本番に実際にどのコミットが反映されているか」を`git rev-parse HEAD`と突き合わせて
  外部から確認する既存の仕組みが、backend側だけ恒久的に機能しなくなっていた
  （frontendは今もRender稼働のため`RENDER_GIT_COMMIT`は生きており影響なし）。
  - **修正**: `Settings.render_git_commit`を`Settings.git_commit`（環境変数`GIT_COMMIT`）へ
    改称し、[.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml)で
    VM上ビルド直前に`git rev-parse HEAD`した値を`docker run -e GIT_COMMIT=...`で
    明示的にコンテナへ渡すよう変更（`backend/app/config.py`・`main.py`・
    `api/routers/health.py`・`version.py`、レスポンスのJSONキー`commit`自体は変更なし
    のためOpenAPI生成物への影響なし）。
  - `docs/architecture.md`の「Renderデプロイの反映確認」節を「デプロイの反映確認
    （backend/frontendで注入元が異なる点に注意）」へ改題し、backend
    （`GIT_COMMIT`・deploy-backend.yml経由）とfrontend（`RENDER_GIT_COMMIT`・Render
    自動注入のまま）で注入元が異なる旨を明記。コードベースマップ内の旧記述
    （`render_git_commit`・「Renderデプロイの反映確認」という節名への参照）も
    あわせて更新。
  - テスト: `test_config.py`・`test_health.py`のフィールド名・env var名を追従。
    backend全体1132件green（直列実行）。
  - **並行してユーザーがRender側のbackendサービスを停止**（2026-08-24、1時間強の
    並行稼働で確認）。本タスクの完了条件（1日間の並行稼働）よりは短いが、ユーザー
    判断により前倒しで実施。

### - [x] T264. 冷パスのステージ別ログ追加＋closure_ms削減 規模S（2026-08-24完了）

- 発端: T263移行後、ユーザーから「30kmがなかなか帰ってこない」報告。調査したところ
  未split地点への初回アクセス（冷パス）で正常に重い処理（クラッシュではない）が
  進行中と判明したが、`prepare_ms`の内訳が`save_graph`の個別ログ以外に無く、
  どの段が支配的か特定できなかった。ユーザー指示「もう少し軽くできない？」を受けて
  ステージ別計測を追加し、実測に基づいて改善余地を探った。
- **ステージ別ログ追加**（`graph_service.py: get_or_build_graph_with_attributes`・
  `_build_search_materials_uncached`）: `closure_ms`（`get_way_specs_with_closure`の
  DB空間クエリ）・`build_ms`（`build_road_graph`の交差点分割）・`save_ms`
  （`save_graph`、既存ログと重複するが1行サマリとして再掲）・`materials_ms`
  （`get_edge_materials_batch`の材料バッチ取得）を追加。
- **実測（水戸・宇都宮、30km・未split地点）**: `build_ms`はT262のlean型化の効果で
  既に軽い（142,081 Edge規模でも2.7秒、8%）。残る内訳: `save_ms`(35%、既にCOPY化済み)・
  `closure_ms`(29%)・`materials_ms`(15%)・その他(14%)。
- **Open-Meteo 429の調査（横道、実害なしと確認）**: 実測中に`weather:open-meteo`で
  429が複数発生していたが、`/api/debug/stats`で確認したところエラー座標が全て
  テスト地点と無関係な東京都心だった。原因は検証用に開いたままだったBrowserタブ
  （東京都心の地図を表示し裏で風データをポーリング）と同時実行したことによる
  Open-Meteo側レート制限への同時ヒットで、移行自体が原因ではないと判定した
  （リレープロキシの経路・送信元IPは移行前後で変わっていない）。タブを閉じて解消。
  既存のリトライ＋stale fallback機構が機能しており、ユーザーへの実害は無かった。
- **closure_msの`EXPLAIN (ANALYZE, BUFFERS)`によるDB側切り分け**: 宇都宮30km
  （primary_ways=35,725）の実際のbboxで`get_way_specs_with_closure`のWay取得クエリを
  直接実行したところ、GiST索引（`idx_osm_raw_ways_geom`）を使ったパラレル
  ビットマップスキャンで**DBサーバー側の実行時間はわずか112ms**だった。
  `closure_ms=9,748ms`との差（約85倍）は、Python側のORM行構築・デシリアライズ・
  ネットワーク転送が支配的であることを示す。
- **原因**: `_way_spec_row_to_domain`（Way→WaySpec変換）・`_raw_node_row_to_coords`
  （Node座標変換）はいずれも`geom`列を一切参照しない（前者はosm_way_id/node_ids/
  highway/surface/tags/directionのみ、後者は緯度経度のみ）にもかかわらず、
  `select(OsmRawWayRow)`・`select(OsmRawNodeRow)`で**全列（geom＝LINESTRING/POINT
  込み）をORM行として取得**しており、不要なshapely decode・ネットワーク転送量を
  発生させていた。`get_graph_topology_in_bbox`（T248候補1c）が同じ理由でEdge/Node
  ともにST_X/ST_Y列指定へ最適化済みだったが、`get_way_specs_with_closure`（closure
  取得）と`get_graph_in_bbox`（表示用フルパス）のNode取得には未適用のまま残っていた。
- **修正**（`road_graph_repository.py`）:
  1. `get_way_specs_with_closure`のway取得クエリを列指定（geom除外）へ変更。
     `_way_spec_row_to_domain`ヘルパーは呼び出し元が無くなったため削除。
  2. 同メソッドのnode座標取得クエリをST_X/ST_Y列指定へ変更。
     `_raw_node_row_to_coords`ヘルパーは呼び出し元が無くなったため削除。
  3. `get_graph_in_bbox`（`lean=False`の表示用パス）のnode取得も同様にST_X/ST_Y
     列指定へ変更（`Node`は`latitude`/`longitude`のみを持ち`geometry`フィールドを
     持たないため、lean/フルどちらのパスでも本来Node側にgeom decodeは不要）。
     `_rows_to_road_graph`を列指定行を受け取る形へ変更。
  4. 未使用になった`geoalchemy2.shape.to_shape`のimportを削除。
- **横展開調査（他に同様の無駄がないか再チェック）**: リポジトリ全体の`select(Model)`
  パターンを再確認。`get_edges_with_geometry`（最終候補への実ジオメトリ付与、T218）・
  `get_graph_in_bbox`のedge取得は実際にgeometry表示が必要なため対象外と確認。
  MVT生成・最近傍検索等の生SQLは全てDB側でgeomを直接使う設計（Pythonへ転送しない）で
  無駄なし。`recompute_node_degrees`系のINSERT...SELECTもDB内で完結しPython側は
  一切geomに触れないため対象外。
- **検証**: `EXPLAIN ANALYZE`と同じ座標帯で正規化比較（エッジあたりの時間）:
  修正前（宇都宮、142,081 Edge）`closure_ms=9,748ms`＝68.6μs/edge → 修正後
  （高崎、207,280 Edge）`closure_ms=5,839ms`＝28.2μs/edge、**約2.4倍の改善**
  （規模が46%大きいにもかかわらず絶対値でも9,748ms→5,839msへ40%減）。
  backend全体1125件green（1件`test_save_graph_with_way_ids_to_replace_handles_...`は
  合成データ（全17,000wayが同一2点を使い回す、GiST索引が病的に遅くなる既知の
  テスト特性）の影響で並列実行時に既存dev DBの状態と衝突し一時的に長時間化したが、
  単体実行では45秒で成功・今回の変更（`road_edges`のINSERTではなく`osm_raw_ways`/
  `osm_raw_nodes`のSELECT側）とは無関係と確認済み）。
- 完了条件: 満たした。`build_ms`は既に十分軽く、`closure_ms`は容易な改善（geom列の
  不要な取得除去）で2.4倍高速化。残る`save_ms`（既にCOPY化済み）・`materials_ms`は
  さらなる高速化にDB側の構造的な見直しが必要になる規模のため、ユーザー判断により
  一旦ここで区切りとする。

---


---

**[T106〜T117ほか（交通ストレスレシピ外出し基盤・交通ストレスレシピ調整UIパネル・
天候取得502の再発・研究パラメータの導線改善・交通ストレス5段階化、いずれも
2026-08-17完了）はdocs/improvement-plan-archive/2026-08-17.md（同一ファイル、
バックエンド一時的到達不能の調査より後の節）へ移設済み]**

## テストスイート実行効率化の検討事項（2026-08-18・フロントvitestタイムアウト調査より）

**[本節の完了タスク（T125・T126・T128）は docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**


### - [ ] T127. 日本全国データ取込の実現可能性検証〔容量・所要時間〕規模不明（調査完了・未実施、2026-08-18） — トリガー: 全国展開の意思決定

- 発端: ユーザー相談「日本全国のデータ取込をするならどれだけの容量、時間がかかるか。
  現実的かを検証してほしい」。実施はせず調査のみ。
- **ファイルサイズ**（Geofabrik実測、2026-08-18時点）: 関東`kanto-latest.osm.pbf`
  466MB・全国`japan-latest.osm.pbf`2,358MB（8地域区分合計。北海道179MB/東北292MB/
  関東466MB/中部484MB/関西333MB/中国223MB/四国84MB/九州297MB）。**倍率は約5.06倍**。
- **ストレージ試算（問題なし）**: 本番DB（関東本土7都県、T101バックフィル後）は
  投入後2,050MB。単純比例で全国約10GB、契約中のOracle Cloudブロックストレージ150GBに
  対し約7%で十分収まる。
- **所要時間試算（不確実性が大きい、要追加検証）**: 本番投入ログ（2026-08-18、T101の
  バックフィル実行）のchunk単位タイムスタンプを精査したところ、**way数94万件を超えた
  あたりから処理速度が非線形に悪化し、投入完了（133万way）まで悪化し続け頭打ちの
  兆候が無かった**（序盤約0.28ms/way→終盤約1.97ms/way、最悪chunk単体で約7.44ms/way）。
  これは2026-08-15の関東拡大時（12章）にも「94万way超からの緩やかな減速」として
  記録済み・未解決の既知事象（GiST索引は対策済みで無関係と判明済み、原因未特定。
  Oracle Always Free枠が2026-06-15に無告知で4 OCPU/24GB→2 OCPU/12GBへ半減された
  小規模構成であることが一因の可能性）。全国規模（約665万way、133万wayの5.06倍）へ
  外挿すると、**楽観（悪化がKanto終了時点の水準で頭打ちすると仮定）で約3.2時間、
  現実的（悪化トレンドがそのまま継続すると仮定）には半日〜それ以上**という、
  133万way超の規模を一度も実行したことが無いゆえの幅の大きい見積もりにしかならない。
- **ローカル開発機の制約**: 作業機のCドライブが237GB中221GB使用済み・空き16GBのみ。
  日本全国PBF（2.3GB）のダウンロードは可能だが、pyosmiumの位置インデックス
  （大規模ファイルではディスクバック方式）の一時領域を考えると余裕は乏しい。
- **推奨する進め方**: いきなり全国投入をテストせず、中間規模（例: 関東+中部+関西＝
  1,283MB、全国の54%・関東の2.75倍）で先に投入し、94万way超の減速が実際にどこまで
  悪化する／頭打ちするかを実測してから全国投入の可否を最終判断する。より精度の高い
  試算をするなら、日本全国PBF（2.3GB、要ダウンロード許可）でway/node/POI件数を
  ローカルで正確にカウントする（DB書き込み無し）ことも検討候補。
- 完了条件（実施する場合の目安）: 上記の段階的検証（中間規模での実投入）で94万way超の
  減速カーブが頭打ちすることを確認し、全国規模の所要時間・リスクを再試算してから着手判断。

**[統合レビュー対応（2026-08-18・review:all第3回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**

## 評価システムの層構造再設計（2026-08-18・区間評価の一次/二次/三次分離）

**[本節の完了タスク（T137・T138・T139・T140・T141・T142・T143・T144・T145b・T161・T162・T146・T147・T148・T149・T151・T150・T152）は docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**


ユーザーから「一次データ（OSM等の生属性）・二次データ（軸スコア）・三次データ（重み付き合成コスト）の
役割が混ざっている」という課題認識のもと、層構造の再設計プロンプトが提示された。現状把握
（本セッション、Explore調査＋主要ファイル直接確認）の結果、提案の一部（〇次ハード制約の分離、
軸内係数と三次重みの分離、レシピの上書き可能な外部化）は既にT16〜T130の過程で実現済みだが、
以下は未実装または方向性の異なる決定事項として残っていた:

- **軸構成**: 提案は6軸（car_stress/accident/surface_q/stop_density/gradient/night）。現状は
  9軸（勾配・風・路面・停止密度・車の圧迫感・自転車インフラ・交差点密度・事故密度・安全度）で
  提案より粒度が細かく、かつ「車の圧迫感」と「安全度」が道路適正(N1)・自動車密度(N2)を意図的に
  共有する設計（T130、本日完了）になっている
- **レジストリ制**: `docs/complexity-review-2026-08-16.md`が「レシピが2つ目しかない段階では
  汎用レジストリ化は過剰」として明示的に見送っていた

ユーザーに確認のうえ、以下の方針で進める（詳細は本セクション追加時のセッション記録参照）:

1. **安全度軸は提案どおり廃止し、事故実績(accident)・夜間(night)へ分割する**（T130の
   「共有基盤化」路線からの転換。安全度が持つ街灯・トンネル補正はnight軸へ、highway別基準値・
   cycleway・maxspeed・lanes・指定路線補正はcar_stress軸へ統合し、事故密度は既存のaccident軸
   （変更なし）へ一本化）
2. **一次属性・二次軸のレジストリ制を導入する**（2026-08-16時点の見送り判断を、軸数が
   6〜9・将来のオープンデータ追加を見込む今回のスコープでは更新する）
3. **DB移行・両ルーティングエンジン書き換え・フロント全面改修を含む大規模変更のため、
   本セクションでタスク分割してから段階的に着手する**（1タスク=1コミット、着手前後で
   全テストgreenの原則をそのまま適用）

**未決定のまま残っている論点**（各タスクの着手時に確認・記録する）:

- ~~交差点密度（intersection_density）・自転車インフラ（bicycle_infra）は提案の6軸表に
  明示的な帰属先が無い~~ → **2026-08-18、設計プロンプト改訂で解決**。自転車インフラは
  car_stressの入力へ統合（T138、従来方針のまま）。交差点密度は単独軸を持たず、
  信号・横断歩道・一時停止・踏切と同じstop_density軸へ「タグなし交差点」を独立した
  低い重みのカテゴリ（例: `unsignaled_intersection: 0.3`、signal=1.0比）として吸収する
  （新規T149）。intersection_densityがstop_densityへ寄せられる理由は「立ち止まる／
  減速する頻度」という同じ性質の指標だから、car_stress（走行中の車との近接ストレス）
  ではなく質的に異なるという設計判断（改訂後の設計プロンプト「現行9軸からの帰属先」節）。
  bicycle_infra統合後は`accident`と`car_stress`の相関を確認し、二重計上懸念を潰す
  （T138の完了条件へ追加）。この決定を受け、T137で先行登録していた`intersection_density`
  単独軸はレジストリから削除しstop_density側のinputsへ統合する後方修正を実施済み（下記
  T137実装メモ追記参照）
- 提案の〇次フィルタは「自転車通行不可・高速道路」のみだが、現状の`DISALLOWED_HIGHWAY_TYPES`は
  `trunk`/`trunk_link`も含む（高速道路より広い）。また現状の`motor_vehicle=no`（自転車可の
  車両通行禁止）は〇次のハード除外ではなく二次軸内の最善値1固定という別ロジックであり、
  提案の「通行不可はハード制約へ統合」との対応関係を明確にする必要がある（T140で扱う）。
  → **2026-08-23、T231で解決済み**: 現行実装（二次軸内の最善値固定）を正とし、0次へは
  移さない方針を確定・記録した（`docs/architecture.md`1029〜1057行目参照）

### - [ ] T145. 地図レイヤーパネルをレジストリ駆動にし、三次（合成コスト）を既定表示レイヤーとして
  新設する 規模L →（2026-08-19、T145a/T145bへ分割・方針再定義）

- 背景: 設計プロンプトのレイヤー表。現状の`mapLayers.ts`は10レイヤーが個別列挙で、
  「常時表示は合成コストのみ」に対応する三次レイヤー自体が存在しない。一次・二次は
  レジストリ（T137、ただしフロント側は別途TypeScript版が必要）から動的に列挙し、軸を
  増やしてもレイヤーパネル・凡例の改修が不要な構造にする。
- 分割の経緯（2026-08-19）: ユーザーと方針を協議し、当初案の「二次レイヤーの動的生成」を
  具体化する過程で2つの重要な制約を確認した。(1) 現行タイルは全ユーザー共有キャッシュ
  （Cache-Control: max-age=3600）のため、レシピ依存の軸最終値をサーバー側で焼き込むと
  研究モードの重み上書き（将来的にはユーザー別レシピ、T141のJSON/DB化が布石）と矛盾する。
  (2) 逆にaccident/stop_density軸は入力データ（事故点・POI集計）自体がタイルに無いため、
  クライアント側expressionでは原理的に計算できない。この2つから、アプリ自身の層構造を
  配信アーキテクチャへ写す「**事実はタイルに、解釈はクライアントに**」方針を採択した:
  一次属性・事前集計カウント（レシピ非依存の事実）はサーバー焼き込み、二次軸スコア
  （レシピ依存の解釈）はクライアントexpressionで計算する。三次（合成コスト）レイヤーは
  本タスクのスコープから外す（係数検証が別途必要なため、実施時期はユーザー判断）。

### - [x] T145a. night軸の専用レイヤーを追加する 規模S〜M（2026-08-24、T278で解消）

- 背景: 6軸のうちnightだけ対応する地図レイヤーが無い。ただし現OSMデータではlitタグが
  疎で、レイヤーを作っても他軸との差がほぼ見えないことをユーザーと確認済み（2026-08-19）。
- 対応方針: T145bの汎用機構へ普通に乗せる（専用実装はしない）。データが充実した時点で
  レジストリ登録のみで地図に現れるのが理想形。
- **解消（2026-08-24、T278）**: night軸の材料（no_lit/has_tunnel）がMVTタイルへ
  焼き込み済みで`tile_property_needs_runtime_scale`/`tile_property_direction_dependent`
  もFalseのため、`domain/axis_display.py: derive_ramp_inputs`の汎用自動導出
  （FlagSumShape、`tests/test_axis_display.py: test_flag_sum_shape_derives_subset_sum_thresholds`
  で検証済み）がnight軸にもそのまま適用され、レジストリ登録（既にAXIS_DEFINITIONSに
  `is_published=True`で存在）だけで地図に現れるようになった。対応方針どおりの決着。
  litタグデータ自体の疎密（2026-08-19時点の懸念）は引き続き別問題として残るが、
  レイヤーの有無をそれに依存させる必要が無くなったため、当初の完了条件
  （「意味のある差を表示できること」）はこの解決策で置き換わった。この解消は
  T278起票時点（下記「目論見書による二画面構想の正式化」節）で一度記録済みだったが、
  本エントリのチェックが更新されていなかった（2026-08-26、ユーザー指摘の食い違い
  確認で発覚・是正）。
- 完了条件: ~~night軸レイヤーが地図上で意味のある差を表示できること。~~ 上記のとおり
  完了条件自体を置き換えて解消済み。

### - [x] T266. 0次ハードフィルタをAPI・ベクトル化計算パスへ配線する 規模M（2026-08-24完了）

- 背景: 2026-08-24、ユーザーから「自転車専用道をなるべく優先して探索したい」という要望を
  受けて調査した結果判明したギャップ。`domain/evaluation.py: is_edge_allowed`は
  `hard_filters`引数でフィルタ名（`no_bicycle`/`motorway`/`trunk`、T140）ごとの
  個別ON/OFFに対応する設計になっているが、(1) APIレイヤー（`api/routers/routes.py`）には
  この`hard_filters`を受け取るフィールドが一切存在せず、(2) 実際のルート生成が使う
  ベクトル化計算パス`compute_edge_costs_bulk`はコード内コメントに明記されている通り
  「hard_filters引数によるレシピ単位の上書きは本関数では未対応」で`DEFAULT_HARD_FILTERS`を
  決め打ちしている。つまり設計（ドメイン層のシグネチャ）は用意されているのに、APIも実計算
  パスも配線されておらず、研究モードから0次フィルタを触る手段が現状存在しない。
- 対応方針:
  1. `compute_edge_costs_bulk`へ`hard_filters`引数を追加し、`HARD_FILTER_HIGHWAY_TYPES`
     走査部分の`DEFAULT_HARD_FILTERS`決め打ち参照をパラメータ化する（`is_edge_allowed`と
     判定基準が食い違わないよう、テストで両者の同値性を担保する）。
  2. `routes.py`の`RouteGenerationRequest`へ`hard_filters`相当のフィールドを追加し、
     APIから受け取れるようにする（コミット時の同期ルールに従い
     `export_openapi.py`→`npm run generate:api`→`frontend/src/types/generated/`の
     diffクリーンを確認）。
  3. 拡張除外設定（highway種別3種＋no_bicycle以外の任意条件、例: 未舗装除外）の要否は
     スコープを絞り本タスクでは着手しない。まず既存4種フィルタの選択的ON/OFFのみを実装し、
     利用実績を見てから任意条件の拡張は別タスクとして起票する。
  4. ~~研究モードUIへ0次フィルタのON/OFFチェックボックス群を追加する~~ → **2026-08-24、
     目論見書承認によりUI側はT267（一般向けルート設定画面の「除外する道路」チップ）へ
     移管**。本タスクはbackend配線（上記1〜2）までをスコープとする。
- 完了条件: APIリクエストで`no_bicycle`/`motorway`/`trunk`を個別にON/OFFしてルート生成でき、
  OFFにしたフィルタに該当する道路が実際に経路候補へ現れることを確認する（UI経由の
  実機確認はT267の完了条件側で行う）。
- **実装メモ（2026-08-24完了）**:
  1. `compute_edge_costs_bulk`/`compute_edge_cost`（scalarオラクル側も合わせて）へ
     `hard_filters: frozenset[str] | None`引数を追加。抽出フェーズ冒頭で
     `active_hard_filters = hard_filters or DEFAULT_HARD_FILTERS`を1回だけ計算し、
     highway種別判定・`no_bicycle`判定の両方をこの値で判定するよう修正した。
  2. **副次的なバグ修正**: 従来の`compute_edge_costs_bulk`は`no_bicycle`フィルタの
     ON/OFFに関わらず`bicycle=no`のEdgeを常時除外していた（フィルタ名チェックが
     漏れていた）。`is_edge_allowed`とロジックがずれていたバグで、今回`hard_filters`の
     配線と同時に修正した（`no_bicycle`をhard_filtersから外すと実際に候補へ現れることを
     `test_bulk_hard_filters_empty_allows_bicycle_no_edge`で確認）。
  3. `EvaluationService.evaluate_graph`→`RoadGraphEngine`（コンストラクタで保持、
     `penalty_strength`/`max_average_grade_percent`と同じパターン）→
     `dependencies.py: RouteGenerationSetup`/`get_route_generation_builder`まで、
     既存の`max_average_grade_percent`と全く同じ経路で配線した。openrouteserviceエンジンは
     対象外（従来の`max_average_grade_percent`等と同じ「road_graphエンジンのみに効く」
     方針を踏襲）。
  4. API: `routes.py`に`HardFilterOverride`（`RootModel[dict[str, bool]]`、
     `RoutePreferenceWeights`と同じ「全3キー必須」検証）を新設し、
     `RouteGenerateRequest.hard_filters`・`GenerationConditions.hard_filters`へ追加。
     省略時は`DEFAULT_HARD_FILTERS`（全フィルタ有効）がconditionsへエコーされる。
  5. OpenAPI再生成・フロント型追従（`api.d.ts`/`openapi.json`）、
     `frontend/src/types/route.ts`へ`HardFilterOverride`型を追加。
  6. 検証: backend全1140件green（新規5件: bulk/scalar一致・no_bicycleバグ回帰・
     API上書き/エコー/バリデーションエラー）、フロントtsc/vitest 516件green。
     docs/architecture.md（Request/Response例・TS型定義）へ`hard_filters`を追記。

**[統合レビュー対応（2026-08-19・review:all第4回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-19.md へ移設済み（2026-08-23棚卸）]**

**[地図レイヤー階層の次数反転（2026-08-19・T128/T161/T162の継続検討） の全タスクは docs/improvement-plan-archive/2026-08-19.md へ移設済み（2026-08-23棚卸）]**

**[動的要素（風・降雨等）の導入（2026-08-20・調査起票） の全タスクは docs/improvement-plan-archive/2026-08-20.md へ移設済み（2026-08-23棚卸）]**

**[統合レビュー対応（2026-08-22・review:all第5回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-22.md へ移設済み（2026-08-23棚卸）]**

## 動的データの追加候補整理（2026-08-22・雷ほか未着手データの棚卸しと起票）

**[本節の完了タスク（T204・T205・T210・T211・T212・T213・T214・T215・T216・T217）は docs/improvement-plan-archive/2026-08-22.md へ移設済み（2026-08-23棚卸）]**
**[T12実装スタックの完了タスク（T218・T218a・T219・T220）は docs/improvement-plan-archive/2026-08-23.md へ移設済み（2026-08-23棚卸）]**


ユーザー要望「動的データの対応追加を進めたい。雷等の改善計画未記載の物含めて、取り込むべき
データを整理して」を受け、既存の動的要素導入（T170〜T178、上記節）以降に検討されていなかった
候補を実機調査つきで棚卸しした（2026-08-22）。T171実装メモが「雷ナウキャストは別レイヤー・
別調査として残す」としていた宿題も含む。設計判断はT170〜T178節と同じ方針を踏襲する
（「回避一択」の危険は評価軸にせず警告表示、動的データの欠測はT87のレイヤーデータ状態機構
へ正直に載せる）。

**実施順序（Phase）**: Phase A（T204）・Phase B（T205）は完了（2026-08-22）。

- **Phase A（最小コスト・即着手、完了）**: T204（雷ナウキャスト、竜巻はオプション同梱）。
  T171と同じタイル配信系で、プロダクトコード（`thns`/`targetTimes_N3.json`）の実在を
  今回のPlaywright実機確認で確定済みのため、残る作業は実装のみ。
- **Phase B（警告バッジ基盤、完了）**: T205（気象警報・注意報）。T174（WBGT）と警告バッジの
  表示枠を共有できるため、この基盤を先に作ってからT174へ進むと二重実装を避けられる
  （`WarningBadge.tsx`として実装済み、T174着手時はこれを再利用する）。
- **Phase C（既起票の優先順位再確認、内容変更なし）**: T176（河川敷冠水、台風期の今が
  調査の好機）→ T175（花粉、冬季着手で間に合う）→ T177（交通量時間帯補正、季節非依存）。
- **Phase D（トリガー付きDEFER・調査のみ）**: T206（積雪・凍結）・T207（雷ポテンシャル
  CAPE延長予報）・T208（視程・霧）・T209（黄砂・PM2.5）・T210（通行止め・道路規制調査）。
  いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

### - [ ] T206. 積雪・凍結情報（JMA「今後の雪」タイル・Open-Meteo積雪変数） 規模S〜M — トリガー: 冬季前（毎年11月）またはユーザーからの着手指示

- 発端: ユーザー要望（2026-08-22）。JMA「今後の雪」タイル配信
  （`https://www.jma.go.jp/bosai/jmatile/data/snow/targetTimes.json`、200 OK実機確認済み。
  `snowd`積雪深・`snowf01h`〜`snowf72h`各時間降雪量を含む）とOpen-Meteoの積雪変数
  （`snowfall`・`snow_depth`・`freezing_level_height`、いずれも実機取得確認済み）が
  候補。関東平野部では対象日が限定的だが、山間部ロングライドでは凍結・積雪が
  「回避一択」の危険になりうる。
- 対応方針（トリガー到達時）: 表現形式（rasterTileの面表示 vs 警告バッジ）・評価軸に
  組み込まない方針（凍結は危険側、警告表示のみ）を含めて着手前に再検討する。
  Open-Meteo経由の`freezing_level_height`（凍結高度）は既存のget_forecast_many格子へ
  変数追加するだけの低コストな経路（T183と同じ相乗り）。
- 完了条件（着手時に確定）: 積雪・凍結の警告が該当時期・該当地点で表示され、対象外
  シーズンは取得自体を行わずUIにも出ないこと。

### - [ ] T207. 雷ポテンシャル（CAPE）による延長予報の検討 規模S — トリガー: T204（雷ナウキャスト60分先まで）だけでは見通しが不足するという利用実績・要望が出た時点

- 発端: ユーザー要望（2026-08-22）。Open-MeteoのCAPE（対流有効位置エネルギー、
  実機取得値2040 J/kgを確認済み）は雷雲発達の指標として60分より先の見通しを提供できるが、
  「CAPE値→雷リスク」への変換は気象学的な閾値設定を要し専門性が高い。T204の
  雷ナウキャスト（実況〜60分）が既に主要な需要をカバーする可能性があり、CAPE延長は
  過剰投資になりうるため、実際に「60分より先も知りたい」という需要が確認できてから
  着手する。
- 対応方針（トリガー到達時）: 降水延長予報（T183、gridFill表現）と同じ経路
  （wind-grid格子へのCAPE変数相乗り）が使えるか検討。閾値設定（気象庁・気象予報士向け
  資料等を参照）を先に固めてから実装する。
- 完了条件（着手時に確定）。

### - [ ] T208. 視程・霧情報の導入可否を調査する 規模S（調査のみ）— トリガー: 山間部・河川霧発生地域での利用報告、または優先度見直し

- 発端: ユーザー要望（2026-08-22）。Open-Meteoの`visibility`変数は取得可能
  （実機取得値29,340m）だが、サイクリングでの実用価値（山岳・河川霧向け、早朝走行時の
  視認性）は関東平野中心の現状ユーザー像に対して優先度が低いと判断。
- 対応方針（調査項目、トリガー到達時）: (1) 表示形式（警告バッジ vs 数値表示）、
  (2) 「霧が出やすい」を判定する閾値（湿度・気温差との複合判定が必要か）、
  (3) 単独の情報価値が低い場合は気温・湿度と合成した「朝もや注意」のような複合指標に
  するか。調査結果を本エントリへ追記し実装可否を判断する（T50〜T54のJICE見送りと同じ
  「調査の結果、見送り」も正当な結論）。
- 完了条件（調査時に確定）。

### - [x] T209. 黄砂・PM2.5情報の導入可否を調査する 規模S（調査のみ、2026-08-23完了・判定: 実装可能、Open-Meteo採用を推奨）

- 発端: ユーザー要望（2026-08-22）。環境省そらまめくん（大気汚染物質広域監視システム）
  等が候補だが未調査。T175（花粉）が調査する「季節性の大気質情報をどう表示するか」
  （春季限定バッジ等の設計）と表現形式を共有できる可能性が高いため、T175の調査結果
  （利用規約・提供期間・地点粒度の調査知見）を踏まえてから着手する方が手戻りが少ない。
- 対応方針（調査項目）: (1) そらまめくんの公開データ提供経路（API/CSV）と利用規約、
  (2) Open-Meteoの大気質API（`air-quality-api.open-meteo.com`、別ドメイン・別クォータ）で
  PM2.5・黄砂（dust）が日本域で取れるかの実データ確認、(3) 表示形式（T175と共通化できるか）。
- 完了条件: 上記3点の調査結果と実装可否の判断が本エントリに記録されること。
- 依存: T175（完了済み）。

- **調査結果（2026-08-23）**:
  1. **そらまめくん（環境省）**: `soramame.env.go.jp/apiManual`にAPI仕様公開あり。
     JSON形式で測定局ごとの時報値（PM2.5・SPM・SP等）を取得可能、APIキー不要。ただし
     **著作権・利用ルールが測定局の運営主体で分かれており**、「国設局」（全国のごく一部）
     以外の大多数の地方公共団体運営局は個別に当該自治体へ問い合わせが必要
     （T175のウェザーニューズ花粉データと同型の「個別許諾が要る」ハードル）。取得可能
     期間も「現在月から遡って1年間のうち3か月以内」という制約があり、高頻度アクセスも
     自粛要請（他クライアントと同じ暗黙のマナー型レート制限）。全国一律で無条件利用
     できる公開データとは言えない。
  2. **Open-Meteo大気質API**: 実機確認（東京、2026年8月・2026年4月の2時点）で
     **PM2.5は常時実データ**（8月: 11.4〜94.3μg/m3、明確な日内変動あり）、
     **dust（黄砂）も黄砂シーズン相当の4月には実データ変動を確認**（240時間中159時間で
     非ゼロ、最大8.0μg/m3）、非シーズンの8月は終始0.0（データ欠損ではなく「観測上
     黄砂無し」の妥当な値と判断）。公式ドキュメントで両変数とも**CAMS Global
     （45km解像度、全球対応）由来と明記**されており、T175のpollen（欧州限定・
     日本は構造的にnull）とは異なり**技術的な対応制約は無い**。
  3. 表示形式: T174（WBGT）・T212（河川氾濫予報）と同じ`WarningBadgeList`共有
     コンポーネントが妥当。環境省の「注意喚起のための暫定的な指針となる値」
     （PM2.5日平均70μg/m3）等の既存の公的閾値を基準に警告バッジを出す設計が
     想定できる。
- **判断: 実装可能、Open-Meteo大気質APIの採用を推奨**。そらまめくんは全国一律の
  無条件利用ができない（T175と同型の許諾ハードル）ため不採用。Open-Meteoは
  技術的制約が無く、`weather_client.py`と同じ統合パターン（別ドメイン・別クォータの
  ため既存の天候クォータへ影響しない、TTLキャッシュ・tenacity再試行の型を流用可能）
  で実装できる。**本タスクは調査のみで完了とし、実装（規模M相当、フロント側の
  バッジ表示・axis/レイヤー設計を含む）は別タスクとして着手指示を待つ**（CLAUDE.mdの
  M以上の変更は着手前にタスクエントリを作成するルールに従う）。

### - [ ] T221. 評価軸のフルレジストリ駆動化＋GUI編集基盤 規模L（Part 3完了でStage Dまで到達、Stage E[GUI編集画面]は未着手）— トリガー: ユーザーの実装着手指示

- 背景: T12原則7の再検証（2026-08-23）で、現行7軸の変換ロジックが実質3テンプレート
  （折れ線補間・カテゴリ変換・フラグ加算、+car_stressの「レシピ→レベル→折れ線補間」の
  複合形）に還元できることが判明した。ユーザーから「将来的には見た目の磨き込み部分だけ
  IFで切り出して残し、裏のロジック部分はすべてフルレジストリ駆動化したい」という将来像
  （2026-08-23）を受け、独立したADRとして起票した。
- ADR: `docs/decisions/t221-axis-registry.md`（ドラフト、2026-08-23起票）。
  ロジック層（素材選択・変換テンプレート・パラメータ・重み・合成）を完全レジストリ駆動へ、
  見た目（アイコン・略名・案内文）は無指定時に汎用フォールバックが効くUIオーバーライド層へ
  分離する方向性のみ承認済み。段階構成（Stage A: 4テンプレートへの実装移行〜Stage E:
  GUI編集画面）・具体的スキーマ・DB化の要否は未承認のドラフトのまま。
- T12（探索速度）とは独立した設計課題だが、素材カタログ（T218参照）を共有する。
  Stage D（DB化）はT12 Part 2のキャッシュ無効化条件（軸定義の版数）との整合が要る。
- 未決の製品判断: GUI編集を誰に開放するか（研究モード限定か否か）、軸追加・重み変更の
  安全性検証をどう設けるか。詳細はADR末尾参照。
- **進捗と価値の変化（2026-08-23追記、統合レビュー第7回 統合-2）**: Stage Aは
  T239で実施済み（`domain/axis_templates.py`、7軸の変換ロジックを4テンプレートへ
  実装移行、外部契約不変）。あわせてT240のevaluate_graphベクトル化により、
  **評価軸追加の1本道が「スカラー2箇所＋配列3箇所」へ増えた**（difficulty.pyの
  スカラー関数と配列版関数の対、compute_edge_costs_bulkの抽出フェーズ・計算フェーズ
  への追記が新たに必要。同期ドリフトは`test_evaluation_bulk.py`のスカラー版全Edge
  一致テストが検知するため黙って壊れるリスクは低い）。**Stage B以降（レジストリ駆動化）
  でレジストリからスカラー/配列両実装を導出できれば、この二重管理が解消する**——
  ベクトル化によりStage B以降の価値が起票時点より上がったことを、将来の着手判断の
  材料として記録する。
- **Part 2着手（2026-08-23、ユーザー指示「T221に着手して」）**: スコープは
  ADRのStage B＋C相当。Stage D（DB化）・Stage E（GUI編集画面）はADR自身が
  「製品判断待ち（GUI編集の開放範囲・極端な重み設定への歯止め・T12 Part 2キャッシュ
  無効化条件との整合）」と明記しているため**今回も対象外のまま**とする。
  並行セッションがT250（モバイル上部バーUI、`page.tsx`等）を作業中のため、
  本タスクは専用worktree（ブランチ`t221-registry`）で実施し、masterへの統合は
  T250のコミット後に行う。実施内容の分割:
  1. **C-1 軸定義のデータ化**: 新規`domain/axis_definitions.py`へ、ADRの
     `AxisDefinition`スキーマ（axis_id・材料・shape・shape_params・default_weight）を
     宣言データとして7軸分定義する。breakpoints等の定数は`difficulty.py`/`night.py`から
     ここへ移動（定数の片側import原則）。
  2. **C-2 評価ロジックのレジストリ駆動化**: 汎用評価関数（スカラー/配列両対応）が
     `AxisDefinition`を読んでスコアを返す形にし、`difficulty.py`の`*_difficulty`
     スカラー関数を定義参照の薄いラッパへ（外部シグネチャ不変）、`*_array`個別実装は
     廃止して同一定義から導出（**T240で増えたスカラー/配列二重実装の解消**）。
     `compute_edge_axis_scores`/`compute_edge_costs_bulk`の軸ループを
     `AXIS_DEFINITIONS`駆動へ置き換え、軸ごとのハードコード行を消す。
  3. **B-1 内部dict化**: `AxisDifficulties`（NamedTuple）→`dict[axis_id, float | None]`、
     `evaluate_axis_difficulties`をレジストリループの薄い関数へ。両エンジンの
     区間ビルダー追従。
  4. **B-2 重みのdict化**: `RoutePreference`→axis_idキーの重み辞書（既知axis_id集合に
     対する全キー必須バリデーションは維持）、`route_preference.yaml`のキーをaxis_idへ、
     API層`RoutePreferenceWeights`→dict形式へ一般化。OpenAPI再生成＋フロント追従
     （`evaluationAxes.ts`の手書き対応表`PREFERENCE_WEIGHT_KEY_BY_AXIS_ID`廃止、
     `WeightPanel`のyamlミラーのaxis_idキー化）。`AXIS_WEIGHT_FIELD_TO_AXIS_ID`・
     `_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`の手書き対応表を削除。
  5. 整合: `registry_defaults.py`（表示カタログ）と`AXIS_DEFINITIONS`（評価定義）の
     軸集合突き合わせテスト、docs/architecture.md追従（同一コミット）。
  - 見送り（本Part内で判断）: `RouteSegmentDetail`の軸別固定フィールドのdict化は
    ADRでも「検討」止まりのため今回は据え置く。**保留の影響**: 軸を追加する際、
    評価・重み系はデータ変更のみで済むようになる一方、区間詳細表示（route.py＋
    両エンジンの区間ビルダー＋フロントのrouteStyleModes）へは引き続き軸ごとの
    手書き追記が必要なまま残る（ルート生成・探索コストはブロックされない。
    表示系の追従漏れは新軸の区間色分けが出ないという形で顕在化する）。
    必要になった時点で別タスクとして起票する。

- **Part 2実装メモ（2026-08-23完了、ブランチ`t221-registry`）**:
  - **C-1/C-2＋B-1（コミット`522e957`）**: 新規`domain/axis_definitions.py`に
    `AXIS_DEFINITIONS`（7軸の材料・shape・パラメータ・既定重みの宣言データ。辞書の
    挿入順が合成の加算順として意味を持つ——Neumaier加算のビット一致条件）と
    汎用評価関数`evaluate_axis_scalar`/`evaluate_axis_array`を実装。
    `difficulty.py`/`night.py`のスカラー関数は定義参照の互換ラッパ（None・負値ガードのみ
    担当）となり、`*_difficulty_array`群を削除して**T240で生じたスカラー/配列二重実装を
    解消**。`compute_edge_axis_scores`/`compute_edge_costs_bulk`/
    `axis_inspector_breakdown`/`evaluate_axis_difficulties`の軸ループをすべて
    `AXIS_DEFINITIONS`駆動化（軸ごとの1行ハードコードが消滅）。`AxisDifficulties`は
    axis_idキーの辞書＋compositeへ一般化。
  - **B-2（コミット`20cd840`）**: `RoutePreference`をaxis_idキーの重み辞書`weights`へ
    一般化（既定値は`AXIS_DEFINITIONS.default_weight`が単一ソース、部分指定は既定値補完・
    未知キーはエラー、night動的化は`with_weight()`）。手書き対応表
    `AXIS_WEIGHT_FIELD_TO_AXIS_ID`・`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`・
    `preference_to_axis_weights`を削除。API層`RoutePreferenceWeights`はRootModel(dict)化
    （全axis_id明示＋非負の検証で「省略時に既定値が黙って入らない」従来方針を維持）。
    `route_preference.yaml`のキーをaxis_idへ移行。`axis-catalog.json`へ
    `preference_defaults`を追加し、フロントの既定重み手書きミラー・
    `PREFERENCE_WEIGHT_KEY_BY_AXIS_ID`対応表を廃止（キー集合の突き合わせは
    `evaluationAxes.test.ts`が生成物と機械照合）。OpenAPI再生成＋型追従、
    docs/architecture.md追従（重み表・APIサンプル・1本道・レジストリ節）。
  - **検証**: backend全1077件green・frontend全501件green・tsc green。dev DB実データ
    54,020エッジでscalar/bulk全件一致（不一致0）。`bench_evaluate_graph`は同一負荷条件の
    masterと同水準（性能回帰なし。並行セッション負荷で絶対値は不安定なためmin値で比較、
    68k: 1.17s vs 1.57s / 121k: 2.40s vs 2.50s）。実機API検証: 旧形式キー422拒否・
    部分指定422拒否・新形式全軸で生成成功（road_graph、5候補）＋conditionsエコー一致。
  - **達成状態**: 既存4テンプレート＋既存材料で表現できる新しい軸は、
    `AXIS_DEFINITIONS`への1エントリ追加＋`registry_defaults.py`の表示登録＋生成物再生成
    だけで、探索コスト・区間インスペクタ・重みAPI/UI（スライダー・既定値）まで反映される。
    残る手書き追記は区間詳細表示（`RouteSegmentDetail`固定フィールド、上記保留）のみ。
  - **残作業（保留、影響範囲付き）**:
    1. **masterへの統合**: 完了（2026-08-23、並行セッションのT250〜T252-255コミット後に
       マージ。コンフリクトはdocs/improvement-plan.mdのみで、`page.tsx`はT250側の変更と
       自動マージされた）。
    2. **研究タブ重みUIのPlaywright実機確認**: 完了（2026-08-23、master統合後に実施）。
       e2eスモーク2件green＋一時spec（T250と同じ運用、検証後削除）で研究タブの
       区間難易度の重み7軸がカタログ由来のラベル・既定値（preference_defaults）で
       表示されることを実機確認した。あわせて`e2e/fixtures.ts`のroute_preference
       フィクスチャが旧キーのまま残っていたのを発見し修正（RootModel化で
       RoutePreferenceWeightsがindex signature型になったため、旧キーでも型検査を
       通ってしまう——この種のドリフトは今後`evaluationAxes.test.ts`のキー集合照合と
       API側の422検証が防波堤になる）。
  - Stage D（レジストリDB化）・Stage E（GUI編集画面）は引き続き製品判断待ち
    （本エントリ冒頭のトリガー・ADR参照。T221自体はPart 2完了でStage Cまで到達）。

- **Part 3着手（2026-08-24、ユーザー指示「T221のDに進んで」）**: 未決だった3点の製品判断
  （GUI編集の開放範囲・極端な重み設定への歯止め・T12 Part 2キャッシュ無効化条件との整合）
  をユーザーへ確認し、それぞれ「研究モード限定」「型・範囲チェックのみ」「軸定義の版数を
  キャッシュキーに含める」で確定（ADR「Stage D実装」節参照）。加えて「将来、研究モードを
  一般ユーザーから隠し何らかの権限制御を導入する計画がある」という方針が示されたため、
  管理APIの認可を「研究モードだから無認可でよい」という前提にせず、差し替え可能な1関数へ
  集約する設計にした。
- **Part 3実装メモ（2026-08-24完了）**: Stage D（レジストリのDBテーブル化＋管理API）を
  実装した。
  - **DB化**: `backend/migrations/0014_axis_definitions.sql`が`axis_definitions`
    （軸定義本体）・`axis_registry_meta`（版数）の2テーブルを追加し、既存7軸を
    `domain/axis_definitions.py`の内容そのままシードする。ORM
    （`infrastructure/axis_definition_models.py`）・リポジトリ
    （`infrastructure/axis_definition_repository.py`）は既存の書き込み非commit規約に従う。
  - **評価ロジックの読み出し方法は変えていない**: `AXIS_DEFINITIONS`は引き続き同期的な
    モジュールレベル辞書として読まれる。`services/axis_registry_service.py:
    refresh_axis_definitions`がアプリ起動時（`main.py`のlifespan）・管理API書き込み直後の
    2箇所だけで同じdictオブジェクトをin-place更新する「push型」設計にし、評価ホットパス・
    Pydanticバリデータ等の既存の同期アクセス箇所を一切変更せずに済ませた。DB未接続・
    未migration・0行の場合はWARNINGログを出しコード内蔵の既定値のまま動作を続けるため、
    **本migrationを本番へ適用するまでの間は評価の振る舞いが一切変わらない**安全側
    ロールアウトになっている（T74の教訓を踏まえた設計）。
  - **管理API**: `/api/admin/axis-definitions`（CRUD）を共有トークンheader
    （`X-Admin-Token`、環境変数`AXIS_ADMIN_TOKEN`）で保護。未設定環境では常に拒否する。
    妥当性検証は型・範囲チェックのみだが、「最後の1軸は削除できない」制約だけは
    構造的な安全策として例外的に持つ（レジストリを空にできると`refresh_axis_definitions`の
    0件フォールバックと衝突し評価が壊れるため、重みの妥当性とは別次元の問題として実装）。
  - **axis-catalog.json（フロント）は変更していない**: CIの`api-contract`ジョブがDB接続を
    持たないため、`export_openapi.py`は引き続きPython内蔵の`AXIS_DEFINITIONS`から生成する。
  - **検証**: backend全1126件green（新規37件、リポジトリ・サービス・ルータの3層）。
    dev DBへ実際にmigrationを適用し、シードされた7軸がPython定義とバイト単位で一致
    すること、`refresh_axis_definitions`後の`AXIS_DEFINITIONS`が元の内容と一致すること
    （評価の振る舞いが変わらないこと）を実DBで確認した。OpenAPI再生成＋フロント型追従
    （`git diff --exit-code`確認、axis-catalog.jsonは無変化）、`tsc --noEmit` green。
    docs/architecture.md「評価軸定義のDB化＋管理API」節を新設。
  - **残作業（保留、影響範囲付き）**:
    1. **本番DBへのmigration適用**: 完了（2026-08-24、ユーザー指示）。既存テーブル・
       既存データには一切触れない加算的な変更で、シード内容がPython定義とバイト単位で
       一致することを本番DBに対して直接確認した。**未設定のまま残っている項目**: Render側の
       環境変数`AXIS_ADMIN_TOKEN`が未設定のため、本番の管理APIは現状常に403（安全側の
       デフォルト、意図通り）。実際に使う段階でRenderダッシュボードから設定すること。
    2. **Stage E（GUI編集画面）**: 引き続き別タスクとして起票する（本ADRのスコープ外）。

### - [x] T222. Overpassライブ経路（`repository`未指定構成）の削除 規模M（2026-08-23完了）

- 背景: T218（探索の素材事前計算化＋リーンロード）実装時に判明。`GraphService`は
  `repository`未指定時、`OverpassClient.get_ways_and_nodes`経由でOverpassから都度
  Road Graphを構築する経路を今も持つ（T22でoverpass_fallback_enabled設定・
  PythonMVTエンコーダ・`OverpassClient.get_roads`は撤去済みだが、`get_ways_and_nodes`は
  「DBなし構成専用」として意図的に存続、`docs/improvement-plan-archive/2026-08-15.md`
  T22参照）。本番・dev環境は常に`repository`を注入するため到達しないが、コードとしては
  並行して残り続けている。
- 対応方針（着手時に検討）: `GraphService.__init__`から`overpass_client`/`http_client`
  引数と`repository`未指定分岐を削除し、`repository`必須の構成へ一本化する。
  `build_graph_with_surface_tags_for_bbox`・`_fetch_graph_with_surface_attributes`・
  `_build`・`OverpassClient.get_ways_and_nodes`本体の要否も合わせて判断する（DBなし構成の
  テスト・ローカル検証で使われている場合は移行方法を検討する）。
- 完了条件: `repository is None`分岐が`GraphService`・`RoadGraphEngine`関連コードから
  消え、DBなし構成に依存していたテストが新方式（repositoryへの直接シード等、T22の
  `test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`と
  同じ移行パターン）で置き換わること。

- **実装メモ（2026-08-23完了、ORS→road_graphエンジン移行の残作業調査を受けて着手）**:
  1. `GraphService.__init__`から`overpass_client`/`http_client`引数を削除し
     `repository: RoadGraphRepository`を必須化。`_build`・
     `build_graph_with_surface_tags_for_bbox`・`_fetch_graph_with_surface_attributes`を
     削除し、残り全メソッドの`if self._repository is None`分岐を除去（常に
     `self._repository.X(...)`を直接呼ぶ）。
  2. `app/infrastructure/overpass_client.py`（`OverpassClient`本体）を丸ごと削除
     （`get_ways_and_nodes`の呼び出し元がGraphService以外に無いことを確認済み。
     クラスの存在理由自体が「GraphServiceのDBなし構成専用」だったため）。
     `tests/test_overpass_client.py`も削除。
  3. `app/api/dependencies.py: get_graph_service()`の`road_graph_use_repository`分岐を
     削除し、常にrepository付きで構築（GraphServiceに限りこの設定の影響を受けなくなる。
     他4箇所[`get_elevation_attribute_service`/`get_surface_match_repository`/
     `get_region_service`/`get_accident_service`]の同フラグ利用は今回のスコープ外の
     ため維持）。`app/services/region_service.py`の直接構築箇所も同様に更新。
  4. `tests/test_graph_service.py`のDBなし構成自体を検証する4テスト（Overpass呼び出し
     回数を数えるテスト等）を削除し、他の全テストの`GraphService(...)`呼び出しを
     `repository=`のみの新シグネチャへ更新。`tests/test_routes_generate.py`の
     軽量ビルダーテストも同様に更新（`RoadGraphRepository(session=None)`でI/O無しの
     ダミーrepositoryを渡す）。
  5. `scripts/verify_phase1_e2e.py`・`scripts/verify_postgis_phase0.py`・
     `benchmarks/bench_postgis_prepare.py`にあった「Overpassが呼ばれないことを保証する」
     ためのFake/Failingスタブ（`FailingOverpassClient`等）を削除し、新シグネチャへ
     更新（これらのスタブの存在理由自体が消滅したため）。
  6. `docs/architecture.md`のファイル構成表（`overpass_client.py`・
     `test_overpass_client.py`の行を削除、`graph_service.py`の説明を更新）・
     `backend/app/config.py`・`backend/.env.example`（`road_graph_use_repository`の
     コメント・プロファイル表）を現状に追従。特に`.env.example`の「開発（DBなし）」
     プロファイルは`ROUTING_ENGINE=road_graph`が選べなくなった点（GraphServiceが
     DATABASE_URLへの実接続を常に必要とするため）を明記した。
  - 検証: backend pytest 1051件全green（削除した重複・DBなし構成専用テスト12件分減）。

### - [x] T223. DEM1A（1mメッシュ）標高データの組み込み可否調査 規模S（調査のみ、2026-08-23完了・判定: 見送り）

- 発端: T10実装直後、ユーザーから「dem 1mメッシュを仕組みに組み込むことは現実的？」との
  質問。T10は現在`DEM_TYPE_PRIORITY = (dem5a, dem5b, dem5c, dem)`（5m/10mメッシュ相当）の
  優先順位フォールバックのみを実装しており、GSI最高精度のDEM1A（航空レーザ測量、1m格子、
  最大ズーム17、東京都心を含む都市部中心にカバレッジ）は対象に含めていない。
  2026-08-16調査（本ファイルT10節参照）では「OSM形状点間隔（多くは5m超）に対し
  1m格子化の恩恵はほぼ出ない」「DEM1Aのカバレッジは全国均一ではない」と判断し
  見送っていたが、この判断はT10実装前の推測であり、T10完了後のDEM_TYPE_PRIORITY実装
  （2026-08-23の多段フォールバック修正）を踏まえた再検証はまだ行っていない。
- 調査事項（着手時に確認する）:
  - `dem1a`エンドポイントの実在・カバレッジ範囲・応答フォーマットを実タイルで確認
    （T10の`dem5a`等と同じ手法で`https://cyberjapandata.gsi.go.jp/xyz/dem1a/{z}/{x}/{y}.txt`
    を実際に叩く。z=14でも取得できるか、dem5a同様の挙動か）。
  - 対象範囲（関東本土）でのDEM1Aカバレッジ率の実測（全エッジ中どの程度が恩恵を受けるか）。
  - サイクリングルートの勾配評価（average_grade、区間長は交差点間=数十m〜数百m）という
    用途にとって、1m格子と5m格子の差が実際に評価結果（gradient軸のdifficulty・
    ルート選択）へ影響する規模かの試算・実データ比較（無作為サンプルで|Δgrade|分布を見る、
    2026-08-16調査が言及した検証方法と同種）。
  - `DEM_TYPE_PRIORITY`の先頭に`dem1a`を追加するだけで済むか（設計上は同じ多段
    フォールバック機構にもう1段追加するだけの想定だが、カバレッジ外の404が大半を占める
    場合は「常に1回余分な404往復が発生する」オーバーヘッドとのトレードオフも評価する）。
- 完了条件: 「組み込む／組み込まない」の判断とその根拠を本タスクへ記録する。組み込む
  判断になった場合は実装を別タスクとして起票する（本タスク自体は調査のみ、実装は
  含めない）。

- **調査結果（2026-08-23）**:
  1. **エンドポイント形式**: `dem1a`という名称は存在せず、正しくは
     `https://cyberjapandata.gsi.go.jp/xyz/dem1a_png/{z}/{x}/{y}.png`
     （**PNG形式**）。既存の`dem5a`/`dem5b`/`dem5c`/`dem`は全て`.txt`
     （カンマ区切りテキスト、`elevation_client.py`が現在パースしている形式）である
     のに対し、DEM1Aのみ形式が異なる。実機確認でz=14〜17は200、z=18は404
     （最大ズーム17、T223発端メモの記載と一致）。
  2. **カバレッジ**: 国土地理院公式発表（2024-03-31改定）で全国の3次メッシュに対する
     提供割合は**約46%**。実機確認（東京駅付近・横浜みなとみらい・奥多摩山間部は200、
     千葉県印西市郊外・埼玉県鴻巣市郊外は404）で、**都市部・山間部（土砂災害等の
     優先整備エリア）は覆う一方、関東近郊の郊外部には明確な欠測がある**ことを確認した。
     2026-08-16調査の「カバレッジは全国均一ではない」という判断は正しかったと裏付けられた。
  3. **本用途への影響試算**: 上記1の理由により、`DEM_TYPE_PRIORITY`への追加だけでは
     済まず、PNG形式のデコード（GSI地理院タイル標準の
     `標高 = 2^16×R + 2^8×G + B`系のエンコード方式、`elevation_client.py`に
     新規パーサが要る）という**既存想定より一段大きい実装コスト**が必要と判明した。
     加えて2026-08-16調査時点の「OSM形状点間隔（多くは5m超）に対し1m格子化の恩恵は
     ほぼ出ない」という判断（区間長が交差点間=数十m〜数百mのため、5m格子と1m格子の
     差はサンプリング間隔の粗さに埋もれる）自体は本調査で覆す新情報が得られなかった。
- **判断: 見送り**。(a) PNG形式デコードという新規実装が必要（想定より実装コストが
  大きい）、(b) カバレッジが依然として全国均一でない（郊外部に明確な欠測を実機確認）、
  (c) 2026-08-16時点の「1m格子化の効果は評価粒度に対し限定的」という判断を覆す新情報が
  得られなかった、の3点から総合的に見送りと判断する。
- 再検討条件: GSI側でDEM1Aの全国カバレッジが更に拡大した場合、またはOSM形状点の
  密度を上げる別の取り組みで区間内サンプリング間隔が5m未満まで細かくなった場合。

## 統合レビュー対応（2026-08-23・review:all第6回の指摘）

レビュー結果の全文・Evidenceは`.claude/commands/review/history/2026-08-23_all.md`、
スコア推移の視覚レポートはArtifact（レビュースコアボード）を参照。

### - [x] T224. save_graph再構築経路の32767パラメータ超過を修正し、road_graph APIのエンドツーエンドを実測してT218/T219の完了条件を裏取りする〔P1〕規模S（修正）＋S（検証）（2026-08-23完了、本番バックフィルはユーザー判断待ちで未実施）

- 発端: 統合レビュー2026-08-23 統合-1。`ROUTING_ENGINE=road_graph`でのAPI実行
  （`POST /api/routes/generate`、dev DB）が2回連続500になることを実機確認。原因は
  `road_graph_repository.py: save_graph`の`delete_stmt.where(RoadEdgeRow.edge_id.
  not_in(new_edge_ids))`——`new_edge_ids`（再構築対象の全edge_id、都心密度で数万件）が
  無分割でIN句パラメータ化され、`id_chunk`（1万件）と合算でasyncpgの上限32,767を超える。
  **T218以前（`a6c82a2`）から存在する既存バグ**であり8コミットの回帰ではないが、
  再構築が必ず失敗するため`split_at`が更新されず`is_split_up_to_date`がFalseのまま
  自己回復不能——以後の全リクエストが再構築→クラッシュを繰り返す恒久500ループになる。
  この状態ではT219のタイルキャッシュ経路にAPI経由で一度も到達できず、T218の完了条件
  「WARM 10秒以内」も裏取り不能のまま。T218検証時（2026-08-23）に「既知・スコープ外」と
  記録しながら起票しなかったため、レビューが再発見するまで追跡不能だった。
- 対応方針:
  1. `new_edge_ids`のNOT IN句をチャンク化または`=ANY(配列)`化して修正（同ファイルで
     確立済みの`=ANY(配列)`パターンを流用。`_ID_CHUNK_SIZE`との合算が上限を超えない設計に）。
  2. 修正後、dev DBでroad_graph API経由のエンドツーエンド（冷→温）を実測し、
     T218「WARM 10秒以内」・T219「同一エリア2回目以降5秒以内」の完了条件を裏取りして
     アーカイブの完了記録へ追記する。
  3. 本番Oracle DBへのmigration 0013（bearing_deg）適用＋バックフィル、
     `precompute_elevation_attributes`バッチの本番初回実行の確認フローを本タスクに含める
     （T218/T218aの完了記録で「実行前にユーザーへ確認」と保留になっている項目。
     実行はユーザー確認後）。
  4. T218aの完了条件「山岳エリア（平均勾配の高いエリア）でgradient重み・ペナルティ強度Pを
     上げると実際に経路が変わることを確認」も本タスクのエンドツーエンド検証に含める
     （2026-08-23の実装時は単体テスト（探索コストへの反映・勾配ハードフィルタ）のみで、
     実地の山岳エリアでの経路変化確認は未実施のまま`[x]`が付いている。2026-08-23棚卸の
     全記録見直しで判明したあいまい残件）。
- 完了条件: dev DBでroad_graphエンジンのルート生成が冷/温とも500にならず完走し、
  数値目標の実測値を記録。山岳エリアでのgradient経路変化を実測。バックフィルの実施可否が
  ユーザー判断で確定している。

- **実装メモ（2026-08-23完了）**:
  1. **修正**: `road_graph_repository.py: save_graph`のNOT IN句を`=ANY(配列)`化
     （`RoadEdgeRow.osm_way_id`/`OsmRawWayRow.osm_way_id`のIN句も同様に統一）。
     `~(RoadEdgeRow.edge_id == any_(cast(new_edge_ids, ARRAY(Text))))`でNOT IN相当を表現。
     回帰テスト`test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`
     （17,000way・34,000Edgeの一括再構築、PostGIS統合テスト）を追加し、**修正前のコードで
     実際に同一エラー（32767超過）が再現すること・修正後は例外なく完了することの両方を
     確認**（一時的に修正をstashして検証）。backend全体1065件green。
  2. **road_graph APIエンドツーエンド実測**（dev DB、`ROUTING_ENGINE=road_graph`）:
     500エラーは解消し、複数の起点・条件で例外なく完走することを確認。
     数値目標: 10kmループ生成（122,710エッジのbbox）で**1回目（split未済・再構築、
     一度きりのコスト）約57秒→2回目（タイルキャッシュ初回投入）約21秒→3回目以降
     （温）約5.4〜5.6秒**。`prepare()`内訳を直接計測すると、タイルキャッシュ自体の
     取得は温状態で約0.16秒（T219の設計どおり）だが、**このbboxの規模
     （122,710エッジ）では`evaluate_graph`約3.4〜3.7秒＋グラフ構築（nx+sparse）約1.0秒が
     支配的**で、目標「5秒以内」をわずかに超過する（5.4〜5.6秒）。T219が完了条件検証時に
     使った基準bbox（東京都心4km四方相当、69,216エッジ）より広いbboxでは
     evaluate_graph等のPythonループコストがエッジ数に比例して伸びるため、目標達成は
     bboxの規模に依存する。この残課題はT220の完了メモに既に記録済み
     （「evaluate_graph自体は今回手を付けていない、将来さらに高速化が必要になった場合は
     個別に精査」）であり、本タスクはT12の当初目標bbox規模での達成を再確認したに留まる
     （新規の課題ではなく、既知のスコープ外事項の実測値更新）。
  3. **T218aの山岳エリア実測**（dev DB）: `elevation_attributes`が本番未バックフィル
     （全128,887エッジ中1,325件のみ）だったため、dev DBに対し
     `precompute_elevation_attributes`を実行し全件（128,887件）バックフィル
     （elapsed=107.5秒、GSI DEMタイルはT10のキャッシュにより現実的な時間で完了）。
     急勾配エッジが集中するエリア（(35.69, 139.68)付近、平均絶対勾配7〜15%のエッジ
     100件超）で8km周回を`penalty_strength=1.0`と`8.0`で比較生成し、**同一方位
     （route-315）で明確な経路変化を実測**（P=1.0: distance=10.02km・
     max_gradient_percent=48.2% → P=8.0: distance=10.74km・max_gradient_percent=31.2%、
     より緩やかな迂回路へ変化）。ペナルティ強度を上げると候補集合自体も変化する
     （P=1.0は6候補・P=8.0は5候補、方位180が新規出現し方位270/090が距離許容差外へ脱落）。
     `max_average_grade_percent=8.0`のハードフィルタも指定し例外なく完走・候補集合が
     変化することを確認（8候補、探索グラフから急勾配エッジが除外されたことによる
     経路再構成）。T218aの完了条件を実地で満たした。
  4. **本番Oracle DBへのmigration 0013適用・バックフィル**: **未実施**。本番DB書き込みを
     伴うため実行前にユーザーへ確認する（本タスクの範囲外として保留、実行判断は別途）。
  5. 検証用の一時ファイル（テスト用uvicornプロセス・診断用printデバッグ・スクリプト）は
     全て削除・復元済み。road_graph_engine.pyの差分はゼロ（診断目的で一時追加したprint文は
     検証後にすべて元へ戻した）。

### - [x] T225. OpenAPI生成物へpenalty_strength/max_average_grade_percentを反映する〔P1〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-2。T218/T218aが`RouteGenerateRequest`・
  `GenerationConditions`へ追加した2フィールドが`openapi.json`/`api.d.ts`に未反映
  （生成物ドリフトの同型3例目。T196でルールを「進め方の原則」へ明文化した翌日に、
  明文化した場所を読まない実装セッションが違反した）。
- 対応方針: `export_openapi.py`→`npm run generate:api`を実行し再生成をコミット。
  再発防止のルール自体は本起票と同時の棚卸（2026-08-23）で**CLAUDE.mdの
  「コミット時の同期ルール」節へ昇格済み**（常時読み込まれる場所へ移動。3例目の
  根本原因が「ルールの置き場所」だったため）。
- 完了条件: `git diff --exit-code -- frontend/src/types/generated/`がクリーン、
  生成物に両フィールドが存在、frontend vitest/tsc green。

- **実装メモ（2026-08-23完了）**: `export_openapi.py`→`npm run generate:api`を実行し
  `openapi.json`/`api.d.ts`へ両フィールドを反映。再生成の結果、`penalty_strength`は
  openapi-typescriptの既定挙動（JSON Schemaに`default`があるフィールドは`?`なしの
  必須型として生成される。既存の`distance_tolerance_km`/`route_type`と同じ扱い）により
  型上は必須になったため、これを消費する3箇所（`page.tsx`のルート生成呼び出し・
  `ComparisonPanel.test.tsx`・`routeApi.test.ts`）へ`penalty_strength: 1.0`
  （UIに調整スライダーは無いため既定値を明示送信、`max_average_grade_percent`は
  `null`）を追加してtscエラーを解消した。frontend vitest 501件・eslint・tsc全green。

### - [x] T226. T218/T219/T220後の旧経路残骸を削除する〔P2〕規模S〜M（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-3（overall O-1・O-2）。設計原則9
  「並行追加→切替→旧削除」の3段目が未実施。
  - `GraphService.get_stop_poi_counts`/`get_intersection_counts`/`get_accident_counts`は
    ランタイム呼び出し元ゼロ（T218→T219の移行で不要化、テストのみが参照）。
  - `_RoadGraphContext.nx_graph`はランタイムで誰にも読まれないまま毎prepare構築されている
    （実測約0.2〜0.4秒/リクエスト@69,216エッジ。T220の「区間表示互換のため維持」という
    理由付けは事実誤認で、実際の読者はテストのみ）。
- 対応方針: GraphServiceラッパー3本と対応テストを削除。prepareのnx_graph構築を廃止し
  contextから外す（テストは`build_networkx_graph`を自前で呼ぶ形へ書き換え）。
  `domain/routing.py`のNetworkX系関数自体はsparse版回帰テストのオラクルとして維持する
  （削除しない）。Repositoryファサードのフラット委譲契約（Keep List）はRepository層の
  話であり本タスクの対象外。
- 完了条件: backend全テストgreen、削除後にprepareの所要時間が短縮されることを確認。

- **実装メモ（2026-08-23完了）**:
  1. `GraphService.get_stop_poi_counts`/`get_intersection_counts`/`get_accident_counts`
     （graph_service.py）を削除。対応する`test_graph_service.py`の2テスト
     （`test_get_stop_poi_counts_without_repository_returns_empty_dict`・
     `test_get_stop_poi_counts_with_repository_delegates`）と`FakeRoadGraphRepository`の
     未使用フィールド・メソッドも削除。`test_road_graph_engine.py`の`FakeGraphService`が
     持っていた同名3メソッド（呼び出し元皆無、コメントのみが参照）も同様に削除。
     `get_way_tags`（引き続き`_build_search_materials_uncached`から呼ばれ現役）は残す。
  2. `_RoadGraphContext.nx_graph`フィールドを削除し、`prepare()`の
     `nx_graph = build_networkx_graph(graph, search_edge_costs)`行を削除
     （`build_networkx_graph`のimport・`import networkx as nx`も不要化のため削除）。
     `domain/routing.py`のNetworkX系関数自体は削除せず維持（`test_routing.py`・
     `benchmarks/bench_route_trace.py`が引き続き参照）。
  3. テスト側で`context.nx_graph[...]`を読んでいた3箇所（night軸・gradient軸の
     コスト比較、ハードフィルタ除外確認）を、実際に探索本体が使う
     `context.sparse_graph`から直接読む方式へ書き換え（`_sparse_edge_weight`/
     `_sparse_has_edge`ヘルパーを追加）。`_RoadGraphContext(...)`を直接構築する
     残り2箇所の`nx_graph=None`引数も削除。
  4. モジュールdocstring・コード内コメントのNetworkX言及をscipy.sparse.csgraph基準の
     記述へ更新（road_graph_engine.py冒頭・`_RoadGraphContext.sparse_graph`docstring）。
     architecture.mdの`RoadGraphEngine.prepare`説明・事故密度精度改善の節も、
     削除済みラッパーへの言及が残らないよう現状に合わせて更新。
  5. **所要時間短縮の実測**: 削除された`build_networkx_graph`呼び出し単体のコストを、
     T219/T220が基準にした規模（69,216エッジ相当、合成格子グラフで再現）で計測すると
     約272ms（`build_sparse_graph`単体は約199ms）。両方構築していた従来の
     グラフ構築コスト約471ms→sparseのみの約199msへ、約58%（約272ms）短縮したことを
     確認（`build_networkx_graph`は削除しておらず`domain/routing.py`に残るため、
     同条件で直接比較できた）。
  - 検証: backend pytest 1063件全green（削除した2テスト分減、新規0件）。

### - [x] T227. architecture.mdのT11完了を追従する〔P2〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-4（consistency F-3）。`docs/architecture.md`の
  「未着手: T11（segmentsのAPI境界ビン化）」行が、同日完了済みのT11
  （`aggregate_segments_into_bins`、約500m単位ビン化）に未追従。
- 対応方針: 該当行を完了の記述へ更新し、segments集約の1文（road_graphエンジンのみに
  適用・`RouteSegmentDetail`型は不変・集約方法の要点）を追記。
- 完了条件: architecture.mdにT11の現状が反映されている。

- **実装メモ（2026-08-23完了）**: `docs/architecture.md`の該当行を、`aggregate_segments_
  into_bins`（`domain/route.py`）による約500m単位集約の説明（road_graph_engine.pyの
  `prepare`が生成した候補のみに適用・openrouteserviceエンジンは対象外・
  `RouteSegmentDetail`型は不変で契約影響なし）へ更新。コード変更なしのためテスト実行は
  不要。

### - [x] T228. 統合レビュー第6回の軽微指摘4件を一括解消する〔P3〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-5。いずれも規模S:
  1. `SearchMaterials`/`_TileMaterials`（graph_service.py）のフィールド完全一致の
     重複データクラスを1クラスへ統合。
  2. 緯度1度≒111kmの定数重複（`domain/routing.py`の`_KM_PER_DEGREE_LATITUDE`と
     `road_graph_engine.py`のリテラル111.0）を`domain/geo.py`へ片側import化（設計原則2）。
  3. `graph_material_cache.py`の型付け（`_LRUCache`ジェネリクス・`object`戻り値）と
     `clear()`のカプセル化（`_data`直接参照の解消）。
  4. ORS失敗時の`RoutingError('openrouteservice request failed: ')`が空文字で
     診断情報ゼロの問題——例外種別・HTTPステータスをメッセージへ含める
     （2026-08-23の実機確認でdev環境のORS全滅の原因切り分けができなかった実績）。
- 完了条件: backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `SearchMaterials`を`domain/attributes.py`へ移設（`EdgeAttributeCounts`/
     `ElevationAttribute`が既にそこにあり、`domain/graph.py`側へ置くと循環importになる
     ため）。`graph_service.py`の`_TileMaterials`を削除し`SearchMaterials`を共有型として
     使用（`_get_or_build_tile_materials`の戻り値・生成箇所を差し替え）。
  2. `KM_PER_DEGREE_LATITUDE`を`domain/geo.py`（`EARTH_RADIUS_KM`の隣）へ定義し、
     `domain/routing.py`の`_KM_PER_DEGREE_LATITUDE`定義を削除してimportへ、
     `road_graph_engine.py: _bbox_around_point`のリテラル`111.0`2箇所をimportへ置換。
  3. `graph_material_cache.py`の`_LRUCache`を`_LRUCache[SearchMaterials]`として具体化し、
     `get_tile_materials`/`set_tile_materials`の型注釈も`object`→`SearchMaterials`へ。
     `_LRUCache`へ`clear()`メソッドを追加し、モジュールの`clear()`関数の
     `_tile_materials_cache._data.clear()`（内部属性への直接アクセス）を
     `_tile_materials_cache.clear()`へ置換。
  4. `ors_client.py`の`httpx.RequestError`ハンドラで、メッセージへ
     `type(exc).__name__`を必ず含める形に変更（`str(exc)`が空文字になる
     httpx例外があるため、種別名だけは常に残る形にした。HTTPステータス側
     （`httpx.HTTPStatusError`）は元々`exc.response.status_code`を含んでおり対象外）。
  - 検証: backend pytest 1065件全green（既存の`test_graph_service.py`・
    `test_road_graph_engine.py`・`domain/routing.py`関連テストを含む）。

### - [x] T229. T219冷パス（タイル分解）のクエリ本数増を実測する 規模S（計測のみ、2026-08-23クローズ・T248へ統合）

- 発端: 統合レビュー2026-08-23 統合-6（complexity C-1、DEFER）。T219のタイルキャッシュは
  冷時に「材料5クエリ×タイル数」（30km生成でz12タイル9〜12枚≒45〜60クエリ）となり、
  従来のbbox一括6クエリより本数が増える。温時0.06秒は実測済みだが冷時の大半径が未計測。
- 完了条件: 冷パスの実測値を記録し、問題があれば対策タスクを別途起票、無ければ
  「計測済み・対応不要」と記録。
- **クローズ記録（2026-08-23、統合レビュー第7回の起票時）**: 冷パスの実測は
  T245〜T247の一連の本番・dev実測で事実上完了した（本番・王子30km冷パス316秒
  [支配はsplit再構築のUPSERT]、dev・新宿10km冷パス46秒→温6.7秒）。「クエリ本数」
  単体の内訳計測よりも「冷パス全体の体験」が課題であることが判明したため、
  本タスクは**T248（性能課題の本体タスク）へ統合してクローズ**する。

## 過去記録の全見直しで判明したあいまい残件の明確化（2026-08-23棚卸・ユーザー指示）

ユーザー指示「過去に実施した改善計画をすべて見直し、過程や結論があいまいな部分があれば、
それを明確にする改善計画をタスクとして追加して」を受け、本体＋アーカイブ全9ファイルの
完了記録を走査した（マーカー: 未解消・未確認・未検証・原因未特定・保留・別途確認等）。
以下の基準で選別した:

- **起票済み・カバー済みのため対象外**: PBF取込の94万way超減速（原因未特定だがT127の
  完了条件が実測検証を含む）／T151の旧実装の次数非決定性（設計変更で依存自体を除去済み、
  撤去済みコードの原因調査に価値なし）／T202のnull警告（サードパーティ基礎地図由来と
  判断・調査打ち切りの理由が記録済み）／T28(B)の「実装完了（未検証）」（同日の関東全域
  拡大で実地検証済み、記録が先行しただけ）／見送り判定group（T52/T175/T177/T210/T211/
  T213、いずれも判定理由が明記済み）／T218のWARM未検証・T218aの山岳未確認（T224へ
  統合済み）。
- **以下の3タスクとして起票**: 追跡タスクが無いまま宙に浮いていたもの。

### - [x] T230. CI・GitHub Actionsの健全性を確定する（api-contract成否・無償枠・Dependabot稼働） 規模S〔P1相当のあいまい解消〕

- 発端: 2026-08-23棚卸の全記録見直し。以下がいずれも「確認できず」のまま残っている:
  - **T196（2026-08-22）の未解消項目**: 「CI実行状況の確認自体はユーザー側で別途行う
    必要がある」——T180（2026-08-20）以降、生成物ドリフトが3回発生したがapi-contract
    CIが赤になったのかCI自体が実行されていない（Actions無償枠枯渇疑い、無償枠対策
    コミット04f6bc3と同時期）のか、一度も確定していない。CIはT1（2026-08-15）以来
    全タスクの安全網とされてきたが、その安全網が直近1週間機能していたかが不明のまま。
  - **T48（2026-08-16）のDependabot**: 「実際のGitHub側スケジュールに依存するため未検証」
    のまま、週次実行が一度でも動いたか未確認。
- 対応方針: 確認手段を確立する（`gh` CLI導入＋認証、またはユーザーがActionsタブを直接
  確認して結果を共有）。T180以降のmasterでのapi-contractジョブの実行有無・成否、
  無償枠の消化状況、Dependabot PRの有無を確定し、記録する。CIが止まっていた期間が
  あれば、その期間のコミットはローカルテスト実行結果のみが安全網だったことを明記する。
- 完了条件: 「CIはいつからいつまで動いていた/いなかった」が事実として記録され、
  止まっていた場合は復旧方針（無償枠・self-hosted・ローカルpre-push等）がユーザー判断で
  確定している。

- **確認結果（2026-08-23、ユーザーがActionsタブを直接確認）**:
  - **api-contractジョブ: 失敗している**。T196で明文化前のOpenAPI生成物ドリフト
    （T180・T185・T218/T218a、統合レビュー2026-08-23 F-1）は、実際にはCIが検知して
    正しく赤にしていたと判明した——「CI安全網が沈黙していたから見逃した」のではなく、
    **「CIは正しく警告していたが誰も見ていなかった」**という、より軽微ではない別種の
    運用ギャップだったことが確定した。
  - **GitHub Actions無償枠: 2000/2000分を使い切り、超過している**。この結果、
    現時点で新規コミットに対するCIの実行自体が行えない状態にある可能性が高い
    （無償枠を使い切った場合、GitHub Actionsは新規ワークフロー実行を受け付けない）。
    **2026-08-23時点のT225・T224を含む直近のコミット群は、CIによる検証を経ておらず、
    ローカルでのpytest/vitest/tsc/eslint実行結果のみが安全網である**。
  - **Dependabot: PRが存在する**（稼働は確認できた）。Dependabot自体はActions無償枠を
    消費する仕組みとは別枠のため、無償枠超過の影響を受けていない。
  - 無償枠の対策コミット（04f6bc3、paths-ignore・concurrency cancel-in-progress・
    Playwrightキャッシュ）は方向性としては正しいが、**既に枯渇した無償枠に対しては
    事後対策**であり、今回の枯渇を防げなかった（対策後も枯渇が進行し続けたか、
    対策前の消費で既に枯渇していたかは切り分けられていない）。
- 復旧方針: **ユーザー判断待ち**。選択肢（無償枠の月次リセット待ち／GitHub Actions
  従量課金の有効化／セルフホストランナー／ローカルpre-push hookでの代替検証）は
  ユーザーへ別途提示し、方針が決まり次第本タスクを完了とする。

- **追加確認（2026-08-23、リポジトリをprivate→publicへ切替後）**: public repoはActions
  無償枠が実質無制限になるため無償枠超過は解消する想定だったが、切替後最新のRun #266
  （コミット71bb5d7）を確認すると、4ジョブ（api-contract/backend/frontend/e2e）全てが
  4秒で即失敗しており、いずれも同一エラー:
  `The job was not started because recent account payments have failed or your
  spending limit needs to be increased. Please check the 'Billing & plans' section
  in your settings`。
  これは「無償枠2000/2000消費」とは別種の**アカウントの支払い方法エラーまたは
  spending limit設定**がジョブの起動自体をブロックしているもので、public化だけでは
  解消しないことが判明した。GitHub Settings → Billing and plansでの支払い方法確認・
  spending limit引き上げが必要（アカウント所有者の決済操作のため、Claude側では代行
  不可。安全ルール上も決済情報の入力は禁止行為に該当する）。
  → **本タスクは依然未完了**。ユーザーがBilling設定を確認・是正した後、再度CIが
  正常実行されることを確認して完了とする。

- **続報（2026-08-23、public化完了・支払いエラー解消後）**: ユーザーがBilling設定を
  是正しpublic化を完了。docsのみのpushはCI自体をトリガーしない設計（`paths-ignore:
  docs/**`、無償枠対策）のため、`workflow_dispatch`で手動実行（Run #267）して確認した
  ところ、api-contract/backend/frontendの3ジョブは成功、**e2eジョブのみ失敗**。
  ローカルで`npx playwright test`により再現・原因調査した結果、CI環境固有の問題では
  なくテストコード側の根本原因が判明した:
  - `smoke.spec.ts`の「地図レイヤーのON/OFF切替」テストが、地図上の単一チップ
    「道路情報」を探すが、これはT165（「道路情報」を「道路種別」「路面」の2チップへ
    論理分割）・T166（次数グループ化により「観測」グループの折りたたみ配下へ格納）の
    2回のUI再構成を経て、もはや存在しないラベル・DOM構造になっていた。
    e2e追加コミット（dba653d）はT165より前で、T165・T166のどちらもe2eテストを
    追従更新していなかった（OpenAPI生成物ドリフトと同種の「変更に追従すべき
    成果物の更新漏れ」）。
  - 修正: `frontend/e2e/smoke.spec.ts`を現在のUI構造に合わせ、「観測」グループ見出しを
    展開してから「道路種別」チップを操作するよう更新。ローカルで`--workers=1`・既定の
    並列2ワーカーの両方で2件とも再現的に成功することを確認済み。
  - もう一方の「ルート生成→候補一覧の表示」テストは、単体実行で安定して成功することを
    確認済み（当初ローカルで両方失敗して見えたのは、このマシンでの並列Playwrightワーカー
    間のWebGL/GPU資源競合による偶発的なブラウザクラッシュが原因で、CI環境やアプリ本体の
    不具合ではないと判断）。
  - **api-contract・backend・frontendの3ジョブが成功したことで、public化＋Billing是正で
    無償枠問題自体は解消したことも確認できた**。
  → 残作業: このe2e修正をpushしCIで再実行し、4ジョブ全green化を確認できた時点で
  本タスクを完了とする。

- **完了確認（2026-08-23）**: 修正をpush（コミット4c7bf63）したところ、docs以外の
  変更のためCIがpushイベントで自動起動（Run #268）し、api-contract・backend・
  frontend・e2eの4ジョブ全てが成功した。「CIはいつからいつまで動いていた/いなかった」
  の事実関係が確定:
  - T1（2026-08-15）〜無償枠枯渇までは正常稼働し、api-contractドリフトも正しく検知
    していた（統合レビュー2026-08-23 F-1で確認済み）。
  - 無償枠枯渇後（正確な枯渇時点は未特定のまま）〜2026-08-23のpublic化+Billing是正
    までは新規コミットのCI実行自体が行えず、ローカルのpytest/vitest/tsc/eslint実行
    結果のみが安全網だった。この間のコミット（T225・T224含む）はCI未検証のまま
    マージされている。
  - 2026-08-23のpublic化+Billing是正後、CIは正常復旧。副産物として、e2eジョブが
    T165/T166のUI再構成に追従できておらず恒常的に失敗する状態だったこと（本タスク
    上部の「続報」参照）も発見・修正できた。
  - Dependabotは無償枠と別枠のため終始影響を受けていなかった（既述のとおり）。
  - 復旧方針: 無償枠は今後もpublic repoのため実質無制限。Billing側の支払い方法さえ
    維持されれば再発しない見込み。セルフホストランナー・ローカルpre-push hook等の
    追加対策は不要と判断（ユーザー確認済みの一連の対応で十分）。
  完了条件（「CIはいつからいつまで動いていた/いなかった」の記録＋復旧方針確定）を
  満たしたため完了とする。

### - [x] T231. 設計判断の未確定残件2件を確定して記録する 規模S（判断のみ）（2026-08-23完了）

- 発端: 2026-08-23棚卸の全記録見直し。「未解決のまま残す」「別途確認が必要」と明記された
  まま追跡されていない設計判断が2件:
  1. **`motor_vehicle=no`の扱い**（評価システムの層構造再設計・T140、2026-08-18）:
     設計プロンプトの「通行不可はハード制約へ統合」に対し、現行実装は「二次軸内の
     最善値固定」という別ロジック。「改訂後の設計プロンプトでも言及が無いため引き続き
     未解決のまま残す」と記録されて以来、宙に浮いている。現行実装を正とするか、
     0次ハードフィルタへ移すかを決めて記録する（実装変更は判断結果次第で別起票）。
  2. **「規模M以上は着手前にタスクエントリを作成する」運用ルールの採否**（T135、
     2026-08-18）: 「CLAUDE.md改訂要否含めユーザー判断のため今回は見送り、別途確認が
     必要」のまま。採用するならCLAUDE.mdの「コミット時の同期ルール」節と同格で明文化、
     不採用なら不採用と記録して閉じる。
- 完了条件: 2件とも判断結果と根拠が記録され、「未解決のまま」という記述が解消されている。

- **判断結果（2026-08-23完了）**:
  1. **`motor_vehicle=no`は現行実装（二次軸内の最善値固定）を正とし、0次ハードフィルタへは
     移さない**。実際には既にT140の時点でこの判断は下されており記録も存在していた
     （`docs/architecture.md`1029〜1057行目「〇次: ハード制約」節、`domain/traffic.py`の
     `motor_vehicle_no_override`docstring、`domain/evaluation.py:263-266`のdocstring
     いずれも「自転車は法的に通行可能なため0次のハード除外対象にはしない」という同一の
     理由を明記済み）。棚卸で「未解決」と書かれていたのは、T140完了前に書かれた懸念文が
     T140完了後も訂正されずに本ファイルへ残っていただけの表記漏れであり、設計上の
     矛盾ではなかった。上記「評価システムの層構造再設計」節（T140の項）の懸念文を
     本エントリで解消済みとして扱う。
  2. **「規模M以上は着手前にタスクエントリを作成する」ルールを採用する**。T130で
     一度違反し事後是正した実績があり、大きめの変更ほど途中で背景・判断根拠が失われ
     やすいため、着手前に記録する運用の方がコストに見合う。CLAUDE.mdの
     「コミット時の同期ルール」節へ同格の1項目として追記済み。

### - [x] T232. 検証が保留のまま記録されている残件4件を明確化する 規模S〜M（2026-08-23完了）

- 発端: 2026-08-23棚卸の全記録見直し。「〜の可能性が高い（未検証）」「要否未確定」の
  まま追跡されていない検証残件:
  1. **dev環境のORS API全滅の原因特定**: 2026-08-23の統合レビュー実機確認で
     `POST /api/routes/generate`が8方位全滅（`openrouteservice request failed: `、
     詳細空文字）。前回レビュー（08-22）では7候補生成に成功しており、APIキー失効・
     クォータ枯渇・ネットワークのいずれか未特定。T228の4（エラーメッセージ改善）とは
     独立に、現在のdev環境で主要導線が回復することを確認する。
  2. **T194ロードマップ⑤⑥の要否確定**（2026-08-21）: ⑤リレープロキシ本番有効化・⑥は
     「未着手」のまま。同じT194で「クォータ枯渇はIP非依存」と判明しており、IP分離が
     効かないならリレープロキシ有効化の価値自体が消滅している可能性が高い。要否を
     確定し、不要なら⑤⑥を閉じてT179の位置づけ（dev用・本番未使用）を記録する。
  3. **動的気象プレースホルダタイル404のStrict Mode由来仮説**（T202、2026-08-22）:
     「`next dev`のReact Strict Mode由来の可能性が高い（本番ビルドでは未検証）」のまま。
     本番ビルド（`next build && next start`）で1回確認して仮説を確定/棄却する。
  4. **ダークモード実描画の実機確認**: 統合レビュー6回すべてで「headless制約により
     未確認」のまま繰り越されている（過去にダークモード配色バグの実績あり:
     現在地アイコンのcolor未指定、2026-08-14）。headless Chromiumの
     `prefers-color-scheme`エミュレーション（Playwrightの`colorScheme: 'dark'`）で
     主要レイヤー・パネル・凡例のダークモード表示を1回実機確認して記録する
     （headlessでも可能な手段が確立すれば以降のレビューでも同手順を使える）。
- 完了条件: 4件それぞれ「確認した結果」または「確認不要と判断した根拠」が記録され、
  「未検証のまま」という記述が解消されている。

- **調査結果（2026-08-23完了）**: 本体の作業ツリーとは別に専用`git worktree`
  （CLAUDE.md「作業ツリーの安全」節の方針どおり、調査目的のため）を作成し、
  backend（dev DB接続）・frontend（本番ビルド）をそこで起動して検証した。検証後は
  worktree・ブランチとも削除済み（本体作業ツリーへの影響なし）。
  1. **dev環境のORS API全滅**: 現時点では**再現しない**ことを確認した。worktree上で
     `POST /api/routes/generate`を15km・15km・30kmの3回実行し、いずれも8方位中8方位が
     成功（`trace_ok=8/8`、ORS関連の警告・エラーなし）。統合レビュー当日（2026-08-23）に
     観測された全滅は、APIキー・クォータ・ネットワークいずれかの一時的な問題だった
     可能性が高いが、再現しない以上ここから遡って原因を確定することはできない。
     T228で追加した「例外種別名を必ず含める」エラーメッセージ改善により、次回同様の
     事象が起きた際は診断がしやすくなっている。
  2. **T194ロードマップ⑤⑥の要否**: **現時点では不要と判断し、クローズする**。
     T194完了時点で既に「クォータ枯渇は送信元IPに依存しない現象」と直接確認済み
     （T182実装メモ）であり、この事実は本調査時点でも変わっていない（IP分離を
     提供するだけの⑤リレープロキシ有効化・⑥自前運用は、クォータ枯渇そのものへの
     対策にならない）。T179（Oracle Cloud VM経由のリレープロキシ）は実装済みのまま
     `OPEN_METEO_BASE_URL`未設定でdev/ローカル検証用として温存し、本番では引き続き
     未使用と位置づける。将来Open-Meteoの利用規約・料金体系が変わる、または利用者数が
     大きく増える等の状況変化があれば、その時点で再度要否を検討する。
  3. **動的気象プレースホルダタイル404のStrict Mode仮説**: **確定（仮説どおり）**。
     worktree上で`next build && next start`（本番ビルド）を実行し、Playwright
     （headless chromium）で降水ナウキャストレイヤーのON/OFF/ON切替を3回試行、
     JMAへの実リクエストを監視した。**プレースホルダURL
     （`.../00000000000000/none/00000000000000/...`）への実リクエストは3回とも
     0件**（実タイムスタンプ入りの実URLへのリクエストのみ、全て200 OK）。`next dev`の
     React Strict Mode（開発時二重effect実行）由来という仮説が確定し、本番ビルドでは
     発生しない・実害なしであることを確認できた。`MapView.tsx`の該当コメント
     （T202で「本番ビルドでは未検証」と記載）を確定済みへ更新する必要はあるが、
     コード変更を伴わない事実確認のため本タスクでは追跡のみ（更新は次回この箇所を
     触る際でよい、または別途軽微修正として起票可）。
  4. **ダークモード実描画**: **確認済み、問題なし**。Playwrightの`colorScheme: 'dark'`
     （headless chromiumで`prefers-color-scheme: dark`をエミュレート）で、初期画面・
     観測データ/推定指標/動的データの各レイヤーグループ・研究タブ（研究モード
     チェックボックス含む）・開発者タブ（デバッグログ表示・サーバー接続状態）・
     ルート生成後の候補一覧・生成したルートの色分け凡例（色スウォッチ4種＋切替
     ボタン4種）を撮影して目視確認した。いずれも文字・アイコンが背景に対して
     十分なコントラストで表示されており、2026-08-14に実績のあった「ダークモードで
     背景色に対しcolor未指定のアイコンが見えなくなる」類のバグは見当たらなかった。
     地図本体（基礎地図タイル）自体は明るい配色のまま（サードパーティ「liberty」
     スタイルにダーク変種が無いため、UI側はダークでも地図はライトのまま、という
     組み合わせ自体は想定どおりで不具合ではない）。この手順（Playwright
     `colorScheme`オプション）は次回以降のレビューでもheadless環境のまま
     ダークモード実機確認に使える。
  - **副産物（worktree検証中に発覚・対策済み）**: frontendを3000番以外のポート
    （3010）で動かすと、backendの`basemap_public_base_url`既定値が`localhost:3000`
    固定のため地図タイル・スプライト・グリフが全滅（`ERR_CONNECTION_REFUSED`）する
    ことが判明（ユーザー指摘のとおり過去にも発生していた既知の踏み抜きポイント）。
    製品コード自体は環境変数で上書き可能な設計のため変更不要と判断し、再発防止として
    メモリ（`basemap-public-base-url-port-mismatch.md`）へ記録した。

## 実装・テスト整合性の総点検対応（2026-08-23・review:consistency）

ユーザー指示「実装とテストがずれているところがないか総点検して」を受け、直近8コミット
（T224・T225）を起点にconsistencyレビューを実施（結果:
[history/2026-08-23_consistency.md](../.claude/commands/review/history/2026-08-23_consistency.md)）。
直近差分自体は整合性OKだったが、範囲を広げた確認で2件のずれを検出・起票・修正した。

### - [x] T233. CIの`backend`ジョブへPostGIS統合テスト実行環境を追加する〔P1〕規模S（2026-08-23完了）

- 発端: consistencyレビュー2026-08-23 F-1。CI相当条件（`TEST_DATABASE_URL`を到達不能な
  ホストへ向けて実行）でpytestを実行すると`965 passed, 100 skipped`（通常実行では
  `1065 passed`）。この100件には**T224の回帰テスト自身**
  （`test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`）
  も含まれており、CIは一度もこのテストをskip以外の結果で実行していなかった。T224が
  修正した不具合（asyncpgプリペアド文パラメータ上限超過）自体、ユニットテストではなく
  実機API呼び出しで発覚しており、「CI green後にPostGIS依存コードの不具合が発覚する」
  というトリガーが既に1回成立していた。
- 対応: `.github/workflows/ci.yml`の`backend`ジョブへ`postgis/postgis:16-3.4`
  （docker-compose.ymlのpostgresサービスと同じイメージ）のサービスコンテナを追加し、
  `TEST_DATABASE_URL`を注入。`conftest.py`が`CREATE EXTENSION postgis`・
  `Base.metadata.create_all`を自前で行うため、番号付きmigrationの適用ステップは不要
  （road_edges等はSQLAlchemyモデルから直接作成される。番号付きmigrationは本番の
  ALTER履歴用）。
- 検証: ローカルでdev DB（PG18+PostGIS、TEST_DATABASE_URLのデフォルト値と同じ接続先）に
  対し`pytest -q`を実行し`1065 passed`（0 skipped）を確認済み。CI上でのサービス
  コンテナ経由の実行結果は、このコミットのpush後にCIで確認する。

### - [x] T234. e2eフィクスチャがGenerationConditions等の必須フィールドと乖離していた問題を修正する〔P2〕規模S（2026-08-23完了）

- 発端: consistencyレビュー2026-08-23 F-2。`frontend/e2e/fixtures.ts`の
  `routeGenerateResponseFixture()`が返す`conditions`が、実際の`GenerationConditions`の
  必須12フィールド中5件（`car_stress_recipe`・`road_suitability_recipe`・
  `motor_vehicle_density_recipe`・`penalty_strength`・`max_average_grade_percent`）を
  欠いていた。T225（コミット1e7ade4）は同じ2フィールドを他2箇所のvitestフィクスチャ
  （ComparisonPanel.test.tsx・routeApi.test.ts）には反映したが、このe2eフィクスチャは
  対象に含めていなかった。戻り値に型注釈が無いため、TypeScriptもこの欠落を検知できて
  いなかった。
- 対応: `routeGenerateResponseFixture()`・`makeRouteCandidate()`の戻り値へ
  `RouteGenerateResponse`/`RouteCandidate`型注釈を付与し、不足5フィールド
  （既存の`ROUTE_PREFERENCE`定数も同様に3フィールド欠落していたため合わせて修正）を
  埋めた。型注釈自体を今後のドリフト検知機構として残す（OpenAPI必須フィールドが
  増えたときにtscがビルドを落とすようになる）。
- 検証: `npx tsc --noEmit`でfixtures.tsのエラーが解消したことを確認。
  `npx playwright test`（既定の並列2ワーカー・`--workers=1`の両方）で2件とも成功する
  ことを確認済み。

### - [x] T235. backend pytestをpytest-xdistで並列化する〔ユーザー指摘: テスト実行が遅い〕規模S（2026-08-23完了）

- 発端: ユーザー「テスト実施が非常に遅い。以前にも改善要望したが、まだ見直せるところは
  ないか？再確認して」。T233でCIがPostGIS統合テスト約100件を実行するようになった分、
  backendのpytest総数が増えており、直列実行のままでは今後さらに伸びる。
- 対応: `pytest-xdist==3.8.0`を追加。PostGIS統合テスト4ファイル
  （test_road_graph_repository.py・test_accident_repository.py・
  test_match_designations.py・test_health.pyの該当テスト）へ
  `pytest.mark.xdist_group(name="postgis")`を付け、同一ridecompass_test DBへ接続する
  テストを全て同一workerへ固定（別workerでの同時TRUNCATEレースを防止）。CIの
  pytestステップを`-n auto --dist loadgroup`に変更。docs/testing.md・CLAUDE.mdへ
  新規DBテストファイルに同マーカーが必須である旨を追記。
- 検証: ローカル（Windows、8論理コア）で`-n auto --dist loadgroup`実行し1065件全green
  （xdist_groupによるレースなしを確認）。実測はローカルでは効果が限定的
  （直列182s→`-n 2`で217s＝悪化、`-n auto`で158s＝約13%短縮）で、OneDriveフォルダの
  ファイルI/O・ウイルス対策スキャン等のワーカー起動オーバーヘッドが要因と推測される。
  **CI実測（Run #270、2026-08-23）は予想に反し改善なし**: pytestステップは
  導入前（Run #269、直列）27秒→導入後（xdist有効）27秒で同一。標準GitHub-hosted
  runnerのCPUコア数が少なく（標準ランナーは2〜4コア）、1065件で27秒という
  既に短い実行時間に対してはworker起動コスト（Pythonプロセス起動＋アプリ全体の
  import）が並列化利得を相殺したとみられる。CIでの並列化効果は「ローカルより
  大きく出る見込み」という当初の予測は誤りだったため訂正する（事実と推測は
  分けて記録する方針どおり）。
- 結論: xdist_group設定自体はDB統合テストのレース防止として引き続き価値があり
  （将来テスト件数が増えCIの実行時間がボトルネックになった際にすぐ効果を出せる
  下地になる）、CIでの実行を害しない（同じ27秒）ため設定は維持する。ただし
  「CIを速くする」という目的では今回は効果が確認できなかった。ローカル実行時の
  約13%短縮（`-n auto`利用時）は開発者の日常的なテスト実行体感には寄与する。
- 実装メモ: ローカルWindows環境でexecnet（xdistのworker起動に使用）が
  `EOFError: expected 1 bytes, got 0`で即座に失敗する問題に遭遇。作業ディレクトリの
  絶対パスに日本語（OneDriveの「ドキュメント」）が含まれることが原因と推測され、
  `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`環境変数で回避できることを確認したが、
  CI実行には影響しない（CIの作業ディレクトリはASCIIパスの`/home/runner/work/...`）ため
  ci.ymlへの追加対応は不要と判断した。

## ORS→road_graphエンジン移行の残作業（2026-08-23・ユーザー指示）

ユーザー指示「ORSから独自の検索エンジンに切り替えるための作業で残っているものはある？」
「1〜6を実施して」を受け、調査で洗い出した6項目のうち5項目を実施する
（項目4「本番Oracle DBへのmigration 0013適用・標高バックフィル」は本番DB書き込みを
伴うため今回保留、他5項目完了後にユーザーと実行タイミングを別途相談する）。

**2026-08-23追記**: 保留していた項目4のうち「migration 0013適用」を、本番DBでの性能・
成功率実測（T241調査の一環）中に判明した**road_graphエンジンが本番DBで一切動作しない**
というブロッカー（後述T242）への対応としてユーザー指示により実施した。「標高バックフィル」
（`precompute_elevation_attributes`、全Edge分のGSI DEM問い合わせを伴う別の大きなバッチ）は
スキーマ同期とは規模も性質も異なるため、本追記の対象外のまま別途判断とする。

### - [x] T242. 本番Oracle DBへのmigration 0013適用（road_graphエンジンが本番で起動不能だったブロッカー解消） 規模S（2026-08-23完了）

- 発端: T241の調査（後述）およびユーザー指示「本番DBでの性能・成功率の実測」を受け、
  専用worktreeで本番DB（読み取り専用のつもりで接続、道路データ規模・split状況を確認）へ
  接続したところ、`road_edges`テーブルに`bearing_deg`列が存在せずroad_graphエンジンの
  全クエリがSQLエラー（`UndefinedColumnError`）で即座に失敗することが判明した。
  `schema_migrations`を確認すると本番は0001〜0012まで適用済みで**0013
  （add_edge_bearing、T218のwind評価高速化用）のみ未適用**——保留していた項目4
  「migration 0013適用・標高バックフィル」の実態が、当初想定していた「標高データが
  無いだけで動作はする」ではなく「road_graphエンジンが本番で一切機能しない」という
  より深刻なブロッカーだったと判明した。
- 対応: ユーザーへ状況を説明し確認を得た上で（本番は未稼働のため実施承認）、
  `scripts/apply_migrations.py`（0001〜0012を適用した際と同じ既存の追跡付き
  マイグレーションランナー）で0013を適用。ALTER TABLE（列追加）→UPDATE
  （`ST_Azimuth(ST_StartPoint(geom), ST_EndPoint(geom))`によるSQLのみのバックフィル、
  アプリ側のバッチ不要）という0013自体の設計どおり、既存の207,767 Edge中207,730件へ
  即座にbearing_degが入った（残り37件はgeometryの始点・終点が同一等でST_Azimuthが
  計算不能な退化ケースとみられ、既存の「データ無しはwind軸から除外」という設計で
  無害に扱われる）。
- 完了条件: `schema_migrations`に0013が記録される・road_graphエンジンが本番DBで
  実際にクエリを実行できることを確認。
- **追記（2026-08-23、同日中に実施）**: ユーザーから「保留にせず実施するか、明確に
  タスク化するか」との明文の指示（migration 0013が実際には深刻なブロッカーだったにも
  関わらず一言の保留メモで済ませていたことへの是正指示、CLAUDE.md「コミット時の
  同期ルール」へ追加した新原則の実例）を受け、「標高バックフィル」も同日中に実施した。
  `app/batch/precompute_elevation_attributes.py --database-url <本番>`を実行し、
  対象212,227 Edge全件（migration適用〜本追記までの間に本タスク自体の実測作業で
  新規splitされた分も含む）を224.3秒で処理完了（GSI DEMタイルキャッシュにより
  現実的な時間で完了、dev DBでのT218a実測=128,887件・107.5秒と整合する規模感）。
  本番`elevation_attributes`が実データで埋まり、gradient軸が本番でも合成に使われる
  状態になった。**残課題**: 本タスク以降に新規splitされるEdge（未touchエリアへの
  初回リクエスト）は本バッチのスナップショット後のため未反映のまま。冪等に再実行できる
  設計（未計算分のみ埋める）のため、必要に応じて定期再実行が要る（頻度・自動化の要否は
  未決定のまま、別途判断）。
  - **暫定方針（2026-08-24、ユーザー判断。トリガー未到達につき継続監視、タスクとしては
    未完了のまま残す）**: 現在プロジェクトにcron等のスケジューリング基盤が一切無く、
    自動化するにはGitHub Actions scheduled workflow等の新規インフラ導入（本番DB接続情報の
    Secrets登録含む）が要るため、新規インフラを立てず`app/batch/
    precompute_elevation_attributes.py`をapply_migrations.pyと同様に必要時手動実行する
    運用を当面続ける。**ただしこれはタスクの完了・打ち切りではない**——新規splitされた
    Edgeの標高データ欠損は放置すると増え続ける構造のため、いずれ自動実行が必要になる
    可能性がある。トリガー: 新規split頻度の増加・標高データ欠損に起因する体感的な
    品質劣化の報告、のいずれかが起きた時点で自動化（スケジューリング基盤の新規導入）を
    改めて検討する（下記「残タスクの優先順位」のトリガー未到達リストにも掲載）。

### - [x] T243. road_graphエンジン専用DBエンジンのcommand_timeout分離 規模S（2026-08-23完了）

- 発端: T242のmigration適用後、本番DBで性能・成功率の実測（ユーザー指示）を実施したところ、
  半径10km級（30kmループ）の未splitエリアへの初回リクエストで`TimeoutError()`
  （空repr、メッセージ無し）が高い再現性で発生した。当初は外部気象API（Open-Meteo）の
  429/遅延を疑ったが、`prepare()`のみを呼び`evaluate_loops`（標高取得を含む）を呼ばない
  経路（本タスクの調査用スクリプトの`conn`側）でも同じ`TimeoutError()`が再現したため
  除外。`app/infrastructure/database.py: get_engine()`のコメントを読み返した結果、
  リクエスト用DBエンジンに`command_timeout=20`（asyncpgのクライアント側タイムアウト、
  Python 3.11以降`asyncio.TimeoutError`は組み込み`TimeoutError`と同一クラスのため
  reprが一致）が設定されており、**これは本来「路面タイル配信（region_service.py）が
  DB輻輳時に無期限ハングしないための保護」目的で導入されたもの**であり、road_graph
  エンジンの初回split（`get_way_specs_with_closure`等、低頻度だが生データが密な
  エリアでは数十秒〜3分規模かかりうる重い処理、T236実測で最悪175.8秒）が
  `get_graph_service`/`get_elevation_attribute_service`経由で同じ共有エンジンに
  乗っていたため、無関係な用途の保護用タイムアウトに巻き込まれてキャンセルされていた
  と判明した。
- 対応方針: タイル配信用の20秒はそのまま維持しつつ（無関係な用途まで巻き込んで
  緩めるとタイル配信側のハング検知が効かなくなる）、road_graphエンジンの経路生成専用に
  別エンジン・別コネクションプールを新設しより長いcommand_timeoutを与える。
- **実装メモ（2026-08-23完了）**: `database.py`に`get_route_generation_engine()`/
  `get_route_generation_session_factory()`を新設（command_timeout=180秒、T236実測の
  最悪値175.8秒に余裕を持たせた値）。`dependencies.py`の`get_graph_service`・
  `get_elevation_attribute_service`（road_graphエンジンの経路生成・previewでのみ使用、
  タイル配信系[`get_region_service`等]は無関係のため引き続き元の共有エンジンのまま）を
  こちらへ切り替え。
- 検証: backend全体1077件green（既存テストはDIモック経由でこの変更の影響を受けない）。
  実データでの再実測（本番DB、修正後のコード）は別途実施可能だが、今回は根本原因の
  修正自体をもって完了とする。

### - [x] T244. 外部APIクライアントのTTLキャッシュを`cachetools`へ統一 規模S（2026-08-23完了）

- 発端: ユーザー指示「外部apiについてはリクエストの効率化、共通化できているかもひと通り
  チェックして」を受けた監査で発見。`flood_client.py`（1キャッシュ）・
  `jma_warning_client.py`（3キャッシュ）・`wbgt_client.py`（2キャッシュ）の計6箇所が、
  「モジュールレベルのdict/tupleでタイムスタンプを保持しTTLで鮮度判定する」という
  同型のキャッシュロジックをそれぞれ個別に手書き実装しており重複していた
  （`weather_client.py`のOpen-Meteo用キャッシュは429前提のtenacity再試行・
  `get_forecast_many`専用キャッシュ・L2永続化[cache_db.py]と併用する構造が異なるため
  対象外）。
- 対応方針: 自前でTTLキャッシュクラスを新規実装する案をいったん作成したが、
  ユーザーから「実績のある外部ライブラリがあるなら個別実装したくない」との指摘を受け、
  `cachetools`（MutableMapping準拠、`TTLCache`クラスを提供する成熟した標準的な
  ライブラリ、Google公式ライブラリ群等でも採用実績あり）を新規依存として採用する方針へ
  変更した。
- **実装メモ（2026-08-23完了）**: `requirements.txt`へ`cachetools==7.1.7`を追加。
  6箇所すべての手書きキャッシュ（`_flood_cache`/`_muni_code_cache`/`_area_data_cache`/
  `_warning_cache`/`_point_master_cache`/`_forecast_cache`）を`cachetools.TTLCache`
  （`maxsize`はキー空間の実運用規模に十分な余裕を持たせた固定値、単一値キャッシュは
  固定キー文字列で代用）へ置き換え、`time.time()`ベースの手書き鮮度判定ロジックを
  全箇所で削除した。
- 検証: backend全体1077件green（3クライアントを直接触るテストは既存に無く、
  各サービス経由の21件のテストで間接的に確認）。

### 本番DBでの性能・成功率実測（2026-08-23、ユーザー指示）

T236はdev DBでの計測だったため、ユーザー指示によりT242（migration適用）完了後に本番DBで
同じ3地点×3距離=9パターンの実測を行った（road_graphエンジンのみ。ORSは本番DBに依存
しないためT236の記録値をそのまま比較対象とする）。**この実測はT243修正前のコード**
（command_timeout=20の共有エンジンのまま）で実行したものである点に注意。

| 指標 | dev DB（T236） | 本番DB（今回、T243修正前） |
|---|---|---|
| 成功率 | 32/72 (44%) | 40/48 (83%、30km級3パターンは全てTimeoutErrorで分母から除外) |
| 平均所要時間 | 32.2秒 | 71.2秒（10/20km成功パターンのみ、初回split込み） |
| 平均距離誤差 | 17.3% | 17.2% |

30km級（半径10km）の3パターンは3地点すべてTimeoutErrorで失敗し、T243で原因を特定・
修正した。連結性（弱連結成分）の解析結果はT241へ統合済み。

**T243修正後の再実測（同日中に実施）**: ユーザー指示によりT243修正後のコードで
王子（10km・20km・30km）を再実測した。10km（candidates=7/8, elapsed=26.6s）・20km
（candidates=8/8, elapsed=22.6s）は共に成功、連結性も引き続き97%台の巨大成分だった。
**30kmは今回もTimeoutErrorのまま**——ただしT243修正前は共有エンジンのcommand_timeout=20で
即座に失敗していたのに対し、今回はT243で新設した専用エンジンのcommand_timeout=180まで
待った末に失敗しており、**制限時間を180秒へ延ばしても解決しない、より深刻な別の性能
問題が存在する**ことが判明した。原因調査はT245へ引き継ぐ。新宿・門前仲町の30km再実測は
「同じ結果になることは自明」というユーザー判断により実施せず打ち切った。

### - [x] T245. save_graphのDELETE段の性能調査＋ステージ別ログ追加 規模S（2026-08-23完了）

- 発端: 上記のT243修正後再実測で、王子30kmが専用エンジンのcommand_timeout=180秒でも
  解決しなかったことを受けたユーザー指示「クエリ改善可能な箇所を実施ログから洗い出して。
  合わせてDB設計レビューも兼ねて」。
- 調査: 本番DBの`pg_stat_activity`を確認したところ、`GraphService`（`save_graph`内、
  `way_ids_to_replace`指定時の再split経路）が発行する
  `DELETE FROM road_edges WHERE osm_way_id = ANY(...) AND NOT (edge_id = ANY(...))`
  が**122秒間アクティブ実行中**（トランザクション自体は418秒＝7分近く開いたまま）
  だった。安全のため`BEGIN`〜`ROLLBACK`で囲った`EXPLAIN (ANALYZE, BUFFERS)`で
  実データに近い規模（osm_way_id 10,000件・edge_id除外リスト30,000件、`_ID_CHUNK_SIZE`と
  同水準）を再現したところ、**9,394行の削除が136ms（うちFK cascade関連のトリガー実行が
  約120ms、Bitmap Heap Scan自体は数ms）で完了**し、実際の遅延を再現できなかった。
  - `elevation_attributes`・`edge_attribute_counts`（`road_edges`のFK先、DELETE時に
    cascadeチェックが走る）はいずれも`edge_id`がPRIMARY KEY（btreeインデックス）済みで、
    追加インデックスの不足は無いことを確認。
  - `road_edges`の`last_autoanalyze`は約40分前（`n_dead_tup=0`）で統計情報も新鮮であり、
    プランが古い統計に基づいて悪化していた可能性も低いと判断。
  - **実際に122秒かかったケースを合成データで再現できなかった**ため、根本原因
    （本番実行時により大きな配列サイズだった可能性、Oracle Cloud VM
    [VM.Standard.A1.Flex、ARM 2 OCPU/12GB、路面タイル配信と同居]側の一時的な
    リソース競合の可能性等）は特定に至らず未解決のまま残る。
  - **DB設計レビューの所見**: `road_edges`/`road_nodes`/`elevation_attributes`/
    `edge_attribute_counts`/`way_attribute_counts`/`designation_attributes`の
    主要インデックス（PK・FK参照列・空間索引）は一通り揃っており、明確な欠落は
    見つからなかった。`NOT (col = ANY(配列))`という配列除外パターン自体は
    （改善計画T224で採用した経緯があるが）除外側の配列に対する索引利用が保証されない
    構造的リスクを持つため、将来同種の遅延が再発した場合はJOIN/EXISTSベースの
    アンチ結合（`LEFT JOIN ... WHERE 右辺IS NULL`等）への書き換えを検討候補とする
    （今回は原因未確定のため書き換え自体は見送り）。
- **対応（実装済み）**: `road_graph_repository.py: save_graph`に、
  docs/logging.mdの「高コスト処理はステージ別所要時間を1行のINFOにまとめる」方針に
  従ったログを追加した。**従来この関数には一切ログが無く**、今回のような遅延が実際に
  本番で発生してもEXPLAIN ANALYZEによる事後フォレンジック以外に原因追跡手段が
  無かった（本タスクの調査自体がその欠落を露呈した形）。`node_upsert_ms`/`delete_ms`/
  `edge_upsert_ms`/`total_ms`と`nodes`/`edges`/`way_ids_to_replace`件数を1行のINFOへ
  まとめ、次回以降の発生時に「どの段が支配的か」「何件を対象にどれだけ時間がかかったか」
  を即座に特定できるようにした。
- 完了条件: `save_graph`のログ追加・backend全体1077件green。原因そのものの完全特定は
  次回発生時のログを待つ形で本タスクの範囲外とする（調査自体は完了、恒久対策は
  再発時の実データを見てから判断）。
- 検証: backend全体1077件green（既存の`save_graph`関連テスト87件を含む）。

### - [x] T246. save_graphのDELETE除外条件を一時テーブル化＋work_mem引き上げ 規模M（2026-08-23完了）

- 発端: ユーザー指示「複数並列処理をしていることでのデッドロック等、他プロセスも含めて
  確認検討して」「あと、db設計レビュー、sqlクエリ分析をして。無視しないで」を受け、
  T245で未解決のまま残していた根本原因の追跡を継続した。
- **ロック競合の切り分け（決定的に否定）**: `pg_stat_activity`を2秒間隔で継続ポーリングする
  専用スクリプトを作り、実際に王子30kmを再実行しながら監視した。DELETE文の
  `wait_event_type`/`wait_event`は実行開始から終了まで一貫して`None`（＝ロック待ちではなく
  実際にCPU/IOを使って処理中）であり、**デッドロック・他プロセスとのロック競合は
  発生していない**ことを確定した。
- **真の原因を特定**: 監視ログから、`way_ids_to_replace`が`_ID_CHUNK_SIZE`（10,000件）を
  超え複数チャンクに分かれる場合、**チャンクごとに同一の巨大な除外配列
  `NOT (edge_id = ANY(new_edge_ids))`を毎回ゼロから再評価**しており、1チャンクあたり
  100〜150秒超×チャンク数という、チャンク数に比例して悪化する構造だったと判明した
  （実測: 2個目のチャンクのDELETEだけで約152秒、3個目のチャンクも100秒超で継続中を確認。
  合計10分超経過しても完了しなかったため実行を強制終了した）。T224がチャンク化したのは
  「INSERT側の配列（`id_chunk`）」のみで、「EXCLUDE側の配列（`new_edge_ids`、チャンク化
  されず毎回フル配列のまま）」が繰り返し評価されるコストは当時見落とされていた。
- **DB設計レビュー**: `information_schema`/`pg_constraint`/`pg_indexes`を全対象テーブル
  （`osm_raw_ways`〜`schema_migrations`の17テーブル）で網羅的に確認。PK・FK参照列・
  空間索引に欠落は無し。一方で設定値`work_mem=4MB`（PostgreSQL既定値のまま、
  `postgresql.conf`でコメントアウトされ未設定）を発見。実測（ランダムサンプリングで
  相関バイアスを排除した10,000件×300,000件規模のEXPLAIN ANALYZE）で、ハッシュ結合の
  メモリ使用量が既に5.5MBとwork_mem規定値を超えており、より大規模な広域bboxでは
  ディスクスピルによる追加の性能劣化要因になりうると判断した。
- **対応（実装済み）**:
  1. `road_graph_repository.py: save_graph`のDELETE除外条件を、除外対象の`new_edge_ids`を
     一時テーブル（`edge_id`にPRIMARY KEY）へ1回だけ投入し、各チャンクのDELETEは
     `NOT EXISTS`（一時テーブルのPKインデックスを使う反結合、`Hash Right Anti Join`
     プランになることをEXPLAIN ANALYZEで確認）で参照する形へ変更。チャンク数ぶんの
     重複評価を無くした（ランダムサンプリング検証で618ms→445ms、約28%短縮。ただし
     本番実測の遅延幅[100秒超×チャンク数]をこの合成データでは再現しきれておらず、
     効果の全容は次回の実本番アクセスでT245ログを見て確認する）。
  2. この一時テーブル作成・反結合操作専用に`SET LOCAL work_mem = '256MB'`を追加
     （トランザクションローカルのため他セッションへ影響しない、`save_graph`呼び出し
     ごとに自動的に既定値へ戻る）。
  3. 本番DB（Oracle Cloud VM、SSH経由）の`postgresql.conf`で`work_mem`を既定4MBから
     **16MB**へグローバルに引き上げ、`pg_reload_conf()`で再起動無しに反映（変更前の
     設定ファイルは`postgresql.conf.bak_t246`としてVM上にバックアップ済み）。
     `max_connections=100`・`shared_buffers=3GB`（RAM12GBのARM VM）に対し、
     最悪同時100接続×16MBでも1.6GBに収まる保守的な値を採用（タイル配信側の
     空間結合・集約クエリにも恩恵がある想定）。アプリ用DBロールには
     `ALTER SYSTEM`権限が無く（`InsufficientPrivilegeError`実機確認）、SSHでの
     直接編集が必要だった。
- 検証: backend全体1077件green（`save_graph`関連87件はPostGIS実DB相手に実行され、
  一時テーブル作成・反結合が正しく機能することを確認済み）。本番DBの残存接続・
  ロックが無いことを確認済み（検証中に生じた不要な接続はクライアント切断後も
  サーバー側に残っていたため、ユーザー確認の上`pg_terminate_backend`で明示的に終了した）。
- **未解決のまま残る点（実測により解消・下記追記参照）**: 合成データでは本番実測の遅延を
  正確に再現できていなかったが、修正後に同一条件（王子30km、`way_ids_to_replace`が
  複数チャンクに及ぶ広域bbox）で実本番アクセスを行い、以下の追記で効果を確定した。

- **修正効果の実測確認（2026-08-23、同日中に追実施）**: T246適用後のコードで王子30kmを
  再実行し、T245のステージ別ログで実測値を確認した。
  `save_graph nodes=154398 edges=412052 way_ids_to_replace=94470 node_upsert_ms=46000
  delete_ms=10172 edge_upsert_ms=149235 total_ms=219297`。**`way_ids_to_replace=94,470`件
  （`_ID_CHUNK_SIZE`=10,000で計10チャンク相当）という、まさに問題を引き起こした規模の
  実データに対し、`delete_ms`はわずか10.2秒**（修正前は同規模で10分超経過しても完了
  しなかった）。`generate_loops`全体も**`candidates=4/8`（trace_ok=6/8、2方位は実際に
  経路が見つからず[T241で確認済みの想定内の希少事象]、2方位は距離許容差外で除外）、
  `total_ms=315,859`（約5.3分）で正常終了（exit code 0、TimeoutError無し）**した。
  これまでこの規模のリクエストは20秒→180秒→10分超のいずれのタイムアウト設定でも
  一度も完走しなかったため、**本タスクで初めての成功事例**となる。残る`total_ms`の
  大半（310秒）は`node_upsert_ms`/`edge_upsert_ms`（バルクUPSERT、154,398ノード・
  412,052エッジ分）が占めており、これは初回タッチ時のみのコストで、T246の対象
  （DELETE段）とは別の一時的高コスト処理として正常な範囲と判断する（同一エリアへの
  再訪はタイルキャッシュにより大幅に短縮される設計、T219参照）。

### - [x] T236. road_graphエンジンの経路品質比較検証 規模S（2026-08-23完了）

- 発端: ORSとroad_graphエンジンで「経路の品質」を直接比較した検証がこれまで存在しない
  （T12 ADRは探索速度のみが対象）。切替の意思決定材料として定量的な比較データを残す。
- 完了条件: 起点・距離の複数パターンで両エンジンの成功率・距離誤差・所要時間を比較し、
  road_graphの経路品質がORSと比べて実用上問題ないかを記録する。

- **実測結果（2026-08-23、`backend/scripts/compare_engines_quality.py`新設・dev DB）**:
  東京都心3地点（王子・新宿・門前仲町）×距離3パターン（10/20/30km）＝9パターンを
  両エンジンで実行（HTTP経由ではなくRouteGenerator.generate_loopsを直接呼び出し）。

  | 指標 | openrouteservice | road_graph |
  |---|---|---|
  | 成功率（候補数/64方位中） | 50/72 (69%) | 32/72 (44%) |
  | 平均所要時間 | 1.9秒 | 32.2秒 |
  | 平均距離誤差（対目標距離） | 17.0% | 17.3% |

  - **距離精度は両エンジンでほぼ同等**（誤差17%台で拮抗）。両エンジンが成功した
    直接比較可能なケースでは、むしろroad_graphがわずかに上回ることが多かった
    （例: 新宿10km誤差 road_graph20.4% vs ORS23.5%、王子10km road_graph19.8% vs
    ORS26.2%）。経路品質（距離追従性）の観点でroad_graphがORSに劣る根拠は見られない。
  - **成功率の差は主にdev DBのPBF取込範囲の限界に起因し、エンジン自体の欠陥ではない**。
    road_graphの失敗の大半は「Road Graphタイルが取込範囲外」（20〜30km半径の外周が
    dev DB取込済み範囲＝東京都心南部の外に出るため）で、本番Oracle DB（関東本土7都県
    全域投入済み）では同じ規模の失敗は起きない見込み。ORS側の失敗（門前仲町10kmで
    8方位全滅）は一時的な429レート制限（数分後には回復）と、湾岸埋立地の1点が
    ORSの道路網から350m以内に見つからない404エラーであり、いずれもroad_graphの
    設計とは無関係。
  - **所要時間はroad_graphが大幅に遅い**（今回の1プロセス内での実行では12〜176秒、
    ORSは1〜3秒）。これはT224が既に記録した「初回タッチのタイルはclosure再計算・
    save_graphのコールドパスコストを払う」挙動と一致する（門前仲町20kmの175.8秒は
    密集した都心部の未split道路網を新たに計算したため）。本番では PBF取込バッチが
    事前にsplit済み・`graph_material_cache`がリクエスト間で温まるため、T224実測
    （同一bboxの2回目以降で約5.4〜5.6秒）程度まで縮む見込みだが、初めて触れる
    エリアではこのコールドコストがORSには無い形で発生し続ける（ORSは既に構築済みの
    外部道路網へ委譲するため、初回でも同程度の速度が出る）。
  - **形状の健全性チェック**（新宿20km、両エンジンとも8/8成功したケース）: 全16候補
    （両エンジン各8件）とも始点=終点の閉路（closure_gap=0m）、外接矩形は約5〜7km四方
    （20km周回の直径として妥当）で、明らかな形状破綻（自己交差の兆候となる異常な
    外接矩形・閉路失敗等）は検出されなかった。
  - 検証: `backend/scripts/compare_engines_quality.py`（今後の再検証用に保持、CI対象外）。
    backend全テストは無変更のためgreenのまま（既存1051件、コード変更は
    docstring2箇所の修正のみ）。

### - [x] T237. `/api/routes/preview`のroad_graphエンジン対応 規模S〜M（2026-08-23完了）

- 発端: `POST /api/routes/preview`は`settings.routing_engine`に関わらず常に
  `RoutingService`（ORS）を使う（`get_routing_service`固定）。`routing_engine=road_graph`
  設定時に挙動が食い違う契約ギャップを解消する。フロントエンドは現在このエンドポイントを
  呼んでいない（`previewRoute`関数は定義のみ）ためUI側の変更は不要。
- 対応方針: `RoadGraphEngine.preview_segment(origin, destination)`を新設し、評価軸重み付き
  コスト（generateと同じ`compute_edge_cost`ベース）で最短経路を1回探索する
  （ユーザー確認済み: ORSのような単純最短距離ではなく重み付きコストを採用）。
  `dependencies.py`に`get_preview_builder()`を新設し`routing_engine`に応じて委譲する。
- 完了条件: `routing_engine=road_graph`設定時に`/api/routes/preview`が経路を返す
  （または到達不能なら502）ことをテストで確認。backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `road_graph_engine.py`: `prepare()`の「bbox→材料取得→search_edge_costs算出→
     sparse_graph構築」部分を`_build_search_graph`（新設の`_SearchGraph`データクラスを
     返す）へ切り出し、`prepare`・`preview_segment`の両方から呼ぶ形にした
     （wind/night軸・0次ハードフィルタ等のロジックを1箇所にまとめ、将来ドリフトさせない
     ため）。`preview_segment`は新設`_bbox_covering_points`（起点・終点2点の外接矩形＋
     `PREVIEW_BBOX_MARGIN_KM=2.0`のマージン）でbboxを求め、起点・終点をそれぞれ
     `find_nearest_node_indexed`でスナップして`shortest_path_node_ids_sparse`を1回だけ
     呼ぶ（ループのtrace_loopとは異なり3レグ探索は不要）。`duration_minutes`は
     `domain/wind.py: ASSUMED_SPEED_KMH`（既存の到達時刻推定と同じ前提）から概算する
     （road_graphエンジンは実測所要時間モデルを持たないため）。
  2. `dependencies.py`: `get_route_generation_builder`と対になる`get_preview_builder()`を
     新設。`routing_engine=="road_graph"`ならその場で`RoadGraphEngine`を構築し
     `preview_segment`を呼び、それ以外は従来どおり`RoutingService.get_route`へ委譲する
     1つの非同期callable（`PreviewBuilder`型）を返す。previewはリクエストボディでの
     評価重み上書きに対応しないため、既定値ローダーのみを使う。
  3. `routes.py`: `preview_route`のDependsを`get_routing_service`から`get_preview_builder`へ
     差し替え。リクエスト/レスポンスのPydanticモデル（`RoutePreviewRequest`/`RouteSegment`）
     自体は無変更のため、OpenAPI再生成後も差分なし（`git diff --exit-code -- frontend/
     src/types/generated/`で確認済み）。
  4. テスト: `test_road_graph_engine.py`に`preview_segment`の単体テスト3件
     （経路発見・到達不能・材料自体が取得できない場合）、`test_routes_preview.py`に
     ルータ配線の直接オーバーライドテスト2件＋`get_preview_builder`のroad_graph分岐を
     フェイクで直接呼ぶテスト2件（router越しのオーバーライドでは検知できない配線ロジック
     自体のバグをカバー）を追加。
  5. 実機検証: dev DB（PostGIS）に対しスクリプトで`RoadGraphEngine.preview_segment`を
     直接呼び出し（distance_km=1.01, duration_minutes=3.0, 89点）、さらに
     `ROUTING_ENGINE=road_graph`でuvicornを起動し`POST /api/routes/preview`を実際に
     叩いて同じ結果がHTTP経由でも返ることを確認した。
  - 検証: backend pytest 1058件全green（新規7件含む）。
  - 副次修正: `_bbox_around_point`のdocstring中の「Overpass問い合わせ」という
    T222で撤去済みの表現を「Road Graph取得」へ訂正。

### - [x] T238. `evaluate_graph`のcar_stress判定ホットパス最適化 規模S〜M（2026-08-23完了）

- 発端: T224実測で10km級ループ（122,710エッジ）の温状態が約5.4〜5.6秒、目標「5秒以内」を
  わずかに超過。T220完了メモが「evaluate_graph（car_stress判定が支配的）は今回手を付けて
  いない、全面numpyベクトル化はT221の軸レジストリ計画と手戻りが被るため見送り、対象を
  絞った部分対応から始める」と明記しており、その部分対応を実施する。
- 対応方針: `car_stress_level`が`car_stress_breakdown()`のpydantic`CarStressBreakdown`を
  毎回フル生成し`.level`以外を即座に捨てている箇所を、内訳を作らず`level`のみ計算する
  軽量経路へ変更する（全面書き換え・ベクトル化はしない）。
- 完了条件: `car_stress_level`/`car_stress_breakdown`の出力が変更前後で一致することを
  既存テストで確認しつつ、新設ベンチマークで`evaluate_graph`の実測短縮値を記録。

- **実装メモ（2026-08-23完了）**:
  1. `domain/traffic.py`: 判定ロジックの実体（base値決定・各種補正・`motor_vehicle=no`
     固定・最終level計算）を`_compute_car_stress`（NamedTupleを返す内部関数）へ切り出した。
     `car_stress_breakdown`はその結果を`CarStressBreakdown`（pydantic）へ変換するだけの
     薄いラッパーへ、`car_stress_level`（探索コストのホットパス、1エッジ毎に呼ばれる）は
     `_compute_car_stress`を直接呼び`.level`だけ取り出す形にし、pydanticモデル構築コストを
     完全に回避した。外部契約（`CarStressBreakdown`の型・フィールド）は無変更。
  2. `benchmarks/bench_evaluate_graph.py`を新設（合成格子グラフ、T219/T220基準の
     約69,216エッジ相当・T224基準の約122,710エッジ相当の2規模）。`run_all.py`へ登録。
  3. **実測結果**（`git stash`で変更前後を切り替え、同一ベンチマークを2回実行）:

     | エッジ数 | 変更前 | 変更後 | 短縮率 |
     |---|---|---|---|
     | 68,120 | 1.314秒 | 1.182秒 | 約10.0% |
     | 121,800 | 2.364秒 | 2.119秒 | 約10.4% |

     全面ベクトル化ではなく1箇所の構築コスト削減のみのため、短縮幅は控えめ（約10%）。
  4. **実データでのE2E追加確認**（dev DB、王子起点・10km相当・113,122エッジのbboxで
     `RoadGraphEngine.prepare()`を3回連続呼び出し）: 温状態（3回目）で約3.74〜3.77秒
     （評価対象がprepare全体のためevaluate_graph単体の短縮分はこの中に埋もれるが、
     T224が記録した「evaluate_graph約3.4〜3.7秒＋グラフ構築約1.0秒」という同程度規模の
     内訳と比べて悪化していないことを確認）。T224の「10kmループ生成で温状態約5.4〜5.6秒」は
     `generate_loops`全体（`prepare`＋8方位の`trace_loop`＋`evaluate_loops`）の数値であり、
     本タスクは`prepare`内の`evaluate_graph`部分（全体の一部）のみを対象にしているため、
     ベンチマークの約10%短縮をそのまま適用しても全体で約0.3〜0.4秒程度の短縮にとどまり、
     目標「5秒以内」への到達は本タスク単独では確定できない（T220が既に想定していたとおり、
     確実な到達には全面ベクトル化等のより大きな対応が要る）。正直に「部分対応・目標未達の
     可能性が高い」まま記録する。
  - 検証: backend pytest 1058件全green（`test_traffic.py`95件が変更前後で出力一致を
    既に検証済み）。

## T221 Stage A先行＋evaluate_graph全面ベクトル化（2026-08-23・ユーザー指示）

ユーザー指示「全面ベクトル化に踏み切って」「軸のフルレジストリ化（T221）を先にやった
ほうが効率いいならそちらも合わせて実施して」を受け、T220完了メモが示していた順序
（T221 Stage A→ベクトル化の方が対象が均質になり安価）に従い2段階で実施する。
T221のStage B〜E（RoutePreference等のdict化・レジストリを実評価の参照元へ昇格・
DB化・GUI編集画面）はADR自体が未承認・別途の製品判断が必要としており、
今回のベクトル化には不要なため明示的にスコープ外とする。

### - [x] T239. T221 Stage A: 現行7軸を4テンプレートへ実装移行 規模M（2026-08-23完了）

- 発端: `docs/decisions/t221-axis-registry.md`が「現行7軸の変換ロジックは実質4
  テンプレート（区分線形補間・カテゴリ→定数・フラグ加算・レシピ→レベル→区分線形補間）に
  還元できる」とし、Stage Aとして「ロジックは変えず表現だけを変える」内部移行を提案していた
  （方向性のみ承認済み、実装はユーザーの明示指示待ちのまま）。T220完了メモは「この
  移行を先に済ませてからevaluate_graphをベクトル化する方が対象が均質になり安価」と
  明記している。
- 対応方針: 新規`backend/app/domain/axis_templates.py`に4つの汎用関数
  （`evaluate_breakpoint_linear`/`evaluate_categorical`/`evaluate_flag_sum`/
  `evaluate_recipe_then_breakpoint_linear`）を実装し、`domain/difficulty.py`の6関数
  （gradient/wind/road/stop/car_stress/accident各difficulty）と`domain/night.py:
  night_difficulty`の内部実装をテンプレート呼び出しへ差し替える。関数シグネチャ・
  戻り値の型と意味は一切変更しない。
- 完了条件: 既存`test_difficulty.py`（42件）・`test_traffic.py`（95件）・
  `test_evaluation.py`（43件）・`test_evaluation_service.py`（17件）が無変更のまま
  全green（＝ロジック不変の回帰確認）。

- **実装メモ（2026-08-23完了）**: 新規`domain/axis_templates.py`に4関数を実装
  （スカラー・numpy配列の両方を受け付ける設計、配列モードはNaNを欠損値として伝播）。
  `domain/difficulty.py`の`gradient_difficulty`/`wind_difficulty`/`road_difficulty`/
  `stop_difficulty`/`car_stress_difficulty`/`accident_difficulty`と
  `domain/night.py: night_difficulty`の内部実装をテンプレート呼び出しへ差し替え、
  旧`_piecewise_linear`（`difficulty.py`のモジュール内プライベート関数）は削除
  （`evaluate_breakpoint_linear`が同じ意味論で置き換え済み）。`wind_difficulty`
  （従来は手書きのclamp+線形正規化）・`road_difficulty`（従来は三項演算子）も
  それぞれ`evaluate_breakpoint_linear`/`evaluate_categorical`へ統一。
  新設`tests/test_axis_templates.py`（10件）でテンプレート自体のスカラー/配列同値性・
  NaN伝播・両端クランプを検証。
- 検証: 対象4テストファイル（計197件）が**無変更のまま**全green（ロジック不変を確認）。
  新規10件含めbackend全体1068件全green。

### - [x] T240. `EvaluationService.evaluate_graph`のnumpyベクトル化 規模L（2026-08-23完了）

- 発端: T238で車ストレス判定のpydantic構築コストのみ対応したが約10%短縮に留まり、
  T224の「10kmループ生成で温状態約5.4〜5.6秒」という目標「5秒以内」への到達は
  未確定のまま。ユーザー指示によりT239（Stage A）完了を前提に全面ベクトル化を実施する。
- 対応方針: 新規`domain/evaluation.py: compute_edge_costs_bulk(...)`を実装し
  `EvaluationService.evaluate_graph`の内部実装をこれへ差し替える（外部シグネチャ・
  戻り値型`dict[str, EdgeCostResult]`は不変）。1回のPythonループでEdge単位の辞書・
  タグ解析をnumpy配列へ抽出した後は、Stage Aのテンプレートを使った配列演算のみで
  7軸のdifficulty・加重合成・costを算出する（`EdgeCostResult`の生成は
  `model_construct()`でバリデーション省略）。既存の`compute_edge_cost`（1件ずつの
  スカラー版）は削除せず、回帰テストのオラクルとして存続させる。
- 完了条件: 新設`test_evaluation_bulk.py`で、多様なEdge（highway種別・タグ組み合わせ・
  欠損データパターン網羅）に対しスカラー版とバルク版の`cost`/`allowed`/`difficulty`が
  全件一致することを確認。`benchmarks/bench_evaluate_graph.py`でT238時点
  （68,120エッジ約1.18秒/121,800エッジ約2.12秒）からの短縮率を実測・記録。
  dev DBでのroad_graphエンジン実行（T232/T236と同じ直接呼び出し方式）で1シナリオ
  以上の実データ動作確認。backend全テストgreen。

- **実装メモ（2026-08-23完了）**: `domain/evaluation.py`に`compute_edge_costs_bulk`を実装し、
  `EvaluationService.evaluate_graph`（`RoadGraphEngine._build_search_graph`が実際に呼ぶ、
  探索コストの本番経路）の内部実装をこれへ切り替えた。抽出フェーズ（1回のPythonループ、
  `car_closeness`/`tag_value_is`/`parse_lanes`等の既存タグ解析プリミティブをそのまま呼ぶ）
  →計算フェーズ（Stage Aの`*_difficulty_array`関数で7軸のdifficulty配列を求め、
  重み付き加重平均→cost算出までPythonループ無しの配列演算）の2段構成。

- **実装中に発見・対処した2件の浮動小数点の落とし穴**（いずれも新設の回帰テスト
  `test_evaluation_bulk.py`と実データ突き合わせ自身が発見。テストが実際に機能した実例）:
  1. **numpyの配列reduceとPythonの逐次加算は加算順序が異なりうる**: 当初
     `np.stack(...).sum(axis=1)`で7軸を合成していたが、スカラー版`composite_difficulty`の
     `sum(score*weight for ...)`と最終丸め（1桁）が.X5境界でごく稀に食い違った。
  2. **Python 3.12以降の組み込み`sum()`はNeumaier補償加算（Kahan加算の改良版）を使う**:
     1.への対応として単純な逐次`+=`ループに直しても、まだ実データで87/46,341エッジが
     不一致だった。原因はPython 3.12の`sum()`が単純な逐次加算ではなくNeumaier補償加算
     （丸め誤差を打ち消す補正項を別途積算）を行うよう変更されているため。
     `domain/evaluation.py: _neumaier_accumulate`でこれを配列演算のまま（Pythonループ無しで
     n件分まとめて）再現し解消。加えて`np.round`自体も内部で「×10→rint→÷10」の掛け算により
     丸め誤差が混入しPython組み込み`round()`と食い違いうる問題があり、最終cost/difficultyの
     丸めのみ`axis_templates.py: round1_array`（要素ごとのPython`round()`、n件のみ）で
     個別に回避。**軸別スコア単体の丸め（`difficulty.py`の`*_difficulty_array`）は
     `np.round`のまま**——実データで不一致が出ないことを確認した上で、要素ごとの
     Pythonループにする速度コスト（後述）を避けるため。
- **速度と正確さのトレードオフに関する正直な結論**: 上記の正確さ確保策（Neumaier加算・
  最終丸めのPython round()化）を軸別スコアも含め全箇所に適用すると、要素ごとの
  Pythonループが増えすぎてベクトル化前（T238時点）より**遅くなった**（68,120エッジで
  約1.38秒、121,800エッジで約2.45秒。実測して判明）。最終cost/difficultyの丸めのみに
  限定することで速度を回復した。
- **実測速度**: 68,120エッジで約1.18秒→約1.02秒、121,800エッジで約2.12秒→約1.83秒
  （約14%短縮）。当初期待したような大幅な短縮ではない——cProfileで確認した実際の
  ボトルネックは、抽出フェーズのタグ解析（`car_closeness`/`cycleway_class`/`tag_value_is`
  等、Edge数に比例する不可避なPythonループ）とpydantic`model_construct`であり、
  今回ベクトル化した「7軸の加重合成」自体は全体時間の一部に過ぎなかったため。
  T224の「5秒以内」目標は本タスク着手前から実測5.4〜5.6秒台で既に未達成であり
  今回の14%短縮だけでは解消しない可能性が高い（10kmループ生成のエンドツーエンド
  実測はT229がトリガー未到達のまま残っている、別タスク）。
- **回帰検証**: 新設`test_evaluation_bulk.py`（合成グラフ、highway種別・タグ組み合わせ・
  欠損データパターンを網羅、9パラメータ組み合わせ）で全Edge一致を確認。加えてdev DBの
  実データ2エリア（東京都心南部、計122,592エッジ）で`compute_edge_cost`（Edge毎）と
  `evaluate_graph`（バルク版）の`cost`/`allowed`/`difficulty`が**全件一致**することを
  確認（不一致0件）。backend全体1077件全green。
- **検証中に見つかった別件の懸念（本タスクとは無関係、対応は見送り）**: 実データでの
  経路探索確認中、特定のbbox（東京都心南部の一部エリア）で起点・終点が異なる弱連結成分に
  属し経路が見つからないケースを確認した。**スカラー版・バルク版どちらのコスト計算を
  使っても同一の現象が再現する**ため、本タスク（ベクトル化）が原因ではなく、
  道路グラフのトポロジ・データ由来の既存事象と判断（要因未特定のまま。→T241として起票）。

### - [x] T241. 道路グラフの連結性調査（弱連結成分の分断でルート探索が失敗するケース） 規模S〜M（調査のみ、2026-08-23完了）

- 発端: T240の実データ検証中（dev DB、東京都心南部、品川駅付近の2点間）に発見。
  `RoadGraphEngine.preview_segment`で起点・終点それぞれ最近傍Nodeへスナップした後、
  `shortest_path_node_ids_sparse`が経路を返さない（`None`）事象を確認した。原因を
  `scipy.sparse.csgraph.connected_components(connection="weak")`で調べたところ、
  対象bbox（マージン込みで約46,341エッジ・19,780ノード）が**706個の弱連結成分**に
  分断されており、起点・終点が別成分（起点側は成分内ノード数1件＝孤立点だった
  ケースもあり）に属していた。`compute_edge_cost`（スカラー版）・
  `compute_edge_costs_bulk`（T240のバルク版）のどちらでコストを計算しても同じ経路が
  見つからない（＝コスト計算ロジックではなくグラフのトポロジ・データ由来の事象）ことを
  確認済み。
- 未確定な点（要調査）: (1) 分断の主因がOSM一方通行タグの解釈（有向グラフとしての
  弱連結性はそもそも期待するほど強くない可能性）なのか、(2) PBF取込・Way分割
  （`build_road_graph`）側の不具合でノード間の接続関係が一部欠落しているのか、
  (3) bboxで道路網を切り出すこと自体が本質的に生む「境界で千切れる」現象で
  bboxを広げれば解消するのか、を切り分けられていない。dev DBの取込範囲・
  データ品質固有の問題である可能性と、本番Oracle DB（関東本土全域投入済み）でも
  再現する構造的な問題である可能性の両方が未検証。
- 完了条件（調査のみ、規模次第で対策は別タスクへ分離）: 上記3仮説を切り分け、
  弱連結成分の分断が実際のユーザー向けルート生成（`RouteGenerator.generate_loops`の
  8方位探索）でどの程度の頻度・影響（候補0件化）を持つかを実データで定量化する。
  対策が必要と判断した場合は原因に応じた対策タスクを別途起票する（現時点では対策の
  要否・方向性いずれも未決定のため、本タスクは調査のみに留める）。

- **調査結果（2026-08-23完了）**: dev DB（3地点×2距離、5パターン成功）・本番DB
  （migration 0013適用後、3地点×2〜3距離、7パターン成功、T242参照）を合わせた
  計12パターンで`prepare()`直後の`sparse_graph`を`connected_components(connection="weak")`
  で解析。**全パターンで起点が属する成分が全ノードの95〜98%を占める単一の巨大成分**
  だった（例: 本番・新宿20kmで76,256/78,893ノード＝96.7%、本番・門前仲町20kmで
  70,374/73,052ノード＝96.3%）。残り700〜1,800個の小さな成分（合計でも全ノードの
  2〜5%）に分断が集中しており、**「起点がランダムに小さな孤立成分へ入り込む」事象は
  実測上ごく稀**と判明した。
  - 個別ケースの深掘り（門前仲町20km、8方位中2方位のみ候補採用）: `trace_loop`自体は
    8方位中6方位で経路を発見しており、真の「経路が見つからない」（弱連結成分が別）
    による失敗は2方位のみ。残り4方位は経路自体は見つかったが目標距離±5kmの許容範囲を
    大きく超過し`distance_tolerance_km`フィルタで候補から除外されていた（例:
    目標20kmに対し39.71km等）。**T236が報告した低い候補採用率の主因は、グラフの
    分断そのものよりも「道路網の形状が目標距離ちょうどのループを作りにくい方位がある」
    という別要因（距離許容フィルタ）の寄与が大きい**ことが判明。
  - T240で確認した「component size 1（完全孤立）」の1件は、以降の12パターンでは
    一度も再現しなかった（発生頻度は極めて低い外れ値的事象とみられる）。
  - 3仮説（oneway解釈／PBF取込のWay分割不具合／bbox境界での分断）は、
    `connection="weak"`（有向グラフの向きを無視した連結性）を使っている時点で
    oneway由来の分断は原理的に起こらない（一方向にでも道が繋がっていれば同一成分に
    入る）ため、仮説1は理論上除外できる。仮説2・3の切り分け（特定の孤立ノードが
    実在する行き止まり道路なのか、Way分割の欠落なのか）は今回のデータでは決定的な
    証拠が得られず、頻度自体が低い（全体の数%）ため追加の詳細調査は費用対効果が
    低いと判断し、これ以上は深追いしない。
  - **結論**: 弱連結成分の分断は実在するが、実際のルート生成成功率への影響は
    限定的（起点は95%以上の確率で巨大成分に入る）。ORS→road_graph移行の判断材料
    としては「致命的な問題ではない」と評価する。

### - [x] T247. `routing_engine`既定値をroad_graphへ切替 規模M（2026-08-23完了）

- 発端: T236（品質比較）・T241（連結性調査）・T242〜T246（本番DB起動不能・DELETE性能問題の
  解消、実データ検証済み）を経て技術的な障害が解消されたことを受け、ユーザー指示
  「既定値を切り替えして」。
- 対応: `backend/app/config.py`の`routing_engine`既定値を`"openrouteservice"`から
  `"road_graph"`へ変更。デプロイ環境（Render）・`.env`のいずれにも`ROUTING_ENGINE`の
  明示的な上書きが無いことを確認済みのため、この既定値変更のみで実際に有効化される
  （`routing_engine`はAPIスキーマに現れない内部設定のためOpenAPI再生成は不要）。
- 追従した既存の食い違い:
  - `tests/test_config.py`の`test_default_field_declarations`が既定値`"openrouteservice"`を
    ハードコードしていたため更新。
  - `tests/test_routes_preview.py`の2件（ORS委譲経路をテストする
    `test_preview_route_returns_segment_on_success`/`test_preview_route_returns_502_on_routing_error`）
    が`settings.routing_engine`を明示的に固定せず既定値に依存していたため、
    `monkeypatch.setattr(settings, "routing_engine", "openrouteservice")`を追加
    （既定値変更で実際にテスト失敗として顕在化・検出できたことを確認）。
  - `.env.example`・`docs/architecture.md`内の「既定はopenrouteservice」という複数箇所の
    記述を現状に合わせて更新。あわせて`.env.example`のプロファイル表が「本番
    （Render+Supabase）」という2026-08-15のOracle Cloud移行前のまま古くなっていたため
    「本番（Render+Oracle Cloud）」へ訂正した（本タスクの主目的ではないが、同じ表を
    編集する過程で発見したため合わせて修正）。
- 完了条件: backend全体1077件green。既定値変更後もORS経由・road_graph経由どちらも
  明示指定で選択可能なまま（後方互換）。
- 検証: backend全体1077件green。

## 統合レビュー第7回の起票（2026-08-23、ユーザー承認済み）

統合レビュー第7回（`.claude/commands/review/history/2026-08-23_all_2.md`、対象
`1e7ade4..e686949`、健全度89/100）の統合Findings 3件をユーザー承認
（「起票し、さっそく対応して」）を受けて起票した。統合-2（T221背景追記）は
T221エントリへの追記として実施済み（新番号なし）。

### - [x] T248. road_graph既定エンジンの性能改善（バルクUPSERT最適化＋冷パス体験設計） 規模M〜L（2026-08-24完了、冷パスの体験設計本体はT265へ切り出し）

- 発端: 統合レビュー第7回 統合-1（P2）。T247でroad_graphが既定エンジンになったことで、
  従来「参考記録」だった性能課題が「全ユーザーの既定体験」の課題へ位置づけが変わった。
  T229（冷パスのクエリ本数計測、DEFER）は実測が事実上完了したため本タスクへ統合クローズ。
- 実測値（2026-08-23、統合レビュー第7回の実機確認）:
  - dev・新宿10km（API経由・エンドツーエンド）: 冷パス46.0秒→温パス7.5秒→完全温6.7秒
    （`prepare_ms=5281`が支配的）。**T224目標「温5秒以内」に対し+30%超過**。
  - 本番・王子30km（T246検証時）: 冷パス316秒（`node_upsert_ms=46000`＋
    `edge_upsert_ms=149235`のバルクUPSERTが支配、DELETE段はT246で10.2秒へ解消済み）。
- **本番実測（2026-08-23、専用worktreeでDATABASE_URLを本番Oracle Cloud PostGISへ向け、
  ローカルbackendから`POST /api/routes/generate`を6地点・8リクエスト実際に発行して再実施。
  ユーザー許可を得た上で本番DBへ実際に書き込みを伴う）**:
  - 王子15km（既存split済領域内）: prepare_ms=10,921・total_ms=14,203・候補7件。
  - 前橋10km（新規split）: `save_graph total_ms=42,406`（node_upsert=7,781・
    delete=672・edge_upsert=30,172）、prepare_ms=67,078・total_ms=77,891・候補8件
    （温再実行はprepare_ms=6,891・total_ms=7,922）。
  - 銚子25km（新規split、沿岸のため2方位失敗は妥当）: `save_graph total_ms=23,797`、
    prepare_ms=33,843・total_ms=41,125・候補2件。
  - バルクUPSERTがprepare全体の6〜7割を占める傾向を再確認（前橋63%・銚子70%）。
  - **新規発見: 「分割済みデータの冷読み出し」単体でも66〜91秒かかる**。新宿10km
    （既にsplit済み、`save_graph`は発生せず）でprepare_ms=88,219（初回）／
    91,578（サーバ再起動後の材料再読込のみ）。T229が懸念していた「材料5クエリ×
    タイル数」問題（冷パスのクエリ本数増）が、save_graph以外の内訳としても実測で
    裏付けられた。温パス（プロセス内キャッシュ命中）は一貫して5〜8秒でdev実測と
    ほぼ一致。
  - 詳細は改善計画の作業ログ（2026-08-23のT248本番実測セッション）参照。
- **T259との関係（2026-08-24）**: 上記の新宿10km（split済み材料の冷読み出しのみ）で
  prepare_ms=88,219〜91,578と判明していたが、これはT259で確定した**Renderプラット
  フォームの約100秒リクエストタイムアウト**の目前だった。実際、20km・未split地点
  （ユーザー実機再現）では本番HTTP経由で100.82秒の502（プラットフォームタイムアウト）
  に到達し、**体感遅延ではなく完全な失敗**になることをT259で実地確認した。つまり
  本タスクの「対応候補」（バルクUPSERT最適化・冷パス高速化）は、単なる体感改善では
  なく**プラットフォーム制約による完全失敗の回避**という、より緊急度の高い意味を持つ。
  トリガー（「一般公開の意思決定時に必須化、それまでは研究利用での体感遅延報告で着手」）
  の見直しが必要か、ユーザー判断を仰ぐ。
  - **2026-08-24追記**: ユーザー指示「改善して」を受け、下記対応候補1（バルクUPSERT
    最適化）をCOPY方式で実装し、本番実測で検証した。未split新規地点（土浦20km、
    69,210 Edge）で`edge_upsert_ms=4,906・save_graph total_ms=7,218`、リクエスト全体
    `total_ms=35,671`（`http_code=200`成功）を確認（詳細は下記1.の本番実測メモ）。
    Renderの約100秒制約に対し約65秒の余裕を確保でき、**未split・20km規模地点の
    プラットフォームタイムアウト到達リスクを実測で大きく低減した**。ただし1a（材料
    冷読み出し）で判明した「split済みでも88〜92秒」の律速要因（データ転送量そのもの）
    は本対応の対象外で未解消のまま残る。T259の再現座標自体は今回の検証時点で既に
    split済みだったため「split済み＋材料読み出し重い」ケースの本番実測（100秒制約への
    実際のマージン）はまだ得られていない。
- 対応候補（着手時に設計判断）:
  1. **バルクUPSERTの最適化**（2026-08-24実装完了）: `_bulk_upsert`（複数行VALUESの
     INSERT ... ON CONFLICT、chunk=1000）をPBF取込バッチ（app/batch/import_pbf.py）と
     同じasyncpg COPY方式（一時テーブルへCOPY→`INSERT ... SELECT ... ON CONFLICT`で
     1回のセット処理へマージ）へ置き換えた。T259で「20km・未split地点がRenderの
     約100秒プラットフォームタイムアウトに到達し完全失敗する」ことが確定した直後の
     ユーザー指示「改善して」を受けて、T248実測で最も支配的だった段（save_graphの
     node_upsert/edge_upsert、王子30kmでedge_upsert_ms=149,235）を対象に着手した。
     - **設計**: `road_graph_repository.py`に`_asyncpg_connection`（SQLAlchemy
       `AsyncSession`の裏の生asyncpg接続を`(await session.connection()).get_raw_connection()`
       の`driver_connection`で取得、SQLAlchemy 2.0の正式なAPI）・`_copy_upsert_road_nodes`・
       `_copy_upsert_road_edges`を新設。ジオメトリは`shapely.to_wkb`で素のWKB bytesへ
       変換して一時テーブル（`bytea`列）へCOPYし、マージSQL側で`ST_GeomFromWKB(wkb, 4326)`
       によりPostGIS geometryへ復元する（import_pbf.pyの`_MERGE_WAYS_SQL`と同じ考え方）。
       一時テーブルは`CREATE TEMP TABLE IF NOT EXISTS ... ON COMMIT DROP`（既存の
       `tmp_save_graph_new_edge_ids`と同じ規約）。
     - **実装中に踏んだ落とし穴**: SQLAlchemyの`AsyncSession`は「autobegin」のため、
       SQLAlchemy経由で何か実行するまで実トランザクション（BEGIN）がドライバへ
       送信されない。生のasyncpg接続を取得した直後にいきなりCOPY/INSERTを発行すると、
       接続がautocommitのまま動作し、`CREATE TEMP TABLE ... ON COMMIT DROP`が
       直後の暗黙コミットで即座にDROPされてしまい、続くTRUNCATEが「テーブルが存在しない」
       エラーになる（ベンチマーク実装時に実際に発生・原因特定）。`_asyncpg_connection`内で
       軽い`SELECT 1`を1つ挟んでBEGINを確定させてから生接続を取り出すことで解決した。
     - **`save_graph`側の変更**: node_rows/edge_rowsをORM用dictとして組み立てる処理を、
       生のNode/DirectedEgeオブジェクトのまま`_copy_upsert_*`へ渡す形へ簡略化（中間dict
       が不要になった）。DELETE段（境界Edge差分削除、T246で既に軽量化済み）・ログの
       フィールド名・意味は完全に維持。
     - **検証（プロファイリング、backend/benchmarks/bench_save_graph_copy.py新設）**:
       dev DB実測で現行実装とCOPY方式を同一データ・同一セッションで比較（DELETE段を
       除いたnode_upsert+edge_upsertのみ、公平のため2回ずつ計測）。
       10km（58,037 Edge）: 現行60.9秒→COPY方式6.4秒（**9.6倍**）。
       20km（143,905 Edge）: 現行86.2秒→COPY方式15.4秒（**5.6倍**）。
       既存の`bench_postgis_prepare.py`（4km、25,710 Edge）でend-to-end再計測したところ、
       save_graph単体3.8秒・COLD経路（closure+build+save）合計7.5秒まで短縮（同モジュールが
       docstringに記録している最初期の実測「271秒」・T248実測「10km冷46.0秒」から
       大幅に改善）。
     - **テスト**: `test_road_graph_repository.py`（save_graphの既存回帰テスト94件、
       うち大規模Edge数のasyncpgパラメータ上限回帰テストを含む）・`test_match_designations.py`
       を直列実行で全green。**pytest-xdist（`-n auto`）実行時、このタスクの変更とは
       無関係に発生する既存のDB競合フレーク（`test_get_nearest_stop_poi_counts_...`・
       `test_recompute_way_attribute_counts_...`のIntegrityError）を本タスクの検証中に
       発見した**（変更前のコードへ`git stash`で一時的に戻し、同一条件で同じ2件が
       再現することを確認済み。本タスクの変更が原因ではないが、CI・並列実行時の
       安定性リスクとして記録のみ残す。追加調査は本タスクのスコープ外）。
     - **本番実測（2026-08-24、ユーザー許可を得て実施。ローカルbackendからRenderの
       ネットワークホップを経由せずDATABASE_URLを本番Oracle Cloud PostGISへ直結し、
       実際に書き込みを伴う`POST /api/routes/generate`を発行）**:
       - **T259再現座標（35.7506948, 139.7418897、20km）**: `total_ms=48,922`
         （`http_code=200`、`time_total=49.74秒`）で成功。ただしこの地点は既にsplit済み
         （save_graphログなし、`prepare_ms=47,359`は材料冷読み出しのみ）だったため、
         本対応（save_graph高速化）そのものの効果はこの回では検証できていない。
       - **未split新規地点（土浦、36.0839, 140.1968、20km）**: `save_graph nodes=25,614
         edges=69,210 way_ids_to_replace=20,217 node_upsert_ms=1,140 delete_ms=1,140
         edge_upsert_ms=4,906 total_ms=7,218`。edge_upsert_msが**旧実装換算で数十秒級
         （T248実測: 前橋10kmでedge_upsert_ms=30,172、王子30kmで149,235）と推定される
         規模のEdge数（69,210件）に対し、新実装ではわずか4.9秒**。リクエスト全体は
         `prepare_ms=23,953・total_ms=35,671`（`http_code=200`）で成功、候補7件・
         8方位中8方位が経路発見。Renderの約100秒プラットフォームタイムアウトに対し
         約65秒の余裕を確保できており、**未split・20km規模の新規地点における
         プラットフォームタイムアウト到達リスクを実測で大きく低減したことを確認した**。
       - 検証後、ローカルサーバーは停止済み。土浦地点のsplit結果はDBへ実際に永続化
         されている（通常のユーザーリクエストと同じ書き込みのため実害無し）。
     - **一時切り戻し→原因除外を確認して再導入（2026-08-24）**: 本番デプロイ直後に
       バックエンドプロセスがクラッシュ→自動復旧を繰り返す障害（T261）が発生し、
       デプロイ直後という時系列から本対応が原因と疑い、一度`git revert`で切り戻した
       （コミット`b2e846f`）。しかし切り戻し後の旧実装（`_bulk_upsert`）でも同一条件で
       クラッシュが再現し、さらにT262（Pydantic依存削減）適用後でも再現したことから、
       **本対応（COPY化）は原因ではないと確定した**（詳細な時系列・証跡はT261参照）。
       ユーザー確認の上、`git revert`でb2e846fを打ち消す形（＝COPY化を再導入）で復元した
       （コミット、T262と同一トランザクション内でマージ）。クラッシュの真因は
       引き続きT261側で調査中（Renderのリソース制約が最有力）。
  1a. **材料読み込み（冷パス、split不要な場合の読み出し）の最適化**（2026-08-24調査・
     部分実装完了）: 本番実測で新規発見（上記）。「材料5クエリ×タイル数」（T229）の
     クエリ本数そのものを削減する方向で着手し、案A・案Bの2つを実装・本番実測したが、
     **案Bは本番実測で効果が確認できず revert し、案Aのみ採用した**。
     - **案A（`is_tile_cached`のバッチ化、採用・実装済み）**: タイル数ぶん個別に発行していた
       `is_tile_cached`ループを、`RoadGraphRepository.get_cached_tiles`（新設、
       `(zoom,x,y) IN (...)`の1クエリ）へ集約。`GraphService._ensure_tiles_cached`として
       `get_or_build_graph_with_attributes`・`get_search_materials_for_bbox`両方の入口で
       共有。**冷パス・温パスの両方**で毎リクエスト効く（温パスは新宿10kmで7クエリ→
       2クエリ）。副作用が無い機械的な改善のため、効果の大小によらず採用。
     - **案B（未キャッシュタイルの材料バッチ取得、試験実装したがrevert済み）**:
       `_build_search_materials_from_tile_cache`を、未キャッシュな複数タイルぶんを個別に
       問い合わせるループから、対象タイル群の外接矩形へ1回のクエリセット（計6クエリ）へ
       集約し、結果をタイルごとへ分割してキャッシュへ格納する方式を実装した
       （新宿10km・z12タイル6枚で49クエリ→25クエリへ削減）。テスト（単体・PostGIS統合・
       backend全体1085件green）は全通過し実装自体にバグは無かった。
       - **本番実測で判明した結論（2026-08-24、本番Oracle Cloud PostGISで新旧方式を
         同一セッション内で公平に比較。DBキャッシュ状態の揺れによる誤差を排除するため
         各方式2回ずつ計測）**: 新宿10km（旧43.63秒→新41.91秒、4%改善）・王子15km
         （旧38.27秒→新42.18秒、**10%悪化**）と、有意な改善は確認できなかった。
         1クエリあたりの実測コスト（旧: 約1.8秒/クエリ、新: 約1.7秒/クエリ）がほぼ
         変わらないことから、律速していたのは「ラウンドトリップの往復回数（レイテンシ）」
         ではなく「1クエリあたりの実行・転送コスト（数万〜十数万行という大きな結果セットの
         DB側処理・シリアライズ・クライアント側デシリアライズ）」だったと判明した。
         この結論はdev-local実測（新方式71.56秒≈旧方式68.80秒、ほぼ同等）とも整合する。
       - **判断・対応**: 「クエリ本数を減らす」という対策の方向性自体が、真のボトルネックに
         対して的外れだったため、投じた実装コスト（境界Edge多重登録・タイル分割ロジックの
         複雑性）に見合う効果が無いと判断し、案Bの実装は2026-08-24中に全てrevertした
         （`_bbox_covering_tiles`・`_partition_search_materials_by_tile`・
         `_fetch_and_cache_missing_tile_materials`・関連テストを削除、
         `_build_search_materials_from_tile_cache`・`_get_or_build_tile_materials`を
         タイル毎ループの元実装へ戻した。`domain/region.py`の`lonlat_to_tile_index`公開化も
         用途が無くなったため`_lonlat_to_tile_index`へ戻した）。
       - **教訓（次に類似の最適化を検討する際に活かす）**: ラウンドトリップ削減が効くのは
         「小さな結果セットを多数の往復で取りに行っている」場合に限られる。今回のように
         1回の結果セット自体が既に大きい（数万〜十数万行）場合は、往復回数を減らしても
         DB側の処理・転送コストは変わらないため効果が出ない。真のボトルネックが
         「往復回数」か「転送データ量」かを、本番実測（可能ならEXPLAIN ANALYZEやDB側の
         実行時間内訳）で先に切り分けてから着手すべきだった。データ量が真因であれば、
         対策の方向性はクエリ集約ではなく「そもそも読み込むデータ量を減らす」
         （タイル粒度の見直し・必要なEdgeへの絞り込み等）や、T248候補2の「冷パスを
         リクエスト同期から切り離す」方向にすべきである。
     - 対応方針としてgeo形式キャッシュ（DBと同じ`ST_Intersects`をサーバー側JOIN条件として
       使い、geometry自体はSELECTしない設計）も検討したが、真因が転送データ量である以上
       効果は薄いと判断し実装は見送った。
  1b. **材料5クエリの1クエリへの統合**（2026-08-24実装完了）: 案Bのrevert後、ユーザーから
     「転送量自体がネックならそれを減らす方針、アーキテクチャを考えられないか」という
     提起を受け、真因を再検討した。dev DBでプロファイリングした結果、律速は往復回数でも
     転送データ量そのものでもなく、**同じEdge集合に対しSQLAlchemy ORMの行オブジェクト
     構築を5回（surface/edge_attribute_counts/way_tags/elevation_attributes/
     designated_edge_ids）繰り返していたPython側のオーバーヘッド**と判明した
     （71,791 Edgeで現行5クエリ8.33秒 → 統合1クエリ[SQLAlchemy Core]1.30秒[6.4倍] →
     統合1クエリ[生asyncpg]0.83秒[10倍]）。
     - **実装**: `domain/attributes.py`に`EdgeMaterialsBatch`（`SearchMaterials`から
       `graph`を除いた5材料のみの型）を新設。`AttributeRepository.get_edge_materials_batch`
       （`road_graph_repository.py`）で、road_edges LEFT JOIN osm_raw_ways/
       edge_attribute_counts/elevation_attributes＋designation_attributesへの
       相関EXISTS副問い合わせを1クエリへ統合。生asyncpg（10倍）ではなくSQLAlchemy Core
       （6.4倍）を採用——効果の大部分をより低リスク（既存セッション・型を維持）に得られる
       ため。各材料の「該当行なし」の意味（surface/way_tagsはLEFT JOINでNone/{}を明示的に
       持つ・edge_attribute_counts/elevation_attributesはNOT NULL列で行の有無を判定し
       key自体を省略・designated_edge_idsはEXISTSの真偽）は元の5メソッドと完全に同じ
       意味を保つよう設計・テストした。`graph_service.py`の`_build_search_materials_uncached`・
       `_get_or_build_tile_materials`の両方をこの1メソッド呼び出しへ差し替え。
     - **テスト**: `test_road_graph_repository.py`に、実在するfwd/bwd2本のEdgeの一方だけへ
       edge_attribute_counts・elevation_attributesを投入し「該当行なしのkey省略」を
       検証する統合テストを追加。`test_graph_service.py`のFakeリポジトリにも
       `get_edge_materials_batch`を追加し、既存の呼び出し回数アサーションを更新。
       backend全体1084件green。dev DBでのE2E確認（新宿10km候補8/8・王子15km候補6/8）で
       機能面の回帰も無いことを確認。
     - **残課題（2026-08-24追記で対応済み、下記1c参照）**: この最適化は5つの「材料」
       クエリのみが対象で、`get_graph_topology_in_bbox`（Edge/Node本体のトポロジ取得、
       深掘りプロファイリングで新宿10km実測33秒）は当初未着手のまま残っていた。
  1c. **`get_graph_topology_in_bbox`のNode取得をST_X/ST_Y列指定へ変更**（2026-08-24実装
     完了）: 1a・1bの流れを受け、残っていた最大の未着手コストを調査した。Node取得が
     `select(RoadNodeRow)`（geom列込みのORM行）＋`shapely.from_wkb`によるgeometry decode
     をしていたが、探索フェーズが必要とするのは緯度経度のみ（Edge側は既にT218で
     `_topology_rows_to_road_graph`向けにgeom列を除いた列指定クエリへ最適化済みだった、
     Node側だけが未対応のまま残っていた）。dev DB実測（68,760件、6タイル拡張bbox・
     T229深掘り計測と同規模）でORM全体取得+shapely decode 2.76秒 → PostGIS側で
     `ST_X(geom)`/`ST_Y(geom)`を計算させプレーンなfloatとして受け取る方式0.89秒
     （**3.1倍**）を確認して実装した。
     - **実装**: `road_graph_repository.py`の`get_graph_topology_in_bbox`のnode_stmtを
       `select(RoadNodeRow)`から`select(RoadNodeRow.node_id, RoadNodeRow.osm_node_id,
       func.ST_X(RoadNodeRow.geom), func.ST_Y(RoadNodeRow.geom))`へ変更。
       `_topology_rows_to_road_graph`も同様に`shapely.from_wkb`呼び出しを削除し、
       行から緯度経度を直接読むだけにした。
     - **注意（深掘りで判明した誤差の原因）**: 当初「33秒の内訳」を特定しようとしたが、
       edge_query単体2.49秒・node取得（旧実装）2.76秒で合計5.25秒にしかならず、
       元の33秒との差が大きいことが判明した。33秒の計測はセッション序盤（DBキャッシュが
       冷えた状態）に対し、今回の内訳計測は同じ範囲への大量の反復アクセス後（DB
       キャッシュが温まった状態）だったための差と考えられる（T229で確認した同種の
       現象）。したがって「edgeクエリ・node取得のどちらが33秒の主因か」は未確定のまま
       だが、**node取得側の3.1倍という相対的な改善効果自体は2回の独立した計測
       （29,017件規模で3.2倍・68,760件規模で3.1倍）で再現しており、方式自体の有効性は
       確度高く確認できている**。`_topology_rows_to_road_graph`内のPydantic
       `model_construct`呼び出し（Edge+Node合計24万件規模）のコストは今回切り分けて
       おらず、次に着手する場合の候補として残る。
     - **テスト**: `get_graph_topology_in_bbox`にはPostGIS統合テストが1件も無かったため
       新規に3件追加（未保存時None・`get_graph_in_bbox`との座標一致回帰・bbox外Edge除外）。
       backend全体1087件green。dev DBでのE2E確認（新宿10km候補8/8・渋谷10km候補6/8・
       王子15km候補4/6）で機能面の回帰なし（新宿の初回計測で237秒という外れ値が出たが、
       直前の重いpytest実行によるDB側の一時的な負荷が原因と考えられ、再実行では10.2秒
       まで復帰したため再現性の問題ではないと判断した）。
  1d. **探索専用lean型をPydanticから完全に分離**（2026-08-24実装完了）: 1cで残課題として
     記録した`model_construct`のコスト（プロファイリングで新宿10km・171,461Edge規模の
     `DirectedEdge.model_construct`だけで8.938秒、`Node.model_construct`2.125秒、DB
     クエリ本体3.4秒より支配的）を受け、ユーザーから「lean型とフル型を完全に分ける」
     方向での実装指示を受けて着手した。
     - **設計**: `domain/graph.py`に`LeanNode`/`LeanEdge`/`LeanRoadGraph`
       （`@dataclass(frozen=True, slots=True)`、Pydanticのバリデーション・内部簿記を
       持たない）を新設。既存の`Node`/`DirectedEdge`/`RoadGraph`（Pydantic、表示・保存用）
       とフィールド構成を完全に一致させ、`NodeLike`/`EdgeLike`/`RoadGraphLike`
       （`typing.Protocol`、`@runtime_checkable`）で両者が満たす構造的型を定義した。
       `RoadGraphEngine.trace_loop`が`hydrated.get(edge_id) or context.graph.edges[edge_id]`
       でlean型（探索グラフ由来）とフル型（表示用に取り直したEdge）を同じリストへ
       混在させる境界があり、フィールド完全一致の設計がこれを事故なく成立させる
       （調査で特定した最大のリスク要因）。
     - **実装範囲**: `_topology_rows_to_road_graph`（road_graph_repository.py）が
       `LeanRoadGraph`を返すよう変更。`domain/routing.py`（`build_sparse_graph`・
       `build_networkx_graph`・`find_nearest_node`・`build_node_spatial_index`・
       `NodeSpatialIndex`）、`domain/evaluation.py`（`is_edge_allowed`・
       `compute_wind_penalty`・`compute_edge_axis_scores`・`compute_edge_cost`・
       `compute_edge_costs_bulk`）、`services/evaluation_service.py`
       （`EvaluationService.evaluate_graph`）、`services/elevation_attribute_service.py`
       （`get_attributes_for_graph`）、`services/road_graph_engine.py`
       （`_SearchGraph`/`_RoadGraphContext`の`graph`フィールド、`_build_segment_details`
       等のEdge集約関数群）、`domain/attributes.py`（`SearchMaterials.graph`）の型注釈を
       `RoadGraph`/`DirectedEdge`から`RoadGraphLike`/`EdgeLike`へ変更（実行時の分岐は
       元々duck typingで動いていたコードのため、型注釈の変更のみで済んだ箇所が大半）。
     - **実装中に見つけた実際のバグ**: `RoadGraphEngine._build_candidate`が
       `path_graph = RoadGraph(graph_version=..., nodes=context.graph.nodes, edges=...)`
       と、Pydantic `RoadGraph`へ`context.graph.nodes`（今回`LeanNode`の辞書になる）を
       直接渡しており、Pydanticのフィールド型検証（`dict[str, Node]`）に失敗して
       実行時エラーになる箇所を発見した。調査の結果`get_attributes_for_graph`は
       `graph.edges`しか参照せず`nodes`は完全に未使用と判明したため、`nodes={}`へ変更した
       上で、`RoadGraph`ではなくバリデーションを行わない`LeanRoadGraph`で`path_graph`を
       構築するよう修正（`edges_in_path`が稀にlean/フル混在になりうる`trace_loop`の
       フォールバック分岐に対しても安全）。副次効果として、候補ごとに数万件規模の
       `context.graph.nodes`をコピーしていた無駄も無くなった。
     - **`GraphService`側の型整合**: `get_or_build_graph_with_attributes`の戻り値、
       `_build_search_materials_from_tile_cache`・`_get_or_build_tile_materials`の
       空グラフ・結合グラフ構築を、`lean`引数や呼び出し経路に応じて`LeanRoadGraph`/
       `RoadGraph`を作り分けるよう修正（`get_or_build_graph_with_attributes`は
       `is_split_up_to_date=True`かつ`lean=True`の高速パスのみ`LeanRoadGraph`を返し、
       closure再構築を伴う低頻度の重い経路は`lean`に関わらず常に`RoadGraph`のまま）。
     - **テスト**: `test_graph.py`に`LeanNode`/`LeanEdge`/`LeanRoadGraph`が対応する
       Protocolを満たすこと・frozenであることの単体テストを追加。
       `test_road_graph_repository.py`の座標一致回帰テストに、戻り値の実体型が
       `LeanRoadGraph`/`LeanNode`/`LeanEdge`であることの検証を追加。backend全体
       1089件green。
     - **実測（dev DB、新宿10km・171,461Edge・68,760Node、6タイル拡張bbox規模）**:
       `get_graph_topology_in_bbox`全体（DBクエリ＋オブジェクト構築を含む）が
       4.2〜4.6秒（3回計測の範囲）。1cまでの実測（edge_query 2.49秒＋node取得
       [ST_X/ST_Y] 0.89秒 ≈ 3.4秒のDB部分のみ）と合わせて、Pydantic
       `model_construct`のオーバーヘッド（旧実装で推定11秒）がほぼ解消されたことを
       裏付ける。dev DBでのE2E確認（新宿10km候補8/8・渋谷10km候補6/8・王子15km候補4/6、
       いずれもエラー無し）で機能面の回帰も無いことを確認。
  2. **冷パスの体験設計**: 初回タッチの重い処理（split再構築）をリクエスト同期から
     切り離す選択肢（バックグラウンドウォームアップ・主要エリアの事前split・
     プログレス表示等）。T59の`_maybe_trigger_graph_build`（タイル閲覧起点の
     バックグラウンド構築）という既存機構との統合可能性を含めて検討する。
     - **調査（2026-08-24）**: `_maybe_trigger_graph_build`（region_service.py）は
       **地図タイル閲覧専用**で、ルート生成側（`RoadGraphEngine.prepare`）からは
       一切呼ばれておらず、そのままでは転用できないと判明。コールドパスは
       (a)未split→`save_graph`再構築が重い（バックグラウンド化で対応可能）と
       (b)split済みでも材料読み出し自体が重い（T229で判明、データ量律速のため
       バックグラウンド化だけでは解決しない）の2種があり、対策を分けて設計する
       必要がある。また、ルート生成経由の`save_graph`は`graph_build_max_concurrent`
       （タイル閲覧経由の構築が使う同時実行ガード）の対象外で、同じ処理が呼び出し
       経路によって異なる同時実行制御を受けている非対称性も確認した。
       本体（バックグラウンドウォームアップ・事前split等の実装）は規模が大きいため
       未着手のまま次回以降に持ち越す。
     - **独立したバグとして先に修正（2026-08-24完了）**: 調査中に、フロントエンドの
       `/api/routes/generate`タイムアウト（90秒、`frontend/src/services/routeApi.ts`）が
       バックエンドのDBコマンドタイムアウト（180秒、`ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS`、
       `database.py`）より短く設定されていることが判明した。王子30kmの本番実測
       （T246、total_ms=315,859≒316秒）のような重いケースでは、バックエンドが処理を
       継続しているにもかかわらずフロントエンドが先にタイムアウトしてユーザーには
       失敗と表示される、というズレが起きうる。冷パス体験設計そのものとは独立した
       既存バグのため先に修正した：フロントエンドのタイムアウトを本番実測の最悪値
       （316秒）を安全マージン込みで上回る360秒へ延長。`frontend/src/services/routeApi.test.ts`
       含めテスト影響なし（5件green）。
  3. 温パスの残り（evaluate_graph約2.6秒＋グラフ構築約1.0秒）はT238/T240で
     最適化済みのため、これ以上の短縮はT12 Part 2（キャッシュ永続化等）の領域。
- 完了条件（着手時に確定）: 温パス5秒以内（T224目標の達成）＋冷パスの体験方針の決定・
  実装。実測値をもって記録する。
- **切り出し**: 本番実測中に発見した「都心部（新宿・渋谷）で候補0件」は性能問題ではなく
  接続性の問題のため、本タスクのスコープ外としてT256へ切り出した。
- **T263（Oracle VM移行）・T264（closure_ms削減）後の再検証（2026-08-24、本番backend
  `https://193-123-166-150.sslip.io`へ直接curlで実施、書き込みを伴う）**: T259で確定した
  「未split・20km規模地点がRenderの約100秒プラットフォームタイムアウトで完全失敗する」
  事象が、移行後も再現するか確認した。
  - **ユーザー実座標（T259再現座標、20km、既にsplit済み）**: `http_code=200・
    time_total=44.1秒`で成功。
  - **前橋（今回初アクセスの未split地点、20km）**: 冷パス`http_code=200・
    time_total=27.6秒`で成功、候補あり。直後の温パス再実行は`time_total=13.3秒`
    （T224目標の温5秒以内には未達、1aで判明した「split済みでも材料読み出しが重い」
    残課題がなお効いている可能性）。
  - **秩父（今回初アクセスの未split地点、30km）**: `http_code=200・time_total=8.4秒`
    （山間部のため候補0件だが失敗ではない）。
  - いずれも`/api/debug/stats`の`started_at`（プロセス起動時刻）はリクエスト前後で
    不変＝クラッシュ・再起動なし。CORSヘッダー（`access-control-allow-origin`）も
    正しく返っており、T259で見られた「CORS違反に見える誤診断」（Renderのエッジ層が
    素の502を生成しCORSヘッダーが付かない現象）自体がOracle VM移行で構造的に
    再発しなくなっている（RenderのHTTPプロキシ層を経由しないため）。
  - **結論**: T259で確定した「完全な失敗」は解消された。20km級の冷パスは30〜45秒
    程度に収まり、フロントのアプリレベルタイムアウト（360秒）に対し十分な余裕がある。
    ただし「対応候補2（冷パスの体験設計）」「温パス5秒以内（完了条件）」は未達のまま
    残っており、これは失敗回避ではなく体感速度の課題として引き続き本タスクのスコープ内。
  1e. **タイル材料キャッシュの書き込み漏れを修正（2026-08-24実装完了）**: 上記の再検証で
     温パス5秒以内が未達（13.3秒）だった原因を深掘りしたところ、真の温パス（同一bboxへ
     3回目のアクセス）は`http_code=200・time_total=4.9秒`でT224目標を達成済みと判明した。
     つまり13.3秒は「温パス」ではなく「split直後の2回目アクセスがまだキャッシュ未着火の
     まま材料をDBから読み直している」状態を計測していただけだった。
     - **原因**: `_build_search_materials_uncached`（split・再構築を伴う経路）は、
       構築した材料を`graph_material_cache`（プロセス内タイル単位キャッシュ）へ書き込まず
       返していた。旧docstringには「この経路自体が低頻度・重い処理のため、タイルキャッシュの
       対象外のまま。ロジックを二重に持たない」という意図的な設計判断が明記されていたが、
       これにより「split直後の次のリクエスト」が毎回この無駄なDB再読み出しを踏む
       ユーザー体感上のギャップが生じていた。
     - **見送った案**: `_build_search_materials_uncached`が既にメモリ上に持つ
       グラフ・材料（リクエストbboxの範囲のみ）をそのままタイル単位キャッシュへ書き込む
       案は、bboxがタイル境界と一致しないため不完全なデータをタイルキーで永続化しうる
       （タイルの一部だけがbboxに含まれる場合、キャッシュされた材料がタイル全体を
       カバーせず、次回同じタイルを使う別リクエストが一部のEdgeを見落とす）ため見送った
       （T248候補1a「案B」がタイル分割ロジックの複雑性を指摘していたのと同じ理由）。
     - **採用した方式**: レスポンスを返した後、バックグラウンドで対象タイルを正規の
       経路（`_get_or_build_tile_materials`、タイル全体をDBから取得する既存メソッドの
       再利用）で温める。タイル全体を読み直すため、部分データによる不整合リスクが無い。
       `region_service.py`の`_maybe_trigger_graph_build`/`_build_graph_for_tile_background`
       （T59、地図タイル閲覧起点のバックグラウンド道路グラフ構築）と同じ設計判断
       （新規セッション・fire-and-forget・in-flight重複防止セット・失敗時はログのみで
       元のレスポンスに影響させない）を、対象データ・キャッシュ先が異なるため
       `graph_service.py`側に独立して実装した（`_maybe_warm_tile_cache`/
       `_warm_tile_cache_background`/`_warming_tiles`）。
     - **isinstanceガード**: `region_service.py`の既存箇所と同じ理由で、
       `isinstance(self._repository, RoadGraphRepository)`が真の場合のみ発火させる
       （テストの`FakeRoadGraphRepository`はダックタイピングでこのクラスを継承しない
       ため、ユニットテストが実DBセッションを開こうとすることはない）。
     - **テスト**: `test_graph_service.py`に6件追加（`_maybe_warm_tile_cache`が
       タイルごとにバックグラウンドタスクを起動すること・キャッシュ済み/温め中の
       タイルをスキップすること・失敗時もin-flightマーカーを解除すること・
       isinstance判定で実リポジトリのときのみ発火し`FakeRoadGraphRepository`では
       発火しないこと）。isinstance判定用に`__getattribute__`で全属性を委譲する
       `_RealRepositoryStandIn`を新設（`RoadGraphRepository`自体が同名の実メソッドを
       持つため、region_service.pyの`_FakeRealRoadGraphRepository`と同じ単純な
       継承オーバーライドでは足りなかった）。backend全体1132件green（直列実行、
       pytest-xdist特有の既存フレーク[T248本文既述]を除く）。
     - **効果**: split直後の2回目アクセスも、1回目のレスポンス後まもなくバックグラウンド
       温めが完了していれば真の温パス（4.9秒）を得られるようになる（温め自体の所要時間
       ぶんの猶予が必要なため、1回目の直後すぐの2回目アクセスでは間に合わない場合が
       残る点に注意）。
- **完了条件の達成状況**: 温パス5秒以内はT224目標どおり達成済み（4.9秒実測）。
  「冷パスの体験方針」はユーザー判断により、バックグラウンドウォームアップ・事前split等の
  大掛かりな設計は実施せず将来課題として保留する方針とした（T265へ切り出し）。
  以上をもって本タスクは完了とする。

### - [ ] T265. 冷パスの体験設計（バックグラウンドウォームアップ・主要エリア事前split・進捗表示） 規模M〜L — トリガー: 一般公開の意思決定、または研究利用での冷パス体感遅延に関する具体的な要望・報告

- 発端: T248完了条件「冷パスの体験方針の決定・実装」のうち、方針決定のみ行い実装は
  見送った本体をこちらへ切り出し（2026-08-24、ユーザー指示「バックグラウンドウォーム
  アップ等の大掛かりな設計は将来的な改善要素として今は実施しない課題として再登録して
  ほしい」）。
- **現状（T248時点までの調査結果、詳細はT248候補2参照）**: 未splitな新規地点への
  初回アクセスは、T263（Oracle VM移行）・T264（closure_ms削減）・T248（バルクUPSERTの
  COPY化・材料クエリ統合等）を経て20km級で30〜45秒程度まで縮んでおり、以前のような
  「完全な失敗」（T259、Renderの約100秒プラットフォームタイムアウト）ではなくなった。
  フロントは「生成中...」のボタン無効化のみで、進捗・見込み時間の表示は無い
  （[RouteForm.tsx](frontend/src/components/RouteForm/RouteForm.tsx)）。
- 保留すると何がブロックされるか: 30〜45秒（今後データ量増加でさらに伸びうる）の
  無反応な待ち時間中、ユーザーには「フリーズしているのでは」という不安が残る。また、
  未splitエリアへの初回アクセスが多数同時に発生した場合（例: 新機能公開直後のアクセス
  集中）、`graph_build_max_concurrent`のガード自体はあるが、待たされるユーザー体験の
  改善（進捗表示・事前warmup）は未着手のまま。一般公開判断が先送りされている間は
  実害が顕在化しにくいため、優先度は低いまま維持してよいという判断（ユーザー承認）。
- 検討対象（T248候補2の調査結果を引き継ぐ）:
  1. **バックグラウンドウォームアップ**: T59の`_maybe_trigger_graph_build`
     （地図タイル閲覧起点）はルート生成側から一切呼ばれておらず転用不可と判明済み。
     ルート生成専用の非同期ジョブ化（リクエストを即座に受理し、ポーリング/WebSocket等で
     完了を通知する設計）が必要。
  2. **主要エリアの事前split**: 関東本土の主要都市・観光地を対象に、デプロイ後や
     定期バッチで先回りしてsplitしておく方式。対象エリアの選定基準（アクセスログ由来か
     固定リストか）が未検討。
  3. **進捗表示**: 上記1・2をやらない場合の最小対応として、フロントに「初回アクセス
     地点は時間がかかる場合があります」等の待機中メッセージ・経過時間表示を追加する
     軽量な選択肢（規模S相当、本タスクとは別に着手も可能）。
  4. コールドパスには(a)未split→`save_graph`再構築が重いケースと(b)split済みでも
     材料読み出し自体が重いケース（T248 1a〜1eで大きく改善、ただしT264が指摘した
     「split済みデータの転送量そのもの」の律速は根本解消していない）の2種があり、
     対策を分けて設計する必要がある（T248候補2調査時点の知見）。
- 完了条件: 未確定（着手時に対応候補を1つ以上選び、設計判断とともに確定する）。

### - [x] T256. 都心部（新宿・渋谷）でルート生成が候補0件になる事象の原因調査＋修正 規模S〜M（2026-08-24完了）

- 発端: T248の本番実測（2026-08-23、専用worktreeでDATABASE_URLを本番Oracle Cloud
  PostGISへ向けた直接サンプリング）で偶発的に発見。
- 事象: 新宿駅(35.6896,139.7006)・渋谷駅(35.6580,139.7016)を起点にdistance_km=10〜20
  （半径≈3.3〜6.7km）で`/api/routes/generate`を実行すると、8方位すべてでtrace失敗し
  候補0件になる。60〜152秒（新規split時）ないし66〜92秒（split済みデータの読み込みのみ）
  待たされた末の結果であるため、単なる低速ではなく「時間をかけても使えない」という
  T248より深刻な体験。DEBUG_MODE有効時の詳細ログでは全方位が
  `RoutingError("no path found between waypoints")`で失敗しており、waypointの
  最近接ノードへのスナップ自体は成功している（＝スナップ失敗ではなく、
  scipy.sparse.csgraph Dijkstraでの経路探索が起点↔経由地間で経路を見つけられていない）。
  半径を10km→20kmに拡大しても再現するため、単純な半径不足ではなさそうである。
- 対照実験: 同じ本番実測で王子15km（候補7件・8/8成功）・前橋10km（候補8件・8/8成功）・
  銚子25km（候補2件・6/8成功、沿岸のため2方位失敗は妥当）はいずれも正常に候補を返しており、
  密集した都心部（山手線内側相当）特有の事象である可能性が高い。一方通行の多さ等、
  役場道路網のトポロジ的特性が疑われるが未検証。
- 影響範囲（保留・未着手のまま次に何が起きうるか）: これまでの性能実測はほぼ王子を
  起点に行われており（T236・T242〜T247）、王子は正常系のため本事象はT247での
  road_graph既定化以降も検出されずに残っていた。研究利用者が実際に試す可能性が高い
  都心部（新宿・渋谷等の主要駅）で発生するため、影響を受ける利用者の割合は郊外での
  発生より大きいと想定される。原因未特定のまま放置すると、T248（性能改善）に着手して
  冷パスを高速化しても、都心部では「速く0件が返る」だけで体験は改善しない。
- 完了条件（調査フェーズ）: 原因を切り分け、以下のいずれかに分類する。
  1. road_graphエンジンの経路探索ロジックの不具合（one-way処理・グラフ構築の
     連結性等）→ 修正タスクとして規模を見積もり直す。
  2. 本番DBのデータ品質固有の問題（特定エリアのOSMデータ・split処理の副作用等）→
     dev DBでも再現するか確認し、再現すればロジック側、しなければデータ側の問題として
     切り分ける。
  3. 既知の事象（T241「8方位中平均1〜2方位が見つからない」）の延長で説明できる限定的な
     ものと判明した場合は、その旨を記録し見送り判定とする（ただし今回は8/8全滅のため
     T241とは事象の severity が異なる点に留意）。
- 参考: T241（道路グラフの連結性、規模不明、8方位中平均1〜2方位の失敗は残存するが実運用
  影響は限定的と評価済み）。
- **原因特定（2026-08-23、専用worktreeでdev DBに対し直接調査）**: 上記完了条件の
  分類1（road_graphエンジンのロジック不具合）と判明。dev DB（東京都心南部データ）でも
  同じ条件で全方位失敗を再現し、本番DB固有の問題ではないことをまず確認した。
  次にdev DBへ直接SQLで最近傍`road_nodes`とその接続`road_edges`のhighwayタグを
  問い合わせたところ、新宿駅最近傍ノード（76m）・渋谷駅最近傍ノード（33m）はいずれも
  **接続edgeが全て`highway=trunk`（甲州街道・明治通り等の国道）のみ**という構造だった。
  一方、王子駅・前橋駅の最近傍ノードは`unclassified`で正常。
  - **根本原因**: `find_nearest_node_indexed`（`domain/routing.py`、`prepare`の
    origin_nodeスナップ・`trace_loop`の経由地スナップ両方で使用）は
    `build_node_spatial_index`が保持する**フィルタ前の生グラフ**（`search.graph`、
    Hard Constraint適用前）から純粋に地理的最近傍のNodeを選ぶ。一方
    `build_sparse_graph`（探索本体が使う`sparse_graph`）は`is_edge_allowed`の
    Hard Constraint（既定`DEFAULT_HARD_FILTERS={"no_bicycle","motorway","trunk"}`、
    `evaluation.py:63`）で`trunk`Edgeを除外する。主要駅が国道の幹線交差点に直接
    面していると、最近傍Nodeの接続Edgeが全てtrunkで除外され、探索用グラフ上では
    孤立点（次数0）になる。この状態でorigin_nodeからDijkstraを実行すると
    到達可能なNodeが存在せず、半径や経由地の位置に関わらず8方位すべてが
    `no path found`で失敗する（実際には50〜100m先に自転車で通行可能な道路網が
    広がっているにもかかわらず）。
  - 影響範囲の裏付け: 新宿・渋谷はいずれも駅前が国道の幹線交差点に面する典型例で、
    同種の主要駅（他にも新橋・池袋等、国道と直接面する駅は都心に多い）で同様の事象が
    起きうる。
  - 対応方針（次に着手する場合の規模見積もり、実装は未着手）: `find_nearest_node_indexed`
    （またはその呼び出し元の`prepare`/`trace_loop`/`preview_segment`）で、Hard
    Constraint適用後も次数1以上を保つNodeのみを候補にする。具体的には
    (a) 索引を`search.graph`ではなく`sparse_graph`側のNode集合から構築する、または
    (b) 最近傍探索が孤立Nodeに当たった場合はグリッドリング探索を継続し次善のNodeへ
    フォールバックする、のいずれか。影響箇所は`road_graph_engine.py`の
    `prepare`・`preview_segment`（node_index構築）と`domain/routing.py`
    （`build_node_spatial_index`/`find_nearest_node_indexed`）。規模S〜M（ロジック変更は
    限定的だが、origin・waypoint両方のスナップ経路・関連テストの追従が必要）。
- **実装（2026-08-24完了）**: 対応方針(a)を採用。
  1. `domain/routing.py`に`routable_node_ids(sparse_graph)`を新設。`sparse_graph.matrix`
     の非ゼロ行・列（＝Hard Constraint通過後も最低1本Edgeを持つNode）の和集合をNode ID
     集合として返す。
  2. `build_node_spatial_index`へ`node_ids`引数（省略時None=従来どおり`graph.nodes`
     全件、互換維持）を追加し、索引の構築対象を絞れるようにした。
  3. `road_graph_engine.py`の`prepare`・`preview_segment`で、`node_index`構築時に
     `node_ids=routable_node_ids(search.sparse_graph)`を渡すよう変更（2箇所）。
     索引の候補が孤立Nodeを含まなくなるため、`find_nearest_node_indexed`は地理的最近傍
     ではなく「実際に経路探索可能な」最近傍Nodeを返すようになる。
  4. テスト追加: `test_routing.py`に`routable_node_ids`の単体テストと、
     `build_node_spatial_index`のnode_ids絞り込みが孤立Nodeをスキップし次善のNodeを返す
     ことを確認する回帰テスト。`test_road_graph_engine.py`に`prepare`が孤立Node（trunk
     のみに接続）を避けて隣接する経路探索可能なNodeへスナップすることを確認する
     エンドツーエンドの回帰テストを追加。既存の
     `test_prepare_excludes_edge_exceeding_max_average_grade_percent_from_search_graph`
     は起点自体が全Edge除外で孤立してしまう構成だったため、除外されない迂回Edgeを
     追加して起点が孤立しないよう調整（新設のnode_ids絞り込みによりprepareがNoneを
     返すようになったための追従）。
- 検証: backend全体1080件green。dev DB（東京都心南部データ、ネイティブPG）に対し
  修正後のコードで実際に`/api/routes/generate`を再実行し、新宿10km（修正前:
  候補0件/8方位全滅 → 修正後: **候補8件・8/8成功**、prepare_ms=35,188）・
  渋谷10km（修正前: 候補0件/8方位全滅 → 修正後: **候補6件・6/8成功**、
  prepare_ms=66,797、残り2方位は距離フィルタ等の別要因で妥当な範囲）を確認した。

### - [x] T249. 統合レビュー第7回の軽微指摘一括 規模S（2026-08-23完了）

- 発端: 統合レビュー第7回 統合-3（P3）。
- 対応内容:
  1. `config.py:88-92`の接続プール上限コメントがT243の2系統エンジン化に未追従
     （「ルート生成用の接続と合わせてもプール上限（15接続）に収まり」という単一プール
     前提の記述が残る。実態はタイル配信系15＋ルート生成系15の2プール）。
  2. `.env`未作成のDBなし環境で、T247以降は既定`road_graph`のため
     `/api/routes/generate`が常に失敗する（`.env.example`には注記済みだが、コピーせず
     起動した場合には効かない）。起動時（lifespan）にroad_graph既定でDB接続不可の場合の
     WARNING1行を追加する。
- 完了条件: コメント更新＋起動時WARNING実装、backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `config.py`のプール上限コメントを2系統プールの実態（タイル配信系15＋ルート生成系15、
     合計最大30接続で本番max_connections=100に余裕あり）へ更新。「Supabase側」という
     Oracle Cloud移行前の記述も「DB側」へ訂正。
  2. `main.py`の起動時スナップショットログの直後に、`routing_engine=road_graph`の場合の
     案内ログを追加。設計判断: (a) 起動時点ではイベントループ起動前のため実際のDB接続
     確認は行わず、設定の組み合わせのみで判定する（実際に接続不可かはリクエスト時の
     エラーで判明するため、ここはその読み解きの補助）、(b) DB接続ありの正常環境でも
     出るためレベルはWARNINGでなく**INFO**にした（正常構成で毎回WARNINGが出ると
     「WARNINGは常時異常のシグナル」というログ方針が薄まるため。docs/logging.mdの
     方針との整合を優先）、(c) DATABASE_URLは`@`以降（ホスト名部分）のみをログに出し
     認証情報を含めない。
- 検証: backend全体1077件green。起動ログの実出力（ホスト名のみ表示・案内文言）を
  実機確認済み。

## モバイル画面のスペース有効活用（2026-08-23・ユーザー指示）

### - [x] T250. スマホ上部バーへ出発地点・距離・生成ボタンを集約＋下部タブ再定義 規模S〜M（2026-08-23完了）

- 発端: ユーザー実機フィードバック「ルートを作るUIがスマホだと使いにくい。作成した
  ルートを地図で見ながらポイントになるところを見る、という使い方をするのだが、
  スマホだと少ないスペースを有効活用できるようにしたい」。「まずは上部バーのUI工夫して」
  との指示のため、今回は上部バー改修のみを対象にする（下部タブ本体の構成見直し・
  RouteListの表示方法変更等は範囲外、必要になれば別タスクとして起票）。
- 対応内容（モバイルのみ。デスクトップのサイドバー「ルートを作る」ブロックは現状維持）:
  1. 出発地点（LocationControl）を、常設の天候ヘッダー直下に新設したモバイル専用の
     操作バーへ移動。表示は座標を省き出典ラベルのみの1行に圧縮し、詳細はtitle属性へ
     退避（`compact`プロパティを追加）。
  2. 距離入力・ルート生成ボタン（RouteForm）も同じ操作バーへ移動。ボタン文言は
     「ルート生成」→「生成」に短縮（`compact`プロパティを追加）。
  3. 生成ボタンがタブを開かずとも常時押せるようになったことで、生成失敗時のエラー
     メッセージが従来のように「ルートを作る」シート内に隠れたままだと見えなくなる
     （以前は生成ボタン自体がそのシートの中にあったため、シートを開かないと押せず、
     結果として押した時点でエラー表示も見えていた）。回帰を避けるため、エラー
     メッセージは新しい操作バー側にも表示する。
  4. 下部タブ「ルートを作る」を「ルート詳細」へ改名。出発地点・距離入力・生成ボタンが
     ヘッダーへ移ったことで、このタブの中身は生成結果（RouteList・比較パネル・
     ルートの色分け設定・条件dirtyヒント）のみになる。
- 完了条件: フロントエンドの型検査・既存テストgreen、LocationControl/RouteFormの
  `compact`分岐に対するテスト追加、Playwrightでモバイル幅の実機確認。

- **実装メモ（2026-08-23完了）**:
  - `tsc --noEmit`・ESLint・vitest（LocationControl/RouteForm、compact分岐のテスト追加分含む）
    すべてgreen。
  - Playwright（一時spec、検証後削除）でモバイル幅(390x844)実機確認: ヘッダー直下の
    操作バーに出発地点・距離入力・生成ボタンが1行で収まること、生成→「ルート詳細」タブが
    地図を覆わない部分シートとして開き候補一覧が見えることを確認。デスクトップ幅でも
    別specでサイドバー側（出発地点・距離・「ルート生成」ボタン）が従来通り表示され、
    モバイル専用の操作バー・改名後のタブラベルが出ないことを確認（回帰なし）。
  - スコープ外として明記した下部タブ本体の構成見直し・RouteListの表示方法変更は
    今回未着手（次に着手する場合は新規タスクとして起票）。

### - [x] T251. 定番UIライブラリでの現行UI同等再現可否・規模の調査 規模M（2026-08-23調査完了、実装は未着手）

- 発端: T250対応中にユーザーが表明した方針（「新規UI機構は自前実装より定番ライブラリを
  優先検討」、進め方の原則へ追記済み）を受け、「今後もデザイン変更・調整を続けるので、
  早い段階で定番ライブラリ・汎用的な拡張機構を用意しておきたい」との指示。新規追加時に
  限らず、**現時点のUIを定番ライブラリ（Radix UI Primitives、vaul等）で同等再現できるか、
  それにどれだけの規模がかかるかを先行調査する**（実装はしない、調査のみ）。
- 完了条件: frontend/src/components配下の汎用UI機構（タブ・折りたたみ・ボトムシート・
  スライダー・トグル/ラジオグループ・モーダル/ポップオーバー等）を棚卸しし、component単位で
  候補ライブラリ・実現性・移行規模（S/M/L）を判定した表を作成。特にBottomSheet
  （地図のピンチズームと衝突しないtouch-action調整・暗幕なし表示という実機チューニング
  済みの独自要件を持つ）は個別にリスクを検討する。Tailwind導入の要否（Radix系ライブラリの
  多くはheadlessでCSS Modulesとも併用可能なため、必須ではない）も論点として明記する。

- **調査メモ（2026-08-23完了、Tailwind検証・ユーザー指摘による訂正を反映）**:
  frontend/src/components配下26コンポーネントを棚卸し（調査レポートはArtifactとして
  作成、ユーザーへ共有済み）。
  - **適合（規模S、機械的に置換可）**: トグルチップ（LayerChip等）→Radix Toggle、
    ラジオ/セグメント選択（ルート色分けモード・LevelPicker）→Radix RadioGroup/ToggleGroup、
    情報開閉ボタン（FieldLabelのinfoButton）→Radix Popover、アコーディオン
    （サイドバー4ブロック・MapLayersPanel・WeightPanel等の`<details>`）→Radix Accordion
    （ただし現状で機能不満はなく優先度低）、汎用アイコンのみ→lucide-react等（大半は
    ドメイン固有で流用不可、効果限定的）、**FloatingPanel（DebugConsole/SystemStatusPanel
    の共通シェル）→react-rnd**（`dragHandleClassName`で現行のハンドル限定ドラッグを再現可、
    `bounds="window"`で画面外へ出ないようクランプする現行に無い改善も可能）。
  - **要検証（規模M〜L）**: BottomSheet→vaul(Drawer)。ドラッグ高さ変更・暗幕なし・
    地図のピンチズームと衝突しないtouch-action調整という3つの独自要件はいずれもvaul単体
    では自動的にカバーされず、個別の実機再検証が要る。**DynamicLayerTimeSlider→Embla
    Carousel**（可変幅スライド・公式wheel-gesturesプラグイン・`align:"start"`スナップは
    いずれも標準機能でカバーできることを確認したが、キーボード操作(Arrow/Home/End)と
    `role="slider"`のARIA意味づけは今と同程度の自前配線が残る）。
  - **対象外**: RouteFormのバリデーション（数値1項目のみで導入コストに見合わない）、
    モバイル判定の二重管理（useIsMobile/globals.css、ライブラリで解決する種類の課題ではない）。
  - **訂正の経緯**: 初回調査ではRadix UI Primitivesの守備範囲だけで判定し、
    DynamicLayerTimeSlider・FloatingPanelを「適合ライブラリなし・非推奨」と誤って結論して
    いた。ユーザーから「類似のコンポーネント実装は世の中にはないか」と指摘を受けRadixに
    限定せず調べ直し（WebSearchでEmbla Carousel公式ドキュメント・react-rnd npmページを
    確認）、上記へ訂正した。
  - **Tailwind導入も検証**: 「下部シートの余白調整のようなデザイン微調整を素早く試したい」
    という動機を受け、①フル移行（26コンポーネント全書き換え、非推奨・規模L）②新規コード
    のみ（導入は軽いが既存ファイルの不満は解決しない）③既存CSS Modulesと併用しJSX上で
    ユーティリティクラスを都度足す（推奨・規模S）の3方式を比較。globals.cssの
    `--space-1〜4`（0.25/0.5/0.75/1rem）がTailwind既定のスペーシングスケールと数値一致
    しており、CSS変数を書き換えずに橋渡しできることを確認。あわせてBottomSheetの
    ヘッダーが窮屈に見える原因を実装から特定: 閉じるボタンの`min-width/height: 44px`
    （タップ領域確保の設計判断）が支配的で、Tailwind導入そのものでは解決しない
    （現行CSSのままでも数行の調整で対応可能）。
  - **推奨順序**: Phase0（Tailwind併用導入、規模S）→Phase1（トグル/ラジオ/Popover/
    FloatingPanel→react-rnd、規模S〜M）→Phase2（アコーディオン、任意・規模S）→
    Phase3（BottomSheet→vaul・DynamicLayerTimeSlider→Embla、規模M〜L、実機検証込み）。
  - 次のアクション: T251の推奨順序（Phase0〜3）をPhaseごとの個別タスク
    （T252〜T255、下記）として起票した。

**T252〜T255は並行して進行中の別セッションの作業が完了してから着手する
（2026-08-23、ユーザー指示）。それまでは4件とも指示待ちで保留する。保留による
実害はない（他のタスク・本番挙動をブロックしない、UI機構自体は現行の自前実装のまま
問題なく動作し続ける）ため、トリガーは「別セッション完了後のユーザーからの着手指示」
のみとする。着手する場合はT252→T253→T254→T255の順（T251の推奨順序どおり、後続
Phaseほど前Phaseの成果を安全網として使える）。**

### - [x] T252. Phase0: Tailwindの併用導入 規模S（2026-08-23完了）

- 発端: T251の調査結果。「デザインの微調整を素早く試したい」という動機（下部シートの
  余白調整等）を受け、既存CSS Modulesは維持したままTailwindのユーティリティクラスを
  併用できるようにする（T251「③併用（推奨）」方式）。
- 対応内容: `tailwindcss`/`@tailwindcss/postcss`を追加し、globals.cssへ
  `@import "tailwindcss";`。既存の`--space-*`/`--color-*`をTailwindの`@theme`で
  トークンとして取り込めるか検証（`--space-1〜4`は既にTailwind既定のスペーシング
  スケールと数値一致していることをT251で確認済み）。既存CSS Modulesファイルは変更しない。
- 完了条件: ビルド成功、既存の全画面表示に差分が出ないことを確認、型検査/ESLint green。
  T253以降でTailwindユーティリティを使う具体例（例: BottomSheetヘッダーの余白調整）を
  1件試して動作確認する。

- **実装メモ（2026-08-23完了）**:
  1. **導入**: `tailwindcss`/`@tailwindcss/postcss`を追加、`postcss.config.mjs`新設、
     `globals.css`先頭へ`@import "tailwindcss";`。`--space-1〜4`はTailwind既定の
     スペーシングスケール（`--spacing: 0.25rem`単位）と数値一致するため@theme上書き
     不要と確認。`--color-*`はダークモードを`@media (prefers-color-scheme: dark)`内の
     再定義で切り替える実装のため、`@theme`（静的値へ固定される）へは取り込まず
     `var(--color-*)`を個別クラスで参照する運用とした（取り込むとダークモード追従が
     壊れるため）。
  2. **重大な発見（1件試す動作確認で発覚）**: 完了条件の「1件試す」検証
     （一時ページ+一時Playwright spec、検証後削除）で`p-2`等のpaddingユーティリティが
     `padding:0`のまま効かないことを発見。原因はCSS Cascade Layersの仕様
     （unlayeredなルールはレイヤー内のルールに詳細度・順序に関係なく常に勝つ）と、
     既存`globals.css`の`* { padding:0; margin:0 }`等の汎用リセットがunlayeredの
     ままだったことの組み合わせ。Tailwindの`.p-2`は`@layer utilities`内にあるため
     機械的に無効化されていた。これはT252の動機そのもの（下部シートの余白調整）を
     阻害する致命的な穴のため、Phase0のうちに修正: `globals.css`の汎用リセット
     （`*`/`html`/`body`/`a`/`button`/`input`の既定値）を`@layer base`へ包み、
     Tailwindが内部で宣言する`@layer theme,base,components,utilities;`の同名
     レイヤーへ合流させ、`utilities`が正しく優先されるようにした。一方MapLibre
     ポップアップの配色上書き（別のunlayeredな`maplibre-gl.css`に詳細度で勝つ設計）と、
     モバイルの44pxタップ領域確保ルール（アクセシビリティ要件を意図的にどのユーティリティ
     クラスにも負けないよう保つ安全網）はunlayeredのまま維持し、その理由をコメントで
     明記した。ユーザー指示により、globals.css以外の全CSS（.module.css全件・
     `:global()`ブロック）も棚卸しし、他に同種の危険な汎用unlayered指定が無いことを
     確認済み（MapLibre関連の`:global()`上書きのみで、いずれも同じ理由で意図的に
     unlayered）。
  3. **副次的に発覚した既存バグ（E2Eサーバーの本番不一致）**: 検証中、Playwrightの
     webServerログに`"next start" does not work with "output: standalone"
     configuration`という警告を発見。`next.config.ts`は`output: "standalone"`
     （本番Dockerfileが`node server.js`で起動する構成）だが、`playwright.config.ts`の
     webServerは`next start`（`npm run start`）を使っており、E2Eがローカル・CIとも
     本番と異なるサーバー実装をテストしていた（フルリポジトリがある環境では
     `next start`でも動作するため偶然気づかれていなかった、T252以前からの既存問題）。
     `frontend/scripts/prepare-standalone.mjs`を新設（Dockerfileの`COPY .next/static`・
     `COPY public`相当をNode標準`fs.cp`でクロスプラットフォームに再現）、
     `package.json`へ`start:standalone`スクリプトを追加、`playwright.config.ts`の
     webServerを`npm run build && npm run start:standalone`へ切替。修正後は警告が
     消え、本番と同じ`node .next/standalone/server.js`エントリポイントでE2Eが走る。
  4. **副次的に発覚した問題（ローカルE2Eのリソース競合）**: 検証中、Playwrightの
     既定worker数（CPU論理コア数ベース）のまま3並列実行すると、同一のwebServer
     プロセスへ複数のヘッドレスChromiumが同時に地図（MapLibre GL・WASM）を読み込みに
     行き、ページ遷移・`beforeEach`フックが軒並み30秒タイムアウトする事象を複数回
     実測（ユーザー報告「同じようにリソース競合でタイムアウトすることが多い」を受け
     切り分け）。`workers: process.env.CI ? undefined : 1`でローカル実行を明示的に
     直列化し、同条件で安定して全green化を確認。CIはGitHub Actions側のジョブ専有
     リソースを前提に対象外。あわせて`docs/testing.md`へパターン4として本項目
     （本番同等サーバー・workers=1）を追記。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`
    いずれもgreen。Playwright E2E（smoke.spec.ts、standalone起動・workers=1）2件green。
    一時ページ・一時specは検証後に削除済み。

### - [x] T253. Phase1: 点在する小部品の置換＋FloatingPanel→react-rnd 規模S〜M（2026-08-23完了）

- 発端: T251の調査結果。
- 対応内容: トグルチップ（LayerChip等）→Radix Toggle、ラジオ/セグメント選択
  （ルート色分けモード・LevelPicker）→Radix RadioGroup/ToggleGroup、情報開閉ボタン
  （FieldLabelのinfoButton）→Radix Popover、FloatingPanel（DebugConsole/
  SystemStatusPanelの共通シェル）→react-rnd（`dragHandleClassName`でハンドル限定
  ドラッグを再現、`bounds="window"`で画面外へ出ないようクランプ）。
- 完了条件: 各コンポーネントの既存vitestテストgreen（必要なら更新）、Playwrightで
  モバイル実機確認、型検査/ESLint green。

- **実装メモ（2026-08-23完了）**:
  1. **LayerChip→Radix Toggle**: `pressed`/`onClick`（生イベント）のみ渡し、
     `onPressedChange`は使わない設計にした。`<summary>`内で使う呼び出し側
     （RecipePanelSection）が`event.preventDefault()`で親detailsの開閉を止めることが
     あり、Radixの`composeEventHandlers`は`defaultPrevented`時に内部トグルハンドラを
     スキップする仕様のため、内部ロジックへ依存すると押下が反映されないケースが生まれる
     ことが分かった。押下状態は従来どおり呼び出し側が完全外部管理のまま、Radixは
     セマンティクス（aria-pressed/data-state）とキーボード操作の提供に留める。
  2. **LevelPicker→Radix RadioGroup**: `role="group"`+個別`aria-pressed`ボタンの
     自前実装（矢印キー移動なし）から、`role="radiogroup"`/`role="radio"`＋roving
     tabindex（矢印キー移動が標準で付く）へ。見た目（`data-filled`+`--level-color`の
     進捗バー表現）はCSS変更なしで維持。呼び出し側テスト4ファイル
     （recipeControls/RoadSuitabilityRecipePanel）の`role: "group"`→`"radiogroup"`、
     `role: "button"`→`"radio"`、`aria-pressed`→`aria-checked`を更新。
  3. **ルート色分けモード（page.tsx）→Radix RadioGroup**: 既に手書きで
     `role="radiogroup"`/`role="radio"`/`aria-checked`を実装していた箇所を置き換え、
     矢印キー移動を標準搭載化。
  4. **FieldLabelのinfoButton→Radix Popover**: 単純な置換に留まらず設計を見直した。
     従来は`open`/`onToggle`を呼び出し側が持ち、説明文（`infoTooltip`）を呼び出し側が
     DOM上の直後（`<p>`または`<tr colSpan>`、呼び出し側ごとに配置形が違った）へ
     個別に配置していた。Popoverはトリガー位置基準のフローティング表示のためDOM配置に
     依存せず、開閉状態もFieldLabel自身が持てるようになったため、`open`/`onToggle`を
     廃し`description`を渡すだけのAPIへ簡素化した。呼び出し側4箇所
     （ScalarInput/ThresholdAdjustmentRow/WeightInput/HighwayRow）から
     `useState`＋条件付きレンダリングの重複コードが消え、`WeightPanel.module.css`/
     `RoadSuitabilityRecipePanel.module.css`の重複していた`infoTooltip`系クラスも削除。
     `.infoTooltip`（recipeControls.module.css）はPortal描画に伴い地の文から
     カード状の見た目（背景・枠線・影、MapLibreポップアップと同トークン）へ変更、
     z-index:46（BottomSheet:45より前面、FloatingPanel:50より背面）。
     `recipeControls.test.tsx`のFieldLabelテストを新API（`description`渡し・
     Popover開閉）へ書き換え。
  5. **FloatingPanel→react-rnd**: 自前のpointerイベントによるposition state管理を
     `Rnd`（`dragHandleClassName`でヘッダーのつまみへドラッグ限定、
     `bounds="window"`で画面外クランプ、`enableResizing={false}`でリサイズ不可は
     維持）へ置換。幅（`widthRem`）は従来どおりCSS側の`min(widthRem, 100vw -
     2*space-3)`で応答的に決め、Rnd自体はx/y位置のみ管理する設計にした
     （Rndのsize経由の固定px化だとウィンドウ幅変更に追従しなくなるため）。
     Rndはx/y絶対px指定のみでCSSの`left:50%+transform:translateX(-50%)`のような
     相対中央寄せができないため、開いた直後に`useLayoutEffect`（ペイント前に同期実行）
     で実際の描画幅を測って中央寄せのx座標を計算し反映する設計にした。Rndの既定
     `style.position`は`"absolute"`（ページスクロールに追従）のため、元のCSS
     （`position:fixed`）と同じビューポート基準の浮遊挙動を保つよう`style`propで
     `"fixed"`に上書きした。
  - **実機確認（Playwright、一時spec・検証後削除）**: モバイル幅(390x844)で
     (a) SystemStatusPanel（FloatingPanel/react-rnd）をハンドルドラッグし、画面外まで
     引っ張ってもbounds="window"でクランプされ座標が0以上に収まること、実際に位置が
     変わることを確認。(b) 研究タブでWeightPanelのFieldLabel Popoverを開き、
     BottomSheetの`overflow-y:auto`にクリップされずポータル先の内容が画面内
     （x/y≥0）に収まること、RoadSuitabilityRecipePanelのLevelPicker（RadioGroup）を
     クリックしaria-checkedが正しく切り替わることを確認。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。

### - [x] T254. Phase2: アコーディオンをRadix Accordionへ 規模S（2026-08-23完了、事前見積もりを上回るM相当の作業になった）

- 発端: T251の調査結果。サイドバー4ブロック（page.tsx）・MapLayersPanel・WeightPanel等の
  `<details>`をRadix Accordionへ置き換える。現状で機能不満はなく優先度は低いため、
  アニメーション等の明確な要望が出るまで見送ってもよい。
- 完了条件: 既存の開閉挙動（デスクトップ「ルートを作る」ブロックの状態外部管理を含む）
  と同等以上、既存テストgreen。
- **着手判断（2026-08-23）**: 実装前の調査で規模Sの見積もりを上回る3つの技術的課題
  （button内buttonの無効なHTML・Radix Accordionの追加DOM階層によるCSS/テスト影響・
  ネイティブ`<details>.open`へのテスト依存26箇所超）が判明したため、着手前にユーザーへ
  規模超過を報告し方針を確認した（AskUserQuestion）。ユーザー判断「計画通り進める」を
  受けて実施。

- **実装メモ（2026-08-23完了）**:
  1. **共通部品`Disclosure`を新設**（`frontend/src/components/Disclosure/`）。9ファイル・
     15箇所超の`<details>/<summary>`をRadix Accordion（`type="single" collapsible`、
     常に1項目のみ＝各セクションが独立開閉する既存の`<details>`と同じ挙動）でラップする
     共通コンポーネント。`Accordion.Item`は`display:contents`で透過させ親CSSへの影響を
     最小化。
  2. **button内buttonの回避**: MapLayersPanel（LayerChip「表示」）・
     RecipePanelSection（LayerChip「上書き」）の2箇所は見出し内に別のインタラクティブ
     ボタンをネストしていた。Radix `Accordion.Trigger`は実体が`<button>`のため、
     そのままネストすると無効なHTMLになる。`trailing` propでTrigger外（見出し行のflex
     コンテナ内の兄弟）に配置する設計へ変更し、以前`<summary>`内クリックの既定動作
     （details開閉）との衝突回避に必要だった`preventDefault`/`stopPropagation`を
     両箇所から削除できた（構造的に開閉トリガーへ伝播しなくなったため不要に）。
  3. **h3のtextContent汚染バグを実機不要で発見・修正**: 当初`trailing`をAccordion.Header
     （h3）の中に置いたところ、h3のtextContentに見出しテキスト＋trailingの文言
     （「勾配表示」等）が混入し、テキスト完全一致で検証する既存テストが複数破壊された。
     `trailing`がある場合のみ見出し行の視覚的な横並び（flex row）を素の`<div>`が担い、
     h3自体はTriggerだけを包む薄い意味付けに留める設計へ修正（trailingが無い単純な
     場合は素のh3のみで済ませ余計なラップを増やさない）。
  4. **ネイティブ`<details open]`>属性→Radix `data-state`のCSS移行**: 3ファイル
     （MapLayersPanel/WeightPanel/recipeControls、他3ファイルはcomposesで追従）の
     chevron回転セレクタを`.layerSection[open] > .layerHeader .chevron`から
     `.layerTitle[data-state="open"] .chevron`（Triggerが自身にdata-stateを持つため
     祖先属性セレクタが不要になった）へ書き換え、`::-webkit-details-marker`の
     dead CSSを削除。page.tsx側3ブロックはネイティブ`<summary>`の既定ディスクロージャ
     三角に頼っていたため（自前chevronが元々無かった）、Radix化でこれが失われる
     退行を防ぐため`.blockChevron`を新設した。
  5. **テストのjsdom依存差分**: 旧`<details>`はjsdomが閉じた中身も隠さずクエリ可能にする
     （実ブラウザのUAスタイルとは異なる）挙動だったため、多数の既存テストが開閉状態を
     意識せず中身を直接検証できていた。Radix Accordion.Contentは閉じるとネイティブ
     `hidden`属性を持ち実ブラウザに忠実に隠れるため、46件のテストが一斉に失敗した
     （CarStressRecipePanel/MotorVehicleDensityRecipePanel/RoadSuitabilityRecipePanel/
     MapLayersPanelの4ファイル）。各ファイルのrenderヘルパーへ「レンダー直後に
     閉じたAccordion.Triggerを全クリックして開く」ヘルパーを追加して解消（ネストした
     Disclosureは1回のクエリで拾いきれない場合があるため変化が無くなるまで反復、
     FieldLabelのPopover.Trigger・renderHintToggleの情報アイコンは同じ
     `aria-expanded="false"`を持つが`aria-controls`の有無で区別し誤って開かないようにした）。
     MapLayersPanel.test.tsxの`openSection`（`document.getElementById(...).open =
     true`）はコンテナ内のトリガーを`fireEvent.click`で辿る方式へ変更（生DOMの
     `.click()`だとReactのstate更新がact()で包まれず次のexpectまでに反映されないことが
     あったため`fireEvent.click`を使用）。domIdは旧`<details id>`と同じ位置づけで
     Trigger単体ではなくRoot（コンテナ）へ付け直した（`within()`によるセクション内
     スコープ検索を保つため）。
  - **実機確認（Playwright、一時spec・検証後削除）**: デスクトップでサイドバー3ブロック
     （ルートを作る/研究/開発者）の開閉・aria-expanded・チェブロン回転を確認。研究タブの
     ネストしたDisclosure（RecipePanelSection内のgroup）とLevelPicker（RadioGroup）の
     組み合わせ動作、および見出し(h3)のtextContentにtrailingの文言が混入していないことを
     実機でも確認（jsdomで見つけた問題の裏取り）。モバイル幅(390x844)でMapLayersPanelの
     レイヤーセクション開閉とLayerChip操作がセクション開閉に影響しないことを確認。
     スクリーンショットで視覚的な崩れ（チェブロン・上書きチップ・LevelPickerの色分け）が
     無いことも確認した。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。

### - [x] T255. Phase3: BottomSheet→vaul（断念）、DynamicLayerTimeSlider→Embla Carousel 規模M〜L（2026-08-24完了、BottomSheetは断念し現行実装を維持）

- 発端: T251の調査結果。4件中もっともリスクが高い2件。
- 対応内容: BottomSheet→vaul(Drawer)。4シート共有の高さ状態・暗幕なし・地図の
  ピンチズームとの共存・矢印キーでの5vh刻み調整は個別の実機再検証が要る（4シート共有の
  高さ状態はvaulの標準機能でカバーしきれない可能性があり、着手前に設計判断が必要）。
  DynamicLayerTimeSlider→Embla Carousel（+wheel-gesturesプラグイン）。可変幅スライド・
  ホイール変換・スナップは標準機能でカバーできるが、キーボード操作（Arrow/Home/End）・
  `role="slider"`のARIA・「現在」ボタンは今と同程度の自前実装が残る。
- 完了条件: 実機チューニング済みの現行操作性（touch-action・スワイプ閉じ・ホイール変換等）
  と同等以上をPlaywright＋実機確認。
- **着手判断（2026-08-24）**: T254で規模Sの想定がM相当になった直後だったため、着手前に
  改めてユーザーへ確認（AskUserQuestion）。「両方とも実施（リスク承知）」の回答を受けて着手。

- **実装メモ（2026-08-24完了）**:
  1. **BottomSheet→vaul: 断念（上流の確定バグ）**。実装自体はPlaywright実機Chromiumで
     一通り動作するところまで到達した（`modal={false}`＋`snapPoints`でheight=100vh＋
     transformで対象スナップポイント分だけ見せる設計、bottom:0＋padding-bottomで
     タブバー分のクリアランスを確保する等、vaulのtransform計算がbottom:0前提であることを
     実機検証で突き止めて回避策を確立した）。しかし最終検証で、`modal={false}`と
     `snapPoints`の組み合わせにおいて、vaulの内部実装（Radix Dialog由来）が`body`要素へ
     `pointer-events: none`を適用してしまい、シート表示中に地図・下部タブバーが
     一切クリックできなくなる**上流の確定した既知バグ**（GitHub Issue
     [emilkowalski/vaul#509](https://github.com/emilkowalski/vaul/issues/509)・
     [#534](https://github.com/emilkowalski/vaul/issues/534)、いずれもOpen・未修正）を
     発見・実機Chromiumで再現確認した。`body.style.pointerEvents`を強制的に空へ戻す
     回避策も試したが、4枚あるBottomSheetインスタンスが切り替わるたびに（Radix Dialogの
     マウント/アンマウントサイクルのたび）再発するため、継続的な監視（MutationObserver等）が
     要る不安定なハックにしかならないと判断した。「暗幕なし・地図が常に操作可能」は
     T34由来のこのアプリの核心要件のため、BottomSheetはvaul化を断念し現行の自前実装
     （pointerイベントによる自前ドラッグ・タッチスワイプ閉じ）をそのまま維持する
     （`git checkout`で復元）。vaulパッケージは削除した。
  2. **DynamicLayerTimeSlider→Embla Carousel: 完了**。可変幅コマ（正時/非正時で幅が違う）は
     Embla標準の可変スライド幅対応でそのままカバーできた。左端固定の目印（旧実装の
     `INDICATOR_OFFSET_PX`）に対して選択中コマの中心を合わせる操作感は、Emblaのカスタム
     `align`関数（`(viewSize, snapSize) => INDICATOR_OFFSET_PX - snapSize / 2`）で再現し、
     `containScroll: false`で最初/最後のコマも目印まで届くようにした。自前だった
     設定確定タイマー（90msデバウンス）・ドラッグのpointerイベント処理・ホイール変換の
     nativeリスナーはすべて撤去できた。キーボード操作（Arrow/Home/End）・
     `role="slider"`のARIAはEmblaが提供しないため従来どおり自前で維持（想定どおり）。
     `settle`イベントで最終確定indexを報告する設計を当初試みたが、実機Playwright検証で
     高速な合成ドラッグ後に`settle`が発火しないケースを確認したため、より標準的で
     確実に発火する`select`イベント（最寄りスナップ位置が変わった瞬間のみ発火し、
     ドラッグ中の毎フレームでは発火しないため過剰報告の懸念も生じない）へ切り替えた。
     jsdomでのテストはmatchMedia・IntersectionObserver・ResizeObserverの3つをEmbla自身が
     無条件に呼ぶため、いずれも未実装のjsdomでは例外になる（useIsMobile.test.tsと同じ
     既知の欠落パターン）。テストファイル側でモックして解消した。
  - **実機確認で判明した限界（Playwrightでは検証不能）**: ホイール（縦スクロール→横変換）
     動作は、Playwrightの合成`mouse.wheel()`イベントでは`embla-carousel-wheel-gestures`
     プラグインの内部ジェスチャー検出（wheelイベントを合成mousedown/mousemoveへ変換して
     Emblaの通常のドラッグ処理に載せる方式）が発火しないことを実機Chromiumで複数パターン
     確認した（単発・連続・高速連打いずれも不発）。ドラッグ（マウス/タッチ）・キーボードは
     Embla自身のAPI（`selectedScrollSnap()`）レベルで正しく動作することを確認済みのため、
     Embla本体の統合自体は機能している。ホイール変換だけがPlaywright上で検証できない状態
     だったため、Playwright特有の合成イベントの限界（vaulのケースのような確定した
     実ブラウザバグではない）なのか実機でも機能しないのかの切り分けをユーザーへ依頼した。
     **ユーザーの実機（実際のマウスホイール/トラックパッド）確認の結果、正常に機能する
     ことを確認済み**（2026-08-24）。Playwright側の合成イベントが検出されなかっただけで、
     実装自体に問題は無かったと判明した。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。BottomSheet.test.tsx
    （5件、既存の自前実装のまま）も引き続きgreen。DynamicLayerTimeSlider.test.tsx
    （9件）はEmbla化後も既存の検証観点（ARIA・キーボード操作）を維持したままgreen。

### - [x] T257. WBGT数値と気象庁警報・注意報の語彙混同バグを修正する 規模S（2026-08-24完了）

- 発端: ユーザー報告「wbgtの数値と、警報注意報の紐づけ。現在25だが警報扱いになっている。
  これは正しいか」に続けて「wbgtと、気象庁の一般的な注意報、警報ってどう紐づけているの？
  言葉から違うと思う。」という確認。
- 調査: WBGT（暑さ指数）は環境省の熱中症予防運動指針に基づく独立した5段階制度
  （ほぼ安全/注意/警戒/厳重警戒/危険、算出基準は気温ではなく湿球黒球温度）で、気象庁の
  気象警報・注意報（注意報/警報/特別警報の3段階）とは所管・算出方法とも無関係の別制度。
  `WarningBadge.tsx`の`LEVEL_SUMMARY_LABEL`は`Record<WarningBadgeLevel, string>`1本で
  JMA（T205）・WBGT（T174）・河川氾濫予報（T212）の3種の表示元を共有しており、
  共通のレベルキー`"warning"`にJMA側の語彙「警報」だけが固定されていた。WBGT値25は
  暑さ指数運動指針上「警戒」に相当するレベルだが、共有テーブル経由で「警報」と誤表示
  されていた（気象庁の公式な「警報」を実際に発表しているわけではない）。
- 修正: `WarningBadgeItem`へ`source: "jma" | "wbgt" | "flood"`を追加、
  `LEVEL_SUMMARY_LABEL`を`Record<WarningBadgeSource, Record<WarningBadgeLevel, string>>`化。
  WBGT: 注意/警戒/厳重警戒/危険、JMA: 注意報/警報/厳重警戒/特別警報、
  flood: 氾濫注意報/氾濫警報/氾濫危険警報/氾濫特別警報、とソースごとに独立した語彙表へ
  分離した。`page.tsx`の3箇所の`WarningBadgeItem`構築時に対応する`source`を付与。
- 検証: `WarningBadge.test.tsx`8件green（新規2件: 「WBGT単独（warningレベル）はJMAの
  『警報』ではなく『警戒』と表示する」「JMAとWBGTが同じwarningレベルで混在すると、
  最初に見つかった方（JMA）の語彙が使われる」）。

### - [x] T258. フロントのfetch()失敗がデバッグログに残らない箇所を横断的に修正する 規模S〜M（2026-08-24完了）

- 発端: ユーザー報告「現在地点から20kmでルート生成に常に失敗する」。本番実機
  （緯度経度35.7506948, 139.7418897、Renderデプロイ済みフロント）でユーザーが
  `POST /api/routes/generate`送信の約1分後に「fail to fetch」が表示される事象を確認したが、
  デバッグログには一切記録が残っていなかった。直接API再現（王子・ユーザー座標いずれも
  ローカルから本番DBへ直結）は2回とも成功しており、根本原因はRenderプラットフォーム側の
  HTTPタイムアウト（未確定、目安約1分）が疑われるが確定していない
  （**根本原因自体は未解決のままT105へ集約**、本タスクはその調査を継続可能にする
  デバッグログ側の穴を塞ぐもの）。ユーザーから「タイムアウト以外にも異常な状態になった
  時にはデバッグログにでてきてほしい。ほかにも表示すべきものがないか確認して」という
  横断監査の指示を受けて着手。
- 調査: T105（バックエンド一時的到達不能の調査、2026-08-17）で確立された
  「`fetch()`自体の例外（タイムアウト・通信エラー）は`response.ok`チェック以前に
  投げられるため、`try/catch`で囲まないとデバッグログに一切残らない」という既知パターンが、
  T105での修正範囲（GET系の`debugStatsApi.ts`・`versionApi.ts`）の外側に複数箇所
  再発していた。`frontend/src`配下の`fetch(`呼び出し箇所を全7ファイル洗い出して確認:
  - `routeApi.ts: postJson`（ルート生成・プレビューのPOST、**今回の20kmバグの直接該当箇所**）
    — 未対応
  - `regionApi.ts: fetchBreakdown・fetchAxisInspector` — 未対応
    （同ファイルの`refreshBasemapCache`のみ既に対応済みだった）
  - `jmaNowcastFrames.ts: fetchJmaTargetTimes` — 未対応、かつタイムアウト指定も無し
    （無期限に待ち続ける状態だった）
  - `page.tsx`: 降水ナウキャスト・雷ナウキャスト読み込み・`handleGenerate`
    （ルート生成ボタンのハンドラ）の3箇所の`catch`ブロック — 例外は捕まえてUIへは
    表示していたが、`debugLog`を呼んでいなかった
  - `weatherApi.ts`・`fetchJson.ts`自身・`healthApi.ts` — 確認の結果、対応済みまたは
    意図的サイレント（後述）
- 修正:
  1. `routeApi.ts`: `postJson`の`fetch()`を`try/catch`で囲み、
     `DOMException("TimeoutError")`か否かで「失敗 (タイムアウト)」「失敗 (通信エラー)」を
     区別して`debugLog`へ記録した上で再送出。
  2. `regionApi.ts`: `fetchBreakdown`・`fetchAxisInspector`へ`refreshBasemapCache`と
     同型の`try/catch`パターンを追加。
  3. `jmaNowcastFrames.ts`: `fetchJmaTargetTimes`を共通GETラッパー`fetchJson`
     （`lib/fetchJson.ts`、T105・regionApi.tsで確立済みのパターンの集約先）経由へ
     リファクタリング。15秒タイムアウトと`api:jma-nowcast-times`カテゴリのログが
     新たに付いた（降水・雷ナウキャスト双方に波及）。
  4. `page.tsx`: 降水・雷ナウキャストの`catch`ブロックへ`debugLog`追加。
     `handleGenerate`の`catch`ブロックへも`debugLog`追加（`postJson`側で既に記録済みの
     失敗を重複記録する形にはなるが、`postJson`を経由しない想定外の例外もこの層で
     拾えるようにする多層防御として残した）。
  5. `weatherApi.ts`は全関数が既に`fetchJson`経由で対応済みと確認（修正不要）。
  6. `healthApi.ts`はログが皆無（成功時含め）だが、頻繁なポーリング（ヘルスチェック）での
     ログスパムを避ける意図的設計と判断し、対象外とした。
- 副作用の修正: `jmaNowcastFrames.ts`のリファクタリングでエラーメッセージの文言・形式が
  `fetchJson`標準形式（`` `${errorLabel}の取得に失敗しました[HTTP ${status}]` ``）に
  変わったため、既存テスト3ファイル（`jmaNowcastFrames.test.ts`・
  `precipitationNowcast.test.ts`・`thunderNowcast.test.ts`）のモックレスポンスへ
  `headers: new Headers()`を追加し、期待エラーメッセージを新形式へ更新した。
- 検証: フロントvitest 56ファイル510件green、`tsc --noEmit`green。
- 完了条件: 満たした（`fetch(`呼び出し全7ファイルの横断監査は完了）。ただし20kmバグ自体の
  根本原因（Renderプラットフォームタイムアウトの確定）は**未解決のままT105へ残す**。
  次回の再現時は、本タスクで追加したデバッグログ（`api:route`カテゴリの
  「失敗 (タイムアウト ...ms)」/「失敗 (通信エラー)」記録）がT105の完了条件（対策済み
  制御の再発かコールドスリープかの切り分け）の材料になる想定。

---

## 目論見書による二画面構想の正式化（2026-08-24・ユーザー承認）

「自転車専用道を優先したい」という要望の調査から始まった一連の議論（0次フィルタの
未配線発見→T266起票→重みUI再設計案→二画面分割案→最終形の構想）を、目論見書
（Artifact: `RideCompass 目論見書`、https://claude.ai/code/artifact/ce418e86-3338-410b-9d14-826e00764b78 ）
として取りまとめ、**ユーザーが承認した**（2026-08-24）。骨子:

- **最終形**: 一般ユーザーは研究側で練り上げられた少数の推定軸の重みを調整するだけで
  最適なルーティングが得られる状態へ「蒸留」していく。一般UIの選択肢は増やさず、
  利用実績に基づいて淘汰する。
- **二画面分割**: 「軸を使う人」（一般向けルート設定）と「軸を作る人」（軸スタジオ=
  T221 Stage E相当）を別画面にする。**軸スタジオは既存ページ内のパネルではなく
  独立URLの管理画面として実装する**（ユーザー指示による修正点。URLレベルで切れて
  いる方が権限制御を敷きやすい）。現行メインページの「研究」セクション
  （ResearchPanel・WeightPanel・レシピパネル群）と「開発者」セクション（DebugPanel・
  DebugConsole・SystemStatusPanel）はこの管理画面へ移設する。
- **設計上の歯止め6条**（材料の排他帰属の機械検査／公開済みaxis_id不変・変更は複製＋
  新ID／テンプレート4種の線引き維持／材料の天井の明示／認可境界1箇所・安全側
  デフォルト／DBが追いつくまで挙動を変えない）を実装に埋め込む。

現在地: T221 Stage A〜D完了（DB化・管理API・本番migration適用済み）、T266起票済み。
残るギャップを以下のタスクへ正式分解する。Phase番号は目論見書6章のロードマップに対応。

### - [x] T267. 一般向けルート設定画面の再設計実装（Phase 1） 規模M〜L（2026-08-24完了）

- 背景: 目論見書4章「ルート設定」。現行の評価重みUI（研究タブ内のWeightPanel）は
  全軸が横並びの数値入力で、どの軸が効いているか・観測/推定/動的の別が分からない。
  これを一般ユーザー向けの導線として再設計する。
- 対応方針（モックアップは本セッションで提示済み・ユーザー合意済み）:
  1. 最上部に0次の除外チップ（自転車通行禁止・高速道路・幹線道路(trunk)）。
     backend配線はT266が前提。
  2. 軸を観測・推定・動的の3カテゴリにグルーピングし、チェックボックスで軸ごと
     ON/OFF＋スライダーで重み設定。**カテゴリ分類の確定（特に夜間軸が観測か推定かの
     境界例判断）を実装時に行い、分類基準を明文化する**（目論見書8章の要判断事項）。
  3. 有効な軸の重み配分を積み上げバーで常時可視化。
  4. プリセットボタン（バランス／自転車専用道を優先／最短時間重視／安全重視）で
     一発適用→微調整の導線。重み値は暫定でよい（実走検証を経て確定、目論見書8章）。
- 完了条件: 一般導線からプリセット適用・軸選択・重み調整・0次除外の変更ができ、
  「自転車専用道を優先」プリセットで実際にcycleway/自転車レーンのある道路が
  優先されたルートが生成されることを実機確認する。docs/architecture.md追従
  （規模M以上・UI構成の変更）。
- 依存: T266（0次チップのbackend）。
- **実装メモ（2026-08-24完了）**:
  1. カテゴリ分類を確定: 観測=`gradient`/`surface_q`/`stop_density`/`night`
     （タグ・POI等の一次属性を直接読む、または単純なフラグ加算のみで判定式を持たない軸）、
     推定=`car_stress`/`accident`（複数材料をレシピ・判定式で合成する軸）、
     動的=`wind`（時々刻々変わる外部データ由来）。夜間はlit/tunnelタグのフラグ加算のみで
     判定式が無いため観測へ分類（目論見書の暫定表と同じ結論。
     `frontend/src/lib/evaluationAxes.ts: axisCategory`が単一ソース）。
  2. 新規コンポーネント`frontend/src/components/RouteSettingsPanel/`。既存の研究モード
     `WeightPanel`とは別の常時表示パネルとして、`renderRouteResultsBody`（デスクトップ・
     モバイル両方が経由する共通関数）内の`RouteList`直前へ設置。
  3. **状態はWeightPanelと共有**: `route_preference`（`routePreference`/
     `weightOverrideEnabled`）はpage.tsxの同じstateをそのまま渡し、`withAutoEnable`で
     どちらのパネルを操作しても自動的に上書きが有効になる（研究モードとの二重管理を
     避けた。T270で研究UIを独立URLの管理画面へ分離する際に整理し直す前提）。
     `hard_filters`は新規state（`hardFilters`）で、既定値がbackendの
     `DEFAULT_HARD_FILTERS`と一致するため上書き専用トグルを設けず常時送信する。
  4. プリセット4種の重み値は目論見書提示のモックアップの値をそのまま採用（暫定、
     実走検証で調整予定と明記）。
  5. UI詳細: `FieldLabel`（説明ポップオーバー、内部に`<button>`を持つ）と
     `checkbox`を`<label>`で束ねると、ポップオーバーボタン押下でcheckboxも
     連動トグルされてしまう不具合になるため、`WeightPanel`の`WeightInput`と同じく
     `aria-label`で関連付ける非`<label>`構成にした。
  6. 実機確認（Playwright代替としてClaude Browserで確認、地図タイル自体は別ポート
     由来のポート不一致で無関係に表示失敗するが対象外）: プリセット「自転車専用道を優先」
     適用→重み配分バーがcar_stress 45%等へ更新→「幹線道路(trunk)」チップをOFF→
     「生成」→`POST /api/routes/generate`のリクエストボディで
     `route_preference`（car_stress:0.45等）・`hard_filters`（trunk:false）が
     期待通り送信され、レスポンスの`conditions`にも同じ値がエコーされることを確認。
  7. 検証: backend全1140件green（T266と共通）、フロントtsc/vitest 516件green。
     docs/architecture.md（コンポーネント一覧）へRouteSettingsPanelを追記。

### - [x] T268. 材料の排他帰属チェックを計算系レジストリへ移植する（Phase 2前提） 規模S〜M（2026-08-24完了）

- 背景: 目論見書7章・歯止め1。排他帰属の機械検査（`registry.py: register_axis`の
  `AxisInputConflictError`）は表示用レジストリにしか無く、実際のルーティング計算を
  駆動する`axis_definitions.py: AXIS_DEFINITIONS`（Stage DでDB化済み）には存在しない。
  軸スタジオ（T270）で自由に軸を登録できるようになる前にこの検査を計算系へ移植
  しないと、既存軸が専有する材料を新軸が黙って再利用し二重計上が混入する。
- 対応方針: 管理API（`/api/admin/axis-definitions`）の作成・更新経路で、材料
  （`AxisDefinition.materials`）の排他帰属を検査する。`shared`相当（距離等の共通
  コンテキスト）の扱いは`registry.py`の設計を踏襲。T218素材カタログ・`registry.py`側の
  attr_idとの対応関係（二重管理の回避、ADR「T12との関係」参照）もここで整理する。
- 完了条件: 既存軸が使用中の材料を参照する新軸の登録が管理APIレベルで拒否される
  テストがgreen。既存7軸のシードデータが検査を通過する（現状の共有設計と矛盾しない）
  ことを確認。
- **実装メモ（2026-08-24完了）**:
  1. `domain/axis_definitions.py`へ`AxisMaterialConflictError`（`registry.py:
     AxisInputConflictError`と同じ原則）と`check_material_exclusivity(candidate,
     existing)`を新設。`existing`に`candidate.axis_id`と同じキーがあれば
     自己比較としてスキップする（更新時に自分自身とは衝突しない）。
  2. **`shared`フラグは持たせなかった**（過剰な汎用化を避ける判断）: 現行7軸の材料
     （gradient_percent/wind_penalty/surface_good/stop_count_per_km/
     intersection_count_per_km/accident_count_per_km_year/car_stress_level/
     no_lit/has_tunnel）はいずれも単一軸専有で、`registry.py`の`shared=True`
     （距離等の共通コンテキスト）に相当する材料が1件も存在しないため
     （`compute_edge_axis_scores`のmaterials辞書を確認、distance_mは軸材料としては
     未使用）。必要になった時点で`MaterialTerm`側への追加を検討する注記のみ残した。
  3. `AxisRegistryAdminService.create`/`update`の冒頭で`check_material_exclusivity`を
     呼ぶ（`ValueError`系のため`axis_admin.py`の既存`except ValueError → 409`が
     そのまま機能し、ルーター側の変更は不要だった）。
  4. T218素材カタログとの対応関係整理は、既存7軸の材料が`registry.py`側の
     `attr_id`と1:1で対応済み（新規の乖離なし）と確認するに留めた。二重管理の解消
     そのもの（レジストリ統合）はT270着手時に改めて要否を判断する。
  5. 既存テスト（`test_axis_registry_service.py`）が同一material="dummy"を使い回す
     フィクスチャだったため、新チェックに引っかかった2件（sort_order確認用ダミー・
     最後の1軸削除ガード確認用の2軸目）をmaterial引数で分離して修正。
  6. 検証: 新規`test_axis_definitions.py`（純粋domain、既存7軸の相互チェックが通ることを
     含む）＋`test_axis_registry_service.py`への追加3件。backend全1147件green。

### - [x] T269. 軸カタログ（axis-catalog.json）のDB追従方式の決定＋実装（Phase 2前提） 規模M（2026-08-24完了）

- 背景: 目論見書8章の要判断事項。フロントの軸一覧・既定重み・ラベルは
  `export_openapi.py`が**Python内蔵の`AXIS_DEFINITIONS`から**生成する
  `axis-catalog.json`に由来し、CIの`api-contract`ジョブはDB接続を持たない。
  このままでは軸スタジオでDBに追加した軸がフロントのカタログに現れない
  （Stage D ADR「axis-catalog.jsonは変更していない」の積み残し）。
- 対応方針（実装前にユーザーと方式を決定する）: 候補は (a) CIにDB接続を追加して
  ビルド時生成を維持、(b) 公開操作時にカタログを再生成しランタイム配信へ切替、
  (c) カタログ取得APIを新設しフロントは起動時フェッチ。静的生成物としての
  型安全性（generated型とのペア）と、デプロイなしで軸が増える運用の両立が論点。
  → **ユーザー選択: (c) カタログ取得API + 起動時フェッチ**。
- 完了条件: 管理APIで追加した軸が、フロントの軸カタログ（一般UIの軸一覧・
  重み既定値）へコード変更・再デプロイなしに（または合意した方式の運用フローで）
  反映されること。
- **実装メモ（2026-08-24完了）**:
  1. **重要な前提の訂正**: 当初の背景文は「axis-catalog.jsonがAXIS_DEFINITIONSから
     生成される」としていたが、調査の結果`axis-catalog.json`の`axes[]`/
     `primary_attributes[]`は実際には`registry.py`（表示専用レジストリ、T137/T145b、
     DB化されていないPython宣言のみ）から生成されており、`AXIS_DEFINITIONS`由来なのは
     `preference_defaults`のみと判明した。`registry.py`はDB書き込み手段を持たないため
     GUIで作った軸を原理的に表現できず、既存のaxis-catalog.jsonをそのまま追従させても
     目的を達成できない。そのため`AxisDefinition`（DB化済み・GUI編集可能な方）自体へ
     `label`/`description`/`category`を追加し、これを単一ソースとする新エンドポイントを
     新設する方針に切り替えた。
  2. `domain/axis_definitions.py: AxisDefinition`へ`label: str`（必須）・
     `description: str = ""`・`category: AxisCategory("観測"|"推定"|"動的") = "推定"`を
     追加。既存7軸の値は`frontend/src/lib/evaluationAxes.ts`の旧`PREFERENCE_AXIS_DESCRIPTIONS`
     ・`registry_defaults.py`のlabelから移植（表示文言は変更なし）。
  3. DB: `migrations/0015_axis_definitions_label.sql`（`0014`は既に本番適用済みのため
     追加カラムのNOT NULL DEFAULT + backfillという安全な形の別migrationとした）。
     ORM（`AxisDefinitionRow`）・repository（`_row_to_definition`/`upsert`）・
     管理API（`AxisDefinitionPayload`/`_to_response`）を追従。本番・dev DB・
     ローカルテストDB(ridecompass_test)いずれにも適用済み。
  4. 新規公開エンドポイント`GET /api/axis-catalog`（`api/routers/axis_catalog.py`、
     認可不要）。DBへは触れず、プロセス内キャッシュ`AXIS_DEFINITIONS`
     （起動時・管理API書き込み直後にpush型更新済み、Stage D設計を踏襲）をそのまま
     読むだけの実装。
  5. フロント: `services/axisCatalogApi.ts`（`fetchJson`共通ヘルパー経由）・
     `hooks/useAxisCatalog.ts`（マウント時に1回取得、取得完了まで/失敗時は既存7軸の
     静的フォールバックを返す）を新設。`RouteSettingsPanel`をこのhook経由に置き換え、
     プリセット適用時は`{...catalog.defaultWeights, ...preset.weights}`で未言及の軸を
     補うようにした（新しい軸が増えてもプリセットが必須キー欠落で422にならないための
     防御）。カタログ更新後に未知のaxis_idが増えていた場合、`routePreference`stateへ
     自動で既定重みを補う`useEffect`も追加（同じ理由）。研究モードの`WeightPanel`は
     引き続き旧`axis-catalog.json`静的読み込みのまま（T270でWeightPanel自体を
     置き換える際に統合する想定、今回はスコープ外）。
  6. 検証: backend全1149件green（新規`test_axis_catalog_routes.py`2件含む）、
     フロントtsc/vitest 516件green、実機確認（`/api/axis-catalog`が200・
     RouteSettingsPanelがDB由来のlabel/description/categoryで正しく表示されることを
     ブラウザで確認）。docs/architecture.md追従。

### - [x] T270. 軸スタジオ — 独立URLの管理画面としてT221 Stage Eを実装する（Phase 2本体） 規模L（2026-08-24完了・残作業あり）

- 背景: 目論見書4章「軸スタジオ」・T221 ADRのStage E（GUI編集画面、ADRスコープ外と
  して起票待ちだったもの）。**ユーザー指示（2026-08-24）により、既存ページ内の
  パネルではなく独立URL（`/admin`系ルート）の管理画面として実装する**。URLレベルで
  一般画面から切れていることで、権限制御（T272）をルーティング境界で敷ける。
- 対応方針:
  1. Next.jsの独立ルートとして管理画面を新設。軸コンポーザー（材料選択→4テンプレート
     選択→パラメータ調整→保存）を管理API（`/api/admin/axis-definitions`）経由で実装。
  2. 検証手段（地図プレビュー・比較生成）への導線を持たせる。空間JOIN系材料
     （事故点・POI集計）は地図プレビュー不可という非対称をUI上で最初から明示する
     （目論見書・歯止め4）。
  3. **現行メインページの「研究」セクション（ResearchPanel・WeightPanel・
     CarStressRecipePanel等のレシピ群）と「開発者」セクション（DebugPanel・
     DebugConsole・SystemStatusPanel）を管理画面へ移設し、メインページからは
     削除する**（ユーザー指示。一般画面に開発者導線を残さない）。
     移設に伴うlocalStorageフラグ（research/debug）の扱いはT272の権限制御設計と
     整合させる。
  4. 本番Renderの`AXIS_ADMIN_TOKEN`設定（現状未設定で管理APIは常時403、
     Stage D ADR残作業1）を完了条件に含める。
- 完了条件: 管理画面から新しい軸を作成・保存し、（T269の方式で）一般UIのカタログに
  出現し、その軸へ重みを付けたルート生成が動作することをE2Eで実機確認。
  メインページから研究・開発者セクションが消え、管理画面で同機能が使えること。
  docs/architecture.md追従（新レイヤー種=管理画面の追加）。
- 依存: T268（排他検査）・T269（カタログ追従）。規模M以上のため着手時に本エントリを
  さらに分割してよい。
- **実装メモ（2026-08-24完了・一部残作業あり）**:
  1. **新規ルート`frontend/src/app/admin/page.tsx`**（+`admin.module.css`）。
     `AxisStudio`（軸コンポーザー・一覧・CRUD）、`ResearchPanel`＋`WeightPanel`＋
     `CarStressRecipePanel`/`RoadSuitabilityRecipePanel`/`MotorVehicleDensityRecipePanel`
     （研究セクション）、`DebugPanel`/`DebugConsole`/`SystemStatusPanel`/`BackendStatus`
     （開発者セクション）をすべて移設した。
  2. **状態共有の設計判断**: WeightPanel等が使うstate（`weightOverrideEnabled`・
     `scoringWeights`・`routePreference`・3レシピの`overrideEnabled`/`recipe`）は、
     メインページ（`/`）と`/admin`が別Reactツリーのため直接共有できない。
     `useStoredJsonState`（新設、`hooks/useStoredState.ts`にJSON直列化の薄いラッパーを
     追加）と、`useRecipeOverride`に追加した`storageKey`引数（指定時は内部で
     `useStoredJsonState`を使う）で、同じlocalStorageキーを両ルートから読み書きする形に
     した。同一タブでのリアルタイム同期ではなく次回マウント時に反映される
     （`lib/researchMode.ts`の既存挙動と同じ制約）。メインページ側は編集UIを持たず
     読み取り専用で使う（setterを破棄）。
  3. **軸コンポーザー**（`components/AxisStudio/`）: `AxisShape`の3判別式
     （区分線形補間・カテゴリ値・フラグ加算、`recipe_then_breakpoint_linear`込みで
     実質4テンプレート）をフォームへ写した。材料選択は
     `lib/axisMaterialsCatalog.ts`の**閉じた9件**
     （`AXIS_DEFINITIONS`が実際に参照するmaterial idの全量、
     `registry_defaults.py`の一次属性カタログとは別語彙）から選ぶ。
  4. **管理APIクライアント**: `lib/adminToken.ts`（localStorage、researchMode.tsと同型の
     簡易実装）＋`services/axisAdminApi.ts`（CRUD、X-Admin-Tokenヘッダ付与）。
  5. **実機E2E確認（2026-08-24、backend/.envへdev専用のAXIS_ADMIN_TOKENを設定して実施）**:
     (a) `/admin`でトークン入力→一覧取得成功。(b) 新規軸作成で`surface_good`材料を選ぶと
     T268の排他チェックが409で正しく拒否することを確認（既存`surface_q`軸と衝突する
     ケース）。(c) `gradient`軸の`default_weight`を編集→PUT 200→
     `GET /api/axis-catalog`が更新値を即座に返す（再起動不要のpush型更新）ことを確認、
     検証後に既定値0.15へ戻した。(d) メインページ（`/`）から「研究」タブが消え、
     「開発者」タブは地図キャッシュ再読み込みボタンのみが残ることを確認。
     backend全1149件・フロントtsc/vitest 516件green。
  6. **残作業（未完了、影響範囲付き）**:
     - **地図プレビュー・比較生成への導線**（対応方針2）は未実装。軸コンポーザーは
       数値入力のみで、作成した軸のスコア分布や地図上の見え方を確認する手段がない。
       次に軸を作る人が「妥当な折れ点か」を勘で決めるしかない状態。
     - **本番Renderの`AXIS_ADMIN_TOKEN`設定**（対応方針4）は未実施
       （Renderダッシュボードへのアクセスが必要、Stage D ADR残作業と同じ制約）。
       設定するまで本番の`/api/admin/axis-definitions`は常時403のまま
       （安全側のデフォルト、意図通り）。**T272（2026-08-24完了）でこの認可機構自体が
       `AXIS_ADMIN_TOKEN`共有トークンからHTTP Basic認証
       （`ADMIN_BASIC_AUTH_USERNAME`/`PASSWORD`）へ置き換わったため、この項目は
       本番側の設定作業として当時のまま未着手だが、設定すべき変数名が変わっている
       点に注意（T272エントリ参照）。**
     - **「新しい軸を作成→ルート生成」のE2Eは未検証**。原因は設計上の制約:
       `lib/axisMaterialsCatalog.ts`の9材料は**全て既存7軸が専有済み**のため、
       現在の閉じた材料集合の範囲では、既存軸を削除しない限りT268の排他チェックに
       必ず引っかかり新規作成できない（実機で実際に確認した制約、上記(b)参照）。
       真に新しい軸を作るには、まず新しい材料を取込パイプライン側に追加する
       （目論見書7章・歯止め4「材料の天井」、コード変更が要る）必要がある。
       軸スタジオ自体はこの制約下で正しく動作している（バグではない）が、
       「材料が増えるまで新規軸は事実上作れない」という運用上の制約は
       ユーザーへ明示しておくべき。

### - [x] T271. 軸の公開フローと統治ルール（Phase 3） 規模M

- 背景: 目論見書7章・歯止め2、8章。一般ユーザーの保存設定は`axis_id`キーで再現される
  ため、公開後の軸の破壊的変更・削除は他ユーザーの設定を黙って壊す。また同じ意図の
  軸が乱立すると一般UIの選択肢が増えて蒸留の方向と逆行する。
- 対応方針: (1) 公開済み`axis_id`の不変制約（管理APIレベルで、公開フラグ付き軸の
  破壊的更新・削除を拒否。改良は複製＋新IDの導線をUIに用意）。(2) 下書き→検証→公開の
  状態遷移をDBスキーマへ追加（公開前の軸は一般カタログに出さない）。(3) 命名・重複
  ガイドと公開前チェックリストを軸スタジオUIへ組み込む。
- 完了条件: 公開済み軸の破壊的変更が構造的に不可能であること、下書き軸が一般UIに
  漏れないことのテストがgreen。
- 依存: T270。
- 実装メモ（2026-08-24完了）: `AxisDefinition.is_published: bool`（既定False）を追加し
  （`migrations/0016_axis_definitions_is_published.sql`、既存7行はDEFAULT trueで
  backfill）、`domain/axis_definitions.py: AxisPublishedImmutableError`/
  `check_publish_immutability`を`AxisRegistryAdminService.update`/`delete`の冒頭で
  呼ぶ形で実装。`GET /api/axis-catalog`（T269）は`is_published=True`のみ返すよう変更。
  `axis_admin.py: update_axis_definition`に欠けていた`ValueError`ハンドラも追加
  （実装中に発見した既存の抜け穴、以前は更新時の材料衝突[T268]が想定外の500だった）。
  フロントは`AxisStudio.tsx`に公開済み/下書きバッジ・編集/削除の無効化・「複製して
  新規作成」ボタンを追加、`AxisComposer.tsx`に`draftFromDuplicate`（axis_idクリア・
  is_published強制false）と「公開する」チェックボックスを追加。「改良は複製＋新IDの
  導線」は3.命名・重複ガイドの専用UI（チェックリスト等）までは作らず、複製ボタン自体を
  唯一の導線とするミニマムな実装とした（対応方針3「命名・重複ガイド・公開前チェック
  リストのUI組み込み」は見送り、複製フローがあれば実用上十分と判断）。
  検証: backend全1169件green（新規`test_axis_definitions.py`3件・
  `test_axis_registry_service.py`3件・`test_axis_admin_routes.py`2件・
  `test_axis_catalog_routes.py`1件含む）、frontend tsc/eslint/vitest 517件green、
  実サーバーで軸スタジオの公開済みバッジ・編集/削除disabled・複製フロー（axis_id空・
  公開チェックOFF）を確認。複製後の新規作成は材料の天井（9材料が既存7軸で専有済み、
  [[rc-phase2-t270-axis-studio]]の既知の制約）により409（材料衝突）で拒否されたが、
  これはT271の不具合ではなく既存の設計上の制約——エラー応答自体が正しく返り、
  公開済みgradient軸のデータが無傷であることをAPI直接確認で検証した。

### - [x] T272. 管理画面・研究機能の権限制御導入（Phase 3） 規模M

- 背景: 目論見書6章Phase 3。「将来、研究パネルを一般ユーザーから隠し権限制御を導入
  する」という以前からの方針（Stage D ADRにも記録）を、管理画面のURL分離（T270）を
  機に実施する。現行の`researchMode.ts`（localStorageトグル、誰でもON可）は
  廃止または管理画面ログインへの置換対象。
- 対応方針: 管理画面のルーティング境界で認可を敷く。backend側は認可判定が
  FastAPI Dependency 1箇所に集約済み（Stage Dの設計）のため、共有トークンから
  実権限チェックへの差し替えを行う。frontend側の方式（Basic認証・トークン入力・
  アカウント制等）は着手時にユーザーと決定する。
- 完了条件: 一般ユーザーの導線から管理画面・研究機能へ到達できず、認可を持つ
  ユーザーのみがアクセスできること。docs/architecture.md追従（認可境界の記述）。
- 依存: T270。
- 実装メモ（2026-08-24完了）: フロント側方式はAskUserQuestionでユーザーに確認し
  「将来的にはアカウント制としたいが、現状は動作確認・研究用のためBasic認証として
  後から拡張する」との回答を得てBasic認証で実装した。共有トークンからの「差し替え」は
  backend/frontend両方でHTTP Basic認証へ統一する形にした（2箇所独立: (1)
  `frontend/src/proxy.ts`が`/admin/:path*`のルーティング境界でブラウザ標準Basic認証
  ダイアログを要求[Next.js 16で`middleware.ts`→`proxy.ts`へ改称、frontend/AGENTS.md
  「このNext.jsは知っているものと違う」の指示どおりnode_modules内docsを確認して
  対応]、(2) backend `axis_admin.py: require_admin_basic_auth`が
  `fastapi.security.HTTPBasic`+`secrets.compare_digest`で軸CRUD APIを保護——別
  オリジンのためブラウザの認証キャッシュが自動転送されず、軸スタジオUI自体の資格情報
  入力フォームは維持。`config.py`の`axis_admin_token`は`admin_basic_auth_username`/
  `admin_basic_auth_password`へ置換、`lib/adminToken.ts`は単一トークンからusername/
  password保持へ再設計、`hooks/useAdminToken.ts`は`useAdminCredentials.ts`へ改称。
  `researchMode.ts`は変更不要と判断（/admin自体が認証済みユーザーのみ到達可能になった
  ため、表示ON/OFFトグルとしての役割のみ残っても意味の重複は生じない）。
  検証: backend全1169件green（`test_axis_admin_routes.py`の認可テストをBasic認証へ
  書き換え）、frontend tsc/eslint/vitest 517件green、実サーバーで(1)`/admin`が資格情報
  なし/誤りで401＋`WWW-Authenticate`ヘッダ、正しい資格情報（`http://user:pass@host/admin`
  形式でBrowser paneから確認）で200、(2)軸CRUD APIも同様に401/200を確認、(3)軸スタジオの
  新ユーザー名/パスワードフォームで実際に軸一覧が取得できることを確認した。
  **残作業（影響範囲付き）**: 本番Render（backend・frontend双方）へ
  `ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_PASSWORD`を未設定のため、
  設定するまで本番の`/admin`ページ・軸CRUD APIは共に401で到達不能のまま（Renderダッシュ
  ボードへのアクセスが必要、Stage D ADR「本番RenderのAXIS_ADMIN_TOKEN未設定」残作業と
  同じ制約が形を変えて継続）。機能低下ではない（本番の管理機能は以前から使えない設計
  だった）が、本番で軸スタジオ・研究モードを実際に使いたくなった時点で必ず両方の
  Renderサービスへ同じ値を設定する必要がある。

### - [ ] T273. 蒸留 — 一般UIの軸カタログ縮退（Phase 4） 規模S〜M（継続的）— トリガー: 一般公開の意思決定、およびPhase 3までの利用実績の蓄積

- 背景: 目論見書3章・6章Phase 4。最終形は「言葉のレベルのつまみ数個」。一般UIの
  軸カタログを練られた少数の推定軸＋プリセットへ絞り込み、観測系の生軸は推定軸の
  内部へ吸収していく。
- 対応方針: 縮退基準（どの利用実績をもって軸を「卒業」＝カタログから隠す・吸収すると
  判定するか、目論見書8章の要判断事項）を利用データが溜まった時点で定義してから
  着手する。機能削除ではなくカタログ表示の絞り込み（軸自体はレジストリに残す）を
  基本とする。
- 完了条件: トリガー到達時に縮退基準とあわせて再定義する。

### - [x] T274. 周回ルートの逆回り（反時計回り/時計回り）候補も評価し、良い方を採用する 規模M（2026-08-24完了）

- 発端: ユーザー指摘「地図上に描画されているルートは有向グラフにできない？勾配や風向き等、
  同じルートでも左回り右回りで評点が変わるはず」（2026-08-24）。
- **調査で確認した現状**:
  1. road_graphエンジンのグラフは既に正しい有向グラフになっている
     （[domain/graph.py:312-336](../backend/app/domain/graph.py:312)）。道路の各区間は
     `-fwd`/`-bwd`という別々のedge_idを持ち、それぞれ実際の進行方向で算出した独自の
     `bearing_deg`（風向きペナルティに使用）を持つ。
  2. 勾配も進行方向で正しく符号反転している
     （[domain/attributes.py:88-124](../backend/app/domain/attributes.py:88):
     `compute_elevation_attribute`はedge自身の形状点列の順序で積算するため、`-fwd`と
     `-bwd`で獲得標高/損失標高・平均勾配の符号が入れ替わる）。
  3. **しかしルート生成（`RouteGenerator._loop_waypoints`、
     [route_generator.py:196-199](../backend/app/services/route_generator.py:196)）は
     8方位それぞれ「起点→経由地A(方位θ)→経由地B(方位θ+45°)→起点」という固定した
     回転方向でしか経路探索していない**。同じ物理的なループ形状を逆回り
     （起点→B→A→起点）で通った場合の候補は生成・比較されていない。
  4. edgeレベルの評価は方向を正しく区別できているのに、生成アルゴリズム側がその区別を
     活かせていない、という食い違いがある。
- **設計（ユーザーとの検討で確定、実装時はこの方針に従う）**: 単純に16候補（8方位×2回転）を
  全て新規にtrace_loop+評価すると、Dijkstra・DB幾何取得・GSI標高取得がいずれも倍になり
  重くなる。以下の要素分割により、**追加のDB/外部API呼び出しゼロ**で逆回り候補を合成できる。
  - **方向に依存しない（そのまま使い回せる）**: `distance_km`（物理長不変）・`road_score`・
    `stop_density`・`intersection_density`・`accident_density`・`car_stress_score`・
    `bicycle_infra_score`。いずれも`edge.edge_id`をキーに`context.surface_attributes`等
    （`prepare()`でbbox全域・両方向のedge_idぶんが取得済み）を引くだけの集計のため、
    逆方向edge_idで引いても新規フェッチ不要。
  - **方向に依存する（再計算は要るが追加I/Oはゼロ）**:
    - `wind_score`: `compute_wind_penalty`は`edge.bearing_deg`依存。逆方向edgeの
      `bearing_deg`は`road_edges`テーブルにpersisted済み・`context.graph`から既に
      取得済み（[road_graph_repository.py:1203](../backend/app/infrastructure/road_graph_repository.py:1203)）のため、参照するだけ。
    - `elevation_gain_m`/`max_gradient_percent`等: GSI標高APIを叩き直さず、順方向で
      既に取得済みの`ElevationAttribute`から代数的に導出する
      （`elevation_gain_m`↔`elevation_loss_m`を入れ替え、`max_grade`↔`min_grade`を
      符号反転して入れ替え、`start_elevation_m`↔`end_elevation_m`を入れ替え、
      `average_grade`を符号反転）。標高は地形の物理量で進行方向に依存しないため、
      この変換は厳密に正しい。
    - `geometry`・turn-by-turn `segments`: 順方向で既に`get_edges_with_geometry`済みの
      ジオメトリ点列を逆順に並べ替えるだけ（DB再取得不要）。
  - **逆回りが成立しない場合のガード**: 経路中に一方通行（`-bwd`が存在しない）edgeが
    1つでもあれば物理的に逆走不可能なため、その方位の逆candidateは生成しない。
    `context.graph`から一度（リクエスト単位）だけ`(from_node_id, to_node_id) → edge_id`
    の逆引きテーブルを作れば判定できる。多重辺（同じNode対を結ぶ別wayが複数存在する稀な
    ケース）は逆引きテーブルの後勝ちで曖昧になりうるが、既存のsparse_graph/
    NodeSpatialIndex側にも同種の簡略化があり許容範囲とした。
  - **候補の採否（ユーザー判断で確定）**: 逆回りcandidateが生成できた場合、
    レスポンスには**方位ごとに評点の良い方だけ**を採用する（両方向を別candidateとして
    追加する案は、候補リストUI・`direction_label`の重複対応が別途必要になり見送った）。
    比較指標は`distance_weighted_difficulty`（`car_stress_score`と同じ集計関数、
    segmentsの`composite_difficulty_value`を距離加重平均したもの）を両方向で算出し、
    小さい方を採用する（ルーティングコスト自体が使う軸重み付けと同じ基準のため、
    アドホックな新規スコア定義を避けられる）。
  - **実装イメージ**（`road_graph_engine.py`）: `_build_candidate`から標高取得部分を
    抽出し、順方向の`ElevationAttribute`を引数として受け取れるようにする。新設する
    `_reverse_traced_loop`（逆方向のEdgeシーケンス＋ジオメトリ合成、上記ガード判定）と
    `_reverse_elevation_attribute`（代数変換）を使い、`evaluate_loops`で各bearingについて
    順方向・逆方向（生成できれば）の両方の`_build_candidate`を呼び、
    `distance_weighted_difficulty`で比較して良い方だけを最終候補に残す。
    `candidate_identity`は方位ベースのまま変更不要（1方位1候補のため）。
- **保留する場合の影響**: 現状の8方位一方向のみのルート生成自体は正常に動作しており、
  失敗ではなく最適化機会の見送りに留まる。ただし保留し続けると、風向き・勾配が不利な
  回転方向のまま候補が提示され続け、同じ形状でより良いスコアの逆回りルートが存在しても
  ユーザーには見えない状態が続く。
- **着手タイミングに関する注記（2026-08-24）**: 設計検討中に、並行セッションが
  `backend/app/services/road_graph_engine.py`・`backend/app/domain/evaluation.py`等
  （T266〜T273、0次ハードフィルタ・二画面構想関連）を編集中であることが判明した
  （作業ツリーの安全ルールに従い、それらのファイルには一切触れていない）。本タスクの
  実装は同じファイルを触るため、並行作業のコミット完了後に着手すること。
- **実装（2026-08-24、フロント作業と競合しないbackend専用タスクとして着手）**:
  上記設計どおり実装した。並行セッション（T266〜T273）・別セッションのフロント作業
  （T292）はいずれも当該コミット完了後だったため、作業ツリーの安全ルール上の制約は
  解消済みだった。
  - `_RoadGraphContext`へ`node_pair_index: dict[tuple[str,str], EdgeLike]`
    （`(from_node_id, to_node_id) → Edge`の逆引き表）を追加、`prepare()`で
    `context.graph`から1リクエストにつき1回だけ構築する。
  - `_reverse_traced_edges(edges_in_path, node_pair_index)`: 順方向経路を逆順に辿る
    Edge列を構築。`node_pair_index`で逆方向Edgeの存在・トポロジ（`bearing_deg`等）を
    引き、geometryは順方向Edge自体のhydrate済みgeometryを反転（DB再取得なし）。
    逆方向Edgeが1つでも存在しない（一方通行）場合はNone。
  - `_reverse_elevation_attribute`/`_reverse_elevation_attributes`: 順方向で
    既に取得済みの`ElevationAttribute`から代数変換（獲得標高↔喪失標高・始点/終点標高の
    入替、平均勾配の符号反転、最大/最小勾配の符号反転＋入替）で逆方向の値を導出。
    GSI標高APIは再呼び出ししない。
  - `_build_candidate`を`edges_in_path`/`elevation_attributes`を引数化する形へリファクタリング
    （以前は`traced.data`と自前のGSI問い合わせ結果を直接使用）、`async`だった標高取得を
    `_fetch_elevation_attributes`へ分離し`_build_candidate`自体は同期関数へ単純化。
  - `_route_composite_difficulty`/`_pick_better_candidate`: 順方向・逆回り候補それぞれの
    `distance_weighted_difficulty`（`RouteGenerator._with_overall_difficulty`と同じ指標だが、
    エンジン内部で方位ごとの採否を決めるタイミングが異なるため独立実装）を比較し、低い方を
    採用（比較不能な逆回りは順方向へフォールバック、安全側）。
  - `evaluate_loops`は方位ごとに`_build_best_candidate`（上記を束ねる新設メソッド）を呼ぶ形へ
    変更。`candidate_identity`は方位ベースのまま変更なし。
  - 既存テストの`_RoadGraphContext`直接構築1箇所へ`node_pair_index={}`を追加（既存の
    テストグラフフィクスチャはいずれも逆方向Edgeを持たないため、新ロジックは常に
    「一方通行」判定となり順方向のみを返す＝既存の期待値に無変更で回帰しないことを確認）。
  - 新規テスト12件（`_build_node_pair_index`・`_reverse_traced_edges`の正常系/一方通行ガード・
    `_reverse_elevation_attribute`の代数変換/全欠損保持・`_reverse_elevation_attributes`の
    欠損伝播・`_route_composite_difficulty`/`_pick_better_candidate`の単体・
    `_build_best_candidate`の統合確認2件[追い風方向への逆回り採用／一方通行での順方向
    フォールバック、東向き経路への最大強度向かい風で決定的に検証]）を追加。
  - backend全1106件green。docs/architecture.md「Road Graphエンジンの探索性能」節へ
    T274の動作を追記済み。
- 完了条件: 実装・テスト（逆回り判定のガード条件・代数変換の正当性・比較ロジック）を
  完了。上記参照。

### - [x] T275. Tailwind CSSの採否を決定する（現状は未使用のまま依存関係にのみ存在） 規模S（調査・意思決定）（2026-08-25、T299で決着）

- 背景: 2026-08-24、T270作業中のユーザー質問（「Radix/Tailwindは実装コスト低減や保守性の
  向上につながっているか」）への回答時に調査して判明。`frontend/package.json`に
  `tailwindcss`/`@tailwindcss/postcss`が依存関係として存在し`globals.css`からも
  importされているが、実際のコンポーネント（`.tsx`）でTailwindのユーティリティクラス
  （`flex`/`gap-`/`bg-`等）を使っている箇所は**リポジトリ全体でゼロ**。全コンポーネントは
  一貫してCSS Modules＋手書きCSSカスタムプロパティ（`--space-*`/`--color-*`等、
  `globals.css`定義）で実装されている。Next.jsのデフォルトスキャフォールドが自動同梱した
  ものがそのまま残っているだけと推測され、意図して導入・活用された形跡がない。
  一方Radix UI（`@radix-ui/react-*`）は`Disclosure`/`FieldLabel`/`LevelPicker`/`LayerChip`等
  複数箇所で実際に採用され、キーボード操作（roving tabindex）・Popover位置計算・
  トグル押下等の自前実装を置き換えて明確にコスト削減できている（対比としてRadixは
  「効果が出ている」と評価できる状態）。
- 対応方針（実装前にユーザーと方式を決定する）: 既存のCSS Modules資産（多数のコンポーネント
  × module.css）をどう扱うかをコストと天秤にかけて判断する。候補は (a) Tailwindを
  依存関係から撤去し「使わない」と明文化してCSS Modules一本化を継続、(b) 新規コンポーネント
  のみTailwindを使い既存CSS Modulesは段階的に置き換えない併用方針、(c) 全面的な
  Tailwindへの移行（既存CSS Modules資産の書き換えコストが規模に対して大きい可能性が高く、
  現時点では推奨しない）。
- **再調査（2026-08-25）**: Tailwindユーティリティクラスの使用箇所は引き続きゼロ
  （`className`にTailwind系パターンを含む`.tsx`を`frontend/src`全体で検索し確認）。
  ユーザーから(c)（全面移行）も候補として検討したいとの意向があったため、規模を実測した:
  CSS Modulesは`frontend/src`配下**30ファイル・合計3,302行**、それらを参照する`.tsx`は
  **33個**。(c)は既存資産をすべて書き換える大規模作業であり、かつ並行するT292の
  フロント移行作業（26ファイル、`carStressExpression.ts`等の置き換え）ともファイル面で
  広く重なるため、現時点では衝突リスクが高いと判断した。
- **保留（2026-08-25）**: (c)の是非は改めて別途検討するとのユーザー判断により、
  (a)/(b)/(c)いずれの方針決定も保留した。保留中は`tailwindcss`/`@tailwindcss/postcss`が
  未使用のまま依存関係に残り続け、`npm audit`等の脆弱性スキャン対象が不必要に増える
  程度の実害に留まる（機能上の支障は無い）。**(c)を検討する場合は、T292フロント移行
  （26ファイル）の完了後に着手すること**（同時進行するとCSS Modules⇄Tailwindの書き換えと
  car_stress関連コンポーネントの置き換えが同一ファイルで衝突しうる）。
- 完了条件: 方針を決定し、`docs/architecture.md`（技術選定表）へ明記する。(a)を選ぶ場合は
  `tailwindcss`/`@tailwindcss/postcss`の依存関係除去と`globals.css`のimport除去も行う。
  (b)を選ぶ場合はCSS ModulesとTailwindの使い分け基準（どういう場合にどちらを使うか）を
  明文化する。(c)を選ぶ場合は30ファイル・3,302行のCSS Modules書き換え計画を別タスクとして
  起票する。
- **決着（2026-08-25、T299）**: (b)（新規UIはTailwind+`components/ui/`を優先、既存CSS
  Modulesは機能改修のタイミングで段階移行し一括置換はしない）を採用した。Radix UI +
  `class-variance-authority`/`clsx`/`tailwind-merge`によるshadcn風の自前コンポーネント層
  `frontend/src/components/ui/`（Button/Input/Card/Dialog/Checkbox）を新設し、使い分け基準・
  Design Token一覧は`docs/architecture.md`技術選定表経由で`docs/frontend-design-system.md`へ
  明文化した。効果実証として、定量調査で「本当に同一実装」と確認できた重複7箇所
  （カード状コンテナ2・純レイアウト3・送信ボタン1・CSS Modulesファイル丸ごと削除1）も
  実際に移行した。(c)全面移行の是非は引き続き別途判断とする（本タスクでは判断しない）。
  詳細はT299参照。

### - [x] T276. registry.py（表示用レジストリ）とAXIS_DEFINITIONS（Stage D）の軸ラベル重複を解消する 規模S（2026-08-24完了）

- 背景: T270完了報告でユーザーから「2つのレジストリ未統合」について「意図的に据え置き」と
  説明したところ、その意図を問われた。実態を確認すると、これは重み付けした設計判断ではなく
  T270のタスク文に統合が明記されていなかったために単に着手していなかっただけで、しかも
  T269の実装メモで自ら「T270で統合する想定」と書いていた宿題を果たしていなかった
  （T270エントリ完了時の見落とし）。ユーザー指示によりその場で着手した。
- 現状把握: `domain/registry_defaults.py`（`registry.py`向けの既定登録、T137）の6軸
  （gradient/surface_q/stop_density/car_stress/night/accident）は、`AxisDisplaySpec.label`
  （地図レイヤーパネル・凡例が表示する軸名）を`AXIS_DEFINITIONS[axis_id].label`
  （T269でDB化、軸スタジオでGUI編集可能）と**完全に同じ文字列**で独立して手書きしていた
  （例:「車の圧迫感」を2箇所で個別に宣言）。一方`AxisSpec.description`
  （開発者向けの長い技術説明）・`AxisDisplaySpec.category`（地図レイヤーパネルの
  グルーピング用「terrain」「road」「trafficSafety」）は`AXIS_DEFINITIONS`側の
  `description`（ユーザー向けの短い説明）・`category`（軸の性質「観測」「推定」「動的」）
  とは対象読者・意味が異なる別概念と判断し、統合対象から除外した（同じ「category」という
  語を使うが指す軸が異なる点に注意）。
- 対応: `registry_defaults.py`の6軸登録で`AxisDisplaySpec(label="車の圧迫感", ...)`のような
  ハードコードをやめ、`AxisDisplaySpec(label=AXIS_DEFINITIONS["car_stress"].label, ...)`
  という参照へ置き換えた（`AXIS_DEFINITIONS`をimport）。`test_registry_defaults.py`へ
  `test_registry_axis_display_labels_match_axis_definitions`を追加し、この参照が将来
  また手書きの別文字列へ差し戻されないことを機械的に確認する（既存の
  `test_registry_axis_ids_match_axis_definitions`と同じ「片方だけ更新しても気づかない
  死角」対策のパターン）。
- **この対応が解決しない範囲（重要）**: `register_defaults()`はビルド時
  （`export_openapi.py`）とテストのみで呼ばれ、FastAPIアプリ起動時には呼ばれない
  （`registry_defaults.py`モジュールdocstring参照）。そのため今回の統合は
  「Pythonコード上の既定値が一致する」ことを保証するのみで、**軸スタジオでDBの`label`を
  GUI編集しても、地図レイヤーパネル・`axis-catalog.json`（ビルド時生成物）側のラベルは
  再デプロイまで追従しない**（T270「残作業」3・Stage D ADR「DB編集がこの生成物へ反映
  されるのはStage E以降の課題」と同根の制約が依然として残る）。真に動的反映させるには、
  地図レイヤー側（`SECONDARY_AXES`/`primaryAttributes.ts`等、`axis-catalog.json`静的importの
  複数箇所）を`useAxisCatalog`と同様の動的フェッチへ置き換える別タスクが必要
  （規模が大きく、地図UI一式に触れるリスクを伴うため本タスクのスコープ外とした）。
- 検証: `test_registry_defaults.py`全13件green（新規1件含む）、backend全1150件green、
  `export_openapi.py`再生成で`axis-catalog.json`が無変化（＝統合前後で値が完全一致、
  意図通りの無害な置き換え）であることを確認。フロントtsc green（生成物差分なし）。

### - [x] T277. 材料カタログをbackend正式レジストリ化し軸コンポーザーへ動的連携する 規模S〜M

- 背景: T276に続き「軸を編集することで地図上の推定アイコンを増減できるか」という
  ユーザー質問を調査した結果、(1) `registry.py`の軸集合と地図タイルのMVT焼き込み
  プロパティを調べたところ、`kind="ramp"`軸は`tile_inputs`（材料→tileプロパティの
  線形結合）から`MapOverlayControls`/`axisLayers.ts`が**既存コードのまま**汎用レイヤーを
  自動生成できること、アイコンも`SECONDARY_AXIS_ICONS[axisId] ?? AxisRampIcon`という
  汎用フォールバックが既にあり専用アイコン無しでも壊れないことが判明した。(2) 9材料中
  5〜6件がMVTタイルへ焼き込み済み（`surface_good`/`stop_per_km`/`intersection_per_km`/
  `accident_per_km`/`tunnel`、`lit`は符号反転要）で、`gradient_percent`/`wind_penalty`
  （タイル非焼き込み・動的取得）・`car_stress_level`（レシピ合成値）はramp化不可と
  判明した。(3) この調査中、ユーザーから「材料は今後システムメンテナンスで増減されうる
  ものとして設計してほしい。ただし材料自体をGUIでメンテナンスする必要はない。
  タイルに焼き込まれた状態である材料を取得し、推定要素（軸）に紐づけてCRUDできることが
  求めている点」という設計要件が示された。これは`frontend/src/lib/axisMaterialsCatalog.ts`
  （T270で作った、9材料をフロントに手書きしたリスト）自体が「システムメンテナンスで
  増減するものをフロントへ固定書きする」という、まさに避けるべき重複だったことを意味する。
- 対応方針:
  1. backendに材料カタログの正式レジストリを新設する（`domain/axis_definitions.py`への
     追加、または新規`domain/material_catalog.py`。案は着手時に決定）。各材料は
     `material_id`・`label`・`dtype`（numeric/boolean）に加え、内部用（フロントへは
     非公開）の`tile_property`（MVT焼き込み済みプロパティ名、無ければNone＝ramp化不可）・
     `tile_property_inverted`（no_lit⟵litのような符号反転フラグ）を持つ。
     `AXIS_MATERIAL_OPTIONS`（axisMaterialsCatalog.ts）と同じ9件を初期データとして移植する。
  2. 新規公開エンドポイント`GET /api/material-catalog`（認可不要、`material_id`/`label`/
     `dtype`のみ返す。`tile_property`系はbackend内部でのみ使う想定——T278（下記の地図表示
     ルール自動生成タスク、未起票）が消費する）。
  3. 管理API（`axis_admin.py`）の作成・更新経路に軽い検証を追加する: 送信された
     `material`（terms/flags/categoricalのmaterial）が材料カタログに存在しない場合は
     422で拒否する（現状は任意文字列を受け付けてしまう）。
  4. フロント: `services/materialCatalogApi.ts`＋`hooks/useMaterialCatalog.ts`
     （`useAxisCatalog`と同じ「マウント時1回取得、取得失敗時は静的フォールバック」
     パターン）を新設し、`components/AxisStudio/AxisComposer.tsx`をこのhook経由に
     置き換える。`lib/axisMaterialsCatalog.ts`はフォールバック定数としてのみ残す
     （またはhook内へ統合し削除）。
  5. **材料自体を追加・編集・削除するGUIは作らない**（ユーザー明示、材料の追加は
     引き続きbackendコード変更＋デプロイで行う、既存ADR「新素材の追加は引き続き
     バックフィルが必要」原則のまま）。
- 完了条件: `GET /api/material-catalog`が材料一覧を返し、軸コンポーザーの材料選択
  ドロップダウンがこのAPIから動的取得した値で構成されること。backend側に材料を
  1件追加（テスト用の一時的な追加で可）すると、フロントのコード変更・再デプロイなしに
  軸コンポーザーの選択肢に現れることを実機確認する。存在しない材料名を指定した
  軸作成・更新が422で拒否されることをテストで確認する。
- 依存: なし（T270完了後の独立タスクとして着手可能）。後続のT278（地図表示ルール
  自動生成、軸集合の同期・kind=ramp自動判定・SECONDARY_AXES動的化。未起票、
  T277完了後に別途起票する）の前提になる。
  **kind自動判定の手動オーバーライド要否はユーザー判断で解消済み（2026-08-24）**:
  `tile_property`を持つ材料（ramp化技術的に可能な材料）を使う軸は一律`kind="ramp"`とし、
  backend側にnoneへの手動オーバーライドは設けない。`surface_q`のような「技術的には
  ramp化可能だが既存の道路情報レイヤーと重複するため出したくない」というケースは、
  地図レイヤーパネル側（`MapOverlayControls`等）にレイヤーの表示/非表示切替を用意する
  ことで運用回避する（＝重複回避はUI層の関心事とし、backendのkind導出ロジックを
  複雑化させない）。T278起工時にこの方針で`kind`自動導出ルールを設計すること。
- 実装メモ（2026-08-24完了）: 対応方針1〜5をそのまま実装。新規`domain/material_catalog.py`
  （`MaterialSpec`/`MATERIAL_CATALOG`、既存9材料を移植）・新規`api/routers/material_catalog.py`
  （`GET /api/material-catalog`、`tile_property`系は非公開）・`axis_admin.py`へ
  `_check_materials_are_known`バリデータ追加（未知材料は422）。フロントは新規
  `services/materialCatalogApi.ts`・`hooks/useMaterialCatalog.ts`（`useAxisCatalog.ts`と
  同型：マウント時1回取得、失敗時は静的フォールバック）を追加し、`AxisComposer.tsx`の
  `emptyDraft`/`draftFromExisting`にmaterialOptions引数を追加してhook経由の材料一覧を
  注入する形へ変更。`lib/axisMaterialsCatalog.ts`は削除せず「フォールバック専用」へ
  役割を縮小（doc commentのみ更新）。OpenAPI再生成（`export_openapi.py`→
  `npm run generate:api`）で`MaterialCatalogEntry`/`MaterialCatalogResponse`型を
  frontend生成物へ反映。検証: backend全1151件green（新規テスト
  `test_create_returns_422_for_unknown_material`含む）、frontend tsc/eslint green、
  vitest全516件green、backend/frontend実サーバーでE2E確認
  （`GET /api/material-catalog`が9材料を返す、軸スタジオの材料ドロップダウンが
  API由来のラベルで構成されることをread_page/get_page_textで確認）。

### - [x] T278. 地図表示ルール(kind=ramp)の自動導出・軸集合の同期 規模M

- 背景: T277完了時点で、軸スタジオ（`/admin`）でDBへ新規登録した軸は`GET /api/axis-catalog`
  （T269）経由で一般向けルート設定画面には現れるが、**地図（レイヤーパネル・凡例・
  地図チップ）には一切現れない**——地図側は`registry.py: all_axes()`が書き出す
  build時静的生成物`axis-catalog.json`（`export_openapi.py`）を単一ソースとしており、
  `registry_defaults.py`に手書き登録された既存6軸（`wind`除く7軸中6軸）以外を知らない
  ため。またT276で調査した際、既存の`surface_q`軸は材料`surface_good`が
  タイルへ焼き込み済み（ramp化技術的に可能）にも関わらず「既存の道路情報レイヤーと
  重複するため」という理由で`kind="none"`に手書き固定されていた。この「技術的には
  ramp化可能だが手で`none`に固定している」という状態を、ユーザー判断（2026-08-24、
  T277完了報告時）で「一律`kind="ramp"`にし、重複回避は地図レイヤーパネル側の表示/
  非表示切替で運用する」という自動導出ルールへ統一する方針が決まった
  （T277エントリ「依存」節に記録済み）。
- 調査で判明した制約（重要）:
  1. `registry.py`の`axes[].inputs`（一次属性=OSM生タグ単位の参照。T167の「推定軸ON→
     観測レイヤー連動ON」・T146の「軸の材料一覧表示」が依存）と、`AXIS_DEFINITIONS`の
     `materials`（評価直前まで解決済みの値単位）は別の語彙で、機械的に統合できない
     （T12関係、docs/decisions/t221-axis-registry.md記載どおり）。そのため
     **`axis-catalog.json`の生成元をregistry.pyからAXIS_DEFINITIONSへ丸ごと差し替える
     ことはできない**——軸スタジオ作成軸は`inputs=[]`（材料一覧表示無し）で妥協する。
  2. `事故密度`軸の材料`accident_count_per_km_year`は年正規化済み（`accident_import_runs`
     の収録年数で除算、実行時に変動しうる）だが、タイル焼き込み済みの`accident_per_km`は
     年正規化前の生値。両者のスケール変換係数は静的に持てないため、**`accident`軸の
     ramp表示（thresholds等）は自動導出の対象外とし、`registry_defaults.py`の
     既存手書き値をそのまま維持する**。
  3. `停止密度`軸は2材料の重み付き線形結合（`stop_count_per_km` + 0.3×
     `intersection_count_per_km`）で、既存thresholds`[1,2,4]`は統計的な経験則であり
     単純な折れ点流用では再現できない。**複数材料の重み付き結合を伴う軸は自動導出の
     対象外**とし、既存の手書き値を維持する（stop_densityはこれに該当し変更しない）。
  4. `車ストレス`軸は材料`car_stress_level`がタイル非依存（レシピ合成値）のため
     自動的にramp化対象外と判定される（既存の`kind="bespoke"`を維持、変更不要）。
  5. MVLタイルの真偽値プロパティ（`surface_good`/`lit`/`tunnel`）はMapLibre上で
     `["==",["get","tunnel"],true]`のような真偽比較で読む必要があり、既存の
     `buildAxisRampValueExpression`（`Σ property×weight`の数値線形結合前提）では
     直接扱えない。`AxisTileInput`/`TileInputSpec`を拡張し、真偽値材料
     （`boolean`/`invert`/`true_value`/`false_value`）に対応させる必要がある。
- 対応方針（自動導出が安全に成立するケースに限定する）:
  1. 新規`domain/axis_display.py: derive_ramp_inputs(definition) -> RampInputs | None`。
     `AxisDefinition.materials`が全て`MATERIAL_CATALOG`でtile_property保持済みの場合のみ
     ramp化を試み、shape種別ごとに以下だけを扱う（それ以外は`None`＝自動導出対象外）:
     - `CategoricalShape`（真偽値材料1件）: 2値の中間点を閾値とする2段階ramp。
     - `FlagSumShape`（真偽値フラグN件）: 達成しうる合計値（部分和の全組合せ、cap適用後）の
       隣接中間点を閾値とする。
     - `BreakpointLinearShape`で**単一材料・weight=1.0・preprocess="identity"**の場合のみ:
       既存breakpointsのx値（先頭除く）をそのまま閾値に流用。複数材料・非等倍weight・
       abs前処理は対象外（制約3・既存stop_density等を変更しないため）。
  2. `registry.py: TileInputSpec`へ`boolean: bool = False`・`invert: bool = False`・
     `true_value: float = 0.0`・`false_value: float = 0.0`を追加（数値材料は`weight`のみ
     使用、真偽値材料は`boolean=True`で`true_value`/`false_value`を使用、`weight`は無視）。
  3. `registry_defaults.py`: `surface_q`（材料`surface_good`）と`night`
     （材料`no_lit`・`has_tunnel`）の`display`を`derive_ramp_inputs()`経由の
     `kind="ramp"`へ置き換える（`category`・`label`・既存の`note`文言は手書きのまま
     維持、`tile_inputs`/`thresholds`のみ自動導出値に差し替え）。`gradient`
     （タイル非依存で自動的に対象外）・`stop_density`（制約3）・`car_stress`
     （制約4）・`accident`（制約2）は変更しない。
  4. `export_openapi.py`: `axis-catalog.json`の`axes[]`生成を、`registry.all_axes()`に
     加えて「`AXIS_DEFINITIONS`にあるが`registry.py`未登録の軸」も走査し、
     `derive_ramp_inputs()`が`None`を返さない（＝ramp化可能と判定された）場合のみ
     `inputs=[]`・`output_range=(0,100)`・自動生成`display`（`category="trafficSafety"`
     既定、`note`はdefinition.descriptionを流用）で追加する。`None`の場合は追加しない
     （地図に出ない＝現状と同じ「専用レイヤー無し」のまま、regressionにならない）。
     これにより将来軸スタジオが作る新規軸のうち、真偽値材料またはシンプルな単一数値材料の
     ものは再デプロイ後に自動で地図へ現れるようになる（複雑な軸は従来どおり地図無しのまま
     グレースフルに動作）。
  5. フロント`components/Map/axisLayers.ts`: `AxisTileInput`に`boolean?`/`invert?`/
     `trueValue?`/`falseValue?`を追加し、`buildAxisRampValueExpression`が
     `boolean=true`の入力を`["case", 真偽比較, trueValue, falseValue]`で組み立てる分岐を
     追加する（既存の数値`Σproperty×weight`分岐とは独立、後方互換）。
  6. フロント`components/Map/secondaryAxes.ts`: `SECONDARY_AXIS_LAYER_IDS`（現状
     car_stress/stop_density/accidentの3件を手書き固定）を「`display.kind==="ramp"`なら
     `axisMapLayerId(axis_id)`を自動算出、bespoke（car_stress）のみ引き続き手書き」という
     ルールへ一般化する（将来ramp軸が増えるたびにこの辞書へ追記する手間を無くす、
     T278の「SECONDARY_AXES動的化」の一部）。`SECONDARY_AXIS_PROXY_HINTS`から
     `surface_q`・`night`のエントリを削除する（両軸ともkind="ramp"に変わり専用レイヤーを
     持つため、「地図表示なし」の代役案内は不要になる）。
  7. `MapView.tsx`・`mapLayers.ts`・`staticAttributeLayers.ts`は変更不要（`RAMP_AXES`を
     汎用的に走査する既存実装がそのまま新しいramp軸2件を拾う設計、調査で確認済み）。
- 完了条件: `surface_q`・`night`が地図の推定指標レイヤーとしてON/OFFトグル・凡例付きで
  表示され、`stop_density`/`accident`/`car_stress`/`gradient`の既存表示が変更前と
  完全に一致すること（回帰無し）。backend/frontend双方のテストが全てgreen。
  実機ブラウザでsurface_q・nightレイヤーのON/OFF・色分け・凡例クリック絞り込みを確認する。
- 依存: T277（材料カタログ、完了済み）。
- 実装メモ（2026-08-24完了）: 対応方針1〜7をそのまま実装。新規`domain/axis_display.py:
  derive_ramp_inputs()`（Categorical/FlagSum/単一材料BreakpointLinearのみ自動導出、
  部分和ベースの閾値算出込み）・`MaterialSpec.tile_property_needs_runtime_scale`
  （accidentを明示的に自動導出対象外とマーク）を追加。`registry_defaults.py`の
  surface_q/nightの`display`を自動導出値へ差し替え、`export_openapi.py`のaxis-catalog.json
  生成を「registry.py未登録だがramp化可能な軸」も含める形へ拡張。フロントは
  `axisLayers.ts`（`AxisTileInput`へboolean/invert/trueValue/falseValue追加、
  `buildAxisRampValueExpression`が`["case",...]`分岐を追加）・`secondaryAxes.ts`
  （`SECONDARY_AXIS_LAYER_IDS`をkind="ramp"なら自動算出する一般化、surface_q/nightの
  proxyHintエントリ削除）・`mapLayers.ts`（unit=""時の空`[]`表示を抑止する軽微な修正）を
  変更。`MapView.tsx`等は調査どおり無変更で新axisを拾えた。
  検証: backend全1160件green（新規`test_axis_display.py`7件＋`test_registry_defaults.py`
  2件含む）、frontend tsc/eslint/vitest 517件green（`MapOverlayControls.test.tsx`・
  `MapLayersPanel.test.tsx`の「surface_q/nightは専用レイヤー無し」という旧前提のテストを
  「他のramp軸と同じ実レイヤーセクションになる」という新前提へ更新）。実サーバーで
  `/api/material-catalog`・軸スタジオの材料ドロップダウン・地図の推定指標グループを
  確認し、舗装質・夜間が停止密度・事故密度と同じ「ON/OFF可能なタイル」として現れる
  （disabledの情報タイルではなくなる）ことをアクセシビリティツリー・コンソール
  エラー無し・ネットワークログで確認した。**ただし本セッションのBrowser paneが
  非表示（compositing不可）の制約により、地図キャンバスへの実際のタイル取得・
  色分けピクセル描画そのもの（MapLibreの実際の色分け結果）は確認できていない**——
  MapLibre style自体の妥当性（`["case",...]`式が無効ならスタイル読込時に例外が出る）は
  コンソールエラー無しで確認済みだが、これは「地図が実際に正しい色で塗られるか」の
  代用にはならない。次にBrowser paneが表示可能なセッションで、舗装質・夜間の
  色分け・凡例クリック絞り込みを実ピクセルで再確認することが望ましい。
- **レビュー修正（2026-08-24、T268〜T278の追加コミット分を対象に`/code-review`実施）**:
  上位10件を修正: (1) `export_openapi.py`がAXIS_DEFINITIONSをDBから再読込しておらず
  「軸スタジオで作った軸が再デプロイ後に地図へ自動反映される」という上記の完了条件が
  実は満たされていなかった致命的バグを修正（DB接続失敗時は`refresh_axis_definitions`と
  同じ安全側フォールバックへ倣う）。(2) OpenAPI/api.d.tsのX-Admin-Token残存ドリフトを
  再生成で解消。(3) 軸定義payloadのdtype（numeric/boolean）と形状種別の不整合を
  バリデーションで拒否するよう追加。(4) `surface_good`未分類路面がNULL→「悪い」評価に
  誤判定されていたバグを`has_unknown_fallback`で修正（灰色「不明」表示に変更）。
  (5) `AxisDefinitionResponse`が書き込み専用バリデータを継承し、削除済み材料を参照する
  既存軸の一覧/取得APIが500になる問題を、フィールド共有の基底クラス分割で修正。
  (6) `BreakpointLinearShape`のramp自動導出が符号反転(`tile_property_inverted`)を
  無視していたため、対象外（`None`）を返すガードへ修正。(7) docs/architecture.md・
  admin/page.tsxのX-Admin-Token時代の古い記述をT272後の実態へ更新。(8) `proxy.ts`の
  Basic認証比較を`timingSafeEqual`によるタイミング攻撃耐性のある比較へ修正。
  (9) `AxisRegistryAdminService.create`/`update`の冗長なDB往復（list_all()+get()の
  2回発行）を`list_all_with_sort_order()`新設で1回へ集約。(10) `FlagSumShape.flags`に
  `Field(max_length=12)`を追加し組合せ爆発を防止。加えてユーザー指示により、
  DebugConsole（地図イベントのライブログ）がT270で`/admin`へ移設された結果
  「`/admin`には地図が無くログがタブ間で共有されないため実質機能しなくなっていた」
  問題を、「`/`=地図を操作しながら見るライブログ本体」「`/admin`=デバッグモードの
  設定・集計」という役割分割で再設計・修正した。上位10件以外の候補6件も精査し、
  `useRecipeOverride.ts`のstorageKey省略時の非永続分岐（T270以降、本番の全呼び出し元が
  storageKeyを渡すためテスト以外では到達しない死んだ分岐だった）をstorageKey必須化で
  簡略化。残り5件（排他チェックの二重実装・TileInputSpecのデュアルモード・
  AxisComposerのDraft構造・proxy.ts/backend二重Basic認証・runtime_scaleフラグ）は
  既存設計が妥当と判断し見送った。検証: backend全1173件green、frontend
  tsc/eslint/vitest全519件green、Playwright(headless)でDebugConsole移設後の
  トップページ・`/admin`両方を実機確認。

---

## 全体最適レビュー第8回の起票（2026-08-24・ユーザー承認済み）

全ソースコード・DB設計をゼロから再読した総合診断レビュー
（[.claude/commands/review/history/2026-08-24_overall.md](../.claude/commands/review/history/2026-08-24_overall.md)、
対象コミット`fc7bd5a`、総合スコア83/100）の指摘を起票する。起票案A〜Fに加え、
ユーザー指示「知見として見つけたものもタスク化・掘り下げするべきものがないか再チェック」を
受け、レポート本文に留めていた知見4件（T285〜T288）もトリガー付きで正式起票した。

### - [x] T279. OpenAPI生成物ドリフトの解消＋CI状態確認＋コミット前検知の機械化判断〔P1〕規模S（2026-08-24完了）

- 背景: レビューで実測検出（レポートF-1）。HEAD `fc7bd5a`自身が`api/routers/axis_admin.py`の
  `AxisDefinitionResponse`へdocstringを追加（500バグ修正の継承分離）しながら
  `export_openapi.py`再生成を行わなかったため、worktreeで再生成すると
  `frontend/src/types/generated/openapi.json`に差分1件（`description`追加）が出る。
  CLAUDE.mdの同一コミット同期ルール（T180・T185・T218の実績を受けT196で明文化、
  2026-08-23にCLAUDE.mdへ昇格）の**4回目の類型再発**であり、ルール明文化・CI検知
  （api-contractジョブ）導入後の初再発である点が重い。
- 内容:
  1. `export_openapi.py`→`npm run generate:api`を実行し、生成物差分をコミットする
     （`git diff --exit-code -- frontend/src/types/generated/`クリーンを確認）。
  2. GitHub Actionsの`fc7bd5a`のapi-contractジョブ結果を確認する（赤である可能性が高い。
     ローカルにgh CLIが無く未確認のため、確認手段の整備〔gh導入またはブラウザ確認の
     手順明記〕も本タスクに含める）。
  3. 再発防止の機械化を判断する: 「気をつける」型のルールは4回破られた実績があるため、
     ローカルのコミット前検知（pre-commitフック等でbackend側API関連ファイル変更時に
     生成物ドリフトをチェック）の導入要否を決め、判断理由ごと記録する。導入しない場合も
     「なぜCIだけで足りるとするか」を明記する（設計原則10）。
- 対応:
  1. `export_openapi.py`→`npm run generate:api`を実行し再生成。差分はレビュー実測
     どおり`AxisDefinitionResponse`のdocstring1件のみ（`openapi.json`・`api.d.ts`）で
     他生成物は無変化。フロントtsc green（型整合確認）を確認しコミット。
  2. GitHub Actions公開API（`/repos/{owner}/{repo}/actions/runs`、認証不要）で`fc7bd5a`の
     CI実行を確認したところ、**予測どおりapi-contractジョブが`git diff --exit-code`で
     失敗（exit code 1）していた**（ユーザーが実際のCIログを提示し裏取り）。ローカルに
     `gh` CLI未導入のため、この公開API直叩きを今回の確認手段として採用した。
  3. **機械化判断: ローカルpre-commitフックを導入する（4回目の再発を受け「気をつける」型
     ルールでは不十分と判断）**。`scripts/pre-commit-api-contract.sh`（リポジトリへコミット、
     版管理下）を新設し、このワークツリーの`.git/hooks/pre-commit`へ手動配置して有効化した。
     設計判断: (a) ステージ済みファイルが`backend/app/api/`・`backend/app/domain/`・
     `backend/app/config.py`・`backend/scripts/export_openapi.py`に該当する場合のみ実行
     （実測約12秒のコストをdocsのみ・frontend UIのみのコミットに負わせない）。
     (b) venv・npmが見つからない環境（並行セッションの`git worktree`で`.venv`が
     複製されない構成を含む。CLAUDE.md「作業ツリーの安全」の並行セッション前提）では
     警告のみでコミットを止めないsoft-fail。差分が実際に検出された場合のみexit 1する。
     (c) `git config core.hooksPath`は変更しない（CLAUDE.md「git configを更新しない」
     方針に従い、このワークツリーへのファイル配置のみに留めた）。他のworktree・clone・CI
     環境には影響しない。**同種のリスクを持つ他の手動同期ペア（タイル世代番号・
     region-tile-config.json等）への同型フック拡張は本タスクのスコープ外**（まず
     OpenAPI契約1件で運用実績を積んでから判断する）。
- 完了条件: 生成物差分ゼロのコミット（済）＋CI状態確認（済、失敗を確認）＋機械化の判断記録（済）。

### - [x] T280. 材料供給の1本道短縮（軸スタジオの「材料の天井」の構造対策）〔P2〕規模M〜L（内容1完了・2026-08-26）

- 背景: レビュー最重要指摘（レポートF-2）。Phase 2〜3（T270〜T272）で軸のGUI作成・統治
  基盤は完成したが、①9材料すべてが既存7軸に排他帰属（`check_material_exclusivity`、
  shared概念なし）、②公開済み軸は不変・削除不可（T271）、③GUI作成軸は表示レジストリ
  （`registry.py`、ビルド時静的・手書き登録）に載る経路が無い——の3制約が重なり、
  **軸スタジオから実用的な新軸を1つも作れない**。天井を破る唯一の変数は材料の供給で、
  現状の新材料追加はコード変更＋デプロイに加え、タイル焼き込みCASE式
  （`_ROAD_SURFACE_TILE_MVT_SQL`）・タイル世代・`compute_edge_costs_bulk`の抽出フェーズ
  （`evaluation.py:598〜`、材料ごとの手書きnumpy配列化）の追記を要する長い経路になっている。
- 内容（候補、着手時に設計判断）:
  1. **【完了】** 抽出フェーズの`MATERIAL_CATALOG`駆動化（材料id→抽出方法の宣言から numpy配列構築を
     導出し、材料追加時の手書き箇所を減らす）。T221 Stage B以降（レジストリ駆動化）の
     残り区間・スカラー/配列二重実装の解消（第7回C-1）と同一方向のため、統合して
     優先度を再評価する。
  2. **【調査の結果、着手見送り】** タイル焼き込みプロパティの宣言化またはコード生成の検討
     （CASE式手書きの削減）。
  3. **【今回スコープ外、ユーザー判断（2026-08-26）】** `shared`材料の導入判断: 例えば
     `gradient_percent`を複数軸で参照可能にする方が、新材料の追加より早く天井を破れる
     可能性がある。排他帰属原則（目論見書）との整合をユーザーと確認のうえ決める必要が
     あり、着手前の質問でユーザーが「①+②のみ」を選択したため今回は行わない。
     再着手する場合はこのタスクを再オープンする。
- 内容1の実装（2026-08-26）: `domain/material_catalog.py`の`MaterialSpec`へ`extractor`
  （`MaterialExtractionContext -> 生値`の関数）と`bool_default`（boolean材料の欠損を
  bool配列のFalseとfloat配列のNaNのどちらへ落とすかの宣言）を追加し、既存14材料の
  抽出ロジック（`tag_value_is`/`parse_maxspeed`/`parse_lanes`/
  `classify_bicycle_infrastructure`/`classify_osm_surface`/`cycleway_class`呼び出し）を
  `domain/evaluation.py: compute_edge_costs_bulk`の手書きループから1材料1関数へ分解して
  移設した。`compute_edge_costs_bulk`側は`MATERIAL_CATALOG`を汎用的に走査するだけになり、
  材料追加時の変更箇所は`material_catalog.py`1箇所に減った。
  - **完了条件の実証**: 以前は`MATERIAL_CATALOG`に登録済みでも`evaluation.py`に専用コードが
    無く実際には抽出されていなかった4材料（bridge・smoothness・cycleway_class・
    生surfaceタグ）に`extractor`を追加しただけで、`evaluation.py`を一切変更せず
    抽出可能になったことを`tests/test_material_catalog.py`で確認した。
  - **設計上の発見（重要、当て推量を避けて実装前にコード調査で確認）**:
    `domain/axis_definitions.py: evaluate_axis_array`のpriority_overrides判定
    （line 1011）が`values.dtype == bool`で分岐しており、boolean材料をfloat配列
    （NaN対応）へ統一すると壊れる。実際に配列表現が2系統ある
    （motor_vehicle_no/no_lit/has_tunnel/is_designated＝bool配列・欠損False、
    surface_good＝float配列・欠損NaN）ことをコードから確認し、`bool_default`で
    材料ごとに固定して吸収した。もし検証せず統一していたら、priority_overridesを持つ
    軸で無言の誤判定を生んでいた。
  - oneway・designation（categorical）は今回もextractor未設定のまま
    （データ源がEdgeLikeに無い/per-edge種別が未配線のため、それぞれ元のコメント通り
    DEFER継続）。
- 内容2の調査結果（着手見送りの根拠）: `_ROAD_SURFACE_TILE_MVT_SQL`
  （`road_graph_repository.py`）を確認したところ、T290で「MVTタイルに焼き込み済みだが
  評価軸には未使用の生データも網羅的に登録する」方針が既に実施済みのため、
  **`MATERIAL_CATALOG`の`tile_property`が設定された材料は現時点で100%タイルSQLに
  焼き込み済み**（未対応は無し）だった。つまり「新材料を追加するたびにCASE式へ
  手で1行足す」という将来の負担は今のところ発生しておらず、宣言化・コード生成に
  投資しても解消する具体的な手間が今は無い。一方でこのSQLは正規表現によるmaxspeed/lanes
  の数値検証・JOINで求めるkm正規化密度・is_ert/is_cl真偽値のCOALESCE合成など、
  材料ごとに形の違う手書きロジックが多く、汎用コード生成のDSLを作る方が複雑さで
  上回るおそれがある（複雑度平衡の原則、必要性が実証されるまで抽象化を追加しない）。
  **DEFER（トリガー付き）**: 3個以上のtile_property付き材料をまとめて追加する必要が
  生じた時点、またはCASE式の手書き量が今回確認した規模から明確に増えた時点で再検討する。
- 影響範囲（内容2・3を保留し続けた場合）: 内容2は前述のとおり現時点で実害が無いため
  保留の影響も無い。内容3（shared材料）を保留し続けると、材料の排他帰属が今後も
  「1材料=1軸専用」のままのため、複数軸が同じ生データ（例: gradient_percent）を
  異なる評価式で使いたいという要望が来た場合、新材料の複製登録（実質的には同じ生データの
  別名材料を作る回避策）でしか対応できない。
- 完了条件: 内容1は「新材料1件の追加に必要な編集箇所一覧が現状から明確に減ったことを、
  実際の材料追加1件で実証する」を満たした（上記実証参照）。内容2・3は次回スコープで
  再判断する。

### - [ ] T281. 派生データ鮮度の段階対応（依存DAG文書化→統合エントリポイント→鮮度台帳）〔P2〕規模S→M — 段階1は2026-08-25完了

- 背景: レビュー指摘（レポートF-3）。`batch/`配下8バッチ（import_pbf・import_accidents・
  import_designations・match_designations・precompute_edge_attribute_counts・
  precompute_elevation_attributes・precompute_road_node_degrees・
  precompute_way_attribute_counts）の実行順序・再実行要否がmigrationコメントと
  docstringに分散した不文律のまま。ランタイムの遅延構築（save_graph）で生まれた新規Edgeは
  バッチ手動再実行まで`edge_attribute_counts`/`elevation_attributes`が欠損し、
  stop/accident/intersection/gradient軸が**黙って評価から抜ける**（重み再正規化で薄まる
  だけで検知できない）。T74・T101・T242の本番障害はすべてこのクラスで、対策が
  「人が気をつけるルール」（CLAUDE.md 2本）に留まっている。
- 内容（段階、各段階にトリガー）:
  1. 【即時・S、2026-08-25完了】依存DAGと「この生データが変わったらこのバッチ群を
     再実行」対応表を[docs/batch-pipeline-dependencies.md](batch-pipeline-dependencies.md)
     として独立ファイル化した（8バッチ全ての読み取り専用調査により、入力・出力・
     依存前提・再実行トリガー・冪等性を表で整理。実行順序は
     ①import_pbf/②import_accidents/③import_designations（相互独立）→
     ④precompute_road_node_degrees→⑤precompute_edge_attribute_counts
     （④の後必須、docstringに明記済みの既知の順序）／⑥precompute_elevation_attributes
     （road_edgesにのみ依存、増分実行可能）→⑦precompute_way_attribute_counts／
     ⑧match_designations（③・①の後）と確認できた。既存のdocstring記述と実装を
     突き合わせ矛盾は無いことを確認済み）。
  2. 【M — トリガー: 次回のデータ投入・エリア拡大作業時】順序解決込みの単一エントリポイント
     （`python -m app.batch.refresh_derived`等）を導入し、手順書の複数コマンドを1つに畳む。
  3. 【トリガー: 同クラス障害の再発、またはT127全国展開の意思決定】*_import_runs系を一般化
     した鮮度台帳で「生データ更新時刻 vs 派生computed_at」を機械比較可能にする。
     T242残課題（標高バックフィル定期実行）のスケジューリング基盤新設と関連するため、
     着手時に統合を検討する。
- 完了条件: 段階1はドキュメント1枚の存在。段階2以降は着手時に確定。

### - [x] T282. Repositoryファサード委譲33本 — R-8トリガー「30本超で再検討」発火の判断記録〔P2〕規模S（判断のみ、2026-08-25完了）

- 背景: レビュー指摘（レポートF-4）。`RoadGraphRepository`ファサード
  （road_graph_repository.py:2267〜）の委譲メソッドが33本に達し、複雑度レビュー
  2026-08-16 R-8がKEEP判断時に設定した再検討トリガー「30本超」を超えた。
- 内容: 選択肢 (a) 現状維持を新上限（例: 45本）とともに再確定、(b) 呼び出し側を
  サブリポジトリ（AttributeRepository等）直接注入へ移行しファサード縮退、(c) 用途別
  ファサード分割（探索材料系/タイル系/バッチ系）。レビューの推奨は**(a)**
  （Fakeリポジトリが依存する正式契約として機能しており、呼び出し元は既にGraphService等で
  束ねられているため。分割は変更理由の異なる利用者が現れてからで遅くない）。
  トリガー発火→判断の記録自体が本タスクの成果物（設計原則10）。
- **判断（2026-08-25）**: レビューの推奨どおり**(a) 現状維持**を採用した。
  - 現時点の実測: 委譲メソッド数は変わらず33本（2026-08-24のレビュー起票時から増減なし）。
    内訳は生OSM層・タイルマーカー5本（`RawOsmRepository`）＋派生グラフ6本
    （`DerivedGraphRepository`）＋Road Attribute20本（`AttributeRepository`）＋
    表示用MVT2本（`RoadSurfaceTileQuery`）。
  - (b)（サブリポジトリ直接注入への移行）を採らない理由: `GraphService`・
    `ElevationAttributeService`・`RegionService`はいずれもこのフラットな契約
    （`repository.get_xxx(...)`）をダックタイピングで期待する設計が改善計画T18で
    既に確定しており、対応する`FakeRoadGraphRepository`等のテストダブルも同じ形。
    移行は「呼び出し元3サービス＋テストダブル数個」を書き換える広範囲な変更になる
    一方、現状のファサードが技術的負債として支障を来している具体的な事象は無い。
  - (c)（用途別ファサード分割）を採らない理由: 現在の4分類（raw_osm/graph/
    attributes/tile_query）はサブリポジトリの粒度で既に整理されており、ファサード
    自体をさらに分割しても呼び出し元（サービス層）から見た複雑さは変わらない
    （分割の恩恵を受けるのは「利用者ごとに変更理由が異なる」場合だが、現状の
    3サービスはいずれも複数分類のメソッドを横断的に使っており、用途別に呼び出し元が
    分かれていない）。
  - **新トリガー**: 委譲メソッド数が**45本を超えた時点**で再検討する（レビュー提案値を
    採用。33本から12本の余裕を持たせる）。次回再検討時は、その時点で追加された
    メソッドの内訳（どの分類が増えたか）も踏まえて(b)/(c)を再評価すること。
- 完了条件: 判断と新トリガーをdocs（complexity-review系の規模ウォッチまたは本ファイル）へ記録。
  本エントリが記録そのもの。

### - [ ] T283. `road_graph_use_repository`設定の名称・既定値の再考〔P3〕規模S — トリガー: 次のconfig.py変更のついで、または新環境構築時

- 背景: レビュー指摘（レポートF-6）。T222（DBなし構成撤去）・T247（road_graph既定化）を
  経て、この設定の実質的な意味は「地図レイヤー（路面/POI/事故タイル）・標高キャッシュ・
  ORSエンジン路面評価のDB利用」フラグへ変わったが、名称は旧来のまま。既定`False`のため
  本番・新環境で設定を忘れると**ルート生成は動くのに地図レイヤーがすべて空**という
  気づきにくい縮退になる（既定エンジンがDB必須になった今、「DBはあるのにこのフラグだけ
  False」という中途半端な状態が最頻の罠）。
- 内容: 名称変更（例: `map_layers_use_db`等）または既定値`True`化（DB接続失敗時は既存の
  空タイルフォールバックが効くため安全側は保てる）を比較し、どちらかを実施する。
  `.env.example`のプロファイル表も追従する。
- 完了条件: 変更の実施＋.env.example追従＋architecture.md該当箇所の更新。

### - [ ] T284. page.tsx閾値発火前の分割方針の事前確認〔P3〕規模S（判断のみ）— トリガー: 次のUI機能（page.tsxへ追記が見込まれるもの）の着手前

- 背景: 規模ウォッチ実測（2026-08-24）: page.tsx **1,773行**（閾値1,900、残127行）・
  state **36件**（useState 28＋useStoredState 5＋useStoredJsonState 3、閾値40）。
  直近2日で+158行のペースであり、次の中規模UI機能で閾値到達がほぼ確実。MapView.tsxは
  2,489行（閾値2,800、残311行）でやや余裕がある。
- 内容: 発火してから慌てて分割するのではなく、着手前に対応方針（レイヤー可視性系の
  useReducer化 or レシピ軸単位のカスタムフック化、複雑度レビュー2026-08-18 F-3の候補）を
  選んでおき、次のUI機能実装と同時または直前に実施するかを判断する。
- 完了条件: 方針の決定記録（実施自体は閾値到達時でよい）。

### - [ ] T285. 表示系レジストリの縮退 — 軸カタログのランタイム一本化〔P3〕規模M〜L — トリガー: T280完了後、またはGUI作成軸を地図レイヤーへ出す要望が出た時点

- 背景: レビュー「目指すべきアーキテクチャ像」§10-2の正式化。軸の情報源が
  計算系（`AXIS_DEFINITIONS`、DB化・ランタイム反映）と表示系（`registry.py`、ビルド時
  静的・手書き登録）の二重レジストリになっており、GUI作成軸は地図レイヤー・凡例へ
  永遠に反映されない。**T276の実装メモが「真に動的反映させるには地図レイヤー側
  （`SECONDARY_AXES`/`primaryAttributes.ts`等、`axis-catalog.json`静的importの複数箇所）を
  `useAxisCatalog`と同様の動的フェッチへ置き換える別タスクが必要（規模が大きく本タスクの
  スコープ外とした）」と明記した宿題**であり、本タスクがその正式起票にあたる。
- 内容: ramp系軸の表示定義は`axis_display.py: derive_ramp_inputs`の自動導出へ寄せ、
  `registry.py`にはbespoke軸の宣言と一次属性カタログのみを残す。`axis-catalog.json`の
  「ビルド時静的」は一次属性・bespoke分に限定し、軸一覧はランタイムAPI
  （`GET /api/axis-catalog`、T269）へ一本化する。地図UI一式（MapView.tsxのレイヤー
  ファクトリ・レイヤーパネル）へ触れるため、Playwright実機確認を完了条件に含めること。
- 影響範囲（保留した場合）: GUI作成軸の地図表示不可という制約が残り続ける（T280が
  完了して軸を作れるようになった時点で、この制約が次のボトルネックとして顕在化する）。
- 完了条件: 着手時に確定（少なくともGUI作成軸1件が再デプロイなしで地図レイヤーに
  現れることの実機確認を含める）。

### - [ ] T286. architecture.mdの経緯記述をdecisions/へ追い出す第2弾〔P3〕規模M — トリガー: 次の大きな設計転換時に独立タスクとして、またはユーザーの整理指示

- 背景: レビュー指摘（レポート§7-4）。architecture.mdが1,680行に達し、「現状の姿」を
  記すはずのドキュメントにStep時代の試行錯誤・撤去済み機能の注記（「当初は〜だったが
  撤去」型の段落）が堆積している。T8（決定記録のdecisions/分離、第1弾）と同型の整理を
  もう一度行う時期に来ている。新規参加者（将来の自分を含む）の初読コストと、
  「コード変更と同一コミットでarchitecture.md更新」ルールの編集コストの両方に効く。
- 内容: 「現状の姿」として残す記述と「経緯・教訓」としてdecisions/へ移す記述を仕分ける。
  移設は内容無変更（リンクで辿れることが条件）。「ついで」にやらず独立タスクとして
  実施する（過去の同種整理T8・2026-08-19棚卸と同じ運用）。
- 完了条件: architecture.md本文の行数削減（目標は着手時に設定）＋decisions/側からの
  リンク整合＋CLAUDE.md/context.mdの参照先が壊れていないこと。

### - [ ] T287. road_nodes/road_edgesのtext型PKの容量・性能再評価〔P3〕規模S（調査のみ）— トリガー: T127（全国データ取込）の意思決定時に容量試算へ含める

- 背景: レビュー指摘（レポート§6）。`road_edges.edge_id`・`road_nodes.node_id`は
  決定論的文字列ID（text型PK）で、FK（elevation_attributes・edge_attribute_counts・
  designation_attributes旧キー）・JOIN・索引サイズがbigint比で数倍になる。関東規模
  （数十万Edge）では実測上問題になっていないが、全国規模（T127、既にPBF取込で
  94万way超の減速実測あり）では索引サイズ・JOINコストの支配項になりうる。
- 内容: T127の容量・所要時間検証に「決定論的採番を維持したままbigintハッシュ等へ移行する
  場合の容量・移行コスト試算」を1項目として含める。現時点でのスキーマ変更は行わない
  （関東規模で問題が出ていない変更は割に合わない）。
- 完了条件: T127検証レポートに本観点の試算が含まれること。

### - [ ] T288. AXIS_DEFINITIONS push型更新のマルチワーカー対応〔P3〕規模S〜M — トリガー: backendの複数ワーカー/複数プロセス構成の採用時（現状は単一プロセスデプロイのため未到達）

- 背景: レビュー指摘（レポート§6）。`AXIS_DEFINITIONS`はmutableグローバル辞書を
  「起動時＋管理API書き込み直後」の2箇所でin-place更新するpush型設計
  （`services/axis_registry_service.py`）。単一ワーカーでは安全だが、複数ワーカー化すると
  他プロセスでの軸編集が反映されない。また同一プロセス内でも「リクエスト冒頭の
  RoutePreference検証」と「後段の評価」の間にawaitを挟むため、管理API書き込みとの
  理論上の不整合ウィンドウがある（実害は管理者手動操作時のみ・確率極小）。
  対応方針（`axis_registry_meta.revision`のポーリングへ差し替え）は
  docs/decisions/t221-axis-registry.md「Stage D設計メモ」に記録済みで、本タスクは
  それをトリガー付きで拾えるようにする正式起票。
- 影響範囲（保留した場合）: 単一プロセスデプロイを続ける限り実害なし。複数ワーカー化を
  「別の理由」（性能等）で行う際に本タスクを見落とすと、軸スタジオの編集が一部プロセスに
  反映されない不整合が黙って起きる——複数ワーカー化のタスクを起こす際は本タスクを
  完了条件に含めること。
- 完了条件: 着手時に確定（ADRの方針どおりrevisionポーリング等へ差し替え、複数プロセスでの
  反映テストを含む）。

### - [x] T289. 一方通行（一次属性）を観測グループの独立レイヤーとして追加する 規模S〜M（2026-08-24完了）

- 背景: T280（材料供給の1本道短縮）着手にあたりユーザーへ具体的な新規要素を確認したところ
  「一方通行」の追加希望が挙がった。調査の結果、**一方通行は既にグラフ構造レベルで完全に
  ハンドリング済み**（`osm_adapter.py: _resolve_direction`が`oneway`/`oneway:bicycle`
  タグからforward/backward/bothを解決し、`graph.py: build_road_graph`が逆方向Edge自体を
  生成しない。探索は構造的に一方通行を厳密に守っており、逆走はそもそも不可能）と判明。
  そのためT280（評価軸向け材料の追加コスト削減）の実証対象にはならず、**独立タスク**として
  起票する。用途はユーザー確認により「まず表示のみ（評価軸への重み付け組み込みは別途）」に
  確定した。
- 設計: `MATERIAL_CATALOG`（評価軸専用）ではなく、`domain/registry.py:
  PrimaryAttributeSpec`（一次属性）＋地図の静的属性レイヤーとして追加する
  （2026-08-22のT217「トンネルを観測グループの独立レイヤーとして追加」と全く同型の
  一次属性追加パターン。tunnelはタイルへの焼き込み自体は既存だったためbackend変更
  ゼロだったが、one-wayは`osm_raw_ways.direction`列がありながらタイルSQLに未焼き込みの
  ため、backend側の変更が一手多い点が異なる）。
- 内容（T217を1本道の地図として利用、`git show 2a603c6`参照）:
  1. **backend**: `_ROAD_SURFACE_TILE_MVT_SQL`（road_graph_repository.py）のCASE式へ
     `CASE WHEN w.direction != 'both' THEN true END AS oneway`を追加
     （`osm_raw_ways.direction`は既にDB永続化済み、migration不要）。
  2. タイル世代番号を上げる（`region_service.py: ROAD_SURFACE_TILE_VERSION`と
     `region-tile-config.json`、CLAUDE.md同期ルール必須）。
  3. `registry_defaults.py`へ一次属性として登録（`attr_id="oneway"`,
     `dtype="boolean"`, `geometry="edge"`, `source="osm"`,
     `ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec"`。どの評価軸のinputsにも
     含めない＝軸に属さない表示専用の一次属性、`all_primary_attributes()`が
     `axis-catalog.json`のprimary_attributes[]へ自動反映するため軸登録は不要と確認済み）。
  4. **frontend**: `mapLayers.ts`（MapLayerId型・MAP_LAYERS・ROAD_SURFACE_SHARED_LAYER_IDS）・
     `staticAttributeLayers.ts`（ONEWAY_LEGEND/COLOR_EXPRESSION/OPACITY_EXPRESSION、
     StaticFilterAxisId・STATIC_FILTER_AXES）・`icons.tsx`（OnewayIcon）・
     `MapView.tsx`（ONEWAY_LAYER_ID・ensureOnewayLayer・STATIC_OVERLAY_LAYERS・
     LAYER_DATA_SOURCES・showOneway props配線、T217差分どおり多数のuseEffect依存配列へ
     機械的に追加）・`page.tsx`（DEFAULT_LAYER_VISIBILITY・showOneway受け渡し）・
     `primaryAttributes.ts`（PRIMARY_ATTRIBUTE_LAYER_IDS・PRIMARY_ATTRIBUTE_CHIP_LABELS）・
     `MapLayersPanel.tsx`（switch文case追加）・`MapOverlayControls.tsx`（LAYER_ICONS）。
  5. テスト: T217の対応テスト（`staticAttributeLayers.test.ts`・`primaryAttributes.test.ts`・
     `MapView.dataStatus.test.ts`・`MapLayersPanel.test.tsx`・`MapOverlayControls.test.tsx`）と
     同型のケースを追加。
- 完了条件: backend/frontend全テストgreen、Playwright実機確認（地図上で一方通行区間が
  色分け表示されること）、docs/architecture.md追従。
- 検証: backend全1174件green（新規1件: `_ROAD_SURFACE_TILE_MVT_SQL`のoneway焼き込み検証）、
  frontend tsc/eslint/vitest全523件green（新規4件）。実機確認（Playwright headless
  chromium、ユーザー明示要望どおりClaude Browserペインでなく自前スクリプトで実施）:
  王子駅付近z14でタイルAPIを直接デコードしoneway=trueが671件中257件正しく焼き込まれて
  いることを確認、地図上で観測グループ「一方通行」チップをONにすると青色（`#2563eb`）で
  一方通行区間が明確に色分け表示されコンソールエラー0件を確認。区間クリックポップアップの
  「一方通行」行表示は座標特定がPlaywright側の制約で難航したため実機クリックでは
  未確認だが、`INTERACTIVE_LAYER_IDS`が`STATIC_OVERLAY_LAYERS`から自動導出される設計
  （手書きリストなし）のためonewayレイヤーは自動的にクリック判定対象へ含まれることを
  コードで確認済み。
- 実装メモ: `MATERIAL_CATALOG`ではなく一次属性として実装したため、当初の起票案どおり
  T280（材料供給の1本道短縮）の実証にはならなかった。T280は「軸スタジオUI拡張より先に
  実施する」という順序制約付きでトリガー待ちのまま据え置き。

### - [x] T290. MVTタイルに焼き込み済みだが材料未登録の生データをMATERIAL_CATALOGへ網羅登録する 規模M（2026-08-24完了）

- 背景: T289完了後、ユーザーから「設計の一貫性を取ろうとしている。評価や地図描画に
  使えそうな生データは全部材料登録しておきたい」という方針指示。`_ROAD_SURFACE_TILE_
  MVT_SQL`の全プロパティと`MATERIAL_CATALOG`（9材料）を突き合わせた結果、**11件の
  生データが既にタイルに焼き込まれているのに材料未登録**と判明した:
  - 既存dtype（numeric/boolean）でそのまま登録可能（5件）: `bridge`・`motor_vehicle_no`・
    `oneway`（T289で一次属性化したが材料化はしていなかった）・`maxspeed_kmh`・`lanes_count`
  - 多値カテゴリカル、dtype拡張が必要（6件）: `highway`・`surface`・`bicycle_infra`・
    `cycleway_class`・`designation`・`smoothness`
- 設計方針（ユーザー承認済み）:
  1. `material_catalog.py: MaterialDType`を`Literal["numeric", "boolean"]`から
     `Literal["numeric", "boolean", "categorical"]`へ拡張し、11材料すべてを登録する。
  2. **`categories`（許容値一覧）フィールドは追加しない**——highway等はこのプロジェクトで
     正準の閉じた集合を管理しておらず、無理に列挙すると事実と異なる情報になるため。
     詳細はMaterialSpecのコメントで説明する。
  3. **`axis_definitions.py: CategoricalShape`（`mapping: dict[bool, float]`）の
     文字列対応拡張は今回のスコープに含めない**——材料の「存在を宣言する」ことと
     「評価軸として実際に使えるようにする」ことは独立した作業であり、今使う予定のない
     評価ロジックを先回りで拡張すると過剰設計になる（設計原則9）。
     **トリガー: 上記6件のいずれかを実際に評価軸の材料として使う新規軸の要求が出た時点**
     （その時点でCategoricalShapeを拡張するか、その軸専用の新Shape種別を追加するかを
     具体的な要件に応じて判断する）。
- 影響範囲（保留した場合）: 現状どおり——軸スタジオの材料選択肢に現れないだけで、
  実害はない。ただしT280（材料の天井対策）の候補材料が見えないままになる。
- 完了条件: `material_catalog.py`へ11材料追加＋`MaterialDType`拡張。
  `GET /api/material-catalog`のレスポンスに20材料（既存9+新規11）が含まれることを
  確認。backend/frontend全テストgreen。既存7軸の挙動・OpenAPI契約（`AXIS_DEFINITIONS`
  非対象のため本来変更なしのはずだが、`material-catalog.json`生成物のドリフト確認は必須）に
  影響がないことを確認。
- 検証: backend全1181件green（新規7件: `test_material_catalog_routes.py`新設5件＋
  `test_axis_admin_routes.py`2件、`categorical`材料をBreakpointLinearShape/
  CategoricalShapeに指定した場合の422拒否を確認）。frontend tsc/eslint/vitest全523件
  green（既存件数のまま、回帰なし）。実機確認（`GET /api/material-catalog`で20材料・
  categorical6件のdtypeを確認、軸スタジオの3つのshape種別[区分線形補間/カテゴリ値/
  フラグ加算]それぞれで材料ドロップダウンを実機確認——numeric専用は7件[新規2件含む]、
  boolean専用は6件[新規3件含む]がそれぞれ正しく表示され、categorical6件はどちらにも
  混入しないことを確認、コンソールエラー0件）。
- 追従修正: `lib/axisMaterialsCatalog.ts: AxisMaterialOption.boolean`（2値フラグ）を
  `dtype: AxisMaterialDType`（"numeric"/"boolean"/"categorical"の3値）へ変更した。
  旧実装のまま`categorical`材料を追加すると`!boolean`（numeric用フィルタ）に誤って
  混入し「選べるのに送信時にエラーになる」UXを生むため、T290に付随する必須の追従修正
  として対応した（`AxisComposer.tsx`のフィルタ条件4箇所を`dtype`比較へ書き換え）。

### - [x] T291. ~~car_stress軸のcycleway補正をbicycle_infra（6値）ベースへ精密化する~~ 規模L（2026-08-24方針転換のため撤回、T292へ発展的解消）

- 背景: T290完了後、ユーザーから「自転車の走りやすい道を推定しようとした時、
  categorical型で特定カテゴリを選択したい」という要望。調査の結果、既に
  `domain/traffic.py: classify_bicycle_infrastructure`（6値: separated/lane/
  shared_busway/shared_pedestrian/prohibited/roadway）と`domain/recipe.py:
  cycleway_class`（3値: track/lane/shared、car_stress軸のcycleway補正専用）という
  **2つの独立した自転車インフラ判定ロジックが並存**していると判明した。ユーザーへ
  設計方針を確認した結果:
  1. 新規独立軸ではなく**既存car_stress軸の「再定義」**（推定カテゴリの軸を、
     T290で取り込んだ一次属性=bicycle_infraで再定義したい）
  2. 再定義の範囲は**cycleway補正部分のみ**（highway基準値・maxspeed補正・
     lanes補正・指定路線補正は維持、軸の趣旨=「車の圧迫感」は変えない）
  3. スコア案（0-100スケール、易→難）: separated=0・lane=20・shared_busway=40・
     shared_pedestrian=50・roadway=70・prohibited=100
  という3点で合意した。
- 設計方針:
  1. `recipe.py: cycleway_adjustment`を、現行の`cycleway_class`（3値）ではなく
     `classify_bicycle_infrastructure(tags, highway)`（6値）で判定するよう拡張する
     （引数へ`highway`を追加）。`cycleway_class`関数自体は撤去しない（SQL側の
     `cycleway_class`タイルプロパティ・T290で登録した同名材料は表示用途として
     引き続き独立に使われる）。
  2. `RoadSuitabilityRecipe`の補正フィールドを3値（track/lane/shared）→5値
     （separated/lane/shared_busway/shared_pedestrian/roadway）へ拡張する。
     `prohibited`は0次ハードフィルタ（`no_bicycle`）で通常除外されるため補正
     フィールドを持たない。
  3. ユーザー提示の0-100スケールを、既存のhighway基準値（1-5スケール）への
     加減算レンジへ線形変換する: `adjustment = round(score/100 × 4 − 2)`
     （現状のtrack=-2・lane=-1という実績値をレンジの両端に対応させる変換式）。
     結果: separated=**-2**（現状track相当・変更なし）・lane=**-1**（変更なし）・
     shared_busway=**0**（現状-1から変更）・shared_pedestrian=**0**（新規）・
     roadway=**+1**（新規）。**shared_buswayの挙動が変わる既存挙動変更**である点に
     注意（T240等の「安全側ロールアウト」原則とは異なり、今回はユーザー自身が
     再定義を求めているため意図的な変更）。
  4. `domain/traffic.py: car_stress_breakdown`の`lanes_low_threshold`抑制条件
     （現状`cycleway_class(tags) == "track"`）を`classify_bicycle_infrastructure(tags,
     highway) == "separated"`へ変更する（フロントの`cyclewayIsTrack`判定と対で変更）。
     内訳表示（`CarStressBreakdown`）のingredientキーも`bicycle_infra`ベースへ
     更新する。
  5. **frontend**: `recipeExpression.ts: cyclewayAdjustmentExpr`を、タイルの
     `bicycle_infra`プロパティ（T290で既に焼き込み済み）を読む6値`match`式へ
     書き換える。`carStressExpression.ts`の`cyclewayIsTrack`判定も対で変更。
     `RoadSuitabilityRecipePanel.tsx`（研究モードのレシピ調整UI）をフィールド変更へ
     追従。
- 影響範囲（調査済み、着手前の網羅確認）: backend
  `domain/recipe.py`・`domain/traffic.py`・`api/routers/routes.py`（Override
  モデルのフィールド変更）／frontend `recipeExpression.ts`・
  `carStressExpression.ts`・`recipeBreakdownPopup.ts`・
  `RoadSuitabilityRecipePanel.tsx`／テスト`test_recipe.py`・`test_traffic.py`・
  `test_evaluation*.py`・`test_measure_axis_stats.py`・`test_routes_generate.py`・
  `carStressExpression.test.ts`・`RoadSuitabilityRecipePanel.test.tsx`・
  `CarStressRecipePanel.test.tsx`・`ComparisonPanel.test.tsx`。
- 完了条件: 上記全ファイルの更新、backend/frontend全テストgreen（挙動変更を伴う
  既存テストの期待値更新を含む）、OpenAPI生成物ドリフトなし、実機確認（Playwright、
  区間クリック内訳表示・研究モードのレシピ調整UI・地図の色分け表示）。
  docs/architecture.md追従。
- **撤回の経緯（2026-08-24）**: 実装着手前の最終調査中にユーザーから「レシピを
  ひとつひとつベタ書きでソース上補正するつもりはない。それをやりだすと、推定軸の
  追加が軸スタジオで完結できなくなってしまう。将来の拡張性を損ねる」という訂正が
  入った。本タスクは「car_stress軸のcycleway補正1箇所だけ」を精密化する狭いスコープ
  だったが、ユーザーが真に求めていたのは**「レシピ付き軸という専用Pythonロジックの
  仕組み自体を廃止し、一次材料の宣言的な組み立て（JSON定義）だけで推定軸を再現・
  新設できる汎用基盤」**だった。本タスクの調査（`car_closeness`/`road_suitability`/
  `cycleway_adjustment`の完全なロジック洗い出し）はT292の設計材料としてそのまま
  活きている。

### - [x] T292. 推定軸に「内部軸→公開軸」の階層構造を導入し、一次材料の宣言的組み立てだけで推定軸を再現・新設できる基盤を作る 規模XL（2026-08-25完了）

- 背景: T291（撤回）の実装検討中にユーザー方針が確定した。「今定義されている推定軸
  要素（car_stress・accidentが使う専用Pythonレシピ: `CarStressRecipe`・
  `RoadSuitabilityRecipe`・`MotorVehicleDensityRecipe`・`car_closeness`・
  `road_suitability`・`cycleway_adjustment`・`car_stress_level`・
  `car_stress_breakdown`等）をすべて消して、一次生データ材料（T290で20材料へ
  拡張済み）が全て揃っている状態から、それを軸スタジオで組み立てて今ある推定軸を
  再現できる基盤を作りたい」「材料の合成ルールをJSONで表現して、そのJSONをアップ
  するぐらいだけでいい（軸スタジオのGUI組み立て機能は今回不要）」「大きく汎用性を
  高めたい、特殊ケースをコードへベタ書きしない」という3点で合意した。加えて
  「フロントの表示層も汎用化したい。序列があるか無いかで、グラデーションと色系列
  だけ決めておいてあとは自動設定」という表示層の汎用化も対象に含める。
- **設計の変遷（当初案から2回転換した経緯を記録）**:
  1. 当初案: 新Shape種別`CompositeShape`（複数材料の加算合成、`overrides`/
     `suppressed_when`という条件付き機構込み）を軸内に追加する案を検討したが、
     目論見書7章歯止め③「テンプレート4種の線引きを維持する。GUIに数式エディタの
     ような際限のない汎用性を持たせない。表現力の天井は意図的な設計」との整合性を
     ユーザー指示で確認したところ、これと衝突するリスクが高いと判明。
  2. 中間案: CompositeShapeを「5つ目の計算テンプレート」として正式追加する案で
     いったん合意しかけたが、ユーザーから「car_stressの例だと1つの推定軸に押し込む
     のが無理があったのでは。複数の推定軸に分解し、それを組み合わせる演算があれば
     再現できないか」という指摘が入った。
  3. **最終案（本エントリの内容）**: car_stress軸のようなPythonレシピ（highway
     基準値＋cycleway補正＋maxspeed補正＋lanes補正＋designation補正の加算）は、
     「1つの複合軸」としてではなく、**5つの独立した内部推定軸（`is_published=False`、
     研究フェーズで自由に増減できる）に分解し、それらを固定重みで合成した「翻訳結果」
     として公開軸`car_stress`を作る**、という**軸に階層を持たせる**設計へ転換した。
     この転換により**新Shape種別は不要**（内部軸のdifficulty値[0-100]を、既存の
     `BreakpointLinearShape`の`terms`へ「材料」と同じ扱いで渡すだけで表現できる）。
     目論見書歯止め③との衝突が完全に解消され、むしろ3章「到達したい姿」Phase4
     「蒸留」（観測系の生軸は推定軸の内部へ**吸収**していく）の具体的な実装方法を
     提供する設計になった（ユーザーとの再突合で確認済み、詳細は下記）。
- **目論見書・全体最適レビューとの突合結果（着手前、ユーザー指示で2回実施）**:
  - 目論見書歯止め③（テンプレート4種維持）: 新Shape種別が不要になったため
    **完全に整合**（第1回突合で懸念was、第2回突合で解消を確認）。
  - 目論見書歯止め①（材料の排他帰属）: 内部軸が材料を1対1で占有し公開軸は
    軸の出力のみを参照する設計のため、以前（1軸が5材料を直接占有）より**歯止めの
    精神に忠実になる**。
  - 目論見書3章Phase4「蒸留」（観測系の生軸を推定軸の内部へ吸収）: 今回の設計は
    この一文の**具体的な実装方法そのもの**（強い整合性）。
  - 目論見書4章「軸のライフサイクル」（材料を選ぶ→テンプレートに載せる→検証する→
    **公開する**）: 内部軸は「公開しない」という目論見書に無い新しい終着点を持つ。
    矛盾ではないが**未規定領域**のため、実装完了時に目論見書へ追記する。
  - 全体最適レビューF-2「材料の天井」問題: 材料を増やす方向ではなく**既存材料の
    組み合わせを軸として再利用可能にする**という別角度から問題を緩和する方向に働く。
  - 全体最適レビューT290判断（`CategoricalShape`拡張のDEFER）: **正しかったことが
    確認された**——「実際に必要になった時点でその軸の要件に応じて設計する」という
    トリガーに対し、出た答えは「`CategoricalShape`拡張」ではなく「カテゴリカル材料を
    独立した内部軸にする」という、より良い解決策だった。
- 現状把握（既存car_stress軸ロジックから抽出した演算要素、この8種で全ロジックを
  再現できることを確認済み）:
  1. カテゴリ値→点数（highway基準値、12区分）
  2. 数値の閾値→加減点（maxspeed/lanes）
  3. 条件（真偽値材料）が立っていれば加点（designation該当）
  4. 点数を合計する
  5. 特定条件が成立したら他の計算を全部無視して固定値にする（motor_vehicle=no→
     最良値1固定、最優先の上書き）
  6. 特定条件が成立している間だけ、ある演算要素を無効化する（自転車が専用道路区間
     ではlanes低減緩和を適用しない）
  7. 合計を上限・下限でクランプする
  8. クランプ後の値を目的のスケール（0-100）へ変換する（折れ線）
- **演算要素⑤⑥の設計簡略化（ユーザー承認済み、着手前に確定）**:
  - ⑤（motor_vehicle=no→固定値）: 探索除外（0次ハードフィルタ）とは別の**「評価を
    優先確定する0次条件」という軸定義共通の機構**（内部軸・公開軸どちらでも、将来
    どのテンプレートでも使える）として切り出す。「各推定軸に重複して持たせない」
    というユーザー指示どおり、共通機構として1箇所にまとめる。
  - ⑤の特殊ケースとして検討した「自転車通行禁止（bicycle=no、
    `classify_bicycle_infrastructure`の`prohibited`）」は、**既存の0次ハード
    フィルタ`no_bicycle`（`DEFAULT_HARD_FILTERS`、探索から除外）で既にカバー
    済み**と確認した（`tag_value_is(edge_way_tags, "bicycle", "no")`という同一の
    判定条件）。追加実装は不要。これが「探索除外の0次条件」と「評価を優先確定する
    0次条件」を区別する具体例になる。
  - ⑥（自転車専用道路区間でのlanes低減緩和の抑制）: 実データ確認
    （`traffic.py:340-341`のコメント、dev DB 2026-08-19）で該当がほぼ皆無
    （対象highway中1件、最終levelへの影響も無し）と判明済みのため、**条件付き
    無効化の機構は作らず単純化し、常に適用する**（ユーザー承認: 「実データ影響
    ほぼゼロなので単純化し、常に適用する」）。
- **最終設計方針（ユーザー承認済み）**:
  1. **軸間参照の実現方法**: 新しい概念・APIを追加せず、既存の`materials`辞書
     （材料id→値）に**計算済みの他軸のdifficulty値も混ぜ込む**だけで実現する。
     `BreakpointLinearShape`/`CategoricalShape`/`FlagSumShape`の評価ロジック自体は
     無変更。呼び出し側（`evaluate_axis_scalar`/`evaluate_axis_array`の呼び出し元）
     が「依存する軸を先に計算し、その結果を`materials`辞書へ書き込んでから次の軸を
     評価する」という順序制御だけを追加する。材料IDと軸IDの名前空間が衝突しない
     命名規則（またはプレフィックス）を導入する。
  2. **依存解決の新規実装**:
     - 軸の依存関係グラフを構築し循環参照を拒否するバリデーション
     - トポロジカルソート順で評価する順序制御（`compute_edge_axis_scores`/
       `compute_edge_costs_bulk`双方に適用）
  3. **3次合成ロジックのフィルタ変更**（実装コスト見積もり時に判明した必須変更点）:
     現状`compute_edge_costs_bulk`は`AXIS_DEFINITIONS`の**全軸**をユーザー重み
     （`RoutePreference.weights`）で3次合成している。内部軸を追加すると何もしなければ
     内部軸まで一般ユーザーの重み付け対象に紛れ込んでしまうため、**`is_published=True`
     の軸だけを3次合成・`default_axis_weights()`・`RoutePreference`バリデーションの
     対象にする**フィルタを追加する。
  4. **新しい0次条件機構**（演算要素⑤担当）: 軸の通常計算（shape評価）より前に
     評価される優先条件。該当時はshape計算をスキップし確定したdifficulty値を
     そのまま返す。`AxisDefinition`へ`priority_overrides`のような形で持たせる
     （材料・一致条件・確定値の組）。motor_vehicle_no=trueがこの機構の最初の適用例。
  5. **`axis_admin.py: _check_materials_are_known`を軸参照対応させる**
     （materialsが材料IDか軸IDかを判別し、軸IDの場合は参照先が循環しないか・
     参照先軸が存在するかを検証）。
  6. **既存car_stress軸を内部軸5つ＋公開軸1つの階層構造でAXIS_DEFINITIONSへ
     置き換え**る。内部軸（`is_published=False`）:
     - highway由来の基準値軸（`CategoricalShape`、12区分）
     - `bicycle_infra`由来の軸（`CategoricalShape`、6値。**これが当初のご要望
       「自転車の走りやすさを推定したい」の実体そのものになる**）
     - `maxspeed_kmh`由来の軸（`BreakpointLinearShape`、閾値変換）
     - `lanes_count`由来の軸（`BreakpointLinearShape`、閾値変換）
     - `designation`由来の軸（`CategoricalShape`、3値）
     公開軸`car_stress`は上記5内部軸を`BreakpointLinearShape`の`terms`として
     固定重みで加重合成する。既存の1-5スケール加減算を0-100スケールの加重平均へ
     変換する数値設計・実データ検証が必要（同じ挙動を保つことを目指す）。
     `recipe.py`・`traffic.py`内の専用レシピコード（`CarStressRecipe`・
     `RoadSuitabilityRecipe`・`MotorVehicleDensityRecipe`・`car_closeness`・
     `road_suitability`・`cycleway_adjustment`・`car_stress_level`・
     `car_stress_breakdown`・`CarStressBreakdown`）を削除する。`evaluation.py`の
     抽出フェーズを、新しい材料（highway/bicycle_infra/maxspeed_kmh/lanes_count/
     designation/motor_vehicle_no）の単純抽出へ置き換える。
  7. **フロント表示層の汎用化**: 各内部軸のカテゴリカル材料の`mapping`（`ordered`
     フラグ付き）を軸定義APIのレスポンスへ含め、フロント側の汎用レイヤーファクトリが
     `ordered=true`ならグラデーション（開始色・終了色から`mapping`の値の範囲に応じて
     線形補間）、`ordered=false`なら定性色パレット（離散色を順に割り当て）を自動生成
     する。既存の`carStressExpression.ts`（bespoke expression、Python側レシピの
     手書きミラー）はこの汎用機構へ置き換わり不要になる見込み——実装時に既存資産の
     削除範囲を確定する。
  8. **目論見書の更新**（実装完了時、同一コミットで）: 4章「軸のライフサイクル」へ
     「内部軸（非公開のまま運用）」という新しい終着点を追記する。
- **実装コスト見積もり（着手前、ユーザー指示で実施）**: バックエンドの評価パイプライン
  変更＋軸再定義＋テストで実装セッション換算2〜3日相当、フロント表示層の汎用化を
  含めると3〜5日相当。内訳: 依存解決の順序制御・循環検出（半日〜1日）／軸間参照の
  実現（半日）／3次合成フィルタ変更（半日）／car_stress軸の階層再設計・数値検証
  （半日〜1日）／既存Pythonレシピ削除（半日）／テスト更新（半日〜1日）／フロント
  表示層汎用化（1〜2日）。規模XLの根拠。
- 影響範囲: 非常に広い。backend `domain/axis_definitions.py`・`domain/recipe.py`・
  `domain/traffic.py`・`domain/evaluation.py`・`api/routers/axis_admin.py`・
  `AXIS_DEFINITIONS`（car_stress軸の定義）／frontend
  `components/Map/carStressExpression.ts`・`recipeExpression.ts`・
  `recipeBreakdownPopup.ts`・`CarStressRecipePanel.tsx`・
  `RoadSuitabilityRecipePanel.tsx`・地図の車ストレスレイヤー描画／関連テスト多数。
  **DBに投入済みの`axis_definitions`テーブル（migration 0014でシード済み7軸）の
  car_stress行も新しいshape_paramsへ更新が必要**（本番・dev両方、加えて新規5内部軸
  分の行追加）。
- 完了条件: 着手時に段階を確定して進める（依存解決基盤→3次合成フィルタ→0次条件
  機構→軸置き換え→フロント表示層→目論見書更新の順）。各段階でbackend/frontend
  全テストgreenを確認。回帰テスト（新旧ロジックの実データ全Edge一致確認、
  `test_evaluation_bulk.py`と同種の手法）を必須とし、既存の評価結果からの意図しない
  乖離が無いことを検証する。docs/architecture.md・docs/decisions/・目論見書
  Artifactへの設計記録を追従させる。
- **進捗（2026-08-24、コミットab213ec）**: 第1段階（依存解決基盤・3次合成フィルタ・
  0次条件機構）完了。`PriorityCondition`/`priority_overrides`・
  `topological_axis_order`/`axis_dependencies`/`AxisDependencyCycleError`・
  `check_material_exclusivity`の軸参照除外・`default_axis_weights`/
  `RoutePreference`のis_published絞り込み・`compute_edge_axis_scores`/
  `compute_edge_costs_bulk`の依存順評価化を実装、`test_axis_hierarchy.py`新設
  （16件）でbool材料の0次条件を含め検証。backend全1197件green（既存軸間に参照が
  無いため現状の合成順・浮動小数点結果は不変）。**残る段階**: 軸置き換え
  （car_stress軸を内部軸5つ＋公開軸1つへ実再定義、旧`recipe.py`/`traffic.py`の
  専用レシピコード削除、`axis_admin.py: _check_materials_are_known`の軸参照対応）→
  フロント表示層の汎用化（orderedフラグによる自動配色、`carStressExpression.ts`置換）→
  目論見書Artifact更新・docs/architecture.md追従。
- **進捗2（2026-08-24）**: 第2段階（軸置き換え）完了。car_stress軸をhighway基準値
  （必須）＋4補正＋motor_vehicle=no優先確定の内部軸6つ（is_published=false）＋
  公開軸1つの階層構造で再実装した。bicycle_infra補正はT291合意済みスコア
  （separated=-2/lane=-1/shared_busway=0/shared_pedestrian=0/roadway=+1）をそのまま
  採用——**実データ検証で、この変更が想定より広範囲（cyclewayタグ未整備の大多数の
  普通道路がroadway=+1点を受ける）に及ぶと判明したが、ユーザー確認の上で予定通り
  適用した**。motor_vehicle=noの優先確定は当初priority_overrides機構を想定していたが、
  実データ確認（dev DB、motor_vehicle=noタグの81.6%がhighway基準値未登録の
  footway/path）でpriority_overridesだと旧ロジックと不一致になる問題が発覚し、
  「他の内部軸の最大合計を確実に上回る固定マイナス項（-1000）を普通の内部軸として
  加算しbreakpointsの端でクランプさせる」方式へ変更した（新しいPythonロジック不要、
  priority_overrides機構自体は他の将来軸用の汎用機構として温存）。
  旧専用Pythonレシピ（`CarStressRecipe`・`RoadSuitabilityRecipe`・
  `MotorVehicleDensityRecipe`・`car_closeness`・`road_suitability`・
  `cycleway_adjustment`・`car_stress_level`・`car_stress_breakdown`等）と、それに依存する
  研究モードAPIのレシピ上書き機能（`/api/routes/generate`・旧`/api/region/
  car-stress-breakdown`エンドポイント含む）・YAML設定3ファイル・calibration用の
  独立研究スクリプト3本（`analyze_jartic_calibration.py`・`measure_axis_correlation.py`・
  `measure_axis_stats.py`、いずれも旧car_stress_levelの1-5段階値を分析対象にしており
  再設計後は主題自体が消滅したため削除）を全廃した。旧`/api/region/car-stress-breakdown`
  は汎用の`/api/region/axis-inspector`（レシピ上書きパラメータなし）へ統合。
  `axis_admin.py: _check_materials_are_known`を軸参照（他の軸のaxis_idをmaterialとして
  指定）対応させ、`AxisRegistryAdminService.create/update`に循環参照検証
  （`topological_axis_order`経由）を追加した。
  **実装中に発見・修正した副次バグ2件**: (1) `CategoricalShape.mapping`を
  `dict[bool, float]`から`dict[bool|str, float]`へ拡張した際、Pydantic既定のsmart-mode
  union解決だとDB往復でJSON文字列"true"/"false"がbool化されずstr型のまま残る回帰
  （既存のsurface_q軸も対象、`union_mode="left_to_right"`で修正、実データ検証・
  回帰テスト追加済み）。(2) 内部軸を`export_openapi.py`のramp自動導出ループが
  誤って処理対象にしKeyErrorでクラッシュ（is_published絞り込み漏れ、
  `derive_ramp_inputs`側もstr多値categoricalで防御的にNoneを返すよう修正）。
  **DB migration**: `0017_car_stress_axis_hierarchy.sql`を作成・dev DBへ適用、
  Python側の値と完全一致することを実測確認済み（本番は別途適用が必要、T74の教訓により
  未適用でも安全側フォールバックのため急ぎではない）。migration適用中に
  dev DBの`schema_migrations`追跡漏れ（0016が実際は適用済みなのに未記録）も発見し、
  スキーマ一致を確認した上でバックフィルした。
  backend全1082件green（scalar/bulk評価パスの回帰比較テストも完全一致）。
- **進捗3（2026-08-24、フロント表示層の汎用化）完了**: 別セッションへ切り出されていた
  残る段階に着手。着手前に`npx tsc --noEmit`を実行したところ、進捗2のbackend変更の
  副作用でフロントのビルドが実際に壊れていることが判明した（13件のTSエラー。backendが
  削除済みの型`CarStressRecipeOverride`等を`types/route.ts`・`types/traffic.ts`が参照、
  backendが削除済みの`/api/region/car-stress-breakdown`を`regionApi.ts`が呼び続けている等）。
  改善計画本文が当初想定していた設計（「各内部軸のmappingにorderedフラグを持たせ、
  フロントの汎用レイヤーファクトリでグラデーション/定性色パレットを自動生成する」）は、
  調査の結果、速度補正・車線数補正という2つの内部軸（自身もbreakpoints型で計算される）を
  扱えず**不完全**と判明したため方針転換した。実際に採用した方式:
  car_stressを他の推定軸（勾配・停止密度・事故密度等）と**全く同じ`axisLayers.ts`の
  汎用rampパイプライン**にそのまま乗せる（car_stressの材料は進捗2でMVTタイルへ全て
  焼き込み済みのためタイル側の変更は不要。`kind="bespoke"`→`kind="ramp"`、
  `TileInputSpec`へN値文字列材料用の`categories`・自身もbreakpoints変換を持つ材料用の
  `breakpoints`の2フィールドを追加し、`registry_defaults.py`へ6内部軸ぶんの
  `tile_inputs`を`stop_density`/`accident`と同じ前例で手書き登録）。あわせて、色分けの
  段階数（バンド数）が4段階固定だったため5段階以上のthresholdsを持つ軸で末尾の段階が
  同色に潰れる問題をユーザーが指摘し、`AXIS_RAMP_COLORS`固定4色配列を
  `rampColorForBand(index, bandCount)`（4色のアンカー間を線形補間、bandCount=4で既存
  4色と完全一致することをテストで担保）へ一般化した。研究モードの専用調整UI3種
  （`CarStressRecipePanel`・`RoadSuitabilityRecipePanel`・`MotorVehicleDensityRecipePanel`）
  は軸スタジオ（T270）が代替済みのため削除。`carStressExpression.ts`・
  `recipeExpression.ts`・`recipeBreakdownPopup.ts`、および調査の過程で発見した
  完全に孤立していた`useRecipeOverride.ts`（削除済みパネルの唯一の呼び出し元を失い
  未import状態になっていた）も削除。backend全935件・frontend全460件green、
  eslint clean、`export_openapi.py`→`npm run generate:api`後の
  `git diff --exit-code -- frontend/src/types/generated/`もクリーン。実機確認
  （Playwright、メイン画面・/admin画面とも）でコンソールエラー0件・地図上の
  「車の圧迫感」レイヤーが新しい階層構造の値で正しく色分け表示されることを確認した
  （このサンドボックス環境にはPostGISデータが無いため、実データでの色の見え方自体は
  T289と同じ方式での確認はできず、ビルド・型・テスト・実機の疎通確認のみ）。
  **パフォーマンス実測（2026-08-25完了）**: フロント側完了・本番反映（T294）後に実施。
  `benchmarks/bench_evaluate_graph.py`（`EvaluationService.evaluate_graph`、T219/T220基準の
  68,120エッジ・T224基準相当の121,800エッジの2規模、各10反復）を使い、T292着手直前の
  コミット（`f42c041`、旧7軸・専用Pythonレシピ）と現行HEAD（内部軸6つ込みの13軸相当）を
  専用worktreeで切り替えながら同一環境・同一ベンチマークで3回ずつ計測して比較した。
  - 68,120エッジ: 旧7軸 min 1.28〜1.41s（3回）→ 新13軸相当 min 1.11〜1.27s（3回）
  - 121,800エッジ: 旧7軸 min 2.25〜2.29s（3回）→ 新13軸相当 min 2.16〜3.19s（3回、
    うち1回だけ外れ値的に高い。他の計測環境ノイズと判断）
  - **結論: 有意な性能劣化は無い（むしろわずかに高速、誤差の範囲内）**。軸数が7→13
    （実質6軸増）になったにも関わらず悪化しなかった理由は、(1)
    `compute_edge_costs_bulk`のボトルネックは軸別計算そのものではなく材料抽出フェーズ
    （Edge数に比例、T240完了メモで既に確認済み）が支配的で軸数の影響は相対的に小さい、
    (2) コードレビュー対応（`evaluate_categorical`のnp.searchsorted化・
    `topological_axis_order`のメモ化）が新規追加分のオーバーヘッドを吸収した、の2点と
    推測される。
  **目論見書Artifact更新（2026-08-25完了）**: 4章「軸のライフサイクル」へ内部軸
  （非公開のまま運用）という新しい終着点を追記し、car_stress軸を実例として明記した。
  7章「設計上の歯止め」の歯止め1（材料の排他帰属）・歯止め2（公開済み軸は不変）・
  歯止め3（テンプレート4種の線引き）にもT292との整合結果（歯止めの精神により忠実に
  なった／内部軸は不変ルールの対象外／新テンプレート不要のまま表現できた）を追記。
  3章の現行7軸表・5章の「できていること」も更新。T292をもって本タスクは完了。

### - [x] T294. 本番DBがmigration 0017・0018未適用のまま起動していた事象の発見・修正 規模S（2026-08-25完了）

- 発端: ユーザーから「本番DBは最新か」という確認依頼。origin/masterのT292フロント作業
  マージ・プッシュ後、Oracle Cloud VM（本番backend・DB同居、T263）へ直接クエリして
  調査した。
- **発見した事実**:
  - `schema_migrations`は0016までしか適用されておらず、T292で追加したmigration
    0017（car_stress軸階層化）・0018（priority_overrides）が未適用だった。
  - `axis_definitions`テーブルのcar_stress行は旧構造のまま（`shape_params`が
    `{"kind": "recipe_then_breakpoint_linear", "terms": [{"material": "car_stress_level", ...}]}`
    ——T292で削除済みの材料`car_stress_level`を参照）。`priority_overrides`カラム自体が
    存在しなかった。
  - **しかし実際の本番挙動は正しかった**（`/api/region/axis-inspector`を実データで
    叩き、car_stress difficulty=50.0が新ロジック通りに返ることを確認）。原因を
    `AxisDefinitionRepository.list_all()`を本番DBに対して直接再現して特定したところ、
    `priority_overrides`カラム不在による`UndefinedColumnError`でSELECT文自体が
    例外を送出し、`services/axis_registry_service.py: refresh_axis_definitions`の
    汎用except節（起動を止めないための安全側フォールバック）に捕捉され、
    コード内蔵の新しい既定値（AXIS_DEFINITIONS、13軸）がそのまま使われ続けていた。
  - **これはmigration 0017のコメントが説明する「0行なら安全にフォールバックする」
    設計通りの動作ではない**（実際には0行ではなく7行の旧データが存在した。
    `refresh_axis_definitions`は0行判定はしているが、0017適用済み・0018未適用のような
    「行はあるが一部カラムが無い半端な状態」は0行判定でもtry/exceptの「読み込み自体が
    エラーになる」パターンでもなければ検知できず、旧shape_paramsをそのまま
    `AXIS_DEFINITIONS`へ上書きロードしてcar_stress軸が黙って評価不能になるリスクが
    あった。今回はたまたま0018のカラム不在がSELECT自体を丸ごと失敗させたことによる
    「意図しない副作用としての安全」であり、設計として保証された安全弁ではなかった）。
- **対応**: `scripts/apply_migrations.py`を本番DATABASE_URL（`.env.oracle.local`）に
  対して実行し、0017・0018を適用（ユーザー確認済み）。適用後、本番backendコンテナを
  SSH経由で再起動（`docker restart ridecompass-backend`、ユーザー確認済み）し、
  `軸定義をDBから読み込みました axes=13`のログと`/api/region/axis-inspector`の
  再検証（car_stress difficulty=50.0、再起動前と同値）で、例外フォールバックではなく
  意図した仕組みでDBから正しく読み込まれていることを確認した。
- **教訓（T74・T101・T242と同クラスだが新しいパターン）**: 「本番DBへのmigration適用が
  コードデプロイに遅れる」問題自体は既知（CLAUDE.md記載の教訓）だが、今回は
  「安全側フォールバックが実際には設計通りに機能していなかった（別の偶然の例外に
  救われていた）」という一段深い問題だった。`refresh_axis_definitions`の
  フォールバック条件（0行 or 読み込み例外）を、より積極的な検知（例:
  コード側AXIS_DEFINITIONSのaxis_id集合とDB側のaxis_id集合の突き合わせ、
  または全軸のshape_paramsがコード内蔵値と一致するかの起動時検証）へ強化するかは
  今後の判断課題として残す（本タスクでは発生済み事象の是正のみ実施、恒久対策は
  T281[派生データ鮮度の段階対応]と関連するため次に類似事象が起きた際に統合検討）。
- 完了条件: 満たした。本番DBのmigration適用・backend再起動・実データでの再検証まで完了。

### - [x] T293. 周回ルートの採用向き（順回り/逆回り）を地図上へ矢印で明示する 規模S〜M（2026-08-25完了）

- 背景: T274（周回ルートの逆回り候補評価）の完了後、ユーザーから「地図上に順向き/逆向き
  どちらが良いかルートの向きを明示する改善はどれだけ大変か」という調査依頼があった。
- **調査（2026-08-24）**: 3案を比較した。
  1. 一覧カードへテキストバッジ（規模S、地図上には出ない）
  2. 経路の線色/線種を向きで塗り分け（規模S〜M、他の色分けモード（風/勾配/舗装/難易度）
     と表示が競合する）
  3. 経路に沿って進行方向の矢印シンボルを配置（規模M〜L見積り、地図単体で完結し
     最も直感的だが、`symbol-placement: "line"`がこのプロジェクト初採用のため
     見え方の検証が必要と判断していた）
  
  ③について、MapLibre GL JS 5.24（`frontend/package.json`記載の実使用バージョン）を
  実際に読み込むインタラクティブなプロトタイプ（Artifact）を作り技術検証した。結果:
  - `symbol-placement: "line"` + `symbol-spacing`（画面px単位、ズームで密度が自動調整）
    という標準プロパティの組み合わせだけで成立し、新しいAPI概念の習得コストは小さい。
  - **矢印の向きはLineStringの座標順をそのまま反映する**。T274のバックエンド実装
    （`_reverse_traced_edges`が逆回り候補のgeometryを既に逆順で構築し、`RouteCandidate.
    geometry`/`segments`は採用された向きの座標順で返る）と噛み合っており、フロント側で
    「どちらが採用されたか」を判定する新規ロジック・新規APIフィールドが一切不要と判明した
    （＝backend側の変更は無し、フロントエンドのみで完結する）。
  - アイコン登録（`sdf:true`）・ハロー層+主層の2層重ねは`windArrowIcon.ts`/
    `windLayer.ts`/`MapView.tsx`の風レイヤーと同じ既存パターンをそのまま流用できる。
  - 残る不確実性は「急カーブ・折り返し区間での矢印の密集/欠落」という実データでの
    調整のみで、技術的な障壁ではないと判断した。
  
  **この検証結果を踏まえ、ユーザーが③（矢印シンボル）を採用方針として確定した**
  （2026-08-24）。実現可能性の不確実性が解消されたため、見積りを当初のM〜LからS〜Mへ
  引き下げた。
- **実装タスク（フロントエンドのみ、backend変更なし）**:
  1. 矢印アイコンの新設（`frontend/src/components/Map/routeArrowIcon.ts`等、
     `windArrowIcon.ts`と同じCanvas 2D + `sdf:true`パターン。シルエットは進行方向を
     指すシンプルな矢じり形でよい）。
  2. `MapView.tsx`に矢印用のsymbolレイヤーを新設（ハロー層+主層の2層、
     `drawSelectedOutline`と同じく選択中ルート（`OUTLINE_SOURCE_ID`のgeometryまたは
     専用source）だけを対象にする——8候補すべてに矢印を出すと輻輳するため、選択中の
     1候補のみに絞る）。`symbol-placement: "line"`・`icon-rotation-alignment: "map"`・
     `symbol-spacing`を設定。
  3. `symbol-spacing`・`icon-size`を実データ（東京都心の実際の道路形状、急カーブ・
     折り返し区間）で調整し、密集/欠落を確認する。
  4. ライト/ダーク両モードでの視認性を実機確認する（過去の教訓「地図UI変更は必ず
     Playwrightで実機確認する」に従う）。
  5. 既存パターンに倣ったテスト追加（`windArrowIcon.test.ts`/`windLayer.test.ts`を参考に、
     アイコン生成・レイヤー登録・選択中ルート切り替え時のsource更新を検証）。
- **着手タイミングに関する注記**: `MapView.tsx`は、別セッションが進めているT292の
  フロント移行作業（`carStressExpression.ts`等の置き換え、影響ファイル26件・約2000行）
  でも中心的に触られるファイルのため、作業ツリーの安全ルールに従い、そのコミットが
  完了してから着手する。
- **保留する場合の影響**: 現状どおり、逆回りが採用されたかどうかはAPIレスポンスの
  geometry/segmentsの座標順にしか表れず、ユーザーからは判別できないまま。失敗ではなく
  UX改善機会の見送りに留まる。
- **実装（2026-08-25）**:
  1. `frontend/src/components/Map/routeArrowIcon.ts`を新設。`windArrowIcon.ts`と同じ
     Canvas 2D + `sdf:true`前提の描画だが、意匠は風（曲線=気流の視覚言語）と区別するため
     単純な三角形の矢じり（シェブロン）にした。`symbol-placement: "line"`時の未回転
     アイコンの基準方向は東（画像の右方向、風の矢印の基準＝北とは異なる）と判明したため、
     右向きのシェブロンとして描く。
  2. `MapView.tsx`の`drawSelectedOutline`に`ensureRouteArrowLayer`を追加。専用sourceは
     持たず、選択中1候補のgeometryだけを保持する既存の`OUTLINE_SOURCE_ID`をそのまま
     流用（8候補すべてに矢印を出すと輻輳するため選択中候補のみに絞るという完了条件を、
     新規sourceを増やさず満たせた）。ハロー層（白・大きめ）+主層（紺・小さめ）の2層重ねは
     風の矢印（`ensureDynamicWeatherLayer`）と同じ構成。icon-sizeのズーム倍率は
     `ICON_ZOOM_SCALE_STOPS`を共有する`zoomIconSizeExpression`（新設、プロパティ非依存版の
     `zoomAndPropertyIconSizeExpression`）で風の矢印と同じズーム曲線に揃えた。
  3. `symbol-spacing=80px`・基準`icon-size=0.55`（ハロー1.4倍）で実データ（東京都心・
     中野の実道路網、急カーブ含む区間）を実機確認した。密集・欠落は確認されず
     （検証区間が限定的なため、より多様な区間での追加確認は今後の実運用フィードバック
     待ち）。
  4. 実機確認: `MapView.tsx`はマップ本体の配色をライト/ダークで切り替える仕組みを持たず
     （地図キャンバス自体はbasemapスタイル1種のみ、アプリ側のCSS `prefers-color-scheme`は
     周辺UIパネルのみに作用しUnaffectedなことをコード上確認済み）、ハロー白+主層紺の
     配色1種類で実際のbasemap上での視認性を確認した（下記スクリーンショット参照）。
  5. `routeArrowIcon.test.ts`を新設（`windArrowIcon.test.ts`と同じ最小スモークテスト）。
     `MapView.tsx`のレイヤー登録・source更新自体はこのプロジェクトに単体テストが無い
     領域（DOM/MapLibre依存が強くPlaywright実機確認で担保する方針、docs/testing.md）
     のため、既存慣行どおり単体テストは追加せず実機確認で代替した。
- **実機確認の方法**: Claude Browserペインはこのセッションでも`isStyleLoaded()`が
  いつまでもfalseのまま進まず（既知の制約、過去メモ参照）画面合成を確認できなかったため、
  `docs/testing.md`の教訓（「地図UI変更は必ずPlaywrightで実機確認する」）どおりPlaywright
  headless chromiumで直接確認した。実DBの道路網（中野・青梅街道付近、Road Graph取込済み
  範囲）でルートを1件生成し、実際のLineString座標での矢印表示・スクリーンショットを取得。
  さらに同じ座標配列を反転させて再描画し、矢印の向きが正しく反転することも確認した
  （T274が逆回り候補のgeometryを実際に逆順で構築する設計と直接対応する、この機能の
  核心的な不変条件）。MapLibreの`queryRenderedFeatures`をsymbolレイヤーへ呼ぶと
  properties空オブジェクトの場合に内部でOut of bounds例外を投げる不具合を検証中に踏んだ
  （本アプリはこれらのレイヤーに対してqueryRenderedFeaturesを呼ばないため実害なし、
  スクリーンショットで実際の描画を直接確認する方式に切り替えて回避した）。
- 完了条件: 満たした。上記5項目を実装、Playwright実機確認で順向き/逆向き双方の矢印表示・
  向きの反転を確認済み。tsc・vitest（Map配下18ファイル200件）green。

## 全体最適レビュー第9回の起票（2026-08-25・ユーザー承認済み）

全ソースコード・DB設計を一から再読した総合診断レビュー
（[.claude/commands/review/history/2026-08-25_overall.md](../.claude/commands/review/history/2026-08-25_overall.md)、
対象コミット`8cea9ee`、総合スコア86/100、前回83から+3）の指摘を起票案A〜Dとして正式起票する。
前回（第8回）が最重要提言とした「材料供給への投資」はT290・T292で消化され、
前回P1（OpenAPIドリフト）もT279のpre-commitフックで再発ゼロを維持している。
今回の最重要指摘は、レビュー期間中に実際に発生した**T294（本番DB migration
0017/0018未適用、4回目の同クラス障害）の恒久対策が宙に浮いている**という点（F-1→T295）。

### - [x] T295. 軸定義DB読み込みの整合検証（未知材料参照の検出・axis_id集合差分の常時ログ）〔P2〕規模S〜M（2026-08-25完了）

- 背景: レビュー指摘（レポートF-1）。`refresh_axis_definitions`
  （services/axis_registry_service.py:36〜）のフォールバック条件は「0行」または
  「読み込み例外」のみで、「行はあるが内容が古い（削除済み材料を参照するshape_params・
  カラム欠如）」を検知できない。T294（本番DBがmigration 0017・0018未適用のまま起動、
  T74・T101・T242に続く同クラス4回目の障害）では、この安全側フォールバックが実際には
  「0018のカラム不在によるSELECT自体の例外」という**偶然**で救われていたに過ぎず、
  設計として保証された安全弁ではなかったことが判明した（もし0017のみ未適用・0018は
  適用済みのような別の組み合わせなら、旧shape_paramsがそのままAXIS_DEFINITIONSを
  上書きし、car_stress軸が黙って全Edge欠損になっていた可能性がある）。T294自身が
  恒久対策を「次に類似事象が起きた際に統合検討」として保留したままになっている。
- 内容:
  1. DB読み込み成功時、各shapeが参照する材料・軸idが`is_known_material`または
     既知のaxis_idであることを検証し、未知の参照があればWARNINGに留めず**フォールバック
     ＋明確なエラーログ**にする。
  2. コード内蔵`AXIS_DEFINITIONS`のaxis_id集合とDB側集合の差分をINFOで常時出す
     （T294の記録が自ら例示した案）。
  3. `refresh_axis_definitions`のdocstringが謳う「安全側フォールバック」の実際の限界
     （0行・例外は検知できるが「半端に古い」は検知できない）を実態に合わせて訂正する。
- 影響範囲（保留した場合）: 軸定義のDB化（Stage D）・軸スタジオ運用が本格化するほど、
  「コードとDBの軸定義の食い違い」が起きる面が増える。現在の検知手段は起動ログ
  （`軸定義をDBから読み込みました axes=13`）の目視のみで、次に発生した場合も
  「偶然」に頼ることになる。T281段階3（鮮度台帳、派生データバッチ向け）を待たずに
  実施できる軽量版として、先にこちらへ着手する（axis_definitionsテーブルはバッチ産物
  ではないためT281のスコープには元々乗っていない）。
- 完了条件: 未知材料参照時のフォールバック強化・起動時のaxis_id差分ログ・
  docstring訂正の3点を実装し、既存テスト（test_axis_hierarchy.py等）へ
  「半端なDB状態からのフォールバック」を検証するケースを追加する。
- **対応（2026-08-25完了）**: `services/axis_registry_service.py`に
  `_find_unknown_references`を新設し、DB読み込み成功後・AXIS_DEFINITIONS反映前に
  各軸が参照する材料id・軸id（`AxisDefinition.materials`）が`is_known_material`
  または同じ読み込みバッチ内の既知axis_idであることを検証するようにした。未知参照が
  1件でも見つかれば（T294のような「行はあるが半端に古い」状態）ERRORログを出し
  コード内蔵の既定値へフォールバックする（0行・例外と同じ全件フォールバック方式。
  一部だけ差し替える部分適用は、依存する公開軸が内部軸を見失う不整合を生みうるため
  意図的に採らなかった）。あわせて、モジュールimport時点の`AXIS_DEFINITIONS`
  キー集合をコード内蔵の既定axis_id集合としてスナップショットし（`_CODE_BUILTIN_AXIS_IDS`）、
  refresh成功時は常にコード側/DB側それぞれにしかないaxis_idの差分をINFOログへ出す
  （差分が無くても空リストで出力し、検証自体が走ったことを常に確認できるようにした、
  docs/logging.md「起動時の構成スナップショット」に対応）。`refresh_axis_definitions`の
  docstringへ、0行・例外の2条件では検知できない「半端に古い」状態の実例（T294）と、
  今回の検証がその限界をどう埋めるかを追記した。
  テストは`tests/test_axis_registry_service.py`に3件追加
  （未知材料参照時のフォールバック・軸id参照は誤検知しないことの確認・axis_id差分の
  INFOログ確認）。既存テストの一部が材料の実在チェックを経ないプレースホルダー材料
  （"dummy"・"own_material"等）を使っていたため、`MATERIAL_CATALOG`に実在する材料
  （gradient_percent/wind_penalty/stop_count_per_km）へ置き換えた（`_check_materials_are_known`
  はAPI層のみの検証で、`AxisRegistryAdminService`は元々これを行っていないため、既存の
  CRUD系テスト自体の意図は変えていない）。backend全1111件green
  （既存1108件+新規3件、他の軸関連テストファイル87件も個別green確認済み）。

### - [x] T296. 軸スタジオでの軸id⇔材料idの名前空間衝突ガード追加〔P3〕規模S（2026-08-25完了）

- 背景: レビュー指摘（レポートF-2）。軸スタジオ（管理API）で、`MATERIAL_CATALOG`の
  材料idと同名のaxis_id（例: `highway`・`surface`）を持つ軸を作成できてしまう。
  `AxisDefinitionPayload._check_materials_are_known`（axis_admin.py:139）はshape参照側の
  検証のみで、axis_id自体と材料idの衝突は検査しない。`AxisRegistryAdminService.create`
  （axis_registry_service.py:89）も既存軸との重複のみ検査する。一方
  `evaluate_axes_scalar`/バルク版は評価結果を`materials_with_axes[axis_id] = value`
  （axis_definitions.py:745、evaluation.py:685）と材料と同じ辞書へ書き込むため、
  材料と同名の軸が評価されると**生の材料値をdifficulty値で上書き**し、それ以降に
  評価される軸が壊れる（`axis_dependencies`は既知材料名を依存として数えないため
  評価順の保証も効かない）。
- 内容: `AxisRegistryAdminService.create`/`update`で、`is_known_material(axis_id)`が
  真ならエラー（409）で拒否するガードを追加する（数行）。
- 影響範囲（保留した場合）: 発生には管理者の操作ミスが必要（Basic認証内・低確率）だが、
  起きた場合はエラーなしの黙った評価破壊で、T292が慎重に排除してきた「黙って欠損する」
  クラスそのものが再発する。
- 完了条件: ガード追加＋テスト（材料id同名でのcreate/updateが409で拒否されることを検証）。
- **対応（2026-08-25完了）**: `AxisRegistryAdminService.create`へ、axis_id重複チェックの
  直後に`is_known_material(definition.axis_id)`のガードを追加した（`ValueError`、
  router層で409へ変換される既存の仕組みをそのまま利用）。axis_idはupdate時に変更
  されないため（`update`はaxis_id自体を書き換える経路を持たない）、update側への
  追加チェックは不要と判断した。テストを1件追加
  （`test_create_rejects_axis_id_colliding_with_known_material`、既知材料"highway"と
  同名のaxis_idでcreateが拒否されることを確認）。backend全1112件green。

### - [x] T297. car_stressランプ表示のmapping未登録highway（footway/path等）の意味論確定〔P3〕規模S〜M（2026-08-25完了）

- 背景: レビュー指摘（レポートF-3）。評価側はhighway基準値未登録（footway/path等、
  河川敷サイクリングロード等のshared_pedestrian該当を含む）のEdgeを「car_stress未評価」
  （required=Trueにより公開軸ごとNone）とするが、タイル表示側（axisLayers.ts:214〜221、
  registry_defaults.py:434〜438）は同じEdgeを緑（最良側）で塗る。`has_unknown_fallback`が
  **プロパティ欠損**のみを不明扱いし、mapping**未登録値**はmatchのフォールバック0点→
  合計が最小帯→緑になるため。旧`carStressExpression.ts`（T292で削除済み）は未登録highwayを
  センチネル-1（判定対象外）として区別していたが、新しい汎用rampパイプラインではこの区別が
  失われている。T292進捗3自身が「実データでの色の見え方は未確認」と記録した領域に該当する。
- 内容: 実データPlaywright確認（T289と同方式）を行い、以下いずれかを選ぶ。
  1. 「緑のままでよい」と判断する場合: その意味論（未評価=車ストレス実質なし）を
     registry_defaults.pyのnoteへ明記する。
  2. 変えると判断する場合: highwayのTileInputSpecへ「mapping未登録値も不明扱い」の
     オプションを足す（match式のフォールバックをセンチネルにして不明判定へ含める）。
- 影響範囲（保留した場合）: 表示上の意味論のみ（探索・評価は正しい）。実害は小さいが、
  区間インスペクタ（available=False表示）と地図の色が矛盾したまま残る。
- 完了条件: 実データ確認の実施と、上記いずれかの対応（コード変更またはnote明記）の完了。
- **実データ確認（2026-08-25）**: dev DBへ直接クエリし、shared_pedestrian該当
  （highway∈{footway,path} AND bicycle∈{yes,designated,permissive}）のwayが
  **4,148件**実在することを確認した（東京都心南部の投入済み範囲、負荷なしの
  一過性クエリ）。既に一定量発生する事象と確定したため「実害は小さい」の前提を
  再確認したうえで対応方針を決めた。
- **調査で判明した根本原因（対応2を選んだ決め手）**: `has_unknown_fallback=True`は
  highwayのTileInputSpec（registry_defaults.py:437）へ**既に設定済み**だった。
  すなわち「未登録値は不明扱いにする」という意図は元々あったが、実装
  （`axisLayers.ts: buildAxisRampUnknownExpression`）が`!has(property)`
  （プロパティの**欠損**）しか見ておらず、highwayのように**プロパティは常に存在するが
  値が未登録**というケースを検出できていなかった——「決めていなかった」のではなく
  「決めていたが実装が意図どおり動いていなかった」設計と実装の乖離だった。
  さらに評価側（`domain/axis_templates.py: evaluate_categorical`）を確認したところ、
  未登録値は`mapping.get(value, None)`で**None**（寄与0ではなく評価不能）を返し、
  `required=True`の材料でNoneは軸全体（car_stress公開軸）を評価不能にすると確定した
  （registry.pyの旧docstringが「未登録値は0扱い＝CategoricalShapeの評価がNoneを
  返すのと同じ規約」と書いていたのは誤りで、Noneと0は別物だった）。この2点により
  「対応2（未登録値も不明扱いへ変更）」が正しい修正であり、「対応1（緑のまま・
  意味論を明記するだけ）」は評価側の実際の意味論と食い違ったまま追認することになる
  ため採らなかった。
- **対応（コード変更、対応2）**:
  1. `axisLayers.ts: buildAxisRampUnknownExpression`を拡張し、`categories`を持つ
     tile_input（`has_unknown_fallback=True`の場合）はプロパティ欠損に加えて
     「値はあるがcategoriesに未登録」も`match`式で「不明」判定するようにした
     （boolean材料の判定は従来どおり`!has(property)`のみで変更なし）。
  2. `registry.py: TileInputSpec`のdocstringを、`has_unknown_fallback`の実際の意味
     （categories材料では未登録値も不明化する。boolean材料とは扱いが異なる）に
     合わせて訂正した。
  3. 新規コード追加・材料の追加は不要（`car_stress`のhighway入力は既存の
     `has_unknown_fallback=True`をそのまま活かすだけで修正された）。
- テスト: `axisLayers.test.ts`へ1件追加（car_stressのhighway入力について、
  match式が既知highway値をfalse[不明でない]・footway等の未登録値と欠損センチネルを
  true[不明]に分類することを検証、凡例に「不明」エントリが現れることも確認）。
  backend全1112件・frontend全458件green（回帰なし）、tsc/eslint clean。
- **実機（Playwright）確認について**: 着手時点で稼働していたdevサーバー
  （backend:8000・frontend:3010、別セッションのT293検証用と思われる）が、確認直前に
  停止していた（並行セッションの作業終了によるものと推測、CLAUDE.md「作業ツリーの
  安全」に従い自分で新規起動はせず現状を尊重した）。かわりに、変更の正しさを
  (a) dev DBへの直接クエリによる実データ4,148件の存在確認、(b) `evaluate_categorical`
  ソースコードの直読みによるNone/0の意味論の確定、(c) 決定的なMapLibre expression
  単体テストの3点で担保した（過去のPlaywright実機確認で座標特定・セレクタ誤りによる
  誤所見が生じた実績があり、決定的な単体テストで代替できる場合はそちらを優先する
  判断）。地図上のピクセル色を実際に目視する確認は次回devサーバー稼働時に持ち越し。

### - [x] T298. T292削除物を参照する残骸コメントの訂正・種別の削除条件明文化〔P3〕規模S（2026-08-25完了）

- 背景: レビュー指摘（レポートF-4）。削除済みの`carStressExpression.ts`・
  `carStressExpression.test.ts`を現行機構として参照するコメントが残る
  （road_graph_repository.py:224,227・regionApi.ts:22）。ほか
  `BreakpointLinearShape.kind="recipe_then_breakpoint_linear"`（axis_definitions.py:79、
  現行定義では未使用。0014時代のDB行の後方互換パースのためだけに残るが削除条件が
  書かれていない）・`registry.py: kind="bespoke"`（利用軸ゼロ、生成物axis-catalog.jsonで
  確認済み）も同様。
- 内容:
  1. road_graph_repository.py・regionApi.tsのコメント2箇所を、現行の汎用rampパイプライン
     （axisLayers.ts）を指すよう書き換える。
  2. `kind="bespoke"`は利用ゼロのため即時削除する。
  3. `recipe_then_breakpoint_linear`は本番の0017適用状況を確認したうえで、削除可能なら
     削除、不可なら「本番0017適用済み確認後に削除可能」等の削除条件を明文化する。
- 影響範囲（保留した場合）: 次にこの領域を触る実装者が存在しないファイルを探す・
  旧設計を現行と誤認する小コスト。実害はドキュメント品質のみ。
- 完了条件: コメント訂正・`bespoke`削除・`recipe_then_breakpoint_linear`の削除または
  削除条件明文化の3点完了。docsのみ〜数行のコード変更のため挙動への影響なし。
- **対応（2026-08-25完了）**:
  1. `road_graph_repository.py`（217〜229行付近）・`regionApi.ts`（22行）の
     コメントを、削除済みの`carStressExpression.ts`/`carStressExpression.test.ts`
     ではなく現行の汎用rampパイプライン（`axisLayers.ts`、片側importによる同期）を
     指すよう書き換えた。
  2. `kind="bespoke"`（`registry.py: AxisDisplaySpec.kind`）を利用ゼロと確認のうえ
     `Literal`から削除した（`kind="bespoke"`を実際に構築している箇所がgrep0件で
     あることを確認済み）。連動して`axis_display.py`・`axisLayers.ts`の関連コメントも
     「bespoke」表記を除去した。
  3. **`recipe_then_breakpoint_linear`は方針転換: 削除しなかった**。実装着手時に
     `axis_templates.py`の既存コメントを精読したところ、この語彙は「未使用の残骸」
     ではなく、**目論見書の歯止め③（テンプレート4種の線引き）に触れるため保守的に
     残す**という**既に記録済みの意図的なKEEP判断**だったことが判明した
     （レビュー段階ではこのコメントを読み落としており、「後方互換パースのためだけに
     残る」という誤った前提でF-4を起票していた）。起票時の判断を機械的に実行するのでは
     なく、実装時に一次情報（既存コメント）を再確認した結果として現状維持へ方針転換した
     （T295〜T297のような「実装」ではなく「調査の結果、指摘の前提自体が古かった」
     ケース）。削除条件を明文化する代わりに、既存コメントへ明示的なトリガー
     （「目論見書のテンプレート4種自体を見直す時のみ削除を検討」）を追記した。
- backend全1112件・frontend tsc/eslint clean、OpenAPI生成物ドリフトなし
  （`export_openapi.py`再生成→`git diff`クリーンを確認、実行時のINFOログ
  `axes=13 code_only=[] db_only=[]`でT295の差分ログも実データで正常動作を確認）。

### - [x] T299. Tailwind CSS + Radix UI + components/ui/ のデザイン基盤を新設する 規模M（2026-08-25完了）

- 背景: ユーザーから「Tailwind CSS + Radix UI + 自前UIコンポーネント層」をデザイン基盤
  として導入したいという明示的な要望があった。T252でTailwindはCascade Layers込みで
  併用導入済み（`@import "tailwindcss"`、スペーシングスケールも既存`--space-*`と数値
  一致）、`@radix-ui/react-*`もAccordion/Popover/RadioGroup/Toggleの4種が
  `Disclosure`/`LayerChip`/`FieldLabel`で既に実採用され効果を上げているが、これらを
  束ねる共通UIコンポーネント層（`components/ui/`）は存在せず、Tailwindユーティリティの
  実利用はリポジトリ全体でゼロのままだった（T275で採否判断を保留中）。
- 事前調査（3件のExploreエージェント＋1件のPlanエージェント）で、`components/ui/`が
  存在しないこと、汎用Buttonが無く各所で素の`<button>`にCSS Modulesクラスを直接当てて
  いること、カード状コンテナ・チップ/トグル・input系・モーダル系で重複実装があることを
  定量確認した。
- 対応方針:
  - **移行範囲はゼロではなく、定量調査で「本当に同一実装」と確認できた重複7箇所
    （カード状コンテナ2・純レイアウト3・送信ボタン1・CSS Modulesファイル丸ごと削除1）
    を実際に移行する**。「基盤だけ作っても効果が見えない」「汎用的な部品で重複実装
    しているところはある程度置き換えを試してほしい」というユーザーフィードバックを
    受け、当初のゼロ移行方針から修正した。それ以外の既存CSS Modules・既存コンポーネント
    は一切変更しない（大規模な一括置換はしない、という当初方針は維持）。
  - shadcn/ui方式（Radix + Tailwind + `class-variance-authority`(variant管理) +
    `clsx`/`tailwind-merge`(`cn()`ヘルパー)をコピー&オウン、npmパッケージとしての
    導入ではない）を採用。定番ライブラリ優先という既存方針と合致する。
  - 新設プリミティブはButton・Input・Card・Dialog・Checkboxの5種。Select・Tabsは
    現状利用箇所ゼロのため見送り（YAGNI、実需が生じたら追加）。`LayerChip.tsx`は
    既に良い設計のRadix Toggleラッパーのため今回は触れず、汎用Chip化も見送る。
  - Design Tokenはradius(`--radius-sm/md/lg`)とshadow(`--shadow-float`)をTailwindの
    `@theme`へ追加登録（既存`:root`の値は変更せず、値を一致させたまま意図的に重複させる
    ——`:root`はunlayeredで既存27ファイルのCSS Modulesが依存しており、動かすことで
    予期せぬCascade Layers影響を受けるリスクを避けるため）。colorトークンは`@theme`へ
    統合しない（ダークモード追従が壊れるリスクを避ける、T252の判断を踏襲）。
  - 詳細な設計判断（各プリミティブのAPI、移行7箇所の内訳と対象外理由、`@theme`の
    具体的な値）は実装メモ・`docs/frontend-design-system.md`参照。
- 完了条件: `components/ui/{Button,Input,Card,Dialog,Checkbox}`実装・テスト
  （vitest+Testing Library、role/aria基準）完了。移行7箇所の実装・既存テストのgreen
  確認・実画面のBefore/After確認（Playwright）完了。`docs/architecture.md`技術選定表へ
  追従。`docs/frontend-design-system.md`新設。T275を(b)採用として決着。
- **対応（2026-08-25完了）**: 上記方針どおり実装した。
  - `frontend/src/components/ui/{Button,Input,Card,Dialog,Checkbox}`を新設（各21件、
    計21テスト）。`frontend/src/lib/cn.ts`（`clsx`+`tailwind-merge`）、新規依存
    `@radix-ui/react-dialog`・`@radix-ui/react-checkbox`・`class-variance-authority`・
    `clsx`・`tailwind-merge`を追加。
  - `globals.css`へ`@theme`ブロックを追加（`--radius-sm/md/lg`・`--shadow-float`、既存
    `:root`定義とは値を一致させたまま意図的に重複——理由は上記対応方針参照）。
  - 移行7箇所を実施（詳細はコミットログ参照）。当初「6箇所の完全重複」と見ていた
    `.panel`/`.legendCard`/`.card`系クラスを精査した結果、実際には**カード表面
    （背景+角丸+padding、`legendCard`/`admin.card`の2箇所がバイト単位で完全一致）**と
    **純レイアウト（`ComparisonPanel`/`RouteSettingsPanel`/`MapLayersPanel`の`.panel`、
    背景・枠線なしの縦積みのみ）**という2種類の異なるパターンが同じ命名慣習で
    紛れていたことが判明し、前者のみ`Card`へ統合、後者はTailwindユーティリティ直書きに
    留めた（新規コンポーネント化は投機的と判断）。`RouteForm`の送信ボタンは`Button`へ
    （暗黙のグローバル`button[type=submit]`リセット依存を解消）、
    `LocationControl.module.css`（18行）はTailwindユーティリティ化により**ファイルごと
    削除**。CSS Modulesの正味削減は約37行（削除した重複ルール6箇所＋ファイル1つぶん、
    `docs/frontend-design-system.md`参照）。
  - 実装中、`globals.css`の`@theme`直前コメントでコロン直後にroot要素セレクタ名を
    書くとLightning CSS（Tailwind v4のCSSエンジン）がコメント境界を誤認識しビルド
    エラーになる実機不具合を発見・回避した（`globals.css`本文・
    `docs/frontend-design-system.md`に注意書きを残した）。
  - 検証: tsc・vitest（フロント全体479件）・`next build`すべてgreen。Playwright
    headless chromiumでライト/ダーク双方の実画面（トップページ・「地図の見え方」
    展開後・adminページの評価重みカード）を確認、コンソールエラーなし。
    `RouteForm.test.tsx`/`LocationControl.test.tsx`はCSSクラス名を一切アサートせず
    無改修のままgreen（移行成功の直接的な証拠）。
  - `docs/frontend-design-system.md`を新設し使い分け基準・Design Token一覧・意図的に
    作らないもの（Select/Tabs/汎用Chip/Dialog↔FloatingPanel統合）・将来候補
    （colorトークンの`@theme inline`統合）を明文化。`docs/architecture.md`技術選定表へ
    追従。T275を(b)採用として決着。
  - 対象外としたもの: `MapOverlayControls.tsx`のiconChip・`RouteList.tsx`のitemの
    チップ重複解消（`MapOverlayControls.tsx`は563行の中心的な地図UIファイルで直近も
    T292で大きく触られたため、追加リスクを取らず将来タスクへ切り出し）。
- **フォローアップ（2026-08-25、同日中）**: 実装直後の実機確認で、`components/ui/Checkbox`
  （Radix製`<button role="checkbox">`）が`globals.css`のモバイル向けブランケットルール
  （`.app-sidebar/.app-floating-panel/.app-bottom-sheet button`全てに一律
  `min-height: 44px`を強制、T34由来）へ意図せず巻き込まれ、375px幅で30.78×44pxという
  不釣り合いなブロックになる不具合をユーザー指摘で発見した。調査の結果、この「一律適用」
  自体が、`LayerChip`（意図的な36pxピル型）・`RadioGroup.Item`（32px）という**既存の
  正しく設計されたコンポーネントも同様に踏みつぶしていた**（詳細度負けで自前サイズが
  無視されていた）ことが判明し、ユーザー判断により以下へ全面再設計した:
  1. `components/ui/Checkbox`自身に`p-0 min-h-0`を明示（`@layer base button`の既定padding
     はTailwindの`utilities`レイヤーより弱く通常は上書きできるが、対象コンポーネントが
     明示的に宣言しない限り素通しされるため）。
  2. `globals.css`のモバイル向け`button`ブランケットルールを**撤去**。「本当にメインの
     導線だけが44pxを持つ」方針へ転換し、`.app-sidebar`（`isMobile`時は`<aside>`自体が
     レンダーされずこのメディアクエリ内では実質デッドコードだったことも判明）を全セレクタ
     から削除。
  3. 唯一「主要な導線」と判断した`MapLayersPanel.module.css`の`.layerTitle`
     （各レイヤーの開閉見出し）にのみ、コンポーネント自身が`@media (max-width: 640px)`
     スコープで`min-height: 44px`を明示。それ以外（RouteSettingsPanelのプリセット/
     リセットボタン・RouteListの候補選択・MapLayersPanelの一括操作リンク・FieldLabelの
     情報アイコン・DebugConsole/FloatingPanelの閉じるボタン・開発者ブロックの運用ボタン群）
     はブランケット撤去後も意図的にオプトインさせず、自然なサイズのままにした。
  4. モバイル向けinput（44px+iOS自動ズーム防止のfont-size:16px）・label（44px）・
     checkbox（1.4rem拡大）のルールは「特定要素カテゴリ全体に共通し個別コンポーネントの
     意図が入り込む余地がない」ため副作用リスクが無いと判断し維持（`.app-sidebar`は
     同様の理由でこちらも削除、`.app-floating-panel`はチェックボックス/input/labelを
     持つ利用先が無いことを確認の上削除）。
  - 検証: 実機Playwright（375px幅）で`.layerTitle`80.17×**44**px・`LayerChip`
    57.98×**36**px（自前サイズへ復元）・`Checkbox`22.39×**22.39**px（1.4rem）を確認。
    devサーバー再起動後のクリーンな状態でhydration警告も再現しないことを確認（再起動前に
    見えていたものは長時間HMRしたサーバーのSSRキャッシュ起因の見せかけの警告と判明）。
    tsc・vitest（479件）・`next build`すべてgreen。
  - `docs/frontend-design-system.md`へ「globals.cssのグローバルルールに関する方針」節
    （新設9節）として、この事例と再発防止の指針（新しい主要導線はコンポーネント自身へ
    `@media`スコープで明示、globals.cssへブランケットとして戻さない）を明文化した。

## ルート詳細タブのモバイルUI再構成（2026-08-25・ユーザー指示）

### - [x] T300. 「開発者」タブ廃止＋「ルート詳細」タブの設定/結果2分割〔P3〕規模M（2026-08-25完了）

- 背景: ユーザーの実機フィードバック「ルート詳細パネル、下に長い。スマホだと使いにくい」。
  調査の結果、モバイル下部タブ`renderRouteResultsBody()`（page.tsx:1235-1271）内で
  `RouteSettingsPanel`（frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx、
  250行、評価軸カテゴリぶん縦に伸びる）・`RouteList`（53行）・`ComparisonPanel`（122行、
  研究モードのみ）・色分けセクション（`renderRouteColorSectionBody()`、page.tsx:1280-1346）
  が同一パネルに同居しており、これが縦長の主因と判明した。あわせてユーザーから
  「開発者」タブ（`MobileSheet`型のdeveloper、page.tsx:215/1382-1404、実質23行。
  「地図データを再読み込み」ボタン1つ＋debugEnabled時のみのログ表示切替＋
  DebugConsole）は情報量がほぼ無く廃止してよい、ログ機能はどこか別の場所へ
  移動すればよいとの判断が出た。
- 内容:
  1. 「開発者」タブを廃止する。「地図データを再読み込み」ボタンは「地図の見え方」タブへ
     移設。ログ表示切替＋`DebugConsole`（frontend/src/components/DebugConsole/
     DebugConsole.tsx）はヘッダーの小アイコン（`debugEnabled`時のみ表示、モーダル/
     ポップオーバーで開く）へ移設する。
  2. 開発者タブ廃止で空いたタブ枠を使い、「ルート詳細」タブを「ルート設定」
     （RouteSettingsPanel）と「ルート結果」（RouteList・ComparisonPanel・
     色分けセクション）の2タブへ分割する。モバイルのタブ総数は3のまま変わらないため、
     タブバー幅制約（開発者タブが既にアイコン化されている経緯）を回避できる。
  3. 分割に伴い、`conditionsDirty`（設定変更→結果未反映の警告、page.tsx:1238）が
     現状は同一パネル内で完結しているため、分割後は「ルート結果」タブ側にも
     設定変更を知らせる導線（バッジ等）を新設する必要がある。
- 影響範囲（保留した場合）: モバイルでの「ルート詳細」パネルの縦長・スクロール過多が
  未解消のまま残る。ユーザーからは方向性の合意を得ているが、現在別の改修で
  フロントエンドを並行して触っているため、コンフリクトを避けて着手を意図的に
  後回しにしている（作業ツリーの安全ルール参照）。放置しても機能停止には至らないが、
  次にこのタブ配下（RouteSettingsPanel等）へ手を入れる作業が発生した場合、
  本タスクと競合しないか着手前に確認すること。
- 完了条件: 着手時に確定。少なくとも(a)開発者タブ廃止と移設先（地図の見え方タブ・
  ヘッダーアイコン）での動作確認、(b)ルート設定/結果2タブへの分割、
  (c)`conditionsDirty`の結果タブ側導線、(d)Playwright等でのモバイル幅実機確認を含める。
- **トリガー解消（2026-08-25、T299完了）**: 本タスクが待っていた「現在進行中の別
  フロント改修」（T299、Tailwind + Radix UIデザイン基盤の新設）が完了した。着手可能。
- **対応（2026-08-25完了）**: 上記内容どおり実装した。
  1. 「開発者」タブを廃止。モバイルの下部タブバーは「ルート設定」「ルート結果」
     「地図の見え方」の3つへ再構成（タブ総数は3のまま）。「ルート設定」用に新規アイコン
     （`components/Map/icons.tsx`の`RouteSettingsIcon`、スライダー3本）を追加し、
     不要になった`DeveloperIcon`は削除した。デスクトップのサイドバーにあった対応する
     「C. 開発者」`Disclosure`ブロックも、中身が全て移設され空になったため同様に廃止した
     （T300の背景で述べた「情報量が薄い」という判断はモバイル・デスクトップ双方に
     等しく当てはまるため）。
  2. 「地図データを再読み込み」ボタンは`renderMapSettingsSectionBody`（地図の見え方）へ、
     デバッグログ切替＋`DebugConsole`は常設ヘッダー（`weatherHeader`）内の新規アイコン
     ボタン（`LogIcon`、`debugEnabled`時のみ表示）へ移設した。`DebugConsole`自体は
     `FloatingPanel`ベースで自己完結する`position:fixed`コンポーネントのため、
     JSXツリー上の設置場所を変えても見た目は変わらない（移設のみ、実装変更なし）。
  3. `renderRouteResultsBody`を`renderRouteSettingsSectionBody`（`RouteSettingsPanel`
     のみ）と`renderRouteOutcomeSectionBody`（`conditionsDirty`ヒント・空状態ガイド・
     `RouteList`・`ComparisonPanel`・色分けセクション）へ分割。デスクトップの
     「ルートを作る」ブロックは両方を続けて呼ぶことで従来どおり1つの折りたたみに収める
     （`conditionsDirty`ヒントの表示位置が「設定の後・結果の前」へ移る軽微な並び替えのみ、
     デスクトップの見た目への実質的な影響はない）。
  4. 「ルート結果」タブボタンに、設定変更後未反映（`conditionsDirty`）を示す小さいバッジ
     （Tailwindユーティリティで実装、新規CSS Modulesクラスは追加していない）を追加し、
     タブを開かなくても気づけるようにした（完了条件(c)）。
  5. ヘッダーの新規デバッグログボタンは`components/ui/Button`（`variant="ghost"`）を
     使用（ユーザー指示「なるべくTailwind使ってね、共通化の一環」を反映）。一方
     「地図データを再読み込み」ボタンは、意図的にボタンらしくないテキストリンク調の
     見た目（`.refreshButton`、下線+透明背景、運用頻度の低さを見た目で伝える設計）を
     既に持っていたため、`Button`コンポーネントの既存variant（primary/secondary/
     danger/ghost）に無理に当てはめず、既存CSS Modulesのまま維持した（移設のみ）。
  6. T303（同時対応、下記参照）とあわせて実装。
- 検証: `npx tsc --noEmit`・`npx eslint`・`npx vitest run`（フロント全体485件、
  並行セッションが追加した`RouteSettingsPanel.test.tsx`3件も無改修でgreenのまま）・
  `npm run build`すべてgreen。Playwright headless chromium（375px幅、light/dark）で
  実機確認: 3タブの開閉・「ルート設定」タブでの`RouteSettingsPanel`表示・「ルート結果」
  タブでの空状態ガイド表示・「地図の見え方」タブでの再読み込みボタン表示・「開発者」
  タブが存在しないこと・ヘッダーのデバッグログボタン→`DebugConsole`表示、いずれも
  確認しコンソールエラーなし。

## 管理者画面（軸スタジオ）の改善（2026-08-25・ユーザー指示）

### - [x] T301. `/admin`画面のモバイル対応（レスポンシブ未実装の解消） 規模S（2026-08-25完了）

- 背景: ユーザー実機フィードバック「管理者画面、スマホだと見切れてさわれない」。調査の
  結果、`/admin`配下（`frontend/src/app/admin/admin.module.css`・
  `frontend/src/components/AxisStudio/AxisStudio.module.css`・`DebugPanel.tsx`）には
  `@media`クエリが1件も無く、メインページで確立済みの640pxブレークポイント
  （`page.module.css`、`frontend/src/hooks/useIsMobile.ts`）が移植されていないだけと
  判明した（意図的にモバイル非対応としたという設計記述はT270完了記録に見当たらない）。
- 当初の内容案: T299のTailwind CSS + Radix UI基盤（docs/frontend-design-system.md）に
  沿ってcomponents/ui/+Tailwindユーティリティで書き直す想定だった。
- **対応（2026-08-25完了）**: 実装時にPlaywrightで375px幅を実機確認したところ、
  想定していた「固定幅inputのはみ出し」ではなく、**別の根本原因**が見つかったため
  方針を変更した。
  1. **真因**: `globals.css`の`body { display: flex; flex-direction: column; }`により
     `AdminPage`のルート`.page`はbodyのflex item（column方向なのでcross軸=横幅）になる。
     `.page`は`margin: 0 auto`で左右マージンがautoのため、Flexboxの仕様上
     「cross軸のマージンがautoの場合はstretchされず、要素自身のfit-content幅で配置される」
     （align-items:stretchが効かない）。この結果、`.page`は子孫の内容に応じた
     最大幅（実測406px）まで広がり、`html,body`の`overflow-x: hidden`（globals.css）で
     はみ出し分が見えないまま操作不能になっていた（横スクロールにならず「見切れて
     さわれない」という言葉通りの症状）。`admin.module.css: .page`へ`width: 100%`を
     追加し、stretchに頼らず明示的にbody幅へ合わせることで解消した
     （`min-width: 0`も併記、Flexアイテムの既定`min-width: auto`による副作用の再発防止）。
  2. `AxisStudio.module.css`の`.listRow`（軸一覧の行）へ`flex-wrap: wrap`を追加。
  3. 同ファイルの`.listRowActions`（編集/複製/非公開に戻す/削除の最大4ボタン）へ
     `flex-wrap: wrap`を追加し、かつ既存の`flex-shrink: 0`を削除した（`flex-shrink:0`が
     残っていると、`.listRow`が折り返してこのグループが単独行になっても「中身のボタン
     全部ぶんの最大幅」を維持しようとして画面外へはみ出し続け、`flex-wrap:wrap`だけでは
     無意味だった。両方揃って初めてボタンが折り返す）。
  4. `.termRow`・`.breakpointRow`（材料選択select・折れ点input）へも`flex-wrap: wrap`、
     `.field input/select`・`.termRow select`へ`max-width: 100%`を追加（保守的な予防、
     この時点では実際のはみ出しは未確認だが同型の再発を避ける）。
  5. Tailwindへの書き直しは行わなかった（理由: 既存CSS Modulesの不具合修正であり新規
     コンポーネントではない、規模Sの局所修正にTailwind移行という別軸の変更を混ぜない）。
     Tailwind移行自体はT299の対象範囲内で今後の一般的な移行の一部として進む想定。
- 完了条件の実施内容: PlaywrightでDOM全走査し「viewport幅を超える要素」を機械的に検出する
  スクリプトで確認（375px幅、offendersCount 0を確認）。デスクトップ幅（1280px）でも
  同スクリプトでoffendersCount 0を確認済み（回帰なし）。フロントtsc/eslint/vitest
  （482件）全green。

### - [x] T302. 軸の公開→未公開（unpublish）を追加し、既存軸の削除を解禁する 規模M（2026-08-25完了）

- 背景: ユーザーから「公開軸を未公開に戻す拡張はできる？既存軸の削除したい」という要望。
  T271のADR（docs/decisions/t221-axis-registry.md「Stage D拡張2」）はunpublishを
  意図的に持たない一方向設計を採用しており、`AxisRegistryAdminService.delete`
  （backend/app/services/axis_registry_service.py:205-208）のコメントには
  「route_preferenceとの整合性チェックは意図的に未実装、Stage EでGUI編集が実利用される
  段階で改めて検討する」と明記されている。今回のユーザー要望がまさにそのトリガー
  （GUI編集の実利用）に該当するため、方針を決定した（決定内容の詳細は
  docs/decisions/t221-axis-registry.md「Stage D拡張3」参照、本エントリはその要約）。
- 決定内容:
  1. **unpublishは専用アクションとして追加する**（`update()`の一般的な緩和ではなく、
     `is_published: True→False`の遷移だけを許す専用エンドポイント/サービスメソッドを
     新設）。それ以外のフィールド編集は引き続き「公開済みは不変」のまま拒否する。
     unpublish後は既存のupdate()経路で自由に再編集・再publishできる（複製ではなく
     同一axis_idのまま行き来できる、データは失われない）。
  2. **フロントの自己修復とセット実装が必須条件**。`RouteSettingsPanel.tsx:92-105`の
     反映ロジックは現状「カタログにあるがroutePreferenceに無いキーを補う」片方向のみ。
     symmetricに「routePreferenceにあるがカタログに無いキーを削除する」処理を追加する。
     これが無いとunpublish直後、旧設定を保持したブラウザで`RoutePreferenceWeights`の
     キー完全一致検証（backend/app/api/routers/routes.py:78-100）が422で落ち、
     ルート生成そのものが壊れる（サーバ側の永続化は無くブラウザのlocalStorage状態のみが
     問題になる）。unpublish機能と自己修復ロジックは同一コミットで実装すること。
  3. **既存軸の削除**: 現行の「公開済みは削除不可」ガード
     （axis_registry_service.py:202-204）はそのまま維持する。削除したい場合は
     「unpublish→（影響が無いことを確認）→delete」の2段階を正式フローとする。実装変更は
     不要（削除ボタンの活性化条件がis_published=Falseに連動するのは既存ロジックのまま
     自然に成立する）。
  4. **既知の残課題（本タスクでは対応しない）**: 地図側の軸カタログ表示（`registry.py`
     由来の静的`axis-catalog.json`、T285未着手）はis_publishedを動的に反映しないため、
     unpublish直後もしばらく地図の凡例・レイヤーパネルには残りうる。表示のみの影響で
     評価・ルート生成には影響しないため、T285完了までの一時的な不整合として許容する。
- 完了条件: 着手時に確定。少なくとも(a)unpublish専用エンドポイントの実装とテスト、
  (b)RouteSettingsPanelの自己修復ロジック追加とテスト、(c)unpublish→delete一連の
  実機確認（Playwright）、(d)OpenAPI生成物の同期を含める。
- **対応（2026-08-25完了）**:
  1. `AxisRegistryAdminService.unpublish()`（axis_registry_service.py）を新設。
     `is_published`のみをFalseへ反転してupsertする（他フィールドは既存値のまま）。
     既に下書きの軸に対してはべき等（何もしない）。
  2. `POST /api/admin/axis-definitions/{axis_id}/unpublish`（axis_admin.py）を新設し、
     更新後の`AxisDefinitionResponse`を返す。OpenAPI・フロント生成型
     （`api.d.ts`・`openapi.json`）を同期。
  3. `RouteSettingsPanel.tsx`の反映effectを双方向化（`RouteSettingsPanel.tsx:92-113`）。
     従来「カタログにあるが無いキーを補う」だけだったのを、「カタログに無いキーを
     routePreferenceから削除する」処理も同じeffectへ追加した。
  4. `AxisStudio.tsx`に「非公開に戻す」ボタンを追加（`is_published`な軸のみ表示）。
     削除ボタンの説明文言も「先に非公開に戻す」を促す内容へ更新。
  5. `axisAdminApi.ts`に`unpublishAxisDefinition()`を追加。
  6. テスト: backend（`test_axis_registry_service.py`5件・`test_axis_admin_routes.py`4件、
     unpublish→再update・unpublish→delete・べき等性・404を含む）、frontend
     （`RouteSettingsPanel.test.tsx`新設、カタログから消えた軸のキー削除・新しい軸の
     キー補完・既に一致時は呼ばれないことの3件）。backend全1121件・frontend
     tsc/eslint/vitest（482件）全green。OpenAPI再生成→`git diff`クリーンを確認。
  7. Playwright実機確認（375px幅、ローカルPostGIS+backend+frontendを一時起動）:
     軸一覧で「公開済み」バッジの軸に「非公開に戻す」ボタンが現れる→クリックで
     「下書き」バッジへ切り替わる→この時点で「削除」ボタンが活性化する→クリックで
     一覧から消え件数が1つ減ることを確認。デスクトップ幅（1280px）でも、unpublishされ
     カタログから消えたaxis_idキーを含むlocalStorageの`route_preference`が、
     ページ訪問後に自動でそのキーを取り除いた状態へ書き換わることを確認。
  8. **既知の残課題（本タスクの対応範囲外として記録）**: 自己修復
     （項目3）は`RouteSettingsPanel`がマウントされたタイミングで走る。モバイルでは
     このパネルは「ルート詳細」タブ（BottomSheet）を開いたときにしかマウントされず、
     ヘッダーの生成ボタン（T250でパネルと分離済み）は直接押せてしまうため、
     「過去に一度でも重みをカスタマイズ済み（`weightOverrideEnabled`永続化済み）の
     ユーザーが、軸のunpublish後にモバイルで『ルート詳細』タブを一度も開かずに
     いきなり生成ボタンを押す」という狭い経路では、自己修復が間に合わず422になる
     可能性が残る。これはT269（新規軸追加時の補完）の時点から存在する同型の
     未解決経路であり、本タスクで新たに作った問題ではないが、解消もしていない。
     影響範囲（保留した場合）: 上記の狭い条件（要weightOverrideEnabled=true＋
     unpublish発生＋モバイルでタブ未オープンのまま生成）でのみ422が起こりうる。
     解消するには生成リクエスト組み立て時（page.tsx側）にも同様のキー整合チェックを
     持たせる設計変更が必要で、規模はS〜M程度。次に「ルート詳細タブを開かず生成できる」
     導線（T250）やroute_preferenceまわりを触るタスクの際に、あわせて解消を検討すること。

### - [x] T303. route_preferenceのキー整合チェックを生成リクエスト組み立て時にも持たせる〔P3〕規模S〜M（2026-08-25完了）

- 背景: T302完了時に発見した既知の残課題（本ファイルT302「対応」項目8参照）。
  `RouteSettingsPanel`の自己修復（カタログと`routePreference`のキー集合を合わせる処理、
  T269・T302）は同パネルがマウントされたときにしか走らない。モバイルでは「ルート詳細」
  タブ（BottomSheet）を開いたときにしかマウントされないが、生成ボタン自体はT250で
  ヘッダーへ分離済みのため、タブを一度も開かずに生成できてしまう。
- 内容: 「過去に重みをカスタマイズ済み（`weightOverrideEnabled`永続化済み）のユーザーが、
  軸の追加/unpublishが起きた後、モバイルで『ルート詳細』タブを一度も開かずに生成ボタンを
  押す」という経路で、`RoutePreferenceWeights`のキー完全一致検証（routes.py）が422になる
  可能性が残っている。生成リクエスト組み立て時（page.tsx側、`weightOverrideEnabled`が
  trueの場合のroute_preference送出箇所）にも、`RouteSettingsPanel`と同じキー整合チェック
  （カタログにない古いキーを送信直前に落とす、または送信前にカタログを取得し直す）を
  持たせる。
- 影響範囲（保留した場合）: 上記の狭い条件（重みカスタマイズ済み＋軸の追加/unpublish＋
  モバイルでタブ未オープンのまま生成）でのみ422が起こりうる。発生頻度は低いと想定される
  （軸の追加/unpublish自体が稀な管理操作であり、かつその直後にタブを開かず生成する
  ユーザーという狭い交差条件のため）が、発生した場合はエラーメッセージだけでは原因が
  分かりにくく、ユーザーがルート生成できない状態に見える。
- 完了条件: 着手時に確定。少なくとも上記の経路を再現するテスト（新しい軸の追加/
  unpublish直後、パネル未マウントのまま生成リクエストを組み立てるケース）を含める。
- **対応（2026-08-25完了、T300と同時実施）**: `RouteSettingsPanel.tsx`のキー整合ロジック
  （`useEffect`本体）を純粋関数`syncRoutePreferenceKeys`（新規
  `frontend/src/lib/routePreferenceSync.ts`）へ抽出した。`RouteSettingsPanel.tsx`は
  この関数を呼ぶだけに変更（**挙動は一切変えていない**——並行セッションが直前に追加した
  `RouteSettingsPanel.test.tsx`3件が無改修のままgreenで通ることで確認済み）。
  `page.tsx`に`useAxisCatalog()`を新規追加し、`handleGenerate`内で`generateRoutes`呼び出し
  直前に`weightOverrideEnabled`が真の場合のみ`syncRoutePreferenceKeys(routePreference,
  catalog.defaultWeights)`を適用し、`null`でなければ補正後の値を送出する。
  `routePreference` state自体は書き換えない（完了条件どおり「生成リクエスト組み立て時」
  だけの穴埋めに留めた。`RouteSettingsPanel`が別途マウントされれば従来どおりstate自体も
  修復される）。`frontend/src/lib/routePreferenceSync.test.ts`（新規、3ケース: 不足キー
  補完・余剰キー削除・変更なしはnull）で検証。frontend全体485件green。

### - [x] T304. 軸スタジオのUX改善（編集モーダル化・説明文追加・研究モードの重み整理） 規模M（2026-08-25完了）

- 背景: ユーザー実機フィードバック「軸スタジオが使いにくい」の3点。(1)利用方法が
  分かりにくい、(2)「編集」ボタンを押した後にそのまま編集画面がポップアップ起動して
  ほしい（下部エリアの編集エリアまで目が行かない）、(3)研究モードの評価重み部分は必要か。
  調査の結果:
  - (2)は事実。以前はeditingAxisIdをセットするだけで、一覧の下・ページ全体でも実質
    最下部にある単一のAxisComposerが再レンダリングされる構造で、自動スクロールも無かった。
  - (3)はWeightPanelが実は2種類の重みを扱っており、半分だけ「はい」だった。
    `routePreference`（軸ごとの重み）はAxisComposerの`default_weight`と中身が同じ概念で、
    さらに一般向けルート設定画面（RouteSettingsPanel、`/`）とも同一のlocalStorageキーを
    共有しており、より分かりやすい編集UI（チェックボックス+スライダー、分類・プリセット
    付き）が既に存在する重複だった。一方`scoringWeights`（候補ルート同士を比べる3次評価、
    距離/獲得標高/風/舗装率の4値）はAxisStudio側に対応するUIが無く、削除すると調整手段が
    完全に無くなるため必要。
- 対応内容:
  1. **編集モーダル化**: `AxisStudio.tsx`に`creatingNew`状態を追加し、
     `editingAxisId !== null || duplicateFrom !== null || creatingNew`を`composerOpen`として
     `components/ui/Dialog`（Radix Dialog、T299導入）で開閉するモーダルへ変更した。
     「編集」を押すとその場でAxisComposerの内容がモーダルとして即座に開く。「+ 新しい軸を
     作る」ボタンを新設（以前は常時表示のフォームがその役割を兼ねていた）。ダイアログの
     デフォルト幅（min(90vw,28rem)）はAxisComposerの可変長リスト（材料/折れ点/フラグ）には
     狭いため、`w-[min(94vw,42rem)] max-h-[85vh] overflow-y-auto`で拡張した。
  2. **説明文の追加**: `AxisComposer.tsx`の主要フィールド（axis_id・表示名・分類・
     既定重み）へ`FieldLabel`（WeightPanelと同じinfoアイコン+ポップオーバー部品）で
     説明ツールチップを追加。変換テンプレート(shape)は選択時にその意味・具体例を1文
     表示するようにした（`SHAPE_KIND_DESCRIPTIONS`）。「公開する」チェックボックスは
     中身（shape設定）を決めた後に来るよう並び順を変更。`AxisStudio.tsx`の一覧上部にも
     基本的な使い方（編集/複製/公開軸の扱い）を1段落で追加した。
  3. **WeightPanelの整理**: 「区間難易度の重み」（routePreference、2次要素）の
     Disclosureグループを撤去。「おすすめ度の重み」（scoringWeights、3次）のみを残し、
     入れ子だったdetails折りたたみも1グループのみになったためフラット化した。
     `renderPreferenceFieldExtra`・`admin/page.tsx`側の`renderAxisMaterialsExtra`（材料
     一覧の差し込み枠、2次グループ専用だった）も不要になったため削除。
- **並行作業とのコンフリクト**: 実装中にmasterでT299フォローアップ（Checkbox巨大化バグ
  修正、`components/ui/Checkbox`への置き換え）が並行してマージされ、`AxisComposer.tsx`の
  同じ「公開する」チェックボックスがコンフリクトした。マージ時に解消し、移動後の位置でも
  ネイティブ`<input type="checkbox">`ではなく新しい`<Checkbox>`コンポーネントを使うよう
  統一した。
- テスト: `AxisStudio.test.tsx`（新設、編集/新規作成でモーダルが即座に開く・閉じると
  一覧が残る・非公開に戻すボタンの表示条件の4件）、`WeightPanel.test.tsx`（2次グループ
  撤去に合わせて全面書き換え）。frontend全484件green、tsc/eslintクリーン。Playwright
  実機確認（複製モーダルの即時起動・shape説明文の表示・FieldLabelツールチップの動作・
  WeightPanelから2次セクションが消えていること）済み。
- 既知の残課題: AxisComposer自体の複雑さ（フィールド数・shape種別ごとの動的リスト）は
  今回のスコープ外（モーダル化・説明追加のみ）。将来的にさらに使いやすくする余地は
  あるが、今回の3点の指摘には対応済み。

### - [x] T305. 軸スタジオの使いにくさ（二重ログイン・axis_id・分類・z-index） 規模M（2026-08-25完了）

- 背景: T304に続くユーザー実機フィードバック4点。
  1. 「Basic認証でログインしたユーザに紐づく評価軸だけを出して（管理者ユーザ名やパスワード
     欄は不要）」——`/admin`ページ自体は既に`proxy.ts`でBasic認証済みなのに、軸スタジオ
     画面内でもユーザー名/パスワード入力を求める二重ログインになっていた（backend別
     オリジンへの直接呼び出しのため、ブラウザがproxy.ts分の認証情報を自動転送しない
     ことが原因）。
  2. 「編集画面で情報アイコン（！）を押すと後ろに隠れて見えない」——T304で追加した
     `FieldLabel`のPopover（z-index:46）が、同じくT304で導入した編集モーダル
     （`components/ui/Dialog`、z-index:50）より背面になっていた。
  3. 「axis_idはシステムが勝手に一意な何かを自動採番してくれればよい。設定画面に
     不要では？画面上は表示名があればよい」。
  4. 「分類は「推定」のみのはず。軸スタジオから材料である観測や動的が生み出せると
     おかしい」。
  5. （ユーザーからの追加指摘）「説明文言がべた書きで全般的にみにくい」、
     「画面の説明で（改善計画T270）とか要らない」。
- 対応内容:
  1. 同一オリジンのNext.js route handler（`frontend/src/app/admin/api/axis-definitions/`
     配下、`lib/adminApiProxy.ts`）を新設し、軸CRUD APIの呼び出し先をbackend直叩きから
     これへ変更した。このパスは`proxy.ts`のmatcher（`/admin/:path*`）に含まれるため、
     ブラウザは`/admin`読込時に一度入力したBasic認証情報を、同一オリジン・同一realmへの
     後続リクエストへ自身の認証キャッシュから自動付与する（ブラウザ標準の挙動）。
     route handler側はサーバー環境変数`ADMIN_BASIC_AUTH_USERNAME`/`PASSWORD`（proxy.tsが
     既に使っている値と同じ、運用上backend側と揃える既存方針のまま）からbackend宛の
     Authorizationヘッダを組み立てて転送するため、backend向けの資格情報はブラウザへ
     一切露出しない。旧`lib/adminToken.ts`・`hooks/useAdminCredentials.ts`は撤去し、
     `AxisStudio.tsx`のユーザー名/パスワード入力欄・保存ボタンも削除した。
  2. `recipeControls.module.css: .infoTooltip`のz-indexを46→60へ引き上げ（Dialog[50]より
     確実に上）。
  3. `AxisComposer.tsx`からaxis_id入力欄を撤去し、`crypto.randomUUID()`由来の値を
     新規作成・複製時に自動生成する`generateAxisId()`を追加した。編集時は既存の
     axis_idをそのまま使う（画面には出さない）。
  4. `AxisComposer.tsx`から分類(category)の選択欄を撤去し、送信payloadで常に
     `category: "推定"`を送るよう固定した（`Draft`型自体からも`category`フィールドを
     削除）。一覧表示（`AxisStudio.tsx`）では既存軸の分類は引き続き表示する
     （建付け軸[観測/動的]の情報自体は有用なため、作成フォーム側だけを制約した）。
  5. `AxisStudio.tsx`の使い方説明を1段落のべた書きから箇条書き（`<ul>`）へ整理し、
     `admin/page.tsx`のsubtitleから「（改善計画T270）」等の内部タスク番号参照を削除した。
- テスト: `AxisStudio.test.tsx`にログイン欄が無いことの確認テストを追加、既存テストを
  axis_id非表示・表示名基準のダイアログタイトルへ更新。frontend全488件green（T303の
  マージによる`routePreferenceSync.test.ts`込み）、tsc/eslintクリーン。Playwright実機
  確認: ログイン画面を経由せず軸一覧が読み込まれること、新規作成モーダルにaxis_id/
  分類欄が無いこと、材料排他制約に配慮した軸を実際に作成し一覧へ`category: 推定`・
  自動採番されたaxis_id（title属性）で反映されることを確認、情報アイコンのツールチップが
  モーダルより前面に表示されることをスクリーンショットで確認。
- **並行作業とのコンフリクト**: 実装中にmasterでT300（モバイルタブ再編）・T303
  （route_preference整合性、`RouteSettingsPanel.tsx`の反映effectを`lib/
  routePreferenceSync.ts`へ共通化）が並行してマージされ、`admin/page.tsx`が軽微に
  コンフリクトした。マージして解消（開発者ブロックのヒント文言更新はT300側、
  subtitleの改善計画番号除去は本タスク側、双方とも保持）。
- 完了条件: 上記4点の実機フィードバックと追加指摘2点への対応、テストgreen、
  docs/architecture.mdの認可設計節の追従。すべて満たして完了。

## ルート設定画面のカテゴリ表示撤去とプロファイル構想（2026-08-25・ユーザー指示）

### - [x] T306. ルート設定画面のカテゴリ別グルーピング表示を撤去 規模S（2026-08-25完了）

- 背景: ユーザーからの質問「ルート設定で、重み配分できる観測、動的要素はどれを出す、
  出さないは何で決まる？」に対し調査の結果、以下を回答した。①表示可否は
  `GET /api/axis-catalog`の`is_published`で決まる。②観測/推定/動的のグルーピングは
  各軸の`category`フィールドで決まる。③T305でGUI作成軸のcategoryが常に`"推定"`固定に
  なったため、実際には観測/動的グループへ入るのはコード内蔵の既定5軸（観測:
  `gradient`/`surface_q`/`stop_density`/`night`、動的: `wind`）のみになっている。
  続く質問「全観測、動的グループのうち、どれをルート設定に出すかはハードコードされてる
  ので合ってる？」には、「候補プール（観測/動的になり得る軸の集合）は
  `axis_definitions.py`にハードコードされているが、実際の表示可否は可変の`is_published`
  フラグ（軸スタジオの公開/非公開ボタンでコード変更なしに切替可）で制御される」という
  半分Yes・半分Noの構造を回答した。これを受けたユーザー最終指示:
  「ハードコードの部分はなくしたい。観測、動的カテゴリも条件そのままだったとしても
  推定要素でラップし、推定要素かつpublishedのみをルートの見せ方では表示して。これに
  合わせてgui上の見え方グルーピングも不要」。
- 対応方針: `category`という分類データ・判定基準（T267で確定した観測/推定/動的の境界例
  判断を含む）自体はbackend側にそのまま残す（軸スタジオの一覧表示等の他用途のため。
  なお下記T307「プロファイル」は0次除外＋重み配分のプリセットをマスタ化する別概念で、
  `category`とは直接関係しない）。変更対象はあくまで**ルート設定画面（RouteSettingsPanel）
  の表示方法**のみとし、公開済み軸をカテゴリに関わらずフラットな1本のリストとして
  表示するよう変更する（＝ユーザーの
  言う「推定要素でラップ」を、表示側でカテゴリの区別自体をしないことで実現）。GUI側の
  見え方グルーピング（軸スタジオの一覧表示）は本タスクでは変更しない
  （軸スタジオの一覧はcategoryを情報として見せているだけでグルーピング表示ではなく、
  ユーザー指摘の「gui上の見え方グルーピング」はRouteSettingsPanel側の3見出し表示を
  指すと判断）。
- 対応内容:
  1. `frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx`: カテゴリ別に
     `AXIS_CATEGORIES`をmapして見出し（`.groupHeader`）付きの3グループへ分けていた
     描画を、`catalog.axes`をそのまま1つの`.group`へ並べるフラット表示へ変更。
  2. `frontend/src/hooks/useAxisCatalog.ts`: `AxisCatalog`インターフェースから
     `categoryOf`（axis_id→categoryの引き当て関数）を削除、`buildCatalog`も
     `categoryByAxisId`の構築をやめた。backend側`GET /api/axis-catalog`のレスポンス自体は
     引き続き`category`フィールドを含む（このhookが単に消費しなくなっただけ）。
  3. `frontend/src/lib/evaluationAxes.ts`: 唯一の消費者が無くなった
     `AxisCategory`型・`AXIS_CATEGORIES`定数・`axisCategory()`関数を削除し、削除理由と
     復元方法（git履歴参照）を説明するコメントへ置き換えた。
  4. `frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.module.css`:
     未使用になった`.groupHeader`ルールを削除。
- **設計判断の反転について**: 本タスクはT267で確定した「観測/推定/動的の3カテゴリ別
  グルーピング表示」という意図的な設計判断を反転させるもの。反転理由はT267時点では
  想定していなかったT305の副作用（GUI作成軸のcategory固定化によるハードコードされた
  非対称性）であり、`category`という分類データ・境界例判断自体（T267実装メモ参照）は
  誤りだったわけではないため保持する。
- テスト: `tsc --noEmit`・`eslint .`・`vitest run`（488/488件）すべてgreen。Playwright
  で`http://localhost:3000/`（frontend単独起動、DB無しのため静的フォールバックカタログ
  使用）を確認し、RouteSettingsPanelが勾配・風・舗装質・停止密度・車の圧迫感・事故密度・
  夜間の7軸を見出し無しの1本のリストとして表示することをスクリーンショットで確認。
  併せて`text=/^(観測|推定|動的)$/`が3件マッチする点を調査したが、これは
  `MapOverlayControls`（地図チップ、`mapLayers.ts: MAP_LAYER_DATA_NATURE_SHORT_LABELS`）
  側の`dataNature`（raw/composite/dynamic）グルーピングによるもので、
  RouteSettingsPanelのaxis `category`とは無関係な別概念（T166で確定済み）であることを
  ソース側で確認し、リグレッションでないことを確認した。
- 完了条件: 上記の表示変更、テストgreen、docs/architecture.md追従（コンポーネント一覧の
  RouteSettingsPanel説明を更新）。すべて満たして完了。

### - [ ] T307. プリセット（プロファイル）機能のマスタ化 規模M〜L（トリガー未到達・保留）

- 背景: T306でRouteSettingsPanel側のカテゴリ別グルーピング表示を撤去した際、ユーザーから
  補足指示があった：「プロファイルね。将来的に公開する推定軸が蒸留しきってから整備
  したい。これもマスタで整備できるようにしたいかな。」——当初は軸の観測/推定/動的分類の
  マスタ化と誤って解釈したが、後続のやり取りでユーザーが「プロファイル」と呼んでいるのは
  別概念だと判明した。正しくは: **0次除外（`hard_filters`）＋軸の重み配分
  （`route_preference`）＋名前をひとまとまりにしたテンプレート**（例:「最短距離」）の
  ことで、現行の`RouteSettingsPanel.tsx`の`PRESETS`/`NON_DEFAULT_PRESETS`
  （「自転車専用道を優先」「最短時間重視」「安全重視」等、改善計画T267導入）の
  **メンテナンス機能のイメージ**——現状フロントのTypeScript配列にハードコードされている
  プリセット定義（かつ`hard_filters`は含まず`route_preference`のみ）を、軸スタジオと
  同様にマスタデータとして管理画面から追加・編集できるようにしたい、という意図。
  ①今は実装せず将来のタイミング（後述トリガー）まで保留する、②実装する際はハードコード
  ではなくマスタデータとして整備したい、という2点は当初の理解通り変わらない。
- 保留する理由と、保留し続けることでブロックされる影響範囲（CLAUDE.mdの保留起票ルール
  に基づき明記）: プリセットは軸の重み配分の具体的な数値を持つため、公開軸の集合・既定重み
  自体がまだ流動的（T267完了直後で軸スタジオの実運用が始まったばかり、公開`推定`軸が
  増減し続けている段階）だと、マスタ化した先からプリセット内容の手直しが頻発し設計が
  空転する可能性が高い。保留し続けても、既存の4プリセット（ハードコード）は現状のまま
  問題なく動作し続ける（本タスクを着手しないことで壊れる既存機能は無い）。ブロックされる
  のは「プリセットを管理画面から追加・編集できる」という運用上の柔軟性のみであり、
  緊急性は無い。
- トリガー条件: 「将来的に公開する推定軸が蒸留しきってから」（ユーザー原文）——具体的には
  軸スタジオ経由で追加された`推定`軸が一定数公開され、その重みを織り込んだプリセットの
  構成（どの軸をどの程度使うか）が実際の利用を通じて安定した時点。現時点ではこの条件に
  達しているか判断する材料が無いため、着手タイミングの判断は都度ユーザーへ確認する。
- 対応方針（着手時の設計メモ、保留中は変更しない）: `axis_definitions`のようなDBテーブル
  （例: `route_profiles`）を新設し、`{name, hard_filters, route_preference}`をレコードとして
  持たせ、軸スタジオと同様の管理画面（例:「プロファイルスタジオ」）から追加・編集・
  公開/非公開を制御できるようにする想定。RouteSettingsPanelの`PRESETS`配列は
  `useAxisCatalog`と同様の取得hookへ置き換える。既定の「バランス」プリセット
  （`catalog.defaultWeights`をそのまま使う特別枠、T267実装メモ参照）を新方式でどう
  扱うかは着手時に再検討する。
- 依存: 特になし（トリガー条件の充足待ち）。

### - [x] T308. 推定軸の地図表示自動連動 規模M〜L（実装完了）

- 背景: ユーザーからの質問「管理画面で公開した推定要素のみ、地図上でアイコン表示する
  ようにできている？材料はモジュール修正が必要なのは理解できるが、推定軸はあくまで
  既存合成した結果。推定軸と地図・凡例は連動させたい」を受けて調査した結果、
  **現状はできていない**ことが判明した。地図レイヤーの動的部分（`RAMP_AXES`）は
  実行時API（`GET /api/axis-catalog`、is_published切替が即反映）ではなくビルド時静的
  生成物（`axis-catalog.json`）を単一ソースにしており、その生成元レジストリ
  （`registry_defaults.py: _register_axes()`）自体が既存7軸のみのハードコードで、
  軸スタジオで作成・公開した軸を走査する経路が無い（Gap 1: 配信経路）。加えて、
  地図表示ルールの自動導出関数（`domain/axis_display.py: derive_ramp_inputs`）が
  対応できる材料構成が狭く（単一材料の軸のみ）、GUIの標準的な軸作成手段
  （複数材料の重み付き結合）で作った軸の多くは自動導出の対象外になる
  （Gap 2: 導出ロジック）。ユーザーへの確認により「推定軸の色分けはMVTタイルに
  焼き込まれていない・タイルの材料の生値から軸の合成式で導出できるはず」という認識が
  合っていることを確認し、「推定軸の材料によって対応が変わる。動的要素や向きのある
  観測要素は時間・有向表現の別途検討が要る」という補足も得た。
- 対応方針: 上記2ギャップを解消する設計を`docs/decisions/
  t308-axis-map-display-auto-derivation.md`へまとめた。要点:
  1. **Gap 1**: `axis_display_for()`という純粋関数（`AXIS_DEFINITIONS`/
     `MATERIAL_CATALOG`のみを見る、DB/IO無し）を新設し、`GET /api/axis-catalog`の
     レスポンスへ`display`フィールドを追加。フロントの`RAMP_AXES`取得を
     `useAxisCatalog.ts`と同じ「実行時フェッチ＋静的フォールバック」パターンへ切替え、
     ビルド時生成物への依存を解消する。
  2. **Gap 2**: `derive_ramp_inputs`の制約（`CategoricalShape`はbool2値のみ、
     `BreakpointLinearShape`は単一材料・weight=1.0のみ）のうち、`BreakpointLinearShape`の
     複数材料重み付き結合は`shape.breakpoints`のx値をそのまま閾値に流用できることが
     数学的に導けるため撤廃可能、`CategoricalShape`のstr N値マッピングも
     `TileInputSpec.categories`（既存機能）で対応可能と判明。一方、`preprocess="abs"`は
     フロント側expression未対応のため当面対象外のまま。
  3. ユーザー指摘を受け、`MaterialSpec`へ`tile_property_direction_dependent`
     （方向依存材料の除外フラグ、新設）を追加し、方向依存・実行時スケール変換要・
     タイル非依存の材料を含む軸は安全側で`kind="none"`（地図に出さない）へ倒す設計とした。
  4. Stage A（Gap2・backend単独）→Stage B（Gap1・backend API＋frontend）の2段階を想定
     （Stage BがStage Aの汎用化を前提とするため）。
- 現状: Stage A（`derive_ramp_inputs`汎用化・`MaterialSpec.tile_property_direction_dependent`
  追加）・Stage B（`axis_display_for()`新設、`GET /api/axis-catalog`への`display`フィールド
  追加、フロント`RAMP_AXES`/`MAP_LAYERS`/`SECONDARY_AXES`等を`useAxisCatalog`経由の実行時
  フェッチ＋静的フォールバックへ切替）とも実装完了。既存7軸の地図表示（ramp閾値・色・
  レイヤー構成）が旧静的生成物と一字一句一致することをテストで担保。
  実装中にユーザーから追加要望を受け、当初設計（Gap1・Gap2）の範囲を超えて
  以下も同一の流れで解消した:
  - **materials統一**: `axisMaterials`/`axisMaterialLayerIds`（`primaryAttributes.ts`）が
    静的json専用の`inputs`フィールド参照のまま残っており、軸スタジオ作成軸には
    「材料の共起ケーシング」「材料一覧ノート」UIが効かないギャップが判明。
    `MaterialSpec.primary_attribute_id`（material_id→attr_idの対応）を新設し、
    `AxisCatalogEntry.primary_attribute_ids`（`car_stress`のような内部軸参照を再帰解決した
    attr_id一覧）をAPIへ追加。フロントは`primaryAttributeIdsToLayerIds(attrIds)`という
    純関数へ置き換え、ライブデータのattr_idを直接渡す形に統一。
  - **STATIC_FILTER_AXES統一**: 上記と同じ「静的RAMP_AXES依存」パターンが凡例の値
    フィルタリング（`staticAttributeLayers.ts`）にも残存していたため、
    `buildStaticFilterAxes(rampAxes)`関数化＋静的フォールバックの型で統一。
  - 既存軸だけ特別扱いしている箇所の洗い出しを実施。上記2件は解消、他は
    「意図的に残す（例: 車速換算等ドメイン固有の表示ロジック）」「対象外
    （動的ramp・向き依存表現は本タスクのスコープ外、T308冒頭の背景参照）」の
    いずれかに分類し、削除対象の死んだコードは合わせて除去した
    （`CatalogAxisInputs`/`AXES_WITH_INPUTS`等）。
  - 実機確認: フロント/バックエンド両サーバーを起動しPlaywrightで確認。
    `GET /api/axis-catalog`への実行時フェッチが発生していること（4回、200）、
    RouteSettingsPanel・MapOverlayControlsがライブレスポンスの重み・軸一覧で描画される
    こと、`車の圧迫感`（car_stress、内部軸再帰解決のケース）の材料ノートが
    「材料: 道路種別・インフラ・指定路線／地図では未表示の材料: 制限速度・車線数・
    車両可否」と期待通り分割表示されることを確認。地図タイル本体（MapLibreの背景地図
    スタイル取得）は本番タイルサーバーへの外部到達性が無いサンドボックス環境の制約で
    502となったが、これは本タスクの変更と無関係。
- 完了条件: 達成済み（上記実機確認・全テストスイート[backend pytest 977 passed / 152
  skipped、frontend tsc・eslint・vitest 491 passed]がすべてクリーン）。
  docs/architecture.md追従はこのコミットで実施。
- 依存: なし（T278[derive_ramp_inputs新設]・T292[car_stressのramp化]の上に積んだ）。

### - [x] T309. ルート詳細レスポンス（RouteSegmentDetail/RouteCandidate）の軸別内訳を汎用化 規模M（実装完了）

- 背景: T308（推定軸の地図表示自動連動）完了後の洗い出しで、地図表示・評価・materials
  経路は軸スタジオ作成軸まで汎用化された一方、**ルート詳細のセグメント別内訳レスポンス**
  （`backend/app/domain/route.py`）だけは既存軸限定の固定フィールドのまま残っていることを
  確認した。具体的には`RouteSegmentDetail`が`elevation_difficulty`/`wind_difficulty`/
  `road_difficulty`/`stop_difficulty`/`car_stress_difficulty`/`accident_difficulty`/
  `night_difficulty`という7個の固定フィールド（既存7軸1対1）を持ち、
  `road_graph_engine.py`/`openrouteservice_engine.py`が`axis_scores.get("gradient")`等で
  個別に埋めていた。当初は着手を保留していたが、T317（`night`軸非公開時の
  `RoutePreference.with_weight`ValidationError、本番500）の対応中にユーザーから
  「対症療法はやめてください。デッドコードを無視してOKにするのはやめてください。
  推定軸の数は可変にしたい。7つの軸がデフォルトな考え方は捨ててほしい」との明確な
  再指示を受け、本タスクとして着手した（AskUserQuestionで実施タイミングを確認済み、
  ユーザー回答「今回やる（推奨、ユーザー意図に忠実）」）。
- 対策: `RouteSegmentDetail`の固定7フィールドを`axis_difficulties: dict[str, float]`
  （axis_id→difficulty、`Field(default_factory=dict)`）＋`difficulty: float | None`
  （総合難易度）の汎用構造へ置き換えた。評価できなかった軸はキー自体を含めない
  （`compute_edge_axis_scores`・`evaluate_axis_difficulties`と同じ「データ無しはキーを
  持たない」規約に統一）。
  - `road_graph_engine.py`/`openrouteservice_engine.py`: 個別代入（7回のkwarg）を
    `axis_difficulties=axis_scores`（またはNoneを除いたdict内包表記）1行へ置き換え。
  - `domain/route.py`: `aggregate_segments_into_bins`のビン集約に`_merge_axis_difficulties`
    （axis_idごとの距離加重平均、ビン内のどのセグメントにも無いaxis_idは結果にも含めない）
    を新設。
  - フロント`routeStyleModes.ts`: `buildSteppedMode(field: string, ...)`を
    `buildSteppedMode(valueExpression: unknown[], ...)`へ一般化し、MapLibre式を
    `["get", field]`から`["get", "wind", ["get", "axis_difficulties"]]`（ネストget）へ
    変更。`MapView.tsx`・`MapView.bench.ts`等の呼び出し側・テストを追従。
  - OpenAPI（`export_openapi.py`）・フロント型（`npm run generate:api`）を同一コミットで
    再生成。
- 最終確認（ユーザー指示）: 「7軸に対応する物理名、ALIAS、変数名でgrepして、コメント行
  以外存在しないことを確認してからこのタスクは完了にしてください」との明示指示に従い、
  `elevation_difficulty`/`wind_difficulty`/`road_difficulty`/`stop_difficulty`/
  `car_stress_difficulty`/`accident_difficulty`/`night_difficulty`をbackend/frontend
  全体でgrepし、残る一致がすべて (a) `domain/difficulty.py`・`domain/night.py`の
  無関係な既存関数名、(b) コメント、のいずれかであること（`RouteSegmentDetail`の
  旧フィールドとしての実参照が0件）を確認した。生成物（`openapi.json`/`api.d.ts`）に
  残っていた旧7フィールドの型定義もOpenAPI再生成で解消済み。
- 実機検証（ユーザー指示「実機テストをしてからだ手戻りが大きいので、先にやって下さい」
  に基づき、pushして本番デプロイする前にサンドボックス内でbackend/frontendを実際に
  起動して検証）:
  - サンドボックスにPostgreSQL 16+PostGISを導入し、migrations（0014〜0019の軸レジストリ
    分）を適用した実DBに対しroad_graphエンジンでbackendサーバーを起動。合成の8角形道路網
    （8ノード・16 Directed Edge）を投入し、実HTTPで`/api/routes/generate`を叩いて
    `axis_difficulties`が辞書として正しく返ることを確認。
  - **T316フォローアップ・T317の実障害シナリオをこの実サーバーで再現・確認**:
    軸スタジオAPI（`/api/admin/axis-definitions/night/unpublish`）で`night`軸を非公開化
    →ルート再生成→500にならず200、`route_preference`・`axis_difficulties`双方から
    `night`キーが正しく消えることを確認。さらにユーザーの本番と同じ状態（公開軸が
    wind/surface_q/accidentの3軸のみ）まで追加で非公開化しても200のままであることを
    確認し、「軸の数は可変」という意図が実際に守られていることを実証した。
  - frontendもNext.js dev serverを実起動し、Playwrightで実ブラウザから「ルート生成」
    ボタンをクリックする実操作を行い、生成された候補一覧・重み配分パネル（軸スタジオ
    DB由来の7軸が動的に表示される）・「総合難易度」色分けモードの切り替えまで、
    JSエラー0件で完走することを確認（地図タイル自体の描画はサンドボックスの外部
    ネットワーク遮断により失敗するが、本タスクの変更と無関係）。
  - 検証後、サンドボックス内のテスト用DB・サーバープロセス・一時スクリプトはすべて
    後片付け済み（リポジトリへは残さない）。
- 検証: backend pytest 997 passed（非PostGIS）＋実DBでのPostGIS統合テスト群も同一
  セッションで実行しグリーンを確認、ruff（触れた行に新規指摘なし、既存の無関係な
  指摘のみ）。frontend vitest 503 passed、eslint clean、tsc --noEmit
  （既存の無関係な`layout.tsx`エラーのみ残存）。
- 依存: T308（`axis_display_for()`等の基盤）、T316（`load_route_preference()`の
  動的化）、T317（`RoutePreference.with_weight`の安全化）の上に積んだ。

### - [x] T310. 軸スタジオへ地図チップ表示要素（アイコン・略称・地図パネル説明文・代役案内・地図ramp閾値上書き）の登録機能を追加 規模M〜L（実装完了）

- 背景: T308の洗い出しで、既存軸だけを特別扱いしているコードのうち以下5件は「汎用
  フォールバックがあり機能は壊れない（未対応でも動く）」という理由でT308スコープ外・
  意図的に残す判断としていた。ユーザーから「これも特別扱いはなくしたい。軸スタジオに
  対応する要素を登録できるようにして、そちらから引っ張ってきて」との追加指示を受け、
  本タスクとして起票する。
  1. `SECONDARY_AXIS_ICONS`（`MapOverlayControls.tsx`）: 既存6軸だけ専用の手描きSVG
     アイコン（`icons.tsx`）を持ち、他の軸は汎用`AxisRampIcon`にフォールバックする。
  2. `RAMP_AXIS_PANEL_HINTS`（`mapLayers.ts`）: 既存3軸（stop_density/accident/
     car_stress）だけ、地図の見え方パネル向けに噛み砕いた説明文を持ち、他の軸は
     `axis.note`（開発者向け実装メモ）がそのまま出る。
  3. `SECONDARY_AXIS_CHIP_LABELS`（`secondaryAxes.ts`）: 既存6軸だけ4文字以内の略称を
     持ち、他の軸は正式名（`label`）がそのままチップに出る。
  4. `SECONDARY_AXIS_PROXY_HINTS`（`secondaryAxes.ts`）: `kind="none"`（専用地図
     レイヤー無し）の軸のうち`gradient`だけ代役レイヤーへの案内文を持ち、他の
     `kind="none"`軸は案内無しの単なる無効行になる。
  5. backend `STOP_DENSITY_DISPLAY`/`ACCIDENT_DISPLAY`/`CAR_STRESS_DISPLAY`
     （`axis_display.py`）: 既存3軸だけ、`derive_ramp_inputs`の自動導出（粗い/導出不能）
     に代えて統計的に調整済みのramp閾値を手書きで持つ。他の軸は自動導出結果（導出
     できなければ`kind="none"`）に固定される——軸スタジオでGUIから閾値を調整する
     手段が無い。
- 対応方針・実装内容:
  1. **アイコン登録方式**: ユーザーへ3案（(a)固定パレットから選択／(b)ラベル頭文字の
     モノグラム自動生成／(c)専用アイコン廃止）を、実際のチップUI上でのモックアップ
     （Artifact）付きで提示して相談した結果、(a)固定パレット方式を採用。
     `frontend/src/components/Map/axisIconPalette.tsx`を新設し、既存6軸の意匠
     （incline/wave/crescent-moon/density-stack/density-scatter/warning-triangle）
     に加え、新規軸向けのスペア6種（wind-flow/thermometer/shield/target/clock/layers、
     `icons.tsx`へ4種を新規追加）を含む計12種の固定パレットを用意した。`axisIconFor
     (iconId)`が未知/未設定のidを汎用`AxisRampIcon`へ安全側でフォールバックする。
     新規アイコン形状の追加は引き続きこのファイルへの1件追加＋コード変更を要する
     （軸スタジオ側はicon_idを選ぶだけ、ユーザー承認済み）。
  2〜4. `panel_hint`/`chip_label`/`proxy_hint`（いずれも`str | None`）を追加。
  5. `display_override: AxisDisplaySpec | None`を追加（`registry.py`の既存型を
     そのまま再利用、TileInputSpecの構造が複雑なためAxisComposer.tsxには編集UIを
     持たせず管理API直接編集のみ対応というスコープ限定を行った）。
  - 上記5フィールドを`domain/axis_definitions.py: AxisDefinition`・
    `axis_admin.py: AxisDefinitionFields`（create/update/レスポンスすべて）・
    `axis_catalog.py: AxisCatalogEntry`（icon_id/chip_label/panel_hint/proxy_hintの4件、
    display_overrideは`axis_display_for()`の出力に統合済みのため別フィールド化しない）・
    `infrastructure/axis_definition_models.py`（新規カラム5件、NULL許容）・
    `axis_definition_repository.py`（読み書き）に配線した。
  - **既存6軸のデータもコード内蔵の既定値（Pythonフォールバック）だけでなく、
    実際の本番DB行としてもbackfillする**（ユーザー指示「今ハードコードされている
    ところは、軸スタジオレコードに対応付けて本番DBに移行してほしい」2026-08-25）。
    `migrations/0019_axis_definitions_display_fields.sql`が、`ALTER TABLE`での
    カラム追加に続けて、`AXIS_DEFINITIONS`から`model_dump(mode="json")`で機械的に
    生成した値（手で書き写していないため転記ミスなし）を`UPDATE`文でDB行へ
    書き込む。本番環境ではこのmigrationの適用（`scripts/apply_migrations.py`）を
    もって初めてDB行にも反映される（既存の0014〜0018と同じ、適用まではPython
    フォールバックのまま動作する設計）。
  - `axis_display.py: axis_display_for()`は軸id→値のハードコード辞書
    （`_HAND_WRITTEN_DISPLAY`）を完全に廃止し、`definition.display_override`を見る
    3行の純粋関数になった（軸id文字列を一切含まない）。`registry_defaults.py`
    （ビルド時静的axis-catalog.json生成用の別レジストリ）も同様に
    `AXIS_DEFINITIONS[axis_id].display_override`を参照する形へ統一した。
  - **chip_labelの4文字制約を検証で強制**（ユーザー指摘「地図アイコンに表示する
    文字は4文字以下の想定」2026-08-25。「車の圧迫感」[label]は5文字のため、
    chip_label未設定のままだとフォールバックのlabelがそのままチップに出て
    レイアウトが崩れる）: `AxisDefinitionPayload`へ`field_validator`を追加し、
    5文字以上のchip_labelを422で拒否する（フロントも`maxLength={4}`で入力段階から
    防ぐ）。既存6軸のchip_labelは全て4文字以内で設定済み（最長は「停止密度」
    「事故密度」の4文字）。
  - 検証: backend pytest 982 passed / 154 skipped（PostGIS往復の新規テスト2件含む）、
    frontend tsc・eslint・vitest 500 passed（新規テスト9件、axisIconPalette.test.ts・
    secondaryAxes.test.ts新設含む）。Playwrightで実サーバーを起動し、`/api/axis-catalog`
    が新フィールドを返すこと・地図チップのアイコンが従来と見た目一致で表示される
    こと（軸id→値の辞書からicon_idベースの動的解決へ内部的に置き換わっただけで
    退行が無いこと）を確認。既存軸だけの特別扱いが残っていないことをユーザー指示で
    再監査し（`SECONDARY_AXIS_ICONS`等の旧シンボル名を全文検索、過去形の説明コメント
    以外に実コードが1件も残っていないことを確認）、残るのはT309（区間別内訳の別タスク、
    意図的にスコープ外）とdisplay_overrideのGUI編集UI（データ層は特別扱い無し、
    編集フォームのみ未対応、ユーザー承認済みのスコープ限定）の2点のみ。
- 依存: T308（`axis_display_for()`・`primary_attribute_ids`等の基盤の上に積んだ）。
- **`/code-review`によるT308〜T310差分の指摘・修正（2026-08-25）**: 8観点（行単位差分・
  削除挙動監査・再利用性・簡素化・効率性・altitude・CLAUDE.md準拠・cross-file追跡）の
  並列レビューで13件の指摘（うちCONFIRMED8件）を受け、全て対応した。
  - **CONFIRMED（実害あり、修正必須）**:
    1. `AxisComposer.tsx`が既存軸編集時に`display_override`/`priority_overrides`を
       payloadへ含めておらず、公開済み軸を非公開化→軽微編集→保存するとDB上のこの
       2フィールドが黙って消えていた（エラー・警告なし）。Draftへ素通し用フィールドを
       追加し保存時に含めるよう修正。
    2. `axis_display_for()`が全公開軸へ常に非null値を返すようになった結果、
       `secondaryAxesFromCatalogAxes`の`display !== null`フィルタでは`wind`
       （category="動的"、専用の動的気象UIを別に持つ）を推定指標チップグループから
       除外できなくなっていた（実際にPlaywright確認スクリーンショットにも写っていたが
       確認時に見落としていた）。`AxisCatalogEntry`/`CatalogAxis`へ軸自身の
       `category`を追加し、`category==="動的"`を明示的に除外する形へ修正。
    3. chip_labelの4文字バリデータが明示的な超過のみを弾き、未設定時のlabelフォールバック
       が4文字を超えるケース（今回の「車の圧迫感」再発パターンそのもの）を防げていな
       かった。`chip_label`未設定時は`label`の長さも検証するmodel_validatorを追加し、
       フロントにも同条件の事前チェックを追加。
    4. `MapLayersPanel.tsx`の凡例・絞り込みが静的`STATIC_FILTER_AXES`のまま
       （propとして未配線）だった。`staticFilterAxes` propを追加し、page.tsx側で
       `buildStaticFilterAxes(axisCatalog.rampAxes)`を計算して渡すよう修正。
    5. page.tsx自身の凡例・絞り込みサマリ計算（`staticLegendHiddenKeysByAxis`・
       `staticFilterSummaries`）も同じく静的`STATIC_FILTER_AXES`のまま取り残されて
       いた。4と同じ`useMemo`から取得する形へ統一。
    6. `MapView.tsx: isRoadSurfaceGroupVisible`がビルド時静的
       `ROAD_SURFACE_SHARED_LAYER_IDS`のまま（MapLayersPanel側は実行時propへ移行
       済みで不整合）だった。第2引数`roadSurfaceSharedLayerIds`を追加し、
       `buildRoadSurfaceSharedLayerIds(rampAxes)`から呼び出し元が渡す形へ変更
       （3箇所の呼び出し元のうち2箇所は一度きりのマウントeffect内のクロージャの
       ため、`redrawPropsRef`経由で最新値を読む既存パターンに合わせて配線）。
    7. `export_openapi.py`の自動ramp軸ループが`derive_ramp_inputs()`の結果のみ見ており、
       T310で導入した`display_override`を一切チェックしていなかった。display_override
       を使う新規GUI軸は実行時APIでは動くが静的axis-catalog.jsonには永久に現れない
       非対称があったため、`axis_display_for()`と同じ優先順位で解決するよう修正。
    8. `derive_ramp_inputs`が`MaterialTerm.required`を無視しており、複数材料の
       BreakpointLinear軸でrequired=Trueの材料が欠損した場合、backend評価では
       「評価不能」でも地図では「良好（緑）」に誤表示されうる理論上の不整合が
       あった。**この項目のみ意図的に未修正**——`if any(term.required...): return None`
       という安全側の制限を試したところ、T308で意図的にこの挙動を許容する設計として
       テスト化済み（`test_multi_term_breakpoint_linear_derives_ramp_with_coarser_
       thresholds`等3件）だったため、レビュー指摘を機械的に適用すると既存の
       レビュー済み設計判断を無断で覆すことになると判断し、コードは変更せず
       docstringへ既知の制約として明記するに留めた（現状は既存7軸のどれもこの
       auto-derive経路を通らないため実害ゼロ、将来のGUI作成軸向けの潜在リスクとして
       記録）。
  - **PLAUSIBLE（妥当と判断、修正）**: `generateAxisId`へ`crypto.randomUUID`未対応
    環境向けのフォールバックを追加／`BACKEND_INTERNAL_URL`の重複定義を
    `lib/backendInternalUrl.ts`へ集約／`axis_display.py`の`_flag_sum_thresholds`が
    `_adjacent_midpoint_thresholds`と重複していた末尾ロジックを共通化／
    `axis_admin.py`のcreate/update両エンドポイントが重複していた`AxisDefinition`
    構築を`AxisDefinitionPayload.to_definition()`へ集約／`useAxisCatalog`が
    同時マウント時に複数回同時発火していたフェッチを、同時実行中のリクエストのみ
    共有する形で重複排除（解決後の結果は永続キャッシュしない、軸スタジオの
    公開操作を再デプロイなしに反映するというT269の設計を保つため）。
  - **指摘されたが対応を見送ったもの（上位指摘以外の精査、ユーザー指示により実施）**:
    `AxisStudio.tsx`の3つの独立boolean状態（判別可能なunion型への整理案）・
    `useAxisCatalog.ts`/`axisLayers.ts`のTileInputSpec二段階マッピング（変換経路の
    一本化案）・`MapView.tsx`の複数useMemoの単一オブジェクト統合案は、いずれも
    実際のバグではなく将来の同期漏れリスクを下げる目的の設計改善であり、
    本セッションで既に多数の変更が入ったMapView.tsx等へさらに広い範囲の
    リファクタリングを重ねるリスクの方が、得られる利益より大きいと判断し見送った。
    `GET /api/axis-catalog`の毎リクエスト再計算・`renderRouteSettingsSectionBody`の
    未メモ化は、指摘したレビューエージェント自身も実害が無視できる規模と評価して
    おり対応不要と判断。`registry_defaults.py`の軸id列挙・T305/T306由来のカテゴリ
    非対称性は、それぞれ`AXIS_DEFINITIONS`と同型の構造的な設計（バグではない）・
    既に別途認識・記録済みの既存指摘のため対応対象外。
  - 検証: backend pytest 984 passed / 154 skipped、frontend tsc・eslint・vitest
    502 passed（新規回帰テスト4件追加）。Playwrightで実サーバーを起動し、
    `推定`グループのチップ列から`風`が消えていること（修正前は6軸中に混入して
    いたことをスクリーンショットで確認）、`next.config.ts`が新しい共有モジュール
    `backendInternalUrl.ts`を問題なく読み込めること（Next.jsのパスエイリアス確立前の
    Node標準解決でも相対importが機能することの確認）を実機確認した。

### - [x] T311. 軸スタジオを開くと500エラーになる不具合の調査・恒久対策 規模S（実装完了）

- 背景: ユーザー報告「軸スタジオを開くと、リクエストに失敗しました500エラーがでる」
  （2026-08-25）。調査の結果、直前のT310（`874d2a8`）で`axis_definitions`テーブルへ
  `icon_id`等5カラムを追加する`migrations/0019_axis_definitions_display_fields.sql`が
  導入されたが、デプロイパイプライン（`deploy-backend.yml`）はmigration適用を含まず、
  `scripts/apply_migrations.py`の手動実行を待って初めて本番DB行へ反映される設計
  （T310本文参照）。このラグの間に軸スタジオ（`/admin`）を開くと、`axis_admin.py`の
  CRUDエンドポイントが新カラムを含む`SELECT`を発行し、DB側にカラムが無くDBAPIError
  （PostgreSQLの`UndefinedColumn`相当）が未処理のまま素の500として返っていた。
  一般ユーザー向け画面は`refresh_axis_definitions`（`axis_registry_service.py`）の
  安全側フォールバック（DB読み込み失敗時はコード内蔵の既定値を使用）で保護されるが、
  軸スタジオのCRUD経路（`AxisRegistryAdminService`経由でDBへ直接SELECT/INSERT）は
  このフォールバックの対象外で、同種の安全網が無かった。
- migration適用そのもの（本番DBへの書き込み操作）は、調査を行ったセッションが本番DB・
  Oracle VMへの接続情報を保持していないため実行できず、**ユーザー自身が
  `scripts/apply_migrations.py`を本番に対して実行する**運びとした（2026-08-25、
  ユーザー選択）。
- 恒久対策として、`axis_admin.py`に`_guard_db_errors()`ヘルパーを追加し、全CRUD
  エンドポイント（list/get/create/update/delete/unpublish）のサービス呼び出しを
  ラップした。`sqlalchemy.exc.DBAPIError`（接続失敗・カラム不在等のDB自体の障害）
  だけを捕捉し、原因の当たりが付くメッセージ（migration未適用の可能性・
  `apply_migrations.py`実行を促す文言）付きの503へ変換する。既存のValueError/KeyError
  （業務ロジック上の409/404）はこのヘルパーの対象外で、呼び出し元のexcept節がそのまま
  扱う。**あえて安全側フォールバック（コード内蔵の既定値を返す）にはしなかった**——
  軸スタジオは常にDBの実データを編集する画面であり、DB障害時に古い既定値を編集画面に
  出すと、気付かないまま上書きしてしまう危険があるため（`_guard_db_errors`docstring
  参照）。
- 検証: `tests/test_axis_admin_routes.py`へ`FailingAxisRegistryAdminService`
  （全メソッドがDBAPIErrorを送出するfake）を追加し、6エンドポイント全てが503
  （detailに"migration"を含む）を返すことを確認する回帰テストを追加。backend
  pytest 771 passed（PostGIS統合テストは本セッションにDB接続が無いため除外）、
  ruff clean。フロント側の変更は無い（`adminFetch`は既に`response.ok`でない
  レスポンスのdetailをそのまま表示する実装のため、503化だけで診断可能なメッセージが
  UIに出るようになる）。
- 依存: T310（本タスクが対策する不具合の直接の原因）。

### - [x] T312. 未公開の内部軸がルート設定画面に漏れる不具合の恒久対策（T311フォローアップ） 規模S（実装完了）

- 背景: ユーザーがT311の対策を受けて本番DBへmigration 0019を適用したところ、「ルート設定に
  未公開の推定軸が出ている」と新たに報告（2026-08-25）。調査の結果、`GET /api/axis-catalog`
  （`axis_catalog.py`）の`is_published`フィルタ自体・`AXIS_DEFINITIONS`のコード内蔵既定値
  （car_stress内部軸6つは全て`is_published=False`）のどちらにも問題は無かった。原因は、
  `axis_admin.py`のPUT（`AxisRegistryAdminService.update`/`create`）に「他の軸から参照
  されている内部軸を公開させない」というT292の設計意図（`axis_definitions.py:
  AxisDefinition`docstring「軸の階層」参照）を強制するコードレベルのガードが一切無かった
  ことで、過去の軸スタジオでの操作（動作確認・トグルの戻し忘れ等）によりcar_stress内部軸の
  いずれかが`is_published=True`のままDBへ保存されていたため。この汚染データは、T310
  デプロイ後〜migration 0019適用前の期間中、`refresh_axis_definitions`がDB読み込み失敗
  （カラム不在のDBAPIError）でコード内蔵の安全な既定値へフォールバックし続けていたため
  画面上見えていなかった（T311参照）。0019適用でDB読み込みが復旧した際、隠れていた汚染
  データがそのまま一般ユーザー向け`GET /api/axis-catalog`へ表に出た。
- 本番DBの実データは調査セッションから直接見えないため、汚染された軸の特定・是正
  （軸スタジオから該当軸を「下書きに戻す」）はユーザー側の対応とした。
- 恒久対策: `domain/axis_definitions.py`へ`check_internal_axis_not_published()`（と
  `AxisInternalAxisPublishError`）を追加し、`AxisRegistryAdminService.create`/`update`
  （`axis_registry_service.py`）から呼び出すよう配線した。候補の軸が他の既存軸から
  軸参照（内部軸）として使われている状態で`is_published=True`のまま保存しようとすると
  409（ValueError→router層の既存except節がそのまま処理）で拒否される。これにより、
  今回と同型の汚染データが将来書き込まれること自体を構造的に防ぐ（DB読み込み失敗時の
  フォールバックに隠れて気付かないまま蓄積する再発パターンを断つ）。
- 検証: `test_axis_definitions.py`へ`check_internal_axis_not_published`の単体テスト
  （内部軸の公開拒否・非参照軸の公開許可・自己参照の除外・car_stress実データでの回帰）、
  `test_axis_registry_service.py`へ`AxisRegistryAdminService.update`経由の統合テスト
  （PostGIS要、本セッションでは未実行）を追加。DB非依存分はbackend pytest 776 passed、
  ruff clean、OpenAPI生成物ドリフト無し。
- 依存: T311（同一不具合の別側面）、T292（内部軸の階層構造そのもの）。

### - [x] T313. 非バランスプリセット選択時に重み配分が薄まる不具合を修正 規模S（実装完了）

- 背景: ユーザー報告「バランス以外のルート設定（自転車専用道を優先等）を選択すると、
  重み配分がMAXにならない」（2026-08-25）。調査の結果、`RouteSettingsPanel.tsx`の
  `applyPreset()`が`{ ...catalog.defaultWeights, ...preset.weights }`で未言及の軸を
  補っていたことが原因と判明。「バランス」プリセットは`weights`自体が
  `catalog.defaultWeights`そのもの（全軸を明示済み）のため影響を受けないが、
  `NON_DEFAULT_PRESETS`（「自転車専用道を優先」等）は既存7軸のみを固定値でハードコード
  しているため、軸スタジオ（T270）経由で新しい公開軸が増えると（T312で発覚した
  「未公開のはずの内部軸が誤って公開された」ケースを含む）、プリセットが一切言及しない
  その軸の既定重み（非ゼロ）が黙って混入し、合計重みが増えて対象軸（例: car_stress）の
  相対比率（フロントの重み配分バー・backendの`composite_difficulty`加重平均が両方使う
  「対象軸の重み÷全軸重み合計」）が意図した値まで上がらなくなっていた。
- 修正: `applyPreset()`の補完元を`catalog.defaultWeights`から「全軸0埋め」へ変更した。
  非バランスプリセットは未言及の軸を0（対象外）として扱うようになり、軸カタログの
  公開軸集合が今後どう変化しても、プリセットが明示する軸の相対比率が薄まらない
  （「バランス」プリセットは全軸を明示済みのためこの変更による影響を受けない）。
- 検証: `RouteSettingsPanel.test.tsx`へ回帰テストを追加（プリセット未対応の新規公開軸を
  含むカタログで「自転車専用道を優先」を実際にクリックし、その軸の重みが0で送信される
  ことを確認）。frontend vitest 501 passed、eslint clean（tscの`LayoutProps`エラーは
  `.next/types`未生成による本タスク無関係の既知の事前状態）。backend側の変更は無い
  （`RoutePreferenceWeights`の検証・正規化ロジックには問題が無いことを調査で確認済み）。
- 依存: T312（同時期に発覚した「未公開軸の誤公開」が症状を顕在化させた一因）、T270
  （軸スタジオでの公開軸集合の動的な増減そのもの）。

### - [x] T314. デプロイ中の接続切断でルート生成が失敗する不具合の恒久対策 規模S（実装完了）

- 背景: ユーザー報告「ルート生成失敗する」（2026-08-25、フロントログ`TypeError: Failed
  to fetch`、durationMs=13893）。調査の結果、`POST /api/routes/generate`はブラウザから
  backendへ直接fetchする構成（`frontend/src/services/routeApi.ts`、タイムアウトは
  360秒でありAbortSignal.timeoutは未発火とログから確認済み）で、フロント側・
  `backendInternalUrl.ts`新設等の直近リファクタには問題が無いことを確認した。
  真因は`.github/workflows/deploy-backend.yml`の`docker stop`が既定のSIGTERM猶予
  （10秒）のまま呼ばれており、ルート生成（通常数秒〜十数秒、冷パスは最大316秒実測）が
  デプロイの再起動タイミングと重なると、処理途中でTCP接続がRSTで強制切断されfetchが
  `TypeError: Failed to fetch`として失敗すること。当日朝、T311・T312・並行セッションの
  指摘対応と、backend変更を含むpushが短時間に3回連続しデプロイも3回連続で走っていた
  ことが引き金になったと判明した。
- 対策: `docker stop`に`-t 90`（SIGTERM猶予90秒）を追加した。backend
  （`backend/Dockerfile`）はuvicornを`--workers`未指定の単一プロセスで起動しており、
  SIGTERM受信で新規接続を止め既存接続の完了を待つグレースフルシャットダウンが
  既定動作のため、猶予を延ばすだけでアプリ側の変更なしに大半の実リクエスト
  （実測4〜17秒）を守れる。冷パス最悪ケース（316秒）まで完全に保証すると通常デプロイが
  長時間ブロックされるため、そこまでは意図的に保証しない（トレードオフとして
  `deploy-backend.yml`のコメントに明記）。
- 見送った選択肢: 新コンテナ起動→ヘルスチェック→旧コンテナ停止の真のゼロダウンタイム
  （blue/green）化。現状は`--network=host`で単一ポートを共有する構成のため、新旧
  コンテナを同時起動できずこの構成のままでは実現できない（VM上nginx側のポート切替が
  別途必要、リポジトリ管理外のため本タスクのスコープ外とした）。
- 検証: `python3 -c "import yaml; yaml.safe_load(...)"`でYAML構文・scriptブロックの
  内容を確認。ワークフローの実際の実行結果はVM上の次回デプロイで確認する
  （本セッションはOracle VMへの直接アクセスを持たない）。
- 依存: T263（Oracle VMへのデプロイパイプラインそのもの）。

### - [x] T315. CORS_ALLOWED_ORIGINS不一致でルート生成が即時失敗する不具合の恒久対策 規模S（実装完了）

- 背景: T314対策後もユーザーから「変わらず即エラーとなる」と再報告（`TypeError:
  Failed to fetch`、durationMs=313——T314で対処した「処理途中で切断される」パターン
  [durationMs=13893]とは明確に異なる、ほぼ即時の失敗）。ブラウザで直接
  `https://193-123-166-150.sslip.io/health`を開くと成功する一方、軸スタジオ
  （Next.jsサーバー経由のサーバー間通信、CORS対象外）は正常に動くのに、ルート生成
  （ブラウザからbackendへ直接fetch、CORS対象）だけが失敗するという非対称性から、
  `CORS_ALLOWED_ORIGINS`（本番フロントのオリジンを許可していない）の不一致と判断した。
  この種の障害は`docs/improvement-plan-archive/2026-08-18-part1.md`に記録された過去の
  障害と同型（2回目の発生）。
- 本番の`CORS_ALLOWED_ORIGINS`はgit管理外のVM上ファイル
  （`/home/ubuntu/ridecompass-backend.env`）で手動管理されており、ユーザーがVMへの
  SSH秘密鍵（ローカルファイル）を紛失していたため、直接編集する通常の手段が使えな
  かった。GitHub Actions側の`ORACLE_VM_SSH_KEY`シークレットは書き込み専用だが
  ワークフロー実行自体は引き続き有効（今回連続していたデプロイが全て成功していた
  ことで裏付け済み）であることに着目し、`deploy-backend.yml`の既存SSHステップに
  自己修復処理を追記する形で対応した。
- 対策: デプロイのたびに、`CORS_ALLOWED_ORIGINS`に本番フロントの既知オリジン
  （`https://ride-compass-frontend.onrender.com`）が含まれているか確認し、無ければ
  追記する冪等処理を追加（既存の他オリジン・ファイル内の他の値は一切変更しない）。
  ユーザー確認の上、VM個別のSSHアクセス回復（新規鍵ペア発行等）ではなく、既存の
  自動デプロイ経路を使う方式を選択した。
- 検証: `python3 -c "import yaml; yaml.safe_load(...)"`でYAML構文・scriptブロックの
  内容を確認。実際の反映結果はVM上の次回デプロイで確認する（本セッションはOracle
  VMへの直接アクセスを持たない）。
- 依存: T314（同一のユーザー報告「ルート生成失敗する」の別側面、時系列で先に対応）。

### - [x] T316. route_preference.yaml撤廃（既定重みの情報源をAXIS_DEFINITIONSへ一本化） 規模S（実装完了）

- 背景: T314・T315を対応してもなお「変わらずルート生成が失敗する」というユーザー報告が
  続いた。VM上のbackendログ（`sudo docker logs`）で実際のトレースバックを確認した結果、
  真因は`pydantic_core.ValidationError: unknown axis_id in weights: ['car_stress',
  'gradient', 'night', 'stop_density'] (known: ['accident', 'surface_q', 'wind'])`
  という、通信経路とは全く別の500だった。ユーザーが軸スタジオ経由で意図的に4軸を
  非公開にしたところ（「今後は公開軸の数を自由に増減させたい、7軸固定は改修意図に
  反する」という明言あり）、`backend/app/route_preference.yaml`（既存7軸のaxis_idを
  固定で書いた重み設定ファイル、`load_route_preference()`が読んでいた）が現在の
  公開軸集合と食い違い、`route_preference`を明示的に上書きしない**全リクエスト**が
  即500になっていた。
- この不整合は、一連の改修（T221 Stage D以降）の目的そのもの——「推定軸の特別な扱い・
  べた書きを撤廃し、軸スタジオから自由に追加・編集・公開/非公開できるようにする」——と
  真っ向から矛盾する見落としだった。`export_openapi.py`の`preference_defaults`は
  既に同種の手書きミラーを`default_axis_weights()`（`AXIS_DEFINITIONS`が唯一の
  情報源）へ置き換え済みだったが、backend自身の`load_route_preference()`だけが
  この移行から取り残されていた。
- 対策: `evaluation_service.py: load_route_preference()`を、YAML読み込みをやめ
  `RoutePreference()`（`weights`の`default_factory=default_axis_weights`が
  `AXIS_DEFINITIONS`のis_published軸から動的に導出）を返すだけに簡素化。
  `route_preference.yaml`・`_load_yaml_section`・`ROUTE_PREFERENCE_CONFIG_PATH`・
  `path`引数を削除（`path`引数は将来の複数プロファイル機能[T307]向けに残していたが、
  実際の呼び出し元は全て既定パスのみで使っており、T307自体が保留中のためYAGNI
  判断で削除。復活させる場合は「静的プロファイルファイルも軸増減に追従できる設計」を
  T307着手時に別途検討する）。関連コメント（`openrouteservice_engine.py`・
  `axis_registry_service.py`・`routes.py`・`axis_definitions.py`・
  `registry_defaults.py`）と`docs/architecture.md`（7軸表・重みのキー節・「1本道」の
  配線経路説明・ファイルツリー・研究インターフェースの上書き節・削除時整合性の節）を
  同一コミットで追従。
- 検証: `route_preference.yaml`の値（gradient=0.15等）が元々`AXIS_DEFINITIONS`の
  `default_weight`と完全一致（手書きミラーとして同期済みだった）していたことを確認
  した上で、`test_evaluation_service.py`の関連テストを`default_axis_weights()`との
  比較へ書き換え（新規回帰テストが今回の障害パターン——公開軸が7から変動しても
  既定値が壊れないこと——を保証）。backend pytest 775 passed（PostGIS統合テストは
  本セッションにDB接続が無いため除外）、ruff clean、OpenAPI生成物は
  `RoutePreferenceWeights`のdocstring変更分のみ（`route_preference.yaml`への言及を
  修正）を反映して再生成・コミット対象に含めた。
- 依存: T221 Stage D（軸のDB化・軸スタジオそのもの）、T269（`export_openapi.py`の
  `preference_defaults`が同種の手書きミラーを先行して撤廃済みだった前例）。

### - [x] T317. night軸非公開時にRoutePreference.with_weightがValidationErrorになる不具合の恒久対策（T316フォローアップ） 規模S（実装完了）

- 背景: T316でbackendの`load_route_preference()`はAXIS_DEFINITIONS由来の動的既定値へ
  移行したが、ユーザーが軸スタジオでさらに`night`軸を非公開化した状態でルート生成すると
  依然として本番500が発生した。VM上のdockerログで実際のトレースバックを確認したところ、
  真因は`road_graph_engine.py: _build_search_graph`が`self._route_preference.with_weight
  ("night", 0.0)`を無条件に呼んでいたこと。`RoutePreference.with_weight()`は
  `RoutePreference(weights={**self.weights, axis_id: value})`を素朴に構築しており、
  `weights`のバリデータ（`_validate_and_fill_weights`）が現在の公開軸集合に無い
  axis_idを拒否するため、`night`が非公開の状態では`"night"`キーの追加そのものが
  `pydantic_core.ValidationError`になっていた（`unknown axis_id in weights: ['night']`）。
  同根の問題として`openrouteservice_engine.py`側も`base_axis_weights["night"]`という
  直接添字アクセスで同様にKeyErrorしうる箇所があった。
- 対策:
  - `domain/evaluation.py: RoutePreference.with_weight()`: `axis_id`が現在の`weights`に
    無い場合は無変更の`self`をそのまま返すよう変更（非公開軸への重み上書きは
    「その軸は評価に参加しない」を意味するため、無視するのが安全側の挙動）。
  - `openrouteservice_engine.py`: `base_axis_weights["night"]`を
    `base_axis_weights.get("night", 0.0)`へ変更し、同様にKeyErrorを防止。
  - 回帰テストを追加: `test_evaluation.py:
    test_route_preference_with_weight_returns_self_for_unknown_axis_id`、
    `test_road_graph_engine.py: test_prepare_does_not_crash_when_night_axis_is_unpublished`
    （`monkeypatch.setitem(AXIS_DEFINITIONS, "night", ...is_published=False)`で実際の
    障害状態を再現）、`test_openrouteservice_engine.py:
    test_evaluate_loops_does_not_crash_when_night_axis_is_unpublished`。
- この修正の対症療法的な限界（T309着手のきっかけ）: 上記は「非公開軸への書き込みは
  無視する」という安全弁であり、`RouteSegmentDetail`側の7軸固定フィールド
  （`elevation_difficulty`等）という、より広い「軸の数は7固定」という前提そのものは
  未解消のままだった。ユーザーから「修正の方向性あってる？　7つの軸のうちないものが
  あれば無視してください、という修正は意図と違う。推定軸の数は可変にしたい」との
  明確な指摘を受け、この限界を解消する本丸としてT309（保留中だったタスク）に
  着手する流れとなった。
- 検証: backend pytest（該当ファイル）全パス。本番同等のシナリオ（night軸非公開＋
  road_graphエンジンでのルート生成）をT309の実機検証時に実サーバーで再現し、
  500にならないことを最終確認済み（T309エントリ参照）。
- 依存: T316（`load_route_preference()`の動的化）の直後に発覚した続報。T309（本丸の
  恒久対策）の前提・トリガーとなった。

### - [ ] T318. 起点(35.75,139.74)でdistance_km=25/30が候補0件になる（distance_km=20はヒット） 規模S〜M（保留・調査未着手）

- 背景: T309/T317デプロイ後の本番実機確認（ユーザー）で、起点(35.7507, 139.7419、東京都北区王子付近)・
  road_graphエンジンにて`distance_km=30, distance_tolerance_km=5`のルート生成が「条件に合う
  ルート候補が見つかりませんでした」になった。backendログ（`sudo docker logs`）で確認したところ
  500ではなく正常系のWARNING:
  ```
  generate engine=road_graph origin=(35.75,139.74) target_km=30.0 -> no candidates
    (trace_ok=8/8 trace_failed=[] filtered_out=8) prepare_ms=41017 trace_ms=899
  ```
  8方位すべて経路探索自体は成功（trace_ok=8/8）した上で、全8件が距離許容範囲
  （target±tolerance、既定は25-35km）外として`route_generator.py`の距離フィルタで
  除外されていた（T309/T317のコード変更[RoutePreference.with_weight・
  RouteSegmentDetail.axis_difficulties]は経路探索・距離フィルタには一切触れていないため、
  今回の一連の修正による回帰ではないと判断）。
  ユーザーが同じ起点でdistance_kmを変えて追試したところ、**20kmはヒットするが25km・30kmは
  候補0件**という結果だった（tolerance固定5kmのまま）。20→25の間のどこかに閾値があるか、
  25以上で系統的に候補が出ない可能性がある。単純な「たまに方位が外れる」ヒューリスティックの
  既知の制約（`docs/architecture.md`記載）にしては、20kmと25km/30kmとの間の落差が大きく
  クリーンすぎる（8方位全滅×複数距離で再現）ため、既知の制約の範囲か、prepare_ms=41017
  （41秒、後述）に見えるような別の問題（bbox・タイルカバレッジ・探索半径の設定ミス等）が
  絡んでいないか要調査。
- 保留の影響範囲: 対応を保留し続けると、この起点付近で25km以上の周回ルートを求める
  リクエストが恒常的に「候補0件」になり続ける（ユーザー体感では原因不明のまま
  「距離を変えて試してください」を繰り返すことになる）。distance_tolerance_kmはUIから
  変更する手段が無い固定値5km（`frontend/src/app/page.tsx:116`）のため、ユーザー側での
  回避策はdistance_km自体を動かすことに限られる。他の起点・距離でも同型の問題が
  再現するかは未確認（本件は1地点1系列の観測のみ）。
- 副次観測（要調査、本タスクと同一origin）: 上記ログの`prepare_ms=41017`（41秒）は
  本セッションのローカル実機検証（合成8ノードグラフ、prepare_ms=6500〜7000程度）と比べて
  一桁大きい。本番の実道路網・タイルキャッシュの温まり具合次第で正常な範囲の可能性もあるが、
  ユーザー体感のレスポンスタイムに直結するため、T318の調査時に合わせて確認する
  （filtered_outの根本原因とは独立の観測、無関係なら別タスクへ切り出す）。
- 調査結果（2026-08-25、コード調査のみ・DEBUGログ未取得）:
  1. **半径計算とbboxカバレッジ**: `radius_km = distance_km × RADIUS_RATIO(1/3)`
     （`route_generator.py:103`）・`margin_km = max(BBOX_MARGIN_MIN_KM=2.0,
     radius_km×BBOX_MARGIN_RATIO=0.3)`（`road_graph_engine.py:91-92`）から、
     20km→bbox直径17.3km、25km→21.7km、30km→26.0kmと算出。関東7都県分のOSM取込済み
     範囲（`docs/osm-pbf-import.md`）には遠く及ばず、**bboxがデータ取込範囲を超えて
     いることはない**（ログが`no context`ではなく`no candidates`である事実とも整合）。
  2. **`prepare_ms=41017`（41秒）の原因**: bbox拡大に伴い覆うz12タイル数が約4→6→9枚に
     増加。`GraphService.is_split_up_to_date`（`graph_service.py:239`）がFalseになると
     軽量なタイルキャッシュ経由パスではなく`_build_search_materials_uncached`
     （`graph_service.py:244-276`、新規split＋バルクUPSERT＋commitを直列実行）という
     重いコールドパスに落ちる。同ファイルのコメントに実測値「1回目27.6秒[新規split]」の
     前例があり、41秒はこれと同規模。25km/30kmで新規タイル境界を踏むたびにこの
     コールドパスを繰り返し踏んでいる可能性が高い（`filtered_out`の直接原因ではないが、
     独立した性能上の見落としの疑い）。
  3. **地理的要因（仮説、未検証）**: `trace_loop`（`road_graph_engine.py:351-384`）は
     3レグ（起点→A→B→起点）の最短路（コスト最小路）を単純連結するだけで、川の存在を
     考慮しない。既定のハードフィルタ（`motorway`/`trunk`除外）により、王子付近の
     荒川・隅田川を渡る主要橋（国道=trunk相当が多い）の通行可能な選択肢が絞られ、
     半径が大きくなるほど8方位すべてが少ない橋へ収束し迂回コストが非線形に増える
     構造的リスクがあると考えられる。「20kmは通り25・30kmは全滅」という落差の大きさは
     このボトルネック構造と整合的だが、未検証の仮説。
  4. **既知の設計制約との関係**: `route_generator.py:48-50`のコメントは「半径固定比・
     適応調整なし、実際の道路網次第で距離のばらつきが生じる」ことを既知の制約として
     明記済み。distance_kmが大きいほど条件に合わなくなりうること自体は設計上許容
     されているが、本件（8方位クリーンに全滅×複数距離で再現）がその許容範囲内か、
     地理的要因による見落としかは、DEBUGログでの実測なしには断定できない。
- 次の一歩（未着手）: (1) DEBUG相当のログ（`distance filter rejected bearing=%d
  distance_km=%.1f (target=%.1f±%.1f)`、`route_generator.py`）で8方位それぞれの実際の
  traced距離を確認し、20km時の分布と25km/30km時の分布を比較する（本番のdebug_modeを
  一時的に有効化するか、`GraphService`のタイル・キャッシュ状態を再現したローカル環境で
  追試する）。(2) 上記地理的要因の仮説（橋のボトルネック）を、実際にtraced distanceの
  内訳（どの方位がどれだけ長くなっているか）から検証する。(3) 別の起点でも
  distance_km=25/30が同様に落ちるか横展開して確認し、地点固有の問題か全般的な問題かを
  切り分ける。(4) prepare_ms=41017（コールドパスの繰り返し）が独立の問題と分かれば
  別タスクへ切り出す。
- 調査追記（2026-08-26、実地検証・ローカル再現の試行）: 上記(1)のDEBUGログ自体は
  `route_generator.py:147-150`に**既に実装済み**であることをコード確認した（新規に
  書く必要は無い）。ローカルdev DBで同一起点(35.7507,139.7419)・distance_km=20/25/30を
  実際にAPI経由で叩いたところ、**いずれも「候補0件」だったが、本番とは異なる失敗経路**
  だった: ローカルは`generate ... -> no context (road data unavailable)`
  （`GraphService.get_search_materials_for_bbox`が空グラフを返し、経路探索自体に
  到達しない）のに対し、本番ログは`trace_ok=8/8`（8方位とも経路探索は成功した上で
  距離フィルタに落ちる）。ローカルdev DBはこの地点周辺にosm_raw_ways・road_edgesとも
  一定量のデータを持つ（30km相当bboxでway 57,800件・road_edges 209,923件、確認済み）
  にも関わらずこの結果になっており、`is_split_up_to_date`とタイルキャッシュ経路の
  組み合わせに起因すると思われる**T318とは別のローカル環境固有のデータ不整合**が
  疑われる（本番のtrace_ok=8/8と矛盾するため、T318の原因ではない。深追いはせず
  ここに記録のみ、必要になれば別タスクとして起票する）。結果、**ローカル環境では
  この地点のT318現象を再現できないことが確定**し、実地検証には本番debug_modeでの
  DEBUGログ取得が必須という結論に至った。
- 保留（2026-08-26、ユーザー判断）: 本番SSHでのdebug_mode一時有効化・再起動・
  リクエスト再実行・ログ取得・復元という一連の作業（本番の一時的な再起動を伴う）を
  ユーザーへ提案したが、「今すぐは調べられない」との回答で本日は保留。
  **保留の影響**: 現状把握（背景節）のとおり、この起点付近で25km以上の周回ルートを
  求めるリクエストは引き続き恒常的に「候補0件」になり続ける。加えて、本番debug_mode
  ログを取得するまでは方位別traced距離の実データが無く、地理的要因（橋のボトルネック）
  仮説の検証も、他起点への横展開確認も、prepare_ms=41017が独立問題かどうかの切り分けも
  すべて着手できないままになる（次の一歩(1)〜(4)全体がこの1点でブロックされている）。
  再開時は本エントリの「次の一歩」からそのまま着手できる（DEBUGログ実装済み・
  ローカル再現不可という調査結果は再利用可能、やり直し不要）。
- 依存: T309/T317のデプロイ後に発見（原因ではないと判断済みだが、時系列として直後の
  実機確認で発覚）。

### - [x] T319. 全軸を軸スタジオで非公開にしても、ルート設定パネルに既存7軸が残り続ける不具合を修正 規模S（実装完了）

- 背景: T318調査の折にユーザーから追加で報告。軸スタジオですべての軸（7軸）を非公開に
  すると、期待では「ルート設定パネルの軸一覧が0件」になるはずが、実際には既定の7軸が
  そのまま表示され続けた。T309で「推定軸の数は可変にしたい、7軸固定という前提を捨てて
  ほしい」という方針を徹底したはずの直後だったため、まだどこかにハードコーディングが
  残っていないか調査した。
- 原因: `frontend/src/hooks/useAxisCatalog.ts`の`useAxisCatalog()`が、`GET
  /api/axis-catalog`のレスポンス受信後に`response.axes.length > 0`という条件で
  `setCatalog`を呼ぶかどうかを分岐していた。これが「まだ取得中/取得失敗」と「取得成功
  したが軸が0件（全軸非公開）」という異なる状態を同一視しており、後者でも初期値の
  `FALLBACK_CATALOG`（ビルド時静的axis-catalog.json由来の既存7軸）が残り続けていた。
  backend側（`app/api/routers/axis_catalog.py`・`domain/axis_definitions.py:
  default_axis_weights()`）は`is_published`のフィルタが正しく効いており、全軸非公開なら
  素直に`{"axes": []}`を返す設計になっていた——ハードコーディングはfrontendのこの1箇所
  のみだった。
- 対策: 分岐条件を`!cancelled`のみへ変更し、フェッチ成功時は`axes`が空でも常に
  `buildCatalog(response.axes)`を適用するよう修正（フェッチ未完了・失敗時のみ
  `FALLBACK_CATALOG`に留まる、という区別に一本化）。
  なお`axisLayers.ts: axisLabelsFromCatalogAxes`が持つ`wind: "風"`のハードコードは
  今回の不具合とは別枠（windは専用の動的気象UIを別に持つため、そもそも軸スタジオの
  is_publishedレジストリとは独立した「地図表示レジストリに未登録」の特別軸として
  設計されており、公開軸数に関わらず変わらないのが正しい挙動と判断、変更なし）。
- 検証: 回帰テスト`useAxisCatalog.test.ts`に「axesが0件のレスポンスはFALLBACK_CATALOGへ
  戻さずそのまま空を返す」ケースを追加。frontend vitest 504 passed、eslint・tsc clean。
- 依存: T309（軸スタジオの公開軸を可変に扱う一連の改修）の直後に発覚した見落とし。
- **訂正（T320で判明）**: 「ハードコーディングはfrontendのこの1箇所のみだった」という
  上記の結論は誤りだった。ユーザーから「他にないか、５回目ぐらいの依頼になるけれども
  再度確認して」との指摘を受け改めて全面監査した結果、少なくとも4件の追加のハード
  コーディング・配線漏れが見つかった（T320参照）。1件直して満足せず、同じクラスの
  問題が他に無いかを毎回横展開すべきだったという反省点として記録する。

### - [x] T320. 既存7軸ハードコーディングの全面再監査と修正（T319で見落とした残り分） 規模M（実装完了）

- 背景: T319対応後、ユーザーから「重ね重ね全部消して、推定軸は可変にしてと何度も
  お願いしていたはず。他にないか、５回目ぐらいの依頼になるけれども再度確認して」との
  強い指摘を受け、frontend/backend全体を対象に「軸の数・軸id集合が7固定、または
  軸スタジオの現在の公開軸集合と食い違いうる」箇所を徹底的に再監査した
  （T313・T316・T317・T309・T319は既知のため対象外）。
- 発見・修正した項目（優先度順）:
  1. **【最重要】`page.tsx: handleGenerate`が、`GET /api/axis-catalog`のフェッチ未完了・
     失敗時にビルド時静的な既存7軸(`axisCatalog.defaultWeights`)へ`route_preference`の
     キーを同期してしまい、実際の公開軸集合と食い違うペイロードを送って422になりうる
     不具合**。`useAxisCatalog`の戻り値へ`loaded: boolean`（フェッチ成功時のみtrue、
     0件成功も含む）を追加し、`loaded===false`の間は`route_preference`自体を送らず
     backend側の既定値（常に最新のAXIS_DEFINITIONS由来）に委ねるよう修正
     （`scoring_weights`は軸レジストリと無関係なため引き続き送る）。
  2. **`RouteSettingsPanel.tsx: applyPreset`が、ゼロ埋め後に`preset.weights`
     （既存7軸を名指しした固定コンテンツ）をそのままspreadしていたため、非公開・削除
     済みの軸idがゴーストキーとしてroutePreference stateへ復活する不具合**。プリセットに
     由来する重みを`catalog.defaultWeights`（＝現在の公開軸集合）に存在するキーだけへ
     フィルタしてから合成するよう修正（重み配分バーの%表示が実際の送信内容と食い違う
     問題、全軸非公開時にプリセットを押すと区間難易度が全てNoneになる問題を解消）。
  3. **`RouteSettingsPanel.module.css`の重み配分バーの色分けが`data-axis="gradient"`等、
     既存7軸のCSSセレクタ固定だった不具合**。軸スタジオで新規公開した軸は対応する
     セレクタが無く、幅だけ取られた透明な帯になっていた。CSS属性セレクタ方式を廃し、
     TSX側でindexベースの固定パレット（`STACK_BAR_COLORS`、色自体に意味は持たせない
     識別用という元の方針は維持）から選ぶ方式へ変更し、軸の増減にコード変更無しで
     追従するようにした。
  4. **区間インスペクタ（`axisInspectorPopup.ts`）が、ビルド時静的な`AXIS_LABELS`を
     直接importしており、軸スタジオで新規公開したGUI作成軸のラベルが表示されず生の
     axis_idがそのまま出ていた不具合**。`useAxisCatalog`が既に用意していた動的な
     `axisLabels`（T308で追加済みだったが消費者が1件も無かった配線漏れ）を
     `MapView.tsx`経由で受け取るよう配線した（`buildAxisInspectorHtml`/
     `attachAxisInspectorHandler`が引数で受け取る形へ変更）。MapView側は
     `redrawPropsRef.current`経由で読む（クリックハンドラを登録するeffectはマウント時
     のみ実行されるため、propsを直接クロージャで捕まえるとフェッチ解決後も
     マウント時点の静的フォールバックのままになる、既存のstaticOverlayLayers等と
     同じ理由）。
  5. **`ComparisonPanel.tsx`（研究モードの実験比較表）が、重みのツールチップ表示で
     ビルド時静的な`PREFERENCE_AXES`（既存7軸固定）を回しており、軸スタジオで新規
     公開した軸の重みが表示されず、非公開化した軸は`p[axis.axisId]`が`undefined`のまま
     「風undefined」のように表示されていた不具合**。表示対象を`route_preference`
     オブジェクト自身のキー集合（＝その回のgenerateへ実際に送られた条件、backendが
     エコーした正）へ変更し、ラベルだけ動的な`axisLabels`から引く形にした。
  6. **`NON_DEFAULT_PRESETS`（自転車専用道を優先/最短時間重視/安全重視）が既存7軸を
     名指しした固定コンテンツで、対象軸がすべて非公開だと押しても実質何も変わらない
     （zeroFilledのまま）操作になる、というユーザー指摘への対応**。プリセット定義
     自体をキュレーションされたコンテンツとして残すこと自体は妥当と判断したが、
     「一見選べるのに押しても意味を持たない」ボタンを有効なまま見せるのは設計不整合、
     というユーザー指摘を受け入れ、プリセットが対象とする軸が現在の公開軸集合と
     1つも重ならない場合はボタンを無効化（`disabled`＋理由をtitleで表示）するよう
     `RouteSettingsPanel.tsx`を修正した。1つでも重なりがあれば「部分的には効く」ため
     有効のまま。
  7. **`backend/app/domain/registry_defaults.py: _register_axes()`が組み込み6軸を
     `if "gradient" in AXIS_DEFINITIONS: register_axis(...)`のように1軸ずつ名指しで
     分岐していた点**。「存在確認さえすれば安全」という前段階の対症療法的な修正を
     ユーザーが明確に拒否（「`if "surface_q" in AXIS_DEFINITIONS:`という分岐が存在
     すること自体を是正してほしい」）したのを受け、`AXIS_DEFINITIONS`をそのまま走査する
     形へ全面書き換えした。`inputs`（参照する一次属性id）・`display`（地図表示宣言）は、
     `GET /api/axis-catalog`（実行時API）が同じ軸に対して呼ぶのと同一の純粋関数
     （`domain/axis_display.py: primary_attribute_ids_for()`・`axis_display_for()`、
     前者は`api/routers/axis_catalog.py`からこのファイルへ移設し両者で共有）から導出する
     ため、ビルド時静的生成物と実行時APIの計算ロジックが完全に一致する。副次効果として
     `scripts/export_openapi.py`側にあった「registry.py未登録の軸だけを別ループで拾う」
     という重複実装（`_auto_ramp_axes`）が構造的に不要になったため削除した。
     `AxisSpec`の`transform_fn`/`output_range`/`description`フィールド（いずれも
     実行時経路のどこからも参照されておらず、`axis-catalog.json`へも書き出されて
     いなかった完全な死蔵フィールド）も削除した。
  8. **`backend/app/domain/difficulty.py`/`night.py`の`*_difficulty`スカラー版互換
     ラッパ（`gradient_difficulty`/`wind_difficulty`/`road_difficulty`/
     `stop_difficulty`/`accident_difficulty`/`night_difficulty`）が実行時経路の
     どこからも呼ばれておらずテストのみの消費者だった点**。「残骸を残しておく意味は
     ない」というユーザー指摘を受け、6関数すべて削除した。実際の評価は両エンジンとも
     `evaluate_axis_difficulties`/`compute_edge_axis_scores`が材料辞書を直接
     `evaluate_axes_scalar`へ渡す経路を使っており、この6関数を経由していなかった
     （削除しても実行時挙動に変化なし）。テストは`evaluate_axis_scalar(AXIS_DEFINITIONS
     [axis_id], {...})`を直接呼ぶ形へ書き換え、同じ検証内容（breakpoints・cap・None
     伝播）を維持した。
  9. **`car_stress_display_level`が`AXIS_DEFINITIONS["car_stress"].shape`が
     `BreakpointLinearShape`であることをassertで前提しており、運用者が軸スタジオで
     car_stressの評価式をcategorical等へ作り替えるとAssertionErrorがルート生成の
     たびに500として表面化する不具合**。「同上、技術的負債を残しておく意味はない」
     というユーザー指摘を受け、assertをif文へ変え、逆変換が意味を持たない形状へ
     変わった場合はNone（他のdifficulty系関数と同じ「算出不能はNone」の規約）を
     返すよう修正した。
  10. 監査で洗い出した上で**意図的に変更しなかった**唯一の項目:
     `axisLayers.ts: axisLabelsFromCatalogAxes`の`wind: "風"`（ユーザー確認済み:
     「風は、推定軸ではない。対象外で問題ない」。windは専用の動的気象UIを別に持つため、
     そもそも軸スタジオのis_publishedレジストリとは独立した「地図表示レジストリに
     未登録」の構造的な特別軸として設計されている）。
  - **T319の反省を踏まえた対応方針**: 1件のバグを直して終わりにせず、同じ性質の
    問題（「軸スタジオが返す実行時の値」と「ビルド時静的な既存7軸フォールバック」の
    取り違え）を横展開でgrepし尽くしたことが今回との違い。今後同種の改修をする際は、
    修正した1箇所だけでなく`axis-catalog.json`・`PREFERENCE_AXES`・`AXIS_LABELS`・
    `RAMP_AXES`等の静的importを持つ全消費者を毎回洗い出すこと。さらに、いったん
    「意図的に変更しない」と判断した項目についても、ユーザーへ理由を提示した上で
    最終判断を仰ぐこと（「存在確認すれば安全」「実害が顕在化しない」「稀な運用操作が
    前提」という個々の理由づけが妥当に見えても、"技術的負債を残す判断はユーザー自身が
    する"という原則を優先する）。
- 検証: backend pytest 1151 passed（PostGIS統合テスト含む）、ruff（触れたファイルで
  新規指摘なし、既存の無関係な指摘のみ）。frontend vitest 508 passed（新規回帰テスト8件:
  useAxisCatalogのloaded関連、axisInspectorPopupの未知axis_idフォールバック、
  ComparisonPanelの新規軸・非公開軸ケース2件、プリセット無効化ケースを含む）、eslint
  clean、tsc --noEmit clean（既存の無関係なlayout.tsxエラーのみ残存）。axis-catalog.json
  の再生成に伴い、地図チップ・地図レイヤーパネルの推定グループの並び順が
  AXIS_DEFINITIONSのsort_order（accident=5がnight=6より前）どおりに変わった
  （以前の手書き登録順はsort_orderと食い違っていた）ため、影響するfrontendテスト2件
  （MapLayersPanel.test.tsx・MapOverlayControls.test.tsx）の期待値を実際の並びへ更新した。
- 依存: T319（直接の発端）、T309（軸スタジオの可変軸方針そのもの）、T310
  （`display_override`・`axis_display_for()`という単一ソースの基盤）。

### - [x] T321. 全ソース対象のデッドコード監査と修正 規模L（実装完了）

- 背景: T320対応後、ユーザーから「全ソースで、デッドコードがないかを確認して。今回の
  対応で『実質通らないパスだから放置』されている実例がかなりあった。過去の改修時にも
  同様の対応があったのではないか。それは技術的負債になりえる」との指摘を受けた。
  「正当な理由がある、例えば将来的な拡張を踏まえて明確にTODO、FIXMEで残っているものは
  良い」という例外基準と、「優先度で順位付けして上位のものだけでなく、すべてを報告して
  対応して」という完全対応の指示のもとで実施した。
- 手法: backend/domain・backend/services+api・backend/infrastructure+batch+scripts・
  frontend/components・frontend/app+lib+hooksの5領域へ並列エージェントを起票し、
  ファイル重複が無いよう分担を明確化した上で、各エージェントに「実行時コードからの
  参照有無をgrepで再検証してから削除」「削除ではなくfalse positiveと判断したら理由を
  報告」を徹底させた。最重要項目（マイグレーションのブートストラップ欠陥）と
  一次属性ラベルの動的化要否判断は担当者自身が直接対応した。
- **【最重要・実害あり】`backend/migrations/0010〜0019`が`IF NOT EXISTS`を欠いており、
  新規DBのブートストラップが確実に失敗する欠陥**: 0001〜0009は一貫して
  `CREATE TABLE IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS`を使っていたが、0010以降で
  この規約が崩れ素の`CREATE TABLE`/`ADD COLUMN`になっていた。標準ブートストラップ順
  （`create_tables()`→`apply_pending_migrations()`、import_pbf.py等が使う順序）では
  `create_tables()`がORM定義済みの全テーブル・カラムを先に作るため、新規DBでは0010が
  `DuplicateTableError`で落ち以降が未適用のまま中断する（0014が落ちるとaxis_definitions
  のシード投入も入らず、axis_registry_serviceがWARNINGを出しつつコード内蔵既定値へ
  静かに縮退する）。この組み合わせを踏むテストが存在せず、本番・dev環境のDBは
  いずれも0010登場以前に作られていたため誰も踏んでいなかった。0010〜0016・0018・0019へ
  `IF NOT EXISTS`を追加（0017はDDLを含まないため対象外）し、実際にフレッシュDBで
  `create_tables()`→`apply_pending_migrations()`を実行して19件全滴用・axis_definitions
  13行のシード投入まで確認した（全コード変更完了後に再検証済み）。
- backend/domain: `routing.py`のNetworkX経路4関数（`build_networkx_graph`等）と
  `networkx`依存自体を削除（T220でDijkstra本体がscipy.sparse.csgraphへ移行後、
  実行時経路から呼ばれなくなっていた。本番依存が死コード専用という発見）。
  ベンチマーク2本はsparse/indexed版APIへ移植して延命。`registry.py`
  `PrimaryAttributeSpec`の死フィールド5個（`ingest_fn`/`source`/`geometry`/`dtype`/
  `update_cadence`/`description`、T320で削除した`AxisSpec.transform_fn`と同型）・
  `get_axis`/`get_primary_attribute`（実行時未使用）を削除。`geo.py:
  sample_line_coordinates`・`traffic.py: smoothness_score`（未接続の評価テーブル）・
  `osm_adapter.py: osm_nodes_to_poi_specs`（未使用の兄弟関数）を削除。`evaluation.py:
  is_edge_allowed`の`bicycle=no`判定を配列版と同じ`tag_value_is`ヘルパーへ統一
  （関数自体は回帰オラクルとして意図的存続のため削除せず）。`axis-catalog.json`の
  `inputs`重複キー（`primary_attribute_ids`と同一値、フロントテスト専用）を削除。
- backend/services・api: `road_graph_engine.py`の未使用変数`stop_count_per_km`を削除。
  `graph_service.py`の`lean`引数（T219のタイルキャッシュ導入後に呼び出し元を失い
  実行時到達不能だった分岐）と、T248の材料取得統合後に呼ばれなくなった素通し
  ラッパー4本を削除。`wind_service.py`の未読出力フィールド`bearing_deg`、
  `weather_service.py`の常にNoneでしか呼ばれない`at`引数を削除。
  `accidents.py`/`region.py`のタイル検証重複実装（ズーム・座標範囲チェック、
  `math.sinh`のOverflowError回避根拠込み）を`_tile_validation.py`へ共通化。
  `evaluation_service.py`の到達しない`or`デフォルト解決を削除し`preference`を必須化。
  `openrouteservice_engine.py`の構造的に常に真の境界チェック3箇所を削除。
  標高集約（`elevation_service.py`⇔`road_graph_engine.py: _aggregate_elevation`）と
  タイル配信（`region_service.py: _get_tile`⇔`accident_service.py:
  get_accident_tile`）の二重実装を、それぞれ新規`elevation_aggregation.py`・
  `tile_serving.py`へ共通化（`_route_composite_difficulty`⇔`_with_overall_difficulty`は
  役割差の理由が明記された意図的な残置と判断し対象外）。撤去済み機構を指す古い
  コメント5件も実態へ修正。
- backend/infrastructure・batch・scripts: `mark_tile_cached`/`is_tile_cached`
  （実行時未使用。`import_pbf.py: _mark_tiles`と別実装かつ競合時の挙動が異なる
  重複実装だった）を削除。`graph_material_cache.py: cached_tile_count`
  （テストからも未参照の完全デッド）を削除。`scripts/collect_jartic.py`
  （較正対象の`car_stress_level`がT292で廃止済み、唯一の消費先
  `analyze_jartic_calibration.py`も削除済みで無意味な処理になっていた）を削除。
  `verify_postgis_phase0.py`/`verify_phase2_e2e.py`は「pytestが検証しない実DB
  ブートストラップの手動運用ツール」として現役と判断し削除せず、撤去済み機構
  （GINインデックス・`surface_attributes`テーブル）を指すdocstring・チェック名のみ
  実態へ修正。config関連のドキュメントドリフト（Overpass経路・Supabase等の
  撤去済み構成を指す記述）も修正。`axis_registry_meta.revision`は「将来の
  マルチプロセス対応」という明記済みの正当な理由があるwrite-onlyと判断し現状維持。
- frontend/components: `MAP_LAYER_CATEGORY_LABELS`（見出し撤去時の取り残し）・
  `LayerChip`の`disabled`/`title`（全呼び出し元で未指定、到達不能分岐）・
  旧凡例CSS3クラス・未使用アイコン2件（`StatusIcon`/`ResearchIcon`）・
  `DialogTrigger`/`description`prop・`Checkbox`の未使用prop3個・`Button`の
  `danger` variantを削除。静的スナップショット5定数（`MAP_LAYERS`等、実行時は
  `build*(catalog.rampAxes)`直呼びへ全面移行済みでexport側はテスト専用だった）を
  削除し、テストを`build*(RAMP_AXES)`明示呼び出し＋軸スタジオのGUI作成軸を含む
  拡張カタログでの反映確認テストへ書き換えた。`PRIMARY_ATTRIBUTE_CHIP_LABELS`に
  未知attrIdでのフォールバックを追加。
- frontend/app・lib・hooks: **`page.tsx`の`layerVisibility`永続化ホワイトリストが
  ビルド時静的な軸集合固定で、軸スタジオの新規公開軸のON状態がリロードで消える
  実バグ**を、`useStoredState`へ`reloadKey`オプション（値が変わるたびに最新の
  `deserialize`で再復元する仕組み）を追加し、`axisCatalog.loaded`を渡すことで
  「マウント直後は静的フォールバック・カタログ取得完了後は実行時軸集合」の2段階
  復元へ修正。`useMaterialCatalog.ts`の`response.materials.length > 0`ガード
  （T318で`useAxisCatalog.ts`から撤去したのと同型のバグ、取得成功0件をフォールバック
  継続と誤認する）を同じ形へ修正。コメントの事実誤認1件・no-op分岐1件も修正。
- 対応不要と判断した項目（理由込み）: `compute_edge_cost`/`is_edge_allowed`
  （回帰オラクルとして意図的存続、`evaluation_service.py`に明記）、
  `axis_display.py`の`tile_property_inverted`分岐（将来の材料追加への安全側防御と
  明記）、`axis_registry_meta.revision`（前述）、`/api/routes/preview`一式・
  フロント`previewRoute()`（T14/T237で「UIから未使用と既知の疎通確認用デバッグ
  エンドポイント」と文書化済みの意図的な残置。T237で最近も投資されているが放置の
  結果ではなく意識的な保守と判断）、`primaryAttributes.ts`のラベル辞書（`axis-catalog.
  json: primary_attributes[]`を単一ソースとする片側import設計と明記済み。一次属性は
  `MATERIAL_CATALOG`（コード定義）が唯一の情報源でDB/GUIでは増減しないため、軸カタログ
  の動的化問題とは前提が異なる。実害だった未知attrIdのフォールバックのみ追加）。
- 判明したが対応しなかった副次的な観測: `export_openapi.py`実行時、DB由来の
  `shape_params`（JSONB列）内の辞書キー順序が実行のたびに入れ替わりうる
  （PostgreSQLのjsonb型はキー挿入順を保証しないため）。値の集合は同一で実害は
  無いが、`axis-catalog.json`再生成のたびに無意味な差分が出る可能性がある。
  本タスクのスコープ外と判断し対応していない（将来、この差分ノイズが問題になったら
  別タスクとして起票すること）。
- 検証: backend pytest 1137 passed（PostGIS統合テスト含む全件）、ruff（新規指摘
  ゼロ、既存6件はいずれも今回変更していない行・ファイル）。フレッシュDBでの
  `create_tables()`→`apply_pending_migrations()`実機検証を全変更完了後に再実施し
  19マイグレーション全適用・axis_definitions 13行シードを確認。frontend
  vitest 519 passed、eslint clean、tsc --noEmit clean（既知のlayout.tsxエラーも
  解消済み）。コード規模は81ファイル変更、+952/-1,461（正味-509行。回帰テスト追加分
  （`page.test.tsx`・`useMaterialCatalog.test.ts`等の新規テストファイル、既存テストへの
  GUI軸反映確認ケース追加）が純減を相殺しているため、削除した死コード自体の行数は
  この正味値より大きい）。
- 依存: T320（直接の発端、同じ「ビルド時静的値とDB/GUI実行時値の取り違え」系統の
  問題が周辺のデッドコードにも波及していないか確認する動機）。

**T321番号の重複についての注記**: 本タスクと並行して別セッションが独立に「T321」という
番号を本タスク（軸スタジオのカテゴリ値テンプレート拡張）に採番していた。git
fetch/mergeで発覚したため、本タスクをT322へ改番して重複を解消した（T318で確立した
「番号衝突が起きたら片方を改番し注記を残す」運用に従う）。

### - [x] T322. 軸スタジオの「カテゴリ値」テンプレートをcategorical材料（highway/bicycle_infra等）にも対応させる 規模S〜M（実装完了・2026-08-25）

- 背景: ユーザーから「自転車専用道かどうかをどう設定すればいいか分からない」との実機
  フィードバック。調査の結果、`material_catalog.py`には自転車専用道に対応する
  `bicycle_infra`材料（`separated`値）が既に登録されていたが、`AxisComposer.tsx`の
  「カテゴリ値」テンプレートの材料選択が`dtype === "boolean"`のみでフィルタされており、
  `dtype="categorical"`の6材料（highway/surface/bicycle_infra/cycleway_class/
  designation/smoothness）はどのテンプレートからも選択できないUI実装漏れだった。
  backend側は改善計画T292で`CategoricalShape.mapping`が`dict[bool | str, float]`へ
  既に拡張済みで、内部軸（`car_stress_highway_base`等）は実際にcategorical材料を
  使っているため、GUIだけが取り残されていた。
- 決定: 「カテゴリ値」テンプレートの材料選択肢へcategorical dtype材料も含め、選んだ
  材料がcategoricalの場合は真偽値2択の代わりに「値(自由入力)→スコア」の行を複数
  追加できるUIへ切り替える。値の一覧をAPIで返す仕組みは持たない（`material_catalog.py`
  の各categorical材料が取りうる値は生OSMタグ値やdomain関数の分類結果でコード側にしか
  無く、閉じた列挙として一元管理されていない材料もある）ため自由入力とし、マッピングに
  無い値は評価対象外（欠損）として扱われる旨をUI上に明示する。
- 実装: `AxisComposer.tsx`のみの変更（backend側は無改修、T292で既にcategorical値の
  文字列mappingを受け付ける）。
  - 材料選択の`filter`を`dtype === "boolean"`から`dtype === "boolean" || dtype ===
    "categorical"`へ拡張。
  - `Draft`へ`categoricalRows: {value, score}[]`を追加。材料切替時、選択先が
    categoricalかつ現在0行なら空行を1件自動追加（terms/flags同様、最初から
    編集対象が見える状態にする）。
  - `draftFromExisting`は保存済みshapeの`material`のdtype（materialOptionsから
    引く）で真偽値2択/カテゴリ値複数行のどちらを初期表示するか判定する
    （mapping自体のキーはJSON化時点で常に文字列のため、キー型からは判別できない）。
  - `buildShape`もdtypeで分岐し、categoricalの場合は空値行を除外して
    `Object.fromEntries`でmappingを組み立てる。全行が空のまま送信しようとすると
    フォーム側で「値ごとのスコアを少なくとも1件設定してください。」を出して弾く
    （空mappingのまま保存され、全区間が黙って評価不能になる事故を防ぐ）。
  - 値が元データのタグ値と完全一致でなければならないこと、未設定値は評価対象外
    （欠損）になることをヒント文で明示。
  - `docs/architecture.md`のT290節にあった「categorical材料はまだどの評価軸でも
    使えない」という記述は、実際にはT292でbackend側が既に対応済みでGUI側だけが
    取り残されていた（本タスクの直接の原因）ため、T322で解消した旨へ更新した。
- 検証: frontend tsc --noEmit clean、eslint（変更2ファイル）clean、vitest 512 passed
  （AxisStudio.test.tsxへ新規回帰テスト1件を追加、既存回帰なし）。ローカルdev環境
  （frontend:3010・backend:8000、Basic認証はDATABASE_URL同様`.env`のdev専用値）で
  軸スタジオを実機確認し、「カテゴリ値」テンプレートで「自転車インフラ種別」を選ぶと
  値・スコアの複数行編集UIへ切り替わり、`separated`のような値を自由入力できることを
  確認した（保存自体はコンソールエラー無し、`GET /api/axis-definitions`のみブラウザの
  Basic認証URL埋め込み方式に起因する検証環境固有の制約で失敗——実運用のブラウザ
  ネイティブ認証プロンプト経由では発生しない）。

### - [x] T323. 軸の削除時、他軸から材料として参照されている場合にその事実と影響を明示する 規模S〜M（実装完了・2026-08-25）

- 背景: `.claude/commands/review/history/2026-08-25_ui.md` F-1（UIレビュー、専門知識のない
  一般ユーザー視点での軸スタジオ実機確認）。`car_stress`公開軸が内部で依存する6つの下書き軸
  （「車ストレス内部軸: highway基準値」等）が、軸一覧でユーザー自身が作った下書き軸と全く
  同じ表示形式・同じ「削除」ボタンで並ぶ（`AxisStudio.tsx:137-182`は`is_published`の真偽
  のみで表示を分岐し、「他軸から参照されている」という第3の状態を区別しない）。
  `AxisRegistryAdminService.delete()`（`axis_registry_service.py:198-219`）も、最後の1軸
  保護・公開済み軸保護はあるが、他軸の`MaterialTerm.material`としてこのaxis_idが参照されて
  いるかどうかのチェックは無い。
- 指摘の核心（ユーザー訂正、2026-08-25）: 論点は「内部軸の削除を禁止すべきか」ではない
  ——内部軸を意図的に整理・再設計するために削除したい場面は今後もありうるため、一律拒否は
  硬直的すぎる。核心は**削除しようとしている軸が他の軸から参照されている、という事実自体が
  UI上見えないこと**。
- 決定: 削除前に、参照されている場合はその事実と影響（例:「この軸は公開軸『車の圧迫感』から
  参照されています。削除すると評価できなくなります。」）を明示する（確認ダイアログ・警告
  表示等）。一律拒否ガードは「それでも削除しようとした場合の最終防波堤」程度の位置づけに
  留める。
- Scope: frontend側の警告表示はS、backend側で「参照元一覧」を返す仕組み（削除APIレスポンス
  or 事前チェック用エンドポイント）を追加する場合はM。
- 参照: `.claude/commands/review/history/2026-08-25_ui.md` F-1（Confidence: High、削除後の
  実際の壊れ方の詳細はMedium）。
- 実装: frontend側の警告表示のみ実装（Sの方）。`AxisStudio.tsx`に`axesReferencing()`
  （既に取得済みの`definitions`一覧から、削除対象axis_idを`shape`のmaterial/terms/flagsで
  参照している軸を洗い出す純関数）を追加し、`handleDelete`の先頭で参照元があれば
  `window.confirm()`で参照元の表示名と影響を明示してからでないと削除が進まないようにした。
  backend側の「参照元一覧を返す事前チェックAPI」（Mの方）は見送った——frontendは削除時点で
  既に全軸定義を保持しているため、追加のAPI往復なしに同じ検出ができ、投資対効果が低いため
  （必要になれば別トリガーで追加）。一律拒否ガードも追加しなかった（決定通り、内部軸の
  意図的な整理・削除は許容する）。
- 検証: frontend tsc --noEmit clean、eslint clean、vitest 65ファイル/526 passed
  （`AxisStudio.test.tsx`回帰3件追加: 参照ありでキャンセル→削除されない、参照ありで確認→
  削除される、参照なしは確認ダイアログを出さない）。

### - [x] T324. 軸スタジオの変換テンプレート4択の説明文を、専門知識のない一般ユーザー向けに言い換える 規模M（T332へ統合実装・2026-08-25）

- 背景: `.claude/commands/review/history/2026-08-25_ui.md` F-2。新規軸作成の最初の必須判断
  である「変換テンプレート(shape)」の4択（`AxisComposer.tsx:27-34`
  `SHAPE_KIND_DESCRIPTIONS`）が、いずれも数学・統計寄りの専門用語（区分線形補間・線形結合・
  折れ点・レシピ判定済み材料・フラグ加算）で構成されており、「その用語が何であるか」は
  説明していても「どんな時にこれを選ぶか」を説明していない。材料(terms)欄の選択肢自体も
  「勾配%（符号付き）」「向かい風ペナルティ(m/s、正=向かい風)」等、単位・符号規約付きで
  専門知識前提。
- 決定: 各テンプレートの説明文冒頭を「◯◯したいとき」というユースケース文へ言い換える
  （例: 「YES/NOで判定したい（一方通行かどうか、等）→カテゴリ値」「値が大きい/小さいほど
  点数を変えたい（勾配が急なほど減点、等）→区分線形補間」）。技術名は括弧書きで残してよいが
  主役にしない。
- Scope: M（4テンプレート分の文言設計＋表示順の再検討）。
- 参照: `.claude/commands/review/history/2026-08-25_ui.md` F-2（Confidence: High）。
- 実装: ユーザーから追加で「軸スタジオの抜本的な用語平易化・ウィザード化」の要望があり、
  単独の文言差し替えではなくT332（ウィザード化）の一部として実装した。詳細はT332参照。

### - [x] T325. 「車の圧迫感」軸のサマリ表示で、他axis_id参照材料をaxis_idのlabelへ解決する 規模S（実装完了・2026-08-25）

- 背景: `.claude/commands/review/history/2026-08-25_ui.md` F-3。`AxisStudio.tsx:148-152`の
  `materialLabel(t.material)`が、`car_stress`軸のterms（T292「他axis_idを材料として参照する
  内部軸階層」）に対しては該当ラベルを引けず、`axisMaterialsCatalog.ts: materialLabel()`の
  フォールバック（`?? materialId`）でid素通しになる実装バグ。一覧に
  「car_stress_highway_base・car_stress_bicycle_infra_adjustment・...」という生の
  snake_case識別子がそのまま表示される（他の軸は正しく日本語ラベル化されている）。
- 決定: `materialLabel`呼び出し側で、`t.material`が材料idではなくaxis_idを指すケース
  （`known_axis_ids`に含まれる場合）は、そのaxis_idの`label`を解決して表示する
  （`AxisStudio`は`definitions`一覧を既に持っているため追加取得は不要）。
- Scope: S（`AxisStudio.tsx`のサマリ生成部1箇所）。
- 参照: `.claude/commands/review/history/2026-08-25_ui.md` F-3（Confidence: High、コード上の
  フォールバック仕様・呼び出し元を確認済み）。
- 実装: `labelForMaterialOrAxis(id, definitions)`（`definitions`一覧からaxis_idの一致を
  探し、見つかればその`label`、無ければ`materialLabel(id)`）を追加。サマリ生成自体も
  categorical/flag_sum/terms別々の三項分岐から、T323で追加済みの`materialIdsOf(shape)`
  （shape種別を問わず材料id一覧を返す）を使う1行へ統合し、重複していたロジックを解消した。
- 検証: frontend tsc --noEmit clean、eslint clean、vitest 65ファイル/530 passed
  （`AxisStudio.test.tsx`回帰1件追加: 他axis_id参照材料が生識別子ではなく参照先の表示名で
  出ることを確認）。

### - [x] T326. 軸スタジオ「カテゴリ値」テンプレートの選択肢ラベルを、多値対応後の実態に合わせて修正 規模S（T332へ統合実装・2026-08-25）

- 背景: `.claude/commands/review/history/2026-08-25_ui.md` F-4。T322で「カテゴリ値」
  テンプレートをcategorical材料（多値）にも対応させたが、`<select>`の選択肢ラベル
  （`AxisComposer.tsx:419`付近 `<option value="categorical">カテゴリ値（真偽2値→定数）
  </option>`）の文言更新を忘れていた（説明文`SHAPE_KIND_DESCRIPTIONS`側は更新済み）。
  「真偽2値」という表記が実態と食い違い、多値カテゴリ材料が選べることに気づきにくい。
- 決定: 「カテゴリ値（真偽値・複数値→定数）」等、多値対応を反映した文言へ修正する。
- Scope: S（1行）。
- 参照: `.claude/commands/review/history/2026-08-25_ui.md` F-4（Confidence: High）。
- 実装: T332でこの選択肢自体（旧`<select>`の`カテゴリ値（真偽2値→定数）`という文言）を
  カード選択UIへ置き換えたため、「真偽2値」という食い違った表記自体が無くなる形で解消した。

### - [x] T327. 軸スタジオの折れ点(breakpoints)編集欄に、スコアの向き（走りやすさの規約）を明示する 規模S（T332へ統合実装・2026-08-25）

- 背景: `.claude/commands/review/history/2026-08-25_ui.md` F-5。「折れ点(breakpoints)
  [入力値, スコア0-100]」欄（`AxisComposer.tsx:454-471`付近）は数値ペアを並べるだけで、
  スコア0〜100が「走りやすさ」を指すのか「難しさ」を指すのかがフィールド上に明示されない。
  既存軸のbreakpoints実データ（`gradient`: `[0,0],[3,25],[6,50],[9,75],[15,100]`）から
  逆算すると「スコアが高いほど走りやすい」という規約と読み取れるが、この規約はUI文言の
  どこにも書かれていない。専門知識のないユーザーが折れ点を自分で編集すると、意図と逆方向の
  スコアリングを誤って作ってしまうリスクが高い。
- 決定: 見出し付近に「スコアは0(最も走りにくい)〜100(最も走りやすい)」という1行の規約説明を
  追加する。折れ点の推移をグラフでプレビュー表示する拡張は別途検討（規模M〜L、本タスクの
  スコープ外）。
- Scope: S（文言追加のみ）。
- 参照: `.claude/commands/review/history/2026-08-25_ui.md` F-5（Confidence: High、UI文言の
  欠如は確認済み。実データからの規約推測はInference）。
- 実装: T332の「点数の詳細を設定」ステップ（折れ点編集欄）にこの規約説明を追加した。
  グラフプレビュー化は決定通りスコープ外のまま。

**T328番号の重複についての注記**: 本タスク（軸スタジオのウィザード化）は当初T328として
実装したが、並行セッションが独立に「T328〜T331」（テスト品質監査の指摘4件）を先に
`origin/master`へ起票していたことがマージ時に判明したため、T332へ改番した
（T318・T321で確立した「番号衝突が起きたら片方を改番し注記を残す」運用に従う）。
本節はテーブル上ではT324〜T327の直後（本来の実装順序）に置くが、実際の番号は
T332であり、直後に続くテスト品質監査のT328〜T331とは無関係の別タスクである。

### - [x] T332. 軸スタジオをウィザード形式へ再設計し、専門知識のない一般ユーザー向けに用語を平易化する（T324/T326/T327を統合実装） 規模L（実装完了・2026-08-25）

- 背景: ユーザーから、T323完了直後に「追加で、軸スタジオの抜本的な用語平易化・ウィザード化も
  実施して」との要望。これはUIレビュー（`.claude/commands/review/history/2026-08-25_ui.md`）
  のDEFER項目「軸スタジオの初見向け抜本的簡略化（用語の全面平易化・ウィザード形式への
  再設計）」（トリガー: 一般ユーザーへ軸作成機能を公開する方針が決まった時点、として
  一旦保留していたもの）を、トリガー未到達のまま前倒しで実施する明示指示。
- 決定: `AxisComposer.tsx`を単一の長いフォームから、4ステップのウィザード（1.基本情報→
  2.点数のつけ方を選ぶ→3.点数の詳細を設定→4.地図表示・公開）へ再構成する。内部で保持する
  4種の変換テンプレート(shape kind)自体・`Draft`/`buildShape`/`draftFromExisting`の
  ロジックは変更しない（ADR「新しい計算テンプレートの追加は引き続きコード変更が必要」の
  方針を維持、変わるのはUIの見せ方のみ）。あわせて、内容が重なるT324（テンプレート4択の
  文言平易化）・T326（「カテゴリ値」選択肢ラベルの文言修正）・T327（折れ点欄のスコア向き
  明示）をこの実装の中に統合し、個別の小修正としては行わない（同じ画面・同じ箇所への
  複数回の書き換えを避けるため）。
- 実装:
  - 「変換テンプレート(shape)」という技術名の`<select>`を撤去し、「この軸はどうやって
    点数をつけますか？」という質問＋4枚のカード選択（ラジオボタン）へ置き換えた
    （`SHAPE_KIND_OPTIONS`）。各カードは「はい/いいえ、または種類ごとに点数を決める」
    「数値の大きさに応じて点数を変える」「複数の要素の有無を数えて減点・加点する」
    「他の軸の計算結果をもとに点数を変える（上級者向け）」という利用例主体の文言（T324）。
    4枚目（`recipe_then_breakpoint_linear`、内部軸参照という上級者向けの用途）には
    「上級者向け」の注記を付け、他3枚より控えめに扱う（UIレビューのSIMPLIFY所感を反映）。
    旧`<option value="categorical">カテゴリ値（真偽2値→定数）</option>`という食い違った
    文言自体が無くなる形でT326も解消。
  - 折れ点(breakpoints)編集欄に「スコアは0(最も走りにくい)〜100(最も走りやすい)で入力
    します。入力値が大きくなるほどスコアを上げれば「値が大きいほど走りやすい」、下げれば
    「値が大きいほど走りにくい」という軸になります。」という規約説明を追加（T327）。
  - ステップ管理（`STEPS`/`stepIndex`/`validateStep`/`goNext`/`goBack`）を新設。
    「次へ」を押す前に該当ステップの入力を検証し、エラーがあればそのステップに留まって
    理由を示す。単一の`<form>`のまま表示するステップだけ切り替える設計のため、最終ステップ
    以外でのEnterキー暗黙送信は「次へ」として扱うよう`handleSubmit`を分岐させた。
  - **実機確認で発見・修正した設計不具合**: 表示名(label)が4文字を超える場合に地図チップの
    略称(chip_label)を要求する既存バリデーションを、当初は「基本情報」ステップ（表示名の
    ステップ）に置いていたところ、`chip_label`欄自体は最終ステップ（地図表示・公開）に
    あるため、「次の地図表示・公開ステップで設定してください」と案内されるだけでその
    ステップへ進めない詰み状態になっていた。検証をchip_label欄が実在する「地図表示・公開」
    ステップ側へ移設して解消した（Playwright実機確認で発覚、修正後に長い表示名でも
    最終ステップまで進め、そこでその場で略称を設定して解決できることを再確認した）。
  - `AxisStudio.module.css`にステップ表示・カード選択用のCSSクラスを追加
    （`.stepIndicator`/`.shapeKindOptions`/`.shapeKindOption`等）。
- 検証: frontend tsc --noEmit clean、eslint clean、vitest 65ファイル/529 passed
  （`AxisStudio.test.tsx`に回帰5件追加: 表示名未入力で次へ進めない、戻るで入力値が残る、
  折れ点ステップにスコア向き説明が出る、カテゴリ値の材料選択がステップをまたいでも動作、
  地図表示ON/OFFトグルが最終ステップにある、の各ケース。既存の関連3テストもウィザード
  導線へ合わせて更新）。ローカルdev環境（frontend:3010・backend:8000）でPlaywright実機
  確認し、デスクトップ幅で4ステップ全てを実際に操作（表示名入力→カード選択→材料選択→
  値入力→地図表示設定→送信）、モバイル幅390pxでも横スクロール無し・カード選択のタップ
  操作が機能することを確認した。送信時のbackend側バリデーション（材料の排他帰属チェック、
  T268）が実際に409で拒否されるケースも実機で踏み、ダイアログが開いたままエラー文言が
  表示されること（サイレント失敗しないこと）を確認した。
- 依存: T321〜T323（UIレビューとその起票群）、T270（軸スタジオ基盤）。

### - [x] T328. テスト品質監査で発見した現存する実装バグ4件の修正 規模S（実装完了）

- 背景: T321完了後、「実装とテストの乖離が無いか」という観点で全211実装ファイルを対象に
  機械的トリアージ＋16並列エージェントによる全件監査を実施した（成果物:
  https://claude.ai/code/artifact/46de02ba-3db5-4356-a776-215262996dfe ）。この監査は
  「テストの不足」を探す過程で、テストの話ではなく**実装自体が壊れている**箇所を4件
  発見した。いずれも小規模な修正で完結する。
- 対応内容（4件、優先度順）:
  1. **`backend/benchmarks/bench_evaluate_graph.py:33-37`（今回のT321コミット自身が原因）**:
     `EvaluationService.evaluate_graph()`の第4引数`preference`をT321で必須化した際、
     追従修正した`bench_nearest_node.py`等4ファイルにこのファイルだけ含まれておらず、
     実行すると`TypeError: missing 1 required positional argument: 'preference'`で
     即失敗する。`run_all.py`経由の実行も道連れで落ちる。`preference=preference`を
     呼び出しへ追加するだけで直る。
  2. **`backend/scripts/verify_postgis_phase0.py:245-261`（T321とは無関係の既存バグ）**:
     ステップ5（「生データを消しGraphServiceがPostGISだけからゼロ構築できるか」の検証）が、
     検証対象bboxのタイルを`road_graph_tiles`へマークする処理を一度も呼んでいないため、
     `GraphService.get_or_build_graph_with_attributes`が`_ensure_tiles_cached`
     （`graph_service.py:73-90`）の判定で常に`None`を返し、この統合検証は毎回
     サイレントに失敗している。`cleanup()`実行後・GraphService呼び出し前に、bboxを
     カバーする全タイルを`road_graph_tiles`へ明示的にマークするステップを追加する。
     まさにこのスクリプトは、T321で発見したmigration 0010〜0020のIF NOT EXISTS欠如
     バグの再発防止としてpytest化を推奨した検証内容そのものであり、放置すると
     T329（下記）の統合テスト新設時に同じ穴を引き継ぐリスクがある。
  3. **`frontend/src/services/regionApi.ts:144-171`（`refreshBasemapCache`）**:
     `!response.ok`時の`throw`が同じtry節内にあるため直後のcatchで再捕捉され、
     実際は「失敗 (HTTP xxx)」なのに「失敗 (通信エラー)」と誤ってログされる
     （ユーザー影響は無いが、障害調査時にログを誤誘導する。docs/logging.mdの
     エラー分類の正確性方針に反する）。`fetchAxisInspector`と同じ構造（`!response.ok`
     判定をtryの外に出す）へ揃える。
  4. **`backend/scripts/compare_engines_quality.py:54-65`（`run_ors`）**:
     docstringは「本番と同じ組み立て方で両エンジンを構築する」と明記するが、
     `OpenRouteServiceEngine`構築時に`repository`引数を渡しておらず、本番では有効な
     路面・停止・交差点・事故の評価軸がORS側だけ欠落した非対称比較になっている。
     T236（エンジン移行判断）の材料として使う以上、系統的バイアスを排除する必要がある。
     `repository=`を明示的に注入するよう修正する。
- 完了条件: 4件とも修正し、`bench_evaluate_graph.py`は実行してクラッシュしないこと、
  `verify_postgis_phase0.py`は全ステップPASSすることを実機確認する。backend/frontend
  全テストgreenを維持する。
- 依存: T321（監査の発端）。
- **実装メモ（2026-08-25完了）**: 4件とも修正し、実機検証済み。
  1. `bench_evaluate_graph.py`: `preference=preference`を追加、実行してクラッシュしない
     ことを確認。
  2. `verify_postgis_phase0.py`: ステップ5の直前でBBOXを覆う全タイルを
     `road_graph_tiles`へ明示的にマークするよう修正（従来あった`cleanup()`呼び出しは、
     ステップ1-2で保存した生データ・Edgeそのものも消してしまい「フレッシュな
     GraphServiceがステップ1-2の永続化済みデータを正しく読めるか」という本来の検証意図と
     矛盾していたため撤去した）。実機検証の過程で**もう1件、無関係の既存バグ**を発見・
     修正: `build_road_graph`がT262でPydantic `RoadGraph`から軽量dataclass
     `LeanRoadGraph`を返すよう移行済みだったが、本スクリプトのステップ2はフィルタ後に
     旧`RoadGraph(...)`へ素通しで渡しており、`LeanNode`/`LeanEdge`を`Node`/
     `DirectedEdge`型フィールドへ渡す形になって`ValidationError`で即クラッシュしていた
     （`LeanRoadGraph(...)`へ差し替えて解消）。ついでに既存のruff指摘（未使用変数
     `applied_first`、T321以前からの指摘）も解消。フレッシュなdev DBに対し実行し
     21/21 PASSを確認済み。
  3. `regionApi.ts: refreshBasemapCache`: `fetchAxisInspector`と同じ構造（`!response.ok`
     判定をtryの外に出す）へ揃えた。`regionApi.test.ts`に、HTTPエラー時`debugLog`が
     「失敗 (HTTP xxx)」で1回だけ呼ばれ「失敗 (通信エラー)」では呼ばれないことを
     直接検証する回帰テストを追加。
  4. `compare_engines_quality.py`: `run_ors`が`session_factory`を受け取り、
     `run_road_graph`と同じ「呼び出しごとに新規セッション」パターンで
     `RoadGraphRepository`を`OpenRouteServiceEngine(repository=...)`へ注入するよう修正。
  検証: backend pytest 1137 passed、ruff clean。frontend vitest 524 passed、eslint/tsc
  clean。

### - [x] T329. テスト実行コストの是正 規模S（実装完了）

- 背景: 上記監査（T328と同じ成果物）で、テスト実行時間そのものへの懸念を受けてコスト面も
  調査した。結論として**削減すべき冗長テストはほぼ見つからなかった**（「モック比率が
  高い」という機械判定の大半は、jsdomの未実装API穴埋めや意図的なオラクル比較設計と
  判明し誤検知だった）。唯一の実質的な支配要因は1本の巨大なテストと、テスト方針からの
  逸脱1件。
- 対応内容:
  1. **`backend/tests/test_road_graph_repository.py::test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`**:
     backend全体のテスト実行時間52.56秒のうち42.75秒（81%）を単独で占める
     （17,000way/34,000edge規模でチャンク境界を検証）。以下を実施する。
     - (a) `way_count`を17,000→約10,050へ削減（`_ID_CHUNK_SIZE=10_000`の境界を
       2チャンック踏破する条件は維持したまま約4割減）
     - (b) 検証方法を`get_graph_in_bbox`による全edgeジオメトリのWKBフルデコードから、
       `road_edges`の行数を直接COUNTする軽量クエリへ変更する
     - (c) (a)(b)後も数秒〜十秒台に収まらない場合は`@pytest.mark.slow`等の新規マーカーを
       導入しCI高速フィードバックから分離する（導入時はdocs/testing.mdへの追記が必要）。
       まずは(a)(b)のみで様子を見る。
  2. **`backend/tests/test_basemap_routes.py::test_basemap_refresh_is_rate_limited_per_client`**:
     docs/testing.mdが定めるレート制限境界値テストのパターン（`rate_limiter.check_rate_limit`
     を直接呼んで上限-1件を埋め、実HTTPは境界の1〜2回に絞る）に反し、上限回数分
     （`settings.basemap_refresh_rate_limit_per_minute`＝6回）を実際にHTTPループで
     消費している。同ファイルの他のレート制限テストは正しいパターンに従っており、
     このテストだけが取り残されている。規定パターンへ揃える。
- 完了条件: backend全テストスイートの実行時間を計測し、42.75秒テストの短縮幅を報告する。
  test_basemap_routes.pyの該当テストがdocs/testing.mdのパターンに従う形へ修正されている
  こと。
- 依存: T321（監査の発端）。
- **実装メモ（2026-08-25完了）**: (a)(b)を実施した時点で当該テスト単体が42.75秒→1.31秒
  （約97%減）まで縮み、想定より大幅に改善したため(c)の`slow`マーカー導入は不要と判断し
  見送った。`test_basemap_refresh_is_rate_limited_per_client`も
  `test_basemap_proxy_is_rate_limited_per_client`と同じ形（`rate_limiter.check_rate_limit`
  で上限-1件を埋め、実HTTPは境界の1〜2回）へ揃えた。検証: backend pytest
  **全体で52.56秒→11.65秒（約78%短縮）**、1137 passed、ruff clean。
- **追記（同日、ユーザー指摘によりfrontend側も対応）**: 「フロントのテストも開発サイクルの
  ボトルネックになりつつある」という指摘を受け、backendと同様に調査した。frontendは
  backendと違い突出して遅い1本は無く（最遅個別テストでも559ms）、65テストファイル分の
  DOM環境構築コストの積み上げが支配的だった。対応:
  - **既定のDOM環境をjsdomからhappy-domへ変更**（`vitest.config.mts: test.environment`）。
    テストスイート全体で30秒→19秒（約35%短縮）を複数回の実行で安定して確認。
    `canvas.getContext("2d")`が未実装でnullを返す挙動（`windArrowIcon.ts`/
    `routeArrowIcon.ts`のフォールバック分岐が依存）がjsdomと同一であることを診断テストで
    個別に確認済み。65ファイル・524テスト全件green（happy-domによる挙動差での破綻なし）。
    未使用になった`jsdom`依存は削除、`happy-dom`を新規devDependencyとして追加。
    `docs/testing.md`の関連記述も更新。
  - **`isolate: false`（ファイル間でモジュール状態・DOM環境を使い回す高速化）も試したが
    不採用**: 30秒→15〜17秒とさらに速くなるが、実行のたびに異なる4〜8件のテストが
    不安定に失敗する（ファイル間の状態漏れ）副作用があり、docs/testing.md基本原則3
    「速度最適化はテストの検証内容を変えない範囲で行う」に反するため見送った。
  - `pool: "threads"`の明示指定・`poolOptions.threads.{min,max}Threads`の明示（4コア
    フル活用）はいずれも有意な差が無かった（元々デフォルトで同等の並列度が出ていたと
    推定）ため採用しなかった。
  - 検証: frontend vitest 65 files / 524 tests passed、eslint/tsc --noEmit clean。

### - [x] T330. テストカバレッジ欠落の是正（影響度「高」・複数レビューで確認済み） 規模M（実装完了）

- 背景: T328と同じ監査成果物より、**影響度が高く、かつ独立した複数回のレビューパスで
  一致して検出された**——すなわち一過性の誤検知ではないと確信度が高い——カバレッジ欠落を
  優先度の高い順にまとめる。共通する性質として、いずれも「過去の実障害・実データ消失
  バグの再発防止コード」または「既定構成で全リクエストが通る主経路」がテストされていない、
  という重大度の高いパターンに該当する。
- 対応内容（8件、優先度順）:
  1. **`frontend/src/components/AxisStudio/AxisComposer.tsx`（600行、テスト無し）**:
     軸スタジオの中核フォーム。`buildShape()`の4テンプレート分岐（breakpoint_linear/
     recipe_then_breakpoint_linear/categorical/flag_sum）、既存軸編集時の
     `priority_overrides`/`display_override`の素通し保持——コード自身のコメントが
     「以前は黙って失われていた」と明記する実データ消失バグの再発防止対象——、
     バリデーション（label空欄・chip_label長）のいずれも、フォーム送信を一度も
     実行しない`AxisStudio.test.tsx`からは検証されていない。`AxisComposer.test.tsx`を
     新設し、4テンプレートの送信payload・素通し保持の回帰・バリデーションを検証する。
  2. **`frontend/src/proxy.ts:35-64`（`/admin`配下のBasic認証ミドルウェア、テスト無し）**:
     資格情報未設定時401・ヘッダ欠落401・Base64デコード失敗時の安全側401（例外を
     投げない）・タイミング攻撃対策`safeEqual`の長さ違い時の挙動、いずれも未検証。
     認可をすり抜けるリグレッションがCIで検知できない。上記6分岐の最小テストを追加する。
  3. **`backend/app/domain/route.py:202-215`（`_merge_axis_difficulties`）**:
     「既存軸を非公開にするとKeyError/ValidationErrorで500になる」という実障害
     （T316フォローアップ、2026-08-25発生）の修正箇所。区間ごとのaxis_difficultiesを
     axis_id別に距離加重平均する集約ロジックが、複数区間の加重平均・部分的axis_id
     欠損・全区間で欠損時の除外いずれも未検証（`test_route.py`に"axis_difficulties"
     の言及が1件も無い）。上記3パターンの最小ケースを追加する。
  4. **`backend/app/services/road_graph_engine.py:341,386` / `infrastructure/road_graph_repository.py:1237`（`get_edges_with_geometry`）**:
     既定エンジン(road_graph)の全リクエスト・全方位で通る「DB実ジオメトリ優先」の
     主経路（`hydrated.get(edge_id) or context.graph.edges[edge_id]`）が、
     `test_road_graph_engine.py`・`test_routes_preview.py`双方のFakeが常に`{}`を
     返すため一度も踏まれず、稀にしか通らない防御的フォールバックだけがテストされている
     逆転状態。PostGIS統合テストも0件。Fakeに非空データを返すケースを追加し、実PostGIS
     統合テストを新設する。付随して`hard_filters`（T266）のエンジンレベル配線確認テスト
     （`road_graph_engine.py:168,183,244`）も同時に追加する。
  5. **フレッシュDBブートストラップ経路（`backend/app/infrastructure/migrate.py`）**:
     本番唯一のブートストラップ順序（`create_tables()`→`apply_pending_migrations()`）を
     検証する自動テストが無い。`conftest.py`は`create_all`のみで`migrations/*.sql`を
     一度も適用しない。この構造的な穴が、migration 0010〜0020のIF NOT EXISTS欠如という
     同一バグを2回連続発生させた直接の原因（T321参照）。T328で修正する
     `verify_postgis_phase0.py`相当の検証を、フレッシュDBに対し
     `create_tables()`→`apply_pending_migrations(engine, migrations_dir=MIGRATIONS_DIR)`
     を実行し例外なく完了することを確認するpytest統合テストとして新設し、CIへ組み込む。
  6. **`backend/app/batch/match_designations.py:57-75`（`_MATCH_SQL`）**:
     「geographyキャストでGiST索引を認識できず30分超無応答になった」という重大な性能
     事故の実績があるST_Buffer/ST_Intersects/ST_Unionクエリ本体が、`run_designations`
     経由でもテスト経由でも一度も実行されていない（テストは前後のDELETE/INSERT
     原子性のみ対象）。少数件seedでの実PostGIS統合テストを追加する。
  7. **`backend/app/infrastructure/database.py:12-85`（テスト無し）**:
     Session pooler対Transaction poolerの実機障害・command_timeout値という重い経緯を
     持つ接続設定にもかかわらず、シングルトン生成すら検証されていない
     （`test_health.py`は`get_engine`自体を差し替えてテストしており実装本体は未実行）。
     シングルトン性・タイムアウト設定値の反映を検証する軽量テストを追加する。
  8. **`frontend/src/components/Map/useLayerDataStatus.ts`（176行、テストファイル自体が
     存在しない）**: 「idleから呼ぶと進行中障害を誤って解除する」という実機バグ修正の
     長文コメント付きロジック（`clearStaleTrackedSourceErrors`）と、
     `querySourceFeatures`の重複呼び出しを避けるメモ化（`computeLayerDataStatus`）を
     含むが無テスト。メモ化条件とerror解除条件（`isSourceLoaded`=true時のみ）の
     単体テストを追加する。
- 完了条件: 8件それぞれにテストを追加し、backend/frontend全テストgreenを維持する。
  新設した統合テスト（5番）はCIで実行されることを確認する。
- 依存: T321（監査の発端）、T328（4番はverify_postgis_phase0.pyの並行修正と整合させる
  必要がある）。
- **実装メモ（2026-08-25完了）**: 8件すべてにテストを追加した（6並列エージェント、
  うち3件はPostGIS統合テストのため専用DB`ridecompass_test_agent5`/`_agent6`を追加
  provisioningし他作業との接続競合を回避）。
  1. `AxisComposer.test.tsx`新設（17件）: 4テンプレート変換・
     priority_overrides/display_override素通し保持の回帰・draftFromExisting往復・
     バリデーションを検証。
  2. `proxy.test.ts`新設（12件、`@vitest-environment node`）: 資格情報未設定/ヘッダ欠落/
     Base64デコード失敗/`:`区切り無し/`safeEqual`長さ違いいずれも例外を投げず401、
     正しい資格情報のみ200を検証。
  3. `test_route.py`へ`_merge_axis_difficulties`の距離加重平均・部分的axis_id欠損・
     全区間欠損時の除外を検証する4件を追加。
  4. `test_road_graph_engine.py`/`test_graph_service.py`/`test_road_graph_repository.py`へ
     `get_edges_with_geometry`の「hydrated優先」主経路（PostGIS統合テスト含む）と
     `hard_filters`のエンジンレベル配線確認を追加。
  5. `test_migrate.py`へ、まっさらなDBから`create_tables()`→`apply_pending_migrations()`
     を実行し例外なく完了・冪等・`axis_definitions`13行シードまで検証する統合テストを
     新設。**このテストが実際に本物のバグを検出した**: `AxisDefinitionRow.updated_at`
     （`app/infrastructure/axis_definition_models.py`）に`server_default`が無く、
     `create_tables()`が先に走る空DBからのブートストラップ経路でmigration 0014の
     INSERTがNOT NULL制約違反になっていた（他の全追加カラムは同種の理由で
     `server_default`を持つのに、最初からあるこのカラムだけ0014導入時に見落とされて
     いた——T321が修正したIF NOT EXISTS欠如と同じバグ類、本テスト新設で初めて
     捕捉できた）。`server_default="now()"`を追加して修正。
  6. `test_match_designations.py`へ`_MATCH_SQL`（ST_Buffer/ST_Intersects/ST_Union）を
     実際にPostGIS上で実行する統合テスト3件（交差率反映・閾値未満除外・複数指定路線
     重複時の二重計上防止）を追加。
  7. `test_database.py`新設（10件）: `get_engine`/`get_route_generation_engine`等の
     シングルトン性、bind先の整合性、`connect_args`（`command_timeout`等）の反映を検証。
  8. `useLayerDataStatus.test.ts`新設（7件）: `computeLayerDataStatus`のメモ化
     （同一source-layer共有時に`querySourceFeatures`が1回のみ）と
     `clearStaleTrackedSourceErrors`の`isSourceLoaded`条件付きerror解除を検証。
  検証: backend pytest 1162 passed、ruff clean（既存の無関係な指摘5件は今回の変更前から
  存在するpre-existingで対象外）。frontend vitest 567 passed、eslint/tsc clean。
  なお本タスクとは無関係に、直近コミットへのCIで`axis-catalog.json`の生成順序drift
  （DB接続可否で`categories`辞書のキー順が変わる既存の非決定性）を発見したため、
  T333として別途起票した。

### - [ ] T331. テストカバレッジ欠落の是正（影響度「中」・残り） 規模L（大部分完了・2026-08-26、残り5項目）

- 背景: T330に次ぐ優先度の指摘群。T330ほどの緊急性は無いが、放置すると同種のパターン
  （静かに縮退する失敗処理・兄弟ファイルとの非対称・新設モジュールの単体テスト欠如）が
  積み上がる。領域別に列挙する（全指摘の詳細・根拠・対象行番号は監査成果物
  https://claude.ai/code/artifact/46de02ba-3db5-4356-a776-215262996dfe の該当セクション
  および全ファイル一覧を参照。ここでは要点のみ）。
- 対応内容（領域別）:
  - **backend/domain**（B判定2件）: `accident.py: distance_weighted_accident_density`の
    境界値（distance_sum=0等）、`region.py: lonlat_to_tile_pixel`の座標変換精度
    （標高評価の入力に直結、姉妹関数`tile_bounds_lonlat`は網羅的なのにこれだけ欠落）。
  - **backend/services・api**（B判定3件）: `dependencies.py`のDB分岐DIファクトリ5本
    （`get_graph_service`等）が直接テストされない、`accidents.py`のy方向境界テストが
    region.py側と非対称。
  - **backend/infrastructure・batch**（C判定3件・D判定2件）: `precompute_elevation_attributes.py`
    （テストファイル自体が無い）、`http_client.py`（timeout別キャッシュという唯一の
    要件が無検証）、`precompute_edge_attribute_counts.py`（`run()`本体・UPSERT無テスト）、
    `graph_material_cache.py`（LRU立ち退き無テスト）、`import_accidents.py`/
    `import_designations.py`/`import_pbf.py`のrun_importオーケストレーション本体が
    CI未検証（手動E2Eスクリプトのみ）。
  - **backend/infrastructure（クライアント群）**: `wbgt_client.py`/`jma_warning_client.py`/
    `flood_client.py`が、同型の`weather_client.py`（キャッシュ・リトライまで網羅的）と
    非対称にテスト無し。失敗時は静かに空リストへ縮退する設計のため気づきにくい。
  - **backend/batch（新設・境界）**: `pbf_source.py`（osmium境界の唯一の層、サイレントな
    データ欠損リスク）、`precompute_way_attribute_counts.py`（兄弟の
    `precompute_edge_attribute_counts.py`は`_chunked`のテストがあるのにこれだけ無い）。
  - **frontend/components**（C判定2件・B判定多数）: `Map/LayerChip.tsx`のdataStatus状態
    表示（statusDot/title）に肯定的な検証が無い、`Map/routeArrowIcon.ts`/`windArrowIcon.ts`
    はjsdomのcanvas制約で描画ロジック自体が未実行、`MapView.tsx`の
    `routesToFeatureCollection`/`computeRouteBounds`が通常テストでは未検証（ベンチマーク
    経由のみ）、`AxisStudio.tsx`のCRUD実行系（複製・削除・非公開化・保存）、
    `BottomSheet.tsx`の高さ調整系（ドラッグ・キーボード・`clampSheetHeightVh`）、
    `Map/staticAttributeLayers.ts`のDESIGNATION関連exportが完全未テスト（過去のT74実績
    あり）、`Map/secondaryAxes.ts`の「動的」軸除外フィルタ（過去のコードレビュー指摘の
    修正）、`RouteList.tsx`の選択状態スタイル・条件付き表示4項目。
  - **frontend/app・lib・hooks・services**（D判定多数）: `lib/researchMode.ts`/
    `hooks/useResearchMode.ts`（同型の`debugLog.ts`は網羅的なのに無テスト）、
    `axis-definitions`配下のroute handler3本、`app/admin/page.tsx`、
    `services/axisAdminApi.ts`/`lib/adminApiProxy.ts`（`AxisStudio.test.tsx`が
    モジュール全体をモックするため実装コードが一度も実行されない。同型の`fetchJson.ts`は
    模範的にテストされておりそのまま流用可能）、`services/axisCatalogApi.ts`/
    `materialCatalogApi.ts`（兄弟の`versionApi.ts`等は皆テストあり）、
    `hooks/useWeatherGrid.ts`の詳細格子失敗フォールバック・間隔変更リセット。
  - **frontend/app/page.tsx**: `handleGenerate`（0件成功・例外失敗・研究モードスロット
    記録）と、天候/警報/WBGT/氾濫予報4並列fetchの「リクエストIDで古い応答を捨てる」
    競合対策ロジックが、`page.test.tsx`（layerVisibility永続化のみ検証）からは
    無防備。15個以上あるハンドラのうち直接検証されているのは実質0個。
- 優先着手順の目安: 「同型の兄弟ファイルとの非対称」（コピーで済むため低コスト・
  高費用対効果）→「新設モジュールの単体テスト」→「巨大コンポーネントの主要ハンドラ」の順。
- 完了条件: 上記領域それぞれで最低1件以上のテストを追加し、D/C判定だったファイルが
  B以上へ改善していることを監査成果物の分類表と突き合わせて確認する。規模が大きいため
  複数回のコミットに分割してよい（都度backend/frontend全テストgreenを確認）。
- 依存: T321（監査の発端）、T330（同種パターンの優先対応）。
- **実装（2026-08-26）**: 4エージェント並行実行×2バッチ（各々独立git worktree）で、
  7領域見出し全てに最低1件以上のテストを追加した。backend 171件（クライアント群25・
  domain/services境界値26・新設モジュール34・importオーケストレーション実DB結合14）、
  frontend 149件（兄弟ファイル非対称36・componentsの非対称79・残りモジュール27・
  page.tsx主要ハンドラ7）、計320件を追加、全件パス。型チェックもクリーン。実装コードは
  一切変更していない（`import_designations`向け`designation_conn`フィクスチャの
  `designation_import_runs`クリア漏れ[他テストとの状態リーク]のみ副次的に修正）。
  コミット: `830473a`（前半4領域）・`7a31719`（後半4領域）。
- **残り5項目（未対応、次回着手時にこのタスクを再オープン）**:
  - `precompute_elevation_attributes.py`（テストファイル自体が無い）
  - `precompute_edge_attribute_counts.py`の`run()`本体・UPSERT
  - `MapView.tsx`の`routesToFeatureCollection`/`computeRouteBounds`
  - `AxisStudio.tsx`のCRUD実行系（複製・削除・非公開化・保存）
  - `routeArrowIcon.ts`/`windArrowIcon.ts`（jsdom/happy-domのcanvas制約で描画ロジック
    自体が未実行のまま。テスト環境側の制約緩和が必要な可能性があり、他の項目より
    調査コストが高い）

### - [x] T333. axis-catalog.json（categorical材料のcategories辞書）の生成順序がDB接続可否で非決定になる 規模S〜M（実装完了・2026-08-26）

- 背景: T330（フレッシュDBブートストラップ統合テスト新設）の実装検証中、直近コミット
  （5325af1）に対するCIで`git diff --exit-code -- frontend/src/types/generated/`が失敗し、
  `frontend/src/types/generated/axis-catalog.json`の`categorical`材料（`highway`/
  `bicycle_infra`等）の`categories`辞書のキー順序だけが変わる（値の集合は完全一致）
  differが検出された。原因を特定済み: `app/services/axis_registry_service.py:93`の
  `except Exception ... # noqa: BLE001`が、DB接続に失敗した場合は起動を止めず
  コード内蔵の既定値`AXIS_DEFINITIONS`（`domain/axis_definitions.py`のPython dict
  リテラル、挿入順が決定的）へフォールバックする設計になっている。一方DBに接続できた
  場合は`shape_params`（JSONB列）をDBから読み込んで使うため、PostgreSQLのjsonb型が
  オブジェクトキーを内部的に（キー長→バイト順で）並べ替えた順序になる。つまり
  `export_openapi.py`（`generate:api`が呼ぶ生成スクリプト）の出力するJSONのキー順序が、
  実行時にDBへ接続できたかどうかという環境差だけで変わってしまう。CI環境ではDB未接続
  （またはDBはあるが軸未シード）でコード側フォールバックが発動し、コミット済みの
  `axis-catalog.json`はDB接続済みの開発環境で生成されたものだったため、順序が食い違った
  と推測される（値の内容自体に差分は無く、CIが偽陽性でdriftを検知し続ける状態）。
- 対応内容（案、要設計判断）: `categories`辞書をJSON出力する直前で決定的な順序へ正規化する
  （例: キーをソートしてから`model_dump`する、またはエクスポート専用のシリアライズ層で
  `dict(sorted(...))`する）。ただし`AXIS_DEFINITIONS`の辞書の**挿入順自体**は合成
  （composite）の浮動小数点加算順として意味を持つ場所が別にある
  （`axis_definitions.py:263`のコメント、`test_evaluation_bulk.py`が検証）ため、
  正規化の対象を「表示専用の`categories`辞書（`TileInputSpec.categories`、
  frontendの色分け表示にしか使わない、加算順とは無関係）」に限定し、評価計算に使う
  他の辞書の挿入順には影響させないこと。
- 完了条件: DB接続あり/なし両方の環境で`export_openapi.py`を実行し、生成される
  `axis-catalog.json`が完全一致することを実機確認する。既存のcategorical材料を使う
  frontend/backendの全テストgreenを維持する。
- 依存: T330（発見の発端）。CLAUDE.mdの「コミット時の同期ルール」（OpenAPI生成物ドリフト
  防止）に該当する再発防止対象。
- 実装: 当初`domain/axis_display.py: derive_ramp_inputs`側の`str_mapping`組み立て時に
  ソートする案で着手したが、実機検証（DB接続あり/なし両方でexport_openapi.pyを実行し
  diff）したところ、この修正だけでは`highway`/`bicycle_infra`のcategoriesに加えて
  `designation`のcategoriesも依然として順序が食い違うことが判明した。原因は
  `car_stress`軸の`display_override`（`TileInputSpec.categories={"emergency_transport":
  1.0, ...}`という手書きPythonリテラル、`axis_definitions.py:579`）自体もDBの
  `display_override`列（JSONB）へ往復して読み込まれており、この経路も同じくPostgreSQLの
  jsonb内部順の影響を受けていたため。個別の組み立て箇所を1つずつ塞ぐのではなく、
  `registry.py: TileInputSpec`に`categories`フィールドの`field_validator`を追加し、
  モデル構築のたびに（コード内リテラル・DB読み込み・APIリクエストボディいずれの経路でも）
  キーをソートして正規化する形に変更した（当初案の`axis_display.py`側の修正は撤回・
  リバート済み、こちらの単一箇所の修正に一本化）。
- 検証: DB接続あり/なし両方の環境で`export_openapi.py`を実行し、生成される
  `axis-catalog.json`が完全一致することを実機確認した（`diff`でバイト同一）。正規手順
  （DB接続あり→`export_openapi.py`→`npm run generate:api`）で生成物を再生成し、
  `openapi.json`/`api.d.ts`等の他生成物には差分が出ないこと、`axis-catalog.json`の
  差分がcategoricalの`categories`辞書のキー順序（アルファベット順へ正規化、値の集合は
  無変更）のみであることを確認した。`test_registry.py`/`test_axis_display.py`/
  `test_axis_definitions.py`/`test_registry_defaults.py`（59件）green。backend全体は
  `test_axis_definition_repository.py`除外で1116 passed / 29 failed
  （`test_axis_registry_service.py`全件、`test_axis_definition_repository.py`を含めると
  さらに15件）、いずれも同一原因の「ローカルテストDBに`icon_id`列が無い」エラーで
  T333とは無関係。修正前のHEAD状態でも同じ失敗を再現し切り分け済み。別タスクとして
  起票案を提示済み。

### - [x] T334. 地図チップ「表示する項目を選ぶ」設定パネルの各項目に個別の情報アイコンを追加する 規模M（実装完了・2026-08-25）

- 背景: T317（動的グループを「地図の見え方」パネルから撤去し、地図上チップの▶パネルへ
  説明文を移設）の同日、ユーザーが直後の指示「▶内に移動した説明文は消して」と、それとは
  別に「動的アイコン（推定/観測/動的の情報アイコンから開く『表示する項目を選ぶ』
  ウィンドウ）の配下要素にも個別の情報アイコンを追加してほしい」という依頼を続けて
  出していたが、後者が実装されないまま抜け落ちていたことが後日判明した。T317追記の
  一括撤去（▶パネル本体の説明文・折りたたみ中設定パネルの入れ子（！）の両方を撤去）が
  この依頼も巻き込んで消してしまっていた可能性が高い。
- 対象範囲の確認: ユーザー確認により、対象は「動的」グループに限らず「推定・観測・動的の
  3グループすべて」で、かつ「同じ作りになるはず」（グループ間で実装を分けない）という
  明示指示があった。
- 決定: `MapOverlayControls.tsx`の`renderVisibilitySettings`（推定/観測/動的の3グループが
  共通で使う、折りたたみ中に見出し脇の情報アイコンから開く「表示する項目を選ぶ」設定
  パネル）の各項目行に、説明文(panelHint)を持つ項目だけ個別の情報アイコンを追加し、
  押すとその項目の行の直下に説明文がインラインで開閉表示されるようにする。T317追記で
  「読みにくい」とされたのは▶パネル本体への**常時表示**であり、今回は設定パネル内で
  ユーザーが個別に開閉する形のため矛盾しない。
- 実装: 3グループ共通の`renderVisibilitySettings`1箇所の改修のみ（グループごとの分岐は
  追加しない、ユーザー指示どおりの汎用実装）。
  - データ配線: `mapLayers.ts: MapLayerDescriptor.panelHint`（既存フィールド、観測/動的
    メンバーの説明文）と`AXIS_DEFINITIONS.panel_hint`（`secondaryAxes.ts:
    SecondaryAxisSummary`に新規`panelHint`フィールドを追加し、`useAxisCatalog.ts`が
    既に中継していた`CatalogAxis.panel_hint`をそのまま反映）の2系統を、
    `MapOverlayControls.tsx: OverlayLayerChip.panelHint`（新規フィールド）と
    `renderVisibilitySettings`の`items[].description`（新規フィールド）という共通の
    受け皿へ流し込む。`page.tsx`の`overlayLayers`組み立てへ`panelHint: layer.panelHint`を
    1行追加。
  - UI: `items`一覧の各`<li>`に、`description`を持つ項目だけ`InfoIcon`ボタンを追加
    （`.detailRowLabel`がflex:1のため後続要素は自然と行右端に来る）。押すと
    `openInfoKeys`（新規state、非表示設定`hiddenIds`とは別のSet、一時的な状態のため
    localStorageへは永続化しない）を切り替え、開いている項目だけその直下に新しい
    `<li>`（`.visibilityInfoRow`、チェックボックス列幅ぶん字下げ）で説明文を表示する。
  - CSS: `.visibilityInfoButton`（`.visibilityCheckbox`に近い1.2rem角の丸ボタン）・
    `.visibilityInfoButtonActive`・`.visibilityInfoRow`を追加。
- 検証: frontend tsc --noEmit clean、eslint clean。`MapOverlayControls.test.tsx`に回帰
  3件追加（観測/動的グループで同じ検証をit.eachで実施し「作りが同じ」ことを裏付け、
  推定グループはSECONDARY_AXES実データ[stop_density軸のpanel_hint]で確認）。Playwright
  実機確認: デスクトップで観測グループの設定パネルを開き、panelHintを持つ「道路種別」に
  情報アイコンが出て押すと説明文が展開/再度押すと閉じること、panelHintを持たない「路面」
  には情報アイコンが出ないことを確認。モバイル幅390pxでも横スクロールなし・タップ操作
  可能なことを確認。コンソールエラーなし。
- 依存: T317（同日の一連の作業、抜け落ちの直接の発端）。
- 2026-08-26追記（撤去）: 同じ説明文(panelHint)がサイドバー「地図の見え方」パネル
  （MapLayersPanel.tsx: renderHintPopoverTrigger、各レイヤーセクション見出し脇に常設）
  からも確認できるようになったため、地図上チップの「表示する項目を選ぶ」設定パネル側
  （本タスクで追加した個別情報アイコン）は重複と判断し撤去した。`MapOverlayControls.tsx`
  の`renderVisibilitySettings`から情報アイコンボタン・`openInfoKeys`state・
  `OverlayLayerChip.panelHint`フィールドを削除、`page.tsx`のpanelHint配線・
  `MapOverlayControls.module.css`の`.visibilityInfoButton`系スタイル・回帰テスト3件も
  合わせて削除。`panelHint`データ自体（mapLayers.ts/secondaryAxes.ts）はMapLayersPanel.tsx
  側が使い続けるため変更していない。tsc --noEmit clean、関連テスト71件パス、Playwright
  実機確認で観測・推定・動的の3グループとも情報アイコンが出ないことを確認。

### - [x] T335. CI(backend)のtest_match_designations.pyがCI環境（PostGIS 16）でだけ失敗する 規模S〜M（2026-08-26完了）

- 背景: T333対応中にCI状況を確認したところ、`api-contract`とは別に`backend`ジョブ
  （`python -m pytest -q -n auto --dist loadgroup`）が失敗していることを発見した。
  ユーザーがCIの実ログを共有してくれたことで特定: 失敗箇所は
  `test_match_designations.py::TestRunMatch::test_overlapping_designations_complete_without_error`
  （T330で新規追加）で、`critical_logistics`のmatched_ratioが期待通り算出されず
  `assert set(by_kind) == {"emergency_transport", "critical_logistics"}`が
  `{"emergency_transport"}`のみで失敗していた。ローカル（実DB・実PostGIS、PG18）では
  該当ファイル6件とも常にpassし、この失敗は一度も再現しなかった。
- **訂正（当て推量による誤修正、同日中に発覚・revert済み）**: 当初「Wayの座標を指定路線と
  完全一致させている退化ケードが原因」という仮説のもとWayの座標を約3mずらす修正を
  一度コミット・プッシュしたが、根拠となる実測データが無いまま行った当て推量だった。
  実際にCIへ反映したところ、直していなかった`test_overlapping_designations_...`は
  相変わらず失敗し、それまでCIでもpassしていた`test_intersecting_way_gets_matched_ratio`
  まで新たに失敗させてしまった（`candidates=1 matched=0`、matched_ratioが閾値未満に
  低下）。ユーザー指摘「あてずっぽうはやめて、根拠を作って積み上げて実地検証して」を
  受け、このコミットは`git revert`で即座に取り消した（コミット`d7e801a`→revert
  `9b0d686`）。この訂正の重要な副産物: `test_intersecting_way_gets_matched_ratio`は
  「Way座標が指定路線と完全一致」という全く同じパターンで**CIでも単独では問題なく
  pass**していた事実が確定した。つまり「完全一致ジオメトリの退化」という当初の仮説
  そのものが誤りだったと判断する（単独の完全一致では壊れず、複数の指定路線・複数kindが
  同時に存在する状況でのみ壊れるため、原因は別にある）。
- 現在の対応（実地検証、当て推量ではなくCIの生データに基づく）: 本番SQL・既存テストは
  一切変更せず、`TestRunMatch`へ診断専用テスト
  `test_diagnostic_t335_raw_match_sql_output_for_two_kinds`を追加した。他テストの
  未クリーンアップ行（`route_designations`は`Base.metadata`の対象外で
  `road_graph_session`のtruncateが効かないため、`TestRunMatch`内の各テストが挿入した
  行は後続テストにも残り続ける）や重複行の複雑さを排した最小構成（専用way_id=9001、
  emergency_transport/critical_logistics各1行、完全一致ジオメトリ）で、`_MATCH_SQL`と
  同じCTEロジックをratioフィルタ前の中間結果（`ST_Intersects`結果・
  `ST_GeometryType`・`ST_AsText`・`unioned`後の長さ）まで可視化し、assertを意図的に
  常に失敗させることでpytestの失敗メッセージにダンプを埋め込み、CIログとして
  確認できるようにした。ローカル（PG18）ではこの最小構成で両kindとも
  `intersects=True`・`ratio=1.0`と問題なく、想定どおり再現しない。
- 診断ラウンド2（CI実測）: 座標完全一致・offset_3m・offset_10m・buffer_zero・
  swapped_argsの5候補をUNION ALLで同時比較したところ、offset_10m（座標完全一致の
  退化とは到底言えない距離）まで含め全候補が`LINESTRING EMPTY`のままだった。これにより
  「座標完全一致の退化ケース」仮説は完全に否定された。
- 診断ラウンド3（CI実測）: 「`route_designations`/`designation_attributes`は
  `osm_raw_ways`等と異なり`Base.metadata`（road_graph_models.py）に属さず
  `road_graph_session`のtruncate対象外なので、`TestRunMatch`内の他テストの残留行が
  `_MATCH_SQL`のCTE処理に干渉している」という仮説（コードで確認済みの事実が根拠）を
  検証するため、診断テスト冒頭で明示的にTRUNCATEしてから最小構成を再構築したが、
  それでも`ST_Intersects=true`かつ`ST_Intersection`が`LINESTRING EMPTY`のまま再現した。
  あわせてway・designation・buffer各ジオメトリの生値（SRID・点数・WKT・ST_IsValid）を
  直接確認したが、いずれも正常だった。これにより「他テストの残留行によるCTE干渉」
  「入力ジオメトリ自体の不正」の両仮説も否定された。
- ヒント確認: ユーザーから「NGが起き始めたのはb101082から」という指摘を受け
  `git show b101082^1:backend/tests/test_match_designations.py`で当該コミット直前の
  内容を確認したところ、`TestRunMatch`クラス自体（`DESIG_LINE`・`WAY_MATCH_ID`・
  `run_match`のimportを含む）がb101082（T330マージ）で新規追加されたものであり、
  それ以前はこのファイルに`TestWriteMatches`しかなかったことが分かった。本番SQL
  （`_MATCH_SQL`・バッファ幅定数）はこの前後で無変更（直近の変更履歴はT137〜T150の
  d245099まで遡り無関係）。つまり「動いていたものが壊れた」のではなく、「新規追加した
  テストが、これまで一度も踏まれたことのない座標パターン（線がバッファの中心軸と
  完全に平行・同一直線上）で、CI環境のGEOSが持つ既存の数値ロバストネス上の不具合を
  初めて踏み抜いた」という構図であることが確定した。
- 診断ラウンド4（CI実測・確定）: 消去法で残った仮説「GEOS OverlayNGの数値ロバストネス
  不具合（ST_Intersectsは頂点近傍判定、ST_Intersectionはnoding処理で別アルゴリズムの
  ため食い違いうる）」を検証するため、PostGIS公式ドキュメントが明記する対策候補
  （`ST_Intersection`の3引数版=gridSize指定でsnap-rounding noding経路に切り替える）を
  gridsize_1e-9/1e-7/1e-5とbuffer_zeroの4候補でCI実測した。結果:
  gridSize指定の3候補は全て正しい長さ（181.0m）を返し、baselineとbuffer_zeroは
  引き続き空だった。gridSizeが唯一有効な対策であることを実地確認した。
- 修正: `_MATCH_SQL`の`ST_Intersection(w.geom, b.buffer_geom)`に
  `gridSize=1e-7`（度単位、OSM座標精度＝小数点以下7桁と同じ桁。バッファ幅20mより
  はるかに細かく精度劣化なし）を追加。診断専用テスト
  `test_diagnostic_t335_gridsize_candidates_for_empty_intersection`は原因特定・
  修正確認後に削除した。
- 依存: T330（当該テストの新規追加元）。

### - [x] T336. bicycle_infra材料をcar_stress_bicycle_infra_adjustment内部軸から正規化フラグ材料群へ置き換える 規模M〔P2〕（2026-08-25完了）

- 背景: [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)
  の設計判断（2026-08-26）。`bicycle_infra`材料（`classify_bicycle_infrastructure`、
  複数タグの優先順位付き分類）を「正規化フラグ材料＋線形結合」で近似したときの
  一致率を実データ（`osm_raw_ways` 86,642件）で検証し、ズレは0.0127%のみと確認した。
  評価軸としては新しいプリミティブを追加せず既存の`BreakpointLinearShape`だけで
  表現できることが分かったが、実装（`car_stress_bicycle_infra_adjustment`内部軸が
  依然`bicycle_infra`材料を直接参照している）はまだこの方針に追従していない。
- 内容: `cycleway`/`cycleway:left`/`cycleway:right`/`cycleway:both`/`highway`から、
  `cycleway_has_track`/`cycleway_has_lane`/`cycleway_has_shared`/`highway_is_cycleway`の
  正規化された真偽値材料を`material_catalog.py`へ追加し、
  `car_stress_bicycle_infra_adjustment`のshapeを`CategoricalShape(material=
  "bicycle_infra", ...)`から`BreakpointLinearShape`（正規化材料の重み付き和、
  `_CAR_STRESS_BICYCLE_INFRA_FLAG_WEIGHTS`/`_CAR_STRESS_BICYCLE_INFRA_FLAG_BREAKPOINTS`、
  `axis_definitions.py`）へ置き換えた。`bicycle_infra`材料自体は地図表示用
  （`staticAttributeLayers.ts`の凡例・car_stress軸`display_override`の
  ramp）に引き続き必要なため削除していない。
- 実装メモ（着手時に判明した設計時点未把握の追加スコープ）: `bicycle_infra`材料は
  評価パイプライン中3箇所（`domain/evaluation.py: axis_inspector_breakdown`・
  `compute_edge_axis_scores`、`services/openrouteservice_engine.py`）が
  `MATERIAL_CATALOG`のextractorを経由せず`classify_bicycle_infrastructure`を直接呼んで
  手組みのmaterials辞書へ詰めるスカラー評価経路だったため、新4材料もこの3箇所すべてで
  併せて配線しないと「常に補正なし(0点)」へ静かに劣化する（`BreakpointLinearShape`の
  `MaterialTerm`既定`required=True`のため、新4材料が辞書に無ければ内部軸全体がNone→
  親のcar_stress側は`required=False`で0点扱いに丸め込まれ、例外にもならず気付けない）。
  抽出ロジックの重複を避けるため`domain/recipe.py: bicycle_infra_flags(tags, highway)`へ
  1箇所へ集約し、3箇所とも`**bicycle_infra_flags(...)`で辞書へ混ぜ込む形にした
  （`bicycle_infra`材料と同じ構成）。この配線漏れを検知する回帰テストを
  `test_evaluation.py`（`compute_edge_axis_scores`/`axis_inspector_breakdown`各1件）へ
  追加、`openrouteservice_engine.py`側は既存の
  `test_car_stress_and_bicycle_infra_reflect_nearest_way_tags_when_repository_injected`
  が既に同じシナリオ（primary+cycleway=track）を検証しており追加不要だった。
- 検証: DBアクセス無しでも検証可能な形にした——cycleway系タグ（track/lane/
  share_busway/shared_lane/opposite_lane/separate/no/未設定）×highway×bicycleタグの
  組み合わせ約17万通りを全数combinatorialで旧`classify_bicycle_infrastructure`ベースの
  スコアと新実装を突き合わせるテスト（`test_axis_definitions.py`）を追加し、
  cycleway/highway由来の判定（track/lane/shared_busway/roadwayの優先順位）は1件も
  ズレが無いこと、ズレは設計文書が想定していたbicycle由来の分岐（shared_pedestrian・
  prohibitedのAND条件、正規化フラグの線形結合では意図的に近似対象外）由来のみである
  ことを機械的に確認した（設計判断時の実データ検証[ズレ0.0127%]と同じ性質）。
- 完了条件: `car_stress`軸のスコアが置き換え前とほぼ一致すること（許容ズレはbicycle由来
  の分岐のみ、cycleway/highway由来のズレは0件）を確認し、`bicycle_infra`材料が評価軸
  （`AXIS_DEFINITIONS`のshape）から参照されなくなった（地図表示`TileInputSpec`からの
  参照のみ残る）。

### - [x] T337. cycleway_class材料の未使用状態を整理する 規模S〔P3〕（2026-08-25完了）

- 背景: [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)
  の調査で判明: `cycleway_class`材料は`axis_definitions.py`のどの軸からも参照されて
  いないが、`material_catalog.py`に登録済みのため軸スタジオの材料選択肢には現れ続けて
  いる。選ぶと値ごとのスコア入力（当初のUX課題）に利用者が直面しうる。
- 内容（着手時に判断）: (a) 削除する、(b) T336と合わせて正規化フラグ材料へ置き換えて
  実際に使えるようにする、(c) 現状のまま「登録されているが未使用」を許容する、の
  いずれか。実データではズレ0.0012%とT336同様に正規化で近似可能なことは確認済み。
  → **(a) 削除を選択した**。T336で追加した`cycleway_has_track`/`cycleway_has_lane`/
  `cycleway_has_shared`正規化フラグ材料が既に同じcycleway系タグをより細かい粒度で
  カバーしており、(b)（cycleway_classを評価軸で使えるようにする）は屋上屋になる
  だけで実利が無い。(c)（現状維持）は背景で述べた軸スタジオUXの問題をそのまま残す。
  加えて調査の結果、地図表示側（`staticAttributeLayers.ts`・`axisLayers.ts`）でも
  `cycleway_class`は一切参照されておらず（`bicycle_infra`のみが表示に使われている）、
  MVTタイルへ焼き込むだけで完全に無消費だったことが判明したため、`MATERIAL_CATALOG`
  登録だけでなく、抽出関数（`material_catalog.py`）・正準判定関数
  （`domain/recipe.py: cycleway_class`）・タイルCASE式
  （`infrastructure/road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）まで
  全層を削除した（フロントfallback`lib/axisMaterialsCatalog.ts`も同期）。タイル
  プロパティ削除に伴い`ROAD_SURFACE_TILE_VERSION`を13→14へ対上げ（`region_service.py`・
  `frontend/src/services/regionApi.ts`）。プロパティ削除のみで参照側への影響が
  無いため、デプロイ順序制約は無い（詳細はコード側コメント参照）。

### - [x] T338. designation材料（3値カテゴリ）の未使用状態を整理する 規模S〔P3〕（2026-08-25完了）

- 背景: [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)
  の調査で判明: `designation`材料（`emergency_transport`/`critical_logistics`/`both`の
  3値）はどの評価軸からも参照されておらず、既に単純化済みの`is_designated`（真偽値）が
  代わりに使われている。実データで"both"が35.01%という高頻度で発生し、他の
  categorical材料と異なりAND条件が構造的に頻発するため、正規化＋線形結合による近似は
  そのままでは不向き。
- 内容（着手時に判断）: T337と同様、削除するか、評価目的では使わず表示専用の材料として
  明示的に位置づけ直すか（`GET /api/material-catalog`のレスポンスから表示専用フラグで
  除外する等）を判断する。
  → **表示専用として明示的に位置づけ直す方を選択した**（T337のcycleway_class削除とは
  異なる判断）。designationは`cycleway_class`と違い、地図表示側（`staticAttributeLayers.ts`
  のdesignation凡例レイヤー）で実際に使われている生きたデータのため、削除は不適切。
  `MaterialSpec`へ`display_only: bool = False`フィールドを追加し（`material_catalog.py`）、
  designationへ`display_only=True`を設定。`GET /api/material-catalog`（新設
  `axis_studio_materials()`）はこれを除外して返すため軸スタジオの選択肢には現れなくなるが、
  `MATERIAL_CATALOG`自体からは削除しない（`is_known_material`はTrueのまま、
  `tile_property`経由の地図表示・car_stress`display_override`のtile_inputsには影響しない）。
  未使用になっていた`all_materials()`（旧`GET /api/material-catalog`の唯一の呼び出し元）は
  `axis_studio_materials()`へ置き換えて削除した。フロントfallback
  `lib/axisMaterialsCatalog.ts`から`designation`エントリも削除し同期。
- **フォローアップ（2026-08-26、ユーザー指摘）**: 上記の`display_only`対応は
  「3値のまま隠す」という場当たり的な対応で、T336（`bicycle_infra`→正規化フラグ材料）と
  設計思想が食い違っていた、という指摘を受けた。正しくは`designation`を正規化フラグ材料へ
  も分解すべき——「N10路線かどうか」「N12路線かどうか」「特定路線かどうか」の3つに分け、
  評価は「特定路線かどうか」（`is_designated`、既存・変更なし）だけで判定する。対応した
  内容:
  - `_ROAD_SURFACE_TILE_MVT_SQL`（`infrastructure/road_graph_repository.py`）が既に内部で
    計算していた`d.is_ert`/`d.is_cl`（3値へCASE式で畳み込む前の生フラグ）を、
    `is_emergency_transport`/`is_critical_logistics`という2つのタイルプロパティとして
    そのまま追加焼き込みした（`ROAD_SURFACE_TILE_VERSION`13→15、プロパティ追加のみで
    デプロイ順序制約なし）。
  - `material_catalog.py`へ`is_emergency_transport`[N10該当]/`is_critical_logistics`
    [N12該当]の2材料を新設（`display_only=False`、軸スタジオの選択肢に現れる）。ただし
    `extractor`は未設定のまま（`is_designated`・`designation`・`oneway`と同じ「トリガー
    付きDEFER」、設計原則9）——`is_designated`と異なりどの内蔵軸からも参照されないため、
    種別ごとのper-edge kindをcompute_edge_costs_bulk・3つのスカラー評価経路へ運ぶ配線は
    実際にそのニーズ（軸スタジオでの利用）が出るまで新設しない。
  - `designation`（3値、地図表示専用）は方針どおり維持（ユーザー確認済み: 地図の凡例
    レイヤーは変更不要）。フロントfallback`lib/axisMaterialsCatalog.ts`に2材料を追加。

### - [x] T339. 材料抽出（extractor）の完全宣言駆動化 規模M〜L〔P2〕（2026-08-25完了）

- 背景: T280で`MaterialSpec.extractor`により「材料→抽出関数」の対応表は宣言的になったが、
  関数の中身自体は依然手書きのPythonコード。実際には現行17個のextractorのうち15個が
  「単一タグの生値取得」「タグ値の単純一致判定（`tag_value_is`）」「数値パース
  （`parse_maxspeed`/`parse_lanes`）」「件数/距離の密度計算」という少数の汎用パターンに
  分類できる（複雑な組み合わせ分類は`bicycle_infra`/`cycleway_class`の2つのみ、
  T336・T337参照）。この汎用パターンが宣言的パラメータとして表現できていないため、
  単純な新規材料（例: 新しいOSMタグを1つ追加するだけ）でも依然Python関数を1つ書く
  必要が残っている。
- 内容（候補、着手時に設計判断）: `MaterialSpec`へ`extractor_kind`（例:
  `"raw_tag"`/`"tag_equals"`/`"count_per_km"`等）＋パラメータ（タグ名・期待値等）の
  宣言を追加し、対応する汎用extractor実装から動的に関数を組み立てる。既存の複雑な
  2材料（bicycle_infra/cycleway_class）は引き続き専用関数のままでよい（T336・T337で
  評価軸からは切り離される想定のため、地図表示専用としてこの宣言化の対象外にできる）。
  → **`MaterialSpec`へのフィールド追加ではなく、パラメータ化された「extractorファクトリ
  関数」（`raw_way_tag_extractor`/`tag_equals_extractor`/`way_tag_parser_extractor`/
  `count_per_km_extractor`、`material_catalog.py`）を採用した**。`extractor_kind`文字列＋
  frozen pydanticモデルの事後変換という案は、材料自体をGUIから追加・編集できるように
  しない（コード変更＋デプロイのみ）という既存方針の下では`extractor_kind`をデータとして
  持つ実益が無く（実行時に動的解釈する相手がGUIでもDBでもない）、frozenモデルの
  事後書き換えという複雑さだけが増えるため見送った。ファクトリ関数は
  `extractor=raw_way_tag_extractor("smoothness", normalize=True)`のように
  `MaterialSpec`宣言の場で直接呼び出せ、「宣言的パラメータで表現する」という目的を
  フィールド追加なしで満たす。既存extractor 9件（motor_vehicle_no/no_lit/has_tunnel/
  bridge/maxspeed_kmh/lanes_count/smoothness/stop_count_per_km/
  intersection_count_per_km）をこれらのファクトリへ置き換え、対応する専用関数
  （`_extract_motor_vehicle_no`等）を削除した（振る舞いは全数テストで不変を確認）。
  cycleway_classはT337で削除済みのため、専用関数のまま残るのは`bicycle_infra`のみ
  （gradient_percent/surface_good/surface/accident_count_per_km_year/is_designated/
  highwayは各々固有の計算経路を持つため対象外）。
- 完了条件: 単純パターンに該当する新規材料1件を、専用のPython関数を書かずに
  `material_catalog.py`への宣言追加だけで抽出可能にできることを実証する。
  → **`tracktype`材料（OSMの未舗装路グレードタグ、grade1〜grade5）で実証した**。
  `extractor=raw_way_tag_extractor("tracktype", normalize=True)`という1行の宣言のみで
  追加し、専用の`def _extract_tracktype`は書いていない
  （`test_material_catalog.py: test_tracktype_material_is_extractable_without_a_
  dedicated_function`で固定）。フロントfallback`lib/axisMaterialsCatalog.ts`にも追加。

### - [x] T340. highway/surface/smoothnessの値一覧・ラベル提示（軸スタジオの値入力UX改善） 規模M〔P2〕（2026-08-25完了）

- 背景: 2026-08-26のユーザー報告「軸スタジオで、値ごとのスコアを入れるのに、物理名を
  直接入力はきつい。暗記していない」が発端。`highway`/`surface`/`smoothness`は
  OSMタグの生値でオープンエンドなため、事前に全量を静的に列挙できない
  （`bicycle_infra`等の閉じた集合とは異なる、詳細は
  [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)
  参照）。
- 内容（検討済み、未実装）: DBに実際に存在する値を動的取得するAPIを新設し
  （`_ROAD_SURFACE_TILE_MVT_SQL`の計算式を再利用したクエリが必要、単純な`DISTINCT`
  では取れない材料もある）、既知の値には日本語ラベルを付与、未知の値はタグ値
  そのまま表示するフォールバックとする。`AxisComposer.tsx`の値入力欄をテキスト
  自由入力から選択式へ変更する。
  → **実装時に判明: highway/surface/smoothnessの3材料に限れば単純な`SELECT DISTINCT`
  （surface/smoothnessは`lower(btrim(...))`、highwayは生値のまま——OSM取込プロファイルで
  既に許可リスト化された正準値のため正規化不要）で足り、`_ROAD_SURFACE_TILE_MVT_SQL`の
  複雑な計算式の再利用は不要だった**（「単純なDISTINCTでは取れない材料もある」という
  当初の想定は`bicycle_infra`のような優先順位付き分類材料を指しており、本タスクの対象
  3材料には該当しなかった）。新設エンドポイントは
  `GET /api/material-catalog/{material_id}/values`
  （`api/routers/material_catalog.py`、既知だが動的値一覧に対応していない材料・
  DB未接続・DB障害はいずれも空リスト、未知の材料idは404）。DB読み取りは
  `RawOsmRepository.get_distinct_material_values`（`infrastructure/
  road_graph_repository.py`）、グレースフルデグレード（DB障害→空リスト、
  `log_external_call`によるログ・統計）は`RegionService.get_material_values`
  （`get_axis_inspector`と同じ方針）が担う。
  → **ラベル付与は「UI語彙のカタログ集約」原則に従い、backendではなくfrontend側
  （`lib/materialValueLabels.ts`）で行う**。highway/surfaceは既存の地図絞り込みUI
  カタログ（`components/Map/roadFilterAxes.ts`のHIGHWAY_GROUPS/SURFACE_GROUPS、
  export済みに変更）から「タグ値→表示グループの日本語ラベル」をそのまま導出し
  （同じ語彙を2箇所に手書きしない）、smoothnessはOSM標準8値のラベルを新規に定義した。
  未知の値・未登録の材料idはタグ値そのまま表示するフォールバック
  （`materialValueLabel`）。
  → **`AxisComposer.tsx`の値入力欄は、自由テキスト入力を完全に置き換えるのではなく、
  隣に「値の候補」セレクト（`useMaterialValues`フック経由で取得した値一覧、
  materialValueLabelでラベル表示）を添える形にした**（選ぶと自由テキスト入力欄へ値が
  反映される）。値一覧が空（動的値一覧に非対応の材料・DB未接続・取得失敗）の間は
  候補セレクト自体を表示せず、従来どおりの自由テキスト入力のみになる（フォールバック）。
  自由テキスト入力を完全に廃止しなかったのは、DBにまだ反映されていない新しいタグ値や
  想定外の値を軸スタジオ側で先回りして設定したいケースを塞がないため。
- 依存: T339（材料抽出の宣言化が先に進むなら、値一覧取得の仕組みもその枠組みに
  乗せられる可能性がある。ただし本タスクは独立に着手可能）。→ 実際には独立に着手し、
  T339の宣言的extractorファクトリとは無関係（値一覧取得はDB直接読み取りのため
  material_catalog.pyのextractor機構を経由しない）。

### - [x] T341. 地図表示ロジックの定義場所をSQL側へ一本化し、分離原則をdocs/architecture.mdへ反映 規模S（2026-08-26完了、当初想定から縮小）

- 背景（2026-08-26、当初案からユーザー指摘を受けて修正）: 当初は
  [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)
  の原則をドキュメント化するだけの想定だったが、調査の結果`bicycle_infra`/
  `cycleway_class`の分類ロジックには2種類の異なる重複パターンがあると判明した。
  - **良い設計（既に片側import、対応不要）**: `surface_good`は`GOOD_OSM_SURFACE_TAGS`/
    `BAD_OSM_SURFACE_TAGS`という**値のリスト**を`domain/road.py`にのみ定義し、SQL側
    （`_ROAD_SURFACE_TILE_MVT_SQL`）は`bindparam`でその値を受け取って`ANY()`判定
    しているだけ（[road_graph_repository.py:186-191](../backend/app/infrastructure/road_graph_repository.py:186)）。
  - **本物の重複（対応が必要）**: `bicycle_infra`（`domain/traffic.py:
    classify_bicycle_infrastructure`）・`cycleway_class`（`domain/recipe.py:
    cycleway_class`）は、**優先順位付き条件分岐というロジック構造そのもの**が
    Python関数とSQL CASE式の両方に独立して手書きされている（`domain/traffic.py`の
    docstringに「SQL側にPythonを呼び出す手段が無いため、やむを得ず2箇所に存在する」と
    明記済み、整合性は`test_road_graph_repository.py`のテストで担保するのみ）。
  - `classify_bicycle_infrastructure`は`evaluation.py`・`road_graph_engine.py`・
    `openrouteservice_engine.py`の複数箇所から呼ばれている（全て「car_stress軸の
    ための材料計算」という同一目的の呼び出し）。
- 内容（着手時に再調査した結果、当初想定を修正）: 当初は「T336・T337完了後、Python分類
  関数は評価パイプラインから一切呼ばれなくなるのでSQL側へ一本化（Python側を削除）できる」
  という想定だったが、実際に呼び出し元を1件ずつ追跡すると誤りだった。
  - `cycleway_class`（`domain/recipe.py`）: T337で実装自体が既に完全削除済み（呼び出し元
    ゼロを確認）。この部分はT337時点で完了済みで対応不要だった。
  - `classify_bicycle_infrastructure`（`domain/traffic.py`）: T336で内部軸
    `car_stress_bicycle_infra_adjustment`が参照する材料が正規化フラグへ置き換わった結果、
    `evaluation.py`（`axis_inspector_breakdown`・`compute_edge_axis_scores`）・
    `openrouteservice_engine.py`が評価用材料辞書へ`"bicycle_infra"`キーを計算・格納する
    処理は**どの軸からも参照されなくなった死んだコード**になっていた（削除、下記「検証」
    参照）。一方`classify_bicycle_infrastructure`の呼び出し自体は、評価軸とは無関係な
    別の消費者（`RouteSegmentDetail.bicycle_infra`区間表示・`RouteCandidate.bicycle_infra_score`
    ルート集約統計、`road_graph_engine.py`・`openrouteservice_engine.py`が直接使用）が
    現役で存在するため、**関数・呼び出し自体は削除できない**（削除すると区間表示APIが
    壊れる）。SQL CASE式とPython関数はどちらも「地図表示」ではなく「MVTタイル生成
    （SQL）」と「ルートAPI応答（Python）」という**別の実行コンテキストの別消費者**であり、
    当初想定した「地図表示ロジックの重複」という構図自体が不正確だった。
  - 実施したのは (1) 上記の死んだコード（`bicycle_infra`キーの評価用材料辞書への
    格納、3箇所）の削除、(2) この経緯と「評価軸の材料は正規化された生データに統一する」
    「地図表示用の人間向けカテゴリラベル（SQL CASE式）とAPI表示用のPython分類関数は
    それぞれ別の実行コンテキストの別消費者であり、評価軸から参照されなくなっても
    削除対象にはならない」という原則を`docs/architecture.md`（「自転車インフラ」節・
    新設「地図表示ロジックと評価軸材料の分離原則」節）へ追記、の2点のみ。
- 検証: `backend/app/domain/evaluation.py`・`backend/app/services/openrouteservice_engine.py`
  から死んだ`"bicycle_infra"`キー格納3箇所を削除（`classify_bicycle_infrastructure`の
  呼び出し自体は`openrouteservice_engine.py`の表示用途で1箇所残存、`evaluation.py`は
  呼び出しごと不要になったためimportも削除）。既存テストは軸評価の出力（axis scores・
  car_stress値）のみを検証しておりこの内部辞書キーの有無を直接assertしていないため
  修正不要、新規テストも追加していない（挙動を変えない死んだコードの削除のため）。
  `ruff check`・非DBテスト1086件全件green。
- 依存: T336・T337（Python側関数を評価パイプラインから切り離す前提作業）。

### - [x] T342. 材料正規化方針を踏まえた軸スタジオUIの見直し検討 規模S（2026-08-26完了）

- 背景: 2026-08-26の設計議論（[material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)）
  で「評価軸の材料は正規化されたフラグ・数値に統一する」方針を確立したことを受け、
  ユーザーから「軸スタジオのUIも変わると思う」との指摘。起票時点では具体的なUI変更を
  設計するには早いため、想定される影響を記録するに留めていた。
- 想定されていた影響（着手時に再検証した）:
  1. **材料選択肢の変化**: T336実施後、`cycleway_has_track`等の正規化フラグ材料が
     新たに材料カタログへ増える一方、`bicycle_infra`のような複雑なcategorical材料は
     評価軸の選択肢から外れる（表示専用へ格下げ）可能性がある。
     → **再検証結果**: 正規化フラグ4件は追加された。`bicycle_infra`は評価軸から
     参照されなくなった（T341で確認）が、`display_only`は付けていない（軸スタジオでは
     引き続き選択可能。`designation`のようにmapping前提の値が3値程度に収まらず、
     複雑なcategoricalとしてなお選択肢に残す判断自体はT342の範囲外——GUIから選べる
     ことがUI上の不整合や不具合を起こしていないため、対応不要と判断）。
  2. **「値ごとのスコアを設定」画面（categoricalテンプレート）の出番が減る**: 正規化
     フラグはboolean化されるため、「該当時/非該当時のスコア」という既存のシンプルな
     入力で足りるケースが増え、T340が解決しようとしている「値の自由入力」画面自体の
     使用頻度が下がる可能性がある。
     → **再検証結果**: 既存UI（`AxisComposer.tsx`の「カテゴリ値」テンプレート内、
     材料のdtypeでboolean/categoricalの2つの入力パターンを自動切替）は元々どちらの
     ケースも同じ画面内で自然に扱える構造だったため、使用頻度が変化するだけで
     UI変更は不要と判断した。
  3. **「複数要素の足し算」操作の重要性が増す**: 正規化材料の線形結合による近似を
     踏まえると、複数の正規化フラグ材料を選んで重みを付けて足し合わせる操作
     （`flag_sum`/`breakpoint_linear`のterms）が、より中心的な使い方になる可能性が
     あり、現行UIがこの操作をどれだけ快適にサポートできているかの再点検が必要、
     という想定だった。
     → **再検証結果（実際に不具合を発見）**: T336が実装した組み込み軸
     `car_stress_bicycle_infra_adjustment`自体が、まさに複数のboolean材料
     （`highway_is_cycleway`/`cycleway_has_track`/`cycleway_has_lane`/
     `cycleway_has_shared`）を重み付きで結合し、任意の折れ点カーブへ変換する
     `BreakpointLinearShape`の実例（backend側`evaluate_axis_scalar`は
     `value * term.weight`でboolean値をそのまま1/0として計算できる）。しかし
     `AxisComposer.tsx`の「数値の大きさに応じて点数を変える」(breakpoint_linear)
     テンプレートの材料(terms)セレクトは`dtype === "numeric"`限定のフィルタのままで、
     boolean材料が選択肢に一切現れなかった——つまり**GUIからはT336と同種の軸を
     組めない**という実害のある欠落だった（`flag_sum`は単純合計+capのみで、
     breakpoint_linearが持つ「任意の折れ点カーブへの変換」ができないため代替にならない）。
- 内容: 上記3で見つかった欠落を修正した。`AxisComposer.tsx`のbreakpoint_linear/
  recipe_then_breakpoint_linearの材料(terms)セレクトのフィルタを`dtype === "numeric"`
  から`dtype === "numeric" || dtype === "boolean"`へ拡張し（categoricalは対象外のまま
  ——文字列材料と数値の掛け算はbackend側でエラーになるため）、boolean材料を選んだ場合の
  挙動（該当時1・非該当時0として係数と掛け合わされる）を説明するヒント文を追加した。
- 検証: `AxisComposer.test.tsx`に回帰テスト1件を追加（boolean材料`surface_good`を
  breakpoint_linearの材料として選択・保存し、payloadへ反映されることを確認）。
  フロント全673件・`npm run lint`・`tsc --noEmit`green。
- 依存: T336・T339（実装が具体化してから中身を判断する、想定どおり両方の完了後に着手）。

### - [x] T343. compute_edge_costs_bulkがextractor未設定の材料を参照する軸でKeyErrorする 規模S（2026-08-26完了）

- 背景: T336〜T340・T338フォローアップの完了後、ユーザー指示で「取込済みデータが評価用に
  正規化されているか」を再点検した際に発見。`MaterialSpec.extractor=None`の材料
  （`oneway`/`designation`/T338フォローアップで追加した`is_emergency_transport`/
  `is_critical_logistics`、いずれも「種別を実際に区別する評価軸のニーズが出るまで
  配線しないトリガー付きDEFER」設計原則9）を参照する軸を、`compute_edge_costs_bulk`
  （実際のルート生成が使うベクトル化経路）が評価すると、`evaluate_axis_array`の
  `materials[term.material]`（直接インデックス）がKeyErrorになり`/api/routes/generate`
  自体が例外で落ちる状態だった。スカラー経路（`evaluate_axis_scalar`、区間インスペクタ・
  openrouteserviceエンジンが使う）は`materials.get(...)`のため発生せず、2経路間の
  非対称なバグだった。`_check_materials_are_known`（axis_admin.py）は`is_known_material`
  のみ検証しextractor有無は見ないため、軸スタジオから素朴にこの状態の軸をGUIで
  作成できてしまう。`is_emergency_transport`/`is_critical_logistics`は`display_only=False`
  で選択可能にしたばかりだったため、実際にユーザーが選ぶと即座に踏みうる状態だった
  （`oneway`/`designation`自体はT338フォローアップ以前から潜在していた既存バグ）。
- 内容: `compute_edge_costs_bulk`の材料配列確保を、抽出関数を持つ材料
  （`extractable_materials`）だけでなく`MATERIAL_CATALOG`全材料ぶんへ拡張した
  （抽出ループ自体は従来どおり抽出関数を持つ材料のみ回す）。抽出関数未配線の材料は
  「データ無し」の欠損値（NaN/`bool_default`に応じたFalse）で埋まった状態になり、
  スカラー経路と同じグレースフルデグレード（その軸だけ恒久的に評価不能、他の軸の
  合成には影響しない）になる。
- 検証: `tests/test_evaluation_bulk.py`に回帰テスト2件を追加
  （`BreakpointLinearShape`経由で`is_emergency_transport`を参照する軸、
  `CategoricalShape`経由で`designation`を参照する軸、それぞれ材料配列の初期化コード
  パスが異なるため個別に検証）。修正前のコードに戻すと両方とも実際にKeyErrorで
  失敗することを確認済み。非DBテスト1086件全件green。

### - [x] T344. CIのbackendジョブがosmium未インストールでtest_import_pbf.py/test_pbf_source.pyの収集に失敗する 規模S（2026-08-26完了）

- 背景: T336〜T343のmasterへのプッシュ後、CI（`.github/workflows/ci.yml`のbackendジョブ）が
  `ModuleNotFoundError: No module named 'osmium'`で`tests/test_import_pbf.py`・
  `tests/test_pbf_source.py`の収集自体に失敗しているとユーザーから報告を受けて発見。
  この2ファイルはPBF取込バッチ（`app/batch/import_pbf.py`・`app/batch/pbf_source.py`）
  専用のテストで、無条件に`import osmium`する。一方osmiumは`backend/requirements.txt`
  には含まれず、`backend/requirements-batch.txt`（バッチ専用の追加依存、コメントに
  「Renderのwebサービスには不要のためrequirements.txtとは分離している」と明記）側にのみ
  ある。CIのbackendジョブは`pip install -r requirements.txt`のみでosmiumを入れておらず、
  かつ`python -m pytest -q -n auto --dist loadgroup`にこの2ファイルを除外する
  `--ignore`・マーカーも無いため、常にこの2ファイルの収集に失敗する構成だった。
  調査の結果、この不整合はCIの導入自体（改善計画T1）まで遡る既存の設定漏れで、
  今回のT336〜T343のいずれの変更が原因でもない（変更したファイルにrequirements.txt・
  ci.yml・この2テストファイルは含まれない）。`test_pbf_source.py`はT331（テスト
  カバレッジ改善）で新設されたばかりで、新設時にCIで一度も実行されていなかった
  （ローカルでは`--ignore`で除外して確認する運用が定着していたため、この収集失敗に
  気づかれないまま残っていたとみられる）。
- 内容: 本番Renderデプロイに不要という`requirements.txt`/`requirements-batch.txt`の
  分離自体はデプロイ物の話であり、CIのテスト実行はデプロイ物と独立した別の関心事の
  ため、CIのbackendジョブのインストール先を`requirements-batch.txt`
  （`-r requirements.txt`を内包、+`osmium==4.1.1`）へ切り替えた（Renderへは影響しない）。
  `cache-dependency-path`も両ファイルを含めるよう更新した（osmiumのバージョンだけが
  変わった場合もキャッシュが正しく無効化されるように）。
- 検証: `uv pip install -r requirements-batch.txt`したvenvで
  `pytest tests/test_import_pbf.py tests/test_pbf_source.py -q`（30 passed, 3 skipped）・
  `pytest -q -n auto --dist loadgroup`（PostGIS統合テストを除く1116 passed, 175 skipped、
  DBが無いローカル環境のため。CIはpostgresサービスコンテナがあるため元の1258件相当が
  通る想定）を確認済み。osmiumのインストール自体はPyPIのwheelのみで完結し追加の
  システムライブラリを要さないため、CI環境（ubuntu-latest）でも同様に通る見込み。

### - [x] T345. 軸スタジオ「値ごとのスコア」操作の改善（材料説明アイコン・重みの相対比較・スコア向き修正） 規模M（2026-08-26完了）

- 背景: ユーザーからの実機フィードバック4点＋その場で見つかった追加指摘1点。
  1. 「候補から選ぶ...」セレクトが`ラベル (物理値)`（例: `分離型 (separated)`）と表示され、
     物理値の併記が不要。
  2. どの材料が何を示しているか分かりにくい。材料ごとの説明文を情報アイコン(ⓘ)から
     参照できるようにしてほしい。
  3. 既に他の軸で使用中の材料を選べなくするのが必要か検討してほしい
     → **検討の結果、実装しない**（ユーザー了承済み）。材料は複数の軸から自由に参照される
     設計が前提（例: `highway`は組み込みの`car_stress_highway_base`が使う一方、
     ユーザーが別目的の軸で同じ材料を使うのは正当なユースケース）で、制限すると
     正当な操作を塞ぐだけのため。
  4. 既定重み(default_weight)やスコアの値をどう設定するとルーティングにどう効くのか
     分からない。分かりやすい入力・表現にしてほしい。
  5. （ユーザーからの追加指摘）「前処理＝絶対値」の説明が分かりにくい。他の項目の
     日本語説明文も推敲してほしい。
- 調査で判明した事実（内容着手前にユーザーへ提示、修正の了承を得た上で着手）:
  - **折れ点(breakpoints)のヒント文が実際の向きと逆というバグを発見**: T327
    （2026-08-25）が明文化した「スコアは0(最も走りにくい)〜100(最も走りやすい)」は、
    組み込みのgradient軸の実データ（勾配0%→スコア0・15%→スコア100、
    `description="登り坂の急さが小さいほど易しい"`）と逆だった。正しくは
    「0=最も走りやすい・100=最も走りにくい」（backend全体の`difficulty`規約
    [`EdgeCostResult.difficulty`等]「0-100、大きいほど走りにくい」と一致）。
  - 前処理(preprocess)の「絶対値」を実際に使っている組み込み軸はgradientのみと判明
    （符号付きの勾配%を、上り・下りどちらでも急なほど走りにくい扱いにするための機能）。
    この実例をそのままヒント文にした。
  - 既定重みの合成（`domain/difficulty.py: composite_difficulty`）は重み付き**平均**
    （重みの合計で正規化）であり、**数値の絶対値そのものには意味が無く、他の公開軸との
    比率だけが効く**（全軸の重みを一律2倍にしても結果は不変）ことを確認。また
    `default_axis_weights()`が対象を`is_published=True`の軸のみに絞るため、内部軸
    （`is_published=False`、既定重みは全件0.0固定）の既定重みはそもそも合成に使われない。
- 内容:
  1. 候補セレクトの表示を論理名(ラベル)のみへ簡略化（`AxisComposer.tsx`、保存される
     値(value)自体は変更なし）。
  2. `MaterialSpec`（`domain/material_catalog.py`）へ`description: str`フィールドを追加し
     全26材料に説明文を記入（`extractor=None`の材料[`oneway`/`is_emergency_transport`/
     `is_critical_logistics`]は「現時点では評価軸の材料として配線されておらず選んでも
     常に「データなし」」である旨を明記）。`GET /api/material-catalog`のレスポンスへ含め、
     `AxisComposer.tsx`に材料選択の隣へ情報アイコン(ⓘ)を新設（`MaterialInfoButton`、
     `recipeControls.tsx: FieldLabel`と同じPopover/InfoIconパターンを流用）し、選択中の
     材料の説明文を表示する。「必須」チェックボックスにも同様の情報アイコンを追加。
  3. （実装しない、上記参照）
  4. 既定重みのヒント文を「他の軸の重みとの比率で効く（絶対値に意味はない）」旨へ修正し、
     `otherAxes`（`AxisStudio.tsx`が保持する全軸一覧、新規props）を渡された場合に
     「公開軸全体の重み合計に対して約◯%」を参考表示する`renderWeightShare()`を追加
     （非公開のままの軸では「重みは直接使われない」旨の注記に切り替える）。
  5. 折れ点のヒント文の向きを訂正（バグ修正）。前処理(preprocess)にgradient軸を実例とした
     ヒント文を新設。「値ごとのスコア」「該当時/非該当時のスコア」「フラグ(flags)の加点」
     にも同じ0-100の向きの説明を追加（flags欄は合計・上限(cap)・マイナス値の扱いも補足）。
- 検証: backend `tests/test_material_catalog.py`（全材料が空でない説明文を持つことを
  検証する回帰テスト追加）・`tests/test_material_catalog_routes.py`（レスポンスの
  descriptionがMATERIAL_CATALOGと一致することを検証）を含め非DBテスト1088件全件green。
  `export_openapi.py`→`npm run generate:api`実行、生成物の差分はdescriptionフィールド
  追加のみでドリフト無し。frontend: 情報アイコンの説明表示・材料切替時の説明文更新・
  必須チェックボックスの説明・既定重みの相対比較（公開/非公開それぞれ）・候補セレクトの
  論理名のみ表示、それぞれの回帰テストを`AxisComposer.test.tsx`・
  `AxisComposer.materialValues.test.tsx`へ追加。折れ点ヒント文の向き修正に伴い
  `AxisStudio.test.tsx`の既存アサーションも正しい向きへ更新。全680件・lint・tsc green。
- 副次的対応: CIのGitHub Actionsが「Node.js 20 is deprecated」警告を出していたのを
  ユーザーが発見（`actions/checkout@v4`・`actions/setup-node@v4`・`actions/setup-python@v5`
  がNode 20をターゲットにしたままNode 24へ強制フォールバックされていた）。挙動を変えない
  バージョン上げ（`@v5`/`@v5`/`@v6`、いずれもNode 24ネイティブ対応）で解消した。続けて
  e2eジョブでも`actions/cache@v4`が同じ警告を出しているとユーザーが発見（当初の警告一覧に
  含まれておらず見落としていた）、`@v5`へ追従した（`actions/upload-artifact@v4`は本稿時点で
  未報告のため据え置き）。
- フォローアップ（2026-08-26、Render実機のスクリーンショットでユーザーが発見）:
  1. **情報アイコンの配置崩れ**: 「カテゴリ値」テンプレートの材料(material)セレクト直後に
     置いた`MaterialInfoButton`が、`.field`（column方向flex）の兄弟要素として単純に並んで
     いたため独立した行にセンター寄せで表示されてしまっていた（breakpoint_linearの
     材料(terms)行・flag_sumのフラグ行は元々`.termRow`という横方向flexコンテナ内だったため
     この問題が起きなかった）。ラベル+セレクトと情報アイコンを`.row`（横方向flex）で
     括って解消した。
  2. **「値」欄に生のOSMタグ値（例: `cycleway`）がそのまま表示され分かりにくい**という
     実機フィードバック。候補（`GET /api/material-catalog/{id}/values`）から選んだ値は
     `lib/materialValueLabels.ts`経由で日本語ラベルへ変換できるにもかかわらず、値入力欄
     自体は生のタグ値を表示する`<input>`のままだった。
     - 初版対応: ラベルが引ける行は読み取り専用のラベル表示にし、「直接入力する」
       ボタンで生のタグ値の編集欄へ戻せるようにした。
     - **ユーザー指摘による見直し**: 「生の値を直接編集する必要のあるシーンは基本無い
       はず（material_catalogに無い値をわざわざ書くことはない）。候補セレクトと値欄の
       2つだけで十分では」という指摘を受け、初版の「直接入力する」エスケープハッチ
       自体が不要と判断し撤去した。T340時点の「DBにまだ反映されていない新しいタグ値を
       先回りして設定したいケースを塞がない」という当初の設計意図は、実際の運用実態
       （軸スタジオ利用者はmaterial_catalogに実在する値しか設定しない）とは合致して
       いなかった——タイプミスがそのまま「静かに一致しない行」として残る落とし穴の方が
       実害として大きいと判断した。動的値一覧（`categoricalMaterialValues`）が存在する
       材料は候補セレクトでの選択のみを許可し、値欄は`readOnly`のinput（ラベルを表示、
       globals.cssの`input[type="text"]`共通スタイルをそのまま流用）にした。動的値一覧に
       対応しない材料（`bicycle_infra`等、選ぶ元の候補自体が存在しない）だけ、従来どおり
       自由テキスト入力のままにする。保存されるvalue自体は引き続き生のタグ値。
  検証: `AxisComposer.materialValues.test.tsx`の該当テストを最終UX（候補選択後は
  readOnly inputにラベル表示、直接入力の撤去）に合わせて更新。フロント全680件・lint・tsc
  green。
  - **さらなるフォローアップ（同日、実機のスクリーンショットで発覚した2件＋ユーザー指摘）**:
    1. highwayの候補セレクトで「自転車・歩行者道」「幹線道路」等が複数個ずつ並び
       見分けが付かなくなっている実機不具合を発見。原因は、値ごとのラベルを
       `roadFilterAxes.ts`のHIGHWAY_GROUPS/SURFACE_GROUPS（地図の色分け専用、意図的に
       多対一——例: motorway/trunk/primary等6値が同じ「幹線道路」）から流用していたため
       （T340時点の「UI語彙のカタログ集約」判断）。ユーザー指摘「地図表示と評価は別。
       そのルールで統一して」を受け、地図の色分けグルーピングとは独立した1値1ラベルの
       専用対訳表へ差し替えた。
    2. 「1値1ラベルの対訳表はOSM wikiのDescription等から取れないか」という提案を受け
       OSM wiki（Key:highway/Key:surface）の直接取得を試みたが、`wiki.openstreetmap.org`
       はネットワークegressポリシーでブロックされておりWebFetch・archive.orgミラー経由
       とも失敗した。WebSearchの断片的なスニペット（例: motorwayの正式説明「高速の
       自動車交通が安全に走行できるように設計された高規格幹線道路」）で大枠の妥当性のみ
       確認し、OSMタグの一般的な定義に基づく独自の1値1ラベル対訳表（例:
       residential→「住宅街の道路」、motorway→「高速道路」）で運用する。
    3. 続けて「1値1ラベルの対訳表はmaterial_catalog側にまとめて持てないか」という提案を
       受け、「材料の属性値はまとめて持ちたい、地図表現は別で構わない」という設計方針を
       確認した上で、この対訳表をfrontend（`lib/materialValueLabels.ts`、撤去した）から
       backend `domain/material_catalog.py: MaterialSpec.value_labels`（材料定義自体の
       一部）へ全面移設した。`GET /api/material-catalog/{material_id}/values`の
       レスポンス形状を`values: string[]`から`values: {value, label}[]`へ変更し、
       ラベル付与自体をbackendが担う（frontendは受け取った値をそのまま表示するだけ）。
       material_id文字列をキーにした材料をまたぐ別辞書（同期漏れリスクのある並列構造、
       T180・T185・T218のOpenAPIドリフト等と同型）にはせず、`MaterialSpec`自身の
       フィールドとして材料定義1件の中に閉じ込めた。
    4. 併せて、「候補から選ぶ」への一本化後に残った読み取り専用の値欄が、見た目上は
       編集可能なinputと区別が付きにくいという指摘を受け、`:read-only`疑似クラスで
       背景・文字色をグレーへ落とすCSSを追加した。
  検証: backend（`MaterialSpec.value_labels`の重複無しテスト・フォールバックテスト追加）
  非DBテスト1090件、`export_openapi.py`→`npm run generate:api`実行しドリフト無しを確認。
  frontend（`useMaterialValues`のテストを新レスポンス形状へ更新、`lib/materialValueLabels.ts`
  とそのテストは撤去）全676件・lint・tsc green。
  - **さらなるフォローアップ2（同日、ユーザー指摘）**: 値ラベル・材料ラベルとも
    「論理名 - 物理名」形式（例: 値「自転車専用道 - cycleway」、材料「道路種別 -
    highway」）へ統一してほしいという指摘。論理名だけでは対応するOSMタグ値・材料id
    (material_id)が分からず、軸定義やドキュメント上で物理名を探す必要があった実運用上の
    不便への対応。
    - `MaterialSpec.value_label(value)`（`domain/material_catalog.py`）を、対訳表に
      論理名があれば`f"{label} - {value}"`を返すよう変更（対訳表に無い値は従来どおり
      物理名のみ、フォールバック）。
    - 材料名側にも同じ発想で`MaterialSpec.full_label()`を新設（`f"{self.label} -
      {self.material_id}"`）し、`GET /api/material-catalog`の`label`フィールドが
      これを返すようにした（`api/routers/material_catalog.py: get_material_catalog`）。
    - frontendの静的フォールバック（`lib/axisMaterialsCatalog.ts: AXIS_MATERIAL_OPTIONS`）
      も同じ形式へ手動で揃えた（動的取得失敗時のみ使われるため自動追従はしないが、
      表示形式は一致させておく）。`AxisComposer.tsx`・`useMaterialValues.ts`側は
      backendが返す文字列をそのまま表示するだけのため、コード変更は不要だった。
    - レスポンスのフィールド型（`str`）自体は変わらないため`export_openapi.py`実行後も
      OpenAPI生成物に差分無し（文字列の中身が変わるだけで、型定義には影響しない）。
    検証: backend `test_value_label_falls_back_to_the_raw_value_for_unknown_values`・
    新設`test_full_label_combines_label_and_material_id`、
    `test_material_catalog_routes.py`の該当アサーションを新形式へ更新。非DBテスト
    1085件（＋2件）green、`export_openapi.py`実行しドリフト無しを確認。frontend:
    `AxisComposer.materialValues.test.tsx`・`AxisComposer.test.tsx`・
    `AxisStudio.test.tsx`の該当アサーション（候補セレクトの選択肢名・情報アイコンの
    aria-label・材料選択肢名）を新形式へ更新（候補セレクトが物理値を併記しないことを
    確認していた回帰テストは、新形式で併記することを確認するテストへ書き換えた）。
    全676件・lint・tsc green。

第17版以降、**T263残作業（Render backendの停止）が完了した**。並行稼働期間は当初想定の
1日間より短い約1時間強だったが、ユーザー判断により前倒しで停止を実施。その過程で、
Render固有の自動注入環境変数`RENDER_GIT_COMMIT`に依存していたデプロイ確認機構
（`/health`のcommit）がbackend側だけ恒久的に`null`化する回帰を発見し、
`GIT_COMMIT`（deploy-backend.ymlが`git rev-parse HEAD`で明示注入）へ切り替えて修正した
（T263本文「残作業」参照）。指示待ちだった項目が無くなったため、指示待ちリストは
現在空。

**第18版への追記（2026-08-24・目論見書承認）**: 二画面構想の目論見書がユーザー承認され、
T266に加えT267〜T273の7タスクを正式起票した（上記「目論見書による二画面構想の正式化」
セクション参照）。着手順序はPhase順（T266→T267がPhase 1、T268・T269→T270がPhase 2、
T271・T272がPhase 3、T273がPhase 4=トリガー待ち）。**同日中にPhase 1（T266・T267）に続き
Phase 2の前提2件（T268・T269）も実装・完了した**。T268: 材料の排他帰属チェックを
`registry.py`から計算系レジストリ（`AXIS_DEFINITIONS`）へ移植。T269: 軸カタログを
`GET /api/axis-catalog`（新規公開API、`AxisDefinition`へlabel/description/category追加、
migration 0015）経由でDBの内容に追従させ、`RouteSettingsPanel`を静的`axis-catalog.json`
依存から切り離した（調査の結果、当初想定と異なり`axis-catalog.json`は`registry.py`
（DB化されていない別レジストリ）由来と判明し、方針を修正した経緯は実装メモ参照）。
backend全1149件・フロントtsc/vitest 516件green、実機確認済み。
**残るPhase 2はT270（軸スタジオ本体、独立URL管理画面）のみ**。

**第18版への追記2（2026-08-24）**: 同日中にPhase 2〜4が以下のとおり進んだ。
Phase 2: T270（軸スタジオ本体）完了、続けてT276（registry.py↔AXIS_DEFINITIONS
ラベル統合）・T277（材料カタログのbackend正式レジストリ化）・T278（地図表示ルール
kind=rampの自動導出、軸集合の同期）を追加着手・完了した——**T278でnight軸が
自動導出のrampレイヤーを持つようになったため、下記「トリガー未到達」リストの
T145a（night軸レイヤー、litタグデータの充実待ち）は解消済み**。Phase 3:
T271（軸の公開フローと統治ルール、is_published導入）・T272（管理画面の権限制御、
HTTP Basic認証）を完了し、**目論見書の二画面構想はPhase 1〜3すべて完了**。
残るはPhase 4のT273（一般UIの軸カタログ縮退、トリガー待ちの継続タスク）のみ。
副次的にT275（Tailwind CSSの要否判断）も起票済み（未着手）。

**第18版への追記3（2026-08-24・全体最適レビュー第8回の起票）**: 全ソースコード・DB設計を
ゼロから再読した総合診断レビュー（対象`fc7bd5a`、総合83/100、詳細は
`.claude/commands/review/history/2026-08-24_overall.md`）の指摘をT279〜T288の10件として
起票した（上記「全体最適レビュー第8回の起票」セクション参照）。即時実施可能なのは
**T279（P1・OpenAPIドリフト解消、唯一の実害ある欠陥）**・T281段階1（依存DAG文書化、S）・
T282（ファサード再検討の判断記録、S）の3件で、着手順はT279を最優先とする。
T280（材料供給の1本道短縮）はレビューの最重要提言であり、**次に軸・材料関連の要望が
出た際は軸スタジオのUI拡張より先に実施する**という順序制約ごと記録した。

**第18版への追記4（2026-08-25・全体最適レビュー第9回の起票）**: 全ソースコード・DB設計を
一から再読した総合診断レビュー（対象`8cea9ee`、総合86/100〔前回83から+3〕、詳細は
`.claude/commands/review/history/2026-08-25_overall.md`）の指摘をT295〜T298の4件として
起票した（上記「全体最適レビュー第9回の起票」セクション参照）。前回P1（OpenAPI
ドリフト）はpre-commitフックで再発ゼロ、前回最重要提言（材料供給への投資）はT290・
T292で消化された。今回の最重要指摘は**T295（P2・軸定義DB読み込みの整合検証）**——
レビュー期間中に実際に発生したT294（本番DB migration未適用、4回目の同クラス障害）の
恒久対策が宙に浮いていることを受けたもの。T296〜T298はP3・規模Sの軽微な指摘。

- **参考記録（対応は不要〜任意、監視のみ）**:
  - T241で見つかった一部方位での「経路が見つからない」事象（8方位中平均1〜2方位）は
    残存するが、実運用への影響は限定的と評価済み（T241本文参照）。

- **トリガー未到達（現時点では着手しない）**:
  1. **T265**（冷パスの体験設計: バックグラウンドウォームアップ・事前split・進捗表示、
     規模M〜L）: T248から切り出し。一般公開の意思決定、または研究利用での冷パス体感
     遅延に関する具体的な要望・報告で着手。T259の「完全な失敗」自体は解消済みのため、
     T248時点にあった緊急性は無い。
  2. **T206**（積雪・凍結、規模S〜M）: 冬季前=11月。季節トリガーの到達が最も近い。
  3. ~~T145a（night軸レイヤー、規模S〜M）: litタグデータの充実待ち~~ →
     **2026-08-24、T278で解消**。night軸は材料（no_lit/has_tunnel）がタイル焼き込み
     済みのため、litタグの疎密に関わらず自動導出のrampレイヤーとして表示できるように
     なった（litタグデータ自体の充実は引き続き別問題として残るが、レイヤーの有無を
     それに依存させる必要が無くなった）。
  4. **T105**（バックエンド到達不能の原因特定、規模S〜M）: 次回の再現報告待ち。
  5. **T127**（全国データ取込の検証、規模不明）: 全国展開の意思決定待ち。
  6. **T145**（レイヤーパネルのレジストリ駆動化・三次レイヤー、規模L）: 裁量待ち。
  7. **T207**（CAPE延長予報、規模S）: 利用実績・要望待ち。
  8. **T208**（視程・霧調査、規模S）: 利用報告待ち。
  9. **T242残課題**（標高バックフィルの定期自動実行、規模S〜M・要スケジューリング基盤新設）:
     新規split頻度の増加、または標高データ欠損に起因する体感的な品質劣化の報告で着手。
     T281段階3（鮮度台帳）と関連するため着手時に統合を検討。
  10. **T280**（材料供給の1本道短縮、規模M〜L）: 次の軸・材料関連の実装要望で着手
      （軸スタジオUI拡張より先、という順序制約付き）。
  11. **T281段階2〜3**（統合エントリポイントバッチ・鮮度台帳、規模M）: 段階2は次回の
      データ投入・エリア拡大作業時、段階3は同クラス障害の再発またはT127。
  12. **T283**（`road_graph_use_repository`の名称・既定値再考、規模S）: 次のconfig.py
      変更のついで、または新環境構築時。
  13. **T284**（page.tsx分割方針の事前確認、規模S・判断のみ）: 次のUI機能着手前。
      実測1,773行/閾値1,900・state 36件/閾値40で発火目前。
  14. **T285**（表示系レジストリ縮退・軸カタログのランタイム一本化、規模M〜L）:
      T280完了後、またはGUI作成軸の地図表示要望。
  15. **T286**（architecture.md経緯追い出し第2弾、規模M）: 次の大きな設計転換時、
      またはユーザーの整理指示。
  16. **T287**（text型PKの再評価、規模S・調査のみ）: T127の意思決定時に容量試算へ含める。
  17. **T288**（AXIS_DEFINITIONSのマルチワーカー対応、規模S〜M）: 複数ワーカー構成の
      採用時（複数ワーカー化タスクの完了条件に含めること）。
いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

**サマリ（第8回レビュー起票後・19タスク）**: **T279・T289・T274・T281段階1・T282・T294・
T293・T299・T275は完了**（T289は当初T280の実証候補として着手したが、調査の結果MATERIAL_CATALOG対象外の
一次属性追加パターンと判明し独立タスクとして完了、T280自体はトリガー待ちのまま。
T274は並行セッションのT266〜T273・別セッションのT292フロント作業のいずれとも
競合しないbackend専用タスクであることを確認した上で着手・完了した。T281段階1・T282は
2026-08-25、いずれもフロント作業と競合しないdocs専用タスクとして完了した。T294は
同日、T292マージ後の本番動作確認の過程で発見した本番DB migration未適用（0017・0018）を
適用・backend再起動まで完了した。T293は同日、T292フロント移行完了でトリガー解消後、
矢印シンボルレイヤーを実装しPlaywright実機確認まで完了した。**T295〜T298（全体最適
レビュー第9回の起票4件）も同日中に全件完了**——T295は軸定義DB読み込みの未知参照検証・
axis_id差分ログ追加、T296は軸id⇔材料idの名前空間衝突ガード追加、T297はcar_stress
ランプ表示のmapping未登録highwayを不明扱いへ修正（dev DB実データ4,148件で事象を確認）、
T298はT292削除物を参照する残骸コメントの訂正・`kind="bespoke"`削除。ただし
T298の`recipe_then_breakpoint_linear`については、実装時に既存コメントを精読した結果
「目論見書の歯止め③に紐づく意図的なKEEP」と判明し、起票時の想定（削除または削除条件
明文化）から方針転換して現状維持とした）。**T299（Tailwind CSS + Radix UI +
components/ui/デザイン基盤の新設）も同日完了**——重複が実証された7箇所（カード状
コンテナ2・純レイアウト3・送信ボタン1・CSS Modulesファイル丸ごと削除1）を実際に移行し、
保留中だった**T275（Tailwind採否）も(b)採用で決着**した。これによりT300
（開発者タブ廃止＋ルート詳細タブの設定/結果2分割）のトリガーが解消し、同日中に
**T300・T303も完了**——モバイル下部タブを「ルート設定」「ルート結果」「地図の見え方」の
3つへ再構成し、`conditionsDirty`をルート結果タブのバッジで示すようにした。T303
（route_preferenceキー整合チェックの生成リクエスト側追加）はT300と同時に対応し、
`RouteSettingsPanel.tsx`と共有する純粋関数`syncRoutePreferenceKeys`へ抽出した。
トリガー未到達15件（T265・T206・T105・T127・T145・T207・T208・T242残課題・
T280・T281段階2〜3・T283〜T288。T145aはT278で解消済みのため除外）／
このほかT273（Phase 4蒸留、トリガー未到達）のみが着手待ち。
T209・T223・T241は調査完了・T242本体（migration 0013適用・
標高バックフィル初回実行）・T243〜T249・T251〜T254・T256〜T259・T261〜T264・
**T248・T263（残作業含む）**は実装/調査完了・T255はDynamicLayerTimeSlider完了
（ホイール操作は実機確認済み）・BottomSheetは断念で完了扱い・T229はT248へ統合クローズ・
T221はPart 3（Stage D）まで実装完了（Stage Eは別タスクとして起票予定）のため、いずれも
本リストから外した。安全網の回復3件（T225・T224・T230）とレビュー指摘の消化5件
（T226〜T228・T231・T232）、およびT222（Overpassライブ経路削除）は全て完了済み。
T258で追加したデバッグログはT105の次回再現時の切り分け材料になる想定だが、T105自体は
トリガー未到達のまま残る。T259（20km失敗の根本原因特定）は調査として完了し、その結果は
T261の本番クラッシュ調査・T263（Oracle VM移行）という一連の対応につながった。
**T248候補1（バルクUPSERTのCOPY化）は一時的に切り戻したが、原因ではないと確定したため
`git revert`のrevertで再導入し、現在も本番で稼働中（詳細はT248候補1・T263参照）**。
**T248は2026-08-24に完了し、未着手のまま残っていた冷パスの体験設計（バックグラウンド
ウォームアップ等）はT265へ切り出してトリガー未到達リストへ移した。T263は同日、
Render backendの停止とデプロイ確認機構の修正をもって残作業を含め完了した。**

## T317: 動的グループを「地図の見え方」パネルから撤去し、説明文を地図上チップへ移設（完了・2026-08-25）

**番号重複についての注記**: 本タスクと並行して別セッション（`claude/jiku-studio-500-error-bvnrvd`
ブランチ）が進めていた作業でも、独立に「T317」という番号が別内容
（`### - [x] T317. night軸非公開時にRoutePreference.with_weightがValidationErrorになる
不具合の恒久対策` 、本ファイル内の別見出し形式・別セクションを参照）に採番されていた
（master統合時の衝突リスクとして事前に把握していたが、見出し形式・挿入位置が異なった
ためgit mergeの機械的な衝突にはならなかった）。両タスクは無関係な別内容であり、
本節が指すのは本文中の実装内容（動的グループのパネル撤去）のみ。

ユーザー指摘「地図上チップの凡例（無風・微風…）と『地図の見え方』パネルの中身が同期
されない、凡例に合わせてパネル内でon/off切り替えたい」から検討開始。調査の結果、
動的グループ（降水ナウキャスト・風・雷・竜巻）は観測グループと異なり、凡例の帯単位で
表示/非表示を切り替える絞り込み機能自体を持たないと判明した（降水の直近60分・雷・竜巻は
気象庁配信の完成画像のみで生データがフロントに来ないため技術的に困難、風のみ
`speed`プロパティを持つ自前GeoJSONのため限定的に可能）。

ユーザー判断: 風だけ限定実装する対応はせず「仕様を統一」し、動的グループは絞り込み
機能を持たないものとして確定。絞り込み機能が無い以上「地図の見え方」パネルに行を
出す意味が無い（ON/OFFは地図上チップで完結する）ため、パネルから動的グループの
見出し・4行を丸ごと撤去した。各行が持っていた説明文（`panelHint`、雷ナウキャストの
「活動度2以上は直ちに避難」等の安全上の注意を含む）は失わせず、地図上チップの▶パネル
（`MapOverlayControls.tsx`）へ移設した。

実装:
- `MapLayersPanel.tsx`: `MAP_LAYER_DATA_NATURE_ORDER`ループで`dataNature === "dynamic"`
  なら即`null`を返し、動的グループの見出し・行を丸ごと非表示に。到達不能になった
  `renderSectionBody`の`precipitationNowcast`/`windVector`専用caseを削除。
- `page.tsx`: `OverlayLayerChip`に新フィールド`hint`を追加し、動的グループ4レイヤーに
  限り`layer.panelHint`を渡す（他レイヤーはサイドバーに説明文が残るため`undefined`の
  まま、重複表示を避ける）。チップの`title`も動的グループでは「[設定はサイドバー]」を
  付けないよう修正（サイドバーに設定行が無くなったため）。
- `MapOverlayControls.tsx`: `OverlayLayerChip.hint`を追加し、`renderRawMemberTile`の
  ▶パネルで凡例（`legendDetails`）の下に説明文を続けて表示するよう拡張
  （実機フィードバックで「凡例が先、説明文は後」の順に確定）。折りたたみ中の
  「表示する項目を選ぶ」設定パネル（`renderVisibilitySettings`）にも、グループ展開
  まで説明文に辿り着けないという実機フィードバックを受け、各項目に個別の（！）
  トグルを追加し、パネルを開いたまま各メンバーの説明文を確認できるようにした。

検証: frontend tsc/eslint/vitest 504 passed（新規回帰テスト3件追加）。Playwrightで
実機確認——「地図の見え方」パネルに「動的データ」見出し・4行が一切出ないこと、
地図上チップの▶パネルで凡例と説明文が両方（凡例が先）読めること、折りたたみ中の
設定パネルからも各メンバーの（！）で説明文（雷の安全注意を含む）が確認できることを
スクリーンショットで確認した。

**T317追記（同日）**: 地図上チップへの説明文表示（▶パネル本体・折りたたみ中の設定
パネルの入れ子（！）の両方）は、ユーザー判断「▶内に移動した説明文は消して」により
撤去した。動的グループの行を「地図の見え方」パネルから撤去する対応（本体）自体は
変更せず、凡例（legendDetails）のみを表示する元の挙動へ戻した
（`OverlayLayerChip.hint`フィールド・`renderVisibilitySettings`の入れ子トグル機構を削除）。
frontend tsc/eslint/vitest 502 passed。

## T318: 軸スタジオに「地図上にアイコン表示」ON/OFFを追加し、proxy_hintを撤去（完了・2026-08-25）

**番号重複についての注記**: 本タスクと並行して別セッション（`claude/jiku-studio-500-error-bvnrvd`
ブランチ）が独立に「T318」という番号を別内容
（`### - [ ] T318. 起点(35.75,139.74)でdistance_km=25/30が候補0件になる` 、本ファイル内の
別見出し形式・別セクションを参照、そのセッションはさらにT319・T320も採番して既存7軸
ハードコーディングの全面撤去を実施済み）に採番していた。見出し形式・挿入位置が異なった
ためgit mergeの機械的な衝突にはならなかったが、両タスクは無関係な別内容である。本節が
指すのは本文中の実装内容（`show_map_icon`追加・`proxy_hint`撤去）のみ。

軸スタジオ（AxisComposer.tsx）で作成する軸は、専用の地図レイヤーを持つか持たないかに
関わらず、公開されている限り常に地図上チップ・「地図の見え方」パネルの両方に何らかの形
（interactive tileまたは無効化されたグレーの案内タイル）で表示される。専用レイヤーを
持たない軸向けの「代役案内文（`proxy_hint`）」がその無効化タイルの説明に使われていた。

ユーザー判断: 軸スタジオ側で「この軸のアイコンを地図上に表示するかどうか」を明示的に
ON/OFFできる新フィールド`show_map_icon`（既定true）を追加し、OFFにした軸は地図上
チップ・サイドバーの両方から丸ごと除外する。これに伴い`proxy_hint`（DBカラム・
Pydanticモデル2箇所・OpenAPI生成物・フロントエンド6箇所に及ぶフルスタックのフィールド）
を撤去した。併せてAxisComposer.tsxのフォーム見出しに残っていた開発用のタスク番号表記
「(任意、改善計画T310)」もユーザー向け画面から削除した。

実装:
- backend: `migrations/0020_axis_definitions_show_map_icon.sql`（`show_map_icon BOOLEAN
  NOT NULL DEFAULT true`追加＋`proxy_hint` DROP、既存行はbackfill不要）。
  `domain/axis_definitions.py`（`AxisDefinition`）・`api/routers/axis_admin.py`
  （`AxisDefinitionFields`）・`api/routers/axis_catalog.py`（`AxisCatalogEntry`、
  必須の真偽値フィールドとして追加）・`infrastructure/axis_definition_models.py`/
  `axis_definition_repository.py`・`scripts/export_openapi.py`の6箇所を機械的に置き換え。
- frontend: `secondaryAxes.ts: secondaryAxesFromCatalogAxes()`のフィルタへ
  `axis.show_map_icon !== false`を1行追加するだけで、地図上チップ
  （`MapOverlayControls.tsx`）・「地図の見え方」パネル（`MapLayersPanel.tsx`）の両方から
  対象軸が除外される（`display.kind`のramp/none別分岐は不要）。`renderAxisTile()`の
  `!member`分岐・`renderProxyAxisSection()`から`proxyHint`表示を削除し、後者は見出し
  （h3）のみへ簡略化（`renderHintToggle`自体が唯一の呼び出し元を失ったため削除）。
  `AxisComposer.tsx`は`proxy_hint`のtextareaを`Checkbox`（`isPublished`と同じ部品）へ
  置き換え、グループ見出しから「、改善計画T310」を削除。
- ドキュメント: `docs/architecture.md`のT310節を`show_map_icon`へ更新し、T318の追加節を
  末尾に置いた。

検証: backend pytest 984 passed / 154 skipped（`show_map_icon` true/false双方のround-trip
テストを含む）。frontend tsc/eslint/vitest 505 passed（`secondaryAxesFromCatalogAxes`の
除外テスト2件・`AxisStudio`のチェックボックス＋T310文字列不在テスト1件を新規追加）。
OpenAPI/静的axis-catalog.json再生成後のdiffもクリーン。本番DB migration（0020）は
コード側の検証が完了した段階のため、適用タイミングは別途ユーザーへ確認する
（無断で本番へは適用しない）。

---

完了タスクの日付別一覧は[docs/improvement-plan-archive/README.md](improvement-plan-archive/README.md)を参照
（2026-08-23棚卸で完了タスクの実施記録は全件アーカイブへ移設済み。本体はオープンタスクのみ）。
