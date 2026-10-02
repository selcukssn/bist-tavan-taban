"""Yahoo Finance'ten tüm BIST hisselerinin günlük kapanışlarını çekip data/bist.json'a yazar.

Hisse listesi Yahoo'nun ekran (screener) API'sinden (borsa = IST) alınır; önceki
çalıştırmalarda görülen ve data/tickers.txt içindeki semboller de eklenir, böylece
screener geçici olarak eksik dönerse liste küçülmez.
"""
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import yfinance as yf
from yfinance import EquityQuery

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "bist.json")
SEED = os.path.join(ROOT, "data", "tickers.txt")
BATCH = 80


def screen_all():
    """Yahoo screener'dan IST borsasındaki tüm hisseleri sayfa sayfa çeker."""
    found = {}
    q = EquityQuery("eq", ["exchange", "IST"])
    offset = 0
    while True:
        res = None
        for attempt in range(3):
            try:
                res = yf.screen(q, offset=offset, size=250, sortField="ticker", sortAsc=True)
                break
            except Exception as e:  # ağ / rate limit
                print(f"screen offset={offset} deneme {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        if not res:
            break
        quotes = res.get("quotes") or []
        for qt in quotes:
            sym = qt.get("symbol") or ""
            if not sym.endswith(".IS"):
                continue
            found[sym[:-3]] = qt.get("longName") or qt.get("shortName") or ""
        total = res.get("total") or 0
        offset += len(quotes)
        if not quotes or offset >= total:
            break
    print(f"screener: {len(found)} hisse", file=sys.stderr)
    return found


def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return {r["s"]: r for r in json.load(f).get("rows", [])}
    except (OSError, ValueError):
        return {}


def load_seed():
    try:
        with open(SEED, encoding="utf-8") as f:
            return [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def fetch_closes(symbols):
    out = {}
    for i in range(0, len(symbols), BATCH):
        chunk = symbols[i:i + BATCH]
        yahoo = [s + ".IS" for s in chunk]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(yahoo, period="15d", interval="1d", auto_adjust=False,
                                 group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:
                print(f"download {i}: {e}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        if df is None or df.empty:
            continue
        for s, y in zip(chunk, yahoo):
            try:
                close = df[y]["Close"].dropna()
            except KeyError:
                continue
            if close.empty:
                continue
            c = float(close.iloc[-1])
            pc = float(close.iloc[-2]) if len(close) > 1 else None
            if not math.isfinite(c) or c <= 0:
                continue
            out[s] = {
                "c": round(c, 2),
                "pc": round(pc, 2) if pc and math.isfinite(pc) else None,
                "d": close.index[-1].strftime("%Y-%m-%d"),
            }
        print(f"{min(i + BATCH, len(symbols))}/{len(symbols)}", file=sys.stderr)
    return out


def main():
    prev = load_previous()
    names = screen_all()
    symbols = set(names) | set(prev) | set(load_seed())
    symbols = sorted(s for s in symbols if s)
    if not symbols:
        sys.exit("hisse listesi boş")

    closes = fetch_closes(symbols)
    if len(closes) < max(50, len(prev) // 2):
        sys.exit(f"çok az veri geldi ({len(closes)}), dosya güncellenmedi")

    rows = []
    for s in symbols:
        if s not in closes:
            continue
        name = names.get(s) or prev.get(s, {}).get("n", "")
        rows.append({"s": s, "n": name, **closes[s]})

    data = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance",
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"{len(rows)} hisse yazıldı -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
