"""Fleet SDK Verifier Decorator - Async Version.

Provides a @verifier decorator that can wrap any sync function to support
both local execution and remote execution via .remote() method.

The client performs dependency detection and creates lightweight bundles.
The server uses uv to resolve dependencies and create the execution environment.
"""

import inspect
import functools
import traceback
import hashlib
import json
import tempfile
import zipfile
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union, List, Set
from io import BytesIO
import uuid
import logging
import ast
from collections import defaultdict

import modulegraph2  # Required dependency for comprehensive dependency detection

try:
    import importlib.metadata as imd
except ImportError:
    import importlib_metadata as imd

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


class FunctionBundler:
    """Handles dependency detection and bundle creation for verifier functions with tree shaking."""
    
    def __init__(self):
        self.cache_dir = Path.home() / ".fleet" / "verifier_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bundle_cache = {}  # func_signature -> bundle_bytes
    
    def create_bundle(
        self, 
        func: Callable,
        extra_requirements: Optional[List[str]] = None,
        verifier_id: Optional[str] = None
    ) -> bytes:
        """Create a tree-shaken bundle with minimal code."""
        
        # Create cache key
        src = inspect.getsource(func)
        cache_key = f"{src}{extra_requirements or []}{verifier_id or ''}"
        
        if cache_key in self.bundle_cache:
            logger.debug(f"Using cached bundle for {func.__name__}")
            return self.bundle_cache[cache_key]
        
        logger.info(f"Creating optimized bundle for {func.__name__}")
        
        # 1. Parse the main function and find dependencies
        mod_file = Path(func.__code__.co_filename)
        project_root = self._find_project_root(mod_file)
        
        # 2. Analyze dependencies with tree shaking
        dependencies = self._analyze_dependencies_with_tree_shaking(func, mod_file, project_root)
        
        # 3. Map external packages
        requirements = self._map_to_pypi_packages(dependencies['external_packages'])
        if extra_requirements:
            requirements.extend(extra_requirements)
        requirements.append("fleet-python")
        
        # 4. Build optimized bundle
        bundle_bytes = self._build_optimized_bundle(
            func, src, requirements, dependencies['extracted_code'], project_root, verifier_id
        )
        
        # Cache the result
        self.bundle_cache[cache_key] = bundle_bytes
        return bundle_bytes
    
    def _analyze_dependencies_with_tree_shaking(
        self, 
        func: Callable, 
        mod_file: Path, 
        project_root: Path
    ) -> Dict[str, Any]:
        """Analyze dependencies and extract only required functions."""
        
        # Parse the main function - handle indentation
        main_func_code = inspect.getsource(func)
        # Remove decorator and normalize indentation
        main_func_lines = main_func_code.split('\n')
        
        # Find the actual function definition line (skip decorators)
        func_start_idx = 0
        for i, line in enumerate(main_func_lines):
            if line.strip().startswith('def '):
                func_start_idx = i
                break
        
        # Extract function definition and body
        func_lines = main_func_lines[func_start_idx:]
        
        # Remove common leading whitespace
        if func_lines:
            import textwrap
            normalized_func_code = textwrap.dedent('\n'.join(func_lines))
            main_func_ast = ast.parse(normalized_func_code)
        else:
            main_func_ast = ast.parse('')
        
        # Find all import statements in the main function
        imports_in_func = self._extract_imports_from_ast(main_func_ast)
        
        # Also analyze the module containing the function
        with open(mod_file, 'r', encoding='utf-8') as f:
            module_content = f.read()
        module_ast = ast.parse(module_content)
        
        # Find imports at module level
        module_imports = self._extract_imports_from_ast(module_ast)
        
        # Combine all imports
        all_imports = {**imports_in_func, **module_imports}
        
        # Separate local and external imports
        local_imports = {}
        external_packages = set()
        extracted_code = {}
        
        for import_type, import_list in all_imports.items():
            for import_info in import_list:
                if import_type == 'from_import':
                    module_name = import_info['module']
                    imported_names = import_info['names']
                    
                    # Try to resolve as local import
                    local_path = self._resolve_local_import(module_name, mod_file, project_root)
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
                        
                elif import_type == 'import':
                    module_name = import_info['name']
                    # Check if it's a local or external import
                    if not self._is_likely_stdlib(module_name):
                        try:
                            dist = imd.distribution(module_name)
                            external_packages.add(dist.metadata['Name'])
                        except imd.PackageNotFoundError:
                            # Could be local, but for now assume external
                            external_packages.add(module_name)
        
        return {
            'local_imports': local_imports,
            'external_packages': external_packages,
            'extracted_code': extracted_code
        }
    
    def _extract_imports_from_ast(self, tree: ast.AST) -> Dict[str, List[Dict[str, Any]]]:
        """Extract import statements from AST."""
        imports = defaultdict(list)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports['import'].append({
                        'name': alias.name,
                        'asname': alias.asname
                    })
            elif isinstance(node, ast.ImportFrom):
                if node.module:  # Skip relative imports without module
                    imports['from_import'].append({
                        'module': node.module,
                        'names': [alias.name for alias in node.names],
                        'level': node.level
                    })
        
        return dict(imports)
    
    def _extract_specific_functions(self, file_path: Path, function_names: List[str]) -> str:
        """Extract specific functions from a file, including their dependencies."""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
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
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                            called_func = node.func.id
                            if called_func in functions and called_func not in required_functions:
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
                    lines = content.split('\n')
                    start_line = node.lineno - 1
                    end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line + 1
                    code = '\n'.join(lines[start_line:end_line])
                    extracted_code.append(code)
            
            result = '\n\n'.join(extracted_code)
            logger.debug(f"Extracted {len(extracted_code)} items from {file_path}")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to extract functions from {file_path}: {e}")
            # Fallback to including the entire file
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
    
    def _resolve_local_import(self, module_name: str, current_file: Path, project_root: Path) -> Optional[Path]:
        """Try to resolve a module name to a local file path."""
        
        # Handle dotted imports (e.g., utils.helpers -> utils/helpers.py)
        module_parts = module_name.split('.')
        
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
            'pyproject.toml', 'setup.py', 'setup.cfg', 
            '.git', '.hg', 'requirements.txt', 'Pipfile'
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
            'os', 'sys', 'json', 'datetime', 'time', 'random', 'math', 're', 
            'collections', 'itertools', 'functools', 'operator', 'pathlib',
            'urllib', 'http', 'socket', 'threading', 'multiprocessing',
            'logging', 'argparse', 'configparser', 'csv', 'xml', 'html',
            'base64', 'hashlib', 'hmac', 'secrets', 'uuid', 'pickle',
            'sqlite3', 'dbm', 'zipfile', 'tarfile', 'gzip', 'shutil',
            'tempfile', 'glob', 'fnmatch', 'linecache', 'fileinput',
            'stat', 'filecmp', 'calendar', 'zoneinfo', 'locale',
            'gettext', 'io', 'traceback', 'inspect', 'types', 'copy',
            'pprint', 'reprlib', 'enum', 'contextlib', 'abc', 'atexit',
            'gc', 'weakref', 'typing', 'dataclasses', 'heapq', 'bisect',
            'array', 'struct', 'codecs', 'unicodedata', 'stringprep', 'ast'
        }
        return module_name in stdlib_modules
    
    def _map_to_pypi_packages(self, package_names: Set[str]) -> List[str]:
        """Map module names to PyPI package names."""
        packages = set()
        
        for mod in package_names:
            try:
                dist = imd.distribution(mod)
                packages.add(dist.metadata['Name'])
                logger.debug(f"Mapped {mod} -> {dist.metadata['Name']}")
            except imd.PackageNotFoundError:
                # Skip stdlib or local modules
                logger.debug(f"Skipping {mod} (stdlib or local)")
                continue
        
        package_list = list(packages)
        logger.debug(f"Final package list: {package_list}")
        return package_list
    
    def _build_optimized_bundle(
        self, 
        func: Callable,
        src: str,
        requirements: List[str],
        extracted_code: Dict[str, str],
        project_root: Path,
        verifier_id: Optional[str] = None
    ) -> bytes:
        """Build an optimized bundle with tree-shaken code."""
        
        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = Path(temp_dir) / "build"
            build_dir.mkdir()
            
            try:
                # Create requirements.txt
                requirements_file = build_dir / "requirements.txt"
                requirements_file.write_text("\n".join(sorted(set(requirements))))
                
                # Create verifier.py with the main function
                verifier_file = build_dir / "verifier.py"
                verifier_content = f"""# Auto-generated verifier module (tree-shaken)
{src}
"""
                verifier_file.write_text(verifier_content)
                
                # Create optimized local files with only extracted functions
                for relative_path, code in extracted_code.items():
                    dest_path = build_dir / relative_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    optimized_content = f"""# Optimized module (tree-shaken)
{code}
"""
                    dest_path.write_text(optimized_content)
                    logger.debug(f"Created optimized file: {relative_path}")
                    
                    # Ensure __init__.py files exist
                    self._ensure_init_files(Path(relative_path), build_dir)
                
                # Create manifest
                manifest_file = build_dir / "manifest.json"
                manifest = {
                    'function_name': func.__name__,
                    'entry': f'verifier.{func.__name__}',
                    'version': '1.0',
                    'optimized': True,
                    'tree_shaken': True,
                    'verifier_id': verifier_id
                }
                manifest_file.write_text(json.dumps(manifest, indent=2))
                
                # Create zip bundle
                return self._create_zip_bundle(build_dir)
                
            except Exception as e:
                logger.error(f"Failed to build optimized bundle: {e}")
                raise RuntimeError(f"Optimized bundle creation failed: {e}")
    
    def _ensure_init_files(self, rel_path: Path, build_dir: Path):
        """Ensure __init__.py files exist for all parent directories."""
        current = rel_path.parent
        
        while current != Path('.'):
            init_file = build_dir / current / "__init__.py"
            if not init_file.exists():
                init_file.parent.mkdir(parents=True, exist_ok=True)
                init_file.write_text("# Auto-generated __init__.py")
                logger.debug(f"Created __init__.py: {current}")
            current = current.parent
    
    def _create_zip_bundle(self, build_dir: Path) -> bytes:
        """Create the final zip bundle in memory."""
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in build_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(build_dir)
                    zf.write(file_path, arcname)
        
        bundle_size = len(zip_buffer.getvalue())
        logger.debug(f"Created optimized zip bundle ({bundle_size:,} bytes)")
        return zip_buffer.getvalue()


