import json
import os
import datetime
import concurrent.futures
from groq import Groq
from slugify import slugify 

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def get_todays_date():
    return datetime.datetime.now().strftime('%Y-%m-%d')

def write_article(item):
    headline = item['headline']
    category = item['category']
    
    print(f"Generating story for: {headline}...")

    # The Prompt: Explicitly asks for web research
    system_prompt = """
    You are a Financial Times journalist.
    Task: Write a short, factual news update based on the headline provided.
    Capabilities: USE YOUR INTERNET SEARCH TOOLS to find real facts from today.
    Format: Output PURE MARKDOWN. Do not output JSON.
    Structure:
    - Start with a strong lead paragraph (bold).
    - Use ## for subheaders.
    - Be concise (approx 300 words).
    - Tone: Professional, objective, British English.
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

    with open('headlines.json', 'r') as f:
        data = json.load(f)

    # Process Top 10 articles in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(write_article, data[:10])

if __name__ == "__main__":
    main()
