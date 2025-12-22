"""Sentiment data fetching."""

import httpx

from moneymaker.config import Settings


class SentimentFetcher:
    """
    Fetches market sentiment data.

    Currently supports:
    - Fear & Greed Index (alternative.me API)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def get_fear_greed_index(self) -> dict:
        """
        Fetch the current Fear & Greed Index.

        Returns dict with:
        - value: Numeric value (0-100)
        - classification: Human-readable classification
        - timestamp: When the data was updated
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "https://api.alternative.me/fng/",
                params={"limit": 1, "format": "json"},
            )
            response.raise_for_status()

            data = response.json()

            if data.get("data") and len(data["data"]) > 0:
                fng = data["data"][0]
                return {
                    "value": int(fng.get("value", 50)),
                    "classification": fng.get("value_classification", "Neutral"),
                    "timestamp": fng.get("timestamp"),
                }

        except Exception as e:
            print(f"Error fetching Fear & Greed Index: {e}")

        # Default fallback
        return {
            "value": 50,
            "classification": "Neutral",
            "timestamp": None,
        }

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
