#!/usr/bin/env python3
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DATA_DIR = DIST / "data"
TZ = ZoneInfo("Asia/Shanghai")

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def read_text(path):
    return path.read_text(encoding="utf-8")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def clock_snapshot():
    """服务端生成北京时间快照。前端直接显示，不依赖设备时区或 JS 跑时钟。"""
    now = datetime.now(TZ)
    return {
        "clockText": now.strftime("%H:%M"),
        "dateText": f"{now.month}月{now.day}日 {WEEKDAYS[now.weekday()]}",
    }


def load_market_with_clock():
    market = json.loads(read_text(ROOT / "data" / "market.json"))
    market["clock"] = clock_snapshot()
    return market


def build_static_site():
    DIST.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    for name in ("index.html", "styles.css", "app.js"):
        shutil.copy2(ROOT / name, DIST / name)

    shutil.copy2(ROOT / "data" / "market.json", DATA_DIR / "market.json")
    shutil.copy2(ROOT / "data" / "sample-market.json", DATA_DIR / "sample-market.json")


def build_single_file():
    html = read_text(ROOT / "index.html")
    css = read_text(ROOT / "styles.css")
    js = read_text(ROOT / "app.js")
    market = load_market_with_clock()

    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.PANEL_DATA = {json.dumps(market, ensure_ascii=False)};</script>\n<script>\n{js}\n</script>",
    )
    write_text(DIST / "sensecraft.html", html)


def build_widget_file():
    html = read_text(ROOT / "index.html")
    css = read_text(ROOT / "styles.css")
    js = read_text(ROOT / "app.js")
    market = load_market_with_clock()
    widget_css = """
html,
body {
  width: 800px;
  height: 480px;
  min-width: 800px;
  min-height: 480px;
  max-width: 800px;
  max-height: 480px;
  margin: 0;
  overflow: hidden;
  display: block;
  background: var(--white);
}

.device-shell {
  width: 800px;
  height: 480px;
  display: block;
  background: transparent;
  border: 0;
}

.panel {
  border: 0;
}
"""

    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n{widget_css}\n</style>")
    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.PANEL_DATA = {json.dumps(market, ensure_ascii=False)};</script>\n<script>\n{js}\n</script>",
    )
    write_text(DIST / "widget.html", html)


def main():
    build_static_site()
    build_single_file()
    build_widget_file()
    print(f"Wrote {DIST}")
    print("Widget URL after hosting: https://<user>.github.io/<repo>/widget.html")


if __name__ == "__main__":
    main()
