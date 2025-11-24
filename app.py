import streamlit as st
import pandas as pd
import requests
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF
from decimal import Decimal, ROUND_HALF_UP, getcontext
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. CONFIGURAÇÃO FINANCEIRA E GLOBAL ---
getcontext().prec = 28
DOIS_DECIMAIS = Decimal('0.01')

st.set_page_config(page_title="CalcJus Pro 4.5 (Final)", layout="wide", page_icon="⚖️")

st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.4rem; color: #0044cc; font-weight: bold; }
    .stAlert { padding: 0.5rem; border-radius: 8px; }
    thead tr th:first-child { display:none }
    tbody th { display:none }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ CalcJus PRO 4.5 - Sistema Integrado")
st.markdown("Cálculos Judiciais com Precisão Decimal e Relatórios Detalhados.")

# --- 2. ESTADO DA SESSÃO ---
state_vars = {
    'simular_erro_bcb': False,
    'total_indenizacao': Decimal('0.00'),
    'total_honorarios': Decimal('0.00'),
    'total_pensao': Decimal('0.00'),
    'df_indenizacao': pd.DataFrame(),
    'df_honorarios': pd.DataFrame(),
    'df_pensao_input': pd.DataFrame(columns=["Vencimento", "Valor Devido (R$)", "Valor Pago (R$)"]),
    'df_pensao_final': pd.DataFrame(),
    'dados_aluguel': None,
    'params_relatorio': {
        'regime_desc': 'Padrão',
        'tipo_regime': 'Padrão',
        'indice_nome': 'Índice',
        'data_corte': None,
        'data_citacao': None,
        'data_calculo': date.today()
    }
}

for var, default in state_vars.items():
    if var not in st.session_state:
        st.session_state[var] = default

# --- 3. FUNÇÕES UTILITÁRIAS ---

def to_decimal(valor):
    """Converte input para Decimal de forma BLINDADA."""
    if not valor: return Decimal('0.00')
    try:
        if isinstance(valor, (float, int, Decimal)):
            return Decimal(str(valor))
        if isinstance(valor, str):
            valor = valor.strip()
            # Se tem vírgula, é formato BR (milhar com ponto ou sem, decimal com virgula)
            if ',' in valor:
                valor = valor.replace('.', '').replace(',', '.')
            # Se só tem ponto, assume que é separador decimal (segurança)
        return Decimal(str(valor))
    except:
        return Decimal('0.00')

def formatar_moeda(valor):
    try:
        if not isinstance(valor, Decimal):
            valor = to_decimal(valor)
        valor_ajustado = valor.quantize(DOIS_DECIMAIS, rounding=ROUND_HALF_UP)
        texto = f"R$ {valor_ajustado:,.2f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def formatar_decimal_str(valor):
    return f"{valor:.6f}"

# --- 4. CONEXÃO BCB ---

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    if st.session_state.simular_erro_bcb: return None
    if data_fim <= data_inicio or data_inicio > date.today():
        return Decimal('1.000000')
    
    d1 = data_inicio.strftime("%d/%m/%Y")
    d2 = data_fim.strftime("%d/%m/%Y")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={d1}&dataFinal={d2}"
    
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)

    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            try:
                dados = response.json()
            except:
                return None 

            fator = Decimal('1.0')
            for item in dados:
                try:
                    val_raw = item['valor']
                    if isinstance(val_raw, str):
                        val_raw = val_raw.replace(',', '.')
                    fator *= (Decimal('1') + (Decimal(val_raw) / Decimal('100')))
                except:
                    continue
            return fator
        return None
    except Exception:
        return None

# --- 5. GERAÇÃO DE PDF (COM CORREÇÃO DE LARGURA DE COLUNAS) ---
class PDFRelatorio(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 0, 0)
        self.cell(0, 5, 'RELATÓRIO DE CÁLCULO JUDICIAL', 0, 1, 'C')
        self.ln(2)
        self.set_draw_color(0, 0, 0)
        self.line(10, 18, 287, 18) 
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 7)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f'Pagina {self.page_no()}/{{nb}} | Gerado via CalcJus Pro em {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 0, 'C')

    def safe_cell(self, w, h, txt, border=0, ln=0, align='', fill=False):
        try:
            txt_safe = str(txt).encode('latin-1', 'replace').decode('latin-1')
            self.cell(w, h, txt_safe, border, ln, align, fill)
        except:
            self.cell(w, h, "?", border, ln, align, fill)

    def safe_multi_cell(self, w, h, txt, border=0, align='J', fill=False):
        try:
            txt_safe = str(txt).encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(w, h, txt_safe, border, align, fill)
        except:
            self.multi_cell(w, h, "Erro texto.", border, align, fill)

