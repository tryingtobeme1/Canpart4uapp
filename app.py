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
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--start-maximized")
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

        # Updated URLs with 42 items for all locations, with dynamic filters for make, model, year
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

    def handle_cookies(self):
        print_status("Looking for cookie consent button...")
        time.sleep(5)
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for button in buttons:
                if "accept" in button.text.lower():
                    button.click()
                    print_status("Clicked accept cookies button")
                    time.sleep(2)
                    return True
            return False
        except Exception as e:
            print_status(f"Error handling cookies: {str(e)}")
            return False

    def scroll_to_load(self, pause_time=2):
        print_status("Scrolling to load more content...")
        for _ in range(3):
            try:
                last_height = self.driver.execute_script("return document.body.scrollHeight")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(pause_time)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            except Exception as e:
                print_status(f"Error during scrolling: {str(e)}")
                continue
        print_status("Scrolling completed.")

    def scrape_page(self):
        print_status(f"Starting scrape for {self.location}...")

        try:
            self.driver.get(self.urls[self.location])
            print_status("Page loaded")

            time.sleep(5)
            self.handle_cookies()

            self.scroll_to_load(pause_time=3)
            time.sleep(2)
            self.scroll_to_load(pause_time=3)

            print_status("Waiting for car listings to load...")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "img[data-src]"))
            )

            time.sleep(3)

            car_elements = self.driver.find_elements(By.CSS_SELECTOR, "img[data-src]")
            print_status(f"Found {len(car_elements)} potential car listings")

            inventory = []
            for idx, car_element in enumerate(car_elements, 1):
                try:
                    title = car_element.get_attribute("alt")
                    image_url = car_element.get_attribute("data-src")
                    parent_element = car_element.find_element(By.XPATH, "../..")
                    detail_url = parent_element.find_element(By.TAG_NAME, "a").get_attribute("href")

                    try:
                        date_listed = parent_element.find_element(By.CLASS_NAME, "infos--date").text
                    except:
                        try:
                            date_listed = parent_element.find_elements(By.CLASS_NAME, "info")[-1].text
                        except:
                            date_listed = "N/A"

                    try:
                        row_info = parent_element.find_element(By.XPATH, ".//p[@class='date info']").text
                    except:
                        row_info = "N/A"

                    if title:
                        car = {
                            'title': title,
                            'image_url': image_url,
                            'detail_url': detail_url,
                            'branch': self.location,
                            'date_listed': date_listed,
                            'row': row_info
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

class EbayScraper:
    def __init__(self):
        print_status("Initializing browser for eBay scraping...")
        self.browser_handler = BrowserHandler()
        self.driver = self.browser_handler.get_driver()

    def scrape_sold_items(self, vehicle_title, min_price=150, max_price=600):
        print_status(f"Starting eBay scrape for vehicle: {vehicle_title} with price range ${min_price} - ${max_price}...")
        try:
            # Construct the eBay search URL with filters
            base_url = "https://www.ebay.com/sch/i.html?_nkw={vehicle}&_sacat=0&LH_Sold=1&LH_Complete=1&LH_ItemCondition=4&_ipg=120&rt=nc"
            min_price_filter = f"&_udlo={min_price}" if min_price else ""
            max_price_filter = f"&_udhi={max_price}" if max_price else ""
            search_url = base_url.format(vehicle=vehicle_title.replace(' ', '+')) + min_price_filter + max_price_filter

            self.driver.get(search_url)
            print_status(f"Navigated to eBay search page for {vehicle_title}")

            WebDriverWait(self.driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.s-item"))
            )
            time.sleep(3)

            items = self.driver.find_elements(By.CSS_SELECTOR, "li.s-item")
            sold_items = []
            for idx, item in enumerate(items, 1):  # Iterate through all items found
                try:
                    # Attempt to locate the title element
                    try:
                        title = item.find_element(By.CSS_SELECTOR, "h3.s-item__title").text
                    except:
                        title = item.find_element(By.CSS_SELECTOR, "div.s-item__info a").text

                    # Attempt to locate the price element
                    try:
                        price = item.find_element(By.CSS_SELECTOR, ".s-item__price").text
                        price_value = float(re.sub(r'[^0-9.]', '', price))
                    except:
                        price_value = 0.0

                    # Attempt to locate the thumbnail URL and listing link
                    try:
                        thumbnail_url = item.find_element(By.CSS_SELECTOR, "img.s-item__image-img").get_attribute("src")
                        listing_url = item.find_element(By.CSS_SELECTOR, "a.s-item__link").get_attribute("href")
                    except:
                        thumbnail_url = ""
                        listing_url = ""

                    # Filter items based on the price range of $150 - $600
                    if 150 <= price_value <= 600:
                        sold_items.append({
                            'item_name': title,
                            'sold_price': price_value,
                            'thumbnail_url': thumbnail_url,
                            'listing_url': listing_url
                        })
                        print_status(f"Added sold item {idx}: {title} for ${price_value}")
                    else:
                        print_status(f"Skipped item {idx}: {title} with price ${price_value} (out of range)")
                except Exception as e:
                    print_status(f"Error processing eBay item {idx}: {str(e)}")
                    continue

            # Analyze sold items
            item_counter = Counter([item['item_name'] for item in sold_items])
            analysis = []
            for item_name, frequency in item_counter.items():
                total_price = sum(item['sold_price'] for item in sold_items if item['item_name'] == item_name)
                average_price = total_price / frequency
                analysis.append({
                    'item_name': item_name,
                    'average_price': average_price,
                    'frequency': frequency
                })

            return {'sold_items': sold_items, 'analysis': analysis}
        except Exception as e:
            print_status(f"Error during eBay scraping: {str(e)}")
            return {'error': str(e)}
        finally:
            self.close()

    def close(self):
        self.browser_handler.close()

# Flask Application
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
            body { 
                font-family: Arial, sans-serif; 
                max-width: 1200px; 
                margin: 0 auto; 
                padding: 20px;
                background-color: #f0f2f5;
                line-height: 1.6;
            }
            .container { 
                background: white; 
                padding: 20px; 
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .locations { 
                display: flex; 
                gap: 15px; 
                margin-bottom: 30px;
                flex-wrap: wrap;
                justify-content: space-around;
            }
            .filter { 
                margin-bottom: 30px;
                display: flex;
                flex-wrap: wrap;
                gap: 15px;
                align-items: center;
            }
            button {
                padding: 12px 24px;
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                transition: background-color 0.3s;
                font-size: 14px;
                font-weight: 500;
            }
            button:hover {
                background-color: #0056b3;
            }
            button:disabled {
                background-color: #cccccc;
                cursor: not-allowed;
            }
            #status {
                margin-top: 20px;
                padding: 10px;
                border-radius: 4px;
                background-color: #e9ecef;
                text-align: center;
            }
            #results {
                margin-top: 20px;
            }
            .grid-container {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 25px;
                margin-top: 20px;
                justify-items: center;
            }
            .card {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
                transition: transform 0.2s;
                width: 100%;
                max-width: 320px;
            }
            .card:hover {
                transform: translateY(-5px);
            }
            .card img {
                width: 100%;
                height: 180px;
                object-fit: cover;
                border-bottom: 1px solid #dee2e6;
            }
            .card-content {
                padding: 20px;
                text-align: center;
            }
            .card h3 {
                font-size: 1.2em;
                margin: 0 0 10px 0;
                color: #2c3e50;
            }
            .card p {
                margin: 5px 0;
                color: #6c757d;
                font-size: 0.9em;
            }
            .card a {
                text-decoration: none;
                color: inherit;
            }
            .card a:hover {
                color: #007bff;
            }
            .loading {
                display: none;
                text-align: center;
                margin: 20px 0;
                padding: 20px;
                background-color: #e9ecef;
                border-radius: 4px;
            }
            .progress {
                margin-top: 20px;
                padding: 15px;
                background-color: #d4edda;
                border-radius: 4px;
                color: #155724;
                text-align: center;
            }
            .timestamp {
                color: #6c757d;
                font-size: 0.9em;
                margin-top: 20px;
                text-align: right;
            }
            .error {
                color: #dc3545;
                padding: 15px;
                margin: 20px 0;
                border-radius: 4px;
                background-color: #f8d7da;
                text-align: center;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 30px;
            }
            table, th, td {
                border: 1px solid #dee2e6;
            }
            th, td {
                padding: 15px;
                text-align: center;
            }
            th {
                background-color: #f8f9fa;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Kenny U-Pull Inventory Scraper</h1>
            <div class="filter">
                <label for="make">Make:</label>
                <input type="text" id="make" name="make">
                <label for="model">Model:</label>
                <input type="text" id="model" name="model">
                <label for="year">Year:</label>
                <input type="text" id="year" name="year">
                <label for="min_price">Min Price:</label>
                <input type="text" id="min_price" name="min_price">
                <label for="max_price">Max Price:</label>
                <input type="text" id="max_price" name="max_price">
                <button onclick="startScrapingWithFilters()">Scrape with Filters</button>
            </div>
            <div class="locations">
                <button onclick="startScraping('Ottawa')" id="btn-ottawa">Scrape Ottawa</button>
                <button onclick="startScraping('Gatineau')" id="btn-gatineau">Scrape Gatineau</button>
                <button onclick="startScraping('Cornwall')" id="btn-cornwall">Scrape Cornwall</button>
                <button onclick="startScraping('all')" id="btn-all">Scrape All Locations</button>
            </div>
            <div id="status"></div>
            <div id="loading" class="loading">
                <p>Scraping in progress... Please wait...</p>
            </div>
            <div id="results"></div>
            <div id="timestamp" class="timestamp"></div>
        </div>

        <script>
            let allResults = {};
            
            function disableButtons(disable) {
                const buttons = ['ottawa', 'gatineau', 'cornwall', 'all'];
                buttons.forEach(btn => {
                    document.getElementById(`btn-${btn}`).disabled = disable;
                });
            }

            async function startScrapingWithFilters() {
                disableButtons(true);
                document.getElementById('loading').style.display = 'block';
                document.getElementById('results').innerHTML = '';
                document.getElementById('timestamp').innerHTML = '';
                allResults = {};

                const make = document.getElementById('make').value;
                const model = document.getElementById('model').value;
                const year = document.getElementById('year').value;
                const minPrice = document.getElementById('min_price').value;
                const maxPrice = document.getElementById('max_price').value;

                try {
                    const response = await fetch(`/scrape_ebay_with_filters?vehicle_title=${encodeURIComponent(make + ' ' + model + ' ' + year)}&min_price=${minPrice}&max_price=${maxPrice}`);
                    if (!response.ok) {
                        throw new Error(`Failed to fetch eBay data with filters. Status: ${response.status}`);
                    }
                    const data = await response.json();
                    displayEbayResults(data);
                } catch (error) {
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('status').innerHTML = `
                        <div class="error">Error: ${error.message}</div>
                    `;
                } finally {
                    disableButtons(false);
                    document.getElementById('loading').style.display = 'none';
                }
            }

            async function startScraping(location) {
                disableButtons(true);
                document.getElementById('loading').style.display = 'block';
                document.getElementById('results').innerHTML = '';
                document.getElementById('timestamp').innerHTML = '';
                allResults = {};

                try {
                    if (location.toLowerCase() === 'all') {
                        const locations = ['Ottawa', 'Gatineau', 'Cornwall'];
                        for (const loc of locations) {
                            document.getElementById('status').innerHTML = `<div class="progress">Scraping ${loc}...</div>`;
                            const response = await fetch(`/scrape/${loc}`);
                            if (!response.ok) {
                                throw new Error(`Failed to fetch data for ${loc}. Status: ${response.status}`);
                            }
                            const data = await response.json();
                            allResults = { ...allResults, ...data };
                            displayResults(allResults);
                        }
                    } else {
                        document.getElementById('status').innerHTML = `<div class="progress">Scraping ${location}...</div>`;
                        const response = await fetch(`/scrape/${location}`);
                        if (!response.ok) {
                            throw new Error(`Failed to fetch data for ${location}. Status: ${response.status}`);
                        }
                        const data = await response.json();
                        displayResults(data);
                    }
                    
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('status').innerHTML = 'Scraping completed!';
                    updateTimestamp();
                } catch (error) {
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('status').innerHTML = `
                        <div class="error">Error: ${error.message}</div>
                    `;
                } finally {
                    disableButtons(false);
                }
            }

            function displayResults(data) {
                const resultsDiv = document.getElementById('results');
                let html = '';
                
                for (const [location, inventory] of Object.entries(data)) {
                    html += `<h2>${location} Inventory (${inventory.length} vehicles)</h2>`;
                    html += '<div class="grid-container">';
                    
                    inventory.forEach(car => {
                        html += `
                            <div class="card">
                                <a href="${car.detail_url}" target="_blank">
                                    <img src="${car.image_url}" alt="${car.title}">
                                </a>
                                <div class="card-content">
                                    <h3><a href="${car.detail_url}" target="_blank">${car.title}</a></h3>
                                    <p><strong>Branch:</strong> ${car.branch}</p>
                                    <p><strong>Date Listed:</strong> ${car.date_listed}</p>
                                    <p><strong>Row:</strong> ${car.row}</p>
                                    <button onclick="searchEbay('${car.title}')">Search eBay for Parts</button>
                                </div>
                            </div>
                        `;
                    });
                    
                    html += '</div>';
                }
                
                resultsDiv.innerHTML = html;
            }

            async function searchEbay(carTitle) {
                try {
                    // Send the request to the backend to scrape eBay.
                    const response = await fetch(`/scrape_ebay/${encodeURIComponent(carTitle)}`);
                    if (!response.ok) {
                        throw new Error(`Failed to fetch eBay data for ${carTitle}. Status: ${response.status}`);
                    }
                    const data = await response.json();

                    // Display the results and analysis on the page.
                    displayEbayResults(data);

                } catch (error) {
                    document.getElementById('status').innerHTML = `
                        <div class="error">Error: ${error.message}</div>
                    `;
                }
            }

            function displayEbayResults(data) {
                const resultsDiv = document.getElementById('results');
                let html = '<h2>eBay Sold Listings Analysis</h2>';
                
                // Display Sold Items in a Table
                html += '<table><thead><tr><th>Item Name</th><th>Sold Price</th><th>Thumbnail</th><th>Link</th></tr></thead><tbody>';
                data.sold_items.forEach(item => {
                    html += `
                        <tr>
                            <td>${item.item_name}</td>
                            <td>$${item.sold_price.toFixed(2)}</td>
                            <td><img src="${item.thumbnail_url}" alt="${item.item_name}" style="height: 80px;"></td>
                            <td><a href="${item.listing_url}" target="_blank">View Listing</a></td>
                        </tr>
                    `;
                });
                html += '</tbody></table>';

                // Display Analysis Summary
                html += '<h2>Analysis Summary</h2>';
                html += '<table><thead><tr><th>Item Name</th><th>Average Price</th><th>Frequency</th></tr></thead><tbody>';
                data.analysis.forEach(result => {
                    html += `
                        <tr>
                            <td>${result.item_name}</td>
                            <td>$${result.average_price.toFixed(2)}</td>
                            <td>${result.frequency}</td>
                        </tr>
                    `;
                });
                html += '</tbody></table>';

                resultsDiv.innerHTML = html;
            }

            function updateTimestamp() {
                const timestamp = new Date().toLocaleString();
                document.getElementById('timestamp').innerHTML = `Last updated: ${timestamp}`;
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
    app.run(debug=True)
