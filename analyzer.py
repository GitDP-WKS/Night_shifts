# analyzer.py
# Вся логика анализа ночной смены

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

import pandas as pd

logger = logging.getLogger("nightshift_analyzer")


@dataclass
class TimeInterval:
    start: datetime
    end: datetime
    label: str


class NightShiftAnalyzer:
    INTERVAL_MINUTES: int = 30
    NIGHT_SHIFT_START_HOUR: int = 18
    NIGHT_SHIFT_START_MINUTE: int = 30
    SHIFT_DURATION_HOURS: int = 12
    NIGHT_OPERATOR_THRESHOLD: int = 4

    def create_intervals(self, base_date: datetime) -> List[TimeInterval]:
        start = base_date.replace(
            hour=self.NIGHT_SHIFT_START_HOUR,
            minute=self.NIGHT_SHIFT_START_MINUTE,
            second=0,
            microsecond=0,
        )
        end = start + timedelta(hours=self.SHIFT_DURATION_HOURS)
        intervals: List[TimeInterval] = []
        cur = start
        while cur < end:
            nxt = cur + timedelta(minutes=self.INTERVAL_MINUTES)
            intervals.append(
                TimeInterval(
                    start=cur,
                    end=nxt,
                    label=f"{cur.strftime('%H:%M')}-{nxt.strftime('%H:%M')}",
                )
            )
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
        Возвращает df с колонками:
        start_datetime, duration_seconds, end_datetime, operator_name.
        """
        col_map: Dict[str, str] = {}
        col_names = list(df.columns)

        for c in col_names:
            lc = str(c).lower()
            if not col_map.get("start") and any(
                k in lc for k in ("начало", "start", "время", "date", "time")
            ):
                col_map["start"] = c
            if not col_map.get("duration") and any(
                k in lc for k in ("длитель", "duration", "length", "sec")
            ):
                col_map["duration"] = c
            if not col_map.get("operator") and any(
                k in lc for k in ("агент", "оператор", "agent", "operator", "имя", "имена")
            ):
                col_map["operator"] = c

        if "start" not in col_map and len(col_names) >= 1:
            col_map["start"] = col_names[0]
        if "duration" not in col_map and len(col_names) >= 2:
            col_map["duration"] = col_names[1]
        if "operator" not in col_map and len(col_names) >= 3:
            col_map["operator"] = col_names[2]

        dfc = df.copy()

        dfc["start_datetime"] = pd.to_datetime(
            dfc[col_map["start"]], errors="coerce", dayfirst=True
        )

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
        dfc["operator_name"] = dfc[col_map["operator"]].apply(
            self._extract_operator_name
        )
        dfc = dfc.dropna(subset=["start_datetime"]).reset_index(drop=True)
        dfc["end_datetime"] = dfc["start_datetime"] + pd.to_timedelta(
            dfc["duration_seconds"], unit="s"
        )
        return dfc

    def analyze(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        dfc = self.prepare_dataframe(df)
        if dfc.empty:
            raise ValueError("Нет валидных временных данных для анализа")

        base = dfc["start_datetime"].min().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        intervals = self.create_intervals(base)
        shift_start = base.replace(
            hour=self.NIGHT_SHIFT_START_HOUR,
            minute=self.NIGHT_SHIFT_START_MINUTE,
        )
        shift_end = shift_start + timedelta(hours=self.SHIFT_DURATION_HOURS)

        # определение ночных операторов
        night_ops: List[str] = []
        for op in sorted(dfc["operator_name"].unique()):
            op_data = dfc[dfc["operator_name"] == op]
            mask = (op_data["start_datetime"] >= shift_start) & (
                op_data["start_datetime"] < shift_end
            )
            calls = mask.sum()
            active_intervals = sum(
                (
                    (op_data["start_datetime"] >= it.start)
                    & (op_data["start_datetime"] < it.end)
                ).any()
                for it in intervals
            )
            if calls > 0 and active_intervals >= self.NIGHT_OPERATOR_THRESHOLD:
                night_ops.append(op)

        if not night_ops:
            raise ValueError(
                "Не найдено операторов ночной смены. Проверьте входные данные или параметры."
            )

        labels = [it.label for it in intervals]
        activity_df = pd.DataFrame(index=labels, columns=night_ops)
        calls_df = pd.DataFrame(index=labels, columns=night_ops)
        total_calls_by_operator: Dict[str, int] = {}

        for op in night_ops:
            op_data = dfc[dfc["operator_name"] == op]
            shift_mask = (op_data["start_datetime"] >= shift_start) & (
                op_data["start_datetime"] < shift_end
            )
            total_calls = int(shift_mask.sum())
            total_calls_by_operator[op] = total_calls

            flags = []
            counts = []
            for it in intervals:
                mask = (op_data["start_datetime"] >= it.start) & (
                    op_data["start_datetime"] < it.end
                )
                cnt = int(mask.sum())
                counts.append(cnt)
                flags.append("Работал" if cnt > 0 else "Спал")
            activity_df[op] = flags
            calls_df[op] = counts

        calls_df["Всего_звонков_за_интервал"] = calls_df[night_ops].sum(axis=1)
        stats_df = self.generate_statistics(
            activity_df, night_ops, total_calls_by_operator, calls_df
        )

        total_calls_all = sum(total_calls_by_operator.values())
        total_from_intervals = int(calls_df[night_ops].sum().sum())
        if total_calls_all != total_from_intervals:
            logger.warning(
                "Несоответствие сумм звонков: суммарно=%d, по интервалам=%d",
                total_calls_all,
                total_from_intervals,
            )

        return activity_df, stats_df, calls_df

    @staticmethod
    def generate_statistics(
        activity_df: pd.DataFrame,
        operators: List[str],
        call_counts: Dict[str, int],
        calls_df: pd.DataFrame,
    ) -> pd.DataFrame:
        rows = []
        for op in operators:
            act = activity_df[op]
            total_intervals = len(act)
            active_intervals = (act == "Работал").sum()
            pct = (
                round(active_intervals / total_intervals * 100, 2)
                if total_intervals > 0
                else 0.0
            )
            calls_from_intervals = int(calls_df[op].sum())
            rows.append(
                {
                    "Оператор": op,
                    "Всего интервалов": total_intervals,
                    "Активных интервалов": int(active_intervals),
                    "% активности": pct,
                    "Звонков за смену": call_counts.get(op, 0),
                    "Звонков (проверка)": calls_from_intervals,
                }
            )
        return pd.DataFrame(rows)
