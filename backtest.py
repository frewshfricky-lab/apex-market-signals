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
OUTPUTSIZE = 5000
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

    for column in ["open", "high", "low", "close"]:
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

    previous = df.iloc[i - 1]
    current = df.iloc[i]

    ema50 = current["ema50"]
    ema200 = current["ema200"]
    atr = current["atr"]
    adx = current["adx"]

    if (
        pd.isna(ema50)
        or pd.isna(ema200)
        or pd.isna(atr)
        or pd.isna(adx)
    ):
        return None

    # =========================
    # BUY LIMIT
    # =========================

    if (
        ema50 > ema200
        and adx > 20
        and previous["close"] > previous["ema50"]
        and current["low"] <= ema50
    ):

        entry = ema50

        return {
            "direction": "BUY",
            "entry": entry,
            "sl": entry - (2 * atr),
            "tp1": entry + (1.5 * atr),
            "tp2": entry + (3 * atr),
            "adx": adx,
            "signal_index": i,
        }

    # =========================
    # SELL LIMIT
    # =========================

    if (
        ema50 < ema200
        and adx > 20
        and previous["close"] < previous["ema50"]
        and current["high"] >= ema50
    ):

        entry = ema50

        return {
            "direction": "SELL",
            "entry": entry,
            "sl": entry + (2 * atr),
            "tp1": entry - (1.5 * atr),
            "tp2": entry - (3 * atr),
            "adx": adx,
            "signal_index": i,
        }

    return None


