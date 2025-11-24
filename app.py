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
# Define precisão global para evitar erros de dízima (padrão bancário)
getcontext().prec = 28
DOIS_DECIMAIS = Decimal('0.01')

# Configuração da Página
st.set_page_config(page_title="CalcJus Pro 4.1 (Final)", layout="wide", page_icon="⚖️")

# CSS Otimizado
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.4rem; color: #0044cc; font-weight: bold; }
    .stAlert { padding: 0.5rem; border-radius: 8px; }
    /* Esconde índices de tabelas para visual mais limpo */
    thead tr th:first-child { display:none }
    tbody th { display:none }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ CalcJus PRO 4.1 - Sistema Integrado")
st.markdown("Cálculos Judiciais com Precisão Decimal e Relatórios Detalhados.")

# --- 2. ESTADO DA SESSÃO (SESSION STATE) ---
# Inicializa variáveis para não dar erro ao abrir o app
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
    # Armazena os parâmetros exatos usados no último cálculo para o PDF
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

# --- 3. FUNÇÕES UTILITÁRIAS (ENGINE FINANCEIRA) ---

def to_decimal(valor):
    """Converte qualquer input (float, string, int) para Decimal de forma segura."""
    if not valor: return Decimal('0.00')
    try:
        if isinstance(valor, str):
            # Remove formatação brasileira (1.000,00 -> 1000.00)
            valor = valor.replace('.', '').replace(',', '.')
        return Decimal(str(valor))
    except:
        return Decimal('0.00')

def formatar_moeda(valor):
    """Formata Decimal para string BRL (R$ X.XXX,XX)."""
    try:
        if not isinstance(valor, Decimal):
            valor = to_decimal(valor)
        # Arredonda para 2 casas apenas para exibição
        valor_ajustado = valor.quantize(DOIS_DECIMAIS, rounding=ROUND_HALF_UP)
        texto = f"R$ {valor_ajustado:,.2f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def formatar_decimal_str(valor):
    """Retorna string do número com 6 casas decimais para auditoria."""
    return f"{valor:.6f}"

# --- 4. CONEXÃO ROBUSTA COM BANCO CENTRAL ---

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    """
    Busca séries do BCB com sistema de Retry (3 tentativas) e Backoff.
    Retorna um objeto Decimal ou None.
    """
    if st.session_state.simular_erro_bcb: return None

    # Validação de Datas
    if data_fim <= data_inicio or data_inicio > date.today():
        return Decimal('1.000000')
    
    d1 = data_inicio.strftime("%d/%m/%Y")
    d2 = data_fim.strftime("%d/%m/%Y")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={d1}&dataFinal={d2}"
    
    # Configuração de Retry (Segurança de Conexão)
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
                return None # Erro de parse JSON

            fator = Decimal('1.0')
            for item in dados:
                try:
                    val_raw = item['valor']
                    if isinstance(val_raw, str):
                        val_raw = val_raw.replace(',', '.')
                    
                    val_dec = Decimal(val_raw)
                    # Fórmula composta: Fator *= (1 + taxa/100)
                    fator *= (Decimal('1') + (val_dec / Decimal('100')))
                except:
                    continue
            return fator
        return None
    except Exception:
        return None

# --- 5. GERAÇÃO DE PDF PROFISSIONAL (COM MEMORIAL DESCRITIVO DETALHADO) ---
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
        """Imprime texto garantindo compatibilidade Latin-1 (evita travar com caracteres estranhos)"""
        try:
            txt_safe = str(txt).encode('latin-1', 'replace').decode('latin-1')
            self.cell(w, h, txt_safe, border, ln, align, fill)
        except:
            self.cell(w, h, "?", border, ln, align, fill)

    def safe_multi_cell(self, w, h, txt, border=0, align='J', fill=False):
        """MultiCell segura para textos longos"""
        try:
            txt_safe = str(txt).encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(w, h, txt_safe, border, align, fill)
        except:
            self.multi_cell(w, h, "Erro de caractere no texto descritivo.", border, align, fill)

