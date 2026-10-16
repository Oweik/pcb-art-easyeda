"""Validate portable skill metadata, resource links and invocation metadata."""
from pathlib import Path
import re
import yaml

root=Path(__file__).resolve().parents[1]
content=(root/'SKILL.md').read_text(encoding='utf-8')
match=re.match(r'^---\n(.*?)\n---\n',content,re.S)
if not match:
    raise SystemExit('Missing skill frontmatter')
metadata=yaml.safe_load(match.group(1))
if metadata.get('name')!='pcb-art-easyeda' or not isinstance(metadata.get('description'),str) or not metadata['description'].strip():
    raise SystemExit('Invalid skill name/description')
for path in [root/'SKILL.md',*(root/'references').glob('*.md')]:
    for link in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
        if '://' in link or link.startswith('#'):
            continue
        if not (path.parent/link.split('#')[0]).exists():
            raise SystemExit(f'Missing reference: {path.name}: {link}')
ui=yaml.safe_load((root/'agents/openai.yaml').read_text(encoding='utf-8'))
if '$pcb-art-easyeda' not in ui['interface']['default_prompt'] or ui.get('policy',{}).get('allow_implicit_invocation',True) is not True:
    raise SystemExit('Invalid invocation configuration')
print('Skill metadata, resource links and invocation configuration passed')
