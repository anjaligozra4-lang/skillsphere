# SkillSphere Setup

## Backend

1. Install Python 3.12.
2. Create MySQL database:
   `mysql -u root -p < database/setup_mysql.sql`
3. Copy `backend/.env.example` to `backend/.env`.
4. Replace MySQL credentials, generate a JWT secret, and set a strong `ADMIN_PASSWORD` for the initial administrator account.
5. Install dependencies and apply migrations before starting the API.

The configured administrator account is created on backend startup if its email is not already registered. Admin accounts cannot be created through public signup; use the administrator login page at `/admin/login`.

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8001
```

For an existing database created by the earlier app before Alembic was applied, run `python -m alembic stamp ee73bf78fa6e` once, followed by `python -m alembic upgrade head`. Do this before starting the updated backend.

Swagger: `http://127.0.0.1:8001/docs`

## Frontend

```powershell
cd frontend
npm.cmd install
copy .env.example .env
npm.cmd run dev
```

Frontend: `http://localhost:5173`

## Tesseract

Install Tesseract OCR and add its executable directory to `PATH`. PDFs and images are first checked for embedded text; OCR is used for scanned pages and images.

Uploads accept PDF, JPG/JPEG, and PNG files up to 10 MB. The backend checks the content signature, records processing status and errors, and stores extracted text page-by-page for resume review.
