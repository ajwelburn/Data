# Let's start with a clean slate and build the manual data entry app.
import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- Data Parsing Function ---

def parse_pasted_data(raw_text, rider_name, year):
    """
    This is the core function that takes the raw, pasted text and turns it
    into structured data (a list of race entries).
    """
    parsed_entries = []
    lines = raw_text.strip().split('\n')

    for line in lines:
        # We only care about lines that start with a date format (e.g., "dd.mm")
        # We explicitly ignore the multi-day tour summary lines (e.g., "dd.mm › dd.mm")
        match = re.match(r'^(\d{2}\.\d{2})\s+', line)
        
        if match:
            date_str = match.group(1)
            # Remove the date part to process the rest of the line
            rest_of_line = line[len(date_str):].strip()
            tokens = rest_of_line.split()

            if not tokens:
                continue

            # --- Extract Data from the tokens ---
            result = 'N/A'
            distance = 0.0
            race_name_tokens = []

            # The first token is almost always the result
            result = tokens[0]
            
            # Find the distance: search from the end for the first number-like token
            # This is more reliable than assuming it's always the very last token.
            distance_found_at_index = -1
            for i in range(len(tokens) - 1, 0, -1):
                try:
                    distance = float(tokens[i])
                    distance_found_at_index = i
                    break # Stop once we find it
                except ValueError:
                    continue # Not a number, keep searching

            # The race name is everything between the result and the distance
            if distance_found_at_index != -1:
                race_name_tokens = tokens[1:distance_found_at_index]
            else:
                # If no distance was found, the rest is the race name
                race_name_tokens = tokens[1:]

            race_name = ' '.join(race_name_tokens)
            
            # Use a dictionary to keep things neat
            parsed_entries.append({
                'Rider': rider_name,
                'Year': year,
                'Date': date_str,
                'Result': result,
                'Race': race_name,
                'Distance': distance
            })

    return parsed_entries

# --- Streamlit App UI ---

st.set_page_config(layout="wide")
st.title('ProCycling Manual Data Analyzer')
st.write("Manually input team, rider, and season data to build your own cycling performance dashboard.")

# Initialize session state to hold data across reruns
if 'all_processed_data' not in st.session_state:
    st.session_state.all_processed_data = []

# --- Step 1: Team and Rider Setup ---
st.header("Step 1: Team and Rider Setup")

team_name = st.text_input("Enter Team Name:", "My Custom Team")
num_riders = st.number_input("How many riders do you want to enter?", min_value=1, value=1, step=1)

# Create a container to hold all the rider forms
all_rider_forms = []

for i in range(num_riders):
    st.markdown("---")
    rider_name = st.text_input(f"Rider {i+1} Name:", key=f"rider_name_{i}")
    num_seasons = st.number_input(f"How many seasons for {rider_name or f'Rider {i+1}'}?", min_value=1, max_value=5, value=1, step=1, key=f"num_seasons_{i}")
    
    season_forms = []
    for j in range(num_seasons):
        st.markdown(f"**Season {j+1} for {rider_name or f'Rider {i+1}'}**")
        year = st.number_input("Year:", min_value=1990, max_value=datetime.now().year + 1, value=datetime.now().year, key=f"year_{i}_{j}")
        raw_text = st.text_area("Paste raw results data here:", height=200, key=f"text_{i}_{j}", placeholder="Paste the entire results block for one season from ProCyclingStats...")
        season_forms.append({'year': year, 'raw_text': raw_text})

    all_rider_forms.append({'name': rider_name, 'seasons': season_forms})

# --- Step 2: Process Data and Build Dashboard ---
st.markdown("---")
st.header("Step 2: Process and Analyze")

if st.button("Process and Build Dashboard", type="primary"):
    # Clear previous data before processing new data
    st.session_state.all_processed_data = []
    
    with st.spinner("Parsing all pasted data..."):
        for rider_form in all_rider_forms:
            rider_name = rider_form['name']
            if not rider_name:
                st.warning("Skipping a rider because their name is empty.")
                continue
            
            for season_form in rider_form['seasons']:
                year = season_form['year']
                raw_text = season_form['raw_text']
                if raw_text:
                    parsed_data = parse_pasted_data(raw_text, rider_name, year)
                    st.session_state.all_processed_data.extend(parsed_data)

    if not st.session_state.all_processed_data:
        st.error("No data was processed. Please paste some results data into the text areas.")
    else:
        st.success("Data processed successfully! Dashboard is ready below.")

# --- Step 3: The Dashboard (only shows if data has been processed) ---
if st.session_state.all_processed_data:
    st.markdown("---")
    st.header(f"Dashboard for {team_name}")
    
    df = pd.DataFrame(st.session_state.all_processed_data)
    
    # --- Data Filtering ---
    st.subheader("Filter and View Data")
    all_riders = df['Rider'].unique()
    selected_riders = st.multiselect("Select riders to view:", options=all_riders, default=list(all_riders))
    
    if not selected_riders:
        st.warning("Please select at least one rider to see the analysis.")
    else:
        filtered_df = df[df['Rider'].isin(selected_riders)].copy()

        # --- Analysis Section ---
        st.subheader("Performance Analysis")
        col1, col2 = st.columns(2)

        with col1:
            # 1. Race Day Comparison
            st.markdown("#### Race Days Comparison")
            race_days = filtered_df.groupby('Rider').size().reset_index(name='Race Days')
            st.bar_chart(race_days, x='Rider', y='Race Days')

        with col2:
            # 2. Performance by Month
            st.markdown("#### Average Result by Month")
            
            # Convert 'Result' to numeric, coercing errors (like 'DNF') to NaN
            filtered_df['Result_Numeric'] = pd.to_numeric(filtered_df['Result'], errors='coerce')
            
            # Extract month from date string
            filtered_df['Month'] = filtered_df['Date'].apply(lambda x: int(x.split('.')[1]))
            
            # Calculate average result, ignoring NaNs
            monthly_performance = filtered_df.dropna(subset=['Result_Numeric']).groupby(['Rider', 'Month'])['Result_Numeric'].mean().reset_index()
            
            # Create a pivot table for easier plotting
            pivot_df = monthly_performance.pivot(index='Month', columns='Rider', values='Result_Numeric')
            st.line_chart(pivot_df)
            st.caption("Lower is better. Shows the average placing for each month.")

        # --- Raw Data View ---
        st.subheader("Processed Data Table")
        st.dataframe(filtered_df)



