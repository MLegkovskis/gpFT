import json
import os
import datetime
import re
import time
import glob
import hashlib
from groq import Groq
from slugify import slugify

CONFIG_PATH = "main_configs.json"
FEED_PATH = os.path.join("_data", "feed.json")
POSTS_DIR = "_posts"

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

PLANNER_MODEL = "llama-3.3-70b-versatile"
RESEARCHER_MODEL = "groq/compound"
WRITER_MODEL = "openai/gpt-oss-120b"


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


def ensure_sources_section(markdown: str) -> str:
    """Ensure the markdown ends with a clean Sources section."""
    if re.search(r"(?im)^\s*###\s+Sources\s*$", markdown):
        return markdown.strip() + "\n"
    return markdown.strip() + "\n\n---\n### Sources\n- _Sources unavailable_\n"


def delete_all_posts(posts_dir=POSTS_DIR):
    if not os.path.exists(posts_dir):
        return
    for path in glob.glob(os.path.join(posts_dir, "*.md")):
        try:
            os.remove(path)
        except Exception:
            pass
    print("[mode] full_rebuild=true -> removed existing posts")


def generate_research_plan(headline):
    today = get_today_str()
    prompt = f"""
    You are a Senior Editor at the Financial Times. Today's date is {today} (UTC).
    We have a breaking headline: "{headline}".
    Generate 3 distinct investigative questions covering:
    1) hard data / numbers (GDP, stock moves, poll numbers)
    2) history or context
    3) market / political reaction or quotes

    Respond ONLY with a JSON array of strings, e.g.
    ["What are the GDP figures?", "How have markets reacted?", "What is the government's stance?"]
    """
    try:
        completion = client.chat.completions.create(
            model=PLANNER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        response = completion.choices[0].message.content
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as exc:
        print(f"Planning failed for {headline}: {exc}")
    return [f"What are the latest, verifiable facts regarding {headline}?"]


def conduct_deep_dive(question, query_context):
    today = get_today_str()
    prompt = f"""
    You are a research assistant with live web tools. Today's date is {today} (UTC).
    Verify each fact and do not invent dates.
    Topic: "{query_context}".

    Investigative Question: {question}

    Provide a dense factual answer with numbers, dates and quotes.
    Conclude with a short 'Sources used:' list containing Markdown links.
    Avoid inline bracket citations like 【Source】.
    """
    try:
        completion = client.chat.completions.create(
            model=RESEARCHER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            compound_custom={
                "tools": {
                    "enabled_tools": [
                        "web_search",
                        "code_interpreter",
                        "visit_website"
                    ]
                }
            }
        )
        return f"**Q: {question}**\n\n{completion.choices[0].message.content}\n\n"
    except Exception as exc:
        return f"Could not research '{question}': {exc}\n"


def write_final_story(headline, research_notes):
    today = get_today_str()
    system_prompt = f"""
    You are a senior correspondent for the Financial Times. Today's date is {today} (UTC).
    Write a 400-600 word article using ONLY the provided research notes.

    Style guide:
    - Tone: authoritative British English.
    - Structure: inverted pyramid; first paragraph must be **bolded**.
    - Do NOT include inline citations in the prose (no 【】 or bracket clutter).
    - List all references in a clean '### Sources' section at the end as bullet points with Markdown links.
    - Never invent dates or sequences. If a date is not clearly in the notes, omit it.
    - Output valid Markdown only.
    """
    user_prompt = f"""
    Headline: {headline}

    Research Notes:
    {research_notes}

    Produce the article now.
    """
    try:
        completion = client.chat.completions.create(
            model=WRITER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        content = completion.choices[0].message.content
        url_pattern = r"(?<![\(\[<\"])(https?://[^\s)]+)"
        content = re.sub(url_pattern, r"<\1>", content)
        content = re.sub(r"【[^】]{1,120}】", "", content)
        content = re.sub(r"[ \t]{2,}", " ", content)
        content = ensure_sources_section(content)
        return content
    except Exception as exc:
        print(f"Writing failed for {headline}: {exc}")
        return None


def process_single_article(item):
    headline = item['headline']
    category = item.get('category', 'News')
    source_url = item.get('url')
    print(f"⚡ Starting: {headline}...")

    questions = generate_research_plan(headline)[:3]

    research_notes = ""
    for question in questions:
        research_notes += conduct_deep_dive(question, headline)

    article_content = write_final_story(headline, research_notes)
    if not article_content:
        time.sleep(1)
        return

    slug = slugify(headline)
    date_slug = get_date_slug()
    time_str = get_current_time_str()
    url_hash = hashlib.sha1((source_url or headline).encode('utf-8')).hexdigest()[:8]
    filename = os.path.join(POSTS_DIR, f"{date_slug}-{slug}-{url_hash}.md")
    safe_title = headline.replace('"', "'")
    front_matter = (
        f"---\n"
        f"layout: post\n"
        f"title: \"{safe_title}\"\n"
        f"category: \"{category}\"\n"
        f"date: {time_str}\n"
        f"source_url: \"{source_url or ''}\"\n"
        f"source_site: \"ft.com\"\n"
        f"---\n\n"
    )
    with open(filename, "w", encoding="utf-8") as f:
        f.write(front_matter + article_content + "\n")
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
    print(
        f"[config] full_rebuild={cfg['full_rebuild']} max_active_posts={cfg['max_active_posts']} "
        f"max_new_articles={cfg['max_new_articles']}"
    )

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
        print("[delta] No new articles detected (delta is empty). Skipping LLM generation.")
        update_feed(scraped, load_existing_source_urls(), cfg['max_active_posts'])
        return

    print(f"[delta] Generating {len(candidates)} articles sequentially with rate limiting...")
    for idx, item in enumerate(candidates):
        process_single_article(item)
        if idx < len(candidates) - 1:
            print("   -> ⏳ Waiting 30 seconds before next article...")
            time.sleep(30)

    existing_urls = load_existing_source_urls()
    update_feed(scraped, existing_urls, cfg['max_active_posts'])


if __name__ == "__main__":
    main()
