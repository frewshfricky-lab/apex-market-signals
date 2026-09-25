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
# DATA PREPARATION
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


# ============================================================
# SIGNAL RULES — FROZEN
# ============================================================

def check_signal(df, i):

    if i < 1:
        return None

    previous = df.iloc[i - 1]
    current = df.iloc[i]

    if (
        pd.isna(current["ema50"])
        or pd.isna(current["ema200"])
        or pd.isna(current["atr"])
        or pd.isna(current["adx"])
    ):
        return None

    # BUY LIMIT
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
            "adx": current["adx"],
        }

    # SELL LIMIT
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
            "adx": current["adx"],
        }

    return None


# ============================================================
# TRADE SIMULATION
#
# end_index is EXCLUSIVE.
#
# Development trades:
#   signal, entry and trade management must all finish
#   before the OOS boundary.
#
# OOS trades:
#   may continue until the historical dataset ends.
# ============================================================

def simulate_trade(
    df,
    signal,
    entry_index,
    end_index
):

    direction = signal["direction"]

    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]

    tp1_hit = False

    for j in range(entry_index, end_index):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        # ----------------------------------------------------
        # BEFORE TP1
        # ----------------------------------------------------

        if not tp1_hit:

            if direction == "BUY":

                sl_hit = low <= sl
                tp1_hit_now = high >= tp1

                # Conservative same-candle assumption:
                # SL is considered first.
                if sl_hit and tp1_hit_now:
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

                if tp1_hit_now:
                    tp1_hit = True

            else:

                sl_hit = high >= sl
                tp1_hit_now = low <= tp1

                # Conservative same-candle assumption:
                # SL is considered first.
                if sl_hit and tp1_hit_now:
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

                if tp1_hit_now:
                    tp1_hit = True

        # ----------------------------------------------------
        # AFTER TP1
        # ----------------------------------------------------

        if tp1_hit:

            if direction == "BUY":

                be_hit = low <= entry
                tp2_hit = high >= tp2

                # Conservative same-candle assumption:
                # BE is considered first.
                if be_hit and tp2_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }

                if be_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "exit_index": j,
                    }

            else:

                be_hit = high >= entry
                tp2_hit = low <= tp2

                # Conservative same-candle assumption:
                # BE is considered first.
                if be_hit and tp2_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }

                if be_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "exit_index": j,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "exit_index": j,
                    }

    return None


# ============================================================
# PERIOD TEST
# ============================================================

def run_period(
    df,
    start_index,
    signal_end_index,
    trade_end_index
):

    results = []

    i = start_index

    while i < signal_end_index:

        signal = check_signal(df, i)

        if signal is None:
            i += 1
            continue

        signal_index = i

        # ----------------------------------------------------
        # ENTRY MUST OCCUR AFTER SIGNAL CANDLE
        # ----------------------------------------------------

        entry_index = None

        for j in range(
            signal_index + 1,
            trade_end_index
        ):

            candle = df.iloc[j]

            if signal["direction"] == "BUY":

                if candle["low"] <= signal["entry"]:
                    entry_index = j
                    break

            else:

                if candle["high"] >= signal["entry"]:
                    entry_index = j
                    break

        # ----------------------------------------------------
        # NO ENTRY
        # ----------------------------------------------------

        if entry_index is None:

            results.append({
                "signal_index": signal_index,
                "direction": signal["direction"],
                "adx": signal["adx"],
                "entry_delay": None,
                "result": "NO_ENTRY",
                "r": 0.0,
            })

            i += 1
            continue

        entry_delay = entry_index - signal_index

        # ----------------------------------------------------
        # TRADE
        # ----------------------------------------------------

        trade = simulate_trade(
            df,
            signal,
            entry_index,
            trade_end_index
        )

        if trade is None:

            results.append({
                "signal_index": signal_index,
                "direction": signal["direction"],
                "adx": signal["adx"],
                "entry_delay": entry_delay,
                "result": "OPEN",
                "r": 0.0,
            })

            # Stop because an unresolved trade means no
            # overlapping trades are allowed.
            break

        results.append({
            "signal_index": signal_index,
            "direction": signal["direction"],
            "adx": signal["adx"],
            "entry_delay": entry_delay,
            "result": trade["result"],
            "r": trade["r"],
            "exit_index": trade["exit_index"],
        })

        # ----------------------------------------------------
        # NO OVERLAPPING TRADES
        # ----------------------------------------------------

        i = trade["exit_index"] + 1

    return results


# ============================================================
# SUMMARY
# ============================================================

def summary(results):

    tp2 = sum(
        x["result"] == "TP2"
        for x in results
    )

    tp1be = sum(
        x["result"] == "TP1+BE"
        for x in results
    )

    sl = sum(
        x["result"] == "SL"
        for x in results
    )

    no_entry = sum(
        x["result"] == "NO_ENTRY"
        for x in results
    )

    open_trades = sum(
        x["result"] == "OPEN"
        for x in results
    )

    resolved = tp2 + tp1be + sl

    total_r = sum(
        x["r"]
        for x in results
    )

    win_rate = (
        (tp2 + tp1be) / resolved * 100
        if resolved
        else 0
    )

    avg_r = (
        total_r / resolved
        if resolved
        else 0
    )

    return {
        "signals": len(results),
        "no_entry": no_entry,
        "open": open_trades,
        "tp2": tp2,
        "tp1be": tp1be,
        "sl": sl,
        "resolved": resolved,
        "win_rate": win_rate,
        "total_r": total_r,
        "avg_r": avg_r,
    }


