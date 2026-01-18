import sys
import os
import json
import logging
import time  # <--- Added import

# Add the current directory to sys.path to ensure imports work correctly
sys.path.append(os.getcwd())

from scripts.journalist import (
    generate_research_plan,
    conduct_deep_dive,
    write_final_story,
    validate_and_clean_links,
    slugify,
    get_date_slug,
    get_current_time_str
)

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

TEST_DIR = "test_posts"

def main():
    # 1. Get headline from command line args
    if len(sys.argv) < 2:
        print("\n⚠️  Usage: python local_write.py \"Your Headline Here\"\n")
        sys.exit(1)
    
    headline = sys.argv[1]
    
    print(f"\n🚀 STARTING LOCAL TEST")
    print(f"📰 Headline: \"{headline}\"")
    print(f"📂 Output Dir: {TEST_DIR}/")
    print("-" * 40)

    # Ensure test directory exists
    os.makedirs(TEST_DIR, exist_ok=True)

    # 2. PLAN
    print("\n🧠 Generating Research Plan...")
    plan_data = generate_research_plan(headline)
    article_type = plan_data.get("type", "General News")
    questions = plan_data.get("questions", [])
    
    print(f"   -> Category Detected: {article_type}")
    print(f"   -> Questions: {json.dumps(questions, indent=2)}")
    
    time.sleep(2) # Short pause after planning

    # 3. RESEARCH
    print("\n🔎 Conducting Deep Dive (this may take 30-60s)...")
    research_notes = ""
    valid_info = False

    for i, q in enumerate(questions):
        print(f"   -> Researching ({i+1}/{len(questions)}): {q}")
        note = conduct_deep_dive(q, headline)
        research_notes += note
        if len(note) > 100 and "could not research" not in note.lower():
            valid_info = True
        
        # --- RATE LIMIT PAUSE ---
        print("      ⏳ Cooldown 5s...")
        time.sleep(5) 

    if not valid_info:
        print("\n❌ RESEARCH FAILED: No valid info found. Aborting write.")
        return

    # 4. WRITE
    print("\n✍️  Writing Article with AI Journalist...")
    article_json = write_final_story(headline, research_notes, article_type)

    if not article_json or article_json.get("status") == "ABORT":
        print("\n❌ WRITER ABORTED: AI refused to write (insufficient data/quality).")
        return

    # 5. ASSEMBLE & VALIDATE
    print("\n✨ Assembling and Validating Links...")
    
    content_body = article_json.get("body_markdown", "")
    sources = article_json.get("sources_markdown", "")
    tldr = article_json.get("tldr", [])
    sentiment_score = article_json.get("sentiment_score", 5)
    sentiment_label = article_json.get("sentiment_label", "Neutral")

    full_content = content_body + "\n\n" + sources
    
    # Run the link validator
    full_content = validate_and_clean_links(full_content)
    
    # 6. SAVE
    slug = slugify(headline)
    date_slug = get_date_slug()
    filename = os.path.join(TEST_DIR, f"TEST-{date_slug}-{slug}.md")

    # Clean TLDR for YAML to avoid syntax errors
    tldr_cleaned = [x.replace('"', "'").strip() for x in tldr]
    tldr_yaml = "\n".join([f'  - "{item}"' for item in tldr_cleaned])

    front_matter = (
        f"---\n"
        f"layout: post\n"
        f"title: \"TEST: {headline}\"\n"
        f"category: \"{article_type}\"\n"
        f"date: {get_current_time_str()}\n"
        f"source_url: \"local_test\"\n"
        f"sentiment_score: {sentiment_score}\n"
        f"sentiment_label: \"{sentiment_label}\"\n"
        f"tldr:\n{tldr_yaml}\n"
        f"---\n\n"
    )

    with open(filename, "w", encoding="utf-8") as f:
        f.write(front_matter + full_content + "\n")

    print("-" * 40)
    print(f"✅ SUCCESS! Article saved to:\n   {filename}")
    print("-" * 40)

if __name__ == "__main__":
    main()