class AsyncVerifiedFunction:
    """Wrapper for a verified function that supports local execution with env-first pattern."""
    
    def __init__(
        self,
        func: F,
        name: str,
        verifier_id: str,
        extra_requirements: Optional[List[str]] = None
    ):
        self.func = func
        self.name = name
        self.verifier_id = verifier_id
        self.extra_requirements = extra_requirements or []
        self._bundler = FunctionBundler()
        self._bundle_sent_to_envs = set()  # Track environments that have our bundle
        
        # Copy function metadata
        functools.update_wrapper(self, func)
    
    async def __call__(self, env, *args, **kwargs) -> float:
        """Local execution of the verifier function with env as first parameter."""
        try:
            result = self.func(env, *args, **kwargs)
            
            # Handle different return types
            if isinstance(result, (int, float)):
                # Direct score return
                return float(result)
            elif isinstance(result, dict) and "score" in result:
                return float(result["score"])
            else:
                # Try to extract score from object attributes
                if hasattr(result, 'score'):
                    return float(result.score)
                else:
                    raise ValueError(f"Verifier function must return a score (number). Got {type(result)}")
                    
        except Exception as e:
            logger.error(f"Error in verifier {self.name}: {e}")
            # Return error score 0
            return 0.0
    
    async def remote(self, env, *args, **kwargs) -> float:
        """Remote execution of the verifier function with bundle tracking optimization."""
        try:
            # Generate environment identifier for tracking
            env_id = self._get_env_id(env)
            
            if env_id not in self._bundle_sent_to_envs:
                # First time sending to this environment - send bundle
                logger.info(f"Sending bundle for {self.name} to environment {env_id}")
                bundle_data = self._bundler.create_bundle(
                    self.func, 
                    self.extra_requirements,
                    self.verifier_id
                )
                
                response = await env.instance.execute_verifier_remote(
                    bundle_data=bundle_data,
                    verifier_id=self.verifier_id,
                    args=args,
                    kwargs=kwargs
                )
                
                # Mark environment as having our bundle
                self._bundle_sent_to_envs.add(env_id)
                
            else:
                # Bundle already sent - just execute using verifier_id
                logger.info(f"Executing cached bundle for {self.name} on environment {env_id}")
                try:
                    response = await env.instance.execute_verifier_by_id(
                        verifier_id=self.verifier_id,
                        args=args,
                        kwargs=kwargs
                    )
                except Exception as e:
                    # Handle server restart or bundle not found
                    if self._is_bundle_not_found_error(e):
                        logger.info(f"Bundle not found on server, re-sending for {self.name}")
                        # Remove from tracking and retry with bundle
                        self._bundle_sent_to_envs.discard(env_id)
                        return await self.remote(env, *args, **kwargs)
                    else:
                        raise
            
            # Handle response
            if response.success:
                return self._process_result(response.result)
            else:
                self._raise_remote_error(response.error)
                
        except Exception as e:
            logger.error(f"Remote execution failed for {self.name}: {e}")
            raise
    
    def _process_result(self, result: Any) -> float:
        """Process remote execution result, handling different return types."""
        # Handle different return types like local execution
        if isinstance(result, (int, float)):
            return float(result)
        elif isinstance(result, dict) and "score" in result:
            return float(result["score"])
        else:
            # Try to extract score from object attributes
            if hasattr(result, 'score'):
                return float(result.score)
            else:
                # Best effort conversion
                try:
                    return float(result)
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert result to float: {result}")
                    return 0.0
    
    def _raise_remote_error(self, error_info: Dict[str, Any]):
        """Reconstruct remote error as local exception."""
        error_type = error_info.get("type", "RuntimeError")
        message = error_info.get("message", "Remote execution failed")
        traceback_str = error_info.get("traceback", "")
        
        # Create a rich error message
        full_message = f"""
Remote verifier execution failed:
{message}

Remote traceback:
{traceback_str}
        """.strip()
        
        # Try to raise the original exception type
        try:
            exception_class = getattr(__builtins__, error_type, RuntimeError)
            raise exception_class(full_message)
        except:
            raise RuntimeError(full_message)
    
    def _get_env_id(self, env) -> str:
        """Generate a unique identifier for the environment."""
        # Use instance base URL or similar unique identifier
        if hasattr(env, 'instance') and hasattr(env.instance, 'base_url'):
            return f"{env.instance.base_url}"
        else:
            # Fallback to object id (less ideal but works)
            return str(id(env))
    
    def _is_bundle_not_found_error(self, error: Exception) -> bool:
        """Check if the error indicates the bundle was not found on the server."""
        # Check for common "bundle not found" error patterns
        error_msg = str(error).lower()
        return (
            "bundle not found" in error_msg or
            "verifier not found" in error_msg or
            "404" in error_msg or
            "not found" in error_msg
        )


