import re

# Diccionari per convertir codis d'aminoàcids de tres lletres a una lletra
amino_dict = {
    "Ala": "A",
    "Arg": "R",
    "Asn": "N",
    "Asp": "D",
    "Cys": "C",
    "Glu": "E",
    "Gln": "Q",
    "Gly": "G",
    "His": "H",
    "Ile": "I",
    "Leu": "L",
    "Lys": "K",
    "Met": "M",
    "Phe": "F",
    "Pro": "P",
    "Ser": "S",
    "Thr": "T",
    "Trp": "W",
    "Tyr": "Y",
    "Val": "V",
    "Ter": "*",  # Stop codon
    "?": "?"
}

def _triplets_to_one_letter(s: str) -> str:
    """Convert concatenated 3-letter amino codes to one-letter codes."""
    out = []
    for i in range(0, len(s), 3):
        chunk = s[i:i+3]
        if not chunk:
            continue
        # Normalize like in JS: First upper, rest lower (e.g., 'thr'->'Thr')
        norm = chunk[:1].upper() + chunk[1:].lower()
        out.append(amino_dict.get(norm, norm))
    return "".join(out)


# 3-letter to 1-letter dictionary
AMINO_DICT = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C",
    "Glu": "E", "Gln": "Q", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P",
    "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    "Ter": "*",  # stop codon
    "?": "?"
}

# Build a regex that matches any of the 3-letter tokens (or '?'),
# case-insensitively, and will match them sequentially (e.g., "ThrAsn")
TOKENS_REGEX = re.compile(
    "(" + "|".join(sorted(map(re.escape, AMINO_DICT.keys()), key=len, reverse=True)) + ")",
    flags=re.IGNORECASE
)

def convert_long_to_short(s: str) -> str:
    """
    Convert HGVS protein changes from 3-letter AA codes to 1-letter codes.
    Works for simple subs (e.g., p.Gly12Val), frameshifts (p.Thr1556AsnfsTer3),
    ranges and del/ins/delins (e.g., p.Leu747_Pro753delinsSer), dup, Ter, and '?'.
    Keeps all HGVS operators, digits, underscores, etc.
    """

    if not isinstance(s, str) or not s:
        return s

    s = s.strip()

    # Strip wrapping brackets like [ ... ] if present
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()

    # Remove "p." prefix if present
    if s.startswith("p."):
        s = s[2:].strip()

    # Replace all 3-letter AA tokens (and '?') with 1-letter
    def repl(m: re.Match) -> str:
        tok = m.group(1)
        # Normalize like "Thr" regardless of input case
        norm = tok[:1].upper() + tok[1:].lower()
        return AMINO_DICT.get(norm, tok)

    return TOKENS_REGEX.sub(repl, s)