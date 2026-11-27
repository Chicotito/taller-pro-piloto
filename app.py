import datetime as dt
import pandas as pd
import streamlit as st

from storage import (
    COLS_INV,
    COLS_SP,
    COLS_VT,
    FILE_INV,
    FILE_SERV_PREV,
    cargar_inventario,
    cargar_servicios_prev,
    cargar_ventas,
    guardar_inventario,
    guardar_servicios_prev,
    guardar_ventas,
    calcular_proximo_servicio,
    normalizar_df_inv,
    normalizar_df_sp,
    siguiente_folio_sp,
    siguiente_folio_vt,
    normalizar_df_vt,
)

st.set_page_config(page_title="Taller Olachea - App", layout="wide")
st.title("Taller Olachea — Sistema de Gestión")

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "1234") if hasattr(st, "secrets") else "1234"
LOGO_PATH = "logo_taller.png"

if "df_serv_prev" not in st.session_state:
    st.session_state["df_serv_prev"] = cargar_servicios_prev(FILE_SERV_PREV)
if "ticket_actual" not in st.session_state:
    st.session_state["ticket_actual"] = ""
if "folio_actual" not in st.session_state:
    st.session_state["folio_actual"] = "TICKET"


def generar_ticket(datos: dict) -> str:
    folio = datos.get("Folio_Venta") or "S/F"
    fecha = datos.get("Fecha_Venta") or dt.date.today().isoformat()
    cliente = datos.get("Cliente") or "Público general"
    tel = datos.get("Telefono") or "-"
    vehiculo = datos.get("Vehiculo") or "-"
    no_eco = datos.get("No_Economico") or "-"
    concepto = datos.get("Concepto") or "Servicio de refrigeración"
    ref = datos.get("Refrigerante") or "-"
    cant = int(datos.get("Cantidad", 1))
    p_unit = float(datos.get("Precio_Unitario", 0.0))
    total = float(datos.get("Total", cant * p_unit))
    pago = datos.get("Metodo_Pago") or "Efectivo"
    estado = datos.get("Estado_Pago") or "Pagado"
    obs = datos.get("Observaciones") or ""

    lineas = [
        "========================================",
        "      TALLER OLACHEA REFRIGERACION",
        "            TICKET DE VENTA",
        "========================================",
        f"Folio:         {folio}",
        f"Fecha:         {fecha}",
        f"Estado:        {estado}",
        "----------------------------------------",
        f"Cliente:       {cliente}",
        f"Telefono:      {tel}",
        f"Unidad:        {vehiculo}",
        f"No. Economico: {no_eco}",
        "----------------------------------------",
        f"Concepto:      {concepto}",
        f"Refrigerante:  {ref}",
        f"Cant x P.U.:   {cant} x ${p_unit:,.2f}",
        f"TOTAL:         ${total:,.2f}",
        f"Pago:          {pago}",
    ]
    if obs:
        lineas.append(f"Notas:         {obs}")
    lineas.extend([
        "========================================",
        "       Gracias por su preferencia",
        "========================================",
    ])
    return "\n".join(lineas)


def _es_duplicado_reciente_vt(df_existente: pd.DataFrame, nuevo: dict) -> bool:
    if df_existente.empty:
        return False
    ult = df_existente.iloc[-1]
    campos_comparar = [
        "Fecha_Venta",
        "Cliente",
        "Telefono",
        "Vehiculo",
        "No_Economico",
        "Concepto",
        "Refrigerante",
        "Cantidad",
        "Precio_Unitario",
        "Total",
        "Metodo_Pago",
        "Estado_Pago",
        "Observaciones",
    ]
    for campo in campos_comparar:
        val_ult = str(ult.get(campo, "") or "").strip()
        val_nuevo = str(nuevo.get(campo, "") or "").strip()
        if campo in {"Cantidad"}:
            try:
                if int(float(val_ult or 0)) != int(float(val_nuevo or 0)):
                    return False
            except ValueError:
                if val_ult != val_nuevo:
                    return False
        elif campo in {"Precio_Unitario", "Total"}:
            try:
                if round(float(val_ult or 0.0), 2) != round(float(val_nuevo or 0.0), 2):
                    return False
            except ValueError:
                if val_ult != val_nuevo:
                    return False
        else:
            if val_ult != val_nuevo:
                return False
    return True


