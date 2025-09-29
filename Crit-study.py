import streamlit as st
import pandas as pd
import fitparse
import matplotlib.pyplot as plt
import io
import math
from pandas import ExcelWriter

# --- App Configuration ---
st.set_page_config(
    page_title="Analyse | Cycling Tool",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------
# Data Processing & Analysis Functions
# -------------------
@st.cache_data
def parse_fit_file(uploaded_file):
    """Parses an uploaded .fit file and returns a DataFrame with time and power."""
    uploaded_file.seek(0)
    try:
        fitfile = fitparse.FitFile(uploaded_file)
        # Extract records that have a non-null power value
        records = [
            data for record in fitfile.get_messages('record')
            if (data := record.get_values()) and 'power' in data and data['power'] is not None
        ]
    except Exception as e:
        return f"Error parsing {uploaded_file.name}: {e}"
    if not records: return None

    df = pd.DataFrame(records)
    # Resample to 1-second intervals to ensure consistent data points
    df = df.set_index('timestamp').resample('1S').ffill().reset_index()
    # Calculate elapsed time in seconds
    df['time'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df[['time', 'power']]

def analyze_bouts(time_values, power_values, cp):
    """Identifies high-intensity bouts from power data based on a CP threshold."""
    threshold_factor = 1.00  # Set threshold to 100% of CP
    threshold_power = cp * threshold_factor
    min_bout_duration = 3
    gap_tolerance = 3  # Allow for short drops below the threshold
    bouts = []
    duration, avg_power, below_counter, start_time = 0, 0, 0, None

    for t, p in zip(time_values, power_values):
        if p > threshold_power:
            if duration == 0: start_time = t
            duration += 1
            avg_power += p
            below_counter = 0
        else:
            if duration > 0:
                below_counter += 1
                if below_counter <= gap_tolerance:
                    # If within tolerance, continue the bout
                    duration += 1
                    avg_power += p
                else:
                    # If gap is too long, end the bout
                    if duration >= min_bout_duration:
                        magnitude = (avg_power / duration / cp) * 100
                        if magnitude >= threshold_factor * 100:
                            bouts.append({'start_time': start_time, 'duration': duration, 'magnitude': magnitude})
                    duration, avg_power, below_counter, start_time = 0, 0, 0, None

    # Check for a bout that might be ongoing at the end of the file
    if duration >= min_bout_duration:
        magnitude = (avg_power / duration / cp) * 100
        if magnitude >= threshold_factor * 100:
            bouts.append({'start_time': start_time, 'duration': duration, 'magnitude': magnitude})

    bouts_df = pd.DataFrame(bouts)
    if not bouts_df.empty:
        # Assign colors for plotting based on magnitude
        bouts_df['color'] = bouts_df['magnitude'].apply(lambda mag: 'red' if mag >= 170 else ('orange' if mag >= 140 else 'blue'))
    return bouts_df

def calculate_w_prime_balance(power_series, cp, w_prime, A, B):
    """Calculates the W' balance over time using a differential recovery model."""
    w_balance = w_prime
    w_bal_list = []
    for p in power_series:
        if p > cp:
            w_balance -= (p - cp)  # Expenditure
        else:
            w_expended = w_prime - w_balance
            delta_p = cp - p
            if delta_p > 0:
                tau = A * (delta_p ** B)
                if tau > 0:
                    w_balance += w_expended * (1 - math.exp(-1 / tau))  # Recovery
        w_balance = min(w_prime, max(0, w_balance))
        w_bal_list.append(w_balance)
    return pd.Series(w_bal_list)

def calculate_depletions_and_zones(w_bal_series, w_prime, time_series):
    """Counts critical depletions and calculates time spent in W' balance zones."""
    # The total duration for percentage calculation is the length of the selected time series
    total_duration = len(time_series)
    depletion_threshold = 0.15 * w_prime
    depletion_count = 0
    depletion_times = []
    below_threshold = False

    for i, val in enumerate(w_bal_series):
        if val < depletion_threshold and not below_threshold:
            depletion_count += 1
            # Get the actual time value from the time_series at the specific index
            depletion_times.append(time_series.iloc[i])
            below_threshold = True
        elif val >= depletion_threshold:
            below_threshold = False

    w_bal_percent = (w_bal_series / w_prime) * 100
    bins = [-1, 10, 15, 25, 50, 70, 101]
    labels = ['0-10%', '10-15%', '15-25%', '25-50%', '50-70%', '70-100%']

    if w_bal_percent.empty:
        zone_counts = pd.Series(0, index=labels)
    else:
        zone_counts = pd.cut(w_bal_percent, bins=bins, labels=labels, right=False).value_counts().sort_index()

    zone_data = pd.DataFrame({
        'Time (s)': zone_counts,
        'Time (%)': (zone_counts / total_duration * 100).round(2) if total_duration > 0 else 0
    })
    return depletion_count, zone_data, depletion_times

# -------------------
# Plotting & Export Functions
# -------------------

def create_summary_plots(bouts_df, cp, w_prime, title_prefix=""):
    """Creates a scatter plot of bout magnitude vs. duration."""
    if bouts_df.empty:
        st.warning(f"No bouts detected for {title_prefix} analysis.")
        return

    bout_durations = bouts_df['duration']
    magnitudes = bouts_df['magnitude']
    # Set default colors from the initial analysis
    bout_colors = bouts_df['color']

    # Apply "Research Grade" styling ONLY for the combined chart
    if "Combined" in title_prefix:
        st.subheader("Combined Magnitude vs. Bout Duration (Research Grade)")
        fig1, ax1 = plt.subplots(figsize=(8, 6), dpi=300)
        
        # Calculate new bout colors based on W' depletion for the combined chart
        bouts_df['depletion'] = (cp * (bouts_df['magnitude'] / 100 - 1) * bouts_df['duration']) / w_prime * 100

        def get_depletion_color(depletion):
            if depletion <= 10: return 'blue'
            elif depletion <= 20: return 'orange'
            elif depletion <= 40: return 'yellow'
            elif depletion <= 50: return 'lightcoral'
            else: return 'red'

        bout_colors = bouts_df['depletion'].apply(get_depletion_color)

        font_settings = {'fontfamily': 'Arial', 'fontsize': 12, 'fontweight': 'bold'}
        title_font_settings = {'fontfamily': 'Arial', 'fontsize': 16, 'fontweight': 'bold'}
        
        ax1.set_xlabel('Bout Duration (s)', **font_settings)
        ax1.set_ylabel('Magnitude (% of CP)', **font_settings)
        ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>100% CP)', **title_font_settings)

        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['left'].set_linewidth(1.5)
        ax1.spines['bottom'].set_linewidth(1.5)
        ax1.tick_params(width=1.5, labelsize=10)
        
        # Remove grid lines for the research grade chart
        ax1.grid(False)
        
    else:  # Keep original styling for individual file charts
        st.subheader(f"{title_prefix}Magnitude vs. Bout Duration")
        fig1, ax1 = plt.subplots(figsize=(10, 5))
        ax1.set_xlabel('Bout Duration (s)')
        ax1.set_ylabel('Magnitude (% of CP)')
        ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>100% CP)')
        ax1.grid(alpha=0.4)

    # Common plotting logic for both chart styles
    ax1.scatter(bout_durations, magnitudes, c=bout_colors, alpha=0.7, label='Individual Bouts', edgecolor='black', linewidth=0.2)
    avg_duration = bout_durations.mean()
    avg_magnitude = magnitudes.mean()
    ax1.scatter(avg_duration, avg_magnitude, color='black', marker='X', s=200, edgecolor='white', linewidth=1.5, label=f'Overall Average ({avg_duration:.0f}s, {avg_magnitude:.0f}%)', zorder=5)

    # Plot W' depletion curves for reference
    if "Combined" in title_prefix:
        grayscale_colors = ['0.0', '0.3', '0.45', '0.6', '0.75']  # Black to lightest grey
        for i, depletion in enumerate(range(10, 60, 10)):
            x_values = range(1, 71)
            w_prime_depleted = w_prime * (depletion / 100)
            y_values = [(((w_prime_depleted / t) + cp) / cp) * 100 for t in x_values]
            ax1.plot(x_values, y_values, color=grayscale_colors[i], linestyle='--', linewidth=1.2, label=f"{depletion}% W'")
    else:
        for depletion in range(10, 60, 10):
            x_values = range(1, 71)
            w_prime_depleted = w_prime * (depletion / 100)
            y_values = [(((w_prime_depleted / t) + cp) / cp) * 100 for t in x_values]
            ax1.plot(x_values, y_values, 'k:', linewidth=0.7, label=f"{depletion}% W'")

    # Set common axis limits
    ax1.set_ylim(100, max(250, magnitudes.max() * 1.1 if not magnitudes.empty else 250))
    ax1.set_xlim(0, 70)
    
    # Customize legend for the research plot
    if "Combined" in title_prefix:
        ax1.legend(fontsize=10, frameon=False)
        fig1.subplots_adjust(top=0.92) # Add space above the title
    else:
        ax1.legend()
        
    st.pyplot(fig1)

