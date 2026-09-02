#!/usr/bin/env python3
"""
Static-site generator for SSC Europe.
Takes Webflow's "Export Code" output (flat .html + css/js/images) and:
  1. Restructures every page into folder/index.html so URLs stay clean
     (/aktuelles/ instead of aktuelles.html) with NO changes needed to the
     already-tested language-switcher / hamburger JS, which expects clean
     paths like '/aktuelles'.
  2. Rewrites every internal href/src to root-relative paths.
  3. Fills in the two CMS-driven pieces Webflow's export drops entirely:
       - the ExpertInnen / Experts listing grids (10 cards each)
       - the 20 individual expert detail pages
  4. Generates German CV / Publications sub-pages from the Jimdo-recovered
     content and wires them into each profile's sidecard.
  5. Rewires the contact form to POST to Formspree instead of Webflow.
"""
import json, os, re, shutil, html
from pathlib import Path
from bs4 import BeautifulSoup
import yaml
import markdown as md_lib

# Repo-root-relative paths (NOT hardcoded absolute paths) so this runs the
# same way locally and in Cloudflare Pages' build environment, which checks
# the repo out to its own path.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "webflow-export"
CONTENT_DIR = ROOT / "content"
EXPERTS_DIR = CONTENT_DIR / "experts"
SETTINGS_FILE = CONTENT_DIR / "settings.yml"
CV_DIR = ROOT / "cv-publications"
PHOTOS = ROOT / "images" / "experts"
ADMIN_SRC = ROOT / "admin_src"
DIST = ROOT / "dist"

FORMSPREE_PLACEHOLDER = "https://formspree.io/f/YOUR_FORM_ID"

# --- 0. Site-wide settings (editable via the CMS: content/settings.yml) -----
SETTINGS = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8"))

def apply_settings(soup, is_en):
    """Overwrite the footer/contact-page contact details (address, email,
    phone) that the Webflow export hard-codes into every single page, with
    the current values from content/settings.yml, so editing that one file
    updates the phone number/address/email everywhere at once."""
    city = SETTINGS["city_en"] if is_en else SETTINGS["city_de"]
    for addr in soup.find_all(class_="ssc-footer-addr"):
        addr.clear()
        addr.append(SETTINGS["org_name"])
        addr.append(soup.new_tag("br"))
        addr.append(SETTINGS["street"])
        addr.append(soup.new_tag("br"))
        addr.append(city)
    for addr in soup.find_all(class_="ssc-addr"):
        # kontakt.html / en/contact.html's standalone contact-person address block
        addr.clear()
        addr.append(SETTINGS["contact_person"])
        addr.append(soup.new_tag("br"))
        addr.append(SETTINGS["street"])
        addr.append(soup.new_tag("br"))
        addr.append(city)
    for a in soup.find_all("a", href=re.compile(r"^mailto:")):
        a["href"] = f"mailto:{SETTINGS['email']}"
        a.string = SETTINGS["email"]
    for a in soup.find_all("a", href=re.compile(r"^tel:")):
        a["href"] = f"tel:{SETTINGS['phone_tel']}"
        a.string = SETTINGS["phone_display"]

# --- 1. Page map: source file (relative to SRC) -> clean output folder ('' = site root) ----
PAGE_MAP = {
    "index.html": "",
    "aktuelles.html": "aktuelles",
    "ueber-uns.html": "ueber-uns",
    "expertinnen.html": "expertinnen",
    "formate.html": "formate",
    "presse.html": "presse",
    "links.html": "links",
    "kontakt.html": "kontakt",
    "seminare.html": "seminare",
    "simulationen.html": "simulationen",
    "consulting.html": "consulting",
    "en/home.html": "en/home",
    "en/news.html": "en/news",
    "en/about.html": "en/about",
    "en/seminars.html": "en/seminars",
    "en/simulations.html": "en/simulations",
    "en/consulting.html": "en/consulting",
    "en/experts.html": "en/experts",
    "en/formats.html": "en/formats",
    "en/press.html": "en/press",
    "en/links.html": "en/links",
    "en/contact.html": "en/contact",
    "en/former-projects.html": "en/former-projects",
}

# Build a lookup of every href variant Webflow's export uses -> clean root-relative path
HREF_LOOKUP = {}
for src_file, clean in PAGE_MAP.items():
    clean_path = "/" + clean + "/" if clean else "/"
    variants = {src_file, "/" + src_file, "./" + src_file}
    if src_file.startswith("en/"):
        variants.add("../" + src_file)          # actual style used within en/*.html, e.g. "../en/news.html"
    else:
        variants.add("../" + src_file)          # e.g. EN pages' static "DE" toggle -> "../index.html"
    HREF_LOOKUP.update({v: clean_path for v in variants})

SLUG_DE = {  # Jimdo-ish umlaut slugs not needed here; Webflow slugs are already clean
}

def clean_href_for(raw, is_en_source):
    """Map a raw href from the export to a clean root-relative path, or None if not a page link."""
    if raw in HREF_LOOKUP:
        return HREF_LOOKUP[raw]
    return None

ASSET_PREFIXES = ("css/", "js/", "images/", "../css/", "../js/", "../images/")

def rewrite_asset(raw):
    for p in ("../css/", "css/"):
        if raw.startswith(p):
            return "/css/" + raw[len(p):]
    for p in ("../js/", "js/"):
        if raw.startswith(p):
            return "/js/" + raw[len(p):]
    for p in ("../images/", "images/"):
        if raw.startswith(p):
            return "/images/" + raw[len(p):]
    return None

def rewrite_srcset(raw):
    parts = raw.split(",")
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        bits = part.split(" ")
        url = bits[0]
        rest = " ".join(bits[1:])
        new_url = rewrite_asset(url) or url
        out.append((new_url + (" " + rest if rest else "")).strip())
    return ", ".join(out)

LEGAL_PAGES = {
    "/impressum": "/impressum/",
    "/datenschutz": "/datenschutz/",
}
LEGAL_PAGES_EN = {
    "/impressum": "/en/impressum/",
    "/datenschutz": "/en/datenschutz/",
}

