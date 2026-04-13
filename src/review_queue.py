"""
Review Queue - Human review queue for AI-analyzed failures.

Stores failures from Splunk that need human validation before
becoming training data.
"""

import sqlite3
import logging
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger("jenkins-agent.review-queue")

DEFAULT_DB_PATH = "/app/data/review_queue.db"


class ReviewStatus(str, Enum):
    """Review queue item status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass
class ReviewItem:
    """Item in the review queue."""
    id: Optional[int] = None
    host: str = ""
    job_name: str = ""
    job_id: str = ""
    log_snippet: str = ""
    
    # AI analysis results
    ai_root_cause: str = ""
    ai_fix: str = ""
    ai_confidence: float = 0.0
    ai_category: str = ""
    
    # Human review
    status: str = "pending"
    confirmed_root_cause: str = ""
    confirmed_fix: str = ""
    confirmed_category: str = ""
    reviewer: str = ""
    notes: str = ""
    
    # Timestamps
    created_at: str = ""
    reviewed_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "host": self.host,
            "job_name": self.job_name,
            "job_id": self.job_id,
            "log_snippet": self.log_snippet[:1000] if self.log_snippet else "",
            "ai_root_cause": self.ai_root_cause,
            "ai_fix": self.ai_fix,
            "ai_confidence": self.ai_confidence,
            "ai_category": self.ai_category,
            "status": self.status,
            "confirmed_root_cause": self.confirmed_root_cause,
            "confirmed_fix": self.confirmed_fix,
            "confirmed_category": self.confirmed_category,
            "reviewer": self.reviewer,
            "notes": self.notes,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
        }
    
    @classmethod
    def from_row(cls, row: tuple) -> "ReviewItem":
        return cls(
            id=row[0],
            host=row[1] or "",
            job_name=row[2] or "",
            job_id=row[3] or "",
            log_snippet=row[4] or "",
            ai_root_cause=row[5] or "",
            ai_fix=row[6] or "",
            ai_confidence=row[7] or 0.0,
            ai_category=row[8] or "",
            status=row[9] or "pending",
            confirmed_root_cause=row[10] or "",
            confirmed_fix=row[11] or "",
            confirmed_category=row[12] or "",
            reviewer=row[13] or "",
            notes=row[14] or "",
            created_at=row[15] or "",
            reviewed_at=row[16] or "",
        )


class ReviewQueue:
    """
    SQLite-based review queue for human validation of AI analyses.
    """
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    log_snippet TEXT,
                    ai_root_cause TEXT,
                    ai_fix TEXT,
                    ai_confidence REAL DEFAULT 0.0,
                    ai_category TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    confirmed_root_cause TEXT,
                    confirmed_fix TEXT,
                    confirmed_category TEXT,
                    reviewer TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    UNIQUE(host, job_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_created ON review_queue(created_at)")
            conn.commit()
    
    def add(
        self,
        host: str,
        job_name: str,
        job_id: str,
        log_snippet: str = "",
        ai_root_cause: str = "",
        ai_fix: str = "",
        ai_confidence: float = 0.0,
        ai_category: str = "",
    ) -> ReviewItem:
        """Add item to review queue."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO review_queue 
                (host, job_name, job_id, log_snippet, ai_root_cause, ai_fix, ai_confidence, ai_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (host, job_name, job_id, log_snippet, ai_root_cause, ai_fix, ai_confidence, ai_category)
            )
            conn.commit()
            
            return ReviewItem(
                id=cursor.lastrowid,
                host=host,
                job_name=job_name,
                job_id=job_id,
                log_snippet=log_snippet,
                ai_root_cause=ai_root_cause,
                ai_fix=ai_fix,
                ai_confidence=ai_confidence,
                ai_category=ai_category,
                status="pending",
            )
    
    def get(self, item_id: int) -> Optional[ReviewItem]:
        """Get item by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            return ReviewItem.from_row(row) if row else None
    
    def exists(self, host: str, job_id: str) -> bool:
        """Check if item already exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM review_queue WHERE host = ? AND job_id = ?",
                (host, job_id)
            )
            return cursor.fetchone() is not None
    
    def list(self, status: str = None, limit: int = 50) -> List[ReviewItem]:
        """List items in queue."""
        with sqlite3.connect(self.db_path) as conn:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM review_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM review_queue ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            return [ReviewItem.from_row(row) for row in cursor.fetchall()]
    
    def update_status(
        self,
        item_id: int,
        status: ReviewStatus,
        confirmed_root_cause: str = None,
        confirmed_fix: str = None,
        confirmed_category: str = None,
        reviewer: str = None,
        notes: str = None,
    ) -> bool:
        """Update item status and review data."""
        with sqlite3.connect(self.db_path) as conn:
            sets = ["status = ?", "reviewed_at = CURRENT_TIMESTAMP"]
            params = [status.value]
            
            if confirmed_root_cause is not None:
                sets.append("confirmed_root_cause = ?")
                params.append(confirmed_root_cause)
            if confirmed_fix is not None:
                sets.append("confirmed_fix = ?")
                params.append(confirmed_fix)
            if confirmed_category is not None:
                sets.append("confirmed_category = ?")
                params.append(confirmed_category)
            if reviewer is not None:
                sets.append("reviewer = ?")
                params.append(reviewer)
            if notes is not None:
                sets.append("notes = ?")
                params.append(notes)
            
            params.append(item_id)
            cursor = conn.execute(
                f"UPDATE review_queue SET {', '.join(sets)} WHERE id = ?",
                params
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, item_id: int) -> bool:
        """Delete item from queue."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM review_queue WHERE id = ?", (item_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                    AVG(CASE WHEN status = 'approved' THEN ai_confidence ELSE NULL END) as avg_approved_confidence
                FROM review_queue
            """)
            row = cursor.fetchone()
            
            return {
                "total": row[0] or 0,
                "pending": row[1] or 0,
                "approved": row[2] or 0,
                "rejected": row[3] or 0,
                "avg_approved_confidence": round(row[4] or 0, 2),
            }


# Singleton
_review_queue: Optional[ReviewQueue] = None


def get_review_queue() -> ReviewQueue:
    """Get or create review queue singleton."""
    global _review_queue
    if _review_queue is None:
        _review_queue = ReviewQueue()
    return _review_queue
