# Redundancy Reduction Plan

## 1. Extract duplicate fetch-comments block in `app.js`

**File:** `frontend/js/app.js`
**Severity:** Medium

`handleFetchComments` contains the same 4-line API call + state assignment block twice — once for the initial attempt and once for the retry after re-authentication.

**Current (lines 461–468 and 475–481):**

```js
const data = await apiPost("/fetch-comments", {
  url,
  session_id: state.sessionId,
});
state.users = data.users;
state.totalComments = data.total_comments;
navigateTo(screens.settings);
```

**Action:** Extract into a helper function (e.g. `doFetchComments(url)`) and call it from both places.

---

## 2. Reuse `tryReauthenticate()` in `init()` Tier 2

**File:** `frontend/js/app.js`
**Severity:** Medium

`tryReauthenticate()` (lines 297–317) and `init()` Tier 2 (lines 901–924) both implement the same pattern: call `/api/login` with the saved cookie, store the session ID on success, clear storage on 401.

**Action:** Refactor `init()` Tier 2 to call `tryReauthenticate()` and handle navigation/error display around its return value:

```js
if (savedCookie) {
  if (await tryReauthenticate()) {
    navigateTo(screens.pasteLink);
    return;
  }
  // handle failure: show login screen with appropriate message
}
```

---

## 3. Remove duplicate log line in `scraper.py`

**File:** `backend/scraper.py`
**Severity:** Low

Line 226 and line 259 both log the fetched comment count. Line 259 is strictly more informative (includes the shortcode), so line 226 is redundant.

**Action:** Remove line 226:

```python
logger.info("Successfully fetched %d comments", len(comments))
```

The remaining line 259 already covers this:

```python
logger.info("Fetched %d comments from post %s", len(comments), shortcode)
```

---

## 4. Remove dead pylint config from `pyproject.toml`

**File:** `pyproject.toml`
**Severity:** Low

The project uses ruff exclusively (CI workflow, user rules, `.ruff_cache`). The `[tool.pylint.format]` and `[tool.pylint."messages control"]` sections are unused. `line-length = 120` is already declared under `[tool.ruff]`.

**Action:** Delete lines 34–41:

```toml
[tool.pylint.format]
max-line-length = 120

[tool.pylint."messages control"]
disable = [
    "import-error",
    "too-few-public-methods",
]
```

---

## 5. Add missing entries to `.gitignore`

**File:** `.gitignore`
**Severity:** Low

Several generated directories/files are not explicitly excluded:

- `.mypy_cache/`
- `.pytest_cache/`
- `.ruff_cache/`
- `.coverage`
- `htmlcov/`

**Action:** Append the following to `.gitignore`:

```gitignore
# Caches
.mypy_cache/
.pytest_cache/
.ruff_cache/

# Coverage
.coverage
htmlcov/
```

---

## 6. Update README API table

**File:** `README.md`
**Severity:** Low

The API table only documents 2 of the 5 endpoints. `/api/login`, `/api/logout`, and `/api/validate-session` are missing.

**Action:** Replace the current table with:

```markdown
| Method | Endpoint                 | Description                                       |
|--------|--------------------------|---------------------------------------------------|
| POST   | `/api/login`             | Authenticate with an Instagram session cookie      |
| POST   | `/api/logout`            | Invalidate a backend session                       |
| POST   | `/api/validate-session`  | Check if a backend session is still alive          |
| POST   | `/api/fetch-comments`    | Accepts Instagram URL, returns usernames + counts  |
| POST   | `/api/pick-winners`      | Accepts user list + settings, returns winners      |
```
