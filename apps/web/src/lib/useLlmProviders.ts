"use client";

import { useCallback, useEffect, useState } from "react";
import {
  providersApi,
  type LlmProviderCatalogResponse,
  type LlmProviderResponse,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

export interface LlmProvidersState {
  providers: LlmProviderResponse[];
  catalog: LlmProviderCatalogResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  setProviders: (updater: (current: LlmProviderResponse[]) => LlmProviderResponse[]) => void;
}

/** Loads the signed-in user's AI providers and the provider catalog once per page. */
export function useLlmProviders(): LlmProvidersState {
  const [providers, setProvidersState] = useState<LlmProviderResponse[]>([]);
  const [catalog, setCatalog] = useState<LlmProviderCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [listed, loadedCatalog] = await Promise.all([
        providersApi.list(),
        providersApi.catalog(),
      ]);
      setProvidersState(listed.items);
      setCatalog(loadedCatalog);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setProviders = useCallback(
    (updater: (current: LlmProviderResponse[]) => LlmProviderResponse[]) => {
      setProvidersState((current) => updater(current));
    },
    [],
  );

  return { providers, catalog, loading, error, reload, setProviders };
}
