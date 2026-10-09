"""Boards, sides and requests shared by the Fever battle tests.

AMA_BATTLE_NATIVE and AMA_TEST_FEVER_ENGINE choose the binaries under test.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.model import EMPTY

NATIVE = Path(os.environ.get('AMA_BATTLE_NATIVE', ROOT / 'bin/fever_battle/fever_battle.exe'))
SOLO = Path(os.environ.get('AMA_TEST_FEVER_ENGINE', ROOT / 'bin/fever/fever.exe'))


def seed3():
    rows = list(EMPTY)
    # Public flat-stacking seed, canonical color labels; not a Steam capture.
    rows[-7:] = ['.....R', '.....R', '.....B', '.....B', '...BRR', '..YYBB', '..YBRR']
    return rows


def seed_with_small_green():
    rows = [list(row) for row in seed3()]
    for y in range(3):
        rows[-1-y][0] = 'G'
    return [''.join(row) for row in rows]


def side(mode='normal', rows=None, queue=None):
    return dict(character='raffina', field=list(rows or EMPTY), mode=mode, gauge=7 if mode == 'fever' else 0,
                observed_frame=0, phase='controllable', moves_since_chain=0,
                dropset_index=0, piece_id=0, queue=queue or ['2:RY'], confirmed=0, unconfirmed=0,
                remainder=0, garbage_phase=0, mode_generation=1 if mode == 'fever' else 0, seed_id=1,
                prepared_frames=900, remaining_frames=900 if mode == 'fever' else 0,
                clock_running=mode == 'fever', seed_base=3, seed_chain=3,
                stored_field=list(EMPTY) if mode == 'fever' else None,
                normal_confirmed=0, normal_unconfirmed=0, fever_confirmed=0, fever_unconfirmed=0)


def bystander():
    """An opponent nothing is decided on: an empty normal board one offset from Fever, which nothing sent kills."""
    enemy = side()
    enemy['gauge'] = 6
    return enemy


def request(own=None, enemy=None):
    return dict(protocol_version=3, rule='fever_battle', match_id='mode-test', frame=0,
                observation=dict(frame_before=0, frame_after=0, match_status='running'),
                target_point=120, gauge_gain_on_offset=1,
                clock_policy=dict(count_chain_frames=True), self=own or side('fever', seed3()),
                enemy=enemy or bystander(), seed_options=dict(budget_ms=500, max_nodes=20000),
                solo_options=dict(beam_width=10, beam_depth=3))
