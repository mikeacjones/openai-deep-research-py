"use strict";
(() => {
  // ui/src/ts/index.ts
  var activeWorkflowKey = "deepResearch.activeWorkflowId";
  var temporalUrlKey = "deepResearch.temporalUiUrl";
  var cachedResultKey = "deepResearch.result";
  var cachedResultWorkflowKey = "deepResearch.resultWorkflowId";
  var client = new window.ResearchClient(window.location.origin);
  function element(selector) {
    const value = document.querySelector(selector);
    if (!value) throw new Error("Missing UI element: " + selector);
    return value;
  }
  var chatContainer = element("#chatContainer");
  var researchForm = element("#researchForm");
  var userInput = element("#researchInput");
  var submitButton = element("#submitButton");
  var spinnerContainer = element("#spinnerContainer");
  var statusText = element("#statusText");
  var workflowLink = element("#workflowIdLink");
  var cancelButton = element("#cancelButton");
  var terminalPanel = element("#terminalPanel");
  var terminalTitle = element("#terminalTitle");
  var terminalMessage = element("#terminalMessage");
  var startNewButton = element("#startNewButton");
  var workflowId = null;
  var temporalUiUrl = "";
  var currentQuestionIndex = 0;
  var lastQuestionKey = null;
  var lastStatus = null;
  var busy = false;
  var acceptingInput = true;
  var terminal = false;
  var completing = false;
  var stopPolling = null;
  function addMessage(text, role = "bot", tone = "default") {
    const message = document.createElement("div");
    message.className = "message " + role;
    const bubble = document.createElement("div");
    bubble.className = "message-bubble " + role + (tone === "error" ? " error" : "");
    bubble.textContent = text;
    message.appendChild(bubble);
    chatContainer.appendChild(message);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }
  function resetConversation() {
    chatContainer.replaceChildren();
    addMessage("Hey there \u2014 what would you like me to research?");
  }
  function showSpinner(visible, text = "Working\u2026") {
    spinnerContainer.hidden = !visible;
    statusText.textContent = text;
  }
  function updateControls() {
    const disabled = busy || !acceptingInput || terminal;
    userInput.disabled = disabled;
    submitButton.disabled = disabled;
    cancelButton.disabled = busy;
    if (!disabled) window.setTimeout(() => userInput.focus(), 0);
  }
  function setBusy(value) {
    busy = value;
    updateControls();
  }
  function setAcceptingInput(value) {
    acceptingInput = value;
    updateControls();
  }
  function displayWorkflowLink() {
    if (!workflowId || !temporalUiUrl) {
      workflowLink.hidden = true;
      workflowLink.removeAttribute("href");
      workflowLink.textContent = "";
      return;
    }
    workflowLink.href = temporalUiUrl;
    workflowLink.textContent = "View workflow " + workflowId;
    workflowLink.hidden = false;
  }
  function persistWorkflow(id, url) {
    workflowId = id;
    temporalUiUrl = url;
    localStorage.setItem(activeWorkflowKey, id);
    if (url) localStorage.setItem(temporalUrlKey, url);
    else localStorage.removeItem(temporalUrlKey);
    displayWorkflowLink();
    cancelButton.hidden = false;
  }
  function clearPersistedWorkflow() {
    localStorage.removeItem(activeWorkflowKey);
    localStorage.removeItem(temporalUrlKey);
  }
  function stopStatusPolling() {
    stopPolling?.();
    stopPolling = null;
    client.stopPolling();
  }
  function isTerminalStatus(status) {
    return status === "completed" || status === "failed" || status === "cancelled";
  }
  function beginPolling() {
    if (!workflowId || terminal) return;
    stopStatusPolling();
    stopPolling = client.startPolling(workflowId, handleStatus, {
      interval: 1500,
      retryInterval: 3e3,
      onError: () => {
        if (!terminal) {
          showSpinner(true, "Connection interrupted. Retrying\u2026");
        }
      }
    });
  }
  function restoreConversation(status) {
    chatContainer.replaceChildren();
    addMessage("Welcome back \u2014 resuming your research session.");
    if (status.original_query) addMessage(status.original_query, "user");
    const answeredCount = Math.min(
      status.current_question_index,
      status.clarification_questions.length
    );
    for (let index = 0; index < answeredCount; index += 1) {
      const question = status.clarification_questions[index];
      const answer = status.clarification_responses["question_" + index];
      if (question) addMessage(question);
      if (answer) addMessage(answer, "user");
    }
  }
  async function finishCompletedResearch() {
    if (!workflowId || completing) return;
    completing = true;
    setAcceptingInput(false);
    showSpinner(true, "Preparing your report\u2026");
    try {
      const result = await client.getResult(workflowId);
      sessionStorage.setItem(cachedResultKey, JSON.stringify(result));
      sessionStorage.setItem(cachedResultWorkflowKey, workflowId);
      window.location.assign("/success?wf=" + encodeURIComponent(workflowId));
    } catch (error) {
      completing = false;
      throw error;
    }
  }
  function showTerminal(status, message) {
    if (terminal) return;
    terminal = true;
    stopStatusPolling();
    showSpinner(false);
    setAcceptingInput(false);
    setBusy(false);
    clearPersistedWorkflow();
    cancelButton.hidden = true;
    researchForm.hidden = true;
    terminalPanel.dataset.status = status;
    terminalPanel.hidden = false;
    if (status === "failed") {
      terminalTitle.textContent = "Research failed";
      terminalMessage.textContent = message || "The research workflow could not finish. You can start a new session.";
      addMessage(
        message ? "Research failed: " + message : "Research failed before a report could be created.",
        "bot",
        "error"
      );
    } else {
      terminalTitle.textContent = "Research cancelled";
      terminalMessage.textContent = "This workflow has stopped. Start a new session whenever you are ready.";
      addMessage("Research cancelled. No report was created.");
    }
  }
  async function handleStatus(status) {
    const previousStatus = lastStatus;
    lastStatus = status.status;
    currentQuestionIndex = status.current_question_index;
    switch (status.status) {
      case "pending":
      case "initializing":
        setAcceptingInput(false);
        showSpinner(true, "Preparing your research plan\u2026");
        break;
      case "awaiting_clarifications":
      case "collecting_answers": {
        showSpinner(false);
        const question = status.current_question;
        if (!question) {
          setAcceptingInput(false);
          showSpinner(true, "Preparing the next step\u2026");
          break;
        }
        const questionKey = String(status.current_question_index) + ":" + question;
        if (questionKey !== lastQuestionKey) {
          addMessage(question);
          lastQuestionKey = questionKey;
        }
        userInput.placeholder = "Reply to the question\u2026";
        setAcceptingInput(true);
        break;
      }
      case "researching":
        setAcceptingInput(false);
        showSpinner(true, "Searching, analyzing, and writing your report\u2026");
        if (previousStatus !== "researching") {
          addMessage(
            "Thanks \u2014 I have what I need. I\u2019m researching your topic now."
          );
        }
        break;
      case "completed":
        stopStatusPolling();
        cancelButton.hidden = true;
        await finishCompletedResearch();
        break;
      case "failed":
        showTerminal("failed", status.error_message);
        break;
      case "cancelled":
        showTerminal("cancelled", null);
        break;
    }
  }
  async function handleSubmit(event) {
    event.preventDefault();
    if (busy || terminal) return;
    const text = userInput.value.trim();
    if (!text) return;
    addMessage(text, "user");
    userInput.value = "";
    setBusy(true);
    setAcceptingInput(false);
    try {
      if (!workflowId) {
        showSpinner(true, "Starting durable research\u2026");
        const started = await client.startResearch(text);
        persistWorkflow(started.workflow_id, started.temporal_ui_url);
        setBusy(false);
        await handleStatus(started.interaction);
      } else {
        stopStatusPolling();
        showSpinner(true, "Saving your answer\u2026");
        await client.submitAnswer(text, workflowId, currentQuestionIndex);
        setBusy(false);
        showSpinner(true, "Preparing the next step\u2026");
      }
      if (workflowId && !terminal && !isTerminalStatus(lastStatus ?? "")) {
        beginPolling();
      }
    } catch (error) {
      setBusy(false);
      showSpinner(false);
      const message = error instanceof Error ? error.message : "Something went wrong. Please try again.";
      addMessage(message, "bot", "error");
      if (workflowId) {
        const canAnswer = lastStatus === "awaiting_clarifications" || lastStatus === "collecting_answers";
        setAcceptingInput(canAnswer);
        beginPolling();
      } else {
        setAcceptingInput(true);
      }
    }
  }
  async function handleCancel() {
    if (!workflowId || busy || terminal) return;
    if (!window.confirm("Cancel this research workflow?")) return;
    stopStatusPolling();
    setBusy(true);
    setAcceptingInput(false);
    showSpinner(true, "Cancelling research\u2026");
    try {
      const response = await client.cancelResearch(workflowId);
      setBusy(false);
      if (response.interaction) await handleStatus(response.interaction);
      if (!terminal) {
        showSpinner(true, "Waiting for the workflow to stop\u2026");
        beginPolling();
      }
    } catch (error) {
      setBusy(false);
      const message = error instanceof Error ? error.message : "Unable to cancel research.";
      addMessage(message, "bot", "error");
      beginPolling();
    }
  }
  function resetSession() {
    stopStatusPolling();
    clearPersistedWorkflow();
    sessionStorage.removeItem(cachedResultKey);
    sessionStorage.removeItem(cachedResultWorkflowKey);
    workflowId = null;
    temporalUiUrl = "";
    currentQuestionIndex = 0;
    lastQuestionKey = null;
    lastStatus = null;
    busy = false;
    acceptingInput = true;
    terminal = false;
    completing = false;
    terminalPanel.hidden = true;
    terminalPanel.removeAttribute("data-status");
    researchForm.hidden = false;
    cancelButton.hidden = true;
    workflowLink.hidden = true;
    userInput.value = "";
    userInput.placeholder = "What would you like to research?";
    displayWorkflowLink();
    showSpinner(false);
    resetConversation();
    updateControls();
  }
  async function resumeExistingWorkflow() {
    const storedWorkflowId = localStorage.getItem(activeWorkflowKey);
    if (!storedWorkflowId) {
      updateControls();
      userInput.focus();
      return;
    }
    workflowId = storedWorkflowId;
    temporalUiUrl = localStorage.getItem(temporalUrlKey) ?? "";
    displayWorkflowLink();
    cancelButton.hidden = false;
    setAcceptingInput(false);
    setBusy(true);
    showSpinner(true, "Resuming your research session\u2026");
    try {
      const status = await client.getStatus(storedWorkflowId);
      restoreConversation(status);
      setBusy(false);
      await handleStatus(status);
      if (!terminal && !isTerminalStatus(status.status)) beginPolling();
    } catch (error) {
      clearPersistedWorkflow();
      workflowId = null;
      temporalUiUrl = "";
      setBusy(false);
      setAcceptingInput(true);
      showSpinner(false);
      displayWorkflowLink();
      cancelButton.hidden = true;
      resetConversation();
      addMessage(
        error instanceof Error ? "The previous session could not be resumed: " + error.message : "The previous session could not be resumed.",
        "bot",
        "error"
      );
    }
  }
  researchForm.addEventListener("submit", (event) => {
    void handleSubmit(event);
  });
  cancelButton.addEventListener("click", () => void handleCancel());
  startNewButton.addEventListener("click", resetSession);
  window.addEventListener("beforeunload", () => client.stopPolling());
  void resumeExistingWorkflow();
})();
//# sourceMappingURL=index.js.map
