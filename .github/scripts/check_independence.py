"""Fail if PayPilotLabs HRMS imports or requires another PayPilotLabs product."""
import pathlib, re, sys

PACKAGE = "hrms"
FORBIDDEN = ['crm', 'helpdesk', 'insights', 'builder', 'erpnext']
ALLOWED_FILES = []  # optional, guarded integrations
pattern = re.compile(r"^\s*(from|import)\s+(" + "|".join(FORBIDDEN) + r")(\.|\s|$)")
problems = []
for path in pathlib.Path(PACKAGE).rglob("*.py"):
    if "node_modules" in path.parts or path.relative_to(PACKAGE).as_posix() in ALLOWED_FILES:
        continue
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if pattern.match(line):
            problems.append(f"{path}:{n}: {line.strip()}")
hooks = pathlib.Path(PACKAGE, "hooks.py").read_text(encoding="utf-8")
m = re.search(r"^required_apps\s*=\s*\[(.*?)\]", hooks, re.M | re.S)
for app in re.findall(r"[\"']([a-z_]+)[\"']", m.group(1) if m else ""):
    if app in FORBIDDEN:
        problems.append(f"hooks.py: required_apps lists {app}")
print("\n".join(problems) or "OK: no imports of other PayPilotLabs products")
sys.exit(1 if problems else 0)
