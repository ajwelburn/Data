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

        # Find the main table containing the riders.
        rider_list_table = soup.find('table', class_='basic')
        if not rider_list_table:
            st.error("Could not find the rider list table on the team page.")
            return []

        # Find the body of the table.
        rider_table_body = rider_list_table.find('tbody')
        if not rider_table_body:
            st.error("Could not find the table body on the team page.")
            return []

        # Loop through each row to find the rider links.
        for row in rider_table_body.find_all('tr'):
            cell = row.find('td') # The link is in the first cell
            if cell:
                link = cell.find('a')
                if link and link.has_attr('href'):
                    # The links are relative, so we need to add the base URL.
                    full_url = base_url + link['href']
                    urls.append(full_url)
        
        return urls

    except requests.exceptions.RequestException as e:
        st.error(f"Failed to retrieve the team page. Error: {e}")
        return []

def scrape_single_rider(url, headers):
    """
    This function handles the logic for scraping one single rider page.
    """
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # The rider's name is usually in the main h1 tag.
        rider_name = soup.find('h1').get_text(strip=True).split('»')[0].strip()

        # The stats are in a specific div. We'll look for the "Race days" label.
        race_days = "N/A" # Default value
        stats_container = soup.find('div', class_='rdr-info-cont')
        if stats_container:
            # We look for all bold tags, as they are used as labels for stats.
            labels = stats_container.find_all('b')
            for label in labels:
                if 'Race days' in label.text:
                    # The number of race days is the text that comes right after the <b> tag.
                    race_days = label.next_sibling.strip()
                    break # Stop looking once we've found it.

        return {'Rider Name': rider_name, 'Number of Race Days': race_days}

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
