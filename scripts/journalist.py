import json
import os
import datetime
import concurrent.futures
import shutil
import re
from groq import Groq
from slugify import slugify

# --- CONFIGURATION ---
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

PLANNER_MODEL = "llama-3.3-70b-versatile"
RESEARCHER_MODEL = "groq/compound"
WRITER_MODEL = "llama-3.3-70b-versatile"


def get_todays_date():
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


# --- STAGE 1: PLANNER ---
def generate_research_plan(headline):
    prompt = f"""
    You are a Senior Editor at the Financial Times. We have a breaking headline: "{headline}".
    Generate exactly 3 distinct research questions that will arm reporters with:
    - hard data / numbers
    - context / history
    - market or political reactions

    Respond ONLY with a JSON array of strings.
    Example: ["What are the GDP figures?", "How have markets reacted?", "What is the government's stance?"]
    """

    try:
        completion = client.chat.completions.create(
            model=PLANNER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        response = completion.choices[0].message.content
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        print(f"Planning failed for {headline}: {e}")
    return [f"Provide the definitive update on: {headline}"]


# --- STAGE 2: RESEARCHER ---
def conduct_deep_dive(question, query_context):
    prompt = f"""
    You are a research assistant with live web tools.
    Story context: "{query_context}".

    Investigative Question: {question}

    Provide a dense, factual answer with numbers, dates and quotes.
    Cite every fact with Markdown links, e.g. [Reuters](https://www.reuters.com/...).
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


# --- STAGE 3: WRITER ---
def write_final_story(headline, research_notes):
    system_prompt = """
    You are a senior correspondent for the Financial Times.
    Write a news article ONLY using the supplied research notes.

    * Tone: authoritative, British English.
    * Structure: inverted pyramid; bold lede paragraph.
    * Length: 400-500 words.
    * Sources: integrate provided citations inline. Finish with a horizontal rule and a `### Sources` section listing the referenced URLs as Markdown links.
    """

    user_prompt = f"""
    Headline: {headline}

    Research Notes:
    {research_notes}

    Produce the article now. Output valid Markdown only.
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
    print(f"⚡ Processing: {headline}...")

    questions = generate_research_plan(headline)
    print(f"   -> Plan generated {len(questions)} angles.")

    research_notes = ""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(questions)) as executor:
        futures = [executor.submit(conduct_deep_dive, q, headline) for q in questions]
        for future in concurrent.futures.as_completed(futures):
            research_notes += future.result()
    print("   -> Research complete.")

    article_content = write_final_story(headline, research_notes)
    if not article_content:
        return

    slug = slugify(headline)
    date_str = get_todays_date()
    filename = f"_posts/{date_str}-{slug}.md"
    file_content = f"""---
layout: post
title: "{headline.replace('"', "'")}"
category: "{category}"
date: {date_str}
author: "Groq AI"
---

{article_content}
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(file_content)
    print(f"   -> ✅ Saved: {filename}")


def main():
    if not os.path.exists('headlines.json'):
        print("No headlines found.")
        return

    reset_posts_dir()

    with open('headlines.json', 'r') as f:
        data = json.load(f)

    for item in data[:5]:
        process_single_article(item)


if __name__ == "__main__":
    main()
