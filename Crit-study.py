import streamlit as st
import fitparse
import pandas as pd
import matplotlib.pyplot as plt
import io
from pandas import ExcelWriter

# Set page configuration to wide mode for better layout
st.set_page_config(layout="wide")

# -------------------
# Data Processing Functions (from previous script, no changes needed)
# -------------------
def parse_fit_file(uploaded_file):
    uploaded_file.seek(0)
    try:
        fitfile = fitparse.FitFile(uploaded_file)
        records = [
            data for record in fitfile.get_messages('record')
            if (data := record.get_values()) and 'power' in data and data['power'] is not None
        ]
    except Exception as e:
        st.error(f"Error parsing {uploaded_file.name}: {e}")
        return None

    if not records: return None
    df = pd.DataFrame(records)
    df['time'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df[['time', 'power']]

def analyze_bouts(time_values, power_values, cp):
    threshold_factor = 1.05
    threshold_power = cp * threshold_factor
    min_bout_duration = 3
    gap_tolerance = 3
    
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
            lambda mag: 'red' if mag >= 170 else ('orange' if mag >= 140 else 'blue')
        )
    return bouts_df

# -------------------
# Plotting Function
# -------------------
def create_summary_plots(bouts_df, cp, w_prime, title_prefix=""):
    """Generates and displays the matplotlib summary plots."""
    if bouts_df.empty:
        st.warning(f"No bouts detected for {title_prefix} analysis.")
        return

    bout_durations = bouts_df['duration']
    magnitudes = bouts_df['magnitude']
    colors = bouts_df['color']
    bout_times = bouts_df['start_time']
    
    # --- Graph 1: Magnitude vs Bout Duration ---
    st.subheader(f"{title_prefix}Magnitude vs. Bout Duration")
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.scatter(bout_durations, magnitudes, c=colors, alpha=0.7)
    
    for depletion in range(10, 60, 10):
        y_values = [( (w_prime * (depletion / 100) / t) + cp ) / cp * 100 for t in range(1, 71)]
        ax1.plot(range(1, 71), y_values, 'k:', linewidth=0.7, label=f'{depletion}% W\'')

    ax1.set_xlabel('Bout Duration (s)'); ax1.set_ylabel('Magnitude (% of CP)')
    ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>105% CP)')
    ax1.set_ylim(105, max(250, magnitudes.max() * 1.1 if not magnitudes.empty else 250))
    ax1.set_xlim(0, 70); ax1.grid(alpha=0.4); ax1.legend()
    st.pyplot(fig1)

    # --- Graph 2 & 3: Time vs Magnitude/Duration ---
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"{title_prefix}Magnitude Over Time")
        fig2, ax2 = plt.subplots(); ax2.scatter(bout_times, magnitudes, c=colors, alpha=0.6)
        ax2.set_xlabel('Time (s)'); ax2.set_ylabel('Magnitude (% of CP)'); ax2.grid(alpha=0.4)
        st.pyplot(fig2)
    with col2:
        st.subheader(f"{title_prefix}Duration Over Time")
        fig3, ax3 = plt.subplots(); ax3.scatter(bout_times, bout_durations, c='purple', alpha=0.6)
        ax3.set_xlabel('Time (s)'); ax3.set_ylabel('Bout Duration (s)'); ax3.grid(alpha=0.4)
        st.pyplot(fig3)

# -------------------
# Excel Export Function
# -------------------
def generate_excel_output(bouts_df, cp, w_prime):
    """Creates an Excel file in memory with bout data and W' curves."""
    # 1. Create DataFrame for W' depletion curves
    w_prime_curves = {'Time (s)': range(1, 71)}
    for depletion in range(10, 60, 10):
        col_name = f"{depletion}% W' Depletion (%CP)"
        w_prime_curves[col_name] = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in w_prime_curves['Time (s)']]
    w_prime_df = pd.DataFrame(w_prime_curves)

    # 2. Write DataFrames to an in-memory Excel file
    output = io.BytesIO()
    with ExcelWriter(output, engine='openpyxl') as writer:
        bouts_df.to_excel(writer, sheet_name='All Bouts Data', index=False)
        w_prime_df.to_excel(writer, sheet_name='W Prime Depletion Curves', index=False)
    
    return output.getvalue()

# -------------------
# Streamlit App UI
# -------------------
st.title("🚴 Multi-File Cycling Bout Analysis Tool")
st.write("Upload one or more FIT files to analyze high-intensity efforts individually and combined.")

with st.sidebar:
    st.header("⚙️ User Inputs")
    # UPDATED: Accept multiple files
    uploaded_files = st.file_uploader("Upload your FIT file(s)", type=["fit"], accept_multiple_files=True)
    cp = st.number_input("Enter your Critical Power (CP) in Watts", 100, 600, 250, 1)
    w_prime_kj = st.number_input("Enter your W' (W prime) in kJ", 5.0, 50.0, 20.0, 0.5)
    w_prime = w_prime_kj * 1000

# --- Main App Logic ---
if uploaded_files:
    all_bouts = []
    
    st.header("Individual File Analysis")
    for file in uploaded_files:
        with st.expander(f"▶️ Analysis for: **{file.name}**"):
            data_df = parse_fit_file(file)
            if data_df is not None and not data_df.empty:
                bouts_df = analyze_bouts(data_df['time'], data_df['power'], cp)
                
                if not bouts_df.empty:
                    # Display metrics for this single file
                    avg_mag = bouts_df['magnitude'].mean()
                    avg_dur = bouts_df['duration'].mean()
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total Efforts", f"{len(bouts_df)}")
                    col2.metric("Avg. Magnitude", f"{avg_mag:.1f}% of CP")
                    col3.metric("Avg. Duration", f"{avg_dur:.1f} s")
                    
                    # Store results for combined analysis
                    bouts_df['source_file'] = file.name # Add filename for tracking
                    all_bouts.append(bouts_df)
                else:
                    st.write("No high-intensity bouts detected in this file.")
            else:
                st.write("Could not process this file or no power data found.")

    st.markdown("---")
    
    # --- Combined Analysis Section ---
    if all_bouts:
        st.header("📊 Combined Analysis for All Files")
        combined_bouts_df = pd.concat(all_bouts, ignore_index=True)

        # Display combined metrics
        avg_mag_comb = combined_bouts_df['magnitude'].mean()
        avg_dur_comb = combined_bouts_df['duration'].mean()
        col1_c, col2_c, col3_c = st.columns(3)
        col1_c.metric("Total Efforts (All Files)", f"{len(combined_bouts_df)}")
        col2_c.metric("Overall Avg. Magnitude", f"{avg_mag_comb:.1f}% of CP")
        col3_c.metric("Overall Avg. Duration", f"{avg_dur_comb:.1f} s")
        
        # Display combined plots
        create_summary_plots(combined_bouts_df, cp, w_prime, title_prefix="Combined ")

        # --- Excel Download Button ---
        st.markdown("---")
        st.header("⬇️ Download Data")
        excel_data = generate_excel_output(combined_bouts_df, cp, w_prime)
        st.download_button(
            label="📥 Download Analysis as Excel File",
            data=excel_data,
            file_name=f'combined_bout_analysis_{cp}W_CP.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    
else:
    st.info("Upload one or more FIT files using the sidebar to begin analysis.")
