from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description='Export only recorded system measurements.')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    if data.get('functional_check_only'):
        parser.error('functional checks are not paper measurements')
    args.output.mkdir(parents=True,exist_ok=True)
    def escape(value):
        return str(value).replace('_',r'\_').replace('&',r'\&').replace('%',r'\%')
    def value(row,key):
        item = row.get(key)
        if item is None:
            item = row.get('metrics',{}).get(key,{}).get('mean')
        return f'{item:.3f}' if isinstance(item,(int,float)) else r'\texttt{'+escape(row['status'])+'}'
    config = data['config']
    note = (r'\parbox{\linewidth}{\scriptsize Three MASCOT parties and three REP3 provers; $N='+str(config['population_size'])+r'$, $m='+str(config['sample_size'])+r'$. A fixed '+str(config['timeout_s'])+' s stage timeout and '+str(config['memory_limit_gib'])+r' GiB aggregate RSS budget apply. Setup includes acquisition or checksum verification of an existing SRS and circuit-specific settings. One session planned per model; sample standard deviation is unavailable for $n=1$. Setup and first-use totals are directly measured once, with OS caches retained. Status cells identify failed model attempts, including phases that were not reached; no time is estimated. Single proving is outside the certification interval.}')
    table1,table2 = [],[]
    for row in data['models']:
        table1.append(escape(row['model'])+' & '+' & '.join(value(row,key) for key in ('setup_s','e2e_s','first_use_total_s'))+r' \\')
        integers = [str(row[key]) if key in row else '--' for key in ('constraints','private_inputs')]
        table2.append(escape(row['model'])+' & '+' & '.join(integers+[value(row,key) for key in ('single_prove_s','co_witness_s','co_prove_s','verify_s','proof_size_kb')])+r' \\')
    for filename,label,caption,cols,header,rows in [
        ('table1_end_to_end.tex','tab:baseline-performance','System-level end-to-end efficiency of BlindCert.','lrrr',r'Model & Setup (s) & End-to-end (s) & First-use total (s) \\',table1),
        ('table2_model_scaling.tex','tab:larger-relations','Performance for certification relations of increasing model size.','lrrrrrrr',r'Model & Constraints & Private inputs & Single prove (s) & Co-witness (s) & Co-prove (s) & verify (s) & Proof size (KB) \\',table2)]:
        text = [r'\begin{table}[t]',r'\centering',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\scriptsize',r'\setlength{\tabcolsep}{3pt}',r'\resizebox{\linewidth}{!}{',r'\begin{tabular}{'+cols+'}',r'\hline',header,r'\hline',*rows,r'\hline',r'\end{tabular}',r'}',r'\par\smallskip',note,r'\end{table}','']
        (args.output/filename).write_text('\n'.join(text))


if __name__ == '__main__':
    main()
