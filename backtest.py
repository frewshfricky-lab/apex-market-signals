import os
import requests
import pandas as pd

from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange


# ============================================================
# APEX MARKET SIGNALS — BACKTEST
# Trend Following Pullback Strategy
# Timeframe: 4H
# ============================================================

API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

SYMBOLS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "BTC/USD",
]

TIMEFRAME = "4h"

# Number of historical candles to download
OUTPUT_SIZE = 1000


# ============================================================
# GET HISTORICAL DATA
# ============================================================

def get_historical_data(symbol):
    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "outputsize": OUTPUT_SIZE,
        "order": "asc",
        "timezone": "UTC",
        "apikey": API_KEY,
    }

    response = requests.get(
        TWELVE_DATA_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(
            f"Twelve Data error for {symbol}: "
            f"{data.get('message', 'Unknown error')}"
        )

    if "values" not in data:
        raise RuntimeError(
            f"No historical data returned for {symbol}."
        )

    df = pd.DataFrame(data["values"])

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True,
    )

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna(
        subset=["open", "high", "low", "close"]
    )

    df = df.sort_values("datetime")
    df = df.reset_index(drop=True)

    return df


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):
    df = df.copy()

    df["ema50"] = EMAIndicator(
        close=df["close"],
        window=50,
    ).ema_indicator()

    df["ema200"] = EMAIndicator(
        close=df["close"],
        window=200,
    ).ema_indicator()

    df["atr"] = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    ).average_true_range()

    df["adx"] = ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    ).adx()

    return df


# ============================================================
# BACKTEST ONE SYMBOL
# ============================================================

def backtest_symbol(symbol):

    print("\n" + "=" * 60)
    print(f"BACKTESTING {symbol}")
    print("=" * 60)

    df = get_historical_data(symbol)
    df = add_indicators(df)

    trades = []

    # We need enough history for EMA200.
    for i in range(201, len(df) - 1):

        previous = df.iloc[i - 1]
        current = df.iloc[i]

        ema50 = current["ema50"]
        ema200 = current["ema200"]
        atr = current["atr"]
        adx = current["adx"]

        if any(
            pd.isna(value)
            for value in [
                ema50,
                ema200,
                atr,
                adx,
            ]
        ):
            continue

        # ----------------------------------------------------
        # BUY SETUP
        # ----------------------------------------------------

        buy_setup = (
            ema50 > ema200
            and adx > 20
            and previous["close"] > ema50
            and current["low"] <= ema50
        )

        if buy_setup:

            entry = ema50
            stop_loss = entry - (2 * atr)
            tp1 = entry + (1.5 * atr)
            tp2 = entry + (3 * atr)

            result = simulate_trade(
                df,
                i + 1,
                entry,
                stop_loss,
                tp1,
                tp2,
                "BUY",
            )

            if result:
                result["symbol"] = symbol
                result["signal_time"] = current["datetime"]

                trades.append(result)

        # ----------------------------------------------------
        # SELL SETUP
        # ----------------------------------------------------

        sell_setup = (
            ema50 < ema200
            and adx > 20
            and previous["close"] < ema50
            and current["high"] >= ema50
        )

        if sell_setup:

            entry = ema50
            stop_loss = entry + (2 * atr)
            tp1 = entry - (1.5 * atr)
            tp2 = entry - (3 * atr)

            result = simulate_trade(
                df,
                i + 1,
                entry,
                stop_loss,
                tp1,
                tp2,
                "SELL",
            )

            if result:
                result["symbol"] = symbol
                result["signal_time"] = current["datetime"]

                trades.append(result)

    return pd.DataFrame(trades)


# ============================================================
# SIMULATE TRADE
# ============================================================

def simulate_trade(
    df,
    start_index,
    entry,
    stop_loss,
    tp1,
    tp2,
    direction,
):

    entry_filled = False

    for j in range(
        start_index,
        len(df),
    ):

        candle = df.iloc[j]

        high = candle["high"]
        low = candle["low"]

        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        if direction == "BUY":

            if not entry_filled:

                if low <= entry <= high:
                    entry_filled = True
                else:
                    continue

            # After entry, check SL/TP.
            hit_sl = low <= stop_loss
            hit_tp2 = high >= tp2
            hit_tp1 = high >= tp1

            # Conservative rule:
            # If SL and TP happen in the same candle,
            # count the trade as SL.
            if hit_sl:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "SL",
                    "r_multiple": -1.0,
                }

            if hit_tp2:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "TP2",
                    "r_multiple": 1.5,
                }

            if hit_tp1:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "TP1",
                    "r_multiple": 0.75,
                }

        # ----------------------------------------------------
        # SELL
        # ----------------------------------------------------

        if direction == "SELL":

            if not entry_filled:

                if low <= entry <= high:
                    entry_filled = True
                else:
                    continue

            hit_sl = high >= stop_loss
            hit_tp2 = low <= tp2
            hit_tp1 = low <= tp1

            # Conservative rule:
            # If SL and TP happen in the same candle,
            # count the trade as SL.
            if hit_sl:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "SL",
                    "r_multiple": -1.0,
                }

            if hit_tp2:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "TP2",
                    "r_multiple": 1.5,
                }

            if hit_tp1:
                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "TP1",
                    "r_multiple": 0.75,
                }

    return {
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "result": "OPEN",
        "r_multiple": 0.0,
    }


# ============================================================
# SUMMARY
# ============================================================

def print_summary(results):

    print("\n")
    print("=" * 60)
    print("APEX MARKET SIGNALS — BACKTEST SUMMARY")
    print("=" * 60)

    if results.empty:
        print("No completed trades found.")
        return

    total = len(results)

    wins = len(
        results[
            results["result"].isin(
                ["TP1", "TP2"]
            )
        ]
    )

    losses = len(
        results[
            results["result"] == "SL"
        ]
    )

    open_trades = len(
        results[
            results["result"] == "OPEN"
        ]
    )

    win_rate = (
        wins / (wins + losses) * 100
        if (wins + losses) > 0
        else 0
    )

    total_r = results["r_multiple"].sum()

    print(f"Total signals: {total}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Open/unresolved: {open_trades}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Total R: {total_r:.2f}")

    print("\nResults by symbol:")

    for symbol in SYMBOLS:

        symbol_results = results[
            results["symbol"] == symbol
        ]

        if symbol_results.empty:
            print(
                f"{symbol}: No completed trades"
            )
            continue

        symbol_wins = len(
            symbol_results[
                symbol_results["result"].isin(
                    ["TP1", "TP2"]
                )
            ]
        )

        symbol_losses = len(
            symbol_results[
                symbol_results["result"] == "SL"
            ]
        )

        symbol_r = symbol_results[
            "r_multiple"
        ].sum()

        print(
            f"{symbol}: "
            f"{len(symbol_results)} trades | "
            f"{symbol_wins} wins | "
            f"{symbol_losses} losses | "
            f"{symbol_r:.2f}R"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    all_results = []

    for symbol in SYMBOLS:

        try:

            results = backtest_symbol(symbol)

            if not results.empty:
                all_results.append(results)

        except Exception as error:

            print(
                f"ERROR while backtesting "
                f"{symbol}: {error}"
            )

    if all_results:

        combined = pd.concat(
            all_results,
            ignore_index=True,
        )

    else:

        combined = pd.DataFrame()

    print_summary(combined)


if __name__ == "__main__":
    main()
