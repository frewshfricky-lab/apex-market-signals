import os
import requests
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange
API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
SYMBOLS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "BTC/USD",
]
INTERVAL = "4h"
OUTPUTSIZE = 5000
DEVELOPMENT_RATIO = 0.70
ADX_MIN = 20
# ============================================================
# STRATEGY RULES — DO NOT CHANGE
# ============================================================
def prepare_data(df):
    df = df.copy()
    df["ema50"] = EMAIndicator(
        close=df["close"],
        window=50
    ).ema_indicator()
    df["ema200"] = EMAIndicator(
        close=df["close"],
        window=200
    ).ema_indicator()
    df["atr"] = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14
    ).average_true_range()
    df["adx"] = ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14
    ).adx()
    return df
def check_signal(df, i):
    if i < 1:
        return None
    previous = df.iloc[i - 1]
    current = df.iloc[i]
    if pd.isna(current["ema50"]):
        return None
    if pd.isna(current["ema200"]):
        return None
    if pd.isna(current["atr"]):
        return None
    if pd.isna(current["adx"]):
        return None
    # --------------------------------------------------------
    # BUY LIMIT
    # --------------------------------------------------------
    if (
        current["ema50"] > current["ema200"]
        and current["adx"] > ADX_MIN
        and previous["close"] > previous["ema50"]
        and current["low"] <= current["ema50"]
    ):
        entry = current["ema50"]
        atr = current["atr"]
        return {
            "direction": "BUY",
            "entry": entry,
            "sl": entry - (2 * atr),
            "tp1": entry + (1.5 * atr),
            "tp2": entry + (3 * atr),
            "signal_index": i,
            "signal_adx": current["adx"],
        }
    # --------------------------------------------------------
    # SELL LIMIT
    # --------------------------------------------------------
    if (
        current["ema50"] < current["ema200"]
        and current["adx"] > ADX_MIN
        and previous["close"] < previous["ema50"]
        and current["high"] >= current["ema50"]
    ):
        entry = current["ema50"]
        atr = current["atr"]
        return {
            "direction": "SELL",
            "entry": entry,
            "sl": entry + (2 * atr),
            "tp1": entry - (1.5 * atr),
            "tp2": entry - (3 * atr),
            "signal_index": i,
            "signal_adx": current["adx"],
        }
    return None
# ============================================================
# TRADE SIMULATION
# ============================================================
def simulate_trade(df, signal, entry_index):
    direction = signal["direction"]
    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]
    risk = abs(entry - sl)
    tp1_hit = False
    for j in range(entry_index, len(df)):
        candle = df.iloc[j]
        high = candle["high"]
        low = candle["low"]
        # ----------------------------------------------------
        # BEFORE TP1
        # ----------------------------------------------------
        if not tp1_hit:
            if direction == "BUY":
                sl_hit = low <= sl
                tp1_reached = high >= tp1
                # Conservative same-candle handling:
                # SL wins if both are touched.
                if sl_hit and tp1_reached:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "exit_index": j,
                    }
                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "exit_index": j,
                    }
                if tp1_reached:
                    tp1_hit = True
                    # Remaining 50% moves to breakeven.
                    # From TP1:
                    # first half = +0.75R x 50% = +0.375R
                    #
                    # Continue looking for TP2 or BE.
            else:
                sl_hit = high >= sl
                tp1_reached = low <= tp1
                # Conservative same-candle handling:
                # SL wins if both are touched.
                if sl_hit and tp1_reached:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "exit_index": j,
                    }
                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "exit_index": j,
                    }
                if tp1_reached:
                    tp1_hit = True
        # ----------------------------------------------------
        # AFTER TP1
        # ----------------------------------------------------
        if tp1_hit:
            if direction == "BUY":
                breakeven_hit = low <= entry
                tp2_reached = high >= tp2
                # Conservative same-candle handling:
                # BE wins if both are touched.
                if breakeven_hit and tp2_reached:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }
                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }
                if tp2_reached:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "exit_index": j,
                    }
            else:
                breakeven_hit = high >= entry
                tp2_reached = low <= tp2
                # Conservative same-candle handling:
                # BE wins if both are touched.
                if breakeven_hit and tp2_reached:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }
                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }
                if tp2_reached:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "exit_index": j,
                    }
    return None
