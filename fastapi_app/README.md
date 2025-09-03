# Gamification App (FastAPI Version)

This is a port of the original Flask-based gamification application to a modern stack using FastAPI, SQLModel, HTMX, and Bootstrap 5.

## Project Setup

### 1. Python Environment

It is recommended to use a virtual environment.

```bash
# Create a virtual environment
python -m venv venv

# Activate it
# On Windows
venv\\Scripts\\activate
# On macOS/Linux
source venv/bin/activate

# Install the required Python packages
pip install -r requirements.txt
```

### 2. Application Configuration

The application is configured using environment variables. Create a `.env` file in the `fastapi_app` directory by copying the `.env.example` file (if one exists) or by creating a new one.

A `SECRET_KEY` is required for signing session cookies. You can generate one with:
```bash
openssl rand -hex 32
```
Your `.env` file should look like this:
```
SECRET_KEY=your_generated_secret_key_here
DATABASE_URL=sqlite:///database.db
```

### 4. Database Migrations

This project uses Alembic to manage database migrations.

To create the database and apply all migrations, run:
```bash
alembic upgrade head
```

When you make changes to the models in `app/models/`, you will need to generate a new migration script:
```bash
alembic revision --autogenerate -m "A description of your changes"
```
Then, apply the new migration:
```bash
alembic upgrade head
```

### 5. Seeding the Database

To create a default admin user, you can run the admin seed script:
```bash
python seed_admin.py
```
This will create a user with the following credentials:
- **Email:** `admin@example.com`
- **Password:** `admin`

## Running the Application

### CSV Upload for Courses

You can bulk-upload courses using a CSV file on the "Courses" page. The CSV file must have the following columns: `name`, `semester`, and `year`.

A `sample_courses.csv` file is included in this directory to serve as an example.

### Running the Development Server

To run the application, use Uvicorn:
```bash
uvicorn app.main:app --reload
```
The application will be available at `http://127.0.0.1:8000`.

## Running the Tests

The tests are written using pytest. To run the tests, execute the following command from the `fastapi_app` directory:
```bash
PYTHONPATH=. pytest
```
