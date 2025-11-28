import streamlit as st
import pandas as pd
import requests
import calendar
import csv
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF
from decimal import Decimal, ROUND_HALF_UP, getcontext
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==============================================================================
# 1. CONFIGURAÇÃO FINANCEIRA E GLOBAL
# ==============================================================================
getcontext().prec = 28
DOIS_DECIMAIS = Decimal('0.01')

st.set_page_config(page_title="CalcJus Pro 4.9 (Final)", layout="wide", page_icon="⚖️")

st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.4rem; color: #0044cc; font-weight: bold; }
    .stAlert { padding: 0.5rem; border-radius: 8px; }
    thead tr th:first-child { display:none }
    tbody th { display:none }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ CalcJus PRO 4.9 - Sistema Completo")
st.markdown("Cálculo Pro Rata Die (Dias Exatos), Tabela TJSP (CSV) e API BCB Integrados.")

# ==============================================================================
# 2. ESTADO DA SESSÃO (Variáveis Globais)
# ==============================================================================
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

# ==============================================================================
# 3. CLASSES E FUNÇÕES DE CÁLCULO
# ==============================================================================

# --- CLASSE PARA LER O CSV DO TJSP ---
class CalculadoraTJSP:
    def __init__(self, arquivo_csv='tabela_tjsp.csv'):
        self.indices = {}
        self.carregar_dados(arquivo_csv)

    def carregar_dados(self, arquivo_csv):
        try:
            with open(arquivo_csv, mode='r', encoding='utf-8') as file:
                leitor = csv.DictReader(file)
                for linha in leitor:
                    if linha['fator']:
                        self.indices[linha['mes_ano']] = float(linha['fator'])
        except FileNotFoundError:
            # Apenas avisa no console, não trava o app
            print(f"AVISO: Arquivo {arquivo_csv} não encontrado.")
        except Exception as e:
            print(f"Erro CSV: {e}")

    def obter_fator(self, data_obj):
        chave = f"{data_obj.month:02d}/{data_obj.year}"
        return self.indices.get(chave)

    def calcular_fator_composto(self, data_venc, data_atualiz):
        idx_base = self.obter_fator(data_venc)
        idx_final = self.obter_fator(data_atualiz)
        if not idx_base or not idx_final: return None
        # Fórmula Tabela Prática: Fator Final / Fator Inicial
        return Decimal(str(idx_final)) / Decimal(str(idx_base))

# Instância Global da Calculadora TJSP
calc_tjsp = CalculadoraTJSP()

# --- FUNÇÕES UTILITÁRIAS ---
def to_decimal(valor):
    if not valor: return Decimal('0.00')
    try:
        if isinstance(valor, (float, int, Decimal)):
            return Decimal(str(valor))
        if isinstance(valor, str):
            valor = valor.strip()
            if ',' in valor:
                valor = valor.replace('.', '').replace(',', '.')
            return Decimal(str(valor))
    except:
        return Decimal('0.00')

def formatar_moeda(valor):
    try:
        if not isinstance(valor, Decimal): valor = to_decimal(valor)
        valor_ajustado = valor.quantize(DOIS_DECIMAIS, rounding=ROUND_HALF_UP)
        texto = f"R$ {valor_ajustado:,.2f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def formatar_decimal_str(valor):
    return f"{valor:.6f}"

# --- CONEXÃO BCB OTIMIZADA ---
@st.cache_data(ttl=3600, show_spinner=False)
def obter_dados_bcb_cache(codigo_serie, data_inicio, data_fim):
    if st.session_state.simular_erro_bcb: return None
    if codigo_serie == -1: return pd.DataFrame() # Código -1 é TJSP (CSV Local)

    if data_fim <= data_inicio or data_inicio > date.today():
        return pd.DataFrame()

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
            dados = response.json()
            if not dados: return pd.DataFrame()
            df = pd.DataFrame(dados)
            df['data_dt'] = pd.to_datetime(df['data'], format='%d/%m/%Y').dt.date
            def converter_fator(x):
                val_str = x.replace(',', '.') if isinstance(x, str) else str(x)
                return Decimal('1') + (Decimal(val_str) / Decimal('100'))
            df['fator_multi'] = df['valor'].apply(converter_fator)
            return df[['data_dt', 'fator_multi']]
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def calcular_fator_memoria(df_serie, dt_ini, dt_fim):
    if df_serie is None or df_serie.empty: return None
    mask = (df_serie['data_dt'] >= dt_ini) & (df_serie['data_dt'] <= dt_fim)
    subset = df_serie.loc[mask]
    if subset.empty: return None
    fator = Decimal('1.0')
    for val in subset['fator_multi']: fator *= val
    return fator