# ============================================================
# PERIOD TEST
# ============================================================
def run_period(df, start_index, end_index):
    results = []
    i = start_index
    while i < end_index:
        signal = check_signal(df, i)
        if signal is None:
            i += 1
            continue
        signal_index = i
        entry_index = None
        entry_delay = None
        # ----------------------------------------------------
        # IMPORTANT:
        # LIMIT ENTRY CAN ONLY FILL AFTER SIGNAL CANDLE
        # ----------------------------------------------------
        for j in range(signal_index + 1, end_index):
            candle = df.iloc[j]
            if signal["direction"] == "BUY":
                if candle["low"] <= signal["entry"]:
                    entry_index = j
                    entry_delay = j - signal_index
                    break
            else:
                if candle["high"] >= signal["entry"]:
                    entry_index = j
                    entry_delay = j - signal_index
                    break
        # ----------------------------------------------------
        # NO ENTRY
        # ----------------------------------------------------
        if entry_index is None:
            results.append({
                "signal_index": signal_index,
                "direction": signal["direction"],
                "adx": signal["signal_adx"],
                "entry_delay": None,
                "no_entry": True,
                "result": "NO_ENTRY",
                "r": 0.0,
            })
            i += 1
            continue
        # ----------------------------------------------------
        # SIMULATE TRADE
        # ----------------------------------------------------
        trade = simulate_trade(
            df,
            signal,
            entry_index
        )
        if trade is None:
            results.append({
                "signal_index": signal_index,
                "direction": signal["direction"],
                "adx": signal["signal_adx"],
                "entry_delay": entry_delay,
                "no_entry": False,
                "result": "OPEN",
                "r": 0.0,
            })
            break
        results.append({
            "signal_index": signal_index,
            "direction": signal["direction"],
            "adx": signal["signal_adx"],
            "entry_delay": entry_delay,
            "no_entry": False,
            "result": trade["result"],
            "r": trade["r"],
        })
        # ----------------------------------------------------
        # NO OVERLAPPING TRADES
        # ----------------------------------------------------
        i = trade["exit_index"] + 1
    return results
# ============================================================
# SUMMARY
# ============================================================
def summarize(results):
    signals = len(results)
    no_entry = sum(
        1 for x in results
        if x["result"] == "NO_ENTRY"
    )
    tp2 = sum(
        1 for x in results
        if x["result"] == "TP2"
    )
    tp1_be = sum(
        1 for x in results
        if x["result"] == "TP1+BE"
    )
    sl = sum(
        1 for x in results
        if x["result"] == "SL"
    )
    resolved = tp2 + tp1_be + sl
    total_r = sum(
        x["r"]
        for x in results
        if x["result"] in ["TP2", "TP1+BE", "SL"]
    )
    win_rate = (
        ((tp2 + tp1_be) / resolved) * 100
        if resolved > 0
        else 0
    )
    avg_r = (
        total_r / resolved
        if resolved > 0
        else 0
    )
    return {
        "signals": signals,
        "no_entry": no_entry,
        "tp2": tp2,
        "tp1_be": tp1_be,
        "sl": sl,
        "resolved": resolved,
        "win_rate": win_rate,
        "total_r": total_r,
        "avg_r": avg_r,
    }
# ============================================================
# ENTRY DELAY BREAKDOWN
# ============================================================
def print_entry_delay_breakdown(results):
    resolved_or_open = [
        x for x in results
        if x["entry_delay"] is not None
    ]
    print()
    print("=" * 60)
    print("ENTRY FILL DELAY — OUT-OF-SAMPLE")
    print("=" * 60)
    if not resolved_or_open:
        print("No entries were filled.")
        return
    delay_counts = {}
    for trade in resolved_or_open:
        delay = trade["entry_delay"]
        if delay not in delay_counts:
            delay_counts[delay] = 0
        delay_counts[delay] += 1
    for delay in sorted(delay_counts):
        count = delay_counts[delay]
        print(
            f"Entry after {delay} candle(s): {count} trades"
        )
    print()
    print("Grouped:")
    
    groups = [
        ("1 candle", lambda x: x == 1),
        ("2 candles", lambda x: x == 2),
        ("3 candles", lambda x: x == 3),
        ("4-5 candles", lambda x: 4 <= x <= 5),
        ("6-10 candles", lambda x: 6 <= x <= 10),
        ("11-20 candles", lambda x: 11 <= x <= 20),
        ("21+ candles", lambda x: x >= 21),
    ]
    for label, condition in groups:
        count = sum(
            1
            for x in resolved_or_open
            if condition(x["entry_delay"])
        )
        print(f"{label}: {count} trades")
