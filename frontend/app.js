/* MollyPaw - Frontend App Logic */
(function () {
  "use strict";

  var API_BASE = "http://127.0.0.1:18765";

  // ---- DOM References ----
  var messagesEl     = document.getElementById("messages");
  var welcomeEl      = document.getElementById("welcome-screen");
  var userInput      = document.getElementById("user-input");
  var sendBtn        = document.getElementById("send-btn");
  var newChatBtn     = document.getElementById("new-chat-btn");
  var settingsBtn    = document.getElementById("settings-btn");
  var settingsModal  = document.getElementById("settings-modal");
  var settingsClose  = document.getElementById("settings-close");
  var cfgApiKey      = document.getElementById("cfg-api-key");
  var cfgBaseUrl     = document.getElementById("cfg-base-url");
  var cfgModel       = document.getElementById("cfg-model");
  var cfgTemperature = document.getElementById("cfg-temperature");
  var cfgSave        = document.getElementById("cfg-save");
  var cfgCancel      = document.getElementById("cfg-cancel");
  var cfgStatus      = document.getElementById("cfg-status");

  var isLoading = false;

  // ---- Helpers ----
  function scrollToBottom() {
    var c = document.getElementById("chat-container");
    c.scrollTop = c.scrollHeight;
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
    messagesEl.classList.add("has-messages");
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

  // ---- Message Rendering ----
  function appendMessage(role, text) {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "message " + role;
    var label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = role === "user" ? "You" : "MollyPaw";
    div.appendChild(label);
    var body = document.createElement("div");
    body.textContent = text;
    div.appendChild(body);
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function showTyping() {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "typing-indicator";
    div.id = "typing";
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span> MollyPaw is thinking...';
    messagesEl.appendChild(div);
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
        appendMessage("error", "Error: " + (result.error || "Unknown error"));
      }
      isLoading = false;
      userInput.focus();
      window._onChatResult = null;
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
    settingsModal.style.display = "flex";
    cfgStatus.textContent = "";
    cfgStatus.className = "cfg-status";

    window._onConfigResult = function (result) {
      if (result.ok) {
        var cfg = result.config;
        cfgApiKey.value = "";
        cfgApiKey.placeholder = cfg.api_key_set ? cfg.api_key : "sk-...";
        cfgBaseUrl.value = cfg.base_url || "";
        cfgModel.value = cfg.model || "";
        cfgTemperature.value = cfg.temperature != null ? cfg.temperature : 0.7;
      } else {
        cfgStatus.textContent = "Failed to load config";
        cfgStatus.className = "cfg-status err";
      }
      window._onConfigResult = null;
    };
    getAPI("/api/config");
  }

  function saveSettings() {
    var cfg = {};
    if (cfgApiKey.value) cfg.api_key = cfgApiKey.value;
    if (cfgBaseUrl.value) cfg.base_url = cfgBaseUrl.value;
    if (cfgModel.value) cfg.model = cfgModel.value;
    if (cfgTemperature.value !== "") cfg.temperature = parseFloat(cfgTemperature.value);

    window._onSaveConfigResult = function (result) {
      if (result.ok) {
        cfgStatus.textContent = "Saved!";
        cfgStatus.className = "cfg-status ok";
        setTimeout(function () { settingsModal.style.display = "none"; }, 800);
      } else {
        cfgStatus.textContent = "Error: " + (result.error || "Unknown");
        cfgStatus.className = "cfg-status err";
      }
      window._onSaveConfigResult = null;
    };
    postAPI("/api/config", cfg);
  }

  // ---- Prompt Chips ----
  document.querySelectorAll(".prompt-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      userInput.value = chip.getAttribute("data-prompt");
      autoResize();
      userInput.focus();
      sendBtn.disabled = false;
    });
  });

  // ---- Event Listeners ----
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

  sendBtn.addEventListener("click", sendMessage);

  newChatBtn.addEventListener("click", function () {
    window._onClearHistoryResult = function () { window._onClearHistoryResult = null; };
    postAPI("/api/clear");
    messagesEl.innerHTML = "";
    messagesEl.classList.remove("has-messages");
    welcomeEl.style.display = "";
    userInput.value = "";
    sendBtn.disabled = true;
  });

  settingsBtn.addEventListener("click", openSettings);
  settingsClose.addEventListener("click", function () {
    settingsModal.style.display = "none";
  });
  cfgSave.addEventListener("click", saveSettings);
  cfgCancel.addEventListener("click", function () {
    settingsModal.style.display = "none";
  });
  settingsModal.addEventListener("click", function (e) {
    if (e.target === settingsModal) settingsModal.style.display = "none";
  });

  // ---- Init ----
  userInput.focus();
})();
