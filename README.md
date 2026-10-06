# AstrBot 全局 Token 用量统计与可视化看板 (astrbot_plugin_token_tracker)

专为 AstrBot 量身定制的全局 LLM Token 用量捕获、多维度分类统计与 **AstrBot 原生内置 WebUI 插件页面**。

## ✨ 特性亮点

1. **全局无死角捕获**：
   - 采用底层 AOP 切面拦截 Provider，覆盖**主对话、原生 Agent、以及所有第三方插件**发起的 LLM 请求。
   - 无论插件是通过 `context.get_using_provider()` 还是直调 `provider.text_chat()`，均可被完整拦截记录。
2. **多维智能归因**：
   - **按模型分类统计**：输入（Prompt）、输出（Completion）、缓存命中（Cached）以及 Total Tokens。
   - **调用源智能识别**：分析运行时调用栈（Call Stack），自动识别是系统主对话还是具体某个第三方插件（如 `astrbot_plugin_meme_manager`、`astrbot_plugin_astrbot_enhance_mode` 等）。
3. **流式与非流式兼顾**：
   - 完整支持流式传输（Streaming）中各模型厂商返回的 Usage 对象。
   - 针对部分大模型在流式模式下未回传 usage 的特殊情况，内置中英文字符轻量估算引擎，自动兜底标记。
4. **原生内置 WebUI 仪表盘 (已接入 AstrBot 管理面板)**：
   - **免配置独立端口**：完全复用 AstrBot 主面板，直接在左侧菜单「插件页面」->「Token 用量看板」内查看。
   - **免重复登录**：无缝继承 AstrBot 管理员会话与权限，随开随用，适配深色/浅色主题。
   - **KPI 核心指标看板**：今日 Token、历史累计、平均耗时、调用频次与预估折算费用。
   - **丰富图表**：各模型消耗占比饼图（Chart.js）、近 14 天用量走势图（按 Prompt / Completion 堆叠）。
   - **模型与插件排行榜**：直观对比各模型用量分布、各插件活跃程度与 Token 占用。
   - **调用流水账明细**：支持关键词过滤、模型筛选、调用源筛选与分页浏览。
   - **一键导出 CSV**：支持导出全量历史调用记录供离线分析。
5. **便捷 Bot 查询指令**：
   - 在聊天群聊或私聊中支持 `/token`、`/tokens` 快捷查询用量简报。

---

## 🖥️ WebUI 访问方式

1. 打开并登录 AstrBot 主管理面板（例如 `http://<服务器IP>:6185`）
2. 在左侧主导航栏中展开 **「插件页面」**
3. 点击 **「Token 用量看板」** 即可直接体验完整可视化大屏！

---

## 🛠️ 指令说明

| 指令 | 说明 | 权限 |
| :--- | :--- | :--- |
| `/token` 或 `/tokens` | 查看今日与累计用量概况、Top3 模型与插件消耗、WebUI 引导 | 所有用户 |
| `/token webui` | 获取 AstrBot 内置 WebUI 看板访问指引 | 所有用户 |
| `/token today` | 查看今日 Token 消耗细分数据 | 所有用户 |
| `/token top` | 查看模型与插件消耗排行榜 | 所有用户 |
| `/token reset confirm` | 危险操作：清空所有历史统计记录 | 管理员 |
| `/token help` | 查看指令帮助列表 | 所有用户 |

---

## ⚙️ 配置说明

可在 AstrBot 管理面板或插件配置文件中按需调整：

```json
{
  "tracker": {
    "enable": true,
    "record_streaming": true,
    "estimate_when_missing": true,
    "currency_symbol": "¥"
  }
}
```
