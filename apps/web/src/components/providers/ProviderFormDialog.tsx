"use client";

import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { FormEvent, useEffect, useState } from "react";
import {
  providersApi,
  type LlmProviderCatalogResponse,
  type LlmProviderCreateRequest,
  type LlmProviderResponse,
  type LlmProviderUpdateRequest,
  type ProviderType,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Button, FieldHint } from "@/components/ui";

interface ProviderFormDialogProps {
  open: boolean;
  catalog: LlmProviderCatalogResponse | null;
  /** When set, the dialog edits this provider instead of creating one. */
  provider: LlmProviderResponse | null;
  initialType?: ProviderType;
  onClose: () => void;
  onSaved: (provider: LlmProviderResponse) => void;
}

interface FormState {
  providerType: ProviderType;
  name: string;
  models: string[];
  defaultModel: string;
  reasoningEffort: string;
  username: string;
  password: string;
  usercase: string;
}

function catalogFor(catalog: LlmProviderCatalogResponse | null, providerType: ProviderType) {
  return catalog?.provider_types.find((item) => item.provider_type === providerType) ?? null;
}

function initialState(
  catalog: LlmProviderCatalogResponse | null,
  provider: LlmProviderResponse | null,
  initialType: ProviderType,
): FormState {
  const providerType = provider?.provider_type ?? initialType;
  const typeCatalog = catalogFor(catalog, providerType);
  const models = provider?.models ?? typeCatalog?.models ?? [];
  const config = provider?.config ?? {};
  return {
    providerType,
    name: provider?.name ?? (providerType === "ai_platform" ? "AI Platform" : "GitHub Copilot"),
    models,
    defaultModel: provider?.default_model ?? typeCatalog?.default_model ?? models[0] ?? "",
    reasoningEffort:
      provider?.default_reasoning_effort ?? catalog?.default_reasoning_effort ?? "high",
    username: config.username ?? "",
    password: "",
    usercase: config.usercase ?? "",
  };
}

function buildPayload(state: FormState): LlmProviderCreateRequest {
  const payload: LlmProviderCreateRequest = {
    name: state.name.trim(),
    provider_type: state.providerType,
    models: state.models,
    default_model: state.defaultModel,
    default_reasoning_effort: state.reasoningEffort,
  };
  if (state.providerType === "ai_platform") {
    payload.config = { username: state.username.trim(), usercase: state.usercase.trim() };
    // An empty password leaves the stored one untouched.
    if (state.password) {
      payload.secrets = { password: state.password };
    }
  }
  return payload;
}

