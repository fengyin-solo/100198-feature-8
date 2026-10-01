"""叶片接口：维护叶片，覆盖提交检查、批量补录历史检查、登记缺陷、更换叶片等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.blade import BladeService

router = APIRouter(prefix="/api/blade", tags=["叶片"])

service = BladeService()

LIST_FIELDS = ["叶片编号", "所属机组", "叶片长度", "制造厂商", "上次检查日", "裂纹数量", "雷击次数", "叶片状态", "检查结论"]
STATUSES = ["待检查", "完好", "存在裂纹", "已更换"]


class BackfillPayload(BaseModel):
    """批量补录历史检查记录的入参：每条记录至少给出叶片编号。"""

    records: list[dict[str, Any]] = Field(default_factory=list)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按叶片编号检索"),
    status: str | None = Query(default=None, description="待检查、完好、存在裂纹、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按叶片编号与状态过滤叶片列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出叶片清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "blade", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条叶片明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"叶片 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/inspections")
def list_inspections(entry_id: int) -> dict[str, Any]:
    """读取一片叶片的历次检查记录与每次的判定依据。"""
    records, message = service.list_inspections(entry_id)
    if records is None:
        raise HTTPException(status_code=404, detail=message)
    return {"entry_id": entry_id, "total": len(records), "items": records}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条叶片，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="叶片已登记", entry=entry)


@router.post("/inspections/backfill", response_model=ActionResult)
def backfill_inspections(payload: BackfillPayload) -> ActionResult:
    """批量补录历史检查记录：按统一口径重算结论，挑出与长度对不上的记录并说明原因。"""
    if not payload.records:
        return ActionResult(ok=False, message="没有收到待补录的检查记录")
    report = service.backfill_inspections(payload.records)
    message = (
        f"共收到 {report['总数']} 条记录，成功补录 {report['补录条数']} 条，"
        f"挑出问题记录 {report['异常条数']} 条"
    )
    return ActionResult(ok=report["补录条数"] > 0, message=message, data=report)


@router.post("/{entry_id}/inspections", response_model=ActionResult)
def submit_inspection(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交一次叶片检查：结论由长度、裂纹数量、雷击次数按口径自动判定，不接受手工结论。"""
    entry, message, result = service.submit_inspection(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message, data=result or None)
    return ActionResult(ok=True, message=message, entry=entry, data=result)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条叶片执行登记缺陷、更换叶片；检查结论统一走检查提交接口按口径判定。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