def rewrite_links_in_soup(soup, is_en_source):
    for tag in soup.find_all(["a"]):
        href = tag.get("href")
        if not href:
            continue
        if href.startswith(("mailto:", "tel:", "http://", "https://", "#")):
            continue
        mapped = clean_href_for(href, is_en_source)
        if mapped:
            tag["href"] = mapped
        elif href in LEGAL_PAGES:
            # The Webflow export hard-codes bare, no-trailing-slash hrefs to the
            # German-only legal pages on every page (DE *and* EN). Point EN pages
            # at their own /en/ legal pages and fix DE's missing trailing slash
            # so both match the folder/index.html structure every other link uses.
            tag["href"] = LEGAL_PAGES_EN[href] if is_en_source else LEGAL_PAGES[href]
    # EN header markup still uses the pre-rename burger classes (ssc-burger /
    # ssc-burger-bar); the site's X-morph CSS only targets the renamed
    # ssc-burger-1 / ssc-burger-bar-1 classes the DE header uses. Normalize EN
    # to match so the hamburger animates into an "X" on EN pages too.
    if is_en_source:
        burger = soup.find(class_="ssc-burger")
        if burger:
            burger["class"] = ["ssc-burger-1" if c == "ssc-burger" else c for c in burger["class"]]
        for bar in soup.find_all(class_="ssc-burger-bar"):
            bar["class"] = ["ssc-burger-bar-1" if c == "ssc-burger-bar" else c for c in bar["class"]]
    for tag in soup.find_all(["link"]):
        href = tag.get("href")
        if href:
            mapped = rewrite_asset(href)
            if mapped:
                tag["href"] = mapped
    for tag in soup.find_all(["img"]):
        src = tag.get("src")
        if src:
            mapped = rewrite_asset(src)
            if mapped:
                tag["src"] = mapped
        srcset = tag.get("srcset")
        if srcset:
            tag["srcset"] = rewrite_srcset(srcset)
    for tag in soup.find_all(["script"]):
        src = tag.get("src")
        if src:
            mapped = rewrite_asset(src)
            if mapped:
                tag["src"] = mapped
    for tag in soup.find_all(["a"], class_="ssc-brand"):
        pass  # brand links already handled by the generic <a> loop above
    apply_settings(soup, is_en_source)

def write_page(out_folder: str, html_text: str):
    if out_folder == "":
        out_path = DIST / "index.html"
    else:
        out_path = DIST / out_folder / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")

# --- 1b. Language switcher: same page, not the homepage ---------------------
# Webflow's export hard-codes the DE<->EN toggle link on every single page to
# the OTHER language's homepage (en/home.html from every German page, and
# index.html from every English page) — so switching language always dumped
# visitors back on the homepage instead of keeping them on the page they were
# reading. This maps each DE clean path to its real EN counterpart (and back),
# and overwrites the toggle link's href with that, page by page. Pages with no
# counterpart in the other language (the English-only "Former Projects" page,
# the German-only CV/Publications sub-pages) fall back to that language's
# homepage, since there's genuinely nothing more specific to link to.
LANG_PAIR_DE_TO_EN = {
    "": "en/home",
    "aktuelles": "en/news",
    "ueber-uns": "en/about",
    "expertinnen": "en/experts",
    "formate": "en/formats",
    "presse": "en/press",
    "links": "en/links",
    "kontakt": "en/contact",
    "seminare": "en/seminars",
    "simulationen": "en/simulations",
    "consulting": "en/consulting",
    "impressum": "en/impressum",
    "datenschutz": "en/datenschutz",
    "presse/pressemitteilungen": "en/press/press-releases",
}
LANG_PAIR_EN_TO_DE = {v: k for k, v in LANG_PAIR_DE_TO_EN.items()}
DEFAULT_DE_HOME = ""
DEFAULT_EN_HOME = "en/home"

def _clean_path(clean):
    return "/" + clean + "/" if clean else "/"

def lang_switch_target(current_clean, is_en_source):
    """The clean root-relative path the language toggle on this page should
    point to: the equivalent page in the other language, or that language's
    homepage if this page has no counterpart."""
    if is_en_source:
        counterpart = LANG_PAIR_EN_TO_DE.get(current_clean, DEFAULT_DE_HOME)
    else:
        counterpart = LANG_PAIR_DE_TO_EN.get(current_clean, DEFAULT_EN_HOME)
    return _clean_path(counterpart)

def apply_lang_switch(soup, current_clean, is_en_source, explicit_target=None):
    target = explicit_target if explicit_target is not None else lang_switch_target(current_clean, is_en_source)
    for a in soup.find_all("a", class_="ssc-lang-off"):
        a["href"] = target
    for a in soup.find_all("a", class_="ssc-lang-off-first"):
        a["href"] = target

# --- 2. Load expert data -----------------------------------------------------
# Editable via the CMS: one YAML file per expert under content/experts/,
# originally generated from the Webflow CMS export but now the source of
# truth going forward (edits made through the CMS commit straight to these
# files). Built into the same {"fieldData": {...}} shape the rest of this
# script (fill_detail / build_listing) already expects, so those don't need
# to change at all.
def render_md(text):
    if not text:
        return ""
    return md_lib.markdown(text, extensions=["extra"])

