import json
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
        seen = set()

        for item in headlines:
            text = item.text.strip()
            
            # --- FILTER LOGIC ---
            # 1. Must be longer than 15 chars
            # 2. Must not be in our seen list
            # 3. Must not contain any "Junk Words"
            if (len(text) > 15 
                and text not in seen 
                and not any(junk.lower() in text.lower() for junk in JUNK_WORDS)):
                
                clean_headlines.append(text)
                seen.add(text)
            
            if len(clean_headlines) >= 25:
                break

        # 4. Output
        print(f"\nFound {len(clean_headlines)} Valid Articles. Here are the top 25:\n")
        print("-" * 40)
        
        for i, text in enumerate(clean_headlines, 1):
            print(f"{i}. {text}")

        print("-" * 40)

        # --- SAVE FOR PIPELINE (Added to connect to Next Step) ---
        # We convert the simple list of strings into a structured JSON 
        # that the Journalist script can consume.
        structured_data = []
        for i, h in enumerate(clean_headlines):
            # Guess category based on keywords
            cat = "Markets"
            if "UK" in h or "London" in h: cat = "UK"
            elif "US" in h or "Trump" in h: cat = "US"
            elif "Tech" in h or "AI" in h or "Nvidia" in h: cat = "Technology"
            
            structured_data.append({
                "id": i,
                "headline": h,
                "category": cat
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
