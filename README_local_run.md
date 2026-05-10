t incidentso# Local run (Windows) - Docker Compose

This repo snapshot contains `main.py`, `App.jsx`, `App.css`, `package.json` at the repository root.

This guide assumes we create a `backend/` and `frontend/` directory structure (done by `setup_app_layout.py`) so that `docker-compose.yml` builds correctly.

## 1) One-time layout setup
```bat
python setup_app_layout.py
```

## 2) Start services
```bat
docker-compose up -d --build
```

## 3) Verify
- Frontend: http://localhost:5173
- Backend docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/health

## 4) Login
- Email: user@example.com
- Password: password123

---

## Render (Hosted) Note
On Render, do **not** rely on `localhost` URLs.
Set the frontend service environment variable:

- `VITE_API_URL=https://devops-crud-chatbot.onrender.com`

# Render frontend URL (for CORS)
- `https://devops-crud-chatbot-1.onrender.com`


