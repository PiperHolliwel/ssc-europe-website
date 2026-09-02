# ssc-europe-website

The ssc-europe.eu site, migrated off Jimdo/Webflow onto Cloudflare Pages.

## What's in this repo
- **The live site itself** at the repo root (`index.html`, `css/`, `js/`,
  `images/`, `en/`, plus every page folder) — this is what Cloudflare Pages
  currently deploys as-is, with no build step.
- **The source it's generated from**, kept alongside it: `webflow-export/`
  (the original Webflow export, used as page templates), `content/`
  (editable YAML — contact info and expert profiles), `cv-publications/`
  (recovered German CV/Publications text), and `build.py` (the generator
  that turns all of that into the pages at the repo root).
- **The content editor** (`admin_src/`, deploys to `/admin/`) and its OAuth
  helper (`cms-oauth-worker.js`) — see "Setting up the content editor" below
  to activate it. Until you do, it's inert and the site works exactly as it
  does today.

Bilingual: German at the root, English under `/en/`.

## Fixed in this pass (pre-launch cleanup)
- Footer links to Impressum/Datenschutz previously used bare hrefs
  (`/impressum`, no trailing slash) on every page, which didn't match the
  folder/index.html structure the rest of the site uses, and English pages
  linked to the German-only pages. Fixed: DE pages link to `/impressum/` and
  `/datenschutz/`; EN pages link to `/en/impressum/` and `/en/datenschutz/`.
- On English pages, the mobile/tablet hamburger menu opened but never
  animated into an "X". Root cause: the English header markup used the
  original `ssc-burger`/`ssc-burger-bar` classes, while the site's CSS
  animation rules only target the renamed `ssc-burger-1`/`ssc-burger-bar-1`
  classes (a rename only ever applied to the German header in Webflow).
  `build.py` now normalizes English pages to the same classes as German.
- Built `/impressum/`, `/en/impressum/`, `/datenschutz/`, and
  `/en/datenschutz/` (previously Datenschutz didn't exist in either
  language, and English had no Impressum). The German Impressum is
  reconstructed from facts recovered from the old Jimdo page; the
  Datenschutz pages are freshly drafted to describe the *current* stack
  (Cloudflare Pages hosting, Formspree contact form, no cookies/analytics/
  tracking). Both are flagged with a ⚠️ note on the page itself and should
  be reviewed by you/a lawyer before being treated as final — this is
  boilerplate, not legal advice.
- Judith Hartmann's expert profile linked to a "Publications" sub-page that
  was never generated (her publications are embedded in her CV instead).
  The sidebar-link logic now checks the same content extraction the
  page-generator itself uses, so a link only ever appears when that page
  actually exists.

## Content audit against the old Jimdo site
Before going live, I went page-by-page comparing everything still live on
the old Jimdo site (ssc-europe.eu, still up as of this pass) against what
made it into this build, specifically to catch anything that fell through
the cracks during the Webflow export step (which happened before I was
involved). Result:
- **Found and fixed a real gap**: a whole sub-section — "Pressemitteilungen"
  / "Press Releases" (SSC Europe's own 6 press releases from 2012-2013,
  linked from the bottom of the Presse/Press pages on the old site) — had
  never been carried into the Webflow export or any build since, so it
  didn't exist anywhere in the new site. Rebuilt at `/presse/pressemitteilungen/`
  and `/en/press/press-releases/`, linked from the bottom of the Presse/Press
  pages like the old site did. Text is reconstructed in substance from the
  original PDFs (not copy-pasted verbatim — flagged ⚠️ on the page). The
  original PDF *files* lived on Jimdo's own storage and can't be re-hosted
  here — if you want those specific PDFs still downloadable, they'd need
  pulling from the old site before it's decommissioned.
