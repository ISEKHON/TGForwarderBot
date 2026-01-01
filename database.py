"""
Database module for Telegram Auto-Forwarder Bot
Handles SQLite operations for message tracking and batch management
"""
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class Database:
    """SQLite database handler for message tracking"""
    
    def __init__(self, db_name: str):
        """Initialize database connection and create tables"""
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Establish database connection"""
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        self.cursor = self.conn.cursor()
        logger.info(f"Database connected: {self.db_name}")
    
    def _create_tables(self):
        """Create necessary tables if they don't exist"""
        # Messages table for tracking all forwarded content
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                main_msg_id INTEGER,
                backup_msg_id INTEGER UNIQUE NOT NULL,
                file_id TEXT,
                status TEXT DEFAULT 'pending',
                batch_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                forwarded_at TIMESTAMP DEFAULT NULL
            )
        ''')
        
        # Add media_group_id column if it doesn't exist (migration for existing databases)
        try:
            self.cursor.execute('SELECT media_group_id FROM messages LIMIT 1')
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            logger.info("Migrating database: Adding media_group_id column...")
            self.cursor.execute('ALTER TABLE messages ADD COLUMN media_group_id TEXT DEFAULT NULL')
            self.conn.commit()
            logger.info("Migration complete: media_group_id column added")
        
        # Batches table for tracking batch processing
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'pending',
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP DEFAULT NULL,
                completed_at TIMESTAMP DEFAULT NULL
            )
        ''')
        
        # Create indices for faster queries
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_status ON messages(status)
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_batch_id ON messages(batch_id)
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backup_msg_id ON messages(backup_msg_id)
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_media_group_id ON messages(media_group_id)
        ''')
        
        self.conn.commit()
        logger.info("Database tables created/verified")
    
    def add_message(self, main_msg_id: int, backup_msg_id: int, file_id: Optional[str] = None, media_group_id: Optional[str] = None) -> int:
        """
        Add a new message to the database
        Returns the message ID
        """
        try:
            self.cursor.execute('''
                INSERT INTO messages (main_msg_id, backup_msg_id, file_id, media_group_id, status)
                VALUES (?, ?, ?, ?, 'pending')
            ''', (main_msg_id, backup_msg_id, file_id, media_group_id))
            self.conn.commit()
            msg_id = self.cursor.lastrowid
            logger.info(f"Added message: main={main_msg_id}, backup={backup_msg_id}, db_id={msg_id}, media_group={media_group_id}")
            return msg_id
        except sqlite3.IntegrityError:
            logger.warning(f"Message already exists: backup_msg_id={backup_msg_id}")
            return -1
    
    def get_pending_count(self) -> int:
        """Get count of pending messages (not assigned to any batch)"""
        self.cursor.execute('''
            SELECT COUNT(*) FROM messages 
            WHERE status = 'pending' AND batch_id IS NULL
        ''')
        count = self.cursor.fetchone()[0]
        return count
    
    def get_message_by_main_id(self, main_msg_id: int):
        """Check if a message from Main Channel already exists in database"""
        self.cursor.execute('''
            SELECT * FROM messages WHERE main_msg_id = ?
        ''', (main_msg_id,))
        return self.cursor.fetchone()
    
    def get_pending_messages(self, limit: int) -> List[sqlite3.Row]:
        """Get pending messages not assigned to any batch"""
        self.cursor.execute('''
            SELECT * FROM messages 
            WHERE status = 'pending' AND batch_id IS NULL
            ORDER BY id ASC
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_all_messages(self, limit: int = None) -> List[sqlite3.Row]:
        """Get all messages from Backup Channel regardless of status"""
        if limit:
            self.cursor.execute('''
                SELECT * FROM messages 
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
        else:
            self.cursor.execute('''
                SELECT * FROM messages 
                ORDER BY id ASC
            ''')
        return self.cursor.fetchall()
    
    def create_batch(self, message_ids: List[int]) -> int:
        """
        Create a new batch and assign messages to it
        Returns the batch ID
        """
        # Create batch
        self.cursor.execute('''
            INSERT INTO batches (status, message_count, started_at)
            VALUES ('processing', ?, CURRENT_TIMESTAMP)
        ''', (len(message_ids),))
        batch_id = self.cursor.lastrowid
        
        # Assign messages to batch
        self.cursor.execute(f'''
            UPDATE messages 
            SET batch_id = ?, status = 'processing'
            WHERE id IN ({','.join('?' * len(message_ids))})
        ''', [batch_id] + message_ids)
        
        self.conn.commit()
        logger.info(f"Created batch {batch_id} with {len(message_ids)} messages")
        return batch_id
    
    def get_batch_messages(self, batch_id: int) -> List[sqlite3.Row]:
        """Get all messages for a specific batch"""
        self.cursor.execute('''
            SELECT * FROM messages 
            WHERE batch_id = ?
            ORDER BY id ASC
        ''', (batch_id,))
        return self.cursor.fetchall()
    
    def mark_message_done(self, backup_msg_id: int):
        """Mark a message as successfully forwarded"""
        self.cursor.execute('''
            UPDATE messages 
            SET status = 'done', forwarded_at = CURRENT_TIMESTAMP
            WHERE backup_msg_id = ?
        ''', (backup_msg_id,))
        self.conn.commit()
    
    def complete_batch(self, batch_id: int):
        """Mark a batch as completed"""
        self.cursor.execute('''
            UPDATE batches 
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (batch_id,))
        self.conn.commit()
        logger.info(f"Batch {batch_id} completed")
    
    def get_active_batch(self) -> Optional[sqlite3.Row]:
        """Get the currently active (processing) batch"""
        self.cursor.execute('''
            SELECT * FROM batches 
            WHERE status = 'processing'
            ORDER BY id ASC
            LIMIT 1
        ''')
        return self.cursor.fetchone()
    
    def get_incomplete_batch_messages(self, batch_id: int) -> List[sqlite3.Row]:
        """Get messages in a batch that haven't been forwarded yet"""
        self.cursor.execute('''
            SELECT * FROM messages 
            WHERE batch_id = ? AND status = 'processing'
            ORDER BY id ASC
        ''', (batch_id,))
        return self.cursor.fetchall()
    
    def get_statistics(self) -> dict:
        """Get database statistics"""
        stats = {}
        
        # Total messages
        self.cursor.execute('SELECT COUNT(*) FROM messages')
        stats['total_messages'] = self.cursor.fetchone()[0]
        
        # Messages by status
        self.cursor.execute('SELECT status, COUNT(*) FROM messages GROUP BY status')
        stats['by_status'] = dict(self.cursor.fetchall())
        
        # Total batches
        self.cursor.execute('SELECT COUNT(*) FROM batches')
        stats['total_batches'] = self.cursor.fetchone()[0]
        
        # Batches by status
        self.cursor.execute('SELECT status, COUNT(*) FROM batches GROUP BY status')
        stats['batches_by_status'] = dict(self.cursor.fetchall())
        
        return stats
    
    def clear_pending_messages(self) -> int:
        """
        Delete all pending messages from database
        Returns the number of messages deleted
        """
        # Get count first
        self.cursor.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'")
        count = self.cursor.fetchone()[0]
        
        # Delete pending messages
        self.cursor.execute("DELETE FROM messages WHERE status = 'pending'")
        self.conn.commit()
        
        logger.info(f"Cleared {count} pending messages from database")
        return count
    
    def reset_database(self) -> dict:
        """
        Reset the entire database - DELETE ALL DATA
        Returns statistics about what was deleted
        """
        # Get counts before deletion
        stats = {}
        self.cursor.execute("SELECT COUNT(*) FROM messages")
        stats['messages_deleted'] = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM batches")
        stats['batches_deleted'] = self.cursor.fetchone()[0]
        
        # Delete all data
        self.cursor.execute("DELETE FROM messages")
        self.cursor.execute("DELETE FROM batches")
        
        # Reset autoincrement counters
        self.cursor.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        self.cursor.execute("DELETE FROM sqlite_sequence WHERE name='batches'")
        
        self.conn.commit()
        
        logger.info(f"Database reset: {stats['messages_deleted']} messages, {stats['batches_deleted']} batches deleted")
        return stats
    
    def reset_stuck_messages(self) -> int:
        """
        Reset messages stuck in 'processing' state back to 'pending'
        Returns count of messages reset
        """
        # Find stuck processing messages
        self.cursor.execute('''
            SELECT COUNT(*) FROM messages 
            WHERE status = 'processing'
        ''')
        count = self.cursor.fetchone()[0]
        
        if count > 0:
            # Reset to pending and clear batch_id
            self.cursor.execute('''
                UPDATE messages 
                SET status = 'pending', batch_id = NULL
                WHERE status = 'processing'
            ''')
            self.conn.commit()
            
        logger.info(f"Reset {count} stuck messages from processing to pending")
        return count
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

