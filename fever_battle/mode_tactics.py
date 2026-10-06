"""Shared conservative policies motivated by Namoko's original strategy notes.

Thresholds are prototype heuristics, not a claim of an optimal battle policy.
Only visible pieces are used when estimating an opponent's immediate attack.
"""
from .model import convert


def offset_gauge(points, pending, remainder, rate, gauge, gain, maximum=7):
    cancelled, offsets = 0, 0
    for point in points:
        amount, remainder, _ = convert(point, remainder, rate, pending)
        taken = min(pending, amount)
        pending -= taken
        cancelled += taken
        offsets += bool(taken)
    return dict(gauge_after=min(maximum, gauge + gain * offsets), offset_links=offsets,
                cancelled=cancelled, remaining_pending=pending)


QUICK_FRAMES = 300   # short-clock region: only visible executable continuations


def seed_turnover_plan(own, scoring, rate):
    """Conservative template estimate, not proof that unseen seeds will fire.

    Four cells/one colour per link; current observed rate, no all-clear bonus.
    Three placement cycles plus a maximum split reserve budget seed setup.
    Each chain may finish after zero, but renewal requires a positive clock.
    """
    from .timing import ChainTiming
    timing=ChainTiming.for_mode('fever')
    remaining=own['remaining_frames']; level=own['seed_chain']
    held=own['normal_confirmed']+own['normal_unconfirmed']
    pending=held+own['fever_confirmed']+own['fever_unconfirmed']
    setup=3*(timing.placement_frames+timing.spawn_frames)+max(timing.split_extra_frames)
    points=0; seeds=0
    while seeds<32 and setup+timing.first_link_frames+8<remaining:
        points+=sum(scoring.link(own['character'],i,[4],1,'fever') for i in range(1,level+1))
        seeds+=1
        end=setup+timing.first_link_frames+(level-1)*68+43
        if end+8>=remaining:break
        remaining-=end
        remaining+=max(0,level-2)*30
        remaining=min(1800,remaining)-timing.chain_ready_frames
        level=min(15,level+1)
    capacity=(points+own['remainder'])//rate
    return dict(pending_nuisance=pending,held_normal_nuisance=held,
                estimated_counter_capacity=capacity,estimated_seed_count=seeds,
                packet_fits_estimate=pending<=capacity,
                status='template_current_rate_unseen_seed_success_not_proven')


def seed_strategy(own, enemy, enemy_possible_score, turnover=None):
    # Pressure alone must not dismantle a seed with a small counter-chain.
    # The solver checks survival after confirmed drops for each build route.
    if own['remaining_frames'] <= QUICK_FRAMES:
        return 'extend', 'visible_late_fire_for_max_chain'
    if turnover is not None and turnover['packet_fits_estimate']:
        return 'quick', 'consume_seeds_packet_within_estimated_capacity'
    if turnover is not None:
        return 'extend', 'grow_next_entry_seed_packet_exceeds_estimated_capacity'
    return 'extend', 'grow_until_time_or_space_requires_fire'
