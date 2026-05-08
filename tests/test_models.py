from inboxanchor.models import EmailClassification
from inboxanchor.models.email import EmailCategory, PriorityLevel


def test_email_classification_schema_round_trips():
    classification = EmailClassification(
        category=EmailCategory.work,
        priority=PriorityLevel.high,
        confidence=0.91,
        reason="Client-facing work email markers detected.",
    )

    assert classification.category == EmailCategory.work
    assert classification.priority == PriorityLevel.high
    assert classification.confidence == 0.91