def _mapear_columnas_inv(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    renombres = {}
    for col in df.columns:
        low = col.lower()
        if any(k in low for k in ["cód", "cod", "sku", "clave", "id"]):
            renombres[col] = "Código"
        elif any(k in low for k in ["prod", "desc", "nombre", "artículo", "articulo"]):
            renombres[col] = "Producto"
        elif any(k in low for k in ["fam", "cat", "lin", "línea", "linea"]):
            renombres[col] = "Familia"
        elif any(k in low for k in ["stock", "cant", "exist"]):
            renombres[col] = "Stock"
        elif "cost" in low:
            renombres[col] = "Costo"
        elif any(k in low for k in ["precio", "venta", "p.u", "pu"]):
            renombres[col] = "Precio Venta"
    return df.rename(columns=renombres)


def _leer_archivo_inv(archivo) -> pd.DataFrame:
    if archivo.name.lower().endswith(".csv"):
        try:
            df = pd.read_csv(archivo, dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            archivo.seek(0)
            df = pd.read_csv(archivo, dtype=str, encoding="latin-1")
    else:
        df = pd.read_excel(archivo, dtype=str)
    return _mapear_columnas_inv(df)


tab_sp, tab_ticket, tab_reporte, tab_inv = st.tabs([
    "Servicios Preventivos",
    "Ticket de Venta",
    "Ventas (Día / Mensual)",
    "Inventario",
])

# ==========================================
# PESTAÑA 1: SERVICIOS PREVENTIVOS
# ==========================================
with tab_sp:
    st.caption(f"Archivo de datos: `{FILE_SERV_PREV}`")

    try:
        raw_sp = cargar_servicios_prev(FILE_SERV_PREV)
        df_actual = normalizar_df_sp(raw_sp)
    except Exception as e:
        st.warning(f"No se pudo leer el CSV previo ({e}). Se iniciará tabla vacía.")
        df_actual = pd.DataFrame(columns=COLS_SP)

    st.subheader("Registros actuales en CSV")
    st.dataframe(df_actual, width="stretch", hide_index=True)

    def _limpios(col_name: str) -> list[str]:
        if df_actual is None or df_actual.empty or col_name not in df_actual.columns:
            return []
        vals = [
            str(v).strip()
            for v in df_actual[col_name].tolist()
            if v is not None and str(v).strip() and str(v).strip().lower() != "nan"
        ]
        return sorted(set(vals))

    clientes_prev = _limpios("Cliente")
    vehiculos_prev = _limpios("Vehiculo")
    ecos_prev = _limpios("No_Economico")

    st.subheader("Nuevo registro de servicio preventivo")
    st.caption("Elige un dato existente para autocompletar o deja **(Nuevo / Escribir)** y escribe directo en el formulario.")

    s1, s2, s3 = st.columns(3)
    with s1:
        eco_sel = st.selectbox(
            "No. Económico registrado",
            options=["(Nuevo / Escribir)"] + ecos_prev,
            key="sp_eco_sel",
        )
    with s2:
        cli_sel = st.selectbox(
            "Cliente registrado",
            options=["(Nuevo / Escribir)"] + clientes_prev,
            key="sp_cli_sel",
        )
    with s3:
        veh_sel = st.selectbox(
            "Vehículo registrado",
            options=["(Nuevo / Escribir)"] + vehiculos_prev,
            key="sp_veh_sel",
        )

    eco_cli_def, eco_veh_def, eco_anio_def, eco_ref_def, eco_tel_def = "", "", "", "", ""
    if eco_sel != "(Nuevo / Escribir)" and not df_actual.empty and "No_Economico" in df_actual.columns:
        coincidencias = df_actual[df_actual["No_Economico"].astype(str).str.strip() == eco_sel]
        if not coincidencias.empty:
            ult = coincidencias.iloc[-1]
            eco_cli_def = str(ult.get("Cliente", "") or "").strip()
            eco_veh_def = str(ult.get("Vehiculo", "") or "").strip()
            eco_anio_def = str(ult.get("Anio", "") or "").strip()
            eco_ref_def = str(ult.get("Refrigerante", "") or "").strip()
            eco_tel_def = str(ult.get("Telefono", "") or "").strip()

    cli_inicial = "" if cli_sel == "(Nuevo / Escribir)" else cli_sel
    if not cli_inicial and eco_cli_def and eco_cli_def.lower() != "nan":
        cli_inicial = eco_cli_def

    veh_inicial = "" if veh_sel == "(Nuevo / Escribir)" else veh_sel
    if not veh_inicial and eco_veh_def and eco_veh_def.lower() != "nan":
        veh_inicial = eco_veh_def

    eco_inicial = "" if eco_sel == "(Nuevo / Escribir)" else eco_sel

    try:
        folio_sugerido = siguiente_folio_sp(df_actual) or f"SP-{len(df_actual) + 1:02d}"
    except Exception:
        folio_sugerido = f"SP-{len(df_actual) + 1:02d}"

    hoy_str = dt.date.today().isoformat()

    with st.form("form_detalle_sp", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)

        with c1:
            folio_prev = st.text_input("Folio Preventivo *", value=folio_sugerido).strip()
            cliente = st.text_input("Cliente *", value=cli_inicial).strip()
            telefono = st.text_input("Teléfono", value="" if eco_tel_def.lower() == "nan" else eco_tel_def).strip()
            refrigerante = st.text_input(
                "Refrigerante",
                value="" if eco_ref_def.lower() == "nan" else eco_ref_def,
                placeholder="Ej. R-134 / R134a / R404A",
            ).strip()
            meses_intervalo = st.number_input(
                "Meses de Intervalo",
                min_value=1,
                max_value=60,
                value=3,
                step=1,
            )

        with c2:
            vehiculo = st.text_input("Vehículo / Unidad *", value=veh_inicial).strip()
            anio = st.text_input(
                "Año",
                value="" if eco_anio_def.lower() == "nan" else eco_anio_def,
                placeholder="Ej. 2024",
            ).strip()
            servicio_prev = st.text_input(
                "Servicio Preventivo",
                placeholder="Ej. Carga completa de gas refrigerante",
            ).strip()
            fecha_servicio = st.text_input("Fecha Servicio (YYYY-MM-DD)", value=hoy_str).strip()
            proximo_servicio_manual = st.text_input(
                "Próximo Servicio (opcional, auto si queda vacío)",
                value="",
                placeholder="YYYY-MM-DD (se calcula automáticamente)",
            ).strip()

        with c3:
            no_eco = st.text_input(
                "No. Económico",
                value=eco_inicial,
                placeholder="Ej. 093, SB-014, U-97",
            ).strip()
            kilometraje = st.text_input("Kilometraje", placeholder="Ej. 85000").strip()
            estado = st.selectbox(
                "Estado",
                ["Programado", "En proceso", "Completado", "Pendiente", "Vencido"],
                index=0,
            )
            monto = st.number_input("Monto ($)", min_value=0.0, value=0.0, step=50.0, format="%.2f")

        observaciones = st.text_area("Observaciones", height=75, placeholder="Detalles del diagnóstico o servicio...").strip()

        enviar = st.form_submit_button("Guardar registro preventivo", type="primary")

        if enviar:
            if not cliente or not vehiculo:
                st.error("Captura al menos **Cliente** y **Vehículo / Unidad**.")
            else:
                df_base = normalizar_df_sp(cargar_servicios_prev(FILE_SERV_PREV))
                folio_final = folio_prev if folio_prev else (siguiente_folio_sp(df_base) or f"SP-{len(df_base) + 1:02d}")
                prox_final = proximo_servicio_manual
                if not prox_final:
                    prox_final = calcular_proximo_servicio(fecha_servicio, int(meses_intervalo))

                fila_dict = {col: "" for col in COLS_SP}
                fila_dict.update({
                    "Folio_Prev": folio_final,
                    "Cliente": cliente,
                    "Telefono": telefono,
                    "Vehiculo": vehiculo,
                    "Anio": anio,
                    "No_Economico": str(no_eco),
                    "Refrigerante": refrigerante,
                    "Servicio_Preventivo": servicio_prev,
                    "Fecha_Servicio": fecha_servicio,
                    "Meses_Intervalo": int(meses_intervalo),
                    "Proximo_Servicio": prox_final,
                    "Kilometraje": kilometraje,
                    "Estado": estado,
                    "Monto": float(monto),
                    "Observaciones": observaciones,
                })
                nueva_fila = pd.DataFrame([fila_dict], columns=COLS_SP)
                df_nuevo = pd.concat([df_base, nueva_fila], ignore_index=True)

                if guardar_servicios_prev(df_nuevo, FILE_SERV_PREV):
                    st.session_state["df_serv_prev"] = cargar_servicios_prev(FILE_SERV_PREV)
                    st.success(f"Guardado **{folio_final}** — No. Económico: `{str(no_eco)}`")
                    st.rerun()

# ==========================================
# PESTAÑA 2: TICKET DE VENTA
# ==========================================
with tab_ticket:
    st.subheader("Emitir Ticket de Venta")
    df_vt_actual = normalizar_df_vt(cargar_ventas())
    folio_sugerido = siguiente_folio_vt(df_vt_actual)

    with st.form("form_ticket_venta", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            folio_venta = st.text_input("Folio", value=folio_sugerido)
            fecha_venta = st.date_input("Fecha", value=dt.date.today())
            cliente_vt = st.text_input("Cliente", placeholder="Ej. Transportes del Pacífico")
            telefono_vt = st.text_input("Teléfono", placeholder="Ej. 6121234567")
            vehiculo_vt = st.text_input("Unidad / Vehículo", placeholder="Ej. Freightliner M2")
            no_eco_vt = st.text_input("No. Económico", placeholder="Ej. 005")
        with c2:
            concepto_vt = st.text_input("Concepto", placeholder="Ej. Carga refrigerante y revisión")
            refrigerante_vt = st.text_input("Refrigerante", placeholder="Ej. R134a / R404A")
            cantidad_vt = st.number_input("Cantidad", min_value=1, max_value=999, value=1, step=1)
            precio_unit_vt = st.number_input("Precio Unitario ($)", min_value=0.0, value=0.0, step=50.0, format="%.2f")
            metodo_pago = st.selectbox("Método de Pago", ["Efectivo", "Transferencia", "Tarjeta", "Crédito"])
            estado_pago = st.selectbox("Estado", ["Pagado", "Pendiente", "Abono"])

        obs_vt = st.text_input("Observaciones", placeholder="Opcional")
        emitir = st.form_submit_button("Generar ticket de venta", type="primary")

        if emitir:
            df_vt_fresh = normalizar_df_vt(cargar_ventas())
            folio_limpio = folio_venta.strip() or siguiente_folio_vt(df_vt_fresh)
            total_calc = round(int(cantidad_vt) * float(precio_unit_vt), 2)
            registro_vt = {
                "Folio_Venta": folio_limpio,
                "Folio_Referencia": "",
                "Fecha_Venta": fecha_venta.isoformat(),
                "Cliente": cliente_vt.strip(),
                "Telefono": telefono_vt.strip(),
                "Vehiculo": vehiculo_vt.strip(),
                "No_Economico": str(no_eco_vt).strip(),
                "Concepto": concepto_vt.strip(),
                "Refrigerante": refrigerante_vt.strip(),
                "Cantidad": int(cantidad_vt),
                "Precio_Unitario": float(precio_unit_vt),
                "Total": float(total_calc),
                "Metodo_Pago": metodo_pago,
                "Estado_Pago": estado_pago,
                "Observaciones": obs_vt.strip(),
            }

            if _es_duplicado_reciente_vt(df_vt_fresh, registro_vt):
                st.warning("Se detectó un envío duplicado idéntico al último registro; no se guardó una segunda copia.")
            else:
                df_vt_nuevo = normalizar_df_vt(
                    pd.concat([df_vt_fresh, pd.DataFrame([registro_vt], columns=COLS_VT)], ignore_index=True)
                )
                guardar_ventas(df_vt_nuevo)
                st.session_state["ticket_actual"] = generar_ticket(registro_vt)
                st.session_state["folio_actual"] = folio_limpio
                st.success(f"Ticket `{folio_limpio}` generado y guardado.")

    if st.session_state["ticket_actual"]:
        st.divider()
        try:
            st.image(LOGO_PATH, width=180)
        except Exception:
            st.caption(f"No se encontró `{LOGO_PATH}` en el repositorio.")

        st.code(st.session_state["ticket_actual"], language="text")
        st.download_button(
            label="Descargar ticket (.txt)",
            data=st.session_state["ticket_actual"].encode("utf-8"),
            file_name=f"ticket_{st.session_state['folio_actual']}.txt",
            mime="text/plain",
        )

# ==========================================
# PESTAÑA 3: VENTAS (DÍA / MENSUAL)
# ==========================================
with tab_reporte:
    st.subheader("Corte y Resumen de Ventas")
    df_rep = normalizar_df_vt(cargar_ventas()).copy()
    fechas_parseadas = pd.to_datetime(df_rep["Fecha_Venta"], errors="coerce")
    df_rep["_fecha"] = fechas_parseadas.dt.date
    df_rep["_mes"] = fechas_parseadas.dt.strftime("%Y-%m").fillna("")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        dia_consulta = st.date_input("Día a consultar", value=dt.date.today())
    with col_f2:
        meses_disponibles = sorted([m for m in df_rep["_mes"].unique() if m], reverse=True)
        mes_actual_str = dia_consulta.strftime("%Y-%m")
        if mes_actual_str not in meses_disponibles:
            meses_disponibles = [mes_actual_str] + meses_disponibles
        mes_consulta = st.selectbox("Mes a consultar", options=meses_disponibles, index=0)

    df_dia = df_rep[df_rep["_fecha"] == dia_consulta].drop(columns=["_fecha", "_mes"])
    df_mes = df_rep[df_rep["_mes"] == mes_consulta].drop(columns=["_fecha", "_mes"])

    total_dia = float(df_dia["Total"].sum()) if not df_dia.empty else 0.0
    total_mes = float(df_mes["Total"].sum()) if not df_mes.empty else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Venta del día ({dia_consulta.isoformat()})", f"${total_dia:,.2f}")
    m2.metric("Tickets del día", len(df_dia))
    m3.metric(f"Venta mensual ({mes_consulta})", f"${total_mes:,.2f}")
    m4.metric("Tickets del mes", len(df_mes))

    vista_modo = st.radio(
        "Ver detalle de:",
        ["Venta del día", "Venta mensual", "Todas las ventas"],
        horizontal=True,
    )

    if vista_modo == "Venta del día":
        df_tabla = df_dia
    elif vista_modo == "Venta mensual":
        df_tabla = df_mes
    else:
        df_tabla = df_rep.drop(columns=["_fecha", "_mes"])

    st.dataframe(df_tabla, width="stretch", hide_index=True)

# ==========================================
# PESTAÑA 4: CONTROL DE INVENTARIO
# ==========================================
with tab_inv:
    st.caption(f"Archivo de datos: `{FILE_INV}`")

    _, col_rec = st.columns([4, 1])
    with col_rec:
        if st.button("Forzar recarga", key="btn_recarga_inv", width="stretch"):
            try:
                st.session_state["df_inv"] = normalizar_df_inv(cargar_inventario(FILE_INV))
                st.success("Inventario recargado desde almacenamiento.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al recargar inventario: {e}")

    try:
        raw_inv = st.session_state.get("df_inv")
        if raw_inv is None or (isinstance(raw_inv, pd.DataFrame) and raw_inv.empty):
            raw_inv = cargar_inventario(FILE_INV)
        df_inv = normalizar_df_inv(raw_inv)
        if not set(COLS_INV).issubset(df_inv.columns):
            df_inv = pd.DataFrame(columns=COLS_INV)
        st.session_state["df_inv"] = df_inv
    except Exception as e:
        st.warning(f"No se pudo leer inventario ({e}). Se iniciará tabla vacía.")
        df_inv = pd.DataFrame(columns=COLS_INV)

    total_skus = len(df_inv)
    sin_stock = int((df_inv["Stock"] <= 0).sum()) if not df_inv.empty else 0
    bajo_stock = int(((df_inv["Stock"] > 0) & (df_inv["Stock"] <= 3)).sum()) if not df_inv.empty else 0
    val_costo = float((df_inv["Stock"] * df_inv["Costo"]).sum()) if not df_inv.empty else 0.0
    val_venta = float((df_inv["Stock"] * df_inv["Precio Venta"]).sum()) if not df_inv.empty else 0.0

    im1, im2, im3, im4, im5 = st.columns(5)
    im1.metric("SKUs registrados", total_skus)
    im2.metric("Sin stock (0)", sin_stock)
    im3.metric("Stock bajo (<=3)", bajo_stock)
    im4.metric("Valor inventario (Costo)", f"${val_costo:,.2f}")
    im5.metric("Valor inventario (Venta)", f"${val_venta:,.2f}")

    tab_i1, tab_i2, tab_i3, tab_i4, tab_i5 = st.tabs([
        "Consultar / Editar",
        "Registrar Producto",
        "Carga Masiva Códigos",
        "Eliminar Producto",
        "Importar Excel / CSV",
    ])

    with tab_i1:
        st.subheader("Consultar y Editar Inventario")
        st.caption("Edita Stock, Costo o Precio Venta directo en la tabla (el Precio Venta se respeta tal como lo captures o ajustes según cliente).")

        if df_inv.empty:
            st.info("No hay productos registrados en el inventario.")
        else:
            familias_disp = ["Todas las Familias"] + sorted(
                [str(f).strip() for f in df_inv["Familia"].unique() if str(f).strip()]
            )
            f1, f2, f3 = st.columns([2, 2, 1])
            with f1:
                fam_sel = st.selectbox("Filtrar por Familia", familias_disp, key="sb_filtro_familia")
            with f2:
                q_inv = st.text_input(
                    "Buscar por Código, Producto o Familia",
                    placeholder="Ej. R134A, Filtro, Compresor",
                    key="txt_buscar_inv",
                ).strip().lower()
            with f3:
                solo_criticos = st.checkbox("Solo stock <= 3", value=False, key="chk_stock_critico")

            df_vista = df_inv.copy()
            if fam_sel != "Todas las Familias":
                df_vista = df_vista[df_vista["Familia"].str.upper() == fam_sel.upper()]
            if solo_criticos:
                df_vista = df_vista[df_vista["Stock"] <= 3]
            if q_inv:
                df_vista = df_vista[
                    df_vista["Código"].str.lower().str.contains(q_inv, na=False)
                    | df_vista["Producto"].str.lower().str.contains(q_inv, na=False)
                    | df_vista["Familia"].str.lower().str.contains(q_inv, na=False)
                ]

            df_edit = st.data_editor(
                df_vista.reset_index(drop=True),
                column_config={
                    "Código": st.column_config.TextColumn("Código / SKU", required=True),
                    "Producto": st.column_config.TextColumn("Producto", required=True),
                    "Familia": st.column_config.TextColumn("Familia / Línea", required=True),
                    "Stock": st.column_config.NumberColumn("Stock", min_value=0.0, step=1.0, format="%.2f"),
                    "Costo": st.column_config.NumberColumn("Costo ($)", min_value=0.0, format="$%,.2f"),
                    "Precio Venta": st.column_config.NumberColumn("Precio Venta ($)", min_value=0.0, format="$%,.2f"),
                },
                width="stretch",
                hide_index=True,
                key="editor_inv",
            )

            p1, p2 = st.columns([2, 1])
            with p1:
                pwd_edit = st.text_input("Clave de modificación:", type="password", key="pwd_edit_inv")
            with p2:
                st.write("")
                st.write("")
                btn_guardar = st.button("Guardar cambios", type="primary", key="btn_guardar_inv_t1", width="stretch")

            if btn_guardar:
                if pwd_edit != ADMIN_PASSWORD:
                    st.error("Clave incorrecta.")
                else:
                    edit_norm = normalizar_df_inv(df_edit)
                    idx_mostrados = set(df_vista.index)
                    df_no_mostrados = df_inv[~df_inv.index.isin(idx_mostrados)]
                    df_merged = normalizar_df_inv(pd.concat([df_no_mostrados, edit_norm], ignore_index=True))

                    validos = df_merged[
                        (df_merged["Código"] != "")
                        & (df_merged["Código"].str.lower() != "nan")
                        & (~df_merged["Código"].str.startswith("#"))
                    ]
                    dups = validos["Código"].str.upper().value_counts()
                    dups = dups[dups > 1].index.tolist()

                    if dups:
                        st.error(f"Código/SKU duplicado detectado: `{dups[0]}`. Corrígelo antes de guardar.")
                    elif guardar_inventario(validos, FILE_INV):
                        st.session_state["df_inv"] = validos
                        st.success("Inventario actualizado y guardado.")
                        st.rerun()

            st.divider()
            with st.expander("Ajustar Precios por Familia o Códigos (Con Clave)", expanded=False):
                st.caption("Aplica un factor sobre Costo únicamente a las Familias o Códigos seleccionados.")
                modo_regla = st.radio(
                    "Aplicar por:",
                    ["Familia", "Códigos (SKU)"],
                    horizontal=True,
                    key="rb_modo_regla_precio",
                )
                r1, r2 = st.columns([2, 1])
                with r1:
                    if modo_regla == "Familia":
                        fams = sorted([str(f).strip() for f in df_inv["Familia"].unique() if str(f).strip()])
                        objetivos = st.multiselect("Selecciona Familia(s):", options=fams, key="ms_fams_precio")
                    else:
                        skus = sorted([str(c).strip() for c in df_inv["Código"].unique() if str(c).strip()])
                        objetivos = st.multiselect("Selecciona Código(s) / SKU:", options=skus, key="ms_skus_precio")
                with r2:
                    factor_pct = st.number_input(
                        "Factor (ej. 1.60 = +60%)",
                        min_value=0.10,
                        max_value=10.00,
                        value=1.60,
                        step=0.05,
                        format="%.2f",
                        key="num_factor_precio",
                    )
                    solo_sin_precio = st.checkbox(
                        "Solo si Precio Venta == $0.00",
                        value=False,
                        key="chk_solo_sin_precio",
                    )

                pwd_regla = st.text_input("Clave de autorización:", type="password", key="pwd_regla_precio")
                if st.button("Aplicar factor de precio", type="primary", key="btn_aplicar_regla_precio"):
                    if pwd_regla != ADMIN_PASSWORD:
                        st.error("Clave incorrecta.")
                    elif not objetivos:
                        st.warning("Selecciona al menos una Familia o un Código.")
                    else:
                        df_upd = normalizar_df_inv(df_inv).copy()
                        if modo_regla == "Familia":
                            objetivos_up = {str(x).strip().upper() for x in objetivos}
                            mascara = df_upd["Familia"].astype(str).str.strip().str.upper().isin(objetivos_up)
                        else:
                            objetivos_up = {str(x).strip().upper() for x in objetivos}
                            mascara = df_upd["Código"].astype(str).str.strip().str.upper().isin(objetivos_up)

                        if solo_sin_precio:
                            mascara = mascara & (df_upd["Precio Venta"] <= 0)

                        df_upd.loc[mascara, "Precio Venta"] = (df_upd.loc[mascara, "Costo"] * float(factor_pct)).round(2)

                        if guardar_inventario(df_upd, FILE_INV):
                            st.session_state["df_inv"] = df_upd
                            st.success(f"Precio Venta actualizado en {int(mascara.sum())} artículo(s) con factor {factor_pct:.2f}.")
                            st.rerun()

    with tab_i2:
        st.subheader("Registrar Producto Manualmente")
        familias_sug = sorted([str(f).strip() for f in df_inv["Familia"].unique() if str(f).strip()]) if not df_inv.empty else []

        with st.form("form_nuevo_prod", clear_on_submit=True):
            n1, n2 = st.columns(2)
            with n1:
                n_codigo = st.text_input("Código / SKU *").strip().upper()
                n_producto = st.text_input("Nombre del Producto *").strip()
                n_familia = st.text_input(
                    "Familia / Categoría",
                    value="General",
                    help="Familias existentes: " + (", ".join(familias_sug[:8]) if familias_sug else "General"),
                ).strip()
            with n2:
                n_stock = st.number_input("Stock Inicial", min_value=0.0, step=1.0, value=0.0, format="%.2f")
                n_costo = st.number_input("Costo de Compra ($)", min_value=0.0, step=10.0, value=0.0, format="%.2f")
                n_precio = st.number_input("Precio de Venta ($)", min_value=0.0, step=10.0, value=0.0, format="%.2f")

            pwd_nuevo = st.text_input("Clave de autorización:", type="password", key="pwd_nuevo_inv")
            if st.form_submit_button("Guardar producto", type="primary"):
                if pwd_nuevo != ADMIN_PASSWORD:
                    st.error("Clave incorrecta.")
                elif not n_codigo or not n_producto:
                    st.error("Captura **Código / SKU** y **Nombre del Producto**.")
                elif not df_inv.empty and (df_inv["Código"].str.upper() == n_codigo).any():
                    st.error(f"El código `{n_codigo}` ya existe en el inventario.")
                else:
                    fila = pd.DataFrame([{
                        "Código": n_codigo,
                        "Producto": n_producto,
                        "Familia": n_familia or "General",
                        "Stock": float(n_stock),
                        "Costo": float(n_costo),
                        "Precio Venta": float(n_precio),
                    }], columns=COLS_INV)
                    df_act = normalizar_df_inv(pd.concat([df_inv, fila], ignore_index=True))
                    if guardar_inventario(df_act, FILE_INV):
                        st.session_state["df_inv"] = df_act
                        st.success(f"Producto `{n_codigo}` — {n_producto} guardado.")
                        st.rerun()

    with tab_i3:
        st.subheader("Carga Masiva de Códigos")
        st.caption("Actualiza existentes por Código/SKU e inserta códigos nuevos sin borrar el resto del inventario.")

        plantilla_csv = (
            "Código,Producto,Familia,Stock,Costo,Precio Venta\n"
            "SKU-001,Filtro Cabina A/C,Filtros,15,120.00,192.00\n"
            "GAS-134A,Refrigerante R134a,Refrigerantes,8,1450.00,2320.00\n"
        )
        st.download_button(
            "Descargar plantilla CSV",
            plantilla_csv.encode("utf-8"),
            "plantilla_inventario.csv",
            "text/csv",
            key="dl_plantilla_inv",
        )

        file_codigos = st.file_uploader(
            "Selecciona archivo (.csv o .xlsx):",
            type=["csv", "xlsx"],
            key="uploader_codigos_custom",
        )
        if file_codigos is not None:
            try:
                df_subida = _leer_archivo_inv(file_codigos)
                st.dataframe(df_subida.head(10), width="stretch", hide_index=True)

                pwd_subida = st.text_input("Clave de autorización:", type="password", key="pwd_subida_codigos")
                if st.button("Importar e integrar códigos", type="primary", key="btn_importar_inv"):
                    if pwd_subida != ADMIN_PASSWORD:
                        st.error("Clave incorrecta.")
                    elif "Código" not in df_subida.columns:
                        st.error("No se encontró columna de Código/SKU en el archivo.")
                    else:
                        for col_num in ["Stock", "Costo", "Precio Venta"]:
                            if col_num in df_subida.columns:
                                df_subida[col_num] = pd.to_numeric(
                                    df_subida[col_num].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).str.strip(),
                                    errors="coerce",
                                )
                        if "Producto" not in df_subida.columns:
                            df_subida["Producto"] = "Sin Nombre"
                        if "Familia" not in df_subida.columns:
                            df_subida["Familia"] = "General"

                        df_subida["Código"] = df_subida["Código"].fillna("").astype(str).str.strip().str.upper()
                        df_subida["Producto"] = df_subida["Producto"].fillna("Sin Nombre").astype(str).str.strip()
                        df_subida["Familia"] = df_subida["Familia"].fillna("General").astype(str).str.strip()
                        df_subida.loc[df_subida["Familia"] == "", "Familia"] = "General"
                        df_subida = df_subida[df_subida["Código"] != ""].drop_duplicates(subset=["Código"], keep="last")

                        base_idx = normalizar_df_inv(df_inv).drop_duplicates(subset=["Código"], keep="last").set_index("Código")
                        sub_idx = df_subida.reindex(columns=[c for c in COLS_INV if c != "Código"]).assign(Código=df_subida["Código"]).set_index("Código")

                        base_idx.update(sub_idx)
                        nuevos = sub_idx[~sub_idx.index.isin(base_idx.index)]
                        df_res = normalizar_df_inv(pd.concat([base_idx, nuevos]).reset_index())

                        if guardar_inventario(df_res, FILE_INV):
                            st.session_state["df_inv"] = df_res
                            st.success(f"Integración completada ({len(sub_idx)} códigos procesados).")
                            st.rerun()
            except Exception as e:
                st.error(f"Error al procesar archivo: {e}")

    with tab_i4:
        st.subheader("Eliminar Producto")
        if df_inv.empty:
            st.info("No hay productos para eliminar.")
        else:
            opciones = [f"{r['Código']} | {r['Producto']} (Stock: {r['Stock']})" for _, r in df_inv.iterrows()]
            sel_borrar = st.selectbox("Selecciona producto a eliminar:", opciones, key="sb_borrar_prod_tab4")
            pwd_borrar = st.text_input("Clave de autorización:", type="password", key="pwd_borrar_input_tab4")

            if st.button("Eliminar producto", type="primary", key="btn_borrar_inv_t4"):
                if pwd_borrar != ADMIN_PASSWORD:
                    st.error("Clave incorrecta.")
                else:
                    cod_borrar = sel_borrar.split(" | ")[0].strip().upper()
                    df_restante = normalizar_df_inv(
                        df_inv[df_inv["Código"].astype(str).str.strip().str.upper() != cod_borrar]
                    )
                    if guardar_inventario(df_restante, FILE_INV):
                        st.session_state["df_inv"] = df_restante
                        st.success(f"Producto `{cod_borrar}` eliminado.")
                        st.rerun()

    with tab_i5:
        st.subheader("Importar desde Excel / CSV (Reemplazo / Fusión por SKU)")
        st.caption("Normaliza columnas automáticamente y conserva el último registro por Código/SKU.")
        file_gen = st.file_uploader("Selecciona archivo (.csv o .xlsx):", type=["csv", "xlsx"], key="uploader_gen_almacen_tab5")

        if file_gen is not None:
            try:
                df_gen = _leer_archivo_inv(file_gen)
                st.dataframe(df_gen.head(10), width="stretch", hide_index=True)
                pwd_gen = st.text_input("Clave de autorización:", type="password", key="pwd_carga_gen_t5")

                if st.button("Fusionar al inventario", type="primary", key="btn_cargar_inv_t5"):
                    if pwd_gen != ADMIN_PASSWORD:
                        st.error("Clave incorrecta.")
                    elif "Código" not in df_gen.columns:
                        st.error("No se encontró columna de Código/SKU en el archivo.")
                    else:
                        df_gen_norm = normalizar_df_inv(df_gen)
                        df_gen_norm = df_gen_norm[df_gen_norm["Código"] != ""]
                        df_fusion = normalizar_df_inv(
                            pd.concat([df_inv, df_gen_norm], ignore_index=True)
                        ).drop_duplicates(subset=["Código"], keep="last")
                        if guardar_inventario(df_fusion, FILE_INV):
                            st.session_state["df_inv"] = df_fusion
                            st.success("Inventario fusionado y guardado.")
                            st.rerun()
            except Exception as e:
                st.error(f"Error al importar archivo: {e}")
