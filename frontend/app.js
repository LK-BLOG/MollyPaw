/* MollyPaw - Frontend App Logic */

(function () {
  "use strict";

  // ---- DOM References ----
  const messagesEl       = document.getElementById("messages");
  const welcomeEl        = document.getElementById("welcome-screen");
  const userInput        = document.getElementById("user-input");
  const sendBtn          = document.getElementById("send-btn");
  const newChatBtn       = document.getElementById("new-chat-btn");
  const settingsBtn      = document.getElementById("settings-btn");
  const settingsModal    = document.getElementById("settings-modal");
  const settingsClose    = document.getElementById("settings-close");
  const cfgApiKey        = document.getElementById("cfg-api-key");
  const cfgBaseUrl       = document.getElementById("cfg-base-url");
  const cfgModel         = document.getElementById("cfg-model");
  const cfgTemperature   = document.getElementById("cfg-temperature");
  const cfgSave          = document.getElementById("cfg-save");
  const cfgCancel        = document.getElementById("cfg-cancel");
  const cfgStatus        = document.getElementById("cfg-status");

  let isLoading = false;

  // ---- Helpers ----
  function api() {
    return window.pywebview ? window.pywebview.api : null;
  }

  function scrollToBottom() {
    const c = document.getElementById("chat-container");
    c.scrollTop = c.scrollHeight;
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
    messagesEl.classList.add("has-messages");
  }

  // ---- Message Rendering ----
  function appendMessage(role, text) {
    hideWelcome();
    const div = document.createElement("div");
    div.className = "message " + role;
    const label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = role === "user" ? "You" : "MollyPaw";
    div.appendChild(label);
    const body = document.createElement("div");
    body.textContent = text;
    div.appendChild(body);
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function showTyping() {
    hideWelcome();
    const div = document.createElement("div");
    div.className = "typing-indicator";
    div.id = "typing";
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span> MollyPaw is thinking...';
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function hideTyping() {
    const el = document.getElementById("typing");
    if (el) el.remove();
  }

  // ---- Send Message ----
  function sendMessage() {
    const text = userInput.value.trim();
    if (!text || isLoading) return;
    if (!api()) {
      appendMessage("error", "Backend not ready. Please wait a moment and try again.");
      return;
    }

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

    api().send_message(text);
  }

  // ---- Auto-resize Textarea ----
  function autoResize() {
    userInput.style.height = "auto";
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
  }

  // ---- Settings ----
  async function openSettings() {
    settingsModal.style.display = "flex";
    cfgStatus.textContent = "";
    cfgStatus.className = "cfg-status";
    if (!api()) return;
    try {
      const raw = await api().get_config();
      const cfg = JSON.parse(raw);
      cfgApiKey.value = "";
      cfgApiKey.placeholder = cfg.api_key_set ? cfg.api_key : "sk-...";
      cfgBaseUrl.value = cfg.base_url || "";
      cfgModel.value = cfg.model || "";
      cfgTemperature.value = cfg.temperature != null ? cfg.temperature : 0.7;
    } catch (e) {
      cfgStatus.textContent = "Failed to load config";
      cfgStatus.className = "cfg-status err";
    }
  }

  async function saveSettings() {
    if (!api()) return;
    const cfg = {};
    if (cfgApiKey.value) cfg.api_key = cfgApiKey.value;
    if (cfgBaseUrl.value) cfg.base_url = cfgBaseUrl.value;
    if (cfgModel.value) cfg.model = cfgModel.value;
    if (cfgTemperature.value !== "") cfg.temperature = parseFloat(cfgTemperature.value);

    try {
      const raw = await api().save_config(JSON.stringify(cfg));
      const result = JSON.parse(raw);
      if (result.ok) {
        cfgStatus.textContent = "Saved!";
        cfgStatus.className = "cfg-status ok";
        setTimeout(() => { settingsModal.style.display = "none"; }, 800);
      } else {
        cfgStatus.textContent = "Error: " + (result.error || "Unknown");
        cfgStatus.className = "cfg-status err";
      }
    } catch (e) {
      cfgStatus.textContent = "Connection error";
      cfgStatus.className = "cfg-status err";
    }
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

  newChatBtn.addEventListener("click", async function () {
    if (api()) {
      await api().clear_history();
    }
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
