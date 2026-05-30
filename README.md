# 🔬 CompanyLens — AI Business Intelligence Platform

AI-powered company enrichment tool built for the AI & Automation Developer Hackathon.

## 📁 Project Structure

```
company-enricher/
├── backend/
│   ├── app.py              ← Flask server (APIs + frontend)
│   ├── requirements.txt    ← Python dependencies
│   ├── Procfile            ← For Render/Railway deployment
│   └── templates/
│       └── index.html      ← Frontend UI
├── colab_pipeline.py       ← Subtask 1 Colab code
├── render.yaml             ← Render deployment config
└── README.md
```

---

## 🚀 Local Setup

### 1. Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 3. Run the server
```bash
python app.py
```

Open `http://localhost:5000` in your browser.

---

## 🌐 Deploy to Render (Free)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Set **Root Directory** to `backend`
5. Set **Build Command**: `pip install -r requirements.txt`
6. Set **Start Command**: `python app.py`
7. Add **Environment Variable**: `ANTHROPIC_API_KEY = sk-ant-your-key`
8. Click **Deploy** — your live URL appears in ~2 minutes

---

## 📡 API Reference

### POST /enrich
Enriches a single company URL.

**Request:**
```json
{
  "url": "https://stripe.com",
  "website_name": "Stripe"  
}
```

**Response:**
```json
{
  "website_name": "Stripe",
  "company_name": "Stripe, Inc.",
  "address": "354 Oyster Point Blvd, South San Francisco, CA",
  "mobile_number": "N/A",
  "mail": ["support@stripe.com"],
  "core_service": "Online payment processing for internet businesses",
  "target_customer": "Startups and enterprises needing payment infrastructure",
  "probable_pain_point": "Complex payment integrations and global compliance",
  "outreach_opener": "Hi Stripe team, ...",
  "source_url": "https://stripe.com"
}
```

### GET /results
Returns all previously enriched companies as a JSON array.

### GET /health
Returns `{"status": "ok"}` — use for uptime monitoring.

---

## 📓 Google Colab — Subtask 1

1. Open the provided Colab notebook link
2. **Cell 1**: Run `!pip install ...` to install dependencies
3. **Cell 2**: Set `os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."` 
4. **Cell 3**: Run all helper functions (no interaction)
5. **Cell 4**: Run → paste your URL array when prompted → get JSON output

**Input format:**
```
["https://stripe.com", "https://shopify.com"]
```

---

## 🧠 Technical Approach

### Smart Scraping (3 Approaches)
1. **Homepage** — Always scraped first
2. **Sitemap** — `/sitemap.xml` parsed for structured URL list
3. **Link extraction** — Internal links fuzzy-matched against `["about", "contact", "services", ...]`

### Token Optimisation
- Removes: `<script>`, `<style>`, `<nav>`, `<footer>`, cookie banners, modals
- Deduplicates repeated lines
- Hard cap at **4,000 words** before sending to AI

### Anti-Hallucination Prompting
- System prompt explicitly prohibits fabricating emails/phones
- Validates `mail` is a list of strings with `@` symbol
- Schema stability: all 9 fields always present, missing = `"N/A"` or `[]`

---

## ✅ Scoring Checklist

| Requirement | Status |
|---|---|
| POST /enrich API | ✅ |
| GET /results API | ✅ |
| Website Name input field | ✅ |
| Results display (cards) | ✅ |
| Loading state indicator | ✅ (Bonus +10) |
| JSON schema stability | ✅ |
| Anti-hallucination prompts | ✅ |
| Token optimisation | ✅ |
| Multi-approach scraping | ✅ |
| Colab with input prompt | ✅ |
| results.json output | ✅ |
