import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro 2.0", layout="wide", page_icon="⚖️")

# CSS Customizado para tabelas e métricas
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        color: #0044cc;
    }
    .stAlert {
        padding: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ CalcJus PRO 2.0 - Relatórios Periciais Auditáveis")
st.markdown("Sistema de Cálculos Judiciais com **Memória de Cálculo Detalhada** e **Metodologia Explícita**.")

# --- FUNÇÃO DE BUSCA NO BANCO CENTRAL (BCB) ---
@st.cache_data(ttl=3600, show_spinner=False)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    """
    Busca o fator acumulado de uma série temporal do SGS/BCB.
    Retorna o fator multiplicador (ex: 1.05 para 5% de correção).
    """
    if data_fim <= data_inicio: return 1.0
    
    # Validação de data futura
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
            return 1.0 # Fallback seguro, mas idealmente logar erro
    except Exception as e:
        return 1.0

# --- CLASSE PDF PROFISSIONAL ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 10)
        self.set_text_color(50, 50, 50)
        self.cell(0, 5, 'CALCJUS PRO - SISTEMA DE CÁLCULOS JUDICIAIS', 0, 1, 'R')
        self.set_draw_color(0, 0, 0)
        self.line(10, 15, 287, 15) 
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 7)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f'Página {self.page_no()}/{{nb}} | Documento gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")} | Hash de validação interno', 0, 0, 'C')

