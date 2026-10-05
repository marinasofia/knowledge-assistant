"""Scan tracked first-party text for common credential leaks and unsafe local files."""
import pathlib
import re
import subprocess

paths = subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
patterns = [r'gh[pousr]_[A-Za-z0-9]{30,}',r'sk-ant-[A-Za-z0-9_-]{20,}',
            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
failures = []
for name in filter(None,paths):
    path = pathlib.Path(name)
    if name == '.env' or name.startswith(('.data/','.venv/')):
        failures.append(name+': private runtime file')
    try:
        text = path.read_text()
    except (UnicodeError,OSError):
        continue
    for pattern in patterns:
        if re.search(pattern,text):
            failures.append(name+': credential pattern')
    if path.suffix not in {'.lock','.json'} and any(c in text for c in ['\u2013','\u2014']):
        failures.append(name+': prohibited punctuation')
if failures:
    raise SystemExit('\n'.join(failures))
print('Tracked-file hygiene checks passed.')
