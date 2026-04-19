import subprocess
import sys
from pathlib import Path

repo_root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
sys.path.insert(0, str(repo_root))

from src.capture.git_hook import run

project = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()).name
run(project)
