"use client";

import { useEffect, useState } from "react";
import { buildSsoLoginUrl } from "@/lib/auth";
import { safeNextPath } from "@/lib/navigation";

export default function LoginPage() {
  const [ssoUrl, setSsoUrl] = useState(() => buildSsoLoginUrl("/cases"));

  useEffect(() => {
    const url = buildSsoLoginUrl(safeNextPath(window.location.search));
    setSsoUrl(url);
    window.location.replace(url);
  }, []);

  return (
    <main className="auth-page">
      <section className="panel auth-card">
        <h1>Continue with SSO</h1>
        <p>Redirecting to corporate sign-in for LogAn Platform access.</p>
        <p className="muted">
          LogAn only supports corporate single sign-on. Your account is provisioned automatically
          the first time you complete SSO.
        </p>
        <div className="form-actions">
          <a className="button" href={ssoUrl}>
            Continue with SSO
          </a>
        </div>
      </section>
    </main>
  );
}
