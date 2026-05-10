from inboxanchor.mail_intelligence import (
    assign_single_label,
    extract_project_slug,
    is_work_dev_or_ai,
    recommend_mailbox_labels,
)


def test_assign_single_label_priority_order_security_beats_finance():
    label = assign_single_label(
        sender="security@mail.instagram.com",
        subject="New sign-in attempt and payment receipt",
        snippet="We noticed a new login to your account.",
        body="Here is your receipt, but first verify your account after this suspicious sign-in.",
    )

    assert label == "security"


def test_assign_single_label_cleanup_fallback():
    label = assign_single_label(
        sender="deals@shop.example",
        subject="Limited offer just for you",
        snippet="Save big this weekend.",
        body="Unsubscribe or manage preferences if you do not want more promo email.",
    )

    assert label == "cleanup"


def test_assign_single_label_high_value_newsletter():
    label = assign_single_label(
        sender="briefing@techcrunch.com",
        subject="TechCrunch Daily: the latest in AI",
        snippet="Your daily startup and AI briefing is here.",
        body="Daily briefing with startup, venture, and AI news. Unsubscribe anytime.",
    )

    assert label == "newsletter"


def test_assign_single_label_routine_newsletter_becomes_cleanup():
    label = assign_single_label(
        sender="newsletter@example.com",
        subject="Weekly digest",
        snippet="Top updates for the week",
        body="Newsletter digest with unsubscribe footer.",
    )

    assert label == "cleanup"


def test_assign_single_label_jobs():
    label = assign_single_label(
        sender="jobs-noreply@linkedin.com",
        subject="New jobs for your profile",
        snippet="Recommended roles and application updates.",
        body="Manage preferences or unsubscribe from these job alerts.",
    )

    assert label == "jobs"


def test_assign_single_label_needs_reply():
    label = assign_single_label(
        sender="Alex Smith <alex@company.com>",
        subject="Can you review this today?",
        snippet="Need your feedback before we send it.",
        body="Please reply with your thoughts when you get a chance.",
    )

    assert label == "needs-reply"


def test_recommend_mailbox_labels_wrapper_returns_single_item_list():
    labels = recommend_mailbox_labels(
        sender="newsletter@example.com",
        subject="Weekly digest",
        snippet="Top updates for the week",
        body="Newsletter digest with unsubscribe footer.",
        category="newsletter",
        priority="low",
    )

    assert labels == ["cleanup"]


def test_extract_project_slug_requires_explicit_project_signal():
    slug = extract_project_slug(
        sender="billing@service.com",
        subject="Invoice update",
        snippet="Your monthly invoice is ready.",
        body="Download the invoice PDF from the dashboard.",
    )

    assert slug is None


def test_is_work_dev_or_ai_does_not_match_ci_inside_normal_words():
    assert not is_work_dev_or_ai(
        sender='"Booking.com" <email.campaign@sg.booking.com>',
        subject="O calatorie la Bucuresti, ultimele preturi sunt aici",
        snippet="Vezi ultimele preturi si oferte de sezon.",
        body="Planifica o escapada si vezi ofertele disponibile.",
    )
