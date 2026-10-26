import ipaddress
from urllib.parse import urlsplit, urlunsplit

import tldextract

# Use the bundled public suffix snapshot: no uncontrolled network fetch at startup.
EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
EXCLUDED_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "youtu.be", "yelp.com", "yelp.ca", "yelp.co.uk", "google.com", "google.ca",
    "google.co.uk", "goo.gl", "g.page", "maps.app.goo.gl", "yellowpages.com",
    "yellowpages.ca", "mapquest.com", "tripadvisor.com", "foursquare.com", "linktr.ee",
    "healthline.com", "healthgrades.com", "zocdoc.com", "vitals.com", "webmd.com",
    "doximity.com", "ratemds.com", "doctoralia.com", "practo.com", "opencare.com",
    "psychologytoday.com", "massagebook.com", "chamberofcommerce.com", "bbb.org",
}


def extract_domain(website: str | None) -> tuple[str | None, str | None, str | None]:
    """Return normalized URL, registrable domain, or an explicit skip reason."""
    if not website or not website.strip():
        return None, None, "no_website"
    website = website.strip()
    try:
        url = urlsplit(website if "://" in website or website.startswith("//") else "https://" + website)
        if url.scheme not in {"", "http", "https"} or not url.hostname or url.username or url.password:
            return None, None, "invalid_website"
        _ = url.port  # Validate malformed ports even though company searches do not use ports.
        host = url.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if any(char.isspace() for char in host):
            return None, None, "invalid_website"
        try:
            ipaddress.ip_address(host)
            return None, None, "invalid_website"
        except ValueError:
            pass
        parts = EXTRACT(host)
        domain = parts.top_domain_under_public_suffix
        if not domain:
            return None, None, "invalid_website"
        normalized = urlunsplit((url.scheme or "https", host, url.path, url.query, ""))
        if domain in EXCLUDED_DOMAINS or (parts.domain == "google" and parts.suffix):
            return normalized, None, "excluded_domain"
        return normalized, domain, None
    except (ValueError, UnicodeError):
        return None, None, "invalid_website"