def gerar_pdf_relatorio(dados_ind, dados_hon, dados_pen, dados_aluguel, totais, config):
    pdf = PDFRelatorio(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- 1. MEMORIAL DESCRITIVO DETALHADO ---
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240) # Cinza claro
    pdf.safe_cell(0, 7, " 1. PARÂMETROS E METODOLOGIA (MEMORIAL DESCRITIVO)", 0, 1, 'L', True)
    pdf.ln(2)
    
    dt_calc = config.get('data_calculo', date.today()).strftime('%d/%m/%Y')
    
    # Lógica para reconstruir o texto detalhado com as DATAS EXPLÍCITAS
    texto_explicativo = f"DATA BASE DO CÁLCULO: {dt_calc}\n\n"
    
    tipo_regime = config.get('tipo_regime', 'Padrao')
    indice_nome = config.get('indice_nome', 'Índice Oficial')
    
    if "Misto" in tipo_regime:
        # Recupera as datas salvas para exibir no texto
        dt_corte = config.get('data_corte').strftime("%d/%m/%Y") if config.get('data_corte') else "-"
        dt_cit = config.get('data_citacao').strftime("%d/%m/%Y") if config.get('data_citacao') else "-"
        
        texto_explicativo += (
            f"METODOLOGIA APLICADA (Regime Misto - EC 113/21):\n"
            f"O cálculo foi realizado em duas etapas distintas para atender à legislação vigente:\n"
            f"1. FASE PRÉ-SELIC (Do vencimento até {dt_corte}): O valor original foi corrigido monetariamente pelo índice '{indice_nome}'. "
            f"Sobre este valor corrigido, aplicaram-se Juros de Mora de 1% a.m. (simples e pro-rata die) contados a partir de {dt_cit} até a data de corte.\n"
            f"2. FASE SELIC (De {dt_corte} até {dt_calc}): O montante total acumulado na Fase 1 foi consolidado e, a partir desta data ({dt_corte}), "
            f"atualizado exclusivamente pela variação da Taxa SELIC, vedada a cumulação com outros índices."
        )
    elif "SELIC" in tipo_regime:
        texto_explicativo += (
            f"METODOLOGIA APLICADA (Taxa SELIC Pura - EC 113/21):\n"
            f"O valor original foi atualizado exclusivamente pela Taxa SELIC acumulada desde a data do vencimento (ou evento danoso) até a data base atual ({dt_calc}). "
            f"Conforme jurisprudência do STJ e a Emenda Constitucional 113/21, a Taxa SELIC engloba juros de mora e correção monetária em um único fator."
        )
    else: # Padrão
        dt_cit = config.get('data_citacao').strftime("%d/%m/%Y") if config.get('data_citacao') else "-"
        texto_explicativo += (
            f"METODOLOGIA APLICADA (Padrão Cível):\n"
            f"1. CORREÇÃO MONETÁRIA: O valor original foi atualizado pelo índice '{indice_nome}' desde a data do vencimento até a data base ({dt_calc}).\n"
            f"2. JUROS DE MORA: Foram aplicados juros moratórios de 1% ao mês (juros simples), calculados de forma pro-rata die (proporcional aos dias), "
            f"incidindo sobre o valor corrigido, contados a partir de {dt_cit}."
        )

    pdf.set_font("Arial", "", 9)
    pdf.safe_multi_cell(0, 5, texto_explicativo)
    pdf.ln(5)

    # --- 2. INDENIZAÇÃO (TABELA COM COLUNAS CORRETAS) ---
    if not dados_ind.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 230, 255) # Azul claro
        pdf.safe_cell(0, 7, " 2. INDENIZAÇÃO / DÍVIDAS CÍVEIS", 0, 1, 'L', True)
        
        # Colunas conforme solicitação: Venc | Valor Orig | Fator CM | V. Corr | Juros | Subtotal F1 | Fator SELIC | TOTAL
        headers = [("Vencimento", 22), ("Valor Orig.", 25), ("Fator CM", 20), 
                   ("V. Corrigido", 25), ("Juros Mora", 35), ("Subtotal F1", 25), 
                   ("Fator SELIC", 20), ("TOTAL", 30)]
        
        pdf.set_font("Arial", "B", 7)
        for txt, w in headers: pdf.safe_cell(w, 6, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for _, row in dados_ind.iterrows():
            dados = [
                str(row['Vencimento']), str(row['Valor Orig.']), str(row.get('Audit Fator CM', '-')),
                str(row.get('V. Corrigido Puro', '-')), str(row.get('Audit Juros %', '-')), 
                str(row.get('Total Fase 1', '-')), str(row.get('Audit Fator SELIC', '-')), 
                str(row['TOTAL'])
            ]
            widths = [h[1] for h in headers]
            for i, d in enumerate(dados):
                align = 'L' if i == 4 else 'C' # Juros alinhado a esquerda
                pdf.safe_cell(widths[i], 6, d, 1, 0, align)
            pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 7, f"Subtotal Indenização: {formatar_moeda(totais['indenizacao'])}", 0, 1, 'R')
        pdf.ln(3)

    # --- 3. HONORÁRIOS ---
    if not dados_hon.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(220, 240, 220) # Verde claro
        pdf.safe_cell(0, 7, " 3. HONORÁRIOS DE SUCUMBÊNCIA", 0, 1, 'L', True)
        pdf.set_font("Arial", "B", 7)
        
        cols_hon = [("Descrição", 60), ("Valor Orig.", 30), ("Fator/Índice", 40), ("Juros", 40), ("TOTAL", 40)]
        for txt, w in cols_hon: pdf.safe_cell(w, 6, txt, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font("Arial", "", 8)
        for _, row in dados_hon.iterrows():
             pdf.safe_cell(60, 6, str(row['Descrição']), 1, 0, 'L')
             pdf.safe_cell(30, 6, str(row['Valor Orig.']), 1, 0, 'C')
             pdf.safe_cell(40, 6, str(row.get('Audit Fator', '-')), 1, 0, 'C')
             pdf.safe_cell(40, 6, str(row.get('Juros', '-')), 1, 0, 'C')
             pdf.safe_cell(40, 6, str(row['TOTAL']), 1, 0, 'C')
             pdf.ln()
        
        pdf.set_font("Arial", "B", 9)
        pdf.safe_cell(0, 7, f"Subtotal Honorários: {formatar_moeda(totais['honorarios'])}", 0, 1, 'R')
        pdf.ln(3)

    # --- 4. PENSÃO ---
    if not dados_pen.empty:
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 230, 230) # Rosa claro
        pdf.safe_cell(0, 7, " 4. PENSÃO ALIMENTÍCIA (DÉBITOS)", 0, 1, 'L', True)
        
        h_pen = [("Vencimento", 25), ("Devido", 25), ("Pago", 25), ("Saldo Base", 25), 
                 ("Fator CM", 20), ("Atualizado", 25), ("Juros", 25), ("TOTAL", 30)]
        
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

    # --- 5. ALUGUEL ---
    if dados_aluguel:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.set_fill_color(255, 255, 220) 
        pdf.safe_cell(0, 7, " DEMONSTRATIVO DE REAJUSTE DE ALUGUEL", 0, 1, 'L', True)
        da = dados_aluguel
        pdf.set_font("Arial", "", 10)
        pdf.ln(2)
        pdf.safe_cell(50, 8, "Item", 1, 0, 'C')
        pdf.safe_cell(100, 8, "Detalhe", 1, 1, 'C')
        pdf.safe_cell(50, 8, "Valor Atual", 1, 0, 'L')
        pdf.safe_cell(100, 8, f"{formatar_moeda(da['valor_antigo'])}", 1, 1, 'R')
        pdf.safe_cell(50, 8, "Índice Aplicado", 1, 0, 'L')
        
        perc_txt = f"{(da['fator']-1)*100:.4f}%" if isinstance(da['fator'], (float, Decimal)) else str(da['fator'])
        pdf.safe_cell(100, 8, f"{da['indice']} (Acumulado: {perc_txt})", 1, 1, 'R')
        
        pdf.safe_cell(50, 8, "Período", 1, 0, 'L')
        pdf.safe_cell(100, 8, da['periodo'], 1, 1, 'R')
        pdf.set_font("Arial", "B", 12)
        pdf.safe_cell(50, 10, "NOVO ALUGUEL", 1, 0, 'L')
        pdf.safe_cell(100, 10, f"{formatar_moeda(da['novo_valor'])}", 1, 1, 'R')

    # --- 6. RESUMO FINAL ---
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
        pdf.set_fill_color(220, 220, 220) # Cinza destaque
        
        # Borda em volta do total
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

