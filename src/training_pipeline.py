"""
Training Pipeline - Prepare and manage fine-tuning data.

Phase 4 of AI Learning System.

Features:
- Combine feedback + knowledge store into training data
- Export in multiple formats (JSONL for OpenAI/Ollama, CSV for analysis)
- Training job management and status tracking
- Data quality validation
- Statistics and metrics

Database: Uses same /app/data/ directory as other stores
"""

import json
import logging
import sqlite3
import hashlib
import csv
import io
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Generator
from enum import Enum

logger = logging.getLogger("jenkins-agent.training")

# Default paths
DEFAULT_DB_PATH = "/app/data/training.db"
DEFAULT_EXPORT_PATH = "/app/data/exports"


class TrainingFormat(str, Enum):
    """Supported training data formats."""
    JSONL_OPENAI = "jsonl_openai"
    JSONL_OLLAMA = "jsonl_ollama"
    JSONL_ANTHROPIC = "jsonl_anthropic"
    CSV = "csv"
    JSON = "json"


class TrainingJobStatus(str, Enum):
    """Training job status."""
    PENDING = "pending"
    PREPARING = "preparing"
    READY = "ready"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TrainingExample:
    """A single training example."""
    id: Optional[int] = None
    source: str = ""
    source_id: Optional[int] = None
    
    # Input context
    job_name: str = ""
    error_category: str = ""
    error_snippet: str = ""
    failed_stage: str = ""
    failed_method: str = ""
    tool_name: str = ""
    
    # Expected output
    root_cause: str = ""
    fix: str = ""
    category: str = ""
    confidence: float = 0.9
    is_retriable: bool = False
    
    # Quality metrics
    quality_score: float = 1.0
    is_validated: bool = False
    validation_notes: str = ""
    
    # Metadata
    created_at: str = ""
    content_hash: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def compute_hash(self) -> str:
        """Compute content hash for deduplication."""
        content = f"{self.error_snippet}|{self.root_cause}|{self.fix}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI/Ollama fine-tuning format."""
        system_prompt = (
            "You are an expert Jenkins CI/CD failure analyst. "
            "Analyze build failures and provide root cause analysis in JSON format."
        )
        
        user_content = f"Analyze this Jenkins build failure:\n\n"
        if self.job_name:
            user_content += f"Job: {self.job_name}\n"
        if self.failed_stage:
            user_content += f"Stage: {self.failed_stage}\n"
        if self.failed_method:
            user_content += f"Method: {self.failed_method}\n"
        if self.tool_name:
            user_content += f"Tool: {self.tool_name}\n"
        user_content += f"Error: {self.error_snippet}"
        
        assistant_content = json.dumps({
            "root_cause": self.root_cause,
            "category": self.category,
            "confidence": self.confidence,
            "is_retriable": self.is_retriable,
            "fix": self.fix,
        })
        
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """Convert to Anthropic fine-tuning format."""
        human_content = f"Analyze this Jenkins build failure:\n\n"
        if self.job_name:
            human_content += f"Job: {self.job_name}\n"
        if self.failed_stage:
            human_content += f"Stage: {self.failed_stage}\n"
        if self.tool_name:
            human_content += f"Tool: {self.tool_name}\n"
        human_content += f"Error: {self.error_snippet}\n\nProvide root cause analysis in JSON format."
        
        assistant_content = json.dumps({
            "root_cause": self.root_cause,
            "category": self.category,
            "confidence": self.confidence,
            "is_retriable": self.is_retriable,
            "fix": self.fix,
        })
        
        return {
            "prompt": f"Human: {human_content}\n\nAssistant: {assistant_content}"
        }
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate training example quality."""
        issues = []
        
        # Required fields
        if not self.error_snippet or len(self.error_snippet) < 10:
            issues.append("error_snippet too short or missing")
        if not self.root_cause or len(self.root_cause) < 10:
            issues.append("root_cause too short or missing")
        
        # Quality checks
        if len(self.error_snippet) > 5000:
            issues.append("error_snippet too long (>5000 chars)")
        if len(self.root_cause) > 2000:
            issues.append("root_cause too long (>2000 chars)")
        
        # Category validation
        valid_categories = [
            "CREDENTIAL", "NETWORK", "PERMISSION", "CONFIGURATION",
            "BUILD", "TEST", "INFRASTRUCTURE", "GROOVY_LIBRARY",
            "GROOVY_CPS", "TOOL_ERROR", "UNKNOWN"
        ]
        if self.category and self.category not in valid_categories:
            issues.append(f"invalid category: {self.category}")
        
        # Confidence check
        if not (0 <= self.confidence <= 1):
            issues.append(f"invalid confidence: {self.confidence}")
        
        is_valid = len(issues) == 0
        return is_valid, issues


@dataclass
class TrainingJob:
    """A training data preparation job."""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    status: str = TrainingJobStatus.PENDING.value
    
    # Configuration
    include_feedback: bool = True
    include_knowledge: bool = True
    min_quality_score: float = 0.5
    format: str = TrainingFormat.JSONL_OPENAI.value
    
    # Results
    total_examples: int = 0
    valid_examples: int = 0
    exported_path: str = ""
    error_message: str = ""
    
    # Timestamps
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TrainingPipeline:
    """
    Training data preparation and management.
    
    Usage:
        pipeline = TrainingPipeline()
        
        # Create a training job
        job_id = pipeline.create_job(
            name="finetune-v1",
            include_feedback=True,
            include_knowledge=True,
            format="jsonl_openai"
        )
        
        # Prepare training data
        pipeline.prepare_job(job_id)
        
        # Export
        filepath = pipeline.export_job(job_id)
    """
    
    def __init__(self, db_path: str = None, export_path: str = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.export_path = export_path or DEFAULT_EXPORT_PATH
        
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.export_path).mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        logger.info(f"TrainingPipeline initialized at {self.db_path}")
    
    def _init_db(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            # Training examples table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_id INTEGER,
                    job_name TEXT,
                    error_category TEXT,
                    error_snippet TEXT NOT NULL,
                    failed_stage TEXT,
                    failed_method TEXT,
                    tool_name TEXT,
                    root_cause TEXT NOT NULL,
                    fix TEXT,
                    category TEXT,
                    confidence REAL DEFAULT 0.9,
                    is_retriable INTEGER DEFAULT 0,
                    quality_score REAL DEFAULT 1.0,
                    is_validated INTEGER DEFAULT 0,
                    validation_notes TEXT,
                    content_hash TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Training jobs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    include_feedback INTEGER DEFAULT 1,
                    include_knowledge INTEGER DEFAULT 1,
                    min_quality_score REAL DEFAULT 0.5,
                    format TEXT DEFAULT 'jsonl_openai',
                    total_examples INTEGER DEFAULT 0,
                    valid_examples INTEGER DEFAULT 0,
                    exported_path TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_examples_source ON training_examples(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_examples_quality ON training_examples(quality_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON training_jobs(status)")
            
            conn.commit()
    
    # =========================================================================
    # Training Examples Management
    # =========================================================================
    
    def add_example(self, example: TrainingExample) -> int:
        """Add a training example."""
        example.content_hash = example.compute_hash()
        if not example.created_at:
            example.created_at = datetime.utcnow().isoformat()
        
        # Validate
        is_valid, issues = example.validate()
        example.is_validated = is_valid
        example.validation_notes = "; ".join(issues) if issues else ""
        example.quality_score = 1.0 if is_valid else 0.5
        
        with sqlite3.connect(self.db_path) as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO training_examples (
                        source, source_id, job_name, error_category, error_snippet,
                        failed_stage, failed_method, tool_name,
                        root_cause, fix, category, confidence, is_retriable,
                        quality_score, is_validated, validation_notes, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    example.source,
                    example.source_id,
                    example.job_name,
                    example.error_category,
                    example.error_snippet[:5000],
                    example.failed_stage,
                    example.failed_method,
                    example.tool_name,
                    example.root_cause[:2000],
                    example.fix[:1000] if example.fix else "",
                    example.category,
                    example.confidence,
                    1 if example.is_retriable else 0,
                    example.quality_score,
                    1 if example.is_validated else 0,
                    example.validation_notes,
                    example.content_hash,
                ))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Duplicate content_hash
                logger.debug(f"Duplicate example skipped: {example.content_hash}")
                return -1
    
    def import_from_feedback(self) -> int:
        """Import training examples from feedback store."""
        try:
            from .feedback_store import FeedbackStore
            
            store = FeedbackStore()
            entries = store.get_recent(limit=10000)
            
            count = 0
            for entry in entries:
                if not entry.error_snippet or not entry.confirmed_root_cause:
                    continue
                
                example = TrainingExample(
                    source="feedback",
                    source_id=entry.id,
                    job_name=entry.job_name,
                    error_category=entry.error_category,
                    error_snippet=entry.error_snippet,
                    failed_stage=entry.failed_stage,
                    failed_method=entry.failed_method,
                    root_cause=entry.confirmed_root_cause,
                    fix=entry.confirmed_fix,
                    category=entry.error_category,
                    confidence=0.95 if entry.was_correct else 0.85,
                )
                
                if self.add_example(example) > 0:
                    count += 1
            
            logger.info(f"Imported {count} examples from feedback store")
            return count
            
        except Exception as e:
            logger.error(f"Failed to import from feedback: {e}")
            return 0
    
    def import_from_knowledge(self) -> int:
        """Import training examples from knowledge store (tool errors)."""
        try:
            from .knowledge_store import get_knowledge_store
            
            store = get_knowledge_store()
            tools = store.list_tools(limit=1000)
            
            count = 0
            for tool_summary in tools:
                tool = store.get_tool(tool_id=tool_summary.id)
                if not tool:
                    continue
                
                for error in tool.errors:
                    if not error.pattern or not error.description:
                        continue
                    
                    # Create synthetic training example from tool error
                    example = TrainingExample(
                        source="knowledge",
                        source_id=error.id,
                        tool_name=tool.name,
                        error_snippet=f"{error.code}: {error.description}",
                        root_cause=f"Tool '{tool.name}' error: {error.description}",
                        fix=error.fix or f"Check {tool.name} documentation",
                        category=error.category,
                        confidence=0.90,
                        is_retriable=error.retriable,
                    )
                    
                    if self.add_example(example) > 0:
                        count += 1
            
            logger.info(f"Imported {count} examples from knowledge store")
            return count
            
        except Exception as e:
            logger.error(f"Failed to import from knowledge: {e}")
            return 0
    
    def add_from_review(
        self,
        job_name: str,
        build_number: str,
        log_snippet: str,
        root_cause: str,
        fix: str,
        category: str = "",
    ) -> int:
        """Add training example from review queue approval."""
        example = TrainingExample(
            source="review_queue",
            source_id=f"{job_name}#{build_number}",
            job_name=job_name,
            error_snippet=log_snippet,
            root_cause=root_cause,
            fix=fix,
            category=category,
            confidence=1.0,  # Human reviewed = high confidence
            is_validated=True,
            quality_score=1.0,
        )
        
        return self.add_example(example)
    
    def get_examples(
        self,
        source: str = None,
        min_quality: float = 0.0,
        validated_only: bool = False,
        limit: int = 1000
    ) -> List[TrainingExample]:
        """Get training examples with filters."""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM training_examples WHERE quality_score >= ?"
            params = [min_quality]
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            if validated_only:
                query += " AND is_validated = 1"
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            
            examples = []
            for row in cursor.fetchall():
                examples.append(TrainingExample(
                    id=row[0],
                    source=row[1],
                    source_id=row[2],
                    job_name=row[3],
                    error_category=row[4],
                    error_snippet=row[5],
                    failed_stage=row[6],
                    failed_method=row[7],
                    tool_name=row[8],
                    root_cause=row[9],
                    fix=row[10],
                    category=row[11],
                    confidence=row[12],
                    is_retriable=bool(row[13]),
                    quality_score=row[14],
                    is_validated=bool(row[15]),
                    validation_notes=row[16],
                    content_hash=row[17],
                    created_at=row[18],
                ))
            
            return examples
    
    # =========================================================================
    # Training Jobs Management
    # =========================================================================
    
    def create_job(
        self,
        name: str,
        description: str = "",
        include_feedback: bool = True,
        include_knowledge: bool = True,
        min_quality_score: float = 0.5,
        format: str = "jsonl_openai"
    ) -> int:
        """Create a new training job."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO training_jobs (
                    name, description, include_feedback, include_knowledge,
                    min_quality_score, format
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                name,
                description,
                1 if include_feedback else 0,
                1 if include_knowledge else 0,
                min_quality_score,
                format,
            ))
            conn.commit()
            
            job_id = cursor.lastrowid
            logger.info(f"Created training job: {name} (id={job_id})")
            return job_id
    
    def get_job(self, job_id: int) -> Optional[TrainingJob]:
        """Get a training job by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM training_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return TrainingJob(
                id=row[0],
                name=row[1],
                description=row[2],
                status=row[3],
                include_feedback=bool(row[4]),
                include_knowledge=bool(row[5]),
                min_quality_score=row[6],
                format=row[7],
                total_examples=row[8],
                valid_examples=row[9],
                exported_path=row[10] or "",
                error_message=row[11] or "",
                created_at=row[12],
                started_at=row[13] or "",
                completed_at=row[14] or "",
            )
    
    def list_jobs(self, limit: int = 50) -> List[TrainingJob]:
        """List recent training jobs."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            
            jobs = []
            for row in cursor.fetchall():
                jobs.append(TrainingJob(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    status=row[3],
                    include_feedback=bool(row[4]),
                    include_knowledge=bool(row[5]),
                    min_quality_score=row[6],
                    format=row[7],
                    total_examples=row[8],
                    valid_examples=row[9],
                    exported_path=row[10] or "",
                    error_message=row[11] or "",
                    created_at=row[12],
                    started_at=row[13] or "",
                    completed_at=row[14] or "",
                ))
            
            return jobs
    
    def _update_job_status(self, job_id: int, status: str, **kwargs):
        """Update job status and optional fields."""
        with sqlite3.connect(self.db_path) as conn:
            sets = ["status = ?"]
            params = [status]
            
            if "total_examples" in kwargs:
                sets.append("total_examples = ?")
                params.append(kwargs["total_examples"])
            if "valid_examples" in kwargs:
                sets.append("valid_examples = ?")
                params.append(kwargs["valid_examples"])
            if "exported_path" in kwargs:
                sets.append("exported_path = ?")
                params.append(kwargs["exported_path"])
            if "error_message" in kwargs:
                sets.append("error_message = ?")
                params.append(kwargs["error_message"])
            if "started_at" in kwargs:
                sets.append("started_at = ?")
                params.append(kwargs["started_at"])
            if "completed_at" in kwargs:
                sets.append("completed_at = ?")
                params.append(kwargs["completed_at"])
            
            params.append(job_id)
            
            conn.execute(f"UPDATE training_jobs SET {', '.join(sets)} WHERE id = ?", params)
            conn.commit()
    
    def prepare_job(self, job_id: int) -> bool:
        """
        Prepare training data for a job.
        
        Imports data from feedback and knowledge stores based on job config.
        """
        job = self.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return False
        
        try:
            self._update_job_status(
                job_id, 
                TrainingJobStatus.PREPARING.value,
                started_at=datetime.utcnow().isoformat()
            )
            
            total = 0
            
            # Import from feedback
            if job.include_feedback:
                count = self.import_from_feedback()
                total += count
            
            # Import from knowledge
            if job.include_knowledge:
                count = self.import_from_knowledge()
                total += count
            
            # Count valid examples
            examples = self.get_examples(min_quality=job.min_quality_score)
            valid_count = len(examples)
            
            self._update_job_status(
                job_id,
                TrainingJobStatus.READY.value,
                total_examples=total,
                valid_examples=valid_count,
            )
            
            logger.info(f"Job {job_id} prepared: {total} total, {valid_count} valid examples")
            return True
            
        except Exception as e:
            logger.exception(f"Job {job_id} preparation failed: {e}")
            self._update_job_status(
                job_id,
                TrainingJobStatus.FAILED.value,
                error_message=str(e),
            )
            return False
    
    def export_job(self, job_id: int) -> Optional[str]:
        """
        Export training data for a job.
        
        Returns filepath to exported data.
        """
        job = self.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return None
        
        try:
            self._update_job_status(job_id, TrainingJobStatus.EXPORTING.value)
            
            # Get examples
            examples = self.get_examples(min_quality=job.min_quality_score)
            
            if not examples:
                raise ValueError("No training examples available")
            
            # Export based on format
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
            if job.format in [TrainingFormat.JSONL_OPENAI.value, TrainingFormat.JSONL_OLLAMA.value]:
                filename = f"training_{job.name}_{timestamp}.jsonl"
                filepath = Path(self.export_path) / filename
                content = self._export_jsonl_openai(examples)
                
            elif job.format == TrainingFormat.JSONL_ANTHROPIC.value:
                filename = f"training_{job.name}_{timestamp}.jsonl"
                filepath = Path(self.export_path) / filename
                content = self._export_jsonl_anthropic(examples)
                
            elif job.format == TrainingFormat.CSV.value:
                filename = f"training_{job.name}_{timestamp}.csv"
                filepath = Path(self.export_path) / filename
                content = self._export_csv(examples)
                
            else:  # JSON
                filename = f"training_{job.name}_{timestamp}.json"
                filepath = Path(self.export_path) / filename
                content = self._export_json(examples)
            
            # Write file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            
            self._update_job_status(
                job_id,
                TrainingJobStatus.COMPLETED.value,
                exported_path=str(filepath),
                completed_at=datetime.utcnow().isoformat(),
            )
            
            logger.info(f"Job {job_id} exported to {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.exception(f"Job {job_id} export failed: {e}")
            self._update_job_status(
                job_id,
                TrainingJobStatus.FAILED.value,
                error_message=str(e),
            )
            return None
    
    def _export_jsonl_openai(self, examples: List[TrainingExample]) -> str:
        """Export to OpenAI/Ollama JSONL format."""
        lines = []
        for ex in examples:
            lines.append(json.dumps(ex.to_openai_format()))
        return "\n".join(lines)
    
    def _export_jsonl_anthropic(self, examples: List[TrainingExample]) -> str:
        """Export to Anthropic JSONL format."""
        lines = []
        for ex in examples:
            lines.append(json.dumps(ex.to_anthropic_format()))
        return "\n".join(lines)
    
    def _export_csv(self, examples: List[TrainingExample]) -> str:
        """Export to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "id", "source", "tool_name", "error_category", "error_snippet",
            "root_cause", "fix", "category", "confidence", "is_retriable",
            "quality_score", "is_validated"
        ])
        
        # Data
        for ex in examples:
            writer.writerow([
                ex.id, ex.source, ex.tool_name, ex.error_category,
                ex.error_snippet[:500], ex.root_cause[:500], ex.fix[:200],
                ex.category, ex.confidence, ex.is_retriable,
                ex.quality_score, ex.is_validated
            ])
        
        return output.getvalue()
    
    def _export_json(self, examples: List[TrainingExample]) -> str:
        """Export to JSON format."""
        return json.dumps({
            "examples": [ex.to_dict() for ex in examples],
            "count": len(examples),
            "exported_at": datetime.utcnow().isoformat(),
        }, indent=2)
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get training pipeline statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
            validated = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE is_validated = 1"
            ).fetchone()[0]
            
            by_source = conn.execute("""
                SELECT source, COUNT(*) FROM training_examples GROUP BY source
            """).fetchall()
            
            by_category = conn.execute("""
                SELECT category, COUNT(*) FROM training_examples GROUP BY category
            """).fetchall()
            
            avg_quality = conn.execute(
                "SELECT AVG(quality_score) FROM training_examples"
            ).fetchone()[0] or 0
            
            jobs_total = conn.execute("SELECT COUNT(*) FROM training_jobs").fetchone()[0]
            jobs_completed = conn.execute(
                "SELECT COUNT(*) FROM training_jobs WHERE status = 'completed'"
            ).fetchone()[0]
            
            return {
                "total_examples": total,
                "validated_examples": validated,
                "validation_rate": validated / total if total > 0 else 0,
                "average_quality": round(avg_quality, 2),
                "by_source": dict(by_source),
                "by_category": dict(by_category),
                "total_jobs": jobs_total,
                "completed_jobs": jobs_completed,
            }


# Global instance
_pipeline: Optional[TrainingPipeline] = None


def get_training_pipeline(db_path: str = None) -> TrainingPipeline:
    """Get or create the global training pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = TrainingPipeline(db_path)
    return _pipeline