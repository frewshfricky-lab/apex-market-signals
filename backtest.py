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

INITIAL_RISK = 1.0

TP1_R = 0.75
TP2_R = 1.50


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

    response = requests.get(url, params=params, timeout=30)
    data = response.json()

    if "values" not in data:
        print(f"{symbol}: ERROR - {data}")
        return None

    df = pd.DataFrame(data["values"])

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.sort_values("datetime").reset_index(drop=True)

    df = df.dropna(
        subset=["datetime", "open", "high", "low", "close"]
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

    previous = df.iloc[i - 1]
    current = df.iloc[i]

    ema50 = current["ema50"]
    ema200 = current["ema200"]
    atr = current["atr"]
    adx = current["adx"]

    if pd.isna(ema50) or pd.isna(ema200):
        return None

    if pd.isna(atr) or pd.isna(adx):
        return None

    # -------------------------
    # BUY LIMIT
    # -------------------------

    if (
        ema50 > ema200
        and adx > 20
        and previous["close"] > previous["ema50"]
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

    # -------------------------
    # SELL LIMIT
    # -------------------------

    if (
        ema50 < ema200
        and adx > 20
        and previous["close"] < previous["ema50"]
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


def backtest_trade(df, start_index, signal):
    direction = signal["direction"]

    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]

    tp1_hit = False

    # The signal candle has already closed.
    # Entry is therefore evaluated from the NEXT candle.
    for j in range(start_index, len(df)):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        if direction == "BUY":

            # Before TP1:
            # If SL and TP1 occur in the same candle,
            # use the conservative assumption that SL happened first.
            if not tp1_hit:

                sl_hit = low <= sl
                tp1_hit_this_candle = high >= tp1

                if sl_hit and tp1_hit_this_candle:
                    return {
                        "result": "SL",
                        "r": -1.0,
                    }

                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                    }

                if tp1_hit_this_candle:
                    tp1_hit = True
                    continue

            # After TP1:
            # Remaining 50% has SL moved to breakeven.
            if tp1_hit:

                breakeven_hit = low <= entry
                tp2_hit = high >= tp2

                # Conservative assumption:
                # if both happen in same candle,
                # count breakeven before TP2.
                if breakeven_hit and tp2_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                    }

                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                    }

        else:

            # SELL
            if not tp1_hit:

                sl_hit = high >= sl
                tp1_hit_this_candle = low <= tp1

                if sl_hit and tp1_hit_this_candle:
                    return {
                        "result": "SL",
                        "r": -1.0,
                    }

                if sl_hit:
                    return {
                        "result": "SL",
                        "r": -1.0,
                    }

                if tp1_hit_this_candle:
                    tp1_hit = True
                    continue

            # After TP1:
            # Remaining 50% moves to breakeven.
            if tp1_hit:

                breakeven_hit = high >= entry
                tp2_hit = low <= tp2

                if breakeven_hit and tp2_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                    }

                if breakeven_hit:
                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                    }

                if tp2_hit:
                    return {
                        "result": "TP2",
                        "r": 1.125,
                    }

    return {
        "result": "OPEN",
        "r": 0.0,
    }


def run_period(df, start, end):
    results = []

    i = start

    while i < end - 1:

        signal = check_signal(df, i)

        if signal is None:
            i += 1
            continue

        trade = backtest_trade(
            df,
            i + 1,
            signal
        )

        results.append(trade)

        # Move forward after the trade finishes.
        # This prevents overlapping trades.
        i += 1

    return results


def summarize(results):
    total = len(results)

    tp2 = sum(
        1 for r in results
        if r["result"] == "TP2"
    )

    tp1_be = sum(
        1 for r in results
        if r["result"] == "TP1+BE"
    )

    sl = sum(
        1 for r in results
        if r["result"] == "SL"
    )

    open_trades = sum(
        1 for r in results
        if r["result"] == "OPEN"
    )

    resolved = total - open_trades

    wins = tp2 + tp1_be

    win_rate = (
        wins / resolved * 100
        if resolved > 0
        else 0
    )

    total_r = sum(
        r["r"] for r in results
    )

    average_r = (
        total_r / resolved
        if resolved > 0
        else 0
    )

    return {
        "total": total,
        "tp2": tp2,
        "tp1_be": tp1_be,
        "sl": sl,
        "open": open_trades,
        "resolved": resolved,
        "win_rate": win_rate,
        "total_r": total_r,
        "average_r": average_r,
    }


def print_summary(title, summary):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)

    print(f"Total signals: {summary['total']}")
    print(f"TP2 wins: {summary['tp2']}")
    print(f"TP1 + breakeven: {summary['tp1_be']}")
    print(f"Full SL losses: {summary['sl']}")
    print(f"Open/unresolved: {summary['open']}")

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
    print("OUT-OF-SAMPLE BACKTEST")
    print("Trend Following Pullback Strategy")
    print("Timeframe: 4H")
    print("Development: 70%")
    print("Out-of-sample: 30%")
    print()

    all_development_results = []
    all_oos_results = []

    for symbol in SYMBOLS:

        print(f"Downloading {symbol}...")

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

        all_development_results.extend(
            development
        )

        all_oos_results.extend(
            out_of_sample
        )

        print()
        print(f"{symbol}")
        print(
            f"Development: "
            f"{dev_summary['total']} trades | "
            f"{dev_summary['total_r']:.2f}R"
        )

        print(
            f"Out-of-sample: "
            f"{oos_summary['total']} trades | "
            f"{oos_summary['total_r']:.2f}R"
        )

    print_summary(
        "COMBINED DEVELOPMENT RESULTS",
        summarize(all_development_results)
    )

    print_summary(
        "COMBINED OUT-OF-SAMPLE RESULTS",
        summarize(all_oos_results)
    )

    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
