from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    SECRET_KEY: str = "a_very_secret_key"
    DATABASE_URL: str = "sqlite:///database.db"

settings = Settings()