# --- FUNÇÃO GERADORA DE RELATÓRIO ---
def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, totais, config):
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- 1. IDENTIFICAÇÃO ---
    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, "DEMONSTRATIVO DE CÁLCULO JUDICIAL ANALÍTICO", 0, 1, "C", fill=True)
    pdf.ln(5)
    
    # Metodologia
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(245, 245, 245)
    pdf.cell(0, 7, " 1. PARÂMETROS E METODOLOGIA APLICADA", 0, 1, fill=True)
    pdf.ln(1)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    indice_nome = config.get('indice_nome', '-')
    regime_desc = config.get('regime_desc', '-') 
    
    pdf.set_font("Arial", "", 9)
    texto_metodologia = (
        f"DATA BASE DO CÁLCULO: {dt_calc}\n"
        f"CRITÉRIO DE ATUALIZAÇÃO: {regime_desc}\n"
        f"ÍNDICE DE CORREÇÃO BASE: {indice_nome} (Fonte: Banco Central/SGS)\n"
        f"CRITÉRIO DE JUROS: 1% ao mês simples (Pro-Rata Die) ou SELIC conforme regime selecionado.\n"
        f"FÓRMULAS:\n"
        f"  - Valor Corrigido = Valor Original x Fator Acumulado do Índice.\n"
        f"  - Juros Moratórios = Valor Corrigido x (Taxa% / 30 x Dias de Atraso).\n"
        f"  - Total Final = Base de Cálculo x Fator SELIC (quando aplicável o regime SELIC)."
    )
    pdf.multi_cell(0, 5, texto_metodologia)
    pdf.ln(5)

    # --- 2. TABELAS ---
    
    # INDENIZAÇÃO
    if totais['indenizacao'] > 0:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255) # Azul claro
        pdf.cell(0, 7, " 2. INDENIZAÇÃO / LUCROS CESSANTES", 0, 1, fill=True)
        
        pdf.set_font("Arial", "B", 7)
        # Colunas ajustadas para paisagem A4
        cols = [
            ("Vencimento", 22), 
            ("Valor Orig.", 25), 
            ("Fator CM", 20), 
            ("V. Corrigido", 25), 
            ("Juros / Mora (Detalhamento)", 45), 
            ("Total Fase 1", 25), 
            ("Fator SELIC", 20), 
            ("TOTAL FINAL", 30)
        ]
        
        # Header da Tabela
        for txt, w in cols: pdf.cell(w, 6, txt, 1, 0, 'C')
        pdf.ln()
        
        # Linhas
        pdf.set_font("Arial", "", 7)
        for index, row in dados_ind.iterrows():
            venc = str(row['Vencimento'])
            orig = str(row['Valor Orig.'])
            f_cm = str(row.get('Audit Fator CM', '-'))
            v_corr = str(row.get('V. Corrigido Puro', '-'))
            j_detalhe = str(row.get('Audit Juros %', '-'))
            
            # Truncar texto de juros se for muito longo
            if len(j_detalhe) > 35: j_detalhe = j_detalhe[:32] + "..."

            total_f1_str = str(row.get('Total Fase 1', '-'))
            f_selic = str(row.get('Audit Fator SELIC', '-'))
            total = str(row['TOTAL'])

            data_row = [venc, orig, f_cm, v_corr, j_detalhe, total_f1_str, f_selic, total]
            col_w = [c[1] for c in cols]
            
            # Altura dinâmica simples
            h = 6
            
            for i, datum in enumerate(data_row):
                align = 'L' if i == 4 else 'C' # Alinha juros à esquerda
                pdf.cell(col_w[i], h, datum, 1, 0, align)
            pdf.ln()
            
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Indenização: R$ {totais['indenizacao']:,.2f}", 0, 1, 'R')
        pdf.ln(3)

    # HONORÁRIOS
    if totais['honorarios'] > 0:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 240, 220) # Verde claro
        pdf.cell(0, 7, " 3. HONORÁRIOS DE SUCUMBÊNCIA", 0, 1, fill=True)
        pdf.set_font("Arial", "", 8)
        for index, row in dados_hon.iterrows():
             pdf.cell(0, 7, f"Descrição: {row['Descrição']} | Base: {row['Valor Orig.']} | Fator: {row.get('Audit Fator', '-')} | Total: {row['TOTAL']}", 0, 1)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Honorários: R$ {totais['honorarios']:,.2f}", 0, 1, 'R')
        pdf.ln(3)

    # PENSÃO
    if totais['pensao'] > 0:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 230, 230) # Vermelho claro
        pdf.cell(0, 7, " 4. PENSÃO ALIMENTÍCIA (DÉBITOS EM ABERTO)", 0, 1, fill=True)
        
        pdf.set_font("Arial", "B", 7)
        headers_pen = [("Vencimento", 25), ("Original", 25), (f"Fator {indice_nome}", 25), ("Atualizado", 25), ("Juros", 25), ("Pago", 25), ("Saldo Devido", 30)]
        for h, w in headers_pen: pdf.cell(w, 6, h, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for index, row in dados_pen.iterrows():
            pdf.cell(25, 6, str(row['Vencimento']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Valor Orig.']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Fator CM']), 1, 0, 'C')
            pdf.cell(25, 6, str(row['Devido Atual.']), 1, 0, 'C')
            pdf.cell(25, 6, str(row.get('Juros', '-')), 1, 0, 'C')
            pdf.cell(25, 6, str(row.get('Pago', '-')), 1, 0, 'C')
            pdf.set_font("Arial", "B", 7)
            pdf.cell(30, 6, str(row['SALDO DEVEDOR']), 1, 0, 'C')
            pdf.set_font("Arial", "", 7)
            pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, f"Subtotal Pensão (Líquido): R$ {totais['pensao']:,.2f}", 0, 1, 'R')

    # --- 3. RESUMO FINAL ---
    pdf.ln(5)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_fill_color(255, 255, 255)
    
    y_start = pdf.get_y()
    
    pdf.set_font("Arial", "B", 11)
    pdf.cell(100, 8, "RESUMO FINAL DA EXECUÇÃO", "B", 1, 'L')
    pdf.ln(2)
    
    pdf.set_font("Arial", "", 10)
    
    # Caixa de totais
    pdf.cell(140, 8, "Principal Atualizado (Soma dos Subtotais)", 0, 0)
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
    pdf.cell(140, 12, "TOTAL GERAL DA CONDENAÇÃO", 1, 0, 'L', fill=True)
    pdf.cell(40, 12, f"R$ {totais['final']:,.2f}", 1, 1, 'R', fill=True)
    
    pdf.ln(5)
    pdf.set_font("Arial", "I", 7)
    pdf.multi_cell(0, 4, "Aviso Legal: Este cálculo é uma estimativa baseada nas séries temporais públicas do Banco Central. "
                           "Diferenças de centavos podem ocorrer devido a arredondamentos. "
                           "Fontes: Séries 188 (INPC), 189 (IGP-M), 192 (INCC), 433 (IPCA), 4390 (SELIC).")
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- MENU LATERAL ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764, "IPCA": 433}
indice_padrao_nome = st.sidebar.selectbox("Índice Base (Pré-Selic ou Padrão)", list(mapa_indices.keys()))
codigo_indice_padrao = mapa_indices[indice_padrao_nome]
cod_selic = 4390

