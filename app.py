import streamlit as st
import pandas as pd
import requests
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="CalcJus - Cumprimento de Sentença", layout="wide")

st.title("⚖️ CalcJus - Cumprimento de Sentença (Completo)")
st.markdown("Calculadora processual para **Indenizações (Lucros Cessantes)** e **Honorários de Sucumbência**.")

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

mapa_indices = {"INPC (IBGE)": 188, "IGP-M (FGV)": 189, "INCC-DI": 192, "IPCA-E": 10764}
indice_nome = st.sidebar.selectbox("Índice de Correção", list(mapa_indices.keys()))
codigo_indice = mapa_indices[indice_nome]

st.sidebar.divider()
st.sidebar.header("2. Penalidades (Art. 523 CPC)")
aplicar_multa_523 = st.sidebar.checkbox("Aplicar Multa de 10%?", value=False)
aplicar_hon_523 = st.sidebar.checkbox("Aplicar Honorários de 10%?", value=False)

# --- ESTADO DA APLICAÇÃO (SESSION STATE) ---
if 'total_indenizacao' not in st.session_state: st.session_state.total_indenizacao = 0.0
if 'total_honorarios' not in st.session_state: st.session_state.total_honorarios = 0.0
if 'df_indenizacao' not in st.session_state: st.session_state.df_indenizacao = pd.DataFrame()
if 'df_honorarios' not in st.session_state: st.session_state.df_honorarios = pd.DataFrame()

# --- ABAS DO APLICATIVO ---
tab1, tab2, tab3 = st.tabs(["🏢 1. Lucros Cessantes (Atraso)", "⚖️ 2. Honorários/Custas", "📊 3. RESUMO FINAL"])

