const API_BASE = window.location.origin;
const ACCESS_STORAGE_KEY = "idea-check-client-access-v1";
const REVEAL_STORAGE_PREFIX = "idea-check-client-reveal-v1:";
const DISMISSED_REVEALS_KEY = "idea-check-client-dismissed-reveals-v1";
const MANUAL_MODE_STORAGE_KEY = "idea-check-client-manual-mode-v1";
const MANUAL_ACCESS_STORAGE_KEY = "idea-check-client-manual-access-v1";
const MANUAL_REVEAL_STORAGE_KEY = "idea-check-client-manual-reveal-v1";
const POLL_INTERVAL_MS = 2000;

const state = {
  mode: "single",
  access: null,
  pairState: null,
  lastReveal: null,
  pollingTimerId: null,
  refreshInFlight: false,
  manual: {
    accessList: [],
    statesByParticipantId: {},
    lastReveal: null,
    refreshInFlight: false,
  },
};

const elements = {
  manualModeToggle: document.querySelector("#manual-mode-toggle"),
  manualModePanel: document.querySelector("#manual-mode-panel"),
  accessPanel: document.querySelector("#access-panel"),
  currentStatePanel: document.querySelector("#current-state-panel"),
  rawStatePanel: document.querySelector("#raw-state-panel"),
  connectionBadge: document.querySelector("#connection-badge"),
  createForm: document.querySelector("#create-form"),
  createDisplayName: document.querySelector("#create-display-name"),
  joinForm: document.querySelector("#join-form"),
  joinSessionId: document.querySelector("#join-session-id"),
  joinDisplayName: document.querySelector("#join-display-name"),
  activeAccess: document.querySelector("#active-access"),
  sessionIdValue: document.querySelector("#session-id-value"),
  participantIdValue: document.querySelector("#participant-id-value"),
  participantSlotValue: document.querySelector("#participant-slot-value"),
  inviteLink: document.querySelector("#invite-link"),
  copyInviteButton: document.querySelector("#copy-invite-button"),
  refreshButton: document.querySelector("#refresh-button"),
  resetButton: document.querySelector("#reset-button"),
  stateKindBadge: document.querySelector("#state-kind-badge"),
  runStateValue: document.querySelector("#run-state-value"),
  sceneStateValue: document.querySelector("#scene-state-value"),
  flagsValue: document.querySelector("#flags-value"),
  scenePanel: document.querySelector("#scene-panel"),
  scenePosition: document.querySelector("#scene-position"),
  sceneTitle: document.querySelector("#scene-title"),
  scenePhaseBadge: document.querySelector("#scene-phase-badge"),
  scenePurpose: document.querySelector("#scene-purpose"),
  sceneIntro: document.querySelector("#scene-intro"),
  answerForm: document.querySelector("#answer-form"),
  questionLabel: document.querySelector("#question-label"),
  answerText: document.querySelector("#answer-text"),
  submitAnswerButton: document.querySelector("#submit-answer-button"),
  answerStatusText: document.querySelector("#answer-status-text"),
  waitingCard: document.querySelector("#waiting-card"),
  waitingCopy: document.querySelector("#waiting-copy"),
  revealCard: document.querySelector("#reveal-card"),
  dismissRevealButton: document.querySelector("#dismiss-reveal-button"),
  revealTitle: document.querySelector("#reveal-title"),
  revealAnswers: document.querySelector("#reveal-answers"),
  summaryCard: document.querySelector("#summary-card"),
  summaryText: document.querySelector("#summary-text"),
  summaryMeta: document.querySelector("#summary-meta"),
  debugOutput: document.querySelector("#debug-output"),
  lastUpdatedLabel: document.querySelector("#last-updated-label"),
  toast: document.querySelector("#toast"),
  manualCreateForm: document.querySelector("#manual-create-form"),
  manualPlayerOneName: document.querySelector("#manual-player-one-name"),
  manualPlayerTwoName: document.querySelector("#manual-player-two-name"),
  manualRefreshButton: document.querySelector("#manual-refresh-button"),
  manualResetButton: document.querySelector("#manual-reset-button"),
  manualSessionBadge: document.querySelector("#manual-session-badge"),
  manualSessionMeta: document.querySelector("#manual-session-meta"),
  manualSessionIdValue: document.querySelector("#manual-session-id-value"),
  manualPlayerOneIdValue: document.querySelector("#manual-player-one-id-value"),
  manualPlayerTwoIdValue: document.querySelector("#manual-player-two-id-value"),
  manualSharedSceneCard: document.querySelector("#manual-shared-scene-card"),
  manualScenePhaseBadge: document.querySelector("#manual-scene-phase-badge"),
  manualSceneTitle: document.querySelector("#manual-scene-title"),
  manualSceneCopy: document.querySelector("#manual-scene-copy"),
  manualRunValue: document.querySelector("#manual-run-value"),
  manualSceneValue: document.querySelector("#manual-scene-value"),
  manualFlagsValue: document.querySelector("#manual-flags-value"),
  manualRevealCard: document.querySelector("#manual-reveal-card"),
  manualClearRevealButton: document.querySelector("#manual-clear-reveal-button"),
  manualRevealTitle: document.querySelector("#manual-reveal-title"),
  manualRevealAnswers: document.querySelector("#manual-reveal-answers"),
  manualDebugOutput: document.querySelector("#manual-debug-output"),
  manualLastUpdatedLabel: document.querySelector("#manual-last-updated-label"),
};

