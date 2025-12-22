"""Market data fetching using ccxt."""

import numpy as np
import ccxt.async_support as ccxt

from moneymaker.config import Exchange, Settings


class MarketDataFetcher:
    """
    Fetches market data from exchanges via ccxt.

    Provides:
    - Trading universe (top N coins by volume)
    - OHLCV data with technical indicators
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._exchange: ccxt.Exchange | None = None

    async def _get_exchange(self) -> ccxt.Exchange:
        """Get or create exchange instance (unauthenticated for public data)."""
        if self._exchange is not None:
            return self._exchange

        exchange_classes = {
            Exchange.COINBASE: ccxt.coinbase,
            Exchange.BINANCE: ccxt.binance,
            Exchange.BINANCEUS: ccxt.binanceus,
            Exchange.KRAKEN: ccxt.kraken,
        }

        exchange_class = exchange_classes[self.settings.preferred_exchange]

        self._exchange = exchange_class({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        return self._exchange

    async def get_universe(self, limit: int = 50) -> list[dict]:
        """
        Get top coins by 24h volume.

        Returns list of dicts with:
        - symbol: Trading pair (e.g., "BTC/USDT")
        - price: Current price
        - change_24h: 24h percent change
        - volume_24h: 24h trading volume in USDT
        - rsi: 14-period RSI
        - macd_signal: "bullish", "bearish", or "neutral"
        - volume_ratio: Current volume vs 20-day average
        """
        exchange = await self._get_exchange()
        base = self.settings.base_currency

        try:
            # Fetch all tickers
            tickers = await exchange.fetch_tickers()

            # Filter to base currency pairs and sort by volume
            universe = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith(f"/{base}"):
                    continue

                # Skip stablecoins
                coin = symbol.split("/")[0]
                if coin in ["USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP"]:
                    continue

                volume = ticker.get("quoteVolume") or 0
                if volume < 100000:  # Minimum volume filter
                    continue

                universe.append({
                    "symbol": symbol,
                    "price": ticker.get("last", 0),
                    "change_24h": ticker.get("percentage", 0) or 0,
                    "volume_24h": volume,
                    "high_24h": ticker.get("high", 0),
                    "low_24h": ticker.get("low", 0),
                })

            # Sort by volume and take top N
            universe.sort(key=lambda x: x["volume_24h"], reverse=True)
            universe = universe[:limit]

            # Enrich with technical indicators
            enriched = []
            for coin in universe:
                try:
                    indicators = await self._get_indicators(coin["symbol"])
                    coin.update(indicators)
                except Exception as e:
                    # Default values if indicators fail
                    coin.update({
                        "rsi": 50,
                        "macd_signal": "neutral",
                        "volume_ratio": 1.0,
                    })
                enriched.append(coin)

            return enriched

        except Exception as e:
            print(f"Error fetching universe: {e}")
            return []

    async def _get_indicators(self, symbol: str) -> dict:
        """Calculate technical indicators for a symbol."""
        exchange = await self._get_exchange()

        try:
            # Fetch OHLCV data (1h candles, last 100)
            ohlcv = await exchange.fetch_ohlcv(symbol, "1h", limit=100)

            if len(ohlcv) < 20:
                return {"rsi": 50, "macd_signal": "neutral", "volume_ratio": 1.0, "change_2h": 0, "change_4h": 0}

            closes = np.array([c[4] for c in ohlcv])
            volumes = np.array([c[5] for c in ohlcv])

            # Calculate short-term price changes
            current_price = closes[-1]
            change_2h = ((current_price - closes[-3]) / closes[-3] * 100) if len(closes) >= 3 else 0
            change_4h = ((current_price - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else 0

            # RSI (14-period)
            rsi = self._calculate_rsi(closes, 14)

            # MACD signal
            macd_signal = self._calculate_macd_signal(closes)

            # Volume ratio (current vs 20-day average)
            avg_volume = np.mean(volumes[-20:])
            current_volume = volumes[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

            return {
                "rsi": rsi,
                "macd_signal": macd_signal,
                "volume_ratio": round(volume_ratio, 2),
                "change_2h": round(change_2h, 2),
                "change_4h": round(change_4h, 2),
            }

        except Exception as e:
            print(f"Error getting indicators for {symbol}: {e}")
            return {"rsi": 50, "macd_signal": "neutral", "volume_ratio": 1.0, "change_2h": 0, "change_4h": 0}

    def _calculate_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        """Calculate RSI."""
        if len(closes) < period + 1:
            return 50

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return round(rsi, 1)

    def _calculate_macd_signal(self, closes: np.ndarray) -> str:
        """Calculate MACD signal (bullish/bearish/neutral)."""
        if len(closes) < 26:
            return "neutral"

        # Calculate EMA series for MACD
        ema_12 = self._ema_series(closes, 12)
        ema_26 = self._ema_series(closes, 26)

        macd_line = ema_12 - ema_26
        signal_line = self._ema_series(macd_line, 9)

        current_macd = macd_line[-1]
        current_signal = signal_line[-1]

        if current_macd > current_signal and current_macd > 0:
            return "bullish"
        elif current_macd < current_signal and current_macd < 0:
            return "bearish"
        return "neutral"

    def _ema_series(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA series (returns array)."""
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        return ema

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA."""
        if len(data) < period:
            return float(np.mean(data))

        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    async def close(self):
        """Close the exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
