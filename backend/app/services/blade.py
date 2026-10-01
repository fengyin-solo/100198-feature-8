"""叶片业务规则：状态流转、字段校验与筛选口径都收在这里。

检查结论不再靠人工填，统一按「叶片长度 + 裂纹数量 + 雷击次数」三项判定：
- 叶片长度分档对应裂纹数量允许上限，超限即「存在裂纹」，否则「完好」；
- 雷击次数达到阈值时必须附补充说明，否则检查记录不允许保存；
- 同一片叶片重复提交只覆盖最新结论，历次判定依据留在检查记录里；
- 批量补录历史记录走同一套口径重算，长度与台账对不上的单独挑出。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "blade"
REQUIRED_FIELDS = ["叶片编号", "所属机组", "叶片长度"]
STATUS_ORDER = ["待检查", "完好", "存在裂纹", "已更换"]
ACTION_RULES = {"提交检查": "完好", "登记缺陷": "存在裂纹", "更换叶片": "已更换"}
NEGATIVE_ACTIONS = []

CONCLUSION_OK = "完好"
CONCLUSION_CRACK = "存在裂纹"

# 叶片长度分档（米，下限含、上限不含）与对应的裂纹数量允许上限。
# 口径集中在这一处，后续标准调整只改这里，提交与批量补录同时生效。
CRACK_LIMIT_BANDS: list[tuple[float, float | None, int, str]] = [
    (0.0, 50.0, 1, "50米以下"),
    (50.0, 70.0, 2, "50米（含）至70米"),
    (70.0, 90.0, 3, "70米（含）至90米"),
    (90.0, None, 5, "90米及以上"),
]
# 雷击次数达到该值（含）即要求补充说明后才能保存。
LIGHTNING_NOTE_LIMIT = 2
# 批量补录时历史记录里的长度允许的丈量/录入误差。
LENGTH_TOLERANCE = 0.1
HISTORY_FIELD = "检查记录"


def parse_length(value: Any) -> float | None:
    """把「68米」「68.5」这类写法解析成数值；解析不了返回 None，交调用方挑出。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        digits = ""
        for ch in text:
            if ch.isdigit() or ch == ".":
                digits += ch
            elif digits:
                break
        try:
            return float(digits) if digits else None
        except ValueError:
            return None


def parse_count(value: Any) -> int | None:
    """裂纹/雷击次数只接受非负整数；空值按 0 处理，其它写法一律视为非法。"""
    if value is None or str(value).strip() == "":
        return 0
    text = str(value).strip()
    if not text.isdigit():
        return None
    return int(text)


def crack_limit_for(length: float) -> tuple[int, str]:
    """按叶片长度返回（裂纹允许上限, 所在档说明）。"""
    for lower, upper, limit, label in CRACK_LIMIT_BANDS:
        if length >= lower and (upper is None or length < upper):
            return limit, label
    return CRACK_LIMIT_BANDS[-1][2], CRACK_LIMIT_BANDS[-1][3]


def evaluate_inspection(
    *,
    blade_length: float,
    crack_count: int,
    lightning_count: int,
) -> dict[str, Any]:
    """三项口径合成一次判定，返回结论与完整判定依据；保存与否由调用方决定。"""
    crack_limit, band_label = crack_limit_for(blade_length)
    over_limit = crack_count > crack_limit
    conclusion = CONCLUSION_CRACK if over_limit else CONCLUSION_OK
    lightning_reached = lightning_count >= LIGHTNING_NOTE_LIMIT
    compare = "超过上限" if over_limit else "未超过上限"
    lightning_word = "达到" if lightning_reached else "未达到"
    basis_text = (
        f"叶片长度{blade_length:g}米（{band_label}），裂纹允许上限{crack_limit}条，"
        f"实测裂纹{crack_count}条，{compare}，判定为{conclusion}；"
        f"雷击{lightning_count}次，阈值{LIGHTNING_NOTE_LIMIT}次，{lightning_word}。"
    )
    return {
        "叶片长度": blade_length,
        "长度分档": band_label,
        "裂纹数量": crack_count,
        "裂纹上限": crack_limit,
        "雷击次数": lightning_count,
        "雷击阈值": LIGHTNING_NOTE_LIMIT,
        "雷击需说明": lightning_reached,
        "结论": conclusion,
        "判定说明": basis_text,
    }


class BladeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("叶片编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], list[str]]:
        """登记叶片：除缺字段外，长度必须能按米解析，否则后续判定无档可归。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, []
        errors: list[str] = []
        if parse_length(values.get("叶片长度")) is None:
            errors.append("叶片长度需为以米计的数值，例如 68 或 68.5")
        if errors:
            return None, [], errors
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for optional in ("制造厂商",):
            if str(values.get(optional) or "").strip():
                entry[optional] = values[optional]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry[HISTORY_FIELD] = []
        rows.append(entry)
        return entry, [], []

    def submit_inspection(
        self,
        entry_id: int,
        *,
        crack_count: Any,
        lightning_count: Any,
        note: str | None = None,
        inspect_date: str | None = None,
        source: str = "检查提交",
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        """提交一次叶片检查：按口径判定，雷击达阈值且无补充说明时拒绝保存。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"叶片 {entry_id} 不存在或已归档", None
        blade_length = parse_length(entry.get("叶片长度"))
        if blade_length is None:
            return None, "叶片台账长度不是有效数值，无法套用判定口径，请先更正长度", None

        cracks = parse_count(crack_count)
        if cracks is None:
            return None, "裂纹数量需为非负整数", None
        lightnings = parse_count(lightning_count)
        if lightnings is None:
            return None, "雷击次数需为非负整数", None
        note = (note or "").strip()
        if lightnings >= LIGHTNING_NOTE_LIMIT and not note:
            return (
                None,
                f"雷击次数已达{LIGHTNING_NOTE_LIMIT}次阈值，须填写补充说明后才能保存",
                None,
            )

        basis = evaluate_inspection(
            blade_length=blade_length, crack_count=cracks, lightning_count=lightnings
        )
        basis["补充说明"] = note
        self._apply_inspection(entry, basis, source=source, inspect_date=inspect_date)
        word = "存在裂纹" if basis["结论"] == CONCLUSION_CRACK else "完好"
        return entry, f"检查结论已按口径判定为「{word}」", basis

    def backfill_inspections(
        self, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """批量补录历史检查记录：同一套口径重算，长度对不上等问题记录原样挑出。"""
        applied: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        rows = store.rows(MODULE)
        by_code = {str(row.get("叶片编号", "")).strip(): row for row in rows}

        for index, raw in enumerate(records, start=1):
            code = str(raw.get("叶片编号") or "").strip()
            item: dict[str, Any] = {"序号": index, "叶片编号": code or f"第{index}行"}
            original = str(raw.get("检查结论") or raw.get("原结论") or "").strip()
            if original:
                item["原结论"] = original

            def reject(reason: str) -> None:
                item["原因"] = reason
                rejected.append(item)

            if not code:
                reject("缺少叶片编号，无法定位台账")
                continue
            entry = by_code.get(code)
            if entry is None:
                reject("台账中不存在该叶片编号，未纳入重算")
                continue

            master_length = parse_length(entry.get("叶片长度"))
            if master_length is None:
                reject("台账叶片长度不是有效数值，无法套用判定口径")
                continue
            record_length = parse_length(raw.get("叶片长度"))
            if record_length is None:
                reject("历史记录缺少有效叶片长度，无法按长度分档")
                continue
            if abs(record_length - master_length) > LENGTH_TOLERANCE:
                reject(
                    f"记录长度{record_length:g}米与台账长度{master_length:g}米不一致，"
                    "疑似叶片对错号或长度登记有误"
                )
                continue

            cracks = parse_count(raw.get("裂纹数量"))
            if cracks is None:
                reject("裂纹数量不是非负整数")
                continue
            lightnings = parse_count(raw.get("雷击次数"))
            if lightnings is None:
                reject("雷击次数不是非负整数")
                continue
            note = str(raw.get("补充说明") or "").strip()
            if lightnings >= LIGHTNING_NOTE_LIMIT and not note:
                reject(f"雷击次数已达{LIGHTNING_NOTE_LIMIT}次阈值，缺少补充说明，未补录")
                continue

            basis = evaluate_inspection(
                blade_length=master_length, crack_count=cracks, lightning_count=lightnings
            )
            basis["补充说明"] = note
            self._apply_inspection(
                entry,
                basis,
                source="批量补录",
                inspect_date=str(raw.get("上次检查日") or "").strip() or None,
            )
            item["重算结论"] = basis["结论"]
            item["判定说明"] = basis["判定说明"]
            item["已保存"] = True
            if original and original != basis["结论"]:
                item["结论有调整"] = True
            applied.append(item)

        return {
            "total": len(records),
            "applied_count": len(applied),
            "rejected_count": len(rejected),
            "applied": applied,
            "rejected": rejected,
        }

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"叶片 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于叶片可执行范围"
        if action == "提交检查":
            # 兼容旧入口：直接用台账已登记的裂纹/雷击数按同一口径判一次。
            entry, message, _ = self.submit_inspection(
                entry_id,
                crack_count=entry.get("裂纹数量"),
                lightning_count=entry.get("雷击次数"),
            )
            return entry, message
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"叶片已{action}"

    # ---- 内部 helpers -------------------------------------------------

    def _apply_inspection(
        self,
        entry: dict[str, Any],
        basis: dict[str, Any],
        *,
        source: str,
        inspect_date: str | None,
    ) -> None:
        """把一次判定落到台账：最新结论覆盖当前字段，判定依据追加进历史。"""
        history = entry.setdefault(HISTORY_FIELD, [])
        record = {
            "序号": len(history) + 1,
            "提交时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "来源": source,
            "结论": basis["结论"],
            "补充说明": basis.get("补充说明", ""),
            "判定依据": basis,
        }
        history.append(record)

        entry["上次检查日"] = inspect_date or datetime.now().strftime("%Y-%m-%d")
        entry["裂纹数量"] = basis["裂纹数量"]
        entry["雷击次数"] = basis["雷击次数"]
        entry["检查结论"] = basis["结论"]
        entry["雷击待说明"] = basis["雷击需说明"] and not basis.get("补充说明")
        entry["叶片状态"] = basis["结论"]
        entry["status"] = basis["结论"]
        entry["abnormal"] = basis["结论"] == CONCLUSION_CRACK
        entry["pending"] = basis["结论"] == CONCLUSION_CRACK
