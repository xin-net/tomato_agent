from app.schemas.agent import StructuredSymptoms
from app.tools.knowledge_search_tool import KnowledgeSearchTool


def test_vision_possible_problem_is_strong_ranking_signal():
    symptoms = StructuredSymptoms(
        affected_parts=["叶片"],
        symptoms=["叶片发黄"],
        possible_categories=["虫害"],
        raw={"vision_possible_problems": ["白粉虱"]},
    )

    entries = KnowledgeSearchTool().search(symptoms)

    assert entries
    assert entries[0].problem_name == "白粉虱"


def test_user_mentioned_problem_is_strong_ranking_signal():
    symptoms = StructuredSymptoms(
        affected_parts=["叶片"],
        symptoms=["叶片发黄"],
        possible_categories=[],
        raw={"mentioned_problems": ["白粉虱"]},
    )

    entries = KnowledgeSearchTool().search(symptoms)

    assert entries
    assert entries[0].problem_name == "白粉虱"
