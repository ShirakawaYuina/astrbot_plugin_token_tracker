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
    trendTitle: "📈 近 14 天用量趋势",
    modelTitle: "🤖 各模型消耗占比",
  },
  today: {
    badge: "今日",
    primaryLabel: "今日 Token 消耗",
    secondaryLabel: "今日调用次数",
    trendTitle: "📈 今日逐小时用量分布",
    modelTitle: "🤖 今日模型消耗占比",
  },
  yesterday: {
    badge: "昨日",
    primaryLabel: "昨日 Token 消耗",
    secondaryLabel: "昨日调用次数",
    trendTitle: "📈 昨日逐小时用量分布",
    modelTitle: "🤖 昨日模型消耗占比",
  },
  "7d": {
    badge: "近 7 天",
    primaryLabel: "近 7 天 Token 消耗",
    secondaryLabel: "近 7 天调用次数",
    trendTitle: "📈 近 7 天用量趋势",
    modelTitle: "🤖 近 7 天模型消耗占比",
  },
  "30d": {
    badge: "近 30 天",
    primaryLabel: "近 30 天 Token 消耗",
    secondaryLabel: "近 30 天调用次数",
    trendTitle: "📈 近 30 天用量趋势",
    modelTitle: "🤖 近 30 天模型消耗占比",
  },
  this_month: {
    badge: "本月",
    primaryLabel: "本月 Token 消耗",
    secondaryLabel: "本月调用次数",
    trendTitle: "📈 本月用量趋势",
    modelTitle: "🤖 本月模型消耗占比",
  },
  custom: {
    badge: "自定义范围",
    primaryLabel: "时段 Token 消耗",
    secondaryLabel: "时段调用次数",
    trendTitle: "📈 所选时段用量分布",
    modelTitle: "🤖 所选时段模型消耗占比",
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
      $("kpi-today-avg-time").textContent = `平均耗时: ${(data.today_avg_duration_ms || data.avg_duration_ms || 0).toFixed(0)} ms`;

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
      $("kpi-today-avg-time").textContent = `平均耗时: ${(data.period_avg_duration_ms || 0).toFixed(0)} ms`;

      const hitRate = periodTokens > 0 ? ((periodCached / periodTokens) * 100).toFixed(1) : "0.0";
      $("kpi-cached-tokens").textContent = formatNumber(periodCached);
      $("kpi-cached-rate").textContent = `时段缓存率: ${hitRate}%`;
    }

    // 卡片3始终展示历史累计
    const totalTokens = data.total_tokens || 0;
    $("kpi-total-tokens").textContent = formatNumber(totalTokens);
    $("kpi-total-sub").textContent = `历史调用: ${formatNumber(data.total_calls || 0)} 次`;

  } catch (err) {
    console.error("Failed to load overview:", err);
    $("kpi-today-tokens").textContent = "0";
    $("kpi-today-sub").textContent = "输入: 0 | 输出: 0";
    $("kpi-today-calls").textContent = "0";
    $("kpi-today-avg-time").textContent = "平均耗时: 0 ms";
    $("kpi-total-tokens").textContent = "0";
    $("kpi-total-sub").textContent = "历史调用: 0 次";
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
      modelTitle = `🤖 模型消耗占比 (${customStartDate} ~ ${customEndDate})`;
    }
    if ($("model-chart-title")) {
      $("model-chart-title").textContent = modelTitle;
    }

    // 渲染环形饼图
    renderModelPieChart(models);

    // 渲染模型排行表
    const modelsTbody = $("models-table-body");
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

    // 渲染来源排行表
    const callersTbody = $("callers-table-body");
    if (callers.length === 0) {
      callersTbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color: var(--text-muted); padding: 24px;">所选时段暂无来源调用记录</td></tr>`;
    } else {
      callersTbody.innerHTML = callers.slice(0, 10).map((c) => {
        const typeBadge = c.caller_type === "plugin" ? "badge-purple" : "badge-gray";
        return `
          <tr>
            <td><strong>${c.caller_name}</strong></td>
            <td><span class="badge ${typeBadge}">${c.caller_type}</span></td>
            <td>${formatNumber(c.prompt_tokens)}</td>
            <td>${formatNumber(c.completion_tokens)}</td>
            <td>${formatNumber(c.total_tokens)}</td>
            <td>${formatNumber(c.call_count)}</td>
          </tr>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Failed to load models/callers:", err);
    $("models-table-body").innerHTML = `<tr><td colspan="6" class="text-center">加载失败</td></tr>`;
    $("callers-table-body").innerHTML = `<tr><td colspan="6" class="text-center">加载失败</td></tr>`;
  }
}

function renderModelPieChart(models) {
  const canvas = $("modelPieChart");
  if (!canvas || typeof Chart === "undefined") return;
  const ctx = canvas.getContext("2d");

  const topModels = models.slice(0, 6);
  const labels = topModels.map((m) => m.model);
  const data = topModels.map((m) => m.total_tokens);

  const colors = [
    "#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#64748b"
  ];

  if (modelPieChartInstance) {
    modelPieChartInstance.destroy();
  }

  const hasData = topModels.length > 0 && topModels.some(m => m.total_tokens > 0);

  modelPieChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: hasData ? labels : ["暂无消耗"],
      datasets: [{
        data: hasData ? data : [1],
        backgroundColor: hasData ? colors : ["#cbd5e1"],
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right" },
        tooltip: {
          callbacks: {
            title: function (tooltipItems) {
              if (!hasData || !tooltipItems || tooltipItems.length === 0) return "";
              const idx = tooltipItems[0].dataIndex;
              return topModels[idx]?.model || tooltipItems[0].label || "";
            },
            label: function (context) {
              if (!hasData) return "暂无消耗";
              const idx = context.dataIndex;
              const m = topModels[idx];
              if (!m) return "";
              return [
                `输入 Token (Prompt): ${formatNumber(m.prompt_tokens)}`,
                `输出 Token (Completion): ${formatNumber(m.completion_tokens)}`,
              ];
            },
          },
        },
      },
      cutout: "60%",
    },
  });
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
        trendTitle = "📈 昨日逐小时用量分布";
      } else if (currentTimeRange === "today") {
        trendTitle = "📈 今日逐小时用量分布";
      } else if (currentTimeRange === "custom") {
        trendTitle = `📈 逐小时用量分布 (${customStartDate})`;
      } else {
        trendTitle = "📈 逐小时用量分布";
      }
    } else if (currentTimeRange === "custom" && customStartDate && customEndDate) {
      trendTitle = `📈 用量趋势 (${customStartDate} ~ ${customEndDate})`;
    }
    if ($("trend-chart-title")) {
      $("trend-chart-title").textContent = trendTitle;
    }

    if (trendLineChartInstance) {
      trendLineChartInstance.destroy();
    }

    trendLineChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: data.labels || [],
        datasets: [
          {
            label: "输入 Token (Prompt)",
            data: data.prompts || [],
            backgroundColor: "#3b82f6",
            stack: "tokens",
          },
          {
            label: "输出 Token (Completion)",
            data: data.completions || [],
            backgroundColor: "#10b981",
            stack: "tokens",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          legend: { position: "top" },
          tooltip: {
            mode: "index",
            intersect: false,
            callbacks: {
              label: function (context) {
                const label = context.dataset.label || "";
                const val = context.parsed.y !== null ? formatNumber(context.parsed.y) : "0";
                return `${label}: ${val}`;
              },
            },
          },
        },
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true },
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

    const tbody = $("records-table-body");
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center" style="color: var(--text-muted); padding: 24px;">暂无调用明细记录</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map((r) => {
      let modeBadge = r.is_streaming ? '<span class="badge badge-blue">流式</span>' : '<span class="badge badge-gray">常规</span>';
      const mLower = String(r.model || "").toLowerCase();
      const pLower = String(r.provider_id || "").toLowerCase();
      const cLower = String(r.caller_name || "").toLowerCase();
      const isEmbed = r.caller_type === "embedding" || (!r.is_streaming && r.completion_tokens === 0 && (
        mLower.includes("embed") || pLower.includes("embed") || cLower.includes("livingmemory") || cLower.includes("kb")
      ));
      if (isEmbed) {
        modeBadge = '<span class="badge badge-purple">嵌入</span>';
      }
      const estBadge = r.is_estimated ? '<span class="badge badge-orange">估算</span>' : "";
      return `
        <tr>
          <td>${r.id}</td>
          <td>${r.datetime_str}</td>
          <td><strong>${r.model}</strong></td>
          <td>${r.caller_name}</td>
          <td>${formatNumber(r.prompt_tokens)}</td>
          <td>${formatNumber(r.completion_tokens)}</td>
          <td>${formatNumber(r.cached_tokens)}</td>
          <td><strong>${formatNumber(r.total_tokens)}</strong></td>
          <td>${(r.duration_ms || 0).toFixed(0)} ms</td>
          <td>${modeBadge} ${estBadge}</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Failed to load records:", err);
    $("records-table-body").innerHTML = `<tr><td colspan="10" class="text-center">加载明细失败</td></tr>`;
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
      if (!confirm("⚠️ 确定要清空所有历史 Token 记录吗？清空后不可恢复！")) {
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
