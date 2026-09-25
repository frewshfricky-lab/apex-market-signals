import os
import requests
import pandas as pd

from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange


# ============================================================
# APEX MARKET SIGNALS
# Trend Following Pullback Strategy
# Timeframe: 4H
# ============================================================

# ------------------------------------------------------------
# MOCK HISTORICAL DATAFRAME
# ------------------------------------------------------------

mock_data = pd.DataFrame(
    {
        "open": [100, 101, 102, 103, 104],
        "high": [102, 103, 104, 105, 106],
        "low": [99, 100, 101, 102, 103],
        "close": [101, 102, 103, 104, 105],
    }
)


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

TIMEFRAME = "4h"

SYMBOLS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "BTC/USD",
]

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ------------------------------------------------------------
# CHECK ENVIRONMENT VARIABLES
# ------------------------------------------------------------

def check_environment():
    missing = []

    if not TWELVE_DATA_API_KEY:
        missing.append("TWELVE_DATA_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        raise RuntimeError(
            "Missing GitHub Secrets: " + ", ".join(missing)
        )


# ------------------------------------------------------------
# GET MARKET DATA FROM TWELVE DATA
# ------------------------------------------------------------

def get_market_data(symbol):
    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "outputsize": 300,
        "order": "asc",
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY,
    }

    response = requests.get(
        TWELVE_DATA_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") == "error":
        message = data.get("message", "Unknown Twelve Data error")
        raise RuntimeError(
            f"Twelve Data error for {symbol}: {message}"
        )

    if "values" not in data:
        raise RuntimeError(
            f"No market data returned for {symbol}."
        )

    df = pd.DataFrame(data["values"])

    required_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
    ]

    for column in required_columns:
        if column not in df.columns:
            raise RuntimeError(
                f"Missing column '{column}' for {symbol}."
            )

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


# ------------------------------------------------------------
# KEEP ONLY CLOSED 4H CANDLES
# ------------------------------------------------------------

def get_closed_candles(df):
    if df.empty:
        return df

    now = pd.Timestamp.now(tz="UTC")

    current_4h_start = now.floor("4h")

    last_closed_start = current_4h_start - pd.Timedelta(
        hours=4
    )

    df = df[
        df["datetime"] <= last_closed_start
    ].copy()

    df = df.reset_index(drop=True)

    return df


# ------------------------------------------------------------
# CALCULATE INDICATORS
# ------------------------------------------------------------

def calculate_indicators(df):
    df = df.copy()

    ema50 = EMAIndicator(
        close=df["close"],
        window=50,
    )

    ema200 = EMAIndicator(
        close=df["close"],
        window=200,
    )

    atr = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    )

    adx = ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    )

    df["ema50"] = ema50.ema_indicator()
    df["ema200"] = ema200.ema_indicator()
    df["atr"] = atr.average_true_range()
    df["adx"] = adx.adx()

    return df


# ------------------------------------------------------------
# ROUND PRICE
# ------------------------------------------------------------

def format_price(symbol, price):
    if "JPY" in symbol:
        return f"{price:.3f}"

    if "BTC" in symbol:
        return f"{price:.2f}"

    return f"{price:.5f}"


# ------------------------------------------------------------
# ANALYZE ONE SYMBOL
# ------------------------------------------------------------

def analyze_symbol(symbol):
    print(f"\nAnalyzing {symbol}...")

    df = get_market_data(symbol)

    df = get_closed_candles(df)

    if len(df) < 210:
        print(
            f"{symbol}: Not enough closed candles. "
            f"Only {len(df)} available."
        )
        return None

    df = calculate_indicators(df)

    previous = df.iloc[-2]
    current = df.iloc[-1]

    # Make sure indicators exist
    required_values = [
        current["ema50"],
        current["ema200"],
        current["atr"],
        current["adx"],
        previous["close"],
    ]

    if any(pd.isna(value) for value in required_values):
        print(f"{symbol}: Indicator data unavailable.")
        return None

    ema50 = float(current["ema50"])
    ema200 = float(current["ema200"])
    atr = float(current["atr"])
    adx = float(current["adx"])

    previous_close = float(previous["close"])

    current_high = float(current["high"])
    current_low = float(current["low"])

    # --------------------------------------------------------
    # BUY LIMIT
    # --------------------------------------------------------

    buy_condition = (
        ema50 > ema200
        and adx > 20
        and previous_close > ema50
        and current_low <= ema50
    )

    if buy_condition:
        entry = ema50
        stop_loss = entry - (2 * atr)
        tp1 = entry + (1.5 * atr)
        tp2 = entry + (3 * atr)

        print(f"{symbol}: BUY LIMIT setup found.")

        return {
            "symbol": symbol,
            "direction": "BUY LIMIT",
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "candle_time": current["datetime"].isoformat(),
        }

    # --------------------------------------------------------
    # SELL LIMIT
    # --------------------------------------------------------

    sell_condition = (
        ema50 < ema200
        and adx > 20
        and previous_close < ema50
        and current_high >= ema50
    )

    if sell_condition:
        entry = ema50
        stop_loss = entry + (2 * atr)
        tp1 = entry - (1.5 * atr)
        tp2 = entry - (3 * atr)

        print(f"{symbol}: SELL LIMIT setup found.")

        return {
            "symbol": symbol,
            "direction": "SELL LIMIT",
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "candle_time": current["datetime"].isoformat(),
        }

    print(f"{symbol}: No valid setup.")

    return None


# ------------------------------------------------------------
# CREATE TELEGRAM MESSAGE
# ------------------------------------------------------------

def create_message(signal):
    symbol = signal["symbol"]

    entry = format_price(
        symbol,
        signal["entry"],
    )

    stop_loss = format_price(
        symbol,
        signal["stop_loss"],
    )

    tp1 = format_price(
        symbol,
        signal["tp1"],
    )

    tp2 = format_price(
        symbol,
        signal["tp2"],
    )

    message = (
        "🚨 *NEW FOREX SIGNAL* 🚨\n\n"
        f"Symbol: {symbol}\n"
        f"Direction: {signal['direction']}\n"
        f"Entry Zone: {entry}\n"
        f"Stop Loss: {stop_loss}\n"
        f"Take Profit 1: {tp1}\n"
        f"Take Profit 2: {tp2}"
    )

    return message


# ------------------------------------------------------------
# SEND TELEGRAM MESSAGE
# ------------------------------------------------------------

def send_telegram(message):
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    response = requests.post(
        url,
        data=payload,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram error: {result}"
        )

    print("Telegram message sent successfully.")


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    print("=" * 60)
    print("APEX MARKET SIGNALS")
    print("Trend Following Pullback Strategy")
    print("Timeframe: 4H")
    print("=" * 60)

    check_environment()

    signals_found = 0

    for symbol in SYMBOLS:
        try:
            signal = analyze_symbol(symbol)

            if signal:
                message = create_message(signal)

                print("\n" + message)

                send_telegram(message)

                signals_found += 1

        except Exception as error:
            print(
                f"ERROR while processing {symbol}: "
                f"{error}"
            )

    print("\n" + "=" * 60)
    print(
        f"Scan complete. Signals found: "
        f"{signals_found}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
