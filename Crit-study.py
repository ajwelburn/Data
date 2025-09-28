import streamlit as st
import fitparse
import pandas as pd
import matplotlib.pyplot as plt
import io
import math
from pandas import ExcelWriter

# Set page configuration to wide mode for better layout
st.set_page_config(layout="wide")

# -------------------
# Data Processing & Analysis Functions
# (These functions remain unchanged)
# -------------------
@st.cache_data # Add caching to speed up re-runs with the same file
def parse_fit_file(uploaded_file):
    """Parses an uploaded FIT file and returns a pandas DataFrame with time and power."""
    uploaded_file.seek(0)
    try:
        fitfile = fitparse.FitFile(uploaded_file)
        records = [
            data for record in fitfile.get_messages('record')
            if (data := record.get_values()) and 'power' in data and data['power'] is not None
        ]
    except Exception as e:
        # Cannot use st.error inside a cached function, so we return the error
        return f"Error parsing {uploaded_file.name}: {e}"

    if not records: return None
    df = pd.DataFrame(records)
    df = df.set_index('timestamp').resample('1S').ffill().reset_index()
    df['time'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df[['time', 'power']]

def analyze_bouts(time_values, power_values, cp):
    """Analyzes power data to find high-intensity bouts and returns a DataFrame."""
    threshold_factor = 1.05
    threshold_power = cp * threshold_factor
    min_bout_duration = 3; gap_tolerance = 3
    bouts = []
    duration, avg_power, below_counter, start_time = 0, 0, 0, None

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
    w_balance = w_prime
    w_bal_list = []
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

# -------------------
# Plotting & Export Functions
# (These functions remain unchanged)
# -------------------
def create_summary_plots(bouts_df, cp, w_prime, title_prefix=""):
    """Generates and displays the matplotlib summary plots for bouts."""
    if bouts_df.empty:
        st.warning(f"No bouts detected for {title_prefix} analysis.")
        return
    bout_durations = bouts_df['duration']; magnitudes = bouts_df['magnitude']
    colors = bouts_df['color']; bout_times = bouts_df['start_time']
    st.subheader(f"{title_prefix}Magnitude vs. Bout Duration")
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.scatter(bout_durations, magnitudes, c=colors, alpha=0.7, label='Individual Bouts')
    avg_duration = bout_durations.mean(); avg_magnitude = magnitudes.mean()
    ax1.scatter(avg_duration, avg_magnitude, color='black', marker='X', s=200, edgecolor='white',
                linewidth=1.5, label=f'Overall Average ({avg_duration:.1f}s, {avg_magnitude:.1f}%)', zorder=5)
    for depletion in range(10, 60, 10):
        y_values = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in range(1, 71)]
        ax1.plot(range(1, 71), y_values, 'k:', linewidth=0.7, label=f'{depletion}% W\'')
    ax1.set_xlabel('Bout Duration (s)'); ax1.set_ylabel('Magnitude (% of CP)')
    ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>105% CP)')
    ax1.set_ylim(105, max(250, magnitudes.max() * 1.1 if not magnitudes.empty else 250))
    ax1.set_xlim(0, 70); ax1.grid(alpha=0.4); ax1.legend()
    st.pyplot(fig1)

def plot_w_prime_balance(time_series, w_bal_series, w_prime, file_name):
    """Plots the W' Balance as a percentage over time."""
    st.subheader(f"⚡ W' Balance (W'bal) Model for {file_name}")
    w_bal_percent = (w_bal_series / w_prime) * 100
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(time_series, w_bal_percent, color='green', label="W' Balance")
    ax.fill_between(time_series, w_bal_percent, 100, color='red', alpha=0.1, label="W' Expended")
    ax.fill_between(time_series, 0, w_bal_percent, color='green', alpha=0.2)
    ax.set_xlabel("Time (s)"); ax.set_ylabel("W' Balance (%)")
    ax.set_title(f"W' Balance Over Time for {file_name}")
    ax.set_ylim(0, 105); ax.set_xlim(0, time_series.max())
    ax.axhline(0, color='r', linestyle='--', linewidth=1)
    ax.axhline(100, color='g', linestyle='--', linewidth=1)
    ax.grid(alpha=0.4); st.pyplot(fig)

def generate_excel_output(bouts_df, cp, w_prime):
    """Creates an Excel file in memory."""
    output = io.BytesIO()
    with ExcelWriter(output, engine='openpyxl') as writer:
        bouts_df.to_excel(writer, sheet_name='All Bouts Data', index=False)
        w_prime_curves = {'Time (s)': range(1, 71)}
        for depletion in range(10, 60, 10):
            col_name = f"{depletion}% W' Depletion (%CP)"
            w_prime_curves[col_name] = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in w_prime_curves['Time (s)']]
        pd.DataFrame(w_prime_curves).to_excel(writer, sheet_name='W Prime Depletion Curves', index=False)
        if not bouts_df.empty:
            summary_data = {'Metric': ['Total Efforts', 'Average Magnitude (% of CP)', 'Average Duration (s)'],
                            'Value': [len(bouts_df), bouts_df['magnitude'].mean(), bouts_df['duration'].mean()]}
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary Stats', index=False)
    return output.getvalue()

