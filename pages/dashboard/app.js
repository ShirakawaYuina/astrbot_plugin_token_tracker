/**
 * AstrBot Token Tracker - Built-in Dashboard Controller
 */

const PLUGIN_NAME = "astrbot_plugin_token_tracker";

let modelPieChartInstance = null;
let trendLineChartInstance = null;
let currentPage = 1;
let currentTotalPages = 1;

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
    const data = await apiGet("overview");
    const sym = data.currency_symbol || "¥";
    const todayTokens = data.today_tokens || 0;
    const todayCost = data.estimated_cost_today || 0;
    const totalTokens = data.total_tokens || 0;
    const totalCost = data.estimated_cost_total || 0;

    $("kpi-today-tokens").textContent = formatNumber(todayTokens);
    $("kpi-today-sub").textContent = `预估费用: ~${sym}${todayCost.toFixed(4)}`;

    $("kpi-today-calls").textContent = formatNumber(data.today_calls || 0);
    $("kpi-today-avg-time").textContent = `平均耗时: ${(data.avg_duration_ms || 0).toFixed(0)} ms`;

    $("kpi-total-tokens").textContent = formatNumber(totalTokens);
    $("kpi-total-sub").textContent = `历史调用: ${formatNumber(data.total_calls || 0)} 次 (~${sym}${totalCost.toFixed(4)})`;

    const cachedTokens = data.total_cached_tokens || 0;
    const hitRate = totalTokens > 0 ? ((cachedTokens / totalTokens) * 100).toFixed(1) : "0.0";
    $("kpi-cached-tokens").textContent = formatNumber(cachedTokens);
    $("kpi-cached-rate").textContent = `缓存命中率: ${hitRate}%`;
  } catch (err) {
    console.error("Failed to load overview:", err);
    $("kpi-today-tokens").textContent = "0";
    $("kpi-today-sub").textContent = "预估费用: -";
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
    const [modelsRes, callersRes, overviewRes] = await Promise.all([
      apiGet("models").catch(() => ({ models: [] })),
      apiGet("callers").catch(() => ({ callers: [] })),
      apiGet("overview").catch(() => ({ total_tokens: 0 })),
    ]);

    const models = modelsRes.models || [];
    const callers = callersRes.callers || [];
    const totalTokens = overviewRes.total_tokens || 1;

    // 渲染环形饼图
    renderModelPieChart(models);

    // 渲染模型排行表
    const modelsTbody = $("models-table-body");
    if (models.length === 0) {
      modelsTbody.innerHTML = `<tr><td colspan="4" class="text-center" style="color: var(--text-muted); padding: 24px;">暂无模型调用记录</td></tr>`;
    } else {
      modelsTbody.innerHTML = models.slice(0, 10).map((m) => {
        const pct = ((m.total_tokens / totalTokens) * 100).toFixed(1);
        return `
          <tr>
            <td><strong>${m.model}</strong></td>
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
      callersTbody.innerHTML = `<tr><td colspan="4" class="text-center" style="color: var(--text-muted); padding: 24px;">暂无来源调用记录</td></tr>`;
    } else {
      callersTbody.innerHTML = callers.slice(0, 10).map((c) => {
        const typeBadge = c.caller_type === "plugin" ? "badge-purple" : "badge-gray";
        return `
          <tr>
            <td><strong>${c.caller_name}</strong></td>
            <td><span class="badge ${typeBadge}">${c.caller_type}</span></td>
            <td>${formatNumber(c.total_tokens)}</td>
            <td>${formatNumber(c.call_count)}</td>
          </tr>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Failed to load models/callers:", err);
    $("models-table-body").innerHTML = `<tr><td colspan="4" class="text-center">加载失败</td></tr>`;
    $("callers-table-body").innerHTML = `<tr><td colspan="4" class="text-center">加载失败</td></tr>`;
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
      },
      cutout: "60%",
    },
  });
}

async function loadTrend() {
  try {
    const data = await apiGet("trend", { days: 14 });
    const canvas = $("trendLineChart");
    if (!canvas || typeof Chart === "undefined") return;
    const ctx = canvas.getContext("2d");

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
        plugins: {
          legend: { position: "top" },
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
    const res = await apiGet("records", {
      page: currentPage,
      page_size: 15,
      keyword: keyword,
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
      const modeBadge = r.is_streaming ? '<span class="badge badge-blue">流式</span>' : '<span class="badge badge-gray">常规</span>';
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
  const refreshBtn = $("btn-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      refreshAll();
    });
  }

  const exportBtn = $("btn-export");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const bridge = getBridge();
      if (bridge && typeof bridge.download === "function") {
        bridge.download("export-csv", {}, `token_records_${Date.now()}.csv`);
      } else {
        window.open(`/api/v1/plugins/extensions/${PLUGIN_NAME}/export-csv`, "_blank");
      }
    });
  }

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
