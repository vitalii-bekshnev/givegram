/**
 * Givegram — Instagram Giveaway Winner Picker
 *
 * Single-page app controller that manages five screens:
 *   0. Login — authenticate with Instagram credentials
 *   1. Paste Link — accept an Instagram URL and fetch comments
 *   2. Giveaway Settings — choose number of winners & minimum comments
 *   3. Searching Animation — suspense countdown while "finding" winners
 *   4. Winner Results — display selected winners with share/restart actions
 */
"use strict";

/* ==========================================================================
   Constants & Configuration
   ========================================================================== */

/** Total circumference of the SVG progress ring (2 * π * r, where r = 90). */
const RING_CIRCUMFERENCE = 2 * Math.PI * 90; // ≈ 565.49

/** Duration in seconds for each winner's countdown animation. */
const COUNTDOWN_SECONDS = 5;

/** Duration in seconds to display each individual winner reveal before proceeding. */
const WINNER_REVEAL_SECONDS = 3;

/**
 * Pool of unique congratulatory messages — one is assigned to each winner
 * without repeats (up to 10 winners). Shuffled at the start of each giveaway.
 */
const CONGRATS_MESSAGES = [
  "Congratulations!",
  "You're a winner!",
  "Lucky you!",
  "What a pick!",
  "Amazing!",
  "Incredible!",
  "Well deserved!",
  "You did it!",
  "Brilliant!",
  "Fantastic!",
];

/** Regex that matches common Instagram post URL formats. */
const INSTAGRAM_URL_RE =
  /^https?:\/\/(?:www\.)?instagram\.com\/(?:p|reel|tv)\/[\w-]+\/?/i;

/** Base path for API endpoints. */
const API_BASE = "/api";

/* ==========================================================================
   DOM References
   ========================================================================== */

const screens = {
  login: document.getElementById("screen-login"),
  pasteLink: document.getElementById("screen-paste-link"),
  settings: document.getElementById("screen-settings"),
  searching: document.getElementById("screen-searching"),
  results: document.getElementById("screen-results"),
};

/** Loading spinner shown while a saved cookie is validated on page load. */
const appLoading = document.getElementById("app-loading");

const els = {
  /* Screen 0 — Login */
  loginForm: document.getElementById("login-form"),
  sessionCookieInput: document.getElementById("login-session-cookie-input"),
  loginError: document.getElementById("login-error"),
  loginBtn: document.getElementById("login-btn"),

  /* Screen 1 — Paste Link */
  fetchForm: document.getElementById("fetch-comments-form"),
  urlInput: document.getElementById("instagram-url-input"),
  urlError: document.getElementById("url-error"),
  fetchBtn: document.getElementById("fetch-comments-btn"),

  /* Screen 2 */
  settingsError: document.getElementById("settings-error"),
  runGiveawayBtn: document.getElementById("run-giveaway-btn"),

  /* Screen 3 — Searching / Reveal */
  findingLabel: document.getElementById("finding-winner-label"),
  searchingPhase: document.getElementById("searching-phase"),
  progressArc: document.querySelector(".progress-ring__arc"),
  countdown: document.getElementById("countdown-number"),
  winnerReveal: document.getElementById("winner-reveal"),
  revealCongrats: document.getElementById("reveal-congrats"),
  revealUsername: document.getElementById("reveal-username"),

  /* Screen 4 */
  winnersList: document.getElementById("winners-list"),
  shareBtn: document.getElementById("share-btn"),
  runAgainBtn: document.getElementById("run-again-btn"),
};

/* ==========================================================================
   Application State
   ========================================================================== */

const state = {
  /** Session ID returned by /api/login — required for authenticated API calls. */
  sessionId: null,
  /** Commenter data returned by /api/fetch-comments. */
  users: [],
  /** Total comments fetched. */
  totalComments: 0,
  /** Currently selected number of winners (1–5). */
  numWinners: 1,
  /** Currently selected minimum comments per user (1–5). */
  minComments: 1,
  /** List of winner usernames returned by /api/pick-winners. */
  winners: [],
};

/* ==========================================================================
   Screen Navigation
   ========================================================================== */

/**
 * Transition to a target screen by deactivating the current one and
 * activating the target. Uses the CSS `screen--active` class for visibility
 * and the `screen-fade-in` animation defined in styles.css.
 *
 * @param {HTMLElement} target — The screen section element to activate.
 */
