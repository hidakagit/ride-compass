"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { searchPlaces } from "@/features/route/placeSearchApi";
import { getQueryClient } from "@/lib/queryClient";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates } from "@/types/route";

// 打ちかけで引き始める長さ（空白を除いた文字数）と、打つのが止まってから引くまでの間。口の回数制限はこの間から決まる。
export const PREDICTION_MIN_LENGTH = routeGenerateConfig.place_prediction_min_length;
const PREDICTION_DELAY_MS = routeGenerateConfig.place_prediction_delay_seconds * 1000;

/**
 * 住所か施設の名前を打つ欄の中身と、地点の検索の口の引き方。打ちかけでも打つのが止まってから引き、かな漢字の変換中は引かない。
 * 引くときに地図の真ん中を添える。
 */
export function usePlaceLookup(mapCenter: Coordinates) {
  const [text, setText] = useState("");
  // 引いた文字列と、引いたときの地図の真ん中。打つのが止まってから引く（打つたびに引くと口の回数制限に当たる）。
  // 引いたあとに地図を動かしても引き直さない（選んでいる最中に並びと距離が変わらない）。
  const [query, setQuery] = useState("");
  const [near, setNear] = useState(mapCenter);
  const lookUpTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const search = useQuery(
    {
      queryKey: ["place-search", query, near.latitude, near.longitude],
      queryFn: () => searchPlaces(query, near),
      enabled: query !== "",
      // 打ちかけで引き直す間も、前の候補を出しておく（一覧が「探しています…」と入れ替わってちらつかない）。
      placeholderData: keepPreviousData,
    },
    getQueryClient(),
  );

  useEffect(() => () => clearTimeout(lookUpTimer.current), []);

  function lookUp(trimmed: string) {
    setQuery(trimmed);
    setNear(mapCenter);
  }

  // かな漢字の変換中は呼ばない（変換を確定したときに呼ぶ）。引き始める長さに足りない文字なら、前の候補を下げる（候補が打った
  // 文字に合わないまま残らない）。
  function scheduleLookUp(value: string) {
    clearTimeout(lookUpTimer.current);
    if (value.replace(/\s/g, "").length < PREDICTION_MIN_LENGTH) {
      setQuery("");
      return;
    }
    const trimmed = value.trim();
    lookUpTimer.current = setTimeout(() => lookUp(trimmed), PREDICTION_DELAY_MS);
  }

  return {
    query,
    near,
    search,
    /** 欄へ渡す値と打つ操作。 */
    inputProps() {
      return {
        value: text,
        onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
          setText(event.target.value);
          if (!(event.nativeEvent as InputEvent).isComposing) scheduleLookUp(event.target.value);
        },
        onCompositionEnd: (event: React.CompositionEvent<HTMLInputElement>) =>
          scheduleLookUp(event.currentTarget.value),
      };
    },
    /** 打った文字ですぐ引く（Enter・「検索」）。同じ文字・同じ真ん中なら引き直す。 */
    submit() {
      clearTimeout(lookUpTimer.current);
      const trimmed = text.trim();
      if (trimmed === "") return;
      lookUp(trimmed);
      if (trimmed === query && near === mapCenter) void search.refetch();
    },
    /** 引いた候補を下げる。`clearText`なら打った文字も消す。 */
    close({ clearText = false } = {}) {
      clearTimeout(lookUpTimer.current);
      setQuery("");
      if (clearText) setText("");
    },
  };
}
