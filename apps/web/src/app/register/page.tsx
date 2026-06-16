"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { authApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { safeNextPath } from "@/lib/navigation";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authApi.register({
        email,
        username,
        full_name: fullName || null,
        password,
      });
      await authApi.login({email_or_username: username, password});
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
        <h1>Register</h1>
        {error && <div className="alert error">{error}</div>}
        <label className="field">
          Email
          <input
            autoComplete="email"
            required
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="field">
          Username
          <input
            autoComplete="username"
            minLength={2}
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          Full name
          <input
            autoComplete="name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </label>
        <label className="field">
          Password
          <input
            autoComplete="new-password"
            minLength={8}
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <div className="form-actions">
          <button className="button" disabled={submitting} type="submit">
            {submitting ? "Creating account" : "Create account"}
          </button>
          <Link href="/login">Sign in</Link>
        </div>
      </form>
    </main>
  );
}
