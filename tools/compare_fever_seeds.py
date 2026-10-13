"""Two sets of Fever battles on the same piece seeds, match by match.

python tools/analyze_fever_matches.py BEFORE.log ... --output before.json
python tools/analyze_fever_matches.py AFTER.log ...  --output after.json
python tools/compare_fever_seeds.py before.json after.json

The seed mod (hoki0niwa.seed32, `record = 1`) fixes the colours a match is dealt and the bridge logs
the seed of each match (`match seed`). A player with the same character has the same pieces whenever
the seed is the same, so a match of one set and the match of the other with the same seed and the
same characters differ only by what the AIs did. They are the same game only up to the first
placement that differs; what is compared is how each seed came out: who lost, the largest chain
each AI fired on its normal board, and the main cause of the loss.

The same binary on the same seed does not repeat itself either (a search that ends a few ms late is
answered differently). Compare a set with a second run of itself first: what differs there is the
noise a change has to exceed.
"""
import argparse
import json
from pathlib import Path


def matches(path):
    """{(seed, characters): [match, ...]} of the rounds that have a seed."""
    out = {}
    for m in json.loads(Path(path).read_text(encoding='utf-8'))['matches']:
        if m.get('seed') is None or len(m['sides']) != 2:
            continue
        key = (m['seed'], tuple(str(m.get('characters', {}).get(ai)) for ai in ('1', '2')))
        out.setdefault(key, []).append(m)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    before, after = matches(args.before), matches(args.after)
    shared = sorted(set(before) & set(after), key=lambda key: (key[0], key[1]))
    chain = lambda m, ai: m['sides'][ai]['biggest_normal_chain']
    cause = lambda m: m['causes'][0] if m.get('causes') else '-'
    print(f'シードの付いた対局：前 {sum(map(len, before.values()))}、後 {sum(map(len, after.values()))}、'
          f'同じシード・同じキャラの組 {len(shared)}')
    print()
    print('| シード | 敗者 前→後 | AI1の通常最大連鎖 前→後 | AI2の通常最大連鎖 前→後 | 主因 前→後 |')
    print('| ---: | --- | --- | --- | --- |')
    same = decided = 0
    wins = {'before': [0, 0], 'after': [0, 0]}
    gain = {'1': [], '2': []}
    for key in shared:
        # a seed played more than once in a set: its first match stands for it
        a, b = before[key][0], after[key][0]
        if a['loser'] and b['loser']:
            decided += 1
            same += a['loser'] == b['loser']
            wins['before'][2 - a['loser']] += 1
            wins['after'][2 - b['loser']] += 1
        for ai in gain:
            gain[ai].append(chain(b, ai) - chain(a, ai))
        print(f"| {key[0]} | AI{a['loser'] or '?'}→AI{b['loser'] or '?'} | {chain(a, '1')}→{chain(b, '1')} | "
              f"{chain(a, '2')}→{chain(b, '2')} | {cause(a)}→{cause(b)} |")
    if not shared:
        return
    print()
    print(f'敗者が両方で分かる組 {decided}：同じ敗者 {same}、入れ替わり {decided - same}')
    print(f"勝ち数（AI1-AI2）：前 {wins['before'][0]}-{wins['before'][1]}、後 {wins['after'][0]}-{wins['after'][1]}")
    for ai, values in gain.items():
        print(f'AI{ai}の通常最大連鎖の差（後−前）：平均 {sum(values) / len(values):+.2f}、'
              f'増 {sum(v > 0 for v in values)}・同 {sum(v == 0 for v in values)}・減 {sum(v < 0 for v in values)}')


if __name__ == '__main__':
    main()