def load_experts():
    de_items, en_items = [], []
    for f in sorted(EXPERTS_DIR.glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        common = {
            "slug": d["slug"],
            "display-order": d.get("display_order", 999),
            "email": d.get("email", ""),
            "phone": d.get("phone", ""),
        }
        de_items.append({"fieldData": {**common,
            "name": d.get("name_de", ""), "expertise": d.get("expertise_de", ""),
            "bio": render_md(d.get("bio_de", "")),
            "activity-history": render_md(d.get("activity_history_de", ""))}})
        en_items.append({"fieldData": {**common,
            "name": d.get("name_en", ""), "expertise": d.get("expertise_en", ""),
            "bio": render_md(d.get("bio_en", "")),
            "activity-history": render_md(d.get("activity_history_en", ""))}})
    return de_items, en_items

def sort_items(items):
    return sorted(items, key=lambda it: it["fieldData"].get("display-order", 999))

de_items, en_items = load_experts()
de_items = sort_items(de_items)
en_items = sort_items(en_items)

PHOTO_EXT = {}
for f in PHOTOS.glob("*.*"):
    PHOTO_EXT[f.stem] = f.suffix

def photo_path(slug):
    ext = PHOTO_EXT.get(slug, ".jpg")
    return f"/images/experts/{slug}{ext}"

def cv_pub_flags(slug):
    """Return (has_cv, has_pub) based on recovered Jimdo content. Delegates to
    extract_section() (defined below) so this always agrees with whether a CV
    / Publications sub-page actually gets generated — previously this used
    its own separate text-matching, which missed a phrasing variant and
    generated a dead 'Publications' sidebar link for at least one expert
    (Judith Hartmann) pointing at a page that was never built."""
    f = CV_DIR / f"{slug}.md"
    if not f.exists():
        return False, False
    text = f.read_text(encoding="utf-8")
    cv_body, _ = extract_section(text, CV_HEADER)
    pub_body, _ = extract_section(text, PUB_HEADER)
    return bool(cv_body), bool(pub_body)

# --- 3. Process the 23 static pages ----------------------------------------
for src_file, clean in PAGE_MAP.items():
    path = SRC / src_file
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    is_en = src_file.startswith("en/")
    rewrite_links_in_soup(soup, is_en)
    apply_lang_switch(soup, clean, is_en)

    # Contact form -> Formspree
    form = soup.find("form")
    if form and src_file in ("kontakt.html", "en/contact.html"):
        form["method"] = "POST"
        form["action"] = FORMSPREE_PLACEHOLDER
        # honeypot spam trap
        honeypot = soup.new_tag("input", attrs={
            "type": "text", "name": "_gotcha",
            "style": "display:none", "tabindex": "-1", "autocomplete": "off",
        })
        form.append(honeypot)

    # Presse/Press -> link through to the recovered Pressemitteilungen /
    # Press Releases sub-page, same as the old Jimdo site linked to it.
    if src_file in ("presse.html", "en/press.html"):
        section = soup.find(class_="ssc-section")
        if section:
            href = "/presse/pressemitteilungen/" if src_file == "presse.html" else "/en/press/press-releases/"
            label = "→ Pressemitteilungen (2012–2013)" if src_file == "presse.html" else "→ Press Releases (2012–2013)"
            more = soup.new_tag("a", href=href, attrs={"class": "ssc-footer-link"})
            more.string = label
            wrap = soup.new_tag("p", style="margin-top:2rem")
            wrap.append(more)
            section.append(wrap)

    write_page(clean, str(soup))

print(f"Wrote {len(PAGE_MAP)} static pages.")

# --- 4. Populate the ExpertInnen / Experts listing grids --------------------
def build_listing(list_file, items, lang):
    path = SRC / list_file
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    is_en = list_file.startswith("en/")
    rewrite_links_in_soup(soup, is_en)
    apply_lang_switch(soup, PAGE_MAP[list_file], is_en)

    item_tpl = soup.find(attrs={"role": "listitem"})
    dyn_list = item_tpl.find_parent(class_="w-dyn-items")
    empty_div = soup.find(class_="w-dyn-empty")

    cards = []
    for it in items:
        fd = it["fieldData"]
        slug = fd["slug"]
        card = BeautifulSoup(str(item_tpl), "html.parser")
        a = card.find("a")
        href_root = "/expertinnen/" if lang == "de" else "/experts/"
        a["href"] = f"{href_root}{slug}/"
        img = card.find("img")
        img["src"] = photo_path(slug)
        img["alt"] = fd.get("name", "")
        del img["class"]
        img["class"] = "ssc-ex-photo"
        name_el = card.find(class_="ssc-ex-name")
        name_el.string = fd.get("name", "")
        del name_el["class"]
        name_el["class"] = "ssc-ex-name"
        field_el = card.find(class_="ssc-ex-field")
        field_el.string = fd.get("expertise", "")
        del field_el["class"]
        field_el["class"] = "ssc-ex-field"
        cards.append(card.div if card.div else card)

    dyn_list.clear()
    for c in cards:
        dyn_list.append(c)
    if empty_div:
        empty_div.decompose()

    write_page(PAGE_MAP[list_file], str(soup))

build_listing("expertinnen.html", de_items, "de")
build_listing("en/experts.html", en_items, "en")
print("Wrote 2 listing pages with 10 cards each.")

# --- 5. Build CV / Publications sub-pages -----------------------------------
CONTENT_PAGE_TEMPLATE = """
<div class="ssc-pagehead">
  <div class="ssc-container">
    <a href="{back_href}" class="ssc-back">&larr; {back_label}</a>
    <h1 class="ssc-pagetitle">{title}</h1>
  </div>
</div>
<div class="ssc-section">
  <div class="ssc-container">
    <div class="ssc-profile-main">
      <div class="ssc-rich w-richtext">{body_html}</div>
    </div>
  </div>
</div>
"""

JIMDO_CHROME_LINES = {"zurück zum profil", "nach oben"}

def text_to_html(md_body: str, expert_name: str = "") -> str:
    """Very small verbatim-text -> HTML paragraph converter for the recovered
    Jimdo CV/Publications text (plain lines, blank-line separated). Drops
    leftover Jimdo page-chrome lines ('zurück zum Profil', 'nach oben', and a
    duplicate 'Lebenslauf {Name}' title line) that aren't part of the CV/
    publications content itself."""
    lines = [l.rstrip() for l in md_body.strip().split("\n")]
    dup_title = f"lebenslauf {expert_name}".strip().lower()
    lines = [l for l in lines if l.strip().lower() not in JIMDO_CHROME_LINES
             and l.strip().lower() != dup_title]
    out, buf = [], []
    def flush():
        if buf:
            out.append("<p>" + "<br>".join(html.escape(x) for x in buf) + "</p>")
            buf.clear()
    for line in lines:
        if line.strip() == "":
            flush()
        elif line.startswith("### "):
            flush(); out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            continue  # section headers handled by caller
        else:
            buf.append(line.strip())
    flush()
    return "\n".join(out)

CV_HEADER = "CV / Lebenslauf"
PUB_HEADER = "Publications / Publikationen"

def extract_section(md_text, header):
    """Pull the FULL body of '## {header}' up to the OTHER top-level section
    header or EOF (nested '### '/'## ' subheadings inside the section, e.g.
    'Berufserfahrung', do not end it), minus the 'Source URL:' line and any
    ⚠️ flag line (kept separately)."""
    other = PUB_HEADER if header == CV_HEADER else CV_HEADER
    pattern = rf"## {re.escape(header)}\n(.*?)(?=\n## {re.escape(other)}\n|\Z)"
    m = re.search(pattern, md_text, re.S)
    if not m:
        return None, None
    block = m.group(1).strip()
    # strip a single leading "Source URL: ...." line in full (it can be a long
    # sentence, e.g. "Source URL: not found on profile page (...)")
    block = re.sub(r"^Source URL:.*(?:\n|$)", "", block).strip()
    flag = None
    fm = re.search(r"(⚠️.*)$", block, re.S)
    if fm:
        flag = fm.group(1).strip()
        block = block[:fm.start()].strip()
    low = block.lower()
    if header == CV_HEADER:
        missing = low.startswith("no cv page found")
    else:
        missing = low.startswith("no publications page found") or \
                  "no separate publications page exists" in low
    if missing or not block:
        return None, None
    return block, flag

def page_shell(title, lang, body_inner, clean=None, switch_target=None):
    """Wrap body_inner in the site's nav+footer using kontakt.html/en/contact.html as the shell.
    Pass `clean` (this page's own clean path, e.g. "impressum") to point the
    language toggle at its real counterpart, or `switch_target` to point it
    somewhere more specific (e.g. an expert's own profile page) when there's
    no page-to-page pairing to look up."""
    shell_src = "kontakt.html" if lang == "de" else "en/contact.html"
    soup = BeautifulSoup((SRC / shell_src).read_text(encoding="utf-8"), "html.parser")
    rewrite_links_in_soup(soup, lang == "en")
    if clean is not None or switch_target is not None:
        apply_lang_switch(soup, clean, lang == "en", explicit_target=switch_target)
    soup.title.string = f"{title} | SSC Europe"
    md = soup.find("meta", attrs={"name": "description"})
    if md:
        md["content"] = title
    # Replace everything between nav and footer with our content
    nav = soup.find(class_="ssc-nav")
    footer = soup.find(class_="ssc-footer")
    new_content = BeautifulSoup(body_inner, "html.parser")
    for el in list(nav.find_next_siblings()):
        if el is footer:
            break
        el.decompose()
    nav.insert_after(new_content)
    return str(soup)

made_cv, made_pub = 0, 0
for it in de_items:
    fd = it["fieldData"]
    slug = fd["slug"]
    name = fd.get("name", "")
    f = CV_DIR / f"{slug}.md"
    if not f.exists():
        continue
    md_text = f.read_text(encoding="utf-8")

    cv_body, cv_flag = extract_section(md_text, "CV / Lebenslauf")
    if cv_body:
        body_html = text_to_html(cv_body, name)
        if cv_flag:
            body_html += f'\n<p class="ssc-flag">{html.escape(cv_flag)}</p>'
        inner = CONTENT_PAGE_TEMPLATE.format(
            back_href=f"/expertinnen/{slug}/", back_label=name,
            title=f"Lebenslauf {name}", body_html=body_html)
        write_page(f"expertinnen/{slug}/lebenslauf", page_shell(f"Lebenslauf {name}", "de", inner,
            switch_target=f"/experts/{slug}/"))
        made_cv += 1

    pub_body, pub_flag = extract_section(md_text, "Publications / Publikationen")
    if pub_body:
        body_html = text_to_html(pub_body)
        if pub_flag:
            body_html += f'\n<p class="ssc-flag">{html.escape(pub_flag)}</p>'
        inner = CONTENT_PAGE_TEMPLATE.format(
            back_href=f"/expertinnen/{slug}/", back_label=name,
            title=f"Publikationen {name}", body_html=body_html)
        write_page(f"expertinnen/{slug}/publikationen", page_shell(f"Publikationen {name}", "de", inner,
            switch_target=f"/experts/{slug}/"))
        made_pub += 1

print(f"Wrote {made_cv} CV pages and {made_pub} Publications pages (German source only).")

# --- 6. Build the 20 expert detail pages ------------------------------------
def fill_detail(template_file, items, lang):
    href_root = "/expertinnen/" if lang == "de" else "/experts/"
    made = 0
    for it in items:
        fd = it["fieldData"]
        slug = fd["slug"]
        name = fd.get("name", "")
        soup = BeautifulSoup((SRC / template_file).read_text(encoding="utf-8"), "html.parser")
        rewrite_links_in_soup(soup, lang == "en")
        # Each expert's profile exists in both languages at the same slug, so
        # the language toggle can point straight at the sibling profile
        # instead of falling back to that language's homepage.
        sibling = f"/experts/{slug}/" if lang == "de" else f"/expertinnen/{slug}/"
        apply_lang_switch(soup, None, lang == "en", explicit_target=sibling)

        soup.title.string = f"{name} | SSC Europe"
        md = soup.find("meta", attrs={"name": "description"})
        if md:
            md["content"] = fd.get("expertise", "")

        img = soup.find(class_="ssc-profile-photo")
        img["src"] = photo_path(slug)
        img["alt"] = name
        if "w-dyn-bind-empty" in img.get("class", []):
            img["class"].remove("w-dyn-bind-empty")

        h1 = soup.find(class_="ssc-pagetitle")
        h1.string = name
        if "w-dyn-bind-empty" in h1.get("class", []):
            h1["class"].remove("w-dyn-bind-empty")

        expertise_p = soup.find(class_="ssc-profile-expertise")
        expertise_p.string = fd.get("expertise", "")
        if "w-dyn-bind-empty" in expertise_p.get("class", []):
            expertise_p["class"].remove("w-dyn-bind-empty")

        mail_a = soup.find(class_="ssc-profile-mail")
        email = fd.get("email") or "info@ssc-europe.eu"
        mail_a["href"] = f"mailto:{email}"
        mail_a.string = email
        if "w-dyn-bind-empty" in mail_a.get("class", []):
            mail_a["class"].remove("w-dyn-bind-empty")

        tel_a = soup.find(class_="ssc-profile-tel")
        phone = fd.get("phone")
        if phone:
            tel_a["href"] = "tel:" + re.sub(r"[^\d+]", "", phone)
            tel_a.string = phone
            if "w-dyn-bind-empty" in tel_a.get("class", []):
                tel_a["class"].remove("w-dyn-bind-empty")
        else:
            tel_a.decompose()

        rich_blocks = soup.find_all(class_="ssc-rich")
        # First = bio ("Profil"), second = activity-history ("Tätigkeiten")
        bio_html = fd.get("bio") or ""
        activity_html = fd.get("activity-history") or ""
        if len(rich_blocks) >= 1:
            rich_blocks[0].clear()
            rich_blocks[0].append(BeautifulSoup(bio_html, "html.parser"))
            if "w-dyn-bind-empty" in rich_blocks[0].get("class", []):
                rich_blocks[0]["class"].remove("w-dyn-bind-empty")
        if len(rich_blocks) >= 2:
            rich_blocks[1].clear()
            rich_blocks[1].append(BeautifulSoup(activity_html, "html.parser"))
            if "w-dyn-bind-empty" in rich_blocks[1].get("class", []):
                rich_blocks[1]["class"].remove("w-dyn-bind-empty")

        has_cv, has_pub = cv_pub_flags(slug)
        sidelinks = soup.find_all(class_="ssc-sidelink")
        # Order in template: [CV, Publications, Anfrage senden]
        cv_link, pub_link, request_link = sidelinks[0], sidelinks[1], sidelinks[2]
        if has_cv:
            cv_link["href"] = f"/expertinnen/{slug}/lebenslauf/"
            if lang == "en":
                cv_link.string = "View CV (German)"
        else:
            cv_link.decompose()
        if has_pub:
            pub_link["href"] = f"/expertinnen/{slug}/publikationen/"
            if lang == "en":
                pub_link.string = "Publications (German)"
        else:
            pub_link.decompose()
        request_link["href"] = "/kontakt/" if lang == "de" else "/en/contact/"

        write_page(f"{href_root.strip('/')}/{slug}", str(soup))
        made += 1
    return made

n1 = fill_detail("detail_expertinnen.html", de_items, "de")
n2 = fill_detail("detail_experts.html", en_items, "en")
print(f"Wrote {n1} DE + {n2} EN expert detail pages.")

# --- 6b. Impressum -----------------------------------------------------------
# The old Jimdo Impressum page's exact prose couldn't be pulled verbatim (the
# extraction tool wouldn't reproduce full legal-page text word-for-word), so
# this is standard German/Austrian legal-notice boilerplate rebuilt around the
# FACTUAL data recovered from the source page (name, address, contact,
# responsible party, statute citations). ⚠️ Flagged for a lawyer/the client to
# confirm the wording before this goes live — see the note at the bottom of
# the page itself.
IMPRESSUM_BODY = """
<h2>Angaben gemäß § 5 ECG / Impressum</h2>
<p>SSC Europe<br>
Frauenfelderstraße 14<br>
A-1170 Wien, Österreich</p>
<p>Telefon: +49 (0) 163 28 55 55 5<br>
E-Mail: <a href="mailto:info@ssc-europe.eu">info@ssc-europe.eu</a></p>

<h3>Inhaltlich Verantwortlicher gemäß § 55 Abs. 2 RStV</h3>
<p>Sebastian Schäffer<br>
E-Mail: <a href="mailto:sschaeffer@ssc-europe.eu">sschaeffer@ssc-europe.eu</a></p>

<h3>Haftung für Inhalte</h3>
<p>Die Inhalte dieser Website wurden mit größtmöglicher Sorgfalt erstellt. Für die Richtigkeit,
Vollständigkeit und Aktualität der Inhalte kann jedoch keine Gewähr übernommen werden. Als
Diensteanbieter sind wir gemäß § 7 Abs. 1 DDG für eigene Inhalte auf diesen Seiten nach den
allgemeinen Gesetzen verantwortlich. Nach §§ 8 bis 10 DDG sind wir als Diensteanbieter jedoch
nicht verpflichtet, übermittelte oder gespeicherte fremde Informationen zu überwachen oder nach
Umständen zu forschen, die auf eine rechtswidrige Tätigkeit hinweisen.</p>

<h3>Haftung für Links</h3>
<p>Unser Angebot enthält Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss
haben. Deshalb können wir für diese fremden Inhalte auch keine Gewähr übernehmen. Für die Inhalte
der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich. Die
verlinkten Seiten wurden zum Zeitpunkt der Verlinkung auf mögliche Rechtsverstöße überprüft. Eine
permanente inhaltliche Kontrolle der verlinkten Seiten ist ohne konkrete Anhaltspunkte einer
Rechtsverletzung nicht zumutbar.</p>

<h3>Urheberrecht</h3>
<p>Die durch die Seitenbetreiber erstellten Inhalte und Werke auf diesen Seiten unterliegen dem
deutschen und österreichischen Urheberrecht. Die Vervielfältigung, Bearbeitung, Verbreitung und
jede Art der Verwertung außerhalb der Grenzen des Urheberrechtes bedürfen der schriftlichen
Zustimmung des jeweiligen Autors bzw. Erstellers. Inhalte Dritter sind als solche gekennzeichnet.</p>

<p>Logo-Design: Anita Nastav.</p>

<p><a href="/datenschutz/">Zu unserer Datenschutzerklärung</a></p>

<p class="ssc-flag">⚠️ Dieser Text wurde anhand der auf der alten Jimdo-Seite vorhandenen
Fakten (Adresse, Kontakt, Verantwortlicher, Gesetzeszitate) neu formuliert, da das
Extraktionswerkzeug den Originaltext nicht wortgleich reproduzieren konnte. Bitte vor
Veröffentlichung mit der Originalseite bzw. anwaltlich abgleichen.</p>
"""

write_page("impressum", page_shell("Impressum", "de",
    CONTENT_PAGE_TEMPLATE.format(back_href="/", back_label="Startseite",
                                  title="Impressum", body_html=IMPRESSUM_BODY),
    clean="impressum"))
print("Wrote Impressum page (reconstructed from recovered facts — flagged for review).")

# --- 6c. Impressum (English) --------------------------------------------------
# Plain-language English rendering of the same factual notice above (same
# ⚠️ review flag applies — legal boilerplate, not legal advice).
IMPRESSUM_BODY_EN = """
<h2>Legal Notice (Impressum)</h2>
<p>SSC Europe<br>
Frauenfelderstraße 14<br>
A-1170 Vienna, Austria</p>
<p>Phone: +49 (0) 163 28 55 55 5<br>
Email: <a href="mailto:info@ssc-europe.eu">info@ssc-europe.eu</a></p>

<h3>Responsible for content (§ 55 para. 2 RStV)</h3>
<p>Sebastian Schäffer<br>
Email: <a href="mailto:sschaeffer@ssc-europe.eu">sschaeffer@ssc-europe.eu</a></p>

<h3>Liability for content</h3>
<p>The content of this website has been created with the greatest possible care. However, we
cannot guarantee the accuracy, completeness, or timeliness of the content. As a service
provider, we are responsible for our own content on these pages in accordance with general
law under § 7 para. 1 DDG. Under §§ 8 to 10 DDG, however, we as a service provider are not
obliged to monitor transmitted or stored third-party information or to investigate
circumstances that indicate illegal activity.</p>

<h3>Liability for links</h3>
<p>Our site contains links to external third-party websites over whose content we have no
control. We therefore cannot accept any liability for this external content. The respective
provider or operator of the linked pages is always responsible for their content. The linked
pages were checked for possible legal violations at the time of linking. Permanent monitoring
of the content of linked pages is not reasonable without concrete evidence of a violation.</p>

<h3>Copyright</h3>
<p>Content and works created by the site operators on these pages are subject to German and
Austrian copyright law. Duplication, editing, distribution, and any kind of use outside the
limits of copyright law require the written consent of the respective author or creator.
Third-party content is marked as such.</p>

<p>Logo design: Anita Nastav.</p>

<p><a href="/en/datenschutz/">Read our privacy policy</a></p>

<p class="ssc-flag">⚠️ This is an English rendering of the German legal notice, itself
reconstructed from facts recovered from the previous Jimdo site (address, contact, person
responsible, statute citations) because the extraction tool could not reproduce the original
wording verbatim. Please have both language versions checked against the original page and/or
by a lawyer before publishing.</p>
"""

write_page("en/impressum", page_shell("Legal Notice", "en",
    CONTENT_PAGE_TEMPLATE.format(back_href="/en/home/", back_label="Home",
                                  title="Legal Notice", body_html=IMPRESSUM_BODY_EN),
    clean="en/impressum"))
print("Wrote English Impressum page.")

# --- 6d. Datenschutz / Privacy policy (German + English) ---------------------
# No Datenschutz source content survived from Jimdo/Webflow, and the old
# policy would describe the OLD stack (Jimdo/Webflow hosting) anyway, which is
# no longer accurate. This is a freshly drafted policy describing the actual
# current, self-hosted setup: Cloudflare Pages hosting + Formspree contact
# form, no cookies/tracking/analytics/embedded fonts in use (confirmed by
# inspecting the live build — no font <link> tags, no analytics scripts).
# ⚠️ Boilerplate, not legal advice — flagged for the client / a lawyer to
# confirm before publishing, same as the Impressum.
DATENSCHUTZ_BODY = """
<h2>Datenschutzerklärung</h2>
<p>Verantwortlicher im Sinne der Datenschutz-Grundverordnung (DSGVO) ist:</p>
<p>SSC Europe<br>
Frauenfelderstraße 14<br>
A-1170 Wien, Österreich<br>
E-Mail: <a href="mailto:info@ssc-europe.eu">info@ssc-europe.eu</a></p>

<h3>Hosting</h3>
<p>Diese Website wird bei Cloudflare, Inc. (Cloudflare Pages) gehostet. Beim Aufruf der Website
verarbeitet Cloudflare automatisch technische Zugriffsdaten (u.&nbsp;a. IP-Adresse, Datum und
Uhrzeit des Zugriffs, aufgerufene Seite, Browsertyp), um die Website sicher und stabil
auszuliefern. Rechtsgrundlage ist unser berechtigtes Interesse an einer funktionsfähigen und
sicheren Website (Art. 6 Abs. 1 lit. f DSGVO). Cloudflare kann Daten außerhalb der EU/des EWR
verarbeiten; Cloudflare verpflichtet sich vertraglich zur Einhaltung des europäischen
Datenschutzniveaus (u.&nbsp;a. EU-Standardvertragsklauseln). Details:
<a href="https://www.cloudflare.com/privacypolicy/" target="_blank" rel="noopener">Cloudflare-Datenschutzerklärung</a>.</p>

<h3>Keine Cookies, kein Tracking</h3>
<p>Diese Website setzt keine Cookies, keine Analyse- oder Tracking-Dienste und keine
eingebetteten Drittanbieter-Schriftarten ein. Es findet keine Erstellung von Nutzerprofilen
statt.</p>

<h3>Kontaktformular</h3>
<p>Nutzen Sie unser Kontaktformular, werden die von Ihnen eingegebenen Daten (u.&nbsp;a. Name,
E-Mail-Adresse, Nachrichtentext) zur Bearbeitung Ihrer Anfrage verwendet. Die technische
Zustellung erfolgt über den Dienstleister Formspree, Inc. (USA). Rechtsgrundlage ist die
Erfüllung bzw. Anbahnung eines Vertrags oder vorvertraglicher Maßnahmen auf Ihre Anfrage hin
(Art. 6 Abs. 1 lit. b DSGVO) sowie unser berechtigtes Interesse an einer zuverlässigen
Formularzustellung (Art. 6 Abs. 1 lit. f DSGVO). Mit Formspree besteht ein Auftragsverarbeitungs-
bzw. Datenübermittlungsverhältnis auf Basis von EU-Standardvertragsklauseln. Details:
<a href="https://formspree.io/legal/privacy-policy" target="_blank" rel="noopener">Formspree-Datenschutzerklärung</a>.</p>

<h3>Kontaktaufnahme per E-Mail oder Telefon</h3>
<p>Wenn Sie uns per E-Mail oder Telefon kontaktieren, werden Ihre Angaben zur Bearbeitung Ihrer
Anfrage gespeichert. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b bzw. lit. f DSGVO.</p>

<h3>Speicherdauer</h3>
<p>Wir speichern personenbezogene Daten nur so lange, wie es für die jeweiligen Zwecke
erforderlich ist oder gesetzliche Aufbewahrungspflichten dies verlangen.</p>

<h3>Ihre Rechte</h3>
<p>Sie haben das Recht auf Auskunft, Berichtigung, Löschung und Einschränkung der Verarbeitung
Ihrer personenbezogenen Daten sowie ein Recht auf Datenübertragbarkeit und Widerspruch gegen
die Verarbeitung. Zudem haben Sie das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu
beschweren, z.&nbsp;B. bei der österreichischen Datenschutzbehörde.</p>

<p><a href="/impressum/">Zum Impressum</a></p>

<p class="ssc-flag">⚠️ Diese Datenschutzerklärung wurde neu erstellt, da von der alten
Jimdo/Webflow-Seite kein übernehmbarer Text vorlag und dieser ohnehin die frühere, inzwischen
abgelöste Technik beschrieben hätte. Sie beschreibt den aktuellen, selbst gehosteten Stand
(Cloudflare Pages + Formspree, keine Cookies/kein Tracking, Stand {build_date}). Bitte vor
Veröffentlichung anwaltlich prüfen lassen — dies ist keine Rechtsberatung.</p>
"""

DATENSCHUTZ_BODY_EN = """
<h2>Privacy Policy</h2>
<p>The controller within the meaning of the General Data Protection Regulation (GDPR) is:</p>
<p>SSC Europe<br>
Frauenfelderstraße 14<br>
A-1170 Vienna, Austria<br>
Email: <a href="mailto:info@ssc-europe.eu">info@ssc-europe.eu</a></p>

<h3>Hosting</h3>
<p>This website is hosted by Cloudflare, Inc. (Cloudflare Pages). When you access the site,
Cloudflare automatically processes technical access data (including IP address, date and time
of access, page requested, browser type) to deliver the site securely and reliably. The legal
basis is our legitimate interest in a functional and secure website (Art. 6(1)(f) GDPR).
Cloudflare may process data outside the EU/EEA; Cloudflare is contractually committed to
maintaining European data protection standards (including EU Standard Contractual Clauses).
Details: <a href="https://www.cloudflare.com/privacypolicy/" target="_blank" rel="noopener">Cloudflare privacy policy</a>.</p>

<h3>No cookies, no tracking</h3>
<p>This website does not use cookies, analytics or tracking services, or embedded third-party
fonts. No user profiles are created.</p>

<h3>Contact form</h3>
<p>If you use our contact form, the information you enter (including name, email address,
message text) is used to process your inquiry. Technical delivery is handled by the service
provider Formspree, Inc. (USA). The legal basis is the performance of, or steps prior to
entering into, a contract at your request (Art. 6(1)(b) GDPR) as well as our legitimate
interest in reliable form delivery (Art. 6(1)(f) GDPR). We have a data-processing/transfer
arrangement with Formspree based on EU Standard Contractual Clauses. Details:
<a href="https://formspree.io/legal/privacy-policy" target="_blank" rel="noopener">Formspree privacy policy</a>.</p>

<h3>Contacting us by email or phone</h3>
<p>If you contact us by email or phone, your details will be stored to process your inquiry.
The legal basis is Art. 6(1)(b) or (f) GDPR.</p>

<h3>Retention period</h3>
<p>We only store personal data for as long as necessary for the respective purpose or as
required by statutory retention obligations.</p>

<h3>Your rights</h3>
<p>You have the right to access, rectify, erase, and restrict the processing of your personal
data, as well as a right to data portability and to object to processing. You also have the
right to lodge a complaint with a data protection supervisory authority, e.g. the Austrian Data
Protection Authority.</p>

<p><a href="/en/impressum/">Legal notice</a></p>

<p class="ssc-flag">⚠️ This privacy policy is newly drafted, since no reusable text survived
from the old Jimdo/Webflow site and it would have described the previous, now-replaced
technology anyway. It describes the current, self-hosted setup (Cloudflare Pages + Formspree,
no cookies/no tracking, as of {build_date}). Please have it reviewed by a lawyer before
publishing — this is not legal advice.</p>
"""

from datetime import date as _date
_build_date = _date.today().strftime("%Y-%m-%d")

write_page("datenschutz", page_shell("Datenschutzerklärung", "de",
    CONTENT_PAGE_TEMPLATE.format(back_href="/", back_label="Startseite",
                                  title="Datenschutzerklärung",
                                  body_html=DATENSCHUTZ_BODY.format(build_date=_build_date)),
    clean="datenschutz"))
write_page("en/datenschutz", page_shell("Privacy Policy", "en",
    CONTENT_PAGE_TEMPLATE.format(back_href="/en/home/", back_label="Home",
                                  title="Privacy Policy",
                                  body_html=DATENSCHUTZ_BODY_EN.format(build_date=_build_date)),
    clean="en/datenschutz"))
# --- 6e. Pressemitteilungen / Press Releases (German + English) -------------
# This whole section existed on the old Jimdo site as a sub-page linked from
# Presse/Press ("Pressemitteilungen" / "Press Releases", 2012-2013 org
# announcements) but was never carried into the Webflow export, so it never
# made it into any earlier build either. Recovered by fetching each of the 6
# original PDF press releases; text below is reconstructed from their
# content, not copy-pasted verbatim, so it's flagged the same way the
# Impressum is. The original PDFs themselves lived on Jimdo's own file
# storage and can't be re-hosted here — if you still want the original PDF
# files attached, they'd need to be downloaded from the old site before it's
# decommissioned and added separately.
PRESSEMITTEILUNGEN_ENTRIES = [
    ("02.10.2013", "Demokratie verankern: Studierende diskutieren tunesische Verfassung",
     "Vom 7. bis 11. Oktober 2013 kamen 10 Studierende aus ganz Deutschland und 10 tunesische "
     "Studierende an der Universität Karthago zusammen, um im gegenseitigen Austausch neue "
     "Perspektiven auf den laufenden Prozess der Verfassungsgebung in Tunesien zu entwickeln."),
    ("25.04.2013", "Seminar „Angewandte Politikforschung“",
     "SSC Europe führte vom 27. April bis 7. Mai 2013 an der Ludwig-Maximilians-Universität "
     "München ein intensives Seminar mit 26 Studierenden und Lehrenden der American University "
     "Cairo und der Cairo University durch — das vierte Projekt im Rahmen der "
     "DAAD-Transformationspartnerschaft. Neben politikwissenschaftlichen Inhalten (u. a. "
     "Europäische Nachbarschaftspolitik, Verfassen von Policy Papers) standen Besuche beim "
     "Informationsbüro des Europäischen Parlaments, der Bayerischen Staatskanzlei und dem "
     "Münchner Stadtrat sowie ein interkultureller Workshop auf dem Programm."),
    ("21.03.2013", "Sonderprogramm Ukraine 2013 DAAD",
     "Vom 25. bis 31. März 2013 entwickelte SSC Europe gemeinsam mit Studierenden und Lehrenden "
     "der Petro-Mohyla-Schwarzmeer-Nationaluniversität in Mykolajiw ein Planspiel zur Östlichen "
     "Partnerschaft der EU, mit den Themenschwerpunkten Demokratie und Regierungsführung, "
     "Energiepolitik sowie zwischenmenschliche Kontakte. Gefördert wurde das Vorhaben vom "
     "Deutschen Akademischen Austauschdienst (DAAD) und dem Auswärtigen Amt im Rahmen eines "
     "Sonderprogramms zur politischen Stabilisierung und EU-/NATO-Annäherung der Ukraine."),
    ("11.02.2013", "Kooperation mit dem DAAD",
     "Vom 11. bis 13. Februar 2013 entwickelte SSC Europe an der Universität Karthago in "
     "Tunesien ein politisches Planspiel zur Arabischen Liga und setzte damit die Kooperation "
     "mit dem Deutschen Akademischen Austauschdienst (DAAD) fort. Weitere Projekte im Jahr 2013 "
     "folgten Ende März (Planspiel Östliche Partnerschaft in Mykolajiw, Ukraine) und Ende April/"
     "Anfang Mai (Intensivworkshop zur Vorbereitung ägyptischer Studierender auf ein Studium in "
     "Deutschland)."),
    ("27.08.2012", "Transformationspartnerschaft DAAD",
     "Vom 27. bis 30. August 2012 brachte SSC Europe im Rahmen der Transformationspartnerschaft "
     "des DAAD zehn tunesische und zehn Münchner Studierende an der Ludwig-Maximilians-"
     "Universität München zu einem Planspiel zu „Die Union für den Mittelmeerraum nach dem "
     "Arabischen Frühling“ zusammen. Tunesische Teilnehmende übernahmen dabei Rollen "
     "europäischer, deutsche Teilnehmende Rollen mediterraner Staaten; behandelt wurden "
     "Sicherheitspolitik, Migration und Energiefragen. Zum Abschluss besuchten die Teilnehmenden "
     "die Vertretung der Europäischen Kommission in München."),
    ("04.07.2012", "Planspiel Finanztransaktionssteuer",
     "SSC Europe entwickelte ein Planspiel zur Finanztransaktionssteuer, in dem Studierende und "
     "Seminarteilnehmende die Rolle von Finanzminister:innen der Eurozone übernehmen und über "
     "Ausgestaltung und Einführung der Steuer verhandeln — ein Thema, das im Zuge der "
     "Verhandlungen um den Europäischen Stabilitätsmechanismus politisch prominent geworden war "
     "und Globalisierungskritiker:innen sowie einzelne Regierungen (u. a. Frankreich, Österreich) "
     "auf der einen und die Finanzbranche sowie Länder wie Großbritannien auf der anderen Seite "
     "gegenüberstellte."),
]

PRESSEMITTEILUNGEN_ENTRIES_EN = [
    ("Oct 2, 2013", "Anchoring democracy: students discuss Tunisia's constitution",
     "From October 7-11, 2013, 10 students from across Germany and 10 Tunisian students came "
     "together at the University of Carthage to develop new perspectives, through mutual "
     "exchange, on Tunisia's ongoing constitution-drafting process."),
    ("Apr 25, 2013", "Seminar “Applied Political Research”",
     "From April 27 to May 7, 2013, SSC Europe ran an intensive seminar at Ludwig-Maximilians-"
     "Universität München with 26 students and faculty from the American University in Cairo "
     "and Cairo University — the fourth project under the DAAD Transformation Partnership. "
     "Alongside coursework (including EU Neighbourhood Policy and policy-paper writing), the "
     "programme included visits to the European Parliament's information office, the Bavarian "
     "State Chancellery, and Munich City Council, plus an intercultural workshop."),
    ("Mar 21, 2013", "Special Ukraine 2013 DAAD programme",
     "From March 25-31, 2013, SSC Europe worked with students and faculty at Petro Mohyla Black "
     "Sea National University in Mykolaiv to develop a simulation on the EU's Eastern "
     "Partnership, covering democracy and governance, energy policy, and people-to-people "
     "contacts. The project was funded by the German Academic Exchange Service (DAAD) and the "
     "Federal Foreign Office as part of a special programme supporting Ukraine's political "
     "stabilization and EU/NATO integration."),
    ("Feb 11, 2013", "Cooperation with the DAAD",
     "From February 11-13, 2013, SSC Europe developed a political simulation on the Arab League "
     "at the University of Carthage in Tunisia, continuing its cooperation with the German "
     "Academic Exchange Service (DAAD). Further 2013 projects followed in late March (Eastern "
     "Partnership simulation in Mykolaiv, Ukraine) and late April/early May (an intensive "
     "workshop preparing Egyptian students for study in Germany)."),
    ("Aug 27, 2012", "DAAD Transformation Partnership",
     "From August 27-30, 2012, as part of the DAAD's Transformation Partnership, SSC Europe "
     "brought together ten Tunisian and ten Munich students at Ludwig-Maximilians-Universität "
     "München for a simulation on “The Union for the Mediterranean after the Arab Spring.” "
     "Tunisian participants took on the roles of European states and German participants the "
     "roles of Mediterranean states, covering security policy, migration, and energy. The "
     "programme concluded with a visit to the European Commission's Munich office."),
    ("Jul 4, 2012", "Financial transaction tax simulation",
     "SSC Europe developed a simulation on the financial transaction tax in which students and "
     "seminar participants take on the roles of eurozone finance ministers, negotiating the "
     "tax's design and introduction — a topic that had become politically prominent amid "
     "European Stability Mechanism negotiations, dividing globalization critics and some "
     "governments (e.g. France, Austria) on one side from the financial sector and countries "
     "such as the UK on the other."),
]

def render_pm_entries(entries):
    parts = []
    for date, title, body in entries:
        parts.append(f'<p class="ssc-project-meta">{html.escape(date)}</p>')
        parts.append(f'<h3>{html.escape(title)}</h3>')
        parts.append(f'<p>{body}</p>')
    return "\n".join(parts)

PRESSEMITTEILUNGEN_BODY = f"""
<h2>Pressemitteilungen</h2>
<p>Eigene Presseaussendungen von SSC Europe.</p>
{render_pm_entries(PRESSEMITTEILUNGEN_ENTRIES)}
<p class="ssc-flag">⚠️ Diese Texte wurden anhand der auf der alten Jimdo-Seite verfügbaren
Pressemitteilungen (2012–2013) sinngemäß rekonstruiert, nicht wortgleich übernommen — bitte bei
Bedarf mit den Originalen abgleichen. Die zugehörigen PDF-Dokumente lagen auf der alten
Jimdo-Seite und wurden nicht mit übernommen.</p>
"""

PRESSEMITTEILUNGEN_BODY_EN = f"""
<h2>Press Releases</h2>
<p>SSC Europe's own press releases.</p>
{render_pm_entries(PRESSEMITTEILUNGEN_ENTRIES_EN)}
<p class="ssc-flag">⚠️ This text is reconstructed from the original 2012–2013 press releases on
the old Jimdo site, in substance rather than word-for-word — please check against the originals
if exact wording matters. The original PDF documents lived on the old Jimdo site and weren't
carried over.</p>
"""

write_page("presse/pressemitteilungen", page_shell("Pressemitteilungen", "de",
    CONTENT_PAGE_TEMPLATE.format(back_href="/presse/", back_label="Presse",
                                  title="Pressemitteilungen", body_html=PRESSEMITTEILUNGEN_BODY),
    clean="presse/pressemitteilungen"))
write_page("en/press/press-releases", page_shell("Press Releases", "en",
    CONTENT_PAGE_TEMPLATE.format(back_href="/en/press/", back_label="Press",
                                  title="Press Releases", body_html=PRESSEMITTEILUNGEN_BODY_EN),
    clean="en/press/press-releases"))
print("Wrote German + English Pressemitteilungen/Press Releases pages (recovered from Jimdo — flagged for review).")

print("Wrote German + English Datenschutz/Privacy pages (freshly drafted — flagged for review).")

# --- 7. Copy static assets ----------------------------------------------------
for folder in ("css", "js", "images"):
    dst = DIST / folder
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC / folder, dst)
# overlay the self-hosted expert photos
shutil.copytree(PHOTOS, DIST / "images" / "experts", dirs_exist_ok=True)

# Decap CMS admin panel (content editor) -> /admin/
if ADMIN_SRC.exists():
    admin_dst = DIST / "admin"
    if admin_dst.exists():
        shutil.rmtree(admin_dst)
    shutil.copytree(ADMIN_SRC, admin_dst)
    print("Copied admin/ (content editor).")

print("Copied css/js/images.")
print("\nBuild complete ->", DIST)
