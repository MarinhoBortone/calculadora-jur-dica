import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro 2.9 (Final)", layout="wide", page_icon="⚖️")

# CSS Customizado
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        color: #0044cc;
    }
    .stAlert {
        padding: 0.5rem;
    }
    /* Destaque para área de dev */
    .dev-mode {
        border: 1px dashed red;
        padding: 10px;
        border-radius: 5px;
        background-color: #fff0f0;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ CalcJus PRO 2.9 - Sistema Validado")
st.markdown("Cálculos Judiciais com **Lógica de Dívida Única** e **Proteção de Rede**.")

# --- INICIALIZAÇÃO DE ESTADO (SESSION STATE) ---
if 'simular_erro_bcb' not in st.session_state: st.session_state.simular_erro_bcb = False
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao_input' not in st.session_state: st.session_state.df_pensao_input = pd.DataFrame(columns=["Vencimento", "Valor Devido (R$)", "Valor Pago (R$)"])
if 'df_pensao_final' not in st.session_state: st.session_state.df_pensao_final = pd.DataFrame()
if 'dados_aluguel' not in st.session_state: st.session_state.dados_aluguel = None 
if 'regime_desc' not in st.session_state: st.session_state.regime_desc = "Padrão"

# --- FUNÇÃO DE BUSCA NO BANCO CENTRAL (BCB) ---
@st.cache_data(ttl=3600, show_spinner=False)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    """
    Busca o fator acumulado.
    INCLUI: Checagem do Modo Desenvolvedor para simular falhas.
    """
    # --- MODO DE TESTE: SIMULAÇÃO DE ERRO ---
    if st.session_state.simular_erro_bcb:
        return None # Simula falha forçada

    if data_fim <= data_inicio: return 1.0
    if data_inicio > date.today(): return 1.0
    
    d1 = data_inicio.strftime("%d/%m/%Y")
    d2 = data_fim.strftime("%d/%m/%Y")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={d1}&dataFinal={d2}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            fator = 1.0
            for item in dados:
                try:
                    val = float(item['valor'])
                    fator *= (1 + val/100)
                except (ValueError, TypeError):
                    continue
            return fator
        else:
            return None
    except Exception as e:
        return None

# --- CLASSE PDF PROFISSIONAL ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 10)
        self.set_text_color(50, 50, 50)
        self.cell(0, 5, 'CALCJUS PRO - SISTEMA DE CÁLCULOS', 0, 1, 'R')
        self.set_draw_color(0, 0, 0)
        self.line(10, 15, 287, 15) 
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 7)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f'Página {self.page_no()}/{{nb}} | Documento gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 0, 'C')

