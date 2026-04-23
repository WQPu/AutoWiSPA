const queryParams = new URLSearchParams(window.location.search);
const AUTO_SCROLL_KEYS = new Set(["pipeline-list", "execution-feed"]);

const state = {
  pinnedRun: queryParams.get("run") || "",
  selectedRoot: queryParams.get("root") || "",
  refreshTimer: null,
  durationTimer: null,
  snapshot: null,
  lastRenderSignature: "",
  contextRequestId: 0,
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeDisplayText(value) {
  const text = value === null || value === undefined ? "" : String(value);
  let normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const escapedNewlineCount = (normalized.match(/\\n/g) || []).length;
  const newlineCount = (normalized.match(/\n/g) || []).length;

  if (escapedNewlineCount && escapedNewlineCount >= newlineCount) {
    normalized = normalized.replace(/\\r\\n/g, "\n").replace(/\\n/g, "\n").replace(/\\t/g, "\t");
  }
  return normalized;
}

function nl2html(value) {
  return escapeHtml(normalizeDisplayText(value)).replace(/\n/g, "<br>");
}

function renderInlineMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${label}</a>`;
  });
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function splitMarkdownTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isMarkdownTableRow(line) {
  const trimmed = line.trim();
  return trimmed.includes("|") && /^\|?.+\|.+\|?$/.test(trimmed);
}

function isMarkdownTableSeparator(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderMarkdownTable(headerLine, bodyLines) {
  const headers = splitMarkdownTableRow(headerLine);
  const headerHtml = headers.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("");
  const bodyHtml = bodyLines
    .map((line) => {
      const cells = splitMarkdownTableRow(line);
      return `<tr>${cells.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join("")}</tr>`;
    })
    .join("");

  return `
    <div class="table-scroll">
      <table class="data-table markdown-table">
        <thead><tr>${headerHtml}</tr></thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}

function detectBlockMathDelimiter(line) {
  const trimmed = line.trim();
  if (trimmed === '$$') {
    return { open: '$$', close: '$$' };
  }
  if (trimmed === '\\[') {
    return { open: '\\[', close: '\\]' };
  }
  return null;
}

function collectBlockMath(lines, startIndex) {
  const delimiter = detectBlockMathDelimiter(lines[startIndex] || '');
  if (!delimiter) {
    return null;
  }

  const blockLines = [delimiter.open];
  let cursor = startIndex + 1;
  while (cursor < lines.length) {
    const currentLine = lines[cursor];
    blockLines.push(currentLine);
    if (currentLine.trim() === delimiter.close) {
      return {
        html: `<div class="math-block">${escapeHtml(blockLines.join('\n'))}</div>`,
        nextIndex: cursor,
      };
    }
    cursor += 1;
  }

  return {
    html: `<div class="math-block">${escapeHtml(blockLines.join('\n'))}</div>`,
    nextIndex: lines.length - 1,
  };
}

function renderMarkdown(value) {
  const lines = normalizeDisplayText(value).split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let listItems = [];
  let inCodeBlock = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${paragraph.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listType) {
      return;
    }
    html.push(`<${listType}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${listType}>`);
    listItems = [];
    listType = "";
  };

  const flushCodeBlock = () => {
    html.push(`<pre class="formatted-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (inCodeBlock) {
      if (line.trim().startsWith("```")) {
        inCodeBlock = false;
        flushCodeBlock();
      } else {
        codeLines.push(line);
      }
      continue;
    }

    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      inCodeBlock = true;
      codeLines = [];
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const blockMath = collectBlockMath(lines, index);
    if (blockMath) {
      flushParagraph();
      flushList();
      html.push(blockMath.html);
      index = blockMath.nextIndex;
      continue;
    }

    if (index + 1 < lines.length && isMarkdownTableRow(line) && isMarkdownTableSeparator(lines[index + 1])) {
      flushParagraph();
      flushList();
      const bodyLines = [];
      index += 2;
      while (index < lines.length && lines[index].trim() && isMarkdownTableRow(lines[index])) {
        bodyLines.push(lines[index]);
        index += 1;
      }
      html.push(renderMarkdownTable(line, bodyLines));
      index -= 1;
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2].trim())}</h${level}>`);
      continue;
    }

    const bulletMatch = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      if (listType && listType !== "ul") {
        flushList();
      }
      listType = "ul";
      listItems.push(bulletMatch[1]);
      continue;
    }

    const orderedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== "ol") {
        flushList();
      }
      listType = "ol";
      listItems.push(orderedMatch[1]);
      continue;
    }

    const quoteMatch = line.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInlineMarkdown(quoteMatch[1])}</blockquote>`);
      continue;
    }

    paragraph.push(line);
  }

  if (inCodeBlock) {
    flushCodeBlock();
  }
  flushParagraph();
  flushList();
  return html.join("");
}

