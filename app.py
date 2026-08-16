import os
import re
import json
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from bs4 import BeautifulSoup
import PyPDF2
import google.generativeai as genai

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA PÁGINA E ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AuditAI - Varredura Diário Oficial de Valinhos",
    page_icon="🔎",
    layout="wide"
)

st.title("🔎 AuditAI - Varredura do Diário Oficial de Valinhos")
st.caption("Automação de Web Scraping + Análise Preditiva de Riscos de Contratos via Google Gemini API")

# -----------------------------------------------------------------------------
# 2. BARRA LATERAL - CONFIGURAÇÕES E PARÂMETROS DE BUSCA
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Configurações do Sistema")
api_key = st.sidebar.text_input("Insira sua Google Gemini API Key:", type="password")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Parâmetros de Varredura")
base_url = "https://www.valinhos.sp.gov.br/portal/diario-oficial/ver/"

kw_search = st.sidebar.text_input("Palavra-chave para busca no portal:", value="contrato")
max_editions = st.sidebar.slider("Quantidade máxima de PDFs para baixar/analisar:", min_value=1, max_value=10, value=3)

if not api_key:
    st.info("💡 Por favor, insira sua API Key do Google Gemini na barra lateral para prosseguir.")
    st.stop()

genai.configure(api_key=api_key)

# -----------------------------------------------------------------------------
# 3. MÓDULO DE WEB SCRAPING DO DIÁRIO OFICIAL
# -----------------------------------------------------------------------------
def fetch_diario_oficial_links(keyword: str, limit: int) -> list:
    """
    Realiza a varredura na página oficial do Diário Oficial de Valinhos
    retornando os dados e links para download dos PDFs.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    found_pdfs = []
    
    try:
        # Acessa a página principal do Diário Oficial
        response = requests.get(base_url, headers=headers, timeout=15)
        if response.status_code != 200:
            st.error(f"Erro ao acessar o portal (Status Code: {response.status_code})")
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Procura os elementos que contenham links para leitura ou download do PDF
        links = soup.find_all("a", href=True)
        
        for a in links:
            href = a['href']
            # Filtra links associados a download ou visualização de arquivos PDF
            if "pdf" in href.lower() or "download" in href.lower() or "diario-oficial" in href.lower():
                full_url = href if href.startswith("http") else f"https://www.valinhos.sp.gov.br{href}"
                
                # Nome/Título da edição extraído do link ou texto próximo
                title = a.get_text(strip=True) or "Edição Diário Oficial"
                
                found_pdfs.append({
                    "titulo": title,
                    "url": full_url
                })
                
                if len(found_pdfs) >= limit:
                    break
                    
    except Exception as e:
        st.error(f"Falha na conexão com o servidor da Prefeitura: {e}")
        
    return found_pdfs

def download_pdf(url: str, output_path: str) -> bool:
    """Faz o download do arquivo PDF do Diário Oficial."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
    except Exception as e:
        st.error(f"Erro no download do arquivo {url}: {e}")
    return False

def extract_text_from_pdf_file(file_path: str) -> str:
    """Extrai texto bruto de um PDF salvo em disco."""
    text = ""
    try:
        reader = PyPDF2.PdfReader(file_path)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        st.error(f"Erro ao ler PDF local {file_path}: {e}")
    return text

