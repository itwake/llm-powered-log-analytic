import Link from "next/link";

export default function RegisterPage() {
  return (
    <main className="main">
      <section className="panel" style={{maxWidth: 480}}>
        <h1>Register</h1>
        <label className="field">Email<input defaultValue="engineer@example.com" /></label>
        <label className="field">Username<input defaultValue="engineer" /></label>
        <label className="field">Full name<input defaultValue="LogAn Engineer" /></label>
        <label className="field">Password<input type="password" defaultValue="password123" /></label>
        <Link className="button" href="/cases">Create account</Link>
      </section>
    </main>
  );
}