function renderJsonContent(value) {
  const normalized = normalizeDisplayText(value);
  let formatted = normalized;

  try {
    formatted = JSON.stringify(JSON.parse(normalized), null, 2);
  } catch {
    formatted = normalized;
  }

  return `<pre class="formatted-json"><code>${escapeHtml(formatted)}</code></pre>`;
}

function renderTableContent(table, emptyLabel = "No table preview is available for this view.") {
  if (!table || !Array.isArray(table.columns) || !table.columns.length || !Array.isArray(table.rows) || !table.rows.length) {
    return `<div class="empty-state subtle-placeholder">${escapeHtml(emptyLabel)}</div>`;
  }

  const headerHtml = table.columns.map((column) => `<th>${escapeHtml(column.label || column.key || "")}</th>`).join("");
  const bodyHtml = table.rows
    .map(
      (row) => `
        <tr>
          ${table.columns.map((column) => `<td>${escapeHtml(row?.[column.key] ?? "-")}</td>`).join("")}
        </tr>
      `,
    )
    .join("");

  return `
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>${headerHtml}</tr>
        </thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}

function renderFormattedContent(value, format = "text", emptyLabel = "No content is available for this view.") {
  if (format === "table") {
    return renderTableContent(value, emptyLabel);
  }

  const normalized = normalizeDisplayText(value);
  if (!normalized.trim()) {
    return `<div class="empty-state subtle-placeholder">${escapeHtml(emptyLabel)}</div>`;
  }

  if (format === "markdown") {
    return `<div class="rich-markdown">${renderMarkdown(normalized)}</div>`;
  }
  if (format === "json") {
    return renderJsonContent(normalized);
  }
  if (format === "code") {
    return `<pre class="formatted-code"><code>${escapeHtml(normalized)}</code></pre>`;
  }
  return `<div class="formatted-text">${nl2html(normalized)}</div>`;
}

function renderMathContent(element) {
  if (!element || typeof window.renderMathInElement !== "function") {
    return;
  }

  window.renderMathInElement(element, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
  });
}

function setFormattedContent(element, value, format = "text", emptyLabel = "No content is available for this view.") {
  if (!element) {
    return;
  }
  element.innerHTML = renderFormattedContent(value, format, emptyLabel);
  renderMathContent(element);
}

function renderChips(items, extraClass = "") {
  if (!items || !items.length) {
    return `<span class="meta-chip ${extraClass}">N/A</span>`;
  }

  return items
    .map((item) => `<span class="meta-chip ${extraClass}">${escapeHtml(item)}</span>`)
    .join("");
}

function renderStatusBadge(status, label) {
  return `<span class="status-badge ${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function renderContextButton(context, extraClass = "") {
  if (!context) {
    return "";
  }

  const attributes = Object.entries(context)
    .map(([key, value]) => {
      if (value === null || value === undefined || value === "") {
        return "";
      }
      return `data-context-${escapeHtml(key)}="${escapeHtml(value)}"`;
    })
    .join(" ");

  return `
    <button type="button" class="context-button ${extraClass}" ${attributes}>
      ${escapeHtml(context.label || "View Full Context")}
    </button>
  `;
}

