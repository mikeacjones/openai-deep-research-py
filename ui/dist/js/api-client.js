"use strict";
(() => {
  // ui/src/ts/api-client.ts
  var terminalStatuses = /* @__PURE__ */ new Set([
    "completed",
    "failed",
    "cancelled"
  ]);
  function isObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }
  function stringValue(value) {
    return typeof value === "string" ? value : null;
  }
  function numberValue(value, fallback = 0) {
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
  }
  function stringArray(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  }
  function stringRecord(value) {
    if (!isObject(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry) => typeof entry[1] === "string"
      )
    );
  }
  function statusValue(value) {
    if (value === "pending" || value === "initializing" || value === "awaiting_clarifications" || value === "collecting_answers" || value === "researching" || value === "completed" || value === "failed" || value === "cancelled") {
      return value;
    }
    return value === "started" ? "initializing" : "pending";
  }
  function failureStageValue(value) {
    return value === "initialization" || value === "clarification" || value === "research" ? value : null;
  }
  function normalizeInteraction(payload, workflowId) {
    const clarificationQuestions = stringArray(payload.clarification_questions);
    return {
      workflow_id: stringValue(payload.workflow_id) ?? workflowId,
      status: statusValue(payload.status),
      original_query: stringValue(payload.original_query),
      clarification_questions: clarificationQuestions,
      clarification_responses: stringRecord(payload.clarification_responses),
      current_question: stringValue(payload.current_question),
      current_question_index: numberValue(payload.current_question_index),
      total_questions: numberValue(
        payload.total_questions,
        clarificationQuestions.length
      ),
      research_completed: payload.research_completed === true || payload.status === "completed",
      error_message: stringValue(payload.error_message),
      failure_stage: failureStageValue(payload.failure_stage)
    };
  }
  async function responseJson(response, fallback) {
    const raw = await response.text();
    let body = {};
    if (raw) {
      try {
        body = JSON.parse(raw);
      } catch {
        body = {};
      }
    }
    if (!response.ok) {
      const detail = isObject(body) && typeof body.detail === "string" ? body.detail : fallback;
      throw new Error(detail);
    }
    return body;
  }
  var ResearchClient = class {
    constructor(baseUrl = window.location.origin) {
      this.baseUrl = baseUrl;
    }
    workflowId = null;
    stopActivePoll = null;
    async startResearch(query) {
      const response = await fetch(this.url("/api/start-research"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query })
      });
      const raw = await responseJson(
        response,
        "Failed to start research"
      );
      const workflowId = stringValue(raw.workflow_id);
      if (!workflowId) throw new Error("The server did not return a workflow ID");
      this.workflowId = workflowId;
      const nested = isObject(raw.interaction) ? raw.interaction : raw;
      return {
        workflow_id: workflowId,
        status: stringValue(raw.status) ?? "started",
        temporal_ui_url: stringValue(raw.temporal_ui_url) ?? "",
        interaction: normalizeInteraction(nested, workflowId)
      };
    }
    async getStatus(workflowId, signal) {
      const id = this.requireWorkflowId(workflowId);
      const response = await fetch(
        this.url("/api/status/" + encodeURIComponent(id)),
        signal ? { signal } : {}
      );
      const raw = await responseJson(
        response,
        "Failed to get research status"
      );
      return normalizeInteraction(raw, id);
    }
    async submitAnswer(answer, workflowId, questionIndex = 0) {
      const id = this.requireWorkflowId(workflowId);
      const response = await fetch(
        this.url(
          "/api/answer/" + encodeURIComponent(id) + "/" + encodeURIComponent(String(questionIndex))
        ),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer })
        }
      );
      await responseJson(response, "Failed to submit answer");
    }
    async cancelResearch(workflowId) {
      const id = this.requireWorkflowId(workflowId);
      const response = await fetch(
        this.url("/api/cancel/" + encodeURIComponent(id)),
        { method: "POST" }
      );
      const raw = await responseJson(
        response,
        "Failed to cancel research"
      );
      const nested = isObject(raw.interaction) ? raw.interaction : raw.status === "cancelled" ? raw : null;
      const result = {
        workflow_id: stringValue(raw.workflow_id) ?? id,
        status: stringValue(raw.status) ?? "cancellation_requested"
      };
      if (nested) result.interaction = normalizeInteraction(nested, id);
      return result;
    }
    async getResult(workflowId) {
      const id = this.requireWorkflowId(workflowId);
      const response = await fetch(
        this.url("/api/result/" + encodeURIComponent(id))
      );
      const raw = await responseJson(
        response,
        "Research result is not available"
      );
      return {
        workflow_id: stringValue(raw.workflow_id) ?? id,
        status: raw.status === "failed" || raw.status === "cancelled" ? raw.status : "completed",
        error_message: stringValue(raw.error_message),
        markdown_report: stringValue(raw.markdown_report) ?? "",
        short_summary: stringValue(raw.short_summary) ?? "",
        follow_up_questions: stringArray(raw.follow_up_questions),
        image_file_path: stringValue(raw.image_file_path),
        pdf_file_path: stringValue(raw.pdf_file_path)
      };
    }
    startPolling(workflowId, onUpdate, options = {}) {
      this.stopPolling();
      this.workflowId = workflowId;
      const controller = new AbortController();
      const interval = options.interval ?? 1500;
      const retryInterval = options.retryInterval ?? 3e3;
      let timeoutId = null;
      const stop = () => {
        controller.abort();
        if (timeoutId !== null) window.clearTimeout(timeoutId);
        timeoutId = null;
        if (this.stopActivePoll === stop) this.stopActivePoll = null;
      };
      const schedule = (delay) => {
        if (controller.signal.aborted) return;
        timeoutId = window.setTimeout(() => void poll(), delay);
      };
      const poll = async () => {
        if (controller.signal.aborted) return;
        try {
          const status = await this.getStatus(workflowId, controller.signal);
          if (controller.signal.aborted) return;
          await onUpdate(status);
          if (terminalStatuses.has(status.status)) {
            stop();
            return;
          }
          schedule(interval);
        } catch (error) {
          if (controller.signal.aborted) return;
          const normalized = error instanceof Error ? error : new Error(String(error));
          await options.onError?.(normalized);
          schedule(retryInterval);
        }
      };
      this.stopActivePoll = stop;
      void poll();
      return stop;
    }
    stopPolling() {
      this.stopActivePoll?.();
      this.stopActivePoll = null;
    }
    requireWorkflowId(workflowId) {
      const id = workflowId ?? this.workflowId;
      if (!id) throw new Error("No workflow ID is available");
      this.workflowId = id;
      return id;
    }
    url(pathname) {
      return new URL(pathname, this.baseUrl).toString();
    }
  };
  window.ResearchClient = ResearchClient;
})();
//# sourceMappingURL=api-client.js.map
