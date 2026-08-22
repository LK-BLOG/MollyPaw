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

  var API_BASE = "http://127.0.0.1:18765";

  // ---- i18n Translations ----
  var translations = {
    en: {
      new_chat: "New Chat",
      no_conversations: "No conversations yet",
      settings: "Settings",
      welcome_title: "Hello, I'm MollyPaw!",
      welcome_sub: "Your AI, right at your paw.",
      chip1: "Write a Python script",
      chip2: "Explain PyWebView",
      chip3: "What can you do?",
      input_placeholder: "Ask MollyPaw anything...",
      hint: "MollyPaw",
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
      new_chat: "\u65B0\u5EFA\u5BF9\u8BDD",
      no_conversations: "\u8FD8\u6CA1\u6709\u5BF9\u8BDD\u8BB0\u5F55",
      settings: "\u8BBE\u7F6E",
      welcome_title: "\u4F60\u597D\uFF0C\u6211\u662F MollyPaw\uFF01",
      welcome_sub: "\u4F60\u7684 AI\uFF0C\u5C31\u5728\u4F60\u7684\u722A\u5B50\u91CC\u3002",
      chip1: "\u5199\u4E00\u4E2A Python \u811A\u672C",
      chip2: "\u89E3\u91CA PyWebView \u5DE5\u4F5C\u539F\u7406",
      chip3: "\u4F60\u80FD\u505A\u4EC0\u4E48\uFF1F",
      input_placeholder: "\u95EE MollyPaw \u4EFB\u4F55\u95EE\u9898...",
      hint: "MollyPaw",
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

  function showToolCall(info) {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "tool-call-indicator";
    div.id = "tool-call-" + info.request_id;

    var argsStr = "";
    try { argsStr = JSON.stringify(info.args, null, 2); } catch(e) { argsStr = String(info.args); }
    if (argsStr.length > 200) argsStr = argsStr.substring(0, 200) + "...";

    div.innerHTML = '<div class="tc-header">' +
      '<span class="tc-icon">\uD83D\uDD27</span>' +
      '<span class="tc-name">' + escapeHtml(info.name) + '</span>' +
      '<span class="tc-danger tc-danger-' + info.danger_level + '">' + dangerLabel(info.danger_level) + '</span>' +
      '</div>' +
      '<pre class="tc-args">' + escapeHtml(argsStr) + '</pre>' +
      '<div class="tc-status tc-running">' + t("tc_running") + '</div>';

    div.addEventListener("click", function() {
      div.classList.toggle("expanded");
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

  window._onLoadConversationResult = function(result) {
    if (result.ok && result.conversation) {
      currentConvId = result.conversation.id;
      highlightActiveConv();
      // Render messages
      if (messagesEl) messagesEl.innerHTML = "";
      hideWelcome();
      var msgs = result.conversation.messages || [];
      for (var i = 0; i < msgs.length; i++) {
        var m = msgs[i];
        if (m.role === "system") continue;
        if (m.role === "user") {
          appendMessage("user", m.content);
        } else if (m.role === "assistant" && m.content) {
          appendMessage("assistant", m.content);
        }
      }
    }
  };

  // ---- Message Rendering ----
  function appendMessage(role, text) {
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

  // ---- Send Message ----
  function sendMessage() {
    var text = userInput.value.trim();
    if (!text || isLoading) return;

    appendMessage("user", text);
    userInput.value = "";
    autoResize();
    sendBtn.disabled = true;
    isLoading = true;
    showTyping();

    window._onChatResult = function (result) {
      hideTyping();
      if (result.ok) {
        appendMessage("assistant", result.response);
      } else {
        appendMessage("error", t("error_prefix") + (result.error || t("unknown_error")));
      }
      isLoading = false;
      userInput.focus();
      window._onChatResult = null;
      // Refresh sidebar after chat
      loadConversations();
    };

    postAPI("/api/chat", { message: text });
  }

  // ---- Auto-resize Textarea ----
  function autoResize() {
    userInput.style.height = "auto";
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
  }

  // ---- Settings ----
  function openSettings() {
    var sm = $("settings-modal");
    if (!sm) return;
    sm.style.display = "flex";
    var cs = $("cfg-status");
    if (cs) { cs.textContent = ""; cs.className = "cfg-status"; }

    window._onConfigResult = function (result) {
      if (result.ok) {
        var cfg = result.config;
        var ak = $("cfg-api-key");
        if (ak) { ak.value = ""; ak.placeholder = cfg.api_key_set ? cfg.api_key : "sk-..."; }
        var bu = $("cfg-base-url");
        if (bu) bu.value = cfg.base_url || "";
        var mo = $("cfg-model");
        if (mo) mo.value = cfg.model || "";
        var te = $("cfg-temperature");
        if (te) te.value = cfg.temperature != null ? cfg.temperature : 0.7;
        var am = $("cfg-approval-mode");
        if (am && cfg.approval_mode) am.value = cfg.approval_mode;
      } else {
        if (cs) { cs.textContent = t("config_failed"); cs.className = "cfg-status err"; }
      }
      window._onConfigResult = null;
    };
    getAPI("/api/config");
  }

  function saveSettings() {
    var cfg = {};
    var ak = $("cfg-api-key");
    if (ak && ak.value) cfg.api_key = ak.value;
    var bu = $("cfg-base-url");
    if (bu && bu.value) cfg.base_url = bu.value;
    var mo = $("cfg-model");
    if (mo && mo.value) cfg.model = mo.value;
    var te = $("cfg-temperature");
    if (te && te.value !== "") cfg.temperature = parseFloat(te.value);
    var am = $("cfg-approval-mode");
    if (am && am.value) cfg.approval_mode = am.value;

    window._onSaveConfigResult = function (result) {
      var cs = $("cfg-status");
      if (result.ok) {
        if (cs) { cs.textContent = t("saved"); cs.className = "cfg-status ok"; }
        setTimeout(function () {
          var sm = $("settings-modal");
          if (sm) sm.style.display = "none";
        }, 800);
      } else {
        if (cs) { cs.textContent = t("error_prefix") + (result.error || ""); cs.className = "cfg-status err"; }
      }
      window._onSaveConfigResult = null;
    };
    postAPI("/api/config", cfg);
  }

  // ---- Language Toggle ----
  var langBtn = $("lang-toggle");
  if (langBtn) {
    langBtn.addEventListener("click", function () {
      currentLang = currentLang === "zh" ? "en" : "zh";
      localStorage.setItem("mollypaw_lang", currentLang);
      applyTranslations();
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

  var cfgCancel = $("cfg-cancel");
  if (cfgCancel) {
    cfgCancel.addEventListener("click", function () {
      var sm = $("settings-modal");
      if (sm) sm.style.display = "none";
    });
  }

  var settingsModal = $("settings-modal");
  if (settingsModal) {
    settingsModal.addEventListener("click", function (e) {
      if (e.target === settingsModal) settingsModal.style.display = "none";
    });
  }

  // ---- Init ----
  applyTranslations();
  loadConversations();
  if (userInput) userInput.focus();
  // Intercept markdown links to open in system browser
  document.addEventListener("click", function(e) {
    var link = e.target.closest('.msg-body a');
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href) return;
    if (href.startsWith('http://') || href.startsWith('https://')) {
      e.preventDefault();
      e.stopPropagation();
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
        window.pywebview.api.open_url(JSON.stringify({url: href}));
      }
    }
  }, true);

})();
