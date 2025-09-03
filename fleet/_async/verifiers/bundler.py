"""Fleet SDK Function Bundler - Dependency Detection and Bundle Creation.

Handles dependency detection and bundle creation for verifier functions with basic static analysis.
The client performs dependency detection and creates lightweight bundles.
The server uses uv to resolve dependencies and create the execution environment.
"""

import inspect
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List, Set
from io import BytesIO
import logging
import ast
from collections import defaultdict

try:
    import importlib.metadata as imd
except ImportError:
    import importlib_metadata as imd

logger = logging.getLogger(__name__)


class FunctionBundler:
    """Handles dependency detection and bundle creation for verifier functions with basic static analysis."""

    def __init__(self):
        pass

    def create_bundle(
        self,
        func: Callable,
        extra_requirements: Optional[List[str]] = None,
        verifier_id: Optional[str] = None,
    ) -> bytes:
        """Create a function bundle with statically extracted code."""

        logger.info(f"Creating function bundle for {func.__name__}")

        # 1. Parse the main function and find dependencies
        mod_file = Path(func.__code__.co_filename)
        project_root = self._find_project_root(mod_file)

        # 2. Analyze dependencies with static analysis
        dependencies = self._analyze_dependencies_with_static_analysis(
            func, mod_file, project_root
        )

        # 3. Map external packages
        requirements = self._map_to_pypi_packages(dependencies["external_packages"])

        # Merge with extra requirements, handling version conflicts
        if extra_requirements:
            requirements = self._merge_requirements(requirements, extra_requirements)

        # 4. Build optimized bundle
        # Get source without decorator
        src = self._get_function_source_without_decorator(func)
        bundle_bytes = self._build_function_bundle(
            func,
            src,
            requirements,
            dependencies["extracted_code"],
            project_root,
            verifier_id,
            dependencies.get("same_module_deps", []),
        )

        return bundle_bytes

    def _analyze_dependencies_with_static_analysis(
        self, func: Callable, mod_file: Path, project_root: Path
    ) -> Dict[str, Any]:
        """Analyze dependencies and extract functions using basic static analysis."""

        # Parse the main function - handle indentation
        main_func_code = inspect.getsource(func)
        # Remove decorator and normalize indentation
        main_func_lines = main_func_code.split("\n")

        # Find the actual function definition line (skip decorators)
        func_start_idx = 0
        for i, line in enumerate(main_func_lines):
            if line.strip().startswith("def "):
                func_start_idx = i
                break

        # Extract function definition and body
        func_lines = main_func_lines[func_start_idx:]

        # Remove common leading whitespace
        if func_lines:
            import textwrap

            normalized_func_code = textwrap.dedent("\n".join(func_lines))
            main_func_ast = ast.parse(normalized_func_code)
        else:
            main_func_ast = ast.parse("")

        # Find all import statements in the main function
        imports_in_func = self._extract_imports_from_ast(main_func_ast)

        # Also analyze the module containing the function
        with open(mod_file, "r", encoding="utf-8") as f:
            module_content = f.read()
        module_ast = ast.parse(module_content)

        # Find imports at module level
        module_imports = self._extract_imports_from_ast(module_ast)

        # Combine all imports
        all_imports = {**imports_in_func, **module_imports}

        # Find function calls within the verifier function
        called_functions = self._extract_function_calls(main_func_ast)
        logger.debug(f"Functions called in verifier: {called_functions}")

        # Find all functions defined in the module
        module_functions = {}
        for node in ast.walk(module_ast):
            if isinstance(node, ast.FunctionDef):
                module_functions[node.name] = node

        # Check which called functions are defined in the same module
        same_module_deps = []
        for func_name in called_functions:
            if func_name in module_functions and func_name != func.__name__:
                same_module_deps.append(func_name)
                logger.debug(f"Found same-module dependency: {func_name}")

        # Separate local and external imports
        local_imports = {}
        external_packages = set()
        extracted_code = {}

        for import_type, import_list in all_imports.items():
            for import_info in import_list:
                if import_type == "from_import":
                    module_name = import_info["module"]
                    imported_names = import_info["names"]

                    # Try to resolve as local import
                    local_path = self._resolve_local_import(
                        module_name, mod_file, project_root
                    )
                    if local_path and local_path.exists():
                        # Extract only the specific functions we need
                        extracted_functions = self._extract_specific_functions(
                            local_path, imported_names
                        )

                        if extracted_functions:
                            relative_path = str(local_path.relative_to(project_root))
                            extracted_code[relative_path] = extracted_functions
                            local_imports[module_name] = imported_names
                    else:
                        # External package
                        external_packages.add(module_name)

                elif import_type == "import":
                    module_name = import_info["name"]
                    # Check if it's a local or external import
                    if not self._is_likely_stdlib(module_name):
                        try:
                            dist = imd.distribution(module_name)
                            external_packages.add(dist.metadata["Name"])
                        except imd.PackageNotFoundError:
                            # Could be local, but for now assume external
                            external_packages.add(module_name)

        return {
            "local_imports": local_imports,
            "external_packages": external_packages,
            "extracted_code": extracted_code,
            "same_module_deps": same_module_deps,  # Add same-module dependencies
        }

    def _extract_imports_from_ast(
        self, tree: ast.AST
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Extract import statements from AST."""
        imports = defaultdict(list)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports["import"].append(
                        {"name": alias.name, "asname": alias.asname}
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:  # Skip relative imports without module
                    imports["from_import"].append(
                        {
                            "module": node.module,
                            "names": [alias.name for alias in node.names],
                            "level": node.level,
                        }
                    )

        return dict(imports)

    def _extract_function_calls(self, tree: ast.AST) -> Set[str]:
        """Extract function calls from AST."""
        function_calls = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Handle direct function calls (e.g., func())
                if isinstance(node.func, ast.Name):
                    function_calls.add(node.func.id)
                # Handle method calls (e.g., obj.method())
                elif isinstance(node.func, ast.Attribute):
                    # We might want to handle these differently
                    pass

        return function_calls

    def _extract_specific_functions(
        self, file_path: Path, function_names: List[str]
    ) -> str:
        """Extract specific functions from a file, including their dependencies."""

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)

            # Find all function definitions
            functions = {}
            classes = {}
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions[node.name] = node
                elif isinstance(node, ast.ClassDef):
                    classes[node.name] = node
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.append(node)

            # Extract required functions and their dependencies
            required_functions = set(function_names)
            extracted_nodes = []

            # Add necessary imports
            used_names = set()
            for func_name in function_names:
                if func_name in functions:
                    # Find all names used in this function
                    for node in ast.walk(functions[func_name]):
                        if isinstance(node, ast.Name):
                            used_names.add(node.id)

            # Add imports that provide these names
            for import_node in imports:
                if isinstance(import_node, ast.Import):
                    for alias in import_node.names:
                        if alias.name in used_names:
                            extracted_nodes.append(import_node)
                            break
                elif isinstance(import_node, ast.ImportFrom):
                    for alias in import_node.names:
                        if alias.name in used_names:
                            extracted_nodes.append(import_node)
                            break

            # Add required functions
            for func_name in required_functions:
                if func_name in functions:
                    extracted_nodes.append(functions[func_name])

                    # Check if this function calls other local functions
                    for node in ast.walk(functions[func_name]):
                        if isinstance(node, ast.Call) and isinstance(
                            node.func, ast.Name
                        ):
                            called_func = node.func.id
                            if (
                                called_func in functions
                                and called_func not in required_functions
                            ):
                                required_functions.add(called_func)
                                extracted_nodes.append(functions[called_func])

            # Convert back to source code
            extracted_code = []
            for node in extracted_nodes:
                try:
                    code = ast.unparse(node)
                    extracted_code.append(code)
                except Exception as e:
                    logger.warning(f"Could not unparse AST node: {e}")
                    # Fallback to original source extraction
                    lines = content.split("\n")
                    start_line = node.lineno - 1
                    end_line = (
                        node.end_lineno
                        if hasattr(node, "end_lineno")
                        else start_line + 1
                    )
                    code = "\n".join(lines[start_line:end_line])
                    extracted_code.append(code)

            result = "\n\n".join(extracted_code)
            logger.debug(f"Extracted {len(extracted_code)} items from {file_path}")
            return result

        except Exception as e:
            logger.warning(f"Failed to extract functions from {file_path}: {e}")
            # Fallback to including the entire file
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

    def _resolve_local_import(
        self, module_name: str, current_file: Path, project_root: Path
    ) -> Optional[Path]:
        """Try to resolve a module name to a local file path."""

        # Handle dotted imports (e.g., utils.helpers -> utils/helpers.py)
        module_parts = module_name.split(".")

        # Search from current file's directory up to project root
        search_dirs = [current_file.parent]

        # Add project root and its subdirectories to search path
        current = current_file.parent
        while current != project_root.parent:
            search_dirs.append(current)
            if current == project_root:
                break
            current = current.parent

        for search_dir in search_dirs:
            # Try as a package (directory with __init__.py)
            package_dir = search_dir
            for part in module_parts:
                package_dir = package_dir / part

            init_file = package_dir / "__init__.py"
            if init_file.exists():
                return init_file

            # Try as a module (file.py)
            module_file = search_dir
            for part in module_parts[:-1]:
                module_file = module_file / part
            module_file = module_file / f"{module_parts[-1]}.py"

            if module_file.exists():
                return module_file

        return None

    def _find_project_root(self, mod_file: Path) -> Path:
        """Find the project root by looking for common markers."""
        current = mod_file.parent

        # Look for common project root markers
        markers = [
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            ".git",
            ".hg",
            "requirements.txt",
            "Pipfile",
        ]

        while current != current.parent:  # Not at filesystem root
            if any((current / marker).exists() for marker in markers):
                return current
            current = current.parent

        # Fallback to the directory containing the source file
        return mod_file.parent

    def _is_likely_stdlib(self, module_name: str) -> bool:
        """Check if a module is likely part of the standard library."""
        stdlib_modules = {
            "os",
            "sys",
            "json",
            "datetime",
            "time",
            "random",
            "math",
            "re",
            "collections",
            "itertools",
            "functools",
            "operator",
            "pathlib",
            "urllib",
            "http",
            "socket",
            "threading",
            "multiprocessing",
            "logging",
            "argparse",
            "configparser",
            "csv",
            "xml",
            "html",
            "base64",
            "hashlib",
            "hmac",
            "secrets",
            "uuid",
            "pickle",
            "sqlite3",
            "dbm",
            "zipfile",
            "tarfile",
            "gzip",
            "shutil",
            "tempfile",
            "glob",
            "fnmatch",
            "linecache",
            "fileinput",
            "stat",
            "filecmp",
            "calendar",
            "zoneinfo",
            "locale",
            "gettext",
            "io",
            "traceback",
            "inspect",
            "types",
            "copy",
            "pprint",
            "reprlib",
            "enum",
            "contextlib",
            "abc",
            "atexit",
            "gc",
            "weakref",
            "typing",
            "dataclasses",
            "heapq",
            "bisect",
            "array",
            "struct",
            "codecs",
            "unicodedata",
            "stringprep",
            "ast",
        }
        return module_name in stdlib_modules

    def _map_to_pypi_packages(self, package_names: Set[str]) -> List[str]:
        """Map module names to PyPI package names with versions."""
        packages = set()

        for mod in package_names:
            try:
                dist = imd.distribution(mod)
                package_name = dist.metadata["Name"]
                version = dist.version  # Get the installed version
                package_with_version = f"{package_name}=={version}"
                packages.add(package_with_version)
                logger.debug(f"Mapped {mod} -> {package_with_version}")
            except imd.PackageNotFoundError:
                # Skip stdlib or local modules
                logger.debug(f"Skipping {mod} (stdlib or local)")
                continue

        package_list = list(packages)
        logger.debug(f"Final package list: {package_list}")
        return package_list

    def _merge_requirements(
        self, auto_detected: List[str], explicit: List[str]
    ) -> List[str]:
        """Merge requirements, preferring explicit versions over auto-detected ones."""
        import re

        # Parse package names from requirements
        def parse_requirement(req: str) -> tuple:
            """Extract package name and version spec from requirement string."""
            # Match patterns like: package==1.0, package>=1.0, package~=1.0, etc.
            match = re.match(r"^([a-zA-Z0-9\-_]+)(.*)$", req)
            if match:
                return match.group(1).lower(), match.group(2)
            return req.lower(), ""

        # Build a map of explicit requirements
        explicit_map = {}
        for req in explicit:
            pkg_name, version_spec = parse_requirement(req)
            explicit_map[pkg_name] = req

        # Build final requirements list
        final_requirements = []
        seen_packages = set()

        # First, add all explicit requirements
        for req in explicit:
            final_requirements.append(req)
            pkg_name, _ = parse_requirement(req)
            seen_packages.add(pkg_name)

        # Then add auto-detected requirements that don't conflict
        for req in auto_detected:
            pkg_name, _ = parse_requirement(req)
            if pkg_name not in seen_packages:
                final_requirements.append(req)
                seen_packages.add(pkg_name)
            else:
                logger.debug(
                    f"Skipping auto-detected {req}, using explicit version instead"
                )

        # Always ensure fleet-python is included
        if "fleet-python" not in seen_packages:
            final_requirements.append("fleet-python")

        return sorted(final_requirements)

    def _build_function_bundle(
        self,
        func: Callable,
        src: str,
        requirements: List[str],
        extracted_code: Dict[str, str],
        project_root: Path,
        verifier_id: Optional[str] = None,
        same_module_deps: List[str] = [],
    ) -> bytes:
        """Build a function bundle with statically extracted code."""

        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = Path(temp_dir) / "build"
            build_dir.mkdir()

            try:
                # Create requirements.txt
                requirements_file = build_dir / "requirements.txt"
                # Ensure fleet-python is always included
                if not requirements:
                    requirements = ["fleet-python"]
                elif "fleet-python" not in [
                    r.split("==")[0].split(">=")[0] for r in requirements
                ]:
                    requirements.append("fleet-python")
                requirements_file.write_text("\n".join(sorted(set(requirements))))

                # Extract same-module dependencies
                same_module_code = ""
                if same_module_deps:
                    # Read the module file that contains the verifier function
                    mod_file = Path(func.__code__.co_filename)
                    with open(mod_file, "r", encoding="utf-8") as f:
                        module_content = f.read()

                    # Extract the source code for each dependency
                    for dep_name in same_module_deps:
                        dep_src = self._extract_function_source(
                            module_content, dep_name
                        )
                        if dep_src:
                            same_module_code += f"\n{dep_src}\n"
                            logger.debug(
                                f"Extracted same-module dependency: {dep_name}"
                            )

                # Create verifier.py with the main function
                verifier_file = build_dir / "verifier.py"
                verifier_content = f"""# Auto-generated verifier module
{same_module_code}
{src}
"""
                verifier_file.write_text(verifier_content)

                # Create local files with only extracted functions
                for relative_path, code in extracted_code.items():
                    dest_path = build_dir / relative_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    extracted_content = f"""# Extracted module (static analysis)
{code}
"""
                    dest_path.write_text(extracted_content)
                    logger.debug(f"Created extracted file: {relative_path}")

                    # Ensure __init__.py files exist
                    self._ensure_init_files(Path(relative_path), build_dir)

                # Create zip bundle
                return self._create_zip_bundle(build_dir)

            except Exception as e:
                logger.error(f"Failed to build function bundle: {e}")
                raise RuntimeError(f"Function bundle creation failed: {e}")

    def _ensure_init_files(self, rel_path: Path, build_dir: Path):
        """Ensure __init__.py files exist for all parent directories."""
        current = rel_path.parent

        while current != Path("."):
            init_file = build_dir / current / "__init__.py"
            if not init_file.exists():
                init_file.parent.mkdir(parents=True, exist_ok=True)
                init_file.write_text("# Auto-generated __init__.py")
                logger.debug(f"Created __init__.py: {current}")
            current = current.parent

    def _create_zip_bundle(self, build_dir: Path) -> bytes:
        """Create the final zip bundle in memory."""
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in build_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(build_dir)
                    zf.write(file_path, arcname)

        bundle_size = len(zip_buffer.getvalue())
        logger.debug(f"Created function bundle ({bundle_size:,} bytes)")
        return zip_buffer.getvalue()

    def _extract_function_source(
        self, module_content: str, function_name: str
    ) -> Optional[str]:
        """Extract the source code of a specific function from module content."""
        try:
            tree = ast.parse(module_content)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == function_name:
                    # Get the source lines for this function
                    lines = module_content.split("\n")
                    start_line = node.lineno - 1
                    end_line = (
                        node.end_lineno
                        if hasattr(node, "end_lineno")
                        else start_line + 1
                    )

                    # Extract the function lines
                    func_lines = lines[start_line:end_line]

                    # Find the minimum indentation (excluding empty lines)
                    min_indent = float("inf")
                    for line in func_lines:
                        if line.strip():  # Non-empty line
                            indent = len(line) - len(line.lstrip())
                            min_indent = min(min_indent, indent)

                    # Remove the common indentation
                    if min_indent < float("inf"):
                        func_lines = [
                            line[min_indent:] if line.strip() else line
                            for line in func_lines
                        ]

                    return "\n".join(func_lines)

        except Exception as e:
            logger.warning(f"Failed to extract function {function_name}: {e}")

        return None

    def _get_function_source_without_decorator(self, func: Callable) -> str:
        """Get function source code without the @verifier decorator."""
        source = inspect.getsource(func)
        lines = source.split("\n")

        # Find where the function definition starts
        func_start = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("def "):
                func_start = i
                break

        if func_start == -1:
            # Couldn't find function definition, return original
            return source

        # Return only from the function definition onward
        func_lines = lines[func_start:]

        # Remove common indentation
        if func_lines:
            # Find minimum indentation (excluding empty lines)
            min_indent = float("inf")
            for line in func_lines:
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    min_indent = min(min_indent, indent)

            # Remove the common indentation
            if min_indent < float("inf"):
                func_lines = [
                    line[min_indent:] if line.strip() else line for line in func_lines
                ]

        return "\n".join(func_lines)
