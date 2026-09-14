#!/usr/bin/env python3
"""Run one local cache composition from an explicit, prepared caller context.

This tutorial driver is not a general campaign runner. It never retries a stage,
and it never resumes an uncertain action by submitting it again. Inspect the
retained AG/Docket records first. Standing is a synthetic tutorial capability;
NQ, Pulse, Nightshift, AG, Docket and the local executor are actual participants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import time

from prepare_connected_cache_run import CONTEXT_SCHEMA, canonical, file_digest, read_regular, write_new
from connected_cache_process import BoundedProcessError, run_bounded

HERE = Path(__file__).resolve().parent
MAX_OUTPUT = 16 * 1024 * 1024


def source_digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_OUTPUT:
            raise ValueError('source is not a bounded regular file')
        data = stream.read(MAX_OUTPUT + 1)
        if len(data) > MAX_OUTPUT:
            raise ValueError('source grew past its bound')
        return hashlib.sha256(data).hexdigest()


class Run:
    def __init__(self, context: Path, accepted: dict | None = None,
                 qualification_pause_after_teardown: bool = False):
        self.context_path = context
        self.c = json.loads(read_regular(context, 128 * 1024))
        if self.c.get('schema') != CONTEXT_SCHEMA or self.c.get('governance', {}).get('standing_kind') != 'synthetic_fixture':
            raise ValueError('unsupported context or Standing capability')
        self.root = Path(self.c['root'])
        self.ids = self.c['identities']
        self.state = self.c['state']['state_paths']
        self.records = self.root / 'records/connected-run'
        self.phase = 'preflight'
        self.sequence = 0
        self.source_pins = {}
        self.accepted = accepted
        self.qualification_pause_after_teardown = qualification_pause_after_teardown
        self.env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': str(Path(self.c['files']['maude_source']['path']) / 'src'),
                    'DOCKER_HOST': 'unix:///var/run/docker.sock'}

    def program(self, name):
        return self.c['programs'][name]['path']

    def file(self, name):
        return self.c['files'][name]['path']

    def write(self, name, value):
        path = self.records / name
        write_new(path, value if isinstance(value, bytes) else canonical(value))
        return path

    def call(self, name, argv, *, output=None, timeout=120):
        # This detects drift in an operator-quiescent checkout; it is not an
        # atomic filesystem snapshot or protection against concurrent writers.
        for path, expected in self.source_pins.items():
            if source_digest(Path(path)) != expected:
                raise ValueError('source changed during this run; inspect original owners')
        self.sequence += 1
        self.phase = name
        prefix = f'{self.sequence:03d}-{name}'
        self.write(prefix + '.started.json', {'argv': [str(x) for x in argv],
                   'started_at_unix_ms': time.time_ns() // 1000000, 'retries': 0})
        stdout = self.records / (prefix + '.stdout')
        stderr = self.records / (prefix + '.stderr')
        try:
            result = run_bounded([str(x) for x in argv], env=self.env,
                                 stdout_path=stdout, stderr_path=stderr, timeout=timeout)
            self.write(prefix + '.finished.json', {'exit_code': result.returncode,
                       'finished_at_unix_ms': time.time_ns() // 1000000})
            if result.returncode:
                raise ValueError(f'{name} refused; inspect {stderr}; no automatic retry')
            if stdout.stat().st_size > MAX_OUTPUT or stderr.stat().st_size > MAX_OUTPUT:
                raise ValueError(f'{name} output exceeded bound; inspect original stage')
            raw = stdout.read_bytes()
            if output is not None:
                write_new(Path(output), raw)
            return raw
        except BoundedProcessError as error:
            self.write(prefix + '.uncertain.json', {
                'reason': str(error) + '; process termination is not attempt settlement',
                'stdout_bytes': error.result.stdout_bytes, 'stderr_bytes': error.result.stderr_bytes,
                'stdout_truncated': error.result.stdout_truncated, 'stderr_truncated': error.result.stderr_truncated,
                'next': 'inspect original owner state before any new submission'})
            raise

    def helper(self, name, *args, output=None):
        return self.call(name.removesuffix('.py'), [self.program('python'), HERE / 'helpers' / name, *args], output=output)

    def nq(self, name, *args, config=None, output=None):
        return self.call(name, [self.program('nq'), '--config', config or self.file('nq_config'), *args], output=output)

    def ns(self, name, *args, output=None):
        return self.call(name, [self.program('nightshift'), '--store', self.state['nightshift_store'], *args], output=output)

    def ag(self, name, *args, output=None):
        return self.call(name, [self.program('ag'), *args, '--database', self.state['ag_database']], output=output)

    def check_pins(self):
        for item in list(self.c['programs'].values()) + list(self.c['files'].values()):
            if 'sha256' in item and file_digest(Path(item['path'])) != item['sha256']:
                raise ValueError('enrolled file bytes changed: ' + item['path'])

    def preflight(self):
        self.check_pins()
        if self.qualification_pause_after_teardown and not self.accepted:
            raise ValueError('post-teardown pause is only for accepted synthetic qualification')
        if self.accepted:
            for name in ('bundle', 'store'):
                pin = self.accepted[name + '_sha256']
                if not Path(self.accepted[name]).is_absolute() or not isinstance(pin, str) \
                        or len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
                    raise ValueError('accepted inputs require absolute paths and lowercase SHA-256 pins')
                if file_digest(Path(self.accepted[name])) != self.accepted[name + '_sha256']:
                    raise ValueError('accepted input differs from its explicit pin')
            for suffix in ('-wal', '-shm'):
                if Path(str(self.accepted['store']) + suffix).exists():
                    raise ValueError('accepted store must be quiescent without writable sidecars')
        if self.c['runtime']['project'] != 'maude-cache-birthday':
            raise ValueError('this compiler profile supports only project maude-cache-birthday')
        source = Path(self.c['files']['maude_source']['path'])
        if source.resolve() / 'qualification/synthetic_cache' != HERE:
            raise ValueError('driver must come from the enrolled Maude checkout')
        def git(*args):
            result = subprocess.run(['/usr/bin/git', '-c', 'core.fsmonitor=false',
                '-c', 'core.untrackedCache=false', '-C', str(source), *args],
                env={'PATH': '/usr/bin:/bin', 'GIT_OPTIONAL_LOCKS': '0'},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=True)
            if len(result.stdout) > 256 * 1024:
                raise ValueError('checkout metadata exceeds this profile bound')
            return result.stdout
        revision = git('rev-parse', 'HEAD').decode().strip()
        if revision != self.c['files']['maude_source']['declared_revision']:
            raise ValueError('actual Maude revision differs from declared revision')
        if git('status', '--porcelain=v1', '--untracked-files=normal').strip():
            raise ValueError('use a clean, quiescent Maude checkout outside edited working copies')
        for raw in git('ls-files', '-z', 'src/maude', 'qualification/synthetic_cache').split(b'\0'):
            if raw:
                path = source / raw.decode()
                self.source_pins[str(path)] = source_digest(path)
        if self.records.exists() or self.records.is_symlink():
            raise ValueError('run already exists; inspect its checkpoint, do not restart')
        for key in ('nightshift_store', 'ag_database', 'maude_store'):
            path = Path(self.state[key])
            if path.exists() or path.is_symlink():
                raise ValueError('owner already has state: ' + key)
        if Path(self.state['docket_directory']).exists() and any(Path(self.state['docket_directory']).iterdir()):
            raise ValueError('Docket state is not empty')
        for directory in (self.root, Path('/data') if Path('/data').exists() else self.root):
            st = os.statvfs(directory)
            if st.f_bavail * st.f_frsize < 61 * 1024**3 or st.f_favail < 10000:
                raise ValueError('tutorial allocation would cross the documented host reserve')
        if not os.environ.get('INVOCATION_ID'):
            raise ValueError('run inside the documented durable systemd manager')

    def project_absent(self, phase):
        docker = self.program('docker')
        selector = 'label=com.docker.compose.project=' + self.c['runtime']['project']
        for kind, argv in (('containers', ['ps', '-aq']), ('networks', ['network', 'ls', '-q'])):
            if self.call(phase + '-' + kind, [docker, *argv, '--filter', selector]).strip():
                raise ValueError('exact tutorial project is not absent; inspect before continuing')

    def construct(self, stage, occurrence):
        ids = self.ids
        artifact = self.records / f'diagnostic-{stage}.json'
        self.helper('cache-host-bootstrap.py', 'construct', '--artifact', artifact,
            '--role-id', ids['role_id'], '--role-version', str(ids['role_version']),
            '--role-digest', ids['role_digest'], '--generation', ids['generation'],
            '--schedule-id', ids['qualification_schedule_id' if stage == 'q' else 'successor_schedule_id'],
            '--attempt-id', ids['qualification_attempt_id' if stage == 'q' else 'successor_attempt_id'],
            '--configuration-version', ids['configuration_version'], '--scheduler-clock-id', ids['scheduler_clock_id'],
            '--occurrence', str(occurrence), '--cycle-request-out', self.records / f'posture-{stage}.json')
        request = json.loads((self.records / f'posture-{stage}.json').read_bytes())
        if request['slot']['scope_id'] != ids['scope_digest']:
            raise ValueError('observed NQ scope differs from enrolled action scope')
        return request['observation_id']

    def compile(self, stage, initial_observation, successor_observation):
        runtime = self.c['runtime']; ids = self.ids
        output = self.root / ('plan-' + stage)
        if self.accepted:
            return self.compile_accepted(stage, output)
        self.call('compile-' + stage, [self.program('python'), self.file('maude_build_plan'),
            '--output-root', output, '--runtime-root', runtime['runtime_root'],
            '--runtime-workspace', runtime['workspace'], '--front-port', str(runtime['front_port']),
            '--image', runtime['image'], '--docker-program', self.program('docker'),
            '--docker-program-identity', 'sha256:' + self.c['programs']['docker']['sha256'],
            '--docker-client-version', runtime['docker_client_version'],
            '--docker-server-version', runtime['docker_server_version'], '--compose-version', runtime['compose_version'],
            '--campaign-id', ids['campaign_id'], '--program-id', ids['program_id'],
            '--subject-digest', ids['subject_digest'], '--scope-digest', ids['scope_digest'],
            '--qualify-occurrence-id', ids['qualification_occurrence_id'],
            '--teardown-occurrence-id', ids['successor_occurrence_id'],
            '--qualify-observation-id', initial_observation, '--teardown-observation-id', successor_observation])
        return output

    def compile_accepted(self, stage, output):
        action = 'qualify' if stage == 'q' else 'teardown'
        preparation = self.root / ('accepted-input-' + stage)
        source = Path(self.c['files']['maude_source']['path'])
        compiler_pin = source_digest(source / 'src/maude/plan/local_compose.py')
        observation = self.records / f'diagnostic-{stage}.json'
        helper = [self.program('python'), HERE / 'compile_accepted_cache_actions.py', action]
        self.call('prepare-accepted-' + stage, [*helper, '--prepare-input',
            '--context', self.context_path, '--context-sha256', file_digest(self.context_path),
            '--accepted-store', self.accepted['store'], '--accepted-store-sha256', self.accepted['store_sha256'],
            '--bundle', self.accepted['bundle'], '--bundle-sha256', self.accepted['bundle_sha256'],
            '--nq-observation', observation, '--nq-observation-sha256', source_digest(observation),
            '--maude-local-compose-sha256', compiler_pin, '--output', preparation])
        self.call('compile-accepted-' + stage, [*helper, '--maude-source', source,
            '--maude-local-compose-sha256', compiler_pin, '--accepted-store', preparation / 'accepted-plan.sqlite',
            '--accepted-store-sha256', file_digest(preparation / 'accepted-plan.sqlite'),
            '--bundle', preparation / 'accepted-bundle.json', '--bundle-sha256', self.accepted['bundle_sha256'],
            '--compiler-input', preparation / f'compiler-input-{action}.json',
            '--compiler-input-sha256', source_digest(preparation / f'compiler-input-{action}.json'),
            '--output', output])
        return output

    def proposal(self, stage, plan, action):
        output = self.records / f'proposal-{stage}.json'
        self.helper('cache-successor-compose-request.py', '--posture-request', self.records / f'posture-{stage}.json',
                    '--precompiled-proposal', plan / f'handoff-{action}.json', '--output', output)
        return output

    def seal(self, stage, plan, request):
        output = self.records / f'authoring-{stage}.json'
        self.call('seal-' + stage, [self.program('python'), HERE / 'seal_cycle_handoff.py',
            '--store', self.state['maude_store'], '--session-key', self.c['credentials']['maude_session'],
            '--producer-key', self.c['credentials']['maude_producer'], '--plan', plan / 'plan-locked.json',
            '--base-request', request, '--output', output, '--session-id', 'session_local_cache_' + stage,
            '--runtime-id', self.ids['runtime_id']])
        return output

    def pulse(self, stage):
        argv = [self.program('python'), HERE / 'prepare_pulse_support.py',
            '--artifact', self.records / f'diagnostic-{stage}.json', '--posture-request', self.records / f'posture-{stage}.json',
            '--output', self.root / ('pulse-' + stage), '--sealer', self.file('pulse_launcher_sealer'),
            '--sealer-sha256', 'sha256:' + self.c['files']['pulse_launcher_sealer']['sha256'],
            '--authority-id', 'pulse-authority:local-cache-' + stage, '--producer-id', 'pulse-producer:local-cache-' + stage]
        for name in ('pulse', 'python', 'openssl'):
            argv += ['--' + name, self.program(name), '--' + name + '-sha256', 'sha256:' + self.c['programs'][name]['sha256']]
        result = json.loads(self.call('prepare-pulse-' + stage, argv))
        self.helper('cache-host-bootstrap.py', 'support', '--pulse', self.program('pulse'),
            '--pulse-config', result['config'], '--acquisition-id',
            self.ids['qualification_pulse_acquisition_id' if stage == 'q' else 'successor_pulse_acquisition_id'])
        return result['resolver']

    def open_cycle(self, stage, request, authoring, resolver, external=None):
        enrollment = json.loads(Path(self.file('ag_enrollment')).read_bytes())
        provenance = json.loads((self.records / f'provenance-{stage}.json').read_bytes())
        args = ['cycle', 'run', '--request', request, '--present-evidence-resolver', resolver,
            '--nq-program', self.program('nq'), '--nq-config', self.file('nq_config'),
            '--nq-source-id', provenance['source']['source_id'], '--ag-loopctl', self.program('ag'),
            '--ag-database', self.state['ag_database'], '--ag-observation-resolver', self.file('observation_resolver'),
            '--ag-observation-resolver-id', enrollment['observation_resolver_id'], '--ag-runtime-profile', self.file('ag_profile'),
            '--maude-authoring-handoff', authoring, '--maude-custody-credential', self.c['credentials']['maude_producer'],
            '--maude-producer-principal-id', 'maude-handoff:synthetic-local', '--maude-producer-key-id', 'maude-handoff-key:synthetic-v1',
            '--maude-session-custody-credential', self.c['credentials']['maude_session'],
            '--maude-session-issuer-principal-id', 'maude:synthetic-supervisor',
            '--maude-session-issuer-key-id', 'maude-session-key:synthetic-v1', '--nightshift-runtime-id', self.ids['runtime_id']]
        if external:
            args += ['--external-evidence-profile', external]
        self.ns('open-' + stage, *args)

    def execute(self, stage, plan, action):
        enrollment = json.loads(Path(self.file('ag_enrollment')).read_bytes())
        mandate = {'schema': 'ag.governed-loop.standing-mandate-store/v1', 'mandates': [{
            'generation': 3 if stage == 'q' else 4, 'scope': self.ids['scope_digest'],
            'subject': self.ids['subject_digest'], 'status': 'active',
            'valid_until_unix_ms': time.time_ns() // 1000000 + 300000}]}
        # This is an explicitly synthetic capability, confined to disposable state.
        # It is not an operator-issued permission in the real shared-review profile.
        temporary = Path(self.state['mandate_store'] + '.' + stage)
        write_new(temporary, canonical(mandate))
        os.replace(temporary, self.state['mandate_store'])
        gate = ['--catalog', self.file('ag_catalog'), '--observation-resolver', self.file('observation_resolver'),
            '--expected-observation-resolver-id', enrollment['observation_resolver_id'],
            '--standing-resolver', self.file('standing_resolver'), '--expected-standing-resolver-id',
            enrollment['standing_resolver_id'], '--max-standing-ttl-ms', str(enrollment['max_standing_ttl_ms'])]
        self.ag('standing-' + stage, 'require-standing')
        for command in ('decide', 'authorize'):
            self.ag(command + '-' + stage, command, *gate)
        dispatch = ['--docket', self.program('docket'), '--docket-state', self.state['docket_directory'],
            '--docket-trust', self.file('docket_trust'), '--docket-standing-resolver', self.file('docket_standing_resolver'),
            '--executor', self.file('maude_executor'), '--executor-config', plan / f'executor-plan-{action}.json',
            '--issuer-principal', enrollment['docket']['issuer_principal'], '--issuer-key-id', enrollment['docket']['issuer_key_id'],
            '--issuer-key', self.c['credentials']['ag_issuer']]
        self.ag('dispatch-' + stage, 'dispatch', *dispatch)
        result = json.loads(self.ag('poll-' + stage, 'poll', *dispatch))
        state = result.get('state', {}).get('settled_observation_required', {})
        if state.get('settlement', {}).get('outcome') != 'success':
            raise ValueError('attempt is not demonstrably successful; inspect AG and Docket before recovery')
        issuance = state['dispatch']['authorized']['issuance']['issuance']
        inspection = self.records / f'docket-{stage}.json'
        raw = self.call('inspect-' + stage, [self.program('docket'), 'governed-loop', 'inspect',
            '--state', self.state['docket_directory'], '--issuance', issuance], output=inspection)
        return issuance, json.loads(raw), inspection

    def run(self):
        self.preflight()
        self.records.mkdir(mode=0o700)
        self.write('checkpoint.json', {'context': str(self.context_path), 'context_sha256': file_digest(self.context_path),
            'host': socket.gethostname(), 'cwd': str(HERE), 'invocation_id': os.environ['INVOCATION_ID'],
            'state': self.state, 'standing': 'synthetic_fixture', 'expected_terminal': 'terminal.json',
            'recovery': 'Inspect the original manager and numbered stage records, then original NQ/AG/Docket stores. Do not rerun this driver.'})
        self.write('source-pins.json', self.source_pins)
        if self.accepted:
            self.write('accepted-inputs.json', {**{k: str(v) for k, v in self.accepted.items()},
                'acceptance_scope': 'Caller-supplied reference; this driver does not authenticate a human or create acceptance.',
                'model_call': False})
        try:
            self.project_absent('initial')
            self.call('image', [self.program('docker'), 'image', 'inspect', self.c['runtime']['image']])
            self.nq('nq-init', 'init')
            for command in ('test', 'admit'):
                self.nq('nq-' + command, 'watcher', command, self.ids['watcher_instance_id'])
            self.helper('cache-host-bootstrap.py', 'acquire', '--nq', self.program('nq'), '--nq-config', self.file('nq_config'),
                '--instance', self.ids['watcher_instance_id'], '--artifact-out', self.records / 'diagnostic-q.json',
                '--provenance-out', self.records / 'provenance-q.json')
            observation = self.construct('q', 0)
            plan = self.compile('q', observation, 'sha256:' + 'e' * 64)
            proposal = self.proposal('q', plan, 'qualify')
            authoring = self.seal('q', plan, proposal)
            self.open_cycle('q', proposal, authoring, self.pulse('q'))
            issuance, inspection, inspection_path = self.execute('q', plan, 'qualify')
            settlements = self.successor(plan, observation, issuance, inspection, inspection_path)
            if self.qualification_pause_after_teardown:
                self.post_teardown_pause(settlements)
            self.project_absent('final')
            self.write('terminal.json', {'exit_code': 0, 'phase': 'verified_local_composition',
                'standing': 'synthetic_fixture', 'present_cache_state': 'project absent at final inspection',
                'release_qualification': 'requires independent inspection and public-only reproduction'})
        except Exception as error:
            self.write('terminal.json', {'exit_code': 1, 'phase': self.phase, 'reason': str(error),
                'next': 'preserve records; inspect original owners before any new action', 'automatic_retry': False})
            raise

    def successor(self, plan, observation, issuance, inspection, inspection_path):
        for kind in ('context', 'custody'):
            self.ns('export-' + kind, 'cycle', 'export-authoring-' + kind,
                '--campaign-id', self.ids['campaign_id'], '--occurrence-id', self.ids['qualification_occurrence_id'],
                output=self.records / ('lineage.json' if kind == 'context' else 'custody.json'))
        attempt = inspection['record']['custody']['attempt']
        evidence = Path(self.c['runtime']['workspace']) / 'evidence/attempts' / (attempt.removeprefix('sha256:') + '.json')
        external = self.root / 'external'
        self.helper('prepare-cache-external-successor.py', '--docket-inspection', inspection_path,
            '--executor-evidence', evidence, '--executor-plan', plan / 'executor-plan-qualify.json',
            '--compilation-receipt', plan / 'compilation-receipt-qualify.json', '--lineage-export', self.records / 'lineage.json',
            '--custody-export', self.records / 'custody.json', '--output', external, '--target-runtime-id', self.ids['runtime_id'],
            '--producer-principal-id', 'maude-observer:synthetic-local', '--producer-key-id', 'maude-observer-key:synthetic-v1',
            '--maude-producer-principal-id', 'maude-handoff:synthetic-local',
            '--maude-producer-key-id', 'maude-handoff-key:synthetic-v1',
            '--maude-session-issuer-principal-id', 'maude:synthetic-supervisor',
            '--maude-session-issuer-key-id', 'maude-session-key:synthetic-v1')
        if json.loads((external / 'recipe.json').read_bytes()).get('launch_admissible') is not True:
            raise ValueError('external observation preparation refused')
        observer_key = self.root / 'credentials/observer.key'
        write_new(observer_key, secrets.token_bytes(32))
        profile = external / 'external-evidence-profile.json'
        acquisition = self.records / 'acquisition.json'
        raw = self.call('acquire-result', [self.program('python'), '-m', 'maude.plan.observation_acquisition',
            'orchestrate-post-settlement', '--ledger', self.root / 'acquisition.sqlite', '--docket-program', self.program('docket'),
            '--docket-state', self.state['docket_directory'], '--issuance', issuance, '--executor-evidence', evidence,
            '--executor-plan', plan / 'executor-plan-qualify.json', '--compilation-receipt', plan / 'compilation-receipt-qualify.json',
            '--governed-bindings', external / 'qualify-governed-cross-probe.json', '--external-profile', profile,
            '--target-runtime-id', self.ids['runtime_id'], '--producer-key', observer_key,
            '--producer-principal-id', 'maude-observer:synthetic-local', '--producer-key-id', 'maude-observer-key:synthetic-v1',
            '--nightshift-program', self.program('nightshift'), '--nightshift-store', self.state['nightshift_store'],
            '--nightshift-credential', observer_key, '--nightshift-runtime-id', self.ids['runtime_id']], output=acquisition)
        if json.loads(raw)['events'][-1]['kind'] != 'custody_accepted':
            raise ValueError('result custody was not accepted')
        self.qualify_result(plan, inspection_path)
        raw = self.nq('successor-acquisition', 'diagnostics', 'acquire-next-local', self.ids['watcher_instance_id'],
            '--acquisition-id', self.ids['local_successor_acquisition_id'], output=self.records / 'diagnostic-t.json')
        artifact = json.loads(raw)['artifact_id']
        if self.nq('successor-export', 'diagnostics', 'export', artifact) != raw:
            raise ValueError('successor export differs; do not reacquire')
        self.nq('successor-admission', '--json', 'diagnostics', 'qualify', artifact, output=self.records / 'provenance-t.json')
        following = self.construct('t', 1)
        self.helper('verify-cache-observation-family.py', '--predecessor', self.records / 'posture-q.json',
            '--successor', self.records / 'posture-t.json')
        successor = self.compile('t', observation, following)
        retained = ('plan-locked.json',) if self.accepted else ('executor-plan-qualify.json', 'compilation-receipt-qualify.json')
        for name in retained:
            if (plan / name).read_bytes() != (successor / name).read_bytes():
                raise ValueError('successor compilation changed initial work')
        proposal = self.proposal('t', successor, 'teardown')
        self.seal('t-cleanup', successor, proposal)
        resolver = self.pulse('t')
        base = self.records / 'external-request.json'
        self.helper('cache-successor-attach-external.py', '--request', proposal, '--acquisition', acquisition,
            '--profile', profile, '--output', base)
        prepared = self.records / 'prepared-request.json'
        self.ns('prepare-external', 'external-observation', 'prepare-cycle', '--request', base, '--profile', profile, output=prepared)
        authoring = self.seal('t', successor, prepared)
        self.open_cycle('t', prepared, authoring, resolver, profile)
        teardown_issuance, teardown_inspection, _ = self.execute('t', successor, 'teardown')
        if self.qualification_pause_after_teardown:
            return {
                'qualification': self.settlement_reference(issuance, inspection),
                'teardown': self.settlement_reference(teardown_issuance, teardown_inspection),
            }
        return None

    @staticmethod
    def settlement_reference(issuance, inspection):
        record = inspection.get('record', {})
        custody = record.get('custody', {})
        settlement = record.get('settlement', {})
        if (record.get('status') != 'settled' or record.get('indeterminate') is not None
                or record.get('issuance', {}).get('issuance') != issuance
                or settlement.get('issuance') != issuance or settlement.get('outcome') != 'success'
                or not isinstance(custody.get('attempt'), str)
                or not isinstance(settlement.get('settlement'), str)):
            raise ValueError('post-teardown pause requires exact successful settlements')
        return {'issuance': issuance, 'attempt': custody['attempt'],
                'settlement': settlement['settlement'], 'outcome': 'success'}

    def post_teardown_pause(self, settlements):
        if self.sequence != 53 or set(settlements) != {'qualification', 'teardown'}:
            raise ValueError('post-teardown pause reached outside the fixed qualification seam')
        barrier = self.records / 'post-teardown-supervisor-pause.json'
        self.write(barrier.name, {
            'schema': 'maude.connected-cache-post-teardown-supervisor-pause/v1',
            'qualification_only': True,
            'invocation_id': os.environ['INVOCATION_ID'],
            'context': str(self.context_path),
            'context_sha256': file_digest(self.context_path),
            'last_finished_stage': '053-inspect-t',
            'settlements': settlements,
            'expected_absent_records': [
                '054-final-containers.started.json',
                '055-final-networks.started.json',
                'terminal.json',
            ],
            'next': 'stop the durable manager; inspect original owners and exact project; never resume this root',
        })
        descriptor = os.open(self.records, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            time.sleep(0.1)
        raise ValueError('qualification pause expired; preserve and inspect this root')

    def qualify_result(self, plan, inspection):
        result = self.root / 'result'
        result.mkdir(mode=0o700)
        for name in ('admissions', 'helpers', 'work'):
            (result / name).mkdir(mode=0o700)
        # Reuse the explicit account/debug choice from the admitted host config.
        import tomllib
        host = tomllib.loads(Path(self.file('nq_config')).read_text())['watchers'][0]['command']
        config = result / 'nq.toml'
        args = ['--docket-inspection', inspection, '--executor-plan', plan / 'executor-plan-qualify.json',
            '--docket-database', Path(self.state['docket_directory']) / 'state.sqlite', '--nq-database', result / 'nq.sqlite',
            '--nq-socket', result / 'nq.sock', '--admissions-dir', result / 'admissions', '--helper-runtime-dir', result / 'helpers',
            '--helper', self.program('nq_result_helper'), '--helper-working-directory', result / 'work',
            '--execution-account', host['execution_account'], '--output', config]
        if host.get('allow_same_identity_in_debug'):
            args += ['--allow-same-identity-in-debug']
        self.helper('cache-successor-result-config.py', *args)
        self.nq('result-init', 'init', config=config)
        for command in ('test', 'admit'):
            self.nq('result-' + command, 'watcher', command, 'synthetic-cache-result', config=config)
        raw = self.nq('result-diagnostic', 'diagnostics', 'execute', 'synthetic-cache-result', config=config)
        artifact = json.loads(raw)
        if self.nq('result-export', 'diagnostics', 'export', artifact['artifact_id'], config=config) != raw:
            raise ValueError('result replay differs')
        provenance = json.loads(self.nq('result-admission', '--json', 'diagnostics', 'qualify', artifact['artifact_id'], config=config))
        outcome = artifact['outcome']
        if (outcome['condition'] != 'explicitly_absent' or outcome['coverage'] != 'complete'
                or outcome['coherence'] != 'jointly_established' or outcome['derivation'] != 'completed'
                or outcome['refusals'] or outcome['unsupported'] or provenance['disposition'] != 'admitted_report'
                or provenance['artifact']['artifact_id'] != artifact['artifact_id']
                or provenance['provider']['profile_semantic_id'] != 'sha256:8954802bd11ae5a1a36d78a155e1a2cc9c07acd52ead658e3f82124b91e5d7ec'):
            raise ValueError('exact past attempt result was not admitted; no successor action')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--accepted-bundle', type=Path)
    parser.add_argument('--accepted-bundle-sha256')
    parser.add_argument('--accepted-store', type=Path)
    parser.add_argument('--accepted-store-sha256')
    parser.add_argument('--qualification-pause-after-teardown', action='store_true',
        help='synthetic accepted-mode recovery qualification only; wait after settled teardown before final inspection')
    args = parser.parse_args()
    values = (args.accepted_bundle, args.accepted_bundle_sha256, args.accepted_store, args.accepted_store_sha256)
    if any(values) and not all(values):
        parser.error('accepted mode requires exact bundle/store paths and both SHA-256 pins')
    accepted = {'bundle': args.accepted_bundle, 'bundle_sha256': args.accepted_bundle_sha256,
                'store': args.accepted_store, 'store_sha256': args.accepted_store_sha256} if all(values) else None
    Run(args.context, accepted, args.qualification_pause_after_teardown).run()


if __name__ == '__main__':
    main()
