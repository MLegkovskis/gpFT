import json
import os
import datetime
import concurrent.futures
import re
import time
import glob
import hashlib
from groq import Groq
from slugify import slugify

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

PLANNER_MODEL = "llama-3.3-70b-versatile"
RESEARCHER_MODEL = "groq/compound"
WRITER_MODEL = "openai/gpt-oss-120b"


def get_current_time_str():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def get_date_slug():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def load_existing_source_urls(posts_dir="_posts") -> set[str]:
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


def generate_research_plan(headline):
    prompt = f"""
    You are a Senior Editor at the Financial Times. We have a breaking headline: "{headline}".
    Generate 3 distinct investigative questions covering:
    1) hard data/numbers (GDP, stock moves, poll numbers)
    2) history or context
    3) market/political reaction or quotes

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
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        print(f"Planning failed for {headline}: {e}")
    return [f"What are the latest, verifiable facts regarding {headline}?"]


def conduct_deep_dive(question, query_context):
    prompt = f"""
    You are a research assistant with live web tools.
    Topic: "{query_context}".

    Investigative Question: {question}

    Provide a dense factual answer with numbers, dates, quotes, and cite every statement with Markdown links (e.g. [Reuters](https://www.reuters.com/...))
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
    except Exception as e:
        return f"Could not research '{question}': {e}\n"


def write_final_story(headline, research_notes):
    system_prompt = """
    You are a senior correspondent for the Financial Times.
    Write a 400-500 word article using ONLY the provided research notes.

    Style guide:
    - Tone: authoritative British English.
    - Structure: inverted pyramid; bold lede paragraph.
    - Cite sources inline and/or conclude with a '### Sources' section listing Markdown links.
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
        return re.sub(url_pattern, r"<\1>", content)
    except Exception as e:
        print(f"Writing failed for {headline}: {e}")
        return None


def process_single_article(item):
    headline = item['headline']
    category = item['category']
    source_url = item.get('url')
    print(f"⚡ Starting: {headline}...")

    questions = generate_research_plan(headline)[:3]

    research_notes = ""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(questions)) as executor:
        futures = [executor.submit(conduct_deep_dive, q, headline) for q in questions]
        for future in concurrent.futures.as_completed(futures):
            research_notes += future.result()

    article_content = write_final_story(headline, research_notes)
    if not article_content:
        time.sleep(1)
        return

    slug = slugify(headline)
    date_slug = get_date_slug()
    time_str = get_current_time_str()
    url_hash = hashlib.sha1((source_url or headline).encode('utf-8')).hexdigest()[:8]
    os.makedirs("_posts", exist_ok=True)
    filename = f"_posts/{date_slug}-{slug}-{url_hash}.md"
    file_content = f"""---
layout: post
title: "{headline.replace('"', "'")}"
category: "{category}"
date: {time_str}
source_url: "{source_url or ''}"
source_site: "ft.com"
---

{article_content}
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(file_content)
    print(f"   -> ✅ Finished: {headline}")


def main():
    if not os.path.exists('headlines.json'):
        print("No headlines found.")
        return

    with open('headlines.json', 'r') as f:
        data = json.load(f)

    existing_urls = load_existing_source_urls("_posts")
    new_items = [item for item in data if item.get('url') and item['url'] not in existing_urls]

    max_new = int(os.getenv("MAX_NEW_ARTICLES", "0"))
    if max_new > 0:
        new_items = new_items[:max_new]

    if not new_items:
        print("No new articles detected (delta is empty).")
        return

    print(f"Processing {len(new_items)} NEW articles in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_single_article, new_items)


if __name__ == "__main__":
    main()
