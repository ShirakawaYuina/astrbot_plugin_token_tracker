/**
 * AstrBot Token Tracker - Built-in Dashboard Controller
 */

const PLUGIN_NAME = "astrbot_plugin_token_tracker";

let modelPieChartInstance = null;
let trendLineChartInstance = null;
let currentPage = 1;
let currentTotalPages = 1;

let currentTimeRange = "all"; // 'all', 'today', 'yesterday', '7d', '30d', 'this_month', 'custom'
let customStartDate = "";
let customEndDate = "";

const RANGE_CONFIG = {
  all: {
    badge: "全部时间",
    primaryLabel: "今日 Token 消耗",
    secondaryLabel: "今日调用次数",
    trendTitle: "近 14 天用量走势与峰值",
    modelTitle: "各模型消耗占比",
  },
  today: {
    badge: "今日",
    primaryLabel: "今日 Token 消耗",
    secondaryLabel: "今日调用次数",
    trendTitle: "今日逐小时用量走势与峰值",
    modelTitle: "今日模型消耗占比",
  },
  yesterday: {
    badge: "昨日",
    primaryLabel: "昨日 Token 消耗",
    secondaryLabel: "昨日调用次数",
    trendTitle: "昨日逐小时用量走势与峰值",
    modelTitle: "昨日模型消耗占比",
  },
  "7d": {
    badge: "近 7 天",
    primaryLabel: "近 7 天 Token 消耗",
    secondaryLabel: "近 7 天调用次数",
    trendTitle: "近 7 天用量走势与峰值",
    modelTitle: "近 7 天模型消耗占比",
  },
  "30d": {
    badge: "近 30 天",
    primaryLabel: "近 30 天 Token 消耗",
    secondaryLabel: "近 30 天调用次数",
    trendTitle: "近 30 天用量走势与峰值",
    modelTitle: "近 30 天模型消耗占比",
  },
  this_month: {
    badge: "本月",
    primaryLabel: "本月 Token 消耗",
    secondaryLabel: "本月调用次数",
    trendTitle: "本月用量走势与峰值",
    modelTitle: "本月模型消耗占比",
  },
  custom: {
    badge: "自定义范围",
    primaryLabel: "时段 Token 消耗",
    secondaryLabel: "时段调用次数",
    trendTitle: "所选时段用量走势与峰值",
    modelTitle: "所选时段模型消耗占比",
  },
};

function $(id) {
  return document.getElementById(id);
}

function getBridge() {
  return window.AstrBotPluginPage || null;
}

function showToast(message) {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 3500);
}

function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseLocalDate(dateStr, isEndOfDay = false) {
  const parts = dateStr.split("-").map(Number);
  if (isEndOfDay) {
    return new Date(parts[0], parts[1] - 1, parts[2], 23, 59, 59, 999);
  }
  return new Date(parts[0], parts[1] - 1, parts[2], 0, 0, 0, 0);
}

function getTimeRangeParams() {
  const params = {};
  if (currentTimeRange === "all") {
    return params;
  }

  const now = new Date();

  if (currentTimeRange === "today") {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    params.start_time = Math.floor(start.getTime() / 1000);
    params.end_time = Math.floor(end.getTime() / 1000);
    params.start_date = formatDate(start);
    params.end_date = formatDate(end);
  } else if (currentTimeRange === "yesterday") {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59, 999);
    params.start_time = Math.floor(start.getTime() / 1000);
    params.end_time = Math.floor(end.getTime() / 1000);
    params.start_date = formatDate(start);
    params.end_date = formatDate(end);
  } else if (currentTimeRange === "7d") {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6, 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    params.start_time = Math.floor(start.getTime() / 1000);
    params.end_time = Math.floor(end.getTime() / 1000);
    params.start_date = formatDate(start);
    params.end_date = formatDate(end);
  } else if (currentTimeRange === "30d") {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 29, 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    params.start_time = Math.floor(start.getTime() / 1000);
    params.end_time = Math.floor(end.getTime() / 1000);
    params.start_date = formatDate(start);
    params.end_date = formatDate(end);
  } else if (currentTimeRange === "this_month") {
    const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    params.start_time = Math.floor(start.getTime() / 1000);
    params.end_time = Math.floor(end.getTime() / 1000);
    params.start_date = formatDate(start);
    params.end_date = formatDate(end);
  } else if (currentTimeRange === "custom") {
    if (customStartDate && customEndDate) {
      const start = parseLocalDate(customStartDate, false);
      const end = parseLocalDate(customEndDate, true);
      params.start_time = Math.floor(start.getTime() / 1000);
      params.end_time = Math.floor(end.getTime() / 1000);
      params.start_date = customStartDate;
      params.end_date = customEndDate;
    }
  }

  return params;
}

