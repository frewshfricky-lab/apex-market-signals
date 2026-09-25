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

TIMEFRAME = "4h"
OUTPUTSIZE = 1000

DEV_SPLIT = 0.70


def get_data(symbol):
    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "outputsize": OUTPUTSIZE,
        "apikey": API_KEY,
        "order": "asc",
        "timezone": "UTC",
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    data = response.json()

    if "values" not in data:
        print(f"{symbol}: ERROR - {data}")
        return None

    df = pd.DataFrame(data["values"])

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True
    )

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

    df = df.sort_values(
        "datetime"
    ).reset_index(drop=True)

    df = df.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close"
        ]
    ).reset_index(drop=True)

    return df


def calculate_indicators(df):
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

    return df.dropna().reset_index(drop=True)


def check_signal(df, i):
    if i < 1:
        return None

    previous = df.iloc[i]
    current = df.iloc[i]

    previous_candle = df.iloc[i - 1]

    ema50 = current["ema50"]
    ema200 = current["ema200"]
    atr = current["atr"]
    adx = current["adx"]

    if pd.isna(ema50):
        return None

    if pd.isna(ema200):
        return None

    if pd.isna(atr):
        return None

    if pd.isna(adx):
        return None

    # =========================
    # BUY LIMIT
    # =========================

    if (
        ema50 > ema200
        and adx > 20
        and previous_candle["close"] > previous_candle["ema50"]
        and current["low"] <= ema50
    ):
        entry = ema50

        sl = entry - (2 * atr)

        tp1 = entry + (1.5 * atr)

        tp2 = entry + (3 * atr)

        return {
            "direction": "BUY",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    # =========================
    # SELL LIMIT
    # =========================

    if (
        ema50 < ema200
        and adx > 20
        and previous_candle["close"] < previous_candle["ema50"]
        and current["high"] >= ema50
    ):
        entry = ema50

        sl = entry + (2 * atr)

        tp1 = entry - (1.5 * atr)

        tp2 = entry - (3 * atr)

        return {
            "direction": "SELL",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    return None


def find_entry_and_manage_trade(
    df,
    signal_index,
    signal
):
    direction = signal["direction"]

    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]

    entry_index = None

    # ==================================================
    # STEP 1
    # WAIT FOR THE LIMIT ORDER TO ACTUALLY FILL
    # ==================================================

    for j in range(
        signal_index + 1,
        len(df)
    ):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        if direction == "BUY":

            if low <= entry:
                entry_index = j
                break

        else:

            if high >= entry:
                entry_index = j
                break

    # Entry was never reached.
    if entry_index is None:
        return {
            "result": "NO_ENTRY",
            "r": 0.0,
        }

    # ==================================================
    # STEP 2
    # MANAGE THE TRADE AFTER ENTRY
    # ==================================================

    tp1_hit = False

    for j in range(
        entry_index,
        len(df)
    ):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        # ==============================================
        # BUY TRADE
        # ==============================================

        if direction == "BUY":

            if not tp1_hit:

                sl_hit = low <= sl

                tp1_hit_this_candle = (
                    high >= tp1
                )

                # Conservative handling when both
                # SL and TP1 occur inside one candle.
                if sl_hit and tp1_hit_this_candle:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                    }

                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                    }

                if tp1_hit_this_candle:
                    tp1_hit = True
                    continue

            # ==========================================
            # AFTER TP1
            # Remaining 50% moves to breakeven.
            # ==========================================

            if tp1_hit:

                breakeven_hit = low <= entry

                tp2_hit = high >= tp2

                # Conservative:
                # if BE and TP2 happen in same candle,
                # count BE.
                if (
                    breakeven_hit
                    and tp2_hit
                ):
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                    }

                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "entry_index": entry_index,
                    }

        # ==============================================
        # SELL TRADE
        # ==============================================

        else:

            if not tp1_hit:

                sl_hit = high >= sl

                tp1_hit_this_candle = (
                    low <= tp1
                )

                if sl_hit and tp1_hit_this_candle:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                    }

                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                    }

                if tp1_hit_this_candle:
                    tp1_hit = True
                    continue

            # ==========================================
            # AFTER TP1
            # Remaining 50% moves to breakeven.
            # ==========================================

            if tp1_hit:

                breakeven_hit = high >= entry

                tp2_hit = low <= tp2

                if (
                    breakeven_hit
                    and tp2_hit
                ):
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                    }

                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "entry_index": entry_index,
                    }

    return {
        "result": "OPEN",
        "r": 0.0,
        "entry_index": entry_index,
    }


