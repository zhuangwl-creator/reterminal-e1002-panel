# reTerminal E1002 A股看板

为 Seeed reTerminal E1002（7.3" 彩色电子纸，800×480，Spectra 6 六色）做的 A 股信息看板：
上证指数 + 自选股 + 规则化建议 + 天气 + 时钟。**不依赖电脑常开**，云端自动刷新。

## 工作原理

```
GitHub Actions（交易时段定时）          SenseCraft（设备每 15 分钟拉取）
  │ 抓新浪/东财行情 + Open-Meteo 天气          ▲
  │ 生成 data/market.json                       │
  │ 打包 dist/widget.html（内联数据）            │
  └──→ GitHub Pages（公网 HTTPS）──→ HTML Widget ─┘
                                          ↓
                                    reTerminal E1002 显示
```

- 数据更新跑在 GitHub Actions（免费、零电脑依赖），页面托管在 GitHub Pages（稳定 HTTPS）。
- 设备端是 SenseCraft HTML Widget，**按平台固定间隔（建议 15 分钟）自动拉取**页面刷新，不是 Apply 一次就固定。
- 样式严格只用 Spectra 6 的 6 个纯色（黑/白/红/黄/蓝/绿），不用灰/半透明/渐变，避免电子纸抖动模糊。

## 目录结构

```
├── index.html / styles.css / app.js   前端面板（800×480）
├── config/panel.json                  自选股 / 城市 / 刷新间隔
├── scripts/
│   ├── fetch_market.py                抓行情+天气，新浪→东财→缓存 三级容错
│   ├── build_dist.py                  打包 dist/（widget.html 内联数据+北京时间快照）
│   └── refresh_panel.py               fetch + build 的便捷封装
├── data/market.json                   运行时生成（仓库内有一份初始样例做冷启动兜底）
├── data/sample-market.json            兜底数据
└── .github/workflows/refresh.yml      云端定时刷新 + 部署
```

## 本地预览与开发

```bash
# 抓取最新行情天气（会联网，覆写 data/market.json）
python3 scripts/fetch_market.py

# 打包 dist/（生成 widget.html / sensecraft.html / 静态站）
python3 scripts/build_dist.py

# 一键：抓取 + 打包
python3 scripts/refresh_panel.py

# 本地浏览器预览（800×480 面板）
python3 -m http.server 4173
# 打开 http://localhost:4173/        （带设备外壳的预览版）
# 或   http://localhost:4173/dist/widget.html  （设备实际看到的版本）
```

改自选股 / 城市：编辑 `config/panel.json`：
```json
{
  "stocks": ["000598", "000999", "002625", "300467", "600887"],
  "index": "sh000001",
  "refreshMinutes": 15,
  "weather": { "city": "深圳", "latitude": 22.5431, "longitude": 114.0579 }
}
```

## 部署到设备（一次配置）

### 1. 推到 GitHub
```bash
git init && git add -A && git commit -m "init"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

### 2. 开启 GitHub Pages
仓库 **Settings → Pages → Source = Deploy from a branch → `gh-pages` / root**。
等首次 Action 跑完（Actions 标签页看进度），访问：
```
https://<你的用户名>.github.io/<仓库名>/widget.html
```
能看到面板即成功。

### 3. 配置 SenseCraft HTML Widget
1. 打开 https://sensecraft.seeed.cc/hmi ，新建页面，选 E1002 / 800×480。
2. 添加 **HTML Widget**，填上面的 Pages URL。
3. 页面刷新间隔设 **15 分钟**。
4. 预览确认后 **Apply** 推送到设备。

之后设备每 15 分钟自动拉取新页面，云端交易时段每 15 分钟更新数据。

## 数据源与容错

`fetch_market.py` 三级容错：
1. **新浪** `hq.sinajs.cn`（主，gbk + Referer）
2. **东方财富** `push2.eastmoney.com`（备，JSON；价格字段以分为单位 /100；输出前做合理性校验，校验不过则丢弃）
3. **保留上次 market.json**（全失败时不覆盖，设备继续显示上次数据）

天气：Open-Meteo（免费、无需 key）。分时折线 `index.series`：东财 trends2，拿不到则隐藏 sparkline。

> **海外 IP 风险**：GitHub Actions 跑在美国服务器，访问新浪/东财**可能被地域限制**。首次 Action 跑完务必看日志确认数据真的拿到了。若持续拿不到，备选方案是改用国内云（阿里云函数计算 + OSS，把本仓库的 `scripts/` 搬过去用 cron 触发即可）。

## 已知限制

- **SenseCraft 无法精确匹配交易时段**：平台只能设固定刷新间隔，不能"盘后停刷"。收盘后设备仍每 15 分钟拉一次，但数据是收盘快照（云端交易时段外不更新）。
- **GitHub cron 不保证准时**：可能延迟几分钟到几十分钟。
- **电子纸刷新慢**：E1002 全屏刷新约 15–30 秒（6 色全屏闪），15 分钟间隔可接受。
- **电池**：15 分钟刷新一次，续航会从标称 3 个月降到约 2–3 周；长期插电更合适。
- **GitHub Pages 冷启动**：首次部署后等 1–2 分钟 CDN 生效。
- **时区**：时钟由云端用 Asia/Shanghai 生成后内联，不依赖设备时区。

## 致谢

前端原型与数据链路基于 codex 的初版重构，改进了 Spectra 6 六色适配（解决浅色模糊）和云端自动化（去除对本地电脑的依赖）。
