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
    """Parses a FIT file and returns a DataFrame with time and power."""
    uploaded_file.seek(0)
    try:
        fitfile = fitparse.FitFile(uploaded_file)
        records = [
            data for record in fitfile.get_messages('record')
            if (data := record.get_values()) and 'power' in data and data['power'] is not None
        ]
    except Exception as e:
        return f"Error parsing {uploaded_file.name}: {e}"

    if not records: return None
    df = pd.DataFrame(records)
    df = df.set_index('timestamp').resample('1S').ffill().reset_index()
    df['time'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df[['time', 'power']]

def analyze_bouts(time_values, power_values, cp):
    """Analyzes power data for high-intensity bouts."""
    threshold_factor = 1.05; threshold_power = cp * threshold_factor
    min_bout_duration = 3; gap_tolerance = 3
    bouts = []; duration, avg_power, below_counter, start_time = 0, 0, 0, None
    for t, p in zip(time_values, power_values):
        if p > threshold_power:
            if duration == 0: start_time = t
            duration += 1; avg_power += p; below_counter = 0
        else:
            if duration > 0:
                below_counter += 1
                if below_counter <= gap_tolerance:
                    duration += 1; avg_power += p
                else:
                    if duration >= min_bout_duration:
                        magnitude = avg_power / duration / cp * 100
                        if magnitude >= threshold_factor * 100:
                            bouts.append({'start_time': start_time, 'duration': duration, 'magnitude': magnitude})
                    duration, avg_power, below_counter, start_time = 0, 0, 0, None
    if duration >= min_bout_duration:
        magnitude = avg_power / duration / cp * 100
        if magnitude >= threshold_factor * 100:
            bouts.append({'start_time': start_time, 'duration': duration, 'magnitude': magnitude})
    bouts_df = pd.DataFrame(bouts)
    if not bouts_df.empty:
        bouts_df['color'] = bouts_df['magnitude'].apply(
            lambda mag: 'red' if mag >= 170 else ('orange' if mag >= 140 else 'blue'))
    return bouts_df

def calculate_w_prime_balance(power_series, cp, w_prime, A, B):
    """Calculates the W' Balance for a given power series."""
    w_balance = w_prime; w_bal_list = []
    for p in power_series:
        if p > cp:
            w_balance -= (p - cp)
        else:
            w_expended = w_prime - w_balance
            delta_p = cp - p
            if delta_p > 0:
                tau = A * (delta_p ** B)
                if tau > 0:
                    w_balance += w_expended * (1 - math.exp(-1 / tau))
        w_balance = min(w_prime, max(0, w_balance))
        w_bal_list.append(w_balance)
    return pd.Series(w_bal_list)

def calculate_matches_and_zones(w_bal_series, w_prime, time_series):
    """Calculates match count, match times, and time in W'bal zones."""
    total_duration = time_series.max()
    match_threshold = 0.15 * w_prime
    match_count = 0
    match_times = []
    below_threshold = False
    for i, val in enumerate(w_bal_series):
        if val < match_threshold and not below_threshold:
            match_count += 1
            match_times.append(time_series[i])
            below_threshold = True
        elif val >= match_threshold:
            below_threshold = False

    w_bal_percent = (w_bal_series / w_prime) * 100
    bins = [-1, 10, 15, 25, 50, 70, 101]
    labels = ['0-10%', '10-15%', '15-25%', '25-50%', '50-70%', '70-100%']
    zone_counts = pd.cut(w_bal_percent, bins=bins, labels=labels, right=False).value_counts().sort_index()
    
    zone_data = pd.DataFrame({
        'Time (s)': zone_counts,
        'Time (%)': (zone_counts / total_duration * 100).round(2)
    })
    return match_count, zone_data, match_times

# -------------------
# Plotting & Export Functions
# -------------------
def create_summary_plots(bouts_df, cp, w_prime, title_prefix=""):
    """Generates and displays summary plots for bouts."""
    if bouts_df.empty:
        st.warning(f"No bouts detected for {title_prefix} analysis.")
        return
    bout_durations = bouts_df['duration']; magnitudes = bouts_df['magnitude']
    st.subheader(f"{title_prefix}Magnitude vs. Bout Duration")
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.scatter(bout_durations, magnitudes, c=bouts_df['color'], alpha=0.7, label='Individual Bouts')
    avg_duration = bout_durations.mean(); avg_magnitude = magnitudes.mean()
    ax1.scatter(avg_duration, avg_magnitude, color='black', marker='X', s=200, edgecolor='white',
                linewidth=1.5, label=f'Overall Average ({avg_duration:.1f}s, {avg_magnitude:.1f}%)', zorder=5)
    for depletion in range(10, 60, 10):
        y_values = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in range(1, 71)]
        ax1.plot(range(1, 71), y_values, 'k:', linewidth=0.7, label=f"{depletion}% W'")
    ax1.set_xlabel('Bout Duration (s)'); ax1.set_ylabel('Magnitude (% of CP)')
    ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>105% CP)')
    ax1.set_ylim(105, max(250, magnitudes.max() * 1.1 if not magnitudes.empty else 250))
    ax1.set_xlim(0, 70); ax1.grid(alpha=0.4); ax1.legend()
    st.pyplot(fig1)