# ==============================================================================
# ABA 1: INDENIZAÇÃO (LÓGICA BLINDADA COM DATAS NO REPORT)
# ==============================================================================
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
        "Regime de Atualização (Jurisprudência):",
        ["1. Índice Correção + Juros 1% a.m.", "2. Taxa SELIC Pura (EC 113/21)", "3. Misto (Índice até Corte -> SELIC)"],
        horizontal=True
    )
    
    # Variáveis locais para inputs
    indice_sel_ind = None
    data_corte_selic = None
    data_citacao_ind = None
    cod_ind_escolhido = None
    
    # Configuração Dinâmica dos Inputs Baseado no Regime
    if "1. Índice" in regime_tipo:
        c_r1, c_r2 = st.columns(2)
        indice_sel_ind = c_r1.selectbox("Índice de Correção:", list(mapa_indices_completo.keys()))
        data_citacao_ind = c_r2.date_input("Data Citação (Início Juros)", value=inicio_atraso, format="DD/MM/YYYY")
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"{indice_sel_ind} + Juros 1% a.m."
        
    elif "3. Misto" in regime_tipo:
        st.info("Regime Misto: Corrige pelo índice até a Data de Corte (ex: promulgação da EC 113), e aplica SELIC depois.")
        c_mix1, c_mix2, c_mix3 = st.columns(3)
        indice_sel_ind = c_mix1.selectbox("Índice Fase 1:", list(mapa_indices_completo.keys()))
        data_citacao_ind = c_mix2.date_input("Data Citação", value=inicio_atraso, format="DD/MM/YYYY")
        data_corte_selic = c_mix3.date_input("Data Início SELIC", value=date(2021, 12, 9), format="DD/MM/YYYY")
        cod_ind_escolhido = mapa_indices_completo[indice_sel_ind]
        desc_regime_txt = f"Misto ({indice_sel_ind} -> SELIC em {data_corte_selic.strftime('%d/%m/%Y')})"
    else:
        desc_regime_txt = "Taxa SELIC (Correção + Juros)"
        indice_sel_ind = "SELIC" # Placeholder

    if st.button("Calcular Indenização", type="primary"):
        # 1. SALVAR PARÂMETROS PARA O PDF (Estado Global)
        st.session_state.params_relatorio = {
            'regime_desc': desc_regime_txt,
            'tipo_regime': regime_tipo,
            'indice_nome': indice_sel_ind,
            'data_corte': data_corte_selic,
            'data_citacao': data_citacao_ind,
            'data_calculo': data_calculo
        }

        lista_resultados = []
        
        with st.status("Processando dados e conectando ao BCB...", expanded=True) as status:
            # Geração das datas de vencimento
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

            # Loop de Cálculo (Usando Decimal)
            for venc in datas_vencimento:
                linha = {
                    "Vencimento": venc.strftime("%d/%m/%Y"),
                    "Valor Orig.": formatar_moeda(val_mensal),
                    "Audit Fator CM": "-", "V. Corrigido Puro": "-",
                    "Audit Juros %": "-", "Total Fase 1": "-",
                    "Audit Fator SELIC": "-", "TOTAL": "-",
                    "_num": Decimal('0.00')
                }

                total_final = Decimal('0.00')

                # REGIME 1: PADRÃO (Índice + Juros)
                if "1. Índice" in regime_tipo:
                    fator = buscar_fator_bcb(cod_ind_escolhido, venc, data_calculo)
                    if fator is None:
                        st.error(f"Falha ao obter índice para {venc}"); st.stop()
                    
                    v_corrigido = val_mensal * fator
                    linha["Audit Fator CM"] = formatar_decimal_str(fator)
                    linha["V. Corrigido Puro"] = formatar_moeda(v_corrigido)
                    
                    dt_inicio_juros = data_citacao_ind if venc < data_citacao_ind else venc
                    dias_atraso = (data_calculo - dt_inicio_juros).days
                    
                    if dias_atraso > 0:
                        fator_juros = (Decimal('0.01') / Decimal('30')) * Decimal(dias_atraso)
                        valor_juros = v_corrigido * fator_juros
                        linha["Audit Juros %"] = f"{(dias_atraso/30):.1f}% ({dias_atraso}d)"
                    else:
                        valor_juros = Decimal('0.00')
                        linha["Audit Juros %"] = "0%"

                    total_final = v_corrigido + valor_juros
                    linha["Total Fase 1"] = formatar_moeda(total_final)

                # REGIME 2: SELIC PURA
                elif "2. Taxa SELIC" in regime_tipo:
                    fator_selic = buscar_fator_bcb(COD_SELIC, venc, data_calculo)
                    if fator_selic is None: st.error("Erro SELIC"); st.stop()
                    
                    total_final = val_mensal * fator_selic
                    linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                
                # REGIME 3: MISTO
                elif "3. Misto" in regime_tipo:
                    if venc >= data_corte_selic:
                        # Cai direto na SELIC
                        fator_selic = buscar_fator_bcb(COD_SELIC, venc, data_calculo)
                        if fator_selic is None: st.error("Erro SELIC"); st.stop()
                        total_final = val_mensal * fator_selic
                        linha["Audit Fator SELIC"] = formatar_decimal_str(fator_selic)
                    else:
                        # FASE 1: Correção até Corte
                        f_fase1 = buscar_fator_bcb(cod_ind_escolhido, venc, data_corte_selic)
                        if f_fase1 is None: st.error("Erro Fase 1"); st.stop()
                        
                        v_corr_f1 = val_mensal * f_fase1
                        linha["Audit Fator CM"] = f"{f_fase1:.6f} (F1)"
                        linha["V. Corrigido Puro"] = formatar_moeda(v_corr_f1)

                        # Juros Fase 1 (Do vencimento/citação até corte)
                        dt_j_f1 = data_citacao_ind if venc < data_citacao_ind else venc
                        if dt_j_f1 < data_corte_selic:
                            dias_f1 = (data_corte_selic - dt_j_f1).days
                            juros_f1 = v_corr_f1 * (Decimal('0.01')/Decimal('30') * Decimal(dias_f1))
                            linha["Audit Juros %"] = f"R$ {juros_f1:,.2f} (F1)"
                        else:
                            juros_f1 = Decimal('0.00')
                        
                        total_fase1 = v_corr_f1 + juros_f1
                        linha["Total Fase 1"] = formatar_moeda(total_fase1)

                        # FASE 2: SELIC do Corte até Hoje sobre o montante acumulado
                        f_selic_f2 = buscar_fator_bcb(COD_SELIC, data_corte_selic, data_calculo)
                        if f_selic_f2 is None: st.error("Erro SELIC F2"); st.stop()
                        
                        total_final = total_fase1 * f_selic_f2
                        linha["Audit Fator SELIC"] = formatar_decimal_str(f_selic_f2)

                linha["TOTAL"] = formatar_moeda(total_final)
                linha["_num"] = total_final
                lista_resultados.append(linha)

            status.update(label="Cálculo Concluído!", state="complete")
        
        df = pd.DataFrame(lista_resultados)
        st.session_state.df_indenizacao = df
        st.session_state.total_indenizacao = df["_num"].sum()
        
        st.success(f"Total Atualizado: {formatar_moeda(st.session_state.total_indenizacao)}")
        st.dataframe(df.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 2: HONORÁRIOS
# ==============================================================================
with tab2:
    st.subheader("Honorários de Sucumbência")
    c_h1, c_h2 = st.columns(2)
    val_hon = to_decimal(c_h1.number_input("Valor Original dos Honorários", value=1500.00))
    data_hon = c_h2.date_input("Data Base (Fixação/Sentença)", value=date(2023, 1, 1), format="DD/MM/YYYY")
    
    idx_hon = st.selectbox("Índice de Atualização", list(mapa_indices_completo.keys()), index=0)
    aplica_juros_hon = st.checkbox("Aplicar Juros de Mora (1% a.m.)?", value=True)
    
    if st.button("Calcular Honorários"):
        fator = buscar_fator_bcb(mapa_indices_completo[idx_hon], data_hon, data_calculo)
        
        if fator:
            val_corr = val_hon * fator
            juros_val = Decimal('0.00')
            desc_juros = "Não"
            
            if aplica_juros_hon:
                dias = (data_calculo - data_hon).days
                if dias > 0:
                    juros_val = val_corr * (Decimal('0.01')/Decimal('30') * Decimal(dias))
                    desc_juros = formatar_moeda(juros_val)
            
            total = val_corr + juros_val
            
            res = [{
                "Descrição": "Honorários",
                "Valor Orig.": formatar_moeda(val_hon),
                "Audit Fator": formatar_decimal_str(fator),
                "Juros": desc_juros,
                "TOTAL": formatar_moeda(total),
                "_num": total
            }]
            st.session_state.df_honorarios = pd.DataFrame(res)
            st.session_state.total_honorarios = total
            st.success(f"Total Honorários: {formatar_moeda(total)}")
            st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), hide_index=True)
        else:
            st.error("Erro ao buscar índices.")

