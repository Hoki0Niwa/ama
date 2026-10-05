"""Replay a simulation document and verify every recorded effect and final state."""
import argparse
import json
from pathlib import Path

from .model import Referee
from .mode import ModeReferee


def replay(document):
    state = document['state']
    # Runs currently begin at rate 120. Rate changes are explicit log events.
    referee_type = ModeReferee if state.get('protocol_version') == 3 else Referee
    ref = referee_type(document['characters'], document.get('initial_target_point', 120),
                  state['gauge_gain_on_offset'])
    for index, record in enumerate(document['events']):
        effect = ref.apply(record['event'])
        if effect != record['effect']:
            raise ValueError(f'recorded effect differs at event {index}')
    if ref.snapshot() != state:
        raise ValueError('recorded final state differs from replay')
    return {'events': len(ref.log), 'state_matches': True,
            'model_status': ref.snapshot()['model_status']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(json.loads(args.path.read_text(encoding='utf-8')))))


if __name__ == '__main__':
    main()