# --- FUNÇÃO GERADORA DE RELATÓRIO ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, dados_aluguel, totais, config):
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    tem_execucao = (totais['final'] > 0)
    tem_aluguel = (dados_aluguel is not None)
    titulo = "RELATÓRIO GERAL"
    if tem_execucao and not tem_aluguel: titulo = "DEMONSTRATIVO DE CÁLCULO - EXECUÇÃO"
    elif not tem_execucao and tem_aluguel: titulo = "MEMÓRIA DE CÁLCULO - REAJUSTE CONTRATUAL"
    
    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, titulo, 0, 1, "C", fill=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(245, 245, 245)
    pdf.cell(0, 7, " 1. PARÂMETROS E METODOLOGIA", 0, 1, fill=True)
    pdf.ln(1)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    regime_desc = config.get('regime_desc', '-') 
    
    pdf.set_font("Arial", "", 9)
    texto_metodologia = f"DATA BASE DO CÁLCULO: {dt_calc}\n"
    
    if tem_execucao:
        texto_metodologia += (
            f"CRITÉRIO INDENIZAÇÃO/DÍVIDA: {regime_desc}\n"
            f"JUROS DE MORA: 1% a.m. simples (Pro-Rata Die) ou conforme SELIC.\n"
            f"FONTE DOS ÍNDICES: Banco Central do Brasil (SGS).\n"
        )
        
    pdf.multi_cell(0, 5, texto_metodologia)
    pdf.ln(5)

    if not dados_ind.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255)
        pdf.cell(0, 7, " 2. INDENIZAÇÃO / DÍVIDAS GERAIS", 0, 1, fill=True)
        pdf.set_font("Arial", "B", 7)
        cols = [("Vencimento", 22), ("Valor Orig.", 25), ("Fator CM", 20), ("V. Corrigido", 25), ("Juros / Mora", 45), ("Total Fase 1", 25), ("Fator SELIC", 20), ("TOTAL FINAL", 30)]
        for txt, w in cols: pdf.cell(w, 6, txt, 1, 0, 'C')
        pdf.ln()
        pdf.set_font("Arial", "", 7)
        for index, row in dados_ind.iterrows():
            j_detalhe = str(row.get('Audit Juros %', '-'))
            if len(j_detalhe) > 35: j_detalhe = j_detalhe[:32] + "..."
            data_row = [str(row['Vencimento']), str(row['Valor Orig.']), str(row.get('Audit Fator CM', '-')), str(row.get('V. Corrigido Puro', '-')), j_detalhe, str(row.get('Total Fase 1', '-')), str(row.get('Audit Fator SELIC', '-')), str(row['TOTAL'])]
            col_w = [c[1] for c in cols]
            for i, datum in enumerate(data_row):
                align = 'L' if i == 4 else 'C'
                pdf.cell(col_w[i], 6, datum, 1, 0, align)
            pdf.ln()
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", 0, 1, 'R')
        pdf.ln(3)

    if not dados_hon.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 240, 220)
        pdf.cell(0, 7, " 3. HONORÁRIOS DE SUCUMBÊNCIA", 0, 1, fill=True)
        pdf.set_font("Arial", "B", 7)
        cols_hon = [("Descrição", 60), ("Valor Orig.", 30), ("Fator/Índice", 40), ("Juros", 40), ("TOTAL", 40)]
        for txt, w in cols_hon: pdf.cell(w, 6, txt, 1, 0, 'C')
        pdf.ln()
        pdf.set_font("Arial", "", 8)
        for index, row in dados_hon.iterrows():
             pdf.cell(60, 6, str(row['Descrição']), 1, 0, 'L')
             pdf.cell(30, 6, str(row['Valor Orig.']), 1, 0, 'C')
             pdf.cell(40, 6, str(row.get('Audit Fator', '-')), 1, 0, 'C')
             pdf.cell(40, 6, str(row.get('Juros', '-')), 1, 0, 'C')
             pdf.cell(40, 6, str(row['TOTAL']), 1, 0, 'C')
             pdf.ln()
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Honorários: R$ {totais['honorarios']:,.2f}", 0, 1, 'R')
        pdf.ln(3)

    if not dados_pen.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 230, 230)
        pdf.cell(0, 7, " 4. PENSÃO ALIMENTÍCIA (DÉBITOS)", 0, 1, fill=True)
        pdf.set_font("Arial", "B", 7)
        headers_pen = [("Vencimento", 25), ("Devido", 25), ("Pago", 25), ("Base Liq.", 25), ("Fator CM", 20), ("Atualizado", 25), ("Juros", 25), ("TOTAL", 30)]
        for h, w in headers_pen: pdf.cell(w, 6, h, 1, 0, 'C')
        pdf.ln()
        pdf.set_font("Arial", "", 7)
        for index, row in dados_pen.iterrows():
            pdf.cell(25, 6, str(row['Vencimento']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Valor Devido']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Valor Pago']), 1, 0, 'C')
            pdf.set_font("Arial", "B", 7)
            pdf.cell(25, 6, str(row['Base Cálculo']), 1, 0, 'C')
            pdf.set_font("Arial", "", 7)
            pdf.cell(20, 6, str(row['Fator CM']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Atualizado']), 1, 0, 'C')
            pdf.cell(25, 6, str(row.get('Juros', '-')), 1, 0, 'C')
            pdf.set_font("Arial", "B", 7)
            pdf.cell(30, 6, str(row['TOTAL']), 1, 0, 'C')
            pdf.set_font("Arial", "", 7)
            pdf.ln()
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Pensão: R$ {totais['pensao']:,.2f}", 0, 1, 'R')

    if tem_aluguel:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 255, 220) 
        pdf.cell(0, 7, " DEMONSTRATIVO DE REAJUSTE DE ALUGUEL", 0, 1, fill=True)
        da = dados_aluguel
        pdf.set_font("Arial", "", 10)
        pdf.ln(2)
        pdf.cell(50, 8, "Item", 1, 0, 'C')
        pdf.cell(100, 8, "Detalhe", 1, 1, 'C')
        pdf.cell(50, 8, "Valor Atual", 1, 0, 'L')
        pdf.cell(100, 8, f"R$ {da['valor_antigo']:,.2f}", 1, 1, 'R')
        pdf.cell(50, 8, "Índice Aplicado", 1, 0, 'L')
        pdf.cell(100, 8, f"{da['indice']} (Acumulado: {(da['fator']-1)*100:.4f}%)", 1, 1, 'R')
        pdf.cell(50, 8, "Período", 1, 0, 'L')
        pdf.cell(100, 8, da['periodo'], 1, 1, 'R')
        pdf.set_font("Arial", "B", 12)
        pdf.cell(50, 10, "NOVO ALUGUEL", 1, 0, 'L')
        pdf.cell(100, 10, f"R$ {da['novo_valor']:,.2f}", 1, 1, 'R')
        pdf.ln(3)

    if tem_execucao:
        pdf.ln(5)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(100, 8, "RESUMO DA EXECUÇÃO", "B", 1, 'L')
        pdf.ln(2)
        pdf.set_font("Arial", "", 10)
        pdf.cell(140, 8, "Principal Atualizado", 0, 0)
        pdf.cell(40, 8, f"R$ {(totais['indenizacao'] + totais['honorarios'] + totais['pensao']):,.2f}", 0, 1, 'R')
        if config['multa_523']:
            pdf.cell(140, 8, "Multa Art. 523 CPC (10%)", 0, 0)
            pdf.cell(40, 8, f"R$ {totais['multa']:,.2f}", 0, 1, 'R')
        if config['hon_523']:
            pdf.cell(140, 8, "Honorários Execução Art. 523 (10%)", 0, 0)
            pdf.cell(40, 8, f"R$ {totais['hon_exec']:,.2f}", 0, 1, 'R')
        pdf.ln(2)
        pdf.set_font("Arial", "B", 14)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(140, 12, "TOTAL GERAL", 1, 0, 'L', fill=True)
        pdf.cell(40, 12, f"R$ {totais['final']:,.2f}", 1, 1, 'R', fill=True)
        
    pdf.ln(5)
    pdf.set_font("Arial", "I", 7)
    pdf.multi_cell(0, 4, "Aviso Legal: Cálculo estimado com base em séries do BCB.")
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- MAPA DE ÍNDICES GLOBAL ---
mapa_indices_completo = {
    "INPC (IBGE) - 188": 188, 
    "IGP-M (FGV) - 189": 189, 
    "IPCA (IBGE) - 433": 433,
    "IPCA-E (IBGE) - 10764": 10764, 
    "INCC-DI (FGV) - 192": 192, 
    "IGP-DI (FGV) - 190": 190,
    "IPC-Brasil (FGV) - 191": 191,
    "IPC-Fipe - 193": 193,
    "SELIC (Taxa Referencial) - 4390": 4390 
}
cod_selic = 4390

# ==============================================================================
# MENU LATERAL COM MODO DESENVOLVEDOR
# ==============================================================================
st.sidebar.header("Parâmetros Globais")
data_calculo = st.sidebar.date_input("Data do Cálculo", value=date.today())

st.sidebar.divider()
st.sidebar.header("Penalidades")
aplicar_multa_523 = st.sidebar.checkbox("Multa 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Honorários 10% (Art. 523)?", value=False)

st.sidebar.divider()
st.sidebar.markdown("### 🛠️ Área do Desenvolvedor")

# TOGGLE PARA SIMULAR ERRO
modo_simulacao = st.sidebar.toggle("Simular Queda do BCB (Erro)", value=False)

# LÓGICA DO TOGGLE
if modo_simulacao:
    # Se ativou, avisa e limpa o cache para o erro aparecer na hora
    if not st.session_state.simular_erro_bcb:
        st.session_state.simular_erro_bcb = True
        st.cache_data.clear() # Limpa o cache para forçar a re-execução com erro
        st.rerun() # Recarrega a página para atualizar o status
    st.sidebar.error("⚠️ SIMULAÇÃO DE ERRO ATIVA")
else:
    # Se desativou, limpa para voltar ao normal
    if st.session_state.simular_erro_bcb:
        st.session_state.simular_erro_bcb = False
        st.cache_data.clear()
        st.rerun()

# ==============================================================================
# ABAS
# ==============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏢 Indenização", "⚖️ Honorários", "👶 Pensão", "🏠 Reajuste Aluguel", "📊 PDF e Exportação"])

# ==============================================================================
# ABA 1 - INDENIZAÇÃO (LÓGICA CORRIGIDA PARA DÍVIDA ÚNICA)
# ==============================================================================
with tab1:
    st.subheader("Cálculo de Indenização / Cobrança de Atrasados")
    col_input1, col_input2, col_input3 = st.columns(3)
    valor_contrato = col_input1.number_input("Valor Base", value=1000.00, step=100.0)
    perc_indenizacao = col_input2.number_input("Percentual / Multiplicador", value=100.0, step=10.0)
    val_mensal = valor_contrato * (perc_indenizacao / 100)
    col_input3.metric("Valor Mensal Base", f"R$ {val_mensal:,.2f}")
    
    st.write("---")
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2021, 7, 10))
    fim_atraso = c5.date_input("Fim da Mora", value=date(2021, 7, 10))
    
    help_metodo = "Ciclo Mensal: Para aluguéis/salários recorrentes. Mês Civil: Calcula dias proporcionais."
    metodo_calculo = st.radio("Método:", ["Ciclo Mensal Fechado", "Mês Civil (Pro-Rata)"], index=1, horizontal=True, help=help_metodo)
    
    st.write("---")
    st.write("**Regime de Atualização (Selecione aqui):**")
    
    regime_tipo = st.radio(
        "Escolha o Regime:",
        ["1. Índice de Correção + Juros de 1% a.m.", "2. Taxa SELIC (EC 113/21)", "3. Misto (Índice até data X -> SELIC)"],
        horizontal=True
    )
    
    indice_selecionado_ind = None
    codigo_indice_ind = None
    data_corte_selic, data_citacao_ind = None, None

    if "1. Índice" in regime_tipo:
        indice_selecionado_ind = st.selectbox("Selecione o Índice de Correção:", list(mapa_indices_completo.keys()))
        codigo_indice_ind = mapa_indices_completo[indice_selecionado_ind]
        data_citacao_ind = st.date_input("Data Citação (Início Juros)", value=inicio_atraso)
        st.session_state.regime_desc = f"{indice_selecionado_ind} + Juros 1% a.m."
        
    elif "3. Misto" in regime_tipo:
        c_mix_ind, c_mix_dt = st.columns(2)
        indice_selecionado_ind = c_mix_ind.selectbox("Índice Fase 1 (Pré-SELIC):", list(mapa_indices_completo.keys()))
        codigo_indice_ind = mapa_indices_completo[indice_selecionado_ind]
        data_citacao_ind = c_mix_dt.date_input("Data Citação", value=inicio_atraso)
        data_corte_selic = st.date_input("Data de Corte (Início SELIC)", value=date(2021, 12, 9))
        st.session_state.regime_desc = f"Misto ({indice_selecionado_ind} -> SELIC em {data_corte_selic.strftime('%d/%m/%Y')})"
    else:
        st.session_state.regime_desc = "SELIC Pura (Correção + Juros)"

    if st.button("Calcular Indenização/Dívida", type="primary"):
        lista_ind = []
        
        # CHECAGEM PRÉVIA DE SIMULAÇÃO (Para feedback visual imediato)
        if st.session_state.simular_erro_bcb:
             st.error("🚨 ERRO SIMULADO: Falha na conexão com o Banco Central detectada.")
        
        with st.status("Processando...", expanded=True) as status:
            datas_vencimento, valores_base = [], []
            
            # --- LÓGICA CORRIGIDA: DÍVIDA ÚNICA ---
            if inicio_atraso == fim_atraso:
                # Se as datas são iguais, o valor é cheio (não divide por dias)
                datas_vencimento = [inicio_atraso]
                valores_base = [val_mensal]
            else:
                # Se as datas são diferentes, é dívida mensal (aplica Pro-Rata se selecionado)
                if metodo_calculo == "Ciclo Mensal Fechado":
                     t_date = inicio_atraso
                     while t_date < fim_atraso:
                         prox = t_date + relativedelta(months=1)
                         venc = prox - timedelta(days=1)
                         if venc > fim_atraso: venc = fim_atraso
                         datas_vencimento.append(venc)
                         valores_base.append(val_mensal) 
                         t_date = prox
                else:
                    curr_date = inicio_atraso
                    while curr_date <= fim_atraso:
                        ultimo_dia = curr_date.replace(day=calendar.monthrange(curr_date.year, curr_date.month)[1])
                        data_fim_p = fim_atraso if fim_atraso < ultimo_dia else ultimo_dia
                        dias_mes = calendar.monthrange(curr_date.year, curr_date.month)[1]
                        dias_corr = (data_fim_p - curr_date).days + 1
                        val = val_mensal if dias_corr == dias_mes else (val_mensal / dias_mes) * dias_corr
                        datas_vencimento.append(data_fim_p)
                        valores_base.append(val)
                        curr_date = ultimo_dia + timedelta(days=1)

            for i, venc in enumerate(datas_vencimento):
                val_base = valores_base[i]
                audit_fator_cm, audit_juros_perc, audit_fator_selic = "-", "-", "-"
                v_base_selic_str = "-"
                total_final = 0.0
                v_fase1 = 0.0
                v_corrigido_puro = 0.0 
                
                # AQUI ENTRA A CHECAGEM DE RETORNO 'NONE'
                if "1. Índice" in regime_tipo:
                    fator = buscar_fator_bcb(codigo_indice_ind, venc, data_calculo)
                    if fator is None:
                        status.update(label="Erro de Conexão!", state="error")
                        st.error(f"Não foi possível obter índice para {venc.strftime('%d/%m/%Y')}.")
                        st.stop() # PARA O CÓDIGO
                        
                    v_fase1 = val_base * fator
                    v_corrigido_puro = v_fase1
                    audit_fator_cm = f"{fator:.5f}" 
                    dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                    dias = (data_calculo - dt_j).days
                    juros_val = v_fase1 * (0.01/30 * dias) if dias > 0 else 0.0
                    audit_juros_perc = f"{(dias/30):.1f}% ({dias}d)"
                    total_final = v_fase1 + juros_val
                    
                elif "2. Taxa SELIC" in regime_tipo:
                    fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                    if fator is None:
                        status.update(label="Erro de Conexão!", state="error")
                        st.error(f"Erro ao buscar SELIC para {venc.strftime('%d/%m/%Y')}.")
                        st.stop()
                        
                    total_final = val_base * fator
                    audit_fator_selic = f"{fator:.5f}"
                    v_fase1 = total_final
                    v_corrigido_puro = total_final
                    
                elif "3. Misto" in regime_tipo:
                    if venc >= data_corte_selic:
                        fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                        if fator is None:
                            st.error(f"Erro ao buscar SELIC.")
                            st.stop()
                        total_final = val_base * fator
                        audit_fator_selic = f"{fator:.5f}"
                        v_fase1 = total_final
                        v_corrigido_puro = total_final
                    else:
                        fator_f1 = buscar_fator_bcb(codigo_indice_ind, venc, data_corte_selic)
                        if fator_f1 is None:
                            st.error(f"Erro ao buscar índice Fase 1.")
                            st.stop()
                            
                        v_corrigido_puro = val_base * fator_f1
                        audit_fator_cm = f"{fator_f1:.5f} (f1)"
                        dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                        if dt_j < data_corte_selic:
                            d_f1 = (data_corte_selic - dt_j).days
                            j_f1 = v_corrigido_puro * (0.01/30 * d_f1)
                            audit_juros_perc = f"R$ {j_f1:.2f} (f1)"
                        else: j_f1 = 0.0
                        base_selic = v_corrigido_puro + j_f1
                        v_base_selic_str = f"R$ {base_selic:,.2f}"
                        
                        fator_s = buscar_fator_bcb(cod_selic, data_corte_selic, data_calculo)
                        if fator_s is None:
                            st.error(f"Erro ao buscar SELIC Fase 2.")
                            st.stop()
                        total_final = base_selic * fator_s
                        audit_fator_selic = f"{fator_s:.5f}"
                        v_fase1 = base_selic

                lista_ind.append({
                    "Vencimento": venc.strftime("%d/%m/%Y"), "Valor Orig.": f"R$ {val_base:,.2f}", 
                    "Audit Fator CM": audit_fator_cm, "V. Corrigido Puro": f"R$ {v_corrigido_puro:,.2f}", 
                    "Audit Juros %": audit_juros_perc, "Audit Fator SELIC": audit_fator_selic,
                    "Total Fase 1": v_base_selic_str, "TOTAL": f"R$ {total_final:,.2f}", "_num": total_final
                })
            status.update(label="Concluído!", state="complete", expanded=False)
        
        df = pd.DataFrame(lista_ind)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        st.success(f"Total Dívida: R$ {st.session_state.total_indenizacao:,.2f}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 2 - HONORÁRIOS (COM TRAVAS DE ERRO)
# ==============================================================================
with tab2:
    st.subheader("Cálculo de Honorários")
    col_h1, col_h2 = st.columns(2)
    v_h = col_h1.number_input("Valor Honorários", value=1500.00, min_value=0.0, step=0.01, format="%.2f")
    d_h = col_h2.date_input("Data Base", date(2023, 1, 1))
    st.write("---")
    regime_hon = st.radio("Atualização Honorários:", ["1. Correção Monetária + Juros", "2. SELIC Pura"], horizontal=True)
    
    col_opt1, col_opt2 = st.columns(2)
    indice_hon_sel = None
    aplicar_juros_hon = False
    
    if "1. Correção" in regime_hon:
        indice_hon_sel = col_opt1.selectbox("Índice", list(mapa_indices_completo.keys()), index=0)
        aplicar_juros_hon = col_opt2.checkbox("Juros de Mora 1%?", value=True)
    else:
        st.info("SELIC engloba correção e juros.")

    if st.button("Calcular Honorários"):
        if st.session_state.simular_erro_bcb:
             st.error("🚨 ERRO SIMULADO: Conexão interrompida.")
             
        total_hon, desc_audit, juros_txt = 0.0, "", "N/A"
        f = None
        if "SELIC Pura" in regime_hon:
            f = buscar_fator_bcb(cod_selic, d_h, data_calculo)
            if f is None:
                st.error("Erro ao buscar SELIC. Verifique sua conexão com a internet.")
                st.stop()
            total_hon = v_h * f
            desc_audit = f"SELIC {f:.5f}"
            juros_txt = "Incluso"
        else:
            cod_ind_hon = mapa_indices_completo[indice_hon_sel]
            f = buscar_fator_bcb(cod_ind_hon, d_h, data_calculo)
            if f is None:
                st.error(f"Erro ao buscar índice {indice_hon_sel}. Verifique sua conexão.")
                st.stop()
            v_corr = v_h * f
            desc_audit = f"{indice_hon_sel} {f:.5f}"
            val_jur = 0.0
            if aplicar_juros_hon:
                dias = (data_calculo - d_h).days
                if dias > 0:
                    val_jur = v_corr * (0.01/30 * dias)
                    juros_txt = f"R$ {val_jur:,.2f}"
            else: juros_txt = "Não"
            total_hon = v_corr + val_jur
            
        res = [{"Descrição": "Honorários", "Valor Orig.": f"R$ {v_h:,.2f}", "Audit Fator": desc_audit, "Juros": juros_txt, "TOTAL": f"R$ {total_hon:,.2f}", "_num": total_hon}]
        st.session_state.df_honorarios = pd.DataFrame(res)
        st.session_state.total_honorarios = total_hon
        st.success(f"Total Honorários: R$ {total_hon:,.2f}")
        st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), hide_index=True)