const manualPlayerElements = [
  {
    nameLabel: document.querySelector("#manual-player-one-name-label"),
    stateKind: document.querySelector("#manual-player-one-state-kind"),
    slot: document.querySelector("#manual-player-one-slot"),
    status: document.querySelector("#manual-player-one-status"),
    flags: document.querySelector("#manual-player-one-flags"),
    question: document.querySelector("#manual-player-one-question"),
    answer: document.querySelector("#manual-player-one-answer"),
    submit: document.querySelector("#manual-player-one-submit"),
    helper: document.querySelector("#manual-player-one-helper"),
    summaryCard: document.querySelector("#manual-player-one-summary-card"),
    summaryText: document.querySelector("#manual-player-one-summary-text"),
  },
  {
    nameLabel: document.querySelector("#manual-player-two-name-label"),
    stateKind: document.querySelector("#manual-player-two-state-kind"),
    slot: document.querySelector("#manual-player-two-slot"),
    status: document.querySelector("#manual-player-two-status"),
    flags: document.querySelector("#manual-player-two-flags"),
    question: document.querySelector("#manual-player-two-question"),
    answer: document.querySelector("#manual-player-two-answer"),
    submit: document.querySelector("#manual-player-two-submit"),
    helper: document.querySelector("#manual-player-two-helper"),
    summaryCard: document.querySelector("#manual-player-two-summary-card"),
    summaryText: document.querySelector("#manual-player-two-summary-text"),
  },
];

bootstrap().catch((error) => {
  notify(error.message || "Failed to initialize client");
});

async function bootstrap() {
  bindEvents();
  hydrateMode();
  hydrateSingleMode();
  hydrateManualMode();
  syncUrl();
  render();

  if (state.mode === "manual" && state.manual.accessList.length === 2) {
    await refreshManualStates();
    return;
  }

  if (state.mode === "single" && state.access) {
    await refreshState();
  }
}

function bindEvents() {
  elements.manualModeToggle.addEventListener("change", handleModeToggle);
  elements.createForm.addEventListener("submit", handleCreateSession);
  elements.joinForm.addEventListener("submit", handleJoinSession);
  elements.answerForm.addEventListener("submit", handleSubmitAnswer);
  elements.copyInviteButton.addEventListener("click", handleCopyInviteLink);
  elements.refreshButton.addEventListener("click", () => refreshState({ showToast: true }));
  elements.resetButton.addEventListener("click", resetAccess);
  elements.dismissRevealButton.addEventListener("click", dismissReveal);
  elements.manualCreateForm.addEventListener("submit", handleManualCreateSession);
  elements.manualRefreshButton.addEventListener("click", () =>
    refreshManualStates({ showToast: true }),
  );
  elements.manualResetButton.addEventListener("click", resetManualMode);
  elements.manualClearRevealButton.addEventListener("click", clearManualReveal);
  manualPlayerElements.forEach((player, index) => {
    player.submit.addEventListener("click", () => handleManualSubmitAnswer(index));
  });
  window.addEventListener("storage", handleStorageEvent);
}

