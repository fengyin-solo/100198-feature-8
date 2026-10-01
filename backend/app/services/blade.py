"""叶片业务规则：检查结论判定口径、历史依据留存与批量补录重算都收在这里。

判定口径（提交检查与批量补录共用同一套规则）：
1. 检查结论由叶片长度、裂纹数量、雷击次数三项共同决定，不允许手工直接填写结论。
2. 按叶片长度分档确定裂纹允许上限，裂纹数量超过上限时结论为「存在裂纹」，否则为「完好」。
3. 雷击次数达到阈值（含阈值）时必须填写补充说明，否则不允许保存；雷击本身不改变结论。
4. 同一片叶片重复提交检查只覆盖最新结论，历次判定依据保存在检查记录里可追溯。
5. 「登记缺陷」「更换叶片」仍是人工状态流转动作，与检查结论口径互不覆盖。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "blade"
REQUIRED_FIELDS = ["叶片编号", "所属机组", "叶片长度"]
STATUS_ORDER = ["待检查", "完好", "存在裂纹", "已更换"]
ACTION_RULES = {"登记缺陷": "存在裂纹", "更换叶片": "已更换"}
NEGATIVE_ACTIONS = []

# 检查结论枚举值；除两档结论外，未提交过检查的叶片保持「待检查」。
CONCLUSION_INTACT = "完好"
CONCLUSION_CRACK = "存在裂纹"
PENDING_STATUS = "待检查"

# 裂纹允许上限按叶片长度（米）分档：长度落在 (上一档上限, 本档上限] 区间时取本档上限。
# 例如 45 米叶片允许 1 条裂纹、68 米允许 2 条、超过 80 米允许 3 条。
LENGTH_TIERS: list[tuple[float, int]] = [
    (40.0, 0),
    (60.0, 1),
    (80.0, 2),
    (float("inf"), 3),
]
# 雷击次数达到该阈值（含）时必须填写补充说明。
LIGHTNING_SUPPLEMENT_THRESHOLD = 3

# 批量补录时允许出现的字段别名，兼容不同来源表格的表头差异。
FIELD_ALIASES = {
    "叶片编号": ("叶片编号", "编号", "blade", "blade_id", "id"),
    "叶片长度": ("叶片长度", "长度", "length"),
    "裂纹数量": ("裂纹数量", "裂纹数", "裂纹", "cracks", "crack_count"),
    "雷击次数": ("雷击次数", "雷击数", "雷击", "lightning", "lightning_count"),
    "检查日期": ("检查日期", "上次检查日", "检查日", "inspect_date", "date"),
    "补充说明": ("补充说明", "说明", "雷击说明", "remark", "note"),
    "原检查结论": ("原检查结论", "原始结论", "历史结论", "检查结论", "conclusion"),
}

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _first_number(raw: Any) -> float | None:
    """从「68 米」「3 次」之类的录入值里取出数字；取不到数值返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    match = _NUMBER_RE.search(str(raw))
    return float(match.group()) if match else None


def crack_limit_for_length(length: Any) -> tuple[int | None, float | None]:
    """返回该叶片长度对应的裂纹允许上限与解析后的长度（米）；长度无法识别时上限为 None。"""
    meters = _first_number(length)
    if meters is None or meters < 0:
        return None, meters
    for upper_bound, limit in LENGTH_TIERS:
        if meters <= upper_bound:
            return limit, meters
    return LENGTH_TIERS[-1][1], meters


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """把批量补录的一条原始记录按表头别名归一成统一字段。"""
    normalized: dict[str, Any] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw and raw[alias] not in (None, ""):
                normalized[canonical] = raw[alias]
                break
    return normalized


