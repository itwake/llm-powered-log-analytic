import Link from "next/link";

export default function LoginPage() {
  return (
    <main className="main">
      <section className="panel" style={{maxWidth: 420}}>
        <h1>Sign in</h1>
        <label className="field">Email or username<input defaultValue="engineer@example.com" /></label>
        <label className="field">Password<input type="password" defaultValue="password123" /></label>
        <Link className="button" href="/cases">Sign in</Link>
        <p className="muted">Need access? Register an engineer account.</p>
      </section>
    </main>
  );
}
