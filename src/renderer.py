"""
renderer.py

Takes a Scene JSON (dict) + asset file paths, and produces a single
self-contained HTML file (CSS and JS inlined, images referenced via
file:// URIs) in generated/html/<run_id>.html.

Self-contained on purpose: Playwright loads this file directly via
file://, so there are no relative-path issues with separate .css/.js
files living in different folders.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
TEMPLATES_DIR = BASE_DIR / "templates"
ANIMATIONS_DIR = BASE_DIR / "animations"
GENERATED_HTML_DIR = BASE_DIR / "generated" / "html"

REQUIRED_ASSET_KEYS = ("background", "character", "image_a", "image_b")
OPTIONAL_ASSET_KEYS = ("character_confused",)


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required template/asset file not found: {path}")
    return path.read_text(encoding="utf-8")


def _file_uri(path_str: str) -> str:
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"Asset image not found: {p}")
    return p.resolve().as_uri()


def validate_assets(assets: dict) -> None:
    missing = [k for k in REQUIRED_ASSET_KEYS if k not in assets]
    if missing:
        raise ValueError(f"Missing required asset keys: {missing}")
    # Validate optional asset file paths too, if provided
    for key in OPTIONAL_ASSET_KEYS:
        if key in assets and assets[key]:
            _file_uri(assets[key])  # raises if the file doesn't exist


def validate_scene_json(scene_json: dict) -> None:
    if "scenes" not in scene_json or not isinstance(scene_json["scenes"], list):
        raise ValueError("Scene JSON must contain a non-empty 'scenes' list")
    if len(scene_json["scenes"]) == 0:
        raise ValueError("Scene JSON 'scenes' list is empty")
    for i, scene in enumerate(scene_json["scenes"]):
        if "text" not in scene:
            raise ValueError(f"Scene {i} is missing 'text'")


def render_html(scene_json: dict, assets: dict, run_id: str) -> Path:
    """
    assets = {
        "background":          "/abs/or/relative/path/background.png",
        "character":           "/abs/or/relative/path/character.png",   # main character (required)
        "character_confused":  "/abs/or/relative/path/confused.png",    # optional
        "image_a":             "/abs/or/relative/path/A.jpg",
        "image_b":             "/abs/or/relative/path/B.jpg",
    }
    Returns the Path to the generated HTML file.
    """
    validate_assets(assets)
    validate_scene_json(scene_json)

    GENERATED_HTML_DIR.mkdir(parents=True, exist_ok=True)

    style_css = _read(TEMPLATES_DIR / "style.css")
    character_js = _read(ANIMATIONS_DIR / "character.js")
    images_js = _read(ANIMATIONS_DIR / "images.js")
    text_js = _read(ANIMATIONS_DIR / "text.js")
    animation_js = _read(TEMPLATES_DIR / "animation.js")

    # Nhúng vào <script>: phải escape "</" nếu không 1 câu thoại chứa
    # "</script>" sẽ đóng sớm thẻ script và làm hỏng cả trang render.
    scene_json_str = json.dumps(scene_json, ensure_ascii=False).replace("</", r"<\/")

    # Optional extra characters are only rendered when their asset is provided.
    confused_img = (
        f'<img id="character-confused" class="character character--confused" '
        f'src="{_file_uri(assets["character_confused"])}" alt="confused">'
        if assets.get("character_confused")
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Comparison Video</title>
<style>
{style_css}
</style>
</head>
<body>
  <div id="stage">
    <img id="background" src="{_file_uri(assets['background'])}" alt="background">
    <img id="image-a" class="compare-image compare-image--a" src="{_file_uri(assets['image_a'])}" alt="A">
    <img id="image-b" class="compare-image compare-image--b" src="{_file_uri(assets['image_b'])}" alt="B">
    <img id="character" class="character" src="{_file_uri(assets['character'])}" alt="character">
    {confused_img}
    <div id="caption" class="caption"></div>
  </div>

  <script>
    const SCENE_DATA = {scene_json_str};
  </script>
  <script>
{character_js}
  </script>
  <script>
{images_js}
  </script>
  <script>
{text_js}
  </script>
  <script>
{animation_js}
  </script>
</body>
</html>
"""

    out_path = GENERATED_HTML_DIR / f"{run_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path