function navigateTo(target) {
  /* Dismiss the initial loading indicator once a real screen is shown. */
  if (appLoading) {
    appLoading.hidden = true;
  }

  const current = document.querySelector(".screen--active");
  if (current) {
    current.classList.remove("screen--active");
    current.hidden = true;
  }
  target.hidden = false;
  /* Force a reflow so the fade-in animation replays. */
  void target.offsetWidth;
  target.classList.add("screen--active");
}

/* ==========================================================================
   Utility Helpers
   ========================================================================== */

/**
 * Show an inline error message element.
 *
 * @param {HTMLElement} el — The error paragraph element.
 * @param {string} message — The error text to display.
 */
function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

/** Hide an inline error message element. */
function hideError(el) {
  el.textContent = "";
  el.hidden = true;
}

/**
 * Toggle a button's loading state — disables the button, hides the label,
 * and shows the spinner (or vice-versa).
 *
 * @param {HTMLButtonElement} btn — The button element.
 * @param {boolean} loading — Whether the button should show its loading state.
 */
function setButtonLoading(btn, loading) {
  const label = btn.querySelector(".btn__label");
  const spinner = btn.querySelector(".btn__spinner");

  btn.disabled = loading;
  if (label) {
    label.hidden = loading;
  }
  if (spinner) {
    spinner.hidden = !loading;
  }
}

/**
 * Custom error class for API responses that carries the HTTP status code,
 * allowing callers to branch on specific statuses (e.g. 401 for expired sessions).
 */
class ApiError extends Error {
  /**
   * @param {string} message — Human-readable error detail.
   * @param {number} status — HTTP status code from the response.
   */
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Make a JSON POST request to an API endpoint.
 *
 * @param {string} endpoint — Relative path (e.g. "/api/fetch-comments").
 * @param {object} body — JSON-serialisable request body.
 * @returns {Promise<object>} Parsed JSON response.
 * @throws {ApiError} With the server's error detail and HTTP status if the response is not OK.
 */
async function apiPost(endpoint, body) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail || `Request failed (HTTP ${response.status})`;
    throw new ApiError(detail, response.status);
  }

  return response.json();
}

/* ==========================================================================
   Cookie Persistence (localStorage)
   ========================================================================== */

/** Key used to store the raw Instagram session cookie in localStorage. */
const COOKIE_STORAGE_KEY = "givegram_session_cookie";

/** Key used to store the backend session ID so we can skip re-login on refresh. */
const SESSION_ID_STORAGE_KEY = "givegram_session_id";

/**
 * Persist the raw Instagram session cookie so it survives page reloads
 * and can be used for transparent re-authentication.
 *
 * @param {string} cookie — The sessionid cookie value.
 */
function saveCookie(cookie) {
  localStorage.setItem(COOKIE_STORAGE_KEY, cookie);
}

/**
 * Retrieve a previously saved session cookie from localStorage.
 *
 * @returns {string | null} The stored cookie, or null if absent.
 */
function getSavedCookie() {
  return localStorage.getItem(COOKIE_STORAGE_KEY);
}

/** Remove the persisted session cookie (e.g. on logout or when stale). */
function clearSavedCookie() {
  localStorage.removeItem(COOKIE_STORAGE_KEY);
}

/**
 * Persist the backend session ID so that page reloads can reuse the
 * existing Instaloader session without contacting Instagram again.
 *
 * @param {string} sessionId — The UUID4 session identifier from /api/login.
 */
function saveSessionId(sessionId) {
  localStorage.setItem(SESSION_ID_STORAGE_KEY, sessionId);
}

/**
 * Retrieve a previously saved backend session ID.
 *
 * @returns {string | null} The stored session ID, or null if absent.
 */
function getSavedSessionId() {
  return localStorage.getItem(SESSION_ID_STORAGE_KEY);
}

/** Remove the persisted session ID (e.g. on logout or when the session expires). */
function clearSavedSessionId() {
  localStorage.removeItem(SESSION_ID_STORAGE_KEY);
}

/* ==========================================================================
   Session Expiry & Transparent Re-authentication
   ========================================================================== */

/**
 * Attempt to re-authenticate with the backend using a cookie saved in
 * localStorage. This allows the app to recover silently when the
 * server-side session expires without forcing the user back to the
 * login screen.
 *
 * @returns {Promise<boolean>} True if re-authentication succeeded and
 *   state.sessionId has been refreshed; false otherwise.
 */
