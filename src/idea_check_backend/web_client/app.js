const API_BASE = window.location.origin;
const ACCESS_STORAGE_KEY = "idea-check-client-access-v1";
const REVEAL_STORAGE_PREFIX = "idea-check-client-reveal-v1:";
const DISMISSED_REVEALS_KEY = "idea-check-client-dismissed-reveals-v1";
const POLL_INTERVAL_MS = 2000;

const state = {
  access: null,
  pairState: null,
  lastReveal: null,
  pollingTimerId: null,
  refreshInFlight: false,
};

const elements = {
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
};

bootstrap().catch((error) => {
  notify(error.message || "Failed to initialize client");
});

async function bootstrap() {
  bindEvents();

  const queryAccess = getAccessFromQuery();
  if (queryAccess) {
    saveAccess(queryAccess);
  }

  const storedAccess = queryAccess || loadAccess();
  if (!storedAccess) {
    render();
    return;
  }

  state.access = storedAccess;
  syncUrl();
  render();
  await refreshState();
}

function bindEvents() {
  elements.createForm.addEventListener("submit", handleCreateSession);
  elements.joinForm.addEventListener("submit", handleJoinSession);
  elements.answerForm.addEventListener("submit", handleSubmitAnswer);
  elements.copyInviteButton.addEventListener("click", handleCopyInviteLink);
  elements.refreshButton.addEventListener("click", () => refreshState({ showToast: true }));
  elements.resetButton.addEventListener("click", resetAccess);
  elements.dismissRevealButton.addEventListener("click", dismissReveal);
  window.addEventListener("storage", handleStorageEvent);
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
    const response = await apiFetch(
      `/pair-sessions/${state.access.sessionId}/participants/${state.access.participantId}/answers`,
      {
        method: "POST",
        body: JSON.stringify({ content_text: contentText }),
      },
    );

    state.pairState = response.state;
    elements.answerText.value = "";
    if (response.reveal) {
      saveRevealSnapshot(state.access.sessionId, response.reveal);
      state.lastReveal = response.reveal;
    }

    if (response.outcome === "waiting") {
      notify("Answer submitted. Waiting for partner.");
    } else if (response.outcome === "completed") {
      notify("Run completed");
    } else {
      notify("Answers revealed");
    }

    render();
    startPolling();
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function refreshState(options = {}) {
  if (!state.access || state.refreshInFlight) {
    return;
  }

  state.refreshInFlight = true;
  try {
    const pairState = await apiFetch(
      `/pair-sessions/${state.access.sessionId}/participants/${state.access.participantId}/state`,
    );
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

function render() {
  renderAccess();
  renderStateSummary();
  renderScene();
  renderAnswerForm();
  renderWaitingState();
  renderReveal();
  renderSummary();
  renderDebug();
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
  elements.runStateValue.textContent = pairState.run
    ? `${pairState.run.phase} (${pairState.run.scene_position || "-"} / ${pairState.run.total_scenes || "-"})`
    : "Waiting for second participant";
  elements.sceneStateValue.textContent = scene
    ? `${scene.key} / ${scene.phase}`
    : pairState.completed
      ? "Completed"
      : "No active scene";

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
  elements.flagsValue.textContent = flags.length > 0 ? flags.join(" / ") : "none";
  elements.lastUpdatedLabel.textContent = new Date(pairState.updated_at).toLocaleString();
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
  elements.revealAnswers.innerHTML = "";
  for (const question of revealSnapshot.questions) {
    const card = document.createElement("article");
    card.className = "answer-card";
    const heading = document.createElement("strong");
    heading.textContent = `Participant ${question.participant_slot}`;
    const answer = document.createElement("p");
    answer.textContent = question.answer_text || "No answer";
    card.append(heading, answer);
    elements.revealAnswers.append(card);
  }
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
  history.replaceState({}, "", "/client/");
  render();
  notify("Local access reset");
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

function startPolling() {
  stopPolling();
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

function handleStorageEvent(event) {
  if (!state.access || !event.key) {
    return;
  }

  if (event.key === `${REVEAL_STORAGE_PREFIX}${state.access.sessionId}`) {
    state.lastReveal = loadRevealSnapshot(state.access.sessionId);
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
  if (!state.access) {
    return;
  }

  const params = new URLSearchParams({
    session: state.access.sessionId,
    participant: state.access.participantId,
  });
  if (state.access.slot) {
    params.set("slot", String(state.access.slot));
  }
  history.replaceState({}, "", `/client/?${params.toString()}`);
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
