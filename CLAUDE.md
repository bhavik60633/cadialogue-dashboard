# CADialogue — Project Documentation
**Last Updated:** May 7, 2026  
**Maintained by:** Claude (Anthropic) — update this file after every session change.

---

## 1. Why This Website Was Made

**CADialogue** (cadialogue.in) was created as **India's trusted finance news and analysis platform**. The goal is to serve Indian retail investors, salaried professionals, CAs, finance students, and business owners with:

- Real-time market data (Nifty, Sensex, Gold, Crude, Bitcoin, USD/INR)
- Accurate news articles on markets, economy, banking, taxation, and personal finance
- SEO-optimised content that ranks on Google for finance keywords in India
- A clean, professional news-portal design that builds reader trust

The site fills a gap between dry CA-exam content (the old cadialogue.in) and premium paywalled finance media — providing free, accurate, timely coverage for the Indian finance audience.

---

## 2. Purpose & Mission

| Goal | Description |
|---|---|
| **Primary** | India's go-to free finance news portal — Nifty / Gold / Economy / Tax / MF |
| **Audience** | Retail investors, CAs, salaried professionals, finance students |
| **Revenue model** | Display ads, sponsored content, newsletter (future: premium subscription) |
| **Differentiation** | Live market prices embedded directly in the homepage; branded article design |
| **Long-term** | Rank on Google for high-volume finance keywords (e.g. "gold price today India", "nifty 50 live") |

---

## 3. Color Theme & Design System

### Primary Palette
| Token | Hex | Usage |
|---|---|---|
| `--red` | `#C0392B` | Primary brand color — nav border, tags, buttons, CTAs |
| `--red-l` | `#E74C3C` | Hover state for red elements |
| `--red-d` | `#96281B` | Pressed/active state |
| `--dark` | `#111` / `#1a1a1a` | Nav bar background, headings |
| `--white` | `#FFFFFF` | Page background, cards |
| `--green` | `#1a7a3c` | Positive price change (▲) |
| `--gold` | `#B7950B` | Accent for commodities |
| `--muted` | `#666` / `#888` | Secondary text, metadata |
| `--border` | `#e2e2e2` | Card borders, dividers |

### Typography
| Font | Usage | Weight |
|---|---|---|
| **Merriweather** (homepage) | H1, H2, article titles | 700, 900 |
| **Playfair Display** (article/category pages) | H1, H2, article titles | 700, 900 |
| **Inter** | Body text, nav, metadata, UI | 400, 500, 600, 700 |

