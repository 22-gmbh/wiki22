"""Normalize bounded request wrappers; never alter entities or factual clauses."""
import re

def normalize_request(query):
    if not isinstance(query,str) or '\n' in query or len(query)>4096:return query
    text=' '.join(query.strip().split())
    text=re.sub(r'^per favore[, ]+','',text,flags=re.I)
    text=re.sub(r'^(?:puoi dirmi|potresti dirmi|mi puoi dire|mi sapresti dire|sai dirmi|mi dici|vorrei sapere)\s+','',text,flags=re.I)
    text=re.sub(r"^qual['’]è\b",'qual è',text,flags=re.I)
    text=re.sub(r'^(qual(?:e)?|chi) é\b',lambda m:m[1]+' è',text,flags=re.I)
    explanation=re.match(r'^(?:mi spieghi|mi racconti|mi descrivi|puoi raccontarmi|potresti raccontarmi)\s+(.+)$',text,re.I)
    if explanation:
        body=explanation[1]
        text=body if re.match(r"^(?:che\b|cos['’]è\b|cosa\b|come\b|perch[eé]\b)",body,re.I) else 'Spiegami '+body
    # A noun phrase with an explicit ownership preposition is an information
    # request. Preserve modifiers, negation, dates and all remaining words.
    if re.fullmatch(r"(?:la\s+)?capitale\s+(?:dell['’]|d['’]|(?:di|del|della|dello)\s+).+",text.rstrip('?.!'),re.I):
        text='Qual è la '+re.sub(r'^la\s+','',text.rstrip('?.!'),flags=re.I)+'?'
    from .request_meaning import interpret
    meaning=interpret(text)
    if meaning and meaning.rule!='Q03' and meaning.canonical.casefold()!=text.casefold():
        text=meaning.canonical
    return text
