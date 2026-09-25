import os
import requests
import pandas as pd

from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange


# ============================================================
# APEX MARKET SIGNALS — REALISTIC BACKTEST
# ============================================================
#
# Strategy:
# Trend Following Pullback
#
# Timeframe:
# 4H
#
# Indicators:
# EMA 50
# EMA 200
# ATR 14
# ADX 14
#
# Trade management:
# 50% at TP1
# 50% at TP2
# Move remaining SL to breakeven after TP1
#
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

    for column in [
        "open",
        "high",
        "low",
        "close",
    ]:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    df = df.sort_values("datetime")
    df = df.reset_index(drop=True)

    return df


# ============================================================
# ADD INDICATORS
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
    tp1_hit = False

    # --------------------------------------------------------
    # BEFORE TP1
    # --------------------------------------------------------

    for j in range(
        start_index,
        len(df),
    ):

        candle = df.iloc[j]

        high = float(candle["high"])
        low = float(candle["low"])

        # ====================================================
        # BUY
        # ====================================================

        if direction == "BUY":

            # -----------------------------------------------
            # Wait for limit entry
            # -----------------------------------------------

            if not entry_filled:

                if low <= entry <= high:
                    entry_filled = True
                else:
                    continue

            # -----------------------------------------------
            # Entry has been filled
            #
            # Conservative rule:
            # If SL and TP1 are both touched in the same
            # candle before TP1 was previously confirmed,
            # assume SL happened first.
            # -----------------------------------------------

            hit_sl = low <= stop_loss
            hit_tp1 = high >= tp1

            if hit_sl and hit_tp1:

                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "SL",
                    "r_multiple": -1.0,
                }

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

            if hit_tp1:

                tp1_hit = True

                # 50% closes at TP1.
                # 0.5 x 0.75R = +0.375R

                tp1_profit = 0.375

                # Continue with the remaining 50%.
                #
                # Its new stop is breakeven = entry.
                #
                for k in range(
                    j + 1,
                    len(df),
                ):

                    next_candle = df.iloc[k]

                    next_high = float(
                        next_candle["high"]
                    )

                    next_low = float(
                        next_candle["low"]
                    )

                    hit_breakeven = (
                        next_low <= entry
                    )

                    hit_tp2 = (
                        next_high >= tp2
                    )

                    # Conservative rule:
                    # If both TP2 and breakeven are touched
                    # in the same candle, assume breakeven
                    # happened first.
                    if hit_breakeven and hit_tp2:

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP1_BE",
                            "r_multiple": tp1_profit,
                        }

                    if hit_breakeven:

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP1_BE",
                            "r_multiple": tp1_profit,
                        }

                    if hit_tp2:

                        # Remaining 50% gets 1.5R.
                        # 0.5 x 1.5R = +0.75R
                        #
                        # Total:
                        # +0.375R + 0.75R = +1.125R

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP2",
                            "r_multiple": 1.125,
                        }

                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "OPEN",
                    "r_multiple": tp1_profit,
                }

        # ====================================================
        # SELL
        # ====================================================

        if direction == "SELL":

            # -----------------------------------------------
            # Wait for limit entry
            # -----------------------------------------------

            if not entry_filled:

                if low <= entry <= high:
                    entry_filled = True
                else:
                    continue

            # -----------------------------------------------
            # Entry has been filled
            # -----------------------------------------------

            hit_sl = high >= stop_loss
            hit_tp1 = low <= tp1

            # Conservative rule:
            # If SL and TP1 occur in the same candle,
            # assume SL happened first.
            if hit_sl and hit_tp1:

                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "SL",
                    "r_multiple": -1.0,
                }

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

            if hit_tp1:

                tp1_hit = True

                # 50% closes at TP1.
                # +0.375R

                tp1_profit = 0.375

                # Remaining 50%:
                # Stop moves to breakeven.

                for k in range(
                    j + 1,
                    len(df),
                ):

                    next_candle = df.iloc[k]

                    next_high = float(
                        next_candle["high"]
                    )

                    next_low = float(
                        next_candle["low"]
                    )

                    hit_breakeven = (
                        next_high >= entry
                    )

                    hit_tp2 = (
                        next_low <= tp2
                    )

                    # Conservative rule:
                    # If TP2 and breakeven happen in the
                    # same candle, assume breakeven first.
                    if hit_breakeven and hit_tp2:

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP1_BE",
                            "r_multiple": tp1_profit,
                        }

                    if hit_breakeven:

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP1_BE",
                            "r_multiple": tp1_profit,
                        }

                    if hit_tp2:

                        return {
                            "direction": direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "tp1": tp1,
                            "tp2": tp2,
                            "result": "TP2",
                            "r_multiple": 1.125,
                        }

                return {
                    "direction": direction,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "result": "OPEN",
                    "r_multiple": tp1_profit,
                }

    # No outcome before historical data ended.
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
# BACKTEST ONE SYMBOL
# ============================================================

