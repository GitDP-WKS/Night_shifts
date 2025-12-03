# loader.py
# Логика загрузки файлов и поиска операторов — без Streamlit

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, IO

import pandas as pd

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

logger = logging.getLogger("nightshift_loader")


@dataclass
class DetectedOperator:
    code: str
    name: str
    source: str
    column: str


class EnhancedOperatorFinder:
    """Поиск операторов в ячейках таблицы по паттернам (код, имя в скобках и т.п.)."""

    def __init__(self) -> None:
        self.operator_patterns = [
            r"(\d{6,7})\s*[\(\[{]?\s*([А-ЯЁа-яёA-Za-z\.\s\-]+)\s*[\)\]}]?",  # 7599416 (Иванов И.И.)
            r"([А-ЯЁа-яёA-Za-z\.\s\-]+)\s*[\(\[{]?\s*(\d{6,7})\s*[\)\]}]?",  # Иванов И.И. (7599416)
            r"^\s*(\d{6,7})\s*$",                                           # только код
            r"^\s*([А-ЯЁ][а-яё]+(?:\s*[А-ЯЁ]\.)?)\s*$",                      # только имя/фамилия
        ]

    def find_operators_in_dataframe(self, df: pd.DataFrame) -> List[Dict[str, str]]:
        found: List[Dict[str, str]] = []

        for col in df.columns:
            try:
                sample = df[col].dropna().astype(str).head(400)
            except Exception:
                continue

            for val in sample:
                s = str(val).strip()
                if len(s) < 2:
                    continue

                for pat in self.operator_patterns:
                    for match in re.findall(pat, s, flags=re.IGNORECASE):
                        if isinstance(match, tuple):
                            code = None
                            name = None
                            for item in match:
                                item = item.strip()
                                if re.match(r"^\d{6,7}$", item):
                                    code = item
                                elif item:
                                    name = item
                            if code or name:
                                found.append(
                                    {
                                        "code": code or f"UNKNOWN_{len(found)}",
                                        "name": name or "Неизвестно",
                                        "source": s,
                                        "column": str(col),
                                    }
                                )
                        else:
                            item = str(match).strip()
                            found.append(
                                {
                                    "code": f"UNKNOWN_{len(found)}",
                                    "name": item,
                                    "source": s,
                                    "column": str(col),
                                }
                            )

        # dedupe по коду — предпочитаем записи с именем
        uniq: Dict[str, Dict[str, str]] = {}
        for op in found:
            c = op["code"]
            if c not in uniq or (op["name"] and op["name"] != "Неизвестно"):
                uniq[c] = op
        return list(uniq.values())


class IntelligentFileLoader:
    """Чистый загрузчик файлов; не зависит от Streamlit, работает с file-like объектом."""

    def __init__(self, operator_finder: EnhancedOperatorFinder | None = None) -> None:
        self.operator_finder = operator_finder or EnhancedOperatorFinder()

    def load(self, file_obj: IO[bytes], filename: str) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
        """
        Загружает файл (xlsx/xls/csv/html/txt) из file-like объекта.
        Возвращает DataFrame и список найденных операторов (примерных).
        """
        name = filename.lower()
        # на всякий случай в начало
        try:
            file_obj.seek(0)
        except Exception:
            pass

        try:
            if name.endswith((".xlsx", ".xls")):
                df = pd.read_excel(file_obj)
            elif name.endswith(".csv"):
                df = pd.read_csv(
                    file_obj,
                    sep=None,
                    engine="python",
                    encoding="utf-8",
                    on_bad_lines="skip",
                )
            elif name.endswith((".html", ".htm")) and BeautifulSoup:
                content = file_obj.read()
                html = content.decode("utf-8", errors="ignore")
                df = self._parse_html(html)
            else:
                # txt или неизвестное расширение — читаем построчно
                content = file_obj.read()
                text = content.decode("utf-8", errors="ignore")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                df = pd.DataFrame({"text": lines})
        except Exception as e:
            logger.warning("Ошибка при чтении основного формата: %s — пытаемся fallback", e)
            try:
                file_obj.seek(0)
                content = file_obj.read().decode("utf-8", errors="ignore")
                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                df = pd.DataFrame({"text": lines})
            except Exception as ee:
                logger.error("Не удалось прочитать файл: %s", ee)
                raise

        operators = self.operator_finder.find_operators_in_dataframe(df)
        return df, operators

    @staticmethod
    def _parse_html(html: str) -> pd.DataFrame:
        if not BeautifulSoup:
            return pd.DataFrame()

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return pd.DataFrame()

        best = max(tables, key=lambda t: len(t.find_all("tr")))
        rows = []
        for tr in best.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)

        if not rows:
            return pd.DataFrame()

        if len(rows) > 1 and len(rows[0]) == len(rows[1]):
            df = pd.DataFrame(rows[1:], columns=rows[0])
        else:
            df = pd.DataFrame(rows)

        return df
