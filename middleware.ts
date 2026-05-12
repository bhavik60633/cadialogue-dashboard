/**
 * Next.js middleware — runs in Edge Runtime.
 * - /api/py/* → 401 JSON when unauthenticated (API clients should not get HTML redirects)
 * - /dashboard/* → redirect to /login when unauthenticated
 */
import NextAuth from "next-auth"
import { authConfig } from "@/lib/auth.config"
import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

const { auth } = NextAuth(authConfig)

export default auth((req: NextRequest & { auth: unknown }) => {
  const isAuthenticated = !!(req as { auth?: { user?: unknown } }).auth?.user

  if (!isAuthenticated) {
    if (req.nextUrl.pathname.startsWith("/api/py")) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
    }
    // Dashboard pages → redirect to login
    const loginUrl = new URL("/login", req.nextUrl)
    loginUrl.searchParams.set("callbackUrl", req.nextUrl.pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
})

export const config = {
  matcher: ["/dashboard/:path*", "/api/py/:path*"],
}
