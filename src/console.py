# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
from rich.console import Console


# Shared Rich console used by the command-line application.
# Force terminal mode so colored status output remains consistent when output
# is redirected or invoked by another local process.
console = Console(force_terminal=True)
