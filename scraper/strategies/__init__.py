# scraper/strategies/__init__.py
from scraper.strategies.scrapy_strategy import ScrapyScraper
from scraper.strategies.playwright_strategy import PlaywrightScraper

__all__ = ["ScrapyScraper", "PlaywrightScraper"]
