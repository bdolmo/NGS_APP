import os, re, shlex, shutil, subprocess, textwrap
from typing import List, Dict, Tuple

HELP_SECT_RE = re.compile(r'^\s*([A-Za-z].*?):\s*$')             # e.g. "optional arguments:"
USAGE_RE     = re.compile(r'^\s*usage:\s*(.+)$', re.I)
# Lines like: "  -j N, --cores N    Number of cores [default: 1]"
# or:         "  --genome GENOME    Reference genome {hg19,hg38}"
OPT_SPLIT_RE = re.compile(r'^\s{0,8}(.+?)\s{2,}(.*)$')           # left  /  right (help text)
IS_FLAG_RE   = re.compile(r'^\s*-\S')                            # starts with a dash (flag)
CHOICES_RE   = re.compile(r'\{([^}]+)\}')                        # {a,b,c}
DEFAULTS_RES = [
    re.compile(r'\[default:\s*([^\]]+)\]', re.I),
    re.compile(r'\(default:\s*([^)]+)\)', re.I),
    re.compile(r'default\s*=\s*([^\s,;]+)', re.I),
]
REQUIRED_RE  = re.compile(r'\brequired\b', re.I)

# Heuristic type inference from metavar / text
def _infer_type_from_metavar(metavar: str) -> str:
    mv = (metavar or '').strip().upper()
    if not mv:
        return 'bool'  # flags without metavar
    if any(k in mv for k in ['INT', 'N', 'NUM', 'COUNT', 'THREAD', 'CORES']):
        return 'int'
    if any(k in mv for k in ['FLOAT', 'DOUBLE', 'FP', 'ALPHA', 'BETA']):
        return 'float'
    if any(k in mv for k in ['DIR', 'DIRECTORY']):
        return 'dir'
    if any(k in mv for k in ['FILE', 'PATH', 'FASTQ', 'BAM', 'VCF', 'BED', 'YAML', 'JSON', 'TSV', 'CSV']):
        return 'file'
    if CHOICES_RE.search(mv):
        return 'choice'
    return 'string'

def _extract_default(text: str) -> str:
    if not text: return ''
    for rx in DEFAULTS_RES:
        m = rx.search(text)
        if m:
            return m.group(1).strip()
    return ''

def _extract_choices(text_or_mv: str) -> List[str]:
    m = CHOICES_RE.search(text_or_mv or '')
    if not m: return []
    return [c.strip() for c in m.group(1).split(',') if c.strip()]

def _tokenize_flags(left: str) -> Tuple[List[str], str]:
    """
    Split left column: "-j N, --cores N" -> flags ["-j", "--cores"], metavar "N"
    Also supports "--flag", "--flag VALUE", "--flag=VALUE"
    """
    # Normalize commas and multiple spaces
    parts = [p.strip() for p in left.split(',')]
    flags = []
    metavar = ''
    for part in parts:
        toks = part.split()
        if not toks: continue
        # "--flag=VALUE" style
        if '=' in toks[0] and toks[0].startswith('-'):
            flag, mv = toks[0].split('=', 1)
            flags.append(flag)
            if mv and not metavar: metavar = mv
            continue
        # "--flag VALUE" or "--flag"
        if toks[0].startswith('-'):
            flags.append(toks[0])
            # take last token as metavar if it is not a flag and is uppercase-like
            if len(toks) >= 2 and not toks[-1].startswith('-'):
                metavar = toks[-1]
        else:
            # positional (no leading dash)
            pass
    return flags, metavar

def _clean_desc(s: str) -> str:
    s = (s or '').strip()
    # Common argparse filler
    return re.sub(r'\s+', ' ', s)

