"""
Groovy and Jenkins Shared Library analyzer.

Specializes in:
- CPS (Continuation Passing Style) stack trace decoding
- Shared library structure parsing
- Pipeline execution graph reconstruction
- Sandbox and serialization error analysis
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from pathlib import Path


class GroovyFailureType(Enum):
    """Categories of Groovy/Pipeline failures."""
    SANDBOX_REJECTION = "sandbox_rejection"
    CPS_TRANSFORMATION = "cps_transformation"
    SERIALIZATION = "serialization"
    MISSING_METHOD = "missing_method"
    MISSING_PROPERTY = "missing_property"
    LIBRARY_LOAD = "library_load"
    LIBRARY_VERSION = "library_version"
    STEP_EXECUTION = "step_execution"
    SCRIPT_APPROVAL = "script_approval"
    CLASS_NOT_FOUND = "class_not_found"
    TYPE_MISMATCH = "type_mismatch"
    NULL_POINTER = "null_pointer"
    COMPILATION = "compilation"
    SYNTAX = "syntax"
    UNKNOWN = "unknown"


@dataclass
class LibraryReference:
    """A shared library reference from Jenkinsfile."""
    name: str
    version: str = ""  # branch, tag, or commit
    implicit: bool = False
    changelog: bool = True
    retriever: str = ""  # SCM retriever type
    source_line: int = 0
    raw_declaration: str = ""


@dataclass
class LibraryFunction:
    """A function from a shared library."""
    name: str
    file_path: str  # vars/myFunc.groovy or src/com/example/MyClass.groovy
    line_number: int = 0
    is_global_var: bool = False  # vars/ functions are global variables
    parameters: List[str] = field(default_factory=list)
    called_from: List[str] = field(default_factory=list)  # Call sites


@dataclass
class CPSFrame:
    """A decoded CPS stack trace frame."""
    class_name: str
    method_name: str
    file_name: str = ""
    line_number: int = 0
    is_pipeline_step: bool = False
    is_library_code: bool = False
    library_name: str = ""
    original_frame: str = ""
    cps_specific: bool = False  # True if this is CPS machinery


@dataclass
class GroovyError:
    """A parsed Groovy/Pipeline error."""
    error_type: GroovyFailureType
    message: str
    exception_class: str = ""
    target_class: str = ""  # Class/method that was being accessed
    target_method: str = ""
    target_property: str = ""
    required_approval: str = ""  # For sandbox rejections
    pipeline_stage: str = ""
    library_context: str = ""  # Which library function if known
    line_number: int = 0
    file_path: str = ""
    cps_frames: List[CPSFrame] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class PipelineExecutionNode:
    """A node in the pipeline execution graph."""
    node_id: str
    node_type: str  # stage, parallel, node, step, library_call
    name: str
    parent_id: str = ""
    status: str = ""  # SUCCESS, FAILURE, RUNNING, NOT_BUILT
    duration_ms: int = 0
    log_start_line: int = 0
    log_end_line: int = 0
    library_calls: List[str] = field(default_factory=list)


@dataclass
class SourceToolInvocation:
    """
    A tool invocation detected in source code (Requirement 17.9).
    
    Used to identify tools called within sh() steps in Jenkinsfile
    or shared library methods.
    """
    tool_name: str
    command_template: str  # The command as written (may contain variables)
    source_file: str
    line_number: int
    enclosing_method: str = ""  # Method/function that contains this sh() call
    is_in_sh_step: bool = True
    variables_used: List[str] = field(default_factory=list)  # Variables in command
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "command_template": self.command_template,
            "source_file": self.source_file,
            "line_number": self.line_number,
            "enclosing_method": self.enclosing_method,
            "is_in_sh_step": self.is_in_sh_step,
            "variables_used": self.variables_used,
        }


@dataclass
class GroovyAnalysis:
    """Complete Groovy/Pipeline analysis result."""
    failure_type: GroovyFailureType
    errors: List[GroovyError] = field(default_factory=list)
    library_references: List[LibraryReference] = field(default_factory=list)
    library_functions_called: List[LibraryFunction] = field(default_factory=list)
    execution_path: List[PipelineExecutionNode] = field(default_factory=list)
    root_cause_function: Optional[LibraryFunction] = None
    decoded_cps_trace: List[CPSFrame] = field(default_factory=list)
    configuration_issues: List[str] = field(default_factory=list)
    summary: str = ""
    # Requirement 17.9: Tool invocations detected in source code
    source_tool_invocations: List[SourceToolInvocation] = field(default_factory=list)


class GroovyAnalyzer:
    """
    Analyzer for Groovy and Jenkins Shared Library errors.
    
    This analyzer specializes in decoding the cryptic error messages
    produced by Jenkins Pipeline's CPS transformation and sandbox.
    """
    
    # CPS-specific class patterns to identify pipeline machinery
    CPS_MACHINERY_PATTERNS = [
        r"org\.jenkinsci\.plugins\.workflow\.cps\.CpsCallableInvocation",
        r"org\.jenkinsci\.plugins\.workflow\.cps\.CpsScript",
        r"org\.jenkinsci\.plugins\.workflow\.cps\.CpsThread",
        r"org\.jenkinsci\.plugins\.workflow\.cps\.CpsFlowExecution",
        r"org\.jenkinsci\.plugins\.workflow\.cps\.DSL",
        r"org\.jenkinsci\.plugins\.workflow\.cps\.CpsBodyExecution",
        r"com\.cloudbees\.groovy\.cps\.CpsTransformedInvocation",
        r"com\.cloudbees\.groovy\.cps\.Continuable",
        r"com\.cloudbees\.groovy\.cps\.impl\.",
        r"sun\.reflect\.",
        r"java\.lang\.reflect\.",
        r"org\.codehaus\.groovy\.runtime\.callsite\.",
    ]
    
    # Pipeline step patterns
    PIPELINE_STEP_PATTERNS = [
        r"org\.jenkinsci\.plugins\.workflow\.steps\.",
        r"org\.jenkinsci\.plugins\.pipeline\.",
        r"hudson\.plugins\.",
    ]
    
    # Error patterns for different Groovy failure types
    ERROR_PATTERNS = {
        GroovyFailureType.SANDBOX_REJECTION: [
            r"Scripts not permitted to use (?:method|staticMethod|new|field)\s+(.+)",
            r"RejectedAccessException:\s*(.+)",
            r"org\.jenkinsci\.plugins\.scriptsecurity\.sandbox\.RejectedAccessException",
            r"Scripts not permitted to use\s+(.+)",
        ],
        GroovyFailureType.CPS_TRANSFORMATION: [
            r"CpsCallableInvocation.*expecting closure",
            r"expected to call.*but wound up catching",
            r"CPS-transformed.*cannot be invoked",
            r"cannot be CPS transformed",
            r"Continuation passing style",
        ],
        GroovyFailureType.SERIALIZATION: [
            r"java\.io\.NotSerializableException:\s*(.+)",
            r"Unable to serialize",
            r"cannot be serialized",
            r"Caused by: an exception which occurred",
            r"Expected to find a CPS-transformed",
        ],
        GroovyFailureType.MISSING_METHOD: [
            r"groovy\.lang\.MissingMethodException:\s*No signature of method:\s*(.+)",
            r"java\.lang\.NoSuchMethodError:\s*(.+)",
            r"No signature of method",
            r"MissingMethodException",
        ],
        GroovyFailureType.MISSING_PROPERTY: [
            r"groovy\.lang\.MissingPropertyException:\s*No such property:\s*(\w+)",
            r"MissingPropertyException:\s*(.+)",
            r"No such property:",
            r"Cannot get property\s+'(\w+)'",
        ],
        GroovyFailureType.LIBRARY_LOAD: [
            r"Unable to find source for class\s+(.+)",
            r"@Library\s*\(\s*['\"](.+?)['\"]\s*\).*not found",
            r"Could not find shared library",
            r"ERROR: Could not resolve SCM from",
            r"Library\s+(.+)\s+does not exist",
            r"checkout .* failed",
        ],
        GroovyFailureType.LIBRARY_VERSION: [
            r"Branch\s+(.+)\s+not found",
            r"Tag\s+(.+)\s+not found",
            r"Unable to checkout revision",
            r"pathspec '(.+)' did not match",
            r"Couldn't find any revision to build",
        ],
        GroovyFailureType.STEP_EXECUTION: [
            r"hudson\.AbortException:\s*(.+)",
            r"FlowInterruptedException",
            r"Step\s+'(.+)'\s+failed",
            r"Required context class\s+(.+)\s+is missing",
        ],
        GroovyFailureType.SCRIPT_APPROVAL: [
            r"Waiting for approval",
            r"Administrator approval is required",
            r"script-security sandbox",
        ],
        GroovyFailureType.CLASS_NOT_FOUND: [
            r"java\.lang\.ClassNotFoundException:\s*(.+)",
            r"Unable to resolve class\s+(.+)",
            r"ClassNotFoundException",
            r"NoClassDefFoundError:\s*(.+)",
        ],
        GroovyFailureType.TYPE_MISMATCH: [
            r"GroovyCastException:\s*(.+)",
            r"Cannot cast object\s+(.+)\s+to class",
            r"ClassCastException:\s*(.+)",
            r"Argument type mismatch",
        ],
        GroovyFailureType.NULL_POINTER: [
            r"java\.lang\.NullPointerException",
            r"Cannot invoke method\s+(\w+)\s+on null object",
            r"Cannot get property\s+'(\w+)'\s+on null object",
        ],
        GroovyFailureType.COMPILATION: [
            r"org\.codehaus\.groovy\.control\.MultipleCompilationErrorsException",
            r"startup failed:",
            r"BUG! exception in phase 'semantic analysis'",
            r"Compilation incomplete",
        ],
        GroovyFailureType.SYNTAX: [
            r"unexpected token:",
            r"expecting\s+'([^']+)'",
            r"SyntaxException:",
            r"unable to resolve class",
        ],
    }
    
    # Pattern to extract @Library declarations
    LIBRARY_DECLARATION_PATTERNS = [
        # @Library('my-lib@branch') _
        r"@Library\s*\(\s*['\"]([^'\"@]+)(?:@([^'\"]+))?\s*['\"]\s*\)\s*_?",
        # @Library(['lib1', 'lib2@v1'])
        r"@Library\s*\(\s*\[([^\]]+)\]\s*\)",
        # library 'my-lib@branch'
        r"library\s+['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]",
        # library identifier: 'my-lib@branch'
        r"library\s+identifier:\s*['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]",
    ]
    
    # Pattern for pipeline stages
    STAGE_PATTERNS = [
        r"\[Pipeline\]\s*{\s*\(([^)]+)\)",
        r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"Entering stage\s+([^\n]+)",
        r"\[([^\]]+)\]\s+Running",
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self.compiled_cps_patterns = [
            re.compile(p) for p in self.CPS_MACHINERY_PATTERNS
        ]
        self.compiled_step_patterns = [
            re.compile(p) for p in self.PIPELINE_STEP_PATTERNS
        ]
    
    def analyze(
        self,
        log_content: str,
        jenkinsfile_content: Optional[str] = None,
        library_sources: Optional[Dict[str, str]] = None,
    ) -> GroovyAnalysis:
        """
        Perform comprehensive Groovy/Pipeline analysis.
        
        Args:
            log_content: Jenkins console log
            jenkinsfile_content: Optional Jenkinsfile source
            library_sources: Optional dict of library file paths to contents
        """
        result = GroovyAnalysis(failure_type=GroovyFailureType.UNKNOWN)
        
        # Extract library references from Jenkinsfile
        if jenkinsfile_content:
            result.library_references = self._extract_library_refs(jenkinsfile_content)
        
        # Also try to extract from log (library loading messages)
        result.library_references.extend(self._extract_library_refs_from_log(log_content))
        
        # Parse Groovy errors from log
        result.errors = self._extract_groovy_errors(log_content)
        
        # Decode CPS stack traces
        result.decoded_cps_trace = self._decode_cps_stack_traces(log_content)
        
        # Reconstruct execution path
        result.execution_path = self._reconstruct_execution_path(log_content)
        
        # Identify library functions involved
        result.library_functions_called = self._identify_library_functions(
            log_content, library_sources or {}
        )
        
        # Determine primary failure type
        result.failure_type = self._determine_failure_type(result.errors)
        
        # Find root cause function
        result.root_cause_function = self._find_root_cause_function(
            result.errors, result.library_functions_called, result.decoded_cps_trace
        )
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        return result
    
    def _extract_library_refs(self, jenkinsfile: str) -> List[LibraryReference]:
        """Extract @Library declarations from Jenkinsfile."""
        refs = []
        
        for pattern in self.LIBRARY_DECLARATION_PATTERNS:
            for match in re.finditer(pattern, jenkinsfile, re.MULTILINE):
                groups = match.groups()
                
                # Handle array syntax
                if "[" in pattern:
                    # Parse library array
                    lib_array = groups[0]
                    for lib_match in re.finditer(r"['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]", lib_array):
                        refs.append(LibraryReference(
                            name=lib_match.group(1),
                            version=lib_match.group(2) or "master",
                            raw_declaration=match.group(0),
                            source_line=jenkinsfile[:match.start()].count('\n') + 1,
                        ))
                else:
                    refs.append(LibraryReference(
                        name=groups[0],
                        version=groups[1] if len(groups) > 1 and groups[1] else "master",
                        raw_declaration=match.group(0),
                        source_line=jenkinsfile[:match.start()].count('\n') + 1,
                    ))
        
        return refs
    
    def _extract_library_refs_from_log(self, log_content: str) -> List[LibraryReference]:
        """Extract library references from log loading messages."""
        refs = []
        
        patterns = [
            r"Loading library\s+([^@\s]+)@([^\s]+)",
            r"Obtained\s+([^@\s]+)\.groovy\s+from\s+git",
            r"Attempting to resolve\s+([^@\s]+)@([^\s]+)",
            r"Selected\s+Git:\s+([^\s]+)\s+for\s+library\s+([^@\s]+)",
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, log_content):
                groups = match.groups()
                lib_name = groups[0] if groups else ""
                version = groups[1] if len(groups) > 1 else "master"
                
                # Avoid duplicates
                if not any(r.name == lib_name for r in refs):
                    refs.append(LibraryReference(
                        name=lib_name,
                        version=version,
                    ))
        
        return refs
    
    def _extract_groovy_errors(self, log_content: str) -> List[GroovyError]:
        """Extract and categorize Groovy errors from log."""
        errors = []
        
        for error_type, patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    error = GroovyError(
                        error_type=error_type,
                        message=match.group(0),
                    )
                    
                    # Extract additional details based on error type
                    if error_type == GroovyFailureType.SANDBOX_REJECTION:
                        error = self._parse_sandbox_rejection(match, error, log_content)
                    elif error_type == GroovyFailureType.MISSING_METHOD:
                        error = self._parse_missing_method(match, error)
                    elif error_type == GroovyFailureType.MISSING_PROPERTY:
                        error = self._parse_missing_property(match, error)
                    elif error_type == GroovyFailureType.SERIALIZATION:
                        error = self._parse_serialization_error(match, error, log_content)
                    
                    # Find pipeline stage context
                    error.pipeline_stage = self._find_stage_context(
                        log_content, match.start()
                    )
                    
                    # Add suggestions
                    error.suggestions = self._generate_error_suggestions(error)
                    
                    errors.append(error)
        
        return errors
    
    def _parse_sandbox_rejection(
        self, match: re.Match, error: GroovyError, log_content: str
    ) -> GroovyError:
        """Parse details from a sandbox rejection error."""
        text = match.group(0)
        
        # Extract what was rejected
        method_match = re.search(
            r"(?:method|staticMethod)\s+(\S+)\s+(\w+)", text
        )
        if method_match:
            error.target_class = method_match.group(1)
            error.target_method = method_match.group(2)
            error.required_approval = f"method {error.target_class} {error.target_method}"
        
        field_match = re.search(r"field\s+(\S+)\s+(\w+)", text)
        if field_match:
            error.target_class = field_match.group(1)
            error.target_property = field_match.group(2)
            error.required_approval = f"field {error.target_class} {error.target_property}"
        
        new_match = re.search(r"new\s+(\S+)", text)
        if new_match:
            error.target_class = new_match.group(1)
            error.required_approval = f"new {error.target_class}"
        
        return error
    
    def _parse_missing_method(self, match: re.Match, error: GroovyError) -> GroovyError:
        """Parse details from a missing method error."""
        text = match.group(0)
        
        # Pattern: No signature of method: ClassName.methodName()
        sig_match = re.search(r"No signature of method:\s+(\S+)\.(\w+)\(", text)
        if sig_match:
            error.target_class = sig_match.group(1)
            error.target_method = sig_match.group(2)
        
        # Extract argument types if present
        args_match = re.search(r"Possible solutions:\s*(.+)", text, re.DOTALL)
        if args_match:
            error.suggestions.append(f"Suggested methods: {args_match.group(1)[:200]}")
        
        return error
    
    def _parse_missing_property(self, match: re.Match, error: GroovyError) -> GroovyError:
        """Parse details from a missing property error."""
        text = match.group(0)
        
        prop_match = re.search(r"No such property:\s*(\w+)\s+for class:\s*(\S+)", text)
        if prop_match:
            error.target_property = prop_match.group(1)
            error.target_class = prop_match.group(2)
        else:
            # Simpler pattern
            prop_match = re.search(r"property\s+'?(\w+)'?", text, re.IGNORECASE)
            if prop_match:
                error.target_property = prop_match.group(1)
        
        return error
    
    def _parse_serialization_error(
        self, match: re.Match, error: GroovyError, log_content: str
    ) -> GroovyError:
        """Parse details from a serialization error."""
        text = match.group(0)
        
        # Extract the non-serializable class
        class_match = re.search(r"NotSerializableException:\s*(\S+)", text)
        if class_match:
            error.target_class = class_match.group(1)
            error.suggestions.append(
                f"Mark variable as @NonCPS or make {error.target_class} serializable"
            )
            error.suggestions.append(
                "Move the non-serializable object usage into a @NonCPS method"
            )
        
        return error
    
    def _decode_cps_stack_traces(self, log_content: str) -> List[CPSFrame]:
        """Decode CPS stack traces to human-readable form."""
        frames = []
        
        # Match Java/Groovy stack trace patterns
        stack_pattern = re.compile(
            r"\s+at\s+(?P<class>[\w.$]+)\.(?P<method>[\w$<>]+)\((?P<location>[^)]+)\)"
        )
        
        for match in stack_pattern.finditer(log_content):
            class_name = match.group("class")
            method_name = match.group("method")
            location = match.group("location")
            
            # Parse location (FileName.groovy:123 or Native Method)
            file_name = ""
            line_number = 0
            loc_match = re.match(r"(\S+):(\d+)", location)
            if loc_match:
                file_name = loc_match.group(1)
                line_number = int(loc_match.group(2))
            
            frame = CPSFrame(
                class_name=class_name,
                method_name=method_name,
                file_name=file_name,
                line_number=line_number,
                original_frame=match.group(0),
            )
            
            # Check if this is CPS machinery (to filter out)
            frame.cps_specific = any(
                p.search(class_name) for p in self.compiled_cps_patterns
            )
            
            # Check if this is a pipeline step
            frame.is_pipeline_step = any(
                p.search(class_name) for p in self.compiled_step_patterns
            )
            
            # Check if this is library code
            if ".vars." in class_name or "WorkflowScript" in class_name:
                frame.is_library_code = True
                # Try to extract library name
                lib_match = re.search(r"([\w-]+)\.vars\.(\w+)", class_name)
                if lib_match:
                    frame.library_name = lib_match.group(1)
            
            frames.append(frame)
        
        return frames
    
    def _reconstruct_execution_path(self, log_content: str) -> List[PipelineExecutionNode]:
        """Reconstruct the pipeline execution graph from log."""
        nodes = []
        
        # Track stages
        for pattern in self.STAGE_PATTERNS:
            for match in re.finditer(pattern, log_content):
                stage_name = match.group(1) if match.groups() else "unknown"
                
                node = PipelineExecutionNode(
                    node_id=f"stage_{len(nodes)}",
                    node_type="stage",
                    name=stage_name,
                    log_start_line=log_content[:match.start()].count('\n'),
                )
                
                # Determine status based on what follows
                remaining = log_content[match.end():match.end() + 5000]
                if re.search(r"(?:ERROR|FAILURE|FAILED)", remaining):
                    node.status = "FAILURE"
                elif re.search(r"(?:SUCCESS|PASSED)", remaining):
                    node.status = "SUCCESS"
                else:
                    node.status = "UNKNOWN"
                
                nodes.append(node)
        
        # Track library function calls
        lib_call_pattern = re.compile(r"Calling\s+(\w+)\.(\w+)\s*\(|(\w+)\s*\(\s*\)\s*{")
        for match in lib_call_pattern.finditer(log_content):
            groups = match.groups()
            func_name = groups[1] if groups[0] else groups[2]
            if func_name:
                node = PipelineExecutionNode(
                    node_id=f"call_{len(nodes)}",
                    node_type="library_call",
                    name=func_name,
                    log_start_line=log_content[:match.start()].count('\n'),
                )
                nodes.append(node)
        
        return nodes
    
    def _identify_library_functions(
        self,
        log_content: str,
        library_sources: Dict[str, str],
    ) -> List[LibraryFunction]:
        """Identify which library functions were called."""
        functions = []
        
        # Pattern for vars/ global functions
        vars_pattern = re.compile(r"vars[/\\](\w+)\.groovy")
        
        for file_path, content in library_sources.items():
            if "vars/" in file_path or "vars\\" in file_path:
                match = vars_pattern.search(file_path)
                if match:
                    func_name = match.group(1)
                    
                    # Check if this function appears in the log
                    if func_name in log_content:
                        func = LibraryFunction(
                            name=func_name,
                            file_path=file_path,
                            is_global_var=True,
                        )
                        
                        # Extract parameters from call() method
                        call_match = re.search(
                            r"def\s+call\s*\(([^)]*)\)", content
                        )
                        if call_match:
                            params = [p.strip() for p in call_match.group(1).split(",")]
                            func.parameters = params
                        
                        functions.append(func)
        
        # Also look for function calls in stack traces
        call_pattern = re.compile(r"at\s+Script\d+\.(\w+)\(")
        for match in call_pattern.finditer(log_content):
            func_name = match.group(1)
            if not any(f.name == func_name for f in functions):
                functions.append(LibraryFunction(
                    name=func_name,
                    file_path="unknown",
                ))
        
        return functions
    
    def _find_stage_context(self, log_content: str, error_position: int) -> str:
        """Find which pipeline stage contains an error position."""
        # Look backwards from error position for stage markers
        before_error = log_content[:error_position]
        
        for pattern in self.STAGE_PATTERNS:
            matches = list(re.finditer(pattern, before_error))
            if matches:
                return matches[-1].group(1)
        
        return ""
    
    def _determine_failure_type(self, errors: List[GroovyError]) -> GroovyFailureType:
        """Determine the primary failure type from errors."""
        if not errors:
            return GroovyFailureType.UNKNOWN
        
        # Priority order
        priority = [
            GroovyFailureType.SANDBOX_REJECTION,
            GroovyFailureType.LIBRARY_LOAD,
            GroovyFailureType.LIBRARY_VERSION,
            GroovyFailureType.CPS_TRANSFORMATION,
            GroovyFailureType.SERIALIZATION,
            GroovyFailureType.MISSING_METHOD,
            GroovyFailureType.MISSING_PROPERTY,
            GroovyFailureType.CLASS_NOT_FOUND,
            GroovyFailureType.COMPILATION,
            GroovyFailureType.SYNTAX,
            GroovyFailureType.NULL_POINTER,
            GroovyFailureType.TYPE_MISMATCH,
            GroovyFailureType.STEP_EXECUTION,
            GroovyFailureType.SCRIPT_APPROVAL,
        ]
        
        error_types = {e.error_type for e in errors}
        for ft in priority:
            if ft in error_types:
                return ft
        
        return errors[0].error_type
    
    def _find_root_cause_function(
        self,
        errors: List[GroovyError],
        functions: List[LibraryFunction],
        cps_trace: List[CPSFrame],
    ) -> Optional[LibraryFunction]:
        """Find the library function that is the root cause."""
        
        # Look for library code in CPS trace
        library_frames = [f for f in cps_trace if f.is_library_code and not f.cps_specific]
        
        if library_frames:
            # Find matching function
            for frame in library_frames:
                for func in functions:
                    if func.name in frame.class_name or func.name == frame.method_name:
                        return func
        
        # Fall back to first function mentioned in errors
        for error in errors:
            if error.library_context:
                for func in functions:
                    if func.name == error.library_context:
                        return func
        
        return None
    
    def _generate_error_suggestions(self, error: GroovyError) -> List[str]:
        """Generate fix suggestions for an error."""
        suggestions = list(error.suggestions)  # Copy existing
        
        if error.error_type == GroovyFailureType.SANDBOX_REJECTION:
            suggestions.extend([
                f"Go to Manage Jenkins → In-process Script Approval and approve: {error.required_approval}",
                "Consider using a @NonCPS annotation if the method doesn't need CPS",
                "Check if there's a whitelisted alternative method",
            ])
        
        elif error.error_type == GroovyFailureType.MISSING_METHOD:
            suggestions.extend([
                f"Verify the method {error.target_method} exists in {error.target_class}",
                "Check for typos in the method name",
                "Verify the correct number and types of arguments",
                "Check if the shared library version has this method",
            ])
        
        elif error.error_type == GroovyFailureType.MISSING_PROPERTY:
            suggestions.extend([
                f"Verify property '{error.target_property}' is defined",
                "Check if this property requires a different scope (env, params, etc.)",
                "Ensure the variable is passed to the library function",
            ])
        
        elif error.error_type == GroovyFailureType.SERIALIZATION:
            suggestions.extend([
                "Move non-serializable code into a @NonCPS method",
                f"Avoid storing {error.target_class} in pipeline variables",
                "Use primitive types or serializable classes instead",
            ])
        
        elif error.error_type == GroovyFailureType.LIBRARY_LOAD:
            suggestions.extend([
                "Verify the library name and SCM URL in Jenkins configuration",
                "Check if the library repository is accessible",
                "Verify credentials for private repositories",
            ])
        
        elif error.error_type == GroovyFailureType.LIBRARY_VERSION:
            suggestions.extend([
                "Verify the branch/tag exists in the repository",
                "Check if the library version was recently deleted",
                "Try using 'master' or 'main' instead of a specific version",
            ])
        
        elif error.error_type == GroovyFailureType.CPS_TRANSFORMATION:
            suggestions.extend([
                "Use @NonCPS annotation for methods that cannot be CPS-transformed",
                "Avoid using closures in certain contexts",
                "Check if the library function is compatible with pipeline CPS",
            ])
        
        return suggestions
    
    def _generate_summary(self, analysis: GroovyAnalysis) -> str:
        """Generate a human-readable summary of the analysis."""
        parts = []
        
        parts.append(f"Groovy/Pipeline Analysis: {analysis.failure_type.value}")
        
        if analysis.errors:
            parts.append(f"Found {len(analysis.errors)} Groovy errors")
        
        if analysis.library_references:
            libs = ", ".join(f"{r.name}@{r.version}" for r in analysis.library_references)
            parts.append(f"Libraries used: {libs}")
        
        if analysis.root_cause_function:
            parts.append(f"Root cause in function: {analysis.root_cause_function.name}")
        
        if analysis.decoded_cps_trace:
            non_cps = [f for f in analysis.decoded_cps_trace if not f.cps_specific]
            if non_cps:
                parts.append(f"Call stack depth: {len(non_cps)} frames")
        
        return ". ".join(parts) + "."
    
    def get_decoded_stack_trace(self, analysis: GroovyAnalysis) -> str:
        """Get a human-readable version of the CPS stack trace."""
        lines = []
        lines.append("=== Decoded Pipeline Stack Trace ===")
        lines.append("(CPS machinery filtered out)")
        lines.append("")
        
        for frame in analysis.decoded_cps_trace:
            if frame.cps_specific:
                continue
            
            prefix = ""
            if frame.is_pipeline_step:
                prefix = "[STEP] "
            elif frame.is_library_code:
                prefix = f"[LIB:{frame.library_name or 'unknown'}] "
            
            loc = f"{frame.file_name}:{frame.line_number}" if frame.line_number else ""
            lines.append(f"  {prefix}{frame.class_name}.{frame.method_name}({loc})")
        
        return "\n".join(lines)
    
    def format_for_ai_prompt(self, analysis: GroovyAnalysis) -> str:
        """Format the analysis for inclusion in an AI prompt."""
        parts = []
        
        parts.append("## Groovy/Pipeline Analysis")
        parts.append(f"**Failure Type:** {analysis.failure_type.value}")
        parts.append("")
        
        # Library context
        if analysis.library_references:
            parts.append("### Shared Libraries")
            for lib in analysis.library_references:
                parts.append(f"- **{lib.name}** @ `{lib.version}`")
            parts.append("")
        
        # Errors
        if analysis.errors:
            parts.append("### Groovy Errors")
            for i, error in enumerate(analysis.errors[:5]):
                parts.append(f"\n**Error {i+1}:** {error.error_type.value}")
                parts.append(f"Message: `{error.message[:500]}`")
                if error.target_class:
                    parts.append(f"Target: `{error.target_class}`")
                if error.target_method:
                    parts.append(f"Method: `{error.target_method}`")
                if error.target_property:
                    parts.append(f"Property: `{error.target_property}`")
                if error.pipeline_stage:
                    parts.append(f"Stage: `{error.pipeline_stage}`")
                if error.suggestions:
                    parts.append("Suggestions:")
                    for s in error.suggestions[:3]:
                        parts.append(f"  - {s}")
            parts.append("")
        
        # Root cause function
        if analysis.root_cause_function:
            parts.append("### Root Cause Function")
            parts.append(f"- **Name:** {analysis.root_cause_function.name}")
            parts.append(f"- **File:** {analysis.root_cause_function.file_path}")
            if analysis.root_cause_function.parameters:
                params = ", ".join(analysis.root_cause_function.parameters)
                parts.append(f"- **Parameters:** {params}")
            parts.append("")
        
        # Decoded stack trace
        if analysis.decoded_cps_trace:
            parts.append("### Decoded Call Stack (CPS machinery filtered)")
            non_cps = [f for f in analysis.decoded_cps_trace if not f.cps_specific][:10]
            for frame in non_cps:
                prefix = "[LIB]" if frame.is_library_code else "[STEP]" if frame.is_pipeline_step else ""
                parts.append(f"  {prefix} {frame.class_name}.{frame.method_name}")
            parts.append("")
        
        # Execution path
        if analysis.execution_path:
            parts.append("### Execution Path")
            for node in analysis.execution_path:
                status = f" ({node.status})" if node.status else ""
                parts.append(f"- {node.node_type}: {node.name}{status}")
            parts.append("")
        
        parts.append(f"**Summary:** {analysis.summary}")
        
        return "\n".join(parts)
    
    # =========================================================================
    # Requirement 17.9: Detect tool invocations within sh() steps
    # =========================================================================
    
    # Known tools to detect in sh() commands
    KNOWN_TOOLS = {
        "aws", "az", "gcloud", "kubectl", "helm", "docker",
        "terraform", "mvn", "mvnw", "gradle", "gradlew",
        "npm", "yarn", "pip", "pip3", "curl", "wget",
        "git", "make", "python", "python3", "java", "node",
        "ansible", "ansible-playbook", "packer", "vault",
    }
    
    # Patterns to match sh() step invocations in Groovy
    SH_STEP_PATTERNS = [
        # sh "command" or sh 'command'
        re.compile(r'sh\s*["\'](.+?)["\']', re.DOTALL),
        # sh """command""" or sh '''command'''
        re.compile(r'sh\s*"{3}(.+?)"{3}', re.DOTALL),
        re.compile(r"sh\s*'{3}(.+?)'{3}", re.DOTALL),
        # sh script: "command"
        re.compile(r'sh\s+script:\s*["\'](.+?)["\']', re.DOTALL),
        re.compile(r'sh\s+script:\s*"{3}(.+?)"{3}', re.DOTALL),
        # shell() function (common in shared libraries)
        re.compile(r'shell\s*\(\s*["\'](.+?)["\']', re.DOTALL),
    ]
    
    # Pattern to extract variables from commands
    VARIABLE_PATTERN = re.compile(r'\$\{?(\w+)\}?')
    
    def extract_sh_tool_invocations(
        self,
        source_code: str,
        source_file: str = "",
        enclosing_method: str = "",
    ) -> List[SourceToolInvocation]:
        """
        Extract tool invocations from sh() steps in Groovy source code.
        
        Implements Requirement 17.9: Detect tools within sh() steps in
        Jenkinsfile or shared library methods.
        
        Args:
            source_code: Groovy/Jenkinsfile source code
            source_file: Path to the source file
            enclosing_method: Name of enclosing method if known
            
        Returns:
            List of SourceToolInvocation objects for detected tools
        """
        invocations = []
        
        # Track line numbers
        lines = source_code.split('\n')
        line_to_offset = {}
        offset = 0
        for i, line in enumerate(lines):
            line_to_offset[offset] = i + 1
            offset += len(line) + 1  # +1 for newline
        
        def get_line_number(match_start: int) -> int:
            """Get line number for a match position."""
            for off, line_num in sorted(line_to_offset.items()):
                if off > match_start:
                    return prev_line
                prev_line = line_num
            return prev_line
        
        # Find all sh() invocations
        for pattern in self.SH_STEP_PATTERNS:
            for match in pattern.finditer(source_code):
                command = match.group(1).strip()
                line_num = get_line_number(match.start())
                
                # Extract tools from the command
                tools = self._extract_tools_from_command(command)
                
                # Extract variables used
                variables = self.VARIABLE_PATTERN.findall(command)
                
                for tool_name, command_part in tools:
                    invocations.append(SourceToolInvocation(
                        tool_name=tool_name,
                        command_template=command_part,
                        source_file=source_file,
                        line_number=line_num,
                        enclosing_method=enclosing_method,
                        is_in_sh_step=True,
                        variables_used=list(set(variables)),
                    ))
        
        return invocations
    
    def _extract_tools_from_command(self, command: str) -> List[Tuple[str, str]]:
        """
        Extract tool names and their command portions from a shell command.
        
        Handles:
        - Simple commands: aws s3 cp ...
        - Piped commands: cat file | grep pattern
        - Chained commands: cmd1 && cmd2
        - Subcommands: $(aws ...) or `aws ...`
        - Multi-line commands (in triple-quoted strings)
        
        Returns list of (tool_name, command_portion) tuples.
        """
        tools = []
        
        # First, split by newlines for multi-line commands
        lines = command.split('\n')
        commands = []
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            commands.append(line)
        
        # Then split each line by common command separators
        separators = ['&&', '||', ';', '|']
        for sep in separators:
            new_commands = []
            for cmd in commands:
                new_commands.extend(cmd.split(sep))
            commands = new_commands
        
        # Also extract subcommands
        subcommand_pattern = re.compile(r'\$\(([^)]+)\)|`([^`]+)`')
        for match in subcommand_pattern.finditer(command):
            sub = match.group(1) or match.group(2)
            if sub:
                commands.append(sub)
        
        # Process each command portion
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            
            # Get first word (the tool)
            parts = cmd.split()
            if not parts:
                continue
            
            first_word = parts[0]
            
            # Strip common prefixes
            if first_word.startswith('./'):
                first_word = first_word[2:]
            if '/' in first_word:
                first_word = first_word.split('/')[-1]
            
            # Check if it's a known tool
            if first_word.lower() in self.KNOWN_TOOLS:
                tools.append((first_word.lower(), cmd))
            elif first_word in self.KNOWN_TOOLS:
                tools.append((first_word, cmd))
        
        return tools
    
    def analyze_source_for_tools(
        self,
        jenkinsfile_content: str = None,
        library_sources: Dict[str, str] = None,
    ) -> List[SourceToolInvocation]:
        """
        Analyze Jenkinsfile and library sources for tool invocations.
        
        Args:
            jenkinsfile_content: Content of Jenkinsfile
            library_sources: Dict mapping file paths to source content
            
        Returns:
            Combined list of all detected tool invocations
        """
        all_invocations = []
        
        # Analyze Jenkinsfile
        if jenkinsfile_content:
            invocations = self.extract_sh_tool_invocations(
                jenkinsfile_content,
                source_file="Jenkinsfile",
            )
            all_invocations.extend(invocations)
        
        # Analyze library sources
        if library_sources:
            for file_path, content in library_sources.items():
                # Try to detect enclosing method from filename
                method_name = ""
                if file_path.startswith("vars/") and file_path.endswith(".groovy"):
                    # vars/myMethod.groovy -> myMethod
                    method_name = Path(file_path).stem
                
                invocations = self.extract_sh_tool_invocations(
                    content,
                    source_file=file_path,
                    enclosing_method=method_name,
                )
                all_invocations.extend(invocations)
        
        return all_invocations
