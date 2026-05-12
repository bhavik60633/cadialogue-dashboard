/**
 * Edge-compatible NextAuth config (no Node.js APIs like fs or bcrypt).
 * Used by middleware.ts which runs in the Edge Runtime.
 * The full config (with Credentials provider) lives in lib/auth.ts.
 */
import type { NextAuthConfig } from "next-auth"

export const authConfig: NextAuthConfig = {
  pages: {
    signIn: "/login",
  },
  providers: [],   // Providers are only needed in the Node.js runtime (lib/auth.ts)
  callbacks: {
    authorized({ auth, request }) {
      const isLoggedIn = !!auth?.user
      const isProtected =
        request.nextUrl.pathname.startsWith("/dashboard") ||
        request.nextUrl.pathname.startsWith("/api/py")

      if (isProtected && !isLoggedIn) return false
      return true
    },
  },
}
