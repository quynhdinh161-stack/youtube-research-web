from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .utils import normalize_header, strip_accents


@dataclass(frozen=True)
class ClassificationRule:
    subject: str
    niche: str
    keywords: tuple[str, ...]
    weight: int = 2


# The classifier is intentionally rule-based so the tool works locally without
# another paid AI key. Specific niches appear before broad categories.
RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(
        "News & Society",
        "Police Bodycam / Crime",
        (
            "bodycam", "body camera", "police footage", "officer involved", "911 call",
            "arrest", "traffic stop", "dwi", "dui", "crime documentary", "true crime",
            "unsolved mystery", "criminal case", "cop watch", "cảnh sát", "tội phạm",
        ),
        4,
    ),
    ClassificationRule(
        "Nature & Events",
        "Natural Disasters / Extreme Weather",
        (
            "natural disaster", "extreme weather", "tornado", "waterspout", "hurricane",
            "earthquake", "tsunami", "flood", "wildfire", "landslide", "volcano",
            "storm caught on camera", "disaster caught", "thiên tai", "lốc xoáy",
            "bão", "động đất", "banjir", "gempa", "bencana alam", "taufan",
        ),
        4,
    ),
    ClassificationRule(
        "Engineering & Technology",
        "Construction / Heavy Machinery",
        (
            "construction", "heavy machinery", "excavator", "bulldozer", "dump truck",
            "road construction", "engineering", "infrastructure", "machine restoration",
            "restoration", "woodworking", "bamboo house", "wooden house", "tiny house",
            "primitive building", "build house", "máy xúc", "xây dựng", "nhà tre",
            "mini tractor", "lego tractor", "diy tractor",
        ),
        4,
    ),
    ClassificationRule(
        "Lifestyle",
        "Farming / Rural Life",
        (
            "farm", "farming", "harvest", "rural life", "village life", "countryside",
            "homestead", "forest farm", "market day", "fish pond", "raising animals",
            "single mom", "single mother", "cuộc sống nông thôn", "thu hoạch", "nông trại",
            "desa", "pedesaan", "panen", "kehidupan desa",
        ),
        4,
    ),
    ClassificationRule(
        "Food & Lifestyle",
        "Cooking / Village Food",
        (
            "cooking", "recipe", "street food", "village cooking", "traditional food",
            "baking", "cake", "food documentary", "kitchen", "nấu ăn", "ẩm thực",
            "món ăn", "masak", "resep", "makanan", "cuisine", "recette",
        ),
        4,
    ),
    ClassificationRule(
        "Travel & Culture",
        "Travel Documentary / Beautiful Places",
        (
            "travel documentary", "beautiful places", "travel guide", "walking tour",
            "4k travel", "world travel", "hidden places", "country documentary",
            "city tour", "du lịch", "địa danh", "voyage", "documentaire de voyage",
            "viaje", "lugares", "wisata", "tempat indah",
        ),
        4,
    ),
    ClassificationRule(
        "News & Society",
        "Homelessness / Social Issues",
        (
            "homeless", "homelessness", "housing crisis", "street survival", "encampment",
            "poverty", "fentanyl crisis", "mental illness", "social documentary",
            "vô gia cư", "khủng hoảng nhà ở",
        ),
        4,
    ),
    ClassificationRule(
        "Automotive",
        "Cars / Crashes / Driving",
        (
            "car crash", "idiots in cars", "dashcam", "supercar", "truck crash",
            "road rage", "driving fails", "vehicle restoration", "auto repair", "car review",
            "tai nạn xe", "ô tô", "mobil", "kecelakaan", "camion", "voiture",
        ),
        4,
    ),
    ClassificationRule(
        "Animals",
        "Wildlife / Pets",
        (
            "wildlife", "animal rescue", "pets", "dog", "cat", "monkey", "crocodile",
            "giant animals", "ocean animals", "fishing", "catch fish", "động vật",
            "khỉ", "mèo", "chó", "hewan", "satwa", "animaux",
        ),
        3,
    ),
    ClassificationRule(
        "Health & Wellness",
        "Fitness / Healthy Aging",
        (
            "workout", "exercise", "fitness", "over 50", "senior fitness", "weight loss",
            "physical therapy", "mobility", "back pain", "shoulder pain", "yoga",
            "tập luyện", "thể dục", "sức khỏe", "senam", "kebugaran",
        ),
        4,
    ),
    ClassificationRule(
        "Health & Wellness",
        "Psychology / Mindfulness",
        (
            "psychology", "mindfulness", "mental health", "self improvement", "stoicism",
            "relationships", "emotional intelligence", "healing", "meditation",
            "tâm lý", "chánh niệm", "sống tích cực",
        ),
        4,
    ),
    ClassificationRule(
        "Education & Knowledge",
        "Science / Explainers",
        (
            "science", "medical science", "research", "explainer", "how it works",
            "knowledge", "facts", "artificial intelligence", "space", "physics",
            "history explained", "khoa học", "kiến thức", "giải thích", "sains",
        ),
        3,
    ),
    ClassificationRule(
        "Technology",
        "Consumer Tech / Reviews",
        (
            "tech review", "smartphone", "laptop", "gadget", "software", "app review",
            "phone repair", "mobile service", "computer", "ai tools", "công nghệ",
            "điện thoại", "teknologi", "gadget review",
        ),
        4,
    ),
    ClassificationRule(
        "Home & Garden",
        "Gardening / DIY Home",
        (
            "garden", "gardening", "landscaping", "plants", "vegetable garden",
            "home improvement", "diy home", "wood decor", "làm vườn", "cây cảnh",
            "kebun", "jardin", "jardinage",
        ),
        4,
    ),
    ClassificationRule(
        "Motivation & Spirituality",
        "Motivation / Religion",
        (
            "motivation", "motivational", "inspiration", "faith", "religion", "bible",
            "prayer", "god", "spiritual", "sermon", "động lực", "tôn giáo", "cầu nguyện",
        ),
        3,
    ),
    ClassificationRule(
        "Entertainment",
        "Film / Media Commentary",
        (
            "film", "movie", "cinema", "celebrity", "media commentary", "video essay",
            "reaction", "story recap", "animation", "short film", "phim", "điện ảnh",
        ),
        2,
    ),
    ClassificationRule(
        "Entertainment",
        "Caught on Camera / Viral Moments",
        (
            "caught on camera", "viral moments", "unbelievable moments", "fails compilation",
            "instant karma", "crazy moments", "camera recorded", "moments caught",
            "khoảnh khắc", "camera ghi lại", "kejadian viral", "tertangkap kamera",
        ),
        4,
    ),
    ClassificationRule(
        "Gaming",
        "Video Games",
        ("gaming", "gameplay", "minecraft", "roblox", "fortnite", "gamer", "video game"),
        4,
    ),
    ClassificationRule(
        "Music",
        "Music / Performances",
        ("music", "official audio", "official video", "lyrics", "song", "concert", "cover song"),
        3,
    ),
    ClassificationRule(
        "Sports",
        "Sports",
        ("football", "soccer", "basketball", "baseball", "boxing", "sports", "highlights"),
        3,
    ),
)