def evaluate_inspection(
    *,
    length: Any,
    crack_count: Any,
    lightning_count: Any,
) -> dict[str, Any]:
    """按统一口径计算一次检查的结论与判定依据。

    返回字典含：conclusion（长度无法识别时为 None）、crack_limit、length_meters、
    crack_count、lightning_count、needs_supplement、basis（逐条可追溯的判定说明）。
    """
    cracks = _first_number(crack_count)
    lightning = _first_number(lightning_count)
    limit, meters = crack_limit_for_length(length)

    basis: list[str] = []
    conclusion: str | None = None

    if meters is None:
        basis.append(f"叶片长度「{length}」无法识别，未能匹配裂纹允许上限分档，结论无法判定")
    else:
        basis.append(f"叶片长度 {_format_number(meters)} 米，对应裂纹允许上限 {limit} 条")
        cracks_value = int(cracks) if cracks is not None and cracks >= 0 else 0
        if cracks is None or cracks < 0:
            basis.append("裂纹数量缺失或非法，按 0 条参与判定")
        if cracks_value > (limit or 0):
            conclusion = CONCLUSION_CRACK
            basis.append(f"裂纹数量 {cracks_value} 条，超过允许上限 {limit} 条，判定为「{conclusion}」")
        else:
            conclusion = CONCLUSION_INTACT
            basis.append(f"裂纹数量 {cracks_value} 条，未超过允许上限 {limit} 条，判定为「{conclusion}」")

    lightning_value = int(lightning) if lightning is not None and lightning >= 0 else 0
    if lightning is None or lightning < 0:
        basis.append("雷击次数缺失或非法，按 0 次参与判定")
    needs_supplement = lightning_value >= LIGHTNING_SUPPLEMENT_THRESHOLD
    if needs_supplement:
        basis.append(
            f"雷击次数 {lightning_value} 次，达到补充说明阈值 {LIGHTNING_SUPPLEMENT_THRESHOLD} 次，"
            "须填写补充说明后方可保存"
        )
    else:
        basis.append(f"雷击次数 {lightning_value} 次，未达到补充说明阈值 {LIGHTNING_SUPPLEMENT_THRESHOLD} 次")

    return {
        "conclusion": conclusion,
        "crack_limit": limit,
        "length_meters": meters,
        "crack_count": int(cracks) if cracks is not None and cracks >= 0 else 0,
        "lightning_count": lightning_value,
        "needs_supplement": needs_supplement,
        "basis": basis,
    }