async function tryReauthenticate() {
  const savedCookie = getSavedCookie();
  if (!savedCookie) {
    return false;
  }

  try {
    const data = await apiPost("/login", { session_cookie: savedCookie });
    state.sessionId = data.session_id;
    saveSessionId(data.session_id);
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      /* Cookie is genuinely stale — clear everything. */
      clearSavedCookie();
      clearSavedSessionId();
    }
    /* Network / abort errors leave stored credentials intact for the next attempt. */
    return false;
  }
}

/**
 * Clear the in-memory session and redirect the user to the login screen
 * with an explanatory message. Does NOT clear the persisted cookie —
 * callers (or tryReauthenticate) are responsible for that when the
 * cookie is known to be stale.
 *
 * @param {string} message — Error text shown on the login screen.
 */
function redirectToLogin(message) {
  state.sessionId = null;
  clearSavedSessionId();
  navigateTo(screens.login);
  showError(els.loginError, message);
}

/**
 * Handle an API error that may signal an expired or invalid session
 * (HTTP 401). Attempts transparent re-authentication using a saved
 * cookie before falling back to the login screen.
 *
 * @param {Error} err — The error thrown by apiPost.
 * @returns {Promise<"not_session_error" | "reauthenticated" | "redirected">}
 *   - "not_session_error": The error was not a 401; caller should handle it.
 *   - "reauthenticated": Re-auth succeeded; caller should retry the request.
 *   - "redirected": Cookie is stale; user has been sent to the login screen.
 */
async function handleSessionExpiry(err) {
  if (!(err instanceof ApiError && err.status === 401)) {
    return "not_session_error";
  }

  if (await tryReauthenticate()) {
    return "reauthenticated";
  }

  /* Pick a message based on whether tryReauthenticate cleared the cookie
     (stale → gone) or kept it (network error → still present). */
  redirectToLogin(
    getSavedCookie()
      ? "Could not reconnect to Instagram. Please try again."
      : "Your session cookie has expired. Please paste a new one."
  );
  return "redirected";
}

/* ==========================================================================
   Screen 0 — Login
   ========================================================================== */

/**
 * Handle the login form submission.
 * Validates the session cookie input, authenticates via the API,
 * stores the session ID, and advances to the Paste Link screen.
 *
 * @param {SubmitEvent} event
 */
async function handleLogin(event) {
  event.preventDefault();
  hideError(els.loginError);

  const sessionCookie = els.sessionCookieInput.value.trim();

  if (!sessionCookie) {
    showError(els.loginError, "Please paste your Instagram session cookie.");
    return;
  }

  setButtonLoading(els.loginBtn, true);

  try {
    const data = await apiPost("/login", { session_cookie: sessionCookie });
    state.sessionId = data.session_id;

    /* Persist credentials so we can skip re-login on future page loads. */
    saveCookie(sessionCookie);
    saveSessionId(data.session_id);

    /* Clear the cookie input for security. */
    els.sessionCookieInput.value = "";

    navigateTo(screens.pasteLink);
  } catch (err) {
    showError(els.loginError, err.message);
  } finally {
    setButtonLoading(els.loginBtn, false);
  }
}

/**
 * Log the user out by clearing the session on the server and locally,
 * then navigate back to the login screen.
 */
async function handleLogout() {
  if (state.sessionId) {
    try {
      await apiPost("/logout", { session_id: state.sessionId });
    } catch {
      /* Best-effort — proceed with local cleanup even if the server call fails. */
    }
  }

  state.sessionId = null;
  clearSavedCookie();
  clearSavedSessionId();
  navigateTo(screens.login);
}

/* ==========================================================================
   Screen 1 — Paste Link
   ========================================================================== */

/**
 * Handle the "Fetch Comments" form submission.
 * Validates the URL, calls the API, stores the response, and advances
 * to the Settings screen.
 *
 * @param {SubmitEvent} event
 */
