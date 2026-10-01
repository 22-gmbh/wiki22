"""LANG001-EXP001: small Italian-first, evidence-bound symbolic learner.
Frozen symbolic predecessor plus optional pinned non-LLM dependency parser.
Grammar productions are authored; their lexical relation instances are induced.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any


def impronta(x: Any) -> str:
    b = x if isinstance(x, bytes) else json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(b).hexdigest()


def normalizza(t: str) -> str:
    return ' '.join(t.replace('’', "'").casefold().split())


def spazi(t: str) -> str:
    return ' '.join(t.replace('’', "'").strip().split())


TOKEN = re.compile(r"\d+(?:[,.]\d+)*|[^\W\d_]+|[^\w\s]", re.UNICODE)
ART = re.compile(r"^(?:il |lo |la |i |gli |le |un |uno |una |l'|l )", re.I)
TIPI = {'persona':'PERSONA','città':'CITTA','paese':'PAESE','luogo':'LUOGO','organizzazione':'ORGANIZZAZIONE','opera':'OPERA','anno':'ANNO','numero':'NUMERO','concetto':'CONCETTO'}
COP = r'(è|sono|era|erano|fu|sei|siamo)'
QUANTIFIERS = re.compile(r'\b(?:nessuno|nessuna|nessun|niente|nulla|tutti|tutte|tutto|tutta|qualcuno|qualcuna|qualcosa|alcuni|alcune|ogni|ognuno|ognuna|ciascuno|ciascuna|chiunque|qualunque|qualsiasi)\b', re.I)


def nome(t: str) -> str:
    return ART.sub('', spazi(t)).strip(' .?!«»"')


def identita(t: str) -> str:
    return normalizza(nome(t))


def espandi(t: str) -> str:
    t = spazi(t)
    t = re.sub(r"\b(?:dell|d)'(?=\w)", 'di ', t, flags=re.I)
    for pre, forms in [('di','del dello della dei degli delle'),('a','al allo alla ai agli alle'),('in','nel nello nella nei negli nelle'),('da','dal dallo dalla dai dagli dalle'),('su','sul sullo sulla sui sugli sulle')]:
        t = re.sub(r'\b(?:'+ '|'.join(forms.split()) +r')\b', pre, t, flags=re.I)
    return t


def tokenizza(t: str, offset: int = 0) -> list[dict]:
    return [{'FORMA':m.group(), 'NORMA':normalizza(m.group()), 'INIZIO':offset+m.start(), 'FINE':offset+m.end()} for m in TOKEN.finditer(t)]


def segmenta(t: str):
    for m in re.finditer(r'[^.!?]+[.!?]?', t):
        s = m.group()
        lead = len(s)-len(s.lstrip())
        s = s.strip()
        if s:
            yield s, m.start()+lead, m.start()+lead+len(s)


class Motore:
    def __init__(self, seme: dict, grammatica: dict, regole: dict):
        self.seme = copy.deepcopy(seme['voci'])
        self.grammatica = copy.deepcopy(grammatica)
        self.regole = copy.deepcopy(regole['regole'])
        self.lessico: dict[str,dict] = {}
        for w, v in self.seme.items():
            self.lessico[w] = {'PAROLA_ID':'L-'+impronta(w)[:16], **copy.deepcopy(v), 'SIGNIFICATI_CANDIDATI':{}, 'CONTESTI_OSSERVATI':[], 'RELAZIONI':[], 'CONFIDENZA':None, 'NUMERO_OCCORRENZE':0, 'EVIDENZE':[], 'STATO':'CONFERMATA', 'ORIGINE':'SEME', 'CATEGORIE_CANDIDATE':{}, 'CONTESTI_DISTINTI':[]}
        self.entita: dict[str,dict] = {}
        self.relazioni: dict[str,dict] = {}
        self.proposizioni: list[dict] = []
        self.evidenze: dict[str,dict] = {}
        self.fonti: dict[str,dict] = {}
        self.sinonimi: dict[str,dict] = {}
        self.sensi: dict[str,dict] = {}
        self.domande_umane: list[dict] = []
        self.risposte_umane: list[dict] = []
        self.traccia_apprendimento: list[dict] = []
        self.bloccato = False
        self._visti: set[str] = set()
        self.ambiguita_risolte = 0
        self.frasi_lette = 0
        self.parole_lette = 0
        # Derived accounting only: never an authority for language or facts.
        self._metric_lex_values = {}
        self._metric_lex_totals = [0,0,0]
        self._metric_dirty_lex = set()
        self._metric_signatures = {}
        self._lemma_words = {}

    def serializza(self) -> dict:
        keys = ['seme','grammatica','regole','lessico','entita','relazioni','proposizioni','evidenze','fonti','sinonimi','sensi','domande_umane','risposte_umane','traccia_apprendimento','bloccato','ambiguita_risolte','frasi_lette','parole_lette']
        return {'schema':'ai22.lang001.memoria.v1', **{k:copy.deepcopy(getattr(self,k)) for k in keys}, 'visti':sorted(self._visti)}

    @classmethod
    def da_stato(cls, s: dict) -> 'Motore':
        m=cls({'voci':s['seme']},s['grammatica'],{'regole':s['regole']})
        for k,v in s.items():
            if k not in {'schema','visti'}: setattr(m,k,copy.deepcopy(v))
        m._visti=set(s['visti'])
        m._rebuild_metrics()
        return m

    def lemma(self, parola: str) -> str:
        n=normalizza(parola)
        if n in self.lessico:
            return self.lessico[n]['LEMMA_CANDIDATO']
        # Productive hypotheses only; irregular forms require seed/evidence.
        if n.endswith('iscono'): return n[:-6]+'ire'
        if n.endswith('isce'): return n[:-4]+'ire'
        return n

    def conosciuta(self, parola: str) -> bool:
        n=normalizza(parola)
        if not any(c.isalpha() for c in n): return True
        if n in self.lessico and self.lessico[n]['STATO'] in {'APPRESA','CONFERMATA'}: return True
        # Hypothesis of unseen regular plural, requiring an already learned base.
        variants=[]
        if n.endswith('e'): variants.append(n[:-1]+'a')
        if n.endswith('i'): variants.extend([n[:-1]+'o',n[:-1]+'e'])
        return any(x in self.lessico and self.lessico[x]['STATO'] in {'APPRESA','CONFERMATA'} for x in variants)

    def sinonimo_canonico(self, lemma: str) -> str:
        reachable={lemma}; todo=[lemma]
        while todo:
            x=todo.pop()
            for e in self.sinonimi.values():
                if len(e['EVIDENZE'])<2: continue
                if x in e['termini']:
                    for y in e['termini']:
                        if y not in reachable: reachable.add(y); todo.append(y)
        return min(reachable)

    def firma(self, p: dict, sinonimi=True) -> dict:
        f=copy.deepcopy(p['FIRMA'])
        if sinonimi: f['testa']=self.sinonimo_canonico(f['testa'])
        return f

    def relazione_nota(self, p: dict) -> bool:
        f=self.firma(p)
        for rel in self.relazioni.values():
            if rel['STATO'] not in {'APPRESA','CONFERMATA'}: continue
            if self.firma({'FIRMA':rel['FIRMA']})==f: return True
        return False

    def nome_predicato(self, firma: dict) -> str:
        return '_'.join(x.replace(' ','_') for x in [firma['testa'], *firma['modificatori'], firma['preposizione']] if x)

    def _ipotesi(self, forma: str, categoria: str, props=None) -> dict:
        n=normalizza(forma)
        lemma=self.lemma(n)
        if categoria=='VERBO' and n not in self.lessico:
            if n.endswith('ano'): lemma=n[:-3]+'are'
            elif n.endswith('a'): lemma=n[:-1]+'are'
        return {'FORMA':forma,'LEMMA_CANDIDATO':lemma,'CATEGORIA_GRAMMATICALE':categoria,'PROPRIETA_MORFOLOGICHE':props or {}}

    def _analizza_semplice(self, testo: str, antecedenti: list[str]|None=None) -> dict:
        """Syntactic proposal only: does not promote knowledge or modify memory."""
        original=testo
        s=spazi(testo).strip('.?! ')
        # G09: an explicit leading year scopes the entire simple assertion.
        # Require the comma; preserve the year and reject a second time scope.
        leading=re.fullmatch(r"(?:Nel|Nell'anno|Durante il) (\d{4}),\s+(.+)",s,re.I)
        temporal_normalized=False
        if leading:
            if re.search(r"\b(?:nel|nell.anno|durante il)\s+\d{4}\b",leading[2],re.I):
                return {'TESTO_ORIGINALE':original,'TOKENS':tokenizza(original),'STATO':'SCONOSCIUTA','MOTIVO':'TEMPI_MULTIPLI_NON_RISOLTI','IPOTESI_LESSICALI':[],'RUOLI_LOGICI':[]}
            s=leading[2]+' nel '+leading[1]
            temporal_normalized=True

        result={'TESTO_ORIGINALE':original,'TOKENS':tokenizza(original),'STATO':'SCONOSCIUTA','MOTIVO':'STRUTTURA_NON_SUPPORTATA','IPOTESI_LESSICALI':[], 'RUOLI_LOGICI':[]}
        if '?' in original or re.search(r'\b(?:se|forse|secondo|probabilmente|presumibilmente|ipoteticamente|potrebbe|sarebbe)\b', s, re.I):
            result['MOTIVO']='DOMANDA_IPOTESI_O_ATTRIBUZIONE_NON_ASSERITA'; return result
        if s.startswith(('«', '"', '*', '-')):
            result['MOTIVO']='CITAZIONE_O_FRAMMENTO_NON_ASSERITO'; return result
        if re.search(r'\b(oppure|benché|mentre|che)\b|\be\b',s,re.I):
            result['MOTIVO']='COORDINAZIONE_O_AMBIGUITA_NON_RISOLTA'; return result
        anno=None
        tm=re.search(r'\s+(?:nel|nell.anno|durante il)\s+(\d{4})$',s,re.I)
        if tm: anno=int(tm.group(1)); s=s[:tm.start()]
        syn=re.fullmatch(r'(?:Il termine\s+)?[«"\']?(\w+)[»"\']?\s+(?:significa|è sinonimo di)\s+[«"\']?(\w+)[»"\']?',s,re.I)
        if syn:
            result.update(STATO='IPOTESI',MOTIVO=None,GRAMMATICA='G05',SINONIMI=[normalizza(syn[1]),normalizza(syn[2])])
            result['IPOTESI_LESSICALI']=[self._ipotesi(x,'NOME') for x in [syn[1],syn[2]]]
            return result
        cop=re.fullmatch(r'(.+?)\s+(non\s+)?'+COP+r'\s+(.+)',s,re.I)
        neg=False; modo='INDICATIVO'; tempo='PRESENTE'; gram=None; classe=None
        if cop:
            sub,negative,aux,rest=cop.groups(); neg=bool(negative)
            tempo='IMPERFETTO' if aux.casefold() in {'era','erano'} else 'PASSATO_REMOTO' if aux.casefold()=='fu' else 'PRESENTE'
            rest=espandi(rest)
            indefinite=re.match(r'^(un|una|uno)\s+([^\s]+)(?:\s+([^\s]+))?$',rest,re.I)
            if indefinite:
                obj=' '.join(x for x in [indefinite[2],indefinite[3]] if x)
                classe=normalizza(indefinite[2]); head='essere'; mods=[]; prep='classe'; kind='TIPO'; gram='G01'
                result['IPOTESI_LESSICALI'].append(self._ipotesi(indefinite[2],'NOME',{'numero':'SINGOLARE','genere':'FEMMINILE' if indefinite[1].casefold()=='una' else 'MASCHILE'}))
            else:
                bare=nome(rest)
                pp=re.fullmatch(r'(.+?)\s+(di|a|in|da|con|su)\s+(.+)',bare,re.I)
                loc=re.fullmatch(r'(a|in|da|su)\s+(.+)',bare,re.I)
                if pp:
                    before,prep,obj=pp.groups(); words=before.split(); rawhead=words[0]; head=self.lemma(rawhead); mods=[normalizza(x) for x in words[1:]]
                    isverb=rawhead.casefold() in self.lessico and self.lessico[rawhead.casefold()]['CATEGORIA_GRAMMATICALE']=='VERBO'
                    kind='VERBALE' if isverb else 'NOMINALE'; gram='G03' if isverb else 'G02'
                    if isverb and mods: return result
                    result['IPOTESI_LESSICALI'].append(self._ipotesi(rawhead,'VERBO' if isverb else 'NOME',{'ruolo':'PREDICATO_VERBALE' if isverb else 'TESTA_PREDICATO_NOMINALE'}))
                    result['IPOTESI_LESSICALI'].extend(self._ipotesi(x,'AGGETTIVO',{'funzione':'MODIFICATORE'}) for x in words[1:])
                elif loc:
                    prep,obj=loc.groups(); head='essere'; mods=[]; kind='LUOGO'; gram='G08'
                else: return result
        else:
            # Coherent but deliberately bounded SVO: simple named subject.
            sv=re.fullmatch(r'([A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*)*)\s+(non\s+)?([a-zà-ÿ]+)\s+(.+)',s)
            if not sv: return result
            sub,negative,rawhead,obj=sv.groups(); neg=bool(negative)
            if rawhead in {'che','di','a','in','se','e'}: return result
            h=self._ipotesi(rawhead,'VERBO',{'persona':3,'numero':'SINGOLARE','tempo':'PRESENTE','modo':'INDICATIVO'})
            head=h['LEMMA_CANDIDATO']; mods=[]; prep='oggetto'; kind='TRANSITIVA'; gram='G04'
            result['IPOTESI_LESSICALI'].append(h)
        sub=nome(sub); obj=nome(obj)
        if not sub or not obj or '?' in obj or re.search(r'\bche\b',obj,re.I): return result
        if normalizza(sub) in {'lei','lui','egli','ella'}:
            ants=list(dict.fromkeys(antecedenti or []))
            if len(ants)!=1:
                result['MOTIVO']='COREFERENZA_NON_UNIVOCA'; return result
            sub=ants[0]; result['COREFERENZA']={'pronome':s.split()[0],'antecedente':sub,'regola':'G06','accordo_genere':'NON_DEDUCIBILE_DAL_SOLO_NOME'}
        signature={'costruzione':kind,'testa':head,'modificatori':mods,'preposizione':normalizza(prep)}
        roles=[{'RUOLO':'SOGGETTO','TESTO':sub},{'RUOLO':'PREDICATO_VERBALE' if kind in {'VERBALE','TRANSITIVA','LUOGO'} else 'PREDICATO_NOMINALE','TESTO':head}]
        objrole='COMPLEMENTO_OGGETTO' if prep=='oggetto' else 'COMPLEMENTO_DI_SPECIFICAZIONE' if prep=='di' else 'COMPLEMENTO_DI_LUOGO' if prep in {'a','in'} else 'PARTE_NOMINALE' if prep=='classe' else 'COMPLEMENTO_INDIRETTO'
        roles.append({'RUOLO':objrole,'TESTO':obj})
        if anno is not None: roles.append({'RUOLO':'COMPLEMENTO_DI_TEMPO','TESTO':str(anno)})
        for n in [sub,obj]:
            words=n.split()
            for i,w in enumerate(words):
                cat='NOME_PROPRIO' if w[:1].isupper() else 'AGGETTIVO' if i>0 and kind=='TIPO' and n==sub else 'NOME'
                result['IPOTESI_LESSICALI'].append(self._ipotesi(w,cat))
        prop={'FIRMA':signature,'PREDICATO':self.nome_predicato(signature),'SOGGETTO':identita(sub),'OGGETTO':identita(obj),'SOGGETTO_TESTO':sub,'OGGETTO_TESTO':obj,'NEGAZIONE':neg,'TEMPO':anno,'TEMPO_VERBALE':tempo,'MODO_VERBALE':modo,'GRAMMATICA':gram,'TIPO_ATTRIBUITO':classe,'RUOLI_LOGICI':roles,'QUALIFICATORI':mods}
        lex_h={normalizza(x['FORMA']):x for x in result['IPOTESI_LESSICALI']}
        result['ANALISI_MORFOLOGICA']=[]
        for token in result['TOKENS']:
            known=self.lessico.get(token['NORMA']); h=known if known and known['STATO'] in {'APPRESA','CONFERMATA'} else lex_h.get(token['NORMA'],{})
            result['ANALISI_MORFOLOGICA'].append({**token, 'LEMMA_CANDIDATO':h.get('LEMMA_CANDIDATO',token['NORMA']), 'CATEGORIA_GRAMMATICALE':h.get('CATEGORIA_GRAMMATICALE','PUNTEGGIATURA' if not any(c.isalnum() for c in token['FORMA']) else 'NUMERO' if token['FORMA'].isdigit() else 'SCONOSCIUTA'), 'PROPRIETA_MORFOLOGICHE':h.get('PROPRIETA_MORFOLOGICHE',{}), 'STATO':'NOTA' if known and known['STATO'] in {'APPRESA','CONFERMATA'} else 'IPOTESI'})
        result.update(STATO='IPOTESI',MOTIVO=None,GRAMMATICA=gram,PROPOSIZIONE=prop,RUOLI_LOGICI=roles)
        if temporal_normalized:result['REGOLE_NORMALIZZAZIONE']=['G09']
        return result

    def _osserva_parole(self, analisi: dict, ev: dict):
        hypotheses={normalizza(x['FORMA']):x for x in analisi['IPOTESI_LESSICALI']}
        for tok in analisi['TOKENS']:
            w=tok['NORMA']
            if not any(c.isalpha() for c in w): continue
            h=hypotheses[w] if w in hypotheses else self._ipotesi(tok['FORMA'],'SCONOSCIUTA')
            if w not in self.lessico:
                self.lessico[w]={'PAROLA_ID':'L-'+impronta(w)[:16], **h,'SIGNIFICATI_CANDIDATI':{},'CONTESTI_OSSERVATI':[],'RELAZIONI':[],'CONFIDENZA':0.0,'NUMERO_OCCORRENZE':0,'EVIDENZE':[],'STATO':'SCONOSCIUTA','ORIGINE':'APPRENDIMENTO','CATEGORIE_CANDIDATE':{},'CONTESTI_DISTINTI':[]}
            self._metric_dirty_lex.add(w)
            lex=self.lessico[w]; previous_lemma=lex['LEMMA_CANDIDATO']; lex['NUMERO_OCCORRENZE']+=1
            if ev['EVIDENCE_REF'] not in lex['EVIDENZE']:
                lex['EVIDENZE'].append(ev['EVIDENCE_REF']); lex['CONTESTI_OSSERVATI'].append({'SOURCE_REF':ev['SOURCE_REF'],'TEXT_SPAN':ev['TEXT_SPAN'],'EVIDENCE_REF':ev['EVIDENCE_REF']})
            if ev['contesto_hash'] not in lex['CONTESTI_DISTINTI']: lex['CONTESTI_DISTINTI'].append(ev['contesto_hash'])
            cat=h['CATEGORIA_GRAMMATICALE']
            if cat!='SCONOSCIUTA': lex['CATEGORIE_CANDIDATE'][cat]=lex['CATEGORIE_CANDIDATE'].get(cat,0)+1
            if lex['ORIGINE']=='SEME': continue
            cats=lex['CATEGORIE_CANDIDATE']; n=len(lex['CONTESTI_DISTINTI'])
            if cats:
                # Proper-name vs common-noun ambiguity is retained rather than silently guessed.
                top=sorted(cats,key=lambda x:(-cats[x],x))[0]
                lex['CATEGORIA_GRAMMATICALE']=top
                if cat==top:
                    lex['LEMMA_CANDIDATO']=h['LEMMA_CANDIDATO']; lex['PROPRIETA_MORFOLOGICHE'].update(h['PROPRIETA_MORFOLOGICHE'])
                lex['STATO']='CONFERMATA' if n>=3 else 'APPRESA' if n>=2 else 'IPOTESI'
                lex['CONFIDENZA']=round(n/(n+1),4)
                if len(cats)>1 and cats[top]==sorted(cats.values(),reverse=True)[1]: lex['STATO']='AMBIGUA'
            else: lex['STATO']='SCONOSCIUTA'
            if previous_lemma!=lex['LEMMA_CANDIDATO']:self._lemma_words.get(previous_lemma,set()).discard(w)
            self._lemma_words.setdefault(lex['LEMMA_CANDIDATO'],set()).add(w)

    def _osserva_entita(self, p: dict, ev: dict):
        for side in ['SOGGETTO','OGGETTO']:
            key=p[side]; display=p[side+'_TESTO']
            if key not in self.entita:
                self.entita[key]={'ENTITA_ID':'E-'+impronta(key)[:16],'NOME':display,'TIPI_CANDIDATI':{},'EVIDENZE':[],'CONTESTI':[],'STATO':'IPOTESI','CONFIDENZA':0.0}
            e=self.entita[key]
            if ev['EVIDENCE_REF'] not in e['EVIDENZE']: e['EVIDENZE'].append(ev['EVIDENCE_REF']); e['CONTESTI'].append({'SOURCE_REF':ev['SOURCE_REF'],'TEXT_SPAN':ev['TEXT_SPAN']})
            if side=='SOGGETTO' and p['TIPO_ATTRIBUITO']:
                t=TIPI.get(p['TIPO_ATTRIBUITO'],p['TIPO_ATTRIBUITO'].upper())
                e['TIPI_CANDIDATI'].setdefault(t,[]).append(ev['EVIDENCE_REF'])
            n=len(e['EVIDENZE']); e['STATO']='APPRESA' if n>=2 else 'IPOTESI'; e['CONFIDENZA']=round(n/(n+1),4)

    def osserva(self, documento: dict):
        if self.bloccato: raise RuntimeError('APPRENDIMENTO_BLOCCATO')
        testo=documento['testo']; source=documento['SOURCE_REF']; digest=impronta(testo.encode('utf-8'))
        if source in self.fonti and self.fonti[source]['sha256']!=digest: raise ValueError('SOURCE_REF_RIUTILIZZATA_CON_ALTRI_BYTE')
        self.fonti[source]={'testo':testo,'sha256':digest,'statuto':documento.get('statuto','TESTO_FORNITO')}
        antecedenti=[]
        for sentence,start,end in segmenta(testo):
            context_hash=impronta(normalizza(sentence))
            self.frasi_lette+=1; self.parole_lette+=sum(t['FORMA'][0].isalnum() for t in tokenizza(sentence))
            if context_hash in self._visti: continue
            self._visti.add(context_hash)
            evid='EV-'+impronta([source,start,end,digest])[:20]
            ev={'EVIDENCE_REF':evid,'SOURCE_REF':source,'TEXT_SPAN':[start,end],'testo':sentence,'source_sha256':digest,'contesto_hash':context_hash,'tipo':'OSSERVAZIONE_TESTUALE'}
            self.evidenze[evid]=ev
            a=self.analizza(sentence,antecedenti)
            self._osserva_parole(a,ev)
            if 'SINONIMI' in a:
                pair=sorted(a['SINONIMI']); k='|'.join(pair)
                self.sinonimi.setdefault(k,{'termini':pair,'EVIDENZE':[],'STATO':'IPOTESI'})['EVIDENZE'].append(evid)
                self.sinonimi[k]['STATO']='APPRESA' if len(self.sinonimi[k]['EVIDENZE'])>=2 else 'IPOTESI'
                continue
            if 'PROPOSIZIONE' not in a: continue
            for proposal in a.get('PROPOSIZIONI',[a['PROPOSIZIONE']]):
                p=copy.deepcopy(proposal); p['PROPOSIZIONE_ID']='P-'+impronta([p,evid])[:20]; p['EVIDENCE_REF']=evid; p['SOURCE_REF']=source; p['TEXT_SPAN']=[start,end]
                self._osserva_entita(p,ev)
                if p['TIPO_ATTRIBUITO']=='persona' and p['SOGGETTO_TESTO'] not in antecedenti: antecedenti.append(p['SOGGETTO_TESTO'])
                fid=impronta(p['FIRMA'])[:20]; rel=self.relazioni.setdefault(fid,{'RELAZIONE_ID':'R-'+fid,'FIRMA':copy.deepcopy(p['FIRMA']),'NOME':p['PREDICATO'],'EVIDENZE':[],'COPPIE_DISTINTE':[],'TIPI_ARGOMENTI_OSSERVATI':[],'STATO':'IPOTESI','CONFIDENZA':0.0})
                rel['EVIDENZE'].append(evid)
                pair=[p['SOGGETTO'],p['OGGETTO']]
                if pair not in rel['COPPIE_DISTINTE']: rel['COPPIE_DISTINTE'].append(pair)
                n=len(rel['COPPIE_DISTINTE']); rel['STATO']='CONFERMATA' if n>=3 else 'APPRESA' if n>=2 else 'IPOTESI'; rel['CONFIDENZA']=round(n/(n+1),4)
                typ=[sorted(self.entita.get(p[x],{}).get('TIPI_CANDIDATI',{})) for x in ['SOGGETTO','OGGETTO']]
                if typ not in rel['TIPI_ARGOMENTI_OSSERVATI']: rel['TIPI_ARGOMENTI_OSSERVATI'].append(typ)
                self.proposizioni.append(p)
                self._count_signature(p)
                h=p['FIRMA']['testa']
                for word in self._lemma_words.get(h,()):
                    lex=self.lessico[word]
                    if lex['LEMMA_CANDIDATO']==h and lex['ORIGINE']!='SEME':
                        self._metric_dirty_lex.add(word)
                        sid='S-'+fid
                        lex['SIGNIFICATI_CANDIDATI'].setdefault(sid,{'SIGNIFICATO_ID':sid,'FIRMA':copy.deepcopy(p['FIRMA']),'EVIDENZE':[],'STATO':'IPOTESI'})['EVIDENZE'].append(evid)
                        if rel['RELAZIONE_ID'] not in lex['RELAZIONI']: lex['RELAZIONI'].append(rel['RELAZIONE_ID'])
                        lex['SIGNIFICATI_CANDIDATI'][sid]['STATO']=rel['STATO']
                if p['TIPO_ATTRIBUITO'] and not p['SOGGETTO_TESTO'][:1].isupper():
                    words=p['SOGGETTO'].split(); base=words[0]; sense=p['OGGETTO'];
                    entry=self.sensi.setdefault(base,{})
                    ss=entry.setdefault(sense,{'indizi':[],'EVIDENZE':[]})
                    ss['EVIDENZE'].append(evid)
                    for w in words[1:]:
                        if w not in ss['indizi']: ss['indizi'].append(w)
                if not p['TIPO_ATTRIBUITO']:
                    for base,senses in self.sensi.items():
                        if len(senses)<2 or base not in normalizza(sentence).split(): continue
                        dis=self.disambigua(base,sentence)
                        if dis['STATO']=='AMBIGUA':
                            self.domande_umane.append({'SOURCE_REF':source,'EVIDENCE_REF':evid,'DOMANDA':dis['DOMANDA'],'STATO':'IN_ATTESA','RISPOSTA_UMANA':None})
                        elif dis['STATO']=='RISOLTA': self.ambiguita_risolte+=1
        self.traccia_apprendimento.append({'SOURCE_REF':source,**self.metriche_stato()})

    def _count_signature(self,p):
        key=impronta(p['FIRMA'])
        if key not in self._metric_signatures:self._metric_signatures[key]=[copy.deepcopy(p['FIRMA']),0]
        self._metric_signatures[key][1]+=1

    def _rebuild_metrics(self):
        self._metric_lex_values={};self._metric_lex_totals=[0,0,0]
        self._metric_dirty_lex=set(self.lessico);self._metric_signatures={}
        self._lemma_words={}
        for word,lex in self.lessico.items():
            if lex['ORIGINE']!='SEME':self._lemma_words.setdefault(lex['LEMMA_CANDIDATO'],set()).add(word)
        for p in self.proposizioni:self._count_signature(p)

    def metriche_stato(self):
        for word in self._metric_dirty_lex:
            lex=self.lessico[word]
            values=(int(lex['STATO'] in {'APPRESA','CONFERMATA'}),int(lex['STATO'] in {'IPOTESI','SCONOSCIUTA','AMBIGUA'}),len(lex['SIGNIFICATI_CANDIDATI'])) if lex['ORIGINE']!='SEME' else (0,0,0)
            before=self._metric_lex_values.get(word,(0,0,0))
            for i in range(3):self._metric_lex_totals[i]+=values[i]-before[i]
            self._metric_lex_values[word]=values
        self._metric_dirty_lex.clear()
        known={impronta(self.firma({'FIRMA':rel['FIRMA']})) for rel in self.relazioni.values() if rel['STATO'] in {'APPRESA','CONFERMATA'}}
        supported=sum(count for signature,count in self._metric_signatures.values() if impronta(self.firma({'FIRMA':signature})) in known)
        return {'PAROLE_LETTE':self.parole_lette,'FRASI_LETTE':self.frasi_lette,'FORME_LESSICALI':len(self.lessico),'PAROLE_APPRESE':self._metric_lex_totals[0],'IPOTESI_LESSICALI':self._metric_lex_totals[1],'SIGNIFICATI_CANDIDATI':self._metric_lex_totals[2]+sum(len(s) for s in self.sensi.values()),'ENTITA':len(self.entita),'RELAZIONI_APPRESE':sum(x['STATO'] in {'APPRESA','CONFERMATA'} for x in self.relazioni.values()),'PROPOSIZIONI_SUPPORTATE':supported,'DOMANDE_GENERATE':len(self.domande_umane),'AMBIGUITA_RISOLTE_AUTONOMAMENTE':self.ambiguita_risolte}

    def disambigua(self, parola: str, contesto: str) -> dict:
        senses=self.sensi.get(normalizza(parola),{})
        if not senses: return {'STATO':'SCONOSCIUTA','SENSO':None,'EVIDENZE':[]}
        scores={s:len(set(x['indizi']) & set(normalizza(contesto).split())) for s,x in senses.items()}
        ordered=sorted(scores,key=lambda s:(-scores[s],s))
        if len(ordered)==1 or (scores[ordered[0]]>0 and scores[ordered[0]]>scores[ordered[1]]):
            s=ordered[0]; return {'STATO':'RISOLTA','SENSO':s,'EVIDENZE':senses[s]['EVIDENZE'],'INDIZI':senses[s]['indizi']}
        return {'STATO':'AMBIGUA','SENSO':None,'EVIDENZE':sorted({e for x in senses.values() for e in x['EVIDENZE']}),'DOMANDA':f"Nel testo, «{parola}» è usata nel senso di "+' oppure '.join('«'+s+'»' for s in ordered)+'?'}

    def _domanda_semplice(self, testo: str) -> dict|None:
        s=spazi(testo).rstrip('? .'); anno=None
        tm=re.search(r'\s+nel\s+(\d{4})$',s,re.I)
        if tm: anno=int(tm[1]); s=s[:tm.start()]
        wh=re.fullmatch(r'(?:Qual|Chi) (è|era|fu)\s+(.+)',s,re.I)
        if wh:
            p=self.analizza('Entità '+wh[1]+' '+wh[2]+'.').get('PROPOSIZIONE')
            if not p: return None
            return {'FIRMA':p['FIRMA'],'SOGGETTO':None,'OGGETTO':p['OGGETTO'],'TEMPO':anno,'TEMPO_VERBALE':p['TEMPO_VERBALE'],'NEGAZIONE':False,'RISPOSTA_SLOT':'SOGGETTO','TESTO':testo}
        born=re.fullmatch(r'In quale paese è nat[oa]\s+(.+)',s,re.I)
        if born:
            return {'FIRMA':{'costruzione':'DERIVATA','testa':'nascere','modificatori':[],'preposizione':'nel_paese'},'SOGGETTO':identita(born[1]),'OGGETTO':None,'TEMPO':anno,'NEGAZIONE':False,'RISPOSTA_SLOT':'OGGETTO','TESTO':testo}
        where=re.fullmatch(r'Dove è\s+(\w+)\s+(.+)',s,re.I)
        if where:
            lemma=self.lemma(where[1]); pre='a' if lemma=='nascere' else 'in' if lemma=='situare' else None
            if pre is None: return None
            return {'FIRMA':{'costruzione':'VERBALE','testa':lemma,'modificatori':[],'preposizione':pre},'SOGGETTO':identita(where[2]),'OGGETTO':None,'TEMPO':anno,'NEGAZIONE':False,'RISPOSTA_SLOT':'OGGETTO','TESTO':testo}
        who=re.fullmatch(r'Chi\s+(\w+)\s+(.+)',s,re.I)
        if who:
            p=self.analizza('Entità '+who[1]+' '+who[2]+'.').get('PROPOSIZIONE')
            if not p: return None
            return {'FIRMA':p['FIRMA'],'SOGGETTO':None,'OGGETTO':p['OGGETTO'],'TEMPO':anno,'TEMPO_VERBALE':p['TEMPO_VERBALE'],'NEGAZIONE':False,'RISPOSTA_SLOT':'SOGGETTO','TESTO':testo}
        return None

    def prepara_evidenze(self, docs: list[dict], usa_memoria=False):
        facts=copy.deepcopy(self.proposizioni) if usa_memoria else []
        evs=copy.deepcopy(self.evidenze) if usa_memoria else {}
        sources=copy.deepcopy(self.fonti) if usa_memoria else {}
        # Types are read from the provided local evidence, not test labels.
        for doc in docs:
            sid=doc['SOURCE_REF']; text=doc['testo']; digest=impronta(text.encode())
            if sid in sources and sources[sid]['sha256']!=digest: raise ValueError('COLLISIONE_FONTE')
            sources[sid]={'testo':text,'sha256':digest,'statuto':doc.get('statuto','EVIDENZA_LOCALE')}
            ants=[]
            for sentence,lo,hi in segmenta(text):
                evid='EV-'+impronta([sid,lo,hi,digest])[:20]
                ev={'EVIDENCE_REF':evid,'SOURCE_REF':sid,'TEXT_SPAN':[lo,hi],'testo':sentence,'source_sha256':digest,'contesto_hash':impronta(normalizza(sentence)),'tipo':'LETTURA_TEMPORANEA_NON_APPRENDIMENTO'}
                evs[evid]=ev
                a=self.analizza(sentence,ants)
                if 'PROPOSIZIONE' not in a: continue
                for proposal in a.get('PROPOSIZIONI',[a['PROPOSIZIONE']]):
                    p=copy.deepcopy(proposal)
                    if p['TIPO_ATTRIBUITO']=='persona': ants.append(p['SOGGETTO_TESTO'])
                    if not self.relazione_nota(p): continue
                    p.update(PROPOSIZIONE_ID='P-'+impronta([p,evid])[:20],EVIDENCE_REF=evid,SOURCE_REF=sid,TEXT_SPAN=[lo,hi])
                    facts.append(p)
        return facts,evs,sources

    def deduci(self, facts: list[dict]) -> list[dict]:
        derived=[]; types={}
        for p in facts:
            contradicted = any(z['FIRMA']==p['FIRMA'] and z['SOGGETTO']==p['SOGGETTO'] and z['OGGETTO']==p['OGGETTO'] and z['TEMPO']==p['TEMPO'] and self.tempo_compatibile(p,z) and z['NEGAZIONE']!=p['NEGAZIONE'] for z in facts)
            if p['TIPO_ATTRIBUITO'] and not p['NEGAZIONE'] and not contradicted: types.setdefault(p['SOGGETTO'],set()).add(p['TIPO_ATTRIBUITO'])
        for rule in self.regole:
            a,b=rule['SE']; conclusion=rule['ALLORA']
            def non_contraddetta(p):
                return not any(z['FIRMA']==p['FIRMA'] and z['SOGGETTO']==p['SOGGETTO'] and z['OGGETTO']==p['OGGETTO'] and z['TEMPO']==p['TEMPO'] and z['NEGAZIONE']!=p['NEGAZIONE'] for z in facts)
            left=[p for p in facts if p['PREDICATO']==a['predicato'] and not p['NEGAZIONE'] and non_contraddetta(p)]
            right=[p for p in facts if p['PREDICATO']==b['predicato'] and not p['NEGAZIONE'] and non_contraddetta(p)]
            for x in left:
                for y in right:
                    if x['OGGETTO']!=y['SOGGETTO']: continue
                    if 'città' not in types.get(x['OGGETTO'],set()) or 'paese' not in types.get(y['OGGETTO'],set()): continue
                    if x['TEMPO'] is not None and y['TEMPO'] is not None and x['TEMPO']!=y['TEMPO']: continue
                    f={'costruzione':'DERIVATA','testa':'nascere','modificatori':[],'preposizione':'nel_paese'}
                    d={'FIRMA':f,'PREDICATO':conclusion['predicato'],'SOGGETTO':x['SOGGETTO'],'OGGETTO':y['OGGETTO'],'SOGGETTO_TESTO':x['SOGGETTO_TESTO'],'OGGETTO_TESTO':y['OGGETTO_TESTO'],'NEGAZIONE':False,'TEMPO':x['TEMPO'],'TIPO_ATTRIBUITO':None,'DERIVAZIONE':{'REGOLA':rule['REGOLA_ID'],'PREMESSE':[x['PROPOSIZIONE_ID'],y['PROPOSIZIONE_ID']],'EVIDENZE':[x['EVIDENCE_REF'],y['EVIDENCE_REF']]}}
                    type_premises=[next(z for z in facts if z['SOGGETTO']==ent and z['TIPO_ATTRIBUITO']==typ and not z['NEGAZIONE']) for ent,typ in [(x['OGGETTO'],'città'),(y['OGGETTO'],'paese')]]
                    d['DERIVAZIONE']['PREMESSE'].extend(z['PROPOSIZIONE_ID'] for z in type_premises)
                    d['DERIVAZIONE']['EVIDENZE'].extend(z['EVIDENCE_REF'] for z in type_premises)
                    d['PROPOSIZIONE_ID']='D-'+impronta(d)[:20]; derived.append(d)
        return derived

    def tempo_compatibile(self, q: dict, p: dict) -> bool:
        if q['TEMPO'] is not None:
            return q['TEMPO'] == p['TEMPO']
        # A current nominal role cannot be supplied by a historical statement.
        # Event questions (birth, location of an event) keep their own scope.
        wanted = q.get('TEMPO_VERBALE')
        if wanted is None:
            return True
        actual = p.get('TEMPO_VERBALE')
        if wanted == 'PRESENTE' and p['TEMPO'] is not None:
            return False
        if wanted in {'IMPERFETTO', 'PASSATO_REMOTO'}:
            return actual in {'IMPERFETTO', 'PASSATO_REMOTO'}
        return wanted == actual

    def compatibile(self, q: dict, p: dict, polarita=True) -> bool:
        return (self.firma(q)==self.firma(p) and all(q[x] is None or q[x]==p[x] for x in ['SOGGETTO','OGGETTO']) and self.tempo_compatibile(q, p) and (not polarita or q['NEGAZIONE']==p['NEGAZIONE']))

    def controlla(self, q: dict, candidato: dict, facts: list[dict], evs: dict, sources: dict) -> dict:
        """Independent adjudication pass: checks candidate, proof and original spans.
        No solver decision/score is accepted as evidence; no automatic PASS from retrieval.
        """
        checks=[]
        def check(n,ok): checks.append({'CONTROLLO':n,'PASS':bool(ok)})
        check('ENTITA_E_RUOLI',all(q[x] is None or q[x]==candidato[x] for x in ['SOGGETTO','OGGETTO']))
        check('RELAZIONE_E_CONTESTO',self.firma(q)==self.firma(candidato))
        check('NEGAZIONE',q['NEGAZIONE']==candidato['NEGAZIONE'])
        check('TEMPO',self.tempo_compatibile(q,candidato))
        if 'DERIVAZIONE' in candidato:
            # Recompute rule closure from source propositions, not from candidate's assertion.
            valid={impronta(x) for x in self.deduci([f for f in facts if 'DERIVAZIONE' not in f])}
            check('REGOLA_E_PREMESSE',impronta(candidato) in valid)
            refs=candidato['DERIVAZIONE']['EVIDENZE']
        else:
            refs=[candidato['EVIDENCE_REF']]
        for ref in refs:
            ev=evs.get(ref); ok=False
            if ev and ev['SOURCE_REF'] in sources:
                source=sources[ev['SOURCE_REF']]; lo,hi=ev['TEXT_SPAN']
                ok=(source['testo'][lo:hi]==ev['testo'] and impronta(source['testo'].encode())==ev['source_sha256'])
                reread={}; ants=[]
                for sentence,sl,sh in segmenta(source['testo']):
                    candidate_read=self.analizza(sentence,ants)
                    if sl==lo and sh==hi: reread=candidate_read; break
                    oldp=candidate_read.get('PROPOSIZIONE',{})
                    if oldp.get('TIPO_ATTRIBUITO')=='persona': ants.append(oldp['SOGGETTO_TESTO'])
                pp=reread.get('PROPOSIZIONE')
                if 'DERIVAZIONE' in candidato:
                    premises = candidato['DERIVAZIONE']['PREMESSE']
                    bound = [f for f in facts if f['PROPOSIZIONE_ID'] in premises and f.get('EVIDENCE_REF')==ref]
                else:
                    bound = [candidato]
                semantic = ['FIRMA','PREDICATO','SOGGETTO','OGGETTO','SOGGETTO_TESTO','OGGETTO_TESTO',
                            'NEGAZIONE','TEMPO','TEMPO_VERBALE','MODO_VERBALE','TIPO_ATTRIBUITO',
                            'GRAMMATICA','RUOLI_LOGICI','QUALIFICATORI','STRUTTURA_COMPOSTA']
                ok = ok and pp is not None and bool(bound)
                if ok:
                    ok = all(f.get('SOURCE_REF')==ev['SOURCE_REF'] and f.get('TEXT_SPAN')==ev['TEXT_SPAN']
                             and any(all(read.get(k)==f.get(k) for k in semantic) for read in reread.get('PROPOSIZIONI',[pp])) for f in bound)
            check('FONTE_E_SPAN:'+ref,ok)
        conflicts=[x['PROPOSIZIONE_ID'] for x in facts if self.firma(x)==self.firma(candidato) and x['SOGGETTO']==candidato['SOGGETTO'] and x['OGGETTO']==candidato['OGGETTO'] and x['TEMPO']==candidato['TEMPO'] and self.tempo_compatibile(candidato,x) and x['NEGAZIONE']!=candidato['NEGAZIONE']]
        check('ASSENZA_CONTRADDIZIONE',not conflicts)
        return {'VERIFICATA':all(x['PASS'] for x in checks),'CONTROLLI':checks,'CONFLITTI':conflicts}

    def _rispondi_semplice(self, domanda: str, docs: list[dict], usa_memoria=False) -> dict:
        q=self._domanda_semplice(domanda)
        out={'DOMANDA':domanda,'STATO':'SCONOSCIUTA','RISPOSTA':None,'CANDIDATI':[],'RIFLESSIONE':[],'FONTI':[],'PROPOSIZIONE_DOMANDA':q}
        if q is None: out['MOTIVO']='GRAMMATICA_DOMANDA_NON_SUPPORTATA'; return out
        if q['FIRMA']['costruzione']!='DERIVATA' and not self.relazione_nota(q):
            out['MOTIVO']='RELAZIONE_NON_ANCORA_APPRESA'; return out
        facts,evs,sources=self.prepara_evidenze(docs,usa_memoria)
        facts+=self.deduci(facts)
        # Lexical candidates are ranked for inspection only; acceptance is structural.
        words=set(normalizza(domanda).split())
        ranked=sorted(facts,key=lambda p:(-len(words & set(normalizza(p['SOGGETTO_TESTO']+' '+p['PREDICATO']+' '+p['OGGETTO_TESTO']).split())),p['PROPOSIZIONE_ID']))
        candidates=[p for p in ranked if self.compatibile(q,p)]
        out['CANDIDATI']=[p['PROPOSIZIONE_ID'] for p in candidates]
        out['SCARTI_SEMANTICI']=[{'PROPOSIZIONE_ID':p['PROPOSIZIONE_ID'],'MOTIVO':'RELAZIONE_DIVERSA' if self.firma(q)!=self.firma(p) else 'RUOLI_ENTITA_TEMPO_O_NEGAZIONE'} for p in ranked if p not in candidates]
        checked=[]
        for p in candidates:
            verdict=self.controlla(q,p,facts,evs,sources)
            out['RIFLESSIONE'].append({'CANDIDATO':p['PROPOSIZIONE_ID'],**verdict})
            if verdict['CONFLITTI']: out['STATO']='CONFLITTO'; out['MOTIVO']='EVIDENZE_CONTRADDITTORIE'; return out
            if verdict['VERIFICATA']: checked.append(p)
        if not checked:
            out['STATO']='EVIDENZA_INSUFFICIENTE'; out['MOTIVO']='NESSUNA_PROPOSIZIONE_VERIFICATA'; return out
        vals={p[q['RISPOSTA_SLOT']] for p in checked}
        if len(vals)!=1:
            out['STATO']='SCONOSCIUTA'; out['MOTIVO']='RISPOSTE_MULTIPLE_NON_DISAMBIGUATE'; return out
        p=checked[0]; answer=p[q['RISPOSTA_SLOT']+'_TESTO']; out['VALORE']=p[q['RISPOSTA_SLOT']]
        if q['FIRMA']['costruzione']=='NOMINALE':
            wording = spazi(domanda).rstrip('? .')
            wording = re.sub(r'\s+nel\s+\d{4}$', '', wording, flags=re.I)
            phrasing = re.fullmatch(r'(?:Qual|Chi) (è|era|fu)\s+(.+)', wording, re.I)
            if not phrasing:
                out['STATO']='SCONOSCIUTA'; out['MOTIVO']='COMPOSIZIONE_NON_SUPPORTATA'; return out
            predicate = phrasing[2]
            scope = f" nel {q['TEMPO']}" if q['TEMPO'] is not None else ''
            out['RISPOSTA']=f"{predicate[:1].upper()+predicate[1:]} {phrasing[1]} {answer}{scope}."
        elif q['FIRMA']['costruzione']=='DERIVATA': out['RISPOSTA']=f"Il paese di nascita documentato di {p['SOGGETTO_TESTO']} è {answer}."
        else: out['RISPOSTA']=answer+'.'
        for r in ([p['EVIDENCE_REF']] if 'DERIVAZIONE' not in p else p['DERIVAZIONE']['EVIDENZE']): out['FONTI'].append(copy.deepcopy(evs[r]))
        out.update(STATO='VERIFICATA',MOTIVO='CONTROLLORE_HA_VERIFICATO_FONTE_RUOLI_RELAZIONE',PROPOSIZIONE=p)
        return out

    def ricevi_risposta_umana(self, testo: str, riferimento_domanda: str, *, origine='UTENTE') -> dict:
        if self.bloccato: raise RuntimeError('APPRENDIMENTO_BLOCCATO')
        record={'tipo':'USER_ASSERTED','SOURCE_REF':origine,'TEXT_SPAN':[0,len(testo)],'testo':testo,'DOMANDA_REF':riferimento_domanda,'EVIDENCE_REF':'U-'+impronta([origine,testo,riferimento_domanda])[:20],'validata_indipendentemente':False}
        self.risposte_umane.append(record)
        return copy.deepcopy(record)

    def autoesercizi(self) -> list[dict]:
        """Training-only probes; never included in held-out score."""
        out=[]
        for p in self.proposizioni[:8]:
            out.append({'USO':'SOLO_AUTOBENCHMARK_DI_TRAINING','TIPO':'INVERSIONE_NEGAZIONE','PREMESSA':p['PROPOSIZIONE_ID'],'NEGAZIONE_PROPOSTA':not p['NEGAZIONE'],'RISPOSTA_ATTESA':'NON_GIUSTIFICATA_DALLA_SOLA_PREMESSA'})
        return out

    def analizza(self, testo, antecedenti=None):
        # A compound source is never replaced by a made-up shorter source.
        # Each proposal binds the entire original sentence plus its parse tree.
        if QUANTIFIERS.search(testo):
            return dict(TESTO_ORIGINALE=testo,TOKENS=tokenizza(testo),STATO='SCONOSCIUTA',MOTIVO='QUANTIFICAZIONE_NON_RISOLTA',IPOTESI_LESSICALI=[],RUOLI_LOGICI=[])
        base=self._analizza_semplice(testo,antecedenti)
        compound=bool(re.search(r'\s+(?:e|ma)\s+|,\s*che\b',testo))
        if not compound:return base
        base=dict(TESTO_ORIGINALE=testo,TOKENS=tokenizza(testo),STATO='SCONOSCIUTA',MOTIVO='COMPOSTA_NON_RISOLTA',IPOTESI_LESSICALI=[],RUOLI_LOGICI=[])
        text=spazi(testo).strip(' .')
        if len(text)>1000 or re.search(r'[?!"«»{}\[\]<>;]|\b(?:se|forse|secondo|probabilmente|presumibilmente|ipoteticamente|potrebbe|sarebbe|afferma|sostiene|oppure)\b',text,re.I):return base
        # Canonical library text may be lowercase. The simple grammar must
        # still validate both complete clauses; capitalization is not truth.
        name=r'[A-Za-zÀ-ÿ][\wÀ-ÿ]*(?:\s+[A-Za-zÀ-ÿ][\wÀ-ÿ]*)*'
        relative=re.fullmatch(r'('+name+r'), che ([^,;.!?]{1,150}), ((?:non )?(?:è|era|fu|sono|erano) .+)',text)
        parts=None;tree=None
        if relative:
            parts=[relative[1]+' '+relative[3]+'.']
            tree=dict(regola='G11',relativa_opaca=relative[2],soggetto=relative[1],originale=testo)
        else:
            split=re.split(r'\s+(e|ma)\s+(?='+name+r' (?:non )?(?:è|era|fu|sono|erano)\b)',text)
            if len(split)==3 and all(re.match(name+r' (?:non )?(?:è|era|fu|sono|erano)\b',piece) for piece in (split[0],split[2])):
                parts=[split[0]+'.',split[2]+'.'];tree=dict(regola='G10',congiunzione=split[1],originale=testo)
        if not parts:return base
        analyses=[self._analizza_semplice(part,antecedenti) for part in parts]
        if any('PROPOSIZIONE' not in a for a in analyses):return base
        # A prepositional phrase or unresolved relative cannot be promoted
        # to the subject of an independent coordinated clause.
        for analysis in analyses:
            subject=analysis['PROPOSIZIONE']['SOGGETTO_TESTO']
            if re.match(r'(?:di|del|della|dello|dei|degli|delle|a|al|alla|da|dal|dalla|in|nel|nella|con|su|sul|sulla|per|tra|fra)\b',subject,re.I) or re.search(r'\b(?:che|cui|dove|quando|come)\b',subject,re.I):return base
        props=[]
        for index,a in enumerate(analyses):
            prop=copy.deepcopy(a['PROPOSIZIONE']);prop['STRUTTURA_COMPOSTA']=dict(tree,indice=index,matrice=parts[index]);props.append(prop)
        result=copy.deepcopy(analyses[0]);result.update(TESTO_ORIGINALE=testo,TOKENS=tokenizza(testo),PROPOSIZIONE=props[0],PROPOSIZIONI=props,ALBERO_FRASI=tree)
        result['IPOTESI_LESSICALI']=[h for a in analyses for h in a['IPOTESI_LESSICALI']]
        return result

    def domanda(self, testo):
        new=self._context_shape(testo)
        if new:return dict(TIPO_AVANZATO=new[0],TESTO=testo)
        old=self._domanda_semplice(testo)
        if old is not None:return old
        shape=self._advanced_shape(testo)
        if shape:return dict(TIPO_AVANZATO=shape[0],TESTO=testo)
        if self._dependency_question(testo):return dict(TIPO_AVANZATO='dependency',TESTO=testo)
        return None

    @staticmethod
    def _advanced_shape(question):
        context=Motore._context_shape(question)
        if context:return context
        text=spazi(question).rstrip(' ?.');name=r'[A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*)*'
        causal=re.fullmatch(r'Perch[ée] (.+)',text,re.I)
        if causal:return 'cause',causal[1]
        relation=re.fullmatch(r'('+name+r') ([a-zà-ÿ]+) ('+name+r')',text)
        if relation:return 'transitive',relation.groups()
        lower=re.fullmatch(r'([a-zà-ÿ]+) ([a-zà-ÿ]+) ([a-zà-ÿ]+)',text)
        if lower:return 'transitive',lower.groups()
        return None

    def _advanced_solve(self, question, docs):
        """Bounded proof proposal from literal local premises, no memory facts."""
        shape=self._advanced_shape(question)
        if shape is None:return None
        records=[];seen={}
        if shape[0] in {'necessary','effect','assertion','reference','reference_event'} and (len({d['SOURCE_REF'] for d in docs})!=1 or any(any(mark in d['testo'] for mark in ['«','»','\"']) for d in docs)):
            return dict(status='EVIDENZA_INSUFFICIENTE',reason='FONTI_O_CITAZIONI_NON_RISOLTE')
        if len(docs)>40 or sum(len(d['testo']) for d in docs)>262144:return dict(status='EVIDENZA_INSUFFICIENTE')
        for d in docs:
            sid=d['SOURCE_REF'];text=d['testo'];sha=impronta(text.encode())
            if sid in seen and seen[sid]!=sha:raise ValueError('COLLISIONE_FONTE')
            if sid in seen:continue
            seen[sid]=sha
            if any(mark in text for mark in ['«','»','"']):continue
            for sentence,lo,hi in segmenta(text):
                records.append(dict(SOURCE_REF=sid,TEXT_SPAN=[lo,hi],testo=sentence,source_sha256=sha,
                    EVIDENCE_REF='EV-'+impronta([sid,lo,hi,sha])[:20]))
        if len(records)>512:return dict(status='EVIDENZA_INSUFFICIENTE')
        if shape[0] in {'necessary','effect','assertion','reference','reference_event'}:return self._linguistic_proposal(shape,records)
        if shape[0] in {'sequence','contrast'}:return self._discourse_proposal(shape,records)
        if shape[0] in {'comparison','passive'}:return self._context_proposal(shape,records)
        if shape[0]=='cause':
            target=normalizza(shape[1]);found=[]
            for r in records:
                text=spazi(r['testo'])
                if not text.endswith('.') or re.search(r'[?!"«»{}\[\]<>;]|\b(?:se|forse|secondo|probabilmente|sarebbe|potrebbe|afferma|sostiene|che|quando|benché|mentre|dice|dicono|crede|ritiene|nega|negano)\b',text,re.I):continue
                match=re.fullmatch(r'([A-ZÀ-ÖØ-Ý][^,.;:!?]{2,220}?) perché ([^.;:!?]{2,220})\.',text)
                if not match or re.search(r'\bnon\b',match[1],re.I) or ' perché ' in match[2]:continue
                if re.search(r'\b(?:e|ma|o|oppure)\b',match[2],re.I):continue
                # Scope across sentences is unresolved: an external negation
                # may deny the effect. Never discard it to select a cause.
                if any(other is not r and re.search(r'\b(?:non|nega|negano|falso|smentisce|smentito)\b',other['testo'],re.I) for other in records):continue
                if normalizza(match[1])!=target:continue
                found.append(dict(value=normalizza(match[2]),answer='La causa indicata dalla fonte è: «'+match[2]+'».',sources=[r],rule='G12_CAUSA_ESPLICITAMENTE_AFFERMATA'))
            if len({f['value'] for f in found})>1:return dict(status='SCONOSCIUTA',reason='CAUSE_MULTIPLE_DA_DISTINGUERE')
            return dict(status='VERIFICATA',**found[0]) if found else dict(status='EVIDENZA_INSUFFICIENTE')
        subject,relation,obj=shape[1];subject=identita(subject);obj=identita(obj)
        rules=[r for r in records if re.fullmatch(re.escape(relation)+r' è una relazione transitiva\.',spazi(r['testo']),re.I)]
        if not rules:return dict(status='EVIDENZA_INSUFFICIENTE',reason='TRANSITIVITA_NON_DICHIARATA')
        if any(re.fullmatch(re.escape(relation)+r' non è una relazione transitiva\.',spazi(r['testo']),re.I) for r in records):
            return dict(status='CONFLITTO',reason='REGOLA_CONTRADDETTA')
        name=r'[A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ]*)*'
        pattern=re.compile(r'('+name+r') (non )?'+re.escape(relation)+r' ('+name+r')\.')
        relevant=[r for r in records if re.search(r'(?<!\w)'+re.escape(relation)+r'(?!\w)',r['testo'],re.I)]
        if QUANTIFIERS.search(question) or any(QUANTIFIERS.search(r['testo']) for r in relevant):
            return dict(status='SCONOSCIUTA',reason='QUANTIFICAZIONE_NON_RISOLTA')
        if len({r['SOURCE_REF'] for r in relevant})>1:
            return dict(status='SCONOSCIUTA',reason='IDENTITA_TRA_FONTI_NON_RISOLTE')
        if any(re.search(r'\b(?:forse|probabilmente|secondo|se|potrebbe|sarebbe|quando|mentre)\b',r['testo'],re.I) for r in relevant):
            return dict(status='EVIDENZA_INSUFFICIENTE',reason='MODALITA_O_CONDIZIONE_NON_RISOLTA')
        positive={};negative={}
        for r in records:
            match=pattern.fullmatch(spazi(r['testo']))
            if match:
                key=identita(match[1]),identita(match[3]);(negative if match[2] else positive).setdefault(key,r)
            elif r in relevant and r not in rules:
                return dict(status='EVIDENZA_INSUFFICIENTE',reason='CONTESTO_RELAZIONALE_NON_ANALIZZATO')
        if len(positive)>64:return dict(status='EVIDENZA_INSUFFICIENTE',reason='LIMITE_GRAFO')
        # A disputed link cannot become a proof step. Search at most four links.
        edges={k:v for k,v in positive.items() if k not in negative};queue=[(subject,[],{subject})];proof=None
        for node,path,visited in queue:
            if len(path)>=4:continue
            for (a,b),source in edges.items():
                if a!=node:continue
                chain=path+[source]
                if b==obj:proof=chain;break
                if b not in visited:queue.append((b,chain,visited|{b}))
            if proof:break
            if len(queue)>256:break
        if proof and (subject,obj) in negative:return dict(status='CONFLITTO',reason='CONCLUSIONE_NEGATA_NELLE_FONTI')
        if not proof:return dict(status='EVIDENZA_INSUFFICIENTE')
        return dict(status='VERIFICATA',value='sì',answer='Sì: '+shape[1][0]+' '+relation+' '+shape[1][2]+'. La conclusione usa la transitività dichiarata e '+str(len(proof))+' collegamenti documentati.',sources=proof+[rules[0]],rule='G13_TRANSITIVITA_DICHIARATA',steps=len(proof))

    def _check_advanced_proof(self, question, proof):
        """Check the submitted path locally, without searching for a new path."""
        shape=self._advanced_shape(question)
        if not shape or proof.get('status')!='VERIFICATA':return False
        sources=proof.get('sources',[])
        if shape[0] in {'necessary','effect','assertion','reference','reference_event'}:
            return self._linguistic_proposal(shape,sources)==proof
        if shape[0] in {'sequence','contrast'}:
            return self._discourse_proposal(shape,sources)==proof
        if shape[0] in {'comparison','passive'}:
            if len(sources)!=1:return False
            checked=self._context_proposal(shape,sources)
            return checked==proof
        if shape[0]=='cause':
            if len(sources)!=1 or proof.get('rule')!='G12_CAUSA_ESPLICITAMENTE_AFFERMATA':return False
            sentence=spazi(sources[0]['testo']).rstrip('.')
            effect,separator,cause=sentence.partition(' perché ')
            return bool(separator and normalizza(effect)==normalizza(shape[1]) and normalizza(cause)==proof.get('value')
                and proof.get('answer')=='La causa indicata dalla fonte è: «'+cause+'».')
        if proof.get('rule')!='G13_TRANSITIVITA_DICHIARATA' or not 2<=len(sources)<=5:return False
        subject,relation,target=shape[1]
        if normalizza(sources[-1]['testo'])!=normalizza(relation+' è una relazione transitiva.'):return False
        current=identita(subject)
        for source in sources[:-1]:
            left,separator,right=spazi(source['testo']).rstrip('.').partition(' '+relation+' ')
            if not separator or identita(left)!=current or not right:return False
            current=identita(right)
        expected='Sì: '+subject+' '+relation+' '+target+'. La conclusione usa la transitività dichiarata e '+str(len(sources)-1)+' collegamenti documentati.'
        return current==identita(target) and proof.get('steps')==len(sources)-1 and proof.get('value')=='sì' and proof.get('answer')==expected

    def _rispondi_previous(self, domanda, docs, usa_memoria=False):
        context=self._context_shape(domanda)
        fallback=None
        if (context is None or context[0]=='reference_event') and self._domanda_semplice(domanda) is not None:
            fallback=self._rispondi_semplice(domanda,docs,usa_memoria)
            if context is None or fallback['STATO'] in {'VERIFICATA','CONFLITTO'}:return fallback
        out={'DOMANDA':domanda,'STATO':'SCONOSCIUTA','RISPOSTA':None,'CANDIDATI':[],'RIFLESSIONE':[],'FONTI':[],'PROPOSIZIONE_DOMANDA':self.domanda(domanda)}
        proof=self._advanced_solve(domanda,docs)
        if proof is None:out['MOTIVO']='GRAMMATICA_DOMANDA_NON_SUPPORTATA';return out
        if proof['status']!='VERIFICATA' and fallback is not None:return fallback
        if proof['status']!='VERIFICATA':out.update(STATO=proof['status'],MOTIVO=proof.get('reason','NESSUNA_PROVA_VERIFICATA'));return out
        # Recompute and bind the proof to exact spans and whole-source hashes.
        repeated=self._advanced_solve(domanda,copy.deepcopy(docs));checks=[]
        checks.append(dict(CONTROLLO='REGOLA_E_CATENA_RICALCOLATE',PASS=proof==repeated))
        checks.append(dict(CONTROLLO='CATENA_E_RISPOSTA_CONTROLLATE_SEPARATAMENTE',PASS=self._check_advanced_proof(domanda,proof)))
        texts={d['SOURCE_REF']:d['testo'] for d in docs}
        for r in proof['sources']:
            text=texts[r['SOURCE_REF']];lo,hi=r['TEXT_SPAN']
            checks.append(dict(CONTROLLO='FONTE_E_SPAN:'+r['EVIDENCE_REF'],PASS=text[lo:hi]==r['testo'] and impronta(text.encode())==r['source_sha256']))
        valid=all(c['PASS'] for c in checks);out['RIFLESSIONE']=[dict(VERIFICATA=valid,CONTROLLI=checks,CONFLITTI=[])]
        if not valid:out.update(STATO='EVIDENZA_INSUFFICIENTE',MOTIVO='PROVA_NON_RIPRODUCIBILE');return out
        out.update(STATO='VERIFICATA',VALORE=proof['value'],RISPOSTA=proof['answer'],FONTI=copy.deepcopy(proof['sources']),MOTIVO='REGOLA_ESPLICITA_E_FONTI_RICONTROLLATE',PROVA=proof)
        return out


    @staticmethod
    def _context_shape(question):
        new=Motore._linguistic_shape(question)
        if new:return new
        new=Motore._discourse_shape(question)
        if new:return new
        text=spazi(question).rstrip(' ?.');phrase=r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{0,100}?"
        degree=r'alto|alta|basso|bassa|lungo|lunga|corto|corta|veloce|lento|lenta|grande|piccolo|piccola|caldo|calda|freddo|fredda|pesante|leggero|leggera'
        m=re.fullmatch(r'(?:Tra|Fra) ('+phrase+r') e ('+phrase+r'), (?:chi|quale) è (più|meno) ('+degree+r')',text,re.I)
        if m:return 'comparison',m.groups()
        m=re.fullmatch(r'Da chi (è stato|è stata|fu|era|è|sono stati|sono state) ([a-zà-ÿ]+) ('+phrase+r')',text,re.I)
        if m and re.fullmatch(r'(?:[a-zà-ÿ]+(?:ato|ata|ati|ate|uto|uta|uti|ute|ito|ita|iti|ite)|scritto|scritta|dipinto|dipinta|fatto|fatta|posto|posta|scelto|scelta|respinto|respinta|aperto|aperta|chiuso|chiusa|preso|presa|deciso|decisa|visto|vista)',m[2],re.I):return 'passive',m.groups()
        return None

    @staticmethod
    def _context_proposal(shape,records):
        # Only explicit, unqualified, same-source comparisons or passive agents.
        # Unanalysed relevant contexts withhold an answer rather than disappearing.
        unknown=dict(status='EVIDENZA_INSUFFICIENTE',reason='AMBITO_DEL_CONFRONTO_O_PASSIVO_NON_RISOLTO')
        kind,args=shape
        phrase=r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{0,100}?"
        blocked=re.compile(r"\b(?:non|se|forse|secondo|probabilmente|sarebbe|potrebbe|dovrebbe|che|quando|mentre|prima|dopo|ora|oggi|ieri|domani|sempre|mai|solo|quasi|circa|e|o|ma|lui|lei|esso|essa|essi|esse|questo|questa|quello|quella)\b",re.I)
        if any(QUANTIFIERS.search(a) or blocked.search(a) for a in args):return unknown
        found=[];relevant=[]
        if any(re.search(r'\b(?:nel|prima|dopo|ieri|oggi|domani|passato|futuro|secondo|forse|se|smentisce|nega)\b|[0-9]',r['testo'],re.I) for r in records):return unknown
        for r in records:
            text=spazi(r['testo'])
            if kind=='comparison':
                a,b,direction,quality=args
                # Require both exact referents, not substring neighbours.
                if not all(re.search(r'(?<!\w)'+re.escape(x)+r'(?!\w)',text,re.I) for x in (a,b)):continue
                relevant.append(r)
                m=re.fullmatch(r'('+phrase+r') è (più|meno) ('+re.escape(quality)+r') di ('+phrase+r')\.',text,re.I)
                if not m or blocked.search(text) or QUANTIFIERS.search(text):return unknown
                left,pol,_,right=m.groups()
                if {identita(left),identita(right)}!={identita(a),identita(b)} or identita(left)==identita(right):return unknown
                chosen=left if pol.casefold()==direction.casefold() else right
                value=identita(chosen);answer='Nel confronto esplicito della fonte: '+chosen+'.'
                rule='G14_CONFRONTO_ESPLICITO'
            else:
                tense,participle,patient=args
                if not re.search(r'(?<!\w)'+re.escape(patient)+r'(?!\w)',text,re.I):continue
                relevant.append(r)
                m=re.fullmatch(re.escape(patient)+r' '+re.escape(tense)+r' '+re.escape(participle)+r' da ('+phrase+r')\.',text,re.I)
                if not m or blocked.search(text) or QUANTIFIERS.search(text):return unknown
                agent=m[1];value=identita(agent);answer='La fonte indica come agente: '+agent+'.';rule='G15_AGENTE_PASSIVO_ESPLICITO'
            found.append(dict(status='VERIFICATA',value=value,answer=answer,sources=[r],rule=rule))
        if len({r['SOURCE_REF'] for r in relevant})>1:return unknown
        if len({r['value'] for r in found})>1:return dict(status='CONFLITTO',reason='CONFRONTI_O_AGENTI_IN_DISACCORDO')
        return found[0] if found else unknown


    @staticmethod
    def _discourse_shape(question):
        text=spazi(question).rstrip(' ?.');term=r"[a-zà-ÿ][a-zà-ÿ' -]{0,60}?"
        if re.fullmatch(r"(?:Qual è il prossimo elemento applicando la regola dichiarata|Qual è il prossimo numero secondo la regola|Continua la sequenza secondo la regola)",text,re.I):
            return 'sequence',()
        m=re.fullmatch(r"Qual è la differenza (?:fra|tra) ("+term+r") e ("+term+r")(?: descritta dal testo)?",text,re.I)
        if m and identita(m[1])!=identita(m[2]):return 'contrast',m.groups()
        return None

    @staticmethod
    def _discourse_proposal(shape,records):
        unknown=dict(status='EVIDENZA_INSUFFICIENTE',reason='REGOLA_O_CONTRASTO_NON_UNIVOCO')
        # Bind a complete, bounded source. Extra context cannot disappear.
        if not records or len({r['SOURCE_REF'] for r in records})!=1:return unknown
        kind,args=shape
        if kind=='sequence':
            if len(records)!=2:return unknown
            rule=spazi(records[0]['testo']);series=spazi(records[1]['testo'])
            seq=re.fullmatch(r'La sequenza è ([^.?!;]{1,300})\.',series,re.I)
            if not seq:return unknown
            values=[s.strip() for s in seq[1].split(',')]
            if not 3<=len(values)<=32:return unknown
            number=re.fullmatch(r'La regola è (raddoppiare ogni numero|aggiungere (-?\d{1,6})|sottrarre (-?\d{1,6})|moltiplicare per (-?\d{1,6}))\.',rule,re.I)
            alternate=re.fullmatch(r"La regola alterna ([a-zà-ÿ]+) e ([a-zà-ÿ]+)\.",rule,re.I)
            if number:
                if any(not re.fullmatch(r'-?\d{1,12}',v) for v in values):return unknown
                ns=list(map(int,values))
                if number[1].casefold().startswith('raddoppiare'):a,b=2,0
                elif number[2] is not None:a,b=1,int(number[2])
                elif number[3] is not None:a,b=1,-int(number[3])
                else:a,b=int(number[4]),0
                if any(y!=a*x+b for x,y in zip(ns,ns[1:])):return unknown
                result=a*ns[-1]+b
                if abs(result)>10**12:return unknown
                value=str(result)
            elif alternate:
                a,b=map(normalizza,alternate.groups());vs=list(map(normalizza,values))
                if a==b or any(v not in (a,b) for v in vs) or any(x==y for x,y in zip(vs,vs[1:])):return unknown
                value=b if vs[-1]==a else a
            else:return unknown
            return dict(status='VERIFICATA',value=value,answer='Applicando la regola dichiarata, il prossimo elemento è '+value+'.',sources=records,rule='G16_SEQUENZA_CON_REGOLA_ESPLICITA')
        if len(records)!=1:return unknown
        text=spazi(records[0]['testo'])
        # Literal parallel clauses only; do not invent an explanation or infer
        # comparative strength, causality or category equivalence.
        if re.search(r"[?!;«»\"]|\b(?:se|forse|secondo|potrebbe|sarebbe|che|lui|lei|oggi|ieri|domani)\b",text,re.I) or QUANTIFIERS.search(text):return unknown
        m=re.fullmatch(r'([^,.;]+), mentre ([^,.;]+)\.',text,re.I)
        if not m:return unknown
        clauses=m.groups();subjects=[]
        for clause in clauses:
            c=re.fullmatch(r"(.+?) (non )?(è|era|conduce|contiene|assorbe|riflette|produce|richiede|riduce|aumenta|trasporta) ([a-zà-ÿ][a-zà-ÿ' -]{0,100})",clause,re.I)
            if not c or re.search(r'\b(?:e|o|ma|mentre)\b',c[4],re.I):return unknown
            subjects.append(identita(c[1]))
        if subjects!=[identita(x) for x in args]:return unknown
        value='; '.join(normalizza(c) for c in clauses)
        return dict(status='VERIFICATA',value=value,answer='Il testo contrappone queste due affermazioni: «'+clauses[0]+'»; «'+clauses[1]+'».',sources=records,rule='G17_CONTRASTO_TESTUALE_ESPLICITO')

    @staticmethod
    def _linguistic_shape(question):
        text=spazi(question).rstrip(' ?.');term=r"[a-zà-ÿ][a-zà-ÿ' -]{0,100}?"
        m=re.fullmatch(r'('+term+r') può ([a-zà-ÿ]+) secondo la regola',text,re.I)
        if m:return 'necessary',m.groups()
        m=re.fullmatch(r'La regola consente a ('+term+r') di ([a-zà-ÿ]+)',text,re.I)
        if m:return 'necessary',m.groups()
        m=re.fullmatch(r'Quale effetto ha ('+term+r') (?:sul|sullo|sulla|sui|sugli|sulle|su) ('+term+r')',text,re.I)
        if m:return 'effect',m.groups()
        m=re.fullmatch(r'(?:Spiega come|Come) ('+term+r') influisce (?:sul|sullo|sulla|sui|sugli|sulle|su) ('+term+r')',text,re.I)
        if m:return 'effect',m.groups()
        m=re.fullmatch(r'Il testo (?:afferma|dice) che ('+term+r')',text,re.I)
        if m:return 'assertion',(m[1],)
        m=re.fullmatch(r"A chi si riferisce (quest'ultimo|quest'ultima|il primo|la prima|lui|lei) nel testo",text,re.I)
        if m:return 'reference',(normalizza(m[1]),)
        m=re.fullmatch(r'Chi ([a-zà-ÿ]+) ('+term+r')',text,re.I)
        if m:return 'reference_event',m.groups()
        return None

    @staticmethod
    def _linguistic_proposal(shape,records):
        """Bounded text comprehension. Whole context is part of every proof.

        Necessary conditions do not establish sufficiency. Modal clauses never
        become asserted events. Coreference uses explicit ordering, not names'
        presumed gender. No fact is imported from another source or memory.
        """
        unknown=dict(status='EVIDENZA_INSUFFICIENTE',reason='CONTESTO_LINGUISTICO_NON_RISOLTO')
        if not records or len(records)>8 or len({r['SOURCE_REF'] for r in records})!=1:return unknown
        texts=[spazi(r['testo']) for r in records];kind,args=shape
        word=r"[a-zà-ÿ]+";term=r"[a-zà-ÿ][a-zà-ÿ' -]{0,100}?"
        # These tokens introduce unresolved scope even when they occur inside
        # a noun phrase. Never silently drop an exception, report or qualifier.
        blocked=re.compile(r'\b(?:forse|probabilmente|secondo|dice|afferma|nega|falso|falsa|smentisce|salvo|tranne|eccetto|eccezioni|ieri|oggi|domani|prima|dopo|sempre|mai|quasi|circa|quando|mentre|benché|sebbene|oppure)\b',re.I)
        scope_texts=texts
        if kind in {'reference','reference_event'}:
            scope_texts=[re.sub(r' il giorno dopo\.$', '.', re.sub(r'^La prima ', 'Referente ', t,flags=re.I),flags=re.I) for t in texts]
        if any(blocked.search(t) or re.search(r'[?!;:"«»\d]',t) for t in scope_texts):return unknown
        def clean(phrase):
            return not (blocked.search(phrase) or re.search(r'\b(?:non|e|o|ma|se|che|cui|lui|lei|tutti|alcuni|nessuno|solo|soltanto|potrebbe|dovrebbe|sarebbe)\b',phrase,re.I))
        def verified(value,answer,rule):
            return dict(status='VERIFICATA',value=value,answer=answer,sources=records,rule=rule)
        if kind=='necessary':
            person,action=args
            if not clean(person) or not clean(action) or len(texts)!=2:return unknown
            rule=re.fullmatch(r'Solo (?:i|gli|le) ('+word+r') con ('+term+r') possono ('+word+r')\.',texts[0],re.I)
            if not rule or not all(clean(x) for x in rule.groups()) or normalizza(action)!=normalizza(rule[3]):return unknown
            fact=re.fullmatch(re.escape(person)+r' non ha ('+term+r')\.',texts[1],re.I)
            if not fact or normalizza(fact[1])!=normalizza(rule[2]):return unknown
            return verified('no','No, secondo la regola: '+person+' non ha '+fact[1]+', che è un requisito necessario per '+action+'.','G18_REQUISITO_NECESSARIO_NEGATO')
        if kind=='effect':
            subject,target=args
            if not clean(subject) or not clean(target):return unknown
            effects=[]
            for t in texts:
                m=re.fullmatch(r'('+term+r') (non )?(limita|riduce|aumenta|diminuisce|favorisce|ostacola|impedisce|accelera|rallenta|trattiene) ('+term+r')\.',t,re.I)
                if not m or not clean(m[1]) or not clean(m[4]):return unknown
                if identita(m[1])!=identita(subject):continue
                obj=identita(m[4]);wanted=identita(target)
                # Match the complete noun head. Retain the original PP, rather
                # than presenting a scoped effect as an unqualified statement.
                if obj!=wanted and not re.fullmatch(re.escape(wanted)+r' (?:a|al|alla|alle|ai|in|nel|nella|nei|nelle|del|della|dei|delle) '+term,obj,re.I):return unknown
                clause=(m[2] or '')+m[3]+' '+m[4]
                effects.append(normalizza(clause))
            if not effects:return unknown
            if len(set(effects))!=1:return dict(status='CONFLITTO',reason='EFFETTI_O_POLARITA_DIVERGENTI')
            return verified(effects[0],'La fonte descrive questo effetto: '+subject+' '+effects[0]+'.','G19_EFFETTO_LETTERALE_CON_AMBITO')
        if kind=='assertion':
            target=normalizza(args[0]);q=re.fullmatch(r'('+word+r') ('+term+r')',target)
            if not q or not clean(q[2]):return unknown
            def indicative(verb):
                irregular={'saremmo':'siamo','avremmo':'abbiamo','andremmo':'andiamo','faremmo':'facciamo','diremmo':'diciamo','berremmo':'beviamo'}
                if verb in irregular:return irregular[verb]
                m=re.fullmatch(r'([a-zà-ÿ]{2,})(?:eremmo|iremmo)',verb)
                return m[1]+('amo' if m[1].endswith('i') else 'iamo') if m else None
            positive=False;negative=False;hypothetical=False;conditions=set()
            # Only the explicit antecedent may supply accompanying copular
            # context. An unrelated or metalinguistic clause cannot disappear.
            for text in texts:
                antecedent=re.fullmatch(r'se ('+term+r') (?:fosse|avesse) ('+term+r'), .+\.',normalizza(text))
                if antecedent and all(clean(x) for x in antecedent.groups()):conditions.add(identita(antecedent[1]))
            for t in texts:
                text=normalizza(t).rstrip('.')
                if text==target:positive=True;continue
                if text=='non '+target:negative=True;continue
                cond=re.fullmatch(r'se ('+term+r') (?:fosse|avesse) ('+term+r'), (non )?('+word+r') ('+term+r')',text)
                if cond and all(clean(cond[i]) for i in (1,2,5)) and indicative(cond[4])==q[1] and normalizza(cond[5])==q[2]:
                    hypothetical=True;continue
                # An explicit copular condition state can accompany a modal
                # clause; it is not used as modus ponens or as its converse.
                state=re.fullmatch(r'('+term+r') (?:è|ha) ('+term+r')',text)
                if state and identita(state[1]) in conditions and all(clean(x) for x in state.groups()):continue
                return unknown
            if positive and negative:return dict(status='CONFLITTO',reason='ASSERZIONE_E_NEGAZIONE_PRESENTI')
            if positive:return verified('sì','Sì. Il testo afferma esplicitamente: «'+args[0]+'».','G20_ASSERZIONE_DISTINTA_DA_IPOTESI')
            if not hypothetical and not negative:return unknown
            answer='No. Il testo presenta «'+args[0]+'» soltanto come possibilità condizionata, non come fatto avvenuto.' if hypothetical and not negative else 'No. Il testo nega esplicitamente: «'+args[0]+'».'
            return verified('no',answer,'G20_ASSERZIONE_DISTINTA_DA_IPOTESI')
        if kind in {'reference','reference_event'}:
            if len(texts) not in (2,4):return unknown
            name=r'[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{0,40}'
            genders={}
            for declaration in texts[:-2]:
                m=re.fullmatch(r'('+name+r') è (un uomo|una donna)\.',declaration,re.I)
                if not m or identita(m[1]) in genders:return unknown
                genders[identita(m[1])]='m' if m[2].casefold()=='un uomo' else 'f'
            event=re.fullmatch(r'('+name+r') (?:consegna|presta|invia|dà|mostra) ((?:il|lo|la|un|una) '+word+r') a ('+name+r')\.',texts[-2],re.I)
            continuation=re.fullmatch(r"(quest'ultimo|quest'ultima|il primo|la prima|lui|lei) (lo|la) ("+word+r')( il giorno dopo)?\.',texts[-1],re.I)
            if not event or not continuation or not clean(continuation[3]):return unknown
            a,b=event[1],event[3]
            if identita(a)==identita(b):return unknown
            if genders and set(genders)!={identita(a),identita(b)}:return unknown
            pronoun=normalizza(continuation[1])
            if kind=='reference' and args[0]!=pronoun:return unknown
            if kind=='reference_event' and (normalizza(args[0])!=normalizza(continuation[3]) or identita(args[1])!=identita(event[2])):return unknown
            if pronoun in {'lui','lei'}:
                gender='m' if pronoun=='lui' else 'f'
                matches=[x for x in (a,b) if genders.get(identita(x))==gender]
                if len(matches)!=1:return unknown
                chosen=matches[0]
            else:
                chosen=b if pronoun.startswith("quest'") else a
                gender='f' if pronoun in {"quest'ultima",'la prima'} else 'm'
                if genders and genders[identita(chosen)]!=gender:return unknown
            value=identita(chosen)
            answer='Nel testo «'+pronoun+'» si riferisce a '+chosen+'.'
            if kind=='reference_event':
                feminine=event[2].casefold().startswith(('la ','una '))
                if continuation[2].casefold()!=('la' if feminine else 'lo'):return unknown
                answer=chosen+' '+continuation[3]+' '+args[1]+(continuation[4] or '')+'.'
            return verified(value,answer,'G21_RIFERIMENTO_ESPLICITO_O_GENERE_DICHIARATO')
        return unknown


    @staticmethod
    def _dependency_question(text):
        if not re.match(r"^(?:chi|che cosa|cosa|dove|quando|qual|quale|quali|a chi|da chi|in quale|in che)\b",text.strip(),re.I):return False
        try:
            from .dependency_reader import solver, _lock
            with _lock:return solver().question(text) is not None
        except (ImportError,OSError,ValueError):return False

    @staticmethod
    def check_dependency_proof(question, documents, proof):
        from .discourse_graph import check_answer
        return check_answer(question, documents, proof)

    def rispondi(self, domanda, docs, usa_memoria=False):
        from .study_reader import interpret, analyze
        if interpret(domanda) is not None:
            return analyze(domanda)
        previous=self._rispondi_previous(domanda,docs,usa_memoria)
        # Frozen symbolic rules already carry their own whole-context contracts.
        # A textual claim-reference must nevertheless be checked by the new graph.
        meta = re.search(r"\b(?:affermazion\w*|fras[ei]|notizi\w*|ricostruzion\w*|dichiarazion\w*|ipotesi|tesi|version[ei]|conclusion\w*|asserzion\w*|scherzo|inattendibil\w*|infondata|inventata|smentit\w*)\b",
                         ' '.join(d['testo'] for d in docs), re.I)
        if previous['STATO'] in {'VERIFICATA','CONFLITTO'} and not meta:return previous
        if not self._dependency_question(domanda):return previous
        unknown=dict(DOMANDA=domanda, STATO='SCONOSCIUTA', VALORE=None,
                     RISPOSTA='Il contesto non consente una risposta verificata.',
                     FONTI=[], CANDIDATI=[], MOTIVO='DISCOURSE_NOT_RESOLVED', LLM_CALLS=0)
        try:
            from .discourse_graph import propose_answer
            proof=propose_answer(domanda,docs)
            if proof['status']!='candidate':
                unknown['DISCOURSE_ANALYSIS']=proof
                return unknown
            if not self.check_dependency_proof(domanda,docs,proof):return unknown
        except (ImportError,OSError,ValueError) as exc:
            unknown['DISCOURSE_ANALYSIS']={'status':'unavailable','reason':type(exc).__name__}
            return unknown
        sources=[]
        for p in proof['proofs']:
            sources.append(dict(SOURCE_REF=p['source'],TEXT_SPAN=p['sentence_span'],testo=p['sentence'],source_sha256=p['source_sha256'],EVIDENCE_REF='EV-'+impronta([p['source'],p['sentence_span'],p['source_sha256']])[:20]))
        # Include the source context that governs a retracted/confirmed assertion.
        for node in proof['graph']['nodes']:
            if node['kind']=='CLAIM_REFERENCE':
                sources.append(dict(SOURCE_REF=node['source'],TEXT_SPAN=node['span'],testo=node['text'],source_sha256=node['source_sha256'],EVIDENCE_REF=node['id']))
        value=proof['proofs'][0]['value']
        return dict(DOMANDA=domanda,STATO='VERIFICATA',VALORE=normalizza(value),
            RISPOSTA='La fonte indica: '+value+'.\nContesto: «'+sources[0]['testo']+'».',
            FONTI=sources,CANDIDATI=[],PROVA=proof,PROPOSIZIONE_DOMANDA=self.domanda(domanda),
            RIFLESSIONE=[dict(VERIFICATA=True,CONFLITTI=[],CONTROLLI=[dict(CONTROLLO=k,PASS=True) for k in ['RUOLI_PREDICATO_E_TEMPO','CONTESTO_COMPLETO_RICONTROLLATO','RISPOSTA_ESTRATTA_DALLA_FONTE','IMPRONTA_E_SPAN']])],
            MOTIVO='GRAFO_DISCORSIVO_LIMITATO_E_FONTE_CONTROLLATA',LLM_CALLS=0,
            NON_LLM_STATISTICAL_PARSER=True)
