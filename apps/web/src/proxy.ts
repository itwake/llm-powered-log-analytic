import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = new Set(["/login", "/register", "/healthz"]);

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname);
}

function nextPathFor(pathname: string, search: string): string {
  if (pathname === "/") {
    return "/cases";
  }
  return `${pathname}${search}`;
}

export function proxy(request: NextRequest) {
  const {pathname, search} = request.nextUrl;
  if (isPublicPath(pathname) || request.cookies.has("logan_session")) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("next", nextPathFor(pathname, search));
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
