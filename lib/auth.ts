/**
 * Full NextAuth v5 config — Node.js runtime only.
 * Imports bcryptjs and reads users.json from the filesystem.
 * Never import this file in Edge Runtime code (middleware.ts uses auth.config.ts).
 */
import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import bcrypt from "bcryptjs"
import fs from "fs"
import path from "path"
import { authConfig } from "./auth.config"

const USERS_FILE = path.join(process.cwd(), "pipeline", "state", "users.json")

interface StoredUser {
  email: string
  name: string
  bcrypt_hash: string
  role: "editor" | "admin"
  created_at: string
}

function loadUsers(): StoredUser[] {
  try {
    const raw = fs.readFileSync(USERS_FILE, "utf-8")
    return JSON.parse(raw) as StoredUser[]
  } catch {
    return []
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null

        const users = loadUsers()
        const user = users.find((u) => u.email === credentials.email)
        if (!user) return null

        const valid = await bcrypt.compare(
          credentials.password as string,
          user.bcrypt_hash
        )
        if (!valid) return null

        return {
          id: user.email,
          email: user.email,
          name: user.name,
          role: user.role,
        }
      },
    }),
  ],
  session: {
    strategy: "jwt",
    maxAge: 8 * 60 * 60,  // 8 hours
  },
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.role = (user as { role?: string }).role
      }
      return token
    },
    session({ session, token }) {
      if (session.user) {
        (session.user as { role?: string }).role = token.role as string
      }
      return session
    },
  },
})