# ==============================================================================
# ABA 3: PENSÃO
# ==============================================================================
with tab3:
    st.subheader("Cálculo de Débito Alimentar")
    st.info("Fluxo: 1. Gere a tabela. 2. Preencha os valores pagos. 3. Clique em Calcular.")
    
    c_p1, c_p2, c_p3 = st.columns(3)
    p_val = to_decimal(c_p1.number_input("Valor da Parcela (R$)", value=1000.00))
    p_ini = c_p2.date_input("Início Período", value=date(2023, 1, 1), format="DD/MM/YYYY")
    p_fim = c_p3.date_input("Fim Período", value=date.today(), format="DD/MM/YYYY")
    idx_pensao = st.selectbox("Índice Correção Pensão", list(mapa_indices_completo.keys()))
    
    if st.button("1. Gerar Tabela para Preenchimento"):
        dates = []
        curr = p_ini
        while curr <= p_fim:
            dates.append({
                "Vencimento": curr, 
                "Valor Devido (R$)": float(p_val), # Float para o editor do streamlit (visual)
                "Valor Pago (R$)": 0.0
            })
            curr += relativedelta(months=1)
        st.session_state.df_pensao_input = pd.DataFrame(dates)

    tabela_editada = st.data_editor(
        st.session_state.df_pensao_input, 
        num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
            "Valor Devido (R$)": st.column_config.NumberColumn(format="%.2f"),
            "Valor Pago (R$)": st.column_config.NumberColumn(format="%.2f")
        }
    )

    if st.button("2. Calcular Saldo Devedor"):
        res_pensao = []
        cod = mapa_indices_completo[idx_pensao]
        
        with st.spinner("Calculando linha a linha..."):
            for _, row in tabela_editada.iterrows():
                try:
                    venc = pd.to_datetime(row["Vencimento"]).date()
                    devido = to_decimal(row["Valor Devido (R$)"])
                    pago = to_decimal(row["Valor Pago (R$)"])
                    
                    saldo = devido - pago
                    
                    if saldo <= 0:
                        res_pensao.append({
                            "Vencimento": venc.strftime("%d/%m/%Y"),
                            "Valor Devido": formatar_moeda(devido),
                            "Valor Pago": formatar_moeda(pago),
                            "Base Cálculo": "QUITADO",
                            "Fator CM": "-", "Atualizado": "-", "Juros": "-",
                            "TOTAL": "R$ 0,00", "_num": Decimal('0.00')
                        })
                    else:
                        fator = buscar_fator_bcb(cod, venc, data_calculo)
                        if not fator: continue
                        
                        atualizado = saldo * fator
                        
                        dias = (data_calculo - venc).days
                        juros = Decimal('0.00')
                        if dias > 0:
                            juros = atualizado * (Decimal('0.01')/Decimal('30') * Decimal(dias))
                        
                        tot = atualizado + juros
                        res_pensao.append({
                            "Vencimento": venc.strftime("%d/%m/%Y"),
                            "Valor Devido": formatar_moeda(devido),
                            "Valor Pago": formatar_moeda(pago),
                            "Base Cálculo": formatar_moeda(saldo),
                            "Fator CM": formatar_decimal_str(fator),
                            "Atualizado": formatar_moeda(atualizado),
                            "Juros": formatar_moeda(juros),
                            "TOTAL": formatar_moeda(tot),
                            "_num": tot
                        })
                except Exception as e:
                    st.error(f"Erro na linha {row}: {e}")
        
        df_fin = pd.DataFrame(res_pensao)
        st.session_state.df_pensao_final = df_fin
        st.session_state.total_pensao = df_fin["_num"].sum() if not df_fin.empty else Decimal('0.00')
        
        st.success(f"Dívida Alimentar Total: {formatar_moeda(st.session_state.total_pensao)}")
        if not df_fin.empty:
            st.dataframe(df_fin.drop(columns=["_num"]), use_container_width=True, hide_index=True)

