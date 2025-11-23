import streamlit as st
import pandas as pd
import requests
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus Pro Multi", layout="wide")

st.title("⚖️ CalcJus PRO - Central de Cálculos Judiciais")
st.markdown("Cálculos de **Indenizações Cíveis**, **Honorários** e **Pensão Alimentícia** com atualização oficial.")

# --- FUNÇÃO DE BUSCA NO BANCO CENTRAL (BCB) ---
@st.cache_data(ttl=3600)
def buscar_fator_bcb(codigo_serie, data_inicio, data_fim):
    if data_fim < data_inicio: return 1.0
    
    d1 = data_inicio.strftime("%d/%m/%Y")
    d2 = data_fim.strftime("%d/%m/%Y")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={d1}&dataFinal={d2}"
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            dados = response.json()
            fator = 1.0
            for item in dados:
                fator *= (1 + float(item['valor'])/100)
            return fator
    except:
        pass
    return 1.0

# --- MENU LATERAL (CONFIGURAÇÕES GERAIS) ---
st.sidebar.header("1. Parâmetros Gerais")
data_calculo = st.sidebar.date_input("Data do Cálculo (Atualização)", value=date.today())

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764, "IPCA": 433}
indice_nome = st.sidebar.selectbox("Índice de Correção", list(mapa_indices.keys()))
codigo_indice = mapa_indices[indice_nome]

st.sidebar.divider()
st.sidebar.header("2. Penalidades (Execução)")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10% (Art. 523)?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)

# --- ESTADO DA APLICAÇÃO (MEMÓRIA) ---
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'total_pensao' not in st.session_state: st.session_state.total_pensao = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()
if 'df_pensao' not in st.session_state: st.session_state.df_pensao = pd.DataFrame()

# --- ABAS DO APLICATIVO ---
tab1, tab2, tab3, tab4 = st.tabs([
    "🏢 1. Indenização/Imóvel", 
    "⚖️ 2. Honorários", 
    "👶 3. Pensão Alimentícia", 
    "📊 4. RESUMO GERAL"
])

