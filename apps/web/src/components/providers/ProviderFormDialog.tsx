"use client";

import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
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

type AuthMode = "ib2b" | "token";

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
  isDefault: boolean;
  chatHost: string;
  chatUri: string;
  authMode: AuthMode;
  username: string;
  password: string;
  usercase: string;
  token: string;
  tokenExpiresAt: string;
  ib2bHost: string;
  ib2bUri: string;
  trustTokenHeader: string;
  trackingPrefix: string;
  githubToken: string;
  apiBaseUrl: string;
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
    isDefault: provider?.is_default ?? false,
    chatHost: config.chat_host ?? "",
    chatUri: config.chat_uri ?? "",
    authMode: provider?.secret_fields.includes("token") ? "token" : "ib2b",
    username: config.username ?? "",
    password: "",
    usercase: config.usercase ?? "",
    token: "",
    tokenExpiresAt: config.token_expires_at ?? "",
    ib2bHost: config.ib2b_host ?? "",
    ib2bUri: config.ib2b_uri ?? "",
    trustTokenHeader: config.trust_token_header ?? "",
    trackingPrefix: config.tracking_prefix ?? "",
    githubToken: "",
    apiBaseUrl: config.api_base_url ?? "",
  };
}

function withoutUndefined(values: Record<string, string | undefined>): Record<string, string | null> {
  const cleaned: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

function buildPayload(state: FormState, editing: boolean): LlmProviderCreateRequest {
  const base: LlmProviderCreateRequest = {
    name: state.name.trim(),
    provider_type: state.providerType,
    models: state.models,
    default_model: state.defaultModel,
    default_reasoning_effort: state.reasoningEffort,
    is_default: state.isDefault,
  };
  if (state.providerType === "ai_platform") {
    const tokenMode = state.authMode === "token";
    base.config = {
      chat_host: state.chatHost.trim(),
      chat_uri: state.chatUri.trim(),
      usercase: state.usercase.trim(),
      username: tokenMode ? "" : state.username.trim(),
      token_expires_at: tokenMode ? state.tokenExpiresAt.trim() : "",
      ib2b_host: state.ib2bHost.trim(),
      ib2b_uri: state.ib2bUri.trim(),
      trust_token_header: state.trustTokenHeader.trim(),
      tracking_prefix: state.trackingPrefix.trim(),
    };
    base.secrets = withoutUndefined(
      tokenMode
        ? { token: state.token || undefined, password: "" }
        : { password: state.password || undefined, token: "" },
    );
    return base;
  }
  base.config = { api_base_url: state.apiBaseUrl.trim() };
  base.secrets = withoutUndefined({ github_token: state.githubToken || undefined });
  if (!editing && !state.githubToken) {
    delete base.secrets.github_token;
  }
  return base;
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
  const [advanced, setAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setState(initialState(catalog, provider, initialType));
      setAdvanced(false);
      setError(null);
    }
  }, [catalog, initialType, open, provider]);

  const typeCatalog = catalogFor(catalog, state.providerType);
  const defaults = catalog?.ai_platform_defaults ?? {};
  const efforts = catalog?.reasoning_efforts ?? [];
  const hasSecret = (field: string) => Boolean(provider?.secret_fields.includes(field));

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
      const payload = buildPayload(state, editing);
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

  const defaultHint = (key: string) =>
    defaults[key] ? `Leave blank to use the deployment default: ${defaults[key]}` : undefined;

  return (
    <Dialog fullWidth maxWidth="md" open={open} onClose={saving ? undefined : onClose}>
      <Box component="form" onSubmit={submit}>
        <DialogTitle sx={{ fontWeight: 850 }}>
          {editing ? `Edit ${provider.name}` : "Add AI provider"}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}

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
                    ? "Enterprise AI Platform gateway reached with a trust token or iB2B credentials."
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
                  Endpoint
                </Typography>
                <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" } }}>
                  <TextField
                    helperText={defaultHint("chat_host") ?? "Origin of the chat completions API."}
                    label="Chat host"
                    placeholder={defaults.chat_host || "https://ai.example.com"}
                    required={!defaults.chat_host}
                    value={state.chatHost}
                    onChange={(event) => update("chatHost", event.target.value)}
                  />
                  <TextField
                    helperText={defaultHint("chat_uri")}
                    label="Chat URI"
                    placeholder={defaults.chat_uri || "/v1/api/v1/chat/completions"}
                    value={state.chatUri}
                    onChange={(event) => update("chatUri", event.target.value)}
                  />
                </Box>

                <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
                  Credentials
                </Typography>
                <ToggleButtonGroup
                  color="primary"
                  exclusive
                  size="small"
                  value={state.authMode}
                  onChange={(_, value: AuthMode | null) => value && update("authMode", value)}
                >
                  <ToggleButton sx={{ px: 2, textTransform: "none" }} value="ib2b">
                    Username and password (iB2B)
                  </ToggleButton>
                  <ToggleButton sx={{ px: 2, textTransform: "none" }} value="token">
                    Trust token
                  </ToggleButton>
                </ToggleButtonGroup>
                {state.authMode === "ib2b" ? (
                  <Stack spacing={2}>
                    <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
                      <TextField
                        label="Username"
                        value={state.username}
                        onChange={(event) => update("username", event.target.value)}
                      />
                      <TextField
                        autoComplete="new-password"
                        label="Password"
                        placeholder={hasSecret("password") ? "Unchanged" : ""}
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
                    <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
                      <TextField
                        helperText={defaultHint("ib2b_host")}
                        label="iB2B host"
                        placeholder={defaults.ib2b_host || "https://identity.example.com"}
                        value={state.ib2bHost}
                        onChange={(event) => update("ib2bHost", event.target.value)}
                      />
                      <TextField
                        helperText={defaultHint("ib2b_uri")}
                        label="iB2B URI"
                        placeholder={defaults.ib2b_uri || "/token"}
                        value={state.ib2bUri}
                        onChange={(event) => update("ib2bUri", event.target.value)}
                      />
                    </Box>
                    <FieldHint>
                      The password is exchanged for a short-lived JWT before each request and stored
                      encrypted on the server.
                    </FieldHint>
                  </Stack>
                ) : (
                  <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "2fr 1fr 1fr" } }}>
                    <TextField
                      autoComplete="off"
                      label="Trust token"
                      placeholder={hasSecret("token") ? "Unchanged" : ""}
                      type="password"
                      value={state.token}
                      onChange={(event) => update("token", event.target.value)}
                    />
                    <TextField
                      helperText="Optional ISO timestamp or epoch seconds."
                      label="Token expires at"
                      value={state.tokenExpiresAt}
                      onChange={(event) => update("tokenExpiresAt", event.target.value)}
                    />
                    <TextField
                      helperText="Sent as the user field."
                      label="Usercase"
                      value={state.usercase}
                      onChange={(event) => update("usercase", event.target.value)}
                    />
                  </Box>
                )}
              </Stack>
            )}

            {state.providerType === "github_copilot" && (
              <Stack spacing={1.5}>
                <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
                  GitHub authorization
                </Typography>
                <FieldHint>
                  {editing
                    ? "Use Connect GitHub on the provider card to authorize with the device flow, or paste a GitHub token here."
                    : "Save the provider, then use Connect GitHub on its card to authorize with the device flow. You can also paste an existing GitHub token."}
                </FieldHint>
                <TextField
                  autoComplete="off"
                  label="GitHub token (optional)"
                  placeholder={hasSecret("github_token") ? "Unchanged" : "gho_…"}
                  type="password"
                  value={state.githubToken}
                  onChange={(event) => update("githubToken", event.target.value)}
                />
              </Stack>
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
                value={efforts.some((item) => item.value === state.reasoningEffort) ? state.reasoningEffort : ""}
                onChange={(event) => update("reasoningEffort", event.target.value)}
              >
                {efforts.map((effort) => (
                  <MenuItem key={effort.value} value={effort.value}>
                    {effort.label}
                  </MenuItem>
                ))}
              </TextField>
            </Box>
            <FormControlLabel
              control={
                <Checkbox
                  checked={state.isDefault}
                  onChange={(event) => update("isDefault", event.target.checked)}
                />
              }
              label="Use as my default provider for new runs and chat"
            />

            <Box>
              <Button size="sm" variant="ghost" onClick={() => setAdvanced((current) => !current)}>
                {advanced ? "Hide advanced settings" : "Show advanced settings"}
              </Button>
              <Collapse in={advanced}>
                <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, mt: 2 }}>
                  {state.providerType === "ai_platform" ? (
                    <>
                      <TextField
                        helperText={defaultHint("trust_token_header")}
                        label="Trust token header"
                        placeholder={defaults.trust_token_header || "X-XXXX-E2E-Trust-Token"}
                        value={state.trustTokenHeader}
                        onChange={(event) => update("trustTokenHeader", event.target.value)}
                      />
                      <TextField
                        helperText={defaultHint("tracking_prefix")}
                        label="Tracking id prefix"
                        placeholder={defaults.tracking_prefix || "EFP"}
                        value={state.trackingPrefix}
                        onChange={(event) => update("trackingPrefix", event.target.value)}
                      />
                    </>
                  ) : (
                    <TextField
                      helperText="Leave blank to use the endpoint reported by GitHub for your account."
                      label="Copilot API base URL"
                      placeholder="https://api.githubcopilot.com"
                      value={state.apiBaseUrl}
                      onChange={(event) => update("apiBaseUrl", event.target.value)}
                    />
                  )}
                </Box>
              </Collapse>
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
