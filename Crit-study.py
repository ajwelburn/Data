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
    uploaded_file.seek(0)
    try:
        fitfile = fitparse.FitFile(uploaded_file)
        records = [data for record in fitfile.get_messages('record') if (data := record.get_values()) and 'power' in data and data['power'] is not None]
    except Exception as e:
        return f"Error parsing {uploaded_file.name}: {e}"
    if not records: return None
    df = pd.DataFrame(records)
    df = df.set_index('timestamp').resample('1S').ffill().reset_index()
    df['time'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds()
    return df[['time', 'power']]

def analyze_bouts(time_values, power_values, cp):
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
        bouts_df['color'] = bouts_df['magnitude'].apply(lambda mag: 'red' if mag >= 170 else ('orange' if mag >= 140 else 'blue'))
    return bouts_df

def calculate_w_prime_balance(power_series, cp, w_prime, A, B):
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

def calculate_depletions_and_zones(w_bal_series, w_prime, time_series):
    total_duration = time_series.max() if not time_series.empty else 0
    depletion_threshold = 0.15 * w_prime
    depletion_count = 0
    depletion_times = []
    below_threshold = False
    for i, val in enumerate(w_bal_series):
        if val < depletion_threshold and not below_threshold:
            depletion_count += 1
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
    zone_data = pd.DataFrame({'Time (s)': zone_counts,'Time (%)': (zone_counts / total_duration * 100).round(2) if total_duration > 0 else 0})
    return depletion_count, zone_data, depletion_times

# -------------------
# Plotting & Export Functions
# -------------------
def create_summary_plots(bouts_df, cp, w_prime, title_prefix=""):
    if bouts_df.empty:
        st.warning(f"No bouts detected for {title_prefix} analysis.")
        return
    bout_durations = bouts_df['duration']; magnitudes = bouts_df['magnitude']
    st.subheader(f"{title_prefix}Magnitude vs. Bout Duration")
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.scatter(bout_durations, magnitudes, c=bouts_df['color'], alpha=0.7, label='Individual Bouts')
    avg_duration = bout_durations.mean(); avg_magnitude = magnitudes.mean()
    ax1.scatter(avg_duration, avg_magnitude, color='black', marker='X', s=200, edgecolor='white', linewidth=1.5, label=f'Overall Average ({avg_duration:.1f}s, {avg_magnitude:.1f}%)', zorder=5)
    for depletion in range(10, 60, 10):
        y_values = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in range(1, 71)]
        ax1.plot(range(1, 71), y_values, 'k:', linewidth=0.7, label=f"{depletion}% W'")
    ax1.set_xlabel('Bout Duration (s)'); ax1.set_ylabel('Magnitude (% of CP)'); ax1.set_title(f'{title_prefix}Magnitude vs Bout Duration (>105% CP)')
    ax1.set_ylim(105, max(250, magnitudes.max() * 1.1 if not magnitudes.empty else 250))
    ax1.set_xlim(0, 70); ax1.grid(alpha=0.4); ax1.legend(); st.pyplot(fig1)

def plot_w_prime_balance(time_series, w_bal_series, w_prime):
    w_bal_percent = (w_bal_series / w_prime) * 100
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time_series, w_bal_percent, color='green', linewidth=1.5); ax.fill_between(time_series, 0, w_bal_percent, color='green', alpha=0.2)
    ax.set_xlabel("Time (s)"); ax.set_ylabel("W' Balance (%)"); ax.set_title("W' Balance Over Time")
    ax.set_ylim(0, 105); ax.set_xlim(0, time_series.max() if not time_series.empty else 1); ax.grid(alpha=0.3); return fig

def plot_depletions(depletion_times, total_duration):
    fig, ax = plt.subplots(figsize=(10, 1.5))
    if depletion_times:
        ax.vlines(depletion_times, ymin=0, ymax=1, color='red', linestyle='--', linewidth=1.5)
    ax.set_xlim(0, total_duration if total_duration > 0 else 1); ax.set_ylim(0,1); ax.yaxis.set_visible(False)
    ax.set_xlabel("Time (s)"); ax.set_title("Critical Depletion Events (<15% W'bal)"); return fig

def generate_excel_output(all_files_data, cp, w_prime):
    output = io.BytesIO()
    with ExcelWriter(output, engine='openpyxl') as writer:
        all_bouts_df = pd.concat([f['bouts_df'] for f in all_files_data if not f['bouts_df'].empty], ignore_index=True)
        if not all_bouts_df.empty:
            all_bouts_df.to_excel(writer, sheet_name='All Bouts Data', index=False)
        
        w_prime_curves = {'Time (s)': range(1, 71)}
        for depletion in range(10, 60, 10):
            w_prime_curves[f"{depletion}% W' Depletion (%CP)"] = [((w_prime * (depletion / 100) / t) + cp) / cp * 100 for t in w_prime_curves['Time (s)']]
        pd.DataFrame(w_prime_curves).to_excel(writer, sheet_name='W Prime Depletion Curves', index=False)
        
        individual_zones_list = []
        for file_data in all_files_data:
            if not file_data['zone_data'].empty:
                zone_df = file_data['zone_data'].copy()
                zone_df['File Name'] = file_data['name']
                zone_df = zone_df.reset_index().rename(columns={'index': 'Zone'})
                individual_zones_list.append(zone_df)
        if individual_zones_list:
            consolidated_zones_df = pd.concat(individual_zones_list, ignore_index=True)
            consolidated_zones_df = consolidated_zones_df[['File Name', 'Zone', 'Time (s)', 'Time (%)']]
            consolidated_zones_df.to_excel(writer, sheet_name='Individual Zone Data', index=False)

        if all_files_data:
            total_zone_seconds = sum(f['zone_data']['Time (s)'] for f in all_files_data)
            total_duration_all_files = sum(f['duration'] for f in all_files_data)
            if total_duration_all_files > 0:
                combined_zones = pd.DataFrame({'Time (s)': total_zone_seconds, 'Time (%)': (total_zone_seconds / total_duration_all_files * 100).round(2)})
                combined_zones.to_excel(writer, sheet_name='Combined Zones')
        
        summary_metrics = {'Metric': ['Total Bouts', 'Average Magnitude (% of CP)', 'Average Duration (s)', 'Total Critical Depletions (<15%)'],
                           'Value': [len(all_bouts_df) if not all_bouts_df.empty else 0,
                                     all_bouts_df['magnitude'].mean() if not all_bouts_df.empty else 0,
                                     all_bouts_df['duration'].mean() if not all_bouts_df.empty else 0,
                                     sum(f['depletion_count'] for f in all_files_data) if all_files_data else 0]}
        pd.DataFrame(summary_metrics).to_excel(writer, sheet_name='Summary Stats', index=False)
    return output.getvalue()

# -------------------
# Streamlit App UI & Main Logic
# -------------------
st.title("🚴 Multi