def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, dados_aluguel, totais, config):
    pdf = PDFRelatorio(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- MEMORIAL ---
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.safe_cell(0, 7, " 1. PARÂMETROS E METODOLOGIA (MEMORIAL DESCRITIVO)", 0, 1, 'L', True)
    pdf.ln(2)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    texto_explicativo = f"DATA BASE DO CÁLCULO: {dt_calc}\n\n"
    tipo_regime = config.get('tipo_regime', 'Padrao')
    
    if "Misto" in tipo_regime:
        dt_corte = config.get('data_corte').strftime("%d/%m/%Y") if config.get('data_corte') else "-"
        texto_explicativo += (
            f"METODOLOGIA APLICADA (Regime Misto - EC 113/21):\n"
            f"1. FASE PRÉ-SELIC (Até {dt_corte}): Correção monetária pelo índice original + Juros de Mora de 1% a.m.\n"
            f"2. FASE SELIC (De {dt_corte} até {dt_calc}): A Taxa SELIC incidiu exclusivamente sobre o PRINCIPAL CORRIGIDO (capital). "
            f"Os juros de mora acumulados na Fase 1 foram somados ao final para evitar anatocismo."
        )
    elif "SELIC" in tipo_regime:
        texto_explicativo += "METODOLOGIA APLICADA: Taxa SELIC Pura (Correção + Juros em fator único), conforme EC 113/21."
    else:
        texto_explicativo += "METODOLOGIA APLICADA (Padrão): Correção Monetária plena + Juros de Mora de 1% a.m. sobre o valor corrigido."

    pdf.set_font("Arial", "", 9)
    pdf.safe_multi_cell(0, 5, texto_explicativo)
    pdf.ln(5)

    # --- INDENIZAÇÃO ---
    if not dados_ind.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255)
        pdf.safe_cell(0, 7, " 2. DEMONSTRATIVO DE CÁLCULO - INDENIZAÇÃO", 0, 1, 'L', True)
        
        # --- LARGURAS CORRIGIDAS ---
        if "Misto" in tipo_regime:
            # Colunas reorganizadas e Fator SELIC aumentado para 45mm
            headers = [
                ("Vencimento", 25), 
                ("Valor Orig.", 25), 
                ("Fator CM", 22), 
                ("V. Corrigido", 28), 
                ("Juros F1", 25),
                ("Subtotal F1", 30),   # Nova coluna de controle
                ("Fator SELIC", 45),   # AUMENTADO para caber o texto "(S/ Princ.)"
                ("TOTAL", 35)
            ]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 
                      'Audit Juros %', 'Subtotal F1', 'Audit Fator SELIC', 'TOTAL']
        
        elif "SELIC" in tipo_regime:
            headers = [("Vencimento", 30), ("Valor Orig.", 35), ("Fator SELIC Acum.", 50), ("TOTAL", 40)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator SELIC', 'TOTAL']
            
        else: # Padrão
            headers = [
                ("Vencimento", 25), ("Valor Orig.", 25), ("Fator CM", 25), 
                ("V. Corrigido", 30), ("Juros %", 25), ("Valor Juros", 30), ("TOTAL", 35)
            ]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 
                      'Audit Juros %', 'Valor Juros', 'TOTAL']

        # Cabeçalho
        pdf.set_font("Arial", "B", 8)
        for txt, w in headers: pdf.safe_cell(w, 7, txt, 1, 0, 'C')
        pdf.ln()
        
        # Linhas
        pdf.set_font("Arial", "", 8)
        for _, row in dados_ind.iterrows():
            widths = [h[1] for h in headers]
            for i, campo in enumerate(campos):
                valor = str(row.get(campo, '-'))
                # Ajuste de fonte se texto for muito longo
                if len(valor) > 25: pdf.set_font("Arial", "", 7)
                else: pdf.set_font("Arial", "", 8)
                pdf.safe_cell(widths[i], 6, valor, 1, 0, 'C') 
            pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 8, f"Subtotal Indenização: {formatar_moeda(totais['indenizacao'])}", 0, 1, 'R')
        pdf.ln(3)

    # --- DEMAIS SEÇÕES ---
    if not dados_hon.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 240, 220)
        pdf.safe_cell(0, 7, " 3. HONORÁRIOS", 0, 1, 'L', True)
        pdf.set_font("Arial", "B", 8)
        cols_hon = [("Descrição", 80), ("Valor Orig.", 35), ("Fator/Juros", 40), ("TOTAL", 40)]
        for txt, w in cols_hon: pdf.safe_cell(w, 7, txt, 1, 0, 'C')
        pdf.ln()
        pdf.set_font("Arial", "", 8)
        for _, row in dados_hon.iterrows():
             pdf.safe_cell(80, 6, str(row['Descrição']), 1, 0, 'L')
             pdf.safe_cell(35, 6, str(row['Valor Orig.']), 1, 0, 'C')
             pdf.safe_cell(40, 6, f"{row.get('Audit Fator', '')} {row.get('Juros', '')}", 1, 0, 'C')
             pdf.safe_cell(40, 6, str(row['TOTAL']), 1, 0, 'C')
             pdf.ln()
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 8, f"Subtotal Honorários: {formatar_moeda(totais['honorarios'])}", 0, 1, 'R')
        pdf.ln(3)

    if not dados_pen.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 230, 230)
        pdf.safe_cell(0, 7, " 4. PENSÃO ALIMENTÍCIA", 0, 1, 'L', True)
        h_pen = [("Venc.", 25), ("Devido", 25), ("Pago", 25), ("Saldo", 25), 
                 ("Fator", 20), ("Atualizado", 25), ("Juros", 25), ("TOTAL", 30)]
        pdf.set_font("Arial", "B", 7)
        for h, w in h_pen: pdf.safe_cell(w, 6, h, 1, 0, 'C')
        pdf.ln()
        pdf.set_font("Arial", "", 7)
        for _, row in dados_pen.iterrows():
            vals = [row['Vencimento'], row['Valor Devido'], row['Valor Pago'], row['Base Cálculo'],
                    row['Fator CM'], row['Atualizado'], row['Juros'], row['TOTAL']]
            widths = [x[1] for x in h_pen]
            for i, v in enumerate(vals):
                pdf.safe_cell(widths[i], 6, str(v), 1, 0, 'C')
            pdf.ln()
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 7, f"Subtotal Pensão: {formatar_moeda(totais['pensao'])}", 0, 1, 'R')

    if dados_aluguel:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 255, 220) 
        pdf.safe_cell(0, 7, " REAJUSTE DE ALUGUEL", 0, 1, 'L', True)
        da = dados_aluguel
        pdf.set_font("Arial", "", 10)
        pdf.ln(2)
        pdf.safe_cell(50, 8, "Período / Índice", 1, 0, 'L')
        perc_txt = f"{(da['fator']-1)*100:.4f}%" if isinstance(da['fator'], (float, Decimal)) else str(da['fator'])
        pdf.safe_cell(140, 8, f"{da['periodo']} - {da['indice']} ({perc_txt})", 1, 1, 'L')
        pdf.set_font("Arial", "B", 12)
        pdf.safe_cell(30, 10, "NOVO:", 0, 0, 'R')
        pdf.safe_cell(50, 10, f"{formatar_moeda(da['novo_valor'])}", 0, 1, 'L')

    # --- RESUMO FINAL ---
    if totais['final'] > 0:
        pdf.ln(8)
        pdf.set_font("Arial", "B", 11)
        pdf.safe_cell(100, 8, "RESUMO DA EXECUÇÃO", "B", 1, 'L')
        pdf.ln(2)
        pdf.set_font("Arial", "", 10)
        pdf.safe_cell(140, 8, "Principal Atualizado (Total das Tabelas)", 0, 0)
        pdf.safe_cell(40, 8, formatar_moeda(totais['indenizacao'] + totais['honorarios'] + totais['pensao']), 0, 1, 'R')
        
        if config['multa_523']:
            pdf.safe_cell(140, 8, "Multa Art. 523 CPC (10%)", 0, 0)
            pdf.safe_cell(40, 8, formatar_moeda(totais['multa']), 0, 1, 'R')
        if config['hon_523']:
            pdf.safe_cell(140, 8, "Honorários Execução Art. 523 (10%)", 0, 0)
            pdf.safe_cell(40, 8, formatar_moeda(totais['hon_exec']), 0, 1, 'R')
            
        pdf.ln(4)
        pdf.set_font("Arial", "B", 14)
        pdf.set_fill_color(220, 220, 220)
        pdf.safe_cell(140, 12, "TOTAL GERAL DA DÍVIDA", 1, 0, 'L', True)
        pdf.safe_cell(40, 12, formatar_moeda(totais['final']), 1, 1, 'R', True)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 6. DADOS ESTÁTICOS ---
