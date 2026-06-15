"use client";

import { useEffect, useRef, useState } from "react";
import { authApi, copilotAuthApi, CopilotStartResponse, UserOut } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Shell } from "@/components/Shell";

function pollMessage(message?: string | null) {
  if (message === "authorization_pending" || message === "slow_down" || message === "rate_limited") {
    return "Waiting for GitHub authorization";
  }
  return message || "Authorization pending";
}

export default function CopilotSettingsPage() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [deviceAuth, setDeviceAuth] = useState<CopilotStartResponse | null>(null);
  const [pollStatus, setPollStatus] = useState<"idle" | "pending" | "authorized" | "stopped">("idle");
  const [nextPollSeconds, setNextPollSeconds] = useState<number | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const checkingRef = useRef(false);

  async function loadMe() {
    setLoading(true);
    setError(null);
    try {
      const response = await authApi.me();
      setUser(response.user);
    } catch (caught) {
      setError(apiErrorMessage(caught));
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadMe();
  }, []);

  async function startAuth() {
    setStarting(true);
    setError(null);
    setMessage(null);
    try {
      const response = await copilotAuthApi.start();
      setDeviceAuth(response);
      setPollStatus("pending");
      setNextPollSeconds(response.interval);
      setPollAttempt((value) => value + 1);
      setMessage("Waiting for GitHub authorization");
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setStarting(false);
    }
  }

  async function disconnect() {
    setDisconnecting(true);
    setError(null);
    setMessage(null);
    try {
      await copilotAuthApi.disconnect();
      setDeviceAuth(null);
      setPollStatus("idle");
      setNextPollSeconds(null);
      setPollAttempt(0);
      setMessage("Copilot disconnected");
      await loadMe();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setDisconnecting(false);
    }
  }

  async function checkAuth(auth: CopilotStartResponse) {
    if (checkingRef.current) {
      return;
    }
    checkingRef.current = true;
    setChecking(true);
    setError(null);
    try {
      const response = await copilotAuthApi.check(auth.auth_id, auth.device_code);
      if (response.status === "authorized") {
        setPollStatus("authorized");
        setMessage("Copilot connected");
        setNextPollSeconds(null);
        setPollAttempt(0);
        await loadMe();
        return;
      }
      if (response.status === "pending") {
        setPollStatus("pending");
        setMessage(pollMessage(response.message));
        setNextPollSeconds(response.next_poll_after_seconds ?? auth.interval ?? 5);
        setPollAttempt((value) => value + 1);
        return;
      }
      setPollStatus("stopped");
      setMessage(response.message || response.status);
      setNextPollSeconds(null);
      setPollAttempt(0);
    } catch (caught) {
      setPollStatus("stopped");
      setError(apiErrorMessage(caught));
      setNextPollSeconds(null);
      setPollAttempt(0);
    } finally {
      checkingRef.current = false;
      setChecking(false);
    }
  }

  useEffect(() => {
    if (!deviceAuth || pollStatus !== "pending") {
      return;
    }
    const delay = Math.max(1, nextPollSeconds || deviceAuth.interval);
    const timer = window.setTimeout(() => {
      void checkAuth(deviceAuth);
    }, delay * 1000);
    return () => window.clearTimeout(timer);
  }, [deviceAuth, nextPollSeconds, pollStatus, pollAttempt]);

  return (
    <Shell>
      <div className="toolbar">
        <h1>Copilot Settings</h1>
        <button
          className="button"
          disabled={starting || loading || disconnecting}
          type="button"
          onClick={startAuth}
        >
          {starting
            ? "Starting"
            : user?.has_copilot_credential
              ? "Reconnect GitHub Copilot"
              : "Connect GitHub Copilot"}
        </button>
        {user?.has_copilot_credential && (
          <button
            className="button danger"
            disabled={disconnecting || loading}
            type="button"
            onClick={disconnect}
          >
            {disconnecting ? "Disconnecting" : "Disconnect"}
          </button>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}
      <section className="grid two">
        <div className="panel">
          <h2>Status</h2>
          {loading && <div className="empty">Checking status</div>}
          {!loading && user && (
            <p>
              <span className={`pill ${user.has_copilot_credential ? "green" : "amber"}`}>
                {user.has_copilot_credential ? "connected" : "not connected"}
              </span>
            </p>
          )}
          {!loading && !user && <p><span className="pill red">signed out</span></p>}
        </div>

        <div className="panel">
          <h2>Device Code</h2>
          {!deviceAuth && <div className="empty">No active device auth</div>}
          {deviceAuth && (
            <>
              <p><strong>{deviceAuth.user_code}</strong></p>
              <p>
                <a href={deviceAuth.verification_uri_complete} rel="noreferrer" target="_blank">
                  {deviceAuth.verification_uri}
                </a>
              </p>
              <table>
                <tbody>
                  <tr><td>Poll interval</td><td>{deviceAuth.interval}s</td></tr>
                  <tr><td>Next check</td><td>{nextPollSeconds ? `${nextPollSeconds}s` : "n/a"}</td></tr>
                  <tr><td>State</td><td>{checking ? "checking" : pollStatus}</td></tr>
                </tbody>
              </table>
              {pollStatus === "pending" && (
                <button
                  className="button secondary"
                  disabled={checking}
                  type="button"
                  onClick={() => void checkAuth(deviceAuth)}
                >
                  {checking ? "Checking" : "Check now"}
                </button>
              )}
            </>
          )}
        </div>
      </section>
    </Shell>
  );
}