### Design Style
- **News portal / editorial** — inspired by The Hindu, Mint, Economic Times
- White background, dark nav bar (#111), red accent throughout
- Cards with 1px border and subtle hover shadow
- Ticker bar: scrolling live prices with red "LIVE MARKETS" label
- Category tags: red background, white uppercase text, small caps

---

## 4. How the Website Was Built

### Architecture
```
WordPress (cadialogue.in, Hostinger)
  └── mu-plugin: cadialogue-homepage.php
        ├── PHP proxy (/?cad_proxy=SYMBOL) — Yahoo Finance server-side fetch
        ├── template_redirect (priority 8) — Category / Archive / Search / 404 pages
        ├── template_redirect (priority 9) — Single posts and inner pages
        └── template_redirect (priority 10) — Homepage (front page)
```

### Key Technology Decisions
| Decision | Reason |
|---|---|
| **mu-plugin (must-use plugin)** | Loads on every page automatically without being deactivatable |
| **template_redirect hook** | Bypasses WordPress/Elementor theme entirely, serving pure HTML |
| **Server-side Yahoo Finance proxy** | CORS prevents direct browser fetch from live domain; PHP `wp_remote_get()` has no CORS restriction |
| **Inline CSS/JS** | No external stylesheets needed; everything self-contained in one file |
| **localStorage cache (15 min TTL)** | Respects free-tier API rate limits |
| **India premium multipliers** | Metal Price API returns London spot; Indian MCX price = spot × 1.085 (gold) / × 1.145 (silver) |
| **3 template_redirect hooks (priorities 8, 9, 10)** | Single mu-plugin file handles ALL page types with one consistent design |

### APIs Used
| API | Used For | Key |
|---|---|---|
| ExchangeRate-API | USD/INR live rate | `b931d4dbb14c6ff58a85d922` |
| Metal Price API | Gold & Silver spot prices (international) | `d8ddfb60f31763d26ee4ebc670688592` |
| CoinGecko (public) | Bitcoin price | No key needed |
| Alpha Vantage | Crude oil (WTI) | `RIZEDJVO1ZLGU08M` |
| Yahoo Finance (via server proxy) | Nifty 50, Sensex, Bank Nifty, Midcap, Indian stocks | No key — server-side proxy |

### WordPress Setup
- **Page ID 1842** — Front page (contains homepage HTML as backup/sync)
- **Page template:** `elementor_canvas` (blank, no theme header/footer)
- **REST API:** Used to create posts and update page content
- **Credentials stored in:** `.env` file (local only, NOT committed to git)

### File Locations
```
C:\Users\PC\OneDrive\Desktop\Prototype\
  ├── homepage-design\
  │   └── cadialogue-homepage.php   ← THE MAIN FILE (mu-plugin)
  ├── .env                          ← API keys and WP credentials
  └── CLAUDE.md                     ← This file
```

**Hostinger deployment path:**
`public_html/wp-content/mu-plugins/cadialogue-homepage.php`

---

## 5. Template Structure (cadialogue-homepage.php)

### Priority 8 — Category/Archive/Search/404 Template
- Handles: `is_category()`, `is_archive()`, `is_search()`, `is_404()`
- Shows: branded dark banner with category name, 2-column post grid with thumbnails, pagination, sidebar
- CSS classes: `.arch-*`, `.post-card`, `.pc-*`, `.c-sw`, `.c-tr-*`, `.c-nav-*`

### Priority 9 — Single Post / Page Template
- Handles: `is_single()`, `is_page() && !is_front_page()`
- Shows: category breadcrumb, H1 title, excerpt, author/date, share buttons, featured image, article body, sidebar
- CSS classes: `.art-*`, `.a-nav-*`, `.a-sw`, `.a-tr-*`
- SEO: Full OG tags, Twitter Cards, JSON-LD NewsArticle schema, canonical URL

### Priority 10 (default) — Homepage
- Handles: `is_front_page()`
- Shows: live ticker bar, breaking news scroller, hero article grid, market snapshot tiles (live), latest news grid, personal finance section, opinion cards, video/podcast grid, sidebar
- CSS classes: `.hero-*`, `.mkt-*`, `.news-*`, `.sidebar`, `.sw`, `.ticker-*`
- SEO: OG tags, Organization JSON-LD schema

---

## 6. Live Market Data Engine

### Data Flow
```
Browser → ExchangeRate-API (USD/INR)
        → Metal Price API (Gold oz, Silver oz)
        → CoinGecko (Bitcoin USD)
        → Alpha Vantage (Crude WTI)
        → WordPress server (/?cad_proxy=SYMBOL) → Yahoo Finance (Nifty/Sensex/etc.)
```

### India Commodity Price Calculation
```javascript
// International spot → Indian MCX approximate price
var INDIA_GOLD_PREMIUM   = 1.085;  // 15% customs + 3% GST ≈ 8.5% net on INR
var INDIA_SILVER_PREMIUM = 1.145;  // Same structure, slightly higher

goldINR   = (goldUSD_per_oz / 31.1035 * 10) * usdInr * INDIA_GOLD_PREMIUM;   // per 10g
silverINR = (silverUSD_per_oz / 31.1035 * 1000) * usdInr * INDIA_SILVER_PREMIUM; // per kg
```

### Proxy Rate Limiting
- Max 120 requests per IP per minute (enforced via WordPress transients)
- Symbol whitelist: `^BSESN`, `^NSEI`, `^NSEBANK`, `^CNXMIDCAP`, `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `INFY.NS`
- Returns 429 if rate exceeded, 403 if symbol not in whitelist

---

## 7. WordPress Posts Created

| ID | Slug | Title | Category |
|---|---|---|---|
| 2344 | `nifty-24000-dii-fii-may-2026` | Nifty Holds 24,000 as DIIs Counter FII Selling | Markets |
| 2345 | `india-inflation-march-2026-rbi-policy` | India CPI Inflation Falls to 3.34% in April 2026 | Economy |
| 2346 | `gold-price-150000-may-2026` | Gold at Rs 1,50,000/10g: MCX Rally | Markets |
| 2347 | `sbi-q4-fy26-results-preview` | SBI Q4 FY26 Results: Net Profit & NPA | Banking |
| 2348 | `itr-filing-2026-new-tax-regime-ay2026-27` | ITR Filing 2026: New Tax Slabs | Tax & GST |
| 2349 | `sip-inflows-record-32087-crore-march-2026` | SIP Inflows Hit Record Rs 32,087 Cr | Mutual Funds |
| 2350 | `mumbai-property-registrations-april-2026` | Mumbai Property Registrations April 2026 | Real Estate |
| 2351 | `silver-price-260000-mcx-may-2026` | Silver Crosses Rs 2,60,000/kg MCX | Markets |

---

## 8. WordPress Categories (in use)

| Slug | Display Name |
|---|---|
| `markets` | Markets |
| `economy` | Economy |
| `banking` | Banking |
| `personal-finance` | Personal Finance |
| `mutual-funds` | Mutual Funds |
| `tax-gst` | Tax & GST |
| `real-estate` | Real Estate |
| `startups` | Startups |
| `crypto` | Crypto |
| `opinion` | Opinion |

---

## 9. SEO Strategy

### What's Implemented
- `<meta name="description">` on every page
- Canonical URL (`<link rel="canonical">`) on articles and homepage
- Open Graph tags (og:title, og:description, og:type, og:image, og:url) on all pages
- Twitter Card tags (summary_large_image) on all pages
- **JSON-LD structured data:**
  - Homepage: `NewsMediaOrganization` schema
  - Articles: `NewsArticle` schema with author, publisher logo, dates
- Logo image shown in header (pulls from WordPress media library)
- Favicon set to cropped CADialogue logo
- Site icon ID 1833 in WordPress

### What Still Needs To Be Done
- [ ] Submit sitemap to Google Search Console (`/sitemap_index.xml`)
- [ ] Create Google Search Console account and verify ownership
- [ ] Add RankMath SEO plugin focus keywords to each post
- [ ] Build internal linking between articles
- [ ] Write 500+ word posts (current ones are 400-600 words — aim for 800+)
- [ ] Add alt text to all images in posts
- [ ] Create category landing pages with unique descriptions
- [ ] Publish 3-5 articles per week consistently
- [ ] Build backlinks from finance directories and PR articles

---

## 10. Security Measures

### Implemented
- HTTP security headers via `send_headers` hook:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- Proxy endpoint: symbol whitelist prevents arbitrary URL fetching
- Rate limiting: 120 requests/IP/minute via WordPress transients
- `sanitize_text_field()` on all user inputs
- `esc_html()`, `esc_url()`, `esc_attr()`, `esc_js()` on all PHP outputs

### Remaining Vulnerabilities to Address
- [ ] HTTPS certificate — verify auto-renewal on Hostinger
- [ ] WordPress core, plugins, themes — keep updated
- [ ] `.env` file — ensure it is NOT accessible via browser (`/Prototype/.env` should not be web-accessible; it's a local file, not in `public_html`)
- [ ] WP Application Password (`xxxx xxxx xxxx xxxx xxxx xxxx`) — rotate periodically
- [ ] Consider adding Cloudflare (free tier) for DDoS protection and WAF
- [ ] LiteSpeed Cache — ensure cache is cleared after each deployment
- [ ] No SQL injection risk (no raw queries in mu-plugin)
- [ ] Content Security Policy (CSP) — currently not set; add when ready

---

## 11. Future Plans

### Phase 2 (Next 1-3 months)
- [ ] Add author profile pages (CA professionals as columnists)
- [ ] Implement full-text search (SearchWP or Relevanssi plugin)
- [ ] Newsletter signup connected to Mailchimp / ConvertKit
- [ ] Comments on articles (Disqus or native WP)
- [ ] Stock/company profile pages (e.g. `/stocks/reliance/`, `/stocks/tcs/`)
- [ ] Live Nifty chart embedded in market snapshot section

### Phase 3 (3-6 months)
- [ ] Premium subscription tier (₹99/month) — exclusive analysis
- [ ] Mobile app (React Native or PWA)
- [ ] Portfolio tracker for registered users
- [ ] Email alerts for price thresholds (Gold, Nifty, etc.)

### SEO / Content Phase
- [ ] Publish daily market summary articles (automated via Python + Claude API)
- [ ] Weekly economy roundup
- [ ] Monthly IPO calendar
- [ ] Quarterly company results analysis

---

## 12. Deployment Procedure

Every time `cadialogue-homepage.php` is updated:

1. Make changes in: `C:\Users\PC\OneDrive\Desktop\Prototype\homepage-design\cadialogue-homepage.php`
2. Push to WordPress page 1842 via PowerShell REST API (for sync):
   ```powershell
   # See push commands in conversation history
   ```
3. **Upload to Hostinger** → File Manager → `public_html/wp-content/mu-plugins/` → overwrite `cadialogue-homepage.php`
4. Clear LiteSpeed Cache: WordPress Admin → LiteSpeed Cache → Purge All
5. Test at `https://cadialogue.in/?nocache=[timestamp]`

---

## 13. Change Log

| Date | Change |
|---|---|
| May 2026 | Initial homepage build — live market data (ExchangeRate-API, Metal Price API, CoinGecko, Alpha Vantage) |
| May 2026 | Built PHP server-side proxy (`/?cad_proxy=SYMBOL`) to bypass CORS for Yahoo Finance |
| May 2026 | Added India commodity price premiums (gold ×1.085, silver ×1.145) |
| May 2026 | Created 10-category nav with CSS dropdown menus (desktop hover) + mobile accordion |
| May 2026 | Created 8 WordPress posts with researched accurate data |
| May 2026 | Added custom single-post template (priority 9) — branded article page with OG/schema SEO |
| May 2026 | Added category/archive/search/404 template (priority 8) — branded post grid pages |
| May 2026 | Fixed CSS `content:'\25BC'` (arrows were rendering as raw `&#9660;`) |
| May 2026 | Fixed `.nav-links { overflow:visible }` — was clipping dropdown menus |
| May 2026 | Fixed all 7 article slugs to match actual WordPress-generated slugs |
| May 2026 | Added CADialogue logo image to all three template headers |
| May 2026 | Added favicon, OG tags, Twitter Cards, JSON-LD schema to all pages |
| May 2026 | Security: added X-Frame-Options, X-XSS-Protection, rate limiting on proxy |
| May 2026 | Fixed all `href="#"` links — social media, footer nav, privacy, terms, sitemap |
| May 7, 2026 | **Full site verification:** homepage ✓, nav dropdowns ✓, article pages ✓, category pages ✓ — all using branded white/black/red design |
| May 7, 2026 | Corrected static Crude Oil value in article + category sidebars ($99.89 → $82.14) — both `.c-com-tbl` and `.a-com-tbl` widgets updated |
| May 7, 2026 | Removed logo `<img>` from all three template headers — text logo only in header; logo image kept in JSON-LD schema + OG tags for Google indexing |
| May 7, 2026 | **Mobile fix (article + category templates):** added `overflow-x:hidden` on `html/body`, `overflow-x:auto` on tables, `flex-wrap` on share buttons, responsive font sizes (24px h1, 16px body), hidden Subscribe button on mobile; added hamburger menu + slide-in drawer (280px) with JS toggle for both templates |
| May 7, 2026 | **Search bar activated** — all 3 template headers: `<div>` → `<form action="/" method="get">`, input `name="s"`, button `type="submit"`; uses WordPress native `/?s=query` search |

---

## 14. Key URLs

| URL | Purpose |
|---|---|
| `https://cadialogue.in/` | Homepage |
| `https://cadialogue.in/wp-admin/` | WordPress admin |
| `https://cadialogue.in/wp-json/wp/v2/posts` | REST API — posts |
| `https://cadialogue.in/wp-json/wp/v2/pages/1842` | REST API — homepage page |
| `https://cadialogue.in/?cad_proxy=^NSEI` | Yahoo Finance proxy (server-side) |
| `https://cadialogue.in/sitemap_index.xml` | XML sitemap |
| `https://cadialogue.in/wp-content/uploads/2025/11/CA-Dialogue-logo-large.jpg` | Main logo image |
| `https://cadialogue.in/wp-content/uploads/2025/11/cropped-CA-Dialogue-small.jpg` | Favicon / site icon |

---

*Update this file after every session. Never delete this file — it is the single source of truth for this project.*
