import json
import requests
import schedule
import time
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    ChatMemberHandler,
)

# Import configuration
from config import config

# === CONFIGURATION ===
TELEGRAM_BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
SOLANA_TOKEN_MINT = config.SOLANA_TOKEN_MINT
MIN_TOKEN_AMOUNT = config.MIN_TOKEN_AMOUNT

# Channel and Admin IDs
VIP_CHANNEL_ID = config.VIP_CHANNEL_ID
VIP_CHANNEL_LINK = config.VIP_CHANNEL_LINK
ADMIN_USER_ID = config.ADMIN_USER_ID

# Group ID for new member handling
GROUP_ID = config.GROUP_ID

USERS_FILE = config.USERS_FILE


# === Helper Functions ===

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            # Validate data structure
            if not isinstance(data, dict):
                print("⚠️ Invalid users.json format, resetting to empty dict")
                return {}
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def is_valid_solana_address(address):
    """Check if the address is a valid Solana wallet address"""
    if not address or len(address) != 44:
        return False
    # Basic Solana address validation (44 characters, base58)
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{44}$', address))


# Cache for token balances to avoid rate limiting
balance_cache = {}
CACHE_DURATION = 300  # 5 minutes

def get_token_balance(wallet_address, token_mint):
    """Get token balance from multiple APIs for reliability with caching"""
    
    # Check cache first
    cache_key = f"{wallet_address}_{token_mint}"
    current_time = time.time()
    
    if cache_key in balance_cache:
        cached_balance, cached_time = balance_cache[cache_key]
        if current_time - cached_time < CACHE_DURATION:
            print(f"Using cached balance: {cached_balance}")
            return cached_balance
    
    # Try Solana RPC first (most reliable, no rate limits)
    try:
        url = "https://api.mainnet-beta.solana.com"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"mint": token_mint},
                {"encoding": "jsonParsed"}
            ]
        }
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"Solana RPC response status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if 'result' in data and 'value' in data['result']:
                accounts = data['result']['value']
                if accounts:
                    amount = accounts[0]['account']['data']['parsed']['info']['tokenAmount']['uiAmount']
                    print(f"Solana RPC found balance: {amount}")
                    # Cache the result
                    balance_cache[cache_key] = (float(amount), current_time)
                    return float(amount)
                else:
                    print("No token accounts found in Solana RPC")
                    balance_cache[cache_key] = (0.0, current_time)
                    return 0.0
            else:
                print("Invalid response format from Solana RPC")
        elif resp.status_code == 429:
            print("Solana RPC rate limited, trying other APIs...")
        else:
            print(f"Solana RPC error: {resp.status_code}")
    except Exception as e:
        print(f"Solana RPC error: {e}")
    
    # Try Birdeye API as secondary option
    try:
        url = f"https://public-api.birdeye.so/public/portfolio?wallet={wallet_address}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"Birdeye API response status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and 'tokens' in data['data']:
                for token in data['data']['tokens']:
                    if token.get('mint') == token_mint:
                        amount = token.get('value', 0)
                        print(f"Birdeye API found balance: {amount}")
                        balance_cache[cache_key] = (float(amount), current_time)
                        return float(amount)
                print("Token not found in Birdeye portfolio")
            else:
                print("Invalid response format from Birdeye API")
        else:
            print(f"Birdeye API error: {resp.status_code}")
    except Exception as e:
        print(f"Birdeye API error: {e}")
    
    # Try Solscan API as last resort
    try:
        url = f"https://api.solscan.io/account/tokens?account={wallet_address}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"Solscan API response status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                for token in data['data']:
                    if token.get('mint') == token_mint:
                        amount = token.get('tokenAmount', {}).get('uiAmount', 0)
                        print(f"Solscan API found balance: {amount}")
                        balance_cache[cache_key] = (float(amount), current_time)
                        return float(amount)
                print("Token not found in Solscan data")
            else:
                print("Invalid response format from Solscan API")
        else:
            print(f"Solscan API error: {resp.status_code}")
    except Exception as e:
        print(f"Solscan API error: {e}")
    
    # If all APIs fail, return cached value if available
    if cache_key in balance_cache:
        cached_balance, _ = balance_cache[cache_key]
        print(f"All APIs failed, returning cached balance: {cached_balance}")
        return cached_balance
    
    print("All APIs failed and no cached value available")
    return None


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group"""
    if not update.message or not update.message.new_chat_members:
        return
    
    # Check if this is the target group
    if update.message.chat.id != GROUP_ID:
        return
    
    for new_member in update.message.new_chat_members:
        # Skip if the new member is the bot itself
        if new_member.id == context.bot.id:
            continue
        
        user_id = str(new_member.id)
        user_name = new_member.first_name or "User"
        user_username = new_member.username or "No username"
        
        print(f"New member joined: {user_name} (@{user_username}) - ID: {user_id}")
        
        # Welcome message in group (without wallet request)
        group_welcome = (
            f"🎉 **Welcome to the group, {user_name}!**\n\n"
            f"🔐 **VIP Access Available**\n"
            f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens to get VIP channel access.\n\n"
            "💳 **Check your private messages** for wallet verification instructions."
        )
        
        await update.message.reply_text(
            group_welcome,
            parse_mode='Markdown'
        )
        
        # Send wallet request privately
        try:
            private_welcome = (
                f"🎉 **Welcome, {user_name}!**\n\n"
                f"🔐 **VIP Access Available**\n"
                f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens to get VIP channel access.\n\n"
                "💳 **Please provide your Solana wallet address:**\n"
                "Send your wallet address to verify your token balance.\n\n"
                "Example: `7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP`"
            )
            
            # Create inline keyboard for wallet options
            keyboard = [
                [
                    InlineKeyboardButton("🔗 Connect Wallet", callback_data="connect_wallet"),
                    InlineKeyboardButton("📝 Manual Entry", callback_data="manual_entry")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=int(user_id),
                text=private_welcome,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Set user state to await wallet
            context.user_data['awaiting_wallet'] = True
            context.user_data['new_member'] = True
            
        except Exception as e:
            print(f"Error sending private message to {user_name}: {e}")
            # Fallback: ask in group if private message fails
            await update.message.reply_text(
                f"💳 **{user_name}, please provide your Solana wallet address:**\n"
                "Send your wallet address to verify your token balance.\n\n"
                "Example: `7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP`"
            )
            context.user_data['awaiting_wallet'] = True
            context.user_data['new_member'] = True


def verify_wallet_and_tokens(wallet_address):
    """Verify wallet and check if it has our tokens"""
    if not is_valid_solana_address(wallet_address):
        return False, "Invalid Solana wallet address format"
    
    # Check token balance
    balance = get_token_balance(wallet_address, SOLANA_TOKEN_MINT)
    if balance is None:
        return False, "Unable to fetch wallet data"
    
    return True, f"Wallet verified! Found {balance} tokens"


# === Channel Management Functions ===

async def check_user_tokens_and_manage_access(app, user_id, user_name, user_username):
    """Check user tokens and manage VIP channel access"""
    users = load_users()
    wallet = users.get(str(user_id), {}).get('wallet')
    
    if not wallet:
        print(f"❌ User {user_name} has no wallet registered")
        return False, "No wallet found"
    
    print(f"🔍 Checking tokens for user {user_name} (@{user_username})")
    balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
    
    if balance is None:
        print(f"❌ Error checking balance for user {user_name}")
        return False, "Error checking balance"
    
    if balance >= MIN_TOKEN_AMOUNT:
        print(f"✅ User {user_name} has sufficient tokens: {balance}")
        # Add user to VIP channel
        try:
            # Use create_chat_invite_link and send it to user instead of direct invite
            invite_link = await app.bot.create_chat_invite_link(
                chat_id=VIP_CHANNEL_ID,
                creates_join_request=False
            )
            return True, f"Access granted! You have {balance} tokens. Use this link: {invite_link.invite_link}"
        except Exception as e:
            print(f"Error creating invite link: {e}")
            return True, f"Tokens verified ({balance}) but channel access failed. Please contact admin."
    else:
        print(f"⚠️ User {user_name} has insufficient tokens: {balance}")
        # Notify admin about low balance
        try:
            await app.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🚨 Low Token Alert!\n\nUser: {user_name} (@{user_username})\nWallet: {wallet[:8]}...{wallet[-8:]}\nBalance: {balance} tokens\nRequired: {MIN_TOKEN_AMOUNT} tokens\nMissing: {MIN_TOKEN_AMOUNT - balance} tokens"
            )
        except Exception as e:
            print(f"Error notifying admin: {e}")
        
        # Remove user from VIP channel if they somehow got in
        try:
            await app.bot.ban_chat_member(
                chat_id=VIP_CHANNEL_ID,
                user_id=user_id
            )
            await app.bot.unban_chat_member(
                chat_id=VIP_CHANNEL_ID,
                user_id=user_id
            )
        except Exception as e:
            print(f"Error removing user from VIP channel: {e}")
        return False, f"Insufficient tokens. You have {balance}, need {MIN_TOKEN_AMOUNT}"


async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when someone tries to join the VIP channel"""
    if not update.chat_member:
        return
    
    # Check if this is the VIP channel
    if update.chat_member.chat.id != VIP_CHANNEL_ID:
        return
    
    user_id = str(update.chat_member.new_chat_member.user.id)
    user_name = update.chat_member.new_chat_member.user.first_name or "Unknown User"
    user_username = update.chat_member.new_chat_member.user.username or "No Username"
    
    # Skip if it's the bot itself
    if update.chat_member.new_chat_member.user.id == context.bot.id:
        return
    
    print(f"🔍 User {user_name} (@{user_username}) trying to join VIP channel")
    
    # Check if user has sufficient tokens
    success, message = await check_user_tokens_and_manage_access(
        context.application, int(user_id), user_name, user_username
    )
    
    if not success:
        print(f"❌ User {user_name} denied access to VIP channel: {message}")
        # Only notify admin, don't remove user automatically
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🚨 **User Joined VIP Channel with Insufficient Tokens!**\n\n"
                     f"User: {user_name} (@{user_username})\n"
                     f"User ID: {user_id}\n"
                     f"Status: {message}\n\n"
                     f"⚠️ **Action Required:**\n"
                     f"Please manually remove this user from the VIP channel if needed.\n"
                     f"Bot will not automatically remove users."
            )
        except Exception as e:
            print(f"Error notifying admin: {e}")
    else:
        print(f"✅ User {user_name} granted access to VIP channel")
        # Notify admin about successful join
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"✅ **User Successfully Joined VIP Channel!**\n\n"
                     f"User: {user_name} (@{user_username})\n"
                     f"User ID: {user_id}\n"
                     f"Status: {message}"
            )
        except Exception as e:
            print(f"Error notifying admin: {e}")


