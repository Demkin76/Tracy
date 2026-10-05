"""Public exchange candles with immutable provenance. Never synthesizes missing data."""

import json
import math
import time
from statistics import pstdev

import httpx
from fastapi import HTTPException

from backend.crypto.hashing import digest

SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
MARKETS = {"SOL/USDC": "SOLUSDC", "BTC/USDC": "BTCUSDC", "ETH/USDC": "ETHUSDC"}
ENDPOINT = "https://data-api.binance.vision/api/v3/klines"


class MarketData:
    def __init__(self, db):
        self.db = db

    def _fetch(self, params):
        try:
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = client.get(ENDPOINT, params=params)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503, "Market data unavailable from Binance. Retry later; no substitute prices are used."
            ) from exc

    def window(self, market, timeframe, count=96, start=None):
        if market not in MARKETS or timeframe not in SECONDS or not 1 <= count <= 1000:
            raise HTTPException(422, "Unsupported market, timeframe or candle count")
        step = SECONDS[timeframe]
        closed_until = int(time.time() - 2) // step * step
        start = closed_until - count * step if start is None else start
        if start % step or start < 0 or start + count * step > closed_until:
            raise HTTPException(422, "Choose aligned dates containing only fully closed candles")
        request_key = f"binance:{market}:{timeframe}:{start}:{count}"
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id FROM market_snapshots WHERE request_key=?", (request_key,)
            ).fetchone()
        if row:
            return self.get(row[0])
        raw = self._fetch(
            {
                "symbol": MARKETS[market],
                "interval": timeframe,
                "startTime": start * 1000,
                "endTime": (start + count * step) * 1000 - 1,
                "limit": count,
            }
        )
        bars = self.normalize(raw, start, count, step)
        body = {
            "provider": "Binance Spot",
            "endpoint": ENDPOINT,
            "market": market,
            "symbol": MARKETS[market],
            "timeframe": timeframe,
            "period_start": start,
            "period_end": start + count * step,
            "fetched_at": int(time.time()),
            "source": "binance_spot",
            "synthetic": False,
            "raw_hash": digest(raw),
            "bars": bars,
        }
        return self.save(body, request_key)

    @staticmethod
    def normalize(raw, start, count, step):
        try:
            if not isinstance(raw, list) or len(raw) != count:
                raise ValueError("Missing candles")
            rows, changes = [], []
            previous = None
            for i, item in enumerate(raw):
                if (
                    len(item) < 9
                    or int(item[0]) != (start + i * step) * 1000
                    or int(item[6]) != (start + (i + 1) * step) * 1000 - 1
                ):
                    raise ValueError("Non-contiguous or incomplete candles")
                opened, high, low, close, volume, quote_volume = [float(item[j]) for j in (1, 2, 3, 4, 5, 7)]
                if not all(math.isfinite(n) for n in (opened, high, low, close, volume, quote_volume)):
                    raise ValueError("Non-finite market data")
                if (
                    not 0 < low <= min(opened, close) <= max(opened, close) <= high
                    or volume < 0
                    or quote_volume < 0
                ):
                    raise ValueError("Invalid OHLCV")
                change = close / (previous or opened) - 1
                changes.append(change)
                rows.append(
                    {
                        "timestamp": start + i * step,
                        "close_timestamp": start + (i + 1) * step,
                        "open": opened,
                        "high": high,
                        "low": low,
                        "close": close,
                        "price": close,
                        "volume": quote_volume,
                        "base_volume": volume,
                        "volatility": round(100 * pstdev(changes[-20:]), 4) if i else 0,
                        "trend": "up" if sum(changes[-8:]) > 0 else "down",
                        "source": "binance_spot",
                        "synthetic": False,
                        "bar": i,
                    }
                )
                previous = close
            return rows
        except (ValueError, TypeError, IndexError, OverflowError) as exc:
            raise HTTPException(
                502, "Exchange returned incomplete or invalid candles. Test was not run."
            ) from exc

    def save(self, body, request_key):
        snapshot_id = digest(body)
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO market_snapshots VALUES(?,?,?,?)",
                (snapshot_id, request_key, json.dumps(body), body["fetched_at"]),
            )
            row = conn.execute(
                "SELECT snapshot_id FROM market_snapshots WHERE request_key=?", (request_key,)
            ).fetchone()
        return self.get(row[0])

    def get(self, snapshot_id):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT body FROM market_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(409, "The stored market data snapshot is missing")
        body = json.loads(row[0])
        if digest(body) != snapshot_id:
            raise HTTPException(409, "Market data snapshot integrity check failed")
        return {**body, "snapshot_id": snapshot_id}

    def slice(self, snapshot, offset, count):
        bars = [{**bar, "bar": i} for i, bar in enumerate(snapshot["bars"][offset : offset + count])]
        if len(bars) != count:
            raise HTTPException(409, "Not enough candles in snapshot")
        body = {k: v for k, v in snapshot.items() if k not in ("snapshot_id", "bars")}
        body.update(
            bars=bars,
            period_start=bars[0]["timestamp"],
            period_end=bars[-1]["close_timestamp"],
            parent_snapshot_id=snapshot["snapshot_id"],
        )
        return self.save(body, f"slice:{snapshot['snapshot_id']}:{offset}:{count}")


def provenance(snapshot):
    return {k: v for k, v in snapshot.items() if k != "bars"}
