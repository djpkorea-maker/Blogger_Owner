"""PyInstaller entry point (normal .py supports both console modes)."""
import sys
from r3studio.startup import launch,smoke_test
if __name__=='__main__':raise SystemExit(smoke_test() if '--smoke-test' in sys.argv else launch(diagnostic='--diagnostic' in sys.argv))
