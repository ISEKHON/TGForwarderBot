# Telegram Auto-Forwarder Bot

🤖 **Fully automatic Telegram bot for continuous video backup and queued bulk forwarding between channels**

## 🎯 Features

### ✅ Feature 1: Automatic Backup (Main → Backup)
- Continuously monitors the Main Channel for new videos
- **Also accepts videos sent directly in private chat**
- Instantly forwards each video to the Backup Channel
- Uses Telegram's native forwarding (no re-upload)
- Indexes all messages in SQLite database
- Tracks message IDs, file IDs, and timestamps

### ✅ Feature 2: Automatic Queued Forwarding (Backup → Target)
- **Fully automatic batch processing** - no manual commands needed
- Automatically creates batches when queue reaches configured size
- Forwards messages in original order with configurable delays
- Processes batches continuously in background
- Crash-safe: resumes incomplete batches after restart
- Handles FloodWait and network errors gracefully

## 📋 Requirements

- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Telegram API credentials (from [my.telegram.org](https://my.telegram.org))
- Bot must be **admin** in all three channels
- Bot privacy mode must be **OFF**

## 🚀 Quick Start

### 1. Clone or Download

```bash
cd c:\Users\Jagdeep\Documents\VSCode\TGForwarder
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note:** `tgcrypto` is optional but provides speed optimization. If you get build errors on Windows, it's already commented out in `requirements.txt`. Pyrogram works fine without it.

### 3. Configuration

Copy the example environment file:

```bash
copy .env.example .env
```

Edit `.env` and fill in your values:

```env
# Get from @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Get from my.telegram.org
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890

# Channel IDs (use actual numeric IDs with - prefix)
# To get IDs: forward a message from channel to @userinfobot
MAIN_CHANNEL_ID=-1001234567890
BACKUP_CHANNEL_ID=-1001234567891
TARGET_CHANNEL_ID=-1001234567892

# Forwarding settings
BATCH_SIZE=100
FORWARD_DELAY=1.5
```

### 4. Setup Channels

1. **Create three channels:**
   - Main Channel (source for videos)
   - Backup Channel (storage + index)
   - Target Channel (distribution)

2. **Add bot as admin to all channels:**
   - Go to each channel
   - Add your bot (search by username)
   - Promote to admin with at least these permissions:
     - Post messages
     - Edit messages
     - Delete messages

3. **Disable bot privacy mode:**
   - Message [@BotFather](https://t.me/botfather)
   - Send `/setprivacy`
   - Select your bot
   - Select `Disable`

### 4. Get Channel IDs (Easy Method)

The bot includes a built-in command to get channel IDs:

1. **Start your bot** (if not running):
   ```bash
   python bot.py
   ```

2. **Open a private chat with your bot** on Telegram

3. **Forward any message** from your channel to the bot

4. **Bot will automatically reply** with the channel ID:
   ```
   ✅ Channel Information:
   
   📌 Title: My Channel
   🆔 Channel ID: `-1001234567890`
   👤 Username: @mychannel
   
   💡 Copy the ID above and use it in your .env file
   ```

5. **Copy the ID** (including the minus sign) to your `.env` file

**Alternative:** You can also use `/getchannelid` command for instructions.

### 5. Run the Bot

```bash
python bot.py
```

The bot will:
- ✓ Validate configuration
- ✓ Create/verify database tables
- ✓ Resume any incomplete batches
- ✓ Start monitoring Main Channel
- ✓ Start background batch processor

## � Bot Commands

Send these commands in private chat with your bot:

| Command | Description |
|---------|-------------|
| `/setup` | Setup private channels - sends test messages to establish connections |
| `/forward` | Forward all pending messages to Target Channel |
| `/forward <count>` | Forward specific number of messages (e.g., `/forward 50`) |
| `/forwardall` | **Re-sync ALL messages** from Backup to Target (including already forwarded) |
| `/backupall` | **Backup all existing messages** from Main Channel history |
| `/backupall <limit>` | Backup specific number of messages (e.g., `/backupall 100`) |
| `/backupforce` | **Force backup** - backup all messages even if already in database |
| `/backupforce <limit>` | Force backup specific number (e.g., `/backupforce 50`) |
| `/auto` | **Start automatic forwarding** - bot will continuously forward all messages |
| `/autostop` | Stop automatic forwarding mode |
| `/stats` | Show queue statistics and pending message count |
| `/check` | **Check database status** - diagnose forwarding issues |
| `/fixstuck` | **Reset stuck messages** - fix messages stuck in processing |
| `/clear` | Clear all pending messages from queue (Backup Channel remains intact) |
| `/reset confirm` | **⚠️ RESET ENTIRE BOT** - deletes all database records and clears state |
| `/getchannelid` | Get instructions for finding channel IDs |

**Example Usage:**
```
/stats              → Shows: 150 pending, 300 completed, Auto: ❌ Disabled
/backupall          → Scans Main Channel, backs up all historical messages
/backupall 50       → Backs up last 50 messages from Main Channel
/backupforce 100    → Force backup last 100 messages (creates duplicates)
/auto               → Starts automatic forwarding
/stats              → Shows: Auto: ✅ Enabled (messages forward automatically)
/autostop           → Stops automatic mode
/forward            → Manually forwards all pending messages
/forward 50         → Forwards only 50 messages
/check              → Shows: 24 total, 22 done, 2 stuck in processing
/fixstuck           → Resets 2 stuck messages back to pending
/forward            → Forwards the 2 previously stuck messages
/forwardall         → Re-syncs ALL 450 messages to Target (even already forwarded)
/clear              → Clears the 150 pending queue
/reset              → Shows confirmation warning
/reset confirm      → Deletes all 450 messages from database
```

**Automatic vs Manual Mode:**
- **Manual Mode** (default): Use `/forward` to manually trigger forwarding
- **Automatic Mode**: Use `/auto` to enable continuous automatic forwarding
  - Bot checks every 5 seconds for new messages
  - Forwards all pending messages automatically
  - Use `/autostop` to disable

**Important - /backupall Command:**
- Scans through **entire Main Channel history**
- Backs up all media messages (videos, photos, documents, etc.)
- **Skips messages already in database** (smart backup)
- Does NOT backup text-only messages
- Useful for initial setup or catching up after bot was offline
- Can specify limit to backup only recent messages
- ⚠️ **Bot Limitation:** Telegram bots cannot fetch arbitrary chat history
  - This command may not work due to Telegram API restrictions
  - Bot can only see messages posted AFTER it joined the channel
  - **Recommended:** Keep bot running to automatically backup new messages
  - **Alternative:** Forward old messages to bot in private chat for backup

**Important - /backupforce Command:**
- Similar to `/backupall` but **ignores existing database entries**
- Backs up ALL messages from Main Channel regardless of database status
- **Creates duplicate entries** in database and Backup Channel
- Subject to same bot limitations as `/backupall`
- Useful for:
  - Re-syncing after data corruption
  - Creating backup copies of important content
  - Testing or debugging purposes
- ⚠️ Warning: Will create duplicates in Backup Channel

**Important - /forwardall Command:**
- Forwards **ALL** messages from Backup to Target, regardless of status
- Useful for re-syncing or recovering Target Channel
- Creates duplicates if messages already exist in Target
- Preserves media groups/albums during forwarding

**⚠️ DANGER - /reset Command:**
- **PERMANENTLY DELETES** all database records
- Clears all message history and batch information
- Resets in-memory state (media group tracking, etc.)
- Stops automatic forwarding if running
- **CANNOT BE UNDONE** - requires `/reset confirm` to execute
- Messages in Backup and Target channels remain intact (only database is cleared)

## 🔧 Troubleshooting

### Not all messages forwarded?

If you have 24 videos in Backup but only 22 forwarded:

1. **Check database status:**
   ```
   /check
   ```
   This shows detailed breakdown of message states

2. **Look for stuck messages:**
   - Messages may be stuck in "processing" state
   - This happens if forwarding was interrupted
   - Check the `/check` output for "Stuck Processing"

3. **Fix stuck messages:**
   ```
   /fixstuck
   ```
   Resets stuck messages back to "pending"

4. **Try forwarding again:**
   ```
   /forward
   ```
   Forward the previously stuck messages

5. **Alternative - Force re-sync:**
   ```
   /forwardall
   ```
   Forwards ALL messages from Backup to Target (creates duplicates)

### Common Issues:

**Missing 2 videos?**
- Likely stuck in "processing" state
- Use `/check` to verify, then `/fixstuck` to resolve

**Media groups separated?**
- Should be fixed in current version
- Albums/groups are preserved during forwarding

**Duplicate messages?**
- Using `/forwardall` will create duplicates
- This is expected behavior for re-syncing

## �📊 How It Works

### Architecture

```
Main Channel          Backup Channel         Target Channel
(Manual Upload)       (Auto Index)           (Auto Distribution)
     │                      │                       │
     │  [New Video]         │                       │
     ├──────────────────────▶                       │
     │   Forward + Index    │                       │
     │                      │                       │
     │                  [Queue: 99]                 │
     │                      │                       │
     │  [New Video]         │                       │
     ├──────────────────────▶                       │
     │   Forward + Index [Queue: 100] ✓ BATCH READY│
     │                      │                       │
     │                      │  [Batch 1: 100 msgs] │
     │                      ├──────────────────────▶│
     │                      │   Auto Forward       │
     │                      │   (1.5s delay)       │
     │                      │                       │
```

### Workflow

**1. Automatic Backup:**
```python
Main Channel (new video)
    ↓ (instant forward)
Backup Channel
    ↓ (store in database)
Status: pending, batch_id: NULL
```

**2. Queue Management:**
```python
# Messages accumulate in queue
pending_count = 97  # Keep accepting
pending_count = 98  # Keep accepting  
pending_count = 99  # Keep accepting
pending_count = 100 # ✓ CREATE BATCH!
```

**3. Automatic Batch Processing:**
```python
# Background processor runs continuously
while True:
    if active_batch exists:
        forward_messages(batch)
        mark_as_done()
    
    if pending_count >= BATCH_SIZE:
        create_new_batch()
    
    sleep(5)
```

### Database Schema

**messages table:**
```sql
- id (PRIMARY KEY)
- main_msg_id (from Main Channel)
- backup_msg_id (from Backup Channel)  
- file_id (Telegram file identifier)
- status (pending → processing → done)
- batch_id (which batch it belongs to)
- created_at (timestamp)
- forwarded_at (timestamp)
```

**batches table:**
```sql
- id (PRIMARY KEY)
- status (pending → processing → completed)
- message_count (messages in batch)
- created_at (timestamp)
- started_at (timestamp)
- completed_at (timestamp)
```

## ⚙️ Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `BATCH_SIZE` | 100 | Number of messages per batch |
| `FORWARD_DELAY` | 1.5 | Seconds between each forward |
| `DB_NAME` | forwarder.db | SQLite database filename |

### Adjusting Batch Size

- **Smaller (50-75)**: Faster processing, more frequent batches
- **Larger (150-200)**: Less overhead, longer queuing time
- **Recommended**: 100 (good balance)

### Adjusting Forward Delay

- **Faster (1.0s)**: Risk of FloodWait errors
- **Slower (2.0s)**: Safer, but slower overall
- **Recommended**: 1.5s (tested and stable)

## 🛡️ Reliability Features

### ✅ Crash Recovery
If bot stops/crashes:
- Database preserves all state
- On restart: automatically resumes incomplete batch
- No messages lost or duplicated

### ✅ FloodWait Handling
```python
try:
    forward_message()
except FloodWait as e:
    sleep(e.value)  # Wait as Telegram requires
    retry()         # Continue automatically
```

### ✅ Network Error Handling
- Catches all exceptions
- Logs errors with full traceback
- Continues processing other messages
- Automatic retry logic

### ✅ Duplicate Prevention
- `backup_msg_id` is UNIQUE in database
- Prevents same message being added twice
- Safe to restart bot anytime

## 📝 Logs

The bot creates two log outputs:

1. **Console**: Real-time status
2. **bot.log**: Persistent file log

### Log Example:
```
2025-12-31 10:30:15 - INFO - Bot initialized
2025-12-31 10:30:16 - INFO - Database connected: forwarder.db
2025-12-31 10:30:16 - INFO - ✓ Configuration validated
2025-12-31 10:30:17 - INFO - Bot started successfully
2025-12-31 10:30:17 - INFO - Batch processor started
2025-12-31 10:31:22 - INFO - New video in Main Channel: msg_id=123
2025-12-31 10:31:23 - INFO - ✓ Backed up: main=123 → backup=456
2025-12-31 10:31:23 - INFO - Queue status: 100 pending messages
2025-12-31 10:31:23 - INFO - Creating new batch (threshold reached: 100)
2025-12-31 10:31:23 - INFO - ✓ Batch 1 created with 100 messages
2025-12-31 10:31:24 - INFO - Processing batch 1
2025-12-31 10:31:24 - INFO - Forwarding 100 messages from batch 1
2025-12-31 10:31:25 - INFO - ✓ Forwarded: backup_msg=456 → target
```

## 🔍 Monitoring

### Check Queue Status
The bot logs queue size after each backup:
```
Queue status: 87 pending messages
```

### Check Batch Progress
During forwarding:
```
Processing batch 3
Forwarding 100 messages from batch 3
✓ Forwarded: backup_msg=1523 → target
```

### Database Statistics
On startup, the bot shows:
```python
Database stats: {
    'total_messages': 523,
    'by_status': {'pending': 23, 'processing': 0, 'done': 500},
    'total_batches': 5,
    'batches_by_status': {'completed': 4, 'processing': 1}
}
```

## 🐛 Troubleshooting

### Bot doesn't receive messages
- ✓ Bot privacy mode is OFF in [@BotFather](https://t.me/botfather)
- ✓ Bot is admin in Main Channel
- ✓ Correct channel ID in `.env` (negative number with -100 prefix)

### FloodWait errors
- ✓ Increase `FORWARD_DELAY` in `.env`
- ✓ Bot automatically handles this, just wait

### Messages not forwarding to Target
- ✓ Bot is admin in Target Channel
- ✓ Check `bot.log` for errors
- ✓ Verify `TARGET_CHANNEL_ID` is correct

### "Configuration validation failed"
- ✓ Copy `.env.example` to `.env`
- ✓ Fill in all required values
- ✓ Channel IDs must be negative numbers

## 📂 Project Structure

```
TGForwarder/
├── bot.py              # Main bot logic
├── database.py         # SQLite operations
├── config.py           # Configuration loader
├── requirements.txt    # Python dependencies
├── .env.example        # Configuration template
├── .env                # Your config (create this)
├── .gitignore          # Git ignore rules
├── README.md           # This file
├── bot.log             # Runtime logs (created)
└── forwarder.db        # SQLite database (created)
```

## 🎮 Usage Examples

### Basic Workflow

**Option 1: Upload to Main Channel**
1. Upload video to Main Channel
2. Bot automatically forwards to Backup Channel
3. Stores in database (status: pending)
4. Adds to queue

**Option 2: Send to Bot Directly**
1. Open private chat with your bot
2. Send video file directly to the bot
3. Bot confirms and forwards to Backup Channel
4. Shows current queue status
5. Adds to queue

**Automatic Processing:**
3. When queue reaches 100:
   - Bot creates batch automatically
   - Starts forwarding to Target Channel
   - 1.5s delay between each
   
4. After batch completes:
   - Bot checks for next batch
   - Process continues indefinitely

### Stopping the Bot

Press `Ctrl+C` in terminal:
```
^C
Shutting down...
Database connection closed
```

All progress is saved. Resume anytime by running `python bot.py`

## 🔐 Security Notes

- Never commit `.env` to version control
- Keep `BOT_TOKEN` and `API_HASH` secret
- Use `.gitignore` (already configured)
- Bot only works in specified channels

## 📞 Support

For issues:
1. Check `bot.log` for errors
2. Verify all configuration values
3. Ensure bot has admin rights
4. Test with small `BATCH_SIZE` first

## 📜 License

This project is provided as-is for automation purposes.

---

**Built with ❤️ using Pyrogram**
