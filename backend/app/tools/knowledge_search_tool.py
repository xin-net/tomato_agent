import re
from pathlib import Path

from app.schemas.agent import StructuredSymptoms
from app.schemas.knowledge import KnowledgeEntry


class KnowledgeSearchTool:
    def __init__(self, knowledge_dir: Path | None = None):
        self.knowledge_dir = knowledge_dir or Path(__file__).resolve().parents[1] / "knowledge" / "tomato"

    def search(self, symptoms: StructuredSymptoms, limit: int = 3) -> list[KnowledgeEntry]:
        entries = self._load_entries()
        scored = [(self._score(entry, symptoms), entry) for entry in entries]
        scored = [(score, entry) for score, entry in scored if score > 0]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def get(self, problem_name: str) -> KnowledgeEntry | None:
        for entry in self._load_entries():
            if entry.problem_name == problem_name:
                return entry
        return None

    def _load_entries(self) -> list[KnowledgeEntry]:
        entries = []
        for path in sorted(self.knowledge_dir.glob("*.md")):
            entries.append(self._parse_entry(path.read_text(encoding="utf-8")))
        return entries

    def _parse_entry(self, text: str) -> KnowledgeEntry:
        def section(name: str) -> list[str]:
            pattern = rf"## {re.escape(name)}\n(.*?)(?=\n## |\Z)"
            match = re.search(pattern, text, flags=re.S)
            if not match:
                return []
            lines = []
            for raw in match.group(1).splitlines():
                line = raw.strip()
                if line.startswith("- "):
                    lines.append(line[2:].strip())
                elif line and not line.startswith("#"):
                    lines.append(line)
            return lines

        title = text.splitlines()[0].lstrip("# ").strip()
        category = section("问题类型")
        return KnowledgeEntry(
            problem_name=title,
            category=category[0] if category else "未知",
            typical_symptoms=section("典型症状"),
            affected_parts=section("常见发生部位"),
            conditions=section("常见发生条件"),
            confusions=section("易混淆问题"),
            evidence_keywords=section("初步判断依据"),
            non_chemical_actions=section("非化学处置建议"),
            observation_points=section("观察重点"),
            escalation_conditions=section("升级条件"),
            safety_notes=section("安全提醒"),
        )

    def _score(self, entry: KnowledgeEntry, symptoms: StructuredSymptoms) -> int:
        haystack = " ".join(
            entry.typical_symptoms
            + entry.affected_parts
            + entry.conditions
            + entry.evidence_keywords
            + [entry.problem_name, entry.category]
        )
        score = 0
        for symptom in symptoms.symptoms:
            if symptom and symptom in haystack:
                score += 3
        for part in symptoms.affected_parts:
            if part and part in haystack:
                score += 2
        for category in symptoms.possible_categories:
            if category and category in entry.category:
                score += 1
        return score