# ============================================================
# DOWNLOAD DATA
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

    df = pd.DataFrame(
        data["values"]
    )

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
        "close"
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
            "close"
        ]
    ]

    df = df.dropna().reset_index(
        drop=True
    )

    return df


# ============================================================
# MAIN
# ============================================================

print()
print("=" * 60)
print("APEX MARKET SIGNALS")
print("CLEAN 70/30 BACKTEST AUDIT")
print("=" * 60)
print("Trend Following Pullback Strategy")
print("Timeframe: 4H")
print(f"Historical candles requested: {OUTPUTSIZE}")
print("Development: 70%")
print("Out-of-sample: 30%")
print()
print("STRATEGY RULES FROZEN.")
print("NO ADX CHANGES.")
print("NO PAIR REMOVALS.")
print("NO NEW FILTERS.")
print("NO OVERLAPPING TRADES.")
print()
print("DEVELOPMENT TRADES CANNOT CROSS INTO OOS.")
print("OOS TRADES MAY CONTINUE TO DATASET END.")
print("=" * 60)

combined_development = []
combined_oos = []

oos_by_symbol = {}

for symbol in SYMBOLS:

    print()
    print(f"Downloading {symbol}...")

    df = download_data(symbol)

    if df is None:
        continue

    df = prepare_data(df)

    split_index = int(
        len(df) * DEVELOPMENT_RATIO
    )

    print(
        f"Data candles: {len(df)}"
    )

    print(
        f"Data start: {df['datetime'].iloc[0]}"
    )

    print(
        f"Data end: {df['datetime'].iloc[-1]}"
    )

    print(
        f"Development end index: {split_index}"
    )

    # --------------------------------------------------------
    # DEVELOPMENT
    #
    # Signals, entries and trade exits MUST all occur before
    # the OOS boundary.
    # --------------------------------------------------------

    development_results = run_period(
        df,
        1,
        split_index,
        split_index
    )

    # --------------------------------------------------------
    # OOS
    #
    # Signals start at the OOS boundary.
    # Entries and trade management can continue until the
    # historical dataset ends.
    # --------------------------------------------------------

    oos_results = run_period(
        df,
        split_index,
        len(df),
        len(df)
    )

    combined_development.extend(
        development_results
    )

    combined_oos.extend(
        oos_results
    )

    oos_by_symbol[symbol] = oos_results

    dev = summary(
        development_results
    )

    oos = summary(
        oos_results
    )

    print()
    print(symbol)

    print(
        f"Development: "
        f"{dev['signals']} signals | "
        f"{dev['total_r']:.2f}R"
    )

    print(
        f"OOS: "
        f"{oos['signals']} signals | "
        f"{oos['total_r']:.2f}R"
    )


# ============================================================
# DEVELOPMENT RESULTS
# ============================================================

dev = summary(
    combined_development
)

print()
print("=" * 60)
print("COMBINED DEVELOPMENT RESULTS")
print("=" * 60)

print(
    f"Signals generated: {dev['signals']}"
)

print(
    f"No-entry signals: {dev['no_entry']}"
)

print(
    f"Open trades: {dev['open']}"
)

print(
    f"TP2 wins: {dev['tp2']}"
)

print(
    f"TP1 + breakeven: {dev['tp1be']}"
)

print(
    f"Full SL losses: {dev['sl']}"
)

print(
    f"Resolved trades: {dev['resolved']}"
)

print(
    f"Resolved win rate: {dev['win_rate']:.2f}%"
)

print(
    f"Total R: {dev['total_r']:.2f}R"
)

print(
    f"Average R per resolved trade: "
    f"{dev['avg_r']:.3f}R"
)


# ============================================================
# OOS RESULTS
# ============================================================

oos = summary(
    combined_oos
)

print()
print("=" * 60)
print("COMBINED OUT-OF-SAMPLE RESULTS")
print("=" * 60)

print(
    f"Signals generated: {oos['signals']}"
)

print(
    f"No-entry signals: {oos['no_entry']}"
)

print(
    f"Open trades: {oos['open']}"
)

print(
    f"TP2 wins: {oos['tp2']}"
)

print(
    f"TP1 + breakeven: {oos['tp1be']}"
)

print(
    f"Full SL losses: {oos['sl']}"
)

print(
    f"Resolved trades: {oos['resolved']}"
)

print(
    f"Resolved win rate: {oos['win_rate']:.2f}%"
)

print(
    f"Total R: {oos['total_r']:.2f}R"
)

print(
    f"Average R per resolved trade: "
    f"{oos['avg_r']:.3f}R"
)


# ============================================================
# FINAL
# ============================================================

print()
print("=" * 60)
print("CLEAN 70/30 BACKTEST AUDIT COMPLETE")
print("=" * 60)
print()
print("STRATEGY RULES WERE NOT CHANGED.")
print("ONLY THE DEVELOPMENT/OOS TRADE BOUNDARY WAS ENFORCED.")
print("=" * 60)
