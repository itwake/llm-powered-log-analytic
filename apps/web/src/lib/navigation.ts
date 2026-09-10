export function safeNextPath(search: string, fallback = "/cases"): string {
  const params = new URLSearchParams(search);
  const next = params.get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//")) {
    return fallback;
  }
  if (next === "/login" || next.startsWith("/login?")) {
    return fallback;
  }
  return next;
}
