"""Turn a crowded, undersized main into a small attack and a rebuildable board.

Visible pieces alone form the attack; six normal-builder virtual bags only rate recovery.
Defense and adequately sized mains remain the responsibility of the existing policy.
"""
import json
from .timing import ChainTiming


def enemy_context(request, enemy, first_main_chain, fever=None):
    """Only observed opening history or a live Fever seed gives permission."""
    if enemy['mode'] == 'normal':
        main = enemy.get('normal_chain_max')
        if (enemy.get('mode_generation') != 0 or type(main) is not int
                or main >= first_main_chain or enemy['gauge'] >= 7 or enemy.get('phase') == 'chain'
                or request.get('enemy_chain')):
            return None
        return dict(kind='normal_opening', first_main_chain=first_main_chain)
    if enemy['mode'] != 'fever' or enemy['remaining_frames'] <= 0:
        return None
    if (not request.get('enemy_chain') and enemy.get('phase') in ('controllable', 'placing')
            and not enemy.get('awaiting_seed') and any(c not in '.#' for r in enemy['field'] for c in r)):
        return dict(kind='fever_extending', remaining_frames=enemy['remaining_frames'],
                    clock_running=enemy['clock_running'])
    if not request.get('enemy_chain') or not fever or 'their_end' not in fever:
        return None
    end = fever['their_end']
    if end < 0 or (request['clock_policy']['count_chain_frames'] and enemy['clock_running']
                   and enemy['remaining_frames'] <= end):
        return None
    return dict(kind='fever_turnover', their_end=end, window=fever.get('disrupt_window', 26),
                remaining_frames=enemy['remaining_frames'], clock_running=enemy['clock_running'])


class NormalConversion:
    def __init__(self, native, solo, scoring):
        self.native, self.solo, self.scoring = native, solo, scoring
        self.cached = None

    def choose(self, request, own, enemy, baseline, options, capacity, config, margin,
               fever=None, enemy_events=None, pace=None):
        if not config.get('enabled', False) or baseline.get('reason') != 'normal_build_or_fire':
            return None
        if (own['mode'] != 'normal' or own['gauge'] >= 7
                or own['confirmed'] or own['unconfirmed']
                or any(margin.get(k) for k in ('rate_events', 'enemy_rate_events'))):
            return None
        context = enemy_context(request, enemy, config['first_main_chain'], fever)
        if context is None:
            return None
        # Reserve every remaining observed opposing link, including ones scoring
        # after our first link. A turnover candidate must actually leave a send.
        rest, produced = enemy['remainder'], 0
        for event in enemy_events or []:
            if event['type'] == 'link':
                amount, rest = (event['nuisance'], rest) if 'nuisance' in event else divmod(rest + event['points'], request['target_point'])
                produced += max(1, amount)
        context['enemy_reply'] = max(0, produced - enemy['confirmed'] - enemy['unconfirmed'])
        incoming = request.get('observation', {}).get('in_flight', {}).get('self', {})
        if incoming.get('incoming_in_flight', 0) or incoming.get('counter_in_flight', 0):
            return None
        cells = sum(c != '.' for row in own['field'] for c in row)
        main = capacity.get('available_chain', 0)
        required = min(config['main_min_chain'], options.get('build_chain', options['trigger']))
        # Opening capacity relief reuses the already completed native traversal.
        # No recovery beams, native request, or unknown colors are needed.
        if config.get('reuse_visible', False) and context['kind'] == 'normal_opening':
            seen = own.get('normal_chain_max', 0)
            if seen is None or 2 <= seen < config['first_main_chain']:
                return None  # rebuild after the observed side shot before spending more
            if seen >= config['first_main_chain'] and (own.get('moves_since_chain') is None or own['moves_since_chain'] < 12):
                return None
            quiet = capacity.get('quiet_moves', 99)
            visible_cells = sum(4 if q[0]=='0' else len(q)-2 for q in own['queue'][:3])
            capacity_cells = 4*13 + 2*(11-options.get('margin',1))
            imminent = cells + visible_cells >= capacity_cells
            if (cells < config['min_cells'] or main >= max(5,required-1)
                    or baseline.get('chain', 0) > 1
                    or (not imminent and quiet > 2)
                    or quiet > config['critical_safe_moves']):
                return None
            roots = {(r['x'], r['r']): r for r in baseline.get('normal_root_values', [])}
            reference = roots.get((baseline['x'], baseline['r']), {}).get('points', [])
            if len(reference) != 6 or baseline.get('normal_root_queue') != own['queue']:
                return None  # no comparable completed construction evidence
            pure = [0]
            for points in self.scoring.chain(own['character'], [dict(groups=[4],colors=1)] * 19):
                pure.append(pure[-1]+points)
            floor = pure[min(required,config['min_recovery'])]
            thresholds = []
            for value in reference:
                equivalent = max(n for n, score in enumerate(pure) if score <= value)
                # Allow at most two pure-chain links to be rebuilt, even when
                # the independent recovery floor would spend a mature main.
                thresholds.append(max(min(value,floor), min(value,pure[max(0,equivalent-2)])))
            eligible = []
            for candidate in capacity.get('small_immediate', []):
                move = candidate['choice']
                root = roots.get((move['x'], move['r']), {})
                points = root.get('points', [])
                # Compare the same six futures, before the single-clear penalty.
                # A sum alone can hide damage on a less favorable color bag.
                if (root.get('next_room', 0) > 0 and len(points) == 6
                        and all(a >= b for a, b in zip(points, thresholds))):
                    eligible.append((min(points), sum(points), candidate['remaining_material'],
                                     candidate['rank'], candidate, points))
            if not eligible:
                return None
            selected = max(eligible, key=lambda c: c[:4])
            forecast = dict(selected[4], enemy_context=context, found=True, reused_visible=True,
                fire_moves=1, path=[selected[4]['choice']],
                retained_points=selected[5], reference_points=reference, required_points=thresholds,
                sent=(selected[4]['conversion_points'] + own['remainder']) // request['target_point'])
            first = forecast['choice']
            actual = self.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                         x=first['x'], r=first['r']))
            points = self.scoring.chain(own['character'], actual['links'])
            if actual['dead'] or not 2 <= len(points) <= 4:
                return None
            return dict(x=first['x'], r=first['r'], shape=own['queue'][0][0],
                reason='normal_capacity_conversion', fire=bool(points), chain=len(points),
                next_chain=len(points), next_score=sum(points), next_field=actual['field'],
                link_points=points, next_all_clear=actual['all_clear'],
                decision_dependencies=['self', 'enemy'], searched_visible=len(own['queue']),
                normal_search_reused=True, normal_decision_status='conversion', capacity_conversion=forecast)
        if (cells < config['min_cells'] or not config['max_chain'] < main < required
                or baseline.get('chain', 0) >= required
                or (not capacity.get('release') and capacity.get('safe_moves', 99) > config['critical_safe_moves'])):
            return None
        weights = self.solo.sets.get(options.get('weight_set', 'fever'), self.solo.sets['build'])
        search_options = {k: v for k, v in config.items()
                          if k not in ('enabled', 'main_min_chain', 'min_cells', 'critical_safe_moves', 'first_main_chain')}
        # Respect a deliberately smaller configured search; keep deterministic resource limits.
        search_options['repair_width'] = min(search_options['repair_width'], options['beam_width'])
        search_options['repair_depth'] = min(search_options['repair_depth'], options['beam_depth'])
        native_request = dict(op='normal_conversion', field=own['field'], queue=own['queue'],
            character=own['character'], dropset_index=own['dropset_index'],
            target_point=request['target_point'], remainder=own['remainder'],
            weights=weights, options=search_options, timing=ChainTiming().native(),
            pace_frames=int(pace or 0), enemy_context=context, gauge=own['gauge'],
            gain=request['gauge_gain_on_offset'])
        key = json.dumps(dict(request=native_request, pattern=own.get('pattern'), powers=own.get('powers')), sort_keys=True)
        if self.cached is None or self.cached[0] != key:
            self.cached = key, self.native.ask(native_request)
        forecast = self.cached[1]
        if not forecast['found']:
            # Useful even for the fallback: distinguishes an impossible visible split
            # from one pruned by the bounded conversion/recovery search.
            baseline['capacity_conversion'] = forecast
            return None
        first = forecast['choice']
        actual = self.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                     x=first['x'], r=first['r']))
        points = self.scoring.chain(own['character'], actual['links'])
        if actual['dead'] or len(points) > config['max_chain']:
            return None
        return dict(x=first['x'], r=first['r'], shape=own['queue'][0][0],
            reason='normal_capacity_conversion', fire=bool(points), chain=len(points),
            next_chain=len(points), next_score=sum(points), next_field=actual['field'],
            link_points=points, next_all_clear=actual['all_clear'],
            decision_dependencies=['self', 'enemy'],
            searched_visible=len(own['queue']), normal_search_reused=False,
            normal_decision_status='conversion', capacity_conversion=forecast)
