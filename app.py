import os
import json
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from bs4 import BeautifulSoup
import PyPDF2
import google.generativeai as genai

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
# 2. AUTENTICAÇÃO E BARRA LATERAL (SECRETS + FALLBACK)
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Configurações do Sistema")

# Tenta carregar a API Key via Streamlit Secrets; se não existir, exibe o input na sidebar
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API Key carregada com sucesso via Secrets!")
else:
    api_key = st.sidebar.text_input("Insira sua Google Gemini API Key:", type="password")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Parâmetros de Varredura")
base_url = "https://www.valinhos.sp.gov.br/portal/diario-oficial/ver/"

kw_search = st.sidebar.text_input("Palavra-chave para busca no portal:", value="contrato")
max_editions = st.sidebar.slider("Quantidade máxima de PDFs para baixar/analisar:", min_value=1, max_value=10, value=2)

if not api_key:
    st.info("💡 Por favor, configure a variável `GEMINI_API_KEY` nos Secrets do Streamlit ou insira a chave na barra lateral.")
    st.stop()

# Configura a biblioteca do Gemini
genai.configure(api_key=api_key)

# -----------------------------------------------------------------------------
# 3. MÓDULO DE SCRAPING & DOWNLOAD VALIDADO
# -----------------------------------------------------------------------------
def fetch_diario_oficial_links(keyword: str, limit: int) -> list:
    """Busca os links das edições no portal oficial da Prefeitura de Valinhos."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    found_pdfs = []
    
    try:
        response = requests.get(base_url, headers=headers, timeout=15)
        if response.status_code != 200:
            st.error(f"Erro ao acessar o portal (Status Code: {response.status_code})")
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=True)
        
        for a in links:
            href = a['href']
            # Identifica links diretos de PDF ou rotas de ver/download
            if ".pdf" in href.lower() or "/download/" in href.lower() or "diario" in href.lower():
                full_url = href if href.startswith("http") else f"https://www.valinhos.sp.gov.br{href}"
                title = a.get_text(strip=True) or "Edição Diário Oficial"
                
                # Evita duplicatas na lista de execução
                if not any(item['url'] == full_url for item in found_pdfs):
                    found_pdfs.append({"titulo": title, "url": full_url})
                
                if len(found_pdfs) >= limit:
                    break
                    
    except Exception as e:
        st.error(f"Falha na conexão com o portal: {e}")
        
    return found_pdfs

def download_and_validate_pdf(url: str, output_path: str) -> bool:
    """Faz o download e valida se o arquivo baixado é um PDF válido (checa o header %PDF)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.valinhos.sp.gov.br/"
    }
    try:
        response = requests.get(url, headers=headers, timeout=30, stream=True)
        if response.status_code == 200:
            content = response.content
            # Verifica o cabeçalho "magic bytes" do arquivo PDF (%PDF-)
            if content.startswith(b'%PDF'):
                with open(output_path, "wb") as f:
                    f.write(content)
                return True
            else:
                st.warning(f"O link retornado não apontou para um arquivo PDF válido (retornou página HTML ou redirecionamento).")
                return False
    except Exception as e:
        st.error(f"Erro durante o download do arquivo: {e}")
    return False

def extract_text_from_pdf(file_path: str) -> str:
    """Extrai texto bruto do PDF com captura de exceções de leitura."""
    text = ""
    try:
        reader = PyPDF2.PdfReader(file_path)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        st.error(f"Erro ao ler PDF ({os.path.basename(file_path)}): {e}")
    return text

