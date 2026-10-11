"""Build research-only instrumentation from pinned B0 translation units.

No production file is edited. Exact anchor checks and generated-source hashes
make the replacement inspectable. flags/source sets follow build.ps1.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_provenance import fingerprints,sha,snapshot


def replace(text,old,new,count=1):
    if text.count(old)!=count:
        raise ValueError(f"B0 source anchor changed: expected {count}: {old[:70]!r}")
    return text.replace(old,new)


def generate(out):
    text=(ROOT/'fever/search.cpp').read_text(encoding='utf-8')
    text='#include "first40_diagnostics.h"\n'+text
    text=replace(text,'    auto locks = normal_space::moves(node.field, piece, rules);',
        '    auto locks = normal_space::moves(node.field, piece, rules);\n    research::parent(node.index,locks.get_size());')
    text=replace(text,'        if (!drop) {\n            continue;',
        '        if (!drop) {\n            research::rejected(node.index,"drop_failed");\n            continue;')
    text=replace(text,'        if (child.field.is_dead(rules)) {\n            continue;',
        '        if (child.field.is_dead(rules)) {\n            research::rejected(node.index,"dead");\n            continue;')
    text=replace(text,'            if (rule::is_unsafe(heights, rules)) {\n                continue;',
        '            if (rule::is_unsafe(heights, rules)) {\n                research::rejected(node.index,"unsafe_margin");\n                continue;')
    text=replace(text,'        // Callback\n', '        research::legal(node.index);\n        // Callback\n')
    text=replace(text,'    std::vector<i64> reached(',
        '    research::begin_layer(int(depth)+1,parents.data.size());\n    std::vector<i64> reached(')
    text=replace(text,'            if (chain.count >= fever::PRUNE_CHAIN) {\n                return;',
        '            if (chain.count >= fever::PRUNE_CHAIN) {\n                research::dropped(child,w,configs,4,chain.count);\n                return;')
    text=replace(text,'                if (child.score.action < entry->action) {\n                    return;',
        '                if (child.score.action < entry->action) {\n                    research::dropped(child,w,configs,3,chain.count);\n                    return;')
    text=replace(text,'                fever::evaluate(child, w, configs);',
        '                research::evaluate_begin(child.index);\n                fever::evaluate(child, w, configs);\n                research::evaluate_end(child);')
    text=replace(text,'            children.add(child);',
        '            research::before_add(child,children,w,configs,chain.count);\n            children.add(child);')
    text=replace(text,'    // Clears the parents layer',
        '    research::finish_layer(children);\n    // Clears the parents layer')
    text=replace(text,'    // Initializes candidates',
        '    research::begin_layer(1,1);\n    // Initializes candidates')
    text=replace(text,'            child.index = i32(result.candidates.size());\n            fever::evaluate(child, w, configs);',
        '            child.index = i32(result.candidates.size());\n            research::evaluate_begin(child.index);\n            fever::evaluate(child, w, configs);\n            research::evaluate_end(child);')
    text=replace(text,'            layers[0].data.push_back(child);',
        '            layers[0].data.push_back(child);\n            research::root_node(child,placement,chain.count);')
    text=replace(text,"    // If there aren't any candidates, stops searching",
        "    research::finish_layer(layers[0]);\n    // If there aren't any candidates, stops searching")
    # This function is only the single-virtual-queue search, before search_multi.
    text=replace(text,'    return result;\n};\n\n// Beam search with multiple threads',
        '    research::completed(result);\n    return result;\n};\n\n// Beam search with multiple threads')
    text=replace(text,'    // Creates future queues',
        '    research::MultiTrace diagnostic_trace(field,queue,character,index,configs);\n    // Creates future queues')
    text=replace(text,'            results[id] = fever::search(field, queues[id], w, configs);',
        '            research::ThreadScope diagnostic_scope(diagnostic_trace,id);\n            results[id] = fever::search(field, queues[id], w, configs);')
    (out/'search.cpp').write_text(text,encoding='utf-8')
    text=(ROOT/'fever/evaluation.cpp').read_text(encoding='utf-8')
    text='#include "first40_diagnostics.h"\n'+text
    text=replace(text,'    Potential best;', '    research::potential_begin(field,configs);\n    Potential best;')
    text=replace(text,'                auto masks = remain.pop();',
        '                auto masks = remain.pop();\n                research::potential_pop();\n                auto diagnostic_masks = research::current ? std::optional(masks) : std::nullopt;')
    text=replace(text,'                        best = {scored.count, scored.score, key, i32(value)};',
        '                        best = {scored.count, scored.score, key, i32(value)};\n                        if(diagnostic_masks)research::witness(remain,*diagnostic_masks,x,c,key,scored.count,i32(value));')
    (out/'evaluation.cpp').write_text(text,encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiler',type=Path,default=Path(r'C:\msys64\mingw64\bin\g++.exe'))
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    info=snapshot(out,[]);initial=fingerprints()
    generated=out/'generated';generated.mkdir();generate(generated)
    dirs=['core','ai','ai/search','ai/search/beam','ai/search/dfs','fever_battle','fever']
    sources=[file for d in dirs for file in sorted((ROOT/d).glob('*.cpp'))
             if file not in {ROOT/'fever_battle/main.cpp',ROOT/'fever/main.cpp',ROOT/'fever/search.cpp',ROOT/'fever/evaluation.cpp'}]
    sources += [generated/'search.cpp',generated/'evaluation.cpp',ROOT/'fever/research/first40_diagnostics.cpp',ROOT/'fever/research/first40_worker.cpp']
    flags=['-std=c++20','-O2','-msse4.1','-DNDEBUG','-static','-s','-I'+str(ROOT/'fever'),'-I'+str(ROOT/'fever/research')]
    command=[str(args.compiler),*flags,*map(str,sources),'-o',str(out/'fever_battle.exe'),'-lpsapi']
    env=dict(os.environ,PATH=str(args.compiler.parent)+os.pathsep+os.environ['PATH'])
    info.update(command=command,compiler_sha256=sha(args.compiler),
        compiler_version=subprocess.check_output([str(args.compiler),'--version'],text=True,env=env).splitlines()[0],
        generated_sha256={str(file):sha(file) for file in generated.glob('*.cpp')},
        replaced_sources={'fever/search.cpp':sha(ROOT/'fever/search.cpp'),'fever/evaluation.cpp':sha(ROOT/'fever/evaluation.cpp')})
    result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    info.update(returncode=result.returncode,source_unchanged=initial==fingerprints(),build_log_sha256=sha(out/'build.log'))
    if result.returncode==0:info['binaries']={str(out/'fever_battle.exe'):sha(out/'fever_battle.exe')}
    (out/'build.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if result.returncode or not info['source_unchanged']:
        print(result.stderr,file=sys.stderr);raise SystemExit('Diagnostic build failed or inputs changed.')
    print(json.dumps({'build':str(out/'build.json'),'binary_sha256':info['binaries']}))


if __name__=='__main__':main()
