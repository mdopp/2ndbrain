"""__main__.py - Einstieg fuer `2ndbrain <befehl>` und `python -m secondbrain <befehl>`.

Setzt den Paketordner in sys.path und uebergibt an befehle.main() - dort stehen alle Befehle.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    import befehle
    return befehle.main() or 0


if __name__ == "__main__":
    sys.exit(main())