mapa_indices_completo = {
    "INPC (IBGE) - 188": 188, 
    "IGP-M (FGV) - 189": 189, 
    "IPCA (IBGE) - 433": 433,
    "IPCA-E (IBGE) - 10764": 10764, 
    "INCC-DI (FGV) - 192": 192, 
    "IGP-DI (FGV) - 190": 190,
    "IPC-Brasil (FGV) - 191": 191,
    "SELIC (Taxa Referencial) - 4390": 4390 
}
COD_SELIC = 4390

# ==============================================================================
# INTERFACE SIDEBAR
# ==============================================================================
st.sidebar.header("Parâmetros do Processo")
data_calculo = st.sidebar.date_input("Data do Cálculo (Data Base)", value=date.today(), format="DD/MM/YYYY")

st.sidebar.divider()
st.sidebar.markdown("### Penalidades Legais")
aplicar_multa_523 = st.sidebar.checkbox("Multa 10% (Art. 523 CPC)", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Honorários 10% (Art. 523 CPC)", value=False)

st.sidebar.divider()
with st.sidebar.expander("🛠️ Ferramentas Admin"):
    if st.button("Limpar Cache de Índices"):
        st.cache_data.clear()
        st.rerun()
    modo_simulacao = st.toggle("Simular Queda do BCB", value=False)
    if modo_simulacao != st.session_state.simular_erro_bcb:
        st.session_state.simular_erro_bcb = modo_simulacao
        st.cache_data.clear()
        st.rerun()
    if st.session_state.simular_erro_bcb:
        st.sidebar.error("ERRO BCB ATIVO")

# ==============================================================================
# NAVEGAÇÃO
# ==============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏢 Indenização/Cível", "⚖️ Honorários", "👶 Pensão Alimentícia", "🏠 Aluguel", "📊 Relatório PDF"])

with tab1:
    st.subheader("Cálculo de Indenização Cível / Dívidas")
    col_i1, col_i2, col_i3 = st.columns(3)
    valor_contrato = to_decimal(col_i1.number_input("Valor Base (R$)", value=1000.00, step=100.00))
    perc_indenizacao = to_decimal(col_i2.number_input("Percentual (%)", value=100.0, step=10.0))
    val_mensal = valor_contrato * (perc_indenizacao / Decimal('100'))
    col_i3.metric("Valor Mensal Calculado", formatar_moeda(val_mensal))
    st.write("---")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora/Evento", value=date(2021, 7, 10), format="DD/MM/YYYY")
    fim_atraso = c5.date_input("Fim da Mora (Última parcela)", value=date(2021, 7, 10), format="DD/MM/YYYY")
    
    regime_tipo = st.radio(
        "Regime de Atualização:",
        ["1. Índice Correção + Juros 1% a.m.", "2. Taxa SELIC Pura (EC 113/21)", "3. Misto (Índice até Corte -> SELIC)"],
        horizontal=True
    )
    
    indice_sel_ind = None
    data_corte_selic = None
    data_citacao_ind = None
    cod_ind_escolhido = None
    
    if "1. Índice" in regime_tipo:
        c_r1, c_r2 = st.columns(2)
        indice_sel_ind = c_r1.selectbox("Índice de Correção:", list(mapa_indices_completo.keys()))
        data_citacao_ind = c_r2.date_input("Data Citação (Início Juros)", value=inicio_atraso, format="DD/MM/YYYY")
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"{indice_sel_ind} + Juros 1% a.m."
    elif "3. Misto" in regime_tipo:
        st.info("Regime Misto: Correção até o corte, depois SELIC sobre o Principal.")
        c_mix1, c_mix2, c_mix3 = st.columns(3)
        indice_sel_ind = c_mix1.selectbox("Índice Fase 1:", list(mapa_indices_completo.keys()))
        data_citacao_ind = c_mix2.date_input("Data Citação", value=inicio_atraso, format="DD/MM/YYYY")
        data_corte_selic = c_mix3.date_input("Data Início SELIC", value=date(2021, 12, 9), format="DD/MM/YYYY")
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"Misto ({indice_sel_ind} -> SELIC)"
    else:
        desc_regime_txt = "Taxa SELIC"
        indice_sel_ind = "SELIC"

    if st.button("Calcular Indenização", type="primary"):
        st.session_state.params_relatorio = {
            'regime_desc': desc_regime_txt, 'tipo_regime': regime_tipo,
            'indice_nome': indice_sel_ind, 'data_corte': data_corte_selic,
            'data_citacao': data_citacao_ind, 'data_calculo': data_calculo
        }

        lista_resultados = []
        with st.status("Processando dados e conectando ao BCB...", expanded=True) as status:
            datas_vencimento = []
            if inicio_atraso == fim_atraso:
                datas_vencimento = [inicio_atraso]
            else:
                curr = inicio_atraso
                while curr <= fim_atraso:
                    datas_vencimento.append(curr)
                    prox_mes = curr.replace(day=1) + relativedelta(months=1)
                    dia_orig = inicio_atraso.day
                    try:
                        curr = prox_mes.replace(day=dia_orig)
                    except ValueError:
                        curr = prox_mes + relativedelta(day=31)
                    if curr > fim_atraso: break

            for venc in datas_vencimento:
                # Inicializa colunas para evitar erro no PDF se alguma ficar vazia
                linha = {
                    "Vencimento": venc.strftime("%d/%m/%Y"),
                    "Valor Orig.": formatar_moeda(val_mensal),
                    "Audit Fator CM": "-", "V. Corrigido Puro": "-",
                    "Audit Juros %": "-", "Valor Juros": "-", "Subtotal F1": "-",
                    "Audit Fator SELIC": "-", "Principal Atualizado": "-", "TOTAL": "-",
                    "_num": Decimal('0.00')
                }

                total_final = Decimal('0.00')

                # REGIME 1: PADRÃO
                if "1. Índice" in regime_tipo:
                    fator = buscar_fator_bcb(cod_ind_escolhido, venc, data_calculo)
                    if fator:
                        v_corrigido = val_mensal * fator
                        linha["Audit Fator CM"] = formatar_decimal_str(fator)
                        linha["V. Corrigido Puro"] = formatar_moeda(v_corrigido)
                        
                        dt_inicio_juros = data_citacao_ind if venc < data_citacao_ind else venc
                        dias_atraso = (data_calculo - dt_inicio_juros).days
                        
                        valor_juros = Decimal('0.00')
                        if dias_atraso > 0:
                            valor_juros = v_corrigido * ((Decimal('0.01') / Decimal('30')) * Decimal(dias_atraso))
                            linha["Audit Juros %"] = f"{(dias_atraso/30):.1f}%"
                            linha["Valor Juros"] = formatar_moeda(valor_juros)
                        
                        total_final = v_corrigido + valor_juros

                # REGIME 2: SELIC PURA
                elif "2. Taxa SELIC" in regime_tipo:
                    fator_selic = buscar_fator_bcb(COD_SELIC, venc, data_calculo)
                    if fator_selic:
                        total_final = val_mensal * fator_selic
                        linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                
                # REGIME 3: MISTO (LÓGICA AJUSTADA PARA O NOVO PDF)
                elif "3. Misto" in regime_tipo:
                    if venc >= data_corte_selic:
                        # Fase SELIC Pura (pós corte)
                        fator_selic = buscar_fator_bcb(COD_SELIC, venc, data_calculo)
                        if fator_selic:
                            total_final = val_mensal * fator_selic
                            linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                            linha["Principal Atualizado"] = formatar_moeda(total_final)
                            linha["Audit Juros %"] = "-"
                    else:
                        # Fase 1: Correção
                        f_fase1 = buscar_fator_bcb(cod_ind_escolhido, venc, data_corte_selic)
                        if f_fase1:
                            v_corr_f1 = val_mensal * f_fase1
                            linha["Audit Fator CM"] = f"{f_fase1:.6f}"
                            linha["V. Corrigido Puro"] = formatar_moeda(v_corr_f1)

                            # Juros (Congelados)
                            dt_j_f1 = data_citacao_ind if venc < data_citacao_ind else venc
                            if dt_j_f1 < data_corte_selic:
                                dias_f1 = (data_corte_selic - dt_j_f1).days
                                juros_f1 = v_corr_f1 * (Decimal('0.01')/Decimal('30') * Decimal(dias_f1))
                                linha["Audit Juros %"] = formatar_moeda(juros_f1)
                            else:
                                juros_f1 = Decimal('0.00')
                            
                            # Subtotal Fase 1 (para o PDF)
                            total_fase1 = v_corr_f1 + juros_f1
                            linha["Subtotal F1"] = formatar_moeda(total_fase1)

                            # Fase 2: SELIC apenas sobre o Principal
                            f_selic_f2 = buscar_fator_bcb(COD_SELIC, data_corte_selic, data_calculo)
                            if f_selic_f2:
                                princ_atualizado = v_corr_f1 * f_selic_f2
                                linha["Audit Fator SELIC"] = f"{f_selic_f2:.6f}"
                                linha["Principal Atualizado"] = formatar_moeda(princ_atualizado)
                                
                                # Total = Principal (com Selic) + Juros da Fase 1
                                total_final = princ_atualizado + juros_f1

                linha["TOTAL"] = formatar_moeda(total_final)
                linha["_num"] = total_final
                lista_resultados.append(linha)

            status.update(label="Concluído!", state="complete")
        
        df = pd.DataFrame(lista_resultados)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        
        st.success(f"Total: {formatar_moeda(st.session_state.total_indenizacao)}")
        # Remove colunas internas e formata para exibição
        cols_exibir = [c for c in df.columns if c != "_num"]
        st.dataframe(df[cols_exibir], use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Honorários")
    c_h1, c_h2 = st.columns(2)
    val_hon = to_decimal(c_h1.number_input("Valor Honorários", value=1500.00))
    data_hon = c_h2.date_input("Data Fixação", value=date(2023, 1, 1), format="DD/MM/YYYY")
    idx_hon = st.selectbox("Índice", list(mapa_indices_completo.keys()), index=0)
    aplica_juros_hon = st.checkbox("Aplicar Juros 1%?", value=True)
    if st.button("Calcular Hon."):
        fator = buscar_fator_bcb(mapa_indices_completo[idx_hon], data_hon, data_calculo)
        if fator:
            val_corr = val_hon * fator
            juros_val = Decimal('0.00')
            if aplica_juros_hon:
                dias = (data_calculo - data_hon).days
                if dias > 0: juros_val = val_corr * (Decimal('0.01')/Decimal('30') * Decimal(dias))
            total = val_corr + juros_val
            res = [{"Descrição": "Honorários", "Valor Orig.": formatar_moeda(val_hon), "Audit Fator": formatar_decimal_str(fator), "Juros": formatar_moeda(juros_val), "TOTAL": formatar_moeda(total), "_num": total}]
            st.session_state.df_honorarios = pd.DataFrame(res)
            st.session_state.total_honorarios = total
            st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), hide_index=True)

