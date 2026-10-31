"""image_edit (MEDIUM) - local image processing with Pillow.

Background removal needs an ML model that is not bundled; rather than fake it the
tool reports exactly which operations are available.
"""
from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw, ImageFont
from pydantic import BaseModel, Field, model_validator

from app.core import media
from app.registry import RiskTier, ToolContext, ToolResult, tool

Operation = Literal[
    "crop", "resize", "enhance", "grayscale", "blur", "sharpen", "rotate", "watermark", "background_removal"
]


class ImageEditInput(BaseModel):
    asset_id: str = Field(description="Asset id returned by /api/media/upload")
    operation: Operation
    width: int | None = Field(default=None, ge=16, le=4096)
    height: int | None = Field(default=None, ge=16, le=4096)
    x: int | None = Field(default=None, ge=0, le=8192)
    y: int | None = Field(default=None, ge=0, le=8192)
    factor: float = Field(default=1.15, ge=0.2, le=3.0, description="enhance strength / blur radius")
    angle: int = Field(default=0, ge=-180, le=180)
    text: str = Field(default="", max_length=60)

    @model_validator(mode="after")
    def _check(self) -> "ImageEditInput":
        if self.operation == "crop" and (self.width is None or self.height is None):
            raise ValueError("crop requires width and height")
        if self.operation == "resize" and (self.width is None or self.height is None):
            raise ValueError("resize requires width and height")
        return self


@tool(
    name="image_edit",
    description=(
        "Edit an uploaded image: crop, resize, enhance, grayscale, blur, sharpen, rotate or watermark. "
        "Background removal and text-to-image require an external model and will report as unavailable."
    ),
    risk=RiskTier.MEDIUM,
    input_model=ImageEditInput,
    scopes=("media:write",),
    rate_limit_per_minute=20,
    dry_run_supported=True,
    category="media",
)
async def image_edit(ctx: ToolContext, payload: ImageEditInput) -> ToolResult:
    if payload.operation == "background_removal":
        return ToolResult(
            ok=False,
            error="Background removal needs an ML model that is not bundled. Configure a removal provider to enable it.",
        )

    loaded = media.read(ctx.user.id, payload.asset_id)
    if loaded is None:
        return ToolResult(ok=False, error="Asset not found for this account")
    _record, blob = loaded

    if ctx.dry_run:
        return ToolResult(ok=True, data={"operation": payload.operation, "dry_run": True})

    try:
        image = Image.open(io.BytesIO(blob)).convert("RGBA")
        if payload.operation == "crop":
            x, y = payload.x or 0, payload.y or 0
            image = image.crop((x, y, x + payload.width, y + payload.height))
        elif payload.operation == "resize":
            image = ImageOps.contain(image, (payload.width, payload.height))
        elif payload.operation == "enhance":
            image = ImageEnhance.Contrast(image).enhance(payload.factor)
            image = ImageEnhance.Sharpness(image).enhance(payload.factor)
        elif payload.operation == "grayscale":
            image = ImageOps.grayscale(image).convert("RGBA")
        elif payload.operation == "blur":
            image = image.filter(ImageFilter.GaussianBlur(radius=min(payload.factor * 3, 12)))
        elif payload.operation == "sharpen":
            image = image.filter(ImageFilter.SHARPEN)
        elif payload.operation == "rotate":
            image = image.rotate(payload.angle, expand=True)
        elif payload.operation == "watermark":
            if not payload.text:
                return ToolResult(ok=False, error="watermark requires text")
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            font = ImageFont.load_default(size=max(14, image.width // 30))
            margin = max(12, image.width // 40)
            draw.text((margin, image.height - margin - 20), payload.text, fill=(244, 246, 251, 190), font=font)
            image = Image.alpha_composite(image, overlay)

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        record = media.save_bytes(
            ctx.user.id,
            buffer.getvalue(),
            "image/png",
            {"source_asset": payload.asset_id, "operation": payload.operation},
        )
    except Exception as exc:
        return ToolResult(ok=False, error=f"Image processing failed: {exc}"[:300])

    return ToolResult(
        ok=True,
        data={"asset_id": record["asset_id"], "url": f"/api/media/{record['asset_id']}", "operation": payload.operation},
        message=f"{payload.operation} applied.",
    )