def plot_w_prime_balance(time_series, w_bal_series, w_prime):
    """Plots the W' balance over time."""
    w_bal_percent = (w_bal_series / w_prime) * 100
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time_series, w_bal_percent, color='green', linewidth=1.5)
    ax.fill_between(time_series, 0, w_bal_percent, color='green', alpha=0.2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("W' Balance (%)")
    ax.set_title("W' Balance Over Time")
    ax.set_ylim(0, 105)
    ax.set_xlim(0, time_series.max() if not time_series.empty else 1)
    ax.grid(alpha=0.3)
    return fig

def generate_excel_output(all_files_data, cp, w_prime):
    """Generates an Excel file with all analysis data."""
    output = io.BytesIO()
    with ExcelWriter(output, engine='openpyxl') as writer:
        # Consolidate all bouts from all files into a single DataFrame
        all_bouts_df = pd.concat([f['bouts_df'] for f in all_files_data if not f['bouts_df'].empty], ignore_index=True)

        # Generate the W' depletion curves data
        w_prime_curves_data = {'Time (s)': range(1, 71)}
        for depletion in range(10, 60, 10):
            w_prime_curves_data[f"{depletion}% W' Depletion (%CP)"] = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in w_prime_curves_data['Time (s)']]
        w_prime_curves_df = pd.DataFrame(w_prime_curves_data)

        # Sheet 1: Combined Bouts and Depletion Curves
        # Merge the bout data with the corresponding W' depletion curve values based on duration
        if not all_bouts_df.empty:
            # Round duration to handle any potential floating point issues and convert to int
            all_bouts_df['duration'] = all_bouts_df['duration'].round().astype(int)
            
            combined_df = pd.merge(
                all_bouts_df,
                w_prime_curves_df,
                left_on='duration',
                right_on='Time (s)',
                how='left'
            )
            combined_df.drop(columns=['Time (s)'], inplace=True, errors='ignore')
            combined_df.to_excel(writer, sheet_name='Bouts vs Depletion Curves', index=False)
        else:
            # Create an empty sheet if there are no bouts, to maintain a consistent file structure
            pd.DataFrame().to_excel(writer, sheet_name='Bouts vs Depletion Curves', index=False)

        # Sheet 2: W' Depletion Curves (kept for reference)
        w_prime_curves_df.to_excel(writer, sheet_name='W Prime Depletion Curves', index=False)

        # Sheet 3: Individual Zone Data
        all_zone_rows = []
        for file_data in all_files_data:
            for zone_name, row in file_data['zone_data'].iterrows():
                all_zone_rows.append({
                    'File Name': file_data['name'], 'Zone': zone_name,
                    'Time (s)': row['Time (s)'], 'Time (%)': row['Time (%)']
                })
        if all_zone_rows:
            pd.DataFrame(all_zone_rows).to_excel(writer, sheet_name='Individual Zone Data', index=False)

        # Sheet 4: Combined Zone Data
        if all_files_data:
            total_zone_seconds = sum(f['zone_data']['Time (s)'] for f in all_files_data)
            total_duration_all_files = sum(f['duration'] for f in all_files_data)
            if total_duration_all_files > 0:
                combined_zones = pd.DataFrame({'Time (s)': total_zone_seconds, 'Time (%)': (total_zone_seconds / total_duration_all_files * 100).round(2)})
                combined_zones.to_excel(writer, sheet_name='Combined Zones')

        # Sheet 5: Summary Stats
        summary_metrics = {
            'Metric': ['Total Bouts', 'Average Magnitude (% of CP)', 'Average Duration (s)', 'Total Critical Depletions (<15%)'],
            'Value': [
                len(all_bouts_df) if not all_bouts_df.empty else 0,
                all_bouts_df['magnitude'].mean() if not all_bouts_df.empty else 0,
                all_bouts_df['duration'].mean() if not all_bouts_df.empty else 0,
                sum(f['depletion_count'] for f in all_files_data) if all_files_data else 0
            ]
        }
        pd.DataFrame(summary_metrics).to_excel(writer, sheet_name='Summary Stats', index=False)
    return output.getvalue()

