"""Navigation intent only: never knowledge, evidence or learned memory."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ResearchContext:
    topic: str
    scope: tuple[str, ...]
    query: str = ''

class ResearchJourney:
    def __init__(self):
        self.current = None
        self.accepted = {}

    def activate(self, topic, scope, query=''):
        if not isinstance(topic, str) or not 0 < len(topic.strip()) <= 180:return False
        ids=tuple(dict.fromkeys(scope))
        if not ids or any(not isinstance(i,str) or not i or len(i)>200 for i in ids):return False
        self.current=ResearchContext(topic.strip(),ids,query)
        return True

    def acknowledge(self, target, topic, scope):
        self.accepted[target]=(topic.strip(),tuple(scope))

    def action(self, target, topic, scope, busy=False):
        if not self.current:return 'none'
        if busy:return 'busy'
        now=(topic.strip(),tuple(scope));wanted=(self.current.topic,self.current.scope)
        if now==wanted:return 'current'
        # Never overwrite an unsubmitted edit or a manual library selection.
        previous=self.accepted.get(target)
        if now[0] and now!=previous:return 'draft'
        if previous and now[1]!=previous[1]:return 'draft'
        return 'open'
