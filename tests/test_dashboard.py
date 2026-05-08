import inboxanchor.app.dashboard as dashboard


def test_dashboard_provider_options_falls_back_when_bootstrap_symbol_is_missing(monkeypatch):
    monkeypatch.delattr(dashboard.bootstrap_module, "PROVIDER_OPTIONS", raising=False)

    assert dashboard._provider_options()[0] == "fake"
    assert "gmail" in dashboard._provider_options()


def test_dashboard_provider_profile_falls_back_when_bootstrap_resolver_is_missing(monkeypatch):
    monkeypatch.delattr(dashboard.bootstrap_module, "get_provider_profile", raising=False)

    profile = dashboard._provider_profile("outlook")

    assert profile.slug == "outlook"
    assert profile.auth_mode == "app-password-or-oauth-later"


def test_dashboard_engine_runner_filters_kwargs_for_older_signatures():
    class OldEngine:
        def run(self, *, dry_run=True, limit=50):
            return {"dry_run": dry_run, "limit": limit}

    result = dashboard._run_engine_compat(
        OldEngine(),
        dry_run=False,
        limit=200,
        batch_size=500,
        confidence_threshold=0.75,
    )

    assert result == {"dry_run": False, "limit": 200}
