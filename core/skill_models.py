"""技能按需加载的数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    """轻量技能目录条目（稳定层）。"""

    name: str = Field(..., min_length=1, description="技能名称")
    description: str = Field(..., min_length=1, description="技能用途简介")


class SkillDocument(BaseModel):
    """技能正文文档（按需层）。"""

    name: str = Field(..., min_length=1, description="技能名称")
    content: str = Field(..., min_length=1, description="技能完整正文")
