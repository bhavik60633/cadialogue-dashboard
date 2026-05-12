import Link from "next/link"
import { auth, signOut } from "@/lib/auth"
import { redirect } from "next/navigation"
import { DashboardNav } from "@/components/dashboard/DashboardNav"

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const session = await auth()
  if (!session?.user) redirect("/login")

  const user = session.user as { name?: string; email?: string; role?: string }
  const initials = (user.name ?? user.email ?? "U")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <div
      className="min-h-screen text-white"
      style={{
        backgroundColor: "#09090b",
        backgroundImage:
          "radial-gradient(ellipse 80% 40% at 50% -10%, rgba(220,38,38,0.07), transparent)",
      }}
    >
      {/* ── Top nav ───────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-neutral-800/50 bg-[#09090b]/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-5 h-14 flex items-center gap-6">

          {/* Brand */}
          <Link
            href="/dashboard"
            className="shrink-0 text-[15px] font-black tracking-tight select-none"
          >
            <span className="text-red-500">CA</span>
            <span className="text-neutral-100">Dialogue</span>
          </Link>

          {/* Separator */}
          <span className="h-4 w-px bg-neutral-800 shrink-0" aria-hidden />

          {/* Navigation (client — needs usePathname) */}
          <DashboardNav />

          {/* Right side */}
          <div className="ml-auto flex items-center gap-3">
            {/* Status pill */}
            <span className="hidden lg:flex items-center gap-1.5 text-[11px] text-neutral-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Auto-runs 7 AM IST
            </span>

            {/* Divider */}
            <span className="hidden lg:block h-4 w-px bg-neutral-800" aria-hidden />

            {/* Avatar + role */}
            <div className="flex items-center gap-2.5">
              <div className="h-7 w-7 rounded-full bg-neutral-800 border border-neutral-700 flex items-center justify-center text-[11px] font-semibold text-neutral-300 select-none">
                {initials}
              </div>
              <div className="hidden sm:block text-[12px] leading-tight">
                <p className="text-neutral-300 font-medium">{user.name ?? user.email}</p>
                {user.role === "admin" && (
                  <p className="text-red-500/80 text-[10px] uppercase tracking-widest font-semibold">
                    Admin
                  </p>
                )}
              </div>
            </div>

            {/* Sign out */}
            <form
              action={async () => {
                "use server"
                await signOut({ redirectTo: "/login" })
              }}
            >
              <button
                type="submit"
                className="h-7 px-2.5 rounded-md text-[12px] text-neutral-500 hover:text-neutral-300 border border-neutral-800/80 hover:border-neutral-700 bg-transparent hover:bg-neutral-900/60 transition-all cursor-pointer"
              >
                Sign out
              </button>
            </form>
          </div>
        </div>
      </header>

      {/* ── Page content ──────────────────────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-5 py-8">
        {children}
      </main>
    </div>
  )
}
