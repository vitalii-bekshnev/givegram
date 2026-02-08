# Givegram — Instagram Giveaway Winner Picker

A simple web app that picks random winners from Instagram post comments. Paste a public Instagram post link, configure giveaway settings, and let the app randomly select winners.

## Features

- Fetch comments from any public Instagram post
- Filter participants by minimum comment count
- Pick 1–5 random winners
- Animated winner reveal with suspense UX
- Mobile-first responsive design

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, Instaloader
- **Frontend**: Vanilla HTML / CSS / JS (no framework)
- **Server**: Uvicorn (serves both API and static frontend)

## Getting Started

### Prerequisites

- Python 3.12+

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running

```bash
source venv/bin/activate
uvicorn backend.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Project Structure

```
givegram/
  backend/
    main.py                # FastAPI app, static files mount, CORS
    scraper.py             # Instagram comment scraper using instaloader
    models.py              # Pydantic request/response models
    winner_selector.py     # Random winner selection logic
  frontend/
    index.html             # Single-page app with 4 screens
    css/styles.css         # Mobile-first styling
    js/app.js              # Screen navigation, API calls, animations
  pyproject.toml           # Project config + ruff settings
  requirements.txt         # Python dependencies
```

## API Endpoints

| Method | Endpoint               | Description                                      |
|--------|------------------------|--------------------------------------------------|
| POST   | `/api/fetch-comments`  | Accepts Instagram URL, returns usernames + counts |
| POST   | `/api/pick-winners`    | Accepts user list + settings, returns winners     |
