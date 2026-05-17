# Magadh Mahila College Hostel ERP Backend

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Stack

- FastAPI + SQLAlchemy
- JWT auth for admin and student workspaces
- MySQL-ready Railway deployment
- PDF receipt generation with QR support
- Hostel admission, renewal, payment, allocation, complaints, and reporting APIs

## Database

`DATABASE_URL` supports:

- `sqlite:///./mmc.db` for local development
- `postgresql+psycopg2://...` for PostgreSQL
- `mysql+pymysql://...` for MySQL

Railway MySQL can be configured with either:

- `DATABASE_URL` / `MYSQL_URL`
- or `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`

See `.env.example` for upload, payment gateway, database, CORS, and admin settings.

## Default admin

- `username`: `admin`
- `password`: `admin123`

Change these with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

## Core endpoints

- `GET /api/health`
- `POST /api/admin/login`
- `GET /api/admin/me`
- `POST /api/register`
- `POST /api/login`
- `POST /api/reset-password`
- `GET /api/application`
- `POST /api/application/draft`
- `POST /api/application/submit`
- `POST /api/application/start-renewal`
- `GET /api/dashboard`
- `POST /api/payment/application`
- `POST /api/payment/hostel`
- `GET /api/complaints`
- `POST /api/complaints`
- `GET /api/admin/dashboard`
- `GET /api/admin/students`
- `PATCH /api/admin/students/{student_id}/verify`
- `PATCH /api/admin/students/{student_id}/shortlist`
- `PATCH /api/admin/students/{student_id}/allocate-hostel`
- `GET /api/admin/payments`
- `POST /api/admin/approve-payment/{payment_id}`
- `POST /api/admin/reject-payment/{payment_id}`
- `GET /api/admin/complaints`
- `PATCH /api/admin/complaints/{complaint_id}`
- `GET /api/admin/hostel/rooms`
- `POST /api/admin/hostel/rooms`
- `PATCH /api/admin/hostel/rooms/{room_id}`
- `GET /api/activity-logs`

## Notes

- Startup seeds a default admin and a baseline room inventory for Vaidehi and Mahima hostels.
- Receipts are generated into `uploads/receipts`.
- Uploaded documents are stored under `uploads/photos`.
- Frontend should point `VITE_ERP_API_BASE` to the deployed backend origin.
