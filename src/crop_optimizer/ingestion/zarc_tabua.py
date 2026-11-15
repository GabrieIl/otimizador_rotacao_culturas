"""Tábua de risco oficial do ZARC (MAPA/Embrapa) a partir do CSV de dados abertos.

Se o CSV original não estiver em data/bronze/zarc/, o módulo tenta baixá-lo do portal
de dados abertos do MAPA (URL direta ou descoberta via API CKAN). O recorte dos
municípios consultados (manejo sequeiro, formato longo: uma linha por decêndio com risco)
é salvo em data/silver/zarc/ para leituras instantâneas nas trocas de cultura, solo,
ciclo e região.

Cada linha da tábua é uma combinação município x cultura x solo x ciclo; as colunas
dec1..dec36 trazem o risco (20, 30 ou 40 %) de plantar naquele decêndio, ou 0 quando
o plantio não é indicado.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import polars as pl

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "zarc"
DEC_COLUMNS = [f"dec{i}" for i in range(1, 37)]
_REQUIRED_COLUMNS = {
    "geocodigo",
    "municipio",
    "UF",
    "Nome_cultura",
    "Cod_Solo",
    "Cod_Ciclo",
    "Portaria",
    "Nome_Outros_Manejos",
    *DEC_COLUMNS,
}
_MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/json,*/*",
}

ProgressCallback = Callable[[int, int | None], None]


class ZarcDataUnavailable(RuntimeError):
    """A tábua do ZARC não está na bronze e não pôde ser baixada."""


@dataclass(slots=True)
class ZarcWindow:
    """Janela de plantio do ZARC para uma cultura num município (filtrada por solo/ciclo)."""

    crop_id: str
    zarc_name: str
    decendios: list[int]  # decêndios com plantio indicado para o filtro escolhido
    start_dec: int
    end_dec: int
    best_risk_pct: int  # menor risco encontrado (20, 30 ou 40)
    combos: int  # quantas combinações solo x ciclo têm janela
    portaria: str
    available_cycles: list[str] = field(default_factory=list)
    soil_group: str | None = None
    cycle_code: str | None = None

    @property
    def label(self) -> str:
        return f"{decendio_start_label(self.start_dec)} a {decendio_end_label(self.end_dec)}"


def decendio_start_label(dec: int) -> str:
    month = (dec - 1) // 3
    day = (1, 11, 21)[(dec - 1) % 3]
    return f"{day:02d}/{_MONTHS_PT[month]}"


def decendio_end_label(dec: int) -> str:
    month = (dec - 1) // 3
    part = (dec - 1) % 3
    day = (10, 20, calendar.monthrange(2027, month + 1)[1])[part]
    return f"{day:02d}/{_MONTHS_PT[month]}"


def decendio_of(month: int, day: int) -> int:
    return (month - 1) * 3 + min(2, (day - 1) // 10) + 1


def zarc_csv_path(settings: Settings | None = None) -> Path:
    cfg = load_yaml_config("zarc")
    settings = settings or get_settings()
    return settings.paths.bronze_source(SOURCE_DIR) / cfg["arquivo"]


def is_zarc_csv_cached(settings: Settings | None = None) -> bool:
    cfg = load_yaml_config("zarc")
    settings = settings or get_settings()
    return (settings.paths.bronze / SOURCE_DIR / cfg["arquivo"]).exists()


def soil_codes_for_group(soil_group: str | None) -> list[str] | None:
    if not soil_group:
        return None
    mapping = load_yaml_config("zarc").get("solo_grupos", {})
    codes = mapping.get(soil_group)
    return [str(c).strip() for c in codes] if codes else None


def cycle_label(cycle_code: str) -> str:
    ciclos = load_yaml_config("zarc").get("ciclos", {})
    return str(ciclos.get(str(cycle_code), f"Ciclo {cycle_code}"))


def _silver_path(settings: Settings, csv_name: str) -> Path:
    folder = settings.paths.silver / SOURCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / csv_name.replace(".csv", ".parquet")


def _validate_header_line(first_line: str) -> None:
    cols = {c.strip().lstrip("\ufeff") for c in first_line.split(";")}
    if "geocodigo" not in cols or "Nome_cultura" not in cols:
        raise ValueError("Arquivo baixado não contém o cabeçalho esperado do ZARC.")


def _discover_ckan_urls(client: httpx.Client, cfg: dict) -> list[str]:
    ckan_url = cfg.get("url_ckan")
    if not ckan_url:
        return []
    response = client.get(ckan_url)
    response.raise_for_status()
    resources = response.json().get("result", {}).get("resources", [])
    target_name = str(cfg.get("arquivo", "")).lower()
    safra_dash = str(cfg.get("safra", "")).replace("/", "-")
    exact: list[str] = []
    fallback: list[str] = []
    for res in resources:
        res_url = str(res.get("url") or "").strip()
        if not res_url:
            continue
        fmt = str(res.get("format") or "").lower()
        name = str(res.get("name") or "").lower()
        url_low = res_url.lower()
        if target_name and (target_name in url_low or target_name in name):
            exact.append(res_url)
        elif ("csv" in fmt or url_low.endswith(".csv")) and (
            not safra_dash or safra_dash in url_low or safra_dash in name
        ):
            fallback.append(res_url)
    return [*exact, *fallback]


def _stream_csv(
    client: httpx.Client,
    url: str,
    dest: Path,
    progress_callback: ProgressCallback | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(".csv.part")
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            ctype = response.headers.get("content-type", "").lower()
            if "text/html" in ctype:
                raise ValueError("Portal retornou página HTML no lugar do CSV.")
            raw_len = response.headers.get("content-length", "")
            total_bytes = int(raw_len) if raw_len.isdigit() else None
            downloaded = 0
            last_reported = 0
            first_line_checked = False
            buf = b""
            with tmp_path.open("wb") as fh:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    if not first_line_checked:
                        buf += chunk
                        if b"\n" in buf:
                            line = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace")
                            _validate_header_line(line)
                            first_line_checked = True
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and (downloaded - last_reported >= 524_288 or last_reported == 0):
                        progress_callback(downloaded, total_bytes)
                        last_reported = downloaded
            if not first_line_checked:
                text = buf.decode("utf-8", errors="replace")
                if not text.strip():
                    raise ValueError("Arquivo CSV do ZARC veio vazio.")
                _validate_header_line(text.splitlines()[0])
            if progress_callback:
                progress_callback(downloaded, total_bytes or downloaded)
        tmp_path.replace(dest)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def download_zarc_csv(
    dest: Path | None = None,
    cfg: dict | None = None,
    progress_callback: ProgressCallback | None = None,
    settings: Settings | None = None,
) -> Path:
    """Baixa o CSV oficial do ZARC para `dest`. Levanta `ZarcDataUnavailable` se falhar."""
    cfg = cfg or load_yaml_config("zarc")
    dest = dest or zarc_csv_path(settings)
    timeout = float(cfg.get("timeout_segundos", 120))
    primary_url = str(cfg.get("url") or "").strip()
    errors: list[str] = []

    try:
        with httpx.Client(timeout=timeout, headers=_DOWNLOAD_HEADERS, follow_redirects=True) as client:
            tried: set[str] = set()
            candidates = [primary_url] if primary_url else []
            for url in candidates:
                tried.add(url)
                try:
                    _stream_csv(client, url, dest, progress_callback=progress_callback)
                    return dest
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{url.split('/')[2]}: {exc}")

            try:
                discovered = _discover_ckan_urls(client, cfg)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"catálogo CKAN: {exc}")
                discovered = []

            for url in discovered:
                if url in tried:
                    continue
                tried.add(url)
                try:
                    _stream_csv(client, url, dest, progress_callback=progress_callback)
                    return dest
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{url}: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))

    detail = "; ".join(errors) if errors else "URL de download não configurada"
    raise ZarcDataUnavailable(
        f"Não foi possível baixar a tábua oficial do ZARC (safra {cfg['safra']}) de "
        f"dados.agricultura.gov.br ({detail}). Se estiver sem conexão, baixe '{cfg['arquivo']}' "
        f"no portal do MAPA e salve em {dest}."
    )


def load_zarc_table(
    ibge_codes: list[str],
    settings: Settings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> pl.DataFrame:
    """Recorte longo da tábua: geocodigo, cultura, solo, ciclo, portaria, decendio, risco_pct."""
    cleaned_codes = sorted({str(c).strip() for c in ibge_codes if str(c).strip()})
    if not cleaned_codes:
        raise ZarcDataUnavailable("Nenhum código IBGE válido informado para consultar o ZARC.")

    cfg = load_yaml_config("zarc")
    settings = settings or get_settings()
    csv_path = settings.paths.bronze_source(SOURCE_DIR) / cfg["arquivo"]
    silver = _silver_path(settings, cfg["arquivo"])

    codes_file = silver.with_suffix(".codigos.json")
    scanned: set[str] = set()
    if silver.exists():
        scanned = (
            {str(c).strip() for c in json.loads(codes_file.read_text(encoding="utf-8"))}
            if codes_file.exists()
            else set(pl.read_parquet(silver)["geocodigo"].unique().to_list())
        )
    if silver.exists() and set(cleaned_codes) <= scanned:
        return pl.read_parquet(silver).filter(pl.col("geocodigo").is_in(cleaned_codes))

    # Recorta a união dos códigos já salvos + novos para não perder regiões consultadas antes
    to_scan = sorted(scanned | set(cleaned_codes))

    if not csv_path.exists():
        download_zarc_csv(csv_path, cfg, progress_callback=progress_callback)

    try:
        lazy_wide = pl.scan_csv(csv_path, separator=";", infer_schema=False, encoding="utf8-lossy")
        schema_cols = set(lazy_wide.collect_schema().names())
        missing = sorted(_REQUIRED_COLUMNS - schema_cols)
        if missing:
            raise ZarcDataUnavailable(
                f"Arquivo do ZARC em {csv_path} está em formato inesperado (faltam colunas: {', '.join(missing[:5])})."
            )
        wide = (
            lazy_wide.with_columns(
                pl.col("geocodigo").str.strip_chars(),
                pl.col("Cod_Solo").str.strip_chars(),
                pl.col("Cod_Ciclo").str.strip_chars(),
            )
            .filter(pl.col("geocodigo").is_in(to_scan) & (pl.col("Nome_Outros_Manejos") == cfg["manejo"]))
            .collect()
        )
        long = (
            wide.select(
                "geocodigo",
                "municipio",
                "UF",
                pl.col("Nome_cultura").alias("cultura"),
                pl.col("Cod_Solo").alias("cod_solo"),
                pl.col("Cod_Ciclo").alias("cod_ciclo"),
                pl.col("Portaria").alias("portaria"),
                *DEC_COLUMNS,
            )
            .unpivot(
                index=["geocodigo", "municipio", "UF", "cultura", "cod_solo", "cod_ciclo", "portaria"],
                on=DEC_COLUMNS,
                variable_name="decendio",
                value_name="risco_pct",
            )
            .with_columns(
                pl.col("decendio").str.replace("dec", "").cast(pl.Int16),
                pl.col("risco_pct").cast(pl.Int16),
            )
            .filter(pl.col("risco_pct") > 0)
        )
    except ZarcDataUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ZarcDataUnavailable(f"Erro ao ler a tábua do ZARC em {csv_path}: {exc}") from exc

    long.write_parquet(silver)
    codes_file.write_text(json.dumps(to_scan), encoding="utf-8")
    return long.filter(pl.col("geocodigo").is_in(cleaned_codes))


def _circular_span(decs: list[int]) -> tuple[int, int]:
    """Início e fim da janela olhando o ano como círculo (ex.: nov-jan cruza a virada)."""
    present = sorted(set(decs))
    if len(present) == 36:
        return 1, 36
    best_gap, start = -1, present[0]
    for i, dec in enumerate(present):
        nxt = present[(i + 1) % len(present)]
        gap = (nxt - dec - 1) % 36
        if gap > best_gap:
            best_gap, start = gap, nxt
    end = present[(present.index(start) - 1) % len(present)]
    return start, end


def _filter_crop_rows(
    local: pl.DataFrame,
    zarc_name: str,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> tuple[pl.DataFrame, list[str]]:
    rows = local.filter(pl.col("cultura") == zarc_name)
    soil_codes = soil_codes_for_group(soil_group)
    if soil_codes is not None:
        rows = rows.filter(pl.col("cod_solo").is_in(soil_codes))
    available_cycles = sorted({str(c) for c in rows["cod_ciclo"].unique().to_list()}) if not rows.is_empty() else []
    if cycle_code and cycle_code != "todos":
        rows = rows.filter(pl.col("cod_ciclo") == cycle_code)
    return rows, available_cycles


def zarc_windows_for(
    table: pl.DataFrame,
    ibge_code: str,
    crop_map: dict[str, str] | None = None,
    *,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> dict[str, ZarcWindow | None]:
    """Janela por cultura do motor; None quando o ZARC não indica plantio de sequeiro."""
    crop_map = crop_map or load_yaml_config("zarc")["culturas"]
    local = table.filter(pl.col("geocodigo") == ibge_code)
    out: dict[str, ZarcWindow | None] = {}
    selected_cycle = None if not cycle_code or cycle_code == "todos" else cycle_code
    for crop_id, zarc_name in crop_map.items():
        rows, available_cycles = _filter_crop_rows(local, zarc_name, soil_group=soil_group, cycle_code=selected_cycle)
        if rows.is_empty():
            out[crop_id] = None
            continue
        decs = rows["decendio"].to_list()
        start, end = _circular_span(decs)
        out[crop_id] = ZarcWindow(
            crop_id=crop_id,
            zarc_name=zarc_name,
            decendios=sorted(set(decs)),
            start_dec=start,
            end_dec=end,
            best_risk_pct=int(rows["risco_pct"].min()),
            combos=rows.select("cod_solo", "cod_ciclo").unique().height,
            portaria=rows["portaria"][0],
            available_cycles=available_cycles,
            soil_group=soil_group,
            cycle_code=selected_cycle,
        )
    return out


def zarc_decendios_for_crops(
    table: pl.DataFrame,
    ibge_code: str,
    crop_map: dict[str, str] | None = None,
    *,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> dict[str, list[int]]:
    """Menor risco (20/30/40) nos 36 decêndios para cada cultura; 0 = não indicado."""
    crop_map = crop_map or load_yaml_config("zarc")["culturas"]
    local = table.filter(pl.col("geocodigo") == ibge_code)
    out: dict[str, list[int]] = {}
    selected_cycle = None if not cycle_code or cycle_code == "todos" else cycle_code
    for crop_id, zarc_name in crop_map.items():
        decs = [0] * 36
        rows, _ = _filter_crop_rows(local, zarc_name, soil_group=soil_group, cycle_code=selected_cycle)
        for dec, risk in rows.group_by("decendio").agg(pl.col("risco_pct").min()).iter_rows():
            decs[int(dec) - 1] = int(risk)
        out[crop_id] = decs
    return out