def plot_w_prime_balance(time_series, w_bal_series, w_prime):
    """Plots the W' Balance as a percentage over time."""
    w_bal_percent = (w_bal_series / w_prime) * 100
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time_series, w_bal_percent, color='green', linewidth=1.5)
    ax.fill_between(time_series, 0, w_bal_percent, color='green', alpha=0.2)
    ax.set_xlabel("Time (s)"); ax.set_ylabel("W' Balance (%)")
    ax.set_title("W' Balance Over Time")
    ax.set_ylim(0, 105); ax.set_xlim(0, time_series.max())
    ax.grid(alpha=0.3)
    return fig

def plot_matches_burned(match_times, total_duration):
    """Plots a timeline of when matches were burned."""
    fig, ax = plt.subplots(figsize=(10, 1.5))
    if match_times:
        ax.vlines(match_times, ymin=0, ymax=1, color='red', linestyle='--', linewidth=1.5, label='Match Burned')
    ax.set_xlim(0, total_duration)
    ax.set_ylim(0,1)
    ax.yaxis.set_visible(False)
    ax.set_xlabel("Time (s)")
    ax.set_title("Match Burn Events")
    return fig

def generate_excel_output(bouts_df, cp, w_prime, all_files_data):
    """Creates a comprehensive Excel file with all analysis data."""
    output = io.BytesIO()
    with ExcelWriter(output, engine='openpyxl') as writer:
        # --- Bouts & Summary ---
        bouts_df.to_excel(writer, sheet_name='All Bouts Data', index=False)
        w_prime_curves = {'Time (s)': range(1, 71)}
        for depletion in range(10, 60, 10):
            w_prime_curves[f"{depletion}% W' Depletion (%CP)"] = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in w_prime_curves['Time (s)']]
        pd.DataFrame(w_prime_curves).to_excel(writer, sheet_name='W Prime Depletion Curves', index=False)
        
        # --- Consolidated Individual Zones ---
        individual_zones_list = []
        for file_data in all_files_data:
            zone_df = file_data['zone_data'].copy()
            zone_df['File Name'] = file_data['name']
            individual_zones_list.append(zone_df)
        
        if individual_zones_list:
            consolidated_zones_df = pd.concat(individual_zones_list)
            consolidated_zones_df = consolidated_zones_df.reset_index().rename(columns={'index': 'Zone'})
            consolidated_zones_df = consolidated_zones_df[['File Name', 'Zone', 'Time (s)', 'Time (%)']]
            consolidated_zones_df.to_excel(writer, sheet_name='Individual Zone Data', index=False)

        # --- Combined Zones ---
        total_zone_seconds = sum(f['zone_data']['Time (s)'] for f in all_files_data)
        total_duration_all_files = sum(f['duration'] for f in all_files_data)
        if total_duration_all_files > 0:
            combined_zones = pd.DataFrame({
                'Time (s)': total_zone_seconds,
                'Time (%)': (total_zone_seconds / total_duration_all_files * 100).round(2)
            })
            combined_zones.to_excel(writer, sheet_name='Combined Zones')

        # --- Summary Sheet ---
        if not bouts_df.empty:
            summary_data = {
                'Metric': ['Total Efforts', 'Average Magnitude (% of CP)', 'Average Duration (s)', 'Total Matches Burned (<15%)'],
                'Value': [len(bouts_df), bouts_df['magnitude'].mean(), bouts_df['duration'].mean(), sum(f['match_count'] for f in all_files_data)]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary Stats', index=False)
            
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

if not uploaded_files:
    st.info("Upload one or more FIT files and click 'Analyze Files' to begin.")
else:
    if analyze_button:
        with st.spinner('Analyzing files... This may take a moment.'):
            all_files_data = []
            
            st.header("Individual File Analysis")
            for file in uploaded_files:
                with st.expander(f"▶️ Analysis for: **{file.name}**", expanded=True):
                    data_df = parse_fit_file(io.BytesIO(file.getvalue()))
                    if not isinstance(data_df, pd.DataFrame) or data_df.empty:
                        st.error(f"Could not process {file.name} or no power data found.")
                        continue

                    bouts_df = analyze_bouts(data_df['time'], data_df['power'], cp)
                    w_bal_series = calculate_w_prime_balance(data_df['power'], cp, w_prime, tau_A, tau_B)
                    match_count, zone_data, match_times = calculate_matches_and_zones(w_bal_series, w_prime, data_df['time'])

                    all_files_data.append({
                        'name': file.name, 'bouts_df': bouts_df, 'duration': data_df['time'].max(),
                        'match_count': match_count, 'zone_data': zone_data, 'match_times': match_times
                    })

                    st.subheader("Bout Analysis Results")
                    if not bouts_df.empty:
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Total Bouts", f"{len(bouts_df)}")
                        col2.metric("Avg. Magnitude", f"{bouts_df['magnitude'].mean():.1f}% CP")
                        col3.metric("Avg. Duration", f"{bouts_df['duration'].mean():.1f} s")
                    else:
                        st.write("No high-intensity bouts detected.")
                    
                    st.markdown("---")
                    st.subheader("W' Balance (W'bal) Analysis")
                    col_wbal_1, col_wbal_2 = st.columns([2, 1])
                    with col_wbal_1:
                        fig_wbal = plot_w_prime_balance(data_df['time'], w_bal_series, w_prime)
                        st.pyplot(fig_wbal)
                        fig_matches = plot_matches_burned(match_times, data_df['time'].max())
                        st.pyplot(fig_matches)
                    with col_wbal_2:
                        st.metric("Matches Burned (<15% W'bal) 🔥", match_count)
                        st.dataframe(zone_data)
                        st.bar_chart(zone_data['Time (%)'])

            if all_files_data:
                st.markdown("---")
                st.header("📊 Combined Analysis for All Files")
                
                combined_bouts_df = pd.concat([f['bouts_df'] for f in all_files_data], ignore_index=True)
                if not combined_bouts_df.empty:
                    st.subheader("Combined Bout Metrics")
                    total_matches = sum(f['match_count'] for f in all_files_data)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Bouts", f"{len(combined_bouts_df)}")
                    c2.metric("Overall Avg. Magnitude", f"{combined_bouts_df['magnitude'].mean():.1f}% CP")
                    c3.metric("Overall Avg. Duration", f"{combined_bouts_df['duration'].mean():.1f} s")
                    c4.metric("Total Matches Burned 🔥", total_matches)
                    create_summary_plots(combined_bouts_df, cp, w_prime, title_prefix="Combined ")

                st.subheader("Combined W'bal Time in Zones")
                total_zone_seconds = sum(f['zone_data']['Time (s)'] for f in all_files_data)
                total_duration_all = sum(f['duration'] for f in all_files_data)
                if total_duration_all > 0:
                    combined_zones_df = pd.DataFrame({
                        'Total Time (s)': total_zone_seconds,
                        'Total Time (%)': (total_zone_seconds / total_duration_all * 100).round(2)
                    })
                    st.dataframe(combined_zones_df)
                    st.bar_chart(combined_zones_df['Total Time (%)'])

                st.markdown("---")
                st.header("⬇️ Download All Data")
                excel_data = generate_excel_output(combined_bouts_df, cp, w_prime, all_files_data)
                st.download_button(
                    label="📥 Download Full Analysis as Excel File",
                    data=excel_data,
                    file_name=f'full_analysis_{cp}W_CP.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
    else:
        st.info(f"✅ **{len(uploaded_files)} file(s) loaded.** Adjust parameters and click 'Analyze Files' to process.")
