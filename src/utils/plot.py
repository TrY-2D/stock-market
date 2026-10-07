from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_series_groups(
    *series_groups: Sequence[Sequence[pd.Series] | pd.Series],
    figsize: tuple[float, float] = (10, 6),
    x: pd.Index | pd.Series | None = None,
    save_path: str | Path | None = None,
) -> None:
    """Plot groups of Series in vertically stacked subplots.

    Each positional argument (a sequence of ``pd.Series``) is rendered in its
    own subplot row. Series within a group share the x-axis but are drawn on
    separate secondary y-axes (``twinx``).

    Parameters
    ----------
    *series_groups :
        One or more sequences of ``pd.Series``. Each becomes one subplot row.
    figsize : tuple[float, float]
        Figure dimensions ``(width, height)`` in inches.
    x : pd.Index | pd.Series | None
        Shared x-axis values. Defaults to each Series' own index.
    save_path : str | Path | None
        Optional path to save figure file (e.g. 'demo_plot.png').

    Raises
    ------
    ValueError
        If no series groups are provided.
    """
    n_rows = len(series_groups)
    if n_rows == 0:
        raise ValueError("At least one sequence of Series must be provided.")

    fig, axs = plt.subplots(
        n_rows,
        1,
        sharex=True,
        figsize=figsize,
        squeeze=False,
    )
    axs = axs.flatten()
    colors: list[str] = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for row_idx, series_list in enumerate(series_groups):
        ax = axs[row_idx]
        lines: list[plt.Line2D] = []
        labels: list[str] = []
        for i, series_ in enumerate(series_list):
            current_ax = ax if i == 0 else ax.twinx()
            if isinstance(series_, pd.Series):
                series_ = [series_]
            for series in series_:
                color: str = colors[len(lines) % len(colors)]
                # Offset additional right spines so y-tick labels don't overlap.
                if i > 1:
                    current_ax.spines["right"].set_position(
                        ("axes", 1 + 0.15 * (i - 1)),
                    )

                label = str(series.name) if series.name is not None else f"Series {i}"
                (line,) = current_ax.plot(
                    x if x is not None else series.index,
                    series.values,
                    color=color,
                    label=label,
                )

                x_axis = x if x is not None else series.index
                x_start = x_axis.iloc[0] if hasattr(x_axis, "iloc") else x_axis[0]
                x_end = x_axis.iloc[-1] if hasattr(x_axis, "iloc") else x_axis[-1]

                current_ax.hlines(
                    series.values[-1],
                    x_start,
                    x_end,
                    colors=color,
                    linestyles='dashed',
                    label="Current " + label,
                )
                current_ax.tick_params(axis="y", colors=color)

                lines.append(line)
                labels.append(label)

        if lines:
            ax.legend(lines, labels, loc="upper left")

    if save_path is not None:
        fig.savefig(save_path, bbox_inches="tight")
    plt.show()
