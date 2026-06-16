#!/usr/bin/env python3
"""抓取 A 股行情 + 天气，输出 data/market.json。

数据源容错链：新浪（主）→ 东方财富（备）→ 保留上次 market.json（兜底）。
分时折线 index.series：东方财富 trends2，拿不到则为空（前端隐藏 sparkline）。

设计要点：
- 新浪解析沿用 codex 已验证的字段映射（gbk + Referer）。
- 东财价格字段以"分"为单位（扩大 100 倍），统一 /100；输出前做合理性校验，
  若东财字段映射假设错误（校验不过）则丢弃，回退缓存，避免输出错误数据。
- 全部数据源失败时保留上次的 market.json 不覆盖，设备继续显示上次数据。
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "panel.json"
OUTPUT_PATH = ROOT / "data" / "market.json"
TZ = ZoneInfo("Asia/Shanghai")

SINA_URL = "https://hq.sinajs.cn/list="
EM_REALTIME_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EM_TRENDS_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ---------- 工具 ----------
def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def market_symbol(code):
    raw = code.strip().lower()
    if raw.startswith(("sh", "sz")):
        return raw
    if raw.startswith(("5", "6", "9")):
        return f"sh{raw}"
    return f"sz{raw}"


def em_secid(symbol):
    """sh000001 → 1.000001；sz000598 → 0.000598（东财 secid：1=沪，0=深）。"""
    market = "1" if symbol.startswith("sh") else "0"
    return f"{market}.{symbol[2:]}"


def display_code(symbol):
    code = symbol[2:]
    suffix = ".SH" if symbol.startswith("sh") else ".SZ"
    return f"{code}{suffix}"


def fetch_text(url, encoding="utf-8", headers=None, timeout=12):
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode(encoding, errors="replace")


def fetch_json(url, headers=None, timeout=12):
    return json.loads(fetch_text(url, headers=headers, timeout=timeout))


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


# ---------- 统一报价构造 ----------
def trend_label(price, open_price, previous_close):
    if price >= previous_close and price >= open_price:
        return "盘中偏强"
    if price < previous_close and price < open_price:
        return "盘中偏弱"
    if price >= previous_close:
        return "红盘震荡"
    return "绿盘震荡"


def build_quote(symbol, name, price, prev_close, open_price, high, low, volume, amount, quote_time):
    """从规范化的标量字段生成最终 quote 字典。新浪/东财共用，避免重复计算。"""
    price = to_float(price)
    prev_close = to_float(prev_close)
    change = price - prev_close
    change_pct = change / prev_close * 100 if prev_close else 0
    return {
        "name": name,
        "code": display_code(symbol),
        "price": round(price, 2),
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "open": round(to_float(open_price), 2),
        "high": round(to_float(high), 2),
        "low": round(to_float(low), 2),
        "volume": int(to_float(volume)),
        "amount": round(to_float(amount), 2),
        "trend": trend_label(price, to_float(open_price), prev_close),
        "risk": "相对强" if change_pct >= 1 else "观察",
        "quoteTime": quote_time,
    }


# ---------- 新浪源（主）----------
def parse_sina_quotes(text):
    quotes = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "hq_str_" not in line:
            continue
        name_start = line.find("hq_str_") + len("hq_str_")
        symbol_end = line.find("=")
        quote_start = line.find('"')
        quote_end = line.rfind('"')
        if symbol_end <= name_start or quote_start < 0 or quote_end <= quote_start:
            continue
        symbol = line[name_start:symbol_end]
        fields = line[quote_start + 1:quote_end].split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        quotes[symbol] = fields
    return quotes


def fetch_sina_all(symbols):
    """返回 {symbol: quote_dict}。任一 symbol 缺失则该 key 不在返回字典里。"""
    headers = {"Referer": "https://finance.sina.com.cn/", "User-Agent": DEFAULT_UA}
    text = fetch_text(f"{SINA_URL}{','.join(symbols)}", encoding="gbk", headers=headers)
    raw = parse_sina_quotes(text)
    result = {}
    for sym in symbols:
        fields = raw.get(sym)
        if fields:
            # fields: 0=名称 1=今开 2=昨收 3=现价 4=最高 5=最低 8=成交量 9=成交额 30=日期 31=时间
            result[sym] = build_quote(
                sym, fields[0], fields[3], fields[2], fields[1], fields[4], fields[5],
                fields[8], fields[9], f"{fields[30]}T{fields[31]}+08:00")
    return result


# ---------- 东方财富源（备）----------
def _em_price(raw):
    """东财价格字段以分为单位（扩大 100 倍），统一除以 100。"""
    return to_float(raw) / 100.0


def fetch_eastmoney_all(symbols):
    headers = {"User-Agent": DEFAULT_UA, "Referer": "https://quote.eastmoney.com/"}
    fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
    result = {}
    for sym in symbols:
        try:
            data = fetch_json(
                f"{EM_REALTIME_URL}?secid={em_secid(sym)}&fields={fields}",
                headers=headers).get("data") or {}
            if data.get("f43") in (None, "", 0):
                continue
            # f43=现价 f44=最高 f45=最低 f46=今开 f47=成交量 f48=成交额 f58=名称 f60=昨收
            result[sym] = build_quote(
                sym, data.get("f58"), _em_price(data["f43"]), _em_price(data.get("f60")),
                _em_price(data.get("f46")), _em_price(data.get("f44")), _em_price(data.get("f45")),
                data.get("f47"), data.get("f48"), now_iso())
        except Exception:
            continue
    return result


def quote_looks_ok(q, is_index):
    """合理性校验：防止东财字段映射假设错误时输出离谱数据。"""
    price = q["price"]
    pct = q["changePct"]
    if not (-12 < pct < 12):
        return False
    if is_index:
        return 200 < price < 50000
    return 0.3 < price < 5000


# ---------- 分时折线（东财 trends2）----------
def fetch_series(symbol, limit=48):
    headers = {"User-Agent": DEFAULT_UA, "Referer": "https://quote.eastmoney.com/"}
    params = {
        "secid": em_secid(symbol),
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ndays": "1",
        "iscr": "0",
    }
    data = fetch_json(f"{EM_TRENDS_URL}?{urlencode(params)}", headers=headers).get("data") or {}
    trends = data.get("trends") or []
    points = []
    for item in trends:
        parts = item.split(",")
        if len(parts) >= 2:
            points.append(round(to_float(parts[1]), 2))
    return points[-limit:] if points else []


# ---------- 行情文案 ----------
def amount_tone(amount):
    if amount <= 0:
        return "成交额待确认"
    return f"成交额约{amount / 100000000:.0f}亿"


def market_trend(index):
    pct = index["changePct"]
    if pct >= 0.6:
        return "指数偏强"
    if pct <= -0.6:
        return "指数偏弱"
    return "窄幅震荡"


# ---------- 天气 ----------
WEATHER_CODES = {
    0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾",
    51: "小雨", 53: "小雨", 55: "中雨", 61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "霰",
    80: "阵雨", 81: "阵雨", 82: "强阵雨", 95: "雷雨", 96: "雷雨", 99: "雷雨",
}


def weather_text(code):
    return WEATHER_CODES.get(int(code), "天气")


def wind_text(degrees):
    dirs = ["北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"]
    return dirs[int((to_float(degrees) + 22.5) // 45) % 8]


def fetch_weather(config):
    weather = config.get("weather", {})
    params = {
        "latitude": weather.get("latitude", 31.2304),
        "longitude": weather.get("longitude", 121.4737),
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
        "timezone": "Asia/Shanghai",
    }
    current = fetch_json(f"{OPEN_METEO_URL}?{urlencode(params)}").get("current", {})
    return {
        "city": weather.get("city", "上海"),
        "condition": weather_text(current.get("weather_code", 0)),
        "temperature": round(to_float(current.get("temperature_2m", 0))),
        "humidity": round(to_float(current.get("relative_humidity_2m", 0))),
        "wind": f"{wind_text(current.get('wind_direction_10m', 0))} "
                f"{to_float(current.get('wind_speed_10m', 0)):.0f}km/h",
    }


def fallback_weather(config):
    weather = config.get("weather", {})
    return {"city": weather.get("city", "上海"), "condition": "天气",
            "temperature": 0, "humidity": 0, "wind": "待更新"}


# ---------- 配置与缓存 ----------
def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_last_market():
    if OUTPUT_PATH.exists():
        try:
            with OUTPUT_PATH.open("r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return None
    return None


# ---------- 美股时段（北京 22:00–次日 09:00）----------
def is_us_window():
    """北京时间 22:00 至次日 09:00 为美股时段。"""
    hour = datetime.now(TZ).hour
    return hour >= 22 or hour < 9


def us_ticker(symbol):
    """gb_aapl → AAPL；gb_$ixic → IXIC（去 gb_ 与 $ 前缀并大写）。"""
    raw = symbol[3:] if symbol.startswith("gb_") else symbol
    return raw.lstrip("$").upper()


def build_us_quote(symbol, name, price, prev_close, open_price, high, low, volume, amount, quote_time):
    """美股报价构造：与 build_quote 相同的 key 集合，code 用原始 ticker（无 .SH/.SZ 后缀）。"""
    price = to_float(price)
    prev_close = to_float(prev_close)
    change = price - prev_close
    change_pct = change / prev_close * 100 if prev_close else 0
    return {
        "name": name,
        "code": us_ticker(symbol),
        "price": round(price, 2),
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "open": round(to_float(open_price), 2),
        "high": round(to_float(high), 2),
        "low": round(to_float(low), 2),
        "volume": int(to_float(volume)),
        "amount": round(to_float(amount), 2),
        "trend": trend_label(price, to_float(open_price), prev_close),
        "risk": "相对强" if change_pct >= 1 else "观察",
        "quoteTime": quote_time,
    }


def quote_looks_ok_us(q, is_index):
    """美股合理性校验：区间比 A 股宽（个股价格上限高，涨跌幅容忍 ±30%）。"""
    pct = q["changePct"]
    if not (-30 < pct < 30):
        return False
    price = q["price"]
    if is_index:
        return 1000 < price < 50000
    return 0.5 < price < 100000


def fetch_sina_us_all(symbols, names):
    """新浪美股（gb_ 前缀，gbk + Referer）。返回 {symbol: quote_dict}。"""
    headers = {"Referer": "https://finance.sina.com.cn/", "User-Agent": DEFAULT_UA}
    text = fetch_text(f"{SINA_URL}{','.join(symbols)}", encoding="gbk", headers=headers)
    raw = parse_sina_quotes(text)
    result = {}
    for sym in symbols:
        fields = raw.get(sym)
        # 美股字段：0=名称 1=现价 2=涨跌幅 4=涨跌额 5=今开 6=最高 7=最低 10=成交量 11=成交额 26=昨收
        if fields and len(fields) >= 27 and fields[1]:
            name = names.get(sym) or fields[0] or us_ticker(sym)
            result[sym] = build_us_quote(
                sym, name, fields[1], fields[26], fields[5], fields[6], fields[7],
                fields[10], fields[11], now_iso())
    return result


def em_us_secid(symbol):
    """美股东财 secid：105=纳斯达克，106=纽交所。"""
    ticker = us_ticker(symbol)
    market = "106" if ticker in {"KO", "SPCX"} else "105"
    return f"{market}.{ticker}"


def fetch_eastmoney_us_all(symbols, names):
    """东财美股（备源）。f43 直接为美元价，不除 100（与 A 股不同）。"""
    headers = {"User-Agent": DEFAULT_UA, "Referer": "https://quote.eastmoney.com/"}
    fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60"
    result = {}
    for sym in symbols:
        try:
            data = fetch_json(
                f"{EM_REALTIME_URL}?secid={em_us_secid(sym)}&fields={fields}&fltt=2",
                headers=headers).get("data") or {}
            if data.get("f43") in (None, "", 0):
                continue
            # f43=现价 f44=最高 f45=最低 f46=今开 f47=成交量 f48=成交额 f58=名称 f60=昨收
            name = names.get(sym) or data.get("f58") or us_ticker(sym)
            result[sym] = build_us_quote(
                sym, name, data["f43"], data.get("f60"), data.get("f46"),
                data.get("f44"), data.get("f45"), data.get("f47"), data.get("f48"), now_iso())
        except Exception:
            continue
    return result


def fetch_series_us(secid="100.NDX", limit=48):
    """美股指数分时折线（东财 trends2，纳斯达克 100.NDX）。失败返回空数组。"""
    headers = {"User-Agent": DEFAULT_UA, "Referer": "https://quote.eastmoney.com/"}
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ndays": "1",
        "iscr": "0",
    }
    data = fetch_json(f"{EM_TRENDS_URL}?{urlencode(params)}", headers=headers).get("data") or {}
    trends = data.get("trends") or []
    points = []
    for item in trends:
        parts = item.split(",")
        if len(parts) >= 2:
            points.append(round(to_float(parts[1]), 2))
    return points[-limit:] if points else []


def fetch_us(config):
    """美股时段主流程：新浪（主）→ 东财（备）→ 保留上次（兜底）。输出与 A 股同结构 payload。"""
    us = config.get("us", {})
    names = us.get("names", {})
    symbols = [us.get("index", "gb_$ixic")]
    symbols.extend(us.get("stocks", []))
    index_symbol = symbols[0]

    quotes = {}
    source = None

    # 主源：新浪美股
    try:
        sina = fetch_sina_us_all(symbols, names)
        if index_symbol in sina and all(s in sina for s in symbols):
            quotes = sina
            source = "Sina Finance 美股 hq.sinajs.cn"
    except Exception as exc:
        print(f"sina us failed: {exc}", file=sys.stderr)

    # 备源：东方财富美股
    if not source:
        try:
            em = fetch_eastmoney_us_all(symbols, names)
            if index_symbol in em and all(s in em for s in symbols):
                if all(quote_looks_ok_us(em[s], s == index_symbol) for s in symbols):
                    quotes = em
                    source = "Eastmoney 美股 push2.eastmoney.com"
                else:
                    print("eastmoney us data failed sanity check", file=sys.stderr)
        except Exception as exc:
            print(f"eastmoney us failed: {exc}", file=sys.stderr)

    # 兜底：全失败则保留上次数据
    if not source:
        last = load_last_market()
        if last:
            print("All US sources failed; keeping last market.json", file=sys.stderr)
            return
        raise RuntimeError("美股行情获取失败且无历史缓存")

    index = quotes[index_symbol]
    index["trend"] = market_trend(index)
    index["volumeTone"] = amount_tone(index["amount"])

    stocks = [quotes[s] for s in symbols[1:]]
    for stock in stocks:
        relative = stock["changePct"] - index["changePct"]
        stock["risk"] = "强于指数" if relative >= 1 else ("弱于指数" if relative <= -1 else "跟随指数")

    # 分时折线：拿不到就空数组（前端隐藏 sparkline）
    try:
        index["series"] = fetch_series_us()
    except Exception as exc:
        print(f"us series failed: {exc}", file=sys.stderr)
        index["series"] = []

    try:
        weather = fetch_weather(config)
    except Exception as exc:
        weather = fallback_weather(config)
        weather["error"] = str(exc)

    payload = {
        "updatedAt": now_iso(),
        "source": {"market": source, "weather": "Open-Meteo"},
        "index": index,
        "stocks": stocks,
        "weather": weather,
        "ui": {"eyebrow": "美股观察"},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Source: {source} | {len(stocks)} stocks | series pts: {len(index.get('series', []))}")


def main():
    config = load_config()
    if is_us_window():
        fetch_us(config)
        return
    symbols = [market_symbol(config.get("index", "sh000001"))]
    symbols.extend(market_symbol(code) for code in config.get("stocks", []))
    index_symbol = symbols[0]

    quotes = {}
    source = None

    # 主源：新浪
    try:
        sina = fetch_sina_all(symbols)
        if index_symbol in sina and all(s in sina for s in symbols):
            quotes = sina
            source = "Sina Finance hq.sinajs.cn"
    except Exception as exc:
        print(f"sina failed: {exc}", file=sys.stderr)

    # 备源：东方财富
    if not source:
        try:
            em = fetch_eastmoney_all(symbols)
            if index_symbol in em and all(s in em for s in symbols):
                if all(quote_looks_ok(em[s], s == index_symbol) for s in symbols):
                    quotes = em
                    source = "Eastmoney push2.eastmoney.com"
                else:
                    print("eastmoney data failed sanity check", file=sys.stderr)
        except Exception as exc:
            print(f"eastmoney failed: {exc}", file=sys.stderr)

    # 兜底：全失败则保留上次数据
    if not source:
        last = load_last_market()
        if last:
            print("All sources failed; keeping last market.json", file=sys.stderr)
            return
        raise RuntimeError("行情获取失败且无历史缓存")

    index = quotes[index_symbol]
    index["trend"] = market_trend(index)
    index["volumeTone"] = amount_tone(index["amount"])

    stocks = [quotes[s] for s in symbols[1:]]
    for stock in stocks:
        relative = stock["changePct"] - index["changePct"]
        stock["risk"] = "强于指数" if relative >= 1 else ("弱于指数" if relative <= -1 else "跟随指数")

    # 分时折线：拿不到就空数组（前端隐藏 sparkline）
    try:
        index["series"] = fetch_series(index_symbol)
    except Exception as exc:
        print(f"series failed: {exc}", file=sys.stderr)
        index["series"] = []

    try:
        weather = fetch_weather(config)
    except Exception as exc:
        weather = fallback_weather(config)
        weather["error"] = str(exc)

    payload = {
        "updatedAt": now_iso(),
        "source": {"market": source, "weather": "Open-Meteo"},
        "index": index,
        "stocks": stocks,
        "weather": weather,
        "ui": {"eyebrow": "A股观察"},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Source: {source} | {len(stocks)} stocks | series pts: {len(index.get('series', []))}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"fetch_market.py failed: {exc}", file=sys.stderr)
        raise
