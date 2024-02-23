import plotly
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots
from collections import defaultdict
import re
import json

def var_location_pie(variants_dict):
    location_dict = defaultdict(dict)
    vartype_dict = defaultdict(dict)
    for var in variants_dict:
        l_list = re.split("&|,", var.consequence)
        for entry in l_list:
            if not entry in location_dict:
                location_dict[entry] = 0
            else:
                location_dict[entry] += 1
        if not var.variant_type in vartype_dict:
            vartype_dict[var.variant_type] = 0
        else:
            vartype_dict[var.variant_type] += 1
    labels_list = []
    for label in location_dict:
        labels_list.append(label)
    values_list = []
    for label in location_dict:
        values_list.append(location_dict[label])
    layout = go.Layout(width=400, height=350, margin=dict(l=0, r=0, b=0, t=0))
    fig = go.Figure(
        data=[go.Pie(labels=labels_list, values=values_list, hole=0.35, opacity=0.85)],
        layout=layout,
    )
    fig.update_layout(
        # title = "Localització/Efecte de les variants"
    )
    fig.update_traces(
        textposition="inside", marker=dict(line=dict(color="#000000", width=1))
    )
    graphJSONpie = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    labels_list = []
    for label in vartype_dict:
        labels_list.append(label)
    values_list = []
    for label in vartype_dict:
        values_list.append(vartype_dict[label])
    layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        width=270,
        height=270,
        margin=dict(l=0, r=0, b=0, t=0),
    )
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels_list,
                y=values_list,
                marker_color="rgba(35,203,167,0.5)",
                marker_line_color="black",
            )
        ],
        layout=layout,
    )
    fig.update_layout(
        # xaxis_title="Tipus",
        yaxis_title="Total",
        # title = "Tipus de variants"
    )
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)

    graphJSONbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return graphJSONpie, graphJSONbar


def cnv_plot(cnv_dict):

    x_list = []
    y_list = []
    z_list = []
    a_list = []
    b_list = []
    for roi in cnv_dict:
        x_list.append(float(roi))
        # print(cnv_dict[roi]['Coordinates'])
        cnv_ratio = float(cnv_dict[roi]["roi_log2"])
        y_list.append(cnv_ratio)
        segment_ratio = float(cnv_dict[roi]["segment_log2"])
        z_list.append(segment_ratio)
        gene = cnv_dict[roi]["Gene"]
        a_list.append(gene)
        status = cnv_dict[roi]["Status"]
        b_list.append(status)
    trace1 = go.Scatter(
        x=x_list,
        y=y_list,
        mode="markers",
        text=a_list,
        name="log2",
        marker=dict(color="lightgrey"),
    )
    trace2 = go.Scatter(x=x_list, y=z_list, mode="lines", text=a_list, name="Segment")
    # trace3 = go.Scatter(x=x_list, y=b_list, mode='markers', name='Status')
    data = [trace1, trace2]
    layout = go.Layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig = go.Figure(data=data, layout=layout)
    fig.update_traces(marker=dict(line=dict(width=1, color="grey")))
    fig.update_layout(
        xaxis_title="#Regió",
        yaxis_title="log2 ratio",
        margin=dict(l=0, r=0, b=0, t=0),
        height=350,
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)

    graphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return graphJSON


def basequal_plot(basequal_dict):

    a_list = []
    c_list = []
    t_list = []
    g_list = []

    position = []
    idx = 0
    for value in basequal_dict["A"]:
        idx += 1
        position.append(idx)

    for base in basequal_dict:
        for value in basequal_dict[base]:
            if base == "A":
                a_list.append(value)
            if base == "C":
                c_list.append(value)
            if base == "T":
                t_list.append(value)
            if base == "G":
                g_list.append(value)

    trace1 = go.Scatter(
        x=position, y=a_list, mode="lines", name="A", marker=dict(color="green")
    )
    trace2 = go.Scatter(
        x=position, y=c_list, mode="lines", name="C", marker=dict(color="blue")
    )
    trace3 = go.Scatter(
        x=position, y=t_list, mode="lines", name="T", marker=dict(color="red")
    )
    trace4 = go.Scatter(
        x=position, y=g_list, mode="lines", name="G", marker=dict(color="black")
    )

    data = [trace1, trace2, trace3, trace4]
    layout = go.Layout(
        # paper_bgcolor= 'rgba(0,0,0,0)',
        # plot_bgcolor = 'rgba(0,0,0,0)'
    )
    fig2 = go.Figure(data=data, layout=layout)
    fig2.update_traces(marker=dict(line=dict(width=1, color="grey")))
    fig2.update_layout(
        autosize=False,
        xaxis_title="Posició",
        yaxis_title="Phred score",
        margin=dict(l=0, r=0, b=0, t=0),
        width=550,
        height=250,
    )
    fig2.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig2.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)

    graphJSON = json.dumps(fig2, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSON


def adapters_plot(r1_adapters_dict, r2_adapters_dict):

    labels_r1 = []
    values_r1 = []
    for x in r1_adapters_dict:
        labels_r1.append(x)
        values_r1.append(r1_adapters_dict[x])

    labels_r2 = []
    values_r2 = []
    for x in r2_adapters_dict:
        labels_r2.append(x)
        values_r2.append(r2_adapters_dict[x])

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.25)
    fig.add_trace(go.Bar(x=values_r1, y=labels_r1, orientation="h"), row=1, col=1)
    fig.add_trace(go.Bar(x=values_r2, y=labels_r2, orientation="h"), row=1, col=2)

    fig.update_layout(
        height=300, width=1200, title_text="", margin=dict(l=0, r=0, b=0, t=0)
    )
    graphJSONhbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return graphJSONhbar


def snv_plot(snv_dict):

    ffpe_artifacts = ["C>T", "G>A"]
    labels_list = []
    values_list = []
    colors_list = []  # List to store colors for each bar

    for var1 in snv_dict:
        for var2 in snv_dict[var1]:
            label = var1 + ">" + var2
            value = snv_dict[var1][var2]
            labels_list.append(label)
            values_list.append(value)
            # Determine color based on whether it's an FFPE artifact
            if label in ffpe_artifacts:  # Assuming ffpe_artifacts is a list of artifact labels
                colors_list.append('rgba(255,0,0,0.5)')  # Red color for FFPE artifacts
            else:
                colors_list.append('rgba(35,203,167,0.5)')  # Original color for other SNVs


    layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        width=270,
        height=270,
        margin=dict(l=0, r=0, b=0, t=0),
    )

    # Rest of your code remains the same...
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels_list,
                y=values_list,
                marker_color=colors_list,  # Use the colors list here
                marker_line_color="black",
            )
        ],
        layout=layout,
    )

    fig.update_layout(
        # xaxis_title="Tipus",
        yaxis_title="Total",
        # title = "Tipus de variants"
    )
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=False)
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=False)

    graphJSONbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSONbar


def vaf_plot(vaf_list):

    layout = go.Layout(margin=dict(l=0, r=0, b=0, t=0))
    fig = go.Figure(data=[go.Histogram(x=vaf_list, histfunc="count", nbinsx=100)])
    fig.update_layout(
        # xaxis_title="Tipus",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=270,
        width=300,
        margin=dict(l=0, r=0, b=0, t=0),
        yaxis_title="Total",
        # title = "Tipus de variants"
    )
    fig.update_xaxes(range=[0, 1])
    graphJSONhist = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSONhist