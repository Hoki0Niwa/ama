"""Post-search measurements. No extra search and no mutation of the decision."""
from collections import Counter
from copy import deepcopy


def current(candidate):
    chain, sent, cancelled = candidate.get('chain', 0), candidate.get('sent', 0), candidate.get('cancelled', 0)
    return ('nonclear' if not chain else 'send' if sent > 0 else
            'counter_only' if cancelled > 0 else 'below_rate')


def candidate_view(candidate):
    if not candidate:
        return None
    return dict(x=candidate['x'], r=candidate['r'], current=dict(
        category=current(candidate), chain=candidate.get('chain', 0), sent=candidate.get('sent', 0),
        cancelled=candidate.get('cancelled', 0), attack=deepcopy(candidate.get('normal_attack'))),
        continuation=dict(sent=candidate.get('projected_sent', 0),
            attack=deepcopy(candidate.get('projected_normal_attack'))))


def summarize(diagnostic, reply):
    forecast = (diagnostic or {}).get('forecast') or {}
    candidates = forecast.get('candidates', [])
    counts = Counter(root_candidates=len(candidates))
    blocks = Counter()
    projected_blocks = Counter()
    for candidate in candidates:
        counts[current(candidate)] += 1
        for prefix, attack in (('current', candidate.get('normal_attack') or {}),
                               ('continuation', candidate.get('projected_normal_attack') or {})):
            detail = attack.get('diagnostic') or {}
            sending = candidate.get('sent' if prefix == 'current' else 'projected_sent', 0) > 0
            if detail:
                counts[prefix + '_evaluated'] += 1
                counts[prefix + '_enemy_excluded'] += int(sending and not detail['enemy_available'])
                counts[prefix + '_resources_pass'] += int(sending and detail['resources_pass'])
                counts[prefix + '_eligible'] += int(sending and detail['resources_pass'] and detail['enemy_available'])
            counts[prefix + '_positive'] += int(attack.get('score', 0) > 0)
            (blocks if prefix == 'current' else projected_blocks).update(detail.get('resource_blocks', []))
    choice = forecast.get('choice')
    executed = next((c for c in candidates if (c['x'], c['r']) == (reply.get('x'), reply.get('r'))), None)
    return dict(schema_version=1, scope='returned_root_candidates_after_pruning',
        search_status=(diagnostic or {}).get('status', 'not_run'), counts=dict(counts),
        resource_blocks=dict(blocks), continuation_resource_blocks=dict(projected_blocks),
        block_counts_overlap=True, selected=candidate_view(choice), executed=candidate_view(executed),
        execution=dict(action=reply.get('action'), x=reply.get('x'), r=reply.get('r'),
                       reason=reply['reason'], chain=reply.get('chain'),
                       matched_root=executed is not None),
        selected_executed=bool(choice and executed and (choice['x'], choice['r']) == (executed['x'], executed['r'])),
        completed_depth=forecast.get('completed_depth'), cutoff=forecast.get('cutoff'))


def without_diagnostics(value):
    """Remove optional output from a reused reply when the caller switches it off."""
    if isinstance(value, dict):
        return {key: without_diagnostics(item) for key, item in value.items()
                if key not in ('diagnostic', 'diagnostics')}
    if isinstance(value, list):
        return [without_diagnostics(item) for item in value]
    return value
