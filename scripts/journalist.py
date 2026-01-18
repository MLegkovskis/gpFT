import json
import os
import datetime
import re
import time
import glob
import hashlib
import requests
from groq import Groq
from slugify import slugify

CONFIG_PATH = "main_configs.json"
FEED_PATH = os.path.join("_data", "feed.json")
POSTS_DIR = "_posts"

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Using models capable of JSON mode
PLANNER_MODEL = "llama-3.3-70b-versatile"
RESEARCHER_MODEL = "groq/compound"
WRITER_MODEL = "llama-3.3-70b-versatile"


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        print(f"[config] Unable to read {CONFIG_PATH}: {exc}. Using defaults.")
        cfg = {}
    cfg.setdefault("full_rebuild", False)
    cfg.setdefault("max_active_posts", 20)
    cfg.setdefault("max_headlines", 50)
    cfg.setdefault("max_new_articles", 0)
    return cfg


def ensure_dirs():
    os.makedirs(POSTS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(FEED_PATH) or ".", exist_ok=True)
    if not os.path.exists(FEED_PATH):
        with open(FEED_PATH, "w", encoding="utf-8") as f:
            json.dump({"active": []}, f, indent=2)


def read_feed_urls():
    try:
        with open(FEED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("active", []))
    except Exception:
        return []


def write_feed_urls(urls):
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump({"active": urls}, f, indent=2)
    print(f"[feed] wrote {len(urls)} URLs to {FEED_PATH}")