async function handleFetchComments(event) {
  event.preventDefault();
  hideError(els.urlError);

  const url = els.urlInput.value.trim();

  if (!url) {
    showError(els.urlError, "Please paste an Instagram link.");
    return;
  }

  if (!INSTAGRAM_URL_RE.test(url)) {
    showError(
      els.urlError,
      "That doesn't look like a valid Instagram post URL."
    );
    return;
  }

  setButtonLoading(els.fetchBtn, true);
  const labelEl = els.fetchBtn.querySelector(".btn__label");
  const originalText = labelEl.textContent;
  labelEl.textContent = "FETCHING...";

  try {
    const data = await apiPost("/fetch-comments", {
      url,
      session_id: state.sessionId,
    });
    state.users = data.users;
    state.totalComments = data.total_comments;
    navigateTo(screens.settings);
  } catch (err) {
    const result = await handleSessionExpiry(err);

    if (result === "reauthenticated") {
      /* Backend session was refreshed — retry the request once. */
      try {
        const data = await apiPost("/fetch-comments", {
          url,
          session_id: state.sessionId,
        });
        state.users = data.users;
        state.totalComments = data.total_comments;
        navigateTo(screens.settings);
      } catch (retryErr) {
        showError(els.urlError, retryErr.message);
      }
    } else if (result === "not_session_error") {
      showError(els.urlError, err.message);
    }
    /* "redirected" — user is already on the login screen, nothing to do. */
  } finally {
    labelEl.textContent = originalText;
    setButtonLoading(els.fetchBtn, false);
  }
}

/* ==========================================================================
   Screen 2 — Giveaway Settings
   ========================================================================== */

/**
 * Handle clicks on the option-button groups (number of winners and
 * minimum comments). Updates visual selection state and application state.
 *
 * @param {MouseEvent} event
 */
function handleOptionClick(event) {
  const btn = event.target.closest(".option-btn");
  if (!btn) {
    return;
  }

  const setting = btn.dataset.setting;
  const value = Number(btn.dataset.value);

  /* Deselect siblings within the same option-group. */
  const group = btn.closest(".option-group");
  group.querySelectorAll(".option-btn").forEach((sibling) => {
    sibling.classList.remove("option-btn--selected");
    sibling.setAttribute("aria-pressed", "false");
  });

  /* Select the clicked button. */
  btn.classList.add("option-btn--selected");
  btn.setAttribute("aria-pressed", "true");

  /* Update state. */
  if (setting === "num-winners") {
    state.numWinners = value;
  } else if (setting === "min-comments") {
    state.minComments = value;
  }
}

/**
 * Handle the "Run Giveaway" button click.
 * Sends settings + user data to the API, stores the winners, and starts
 * the searching animation.
 */
async function handleRunGiveaway() {
  hideError(els.settingsError);
  setButtonLoading(els.runGiveawayBtn, true);

  try {
    const data = await apiPost("/pick-winners", {
      users: state.users,
      num_winners: state.numWinners,
      min_comments: state.minComments,
    });

    state.winners = data.winners;

    navigateTo(screens.searching);
    await runSearchingAnimation(state.winners);
    showResults(state.winners);
  } catch (err) {
    showError(els.settingsError, err.message);
  } finally {
    setButtonLoading(els.runGiveawayBtn, false);
  }
}

/* ==========================================================================
   Screen 3 — Searching Animation
   ========================================================================== */

/**
 * Return a shuffled copy of the CONGRATS_MESSAGES array so that each
 * winner in a single giveaway gets a unique message.
 *
 * @returns {string[]} Shuffled congratulatory messages.
 */
function shuffleCongratsMessages() {
  const pool = [...CONGRATS_MESSAGES];
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool;
}

/**
 * Show the searching/countdown phase and hide the winner reveal phase.
 */
function showSearchingPhase() {
  els.searchingPhase.hidden = false;
  els.winnerReveal.hidden = true;
}

/**
 * Show the winner reveal phase and hide the searching/countdown phase.
 * Strips and re-applies CSS animations so the entrance effect replays
 * for every winner, not just the first.
 *
 * @param {string} username — The winner's Instagram handle (without @).
 * @param {string} congratsText — The unique congrats message for this winner.
 */
function showRevealPhase(username, congratsText) {
  els.searchingPhase.hidden = true;

  els.revealCongrats.textContent = congratsText;
  els.revealUsername.textContent = `@${username}`;

  /*
   * To replay CSS animations we must:
   * 1. Strip the animation (animation: none).
   * 2. Make the element visible (remove hidden).
   * 3. Force a synchronous reflow so the browser commits the no-animation state.
   * 4. Remove the inline override so the stylesheet animation kicks in fresh.
   */
  els.winnerReveal.style.animation = "none";
  els.revealUsername.style.animation = "none";
  els.winnerReveal.hidden = false;
  void els.winnerReveal.offsetWidth;
  els.winnerReveal.style.animation = "";
  els.revealUsername.style.animation = "";
}

/**
 * Wait for a specified number of seconds.
 *
 * @param {number} seconds — Duration to wait.
 * @returns {Promise<void>}
 */
