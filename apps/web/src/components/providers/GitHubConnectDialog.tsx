"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import MuiButton from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  providersApi,
  type GitHubDeviceStartResponse,
  type LlmProviderResponse,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Button, FieldHint } from "@/components/ui";

type Phase = "starting" | "waiting" | "authorized" | "failed";

interface GitHubConnectDialogProps {
  open: boolean;
  provider: LlmProviderResponse | null;
  onClose: () => void;
  onConnected: (provider: LlmProviderResponse) => void;
}

function formatRemaining(seconds: number): string {
  const clamped = Math.max(0, seconds);
  const minutes = Math.floor(clamped / 60);
  const rest = clamped % 60;
  return `${minutes}:${rest < 10 ? "0" : ""}${rest}`;
}

/**
 * GitHub device authorization for a GitHub Copilot provider. The browser only sees the one-time
 * user code; the resulting token is stored by the API on the provider record.
 */
export function GitHubConnectDialog({ onClose, onConnected, open, provider }: GitHubConnectDialogProps) {
  const [phase, setPhase] = useState<Phase>("starting");
  const [flow, setFlow] = useState<GitHubDeviceStartResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [login, setLogin] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pollTimer = useRef<number | null>(null);
  const countdownTimer = useRef<number | null>(null);

  const stopTimers = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    if (countdownTimer.current !== null) {
      window.clearInterval(countdownTimer.current);
      countdownTimer.current = null;
    }
  }, []);

  useEffect(() => {
    if (!open || !provider) {
      return undefined;
    }
    let cancelled = false;
    const providerId = provider.provider_id;
    setPhase("starting");
    setFlow(null);
    setMessage(null);
    setLogin(null);
    setCopied(false);

    function schedulePoll(authId: string, intervalSeconds: number) {
      pollTimer.current = window.setTimeout(async () => {
        if (cancelled) {
          return;
        }
        let nextInterval = intervalSeconds;
        try {
          const result = await providersApi.githubDeviceCheck(providerId, authId);
          if (cancelled) {
            return;
          }
          if (result.status === "authorized") {
            stopTimers();
            setPhase("authorized");
            setLogin(result.github_login);
            if (result.provider) {
              onConnected(result.provider);
            }
            return;
          }
          if (result.status !== "pending") {
            stopTimers();
            setPhase("failed");
            setMessage(result.message || `GitHub authorization ${result.status}.`);
            return;
          }
          if (result.interval && result.interval > nextInterval) {
            nextInterval = result.interval;
          }
        } catch (caught) {
          if (cancelled) {
            return;
          }
          stopTimers();
          setPhase("failed");
          setMessage(apiErrorMessage(caught));
          return;
        }
        schedulePoll(authId, nextInterval);
      }, Math.max(intervalSeconds, 1) * 1000);
    }

    providersApi
      .githubDeviceStart(providerId)
      .then((started) => {
        if (cancelled) {
          return;
        }
        setFlow(started);
        setPhase("waiting");
        setRemaining(started.expires_in);
        countdownTimer.current = window.setInterval(() => {
          setRemaining((current) => {
            if (current <= 1) {
              stopTimers();
              setPhase("failed");
              setMessage("The code expired before GitHub confirmed it. Start again.");
              return 0;
            }
            return current - 1;
          });
        }, 1000);
        schedulePoll(started.auth_id, started.interval);
      })
      .catch((caught) => {
        if (!cancelled) {
          setPhase("failed");
          setMessage(apiErrorMessage(caught));
        }
      });

    return () => {
      cancelled = true;
      stopTimers();
    };
  }, [attempt, onConnected, open, provider, stopTimers]);

  async function copyCode() {
    if (!flow) {
      return;
    }
    try {
      await navigator.clipboard.writeText(flow.user_code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Dialog fullWidth maxWidth="sm" open={open} onClose={onClose}>
      <DialogTitle sx={{ fontWeight: 850 }}>Connect GitHub Copilot</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {provider && (
            <Typography color="text.secondary" variant="body2">
              Authorize <strong>{provider.name}</strong> with your GitHub account. LogAn uses the
              GitHub Copilot device flow; the resulting token is stored encrypted on the server.
            </Typography>
          )}
          {phase === "starting" && (
            <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
              <CircularProgress size={18} />
              <Typography variant="body2">Contacting GitHub…</Typography>
            </Stack>
          )}
          {phase === "waiting" && flow && (
            <Stack spacing={1.5}>
              <Typography variant="body2">
                1. Open the GitHub device page and enter this one-time code:
              </Typography>
              <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                <Box
                  component="code"
                  sx={{
                    bgcolor: "rgba(91,92,246,0.08)",
                    border: "1px solid rgba(91,92,246,0.2)",
                    borderRadius: "10px",
                    fontSize: 24,
                    fontWeight: 900,
                    letterSpacing: 3,
                    px: 2,
                    py: 1,
                  }}
                >
                  {flow.user_code}
                </Box>
                <Button size="sm" variant="secondary" onClick={() => void copyCode()}>
                  {copied ? "Copied" : "Copy code"}
                </Button>
                <MuiButton
                  component="a"
                  disableElevation
                  href={flow.verification_uri_complete || flow.verification_uri}
                  rel="noopener noreferrer"
                  size="small"
                  target="_blank"
                  variant="contained"
                >
                  Open GitHub
                </MuiButton>
              </Stack>
              <Typography variant="body2">2. Confirm the authorization in GitHub.</Typography>
              <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
                <CircularProgress size={16} />
                <Typography color="text.secondary" variant="body2">
                  Waiting for GitHub… code valid for {formatRemaining(remaining)}
                </Typography>
              </Stack>
              <FieldHint>
                Enterprise-managed accounts may first need to sign in through the company SSO in
                the GitHub tab.
              </FieldHint>
            </Stack>
          )}
          {phase === "authorized" && (
            <Alert severity="success">
              GitHub Copilot is connected{login ? ` as ${login}` : ""}. You can use this provider
              for analysis runs and chat.
            </Alert>
          )}
          {phase === "failed" && (
            <Alert
              action={
                <Button size="sm" variant="ghost" onClick={() => setAttempt((current) => current + 1)}>
                  Try again
                </Button>
              }
              severity="error"
            >
              {message || "GitHub authorization failed."}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}>
        <Button variant={phase === "authorized" ? "primary" : "secondary"} onClick={onClose}>
          {phase === "authorized" ? "Done" : "Close"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