# -------------------
# Streamlit App UI & Main Logic
# -------------------
st.title("🚴 Multi-File Cycling Bout & W'bal Analysis Tool")

with st.sidebar:
    st.header("⚙️ User Inputs")
    uploaded_files = st.file_uploader("1. Upload your FIT file(s)", type=["fit"], accept_multiple_files=True)
    st.markdown("---")
    st.subheader("2. Set Parameters")
    cp = st.number_input("Critical Power (CP) in Watts", 100, 600, 250, 1)
    w_prime_kj = st.number_input("W' (W prime) in kJ", 5.0, 50.0, 20.0, 0.5)
    w_prime = w_prime_kj * 1000
    st.markdown("---")
    st.subheader("W'bal Model Parameters (Tau)")
    st.info("These values control the rate of W' recovery.")
    tau_A = st.number_input("Parameter A", value=350.0, step=10.0, format="%.1f")
    tau_B = st.number_input("Parameter B (must be negative)", value=-0.3, step=0.01, format="%.2f")
    st.markdown("---")
    # NEW: The Analyze button that triggers the main logic
    analyze_button = st.button("Analyze Files", type="primary", use_container_width=True)

# Main panel logic
if not uploaded_files:
    st.info("Upload one or more FIT files using the sidebar to begin.")
else:
    # This block now only runs when the button is clicked
    if analyze_button:
        with st.spinner('Analyzing files... This may take a moment.'):
            all_bouts_list = []
            st.header("Individual File Analysis")
            for file in uploaded_files:
                with st.expander(f"▶️ Analysis for: **{file.name}**", expanded=True):
                    # Use a copy of the file object for caching
                    file_copy = io.BytesIO(file.getvalue())
                    data_df = parse_fit_file(file_copy)
                    
                    if isinstance(data_df, str): # Check if parsing returned an error message
                        st.error(data_df)
                        continue
                    if data_df is None or data_df.empty:
                        st.write("Could not process this file or no power data found.")
                        continue

                    # --- Bout Analysis ---
                    st.subheader("Bout Analysis Results")
                    bouts_df = analyze_bouts(data_df['time'], data_df['power'], cp)
                    if not bouts_df.empty:
                        avg_mag = bouts_df['magnitude'].mean(); avg_dur = bouts_df['duration'].mean()
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Total Efforts", f"{len(bouts_df)}")
                        col2.metric("Avg. Magnitude", f"{avg_mag:.1f}% of CP")
                        col3.metric("Avg. Duration", f"{avg_dur:.1f} s")
                        bouts_df['source_file'] = file.name
                        all_bouts_list.append(bouts_df)
                    else:
                        st.write("No high-intensity bouts detected in this file.")
                    
                    # --- W'bal Model ---
                    st.markdown("---")
                    w_bal_series = calculate_w_prime_balance(data_df['power'], cp, w_prime, tau_A, tau_B)
                    plot_w_prime_balance(data_df['time'], w_bal_series, w_prime, file.name)
            
            # --- Combined Analysis Section ---
            if all_bouts_list:
                st.markdown("---")
                st.header("📊 Combined Bout Analysis for All Files")
                combined_bouts_df = pd.concat(all_bouts_list, ignore_index=True)
                avg_mag_comb = combined_bouts_df['magnitude'].mean()
                avg_dur_comb = combined_bouts_df['duration'].mean()
                col1_c, col2_c, col3_c = st.columns(3)
                col1_c.metric("Total Efforts (All Files)", f"{len(combined_bouts_df)}")
                col2_c.metric("Overall Avg. Magnitude", f"{avg_mag_comb:.1f}% of CP")
                col2_c.metric("Overall Avg. Duration", f"{avg_dur_comb:.1f} s")
                create_summary_plots(combined_bouts_df, cp, w_prime, title_prefix="Combined ")
                
                # --- Excel Download Button ---
                st.markdown("---")
                st.header("⬇️ Download Bout Data")
                excel_data = generate_excel_output(combined_bouts_df, cp, w_prime)
                st.download_button(label="📥 Download Bout Analysis as Excel File", data=excel_data,
                                  file_name=f'combined_bout_analysis_{cp}W_CP.xlsx',
                                  mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        # This message shows after files are uploaded but before the button is clicked
        st.info(f"✅ **{len(uploaded_files)} file(s) loaded.** Adjust parameters in the sidebar and click 'Analyze Files' to process.")
