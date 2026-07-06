import re

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
        "白色飞虫",
    ]

    problem_keywords = {
        "白粉虱": "白粉虱",
        "粉白虱": "白粉虱",
        "早疫病": "番茄早疫病",
        "晚疫病": "番茄晚疫病",
        "叶霉病": "番茄叶霉病",
        "灰霉病": "番茄灰霉病",
        "蚜虫": "蚜虫",
        "红蜘蛛": "红蜘蛛",
        "脐腐病": "脐腐病",
        "缺镁": "缺镁黄化",
        "肥害": "肥害或药害",
        "药害": "肥害或药害",
    }

    def extract(self, text: str, base: dict | None = None) -> StructuredSymptoms:
        raw = dict(base or {})
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

        mentioned_problems = []
        for keyword, problem in self.problem_keywords.items():
            if keyword in text and problem not in mentioned_problems:
                mentioned_problems.append(problem)
        if (
            any(word in text for word in ["小白虫", "白色飞虫", "飞虫"])
            and "蚜虫" not in text
            and "白粉虱" not in mentioned_problems
        ):
            mentioned_problems.append("白粉虱")
        if mentioned_problems:
            raw["mentioned_problems"] = mentioned_problems

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

        growth_stage = self._extract_growth_stage(text)
        if growth_stage:
            raw["growth_stage"] = growth_stage

        days_to_harvest = self._extract_days_to_harvest(text)
        if days_to_harvest is not None:
            raw["days_to_harvest"] = days_to_harvest

        environment = self._extract_environment(text)
        if environment:
            raw["environment"] = environment

        if any(word in text for word in ["喷药", "用药", "打药"]):
            raw["recent_pesticide_use"] = "用户提到近期用药"
        if any(word in text for word in ["施肥", "追肥", "肥料"]):
            raw["recent_fertilizer_use"] = "用户提到近期施肥"

        return StructuredSymptoms(
            affected_parts=affected_parts,
            symptoms=symptoms,
            possible_categories=possible_categories,
            missing_fields=missing_fields,
            severity=severity,
            raw=raw,
        )

    def _extract_growth_stage(self, text: str) -> str | None:
        if "苗期" in text:
            return "苗期"
        if "开花" in text:
            return "开花期"
        if "结果" in text:
            return "结果期"
        if "采收" in text:
            return "采收期"
        return None

    def _extract_days_to_harvest(self, text: str) -> int | None:
        patterns = [
            r"(?:距离|离|还有|再过)?(?:预计)?采收(?:大概|约|还有|剩)?\s*(\d{1,3})\s*天",
            r"(\d{1,3})\s*天(?:后|左右|内)?采收",
            r"还有\s*(\d{1,3})\s*天",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def _extract_environment(self, text: str) -> str | None:
        if "温室" in text or "大棚" in text:
            return "设施栽培"
        if "露天" in text or "露地" in text:
            return "露地"
        if "阳台" in text or "盆栽" in text:
            return "家庭盆栽"
        return None