def backtest_symbol(symbol):

    print("\n" + "=" * 60)
    print(f"BACKTESTING {symbol}")
    print("=" * 60)

    df = get_historical_data(symbol)

    df = add_indicators(df)

    trades = []

    # Need enough history for EMA200.
    for i in range(
        201,
        len(df) - 1,
    ):

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

        # ====================================================
        # BUY LIMIT SETUP
        # ====================================================

        buy_setup = (
            ema50 > ema200
            and adx > 20
            and previous["close"] > ema50
            and current["low"] <= ema50
        )

        if buy_setup:

            entry = ema50

            stop_loss = (
                entry - (2 * atr)
            )

            tp1 = (
                entry + (1.5 * atr)
            )

            tp2 = (
                entry + (3 * atr)
            )

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

                result["signal_time"] = (
                    current["datetime"]
                )

                trades.append(result)

        # ====================================================
        # SELL LIMIT SETUP
        # ====================================================

        sell_setup = (
            ema50 < ema200
            and adx > 20
            and previous["close"] < ema50
            and current["high"] >= ema50
        )

        if sell_setup:

            entry = ema50

            stop_loss = (
                entry + (2 * atr)
            )

            tp1 = (
                entry - (1.5 * atr)
            )

            tp2 = (
                entry - (3 * atr)
            )

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

                result["signal_time"] = (
                    current["datetime"]
                )

                trades.append(result)

    return pd.DataFrame(trades)


# ============================================================
# SUMMARY
# ============================================================

def print_summary(results):

    print("\n")
    print("=" * 60)
    print("APEX MARKET SIGNALS — REALISTIC BACKTEST")
    print("=" * 60)

    if results.empty:

        print("No completed trades found.")

        return

    total = len(results)

    full_losses = len(
        results[
            results["result"] == "SL"
        ]
    )

    tp2_wins = len(
        results[
            results["result"] == "TP2"
        ]
    )

    tp1_breakeven = len(
        results[
            results["result"] == "TP1_BE"
        ]
    )

    open_trades = len(
        results[
            results["result"] == "OPEN"
        ]
    )

    profitable_trades = (
        tp2_wins + tp1_breakeven
    )

    resolved_trades = (
        total - open_trades
    )

    win_rate = (
        profitable_trades
        / resolved_trades
        * 100
        if resolved_trades > 0
        else 0
    )

    total_r = results[
        "r_multiple"
    ].sum()

    average_r = (
        total_r / resolved_trades
        if resolved_trades > 0
        else 0
    )

    print(
        f"Total trade signals: {total}"
    )

    print(
        f"TP2 wins: {tp2_wins}"
    )

    print(
        f"TP1 + breakeven: "
        f"{tp1_breakeven}"
    )

    print(
        f"Full SL losses: "
        f"{full_losses}"
    )

    print(
        f"Open/unresolved: "
        f"{open_trades}"
    )

    print(
        f"Resolved win rate: "
        f"{win_rate:.2f}%"
    )

    print(
        f"Total R: "
        f"{total_r:.2f}R"
    )

    print(
        f"Average R per resolved trade: "
        f"{average_r:.3f}R"
    )

    print("\nResults by symbol:")

    for symbol in SYMBOLS:

        symbol_results = results[
            results["symbol"] == symbol
        ]

        if symbol_results.empty:

            print(
                f"{symbol}: "
                f"No completed trades"
            )

            continue

        symbol_tp2 = len(
            symbol_results[
                symbol_results["result"]
                == "TP2"
            ]
        )

        symbol_tp1_be = len(
            symbol_results[
                symbol_results["result"]
                == "TP1_BE"
            ]
        )

        symbol_sl = len(
            symbol_results[
                symbol_results["result"]
                == "SL"
            ]
        )

        symbol_open = len(
            symbol_results[
                symbol_results["result"]
                == "OPEN"
            ]
        )

        symbol_r = symbol_results[
            "r_multiple"
        ].sum()

        print(
            f"{symbol}: "
            f"{len(symbol_results)} trades | "
            f"TP2: {symbol_tp2} | "
            f"TP1+BE: {symbol_tp1_be} | "
            f"SL: {symbol_sl} | "
            f"Open: {symbol_open} | "
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

            results = backtest_symbol(
                symbol
            )

            if not results.empty:

                all_results.append(
                    results
                )

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
