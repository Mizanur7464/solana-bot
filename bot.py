import json
import requests
import schedule
import time
import threading
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# === CONFIGURATION ===
TELEGRAM_BOT_TOKEN = "8415910797:AAHzVNLFhTEsjwpwQJBazMDtY6eTkCp4FwI"
SOLANA_TOKEN_MINT = "9UNqoPEXXxEnEphmyYsZYdL5dnmAUtdiKRUchpnUF5Ph"
MIN_TOKEN_AMOUNT = 50  # Set your minimum token amount here

USERS_FILE = "users.json"


# === Helper Functions ===

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def get_token_balance(wallet_address, token_mint):
    url = (
        "https://public-api.solscan.io/account/tokens?account="
        + wallet_address
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        tokens = resp.json()
        for token in tokens:
            if token.get('tokenAddress') == token_mint:
                return float(token.get('tokenAmount', {}).get('uiAmount', 0))
        return 0
    except Exception as e:
        print(f"Error fetching token balance: {e}")
        return None


# === Telegram Bot Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_users()
    if user_id in users and users[user_id].get('wallet'):
        await update.message.reply_text(
            f"Your wallet: {users[user_id]['wallet']}\nUse /verify to check again."
        )
    else:
        await update.message.reply_text(
            "Welcome! Please send your Solana wallet address:"
        )
        context.user_data['awaiting_wallet'] = True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_users()
    if context.user_data.get('awaiting_wallet'):
        wallet = update.message.text.strip()
        users[user_id] = {'wallet': wallet}
        save_users(users)
        context.user_data['awaiting_wallet'] = False
        await update.message.reply_text(
            f"Your wallet has been saved: {wallet}\nUse /verify to check tokens."
        )
    else:
        await update.message.reply_text(
            "Use /start to begin or /verify to check tokens."
        )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_users()
    wallet = users.get(user_id, {}).get('wallet')
    if not wallet:
        await update.message.reply_text(
            "No wallet found. Please use /start to provide your wallet address."
        )
        return
    await update.message.reply_text("Checking your token balance...")
    balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
    if balance is None:
        await update.message.reply_text(
            "Error checking balance. Please try again later."
        )
        return
    if balance >= MIN_TOKEN_AMOUNT:
        await update.message.reply_text(
            f"Congratulations! You have {balance} tokens in your wallet."
        )
    else:
        await update.message.reply_text(
            f"Sorry, you do not have the minimum {MIN_TOKEN_AMOUNT} tokens. "
            f"Your balance: {balance}"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start the bot\n/verify - Check your token balance\n/help - Help"
    )


# === Daily Check Function ===

def daily_check_job(app):
    users = load_users()
    for user_id, data in users.items():
        wallet = data.get('wallet')
        if not wallet:
            continue
        balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
        if balance is None:
            continue
        if balance < MIN_TOKEN_AMOUNT:
            try:
                app.bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        f"Alert: Your wallet does not have the minimum {MIN_TOKEN_AMOUNT} tokens. "
                        f"Current balance: {balance}"
                    ),
                )
            except Exception as e:
                print(f"Error sending message to {user_id}: {e}")


# === Scheduler Thread ===

def run_scheduler(app):
    schedule.every().day.at("00:00").do(daily_check_job, app)
    while True:
        schedule.run_pending()
        time.sleep(60)


# === Main Function ===

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Scheduler in background
    scheduler_thread = threading.Thread(
        target=run_scheduler, args=(app,), daemon=True
    )
    scheduler_thread.start()

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main() 