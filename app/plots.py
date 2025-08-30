import json
import re
from collections import Counter, namedtuple
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from plotly.utils import PlotlyJSONEncoder

# Shared default layout for most plots
BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, b=0, t=0),
)

def var_location_pie(variants):
    """
    Returns (pie_json, bar_json) where:
      - pie_json: distribution of consequences
      - bar_json: distribution of variant types
    """
    consequence_counts = Counter()
    vartype_counts      = Counter()

    for var in variants:
        # split on , or & and strip whitespace
        for entry in re.split(r"[,&]", var.consequence or ""):
            entry = entry.strip()
            if entry:
                consequence_counts[entry] += 1

        if var.variant_type:
            vartype_counts[var.variant_type] += 1

    # PIE of consequences
    pie_labels = list(consequence_counts.keys())
    pie_values = [consequence_counts[l] for l in pie_labels]

    pie_fig = go.Figure(
        data=[go.Pie(
            labels=pie_labels,
            values=pie_values,
            hole=0.35,
            marker=dict(line=dict(color="#000000", width=1))
        )],
        layout=go.Layout(width=400, height=350, **BASE_LAYOUT)
    )
    pie_fig.update_traces(textposition="inside")
    graphJSONpie = json.dumps(pie_fig, cls=PlotlyJSONEncoder)

    # BAR of variant types
    bar_labels = list(vartype_counts.keys())
    bar_values = [vartype_counts[l] for l in bar_labels]

    bar_fig = go.Figure(
        data=[go.Bar(
            x=bar_labels,
            y=bar_values,
            marker=dict(color="rgba(35,203,167,0.5)",
                        line=dict(color="black", width=1))
        )],
        layout=go.Layout(width=270, height=270, yaxis_title="Total", **BASE_LAYOUT)
    )
    bar_fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    bar_fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    graphJSONbar = json.dumps(bar_fig, cls=PlotlyJSONEncoder)

    return graphJSONpie, graphJSONbar


def snv_plot(snv_dict, ffpe_artifacts=None):
    """
    Bar plot of SNV transitions/transversions.
    Highlights ffpe_artifacts in red.
    """
    if ffpe_artifacts is None:
        ffpe_artifacts = {"C>T", "G>A"}

    # flatten dict of dicts into list of (label, count)
    items = [
        (f"{ref}>{alt}", count)
        for ref, alts in snv_dict.items()
        for alt, count in alts.items()
    ]
    labels, values = zip(*items) if items else ([], [])

    colors = [
        'rgba(255,0,0,0.5)' if lbl in ffpe_artifacts else 'rgba(35,203,167,0.5)'
        for lbl in labels
    ]

    fig = go.Figure(
        data=[go.Bar(
            x=list(labels),
            y=list(values),
            marker=dict(color=colors, line=dict(color="black", width=1))
        )],
        layout=go.Layout(width=270, height=270, yaxis_title="Total", **BASE_LAYOUT)
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    return json.dumps(fig, cls=PlotlyJSONEncoder)


def vaf_plot(vaf_list):
    """
    Histogram of VAF values (0–1).
    """
    fig = go.Figure(
        data=[go.Histogram(x=vaf_list, histfunc="count", nbinsx=100)],
        layout=go.Layout(
            width=300, height=270,
            yaxis_title="Total",
            **BASE_LAYOUT
        )
    )
    fig.update_xaxes(range=[0, 1])
    return json.dumps(fig, cls=PlotlyJSONEncoder)


def cnv_plot(cnv_dict):
    """
    Scatter + line plot of copy number ratios.
    Expects each v in cnv_dict to have:
      - "Coordinates": "chr<chrom>:<start>-<end>"
      - "roi_log2" and "segment_log2"
      - "Gene"
    """
    Entry = namedtuple("Entry", ["chrom", "region", "roi", "seg", "gene"])
    entries = []

    for v in cnv_dict.values():
        coords = v.get("Coordinates", "")
        m = re.match(r"chr([^:]+):(\d+)-(\d+)", coords, re.IGNORECASE)
        if not m:
            continue
        chrom, start_s, end_s = m.groups()
        try:
            start = int(start_s)
            end   = int(end_s)
        except ValueError:
            continue
        region_mid = (start + end) / 2

        try:
            roi = float(v.get("roi_log2", 0))
        except:
            roi = 0.0
        try:
            seg = float(v.get("segment_log2", 0))
        except:
            seg = 0.0

        gene = v.get("Gene", "")

        entries.append(Entry(chrom=chrom, region=region_mid, roi=roi, seg=seg, gene=gene))

    # sort by chromosome (numeric first) then region
    def chrom_key(c):
        try:
            return (0, int(c))
        except ValueError:
            return (1, c)

    entries.sort(key=lambda e: (chrom_key(e.chrom), e.region))

    # unpack into plotting arrays
    x_vals = [e.region for e in entries]
    y_vals = [e.roi    for e in entries]
    z_vals = [e.seg    for e in entries]
    texts  = [e.gene   for e in entries]

    fig = go.Figure(
        data=[
            go.Scatter(
                x=x_vals, y=y_vals, mode="markers", text=texts, name="ROI log2",
                marker=dict(color="lightgrey", line=dict(color="grey", width=1))
            ),
            go.Scatter(
                x=x_vals, y=z_vals, mode="lines", text=texts, name="Segment log2",
                line=dict(color="steelblue")
            ),
        ],
        layout=go.Layout(
            xaxis_title="Genomic Mid‐Point",
            yaxis_title="log₂ ratio",
            height=350,
            **BASE_LAYOUT
        )
    )

    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)

    return json.dumps(fig, cls=PlotlyJSONEncoder)


def basequal_plot(basequal_dict):
    """
    Line plot of base quality by position for A, C, G, T.
    """
    # positions inferred from length of one list
    bases = ["A", "C", "G", "T"]
    position = list(range(1, len(basequal_dict.get("A", [])) + 1))

    fig = go.Figure(layout=go.Layout(
        xaxis_title="Posició",
        yaxis_title="Phred score",
        width=550, height=250,
        **BASE_LAYOUT
    ))

    for base in bases:
        values = basequal_dict.get(base, [])
        fig.add_trace(go.Scatter(
            x=position, y=values, mode="lines", name=base
        ))

    fig.update_traces(marker=dict(line=dict(color="grey", width=1)))
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    return json.dumps(fig, cls=PlotlyJSONEncoder)


def adapters_plot(r1_adapters, r2_adapters):
    """
    Side-by-side horizontal bar charts for R1 and R2 adapter counts.
    """
    labels1, values1 = zip(*r1_adapters.items()) if r1_adapters else ([], [])
    labels2, values2 = zip(*r2_adapters.items()) if r2_adapters else ([], [])

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.25)

    fig.add_trace(go.Bar(x=list(values1), y=list(labels1), orientation="h"), row=1, col=1)
    fig.add_trace(go.Bar(x=list(values2), y=list(labels2), orientation="h"), row=1, col=2)

    fig.update_layout(
        height=300, width=1200,
        **BASE_LAYOUT
    )
    return json.dumps(fig, cls=PlotlyJSONEncoder)
