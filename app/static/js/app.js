(function () {
  var CHAT_STORAGE_KEY = "retrievia_chat_threads";
  var CHAT_THREAD_INDEX_KEY = "retrievia_chat_thread_index";
  var ACTIVE_CHAT_STORAGE_KEY = "retrievia_active_chat";
  var activeStreamController = null;
  var activeStreamTarget = null;
  var activeConversationLoadToken = 0;

  function showToast(message, level) {
    var region = document.getElementById("toast-region");
    if (!region || !message) {
      return;
    }
    var item = document.createElement("div");
    item.className =
      "toast-item rounded-lg border px-3 py-2 text-sm shadow-soft " +
      (level === "error"
        ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
        : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200");
    item.textContent = message;
    region.appendChild(item);
    setTimeout(function () {
      item.remove();
    }, 3500);
  }

  function extractApiErrorMessage(rawPayload, fallback) {
    var fallbackMessage = fallback || "Request failed";
    if (!rawPayload) {
      return fallbackMessage;
    }
    if (typeof rawPayload === "string") {
      return rawPayload.trim() || fallbackMessage;
    }
    if (typeof rawPayload.message === "string" && rawPayload.message.trim()) {
      return rawPayload.message.trim();
    }
    if (typeof rawPayload.error === "string" && rawPayload.error.trim()) {
      return rawPayload.error.trim();
    }
    if (typeof rawPayload.detail === "string" && rawPayload.detail.trim()) {
      return rawPayload.detail.trim();
    }
    if (Array.isArray(rawPayload.errors) && rawPayload.errors.length) {
      return String(rawPayload.errors[0]);
    }
    return fallbackMessage;
  }

  async function parseApiErrorResponse(response, fallback) {
    var fallbackMessage = fallback || "Request failed";
    if (!response) {
      return fallbackMessage;
    }
    try {
      var contentType = (response.headers && response.headers.get("content-type")) || "";
      if (contentType.indexOf("application/json") !== -1) {
        var json = await response.json();
        return extractApiErrorMessage(json, fallbackMessage);
      }
      var text = await response.text();
      return extractApiErrorMessage(text, fallbackMessage);
    } catch (_err) {
      return fallbackMessage;
    }
  }

  function setTheme(theme) {
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
    } else if (theme === "light") {
      document.documentElement.classList.remove("dark");
    } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("retrievia-theme", theme);
  }

  function toggleTheme() {
    var isDark = document.documentElement.classList.contains("dark");
    setTheme(isDark ? "light" : "dark");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function markdownToHtml(markdownText) {
    var raw = String(markdownText || "");
    if (window.marked && window.DOMPurify) {
      return window.DOMPurify.sanitize(window.marked.parse(raw));
    }
    return escapeHtml(raw).replace(/\n/g, "<br>");
  }

  function detectCodeLanguage(codeNode) {
    if (!codeNode || !codeNode.className) {
      return "text";
    }
    var className = String(codeNode.className);
    var match = className.match(/language-([\w-]+)/i);
    if (!match) {
      return "text";
    }
    return String(match[1] || "text").toLowerCase();
  }

  async function runCodeSnippet(source, language, outputNode) {
    var code = String(source || "");
    var lang = String(language || "").toLowerCase();
    if (!outputNode) {
      return;
    }
    if (!(lang === "js" || lang === "javascript" || lang === "node" || lang === "mjs" || lang === "cjs")) {
      outputNode.textContent = "Run is supported for JavaScript snippets only.";
      return;
    }
    if (!code.trim()) {
      outputNode.textContent = "Nothing to run.";
      return;
    }

    var logs = [];
    var sandboxConsole = {
      log: function () {
        logs.push(Array.prototype.slice.call(arguments).join(" "));
      },
      error: function () {
        logs.push("[error] " + Array.prototype.slice.call(arguments).join(" "));
      },
      warn: function () {
        logs.push("[warn] " + Array.prototype.slice.call(arguments).join(" "));
      },
    };

    outputNode.textContent = "Running...";
    try {
      var runner = new Function("console", "\"use strict\";\n" + code);
      var result = runner(sandboxConsole);
      if (result && typeof result.then === "function") {
        result = await Promise.race([
          result,
          new Promise(function (_resolve, reject) {
            setTimeout(function () {
              reject(new Error("Execution timed out"));
            }, 3000);
          }),
        ]);
      }

      var output = [];
      if (logs.length) {
        output.push(logs.join("\n"));
      }
      if (result !== undefined) {
        output.push("=> " + String(result));
      }
      outputNode.textContent = output.length ? output.join("\n") : "Done (no output).";
    } catch (err) {
      outputNode.textContent = "Execution failed: " + extractApiErrorMessage(err, "Unknown error");
    }
  }

  function enhanceCodeBlocks(scope) {
    var root = scope || document;
    root.querySelectorAll(".assistant-content pre").forEach(function (pre) {
      if (pre.dataset.enhanced === "1") {
        return;
      }
      pre.dataset.enhanced = "1";
      var code = pre.querySelector("code");
      var language = detectCodeLanguage(code);

      var shell = document.createElement("div");
      shell.className = "code-block-shell";

      var toolbar = document.createElement("div");
      toolbar.className = "code-toolbar";

      var lang = document.createElement("span");
      lang.className = "code-lang";
      lang.textContent = language;

      var actions = document.createElement("div");
      actions.className = "code-toolbar-actions";
      actions.innerHTML =
        "<button type='button' class='code-toolbar-btn js-code-copy'>Copy</button>" +
        "<button type='button' class='code-toolbar-btn js-code-run'>Run</button>" +
        "<button type='button' class='code-toolbar-btn js-code-toggle'>Collapse</button>";

      var output = document.createElement("div");
      output.className = "code-run-output hidden";

      toolbar.appendChild(lang);
      toolbar.appendChild(actions);
      shell.appendChild(toolbar);
      pre.parentNode.insertBefore(shell, pre);
      shell.appendChild(pre);
      shell.appendChild(output);

      var copyButton = toolbar.querySelector(".js-code-copy");
      var runButton = toolbar.querySelector(".js-code-run");
      var toggleButton = toolbar.querySelector(".js-code-toggle");

      copyButton.addEventListener("click", async function () {
        try {
          await navigator.clipboard.writeText((code && code.textContent) || "");
          showToast("Code copied", "ok");
        } catch (_err) {
          showToast("Code copy failed", "error");
        }
      });

      runButton.addEventListener("click", async function () {
        output.classList.remove("hidden");
        await runCodeSnippet((code && code.textContent) || "", language, output);
      });

      toggleButton.addEventListener("click", function () {
        var isHidden = pre.classList.toggle("hidden");
        toggleButton.textContent = isHidden ? "Expand" : "Collapse";
        if (isHidden) {
          output.classList.add("hidden");
        }
      });
    });
  }

  function renderMarkdownIn(scope) {
    var root = scope || document;
    var nodes = root.querySelectorAll(".assistant-content");
    nodes.forEach(function (node) {
      if (node.dataset.streamTarget === "true") {
        return;
      }
      if (node.dataset.markdownRendered === "1") {
        return;
      }
      var raw = node.textContent || "";
      node.innerHTML = markdownToHtml(raw);
      node.dataset.markdownRendered = "1";
      node.dataset.rawAnswer = raw;
    });
    enhanceCodeBlocks(root);
  }

  function scrollChatToBottom() {
    var container = document.getElementById("chat-messages");
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }

  function setGeneratingState(isGenerating, streamTarget) {
    var sendButton = document.querySelector("#chat-form .send-button");
    var stopButton = document.getElementById("chat-stop-button");
    if (sendButton) {
      sendButton.classList.toggle("hidden", !!isGenerating);
    }
    if (stopButton) {
      stopButton.classList.toggle("hidden", !isGenerating);
    }
    if (activeStreamTarget && activeStreamTarget !== streamTarget) {
      activeStreamTarget.classList.remove("stream-shimmer");
    }
    if (isGenerating && streamTarget) {
      streamTarget.classList.add("stream-shimmer");
    }
    if (!isGenerating && activeStreamTarget) {
      activeStreamTarget.classList.remove("stream-shimmer");
    }
  }

  function clearActiveStreamState() {
    activeStreamController = null;
    activeStreamTarget = null;
    setGeneratingState(false, null);
  }

  function stopActiveStream() {
    if (!activeStreamController) {
      return;
    }
    activeStreamController.abort();
    showToast("Stopped generating", "ok");
    clearActiveStreamState();
  }

  function openModal() {
    var modal = document.getElementById("document-modal");
    if (!modal) {
      return;
    }
    modal.classList.remove("hidden", "pointer-events-none");
    modal.classList.add("flex");
  }

  function closeModal() {
    var modal = document.getElementById("document-modal");
    if (!modal) {
      return;
    }
    modal.classList.remove("flex");
    modal.classList.add("hidden", "pointer-events-none");
  }

  function updateSources(sources) {
    var panel = document.getElementById("sources-panel");
    if (!panel) {
      return;
    }
    if (!Array.isArray(sources) || sources.length === 0) {
      panel.innerHTML = "<p class='text-slate-500 dark:text-slate-400'>No sources returned.</p>";
      return;
    }
    panel.innerHTML = sources
      .map(function (source) {
        var page = source.page ? " p." + source.page : "";
        var section = source.section ? " / " + source.section : "";
        return (
          "<button type='button' class='w-full rounded-lg border border-slate-200 px-3 py-2 text-left hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800' onclick='window.retrievia.scrollToCitation(\"" +
          source.citation_id +
          "\")'>" +
          "<div class='font-medium'>[" +
          source.citation_id +
          "] " +
          (source.title || "Untitled") +
          "</div>" +
          "<div class='mt-1 text-xs text-slate-500 dark:text-slate-400'>" +
          (source.doc_id || "") +
          page +
          section +
          "</div>" +
          "</button>"
        );
      })
      .join("");
  }

  function scrollToCitation(citationId) {
    var containers = document.querySelectorAll("#chat-messages [data-assistant-message='true']");
    var target = null;
    for (var i = containers.length - 1; i >= 0; i -= 1) {
      if (containers[i].textContent.indexOf("[" + citationId + "]") !== -1) {
        target = containers[i];
        break;
      }
    }
    if (!target && containers.length) {
      target = containers[containers.length - 1];
    }
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
      target.classList.add("ring-2", "ring-brand-400", "ring-offset-2", "dark:ring-offset-slate-900");
      setTimeout(function () {
        target.classList.remove("ring-2", "ring-brand-400", "ring-offset-2", "dark:ring-offset-slate-900");
      }, 1000);
    }
  }

  function newLocalThreadId() {
    return "local-" + Date.now() + "-" + Math.random().toString(16).slice(2, 8);
  }

  function getChatThreads() {
    try {
      var raw = localStorage.getItem(CHAT_STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return typeof parsed === "object" && parsed ? parsed : {};
    } catch (_err) {
      return {};
    }
  }

  function saveChatThreads(threads) {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(threads));
  }

  function getThreadIndex() {
    try {
      var raw = localStorage.getItem(CHAT_THREAD_INDEX_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (_err) {
      return [];
    }
  }

  function saveThreadIndex(index) {
    localStorage.setItem(CHAT_THREAD_INDEX_KEY, JSON.stringify(index));
  }

  function getActiveChatKey() {
    return localStorage.getItem(ACTIVE_CHAT_STORAGE_KEY) || "";
  }

  function setActiveChatKey(key) {
    localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, key || "");
  }

  function getCurrentConversationId() {
    var input = document.getElementById("conversation-id");
    return input ? input.value || "" : "";
  }

  function buildChatKeyFromThreadId(threadId) {
    return "chat:" + threadId;
  }

  function buildThreadIdFromConversationId(conversationId) {
    return "srv:" + conversationId;
  }

  function isServerThreadId(threadId) {
    return String(threadId || "").indexOf("srv:") === 0;
  }

  function getEmptyStateHtml() {
    return "<div id='chat-empty-state' class='chat-empty-state mx-auto max-w-2xl rounded-2xl border border-slate-200/80 bg-white/90 p-6 text-center dark:border-slate-700 dark:bg-slate-900/80'><p class='text-base font-semibold text-slate-800 dark:text-slate-100'>How can I help today?</p><p class='mt-2 text-sm text-slate-600 dark:text-slate-300'>Ask about your uploaded files, request a plan, or generate a concise brief.</p></div>";
  }

  function upsertThread(thread) {
    var index = getThreadIndex();
    var existingPos = -1;
    var existingThread = null;
    for (var i = 0; i < index.length; i += 1) {
      if (index[i].id === thread.id) {
        existingPos = i;
        existingThread = index[i];
        break;
      }
    }
    var next = {
      id: thread.id,
      title: thread.title || "New chat",
      conversationId: thread.conversationId || "",
      updatedAt: Number(thread.updatedAt || Date.now()),
      pinned: typeof thread.pinned === "boolean" ? thread.pinned : !!(existingThread && existingThread.pinned),
    };
    if (existingPos === -1) {
      index.unshift(next);
    } else {
      index[existingPos] = next;
    }
    index.sort(function (a, b) {
      if (!!a.pinned !== !!b.pinned) {
        return a.pinned ? -1 : 1;
      }
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    });
    saveThreadIndex(index);
    return next;
  }

  function getCurrentThreadId() {
    var key = getActiveChatKey();
    if (!key || key.indexOf("chat:") !== 0) {
      return "";
    }
    return key.slice(5);
  }

  function getCurrentThreadMeta() {
    var currentId = getCurrentThreadId();
    var index = getThreadIndex();
    for (var i = 0; i < index.length; i += 1) {
      if (index[i].id === currentId) {
        return index[i];
      }
    }
    return null;
  }

  function getConversationSearchTerm() {
    var input = document.getElementById("conversation-search");
    if (!input) {
      return "";
    }
    return (input.value || "").trim().toLowerCase();
  }

  function toggleThreadPinned(threadId) {
    if (!threadId) {
      return;
    }
    var index = getThreadIndex();
    var updated = false;
    var next = index.map(function (thread) {
      if (thread.id !== threadId) {
        return thread;
      }
      updated = true;
      return {
        id: thread.id,
        title: thread.title || "New chat",
        conversationId: thread.conversationId || "",
        updatedAt: Number(thread.updatedAt || Date.now()),
        pinned: !thread.pinned,
      };
    });
    if (!updated) {
      return;
    }
    next.sort(function (a, b) {
      if (!!a.pinned !== !!b.pinned) {
        return a.pinned ? -1 : 1;
      }
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    });
    saveThreadIndex(next);
    renderConversationList();
  }

  function closeConversationMenus(scope) {
    var root = scope || document;
    root.querySelectorAll(".thread-action-menu").forEach(function (menu) {
      menu.classList.add("hidden");
    });
  }

  async function renameConversationThread(threadId) {
    var index = getThreadIndex();
    var thread = null;
    for (var i = 0; i < index.length; i += 1) {
      if (index[i].id === threadId) {
        thread = index[i];
        break;
      }
    }
    if (!thread) {
      return;
    }

    var currentTitle = String(thread.title || "New chat");
    var nextTitle = window.prompt("Rename conversation", currentTitle);
    if (typeof nextTitle !== "string") {
      return;
    }
    nextTitle = nextTitle.trim();
    if (!nextTitle) {
      showToast("Title cannot be empty", "error");
      return;
    }

    var previousTitle = thread.title;
    thread.title = nextTitle;
    saveThreadIndex(index);
    renderConversationList();

    if (!thread.conversationId) {
      return;
    }

    try {
      var response = await fetch("/app/chat/conversations/" + encodeURIComponent(thread.conversationId), {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: nextTitle }),
      });
      if (!response.ok) {
        thread.title = previousTitle;
        saveThreadIndex(index);
        renderConversationList();
        showToast(await parseApiErrorResponse(response, "Rename failed"), "error");
        return;
      }
      showToast("Conversation renamed", "ok");
    } catch (err) {
      thread.title = previousTitle;
      saveThreadIndex(index);
      renderConversationList();
      showToast(extractApiErrorMessage(err, "Rename failed"), "error");
    }
  }

  async function deleteConversationThread(threadId) {
    var index = getThreadIndex();
    var thread = null;
    for (var i = 0; i < index.length; i += 1) {
      if (index[i].id === threadId) {
        thread = index[i];
        break;
      }
    }
    if (!thread) {
      return;
    }

    var confirmed = window.confirm("Delete this conversation?");
    if (!confirmed) {
      return;
    }

    if (thread.conversationId) {
      try {
        var response = await fetch("/app/chat/conversations/" + encodeURIComponent(thread.conversationId), {
          method: "DELETE",
          credentials: "same-origin",
        });
        if (!response.ok && response.status !== 204) {
          showToast(await parseApiErrorResponse(response, "Delete failed"), "error");
          return;
        }
      } catch (err) {
        showToast(extractApiErrorMessage(err, "Delete failed"), "error");
        return;
      }
    }

    var activeThreadId = getCurrentThreadId();
    var remaining = index.filter(function (item) {
      return item.id !== threadId;
    });
    saveThreadIndex(remaining);

    var threads = getChatThreads();
    delete threads[buildChatKeyFromThreadId(threadId)];
    saveChatThreads(threads);

    if (!remaining.length) {
      var created = upsertThread({ id: newLocalThreadId(), title: "New chat", conversationId: "", updatedAt: Date.now() });
      setActiveChatKey(buildChatKeyFromThreadId(created.id));
      restoreChatByKey(buildChatKeyFromThreadId(created.id));
      updateSources([]);
      renderConversationList();
      showToast("Conversation deleted", "ok");
      return;
    }

    if (activeThreadId === threadId) {
      selectConversation(remaining[0].id);
    } else {
      renderConversationList();
    }
    showToast("Conversation deleted", "ok");
  }

  function renderConversationList() {
    var list = document.getElementById("conversation-list");
    var switcher = document.getElementById("conversation-switcher");
    var index = getThreadIndex();
    var activeThreadId = getCurrentThreadId();
    var searchTerm = getConversationSearchTerm();
    var visibleThreads = index.filter(function (thread) {
      if (!searchTerm) {
        return true;
      }
      return String(thread.title || "New chat").toLowerCase().indexOf(searchTerm) !== -1;
    });
    var pinnedThreads = visibleThreads.filter(function (thread) {
      return !!thread.pinned;
    });
    var normalThreads = visibleThreads.filter(function (thread) {
      return !thread.pinned;
    });

    function buildThreadRows(threads) {
      return threads
        .map(function (thread) {
          var activeClass = thread.id === activeThreadId ? " active" : "";
          var pinLabel = thread.pinned ? "Unpin" : "Pin";
          var pinTitle = thread.pinned ? "Unpin" : "Pin";
          return (
            "<div class='conversation-row'>" +
            "<button type='button' class='conversation-item w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800" +
            activeClass +
            "' data-thread-id='" +
            thread.id +
            "' data-conversation-id='" +
            (thread.conversationId || "") +
            "'>" +
            escapeHtml(thread.title || "New chat") +
            "</button>" +
            "<div class='thread-menu-wrap'>" +
            "<button type='button' class='thread-menu-toggle' data-menu-thread-id='" +
            thread.id +
            "' title='Conversation actions' aria-label='Conversation actions'>...</button>" +
            "<div class='thread-action-menu hidden'>" +
            "<button type='button' class='thread-menu-action' data-menu-action='pin' data-thread-id='" +
            thread.id +
            "'>" +
            pinLabel +
            "</button>" +
            "<button type='button' class='thread-menu-action' data-menu-action='rename' data-thread-id='" +
            thread.id +
            "'>Rename</button>" +
            "<button type='button' class='thread-menu-action danger' data-menu-action='delete' data-thread-id='" +
            thread.id +
            "'>Delete</button>" +
            "</div>" +
            "</div>" +
            "</div>"
          );
        })
        .join("");
    }

    if (list) {
      if (!visibleThreads.length) {
        list.innerHTML =
          "<div class='rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400'>" +
          (searchTerm ? "No matches found" : "No conversations yet") +
          "</div>";
      } else {
        var html = "";
        if (pinnedThreads.length) {
          html += "<div class='conversation-section-label'>Pinned</div>" + buildThreadRows(pinnedThreads);
        }
        if (normalThreads.length) {
          html += "<div class='conversation-section-label'>Recent</div>" + buildThreadRows(normalThreads);
        }
        list.innerHTML = html;

        list.querySelectorAll(".conversation-item").forEach(function (button) {
          button.addEventListener("click", function () {
            closeConversationMenus(list);
            selectConversation(button.getAttribute("data-thread-id") || "");
          });
        });
        list.querySelectorAll(".thread-menu-toggle").forEach(function (button) {
          button.addEventListener("click", function () {
            var wrap = button.closest(".thread-menu-wrap");
            var menu = wrap ? wrap.querySelector(".thread-action-menu") : null;
            if (!menu) {
              return;
            }
            var shouldOpen = menu.classList.contains("hidden");
            closeConversationMenus(list);
            menu.classList.toggle("hidden", !shouldOpen);
          });
        });
        list.querySelectorAll(".thread-menu-action").forEach(function (button) {
          button.addEventListener("click", function () {
            var action = button.getAttribute("data-menu-action") || "";
            var targetThreadId = button.getAttribute("data-thread-id") || "";
            closeConversationMenus(list);
            if (action === "pin") {
              toggleThreadPinned(targetThreadId);
              return;
            }
            if (action === "rename") {
              renameConversationThread(targetThreadId);
              return;
            }
            if (action === "delete") {
              deleteConversationThread(targetThreadId);
            }
          });
        });
      }
    }

    if (switcher) {
      switcher.innerHTML = index
        .map(function (thread) {
          var prefix = thread.pinned ? "[P] " : "";
          return "<option value='" + escapeHtml(thread.id) + "'>" + prefix + escapeHtml(thread.title || "New chat") + "</option>";
        })
        .join("");
      switcher.value = activeThreadId || (index[0] ? index[0].id : "");
      if (switcher.dataset.bound !== "1") {
        switcher.dataset.bound = "1";
        switcher.addEventListener("change", function () {
          selectConversation(switcher.value || "");
        });
      }
    }
  }

  function initializeThreadStore() {
    var seedEl = document.getElementById("seed-conversations");
    var seeded = [];
    if (seedEl && seedEl.textContent) {
      try {
        var parsed = JSON.parse(seedEl.textContent);
        if (Array.isArray(parsed)) {
          seeded = parsed;
        }
      } catch (_err) {
        seeded = [];
      }
    }

    seeded.forEach(function (item) {
      if (!item || !item.conversation_id) {
        return;
      }
      upsertThread({
        id: buildThreadIdFromConversationId(item.conversation_id),
        title: item.title || "Conversation",
        conversationId: item.conversation_id,
        updatedAt: Date.now(),
      });
    });

    if (!getThreadIndex().length) {
      var id = newLocalThreadId();
      upsertThread({ id: id, title: "New chat", conversationId: "", updatedAt: Date.now() });
      setActiveChatKey(buildChatKeyFromThreadId(id));
    }

    renderConversationList();
  }

  function persistCurrentChat() {
    var messages = document.getElementById("chat-messages");
    if (!messages) {
      return;
    }
    var threadId = getCurrentThreadId();
    if (!threadId) {
      return;
    }

    var threadMeta = getCurrentThreadMeta();
    var currentConversationId = getCurrentConversationId();
    var now = Date.now();
    var threads = getChatThreads();
    threads[getActiveChatKey()] = {
      html: messages.innerHTML,
      conversationId: currentConversationId,
      updatedAt: now,
      scrollTop: messages.scrollTop,
    };
    saveChatThreads(threads);
    upsertThread({
      id: threadId,
      title: (threadMeta && threadMeta.title) || "New chat",
      conversationId: currentConversationId,
      updatedAt: now,
    });
    renderConversationList();
  }

  function adoptServerConversation(conversationId, titleHint) {
    var normalizedConversationId = String(conversationId || "").trim();
    if (!normalizedConversationId) {
      return;
    }

    var conversationInput = document.getElementById("conversation-id");
    if (conversationInput) {
      conversationInput.value = normalizedConversationId;
    }

    var currentThreadId = getCurrentThreadId();
    if (!currentThreadId) {
      return;
    }

    var serverThreadId = buildThreadIdFromConversationId(normalizedConversationId);
    var index = getThreadIndex();
    var currentMeta = null;
    var serverMeta = null;

    index.forEach(function (thread) {
      if (thread.id === currentThreadId) {
        currentMeta = thread;
      }
      if (thread.id === serverThreadId) {
        serverMeta = thread;
      }
    });

    var threads = getChatThreads();
    var currentKey = buildChatKeyFromThreadId(currentThreadId);
    var serverKey = buildChatKeyFromThreadId(serverThreadId);
    if (threads[currentKey] && currentKey !== serverKey) {
      threads[serverKey] = threads[currentKey];
      delete threads[currentKey];
      saveChatThreads(threads);
    }

    var mergedTitle =
      String(titleHint || "").trim() ||
      (currentMeta && currentMeta.title) ||
      (serverMeta && serverMeta.title) ||
      "New chat";
    var pinned = !!((currentMeta && currentMeta.pinned) || (serverMeta && serverMeta.pinned));

    if (currentThreadId !== serverThreadId && !isServerThreadId(currentThreadId)) {
      index = index.filter(function (thread) {
        return thread.id !== currentThreadId;
      });
    }

    index = index.filter(function (thread) {
      return thread.id !== serverThreadId;
    });
    index.unshift({
      id: serverThreadId,
      title: mergedTitle,
      conversationId: normalizedConversationId,
      updatedAt: Date.now(),
      pinned: pinned,
    });
    saveThreadIndex(index);

    setActiveChatKey(serverKey);
    renderConversationList();
  }

  async function loadConversationFromServer(conversationId) {
    var normalizedConversationId = String(conversationId || "").trim();
    var messages = document.getElementById("chat-messages");
    if (!normalizedConversationId || !messages) {
      return false;
    }

    var requestToken = activeConversationLoadToken + 1;
    activeConversationLoadToken = requestToken;
    var activeKey = getActiveChatKey();
    var cachedRecord = getChatThreads()[activeKey] || null;
    var preferredScrollTop = cachedRecord && typeof cachedRecord.scrollTop === "number" ? cachedRecord.scrollTop : null;
    messages.classList.add("chat-feed-loading");

    try {
      var response = await fetch("/app/chat/conversations/" + encodeURIComponent(normalizedConversationId), {
        credentials: "same-origin",
        headers: {
          "HX-Request": "true",
        },
      });
      if (requestToken !== activeConversationLoadToken) {
        return false;
      }
      if (!response.ok) {
        var errorMessage = await parseApiErrorResponse(response, "Unable to load conversation");
        showToast(errorMessage, "error");
        return false;
      }
      var nextHtml = await response.text();
      if (requestToken !== activeConversationLoadToken) {
        return false;
      }
      if (messages.innerHTML !== nextHtml) {
        messages.innerHTML = nextHtml;
      }
      renderMarkdownIn(messages);
      bindMessageActions(messages);
      if (preferredScrollTop !== null) {
        messages.scrollTop = preferredScrollTop;
      }
      persistCurrentChat();
      return true;
    } catch (err) {
      showToast(extractApiErrorMessage(err, "Unable to load conversation"), "error");
      return false;
    } finally {
      if (requestToken === activeConversationLoadToken) {
        messages.classList.remove("chat-feed-loading");
      }
    }
  }

  function restoreChatByKey(key) {
    var messages = document.getElementById("chat-messages");
    if (!messages) {
      return;
    }
    var threads = getChatThreads();
    var record = threads[key];
    if (!record || !record.html) {
      messages.innerHTML = getEmptyStateHtml();
      return;
    }
    messages.innerHTML = record.html;
    renderMarkdownIn(messages);
    bindMessageActions(messages);
    if (typeof record.scrollTop === "number") {
      messages.scrollTop = record.scrollTop;
    } else {
      scrollChatToBottom();
    }
  }

  function selectConversation(threadId) {
    if (threadId && threadId === getCurrentThreadId()) {
      return;
    }
    persistCurrentChat();

    var index = getThreadIndex();
    var normalizedThreadId = threadId || "";
    var existing = null;
    for (var i = 0; i < index.length; i += 1) {
      if (index[i].id === normalizedThreadId) {
        existing = index[i];
        break;
      }
    }
    if (!existing) {
      normalizedThreadId = newLocalThreadId();
      existing = upsertThread({ id: normalizedThreadId, title: "New chat", conversationId: "", updatedAt: Date.now() });
    }

    var input = document.getElementById("conversation-id");
    if (input) {
      input.value = existing.conversationId || "";
    }

    var key = buildChatKeyFromThreadId(existing.id);
    setActiveChatKey(key);
    renderConversationList();
    if (existing.conversationId) {
      loadConversationFromServer(existing.conversationId);
      return;
    }
    restoreChatByKey(key);
    updateSources([]);
  }

  function createNewConversation() {
    var thread = upsertThread({
      id: newLocalThreadId(),
      title: "New chat",
      conversationId: "",
      updatedAt: Date.now(),
    });
    selectConversation(thread.id);
    showToast("Started a new conversation", "ok");
  }

  function setStreamingContent(target, text) {
    var safeText = escapeHtml(text).replace(/\n/g, "<br>");
    target.innerHTML = safeText + "<span class='typing-cursor' aria-hidden='true'></span>";
  }

  function finalizeStreamingContent(target, text) {
    target.classList.remove("stream-shimmer");
    target.innerHTML = markdownToHtml(text);
    target.dataset.markdownRendered = "1";
    target.dataset.rawAnswer = text;
    enhanceCodeBlocks(target.closest("#chat-messages") || document);
  }

  function enableAssistantActions(target) {
    var article = target.closest("[data-assistant-message='true']");
    if (!article) {
      return;
    }
    article.querySelectorAll(".js-copy-answer, .js-regenerate-answer").forEach(function (button) {
      button.removeAttribute("disabled");
    });

    var conversationId = getCurrentConversationId();
    if (conversationId) {
      article.querySelectorAll(".js-regenerate-answer").forEach(function (button) {
        button.dataset.conversationId = conversationId;
      });
    }
  }

  async function streamChat(target, payload, hasRetried) {
    var accumulated = "";
    setStreamingContent(target, "Thinking...");

    if (activeStreamController && activeStreamController !== null) {
      activeStreamController.abort();
    }

    var controller = new AbortController();
    activeStreamController = controller;
    activeStreamTarget = target;
    setGeneratingState(true, target);

    try {
      var response = await fetch("/app/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        var statusMessage = await parseApiErrorResponse(response, "Streaming failed.");
        target.textContent = statusMessage;
        showToast(statusMessage, "error");
        return;
      }

      var reader = response.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var currentEvent = "message";

      function consumeEvent(eventName, eventData) {
        if (eventName === "token") {
          try {
            var token = JSON.parse(eventData);
            if (token.delta) {
              if (accumulated === "" && token.delta.trim().length > 0 && target.textContent.indexOf("Thinking") !== -1) {
                accumulated = "";
              }
              accumulated += token.delta;
              setStreamingContent(target, accumulated);
              scrollChatToBottom();
            }
          } catch (_err) {
            accumulated += eventData;
            setStreamingContent(target, accumulated);
          }
          return;
        }

        if (eventName === "final") {
          try {
            var finalPayload = JSON.parse(eventData);
            if (finalPayload.answer) {
              accumulated = finalPayload.answer;
            }
            var finalConversationId = String(finalPayload.conversation_id || "").trim();
            if (finalConversationId) {
              adoptServerConversation(finalConversationId, payload.message || "");
            }
            finalizeStreamingContent(target, accumulated);
            updateSources(finalPayload.sources || []);
            enableAssistantActions(target);
            persistCurrentChat();
            scrollChatToBottom();
          } catch (_err) {
            finalizeStreamingContent(target, accumulated);
          }
          return;
        }

        if (eventName === "error") {
          var rawErrorMessage = "Streaming error";
          try {
            var errorPayload = JSON.parse(eventData);
            rawErrorMessage = extractApiErrorMessage(errorPayload, "Streaming error");
          } catch (_err) {
            rawErrorMessage = extractApiErrorMessage(eventData, "Streaming error");
          }

          var normalizedError = String(rawErrorMessage).toLowerCase();
          var canRetryWithoutConversation =
            !hasRetried &&
            payload &&
            payload.conversation_id &&
            (normalizedError.indexOf("fk_messages_conversation_id_conversations") !== -1 ||
              (normalizedError.indexOf("foreignkeyviolation") !== -1 && normalizedError.indexOf("conversation_id") !== -1) ||
              (normalizedError.indexOf("conversation") !== -1 && normalizedError.indexOf("not found") !== -1));

          if (canRetryWithoutConversation) {
            var retryPayload = { message: payload.message || "" };
            var conversationInput = document.getElementById("conversation-id");
            if (conversationInput) {
              conversationInput.value = "";
            }
            selectConversation("");
            showToast("Conversation reset. Retrying message...", "ok");
            streamChat(target, retryPayload, true);
            return;
          }

          target.textContent = rawErrorMessage;
          showToast(rawErrorMessage, "error");
        }
      }

      while (true) {
        var chunkResult = await reader.read();
        if (chunkResult.done) {
          break;
        }
        buffer += decoder.decode(chunkResult.value, { stream: true });
        var parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        parts.forEach(function (rawEvent) {
          if (!rawEvent.trim()) {
            return;
          }
          var lines = rawEvent.split("\n");
          var dataLines = [];
          currentEvent = "message";
          lines.forEach(function (line) {
            if (line.startsWith("event:")) {
              currentEvent = line.slice(6).trim();
            }
            if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trim());
            }
          });
          consumeEvent(currentEvent, dataLines.join("\n"));
        });
      }
    } catch (err) {
      if (err && err.name === "AbortError") {
        if (accumulated.trim()) {
          finalizeStreamingContent(target, accumulated + "\n\n_Stopped generating._");
        } else {
          target.textContent = "Generation stopped.";
        }
        persistCurrentChat();
        return;
      }
      var fatalMessage = extractApiErrorMessage(err, "Unable to stream response");
      target.textContent = fatalMessage;
      showToast(fatalMessage, "error");
    } finally {
      if (activeStreamController === controller) {
        clearActiveStreamState();
      }
    }
  }

  function startPendingStreams(scope) {
    var pending = (scope || document).querySelectorAll(".js-stream-pending");
    pending.forEach(function (node) {
      var streamTarget = node.previousElementSibling && node.previousElementSibling.querySelector("[data-stream-target='true']");
      if (!streamTarget) {
        node.remove();
        return;
      }
      var payload = {
        message: node.dataset.message || "",
      };
      if (node.dataset.conversationId) {
        payload.conversation_id = node.dataset.conversationId;
      }
      streamChat(streamTarget, payload, false).finally(function () {
        node.remove();
        scrollChatToBottom();
      });
    });
  }

  function bindQuickPrompts(scope) {
    var root = scope || document;
    var promptContainer = root.querySelector("#quick-prompts");
    var input = document.getElementById("chat-message-input");
    if (!promptContainer || !input || promptContainer.dataset.bound === "1") {
      return;
    }
    promptContainer.dataset.bound = "1";
    promptContainer.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-prompt]");
      if (!button) {
        return;
      }
      input.value = button.dataset.prompt || "";
      updateMessageCount();
      input.focus();
    });
  }

  function bindConversationSearch(scope) {
    var root = scope || document;
    var input = root.querySelector("#conversation-search");
    if (!input || input.dataset.bound === "1") {
      return;
    }
    input.dataset.bound = "1";
    input.addEventListener("input", function () {
      renderConversationList();
    });
  }

  function updateMessageCount() {
    var input = document.getElementById("chat-message-input");
    var count = document.getElementById("chat-message-count");
    if (!input || !count) {
      return;
    }
    count.textContent = String((input.value || "").length);
  }

  function resetComposer() {
    var input = document.getElementById("chat-message-input");
    if (!input) {
      return;
    }
    input.value = "";
    input.style.height = "auto";
    updateMessageCount();
    input.focus();
  }

  function submitMessage(message, conversationId) {
    var input = document.getElementById("chat-message-input");
    var conversationInput = document.getElementById("conversation-id");
    var form = document.getElementById("chat-form");
    if (!input || !form) {
      return;
    }
    input.value = message;
    if (conversationInput && conversationId !== undefined) {
      conversationInput.value = conversationId || "";
    }
    updateMessageCount();
    form.requestSubmit();
  }

  function bindComposer(scope) {
    var root = scope || document;
    var input = root.querySelector("#chat-message-input");
    var form = document.getElementById("chat-form");
    if (!input || !form || input.dataset.bound === "1") {
      return;
    }
    input.dataset.bound = "1";
    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 260) + "px";
      updateMessageCount();
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    updateMessageCount();
  }

  function bindMessageActions(scope) {
    var root = scope || document;
    root.querySelectorAll(".js-copy-answer").forEach(function (button) {
      if (button.dataset.bound === "1") {
        return;
      }
      button.dataset.bound = "1";
      button.addEventListener("click", async function () {
        var article = button.closest("[data-assistant-message='true']");
        if (!article) {
          return;
        }
        var content = article.querySelector(".assistant-content");
        var raw = (content && (content.dataset.rawAnswer || content.textContent)) || "";
        try {
          await navigator.clipboard.writeText(raw.trim());
          showToast("Copied answer", "ok");
        } catch (_err) {
          showToast("Copy failed", "error");
        }
      });
    });

    root.querySelectorAll(".js-regenerate-answer").forEach(function (button) {
      if (button.dataset.bound === "1") {
        return;
      }
      button.dataset.bound = "1";
      button.addEventListener("click", function () {
        var message = button.dataset.userMessage || "";
        var conversationId = button.dataset.conversationId || getCurrentConversationId() || "";
        if (!message) {
          return;
        }
        submitMessage(message, conversationId);
      });
    });
  }

  function bindDocumentSearch(scope) {
    var root = scope || document;
    var search = root.querySelector("#documents-search");
    if (!search || search.dataset.bound === "1") {
      return;
    }
    search.dataset.bound = "1";
    search.addEventListener("input", function () {
      var query = (search.value || "").trim().toLowerCase();
      var rows = document.querySelectorAll(".document-row");
      rows.forEach(function (row) {
        var haystack = row.getAttribute("data-doc-search") || "";
        row.style.display = !query || haystack.indexOf(query) !== -1 ? "" : "none";
      });
    });
  }

  function bindUploadMeta(scope) {
    var root = scope || document;
    var input = root.querySelector("#upload-file-input");
    var meta = document.getElementById("upload-file-meta");
    if (!input || !meta || input.dataset.bound === "1") {
      return;
    }
    input.dataset.bound = "1";
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) {
        meta.textContent = "Accepted: PDF, TXT, MD";
        return;
      }
      var sizeMb = (file.size / (1024 * 1024)).toFixed(2);
      meta.textContent = file.name + " - " + sizeMb + " MB";
    });
  }

  function bindStreamingControls(scope) {
    var root = scope || document;
    var stopButton = root.querySelector("#chat-stop-button");
    if (!stopButton || stopButton.dataset.bound === "1") {
      return;
    }
    stopButton.dataset.bound = "1";
    stopButton.addEventListener("click", function () {
      stopActiveStream();
    });
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var target = event.target;
    if (target && target.id === "chat-form") {
      var modeInput = document.getElementById("chat-mode-input");
      var streamToggle = document.getElementById("chat-stream-mode");
      var input = document.getElementById("chat-message-input");
      var currentThread = getCurrentThreadMeta();
      if (modeInput && streamToggle) {
        modeInput.value = streamToggle.checked ? "stream" : "sync";
      }
      if (currentThread && currentThread.title === "New chat" && input && input.value.trim()) {
        upsertThread({
          id: currentThread.id,
          title: input.value.trim().slice(0, 48),
          conversationId: currentThread.conversationId || "",
          updatedAt: Date.now(),
        });
        renderConversationList();
      }
    }
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    startPendingStreams(event.target);
    renderMarkdownIn(event.target);
    bindQuickPrompts(event.target);
    bindConversationSearch(event.target);
    bindComposer(event.target);
    bindMessageActions(event.target);
    bindStreamingControls(event.target);
    bindDocumentSearch(event.target);
    bindUploadMeta(event.target);
    persistCurrentChat();
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.target && event.target.id === "chat-form" && event.detail && event.detail.successful) {
      var activeConversationId = getCurrentConversationId();
      if (activeConversationId) {
        adoptServerConversation(activeConversationId);
      }
      resetComposer();
      scrollChatToBottom();
      persistCurrentChat();
      renderConversationList();
    }
  });

  document.body.addEventListener("htmx:responseError", function (event) {
    var xhr = event.detail && event.detail.xhr;
    var status = xhr ? xhr.status : 0;
    var responseText = xhr && typeof xhr.responseText === "string" ? xhr.responseText : "";
    var message = "Request failed";

    if (responseText) {
      try {
        message = extractApiErrorMessage(JSON.parse(responseText), "Request failed");
      } catch (_err) {
        message = extractApiErrorMessage(responseText, "Request failed");
      }
    } else if (status) {
      message = "Request failed (" + status + ")";
    }

    showToast(message, "error");
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeConversationMenus(document);
      closeModal();
    }
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".thread-menu-wrap")) {
      closeConversationMenus(document);
    }
    var modal = document.getElementById("document-modal");
    if (!modal || modal.classList.contains("hidden")) {
      return;
    }
    if (event.target === modal) {
      closeModal();
    }
  });

  bindQuickPrompts(document);
  bindConversationSearch(document);
  bindComposer(document);
  bindMessageActions(document);
  bindStreamingControls(document);
  bindDocumentSearch(document);
  bindUploadMeta(document);

  initializeThreadStore();
  var activeThreadId = getCurrentThreadId();
  if (!activeThreadId) {
    var initialIndex = getThreadIndex();
    if (initialIndex.length) {
      activeThreadId = initialIndex[0].id;
      setActiveChatKey(buildChatKeyFromThreadId(activeThreadId));
    }
  }
  if (activeThreadId) {
    selectConversation(activeThreadId);
  }

  window.retrievia = {
    toggleTheme: toggleTheme,
    selectConversation: selectConversation,
    createNewConversation: createNewConversation,
    updateSources: updateSources,
    scrollToCitation: scrollToCitation,
    scrollChatToBottom: scrollChatToBottom,
    openModal: openModal,
    closeModal: closeModal,
    showToast: showToast,
    renderMarkdownIn: renderMarkdownIn,
  };
})();
