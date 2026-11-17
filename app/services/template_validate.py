MAX_TEMPLATE_SIZE_BYTES = 80 * 1024
WARNING_THRESHOLD_BYTES = int(MAX_TEMPLATE_SIZE_BYTES * 0.9)


def html_size_bytes(html_body: str) -> int:
    return len(html_body.encode("utf-8"))


def validate_html_size(html_body: str) -> str | None:
    """Returns an error message if too large, else None."""
    size = html_size_bytes(html_body)
    if size > MAX_TEMPLATE_SIZE_BYTES:
        return (
            f"HTML body is {size / 1024:.1f} KB, which exceeds the "
            f"{MAX_TEMPLATE_SIZE_BYTES / 1024:.0f} KB limit."
        )
    return None
