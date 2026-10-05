"""A chain is predicted once at its start; delivered links are never counted twice."""
from .model import integer
from .timing import ChainTiming


def enemy_events(prediction, elapsed, scored_links):
    integer(elapsed, 'elapsed frames', 0, 1000000)
    integer(scored_links, 'scored_links', 0, len(prediction['links']))
    events = [dict(type='link', frame=max(0, link.get('score_at_min',link['score_at']) - elapsed), points=link['points'])
              for link in prediction['links'][scored_links:]]
    events.append(dict(type='end', frame=max(0, prediction.get('end_frame_min',prediction['end_frame']) - elapsed)))
    return events


class ChainPrediction:
    def __init__(self, identity, character, transition, scoring, start_frame, timing=None, start_is_lock=False):
        self.identity, self.character, self.start_frame = identity, character, start_frame
        points = scoring.chain(character, transition['links'])
        if not points:
            raise ValueError('a prediction requires an actual clearing lock')
        clock=timing or ChainTiming()
        # Live captures start at the first link. Lock predictions explicitly
        # include split and the first-link check instead.
        offset=(15+clock.split_extra_frames[max(transition['split_distances'])]
                if start_is_lock and clock.geometry_enabled and 'split_distances' in transition else 0)
        self.prediction = clock.timeline(points, transition['fall_distances'],transition.get('fall_features'),offset)
        self.prediction.update(total_points=sum(points), points=points, identity=identity)
        self.observed_link = 0
        self.observed_link_frame = start_frame
        self.prediction['fall_features']=transition.get('fall_features',[])

    def observe_link(self, frame, link):
        """Re-anchor unscored links at actual onsets without recomputing score."""
        integer(link,'observed link',1,len(self.prediction['links']))
        if link > self.observed_link and frame >= self.observed_link_frame:
            self.observed_link, self.observed_link_frame = link, frame

    def remaining(self, frame, scored_links):
        predicted_onset = (self.prediction['links'][self.observed_link-1]['score_at_min']
                           if self.observed_link else 0)
        elapsed = predicted_onset + max(0,frame-self.observed_link_frame)
        return enemy_events(self.prediction,elapsed,scored_links)
