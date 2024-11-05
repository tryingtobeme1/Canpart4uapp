import os
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
from datetime import datetime
from webdriver_manager.chrome import ChromeDriverManager
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import re
from collections import Counter

def print_status(message):
    """Print status messages in a consistent format"""
    print(f"[STATUS] {message}")

class BrowserHandler:
    def __init__(self, headless=True):
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
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

class KennyUPullScraper:
    def __init__(self, location, make=None, model=None, year=None):
        print_status(f"Initializing browser for {location}...")
        self.location = location
        self.browser_handler = BrowserHandler()
        self.driver = self.browser_handler.get_driver()

        base_url = "https://kennyupull.com/auto-parts/our-inventory/?branch%5B%5D={branch_id}&nb_items=42&sort=date"
        make_filter = f"&input-select-brand-1621770108-auto-parts={make}" if make else ""
        model_filter = f"&input-select-model-661410576-auto-parts={model}" if model else ""
        year_filter = f"&input-select-model_year-443917684-auto-parts={year}" if year else ""

        self.url = base_url + make_filter + model_filter + year_filter
        self.urls = {
            'Ottawa': self.url.format(branch_id='1457192'),
            'Gatineau': self.url.format(branch_id='1457182'),
            'Cornwall': self.url.format(branch_id='1576848')
        }

    def scrape_page(self):
        print_status(f"Starting scrape for {self.location}...")

        try:
            self.driver.get(self.urls[self.location])
            print_status("Page loaded")

            time.sleep(5)

            print_status("Scrolling to load more content...")
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            while True:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            print_status("Waiting for car listings to load...")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "img[data-src]"))
            )

            car_elements = self.driver.find_elements(By.CSS_SELECTOR, "img[data-src]")
            print_status(f"Found {len(car_elements)} potential car listings")

            inventory = []
            for idx, car_element in enumerate(car_elements, 1):
                try:
                    title = car_element.get_attribute("alt")
                    image_url = car_element.get_attribute("data-src")
                    parent_element = car_element.find_element(By.XPATH, "../..")
                    detail_url = parent_element.find_element(By.TAG_NAME, "a").get_attribute("href")

                    car = {
                        'title': title,
                        'image_url': image_url,
                        'detail_url': detail_url,
                        'branch': self.location,
                    }
                    inventory.append(car)
                    print_status(f"Added car {idx}: {car['title']}")
                except Exception as e:
                    print_status(f"Error processing car {idx}: {str(e)}")
                    continue

            print_status(f"Successfully scraped {len(inventory)} vehicles from {self.location}")
            return inventory

        except Exception as e:
            print_status(f"Error during scraping: {str(e)}")
            return []

    def close(self):
        self.browser_handler.close()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/')
def home():
    """Render the main page"""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Kenny U-Pull Inventory Scraper</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f0f2f5; }
            .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .locations, .filter { margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 10px; }
            button { padding: 10px 20px; background-color: #007bff; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
            button:hover { background-color: #0056b3; }
            #status { margin-top: 20px; padding: 10px; background-color: #e9ecef; border-radius: 4px; }
            .card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); transition: transform 0.2s; }
            .card:hover { transform: translateY(-5px); }
            .card img { max-width: 100%; height: auto; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Kenny U-Pull Inventory Scraper</h1>
            <div class="locations">
                <button onclick="startScraping('Ottawa')">Scrape Ottawa</button>
                <button onclick="startScraping('Gatineau')">Scrape Gatineau</button>
                <button onclick="startScraping('Cornwall')">Scrape Cornwall</button>
            </div>
            <div id="status"></div>
            <div id="results"></div>
        </div>
        <script>
            function startScraping(location) {
                document.getElementById('status').innerHTML = `Scraping ${location}... please wait.`;
                fetch(`/scrape/${location}`)
                    .then(response => response.json())
                    .then(data => {
                        displayResults(data);
                        document.getElementById('status').innerHTML = `Scraping ${location} completed.`;
                    })
                    .catch(error => {
                        document.getElementById('status').innerHTML = `Error: ${error}`;
                    });
            }

            function displayResults(data) {
                const resultsDiv = document.getElementById('results');
                let html = '<div class="grid-container">';
                for (const [location, inventory] of Object.entries(data)) {
                    inventory.forEach(car => {
                        html += `
                            <div class="card">
                                <a href="${car.detail_url}" target="_blank">
                                    <img src="${car.image_url}" alt="${car.title}">
                                </a>
                                <div class="card-content">
                                    <h3>${car.title}</h3>
                                    <p>Branch: ${car.branch}</p>
                                </div>
                            </div>
                        `;
                    });
                }
                html += '</div>';
                resultsDiv.innerHTML = html;
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))  # Use the PORT environment variable or default to 8080
    app.run(host="0.0.0.0", port=port, debug=False)
