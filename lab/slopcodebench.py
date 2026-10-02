"""Keep the established setup command; implementation belongs to the benchmark."""
import sys
from benchmarks import slopcodebench as implementation

if __name__ == "__main__":
    implementation.main()
else:
    sys.modules[__name__] = implementation
