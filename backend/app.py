import os
import json
import time
import re
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from groq import Groq

app = Flask(__name__)
CORS(app)

RESULTS_FILE = "results.json"

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return []

def save_results(data):
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

TARGET_KEYWORDS = [
    "about", "contact", "services", "service", "solutions",
    "team", "company", "who-we-are", "what-we-do", "our-work",
    "products", "offerings", "expertise", "capabilities"
]

def fetch_page(url, timeout=12):
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            time.sleep(1.5)
    return ""

def clean_html(html):
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(True):
            try:
                if tag.name in ["script", "style", "nav", "footer", "header",
                                 "noscript", "iframe", "svg", "form", "aside",
                                 "meta", "link", "button"]:
                    tag.decompose()
                    continue
                classes = tag.get("class") or []
                cls = " ".join(classes).lower() if isinstance(classes, list) else str(classes).lower()
                if any(kw in cls for kw in ["cookie", "banner", "popup", "modal", "overlay"]):
                    tag.decompose()
            except Exception:
                continue
        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        deduped, prev = [], None
        for line in lines:
            if line != prev:
                deduped.append(line)
            prev = line
        return "\n".join(deduped)
    except Exception:
        return ""

def get_sitemap_urls(base_url):
    urls = []
    for path in ["/sitemap.xml", "/sitemap_index.xml"]:
        try:
            resp = requests.get(base_url.rstrip("/") + path, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                locs = soup.find_all("loc")
                urls = [l.get_text().strip() for l in locs]
                if urls:
                    break
        except Exception:
            continue
    return urls

def fuzzy_match_links(links):
    matched = []
    for link in links:
        path = urlparse(link).path.lower()
        if any(kw in path for kw in TARGET_KEYWORDS):
            matched.append(link)
    return matched

def get_relevant_links_from_html(base_url, html):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(base_url)
    links = set()
    for a in soup.find_all("a"):
        try:
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin(base_url, href.strip())
            parsed = urlparse(full)
            if parsed.netloc == base.netloc and parsed.scheme in ("http", "https"):
                links.add(full)
        except Exception:
            continue
    return fuzzy_match_links(list(links))

def scrape_company(url):
    base_url = url.rstrip("/")
    combined_text = []

    homepage_html = fetch_page(base_url)
    if homepage_html:
        cleaned = clean_html(homepage_html)
        if cleaned:
            combined_text.append("=== HOMEPAGE ===\n" + cleaned)

    try:
        sitemap_urls = get_sitemap_urls(base_url)
        relevant_sitemap = fuzzy_match_links(sitemap_urls)[:4]
    except Exception:
        relevant_sitemap = []

    try:
        relevant_inline = get_relevant_links_from_html(base_url, homepage_html)[:4] if homepage_html else []
    except Exception:
        relevant_inline = []

    all_relevant = list(dict.fromkeys(relevant_sitemap + relevant_inline))[:5]

    for link in all_relevant:
        if link == base_url:
            continue
        try:
            time.sleep(0.5)
            html = fetch_page(link)
            if html:
                cleaned = clean_html(html)
                if cleaned:
                    section = urlparse(link).path.strip("/") or "page"
                    combined_text.append(f"=== {section.upper()} ===\n" + cleaned)
        except Exception:
            continue

    full_text = "\n\n".join(combined_text)
    words = full_text.split()
    if len(words) > 600:
        full_text = " ".join(words[:600])
    return full_text

def enrich_with_ai(url, scraped_text):
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    prompt = f"""Extract company information from this website content.
URL: {url}

CONTENT:
{scraped_text}

Return ONLY this JSON object. No markdown, no backticks, no explanation:
{{
  "website_name": "brand name",
  "company_name": "full company name",
  "address": "address or N/A",
  "mobile_number": "phone or N/A",
  "mail": ["emails found in text only"],
  "core_service": "main service in one sentence",
  "target_customer": "who they sell to",
  "probable_pain_point": "main problem they solve",
  "outreach_opener": "2 sentence personalised cold email opener mentioning company name"
}}
NEVER invent data. Only use what is in the content. Missing fields = N/A."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=800
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw.strip()).strip()

    data = json.loads(raw)

    defaults = {
        "website_name": "N/A", "company_name": "N/A",
        "address": "N/A", "mobile_number": "N/A", "mail": [],
        "core_service": "N/A", "target_customer": "N/A",
        "probable_pain_point": "N/A", "outreach_opener": "N/A"
    }
    for key, default in defaults.items():
        if key not in data or data[key] is None:
            data[key] = default
    if not isinstance(data["mail"], list):
        data["mail"] = [data["mail"]] if data["mail"] and data["mail"] != "N/A" else []

    data["source_url"] = url
    return data

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/test", methods=["GET"])
def test():
    try:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            return jsonify({"error": "GROQ_API_KEY not set"}), 500
        return jsonify({"status": "ok", "key_starts_with": key[:8]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/enrich", methods=["POST"])
def enrich():
    try:
        body = request.get_json(force=True, silent=True)
        if not body:
            return jsonify({"error": "Invalid JSON body"}), 400

        url = body.get("url", "").strip()
        website_name_hint = body.get("website_name", "").strip()

        if not url:
            return jsonify({"error": "URL is required"}), 400
        if not url.startswith("http"):
            url = "https://" + url

        scraped = scrape_company(url)
        if not scraped:
            return jsonify({"error": "Could not scrape the website."}), 422

        result = enrich_with_ai(url, scraped)

        if not result:
            return jsonify({"error": "AI returned empty result"}), 500

        if website_name_hint and result.get("website_name") in ("N/A", "", None):
            result["website_name"] = website_name_hint

        results = load_results()
        results = [r for r in results if r.get("source_url") != url]
        results.append(result)
        save_results(results)

        return jsonify(result), 200

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
