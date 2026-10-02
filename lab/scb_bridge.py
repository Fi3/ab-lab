"""Import alias for existing evaluator clients; benchmark owns the bridge."""
import sys
from benchmarks import scb_bridge as implementation

if __name__ == "__main__":
    sys.exit(implementation.main())
else:
    sys.modules[__name__] = implementation
