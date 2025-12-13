import json
import os
import datetime
import concurrent.futures
import shutil
import re
import time
from groq import Groq
from slugify import slugify

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

PLANNER_MODEL = "llama-3.3-70b-versatile"
RESEARCHER_MODEL = "groq/compound"
WRITER_MODEL = "llama-3.3-70b-versatile"


def get_current_time_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_date_slug():
    return datetime.datetime.now().strftime('%Y-%m-%d')


def reset_posts_dir(posts_dir="_posts"):
    if os.path.exists(posts_dir):
        for entry in os.listdir(posts_dir):
            entry_path = os.path.join(posts_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    else:
        os.makedirs(posts_dir)
    os.makedirs(posts_dir, exist_ok=True)


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
            ]
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
    filename = f"_posts/{date_slug}-{slug}.md"
    file_content = f"""---
layout: post
title: "{headline.replace('"', "'")}"
category: "{category}"
date: {time_str}
author: "Groq AI"
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

    reset_posts_dir()

    with open('headlines.json', 'r') as f:
        data = json.load(f)

    articles = data[:5]
    print(f"Processing {len(articles)} articles in parallel...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_single_article, articles)


if __name__ == "__main__":
    main()