def _format_number(value: float) -> str:
    """整数米不显示小数尾巴，非整数保留原精度。"""
    return str(int(value)) if value.is_integer() else f"{value:g}"


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

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if values.get("制造厂商") is not None:
            entry["制造厂商"] = values.get("制造厂商")
        entry["裂纹数量"] = 0
        entry["雷击次数"] = 0
        entry["上次检查日"] = None
        entry["检查结论"] = None
        entry["检查记录"] = []
        entry["叶片状态"] = STATUS_ORDER[0]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def submit_inspection(
        self,
        entry_id: int,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """对一片叶片提交一次检查，按统一口径落结论；重复提交只覆盖最新结论、保留历次依据。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"叶片 {entry_id} 不存在或已归档", {}

        inspect_date = str(values.get("检查日期") or date.today().isoformat()).strip()
        remark = str(values.get("补充说明") or "").strip() or None

        result = evaluate_inspection(
            length=entry.get("叶片长度"),
            crack_count=values.get("裂纹数量", 0),
            lightning_count=values.get("雷击次数", 0),
        )
        if result["conclusion"] is None:
            return None, "；".join(result["basis"]), result
        if result["needs_supplement"] and not remark:
            return (
                None,
                f"雷击次数达到 {LIGHTNING_SUPPLEMENT_THRESHOLD} 次，必须填写补充说明后才能保存",
                result,
            )

        # 只保留最新结论，历次判定依据追加进检查记录，便于追溯。
        record = {
            "序号": len(entry.get("检查记录", [])) + 1,
            "检查日期": inspect_date,
            "叶片长度": entry.get("叶片长度"),
            "裂纹数量": result["crack_count"],
            "雷击次数": result["lightning_count"],
            "裂纹允许上限": result["crack_limit"],
            "检查结论": result["conclusion"],
            "补充说明": remark,
            "判定依据": result["basis"],
            "来源": "现场提交",
        }
        entry.setdefault("检查记录", []).append(record)
        self._apply_latest(entry, record)
        return entry, f"检查已提交，结论按口径判定为「{result['conclusion']}」", result

    def list_inspections(self, entry_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        """读取一片叶片的历次检查记录（含每次的判定依据）；最新一次排在最后。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"叶片 {entry_id} 不存在或已归档"
        return list(entry.get("检查记录", [])), ""

    def backfill_inspections(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """批量补录历史检查记录：按同一套口径重算结论，与长度对不上的记录挑出来说明原因。

        每片叶片仍只保留最新结论（按检查日期覆盖），但补录的历次判定依据全部留痕。
        """
        imported: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        rows = store.rows(MODULE)
        by_code = {str(row.get("叶片编号", "")): row for row in rows}

        for index, raw in enumerate(records, start=1):
            item = _normalize_record(raw)
            code = str(item.get("叶片编号", "")).strip()
            reasons: list[str] = []

            if not code:
                reasons.append("缺少叶片编号，无法匹配叶片")
            entry = by_code.get(code) if code else None
            if code and entry is None:
                reasons.append(f"系统中找不到编号为「{code}」的叶片")

            # 长度以本次补录记录为准；为空时回退到叶片台账长度。
            length = item.get("叶片长度", entry.get("叶片长度") if entry else None)
            limit, meters = crack_limit_for_length(length)
            if limit is None:
                reasons.append(f"叶片长度「{length}」无法识别，匹配不到裂纹允许上限分档")

            crack_raw = item.get("裂纹数量", 0)
            lightning_raw = item.get("雷击次数", 0)
            cracks = _first_number(crack_raw)
            lightning = _first_number(lightning_raw)
            if cracks is None or cracks < 0:
                reasons.append(f"裂纹数量「{crack_raw}」不是有效数字")
            if lightning is None or lightning < 0:
                reasons.append(f"雷击次数「{lightning_raw}」不是有效数字")

            remark = str(item.get("补充说明") or "").strip() or None
            result = evaluate_inspection(length=length, crack_count=crack_raw, lightning_count=lightning_raw)
            if result["needs_supplement"] and not remark:
                reasons.append(
                    f"雷击次数 {result['lightning_count']} 次达到阈值 "
                    f"{LIGHTNING_SUPPLEMENT_THRESHOLD} 次，缺少补充说明"
                )

            # 原始结论与重算结论对不上的记录也要挑出来，但仍正常补录并标注。
            original = str(item.get("原检查结论", "")).strip() or None
            recalculated = result["conclusion"]
            mismatch = bool(
                original
                and recalculated
                and original not in (PENDING_STATUS,)
                and original != recalculated
            )
            if mismatch:
                reasons.append(
                    f"原始结论「{original}」与按长度/裂纹重算的结论「{recalculated}」不一致"
                )

            if reasons:
                issues.append({
                    "行号": index,
                    "叶片编号": code or None,
                    "叶片长度": item.get("叶片长度"),
                    "裂纹数量": item.get("裂纹数量"),
                    "雷击次数": item.get("雷击次数"),
                    "原检查结论": original,
                    "重算结论": recalculated,
                    "问题原因": reasons,
                    "已补录": bool(
                        entry is not None
                        and limit is not None
                        and cracks is not None
                        and lightning is not None
                        and not (result["needs_supplement"] and not remark)
                    ),
                })

            # 数值与长度都可用时，结论与历史对不上的记录仍按口径落库并标注；
            # 但无法判定（长度缺失）、关键字段非法或雷击缺补充说明的记录一律不保存，
            # 与现场提交「达到阈值必须补充说明才能保存」的口径保持一致。
            if entry is None or limit is None or cracks is None or cracks < 0 \
                    or lightning is None or lightning < 0 \
                    or (result["needs_supplement"] and not remark):
                continue

            record = {
                "序号": len(entry.get("检查记录", [])) + 1,
                "检查日期": str(item.get("检查日期") or date.today().isoformat()).strip(),
                "叶片长度": length,
                "裂纹数量": result["crack_count"],
                "雷击次数": result["lightning_count"],
                "裂纹允许上限": limit,
                "检查结论": recalculated,
                "补充说明": remark,
                "判定依据": result["basis"]
                + ([f"历史记录原结论为「{original}」，与重算结论不一致，已按重算结论覆盖"]
                   if mismatch else []),
                "来源": "批量补录",
            }
            entry.setdefault("检查记录", []).append(record)
            self._apply_latest(entry, record)
            imported.append({
                "行号": index,
                "叶片编号": code,
                "重算结论": recalculated,
                "检查日期": record["检查日期"],
            })

        return {
            "总数": len(records),
            "已补录": imported,
            "补录条数": len(imported),
            "异常条数": len(issues),
            "问题记录": issues,
        }

    @staticmethod
    def _apply_latest(entry: dict[str, Any], record: dict[str, Any]) -> None:
        """把一次检查的结论覆盖为叶片最新状态；历史依据仍保留在「检查记录」中。"""
        conclusion = record["检查结论"]
        entry["裂纹数量"] = record["裂纹数量"]
        entry["雷击次数"] = record["雷击次数"]
        entry["上次检查日"] = record["检查日期"]
        entry["叶片长度"] = record["叶片长度"]
        entry["检查结论"] = conclusion
        entry["叶片状态"] = conclusion
        entry["status"] = conclusion
        entry["abnormal"] = conclusion == CONCLUSION_CRACK
        entry["pending"] = False

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"叶片 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于叶片可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["叶片状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS or target == CONCLUSION_CRACK
        return entry, f"叶片已{action}"
