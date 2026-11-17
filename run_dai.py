"""Run D-AI without installing: python run_dai.py research "question" --url ..."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dai.cli.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
