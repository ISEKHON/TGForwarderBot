"""
Telegram Auto-Forwarder Bot
Automatic video backup and queued bulk forwarding system

FEATURES:
1. Automatic backup: Main Channel → Backup Channel
2. Automatic queued forwarding: Backup Channel → Target Channel (batched)
"""
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from config import Config
from database import Database

# Configure logging with UTF-8 encoding for Windows
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class TelegramForwarder:
    """Main bot class handling all forwarding operations"""
    
    def __init__(self):
        """Initialize bot, database, and background tasks"""
        self.app = Client(
            "forwarder_bot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN
        )
        
        self.db = Database(Config.DB_NAME)
        self.batch_processor_task = None
        self.auto_forward_enabled = False  # Track automatic forwarding state
        
        # Track media groups being processed to avoid duplicates
        self.processing_media_groups = {}
        self.processed_media_groups = set()  # Track completed groups to prevent re-processing
        
        # Register handlers
        self.register_handlers()
        
        logger.info("Bot initialized")
    
    def register_handlers(self):
        """Register message handlers"""
        
        # Handler for /setup command - IMPORTANT for private channels
        @self.app.on_message(filters.command("setup") & filters.private)
        async def setup_command(client: Client, message: Message):
            """
            Setup command to establish connection with private channels
            """
            await self.setup_channels(message)
        
        # Handler for /forward command - MANUAL forwarding trigger
        @self.app.on_message(filters.command("forward") & filters.private)
        async def forward_command(client: Client, message: Message):
            """
            Manually start forwarding pending messages to Target Channel
            Usage: /forward or /forward 50 (to forward specific number)
            """
            await self.manual_forward(message)
        
        # Handler for /forwardall command - Forward ALL messages
        @self.app.on_message(filters.command("forwardall") & filters.private)
        async def forwardall_command(client: Client, message: Message):
            """
            Forward ALL messages from Backup to Target (including already forwarded)
            Usage: /forwardall
            """
            await self.forward_all_messages(message)
        
        # Handler for /stats command
        @self.app.on_message(filters.command("stats") & filters.private)
        async def stats_command(client: Client, message: Message):
            """
            Show current queue and batch statistics
            """
            await self.show_stats(message)
        
        # Handler for /clear command - Clear pending messages
        @self.app.on_message(filters.command("clear") & filters.private)
        async def clear_command(client: Client, message: Message):
            """
            Clear all pending messages from queue
            Usage: /clear
            """
            await self.clear_queue(message)
        
        # Handler for /reset command - Reset entire bot
        @self.app.on_message(filters.command("reset") & filters.private)
        async def reset_command(client: Client, message: Message):
            """
            Reset the entire bot - clears all data
            Usage: /reset confirm
            """
            await self.reset_bot(message)
        
        # Handler for /backupall command - Backup all channel history
        @self.app.on_message(filters.command("backupall") & filters.private)
        async def backupall_command(client: Client, message: Message):
            """
            Backup all existing messages from Main Channel to Backup Channel
            Usage: /backupall or /backupall <limit>
            """
            await self.backup_all_channel_history(message, force=False)
        
        # Handler for /backupforce command - Force backup (ignore existing)
        @self.app.on_message(filters.command("backupforce") & filters.private)
        async def backupforce_command(client: Client, message: Message):
            """
            Force backup all messages from Main Channel (even if already backed up)
            Usage: /backupforce or /backupforce <limit>
            """
            await self.backup_all_channel_history(message, force=True)
        
        # Handler for /check command - Check database status
        @self.app.on_message(filters.command("check") & filters.private)
        async def check_command(client: Client, message: Message):
            """
            Check database status and identify any issues
            Usage: /check
            """
            await self.check_database_status(message)
        
        # Handler for /fixstuck command - Reset stuck processing messages
        @self.app.on_message(filters.command("fixstuck") & filters.private)
        async def fixstuck_command(client: Client, message: Message):
            """
            Reset stuck processing messages back to pending
            Usage: /fixstuck
            """
            await self.fix_stuck_messages(message)
        
        # Handler for /auto command - Start automatic forwarding
        @self.app.on_message(filters.command("auto") & filters.private)
        async def auto_command(client: Client, message: Message):
            """
            Start automatic forwarding from Backup to Target
            Usage: /auto
            """
            await self.start_auto_forward(message)
        
        # Handler for /autostop command - Stop automatic forwarding
        @self.app.on_message(filters.command("autostop") & filters.private)
        async def autostop_command(client: Client, message: Message):
            """
            Stop automatic forwarding
            Usage: /autostop
            """
            await self.stop_auto_forward(message)
        
        # Handler for /getchannelid command
        @self.app.on_message(filters.command("getchannelid") & filters.private)
        async def get_channel_id_command(client: Client, message: Message):
            """
            Command to help users get channel IDs
            Usage: Forward a message from the channel to the bot, then use /getchannelid
            """
            await self.get_channel_id(message)
        
        # Handler for forwarded messages to get channel ID
        @self.app.on_message(filters.forwarded & filters.private)
        async def handle_forwarded_message(client: Client, message: Message):
            """
            Automatically detect channel ID from forwarded messages
            """
            await self.get_channel_id_from_forward(message)
        
        # Handler for Main Channel - automatic backup (all media except text)
        @self.app.on_message(filters.chat(Config.MAIN_CHANNEL_ID) & (filters.photo | filters.video | filters.document | filters.audio | filters.voice | filters.video_note | filters.animation | filters.sticker))
        async def handle_main_channel(client: Client, message: Message):
            """
            FEATURE 1: Automatic Backup (Main Channel)
            Forwards all media from Main Channel to Backup Channel (excludes text-only messages)
            """
            await self.backup_media(message)
        
        # Handler for private chat media - also backup (all media except text)
        @self.app.on_message(filters.private & (filters.photo | filters.video | filters.document | filters.audio | filters.voice | filters.video_note | filters.animation | filters.sticker) & ~filters.forwarded)
        async def handle_private_media(client: Client, message: Message):
            """
            FEATURE 1B: Automatic Backup (Private Chat)
            Accepts all media sent directly to bot in private chat
            Forwards to Backup Channel and adds to queue (excludes text-only messages)
            """
            # Skip if message is a command (commands are handled separately)
            if message.text and message.text.startswith('/'):
                return
            await self.backup_media_from_private(message)
    
    async def setup_channels(self, message: Message):
        """
        Setup command to establish connection with all configured channels.
        This is REQUIRED for private channels to work with bot tokens.
        """
        # First, provide instructions
        instruction_msg = await message.reply_text(
            "🔧 **Setting up channels...**\n\n"
            "⚠️ **IMPORTANT:** For private channels, you must first:\n"
            "1. Make sure bot is ADMIN in all 3 channels\n"
            "2. Post ANY message (text, emoji, anything) in each channel\n"
            "3. The bot will see it and cache the channel\n\n"
            "If you haven't done this yet:\n"
            "❌ Cancel now and post messages first\n"
            "✅ If you already posted, wait 5 seconds...\n\n"
            "Starting setup in 5 seconds..."
        )
        
        await asyncio.sleep(5)
        
        status_msg = await instruction_msg.edit_text("🔧 Setting up channels...\n\nPlease wait...")
        
        results = []
        channels = {
            "Main Channel": Config.MAIN_CHANNEL_ID,
            "Backup Channel": Config.BACKUP_CHANNEL_ID,
            "Target Channel": Config.TARGET_CHANNEL_ID
        }
        
        for name, channel_id in channels.items():
            try:
                # Send a test message to establish peer connection
                test_msg = await self.app.send_message(
                    chat_id=channel_id,
                    text=f"✅ Bot setup complete for {name}"
                )
                
                # Get channel info
                chat = test_msg.chat
                channel_title = chat.title or "Unknown"
                
                # Delete test message
                await asyncio.sleep(1)
                await test_msg.delete()
                
                results.append(f"✅ {name}: {channel_title}")
                logger.info(f"[SETUP] {name} connected: {channel_title} (ID: {channel_id})")
                
            except Exception as e:
                results.append(f"❌ {name}: Failed - {str(e)[:50]}")
                logger.error(f"[SETUP] Failed to connect to {name} (ID: {channel_id}): {e}")
        
        # Send results
        result_text = "🔧 **Channel Setup Results:**\n\n" + "\n".join(results)
        result_text += "\n\n"
        
        if all("✅" in r for r in results):
            result_text += "🎉 **All channels connected successfully!**\n"
            result_text += "Bot is now ready to forward messages."
        else:
            result_text += "⚠️ **Some channels failed to connect.**\n\n"
            result_text += "**FIX: Do this for each failed channel:**\n"
            result_text += "1. Go to the channel\n"
            result_text += "2. Post ANY message (like: test)\n"
            result_text += "3. Wait 5 seconds\n"
            result_text += "4. Run /setup again\n\n"
            result_text += "**Also verify:**\n"
            result_text += "1. Bot is added to each channel\n"
            result_text += "2. Bot is ADMIN in each channel\n"
            result_text += "3. Channel IDs in .env are correct"
        
        await status_msg.edit_text(result_text)
    
    async def get_channel_id(self, message: Message):
        """
        Send instructions on how to get channel ID
        """
        instructions = (
            "📋 **How to Get Channel ID:**\n\n"
            "1️⃣ Go to the channel you want to get the ID for\n"
            "2️⃣ Forward ANY message from that channel to me\n"
            "3️⃣ I'll automatically reply with the channel ID!\n\n"
            "**Note:** You must be able to forward messages from the channel."
        )
        await message.reply_text(instructions)
    
    async def get_channel_id_from_forward(self, message: Message):
        """
        Extract and display channel ID from a forwarded message
        """
        try:
            if message.forward_from_chat:
                chat = message.forward_from_chat
                chat_id = chat.id
                chat_title = chat.title or "Unknown"
                chat_username = f"@{chat.username}" if chat.username else "No username"
                
                response = (
                    f"✅ **Channel Information:**\n\n"
                    f"📌 **Title:** {chat_title}\n"
                    f"🆔 **Channel ID:** `{chat_id}`\n"
                    f"👤 **Username:** {chat_username}\n\n"
                    f"💡 **Copy the ID above and use it in your .env file**\n"
                    f"(Include the minus sign if present)"
                )
                
                await message.reply_text(response)
                logger.info(f"Provided channel ID: {chat_id} ({chat_title})")
            else:
                await message.reply_text(
                    "❌ This message is not forwarded from a channel.\n"
                    "Please forward a message from the channel you want to get the ID for."
                )
        except Exception as e:
            logger.error(f"Error getting channel ID: {e}")
            await message.reply_text("❌ Error getting channel ID. Please try again.")
    
    async def manual_forward(self, message: Message):
        """
        Manually trigger forwarding of pending messages to Target Channel
        Usage: /forward or /forward 50
        """
        try:
            # Parse count argument if provided
            args = message.text.split()
            count = int(args[1]) if len(args) > 1 else Config.BATCH_SIZE
            
            pending_count = self.db.get_pending_count()
            
            if pending_count == 0:
                await message.reply_text("❌ No pending messages to forward.")
                return
            
            # Limit to available messages
            count = min(count, pending_count)
            
            status_msg = await message.reply_text(
                f"⏳ **Starting manual forward...**\n\n"
                f"📦 Forwarding {count} messages to Target Channel\n"
                f"⏱️ Estimated time: {int(count * Config.FORWARD_DELAY / 60)} min {int(count * Config.FORWARD_DELAY % 60)} sec"
            )
            
            # Get pending messages
            messages = self.db.get_pending_messages(count)
            message_ids = [msg['id'] for msg in messages]
            
            # Create batch
            batch_id = self.db.create_batch(message_ids)
            logger.info(f"[MANUAL] Created batch {batch_id} with {len(message_ids)} messages")
            
            # Forward messages
            await self.process_batch_messages(batch_id, messages)
            
            # Complete batch
            self.db.complete_batch(batch_id)
            
            # Check how many were actually marked as done
            done_count = self.db.cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE batch_id = ? AND status = 'done'",
                (batch_id,)
            ).fetchone()[0]
            
            still_processing = self.db.cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE batch_id = ? AND status = 'processing'",
                (batch_id,)
            ).fetchone()[0]
            
            # Update status
            status_text = f"✅ **Forward complete!**\n\n"
            status_text += f"📦 Attempted: {count} messages\n"
            status_text += f"✅ Success: {done_count} messages\n"
            
            if still_processing > 0:
                status_text += f"⚠️ Failed: {still_processing} messages\n"
                status_text += f"\nUse /check to see details\n"
                status_text += f"Use /forwardall to retry all\n"
            
            status_text += f"📈 Batch ID: {batch_id}\n"
            status_text += f"📊 Remaining: {self.db.get_pending_count()} pending"
            
            await status_msg.edit_text(status_text)
            
        except ValueError:
            await message.reply_text("❌ Invalid count. Use: /forward or /forward 50")
        except Exception as e:
            logger.error(f"Error in manual forward: {e}", exc_info=True)
            await message.reply_text(f"❌ Error: {str(e)}")
    
    async def forward_all_messages(self, message: Message):
        """
        Forward ALL messages from Backup to Target Channel
        This re-syncs everything, ignoring current status
        """
        try:
            # Get total message count
            total_count = self.db.get_statistics()['total_messages']
            
            if total_count == 0:
                await message.reply_text("❌ No messages in Backup Channel to forward.")
                return
            
            # Confirm action
            confirm_msg = await message.reply_text(
                f"⚠️ **Forward ALL Messages**\n\n"
                f"This will forward **{total_count}** messages from Backup to Target.\n"
                f"This includes already forwarded messages.\n\n"
                f"⏱️ Estimated time: {int(total_count * Config.FORWARD_DELAY / 60)} min\n\n"
                f"⏳ Starting in 3 seconds...\n"
                f"Send /cancel to abort (not implemented yet, just wait)"
            )
            
            await asyncio.sleep(3)
            
            await confirm_msg.edit_text(
                f"⏳ **Forwarding ALL messages...**\n\n"
                f"📦 Total: {total_count} messages\n"
                f"🔄 Please wait..."
            )
            
            # Get all messages
            all_messages = self.db.get_all_messages()
            
            # Group messages by media_group_id for proper album forwarding
            media_groups = {}
            individual_messages = []
            
            for msg_record in all_messages:
                try:
                    media_group_id = msg_record['media_group_id']
                except (KeyError, IndexError):
                    media_group_id = None
                
                if media_group_id:
                    if media_group_id not in media_groups:
                        media_groups[media_group_id] = []
                    media_groups[media_group_id].append(msg_record)
                else:
                    individual_messages.append(msg_record)
            
            # Forward media groups first
            success = 0
            failed = 0
            
            for group_id, group_messages in media_groups.items():
                try:
                    backup_msg_ids = [msg['backup_msg_id'] for msg in group_messages]
                    
                    # Copy media group to Target Channel
                    await self.app.copy_media_group(
                        chat_id=Config.TARGET_CHANNEL_ID,
                        from_chat_id=Config.BACKUP_CHANNEL_ID,
                        message_id=backup_msg_ids[0]
                    )
                    
                    success += len(group_messages)
                    
                    # Update status
                    if success % 10 == 0:
                        await confirm_msg.edit_text(
                            f"⏳ **Forwarding...**\n\n"
                            f"✅ Success: {success}\n"
                            f"❌ Failed: {failed}\n"
                            f"📊 Progress: {int((success + failed)/total_count*100)}%"
                        )
                    
                    await asyncio.sleep(Config.FORWARD_DELAY)
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait: sleeping {e.value}s")
                    await asyncio.sleep(e.value)
                    continue
                    
                except Exception as e:
                    logger.error(f"Error forwarding media group {group_id}: {e}")
                    failed += len(group_messages)
                    await asyncio.sleep(2)
            
            # Forward individual messages
            for msg_record in individual_messages:
                try:
                    backup_msg_id = msg_record['backup_msg_id']
                    
                    # Copy from Backup Channel to Target Channel
                    await self.app.copy_message(
                        chat_id=Config.TARGET_CHANNEL_ID,
                        from_chat_id=Config.BACKUP_CHANNEL_ID,
                        message_id=backup_msg_id
                    )
                    
                    success += 1
                    
                    # Update status every 10 messages
                    if success % 10 == 0:
                        await confirm_msg.edit_text(
                            f"⏳ **Forwarding...**\n\n"
                            f"✅ Success: {success}\n"
                            f"❌ Failed: {failed}\n"
                            f"📊 Progress: {int((success + failed)/total_count*100)}%"
                        )
                    
                    # Apply delay
                    await asyncio.sleep(Config.FORWARD_DELAY)
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait: sleeping {e.value}s")
                    await asyncio.sleep(e.value)
                    continue
                    
                except Exception as e:
                    logger.error(f"Error forwarding backup_msg={backup_msg_id}: {e}")
                    failed += 1
                    await asyncio.sleep(2)
            
            # Final status
            await confirm_msg.edit_text(
                f"✅ **Forward ALL Complete!**\n\n"
                f"📦 Total in DB: {total_count}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Success Rate: {int(success/(success+failed)*100) if (success+failed) > 0 else 0}%\n\n"
                f"{'⚠️ Some messages failed. Check logs or use /check' if failed > 0 else 'All messages re-synced successfully!'}"
            )
            
            logger.info(f"[FORWARDALL] Completed: {success} success, {failed} failed out of {total_count} total")
            
        except Exception as e:
            logger.error(f"Error in forward all: {e}", exc_info=True)
            await message.reply_text(f"❌ Error: {str(e)}")
    
    async def show_stats(self, message: Message):
        """
        Show current statistics and queue status
        """
        try:
            stats = self.db.get_statistics()
            pending = self.db.get_pending_count()
            active_batch = self.db.get_active_batch()
            
            status_text = "📊 **Bot Statistics**\n\n"
            status_text += f"📦 **Queue Status:**\n"
            status_text += f"   Pending: {pending} messages\n"
            status_text += f"   Processing: {stats['by_status'].get('processing', 0)} messages\n"
            status_text += f"   Completed: {stats['by_status'].get('done', 0)} messages\n\n"
            
            status_text += f"📊 **Total Messages:** {stats['total_messages']}\n"
            status_text += f"📦 **Total Batches:** {stats['total_batches']}\n\n"
            
            if active_batch:
                status_text += f"⏳ **Active Batch:** {active_batch['id']}\n"
            
            status_text += f"\n🔧 **Commands:**\n"
            status_text += f"/forward - Forward all pending ({pending} messages)\n"
            status_text += f"/forward 50 - Forward specific number\n"
            status_text += f"/forwardall - Forward ALL messages (re-sync)\n"
            status_text += f"/backupall - Backup all Main Channel history\n"
            status_text += f"/backupforce - Force backup (ignore existing)\n"
            status_text += f"/check - Check database status\n"
            status_text += f"/fixstuck - Reset stuck messages\n"
            status_text += f"/auto - Start automatic forwarding\n"
            status_text += f"/autostop - Stop automatic forwarding\n"
            status_text += f"/stats - Show this status\n"
            status_text += f"/clear - Clear pending queue\n"
            status_text += f"/reset confirm - Reset entire bot (delete all data)\n"
            status_text += f"\n🤖 **Auto Mode:** {'✅ Enabled' if self.auto_forward_enabled else '❌ Disabled'}\n"
            
            await message.reply_text(status_text)
            
        except Exception as e:
            logger.error(f"Error showing stats: {e}")
            await message.reply_text("❌ Error getting statistics")
    
    async def clear_queue(self, message: Message):
        """
        Clear all pending messages from queue
        """
        try:
            # Get count before clearing
            pending_count = self.db.get_pending_count()
            
            if pending_count == 0:
                await message.reply_text("ℹ️ Queue is already empty!")
                return
            
            # Clear all pending messages
            cleared = self.db.clear_pending_messages()
            
            await message.reply_text(
                f"✅ **Queue Cleared!**\n\n"
                f"🗑️ Removed: {cleared} pending messages\n\n"
                f"Messages in Backup Channel remain intact.\n"
                f"Only the forward queue was cleared."
            )
            
            logger.info(f"Queue cleared: {cleared} pending messages removed")
            
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            await message.reply_text("❌ Error clearing queue")
    
    async def check_database_status(self, message: Message):
        """
        Check database status and identify any discrepancies
        Helps diagnose why some messages might not be forwarding
        """
        try:
            status_msg = await message.reply_text("🔍 **Checking database status...**\n\nPlease wait...")
            
            # Get database statistics
            stats = self.db.get_statistics()
            
            # Get detailed breakdown
            all_messages = self.db.get_all_messages()
            
            # Analyze by status
            pending_msgs = [m for m in all_messages if m['status'] == 'pending']
            processing_msgs = [m for m in all_messages if m['status'] == 'processing']
            done_msgs = [m for m in all_messages if m['status'] == 'done']
            
            # Check for messages without batch_id
            no_batch = [m for m in all_messages if m['batch_id'] is None]
            
            # Check for stuck processing messages
            stuck_processing = [m for m in processing_msgs if m['batch_id'] is not None]
            
            # Group by media_group_id to find albums
            media_groups = {}
            for msg in all_messages:
                mgid = msg.get('media_group_id') or msg['media_group_id'] if 'media_group_id' in msg else None
                if mgid:
                    if mgid not in media_groups:
                        media_groups[mgid] = []
                    media_groups[mgid].append(msg)
            
            # Build report
            report = f"📊 **Database Status Report**\n\n"
            report += f"**Total Messages:** {stats['total_messages']}\n\n"
            
            report += f"**By Status:**\n"
            report += f"   ⏳ Pending: {len(pending_msgs)}\n"
            report += f"   ⚙️ Processing: {len(processing_msgs)}\n"
            report += f"   ✅ Done: {len(done_msgs)}\n\n"
            
            if stuck_processing:
                report += f"⚠️ **Stuck Processing:** {len(stuck_processing)} messages\n"
                report += f"   (Messages marked as processing but in a batch)\n\n"
            
            report += f"**Media Groups (Albums):**\n"
            report += f"   Total groups: {len(media_groups)}\n"
            if media_groups:
                group_sizes = [len(msgs) for msgs in media_groups.values()]
                report += f"   Largest group: {max(group_sizes)} items\n"
                report += f"   Total in groups: {sum(group_sizes)} messages\n\n"
            else:
                report += f"   No media groups found\n\n"
            
            report += f"**Batches:**\n"
            report += f"   Total: {stats['total_batches']}\n"
            if 'batches_by_status' in stats:
                for status, count in stats['batches_by_status'].items():
                    report += f"   {status}: {count}\n"
            
            # Check for active incomplete batches
            active_batch = self.db.get_active_batch()
            if active_batch:
                incomplete_msgs = self.db.get_incomplete_batch_messages(active_batch['id'])
                report += f"\n⚠️ **Incomplete Batch Found:**\n"
                report += f"   Batch ID: {active_batch['id']}\n"
                report += f"   Incomplete: {len(incomplete_msgs)} messages\n"
                report += f"   Use /forward to complete it\n"
            
            # Recommendations
            report += f"\n💡 **Recommendations:**\n"
            if stuck_processing:
                report += f"• {len(stuck_processing)} messages stuck in processing\n"
                report += f"  Use /forwardall to re-sync\n"
            if pending_msgs:
                report += f"• {len(pending_msgs)} messages ready to forward\n"
                report += f"  Use /forward to send them\n"
            if len(media_groups) > 0:
                report += f"• {len(media_groups)} media groups detected\n"
                report += f"  These are forwarded as albums\n"
            
            await status_msg.edit_text(report)
            
            logger.info(f"[CHECK] Database check completed: {stats['total_messages']} total, {len(pending_msgs)} pending, {len(done_msgs)} done")
            
        except Exception as e:
            logger.error(f"Error checking database: {e}", exc_info=True)
            await message.reply_text(f"❌ Error checking database: {str(e)}")
    
    async def fix_stuck_messages(self, message: Message):
        """
        Reset stuck processing messages back to pending
        This fixes messages that failed to complete during forwarding
        """
        try:
            # Check how many are stuck
            stuck_count = self.db.cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'processing'"
            ).fetchone()[0]
            
            if stuck_count == 0:
                await message.reply_text("✅ No stuck messages found!\n\nAll messages are in proper state.")
                return
            
            # Show confirmation
            confirm_msg = await message.reply_text(
                f"🔧 **Fix Stuck Messages**\n\n"
                f"Found: {stuck_count} messages stuck in 'processing' state\n\n"
                f"These will be reset to 'pending' so you can forward them again.\n\n"
                f"⏳ Processing..."
            )
            
            # Reset stuck messages
            reset_count = self.db.reset_stuck_messages()
            
            await confirm_msg.edit_text(
                f"✅ **Stuck Messages Fixed!**\n\n"
                f"🔄 Reset: {reset_count} messages\n"
                f"📦 Status: Changed from 'processing' to 'pending'\n\n"
                f"Now you can:\n"
                f"• /forward - Forward these messages again\n"
                f"• /stats - Check current queue status"
            )
            
            logger.info(f"[FIXSTUCK] Reset {reset_count} stuck messages")
            
        except Exception as e:
            logger.error(f"Error fixing stuck messages: {e}", exc_info=True)
            await message.reply_text(f"❌ Error: {str(e)}")
    
    async def reset_bot(self, message: Message):
        """
        Reset the entire bot - clear all data and state
        Requires confirmation to prevent accidental resets
        """
        try:
            # Check for confirmation
            args = message.text.split()
            if len(args) < 2 or args[1].lower() != 'confirm':
                stats = self.db.get_statistics()
                await message.reply_text(
                    f"⚠️ **RESET BOT - CONFIRMATION REQUIRED**\n\n"
                    f"This will DELETE ALL DATA:\n"
                    f"📦 Messages: {stats['total_messages']}\n"
                    f"📊 Batches: {stats['total_batches']}\n"
                    f"🗄️ Database will be completely cleared\n"
                    f"🤖 All in-memory state will be reset\n\n"
                    f"⚠️ **THIS CANNOT BE UNDONE!**\n\n"
                    f"To confirm, send:\n"
                    f"`/reset confirm`"
                )
                return
            
            # Get stats before reset
            stats = self.db.get_statistics()
            
            # Stop auto-forwarding if running
            was_auto = self.auto_forward_enabled
            if self.auto_forward_enabled:
                self.auto_forward_enabled = False
                await asyncio.sleep(1)  # Let current operations finish
            
            status_msg = await message.reply_text(
                f"⏳ **Resetting bot...**\n\n"
                f"🗑️ Deleting all data..."
            )
            
            # Reset database
            reset_stats = self.db.reset_database()
            
            # Clear in-memory state
            self.processing_media_groups.clear()
            self.processed_media_groups.clear()
            
            await status_msg.edit_text(
                f"✅ **Bot Reset Complete!**\n\n"
                f"🗑️ **Deleted:**\n"
                f"   Messages: {reset_stats['messages_deleted']}\n"
                f"   Batches: {reset_stats['batches_deleted']}\n\n"
                f"🔄 **Reset:**\n"
                f"   Database cleared\n"
                f"   In-memory cache cleared\n"
                f"   Auto-forward: {'Stopped' if was_auto else 'Already disabled'}\n\n"
                f"✨ Bot is now in fresh state!\n"
                f"Ready to backup and forward new messages."
            )
            
            logger.info(f"[RESET] Bot reset completed: {reset_stats['messages_deleted']} messages, {reset_stats['batches_deleted']} batches deleted")
            
        except Exception as e:
            logger.error(f"Error resetting bot: {e}", exc_info=True)
            await message.reply_text(f"❌ Error during reset: {str(e)}")
    
    async def backup_all_channel_history(self, message: Message, force: bool = False):
        """
        Backup all existing messages from Main Channel to Backup Channel
        This scans through channel history and backs up all media
        
        Args:
            message: The command message
            force: If True, backup even if message already exists in database
            
        Note: Bot tokens have limited access to chat history.
        This command works best when bot has been running and collecting messages.
        """
        try:
            # Parse limit argument if provided
            args = message.text.split()
            limit = int(args[1]) if len(args) > 1 else None
            
            mode_text = "**FORCE MODE**" if force else "Standard Mode"
            
            status_msg = await message.reply_text(
                f"⏳ **Scanning Main Channel...**\n\n"
                f"🔧 Mode: {mode_text}\n"
                f"📡 Attempting to fetch message history...\n"
                f"{'📊 Limit: ' + str(limit) + ' messages' if limit else '📊 No limit (all available)'}\n\n"
                f"⚠️ Note: Bots have limited history access\n"
                f"This may take a while..."
            )
            
            # Scan Main Channel for all media messages
            scanned = 0
            backed_up = 0
            skipped = 0
            errors = 0
            
            try:
                # Try to iterate through channel history
                # Note: This may not work for all bot setups due to Telegram limitations
                async for msg in self.app.get_chat_history(Config.MAIN_CHANNEL_ID, limit=limit):
                    scanned += 1
                    
                    # Check if it's a media message
                    has_media = (msg.video or msg.photo or msg.document or msg.audio or 
                               msg.voice or msg.video_note or msg.animation or msg.sticker)
                    
                    if not has_media:
                        continue
                    
                    try:
                        # Check if already backed up (skip only if not force mode)
                        if not force:
                            existing = self.db.get_message_by_main_id(msg.id)
                            if existing:
                                skipped += 1
                                continue
                        
                        # Copy to Backup Channel
                        backup_msg = await self.app.copy_message(
                            chat_id=Config.BACKUP_CHANNEL_ID,
                            from_chat_id=Config.MAIN_CHANNEL_ID,
                            message_id=msg.id
                        )
                        
                        # Get file_id
                        file_id = None
                        if msg.video:
                            file_id = msg.video.file_id
                        elif msg.photo:
                            file_id = msg.photo.file_id
                        elif msg.document:
                            file_id = msg.document.file_id
                        elif msg.audio:
                            file_id = msg.audio.file_id
                        elif msg.voice:
                            file_id = msg.voice.file_id
                        elif msg.animation:
                            file_id = msg.animation.file_id
                        elif msg.sticker:
                            file_id = msg.sticker.file_id
                        
                        # Store in database (force mode will create duplicate entries)
                        self.db.add_message(
                            main_msg_id=msg.id,
                            backup_msg_id=backup_msg.id,
                            file_id=file_id,
                            media_group_id=msg.media_group_id if hasattr(msg, 'media_group_id') else None
                        )
                        
                        backed_up += 1
                        
                        # Update status every 10 messages
                        if backed_up % 10 == 0:
                            await status_msg.edit_text(
                                f"⏳ **Backing up channel history...**\n\n"
                                f"🔧 Mode: {mode_text}\n"
                                f"🔍 Scanned: {scanned} messages\n"
                                f"✅ Backed up: {backed_up}\n"
                                f"⏭️ Skipped: {skipped} {'(force mode: 0)' if force else '(already backed up)'}\n"
                                f"❌ Errors: {errors}\n\n"
                                f"⏱️ Please wait..."
                            )
                        
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.5)
                        
                    except FloodWait as e:
                        logger.warning(f"FloodWait: sleeping {e.value}s")
                        await asyncio.sleep(e.value)
                        continue
                        
                    except Exception as e:
                        logger.error(f"Error backing up msg {msg.id}: {e}")
                        errors += 1
                
                # Final status
                await status_msg.edit_text(
                    f"✅ **Channel Backup Complete!**\n\n"
                    f"🔧 Mode: {mode_text}\n"
                    f"🔍 Scanned: {scanned} messages\n"
                    f"✅ Backed up: {backed_up} {'(includes duplicates)' if force else 'new messages'}\n"
                    f"⏭️ Skipped: {skipped} {'(force mode skips nothing)' if force else '(already backed up)'}\n"
                    f"❌ Errors: {errors}\n\n"
                    f"📊 Total in database: {self.db.get_statistics()['total_messages']}\n"
                    f"📦 Pending to forward: {self.db.get_pending_count()}\n\n"
                    f"Use /forward or /auto to send to Target Channel"
                )
                
                logger.info(f"[BACKUP{'FORCE' if force else 'ALL'}] Completed: scanned={scanned}, backed_up={backed_up}, skipped={skipped}, errors={errors}")
            
            except Exception as history_error:
                # Handle the specific bot limitation error
                error_msg = str(history_error)
                if "BOT_METHOD_INVALID" in error_msg or "GetHistory" in error_msg:
                    await status_msg.edit_text(
                        f"❌ **Bot Limitation Error**\n\n"
                        f"⚠️ Telegram bots cannot fetch chat history using standard methods.\n\n"
                        f"**Why this happens:**\n"
                        f"• Bot API has limited access to message history\n"
                        f"• Only user accounts can fetch arbitrary messages\n"
                        f"• Bots can only see messages sent after they joined\n\n"
                        f"**Alternative Solutions:**\n"
                        f"1. Keep bot running - it will backup new messages automatically\n"
                        f"2. Forward old messages to the bot in private chat\n"
                        f"3. Use a userbot (requires user account, not recommended)\n\n"
                        f"💡 The bot will automatically backup all NEW messages posted to Main Channel!"
                    )
                    logger.error(f"[BACKUP] Bot limitation: Cannot access chat history - {error_msg}")
                else:
                    await status_msg.edit_text(
                        f"❌ **Error accessing channel history**\n\n"
                        f"Error: {error_msg}\n\n"
                        f"Make sure:\n"
                        f"• Bot is admin in Main Channel\n"
                        f"• Bot has 'Read Messages' permission\n"
                        f"• Channel ID is correct"
                    )
                    logger.error(f"[BACKUP] Error: {error_msg}")
            
        except ValueError:
            await message.reply_text(f"❌ Invalid limit. Use: /backup{'force' if force else 'all'} or /backup{'force' if force else 'all'} 100")
        except Exception as e:
            logger.error(f"Error in backup all: {e}", exc_info=True)
            await message.reply_text(f"❌ Error: {str(e)}")
    
    async def start_auto_forward(self, message: Message):
        """
        Start automatic forwarding from Backup to Target Channel
        """
        try:
            if self.auto_forward_enabled:
                await message.reply_text("ℹ️ Automatic forwarding is already running!")
                return
            
            pending_count = self.db.get_pending_count()
            
            # Enable auto forward
            self.auto_forward_enabled = True
            
            # Start background processor if not running
            if self.batch_processor_task is None or self.batch_processor_task.done():
                self.batch_processor_task = asyncio.create_task(self.auto_forward_processor())
            
            await message.reply_text(
                f"✅ **Automatic Forwarding Started!**\n\n"
                f"📦 Pending: {pending_count} messages\n"
                f"⚡ Bot will automatically forward all messages\n\n"
                f"🛑 Use /autostop to stop automatic mode\n"
                f"📊 Use /stats to check status"
            )
            
            logger.info("[AUTO] Automatic forwarding enabled")
            
        except Exception as e:
            logger.error(f"Error starting auto forward: {e}")
            await message.reply_text("❌ Error starting automatic forwarding")
    
    async def stop_auto_forward(self, message: Message):
        """
        Stop automatic forwarding
        """
        try:
            if not self.auto_forward_enabled:
                await message.reply_text("ℹ️ Automatic forwarding is not running!")
                return
            
            # Disable auto forward
            self.auto_forward_enabled = False
            
            await message.reply_text(
                f"🛑 **Automatic Forwarding Stopped!**\n\n"
                f"✅ Background processor will stop after current batch\n\n"
                f"⚡ Use /auto to restart automatic mode\n"
                f"📊 Use /stats to check queue status"
            )
            
            logger.info("[AUTO] Automatic forwarding disabled")
            
        except Exception as e:
            logger.error(f"Error stopping auto forward: {e}")
            await message.reply_text("❌ Error stopping automatic forwarding")
    
    async def auto_forward_processor(self):
        """
        Background task that automatically processes pending messages
        Runs continuously while auto_forward_enabled is True
        """
        logger.info("[AUTO] Background processor started")
        
        try:
            while self.auto_forward_enabled:
                try:
                    pending_count = self.db.get_pending_count()
                    
                    if pending_count > 0:
                        # Forward all pending messages
                        messages = self.db.get_pending_messages(pending_count)
                        message_ids = [msg['id'] for msg in messages]
                        
                        # Create batch
                        batch_id = self.db.create_batch(message_ids)
                        logger.info(f"[AUTO] Created batch {batch_id} with {len(message_ids)} messages")
                        
                        # Forward messages
                        await self.process_batch_messages(batch_id, messages)
                        
                        # Complete batch
                        self.db.complete_batch(batch_id)
                        logger.info(f"[AUTO] Batch {batch_id} completed - forwarded {len(message_ids)} messages")
                    
                    # Wait before checking again (check every 5 seconds)
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"[AUTO] Error in background processor: {e}", exc_info=True)
                    await asyncio.sleep(10)  # Wait longer on error
                    
        except asyncio.CancelledError:
            logger.info("[AUTO] Background processor cancelled")
        except Exception as e:
            logger.error(f"[AUTO] Fatal error in background processor: {e}", exc_info=True)
        finally:
            logger.info("[AUTO] Background processor stopped")
    
    async def backup_media_from_private(self, message: Message):
        """
        Handle all media sent directly to bot in private chat
        Forward to Backup Channel and index for batch forwarding
        """
        try:
            # Check if this is part of a media group
            media_group_id = message.media_group_id if hasattr(message, 'media_group_id') else None
            
            if media_group_id:
                # Check if this group was already processed
                if media_group_id in self.processed_media_groups:
                    logger.info(f"Media group {media_group_id} already processed, skipping message {message.id}")
                    return
                
                # This is part of a media group/album
                # Wait a bit to collect all messages in the group
                if media_group_id not in self.processing_media_groups:
                    self.processing_media_groups[media_group_id] = {
                        'messages': [],
                        'chat_id': message.chat.id,
                        'status_msg': None,
                        'processing': False  # Flag to prevent concurrent processing
                    }
                    # Send initial status
                    status_msg = await message.reply_text("⏳ Processing your album...")
                    self.processing_media_groups[media_group_id]['status_msg'] = status_msg
                
                # Add message to group
                self.processing_media_groups[media_group_id]['messages'].append(message)
                
                # If another message is already processing this group, skip
                if self.processing_media_groups[media_group_id]['processing']:
                    logger.info(f"Media group {media_group_id} already being processed by another message")
                    return
                
                # Mark as processing
                self.processing_media_groups[media_group_id]['processing'] = True
                
                # Wait a bit for more messages in the group
                await asyncio.sleep(1.5)
                
                # Check if we should process this group now
                group_data = self.processing_media_groups.get(media_group_id)
                if group_data and len(group_data['messages']) > 0:
                    # Process the entire media group
                    messages = group_data['messages']
                    status_msg = group_data['status_msg']
                    
                    # Copy the media group to Backup Channel
                    copied_messages = await self.app.copy_media_group(
                        chat_id=Config.BACKUP_CHANNEL_ID,
                        from_chat_id=message.chat.id,
                        message_id=messages[0].id
                    )
                    
                    # Store each message in database
                    for orig_msg, backup_msg in zip(messages, copied_messages):
                        file_id = None
                        if orig_msg.video:
                            file_id = orig_msg.video.file_id
                        elif orig_msg.photo:
                            file_id = orig_msg.photo.file_id
                        elif orig_msg.document:
                            file_id = orig_msg.document.file_id
                        
                        self.db.add_message(
                            main_msg_id=0,
                            backup_msg_id=backup_msg.id,
                            file_id=file_id,
                            media_group_id=media_group_id
                        )
                    
                    # Update status
                    if status_msg:
                        await status_msg.edit_text(
                            f"✅ **Album backed up successfully!**\n\n"
                            f"📦 {len(copied_messages)} items backed up\n"
                            f"📊 Queue Status: {self.db.get_pending_count()} pending\n\n"
                            f"🔧 Use /forward to send to Target Channel\n"
                            f"📊 Use /stats to check queue status"
                        )
                    
                    logger.info(f"✓ Backed up media group from private: {len(copied_messages)} items")
                    
                    # Mark as processed
                    self.processed_media_groups.add(media_group_id)
                    
                    # Clean up
                    del self.processing_media_groups[media_group_id]
                    return
            
            # Single media item (not part of a group)
            # Detect media type
            media_type = "media"
            if message.video:
                media_type = "video"
            elif message.photo:
                media_type = "photo"
            elif message.document:
                media_type = "document"
            elif message.audio:
                media_type = "audio"
            elif message.voice:
                media_type = "voice"
            elif message.animation:
                media_type = "animation"
            elif message.sticker:
                media_type = "sticker"
            
            logger.info(f"New {media_type} from private chat: user_id={message.from_user.id}")
            
            # Send confirmation
            status_msg = await message.reply_text(f"⏳ Processing your {media_type}...")
            
            # Copy to Backup Channel (without author attribution)
            backup_message = await self.app.copy_message(
                chat_id=Config.BACKUP_CHANNEL_ID,
                from_chat_id=message.chat.id,
                message_id=message.id
            )
            
            # Extract file_id
            file_id = None
            if message.video:
                file_id = message.video.file_id
            elif message.photo:
                file_id = message.photo.file_id
            elif message.document:
                file_id = message.document.file_id
            elif message.audio:
                file_id = message.audio.file_id
            elif message.voice:
                file_id = message.voice.file_id
            elif message.animation:
                file_id = message.animation.file_id
            elif message.sticker:
                file_id = message.sticker.file_id
            
            # Store in database (main_msg_id = 0 for private uploads)
            self.db.add_message(
                main_msg_id=0,  # 0 indicates private chat upload
                backup_msg_id=backup_message.id,
                file_id=file_id,
                media_group_id=None
            )
            
            # Update status message
            await status_msg.edit_text(
                f"✅ **{media_type.capitalize()} backed up successfully!**\n\n"
                f"📦 Backup Message ID: `{backup_message.id}`\n"
                f"📊 Queue Status: {self.db.get_pending_count()} pending\n\n"
                f"🔧 Use /forward to send to Target Channel\n"
                f"📊 Use /stats to check queue status"
            )
            
            logger.info(f"✓ Backed up {media_type} from private: backup={backup_message.id}")
            
        except FloodWait as e:
            logger.warning(f"FloodWait on private backup: sleeping {e.value}s")
            await asyncio.sleep(e.value)
            await self.backup_media_from_private(message)
        except Exception as e:
            logger.error(f"Error backing up private media: {e}", exc_info=True)
            await message.reply_text("❌ Error processing your media. Please try again.")
    
    async def backup_media(self, message: Message):
        """
        Forward all media from Main Channel to Backup Channel and index it
        
        Process:
        1. Check if part of media group, handle accordingly
        2. Forward message(s) to Backup Channel
        3. Store message IDs and file_id in database
        4. Message is automatically queued for batch forwarding
        """
        try:
            # Check if this is part of a media group
            media_group_id = message.media_group_id if hasattr(message, 'media_group_id') else None
            
            if media_group_id:
                # Check if this group was already processed
                if media_group_id in self.processed_media_groups:
                    logger.info(f"Media group {media_group_id} already processed, skipping message {message.id}")
                    return
                
                # This is part of a media group/album from Main Channel
                # Track it to process as group
                if media_group_id not in self.processing_media_groups:
                    self.processing_media_groups[media_group_id] = {
                        'messages': [],
                        'chat_id': Config.MAIN_CHANNEL_ID,
                        'processing': False  # Flag to prevent concurrent processing
                    }
                
                # Add message to group
                self.processing_media_groups[media_group_id]['messages'].append(message)
                
                # If another message is already processing this group, skip
                if self.processing_media_groups[media_group_id]['processing']:
                    logger.info(f"Media group {media_group_id} already being processed by another message")
                    return
                
                # Mark as processing
                self.processing_media_groups[media_group_id]['processing'] = True
                
                # Wait a bit for more messages in the group
                await asyncio.sleep(1.5)
                
                # Check if we should process this group now
                group_data = self.processing_media_groups.get(media_group_id)
                if group_data and len(group_data['messages']) > 0:
                    # Process the entire media group
                    messages = group_data['messages']
                    
                    logger.info(f"New media group in Main Channel: {len(messages)} items, msg_id={messages[0].id}")
                    
                    # Copy the media group to Backup Channel
                    copied_messages = await self.app.copy_media_group(
                        chat_id=Config.BACKUP_CHANNEL_ID,
                        from_chat_id=Config.MAIN_CHANNEL_ID,
                        message_id=messages[0].id
                    )
                    
                    # Store each message in database
                    for orig_msg, backup_msg in zip(messages, copied_messages):
                        file_id = None
                        if orig_msg.video:
                            file_id = orig_msg.video.file_id
                        elif orig_msg.photo:
                            file_id = orig_msg.photo.file_id
                        elif orig_msg.document:
                            file_id = orig_msg.document.file_id
                        
                        self.db.add_message(
                            main_msg_id=orig_msg.id,
                            backup_msg_id=backup_msg.id,
                            file_id=file_id,
                            media_group_id=media_group_id
                        )
                    
                    logger.info(f"✓ Backed up media group: main={messages[0].id} → backup ({len(copied_messages)} items)")
                    
                    # Mark as processed
                    self.processed_media_groups.add(media_group_id)
                    
                    # Clean up
                    del self.processing_media_groups[media_group_id]
                    return
            
            # Single media item (not part of a group)
            # Detect media type
            media_type = "media"
            if message.video:
                media_type = "video"
            elif message.photo:
                media_type = "photo"
            elif message.document:
                media_type = "document"
            elif message.audio:
                media_type = "audio"
            elif message.voice:
                media_type = "voice"
            elif message.animation:
                media_type = "animation"
            elif message.sticker:
                media_type = "sticker"
            
            logger.info(f"New {media_type} in Main Channel: msg_id={message.id}")
            
            # Copy to Backup Channel (without author attribution)
            backup_message = await self.app.copy_message(
                chat_id=Config.BACKUP_CHANNEL_ID,
                from_chat_id=Config.MAIN_CHANNEL_ID,
                message_id=message.id
            )
            
            # Extract file_id for reference
            file_id = None
            if message.video:
                file_id = message.video.file_id
            elif message.photo:
                file_id = message.photo.file_id
            elif message.document:
                file_id = message.document.file_id
            elif message.audio:
                file_id = message.audio.file_id
            elif message.voice:
                file_id = message.voice.file_id
            elif message.animation:
                file_id = message.animation.file_id
            elif message.sticker:
                file_id = message.sticker.file_id
            
            # Store in database (automatically queued as 'pending')
            self.db.add_message(
                main_msg_id=message.id,
                backup_msg_id=backup_message.id,
                file_id=file_id,
                media_group_id=None
            )
            
            logger.info(
                f"✓ Backed up {media_type}: main={message.id} → backup={backup_message.id}"
            )
            
        except FloodWait as e:
            logger.warning(f"FloodWait on backup: sleeping {e.value}s")
            await asyncio.sleep(e.value)
            # Retry backup
            await self.backup_media(message)
        except Exception as e:
            logger.error(f"Error backing up media: {e}", exc_info=True)
    
    async def process_batch_messages(self, batch_id: int, messages: list):
        """
        Forward a batch of messages from Backup to Target Channel
        Groups media albums together when possible.
        
        Args:
            batch_id: The batch being processed
            messages: List of message records to forward
        
        Process:
        1. Group messages by media_group_id
        2. Forward media groups together
        3. Forward individual messages separately
        4. Apply delay between forwards
        5. Handle FloodWait gracefully
        6. Update database status after each success
        """
        logger.info(f"Forwarding {len(messages)} messages from batch {batch_id}")
        
        # Group messages by media_group_id
        media_groups = {}
        individual_messages = []
        
        for msg_record in messages:
            # sqlite3.Row doesn't have .get() method, use direct access with try/except
            try:
                media_group_id = msg_record['media_group_id']
            except (KeyError, IndexError):
                media_group_id = None
            
            if media_group_id:
                if media_group_id not in media_groups:
                    media_groups[media_group_id] = []
                media_groups[media_group_id].append(msg_record)
            else:
                individual_messages.append(msg_record)
        
        # Forward media groups first
        for group_id, group_messages in media_groups.items():
            try:
                logger.info(f"Forwarding media group {group_id} with {len(group_messages)} items")
                
                # Get all message IDs in this group
                backup_msg_ids = [msg['backup_msg_id'] for msg in group_messages]
                
                # Copy media group to Target Channel
                await self.app.copy_media_group(
                    chat_id=Config.TARGET_CHANNEL_ID,
                    from_chat_id=Config.BACKUP_CHANNEL_ID,
                    message_id=backup_msg_ids[0]  # Pyrogram uses first message ID to copy entire group
                )
                
                # Mark all messages in group as done
                for msg in group_messages:
                    self.db.mark_message_done(msg['backup_msg_id'])
                
                logger.info(f"✓ Forwarded media group {group_id} ({len(group_messages)} items) → target")
                
                # Apply delay
                await asyncio.sleep(Config.FORWARD_DELAY)
                
            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)
                continue
                
            except Exception as e:
                logger.error(f"Error forwarding media group {group_id}: {e}")
                # Fall back to individual forwarding for this group
                logger.info(f"Falling back to individual forwarding for media group {group_id}")
                individual_messages.extend(group_messages)
                await asyncio.sleep(5)
        
        # Forward individual messages
        for msg_record in individual_messages:
            try:
                backup_msg_id = msg_record['backup_msg_id']
                
                # Copy from Backup Channel to Target Channel (without author attribution)
                await self.app.copy_message(
                    chat_id=Config.TARGET_CHANNEL_ID,
                    from_chat_id=Config.BACKUP_CHANNEL_ID,
                    message_id=backup_msg_id
                )
                
                # Mark as done in database
                self.db.mark_message_done(backup_msg_id)
                
                logger.info(f"✓ Forwarded: backup_msg={backup_msg_id} → target")
                
                # Apply delay to avoid rate limits
                await asyncio.sleep(Config.FORWARD_DELAY)
                
            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)
                # Retry this message (loop will continue)
                continue
                
            except Exception as e:
                logger.error(f"Error forwarding message {backup_msg_id}: {e}")
                # Continue with next message (can implement retry logic here)
                await asyncio.sleep(5)
    
    async def startup(self):
        """
        Bot startup routine
        
        1. Check for incomplete batches (crash recovery)
        2. Show configuration and instructions
        """
        logger.info("Bot starting up...")
        logger.info("")
        logger.info("Configuration:")
        logger.info(f"  Main Channel ID: {Config.MAIN_CHANNEL_ID}")
        logger.info(f"  Backup Channel ID: {Config.BACKUP_CHANNEL_ID}")
        logger.info(f"  Target Channel ID: {Config.TARGET_CHANNEL_ID}")
        logger.info(f"  Batch Size: {Config.BATCH_SIZE}")
        logger.info(f"  Forward Delay: {Config.FORWARD_DELAY}s")
        logger.info("")
        
        # Try to resolve channels (skip if they're private and not yet discovered)
        logger.info("Note: For PRIVATE channels, the bot will discover them automatically")
        logger.info("      when messages arrive. Make sure bot is admin in all channels!")
        logger.info("")
        
        # Check for incomplete batches from previous run
        active_batch = self.db.get_active_batch()
        if active_batch:
            logger.info(f"⚠️  Incomplete batch found: {active_batch['id']}")
            logger.info(f"   Use /forward to resume or it will be processed on next forward")
        
        # Print statistics
        stats = self.db.get_statistics()
        logger.info(f"Database stats: {stats}")
        logger.info("")
        logger.info("="*60)
        logger.info("[OK] Bot is READY and monitoring for messages!")
        logger.info("="*60)
        logger.info("")
        logger.info("⚠️  SETUP REQUIRED FOR PRIVATE CHANNELS:")
        logger.info("")
        logger.info("STEP 1: Post a message in EACH channel")
        logger.info("  - Go to Main Channel → Post ANY message (text/emoji)")
        logger.info("  - Go to Backup Channel → Post ANY message")
        logger.info("  - Go to Target Channel → Post ANY message")
        logger.info("  - This lets the bot discover the channels")
        logger.info("")
        logger.info("STEP 2: Run setup command")
        logger.info("  - Open private chat with your bot")
        logger.info("  - Send: /setup")
        logger.info("  - Wait for confirmation")
        logger.info("")
        logger.info("NOTE: You only need to do this ONCE or after bot restart")
        logger.info("")
        logger.info("📤 After setup, upload media:")
        logger.info("  1. Upload to Main Channel, OR")
        logger.info("  2. Send directly to the bot in private chat")
        logger.info("")
        logger.info("🎮 Manual forwarding:")
        logger.info("  - Bot will BACKUP media automatically")
        logger.info("  - Use /stats to check queue")
        logger.info("  - Use /forward to send to Target Channel")
        logger.info("")
    

    
    async def run(self):
        """Start the bot"""
        await self.app.start()
        logger.info("Bot started successfully")
        
        # Run startup tasks
        await self.startup()
        
        # Keep bot running
        await asyncio.Event().wait()


async def main():
    """Main entry point"""
    logger.info("="*60)
    logger.info("Telegram Auto-Forwarder Bot")
    logger.info("="*60)
    
    # Create and run bot
    bot = TelegramForwarder()
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        bot.db.close()


if __name__ == "__main__":
    asyncio.run(main())
