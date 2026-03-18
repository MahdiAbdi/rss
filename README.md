# RSS — Telegram + Websites → GitHub Pages

Fetches content from public Telegram channels and websites (RSS/HTML) and publishes a unified feed to this repo. A static GitHub Pages site lets you read the feed when other sites are unreachable.

**No Telegram API key or login required.** Public channels are read via `t.me/s/<channel>`.

## Setup

### 1. Add your sources

Edit `sources.yaml` in the repo root:

```yaml
telegram:
  - durov
  - your_channel_name   # username only, no @ or t.me

websites:
  - url: https://example.com/feed.xml
    type: rss
  - url: https://news.site/page
    type: html
    selector: "article"   # optional CSS selector for item links
```

- **Telegram**: list channel usernames, or use a dict for options:
  - Simple: `- durov` (fetches one page, up to 50 items).
  - Full fetch (incremental): use `name`, `full_fetch: true`, and optional `max_items: 100`. Each run fetches only new items since last run and merges with previous items, keeping at most `max_items` (cap 100).
- **Websites**: `type: rss` for RSS/Atom feeds; `type: html` for a normal page (optional `selector` for the element that wraps each link).

The Pages UI includes **Filter by source** chips (All + one per source) and a reader that shows full article content when you open an item.

### 2. Enable GitHub Pages

1. In the repo: **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. **Branch**: `main`, **Folder**: `/docs`.
4. Save. The site will be at `https://<username>.github.io/<repo>/`.

### 3. Run the fetcher

- **Automatic**: the workflow runs every 30 minutes (`*/30 * * * *`).
- **Manual**: **Actions → Fetch and publish → Run workflow**.

After the first successful run, `docs/data/feed.json` is updated and the Pages site shows the feed.

## How it works

- **`.github/workflows/fetch-and-publish.yml`**: On schedule or manual run, installs Python deps (with cache), runs `scripts/fetch.py`, then commits and pushes only if `docs/data/feed.json` changed.
- **`scripts/fetch.py`**: Reads `sources.yaml`, fetches each Telegram channel (t.me/s) and website (RSS or HTML), merges into one JSON, writes `docs/data/feed.json`.
- **`docs/`**: Static `index.html` + `app.js` load `data/feed.json` and render it. No build step.

## Cost

- **Public repo**: GitHub Actions and Pages are free.
- **Private repo**: 2,000 Actions minutes/month on Free plan; overage is billed. Run less often or use a public repo to avoid cost.

## No Actions or Pages?

- **Actions tab empty or no workflow?**  
  Repo **Settings → Actions → General** → set **Allow all actions and reusable workflows** (or at least allow this repo). Then go to **Actions**; you should see **Fetch and publish**. You can **Run workflow** manually.

- **Pages not loading?**  
  Pages do **not** turn on by themselves. Go to repo **Settings → Pages** → under **Build and deployment**, set **Source** to **Deploy from a branch** → **Branch**: `main`, **Folder**: `/docs` → Save. The site will be at `https://<username>.github.io/rss/` after a minute or two.
