
# First, let's bring in the tools we'll need.
# It's like getting all your ingredients ready before you start cooking.
import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

def scrape_rider_data():
    """
    This is our main function, the heart of the operation. It will visit the website,
    grab the data we need, and organize it.
    """
    # The specific URL we are targeting.
    url = "https://www.procyclingstats.com/team/decathlon-ag2r-la-mondiale-development-team-2025/overview/start"

    # We need to act like a real browser, so we'll send some headers with our request.
    # This helps the website know we're a friendly visitor.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }

    try:
        # Let's try to get the webpage. We'll send our request with the URL and headers.
        response = requests.get(url, headers=headers)
        # This will raise an error if the request was not successful (like a 404 Not Found).
        response.raise_for_status()

        # Now, we'll use BeautifulSoup to parse the HTML content we received.
        # Think of it as a tool that helps us read and navigate the website's structure.
        soup = BeautifulSoup(response.content, 'html.parser')

        # We'll create two empty lists to store the data we find.
        rider_names = []
        race_days = []

        # --- FIX STARTS HERE ---
        # Instead of chaining .find() calls, we'll do it in steps to make it safer.
        # First, find the container div for the riders list.
        team_riders_div = soup.find('div', class_='team_riders_list')

        # If we can't find that div, the website structure has likely changed.
        if not team_riders_div:
            st.error("Could not find the rider list container on the page. The website structure has probably changed.")
            return None

        # Now, look for the table body (tbody) inside that div.
        rider_table = team_riders_div.find('tbody')
        # --- FIX ENDS HERE ---


        # If we can't find the table, something is wrong.
        if not rider_table:
            st.error("Could not find the rider data table on the page. The website structure might have changed.")
            return None

        # Now we'll go through each row (tr) in the table body. Each row is one rider.
        for row in rider_table.find_all('tr'):
            # The columns (td) in each row contain the specific pieces of info.
            cells = row.find_all('td')

            # We need to make sure the row has enough columns to avoid errors.
            if len(cells) > 3:
                # The rider's name is in the first cell (index 0) inside a link (a tag).
                rider_name_tag = cells[0].find('a')
                if rider_name_tag:
                    # We clean up the name a bit to make it look nice.
                    rider_name = ' '.join(rider_name_tag.text.split())
                    rider_names.append(rider_name)
                else:
                    # If we can't find a name, we'll add a placeholder.
                    rider_names.append("N/A")

                # The number of race days is in the fourth cell (index 3).
                races_completed = cells[3].text.strip()
                race_days.append(races_completed)


        # Now that we have our lists, let's put them into a pandas DataFrame.
        # A DataFrame is just a fancy table, which is perfect for our data.
        df = pd.DataFrame({
            'Rider Name': rider_names,
            'Number of Race Days': race_days
        })

        return df

    except requests.exceptions.RequestException as e:
        # If anything goes wrong with fetching the website, we'll show an error.
        st.error(f"Failed to retrieve the webpage. Please check the URL or your connection. Error: {e}")
        return None

# --- Streamlit App Interface ---

# Let's set a title for our web app. This shows up at the top.
st.title('ProCycling Team Race Day Counter')

st.write("This app scrapes rider data from the Decathlon AG2R La Mondiale Development Team page on ProCyclingStats.")

# We'll add a button to start the scraping process.
# This way, it only runs when the user wants it to.
if st.button('Fetch Rider Data'):
    # When the button is clicked, we'll show a message while it's working.
    with st.spinner('Scraping the website for data... please wait.'):
        # We call our main function to get the data.
        rider_df = scrape_rider_data()

        # If we successfully got the data, we'll display it.
        if rider_df is not None:
            st.success('Data scraped successfully!')
            # st.dataframe displays the data in a nice, interactive table.
            st.dataframe(rider_df)
