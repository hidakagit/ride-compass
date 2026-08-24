"use client";

import { useSyncExternalStore } from "react";
import { type AdminCredentials, getAdminCredentials, subscribeAdminCredentials } from "@/lib/adminToken";

const EMPTY_CREDENTIALS: AdminCredentials = { username: "", password: "" };

export function useAdminCredentials(): AdminCredentials {
  return useSyncExternalStore(subscribeAdminCredentials, getAdminCredentials, () => EMPTY_CREDENTIALS);
}
