"""
Feedback Store - SQLite-based storage for analyst-confirmed analyses.

Implements Requirement 15: Feedback Collection and RAG-Based Few-Shot Learning

Stores confirmed root cause analyses that are used as few-shot examples
in future AI prompts to improve accuracy without model retraining.

Database location: /app/data/feedback.db (persisted via agent_data Docker volume)
"""

import sqlite3
import logging
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import re
from collections import Counter

logger = logging.getLogger("jenkins-agent.feedback")

# Default database path (Req 15.1)
DEFAULT_DB_PATH = "/app/data/feedback.db"


@dataclass
class FeedbackEntry:
    """A single feedback entry (Req 15.2)."""
    id: Optional[int] = None
    timestamp: str = ""
    job_name: str = ""
    build_number: int = 0
    error_category: str = ""
    error_snippet: str = ""  # First 500 chars of primary error
    failed_stage: str = ""
    failed_method: str = ""
    ai_root_cause: str = ""  # What AI said
    confirmed_root_cause: str = ""  # What analyst confirmed
    confirmed_fix: str = ""  # Actual fix applied
    was_correct: bool = True  # Did AI get it right?
    feedback_source: str = "user"  # "user" or "auto"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: tuple) -> "FeedbackEntry":
        """Create from database row."""
        return cls(
            id=row[0],
            timestamp=row[1],
            job_name=row[2],
            build_number=row[3],
            error_category=row[4],
            error_snippet=row[5],
            failed_stage=row[6],
            failed_method=row[7],
            ai_root_cause=row[8],
            confirmed_root_cause=row[9],
            confirmed_fix=row[10],
            was_correct=bool(row[11]),
            feedback_source=row[12],
        )