function renderErrorMessage(message) {
  if (!message) {
    return "";
  }

  return `<div class="error-message">${nl2html(message)}</div>`;
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setTopTag(id, text, mode = "") {
  const element = document.getElementById(id);
  element.textContent = text;
  element.className = `top-tag ${mode}`.trim();
}

function buildSnapshotSignature(snapshot) {
  return JSON.stringify({
    run: {
      name: snapshot.run.name,
      path: snapshot.run.path,
      root_key: snapshot.run.root_key,
      available_roots: (snapshot.run.available_roots || []).map((root) => `${root.key}:${root.label}`),
      updated_at: snapshot.run.updated_at,
      available_runs: (snapshot.run.available_runs || []).map((run) => `${run.name}:${run.modified || ""}`),
    },
    mission: snapshot.mission,
    overview_cards: snapshot.overview_cards,
    pipeline: snapshot.pipeline,
    execution_feed: snapshot.execution_feed,
    focus: snapshot.focus,
    runtime: {
      live_label: snapshot.runtime.live_label,
      static_lines: snapshot.runtime.static_lines,
      error_lines: snapshot.runtime.error_lines,
      latest_activity_ts: snapshot.runtime.latest_activity_ts,
    },
    llm_feed: snapshot.llm_feed,
    stage_cards: snapshot.stage_cards,
    report: snapshot.report,
    performance: snapshot.performance,
  });
}

function captureScrollState() {
  const positions = { windowY: window.scrollY };
  document.querySelectorAll("[data-scroll-key]").forEach((element) => {
    if (AUTO_SCROLL_KEYS.has(element.dataset.scrollKey)) {
      return;
    }
    positions[element.dataset.scrollKey] = element.scrollTop;
  });
  return positions;
}

function scrollElementToBottom(scrollKey) {
  const element = document.querySelector(`[data-scroll-key="${scrollKey}"]`);
  if (element) {
    element.scrollTop = element.scrollHeight;
  }
}

function restoreScrollState(positions) {
  window.requestAnimationFrame(() => {
    if (typeof positions.windowY === "number") {
      window.scrollTo({ top: positions.windowY, left: 0, behavior: "auto" });
    }
    document.querySelectorAll("[data-scroll-key]").forEach((element) => {
      if (AUTO_SCROLL_KEYS.has(element.dataset.scrollKey)) {
        return;
      }
      const nextTop = positions[element.dataset.scrollKey];
      if (typeof nextTop === "number") {
        element.scrollTop = nextTop;
      }
    });
    AUTO_SCROLL_KEYS.forEach((scrollKey) => {
      scrollElementToBottom(scrollKey);
    });
  });
}

function updateLocationQuery() {
  const url = new URL(window.location.href);
  if (state.pinnedRun) {
    url.searchParams.set("run", state.pinnedRun);
  } else {
    url.searchParams.delete("run");
  }
  if (state.selectedRoot) {
    url.searchParams.set("root", state.selectedRoot);
  } else {
    url.searchParams.delete("root");
  }
  window.history.replaceState({}, "", url);
}

function formatDurationSinceLatestActivity(latestActivityTs) {
  if (!Number.isFinite(latestActivityTs) || latestActivityTs <= 0) {
    return "-- min -- sec";
  }

  const ageSeconds = Math.max(0, Math.floor(Date.now() / 1000 - latestActivityTs));
  if (ageSeconds > 600) {
    return "-- min -- sec";
  }

  const minutes = Math.floor(ageSeconds / 60);
  const seconds = ageSeconds % 60;
  return `${minutes} min ${seconds} sec`;
}

function updateRuntimeDuration() {
  const durationElement = document.getElementById("runtime-duration");
  if (!durationElement) {
    return;
  }

  const latestActivityTs = Number(state.snapshot?.runtime?.latest_activity_ts || 0);
  durationElement.textContent = `Duration since latest activity: ${formatDurationSinceLatestActivity(latestActivityTs)}`;
}

function setMessageBlock(id, message) {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }

  if (message) {
    element.hidden = false;
    element.innerHTML = nl2html(message);
  } else {
    element.hidden = true;
    element.innerHTML = "";
  }
}

function setActionBlock(id, context) {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }

  const content = renderContextButton(context);
  element.innerHTML = content;
  element.style.display = content ? "flex" : "none";
}