function hydrateMode() {
  const params = new URLSearchParams(window.location.search);
  const modeFromQuery = params.get("mode");
  if (modeFromQuery === "manual" || modeFromQuery === "single") {
    state.mode = modeFromQuery;
    localStorage.setItem(MANUAL_MODE_STORAGE_KEY, modeFromQuery);
  } else {
    state.mode = localStorage.getItem(MANUAL_MODE_STORAGE_KEY) === "manual" ? "manual" : "single";
  }
  elements.manualModeToggle.checked = state.mode === "manual";
}

function hydrateSingleMode() {
  const queryAccess = getAccessFromQuery();
  if (queryAccess) {
    saveAccess(queryAccess);
  }

  const storedAccess = queryAccess || loadAccess();
  if (!storedAccess) {
    return;
  }

  state.access = storedAccess;
  state.lastReveal = loadRevealSnapshot(storedAccess.sessionId);
}

function hydrateManualMode() {
  const manualAccess = loadManualAccess();
  if (manualAccess.length === 2) {
    state.manual.accessList = manualAccess;
  }
  state.manual.lastReveal = loadManualReveal();
}

function handleModeToggle() {
  state.mode = elements.manualModeToggle.checked ? "manual" : "single";
  localStorage.setItem(MANUAL_MODE_STORAGE_KEY, state.mode);
  syncUrl();
  stopPolling();
  render();

  if (state.mode === "manual") {
    if (state.manual.accessList.length === 2) {
      refreshManualStates();
    }
    return;
  }

  if (state.access) {
    refreshState();
  }
}

