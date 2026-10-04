(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const STATIC_DEMO = document.body.dataset.staticDemo === "true";
  const PREPARED_EXAMPLES = window.TRACEAID_DEMO?.examples || [];

  const state = {
    examples: [],
    selectedExample: null,
    lastResponse: null,
    lastPayload: null,
    activeArtifact: "curl",
    progressTimer: null,
    toastTimer: null
  };

  const elements = {
    form: $("#diagnosis-form"),
    method: $("#request-method"),
    url: $("#request-url"),
    requestHeaders: $("#request-headers"),
    requestBody: $("#request-body"),
    statusCode: $("#status-code"),
    latency: $("#latency-ms"),
    observedError: $("#observed-error"),
    responseHeaders: $("#response-headers"),
    responseBody: $("#response-body"),
    executeProbe: $("#execute-probe"),
    useAi: $("#use-ai"),
    observedDetails: $("#observed-details"),
    analyzeButton: $("#analyze-button"),
    emptyState: $("#empty-state"),
    progressState: $("#progress-state"),
    errorState: $("#error-state"),
    resultContent: $("#result-content"),
    resultMode: $("#result-mode"),
    fallbackNotice: $("#fallback-notice"),
    exampleGrid: $("#example-grid"),
    toast: $("#toast")
  };

  function stringify(value, fallback = "") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "string") return value;
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  }

  function parseJsonField(element, options = {}) {
    const value = element.value.trim();
    if (!value) return options.emptyValue ?? null;
    try {
      const parsed = JSON.parse(value);
      if (options.objectOnly && (Array.isArray(parsed) || parsed === null || typeof parsed !== "object")) {
        throw new Error("Enter a JSON object enclosed in { }.");
      }
      return parsed;
    } catch (error) {
      if (options.allowText) return value;
      error.fieldName = options.name;
      throw error;
    }
  }

  function setFieldError(name, message) {
    const errorElement = $(`#${name}-error`);
    const inputId = { url: "request-url", headers: "request-headers", body: "request-body" }[name] || name;
    const inputElement = $(`#${inputId}`);
    if (errorElement) errorElement.textContent = message || "";
    if (inputElement) inputElement.setAttribute("aria-invalid", message ? "true" : "false");
  }

  function validateJsonEditor(element, validityElement, objectOnly, errorName) {
    const value = element.value.trim();
    if (!value) {
      validityElement.textContent = "empty";
      validityElement.classList.remove("invalid");
      setFieldError(errorName, "");
      return true;
    }
    try {
      const parsed = JSON.parse(value);
      if (objectOnly && (parsed === null || Array.isArray(parsed) || typeof parsed !== "object")) throw new Error("Expected a JSON object.");
      validityElement.textContent = "valid";
      validityElement.classList.remove("invalid");
      setFieldError(errorName, "");
      return true;
    } catch (error) {
      validityElement.textContent = "invalid";
      validityElement.classList.add("invalid");
      setFieldError(errorName, error.message.replace(/^JSON\.parse: /, ""));
      return false;
    }
  }

  function collectPayload() {
    let valid = true;
    const rawUrl = elements.url.value.trim();
    setFieldError("url", "");

    if (!rawUrl) {
      setFieldError("url", "Add the URL that produced the failure.");
      valid = false;
    } else {
      try {
        const parsedUrl = new URL(rawUrl);
        if (!["http:", "https:"].includes(parsedUrl.protocol)) throw new Error();
      } catch {
        setFieldError("url", "Use a complete HTTP or HTTPS URL.");
        valid = false;
      }
    }

    let headers = {};
    let body = null;
    let observedHeaders = {};
    try { headers = parseJsonField(elements.requestHeaders, { objectOnly: true, emptyValue: {}, name: "headers" }); }
    catch (error) { setFieldError("headers", error.message); valid = false; }
    try { body = parseJsonField(elements.requestBody, { emptyValue: null, name: "body" }); }
    catch (error) { setFieldError("body", error.message); valid = false; }
    try { observedHeaders = parseJsonField(elements.responseHeaders, { objectOnly: true, emptyValue: {}, name: "response-headers" }); }
    catch (error) { setFieldError("response-headers", error.message); valid = false; }

    const statusValue = elements.statusCode.value.trim();
    if (statusValue && (+statusValue < 100 || +statusValue > 599)) {
      showToast("Status code must be between 100 and 599.");
      valid = false;
    }
    if (!valid) return null;

    const observed = {
      status_code: statusValue ? Number(statusValue) : null,
      headers: observedHeaders,
      body: parseJsonField(elements.responseBody, { allowText: true, emptyValue: null }),
      latency_ms: elements.latency.value.trim() ? Number(elements.latency.value) : null,
      error: elements.observedError.value.trim() || null
    };
    const hasObservedEvidence = observed.status_code !== null
      || observed.latency_ms !== null
      || observed.body !== null
      || observed.error !== null
      || Object.keys(observed.headers).length > 0;

    return {
      request: {
        method: elements.method.value,
        url: rawUrl,
        headers,
        body
      },
      observed: hasObservedEvidence ? observed : null,
      execute_probe: elements.executeProbe.checked,
      use_ai: elements.useAi.checked
    };
  }

  function normalizeExamples(payload) {
    const collection = Array.isArray(payload) ? payload : payload?.examples || payload?.items || payload?.data;
    if (!Array.isArray(collection)) return [];
    return collection.map((item, index) => {
      const examplePayload = item.payload || item.input || item;
      return ({
      id: item.id || item.slug || `example-${index + 1}`,
      title: item.title || item.name || item.diagnosis?.title || `Incident ${index + 1}`,
      description: item.description || item.summary || item.diagnosis?.summary || "Sanitized API incident for diagnostic analysis.",
      category: item.category || item.kind || item.diagnosis?.category || "API failure",
      request: examplePayload.request || {},
      observed: examplePayload.observed || {},
      diagnosis: item.diagnosis || examplePayload.diagnosis || item.expected?.diagnosis || null,
      report: item.report || null,
      execute_probe: Boolean(examplePayload.execute_probe),
      use_ai: Boolean(examplePayload.use_ai)
    });
    });
  }

  function normalizeEvidence(evidence) {
    if (!Array.isArray(evidence)) {
      if (evidence && typeof evidence === "object") {
        return Object.entries(evidence).map(([label, detail]) => ({ label, detail: stringify(detail) }));
      }
      return evidence ? [{ label: "Observed signal", detail: String(evidence) }] : [];
    }
    return evidence.map((item, index) => {
      if (typeof item === "string") return { label: `Signal ${index + 1}`, detail: item };
      return {
        label: item.label || item.title || item.signal || item.name || `Signal ${index + 1}`,
        detail: stringify(item.detail || item.description || item.value || item.reason || "Supports the ranked diagnosis.")
      };
    });
  }

  function normalizeResponse(payload, requestPayload) {
    const diagnosis = payload?.diagnosis || payload?.result?.diagnosis || payload?.result || payload || {};
    const artifacts = payload?.artifacts || payload?.result?.artifacts || diagnosis?.artifacts || {};
    const rawConfidence = diagnosis.confidence ?? diagnosis.score ?? 0.75;
    const confidence = Number(rawConfidence) > 1 ? Number(rawConfidence) / 100 : Number(rawConfidence);

    return {
      id: payload?.id || payload?.trace_id || payload?.diagnosis_id || `TRC-${Date.now().toString(36).toUpperCase()}`,
      created_at: payload?.created_at || payload?.timestamp || new Date().toISOString(),
      mode: payload?.mode || payload?.metadata?.mode || (requestPayload?.use_ai ? "AI assisted" : "Deterministic"),
      rawReport: payload,
      redacted_request: payload?.redacted_request || null,
      diagnosis: {
        severity: String(diagnosis.severity || diagnosis.level || "medium").toLowerCase(),
        title: diagnosis.title || diagnosis.name || diagnosis.root_cause || "API request failure identified",
        summary: diagnosis.summary || diagnosis.explanation || "TraceAid correlated the supplied request and response signals.",
        confidence: Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : 0.75,
        likely_cause: diagnosis.likely_cause || diagnosis.root_cause || diagnosis.cause || "The observed response matches a known API failure pattern.",
        evidence: normalizeEvidence(diagnosis.evidence || diagnosis.signals || []),
        fix_steps: Array.isArray(diagnosis.fix_steps || diagnosis.recommendations || diagnosis.actions)
          ? (diagnosis.fix_steps || diagnosis.recommendations || diagnosis.actions).map(item => typeof item === "string" ? item : item.description || item.title || stringify(item))
          : [diagnosis.fix_steps || diagnosis.recommendation || "Review the generated corrected request and retry safely."].filter(Boolean)
      },
      artifacts: {
        corrected_curl: artifacts.corrected_curl || "",
        python_snippet: artifacts.python_snippet || "",
        pytest_test: artifacts.pytest_test || "",
        markdown_report: artifacts.markdown_report || artifacts.markdown || null
      },
      probe: payload?.probe || null,
      metadata: payload?.metadata || {}
    };
  }

  function showView(view) {
    elements.emptyState.hidden = view !== "empty";
    elements.progressState.hidden = view !== "progress";
    elements.errorState.hidden = view !== "error";
    elements.resultContent.hidden = view !== "result";
    elements.resultMode.hidden = view !== "result";
  }

  function startProgress() {
    showView("progress");
    clearInterval(state.progressTimer);
    const labels = ["Parsing request evidence…", "Matching failure signatures…", "Ranking likely causes…", "Building repair artifacts…"];
    const widths = [18, 43, 69, 88];
    let step = 0;
    const render = () => {
      $("#progress-title").textContent = labels[step];
      $("#progress-bar").style.width = `${widths[step]}%`;
      $$("#progress-steps li").forEach((item, index) => {
        item.classList.toggle("active", index === step);
        item.classList.toggle("done", index < step);
      });
      step = Math.min(step + 1, labels.length - 1);
    };
    render();
    state.progressTimer = setInterval(render, 560);
  }

  function finishProgress() {
    clearInterval(state.progressTimer);
    $("#progress-bar").style.width = "100%";
    $$("#progress-steps li").forEach(item => { item.classList.remove("active"); item.classList.add("done"); });
  }

  function setBusy(busy) {
    elements.analyzeButton.disabled = busy;
    elements.analyzeButton.querySelector("span").textContent = busy ? "Tracing incident…" : "Analyze incident";
  }

  function renderResult(response) {
    const d = response.diagnosis;
    state.lastResponse = response;
    $("#severity-badge").textContent = d.severity.toUpperCase();
    $("#severity-badge").className = `severity-badge ${d.severity}`;
    $("#trace-id").textContent = String(response.id).toUpperCase();
    const date = new Date(response.created_at);
    $("#result-time").textContent = Number.isNaN(date.valueOf()) ? "just now" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    $("#diagnosis-title").textContent = d.title;
    $("#diagnosis-summary").textContent = d.summary;
    $("#likely-cause").textContent = d.likely_cause;
    const confidence = Math.round(d.confidence * 100);
    $("#confidence-value").textContent = `${confidence}%`;
    $("#confidence-meter").setAttribute("aria-valuenow", String(confidence));
    $("#confidence-bar").style.width = "0";

    const evidenceList = $("#evidence-list");
    evidenceList.replaceChildren();
    (d.evidence.length ? d.evidence : [{ label: "Request captured", detail: "The diagnostic engine normalized the supplied API call." }]).forEach(item => {
      const li = document.createElement("li");
      const marker = document.createElement("span");
      marker.className = "evidence-marker";
      marker.textContent = "✓";
      const text = document.createElement("div");
      text.className = "evidence-text";
      const strong = document.createElement("strong");
      strong.textContent = item.label;
      const detail = document.createElement("span");
      detail.textContent = item.detail;
      text.append(strong, detail);
      li.append(marker, text);
      evidenceList.append(li);
    });

    const fixList = $("#fix-list");
    fixList.replaceChildren();
    d.fix_steps.forEach((step, index) => {
      const li = document.createElement("li");
      const marker = document.createElement("span");
      marker.className = "fix-index";
      marker.setAttribute("aria-hidden", "true");
      marker.textContent = String(index + 1);
      const text = document.createElement("span");
      text.textContent = step;
      li.append(marker, text);
      fixList.append(li);
    });

    $("#artifact-curl").textContent = response.artifacts.corrected_curl;
    $("#artifact-python").textContent = response.artifacts.python_snippet;
    $("#artifact-pytest").textContent = response.artifacts.pytest_test;
    elements.resultMode.textContent = STATIC_DEMO ? "Prepared · rules engine" : response.mode;
    elements.fallbackNotice.hidden = !STATIC_DEMO;
    showView("result");
    requestAnimationFrame(() => { $("#confidence-bar").style.width = `${confidence}%`; });
    if (window.matchMedia("(max-width: 1120px)").matches) {
      setTimeout(() => elements.resultContent.closest(".results-panel")?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start"
      }), 80);
    }
  }

  async function analyze(event) {
    event?.preventDefault?.();
    const payload = collectPayload();
    if (!payload) {
      const invalid = $("[aria-invalid='true']", elements.form);
      invalid?.focus();
      return;
    }

    state.lastPayload = payload;
    if (STATIC_DEMO) {
      const report = state.selectedExample?.report;
      if (!report) {
        showToast("Select one of the prepared incident cases first.");
        return;
      }
      renderResult(normalizeResponse(report, payload));
      return;
    }
    setBusy(true);
    startProgress();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let responsePayload;
    let apiError = null;

    try {
      const response = await fetch("/api/v1/diagnose", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      if (!response.ok) {
        let detail = `Diagnostic API returned ${response.status}.`;
        try {
          const errorBody = await response.json();
          detail = errorBody.detail || errorBody.message || detail;
          if (Array.isArray(detail)) detail = detail.map(item => item.msg || stringify(item)).join(" · ");
        } catch { /* response was not JSON */ }
        throw new Error(detail);
      }
      responsePayload = await response.json();
    } catch (error) {
      apiError = error;

    } finally {
      clearTimeout(timeout);
    }

    finishProgress();
    await new Promise(resolve => setTimeout(resolve, 170));
    setBusy(false);

    if (responsePayload) {
      const normalized = normalizeResponse(responsePayload, payload);
      renderResult(normalized);

    } else {
      showView("error");
      $("#error-message").textContent = apiError?.name === "AbortError"
        ? "The diagnostic API took too long to respond. Try again or use the demo case."
        : apiError?.message || "Check the request and try again.";
    }
  }

  function fillExample(example, options = {}) {
    state.selectedExample = example;
    state.lastResponse = null;
    showView("empty");
    const request = example.request || {};
    const observed = example.observed || {};
    elements.method.value = String(request.method || "GET").toUpperCase();
    elements.url.value = request.url || "";
    elements.requestHeaders.value = stringify(request.headers, "{\n  \"Content-Type\": \"application/json\"\n}");
    elements.requestBody.value = stringify(request.body);
    elements.statusCode.value = observed.status_code ?? observed.status ?? "";
    elements.latency.value = observed.latency_ms ?? observed.latency ?? "";
    elements.observedError.value = observed.error || "";
    elements.responseHeaders.value = stringify(observed.headers);
    elements.responseBody.value = stringify(observed.body);
    elements.observedDetails.open = Boolean(elements.statusCode.value || elements.observedError.value || elements.responseBody.value);
    validateJsonEditor(elements.requestHeaders, $("#headers-validity"), true, "headers");
    validateJsonEditor(elements.requestBody, $("#body-validity"), false, "body");
    setFieldError("url", "");

    if (options.scroll !== false) {
      $("#workbench").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
    if (options.analyze) setTimeout(() => analyze(null), options.scroll === false ? 0 : 380);
    else showToast(`Loaded “${example.title}”.`);
  }

  function renderExamples(examples) {
    elements.exampleGrid.replaceChildren();
    examples.slice(0, 6).forEach((example, index) => {
      const status = example.observed?.status_code ?? example.observed?.status ?? "ERR";
      const method = example.request?.method || "GET";
      let path = example.request?.url || "/api/resource";
      try { path = new URL(path).pathname; } catch { /* keep raw path */ }
      const card = document.createElement("article");
      card.className = "example-card";
      const top = document.createElement("div"); top.className = "example-top";
      const statusEl = document.createElement("span"); statusEl.className = `example-status ${String(status).toLowerCase().includes("time") ? "timeout" : ""}`; statusEl.textContent = status;
      const category = document.createElement("span"); category.className = "example-category"; category.textContent = example.category;
      top.append(statusEl, category);
      const title = document.createElement("h3"); title.textContent = example.title;
      const description = document.createElement("p"); description.textContent = example.description;
      const requestLine = document.createElement("div"); requestLine.className = "example-request";
      const methodEl = document.createElement("strong"); methodEl.textContent = method;
      const pathEl = document.createElement("span"); pathEl.textContent = path;
      requestLine.append(methodEl, pathEl);
      const footer = document.createElement("div"); footer.className = "example-footer";
      const confidence = document.createElement("span"); confidence.className = "example-confidence";
      const score = example.diagnosis?.confidence;
      confidence.textContent = score ? `${Math.round((score > 1 ? score / 100 : score) * 100)}% expected confidence` : "Sanitized trace";
      const load = document.createElement("button"); load.type = "button"; load.className = "example-load"; load.textContent = "Load case  →"; load.setAttribute("aria-label", `Load case: ${example.title}`);
      load.addEventListener("click", () => fillExample(state.examples[index], { scroll: true, analyze: STATIC_DEMO }));
      footer.append(confidence, load);
      card.append(top, title, description, requestLine, footer);
      elements.exampleGrid.append(card);
    });
  }

  async function loadExamples() {
    if (STATIC_DEMO) {
      state.examples = normalizeExamples(PREPARED_EXAMPLES);
      renderExamples(state.examples);
      if (state.examples.length) state.examples[0] && fillExample(state.examples[0], { scroll: false });
      else showToast("Prepared demo data is missing. Rebuild the static site.");
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3500);
    try {
      const response = await fetch("/api/v1/examples", { headers: { Accept: "application/json" }, signal: controller.signal });
      if (!response.ok) throw new Error("Examples unavailable");
      state.examples = normalizeExamples(await response.json());
    } catch {
      state.examples = [];
      showToast("The API could not load examples. Start the local FastAPI server and retry.");
    } finally {
      clearTimeout(timeout);
    }
    renderExamples(state.examples);
  }

  function activateTab(tab) {
    const artifact = tab.dataset.artifact;
    state.activeArtifact = artifact;
    $$("[role='tab']", $(".tab-bar")).forEach(button => {
      const selected = button === tab;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      $(`#panel-${button.dataset.artifact}`).hidden = !selected;
    });
  }

  async function copyCurrentArtifact() {
    const code = $(`#artifact-${state.activeArtifact}`).textContent;
    try {
      await navigator.clipboard.writeText(code);
      $("#copy-code-button span").textContent = "Copied";
      showToast("Code copied to clipboard.");
      setTimeout(() => { $("#copy-code-button span").textContent = "Copy"; }, 1300);
    } catch {
      showToast("Clipboard access is unavailable. Select the code to copy it.");
    }
  }

  function downloadFile(name, content, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function exportJson() {
    if (!state.lastResponse) return;
    downloadFile(`traceaid-${state.lastResponse.id}.json`, JSON.stringify(state.lastResponse.rawReport, null, 2), "application/json");
    showToast("JSON report exported.");
  }

  function exportMarkdown() {
    if (!state.lastResponse) return;
    const markdown = state.lastResponse.artifacts.markdown_report || "";
    downloadFile(`traceaid-${state.lastResponse.id}.md`, markdown, "text/markdown");
    showToast("Markdown report exported.");
  }

  function showToast(message) {
    clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("visible");
    state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
  }

  function bindEvents() {
    elements.form.addEventListener("submit", event => analyze(event));
    elements.requestHeaders.addEventListener("input", () => validateJsonEditor(elements.requestHeaders, $("#headers-validity"), true, "headers"));
    elements.requestBody.addEventListener("input", () => validateJsonEditor(elements.requestBody, $("#body-validity"), false, "body"));
    elements.url.addEventListener("input", () => setFieldError("url", ""));
    $("#load-demo-button").addEventListener("click", () => state.examples[0] && fillExample(state.examples[0], { scroll: false, analyze: false }));
    $("#hero-demo-button").addEventListener("click", () => state.examples[0] && fillExample(state.examples[0], { scroll: true, analyze: true }));
    $("#empty-demo-button").addEventListener("click", () => state.examples[0] && fillExample(state.examples[0], { scroll: false, analyze: true }));
    $("#retry-button").addEventListener("click", () => analyze(null));
    $("#copy-code-button").addEventListener("click", copyCurrentArtifact);
    $("#export-json").addEventListener("click", exportJson);
    $("#export-markdown").addEventListener("click", exportMarkdown);

    $$("[role='tab']", $(".tab-bar")).forEach(tab => {
      tab.addEventListener("click", () => activateTab(tab));
      tab.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const tabs = $$("[role='tab']", $(".tab-bar"));
        let index = tabs.indexOf(tab);
        if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") index = 0;
        if (event.key === "End") index = tabs.length - 1;
        activateTab(tabs[index]);
        tabs[index].focus();
      });
    });

    $$("textarea").forEach(area => area.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      event.preventDefault();
      const start = area.selectionStart;
      const end = area.selectionEnd;
      area.setRangeText("  ", start, end, "end");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    }));
  }

  function init() {
    $("#footer-year").textContent = new Date().getFullYear();
    if (STATIC_DEMO) {
      document.title = "TraceAid AI — Interactive portfolio demo";
      $(".status-label").textContent = "Prepared portfolio demo";
      $(".live-label").textContent = "SAMPLE";
      $(".system-status").title = "Prepared reports generated by the Python rules engine";
      $(".hero-lede").textContent = "Explore six synthetic API incidents, inspect evidence-backed diagnostics, and copy Python, curl, and pytest artifacts generated by the real backend. No API key required.";
      $(".hero-actions .button-primary").firstChild.textContent = "Explore prepared cases ";
      $(".hero-actions .button-primary").href = "#examples";
      $("#workbench-title").textContent = "Inspect a prepared incident";
      $(".workbench-section .section-heading > p").textContent = "Prepared examples only. No requests are sent to an API or AI provider.";
      $(".request-panel .panel-header h3 + p").textContent = "Select a case below; evidence is read-only.";
      elements.analyzeButton.querySelector("span").textContent = "Show prepared diagnosis";
      $$(".request-panel input, .request-panel textarea, .request-panel select").forEach(field => { field.disabled = true; });
      $(".form-footer > p").lastChild.textContent = " Synthetic evidence; credentials removed.";
      $(".fallback-notice p").textContent = "Prepared demo — this report was generated from the displayed synthetic incident by the Python rules engine. Custom analysis and optional AI run in the local application.";
      $(".how-intro > p:last-child").textContent = "These prepared reports use the same deterministic pipeline as the local application. Run FastAPI locally to diagnose your own evidence or opt into AI.";
      $("#empty-state > p:not([class])").textContent = "Choose one of six prepared cases, then inspect its diagnosis and suggested repair artifacts.";
      $(".hero-stats > div:nth-child(1) dd").textContent = "prepared cases";
      $(".hero-stats > div:nth-child(2) dt").textContent = "0";
      $(".hero-stats > div:nth-child(2) dd").textContent = "API keys needed";
    }
    bindEvents();
    loadExamples();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