# === Telegram Bot Handlers ===

async def handle_vip_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle VIP channel access requests"""
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    user_username = update.effective_user.username or "No Username"
    
    print(f"🔐 VIP request from {user_name} (@{user_username})")
    
    # Check if user has wallet registered
    users = load_users()
    if user_id not in users or not users[user_id].get('wallet'):
        await update.message.reply_text(
            f"❌ **VIP Access Denied**\n\n"
            "You need to register your wallet first.\n"
            "Use /start to add your Solana wallet address.\n\n"
            f"Minimum required: {MIN_TOKEN_AMOUNT:,} tokens"
        )
        return
    
    # Check token balance and manage access
    success, message = await check_user_tokens_and_manage_access(
        context.application, int(user_id), user_name, user_username
    )
    
    if success:
        await update.message.reply_text(
            f"✅ **VIP Access Granted!**\n\n"
            f"{message}\n\n"
            f"🔗 VIP Channel: {VIP_CHANNEL_LINK}\n\n"
            "You now have access to our VIP channel!"
        )
    else:
        await update.message.reply_text(
            f"❌ **VIP Access Denied**\n\n"
            f"{message}\n\n"
            f"You need minimum {MIN_TOKEN_AMOUNT:,} tokens for VIP access.\n"
            "Add more tokens and try again."
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if effective_user exists
    if not update.effective_user:
        return
    
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    user_username = update.effective_user.username or "No Username"
    
    print(f"👤 User {user_name} (@{user_username}) started the bot")
    
    users = load_users()
    if user_id in users and users[user_id].get('wallet'):
        # Send private message
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"✅ **Wallet Registered**\n\n"
                     f"Your wallet: {users[user_id]['wallet'][:8]}...{users[user_id]['wallet'][-8:]}\n\n"
                     "Use /vip to request VIP channel access\n"
                     "Use /verify to check your token balance\n"
                     "Use /change to update your wallet"
            )
            # Confirm in group
            await update.message.reply_text(
                f"✅ **Welcome back, {user_name}!**\n\n"
                "Check your private messages for wallet details."
            )
        except Exception as e:
            await update.message.reply_text(
                f"✅ **Welcome back, {user_name}!**\n\n"
                f"Your wallet: {users[user_id]['wallet'][:8]}...{users[user_id]['wallet'][-8:]}\n\n"
                "Use /vip to request VIP channel access\n"
                "Use /verify to check your token balance\n"
                "Use /change to update your wallet"
            )
    else:
        # Create wallet connect button
        keyboard = [
            [InlineKeyboardButton("🔗 Connect Wallet", callback_data="connect_wallet")],
            [InlineKeyboardButton("📝 Manual Entry", callback_data="manual_entry")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send private message
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="🚀 Welcome to Solana Token Checker Bot!\n\n"
                     "🔐 **VIP Access Required**\n"
                     f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens to access VIP channel.\n\n"
                     "Choose how to connect your wallet:\n\n"
                     "🔗 **Connect Wallet** - Quick wallet connection\n"
                     "📝 **Manual Entry** - Type wallet address manually",
                reply_markup=reply_markup
            )
            # Confirm in group
            await update.message.reply_text(
                f"🎉 **Welcome, {user_name}!**\n\n"
                "Check your private messages to connect your wallet."
            )
        except Exception as e:
            await update.message.reply_text(
                "🚀 Welcome to Solana Token Checker Bot!\n\n"
                "🔐 **VIP Access Required**\n"
                f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens to access VIP channel.\n\n"
                "Choose how to connect your wallet:\n\n"
                "🔗 **Connect Wallet** - Quick wallet connection\n"
                "📝 **Manual Entry** - Type wallet address manually",
                reply_markup=reply_markup
            )
        context.user_data['awaiting_wallet'] = True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if effective_user exists
    if not update.effective_user:
        print("❌ No effective user found in update")
        return
    
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    user_username = update.effective_user.username or "No Username"
    users = load_users()
    
    if context.user_data.get('awaiting_wallet') or context.user_data.get(user_id, {}).get('awaiting_wallet'):
        wallet = update.message.text.strip()
        
        print(f"🔍 User {user_name} (@{user_username}) provided wallet: {wallet[:8]}...{wallet[-8:]}")
        
        # Validate wallet address
        if not is_valid_solana_address(wallet):
            print(f"❌ User {user_name} provided invalid wallet format")
            await update.message.reply_text(
                "❌ Invalid wallet address format!\n\n"
                "Please send a valid Solana wallet address.\n"
                "It should be 44 characters long.\n\n"
                "Example: 7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP"
            )
            return
        
        # Verify wallet and check tokens
        await update.message.reply_text("🔍 Verifying wallet and checking tokens...")
        is_valid, message = verify_wallet_and_tokens(wallet)
        
        if is_valid:
            users[user_id] = {'wallet': wallet}
            save_users(users)
            context.user_data['awaiting_wallet'] = False
            if user_id in context.user_data:
                context.user_data[user_id]['awaiting_wallet'] = False
            
            print(f"✅ User {user_name} wallet verified successfully")
            
            # Check VIP access
            success, access_message = await check_user_tokens_and_manage_access(
                context.application, int(user_id), user_name, user_username
            )
            
            if success:
                await update.message.reply_text(
                    f"✅ {message}\n\n"
                    f"🎉 **VIP Access Granted!**\n"
                    f"🔗 VIP Channel: {VIP_CHANNEL_LINK}\n"
                    f"Wallet saved: {wallet[:8]}...{wallet[-8:]}\n\n"
                    "Use /verify to recheck your balance"
                )
            else:
                await update.message.reply_text(
                    f"✅ {message}\n\n"
                    f"❌ **VIP Access Denied**\n"
                    f"{access_message}\n\n"
                    f"You need minimum {MIN_TOKEN_AMOUNT} tokens for VIP access.\n"
                    "Add more tokens and use /verify to try again."
                )
        else:
            print(f"❌ User {user_name} wallet verification failed: {message}")
            await update.message.reply_text(
                f"❌ {message}\n\n"
                "Please check your wallet address and try again."
            )
    else:
        # IGNORE normal messages - don't reply to avoid spam
        return


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if effective_user exists
    if not update.effective_user:
        return
    
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    user_username = update.effective_user.username or "No Username"
    
    print(f"🔍 User {user_name} (@{user_username}) checking token balance")
    
    users = load_users()
    wallet = users.get(user_id, {}).get('wallet')
    
    if not wallet:
        # Send private message
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **No Wallet Found**\n\nPlease use /start to register your wallet first."
            )
            # Confirm in group
            await update.message.reply_text(
                f"❌ **No Wallet Found**\n\n"
                f"Check your private messages for details."
            )
        except Exception as e:
            await update.message.reply_text(
                "❌ **No Wallet Found**\n\n"
                "Please use /start to register your wallet first."
            )
        return
    
    balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
    
    if balance is None:
        # Send private message
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **Error checking balance**\n\nUnable to fetch wallet data. Please try again later."
            )
            # Confirm in group
            await update.message.reply_text(
                f"❌ **Error checking balance**\n\n"
                f"Check your private messages for details."
            )
        except Exception as e:
            await update.message.reply_text(
                "❌ **Error checking balance**\n\n"
                "Unable to fetch wallet data. Please try again later."
            )
        return
    
    # Send private message with balance details
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=f"📊 **Token Balance**\n\n"
                 f"Wallet: {wallet[:8]}...{wallet[-8:]}\n"
                 f"Balance: {balance:,.2f} tokens\n"
                 f"Required: {MIN_TOKEN_AMOUNT:,} tokens\n\n"
                 f"{'✅ Sufficient tokens for VIP access' if balance >= MIN_TOKEN_AMOUNT else '❌ Insufficient tokens for VIP access'}\n\n"
                 "Use /vip to request VIP channel access"
        )
        # Confirm in group
        await update.message.reply_text(
            f"✅ **Balance Check Complete!**\n\n"
            f"Check your private messages for detailed balance information.\n"
            f"{'🎉 VIP Access Available!' if balance >= MIN_TOKEN_AMOUNT else '❌ VIP Access Denied'}"
        )
    except Exception as e:
        await update.message.reply_text(
            f"📊 **Token Balance**\n\n"
            f"Wallet: {wallet[:8]}...{wallet[-8:]}\n"
            f"Balance: {balance:,.2f} tokens\n"
            f"Required: {MIN_TOKEN_AMOUNT:,} tokens\n\n"
            f"{'✅ Sufficient tokens for VIP access' if balance >= MIN_TOKEN_AMOUNT else '❌ Insufficient tokens for VIP access'}\n\n"
            "Use /vip to request VIP channel access"
        )


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle VIP access requests"""
    # Check if effective_user exists
    if not update.effective_user:
        return
    
    await handle_vip_request(update, context)


