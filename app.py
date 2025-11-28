import streamlit as st
import pandas as pd
import requests
import calendar
import csv
import io
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from fpdf import FPDF
from decimal import Decimal, ROUND_HALF_UP, getcontext
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. CONFIGURAÇÃO FINANCEIRA E GLOBAL ---
getcontext().prec = 28
DOIS_DECIMAIS = Decimal('0.01')

st.set_page_config(page_title="CalcJus Pro 4.8 (Pro-Rata)", layout="wide", page_icon="⚖️")

st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.4rem; color: #0044cc; font-weight: bold; }
    .stAlert { padding: 0.5rem; border-radius: 8px; }
    thead tr th:first-child { display:none }
    tbody th { display:none }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# INTERFACE SIDEBAR
# ==============================================================================
st.sidebar.header("Parâmetros do Processo")
data_calculo = st.sidebar.date_input("Data do Cálculo (Data Base)", value=date.today(), format="DD/MM/YYYY")

st.sidebar.divider()
st.sidebar.markdown("### 📂 Base de Dados (TJSP)")
arquivo_tjsp_upload = st.sidebar.file_uploader("Atualizar Tabela TJSP (.csv)", type=["csv"])

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
    if "simular_erro_bcb" not in st.session_state:
        st.session_state["simular_erro_bcb"] = False
    if modo_simulacao != st.session_state["simular_erro_bcb"]:
         st.session_state["simular_erro_bcb"] = modo_simulacao
         st.cache_data.clear()
         st.rerun()
    if st.session_state.simular_erro_bcb:
        st.sidebar.error("ERRO BCB ATIVO")

