"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { capabilitiesApi, CapabilitiesResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Badge, Card, InfoGrid } from "@/components/ui";

function providerLabel(provider: string): string {
  return provider === "ai_platform" ? "AI Platform" : provider;
}

export default function AIPlatformSettingsPage() {
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    capabilitiesApi
      .get()
      .then((response) => {
        if (!cancelled) {
          setCapabilities(response);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(apiErrorMessage(caught));
          setCapabilities(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          AI Platform
        </Typography>
        <Typography color="text.secondary">Runtime capability and model surface configuration.</Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" } }}>
        <Card>
          <Typography component="h2" gutterBottom sx={{ fontWeight: 800 }} variant="h6">
            Runtime
          </Typography>
          {loading && <Skeleton height={150} variant="rounded" />}
          {!loading && capabilities && (
            <InfoGrid
              rows={[
                { label: "Provider", value: providerLabel(capabilities.models.provider) },
                { label: "Default model", value: capabilities.models.default_model },
                {
                  label: "Status",
                  value: (
                    <Badge tone={capabilities.models.provider === "ai_platform" ? "success" : "warning"}>
                      {capabilities.models.provider === "ai_platform" ? "configured" : "check configuration"}
                    </Badge>
                  ),
                },
              ]}
            />
          )}
        </Card>

        <Card>
          <Typography component="h2" gutterBottom sx={{ fontWeight: 800 }} variant="h6">
            Model Surface
          </Typography>
          {loading && <Skeleton height={150} variant="rounded" />}
          {!loading && capabilities && (
            <InfoGrid
              rows={[
                { label: "Supported models", value: capabilities.models.supported_models.join(", ") },
                { label: "Views", value: capabilities.views.join(", ") },
                { label: "Uploads", value: capabilities.upload.supported_extensions.join(", ") },
              ]}
            />
          )}
        </Card>
      </Box>
    </Stack>
  );
}
