import json
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def get_ft_headlines_filtered():
    url = 'https://www.ft.com'
    max_headlines = int(os.getenv("MAX_HEADLINES", "50"))

    # --- CI SPECIFIC OPTIONS ---
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")

    # Define junk words to filter out (Market data, menus)
    JUNK_WORDS = [
        "FTSE", "Euro/Dollar", "Pound/Dollar", "Brent Crude", "Minus", "Plus", 
        "OPEN SIDE", "Skip to", "Manage cookies", "Become a member", "Sign in"
    ]

    block_tags = {"Opinion", "Lex", "FT Magazine", "Life & Arts", "Interview", "Weekend", "HTSI"}
    block_headline_terms = [
        "opinion content", "lex.", "interview.", "ft magazine", "life & arts", "review", "how to"
    ]

    def is_news_item(headline: str, tag: str | None) -> bool:
        if tag and tag.strip() in block_tags:
            return False
        lowered = headline.lower()
        return not any(term in lowered for term in block_headline_terms)

    print("Launching Headless Browser...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    clean_headlines = [] # Initialize outside try block to ensure access

    try:
        print(f"Fetching {url}...")
        driver.get(url)

        # 1. SMART WAIT: Wait up to 20 seconds for actual article headlines to appear
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "o-teaser__heading"))
            )
            print("Page content loaded successfully.")
        except:
            print("Warning: Timed out waiting for specific article tags. Page might be blocked or slow.")

        # 2. Extract Headlines (Targeting the specific class first)
        headlines = driver.find_elements(By.CLASS_NAME, "o-teaser__heading")

        # Fallback: If specific class failed, grab all links but filter heavily
        if not headlines:
            print("Specific tags not found. Using fallback search...")
            links = driver.find_elements(By.TAG_NAME, "a")
            # Only keep links with substantial text
            headlines = [l for l in links if len(l.text.strip()) > 25]

        # 3. Process and Filter
        seen_urls = set()

        for item in headlines:
            text = item.text.strip()
            href = None
            tag_text = None

            try:
                link_el = item.find_element(By.XPATH, ".//a")
                href = link_el.get_attribute("href")
            except Exception:
                try:
                    href = item.get_attribute("href")
                except Exception:
                    href = None

            try:
                teaser = item.find_element(By.XPATH, "./ancestor::*[contains(@class,'o-teaser')][1]")
                try:
                    tag_text = teaser.find_element(By.CSS_SELECTOR, ".o-teaser__tag").text.strip()
                except Exception:
                    try:
                        tag_text = teaser.find_element(By.CSS_SELECTOR, "[data-trackable='teaser-tag']").text.strip()
                    except Exception:
                        tag_text = None
            except Exception:
                tag_text = None
            
            if (
                len(text) > 15
                and href
                and href not in seen_urls
                and not any(junk.lower() in text.lower() for junk in JUNK_WORDS)
                and is_news_item(text, tag_text)
            ):
                clean_headlines.append({"headline": text, "url": href, "tag": tag_text})
                seen_urls.add(href)
            
            if len(clean_headlines) >= max_headlines:
                break

        # 4. Output
        print(f"\nFound {len(clean_headlines)} Valid Articles. Here are the top {max_headlines}:\n")
        print("-" * 40)
        
        for i, item in enumerate(clean_headlines, 1):
            print(f"{i}. {item['headline']} ({item.get('tag')}) -> {item['url']}")

        print("-" * 40)

        # --- SAVE FOR PIPELINE (Added to connect to Next Step) ---
        # We convert the simple list of strings into a structured JSON 
        # that the Journalist script can consume.
        structured_data = []
        for i, item in enumerate(clean_headlines):
            headline = item['headline']
            tag = item.get('tag')
            category = tag if tag and len(tag) < 30 else "News"
            if category == "News":
                if "UK" in headline or "London" in headline:
                    category = "UK"
                elif "US" in headline or "Trump" in headline:
                    category = "US"
                elif any(term in headline for term in ["Tech", "AI", "Nvidia", "chip"]):
                    category = "Technology"
            structured_data.append({
                "id": i,
                "headline": headline,
                "category": category,
                "url": item['url'],
                "tag": tag
            })

        with open('headlines.json', 'w') as f:
            json.dump(structured_data, f, indent=2)
        print("Successfully saved headlines.json")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        driver.quit()

if __name__ == "__main__":
    get_ft_headlines_filtered()
