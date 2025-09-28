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
        y_values = [((