class FeedbackStore:
    """
    SQLite-based feedback storage (Requirement 15).
    
    Usage:
        store = FeedbackStore()  # Uses default path
        store.add_feedback(entry)
        similar = store.find_similar(error_snippet, category, limit=3)
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize feedback store.
        
        Args:
            db_path: Path to SQLite database. Defaults to /app/data/feedback.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database (Req 15.9)
        self._init_db()
        
        logger.info(f"FeedbackStore initialized at {self.db_path}")
    
    def _init_db(self):
        """Create tables if they don't exist (Req 15.9)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    build_number INTEGER,
                    error_category TEXT,
                    error_snippet TEXT,
                    failed_stage TEXT,
                    failed_method TEXT,
                    ai_root_cause TEXT,
                    confirmed_root_cause TEXT,
                    confirmed_fix TEXT,
                    was_correct INTEGER DEFAULT 1,
                    feedback_source TEXT DEFAULT 'user'
                )
            """)
            
            # Index for similarity search
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_category 
                ON feedback(error_category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_stage 
                ON feedback(failed_stage)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_method 
                ON feedback(failed_method)
            """)
            
            conn.commit()
    
    def add_feedback(self, entry: FeedbackEntry) -> int:
        """
        Add a feedback entry (Req 15.3).
        
        Args:
            entry: FeedbackEntry to store
            
        Returns:
            ID of the inserted row
        """
        if not entry.timestamp:
            entry.timestamp = datetime.utcnow().isoformat()
        
        # Truncate error_snippet to 500 chars (Req 15.2)
        entry.error_snippet = entry.error_snippet[:500] if entry.error_snippet else ""
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO feedback (
                    timestamp, job_name, build_number, error_category,
                    error_snippet, failed_stage, failed_method,
                    ai_root_cause, confirmed_root_cause, confirmed_fix,
                    was_correct, feedback_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.timestamp,
                entry.job_name,
                entry.build_number,
                entry.error_category,
                entry.error_snippet,
                entry.failed_stage,
                entry.failed_method,
                entry.ai_root_cause,
                entry.confirmed_root_cause,
                entry.confirmed_fix,
                1 if entry.was_correct else 0,
                entry.feedback_source,
            ))
            conn.commit()
            
            entry_id = cursor.lastrowid
            
            # Log corrections (Req 15.12)
            if not entry.was_correct:
                logger.info(f"Correction received for {entry.job_name}#{entry.build_number}: "
                           f"AI said '{entry.ai_root_cause[:50]}...', "
                           f"actual was '{entry.confirmed_root_cause[:50]}...'")
            
            return entry_id
    
    def get_recent(self, limit: int = 50, category: str = None) -> List[FeedbackEntry]:
        """
        Get recent feedback entries (Req 15.4).
        
        Args:
            limit: Maximum entries to return
            category: Optional category filter
            
        Returns:
            List of FeedbackEntry objects
        """
        with sqlite3.connect(self.db_path) as conn:
            if category:
                cursor = conn.execute("""
                    SELECT * FROM feedback 
                    WHERE error_category = ?
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (category, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM feedback 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
            
            return [FeedbackEntry.from_row(row) for row in cursor.fetchall()]
    
    def find_similar(
        self,
        error_snippet: str,
        error_category: str = None,
        failed_stage: str = None,
        failed_method: str = None,
        limit: int = 3,
    ) -> List[FeedbackEntry]:
        """
        Find similar past cases using keyword similarity (Req 15.5, 15.6).
        
        Uses simple TF-IDF-like keyword overlap - no vector DB needed.
        
        Args:
            error_snippet: Current error text to match
            error_category: Optional category filter
            failed_stage: Optional stage filter
            failed_method: Optional method filter
            limit: Maximum results (default 3 per Req 15.5)
            
        Returns:
            List of similar FeedbackEntry objects, scored by relevance
        """
        # Get candidates from database
        with sqlite3.connect(self.db_path) as conn:
            # Build query with optional filters
            query = "SELECT * FROM feedback WHERE 1=1"
            params = []
            
            if error_category:
                query += " AND error_category = ?"
                params.append(error_category)
            
            if failed_stage:
                query += " AND failed_stage = ?"
                params.append(failed_stage)
            
            if failed_method:
                query += " AND failed_method = ?"
                params.append(failed_method)
            
            # Limit candidates for scoring
            query += " ORDER BY timestamp DESC LIMIT 100"
            
            cursor = conn.execute(query, params)
            candidates = [FeedbackEntry.from_row(row) for row in cursor.fetchall()]
        
        if not candidates:
            return []
        
        # Score by keyword overlap (Req 15.6)
        query_tokens = self._tokenize(error_snippet)
        
        scored = []
        for entry in candidates:
            entry_tokens = self._tokenize(entry.error_snippet)
            score = self._keyword_overlap_score(query_tokens, entry_tokens)
            
            # Boost for matching category/stage/method
            if error_category and entry.error_category == error_category:
                score += 0.3
            if failed_stage and entry.failed_stage == failed_stage:
                score += 0.2
            if failed_method and entry.failed_method == failed_method:
                score += 0.2
            
            if score > 0:
                scored.append((score, entry))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return [entry for score, entry in scored[:limit]]
    
    def _tokenize(self, text: str) -> Counter:
        """Tokenize text into word frequency counter."""
        if not text:
            return Counter()
        
        # Lowercase and split on non-word characters
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter out very short words and common stop words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with',
                      'this', 'that', 'it', 'not', 'no', 'yes', 'true', 'false'}
        
        words = [w for w in words if len(w) > 2 and w not in stop_words]
        
        return Counter(words)
    
    def _keyword_overlap_score(self, query: Counter, entry: Counter) -> float:
        """Calculate keyword overlap score (simple TF-IDF-like)."""
        if not query or not entry:
            return 0.0
        
        # Intersection of keywords
        common = set(query.keys()) & set(entry.keys())
        
        if not common:
            return 0.0
        
        # Score based on overlap normalized by size
        overlap_count = sum(min(query[w], entry[w]) for w in common)
        total_count = sum(query.values()) + sum(entry.values())
        
        return (2.0 * overlap_count) / total_count if total_count > 0 else 0.0
    
    def format_few_shot_prompt(self, similar_cases: List[FeedbackEntry]) -> str:
        """
        Format similar cases for AI prompt injection (Req 15.8).
        
        Args:
            similar_cases: List of similar FeedbackEntry objects
            
        Returns:
            Formatted prompt section string
        """
        if not similar_cases:
            return ""
        
        parts = ["## SIMILAR PAST CASES ##\n"]
        
        for i, case in enumerate(similar_cases, 1):
            parts.append(f"""
Case {i}: {case.error_category} in stage "{case.failed_stage}"
Error: {case.error_snippet[:200]}...
Root Cause: {case.confirmed_root_cause}
Fix: {case.confirmed_fix}
""")
        
        return "\n".join(parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get feedback store statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            correct = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE was_correct = 1"
            ).fetchone()[0]
            
            categories = conn.execute("""
                SELECT error_category, COUNT(*) as cnt 
                FROM feedback 
                GROUP BY error_category 
                ORDER BY cnt DESC
            """).fetchall()
            
            return {
                "total_entries": total,
                "correct_predictions": correct,
                "accuracy": correct / total if total > 0 else 0,
                "by_category": dict(categories),
            }


# Global instance for convenience
_store: Optional[FeedbackStore] = None


def get_feedback_store(db_path: str = None) -> FeedbackStore:
    """Get or create the global feedback store instance."""
    global _store
    if _store is None:
        _store = FeedbackStore(db_path)
    return _store
