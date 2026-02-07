# Gamification

A classroom gamification application providing badges, awards, and point tracking for students.

## Architecture

This application is built with:
- **FastAPI**: Modern, high-performance web framework for Python.
- **SQLAlchemy**: Powerful SQL toolkit and Object-Relational Mapper (ORM).
- **Jinja2**: Server-side templating engine for rendering HTML.
- **JWT Authentication**: Modern and robust authentication using JSON Web Tokens stored in HttpOnly cookies.
- **Bootstrap 5**: Responsive CSS framework for the frontend.

## Setup

1. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
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

By default, the server runs on `http://localhost:5000`.

## Authentication

The application uses a custom JWT-based authentication system.
- Tokens are issued upon login and stored in an `access_token` HttpOnly cookie.
- The `get_current_user` dependency validates the token and retrieves the user from the database.
- Permissions are handled via `require_user` and `require_role` dependencies.

## (Optional) Seed and manage database data

### Full reset + seed (legacy behavior)
```bash
python seeds/seed.py
# or
python seeds/manage_data.py reset-and-seed
```

### Scriptable data-management actions
```bash
python seeds/manage_data.py reset-database
python seeds/manage_data.py reset-admin-users
python seeds/manage_data.py seed-test-data
python seeds/manage_data.py delete-test-data
```

- `reset-database` backs up the SQLite DB into `backups/`, deletes it, and recreates tables.
- `reset-admin-users` re-creates default admin/issuer users.
- `seed-test-data` seeds sample students, courses, badges, and awards.
- `delete-test-data` removes the seeded test users/courses/badges/awards.
