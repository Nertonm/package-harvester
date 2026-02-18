"""
Enhanced Nix Expression Parser
================================

CRITICAL FIX: Addresses the "Data Hallucination" problem in Harvester.

The Problem:
- Original parser uses simple regex on Nix expressions
- Nix is a functional language with complex syntax
- Conditional dependencies, variables, imports are ignored
- Results in incomplete dependency lists

Solutions Implemented:
1. Multi-pass parsing with improved regex patterns
2. Variable expansion tracking
3. Conditional expression detection
4. Comment handling
5. Validation and logging of parse quality

This is not a full AST parser (would require nix-parser library),
but a significantly improved heuristic parser that handles most real-world cases.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)

class ParseQuality(Enum):
    """Quality assessment of parse results."""
    HIGH = auto()      # All dependencies likely captured
    MEDIUM = auto()    # Most dependencies captured, some may be missing
    LOW = auto()       # Partial capture, significant deps likely missing
    UNKNOWN = auto()   # Cannot assess quality

@dataclass
class NixDependencies:
    """Structured representation of Nix package dependencies."""
    build_inputs: set[str] = field(default_factory=set)
    native_build_inputs: set[str] = field(default_factory=set)
    propagated_build_inputs: set[str] = field(default_factory=set)
    check_inputs: set[str] = field(default_factory=set)
    
    # Metadata
    variables: dict[str, set[str]] = field(default_factory=dict)
    conditionals: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    
    # Quality metrics
    parse_quality: ParseQuality = ParseQuality.UNKNOWN
    warnings: list[str] = field(default_factory=list)
    
    def get_all_dependencies(self) -> set[str]:
        """Get all dependencies from all categories."""
        all_deps = set()
        all_deps.update(self.build_inputs)
        all_deps.update(self.native_build_inputs)
        all_deps.update(self.propagated_build_inputs)
        all_deps.update(self.check_inputs)
        return all_deps
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "buildInputs": list(self.build_inputs),
            "nativeBuildInputs": list(self.native_build_inputs),
            "propagatedBuildInputs": list(self.propagated_build_inputs),
            "checkInputs": list(self.check_inputs),
            "variables": {k: list(v) for k, v in self.variables.items()},
            "conditionals": self.conditionals,
            "imports": self.imports,
            "parseQuality": self.parse_quality.name,
            "warnings": self.warnings,
            "totalDependencies": len(self.get_all_dependencies())
        }

class EnhancedNixParser:
    """
    Enhanced parser for Nix expressions with improved dependency extraction.
    
    Handles:
    - Simple lists: buildInputs = [ foo bar ];
    - With statements: buildInputs = with pkgs; [ ... ];
    - Variables: commonDeps = [ ... ]; buildInputs = commonDeps ++ [ ... ];
    - Conditionals: buildInputs = [ ... ] ++ lib.optionals stdenv.isLinux [ ... ];
    - Multi-line arrays
    - Comments (# and /* */)
    - String interpolation
    """
    
    # Dependency field patterns
    DEPENDENCY_FIELDS = [
        "buildInputs",
        "nativeBuildInputs",
        "propagatedBuildInputs",
        "checkInputs",
        "buildInputs",
    ]
    
    def __init__(self):
        self.warnings = []
    
    def parse(self, content: str, pkg_name: str | None = None) -> NixDependencies:
        """
        Parse Nix expression content and extract dependencies.
        
        Args:
            content: Nix expression content
            pkg_name: Package name for logging context
        
        Returns:
            NixDependencies object with parsed data
        """
        self.warnings = []
        deps = NixDependencies()
        
        # Step 1: Remove comments
        cleaned_content = self._remove_comments(content)
        
        # Step 2: Extract variable definitions
        variables = self._extract_variables(cleaned_content)
        deps.variables = variables
        
        # Step 3: Extract imports
        deps.imports = self._extract_imports(cleaned_content)
        
        # Step 4: Parse each dependency field
        for field in self.DEPENDENCY_FIELDS:
            field_deps = self._parse_dependency_field(
                cleaned_content,
                field,
                variables
            )
            
            # Map to NixDependencies fields
            if field == "buildInputs":
                deps.build_inputs.update(field_deps)
            elif field == "nativeBuildInputs":
                deps.native_build_inputs.update(field_deps)
            elif field == "propagatedBuildInputs":
                deps.propagated_build_inputs.update(field_deps)
            elif field == "checkInputs":
                deps.check_inputs.update(field_deps)
        
        # Step 5: Detect conditionals
        deps.conditionals = self._detect_conditionals(cleaned_content)
        
        # Step 6: Assess parse quality
        deps.parse_quality = self._assess_quality(deps, cleaned_content)
        deps.warnings = self.warnings
        
        # Log results
        if pkg_name:
            logger.info(
                f"[NIX-PARSE] {pkg_name}: "
                f"{len(deps.get_all_dependencies())} deps, "
                f"quality={deps.parse_quality.name}, "
                f"{len(deps.warnings)} warnings"
            )
        
        return deps
    
    def _remove_comments(self, content: str) -> str:
        """
        Remove Nix comments from content.
        
        Handles:
        - Single-line: # comment
        - Multi-line: /* comment */
        """
        # Remove multi-line comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Remove single-line comments (but preserve in strings)
        lines = []
        for line in content.splitlines():
            # Simple heuristic: if # is inside quotes, keep it
            if '"' in line or "'" in line:
                # Complex case, keep line as-is (may have false positives)
                lines.append(line)
            else:
                # Remove everything after #
                line = re.sub(r'#.*$', '', line)
                lines.append(line)
        
        return '\n'.join(lines)
    
    def _extract_variables(self, content: str) -> dict[str, set[str]]:
        """
        Extract variable definitions like:
        commonDeps = [ foo bar ];
        """
        variables = {}
        
        # Pattern: varName = [ ... ];
        pattern = re.compile(
            r'(\w+)\s*=\s*(?:with\s+[\w\.]+;\s*)?\[(.*?)\];',
            re.DOTALL
        )
        
        for match in pattern.finditer(content):
            var_name = match.group(1)
            var_content = match.group(2)
            
            # Skip if it looks like a field (starts with lowercase or is known field)
            if var_name in self.DEPENDENCY_FIELDS:
                continue
            
            # Parse content
            deps = self._parse_list_content(var_content)
            if deps:
                variables[var_name] = deps
                logger.debug(f"[NIX-PARSE] Variable {var_name} = {deps}")
        
        return variables
    
    def _extract_imports(self, content: str) -> list[str]:
        """
        Extract imports like:
        import ./foo.nix
        callPackage ./bar.nix {}
        """
        imports = []

        import_pattern = re.compile(r'import\s+(\.[\w\/\-\.]+)')
        imports.extend(import_pattern.findall(content))
        
        # callPackage patterns
        call_pattern = re.compile(r'callPackage\s+(\.[\w\/\-\.]+)')
        imports.extend(call_pattern.findall(content))
        
        return imports
    
    def _parse_dependency_field(
        self,
        content: str,
        field_name: str,
        variables: dict[str, set[str]]
    ) -> set[str]:
        """
        Parse a single dependency field with variable expansion.
        
        Handles:
        - Simple: buildInputs = [ foo bar ];
        - With: buildInputs = with pkgs; [ ... ];
        - Variables: buildInputs = commonDeps ++ [ ... ];
        - Conditionals: buildInputs = [ ... ] ++ lib.optionals condition [ ... ];
        """
        deps = set()
        
        # Find field definition
        # Pattern matches:
        # fieldName = <expression>;
        field_pattern = re.compile(
            rf'{field_name}\s*=\s*(.*?);',
            re.DOTALL
        )
        
        match = field_pattern.search(content)
        if not match:
            return deps
        
        expression = match.group(1)
        
        # Parse the expression
        deps.update(self._parse_expression(expression, variables))
        
        return deps
    
    def _parse_expression(
        self,
        expression: str,
        variables: dict[str, set[str]]
    ) -> set[str]:
        """
        Parse a Nix expression that may contain:
        - Lists: [ foo bar ]
        - Variable references: commonDeps
        - Concatenations: [ foo ] ++ bar ++ [ baz ]
        - Conditionals: lib.optionals condition [ ... ]
        """
        deps = set()
        
        # Split by ++ (concatenation operator)
        parts = re.split(r'\+\+', expression)
        
        for part in parts:
            part = part.strip()
            
            # Check if it's a variable reference
            var_match = re.match(r'^(\w+)$', part)
            if var_match:
                var_name = var_match.group(1)
                if var_name in variables:
                    deps.update(variables[var_name])
                    logger.debug(f"[NIX-PARSE] Expanded variable {var_name}")
                    continue
            
            # Check if it's a conditional (lib.optionals, lib.optional)
            if 'lib.optional' in part:
                # Extract the list inside the conditional
                list_match = re.search(r'\[(.*?)\]', part)
                if list_match:
                    list_content = list_match.group(1)
                    deps.update(self._parse_list_content(list_content))
                    self.warnings.append(
                        f"Conditional dependency found: {part[:50]}..."
                    )
                continue
            
            # Check if it's a list
            list_match = re.search(r'\[(.*?)\]', part, re.DOTALL)
            if list_match:
                list_content = list_match.group(1)
                
                # Handle 'with pkgs;' prefix
                if 'with' in part:
                    list_content = re.sub(r'with\s+[\w\.]+;\s*', '', list_content)
                
                deps.update(self._parse_list_content(list_content))
        
        return deps
    
    def _parse_list_content(self, content: str) -> set[str]:
        """
        Parse the content of a list [ foo bar baz ].
        
        Handles:
        - Simple tokens: foo bar
        - Quoted strings: "foo" 'bar'
        - Attributes: pkgs.foo
        - Filters out: variables (${...}), operators, keywords
        """
        deps = set()
        
        # Remove string quotes and split by whitespace
        content = content.replace('"', ' ').replace("'", ' ')
        
        # Split into tokens
        tokens = content.split()
        
        for token in tokens:
            token = token.strip()
            
            # Skip empty
            if not token:
                continue
            
            # Skip variables ${...}
            if token.startswith('${'):
                continue
            
            # Skip operators and keywords
            if token in ['++', '||', '&&', 'if', 'then', 'else', 'let', 'in', 'with']:
                continue
            
            # Skip Nix builtins
            if token in ['stdenv', 'lib', 'fetchurl', 'fetchgit', 'mkDerivation']:
                continue
            
            # Handle attribute paths (pkgs.foo -> foo)
            if '.' in token:
                token = token.split('.')[-1]
            
            # Clean up
            token = token.strip('";,')
            
            # Validate: should be alphanumeric with dashes/underscores
            if re.match(r'^[a-zA-Z0-9_\-]+$', token) and len(token) > 1:
                deps.add(token)
        
        return deps
    
    def _detect_conditionals(self, content: str) -> list[str]:
        """Detect conditional expressions in the content."""
        conditionals = []
        
        patterns = [
            r'lib\.optionals?\s+([^\[]+)\[',
            r'if\s+([^\n]+)\s+then',
            r'stdenv\.is\w+',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            conditionals.extend(matches)
        
        return conditionals
    
    def _assess_quality(self, deps: NixDependencies, content: str) -> ParseQuality:
        """
        Assess the quality of the parse based on heuristics.
        
        Returns:
            ParseQuality enum value
        """
        # Check for unparsed patterns that might indicate missing deps
        
        # If we found imports, quality is lower (may have external deps)
        if deps.imports:
            self.warnings.append(f"Found {len(deps.imports)} imports - external dependencies may be missing")
            return ParseQuality.MEDIUM
        
        # If we found conditionals, quality depends on parsing
        if deps.conditionals:
            if len(deps.conditionals) > 3:
                self.warnings.append("Multiple conditionals found - some dependencies may be conditional")
                return ParseQuality.MEDIUM
        
        # Check for unparsed callPackage or import
        if re.search(r'callPackage\s+\w+', content):
            self.warnings.append("callPackage with variable found - dependencies may be incomplete")
            return ParseQuality.LOW
        
        # If we have dependencies and no major warnings
        total_deps = len(deps.get_all_dependencies())
        if total_deps > 0:
            if len(self.warnings) == 0:
                return ParseQuality.HIGH
            else:
                return ParseQuality.MEDIUM
        
        # No dependencies found
        if total_deps == 0:
            self.warnings.append("No dependencies found - may be incorrect or empty package")
            return ParseQuality.LOW
        
        return ParseQuality.UNKNOWN

# Convenience function for backward compatibility
def parse_nix_dependencies(content: str, pkg_name: str | None = None) -> dict[str, Any]:
    """
    Parse Nix expression and return dictionary.
    
    This is a drop-in replacement for the old _parse_nix_deps method.
    """
    parser = EnhancedNixParser()
    deps = parser.parse(content, pkg_name)
    return deps.to_dict()
