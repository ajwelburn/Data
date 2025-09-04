# First, let's bring in the tools we'll need.
# It's like getting all your ingredients ready before you start cooking.
import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

# --- Helper Functions for Scraping ---

def get_rider_urls(team_url, headers):
    """
    Visits the main team page and collects the URLs for each individual rider.
    """
    try:
        response = requests.get(team_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        urls = []
        base_url = "https://www.procyclingstats.com/"

        # Instead of looking for a specific heading, we'll find all lists (<ul>)
        # and check which one contains the rider links. This is more resilient.
        all_lists = soup.find_all('ul')
        rider_list_found = False

        for list_element in all_lists:
            # For each list, find all the links within it.
            links_in_list = list_element.find_all('a')
            potential_rider_links = []
            
            for link in links_in_list:
                # Check if the link looks like a rider profile link.
                if link.has_attr('href') and 'rider/' in link['href']:
                    full_url = base_url + link['href']
                    if full_url not in potential_rider_links:
                        potential_rider_links.append(full_url)
            
            # If we found valid rider links, we assume this is the correct list.
            if potential_rider_links:
                urls = potential_rider_links
                rider_list_found = True
                break # Stop searching after finding the first valid list.
        
        if not rider_list_found:
            st.error("Could not find a list containing rider links on the page. The website structure may have changed.")
            return []

        return urls

    except requests.exceptions.RequestException as e:
        st.error(f"Failed to retrieve the team page. Error: {e}")
        return []

def scrape_single_rider(url, headers):
    """
    This function scrapes a rider's page and counts their actual race days
    by looking at each entry in the results table.
    """
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # The rider's name is usually in the main h1 tag.
        rider_name_element = soup.find('h1')
        if not rider_name_element:
             return None # Can't find name, skip this rider
        rider_name = rider_name_element.get_text(strip=True).split('»')[0].strip()

        # --- NEW, MORE ROBUST LOGIC FOR COUNTING RACE DAYS ---
        race_day_count = 0
        
        # The race results are in a table with class 'basic'.
        results_table = soup.find('table', class_='basic')
        
        if results_table:
            table_body = results_table.find('tbody')
            if table_body:
                rows = table_body.find_all('tr')
                for row in rows:
                    # Find the first column, which should contain the date.
                    date_cell = row.find('td')
                    if date_cell:
                        date_text = date_cell.get_text(strip=True)
                        
                        # A valid race day is any row with a date that is NOT a date range.
                        # This correctly counts one-day races AND individual stages.
                        if date_text and '›' not in date_text:
                            race_day_count += 1
        
        return {'Rider Name': rider_name, 'Number of Race Days': race_day_count}

    except requests.exceptions.RequestException:
        # We won't show an error for every single failed URL, just skip it.
        return None
    except Exception:
        # If the page structure is weird, we'll also just skip it.
        return None

# --- Main Application Logic ---

st.title('ProCycling Team Data Scraper')
st.write("Click the button to automatically fetch all rider data from the Decathlon AG2R La Mondiale Development Team page.")

# The URL of the team we are targeting.
team_url = "https://www.procyclingstats.com/team/decathlon-ag2r-la-mondiale-development-team-2025/overview/start"

if st.button('Fetch All Rider Data'):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.302_scraper.py9.110 Safari/537.36'
    }

    # Step 1: Get all the individual rider URLs from the team page.
    with st.spinner("Step 1: Finding all rider links on the team page..."):
        rider_urls = get_rider_urls(team_url, headers)

    if not rider_urls:
        st.error("Halting process. Could not retrieve any rider links.")
    else:
        st.success(f"Found {len(rider_urls)} riders. Now fetching their data...")
        
        all_rider_data = []
        progress_bar = st.progress(0)

        # Step 2: Loop through each URL and scrape the data.
        for i, url in enumerate(rider_urls):
            rider_data = scrape_single_rider(url, headers)
            if rider_data:
                all_rider_data.append(rider_data)
            
            # To be a good web citizen, let's wait a tiny bit between requests.
            time.sleep(0.2) 
            
            # Update the progress bar and status text
            progress_bar.progress((i + 1) / len(rider_urls), text=f"Scraping rider {i+1} of {len(rider_urls)}")

        progress_bar.empty() # Clear the progress bar

        # Step 3: Display the results.
        if all_rider_data:
            st.success('Data scraping complete!')
            df = pd.DataFrame(all_rider_data)
            st.dataframe(df)
        else:
            st.error("Could not retrieve data for any of the riders.")