# ============================================================
# ENTRY DELAY PERFORMANCE
# ============================================================
def print_entry_delay_performance(results):
    print()
    print("=" * 60)
    print("ENTRY DELAY PERFORMANCE — OUT-OF-SAMPLE")
    print("=" * 60)
    groups = [
        ("1 candle", lambda x: x == 1),
        ("2 candles", lambda x: x == 2),
        ("3 candles", lambda x: x == 3),
        ("4-5 candles", lambda x: 4 <= x <= 5),
        ("6-10 candles", lambda x: 6 <= x <= 10),
        ("11-20 candles", lambda x: 11 <= x <= 20),
        ("21+ candles", lambda x: x >= 21),
    ]
    for label, condition in groups:
        group = [
            x for x in results
            if x["entry_delay"] is not None
            and condition(x["entry_delay"])
            and x["result"] in ["TP2", "TP1+BE", "SL"]
        ]
        if not group:
            print(
                f"{label}: 0 resolved trades"
            )
            continue
        tp2 = sum(
            1 for x in group
            if x["result"] == "TP2"
        )
        tp1_be = sum(
            1 for x in group
            if x["result"] == "TP1+BE"
        )
        sl = sum(
            1 for x in group
            if x["result"] == "SL"
        )
        resolved = len(group)
        wins = tp2 + tp1_be
        win_rate = (
            wins / resolved * 100
        )
        total_r = sum(
            x["r"] for x in group
        )
        avg_r = (
            total_r / resolved
        )
        print(
            f"{label}: "
            f"{resolved} trades | "
            f"Win rate: {win_rate:.2f}% | "
            f"R: {total_r:.2f} | "
            f"Avg R: {avg_r:.3f}"
        )
# ============================================================
# DATA DOWNLOAD
# ============================================================
def download_data(symbol):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": OUTPUTSIZE,
        "apikey": API_KEY,
        "format": "JSON",
    }
    response = requests.get(
        url,
        params=params,
        timeout=30,
    )
    data = response.json()
    if "values" not in data:
        print("API ERROR:")
        print(data)
        return None
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(
        df["datetime"]
    )
    df = df.sort_values(
        "datetime"
    ).reset_index(drop=True)
    for column in [
        "open",
        "high",
        "low",
        "close",
    ]:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )
    df = df[
        [
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    ]
    df = df.dropna().reset_index(drop=True)
    return df
# ============================================================
# MAIN
# ============================================================
print()
print("APEX MARKET SIGNALS")
print("ENTRY-FILL TIMING DIAGNOSTIC")
print("Trend Following Pullback Strategy")
print("Timeframe: 4H")
print(f"Historical candles: {OUTPUTSIZE}")
print("Development: 70%")
print("Out-of-sample: 30%")
print()
print("NO STRATEGY RULES ARE BEING CHANGED.")
print("TRADES CANNOT OVERLAP.")
print("THIS TEST MEASURES ENTRY-FILL DELAY.")
print()
all_oos_results = []
for symbol in SYMBOLS:
    print(f"Downloading {symbol}...")
    df = download_data(symbol)
    if df is None:
        continue
    df = prepare_data(df)
    split_index = int(
        len(df) * DEVELOPMENT_RATIO
    )
    development_results = run_period(
        df,
        1,
        split_index
    )
    oos_results = run_period(
        df,
        split_index,
        len(df)
    )
    development_summary = summarize(
        development_results
    )
    oos_summary = summarize(
        oos_results
    )
    all_oos_results.extend(oos_results)
    print()
    print(symbol)
    print(
        f"Development: "
        f"{development_summary['signals']} signals | "
        f"{development_summary['total_r']:.2f}R"
    )
    print(
        f"Out-of-sample: "
        f"{oos_summary['signals']} signals | "
        f"{oos_summary['total_r']:.2f}R"
    )
# ============================================================
# COMBINED OOS ENTRY DELAY DIAGNOSTICS
# ============================================================
print_entry_delay_breakdown(
    all_oos_results
)
print_entry_delay_performance(
    all_oos_results
)
# ============================================================
# FINAL OOS SUMMARY
# ============================================================
summary = summarize(
    all_oos_results
)
print()
print("=" * 60)
print("CURRENT OUT-OF-SAMPLE BASELINE")
print("=" * 60)
print(
    f"Signals generated: {summary['signals']}"
)
print(
    f"No-entry signals: {summary['no_entry']}"
)
print(
    f"TP2 wins: {summary['tp2']}"
)
print(
    f"TP1 + breakeven: {summary['tp1_be']}"
)
print(
    f"Full SL losses: {summary['sl']}"
)
print(
    f"Resolved trades: {summary['resolved']}"
)
print(
    f"Resolved win rate: {summary['win_rate']:.2f}%"
)
print(
    f"Total R: {summary['total_r']:.2f}R"
)
print(
    f"Average R per resolved trade: "
    f"{summary['avg_r']:.3f}R"
)
print()
print("=" * 60)
print("ENTRY-FILL TIMING DIAGNOSTIC COMPLETE")
print("=" * 60)
