const state = {
  market: null,
};

const fallbackData = {
  updatedAt: "2026-06-16T00:03:05+08:00",
  index: {
    name: "上证指数",
    code: "000001.SH",
    price: 4096.47,
    change: 64.96,
    changePct: 1.61,
    volumeTone: "成交额约14036亿",
    trend: "指数偏强",
  },
  stocks: [
    { name: "兴蓉环境", code: "000598.SZ", price: 6.99, changePct: -0.57, trend: "盘中偏弱", risk: "弱于指数" },
    { name: "华润三九", code: "000999.SZ", price: 24.55, changePct: -1.21, trend: "盘中偏弱", risk: "弱于指数" },
    { name: "光启技术", code: "002625.SZ", price: 38.3, changePct: -1.01, trend: "盘中偏弱", risk: "弱于指数" },
    { name: "迅游科技", code: "300467.SZ", price: 33.22, changePct: 1.28, trend: "盘中偏强", risk: "跟随指数" },
    { name: "伊利股份", code: "600887.SH", price: 25.41, changePct: -1.17, trend: "盘中偏弱", risk: "弱于指数" },
  ],
  weather: {
    city: "深圳",
    condition: "阴",
    temperature: 25,
    humidity: 99,
    wind: "东南风 4km/h",
  },
};

function formatSigned(value, suffix = "") {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}${suffix}`;
}

function toneClass(value) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

function signalFor(stock) {
  if (stock.changePct <= -1.5) return { label: "控风险", className: "signal-risk" };
  if (stock.changePct >= 2.5) return { label: "不追高", className: "signal-risk" };
  if (stock.changePct >= 0.8) return { label: "持有", className: "signal-hold" };
  return { label: "观察", className: "signal-watch" };
}

function buildMarketSummary(data) {
  const pct = data.index.changePct;
  if (pct >= 0.6) {
    return `${data.index.trend}，${data.index.volumeTone}。仓位可维持，追涨只看强势股回落。`;
  }
  if (pct <= -0.6) {
    return `${data.index.trend}，指数偏弱。先看防守位，减少临盘加仓。`;
  }
  return `${data.index.trend}，市场分歧中。重点看自选股相对强弱，不急着扩大仓位。`;
}

function buildAdvice(data) {
  const strong = data.stocks.filter((item) => item.changePct > data.index.changePct + 1);
  const weak = data.stocks.filter((item) => item.changePct < data.index.changePct - 1.2);
  const list = [];

  if (strong.length) {
    list.push(`强于指数：${strong.slice(0, 2).map((item) => item.name).join("、")}，等回踩确认。`);
  }

  if (weak.length) {
    list.push(`弱于指数：${weak.slice(0, 2).map((item) => item.name).join("、")}，先控仓观察。`);
  }

  list.push(data.index.changePct >= 0 ? "指数偏暖，避免在急拉处新增大仓位。" : "指数偏冷，优先保留现金和确定性。");
  return list.slice(0, 3);
}

function renderStocks(stocks) {
  const root = document.querySelector("#stockList");
  root.innerHTML = "";

  stocks.forEach((stock) => {
    const signal = signalFor(stock);
    const row = document.createElement("div");
    row.className = "stock-row";
    row.innerHTML = `
      <div class="stock-name">
        <strong>${stock.name}</strong>
        <span>${stock.code}</span>
      </div>
      <div>
        <span class="metric-label">现价</span>
        <strong class="stock-price">${stock.price.toFixed(2)}</strong>
      </div>
      <div class="${toneClass(stock.changePct)} stock-change">${formatSigned(stock.changePct, "%")}</div>
      <div class="signal ${signal.className}">${signal.label}</div>
    `;
    root.appendChild(row);
  });
}

function renderAdvice(data) {
  const root = document.querySelector("#adviceList");
  root.innerHTML = "";
  buildAdvice(data).forEach((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    root.appendChild(item);
  });
}

function render(data) {
  state.market = data;
  document.querySelector("#indexTitle").textContent = data.index.name;
  document.querySelector("#eyebrow").textContent = (data.ui && data.ui.eyebrow) || "行情观察";
  document.querySelector("#indexValue").textContent = data.index.price.toFixed(2);
  document.querySelector("#indexChange").className = `change-row ${toneClass(data.index.change)}`;
  document.querySelector("#indexChange").textContent = `${formatSigned(data.index.change)} / ${formatSigned(data.index.changePct, "%")}`;
  document.querySelector("#marketSummary").textContent = buildMarketSummary(data);
  document.querySelector("#weatherIcon").textContent = data.weather.condition;
  document.querySelector("#weatherTemp").textContent = `${data.weather.temperature}°`;
  document.querySelector("#weatherMeta").textContent = `${data.weather.city} · 湿度${data.weather.humidity}% · ${data.weather.wind}`;
  document.querySelector("#refreshText").textContent = new Date(data.updatedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  renderStocks(data.stocks);
  renderAdvice(data);
  renderClock(data);
  renderSparkline(data.index.series);
}

function renderClock(data) {
  // 优先用服务端注入的北京时间快照，不依赖设备时区或 JS 跑时钟
  if (data && data.clock && data.clock.clockText) {
    document.querySelector("#dateText").textContent = data.clock.dateText;
    document.querySelector("#timeText").textContent = data.clock.clockText;
    return;
  }
  const now = new Date();
  document.querySelector("#dateText").textContent = now.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
  document.querySelector("#timeText").textContent = now.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderSparkline(series) {
  // 分时折线用 SVG 实色（蓝）绘制，符合 6 色约束；无数据则隐藏整个区域
  const root = document.querySelector("#indexSparkline");
  if (!series || series.length < 2) {
    root.style.display = "none";
    return;
  }
  root.style.display = "";
  const w = 100;
  const h = 100;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const pts = series
    .map((v, i) => `${((i / (series.length - 1)) * w).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`)
    .join(" ");
  root.innerHTML =
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">` +
    `<polyline points="${pts}" fill="none" stroke="#1565c0" stroke-width="3" vector-effect="non-scaling-stroke" />` +
    `</svg>`;
}

async function loadData() {
  if (window.PANEL_DATA) {
    return window.PANEL_DATA;
  }

  const dataFiles = ["data/market.json", "data/sample-market.json"];

  for (const file of dataFiles) {
    try {
      const response = await fetch(file, { cache: "no-store" });
      if (!response.ok) throw new Error(`${file} unavailable`);
      return await response.json();
    } catch {
      // Try the next data source.
    }
  }

  return fallbackData;
}

// 时钟由服务端快照驱动（每次整页刷新时随 render 更新），无需 setInterval。
// 原因：SenseCraft 设备可能是静态截图渲染模式，setInterval 不会持续触发。
loadData().then(render);
