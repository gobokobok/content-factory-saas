"""Sprint P-BILL-1 S4 / S5 — what the pages show and which calls they make (D123).

Static checks of the Creator page (balance, prices, history), the owner's Credits screen and
the menu entry, plus the rule that every call the page makes is one the server will answer
for the account that makes it. The behaviour behind them is tested with real sessions in
test_p_auth_billing_routes.py and was looked at in a browser against an in-memory server.
"""

import re
from pathlib import Path

from cf_platform.core.gating import basic_may

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
CREATOR_JS = (STATIC / "ui" / "creator.js").read_text()
CREATOR_HTML = (STATIC / "creator.html").read_text()
CORE_JS = (STATIC / "ui" / "core.js").read_text()
MENU_JS = (STATIC / "ui" / "super-menu.js").read_text()


class TestCreatorPage:
    def test_the_credits_entry_and_screen_exist_and_start_hidden(self):
        assert 'id="nav-credits" href="#credits"' in CREATOR_HTML
        assert re.search(r'id="nav-credits"[^>]*class="nav-btn hidden"|class="nav-btn hidden" id="nav-credits"', CREATOR_HTML)
        assert 'id="s-credits"' in CREATOR_HTML and 'id="credits-body"' in CREATOR_HTML

    def test_the_page_reads_its_own_balance_from_the_one_account_route(self):
        assert "api('/platform/billing/me')" in CREATOR_JS
        assert "tenant_id" not in CREATOR_JS.split("async function loadBilling")[1].split("const CHARGE_STATE")[0]

    def test_the_entry_and_the_prices_show_only_while_billing_is_on(self):
        load = CREATOR_JS.split("async function loadBilling")[1].split("const CHARGE_STATE")[0]
        assert "S.billing.enabled" in load and "toggle('hidden', !on)" in load
        assert "S.billing && S.billing.enabled" in CREATOR_JS.split("function priceTag")[1].split("}")[0]

    def test_each_paid_step_shows_its_price_on_the_button(self):
        for key, label in (("voice", "Generate voiceover"), ("storyboard", "Create storyboard")):
            assert f"'{label}') + priceTag('{key}')" in CREATOR_JS
        assert "priceTag('render')" in CREATOR_JS

    def test_the_balance_is_refreshed_when_a_job_ends_and_after_images_start(self):
        poll = CREATOR_JS.split("async function poll")[1].split("// ── Navigation")[0]
        assert "loadBilling()" in poll
        assert CREATOR_JS.count("loadBilling();") >= 4

    def test_the_images_dialog_shows_the_price_in_credits_before_confirming(self):
        plan = CREATOR_JS.split("async function planAssets")[1].split("async function watchImages")[0]
        assert "p.estimated_credits" in plan and "credits in your balance" in plan
        assert plan.index("estimated_credits") < plan.index("confirmBox(all ?")

    def test_a_refusal_is_shown_as_the_servers_own_sentence(self):
        assert "typeof res.data.detail === 'string' && res.data.detail" in CREATOR_JS

    def test_history_says_what_was_charged_what_is_held_and_what_was_refunded(self):
        assert "held: 'In progress', settled: 'Charged', refunded: 'Refunded'" in CREATOR_JS
        assert "credits held" in CREATOR_JS

    def test_the_markup_is_never_shown(self):
        assert "markup" not in CREATOR_JS.lower().split("async function loadbilling")[1].split("const runurl")[0].lower()


class TestOwnerScreen:
    def test_the_owner_has_a_credits_entry_under_settings_and_other_accounts_do_not(self):
        assert "settings/credits" in MENU_JS and "owner ? [CREDITS] : []" in MENU_JS
        assert "mount(container, basic, owner)" in MENU_JS
        assert "mountSuperMenu(me.effective_type !== 'super', !!me.is_owner)" in CREATOR_JS

    def test_the_screen_is_only_opened_for_the_owner(self):
        assert "id === 'credits' && isOwner() ? 'credits'" in CORE_JS
        assert "A.S.me.is_owner" in CORE_JS

    def test_it_uses_the_four_owner_routes_and_only_those(self):
        for call in ("/platform/admin/billing/users", "/platform/admin/billing/usage", "/platform/admin/billing/topup",
                     "/platform/admin/billing/refund-stale"):
            assert call in CORE_JS

    def test_top_up_asks_for_whole_credits_and_shows_the_servers_refusal(self):
        topup = CORE_JS.split("async function topup")[1].split("async function refundStale")[0]
        assert "Number.isInteger(credits)" in topup and "A.why(r)" in topup

    def test_the_actions_are_exported_for_the_markup(self):
        assert re.search(r"dlgTopup, topup, refundStale", CORE_JS)

    def test_the_screen_has_help_in_the_information_panel(self):
        assert "credits: ['Credits'" in CORE_JS and "return id === 'defaults' ? 'defaults' : id === 'credits' ? 'credits'" in CORE_JS


class TestEveryCallIsOpenToTheAccountThatMakesIt:
    def test_the_creator_page_only_calls_routes_a_basic_account_may(self):
        """billing/me is on the allow-list; the page's own calls (creator.js) are Basic's."""
        calls = set(re.findall(r"api\(\s*'(/platform/billing/[a-z/]+)'", CREATOR_JS))
        assert calls == {"/platform/billing/me"}
        assert all(basic_may("GET", c) for c in calls)

    def test_the_owner_routes_are_not_on_the_basic_allow_list(self):
        for method, path in (("GET", "/platform/admin/billing/users"), ("GET", "/platform/admin/billing/usage"),
                             ("POST", "/platform/admin/billing/topup"), ("POST", "/platform/admin/billing/refund-stale")):
            assert not basic_may(method, path)