async def change_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if effective_user exists
    if not update.effective_user:
        return
    
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    
    # Send private message
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text="🔄 **Wallet Update**\n\n"
                 "Please send your new Solana wallet address.\n"
                 "You can copy it from your wallet app or DEXScreener.\n\n"
                 "Example: 7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP"
        )
        # Confirm in group
        await update.message.reply_text(
            f"🔄 **Wallet Update Requested**\n\n"
            f"Check your private messages to update your wallet."
        )
    except Exception as e:
        await update.message.reply_text(
            "🔄 **Wallet Update**\n\n"
            "Please send your new Solana wallet address.\n"
            "You can copy it from your wallet app or DEXScreener.\n\n"
            "Example: 7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP"
        )
    context.user_data['awaiting_wallet'] = True


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "connect_wallet":
        await query.edit_message_text(
            "🔗 **Wallet Connection Guide**\n\n"
            "1. Open your Solana wallet (Phantom, Solflare, etc.)\n"
            "2. Copy your wallet address\n"
            "3. Paste it here\n\n"
            "Or visit: https://solscan.io to find your wallet address\n\n"
            "Send your wallet address now:"
        )
        context.user_data['awaiting_wallet'] = True
    
    elif query.data == "manual_entry":
        await query.edit_message_text(
            "📝 **Manual Wallet Entry**\n\n"
            "Please send your Solana wallet address.\n"
            "It should be 44 characters long.\n\n"
            "Example: 7Gk1v2Qw3e4r5t6y7u8i9o0pLkJhGfDsAqWeRtYuIoP\n\n"
            "Send your wallet address now:"
        )
        context.user_data['awaiting_wallet'] = True


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if effective_user exists
    if not update.effective_user:
        return
    
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    
    # Send private message
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text="🤖 **Solana Token Checker Bot**\n\n"
                 "🔐 **VIP Access System**\n"
                 f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens for VIP channel access.\n\n"
                 "Commands:\n"
                 "📋 /start - Start the bot and add wallet\n"
                 "🔍 /verify - Check your token balance\n"
                 "🔐 /vip - Request VIP channel access\n"
                 "🔄 /change - Update your wallet address\n"
                 "✅ /checkme - Check your balance manually\n"
                 "❓ /help - Show this help message\n\n"
                 "Features:\n"
                 "✅ Manual wallet verification\n"
                 "📊 Token balance monitoring\n"
                 "🚨 Admin notifications for low balance\n"
                 "🔐 VIP channel access management\n\n"
                 f"Minimum tokens required: {MIN_TOKEN_AMOUNT:,}"
        )
        # Confirm in group
        await update.message.reply_text(
            f"❓ **Help Information**\n\n"
            f"Check your private messages for detailed help information."
        )
    except Exception as e:
        await update.message.reply_text(
            "🤖 **Solana Token Checker Bot**\n\n"
            "🔐 **VIP Access System**\n"
            f"Hold minimum {MIN_TOKEN_AMOUNT:,} tokens for VIP channel access.\n\n"
            "Commands:\n"
            "📋 /start - Start the bot and add wallet\n"
            "🔍 /verify - Check your token balance\n"
            "🔐 /vip - Request VIP channel access\n"
            "🔄 /change - Update your wallet address\n"
            "✅ /checkme - Check your balance manually\n"
            "❓ /help - Show this help message\n\n"
            "Features:\n"
            "✅ Manual wallet verification\n"
            "📊 Token balance monitoring\n"
            "🚨 Admin notifications for low balance\n"
            "🔐 VIP channel access management\n\n"
            f"Minimum tokens required: {MIN_TOKEN_AMOUNT:,}"
        )


