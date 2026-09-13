import type {
  AnalysisRunResponse,
  InferenceSelection,
  LlmProviderCatalogResponse,
  LlmProviderResponse,
} from "@/lib/api";

export const EMPTY_SELECTION: InferenceSelection = {
  provider_id: null,
  model: null,
  reasoning_effort: null,
};

const FALLBACK_REASONING_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

/** Providers that can answer a request right now. */
export function readyProviders(providers: LlmProviderResponse[]): LlmProviderResponse[] {
  return providers.filter((provider) => provider.credentials_configured);
}

export function findProvider(
  providers: LlmProviderResponse[],
  providerId: string | null | undefined,
): LlmProviderResponse | null {
  if (!providerId) {
    return null;
  }
  return providers.find((provider) => provider.provider_id === providerId) ?? null;
}

export function selectionForProvider(
  provider: LlmProviderResponse | null | undefined,
): InferenceSelection {
  if (!provider) {
    return EMPTY_SELECTION;
  }
  return {
    provider_id: provider.provider_id,
    model: provider.default_model,
    reasoning_effort: provider.default_reasoning_effort,
  };
}

/**
 * The preferred provider (with its preferred model and thinking level when still valid) when
 * one is known, else the user's default provider, else the first ready one.
 */
export function defaultInferenceSelection(
  providers: LlmProviderResponse[],
  preferred?: Partial<InferenceSelection> | null,
): InferenceSelection {
  const ready = readyProviders(providers);
  const preferredProvider = findProvider(ready, preferred?.provider_id);
  if (preferredProvider) {
    return {
      provider_id: preferredProvider.provider_id,
      model:
        preferred?.model && preferredProvider.models.includes(preferred.model)
          ? preferred.model
          : preferredProvider.default_model,
      reasoning_effort: preferred?.reasoning_effort || preferredProvider.default_reasoning_effort,
    };
  }
  const provider = ready.find((item) => item.is_default) ?? ready[0] ?? null;
  return selectionForProvider(provider);
}

/** Keep the current choice when it is still valid; otherwise fall back to a default. */
export function reconcileSelection(
  providers: LlmProviderResponse[],
  current: InferenceSelection,
  preferred?: Partial<InferenceSelection> | null,
): InferenceSelection {
  const provider = findProvider(readyProviders(providers), current.provider_id);
  if (!provider) {
    return defaultInferenceSelection(providers, preferred);
  }
  const model = current.model && provider.models.includes(current.model)
    ? current.model
    : provider.default_model;
  return {
    provider_id: provider.provider_id,
    model,
    reasoning_effort: current.reasoning_effort ?? provider.default_reasoning_effort,
  };
}

export function reasoningLabel(
  catalog: LlmProviderCatalogResponse | null | undefined,
  value: string | null | undefined,
): string {
  if (!value) {
    return "Default";
  }
  const option = catalog?.reasoning_efforts.find((item) => item.value === value);
  return option?.label ?? FALLBACK_REASONING_LABELS[value] ?? value;
}

export function describeSelection(
  providers: LlmProviderResponse[],
  catalog: LlmProviderCatalogResponse | null | undefined,
  selection: InferenceSelection,
): string {
  const provider = findProvider(providers, selection.provider_id);
  if (!provider) {
    return "No AI provider";
  }
  return [provider.name, selection.model ?? provider.default_model, reasoningLabel(catalog, selection.reasoning_effort)]
    .filter(Boolean)
    .join(" · ");
}

/** Human-readable label of the provider, model, and thinking level a run was created with. */
export function describeRunModel(
  run: AnalysisRunResponse | null | undefined,
  catalog?: LlmProviderCatalogResponse | null,
): string {
  if (!run) {
    return "n/a";
  }
  if (run.model_provider === "none") {
    return "None (deterministic)";
  }
  const parts = [run.llm_provider_name || run.model_provider, run.model_name];
  if (run.reasoning_effort) {
    parts.push(reasoningLabel(catalog, run.reasoning_effort));
  }
  return parts.join(" · ");
}
