# Let's start with a clean slate and build the manual data entry app.
import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- Data Parsing Function ---

def parse_pasted_data(raw_text, rider_name, year):
    """
    This is the core function that takes the raw, pasted text and turns it
    into structured data. It now understands stage races.
    """
    parsed_entries = []
    lines = raw_text.strip().split('\n')
    current_stage_race_name = ""

    for line in lines:
        # Check for a stage race summary line first (e.g., "dd.mm › dd.mm Race Name")
        stage_race_match = re.search(r'^\d{2}\.\d{2}\s›\s\d{2}\.\d{2}\s+(.*)', line)
        if stage_race_match:
            # It's a stage race summary. We extract the name and wait for stage lines.
            full_line_text = stage_race_match.group(1).strip()
            # Clean up the name by removing extra text like "more" or classifications
            current_stage_race_name = re.split(r'\s*(?:more|\d+Youth|\d+Points|\d+General)', full_line_text)[0].strip()
            continue

        # Check for a single race day line (e.g., "dd.mm result Race Name distance")
        single_day_match = re.match(r'^(\d{2}\.\d{2})\s+', line)
        if single_day_match:
            date_str = single_day_match.group(1)
            rest_of_line = line[len(date_str):].strip()
            tokens = rest_of_line.split()

            if not tokens:
                continue

            # --- Extract Data from the tokens ---
            result = tokens[0]
            distance = 0.0
            distance_found_at_index = -1

            # Find the distance by searching from the end for a number
            for i in range(len(tokens) - 1, 0, -1):
                try:
                    distance = float(tokens[i])
                    distance_found_at_index = i
                    break
                except ValueError:
                    continue

            # The race name is everything between the result and the distance
            if distance_found_at_index != -1:
                race_name_tokens = tokens[1:distance_found_at_index]
            else:
                race_name_tokens = tokens[1:]

            individual_race_name = ' '.join(race_name_tokens)

            # Combine with stage race name if we're in one
            final_race_name = f"{current_stage_race_name}: {individual_race_name}" if current_stage_race_name else individual_race_name
            
            # If the race name doesn't seem like a stage, we assume the stage race has ended
            if not any(keyword in individual_race_name for keyword in ['Stage', 'Prologue', 'ITT', 'stage']):
                 current_stage_race_name = ""

            parsed_entries.append({
                'Rider': rider_name,
                'Year': year,
                'Date': date_str,
                'Result': result,
                'Race': final_race_name,
                'Distance': distance
            })

    return parsed_entries

# --- Streamlit App UI ---

st.set_page_config(layout="wide")
st.title('🚴 ProCycling Manual Data Analyzer')
st.write("Manually input team, rider, and season data to build your own cycling performance dashboard.")

# Initialize session state to hold data across reruns
if 'all_processed_data' not in st.session_state:
    st.session_state.all_processed_data = []

# --- Step 1: Team and Rider Setup ---
with st.expander("Step 1: Data Entry", expanded=True):
    team_name = st.text_input("Enter Team Name:", "My Custom Team")
    num_riders = st.number_input("How many riders do you want to enter?", min_value=1, value=1, step=1)

    all_rider_forms = []

    for i in range(num_riders):
        st.markdown("---")
        rider_name = st.text_input(f"Rider {i+1} Name:", key=f"rider_name_{i}")
        num_seasons = st.number_input(f"How many seasons for {rider_name or f'Rider {i+1}'}?", min_value=1, max_value=5, value=1, step=1, key=f"num_seasons_{i}")
        
        season_forms = []
        for j in range(num_seasons):
            st.markdown(f"**Season {j+1} for {rider_name or f'Rider {i+1}'}**")
            year = st.number_input("Year:", min_value=1990, max_value=datetime.now().year + 5, value=datetime.now().year, key=f"year_{i}_{j}")
            raw_text = st.text_area("Paste raw results data here:", height=200, key=f"text_{i}_{j}", placeholder="Paste the entire results block for one season from ProCyclingStats...")
            season_forms.append({'year': year, 'raw_text': raw_text})

        all_rider_forms.append({'name': rider_name, 'seasons': season_forms})

