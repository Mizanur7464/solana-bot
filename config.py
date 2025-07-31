import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# === CONFIGURATION ===
class Config:
    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not found in environment variables"
        )
    
    # Solana Token Configuration
    SOLANA_TOKEN_MINT = os.getenv('SOLANA_TOKEN_MINT')
    if not SOLANA_TOKEN_MINT:
        raise ValueError("SOLANA_TOKEN_MINT not found in environment variables")
    
    MIN_TOKEN_AMOUNT = int(os.getenv('MIN_TOKEN_AMOUNT', '50000'))
    
    # Channel and Admin IDs
    VIP_CHANNEL_ID = int(os.getenv('VIP_CHANNEL_ID', '0'))
    if not VIP_CHANNEL_ID:
        raise ValueError("VIP_CHANNEL_ID not found in environment variables")
    
    VIP_CHANNEL_LINK = os.getenv('VIP_CHANNEL_LINK')
    if not VIP_CHANNEL_LINK:
        raise ValueError("VIP_CHANNEL_LINK not found in environment variables")
    
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '0'))
    if not ADMIN_USER_ID:
        raise ValueError("ADMIN_USER_ID not found in environment variables")
    
    # Group ID for new member handling
    GROUP_ID = int(os.getenv('GROUP_ID', '0'))
    if not GROUP_ID:
        raise ValueError("GROUP_ID not found in environment variables")
    
    # File Configuration
    USERS_FILE = os.getenv('USERS_FILE', 'users.json')
    
    # Cache Configuration
    CACHE_DURATION = int(os.getenv('CACHE_DURATION', '300'))  # 5 minutes
    
    # Scheduler Configuration
    CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL_MINUTES', '60'))
    CHANNEL_CHECK_INTERVAL_HOURS = int(os.getenv('CHANNEL_CHECK_INTERVAL_HOURS', '2'))

# Create a config instance
try:
    config = Config()
    print("✅ Configuration loaded successfully!")
except ValueError as e:
    print(f"❌ Configuration Error: {e}")
    print("\n📝 Please create a .env file with the following variables:")
    print("TELEGRAM_BOT_TOKEN=your_bot_token_here")
    print("SOLANA_TOKEN_MINT=your_token_mint_here")
    print("VIP_CHANNEL_ID=your_channel_id_here")
    print("VIP_CHANNEL_LINK=your_channel_link_here")
    print("ADMIN_USER_ID=your_admin_id_here")
    print("GROUP_ID=your_group_id_here")
    exit(1) 