"""外部HTTPの代役。応答はrespxの経路（`respx.Router`）で決め、実装へは本物の`httpx.AsyncClient`を渡す。

経路は`httpx.MockTransport`へ差すので網へは出ず、既定の送り先（証明書の読み込みを伴い、
1つ作るのに開発機で0.5秒かかる）も作らない。応答は本物の`httpx.Response`なので、
`raise_for_status`・`json`・`text`・ヘッダの読み方は実装と同じものを通る。経路に無いURLを
引くとrespxが落とす（引くはずの無いURLを黙って通さない）。

要求を見るときは経路の記録（`router.calls`・`route.calls`）を読む。クエリはURLに載った形
（`request.url.params`、値は文字列）で見る。

クライアントを受け取らず、自分で`httpx.stream`等を呼ぶ実装は、pytestのフィクスチャ`respx_mock`で差す。
そのときも、実装の中で作られる`httpx.Client`を1テストで何度も作らせない。
"""

import httpx
import respx


def client_for(router: respx.Router) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(router.handler))


def answering(*args, **kwargs) -> httpx.AsyncClient:
    """どのURLへも同じ応答を返すクライアント。引数は`respx.Route.respond`のもの（例: `json=...`・`text=...`・`500`）。"""
    router = respx.Router()
    router.route().respond(*args, **kwargs)
    return client_for(router)
