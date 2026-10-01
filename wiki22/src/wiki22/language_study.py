"""User-facing linguistic study service backed by frozen candidate14."""
import hashlib
import time
from .offline import OfflineGuard

MODES = ('Analisi completa', 'Lemma', 'Categoria', 'Tempo verbale', 'Modo verbale', 'Numero', 'Genere', 'Persona')


def question_for(mode, word=''):
    if mode not in MODES:
        raise ValueError('Scegli un tipo di analisi disponibile.')
    if mode == 'Analisi completa':
        return 'Analizza la frase'
    word = word.strip()
    if not word or len(word) > 80 or any(c in word for c in '«»“”"\n\r'):
        raise ValueError('Indica una sola parola del passaggio, senza virgolette.')
    if mode == 'Lemma':
        return f'Qual è il lemma della parola «{word}»?'
    if mode == 'Categoria':
        return f'Quale categoria grammaticale ha la parola «{word}»?'
    feature = {'Tempo verbale': 'tempo', 'Modo verbale': 'modo'}.get(mode, mode.casefold())
    return f'Quale {feature} ha la parola «{word}»?'


def analyze_passage(text, mode='Analisi completa', word='', question=''):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Scrivi un passaggio o scegli una fonte di Studio.')
    if len(text) > 16_384:
        raise ValueError('Il passaggio è troppo lungo: scegli una parte fino a 16.384 caratteri.')
    if len(question) > 8192:
        raise ValueError('La domanda è troppo lunga.')
    request = question.strip() or question_for(mode, word)
    started = time.perf_counter()
    from .native22_study_interpreter.identity import verify_implementation
    from .native22_study_interpreter.study_reader import analyze, check_analysis
    verify_implementation()
    with OfflineGuard():
        result = analyze(request, text)
        if result['STATO'] == 'ANALISI_LINGUISTICA' and result['PROVA']['request']['passage'] not in text:
            raise ValueError('La domanda cita un passaggio diverso: inseriscilo nel riquadro del testo.')
        if result['STATO'] == 'ANALISI_LINGUISTICA' and not check_analysis(request, text, result):
            raise ValueError('L’analisi non corrisponde più al testo: riprova.')
    return dict(result=result, request=request, input_sha256=hashlib.sha256(text.encode()).hexdigest(),
                elapsed_ms=round((time.perf_counter()-started)*1000, 2), llm_calls=0,
                local_statistical_inference_required=True, certified_cefr=None, human_iq=None)
