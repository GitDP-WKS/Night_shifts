# streamlit_app.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from analyzer import NightShiftAnalyzer
from loader import IntelligentFileLoader
from viz import (
    plot_calls_bar_interactive,
    plot_activity_pct_line_interactive,
    plot_heatmap_interactive,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streamlit_nightshift_cards")


# ------------------------- Streamlit config -------------------------
st.set_page_config(page_title="Анализ ночной смены — карточки", layout="wide")
st.title("📊 Анализ ночной смены — понятный интерфейс")
st.markdown(
    """
Добро пожаловать! Это инструмент для анализа ночных смен колл-центра.  
Загрузите файл (Excel/CSV/HTML/TXT), настройте фильтры в карточках ниже и получите:
- интерактивные графики,
- таблицы активности и статистику,
- скачиваемый Excel-отчёт.
"""
)


# ------------------------- Кэшируемая загрузка -------------------------
@st.cache_data(show_spinner=False)
def load_data_cached(file_bytes: bytes, filename: str):
    """
    Обёртка над IntelligentFileLoader с кэшированием.
    Кэшируется по содержимому файла и имени.
    """
    loader = IntelligentFileLoader()
    bio = BytesIO(file_bytes)
    df_raw, operators_detected = loader.load(bio, filename)
    return df_raw, operators_detected


# ------------------------- UI: карточки настроек -------------------------
def settings_card_container(uploaded_present: bool):
    st.markdown("## ⚙️ Настройки анализа")
    st.markdown("Ниже — блоки с настройками. В каждой карточке есть подсказка, что именно она делает.")

    col_left, col_center, col_right = st.columns([1, 2, 1])

    with col_center:
        st.markdown("### 🔹 Файл и обнаруженные операторы")
        st.info(
            "Загрузите файл сверху. После загрузки приложение попытается автоматически найти колонки с временем, "
            "длительностью и именами операторов. В таблице показаны примеры найденных операторов."
        )
        if uploaded_present:
            st.success("Файл загружен — продолжайте настраивать фильтры ниже.")
        else:
            st.warning("Файл ещё не загружен — сначала выберите файл.")

        st.markdown("### 🔸 Выбор операторов")
        st.caption("Выберите одного или нескольких операторов — анализ и графики будут рассчитаны только для выбранных.")

        st.markdown("### 🔹 Фильтр по датам (опционально)")
        st.caption("Если в данных есть даты, выберите период. Анализ будет производиться только для записей в выбранном диапазоне.")

        st.markdown("### 🔸 Параметры ночной смены")
        st.caption(
            "Задайте время начала ночной смены и её длительность (по умолчанию 18:30 — 12 часов). "
            "Интервалы используются для построения матрицы активности."
        )

        st.markdown("### 🔹 Отображение")
        st.caption("Выберите, какие графики и таблицы показывать в интерфейсе.")

    return col_center


# ------------------------- Main -------------------------
uploaded_file = st.file_uploader(
    "📁 Загрузите файл с данными (xlsx, csv, html, txt)",
    type=["xlsx", "xls", "csv", "txt", "html", "htm"],
)

center_col = settings_card_container(uploaded_present=bool(uploaded_file))

with center_col:
    if uploaded_file:
        # читаем байты один раз (для кэша)
        file_bytes = uploaded_file.getvalue()

        with st.spinner("Загрузка файла и обнаружение операторов..."):
            try:
                df_raw, operators_detected = load_data_cached(file_bytes, uploaded_file.name)
            except Exception as e:
                st.error(f"Ошибка при загрузке файла: {e}")
                st.stop()

        st.markdown("**Примеры найденных операторов (примерные):**")
        if operators_detected:
            st.dataframe(pd.DataFrame(operators_detected))
        else:
            st.info("Операторы не обнаружены автоматически — будут использованы первые колонки файла.")

        st.markdown("---")
        st.markdown("#### ⏱ Параметры интервала и смены")
        interval_minutes = st.number_input(
            "Длительность интервала (минут)", min_value=5, max_value=60, value=30, step=5
        )
        night_start = st.time_input(
            "Время начала ночной смены (чч:мм)",
            value=datetime(2025, 1, 1, 18, 30).time(),
        )
        shift_hours = st.number_input(
            "Длительность смены (часов)", min_value=1, max_value=24, value=12, step=1
        )
        min_active_intervals = st.number_input(
            "Мин. число активных интервалов для определения 'ночного' оператора",
            min_value=1,
            max_value=50,
            value=4,
            step=1,
        )

        st.markdown("---")
        st.markdown("#### 📈 Отображение")
        show_heatmap = st.checkbox("Показывать heatmap (интерактивно)", value=True)
        show_bar = st.checkbox("Показывать столбчатую диаграмму (звонки)", value=True)
        show_line = st.checkbox("Показывать линию (% активности)", value=True)

        st.markdown("---")
        st.markdown("#### 👥 Выбор операторов для анализа")
        st.caption("По умолчанию выбраны все операторы, отнесённые к ночной смене.")

        analyzer_preview = NightShiftAnalyzer()
        analyzer_preview.INTERVAL_MINUTES = int(interval_minutes)
        analyzer_preview.NIGHT_SHIFT_START_HOUR = night_start.hour
        analyzer_preview.NIGHT_SHIFT_START_MINUTE = night_start.minute
        analyzer_preview.SHIFT_DURATION_HOURS = int(shift_hours)
        analyzer_preview.NIGHT_OPERATOR_THRESHOLD = int(min_active_intervals)

        try:
            _, stats_preview, _ = analyzer_preview.analyze(df_raw)
            all_ops = list(stats_preview["Оператор"])
        except Exception:
            all_ops = [op["name"] for op in operators_detected] if operators_detected else []

        if not all_ops:
            st.warning("Не удалось автоматически определить список операторов.")
            all_ops = []

        selected_ops = st.multiselect(
            "Список операторов (мультивыбор)", options=all_ops, default=all_ops
        )

        st.markdown("---")
        st.markdown("#### 🗓 Фильтр по диапазону дат (если доступны даты)")

        analyzer_for_dates = NightShiftAnalyzer()
        try:
            dfc_all = analyzer_for_dates.prepare_dataframe(df_raw)
            min_dt = dfc_all["start_datetime"].min().date()
            max_dt = dfc_all["start_datetime"].max().date()
            date_filter_available = True
        except Exception:
            date_filter_available = False

        if date_filter_available:
            date_from = st.date_input("Дата с", value=min_dt, min_value=min_dt, max_value=max_dt)
            date_to = st.date_input("Дата по", value=max_dt, min_value=min_dt, max_value=max_dt)
            if date_from > date_to:
                st.error("Дата 'с' не может быть позже даты 'по'.")
                st.stop()
        else:
            st.info("Даты в файле не обнаружены автоматически — фильтр по дате недоступен.")
            date_from = None
            date_to = None

        st.markdown("---")
        run_button = st.button("🔎 Запустить анализ с этими настройками")

        if run_button:
            analyzer = NightShiftAnalyzer()
            analyzer.INTERVAL_MINUTES = int(interval_minutes)
            analyzer.NIGHT_SHIFT_START_HOUR = night_start.hour
            analyzer.NIGHT_SHIFT_START_MINUTE = night_start.minute
            analyzer.SHIFT_DURATION_HOURS = int(shift_hours)
            analyzer.NIGHT_OPERATOR_THRESHOLD = int(min_active_intervals)

            with st.spinner("Выполняется анализ..."):
                try:
                    dfc_full = analyzer.prepare_dataframe(df_raw)

                    if date_filter_available and date_from and date_to:
                        mask_date = (
                            (dfc_full["start_datetime"].dt.date >= date_from)
                            & (dfc_full["start_datetime"].dt.date <= date_to)
                        )
                        dfc_filtered = dfc_full.loc[mask_date].reset_index(drop=True)
                        if dfc_filtered.empty:
                            st.warning("Нет данных в выбранном диапазоне дат.")
                            st.stop()

                        # небольшой локальный анализ по фильтрованному df
                        activity_df, stats_df, calls_df = analyzer.analyze(dfc_filtered)
                    else:
                        activity_df, stats_df, calls_df = analyzer.analyze(df_raw)

                    # фильтрация по выбранным операторам
                    ops_available = [op for op in selected_ops if op in activity_df.columns]
                    if not ops_available:
                        st.warning(
                            "Ни один из выбранных операторов не найден в анализе. "
                            "Попробуйте выбрать других операторов или изменить параметры."
                        )
                        st.stop()

                    activity_df = activity_df[ops_available]
                    calls_df = calls_df[ops_available + ["Всего_звонков_за_интервал"]]
                    stats_df = stats_df[stats_df["Оператор"].isin(ops_available)].reset_index(drop=True)

                    st.success("Анализ завершён успешно ✅")

                    st.markdown("### 📋 Статистика по выбранным операторам")
                    st.dataframe(stats_df.sort_values("Звонков за смену", ascending=False))

                    st.markdown("### 📑 Таблица: звонки по интервалам")
                    st.dataframe(calls_df)

                    st.markdown("### 🗂 Таблица: активность (интервалы × операторы)")
                    st.dataframe(activity_df)

                    col1, col2 = st.columns([1, 1])
                    if show_bar:
                        with col1:
                            st.plotly_chart(
                                plot_calls_bar_interactive(stats_df),
                                use_container_width=True,
                            )
                    if show_line:
                        with col2:
                            st.plotly_chart(
                                plot_activity_pct_line_interactive(stats_df),
                                use_container_width=True,
                            )
                    if show_heatmap:
                        st.subheader("🔥 Интерактивная тепловая карта (Heatmap)")
                        st.plotly_chart(
                            plot_heatmap_interactive(calls_df, list(stats_df["Оператор"])),
                            use_container_width=True,
                        )

                    # экспорт в Excel
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        activity_df.to_excel(writer, sheet_name="Активность", index=True)
                        calls_df.to_excel(writer, sheet_name="Звонки", index=True)
                        stats_df.to_excel(writer, sheet_name="Статистика", index=False)

                    st.download_button(
                        label="⬇ Скачать Excel-отчёт",
                        data=output.getvalue(),
                        file_name="night_shift_analysis.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

                except Exception as e:
                    st.error(f"Ошибка при анализе: {e}")

    else:
        st.info("Загрузите файл, чтобы увидеть обнаруженных операторов и открыть настройки.")

if not uploaded_file:
    st.markdown("---")
    st.markdown("### Полезные советы перед загрузкой файла")
    st.markdown(
        """
- Рекомендуемый формат: Excel (.xlsx) с заголовками колонок.  
- Важно: в файле должна быть колонка с временем начала звонка и колонка с оператором (`7599416 (Иванов И.И.)`).  
- Для теста можно загрузить небольшой CSV с 10–50 строками.
"""
    )
