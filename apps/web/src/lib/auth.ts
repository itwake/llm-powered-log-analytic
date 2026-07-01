const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export function buildSsoLoginUrl(nextPath = "/cases"): string {
  const safeNextPath = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/cases";
  const query = new URLSearchParams({next: safeNextPath}).toString();
  return API_BASE_URL ? `${API_BASE_URL}/api/auth/sso/login?${query}` : `/api/auth/sso/login?${query}`;
}

