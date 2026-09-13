"use client";

import AddCircleIcon from "@mui/icons-material/AddCircle";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useCallback, useState } from "react";
import { providersApi, type LlmProviderResponse, type ProviderType } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { reasoningLabel } from "@/lib/inference";
import { useLlmProviders } from "@/lib/useLlmProviders";
import { GitHubConnectDialog } from "@/components/providers/GitHubConnectDialog";
import { ProviderFormDialog } from "@/components/providers/ProviderFormDialog";
import { Badge, Button, Card, EmptyState, SectionHeader } from "@/components/ui";

type DialogState =
  | { mode: "create"; initialType: ProviderType }
  | { mode: "edit"; provider: LlmProviderResponse }
  | null;

interface TestResult {
  ok: boolean;
  message: string;
}

export default function AiProvidersPage() {
  const { providers, catalog, loading, error, reload, setProviders } = useLlmProviders();
  const [dialog, setDialog] = useState<DialogState>(null);
  const [connecting, setConnecting] = useState<LlmProviderResponse | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const defaults = catalog?.ai_platform_defaults ?? {};

  const handleSaved = useCallback(
    (saved: LlmProviderResponse) => {
      setDialog(null);
      setTestResults((current) => {
        const next = { ...current };
        delete next[saved.provider_id];
        return next;
      });
      void reload();
    },
    [reload],
  );

  const handleConnected = useCallback(
    (connected: LlmProviderResponse) => {
      setProviders((current) =>
        current.map((item) => (item.provider_id === connected.provider_id ? connected : item)),
      );
    },
    [setProviders],
  );

  async function runTest(provider: LlmProviderResponse) {
    setBusy(`${provider.provider_id}:test`);
    setPageError(null);
    try {
      const result = await providersApi.test(provider.provider_id);
      setTestResults((current) => ({
        ...current,
        [provider.provider_id]: { ok: result.ok, message: result.message },
      }));
    } catch (caught) {
      setTestResults((current) => ({
        ...current,
        [provider.provider_id]: { ok: false, message: apiErrorMessage(caught) },
      }));
    } finally {
      setBusy(null);
    }
  }

  async function makeDefault(provider: LlmProviderResponse) {
    setBusy(`${provider.provider_id}:default`);
    setPageError(null);
    try {
      await providersApi.update(provider.provider_id, { is_default: true });
      await reload();
    } catch (caught) {
      setPageError(apiErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function remove(provider: LlmProviderResponse) {
    if (!window.confirm(`Delete the AI provider "${provider.name}"? Stored credentials are erased.`)) {
      return;
    }
    setBusy(`${provider.provider_id}:delete`);
    setPageError(null);
    try {
      await providersApi.remove(provider.provider_id);
      await reload();
    } catch (caught) {
      setPageError(apiErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Stack spacing={2.5}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        sx={{ alignItems: { md: "flex-end" }, justifyContent: "space-between" }}
      >
        <Box>
          <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
            Settings
          </Typography>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
            AI Providers
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            Connect AI Platform or GitHub Copilot, choose the models to offer, and set the default
            thinking level. Providers and credentials belong to your account only.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1.5} sx={{ flexShrink: 0 }}>
          <Button
            startIcon={<AddCircleIcon fontSize="small" />}
            onClick={() => setDialog({ mode: "create", initialType: "ai_platform" })}
          >
            Add AI Platform
          </Button>
          <Button
            startIcon={<AddCircleIcon fontSize="small" />}
            variant="secondary"
            onClick={() => setDialog({ mode: "create", initialType: "github_copilot" })}
          >
            Add GitHub Copilot
          </Button>
        </Stack>
      </Stack>

      {(error || pageError) && <Alert severity="error">{pageError || error}</Alert>}

      {loading && providers.length === 0 && (
        <Card>
          <EmptyState title="Loading providers" />
        </Card>
      )}

      {!loading && providers.length === 0 && (
        <Card>
          <EmptyState icon={<SmartToyIcon fontSize="small" />} title="No AI providers yet">
            <Typography color="text.secondary" sx={{ maxWidth: 560, mx: "auto" }}>
              Without a provider, analysis runs use the deterministic pipeline only. Add a
              provider to enable template annotation, generated summaries, and analysis chat.
            </Typography>
          </EmptyState>
        </Card>
      )}

      {providers.length > 0 && (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", xl: "repeat(2, minmax(0, 1fr))" } }}>
          {providers.map((provider) => {
            const testResult = testResults[provider.provider_id];
            const isBusy = busy?.startsWith(`${provider.provider_id}:`) ?? false;
            const endpoint =
              provider.provider_type === "ai_platform"
                ? `${provider.config.chat_host || defaults.chat_host || "chat host not set"}${provider.config.chat_uri || defaults.chat_uri || ""}`
                : provider.config.github_login
                  ? `GitHub account ${provider.config.github_login}`
                  : "GitHub account not connected";
            return (
              <Card key={provider.provider_id}>
                <Stack spacing={2}>
                  <SectionHeader
                    actions={
                      <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                        <Badge tone="info">{provider.provider_label}</Badge>
                        {provider.is_default && <Badge tone="success">Default</Badge>}
                        <Badge tone={provider.credentials_configured ? "success" : "warning"}>
                          {provider.credentials_configured ? "Ready" : "Not connected"}
                        </Badge>
                      </Stack>
                    }
                    eyebrow="Provider"
                    title={provider.name}
                  />
                  <Box
                    component="dl"
                    sx={{
                      display: "grid",
                      gap: 1,
                      gridTemplateColumns: "130px minmax(0, 1fr)",
                      m: 0,
                      "& dt": { color: "text.secondary" },
                      "& dd": { m: 0, overflowWrap: "anywhere" },
                    }}
                  >
                    <dt>Credentials</dt>
                    <dd>{provider.credential_summary || "None stored yet"}</dd>
                    <dt>{provider.provider_type === "ai_platform" ? "Endpoint" : "Account"}</dt>
                    <dd>{endpoint}</dd>
                    <dt>Default model</dt>
                    <dd>
                      {provider.default_model} · {reasoningLabel(catalog, provider.default_reasoning_effort)} thinking
                    </dd>
                    <dt>Models</dt>
                    <dd>
                      <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.75 }}>
                        {provider.models.map((model) => (
                          <Chip
                            color={model === provider.default_model ? "primary" : "default"}
                            key={model}
                            label={model}
                            size="small"
                            variant={model === provider.default_model ? "filled" : "outlined"}
                          />
                        ))}
                      </Stack>
                    </dd>
                  </Box>
                  {testResult && (
                    <Alert severity={testResult.ok ? "success" : "error"}>{testResult.message}</Alert>
                  )}
                  <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                    {provider.provider_type === "github_copilot" && (
                      <Button disabled={isBusy} size="sm" onClick={() => setConnecting(provider)}>
                        {provider.credentials_configured ? "Reconnect GitHub" : "Connect GitHub"}
                      </Button>
                    )}
                    <Button
                      disabled={isBusy || !provider.credentials_configured}
                      size="sm"
                      variant="secondary"
                      onClick={() => void runTest(provider)}
                    >
                      {busy === `${provider.provider_id}:test` ? "Testing" : "Test connection"}
                    </Button>
                    <Button
                      disabled={isBusy}
                      size="sm"
                      variant="secondary"
                      onClick={() => setDialog({ mode: "edit", provider })}
                    >
                      Edit
                    </Button>
                    {!provider.is_default && (
                      <Button disabled={isBusy} size="sm" variant="ghost" onClick={() => void makeDefault(provider)}>
                        {busy === `${provider.provider_id}:default` ? "Saving" : "Set as default"}
                      </Button>
                    )}
                    <Button disabled={isBusy} size="sm" variant="danger" onClick={() => void remove(provider)}>
                      {busy === `${provider.provider_id}:delete` ? "Deleting" : "Delete"}
                    </Button>
                  </Stack>
                </Stack>
              </Card>
            );
          })}
        </Box>
      )}

      <Card tone="subtle">
        <Stack spacing={1}>
          <Typography sx={{ fontWeight: 850 }} variant="subtitle1">
            How providers are used
          </Typography>
          <Typography color="text.secondary" variant="body2">
            When you start an analysis run you pick a provider, a model, and a thinking level; the
            run annotates templates and writes the causal summary with that choice. Analysis chat
            lets you pick again for every question. Credentials are stored encrypted with the
            server secret and only ever leave the server to reach the provider itself.
          </Typography>
        </Stack>
      </Card>

      <ProviderFormDialog
        catalog={catalog}
        initialType={dialog?.mode === "create" ? dialog.initialType : "ai_platform"}
        open={dialog !== null}
        provider={dialog?.mode === "edit" ? dialog.provider : null}
        onClose={() => setDialog(null)}
        onSaved={handleSaved}
      />
      <GitHubConnectDialog
        open={connecting !== null}
        provider={connecting}
        onClose={() => setConnecting(null)}
        onConnected={handleConnected}
      />
    </Stack>
  );
}
