import re

def convert_verifier_string(verifier_str: str) -> str:
    """
    Convert a verifier function string from the old format (env: Environment) 
    to the new format (before: DatabaseSnapshot, after: DatabaseSnapshot).
    
    Args:
        verifier_str: The original verifier function as a string
        
    Returns:
        The converted verifier function string
    """
    # First, handle escaped newlines in the input
    verifier_str = verifier_str.replace('\\n', '\n')
    
    # Extract function name, docstring, and body
    # More flexible pattern that accepts both int and float return types
    func_pattern = r'def\s+(\w+)\s*\(\s*env(?:\s*:\s*Environment)?\s*,?\s*final_answer(?:\s*:\s*str\s*\|\s*None)?\s*(?:=\s*None)?\s*\)\s*->\s*(?:float|int):\s*\n((?:\s*""".*?"""\s*\n)?)(.*)'
    match = re.match(func_pattern, verifier_str.strip(), re.DOTALL)
    
    if not match:
        # Try with multiline pattern
        func_pattern_multiline = r'def\s+(\w+)\s*\(\s*\n?\s*env(?:\s*:\s*Environment)?\s*,?\s*\n?\s*final_answer(?:\s*:\s*str\s*\|\s*None)?\s*(?:=\s*None)?\s*\n?\s*\)\s*->\s*(?:float|int):\s*\n((?:\s*""".*?"""\s*\n)?)(.*)'
        match = re.match(func_pattern_multiline, verifier_str.strip(), re.DOTALL)
        
        if not match:
            raise ValueError("Could not parse verifier function. Expected format: def function_name(env: Environment, final_answer: str | None = None) -> float/int:")
    
    func_name = match.group(1)
    docstring = match.group(2).strip()
    body = match.group(3)
    
    # Find all unique env.db() calls
    db_calls = re.findall(r'env\.db\("(\w+)"\)', body)
    unique_db_names = list(dict.fromkeys(db_calls))  # Remove duplicates while preserving order
    
    # Build the new function
    new_func = f'''def {func_name}(
    before: DatabaseSnapshot, after: DatabaseSnapshot, transcript: str | None = None
) -> int:
    class Environment:
        def db(self, name: str) -> DatabaseSnapshot:'''
    
    # Build the db method based on found database names
    if unique_db_names:
        conditions = []
        for db_name in unique_db_names:
            if db_name == "seed":
                conditions.append('before if name == "seed"')
            elif db_name == "current":
                conditions.append('after')
            else:
                # Handle other database names if needed
                conditions.append(f'None  # Handle "{db_name}"')
        
        if len(conditions) == 2 and "seed" in unique_db_names and "current" in unique_db_names:
            new_func += f'''
            return before if name == "seed" else after'''
        else:
            # More complex mapping if needed
            new_func += f'''
            if name == "seed":
                return before
            elif name == "current":
                return after
            else:
                raise ValueError(f"Unknown database name: {{name}}")'''
    else:
        new_func += '''
            return before if name == "seed" else after'''
    
    new_func += '''

        @property
        def instance(self):
            return self
        
        def load(self):
            pass

    def verifier(env: Environment, final_answer: str | None = None) -> float:'''
    
    if docstring:
        new_func += f'\n        {docstring}'
    
    # First, find the minimum indentation in the body (excluding empty lines)
    body_lines = body.splitlines()
    min_indent = float('inf')
    for line in body_lines:
        if line.strip():  # Non-empty line
            indent_len = len(line) - len(line.lstrip())
            min_indent = min(min_indent, indent_len)
    
    # If we didn't find any non-empty lines, set min_indent to 0
    if min_indent == float('inf'):
        min_indent = 0
    
    # Now strip the minimum indentation and re-indent to 8 spaces
    if body_lines:
        indented_lines = []
        for line in body_lines:
            if line.strip():  # Non-empty line
                # Remove the minimum indentation and add 8 spaces
                stripped_line = line[min_indent:] if len(line) > min_indent else line.lstrip()
                indented_lines.append('        ' + stripped_line)
            else:  # Empty line
                indented_lines.append('')
        
        indented_body = '\n'.join(indented_lines)
        new_func += f'\n{indented_body}'
    
    # Add the return statement
    new_func += '\n\n    return verifier(Environment(), transcript)'
    
    return new_func