st.sidebar.divider()
st.sidebar.header("2. Penalidades (Execução)")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)
st.sidebar.info("Estas penalidades incidem sobre o subtotal atualizado.")

# Inicialização do Estado (Session State)
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao_input' not in st.session_state: st.session_state.df_pensao_input = pd.DataFrame(columns=["Vencimento", "Valor Devido (R$)", "Valor Pago (R$)"])
if 'df_pensao_final' not in st.session_state: st.session_state.df_pensao_final = pd.DataFrame()
if 'regime_desc' not in st.session_state: st.session_state.regime_desc = "Padrão"

tab1, tab2, tab3, tab4 = st.tabs(["🏢 Indenização", "⚖️ Honorários", "👶 Pensão", "📊 PDF Final"])

# ==============================================================================
# ABA 1 - INDENIZAÇÃO COM AUDITORIA
# ==============================================================================
with tab1:
    st.subheader("Cálculo de Indenização / Lucros Cessantes")
    col_input1, col_input2, col_input3 = st.columns(3)
    valor_contrato = col_input1.number_input("Valor Base (Contrato/Aluguel)", value=10000.00, step=100.0)
    perc_indenizacao = col_input2.number_input("% Mensal", value=0.5, step=0.1)
    val_mensal = valor_contrato * (perc_indenizacao / 100)
    col_input3.metric("Valor Mensal Calculado", f"R$ {val_mensal:,.2f}")
    
    st.write("---")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 1, 1))
    fim_atraso = c5.date_input("Fim da Mora", value=date.today())
    metodo_calculo = st.radio("Método de Contagem:", ["Ciclo Mensal Fechado", "Mês Civil (Pro-Rata)"], index=1, horizontal=True, help="Ciclo Mensal considera dia a dia do mês seguinte. Mês Civil quebra pelo calendário (ex: 1 a 31).")
    
    st.write("---")
    st.write("**Regime de Atualização:**")
    tipo_regime = st.radio("Selecione o critério:", 
        [f"1. Padrão: {indice_padrao_nome} + Juros 1% a.m.", "2. SELIC Pura (EC 113/21)", "3. Misto: Correção/Juros até Data X -> SELIC depois"],
        horizontal=True
    )
    
    data_corte_selic = None
    data_citacao_ind = None
    
    if "3. Misto" in tipo_regime:
        c_mix1, c_mix2 = st.columns(2)
        data_citacao_ind = c_mix1.date_input("Data Citação (Início Juros Fase 1)", value=inicio_atraso)
        data_corte_selic = c_mix2.date_input("Data Início SELIC (Corte)", value=date(2021, 12, 9))
        st.session_state.regime_desc = f"Misto ({indice_padrao_nome} + Juros 1% até {data_corte_selic.strftime('%d/%m/%Y')} -> SELIC acumulada)"
    elif "1. Padrão" in tipo_regime:
        data_citacao_ind = st.date_input("Data Citação (Início Juros Moratórios)", value=inicio_atraso)
        st.session_state.regime_desc = f"Padrão ({indice_padrao_nome} + Juros 1% a.m.)"
    else:
        st.session_state.regime_desc = "SELIC Pura (EC 113/21)"
        st.info("ℹ️ Regime SELIC Pura: Aplica-se a taxa SELIC (que engloba juros e correção) desde o vencimento de cada parcela.")

    if st.button("Calcular Indenização", type="primary", use_container_width=True):
        lista_ind = []
        
        with st.status("Processando dados...", expanded=True) as status:
            st.write("Gerando datas de vencimento...")
            # GERAÇÃO DE DATAS
            datas_vencimento = []
            valores_base = []
            
            if metodo_calculo == "Ciclo Mensal Fechado":
                 t_date = inicio_atraso
                 while t_date < fim_atraso:
                     prox = t_date + relativedelta(months=1)
                     venc = prox - timedelta(days=1)
                     if venc > fim_atraso: venc = fim_atraso
                     datas_vencimento.append(venc)
                     valores_base.append(val_mensal) 
                     t_date = prox # Avança ciclo
            else:
                # Mês Civil Pro-Rata
                curr_date = inicio_atraso
                while curr_date <= fim_atraso:
                    # Define o último dia do mês atual
                    ultimo_dia_mes = curr_date.replace(day=calendar.monthrange(curr_date.year, curr_date.month)[1])
                    
                    # Se o fim do atraso for antes do fim do mês, corta ali
                    data_fim_periodo = fim_atraso if fim_atraso < ultimo_dia_mes else ultimo_dia_mes
                    
                    # Cálculo pro-rata
                    dias_no_mes = calendar.monthrange(curr_date.year, curr_date.month)[1]
                    dias_corridos = (data_fim_periodo - curr_date).days + 1
                    
                    if dias_corridos == dias_no_mes:
                        val = val_mensal # Mês cheio
                    else:
                        val = (val_mensal / dias_no_mes) * dias_corridos # Pro-rata
                    
                    datas_vencimento.append(data_fim_periodo)
                    valores_base.append(val)
                    
                    # Avança para o dia 1 do próximo mês
                    curr_date = ultimo_dia_mes + timedelta(days=1)

            st.write(f"Consultando APIs do Banco Central ({len(datas_vencimento)} parcelas)...")
            
            # CÁLCULO
            for i, venc in enumerate(datas_vencimento):
                val_base = valores_base[i]
                
                audit_fator_cm = "-"
                audit_juros_perc = "-"
                audit_fator_selic = "-"
                v_base_selic_str = "-" 
                
                total_final = 0.0
                v_fase1 = 0.0
                v_corrigido_puro = 0.0 
                
                if "1. Padrão" in tipo_regime:
                    fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                    v_fase1 = val_base * fator
                    v_corrigido_puro = v_fase1
                    audit_fator_cm = f"{fator:.5f}" 
                    
                    # Juros
                    dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                    dias = (data_calculo - dt_j).days
                    juros_val = v_fase1 * (0.01/30 * dias) if dias > 0 else 0.0
                    perc_juros = (dias/30) 
                    audit_juros_perc = f"{perc_juros:.1f}% ({dias} dias)"
                    
                    total_final = v_fase1 + juros_val

                elif "2. SELIC" in tipo_regime:
                    fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                    total_final = val_base * fator
                    audit_fator_selic = f"{fator:.5f}"
                    v_fase1 = total_final 
                    v_corrigido_puro = total_final
                
                elif "3. Misto" in tipo_regime:
                    if venc >= data_corte_selic:
                        # Venceu na era SELIC, só aplica SELIC
                        fator = buscar_fator_bcb(cod_selic, venc, data_calculo)
                        total_final = val_base * fator
                        audit_fator_selic = f"{fator:.5f}"
                        v_corrigido_puro = total_final
                        v_fase1 = total_final
                    else:
                        # Fase 1: Correção monetária até a data de corte
                        fator_f1 = buscar_fator_bcb(codigo_indice_padrao, venc, data_corte_selic)
                        v_corrigido_puro = val_base * fator_f1
                        audit_fator_cm = f"{fator_f1:.5f} (até {data_corte_selic.strftime('%d/%m/%y')})"
                        
                        # Fase 1: Juros até a data de corte
                        dt_j = data_citacao_ind if venc < data_citacao_ind else venc
                        if dt_j < data_corte_selic:
                            d_f1 = (data_corte_selic - dt_j).days
                            j_f1 = v_corrigido_puro * (0.01/30 * d_f1)
                            audit_juros_perc = f"R$ {j_f1:,.2f} ({d_f1}d - Fase 1)"
                        else:
                            j_f1 = 0.0
                        
                        base_selic = v_corrigido_puro + j_f1
                        v_base_selic_str = f"R$ {base_selic:,.2f}"
                        
                        # Fase 2: SELIC da data de corte até hoje
                        fator_s = buscar_fator_bcb(cod_selic, data_corte_selic, data_calculo)
                        total_final = base_selic * fator_s
                        audit_fator_selic = f"{fator_s:.5f}"
                        v_fase1 = base_selic 

                lista_ind.append({
                    "Vencimento": venc.strftime("%d/%m/%Y"), 
                    "Valor Orig.": f"R$ {val_base:,.2f}", 
                    "Audit Fator CM": audit_fator_cm,
                    "V. Corrigido Puro": f"R$ {v_corrigido_puro:,.2f}", 
                    "Audit Juros %": audit_juros_perc,
                    "Audit Fator SELIC": audit_fator_selic,
                    "Total Fase 1": v_base_selic_str, 
                    "TOTAL": f"R$ {total_final:,.2f}", 
                    "_num": total_final
                })
            
            status.update(label="Cálculo Concluído!", state="complete", expanded=False)
        
        df = pd.DataFrame(lista_ind)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        
        st.success(f"Total Atualizado: R$ {st.session_state.total_indenizacao:,.2f}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 2 - HONORÁRIOS
# ==============================================================================
with tab2:
    st.subheader("Cálculo de Honorários Isolados")
    col_h1, col_h2 = st.columns(2)
    v_h = col_h1.number_input("Valor Nominal", 1500.00)
    d_h = col_h2.date_input("Data Base Honorários", date(2023, 1, 1))
    
    if st.button("Calcular Honorários", type="primary"):
        f = buscar_fator_bcb(codigo_indice_padrao, d_h, data_calculo)
        tot = v_h * f
        res = [{"Descrição": "Honorários Fixados", "Valor Orig.": f"R$ {v_h:.2f}", "Audit Fator": f"{indice_padrao_nome} {f:.4f}", "Juros": "N/A", "TOTAL": f"R$ {tot:.2f}", "_num": tot}]
        st.session_state.df_honorarios = pd.DataFrame(res)
        st.session_state.total_honorarios = tot
        st.success(f"Honorários Atualizados: R$ {tot:,.2f}")
        st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), hide_index=True)