function buildContextUrl(descriptor) {
  const runName = state.snapshot?.run?.name;
  if (!runName || runName === "NO RUN") {
    throw new Error("No experiment run is available for context preview.");
  }

  const url = new URL(`/api/context/${encodeURIComponent(runName)}`, window.location.origin);
  const activeRoot = state.selectedRoot || state.snapshot?.run?.root_key || "";
  if (activeRoot) {
    url.searchParams.set("root", activeRoot);
  }
  url.searchParams.set("source", descriptor.source || "");
  if (descriptor.step) {
    url.searchParams.set("step", descriptor.step);
  }
  if (descriptor.slot) {
    url.searchParams.set("slot", descriptor.slot);
  }
  if (descriptor.index !== undefined && descriptor.index !== null && descriptor.index !== "") {
    url.searchParams.set("index", descriptor.index);
  }
  return `${url.pathname}${url.search}`;
}

function buildDashboardQuery() {
  const params = new URLSearchParams();
  if (state.selectedRoot) {
    params.set("root", state.selectedRoot);
  }
  if (state.pinnedRun) {
    params.set("run", state.pinnedRun);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function openContextModalShell({ title = "Full Context", source = "", content = "", error = "", format = "text" }) {
  const modal = document.getElementById("context-modal");
  const sourceElement = document.getElementById("context-modal-source");
  document.getElementById("context-modal-title").textContent = title;
  sourceElement.textContent = source;
  sourceElement.style.display = source ? "block" : "none";
  setMessageBlock("context-modal-error", "");
  setFormattedContent(
    document.getElementById("context-modal-content"),
    content || (error ? "" : ""),
    format,
    "No context content is available for this view.",
  );
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

function closeContextModal() {
  const modal = document.getElementById("context-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

async function handleContextButtonClick(button) {
  const descriptor = {
    source: button.dataset.contextSource || "",
    step: button.dataset.contextStep || "",
    slot: button.dataset.contextSlot || "",
    index: button.dataset.contextIndex || "",
  };

  const requestId = ++state.contextRequestId;
  openContextModalShell({
    title: button.textContent.trim() || "Full Context",
    source: "Loading...",
    content: "Loading full context...",
    error: "",
    format: "text",
  });

  try {
    const payload = await fetchJson(buildContextUrl(descriptor));
    if (requestId !== state.contextRequestId) {
      return;
    }
    openContextModalShell(payload);
  } catch (error) {
    if (requestId !== state.contextRequestId) {
      return;
    }
    openContextModalShell({
      title: "Full Context",
      source: "",
      content: "Full context is temporarily unavailable.",
      error: "",
      format: "text",
    });
  }
}

function bindContextModal() {
  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("[data-context-source]");
    if (button) {
      event.preventDefault();
      handleContextButtonClick(button);
      return;
    }

    if (event.target.closest("[data-context-close]")) {
      closeContextModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeContextModal();
    }
  });
}

function renderRunSelector(snapshot) {
  const selector = document.getElementById("run-selector");
  const runs = snapshot.run.available_runs || [];
  const selectedRun = state.pinnedRun || "";

  const autoFollowOption = `<option value="">AUTO-FOLLOW LATEST TASK</option>`;
  const runOptions = runs
    .map(
      (run) => `
        <option value="${escapeHtml(run.name)}">
          ${escapeHtml(run.name)}${run.modified ? ` · ${escapeHtml(run.modified)}` : ""}
        </option>
      `,
    )
    .join("");

  selector.innerHTML = `${autoFollowOption}${runOptions}`;
  selector.disabled = runs.length === 0;

  if (selectedRun && runs.some((run) => run.name === selectedRun)) {
    selector.value = selectedRun;
  } else {
    selector.value = "";
  }
}

function renderRootSelector(snapshot) {
  const selector = document.getElementById("root-selector");
  const roots = snapshot.run.available_roots || [];
  const selectedRoot = state.selectedRoot || snapshot.run.root_key || "";

  selector.innerHTML = roots
    .map((root) => `<option value="${escapeHtml(root.key)}">${escapeHtml(root.label)}</option>`)
    .join("");
  selector.disabled = roots.length === 0;

  if (selectedRoot && roots.some((root) => root.key === selectedRoot)) {
    selector.value = selectedRoot;
  } else if (snapshot.run.root_key) {
    selector.value = snapshot.run.root_key;
  }
}

function renderHeader(snapshot) {
  renderRunSelector(snapshot);
  renderRootSelector(snapshot);
  setTopTag("run-name", snapshot.run.name || "AUTO-FOLLOW");
  setTopTag("active-stage-tag", snapshot.focus.stage_label || "WAITING");
  setTopTag(
    "live-tag",
    snapshot.runtime.live_label || "IDLE",
    (snapshot.runtime.live_label || "idle").toLowerCase(),
  );
  setTopTag("updated-tag", snapshot.run.updated_at || "N/A");
  document.title = `AUTO•WISPA · ${snapshot.run.name || "Stage Monitor"}`;
}

function renderMission(snapshot) {
  setFormattedContent(
    document.getElementById("mission-query"),
    snapshot.mission.query || "",
    snapshot.mission.format || "text",
    "No mission query is available for the selected task.",
  );
  document.getElementById("mission-chips").innerHTML = renderChips(snapshot.mission.chips || []);
}

function renderOverview(snapshot) {
  const container = document.getElementById("overview-cards");
  container.innerHTML = (snapshot.overview_cards || [])
    .map(
      (card) => `
        <div class="metric-tile">
          <div class="metric-label">${escapeHtml(card.label)}</div>
          <div class="metric-value">${escapeHtml(card.value)}</div>
        </div>
      `,
    )
    .join("");
}

function renderPipeline(snapshot) {
  const container = document.getElementById("pipeline-list");
  const items = snapshot.pipeline || [];
  document.getElementById("pipeline-meta").textContent = `${items.length} Steps`;

  if (!items.length) {
    container.innerHTML = `<div class="empty-state subtle-placeholder">No workflow steps are available yet.</div>`;
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="pipeline-item ${escapeHtml(item.status)}">
          <div class="pipeline-stage-code">${escapeHtml(item.code)}</div>
          <div class="pipeline-copy">
            <div class="pipeline-title">${escapeHtml(item.label)}</div>
            <div class="pipeline-summary">${escapeHtml(item.summary || "Awaiting output")}</div>
          </div>
          ${renderStatusBadge(item.status, item.status_label)}
        </div>
      `,
    )
    .join("");
}

function renderExecutionFeed(snapshot) {
  const container = document.getElementById("execution-feed");
  const items = snapshot.execution_feed || [];
  document.getElementById("execution-meta").textContent = `All Events (${items.length})`;

  if (!items.length) {
    container.innerHTML = `<div class="empty-state subtle-placeholder">No execution trace is available yet. Waiting for a checkpoint or execution_trace artifact.</div>`;
    return;
  }

  container.innerHTML = items
    .map(
      (item, index) => `
        <div class="feed-item">
          <div class="feed-stage">Event ${String(index + 1).padStart(2, "0")} · ${escapeHtml(item.stage_label)}</div>
          <div class="feed-title">${escapeHtml(item.title)}</div>
          ${(item.summary_lines || []).length
            ? `<ul>${item.summary_lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
            : ""
          }
        </div>
      `,
    )
    .join("");
}

function renderFocus(snapshot) {
  const focus = snapshot.focus || {};
  document.getElementById("focus-stage").textContent = focus.stage_label || "Waiting";
  document.getElementById("focus-headline").textContent = focus.headline || "";
  document.getElementById("focus-meta").innerHTML = renderChips(focus.meta || [], "compact");

  const focusBody = document.getElementById("focus-body");
  setFormattedContent(
    focusBody,
    focus.body || "",
    focus.body_format || "text",
    "No focus preview is available for the current step.",
  );
  focusBody.classList.toggle("subtle-placeholder", Boolean(focus.is_placeholder));

  const focusStatus = document.getElementById("focus-status");
  focusStatus.className = `status-badge ${focus.status || "pending"}`;
  focusStatus.textContent = focus.status_label || "Pending";

  const summary = document.getElementById("focus-summary");
  if ((focus.summary_lines || []).length) {
    summary.innerHTML = `<ul>${focus.summary_lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
    summary.style.display = "block";
  } else {
    summary.style.display = "none";
    summary.innerHTML = "";
  }

  setMessageBlock("focus-error", focus.error_message || "");
  setActionBlock("focus-actions", focus.context || null);
}

function renderRuntime(snapshot) {
  const runtime = snapshot.runtime || {};
  const container = document.getElementById("runtime-lines");
  const staticLines = runtime.static_lines || [];

  container.innerHTML = [
    `<div id="runtime-duration" class="runtime-line"></div>`,
    ...staticLines.map((line) => `<div class="runtime-line">${escapeHtml(line)}</div>`),
  ].join("");

  updateRuntimeDuration();
}

function renderLlmFeed(snapshot) {
  const container = document.getElementById("llm-feed");
  const entries = snapshot.llm_feed.entries || [];
  document.getElementById("llm-model-tag").textContent = snapshot.llm_feed.latest_model || "idle";

  if (!entries.length) {
    container.innerHTML = `<div class="empty-state subtle-placeholder">No LLM call log has been written for the selected run yet.</div>`;
    return;
  }

  container.innerHTML = entries
    .map(
      (entry, index) => `
        <article class="llm-call">
          <header>
            <span class="call-model">${escapeHtml(entry.model)}</span>
            <span class="call-time">${escapeHtml(entry.timestamp)}</span>
          </header>
          <div class="call-block">
            <div class="call-block-header">
              <div class="call-label">Prompt</div>
              ${renderContextButton(entry.prompt_context, "inline")}
            </div>
            <div class="call-text" data-scroll-key="llm-prompt-${index}">${nl2html(entry.prompt_preview || "")}</div>
          </div>
          <div class="call-block">
            <div class="call-block-header">
              <div class="call-label">Response</div>
              ${renderContextButton(entry.response_context, "inline")}
            </div>
            <div class="call-text" data-scroll-key="llm-response-${index}">${nl2html(entry.response_preview || "")}</div>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderStageCards(snapshot) {
  const container = document.getElementById("stage-cards");
  container.innerHTML = (snapshot.stage_cards || [])
    .map(
      (card) => `
        <article class="panel stage-card status-${escapeHtml(card.status)} ${card.is_placeholder ? "subtle-placeholder" : ""}">
          <div class="stage-card-header">
            <div class="stage-title">${escapeHtml(card.code)} · ${escapeHtml(card.label)}</div>
            ${renderStatusBadge(card.status, card.status_label)}
          </div>
          <div class="stage-headline">${escapeHtml(card.headline)}</div>
          <div class="stage-meta">${renderChips(card.meta || [], "compact")}</div>
          <div class="stage-body" data-scroll-key="stage-body-${escapeHtml(card.key)}">${renderFormattedContent(
            card.body || "",
            card.body_format || "text",
            "No preview is available for this stage.",
          )}</div>
          ${renderErrorMessage(card.error_message || "")}
          ${card.context ? `<div class="stage-footer">${renderContextButton(card.context)}</div>` : ""}
        </article>
      `,
    )
    .join("");
  renderMathContent(container);
}

function renderReport(snapshot) {
  const headline = document.getElementById("report-headline");
  const content = document.getElementById("report-content");
  headline.textContent = snapshot.report.headline || "Final Report / Live Draft";
  setFormattedContent(
    content,
    snapshot.report.content || "",
    snapshot.report.format || "text",
    "No report text is available yet.",
  );
  content.classList.toggle("subtle-placeholder", Boolean(snapshot.report.is_placeholder));
  setMessageBlock("report-error", snapshot.report.error_message || "");
  setActionBlock("report-actions", snapshot.report.context || null);
}

function renderPerformance(snapshot) {
  const metricContainer = document.getElementById("performance-metrics");
  const summaryContainer = document.getElementById("performance-summary");
  const plotContainer = document.getElementById("performance-plot");
  const summaryFormat = snapshot.performance.summary_format || "text";
  const summaryValue = summaryFormat === "table" ? snapshot.performance.summary_table : snapshot.performance.summary;

  metricContainer.innerHTML = (snapshot.performance.metrics || [])
    .map(
      (metric) => `
        <div class="metric-pill">
          <div class="metric-pill-label">${escapeHtml(metric.label)}</div>
          <div class="metric-pill-value">${escapeHtml(metric.value)}</div>
        </div>
      `,
    )
    .join("");

  setMessageBlock("performance-error", snapshot.performance.error_message || "");

  setFormattedContent(
    summaryContainer,
    summaryValue || "",
    summaryFormat,
    "No performance summary is available for the selected run.",
  );
  summaryContainer.classList.toggle("subtle-placeholder", Boolean(snapshot.performance.is_placeholder));
  setActionBlock("performance-actions", snapshot.performance.context || null);

  if (snapshot.performance.plot_url) {
    const plotUrl = new URL(snapshot.performance.plot_url, window.location.origin);
    const activeRoot = state.selectedRoot || snapshot.run.root_key || "";
    if (activeRoot) {
      plotUrl.searchParams.set("root", activeRoot);
    }
    if (snapshot.performance.plot_version) {
      plotUrl.searchParams.set("v", snapshot.performance.plot_version);
    }
    const nextPlotSrc = `${plotUrl.pathname}${plotUrl.search}`;
    const currentImage = plotContainer.querySelector("img");

    if (!currentImage || currentImage.dataset.src !== nextPlotSrc) {
      plotContainer.innerHTML = `<img src="${nextPlotSrc}" data-src="${nextPlotSrc}" alt="Performance plot">`;
    }
  } else {
    plotContainer.innerHTML = `<div class="empty-state subtle-placeholder">No plottable performance curve is available for the selected run.</div>`;
  }
}

function renderDashboard(snapshot) {
  renderHeader(snapshot);
  renderMission(snapshot);
  renderOverview(snapshot);
  renderPipeline(snapshot);
  renderExecutionFeed(snapshot);
  renderFocus(snapshot);
  renderRuntime(snapshot);
  renderLlmFeed(snapshot);
  renderStageCards(snapshot);
  renderReport(snapshot);
  renderPerformance(snapshot);
}

function renderError(error) {
  setTopTag("live-tag", "ERROR", "error");
  document.getElementById("mission-query").innerHTML = nl2html(`Dashboard refresh failed: ${error.message}`);
}

async function refreshDashboard({ force = false } = {}) {
  const suffix = buildDashboardQuery();

  try {
    const snapshot = await fetchJson(`/api/dashboard${suffix}`);
    const signature = buildSnapshotSignature(snapshot);

    if (!force && signature === state.lastRenderSignature) {
      state.snapshot = snapshot;
      updateRuntimeDuration();
      return;
    }

    const scrollState = captureScrollState();
    state.snapshot = snapshot;
    renderDashboard(snapshot);
    state.lastRenderSignature = signature;
    restoreScrollState(scrollState);
  } catch (error) {
    console.error(error);
    renderError(error);
  }
}

async function pickDataFolder() {
  const response = await fetch("/api/roots/pick", {
    method: "POST",
    cache: "no-store",
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json();
}

function bindControls() {
  document.getElementById("run-selector").addEventListener("change", async (event) => {
    state.pinnedRun = event.target.value || "";
    updateLocationQuery();
    await refreshDashboard({ force: true });
  });

  document.getElementById("root-selector").addEventListener("change", async (event) => {
    state.selectedRoot = event.target.value || "";
    state.pinnedRun = "";
    state.lastRenderSignature = "";
    updateLocationQuery();
    await refreshDashboard({ force: true });
  });

  document.getElementById("root-picker-button").addEventListener("click", async () => {
    try {
      const payload = await pickDataFolder();
      if (!payload || !payload.root_key) {
        return;
      }
      state.selectedRoot = payload.root_key;
      state.pinnedRun = "";
      state.lastRenderSignature = "";
      updateLocationQuery();
      await refreshDashboard({ force: true });
    } catch (error) {
      console.error(error);
      renderError(error);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindControls();
  bindContextModal();
  refreshDashboard({ force: true });
  state.refreshTimer = window.setInterval(() => {
    refreshDashboard();
  }, 2500);
  state.durationTimer = window.setInterval(() => {
    updateRuntimeDuration();
  }, 1000);
});