import json
import os
import datetime
import concurrent.futures
import shutil
from groq import Groq
from slugify import slugify 

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def get_todays_date():
    return datetime.datetime.now().strftime('%Y-%m-%d')


def reset_posts_dir(posts_dir="_posts"):
    """Remove all existing posts to keep deployments in lockstep with a run."""
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

def write_article(item):
    headline = item['headline']
    category = item['category']
    
    print(f"Generating story for: {headline}...")

    # The Prompt: Explicitly asks for web research
    system_prompt = """
    You are a senior market correspondent emulating the prestigious editorial voice of the Financial Times.
    Your task is to write a fresh, high-caliber articles based on the provided headline.

    **CRITICAL SOURCING PROTOCOL:**
    The original source is behind a paywall. **Do not** attempt to access it or reference it directly.
    Instead, use your web browsing capabilities to **triangulate the story** using reputable open-web sources. 
    Reconstruct the narrative using these public facts, ensuring the data is current and accurate.

    **EDITORIAL GUIDELINES (The "Pink Paper" Style):**
    1. **Tone:** Authoritative, understated, and analytical. Avoid sensationalism, adverbs, and "clickbait" phrasing.
    2. **Language:** Strict British English (e.g., 'labour', 'defence', 'programme').
    3. **Data-Density:** Prioritize hard numbers, timestamps, and percent changes over vague descriptions.
    4. **Structure:** Use the "Inverted Pyramid". Start with the most critical info.

    **FORMATTING REQUIREMENTS:**
    - **The Lede:** The first paragraph must be **bolded** and act as a comprehensive "nut graf" (summary).
    - **Subheads:** Use `##` for clear, professional section breaks.
    - **Length:** Approximately 350-400 words.

    **OUTPUT:**
    Return ONLY valid Markdown. Do not include preambles like "Here is the article" or "I have found...". Start directly with the story.
    """


    user_prompt = f"Headline: '{headline}'. Find the latest details and write the article."

    try:
        completion = client.chat.completions.create(
            model="groq/compound", # Internet Connected Model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        content = completion.choices[0].message.content
        
        # Create Jekyll Front Matter
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

{content}
"""
        # Ensure _posts exists
        os.makedirs("_posts", exist_ok=True)
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        print(f"Saved: {filename}")

    except Exception as e:
        print(f"Error on {headline}: {e}")

def main():
    if not os.path.exists('headlines.json'):
        print("No headlines found.")
        return

    reset_posts_dir()

    with open('headlines.json', 'r') as f:
        data = json.load(f)

    # Process the top five articles to respect API limits
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(write_article, data[:5])

if __name__ == "__main__":
    main()
