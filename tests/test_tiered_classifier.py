from inboxanchor.agents.classifier import ClassifierAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.core import tiered_classifier as tiered_module
from inboxanchor.core.tiered_classifier import TieredClassifier
from inboxanchor.models.email import EmailCategory, EmailClassification, PriorityLevel
from inboxanchor.sender_intelligence import MessageSignals


def _email(**updates):
    seed = build_demo_emails()[0]
    return seed.model_copy(update=updates)


def _signals(**updates):
    base = MessageSignals(
        automated=False,
        spam_like=False,
        finance_invoice=False,
        finance_receipt=False,
        job_related=False,
        job_alert=False,
        recruiter=False,
        work_dev=False,
        newsletter=False,
        high_value_newsletter=False,
        promo=False,
        social=False,
        security=False,
        deadline=False,
        reply_needed=False,
        personal=False,
        opportunity=False,
        human_like=False,
    )
    return base.__class__(**(base.__dict__ | updates))


def test_tier1_archetype_match_shopping_promo():
    classifier = TieredClassifier()
    classification, tier = classifier.classify_with_tier(
        _email(),
        sender_profile={"archetype": "shopping_promo", "archetype_confidence": 0.85},
    )

    assert classification.category == EmailCategory.promo
    assert tier == 1


def test_tier1_below_threshold_falls_through(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(promo=True, automated=True),
    )

    classification, tier = classifier.classify_with_tier(
        _email(),
        sender_profile={"archetype": "shopping_promo", "archetype_confidence": 0.60},
    )

    assert classification.category == EmailCategory.promo
    assert tier == 2


def test_tier2_security_beats_everything(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(security=True, finance_invoice=True),
    )

    classification, tier = classifier.classify_with_tier(_email())

    assert classification.category == EmailCategory.urgent
    assert classification.priority == PriorityLevel.critical
    assert tier == 2


def test_tier2_spam_like_maps_correctly(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(spam_like=True),
    )

    classification, tier = classifier.classify_with_tier(_email())

    assert classification.category == EmailCategory.spam_like
    assert classification.priority == PriorityLevel.low
    assert tier == 2


def test_tier2_human_reply_needed(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(reply_needed=True, human_like=True, automated=False),
    )

    classification, tier = classifier.classify_with_tier(_email())

    assert classification.category == EmailCategory.work
    assert classification.priority == PriorityLevel.high
    assert tier == 2


def test_tier3_llm_fallback(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(),
    )

    def fake_classify(self, email, *, intelligence=None, allow_llm=True):
        return EmailClassification(
            category=EmailCategory.unknown,
            priority=PriorityLevel.low,
            confidence=0.61,
            reason="Legacy fallback result.",
        )

    monkeypatch.setattr(ClassifierAgent, "classify", fake_classify)

    classification, tier = classifier.classify_with_tier(_email())

    assert classification.category == EmailCategory.unknown
    assert tier == 3
    assert "(tier 3" in classification.reason


def test_classify_smart_interface(monkeypatch):
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(personal=True, human_like=True),
    )

    classification = ClassifierAgent().classify_smart(_email())

    assert isinstance(classification, EmailClassification)
    assert classification.category == EmailCategory.personal


def test_archetype_unknown_falls_through(monkeypatch):
    classifier = TieredClassifier()
    monkeypatch.setattr(
        tiered_module,
        "analyze_message_signals",
        lambda email: _signals(personal=True, human_like=True),
    )

    classification, tier = classifier.classify_with_tier(
        _email(),
        sender_profile={"archetype": "unknown_type", "archetype_confidence": 0.95},
    )

    assert classification.category == EmailCategory.personal
    assert tier == 2
