"""Configuration management for the trading bot."""

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Exchange(str, Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    BINANCEUS = "binanceus"
    KRAKEN = "kraken"


class Settings(BaseSettings):
    """Main configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude API
    anthropic_api_key: str = Field(default="")

    # Exchange credentials
    coinbase_api_key: str = Field(default="")
    coinbase_api_secret: str = Field(default="")
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")
    kraken_api_key: str = Field(default="")
    kraken_api_secret: str = Field(default="")

    # Trading configuration
    trading_mode: TradingMode = Field(default=TradingMode.LIVE)
    initial_capital: float = Field(default=250.0)

    @field_validator("trading_mode", mode="before")
    @classmethod
    def parse_trading_mode(cls, v):
        if isinstance(v, str):
            v = v.lower().strip()
            if v == "live":
                return TradingMode.LIVE
            elif v == "paper":
                return TradingMode.PAPER
        return v

    base_currency: str = Field(default="USDT")
    preferred_exchange: Exchange = Field(default=Exchange.BINANCEUS)

    # Loop and trading settings
    loop_interval_minutes: int = Field(default=120)  # Every 2 hours
    min_trade_size_usd: float = Field(default=10.0)  # Binance minimum
    max_position_pct: float = Field(default=0.80)  # Max 80% in single position (aggressive)
    min_cash_pct: float = Field(default=0.05)  # Minimum 5% cash reserve
    universe_size: int = Field(default=50)  # Top N coins by volume

    # Paths - use absolute path for Railway volume persistence
    data_dir: Path = Field(default=Path("/app/data"))
    db_path: Path = Field(default=Path("/app/data/moneymaker.db"))

    def get_exchange_credentials(self, exchange: Exchange) -> tuple[str, str]:
        """Get API credentials for a specific exchange."""
        match exchange:
            case Exchange.COINBASE:
                return self.coinbase_api_key, self.coinbase_api_secret
            case Exchange.BINANCE | Exchange.BINANCEUS:
                return self.binance_api_key, self.binance_api_secret
            case Exchange.KRAKEN:
                return self.kraken_api_key, self.kraken_api_secret
            case _:
                return "", ""


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
