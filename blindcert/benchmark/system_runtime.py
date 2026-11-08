from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from blindcert.benchmark.system_models import generate_model
from blindcert.benchmark.system_relation import ROOT, digest, leaf, poseidon, tree, arithmetic
from blindcert.bridge.mpspdz_rep3 import SCALAR_FIELD as Q


TOOLS = ROOT / 'external'
MPC = TOOLS / 'mp-spdz-0.4.3'
CO = TOOLS / 'co-circom'
SNARK = TOOLS / 'node_modules/.bin/snarkjs'
NODE = TOOLS / 'node-v24.18.0-linux-x64/bin/node'
ENV = {**os.environ, 'PATH': str(NODE.parent)+':'+os.environ['PATH'],
       'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'RAYON_NUM_THREADS': '1'}


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':'))+'\n')


def load(path: Path):
    return json.loads(path.read_text())


def checksum(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ExecutionFailure(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def rss_tree(pids: set[int]) -> int:
    rows = []
    for item in Path('/proc').iterdir():
        if item.name.isdigit():
            try:
                content = (item/'stat').read_text().rsplit(')', 1)[1].split()
                rows.append((int(item.name), int(content[1]), int(content[21])*os.sysconf('SC_PAGE_SIZE')))
            except (OSError, IndexError, ValueError):
                pass
    for _ in range(10):
        children = {pid for pid, parent, _ in rows if parent in pids}
        if children <= pids:
            break
        pids |= children
    return sum(rss for pid, _, rss in rows if pid in pids)


def commands(items: list[tuple[list[str], Path]], logdir: Path, label: str,
             timeout: float, memory_gib: float) -> dict:
    logdir.mkdir(parents=True, exist_ok=True)
    procs, files = [], []
    started = time.perf_counter()
    peak = 0
    result = {'commands': [[('<redacted entropy>' if token.startswith('-e=') else token) for token in cmd] for cmd, _ in items]}
    try:
        for i, (cmd, cwd) in enumerate(items):
            log = (logdir/f'{label}-{i}.log').open('w')
            files.append(log)
            procs.append(subprocess.Popen(cmd, cwd=cwd, env=ENV, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        while True:
            if any(p.poll() not in (None, 0) for p in procs):
                raise ExecutionFailure('FAILED', f'{label} process failed; see {logdir}')
            if time.perf_counter()-started > timeout:
                raise ExecutionFailure('TIMEOUT', f'{label} exceeded {timeout}s')
            if label == 'mascot':
                for marker,key in [('INPUT_SHARED','input_shared_observed_s'),('EVALUATION_COMPLETE','evaluation_observed_s')]:
                    if key not in result and all(marker in (logdir/f'{label}-{i}.log').read_text() for i in range(len(procs))):
                        result[key] = time.perf_counter()-started
            if all(p.poll() is not None for p in procs):
                break
            peak = max(peak, rss_tree({p.pid for p in procs}))
            if peak > memory_gib*1024**3:
                raise ExecutionFailure('OOM', f'{label} exceeded {memory_gib} GiB aggregate RSS')
            time.sleep(.1)
        codes = [p.returncode for p in procs]
        result.update(exit_codes=codes, peak_rss_bytes=peak, wall_s=time.perf_counter()-started)
        if any(codes):
            raise ExecutionFailure('FAILED', f'{label} exit codes {codes}; see {logdir}')
        return result
    except BaseException as exc:
        result['error'] = str(exc)
        raise
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        for file in files:
            file.close()
        result.update(exit_codes=[p.returncode for p in procs], wall_s=time.perf_counter()-started, peak_rss_bytes=peak)
        save(logdir/f'{label}.json', result)


def selected(seed: str, config: dict) -> list[int]:
    partition = config['population_size']//4
    count = config['sample_size']//2
    result = []
    counter = 0
    for g in range(2):
        population = list(range(partition*2))
        for i in range(count):
            span = len(population)-i
            limit = 2**256-(2**256 % span)
            while True:
                raw = int.from_bytes(hashlib.sha256(bytes.fromhex(seed)+counter.to_bytes(8,'big')).digest(),'big')
                counter += 1
                if raw < limit:
                    break
            j = i + raw % span
            population[i],population[j] = population[j],population[i]
        result += [g*partition*2+value for value in sorted(population[:count])]
    return result


def public_vector(registration: dict, challenge: dict) -> list[str]:
    tag = int(checksum({'registration': registration, 'challenge': challenge}), 16) % Q
    commitment = int(registration['commitment'])
    return [str(v) for v in [1, poseidon([tag, commitment]), tag, commitment,
                              *registration['roots'], *challenge['indices']]]


def party(action: str, path: Path, ident: int) -> None:
    config = load(path/'config.json')
    spec = load(path/'spec.json')
    directory = path/f'party{ident}'
    private = directory/'private.json'
    if action == 'register':
        value = load(private)
        if ident == 0:
            nonce = secrets.randbelow(Q)
            save(directory/'state.json', {'parameters': value['parameters'], 'modelNonce': nonce})
            save(directory/'registration.json', {'commitment': digest(1, [*value['parameters'], nonce])})
        else:
            levels = []
            for g in range(2):
                records = sorted((r for r in value if r['stratum'] == g), key=lambda r:r['local_index'])
                if [r['local_index'] for r in records] != list(range(config['population_size']//4)):
                    raise ValueError('registration must authenticate every record in the full partition')
                levels.append(tree([leaf(ident-1, r) for r in records]))
            save(directory/'state.json', {'records': value, 'levels': levels})
            save(directory/'registration.json', {'roots': [level[-1][0] for level in levels]})
    elif action == 'commit':
        opening = secrets.token_hex(32)
        save(directory/'opening.json', opening)
        save(directory/'commit.json', checksum({'sid': path.name, 'party': ident, 'opening': opening}))
    elif action == 'reveal':
        save(directory/'reveal.json', load(directory/'opening.json'))
    elif action == 'input':
        state = load(directory/'state.json')
        if ident == 0:
            values = [*state['parameters'], state['modelNonce']]
        else:
            partition = config['population_size']//4
            lookup = {(r['stratum'],r['local_index']):r for r in state['records']}
            values = []
            for index in load(path/'challenge.json')['indices']:
                g, remainder = divmod(index, 2*partition)
                holder, local = divmod(remainder, partition)
                if holder != ident-1:
                    continue
                record = lookup[g,local]
                siblings = [level[(local >> depth)^1] for depth, level in enumerate(state['levels'][g][:-1])]
                values += [*record['x'], record['y'], record['attribute'], int(record['nonce']), *siblings]
        (directory/'Player-Data').mkdir(exist_ok=True)
        (directory/f'Player-Data/Input-P{ident}-0').write_text(' '.join(map(str,values))+'\n')
    elif action == 'convert':
        from blindcert.bridge.mpspdz_rep3 import read_authenticated_share_values, encode_rep3_input
        metadata = load(path/'metadata.json')
        count = sum(metadata['layout'].values())
        own = read_authenticated_share_values(directory/f'Persistence/Transactions-P{ident}.data', count)
        previous_id = (ident-1)%3
        previous = read_authenticated_share_values(path/f'party{previous_id}/Persistence/Transactions-P{previous_id}.data', count)
        (directory/'input.shared').write_bytes(encode_rep3_input(own,previous,metadata['layout'],load(path/'public_inputs.json')))
    else:
        raise ValueError(action)


def mpc_program(spec: dict, config: dict, metadata: dict) -> str:
    n, d, depth = config['sample_size'], spec['layers'][0], metadata['depth']
    p = metadata['parameter_count']
    lines = ['from Compiler.library import public_input, check_point', f'theta = Array({p}, sint)',
             f'for j in range({p}): theta[j] = sint.get_input_from(0)', 'modelNonce = sint.get_input_from(0)']
    for name,size in [('x',n*d),('y',n),('attribute',n),('nonce',n),('paths',n*depth),('prediction',n)]:
        lines.append(f'{name} = Array({size}, sint)')
    for row in range(n):
        lines += ['owner = regint(public_input())',
                  *[f'x[{row*d+j}] = sint.get_input_from(owner)' for j in range(d)],
                  f'y[{row}] = sint.get_input_from(owner)', f'attribute[{row}] = sint.get_input_from(owner)',
                  f'nonce[{row}] = sint.get_input_from(owner)',
                  *[f'paths[{row*depth+j}] = sint.get_input_from(owner)' for j in range(depth)]]
    lines += ['check_point()', "print_ln('INPUT_SHARED')"]
    ops, scores = arithmetic(spec,n,'mpc')
    lines += ops
    lines += [f'prediction[{row}] = {score} >= 0' for row,score in enumerate(scores)]
    checks = []
    for g in range(2):
        begin,end = g*(n//2),(g+1)*(n//2)
        lines += [f'correct{g} = '+ '+'.join(f'(prediction[{i}] == y[{i}])' for i in range(begin,end)),
                  f'bad{g} = '+ '+'.join(f'(prediction[{i}]*attribute[{i}])' for i in range(begin,end))]
        checks += [f'(correct{g} >= {metadata["policy"]["required_correct_per_stratum"]})',
                   f'(bad{g} <= {metadata["policy"]["allowed_violations_per_stratum"]})']
    lines += ['passed = '+' * '.join(checks), "print_ln('POLICY=%s', passed.reveal())", "print_ln('EVALUATION_COMPLETE')", 'exported = []']
    for name,size in metadata['layout'].items():
        lines.append(f'exported.extend([{name}[i] for i in range({size})])' if name != 'modelNonce' else 'exported.append(modelNonce)')
    lines += ['for value in exported:', '    masked = value+sint.get_random()',
              "    print_ln('MASKED=%s', masked.reveal())", 'check_point()',
              'sint.write_to_file(exported, position=0)', 'check_point()', "print_ln('MAC_CHECK_COMPLETE')"]
    return '\n'.join(lines)+'\n'


def setup(spec: dict, config: dict, directory: Path, call) -> dict:
    from blindcert.benchmark.system_relation import generate_circuit
    started = time.perf_counter()
    directory.mkdir(parents=True,exist_ok=True)
    save(directory/'spec.json',spec)
    save(directory/'config.json',config)
    call([[sys.executable,'-m','blindcert.benchmark.system_runtime','generate',str(directory)]], [ROOT], 'generate-source')
    metadata = load(directory/'metadata.json')
    program_name = metadata['program_name']
    call([[sys.executable,str(MPC/'compile.py'),'-F','64',program_name]], [MPC], 'compile-mascot')
    call([[str(TOOLS/'circom'),'cert.circom','--r1cs','--wasm','--sym','--O2','-o',str(directory)]], [directory], 'compile-circuit')
    import struct
    with (directory/'cert.r1cs').open('rb') as stream:
        if stream.read(4) != b'r1cs':
            raise ValueError('not an R1CS artifact')
        version,sections = struct.unpack('<II',stream.read(8))
        for _ in range(sections):
            section,size = struct.unpack('<IQ',stream.read(12))
            if section == 1:
                field_size = struct.unpack('<I',stream.read(4))[0]
                prime = int.from_bytes(stream.read(field_size),'little')
                wires,outputs,public,private = struct.unpack('<IIII',stream.read(16))
                labels,constraints = struct.unpack('<QI',stream.read(12))
                if prime != Q:
                    raise ValueError('R1CS scalar field mismatch')
                break
            stream.seek(size,1)
        else:
            raise ValueError('missing R1CS header')
    save(directory/'r1cs_metrics.json', {'constraints':constraints,'private_inputs':private,'wires':wires,'public_inputs':public,'public_outputs':outputs,'parameter_count':metadata['parameter_count']})
    power = max(4,(constraints+public+outputs+1).bit_length())
    if power > config.get('srs_max_power', 28):
        raise ExecutionFailure('NOT_IMPLEMENTED',f'required SRS power {power} exceeds configured SRS resource budget')
    srs_source = 'fresh local BN254 ceremony with random contributions; single trusted machine'
    srs_reused = False
    if config.get('srs_source') == 'snarkjs-published':
        import re
        readme = (TOOLS/'node_modules/snarkjs/README.md').read_text()
        match = re.search(r'\[powersOfTau28_hez_final_'+str(power)+r'\.ptau\]\((https://[^)]+)\)\s*\|\s*([0-9a-f]{128})',readme)
        if not match:
            raise ExecutionFailure('NOT_IMPLEMENTED',f'no pinned SRS source for power {power}')
        original_url,expected_hash = match.groups()
        url = 'https://circom.info/powersOfTau28_hez_final_'+str(power)+'.ptau'
        cache = TOOLS/'system_srs'
        cache.mkdir(exist_ok=True)
        target = cache/f'power{power}.ptau'
        srs_reused = target.exists()
        download = target if srs_reused else target.with_suffix('.part')
        if not srs_reused:
            call([['curl','--fail','--location','--retry','2','--max-time',str(config['timeout_s']),url,'--output',str(download)]],[ROOT],'srs-acquire')
        before = time.perf_counter()
        actual = hashlib.blake2b()
        with download.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                actual.update(block)
        if actual.hexdigest() != expected_hash:
            raise ExecutionFailure('FAILED','SRS checksum differs from pinned snarkjs release README')
        if not srs_reused:
            download.rename(target)
        save(directory/'srs.json',{'url':url,'original_release_url':original_url,'blake2b':expected_hash,'checksum_s':time.perf_counter()-before,'reused_cache':srs_reused})
        (directory/'final.ptau').symlink_to(target)
        srs_source = url+'; checksum authenticated by pinned snarkjs release README; no local SRS generation'
    else:
        call([[str(SNARK),'powersoftau','new','bn128',str(power),'pot0.ptau']], [directory], 'srs-new')
        call([[str(SNARK),'powersoftau','contribute','pot0.ptau','pot1.ptau','-e='+secrets.token_hex(64)]], [directory], 'srs-contribute')
        call([[str(SNARK),'powersoftau','prepare','phase2','pot1.ptau','final.ptau']], [directory], 'srs-phase2')
    call([[str(SNARK),'groth16','setup','cert.r1cs','final.ptau','initial.zkey']], [directory], 'groth16-setup')
    call([[str(SNARK),'zkey','contribute','initial.zkey','cert.zkey','-e='+secrets.token_hex(64)]], [directory], 'zkey-contribute')
    call([[str(SNARK),'zkey','export','verificationkey','cert.zkey','vk.json']], [directory], 'vk-export')
    for i in range(3):
        keydir = directory/f'network{i}'
        keydir.mkdir()
        call([['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1',
               '-nodes','-keyout','key.pem','-out','cert.pem','-days','30','-subj','/CN=localhost',
               '-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-addext','basicConstraints=critical,CA:FALSE']], [keydir], f'tls-new{i}')
        call([['openssl','pkcs8','-topk8','-nocrypt','-in','key.pem','-outform','DER','-out','key.der']], [keydir], f'tls-key{i}')
        call([['openssl','x509','-in','cert.pem','-outform','DER','-out','cert.der']], [keydir], f'tls-cert{i}')
    artifacts = {}
    for filename in ('cert.r1cs','cert.zkey','vk.json','cert.circom'):
        file = directory/filename
        hashed = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                hashed.update(block)
        artifacts[filename] = {'bytes':file.stat().st_size,'sha256':hashed.hexdigest()}
    return {**metadata,'artifacts':artifacts,'program_name':program_name,'constraints':constraints,'private_inputs':private,
            'wires':wires,'public_inputs':public,'public_outputs':outputs,'srs_power':power,
            'srs_source':srs_source,
            'srs_reused':srs_reused,'setup_s':time.perf_counter()-started}


def worker_commands(action: str, session: Path) -> list[list[str]]:
    return [[sys.executable,'-m','blindcert.benchmark.system_runtime',action,str(session),str(i)] for i in range(3)]


def session(spec: dict, config: dict, metadata: dict, artifact: Path, path: Path, workload: Path, call) -> dict:
    import shutil
    start = time.perf_counter()
    stages = {}
    def stage(name, function):
        before = time.perf_counter()
        result = function()
        stages[name] = time.perf_counter()-before
        return result
    def initialize():
        path.mkdir(parents=True,mode=0o700)
        save(path/'config.json',config)
        save(path/'spec.json',spec)
        save(path/'metadata.json',metadata)
        for i in range(3):
            directory = path/f'party{i}'
            directory.mkdir(mode=0o700)
            shutil.copy2(workload/('owner.json' if i == 0 else f'holder{i-1}.json'),directory/'private.json')
            (directory/'Programs').symlink_to(MPC/'Programs',target_is_directory=True)
            text = f'[network]\nmy_id={i}\nbind_addr="127.0.0.1:{16000+i}"\nkey_path="{artifact/f"network{i}/key.der"}"\n'
            for j in range(3):
                text += f'\n[[network.parties]]\nid={j}\ndns_name="localhost:{16000+j}"\ncert_path="{artifact/f"network{j}/cert.der"}"\n'
            (directory/'network.toml').write_text(text)
    stage('startup_input_s',initialize)
    def register():
        call(worker_commands('register',path),[ROOT]*3,'registration')
        owner = load(path/'party0/registration.json')
        holders = [load(path/f'party{i}/registration.json')['roots'] for i in (1,2)]
        registration = {'sid':path.name,'model':spec,'config':config,'policy':metadata['policy'],
                        'commitment':owner['commitment'],'roots':[holders[h][g] for g in range(2) for h in range(2)]}
        save(path/'registration.json',registration)
        return registration
    registration = stage('registration_s',register)
    def challenge():
        call(worker_commands('commit',path),[ROOT]*3,'commit')
        commits = [load(path/f'party{i}/commit.json') for i in range(3)]
        call(worker_commands('reveal',path),[ROOT]*3,'reveal')
        openings = [load(path/f'party{i}/reveal.json') for i in range(3)]
        seed = checksum({'sid':path.name,'openings':openings})
        challenge = {'commits':commits,'openings':openings,'seed':seed,'indices':selected(seed,config)}
        save(path/'challenge.json',challenge)
        expected = public_vector(registration,challenge)
        public = {'tag':[int(expected[2])],'commitment':[int(registration['commitment'])],
                  'roots':registration['roots'],'indices':challenge['indices']}
        save(path/'public_inputs.json',public)
        save(path/'expected.json',{'registration':registration,'challenge':challenge,'public_input':expected})
        partition = config['population_size']//4
        owners = [((index % (partition*2))//partition)+1 for index in challenge['indices']]
        publicfile = MPC/'Programs/Public-Input'/metadata['program_name']
        publicfile.parent.mkdir(exist_ok=True)
        publicfile.write_text(' '.join(map(str,owners))+'\n')
        return challenge
    transcript = stage('challenge_s',challenge)
    stage('input_sharing_s',lambda:call(worker_commands('input',path),[ROOT]*3,'input-sharing'))
    def evaluate():
        commands_ = [['stdbuf','-oL',str(MPC/'mascot-party.x'),'-OF','.', '-N','3','-P',str(Q),'-pn','16100','-h','127.0.0.1','-p',str(i),metadata['program_name']] for i in range(3)]
        receipt = call(commands_,[path/f'party{i}' for i in range(3)],'mascot')
        if 'input_shared_observed_s' not in receipt or 'evaluation_observed_s' not in receipt:
            raise ExecutionFailure('FAILED','input sharing phase marker was not observed before MPC termination')
        return_receipt = receipt
        log = (path/'logs/mascot-0.log').read_text()
        if 'MAC_CHECK_COMPLETE' not in log or 'POLICY=1' not in log:
            raise ExecutionFailure('FAILED','MASCOT policy or MAC check did not complete')
        return return_receipt
    receipt = stage('mpc_s',evaluate)
    shared_s = receipt['input_shared_observed_s']
    stages['input_sharing_s'] += shared_s
    conversion_tail = stages['mpc_s']-receipt['evaluation_observed_s']
    stages['mpc_s'] = receipt['evaluation_observed_s']-shared_s
    stage('conversion_s',lambda:call(worker_commands('convert',path),[ROOT]*3,'conversion'))
    stages['conversion_s'] += conversion_tail
    stage('co_witness_s',lambda:call([
        [str(CO),'generate-witness','-O2','--input',str(path/f'party{i}/input.shared'),'--circuit',str(artifact/'cert.circom'),
         '--protocol','REP3','--curve','BN254','--config',str(path/f'party{i}/network.toml'),'--out',str(path/f'party{i}/witness.shared')]
        for i in range(3)],[path/f'party{i}' for i in range(3)],'co-witness'))
    def prove():
        items = []
        for i in range(3):
            cmd = [str(CO),'generate-proof','groth16','--witness',str(path/f'party{i}/witness.shared'),
                   '--zkey',str(artifact/'cert.zkey'),'--protocol','REP3','--curve','BN254','--config',str(path/f'party{i}/network.toml')]
            if i == 0:
                cmd += ['--out',str(path/'proof.json'),'--public-input',str(path/'public.json')]
            items.append(cmd)
        call(items,[path/f'party{i}' for i in range(3)],'co-prove')
    stage('co_prove_s',prove)
    def package():
        package = {'registration':registration,'challenge':transcript,'proof':load(path/'proof.json'),
                   'public_input':load(path/'public.json'),'expiry':int(time.time())+86400}
        save(path/'passport.json',package)
        return package
    package = stage('packaging_s',package)
    stage('verify_s',lambda:call([[sys.executable,'-m','blindcert.benchmark.system_runtime','verify',str(path),str(artifact)]],[ROOT],'verify'))
    stage('finalize_s',lambda:save(path/'accepted.json',{'verified':True,'sid':path.name}))
    stages['e2e_s'] = time.perf_counter()-start
    stages['uncovered_s'] = stages['e2e_s']-sum(value for key,value in stages.items() if key != 'e2e_s')
    proof_bytes = len(json.dumps(package['proof'],separators=(',',':'),sort_keys=True).encode())
    return {'sid':path.name,'verified':True,'stages':stages,'proof_bytes':proof_bytes,
            'passport_bytes':(path/'passport.json').stat().st_size,
            'statement_digest':checksum(load(path/'expected.json')),'session_directory':str(path)}


def verify(path: Path, artifact: Path) -> None:
    package = load(path/'passport.json')
    expected = load(path/'expected.json')
    if package['expiry'] < time.time() or package['registration'] != expected['registration']:
        raise ValueError('expired passport or unexpected registration')
    challenge = package['challenge']
    sid = expected['registration']['sid']
    if len(challenge['commits']) != 3 or len(challenge['openings']) != 3:
        raise ValueError('three contributions are required')
    for i in range(3):
        if checksum({'sid':sid,'party':i,'opening':challenge['openings'][i]}) != challenge['commits'][i]:
            raise ValueError('commit/reveal mismatch')
    seed = checksum({'sid':sid,'openings':challenge['openings']})
    if challenge['seed'] != seed or challenge['indices'] != selected(seed,expected['registration']['config']):
        raise ValueError('incorrect challenge or sampled indices')
    vector = public_vector(expected['registration'],challenge)
    if challenge != expected['challenge'] or package['public_input'] != vector or vector != expected['public_input']:
        raise ValueError('unexpected public input vector')
    commands([([str(CO),'verify','groth16','--proof',str(path/'proof.json'),'--vk',str(artifact/'vk.json'),
               '--public-input',str(path/'public.json'),'--curve','BN254'],ROOT)],path/'logs','verify-kernel',120,4)
    if load(path/'proof.json') != package['proof'] or load(path/'public.json') != vector:
        raise ValueError('proof files differ from passport')


def single(path: Path, artifact: Path, output: Path, spec: dict, config: dict, call) -> dict:
    output.mkdir(parents=True,mode=0o700)
    state = load(path/'party0/state.json')
    holders = [load(path/f'party{i}/state.json') for i in (1,2)]
    public = load(path/'public_inputs.json')
    inputs = {**public,'tag':public['tag'][0],'commitment':public['commitment'][0],
              'theta':state['parameters'],'modelNonce':state['modelNonce'],
              'x':[],'y':[],'attribute':[],'nonce':[],'paths':[],'prediction':[]}
    partition = config['population_size']//4
    model = generate_model(spec,config['workload_seed'])
    for index in load(path/'challenge.json')['indices']:
        g,remainder = divmod(index,2*partition)
        holder,local = divmod(remainder,partition)
        state = holders[holder]
        record = next(r for r in state['records'] if r['stratum']==g and r['local_index']==local)
        inputs['x'] += record['x']
        for name in ('y','attribute','nonce'):
            inputs[name].append(int(record[name]))
        inputs['paths'] += [level[(local>>depth)^1] for depth,level in enumerate(state['levels'][g][:-1])]
        inputs['prediction'].append(model.predict(record['x']))
    def strings(value):
        return [strings(v) for v in value] if isinstance(value,list) else str(value % Q)
    save(output/'input.json',{key:strings(value) for key,value in inputs.items()})
    call([[str(NODE),str(artifact/'cert_js/generate_witness.js'),str(artifact/'cert_js/cert.wasm'),str(output/'input.json'),str(output/'witness.wtns')]],[ROOT],'single-witness')
    result = call([[str(SNARK),'groth16','prove',str(artifact/'cert.zkey'),str(output/'witness.wtns'),str(output/'proof.json'),str(output/'public.json')]],[ROOT],'single-prove')
    if load(output/'public.json') != load(path/'expected.json')['public_input']:
        raise ValueError('single-prover integer reference and collaborative public inputs differ')
    return {'single_prove_s':result['wall_s'],'statement_digest':checksum(load(path/'expected.json'))}


if __name__ == '__main__':
    if sys.argv[1] == 'generate':
        from blindcert.benchmark.system_relation import generate_circuit
        directory = Path(sys.argv[2])
        spec,config = load(directory/'spec.json'),load(directory/'config.json')
        metadata = generate_circuit(spec,config,directory)
        name = 'bc_system_'+checksum({'spec':spec,'config':config})[:16]
        (MPC/'Programs/Source'/f'{name}.mpc').write_text(mpc_program(spec,config,metadata))
        save(directory/'metadata.json',{**metadata,'program_name':name})
    elif sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]),Path(sys.argv[3]))
    else:
        party(sys.argv[1],Path(sys.argv[2]),int(sys.argv[3]))