- **Found and fixed a small gap**: the Links/Kooperationspartner page had 3
  partner names quietly shortened somewhere before I got involved (dropped
  trailing words, e.g. "Bertelsmann Stiftung" instead of "Bertelsmann
  Stiftung - Europas Zukunft/ Europa und der Nahe Osten"). Restored to match
  the old site exactly, both languages.
- **Flagging, not yet resolved** — Formate/Formats pages ("Planspiele/
  Simulationen" section) reference a downloadable example presentation
  ("Präsentation_Angebot_FTT.pdf", an 11-slide deck on the Financial
  Transaction Tax simulation). I could only recover a coarse summary of it
  (not exact slide text/design), so rather than publish a lossy
  reconstruction under your name, I left the sentence out rather than link
  to something broken or wrong. If you still have the original file, send
  it over and I'll host it properly; otherwise I can either write a short
  from-scratch summary blurb or just leave it out — your call.
- **Flagging, minor** — the old Kontakt page listed a fax number
  (+49 (0)30 25 05 95 17) that isn't in the new site anywhere. Left out
  since fax is unusual to carry forward, but easy to add to
  `content/settings.yml` if you actually still use it.
- **Not content, cosmetic only** — the old site's Simulations page and
  homepage had a few captioned activity photos (conference panels, past
  workshops) that aren't in the new design. No text/facts were lost; this
  is a visual/design choice, not a gap. Can add if you want that back.
- Everything else — Über uns/About, Seminars, Simulations, Consulting,
  Formate/Formats' main text, the 14 partner links, Former Projects (all 8
  entries), the homepage welcome text, and all 8 Presse/Press media-mention
  items in both languages — checked and matches the old site in substance.
- Verified: 0 broken internal links/assets across all 68 generated pages.

## Still open
- Replace the Formspree placeholder form ID (in `webflow-export/kontakt.html`
  and `webflow-export/en/contact.html`) with your real Formspree form once
  you've created an account — search for `YOUR_FORM_ID`.
- Have the Impressum, Datenschutz, and Pressemitteilungen/Press Releases
  pages (DE + EN) reviewed/signed off.
- Decide on the FTT presentation PDF and fax number items above.
- Connect the live `ssc-europe.eu` domain to the Cloudflare Pages project.

Deploy target (as of today): Cloudflare Pages, root directory, no build
command. That changes if you activate the content editor below.

---

## Setting up the content editor

This lets you edit contact info (phone/address/email) and expert profiles
(bio, photo, expertise) from a web page at `yoursite.com/admin/`, without
touching code — each save commits straight to this GitHub repo, and
Cloudflare Pages rebuilds the site automatically within about a minute.

It's a git-based editor (Decap CMS), so there's no separate database or
account system — it edits the same repo you already have, using your
GitHub login.

**Do this in order.** Nothing here affects the live site until the last
step, so there's no risk of breaking anything partway through.

### 1. Update the Cloudflare Pages build settings
The site currently deploys with no build step (Cloudflare just serves the
repo as-is). To make the editor's changes actually regenerate the site, it
needs to run `build.py` on every push:

1. Cloudflare dashboard → Workers & Pages → your `ssc-europe-website`
   project → **Settings** → **Builds & deployments**.
2. Set **Build command** to:
   ```
   pip install -r requirements.txt && python3 build.py
   ```
3. Set **Build output directory** to:
   ```
   dist
   ```
4. Save.

(If a build fails for any reason, Cloudflare keeps the last working
deployment live — it doesn't take the site down — so this is safe to try.)

### 2. Create a GitHub OAuth App
This is what lets the editor log you in with your GitHub account (the same
way you already access this repo) instead of a separate password.

1. GitHub → **Settings** → **Developer settings** → **OAuth Apps** →
   **New OAuth App**.
2. **Application name**: anything, e.g. "SSC Europe content editor".
3. **Homepage URL**: `https://ssc-europe-website.olenababii-tests.workers.dev`
   (or your real domain once it's connected).
4. **Authorization callback URL**: you'll fill this in after step 3, once
   you know your Worker's URL — it'll be `https://<your-worker>.workers.dev/callback`.
   You can save a placeholder now and edit it after.
5. Click **Register application**, then **Generate a new client secret**.
   Keep this tab open — you'll need the **Client ID** and the **Client
   secret** in the next step.

### 3. Deploy the OAuth helper as a Cloudflare Worker
GitHub OAuth needs a small server-side piece to safely exchange your login
for an access token (the secret from step 2 can never sit in the browser).
`cms-oauth-worker.js` in this repo is that piece — about 100 lines, nothing
else required to deploy it.

1. Cloudflare dashboard → **Workers & Pages** → **Create** → **Workers** →
   **Create Worker**. Give it a name, e.g. `ssc-cms-auth`.
2. Once created, open it → **Edit code** (Quick Edit).
3. Delete the placeholder code and paste in the full contents of
   `cms-oauth-worker.js` from this repo. Click **Deploy**.
4. Note the Worker's URL (shown at the top, looks like
   `https://ssc-cms-auth.<your-subdomain>.workers.dev`).
5. Go back to your Worker → **Settings** → **Variables and Secrets** → **Add**:
   - `GITHUB_CLIENT_ID` = the Client ID from step 2
   - `GITHUB_CLIENT_SECRET` = the Client secret from step 2
   (Add both as **Secret** type, not plain text, so they're encrypted.)
6. Go back to your GitHub OAuth App (step 2) and set the **Authorization
   callback URL** to `https://<your-worker-url>/callback` using the URL
   from step 4. Save.

### 4. Point the editor at your Worker
1. Open `admin_src/config.yml` in this repo.
2. Find the line starting `base_url:` and replace
   `https://REPLACE-WITH-YOUR-WORKER-URL.workers.dev` with your actual
   Worker URL from step 3.4 (no trailing slash).
3. Commit and push.

### 5. Try it
Once Cloudflare finishes rebuilding (check the **Deployments** tab), open
`https://yoursite.com/admin/`. You should see a "Login with GitHub" screen;
after logging in you'll see two sections: **Contact info & address** and
**Expert profiles**. Edits save as a commit to this repo and go live after
the next automatic rebuild.

### What's editable now, and what isn't
Right now the editor covers contact details and the 10 expert profiles
(bio, photo, areas of expertise) — the things you mentioned changing most
often. The static page text (About Us, service descriptions, etc.) isn't
wired up yet. If you want that added later, the pattern in `build.py` and
`admin_src/config.yml` extends the same way the expert profiles do — just
say the word and I can add it without redoing any of the above setup.
