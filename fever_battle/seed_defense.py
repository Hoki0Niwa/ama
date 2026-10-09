"""Cached geometry checks for the actual opponent seed, all color/shape types."""
import json
from .model import ROOT


def canonical(rows):
    colors={}
    def cell(c):
        if c in '.#':return c
        return colors.setdefault(c,str(len(colors)))
    return tuple(''.join(cell(c) for c in row) for row in rows)


class SeedDefenses:
    def __init__(self,native,scoring):
        self.native,self.scoring=native,scoring
        self.cache={}
        seeds=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))['seeds']
        self.templates={}
        for s in seeds:self.templates.setdefault(canonical(s['field']),[]).append((s['id'],s['kind']))

    def observe(self,enemy,analyze=False,budget_ms=0):
        key=(enemy['character'],enemy['seed_chain'],tuple(enemy['field']),tuple(enemy['queue']),enemy.get('garbage_phase'))
        remembered=self.cache.get(key)
        if remembered is None:
            remembered=dict(profiles=[dict(amount=n,checked=False,regular_after_drop=False,counter_points=0) for n in range(31)],
                            frame=None,expanded=0)
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=remembered
        missing=[n for n in (12,30,6,18,24,13,*range(31)) if not remembered['profiles'][n]['checked']]
        missing=list(dict.fromkeys(missing))
        if analyze and missing and remembered['frame']!=enemy['observed_frame'] and len(enemy['queue'])>=2:
            result=self.native.ask(dict(op='seed_defense',field=enemy['field'],queue=enemy['queue'],
                seed_chain=enemy['seed_chain'],amounts=missing,max_nodes=16000,budget_ms=budget_ms,
                unknown_garbage_phase=enemy.get('garbage_phase') is None,garbage_phase=enemy.get('garbage_phase') or 0,
                powers=self.scoring.data['characters'][enemy['character']]['fever'],bonuses=self.scoring.data['bonuses']))
            for p in result['profiles']:
                if p['checked']:remembered['profiles'][p['amount']]=p
            remembered.update(frame=enemy['observed_frame'],expanded=result['expanded'])
        reference=self.templates.get(canonical(enemy['field']),[])
        return remembered['profiles'],dict(reference_ids=[r[0] for r in reference],
            family='/'.join(sorted({r[1] for r in reference})) if reference else 'live_modified_or_unlisted',
            checked_packets=sum(p['checked'] for p in remembered['profiles']),expanded=remembered['expanded'],
            status='visible_queue_geometry_not_unknown_future_colors')
