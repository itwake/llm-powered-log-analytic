"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { authApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { safeNextPath } from "@/lib/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [emailOrUsername, setEmailOrUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authApi.login({email_or_username: emailOrUsername, password});
      router.replace(safeNextPath(window.location.search));
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="panel auth-card" onSubmit={submit}>
        <h1>Sign in</h1>
        {error && <div className="alert error">{error}</div>}
        <label className="field">
          Email or username
          <input
            autoComplete="username"
            required
            value={emailOrUsername}
            onChange={(event) => setEmailOrUsername(event.target.value)}
          />
        </label>
        <label className="field">
          Password
          <input
            autoComplete="current-password"
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <div className="form-actions">
          <button className="button" disabled={submitting} type="submit">
            {submitting ? "Signing in" : "Sign in"}
          </button>
          <Link href="/register">Register</Link>
        </div>
      </form>
    </main>
  );
}