def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    # Se for TJSP (-1), usa a classe local. Se for BCB, usa API.
    if codigo_serie == -1: return calc_tjsp.calcular_fator_composto(data_inicio, data_fim)
    df = obter_dados_bcb_cache(codigo_serie, data_inicio, data_fim)
    if df is None or df.empty: return None
    return calcular_fator_memoria(df, data_inicio, data_fim)

# --- GERAÇÃO DE PDF ---
class PDFRelatorio(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 0, 0)
        self.cell(0, 5, 'RELATÓRIO DE CÁLCULO JUDICIAL (PRO RATA DIE)', 0, 1, 'C')
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
    
    # MEMORIAL
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.safe_cell(0, 7, " 1. MEMORIAL DESCRITIVO", 0, 1, 'L', True)
    pdf.ln(2)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    texto_explicativo = f"DATA BASE: {dt_calc}\nMETODOLOGIA: Juros calculados PRO RATA DIE (1% a.m. / 30 * dias corridos).\n\n"
    tipo_regime = config.get('tipo_regime', 'Padrao')
    
    if "Misto" in tipo_regime:
        dt_corte = config.get('data_corte').strftime("%d/%m/%Y") if config.get('data_corte') else "-"
        texto_explicativo += f"REGIME MISTO (EC 113/21): Fase 1 (Até {dt_corte}) Índice + Juros Pro Rata. Fase 2 (Pós) SELIC."
    elif "SELIC" in tipo_regime:
        texto_explicativo += "REGIME SELIC PURA (EC 113/21)."
    else:
        texto_explicativo += f"REGIME PADRÃO: Correção Monetária ({config.get('indice_nome')}) + Juros Moratórios Simples 1% a.m. (Pro Rata Die)."

    pdf.set_font("Arial", "", 9)
    pdf.safe_multi_cell(0, 5, texto_explicativo)
    pdf.ln(5)

    # INDENIZAÇÃO
    if not dados_ind.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255)
        pdf.safe_cell(0, 7, " 2. INDENIZAÇÃO (DETALHADO)", 0, 1, 'L', True)
        
        if "Misto" in tipo_regime:
            headers = [("Vencimento", 25), ("Valor Orig.", 25), ("Fator CM", 22), ("V. Corrigido", 28), ("Juros F1", 25), ("Subtotal F1", 30), ("Fator SELIC", 45), ("TOTAL", 35)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 'Audit Juros %', 'Subtotal F1', 'Audit Fator SELIC', 'TOTAL']
        elif "SELIC" in tipo_regime:
            headers = [("Vencimento", 30), ("Valor Orig.", 35), ("Fator SELIC Acum.", 50), ("TOTAL", 40)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator SELIC', 'TOTAL']
        else: 
            headers = [("Vencimento", 25), ("Valor Orig.", 25), ("Fator CM", 25), ("V. Corrigido", 30), ("Juros % (Dias)", 35), ("Valor Juros", 25), ("TOTAL", 35)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 'Audit Juros %', 'Valor Juros', 'TOTAL']

        pdf.set_font("Arial", "B", 8)
        for txt, w in headers: pdf.safe_cell(w, 7, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for _, row in dados_ind.iterrows():
            widths = [h[1] for h in headers]
            for i, campo in enumerate(campos):
                valor = str(row.get(campo, '-'))
                pdf.safe_cell(widths[i], 6, valor, 1, 0, 'C') 
            pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 8, f"Subtotal Indenização: {formatar_moeda(totais['indenizacao'])}", 0, 1, 'R')
        pdf.ln(3)

    # DEMAIS SEÇÕES (HONORÁRIOS, PENSÃO, ALUGUEL)
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
        pdf.safe_cell(0, 8, f"Subtotal: {formatar_moeda(totais['honorarios'])}", 0, 1, 'R')
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

    # RESUMO FINAL
    if totais['final'] > 0:
        pdf.ln(8)
        pdf.set_font("Arial", "B", 11)
        pdf.safe_cell(100, 8, "RESUMO DA EXECUÇÃO", "B", 1, 'L')
        pdf.ln(2)
        pdf.set_font("Arial", "", 10)
        pdf.safe_cell(140, 8, "Principal Atualizado", 0, 0)
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
        pdf.safe_cell(140, 12, "TOTAL GERAL", 1, 0, 'L', True)
        pdf.safe_cell(40, 12, formatar_moeda(totais['final']), 1, 1, 'R', True)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 4. DADOS ESTÁTICOS
# ==============================================================================
mapa_indices_completo = {
    "Tabela Prática TJSP (Oficial)": -1,
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
# 5. INTERFACE (SIDEBAR E ABAS)
# ==============================================================================
st.sidebar.header("Parâmetros do Processo")
data_calculo = st.sidebar.date_input("Data do Cálculo (Data Base)", value=date.today(), format="DD/MM/YYYY")

st.sidebar.divider()
st.sidebar.markdown("### Penalidades")
aplicar_multa_523 = st.sidebar.checkbox("Multa 10% (Art. 523 CPC)", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Honorários 10% (Art. 523 CPC)", value=False)

st.sidebar.divider()
with st.sidebar.expander("🛠️ Admin"):
    if st.button("Limpar Cache"):
        st.cache_data.clear()
        st.rerun()

# --- NAVEGAÇÃO ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏢 Indenização (Cível)", "⚖️ Honorários", "👶 Pensão", "🏠 Aluguel", "📊 PDF"])

# ABA 1: INDENIZAÇÃO
with tab1:
    st.subheader("Cálculo de Indenização (Pro Rata Die)")
    
    col_i1, col_i2, col_i3 = st.columns(3)
    valor_contrato = to_decimal(col_i1.number_input("Valor Base (R$)", value=1700.00, step=100.00))
    perc_indenizacao = to_decimal(col_i2.number_input("Percentual (%)", value=100.0, step=10.0))
    val_mensal = valor_contrato * (perc_indenizacao / Decimal('100'))
    col_i3.metric("Valor da Parcela", formatar_moeda(val_mensal))
    st.write("---")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 1, 21), format="DD/MM/YYYY")
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 9, 26), format="DD/MM/YYYY")
    
    # --- NOVO: SELETOR DE TERMO INICIAL DOS JUROS ---
    st.markdown("##### Configuração de Juros")
    tipo_termo_juros = st.radio(
        "Cobrar Juros a partir de:",
        ["Do Vencimento (Mora Ex Re)", "Da Citação (Mora Ex Personam)"],
        horizontal=True
    )
    # -----------------------------------------------

    regime_tipo = st.radio("Regime de Atualização:", ["1. Índice + Juros 1% (Pro Rata)", "2. SELIC (EC 113/21)", "3. Misto"], horizontal=True)
    
    indice_sel_ind = None
    data_corte_selic = None
    data_citacao_ind = None
    cod_ind_escolhido = None
    
    if "1. Índice" in regime_tipo:
        c_r1, c_r2 = st.columns(2)
        indice_sel_ind = c_r1.selectbox("Índice Correção:", list(mapa_indices_completo.keys()))
        
        # Se for pelo vencimento, a data da citação fica opcional
        if "Citação" in tipo_termo_juros:
            data_citacao_ind = c_r2.date_input("Data Citação", value=date.today())
        else:
            data_citacao_ind = None
            c_r2.info("Juros contados desde cada vencimento.")
            
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"{indice_sel_ind} + Juros 1% (Pro Rata)"

    elif "3. Misto" in regime_tipo:
        c_mix1, c_mix2, c_mix3 = st.columns(3)
        indice_sel_ind = c_mix1.selectbox("Índice Fase 1:", list(mapa_indices_completo.keys()))
        
        if "Citação" in tipo_termo_juros:
            data_citacao_ind = c_mix2.date_input("Data Citação", value=date(2024, 11, 11))
        else:
            data_citacao_ind = None
            c_mix2.info("Juros desde vencimento.")

        data_corte_selic = c_mix3.date_input("Início SELIC", value=date(2024, 11, 11))
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"Misto ({indice_sel_ind} -> SELIC)"
    else:
        desc_regime_txt = "Taxa SELIC"
        indice_sel_ind = "SELIC"

    if st.button("Calcular (Pro Rata)", type="primary"):
        st.session_state.params_relatorio = {
            'regime_desc': desc_regime_txt, 'tipo_regime': regime_tipo,
            'indice_nome': indice_sel_ind, 'data_corte': data_corte_selic,
            'data_citacao': data_citacao_ind, 'data_calculo': data_calculo
        }

        lista_resultados = []
        with st.status("Calculando Pro Rata Die...", expanded=True) as status:
            datas_vencimento = []
            if inicio_atraso == fim_atraso:
                datas_vencimento = [inicio_atraso]
            else:
                curr = inicio_atraso
                while curr <= fim_atraso:
                    datas_vencimento.append(curr)
                    prox_mes = curr.replace(day=1) + relativedelta(months=1)
                    try: curr = prox_mes.replace(day=inicio_atraso.day)
                    except: curr = prox_mes + relativedelta(day=31)
                    if curr > fim_atraso: break
            
            dt_min = min(datas_vencimento)
            df_ind = pd.DataFrame()
            if cod_ind_escolhido and cod_ind_escolhido != -1:
                df_ind = obter_dados_bcb_cache(cod_ind_escolhido, dt_min, data_calculo)
            elif cod_ind_escolhido == -1:
                status.write("Lendo Tabela TJSP Local...")
            
            df_selic = pd.DataFrame()
            if "SELIC" in regime_tipo or "Misto" in regime_tipo:
                dt_s = data_corte_selic if data_corte_selic else dt_min
                if dt_s > dt_min: dt_s = dt_min
                df_selic = obter_dados_bcb_cache(COD_SELIC, dt_s, data_calculo)

            for venc in datas_vencimento:
                linha = {
                    "Vencimento": venc.strftime("%d/%m/%Y"),
                    "Valor Orig.": formatar_moeda(val_mensal),
                    "Audit Fator CM": "-", "V. Corrigido Puro": "-",
                    "Audit Juros %": "-", "Valor Juros": "-", "Subtotal F1": "-",
                    "Audit Fator SELIC": "-", "Principal Atualizado": "-", "TOTAL": "-",
                    "_num": Decimal('0.00')
                }
                total_final = Decimal('0.00')

                # --- LÓGICA DE TERMO INICIAL DOS JUROS ---
                if "Vencimento" in tipo_termo_juros:
                    dt_inicio_juros_efetiva = venc
                else:
                    if data_citacao_ind:
                        dt_inicio_juros_efetiva = data_citacao_ind if venc < data_citacao_ind else venc
                    else:
                        dt_inicio_juros_efetiva = venc
                # ----------------------------------------

                # REGIME 1: Pro Rata (Lógica Principal)
                if "1. Índice" in regime_tipo:
                    if cod_ind_escolhido == -1: fator = calc_tjsp.calcular_fator_composto(venc, data_calculo)
                    else: fator = calcular_fator_memoria(df_ind, venc, data_calculo)
                    
                    if fator:
                        v_corr = val_mensal * fator
                        linha["Audit Fator CM"] = formatar_decimal_str(fator)
                        linha["V. Corrigido Puro"] = formatar_moeda(v_corr)
                        
                        dias_atraso = (data_calculo - dt_inicio_juros_efetiva).days
                        
                        val_jur = Decimal('0.00')
                        if dias_atraso > 0:
                            # CÁLCULO PRO RATA DIE EXATO: (1% / 30) * DIAS
                            taxa_dia = Decimal('0.01') / Decimal('30')
                            perc_total = taxa_dia * Decimal(dias_atraso)
                            val_jur = v_corr * perc_total
                            
                            perc_fmt = perc_total * 100
                            linha["Audit Juros %"] = f"{perc_fmt:.4f}% ({dias_atraso}d)"
                            linha["Valor Juros"] = formatar_moeda(val_jur)
                        
                        total_final = v_corr + val_jur

                elif "2. Taxa SELIC" in regime_tipo:
                    fs = calcular_fator_memoria(df_selic, venc, data_calculo)
                    if fs:
                        total_final = val_mensal * fs
                        linha["Audit Fator SELIC"] = formatar_decimal_str(fs)
                
                elif "3. Misto" in regime_tipo:
                    if venc >= data_corte_selic:
                        fs = calcular_fator_memoria(df_selic, venc, data_calculo)
                        if fs:
                            total_final = val_mensal * fs
                            linha["Audit Fator SELIC"] = formatar_decimal_str(fs)
                            linha["Principal Atualizado"] = formatar_moeda(total_final)
                    else:
                        if cod_ind_escolhido == -1: f1 = calc_tjsp.calcular_fator_composto(venc, data_corte_selic)
                        else: f1 = calcular_fator_memoria(df_ind, venc, data_corte_selic)
                        if f1:
                            vc1 = val_mensal * f1
                            linha["Audit Fator CM"] = f"{f1:.6f}"
                            linha["V. Corrigido Puro"] = formatar_moeda(vc1)
                            
                            dt_limite_juros = data_corte_selic
                            if dt_inicio_juros_efetiva < dt_limite_juros:
                                dias = (dt_limite_juros - dt_inicio_juros_efetiva).days
                                taxa = (Decimal('0.01')/Decimal('30')) * Decimal(dias)
                                j1 = vc1 * taxa
                                linha["Audit Juros %"] = f"{(taxa*100):.4f}% ({dias}d)"
                            else: 
                                j1 = Decimal('0.00')
                            
                            sub_f1 = vc1 + j1
                            linha["Subtotal F1"] = formatar_moeda(sub_f1)
                            
                            f2 = calcular_fator_memoria(df_selic, data_corte_selic, data_calculo)
                            if f2:
                                princ = vc1 * f2
                                linha["Audit Fator SELIC"] = f"{f2:.6f}"
                                linha["Principal Atualizado"] = formatar_moeda(princ)
                                total_final = princ + j1

                linha["TOTAL"] = formatar_moeda(total_final)
                linha["_num"] = total_final
                lista_resultados.append(linha)
            status.update(label="Concluído!", state="complete")
        
        df = pd.DataFrame(lista_resultados)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        
        st.success(f"Total: {formatar_moeda(st.session_state.total_indenizacao)}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ABA 2: HONORÁRIOS
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

# ABA 3: PENSÃO
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

# ABA 4: ALUGUEL
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

# ABA 5: FECHAMENTO
with tab5:
    st.header("Fechamento Geral")
    sub = st.session_state.total_indenizacao + st.session_state.total_honorarios + st.session_state.total_pensao
    m523 = sub * Decimal('0.10') if aplicar_multa_523 else Decimal('0.00')
    h523 = sub * Decimal('0.10') if aplicar_hon_523 else Decimal('0.00')
    final = sub + m523 + h523
    
    st.metric("TOTAL DA EXECUÇÃO", formatar_moeda(final))
    
    tp = {'indenizacao': st.session_state.total_indenizacao, 'honorarios': st.session_state.total_honorarios, 'pensao': st.session_state.total_pensao, 'multa': m523, 'hon_exec': h523, 'final': final}
    conf = st.session_state.params_relatorio.copy()
    conf.update({'multa_523': aplicar_multa_523, 'hon_523': aplicar_hon_523})
    
    if st.button("📄 Baixar Relatório PDF"):
        b = gerar_pdf_relatorio(st.session_state.df_indenizacao, st.session_state.df_honorarios, st.session_state.df_pensao_final, st.session_state.dados_aluguel, tp, conf)
        st.download_button("Download PDF", b, "Relatorio_ProRata.pdf", "application/pdf")
