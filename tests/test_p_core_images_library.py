"""Images library: stock/uploaded stills and AI-generated stills in one list, two types (P-CORE UX pass)."""

from cf_platform.core.library import LIBRARY_KINDS, classify_run_keys


def test_images_library_has_stock_and_ai_stills_but_no_clips():
    assert "images" in LIBRARY_KINDS
    keys = {
        "video": ["runs/r/video/clip1.mp4", "runs/r/video/pexels_1.jpg"],
        "images": ["runs/r/images/scene_1_ai_v1.png", "runs/r/images/scene_1_ai_v2.png", "runs/r/images/upload_2.webp"],
    }
    items = classify_run_keys("images", keys, in_use={"runs/r/images/scene_1_ai_v2.png"})
    by_name = {i["name"]: i for i in items}
    assert "clip1.mp4" not in by_name
    assert by_name["pexels_1.jpg"]["facet"] == "Stock" and by_name["upload_2.webp"]["facet"] == "Stock"
    assert by_name["scene_1_ai_v1.png"]["facet"] == "AI generated" and by_name["scene_1_ai_v1.png"]["facts"].endswith("replaced")
    assert by_name["scene_1_ai_v2.png"]["facts"].endswith("in use")