# --- 2. ESTADO DA SESSÃO ---
state_vars = {
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

# --- CLASSE PARA LER CSV ---
class CalculadoraTJSP:
    def __init__(self, arquivo_prioritario=None, arquivo_padrao='tabela_tjsp.csv'):
        self.indices = {}
        if arquivo_prioritario is not None:
            self.carregar_dados(arquivo_prioritario, eh_upload=True)
        else:
            self.carregar_dados(arquivo_padrao, eh_upload=False)

    def carregar_dados(self, arquivo, eh_upload=False):
        try:
            leitor = None
            if eh_upload:
                arquivo.seek(0)
                conteudo = arquivo.getvalue().decode('utf-8')
                f = io.StringIO(conteudo)
                leitor = csv.DictReader(f)
            else:
                try:
                    with open(arquivo, mode='r', encoding='utf-8') as f:
                        conteudo = f.read()
                    f_io = io.StringIO(conteudo)
                    leitor = csv.DictReader(f_io)
                except FileNotFoundError:
                    return 

            if leitor:
                for linha in leitor:
                    if 'fator' in linha and linha['fator']:
                        self.indices[linha['mes_ano']] = float(linha['fator'])
                        
        except Exception as e:
            print(f"Erro ao ler CSV TJSP: {e}")

    def obter_fator(self, data_obj):
        chave = f"{data_obj.month:02d}/{data_obj.year}"
        return self.indices.get(chave)

    def calcular_fator_composto(self, data_venc, data_atualiz):
        idx_base = self.obter_fator(data_venc)
        idx_final = self.obter_fator(data_atualiz)
        if not idx_base or not idx_final: return None
        return Decimal(str(idx_final)) / Decimal(str(idx_base))

calc_tjsp = CalculadoraTJSP(arquivo_prioritario=arquivo_tjsp_upload)

# --- 3. FUNÇÕES UTILITÁRIAS ---

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
        if not isinstance(valor, Decimal):
            valor = to_decimal(valor)
        valor_ajustado = valor.quantize(DOIS_DECIMAIS, rounding=ROUND_HALF_UP)
        texto = f"R$ {valor_ajustado:,.2f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def formatar_decimal_str(valor):
    return f"{valor:.6f}"

# --- 4. CONEXÃO BCB OTIMIZADA ---

@st.cache_data(ttl=3600, show_spinner=False)
def obter_dados_bcb_cache(codigo_serie, data_inicio, data_fim):
    if st.session_state.simular_erro_bcb: return None
    if codigo_serie == -1: return pd.DataFrame()

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
    for val in subset['fator_multi']:
        fator *= val
    return fator

def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    if codigo_serie == -1: 
        return calc_tjsp.calcular_fator_composto(data_inicio, data_fim)
    df = obter_dados_bcb_cache(codigo_serie, data_inicio, data_fim)
    if df is None or df.empty: return None
    return calcular_fator_memoria(df, data_inicio, data_fim)

# --- 5. GERAÇÃO DE PDF ---
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
    
    # MEMORIAL
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.safe_cell(0, 7, " 1. PARÂMETROS E METODOLOGIA (MEMORIAL DESCRITIVO)", 0, 1, 'L', True)
    pdf.ln(2)
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    texto_explicativo = f"DATA BASE DO CÁLCULO: {dt_calc}\n\n"
    tipo_regime = config.get('tipo_regime', 'Padrao')
    
    if "Misto" in tipo_regime:
        dt_corte = config.get('data_corte').strftime("%d/%m/%Y") if config.get('data_corte') else "-"
        texto_explicativo += (f"METODOLOGIA APLICADA (Regime Misto - EC 113/21):\n1. FASE PRÉ-SELIC (Até {dt_corte}): Correção monetária pelo índice original + Juros de Mora de 1% a.m.\n2. FASE SELIC (De {dt_corte} até {dt_calc}): A Taxa SELIC incidiu exclusivamente sobre o PRINCIPAL CORRIGIDO. Os juros de mora acumulados na Fase 1 foram somados ao final.")
    elif "SELIC" in tipo_regime:
        texto_explicativo += "METODOLOGIA APLICADA: Taxa SELIC Pura (Correção + Juros em fator único), conforme EC 113/21."
    else:
        texto_explicativo += "METODOLOGIA APLICADA (Padrão): Correção Monetária plena + Juros de Mora de 1% a.m. sobre o valor corrigido."

    pdf.set_font("Arial", "", 9)
    pdf.safe_multi_cell(0, 5, texto_explicativo)
    pdf.ln(5)

    # INDENIZAÇÃO
    if not dados_ind.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255)
        pdf.safe_cell(0, 7, " 2. DEMONSTRATIVO DE CÁLCULO - INDENIZAÇÃO", 0, 1, 'L', True)
        
        if "Misto" in tipo_regime:
            headers = [("Vencimento", 25), ("Valor Orig.", 25), ("Fator CM", 22), ("V. Corrigido", 28), ("Juros F1", 25), ("Subtotal F1", 30), ("Fator SELIC", 45), ("TOTAL", 35)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 'Audit Juros %', 'Subtotal F1', 'Audit Fator SELIC', 'TOTAL']
        elif "SELIC" in tipo_regime:
            headers = [("Vencimento", 30), ("Valor Orig.", 35), ("Fator SELIC Acum.", 50), ("TOTAL", 40)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator SELIC', 'TOTAL']
        else:
            headers = [("Vencimento", 25), ("Valor Orig.", 25), ("Fator CM", 25), ("V. Corrigido", 30), ("Juros %", 25), ("Valor Juros", 30), ("TOTAL", 35)]
            campos = ['Vencimento', 'Valor Orig.', 'Audit Fator CM', 'V. Corrigido Puro', 'Audit Juros %', 'Valor Juros', 'TOTAL']

        pdf.set_font("Arial", "B", 8)
        for txt, w in headers: pdf.safe_cell(w, 7, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for _, row in dados_ind.iterrows():
            widths = [h[1] for h in headers]
            for i, campo in enumerate(campos):
                valor = str(row.get(campo, '-'))
                pdf.safe_cell(widths[i], 6, valor, 1, 0, 'C') 
            pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 8, f"Subtotal Indenização: {formatar_moeda(totais['indenizacao'])}", 0, 1, 'R')
        pdf.ln(3)

    # (DEMAIS PARTES DO PDF SIMPLIFICADAS AQUI - JÁ ESTAVAM FUNCIONANDO)
    if not dados_hon.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.safe_cell(0, 7, " 3. HONORÁRIOS E DEMAIS", 0, 1, 'L', True)
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 8, f"Subtotal Honorários: {formatar_moeda(totais['honorarios'])}", 0, 1, 'R')
        pdf.ln(3)

    # RESUMO
    if totais['final'] > 0:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 14)
        pdf.set_fill_color(220, 220, 220)
        pdf.safe_cell(140, 12, "TOTAL GERAL DA DÍVIDA", 1, 0, 'L', True)
        pdf.safe_cell(40, 12, formatar_moeda(totais['final']), 1, 1, 'R', True)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 6. DADOS ESTÁTICOS ---