def get_current_time_str():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def get_date_slug():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def get_today_str():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def load_existing_source_urls(posts_dir=POSTS_DIR) -> set[str]:
    urls = set()
    if not os.path.exists(posts_dir):
        return urls
    for path in glob.glob(os.path.join(posts_dir, "*.md")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            match = re.search(r"^source_url:\s*\"?(.+?)\"?\s*$", text, re.MULTILINE)
            if match:
                urls.add(match.group(1).strip())
        except Exception:
            continue
    return urls


def validate_and_clean_links(markdown_text):
    """Ping markdown links to strip 404s."""
    url_pattern = r"\[([^\]]+)\]\((https?://[^\)]+)\)"

    def check_link(match):
        text = match.group(1)
        url = match.group(2)
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.head(url, headers=headers, timeout=3, allow_redirects=True)
            if response.status_code == 404:
                print(f"    [Link Check] ❌ Dead link found and removed: {url}")
                return text
            return f"[{text}]({url})"
        except Exception:
            return text

    return re.sub(url_pattern, check_link, markdown_text)


def ensure_sources_section(markdown: str) -> str:
    if re.search(r"(?im)^\s*###\s+Sources", markdown):
        return markdown.strip() + "\n"
    return markdown.strip() + "\n\n---\n### Sources\n"


def delete_all_posts(posts_dir=POSTS_DIR):
    if not os.path.exists(posts_dir):
        return
    for path in glob.glob(os.path.join(posts_dir, "*.md")):
        try:
            os.remove(path)
        except Exception:
            pass
    print("[mode] full_rebuild=true -> removed existing posts")


def clean_json_response(content: str) -> str:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def generate_research_plan(headline):
    today = get_today_str()
    prompt = f"""
    You are a Senior Editor. Today is {today}.
    Headline: "{headline}"

    1. Classify this headline into one of these types: [Financial/Market], [Political], [General News/Culture], [Tech], [Sports].
    2. Generate 3 specific investigative questions.
       - If [Financial]: Ask about stock moves, GDP impact, revenue numbers.
       - If [General/Culture/Sports]: Ask about event details, quotes, and context. DO NOT ask for financial impact unless obvious.

    Respond ONLY with a JSON object in this format:
    {{
        "type": "Category Name",
        "questions": ["Question 1", "Question 2", "Question 3"]
    }}
    """
    try:
        completion = client.chat.completions.create(
            model=PLANNER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_content = completion.choices[0].message.content
        return json.loads(clean_json_response(raw_content))
    except Exception as exc:
        print(f"Planning failed for {headline}: {exc}")
        return {
            "type": "General News",
            "questions": [f"What are the verifiable facts regarding {headline}?"]
        }


def conduct_deep_dive(question, query_context):
    today = get_today_str()
    prompt = f"""
    You are a research assistant with live web tools. Today's date is {today} (UTC).
    Verify each fact.
    Topic: "{query_context}".

    Investigative Question: {question}

    Provide a dense factual answer with numbers, dates and quotes.
    Conclude with a short 'Sources used:' list containing Markdown links.
    """
    try:
        completion = client.chat.completions.create(
            model=RESEARCHER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            compound_custom={
                "tools": {
                    "enabled_tools": ["web_search", "code_interpreter", "visit_website"]
                }
            }
        )
        return f"**Q: {question}**\n\n{completion.choices[0].message.content}\n\n"
    except Exception as exc:
        return f"Could not research '{question}': {exc}\n"


def write_final_story(headline, research_notes, article_type):
    today = get_today_str()

    if len(research_notes) > 15000:
        print("   [Safety] Truncating research notes to avoid 413 Payload error.")
        research_notes = research_notes[:15000] + "\n...[truncated]..."

    if "Financial" in article_type or "Tech" in article_type:
        style_instruction = "Focus on numbers, market reaction, and economic implications."
    else:
        style_instruction = "Focus on the narrative and facts. DO NOT force financial metrics if not relevant."

    system_prompt = f"""
    You are a Journalist. Today's date is {today}.

    Task: Write an article based ONLY on the provided research notes.

    CRITICAL INSTRUCTIONS:
    1. **Data Check**: If notes say "could not research" or contain no facts, set "status" to "ABORT".
    2. **Relevance**: {style_instruction}
    3. **Sentiment**: Analyze the research. Score from 1 (Bearish/Negative) to 10 (Bullish/Positive).

    OUTPUT FORMAT (JSON ONLY):
    {{
        "status": "OK" or "ABORT",
        "sentiment_score": 7,
        "sentiment_label": "Cautiously Optimistic",
        "tldr": ["Bullet 1", "Bullet 2", "Bullet 3"],
        "body_markdown": "The full article in markdown...",
        "sources_markdown": "### Sources\n- [Link Title](url)..."
    }}
    """

    user_prompt = f"""
    Headline: {headline}
    Category: {article_type}

    Research Notes:
    {research_notes}
    """
    try:
        completion = client.chat.completions.create(
            model=WRITER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        raw_content = completion.choices[0].message.content
        return json.loads(clean_json_response(raw_content))
    except Exception as exc:
        print(f"Writing failed for {headline}: {exc}")
        return None


def process_single_article(item):
    headline = item['headline']
    category = item.get('category', 'News')
    source_url = item.get('url')
    print(f"⚡ Starting: {headline}...")

    plan_data = generate_research_plan(headline)
    article_type = plan_data.get("type", "General News")
    questions = plan_data.get("questions", [])[:3]

    print(f"   [Plan] Detected type: {article_type}")
    time.sleep(1)

    research_notes = ""
    valid_info_found = False

    for idx, question in enumerate(questions):
        print(f"   -> Researching ({idx + 1}/{len(questions)})...")
        note = conduct_deep_dive(question, headline)
        if len(note) > 100 and "could not research" not in note.lower():
            valid_info_found = True
        research_notes += note
        if idx < len(questions) - 1:
            print("      ⏳ Cooldown 5s...")
            time.sleep(5)

    if not valid_info_found:
        print(f"   [Skip] ❌ Research failed/insufficient data for: {headline}")
        return

    article_json = write_final_story(headline, research_notes, article_type)

    if not article_json or article_json.get("status") == "ABORT":
        print(f"   [Skip] ❌ Writer aborted (low quality data) for: {headline}")
        return

    content_body = article_json.get("body_markdown", "")
    sources = article_json.get("sources_markdown", "")
    tldr = article_json.get("tldr", [])
    sentiment_score = article_json.get("sentiment_score", 5)
    sentiment_label = article_json.get("sentiment_label", "Neutral")

    full_content = content_body + "\n\n" + sources

    if "I'm sorry" in full_content[:100] or "AI language model" in full_content[:100]:
        print(f"   [Skip] ❌ Writer refused prompt.")
        return

    full_content = validate_and_clean_links(full_content)
    full_content = re.sub(r"【[^】]+】", "", full_content)

    slug = slugify(headline)
    date_slug = get_date_slug()
    time_str = get_current_time_str()
    url_hash = hashlib.sha1((source_url or headline).encode('utf-8')).hexdigest()[:8]
    filename = os.path.join(POSTS_DIR, f"{date_slug}-{slug}-{url_hash}.md")

    safe_title = headline.replace('"', "'").replace(':', ' -')

    tldr_cleaned = [x.replace('"', "'").strip() for x in tldr]
    tldr_yaml = "\n".join([f'  - "{item}"' for item in tldr_cleaned])

    front_matter = (
        f"---\n"
        f"layout: post\n"
        f"title: \"{safe_title}\"\n"
        f"category: \"{category}\"\n"
        f"date: {time_str}\n"
        f"source_url: \"{source_url or ''}\"\n"
        f"sentiment_score: {sentiment_score}\n"
        f"sentiment_label: \"{sentiment_label}\"\n"
        f"tldr:\n{tldr_yaml}\n"
        f"---\n\n"
    )
    with open(filename, "w", encoding="utf-8") as f:
        f.write(front_matter + full_content + "\n")
    print(f"   -> ✅ Saved: {filename}")


def update_feed(scraped_items, existing_urls, max_active_posts):
    ensure_dirs()
    old_feed = read_feed_urls()
    scraped_urls = [item.get('url') for item in scraped_items if item.get('url')]

    new_feed = []
    for url in scraped_urls:
        if url in existing_urls and url not in new_feed:
            new_feed.append(url)
        if len(new_feed) >= max_active_posts:
            break

    if len(new_feed) < max_active_posts:
        for url in old_feed:
            if url in existing_urls and url not in new_feed:
                new_feed.append(url)
            if len(new_feed) >= max_active_posts:
                break

    write_feed_urls(new_feed)
    print(f"[feed] Active set size {len(new_feed)}/{max_active_posts}")


def main():
    cfg = load_config()
    ensure_dirs()
    print(f"[config] full_rebuild={cfg['full_rebuild']} max_active_posts={cfg['max_active_posts']}")

    if not os.path.exists('headlines.json'):
        print("No headlines found.")
        return

    with open('headlines.json', 'r', encoding='utf-8') as f:
        scraped = json.load(f)

    if cfg.get('full_rebuild'):
        delete_all_posts()
        existing_urls = set()
        candidates = [item for item in scraped if item.get('url')]
    else:
        existing_urls = load_existing_source_urls()
        candidates = [item for item in scraped if item.get('url') and item['url'] not in existing_urls]

    max_new = int(cfg.get('max_new_articles', 0))
    if max_new > 0:
        candidates = candidates[:max_new]

    if not candidates:
        print("[delta] No new articles detected.")
        update_feed(scraped, load_existing_source_urls(), cfg['max_active_posts'])
        return

    print(f"[delta] Processing {len(candidates)} articles...")
    for idx, item in enumerate(candidates):
        process_single_article(item)
        if idx < len(candidates) - 1:
            print("   -> ⏳ Cooldown (20s)...")
            time.sleep(20)

    update_feed(scraped, load_existing_source_urls(), cfg['max_active_posts'])


if __name__ == "__main__":
    main()
