import streamlit as st
import requests
from openai import OpenAI
from datetime import datetime, time
import time as time_module
import concurrent.futures

st.set_page_config(page_title="Mon Analyste Sportif IA", page_icon="⚽", layout="wide")

# --- CONFIGURATION DES CLÉS API (Sécurisée) ---
# 1. On essaie de récupérer les clés depuis les Secrets Streamlit Cloud
try:
    API_FOOTBALL_KEY = st.secrets["API_FOOTBALL_KEY"]
    OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
# 2. Si on est sur notre PC (pas de secrets), on utilise les clés ci-dessous
except Exception:
    API_FOOTBALL_KEY = "daae1d4c341ac3640f47a6c400bdc7c4"
    OPENROUTER_API_KEY = "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"

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
headers_football = {"x-apisports-key": API_FOOTBALL_KEY}
BASE_URL = "https://v3.football.api-sports.io/"

st.title("⚽ Mon Analyste Sportif IA (Filtres Avancés)")

# --- 1. CHOIX DE LA DATE ET RECUPERATION DES MATCHS ---
date_choisie = st.text_input("Date (vide = aujourd'hui)", "")

if "fixtures_du_jour" not in st.session_state:
    st.session_state.fixtures_du_jour = None

@st.cache_data(ttl=3600, show_spinner=False)
def get_fixtures_du_jour(date_str):
    url = f"{BASE_URL}fixtures?date={date_str}&timezone=Africa/Abidjan"
    res = requests.get(url, headers=headers_football).json()
    return res

# Bouton pour charger les matchs (1 seule requête API)
if st.button("Charger les matchs disponibles"):
    if not date_choisie:
        date_choisie = datetime.today().strftime('%Y-%m-%d')
    
    with st.spinner("Récupération des matchs..."):
        res = get_fixtures_du_jour(date_choisie)
        if res.get("errors"):
            st.error(f"Erreur API : {res['errors']}")
        elif res.get("results", 0) == 0:
            st.warning("Aucun match pour cette date.")
        else:
            st.session_state.fixtures_du_jour = res["response"]
            st.success(f"{len(res['response'])} matchs trouvés. Utilisez les filtres ci-dessous.")

# --- 2. AFFICHAGE DES FILTRES (si les matchs sont chargés) ---
if st.session_state.fixtures_du_jour:
    
    tous_les_pays = sorted(list(set(m['league']['country'] for m in st.session_state.fixtures_du_jour)))
    toutes_les_ligues = sorted(list(set(m['league']['name'] for m in st.session_state.fixtures_du_jour)))
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        choix_pays = st.selectbox("Pays", ["Tous"] + tous_les_pays)
    with col2:
        choix_ligue = st.selectbox("Championnat", ["Tous"] + toutes_les_ligues)
    with col3:
        heure_debut = st.time_input("Heure début", value=time(0, 0))
    with col4:
        heure_fin = st.time_input("Heure fin", value=time(23, 59))
    with col5:
        nb_matchs = st.number_input("Max matchs", min_value=1, value=5, step=1)
        
    st.subheader("Consignes pour l'IA")
    criteres = st.text_area(
        "Explique à l'IA ce qu'elle doit chercher :",
        "Tu es un analyste sportif. Analyse UNIQUEMENT le match fourni. "
        "Compare les 5 derniers matchs de chaque équipe. "
        "Donne un pronostic clair (1, N ou 2) et justifie-le en 3 phrases maximum avec les stats fournies."
    )
    
    if st.button("Lancer l'analyse 🚀", type="primary"):
        
        matchs_filtres = []
        for m in st.session_state.fixtures_du_jour:
            if choix_pays != "Tous" and m['league']['country'] != choix_pays:
                continue
            if choix_ligue != "Tous" and m['league']['name'] != choix_ligue:
                continue
            
            dt = datetime.fromisoformat(m['fixture']['date'])
            heure_match = dt.time()
            if not (heure_debut <= heure_match <= heure_fin):
                continue
                
            matchs_filtres.append(m)
            
        if len(matchs_filtres) == 0:
            st.warning("Aucun match ne correspond à ces critères. Modifiez les filtres.")
            st.stop()
            
        nb_a_analyser = min(nb_matchs, len(matchs_filtres))
        matchs_a_analyser = matchs_filtres[:nb_a_analyser]
        
        st.success(f"{len(matchs_filtres)} matchs correspondent. Analyse des {nb_a_analyser} premiers.")
        
        @st.cache_data(ttl=3600, show_spinner=False)
        def get_derniers_matchs(team_id, limit=5):
            url = f"{BASE_URL}fixtures?team={team_id}&last={limit}"
            res = requests.get(url, headers=headers_football).json()
            resultats = []
            if res.get("results", 0) > 0:
                for event in res["response"]:
                    if event['goals']['home'] is not None:
                        h, a = event['teams']['home']['name'], event['teams']['away']['name']
                        hg, ag = event['goals']['home'], event['goals']['away']
                        resultats.append(f"{h} {hg} - {ag} {a}")
            return resultats

        def preparer_donnees_match(match):
            return {
                "comp": match['league']['name'],
                "pays": match['league']['country'],
                "equipe_dom": match['teams']['home']['name'],
                "equipe_ext": match['teams']['away']['name'],
                "heure_match": match['fixture']['date'],
                "hist_dom": get_derniers_matchs(match['teams']['home']['id']),
                "hist_ext": get_derniers_matchs(match['teams']['away']['id'])
            }

        donnees_matchs = []
        with st.spinner("Téléchargement des historiques..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(preparer_donnees_match, m) for m in matchs_a_analyser]
                for future in concurrent.futures.as_completed(futures):
                    donnees_matchs.append(future.result())
        
        donnees_matchs = sorted(donnees_matchs, key=lambda x: x['heure_match'])
        
        for index, data in enumerate(donnees_matchs):
            heure = datetime.fromisoformat(data['heure_match']).strftime('%H:%M')
            st.info(f"Match {index+1}/{nb_a_analyser} : **{data['equipe_dom']} vs {data['equipe_ext']}** ({data['pays']} - {data['comp']}) - ⏰ {heure}")
            
            if not data['hist_dom'] or not data['hist_ext']:
                st.warning("Historique insuffisant pour ces équipes.")
                continue
            
            contexte = f"""
            Match : {data['equipe_dom']} (Domicile) vs {data['equipe_ext']} (Extérieur) en {data['comp']} ({data['pays']}).
            
            5 derniers matchs de {data['equipe_dom']} :
            {chr(10).join(data['hist_dom'])}
            
            5 derniers matchs de {data['equipe_ext']} :
            {chr(10).join(data['hist_ext'])}
            """
            
            try:
                with st.spinner("L'IA réfléchit..."):
                    response = client.chat.completions.create(
                        model="openrouter/free", 
                        messages=[{"role": "system", "content": criteres}, {"role": "user", "content": contexte}]
                    )
                
                st.markdown("### 🤖 Analyse de l'IA :")
                st.markdown(response.choices[0].message.content)
                st.divider() 
                
            except Exception as e:
                if "429" in str(e):
                    st.error("🛑 Limite OpenRouter atteinte.")
                    st.stop()
                else:
                    st.error(f"Erreur IA : {e}")
            
            time_module.sleep(3)
