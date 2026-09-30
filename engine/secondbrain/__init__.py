"""__init__.py - Paket der 2ndBrain-Engine fuer einen Obsidian-Vault: Automatik, Einarbeiten,
Vor- und Nachbereiten, Stand, Glossar und MCP-Server.

Befehlszeile: `2ndbrain <befehl>` oder `python -m secondbrain <befehl>` (siehe befehle.py).
Die Module liegen flach in diesem Paket und importieren einander ueber ihren Namen
(`import vault_paths as vp`); `__main__` und die meisten Module setzen dafuer den Paketordner
in sys.path. Der Code liegt nicht im Vault - Konfiguration und Daten stehen in dessen `.2ndbrain/`.
"""
__version__ = "0.12.0"
