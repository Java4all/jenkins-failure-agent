"""
RC_Analyzer - Enhanced Root Cause Analysis Orchestrator

Implements the multi-call iterative AI root cause flow as specified in requirements.
Coordinates with LogParser, RootCauseFinder, AIAnalyzer, and source fetching.

Logger: jenkins-agent.rc-analyzer
"""

import logging
import json
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("jenkins-agent.rc-analyzer")


@dataclass
class RCAnalyzerConfig:
    """Configuration for RC_Analyzer."""
    max_rc_iterations: int = 3
    confidence_threshold: float = 0.7
    max_source_context_chars: int = 8000
    enabled: bool = True


@dataclass
class FunctionSignature:
    """Extracted function signature."""
    name: str
    parameters: List[str] = field(default_factory=list)
    return_type: str = ""
    raw_signature: str = ""
    file_path: str = ""
    line_number: int = 0


@dataclass
class SignatureMismatch:
    """Detected signature mismatch between call site and definition."""
    function_name: str
    called_with: List[str] = field(default_factory=list)  # Arguments at call site
    defined_as: List[str] = field(default_factory=list)   # Parameters in definition
    call_site_file: str = ""
    definition_file: str = ""
    mismatch_type: str = ""  # "argument_count", "argument_type", "missing_method"


@dataclass
class IterationResult:
    """Result from a single AI iteration."""
    iteration: int
    root_cause: str
    confidence: float
    category: str = ""
    is_retriable: bool = False
    fix: str = ""
    needs_source: List[str] = field(default_factory=list)
    raw_response: str = ""


@dataclass
class RCAnalysisResult:
    """Final result from RC_Analyzer."""
    root_cause: str
    confidence: float
    category: str
    is_retriable: bool
    fix: str
    iterations_used: int
    source_files_fetched: List[str] = field(default_factory=list)
    all_iterations: List[IterationResult] = field(default_factory=list)
    signature_mismatches: List[SignatureMismatch] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "confidence": self.confidence,
            "category": self.category,
            "is_retriable": self.is_retriable,
            "fix": self.fix,
            "iterations_used": self.iterations_used,
            "source_files_fetched": self.source_files_fetched,
        }


