"""SELF001/CAP001/STATE001 on the installed Wiki22 source and reviewed probes."""
import json
from pathlib import Path

from .kernel.common import digest
from .kernel.scanner import scan
from .kernel.model import build_model
from .kernel.probes import ProbeLedger, run_probe
from .kernel.queries import SelfQuery


class SelfInspection:
    def __init__(self, product_root):
        self.root = Path(product_root).resolve(strict=True)
        self.allowlist_path = self.root / 'src/wiki22/self_inspection/probe_allowlist.json'
        self.model = None
        self.probes = []

    def inspect(self, *, run_reviewed_probes=True):
        allowlist = json.loads(self.allowlist_path.read_text())
        if allowlist.get('schema') != 'wiki22.self.probe.allowlist.v1':
            raise ValueError('Unknown product probe allowlist')
        approved = allowlist['files']
        if any((self.root / name).is_symlink() or not (self.root / name).resolve().is_relative_to(self.root)
               for name in approved):
            raise ValueError('Unsafe product probe input')
        # Source, resources and the reviewed allowlist all invalidate receipts.
        extras = [name for name in approved if not name.endswith('.py')]
        extras.append('src/wiki22/self_inspection/probe_allowlist.json')
        found = scan(self.root, [self.root], phase_rnd=False, additional_identity_files=extras)
        ledger = ProbeLedger()
        self.probes = []
        if run_reviewed_probes:
            for spec in allowlist['probes']:
                _, receipt = run_probe(self.root, found, spec, approved, ledger)
                self.probes.append(receipt)
        self.model = build_model(found, ledger, runtime_policy={
            'network_allowed': False, 'model_calls_allowed': False, 'production_allowed': False,
            'probe_execution': 'REVIEWED_HASH_BOUND_DISPOSABLE_COPY' if run_reviewed_probes else 'NONE'})
        self.query = SelfQuery(self.model, self.root, phase_rnd=False, additional_identity_files=extras)
        self.additional_identity_files = extras
        return self.summary()

    def summary(self):
        if self.model is None:
            return {'status': 'NOT_INSPECTED', 'verified_capabilities': 0}
        capabilities = self.model['CAPACITA']
        return {'status': 'PROBED' if self.probes else 'STATIC_ONLY',
                'source_tree_sha256': self.model['SOURCE_TREE_SHA256'],
                'components': len(self.model['COMPONENTI']), 'candidate_capabilities': len(capabilities),
                'verified_capabilities': sum(c['STATO_VERIFICA'] == 'VERIFICATA' for c in capabilities),
                'probe_pass': sum(p['status'] == 'PASS' for p in self.probes), 'probe_total': len(self.probes),
                'capabilities': [{'name': c['NOME'], 'component': c['COMPONENTE'],
                                  'status': c['STATO_VERIFICA'], 'proofs': c['SONDE_VERIFICATE']}
                                 for c in capabilities if c['STATO_VERIFICA'] == 'VERIFICATA'],
                'limitations': self.model['LIMITI'], 'runtime': self.model['RUNTIME']}

    def answer(self, question):
        if self.model is None:
            self.inspect(run_reviewed_probes=False)
        return self.query.answer(question)
