/**
 * Next.js server-side proxy → FastAPI sidecar on 127.0.0.1:8765.
 *
 * Every request is:
 *   1. Session-checked via NextAuth (returns 401 if unauthenticated)
 *   2. Forwarded to FastAPI with the service bearer token injected
 *   3. SSE streams are piped through transparently
 */
import { auth } from "@/lib/auth"
import { NextRequest, NextResponse } from "next/server"

const FASTAPI_BASE = "http://127.0.0.1:8765"
const SERVICE_TOKEN = process.env.PIPELINE_SERVICE_TOKEN ?? ""

async function proxy(
  req: NextRequest,
  path: string[]
): Promise<Response> {
  // Gate: require a valid session
  const session = await auth()
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const upstream = `${FASTAPI_BASE}/${path.join("/")}${
    req.nextUrl.search ? req.nextUrl.search : ""
  }`

  // Build forwarded headers — strip Host, inject Bearer token
  const headers = new Headers()
  for (const [key, value] of req.headers.entries()) {
    if (key.toLowerCase() === "host") continue
    headers.set(key, value)
  }
  headers.set("Authorization", `Bearer ${SERVICE_TOKEN}`)

  let body: BodyInit | undefined
  if (req.method !== "GET" && req.method !== "HEAD") {
    const ct = req.headers.get("content-type") ?? ""
    // Stream binary bodies (file uploads) directly; read text for JSON/form
    if (ct.includes("multipart/form-data") || ct.includes("application/octet-stream")) {
      body = req.body ?? undefined
    } else {
      body = await req.text()
    }
  }

  try {
    const upstreamRes = await fetch(upstream, {
      method: req.method,
      headers,
      body,
    })

    // Pipe SSE streams straight through
    if (upstreamRes.headers.get("content-type")?.includes("text/event-stream")) {
      return new Response(upstreamRes.body, {
        status: upstreamRes.status,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
        },
      })
    }

    // Normal JSON responses
    const data = await upstreamRes.text()
    return new Response(data, {
      status: upstreamRes.status,
      headers: { "Content-Type": upstreamRes.headers.get("content-type") ?? "application/json" },
    })
  } catch {
    return NextResponse.json(
      { error: "Pipeline service unavailable — is uvicorn running?" },
      { status: 503 }
    )
  }
}

// Next.js 15+ route params are Promises
type RouteContext = { params: Promise<{ path: string[] }> }

export async function GET(req: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function PUT(req: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function PATCH(req: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function DELETE(req: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params
  return proxy(req, path)
}