mapa_indices_completo = {
    "Tabela Prática TJSP (Oficial)": -1,
    "INPC (IBGE) - 188": 188, 
    "IGP-M (FGV) - 189": 189, 
    "IPCA (IBGE) - 433": 433,
    "IPCA-E (IBGE) - 10764": 10764, 
    "SELIC (Taxa Referencial) - 4390": 4390 
}
COD_SELIC = 4390

# ==============================================================================
# NAVEGAÇÃO
# ==============================================================================
st.title("⚖️ CalcJus PRO 4.8 - Com Tabela TJSP")
st.markdown("Cálculos Judiciais com Precisão Decimal, API BCB e Tabela Prática.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏢 Indenização (Pro-Rata)", "⚖️ Honorários", "👶 Pensão", "🏠 Aluguel", "📊 Relatório PDF"])

with tab1:
    st.subheader("Cálculo de Indenização Cível / Dívidas")
    col_i1, col_i2, col_i3 = st.columns(3)
    valor_contrato = to_decimal(col_i1.number_input("Valor Base (R$)", value=1000.00, step=100.00))
    perc_indenizacao = to_decimal(col_i2.number_input("Percentual (%)", value=100.0, step=10.0))
    val_mensal_cheio = valor_contrato * (perc_indenizacao / Decimal('100'))
    col_i3.metric("Valor Mensal (Cheio)", formatar_moeda(val_mensal_cheio))
    st.write("---")
    
    c4, c5 = st.columns(2)
    inicio_atraso = c4.date_input("Início da Mora/Evento", value=date(2024, 1, 21), format="DD/MM/YYYY")
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 9, 26), format="DD/MM/YYYY")
    
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
        with st.status("Processando dados (Pro-Rata)...", expanded=True) as status:
            
            # --- NOVA LÓGICA DE DATAS (PRO-RATA) ---
            datas_calc = []
            curr = inicio_atraso
            
            # Navega mês a mês até passar a data final
            while curr <= fim_atraso:
                # Último dia deste mês
                ultimo_dia_mes = calendar.monthrange(curr.year, curr.month)[1]
                data_fim_mes = date(curr.year, curr.month, ultimo_dia_mes)
                
                # O período neste mês termina no fim do mês OU na data final do contrato?
                data_encerramento_periodo = min(data_fim_mes, fim_atraso)
                
                # Cálculo de dias ativos neste mês
                dias_ativos = (data_encerramento_periodo - curr).days + 1
                dias_no_mes = ultimo_dia_mes
                
                # Verifica se é pro-rata
                eh_pro_rata = False
                valor_base_mes = val_mensal_cheio
                txt_pro_rata = "Integral"

                if dias_ativos < dias_no_mes:
                    eh_pro_rata = True
                    fator_pro = Decimal(dias_ativos) / Decimal(dias_no_mes)
                    valor_base_mes = val_mensal_cheio * fator_pro
                    txt_pro_rata = f"Pro-rata ({dias_ativos}/{dias_no_mes} dias)"

                datas_calc.append({
                    "vencimento": curr, # Data de início da vigência naquele mês
                    "valor_base": valor_base_mes,
                    "info_prorata": txt_pro_rata
                })
                
                # Avança para o dia 1 do próximo mês
                curr = data_fim_mes + timedelta(days=1)
            
            # --- BAIXA DADOS DO BCB ---
            # Define o range total necessário para API
            dt_minima_api = min([d['vencimento'] for d in datas_calc])
            
            df_indice_principal = pd.DataFrame()
            if cod_ind_escolhido and cod_ind_escolhido != -1:
                status.write(f"Baixando série histórica {indice_sel_ind}...")
                df_indice_principal = obter_dados_bcb_cache(cod_ind_escolhido, dt_minima_api, data_calculo)
            elif cod_ind_escolhido == -1:
                status.write("Acessando Tabela Prática TJSP...")
            
            df_selic_cache = pd.DataFrame()
            if "SELIC" in regime_tipo or "Misto" in regime_tipo:
                status.write("Baixando série histórica SELIC...")
                dt_inicio_selic = data_corte_selic if data_corte_selic else dt_minima_api
                if dt_inicio_selic > dt_minima_api: dt_inicio_selic = dt_minima_api
                df_selic_cache = obter_dados_bcb_cache(COD_SELIC, dt_inicio_selic, data_calculo)
            
            # --- LOOP DE CÁLCULO ---
            for item in datas_calc:
                venc = item['vencimento']
                val_base = item['valor_base']
                
                linha = {
                    "Vencimento": venc.strftime("%d/%m/%Y"),
                    "Pro-Rata": item['info_prorata'],
                    "Valor Orig.": formatar_moeda(val_base),
                    "Audit Fator CM": "-", "V. Corrigido Puro": "-",
                    "Audit Juros %": "-", "Valor Juros": "-", "Subtotal F1": "-",
                    "Audit Fator SELIC": "-", "Principal Atualizado": "-", "TOTAL": "-",
                    "_num": Decimal('0.00'),
                    "data_sort": venc
                }

                total_final = Decimal('0.00')

                # LÓGICA DE REGIMES (IGUAL ANTERIOR, MAS USANDO val_base JÁ PROPORCIONAL)
                if "1. Índice" in regime_tipo:
                    if cod_ind_escolhido == -1:
                         fator = calc_tjsp.calcular_fator_composto(venc, data_calculo)
                    else:
                         fator = calcular_fator_memoria(df_indice_principal, venc, data_calculo)
                    
                    if fator:
                        v_corrigido = val_base * fator
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

                elif "2. Taxa SELIC" in regime_tipo:
                    fator_selic = calcular_fator_memoria(df_selic_cache, venc, data_calculo)
                    if fator_selic:
                        total_final = val_base * fator_selic
                        linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                
                elif "3. Misto" in regime_tipo:
                    if venc >= data_corte_selic:
                        fator_selic = calcular_fator_memoria(df_selic_cache, venc, data_calculo)
                        if fator_selic:
                            total_final = val_base * fator_selic
                            linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                            linha["Principal Atualizado"] = formatar_moeda(total_final)
                            linha["Audit Juros %"] = "-"
                    else:
                        if cod_ind_escolhido == -1:
                             f_fase1 = calc_tjsp.calcular_fator_composto(venc, data_corte_selic)
                        else:
                             f_fase1 = calcular_fator_memoria(df_indice_principal, venc, data_corte_selic)

                        if f_fase1:
                            v_corr_f1 = val_base * f_fase1
                            linha["Audit Fator CM"] = f"{f_fase1:.6f}"
                            linha["V. Corrigido Puro"] = formatar_moeda(v_corr_f1)

                            dt_j_f1 = data_citacao_ind if venc < data_citacao_ind else venc
                            if dt_j_f1 < data_corte_selic:
                                dias_f1 = (data_corte_selic - dt_j_f1).days
                                juros_f1 = v_corr_f1 * (Decimal('0.01')/Decimal('30') * Decimal(dias_f1))
                                linha["Audit Juros %"] = formatar_moeda(juros_f1)
                            else:
                                juros_f1 = Decimal('0.00')
                            
                            total_fase1 = v_corr_f1 + juros_f1
                            linha["Subtotal F1"] = formatar_moeda(total_fase1)

                            f_selic_f2 = calcular_fator_memoria(df_selic_cache, data_corte_selic, data_calculo)
                            if f_selic_f2:
                                princ_atualizado = v_corr_f1 * f_selic_f2
                                linha["Audit Fator SELIC"] = f"{f_selic_f2:.6f}"
                                linha["Principal Atualizado"] = formatar_moeda(princ_atualizado)
                                total_final = princ_atualizado + juros_f1

                linha["TOTAL"] = formatar_moeda(total_final)
                linha["_num"] = total_final
                lista_resultados.append(linha)

            status.update(label="Concluído!", state="complete")
        
        df = pd.DataFrame(lista_resultados)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        
        st.success(f"Total: {formatar_moeda(st.session_state.total_indenizacao)}")
        
        if not df.empty:
            chart_data = df[['data_sort', '_num']].copy()
            chart_data = chart_data.rename(columns={'data_sort': 'Vencimento', '_num': 'Valor Atualizado'})
            chart_data['Valor Atualizado'] = chart_data['Valor Atualizado'].astype(float)
            st.area_chart(chart_data.set_index('Vencimento'))

        cols_exibir = [c for c in df.columns if c not in ["_num", "data_sort"]]
        st.dataframe(df[cols_exibir], use_container_width=True, hide_index=True)

with tab2:
    # (Mantido igual - omitido para brevidade, usar do código anterior se necessário, ou manter o seu)
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
    # (Código padrão mantido)
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
    # (Mantido padrão)
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
    
