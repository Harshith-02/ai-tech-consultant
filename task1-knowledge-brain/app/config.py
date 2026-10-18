import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Knowledge Brain API"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = DATA_DIR / "knowledge_brain.db"
    MANIFEST_PATH: Path = DATA_DIR / "ingestion_manifest.json"
    RAW_ARTICLES_DIR: Path = DATA_DIR / "raw_articles"
    IMAGES_DIR: Path = DATA_DIR / "images"
    
    # Crawler settings
    SITEMAP_URL: str = "https://support.brilliantdirectories.com/support/sitemap.xml"
    USER_AGENT: str = "AI-Tech-Consultant/1.0 (+https://github.com/ai-tech-consultant)"
    CRAWL_DELAY_SECONDS: float = 0.3
    MAX_CRAWL_RETRIES: int = 3
    REQUEST_TIMEOUT_SECONDS: float = 15.0
    
    # Model & Retrieval settings
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL_PRIMARY: str = os.getenv("CLAUDE_MODEL_PRIMARY", "claude-3-5-sonnet-20241022")
    CLAUDE_MODEL_FAST: str = os.getenv("CLAUDE_MODEL_FAST", "claude-3-5-haiku-20241022")
    
    # Grounding & Abstention thresholds
    MIN_RELEVANCE_SCORE: float = 0.50
    MIN_CONFIDENCE_THRESHOLD: float = 0.50
    DEFAULT_TOP_K: int = 4
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.RAW_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
settings.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