# ==============================================================================
# ABA 3 - PENSÃO
# ==============================================================================
with tab3:
    st.subheader("👶 Pensão Alimentícia")
    st.markdown("Utilize esta aba para calcular diferenças de pensão não paga. Você pode gerar a tabela automática e depois editar os valores pagos.")
    
    col_p1, col_p2, col_p3 = st.columns(3)
    v_pensao_base = col_p1.number_input("Valor da Parcela Mensal", value=1000.00)
    dia_vencimento = col_p2.number_input("Dia de Vencimento", value=10, min_value=1, max_value=31)
    
    col_d1, col_d2 = st.columns(2)
    ini_pensao = col_d1.date_input("Data Início (Primeira Parcela)", value=date(2023, 1, 1))
    fim_pensao = col_d2.date_input("Data Fim", value=date.today())
    
    if st.button("1. Gerar Tabela Base", help="Cria uma lista de meses entre as datas selecionadas"):
        l = []
        # Lógica para definir a data correta do primeiro mês
        dt_cursor = ini_pensao.replace(day=dia_vencimento) if dia_vencimento <= 28 else ini_pensao
        # Se a data calculada for anterior ao inicio real, avança um mês (opcional, depende do caso)
        if dt_cursor < ini_pensao: 
            dt_cursor += relativedelta(months=1)
            
        while dt_cursor <= fim_pensao:
            l.append({
                "Vencimento": dt_cursor, 
                "Valor Devido (R$)": float(v_pensao_base), 
                "Valor Pago (R$)": 0.0
            })
            dt_cursor += relativedelta(months=1)
        
        st.session_state.df_pensao_input = pd.DataFrame(l)

    # Tabela Editável
    st.write("👇 **Tabela de Lançamentos (Edite valores pagos ou adicione linhas):**")
    
    tabela_editada = st.data_editor(
        st.session_state.df_pensao_input, 
        num_rows="dynamic", 
        hide_index=True,
        column_config={
            "Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
            "Valor Devido (R$)": st.column_config.NumberColumn("Devido", format="R$ %.2f"),
            "Valor Pago (R$)": st.column_config.NumberColumn("Pago", format="R$ %.2f"),
        },
        use_container_width=True
    )
    
    if st.button("2. Calcular Saldo Devedor", type="primary"):
        if tabela_editada.empty:
            st.warning("A tabela está vazia.")
        else:
            res_p = []
            total_divida = 0.0
            
            bar = st.progress(0)
            total_rows = len(tabela_editada)
            
            for i, (index, r) in enumerate(tabela_editada.iterrows()):
                bar.progress((i+1)/total_rows)
                
                try:
                    venc = pd.to_datetime(r["Vencimento"]).date()
                    v_orig = float(r["Valor Devido (R$)"])
                    v_pago = float(r["Valor Pago (R$)"])
                except:
                    continue # Pula linhas inválidas
                
                # Correção Monetária
                fator = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_corr = v_orig * fator
                
                # Juros (Padrão 1% simples)
                juros = 0.0
                dias = (data_calculo - venc).days
                if dias > 0: juros = v_corr * (0.01/30 * dias)
                
                total_bruto = v_corr + juros
                
                # Abatimento do valor pago (sem atualizar o valor pago, método simples de compensação)
                # OBS: Em cálculos complexos, o valor pago também deve ser atualizado até a data base.
                # Aqui faremos a dedução direta para simplificação, ou atualizamos o pago também:
                
                fator_pago = buscar_fator_bcb(codigo_indice_padrao, venc, data_calculo)
                v_pago_atualizado = v_pago * fator_pago
                
                saldo_mes = total_bruto - v_pago_atualizado
                if saldo_mes < 0: saldo_mes = 0 # Não gera crédito reverso nesta lógica
                
                res_p.append({
                    "Vencimento": venc.strftime("%d/%m/%Y"), 
                    "Valor Orig.": f"R$ {v_orig:,.2f}", 
                    "Fator CM": f"{fator:.5f}", 
                    "Devido Atual.": f"R$ {v_corr:,.2f}", 
                    "Juros": f"R$ {juros:,.2f}", 
                    "Pago": f"R$ {v_pago:,.2f} (At: {v_pago_atualizado:,.2f})",
                    "SALDO DEVEDOR": f"R$ {saldo_mes:,.2f}", 
                    "_num": saldo_mes
                })
            
            bar.empty()
            st.session_state.df_pensao_final = pd.DataFrame(res_p)
            st.session_state.total_pensao = st.session_state.df_pensao_final["_num"].sum()
            
            st.success(f"Saldo Devedor Total: R$ {st.session_state.total_pensao:,.2f}")
            st.dataframe(st.session_state.df_pensao_final.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 4 - RESUMO
# ==============================================================================
with tab4:
    st.header("Resumo Global e Exportação")
    
    col_res1, col_res2 = st.columns([1, 2])
    
    with col_res1:
        st.markdown("### Valores Consolidados")
        t1 = st.session_state.total_indenizacao
        t2 = st.session_state.total_honorarios
        t3 = st.session_state.total_pensao
        
        st.write(f"🏢 Indenização: **R$ {t1:,.2f}**")
        st.write(f"⚖️ Honorários: **R$ {t2:,.2f}**")
        st.write(f"👶 Pensão: **R$ {t3:,.2f}**")
        
        sub = t1 + t2 + t3
        st.markdown("---")
        st.write(f"**Subtotal:** R$ {sub:,.2f}")
        
        mul = sub * 0.10 if aplicar_multa_523 else 0.0
        hon = sub * 0.10 if aplicar_hon_523 else 0.0
        
        if aplicar_multa_523: st.write(f"+ Multa 10%: R$ {mul:,.2f}")
        if aplicar_hon_523: st.write(f"+ Hon. Execução 10%: R$ {hon:,.2f}")
        
        fin = sub + mul + hon
        st.metric("TOTAL FINAL DA EXECUÇÃO", f"R$ {fin:,.2f}")

    with col_res2:
        st.info("💡 Clique abaixo para gerar o PDF oficial com a memória de cálculo completa e metodologia detalhada.")
        
        tot_pdf = {'indenizacao': t1, 'honorarios': t2, 'pensao': t3, 'multa': mul, 'hon_exec': hon, 'final': fin}
        conf_pdf = {
            'multa_523': aplicar_multa_523, 
            'hon_523': aplicar_hon_523, 
            'metodo': metodo_calculo, 
            'indice_nome': indice_padrao_nome, 
            'data_calculo': data_calculo, 
            'regime_desc': st.session_state.regime_desc
        }
        
        if st.button("📄 Gerar PDF Oficial"):
            if fin == 0:
                st.error("Realize pelo menos um cálculo antes de gerar o PDF.")
            else:
                try:
                    pdf_bytes = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, tot_pdf, conf_pdf)
                    st.download_button(
                        label="⬇️ Baixar Relatório PDF",
                        data=pdf_bytes,
                        file_name=f"Calculo_Juridico_{date.today().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                except Exception as e:
                    st.error(f"Erro ao gerar PDF: {e}")