# ==============================================================================
# ABA 1: INDENIZAÇÃO POR ATRASO (LUCROS CESSANTES)
# ==============================================================================
with tab1:
    st.subheader("Cálculo de Lucros Cessantes (Atraso de Obra)")
    st.caption("Gera parcelas mensais baseadas em % do contrato.")
    
    c1, c2, c3 = st.columns(3)
    valor_contrato = c1.number_input("Valor do Contrato (R$)", value=318316.50, step=1000.00)
    perc_indenizacao = c2.number_input("% Indenização Mensal", value=0.5, step=0.1)
    valor_mensal = valor_contrato * (perc_indenizacao / 100)
    c3.metric("Valor Mensal Base", f"R$ {valor_mensal:,.2f}")
    
    st.write("---")
    c4, c5, c6 = st.columns(3)
    inicio_atraso = c4.date_input("Início da Mora", value=date(2024, 7, 1))
    fim_atraso = c5.date_input("Fim da Mora", value=date(2024, 10, 16))
    data_citacao_ind = c6.date_input("Data da Citação (Para Juros)", value=date(2025, 2, 25))
    
    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        temp_date = inicio_atraso
        progresso = st.progress(0, text="Processando indenização...")
        
        while temp_date < fim_atraso:
            prox_mes = temp_date + relativedelta(months=1)
            data_vencimento = prox_mes - timedelta(days=1)
            
            fator_pro_rata = 1.0
            if data_vencimento > fim_atraso:
                dias_no_mes = (data_vencimento - temp_date).days + 1
                dias_pro_rata = (fim_atraso - temp_date).days + 1
                fator_pro_rata = dias_pro_rata / dias_no_mes
                data_vencimento = fim_atraso
                
            valor_base_mes = valor_mensal * fator_pro_rata
            
            fator_corr = buscar_fator_bcb(codigo_indice, data_vencimento, data_calculo)
            val_corr = valor_base_mes * fator_corr
            
            data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
            dias_juros = (data_calculo - data_inicio_juros).days
            val_juros = 0.0
            if dias_juros > 0:
                val_juros = val_corr * (0.01/30 * dias_juros)
            
            lista_ind.append({
                "Vencimento": data_vencimento.strftime("%d/%m/%Y"),
                "Valor Orig.": f"R$ {valor_base_mes:,.2f}",
                "Fator CM": f"{fator_corr:.4f}",
                "V. Corrigido": f"R$ {val_corr:,.2f}",
                "Juros (R$)": f"R$ {val_juros:,.2f}",
                "TOTAL": f"R$ {val_corr + val_juros:,.2f}",
                "_num": val_corr + val_juros
            })
            temp_date = prox_mes.replace(day=1)

        progresso.empty()
        if lista_ind:
            df = pd.DataFrame(lista_ind)
            st.session_state.df_indenizacao = df
            st.session_state.total_indenizacao = df["_num"].sum()
            st.success(f"Total Indenização: R$ {st.session_state.total_indenizacao:,.2f}")
            st.dataframe(df.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 2: HONORÁRIOS E CUSTAS
# ==============================================================================
with tab2:
    st.subheader("Cálculo de Honorários / Custas Processuais")
    
    col_h1, col_h2 = st.columns(2)
    valor_honorarios = col_h1.number_input("Valor Arbitrado (R$)", value=1500.00)
    
    col_d1, col_d2 = st.columns(2)
    data_base_corr = col_d1.date_input("Correção desde (Ajuizamento):", value=date(2024, 12, 3))
    data_base_juros = col_d2.date_input("Juros desde (Trânsito em Julgado):", value=date(2025, 11, 10))
    
    if st.button("Calcular Honorários"):
        with st.spinner("Calculando honorários..."):
            fator_h = buscar_fator_bcb(codigo_indice, data_base_corr, data_calculo)
            val_h_corr = valor_honorarios * fator_h
            
            dias_h = (data_calculo - data_base_juros).days
            val_h_juros = 0.0
            if dias_h > 0:
                val_h_juros = val_h_corr * (0.01/30 * dias_h)
                
            total_h = val_h_corr + val_h_juros
            
            res_hon = [{
                "Descrição": "Honorários Sucumbenciais",
                "Valor Orig.": f"R$ {valor_honorarios:,.2f}",
                "Correção": f"R$ {val_h_corr - valor_honorarios:,.2f}",
                "Juros": f"R$ {val_h_juros:,.2f}",
                "TOTAL": f"R$ {total_h:,.2f}",
                "_num": total_h
            }]
            
            st.session_state.df_honorarios = pd.DataFrame(res_hon)
            st.session_state.total_honorarios = total_h
            st.success(f"Total Honorários: R$ {total_h:,.2f}")
            st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 3: PENSÃO ALIMENTÍCIA (NOVA FUNÇÃO)
# ==============================================================================
with tab3:
    st.subheader("👶 Cálculo de Pensão Alimentícia em Atraso")
    st.caption("Gera automaticamente os meses devidos, aplica correção e juros desde cada vencimento.")

    col_p1, col_p2, col_p3 = st.columns(3)
    valor_pensao = col_p1.number_input("Valor da Pensão (R$)", value=1000.00, step=50.00)
    dia_vencimento = col_p2.number_input("Dia do Vencimento (todo dia...)", value=10, min_value=1, max_value=31)
    
    st.write("---")
    col_p4, col_p5 = st.columns(2)
    inicio_pensao = col_p4.date_input("Data da 1ª Parcela não paga", value=date(2024, 1, 10))
    fim_pensao = col_p5.date_input("Data da última parcela a cobrar", value=date.today())

    if st.button("Calcular Pensão Atrasada", type="primary"):
        lista_pensao = []
        
        # Lógica para encontrar o primeiro vencimento válido
        data_atual = inicio_pensao.replace(day=dia_vencimento)
        if data_atual < inicio_pensao:
             data_atual = data_atual + relativedelta(months=1)

        progresso_p = st.progress(0, text="Calculando pensão mês a mês...")
        meses_calculados = 0
        
        # Loop para gerar parcelas até a data final
        temp_dates = []
        while data_atual <= fim_pensao:
            temp_dates.append(data_atual)
            data_atual = data_atual + relativedelta(months=1)
            
        for i, vencimento in enumerate(temp_dates):
            progresso_p.progress((i + 1) / len(temp_dates))
            
            # 1. Correção Monetária (Desde o vencimento)
            fator_corr_p = buscar_fator_bcb(codigo_indice, vencimento, data_calculo)
            val_corr_p = valor_pensao * fator_corr_p
            
            # 2. Juros de Mora (1% a.m. desde o vencimento - Regra de Alimentos)
            dias_atraso_p = (data_calculo - vencimento).days
            val_juros_p = 0.0
            if dias_atraso_p > 0:
                # Juros simples pro-rata
                val_juros_p = val_corr_p * (0.01/30 * dias_atraso_p)
            
            total_parcela_p = val_corr_p + val_juros_p
            
            lista_pensao.append({
                "Vencimento": vencimento.strftime("%d/%m/%Y"),
                "Valor Orig.": f"R$ {valor_pensao:,.2f}",
                "Fator CM": f"{fator_corr_p:.4f}",
                "V. Atualizado": f"R$ {val_corr_p:,.2f}",
                "Dias Atraso": dias_atraso_p,
                "Juros (R$)": f"R$ {val_juros_p:,.2f}",
                "TOTAL": f"R$ {total_parcela_p:,.2f}",
                "_num": total_parcela_p
            })
            
        progresso_p.empty()
        
        if lista_pensao:
            df_p = pd.DataFrame(lista_pensao)
            st.session_state.df_pensao = df_p
            st.session_state.total_pensao = df_p["_num"].sum()
            st.success(f"Total Pensão Alimentícia: R$ {st.session_state.total_pensao:,.2f}")
            st.dataframe(df_p.drop(columns=["_num"]), use_container_width=True, height=400)
        else:
            st.warning("Nenhuma parcela encontrada no período selecionado.")


# ==============================================================================
# ABA 4: RESUMO GERAL (TOTAL)
# ==============================================================================
with tab4:
    st.subheader("Resumo Global da Execução")
    
    tot_ind = st.session_state.total_indenizacao
    tot_hon = st.session_state.total_honorarios
    tot_pen = st.session_state.total_pensao
    
    total_parcial = tot_ind + tot_hon + tot_pen
    
    if total_parcial == 0:
        st.info("Realize os cálculos nas abas anteriores para ver o resumo aqui.")
    else:
        # Multas Art. 523 CPC
        multa_523 = total_parcial * 0.10 if aplicar_multa_523 else 0.0
        hon_523 = total_parcial * 0.10 if aplicar_hon_523 else 0.0
        
        total_final = total_parcial + multa_523 + hon_523
        
        col_res1, col_res2 = st.columns([3, 2])
        
        with col_res1:
            st.markdown("### Discriminativo")
            if tot_ind > 0: st.write(f"🔹 **Indenização Cível:** R$ {tot_ind:,.2f}")
            if tot_hon > 0: st.write(f"🔹 **Honorários:** R$ {tot_hon:,.2f}")
            if tot_pen > 0: st.write(f"🔹 **Pensão Alimentícia:** R$ {tot_pen:,.2f}")
            
            st.markdown("---")
            st.write(f"**Subtotal:** R$ {total_parcial:,.2f}")
            
            if aplicar_multa_523: st.write(f"+ Multa 10% (Art. 523): R$ {multa_523:,.2f}")
            if aplicar_hon_523: st.write(f"+ Honorários 10% (Art. 523): R$ {hon_523:,.2f}")
        
        with col_res2:
            st.success("VALOR FINAL DA EXECUÇÃO")
            st.metric(label="TOTAL", value=f"R$ {total_final:,.2f}")
            
        # Botão para limpar tudo
        if st.button("Limpar Todos os Cálculos"):
            st.session_state.total_indenizacao = 0.0
            st.session_state.total_honorarios = 0.0
            st.session_state.total_pensao = 0.0
            st.session_state.df_indenizacao = pd.DataFrame()
            st.session_state.df_honorarios = pd.DataFrame()
            st.session_state.df_pensao = pd.DataFrame()
            st.rerun()