# -----------------------------------------------------------------------------
# 4. MÓDULO DE INTELIGÊNCIA ARTIFICIAL (GEMINI API)
# -----------------------------------------------------------------------------
def analyze_text_for_frauds(text_content: str, source_name: str) -> dict:
    """Envia o conteúdo extrato para o Gemini analisar suspeitas e contratos."""
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    Você é um auditor sênior especializado em licitações e contratos do Tribunal de Contas do Estado de São Paulo (TCE-SP).
    Analise o texto abaixo extraído do Diário Oficial da Prefeitura de Valinhos em busca de extratos de contratos, aditivos, dispensas de licitação e indícios de fraude ou vícios administrativos.

    **Texto do Diário Oficial ({source_name}):**
    {text_content[:20000]}

    Retorne **ESTRITAMENTE** um JSON válido com a seguinte estrutura, sem explicações adicionais fora do JSON:
    {{
      "documento_fonte": "{source_name}",
      "contratos_encontrados": 0,
      "empresa_principal": "Nome da empresa citada com maior valor ou em destaque",
      "cnpj": "CNPJ identificado (se houver)",
      "valor_total_identificado": 0.00,
      "score_risco": 0,  // Inteiro de 0 (Seguro/Normal) a 100 (Alto risco/Anomalia grave)
      "classificacao_risco": "Baixo | Médio | Alto | Crítico",
      "alertas_inconformidades": [
        "Descrição detalhada do indício ou anomalia 1",
        "Descrição detalhada do indício ou anomalia 2"
      ],
      "resumo_extratos": "Breve resumo dos atos oficiais e contratos identificados nesta edição."
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Erro na análise de IA para {source_name}: {e}")
        return {}

# -----------------------------------------------------------------------------
# 5. FLUXO DE EXECUÇÃO PRINCIPAL
# -----------------------------------------------------------------------------
st.subheader("1. Iniciar Varrer do Portal Oficial")
st.write(f"Endereço alvo: `{base_url}`")

if st.button("🚀 Iniciar Scraping & Auditoria Automatizada", type="primary"):
    with st.spinner("Conectando ao servidor da Prefeitura de Valinhos e varrendo diários oficiais..."):
        items = fetch_diario_oficial_links(kw_search, max_editions)
        
    if not items:
        st.warning("Nenhuma edição/link de PDF foi retornado no scraping inicial. O site pode estar requerendo renderização dinâmica ou restrição de sessão.")
    else:
        st.success(f"Encontrados {len(items)} arquivos/edições para análise.")
        
        # Garante diretório temporário para downloads
        os.makedirs("downloads_diario", exist_ok=True)
        
        results = []
        progress_bar = st.progress(0)
        
        for idx, item in enumerate(items):
            file_name = f"diario_edicao_{idx + 1}.pdf"
            file_path = os.path.join("downloads_diario", file_name)
            
            st.text(f"Baixando: {item['titulo']}...")
            success = download_pdf(item['url'], file_path)
            
            if success:
                st.text(f"Extraindo texto e auditando {file_name} via Gemini...")
                extracted_text = extract_text_from_pdf_file(file_path)
                
                if extracted_text.strip():
                    audit_res = analyze_text_for_frauds(extracted_text, file_name)
                    if audit_res:
                        results.append(audit_res)
                else:
                    st.warning(f"O arquivo {file_name} não possui texto extraível (pode ser imagem digitalizada).")
            
            progress_bar.progress((idx + 1) / len(items))
            
        if results:
            st.markdown("---")
            st.subheader("2. Consolidação dos Resultados de Auditoria")
            
            df = pd.DataFrame(results)
            
            # Exibição de Tabela Consolidada
            st.dataframe(
                df[["documento_fonte", "empresa_principal", "cnpj", "valor_total_identificado", "score_risco", "classificacao_risco"]],
                use_container_width=True
            )
            
            # Visualização Gráfica
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                fig_bar = px.bar(
                    df,
                    x="documento_fonte",
                    y="score_risco",
                    color="classificacao_risco",
                    title="Nível de Risco por Edição Auditada",
                    labels={"score_risco": "Score de Risco (0-100)", "documento_fonte": "Documento"}
                )
                st.plotly_chart(fig_bar, use_container_width=True)
                
            with col_chart2:
                fig_scatter = px.scatter(
                    df,
                    x="valor_total_identificado",
                    y="score_risco",
                    hover_data=["empresa_principal", "cnpj"],
                    title="Cruzamento: Valor Identificado x Score de Risco"
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
                
            # Detalhamento de Alertas
            st.markdown("### 🚨 Detalhamento dos Alertas por Documento")
            for res in results:
                with st.expander(f"📄 {res.get('documento_fonte')} - Empresa: {res.get('empresa_principal', 'N/A')} (Score: {res.get('score_risco')})"):
                    st.write(f"**CNPJ:** {res.get('cnpj', 'N/A')}")
                    st.write(f"**Valor Estimado/Identificado:** R$ {res.get('valor_total_identificado', 0):,.2f}")
                    st.write(f"**Resumo:** {res.get('resumo_extratos')}")
                    st.markdown("**Alertas/Inconformidades:**")
                    for alert in res.get("alertas_inconformidades", []):
                        st.write(f"- ⚠️ {alert}")