# -------------------
# Streamlit App UI & Main Logic
# -------------------
st.title("🚴 Multi-File Cycling Bout & W'bal Analysis Tool")

with st.sidebar:
    st.header("⚙️ User Inputs")
    uploaded_files = st.file_uploader("1. Upload FIT file(s)", type=["fit"], accept_multiple_files=True)
    st.markdown("---")
    st.subheader("2. Set Parameters")
    cp = st.number_input("Critical Power (CP) in Watts", 100, 600, 250, 1)
    w_prime_kj = st.number_input("W' (W prime) in kJ", 5.0, 50.0, 20.0, 0.5)
    w_prime = w_prime_kj * 1000
    st.markdown("---")
    st.subheader("W'bal Model Parameters (Tau)")
    tau_A = st.number_input("Parameter A", value=350.0, step=10.0, format="%.1f")
    tau_B = st.number_input("Parameter B (negative)", value=-0.3, step=0.01, format="%.2f")
    st.markdown("---")
    analyze_button = st.button("Analyze Files", type="primary", use_container_width=True)

# --- Initialize session state variables ---
if 'analysis_triggered' not in st.session_state:
    st.session_state.analysis_triggered = False
if 'time_ranges' not in st.session_state:
    st.session_state.time_ranges = {}
    
# Trigger analysis on button click and reset ranges for the new analysis
if analyze_button:
    st.session_state.analysis_triggered = True
    st.session_state.time_ranges = {}

