"use client"

import { signIn } from "next-auth/react"
import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"

export default function LoginPage() {
  const router = useRouter()
  const [error, setError] = useState("")
  const [isPending, startTransition] = useTransition()

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    setError("")

    startTransition(async () => {
      const result = await signIn("credentials", {
        email: fd.get("email") as string,
        password: fd.get("password") as string,
        redirect: false,
      })
      if (result?.error) {
        setError("Invalid email or password.")
      } else {
        router.push("/dashboard/queue")
        router.refresh()
      }
    })
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{
        backgroundColor: "#09090b",
        backgroundImage: [
          "radial-gradient(ellipse 60% 50% at 50% -20%, rgba(220,38,38,0.09), transparent)",
          "radial-gradient(ellipse 40% 40% at 50% 110%, rgba(255,255,255,0.02), transparent)",
        ].join(", "),
      }}
    >
      <div className="w-full max-w-[360px]">

        {/* ── Brand ── */}
        <div className="mb-8 text-center">
          <a
            href="https://cadialogue.in"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block"
          >
            <span className="text-[26px] font-black tracking-tight">
              <span className="text-red-500">CA</span>
              <span className="text-neutral-100">Dialogue</span>
            </span>
          </a>
          <p className="mt-2 text-[13px] text-neutral-600">
            Content team dashboard
          </p>
        </div>

        {/* ── Card ── */}
        <div className="rounded-2xl border border-neutral-800/60 bg-neutral-900/50 p-7 shadow-2xl backdrop-blur-sm">

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Email */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="block text-[11px] font-semibold uppercase tracking-widest text-neutral-500"
              >
                Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                placeholder="you@cadialogue.in"
                className="
                  w-full rounded-lg border border-neutral-800 bg-neutral-950/60 px-3.5 py-2.5
                  text-[13px] text-neutral-100 placeholder-neutral-700
                  focus:outline-none focus:border-red-600/60 focus:ring-2 focus:ring-red-600/20
                  transition-all duration-150
                "
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-[11px] font-semibold uppercase tracking-widest text-neutral-500"
              >
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                placeholder="••••••••"
                className="
                  w-full rounded-lg border border-neutral-800 bg-neutral-950/60 px-3.5 py-2.5
                  text-[13px] text-neutral-100 placeholder-neutral-700
                  focus:outline-none focus:border-red-600/60 focus:ring-2 focus:ring-red-600/20
                  transition-all duration-150
                "
              />
            </div>

            {/* Error */}
            {error && (
              <div
                className="flex items-center gap-2.5 rounded-lg border border-red-900/40 bg-red-950/40 px-3.5 py-2.5"
                role="alert"
              >
                <svg className="h-3.5 w-3.5 shrink-0 text-red-500" viewBox="0 0 16 16" fill="currentColor">
                  <path fillRule="evenodd" d="M8 15A7 7 0 108 1a7 7 0 000 14zm.75-10.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5zm-.75 6a.875.875 0 100-1.75.875.875 0 000 1.75z" />
                </svg>
                <p className="text-[12px] text-red-400">{error}</p>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={isPending}
              className="
                w-full mt-2 flex items-center justify-center gap-2 rounded-lg
                bg-red-600 hover:bg-red-500 active:bg-red-700
                disabled:opacity-60 disabled:cursor-not-allowed
                py-2.5 text-[13px] font-semibold text-white
                transition-all duration-150 cursor-pointer
                focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500
              "
            >
              {isPending ? (
                <>
                  <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>
          </form>
        </div>

        {/* ── Footer ── */}
        <p className="mt-5 text-center text-[11px] text-neutral-700">
          New team member?{" "}
          <span className="text-neutral-600">
            Ask admin to run <code className="font-mono text-neutral-500">add_user.py</code>
          </span>
        </p>
      </div>
    </div>
  )
}
