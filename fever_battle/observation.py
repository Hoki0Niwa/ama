"""Validate capture coherence and reject stale decisions before input.

The bridge supplies real observations. This module never invents memory offsets
or a game setting, and has no controller or memory-writing capability.
"""
from .model import integer


def coherent(request):
    capture = request['observation']
    frame = integer(request['frame'], 'frame')
    before = integer(capture['frame_before'], 'frame_before')
    after = integer(capture['frame_after'], 'frame_after')
    if before != frame or after != frame:
        raise ValueError('mixed-frame capture; reread both players')
    if capture['match_status'] != 'running':
        raise ValueError('only running matches may request a decision')
    for side in (request['self'], request['enemy']):
        if integer(side['observed_frame'], 'observed_frame') != frame:
            raise ValueError('player observation belongs to another frame')
        if side['phase'] not in ('controllable', 'placing', 'chain', 'waiting_seed'):
            raise ValueError('unknown player phase')
    if request['self']['phase'] != 'controllable':
        raise ValueError('own current piece is not controllable')


def authorize_reply(request, reply, latest):
    """Pure pre-input check. A newer unchanged capture may accept the decision."""
    coherent(request)
    coherent(latest)
    identity = {'match_id': request['match_id'], 'frame': request['frame'],
                'piece_id': request['self']['piece_id'],
                'dropset_index': request['self']['dropset_index']}
    if reply.get('decision_identity') != identity:
        raise ValueError('reply identity does not match the requested decision')
    if latest['frame'] < request['frame']:
        raise ValueError('latest observation predates the decision')
    for key in ('match_id', 'protocol_version', 'rule', 'target_point', 'gauge_gain_on_offset'):
        if latest[key] != request[key]:
            raise ValueError(f'{key} changed; discard decision')
    for name in ('self', 'enemy'):
        old = {k: v for k, v in request[name].items() if k != 'observed_frame'}
        new = {k: v for k, v in latest[name].items() if k != 'observed_frame'}
        if old != new:
            raise ValueError(f'{name} state changed; replan before input')
    return True
