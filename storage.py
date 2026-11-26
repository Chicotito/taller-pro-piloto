import base64
import datetime as dt
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FILE_SERV_PREV = DATA_DIR / "servicios_preventivos.csv"
FILE_VENTAS = DATA_DIR / "ventas.csv"

COLS_SP = [
    "Folio_Prev",
    "Cliente",
    "Telefono",
    "Vehiculo",
    "Anio",
    "No_Economico",
    "Refrigerante",
    "Servicio_Preventivo",
    "Fecha_Servicio",
    "Meses_Intervalo",
    "Proximo_Servicio",
    "Kilometraje",
    "Estado",
    "Monto",
    "Observaciones",
]

COLS_VT = [
    "Folio_Venta",
    "Folio_Referencia",
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


def _sincronizar_a_github(ruta_local: Path, contenido_texto: str, mensaje_commit: str) -> None:
    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        return

    token = str(secrets.get("GITHUB_TOKEN", "")).strip()
    repo = str(secrets.get("GITHUB_REPO", "")).strip()
    branch = str(secrets.get("GITHUB_BRANCH", "main")).strip() or "main"

    if not token or not repo:
        st.warning("Sincronización GitHub omitida: falta GITHUB_TOKEN o GITHUB_REPO en Secrets.")
        return

    try:
        ruta_repo = ruta_local.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        ruta_repo = f"data/{ruta_local.name}"

    url = f"https://api.github.com/repos/{repo}/contents/{ruta_repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "taller-pro-app",
    }

    sha = None
    try:
        req_get = urllib.request.Request(f"{url}?ref={branch}", headers=headers, method="GET")
        with urllib.request.urlopen(req_get, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            st.warning(f"Error consultando archivo en GitHub ({e.code}): {e.reason}")
            return
    except Exception as e:
        st.warning(f"Error de red al consultar GitHub: {e}")
        return

    payload = {
        "message": mensaje_commit,
        "content": base64.b64encode(contenido_texto.encode("utf-8-sig")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        req_put = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req_put, timeout=15):
            pass
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="ignore")
        st.error(f"GitHub rechazó el guardado ({e.code}): {detalle[:220]}")
    except Exception as e:
        st.error(f"Error enviando datos a GitHub: {e}")


def normalizar_df_sp(df_in: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df_in, pd.DataFrame):
        df_n = pd.DataFrame(columns=COLS_SP)
    else:
        df_n = df_in.copy()

    for col in COLS_SP:
        if col not in df_n.columns:
            df_n[col] = ""

    df_n = df_n[COLS_SP].copy()

    cols_texto = [c for c in COLS_SP if c not in ["Meses_Intervalo", "Monto"]]
    for col in cols_texto:
        df_n[col] = df_n[col].where(df_n[col].notna(), "").astype(str).str.strip()
        df_n.loc[df_n[col].str.lower().isin(["nan", "none", "<na>"]), col] = ""

    df_n["Meses_Intervalo"] = (
        pd.to_numeric(df_n["Meses_Intervalo"], errors="coerce").fillna(6).astype(int)
    )
    df_n["Monto"] = (
        pd.to_numeric(df_n["Monto"], errors="coerce").fillna(0.0).round(2)
    )
    df_n["Estado"] = df_n["Estado"].replace("", "Programado")
    return df_n


def cargar_servicios_prev(ruta_csv: Path = FILE_SERV_PREV) -> pd.DataFrame:
    ruta = Path(ruta_csv)
    if not ruta.exists():
        return normalizar_df_sp(pd.DataFrame(columns=COLS_SP))

    df_csv = pd.read_csv(ruta, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return normalizar_df_sp(df_csv)


def guardar_servicios_prev(df_g: pd.DataFrame, ruta_csv: Path = FILE_SERV_PREV) -> bool:
    ruta = Path(ruta_csv)
    df_limpio = normalizar_df_sp(df_g)
    try:
        csv_texto = df_limpio.to_csv(index=False, encoding="utf-8-sig")
        ruta.write_text(csv_texto, encoding="utf-8-sig")
        _sincronizar_a_github(ruta, csv_texto, f"Actualizar {ruta.name}")
        return True
    except OSError:
        return False


def normalizar_df_vt(df_in: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df_in, pd.DataFrame):
        df_n = pd.DataFrame(columns=COLS_VT)
    else:
        df_n = df_in.copy()

    for col in COLS_VT:
        if col not in df_n.columns:
            df_n[col] = ""

    df_n = df_n[COLS_VT].copy()

    cols_texto = [c for c in COLS_VT if c not in ["Cantidad", "Precio_Unitario", "Total"]]
    for col in cols_texto:
        df_n[col] = df_n[col].where(df_n[col].notna(), "").astype(str).str.strip()
        df_n.loc[df_n[col].str.lower().isin(["nan", "none", "<na>"]), col] = ""

    df_n["Cantidad"] = (
        pd.to_numeric(df_n["Cantidad"], errors="coerce").fillna(1).astype(int)
    )
    df_n["Precio_Unitario"] = (
        pd.to_numeric(df_n["Precio_Unitario"], errors="coerce").fillna(0.0).round(2)
    )
    df_n["Total"] = (
        pd.to_numeric(df_n["Total"], errors="coerce").fillna(0.0).round(2)
    )
    df_n["Estado_Pago"] = df_n["Estado_Pago"].replace("", "Pagado")
    return df_n


def cargar_ventas(ruta_csv: Path = FILE_VENTAS) -> pd.DataFrame:
    ruta_f = Path(ruta_csv)
    if not ruta_f.exists():
        return normalizar_df_vt(pd.DataFrame(columns=COLS_VT))

    df_csv = pd.read_csv(ruta_f, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return normalizar_df_vt(df_csv)


def guardar_ventas(df_g: pd.DataFrame, ruta_csv: Path = FILE_VENTAS) -> bool:
    ruta_f = Path(ruta_csv)
    df_limpio = normalizar_df_vt(df_g)
    try:
        csv_texto = df_limpio.to_csv(index=False, encoding="utf-8-sig")
        ruta_f.write_text(csv_texto, encoding="utf-8-sig")
        _sincronizar_a_github(ruta_f, csv_texto, f"Actualizar {ruta_f.name}")
        return True
    except OSError:
        return False


def calcular_proximo_servicio(fecha_servicio: str, meses_intervalo: int) -> str:
    txt = (fecha_servicio or "").strip()
    if not txt:
        return ""
    try:
        fb = dt.date.fromisoformat(txt)
    except ValueError:
        return ""
    meses = max(1, int(meses_intervalo))
    total_meses = (fb.year * 12 + (fb.month - 1)) + meses
    yp, mp_idx = divmod(total_meses, 12)
    mp = mp_idx + 1
    siguiente_mes_y = yp + (1 if mp == 12 else 0)
    siguiente_mes_m = 1 if mp == 12 else mp + 1
    ultimo_dia = (dt.date(siguiente_mes_y, siguiente_mes_m, 1) - dt.timedelta(days=1)).day
    return dt.date(yp, mp, min(fb.day, ultimo_dia)).isoformat()


def siguiente_folio_sp(df_sp: pd.DataFrame, prefijo: str = "SP-") -> str:
    max_num = 0
    if isinstance(df_sp, pd.DataFrame) and "Folio_Prev" in df_sp.columns:
        for val in df_sp["Folio_Prev"].tolist():
            m = re.search(r"(\d+)$", str(val or "").strip())
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{prefijo}{max_num + 1:02d}"


def siguiente_folio_vt(df_vt: pd.DataFrame, prefijo: str = "V-") -> str:
    max_num = 0
    if isinstance(df_vt, pd.DataFrame) and "Folio_Venta" in df_vt.columns:
        for val in df_vt["Folio_Venta"].tolist():
            if val is None:
                continue
            s = str(val).strip()
            if not s or s.lower() == "nan":
                continue
            m = re.search(r"(\d+)$", s)
            ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "1234") if hasattr(st, "secrets") else "1234"

st.caption(f"Archivo de datos: `{FILE_INV}`")

if st.button("🔄 Forzar Recarga de Inventario", key="btn_recarga_inv"):
    try:
        st.session_state["df_inv"] = normalizar_df_inv(cargar_inventario(FILE_INV))
        st.success("¡Inventario recargado con éxito!")
        st.rerun()
    except Exception as e:
        st.error(f"Error al recargar: {e}")

if "df_inv" in st.session_state and not st.session_state["df_inv"].empty:
    df_inv = normalizar_df_inv(st.session_state["df_inv"])
else:
    try:
        df_inv = normalizar_df_inv(cargar_inventario(FILE_INV))
        st.session_state["df_inv"] = df_inv
    except Exception:
        df_inv = pd.DataFrame(columns=COLS_INV)

tab_i1, tab_i2, tab_i3, tab_i4, tab_i5 = st.tabs([
    "📋 Consultar / Editar Inventario",
    "➕ Registrar Nuevo Producto",
    "📥 Subir Códigos / Carga Masiva",
    "🗑️ Eliminar Producto",
    "📁 Cargar desde Excel / CSV",
])

# --- TAB 1: CONSULTAR Y EDITAR POR FAMILIA ---
with tab_i1:
    st.subheader("📋 Consultar y Editar Inventario por Familia")
    st.caption("Filtra por familia para visualizar refacciones específicas o edita los campos directamente en la tabla.")

    if df_inv.empty:
        st.info("No hay productos en inventario.")
    else:
        df_inv_clean = normalizar_df_inv(df_inv)
        familias_disponibles = ["Todas las Familias"] + sorted(
            [f for f in df_inv_clean["Familia"].unique() if f]
        )
        col_f1, col_f2 = st.columns([2, 2])
        with col_f1:
            familia_sel = st.selectbox(
                "📂 Filtrar por Familia / Categoría:",
                familias_disponibles,
                key="sb_filtro_familia",
            )
        with col_f2:
            calc_auto = st.checkbox(
                "⚡ Recalcular Precio Venta automáticamente (Costo × 1.60)",
                value=False,
                key="chk_calc_auto_inv",
            )

        if familia_sel != "Todas las Familias":
            df_mostrar = df_inv_clean[df_inv_clean["Familia"].str.upper() == familia_sel.upper()].copy()
        else:
            df_mostrar = df_inv_clean.copy()

        df_inv_edit = st.data_editor(
            df_mostrar,
            column_config={
                "Código": st.column_config.TextColumn("Código / SKU", required=True),
                "Producto": st.column_config.TextColumn("Producto", required=True),
                "Familia": st.column_config.TextColumn("Familia / Línea", required=True),
                "Stock": st.column_config.NumberColumn("Stock", min_value=0.0, step=1.0, format="%.2f"),
                "Costo": st.column_config.NumberColumn("Costo ($)", format="$%,.2f", min_value=0.0),
                "Precio Venta": st.column_config.NumberColumn("Precio Venta ($)", format="$%,.2f", min_value=0.0),
            },
            use_container_width=True,
            hide_index=True,
            key="editor_inv",
        )

        st.divider()
        col_p1, col_p2 = st.columns([2, 1])
        with col_p1:
            pwd_edit = st.text_input("Clave de Modificación:", type="password", key="pwd_edit_inv")
        with col_p2:
            st.write("")
            st.write("")
            btn_guardar = st.button("💾 Guardar Cambios", type="primary", key="btn_guardar_inv_t1")

        if btn_guardar:
            if pwd_edit != ADMIN_PASSWORD:
                st.error("🔑 Clave incorrecta.")
            else:
                edit_norm = normalizar_df_inv(df_inv_edit)
                if calc_auto:
                    edit_norm["Precio Venta"] = (edit_norm["Costo"] * 1.60).round(2)

                if familia_sel != "Todas las Familias":
                    df_resto = df_inv_clean[df_inv_clean["Familia"].str.upper() != familia_sel.upper()]
                    df_final = pd.concat([df_resto, edit_norm], ignore_index=True)
                else:
                    df_final = edit_norm.copy()

                df_validos = df_final[
                    (df_final["Código"] != "")
                    & (df_final["Código"].str.lower() != "nan")
                    & (~df_final["Código"].str.startswith("#"))
                ]

                duplicados = df_validos["Código"].value_counts()
                duplicados = duplicados[duplicados > 1].index.tolist()

                if duplicados:
                    st.error(f"⚠️ El código/SKU '{duplicados[0]}' está repetido. Cada producto debe tener un identificador único.")
                else:
                    if guardar_inventario(df_final, FILE_INV):
                        st.session_state["df_inv"] = normalizar_df_inv(df_final)
                        st.success("¡Inventario, familias, costos y precios actualizados con éxito!")
                        st.rerun()

# --- TAB 2: REGISTRAR PRODUCTO MANUALMENTE ---
with tab_i2:
    st.subheader("Registrar Producto Manualmente")
    with st.form("form_nuevo_prod", clear_on_submit=True):
        n_codigo = st.text_input("Código / SKU:").strip().upper()
        n_producto = st.text_input("Nombre del Producto:").strip()
        n_familia = st.text_input("Familia / Categoría:", value="General").strip()
        n_stock = st.number_input("Stock Inicial:", min_value=0.0, step=1.0, value=0.0)
        n_costo = st.number_input("Costo de Compra ($):", min_value=0.0, format="%.2f")
        sug_precio = round(n_costo * 1.60, 2) if n_costo > 0 else 0.0
        n_precio = st.number_input("Precio de Venta ($):", min_value=0.0, value=sug_precio, format="%.2f")
        pwd_nuevo = st.text_input("Clave de Autorización:", type="password")

        if st.form_submit_button("Guardar Producto", type="primary"):
            if pwd_nuevo != ADMIN_PASSWORD:
                st.error("🔑 Clave incorrecta.")
            elif not n_codigo or not n_producto:
                st.error("El código y nombre son obligatorios.")
            elif not df_inv.empty and (df_inv["Código"].str.upper() == n_codigo).any():
                st.error(f"⚠️ El código '{n_codigo}' ya existe en el inventario.")
            else:
                nuevo_item = pd.DataFrame([{
                    "Código": n_codigo,
                    "Producto": n_producto,
                    "Familia": n_familia if n_familia else "General",
                    "Stock": float(n_stock),
                    "Costo": float(n_costo),
                    "Precio Venta": float(n_precio),
                }])
                df_inv_temp = normalizar_df_inv(pd.concat([df_inv, nuevo_item], ignore_index=True))
                if guardar_inventario(df_inv_temp, FILE_INV):
                    st.session_state["df_inv"] = df_inv_temp
                    st.success(f"Producto '{n_producto}' registrado con éxito.")
                    st.rerun()

# --- TAB 3: SUBIDA Y CARGA MASIVA DE CÓDIGOS ---
with tab_i3:
    st.subheader("📥 Subida y Carga Masiva de Códigos")
    st.write("Sube un archivo `.csv` o `.xlsx` con tus códigos de inventario.")

    csv_plantilla_inv = (
        "Código,Producto,Familia,Stock,Costo,Precio Venta\n"
        "SKU-001,Filtro Cabina A/C,Filtros,15,120.00,192.00"
    )
    st.download_button(
        "📥 Descargar Plantilla",
        csv_plantilla_inv,
        "plantilla_inventario.csv",
        "text/csv",
        key="dl_plantilla_inv",
    )

    st.divider()
    file_codigos = st.file_uploader(
        "Selecciona archivo de códigos:",
        type=["csv", "xlsx"],
        key="uploader_codigos_custom",
    )
    if file_codigos is not None:
        try:
            if file_codigos.name.lower().endswith(".csv"):
                try:
                    df_subida = pd.read_csv(file_codigos, dtype=str, encoding="utf-8")
                except UnicodeDecodeError:
                    file_codigos.seek(0)
                    df_subida = pd.read_csv(file_codigos, dtype=str, encoding="latin-1")
            else:
                df_subida = pd.read_excel(file_codigos, dtype=str)

            df_subida.columns = df_subida.columns.str.strip()

            renombres_map = {}
            for col in df_subida.columns:
                col_low = col.lower().strip()
                if any(k in col_low for k in ["cód", "cod", "sku", "clave", "id"]):
                    renombres_map[col] = "Código"
                elif any(k in col_low for k in ["prod", "desc", "nombre"]):
                    renombres_map[col] = "Producto"
                elif any(k in col_low for k in ["fam", "cat", "lin"]):
                    renombres_map[col] = "Familia"
                elif any(k in col_low for k in ["stock", "cant", "exist"]):
                    renombres_map[col] = "Stock"
                elif "cost" in col_low:
                    renombres_map[col] = "Costo"
                elif any(k in col_low for k in ["precio", "venta"]):
                    renombres_map[col] = "Precio Venta"

            df_subida.rename(columns=renombres_map, inplace=True)
            st.write("📋 **Vista previa de los datos a importar:**")
            st.dataframe(df_subida.head(10), use_container_width=True, hide_index=True)

            pwd_subida = st.text_input(
                "Clave de Autorización de Administrador:",
                type="password",
                key="pwd_subida_codigos",
            )

            if st.button("🚀 Importar e Integrar Códigos al Inventario General", key="btn_importar_inv"):
                if pwd_subida != ADMIN_PASSWORD:
                    st.error("🔑 Clave incorrecta.")
                elif "Código" not in df_subida.columns:
                    st.error("⚠️ El archivo no contiene una columna válida para 'Código'.")
                else:
                    for col_num in ["Costo", "Precio Venta", "Stock"]:
                        if col_num in df_subida.columns:
                            df_subida[col_num] = (
                                df_subida[col_num]
                                .astype(str)
                                .str.replace("$", "", regex=False)
                                .str.replace(",", "", regex=False)
                                .str.strip()
                            )
                            df_subida[col_num] = pd.to_numeric(df_subida[col_num], errors="coerce")

                    if "Familia" not in df_subida.columns:
                        df_subida["Familia"] = "General"
                    if "Producto" not in df_subida.columns:
                        df_subida["Producto"] = "Sin Nombre"

                    df_subida["Código"] = df_subida["Código"].fillna("").astype(str).str.strip().str.upper()
                    df_subida["Producto"] = df_subida["Producto"].fillna("Sin Nombre").astype(str).str.strip()
                    df_subida["Familia"] = df_subida["Familia"].fillna("General").astype(str).str.strip()
                    df_subida.loc[df_subida["Familia"] == "", "Familia"] = "General"

                    df_subida = df_subida[df_subida["Código"] != ""].drop_duplicates(subset=["Código"], keep="last")

                    df_inv_act = normalizar_df_inv(df_inv).drop_duplicates(subset=["Código"], keep="last")
                    df_inv_act.set_index("Código", inplace=True)
                    df_subida_idx = df_subida.set_index("Código")

                    df_inv_act.update(df_subida_idx)
                    nuevos_codigos = df_subida_idx[~df_subida_idx.index.isin(df_inv_act.index)]
                    df_resultado = normalizar_df_inv(pd.concat([df_inv_act, nuevos_codigos]).reset_index())

                    if guardar_inventario(df_resultado, FILE_INV):
                        st.session_state["df_inv"] = df_resultado
                        st.success("¡Inventario actualizado e integrado correctamente!")
                        st.rerun()
        except Exception as e:
            st.error(f"Error al procesar el archivo: {e}")

# --- TAB 4: ELIMINAR PRODUCTO ---
with tab_i4:
    st.subheader("🗑️ Eliminar Producto o Código Erróneo")
    st.write("Selecciona un código para removerlo del inventario general.")

    if df_inv.empty:
        st.info("No hay registros en el inventario para eliminar.")
    else:
        opciones_borrar = [f"Cód: {r['Código']} | {r['Producto']}" for _, r in df_inv.iterrows()]
        prod_a_borrar = st.selectbox(
            "Selecciona el artículo a eliminar:",
            opciones_borrar,
            key="sb_borrar_prod_tab4",
        )
        pwd_borrar = st.text_input(
            "Clave de Administrador para Borrar:",
            type="password",
            key="pwd_borrar_input_tab4",
        )

        if st.button("🗑️ Eliminar Producto Seleccionado", type="primary", key="btn_borrar_inv_t4"):
            if pwd_borrar != ADMIN_PASSWORD:
                st.error("🔑 Clave incorrecta de administrador.")
            else:
                codigo_a_quitar = prod_a_borrar.split(" | ")[0].replace("Cód: ", "").strip().upper()
                df_inv_filtrado = normalizar_df_inv(
                    df_inv[df_inv["Código"].astype(str).str.strip().str.upper() != codigo_a_quitar]
                )
                if guardar_inventario(df_inv_filtrado, FILE_INV):
                    st.session_state["df_inv"] = df_inv_filtrado
                    st.success(f"🗑️ El código **{codigo_a_quitar}** ha sido eliminado del inventario correctamente.")
                    st.rerun()

# --- TAB 5: CARGAR DESDE EXCEL / CSV GENERAL ---
with tab_i5:
    st.subheader("📁 Cargar desde Excel / CSV (General)")
    st.write("Herramienta rápida para fusionar catálogos completos.")
    file_subida_gen = st.file_uploader(
        "Selecciona archivo CSV o Excel general:",
        type=["csv", "xlsx"],
        key="uploader_gen_almacen_tab5",
    )
    if file_subida_gen is not None:
        try:
            if file_subida_gen.name.lower().endswith(".csv"):
                try:
                    df_sub = pd.read_csv(file_subida_gen, dtype=str, encoding="utf-8")
                except UnicodeDecodeError:
                    file_subida_gen.seek(0)
                    df_sub = pd.read_csv(file_subida_gen, dtype=str, encoding="latin-1")
            else:
                df_sub = pd.read_excel(file_subida_gen, dtype=str)

            df_sub.columns = df_sub.columns.str.strip()
            st.dataframe(df_sub.head(5), use_container_width=True, hide_index=True)
            pwd_carga_t5 = st.text_input(
                "Clave de Administrador para Carga General:",
                type="password",
                key="pwd_carga_gen_t5",
            )

            if st.button("🚀 Integrar al Inventario General (Tab 5)", key="btn_cargar_inv_t5"):
                if pwd_carga_t5 != ADMIN_PASSWORD:
                    st.error("🔑 Clave incorrecta.")
                else:
                    df_fusion = normalizar_df_inv(pd.concat([df_inv, normalizar_df_inv(df_sub)], ignore_index=True))
                    if guardar_inventario(df_fusion, FILE_INV):
                        st.session_state["df_inv"] = df_fusion
                        st.success("¡Inventario general actualizado correctamente!")
                        st.rerun()
        except Exception as e:
            st.error(f"Error al procesar archivo: {e}")
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
    return f"{prefijo}{max_num + 1:02d}"
