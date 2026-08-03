"""Shared Turkish text helpers."""

from __future__ import annotations


def tr_lower(text: str) -> str:
    """Turkish-aware lowering: İ→i and I→ı BEFORE str.lower(), which would otherwise
    produce i̇ (combining dot) and break substring matches on caps/İ-initial text."""
    return text.replace("İ", "i").replace("I", "ı").lower()


# The one ACL key every reader implicitly holds. Content carrying it is readable by
# anyone who can reach the tenant, which is why it never CONSTRAINS an audience
# intersection: a page distilled from a public source and a restricted one is
# readable by exactly the restricted source's audience, not by nobody.
PUBLIC_ACL = "public"


def restricting_audiences(key_sets: list[set[str]]) -> set[str] | None:
    """The audience that can read EVERY one of these sources.

    Returns None when the sources share no common audience (genuinely unpublishable
    together). A source whose keys include PUBLIC_ACL is readable by everyone and so
    imposes no constraint — treating it as a constraint is what made the common
    "one public source + one restricted source" case look unpublishable and invited
    an arbitrary override.
    """
    restricting = [keys for keys in key_sets if keys and PUBLIC_ACL not in keys]
    if not restricting:
        return {PUBLIC_ACL}
    common: set[str] = set.intersection(*restricting)
    return common or None