# ==============================================================================
# ABA 3 - PENSÃO (COM TRAVAS DE ERRO)
# ==============================================================================
with tab3:
    st.subheader("👶 Pensão Alimentícia")
    st.info("Cálculo de Dívida: O sistema abate o valor pago do original antes de aplicar juros/correção.")
    
    idx_pensao = st.selectbox("Índice para Pensão:", list(mapa_indices_completo.keys()), index=0)
    cod_idx_pensao = mapa_indices_completo[idx_pensao]

    col_p1, col_p2, col_p3 = st.columns(3)
    v_pensao_base = col_p1.number_input("Valor Parcela", value=1000.00)
    dia_vencimento = col_p2.number_input("Dia Venc.", value=10, min_value=1, max_value=31)
    col_d1, col_d2 = st.columns(2)
    ini_pensao = col_d1.date_input("Início", value=date(2023, 1, 1))
    fim_pensao = col_d2.date_input("Fim", value=date.today())
    
    if st.button("1. Gerar Tabela"):
        l = []
        dt_cursor = ini_pensao.replace(day=dia_vencimento) if dia_vencimento <= 28 else ini_pensao
        if dt_cursor < ini_pensao: dt_cursor += relativedelta(months=1)
        while dt_cursor <= fim_pensao:
            l.append({"Vencimento": dt_cursor, "Valor Devido (R$)": float(v_pensao_base), "Valor Pago (R$)": 0.0})
            dt_cursor += relativedelta(months=1)
        st.session_state.df_pensao_input = pd.DataFrame(l)

    tabela_editada = st.data_editor(st.session_state.df_pensao_input, num_rows="dynamic", hide_index=True, use_container_width=True)
    
    if st.button("2. Calcular Saldo Devedor"):
        if st.session_state.simular_erro_bcb:
             st.error("🚨 ERRO SIMULADO: Falha de rede.")
        
        if not tabela_editada.empty:
            res_p = []
            erro_flag = False
            for i, (index, r) in enumerate(tabela_editada.iterrows()):
                try:
                    venc = pd.to_datetime(r["Vencimento"]).date()
                    v_devido, v_pago = float(r["Valor Devido (R$)"]), float(r["Valor Pago (R$)"])
                except: continue
                
                saldo_base = v_devido - v_pago
                if saldo_base <= 0:
                    res_p.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Valor Devido": f"R$ {v_devido:.2f}", "Valor Pago": f"R$ {v_pago:.2f}", "Base Cálculo": "R$ 0.00", "Fator CM": "-", "Atualizado": "QUITADO", "Juros": "-", "TOTAL": "R$ 0.00", "_num": 0.0})
                else:
                    fator = buscar_fator_bcb(cod_idx_pensao, venc, data_calculo)
                    if fator is None:
                        erro_flag = True
                        break
                    v_corr = saldo_base * fator
                    juros = 0.0
                    dias = (data_calculo - venc).days
                    if dias > 0: juros = v_corr * (0.01/30 * dias)
                    total_linha = v_corr + juros
                    res_p.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Valor Devido": f"R$ {v_devido:,.2f}", "Valor Pago": f"R$ {v_pago:,.2f}", "Base Cálculo": f"R$ {saldo_base:,.2f}", "Fator CM": f"{fator:.5f}", "Atualizado": f"R$ {v_corr:,.2f}", "Juros": f"R$ {juros:,.2f}", "TOTAL": f"R$ {total_linha:,.2f}", "_num": total_linha})
            
            if erro_flag:
                st.error("Erro de conexão com BCB. Não foi possível calcular todos os meses.")
                st.stop()
            else:
                st.session_state.df_pensao_final = pd.DataFrame(res_p)
                st.session_state.total_pensao = st.session_state.df_pensao_final["_num"].sum()
                st.success(f"Saldo Devedor: R$ {st.session_state.total_pensao:,.2f}")
                st.dataframe(st.session_state.df_pensao_final.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 4 - REAJUSTE ALUGUEL (COM TRAVAS DE ERRO)
# ==============================================================================
with tab4:
    st.subheader("🏠 Reajuste Anual de Aluguel (Contratual)")
    c_alug1, c_alug2, c_alug3 = st.columns(3)
    val_atual_aluguel = c_alug1.number_input("Valor Atual do Aluguel", value=2000.00, step=50.0)
    dt_reajuste_aluguel = c_alug2.date_input("Data do Reajuste (Aniversário)", value=date.today())
    idx_aluguel = c_alug3.selectbox("Índice de Reajuste", list(mapa_indices_completo.keys()), index=1)
    
    if st.button("Calcular Novo Valor"):
        dt_inicio_12m = dt_reajuste_aluguel - relativedelta(months=12)
        cod_serie_aluguel = mapa_indices_completo[idx_aluguel]
        
        fator_reajuste = None
        with st.spinner(f"Buscando acumulado de {idx_aluguel}..."):
            fator_reajuste = buscar_fator_bcb(cod_serie_aluguel, dt_inicio_12m, dt_reajuste_aluguel)
        
        if fator_reajuste is None:
            st.error(f"Não foi possível obter o índice {idx_aluguel} no BCB. Tente novamente mais tarde.")
            st.stop()
            
        novo_valor_aluguel = val_atual_aluguel * fator_reajuste
        dif = novo_valor_aluguel - val_atual_aluguel
        perc_acum = (fator_reajuste - 1) * 100
        
        st.session_state.dados_aluguel = {
            'valor_antigo': val_atual_aluguel,
            'novo_valor': novo_valor_aluguel,
            'indice': idx_aluguel,
            'periodo': f"{dt_inicio_12m.strftime('%d/%m/%Y')} a {dt_reajuste_aluguel.strftime('%d/%m/%Y')}",
            'fator': fator_reajuste
        }
        
        st.markdown("### Resultado do Reajuste")
        m1, m2, m3 = st.columns(3)
        m1.metric("Índice Acumulado", f"{perc_acum:.4f}%")
        m2.metric("Aumento", f"R$ {dif:,.2f}")
        m3.metric("Novo Aluguel", f"R$ {novo_valor_aluguel:,.2f}")

# ==============================================================================
# ABA 5 - PDF FINAL
# ==============================================================================
with tab5:
    st.header("Gerar Relatório / PDF")
    
    t1 = st.session_state.total_indenizacao
    t2 = st.session_state.total_honorarios
    t3 = st.session_state.total_pensao
    tem_aluguel = st.session_state.dados_aluguel is not None
    
    sub = t1 + t2 + t3
    mul = sub * 0.10 if aplicar_multa_523 else 0.0
    hon = sub * 0.10 if aplicar_hon_523 else 0.0
    fin = sub + mul + hon
    
    st.write("### Itens que serão incluídos no PDF:")
    c_status1, c_status2, c_status3, c_status4 = st.columns(4)
    c_status1.checkbox("Indenização/Dívida", value=(t1 > 0), disabled=True)
    c_status2.checkbox("Honorários", value=(t2 > 0), disabled=True)
    c_status3.checkbox("Pensão", value=(t3 > 0), disabled=True)
    c_status4.checkbox("Reajuste Aluguel", value=tem_aluguel, disabled=True)
    
    st.write("---")
    if fin > 0:
        st.metric("TOTAL DA EXECUÇÃO (DÍVIDAS)", f"R$ {fin:,.2f}")
    elif tem_aluguel:
        st.info("Apenas Reajuste de Aluguel será gerado (sem valor de execução).")
    else:
        st.warning("Nenhum cálculo realizado ainda.")
    
    conf_pdf = {'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523, 'metodo': metodo_calculo, 'data_calculo': data_calculo, 'regime_desc': st.session_state.regime_desc}
    tot_pdf = {'indenizacao': t1, 'honorarios': t2, 'pensao': t3, 'multa': mul, 'hon_exec': hon, 'final': fin}
    
    if st.button("📄 Gerar PDF Inteligente"):
        if fin == 0 and not tem_aluguel:
            st.error("Realize pelo menos um cálculo antes de gerar o PDF.")
        else:
            pdf_bytes = gerar_pdf_relatorio(
                st.session_state.df_indenizacao, 
                st.session_state.df_honorarios, 
                st.session_state.df_pensao_final, 
                st.session_state.dados_aluguel,
                tot_pdf, 
                conf_pdf
            )
            st.download_button(label="⬇️ Baixar PDF", data=pdf_bytes, file_name="Relatorio_CalcJus.pdf", mime="application/pdf")
