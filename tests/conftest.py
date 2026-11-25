import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "experiments"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# experiments/run_*.py 는 실행 스크립트이지 테스트가 아니다
collect_ignore_glob = [str(ROOT / "experiments" / "*.py")]