if not uploaded_files:
    st.session_state.analysis_triggered = False # Reset if files are removed
    st.info("Upload one or more FIT files and click 'Analyze Files' to begin.")
else:
    # Run analysis if triggered
    if st.session_state.analysis_triggered:
        with st.spinner('Analyzing files... This may take a moment.'):
            all_files_data = []
            st.header("Individual File Analysis")

            for file in uploaded_files:
                with st.expander(f"▶️ Analysis for: **{file.name}**", expanded=True):
                    # Use a cached function to avoid reprocessing files unnecessarily
                    data_df = parse_fit_file(file)
                    if not isinstance(data_df, pd.DataFrame) or data_df.empty:
                        st.error(f"Could not process {file.name} or no power data found.")
                        continue
                    
                    # --- Step 1: Perform initial calculations on the FULL dataset ---
                    bouts_df = analyze_bouts(data_df['time'], data_df['power'], cp)
                    w_bal_series_full = calculate_w_prime_balance(data_df['power'], cp, w_prime, tau_A, tau_B)

                    # --- Step 2: Display full data plots and the new time range slider ---
                    st.subheader("W' Balance (W'bal) Analysis")
                    st.pyplot(plot_w_prime_balance(data_df['time'], w_bal_series_full, w_prime))
                    
                    min_time, max_time = float(data_df['time'].min()), float(data_df['time'].max())
                    
                    # Set default range to the full time span if not already set for this file
                    if file.name not in st.session_state.time_ranges:
                        st.session_state.time_ranges[file.name] = (min_time, max_time)

                    selected_range = st.slider(
                        "Select time range (seconds) for Zone Analysis:",
                        min_value=min_time,
                        max_value=max_time,
                        value=st.session_state.time_ranges[file.name],
                        key=f"slider_{file.name}"
                    )
                    # Update the session state with the new slider value
                    st.session_state.time_ranges[file.name] = selected_range
                    start_time, end_time = selected_range

                    # --- Step 3: Filter data based on the selected range for Zone Analysis ---
                    time_mask = (data_df['time'] >= start_time) & (data_df['time'] <= end_time)
                    w_bal_series_filtered = w_bal_series_full[time_mask]
                    time_series_filtered = data_df['time'][time_mask]

                    depletion_count, zone_data, _ = calculate_depletions_and_zones(
                        w_bal_series_filtered, w_prime, time_series_filtered
                    )

                    # --- Step 4: Display the filtered results and append to all_files_data ---
                    col_wbal_1, col_wbal_2 = st.columns([1, 1])
                    with col_wbal_1:
                        st.metric(f"Critical Depletions in Selection (<15% W'bal) 🔥", depletion_count)
                        st.dataframe(zone_data)
                    with col_wbal_2:
                         st.bar_chart(zone_data['Time (%)'])

                    # Store data for combined analysis. Note: duration is now the length of the selection
                    all_files_data.append({
                        'name': file.name,
                        'bouts_df': bouts_df, # Bouts are from the full file
                        'duration': len(time_series_filtered), # Duration of the selected range
                        'depletion_count': depletion_count, # Depletions from the selected range
                        'zone_data': zone_data # Zone data from the selected range
                    })
                    
                    st.markdown("---")
                    st.subheader("High-Intensity Bout Analysis (Full File)")
                    if not bouts_df.empty:
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Total Bouts", f"{len(bouts_df)}")
                        col2.metric("Avg. Magnitude", f"{bouts_df['magnitude'].mean():.1f}% CP")
                        col3.metric("Avg. Duration", f"{bouts_df['duration'].mean():.1f} s")
                        
                        create_summary_plots(bouts_df, cp, w_prime, title_prefix="")
                    else:
                        st.write("No high-intensity bouts detected.")

            if all_files_data:
                st.markdown("---")
                st.header("📊 Combined Analysis for All Files (Based on Selections)")
                st.subheader("Combined Summary Metrics")
                combined_bouts_df = pd.concat([f['bouts_df'] for f in all_files_data if not f['bouts_df'].empty], ignore_index=True)
                total_depletions = sum(f['depletion_count'] for f in all_files_data)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Bouts (All Files)", f"{len(combined_bouts_df)}" if not combined_bouts_df.empty else "0")
                c2.metric("Overall Avg. Magnitude", f"{combined_bouts_df['magnitude'].mean():.1f}% CP" if not combined_bouts_df.empty else "N/A")
                c3.metric("Overall Avg. Duration", f"{combined_bouts_df['duration'].mean():.1f} s" if not combined_bouts_df.empty else "N/A")
                c4.metric("Total Critical Depletions 🔥", total_depletions)

                if not combined_bouts_df.empty:
                    create_summary_plots(combined_bouts_df, cp, w_prime, title_prefix="Combined ")

                st.subheader("Combined W'bal Time in Zones")
                total_duration_all = sum(f['duration'] for f in all_files_data)
                if total_duration_all > 0:
                    total_zone_seconds = sum(f['zone_data']['Time (s)'] for f in all_files_data)
                    combined_zones_df = pd.DataFrame({'Total Time (s)': total_zone_seconds, 'Total Time (%)': (total_zone_seconds / total_duration_all * 100).round(2)})
                    st.dataframe(combined_zones_df)
                    st.bar_chart(combined_zones_df['Total Time (%)'])

                st.markdown("---")
                st.header("⬇️ Download All Data")
                excel_data = generate_excel_output(all_files_data, cp, w_prime)
                st.download_button(label="📥 Download Full Analysis as Excel File", data=excel_data, file_name=f'full_analysis_{cp}W_CP.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        st.info(f"✅ **{len(uploaded_files)} file(s) loaded.** Adjust parameters and click 'Analyze Files' to process.")


