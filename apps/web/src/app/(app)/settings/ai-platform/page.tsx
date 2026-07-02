"use client";

import { useEffect, useState } from "react";
import { capabilitiesApi, CapabilitiesResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

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
    <>
      <div className="toolbar">
        <h1>AI Platform</h1>
      </div>

      {error && <div className="alert error">{error}</div>}

      <section className="grid two">
        <div className="panel">
          <h2>Runtime</h2>
          {loading && <div className="empty">Checking model runtime</div>}
          {!loading && capabilities && (
            <table>
              <tbody>
                <tr>
                  <td>Provider</td>
                  <td>{providerLabel(capabilities.models.provider)}</td>
                </tr>
                <tr>
                  <td>Default model</td>
                  <td>{capabilities.models.default_model}</td>
                </tr>
                <tr>
                  <td>Status</td>
                  <td>
                    <span className={`pill ${capabilities.models.provider === "ai_platform" ? "green" : "amber"}`}>
                      {capabilities.models.provider === "ai_platform" ? "configured" : "check configuration"}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2>Model Surface</h2>
          {loading && <div className="empty">Loading capabilities</div>}
          {!loading && capabilities && (
            <table>
              <tbody>
                <tr>
                  <td>Supported models</td>
                  <td>{capabilities.models.supported_models.join(", ")}</td>
                </tr>
                <tr>
                  <td>Views</td>
                  <td>{capabilities.views.join(", ")}</td>
                </tr>
                <tr>
                  <td>Uploads</td>
                  <td>{capabilities.upload.supported_extensions.join(", ")}</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </section>
    </>
  );
}
