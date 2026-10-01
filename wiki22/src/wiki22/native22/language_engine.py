"""LANG001-EXP001: small Italian-first, evidence-bound symbolic learner.
Only standard-library code; no external model, word vectors or NLP package.
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

    def serializza(self) -> dict:
        keys = ['seme','grammatica','regole','lessico','entita','relazioni','proposizioni','evidenze','fonti','sinonimi','sensi','domande_umane','risposte_umane','traccia_apprendimento','bloccato','ambiguita_risolte','frasi_lette','parole_lette']
        return {'schema':'ai22.lang001.memoria.v1', **{k:copy.deepcopy(getattr(self,k)) for k in keys}, 'visti':sorted(self._visti)}

    @classmethod
    def da_stato(cls, s: dict) -> 'Motore':
        m=cls({'voci':s['seme']},s['grammatica'],{'regole':s['regole']})
        for k,v in s.items():
            if k not in {'schema','visti'}: setattr(m,k,copy.deepcopy(v))
        m._visti=set(s['visti'])
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

    def analizza(self, testo: str, antecedenti: list[str]|None=None) -> dict:
        """Syntactic proposal only: does not promote knowledge or modify memory."""
        original=testo
        s=spazi(testo).strip('.?! ')
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
        return result

    def _osserva_parole(self, analisi: dict, ev: dict):
        hypotheses={normalizza(x['FORMA']):x for x in analisi['IPOTESI_LESSICALI']}
        for tok in analisi['TOKENS']:
            w=tok['NORMA']
            if not any(c.isalpha() for c in w): continue
            h=hypotheses.get(w,self._ipotesi(tok['FORMA'],'SCONOSCIUTA'))
            if w not in self.lessico:
                self.lessico[w]={'PAROLA_ID':'L-'+impronta(w)[:16], **h,'SIGNIFICATI_CANDIDATI':{},'CONTESTI_OSSERVATI':[],'RELAZIONI':[],'CONFIDENZA':0.0,'NUMERO_OCCORRENZE':0,'EVIDENZE':[],'STATO':'SCONOSCIUTA','ORIGINE':'APPRENDIMENTO','CATEGORIE_CANDIDATE':{},'CONTESTI_DISTINTI':[]}
            lex=self.lessico[w]; lex['NUMERO_OCCORRENZE']+=1
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
            p=a['PROPOSIZIONE']; p['PROPOSIZIONE_ID']='P-'+impronta([p,evid])[:20]; p['EVIDENCE_REF']=evid; p['SOURCE_REF']=source; p['TEXT_SPAN']=[start,end]
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
            h=p['FIRMA']['testa']
            for lex in self.lessico.values():
                if lex['LEMMA_CANDIDATO']==h and lex['ORIGINE']!='SEME':
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

    def metriche_stato(self):
        nonseme=[x for x in self.lessico.values() if x['ORIGINE']!='SEME']
        known={impronta(self.firma({'FIRMA':rel['FIRMA']})) for rel in self.relazioni.values() if rel['STATO'] in {'APPRESA','CONFERMATA'}}
        return {'PAROLE_LETTE':self.parole_lette,'FRASI_LETTE':self.frasi_lette,'FORME_LESSICALI':len(self.lessico),'PAROLE_APPRESE':sum(x['STATO'] in {'APPRESA','CONFERMATA'} for x in nonseme),'IPOTESI_LESSICALI':sum(x['STATO'] in {'IPOTESI','SCONOSCIUTA','AMBIGUA'} for x in nonseme),'SIGNIFICATI_CANDIDATI':sum(len(x['SIGNIFICATI_CANDIDATI']) for x in nonseme)+sum(len(s) for s in self.sensi.values()),'ENTITA':len(self.entita),'RELAZIONI_APPRESE':sum(x['STATO'] in {'APPRESA','CONFERMATA'} for x in self.relazioni.values()),'PROPOSIZIONI_SUPPORTATE':sum(impronta(self.firma(p)) in known for p in self.proposizioni),'DOMANDE_GENERATE':len(self.domande_umane),'AMBIGUITA_RISOLTE_AUTONOMAMENTE':self.ambiguita_risolte}

    def disambigua(self, parola: str, contesto: str) -> dict:
        senses=self.sensi.get(normalizza(parola),{})
        if not senses: return {'STATO':'SCONOSCIUTA','SENSO':None,'EVIDENZE':[]}
        scores={s:len(set(x['indizi']) & set(normalizza(contesto).split())) for s,x in senses.items()}
        ordered=sorted(scores,key=lambda s:(-scores[s],s))
        if len(ordered)==1 or (scores[ordered[0]]>0 and scores[ordered[0]]>scores[ordered[1]]):
            s=ordered[0]; return {'STATO':'RISOLTA','SENSO':s,'EVIDENZE':senses[s]['EVIDENZE'],'INDIZI':senses[s]['indizi']}
        return {'STATO':'AMBIGUA','SENSO':None,'EVIDENZE':sorted({e for x in senses.values() for e in x['EVIDENZE']}),'DOMANDA':f"Nel testo, «{parola}» è usata nel senso di "+' oppure '.join('«'+s+'»' for s in ordered)+'?'}

    def domanda(self, testo: str) -> dict|None:
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
                p=a['PROPOSIZIONE']
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
                            'GRAMMATICA','RUOLI_LOGICI','QUALIFICATORI']
                ok = ok and pp is not None and bool(bound)
                if ok:
                    ok = all(f.get('SOURCE_REF')==ev['SOURCE_REF'] and f.get('TEXT_SPAN')==ev['TEXT_SPAN']
                             and all(pp.get(k)==f.get(k) for k in semantic) for f in bound)
            check('FONTE_E_SPAN:'+ref,ok)
        conflicts=[x['PROPOSIZIONE_ID'] for x in facts if self.firma(x)==self.firma(candidato) and x['SOGGETTO']==candidato['SOGGETTO'] and x['OGGETTO']==candidato['OGGETTO'] and x['TEMPO']==candidato['TEMPO'] and self.tempo_compatibile(candidato,x) and x['NEGAZIONE']!=candidato['NEGAZIONE']]
        check('ASSENZA_CONTRADDIZIONE',not conflicts)
        return {'VERIFICATA':all(x['PASS'] for x in checks),'CONTROLLI':checks,'CONFLITTI':conflicts}

    def rispondi(self, domanda: str, docs: list[dict], usa_memoria=False) -> dict:
        q=self.domanda(domanda)
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