# ==============================================================================
# ABA 1: INDENIZAÇÃO POR ATRASO (LUCROS CESSANTES)
# ==============================================================================
with tab1:
    st.subheader("Cálculo de Lucros Cessantes (0,5% do Contrato)")
    
    c1, c2, c3 = st.columns(3)
    valor_contrato = c1.number_input("Valor do Contrato (R$)", value=318316.50, step=1000.00)
    perc_indenizacao = c2.number_input("% Indenização Mensal", value=0.5, step=0.1)
    valor_mensal = valor_contrato * (perc_indenizacao / 100)
    c3.metric("Valor Mensal Base", f"R$ {valor_mensal:,.2f}")
    
    st.write("---")
    c4, c5, c6 = st.columns(3)
    inicio_atraso = c4.date_input("Início da Mora (Pós Tolerância)", value=date(2024, 7, 1))
    fim_atraso = c5.date_input("Fim da Mora (Entrega Chaves)", value=date(2024, 10, 16))
    data_citacao_ind = c6.date_input("Data da Citação (Para Juros)", value=date(2025, 2, 25))
    
    if st.button("Calcular Indenização", type="primary"):
        lista_ind = []
        temp_date = inicio_atraso
        
        # Gera meses até a data final
        while temp_date < fim_atraso:
            # Define data fim deste mês específico (ex: 30/07, 30/08)
            # Simplificação: Usar último dia do mês ou dia da entrega se for o último mês
            prox_mes = temp_date + relativedelta(months=1)
            data_vencimento = prox_mes - timedelta(days=1) # Fim do mês
            
            # Se passou da data final, ajusta para pro-rata
            fator_pro_rata = 1.0
            if data_vencimento > fim_atraso:
                dias_no_mes = (data_vencimento - temp_date).days + 1
                dias_pro_rata = (fim_atraso - temp_date).days + 1
                fator_pro_rata = dias_pro_rata / dias_no_mes
                data_vencimento = fim_atraso # Vencimento é a entrega
                
            valor_base_mes = valor_mensal * fator_pro_rata
            
            # 1. Correção (Do vencimento até hoje)
            fator_corr = buscar_fator_bcb(codigo_indice, data_vencimento, data_calculo)
            val_corr = valor_base_mes * fator_corr
            
            # 2. Juros (Da Citação ou Vencimento)
            data_inicio_juros = data_citacao_ind if data_vencimento < data_citacao_ind else data_vencimento
            dias_juros = (data_calculo - data_inicio_juros).days
            val_juros = 0.0
            if dias_juros > 0:
                val_juros = val_corr * (0.01/30 * dias_juros)
            
            lista_ind.append({
                "Mês Ref": temp_date.strftime("%m/%Y"),
                "Valor Base": f"R$ {valor_base_mes:,.2f}",
                "Vencimento": data_vencimento.strftime("%d/%m/%Y"),
                "Fator CM": f"{fator_corr:.4f}",
                "V. Corrigido": f"R$ {val_corr:,.2f}",
                "Dias Juros": dias_juros,
                "Juros (R$)": f"R$ {val_juros:,.2f}",
                "TOTAL": f"R$ {val_corr + val_juros:,.2f}",
                "_num": val_corr + val_juros
            })
            
            # Avança para próximo mês (dia 1)
            temp_date = prox_mes.replace(day=1)

        if lista_ind:
            df = pd.DataFrame(lista_ind)
            st.session_state.df_indenizacao = df
            st.session_state.total_indenizacao = df["_num"].sum()
            st.success(f"Indenização Calculada: R$ {st.session_state.total_indenizacao:,.2f}")
            st.dataframe(df.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 2: HONORÁRIOS E CUSTAS
# ==============================================================================
with tab2:
    st.subheader("Cálculo de Honorários Sucumbenciais / Custas")
    
    col_h1, col_h2 = st.columns(2)
    valor_honorarios = col_h1.number_input("Valor Fixo Arbitrado (R$)", value=1500.00)
    
    col_d1, col_d2 = st.columns(2)
    data_base_corr = col_d1.date_input("Correção desde (Ajuizamento):", value=date(2024, 12, 3))
    data_base_juros = col_d2.date_input("Juros desde (Trânsito em Julgado):", value=date(2025, 11, 10))
    
    if st.button("Calcular Honorários"):
        # 1. Correção
        fator_h = buscar_fator_bcb(codigo_indice, data_base_corr, data_calculo)
        val_h_corr = valor_honorarios * fator_h
        
        # 2. Juros
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
        st.success(f"Honorários Calculados: R$ {total_h:,.2f}")
        st.dataframe(st.session_state.df_honorarios.drop(columns=["_num"]), use_container_width=True)

# ==============================================================================
# ABA 3: RESUMO GERAL (TOTAL)
# ==============================================================================
with tab3:
    st.subheader("Resumo do Cumprimento de Sentença")
    
    if st.session_state.total_indenizacao == 0 and st.session_state.total_honorarios == 0:
        st.warning("Realize os cálculos nas abas 1 e 2 primeiro.")
    else:
        # Consolidação
        total_parcial = st.session_state.total_indenizacao + st.session_state.total_honorarios
        
        # Multas Art. 523 CPC
        multa_523 = total_parcial * 0.10 if aplicar_multa_523 else 0.0
        hon_523 = total_parcial * 0.10 if aplicar_hon_523 else 0.0
        
        total_final = total_parcial + multa_523 + hon_523
        
        # Exibição Bonita
        col_res1, col_res2 = st.columns([1, 1])
        
        with col_res1:
            st.write(f"**1. Lucros Cessantes (Exequente):** R$ {st.session_state.total_indenizacao:,.2f}")
            st.write(f"**2. Honorários (Advogado):** R$ {st.session_state.total_honorarios:,.2f}")
            st.write("---")
            st.write(f"**SUBTOTAL:** R$ {total_parcial:,.2f}")
            
            if aplicar_multa_523:
                st.write(f"+ Multa 10% (Art. 523): R$ {multa_523:,.2f}")
            if aplicar_hon_523:
                st.write(f"+ Honorários 10% (Art. 523): R$ {hon_523:,.2f}")
                
        with col_res2:
            st.metric(label="TOTAL DA EXECUÇÃO", value=f"R$ {total_final:,.2f}")
            
        st.info(f"Cálculo atualizado até: {data_calculo.strftime('%d/%m/%Y')} | Índice: {indice_nome}")
