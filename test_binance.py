#!/usr/bin/env python3
"""Test Binance API keys - no external dependencies."""

import hashlib
import hmac
import time
import urllib.request
import urllib.parse
import json
import os

# Get keys from environment or hardcode for testing
API_KEY = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.us"


def sign(params: dict, secret: str) -> str:
    """Create HMAC SHA256 signature."""
    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        secret.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return signature


def test_public_api():
    """Test public endpoint (no auth needed)."""
    print("\n1. Testing public API (BTC price)...")
    try:
        url = f"{BASE_URL}/api/v3/ticker/price?symbol=BTCUSDT"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"   ✓ BTC/USDT price: ${float(data['price']):,.2f}")
            return True
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False


def test_account_access():
    """Test account endpoint (requires valid key + signature)."""
    print("\n2. Testing account access (requires API key)...")

    if not API_KEY or not API_SECRET:
        print("   ✗ API_KEY or API_SECRET not set")
        print("   Run with: BINANCE_API_KEY=xxx BINANCE_API_SECRET=yyy python test_binance.py")
        return False

    print(f"   Using key: {API_KEY[:8]}...")

    try:
        params = {
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        params["signature"] = sign(params, API_SECRET)

        url = f"{BASE_URL}/api/v3/account?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("X-MBX-APIKEY", API_KEY)

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

            # Find USDT balance
            usdt = next((b for b in data["balances"] if b["asset"] == "USDT"), None)
            usdt_free = float(usdt["free"]) if usdt else 0

            print(f"   ✓ Account access OK!")
            print(f"   ✓ USDT balance: ${usdt_free:.2f}")
            print(f"   ✓ Can trade: {data.get('canTrade', False)}")
            print(f"   ✓ Can deposit: {data.get('canDeposit', False)}")
            print(f"   ✓ Can withdraw: {data.get('canWithdraw', False)}")
            return True

    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"   ✗ HTTP {e.code}: {body}")

        if "Invalid API-key" in body:
            print("   → API key is invalid or doesn't exist")
        elif "Signature" in body:
            print("   → API secret is wrong")
        elif "IP" in body:
            print("   → IP not whitelisted")
        return False
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False


def test_open_orders():
    """Test fetching open orders (requires spot trading permission)."""
    print("\n3. Testing spot trading permission...")

    if not API_KEY or not API_SECRET:
        print("   ✗ Skipped (no keys)")
        return False

    try:
        params = {
            "symbol": "BTCUSDT",
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        params["signature"] = sign(params, API_SECRET)

        url = f"{BASE_URL}/api/v3/openOrders?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("X-MBX-APIKEY", API_KEY)

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"   ✓ Spot trading enabled!")
            print(f"   ✓ Open orders: {len(data)}")
            return True

    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"   ✗ HTTP {e.code}: {body}")
        if "-2015" in body:
            print("   → Spot trading NOT enabled on this API key")
        return False
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Binance API Key Tester")
    print("=" * 50)

    results = []
    results.append(("Public API", test_public_api()))
    results.append(("Account Access", test_account_access()))
    results.append(("Spot Trading", test_open_orders()))

    print("\n" + "=" * 50)
    print("Summary:")
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    print("=" * 50)
    if all_passed:
        print("🚀 All tests passed! Ready for live trading.")
    else:
        print("⚠️  Some tests failed. Check the errors above.")