async function apiGet(endpoint, params = {}) {
  const bridge = getBridge();
  if (bridge && typeof bridge.apiGet === "function") {
    try {
      if (typeof bridge.ready === "function") {
        await bridge.ready();
      }
      return await bridge.apiGet(endpoint, params);
    } catch (err) {
      console.warn("bridge.apiGet failed, falling back to direct API:", err);
    }
  }

  // Fallback: 直接请求 AstrBot 原生扩展 API
  const url = new URL(`/api/v1/plugins/extensions/${PLUGIN_NAME}/${endpoint}`, window.location.origin);
  Object.keys(params).forEach((k) => {
    if (params[k] !== undefined && params[k] !== null && params[k] !== "") {
      url.searchParams.set(k, params[k]);
    }
  });

  const res = await fetch(url.toString(), {
    headers: { "Accept": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  const json = await res.json();
  if (json && json.status === "error") {
    throw new Error(json.message || "Request failed");
  }
  return json?.data ?? json;
}

async function apiPost(endpoint, body = {}) {
  const bridge = getBridge();
  if (bridge && typeof bridge.apiPost === "function") {
    try {
      if (typeof bridge.ready === "function") {
        await bridge.ready();
      }
      return await bridge.apiPost(endpoint, body);
    } catch (err) {
      console.warn("bridge.apiPost failed, falling back to direct API:", err);
    }
  }

  const res = await fetch(`/api/v1/plugins/extensions/${PLUGIN_NAME}/${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  const json = await res.json();
  if (json && json.status === "error") {
    throw new Error(json.message || "Request failed");
  }
  return json?.data ?? json;
}

function formatNumber(num) {
  return Number(num || 0).toLocaleString();
}

async function loadOverview() {
  try {
    const timeParams = getTimeRangeParams();
    const data = await apiGet("overview", timeParams);
    const sym = data.currency_symbol || "¥";

    const isAll = currentTimeRange === "all";
    const cfg = RANGE_CONFIG[currentTimeRange] || RANGE_CONFIG.all;

    // 更新 KPI 标签文字
    if ($("kpi-label-primary")) $("kpi-label-primary").textContent = cfg.primaryLabel;
    if ($("kpi-label-secondary")) $("kpi-label-secondary").textContent = cfg.secondaryLabel;

    if (isAll) {
      // 默认/全部时间: 卡片1与卡片2展示今日，卡片3展示历史累计
      const todayTokens = data.today_tokens || 0;
      const todayPrompt = data.today_prompt_tokens || 0;
      const todayCached = data.today_cached_tokens || 0;
      const todayCompletion = data.today_completion_tokens || 0;
      $("kpi-today-tokens").textContent = formatNumber(todayTokens);
      const cacheNote = todayCached > 0 ? ` (含缓存 ${formatNumber(todayCached)})` : "";
      $("kpi-today-sub").textContent = `输入: ${formatNumber(todayPrompt)}${cacheNote} | 输出: ${formatNumber(todayCompletion)}`;

      $("kpi-today-calls").textContent = formatNumber(data.today_calls || 0);
      $("kpi-today-avg-time").textContent = `平均耗时: ${((data.today_avg_duration_ms || data.avg_duration_ms || 0) / 1000).toFixed(2)} s`;

      const cachedTokens = data.total_cached_tokens || 0;
      const totalTokens = data.total_tokens || 0;
      const hitRate = totalTokens > 0 ? ((cachedTokens / totalTokens) * 100).toFixed(1) : "0.0";
      $("kpi-cached-tokens").textContent = formatNumber(cachedTokens);
      $("kpi-cached-rate").textContent = `缓存命中率: ${hitRate}%`;
    } else {
      // 有时段筛选: 卡片1与卡片2展示该时段数据
      const periodTokens = data.period_tokens || 0;
      const periodPrompt = data.period_prompt_tokens || 0;
      const periodCached = data.period_cached_tokens || 0;
      const periodCompletion = data.period_completion_tokens || 0;
      $("kpi-today-tokens").textContent = formatNumber(periodTokens);
      const cacheNote = periodCached > 0 ? ` (含缓存 ${formatNumber(periodCached)})` : "";
      $("kpi-today-sub").textContent = `输入: ${formatNumber(periodPrompt)}${cacheNote} | 输出: ${formatNumber(periodCompletion)}`;

      $("kpi-today-calls").textContent = formatNumber(data.period_calls || 0);
      $("kpi-today-avg-time").textContent = `平均耗时: ${((data.period_avg_duration_ms || 0) / 1000).toFixed(2)} s`;

      const hitRate = periodTokens > 0 ? ((periodCached / periodTokens) * 100).toFixed(1) : "0.0";
      $("kpi-cached-tokens").textContent = formatNumber(periodCached);
      $("kpi-cached-rate").textContent = `时段缓存率: ${hitRate}%`;
    }

    // 卡片3始终展示历史累计
    const totalTokens = data.total_tokens || 0;
    $("kpi-total-tokens").textContent = formatNumber(totalTokens);
    $("kpi-total-sub").textContent = `历史调用: ${formatNumber(data.total_calls || 0)} 次`;

    const startDate = data.start_date || data.earliest_date || "";
    const endDate = data.end_date || data.latest_date || "";
    const startDt = data.start_datetime || data.earliest_datetime || "";
    const endDt = data.end_datetime || data.latest_datetime || "";

    const rangeEl = $("kpi-total-range");
    if (rangeEl) {
      if (startDate && endDate) {
        if (startDate === endDate) {
          rangeEl.textContent = `统计范围: ${startDate}`;
        } else {
          rangeEl.textContent = `统计范围: ${startDate} ~ ${endDate}`;
        }
        if (startDt && endDt) {
          rangeEl.title = `起止时间: ${startDt} 至 ${endDt}`;
        }
      } else if (startDate) {
        rangeEl.textContent = `统计范围: ${startDate}`;
      } else {
        rangeEl.textContent = `统计范围: 暂无数据`;
      }
    }

  } catch (err) {
    console.error("Failed to load overview:", err);
    $("kpi-today-tokens").textContent = "0";
    $("kpi-today-sub").textContent = "输入: 0 | 输出: 0";
    $("kpi-today-calls").textContent = "0";
    $("kpi-today-avg-time").textContent = "平均耗时: 0.00 s";
    $("kpi-total-tokens").textContent = "0";
    $("kpi-total-sub").textContent = "历史调用: 0 次";
    if ($("kpi-total-range")) $("kpi-total-range").textContent = "统计范围: 暂无数据";
    $("kpi-cached-tokens").textContent = "0";
    $("kpi-cached-rate").textContent = "缓存命中率: 0.0%";
  }
}

async function loadModelsAndCallers() {
  try {
    const timeParams = getTimeRangeParams();
    const [modelsRes, callersRes] = await Promise.all([
      apiGet("models", timeParams).catch(() => ({ models: [] })),
      apiGet("callers", timeParams).catch(() => ({ callers: [] })),
    ]);

    const models = modelsRes.models || [];
    const callers = callersRes.callers || [];
    const periodTokens = models.reduce((acc, m) => acc + (m.total_tokens || 0), 0) || 1;

    // 动态调整模型占比标题
    const cfg = RANGE_CONFIG[currentTimeRange] || RANGE_CONFIG.all;
    let modelTitle = cfg.modelTitle;
    if (currentTimeRange === "custom" && customStartDate && customEndDate) {
      modelTitle = `模型消耗占比 (${customStartDate} ~ ${customEndDate})`;
    }
    if ($("model-chart-title")) {
      $("model-chart-title").textContent = modelTitle;
    }

    // 渲染环形饼图
    renderModelPieChart(models);

    // 渲染模型排行表 (概览页已精简，若存在则更新)
    const modelsTbody = $("models-table-body");
    if (modelsTbody) {
      if (models.length === 0) {
        modelsTbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color: var(--text-muted); padding: 24px;">所选时段暂无模型调用记录</td></tr>`;
      } else {
        modelsTbody.innerHTML = models.slice(0, 10).map((m) => {
          const pct = ((m.total_tokens / periodTokens) * 100).toFixed(1);
          return `
            <tr>
              <td><strong>${m.model}</strong></td>
              <td>${formatNumber(m.prompt_tokens)}</td>
              <td>${formatNumber(m.completion_tokens)}</td>
              <td>${formatNumber(m.total_tokens)}</td>
              <td>${formatNumber(m.call_count)}</td>
              <td><span class="badge badge-blue">${pct}%</span></td>
            </tr>
          `;
        }).join("");
      }
    }    // 渲染模型全量列表（Tab 2 - 极简单行流）
    const modelsContainer = $("models-compact-list") || $("models-table-body-full");
    const modelsTotalPill = $("models-total-pill");
    if (modelsTotalPill) {
      modelsTotalPill.textContent = `共 ${models.length} 个模型`;
    }
    if (modelsContainer) {
      if (models.length === 0) {
        modelsContainer.innerHTML = `
          <div class="empty-compact-state">
            <span>所选时段暂无模型调用记录</span>
          </div>
        `;
      } else {
        const colors = ["#2563eb", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#64748b"];
        modelsContainer.innerHTML = models.map((m, idx) => {
          const pct = periodTokens > 0 ? ((m.total_tokens / periodTokens) * 100).toFixed(1) : "0.0";
          const color = colors[idx % colors.length];
          const isTop = idx === 0;

          return `
            <div class="compact-row" title="${m.model}&#10;总用量: ${formatNumber(m.total_tokens)} tokens (${pct}%)&#10;输入: ${formatNumber(m.prompt_tokens)}&#10;输出: ${formatNumber(m.completion_tokens)}&#10;缓存: ${formatNumber(m.cached_tokens)}&#10;调用次数: ${formatNumber(m.call_count)}">
              <div class="row-left">
                <span class="row-rank ${isTop ? 'rank-top' : ''}">#${idx + 1}</span>
                <div class="model-chip" title="${m.model}">
                  <span class="dot" style="background: ${color};"></span>
                  <span>${m.model}</span>
                </div>
                <div class="calls-col">
                  <span class="calls-badge">${formatNumber(m.call_count)} 次调用</span>
                </div>
              </div>
              <div class="row-right">
                <span class="row-tokens">${formatNumber(m.total_tokens)} <span class="row-tokens-unit">tokens</span></span>
                <div class="row-io-split">
                  <span class="split-p" title="输入 Token">入 ${formatNumber(m.prompt_tokens)}</span>
                  <span class="split-c" title="输出 Token">出 ${formatNumber(m.completion_tokens)}</span>
                  <span class="split-cached ${m.cached_tokens > 0 ? 'hit' : ''}" title="缓存 Token">缓 ${formatNumber(m.cached_tokens || 0)}</span>
                </div>
                <span class="row-pct-pill">${pct}%</span>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // 渲染来源全量列表（Tab 3 - 极简单行流）
    const callersContainer = $("callers-compact-list") || $("callers-table-body-full");
    const callersTotalPill = $("callers-total-pill");
    const totalCallerTokens = callers.reduce((acc, c) => acc + (c.total_tokens || 0), 0);
    if (callersTotalPill) {
      callersTotalPill.textContent = `共 ${callers.length} 个来源`;
    }
    if (callersContainer) {
      if (callers.length === 0) {
        callersContainer.innerHTML = `
          <div class="empty-compact-state">
            <span>所选时段暂无来源调用记录</span>
          </div>
        `;
      } else {
        const colors = ["#8b5cf6", "#2563eb", "#10b981", "#f59e0b", "#ec4899", "#64748b"];
        callersContainer.innerHTML = callers.map((c, idx) => {
          const pct = totalCallerTokens > 0 ? ((c.total_tokens / totalCallerTokens) * 100).toFixed(1) : "0.0";
          const color = colors[idx % colors.length];
          const isTop = idx === 0;
          const isPlugin = c.caller_type === "plugin";

          return `
            <div class="compact-row" title="${c.caller_name}&#10;类型: ${c.caller_type}&#10;总用量: ${formatNumber(c.total_tokens)} tokens (${pct}%)&#10;输入: ${formatNumber(c.prompt_tokens)}&#10;输出: ${formatNumber(c.completion_tokens)}&#10;调用次数: ${formatNumber(c.call_count)}">
              <div class="row-left">
                <span class="row-rank ${isTop ? 'rank-top' : ''}">#${idx + 1}</span>
                <div class="caller-entity-col">
                  <div class="model-chip" title="${c.caller_name}">
                    <span class="dot" style="background: ${color};"></span>
                    <span>${c.caller_name}</span>
                  </div>
                  <span class="${isPlugin ? 'tag-plugin' : 'tag-chat'}">${isPlugin ? '插件' : '核心对话'}</span>
                </div>
                <div class="calls-col">
                  <span class="calls-badge">${formatNumber(c.call_count)} 次调用</span>
                </div>
              </div>
              <div class="row-right">
                <span class="row-tokens">${formatNumber(c.total_tokens)} <span class="row-tokens-unit">tokens</span></span>
                <div class="row-io-split">
                  <span class="split-p" title="输入 Token">入 ${formatNumber(c.prompt_tokens)}</span>
                  <span class="split-c" title="输出 Token">出 ${formatNumber(c.completion_tokens)}</span>
                  <span class="split-cached ${c.cached_tokens > 0 ? 'hit' : ''}" title="缓存 Token">缓 ${formatNumber(c.cached_tokens || 0)}</span>
                </div>
                <span class="row-pct-pill">${pct}%</span>
              </div>
            </div>
          `;
        }).join("");
      }
    }} catch (err) {
    console.error("Failed to load models/callers:", err);
    if ($("models-table-body")) $("models-table-body").innerHTML = `<tr><td colspan="6" class="text-center">加载失败</td></tr>`;
    if ($("callers-table-body")) $("callers-table-body").innerHTML = `<tr><td colspan="6" class="text-center">加载失败</td></tr>`;
  }
}

function renderModelPieChart(models) {
  const container = $("modelWidgetGrid");
  if (!container) return;

  const statPill = $("model-stat-pill");
  const grandTotal = models.reduce((acc, m) => acc + (m.total_tokens || 0), 0);
  const topModels = models.slice(0, 6);

  if (statPill) {
    statPill.textContent = topModels.length > 0 ? `${topModels.length} 个活跃模型` : "暂无活跃模型";
  }

  if (topModels.length === 0 || grandTotal === 0) {
    container.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; min-height: 240px; color: var(--text-muted); font-size: 0.85rem;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.5; margin-bottom: 8px;">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span>所选时段暂无模型调用数据</span>
      </div>
    `;
    return;
  }

  const colors = [
    "#2563eb", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#64748b"
  ];

  // SVG 独立微环进度参数 (r = 18, 周长 ≈ 113.1)
  const circumference = 2 * Math.PI * 18;

  const cardsHtml = topModels.map((m, idx) => {
    const pct = grandTotal > 0 ? ((m.total_tokens / grandTotal) * 100).toFixed(1) : "0.0";
    const numPct = parseFloat(pct);
    const strokeDash = (numPct / 100) * circumference;
    const strokeOffset = Math.max(0, circumference - strokeDash);
    const color = colors[idx % colors.length];
    const isTop = idx === 0;

    return `
      <div class="widget-card" title="${m.model}&#10;总消耗: ${formatNumber(m.total_tokens)} tokens (${pct}%)&#10;输入 (Prompt): ${formatNumber(m.prompt_tokens)}&#10;输出 (Completion): ${formatNumber(m.completion_tokens)}&#10;调用次数: ${formatNumber(m.call_count)}">
        <div class="progress-circle-wrap">
          <svg viewBox="0 0 44 44">
            <circle class="circle-bg" cx="22" cy="22" r="18" />
            <circle class="circle-fill" cx="22" cy="22" r="18"
              stroke="${color}"
              stroke-dasharray="${circumference.toFixed(1)}"
              stroke-dashoffset="${strokeOffset.toFixed(1)}" />
          </svg>
          <div class="circle-pct-text">${Math.round(numPct)}%</div>
        </div>
        <div class="widget-info">
          <div class="widget-top-line">
            <span class="widget-name">${m.model}</span>
            <span class="widget-rank ${isTop ? 'rank-top' : ''}">#${idx + 1}</span>
          </div>
          <div class="widget-val-line">
            <span class="widget-val">${formatCompactTokens(m.total_tokens)} <span class="widget-unit">tokens</span></span>
            <span class="widget-calls">${formatNumber(m.call_count)} 次</span>
          </div>
          <div class="widget-sub-line">
            <span class="tag-io-p" title="输入 Token">入 ${formatCompactTokens(m.prompt_tokens)}</span>
            <span class="tag-io-c" title="输出 Token">出 ${formatCompactTokens(m.completion_tokens)}</span>
          </div>
        </div>
      </div>
    `;
  }).join("");

  container.innerHTML = `<div class="widget-grid">${cardsHtml}</div>`;
}

function formatCompactTokens(val) {
  if (val === null || val === undefined || isNaN(val)) return "0";
  const num = Number(val);
  if (num >= 1000000) {
    return (num / 1000000).toFixed(2).replace(/\.00$/, "").replace(/(\.[0-9])0$/, "$1") + "M";
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1).replace(/\.0$/, "") + "K";
  }
  return num.toLocaleString();
}

async function loadTrend() {
  try {
    const timeParams = getTimeRangeParams();
    const data = await apiGet("trend", { ...timeParams, days: 14 });
    const canvas = $("trendLineChart");
    if (!canvas || typeof Chart === "undefined") return;
    const ctx = canvas.getContext("2d");

    // 动态调整趋势图标题
    const cfg = RANGE_CONFIG[currentTimeRange] || RANGE_CONFIG.all;
    let trendTitle = cfg.trendTitle;
    if (data.mode === "hourly") {
      if (currentTimeRange === "yesterday") {
        trendTitle = "昨日逐小时用量走势与峰值";
      } else if (currentTimeRange === "today") {
        trendTitle = "今日逐小时用量走势与峰值";
      } else if (currentTimeRange === "custom") {
        trendTitle = `逐小时用量走势与峰值 (${customStartDate})`;
      } else {
        trendTitle = "逐小时用量走势与峰值";
      }
    } else if (currentTimeRange === "custom" && customStartDate && customEndDate) {
      trendTitle = `用量走势与峰值 (${customStartDate} ~ ${customEndDate})`;
    }
    if ($("trend-chart-title")) {
      $("trend-chart-title").textContent = trendTitle;
    }

    const rawLabels = data.labels || [];
    const prompts = data.prompts || [];
    const completions = data.completions || [];
    const totals = (data.totals && data.totals.length === rawLabels.length)
      ? data.totals
      : rawLabels.map((_, i) => (prompts[i] || 0) + (completions[i] || 0));

    const totalSum = totals.reduce((acc, v) => acc + (v || 0), 0);
    const avgVal = rawLabels.length > 0 ? totalSum / rawLabels.length : 0;
    const maxVal = totals.length > 0 ? Math.max(...totals, 0) : 0;
    const peakIndex = totals.indexOf(maxVal);

    // 更新右上角均值统计胶囊（如：日均 1.55M tokens / 时均 12.3K tokens）
    const pill = $("trend-stat-pill");
    if (pill) {
      const avgLabel = data.mode === "hourly" ? "时均" : "日均";
      pill.textContent = `${avgLabel} ${formatCompactTokens(avgVal)} tokens`;
    }

    if (trendLineChartInstance) {
      trendLineChartInstance.destroy();
    }

    const todayStr = formatDate(new Date());

    trendLineChartInstance = new Chart(ctx, {
      type: "line",
      data: {
        labels: rawLabels,
        datasets: [
          {
            label: "Token 总消耗",
            data: totals,
            borderColor: "#2563eb",
            borderWidth: 2.5,
            fill: "start",
            // 曲线下方动态垂直渐变色：顶部深蓝 -> 中部过渡 -> 底部基线颜色完全消失
            backgroundColor: function (context) {
              const chart = context.chart;
              const { ctx: chartCtx, chartArea } = chart;
              if (!chartArea) {
                return "rgba(37, 99, 235, 0.15)";
              }
              const g = chartCtx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
              g.addColorStop(0, "rgba(37, 99, 235, 0.55)");    // 曲线紧贴处深蓝
              g.addColorStop(0.35, "rgba(59, 130, 246, 0.30)"); // 中部过度
              g.addColorStop(0.75, "rgba(59, 130, 246, 0.10)"); // 下部渐淡
              g.addColorStop(1, "rgba(59, 130, 246, 0.00)");    // 底部基线完全透明消失
              return g;
            },
            tension: 0.42,
            cubicInterpolationMode: "monotone",
            // 默认隐藏普通数据点，仅在峰值处展示高亮圆点
            pointRadius: function (context) {
              return (context.dataIndex === peakIndex && maxVal > 0) ? 4.5 : 0;
            },
            pointHoverRadius: 6,
            pointBackgroundColor: "#ffffff",
            pointBorderColor: "#2563eb",
            pointBorderWidth: 2.5,
            pointHoverBackgroundColor: "#ffffff",
            pointHoverBorderColor: "#1d4ed8",
            pointHoverBorderWidth: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: { top: 14, bottom: 4, left: 6, right: 14 },
        },
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index",
            intersect: false,
            backgroundColor: "rgba(15, 23, 42, 0.94)",
            titleColor: "#f8fafc",
            bodyColor: "#cbd5e1",
            borderColor: "rgba(255, 255, 255, 0.12)",
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
            callbacks: {
              title: function (items) {
                if (!items || !items.length) return "";
                const idx = items[0].dataIndex;
                const raw = rawLabels[idx] || "";
                if (data.mode === "hourly") {
                  return raw;
                }
                return raw === todayStr ? `${raw} (今日)` : raw;
              },
              label: function (context) {
                const idx = context.dataIndex;
                const tot = totals[idx] || 0;
                const p = prompts[idx] || 0;
                const c = completions[idx] || 0;
                const lines = [];
                if (idx === peakIndex && maxVal > 0) {
                  lines.push("周期最高峰值");
                }
                lines.push(`总消耗: ${formatNumber(tot)} tokens`);
                lines.push(`输入: ${formatNumber(p)} | 输出: ${formatNumber(c)}`);
                return lines;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false, drawBorder: false },
            border: { display: false },
            ticks: {
              color: "#94a3b8",
              font: { size: 11 },
              maxTicksLimit: 6,
              maxRotation: 0,
              minRotation: 0,
              autoSkip: true,
              callback: function (val, index) {
                const raw = this.getLabelForValue(val) || "";
                if (data.mode === "hourly") {
                  return raw.includes(" ") ? raw.split(" ")[1] : raw;
                }
                let shortDate = raw.length >= 10 ? raw.slice(5) : raw;
                if (raw === todayStr || index === rawLabels.length - 1) {
                  shortDate += " (今日)";
                }
                return shortDate;
              },
            },
          },
          y: {
            display: true,
            beginAtZero: true,
            suggestedMax: maxVal > 0 ? maxVal * 1.15 : 100,
            border: { display: false },
            grid: {
              display: true,
              color: "rgba(148, 163, 184, 0.16)",
              borderDash: [4, 4],
              drawTicks: true,
              tickLength: 4,
            },
            ticks: {
              color: "#94a3b8",
              font: { size: 10.5 },
              maxTicksLimit: 5,
              padding: 6,
              callback: function (val) {
                return formatCompactTokens(val);
              },
            },
          },
        },
      },
    });
  } catch (err) {
    console.error("Failed to load trend:", err);
  }
}

async function loadRecords(page = 1) {
  try {
    currentPage = page;
    const keyword = ($("filter-keyword") ? $("filter-keyword").value : "").trim();
    const timeParams = getTimeRangeParams();
    const res = await apiGet("records", {
      page: currentPage,
      page_size: 15,
      keyword: keyword,
      ...timeParams,
    });

    const items = res.items || [];
    currentTotalPages = res.total_pages || 1;

    $("pagination-info").textContent = `第 ${res.page || 1} / ${currentTotalPages} 页 (共 ${res.total || 0} 条)`;
    $("btn-prev").disabled = currentPage <= 1;
    $("btn-next").disabled = currentPage >= currentTotalPages;

    const container = $("records-compact-list") || $("records-table-body");
    if (!container) return;

    if (items.length === 0) {
      container.innerHTML = `
        <div class="empty-compact-state">
          <span>暂无明细流水记录</span>
        </div>
      `;
      return;
    }

    const colors = ["#2563eb", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#64748b"];

    container.innerHTML = items.map((r, idx) => {
      const isStreaming = r.is_streaming;
      const isEstimated = r.is_estimated;
      const mLower = String(r.model || "").toLowerCase();
      const pLower = String(r.provider_id || "").toLowerCase();
      const cLower = String(r.caller_name || "").toLowerCase();
      const isEmbed = r.caller_type === "embedding" || (!isStreaming && r.completion_tokens === 0 && (
        mLower.includes("embed") || pLower.includes("embed") || cLower.includes("livingmemory") || cLower.includes("kb")
      ));

      let modeTag = isEmbed ? '<span class="tag-embed">嵌入</span>' : (isStreaming ? '<span class="tag-stream">流式</span>' : '<span class="tag-stream">常规</span>');
      let estTag = isEstimated ? '<span class="tag-est">估算</span>' : '';

      const durSec = (r.duration_ms || 0) / 1000;
      const isSlow = durSec > 10.0;
      const color = colors[idx % colors.length];

      // 提取纯时分秒，提高紧凑可读性
      let timeStr = r.datetime_str || "";
      if (timeStr.includes(" ")) {
        timeStr = timeStr.split(" ")[1];
      }

      return `
        <div class="compact-row" title="${r.model}&#10;来源: ${r.caller_name}&#10;完整时戳: ${r.datetime_str}&#10;总用量: ${formatNumber(r.total_tokens)} tokens&#10;输入 (Prompt): ${formatNumber(r.prompt_tokens)}&#10;输出 (Completion): ${formatNumber(r.completion_tokens)}&#10;缓存 (Cached): ${formatNumber(r.cached_tokens)}&#10;耗时: ${durSec.toFixed(2)}s">
          <div class="row-left">
            <span class="row-id">#${r.id}</span>
            <span class="row-time">${timeStr}</span>
            <div class="model-chip" title="${r.model}">
              <span class="dot" style="background: ${color};"></span>
              <span>${r.model}</span>
            </div>
            <div class="caller-col">
              <span class="caller-chip" title="${r.caller_name}">${r.caller_name}</span>
              <div class="tags-group">
                ${modeTag}
                ${estTag}
              </div>
            </div>
          </div>
          <div class="row-right">
            <span class="row-tokens">${formatNumber(r.total_tokens)} <span class="row-tokens-unit">tokens</span></span>
            <div class="row-io-split">
              <span class="split-p" title="输入 Token">入 ${formatNumber(r.prompt_tokens)}</span>
              <span class="split-c" title="输出 Token">出 ${formatNumber(r.completion_tokens)}</span>
              <span class="split-cached ${r.cached_tokens > 0 ? 'hit' : ''}" title="缓存 Token">缓 ${formatNumber(r.cached_tokens || 0)}</span>
            </div>
            <span class="row-lat-pill ${isSlow ? 'lat-slow' : 'lat-normal'}">${durSec.toFixed(2)}s</span>
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    console.error("Failed to load records:", err);
    const container = $("records-compact-list") || $("records-table-body");
    if (container) {
      container.innerHTML = `
        <div class="empty-compact-state">
          <span style="color: #ef4444;">加载明细记录失败</span>
        </div>
      `;
    }
  }
}

async function refreshAll() {
  await Promise.allSettled([
    loadOverview(),
    loadModelsAndCallers(),
    loadTrend(),
    loadRecords(1),
  ]);
  showToast("数据已刷新");
}

function bindEvents() {
  // 标签页切换 (Vuetify V-Tabs)
  const tabItems = document.querySelectorAll("#main-tabs-bar .v-tab-item");
  tabItems.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabItems.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const targetId = tab.getAttribute("data-tab");
      document.querySelectorAll(".tab-content-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === targetId);
      });
      if (targetId === "tab-overview") {
        if (modelPieChartInstance) modelPieChartInstance.resize();
        if (trendLineChartInstance) trendLineChartInstance.resize();
      }
    });
  });

  // 刷新按钮
  const refreshBtn = $("btn-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      refreshAll();
    });
  }

  // 时间筛选预设按钮
  const presetContainer = $("time-presets");
  if (presetContainer) {
    presetContainer.addEventListener("click", (e) => {
      const btn = e.target.closest(".time-btn");
      if (!btn) return;
      const range = btn.dataset.range;
      if (!range) return;

      presetContainer.querySelectorAll(".time-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      currentTimeRange = range;
      const customContainer = $("custom-date-container");

      if (range === "custom") {
        if (customContainer) customContainer.classList.remove("hidden");
        const todayStr = formatDate(new Date());
        if ($("custom-start-date") && !$("custom-start-date").value) {
          $("custom-start-date").value = todayStr;
        }
        if ($("custom-end-date") && !$("custom-end-date").value) {
          $("custom-end-date").value = todayStr;
        }
        return;
      }

      if (customContainer) customContainer.classList.add("hidden");

      const badge = $("current-filter-badge");
      if (badge) {
        badge.textContent = RANGE_CONFIG[range]?.badge || range;
      }

      refreshAll();
    });
  }

  // 自定义日期“应用”按钮
  const applyCustomBtn = $("btn-apply-custom-date");
  if (applyCustomBtn) {
    applyCustomBtn.addEventListener("click", () => {
      const sVal = $("custom-start-date") ? $("custom-start-date").value : "";
      const eVal = $("custom-end-date") ? $("custom-end-date").value : "";
      if (!sVal || !eVal) {
        showToast("请选择完整的起止日期");
        return;
      }
      if (sVal > eVal) {
        showToast("开始日期不能晚于结束日期");
        return;
      }
      customStartDate = sVal;
      customEndDate = eVal;

      const badge = $("current-filter-badge");
      if (badge) {
        badge.textContent = `${sVal} 至 ${eVal}`;
      }

      refreshAll();
    });
  }

  // 导出 CSV (携带时段过滤参数)
  const exportBtn = $("btn-export");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const timeParams = getTimeRangeParams();
      const keyword = ($("filter-keyword") ? $("filter-keyword").value : "").trim();
      const params = { ...timeParams };
      if (keyword) params.keyword = keyword;

      const bridge = getBridge();
      if (bridge && typeof bridge.download === "function") {
        bridge.download("export-csv", params, `token_records_${Date.now()}.csv`);
      } else {
        const q = new URLSearchParams(params).toString();
        const url = `/api/v1/plugins/extensions/${PLUGIN_NAME}/export-csv${q ? '?' + q : ''}`;
        window.open(url, "_blank");
      }
    });
  }

  // 清空数据
  const clearBtn = $("btn-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      if (!confirm("确定要清空所有历史 Token 记录吗？清空后不可恢复！")) {
        return;
      }
      try {
        await apiPost("clear");
        showToast("已清空历史统计记录");
        await refreshAll();
      } catch (err) {
        alert("清空失败: " + err.message);
      }
    });
  }

  // 搜索关键字
  const searchBtn = $("btn-search");
  if (searchBtn) {
    searchBtn.addEventListener("click", () => {
      loadRecords(1);
    });
  }

  const filterInput = $("filter-keyword");
  if (filterInput) {
    filterInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        loadRecords(1);
      }
    });
  }

  // 分页翻页
  const prevBtn = $("btn-prev");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) {
        loadRecords(currentPage - 1);
      }
    });
  }

  const nextBtn = $("btn-next");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (currentPage < currentTotalPages) {
        loadRecords(currentPage + 1);
      }
    });
  }
}

// 启动初始化
async function init() {
  const bridge = getBridge();
  if (bridge) {
    if (typeof bridge.onContext === "function") {
      bridge.onContext((ctx) => {
        if (ctx && ctx.isDark) {
          document.documentElement.setAttribute("data-theme", "dark");
        } else {
          document.documentElement.setAttribute("data-theme", "light");
        }
      });
    }

    if (typeof bridge.ready === "function") {
      try {
        await bridge.ready();
      } catch (err) {
        console.warn("bridge.ready error:", err);
      }
    }
  }

  bindEvents();
  await refreshAll();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
