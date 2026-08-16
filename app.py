import os
import json
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from bs4 import BeautifulSoup
import PyPDF2
import urllib3

# SDK Atualizado do Google GenAI
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AuditAI - Varredura Diário Oficial de Valinhos",
    page_icon="🔎",
    layout="wide"
)

st.title("🔎 AuditAI - Varredura do Diário Oficial de Valinhos")
st.caption("Automação de Web Scraping + Análise Preditiva de Riscos via Google Gemini API")

# -----------------------------------------------------------------------------
# 2. AUTENTICAÇÃO E TRATAMENTO DA API KEY
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Configurações do Sistema")

api_key = ""

if "GEMINI_API_KEY" in st.secrets:
    api_key = str(st.secrets["GEMINI_API_KEY"]).strip().strip('"').strip("'")

if not api_key or len(api_key) < 20:
    api_key = st.sidebar.text_input("Insira sua Google Gemini API Key:", type="password").strip()
else:
    st.sidebar.success("🔑 API Key carregada dos Secrets!")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Parâmetros de Varredura")
base_url = "https://www.valinhos.sp.gov.br/portal/diario-oficial/ver/"

kw_search = st.sidebar.text_input("Palavra-chave para busca no portal:", value="contrato")
max_editions = st.sidebar.slider("Quantidade máxima de PDFs para baixar/analisar:", min_value=1, max_value=10, value=2)

if not api_key:
    st.info("💡 Por favor, verifique sua API Key e configure nos Secrets do Streamlit Cloud ou na barra lateral.")
    st.stop()

# Instancia o cliente do SDK oficial atualizado
client = genai.Client(api_key=api_key)

# -----------------------------------------------------------------------------
# 3. SCRAPING MELHORADO PARA LINKS DIRETOS DE PDF
# -----------------------------------------------------------------------------
def fetch_diario_oficial_links(keyword: str, limit: int) -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    found_pdfs = []
    
    try:
        response = requests.get(base_url, headers=headers, timeout=15, verify=False)
        if response.status_code != 200:
            st.error(f"Erro ao acessar portal ({response.status_code})")
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=True)
        
        for a in links:
            href = a['href']
            # Filtra links que de fato levam ao arquivo de download
            if "download" in href.lower() or ".pdf" in href.lower() or "/ver/" in href.lower():
                full_url = href if href.startswith("http") else f"https://www.valinhos.sp.gov.br{href}"
                title = a.get_text(strip=True) or "Edição Diário Oficial"
                
                # Trata URLs que abrem a página interna para tentar converter no endpoint direto de download
                if "/ver/" in full_url and "download" not in full_url:
                    full_url = full_url.replace("/ver/", "/download/")

                if not any(item['url'] == full_url for item in found_pdfs):
                    found_pdfs.append({"titulo": title, "url": full_url})
                
                if len(found_pdfs) >= limit:
                    break
                    
    except Exception as e:
        st.error(f"Erro na conexão de busca: {e}")
        
    return found_pdfs

def download_and_validate_pdf(url: str, output_path: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=30, verify=False, allow_redirects=True)
        if response.status_code == 200:
            content = response.content
            if content.startswith(b'%PDF'):
                with open(output_path, "wb") as f:
                    f.write(content)
                return True
            else:
                st.warning("O link do portal redirecionou para uma página HTML em vez de entregar o PDF bruto.")
                return False
    except Exception as e:
        st.error(f"Erro no download: {e}")
    return False

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        reader = PyPDF2.PdfReader(file_path)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        st.error(f"Erro ao extrair texto do PDF: {e}")
    return text

# -----------------------------------------------------------------------------
# 4. ANALISADOR INTELIGENTE (GOOGLE GENAI SDK - GEMINI 2.5 FLASH)
# -----------------------------------------------------------------------------
def analyze_with_gemini(text_content: str, source_name: str) -> dict:
    prompt = f"""
    Você é um auditor sênior do Tribunal de Contas do Estado de São Paulo (TCE-SP).
    Analise o texto abaixo do Diário Oficial de Valinhos procurando por extratos de contratos, dispensas de licitação e aditivos.

    Texto:
    {text_content[:20000]}

    Retorne APENAS um JSON estrito com esta estrutura exata:
    {{
      "documento_fonte": "{source_name}",
      "empresa_principal": "Nome da empresa ou N/A",
      "cnpj": "CNPJ ou N/A",
      "valor_total_identificado": 0.00,
      "score_risco": 0,
      "classificacao_risco": "Baixo | Médio | Alto | Crítico",
      "alertas_inconformidades": ["Descrição do alerta"],
      "resumo_extratos": "Resumo dos atos oficiais"
    }}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Erro na chamada do Gemini ({source_name}): {e}")
        return {}

# -----------------------------------------------------------------------------
# 5. EXECUÇÃO DA INTERFACE
# -----------------------------------------------------------------------------
st.subheader("1. Iniciar Varredura do Portal Oficial")

if st.button("🚀 Iniciar Scraping & Auditoria Automatizada", type="primary"):
    with st.spinner("Buscando publicações no Diário Oficial..."):
        items = fetch_diario_oficial_links(kw_search, max_editions)
        
    if not items:
        st.warning("Nenhum link localizado no momento.")
    else:
        st.success(f"Encontrados {len(items)} links de diários/extratos.")
        
        os.makedirs("downloads_diario", exist_ok=True)
        results = []
        progress_bar = st.progress(0)
        
        for idx, item in enumerate(items):
            file_name = f"diario_edicao_{idx + 1}.pdf"
            file_path = os.path.join("downloads_diario", file_name)
            
            st.text(f"Baixando: {item['titulo']}...")
            is_valid_pdf = download_and_validate_pdf(item['url'], file_path)
            
            if is_valid_pdf:
                st.text(f"Extraindo texto e auditando {file_name} via Gemini...")
                extracted_text = extract_text_from_pdf(file_path)
                
                if extracted_text.strip():
                    audit_res = analyze_with_gemini(extracted_text, file_name)
                    if audit_res:
                        results.append(audit_res)
                else:
                    st.warning(f"O arquivo {file_name} não possui texto extraível.")
            
            progress_bar.progress((idx + 1) / len(items))
            
        if results:
            st.markdown("---")
            st.subheader("2. Consolidação dos Resultados")
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            
            fig = px.bar(df, x="documento_fonte", y="score_risco", color="classificacao_risco", title="Score de Risco")
            st.plotly_chart(fig, use_container_width=True)
