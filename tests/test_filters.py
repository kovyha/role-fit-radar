from sources.filters import passes_local_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allow(terms):
    return frozenset(terms)


def block(terms):
    return frozenset(terms)


# ---------------------------------------------------------------------------
# Allowlist behaviour
# ---------------------------------------------------------------------------

class TestAllowlist:
    def test_empty_allowlist_skips_check_passes(self):
        """Empty allowlist means no allowlist filtering — always pass."""
        assert passes_local_filter("Anything Goes Here", allow([]), block([])) is True

    def test_plain_allowlist_substring_match(self):
        """Plain allowlist term matches as a substring."""
        assert passes_local_filter("Electronic Trading Developer", allow(["trading"]), block([])) is True

    def test_plain_allowlist_no_match_blocks(self):
        """Title with no allowlist term is rejected."""
        assert passes_local_filter("Marketing Manager", allow(["trading", "quant"]), block([])) is False

    def test_multiple_terms_first_match_suffices(self):
        """Only one allowlist term needs to be present — first term matches."""
        assert passes_local_filter("Quant Analyst", allow(["quant", "trader"]), block([])) is True

    def test_multiple_terms_later_match_suffices(self):
        """Only one allowlist term needs to be present — later term matches."""
        assert passes_local_filter("Trading Analyst", allow(["quant", "trading"]), block([])) is True

    def test_plain_term_matches_within_longer_word(self):
        """Plain allowlist term is a dumb substring match — passes even inside a longer word."""
        assert passes_local_filter("Quantitative Analyst", allow(["quant"]), block([])) is True


# ---------------------------------------------------------------------------
# Blocklist — plain (substring) behaviour
# ---------------------------------------------------------------------------

class TestBlocklistPlain:
    def test_plain_blocklist_blocks_substring(self):
        """Plain blocklist term blocks when it appears anywhere in the title."""
        assert passes_local_filter("Junior Quant", allow([]), block(["junior"])) is False

    def test_plain_blocklist_no_match_passes(self):
        """Title not containing the plain blocklist term is not blocked."""
        assert passes_local_filter("Quant Developer", allow([]), block(["junior"])) is True

    def test_plain_blocklist_blocks_substring_within_word(self):
        """Plain (non-glob) term blocks even when embedded inside a longer word — contrast with glob."""
        assert passes_local_filter("Quantitative Analyst", allow([]), block(["quant"])) is False

    def test_multiple_terms_first_triggers(self):
        """Blocked when the first of multiple blocklist terms matches."""
        assert passes_local_filter("Junior Analyst", allow([]), block(["junior", "intern"])) is False

    def test_multiple_terms_second_triggers(self):
        """Blocked when a later blocklist term matches, not just the first."""
        assert passes_local_filter("Quant Intern", allow([]), block(["junior", "intern"])) is False

    def test_multiple_terms_none_match_passes(self):
        """Not blocked when none of multiple blocklist terms is present."""
        assert passes_local_filter("Quant Analyst", allow([]), block(["junior", "intern"])) is True


# ---------------------------------------------------------------------------
# Blocklist — glob-wrapped (embedded-only) behaviour
# ---------------------------------------------------------------------------

class TestBlocklistGlob:
    def test_glob_blocks_embedded_occurrence(self):
        """'*ai*' blocks 'Retail Manager' — 'ai' is embedded in 'retail' (r-e-t-a-i-l)."""
        assert passes_local_filter("Retail Manager", allow([]), block(["*ai*"])) is False

    def test_glob_permits_standalone_occurrence(self):
        """'*ai*' must NOT block 'AI Engineer' where 'ai' stands alone."""
        assert passes_local_filter("AI Engineer", allow([]), block(["*ai*"])) is True

    def test_glob_permits_no_occurrence_at_all(self):
        """Title with no 'ai' at all is not blocked by '*ai*'."""
        assert passes_local_filter("Quant Researcher", allow([]), block(["*ai*"])) is True

    def test_glob_ml_blocks_xml(self):
        """'*ml*' blocks 'XML Developer' — 'ml' is embedded in 'xml' (x-m-l)."""
        assert passes_local_filter("XML Developer", allow([]), block(["*ml*"])) is False

    def test_glob_ml_blocks_html(self):
        """'*ml*' blocks 'HTML Analyst' — 'ml' is embedded in 'html' (h-t-m-l)."""
        assert passes_local_filter("HTML Analyst", allow([]), block(["*ml*"])) is False

    def test_glob_ml_permits_standalone(self):
        """'*ml*' does NOT block 'ML Engineer' where 'ml' stands alone."""
        assert passes_local_filter("ML Engineer", allow([]), block(["*ml*"])) is True

    def test_glob_ai_blocks_training(self):
        """'*ai*' blocks 'Training Coordinator' — 'ai' is embedded in 'training'."""
        assert passes_local_filter("Training Coordinator", allow([]), block(["*ai*"])) is False

    def test_glob_ai_head_of_ai_passes(self):
        """'*ai*' does NOT block 'Head of AI' — 'ai' is standalone at end of title."""
        assert passes_local_filter("Head of AI", allow([]), block(["*ai*"])) is True

    def test_glob_standalone_at_title_start_passes(self):
        """'*ai*' does NOT block when 'ai' is standalone at the start of the title."""
        assert passes_local_filter("AI Quant Developer", allow([]), block(["*ai*"])) is True

    def test_glob_standalone_in_title_middle_passes(self):
        """'*ai*' does NOT block when 'ai' is standalone in the middle of the title."""
        assert passes_local_filter("Senior AI Researcher", allow([]), block(["*ai*"])) is True

    def test_glob_both_standalone_and_embedded_standalone_wins(self):
        """When 'ai' appears standalone AND embedded in the same title, standalone presence passes."""
        assert passes_local_filter("AI Financial Analyst", allow([]), block(["*ai*"])) is True

    def test_glob_case_insensitive_blocks_embedded(self):
        """Title is lowercased internally — uppercase embedded occurrence is still blocked."""
        assert passes_local_filter("RETAIL MANAGER", allow([]), block(["*ai*"])) is False

    def test_glob_case_insensitive_passes_standalone(self):
        """Title is lowercased internally — uppercase standalone occurrence still passes."""
        assert passes_local_filter("AI ENGINEER", allow([]), block(["*ai*"])) is True


# ---------------------------------------------------------------------------
# Combined allowlist + blocklist
# ---------------------------------------------------------------------------

class TestCombined:
    def test_passes_both(self):
        assert passes_local_filter(
            "Senior Quant Developer",
            allow(["quant", "developer"]),
            block(["intern"]),
        ) is True

    def test_fails_allowlist_even_if_blocklist_clear(self):
        assert passes_local_filter(
            "Marketing Director",
            allow(["quant"]),
            block(["intern"]),
        ) is False

    def test_fails_blocklist_even_if_allowlist_passes(self):
        assert passes_local_filter(
            "Quant Intern",
            allow(["quant"]),
            block(["intern"]),
        ) is False

    def test_glob_blocklist_does_not_clobber_valid_allowlist_match(self):
        """Title matching the allowlist with standalone 'AI' passes '*ai*' blocklist."""
        assert passes_local_filter(
            "AI Research Scientist",
            allow(["research"]),
            block(["*ai*"]),
        ) is True

    def test_glob_blocklist_blocks_embedded_even_when_allowlist_matches(self):
        """Title with allowlist match but embedded 'ai' (retail) is still blocked."""
        assert passes_local_filter(
            "Retail Quant Analyst",
            allow(["quant"]),
            block(["*ai*"]),
        ) is False
