# Gamification

Badge and awards for a class.

## Setup

1. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
   Windows: 

   ```bash
   .\.venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. (Optional) Configure environment variables:
   - `SECRET_KEY` (default: `dev-secret-key-change-me`)
   - `DATABASE_URL` (default: `sqlite:///app.db`)
   - `APP_NAME` (default: `app`)
   - `APP_VERSION` (default: `1.0.0`)

   You can set these in a `.env` file in the project root or export them in your shell.

## Run the application

Start the FastAPI app with Uvicorn:
```bash
python run.py
```

By default, the server runs on `http://localhost:8000`.

## (Optional) Seed the database

If you want sample data, run:
```bash
python seeds/seed.py
```

This resets the database and prints the default admin credentials.