# ==============================================================================
# ABA 4: ALUGUEL
# ==============================================================================
with tab4:
    st.subheader("Reajuste Anual de Aluguel")
    ca1, ca2 = st.columns(2)
    alug_atual = to_decimal(ca1.number_input("Valor Atual", value=2000.00))
    dt_reaj = ca2.date_input("Data Aniversário", value=date.today())
    idx_a = st.selectbox("Índice", list(mapa_indices_completo.keys()), index=1)
    
    if st.button("Calcular Reajuste"):
        dt_ini = dt_reaj - relativedelta(months=12)
        fator = buscar_fator_bcb(mapa_indices_completo[idx_a], dt_ini, dt_reaj)
        
        if fator:
            novo_val = alug_atual * fator
            perc = (fator - 1) * 100
            
            st.session_state.dados_aluguel = {
                'valor_antigo': alug_atual, 'novo_valor': novo_val,
                'indice': idx_a, 'periodo': f"{dt_ini.strftime('%d/%m/%Y')} a {dt_reaj.strftime('%d/%m/%Y')}",
                'fator': fator
            }
            
            c_res1, c_res2 = st.columns(2)
            c_res1.metric("Novo Aluguel", formatar_moeda(novo_val))
            c_res2.metric("Percentual Acumulado", f"{perc:.4f}%")
        else:
            st.error("Erro ao buscar índice.")