def verifier(
    name: Optional[str] = None,
    verifier_id: Optional[str] = None,
    extra_requirements: Optional[List[str]] = None
) -> Callable[[F], AsyncVerifiedFunction]:
    """
    Decorator to create a verifier function with env-first pattern.
    
    The decorated function must take 'env' as its first parameter, making it explicit
    that verifiers operate within an environment context. This makes verifiers reusable
    across different environments.
    
    Args:
        name: Optional name for the verifier. Defaults to function name.
        verifier_id: Optional unique ID for the verifier. Defaults to generated UUID.
        extra_requirements: Additional PyPI packages needed by the verifier.
    
    Example:
        @verifier(
            name="test_database_state",
            extra_requirements=["torch==2.3.0"]
        )
        def check_user_count(env, expected_count: int) -> float:
            db = env.db()
            result = db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0
        
        # Usage with different environments
        env1 = flt.env.make("fira")
        env2 = flt.env.make("another_env")
        
        # Local execution
        result = await check_user_count(env1, 5)
        result = await check_user_count(env2, 5)  # Same verifier, different env
        
        # Remote execution
        result = await check_user_count.remote(env1, 5)
    """
    def decorator(func: F) -> AsyncVerifiedFunction:
        verifier_name = name or func.__name__
        verifier_uuid = verifier_id or str(uuid.uuid4())
        
        return AsyncVerifiedFunction(
            func,
            verifier_name,
            verifier_uuid,
            extra_requirements
        )
    
    return decorator