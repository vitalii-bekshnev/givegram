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

  /* Screen 3 */
  findingLabel: document.getElementById("finding-winner-label"),
  progressArc: document.querySelector(".progress-ring__arc"),
  countdown: document.getElementById("countdown-number"),

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
   Session Expiry Helper
   ========================================================================== */

/**
 * If an API error signals an expired or invalid session (HTTP 401),
 * clear the session state and redirect the user to the login screen.
 *
 * @param {Error} err — The error thrown by apiPost.
 * @returns {boolean} True if the error was a 401 and the redirect was triggered.
 */
function handleSessionExpiry(err) {
  if (err instanceof ApiError && err.status === 401) {
    state.sessionId = null;
    navigateTo(screens.login);
    showError(els.loginError, "Session expired, please log in again.");
    return true;
  }
  return false;
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
      "That doesn\u2019t look like a valid Instagram post URL."
    );
    return;
  }

  setButtonLoading(els.fetchBtn, true);

  try {
    const data = await apiPost("/fetch-comments", {
      url,
      session_id: state.sessionId,
    });
    state.users = data.users;
    state.totalComments = data.total_comments;
    navigateTo(screens.settings);
  } catch (err) {
    if (!handleSessionExpiry(err)) {
      showError(els.urlError, err.message);
    }
  } finally {
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
 * Run the suspense countdown animation for each winner sequentially.
 * The progress ring fills over COUNTDOWN_SECONDS while the countdown
 * number ticks down.
 *
 * @param {string[]} winners — Array of winner usernames.
 * @returns {Promise<void>} Resolves when all animations are complete.
 */
async function runSearchingAnimation(winners) {
  for (let i = 0; i < winners.length; i++) {
    els.findingLabel.textContent = `FINDING WINNER ${i + 1}`;
    await animateCountdown();
  }
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

/** Wire up all event listeners once the DOM is ready. */
function init() {
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
}

init();