def manage_trade(df, signal):

    direction = signal["direction"]

    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]

    signal_index = signal["signal_index"]

    # ==========================================
    # STEP 1 — WAIT FOR ACTUAL ENTRY
    # ==========================================

    entry_index = None

    for j in range(
        signal_index + 1,
        len(df)
    ):

        candle = df.iloc[j]

        if direction == "BUY":

            if candle["low"] <= entry:
                entry_index = j
                break

        else:

            if candle["high"] >= entry:
                entry_index = j
                break

    if entry_index is None:

        return {
            "result": "NO_ENTRY",
            "r": 0.0,
            "entry_index": None,
            "exit_index": None,
        }

    # ==========================================
    # STEP 2 — MANAGE AFTER ENTRY
    # ==========================================

    tp1_hit = False

    for j in range(
        entry_index,
        len(df)
    ):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        # ======================================
        # BUY
        # ======================================

        if direction == "BUY":

            if not tp1_hit:

                sl_hit = low <= sl
                tp1_hit_this_candle = high >= tp1

                if (
                    sl_hit
                    and tp1_hit_this_candle
                ):

                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if sl_hit:

                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if tp1_hit_this_candle:

                    tp1_hit = True
                    continue

            if tp1_hit:

                breakeven_hit = low <= entry
                tp2_hit = high >= tp2

                if (
                    breakeven_hit
                    and tp2_hit
                ):

                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if breakeven_hit:

                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if tp2_hit:

                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

        # ======================================
        # SELL
        # ======================================

        else:

            if not tp1_hit:

                sl_hit = high >= sl
                tp1_hit_this_candle = low <= tp1

                if (
                    sl_hit
                    and tp1_hit_this_candle
                ):

                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if sl_hit:

                    return {
                        "result": "SL",
                        "r": -1.0,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if tp1_hit_this_candle:

                    tp1_hit = True
                    continue

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
                        "exit_index": j,
                    }

                if breakeven_hit:

                    return {
                        "result": "TP1+BE",
                        "r": 0.375,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

                if tp2_hit:

                    return {
                        "result": "TP2",
                        "r": 1.125,
                        "entry_index": entry_index,
                        "exit_index": j,
                    }

    return {
        "result": "OPEN",
        "r": 0.0,
        "entry_index": entry_index,
        "exit_index": None,
    }


def run_period(df, symbol, start, end):

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

        trade = manage_trade(
            df,
            signal
        )

        trade["symbol"] = symbol
        trade["direction"] = signal["direction"]
        trade["adx"] = signal["adx"]

        results.append(trade)

        # ======================================
        # IMPORTANT:
        # Do not allow another trade while
        # this trade is still active.
        # ======================================

        if trade["exit_index"] is not None:

            i = trade["exit_index"] + 1

        elif trade["entry_index"] is not None:

            i = len(df)

        else:

            i += 1

    return results


def summarize(results):

    resolved = [
        r for r in results
        if r["result"]
        in ["TP2", "TP1+BE", "SL"]
    ]

    tp2 = sum(
        r["result"] == "TP2"
        for r in resolved
    )

    tp1_be = sum(
        r["result"] == "TP1+BE"
        for r in resolved
    )

    sl = sum(
        r["result"] == "SL"
        for r in resolved
    )

    no_entry = sum(
        r["result"] == "NO_ENTRY"
        for r in results
    )

    wins = tp2 + tp1_be

    win_rate = (
        wins / len(resolved) * 100
        if resolved
        else 0
    )

    total_r = sum(
        r["r"]
        for r in resolved
    )

    average_r = (
        total_r / len(resolved)
        if resolved
        else 0
    )

    return {
        "signals": len(results),
        "no_entry": no_entry,
        "tp2": tp2,
        "tp1_be": tp1_be,
        "sl": sl,
        "resolved": len(resolved),
        "win_rate": win_rate,
        "total_r": total_r,
        "average_r": average_r,
    }


def print_summary(title, summary):

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


def print_diagnostic(title, results):

    print()
    print("=" * 60)
    print(title)
    print("=" * 60)

    resolved = [
        r for r in results
        if r["result"]
        in ["TP2", "TP1+BE", "SL"]
    ]

    for symbol in SYMBOLS:

        symbol_trades = [
            r for r in resolved
            if r["symbol"] == symbol
        ]

        if not symbol_trades:
            continue

        buys = [
            r for r in symbol_trades
            if r["direction"] == "BUY"
        ]

        sells = [
            r for r in symbol_trades
            if r["direction"] == "SELL"
        ]

        def direction_stats(trades):

            tp2 = sum(
                r["result"] == "TP2"
                for r in trades
            )

            tp1_be = sum(
                r["result"] == "TP1+BE"
                for r in trades
            )

            sl = sum(
                r["result"] == "SL"
                for r in trades
            )

            total_r = sum(
                r["r"]
                for r in trades
            )

            return (
                len(trades),
                tp2,
                tp1_be,
                sl,
                total_r
            )

        b = direction_stats(buys)
        s = direction_stats(sells)

        print()
        print(symbol)

        print(
            f"  BUY  | "
            f"Trades: {b[0]} | "
            f"TP2: {b[1]} | "
            f"TP1+BE: {b[2]} | "
            f"SL: {b[3]} | "
            f"R: {b[4]:.2f}"
        )

        print(
            f"  SELL | "
            f"Trades: {s[0]} | "
            f"TP2: {s[1]} | "
            f"TP1+BE: {s[2]} | "
            f"SL: {s[3]} | "
            f"R: {s[4]:.2f}"
        )

    # ==========================================
    # ADX BREAKDOWN
    # ==========================================

    print()
    print("=" * 60)
    print("ADX BREAKDOWN — OUT-OF-SAMPLE")
    print("=" * 60)

    adx_ranges = [
        ("20-25", 20, 25),
        ("25-30", 25, 30),
        ("30-40", 30, 40),
        ("40+", 40, float("inf")),
    ]

    for label, low_adx, high_adx in adx_ranges:

        group = [
            r for r in resolved
            if low_adx <= r["adx"] < high_adx
        ]

        if not group:
            print(
                f"ADX {label}: 0 trades"
            )
            continue

        wins = sum(
            r["result"]
            in ["TP2", "TP1+BE"]
            for r in group
        )

        total_r = sum(
            r["r"]
            for r in group
        )

        win_rate = (
            wins / len(group) * 100
        )

        print(
            f"ADX {label}: "
            f"{len(group)} trades | "
            f"Win rate: {win_rate:.2f}% | "
            f"R: {total_r:.2f}"
        )


def main():

    print()
    print("APEX MARKET SIGNALS")
    print("STRATEGY DIAGNOSTIC BACKTEST")
    print("Trend Following Pullback Strategy")
    print("Timeframe: 4H")
    print("Historical candles: 5000")
    print("Development: 70%")
    print("Out-of-sample: 30%")
    print()
    print(
        "No strategy rules are being changed."
    )
    print(
        "Trades cannot overlap."
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
            symbol,
            0,
            split_index
        )

        out_of_sample = run_period(
            df,
            symbol,
            split_index,
            len(df)
        )

        all_development.extend(
            development
        )

        all_oos.extend(
            out_of_sample
        )

        dev = summarize(
            development
        )

        oos = summarize(
            out_of_sample
        )

        print()
        print(symbol)

        print(
            f"Development: "
            f"{dev['signals']} signals | "
            f"{dev['total_r']:.2f}R"
        )

        print(
            f"Out-of-sample: "
            f"{oos['signals']} signals | "
            f"{oos['total_r']:.2f}R"
        )

    print_summary(
        "COMBINED DEVELOPMENT RESULTS",
        summarize(all_development)
    )

    print_summary(
        "COMBINED OUT-OF-SAMPLE RESULTS",
        summarize(all_oos)
    )

    print_diagnostic(
        "DIRECTION BREAKDOWN — OUT-OF-SAMPLE",
        all_oos
    )

    print()
    print("=" * 60)
    print("DIAGNOSTIC TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