def parse_help_command(command: str) -> Dict:
    """
    Execute `<command> --help` (or -h) and parse argparse-like help into our schema.
    Returns { "pipeline": {...}, "params": [...] } similar to parse_cli.
    """
    cmd = (command or '').strip()
    if not cmd:
        return {"pipeline": {}, "params": []}

    # Ensure we try with help; if the user already included -h/--help, keep it.
    toks = shlex.split(cmd)
    has_help = any(t in ('-h', '--help') or t.endswith('help') for t in toks)
    if not has_help:
        # For nextflow, prefer inserting before params only if "run" present
        if toks and toks[0] == 'nextflow':
            # nextflow run PIPELINE --help  (works)
            toks.append('--help')
        else:
            toks.append('--help')

    # Run help safely
    try:
        proc = subprocess.run(
            toks,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
            text=True,
            env={**os.environ, 'PYTHONWARNINGS': 'ignore'}
        )
        help_text = proc.stdout or ''
    except Exception as e:
        # If execution fails, return empty but keep pipeline meta from CLI parse
        base = parse_cli(command).get('pipeline', {})
        return {"pipeline": base, "params": []}

    # Parse meta via your existing CLI heuristics (interpreter/entrypoint/name)
    base_meta = parse_cli(command).get('pipeline', {})

    lines = help_text.splitlines()
    # Join wrapped description lines: collect option blocks under current section
    section = None
    params: Dict[str, Dict] = {}
    positionals: List[Dict] = []
    buf_left, buf_right = None, None

    def flush_option():
        nonlocal buf_left, buf_right, section
        if not buf_left: return
        left = buf_left
        desc = _clean_desc(buf_right or '')
        buf_left, buf_right = None, None

        if IS_FLAG_RE.match(left):
            flags, metavar = _tokenize_flags(left)
            long_name = None
            short = None
            for f in flags:
                if f.startswith('--'):
                    long_name = f
                elif f.startswith('-') and len(f) == 2:
                    short = f[1]
            # Fallback: if no long flag, use first token as name (without dashes)
            if not long_name:
                long_name = flags[0] if flags else left.strip()
            clean = long_name.lstrip('-')

            default = _extract_default(desc)
            choices = _extract_choices(desc) or _extract_choices(metavar)
            typ = _infer_type_from_metavar(metavar)
            if choices and typ != 'bool':
                typ = 'choice'
            required = bool(REQUIRED_RE.search(desc) or (section and 'required' in section.lower()))
            is_bool = (typ == 'bool')

            p = params.get(clean, {
                "name": clean,
                "short": short,
                "type": None,
                "default": "",
                "required": False,
                "is_positional": False,
                "position": None,
                "description": "",
                "choices": [],
                "group_name": section or None
            })
            # Prefer first discovered short if any
            if short and not p.get('short'):
                p['short'] = short

            p['choices'] = p.get('choices') or choices
            # Type & default
            if not p['type']:
                p['type'] = typ if typ else 'string'
            if is_bool:
                # boolean flags default to "", set True if "store_true"-like (no explicit default)
                p['default'] = True if default in ('', None) else (default.lower() in ('1','true','yes','on'))
                # normalize (UI expects True/"" pattern)
                p['default'] = True if p['default'] else ""
            else:
                if default != '':
                    p['default'] = default
            # Description
            if desc:
                p['description'] = (p['description'] + ' ' + desc).strip()
            params[clean] = p
        else:
            # positional
            name = left.strip().split()[0]
            pos = {
                "name": name,
                "short": None,
                "type": _infer_type_from_metavar(name),
                "default": "",
                "required": True,
                "is_positional": True,
                "position": len(positionals)+1,
                "description": _clean_desc(desc),
                "choices": [],
                "group_name": section or None
            }
            positionals.append(pos)

    for raw in lines:
        # Section headers
        msect = HELP_SECT_RE.match(raw)
        if msect:
            # flush pending
            flush_option()
            section = msect.group(1).strip()
            continue

        # usage line? just flush and skip
        if USAGE_RE.match(raw):
            flush_option()
            continue

        m = OPT_SPLIT_RE.match(raw)
        if m:
            # new option/positional line begins
            flush_option()
            buf_left, buf_right = m.group(1), m.group(2)
        else:
            # continuation of previous description (wrapped)
            if buf_left is not None:
                if raw.strip():
                    buf_right = (buf_right or '') + ' ' + raw.strip()

    # flush tail
    flush_option()

    # Merge positionals into params dict (keep your schema)
    for pos in positionals:
        params[pos['name']] = pos

    # Final normalization like parse_cli
    # Fill missing types/default normalization for bools
    for p in params.values():
        if p['type'] in (None, ''):
            p['type'] = 'bool' if isinstance(p.get('default'), bool) else 'string'
        if p['type'] == 'bool':
            p['default'] = True if p.get('default') else ""

    # Sort: positionals first by position, then by name
    sorted_params = sorted(
        params.values(),
        key=lambda x: (not x.get('is_positional'), x.get('position') or 0, x.get('name') or '')
    )

    return {
        "pipeline": {
            "interpreter": base_meta.get('interpreter', ''),
            "entrypoint": base_meta.get('entrypoint', ''),
            "workdir": base_meta.get('workdir', ''),
            "suggested_name": base_meta.get('suggested_name') or base_meta.get('interpreter') or ''
        },
        "params": sorted_params
    }
