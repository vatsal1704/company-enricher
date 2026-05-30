import os
import json
import time
import re
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import anthropic

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")

# ---------- Storage (in-memory + file-backed) ----------
RESULTS_FILE = "results.json"

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return []

def save_results(data):
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ---------- Scraping Helpers ----------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TARGET_KEYWORDS = [
    "about", "contact", "services", "service", "solutions",
    "team", "company", "who-we-are", "what-we-do", "our-work",
    "products", "offerings", "expertise", "capabilities"
]

def fetch_page(url, timeout=10):
    """Fetch a URL with retries and return raw HTML."""
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            time.sleep(1)
    return ""

def clean_html(html):
    """Strip HTML to clean readable text, removing nav/footer/script boilerplate."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "iframe", "svg", "form", "aside",
                     "meta", "link", "button"]):
        tag.decompose()
    # Remove cookie banners / overlay divs by class hint
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", []))
        if any(kw in cls.lower() for kw in ["cookie", "banner", "popup", "modal", "overlay", "ads"]):
            tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Deduplicate consecutive identical lines
    deduped = []
    prev = None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line
    return "\n".join(deduped)

def get_sitemap_urls(base_url):
    """Try to fetch sitemap.xml and extract URLs."""
    urls = []
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/"]:
        try:
            resp = requests.get(base_url.rstrip("/") + path, headers=HEADERS, timeout=8)
            if resp.status_code == 200 and "<url>" in resp.text.lower():
                soup = BeautifulSoup(resp.text, "xml")
                locs = soup.find_all("loc")
                urls = [l.get_text().strip() for l in locs]
                if urls:
                    break
        except Exception:
            continue
    return urls

def fuzzy_match_links(links, keywords=TARGET_KEYWORDS):
    """Return links whose path loosely matches target keywords."""
    matched = []
    for link in links:
        path = urlparse(link).path.lower()
        if any(kw in path for kw in keywords):
            matched.append(link)
    return matched

def get_relevant_links(base_url, html):
    """Extract internal links from homepage and fuzzy-match relevant ones."""
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(base_url)
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc == base.netloc and parsed.scheme in ("http", "https"):
            links.add(full)
    return fuzzy_match_links(list(links))

def scrape_company(url):
    """
    Multi-approach scraping:
    1. Fetch homepage
    2. Try sitemap for relevant pages
    3. Fallback: extract links from homepage and fuzzy-match
    Returns combined cleaned text (token-optimised, max ~4000 words).
    """
    base_url = url.rstrip("/")
    combined_text = []

    # Approach 1: Homepage
    homepage_html = fetch_page(base_url)
    if homepage_html:
        combined_text.append("=== HOMEPAGE ===\n" + clean_html(homepage_html))

    # Approach 2: Sitemap
    sitemap_urls = get_sitemap_urls(base_url)
    relevant_from_sitemap = fuzzy_match_links(sitemap_urls)[:4]

    # Approach 3: Link extraction from homepage
    if homepage_html:
        inline_links = get_relevant_links(base_url, homepage_html)
        relevant_from_inline = inline_links[:4]
    else:
        relevant_from_inline = []

    # Merge, deduplicate, prioritise
    all_relevant = list(dict.fromkeys(relevant_from_sitemap + relevant_from_inline))[:5]

    for link in all_relevant:
        if link == base_url:
            continue
        time.sleep(0.5)
        html = fetch_page(link)
        if html:
            section_name = urlparse(link).path.strip("/").replace("/", " > ") or "page"
            combined_text.append(f"=== {section_name.upper()} ===\n" + clean_html(html))

    full_text = "\n\n".join(combined_text)

    # Token optimisation: cap at ~4000 words (~5500 tokens)
    words = full_text.split()
    if len(words) > 4000:
        full_text = " ".join(words[:4000])

    return full_text


# ---------- AI Enrichment ----------

def enrich_with_ai(url, scraped_text):
    """Call Claude to extract structured company profile."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = """You are a precise business intelligence extractor. 
Your ONLY job is to extract factual information from the provided website text.

CRITICAL RULES:
- NEVER hallucinate or invent contact details, emails, phone numbers, or services.
- If a field is not found in the text, return "" or "N/A" — never guess.
- Emails must be real email addresses found in the text (contain @ symbol).
- Phone numbers must be real numbers found in the text.
- Return ONLY valid JSON. No markdown, no explanation, no backticks.
"""

    user_prompt = f"""Extract company information from the following website content.
URL: {url}

WEBSITE CONTENT:
{scraped_text}

Return a single JSON object with EXACTLY these fields:
{{
  "website_name": "Short brand/website name",
  "company_name": "Full legal or trade name of the company",
  "address": "Physical address if found, else N/A",
  "mobile_number": "Phone number if found, else N/A",
  "mail": ["list", "of", "email", "addresses", "found"],
  "core_service": "Primary service or product in one clear sentence",
  "target_customer": "Who they sell to",
  "probable_pain_point": "The main business problem their customers face",
  "outreach_opener": "A personalised 2-sentence cold outreach message mentioning the company name and their specific service"
}}

Remember: Only use information actually present in the website content. Return pure JSON only."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()

    data = json.loads(raw)

    # Enforce schema stability
    defaults = {
        "website_name": "N/A",
        "company_name": "N/A",
        "address": "N/A",
        "mobile_number": "N/A",
        "mail": [],
        "core_service": "N/A",
        "target_customer": "N/A",
        "probable_pain_point": "N/A",
        "outreach_opener": "N/A"
    }
    for key, default in defaults.items():
        if key not in data or data[key] is None:
            data[key] = default
    if not isinstance(data["mail"], list):
        data["mail"] = [data["mail"]] if data["mail"] else []

    data["source_url"] = url
    return data


# ---------- API Routes ----------

@app.route("/enrich", methods=["POST"])
def enrich():
    body = request.get_json(force=True)
    url = body.get("url", "").strip()
    website_name_hint = body.get("website_name", "").strip()

    if not url:
        return jsonify({"error": "URL is required"}), 400

    # Normalise URL
    if not url.startswith("http"):
        url = "https://" + url

    try:
        scraped = scrape_company(url)
        if not scraped:
            return jsonify({"error": "Could not scrape the website. It may be blocking crawlers."}), 422

        result = enrich_with_ai(url, scraped)

        # Apply website_name hint if provided and AI didn't find one
        if website_name_hint and result.get("website_name") in ("N/A", "", None):
            result["website_name"] = website_name_hint

        # Save to results
        results = load_results()
        # Avoid exact duplicate URLs
        results = [r for r in results if r.get("source_url") != url]
        results.append(result)
        save_results(results)

        return jsonify(result), 200

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned malformed JSON. Try again."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/results", methods=["GET"])
def results():
    return jsonify(load_results()), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
