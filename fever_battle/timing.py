"""Steam 15209927 timing: measured boundaries and bounded geometry estimates."""
from dataclasses import dataclass
import json
from pathlib import Path
from .model import integer


@dataclass(frozen=True)
class ChainTiming:
    pop_frames: int = 55
    fall_frames_per_row: int = 2
    settle_frames: int = 14
    placement_frames: int = 14
    spawn_frames: int = 28
    score_offset_frames: int = 0
    status: str = 'steam_15209927_calibrated_chain_estimate_input_time_estimated'
    split_extra_frames: tuple = (0, 13, 18, 22, 25, 28, 30, 33, 35, 37, 39, 41, 43, 45)
    mode: str = 'normal'
    first_link_frames: int = 15
    chain_ready_frames: int = 13
    nuisance_check_frames: int = 16
    nuisance_ready_frames: int = 0

    @classmethod
    def for_mode(cls, mode, placement_frames=14):
        if mode == 'normal':
            return cls(placement_frames=placement_frames)
        if mode != 'fever':
            raise ValueError('unknown timing mode')
        data = json.loads((Path(__file__).resolve().parents[1] / 'data/fever/timing.json').read_text(encoding='utf-8'))['fever_clock']
        return cls(mode=mode, placement_frames=placement_frames, status=data['status'],
            nuisance_check_frames=14,
            nuisance_ready_frames=data['nuisance_drop_to_operable_estimate_frames'],
            pop_frames=data['pop_to_fall_frames'], settle_frames=data['after_contact_to_next_check_frames'],
            spawn_frames=data['nonclearing_lock_to_operable_without_split_frames'],
            first_link_frames=data['lock_to_first_link_without_split_frames'],
            chain_ready_frames=data['seed_exchange_estimate_frames'],
            split_extra_frames=tuple(data['split_extra_frames']))

    @property
    def geometry_enabled(self):
        # Explicit test/simulation constants retain their linear clock.
        expected = (43,2,11) if self.mode == 'fever' else (55,2,14)
        return (self.pop_frames,self.fall_frames_per_row,self.settle_frames)==expected

    @property
    def effective_status(self):
        return self.status if self.geometry_enabled else 'explicit_linear_costs'

    @staticmethod
    def fall_frames(features):
        columns=features['moving_distances_by_column']
        return max((2*max(v)-1+((3*(len(v)-1)+1)//2+1 if len(v)>1 else 0)
                    for v in columns if v),default=0)

    def duration(self,distance,features=None,terminal=False):
        if not self.geometry_enabled:
            return self.pop_frames+self.settle_frames+distance*self.fall_frames_per_row
        if features is None:features=dict(moving_distances_by_column=[[distance]] if distance else [[]])
        falling=self.fall_frames(features)
        return self.pop_frames if terminal and not falling else self.pop_frames+self.settle_frames+falling

    def native(self):
        result = {name: integer(getattr(self, name), name, 0, 10000)
                  for name in ('pop_frames', 'fall_frames_per_row', 'settle_frames',
                               'placement_frames', 'spawn_frames')}
        if result['pop_frames'] == 0 or result['placement_frames'] == 0:
            raise ValueError('pop and placement durations must be positive')
        if len(self.split_extra_frames)!=14:raise ValueError('split table must cover rows 0..13')
        result['split_extra_frames']=[None if value is None else integer(value,'split duration',0,10000)
                                      for value in self.split_extra_frames]
        result['score_offset_frames']=integer(self.score_offset_frames,'score offset',0,self.pop_frames)
        result.update(geometry_timing=self.geometry_enabled,
                      first_link_frames=integer(self.first_link_frames,'first link duration',0,10000) if self.geometry_enabled else 0,
                      chain_ready_frames=integer(self.chain_ready_frames,'chain ready duration',0,10000) if self.geometry_enabled else self.spawn_frames,
                      nuisance_check_frames=self.nuisance_check_frames if self.geometry_enabled else 0,
                      nuisance_ready_frames=integer(self.nuisance_ready_frames,'nuisance ready duration',0,10000) if self.geometry_enabled else 0,
                      mode=self.mode)
        return result

    def timeline(self, points, fall_distances, fall_features=None, start_offset=0):
        if len(points) != len(fall_distances):
            raise ValueError('each chain link needs its own fall distance')
        if fall_features is not None and len(fall_features)!=len(points):
            raise ValueError('each chain link needs its own fall geometry')
        now, links, uncertainty = start_offset, [], 0
        constants = self.native()
        for i, (point, distance) in enumerate(zip(points, fall_distances), 1):
            # Steam's displayed score advances at link onset. Pop animation
            # duration belongs to the link interval, not to score delivery.
            score_at = now + constants['score_offset_frames']
            distance=integer(distance,'fall distance',0,13)
            features=fall_features[i-1] if fall_features is not None else None
            score_min,score_max=max(start_offset,score_at-uncertainty),score_at+uncertainty
            duration=self.duration(distance,features,terminal=i==len(points))
            now += duration
            uncertainty += 2 if self.geometry_enabled and distance else 0
            links.append(dict(link=i, points=point, score_at=score_at, settled_at=now,
                              score_at_min=score_min,score_at_max=score_max,
                              duration_frames=duration,fall_distance=distance))
        return dict(links=links, end_frame=now,end_frame_min=max(start_offset,now-uncertainty),
                    end_frame_max=now+uncertainty,ready_frame=now+constants['chain_ready_frames'],
                    readiness_status=('seed_exchange_estimated_not_universal_bound' if self.mode=='fever'
                                      else 'normal_chain_ready_calibrated_estimate'),
                    observed_error_budget_per_moving_link=2 if self.geometry_enabled else 0,
                    status=self.effective_status, constants=constants)


def predict_chain(native, scoring, character, trigger_field, timing=None):
    """Called at chain start, on the locked board before the first pop."""
    resolved = native.ask(dict(op='resolve', field=trigger_field))
    points = scoring.chain(character, resolved['links'])
    timeline = (timing or ChainTiming()).timeline(points, resolved['fall_distances'],resolved.get('fall_features'))
    return dict(points=points, total_points=sum(points), field=resolved['field'],
                groups=resolved['links'], fall_features=resolved.get('fall_features',[]), **timeline)
