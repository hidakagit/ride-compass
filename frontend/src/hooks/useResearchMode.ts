"use client";

import { useSyncExternalStore } from "react";
import { isResearchEnabled, subscribeResearchMode } from "@/lib/researchMode";

export function useResearchEnabled(): boolean {
  return useSyncExternalStore(subscribeResearchMode, isResearchEnabled, () => false);
}
