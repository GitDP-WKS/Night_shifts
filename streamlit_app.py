# streamlit_app.py
# -*- coding: utf-8 -*-
"""
Streamlit Call-Center Night Shift Analyzer — Card UI (Русский)
Версия: красивая, понятная, готовая к использованию всеми сотрудниками.

Особенности:
- Централизованные карточки настроек (настройки объяснены на русском).
- Мультивыбор операторов (несколько операторов одновременно).
- Фильтр по диапазону дат (если в данных есть даты).
- Интерактивные Plotly графики: столбчатая диаграмма, линия активности, heatmap.
- Экспорт отчёта в Excel (скачивание).
- Кэширование загрузки/анализа для плавной работы.
- Дружелюбные подсказки и инструкции прямо в UI.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import re
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Tuple
from io import BytesIO

import plotly.express as px
import plotly.graph_objects as go

# Optional HTML parser
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streamlit_nightshift_cards")

# -------------------------
# Streamlit page config
# -------------------------
st.set_page_config(page_title="Анализ ночной смены — карточки", layout="wide")
st.title("📊 Анализ ночной смены — понятный интерфейс")
st.markdown(
    """
Добро пожаловать! Это интуитивно понятный инструмент для анализа ночных смен колл-центра.  
Загрузите файл (Excel/CSV/HTML/TXT), настройте фильтры в карточках ниже и получите:
- интерактивные графики,
- таблицы активности и статистику,
- скачиваемый Excel-отчёт.
"""
)

# -------------------------
# Типы данных и структуры
# -------------------------
@dataclass
class TimeInterval:
    start: datetime
    end: datetime
    label: str


# -------------------------
# Утилиты: поиск операторов
# -------------------------
class EnhancedOperatorFinder:
    """Поиск операторов в ячейках таблицы по паттернам (код, имя в скобках и т.п.)."""

    def __init__(self):
        self.operator_patterns = [
            r"(\d{6,7})\s*[\(\[{]?\s*([А-ЯЁа-яёA-Za-z\.\s\-]+)\s*[\)\]}]?",
            r"([А-ЯЁа-яёA-Za-z\.\s\-]+)\s*[\(\[{]?\s*(\d{6,7})\s*[\)\]}]?",
            r"^\s*(\d{6,7})\s*$",
            r"^\s*([А-ЯЁ][а-яё]+(?:\s*[А-ЯЁ]\.)?)\s*$",
        ]

    def find_operators_in_dataframe(self, df: pd.DataFrame) -> List[Dict[str, str]]:
        found = []
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
                                found.append({
                                    "code": code or f"UNKNOWN_{len(found)}",
                                    "name": name or "Неизвестно",
                                    "source": s,
                                    "column": str(col)
                                })
                        else:
                            item = match.strip()
                            found.append({
                                "code": f"UNKNOWN_{len(found)}",
                                "name": item,
                                "source": s,
                                "column": str(col)
                            })
        # dedupe: по коду, предпочитаем записи с именем
        uniq = {}
        for op in found:
            c = op["code"]
            if c not in uniq or (op["name"] and op["name"] != "Неизвестно"):
                uniq[c] = op
        return list(uniq.values())


# -------------------------
# Интеллектуальная загрузка файлов
# -------------------------
class IntelligentFileLoader:
    def __init__(self):
        self.operator_finder = EnhancedOperatorFinder()

    @st.cache_data(show_spinner=False)
    def load_file(_self, _uploaded) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
        """
        Загружает файл — xlsx/xls/csv/html/txt.
        Возвращает DataFrame и список найденных операторов (примерных).
        """
        name = _uploaded.name.lower()
        try:
            if name.endswith((".xlsx", ".xls")):
                df = pd.read_excel(_uploaded)
            elif name.endswith(".csv"):
                df = pd.read_csv(_uploaded, sep=None, engine="python", encoding="utf-8", on_bad_lines="skip")
            elif name.endswith((".html", ".htm")) and BeautifulSoup:
                html = _uploaded.read().decode("utf-8", errors="ignore")
                df = _self._parse_html(html)
            else:
                text = _uploaded.read().decode("utf-8", errors="ignore")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                df = pd.DataFrame({"text": lines})
        except Exception as e:
            logger.warning("Ошибка при чтении основного формата: %s — пытаем fallback", e)
            try:
                _uploaded.seek(0)
            except Exception:
                pass
            try:
                content = _uploaded.read().decode("utf-8", errors="ignore")
                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                df = pd.DataFrame({"text": lines})
            except Exception as ee:
                logger.error("Не удалось прочитать файл: %s", ee)
                raise

        operators = _self.operator_finder.find_operators_in_dataframe(df)
        return df, operators

    def _parse_html(self, html: str) -> pd.DataFrame:
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


# -------------------------
# Analyzer
# -------------------------
class NightShiftAnalyzer:
    INTERVAL_MINUTES = 30
    NIGHT_SHIFT_START_HOUR = 18
    NIGHT_SHIFT_START_MINUTE = 30
    SHIFT_DURATION_HOURS = 12
    NIGHT_OPERATOR_THRESHOLD = 4

    def create_intervals(self, base_date: datetime) -> List[TimeInterval]:
        start = base_date.replace(hour=self.NIGHT_SHIFT_START_HOUR,
                                  minute=self.NIGHT_SHIFT_START_MINUTE,
                                  second=0, microsecond=0)
        end = start + timedelta(hours=self.SHIFT_DURATION_HOURS)
        intervals = []
        cur = start
        while cur < end:
            nxt = cur + timedelta(minutes=self.INTERVAL_MINUTES)
            intervals.append(TimeInterval(start=cur, end=nxt, label=f"{cur.strftime('%H:%M')}-{nxt.strftime('%H:%M')}"))
            cur = nxt
        return intervals

    @staticmethod
    def _extract_operator_name(value) -> str:
        if pd.isna(value):
            return "Неизвестно"
        s = str(value)
        m = re.search(r"\((.*?)\)", s)
        if m:
            return m.group(1).strip()
        return s.strip()

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Попытка определить колонки: время начала, длительность, оператор.
        Если не найдены, используются первые 3 колонки как fallback.
        Возвращает df с колонками: start_datetime, duration_seconds, end_datetime, operator_name.
        """
        col_map = {}
        col_names = list(df.columns)
        for c in col_names:
            lc = str(c).lower()
            if not col_map.get("start") and any(k in lc for k in ("начало", "start", "время", "date", "time")):
                col_map["start"] = c
            if not col_map.get("duration") and any(k in lc for k in ("длитель", "duration", "length", "sec")):
                col_map["duration"] = c
            if not col_map.get("operator") and any(k in lc for k in ("агент", "оператор", "agent", "operator", "имя", "имена")):
                col_map["operator"] = c

        if "start" not in col_map and len(col_names) >= 1:
            col_map["start"] = col_names[0]
        if "duration" not in col_map and len(col_names) >= 2:
            col_map["duration"] = col_names[1]
        if "operator" not in col_map and len(col_names) >= 3:
            col_map["operator"] = col_names[2]

        dfc = df.copy()
        dfc["start_datetime"] = pd.to_datetime(dfc[col_map["start"]], errors="coerce", dayfirst=True)

        def _parse_duration(v):
            if pd.isna(v):
                return 0
            s = str(v).strip()
            if ":" in s:
                parts = [int(x) for x in re.findall(r"\d+", s)]
                if len(parts) == 3:
                    return parts[0] * 3600 + parts[1] * 60 + parts[2]
                if len(parts) == 2:
                    return parts[0] * 60 + parts[1]
            try:
                return int(float(s))
            except Exception:
                return 0

        dfc["duration_seconds"] = dfc[col_map["duration"]].apply(_parse_duration)
        dfc["operator_name"] = dfc[col_map["operator"]].apply(self._extract_operator_name)
        dfc = dfc.dropna(subset=["start_datetime"]).reset_index(drop=True)
        dfc["end_datetime"] = dfc["start_datetime"] + pd.to_timedelta(dfc["duration_seconds"], unit="s")
        return dfc

    def analyze(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        dfc = self.prepare_dataframe(df)
        if dfc.empty:
            raise ValueError("Нет валидных временных данных для анализа")

        base = dfc["start_datetime"].min().replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = self.create_intervals(base)
        shift_start = base.replace(hour=self.NIGHT_SHIFT_START_HOUR, minute=self.NIGHT_SHIFT_START_MINUTE)
        shift_end = shift_start + timedelta(hours=self.SHIFT_DURATION_HOURS)

        # определение ночных операторов
        night_ops = []
        for op in sorted(dfc["operator_name"].unique()):
            op_data = dfc[dfc["operator_name"] == op]
            mask = (op_data["start_datetime"] >= shift_start) & (op_data["start_datetime"] < shift_end)
            calls = mask.sum()
            active_intervals = sum(((op_data["start_datetime"] >= it.start) & (op_data["start_datetime"] < it.end)).any() for it in intervals)
            if calls > 0 and active_intervals >= self.NIGHT_OPERATOR_THRESHOLD:
                night_ops.append(op)

        if not night_ops:
            raise ValueError("Не найдено операторов ночной смены. Проверьте входные данные или параметры.")

        labels = [it.label for it in intervals]
        activity_df = pd.DataFrame(index=labels, columns=night_ops)
        calls_df = pd.DataFrame(index=labels, columns=night_ops)
        total_calls_by_operator = {}

        for op in night_ops:
            op_data = dfc[dfc["operator_name"] == op]
            shift_mask = (op_data["start_datetime"] >= shift_start) & (op_data["start_datetime"] < shift_end)
            total_calls = int(shift_mask.sum())
            total_calls_by_operator[op] = total_calls
            flags = []
            counts = []
            for it in intervals:
                mask = (op_data["start_datetime"] >= it.start) & (op_data["start_datetime"] < it.end)
                cnt = int(mask.sum())
                counts.append(cnt)
                flags.append("Работал" if cnt > 0 else "Спал")
            activity_df[op] = flags
            calls_df[op] = counts

        calls_df["Всего_звонков_за_интервал"] = calls_df[night_ops].sum(axis=1)
        stats_df = self.generate_statistics(activity_df, night_ops, total_calls_by_operator, calls_df)

        # проверка согласованности сумм
        total_calls_all = sum(total_calls_by_operator.values())
        total_from_intervals = int(calls_df[night_ops].sum().sum())
        if total_calls_all != total_from_intervals:
            logger.warning("Несоответствие сумм звонков: суммарно=%d, по интервалам=%d", total_calls_all, total_from_intervals)

        return activity_df, stats_df, calls_df

    @staticmethod
    def generate_statistics(activity_df: pd.DataFrame, operators: List[str], call_counts: Dict[str, int], calls_df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for op in operators:
            act = activity_df[op]
            total_intervals = len(act)
            active_intervals = (act == "Работал").sum()
            pct = round(active_intervals / total_intervals * 100, 2) if total_intervals > 0 else 0.0
            calls_from_intervals = int(calls_df[op].sum())
            rows.append({
                "Оператор": op,
                "Всего интервалов": total_intervals,
                "Активных интервалов": int(active_intervals),
                "% активности": pct,
                "Звонков за смену": call_counts.get(op, 0),
                "Звонков (проверка)": calls_from_intervals
            })
        return pd.DataFrame(rows)


# -------------------------
# Plotly визуализации
# -------------------------
def plot_calls_bar_interactive(stats_df: pd.DataFrame) -> go.Figure:
    df = stats_df.sort_values("Звонков за смену", ascending=False)
    fig = px.bar(df, x="Оператор", y="Звонков за смену", text="Звонков за смену", title="Звонков за смену по операторам")
    fig.update_layout(xaxis_tickangle=-45, margin=dict(l=40, r=20, t=50, b=160))
    return fig


def plot_activity_pct_line_interactive(stats_df: pd.DataFrame) -> go.Figure:
    df = stats_df.sort_values("% активности", ascending=False)
    fig = px.line(df, x="Оператор", y="% активности", markers=True, title="% активности операторов")
    fig.update_yaxes(range=[0, 100])
    fig.update_layout(xaxis_tickangle=-45, margin=dict(l=40, r=20, t=50, b=160))
    return fig


def plot_heatmap_interactive(calls_df: pd.DataFrame, operators_order: List[str]) -> go.Figure:
    df_heat = calls_df.copy()
    if "Всего_звонков_за_интервал" in df_heat.columns:
        df_heat = df_heat.drop(columns=["Всего_звонков_за_интервал"])
    df_heat = df_heat.fillna(0).astype(int)
    cols = [c for c in operators_order if c in df_heat.columns]
    if not cols:
        cols = list(df_heat.columns)
    z = df_heat[cols].values.tolist()
    x = cols
    y = df_heat.index.tolist()
    fig = go.Figure(data=go.Heatmap(z=z, x=x, y=y, colorscale="YlOrRd", hoverongaps=False, colorbar=dict(title="Звонков")))
    fig.update_layout(title="Heatmap: звонки (интервалы × операторы)", xaxis_tickangle=-45, margin=dict(l=80, r=20, t=50, b=160))
    return fig


# -------------------------
# UI: карточки настроек (центр страницы)
# -------------------------
def settings_card_container(uploaded_present: bool):
    """
    Возвращает контейнер с интерактивными карточками настроек по центру страницы.
    Каждая карточка содержит заголовок, элементы управления и краткую подсказку.
    """
    st.markdown("## ⚙️ Настройки анализа")
    st.markdown("Ниже — блоки с настройками. В каждой карточке есть подсказка, что именно она делает.")
    # используем три колонки, центрирующие карточки
    col_left, col_center, col_right = st.columns([1, 2, 1])

    with col_center:
        # Карточка 1: Файл и базовая информация
        st.markdown("### 🔹 Файл и обнаруженные операторы")
        st.info(
            "Загрузите файл сверху. После загрузки приложение попытается автоматически найти колонки с временем, длительностью и "
            "именами операторов (или кодами). В таблице показаны примеры найденных операторов."
        )
        if uploaded_present:
            st.success("Файл загружен — продолжайте настраивать фильтры ниже.")
        else:
            st.warning("Файл ещё не загружен — сначала выберите файл.")

        # Карточка 2: Выбор операторов
        st.markdown("### 🔸 Выбор операторов")
        st.caption("Выберите одного или нескольких операторов — анализ и графики будут рассчитаны только для выбранных.")
        # placeholder для мультиселекта (будет заполнен динамически ниже)

        # Карточка 3: Диапазон дат
        st.markdown("### 🔹 Фильтр по датам (опционально)")
        st.caption(
            "Если в данных есть даты, выберите период. Анализ будет производиться только для записей в выбранном диапазоне."
        )

        # Карточка 4: Параметры ночной смены
        st.markdown("### 🔸 Параметры ночной смены")
        st.caption(
            "Задайте время начала ночной смены и её длительность (по умолчанию 18:30 — 12 часов). "
            "Интервалы используются для построения матрицы активности (например, 30 минут)."
        )

        # Карточка 5: Что отображать
        st.markdown("### 🔹 Отображение")
        st.caption("Выберите, какие графики и таблицы показывать в интерфейсе.")

    return col_center  # возвращаем центральный столбец, где далее разместим конкретные контролы


# -------------------------
# Main: загрузка и отображение
# -------------------------
uploaded_file = st.file_uploader("📁 Загрузите файл с данными (xlsx, csv, html, txt)", type=["xlsx", "xls", "csv", "txt", "html", "htm"])

center_col = settings_card_container(uploaded_present=bool(uploaded_file))

# В центре: управляющие элементы (кнопки/селекты)
with center_col:
    loader = IntelligentFileLoader()
    if uploaded_file:
        with st.spinner("Загрузка файла и обнаружение операторов..."):
            try:
                df_raw, operators_detected = loader.load_file(uploaded_file)
            except Exception as e:
                st.error(f"Ошибка при загрузке файла: {e}")
                st.stop()

        st.markdown("**Примеры найденных операторов (примерные):**")
        if operators_detected:
            st.dataframe(pd.DataFrame(operators_detected))
        else:
            st.info("Операторы не обнаружены автоматически — используйте первые колонки файла как fallback.")

        # Параметры смены и интервалов
        st.markdown("---")
        st.markdown("#### ⏱ Параметры интервала и смены")
        interval_minutes = st.number_input("Длительность интервала (минут)", min_value=5, max_value=60, value=30, step=5)
        night_start = st.time_input("Время начала ночной смены (чч:мм)", value=datetime(2025, 1, 1, 18, 30).time())
        shift_hours = st.number_input("Длительность смены (часов)", min_value=1, max_value=24, value=12, step=1)
        min_active_intervals = st.number_input("Мин. число активных интервалов для определения 'ночного' оператора", min_value=1, max_value=50, value=4, step=1)

        # Отображение графиков
        st.markdown("---")
        st.markdown("#### 📈 Отображение")
        show_heatmap = st.checkbox("Показывать heatmap (интерактивно)", value=True)
        show_bar = st.checkbox("Показывать столбчатую диаграмму (звонки)", value=True)
        show_line = st.checkbox("Показывать линию (% активности)", value=True)

        # Мультивыбор операторов
        st.markdown("---")
        st.markdown("#### 👥 Выбор операторов для анализа")
        st.caption("Выберите одного или несколько операторов. По умолчанию выбраны все автоматически определённые операторы.")
        all_ops = None
        try:
            # По умолчанию берем из анализа, если он есть; иначе пустой список
            # Мы предварительно запустим анализ, чтобы получить список операторов
            analyzer_preview = NightShiftAnalyzer()
            # применяем параметры в класс (чтобы create_intervals использовал введённые)
            analyzer_preview.INTERVAL_MINUTES = int(interval_minutes)
            analyzer_preview.NIGHT_SHIFT_START_HOUR = night_start.hour
            analyzer_preview.NIGHT_SHIFT_START_MINUTE = night_start.minute
            analyzer_preview.SHIFT_DURATION_HOURS = int(shift_hours)
            analyzer_preview.NIGHT_OPERATOR_THRESHOLD = int(min_active_intervals)

            # попробуем получить статистику для автоматического списка операторов
            try:
                _, stats_preview, _ = analyzer_preview.analyze(df_raw)
                all_ops = list(stats_preview["Оператор"])
            except Exception:
                # если не получилось проанализировать (например, нет валидных времён), используем найденные операторы heuristics
                all_ops = [op["name"] for op in operators_detected] if operators_detected else []
        except Exception:
            all_ops = [op["name"] for op in operators_detected] if operators_detected else []

        if not all_ops:
            st.warning("Не удалось автоматически определить список операторов. Проверьте входной файл или вручную отредактируйте данные.")
            all_ops = []

        selected_ops = st.multiselect("Список операторов (мультивыбор)", options=all_ops, default=all_ops)

        # Диапазон дат (опционально)
        st.markdown("---")
        st.markdown("#### 🗓 Фильтр по диапазону дат (если доступны даты)")
        st.caption(
            "Если в данных есть поле с датой/временем, вы сможете отфильтровать записи по периоду. "
            "Если нет — этот фильтр будет скрыт."
        )
        # обнаружение дат: используем analyzer.prepare_dataframe
        try:
            analyzer_for_dates = NightShiftAnalyzer()
            dfc_all = analyzer_for_dates.prepare_dataframe(df_raw)
            min_dt = dfc_all["start_datetime"].min().date()
            max_dt = dfc_all["start_datetime"].max().date()
            date_filter_available = True
        except Exception:
            date_filter_available = False
            min_dt = None
            max_dt = None

        if date_filter_available:
            date_from = st.date_input("Дата с", value=min_dt, min_value=min_dt, max_value=max_dt)
            date_to = st.date_input("Дата по", value=max_dt, min_value=min_dt, max_value=max_dt)
            if date_from > date_to:
                st.error("Дата 'с' не может быть позже даты 'по'. Исправьте диапазон.")
                st.stop()
        else:
            st.info("Даты в файле не обнаружены автоматически — фильтр по дате недоступен.")
            date_from = None
            date_to = None

        # -------------------------
        # Выполнение анализа с выбранными настройками
        # -------------------------
        st.markdown("---")
        run_button = st.button("🔎 Запустить анализ с этими настройками")

        if run_button:
            # применяем параметры в analyzer
            analyzer = NightShiftAnalyzer()
            analyzer.INTERVAL_MINUTES = int(interval_minutes)
            analyzer.NIGHT_SHIFT_START_HOUR = night_start.hour
            analyzer.NIGHT_SHIFT_START_MINUTE = night_start.minute
            analyzer.SHIFT_DURATION_HOURS = int(shift_hours)
            analyzer.NIGHT_OPERATOR_THRESHOLD = int(min_active_intervals)

            with st.spinner("Выполняется анализ — это может занять несколько секунд..."):
                try:
                    # если выбран диапазон дат — отфильтруем исходный dfc
                    dfc_full = analyzer.prepare_dataframe(df_raw)
                    if date_filter_available and date_from and date_to:
                        mask_date = (dfc_full["start_datetime"].dt.date >= date_from) & (dfc_full["start_datetime"].dt.date <= date_to)
                        dfc_filtered = dfc_full.loc[mask_date].reset_index(drop=True)
                        if dfc_filtered.empty:
                            st.warning("Нет данных в выбранном диапазоне дат.")
                            st.stop()
                        # создаём временный DataFrame для анализа (анализируем по dfc_filtered)
                        # построим интервалы на основе min date в фильтре
                        base = dfc_filtered["start_datetime"].min().replace(hour=0, minute=0, second=0, microsecond=0)
                        analyzer.NIGHT_SHIFT_START_HOUR = night_start.hour
                        analyzer.NIGHT_SHIFT_START_MINUTE = night_start.minute
                        analyzer.INTERVAL_MINUTES = int(interval_minutes)
                        analyzer.SHIFT_DURATION_HOURS = int(shift_hours)
                        intervals = analyzer.create_intervals(base)

                        # определяем ночных операторов в этом диапазоне, но затем отфильтруем по selected_ops
                        night_ops = []
                        for op in sorted(dfc_filtered["operator_name"].unique()):
                            op_data = dfc_filtered[dfc_filtered["operator_name"] == op]
                            mask = (op_data["start_datetime"] >= base.replace(hour=analyzer.NIGHT_SHIFT_START_HOUR, minute=analyzer.NIGHT_SHIFT_START_MINUTE)) & \
                                   (op_data["start_datetime"] < base.replace(hour=analyzer.NIGHT_SHIFT_START_HOUR, minute=analyzer.NIGHT_SHIFT_START_MINUTE) + timedelta(hours=analyzer.SHIFT_DURATION_HOURS))
                            calls = mask.sum()
                            active_intervals = sum(((op_data["start_datetime"] >= it.start) & (op_data["start_datetime"] < it.end)).any() for it in intervals)
                            if calls > 0 and active_intervals >= analyzer.NIGHT_OPERATOR_THRESHOLD:
                                night_ops.append(op)
                        # пересчёт только для выбранных операторов
                        ops_to_include = [op for op in selected_ops if op in night_ops]
                        if not ops_to_include:
                            st.warning("В выбранном диапазоне/по текущим параметрам ни один из выбранных операторов не является 'ночным'. Попробуйте снять фильтр по дате или выбрать других операторов.")
                            st.stop()

                        # Построение activity_df и calls_df
                        labels = [it.label for it in intervals]
                        activity_df = pd.DataFrame(index=labels, columns=ops_to_include)
                        calls_df = pd.DataFrame(index=labels, columns=ops_to_include)
                        total_calls_by_operator = {}
                        for op in ops_to_include:
                            op_data = dfc_filtered[dfc_filtered["operator_name"] == op]
                            shift_mask = (op_data["start_datetime"] >= base.replace(hour=analyzer.NIGHT_SHIFT_START_HOUR, minute=analyzer.NIGHT_SHIFT_START_MINUTE)) & \
                                         (op_data["start_datetime"] < base.replace(hour=analyzer.NIGHT_SHIFT_START_HOUR, minute=analyzer.NIGHT_SHIFT_START_MINUTE) + timedelta(hours=analyzer.SHIFT_DURATION_HOURS))
                            total_calls = int(shift_mask.sum())
                            total_calls_by_operator[op] = total_calls
                            flags = []
                            counts = []
                            for it in intervals:
                                mask = (op_data["start_datetime"] >= it.start) & (op_data["start_datetime"] < it.end)
                                cnt = int(mask.sum())
                                counts.append(cnt)
                                flags.append("Работал" if cnt > 0 else "Спал")
                            activity_df[op] = flags
                            calls_df[op] = counts
                        calls_df["Всего_звонков_за_интервал"] = calls_df[ops_to_include].sum(axis=1)
                        stats_df = analyzer.generate_statistics(activity_df, ops_to_include, total_calls_by_operator, calls_df)
                    else:
                        # нет фильтра даты — используем полный набор данных
                        activity_df, stats_df, calls_df = analyzer.analyze(df_raw)
                        # фильтруем по выбранным операторам
                        ops_available = [op for op in selected_ops if op in activity_df.columns]
                        if not ops_available:
                            st.warning("Ни один из выбранных операторов не найден в анализе. Попробуйте выбрать другие или проверить исходный файл.")
                            st.stop()
                        activity_df = activity_df[ops_available]
                        calls_df = calls_df[ops_available]
                        stats_df = stats_df[stats_df["Оператор"].isin(ops_available)].reset_index(drop=True)

                    # Отобразим результаты
                    st.success("Анализ завершён успешно ✅")
                    st.markdown("### 📋 Статистика по выбранным операторам")
                    st.dataframe(stats_df.sort_values("Звонков за смену", ascending=False))

                    st.markdown("### 📑 Таблица: звонки по интервалам")
                    st.dataframe(calls_df)

                    st.markdown("### 🗂 Таблица: активность (интервалы × операторы)")
                    st.dataframe(activity_df)

                    # Визуализации Plotly
                    vis_col1, vis_col2 = st.columns([1, 1])
                    if show_bar:
                        fig_bar = plot_calls_bar_interactive(stats_df)
                        with vis_col1:
                            st.plotly_chart(fig_bar, use_container_width=True)
                    if show_line:
                        fig_line = plot_activity_pct_line_interactive(stats_df)
                        with vis_col2:
                            st.plotly_chart(fig_line, use_container_width=True)
                    if show_heatmap:
                        try:
                            fig_heat = plot_heatmap_interactive(calls_df, list(stats_df["Оператор"]))
                            st.subheader("🔥 Интерактивная тепловая карта (Heatmap)")
                            st.plotly_chart(fig_heat, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Не удалось построить heatmap: {e}")

                    # Экспорт в Excel
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        activity_df.to_excel(writer, sheet_name="Активность", index=True)
                        calls_df.to_excel(writer, sheet_name="Звонки", index=True)
                        stats_df.to_excel(writer, sheet_name="Статистика", index=False)
                    st.download_button(
                        label="⬇ Скачать Excel-отчёт",
                        data=output.getvalue(),
                        file_name="night_shift_analysis.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

                except Exception as e:
                    st.error(f"Ошибка при анализе: {e}")
    else:
        st.info("Загрузите файл, чтобы увидеть обнаруженных операторов и открыть настройки.")


# -------------------------
# If no file: show sample/help
# -------------------------
if not uploaded_file:
    st.markdown("---")
    st.markdown("### Полезные советы перед загрузкой файла")
    st.markdown("""
- Рекомендуемый формат: Excel (.xlsx) с заголовками колонок.  
- Важно: в файле должна быть колонка с временем начала звонка (в формате `DD.MM.YYYY HH:MM:SS` или похожем) и колонка с оператором (например `7599416 (Иванов И.И.)`).  
- Если формат отличается — приложение пытается догадаться по эвристике.  
- Для теста можно загрузить небольшой CSV с 10–50 строками, чтобы убедиться, что парсинг проходит корректно.
""")
    st.info("Если нужно — пришлю пример шаблона файла для теста. Напиши 'шаблон' и пришлю пример в чат.")

# Конец файла
