import ipaddress
from urllib.parse import urlsplit, urlunsplit

import tldextract

# Use the bundled public suffix snapshot: no uncontrolled network fetch at startup.
EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


def extract_domain(website: str | None) -> tuple[str | None, str | None, str | None]:
    """Skip only blank websites; retain every other value for downstream processing.

    Prefer a registrable domain, then the hostname (including IPs and unknown
    suffixes), then the original nonblank value if parsing is impossible.
    """
    if not website or not website.strip():
        return None, None, "no_website"
    website = website.strip()
    try:
        # A bare IPv6 address needs brackets before URL parsing.
        try:
            address = ipaddress.ip_address(website)
        except ValueError:
            address = None
        if address:
            host = str(address)
            netloc = f"[{host}]" if address.version == 6 else host
            return "https://" + netloc, host, None
        url = urlsplit(website if "://" in website or website.startswith("//") else "https://" + website)
        if url.hostname:
            host = url.hostname.rstrip(".")
            if host:
                try:
                    host = host.encode("idna").decode("ascii").lower()
                except UnicodeError:
                    host = host.casefold()
                domain = EXTRACT(host).top_domain_under_public_suffix or host
                netloc = f"[{host}]" if ":" in host else host
                normalized = urlunsplit((url.scheme or "https", netloc, url.path, url.query, ""))
                return normalized, domain, None
    except (ValueError, UnicodeError):
        pass
    return website, website.casefold(), "website_domain_unparsed"