# ==============================================================================
# ABA 5: PDF E FECHAMENTO
# ==============================================================================
with tab5:
    st.header("Fechamento do Cálculo")
    
    t1 = st.session_state.total_indenizacao
    t2 = st.session_state.total_honorarios
    t3 = st.session_state.total_pensao
    
    subtotal = t1 + t2 + t3
    
    val_multa_523 = subtotal * Decimal('0.10') if aplicar_multa_523 else Decimal('0.00')
    val_hon_523 = subtotal * Decimal('0.10') if aplicar_hon_523 else Decimal('0.00')
    
    total_geral = subtotal + val_multa_523 + val_hon_523
    
    st.metric("TOTAL DA EXECUÇÃO (BRUTO)", formatar_moeda(total_geral))
    
    col_detalhes = st.expander("Ver Detalhes dos Totais", expanded=True)
    col_detalhes.write(f"Soma Principal: {formatar_moeda(subtotal)}")
    if aplicar_multa_523: col_detalhes.write(f"+ Multa 10%: {formatar_moeda(val_multa_523)}")
    if aplicar_hon_523: col_detalhes.write(f"+ Hon. Execução 10%: {formatar_moeda(val_hon_523)}")
    
    # Prepara o PDF usando os dados salvos na sessão (garante que as datas venham da aba 1)
    totais_pdf = {
        'indenizacao': t1, 'honorarios': t2, 'pensao': t3,
        'multa': val_multa_523, 'hon_exec': val_hon_523, 'final': total_geral
    }
    
    # Recupera parâmetros salvos (para não perder se o usuário trocou de aba)
    config_pdf = st.session_state.params_relatorio.copy()
    config_pdf.update({
        'multa_523': aplicar_multa_523,
        'hon_523': aplicar_hon_523,
        # data_calculo pode vir da sidebar, mas por segurança mantemos a do cálculo
    })
    
    if st.button("📄 Baixar Laudo Técnico (PDF)"):
        if total_geral == 0 and st.session_state.dados_aluguel is None:
            st.warning("Não há valores calculados para gerar relatório.")
        else:
            pdf_bytes = gerar_pdf_relatorio(
                st.session_state.df_indenizacao,
                st.session_state.df_honorarios,
                st.session_state.df_pensao_final,
                st.session_state.dados_aluguel,
                totais_pdf,
                config_pdf
            )
            st.download_button(
                label="⬇️ Download PDF Assinado Digitalmente (Simulado)",
                data=pdf_bytes,
                file_name=f"Laudo_CalcJus_{date.today()}.pdf",
                mime="application/pdf"
            )
