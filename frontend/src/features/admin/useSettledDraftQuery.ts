"use client";

// 軸スタジオの下書きから組んだ問い合わせを、入力が落ち着いてから投げ、今の入力に対する答えだけを返す。
// 判定・計算はbackendが持ち、画面は下書きを送って結果を出すだけの問い合わせ（点数の試算・地図の段の判定等）が使う。

import { useQuery } from "@tanstack/react-query";

import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { getQueryClient } from "@/lib/queryClient";

/** `request`がnullの間は問い合わせない。入力を変えた直後（落ち着く前）・届く前・取得に失敗したときは`undefined`
 * ——前の入力に対する答えを、今の入力のものとして出さない。`name`は問い合わせの種類（取得の共有の鍵の頭）。 */
export function useSettledDraftQuery<Request, Response>(
  name: string,
  request: Request | null,
  fetcher: (request: Request) => Promise<Response>,
): Response | undefined {
  const key = request === null ? "" : JSON.stringify(request);
  const debouncedKey = useDebouncedValue(key, MAP_FETCH_DEBOUNCE_MS);
  const { data } = useQuery(
    {
      queryKey: [name, debouncedKey],
      queryFn: () => fetcher(JSON.parse(debouncedKey) as Request),
      enabled: debouncedKey !== "",
    },
    getQueryClient(),
  );
  return debouncedKey === key ? data : undefined;
}
