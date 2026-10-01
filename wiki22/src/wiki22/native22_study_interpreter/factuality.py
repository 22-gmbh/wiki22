"""Small supervised factuality classifier; proposals/vetoes only, never truth.

No embeddings, transformer, text generator, LLM service, or external runtime
library. The optional upstream dependency parser supplies grammatical features.
Training data and gold event locations are handled by separate research tools.
"""
from __future__ import annotations
import json
from pathlib import Path

CLASSES = ('FACTUAL', 'NON_FACTUAL', 'COUNTERFACTUAL')


def features(tokens, event_id):
    """Use text and grammar only: gold labels must never enter this function."""
    by_id = {t.id: t for t in tokens}
    event = by_id[event_id]
    index = next(i for i, t in enumerate(tokens) if t.id == event_id)
    result = {'bias', 'lemma=' + event.lemma, 'pos=' + event.pos,
              'form=' + event.form.casefold(), 'rel=' + event.rel}
    for length in (2, 3, 4):
        result.add('suffix%d=' % length + event.form.casefold()[-length:])
    for feature in event.feats.split('|'):
        result.add('morph=' + feature)
    for offset in (-4, -3, -2, -1, 1, 2, 3):
        other = index + offset
        if 0 <= other < len(tokens):
            t = tokens[other]
            result.update(('w%d=' % offset + t.form.casefold(),
                           'p%d=' % offset + t.pos,
                           'l%d=' % offset + t.lemma))
    for t in tokens:
        if t.head == event.id:
            result.update(('child=' + t.rel + ':' + t.lemma,
                           'child_pos=' + t.rel + ':' + t.pos))
            for f in t.feats.split('|'):
                result.add('child_morph=' + t.rel + ':' + f)
    node = event
    for depth in range(3):
        if node.head not in by_id:
            break
        node = by_id[node.head]
        result.update(('ancestor%d=' % depth + node.lemma,
                       'ancestor_pos%d=' % depth + node.pos,
                       'ancestor_rel%d=' % depth + node.rel))
        for f in node.feats.split('|'):
            result.add('ancestor_morph%d=' % depth + f)
        for child in tokens:
            if child.head == node.id and child.lemma in {'non', 'mai', 'se', 'forse'}:
                result.add('ancestor_cue%d=' % depth + child.lemma)
    return sorted(result)


class FactualityClassifier:
    def __init__(self, model=None):
        self.model = model if model is not None else json.loads(
            (Path(__file__).parent / 'resources/factuality_weights.json').read_text())
        if self.model['schema'] != 'wiki22.factuality.perceptron.v1':
            raise ValueError('Unknown factuality model schema')
        if tuple(self.model['classes']) != CLASSES:
            raise ValueError('Unknown factuality classes')

    def predict(self, tokens, event_id):
        scores = [0.0] * len(CLASSES)
        for feature in features(tokens, event_id):
            vector = self.model['weights'].get(feature)
            if vector is not None:
                for i, value in enumerate(vector):
                    scores[i] += value
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        label = CLASSES[order[0]]
        margin = scores[order[0]] - scores[order[1]]
        return dict(label=label, margin=round(margin, 6), scores=scores,
                    veto=label != 'FACTUAL' and margin >= self.model.get('veto_margin', 0),
                    authorizes_answer=False, llm_calls=0)
