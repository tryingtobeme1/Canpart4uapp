import os
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, Response
from flask_cors import CORS
import threading
import queue
import re
from collections import Counter

def print_status(message):
    """Print status messages in a consistent format"""
    print(f"[STATUS] {message}")

class BrowserHandler:
    """
    Class to handle Chrome browser setup and teardown to reduce duplication.
    """
    def __init__(self, headless=True):
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")  # Required for Render
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        # Render specific paths for Chrome binary and driver
        chrome_bin_path = "/usr/bin/google-chrome"
        chrome_driver_path = "/usr/local/bin/chromedriver"
        
        chrome_options.binary_location = chrome_bin_path
        
        try:
            self.driver = webdriver.Chrome(
                executable_path=chrome_driver_path,
                options=chrome_options
            )
            print_status("Browser initialized successfully.")
        except Exception as e:
            print_status(f"Failed to initialize browser: {str(e)}")
            raise

    def get_driver(self):
        return self.driver

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
                print_status("Browser closed successfully.")
        except Exception as e:
            print_status(f"Error while closing the driver: {str(e)}")

# The rest of the code remains largely the same, including KennyUPullScraper, EbayScraper classes,
# and Flask app routes, as they rely on the driver being managed by BrowserHandler.

# Flask Application
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/')
def home():
    """Render the main page"""
    # HTML content remains the same
    # ...

@app.route('/scrape/<location>')
def scrape(location):
    """Handle scraping requests"""
    scraper = KennyUPullScraper(location)
    try:
        inventory = scraper.scrape_page()
        return jsonify({location: inventory})  # Return the scraped inventory as JSON
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        scraper.close()

@app.route('/scrape_ebay/<vehicle_title>')
def scrape_ebay(vehicle_title):
    """Handle eBay scraping requests for a given vehicle title"""
    scraper = EbayScraper()
    try:
        data = scraper.scrape_sold_items(vehicle_title)
        return jsonify(data)  # Return the eBay scraped data as JSON
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        scraper.close()

@app.route('/scrape_ebay_with_filters')
def scrape_ebay_with_filters():
    """Handle eBay scraping requests for a given vehicle title with filters"""
    vehicle_title = request.args.get('vehicle_title')
    min_price = request.args.get('min_price', default=150, type=int)
    max_price = request.args.get('max_price', default=600, type=int)
    scraper = EbayScraper()
    try:
        data = scraper.scrape_sold_items(vehicle_title, min_price, max_price)
        return jsonify(data)  # Return the eBay scraped data as JSON
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        scraper.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))  # Use 8080 as the default port
    app.run(host="0.0.0.0", port=port, debug=False)
