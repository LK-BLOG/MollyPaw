/* MollyPaw - Frontend App Logic */
(function () {
  "use strict";

  // Configure marked
  if (typeof marked !== "undefined") {
    marked.setOptions({
      breaks: true,
      gfm: true,
    });
  }

  // 页面由同一个 HTTP 服务提供，所以默认走相对路径。
  // 只有从 file:// 直接打开时才需要写死地址（历史行为，保留兜底）。
  var API_BASE = (location.protocol === "file:")
    ? "http://127.0.0.1:18765"
    : "";

  // ---- i18n Translations ----
  var translations = {
    en: {
      max_tokens_label: "Max output tokens",
      max_tokens_ph: "Leave empty = let the server decide (recommended)",
      max_tokens_hint: "Empty is safest. If set, it must be below the model's context limit or the API returns 400.",
      relay_server_label: "Relay server",
      relay_server_official: "Official relay (recommended)",
      relay_server_official_hint: "Works out of the box — no server to run",
      relay_server_custom: "Self-hosted relay",
      relay_server_custom_hint: "Pick this if you run your own",
      relay_url_hint: "Your own relay URL; must start with ws:// or wss://",
      relay_stop: "Stop remote access",
      relay_stop_short: "Stop",
      relay_show: "Show",
      relay_hide: "Hide",
      relay_scan_hint: "Scan this with the phone app — no key typing needed.",
      relay_code_manual: "Can't scan? Copy the pairing code",
      relay_code_warning: "The pairing code is a temporary key. Don't screenshot it into group chats. Valid 15 minutes, single use.",
      relay_qr_failed: "QR generation failed. Use the pairing code below instead:",
      relay_revoke_all: "Revoke all",
      relay_revoke_all_hint: "Changing the key only disconnects old devices — use this to actually revoke them",
      relay_revoke_all_confirm: "Revoke every paired device? They will all need to pair again.",
      relay_revoke_all_done: "Revoked {n} device(s).",
      relay_cancel: "Cancel",
      relay_copied: "Copied to clipboard.",
      relay_copy_failed: "Copy failed, select and copy manually.",
      relay_need_psk: "Set a connection key first.",
      relay_nothing_to_copy: "No key to copy yet.",
      relay_psk_generated: "Generated and selected — press Ctrl+C to copy.",
      relay_starting: "Starting...",
      relay_stopping: "Stopping...",
      relay_working: "Working...",
      relay_copy: "Copy",
      relay_psk_gen: "Generate one",
      relay_psk_save: "Save key",
      stop: "Stop",
      stopping: "Stopping...",
      stopped: "Stopped.",
      stop_failed: "Could not stop: ",
      busy_hint: "Another round is still running. Stop it first.",
      live: "Live",
      polling: "Polling",
      update_title: "Update available",
      update_notes: "What's new",
      update_now: "Update now",
      update_later: "Later",
      update_downloading: "Downloading update",
      update_ready: "Update downloaded",
      update_restart: "Restart & install",
      update_failed: "Update failed",
      update_dev_mode: "Running from source can't self-update; use git pull",
      tc_history_args: "Arguments",
      tc_history_result: "Result",
      tc_history_expand: "Expand",
      tc_history_collapse: "Collapse",
      update_restarting: "Restarting…",
      kbd_hint_insert: "queues a message while AI is working",
      kbd_hint_stop: "Press Esc twice to stop AI",
      queue_pending: "{n} queued — sent when this round ends",
      relay_via_proxy: "Proxy",
      relay_direct: "Direct",
      relay_pair_guard: "Turn on remote access first and wait until it says Connected, then add a device. A pairing code generated while the relay is offline is dead.",
      relay_title: "Remote Access",
      relay_desc: "Connect your phone to this computer over an encrypted channel.",
      relay_enable: "Enable remote access",
      relay_url: "Relay address",
      relay_psk: "Connection key",
      relay_psk_ph: "At least 16 chars, with upper, lower and digit",
      relay_psk_saved: "Key saved (leave blank to keep)",
      relay_room: "Room",
      relay_state: "State",
      relay_add_device: "Add device",
      relay_add_observer: "Add read-only device",
      relay_pin_hint: "Type this code on your phone. Valid for 5 minutes.",
      relay_pin_ttl: "Expires in",
      relay_devices: "Paired devices",
      relay_no_devices: "No devices paired yet.",
      relay_revoke: "Revoke",
      relay_remove: "Remove",
      relay_role_app: "Control",
      relay_role_observer: "Read-only",
      relay_audit: "File access log",
      relay_audit_empty: "No file access recorded.",
      relay_connected: "Connected",
      relay_disconnected: "Disconnected",
      relay_reconnecting: "Reconnecting",
      relay_stopped: "Off",
      relay_error: "Error",
      relay_last_seen: "Last seen",
      relay_added: "Added",
      new_chat: "New Chat",
      no_conversations: "No conversations yet",
      settings: "Settings",
      welcome_title: "Hello, I'm MollyPaw!",
      welcome_sub: "Your AI, right at your paw.",
      chip1: "Write a Python script",
      chip2: "Explain PyWebView",
      chip3: "What can you do?",
      input_placeholder: "Ask MollyPaw anything...",
      hint: "MollyPaw Beta 0.0.0.1.5",
      send: "Send",
      balance_label: "Balance: ",
      balance_unavailable: "Balance unavailable",
      balance_no_endpoint: "No balance endpoint for this provider",
      balance_unsupported: "This provider doesn't expose balance",
      balance_no_field: "Balance response not recognised",
      balance_no_key: "Add an API key to see balance",
      cost_label: "Cost: ",
      thinking_depth: "Reasoning",
      thinking_none: "None",
      thinking_low: "Low",
      thinking_medium: "Medium",
      thinking_high: "High",
      thinking_max: "Max",
      approval_short_dangerous: "Approve for me",
      approval_short_all: "Ask for approval",
      approval_short_full: "Full access",
      msg_you: "You",
      msg_mollypaw: "MollyPaw",
      typing: "MollyPaw is thinking...",
      error_prefix: "Error: ",
      unknown_error: "Unknown error",
      tc_running: "Running...",
      tc_done: "Done",
      tc_error: "Failed",
      tc_rejected: "Rejected by user",
      danger_safe: "Safe",
      danger_moderate: "Moderate",
      danger_dangerous: "\u26A0\uFE0F Dangerous",
      settings_title: "Settings",
      provider_label: "Provider",
      protocol_label: "API Protocol",
      protocol_chat: "OpenAI Chat Completions",
      protocol_responses: "OpenAI Responses",
      fetch_models: "Fetch models",
      model_fetching: "Fetching models...",
      model_fetch_failed: "Model fetch failed",
      manual_model_placeholder: "Enter model ID manually",
      api_key_label: "API Key",
      base_url_label: "Base URL",
      model_label: "Model",
      temp_label: "Temperature",
      approval_mode_label: "Tool Approval Mode",
      approval_all: "Prompt for all tools",
      approval_dangerous: "Prompt dangerous only",
      approval_full: "Full access (no prompts)",
      save: "Save",
      cancel: "Cancel",
      saved: "Saved!",
      config_failed: "Failed to load config",
      approval_title: "Approval Required",
      approval_tool: "Tool",
      approval_args: "Arguments",
      approval_danger: "Danger Level",
      approval_approve: "Approve",
      approval_reject: "Reject",
      approval_always: "Always approve in this session",
      chip_prompt1: "Help me write a Python script to sort files by extension",
      chip_prompt2: "Explain how PyWebView works under the hood",
      chip_prompt3: "What can you do as an AI agent?",
      conv_unnamed: "Unnamed",
      conv_delete: "Delete",
    },
    zh: {
      max_tokens_label: "最大输出 tokens",
      max_tokens_ph: "留空 = 由服务端决定（推荐）",
      max_tokens_hint: "留空最安全。填了就必须小于模型上下文上限，否则上游会报 400。",
      relay_server_label: "中继服务器",
      relay_server_official: "官方中继（推荐）",
      relay_server_official_hint: "开箱即用，不用自己搭服务器",
      relay_server_custom: "自建中继",
      relay_server_custom_hint: "你有自己的服务器时选这个",
      relay_url_hint: "填你自己部署的中继地址，需以 ws:// 或 wss:// 开头",
      relay_stop: "关闭远程互联",
      relay_stop_short: "关闭",
      relay_show: "显示",
      relay_hide: "隐藏",
      relay_scan_hint: "用手机 App 扫这个码就能连上，不用手输密钥。",
      relay_code_manual: "手机扫不了？手动复制配对码",
      relay_code_warning: "配对码等于临时钥匙，别截图发群里。15 分钟内有效，用过一次就作废。",
      relay_qr_failed: "二维码生成失败，请用下面的配对码手动连接：",
      relay_revoke_all: "全部吊销",
      relay_revoke_all_hint: "换密钥后旧设备只是连不上、并没有被清退，要彻底断了点这里",
      relay_revoke_all_confirm: "确定要吊销全部已配对设备吗？它们都需要重新扫码配对。",
      relay_revoke_all_done: "已吊销 {n} 台设备。",
      relay_cancel: "取消",
      relay_copied: "已复制到剪贴板。",
      relay_copy_failed: "复制失败，请手动选中复制。",
      relay_need_psk: "先填一个连接密钥再开启。",
      relay_nothing_to_copy: "还没有密钥可复制。",
      relay_psk_generated: "已生成，已自动选中，可直接 Ctrl+C 复制。",
      relay_starting: "正在开启...",
      relay_stopping: "正在关闭...",
      relay_working: "处理中...",
      relay_copy: "复制",
      relay_psk_gen: "随机生成一个",
      relay_psk_save: "保存密钥",
      busy_hint: "还有一轮在跑，先点停止。",
      live: "实时",
      polling: "轮询",
      relay_add_device: "添加设备",
      relay_add_observer: "添加只读设备",
      relay_added: "添加于",
      relay_audit: "文件访问日志",
      relay_audit_empty: "没有文件访问记录。",
      relay_connected: "已连接",
      relay_desc: "让手机通过加密通道连上这台电脑。",
      relay_devices: "已配对设备",
      relay_disconnected: "已断开",
      relay_enable: "开启远程互联",
      relay_error: "出错",
      relay_last_seen: "最后在线",
      relay_no_devices: "还没有配对过设备。",
      relay_pin_hint: "在手机上输入这串码。5 分钟内有效。",
      relay_pin_ttl: "剩余",
      relay_psk: "连接密钥",
      relay_psk_ph: "至少 16 位，含大写、小写、数字",
      relay_psk_saved: "已保存（留空则不改）",
      relay_reconnecting: "重连中",
      relay_remove: "删除",
      relay_revoke: "吊销",
      relay_role_app: "控制端",
      relay_role_observer: "只读端",
      relay_room: "房间",
      relay_state: "状态",
      relay_stopped: "已关闭",
      update_title: "有新版本可用",
      update_notes: "更新内容",
      update_now: "立即更新",
      update_later: "稍后再说",
      update_downloading: "正在下载新版本",
      update_ready: "新版本已下载好",
      update_restart: "重启并安装",
      update_failed: "更新失败",
      update_dev_mode: "源码运行不能自替换，请用 git pull 更新",
      tc_history_args: "参数",
      tc_history_result: "结果",
      tc_history_expand: "展开",
      tc_history_collapse: "收起",
      update_restarting: "正在重启…",
      kbd_hint_insert: "AI 工作时插入消息",
      kbd_hint_stop: "连按两次 Esc 停止 AI",
      queue_pending: "已排队 {n} 条，本轮结束自动发送",
      relay_via_proxy: "代理",
      relay_direct: "直连",
      relay_pair_guard: "先点上面的「开启远程互联」，等状态变成「已连接」，再添加设备。中继没连上时生成的配对码是死的。",
      relay_title: "远程互联",
      relay_url: "中继地址",
      stop: "停止",
      stop_failed: "停不下来：",
      stopped: "已停止。",
      stopping: "正在停...",
      new_chat: "\u65B0\u5EFA\u5BF9\u8BDD",
      no_conversations: "\u8FD8\u6CA1\u6709\u5BF9\u8BDD\u8BB0\u5F55",
      settings: "\u8BBE\u7F6E",
      welcome_title: "\u4F60\u597D\uFF0C\u6211\u662F MollyPaw\uFF01",
      welcome_sub: "\u4F60\u7684 AI\uFF0C\u5C31\u5728\u4F60\u7684\u722A\u5B50\u91CC\u3002",
      chip1: "\u5199\u4E00\u4E2A Python \u811A\u672C",
      chip2: "\u89E3\u91CA PyWebView \u5DE5\u4F5C\u539F\u7406",
      chip3: "\u4F60\u80FD\u505A\u4EC0\u4E48\uFF1F",
      input_placeholder: "\u95EE MollyPaw \u4EFB\u4F55\u95EE\u9898...",
      hint: "MollyPaw Beta 0.0.0.1.5",
      send: "发送",
      balance_label: "余额：",
      balance_unavailable: "余额暂不可用",
      balance_no_endpoint: "这个服务商没有余额接口",
      balance_unsupported: "这个服务商不提供余额查询",
      balance_no_field: "余额返回里没认出来的字段",
      balance_no_key: "先填 API Key 才能看余额",
      cost_label: "本轮消耗：",
      thinking_depth: "思考深度",
      thinking_none: "无",
      thinking_low: "低",
      thinking_medium: "中",
      thinking_high: "高",
      thinking_max: "最高",
      approval_short_dangerous: "帮我批准",
      approval_short_all: "请求批准",
      approval_short_full: "完全访问",
      msg_you: "\u4F60",
      msg_mollypaw: "MollyPaw",
      typing: "MollyPaw \u6B63\u5728\u601D\u8003...",
      error_prefix: "\u9519\u8BEF\uFF1A",
      unknown_error: "\u672A\u77E5\u9519\u8BEF",
      tc_running: "\u6267\u884C\u4E2D...",
      tc_done: "\u5B8C\u6210",
      tc_error: "\u6267\u884C\u5931\u8D25",
      tc_rejected: "\u5DF2\u88AB\u7528\u6237\u62D2\u7EDD",
      danger_safe: "\u5B89\u5168",
      danger_moderate: "\u4E2D\u7B49",
      danger_dangerous: "\u26A0\uFE0F \u5371\u9669",
      settings_title: "\u8BBE\u7F6E",
      provider_label: "\u4F9B\u5E94\u5546",
      protocol_label: "API \u534F\u8BAE",
      protocol_chat: "OpenAI Chat Completions",
      protocol_responses: "OpenAI Responses",
      fetch_models: "\u62C9\u53D6\u6A21\u578B",
      model_fetching: "\u6B63\u5728\u62C9\u53D6\u6A21\u578B...",
      model_fetch_failed: "\u6A21\u578B\u62C9\u53D6\u5931\u8D25",
      manual_model_placeholder: "\u624B\u52A8\u8F93\u5165\u6A21\u578B ID",
      api_key_label: "API Key",
      base_url_label: "Base URL",
      model_label: "\u6A21\u578B",
      temp_label: "\u6E29\u5EA6",
      approval_mode_label: "\u5DE5\u5177\u5BA1\u6279\u6A21\u5F0F",
      approval_all: "\u6240\u6709\u5DE5\u5177\u90FD\u63D0\u793A",
      approval_dangerous: "\u4EC5\u5371\u9669\u5DE5\u5177\u63D0\u793A",
      approval_full: "\u5B8C\u5168\u8BBF\u95EE\uFF08\u65E0\u63D0\u793A\uFF09",
      save: "\u4FDD\u5B58",
      cancel: "\u53D6\u6D88",
      saved: "\u5DF2\u4FDD\u5B58\uFF01",
      config_failed: "\u52A0\u8F7D\u914D\u7F6E\u5931\u8D25",
      approval_title: "\u9700\u8981\u4F60\u7684\u6279\u51C6",
      approval_tool: "\u5DE5\u5177",
      approval_args: "\u53C2\u6570",
      approval_danger: "\u5371\u9669\u7B49\u7EA7",
      approval_approve: "\u6279\u51C6",
      approval_reject: "\u62D2\u7EDD",
      approval_always: "\u672C\u6B21\u4F1A\u8BDD\u59CB\u7EC8\u6279\u51C6",
      chip_prompt1: "\u5E2E\u6211\u5199\u4E00\u4E2A\u6309\u6269\u5C55\u540D\u6392\u5E8F\u6587\u4EF6\u7684 Python \u811A\u672C",
      chip_prompt2: "\u89E3\u91CA\u4E00\u4E0B PyWebView \u7684\u5DE5\u4F5C\u539F\u7406",
      chip_prompt3: "\u4F60\u80FD\u505A\u4EC0\u4E48\uFF1F",
      conv_unnamed: "\u672A\u547D\u540D\u5BF9\u8BDD",
      conv_delete: "\u5220\u9664",
    }
  };

  var currentLang = localStorage.getItem("mollypaw_lang") || "zh";
  var currentConvId = null;

  function t(key) {
    var lang = translations[currentLang] || translations.en;
    return lang[key] || translations.en[key] || key;
  }

  function dangerLabel(level) {
    if (level === "safe") return t("danger_safe");
    if (level === "moderate") return t("danger_moderate");
    if (level === "dangerous") return t("danger_dangerous");
    return level;
  }

  // ---- Apply translations to all [data-i18n] elements ----
  function applyTranslations() {
    document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";
    var els = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var key = el.getAttribute("data-i18n");
      var text = t(key);
      var attrTarget = el.getAttribute("data-i18n-attr");
      if (attrTarget) {
        el.setAttribute(attrTarget, text);
      } else {
        el.textContent = text;
      }
    }
    // Update prompt chip translated prompts
    var chips = document.querySelectorAll(".prompt-chip[data-i18n-prompt]");
    for (var j = 0; j < chips.length; j++) {
      var pKey = chips[j].getAttribute("data-i18n-prompt");
      if (pKey) chips[j].setAttribute("data-prompt", t(pKey));
    }
    // Update lang toggle label
    var langToggle = document.getElementById("lang-toggle");
    if (langToggle) {
      langToggle.textContent = currentLang === "zh" ? "EN" : "CN";
      langToggle.title = currentLang === "zh" ? "Switch to English" : "\u5207\u6362\u4E3A\u4E2D\u6587";
    }
  }

  // ---- DOM References (null-safe) ----
  function $(id) { return document.getElementById(id); }

  var messagesEl     = $("messages");
  var welcomeEl      = $("welcome-screen");
  var userInput      = $("user-input");
  var sendBtn        = $("send-btn");
  var chatHistory    = $("chat-history");
  var isLoading = false;
  // 连按两次 Esc 停止：记录上一次 Esc 的时间
  var lastEscapeAt = 0;
  // AI 工作时按 Enter 发的消息排这里，本轮一结束立刻发出去
  var pendingQueue = [];

  var approvalBtn    = $("approval-btn");
  var approvalLabelEl = $("approval-label");
  var approvalMenu   = $("approval-menu");
  var modelMenuBtn   = $("model-menu-btn");
  var thinkingMenu   = $("thinking-menu");
  var thinkingSlider = $("thinking-slider");
  var thinkingCurrent = $("thinking-current");
  var thinkingModel  = $("thinking-model");
  var thinkingThumb  = $("thinking-thumb");
  var balanceStatus  = $("balance-status");
  var thinkingLevels = ["none", "low", "medium", "high", "max"];
  var approvalModes  = ["prompt_dangerous", "prompt_all", "full_access"];

  function approvalLabel(mode) {
    if (mode === "prompt_all") return t("approval_short_all");
    if (mode === "full_access") return t("approval_short_full");
    return t("approval_short_dangerous");
  }

  function setApprovalMode(mode) {
    if (approvalModes.indexOf(mode) < 0) mode = "prompt_dangerous";
    if (approvalBtn) {
      approvalBtn.dataset.mode = mode;
      approvalLabelEl.textContent = approvalLabel(mode);
    }
    document.querySelectorAll("[data-approval-mode]").forEach(function (option) {
      option.classList.toggle("active", option.dataset.approvalMode === mode);
    });
    document.querySelectorAll("[data-mode-icon]").forEach(function (icon) {
      icon.classList.toggle("active", icon.dataset.modeIcon === mode);
    });
  }

  var thinkingFrame = 0;

  function updateThinkingThumb(index) {
    if (!thinkingThumb) return;
    var last = Math.max(1, thinkingLevels.length - 1);
    var progress = Math.max(0, Math.min(index, last)) / last;
    var offset = (1 - progress * 2) * 15;
    thinkingThumb.style.left = "calc(" + (progress * 100).toFixed(3) + "% + " + offset.toFixed(2) + "px)";
    var wrap = thinkingSlider ? thinkingSlider.closest(".thinking-slider-wrap") : null;
    if (wrap) {
      wrap.style.setProperty("--slider-progress", (progress * 100).toFixed(3) + "%");
      wrap.classList.toggle("is-max", index === last);
    }
  }

  function previewThinkingLevel(level) {
    if (thinkingFrame) cancelAnimationFrame(thinkingFrame);
    thinkingFrame = requestAnimationFrame(function () {
      thinkingFrame = 0;
      var index = thinkingLevels.indexOf(level);
      if (index < 0) { level = "none"; index = 0; }
      updateThinkingThumb(index);
      if (thinkingCurrent) thinkingCurrent.textContent = t("thinking_" + level);
      document.querySelectorAll(".thinking-dots span").forEach(function (dot, dotIndex) {
        dot.classList.toggle("active", dotIndex <= index);
      });
      if (thinkingModel) thinkingModel.textContent = formatModelName(modelMenuBtn ? modelMenuBtn.dataset.model : "");
    });
  }

  function setThinkingLevel(level, persist) {
    var index = thinkingLevels.indexOf(level);
    if (index < 0) { level = "none"; index = 0; }
    localStorage.setItem("mollypaw_thinking", level);
    if (thinkingSlider && Number(thinkingSlider.value) !== index) thinkingSlider.value = String(index);
    updateThinkingThumb(index);
    if (thinkingCurrent) thinkingCurrent.textContent = t("thinking_" + level);
    document.querySelectorAll(".thinking-dots span").forEach(function (dot, dotIndex) {
      dot.classList.toggle("active", dotIndex <= index);
    });
    updateModelButton();
    if (persist) postAPI("/api/thinking_level", { level: level });
  }

  function formatModelName(model) {
    if (!model) return t("model_label");
    var names = { deepseek: "DeepSeek", openai: "OpenAI", gpt: "GPT", qwen: "Qwen", glm: "GLM", kimi: "Kimi", grok: "Grok", llm: "LLM" };
    return String(model).split("/").pop().split(/[-_\s]+/).filter(Boolean).map(function (part) {
      var lower = part.toLowerCase();
      if (names[lower]) return names[lower];
      if (/^v\d/i.test(part)) return part.charAt(0).toUpperCase() + part.slice(1);
      return part.charAt(0).toUpperCase() + part.slice(1);
    }).join(" ");
  }

  function setContextWindowInput(tokens) {
    var input = $("cfg-context-window");
    var unit = $("cfg-context-unit");
    if (!input || !unit) return;
    var value = Number(tokens);
    if (!Number.isFinite(value) || value <= 0) value = 200000;
    if (value >= 1000000) {
      input.value = String(value / 1000000);
      unit.value = "M";
    } else {
      input.value = String(value / 1000);
      unit.value = "K";
    }
  }

  function readContextWindowInput() {
    var input = $("cfg-context-window");
    var unit = $("cfg-context-unit");
    var amount = input ? Number(input.value) : NaN;
    if (!Number.isFinite(amount) || amount <= 0) return null;
    var multiplier = unit && unit.value === "M" ? 1000000 : 1000;
    return Math.round(amount * multiplier);
  }

  function updateModelButton() {
    if (!modelMenuBtn) return;
    var model = formatModelName(modelMenuBtn.dataset.model);
    var level = localStorage.getItem("mollypaw_thinking") || "none";
    modelMenuBtn.textContent = model + "  " + t("thinking_" + level);
    if (thinkingModel) thinkingModel.textContent = model;
  }

  // ---- Helpers ----
  function scrollToBottom() {
    var c = $("chat-container");
    if (c) c.scrollTop = c.scrollHeight;
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
    if (messagesEl) messagesEl.classList.add("has-messages");
  }

  function showWelcome() {
    if (welcomeEl) welcomeEl.style.display = "";
    if (messagesEl) {
      messagesEl.innerHTML = "";
      messagesEl.classList.remove("has-messages");
    }
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function postAPI(path, body) {
    return fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) { return r.json(); });
  }

  function getAPI(path) {
    return fetch(API_BASE + path).then(function (r) { return r.json(); });
  }

  function pollEvents() {
    getAPI("/api/events").then(function (result) {
      (result.events || []).forEach(function (event) {
        if (typeof window[event.name] === "function") window[event.name](event.payload);
      });
    }).catch(function () {}).finally(function () {
      setTimeout(pollEvents, 250);
    });
  }

  // ---- 实时通道：WS 优先，失败降级到轮询 ----
  //
  // 后端仍然是 250ms 轮询 /api/events 的模式，前端先试 WebSocket，
  // 连不上就继续用轮询（所以老环境不会退化）。
  // 现在其实还没开 WS 端点，这里先把骨架和状态显示做出来。
  var wsState = "polling";
  var wsRetry = 0;

  function setTransport(state) {
    wsState = state;
    var el = document.getElementById("transportState");
    if (el) {
      el.textContent = state === "ws" ? "实时" : "轮询";
      el.className = "transport-badge " + (state === "ws" ? "on" : "off");
    }
  }

  function tryWebSocket() {
    if (!window.WebSocket) { setTransport("polling"); return; }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws;
    try {
      ws = new WebSocket(proto + "//" + location.host + "/ws");
    } catch (e) {
      setTransport("polling");
      return;
    }
    var settled = false;
    ws.onopen = function () {
      settled = true;
      wsRetry = 0;
      setTransport("ws");
    };
    ws.onmessage = function (ev) {
      try {
        var event = JSON.parse(ev.data);
        if (typeof window[event.name] === "function") window[event.name](event.payload);
      } catch (e) {}
    };
    ws.onclose = function () {
      setTransport("polling");
      if (!settled) {
        // 说明服务器没这个端点，别一直重试
        wsRetry += 1;
        if (wsRetry > 2) return;
      }
      setTimeout(tryWebSocket, Math.min(30000, 1000 * Math.pow(2, wsRetry)));
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }

  // ---- Sidebar: Conversation List ----
  function loadConversations() {
    getAPI("/api/conversations");
  }

  function renderConversationList(convs) {
    if (!chatHistory) return;
    chatHistory.innerHTML = "";
    if (!convs || convs.length === 0) {
      var empty = document.createElement("div");
      empty.className = "history-empty";
      empty.setAttribute("data-i18n", "no_conversations");
      empty.textContent = t("no_conversations");
      chatHistory.appendChild(empty);
      return;
    }
    for (var i = 0; i < convs.length; i++) {
      var conv = convs[i];
      var item = document.createElement("div");
      item.className = "history-item" + (conv.id === currentConvId ? " active" : "");
      item.setAttribute("data-conv-id", conv.id);

      var titleSpan = document.createElement("span");
      titleSpan.className = "history-item-title";
      titleSpan.textContent = conv.title || t("conv_unnamed");
      item.appendChild(titleSpan);

      var delBtn = document.createElement("button");
      delBtn.className = "history-item-delete";
      delBtn.textContent = "\u00D7";
      delBtn.title = t("conv_delete");
      delBtn.setAttribute("data-conv-id", conv.id);
      delBtn.addEventListener("click", (function (id) {
        return function (e) {
          e.stopPropagation();
          if (confirm(t("conv_delete") + "?")) {
            postAPI("/api/conversations/delete", { id: id });
            if (currentConvId === id) {
              currentConvId = null;
              showWelcome();
            }
          }
        };
      })(conv.id));
      item.appendChild(delBtn);

      item.addEventListener("click", (function (id) {
        return function () {
          postAPI("/api/conversations/load", { id: id });
        };
      })(conv.id));

      chatHistory.appendChild(item);
    }
  }

  function highlightActiveConv() {
    var items = document.querySelectorAll(".history-item");
    for (var i = 0; i < items.length; i++) {
      if (items[i].getAttribute("data-conv-id") === currentConvId) {
        items[i].classList.add("active");
      } else {
        items[i].classList.remove("active");
      }
    }
  }

  // ---- Tool Call Indicators ----
  var pendingApprove = null;

  // 唯一的工具调用卡片渲染入口。
  //
  // 实时（showToolCall）和历史（renderToolCallHistory）必须共用它 ——
  // 早先两处各写一套样式，结果同一段对话刷新前后长得完全不一样。
  //
  // opts: { id, name, args, danger, result, rejected, running }
  function renderToolCallCard(opts) {
    var div = document.createElement("div");
    div.className = "tool-call-indicator";
    if (opts.id) div.id = "tool-call-" + opts.id;

    var argsStr = "";
    try {
      argsStr = (typeof opts.args === "string")
        ? opts.args
        : JSON.stringify(opts.args === undefined ? {} : opts.args, null, 2);
    } catch (e) { argsStr = String(opts.args); }
    if (argsStr.length > 400) argsStr = argsStr.substring(0, 400) + "…";

    var dangerHtml = "";
    if (opts.danger) {
      dangerHtml = '<span class="tc-danger tc-danger-' + opts.danger + '">'
        + escapeHtml(dangerLabel(opts.danger)) + '</span>';
    }

    var html = '<div class="tc-header">'
      + '<span class="tc-icon">\uD83D\uDD27</span>'
      + '<span class="tc-name">' + escapeHtml(opts.name || "tool") + '</span>'
      + dangerHtml
      + '<span class="tc-toggle">' + t("tc_history_expand") + '</span>'
      + '</div>'
      + '<pre class="tc-args">' + escapeHtml(argsStr) + '</pre>';

    if (opts.result !== undefined && opts.result !== null && opts.result !== "") {
      var resText = String(opts.result);
      if (resText.length > 400) resText = resText.substring(0, 400) + "…";
      html += '<pre class="tc-result">' + escapeHtml(resText) + '</pre>';
    }

    var statusClass = "tc-running";
    var statusText = t("tc_running");
    if (opts.rejected) {
      statusClass = "tc-rejected";
      statusText = "\u274C " + t("tc_rejected");
    } else if (opts.result !== undefined && opts.result !== null) {
      var failed = /^Error/i.test(String(opts.result));
      statusClass = failed ? "tc-error" : "tc-done";
      statusText = failed
        ? "\u274C " + t("tc_error")
        : "\u2705 " + t("tc_done");
    }
    html += '<div class="tc-status ' + statusClass + '">' + statusText + '</div>';

    div.innerHTML = html;
    div.addEventListener("click", function () {
      div.classList.toggle("expanded");
      var toggle = div.querySelector(".tc-toggle");
      if (toggle) {
        toggle.textContent = div.classList.contains("expanded")
          ? t("tc_history_collapse") : t("tc_history_expand");
      }
    });
    return div;
  }

  function showToolCall(info) {
    hideWelcome();
    var div = renderToolCallCard({
      id: info.request_id,
      name: info.name,
      args: info.args,
      danger: info.danger_level,
      running: true,
    });
    if (messagesEl) messagesEl.appendChild(div);
    scrollToBottom();
  }

  function updateToolResult(requestId, result, success) {
    var el = document.getElementById("tool-call-" + requestId);
    if (!el) return;
    var status = el.querySelector(".tc-status");
    if (status) {
      status.className = "tc-status " + (success ? "tc-done" : "tc-error");
      status.textContent = success ? "\u2705 " + t("tc_done") : "\u274C " + (result || t("tc_error"));
    }
    // 实时那一轮也要能看到结果正文，别只留一句状态
    var text = String(result || "");
    if (text && !el.querySelector(".tc-result")) {
      if (text.length > 400) text = text.substring(0, 400) + "…";
      var pre = document.createElement("pre");
      pre.className = "tc-result";
      pre.textContent = text;
      var args = el.querySelector(".tc-args");
      if (args && args.parentNode) args.parentNode.insertBefore(pre, args.nextSibling);
      else el.appendChild(pre);
    }
  }

  function showToolRejected(requestId) {
    var el = document.getElementById("tool-call-" + requestId);
    if (!el) return;
    var status = el.querySelector(".tc-status");
    if (status) {
      status.className = "tc-status tc-rejected";
      status.textContent = "\u274C " + t("tc_rejected");
    }
  }

  // ---- Approval Modal ----
  function showApprovalModal(info) {
    var overlay = $("approval-overlay");
    if (!overlay) return Promise.resolve(false);
    var tn = $("approval-tool-name");
    if (tn) tn.textContent = info.name;

    var argsStr = "";
    try { argsStr = JSON.stringify(info.args, null, 2); } catch(e) { argsStr = String(info.args); }
    var aa = $("approval-args");
    if (aa) aa.textContent = argsStr;

    var dangerEl = $("approval-danger");
    if (dangerEl) {
      dangerEl.textContent = dangerLabel(info.danger_level);
      dangerEl.className = "danger-badge danger-" + info.danger_level;
    }

    overlay.style.display = "flex";
    var ac = $("approval-always-check");
    if (ac) ac.checked = false;

    return new Promise(function(resolve) {
      pendingApprove = { resolve: resolve, requestId: info.request_id };
    });
  }

  function hideApprovalModal() {
    var overlay = $("approval-overlay");
    if (overlay) overlay.style.display = "none";
  }

  // Approval buttons (null-safe)
  var approveBtn = $("approval-approve");
  if (approveBtn) {
    approveBtn.addEventListener("click", function() {
      var always = $("approval-always-check");
      if (always && always.checked) {
        postAPI("/api/approval_mode", { mode: "full_access" });
      }
      if (pendingApprove) {
        postAPI("/api/approve_tool", { request_id: pendingApprove.requestId, approved: true });
        pendingApprove.resolve(true);
        pendingApprove = null;
      }
      hideApprovalModal();
    });
  }

  var rejectBtn = $("approval-reject");
  if (rejectBtn) {
    rejectBtn.addEventListener("click", function() {
      if (pendingApprove) {
        postAPI("/api/approve_tool", { request_id: pendingApprove.requestId, approved: false });
        pendingApprove.resolve(false);
        pendingApprove = null;
      }
      hideApprovalModal();
    });
  }

  // ---- Python Callbacks ----
  window._onBalanceResult = function (result) {
    var el = $("balance-status");
    if (!el) return;
    if (result.ok && result.supported) {
      var values = result.balances && result.balances.length ? result.balances.slice() : [{ currency: result.currency, balance: result.balance }];
      var priority = { CNY: 0, USD: 1 };
      values.sort(function (a, b) {
        return (priority[a.currency] == null ? 99 : priority[a.currency]) - (priority[b.currency] == null ? 99 : priority[b.currency]);
      });
      el.textContent = t("balance_label") + values.map(function (item) {
        return (item.currency ? item.currency + " " : "") + item.balance;
      }).join(" / ");
    } else {
      // 后端给的是英文排障文案，不能直接显示在中文界面上。
      // 按 error_code 取本地化文案，原始英文塞进 title（hover 能看细节）。
      var code = result.error_code;
      var key = "balance_unavailable";
      if (code === "no_endpoint") key = "balance_no_endpoint";
      else if (code === "unsupported") key = "balance_unsupported";
      else if (code === "no_field") key = "balance_no_field";
      else if (code === "no_key") key = "balance_no_key";
      el.textContent = t(key);
      el.title = result.error || "";
    }
  };

  window._onToolCall = function(info) {
    showToolCall(info);
  };

  window._onToolResult = function(info) {
    if (info.rejected) {
      showToolRejected(info.request_id);
    } else {
      var truncated = info.result || "";
      if (truncated.length > 100) truncated = truncated.substring(0, 100) + "...";
      updateToolResult(info.request_id, truncated, info.success);
    }
  };

  window._onApprovalRequest = function(info) {
    showApprovalModal(info);
  };

  // Conversation callbacks
  window._onConversationsResult = function(result) {
    if (result.ok) {
      renderConversationList(result.conversations);
    }
  };

  window._onNewConversationResult = function(result) {
    if (result.ok) {
      currentConvId = result.id;
      showWelcome();
      highlightActiveConv();
    }
  };

  // 历史里的 tool_call 走和实时完全相同的卡片（renderToolCallCard）。
  //
  // 数据一直在：core.py 往 history 里写的是
  //   {"role":"assistant","content":"","tool_calls":[...]}
  //   {"role":"tool","tool_call_id":"...","content":"执行结果"}
  // 之前只渲染 role=user / role=assistant+content，工具那一轮像凭空消失。
  function renderToolCallHistory(calls, resultsById) {
    (calls || []).forEach(function (tc) {
      var fn = (tc && tc["function"]) || {};
      var callId = tc && tc.id;
      var card = renderToolCallCard({
        id: callId || ("hist-" + Math.random().toString(36).slice(2, 8)),
        name: fn.name,
        args: fn.arguments,
        danger: null,
        result: resultsById[callId],
      });
      if (messagesEl) messagesEl.appendChild(card);
    });
  }

  window._onLoadConversationResult = function(result) {
    if (result.ok && result.conversation) {
      currentConvId = result.conversation.id;
      highlightActiveConv();
      // Render messages
      if (messagesEl) messagesEl.innerHTML = "";
      hideWelcome();
      var msgs = result.conversation.messages || [];
      // 先把 role=tool 的结果按 tool_call_id 建索引，供上面的卡片引用
      var resultsById = {};
      for (var k = 0; k < msgs.length; k++) {
        if (msgs[k].role === "tool" && msgs[k].tool_call_id) {
          resultsById[msgs[k].tool_call_id] = msgs[k].content || "";
        }
      }
      for (var i = 0; i < msgs.length; i++) {
        var m = msgs[i];
        if (m.role === "system" || m.role === "tool") continue;
        if (m.role === "user") {
          appendMessage("user", m.content);
        } else if (m.role === "assistant") {
          if (m.content) appendMessage("assistant", m.content);
          if (m.tool_calls && m.tool_calls.length) {
            renderToolCallHistory(m.tool_calls, resultsById);
          }
        }
      }
      scrollToBottom();
    }
  };

  // ---- Message Rendering ----
  function appendMessage(role, text, meta) {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "message " + role;
    var label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = role === "user" ? t("msg_you") : t("msg_mollypaw");
    div.appendChild(label);
    var body = document.createElement("div");
    body.className = "msg-body";
    if (role === "assistant" && typeof marked !== "undefined") {
      body.innerHTML = marked.parse(text || "");
    } else {
      body.textContent = text;
    }
    div.appendChild(body);
    if (role === "assistant" && meta && meta.cost !== null && meta.cost !== undefined && !isNaN(Number(meta.cost))) { var cost = document.createElement("div"); cost.className = "msg-cost"; cost.textContent = t("cost_label") + meta.cost; div.appendChild(cost); }
    if (messagesEl) messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function showTyping() {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "typing-indicator";
    div.id = "typing";
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span> ' + t("typing");
    if (messagesEl) messagesEl.appendChild(div);
    scrollToBottom();
  }

  function hideTyping() {
    var el = document.getElementById("typing");
    if (el) el.remove();
  }

  // ---- 流式渲染 ----
  //
  // 以前只能等一整坨回复回来再显示。现在把 chat 拆成若干 event：
  //   _onChatDelta  逐片文字（边生成边显示）
  //   _onChatResult 本轮结束（含取消 / 报错）
  //   _onChatStopped 用户点了停止
  var streamingEl = null;      // 正在写入的那个气泡
  var streamingRaw = "";       // 累积的原始 markdown

  function beginStreaming() {
    hideTyping();
    var div = document.createElement("div");
    div.className = "message assistant streaming";
    var content = document.createElement("div");
    content.className = "message-content";
    div.appendChild(content);
    if (messagesEl) messagesEl.appendChild(div);
    streamingEl = content;
    streamingRaw = "";
    scrollToBottom();
    return div;
  }

  function appendStreamDelta(payload) {
    if (!streamingEl) beginStreaming();
    if (payload && payload.text) {
      streamingRaw += payload.text;
      // 流式过程中逐片渲染 markdown，长文会有点抖，但用户能看到字在长。
      try {
        streamingEl.innerHTML = marked.parse(streamingRaw || "");
      } catch (e) {
        streamingEl.textContent = streamingRaw;
      }
      scrollToBottom();
    }
  }

  function finishStreaming(response) {
    var text = response || streamingRaw;
    if (streamingEl) {
      var bubble = streamingEl.parentElement;
      if (bubble) {
        bubble.classList.remove("streaming");
        if (text) {
          try {
            streamingEl.innerHTML = marked.parse(text || "");
          } catch (e) {
            streamingEl.textContent = text;
          }
        }
      }
      streamingEl = null;
    }
    streamingRaw = "";
    if (!text) return null;
    return true;
  }

  // 停止按钮：真的中断，不是摆设
  function stopChat() {
    var btn = document.getElementById("stop-btn");
    if (btn) {
      // 按钮里现在是 SVG（圆 + 方块），不能改 textContent —— 一改图形就没了。
      btn.disabled = true;
      btn.classList.add("stopping");
    }
    postAPI("/api/stop", { by: "local" }).then(function (res) {
      if (!res.ok) {
        // 停不下来就告诉用户，别假装停了
        appendMessage("error", t("stop_failed") + (res.error || ""));
      }
    }).catch(function () {});
  }
  window.stopChat = stopChat;

  // ---- Send Message ----
  var stopBtn = document.getElementById("stop-btn");
  if (stopBtn) stopBtn.addEventListener("click", stopChat);

  function setLoading(state) {
    isLoading = state;
    sendBtn.disabled = state;
    if (stopBtn) {
      // 两个按钮**互斥**：AI 跑着时只有停止，空闲时只有发送。
      // 同时出现两个圆按钮会让人不知道该点哪个。
      stopBtn.style.display = state ? "inline-flex" : "none";
      stopBtn.disabled = false;
      stopBtn.classList.remove("stopping");
    }
    sendBtn.style.display = state ? "none" : "flex";
    var composer = document.querySelector(".composer");
    if (composer) composer.classList.toggle("is-running", state);
  }

  // 把排队里的下一条发出去（本轮结束时调用）
  function flushQueue() {
    if (isLoading || !pendingQueue.length) return;
    var next = pendingQueue.shift();
    renderQueueHint();
    sendMessage(next);
  }

  function renderQueueHint() {
    var hint = $("queue-hint");
    if (!hint) return;
    if (pendingQueue.length) {
      hint.hidden = false;
      hint.textContent = t("queue_pending").replace("{n}", pendingQueue.length);
    } else {
      hint.hidden = true;
      hint.textContent = "";
    }
  }

  function sendMessage(textOverride) {
    var text = (typeof textOverride === "string" ? textOverride : userInput.value).trim();
    if (!text) return;
    // AI 正在跑：不打断它，先排队，本轮结束立刻发
    if (isLoading) {
      pendingQueue.push(text);
      userInput.value = "";
      autoResize();
      sendBtn.disabled = true;
      renderQueueHint();
      return;
    }

    appendMessage("user", text);
    userInput.value = "";
    autoResize();
    setLoading(true);
    showTyping();

    var gotAnyDelta = false;

    window._onChatDelta = function (payload) {
      gotAnyDelta = true;
      if (streamingEl === null) beginStreaming();
      appendStreamDelta(payload);
    };

    window._onChatStopped = function () {
      hideTyping();
      showTyping();
    };

    window._onChatResult = function (result) {
      hideTyping();
      if (result.cancelled) {
        // 被停止：保留已经流出来的内容，别再插一个气泡
        if (gotAnyDelta) {
          finishStreaming(streamingRaw || t("stopped"));
        } else {
          appendMessage("assistant", t("stopped"));
        }
      } else if (result.ok) {
        if (gotAnyDelta) {
          finishStreaming(result.response);
        } else {
          appendMessage("assistant", result.response, result);
        }
      } else {
        if (result.error === "busy" || (result.busy)) {
          appendMessage("error", t("busy_hint"));
        } else {
          appendMessage("error", t("error_prefix") + (result.error || t("unknown_error")));
        }
      }
      setLoading(false);
      userInput.focus();
      window._onChatResult = null;
      window._onChatDelta = null;
      window._onChatStopped = null;
      loadConversations();
      // 本轮结束了：AI 工作时排队的消息现在自动发出去
      flushQueue();
    };

    postAPI("/api/chat", {
      message: text,
      thinking_level: localStorage.getItem("mollypaw_thinking") || "none"
    }).then(function (res) {
      if (res && res.ok === false) {
        // 服务端直接拒了（比如正忙），把它当成结果处理，别一直转圈
        if (window._onChatResult) window._onChatResult(res);
      }
    }).catch(function (err) {
      if (window._onChatResult) {
        window._onChatResult({ ok: false, error: String(err) });
      }
    });
  }

  // ---- Auto-resize Textarea ----
  function autoResize() {
    userInput.style.height = "auto";
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
  }

  // ---- Settings ----
  var providers = [];
  var selectedProvider = null;

  function renderModels(models) {
    var select = $("cfg-model");
    if (!select) return;
    select.innerHTML = "";
    (models || []).forEach(function (id) {
      var option = document.createElement("option");
      option.value = id;
      option.textContent = formatModelName(id);
      select.appendChild(option);
    });
    select.disabled = !(models && models.length);
  }

  function updateProviderFields() {
    var id = $("cfg-provider").value;
    selectedProvider = providers.filter(function (p) { return p.id === id; })[0];
    var custom = id === "custom";
    $("cfg-custom-url-group").style.display = custom ? "" : "none";
    $("cfg-protocol-group").style.display = custom ? "" : "none";
    $("cfg-balance-path-group").style.display = custom ? "" : "none";
    var tempGroup = $("cfg-temperature").closest(".form-group");
    if (tempGroup) tempGroup.style.display = selectedProvider && !selectedProvider.supports_temperature ? "none" : "";
    if (custom) $("cfg-protocol").value = "chat";
    renderModels([]);
    $("cfg-manual-model").style.display = "none";
  }

  function loadProviders(done) {
    getAPI("/api/providers").then(function (result) {
      providers = result.providers || [];
      var select = $("cfg-provider");
      if (select) {
        select.innerHTML = "";
        providers.forEach(function (provider) {
          var option = document.createElement("option");
          option.value = provider.id;
          option.textContent = provider.display_name;
          select.appendChild(option);
        });
      }
      if (done) done();
    });
  }

  function applyConfig(cfg) {
    if (modelMenuBtn) modelMenuBtn.dataset.model = cfg.model || "";
    setThinkingLevel(cfg.thinking_level || localStorage.getItem("mollypaw_thinking") || "none", false);
    setApprovalMode(cfg.approval_mode || "prompt_dangerous");
    var ak = $("cfg-api-key");
    if (ak) {
      ak.type = "password";
      ak.dataset.original = cfg.api_key_set ? cfg.api_key : "";
      ak.dataset.hasKey = cfg.api_key_set ? "true" : "false";
      ak.value = cfg.api_key_set ? cfg.api_key : "";
      ak.placeholder = "sk-...";
      ak.onfocus = function () {
        if (ak.dataset.hasKey === "true" && ak.value === ak.dataset.original) ak.select();
      };
    }
    loadProviders(function () {
      var ps = $("cfg-provider");
      if (ps) ps.value = cfg.provider_id || "custom";
      updateProviderFields();
      if (selectedProvider && selectedProvider.id !== "custom") {
        renderModels(cfg.model ? [cfg.model] : []);
      }
      if ($("cfg-base-url")) $("cfg-base-url").value = cfg.base_url || "";
      if ($("cfg-balance-path")) $("cfg-balance-path").value = cfg.balance_path || "";
      if ($("cfg-protocol")) $("cfg-protocol").value = cfg.protocol || "chat";
      if ($("cfg-temperature")) $("cfg-temperature").value = cfg.temperature != null ? cfg.temperature : 0.7;
      // max_tokens 为 0 表示"不带该参数"，界面上就该是空，而不是显示 0
      if ($("cfg-max-tokens")) {
        var mtVal = cfg.max_tokens;
        $("cfg-max-tokens").value = (mtVal && mtVal > 0) ? mtVal : "";
      }
      setContextWindowInput(cfg.context_window || cfg.context_window_resolved || 200000);
      if ($("cfg-approval-mode") && cfg.approval_mode) $("cfg-approval-mode").value = cfg.approval_mode;
    });
  }

  window._onConfigResult = function (result) {
    if (!result.ok) {
      var cs = $("cfg-status");
      if (cs) { cs.textContent = t("config_failed"); cs.className = "cfg-status err"; }
      return;
    }
    applyConfig(result.config || {});
  };

  var currentSleepSettings = { mode: "off", tasks: ["memory", "review", "dream"], max_llm_calls: 100 };

  function setSleepStatus(text, isError) {
    var el = $("sleep-status-text");
    if (!el) return;
    el.textContent = text || "";
    el.className = isError ? "sleep-status err" : "sleep-status ok";
  }

  function applySleepSettings(settings) {
    currentSleepSettings = Object.assign({}, currentSleepSettings, settings || {});
    var mode = $("cfg-sleep-mode");
    if (mode) mode.value = currentSleepSettings.mode || "off";
    var maxCalls = $("cfg-sleep-max-calls");
    if (maxCalls) maxCalls.value = currentSleepSettings.max_llm_calls != null ? currentSleepSettings.max_llm_calls : 100;
    var selected = currentSleepSettings.tasks || [];
    document.querySelectorAll("#sleep-task-group input").forEach(function (input) {
      input.checked = selected.indexOf(input.value) >= 0;
    });
    var enabled = currentSleepSettings.mode === "full";
    document.querySelectorAll("#sleep-task-group input").forEach(function (input) { input.disabled = !enabled; });
    var group = $("sleep-task-group");
    if (group) group.classList.toggle("disabled", !enabled);
  }

  function loadSleepSettings() {
    getAPI("/api/sleep").then(function (result) {
      if (result.ok) applySleepSettings(result.sleep || {});
      else setSleepStatus(result.error || "读取失败", true);
    }).catch(function (err) { setSleepStatus(String(err), true); });
  }

  function saveSleepSettings() {
    var settings = Object.assign({}, currentSleepSettings);
    var mode = $("cfg-sleep-mode");
    if (mode) settings.mode = mode.value;
    var maxCalls = $("cfg-sleep-max-calls");
    if (maxCalls && maxCalls.value !== "") settings.max_llm_calls = Math.max(1, Math.min(500, parseInt(maxCalls.value, 10) || 100));
    settings.tasks = [];
    document.querySelectorAll("#sleep-task-group input").forEach(function (input) {
      if (input.checked) settings.tasks.push(input.value);
    });
    currentSleepSettings = settings;
    var enabled = settings.mode === "full";
    document.querySelectorAll("#sleep-task-group input").forEach(function (input) { input.disabled = !enabled; });
    var group = $("sleep-task-group");
    if (group) group.classList.toggle("disabled", !enabled);

    function done(result) {
      if (result.ok) {
        currentSleepSettings = Object.assign({}, currentSleepSettings, result.sleep || {});
        setSleepStatus("已生效");
      } else {
        setSleepStatus(result.error || "保存失败", true);
      }
    }
    postAPI("/api/sleep", settings).then(done).catch(function (err) {
      setSleepStatus(String(err), true);
    });
  }

  function showSettingsTab(name) {
    document.querySelectorAll("[data-settings-tab]").forEach(function (button) {
      button.classList.toggle("active", button.dataset.settingsTab === name);
    });
    document.querySelectorAll("[data-settings-panel]").forEach(function (panel) {
      panel.classList.toggle("active", panel.dataset.settingsPanel === name);
    });
  }

  function openSettings() {
    var sm = $("settings-modal");
    if (!sm) return;
    sm.style.display = "flex";
    var cs = $("cfg-status");
    if (cs) { cs.textContent = ""; cs.className = "cfg-status"; }
    showSettingsTab("model");
    getAPI("/api/config");
    loadSleepSettings();
    if (window.loadRelay) window.loadRelay();
  }
  function fetchModels() {
    var providerId = $("cfg-provider").value;
    var keyInput = $("cfg-api-key");
    var key = keyInput ? keyInput.value.trim() : "";
    var button = $("cfg-fetch-models");
    var status = $("cfg-status");
    if (button) { button.disabled = true; button.textContent = t("model_fetching"); }
    postAPI("/api/models", { provider_id: providerId, api_key: key, base_url: $("cfg-base-url").value, protocol: $("cfg-protocol").value })
      .then(function () { /* result arrives through HTTP event polling */ });
    window._onModelsResult = function (result) {
      if (button) { button.disabled = false; button.textContent = t("fetch_models"); }
      if (result.ok) {
        renderModels(result.models);
        $("cfg-manual-model").style.display = "none";
        if (status) { status.textContent = (result.models || []).length + " models"; status.className = "cfg-status ok"; }
      } else {
        renderModels([]);
        $("cfg-manual-model").style.display = "";
        $("cfg-manual-model").placeholder = t("manual_model_placeholder");
        if (status) { status.textContent = t("model_fetch_failed") + ": " + (result.error || ""); status.className = "cfg-status err"; }
      }
      window._onModelsResult = null;
    };
  }

  function saveSettings() {
    var modelSelect = $("cfg-model");
    var manual = $("cfg-manual-model");
    var cfg = { provider_id: $("cfg-provider").value, model: (manual && manual.style.display !== "none" ? manual.value : modelSelect.value), protocol: $("cfg-protocol").value };
    var ak = $("cfg-api-key");
    if (ak && ak.value && ak.value !== ak.dataset.original && ak.value.indexOf("...") < 0) cfg.api_key = ak.value.trim();
    if (cfg.provider_id === "custom") {
      cfg.base_url = $("cfg-base-url").value;
      cfg.balance_path = $("cfg-balance-path").value;
    }
    var te = $("cfg-temperature");
    if (te && te.value !== "") cfg.temperature = parseFloat(te.value);
    var mt = $("cfg-max-tokens");
    if (mt) {
      // 留空 = **不发这个参数**（0），由服务端决定输出上限。
      // 早先强制 Math.max(256, ...)，既让用户没法留空，
      // 又把一个可能超出模型上下文的值原样发出去 → 上游 400。
      var raw = String(mt.value || "").trim();
      if (raw === "") {
        cfg.max_tokens = 0;
      } else {
        var parsed = parseInt(raw, 10);
        cfg.max_tokens = (isNaN(parsed) || parsed <= 0) ? 0 : parsed;
      }
    }
    var cw = $("cfg-context-window");
    if (cw && cw.value !== "") {
      var parsedContext = readContextWindowInput();
      if (parsedContext == null) {
        $("cfg-status").textContent = "上下文窗口必须大于 0";
        return;
      }
      cfg.context_window = parsedContext;
    }
    var am = $("cfg-approval-mode");
    if (am && am.value) cfg.approval_mode = am.value;
    if (!cfg.model) { $("cfg-status").textContent = t("model_fetch_failed"); return; }
    postAPI("/api/config", cfg);
  }

  window._onSaveConfigResult = function (result) {
    var cs = $("cfg-status");
    if (cs) { cs.textContent = result.ok ? t("saved") : t("error_prefix") + (result.error || ""); cs.className = result.ok ? "cfg-status ok" : "cfg-status err"; }
    if (result.ok) {
      setTimeout(function () { $("settings-modal").style.display = "none"; }, 800);
      getAPI("/api/config");
      getAPI("/api/balance");
    }
  };

  pollEvents();

  // ---- Language Toggle ----
  var langBtn = $("lang-toggle");
  if (langBtn) {
    langBtn.addEventListener("click", function () {
      currentLang = currentLang === "zh" ? "en" : "zh";
      localStorage.setItem("mollypaw_lang", currentLang);
      applyTranslations();
      setThinkingLevel(localStorage.getItem("mollypaw_thinking") || "none", false);
      setApprovalMode(approvalBtn ? approvalBtn.dataset.mode : "prompt_dangerous");
      // Re-render sidebar with new language
      loadConversations();
    });
  }

  // ---- Prompt Chips ----
  var chips = document.querySelectorAll(".prompt-chip");
  for (var ci = 0; ci < chips.length; ci++) {
    chips[ci].addEventListener("click", function () {
      userInput.value = this.getAttribute("data-prompt");
      autoResize();
      userInput.focus();
      sendBtn.disabled = false;
    });
  }

  // ---- Event Listeners ----
  if (userInput) {
    userInput.addEventListener("input", function () {
      sendBtn.disabled = !userInput.value.trim();
      autoResize();
    });

    userInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (modelMenuBtn && thinkingMenu) {
    modelMenuBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (approvalMenu) approvalMenu.hidden = true;
      var open = thinkingMenu.hidden;
      thinkingMenu.hidden = !open;
      thinkingMenu.style.display = open ? "block" : "none";
      modelMenuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    if (thinkingSlider) {
      thinkingSlider.addEventListener("input", function (e) {
        e.stopPropagation();
        previewThinkingLevel(thinkingLevels[Number(thinkingSlider.value)] || "none");
      });
      thinkingSlider.addEventListener("change", function () {
        setThinkingLevel(thinkingLevels[Number(thinkingSlider.value)] || "none", true);
      });
      thinkingSlider.addEventListener("click", function (e) { e.stopPropagation(); });
    }
  }

  if (approvalBtn && approvalMenu) {
    approvalBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (thinkingMenu) thinkingMenu.hidden = true;
      approvalMenu.hidden = !approvalMenu.hidden;
    });
    document.querySelectorAll("[data-approval-mode]").forEach(function (option) {
      option.addEventListener("click", function (e) {
        e.stopPropagation();
        var mode = option.dataset.approvalMode;
        setApprovalMode(mode);
        postAPI("/api/approval_mode", { mode: mode });
        approvalMenu.hidden = true;
      });
    });
  }

  document.addEventListener("click", function (e) {
    var target = e.target;
    if (target && target.closest && (target.closest("#model-menu-btn") || target.closest("#thinking-menu") || target.closest("#approval-btn") || target.closest("#approval-menu"))) return;
    if (thinkingMenu) { thinkingMenu.hidden = true; thinkingMenu.style.display = "none"; }
    if (approvalMenu) approvalMenu.hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (thinkingMenu) thinkingMenu.hidden = true;
      if (approvalMenu) approvalMenu.hidden = true;
      // 连按两次 Esc = 停止 AI。
      // 为什么是两次：一次 Esc 在本应用里有"关菜单"的语义，
      // 直接一次就停会把用户吓到（也会误停）。
      var now = Date.now();
      if (now - lastEscapeAt < 600 && isLoading) {
        lastEscapeAt = 0;
        stopChat();
      } else {
        lastEscapeAt = now;
      }
    }
  });

  if (sendBtn) sendBtn.addEventListener("click", sendMessage);

  // ---- New Chat Button ----
  var newChatBtn = $("new-chat-btn");
  if (newChatBtn) {
    newChatBtn.addEventListener("click", function () {
      currentConvId = null;
      postAPI("/api/conversations/new");
      showWelcome();
    });
  }

  // ---- Settings Button ----
  var settingsBtn = $("settings-btn");
  if (settingsBtn) settingsBtn.addEventListener("click", openSettings);

  var settingsClose = $("settings-close");
  if (settingsClose) {
    settingsClose.addEventListener("click", function () {
      var sm = $("settings-modal");
      if (sm) sm.style.display = "none";
    });
  }

  var cfgSave = $("cfg-save");
  if (cfgSave) cfgSave.addEventListener("click", saveSettings);
  var cfgFetch = $("cfg-fetch-models");
  if (cfgFetch) cfgFetch.addEventListener("click", fetchModels);
  var cfgProvider = $("cfg-provider");
  if (cfgProvider) cfgProvider.addEventListener("change", updateProviderFields);

  var sleepMode = $("cfg-sleep-mode");
  if (sleepMode) sleepMode.addEventListener("change", saveSleepSettings);
  var sleepMaxCalls = $("cfg-sleep-max-calls");
  if (sleepMaxCalls) sleepMaxCalls.addEventListener("change", saveSleepSettings);
  document.querySelectorAll("#sleep-task-group input").forEach(function (input) {
    input.addEventListener("change", saveSleepSettings);
  });

  var cfgCancel = $("cfg-cancel");
  if (cfgCancel) {
    cfgCancel.addEventListener("click", function () {
      var sm = $("settings-modal");
      if (sm) sm.style.display = "none";
    });
  }

  // ---- 远程互联面板 ----
  //
  // 后端接口：
  //   GET  /api/relay/available  依赖是否装了
  //   GET  /api/relay/status     连接状态
  //   GET  /api/relay/settings   当前设置（不回传 psk 明文）
  //   GET  /api/relay/devices    已配对设备
  //   GET  /api/relay/audit      文件访问日志
  //   GET  /api/relay/pin        当前待认领 PIN（可能为 null）
  //   POST /api/relay/start | stop | settings | pin | pin/cancel | device_revoke
  var relayPinTimer = null;

  function relayStateLabel(state) {
    var map = {
      connected: t("relay_connected"),
      disconnected: t("relay_disconnected"),
      reconnecting: t("relay_reconnecting"),
      stopped: t("relay_stopped"),
      error: t("relay_error"),
      starting: t("relay_reconnecting"),
    };
    return map[state] || state || t("relay_stopped");
  }

  // 官方中继地址（选"官方"时用它，不让用户看到这个字符串）
  var OFFICIAL_RELAY_URL = "wss://mollypaw-online.pages.dev/server";

  function currentRelayUrlChoice() {
    var checked = document.querySelector('input[name="relay-server"]:checked');
    return checked ? checked.value : "official";
  }

  function applyRelayServerChoice(choice, url) {
    var isCustom = choice === "custom";
    var group = $("relay-url-group");
    if (group) group.hidden = !isCustom;
    var radios = document.querySelectorAll('input[name="relay-server"]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].checked = (radios[i].value === choice);
    }
    if (url && $("relay-url")) $("relay-url").value = url;
  }

  // 通道显示：当前到底走代理还是直连。
  // 这是排查"手机连不上"时最有用的一行 —— 裸连 pages.dev 在国内会被
  // 干扰到连上就断，用户必须看得见自己在走什么路。
  function renderRelayTransport(st) {
    var roomEl = $("relay-room");
    if (!roomEl || !roomEl.parentNode) return;
    var el = $("relay-transport");
    if (!el) {
      el = document.createElement("span");
      el.id = "relay-transport";
      el.className = "relay-transport";
      roomEl.parentNode.insertBefore(el, roomEl.nextSibling);
    }
    var running = !!st.running;
    if (!running) { el.textContent = ""; return; }
    if (st.proxy_active) {
      el.textContent = t("relay_via_proxy") + " " + st.proxy_active;
      el.title = t("relay_via_proxy");
      el.className = "relay-transport via-proxy";
    } else {
      el.textContent = t("relay_direct");
      el.title = t("relay_direct");
      el.className = "relay-transport direct";
    }
  }

  // 没连上中继就别让人点「添加设备」——
  // 那个二维码是死的，手机扫了只会一直等。
  function renderRelayPairGuard(connected) {
    var addApp = $("relay-add-app");
    var addObs = $("relay-add-obs");
    var box = $("relay-pair-guard");
    if (!box) {
      var actions = document.querySelector(".relay-pair-actions");
      if (actions && actions.parentNode) {
        box = document.createElement("p");
        box.id = "relay-pair-guard";
        box.className = "relay-hint relay-pair-guard";
        actions.parentNode.insertBefore(box, actions.nextSibling);
      }
    }
    [addApp, addObs].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = !connected;
      btn.title = connected ? "" : t("relay_pair_guard");
    });
    if (box) {
      box.hidden = connected;
      if (!connected) box.textContent = t("relay_pair_guard");
    }
  }

  function renderRelayStatus(st) {
    var stateEl = $("relay-state");
    var roomEl = $("relay-room");
    var toggle = $("relay-toggle");
    if (!st) return;

    // 状态显示必须自洽。
    // 以前出现过「重连中」和「已关闭」同时显示 —— 因为 running 与 state
    // 分别取自不同来源，互相矛盾。这里统一以 running 为准：
    //   running=false → 只显示"已关闭"，绝不显示重连中/已连接
    var running = !!st.running;
    var state = st.state || "stopped";
    if (!running && (state === "reconnecting" || state === "connected"
                     || state === "starting" || state === "disconnected")) {
      state = "stopped";
    }

    if (stateEl) {
      stateEl.textContent = relayStateLabel(state);
      stateEl.className = "relay-state " + state;
    }
    if (roomEl) {
      // 关闭时不该显示房间号（那会让人以为还连着）
      roomEl.textContent = (running && st.room)
        ? (t("relay_room") + " " + st.room.slice(0, 8)) : "";
    }
    if (toggle) {
      toggle.textContent = running ? t("relay_stop") : t("relay_enable");
      toggle.dataset.running = running ? "1" : "0";
    }
    renderRelayTransport(st);
    renderRelayPairGuard(running && !!st.connected);
  }

  function setPskField(saved, problems) {
    var psk = $("relay-psk");
    if (!psk) return;
    // 已保存时把密钥回填出来 —— 用户得看得见才抄得到手机上。
    // 早期版本直接清空、只留个 placeholder，等于"保存了就消失"。
    if (typeof saved === "string" && saved) {
      psk.value = saved;
    }
    psk.placeholder = t("relay_psk_ph");
    updatePskHint(problems || []);
  }

  function loadRelay() {
    getAPI("/api/relay/available").then(function (av) {
      if (!av.available) {
        var box = document.querySelector('[data-settings-panel="relay"]');
        if (box) {
          box.innerHTML = '<p class="relay-intro">远程互联需要额外依赖，请先运行：'
            + '<code>pip install -r requirements.txt</code></p>';
        }
        return;
      }
      getAPI("/api/relay/status").then(function (st) {
        if (st && st.ok === false) return;
        renderRelayStatus(st);
      });
      getAPI("/api/relay/settings").then(function (s) {
        if (!s || s.ok === false) return;
        var url = s.url || OFFICIAL_RELAY_URL;
        var isOfficial = (url === OFFICIAL_RELAY_URL);
        applyRelayServerChoice(isOfficial ? "official" : "custom", url);
        // 回填明文密钥：它是要手动抄到手机上的东西，藏起来等于没法用。
        setPskField(s.psk || "", s.psk_problems || []);
      });
      loadRelayDevices();
    }).catch(function () {});
  }

  function updatePskHint(problems) {
    var hint = $("relay-psk-hint");
    if (!hint) return;
    if (!problems || !problems.length) {
      hint.textContent = "";
      hint.className = "relay-hint";
      return;
    }
    hint.textContent = problems.join("；");
    hint.className = "relay-hint bad";
  }

  function loadRelayDevices() {
    getAPI("/api/relay/devices").then(function (data) {
      var box = $("relay-device-list");
      if (!box) return;
      box.innerHTML = "";
      var list = (data && data.devices) || [];
      if (!list.length) {
        var empty = document.createElement("div");
        empty.className = "relay-empty";
        empty.textContent = t("relay_no_devices");
        box.appendChild(empty);
        return;
      }
      list.forEach(function (dev) {
        var row = document.createElement("div");
        row.className = "relay-device" + (dev.revoked ? " revoked" : "");

        var main = document.createElement("div");
        main.className = "relay-device-main";
        var name = document.createElement("strong");
        name.textContent = dev.name || dev.dev_id;
        var meta = document.createElement("small");
        var roleLabel = dev.role === "observer" ? t("relay_role_observer") : t("relay_role_app");
        var when = dev.last_seen ? new Date(dev.last_seen * 1000).toLocaleString() : "-";
        meta.textContent = roleLabel + " · " + t("relay_last_seen") + " " + when
          + (dev.revoked ? " · 已吊销" : "");
        main.appendChild(name);
        main.appendChild(meta);

        var actions = document.createElement("div");
        actions.className = "relay-device-actions";
        if (!dev.revoked) {
          var revoke = document.createElement("button");
          revoke.type = "button";
          revoke.className = "link-btn danger";
          revoke.textContent = t("relay_revoke");
          revoke.addEventListener("click", function () {
            postAPI("/api/relay/device_revoke", { dev_id: dev.dev_id }).then(function () {
              loadRelayDevices();
            });
          });
          actions.appendChild(revoke);
        }
        var del = document.createElement("button");
        del.type = "button";
        del.className = "link-btn";
        del.textContent = t("relay_remove");
        del.addEventListener("click", function () {
          postAPI("/api/relay/device_revoke", { dev_id: dev.dev_id, remove: true })
            .then(function () { loadRelayDevices(); });
        });
        actions.appendChild(del);

        row.appendChild(main);
        row.appendChild(actions);
        box.appendChild(row);
      });
    });
  }

  function loadRelayAudit() {
    getAPI("/api/relay/audit").then(function (data) {
      var box = $("relay-audit-list");
      if (!box) return;
      box.innerHTML = "";
      var entries = (data && data.entries) || [];
      if (!entries.length) {
        var empty = document.createElement("div");
        empty.className = "relay-empty";
        empty.textContent = t("relay_audit_empty");
        box.appendChild(empty);
        return;
      }
      entries.slice(0, 100).forEach(function (e) {
        var line = document.createElement("div");
        line.className = "relay-audit-line";
        var ts = new Date((e.ts || 0) * 1000).toLocaleString();
        line.textContent = "[" + ts + "] " + (e.device || "?") + " "
          + (e.action || "?") + " " + (e.path || "");
        box.appendChild(line);
      });
    });
  }

  function showRelayPin(session) {
    var box = $("relay-pair-box");
    if (!box) return;
    if (!session) {
      box.hidden = true;
      if (relayPinTimer) { clearInterval(relayPinTimer); relayPinTimer = null; }
      return;
    }
    box.hidden = false;

    // 二维码：手机扫一下就配对，不用手输密钥。
    // 后端已经把 PNG 转成 base64 一起返回，这里直接用。
    var qrImg = $("relay-qr");
    if (qrImg) {
      if (session.qr_png) {
        qrImg.src = "data:image/png;base64," + session.qr_png;
        qrImg.hidden = false;
      } else {
        // 生成失败也别装作有二维码 —— 让用户走手动复制那条路
        qrImg.hidden = true;
      }
    }

    // 手动复制用的配对码
    if ($("relay-code")) $("relay-code").value = session.code || "";

    if ($("relay-pair-role")) {
      $("relay-pair-role").textContent = session.role === "observer"
        ? t("relay_role_observer") : t("relay_role_app");
    }

    var left = session.ttl || 900;
    if ($("relay-pin-ttl")) $("relay-pin-ttl").textContent = left;
    if (relayPinTimer) clearInterval(relayPinTimer);
    relayPinTimer = setInterval(function () {
      left -= 1;
      if ($("relay-pin-ttl")) $("relay-pin-ttl").textContent = Math.max(0, left);
      if (left <= 0) {
        clearInterval(relayPinTimer);
        relayPinTimer = null;
        showRelayPin(null);
      }
    }, 1000);
  }

  function makePin(role) {
    postAPI("/api/relay/pin", { role: role }).then(function (res) {
      if (res && res.ok) {
        showRelayPin(res);
        if (res.qr_error && window.relayToast) {
          window.relayToast(t("relay_qr_failed") + res.qr_error, true);
        }
      } else {
        var msg = (res && res.error) || t("relay_error");
        if (window.relayToast) window.relayToast(msg, true);
      }
    });
  }

  (function wireRelayPanel() {
    // 面板内的即时反馈条。
    // 以前点按钮什么都不显示，用户以为"点不动" —— 其实后端成功了但没提示。
    function relayToast(msg, isError) {
      var hint = $("relay-psk-hint");
      if (!hint) return;
      hint.textContent = msg || "";
      hint.className = "relay-hint" + (isError ? " bad" : " ok");
      if (msg) {
        clearTimeout(relayToast._timer);
        relayToast._timer = setTimeout(function () {
          if (hint.textContent === msg) {
            hint.textContent = "";
            hint.className = "relay-hint";
          }
        }, 4500);
      }
    }
    window.relayToast = relayToast;

    var toggle = $("relay-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var running = toggle.dataset.running === "1";
        var ep = running ? "/api/relay/stop" : "/api/relay/start";
        toggle.disabled = true;
        toggle.textContent = t("relay_working");
        relayToast(running ? t("relay_stopping") : t("relay_starting"));

        postAPI(ep, {}).then(function (res) {
          toggle.disabled = false;
          if (res && res.ok === false) {
            renderRelayStatus({ state: "error", running: false });
            relayToast(res.error || t("relay_error"), true);
            return;
          }
          renderRelayStatus(res || {});
          if (res && res.state === "error") {
            // 最常见的两种：没填密钥 / 密钥太弱
            var detail = (res.detail && res.detail.length)
              ? res.detail.join("；")
              : (res.error || t("relay_need_psk"));
            relayToast(detail, true);
          } else if (res && res.connected) {
            relayToast(t("relay_connected"));
          } else if (res && res.running) {
            relayToast(t("relay_starting"));
          } else {
            relayToast(t("relay_stopped"));
          }
        }).catch(function (err) {
          toggle.disabled = false;
          renderRelayStatus({ state: "error", running: false });
          relayToast(String(err), true);
        });
      });
    }

    // 复制密钥。
    // 用户反馈过：password 框里的值看不到也复制不了（浏览器只对自己输入过的
    // 登录框给"显示密码"按钮，脚本填的值不算）。所以输入框改成 text，
    // 再配一个显式的复制按钮。
    function copyText(text, input) {
      if (!text) { relayToast(t("relay_nothing_to_copy"), true); return; }
      var done = function () { relayToast(t("relay_copied")); };
      var fallback = function () {
        if (input) { input.focus(); input.select(); }
        try { document.execCommand("copy"); done(); }
        catch (e) { relayToast(t("relay_copy_failed"), true); }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(fallback);
      } else {
        fallback();
      }
    }

    var copyBtn = $("relay-psk-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var input = $("relay-psk");
        copyText(input ? input.value : "", input);
      });
    }

    // 配对码的手动复制（扫不了码时的退路）
    var codeCopy = $("relay-code-copy");
    if (codeCopy) {
      codeCopy.addEventListener("click", function () {
        var input = $("relay-code");
        copyText(input ? input.value : "", input);
      });
    }

    // 密钥显示 / 隐藏。用 text+遮罩而不是 type=password，
    // 因为 password 会让浏览器接管显示逻辑、外加不给"显示"按钮。
    var reveal = $("relay-psk-reveal");
    if (reveal) {
      reveal.addEventListener("click", function () {
        var input = $("relay-psk");
        if (!input) return;
        var masked = input.classList.toggle("masked");
        reveal.textContent = masked ? t("relay_show") : t("relay_hide");
        if (input.type === "password") input.type = "text";
      });
    }

    // 中继服务器：官方 / 自建
    var serverRadios = document.querySelectorAll('input[name="relay-server"]');
    for (var ri = 0; ri < serverRadios.length; ri++) {
      serverRadios[ri].addEventListener("change", function () {
        var group = $("relay-url-group");
        if (group) group.hidden = (currentRelayUrlChoice() !== "custom");
      });
    }

    // 全部吊销：换密钥后把老设备彻底清退。
    // 为什么需要这个按钮：换 PSK 只让老设备"连不上"（房间号变了），
    // devices.json 里的授权记录还在 —— 它拿到新密钥照样能连进来。
    var revokeAll = $("relay-revoke-all");
    if (revokeAll) {
      revokeAll.addEventListener("click", function () {
        if (!window.confirm(t("relay_revoke_all_confirm"))) return;
        postAPI("/api/relay/device_revoke_all", { mode: "revoke" }).then(function (res) {
          if (res && res.ok) {
            relayToast(t("relay_revoke_all_done").replace("{n}", res.count || 0));
            loadRelayDevices();
          } else {
            relayToast((res && res.error) || t("relay_error"), true);
          }
        });
      });
    }

    var savePsk = $("relay-psk-save");
    if (savePsk) {
      savePsk.addEventListener("click", function () {
        var url = $("relay-url") ? $("relay-url").value.trim() : "";
        var psk = $("relay-psk") ? $("relay-psk").value : "";
        var body = { url: url };
        if (psk) body.psk = psk;   // 留空表示不改
        postAPI("/api/relay/settings", body).then(function (res) {
          if (res && res.ok) {
            updatePskHint(res.psk_problems || []);
            if ($("relay-psk")) {
              // 保存后保留明文，方便用户复制去手机 —— 清空过一次，
              // 结果用户以为"保存了就没了"，还得重新生成。
              $("relay-psk").placeholder = res.psk_set ? t("relay_psk_saved") : t("relay_psk_ph");
            }
            renderRelayStatus(res);
            if (res.psk_problems && res.psk_problems.length) {
              relayToast(res.psk_problems.join("；"), true);
            } else {
              relayToast(t("relay_psk_saved"));
            }
          } else {
            updatePskHint([(res && res.error) || t("relay_error")]);
            relayToast((res && res.error) || t("relay_error"), true);
          }
        });
      });
    }

    var genPsk = $("relay-psk-gen");
    if (genPsk) {
      genPsk.addEventListener("click", function () {
        // 生成一个满足强度要求（长度≥16、含大小写和数字）的随机密钥
        var upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
        var lower = "abcdefghijkmnopqrstuvwxyz";
        var digits = "23456789";
        var all = upper + lower + digits;
        var pick = function (set) { return set[Math.floor(Math.random() * set.length)]; };
        var chars = [pick(upper), pick(lower), pick(digits)];
        for (var i = 0; i < 17; i++) chars.push(pick(all));
        for (var j = chars.length - 1; j > 0; j--) {
          var k = Math.floor(Math.random() * (j + 1));
          var tmp = chars[j]; chars[j] = chars[k]; chars[k] = tmp;
        }
        var input = $("relay-psk");
        if (input) {
          input.value = chars.join("");
          // 生成完立刻选中，方便 Ctrl+C；配合 type=text 用户能直接看见
          input.focus();
          input.select();
        }
        updatePskHint([]);
        relayToast(t("relay_psk_generated"));
      });
    }

    var addApp = $("relay-add-app");
    if (addApp) addApp.addEventListener("click", function () { makePin("app"); });
    var addObs = $("relay-add-obs");
    if (addObs) addObs.addEventListener("click", function () { makePin("observer"); });
    var cancelPin = $("relay-pin-cancel");
    if (cancelPin) {
      cancelPin.addEventListener("click", function () {
        postAPI("/api/relay/pin/cancel", {}).then(function () { showRelayPin(null); });
      });
    }

    var audit = document.querySelector(".relay-audit");
    if (audit) audit.addEventListener("toggle", function () { if (audit.open) loadRelayAudit(); });
  })();
  window.loadRelay = loadRelay;
  window.loadRelayDevices = loadRelayDevices;

  document.querySelectorAll("[data-settings-tab]").forEach(function (button) {
    button.addEventListener("click", function () { showSettingsTab(button.dataset.settingsTab); });
  });

  var settingsModal = $("settings-modal");
  if (settingsModal) {
    settingsModal.addEventListener("click", function (e) {
      if (e.target === settingsModal) settingsModal.style.display = "none";
    });
  }

  // ---- Activity Wakeup ----
  var lastActivityPing = 0;
  function pingActivity() {
    var now = Date.now();
    if (now - lastActivityPing < 5000) return;
    lastActivityPing = now;
    postAPI("/api/activity", {});
  }
  document.addEventListener("pointerdown", pingActivity, true);
  document.addEventListener("keydown", pingActivity, true);

  // ---- Init ----
  applyTranslations();
  setThinkingLevel(localStorage.getItem("mollypaw_thinking") || "none", false);
  getAPI("/api/config");
  getAPI("/api/balance");

  // ---- 自动更新 --------------------------------------------------------
  // 流程：启动时 check -> 有新版弹窗（带更新内容）-> 立即更新则后台下载
  // -> 左下角进度条 -> 下完变「重启并安装」-> POST apply -> 程序自己换 exe 重启。
  var updateInfo = null;

  function fmtSize(bytes) {
    var n = Number(bytes) || 0;
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
    return n + " B";
  }

  function renderUpdateNotes(text) {
    var box = $("update-notes");
    if (!box) return;
    // Release notes 就是 CHANGELOG 正文，是 markdown；用 marked 渲染，
    // 没加载 marked 就退回纯文本 —— 但内容一定得展示出来。
    if (typeof marked !== "undefined" && text) {
      try { box.innerHTML = marked.parse(text); return; } catch (e) {}
    }
    box.textContent = text || "";
  }

  function showUpdateModal(info) {
    updateInfo = info;
    var overlay = $("update-overlay");
    if (!overlay) return;
    var fromEl = $("update-from");
    var toEl = $("update-to");
    if (fromEl) fromEl.textContent = "v" + (info.current || "");
    if (toEl) toEl.textContent = "v" + (info.latest || "");
    var sub = $("update-title");
    if (sub && info.asset && info.asset.size) {
      sub.textContent = t("update_title") + " · " + fmtSize(info.asset.size);
    }
    renderUpdateNotes(info.notes || "");
    var err = $("update-error");
    if (err) err.hidden = true;
    var now = $("update-now");
    if (now) {
      if (info.frozen === false) {
        now.disabled = true;
        now.title = t("update_dev_mode");
        if (err) {
          err.hidden = false;
          err.textContent = t("update_dev_mode");
        }
      } else {
        now.disabled = false;
      }
    }
    overlay.style.display = "flex";
  }

  function hideUpdateModal() {
    var overlay = $("update-overlay");
    if (overlay) overlay.style.display = "none";
  }

  function setUpdateProgress(pct, label) {
    var box = $("update-progress");
    var fill = $("update-progress-fill");
    var pctEl = $("update-progress-pct");
    var lab = $("update-progress-label");
    if (box) box.hidden = false;
    if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    if (pctEl) pctEl.textContent = Math.max(0, Math.min(100, pct)) + "%";
    if (lab && label) lab.textContent = label;
  }

  function hideUpdateProgress() {
    var box = $("update-progress");
    if (box) box.hidden = true;
    var actions = $("update-progress-actions");
    if (actions) actions.hidden = true;
  }

  function startUpdateDownload() {
    if (!updateInfo) return;
    hideUpdateModal();
    setUpdateProgress(0, t("update_downloading"));
    postAPI("/api/update/download", {
      url: (updateInfo.asset && updateInfo.asset.url) || "",
      name: (updateInfo.asset && updateInfo.asset.name) || "MollyPaw.exe"
    }).then(function (res) {
      if (!res || !res.ok) {
        setUpdateProgress(0, t("update_failed"));
        var err = $("update-error");
        showUpdateModal(updateInfo);
        if (err) { err.hidden = false; err.textContent = (res && res.error) || t("update_failed"); }
      }
    }).catch(function (e) {
      updateInfo = updateInfo;
      hideUpdateProgress();
      alert(t("update_failed") + ": " + e);
    });
  }

  window._onUpdateProgress = function (payload) {
    setUpdateProgress(payload.percent || 0, t("update_downloading"));
  };

  window._onUpdateReady = function (payload) {
    setUpdateProgress(100, t("update_ready"));
    var actions = $("update-progress-actions");
    if (actions) actions.hidden = false;
    var pctEl = $("update-progress-pct");
    if (pctEl) pctEl.textContent = "100%";
  };

  window._onUpdateFailed = function (payload) {
    var lab = $("update-progress-label");
    if (lab) lab.textContent = t("update_failed") + "：" + ((payload && payload.error) || "");
    var actions = $("update-progress-actions");
    if (actions) actions.hidden = true;
  };

  window._onUpdateApplying = function () {
    var lab = $("update-progress-label");
    if (lab) lab.textContent = "正在重启…";
  };

  function applyUpdateNow() {
    postAPI("/api/update/apply", {}).then(function (res) {
      if (res && res.ok) {
        var lab = $("update-progress-label");
        if (lab) lab.textContent = "正在重启…";
      } else {
        var el = $("update-error");
        hideUpdateProgress();
        showUpdateModal(updateInfo);
        if (el) { el.hidden = false; el.textContent = (res && res.error) || t("update_failed"); }
      }
    }).catch(function (e) {
      var el = $("update-error");
      if (el) { el.hidden = false; el.textContent = String(e); }
    });
  }

  (function wireUpdate() {
    var now = $("update-now");
    if (now) now.addEventListener("click", startUpdateDownload);
    var later = $("update-later");
    if (later) later.addEventListener("click", hideUpdateModal);
    var restart = $("update-restart");
    if (restart) restart.addEventListener("click", applyUpdateNow);
  })();

  // 左下角的版本号必须跟版本真源（tag -> agent/version.py）一致。
  // 之前写死 0.0.0.1.5，发了好几个版本还显示旧号，排查时非常误导。
  function syncVersionLabel() {
    getAPI("/api/version").then(function (res) {
      if (!res || !res.ok || !res.version) return;
      var label = "MollyPaw Beta " + res.version;
      // 底部那行是 <p class="input-hint" data-i18n="hint">，i18n 键是 hint；
      // 顺手兼容以后可能加的 #version-hint。
      var els = document.querySelectorAll('[data-i18n="hint"], #version-hint');
      for (var i = 0; i < els.length; i++) els[i].textContent = label;
    }).catch(function () {});
  }

  function checkUpdate() {
    getAPI("/api/update/check").then(function (info) {
      if (info && info.ok && info.available) showUpdateModal(info);
    }).catch(function () {});
  }

  loadConversations();

  // 启动后延迟 2 秒查更新，别和首屏抢带宽
  setTimeout(checkUpdate, 2000);
  syncVersionLabel();
  if (userInput) userInput.focus();
  // Intercept markdown links to open in system browser
  document.addEventListener("click", function(e) {
    var link = e.target.closest('.msg-body a');
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href) return;
    if (href.startsWith('http://') || href.startsWith('https://')) {
      e.preventDefault();
      window.open(href, "_blank", "noopener");
    }
  }, true);

})();