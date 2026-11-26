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
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
    return f"{prefijo}{max_num + 1:02d}"