async function handleCreateSession(event) {
  event.preventDefault();
  setBusy(true);
  try {
    const payload = {
      display_name: elements.createDisplayName.value.trim() || null,
    };
    const response = await apiFetch("/pair-sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    activateAccess({
      sessionId: response.state.session.id,
      participantId: response.access.id,
      displayName: response.access.display_name,
      slot: response.access.slot,
    });
    state.pairState = response.state;
    notify("Session created");
    render();
    startPolling();
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleJoinSession(event) {
  event.preventDefault();
  const sessionId = elements.joinSessionId.value.trim();
  if (!sessionId) {
    notify("Session ID is required");
    return;
  }

  setBusy(true);
  try {
    const payload = {
      display_name: elements.joinDisplayName.value.trim() || null,
    };
    const response = await apiFetch(`/pair-sessions/${sessionId}/join`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    activateAccess({
      sessionId,
      participantId: response.access.id,
      displayName: response.access.display_name,
      slot: response.access.slot,
    });
    state.pairState = response.state;
    notify("Joined session");
    render();
    startPolling();
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleSubmitAnswer(event) {
  event.preventDefault();
  if (!state.access || !state.pairState?.current_scene) {
    return;
  }

  const contentText = elements.answerText.value.trim();
  if (!contentText) {
    notify("Answer cannot be empty");
    return;
  }

  setBusy(true, "Submitting answer...");
  try {
    const response = await submitAnswer(state.access, contentText);
    state.pairState = response.state;
    elements.answerText.value = "";
    if (response.reveal) {
      saveRevealSnapshot(state.access.sessionId, response.reveal);
      state.lastReveal = response.reveal;
    }

    notify(outcomeMessage(response.outcome));
    render();
    startPolling();
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleManualCreateSession(event) {
  event.preventDefault();
  setBusy(true);
  try {
    const playerOneName = elements.manualPlayerOneName.value.trim() || null;
    const playerTwoName = elements.manualPlayerTwoName.value.trim() || null;

    const createResponse = await apiFetch("/pair-sessions", {
      method: "POST",
      body: JSON.stringify({ display_name: playerOneName }),
    });
    const sessionId = createResponse.state.session.id;
    const joinResponse = await apiFetch(`/pair-sessions/${sessionId}/join`, {
      method: "POST",
      body: JSON.stringify({ display_name: playerTwoName }),
    });

    state.manual.accessList = sortManualAccess([
      {
        sessionId,
        participantId: createResponse.access.id,
        displayName: createResponse.access.display_name,
        slot: createResponse.access.slot,
      },
      {
        sessionId,
        participantId: joinResponse.access.id,
        displayName: joinResponse.access.display_name,
        slot: joinResponse.access.slot,
      },
    ]);
    state.manual.statesByParticipantId = {
      [createResponse.access.id]: createResponse.state,
      [joinResponse.access.id]: joinResponse.state,
    };
    state.manual.lastReveal = null;
    saveManualAccess(state.manual.accessList);
    saveManualReveal(null);
    notify("Dual-player session created");
    await refreshManualStates();
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleManualSubmitAnswer(index) {
  const access = state.manual.accessList[index];
  const player = manualPlayerElements[index];
  const pairState = access ? state.manual.statesByParticipantId[access.participantId] : null;
  if (!access || !pairState?.current_scene) {
    return;
  }

  const contentText = player.answer.value.trim();
  if (!contentText) {
    notify("Answer cannot be empty");
    return;
  }

  setBusy(true, `Submitting player ${index + 1} answer...`);
  try {
    const response = await submitAnswer(access, contentText);
    state.manual.statesByParticipantId[access.participantId] = response.state;
    player.answer.value = "";

    if (response.reveal) {
      state.manual.lastReveal = response.reveal;
      saveManualReveal(response.reveal);
    }

    await refreshManualStates();
    notify(`Player ${index + 1}: ${outcomeMessage(response.outcome)}`);
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function submitAnswer(access, contentText) {
  return apiFetch(
    `/pair-sessions/${access.sessionId}/participants/${access.participantId}/answers`,
    {
      method: "POST",
      body: JSON.stringify({ content_text: contentText }),
    },
  );
}

async function refreshState(options = {}) {
  if (!state.access || state.refreshInFlight || state.mode !== "single") {
    return;
  }

  state.refreshInFlight = true;
  try {
    const pairState = await fetchParticipantState(state.access);
    state.pairState = pairState;
    state.lastReveal = loadRevealSnapshot(state.access.sessionId);
    render();
    if (options.showToast) {
      notify("State refreshed");
    }
    startPolling();
  } catch (error) {
    stopPolling();
    notify(error.message);
  } finally {
    state.refreshInFlight = false;
  }
}

async function refreshManualStates(options = {}) {
  if (state.manual.accessList.length !== 2 || state.manual.refreshInFlight || state.mode !== "manual") {
    return;
  }

  state.manual.refreshInFlight = true;
  try {
    const states = await Promise.all(state.manual.accessList.map(fetchParticipantState));
    state.manual.statesByParticipantId = Object.fromEntries(
      state.manual.accessList.map((access, index) => [access.participantId, states[index]]),
    );
    state.manual.lastReveal = loadManualReveal();
    render();
    if (options.showToast) {
      notify("Both states refreshed");
    }
    startPolling();
  } catch (error) {
    stopPolling();
    notify(error.message);
  } finally {
    state.manual.refreshInFlight = false;
  }
}

async function fetchParticipantState(access) {
  return apiFetch(`/pair-sessions/${access.sessionId}/participants/${access.participantId}/state`);
}

function render() {
  renderMode();
  renderAccess();
  renderStateSummary();
  renderScene();
  renderAnswerForm();
  renderWaitingState();
  renderReveal();
  renderSummary();
  renderDebug();
  renderManualMode();
}

function renderMode() {
  const manual = state.mode === "manual";
  elements.manualModePanel.classList.toggle("hidden", !manual);
  elements.accessPanel.classList.toggle("hidden", manual);
  elements.currentStatePanel.classList.toggle("hidden", manual);
  elements.rawStatePanel.classList.toggle("hidden", manual);
}

function renderAccess() {
  const hasAccess = Boolean(state.access);
  elements.connectionBadge.textContent = hasAccess ? "Connected" : "Disconnected";
  elements.activeAccess.classList.toggle("hidden", !hasAccess);

  if (!hasAccess) {
    return;
  }

  elements.joinSessionId.value = state.access.sessionId;
  elements.sessionIdValue.textContent = state.access.sessionId;
  elements.participantIdValue.textContent = state.access.participantId;
  elements.participantSlotValue.textContent = String(state.access.slot || "-");
  elements.inviteLink.value = `${window.location.origin}/client/?session=${encodeURIComponent(state.access.sessionId)}`;
}

function renderStateSummary() {
  const pairState = state.pairState;
  if (!pairState) {
    elements.stateKindBadge.textContent = "No session";
    elements.runStateValue.textContent = "Not started";
    elements.sceneStateValue.textContent = "-";
    elements.flagsValue.textContent = "-";
    elements.lastUpdatedLabel.textContent = "Never";
    return;
  }

  const scene = pairState.current_scene;
  elements.stateKindBadge.textContent = pairState.state_kind;
  elements.runStateValue.textContent = formatRun(pairState.run);
  elements.sceneStateValue.textContent = scene
    ? `${scene.key} / ${scene.phase}`
    : pairState.completed
      ? "Completed"
      : "No active scene";
  elements.flagsValue.textContent = formatFlags(pairState);
  elements.lastUpdatedLabel.textContent = formatUpdatedAt(pairState.updated_at);
}

function renderScene() {
  const scene = state.pairState?.current_scene;
  const hasScene = Boolean(scene);
  elements.scenePanel.classList.toggle("hidden", !hasScene);
  if (!hasScene) {
    return;
  }

  elements.scenePosition.textContent = `Scene ${scene.position}`;
  elements.sceneTitle.textContent = scene.title || scene.key;
  elements.scenePhaseBadge.textContent = scene.phase;
  elements.scenePurpose.textContent = scene.purpose || "";
  elements.sceneIntro.textContent = scene.intro_text || scene.transition_text || "";
}

function renderAnswerForm() {
  const pairState = state.pairState;
  const scene = pairState?.current_scene;
  const shouldShow =
    Boolean(scene) &&
    pairState.state_kind === "answering" &&
    !pairState.answered_current_question;

  elements.answerForm.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) {
    elements.answerStatusText.textContent = "";
    return;
  }

  const question = scene.questions.find(
    (item) => item.participant_id === state.access?.participantId,
  );
  elements.questionLabel.textContent = question?.prompt_text || "Your answer";
  elements.answerStatusText.textContent = "Submit once per scene.";
}

function renderWaitingState() {
  const pairState = state.pairState;
  const shouldShow = Boolean(pairState) && pairState.state_kind === "waiting";
  elements.waitingCard.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) {
    return;
  }

  if (!pairState.run) {
    elements.waitingCopy.textContent = "Session created. Send the invite link to the second participant.";
    return;
  }

  elements.waitingCopy.textContent = pairState.answered_current_question
    ? "Your answer is saved. Waiting for your partner to answer this scene."
    : "Waiting for your partner to join or advance the flow.";
}

function renderReveal() {
  const pairState = state.pairState;
  const revealSnapshot = state.access ? loadRevealSnapshot(state.access.sessionId) : null;
  state.lastReveal = revealSnapshot;
  const shouldShow =
    Boolean(revealSnapshot) &&
    Boolean(pairState) &&
    !pairState.completed &&
    !isRevealDismissed(revealSnapshot.key);

  elements.revealCard.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) {
    return;
  }

  elements.revealTitle.textContent = `${revealSnapshot.title || revealSnapshot.key}`;
  renderRevealAnswers(elements.revealAnswers, revealSnapshot.questions);
}

function renderSummary() {
  const summary = state.pairState?.final_summary;
  const shouldShow = Boolean(summary);
  elements.summaryCard.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) {
    return;
  }

  elements.summaryText.textContent = summary.text;
  elements.summaryMeta.innerHTML = "";
  for (const label of [summary.tone, ...summary.focus].filter(Boolean)) {
    const chip = document.createElement("span");
    chip.textContent = label;
    elements.summaryMeta.append(chip);
  }
}

function renderDebug() {
  elements.debugOutput.textContent = state.pairState
    ? JSON.stringify(state.pairState, null, 2)
    : "No state loaded yet.";
}

function renderManualMode() {
  const accessList = state.manual.accessList;
  const hasSession = accessList.length === 2;
  const sessionId = accessList[0]?.sessionId || null;
  const states = accessList.map((access) => state.manual.statesByParticipantId[access.participantId] || null);
  const primaryState = states.find(Boolean);
  const activeScene = primaryState?.current_scene || null;
  const completed = states.length === 2 && states.every((item) => item?.completed);
  const latestUpdatedAt = states
    .map((item) => item?.updated_at || null)
    .filter(Boolean)
    .sort()
    .at(-1);

  elements.manualSessionBadge.textContent = hasSession ? sessionId : "No session";
  elements.manualSessionMeta.classList.toggle("hidden", !hasSession);
  elements.manualSessionIdValue.textContent = sessionId || "-";
  elements.manualPlayerOneIdValue.textContent = accessList[0]?.participantId || "-";
  elements.manualPlayerTwoIdValue.textContent = accessList[1]?.participantId || "-";
  elements.manualLastUpdatedLabel.textContent = latestUpdatedAt ? formatUpdatedAt(latestUpdatedAt) : "Never";

  elements.manualSharedSceneCard.classList.toggle("hidden", !primaryState);
  if (primaryState) {
    elements.manualScenePhaseBadge.textContent = activeScene?.phase || (completed ? "completed" : "waiting");
    elements.manualSceneTitle.textContent = activeScene?.title || activeScene?.key || "No active scene";
    elements.manualSceneCopy.textContent =
      activeScene?.intro_text || activeScene?.transition_text || "Progression updates appear here.";
    elements.manualRunValue.textContent = formatRun(primaryState.run);
    elements.manualSceneValue.textContent = activeScene
      ? `${activeScene.key} / ${activeScene.phase}`
      : completed
        ? "Completed"
        : "Waiting for scene";
    elements.manualFlagsValue.textContent =
      states.filter(Boolean).map((item, index) => `P${index + 1}: ${formatFlags(item)}`).join(" | ") || "-";
  }

  const manualReveal = state.manual.lastReveal;
  const showReveal = Boolean(manualReveal);
  elements.manualRevealCard.classList.toggle("hidden", !showReveal);
  if (showReveal) {
    elements.manualRevealTitle.textContent = `${manualReveal.title || manualReveal.key}`;
    renderRevealAnswers(elements.manualRevealAnswers, manualReveal.questions);
  }

  manualPlayerElements.forEach((player, index) => {
    const access = accessList[index] || null;
    const pairState = access ? state.manual.statesByParticipantId[access.participantId] : null;
    const question = pairState?.current_scene?.questions.find(
      (item) => item.participant_id === access?.participantId,
    );
    const canSubmit =
      Boolean(pairState?.current_scene) &&
      pairState.state_kind === "answering" &&
      !pairState.answered_current_question;

    player.nameLabel.textContent = access?.displayName || `Participant ${access?.slot || index + 1}`;
    player.stateKind.textContent = pairState?.state_kind || "idle";
    player.slot.textContent = access ? `${access.participantId} / slot ${access.slot}` : "-";
    player.status.textContent = pairState?.participant?.status || "-";
    player.flags.textContent = pairState ? formatFlags(pairState) : "-";
    player.question.textContent = question?.prompt_text || manualQuestionFallback(pairState);
    player.submit.disabled = !canSubmit;
    player.answer.disabled = !access;
    player.helper.textContent = manualHelperText(pairState, question);
    player.summaryCard.classList.toggle("hidden", !pairState?.final_summary);
    player.summaryText.textContent = pairState?.final_summary?.text || "";
  });

  elements.manualDebugOutput.textContent = JSON.stringify(
    {
      session_id: sessionId,
      participants: accessList,
      states,
      latest_reveal: state.manual.lastReveal,
    },
    null,
    2,
  );
}

function manualQuestionFallback(pairState) {
  if (!pairState) {
    return "Create a manual session to load both participants.";
  }
  if (pairState.completed) {
    return "Run completed.";
  }
  if (pairState.waiting_for_partner) {
    return pairState.answered_current_question
      ? "Answer submitted. Waiting for the other player."
      : "Waiting for the other player to join or progress.";
  }
  if (pairState.current_scene) {
    return "This player has no pending answer in the current scene.";
  }
  return "No active scene yet.";
}

function manualHelperText(pairState, question) {
  if (!pairState) {
    return "No participant access yet.";
  }
  if (pairState.completed) {
    return "Summary ready.";
  }
  if (pairState.answered_current_question) {
    return "Submitted for this scene.";
  }
  if (pairState.waiting_for_partner && !question) {
    return "Waiting for the other player.";
  }
  return question ? "Submit once per scene." : "No answer needed right now.";
}

function activateAccess(access) {
  state.access = access;
  saveAccess(access);
  syncUrl();
  state.lastReveal = loadRevealSnapshot(access.sessionId);
}

function resetAccess() {
  stopPolling();
  state.access = null;
  state.pairState = null;
  state.lastReveal = null;
  localStorage.removeItem(ACCESS_STORAGE_KEY);
  syncUrl();
  render();
  notify("Local access reset");
}

function resetManualMode() {
  stopPolling();
  state.manual.accessList = [];
  state.manual.statesByParticipantId = {};
  state.manual.lastReveal = null;
  saveManualAccess([]);
  saveManualReveal(null);
  manualPlayerElements.forEach((player) => {
    player.answer.value = "";
  });
  syncUrl();
  render();
  notify("Manual mode reset");
}

async function handleCopyInviteLink() {
  try {
    await navigator.clipboard.writeText(elements.inviteLink.value);
    notify("Invite link copied");
  } catch {
    notify("Clipboard copy failed");
  }
}

function dismissReveal() {
  if (!state.lastReveal) {
    return;
  }
  markRevealDismissed(state.lastReveal.key);
  render();
}

function clearManualReveal() {
  state.manual.lastReveal = null;
  saveManualReveal(null);
  render();
}

function startPolling() {
  stopPolling();
  if (state.mode === "manual") {
    if (state.manual.accessList.length !== 2 || areAllManualStatesCompleted()) {
      return;
    }
    state.pollingTimerId = window.setInterval(() => {
      refreshManualStates();
    }, POLL_INTERVAL_MS);
    return;
  }

  if (!state.access || state.pairState?.completed) {
    return;
  }
  state.pollingTimerId = window.setInterval(() => {
    refreshState();
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (state.pollingTimerId) {
    window.clearInterval(state.pollingTimerId);
    state.pollingTimerId = null;
  }
}

function areAllManualStatesCompleted() {
  const accessList = state.manual.accessList;
  return (
    accessList.length === 2 &&
    accessList.every((access) => state.manual.statesByParticipantId[access.participantId]?.completed)
  );
}

function handleStorageEvent(event) {
  if (!event.key) {
    return;
  }

  if (state.access && event.key === `${REVEAL_STORAGE_PREFIX}${state.access.sessionId}`) {
    state.lastReveal = loadRevealSnapshot(state.access.sessionId);
    render();
  }

  if (event.key === MANUAL_REVEAL_STORAGE_KEY) {
    state.manual.lastReveal = loadManualReveal();
    render();
  }
}

function saveAccess(access) {
  localStorage.setItem(ACCESS_STORAGE_KEY, JSON.stringify(access));
}

function loadAccess() {
  const raw = localStorage.getItem(ACCESS_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(ACCESS_STORAGE_KEY);
    return null;
  }
}

function getAccessFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("session");
  const participantId = params.get("participant");
  if (!sessionId || !participantId) {
    if (sessionId) {
      elements.joinSessionId.value = sessionId;
    }
    return null;
  }

  return {
    sessionId,
    participantId,
    displayName: params.get("name"),
    slot: Number(params.get("slot")) || null,
  };
}

function syncUrl() {
  const params = new URLSearchParams();
  if (state.mode === "manual") {
    params.set("mode", "manual");
  }
  if (state.mode === "single" && state.access) {
    params.set("session", state.access.sessionId);
    params.set("participant", state.access.participantId);
    if (state.access.slot) {
      params.set("slot", String(state.access.slot));
    }
  }
  const query = params.toString();
  history.replaceState({}, "", query ? `/client/?${query}` : "/client/");
}

function saveRevealSnapshot(sessionId, reveal) {
  localStorage.setItem(`${REVEAL_STORAGE_PREFIX}${sessionId}`, JSON.stringify(reveal));
}

function loadRevealSnapshot(sessionId) {
  const raw = localStorage.getItem(`${REVEAL_STORAGE_PREFIX}${sessionId}`);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(`${REVEAL_STORAGE_PREFIX}${sessionId}`);
    return null;
  }
}

function saveManualAccess(accessList) {
  if (!accessList.length) {
    localStorage.removeItem(MANUAL_ACCESS_STORAGE_KEY);
    return;
  }
  localStorage.setItem(MANUAL_ACCESS_STORAGE_KEY, JSON.stringify(accessList));
}

function loadManualAccess() {
  const raw = localStorage.getItem(MANUAL_ACCESS_STORAGE_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? sortManualAccess(parsed) : [];
  } catch {
    localStorage.removeItem(MANUAL_ACCESS_STORAGE_KEY);
    return [];
  }
}

function saveManualReveal(reveal) {
  if (!reveal) {
    localStorage.removeItem(MANUAL_REVEAL_STORAGE_KEY);
    return;
  }
  localStorage.setItem(MANUAL_REVEAL_STORAGE_KEY, JSON.stringify(reveal));
}

function loadManualReveal() {
  const raw = localStorage.getItem(MANUAL_REVEAL_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(MANUAL_REVEAL_STORAGE_KEY);
    return null;
  }
}

function isRevealDismissed(sceneKey) {
  const dismissed = loadDismissedReveals();
  return dismissed.includes(sceneKey);
}

function markRevealDismissed(sceneKey) {
  const dismissed = loadDismissedReveals();
  if (dismissed.includes(sceneKey)) {
    return;
  }
  dismissed.push(sceneKey);
  sessionStorage.setItem(DISMISSED_REVEALS_KEY, JSON.stringify(dismissed));
}

function loadDismissedReveals() {
  const raw = sessionStorage.getItem(DISMISSED_REVEALS_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    sessionStorage.removeItem(DISMISSED_REVEALS_KEY);
    return [];
  }
}

function renderRevealAnswers(container, questions) {
  container.innerHTML = "";
  for (const question of questions) {
    const card = document.createElement("article");
    card.className = "answer-card";
    const heading = document.createElement("strong");
    heading.textContent = `Participant ${question.participant_slot}`;
    const prompt = document.createElement("p");
    prompt.textContent = question.prompt_text || "No prompt";
    const answer = document.createElement("p");
    answer.textContent = question.answer_text || "No answer";
    card.append(heading, prompt, answer);
    container.append(card);
  }
}

function formatRun(run) {
  return run
    ? `${run.phase} (${run.scene_position || "-"} / ${run.total_scenes || "-"})`
    : "Waiting for second participant";
}

function formatFlags(pairState) {
  const flags = [];
  if (pairState.answered_current_question) {
    flags.push("answered");
  }
  if (pairState.waiting_for_partner) {
    flags.push("waiting");
  }
  if (pairState.can_reveal) {
    flags.push("reveal");
  }
  if (pairState.completed) {
    flags.push("completed");
  }
  return flags.length > 0 ? flags.join(" / ") : "none";
}

function formatUpdatedAt(value) {
  return new Date(value).toLocaleString();
}

function sortManualAccess(accessList) {
  return [...accessList].sort((left, right) => (left.slot || 0) - (right.slot || 0));
}

function outcomeMessage(outcome) {
  if (outcome === "waiting") {
    return "Answer submitted. Waiting for partner.";
  }
  if (outcome === "completed") {
    return "Run completed";
  }
  if (outcome === "progressed") {
    return "Advanced to next scene";
  }
  return "Answers revealed";
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  return response.json();
}

function setBusy(isBusy, statusText = "") {
  for (const button of document.querySelectorAll("button")) {
    button.disabled = isBusy;
  }
  elements.answerStatusText.textContent = statusText;
}

function notify(message) {
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden");
  window.clearTimeout(notify.timeoutId);
  notify.timeoutId = window.setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 2600);
}