def run_period(
    df,
    start,
    end
):

    results = []

    i = start

    while i < end - 1:

        signal = check_signal(
            df,
            i
        )

        if signal is None:
            i += 1
            continue

        trade = find_entry_and_manage_trade(
            df,
            i,
            signal
        )

        results.append(trade)

        # If the trade entered and finished,
        # don't allow overlapping trades.
        if "entry_index" in trade:
            entry_index = trade["entry_index"]

            i = max(
                i + 1,
                entry_index
            )
        else:
            i += 1

    return results


def summarize(results):

    total_signals = len(results)

    no_entry = sum(
        1
        for r in results
        if r["result"] == "NO_ENTRY"
    )

    tp2 = sum(
        1
        for r in results
        if r["result"] == "TP2"
    )

    tp1_be = sum(
        1
        for r in results
        if r["result"] == "TP1+BE"
    )

    sl = sum(
        1
        for r in results
        if r["result"] == "SL"
    )

    open_trades = sum(
        1
        for r in results
        if r["result"] == "OPEN"
    )

    resolved = (
        tp2
        + tp1_be
        + sl
    )

    wins = (
        tp2
        + tp1_be
    )

    win_rate = (
        wins / resolved * 100
        if resolved > 0
        else 0
    )

    total_r = sum(
        r["r"]
        for r in results
    )

    average_r = (
        total_r / resolved
        if resolved > 0
        else 0
    )

    return {
        "signals": total_signals,
        "no_entry": no_entry,
        "tp2": tp2,
        "tp1_be": tp1_be,
        "sl": sl,
        "open": open_trades,
        "resolved": resolved,
        "win_rate": win_rate,
        "total_r": total_r,
        "average_r": average_r,
    }


def print_summary(
    title,
    summary
):

    print()
    print("=" * 60)
    print(title)
    print("=" * 60)

    print(
        f"Signals generated: "
        f"{summary['signals']}"
    )

    print(
        f"No-entry signals: "
        f"{summary['no_entry']}"
    )

    print(
        f"TP2 wins: "
        f"{summary['tp2']}"
    )

    print(
        f"TP1 + breakeven: "
        f"{summary['tp1_be']}"
    )

    print(
        f"Full SL losses: "
        f"{summary['sl']}"
    )

    print(
        f"Open/unresolved: "
        f"{summary['open']}"
    )

    print(
        f"Resolved trades: "
        f"{summary['resolved']}"
    )

    print(
        f"Resolved win rate: "
        f"{summary['win_rate']:.2f}%"
    )

    print(
        f"Total R: "
        f"{summary['total_r']:.2f}R"
    )

    print(
        f"Average R per resolved trade: "
        f"{summary['average_r']:.3f}R"
    )


def main():

    print()
    print("APEX MARKET SIGNALS")
    print("ENTRY-FILL AUDIT BACKTEST")
    print("Trend Following Pullback Strategy")
    print("Timeframe: 4H")
    print("Development: 70%")
    print("Out-of-sample: 30%")
    print()
    print(
        "IMPORTANT: A signal is only counted as a trade "
        "after the EMA50 limit entry is actually reached."
    )
    print()

    all_development = []
    all_oos = []

    for symbol in SYMBOLS:

        print(
            f"Downloading {symbol}..."
        )

        df = get_data(symbol)

        if df is None:
            continue

        if len(df) < 300:

            print(
                f"{symbol}: Not enough candles "
                f"({len(df)})"
            )

            continue

        df = calculate_indicators(df)

        split_index = int(
            len(df) * DEV_SPLIT
        )

        development = run_period(
            df,
            0,
            split_index
        )

        out_of_sample = run_period(
            df,
            split_index,
            len(df)
        )

        dev_summary = summarize(
            development
        )

        oos_summary = summarize(
            out_of_sample
        )

        all_development.extend(
            development
        )

        all_oos.extend(
            out_of_sample
        )

        print()
        print(symbol)

        print(
            f"Development: "
            f"{dev_summary['signals']} signals | "
            f"{dev_summary['no_entry']} no-entry | "
            f"{dev_summary['total_r']:.2f}R"
        )

        print(
            f"Out-of-sample: "
            f"{oos_summary['signals']} signals | "
            f"{oos_summary['no_entry']} no-entry | "
            f"{oos_summary['total_r']:.2f}R"
        )

    print_summary(
        "COMBINED DEVELOPMENT RESULTS",
        summarize(all_development)
    )

    print_summary(
        "COMBINED OUT-OF-SAMPLE RESULTS",
        summarize(all_oos)
    )

    print()
    print("=" * 60)
    print("ENTRY-FILL AUDIT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
