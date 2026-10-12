"""Build an independent public-observation research planner; preserve product binaries."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_provenance import fingerprints,sha,snapshot


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiler',type=Path,default=Path(r'C:\msys64\mingw64\bin\g++.exe'))
    args=p.parse_args(); out=args.output.resolve()
    out.relative_to(ROOT)
    out.mkdir(parents=True,exist_ok=False)
    info=snapshot(out,[]); initial=fingerprints()
    settings=ROOT/'data/fever/research/firstscore40_v1.json'
    (out/'research-settings.json').write_bytes(settings.read_bytes())
    info['research_settings_sha256']=sha(settings)
    sources=sorted((ROOT/'core').glob('*.cpp'))+[ROOT/'fever/research'/name for name in ('firstscore40_goal.cpp','firstscore40_worker.cpp')]
    flags=['-std=c++20','-O2','-msse4.1','-DNDEBUG','-static','-s']
    command=[str(args.compiler),*flags,*map(str,sources),'-o',str(out/'firstscore40.exe')]
    env={**os.environ,'PATH':str(args.compiler.parent)+os.pathsep+os.environ['PATH']}
    result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    info.update(command=command,compiler_sha256=sha(args.compiler),
                compiler_version=subprocess.check_output([str(args.compiler),'--version'],env=env,text=True).splitlines()[0],
                returncode=result.returncode,source_unchanged=initial==fingerprints(),
                compiled_sources={str(f.relative_to(ROOT)):sha(f) for f in sources},
                build_log_sha256=sha(out/'build.log'))
    if result.returncode==0:
        command2=[str(args.compiler),'-std=c++20','-O2','-shared','-static','-s','-DAMA_FEVER_OPERATION',
                  str(ROOT/'core/operation.cpp'),'-o',str(out/'operations.dll')]
        dll=subprocess.run(command2,cwd=ROOT,env=env,capture_output=True,text=True)
        (out/'operations-build.log').write_text(dll.stdout+dll.stderr,encoding='utf-8')
        info.update(operations_command=command2,operations_returncode=dll.returncode)
        if dll.returncode==0:info['binaries']={str(out/name):sha(out/name) for name in ('firstscore40.exe','operations.dll')}
        else: result=dll
    (out/'build.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if result.returncode or not info['source_unchanged']:
        print(result.stderr,file=sys.stderr);raise SystemExit('Research build failed; retained log.')
    print(json.dumps({'build':str(out/'build.json'),'binaries':info['binaries']}))


if __name__=='__main__':main()