# --- Step 2: Process Data and Build Dashboard ---
st.markdown("---")
if st.button("📊 Process and Build Dashboard", type="primary"):
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
    
    st.subheader("Filter and View Data")
    all_riders = df['Rider'].unique()
    selected_riders = st.multiselect("Select riders to view:", options=all_riders, default=list(all_riders))
    
    if not selected_riders:
        st.warning("Please select at least one rider to see the analysis.")
    else:
        filtered_df = df[df['Rider'].isin(selected_riders)].copy()
        
        tab1, tab2, tab3, tab4 = st.tabs(["📈 Overall Comparison", "⏱️ Results Over Time", " riders Deep Dive", "📋 Raw Data Table"])

        with tab1:
            st.subheader("High-Level Comparison")
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Race Days Comparison")
                race_days = filtered_df.groupby('Rider').size().reset_index(name='Race Days')
                st.bar_chart(race_days, x='Rider', y='Race Days', use_container_width=True)

            with col2:
                st.markdown("#### Average Result by Month")
                df_monthly = filtered_df.copy()
                df_monthly['Result_Numeric'] = pd.to_numeric(df_monthly['Result'], errors='coerce')
                df_monthly['Month'] = df_monthly['Date'].apply(lambda x: int(x.split('.')[1]))
                monthly_performance = df_monthly.dropna(subset=['Result_Numeric']).groupby(['Rider', 'Month'])['Result_Numeric'].mean().reset_index()
                pivot_df = monthly_performance.pivot(index='Month', columns='Rider', values='Result_Numeric')
                st.line_chart(pivot_df, use_container_width=True)
                st.caption("Lower is better. Shows the average placing for each month.")

        with tab2:
            st.subheader("All Race Results Over Time")
            df_scatter = filtered_df.copy()
            df_scatter['Result_Numeric'] = pd.to_numeric(df_scatter['Result'], errors='coerce')
            df_scatter.dropna(subset=['Result_Numeric'], inplace=True)
            df_scatter['Full_Date'] = pd.to_datetime(df_scatter['Date'] + '.' + df_scatter['Year'].astype(str), format='%d.%m.%Y')
            
            st.scatter_chart(df_scatter, x='Full_Date', y='Result_Numeric', color='Rider', use_container_width=True)
            st.caption("Each point represents a single race result. Lower is better.")

        with tab3:
            st.subheader("Detailed Rider Breakdown")
            for rider in sorted(selected_riders):
                rider_df = filtered_df[filtered_df['Rider'] == rider].copy()
                
                with st.expander(f"View details for {rider}"):
                    rider_df['Result_Numeric'] = pd.to_numeric(rider_df['Result'], errors='coerce')
                    
                    total_race_days = len(rider_df)
                    total_distance = rider_df['Distance'].sum()
                    top_10s = len(rider_df[rider_df['Result_Numeric'] <= 10])

                    kpi_cols = st.columns(3)
                    kpi_cols[0].metric(label="Total Race Days", value=total_race_days)
                    kpi_cols[1].metric(label="Total Distance (km)", value=f"{total_distance:,.1f}")
                    kpi_cols[2].metric(label="Top 10 Finishes", value=top_10s)

                    st.markdown("**Best 3 Results**")
                    best_results = rider_df.dropna(subset=['Result_Numeric']).sort_values('Result_Numeric').head(3)
                    
                    if best_results.empty:
                        st.write("No numeric results found to determine best performances.")
                    else:
                        for index, row in best_results.iterrows():
                            st.write(f"**{int(row['Result_Numeric'])}.** in *{row['Race']}*")
        
        with tab4:
            st.subheader("Processed Data")
            st.dataframe(filtered_df, use_container_width=True)


