from __future__ import annotations

import argparse
import csv
import json
import secrets
import subprocess
import platform
import hashlib
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from blindcert.benchmark.system_relation import ROOT
from blindcert.benchmark.system_runtime import ExecutionFailure, commands, save, load, setup, session, single


def aggregate(values):
    return {'n':len(values),'mean':statistics.mean(values),'stdev':statistics.stdev(values) if len(values)>1 else None,
            'median':statistics.median(values),'min':min(values),'max':max(values)}


def main() -> int:
    parser = argparse.ArgumentParser(description='Run continuous three-party certification measurements.')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/system_efficiency.yaml')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--iterations',type=int)
    parser.add_argument('--functional-check',action='store_true')
    parser.add_argument('--reuse-setup',type=Path)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    if args.iterations is not None:
        config['iterations'] = args.iterations
    if config['iterations'] != 1:
        parser.error('the supplied experiment plan explicitly requests one session')
    if args.functional_check:
        config.update(population_size=16,sample_size=4,minimum_accuracy=.25,maximum_violation_rate=.75,
                      statistical_failure_probability=.9,timeout_s=180,srs_source='local')
        config['models'] = [{'name':'functional-LR-D2','kind':'linear','layers':[2,1]}]
    if args.reuse_setup and not args.functional_check:
        parser.error('setup reuse is only allowed for functional checks')
    output = (args.output or ROOT/config['output_dir']).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if (output/'summary.json').exists():
        parser.error('output already contains a summary; choose a new empty output directory')
    source_commit = subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    source_hashes = {str(file.relative_to(ROOT)):hashlib.sha256(file.read_bytes()).hexdigest() for file in [ROOT/'blindcert/benchmark/system_runtime.py',ROOT/'blindcert/benchmark/system_relation.py',ROOT/'blindcert/benchmark/system_models.py']}
    save(output/'environment.json',{'source_commit':source_commit,'source_files_sha256':source_hashes,'platform':platform.platform(),'python':sys.version,'cpu':subprocess.check_output(['lscpu'],text=True),'memory':subprocess.check_output(['free','-b'],text=True),'thread_configuration':{'RAYON_NUM_THREADS':1,'OMP_NUM_THREADS':1,'OPENBLAS_NUM_THREADS':1,'snarkjs':'Node worker pool on the fixed eight-vCPU guest'}})
    save(output/'effective_config.json',config)
    (output/'effective_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
    workload = ROOT/'artifacts/system_workload'
    if args.functional_check:
        workload = output/'private_workload'
        from blindcert.benchmark.system_models import generate_model
        import random
        spec = config['models'][0]
        model = generate_model(spec,config['workload_seed'])
        directory = workload/'functional-LR-D2'
        directory.mkdir(parents=True,mode=0o700)
        save(directory/'owner.json',{'parameters':model.parameters})
        records = [[],[]]
        rng = random.Random(config['workload_seed'])
        for index in range(16):
            x = [rng.choice((-1,0,1)) for _ in range(2)]
            y = model.predict(x)
            records[index%2].append({'stratum':(index//2)%2,'local_index':index//4,'nonce':str(rng.getrandbits(128)),
                                     'x':x,'y':y,'attribute':int(not y)})
        for i in range(2):
            save(directory/f'holder{i}.json',records[i])
    models = []
    for spec in config['models']:
        name = spec['name'].replace(' ','_').replace(',','_')
        artifact = output/'artifacts'/name
        sid = secrets.token_hex(16)
        path = output/'sessions'/name/sid
        row = {'model':spec['name'],'structure':spec,'planned_runs':1,'successful_runs':0,
               'population_size':config['population_size'],'sample_size':config['sample_size'],
               'source_commit':source_commit,'source_files_sha256':source_hashes,'mpc_parties':3,'proof_parties':3,'status':'RUNNING','metrics':{}}
        models.append(row)
        run = None
        first_start = time.perf_counter()
        active_log = output/'logs'/name/'setup'
        def call(cmds,dirs,label):
            return commands(list(zip(cmds,dirs)),active_log,label,config['timeout_s'],config['memory_limit_gib'])
        try:
            print(json.dumps({'model':spec['name'],'stage':'setup','output':str(output)}),flush=True)
            if args.reuse_setup:
                artifact = args.reuse_setup.resolve()
                metadata = load(artifact/'metadata.json')
                from blindcert.benchmark.system_runtime import MPC,mpc_program
                (MPC/'Programs/Source'/(metadata['program_name']+'.mpc')).write_text(mpc_program(spec,config,metadata))
                call([[sys.executable,str(MPC/'compile.py'),'-F','64',metadata['program_name']]],[MPC],'recompile-mascot')
                row['functional_setup_reused'] = True
            else:
                metadata = setup(spec,config,artifact,call)
            row.update({key:metadata[key] for key in ('parameter_count','constraints','private_inputs','setup_s')})
            row['setup'] = metadata
            save(artifact/'metadata.json',metadata)
            active_log = path/'logs'
            run = session(spec,config,metadata,artifact,path,workload/name,call)
            row['first_use_total_s'] = time.perf_counter()-first_start
            row['successful_runs'] = 1
            row['metrics'] = {key:aggregate([value]) for key,value in {**run['stages'],'proof_size_kb':run['proof_bytes']/1024}.items()}
            active_log = output/'logs'/name/'single'
            control = single(path,artifact,output/'single'/name,spec,config,call)
            row['successful_runs'] = 1
            row['status'] = 'OK'
            receipts = {receipt.stem:load(receipt) for receipt in (path/'logs').glob('*.json')}
            run.update(source_commit=source_commit,source_files_sha256=source_hashes,process_receipts=receipts,backends={'mpc':'MASCOT','proof':'Groth16/REP3'},artifact_digests=metadata.get('artifacts',{}),model=spec['name'],structure=spec,population_size=config['population_size'],sample_size=config['sample_size'],
                       parameter_count=metadata['parameter_count'],mpc_parties=3,proof_parties=3,
                       single_prover=control)
            with (output/'runs.jsonl').open('a') as handle:
                handle.write(json.dumps(run)+'\n')
            values = {**run['stages'],'single_prove_s':control['single_prove_s'],'proof_size_kb':run['proof_bytes']/1024}
            row['metrics'] = {key:aggregate([value]) for key,value in values.items()}
            row['session_directory'] = str(path)
        except Exception as exc:
            row['status'] = exc.status if isinstance(exc,ExecutionFailure) else 'FAILED'
            row['reason'] = str(exc)
            if (artifact/'r1cs_metrics.json').exists():
                row.update(load(artifact/'r1cs_metrics.json'))
            with (output/'runs.jsonl').open('a') as handle:
                handle.write(json.dumps({**(run or {}),'model':spec['name'],'sid':sid,'verified':bool(run and run['verified']),'status':row['status'],'reason':str(exc)})+'\n')
            print(json.dumps({'model':spec['name'],'status':row['status'],'reason':str(exc)}),flush=True)
        with (output/'setup.jsonl').open('a') as handle:
            handle.write(json.dumps({key:value for key,value in row.items() if key != 'metrics'})+'\n')
        save(output/'summary.json',{'functional_check_only':args.functional_check,'config':config,'models':models})
    with (output/'summary.csv').open('w',newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['model','status','setup_s','e2e_s','first_use_total_s','reason'])
        for row in models:
            writer.writerow([row['model'],row['status'],row.get('setup_s'),row['metrics'].get('e2e_s',{}).get('mean'),row.get('first_use_total_s'),row.get('reason','')])
    save(output/'model_manifest.json',[{key:value for key,value in row.items() if key not in ('metrics','setup')} for row in models])
    return 0 if all(row['status']=='OK' for row in models) else 2


if __name__ == '__main__':
    raise SystemExit(main())
