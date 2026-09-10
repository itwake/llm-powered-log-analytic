import { API_BASE_URL } from "@/lib/api/http";

export function buildLoginUrl(nextPath = "/cases"): string {
  const safeNextPath = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/cases";
  const query = new URLSearchParams({next: safeNextPath}).toString();
  return `${API_BASE_URL}/api/auth/login?${query}`;
}

