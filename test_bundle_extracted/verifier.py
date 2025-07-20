# Auto-generated verifier module

def helper_function(x: int, y: int) -> int:
    """Helper function that will be bundled."""
    return x + y

@verifier(name="test_bundler", extra_requirements=["numpy>=1.20.0"])
def test_verifier(env: AsyncEnvironment, threshold: int = 10) -> float:
    """Test verifier that uses a helper function."""
    result = helper_function(5, 7)
    result2 = helper_function_four(5, 7)
    return 1.0 if result > threshold else 0.0

