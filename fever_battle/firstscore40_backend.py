"""Public-observation score firing and tail planning, with bounded legacy fallback."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from .first40_benchmark import LegacyBackend
from .model import ROOT
from .worker import JsonProcess

SETTINGS=ROOT/'data/fever/research/firstscore40_v1.json'


class ExperimentExpired(RuntimeError):
    """Research-wide censoring, distinct from a per-move timeout failure."""


class ScoreBackend(LegacyBackend):
    def __init__(self,native,planner,config,mode='b0',budget_ms=1000,planner_budget_ms=None,experiment_deadline=None):
        if mode not in ('b0','s0','h1'):raise ValueError('invalid mode')
        if not 0<budget_ms<=5000:raise ValueError('invalid budget')
        super().__init__(native,config,250,8)
        self.mode,self.budget_ms=mode,budget_ms
        self.experiment_deadline=experiment_deadline
        self.settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
        if self.settings['targets']!={'raffina':160520,'rafisol':166840}:
            super().close();raise ValueError('research targets disagree with compiled worker/judge')
        self.planner_budget_ms=planner_budget_ms if planner_budget_ms is not None else (25 if budget_ms<=250 else budget_ms-300)
        self.planner=None;self.deadline=None;self.last_planner={}
        original=self.engine.native.ask
        def bounded(request,timeout=10):
            remaining=self.deadline-time.perf_counter() if self.deadline else timeout
            if remaining<=0:raise TimeoutError('choose deadline exceeded')
            if 'seed' in request or 'seed' in request.get('request',{}):raise ValueError('environment seed forbidden')
            return original(request,timeout=min(timeout,remaining))
        self.engine.native.ask=bounded
        try:
            if mode!='b0':
                self.planner=JsonProcess([planner],cwd=ROOT)
                self.planner.ask({'op':'reset'})
        except Exception:
            super().close();raise

    def choose(self,observation):
        self.deadline=time.perf_counter()+self.budget_ms/1000
        if self.experiment_deadline is not None:
            if time.perf_counter()>=self.experiment_deadline:raise ExperimentExpired('research wall cap reached')
            self.deadline=min(self.deadline,self.experiment_deadline)
        self.last_planner={}
        try:
            if self.planner is not None:
                available=min(self.planner_budget_ms,max(0,(self.deadline-time.perf_counter())*1000-300 if self.budget_ms>250 else self.planner_budget_ms))
                request=dict(op='goal-choose' if self.mode=='h1' else 'score-probe',observation=asdict(observation),
                    work_budget_ms=available,transition_limit=self.settings['transition_limit'],witness_limit=self.settings['witness_limit'])
                self.last_planner=self.planner.ask(request,timeout=max(.001,self.deadline-time.perf_counter()))
                proposal=self.last_planner.get('decision')
                if proposal is not None:
                    # Validate the intervention against the frozen native, never against its own prediction alone.
                    tr=self.engine.native.ask(dict(op='transition',field=list(observation.field),piece=observation.visible[0],x=proposal['x'],r=proposal['r']))
                    if tr['field']!=proposal['next_field'] or len(tr['links'])!=proposal['next_chain']:
                        raise ValueError('planner prediction differs from reference transition')
                    result=dict(proposal,chain=self.last_planner.get('first_main_chain',proposal['next_chain']),fire=proposal['action_source']=='score_fire',
                                fire_moves=len(proposal['proof']) if proposal['action_source']=='score_fire' else 0)
                else:result=super().choose(observation)
            else:result=super().choose(observation)
            if time.perf_counter()>self.deadline:raise TimeoutError('total choose budget exceeded')
            return result
        except TimeoutError:
            if self.experiment_deadline is not None and time.perf_counter()>=self.experiment_deadline:
                raise ExperimentExpired('research wall cap reached during choose') from None
            raise
        finally:self.deadline=None

    def processes(self):
        result=super().processes()
        if self.planner:result['research_planner']=self.planner.process
        return result

    def close(self):
        if self.planner:self.planner.close()
        super().close()
