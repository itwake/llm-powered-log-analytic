"use client";

import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Link from "@/components/Link";
import type {
  InferenceSelection,
  LlmProviderCatalogResponse,
  LlmProviderResponse,
} from "@/lib/api";
import { EMPTY_SELECTION, findProvider, selectionForProvider } from "@/lib/inference";

const NO_PROVIDER_VALUE = "__none__";

interface InferenceSelectorProps {
  providers: LlmProviderResponse[];
  catalog: LlmProviderCatalogResponse | null;
  value: InferenceSelection;
  onChange: (next: InferenceSelection) => void;
  /** Offer a "No AI" choice that runs the deterministic pipeline only. */
  allowNone?: boolean;
  disabled?: boolean;
  loading?: boolean;
  compact?: boolean;
}

/** Provider, model, and thinking-level pickers shared by chat and analysis runs. */
export function InferenceSelector({
  allowNone = false,
  catalog,
  compact = false,
  disabled = false,
  loading = false,
  onChange,
  providers,
  value,
}: InferenceSelectorProps) {
  const selectedProvider = findProvider(providers, value.provider_id);
  const providerValue = selectedProvider ? selectedProvider.provider_id : NO_PROVIDER_VALUE;
  const models = selectedProvider?.models ?? [];
  const modelValue = value.model && models.includes(value.model) ? value.model : "";
  const efforts = catalog?.reasoning_efforts ?? [];
  const effortValue =
    value.reasoning_effort && efforts.some((item) => item.value === value.reasoning_effort)
      ? value.reasoning_effort
      : "";
  const size = compact ? "small" : "medium";
  const nothingConfigured = !loading && providers.length === 0;

  function changeProvider(providerId: string) {
    if (providerId === NO_PROVIDER_VALUE) {
      onChange(EMPTY_SELECTION);
      return;
    }
    onChange(selectionForProvider(findProvider(providers, providerId)));
  }

  return (
    <Stack spacing={1}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
        <TextField
          disabled={disabled || loading || (nothingConfigured && !allowNone)}
          label="AI provider"
          select
          size={size}
          slotProps={{ select: { displayEmpty: true } }}
          sx={{ minWidth: { sm: 220 }, flex: 1.4 }}
          value={providerValue}
          onChange={(event) => changeProvider(event.target.value)}
        >
          {allowNone && <MenuItem value={NO_PROVIDER_VALUE}>No AI (deterministic pipeline)</MenuItem>}
          {!allowNone && providers.length === 0 && (
            <MenuItem disabled value={NO_PROVIDER_VALUE}>
              {loading ? "Loading providers" : "No AI provider configured"}
            </MenuItem>
          )}
          {providers.map((provider) => (
            <MenuItem
              disabled={!provider.credentials_configured}
              key={provider.provider_id}
              value={provider.provider_id}
            >
              {provider.name}
              {provider.is_default ? " (default)" : ""}
              {provider.credentials_configured ? "" : " — not connected"}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          disabled={disabled || !selectedProvider}
          label="Model"
          select
          size={size}
          sx={{ minWidth: { sm: 170 }, flex: 1 }}
          value={modelValue}
          onChange={(event) => onChange({ ...value, model: event.target.value })}
        >
          {models.map((model) => (
            <MenuItem key={model} value={model}>
              {model}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          disabled={disabled || !selectedProvider}
          label="Thinking"
          select
          size={size}
          sx={{ minWidth: { sm: 150 }, flex: 0.8 }}
          value={effortValue}
          onChange={(event) => onChange({ ...value, reasoning_effort: event.target.value })}
        >
          {efforts.map((effort) => (
            <MenuItem key={effort.value} value={effort.value}>
              {effort.label}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      {nothingConfigured && (
        <Typography color="text.secondary" variant="caption">
          No AI provider is configured.{" "}
          <Box component={Link} href="/settings/ai-providers" sx={{ fontWeight: 750 }}>
            Add an AI Platform or GitHub Copilot provider
          </Box>{" "}
          to enable annotation, generated summaries, and chat.
        </Typography>
      )}
      {!nothingConfigured && selectedProvider && (
        <Typography color="text.secondary" variant="caption">
          {selectedProvider.provider_label}
          {selectedProvider.credential_summary ? ` · ${selectedProvider.credential_summary}` : ""}
        </Typography>
      )}
    </Stack>
  );
}
