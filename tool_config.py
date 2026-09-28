"""Local defaults and immutable per-session catalogs; never rewrite shipped tools."""
import json
import os
from pathlib import Path
import re
import uuid

LOCAL_TOOLS_CONFIG = 'kali_tools.json'


def default_tools_path(root):
    root = Path(root)
    local = root / LOCAL_TOOLS_CONFIG
    return local if local.is_file() else root / 'kali_tools.default.json'


def validate_tools(config):
    if not isinstance(config, dict) or not isinstance(config.get('tools'), list):
        raise ValueError('Tool configuration must contain a tools list')
    if any(not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or not tool['name'].strip()
           for tool in config['tools']):
        raise ValueError('Each tool must have a nonempty name')
    return config


def session_tools_path(root, run_id, config):
    validate_tools(config)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', run_id) or run_id in ('.', '..'):
        raise ValueError('Invalid run ID for tool configuration')
    root = Path(root).resolve()
    directory = root / 'runs' / run_id
    if not directory.resolve().is_relative_to(root / 'runs'):
        raise ValueError('Tool configuration must remain inside runs')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('tools-config-' + uuid.uuid4().hex + '.json')
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(config, stream, indent=2)
        stream.write('\n')
    return str(path)