# -----------------------------------------------------------------------------
# 4. MÓDULO DE INTELIGÊNCIA ARTIFICIAL (GEMINI API)
# -----------------------------------------------------------------------------
def analyze_with_gemini(text_content: str, source_name: str) -> dict:
    """Realiza a análise dos trechos do Diário Oficial utilizando o modelo Gemini."""
    
    # Alias do modelo com alta compatibilidade para tarefas estruturadas
    model_name = "gemini-1.5-flash-latest"
    
    try:
        model = genai.GenerativeModel(model_name)
    except Exception:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")

    prompt = f"""
    Você é um auditor sênior do Tribunal de Contas do Estado de São Paulo (TCE-SP).
    Análise o texto abaixo extraído do Diário Oficial de Valinhos procurando por extratos de contratos, dispensas de licitação, aditivos e indícios de anomalias/fraudes.

    **Texto Extraído ({source_name}):**
    {text_content[:20000]}

    Retorne **ESTRITAMENTE** um objeto JSON estruturado como neste exemplo, sem marcadores ou blocos de código extras fora da estrutura JSON:
    {{
      "documento_fonte": "{source_name}",
      "empresa_principal": "Nome da empresa em destaque ou N/A",
      "cnpj": "CNPJ identificado ou N/A",
      "valor_total_identificado": 0.00,
      "score_risco": 0,
      "classificacao_risco": "Baixo | Médio | Alto | Crítico",
      "alertas_inconformidades": [
        "Descrição detalhada da inconsistência 1"
      ],
      "resumo_extratos": "Breve resumo dos atos oficiais analisados nesta edição."
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Erro na chamada do modelo Gemini para {source_name}: {e}")
        return {}

# -----------------------------------------------------------------------------
# 5. FLUXO PRINCIPAL E INTERFACE
# -----------------------------------------------------------------------------
st.subheader("1. Iniciar Varredura do Portal Oficial")
st.write(f"Endereço-alvo: `{base_url}`")

if st.button("🚀 Iniciar Scraping & Auditoria Automatizada", type="primary"):
    with st.spinner("Conectando ao portal da Prefeitura de Valinhos e buscando arquivos..."):
        items = fetch_diario_oficial_links(kw_search, max_editions)
        
    if not items:
        st.warning("Nenhum link correspondente foi localizado no portal durante a execução do scraper.")
    else:
        st.success(f"Encontrados {len(items)} links de diários/extratos para análise.")
        
        os.makedirs("downloads_diario", exist_ok=True)
        results = []
        progress_bar = st.progress(0)
        
        for idx, item in enumerate(items):
            file_name = f"diario_edicao_{idx + 1}.pdf"
            file_path = os.path.join("downloads_diario", file_name)
            
            st.text(f"Baixando e validando: {item['titulo']}...")
            is_valid_pdf = download_and_validate_pdf(item['url'], file_path)
            
            if is_valid_pdf:
                st.text(f"Extraindo texto e auditando {file_name} via Gemini...")
                extracted_text = extract_text_from_pdf(file_path)
                
                if extracted_text.strip():
                    audit_res = analyze_with_gemini(extracted_text, file_name)
                    if audit_res:
                        results.append(audit_res)
                else:
                    st.warning(f"O arquivo {file_name} não possui camada de texto editável (pode ser imagem digitalizada).")
            
            progress_bar.progress((idx + 1) / len(items))
            
        if results:
            st.markdown("---")
            st.subheader("2. Consolidação dos Resultados")
            
            df = pd.DataFrame(results)
            
            # Tabela resumida dos dados analisados
            st.dataframe(
                df[["documento_fonte", "empresa_principal", "cnpj", "valor_total_identificado", "score_risco", "classificacao_risco"]],
                use_container_width=True
            )
            
            # Visualização Gráfica
            col1, col2 = st.columns(2)
            
            with col1:
                fig_bar = px.bar(
                    df,
                    x="documento_fonte",
                    y="score_risco",
                    color="classificacao_risco",
                    title="Score de Risco por Edição Analisada",
                    labels={"score_risco": "Score (0-100)", "documento_fonte": "Documento"}
                )
                st.plotly_chart(fig_bar, use_container_width=True)
                
            with col2:
                fig_scatter = px.scatter(
                    df,
                    x="valor_total_identificado",
                    y="score_risco",
                    hover_data=["empresa_principal", "cnpj"],
                    title="Relação: Valor Identificado x Score de Risco"
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
                
            # Exibição detalhada de alertas por arquivo
            st.markdown("### 🚨 Detalhamento das Anomalias e Extratos")
            for res in results:
                with st.expander(f"📄 {res.get('documento_fonte')} — Empresa: {res.get('empresa_principal', 'N/A')} (Score: {res.get('score_risco')}/100)"):
                    st.write(f"**CNPJ:** {res.get('cnpj', 'N/A')}")
                    st.write(f"**Valor Identificado:** R$ {res.get('valor_total_identificado', 0):,.2f}")
                    st.write(f"**Resumo dos Atos:** {res.get('resumo_extratos')}")
                    st.markdown("**Alertas de Inconformidades:**")
                    for alert in res.get("alertas_inconformidades", []):
                        st.write(f"- ⚠️ {alert}")
