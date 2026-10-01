"""Editorial reading prompts; only verified titles in the user's scope resolve."""
from copy import deepcopy
from .title_search import fold

CATEGORIES = [
    dict(id='storia', title='Storia e civiltà', description='Trasformazioni, popoli e luoghi che hanno cambiato il mondo.', paths=[
        dict(id='roma',title='Roma: dalla repubblica all’impero',question='Come cambiano istituzioni e società nel mondo romano?',topics=['Repubblica romana','Impero romano','Augusto']),
        dict(id='italia',title='Come nasce l’Italia unita',question='Esplora il Risorgimento, i suoi protagonisti e il nuovo Stato.',topics=['Risorgimento','Giuseppe Garibaldi',"Regno d’Italia (1861-1946)"])]),
    dict(id='arte',title='Arte e letteratura',description='Opere e idee, lette insieme al loro contesto.',paths=[
        dict(id='rinascimento',title='Il Rinascimento tra arte e conoscenza',question='Avvicina il rinnovamento culturale attraverso arte, scienza e umanesimo.',topics=['Rinascimento','Leonardo da Vinci','Umanesimo']),
        dict(id='dante',title='Dante e il suo mondo',question='Leggi la Commedia nel contesto della vita dell’autore e del Medioevo.',topics=['Dante Alighieri','Divina Commedia','Medioevo'])]),
    dict(id='scienza',title='Scienza e tecnologia',description='Scoperte, metodi e strumenti per conoscere.',paths=[
        dict(id='metodo',title='Come nasce la scienza moderna',question='Esplora osservazione, esperimento e rivoluzione astronomica.',topics=['Galileo Galilei','Metodo scientifico','Rivoluzione scientifica']),
        dict(id='energia',title='Energia: dalla macchina a vapore all’elettricità',question='Segui le invenzioni e i cambiamenti della società industriale.',topics=['Rivoluzione industriale','Motore a vapore','Elettricità'])]),
    dict(id='natura',title='Natura e ambiente',description='La vita, il pianeta e le loro trasformazioni.',paths=[
        dict(id='evoluzione',title='Come cambia la vita sulla Terra',question='Metti in relazione evoluzione, selezione naturale e biodiversità.',topics=['Evoluzione','Charles Darwin','Biodiversità']),
        dict(id='clima',title='Capire il clima e i suoi cambiamenti',question='Distingui i meccanismi dell’atmosfera e le trasformazioni climatiche.',topics=['Clima','Effetto serra','Cambiamento climatico'])]),
    dict(id='pensiero',title='Filosofia e religioni',description='Testi, domande e tradizioni del pensiero.',paths=[
        dict(id='cristianesimo',title='Gesù, la Bibbia e le origini cristiane',question='Leggi insieme testi, figura storica e sviluppo della tradizione.',topics=['Gesù','Bibbia','Cristianesimo']),
        dict(id='grecia',title='Le domande della filosofia greca',question='Esplora conoscenza, etica e politica attraverso tre filosofi.',topics=['Socrate','Platone','Aristotele'])]),
    dict(id='societa',title='Società e istituzioni',description='Diritti, convivenza e organizzazione della vita comune.',paths=[
        dict(id='democrazia',title='Come funziona una democrazia',question='Confronta partecipazione politica, costituzioni e diritti.',topics=['Democrazia','Costituzione','Diritti umani']),
        dict(id='europa',title='L’Europa come progetto comune',question='Esplora istituzioni, cittadinanza e cooperazione europea.',topics=['Unione europea','Parlamento europeo',"Cittadinanza dell’Unione europea"])])]


def catalog():
    return deepcopy(CATEGORIES)


def resolve(service, path_id, mode='UNIFIED', ids=None):
    path=next((p for c in CATEGORIES for p in c['paths'] if p['id']==path_id),None)
    if path is None:raise ValueError('Percorso non disponibile.')
    rows=[];missing=[];limited=False
    for title in path['topics']:
        result=service.search(title,mode=mode,ids=ids,limit=50)
        matches=[r for r in result['rows'] if fold(r['title'])==fold(title)]
        if not matches:missing.append(title)
        rows.extend(matches)
        limited=limited or bool(result.get('next'))
    # Explicitly choose editions in the UI; never silently substitute near matches.
    return dict(path=deepcopy(path),rows=rows,missing=missing,limited=limited,
                method='Proposta di lettura: le voci sono cercate per titolo nelle sole librerie selezionate. Scegli i testi da riunire; i collegamenti dipendono dai passaggi disponibili.')
