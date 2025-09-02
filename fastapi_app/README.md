# Gamification App (FastAPI Version)

This is a port of the original Flask-based gamification application to a modern stack using FastAPI, SQLModel, HTMX, and Tailwind CSS.

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

### 2. Node.js Environment

This project uses Tailwind CSS for styling. You will need Node.js and npm installed.

```bash
# Install the Node.js dependencies
npm install
```

### 3. Application Configuration

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

## Running the Application

### Building the CSS

Before running the application, you need to build the Tailwind CSS file.
```bash
npm run build:css
```
I have not yet added the `build:css` script to `package.json`. I will do that now.

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
