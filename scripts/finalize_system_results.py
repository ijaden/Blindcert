from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import yaml
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description='Package recorded measurements without estimating missing results.')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--public-output',type=Path,required=True)
    args = parser.parse_args()
    directory = args.input.resolve()
    data = json.loads((directory/'summary.json').read_text())
    if data.get('functional_check_only') or len(data['models']) != len(data['config']['models']):
        parser.error('a complete formal attempt is required')
    workloads = {item['name']:item for item in json.loads((ROOT/'artifacts/system_workload/manifest.json').read_text())}
    for row in data['models']:
        prepared = workloads[row['model']]
        row.setdefault('parameter_count',prepared['parameter_count'])
        row['arithmetic'] = prepared['arithmetic']
        row['input_artifact_sha256'] = prepared['file_sha256']
        for key in ('setup_s','first_use_total_s'):
            if isinstance(row.get(key),(int,float)):
                value = row[key]
                row['metrics'][key] = {'n':1,'mean':value,'stdev':None,'median':value,'min':value,'max':value}
    (directory/'model_manifest.json').write_text(json.dumps([{key:value for key,value in row.items() if key not in ('metrics','setup')} for row in data['models']],indent=2)+'\n')
    (directory/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    data['execution_output_dir'] = str(directory)
    effective = yaml.safe_load((directory/'effective_config.yaml').read_text())
    effective['execution_output_dir'] = str(directory)
    (directory/'effective_config.yaml').write_text(yaml.safe_dump(effective,sort_keys=False))
    (directory/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    contexts = {row['model']:row for row in data['models']}
    records = []
    for line in (directory/'runs.jsonl').read_text().splitlines():
        record = json.loads(line)
        row = contexts[record['model']]
        for key in ('structure','source_commit','source_files_sha256','population_size','sample_size','mpc_parties','proof_parties','parameter_count','input_artifact_sha256'):
            record.setdefault(key,row.get(key))
        record['backends'] = {'mpc':'MASCOT','proof':'Groth16/REP3'}
        records.append(record)
    (directory/'runs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in records))
    metrics = sorted({key for row in data['models'] for key in row['metrics']})
    with (directory/'summary.csv').open('w',newline='') as handle:
        writer = csv.writer(handle,lineterminator="\n")
        writer.writerow(['model','status','constraints','private_inputs','planned_runs','successful_runs',*metrics,'reason'])
        for row in data['models']:
            writer.writerow([row['model'],row['status'],row.get('constraints'),row.get('private_inputs'),row['planned_runs'],row['successful_runs'],
                             *[row['metrics'].get(key,{}).get('mean') for key in metrics],row.get('reason','')])
    environment = json.loads((directory/'environment.json').read_text())
    environment['toolchain_lock'] = json.loads((ROOT/'docs/toolchain_lock.json').read_text())
    environment['resource_limits'] = {key:data['config'][key] for key in ('timeout_s','memory_limit_gib','srs_max_power')}
    environment['cgroup_limits'] = {}
    for name in ('cpu.max','memory.max','memory.swap.max'):
        path = Path('/sys/fs/cgroup')/name
        if path.exists():
            environment['cgroup_limits'][name] = path.read_text().strip()
    (directory/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    subprocess.run([sys.executable,str(ROOT/'scripts/export_system_tables.py'),'--input',str(directory/'summary.json'),
                    '--output',str(directory/'tables')],check=True)
    args.public_output.mkdir(parents=True,exist_ok=True)
    for name in ('summary.json','summary.csv','setup.jsonl','runs.jsonl','model_manifest.json','environment.json','effective_config.yaml','control_verification.json'):
        shutil.copy2(directory/name,args.public_output/name)
    shutil.copytree(directory/'tables',args.public_output/'tables',dirs_exist_ok=True)
    for row in data['models']:
        if row['status'] == 'OK':
            name = row['model'].replace(' ','_').replace(',','_')
            source = Path(row['session_directory'])
            public = args.public_output/'public_passports'/name
            public.mkdir(parents=True,exist_ok=True)
            for filename in ('passport.json','expected.json','proof.json','public.json'):
                shutil.copy2(source/filename,public/filename)
            (public/'materials').mkdir(exist_ok=True)
            shutil.copy2(directory/'artifacts'/name/'vk.json',public/'materials/vk.json')
    manifests = {}
    for path in sorted((directory/'logs').rglob('*.json')):
        manifests[str(path.relative_to(directory))] = json.loads(path.read_text())
    for path in sorted((directory/'sessions').rglob('logs/*.json')):
        manifests[str(path.relative_to(directory))] = json.loads(path.read_text())
    (args.public_output/'process_receipts.json').write_text(json.dumps(manifests,indent=2)+'\n')
    hashes = {}
    for path in args.public_output.rglob('*'):
        if path.is_file() and path.name != 'manifest_sha256.json':
            hashes[str(path.relative_to(args.public_output))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.public_output/'manifest_sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps({'models':len(data['models']),'successful_certifications':sum(row['successful_runs'] for row in data['models']),
                      'fully_successful_models':[row['model'] for row in data['models'] if row['status']=='OK'],
                      'failed_models':{row['model']:row['status'] for row in data['models'] if row['status']!='OK'},
                      'local_results':str(directory),'public_results':str(args.public_output)}))


if __name__ == '__main__':
    main()
