# MMC Backend

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Database

`DATABASE_URL` supports:

- `sqlite:///./mmc.db` for local development
- `postgresql+psycopg2://...` for PostgreSQL
- `mysql+pymysql://...` for MySQL

See `.env.example` for upload, database, and admin settings.

## Default admin

- `username`: `admin`
- `password`: `admin123`

Change these with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

## Available endpoints

- `POST /api/admin/login`
- `GET /api/admin/me`
- `GET /api/notices/categories`
- `GET /api/notices`
- `GET /api/notices/admin`
- `GET /api/notices/admin/{id}`
- `POST /api/notices/admin`
- `PATCH /api/notices/admin/{id}`
- `DELETE /api/notices/admin/{id}`

## Notes

- This backend now excludes the Hostel ERP codebase.
- The standalone Hostel ERP backend lives in `hostel-erp-backend/`.
- Notices and admin notice management routes remain available under `/api/notices`.
