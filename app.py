import streamlit as st
import google.generativeai as genai
import PyPDF2
import pandas as pd
import json
import plotly.express as px

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(
    page_title="AuditAI Valinhos - Detector de Anomalias",
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 AuditAI Valinhos - Análise de Contratos Públicos")
st.caption("Cruzamento Inteligente de Documentos para Identificação de Riscos e Anomalias via Gemini API")

# 2. CONFIGURAÇÃO DA API GEMINI
st.sidebar.header("⚙️ Configurações")
api_key = st.sidebar.text_input("Insira sua Gemini API Key:", type="password")

if not api_key:
    st.info("💡 Por favor, insira sua API Key do Google Gemini na barra lateral para prosseguir.")
    st.stop()

genai.configure(api_key=api_key)

# 3. FUNÇÕES AUXILIARES
def extract_text_from_pdf(uploaded_file) -> str:
    """Extrai o texto bruto de um arquivo PDF carregado."""
    text = ""
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        st.error(f"Erro ao ler o arquivo {uploaded_file.name}: {e}")
    return text

def audit_contract_with_gemini(contract_text: str, edital_text: str = "") -> dict:
    """Envia o contrato (e edital opcional) para análise do modelo Gemini."""
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = f"""
    Você é um auditor especialista em licitações e contratos do Tribunal de Contas do Estado de São Paulo (TCE-SP).
    Análise o texto do contrato da Prefeitura de Valinhos (e o edital, se fornecido) em busca de indícios de fraude, vícios ou inconformidades.

    **Contrato:**
    {contract_text[:15000]}

    **Edital de Referência (se fornecido):**
    {edital_text[:15000]}

    Instruções de Resposta:
    Retorne **ESTRITAMENTE** um JSON válido contendo a estrutura abaixo, sem marcações markdown de código fora do JSON:
    {{
      "empresa_contratada": "Nome da empresa",
      "cnpj": "CNPJ da empresa",
      "valor_total": 0.00,
      "objeto_resumido": "Descrição do objeto",
      "score_risco": 0,  // Inteiro de 0 (Baixo) a 100 (Crítico)
      "classificacao_risco": "Baixo | Médio | Alto | Crítico",
      "alertas_identificados": [
        "Descrição detalhada do alerta 1",
        "Descrição detalhada do alerta 2"
      ],
      "clausulas_suspeitas": [
        "Citação ou trecho de cláusula problemático"
      ],
      "recomendacao_auditoria": "Ação recomendada para a fiscalização"
    }}
    """

    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Erro no processamento do modelo AI: {e}")
        return {}

# 4. INTERFACE PRINCIPAL
tab_single, tab_cross = st.tabs(["📄 Análise Individual / Edital", "🔄 Cruzamento em Lote"])

with tab_single:
    st.subheader("Análise de Contrato x Edital/Legislação")
    
    col_pdf1, col_pdf2 = st.columns(2)
    with col_pdf1:
        contract_file = st.file_uploader("Upload do Contrato (PDF)", type=["pdf"], key="single_contract")
    with col_pdf2:
        edital_file = st.file_uploader("Upload do Edital/Anexo (Opcional - PDF)", type=["pdf"], key="single_edital")

    if st.button("Executar Auditoria Inteligente", type="primary"):
        if contract_file:
            with st.spinner("Extraindo textos e executando motor estatístico-linguístico..."):
                c_text = extract_text_from_pdf(contract_file)
                e_text = extract_text_from_pdf(edital_file) if edital_file else ""
                
                result = audit_contract_with_gemini(c_text, e_text)
                
                if result:
                    st.success("Análise concluída!")
                    
                    # Exibição de Métricas
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Empresa", result.get("empresa_contratada", "N/A"))
                    col_m2.metric("CNPJ", result.get("cnpj", "N/A"))
                    col_m3.metric("Valor Total", f"R$ {result.get('valor_total', 0):,.2f}")
                    
                    score = result.get("score_risco", 0)
                    col_m4.metric("Score de Risco", f"{score}/100", delta_color="inverse")

                    st.markdown("---")
                    
                    # Detalhes do Risco
                    risk_class = result.get("classificacao_risco", "N/A")
                    if score >= 70:
                        st.error(f"⚠️ **Nível de Risco:** {risk_class}")
                    elif score >= 40:
                        st.warning(f"⚡ **Nível de Risco:** {risk_class}")
                    else:
                        st.success(f"✅ **Nível de Risco:** {risk_class}")

                    col_det1, col_det2 = st.columns(2)
                    with col_det1:
                        st.markdown("### 🚨 Alertas Identificados")
                        for alert in result.get("alertas_identificados", []):
                            st.write(f"- {alert}")
                            
                    with col_det2:
                        st.markdown("### 📌 Cláusulas de Atenção")
                        for clausula in result.get("clausulas_suspeitas", []):
                            st.write(f"- *\"{clausula}\"*")
                            
                    st.markdown("### 💡 Recomendação da Auditoria")
                    st.info(result.get("recomendacao_auditoria", "Nenhuma ação crítica recomendada."))
        else:
            st.warning("Envie ao menos o arquivo do Contrato.")

with tab_cross:
    st.subheader("Cruzamento Múltiplo para Detecção de Padrões")
    st.write("Carregue múltiplos contratos para identificar sobreposição de CNPJs, discrepâncias de valores e padrões atípicos.")
    
    multiple_files = st.file_uploader("Selecione múltiplos contratos (PDF)", type=["pdf"], accept_multiple_files=True)
    
    if st.button("Analisar Lote e Cruzar Dados", type="primary"):
        if multiple_files:
            results_list = []
            progress_bar = st.progress(0)
            
            for idx, file in enumerate(multiple_files):
                text = extract_text_from_pdf(file)
                res = audit_contract_with_gemini(text)
                if res:
                    res["arquivo"] = file.name
                    results_list.append(res)
                progress_bar.progress((idx + 1) / len(multiple_files))
                
            if results_list:
                df = pd.DataFrame(results_list)
                
                st.markdown("### 📊 Visão Geral do Lote Auditado")
                st.dataframe(
                    df[["arquivo", "empresa_contratada", "cnpj", "valor_total", "score_risco", "classificacao_risco"]],
                    use_container_width=True
                )
                
                # Gráficos de análise
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    fig_bar = px.bar(
                        df, 
                        x="empresa_contratada", 
                        y="score_risco", 
                        color="classificacao_risco",
                        title="Score de Risco por Empresa",
                        labels={"score_risco": "Score (0-100)", "empresa_contratada": "Empresa"}
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                    
                with col_g2:
                    fig_scatter = px.scatter(
                        df, 
                        x="valor_total", 
                        y="score_risco", 
                        size="score_risco",
                        hover_data=["empresa_contratada", "arquivo"],
                        title="Relação: Valor do Contrato x Score de Risco"
                    )
                    st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.warning("Selecione dois ou mais contratos para realizar o cruzamento.")
