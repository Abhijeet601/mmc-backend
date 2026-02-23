# MMC Backend (FastAPI)

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Deploy on Railway

- Ensure the Railway service points to this `backend` directory (if your repo also has `frontend`).
- A `Procfile` is included with an explicit start command:
  `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`
- Set environment variables from `.env.example` in Railway.

## Default admin

- `username`: `admin`
- `password`: `admin123`

Change these via `.env`.

## Key endpoints

- `POST /api/admin/login`
- `GET /api/admin/me`
- `GET /api/notices?publish_to=tenders|upcoming_events|notifications|notices`
- `GET /api/notices/admin` (auth)
- `POST /api/notices/admin` (auth, multipart form)
- `PATCH /api/notices/admin/{id}` (auth, multipart form)
- `DELETE /api/notices/admin/{id}` (auth)

`POST/PATCH /api/notices/admin` supports `publish_date` (ISO datetime) to schedule publication.

On startup, the backend also auto-imports files from `NOTICE_SOURCE_DIR` (default: `../frontend/data files/Notice`)
into both `publish_to=notices` and `publish_to=notifications`, and serves them via `/uploads/source-notices/...`.
