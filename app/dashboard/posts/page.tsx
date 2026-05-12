import Link from "next/link"
import { PostsManager } from "@/components/posts/PostsManager"

export default function PostsPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-neutral-100 tracking-tight">Posts</h1>
          <p className="mt-1 text-[13px] text-neutral-500">
            View, edit, and manage all articles published on cadialogue.in
          </p>
        </div>
        <Link
          href="/dashboard/posts/new"
          className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-4 py-2 text-[13px] font-semibold text-white transition-colors"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 3v10M3 8h10" />
          </svg>
          New Post
        </Link>
      </div>

      {/* Client-side posts manager */}
      <PostsManager />
    </div>
  )
}