TOPIC_FALLBACKS: tuple[tuple[str, str, str], ...] = (
    ("Film", "Entertainment", "Film / Media"),
    ("Entertainment", "Entertainment", "General Entertainment"),
    ("Lifestyle", "Lifestyle", "Lifestyle"),
    ("Society", "News & Society", "Society / Human Stories"),
    ("Knowledge", "Education & Knowledge", "Knowledge / Explainers"),
    ("Technology", "Technology", "Technology"),
    ("Health", "Health & Wellness", "Health"),
    ("Physical fitness", "Health & Wellness", "Fitness"),
    ("Food", "Food & Lifestyle", "Food / Cooking"),
    ("Tourism", "Travel & Culture", "Travel"),
    ("Hobby", "Lifestyle", "Hobbies"),
    ("Pets", "Animals", "Pets / Wildlife"),
    ("Music", "Music", "Music"),
    ("Sports", "Sports", "Sports"),
    ("Video game", "Gaming", "Video Games"),
)


def _normalize_text(value: Any) -> str:
    text = strip_accents(str(value or "")).lower()
    text = re.sub(r"[_|/\\]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_channel(
    channel: dict[str, Any], videos: list[dict[str, Any]] | None = None
) -> dict[str, str]:
    videos = videos or []
    recent_titles = " ".join(str(v.get("title", "")) for v in videos[:25])
    combined = " ".join(
        [
            str(channel.get("title", "")),
            str(channel.get("description", "")),
            str(channel.get("channel_keywords", "")),
            str(channel.get("topic_categories", "")),
            recent_titles,
        ]
    )
    text = _normalize_text(combined)

    best_rule: ClassificationRule | None = None
    best_score = 0
    best_matches: list[str] = []

    for rule in RULES:
        matches: list[str] = []
        score = 0
        for keyword in rule.keywords:
            normalized_keyword = _normalize_text(keyword)
            if normalized_keyword and normalized_keyword in text:
                matches.append(keyword)
                # Multiple mentions help but are capped to avoid one repeated word dominating.
                occurrences = min(text.count(normalized_keyword), 3)
                score += rule.weight + max(0, occurrences - 1)
        if score > best_score:
            best_rule = rule
            best_score = score
            best_matches = matches

    if best_rule and best_score >= 4:
        confidence = "Cao" if best_score >= 10 else "Trung bình"
        reason = ", ".join(best_matches[:6])
        return {
            "auto_subject": best_rule.subject,
            "auto_niche": best_rule.niche,
            "classification_confidence": confidence,
            "classification_reason": reason,
        }

    topic_text = _normalize_text(channel.get("topic_categories", ""))
    for topic, subject, niche in TOPIC_FALLBACKS:
        if _normalize_text(topic) in topic_text:
            return {
                "auto_subject": subject,
                "auto_niche": niche,
                "classification_confidence": "Thấp",
                "classification_reason": f"Topic YouTube: {topic}",
            }

    return {
        "auto_subject": "Khác",
        "auto_niche": "Chưa phân loại",
        "classification_confidence": "Thấp",
        "classification_reason": "Chưa đủ từ khóa công khai",
    }
