"""Verify the controlled native extension before loading its grammar/data."""
import hashlib
import json
from pathlib import Path


def verify_implementation(root=None):
    root = Path(root) if root is not None else Path(__file__).parent
    manifest = json.loads((root / 'implementation.json').read_text())
    if manifest.get('schema') != 'wiki22.native.extension.identity.v1':
        raise ValueError('Unknown native extension identity')
    required = {'study_reader.py', 'discourse_graph.py', 'factuality.py', 'resources/factuality_weights.json', 'dependency_reader.py', 'resources/parser_runtime.json', 'language_engine.py', 'session.py', 'identity.py', '__init__.py',
                'resources/grammatica.json', 'resources/lessico_seme.json',
                'resources/regole_ragionamento.json', 'resources/reading_curriculum.json'}
    if set(manifest['files']) != required:
        raise ValueError('Incomplete native extension identity')
    for name, expected in manifest['files'].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest().upper()
        if actual != expected:
            raise ValueError('Native extension identity drift: ' + name)
    return manifest