export function ProviderFormDialog({
  catalog,
  initialType = "ai_platform",
  onClose,
  onSaved,
  open,
  provider,
}: ProviderFormDialogProps) {
  const editing = provider !== null;
  const [state, setState] = useState<FormState>(() => initialState(catalog, provider, initialType));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setState(initialState(catalog, provider, initialType));
      setError(null);
    }
  }, [catalog, initialType, open, provider]);

  const typeCatalog = catalogFor(catalog, state.providerType);
  const efforts = catalog?.reasoning_efforts ?? [];
  const hasStoredPassword = Boolean(provider?.secret_fields.includes("password"));

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setState((current) => ({ ...current, [key]: value }));
  }

  function changeType(providerType: ProviderType) {
    setState(initialState(catalog, null, providerType));
  }

  function changeModels(models: string[]) {
    const cleaned = models.map((model) => model.trim()).filter(Boolean);
    setState((current) => ({
      ...current,
      models: cleaned,
      defaultModel: cleaned.includes(current.defaultModel) ? current.defaultModel : cleaned[0] ?? "",
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = buildPayload(state);
      let saved: LlmProviderResponse;
      if (provider) {
        const { provider_type: _ignored, ...update } = payload;
        void _ignored;
        saved = await providersApi.update(provider.provider_id, update as LlmProviderUpdateRequest);
      } else {
        saved = await providersApi.create(payload);
      }
      onSaved(saved);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog fullWidth maxWidth="sm" open={open} onClose={saving ? undefined : onClose}>
      <Box component="form" onSubmit={submit}>
        <DialogTitle sx={{ fontWeight: 850 }}>
          {editing ? `Edit ${provider.name}` : "Add AI provider"}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            {typeCatalog && !typeCatalog.available && (
              <Alert severity="warning">{typeCatalog.unavailable_reason}</Alert>
            )}

            {!editing && (
              <Stack spacing={1}>
                <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
                  Provider type
                </Typography>
                <ToggleButtonGroup
                  color="primary"
                  exclusive
                  value={state.providerType}
                  onChange={(_, value: ProviderType | null) => value && changeType(value)}
                >
                  <ToggleButton sx={{ px: 2.5, textTransform: "none" }} value="ai_platform">
                    AI Platform
                  </ToggleButton>
                  <ToggleButton sx={{ px: 2.5, textTransform: "none" }} value="github_copilot">
                    GitHub Copilot
                  </ToggleButton>
                </ToggleButtonGroup>
                <FieldHint>
                  {state.providerType === "ai_platform"
                    ? "The enterprise gateway. Its endpoints come from the deployment; you supply your own credentials."
                    : "Your GitHub Copilot subscription, authorized through the GitHub device flow."}
                </FieldHint>
              </Stack>
            )}

            <TextField
              label="Name"
              required
              value={state.name}
              onChange={(event) => update("name", event.target.value)}
            />

            {state.providerType === "ai_platform" && (
              <Stack spacing={2}>
                <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
                  Credentials
                </Typography>
                <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
                  <TextField
                    label="Username"
                    value={state.username}
                    onChange={(event) => update("username", event.target.value)}
                  />
                  <TextField
                    autoComplete="new-password"
                    label="Password"
                    placeholder={hasStoredPassword ? "Unchanged" : ""}
                    type="password"
                    value={state.password}
                    onChange={(event) => update("password", event.target.value)}
                  />
                  <TextField
                    label="Usercase"
                    value={state.usercase}
                    onChange={(event) => update("usercase", event.target.value)}
                  />
                </Box>
                <FieldHint>
                  The password is exchanged for a short-lived token before each request.
                </FieldHint>
              </Stack>
            )}

            {state.providerType === "github_copilot" && (
              <FieldHint>
                {editing
                  ? "Use Connect GitHub on the provider card to authorize this provider."
                  : "Save the provider, then use Connect GitHub on its card to authorize it."}
              </FieldHint>
            )}

            <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
              Models and thinking
            </Typography>
            <Autocomplete
              freeSolo
              multiple
              options={typeCatalog?.models ?? []}
              renderInput={(params) => (
                <TextField
                  {...params}
                  helperText="Models offered when this provider is selected. Type a model id and press Enter to add it."
                  label="Models"
                />
              )}
              renderValue={(values, getItemProps) =>
                values.map((option, index) => {
                  const { key, ...itemProps } = getItemProps({ index });
                  return (
                    <Chip
                      color={option === state.defaultModel ? "primary" : "default"}
                      key={key}
                      label={option}
                      size="small"
                      variant={option === state.defaultModel ? "filled" : "outlined"}
                      {...itemProps}
                    />
                  );
                })
              }
              value={state.models}
              onChange={(_, values) => changeModels(values)}
            />
            <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
              <TextField
                label="Default model"
                select
                value={state.models.includes(state.defaultModel) ? state.defaultModel : ""}
                onChange={(event) => update("defaultModel", event.target.value)}
              >
                {state.models.map((model) => (
                  <MenuItem key={model} value={model}>
                    {model}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Default thinking level"
                select
                value={
                  efforts.some((item) => item.value === state.reasoningEffort)
                    ? state.reasoningEffort
                    : ""
                }
                onChange={(event) => update("reasoningEffort", event.target.value)}
              >
                {efforts.map((effort) => (
                  <MenuItem key={effort.value} value={effort.value}>
                    {effort.label}
                  </MenuItem>
                ))}
              </TextField>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button disabled={saving} variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving || !state.name.trim() || state.models.length === 0} type="submit">
            {saving ? "Saving" : editing ? "Save changes" : "Create provider"}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}