with tab3:
    st.subheader("Pensão Alimentícia")
    c_p1, c_p2, c_p3 = st.columns(3)
    p_val = to_decimal(c_p1.number_input("Valor Parcela", value=1000.00))
    p_ini = c_p2.date_input("Início", value=date(2023, 1, 1), format="DD/MM/YYYY")
    p_fim = c_p3.date_input("Fim", value=date.today(), format="DD/MM/YYYY")
    idx_pensao = st.selectbox("Índice Pensão", list(mapa_indices_completo.keys()))
    if st.button("1. Gerar Tabela"):
        dates = []
        curr = p_ini
        while curr <= p_fim:
            dates.append({"Vencimento": curr, "Valor Devido (R$)": float(p_val), "Valor Pago (R$)": 0.0})
            curr += relativedelta(months=1)
        st.session_state.df_pensao_input = pd.DataFrame(dates)
    
    tabela_editada = st.data_editor(st.session_state.df_pensao_input, num_rows="dynamic", use_container_width=True, hide_index=True, column_config={"Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"), "Valor Devido (R$)": st.column_config.NumberColumn(format="%.2f"), "Valor Pago (R$)": st.column_config.NumberColumn(format="%.2f")})

    if st.button("2. Calcular Saldo"):
        res_pensao = []
        cod = mapa_indices_completo[idx_pensao]
        for _, row in tabela_editada.iterrows():
            try:
                venc = pd.to_datetime(row["Vencimento"]).date()
                devido = to_decimal(row["Valor Devido (R$)"])
                pago = to_decimal(row["Valor Pago (R$)"])
                saldo = devido - pago
                if saldo <= 0:
                    res_pensao.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Valor Devido": formatar_moeda(devido), "Valor Pago": formatar_moeda(pago), "Base Cálculo": "QUITADO", "Fator CM": "-", "Atualizado": "-", "Juros": "-", "TOTAL": "R$ 0,00", "_num": Decimal('0.00')})
                else:
                    fator = buscar_fator_bcb(cod, venc, data_calculo)
                    if not fator: continue
                    atualizado = saldo * fator
                    dias = (data_calculo - venc).days
                    juros = atualizado * (Decimal('0.01')/Decimal('30') * Decimal(dias)) if dias > 0 else Decimal('0.00')
                    tot = atualizado + juros
                    res_pensao.append({"Vencimento": venc.strftime("%d/%m/%Y"), "Valor Devido": formatar_moeda(devido), "Valor Pago": formatar_moeda(pago), "Base Cálculo": formatar_moeda(saldo), "Fator CM": formatar_decimal_str(fator), "Atualizado": formatar_moeda(atualizado), "Juros": formatar_moeda(juros), "TOTAL": formatar_moeda(tot), "_num": tot})
            except: pass
        df_fin = pd.DataFrame(res_pensao)
        st.session_state.df_pensao_final = df_fin
        st.session_state.total_pensao = df_fin["_num"].sum() if not df_fin.empty else Decimal('0.00')
        st.success(f"Total: {formatar_moeda(st.session_state.total_pensao)}")
        if not df_fin.empty: st.dataframe(df_fin.drop(columns=["_num"]), use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Aluguel")
    ca1, ca2 = st.columns(2)
    alug_atual = to_decimal(ca1.number_input("Valor Atual", value=2000.00))
    dt_reaj = ca2.date_input("Data Reajuste", value=date.today())
    idx_a = st.selectbox("Índice Aluguel", list(mapa_indices_completo.keys()), index=1)
    if st.button("Calcular Reajuste"):
        dt_ini = dt_reaj - relativedelta(months=12)
        fator = buscar_fator_bcb(mapa_indices_completo[idx_a], dt_ini, dt_reaj)
        if fator:
            novo_val = alug_atual * fator
            st.session_state.dados_aluguel = {'valor_antigo': alug_atual, 'novo_valor': novo_val, 'indice': idx_a, 'periodo': f"{dt_ini.strftime('%d/%m/%Y')} a {dt_reaj.strftime('%d/%m/%Y')}", 'fator': fator}
            st.metric("Novo Aluguel", formatar_moeda(novo_val))

with tab5:
    st.header("Fechamento")
    subtotal = st.session_state.total_indenizacao + st.session_state.total_honorarios + st.session_state.total_pensao
    val_multa_523 = subtotal * Decimal('0.10') if aplicar_multa_523 else Decimal('0.00')
    val_hon_523 = subtotal * Decimal('0.10') if aplicar_hon_523 else Decimal('0.00')
    total_geral = subtotal + val_multa_523 + val_hon_523
    
    st.metric("TOTAL DA EXECUÇÃO", formatar_moeda(total_geral))
    
    totais_pdf = {'indenizacao': st.session_state.total_indenizacao, 'honorarios': st.session_state.total_honorarios, 'pensao': st.session_state.total_pensao, 'multa': val_multa_523, 'hon_exec': val_hon_523, 'final': total_geral}
    config_pdf = st.session_state.params_relatorio.copy()
    config_pdf.update({'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523})
    
    if st.button("📄 Baixar PDF"):
        pdf_bytes = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, st.session_state.dados_aluguel, totais_pdf, config_pdf)
        st.download_button(label="⬇️ Download PDF", data=pdf_bytes, file_name=f"Laudo_CalcJus_{date.today()}.pdf", mime="application/pdf")
