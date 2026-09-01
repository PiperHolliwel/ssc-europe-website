# ssc-europe-website

Static export of the ssc-europe.eu site, migrated off Jimdo/Webflow.

- Plain HTML/CSS/JS, no build step — every page lives at `{path}/index.html` so
  clean URLs (e.g. `/aktuelles/`, `/expertinnen/michael-bauer/`) work on any
  static host without extra rewrite rules.
- Bilingual: German at the root, English under `/en/`.
- The 20 expert profile pages, the ExpertInnen/Experts listing grids, and the
  German CV/Publications sub-pages are generated from CMS + recovered content
  rather than hand-written — see `build.py` (kept alongside this export for
  reference) if content needs regenerating from source data.
- The contact form (`/kontakt/`, `/en/contact/`) posts to Formspree. Replace
  the placeholder endpoint in both pages' `<form action="...">` with your real
  Formspree form URL before going live.
- `/datenschutz/` (privacy policy) is not yet built — pending source content.

Deploy target: Cloudflare Pages, root directory, no build command.
