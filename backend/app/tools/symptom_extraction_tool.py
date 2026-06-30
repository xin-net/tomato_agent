from app.schemas.agent import StructuredSymptoms


class SymptomExtractionTool:
    keyword_map = {
        "下部": "下部老叶",
        "老叶": "下部老叶",
        "新叶": "新叶",
        "叶背": "叶背",
        "果实": "果实",
        "茎": "茎",
        "花": "花",
    }

    symptom_keywords = [
        "发黄",
        "黄化",
        "褐色斑点",
        "斑点",
        "同心轮纹",
        "一圈一圈",
        "霉层",
        "小白虫",
        "飞虫",
        "蚜虫",
        "红蜘蛛",
        "底部发黑",
        "萎蔫",
        "扩散",
    ]

    def extract(self, text: str, base: dict | None = None) -> StructuredSymptoms:
        affected_parts = []
        for keyword, part in self.keyword_map.items():
            if keyword in text and part not in affected_parts:
                affected_parts.append(part)

        symptoms = [keyword for keyword in self.symptom_keywords if keyword in text]
        if "一圈一圈" in symptoms and "同心轮纹" not in symptoms:
            symptoms.append("同心轮纹")

        possible_categories = []
        if any(word in text for word in ["小白虫", "飞虫", "蚜虫", "红蜘蛛"]):
            possible_categories.append("虫害")
        if any(word in text for word in ["斑点", "霉层", "同心轮纹"]):
            possible_categories.append("病害")
        if any(word in text for word in ["底部发黑", "浇水"]):
            possible_categories.append("生理性问题")

        missing_fields = []
        if not affected_parts:
            missing_fields.append("发生部位")
        if not any(stage in text for stage in ["苗期", "开花", "结果", "采收"]):
            missing_fields.append("生长阶段")
        if not any(word in text for word in ["采收", "天"]):
            missing_fields.append("距离采收时间")
        if not any(word in text for word in ["施肥", "用药", "喷药"]):
            missing_fields.append("近期施肥或用药")

        severity = None
        if any(word in text for word in ["大面积", "严重", "三株", "快速"]):
            severity = "严重"
        elif any(word in text for word in ["少量", "轻微"]):
            severity = "轻度"

        raw = base or {}
        return StructuredSymptoms(
            affected_parts=affected_parts,
            symptoms=symptoms,
            possible_categories=possible_categories,
            missing_fields=missing_fields,
            severity=severity,
            raw=raw,
        )
