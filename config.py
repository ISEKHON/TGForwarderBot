"""
Configuration module for Telegram Auto-Forwarder Bot
Loads all environment variables and provides validation
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Bot configuration loaded from environment variables"""
    
    # Telegram API credentials
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    API_ID = os.getenv("API_ID")
    API_HASH = os.getenv("API_HASH")
    
    # Channel IDs (must be numeric with - prefix for channels)
    MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID", 0))
    BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID", 0))
    TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", 0))
    
    # Forwarding configuration
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 100))
    FORWARD_DELAY = float(os.getenv("FORWARD_DELAY", 1.5))
    
    # Database configuration
    DB_NAME = os.getenv("DB_NAME", "forwarder.db")
    
    @classmethod
    def validate(cls):
        """Validate all required configuration values"""
        errors = []
        
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is not set")
        if not cls.API_ID:
            errors.append("API_ID is not set")
        if not cls.API_HASH:
            errors.append("API_HASH is not set")
        if cls.MAIN_CHANNEL_ID == 0:
            errors.append("MAIN_CHANNEL_ID is not set or invalid")
        if cls.BACKUP_CHANNEL_ID == 0:
            errors.append("BACKUP_CHANNEL_ID is not set or invalid")
        if cls.TARGET_CHANNEL_ID == 0:
            errors.append("TARGET_CHANNEL_ID is not set or invalid")
        
        if errors:
            raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return True


# Validate configuration on import
try:
    Config.validate()
    print("✓ Configuration validated successfully")
except ValueError as e:
    print(f"✗ Configuration validation failed:\n{e}")
    print("\nPlease copy .env.example to .env and fill in all required values.")
    exit(1)