async def checkme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual balance check command"""
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "Unknown User"
    user_username = update.effective_user.username or "No Username"
    
    print(f"🔍 Manual check requested by {user_name} (@{user_username})")
    
    users = load_users()
    wallet = users.get(user_id, {}).get('wallet')
    
    if not wallet:
        # Send private message for privacy
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **No Wallet Found**\n\nPlease use /start to register your wallet first."
            )
            # Confirm in group that message was sent
            await update.message.reply_text(
                f"🔒 **Privacy Protected**\n\n"
                f"Check your balance details sent to you privately.\n"
                f"If you didn't receive a message, please start the bot first: @{context.bot.username}"
            )
        except Exception as e:
            await update.message.reply_text(
                "❌ **Cannot send private message**\n\n"
                "Please start the bot first to receive private messages:\n"
                f"@{context.bot.username}"
            )
        return
    
    # Send "checking" message in group
    await update.message.reply_text("🔍 Checking your token balance... (sending details privately)")
    
    balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
    
    if balance is None:
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **Error checking balance**\n\nUnable to fetch wallet data. Please try again later."
            )
        except Exception as e:
            await update.message.reply_text("❌ Error checking balance. Please try again later.")
        return
    
    # Check VIP access status
    success, access_message = await check_user_tokens_and_manage_access(
        context.application, int(user_id), user_name, user_username
    )
    
    # Send detailed results privately
    try:
        if success:
            private_message = (
                f"✅ **Balance Check Complete!**\n\n"
                f"Wallet: {wallet[:8]}...{wallet[-8:]}\n"
                f"Balance: {balance:,.2f} tokens\n"
                f"Required: {MIN_TOKEN_AMOUNT:,} tokens\n\n"
                f"🎉 **VIP Access Active!**\n"
                f"🔗 VIP Channel: {VIP_CHANNEL_LINK}\n\n"
                f"Status: {access_message}"
            )
        else:
            private_message = (
                f"❌ **Balance Check Complete!**\n\n"
                f"Wallet: {wallet[:8]}...{wallet[-8:]}\n"
                f"Balance: {balance:,.2f} tokens\n"
                f"Required: {MIN_TOKEN_AMOUNT:,} tokens\n\n"
                f"❌ **VIP Access Denied**\n"
                f"{access_message}\n\n"
                f"Add more tokens and try again."
            )
        
        await context.bot.send_message(
            chat_id=int(user_id),
            text=private_message
        )
        
        # Confirm in group
        await update.message.reply_text(
            f"✅ **Check Complete!**\n\n"
            f"Your balance details have been sent to you privately.\n"
            f"{'🎉 VIP Access Active!' if success else '❌ VIP Access Denied'}"
        )
        
    except Exception as e:
        await update.message.reply_text(
            "❌ **Cannot send private message**\n\n"
            "Please start the bot first to receive private messages:\n"
            f"@{context.bot.username}"
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
                        f"🚨 Daily Balance Alert!\n\n"
                        f"Your wallet: {wallet[:8]}...{wallet[-8:]}\n"
                        f"Current balance: {balance} tokens\n"
                        f"Minimum required: {MIN_TOKEN_AMOUNT} tokens\n"
                        f"Missing: {MIN_TOKEN_AMOUNT - balance} tokens\n\n"
                        f"⚠️ Your VIP access will be revoked if you don't add more tokens."
                    ),
                )
            except Exception as e:
                print(f"Error sending message to {user_id}: {e}")


async def check_vip_channel_members(app):
    """Check all VIP channel members and notify admin about insufficient tokens"""
    print("🔍 Checking VIP channel members...")
    
    try:
        # Get all channel members
        members = await app.bot.get_chat_administrators(VIP_CHANNEL_ID)
        # Note: get_chat_members is not available, so we'll check registered users
        
        users = load_users()
        low_balance_count = 0
        
        for user_id, data in users.items():
            wallet = data.get('wallet')
            if not wallet:
                continue
                
            balance = get_token_balance(wallet, SOLANA_TOKEN_MINT)
            if balance is None:
                continue
                
            if balance < MIN_TOKEN_AMOUNT:
                print(f"❌ User {user_id} has insufficient tokens: {balance}")
                low_balance_count += 1
                
                # Only notify admin, don't remove user automatically
                try:
                    user_name = data.get('name', 'Unknown User')
                    await app.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=f"🚨 **Low Token Alert!**\n\n"
                             f"User: {user_name} (@{data.get('username', 'No Username')})\n"
                             f"Wallet: {wallet[:8]}...{wallet[-8:]}\n"
                             f"Balance: {balance} tokens\n"
                             f"Required: {MIN_TOKEN_AMOUNT} tokens\n"
                             f"Missing: {MIN_TOKEN_AMOUNT - balance} tokens\n\n"
                             f"⚠️ **Action Required:**\n"
                             f"Please manually remove this user from the VIP channel if needed.\n"
                             f"Bot will not automatically remove users."
                    )
                    
                except Exception as e:
                    print(f"Error notifying admin about user {user_id}: {e}")
        
        if low_balance_count > 0:
            print(f"✅ VIP channel check complete. Found {low_balance_count} users with insufficient tokens.")
        else:
            print("✅ VIP channel check complete. All users have sufficient tokens.")
        
    except Exception as e:
        print(f"Error checking VIP channel members: {e}")


# === Scheduler Thread ===

def run_scheduler(app):
    # Check every 60 minutes instead of daily
    schedule.every(60).minutes.do(daily_check_job, app)
    # Check VIP channel members every 2 hours
    schedule.every(2).hours.do(check_vip_channel_members, app)
    while True:
        schedule.run_pending()
        time.sleep(60)


# === Main Function ===

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("vip", vip_command))
    app.add_handler(CommandHandler("change", change_wallet))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("checkme", checkme_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_handler(ChatMemberHandler(handle_new_chat_members))
    app.add_handler(ChatMemberHandler(handle_chat_member_update))

    print("🤖 Solana Token Checker Bot (Channel Mode) is running...")
    print(f"Minimum tokens required: {MIN_TOKEN_AMOUNT:,}")
    print(f"VIP Channel: {VIP_CHANNEL_LINK}")
    
    # Start scheduler in background
    import threading
    scheduler_thread = threading.Thread(target=run_scheduler, args=(app,), daemon=True)
    scheduler_thread.start()
    print("📅 Scheduler started successfully!")
    
    app.run_polling()


if __name__ == "__main__":
    main() 