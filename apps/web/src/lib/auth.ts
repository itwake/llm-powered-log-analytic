const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

export function buildLoginUrl(nextPath = "/cases"): string {
  const safeNextPath = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/cases";
  const query = new URLSearchParams({next: safeNextPath}).toString();
  return `${API_BASE_URL}/api/auth/login?${query}`;
}

