"""
Shared utilities for OpenDocument format handlers (ODT, ODS, ODP).

Provides common font extraction and text node traversal used by all three
ODF handlers. The odt_handler variant additionally extracts fontfamily attrs.
"""


def extract_odf_fonts(doc, include_fontfamily: bool = False) -> list[str]:
    """Extract font declarations from an ODF document.

    Args:
        doc: An odfpy OpenDocument object.
        include_fontfamily: If True, also extract the 'fontfamily' attribute
            (used by ODT; ODS/ODP only use 'name').

    Returns:
        Sorted list of unique font names found.
    """
    fonts = set()
    try:
        font_decls = doc.fontfacedecls
        if font_decls:
            for child in font_decls.childNodes:
                if hasattr(child, "getAttribute"):
                    name = child.getAttribute("name")
                    if name:
                        fonts.add(name)
                    if include_fontfamily:
                        family = child.getAttribute("fontfamily")
                        if family:
                            fonts.add(family)
    except Exception:
        pass
    return sorted(fonts)


def get_odf_text(node) -> str:
    """Recursively extract text from an ODF XML node."""
    if hasattr(node, "data"):
        return node.data or ""
    parts: list[str] = []
    if hasattr(node, "childNodes"):
        for child in node.childNodes:
            if hasattr(child, "data"):
                parts.append(child.data or "")
            elif hasattr(child, "childNodes"):
                parts.append(get_odf_text(child))
    return "".join(parts)
