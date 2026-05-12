# CADialogue Dashboard

A team-friendly dashboard for **CADialogue.in** — automatically discover finance
news topics, generate full SEO-optimised articles with GPT-4o, attach real
photos from Pexels, and publish to WordPress in one click.

## Features

- 🗞 **Auto topic discovery** — pulls 10 ranked finance topics from NewsAPI every morning, scored by GPT-4o-mini
- ✍ **Full article generation** — GPT-4o writes 1,500–2,000 word SEO articles with FAQ and schema markup
- 🖼 **Real stock photos** — Pexels integration: pick from 3M+ professional photos per article section
- 🔄 **One-click publish** — direct WordPress REST API integration with featured image, alt text, and JSON-LD schema
- 👥 **Multi-user** — NextAuth credentials with bcrypt; editor / admin roles
- 📚 **Topic library** — 14 finance categories, manual add, "promote to today's queue"
- 💾 **Persistent state** — runs, batches, topics, and images survive restarts

## Stack

| Layer       | Tech                                             |
| ----------- | ------------------------------------------------ |
| Frontend    | Next.js 16 (App Router), Tailwind, NextAuth v5  |
| Backend     | FastAPI sidecar (Python 3.12)                    |
| AI          | OpenAI GPT-4o (primary) + Gemini 2.5 (fallback) |
| Photos      | Pexels API                                       |
| Publishing  | WordPress REST API                               |
| State       | JSON files (filelock + bcrypt for auth)         |

## Local development

```bash
cp .env.example .env       # fill in your keys
npm install
pip install -r pipeline/requirements.txt
npm run dev                # starts Next.js + FastAPI together
```

Open http://localhost:3000

## Deployment

See **[DEPLOYMENT.md](./DEPLOYMENT.md)** for step-by-step instructions to deploy
to Render with a custom domain (`dashboard.cadialogue.in`).

Total deploy time: ~15 minutes.
Monthly cost: ~$7 (Render Starter) + GPT-4o usage.