class RCAnalyzer:
    """
    Enhanced Root Cause Analyzer with iterative AI flow.
    
    Implements Requirements 1-8 from the requirements document:
    - Multi-call iterative analysis (up to max_rc_iterations)
    - Source code context fetching (Jenkinsfile + library files)
    - Integration with existing components (LogParser, RootCauseFinder, AIAnalyzer)
    - Source-aware error classification
    
    Usage:
        rc_analyzer = RCAnalyzer(
            ai_analyzer=ai_analyzer,
            github_client=github_client,
            config=rc_config,
        )
        result = rc_analyzer.analyze(
            parsed_log=parsed_log,
            rc_context=rc_context,
            build_info=build_info,
        )
    """
    
    # System prompt for iterative RC analysis
    SYSTEM_PROMPT = """You are an expert Jenkins CI/CD failure analyst. You analyze build failures iteratively, refining your hypothesis with each piece of evidence.

RESPONSE FORMAT (JSON only):
{
  "root_cause": "Clear, specific explanation of what failed and why",
  "category": "CREDENTIAL|NETWORK|PERMISSION|BUILD|TEST|CONFIGURATION|GROOVY_LIBRARY|GROOVY_CPS|INFRASTRUCTURE|UNKNOWN",
  "confidence": 0.0-1.0,
  "is_retriable": true|false,
  "fix": "Specific steps or commands to fix the issue",
  "needs_source": ["path/to/file.groovy"] // Optional: request additional source files
}

RULES:
- Be SPECIFIC: use exact names, IDs, paths from the evidence
- If you need source code to confirm your hypothesis, request it via "needs_source"
- Increase confidence only when you have concrete evidence
- If a library method signature doesn't match how it's called, classify as GROOVY_LIBRARY"""

    def __init__(
        self,
        ai_analyzer,  # Existing AIAnalyzer instance
        github_client=None,  # For fetching source files
        groovy_analyzer=None,  # For Groovy-specific classification
        config: Optional[RCAnalyzerConfig] = None,
    ):
        self.ai_analyzer = ai_analyzer
        self.github_client = github_client
        self.groovy_analyzer = groovy_analyzer
        self.config = config or RCAnalyzerConfig()
        
        # Library mappings from config
        self.library_mappings = {}
        if hasattr(ai_analyzer, 'config') and hasattr(ai_analyzer.config, 'github'):
            github_config = ai_analyzer.config.github
            if github_config and hasattr(github_config, 'library_mappings'):
                self.library_mappings = github_config.library_mappings or {}
    
    def analyze(
        self,
        parsed_log,  # ParsedLog from LogParser
        rc_context,  # RootCauseContext from RootCauseFinder
        build_info: Optional[Dict[str, Any]] = None,
        jenkinsfile_content: Optional[str] = None,
        library_sources: Optional[Dict[str, str]] = None,
    ) -> RCAnalysisResult:
        """
        Run iterative root cause analysis.
        
        Implements Requirement 3: Multi-Call Iterative AI Root Cause Flow
        Implements Requirement 7: Source-Aware Error Classification
        """
        logger.info(f"Starting iterative RC analysis (max_iterations={self.config.max_rc_iterations}, "
                   f"confidence_threshold={self.config.confidence_threshold})")
        
        # Initialize tracking
        iterations: List[IterationResult] = []
        source_files_fetched: List[str] = []
        best_result: Optional[IterationResult] = None
        signature_mismatches: List[SignatureMismatch] = []
        
        # Get error context for classification
        error_message = ""
        failed_method = None
        if rc_context:
            error_message = getattr(rc_context, 'error_line', '') or ''
        if parsed_log:
            failed_method = getattr(parsed_log, 'failed_method', None)
            if not error_message and hasattr(parsed_log, 'errors') and parsed_log.errors:
                error_message = parsed_log.errors[0].line if parsed_log.errors else ''
        
        # Requirement 7: Source-aware error classification
        source_category, mismatch = self.classify_with_source_context(
            error_message=error_message,
            jenkinsfile=jenkinsfile_content,
            library_sources=library_sources,
            failed_method=failed_method,
        )
        if mismatch:
            signature_mismatches.append(mismatch)
            logger.info(f"Detected signature mismatch: {mismatch.mismatch_type}")
        
        # Fetch initial source context (Requirement 2)
        source_context = self._build_source_context(
            parsed_log=parsed_log,
            jenkinsfile_content=jenkinsfile_content,
            library_sources=library_sources,
            source_files_fetched=source_files_fetched,
        )
        
        # Add signature mismatch to source context if found (Requirement 7.3)
        mismatch_context = ""
        if mismatch:
            mismatch_context = self.build_signature_comparison_prompt(mismatch)
        
        # Build initial prompt using RootCauseFinder output (Requirement 4.1)
        current_prompt = self._build_initial_prompt(
            rc_context=rc_context,
            parsed_log=parsed_log,
            build_info=build_info,
            source_context=source_context,
            mismatch_context=mismatch_context,
        )
        
        # Iterative analysis loop (Requirement 3.1)
        for iteration in range(1, self.config.max_rc_iterations + 1):
            logger.info(f"Iteration {iteration}/{self.config.max_rc_iterations}: "
                       f"current_confidence={best_result.confidence if best_result else 0}, "
                       f"source_files_fetched={len(source_files_fetched)}")
            
            # Log full prompt at DEBUG level (Requirement 8.2)
            logger.debug(f"Iteration {iteration} prompt:\n{current_prompt}")
            
            # Call AI using existing AIAnalyzer (Requirement 3.8)
            try:
                raw_response = self._call_ai(current_prompt)
                iteration_result = self._parse_iteration_response(raw_response, iteration)
            except Exception as e:
                logger.warning(f"Iteration {iteration} AI call failed: {e}")
                if best_result:
                    break
                continue
            
            iterations.append(iteration_result)
            
            # Track best result (Requirement 3.6)
            if best_result is None or iteration_result.confidence > best_result.confidence:
                best_result = iteration_result
            
            # Check if confidence threshold reached (Requirement 3.5)
            if iteration_result.confidence >= self.config.confidence_threshold:
                logger.info(f"Confidence threshold reached at iteration {iteration}: "
                           f"{iteration_result.confidence} >= {self.config.confidence_threshold}")
                break
            
            # Check if AI requested additional source files (Requirement 3.4)
            if iteration_result.needs_source and iteration < self.config.max_rc_iterations:
                additional_source = self._fetch_requested_sources(
                    iteration_result.needs_source,
                    source_files_fetched,
                )
                if additional_source:
                    source_context += f"\n\n{additional_source}"
            
            # Build follow-up prompt (Requirement 4.3)
            current_prompt = self._build_followup_prompt(
                rc_context=rc_context,
                parsed_log=parsed_log,
                build_info=build_info,
                source_context=source_context,
                previous_result=iteration_result,
            )
        
        # Build final result (Requirement 3.6)
        if best_result is None:
            best_result = IterationResult(
                iteration=0,
                root_cause="Unable to determine root cause",
                confidence=0.0,
                category="UNKNOWN",
            )
        
        # Use source-aware category if detected (Requirement 7.1)
        final_category = best_result.category
        if signature_mismatches and source_category == 'GROOVY_LIBRARY':
            final_category = 'GROOVY_LIBRARY'
            logger.info(f"Overriding category to GROOVY_LIBRARY due to signature mismatch")
        
        final_result = RCAnalysisResult(
            root_cause=best_result.root_cause,
            confidence=best_result.confidence,
            category=final_category,
            is_retriable=best_result.is_retriable,
            fix=best_result.fix,
            iterations_used=len(iterations),
            source_files_fetched=source_files_fetched,
            all_iterations=iterations,
            signature_mismatches=signature_mismatches,
        )
        
        # Log final result (Requirement 8.4)
        logger.info(f"RC analysis complete: iterations={final_result.iterations_used}, "
                   f"confidence={final_result.confidence}, "
                   f"root_cause={final_result.root_cause[:200]}...")
        
        return final_result
    
    def _build_source_context(
        self,
        parsed_log,
        jenkinsfile_content: Optional[str],
        library_sources: Optional[Dict[str, str]],
        source_files_fetched: List[str],
    ) -> str:
        """
        Build source code context for AI prompt.
        
        Implements Requirement 2: Source Code Context Fetching
        Implements Requirement 11: Automatic Source Pre-loading from Method Tags
        """
        parts = []
        total_chars = 0
        max_chars = self.config.max_source_context_chars
        
        # Add Jenkinsfile if available (Requirement 2.1)
        if jenkinsfile_content:
            truncated = self._truncate_source(jenkinsfile_content, max_chars // 2)
            parts.append(f"### JENKINSFILE ###\n{truncated}")
            total_chars += len(truncated)
            source_files_fetched.append("Jenkinsfile")
        
        # Add library sources if available (Requirement 2.2)
        if library_sources:
            for path, content in library_sources.items():
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break
                truncated = self._truncate_source(content, remaining)
                parts.append(f"### {path} ###\n{truncated}")
                total_chars += len(truncated)
                source_files_fetched.append(path)
        
        # Requirement 11: Pre-load sources for ALL active methods
        # Active methods are those that started but didn't finish
        active_methods_to_fetch = []
        if parsed_log:
            # Get active methods (Req 11.1)
            active_methods = getattr(parsed_log, 'active_methods', [])
            for method in active_methods:
                method_file = f"vars/{method}.groovy"
                if method_file not in source_files_fetched:
                    active_methods_to_fetch.append((method, method_file))
            
            # Also include failed_method if not already covered
            failed_method = getattr(parsed_log, 'failed_method', None)
            if failed_method:
                method_file = f"vars/{failed_method}.groovy"
                if method_file not in source_files_fetched and (failed_method, method_file) not in active_methods_to_fetch:
                    active_methods_to_fetch.insert(0, (failed_method, method_file))
        
        # Fetch source files for active methods (Req 11.3)
        if active_methods_to_fetch and self.github_client:
            for method_name, method_file in active_methods_to_fetch:
                remaining = max_chars - total_chars
                if remaining <= 100:  # Need meaningful space
                    break
                
                # Search across all library repos (Req 11.9, 11.10)
                content, found_path = self._search_method_source(method_name)
                if content:
                    truncated = self._truncate_source(content, min(remaining, 2000))
                    actual_path = found_path or method_file
                    parts.append(f"### {actual_path} ###\n{truncated}")
                    total_chars += len(truncated)
                    source_files_fetched.append(actual_path)
                    
                    # Extract imports for cross-library context (Req 11.11)
                    imports = self._extract_groovy_imports(content)
                    if imports:
                        logger.debug(f"Method {method_name} imports: {imports}")
                else:
                    logger.warning(f"Could not find source for method: {method_name} (Req 11.7)")
        
        if parts:
            return "## SOURCE CODE CONTEXT ##\n\n" + "\n\n".join(parts)
        return ""
    
    def _search_method_source(self, method_name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Search for method source file across all registered library repos.
        
        Implements Requirement 11.2: Search strategy
        Returns: (content, file_path) or (None, None) if not found
        """
        if not self.github_client:
            return None, None
        
        # Search patterns (Req 11.2a, 11.2b)
        search_paths = [
            f"vars/{method_name}.groovy",      # Exact match in vars/
            f"src/**/{method_name}.groovy",    # Class file in src/
        ]
        
        # Try each library mapping (Req 11.9)
        for library_name, repo_path in self.library_mappings.items():
            for search_path in search_paths:
                try:
                    # Handle glob patterns
                    if "**" in search_path:
                        # For src/**/ we need to search recursively
                        # Try common patterns
                        for src_path in [
                            f"src/com/{method_name}.groovy",
                            f"src/org/{method_name}.groovy",
                            f"src/{method_name}.groovy",
                        ]:
                            content = self.github_client.get_file_content(repo_path, src_path)
                            if content:
                                logger.debug(f"Found {method_name} at {repo_path}:{src_path}")
                                return content, src_path
                    else:
                        content = self.github_client.get_file_content(repo_path, search_path)
                        if content:
                            logger.debug(f"Found {method_name} at {repo_path}:{search_path}")
                            return content, search_path
                except Exception as e:
                    logger.debug(f"Could not fetch {search_path} from {repo_path}: {e}")
                    continue
        
        return None, None
    
    def _extract_groovy_imports(self, content: str) -> List[str]:
        """Extract import statements from Groovy source (Req 11.11)."""
        imports = []
        import_pattern = re.compile(r'^import\s+([a-zA-Z0-9_.]+)', re.MULTILINE)
        for match in import_pattern.finditer(content):
            imports.append(match.group(1))
        return imports
    
    def _fetch_library_file(self, file_path: str) -> Optional[str]:
        """
        Fetch a library file from GitHub.
        
        Implements Requirement 2.4: Handle fetch failures gracefully
        """
        if not self.github_client:
            return None
        
        try:
            # Try each library mapping (Requirement 2.6)
            for library_name, repo_path in self.library_mappings.items():
                try:
                    content = self.github_client.get_file_content(repo_path, file_path)
                    if content:
                        logger.debug(f"Fetched {file_path} from {repo_path}")
                        return content
                except Exception as e:
                    logger.debug(f"Could not fetch {file_path} from {repo_path}: {e}")
                    continue
            
            # Try default repo if no mapping matched
            if hasattr(self.github_client, 'default_repo'):
                return self.github_client.get_file_content(self.github_client.default_repo, file_path)
        except Exception as e:
            logger.warning(f"Failed to fetch library file {file_path}: {e}")
        
        return None
    
    def _fetch_requested_sources(
        self,
        requested_files: List[str],
        already_fetched: List[str],
    ) -> str:
        """Fetch source files requested by AI in previous iteration."""
        parts = []
        
        for file_path in requested_files:
            if file_path in already_fetched:
                continue
            
            content = self._fetch_library_file(file_path)
            if content:
                truncated = self._truncate_source(content, 2000)
                parts.append(f"### {file_path} ###\n{truncated}")
                already_fetched.append(file_path)
        
        if parts:
            return "## ADDITIONAL SOURCE CODE (requested) ##\n\n" + "\n\n".join(parts)
        return ""
    
    def _truncate_source(self, content: str, max_chars: int) -> str:
        """Truncate source content to max_chars (Requirement 2.5)."""
        if len(content) <= max_chars:
            return content
        
        # Keep first and last parts
        half = max_chars // 2 - 20
        return content[:half] + "\n\n... [truncated] ...\n\n" + content[-half:]
    
    def _build_initial_prompt(
        self,
        rc_context,
        parsed_log,
        build_info: Optional[Dict[str, Any]],
        source_context: str,
        mismatch_context: str = "",
    ) -> str:
        """
        Build the initial prompt for first iteration.
        
        Implements Requirement 4.1: Use RootCauseFinder output
        Implements Requirement 4.2: Append SOURCE CODE CONTEXT section
        Implements Requirement 7.3: Include signature mismatch comparison
        Implements Requirement 11.12: Include METHOD CALL SEQUENCE
        Implements Requirement 13.7: Include PIPELINE STAGE SEQUENCE
        """
        parts = []
        
        # Build info
        if build_info:
            parts.append(f"JOB: {build_info.get('job_name', 'unknown')} #{build_info.get('build_number', '?')}")
        
        # Failed method info
        if parsed_log and hasattr(parsed_log, 'failed_method') and parsed_log.failed_method:
            parts.append(f"FAILED METHOD: {parsed_log.failed_method}")
        
        # Pipeline stage sequence (Requirement 13.7)
        if parsed_log and hasattr(parsed_log, 'stage_sequence') and parsed_log.stage_sequence:
            parts.append("\n## PIPELINE STAGE SEQUENCE ##")
            parts.append("Stages executed in order (failure occurred in last stage):")
            for i, stage in enumerate(parsed_log.stage_sequence, 1):
                marker = " <-- FAILED" if i == len(parsed_log.stage_sequence) else ""
                parts.append(f"  {i}. {stage}{marker}")
        
        # Method call sequence (Requirement 11.12)
        if parsed_log and hasattr(parsed_log, 'method_call_sequence') and parsed_log.method_call_sequence:
            parts.append("\n## METHOD CALL SEQUENCE ##")
            parts.append("Library methods called in order (via method tags):")
            active_methods = set(getattr(parsed_log, 'active_methods', []))
            for i, method in enumerate(parsed_log.method_call_sequence, 1):
                marker = " <-- ACTIVE (did not finish)" if method in active_methods else ""
                parts.append(f"  {i}. {method}{marker}")
        
        # Signature mismatch context (Requirement 7.3) - add early for visibility
        if mismatch_context:
            parts.append("\n" + mismatch_context)
        
        # RootCauseFinder context (Requirement 4.1)
        if rc_context and hasattr(rc_context, 'get_ai_prompt_context'):
            parts.append("\n## ERROR CONTEXT ##")
            parts.append(rc_context.get_ai_prompt_context())
        
        # Source code context (Requirement 4.2)
        if source_context:
            parts.append("\n" + source_context)
        
        # Function signature if available (Requirement 7.2)
        if parsed_log and hasattr(parsed_log, 'failed_method') and parsed_log.failed_method:
            signature = self.extract_function_signature(source_context, parsed_log.failed_method)
            if signature:
                parts.append(f"\n## FUNCTION SIGNATURE ##\n{signature.raw_signature}")
        
        parts.append("\nAnalyze the above and provide root cause analysis.")
        
        return "\n".join(parts)
    
    def _build_followup_prompt(
        self,
        rc_context,
        parsed_log,
        build_info: Optional[Dict[str, Any]],
        source_context: str,
        previous_result: IterationResult,
    ) -> str:
        """
        Build follow-up prompt for subsequent iterations.
        
        Implements Requirement 4.3: Include PREVIOUS ANALYSIS section
        """
        parts = []
        
        # Previous analysis summary (Requirement 4.3)
        parts.append("## PREVIOUS ANALYSIS ##")
        parts.append(f"Root Cause: {previous_result.root_cause}")
        parts.append(f"Confidence: {previous_result.confidence}")
        parts.append(f"Category: {previous_result.category}")
        if previous_result.fix:
            parts.append(f"Suggested Fix: {previous_result.fix}")
        parts.append("")
        
        # Instruction for refinement
        parts.append("The previous analysis had low confidence. Review the evidence again:")
        parts.append("")
        
        # Add original context
        initial_prompt = self._build_initial_prompt(rc_context, parsed_log, build_info, source_context)
        parts.append(initial_prompt)
        
        parts.append("\nRefine your analysis based on all available evidence. "
                    "If you need more source files to confirm, list them in 'needs_source'.")
        
        return "\n".join(parts)
    
    def _extract_function_signature(self, method_name: str, source_context: str) -> Optional[str]:
        """
        Extract function signature from source context.
        
        Implements Requirement 7.2: Include actual parameter list
        """
        if not source_context:
            return None
        
        # Look for def call(...) or def methodName(...)
        patterns = [
            rf'def\s+call\s*\([^)]*\)',
            rf'def\s+{re.escape(method_name)}\s*\([^)]*\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, source_context, re.MULTILINE)
            if match:
                return match.group(0)
        
        return None
    
    def _call_ai(self, prompt: str) -> str:
        """
        Call AI using existing AIAnalyzer.
        
        Implements Requirement 3.8: Reuse existing _call_ai method
        """
        # Use the AIAnalyzer's client directly
        response = self.ai_analyzer.client.chat.completions.create(
            model=self.ai_analyzer.config.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        return response.choices[0].message.content
    
    def _parse_iteration_response(self, raw_response: str, iteration: int) -> IterationResult:
        """
        Parse AI response for an iteration.
        
        Implements Requirement 8.3: Log parse failures at WARNING level
        """
        try:
            # Clean response
            response = raw_response.strip()
            if response.startswith('```'):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            data = json.loads(response)
            
            return IterationResult(
                iteration=iteration,
                root_cause=data.get('root_cause', ''),
                confidence=float(data.get('confidence', 0)),
                category=data.get('category', 'UNKNOWN'),
                is_retriable=data.get('is_retriable', False),
                fix=data.get('fix', ''),
                needs_source=data.get('needs_source', []),
                raw_response=raw_response,
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Iteration {iteration}: Failed to parse AI response as JSON: {e}")
            logger.warning(f"Raw response: {raw_response[:500]}...")
            
            # Try to extract root cause from raw text
            return IterationResult(
                iteration=iteration,
                root_cause=raw_response[:500] if raw_response else "Parse error",
                confidence=0.3,
                category="UNKNOWN",
                raw_response=raw_response,
            )
        except Exception as e:
            logger.warning(f"Iteration {iteration}: Error parsing response: {e}")
            return IterationResult(
                iteration=iteration,
                root_cause=str(e),
                confidence=0.0,
                category="UNKNOWN",
                raw_response=raw_response,
            )
    
    # =========================================================================
    # Requirement 7: Source-Aware Error Classification
    # =========================================================================
    
    def extract_function_signature(self, source_code: str, function_name: str) -> Optional[FunctionSignature]:
        """
        Extract function signature from Groovy source code.
        
        Implements Requirement 7.2: Extract def call(...) signature
        """
        if not source_code or not function_name:
            return None
        
        # Pattern for def call(...) or def functionName(...)
        patterns = [
            # def call(Map config, String name) - with types
            rf'def\s+(?:call|{re.escape(function_name)})\s*\(([^)]*)\)',
            # def call(config, name) - without types  
            rf'def\s+(?:call|{re.escape(function_name)})\s*\(\s*([^)]*)\s*\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, source_code, re.MULTILINE | re.DOTALL)
            if match:
                params_str = match.group(1).strip()
                parameters = self._parse_parameters(params_str)
                
                return FunctionSignature(
                    name=function_name,
                    parameters=parameters,
                    raw_signature=match.group(0),
                )
        
        return None
    
    def _parse_parameters(self, params_str: str) -> List[str]:
        """Parse parameter list from signature string."""
        if not params_str:
            return []
        
        # Handle multi-line and complex parameters
        params_str = re.sub(r'\s+', ' ', params_str.strip())
        
        parameters = []
        depth = 0
        current = ""
        
        for char in params_str:
            if char in '([<':
                depth += 1
                current += char
            elif char in ')]>':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                if current.strip():
                    parameters.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            parameters.append(current.strip())
        
        return parameters
    
    def extract_call_site(self, jenkinsfile: str, function_name: str) -> Optional[Tuple[List[str], int]]:
        """
        Extract how a function is called from Jenkinsfile.
        
        Returns (arguments, line_number) or None
        """
        if not jenkinsfile or not function_name:
            return None
        
        # Pattern for function call: functionName(...) or functionName { }
        patterns = [
            # functionName(arg1, arg2)
            rf'{re.escape(function_name)}\s*\(([^)]*)\)',
            # functionName arg1, arg2
            rf'{re.escape(function_name)}\s+([^{{)\n]+)',
            # functionName { closure }
            rf'{re.escape(function_name)}\s*\{{',
        ]
        
        for i, line in enumerate(jenkinsfile.split('\n'), 1):
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    if match.lastindex and match.group(1):
                        args = self._parse_parameters(match.group(1))
                        return (args, i)
                    else:
                        return ([], i)  # Closure-style call
        
        return None
    
    def detect_signature_mismatch(
        self,
        jenkinsfile: Optional[str],
        library_sources: Optional[Dict[str, str]],
        failed_method: Optional[str],
        error_message: str,
    ) -> Optional[SignatureMismatch]:
        """
        Detect signature mismatch between call site and definition.
        
        Implements Requirement 7.1: Detect mismatches and classify as GROOVY_LIBRARY
        Implements Requirement 7.3: Structured comparison for MissingMethodException
        """
        if not failed_method:
            return None
        
        # Check if this is a MissingMethodException
        is_missing_method = any(kw in error_message.lower() for kw in [
            'missingmethodexception',
            'no signature of method',
            'missing method',
        ])
        
        # Extract signature from library source
        library_signature = None
        source_file = None
        if library_sources:
            for path, content in library_sources.items():
                if failed_method in path or path.endswith(f"{failed_method}.groovy"):
                    library_signature = self.extract_function_signature(content, failed_method)
                    source_file = path
                    break
        
        # Extract call site from Jenkinsfile
        call_info = None
        if jenkinsfile:
            call_info = self.extract_call_site(jenkinsfile, failed_method)
        
        # Compare signatures
        if library_signature and call_info:
            called_args, call_line = call_info
            defined_params = library_signature.parameters
            
            # Check for argument count mismatch
            if len(called_args) != len(defined_params):
                return SignatureMismatch(
                    function_name=failed_method,
                    called_with=called_args,
                    defined_as=defined_params,
                    call_site_file="Jenkinsfile",
                    definition_file=source_file or f"vars/{failed_method}.groovy",
                    mismatch_type="argument_count",
                )
        
        # If MissingMethodException but we have the source, still report
        if is_missing_method and library_signature:
            return SignatureMismatch(
                function_name=failed_method,
                called_with=call_info[0] if call_info else [],
                defined_as=library_signature.parameters,
                call_site_file="Jenkinsfile",
                definition_file=source_file or f"vars/{failed_method}.groovy",
                mismatch_type="missing_method",
            )
        
        return None
    
    def build_signature_comparison_prompt(self, mismatch: SignatureMismatch) -> str:
        """
        Build structured comparison for AI prompt.
        
        Implements Requirement 7.3: Structured comparison in prompt
        """
        lines = [
            "## SIGNATURE MISMATCH DETECTED ##",
            f"Function: {mismatch.function_name}",
            f"Mismatch Type: {mismatch.mismatch_type}",
            "",
            f"CALLED WITH ({mismatch.call_site_file}):",
            f"  {mismatch.function_name}({', '.join(mismatch.called_with) if mismatch.called_with else '...'})",
            "",
            f"DEFINED AS ({mismatch.definition_file}):",
            f"  def call({', '.join(mismatch.defined_as) if mismatch.defined_as else '...'})",
            "",
        ]
        
        if mismatch.mismatch_type == "argument_count":
            lines.append(f"ERROR: Called with {len(mismatch.called_with)} arguments, "
                        f"but function expects {len(mismatch.defined_as)} parameters")
        elif mismatch.mismatch_type == "missing_method":
            lines.append("ERROR: Method signature does not match the call")
        
        return '\n'.join(lines)
    
    def classify_with_source_context(
        self,
        error_message: str,
        jenkinsfile: Optional[str],
        library_sources: Optional[Dict[str, str]],
        failed_method: Optional[str],
    ) -> Tuple[str, Optional[SignatureMismatch]]:
        """
        Classify error using source code context.
        
        Implements Requirement 7.1: Classify as GROOVY_LIBRARY if mismatch detected
        Implements Requirement 7.4: Reuse GroovyAnalyzer for classification
        """
        # First try GroovyAnalyzer if available
        base_category = "UNKNOWN"
        if self.groovy_analyzer:
            try:
                groovy_result = self.groovy_analyzer.analyze(error_message)
                if groovy_result and hasattr(groovy_result, 'primary_failure_type'):
                    groovy_type = groovy_result.primary_failure_type.value
                    # Map to RC categories
                    type_mapping = {
                        'missing_method': 'GROOVY_LIBRARY',
                        'missing_property': 'GROOVY_LIBRARY',
                        'cps_transformation': 'GROOVY_CPS',
                        'serialization': 'GROOVY_SERIALIZATION',
                        'sandbox_rejection': 'GROOVY_SANDBOX',
                    }
                    base_category = type_mapping.get(groovy_type, 'UNKNOWN')
            except Exception as e:
                logger.debug(f"GroovyAnalyzer failed: {e}")
        
        # Try to detect signature mismatch
        mismatch = self.detect_signature_mismatch(
            jenkinsfile=jenkinsfile,
            library_sources=library_sources,
            failed_method=failed_method,
            error_message=error_message,
        )
        
        # If mismatch found, override category (Requirement 7.1)
        if mismatch:
            logger.info(f"Signature mismatch detected: {mismatch.function_name} - {mismatch.mismatch_type}")
            return 'GROOVY_LIBRARY', mismatch
        
        return base_category, None