function wait(seconds) {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/**
 * Run the full suspense animation sequence for all winners:
 * [Countdown] → [Reveal Winner] → [Countdown] → [Reveal Winner] → …
 *
 * Each winner gets a unique congratulatory message drawn from a
 * pre-shuffled pool so no two winners see the same text.
 *
 * @param {string[]} winners — Array of winner usernames.
 * @returns {Promise<void>} Resolves when all winners have been revealed.
 */
async function runSearchingAnimation(winners) {
  const congratsPool = shuffleCongratsMessages();

  for (let i = 0; i < winners.length; i++) {
    /* --- Countdown phase --- */
    showSearchingPhase();
    els.findingLabel.textContent = `FINDING WINNER ${i + 1}`;
    await animateCountdown();

    /* --- Reveal phase --- */
    const congrats = congratsPool[i % congratsPool.length];
    els.findingLabel.textContent = `WINNER ${i + 1}`;
    showRevealPhase(winners[i], congrats);
    await wait(WINNER_REVEAL_SECONDS);
  }

  /* Ensure we return to the searching phase state for next time. */
  showSearchingPhase();
}

/**
 * Animate a single countdown cycle: fills the SVG arc from 0 → 100%
 * while the numeric countdown ticks from COUNTDOWN_SECONDS → 0.
 *
 * @returns {Promise<void>} Resolves when the countdown reaches zero.
 */
function animateCountdown() {
  return new Promise((resolve) => {
    let remaining = COUNTDOWN_SECONDS;
    const totalSteps = COUNTDOWN_SECONDS;

    /* Reset the arc to fully hidden (offset = full circumference). */
    els.progressArc.style.transition = "none";
    els.progressArc.style.strokeDashoffset = `${RING_CIRCUMFERENCE}`;

    /* Force reflow so the reset takes effect before we animate. */
    void els.progressArc.offsetWidth;

    /* Re-enable the CSS transition for smooth animation. */
    els.progressArc.style.transition = "stroke-dashoffset 1s linear";

    /* Display initial countdown value. */
    els.countdown.textContent = String(remaining).padStart(2, "0");

    const interval = setInterval(() => {
      remaining -= 1;

      /* Calculate how much of the ring to reveal. */
      const progress = (totalSteps - remaining) / totalSteps;
      const offset = RING_CIRCUMFERENCE * (1 - progress);
      els.progressArc.style.strokeDashoffset = `${offset}`;

      /* Update the countdown number. */
      els.countdown.textContent = String(remaining).padStart(2, "0");

      if (remaining <= 0) {
        clearInterval(interval);
        /* Brief pause at completion before resolving. */
        setTimeout(resolve, 400);
      }
    }, 1000);
  });
}

/* ==========================================================================
   Screen 4 — Winner Results
   ========================================================================== */

/**
 * Populate the winners list and navigate to the results screen.
 *
 * @param {string[]} winners — Array of winner usernames.
 */
function showResults(winners) {
  els.winnersList.innerHTML = "";

  /** Predefined avatar gradient pairs for visual variety. */
  const avatarGradients = [
    "linear-gradient(135deg, #8b1a1a, #d4a844)",
    "linear-gradient(135deg, #d4a844, #e8785c)",
    "linear-gradient(135deg, #6b5e54, #8b1a1a)",
    "linear-gradient(135deg, #e8785c, #d4a844)",
    "linear-gradient(135deg, #8b1a1a, #6b5e54)",
  ];

  winners.forEach((username, index) => {
    const li = document.createElement("li");
    li.className = "winner-card";

    const avatar = document.createElement("span");
    avatar.className = "winner-card__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.style.background = avatarGradients[index % avatarGradients.length];

    const name = document.createElement("span");
    name.className = "winner-card__username";
    name.textContent = `@${username}`;

    const trophy = document.createElement("span");
    trophy.className = "winner-card__trophy";
    trophy.setAttribute("aria-hidden", "true");
    trophy.textContent = "\uD83C\uDFC6"; /* 🏆 */

    li.append(avatar, name, trophy);
    els.winnersList.appendChild(li);
  });

  navigateTo(screens.results);
}

/* ==========================================================================
   Screen 4 — Actions (Share & Run Again)
   ========================================================================== */

/**
 * Build a shareable text summary of the giveaway results and attempt to
 * use the Web Share API; falls back to copying to the clipboard.
 */
async function handleShare() {
  const winnerText = state.winners.map((u) => `@${u}`).join(", ");
  const shareText =
    `\uD83C\uDF89 Giveaway Results!\n\n` +
    `Our lucky winner${state.winners.length > 1 ? "s" : ""}: ${winnerText}\n\n` +
    `Picked with Givegram \u2728`;

  if (navigator.share) {
    try {
      await navigator.share({ text: shareText });
      return;
    } catch {
      /* User cancelled or share failed — fall through to clipboard. */
    }
  }

  try {
    await navigator.clipboard.writeText(shareText);
    const originalText = els.shareBtn.textContent;
    els.shareBtn.textContent = "COPIED!";
    setTimeout(() => {
      els.shareBtn.textContent = originalText;
    }, 2000);
  } catch {
    /* Clipboard API unavailable — open a prompt as last resort. */
    window.prompt("Copy the results:", shareText);
  }
}

/**
 * Reset the giveaway state (but keep the session) and navigate back
 * to the Paste Link screen so the user can start a new giveaway
 * without re-authenticating.
 */
function handleRunAgain() {
  state.users = [];
  state.totalComments = 0;
  state.numWinners = 1;
  state.minComments = 1;
  state.winners = [];

  /* Reset settings UI to defaults. */
  document.querySelectorAll(".option-btn").forEach((btn) => {
    const isDefault = btn.dataset.value === "1";
    btn.classList.toggle("option-btn--selected", isDefault);
    btn.setAttribute("aria-pressed", String(isDefault));
  });

  /* Clear previous input & errors. */
  els.urlInput.value = "";
  hideError(els.urlError);
  hideError(els.settingsError);
  els.winnersList.innerHTML = "";

  /* Navigate to paste-link, not login — session is still valid. */
  navigateTo(screens.pasteLink);
}

/* ==========================================================================
   Event Binding
   ========================================================================== */

/**
 * Wire up all event listeners and attempt to restore a previous session
 * from localStorage so the user skips the login screen when possible.
 */
async function init() {
  /* Screen 0 — Login */
  els.loginForm.addEventListener("submit", handleLogin);

  /* Screen 1 — Paste Link */
  els.fetchForm.addEventListener("submit", handleFetchComments);

  /* Logout link (if present in the DOM). */
  const logoutLink = document.getElementById("logout-link");
  if (logoutLink) {
    logoutLink.addEventListener("click", (event) => {
      event.preventDefault();
      handleLogout();
    });
  }

  /* Screen 2 — delegate option clicks to the settings content area */
  screens.settings
    .querySelector(".screen__content")
    .addEventListener("click", handleOptionClick);
  els.runGiveawayBtn.addEventListener("click", handleRunGiveaway);

  /* Screen 4 */
  els.shareBtn.addEventListener("click", handleShare);
  els.runAgainBtn.addEventListener("click", handleRunAgain);

  /*
   * Restore session using a two-tier strategy to minimise Instagram API hits:
   *
   *   1. Try the stored backend session_id via /api/validate-session.
   *      This is a cheap in-memory check — no Instagram contact at all.
   *
   *   2. If that fails (server restarted / session expired), fall back to
   *      re-login with the stored cookie. This DOES hit Instagram, but
   *      only when absolutely necessary.
   *
   *   3. If neither credential is available, show the login screen.
   *
   * The loading indicator stays visible until navigateTo() is called.
   */
  const savedSessionId = getSavedSessionId();
  const savedCookie = getSavedCookie();

  /* --- Tier 1: reuse existing backend session (no Instagram hit) --- */
  if (savedSessionId) {
    try {
      await apiPost("/validate-session", { session_id: savedSessionId });
      state.sessionId = savedSessionId;
      navigateTo(screens.pasteLink);
      return;
    } catch {
      /* Session gone (server restart / TTL) — clear stale id, try cookie. */
      clearSavedSessionId();
    }
  }

  /* --- Tier 2: re-login with stored cookie (contacts Instagram) --- */
  if (savedCookie) {
    try {
      const data = await apiPost("/login", { session_cookie: savedCookie });
      state.sessionId = data.session_id;
      saveSessionId(data.session_id);
      navigateTo(screens.pasteLink);
      return;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        /* Cookie is genuinely stale — clear everything. */
        clearSavedCookie();
        clearSavedSessionId();
        navigateTo(screens.login);
        showError(
          els.loginError,
          "Your saved session has expired. Please paste a new cookie."
        );
      } else {
        /* Network / abort error — keep credentials for the next attempt. */
        navigateTo(screens.login);
      }
      return;
    }
  }

  /* --- Tier 3: no stored credentials — show login screen --- */
  navigateTo(screens.login);
}

init();
