# Financial Clone

A Financial Times-inspired newsroom that runs entirely on GitHub Pages. Jekyll provides the "FT Pink" shell, Selenium scrapes live headlines from FT.com, Groq's `groq/compound` model writes real articles, and GitHub Actions glues everything together.

## Directory map

```
/
├── _layouts/            # default, home, and post views
├── assets/css/          # Custom FT styling
├── scripts/             # Selenium scraper and Groq journalist
├── _posts/              # Markdown articles generated daily
├── .github/workflows/   # Daily Edition workflow
├── _config.yml          # Jekyll config (update url/baseurl before deploying)
└── requirements.txt     # Python dependencies shared by CI and dev
```

## Local setup

1. Install Ruby + Bundler (for `jekyll-build-pages` parity) and run `bundle install` if needed.
2. Install Python deps: `pip install -r requirements.txt`.
3. Ensure Chrome is installed locally or adjust the Selenium driver path/options as needed.
4. Run `python scripts/scraper.py` to capture `headlines.json`.
5. Export `GROQ_API_KEY` and run `python scripts/journalist.py` to create `_posts/*.md`.
6. Serve locally with `bundle exec jekyll serve` to preview the FT-styled front page.

## Automation flow

`Daily Edition` GitHub Actions workflow:
1. Installs Python deps + Chrome on ubuntu-latest.
2. Runs the Selenium scraper to produce `headlines.json`.
3. Calls Groq Compound to draft Markdown articles with Jekyll front matter.
4. Commits new posts and then triggers `actions/jekyll-build-pages@v1` to deploy.

Add `GROQ_API_KEY` as a repository secret and enable GitHub Pages with the GitHub Actions source, then either run the workflow manually or wait for the 08:00 UTC schedule.
