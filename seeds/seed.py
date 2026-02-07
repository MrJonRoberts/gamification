from pathlib import Path
import sys

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from seeds.manage_data import run_reset_and_seed


def main() -> None:
    run_reset_and_seed()


if __name__ == '__main__':
    main()
